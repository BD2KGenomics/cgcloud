from contextlib import contextmanager
import logging
from operator import attrgetter
import time
import errno

from boto.exception import EC2ResponseError

from cgcloud.lib.util import UserError

a_short_time = 5

a_long_time = 60 * 60

log = logging.getLogger( __name__ )


def not_found( e ):
    return e.error_code.endswith( '.NotFound' )


def true( _ ):
    return True


def false( _ ):
    return False


def retry_ec2( retry_after=a_short_time,
               retry_for=10 * a_short_time,
               retry_while=not_found ):
    """
    Retry an EC2 operation while the failure matches a given predicate and until a given timeout
    expires, waiting a given amount of time in between attempts. This function is a generator
    that yields contextmanagers. See doctests below for example usage.

    :param retry_after: the delay in seconds between attempts

    :param retry_for: the timeout in seconds.

    :param retry_while: a callable with one argument, an instance of EC2ResponseError, returning
    True if another attempt should be made or False otherwise

    :return: a generator yielding contextmanagers

    Retry for a limited amount of time:
    >>> i = 0
    >>> for attempt in retry_ec2( retry_after=0, retry_for=.1, retry_while=true ):
    ...     with attempt:
    ...         i += 1
    ...         raise EC2ResponseError( 'foo', 'bar' )
    Traceback (most recent call last):
    ...
    EC2ResponseError: EC2ResponseError: foo bar
    <BLANKLINE>
    >>> i > 1
    True

    Do exactly one attempt:
    >>> i = 0
    >>> for attempt in retry_ec2( retry_for=0 ):
    ...     with attempt:
    ...         i += 1
    ...         raise EC2ResponseError( 'foo', 'bar' )
    Traceback (most recent call last):
    ...
    EC2ResponseError: EC2ResponseError: foo bar
    <BLANKLINE>
    >>> i
    1

    Don't retry on success
    >>> i = 0
    >>> for attempt in retry_ec2( retry_after=0, retry_for=.1, retry_while=true ):
    ...     with attempt:
    ...         i += 1
    >>> i
    1

    Don't retry on unless condition returns
    >>> i = 0
    >>> for attempt in retry_ec2( retry_after=0, retry_for=.1, retry_while=false ):
    ...     with attempt:
    ...         i += 1
    ...         raise EC2ResponseError( 'foo', 'bar' )
    Traceback (most recent call last):
    ...
    EC2ResponseError: EC2ResponseError: foo bar
    <BLANKLINE>
    >>> i
    1
    """
    if retry_for > 0:
        go = [ None ]

        @contextmanager
        def repeated_attempt( ):
            try:
                yield
            except EC2ResponseError as e:
                if time.time( ) + retry_after < expiration and retry_while( e ):
                    log.info(
                        '... got %s, trying again in %is ...' % ( e.error_code, retry_after ) )
                    time.sleep( retry_after )
                else:
                    raise
            else:
                go.pop( )

        expiration = time.time( ) + retry_for
        while go:
            yield repeated_attempt( )
    else:
        @contextmanager
        def single_attempt( ):
            yield

        yield single_attempt( )


class EC2VolumeHelper( object ):
    """
    A helper for creating, looking up and attaching an EBS volume in EC2
    """

    def __init__( self, ec2, name, size, availability_zone, volume_type="standard" ):
        """
        :param ec2: the Boto EC2 connection object
        :type ec2: boto.ec2.connection.EC2Connection
        """
        super( EC2VolumeHelper, self ).__init__( )
        self.availability_zone = availability_zone
        self.ec2 = ec2
        self.name = name
        self.volume_type = volume_type
        volume = self.__lookup( )
        if volume is None:
            log.info( "Creating volume %s, ...", self.name )
            volume = self.ec2.create_volume( size, availability_zone, volume_type=self.volume_type )
            self.__wait_transition( volume, { 'creating' }, 'available' )
            volume.add_tag( 'Name', self.name )
            log.info( '... created %s.', volume.id )
            volume = self.__lookup( )
        self.volume = volume

    def attach( self, instance_id, device ):
        if self.volume.attach_data.instance_id == instance_id:
            log.info( "Volume '%s' already attached to instance '%s'." %
                      (self.volume.id, instance_id) )
        else:
            self.__assert_attachable( )
            self.ec2.attach_volume( volume_id=self.volume.id,
                                    instance_id=instance_id,
                                    device=device )
            self.__wait_transition( self.volume, { 'available' }, 'in-use' )
            if self.volume.attach_data.instance_id != instance_id:
                raise UserError( "Volume %s is not attached to this instance." )

    def __lookup( self ):
        """
        Ensure that an EBS volume of the given name is available in the current availability zone.
        If the EBS volume exists but has been placed into a different zone, or if it is not
        available, an exception will be thrown.

        :rtype: boto.ec2.volume.Volume
        """
        volumes = self.ec2.get_all_volumes( filters={ 'tag:Name': self.name } )
        if len( volumes ) < 1:
            return None
        if len( volumes ) > 1:
            raise UserError( "More than one EBS volume named %s" % self.name )
        return volumes[ 0 ]

    @staticmethod
    def __wait_transition( volume, from_states, to_state ):
        wait_transition( volume, from_states, to_state, attrgetter( 'status' ) )

    def __assert_attachable( self ):
        if self.volume.status != 'available':
            raise UserError( "EBS volume %s is not available." % self.name )
        expected_zone = self.availability_zone
        if self.volume.zone != expected_zone:
            raise UserError( "Availability zone of EBS volume %s is %s but should be %s."
                             % (self.name, self.volume.zone, expected_zone ) )


class UnexpectedResourceState(Exception):
    def __init__(self, resource, to_state, state):
        super(UnexpectedResourceState, self).__init__("Expected state of %s to be '%s' but got '%s'" %
                                                      (resource, to_state, state ) )


def wait_transition( resource, from_states, to_state, state_getter=attrgetter( 'state' ) ):
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
        time.sleep( a_short_time )
        for attempt in retry_ec2( ):
            with attempt:
                resource.update( validate=True )
        state = state_getter( resource )
    if state != to_state:
        raise UnexpectedResourceState( resource, to_state, state )

def running_on_ec2():
    try:
        with open( '/sys/hypervisor/uuid' ) as f:
            return f.read(3) == 'ec2'
    except IOError as e:
        if e.errno == errno.ENOENT:
            return False
        else:
            raise
