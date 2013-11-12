from __future__ import print_function
from StringIO import StringIO
from contextlib import closing
from functools import partial, wraps
from operator import attrgetter
import socket
import subprocess
import time
import sys
import itertools

from boto.ec2.blockdevicemapping import BlockDeviceType, BlockDeviceMapping
from boto.exception import BotoServerError, EC2ResponseError
from fabric.operations import sudo, run, get, put
from boto import logging
from fabric.api import execute
from paramiko import SSHClient
from paramiko.client import MissingHostKeyPolicy

from cghub.cloud.lib.context import Context
from cghub.cloud.lib.util import UserError, unpack_singleton, prepend_shell_script, camel_to_snake


EC2_POLLING_INTERVAL = 5


def needs_instance( method ):
    def wrapped_method( self, *args, **kwargs ):
        if self.instance_id is None:
            raise AssertionError( "Instance ID not set" )
        return method( self, *args, **kwargs )


    return wrapped_method


class fabric_task( object ):
    # FIXME: not thread-safe

    user_stack = [ ]


    def __new__( cls, user=None ):
        if callable( user ):
            return cls( )( user )
        else:
            return super( fabric_task, cls ).__new__( cls )


    def __init__( self, user=None ):
        self.user = user


    def __call__( self, function ):
        @wraps( function )
        def wrapper( box, *args, **kwargs ):
            user = box.username( ) if self.user is None else self.user
            if self.user_stack and self.user_stack[ -1 ] == user:
                return function( box, *args, **kwargs )
            else:
                self.user_stack.append( user )
                try:
                    task = partial( function, box, *args, **kwargs )
                    task.name = function.__name__
                    return box._execute_task( task, user )
                finally:
                    assert self.user_stack.pop( ) == user


        return wrapper


