import errno
import logging
import time
from collections import Iterator
from contextlib import contextmanager
from operator import attrgetter

from bd2k.util.exceptions import panic
from boto.ec2.spotinstancerequest import SpotInstanceRequest
from boto.ec2.instance import Instance
from boto.ec2.ec2object import TaggedEC2Object
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
                    log.info( '... got %s, trying again in %is ...', e.error_code, retry_after )
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
                             % (self.name, self.volume.zone, expected_zone) )


class UnexpectedResourceState( Exception ):
    def __init__( self, resource, to_state, state ):
        super( UnexpectedResourceState, self ).__init__(
            "Expected state of %s to be '%s' but got '%s'" %
            (resource, to_state, state) )


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


def running_on_ec2( ):
    try:
        with open( '/sys/hypervisor/uuid' ) as f:
            return f.read( 3 ) == 'ec2'
    except IOError as e:
        if e.errno == errno.ENOENT:
            return False
        else:
            raise


from collections import namedtuple

InstanceType = namedtuple( 'InstanceType', [
    'name',  # the API name of the instance type
    'cores',  # the number of cores
    'ecu',  # the computational power of the core times the number of cores
    'memory',  # RAM in GB
    'virtualization_types',  # the supported virtualization types, in order of preference
    'disks',  # the number of ephemeral (aka 'instance store') volumes
    'disk_type',  # the type of ephemeral volume
    'disk_capacity',  # the capacity of each ephemeral volume in GB
    'spot_availability'  # can this instance type be used on the spot market?
] )

hvm = 'hvm'  # hardware virtualization
pv = 'paravirtual'  # para-virtualization
ssd = 'SSD'  # solid-state disk
hdd = 'HDD'  # spinning disk
variable_ecu = -1  # variable ecu

