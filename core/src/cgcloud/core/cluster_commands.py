import logging
import os
import sys
from abc import abstractmethod
from functools import partial

from bd2k.util.exceptions import panic
from bd2k.util.expando import Expando

from cgcloud.core.commands import (RecreateCommand,
                                   ContextCommand,
                                   SshCommandMixin,
                                   RsyncCommandMixin)
from cgcloud.lib.util import (abreviated_snake_case_class_name,
                              UserError,
                              heredoc,
                              thread_pool,
                              allocate_cluster_ordinals)

log = logging.getLogger( __name__ )


class ClusterTypeCommand( ContextCommand ):
    def __init__( self, application ):
        """
        Set later, once we have a context.
        :type: Cluster
        """
        super( ClusterTypeCommand, self ).__init__( application )
        self.option( '--num-threads', metavar='NUM',
                     type=int, default=100,
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
                     type=int, default=1,
                     help='The number of workers to launch.' )

        self.option( '--ebs-volume-size', '-e', metavar='GB',
                     help=heredoc( """The size in GB of an EBS volume to be attached to each node
                     for persistent data. The volume will be mounted at /mnt/persistent.""" ) )

        self.option( '--leader-on-demand', '-D',
                     default=False, action='store_true',
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

    def preparation_kwargs( self, options, box ):
        return dict( super( CreateClusterCommand, self ).preparation_kwargs( options, box ),
                     cluster_name=options.cluster_name,
                     ebs_volume_size=options.ebs_volume_size )

    def creation_kwargs( self, options, box ):
        return dict( super( CreateClusterCommand, self ).creation_kwargs( options, box ),
                     num_instances=options.num_workers )

    def option( self, option_name, *args, **kwargs ):
        _super = super( CreateClusterCommand, self )
        if option_name in ('role', '--terminate'):
            # Suppress the role positional argument since the role is hard-wired and the
            # --terminate option since it doesn't make sense when creating clusters.
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
        # Validate shared path
        if options.share_path is not None:
            if not os.path.exists( options.share_path ):
                raise UserError( "No such file or directory: '%s'" % options.share_path )
        # --leader-instance-type should default to the value of --instance-type
        if options.instance_type is None:
            options.instance_type = options.worker_instance_type
        super( CreateClusterCommand, self ).run( options )

    def run_on_cluster_type( self, ctx, options, cluster_type ):
        self.cluster = cluster_type( ctx )
        leader_role = self.cluster.leader_role
        options.role = leader_role.role( )
        self.run_on_role( options, ctx, leader_role )

    def run_on_box( self, options, leader ):
        """
        :type leader: cgcloud.core.box.Box
        """
        log.info( '=== Creating leader ===' )
        preparation_kwargs = self.preparation_kwargs( options, leader )
        if options.leader_on_demand:
            preparation_kwargs = { k: v for k, v in preparation_kwargs.iteritems( )
                if not k.startswith( 'spot_' ) }
        spec = leader.prepare( **preparation_kwargs )
        creation_kwargs = dict( self.creation_kwargs( options, leader ),
                                num_instances=1,
                                # We must always wait for the leader since workers depend on it.
                                wait_ready=True )
        leader.create( spec, **creation_kwargs )
        try:
            self.run_on_creation( leader, options )
        except:
            if options.terminate is not False:
                with panic( log ):
                    leader.terminate( wait=False )
            raise
        # Leader is fully setup, even if the code below fails to add workers,
        # the GrowClusterCommand can be used to recover from that failure.
        if options.num_workers:
            log.info( '=== Creating workers ===' )
            first_worker = self.cluster.worker_role( leader.ctx )
            preparation_kwargs = dict( self.preparation_kwargs( options, first_worker ),
                                       leader_instance_id=leader.instance_id,
                                       instance_type=options.worker_instance_type )
            spec = first_worker.prepare( **preparation_kwargs )
            with thread_pool( min( options.num_threads, options.num_workers ) ) as pool:
                workers = first_worker.create( spec,
                                               cluster_ordinal=leader.cluster_ordinal + 1,
                                               executor=pool.apply_async,
                                               **self.creation_kwargs( options, first_worker ) )
        else:
            workers = [ ]
        if options.list:
            self.list( [ leader ] )
            self.list( workers, print_headers=False )
        self.log_ssh_hint( options )

    def run_on_creation( self, leader, options ):
        local_path = options.share_path
        if local_path is not None:
            log.info( '=== Copying %s%s to ~/shared on leader ===',
                      'the contents of ' if local_path.endswith( '/' ) else '', local_path )
            leader.rsync( args=[ '-r', local_path, ":shared/" ], ssh_opts=options.ssh_opts )

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
    Increase the size of the cluster
    """

    def __init__( self, application ):
        super( GrowClusterCommand, self ).__init__( application )
        self.cluster = None
        self.option( '--num-workers', '-s', metavar='NUM',
                     type=int, default=1,
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

    def creation_kwargs( self, options, box ):
        return dict( super( GrowClusterCommand, self ).creation_kwargs( options, box ),
                     num_instances=options.num_workers )

    def run_on_box( self, options, first_worker ):
        """
        :param cgcloud.core.box.Box first_worker:
        """
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
        cluster_ordinal = allocate_cluster_ordinals( num=options.num_workers,
                                                     used=used_cluster_ordinals )
        first_worker.unbind( )  # list() bound it
        spec = first_worker.prepare( leader_instance_id=leader.instance_id,
                                     cluster_name=leader.cluster_name,
                                     **self.preparation_kwargs( options, first_worker ) )
        with thread_pool( min( options.num_threads, options.num_workers ) ) as pool:
            workers = first_worker.create( spec,
                                           cluster_ordinal=cluster_ordinal,
                                           executor=pool.apply_async,
                                           **self.creation_kwargs( options, first_worker ) )
        if options.list:
            self.list( workers )


class ApplyClusterCommand( ClusterCommand ):
    """
    A command that applies an operation to a running cluster.
    """

    def __init__( self, application ):
        super( ApplyClusterCommand, self ).__init__( application )
        self.option( '--skip-leader', '-L', default=False, action='store_true',
                     help=heredoc( """Don't perform the operation on the leader.""" ) )


class ClusterLifecycleCommand( ApplyClusterCommand ):
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
                       skip_leader=options.skip_leader,
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
        self.option( '--quick', '-Q', default=False, action='store_true',
                     help="""Exit immediately after termination request has been made, don't wait
                     until the cluster is terminated.""" )

    def run_on_node( self, options, node ):
        node.terminate( wait=not options.quick )


# NB: The ordering of bases affects ordering of positionals

class SshClusterCommand( SshCommandMixin, ApplyClusterCommand ):
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
        exit_codes = [ ]
        cluster.apply( partial( self.ssh, options ),
                       cluster_name=options.cluster_name,
                       ordinal=options.ordinal,
                       leader_first=True,
                       skip_leader=options.skip_leader,
                       pool_size=options.num_threads if options.parallel else 0,
                       wait_ready=False,
                       callback=exit_codes.append )
        if any( exit_code for exit_code in exit_codes ):
            sys.exit( 2 )


class RsyncClusterCommand( RsyncCommandMixin, ApplyClusterCommand ):
    """
    Run rsync against each node in a cluster. The rsync program will be run against master first,
    followed by all workers in parallel. To avoid being prompted for confirmation of the host
    key, use --ssh-opts="-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no".
    """

    def run_on_cluster( self, options, ctx, cluster ):
        cluster.apply( partial( self.rsync, options ),
                       cluster_name=options.cluster_name,
                       ordinal=options.ordinal,
                       leader_first=True,
                       skip_leader=options.skip_leader,
                       pool_size=options.num_threads,
                       wait_ready=False )
