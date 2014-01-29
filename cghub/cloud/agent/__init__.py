import logging
import errno
import os
import tempfile
from boto.sqs.message import RawMessage

from cghub.cloud.lib.context import Context
from cghub.cloud.lib.message import Message, UnknownVersion
from cghub.cloud.lib.util import UserError
from cghub.util.throttle import LocalThrottle

log = logging.getLogger( __name__ )


class Agent( object ):
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
        while True:
            # Do 'long' (20s) polling for messages
            messages = self.queue.get_messages( num_messages=10, # the maximum permitted
                                                wait_time_seconds=20, # ditto
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

    def update_ssh_keys( self ):
        keypairs = self.ctx.expand_keypair_globs( self.options.ec2_keypair_names )
        fingerprints = set( keypair.fingerprint for keypair in keypairs )
        if fingerprints != self.fingerprints:
            ssh_keys = set( self.download_ssh_key( keypair ) for keypair in keypairs )
            if None in ssh_keys: ssh_keys.remove( None )
            path = self.options.authorized_keys_path
            try:
                with open( path ) as f:
                    local_ssh_keys = set( l.strip( ) for l in f.readlines( ) if not l.isspace( ) )
            except IOError as e:
                if e.errno == errno.ENOENT:
                    local_ssh_keys = None
                else:
                    raise
            if local_ssh_keys != ssh_keys:
                dir_path, file_name = os.path.split( path )
                with tempfile.NamedTemporaryFile( prefix=file_name + '.',
                                                  dir=dir_path,
                                                  delete=False ) as temp_file:
                    temp_file.writelines( ssh_key + '\n' for ssh_key in ssh_keys )
                os.rename( temp_file.name, path )

            self.fingerprints = fingerprints

    def download_ssh_key( self, keypair ):
        try:
            return self.ctx.download_ssh_pubkey( keypair ).strip( )
        except UserError:
            log.warn( 'Exception while downloading SSH public key from S3.', exc_info=True )
            return None

