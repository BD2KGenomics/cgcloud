from StringIO import StringIO
from abc import ABCMeta, abstractmethod
from contextlib import closing
from functools import partial, wraps
from operator import attrgetter
import socket
import subprocess
import time
import itertools

from boto.ec2.blockdevicemapping import BlockDeviceType, BlockDeviceMapping
from boto.exception import BotoServerError, EC2ResponseError
from fabric.operations import sudo, run, get, put
from boto import logging
from fabric.api import execute
from paramiko import SSHClient
from paramiko.client import MissingHostKeyPolicy
from cgcloud.lib.context import Context
from cgcloud.lib.util import UserError, unpack_singleton, camel_to_snake, ec2_keypair_fingerprint, \
    private_to_public_key

EC2_POLLING_INTERVAL = 5

log = logging.getLogger( __name__ )

# noinspection PyPep8Naming
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
            user = box.admin_account( ) if self.user is None else self.user
            if self.user_stack and self.user_stack[ -1 ] == user:
                return function( box, *args, **kwargs )
            else:
                self.user_stack.append( user )
                try:
                    task = partial( function, box, *args, **kwargs )
                    task.name = function.__name__
                    # noinspection PyProtectedMember
                    return box._execute_task( task, user )
                finally:
                    assert self.user_stack.pop( ) == user

        return wrapper


