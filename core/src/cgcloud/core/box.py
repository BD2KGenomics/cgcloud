import datetime
import socket
# cluster ssh and rsync commands need thread-safe subprocess
import subprocess32
import threading
import time
from StringIO import StringIO
from abc import ABCMeta, abstractmethod
from collections import namedtuple, Iterator
from contextlib import closing, contextmanager
from copy import copy
from functools import partial, wraps
from itertools import count, izip
from operator import attrgetter
from pipes import quote

from bd2k.util.collections import OrderedSet
from bd2k.util.exceptions import panic
from bd2k.util.expando import Expando
from bd2k.util.iterables import concat
from boto import logging
from boto.ec2.blockdevicemapping import BlockDeviceType, BlockDeviceMapping
from boto.ec2.instance import Instance
from boto.ec2.spotpricehistory import SpotPriceHistory
from boto.exception import BotoServerError, EC2ResponseError
from fabric.api import execute
from fabric.context_managers import settings
from fabric.operations import sudo, run, get, put
from paramiko import SSHClient
from paramiko.client import MissingHostKeyPolicy

from cgcloud.core.project import project_artifacts
from cgcloud.lib.context import Context
from cgcloud.lib.ec2 import (ec2_instance_types,
                             wait_instances_running,
                             inconsistencies_detected,
                             create_spot_instances,
                             create_ondemand_instances,
                             tag_object_persistently)
from cgcloud.lib.ec2 import retry_ec2, a_short_time, a_long_time, wait_transition
from cgcloud.lib.util import (UserError,
                              camel_to_snake,
                              ec2_keypair_fingerprint,
                              private_to_public_key,
                              mean, std_dev)

log = logging.getLogger( __name__ )


