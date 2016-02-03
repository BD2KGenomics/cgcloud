from abc import abstractmethod
from functools import partial
import logging
import os

from itertools import count, islice
from bd2k.util.expando import Expando
from bd2k.util.iterables import concat

from cgcloud.core.commands import (RecreateCommand, ContextCommand, SshCommandMixin,
                                   RsyncCommandMixin)
from cgcloud.lib.util import abreviated_snake_case_class_name, UserError, heredoc, thread_pool

log = logging.getLogger( __name__ )


class ClusterTypeCommand( ContextCommand ):
    def __init__( self, application ):
        """
        Set later, once we have a context.
        :type: Cluster
        """
        super( ClusterTypeCommand, self ).__init__( application )
        self.option( '--num-threads', metavar='NUM',
                     type=int, default=100, dest='num_threads',
                     help='The maximum number of tasks to be performed concurrently.' )

        self.option( 'cluster_type', metavar='TYPE',
                     completer=self.completer,
                     help=heredoc( """The type of the cluster to be used. The cluster type is
                     covariant with the role of the leader node. For example, a box performing
                     the 'foo-leader' role will be part of a cluster of type 'foo'.""" ) )

    # noinspection PyUnusedLocal
    def completer( self, prefix, **kwargs ):
        return [ cluster_type
            for cluster_type in self.application.cluster_types.iterkeys( )
            if cluster_type.startswith( prefix ) ]

    def run_in_ctx( self, options, ctx ):
        try:
            cluster_type = self.application.cluster_types[ options.cluster_type ]
        except KeyError:
            raise UserError( "Unknown cluster type '%s'" % options.cluster_type )
        self.run_on_cluster_type( ctx, options, cluster_type )

    @abstractmethod
    def run_on_cluster_type( self, ctx, options, cluster_type ):
        raise NotImplementedError( )


class CreateClusterCommand( ClusterTypeCommand, RecreateCommand ):
    """
    Creates a cluster with one leader and one or more workers.
    """

    def __init__( self, application ):
        super( CreateClusterCommand, self ).__init__( application )
        self.cluster = None

        self.option( '--cluster-name', '-c', metavar='NAME',
                     help=heredoc( """A name for the new cluster. If absent, the instance ID of
                     the master will be used. Cluster names do not need to be unique, but they
                     should be in order to avoid user error.""" ) )

        self.option( '--num-workers', '-s', metavar='NUM',
                     type=int, default=1, dest='num_workers',
                     help='The number of workers to launch.' )

        self.option( '--ebs-volume-size', '-e', metavar='GB',
                     help=heredoc( """The size in GB of an EBS volume to be attached to each node
                     for persistent data. The volume will be mounted at /mnt/persistent.""" ) )

        self.option( '--leader-on-demand', '-D',
                     dest='leader_on_demand', default=False, action='store_true',
                     help=heredoc( """Use this option to insure that the leader will be an
                     on-demand instance, even if --spot-bid is given.""" ) )

        self.option( '--share', '-S', metavar='PATH',
                     default=None, dest='share_path',
                     help=heredoc( """The path to a local file or directory for distribution to
                     the cluster. The given file or directory (or the contents of the given
                     directory, if the path ends in a slash) will be placed in the default user's
                     ~/shared directory on each node.""" ) )

        self.option( '--ssh-opts', metavar='OPTS', default=None,
                     help=heredoc( """Additional options to pass to ssh when uploading the files
                     shared via rsync. For more detail refer to cgcloud rsync --help""" ) )

    def instance_options( self, options, box ):
        return dict( super( CreateClusterCommand, self ).instance_options( options, box ),
                     cluster_name=options.cluster_name,
                     leader_on_demand=options.leader_on_demand,
                     ebs_volume_size=options.ebs_volume_size )

    def option( self, option_name, *args, **kwargs ):
        _super = super( CreateClusterCommand, self )
        if option_name in ('role', '--terminate'):
            # Suppress the role positional argument since the role is hard-wired and the
            # --terminate option since it doesn't make sense here.
            return
        if option_name == '--instance-type':
            # We want --instance-type to apply to the workers and --leader-instance-type to the
            # leader. Furthermore, we want --leader-instance-type to default to the value of
            # --instance-type.
            assert 'dest' not in kwargs
            assert args[ 0 ] == '-t'
            kwargs[ 'help' ] = kwargs[ 'help' ].replace( 'for the box',
                                                         'for the leader' )
            _super.option( '--leader-instance-type', '-T',
                           *args[ 1: ], dest='instance_type', **kwargs )
            kwargs[ 'help' ] = kwargs[ 'help' ].replace( 'leader', 'workers' )
            kwargs[ 'dest' ] = 'worker_instance_type'
        _super.option( option_name, *args, **kwargs )

    def run( self, options ):
        if options.share_path is not None:
            if not os.path.exists( options.share_path ):
                raise UserError( "No such file or directory: '%s'" % options.share_path )
        # --leader-instance-type should default to the value of --instance-type
        if options.instance_type is None:
            options.instance_type = options.worker_instance_type
        super( CreateClusterCommand, self ).run( options )

    def run_on_cluster_type( self, ctx, options, cluster_type ):
        self.cluster = cluster_type( ctx )
        log.info( '=== Creating leader ===' )
        options.role = self.cluster.leader_role.role( )
        self.run_on_role( options, ctx, self.cluster.leader_role )

    def run_on_creation( self, leader, options ):
        local_path = options.share_path
        if local_path is not None:
            log.info( '=== Copying %s%s to ~/shared on leader ===',
                      'the contents of ' if local_path.endswith( '/' ) else '', local_path )
            leader.rsync( args=[ '-r', local_path, ":shared/" ], ssh_opts=options.ssh_opts )
        log.info( '=== Creating workers ===' )
        leader.clone( worker_role=self.cluster.worker_role,
                      num_workers=options.num_workers,
                      worker_instance_type=options.worker_instance_type,
                      pool_size=min( options.num_threads, options.num_workers ))

    def ssh_hint( self, options ):
        hint = super( CreateClusterCommand, self ).ssh_hint( options )
        hint.options.append( Expando( name='-c', value=options.cluster_name, default=None ) )
        hint.object = 'cluster'
        return hint