_ec2_instance_types = [
    # current generation instance types
    InstanceType( 't2.micro', 1, variable_ecu, 1, [ hvm ], 0, None, 0, False ),
    InstanceType( 't2.small', 1, variable_ecu, 2, [ hvm ], 0, None, 0, False ),
    InstanceType( 't2.medium', 2, variable_ecu, 4, [ hvm ], 0, None, 0, False ),
    InstanceType( 't2.large', 2, variable_ecu, 8, [ hvm ], 0, None, 0, False ),

    InstanceType( 'm3.medium', 1, 3, 3.75, [ hvm, pv ], 1, ssd, 4, True ),
    InstanceType( 'm3.large', 2, 6.5, 7.5, [ hvm, pv ], 1, ssd, 32, True ),
    InstanceType( 'm3.xlarge', 4, 13, 15, [ hvm, pv ], 2, ssd, 40, True ),
    InstanceType( 'm3.2xlarge', 8, 26, 30, [ hvm, pv ], 2, ssd, 80, True ),

    InstanceType( 'm4.large', 2, 6.5, 8, [ hvm ], 0, None, 0, True ),
    InstanceType( 'm4.xlarge', 4, 13, 16, [ hvm ], 0, None, 0, True ),
    InstanceType( 'm4.2xlarge', 8, 26, 32, [ hvm ], 0, None, 0, True ),
    InstanceType( 'm4.4xlarge', 16, 53.5, 64, [ hvm ], 0, None, 0, True ),
    InstanceType( 'm4.10xlarge', 40, 124.5, 160, [ hvm ], 0, None, 0, True ),

    InstanceType( 'c4.large', 2, 8, 3.75, [ hvm ], 0, None, 0, True ),
    InstanceType( 'c4.xlarge', 4, 16, 7.5, [ hvm ], 0, None, 0, True ),
    InstanceType( 'c4.2xlarge', 8, 31, 15, [ hvm ], 0, None, 0, True ),
    InstanceType( 'c4.4xlarge', 16, 62, 30, [ hvm ], 0, None, 0, True ),
    InstanceType( 'c4.8xlarge', 36, 132, 60, [ hvm ], 0, None, 0, True ),

    InstanceType( 'c3.large', 2, 7, 3.75, [ hvm, pv ], 2, ssd, 16, True ),
    InstanceType( 'c3.xlarge', 4, 14, 7.5, [ hvm, pv ], 2, ssd, 40, True ),
    InstanceType( 'c3.2xlarge', 8, 28, 15, [ hvm, pv ], 2, ssd, 80, True ),
    InstanceType( 'c3.4xlarge', 16, 55, 30, [ hvm, pv ], 2, ssd, 160, True ),
    InstanceType( 'c3.8xlarge', 32, 108, 60, [ hvm, pv ], 2, ssd, 320, True ),

    InstanceType( 'g2.2xlarge', 8, 26, 15, [ hvm ], 1, ssd, 60, True ),

    InstanceType( 'r3.large', 2, 6.5, 15, [ hvm ], 1, ssd, 32, True ),
    InstanceType( 'r3.xlarge', 4, 13, 30.5, [ hvm ], 1, ssd, 80, True ),
    InstanceType( 'r3.2xlarge', 8, 26, 61, [ hvm ], 1, ssd, 160, True ),
    InstanceType( 'r3.4xlarge', 16, 52, 122, [ hvm ], 1, ssd, 320, True ),
    InstanceType( 'r3.8xlarge', 32, 104, 244, [ hvm ], 2, ssd, 320, True ),

    InstanceType( 'i2.xlarge', 4, 14, 30.5, [ hvm ], 1, ssd, 800, False ),
    InstanceType( 'i2.2xlarge', 8, 27, 61, [ hvm ], 2, ssd, 800, False ),
    InstanceType( 'i2.4xlarge', 16, 53, 122, [ hvm ], 4, ssd, 800, False ),
    InstanceType( 'i2.8xlarge', 32, 104, 244, [ hvm ], 8, ssd, 800, False ),

    InstanceType( 'd2.xlarge', 4, 14, 30.5, [ hvm ], 3, hdd, 2000, True ),
    InstanceType( 'd2.2xlarge', 8, 28, 61, [ hvm ], 6, hdd, 2000, True ),
    InstanceType( 'd2.4xlarge', 16, 56, 122, [ hvm ], 12, hdd, 2000, True ),
    InstanceType( 'd2.8xlarge', 36, 116, 244, [ hvm ], 24, hdd, 2000, True ),

    # previous generation instance types
    InstanceType( 'm1.small', 1, 1, 1.7, [ pv ], 1, hdd, 160, True ),
    InstanceType( 'm1.medium', 1, 2, 3.75, [ pv ], 1, hdd, 410, True ),
    InstanceType( 'm1.large', 2, 4, 7.5, [ pv ], 2, hdd, 420, True ),
    InstanceType( 'm1.xlarge', 4, 8, 15, [ pv ], 4, hdd, 420, True ),

    InstanceType( 'c1.medium', 2, 5, 1.7, [ pv ], 1, hdd, 350, True ),
    InstanceType( 'c1.xlarge', 8, 20, 7, [ pv ], 4, hdd, 420, True ),

    InstanceType( 'cc2.8xlarge', 32, 88, 60.5, [ hvm ], 4, hdd, 840, True ),

    InstanceType( 'm2.xlarge', 2, 6.5, 17.1, [ pv ], 1, hdd, 420, True ),
    InstanceType( 'm2.2xlarge', 4, 13, 34.2, [ pv ], 1, hdd, 850, True ),
    InstanceType( 'm2.4xlarge', 8, 26, 68.4, [ pv ], 2, hdd, 840, True ),

    InstanceType( 'cr1.8xlarge', 32, 88, 244, [ hvm ], 2, ssd, 120, True ),

    InstanceType( 'hi1.4xlarge', 16, 35, 60.5, [ hvm, pv ], 2, ssd, 1024, True ),
    InstanceType( 'hs1.8xlarge', 16, 35, 117, [ hvm, pv ], 24, hdd, 2048, False ),

    InstanceType( 't1.micro', 1, variable_ecu, 0.615, [ pv ], 0, None, 0, True ) ]

ec2_instance_types = dict( (_.name, _) for _ in _ec2_instance_types )


def wait_instances_running( ec2, instances ):
    """
    Wait until no instance in the given iterable is 'pending'. Yield every instance that
    entered the running state as soon as it does.

    :param boto.ec2.connection.EC2Connection ec2: the EC2 connection to use for making requests
    :param Iterator[Instance] instances: the instances to wait on
    :rtype: Iterator[Instance]
    """
    running_ids = set( )
    other_ids = set( )
    while True:
        pending_ids = set( )
        for i in instances:
            if i.state == 'pending':
                pending_ids.add( i.id )
            elif i.state == 'running':
                assert i.id not in running_ids
                running_ids.add( i.id )
                yield i
            else:
                assert i.id not in other_ids
                other_ids.add( i.id )
                yield i
        log.info( '%i instance(s) pending, %i running, %i other.',
                  *map( len, (pending_ids, running_ids, other_ids) ) )
        if not pending_ids:
            break
        seconds = max( a_short_time, min( len( pending_ids ), 10 * a_short_time ) )
        log.info( 'Sleeping for %is', seconds )
        time.sleep( seconds )
        for attempt in retry_ec2( ):
            with attempt:
                instances = ec2.get_only_instances( list( pending_ids ) )