class Box( object ):
    """
    Manage EC2 instances. Each instance of this class represents a single virtual machine (aka
    instance) in EC2.
    """


    @classmethod
    def role( cls ):
        """
        The name of the role performed by instances of this class, or rather by the EC2 instances
        they represent.
        """
        return camel_to_snake( cls.__name__, '-' )


    def username( self ):
        """
        Returns the username for making SSH connections to the instance.
        """
        raise NotImplementedError( )


    def _base_image( self ):
        """
        Returns the default base image that boxes performing this role should be booted from
        before they are being setup

        :rtype boto.ec2.image.Image
        """
        raise NotImplementedError( )


    def setup( self, update=False ):
        """
        Create the EC2 instance represented by this box, install OS and additional packages on,
        optionally create an AMI image of it, and/or terminate it.

        :param update:
            Bring the package repository as well as any installed packages up to date, i.e. do
            what on Ubuntu is achieved by doing 'sudo apt-get update ; sudo apt-get upgrade'.
        """
        raise NotImplementedError( )


    def _ephemeral_mount_point( self ):
        """
        Returns the absolute path to the directory at which the ephemeral volume is mounted. This
        depends on the platform, and even on the author of the image.
        """
        raise NotImplementedError( )


    def __init__( self, ctx ):
        """
        Initialize an instance of this class. Before calling any of the methods on this object,
        you must ensure that a corresponding EC2 instance exists by calling either create() or
        adopt(). The former creates a new EC2 instance, the latter looks up an existing one.

        :type ctx: Context
        """
        self.ctx = ctx
        self.instance_id = None
        self.generation = None
        self.ec2_keypairs = None
        self.ec2_keypair_globs = None

        """
        The number of previous generations of this box. When an instances is booted from a
        stock AMI, generations is zero. After that instance is set up and imaged and another
        instance is booted from the resulting AMI, generations will be one.
        """
        self.ip_address = None


    def _populate_instance_creation_args( self, image, kwargs ):
        """
        Add, remove or modify the keyword arguments that will be passed to the EC2 run_instances
        request.

        :type image: boto.ec2.image.Image
        :type kwargs: dict
        """
        for root_device in ( '/dev/sda1', '/dev/sda' ):
            root_bdt = image.block_device_mapping.get( root_device )
            if root_bdt:
                root_bdt.size = 10
                bdm = kwargs.setdefault( 'block_device_map', BlockDeviceMapping( ) )
                bdm[ '/dev/sda1' ] = root_bdt
                bdm[ '/dev/sdb' ] = BlockDeviceType( ephemeral_name='ephemeral0' )
                return
        raise RuntimeError( "Can't determine root volume from image" )


    def __read_generation( self, image_id ):
        image = self.ctx.ec2.get_image( image_id )
        self.generation = int( image.tags.get( 'generation', '0' ) )


    def create( self, ec2_keypair_globs, instance_type=None, boot_image=None ):
        """
        Launch (aka 'run' in EC2 lingo) the EC2 instance represented by this box

        :param instance_type: The type of instance to create, e.g. m1.small or t1.micro.

        :type instance_type: string

        :param ec2_keypair_globs: The names of EC2 keypairs whose public key is to be to injected
         into the instance to facilitate SSH logins. For the first listed keypair a matching
         private key needs to be present locally. Note that after the agent is installed on the
         box it will

        :type ec2_keypair_globs: list of strings

        :param boot_image: the ordinal or AMI ID of the image to boot from. If None,
        the return value of self._boot_image_id() will be used.
        """
        if self.instance_id is not None:
            raise AssertionError( "Instance already adopted or created" )
        if instance_type is None:
            instance_type = self.recommended_instance_type( )

        if boot_image is not None:
            if isinstance( boot_image, int ):
                images = self.list_images( )
                try:
                    image = images[ boot_image ]
                except IndexError:
                    raise UserError( "No image with ordinal %i" % boot_image )
            else:
                image = self.ctx.ec2.get_image( boot_image )
        else:
            self._log( "Looking up default image for role %s, ... " % self.role( ),
                       newline=False )
            image = self._base_image( )
            self._log( "found %s." % image.id )

        self.__read_generation( image.id )

        ec2_keypairs = self.ctx.expand_keypair_globs( ec2_keypair_globs )
        if not ec2_keypairs:
            raise UserError( 'No matching key pairs found' )
        if ec2_keypairs[ 0 ].name != ec2_keypair_globs[ 0 ]:
            raise UserError( "The first key pair name can't be a glob." )

        self._log( 'Creating %s instance, ... ' % instance_type, newline=False )
        kwargs = dict( instance_type=instance_type,
                       key_name=ec2_keypairs[ 0 ].name,
                       placement=self.ctx.availability_zone,
                       instance_profile_arn=self.get_instance_profile_arn( ) )
        self._populate_instance_creation_args( image, kwargs )

        while True:
            try:
                reservation = self.ctx.ec2.run_instances( image.id, **kwargs )
                break
            except EC2ResponseError as e:
                if 'Invalid IAM Instance Profile' in e.error_message:
                    time.sleep( EC2_POLLING_INTERVAL )
                    pass
                else:
                    raise

        instance = unpack_singleton( reservation.instances )
        self.instance_id = instance.id
        self.ec2_keypairs = ec2_keypairs
        self.ec2_keypair_globs = ec2_keypair_globs
        self._on_instance_created( instance )
        self.__wait_ready( instance, { 'pending' }, first_boot=True )

    def _on_instance_created( self, instance ):
        """
        Invoked right after an instance was created.

        :type instance: boto.ec2.instance.Instance
        """
        self._log( 'tagging instance ... ', newline=False )
        instance.add_tag( 'Name', self.absolute_role( ) )


    def _on_instance_running( self, first_boot ):
        """
        Invoked while creating, adopting or starting an instance, right after the instance
        entered the running state.

        :param first_boot: True if this is the first time the instance enters the running state
        since its creation
        """
        pass


    def _on_instance_ready( self, first_boot ):
        """
        Invoked while creating, adopting or starting an instance, right after the instance became
        ready.

        :param first_boot: True if this is the first time the instance becomes ready since
        its creation
        """
        if first_boot:
            self.__inject_authorized_keys( self.ec2_keypairs[ 1: ] )


    def adopt( self, ordinal=None, wait_ready=True ):
        """
        Verify that the EC instance represented by this box exists and, optionally,
        wait until it is ready, i.e. that it is is running, has a public host name and can be
        connected to via SSH. If the box doesn't exist and exception will be raised.

        :param wait_ready: if True, wait for the instance to be ready
        """
        if self.instance_id is None:
            self._log( 'Adopting instance ... ', newline=False )
            instance = self.__get_instance_by_ordinal( ordinal )
            self.instance_id = instance.id
            self.__read_generation( instance.image_id )
            if wait_ready:
                self.__wait_ready( instance, from_states={ 'pending' } )
            else:
                self._log( 'done.' )


    def list( self ):
        role, instances = self.__list_instances( )
        return [ dict( role=role,
                       ordinal=ordinal,
                       id=instance.id,
                       ip=instance.ip_address,
                       created_at=instance.launch_time,
                       state=instance.state )
            for ordinal, instance in enumerate( instances ) ]


    def __list_instances( self ):
        """
        Lookup and return a list of instance performing this box' role

        :return tuple of role name and list of instances
        :rtype: string, list of boto.ec2.instance.Instance
        """
        name = self.absolute_role( )
        reservations = self.ctx.ec2.get_all_instances( filters={ 'tag:Name': name } )
        instances = [ i for r in reservations for i in r.instances if i.state != 'terminated' ]
        instances.sort( key=attrgetter( 'launch_time' ) )
        return name, instances


    def __get_instance_by_ordinal( self, ordinal ):
        """
        Get the n-th instance that performs this box' role

        :param ordinal: the index of the instance based on the ordering by launch_time

        :rtype: boto.ec2.instance.Instance
        """
        role, instances = self.__list_instances( )
        if not instances:
            raise UserError( "No instance performing role '%s'" % role )
        if ordinal is None:
            if len( instances ) > 1:
                raise UserError( "More than one instance performing role '%s'. "
                                 "Please specify an ordinal." % role )
            ordinal = 0
        try:
            return instances[ ordinal ]
        except IndexError:
            raise UserError( 'No box with ordinal %i' % ordinal )


    def _image_block_device_mapping( self ):
        """
        Returns the block device mapping to be used for the image. The base implementation
        returns None, indicating that all volumes attached to the instance should be included in
        the image.
        """
        return None


    @needs_instance
    def image( self ):
        """
        Create an image (AMI) of the EC2 instance represented by this box and return its ID.
        The EC2 instance needs to use an EBS-backed root volume. The box must be stopped or
        an exception will be raised.
        """
        self.__assert_state( 'stopped' )

        self._log( "Creating image, ... ", newline=False )
        image_name = "%s %s" % ( self.absolute_role( ), time.strftime( '%Y-%m-%d %H-%M-%S' ) )
        image_id = self.ctx.ec2.create_image(
            instance_id=self.instance_id,
            name=image_name,
            block_device_mapping=self._image_block_device_mapping( ) )
        while True:
            try:
                image = self.ctx.ec2.get_image( image_id )
                image.add_tag( 'generation', str( self.generation + 1 ) )
                self.__wait_transition( image, { 'pending' }, 'available' )
                self._log( "done. Created image %s (%s)." % ( image.id, image.name ) )
                return image_id
            except self.ctx.ec2.ResponseError as e:
                if e.error_code != 'InvalidAMIID.NotFound':
                    raise


    @needs_instance
    def stop( self ):
        """
        Stop the EC2 instance represented by this box. Stopped instances can be started later using
        :py:func:`Box.start`.
        """
        instance = self.__assert_state( 'running' )
        self._log( 'Stopping instance, ... ', newline=False )
        self.ctx.ec2.stop_instances( [ instance.id ] )
        self.__wait_transition( instance,
                                from_states={ 'running', 'stopping' },
                                to_state='stopped' )
        self._log( 'done.' )


    @needs_instance
    def start( self ):
        """
        Start the EC2 instance represented by this box
        """
        instance = self.__assert_state( 'stopped' )
        self._log( 'Starting instance, ... ', newline=False )
        self.ctx.ec2.start_instances( [ self.instance_id ] )
        # Not 100% sure why from_states includes 'stopped' but I think I noticed that there is a
        # short interval after start_instances returns during which the instance is still in
        # stopped before it goes into pending
        self.__wait_ready( instance, from_states={ 'stopped', 'pending' } )


    @needs_instance
    def reboot( self ):
        """
        Reboot the EC2 instance represented by this box. When this method returns,
        the EC2 instance represented by this object will likely have different public IP and
        hostname.
        """
        # There is reboot_instances in the API but reliably detecting the
        # state transitions is hard. So we stop and start instead.
        self.stop( )
        self.start( )


    def terminate( self, wait=True ):
        """
        Terminate the EC2 instance represented by this box.
        """
        if self.instance_id is not None:
            instance = self.get_instance( )
            if instance.state != 'terminated':
                self._log( 'Terminating instance, ... ', newline=False )
                self.ctx.ec2.terminate_instances( [ self.instance_id ] )
                if wait:
                    self.__wait_transition( instance,
                                            from_states={ 'running', 'shutting-down', 'stopped' },
                                            to_state='terminated' )
                self._log( 'done.' )


    def get_attachable_volume( self, name ):
        """
        Ensure that an EBS volume of the given name is available in the current availability zone.
        If the EBS volume exists but has been placed into a different zone, or if it is not
        available, an exception will be thrown.

        :param name: the name of the volume
        """
        name = self.ctx.absolute_name( name )
        volumes = self.ctx.ec2.get_all_volumes( filters={ 'tag:Name': name } )
        if len( volumes ) < 1: return None
        if len( volumes ) > 1: raise UserError( "More than one EBS volume named %s" % name )
        volume = volumes[ 0 ]
        if volume.status != 'available':
            raise UserError( "EBS volume %s is not available." % name )
        expected_zone = self.ctx.availability_zone
        if volume.zone != expected_zone:
            raise UserError( "Availability zone of EBS volume %s is %s but should be %s."
                             % (name, volume.zone, expected_zone ) )
        return volume


    def get_or_create_volume( self, name, size, **kwargs ):
        """
        Ensure that an EBS volume of the given name is available in the current availability zone.
        If the EBS volume exists but has been placed into a different zone, or if it is not
        available, an exception will be thrown. If the volume does not exist it will be created in
        the current zone with the specified size.

        :param name: the name of the volume
        :param size: the size to be used if it needs to be created
        :param kwargs: additional parameters for boto.connection.create_volume()
        :return: the volume
        """
        name = self.ctx.absolute_name( name )
        volume = self.get_attachable_volume( name )
        if volume is None:
            self._log( "Creating volume %s, ... " % name, newline=False )
            zone = self.ctx.availability_zone
            volume = self.ctx.ec2.create_volume( size, zone, **kwargs )
            self.__wait_volume_transition( volume, { 'creating' }, 'available' )
            volume.add_tag( 'Name', name )
            self._log( 'done.' )
            volume = self.get_attachable_volume( name )
        return volume


    @needs_instance
    def attach_volume( self, volume, device ):
        self.ctx.ec2.attach_volume( volume_id=volume.id,
                                    instance_id=self.instance_id,
                                    device=device )
        self.__wait_volume_transition( volume, { 'available' }, 'in-use' )
        if volume.attach_data.instance_id != self.instance_id:
            raise UserError( "Volume %s is not attached to this instance." )


    def _log( self, string, newline=True ):
        if newline:
            print( string, file=sys.stderr )
        else:
            sys.stderr.write( string )
            sys.stderr.flush( )


    @needs_instance
    def _execute_task( self, task, user ):
        """
        Execute the given Fabric task on the EC2 instance represented by this box
        """
        if not callable( task ): task = task( self )
        # using IP instead of host name yields more compact log lines
        host = "%s@%s" % ( user, self.ip_address )
        return execute( task, hosts=[ host ] )[ host ]


    def __assert_state( self, expected_state ):
        """
        Raises a UserError if the instance represented by this object is not in the given state.

        :param expected_state: the expected state
        :return: the instance
        :rtype: boto.ec2.instance.Instance
        """
        instance = self.get_instance( )
        actual_state = instance.state
        if actual_state != expected_state:
            raise UserError( "Expected instance state '%s' but got '%s'"
                             % (expected_state, actual_state) )
        return instance


    @needs_instance
    def get_instance( self ):
        """
        Return the EC2 instance API object represented by this box.

        :rtype: boto.ec2.instance.Instance
        """
        reservations = self.ctx.ec2.get_all_instances( self.instance_id )
        return unpack_singleton( unpack_singleton( reservations ).instances )


    def __wait_ready( self, instance, from_states, first_boot=False ):
        """
        Wait until the given instance transistions from stopped or pending state to being fully
        running and accessible via SSH.

        :type instance: boto.ec2.instance.Instance
        """
        self._log( "waiting for instance ... ", newline=False )
        self.__wait_transition( instance, from_states, 'running' )
        self._on_instance_running( first_boot )
        self._log( "running, waiting for hostname ... ", newline=False )
        self.__wait_public_ip_assigned( instance )
        self._log( "assigned, waiting for ssh ... ", newline=False )
        self.__wait_ssh_port_open( )
        self._log( "port open, testing ... ", newline=False )
        self.__wait_ssh_working( )
        self._log( "working, done." )
        self._on_instance_ready( first_boot )


    def __wait_public_ip_assigned( self, instance ):
        """
        Wait until the instances has a public IP address assigned to it.

        :type instance: boto.ec2.instance.Instance
        """
        while True:
            ip_address = instance.ip_address
            host_name = instance.public_dns_name
            if ip_address and host_name:
                self.ip_address = ip_address
                self.host_name = host_name
                return
            time.sleep( EC2_POLLING_INTERVAL )
            instance.update( )


    def __wait_ssh_port_open( self ):
        """
        Wait until the instance represented by this box is accessible via SSH.

        :return: the number of unsuccessful attempts to connect to the port before a the first
        success
        """
        for i in itertools.count( ):
            s = socket.socket( socket.AF_INET, socket.SOCK_STREAM )
            try:
                s.settimeout( EC2_POLLING_INTERVAL )
                s.connect( (self.ip_address, 22) )
                return i
            except socket.error:
                pass
            finally:
                s.close( )


    class IgnorePolicy( MissingHostKeyPolicy ):
        def missing_host_key( self, client, hostname, key ):
            pass


    def __wait_ssh_working( self ):
        while True:
            client = SSHClient( )
            try:
                client.set_missing_host_key_policy( self.IgnorePolicy( ) )
                client.connect( hostname=self.ip_address,
                                username=self.username( ),
                                timeout=EC2_POLLING_INTERVAL )
                stdin, stdout, stderr = client.exec_command( 'echo hi' )
                try:
                    line = stdout.readline( )
                    if line == 'hi\n':
                        return
                    else:
                        raise AssertionError( "Read unexpected line '%s'" % line )
                finally:
                    stdin.close( )
                    stdout.close( )
                    stderr.close( )
            except AssertionError:
                raise
            except KeyboardInterrupt:
                raise
            except Exception as e:
                logging.info( e )
            finally:
                client.close( )
            time.sleep( EC2_POLLING_INTERVAL )


    def __wait_volume_transition( self, volume, from_states, to_state ):
        """
        Same as :py:meth:`_wait_transition`, but for volumes which use 'status' instead of 'state'.
        """
        self.__wait_transition( volume, from_states, to_state, lambda volume: volume.status )


    def __wait_transition( self, resource, from_states, to_state,
                           state_getter=lambda resource: resource.state ):
        """
        Wait until the specified EC2 resource (instance, image, volume, ...) transitions from any
        of the given 'from' states to the specified 'to' state. If the instance is found in a state
        other that the to state or any of the from states, an exception will be thrown.

        :param resource: the resource to monitor
        :param from_states:
            a set of states that the resource is expected to be in before the  transition occurs
        :param to_state: the state of the resource when this method returns
        """
        state = state_getter( resource )
        while state in from_states:
            time.sleep( EC2_POLLING_INTERVAL )
            resource.update( validate=True )
            state = state_getter( resource )
        if state != to_state:
            raise AssertionError( "Expected state of %s to be '%s' but got '%s'"
                                  % ( resource, to_state, state ) )


    def _config_file_path( self, file_name, mkdir=False, role=None ):
        """
        Returns the path to a role-specific config file.

        :param file_name: the desired file name
        :param mkdir: ensure that the directies in the returned path exist
        :return: the absolute path of the config file
        """
        if role is None: role = self.role( )
        return self.ctx.config_file_path( [ role, file_name ], mkdir=mkdir )


    def _read_config_file( self, file_name, **kwargs ):
        """
        Returns the contents of the given config file. Accepts the same parameters as
        self._config_file_path() with the exception of 'mkdir' which must be omitted.
        """
        path = self._config_file_path( file_name, mkdir=False, **kwargs )
        with open( path, 'r' ) as f:
            return f.read( )


    @needs_instance
    def ssh( self, options=None, user=None, command=None ):
        if not command: command = [ ]
        if not options: options = [ ]
        subprocess.call( self._ssh_args( options, user, command ) )


    def _ssh_args( self, options, user, command ):
        if user is None:
            user = self.username( )
        args = [ 'ssh', '-A' ] + options
        # Using host name instead of IP allows for more descriptive known_hosts entries and
        # enables using wildcards like *.compute.amazonaws.com Host entries in ~/.ssh/config.
        args.append( '%s@%s' % ( user, self.host_name ) )
        args += command
        return args


    def absolute_role( self ):
        return self.ctx.absolute_name( self.role( ) )


    @fabric_task
    def __inject_authorized_keys( self, ec2_keypairs ):
        with closing( StringIO( ) ) as authorized_keys:
            get( local_path=authorized_keys, remote_path='~/.ssh/authorized_keys' )
            authorized_keys.seek( 0 )
            ssh_pubkeys = set( l.strip( ) for l in authorized_keys.readlines( ) )
            for ec2_keypair in ec2_keypairs:
                ssh_pubkey = self.ctx.download_ssh_pubkey( ec2_keypair )
                ssh_pubkeys.add( ssh_pubkey.strip( ) )
            authorized_keys.seek( 0 )
            authorized_keys.truncate( )
            authorized_keys.write( '\n'.join( ssh_pubkeys ) )
            authorized_keys.write( '\n' )
            put( local_path=authorized_keys, remote_path='~/.ssh/authorized_keys' )


    @fabric_task
    def _propagate_authorized_keys( self, user, group=None ):
        """
        Ensure that the given user account accepts SSH connections for the same keys as the
        current user. The current user must have sudo.

        :param user:
            the name of the user to propagate the current user's authorized keys to

        :param group:
            the name of the group that should own the files and directories that are created by
            this method, defaults to the default group of the given user
        """

        if group is None:
            group = run( "getent group $(getent passwd %s | cut -d : -f 4) "
                         "| cut -d : -f 1" % user )
        args = dict( src_user=self.username( ),
                     dst_user=user,
                     dst_group=group )
        sudo( 'install -d ~{dst_user}/.ssh '
              '-m 755 -o {dst_user} -g {dst_group}'.format( **args ) )
        sudo( 'install -t ~{dst_user}/.ssh ~{src_user}/.ssh/authorized_keys '
              '-m 644 -o {dst_user} -g {dst_group}'.format( **args ) )


    def recommended_instance_type( self ):
        return 't1.micro'


    def list_images( self ):
        """
        :rtype: list of boto.ec2.image.Image
        """
        image_name_pattern = '%s *' % self.absolute_role( )
        images = self.ctx.ec2.get_all_images( filters={ 'name': image_name_pattern } )
        images.sort( key=attrgetter( 'name' ) ) # that sorts by date, effectively
        return images


    @fabric_task
    def _prepend_remote_shell_script( self, script, remote_path, **put_kwargs ):
        """
        Insert the given script into the remote file at the given path before the first script
        line. See prepend_shell_script() for a definition of script line.

        :param script: the script to be inserted
        :param remote_path: the path to the file on the remote host
        :param put_kwargs: arguments passed to Fabric's put operation
        """
        with closing( StringIO( ) ) as out_file:
            with closing( StringIO( ) ) as in_file:
                get( remote_path=remote_path, local_path=in_file )
                in_file.seek( 0 )
                prepend_shell_script( '\n' + script, in_file, out_file )
            out_file.seek( 0 )
            put( remote_path=remote_path, local_path=out_file, **put_kwargs )


    def get_instance_profile_arn( self ):
        try:
            profile = self.ctx.iam.get_instance_profile( self.role( ) )
            profile = profile[
                'get_instance_profile_response' ][
                'get_instance_profile_result' ]
        except BotoServerError as e:
            if e.status == 404:
                profile = self.ctx.iam.create_instance_profile( self.role( ),
                                                                path=self.ctx.namespace )
                profile = profile[
                    'create_instance_profile_response' ][
                    'create_instance_profile_result' ]
            else:
                raise
        profile = profile[ 'instance_profile' ]
        # Boto 2.13.3.returns some unparsed 'garbage' in the roles entry but IAM only allows one
        # role per profile so we're just gonna brute force it.
        try:
            self.ctx.iam.add_role_to_instance_profile( self.role( ), 'cghub-cloud-utils' )
        except BotoServerError as e:
            if e.status != 409:
                raise
        return profile[ 'arn' ]