class ClusterCommand( ClusterTypeCommand ):
    def __init__( self, application ):
        super( ClusterCommand, self ).__init__( application )

        self.option( '--cluster-name', '-c', metavar='NAME',
                     help=heredoc( """The name of the cluster to operate on. The default is to
                     consider all clusters of the given type regardless of their name,
                     using --ordinal to disambiguate. Note that the cluster name is not
                     necessarily unique, not even with a specific cluster type, there may be more
                     than one cluster of a particular name and type.""" ) )

        self.option( '--ordinal', '-o', default=-1, type=int,
                     help=heredoc( """Selects an individual cluster from the list of currently
                     running clusters of the given cluster type and name. Since there is one
                     leader per cluster, this is equal to the ordinal of the leader among all
                     leaders of clusters of the given type and name. The ordinal is a zero-based
                     index into the list of all clusters of the specified type and name,
                     sorted by creation time. This means that the ordinal of a cluster is not
                     fixed, it may change if another cluster of the same type and name is
                     terminated. If the ordinal is negative, it will be converted to a positive
                     ordinal by adding the number of clusters of the specified type. Passing -1,
                     for example, selects the most recently created box.""" ) )

    def run_on_cluster_type( self, ctx, options, cluster_type ):
        cluster = cluster_type( ctx )
        self.run_on_cluster( options, ctx, cluster )

    @abstractmethod
    def run_on_cluster( self, options, ctx, cluster ):
        raise NotImplementedError( )


class GrowClusterCommand( ClusterCommand, RecreateCommand ):
    """
    Increase
    """

    def __init__( self, application ):
        super( GrowClusterCommand, self ).__init__( application )
        self.cluster = None

        self.option( '--num-workers', '-s', metavar='NUM',
                     type=int, default=1, dest='num_workers',
                     help='The number of workers to add.' )

    def option( self, option_name, *args, **kwargs ):
        _super = super( GrowClusterCommand, self )
        if option_name in ('role', '--terminate'):
            # Suppress the role positional argument since the role is hard-wired and the
            # --terminate option since it doesn't make sense here.
            return
        if option_name == '--instance-type':
            assert 'dest' not in kwargs
            assert args[ 0 ] == '-t'
            kwargs[ 'help' ] = kwargs[ 'help' ].replace( 'for the box',
                                                         'for the workers' )
        _super.option( option_name, *args, **kwargs )

    def run_on_cluster( self, options, ctx, cluster ):
        self.cluster = cluster
        options.role = self.cluster.worker_role.role( )
        self.run_on_role( options, ctx, self.cluster.worker_role )

    def instance_options( self, options, box ):
        return dict( super( GrowClusterCommand, self ).instance_options( options, box ),
                     cluster_name=options.cluster_name,
                     num_instances=options.num_workers )

    def run_on_box( self, options, first_worker ):
        log.info( '=== Binding to leader ===' )
        leader = self.cluster.leader_role( self.cluster.ctx )
        leader.bind( cluster_name=options.cluster_name,
                     ordinal=options.ordinal,
                     wait_ready=False )
        log.info( '=== Creating workers  ===' )
        workers = first_worker.list( leader_instance_id=leader.instance_id )
        used_cluster_ordinals = set( w.cluster_ordinal for w in workers )
        assert len( used_cluster_ordinals ) == len( workers )  # check for collisions
        assert 0 not in used_cluster_ordinals  # master has 0
        used_cluster_ordinals.add( 0 )  # to make the math easier
        cluster_ordinal = self.allocate_cluster_ordinals( num=options.num_workers,
                                                          used=used_cluster_ordinals )
        spec = first_worker.prepare( leader_instance_id=leader.instance_id,
                                     **self.instance_options( options, first_worker ) )
        with thread_pool( min( options.num_threads, options.num_workers ) ) as pool:
            first_worker.create( spec,
                                 wait_ready=True,
                                 cluster_ordinal=cluster_ordinal,
                                 executor=pool.apply_async )

    @staticmethod
    def allocate_cluster_ordinals( num, used ):
        """
        Return an iterator containing a given number of unused cluster ordinals. The result is
        guaranteed to yield each ordinal exactly once, i.e. the result is set-like. The argument
        set and the result iterator will be disjoint. The sum of all ordinals in the argument and
        the result is guaranteed to be minimal, i.e. the function will first fill the gaps in the
        argument before allocating higher values. The result will yield ordinal in ascending order.

        :param int num: the number of ordinal to allocate
        :param set[int] used: a set of currently used ordinal
        :rtype: iterator

        >>> f = GrowClusterCommand.allocate_cluster_ordinals

        >>> list(f(0,set()))
        []
        >>> list(f(1,set()))
        [0]
        >>> list(f(0,{0}))
        []
        >>> list(f(1,{0}))
        [1]
        >>> list(f(0,{0,1}))
        []
        >>> list(f(1,{0,1}))
        [2]
        >>> list(f(0,{0,2}))
        []
        >>> list(f(1,{0,2}))
        [1]
        >>> list(f(2,{0,2}))
        [1, 3]
        >>> list(f(3,{0,2}))
        [1, 3, 4]
        """
        assert isinstance( used, set )
        first_free = max( used ) + 1 if used else 0
        complete = set( range( 0, len( used ) ) )
        gaps = sorted( complete - used )
        return islice( concat( gaps, count( first_free ) ), num )