def wait_spot_requests_active( ec2, requests, timeout=None, tentative=False ):
    """
    Wait until no spot request in the given iterator is in the 'open' state or, optionally,
    a timeout occurs. Yield spot requests as soon as they leave the 'open' state.

    :param Iterator[SpotInstanceRequest] requests:

    :param float timeout: Maximum time in seconds to spend waiting or None to wait forever. If a
    timeout occurs, the remaining open requests will be cancelled.

    :param bool tentative: if True, give up on a spot request at the earliest indication of it
    not being fulfilled immediately

    :rtype: Iterator[list[SpotInstanceRequest]]
    """

    if timeout is not None:
        timeout = time.time( ) + timeout
    active_ids = set( )
    other_ids = set( )
    open_ids = None

    def cancel( ):
        log.warn( 'Cancelling remaining %i spot requests.', len( open_ids ) )
        ec2.cancel_spot_instance_requests( list( open_ids ) )

    def spot_request_not_found( e ):
        error_code = 'InvalidSpotInstanceRequestID.NotFound'
        return isinstance( e, EC2ResponseError ) and e.error_code == error_code

    try:
        while True:
            open_ids = set( )
            pending_ids = set( )
            batch = [ ]
            for r in requests:
                if r.state == 'open':
                    open_ids.add( r.id )
                    if r.status.code == 'pending-evaluation':
                        pending_ids.add( r.id )
                elif r.state == 'active':
                    assert r.id not in active_ids
                    active_ids.add( r.id )
                    batch.append( r )
                else:
                    assert r.id not in other_ids
                    other_ids.add( r.id )
                    batch.append( r )
            if batch:
                yield batch
            log.info( '%i spot requests(s) are open (%i of which pending evaluation), %i active, '
                      '%i other.', *map( len, (open_ids, pending_ids, active_ids, other_ids) ) )
            if not open_ids or tentative and not pending_ids:
                break
            sleep_time = 2 * a_short_time
            if timeout is not None and time.time( ) + sleep_time >= timeout:
                break
            log.info( 'Sleeping for %is', sleep_time )
            time.sleep( sleep_time )
            for attempt in retry_ec2( retry_while=spot_request_not_found ):
                with attempt:
                    requests = ec2.get_all_spot_instance_requests( list( open_ids ) )
        log.warn( 'Timed out waiting for spot requests.' )
    except:
        if open_ids:
            with panic( log ):
                cancel( )
        raise
    else:
        if open_ids:
            cancel( )


def create_spot_instances( ec2, price, image_id, spec,
                           num_instances=1, timeout=None, tentative=False ):
    """
    :rtype: Iterator[list[Instance]]
    """
    for attempt in retry_ec2( retry_for=a_long_time,
                              retry_while=inconsistencies_detected ):
        with attempt:
            requests = ec2.request_spot_instances( price, image_id, count=num_instances, **spec )

    num_active, num_other = 0, 0
    # noinspection PyUnboundLocalVariable,PyTypeChecker
    # request_spot_instances's type annotation is wrong
    for batch in wait_spot_requests_active( ec2,
                                            requests,
                                            timeout=timeout,
                                            tentative=tentative ):
        instance_ids = [ ]
        for request in batch:
            if request.state == 'active':
                instance_ids.append( request.instance_id )
                num_active += 1
            else:
                log.info( 'Request %s in unexpected state %s.', request.id, request.state )
                num_other += 1
        if instance_ids:
            # This next line is the reason we batch. It's so we can get multiple instances in
            # a single request.
            yield ec2.get_only_instances( instance_ids )
    if not num_active:
        raise RuntimeError( 'None of the spot requests entered the active state' )
    if num_other:
        log.warn( '%i request(s) entered a state other than active.', num_other )


def inconsistencies_detected( e ):
    if e.code == 'InvalidGroup.NotFound': return True
    m = e.error_message.lower( )
    return 'invalid iam instance profile' in m or 'no associated iam roles' in m


def create_ondemand_instances( ec2, image_id, spec, num_instances=1 ):
    """
    Requests the RunInstances EC2 API call but accounts for the race between recently created
    instance profiles, IAM roles and an instance creation that refers to them.

    :rtype: list[Instance]
    """
    instance_type = spec[ 'instance_type' ]
    log.info( 'Creating %s instance(s) ... ', instance_type )
    for attempt in retry_ec2( retry_for=a_long_time,
                              retry_while=inconsistencies_detected ):
        with attempt:
            return ec2.run_instances( image_id,
                                      min_count=num_instances,
                                      max_count=num_instances,
                                      **spec ).instances


def tag_object_persistently( tagged_ec2_object, tags_dict ):
    """
    Object tagging occasionally fails with "NotFound" types of errors so we need to
    retry a few times. Sigh ...

    :type tagged_ec2_object: TaggedEC2Object
    """
    for attempt in retry_ec2( ):
        with attempt:
            tagged_ec2_object.add_tags( tags_dict )

