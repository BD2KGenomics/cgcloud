from __future__ import print_function
import socket
import subprocess
import time

from boto import ec2

from fabric.api import execute
import sys
from util import unpack_singleton

EC2_POLLING_INTERVAL = 5


def needs_instance(method):
    def wrapped_method(self, *args, **kwargs):
        if self.instance_id is None:
            raise RuntimeError( "Instance ID not set" )
        method( self, *args, **kwargs )

    return wrapped_method


class Ec2Box( object ):
    """
    Manage EC2 instances. Each instance of this class represents a single virtual machine (aka
    instance) in EC2.
    """

    @staticmethod
    def name(self):
        """
        The human-readable name of this box
        """
        raise NotImplementedError( )

    def username(self):
        """
        Returns the username for making SSH connections to the instance.
        """
        raise NotImplementedError( )

    def image_id(self):
        """
        Returns the ID of the AMI to boot this box from
        """
        raise NotImplementedError( )

    def setup(self, update=False):
        """
        Create the EC2 instance represented by this box, install OS and additional packages on,
        optionally create an AMI image of it, and/or terminate it.

        :param update:
            Bring the package repository as well as any installed packages up to date, i.e. do
            what on Ubuntu is achieved by doing 'sudo apt-get update ; sudo apt-get upgrade'.
        """
        raise NotImplementedError( )

    def __init__(self, ec2_options):
        """
        Initialize an instance of this class. Before calling any of the methods on this object,
        you must ensure that a corresponding EC2 instance exists by calling either create() or
        adopt(). The former creates a new EC2 instance, the latter looks up an existing one.
        """
        self.ec2_options = ec2_options
        self.instance_id = None
        self.host_name = None
        self.connection = ec2.connect_to_region( ec2_options.region )

    def create(self):
        """
        Launch (aka 'run' in EC2 lingo) the EC2 instance represented by this box
        """
        if self.instance_id is not None:
            raise RuntimeError( "Instance already adopted or created" )

        self._log( 'Creating instance ... ', newline=False )

        kwargs = self._instance_creation_args( )

        reservation = self.connection.run_instances( self.image_id( ), **kwargs )
        instance = unpack_singleton( reservation.instances )
        self.instance_id = instance.id

        self.__wait_ready( instance )

        self._log( 'Tagging instances.' )
        instance.add_tag( 'Name', self.name( ) )

    def _instance_creation_args(self):
        """
        Returns the keyword arguments that will be passed to boto.connection.run_instances method.
        Subclasses may want to override this method in order to modify those arguments to.
        """
        kwargs = dict( instance_type=self.ec2_options.instance_type,
                       key_name=self.ec2_options.ssh_key_name,
                       placement=self.ec2_options.availability_zone )
        return kwargs

    def adopt(self):
        """
        Adopt the EC instance represented by this box.
        """
        if self.instance_id is None:
            self._log( 'Looking up instance ... ', newline=False )
            box_name = self.name( )
            reservations = self.connection.get_all_instances( filters={ 'tag:Name': box_name } )
            if not reservations:
                raise RuntimeError( "No such box: '%s'" % box_name )
            reservation = unpack_singleton( reservations )
            instance = unpack_singleton( reservation.instances )
            self.instance_id = instance.id
            self.__wait_ready( instance )

    def create_and_setup(self, update=False, image=False, terminate=None):
        """
        Create the EC2 instance to be represented by this box, install OS and additional packages
        on it, optionally create an AMI image of it, and/or terminate it.

        :param update:
            Bring the package repository as well as any installed packages up to date, i.e. do
            what on Ubuntu is achieved by doing 'sudo apt-get update ; sudo apt-get upgrade'.
        :param image:
            If True, create an image (AMI) of this box after setup completes. The image name (the
            value of the Name tag) will be the name of the box followed by the current date.
        :param terminate:
            If True, terminate the box before this method exits. If False, don't
            terminate this box. If None, terminate only on exceptions.
        """
        try:
            self.setup( update )
            if image:
                self.stop( )
                self.create_image( )
                if terminate is not True:
                    self.start( )
        except:
            if terminate is not False:
                self.terminate( wait=False )
            raise
        else:
            if terminate is True:
                self.terminate( )

    def ssh_args(self):
        return [ 'ssh', '-l', 'ubuntu', self.host_name ]

    def ssh(self):
        self.adopt( )
        subprocess.call( self.ssh_args( ) )

    @needs_instance
    def execute(self, task):
        """
        Execute the given Fabric task on the EC2 instance represented by this box
        """
        if not callable( task ): task = task( self )
        execute( task, hosts=[ "%s@%s" % ( self.username( ), self.host_name ) ] )

    @needs_instance
    def create_image(self):
        """
        Create an image (AMI) of the EC2 instance represented by this box and return its ID.
        The EC2 instance needs to use an EBS-backed root volume. The box must be stopped or
        an exception will be raised.
        """
        instance = self._get_instance( )
        if instance.state != 'stopped':
            raise RuntimeError( 'Instance is not stopped' )

        self._log( "Creating image ... ", newline=False )
        image_name = "%s %s" % ( self.name( ), time.strftime( '%Y%m%d%H%M%S' ) )
        image_id = self.connection.create_image( self.instance_id, image_name )
        while True:
            try:
                image = self.connection.get_image( image_id )
                break
            except self.connection.ResponseError as e:
                if e.error_code != 'InvalidAMIID.NotFound':
                    raise
        self.__wait_transition( image, { 'pending' }, 'available' )
        self._log( "done." )
        return image_id

    @needs_instance
    def stop(self):
        """
        Stop the EC2 instance represented by this box. Stopped instances can be started later using
        :py:func:`start`.
        """
        self._log( 'Stopping instance ... ', newline=False )
        self.connection.stop_instances( [ self.instance_id ] )
        self.__wait_transition( self._get_instance( ), { 'stopping' }, 'stopped' );
        self._log( 'done.' )

    @needs_instance
    def start(self):
        """
        Start the EC2 instance represented by this box
        """
        self._log( 'Starting instance ... ', newline=False )
        self.connection.start_instances( [ self.instance_id ] )
        self.__wait_ready( self._get_instance( ) )

    @needs_instance
    def reboot(self):
        """
        Reboot the EC2 instance represented by this box
        """
        # There is reboot_instances in the API but reliably detecting the
        # state transitions is hard. So we stop and start instead. Note that
        # this will change the IP address and hostname of the instance.
        self.stop( )
        self.start( )

    def terminate(self, wait=True):
        """
        Terminate the EC2 instance represented by this box.
        """
        if self.instance_id is not None:
            self._log( 'Terminating instance ... ', newline=False )
            self.connection.terminate_instances( [ self.instance_id ] )
            if wait:
                self.__wait_transition( self._get_instance( ),
                                        { 'running', 'shutting-down', 'stopped' },
                                        'terminated' )
        self._log( 'done.' )

    def lookup_volume(self, name):
        """
        Ensure that an EBS volume of the given name is available in the current availability zone.
        If the EBS volume exists but has been placed into a different zone, or if it is not
        available, an exception will be thrown.

        :param name: the name of the volume
        """
        volumes = self.connection.get_all_volumes( filters={ 'tag:Name': name } )
        if len( volumes ) < 1: return None
        if len( volumes ) > 1: raise RuntimeError( "More than one EBS volume named %s" % name )
        volume = volumes[ 0 ]
        if volume.status != 'available':
            raise RuntimeError( "EBS volume %s is not available." % name )
        expected_zone = self.ec2_options.availability_zone
        if volume.zone != expected_zone:
            raise RuntimeError( "Availability zone of EBS volume %s is %s but should be %s."
                                % (name, volume.zone, expected_zone ) )
        return volume

    def ensure_volume_exists(self, name, size, **kwargs):
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
        volume = self.lookup_volume( name )
        if volume is None:
            self._log( "Creating volume %s ... " % name, newline=False )
            zone = self.ec2_options.availability_zone
            volume = self.connection.create_volume( size, zone, **kwargs )
            self.__wait_volume_transition( volume, { 'creating' }, 'available' )
            volume.add_tag( 'Name', name )
            self._log( 'done.' )
            volume = self.lookup_volume( name )
        return volume

    @needs_instance
    def attach_volume(self, volume, device):
        self.connection.attach_volume( volume_id=volume.id,
                                       instance_id=self.instance_id,
                                       device=device )
        self.__wait_volume_transition( volume, { 'available' }, 'in-use' )
        if volume.attach_data.instance_id != self.instance_id:
            raise RuntimeError( "Volume %s is not attached to this instance." )

    def _log(self, string, newline=True):
        if newline:
            print( string, file=sys.stderr )
        else:
            sys.stderr.write( string )
            sys.stderr.flush( )

    def _get_instance(self):
        """
        Return the EC2 instance API object represented by this box.
        """
        reservations = self.connection.get_all_instances( self.instance_id )
        return unpack_singleton( unpack_singleton( reservations ).instances )

    def __wait_ready(self, instance):
        """
        Wait until the given instance transistions from stopped or pending state to being fully
        running and accessible via SSH.
        """
        self.__wait_transition( instance, { 'stopped', 'pending' }, 'running' )
        self._log( "running, ... ", newline=False )
        self.__wait_hostname_assigned( instance )
        self._log( "hostname assigned, ... ", newline=False )
        self.__wait_ssh_port_open( )
        self._log( "SSH open, done." )

    def __wait_hostname_assigned(self, instance):
        """
        Wait until the instances has a public host name assigned to it. Returns a dictionary with
         one entry per instance, mapping its instance ID to its public hostname.
        """
        while True:
            host_name = instance.public_dns_name
            if host_name is not None and len( host_name ) > 0: break
            time.sleep( EC2_POLLING_INTERVAL )
            instance.update( )

        self.host_name = host_name

    def __wait_ssh_port_open(self):
        """
        Wait until the instance represented by this box is accessible via SSH.
        """
        while True:
            s = socket.socket( socket.AF_INET, socket.SOCK_STREAM )
            try:
                s.settimeout( EC2_POLLING_INTERVAL )
                s.connect( (self.host_name, 22) )
                return
            except socket.error:
                pass
            except socket.timeout:
                pass
            finally:
                s.close( )

    def __wait_volume_transition(self, volume, from_states, to_state):
        """
        Same as :py:meth:`_wait_transition`, but for volumes which use 'status' instead of 'state'.
        """
        self.__wait_transition( volume, from_states, to_state, lambda volume: volume.status )

    def __wait_transition(self, resource, from_states, to_state,
                          state_getter=lambda resource: resource.state):
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
            raise RuntimeError( "Expected state of %s to be '%s' but got '%s'"
                                % ( resource, to_state, state ) )