# noinspection PyPep8Naming
class fabric_task( object ):
    # A stack to stash the current fabric user before a new one is set via this decorator
    user_stack = [ ]
    # A reentrant lock to prevent multiple concurrent uses of fabric, which is not thread-safe
    lock = threading.RLock( )

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
            with self.lock:
                user = box.admin_account( ) if self.user is None else self.user
                user_stack = self.user_stack
                if user_stack and user_stack[ -1 ] == user:
                    return function( box, *args, **kwargs )
                else:
                    user_stack.append( user )
                    try:
                        task = partial( function, box, *args, **kwargs )
                        task.name = function.__name__
                        # noinspection PyProtectedMember
                        return box._execute_task( task, user )
                    finally:
                        assert user_stack.pop( ) == user

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
        Returns the name of a user that has sudo privileges. All administrative commands on the
        box are invoked via SSH as this user.
        """
        raise NotImplementedError( )

    def default_account( self ):
        """
        Returns the name of the user with which interactive SSH session are started on the box.
        The default implementation forwards to self.admin_account().
        """
        return self.admin_account( )

    def _image_name_prefix( self ):
        """
        Returns the prefix to be used for naming images created from this box
        """
        return self.role( )

    class NoSuchImageException( RuntimeError ):
        pass

    @abstractmethod
    def _base_image( self, virtualization_type ):
        """
        Returns the default base image that boxes performing this role should be booted from
        before they are being setup

        :rtype: boto.ec2.image.Image

        :raises Box.NoSuchImageException: if no image exists for this role and the given
                                          virtualization type
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
    def _ephemeral_mount_point( self, i ):
        """
        Returns the absolute path to the directory at which the i-th ephemeral volume is mounted
        or None if no such mount point exists. Note that there must always be a mountpoint for
        the first volume, so this method always returns a value other than None if i is 0. We
        have this method because the mount point typically depends on the distribution, and even
        on the author of the image.
        """
        raise NotImplementedError( )

    def _manages_keys_internally( self ):
        """
        Returns True if this box manages its own keypair, e.g. via the agent.
        """
        return False

    def _populate_ec2_keypair_globs( self, ec2_keypair_globs ):
        """
        Populate the given list with keypair globs defining the set of keypairs whose public
        component will be deployed to this box.

        :param ec2_keypair_globs: the suggested list of globs, to be modified in place
        """
        pass

    def __init__( self, ctx ):
        """
        Before invoking any methods on this object,
        you must ensure that a corresponding EC2 instance exists by calling either

         * prepare() and create()
         * bind()

        :type ctx: Context
        """

        # The context to be used by the instance
        self.ctx = ctx

        # The image the instance was or will be booted from
        self.image_id = None

        # The SSH key pairs to be injected into the instance.
        self.ec2_keypairs = None

        # The globs from which to derive the SSH key pairs to be inhected into the instance
        self.ec2_keypair_globs = None

        # The instance represented by this box
        self.instance = None

        # The number of previous generations of this box. When an instance is booted from a stock
        # AMI, generation is 0. After that instance is set up and imaged and another instance is
        # booted from the resulting AMI, generation will be 1.
        self.generation = None

        # The ordinal of this box within a cluster of boxes. For boxes that don't join a cluster,
        # this will be 0
        self.cluster_ordinal = None

        # The name of the cluster this box is a node of, or None if this box is not in a cluster.
        self.cluster_name = None

        # Role-specifc options for this box
        self.role_options = { }

    @property
    def instance_id( self ):
        return self.instance and self.instance.id

    @property
    def ip_address( self ):
        return self.instance and self.instance.ip_address

    @property
    def private_ip_address( self ):
        """
        Set by bind() and create(), the private IP address of this instance
        """
        return self.instance and self.instance.private_ip_address

    @property
    def host_name( self ):
        return self.instance and self.instance.public_dns_name

    @property
    def launch_time( self ):
        return self.instance and self.instance.launch_time

    @property
    def state( self ):
        return self.instance and self.instance.state

    @property
    def zone( self ):
        return self.instance and self.instance.placement

    @property
    def role_name( self ):
        return self.role( )

    @property
    def instance_type( self ):
        return self.instance and self.instance.instance_type

    possible_root_devices = ('/dev/sda1', '/dev/sda', '/dev/xvda')

    # FIXME: this can probably be rolled into prepare()

    def _spec_block_device_mapping( self, spec, image ):
        """
        Add, remove or modify the keyword arguments that will be passed to the EC2 run_instances
        request.

        :type image: boto.ec2.image.Image
        :type spec: dict
        """
        for root_device in self.possible_root_devices:
            root_bdt = image.block_device_mapping.get( root_device )
            if root_bdt:
                root_bdt.size = 10
                root_bdt.snapshot_id = None
                root_bdt.encrypted = None
                root_bdt.delete_on_termination = True
                bdm = spec.setdefault( 'block_device_map', BlockDeviceMapping( ) )
                bdm[ '/dev/sda1' ] = root_bdt
                for i in range( ec2_instance_types[ spec[ 'instance_type' ] ].disks ):
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
                                 % (image_ref, self.role( )) )
        else:
            return self.ctx.ec2.get_image( image_ref )

    def _security_group_name( self ):
        """
        Override the security group name to be used for this box
        """
        return self.role( )

    def __setup_security_groups( self, vpc_id=None ):
        log.info( 'Setting up security group ...' )
        name = self.ctx.to_aws_name( self._security_group_name( ) )
        try:
            sg = self.ctx.ec2.create_security_group(
                name=name,
                vpc_id=vpc_id,
                description="Security group for box of role %s in namespace %s" % (
                    self.role( ), self.ctx.namespace) )
        except EC2ResponseError as e:
            if e.error_code == 'InvalidGroup.Duplicate':
                filters = { 'group-name': name }
                if vpc_id is not None:
                    filters[ 'vpc-id' ] = vpc_id
                for attempt in retry_ec2( retry_while=inconsistencies_detected,
                                          retry_for=10 * 60 ):
                    with attempt:
                        sgs = self.ctx.ec2.get_all_security_groups( filters=filters )
                        assert len( sgs ) == 1
                        sg = sgs[ 0 ]
            else:
                raise
        # It's OK to have two security groups of the same name as long as their VPC is distinct.
        assert vpc_id is None or sg.vpc_id == vpc_id
        rules = self._populate_security_group( sg.name )
        for rule in rules:
            try:
                for attempt in retry_ec2( retry_while=inconsistencies_detected,
                                          retry_for=10 * 60 ):
                    with attempt:
                        assert self.ctx.ec2.authorize_security_group( group_name=sg.name, **rule )
            except EC2ResponseError as e:
                if e.error_code == 'InvalidPermission.Duplicate':
                    pass
                else:
                    raise
        # FIXME: What about stale rules? I tried writing code that removes them but gave up. The
        # API in both boto and EC2 is just too brain-dead.
        log.info( '... finished setting up %s.', sg.id )
        return [ sg.id ]

    def _populate_security_group( self, group_name ):
        """
        :return: A list of rules, each rule is a dict with keyword arguments to
        boto.ec2.connection.EC2Connection.authorize_security_group, namely

        ip_protocol
        from_port
        to_port
        cidr_ip
        src_security_group_name
        src_security_group_owner_id
        src_security_group_group_id
        """
        return [
            dict( ip_protocol='tcp', from_port=22, to_port=22, cidr_ip='0.0.0.0/0' ),
            # This is necessary to allow PMTUD. A common symptom for PMTUD not working is that
            # TCP connections hang after a certain constant amount of data has been transferred
            # if the connection is between the instance and a host with jumbo frames enabled.
            dict( ip_protocol='icmp', from_port=3, to_port=4, cidr_ip='0.0.0.0/0' ) ]

    def __get_virtualization_types( self, instance_type, requested_vtype=None ):
        instance_vtypes = OrderedSet( ec2_instance_types[ instance_type ].virtualization_types )
        role_vtypes = OrderedSet( self.supported_virtualization_types( ) )
        supported_vtypes = instance_vtypes & role_vtypes
        if supported_vtypes:
            if requested_vtype is None:
                virtualization_types = list( supported_vtypes )
            else:
                if requested_vtype in supported_vtypes:
                    virtualization_types = [ requested_vtype ]
                else:
                    raise UserError( 'Virtualization type %s not supported by role %s and instance '
                                     'type %s' % (requested_vtype, self.role( ), instance_type) )
        else:
            raise RuntimeError( 'Cannot find any virtualization types supported by both role '
                                '%s and instance type %s' % (self.role( ), instance_type) )

        return virtualization_types

    def __get_image( self, virtualization_types, image_ref=None ):
        if image_ref is None:
            for virtualization_type in virtualization_types:
                log.info( "Looking up default image for role %s and virtualization type %s, ... ",
                          self.role( ), virtualization_type )
                try:
                    image = self._base_image( virtualization_type )
                except self.NoSuchImageException as e:
                    log.info( "... %s", e.message )
                else:
                    log.info( "... found %s.", image.id )
                    assert (image.virtualization_type in virtualization_types)
                    return image
            raise RuntimeError( "Could not find suitable image for role %s", self.role( ) )
        else:
            image = self.__select_image( image_ref )
            if image.virtualization_type not in virtualization_types:
                raise RuntimeError(
                    "Role and type support virtualization types %s but image only supports %s" % (
                        virtualization_types, image.virtualization_type) )
            return image

    # Note: The name of all spot-related keyword arguments should begin with 'spot_'

    def prepare( self, ec2_keypair_globs,
                 instance_type=None, image_ref=None, virtualization_type=None,
                 spot_bid=None, spot_launch_group=None, spot_auto_zone=False,
                 vpc_id=None, subnet_id=None,
                 **options ):
        """
        Prepare to create an EC2 instance represented by this box. Return a dictionary with
        keyword arguments to boto.ec2.connection.EC2Connection.run_instances() that can be used
        to create the instance.

        :param list[str] ec2_keypair_globs: The names of EC2 keypairs whose public key is to be
        injected into the instance to facilitate SSH logins. For the first listed keypair a
        matching private key needs to be present locally. Note that after the agent is installed
        on the box it will

        :param str instance_type: The type of instance to create, e.g. m1.small or t1.micro.

        :param int|str image_ref: The ordinal or AMI ID of the image to boot from. If None,
               the return value of self._base_image() will be used.

        :param str virtualization_type: The desired virtualization type to use for the instance

        :param int num_instances: The number of instances to prepare for

        :param float spot_bid: Dollar amount to bid for spot instances. If None, an on-demand
        instance will be created

        :param str spot_launch_group: Specify a launch group in your Spot instance request to tell
        Amazon EC2 to launch a set of Spot instances only if it can launch them all. In addition,
        if the Spot service must terminate one of the instances in a launch group (for example,
        if the Spot price rises above your bid price), it must terminate them all.
        
        :param bool spot_auto_zone: Use heuristic to automatically choose the "best" availability 
        zone to launch spot instances in. Can't be combined with subnet_id. Overrides the 
        availability zone in the context.
        
        :param: str vpc_id: The ID of a VPC to create the instance and associated security group 
        in. If this argument is None or absent and the AWS account has a default VPC, the default 
        VPC will be used. This is the most common case. If this argument is None or absent and 
        the AWS account has EC2 Classic enabled and the selected instance type supports EC2 
        classic mode, no VPC will be used. If this argument is None or absent and the AWS account 
        has no default VPC and an instance type that only supports VPC is used, an exception will 
        be raised.
        
        :param: str subnet_id: The ID of a subnet to allocate instance's private IP address from. 
        Can't be combined with spot_auto_zone. The specified subnet must belong to the specified 
        VPC (or the default VPC if none was specified) and reside in the context's availability 
        zone. If this argument is None or absent, a subnet will be chosen automatically.

        :param dict options: Additional, role-specific options can be specified. These options
        augment the options associated with the givem image.
        """
        if spot_launch_group is not None and spot_bid is None:
            raise UserError( 'Need a spot bid when specifying a launch group for spot instances' )

        if spot_auto_zone and spot_bid is None:
            raise UserError( 'Need a spot bid for automatically chosing a zone for spot instances' )

        if subnet_id is not None and spot_auto_zone:
            raise UserError( 'Cannot automatically choose an availability zone for spot instances '
                             'while placing them in an explicitly defined subnet since the subnet '
                             'implies a specific availability zone.' )

        if self.instance_id is not None:
            raise AssertionError( 'Instance already bound or created' )

        if instance_type is None:
            instance_type = self.recommended_instance_type( )

        virtualization_types = self.__get_virtualization_types( instance_type, virtualization_type )
        image = self.__get_image( virtualization_types, image_ref )
        self.image_id = image.id

        zone = self.ctx.availability_zone

        security_group_ids = self.__setup_security_groups( vpc_id=vpc_id )
        if vpc_id is not None and subnet_id is None:
            log.info( 'Looking up suitable subnet for VPC %s in zone %s.', vpc_id, zone )
            subnets = self.ctx.vpc.get_all_subnets( filters={ 'vpc-id': vpc_id,
                                                              'availability-zone': zone } )
            if subnets:
                subnet_id = subnets[ 0 ].id
            else:
                raise UserError( 'There is no subnet belonging to VPC %s in availability zone %s. '
                                 'Please create a subnet manually using the VPC console.'
                                 % (vpc_id, zone) )

        options = dict( image.tags, **options )
        self._set_instance_options( options )

        self._populate_ec2_keypair_globs( ec2_keypair_globs )
        ec2_keypairs = self.ctx.expand_keypair_globs( ec2_keypair_globs )
        if not ec2_keypairs:
            raise UserError( "No key pairs matching '%s' found." % ' '.join( ec2_keypair_globs ) )
        if ec2_keypairs[ 0 ].name != ec2_keypair_globs[ 0 ]:
            raise UserError( "The first key pair name can't be a glob." )
        self.ec2_keypairs = ec2_keypairs
        self.ec2_keypair_globs = ec2_keypair_globs

        spec = Expando( instance_type=instance_type,
                        key_name=ec2_keypairs[ 0 ].name,
                        placement=zone,
                        security_group_ids=security_group_ids,
                        subnet_id=subnet_id,
                        instance_profile_arn=self.get_instance_profile_arn( ) )
        self._spec_block_device_mapping( spec, image )
        self._spec_spot_market( spec,
                                bid=spot_bid,
                                launch_group=spot_launch_group,
                                auto_zone=spot_auto_zone )
        return spec

    def _spec_spot_market( self, spec, bid, launch_group, auto_zone ):
        if bid is not None:
            if not ec2_instance_types[ spec.instance_type ].spot_availability:
                raise UserError( 'The instance type %s is not available on the spot market.' %
                                 spec.instance_type )
            if auto_zone:
                spec.placement = self._optimize_spot_bid( spec.instance_type, bid )
            spec.price = bid
            if launch_group is not None:
                spec.launch_group = self.ctx.to_aws_name( launch_group )

    ZoneTuple = namedtuple( 'ZoneTuple', [ 'name', 'price_deviation' ] )

    @classmethod
    def _choose_spot_zone( cls, zones, bid, spot_history ):
        """
        Returns the zone to put the spot request based on, in order of priority:

           1) zones with prices currently under the bid

           2) zones with the most stable price

        :param list[boto.ec2.zone.Zone] zones:
        :param float bid:
        :param list[boto.ec2.spotpricehistory.SpotPriceHistory] spot_history:

        :rtype: str
        :return: the name of the selected zone

        >>> from collections import namedtuple
        >>> FauxHistory = namedtuple( 'FauxHistory', [ 'price', 'availability_zone' ] )
        >>> ZoneTuple = namedtuple( 'ZoneTuple', [ 'name' ] )

        >>> zones = [ ZoneTuple( 'us-west-2a' ), ZoneTuple( 'us-west-2b' ) ]
        >>> spot_history = [ FauxHistory( 0.1, 'us-west-2a' ), \
                             FauxHistory( 0.2,'us-west-2a'), \
                             FauxHistory( 0.3,'us-west-2b'), \
                             FauxHistory( 0.6,'us-west-2b')]
        >>> # noinspection PyProtectedMember
        >>> Box._choose_spot_zone( zones, 0.15, spot_history )
        'us-west-2a'

        >>> spot_history=[ FauxHistory( 0.3, 'us-west-2a' ), \
                           FauxHistory( 0.2, 'us-west-2a' ), \
                           FauxHistory( 0.1, 'us-west-2b'), \
                           FauxHistory( 0.6, 'us-west-2b') ]
        >>> # noinspection PyProtectedMember
        >>> Box._choose_spot_zone(zones, 0.15, spot_history)
        'us-west-2b'

        >>> spot_history={ FauxHistory( 0.1, 'us-west-2a' ), \
                           FauxHistory( 0.7, 'us-west-2a' ), \
                           FauxHistory( 0.1, "us-west-2b" ), \
                           FauxHistory( 0.6, 'us-west-2b' ) }
        >>> # noinspection PyProtectedMember
        >>> Box._choose_spot_zone(zones, 0.15, spot_history)
        'us-west-2b'
       """

        # Create two lists of tuples of form: [ (zone.name, std_deviation), ... ] one for zones
        # over the bid price and one for zones under bid price. Each are sorted by increasing
        # standard deviation values.
        #
        markets_under_bid, markets_over_bid = [ ], [ ]
        for zone in zones:
            zone_histories = filter( lambda zone_history:
                                     zone_history.availability_zone == zone.name, spot_history )
            price_deviation = std_dev( [ history.price for history in zone_histories ] )
            recent_price = zone_histories[ 0 ]
            zone_tuple = cls.ZoneTuple( name=zone.name, price_deviation=price_deviation )
            (markets_over_bid, markets_under_bid)[ recent_price.price < bid ].append( zone_tuple )

        return min( markets_under_bid or markets_over_bid,
                    key=attrgetter( 'price_deviation' ) ).name

    def _optimize_spot_bid( self, instance_type, spot_bid ):
        """
        Check whether the bid is sane and makes an effort to place the instance in a sensible zone.
        """
        spot_history = self._get_spot_history( instance_type )
        self._check_spot_bid( spot_bid, spot_history )
        zones = self.ctx.ec2.get_all_zones( )
        most_stable_zone = self._choose_spot_zone( zones, spot_bid, spot_history )
        log.info( "Placing spot instances in zone %s.", most_stable_zone )
        return most_stable_zone

    @staticmethod
    def _check_spot_bid( spot_bid, spot_history ):
        """
        Prevents users from potentially over-paying for instances

        Note: this checks over the whole region, not a particular zone

        :param spot_bid: float

        :type spot_history: list[SpotPriceHistory]

        :raises UserError: if bid is > 2X the spot price's average

        >>> from collections import namedtuple
        >>> FauxHistory = namedtuple( "FauxHistory", [ "price", "availability_zone" ] )
        >>> spot_data = [ FauxHistory( 0.1, "us-west-2a" ), \
                          FauxHistory( 0.2, "us-west-2a" ), \
                          FauxHistory( 0.3, "us-west-2b" ), \
                          FauxHistory( 0.6, "us-west-2b" ) ]
        >>> # noinspection PyProtectedMember
        >>> Box._check_spot_bid( 0.1, spot_data )
        >>> # noinspection PyProtectedMember

        # >>> Box._check_spot_bid( 2, spot_data )
        Traceback (most recent call last):
        ...
        UserError: Your bid $ 2.000000 is more than double this instance type's average spot price ($ 0.300000) over the last week
        """
        average = mean( [ datum.price for datum in spot_history ] )
        if spot_bid > average * 2:
            log.warn( "Your bid $ %f is more than double this instance type's average "
                      "spot price ($ %f) over the last week", spot_bid, average )

    def _get_spot_history( self, instance_type ):
        """
        Returns list of 1,000 most recent spot market data points represented as SpotPriceHistory
        objects. Note: The most recent object/data point will be first in the list.

        :rtype: list[SpotPriceHistory]
        """

        one_week_ago = datetime.datetime.now( ) - datetime.timedelta( days=7 )
        spot_data = self.ctx.ec2.get_spot_price_history( start_time=one_week_ago.isoformat( ),
                                                         instance_type=instance_type,
                                                         product_description="Linux/UNIX" )
        spot_data.sort( key=attrgetter( "timestamp" ), reverse=True )
        return spot_data

    def create( self, spec,
                num_instances=1,
                wait_ready=True,
                terminate_on_error=True,
                spot_timeout=None,
                spot_tentative=False,
                cluster_ordinal=0,
                executor=None ):
        """
        Create the EC2 instance represented by this box, and optionally waits for the instance to
        be ready. If the box was prepared to launch multiple instances, and multiple instances
        were indeed launched by EC2, adoptees of this box will be created, one clone for each
        additional instance. This box will represent the first instance while the adoptees will
        represent the subsequent instances. The given executor will be used to handle
        post-creation activity on each instance.

        :param spec: a dictionary with keyword arguments to request_spot_instances,
        if the 'price' key is present, or run_instances otherwise.

        :param bool wait_ready: whether to wait for all instances to be ready. The waiting for an
        instance will be handled as a task that is submitted to the given executor.

        :param bool terminate_on_error: If True, terminate instance on errors. If False,
        never terminate any instances. Unfulfilled spot requests will always be cancelled.

        :param cluster_ordinal: the cluster ordinal to be assigned to the first instance or an
        iterable yielding ordinals for the instances

        :param executor: a callable that accepts two arguments: a task function and a sequence of
        task arguments. The executor applies the task function to the given sequence of
        arguments. It may choose to do so immediately, i.e. synchronously or at a later time,
        i.e asynchronously. If None, a synchronous executor will be used by default.

        :rtype: list[Box]
        """
        if isinstance( cluster_ordinal, int ):
            cluster_ordinal = count( start=cluster_ordinal )

        if executor is None:
            def executor( f, args ):
                f( *args )

        adopters = iter( concat( self, self.clones( ) ) )
        boxes = [ ]
        pending_ids = set( )
        pending_ids_lock = threading.RLock( )

        def adopt( adoptees ):
            """
            :type adoptees: Iterator[Instance]
            """
            pending_ids.update( i.id for i in adoptees )
            for box, instance in izip( adopters, adoptees ):
                box.adopt( instance, next( cluster_ordinal ) )
                if not wait_ready:
                    # Without wait_ready, an instance is done as soon as it has been adopted.
                    pending_ids.remove( instance.id )
                boxes.append( box )

        try:
            if 'price' in spec:
                price = spec.price
                del spec.price
                # Spot requests are fulfilled in batches. A batch could consist of one instance,
                # all requested instances or a subset thereof. As soon as a batch comes back from
                #  _create_spot_instances(), we will want to adopt every instance in it. Part of
                # adoption is tagging which is crucial for cluster nodes.
                # TODO: timeout
                for batch in create_spot_instances( self.ctx.ec2, price, self.image_id, spec,
                                                    num_instances=num_instances,
                                                    timeout=spot_timeout,
                                                    tentative=spot_tentative ):
                    adopt( batch )
            else:
                adopt( create_ondemand_instances( self.ctx.ec2, self.image_id, spec,
                                                  num_instances=num_instances ) )

            assert boxes
            assert boxes[ 0 ] is self

            if wait_ready:
                def _wait_ready( box ):
                    try:
                        # noinspection PyProtectedMember
                        box._wait_ready( { 'pending' }, first_boot=True )
                    except:
                        if terminate_on_error:
                            with panic( log ):
                                log.warn( 'Terminating instance ...' )
                                self.ctx.ec2.terminate_instances( [ box.instance_id ] )
                        raise
                    finally:
                        with pending_ids_lock:
                            pending_ids.remove( box.instance_id )

                if len( boxes ) == 1:
                    # For a single instance, self._wait_ready will wait for the instance to change to
                    # running ...
                    executor( _wait_ready, (self,) )
                else:
                    # .. but for multiple instances it is more efficient to wait for all of the
                    # instances together.
                    boxes_by_id = { box.instance_id: box for box in boxes }
                    # Wait for instances to enter the running state and as they do, pass them to
                    # the executor where they are waited on concurrently.
                    num_running, num_other = 0, 0
                    # TODO: timeout
                    instances = (box.instance for box in boxes)
                    for instance in wait_instances_running( self.ctx.ec2, instances ):
                        box = boxes_by_id[ instance.id ]
                        # equivalent to the instance.update() done in _wait_ready()
                        box.instance = instance
                        if instance.state == 'running':
                            executor( _wait_ready, (box,) )
                            num_running += 1
                        else:
                            log.info( 'Instance %s in unexpected state %s.',
                                      instance.id, instance.state )
                            num_other += 1
                    assert num_running + num_other == len( boxes )
                    if not num_running:
                        raise RuntimeError( 'None of the instances entered the running state.' )
                    if num_other:
                        log.warn( '%i instance(s) entered a state other than running.', num_other )
        except:
            if terminate_on_error:
                with panic( log ):
                    with pending_ids_lock:
                        unfinished_ids_list = list( pending_ids )
                    if unfinished_ids_list:
                        log.warn( 'Terminating instances ...' )
                        self.ctx.ec2.terminate_instances( unfinished_ids_list )
            raise
        else:
            return boxes

    def clones( self ):
        """
        Generates infinite numbers of clones of this box.

        :rtype: Iterator[Box]
        """
        while True:
            clone = copy( self )
            clone.unbind( )
            yield clone

    def adopt( self, instance, cluster_ordinal ):
        """
        Link the given newly created EC2 instance with this box.
        """
        log.info( '... created %s.', instance.id )
        self.instance = instance
        self.cluster_ordinal = cluster_ordinal
        if self.cluster_name is None:
            self.cluster_name = self.instance_id
        self._on_instance_created( )

    def _set_instance_options( self, options ):
        """
        Initialize optional instance attributes from the given dictionary mapping option names to
        option values. The keys in the dictionary must be strings, the values can be any type.
        This method handles the conversion of values from string transparently. If a key is
        missing this method will provide a default.
        """
        # Relies on idempotence of int
        self.generation = int( options.get( 'generation' ) or 0 )
        self.cluster_ordinal = int( options.get( 'cluster_ordinal' ) or 0 )
        self.cluster_name = options.get( 'cluster_name' )
        for option in self.get_role_options( ):
            value = options.get( option.name )
            if value is not None:
                self.role_options[ option.name ] = option.type( value )

    def _get_instance_options( self ):
        """
        Return a dictionary specifying the tags an instance of this role should be tagged with.
        Keys and values should be strings.
        """
        options = dict( Name=self.ctx.to_aws_name( self.role( ) ),
                        generation=str( self.generation ),
                        cluster_ordinal=str( self.cluster_ordinal ),
                        cluster_name=self.cluster_name )
        for option in self.get_role_options( ):
            value = self.role_options.get( option.name )
            if value is not None:
                options[ option.name ] = option.repr( value )
        return options

    def _get_image_options( self ):
        """
        Return a dictionary specifying the tags an image of an instance of this role should be
        tagged with. Keys and values should be strings.
        """
        options = dict( generation=str( self.generation + 1 ) )
        for option in self.get_role_options( ):
            if option.inherited:
                value = self.role_options.get( option.name )
                if value is not None:
                    options[ option.name ] = option.repr( value )
        return options

    # noinspection PyClassHasNoInit
    class RoleOption( namedtuple( "_RoleOption", 'name type repr help inherited' ) ):
        """
        Describes a role option, i.e. an instance option that is specific to boxes of a
        particular role. Name is the name of the option, type is a function converting an option
        value from a string to the option's native type, repr is the inverse of type, help is a
        help text describing the option and inherited is a boolean controlling whether the option
        is inherited by images created from an instance.
        """

        def to_dict( self ):
            return self._asdict( )

        def type( self, value ):
            try:
                # noinspection PyUnresolvedReferences
                return super( Box.RoleOption, self ).type( value )
            except ValueError:
                raise UserError(
                    "'%s' is not a valid value for option %s" % (value, self.name) )

    @classmethod
    def get_role_options( cls ):
        """
        Return a list of RoleOption objects, one for each supported option supported by this role.

        :rtype: list[Box.RoleOption]
        """
        return [ ]

    def _on_instance_created( self ):
        """
        Invoked right after an instance was created.
        """
        log.info( 'Tagging instance ... ' )
        tags_dict = self._get_instance_options( )
        tag_object_persistently( self.instance, tags_dict )
        log.info( '... instance tagged %r.', tags_dict )

    def _on_instance_running( self, first_boot ):
        """
        Invoked while creating, binding or starting an instance, right after the instance entered
        the running state.

        :param first_boot: True if this is the first time the instance enters the running state
        since its creation
        """
        pass

    def _on_instance_ready( self, first_boot ):
        """
        Invoked while creating, binding or starting an instance, right after the instance was
        found to be ready.

        :param first_boot: True if the instance was booted for the first time, i.e. if this is
        the first time the instance becomes ready since its creation, False if the instance was
        booted but not for the first time, None if it is not clear whether the instance was
        booted, e.g. after binding.
        """
        if first_boot and not self._manages_keys_internally( ):
            self.__inject_authorized_keys( self.ec2_keypairs[ 1: ] )

    def bind( self,
              instance=None,
              instance_id=None,
              ordinal=None, cluster_name=None,
              wait_ready=True, verbose=True ):
        """
        Verify that the EC instance represented by this box exists and, optionally,
        wait until it is ready, i.e. that it is is running, has a public host name and can be
        connected to via SSH. If the box doesn't exist and exception will be raised.

        :param wait_ready: if True, wait for the instance to be ready
        """
        if wait_ready: verbose = True
        if self.instance is None:
            if verbose: log.info( 'Binding to instance ... ' )
            if instance is not None:
                assert ordinal is None and cluster_name is None and instance_id is None
                name = instance.tags[ 'Name' ]
                assert self.ctx.contains_aws_name( name )
                assert self.ctx.base_name( self.ctx.from_aws_name( name ) ) == self.role( )
            elif instance_id is not None:
                assert ordinal is None
                try:
                    instance = self.ctx.ec2.get_only_instances( instance_id )[ 0 ]
                except EC2ResponseError as e:
                    if e.error_code.startswith( 'InvalidInstanceID' ):
                        raise UserError( "No instance with ID '%s'." % instance_id )
                try:
                    name = instance.tags[ 'Name' ]
                except KeyError:
                    raise UserError( "Instance %s does not have a Name tag." % instance.id )
                if not self.ctx.try_contains_aws_name( name ):
                    raise UserError( "Instance %s with Name tag '%s' is not in namespace %s."
                                     % (instance.id, name, self.ctx.namespace) )
                if self.ctx.base_name( self.ctx.from_aws_name( name ) ) != self.role( ):
                    raise UserError( "Instance %s with Name tag '%s' is not a %s." %
                                     (instance.id, name, self.role( )) )
                if cluster_name is not None:
                    actual_cluster_name = instance.tags.get( 'cluster_name' )
                    if actual_cluster_name is not None and actual_cluster_name != cluster_name:
                        raise UserError( "Instance %s has cluster name '%s', not '%s'." %
                                         (instance.id, actual_cluster_name, cluster_name) )
            else:
                instance = self.__get_instance_by_ordinal( ordinal=ordinal,
                                                           cluster_name=cluster_name )
            self.instance = instance
            self.image_id = self.instance.image_id
            options = dict( self.instance.tags )
            self._set_instance_options( options )
            if wait_ready:
                self._wait_ready( from_states={ 'pending' }, first_boot=None )
            else:
                if verbose: log.info( '... bound to %s.', self.instance.id )
        return self

    def unbind( self ):
        """
        Unset all state in this box that would be specific to an individual EC2 instance. This
        method prepares this box for being bound to another EC2 instance.
        """
        self.instance = None
        self.cluster_ordinal = None

    def list( self, wait_ready=False, **tags ):
        return [ box.bind( instance=instance, wait_ready=wait_ready, verbose=False )
            for box, instance in izip( concat( self, self.clones( ) ),
                                       self.__list_instances( **tags ) ) ]

    def __list_instances( self, **tags ):
        """
        Lookup and return a list of instance performing this box' role.

        :rtype: list[Instance]
        """
        name = self.ctx.to_aws_name( self.role( ) )
        filters = { 'tag:Name': name }
        for k, v in tags.iteritems( ):
            if v is not None:
                filters[ 'tag:' + k ] = v
        reservations = self.ctx.ec2.get_all_instances( filters=filters )
        instances = [ i for r in reservations for i in r.instances if i.state != 'terminated' ]
        instances.sort( key=self.__ordinal_sort_key )
        return instances

    def __ordinal_sort_key( self, instance ):
        return instance.launch_time, instance.private_ip_address, instance.id

    def __get_instance_by_ordinal( self, ordinal=None, cluster_name=None ):
        """
        Get the n-th instance that performs this box' role

        :param ordinal: the index of the instance based on the ordering by launch_time

        :rtype: boto.ec2.instance.Instance
        """
        instances = self.__list_instances( cluster_name=cluster_name )
        if not instances:
            raise UserError(
                "No instance performing role %s in namespace %s" % (
                    self.role( ), self.ctx.namespace) if cluster_name is None
                else "No instance performing role %s in cluster %s and namespace %s" % (
                    self.role( ), cluster_name, self.ctx.namespace) )
        if ordinal is None:
            if len( instances ) > 1:
                raise UserError( "More than one instance performing role '%s'. Please specify an "
                                 "ordinal, a cluster name or both to disambiguate." % self.role( ) )
            ordinal = 0
        try:
            return instances[ ordinal ]
        except IndexError:
            raise UserError(
                "No instance performing role %s in namespace %s has ordinal %i" % (
                    self.role( ), self.ctx.namespace, ordinal) if cluster_name is None
                else "No instance performing role %s in cluster %s and namespace %s has ordinal %i" % (
                    self.role( ), cluster_name, self.ctx.namespace, ordinal) )

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
        # We've observed instance state to flap from stopped back to stoppping. As a best effort
        # we wait for it to flap back to stopped.
        wait_transition( self.instance, { 'stopping' }, 'stopped' )

        log.info( "Creating image ..." )
        timestamp = time.strftime( '%Y-%m-%d_%H-%M-%S' )
        image_name = self.ctx.to_aws_name( self._image_name_prefix( ) + "_" + timestamp )
        image_id = self.ctx.ec2.create_image(
            instance_id=self.instance_id,
            name=image_name,
            block_device_mapping=self._image_block_device_mapping( ) )
        while True:
            try:
                image = self.ctx.ec2.get_image( image_id )
                tag_object_persistently( image, self._get_image_options( ) )
                wait_transition( image, { 'pending' }, 'available' )
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
            log.info( '... image %s not yet discoverable, trying again in %is ...', image_id,
                      a_short_time )
            time.sleep( a_short_time )
        return image_id

    def stop( self ):
        """
        Stop the EC2 instance represented by this box. Stopped instances can be started later using
        :py:func:`Box.start`.
        """
        self.__assert_state( 'running' )
        log.info( 'Stopping instance ...' )
        self.ctx.ec2.stop_instances( [ self.instance_id ] )
        wait_transition( self.instance,
                         from_states={ 'running', 'stopping' },
                         to_state='stopped' )
        log.info( '... instance stopped.' )

    def start( self ):
        """
        Start the EC2 instance represented by this box
        """
        self.__assert_state( 'stopped' )
        log.info( 'Starting instance, ... ' )
        self.ctx.ec2.start_instances( [ self.instance_id ] )
        # Not 100% sure why from_states includes 'stopped' but I think I noticed that there is a
        # short interval after start_instances returns during which the instance is still in
        # stopped before it goes into pending
        self._wait_ready( from_states={ 'stopped', 'pending' }, first_boot=False )

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
            instance = self.instance
            if instance.state != 'terminated':
                log.info( 'Terminating instance ...' )
                self.ctx.ec2.terminate_instances( [ self.instance_id ] )
                if wait:
                    wait_transition( instance,
                                     from_states={ 'running', 'shutting-down', 'stopped' },
                                     to_state='terminated' )
                    log.info( '... instance terminated.' )

    def _attach_volume( self, volume_helper, device ):
        volume_helper.attach( self.instance_id, device )

    def _execute_task( self, task, user ):
        """
        Execute the given Fabric task on the EC2 instance represented by this box
        """
        if not callable( task ): task = task( self )
        # using IP instead of host name yields more compact log lines
        # host = "%s@%s" % ( user, self.ip_address )
        with settings( user=user ):
            host = self.ip_address
            return execute( task, hosts=[ host ] )[ host ]

    def __assert_state( self, expected_state ):
        """
        Raises a UserError if the instance represented by this object is not in the given state.

        :param expected_state: the expected state
        :return: the instance
        :rtype: boto.ec2.instance.Instance
        """
        actual_state = self.instance.state
        if actual_state != expected_state:
            raise UserError( "Expected instance state '%s' but got '%s'"
                             % (expected_state, actual_state) )

    def _wait_ready( self, from_states, first_boot ):
        """
        Wait until the given instance transistions from stopped or pending state to being fully
        running and accessible via SSH.

        :param from_states: the set of states the instance may be in when this methods is
        invoked, any other state will raise an exception.
        :type from_states: set of str

         :param first_boot: True if the instance is currently booting for the first time,
         None if the instance isn't booting, False if the instance is booting but not for the
         first time.
        """
        log.info( "... waiting for instance %s ... ", self.instance.id )
        wait_transition( self.instance, from_states, 'running' )
        self._on_instance_running( first_boot )
        log.info( "... running, waiting for assignment of public IP ... " )
        self.__wait_public_ip_assigned( self.instance )
        log.info( "... assigned, waiting for SSH port ... " )
        self.__wait_ssh_port_open( )
        log.info( "... open ... " )
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
        while not instance.ip_address or not instance.public_dns_name:
            time.sleep( a_short_time )
            instance.update( )

    def __wait_ssh_port_open( self ):
        """
        Wait until the instance represented by this box is accessible via SSH.

        :return: the number of unsuccessful attempts to connect to the port before a the first
        success
        """
        for i in count( ):
            s = socket.socket( socket.AF_INET, socket.SOCK_STREAM )
            try:
                s.settimeout( a_short_time )
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
            client = None
            try:
                client = self._ssh_client( )
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
                if client is not None:
                    client.close( )
            time.sleep( a_short_time )

    def _ssh_client( self ):
        client = SSHClient( )
        client.set_missing_host_key_policy( self.IgnorePolicy( ) )
        client.connect( hostname=self.ip_address,
                        username=self.admin_account( ),
                        timeout=a_short_time )
        return client

    def ssh( self, user=None, command=None ):
        if command is None: command = [ ]
        status = subprocess32.call( self._ssh_args( user, command ) )
        # According to ssh(1), SSH returns the status code of the remote process or 255 if
        # something else went wrong. Python exits with status 1 if an uncaught exception is
        # thrown. Since this is also the default status code that most other programs return on
        # failure, there is no easy way to distinguish between failures in programs run remotely
        # by cgcloud ssh and something being wrong in cgcloud.
        if status == 255:
            raise RuntimeError( 'ssh failed' )
        return status

    def rsync( self, args, user=None, ssh_opts=None ):
        ssh_args = self._ssh_args( user, [ ] )
        if ssh_opts:
            ssh_args.append( ssh_opts )
        subprocess32.check_call( [ 'rsync', '-e', ' '.join( ssh_args ) ] + args )

    def _ssh_args( self, user, command ):
        if user is None: user = self.default_account( )
        # Using host name instead of IP allows for more descriptive known_hosts entries and
        # enables using wildcards like *.compute.amazonaws.com Host entries in ~/.ssh/config.
        return [ 'ssh', '%s@%s' % (user, self.host_name), '-A' ] + command

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
        image_name_pattern = self.ctx.to_aws_name( self._image_name_prefix( ) + '_' ) + '*'
        images = self.ctx.ec2.get_all_images( filters={ 'name': image_name_pattern } )
        images.sort( key=attrgetter( 'name' ) )  # that sorts by date, effectively
        return images

    @abstractmethod
    def _register_init_command( self, cmd ):
        """
        Register a shell command to be executed towards the end of system initialization. The
        command should work when set -e is in effect.
        """
        raise NotImplementedError( )

    def get_instance_profile_arn( self ):
        """
        Prepares the instance profile to be used for this box and returns its ARN
        """
        role_name, policies = self._get_iam_ec2_role( )
        aws_role_name = self.ctx.setup_iam_ec2_role( role_name, policies )
        aws_instance_profile_name = self.ctx.to_aws_name( self.role( ) )
        try:
            profile = self.ctx.iam.get_instance_profile( aws_instance_profile_name )
        except BotoServerError as e:
            if e.status == 404:
                profile = self.ctx.iam.create_instance_profile( aws_instance_profile_name )
                profile = profile.create_instance_profile_response.create_instance_profile_result
            else:
                raise
        else:
            profile = profile.get_instance_profile_response.get_instance_profile_result

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
        Returns the ARN for roles with the given prefix in the current AWS account
        """
        aws_role_prefix = self.ctx.to_aws_name( role_prefix + Box.role_prefix )
        return "arn:aws:iam::%s:role/%s*" % (self.ctx.account, aws_role_prefix)

    def _get_iam_ec2_role( self ):
        """
        Returns the IAM role to be associated for this box

        :return A tuple of the form ( role_arn, policy_document ) where policy_document is the
        """
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
                              a_short_time )
                    time.sleep( a_short_time )
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
                log.info( "Deleting snapshot %s.", snapshot_id )
                # It is safe to retry this indefinitely because a snapshot can only be
                # referenced by one AMI. See also https://github.com/boto/boto/issues/3019.
                for attempt in retry_ec2(
                    retry_for=a_long_time if wait else 0,
                    retry_while=lambda e: e.error_code == 'InvalidSnapshot.InUse' ):
                    with attempt:
                        self.ctx.ec2.delete_snapshot( snapshot_id )
                return
        raise RuntimeError( 'Could not determine root device in AMI' )

    def _provide_generated_keypair( self,
                                    ec2_keypair_name,
                                    private_key_path,
                                    overwrite_local=True,
                                    overwrite_ec2=False ):
        """
        Expects to be running in a Fabric task context!

        Ensures that 1) a key pair has been generated in EC2 under the given name, 2) a matching
        private key exists on this box at the given path and 3) the corresponding public key
        exists at the given path with .pub appended. A generated keypair is one for which EC2
        generated the private key. This is different from imported keypairs where the private key
        is generated locally and the public key is then imported to EC2.

        Since EC2 exposes only the fingerprint for a particular key pair, but not the public key,
        the public key of the generated key pair is additionally stored in S3. The public key
        object in S3 will be identified using the key pair's fingerprint, which really is the the
        private key's fingerprint. Note that this is different to imported key pairs which are
        identified by their public key's fingerprint, both by EC2 natively and by cgcloud in S3.

        If there already is a key pair in EC2 and a private key at the given path in this box,
        they are checked to match each other. If they don't, an exception will be raised.

        If there already is a local private key but no key pair in EC2, either an exception will
        be raised (if overwrite_local is False) or a key pair will be created and the local
        private key will be overwritten (if overwrite_local is True).

        If there is a key pair in EC2 but no local private key, either an exception will be
        raised (if overwrite_ec2 is False) or the key pair will be deleted and a new one will be
        created in its stead (if overwrite_ec2 is True).

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
            ssh_privkey, ssh_pubkey = self.__generate_keypair( ec2_keypair_name, private_key_path )
        else:
            # With an existing keypair there is no way to get the private key from AWS,
            # all we can do is check whether the locally stored private key is consistent.
            if key_file_exists:
                ssh_privkey, ssh_pubkey = self.__verify_generated_keypair( ec2_keypair,
                                                                           private_key_path )
            else:
                if overwrite_ec2:
                    self.ctx.ec2.delete_key_pair( ec2_keypair_name )
                    ssh_privkey, ssh_pubkey = self.__generate_keypair( ec2_keypair_name,
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

    def __generate_keypair( self, ec2_keypair_name, private_key_path ):
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

    def __verify_generated_keypair( self, ec2_keypair, private_key_path ):
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

    def _provide_imported_keypair( self, ec2_keypair_name, private_key_path, overwrite_ec2=False ):
        """
        Expects to be running in a Fabric task context!

        Ensures that 1) a key pair has been imported to EC2 under the given name, 2) a matching
        private key exists on this box at the given path and 3) the corresponding public key
        exists at the given path with .pub appended.

        If there is no private key at the given path on this box, one will be created. If there
        already is a imported key pair in EC2, it is checked to match the local public key. If
        they don't match an exception will be raised (overwrite_ec2 is False) or the EC2 key pair
        will be replaced with a new one by importing the local public key. The public key itself
        will be tracked in S3. See _provide_generated_keypair for details.

        :param ec2_keypair_name: the name of the keypair in EC2
        :param private_key_path: the path to the private key on this box (tilde will be expanded)
        :return: the actual contents of the private and public keys as a tuple in that order
        """
        key_file_exists = run( 'test -f %s' % private_key_path, quiet=True ).succeeded
        if not key_file_exists:
            run( "ssh-keygen -N '' -C '%s' -f '%s'" % (ec2_keypair_name, private_key_path) )
        ssh_privkey = StringIO( )
        get( remote_path=private_key_path, local_path=ssh_privkey )
        ssh_privkey = ssh_privkey.getvalue( )
        ssh_pubkey = StringIO( )
        get( remote_path=private_key_path + '.pub', local_path=ssh_pubkey )
        ssh_pubkey = ssh_pubkey.getvalue( )
        self.ctx.register_ssh_pubkey( ec2_keypair_name, ssh_pubkey, force=overwrite_ec2 )
        return ssh_privkey, ssh_pubkey

    @contextmanager
    def _project_artifacts( self, project_name ):
        """
        Like project.project_artifacts() but uploads any source distributions to the instance
        represented by this box such that a pip running on that instance box can install them.
        Must be called directly or indirectly from a function decorated with fabric_task. Returns
        a list of artifacts references, each reference being either a remote path to a source
        distribution or a versioned dependency reference, typically referring to a package on PyPI.
        """
        artifacts = [ ]
        for artifact in project_artifacts( project_name ):
            if artifact.startswith( '/' ):
                artifact = put( local_path=artifact )[ 0 ]
            artifacts.append( artifact )

        yield artifacts

        for artifact in artifacts:
            if artifact.startswith( '/' ):
                run( 'rm %s' % quote( artifact ) )
