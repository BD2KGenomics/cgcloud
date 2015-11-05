import logging

from bd2k.util.iterables import concat

from cgcloud.core.box import Box
from cgcloud.core.commands import RecreateCommand

log = logging.getLogger( __name__ )


class ClusterCommand( RecreateCommand ):
    """
    A command that creates a cluster with one leader and one or more workers. Both leader and
    workers are launched from the same AMI.
    """

    def __init__( self, application, leader_role, worker_role, leader='leader', worker='worker' ):
        self.leader_role = leader_role
        self.worker_role = worker_role
        self.leader = leader
        self.worker = worker
        self.workers = self.worker + 's'

        super( ClusterCommand, self ).__init__( application )

        self.option( '--num-%s' % self.workers, '-s', metavar='NUM',
                     type=int, default=1, dest='num_workers',
                     help='The number of %s to start.' % self.workers )

        self.option( '--ebs-volume-size', metavar='GB',
                     help='The size in GB of an EBS volume to be attached to each node for '
                          'persistent data. The volume will be mounted at /mnt/persistent.' )

        self.option( '--%s-on-demand' % self.leader, dest='leader_on_demand',
                     default=False,
                     action='store_true',
                     help='Use this option to insure that the %s will be an on-demand '
                          'instance, even if --spot-bid is given.' % self.leader )

    def instance_options( self, options ):
        return dict( super( ClusterCommand, self ).instance_options( options ),
                     leader_on_demand=options.leader_on_demand,
                     ebs_volume_size=options.ebs_volume_size )

    def option( self, option_name, *args, **kwargs ):
        _super = super( ClusterCommand, self )
        if option_name == 'role':
            # Suppress the role positional argument since the role is hard-wired by subclasses.
            return
        if option_name == '--instance-type':
            # We want --instance-type to apply to the workers and --leader-instance-type to the
            # leader. Furthermore, we want --leader-instance-type to default to the value of
            # --leader-instance-type.
            kwargs[ 'dest' ] = 'instance_type'
            kwargs[ 'help' ] = kwargs[ 'help' ].replace( 'for the box',
                                                         'for the %s' % self.workers )
            assert args[ 0 ] == '-t'
            kwargs[ 'dest' ] = 'instance_type'
            _super.option( '--%s-instance-type' % self.leader, *args[ 1: ], **kwargs )
            kwargs[ 'help' ] = kwargs[ 'help' ].replace( self.workers, self.leader )
            kwargs[ 'dest' ] = 'worker_instance_type'
        _super.option( option_name, *args, **kwargs )

    def run_in_ctx( self, options, ctx ):
        log.info( '=== Launching master ===' )
        if options.instance_type is None:
            # --leader-instance-type should default to the value of --instance-type
            options.instance_type = options.worker_instance_type
        options.role = self.leader_role.role( )
        super( ClusterCommand, self ).run_in_ctx( options, ctx )

    def run_on_creation( self, leader, options ):
        """
        :type leader: ClusterLeader
        """
        log.info( '=== Launching %s ===', self.workers )
        leader.clone( worker_role=self.worker_role,
                      num_workers=options.num_workers,
                      worker_instance_type=options.worker_instance_type )


class ClusterBox( Box ):
    def _set_instance_options( self, options ):
        super( ClusterBox, self )._set_instance_options( options )
        self.ebs_volume_size = int( options.get( 'ebs_volume_size' ) or 0 )

    def _get_instance_options( self ):
        return dict( super( ClusterBox, self )._get_instance_options( ),
                     ebs_volume_size=str( self.ebs_volume_size ) )

    @classmethod
    def _get_node_role( cls ):
        """
        Return the role (box class) from which the node image should be created.
        """
        # Traverses the inheritance DAG upwards until we find a class that has this class as a
        # base, i.e. that mixes in this class. The traversal itself only follows the first base
        # class.
        while cls not in (ClusterBox, ClusterLeader, ClusterWorker, Box):
            if ClusterBox in cls.__bases__:
                return cls
            else:
                # noinspection PyMethodFirstArgAssignment
                cls = cls.__bases__[ 0 ]
        assert False, "Class %s doesn't have an ancestor that mixes in %s" % (cls, ClusterBox)

    def _image_name_prefix( self ):
        # The default implementation of this method derives the image name prefix from the
        # concrete class name. The leader and workers are booted from the node image so we need
        # to pin the name using the node role.
        return self._get_node_role( ).role( )

    def _security_group_name( self ):
        # The default implementation of this method derives the security group name from the
        # concrete class name. The leader and workers must use be assigned the same security
        # group (because the group allows traffic only within the group) so we need to pin
        # the name using the node role.
        return self._get_node_role( ).role( )


class ClusterLeader( ClusterBox ):
    """
    A mixin for a box that serves as a leader in a cluster
    """

    def __init__( self, ctx ):
        super( ClusterLeader, self ).__init__( ctx )
        self.preparation_args = None
        self.preparation_kwargs = None

    def prepare( self, *args, **kwargs ):
        # Stash away arguments to prepare() so we can use them when cloning the workers
        self.preparation_args = args
        self.preparation_kwargs = dict( kwargs )
        if kwargs[ 'leader_on_demand' ]:
            kwargs[ 'spot_bid' ] = None
        return super( ClusterLeader, self ).prepare( *args, **kwargs )

    def _get_instance_options( self ):
        return dict( super( ClusterLeader, self )._get_instance_options( ),
                     leader_instance_id=self.instance_id )

    def clone( self, worker_role, num_workers, worker_instance_type ):
        """
        Create a number of worker boxes that are connected to this leader.
        """
        first_worker = worker_role( self.ctx )
        args = self.preparation_args
        kwargs = dict( self.preparation_kwargs,
                       instance_type=worker_instance_type,
                       leader_instance_id=self.instance_id )
        spec = dict( first_worker.prepare( *args, **kwargs ),
                     min_count=num_workers,
                     max_count=num_workers )
        other_workers = first_worker.create( spec,
                                             wait_ready=False,
                                             cluster_ordinal=self.cluster_ordinal + 1 )
        return concat( first_worker, other_workers )


class ClusterWorker( ClusterBox ):
    """
    A mixin for a box that serves as a leader in a cluster
    """

    def __init__( self, ctx ):
        super( ClusterWorker, self ).__init__( ctx )
        self.leader_instance_id = None

    def _populate_instance_spec( self, image, spec ):
        return super( ClusterWorker, self )._populate_instance_spec( image, spec )

    def _set_instance_options( self, options ):
        super( ClusterWorker, self )._set_instance_options( options )
        self.leader_instance_id = options[ 'leader_instance_id' ]

    def _get_instance_options( self ):
        return dict( super( ClusterWorker, self )._get_instance_options( ),
                     leader_instance_id=self.leader_instance_id )