class Box( object ):
    """
    Manage EC2 instances. Each instance of this class represents a single virtual machine (aka
    instance) in EC2.
    """

    __metaclass__ = ABCMeta

    @classmethod
    def role( cls ):
        """
        The name of the role performed by instances of this class, or rather by the EC2 instances
        they represent.
        """
        return camel_to_snake( cls.__name__, '-' )

    @abstractmethod
    def admin_account( self ):
        """
        Returns the username for making SSH connections to the instance.
        """
        raise NotImplementedError( )

    @abstractmethod
    def _base_image( self, virtualization_type ):
        """
        Returns the default base image that boxes performing this role should be booted from
        before they are being setup

        :rtype boto.ec2.image.Image
        """
        raise NotImplementedError( )

    @abstractmethod
    def setup( self, **kwargs ):
        """
        Create the EC2 instance represented by this box, install OS and additional packages on,
        optionally create an AMI image of it, and/or terminate it.
        """
        raise NotImplementedError( )

    @abstractmethod
    def _ephemeral_mount_point( self ):
        """
        Returns the absolute path to the directory at which the ephemeral volume is mounted. This
        depends on the platform, and even on the author of the image.
        """
        raise NotImplementedError( )

    def _manages_keys_internally( self ):
        """
        Returns True if this box manages its own keypair, e.g. via the agent.
        """
        return False

    def __init__( self, ctx ):
        """
        Initialize an instance of this class. Before invoking any methods on this object,
        you must ensure that a corresponding EC2 instance exists by calling either create() or
        adopt().

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
        self.host_name = None

    num_ephemeral_drives_by_instance_type = {
        't2.micro': 0,
        't2.small': 0,
        't2.medium': 0,
        'm3.medium': 1,
        'm3.large': 1,
        'm3.xlarge': 2,
        'm3.2xlarge': 2,
        'c3.large': 2,
        'c3.xlarge': 2,
        'c3.2xlarge': 2,
        'c3.4xlarge': 2,
        'c3.8xlarge': 2,
        'g2.2xlarge': 1,
        'r3.large': 1,
        'r3.xlarge': 1,
        'r3.2xlarge': 1,
        'r3.4xlarge': 1,
        'r3.8xlarge': 2,
        'i2.xlarge': 1,
        'i2.2xlarge': 2,
        'i2.4xlarge': 4,
        'i2.8xlarge': 8,
        'hs1.8xlarge': 24
    }

    possible_root_devices = ( '/dev/sda1', '/dev/sda', '/dev/xvda' )

    def _populate_instance_creation_args( self, image, kwargs ):
        """
        Add, remove or modify the keyword arguments that will be passed to the EC2 run_instances
        request.

        :type image: boto.ec2.image.Image
        :type kwargs: dict
        """
        for root_device in self.possible_root_devices:
            root_bdt = image.block_device_mapping.get( root_device )
            if root_bdt:
                root_bdt.size = 10
                root_bdt.snapshot_id = None
                root_bdt.encrypted = None
                root_bdt.delete_on_termination = True
                bdm = kwargs.setdefault( 'block_device_map', BlockDeviceMapping( ) )
                bdm[ '/dev/sda1' ] = root_bdt
                instance_type_ = kwargs[ 'instance_type' ]
                num_ephemeral_drives = self.num_ephemeral_drives_by_instance_type.get(
                    instance_type_, 1 )
                for i in range( num_ephemeral_drives ):
                    device = '/dev/sd' + chr( ord( 'b' ) + i )
                    bdm[ device ] = BlockDeviceType( ephemeral_name='ephemeral%i' % i )
                return
        raise RuntimeError( "Can't determine root volume from image" )

    def __select_image( self, image_ref ):
        if isinstance( image_ref, int ):
            images = self.list_images( )
            try:
                return images[ image_ref ]
            except IndexError:
                raise UserError( "No image with ordinal %i for role %s"
                                 % ( image_ref, self.role( ) ) )
        else:
            return self.ctx.ec2.get_image( image_ref )

    default_security_groups = [ 'default' ]

    def create( self, ec2_keypair_globs, instance_type=None, image_ref=None, security_groups=None,
                virtualization_type=None, **options ):
        """
        Launch (aka 'run' in EC2 lingo) the EC2 instance represented by this box

        :param instance_type: The type of instance to create, e.g. m1.small or t1.micro.

        :type instance_type: string

        :param ec2_keypair_globs: The names of EC2 keypairs whose public key is to be to injected
         into the instance to facilitate SSH logins. For the first listed keypair a matching
         private key needs to be present locally. Note that after the agent is installed on the
         box it will

        :type ec2_keypair_globs: list of strings

        :param image_ref: the ordinal or AMI ID of the image to boot from. If None,
        the return value of self._base_image() will be used.
        """
        if self.instance_id is not None:
            raise AssertionError( "Instance already adopted or created" )
        if instance_type is None:
            instance_type = self.recommended_instance_type( )

        if virtualization_type is None:
            virtualization_type = self.__default_virtualization_type( instance_type )

        if virtualization_type not in self.supported_virtualization_types( ):
            raise RuntimeError( 'Virtualization type %s not supported by role %s' % (
                virtualization_type,
                self.role( ) ) )

        if image_ref is not None:
            image = self.__select_image( image_ref )
        else:
            log.info( "Looking up default image for role %s, ... ", self.role( ) )
            image = self._base_image( virtualization_type )
            log.info( "... found %s.", image.id )

        if image.virtualization_type != virtualization_type:
            raise RuntimeError( "Expected virtualization type %s but image only supports %s" % (
                virtualization_type,
                image.virtualization_type ) )

        if security_groups is None:
            security_groups = self.default_security_groups
        security_groups = self.ctx.ec2.get_all_security_groups(
            groupnames=security_groups,
            filters={ 'ip-permission.to-port': 22 } )
        if len( security_groups ) == 0:
            log.warn( "There is no security group that explicitly mentions port 22. "
                      "You might have trouble actually connecting with the box via SSH. "
                      "However, this is a heuristic and may be wrong." )

        str_options = dict( image.tags )
        for k, v in options.iteritems( ):
            str_options[ k ] = str( v )
        self._set_instance_options( str_options )

        ec2_keypairs = self.ctx.expand_keypair_globs( ec2_keypair_globs )
        if not ec2_keypairs:
            raise UserError( 'No matching key pairs found' )
        if ec2_keypairs[ 0 ].name != ec2_keypair_globs[ 0 ]:
            raise UserError( "The first key pair name can't be a glob." )

        log.info( 'Creating %s instance ... ', instance_type )
        kwargs = dict( instance_type=instance_type,
                       key_name=ec2_keypairs[ 0 ].name,
                       placement=self.ctx.availability_zone,
                       security_groups=security_groups,
                       instance_profile_arn=self._get_instance_profile_arn( ) )
        self._populate_instance_creation_args( image, kwargs )

        while True:
            try:
                reservation = self.ctx.ec2.run_instances( image.id, **kwargs )
                break
            except EC2ResponseError as e:
                message = e.error_message.lower( )
                if 'invalid iam instance profile' in message or 'no associated iam roles' in message:
                    time.sleep( EC2_POLLING_INTERVAL )
                else:
                    raise

        instance = unpack_singleton( reservation.instances )
        log.info( '... created %s.', instance.id )
        self.instance_id = instance.id
        self.ec2_keypairs = ec2_keypairs
        self.ec2_keypair_globs = ec2_keypair_globs
        self._on_instance_created( instance )
        self.__wait_ready( instance, { 'pending' }, first_boot=True )

    def _set_instance_options( self, options ):
        """
        Initialize optional instance attributes from the given dictionary mapping option names to
        option values. Both keys and values are strings.
        """
        self.generation = int( options.get( 'generation', '0' ) )

    def _get_instance_options( self ):
        """
        Return a dictionary mapping option names to option values. Both keys and values are strings.
        """
        return dict( generation=str( self.generation ) )

    def __write_options( self, tagged_ec2_object ):
        """
        :type tagged_ec2_object: boto.ec2.TaggedEC2Object
        """
        for k, v in self._get_instance_options( ).iteritems( ):
            self._tag_object_persistently( tagged_ec2_object, k, v )

    def _tag_object_persistently( self, tagged_ec2_object, tag_name, tag_value ):
        """
        Object tagging occasionally fails with "does not exist" types of errors so we need to
        retry a few times. Sigh ...

        :type tagged_ec2_object: boto.ec2.TaggedEC2Object
        """
        while True:
            try:
                tagged_ec2_object.add_tag( tag_name, tag_value )
            except EC2ResponseError as e:
                if e.error_code.endswith( 'NotFound' ):
                    log.info( '... trying again in %is ...' % EC2_POLLING_INTERVAL )
                    time.sleep( EC2_POLLING_INTERVAL )
                else:
                    raise
            else:
                break

    def _on_instance_created( self, instance ):
        """
        Invoked right after an instance was created.

        :type instance: boto.ec2.instance.Instance
        """
        log.info( 'Tagging instance ... ' )
        name = self.ctx.to_aws_name( self.role( ) )
        self._tag_object_persistently( instance, 'Name', name )
        self.__write_options( instance )
        log.info( ' instance tagged %s.', name )

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
        Invoked while creating, adopting or starting an instance, right after the instance was
        found to ready.

        :param first_boot: True if the instance was booted for the first time, i.e. if this is
        the first time the instance becomes ready since its creation, False if the instance was
        booted but not for the first time, None if it is not clear whether the instance was
        booted, e.g. after adoption.
        """
        if first_boot and not self._manages_keys_internally( ):
            self.__inject_authorized_keys( self.ec2_keypairs[ 1: ] )

    def adopt( self, ordinal=None, wait_ready=True ):
        """
        Verify that the EC instance represented by this box exists and, optionally,
        wait until it is ready, i.e. that it is is running, has a public host name and can be
        connected to via SSH. If the box doesn't exist and exception will be raised.

        :param wait_ready: if True, wait for the instance to be ready
        """
        if self.instance_id is None:
            log.info( 'Adopting instance ... ' )
            instance = self.__get_instance_by_ordinal( ordinal )
            self.instance_id = instance.id
            image = self.ctx.ec2.get_image( instance.image_id )
            if image is None:  # could already be deleted
                log.warn( 'Could not get image details for %s.', instance.image_id )
                options = dict( instance.tags )
            else:
                options = dict( image.tags )
                options.update( instance.tags )
            self._set_instance_options( options )

            if wait_ready:
                self.__wait_ready( instance, from_states={ 'pending' }, first_boot=None )
            else:
                log.info( '... adopted %s.', instance.id )

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
        name = self.ctx.to_aws_name( self.role( ) )
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

    def image( self ):
        """
        Create an image (AMI) of the EC2 instance represented by this box and return its ID.
        The EC2 instance needs to use an EBS-backed root volume. The box must be stopped or
        an exception will be raised.
        """
        self.__assert_state( 'stopped' )

        log.info( "Creating image ..." )
        image_name = self.ctx.to_aws_name(
            "%s_%s" % ( self.role( ), time.strftime( '%Y-%m-%d_%H-%M-%S' ) ) )
        image_id = self.ctx.ec2.create_image(
            instance_id=self.instance_id,
            name=image_name,
            block_device_mapping=self._image_block_device_mapping( ) )
        while True:
            try:
                image = self.ctx.ec2.get_image( image_id )
                self.generation += 1
                try:
                    self.__write_options( image )
                finally:
                    self.generation -= 1
                self.__wait_transition( image, { 'pending' }, 'available' )
                log.info( "... created %s (%s).", image.id, image.name )
                break
            except self.ctx.ec2.ResponseError as e:
                # FIXME: I don't think get_image can throw this, it should be outside the try
                if e.error_code != 'InvalidAMIID.NotFound':
                    raise
        # There seems to be another race condition in EC2 that causes a freshly created image to
        # not be included in queries other than by AMI ID.
        log.info( 'Checking if image %s is discoverable ...' % image_id )
        while True:
            if image_id in (_.id for _ in self.list_images( )):
                log.info( '... image now discoverable.' )
                break
            log.info( '... image %s not yet discoverable, trying again in %is ...' % (
                image_id, EC2_POLLING_INTERVAL ) )
            time.sleep( EC2_POLLING_INTERVAL )
        return image_id

    def stop( self ):
        """
        Stop the EC2 instance represented by this box. Stopped instances can be started later using
        :py:func:`Box.start`.
        """
        instance = self.__assert_state( 'running' )
        log.info( 'Stopping instance ...' )
        self.ctx.ec2.stop_instances( [ instance.id ] )
        self.__wait_transition( instance,
                                from_states={ 'running', 'stopping' },
                                to_state='stopped' )
        log.info( '... instance stopped.' )

    def start( self ):
        """
        Start the EC2 instance represented by this box
        """
        instance = self.__assert_state( 'stopped' )
        log.info( 'Starting instance, ... ' )
        self.ctx.ec2.start_instances( [ self.instance_id ] )
        # Not 100% sure why from_states includes 'stopped' but I think I noticed that there is a
        # short interval after start_instances returns during which the instance is still in
        # stopped before it goes into pending
        self.__wait_ready( instance, from_states={ 'stopped', 'pending' }, first_boot=False )

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
                log.info( 'Terminating instance ...' )
                self.ctx.ec2.terminate_instances( [ self.instance_id ] )
                if wait:
                    self.__wait_transition( instance,
                                            from_states={ 'running', 'shutting-down', 'stopped' },
                                            to_state='terminated' )
                log.info( '... instance terminated.' )

    def get_attachable_volume( self, name ):
        """
        Ensure that an EBS volume of the given name is available in the current availability zone.
        If the EBS volume exists but has been placed into a different zone, or if it is not
        available, an exception will be thrown.

        :param name: the name of the volume
        """
        name = self.ctx.absolute_name( name )
        volumes = self.ctx.ec2.get_all_volumes(
            filters={ 'tag:Name': self.ctx.to_aws_name( name ) } )
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
        available, an exception will be thrown. If the volume does not exist, it will be created
        in the current zone with the specified size.

        :param name: the name of the volume
        :param size: the size to be used if it needs to be created
        :param kwargs: additional parameters for boto.connection.create_volume()
        :return: the volume
        """
        volume = self.get_attachable_volume( name )
        if volume is None:
            log.info( "Creating volume %s, ...", name )
            zone = self.ctx.availability_zone
            volume = self.ctx.ec2.create_volume( size, zone, **kwargs )
            self.__wait_volume_transition( volume, { 'creating' }, 'available' )
            volume.add_tag( 'Name', self.ctx.to_aws_name( name ) )
            log.info( '... created %s.', volume.id )
            volume = self.get_attachable_volume( name )
        return volume

    def attach_volume( self, volume, device ):
        self.ctx.ec2.attach_volume( volume_id=volume.id,
                                    instance_id=self.instance_id,
                                    device=device )
        self.__wait_volume_transition( volume, { 'available' }, 'in-use' )
        if volume.attach_data.instance_id != self.instance_id:
            raise UserError( "Volume %s is not attached to this instance." )

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

    def get_instance( self ):
        """
        Return the EC2 instance API object represented by this box.

        :rtype: boto.ec2.instance.Instance
        """
        reservations = self.ctx.ec2.get_all_instances( self.instance_id )
        return unpack_singleton( unpack_singleton( reservations ).instances )

    def __wait_ready( self, instance, from_states, first_boot ):
        """
        Wait until the given instance transistions from stopped or pending state to being fully
        running and accessible via SSH.

        :param instance: the instance to wait for
        :type instance: boto.ec2.instance.Instance

        :param from_states: the set of states the instance may be in when this methods is
        invoked, any other state will raise an exception.
        :type from_states: set of str

         :param first_boot: True if the instance is currently booting for the first time,
         None if the instance isn't booting, False if the instance is booting but not for the
         first time.
        """
        log.info( "... waiting for instance %s ... ", instance.id )
        self.__wait_transition( instance, from_states, 'running' )
        self._on_instance_running( first_boot )
        log.info( "... instance running, waiting for hostname ... " )
        self.__wait_public_ip_assigned( instance )
        log.info( "... assigned, waiting for ssh ... " )
        self.__wait_ssh_port_open( )
        log.info( "... port open ... " )
        if first_boot is not None:
            log.info( "... testing SSH ... " )
            self.__wait_ssh_working( )
            log.info( "... SSH working ..., " )
        log.info( "... instance ready." )
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
                                username=self.admin_account( ),
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
        self.__wait_transition( volume, from_states, to_state, lambda vol: vol.status )

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

    def ssh( self, user=None, command=None ):
        if command is None: command = [ ]
        subprocess.check_call( self._ssh_args( user, command ) )

    def rsync( self, args, user=None, ssh_opts=None ):
        ssh_args = self._ssh_args( user, [ ] )
        if ssh_opts:
            ssh_args.append( ssh_opts )
        subprocess.check_call( [ 'rsync', '-e', ' '.join( ssh_args ) ] + args )

    def _ssh_args( self, user, command ):
        if user is None: user = self.admin_account( )
        # Using host name instead of IP allows for more descriptive known_hosts entries and
        # enables using wildcards like *.compute.amazonaws.com Host entries in ~/.ssh/config.
        return [ 'ssh', '%s@%s' % ( user, self.host_name ), '-A' ] + command

    @fabric_task
    def __inject_authorized_keys( self, ec2_keypairs ):
        with closing( StringIO( ) ) as authorized_keys:
            get( local_path=authorized_keys, remote_path='~/.ssh/authorized_keys' )
            authorized_keys.seek( 0 )
            ssh_pubkeys = set( l.strip( ) for l in authorized_keys.readlines( ) )
            for ec2_keypair in ec2_keypairs:
                ssh_pubkey = self.__download_ssh_pubkey( ec2_keypair )
                if ssh_pubkey: ssh_pubkeys.add( ssh_pubkey )
            authorized_keys.seek( 0 )
            authorized_keys.truncate( )
            authorized_keys.write( '\n'.join( ssh_pubkeys ) )
            authorized_keys.write( '\n' )
            put( local_path=authorized_keys, remote_path='~/.ssh/authorized_keys' )

    def __download_ssh_pubkey( self, keypair ):
        try:
            return self.ctx.download_ssh_pubkey( keypair ).strip( )
        except UserError as e:
            log.warn( 'Exception while downloading SSH public key from S3', e )
            return None

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
        args = dict( src_user=self.admin_account( ),
                     dst_user=user,
                     dst_group=group )
        sudo( 'install -d ~{dst_user}/.ssh '
              '-m 755 -o {dst_user} -g {dst_group}'.format( **args ) )
        sudo( 'install -t ~{dst_user}/.ssh ~{src_user}/.ssh/authorized_keys '
              '-m 644 -o {dst_user} -g {dst_group}'.format( **args ) )

    @classmethod
    def recommended_instance_type( cls ):
        return 't2.micro' if 'hvm' in cls.supported_virtualization_types( ) else 't1.micro'

    @classmethod
    def supported_virtualization_types( cls ):
        """
        Returns the virtualization types supported by this box in order of preference, preferred
        types first.
        """
        return [ 'hvm', 'paravirtual' ]

    def list_images( self ):
        """
        :rtype: list of boto.ec2.image.Image
        """
        image_name_pattern = self.ctx.to_aws_name( self.role( ) + '_' ) + '*'
        images = self.ctx.ec2.get_all_images( filters={ 'name': image_name_pattern } )
        images.sort( key=attrgetter( 'name' ) )  # that sorts by date, effectively
        return images

    @abstractmethod
    def _register_init_command( self, cmd ):
        """
        Register a shell command to be executed towards the end of system initialization
        """
        raise NotImplementedError( )

    def _get_instance_profile_arn( self ):
        role_name, policies = self._get_iam_ec2_role( )
        aws_role_name = self.ctx.setup_iam_ec2_role( role_name, policies )
        aws_instance_profile_name = self.ctx.to_aws_name( self.role( ) )
        try:
            profile = self.ctx.iam.get_instance_profile( aws_instance_profile_name )
            profile = profile.get_instance_profile_response.get_instance_profile_result
        except BotoServerError as e:
            if e.status == 404:
                profile = self.ctx.iam.create_instance_profile( aws_instance_profile_name )
                profile = profile.create_instance_profile_response.create_instance_profile_result
            else:
                raise
        profile = profile.instance_profile
        profile_arn = profile.arn
        # Note that Boto does not correctly parse the result from get/create_instance_profile.
        # The 'roles' field should be an instance of ListElement, whereas it currently is a
        # simple, dict-like Element. We can check a dict-like element for size but since all
        # children have the same name -- 'member' in this case -- the dictionary will always have
        # just one entry. Luckily, IAM currently only supports one role per profile so this Boto
        # bug does not affect us much.
        if len( profile.roles ) > 1:
            raise RuntimeError( 'Did not expect profile to contain more than one role' )
        elif len( profile.roles ) == 1:
            # this should be profile.roles[0].role_name
            if profile.roles.member.role_name == aws_role_name:
                return profile_arn
            else:
                self.ctx.iam.remove_role_from_instance_profile( aws_instance_profile_name,
                                                                profile.roles.member.role_name )
        self.ctx.iam.add_role_to_instance_profile( aws_instance_profile_name, aws_role_name )

        return profile_arn

    role_prefix = 'cgcloud'

    def _role_arn( self, role_prefix="" ):
        """
        Returns the ARN for roles in the given account that have the give prefix
        """
        aws_role_prefix = self.ctx.to_aws_name( role_prefix + Box.role_prefix )
        return "arn:aws:iam::%s:role/%s*" % ( self.ctx.account, aws_role_prefix )

    def _get_iam_ec2_role( self ):
        return self.role_prefix, { }

    # http://aws.amazon.com/amazon-linux-ami/instance-type-matrix/
    #
    virtualization_types = [ 'paravirtual', 'hvm' ]
    paravirtual_families = [ 'm1', 'c1', 'm2', 't1' ]

    def __default_virtualization_type( self, instance_type ):
        family = instance_type.split( '.', 2 )[ 0 ].lower( )
        return 'paravirtual' if family in self.paravirtual_families else 'hvm'

    def delete_image( self, image_ref, wait=True, delete_snapshot=True ):
        image = self.__select_image( image_ref )
        image_id = image.id
        log.info( "Deregistering image %s", image_id )
        image.deregister( )
        if wait:
            log.info( "Waiting for deregistration to finalize ..." )
            while True:
                if self.ctx.ec2.get_image( image_id ):
                    log.info( '... image still registered, trying again in %is ...' %
                              EC2_POLLING_INTERVAL )
                    time.sleep( EC2_POLLING_INTERVAL )
                else:
                    log.info( "... image deregistered." )
                    break
        if delete_snapshot:
            self.__delete_image_snapshot( image, wait=wait )

    def __delete_image_snapshot( self, image, wait=True ):
        for root_device in self.possible_root_devices:
            root_bdt = image.block_device_mapping.get( root_device )
            if root_bdt:
                snapshot_id = image.block_device_mapping[ root_device ].snapshot_id
                while True:
                    log.info( "Deleting snapshot %s.", snapshot_id )
                    try:
                        self.ctx.ec2.delete_snapshot( snapshot_id )
                    except EC2ResponseError as e:
                        # It is safe to retry this indefinitely because a snapshot can only be
                        # referenced by one AMI. See also https://github.com/boto/boto/issues/3019.
                        if wait and e.error_code == 'InvalidSnapshot.InUse':
                            log.info( '... snapshot in use, trying again in %is ...' %
                                      EC2_POLLING_INTERVAL )
                            time.sleep( EC2_POLLING_INTERVAL )
                        else:
                            raise
                    break
                return
        raise RuntimeError( 'Could not determine root device in AMI' )

    def _provide_keypair( self, ec2_keypair_name, private_key_path, overwrite_local=True,
                          overwrite_ec2=True ):
        """
        Expects to be running in a Fabric task context!

        Ensures 1) that a key pair has been generated in EC2 under the given name and 2) that a
        matching private key exists on this box at the given path and 3) that the corresponding
        public key exists at the given path plus ".pub". Since EC2 doesn't even expose the public
        key for a partitluar key pair, the public key of generated keypair is additionally stored
        in S3 under the private key's fingerprint. Note that this is different to imported EC2
        keypairs which are identified by their public key's fingerprint, both by EC2 natively and
        by the mirror public key registry maintained by cgcloud in S3.

        If there already is a keypair in EC2 and a private key at the given path in this box,
        they are checked to be consistent with each other. If they are not, an exception will be
        raised.

        If there already is a local private key but no keypair in EC2, either an exception will
        be raised (if overwrite_local is False) or a keypair is created and the local private key
        will be overwritten (if overwrite_local is True).

        If there is a keypair in EC2 but no local private key, either an exception will be raised
        (if overwrite_ec2 is False) or the keypair will be deleted and a new one will be created
        in its stead (if overwrite_ec2 is True).

        To understand the logic behind all this keep in mind that the private component of a
        EC2-generated keypair can only be downloaded once, at creation time.

        :param ec2_keypair_name: the name of the keypair in EC2
        :param private_key_path: the path to the private key on this box
        :param overwrite_local: whether to overwrite a local private key, see above
        :param overwrite_ec2: whether to overwrite a keypair in EC2, see above
        :return: the actual contents of the private and public keys as a tuple in that order
        """

        ec2_keypair = self.ctx.ec2.get_key_pair( ec2_keypair_name )
        key_file_exists = run( 'test -f %s' % private_key_path, quiet=True ).succeeded

        if ec2_keypair is None:
            if key_file_exists:
                if overwrite_local:
                    # TODO: make this more prominent, e.g. by displaying all warnings at the end
                    log.warn( 'Warning: Overwriting private key with new one from EC2.' )
                else:
                    raise UserError( "Private key already exists on box. Creating a new key pair "
                                     "in EC2 would require overwriting that file" )
            ssh_privkey, ssh_pubkey = self.__create_keypair( ec2_keypair_name, private_key_path )
        else:
            # With an existing keypair there is no way to get the private key from AWS,
            # all we can do is check whether the locally stored private key is consistent.
            if key_file_exists:
                ssh_privkey, ssh_pubkey = self.__verify_keypair( ec2_keypair, private_key_path )
            else:
                if overwrite_ec2:
                    self.ctx.ec2.delete_key_pair( ec2_keypair_name )
                    ssh_privkey, ssh_pubkey = self.__create_keypair( ec2_keypair_name,
                                                                     private_key_path )
                else:
                    raise UserError(
                        "The key pair {ec2_keypair.name} is registered in EC2 but the "
                        "corresponding private key file {private_key_path} does not exist on the "
                        "instance. In order to create the private key file, the key pair must be "
                        "created at the same time. Please delete the key pair from EC2 before "
                        "retrying.".format( **locals( ) ) )

        # Store public key
        put( local_path=StringIO( ssh_pubkey ), remote_path=private_key_path + '.pub' )

        return ssh_privkey, ssh_pubkey

    def __create_keypair( self, ec2_keypair_name, private_key_path ):
        """
        Generate a keypair in EC2 using the given name and write the private key to the file at
        the given path. Return the private and public key contents as a tuple.
        """
        ec2_keypair = self.ctx.ec2.create_key_pair( ec2_keypair_name )
        if not ec2_keypair.material:
            raise AssertionError( "Created key pair but didn't get back private key" )
        ssh_privkey = ec2_keypair.material
        put( local_path=StringIO( ssh_privkey ), remote_path=private_key_path )
        assert ec2_keypair.fingerprint == ec2_keypair_fingerprint( ssh_privkey )
        run( 'chmod go= %s' % private_key_path )
        ssh_pubkey = private_to_public_key( ssh_privkey )
        self.ctx.upload_ssh_pubkey( ssh_pubkey, ec2_keypair.fingerprint )
        return ssh_privkey, ssh_pubkey

    def __verify_keypair( self, ec2_keypair, private_key_path ):
        """
        Verify that the given EC2 keypair matches the private key at the given path. Return the
        private and public key contents as a tuple.
        """
        ssh_privkey = StringIO( )
        get( remote_path=private_key_path, local_path=ssh_privkey )
        ssh_privkey = ssh_privkey.getvalue( )
        fingerprint = ec2_keypair_fingerprint( ssh_privkey )
        if ec2_keypair.fingerprint != fingerprint:
            raise UserError(
                "The fingerprint {ec2_keypair.fingerprint} of key pair {ec2_keypair.name} doesn't "
                "match the fingerprint {fingerprint} of the private key file currently present on "
                "the instance. Please delete the key pair from EC2 before retrying. "
                .format( **locals( ) ) )
        ssh_pubkey = self.ctx.download_ssh_pubkey( ec2_keypair )
        if ssh_pubkey != private_to_public_key( ssh_privkey ):
            raise RuntimeError( "The private key on the data volume doesn't match the "
                                "public key in EC2." )
        return ssh_privkey, ssh_pubkey