class ClusterLifecycleCommand( ClusterCommand ):
    """
    A command that runs a simple method on each node in a cluster
    """
    leader_first = True
    wait_ready = False

    def run_on_cluster( self, options, ctx, cluster ):
        cluster.apply( partial( self.run_on_node, options ),
                       cluster_name=options.cluster_name,
                       ordinal=options.ordinal,
                       leader_first=self.leader_first,
                       wait_ready=self.wait_ready,
                       pool_size=options.num_threads,
                       operation=self.operation( ) + '()' )

    def run_on_node( self, options, node ):
        getattr( node, self.operation( ) )( )

    def operation( self ):
        return abreviated_snake_case_class_name( self.__class__, ClusterCommand )


class StopClusterCommand( ClusterLifecycleCommand ):
    """
    Stop all nodes of a cluster
    """
    leader_first = False


class StartClusterCommand( ClusterLifecycleCommand ):
    """
    Start all nodes of a cluster
    """
    leader_first = True


class TerminateClusterCommand( ClusterLifecycleCommand ):
    """
    Terminate all nodes of a cluster
    """
    leader_first = False

    def __init__( self, application ):
        super( TerminateClusterCommand, self ).__init__( application )
        self.option( '--quick', '-q', default=False, action='store_true',
                     help="""Exit immediately after termination request has been made, don't wait
                     until the cluster is terminated.""" )

    def run_on_node( self, options, node ):
        node.terminate( wait=not options.quick )


# NB: The ordering of bases affects ordering of positionals

class SshClusterCommand( SshCommandMixin, ClusterCommand ):
    """
    Run a command via SSH on each node of a cluster. The command is run on the leader first,
    followed by the workers, serially by default or optionally in parallel.
    """

    def __init__( self, application ):
        super( SshClusterCommand, self ).__init__( application )
        self.option( '--parallel', '-P', default=False, action='store_true',
                     help=heredoc( """Run command on the workers in parallel. Note that this
                     doesn't work if SSH or the command itself prompts for input. This will
                     likely be the case on the first connection attempt when SSH typically
                     prompts for confirmation of the host key. An insecure work-around is to pass
                     "-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no".""" ) )

    def run_on_cluster( self, options, ctx, cluster ):
        cluster.apply( partial( self.ssh, options ),
                       cluster_name=options.cluster_name,
                       ordinal=options.ordinal,
                       leader_first=True,
                       pool_size=options.num_threads if options.parallel else 1,
                       wait_ready=False )


class RsyncClusterCommand( RsyncCommandMixin, ClusterCommand ):
    """
    Run rsync against each node in a cluster. The rsync program will be run against master first,
    followed by all workers in parallel. To avoid being prompted for confirmation of the host
    key, use --ssh-opts="-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no".
    """

    def run_on_cluster( self, options, ctx, cluster ):
        cluster.apply( partial( self.rsync, options ),
                       cluster_name=options.cluster_name,
                       ordinal=options.ordinal,
                       pool_size=options.num_threads,
                       leader_first=True,
                       wait_ready=False )
