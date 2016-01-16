from contextlib import contextmanager
import logging
import errno
import os
import tempfile
import pwd
import threading

from boto.sqs.message import RawMessage
from bd2k.util.throttle import LocalThrottle
import time

from cgcloud.lib.context import Context
from cgcloud.lib.message import Message, UnknownVersion
from cgcloud.lib.util import UserError

log = logging.getLogger( __name__ )


class Agent( object ):
    """
    The agent is a daemon process running on every EC2 instance of AgentBox.
    """

    def __init__( self, ctx, options ):
        """
        :type ctx: Context
        """
        super( Agent, self ).__init__( )
        self.ctx = ctx
        self.options = options
        self.fingerprints = None

        queue_name = self.ctx.to_aws_name( self.ctx.agent_queue_name )
        self.queue = self.ctx.sqs.get_queue( queue_name )
        if self.queue is None:
            # The create_queue API call handles races gracefully,
            # the conditional above is just an optimization.
            self.queue = self.ctx.sqs.create_queue( queue_name )
        self.queue.set_message_class( RawMessage )
        self.ctx.sns.subscribe_sqs_queue( ctx.agent_topic_arn, self.queue )

    def run( self ):
        throttle = LocalThrottle( min_interval=self.options.interval )
        # First call always returns immediately
        throttle.throttle( )
        # Always update keys initially
        self.update_ssh_keys( )
        self.start_metric_thread( )
        while True:
            # Do 'long' (20s) polling for messages
            messages = self.queue.get_messages( num_messages=10,  # the maximum permitted
                                                wait_time_seconds=20,  # ditto
                                                visibility_timeout=10 )
            if messages:
                # Process messages, combining multiple messages of the same type
                update_ssh_keys = False
                for sqs_message in messages:
                    try:
                        message = Message.from_sqs( sqs_message )
                    except UnknownVersion as e:
                        log.warning( 'Ignoring message with unkown version' % e.version )
                    else:
                        if message.type == Message.TYPE_UPDATE_SSH_KEYS:
                            update_ssh_keys = True
                if update_ssh_keys:
                    self.update_ssh_keys( )
                    # Greedily consume all accrued messages
                self.queue.delete_message_batch( messages )
            else:
                # Without messages, update if throttle interval has passed
                if throttle.throttle( wait=False ):
                    self.update_ssh_keys( )

    def make_dir( self, path, mode, uid, gid ):
        try:
            os.mkdir( path, mode )
        except OSError as e:
            if e.errno == errno.EEXIST:
                pass
            else:
                raise
        else:
            os.chown( path, uid, gid )

    @contextmanager
    def make_file( self, path, mode, uid, gid ):
        """
        Atomically create a file at the given path. To be used as a context manager that yields
        a file handle for writing to.
        """
        dir_path, file_name = os.path.split( path )
        with tempfile.NamedTemporaryFile( prefix=file_name + '.',
                                          dir=dir_path,
                                          delete=False ) as temp_file:
            yield temp_file
        os.chmod( temp_file.name, mode )
        os.chown( temp_file.name, uid, gid )
        os.rename( temp_file.name, path )

    def update_ssh_keys( self ):
        keypairs = self.ctx.expand_keypair_globs( self.options.ec2_keypair_names )
        fingerprints = set( keypair.fingerprint for keypair in keypairs )
        if fingerprints != self.fingerprints:
            ssh_keys = set( self.download_ssh_key( keypair ) for keypair in keypairs )
            if None in ssh_keys: ssh_keys.remove( None )

            for account in self.options.accounts:
                pw = pwd.getpwnam( account )
                dot_ssh_path = os.path.join( pw.pw_dir, '.ssh' )
                self.make_dir( dot_ssh_path, 00755, pw.pw_uid, pw.pw_gid )
                authorized_keys_path = os.path.join( dot_ssh_path, 'authorized_keys' )
                try:
                    with open( authorized_keys_path ) as f:
                        local_ssh_keys = set(
                            l.strip( ) for l in f.readlines( ) if not l.isspace( ) )
                except IOError as e:
                    if e.errno == errno.ENOENT:
                        local_ssh_keys = None
                    else:
                        raise
                if local_ssh_keys != ssh_keys:
                    with self.make_file( authorized_keys_path, 00644, pw.pw_uid,
                                         pw.pw_gid ) as authorized_keys:
                        authorized_keys.writelines( ssh_key + '\n' for ssh_key in ssh_keys )
            self.fingerprints = fingerprints

    def download_ssh_key( self, keypair ):
        try:
            return self.ctx.download_ssh_pubkey( keypair ).strip( )
        except UserError:
            log.warn( 'Exception while downloading SSH public key from S3.', exc_info=True )
            return None

    def start_metric_thread( self ):
        try:
            import psutil
        except ImportError:
            pass
        else:
            t = threading.Thread( target=self.metric_thread )
            t.daemon = True
            t.start( )

    def metric_thread( self ):
        """
        Collects memory and disk usage as percentages via psutil and adds them as Cloudwatch
        metrics. Any "3" type instance assumes ephemeral (/mnt/ephemeral) is primary storage.
        Metrics are updated every 5 minutes under the 'AWS/EC2' Namespace.

        Resource    Metric Name
        --------    -----------
        Memory      MemUsage
        Disk        DiskUsage_root or DiskUsage_<mount_point>
        """
        import psutil
        from boto.ec2 import cloudwatch
        from boto.utils import get_instance_metadata
        metadata = get_instance_metadata( )
        instance_id = metadata[ 'instance-id' ]
        region = metadata[ 'placement' ][ 'availability-zone' ][ 0:-1 ]
        while True:
            # Collect memory metrics
            memory_percent = psutil.virtual_memory( ).percent
            metrics = { 'MemUsage': memory_percent }
            # Collect disk metrics
            for partition in psutil.disk_partitions( ):
                mountpoint = partition.mountpoint
                if mountpoint == '/':
                    metrics[ 'DiskUsage_root' ] = psutil.disk_usage( mountpoint ).percent
                else:
                    metrics[ 'DiskUsage' + mountpoint.replace( '/', '_' ) ] = psutil.disk_usage(
                        mountpoint ).percent
            # Send metrics
            cw = cloudwatch.connect_to_region( region )
            try:
                cw.put_metric_data( 'CGCloud', metrics.keys( ), metrics.values( ),
                                    unit='Percent', dimensions={ "InstanceId": instance_id } )
            finally:
                cw.close( )
            cw = None
            time.sleep( 300 )
