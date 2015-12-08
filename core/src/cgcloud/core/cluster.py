import logging
import multiprocessing
import multiprocessing.pool
from abc import ABCMeta, abstractproperty
from contextlib import contextmanager
from copy import copy

from bd2k.util.iterables import concat

from cgcloud.core.box import Box
from cgcloud.lib.util import abreviated_snake_case_class_name

log = logging.getLogger( __name__ )


class Cluster( object ):
    """
    A cluster consists of one leader box and N worker boxes. A box that is part of a cluster is
    referred to as "node". There is one role (subclass of Box) describing the leader node and
    another one describing the workers. Leader and worker roles are siblings and their common
    ancestor--the node role--describes the software deployed on them, which is identical for both
    leader and workers. The node role is used to create the single image from which the actual
    nodes will be booted from when the cluster is created. In other words, the specialization
    into leader and workers happens at cluster creation time, not earlier.
    """
    __metaclass__ = ABCMeta

    def __init__( self, ctx ):
        super( Cluster, self ).__init__( )
        self.ctx = ctx

    @abstractproperty
    def leader_role( self ):
        """
        :return: The Box subclass to use for the leader
        """
        raise NotImplementedError( )

    @abstractproperty
    def worker_role( self ):
        """
        :return: The Box subclass to use for the workers
        """
        raise NotImplementedError( )

    @classmethod
    def name( cls ):
        return abreviated_snake_case_class_name( cls, Cluster )

    def apply( self, f, cluster_name=None, ordinal=None, leader_first=True, wait_ready=True,
               operation='operation', pool_size=None ):
        """
        Apply a callable to the leader and each worker. The callable may be applied to multiple
        workers concurrently.
        """
        # Look up the leader first, even if leader_first is False, that way we fail early if the
        # cluster doesn't exist.
        leader = self.leader_role( self.ctx )
        leader.bind( cluster_name=cluster_name, ordinal=ordinal, wait_ready=wait_ready )
        first_worker = self.worker_role( self.ctx )

        def apply_leader( ):
            log.info( '=== Performing %s on leader ===', operation )
            f( leader )

        def clones( ):
            while True:
                yield copy( first_worker )

        def apply_workers( ):
            log.info( '=== Performing %s on workers ===', operation )
            instances = first_worker.list( leader_instance_id=leader.instance_id )
            papply( apply_worker,
                    pool_size=pool_size,
                    seq=zip( concat( first_worker, clones( ) ),
                             (i.id for i in instances) ) )

        def apply_worker( worker, instance_id ):
            worker.bind( instance_id=instance_id, wait_ready=wait_ready )
            f( worker )

        if leader_first:
            apply_leader( )
            apply_workers( )
        else:
            apply_workers( )
            apply_leader( )


class ClusterBox( Box ):
    """
    A mixin for a box that is part of a cluster
    """

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
            del kwargs[ 'spot_bid' ]
            del kwargs[ 'launch_group' ]
        return super( ClusterLeader, self ).prepare( *args, **kwargs )

    def _get_instance_options( self ):
        return dict( super( ClusterLeader, self )._get_instance_options( ),
                     leader_instance_id=self.instance_id )

    def clone( self, worker_role, num_workers, worker_instance_type, wait_ready=True ):
        """
        Create a number of worker boxes that are connected to this leader.
        """
        first_worker = worker_role( self.ctx )
        args = self.preparation_args
        kwargs = dict( self.preparation_kwargs,
                       instance_type=worker_instance_type,
                       leader_instance_id=self.instance_id )
        spec = first_worker.prepare( *args, **kwargs )
        spec.min_count = num_workers
        spec.max_count = num_workers
        with thread_pool( size=default_pool_size( num_workers ) ) as pool:
            first_worker.create( spec,
                                 wait_ready=wait_ready,
                                 cluster_ordinal=self.cluster_ordinal + 1,
                                 executor=pool.apply_async )


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
                     leader_instance_id=self.leader_instance_id,
                     cluster_name=self.cluster_name or self.leader_instance_id )


@contextmanager
def thread_pool( size ):
    pool = multiprocessing.pool.ThreadPool( processes=size )
    try:
        yield pool
    except:
        pool.terminate( )
        raise
    else:
        pool.close( )
        pool.join( )


def pmap( f, seq, pool_size=None ):
    """
    >>> pmap( lambda (a, b): a + b, [] )
    []
    >>> pmap( lambda (a, b): a + b, [ (1, 2) ] )
    [3]
    >>> pmap( lambda (a, b): a + b, [ (1, 2), (3, 4) ] )
    [3, 7]
    >>> pmap( lambda a, b: a + b, [ (1, 2), (3, 4) ] )
    Traceback (most recent call last):
    ...
    TypeError: <lambda>() takes exactly 2 arguments (1 given)
    """
    if pool_size is None:
        pool_size = default_pool_size( len( seq ) )
    with thread_pool( pool_size ) as pool:
        return pool.map( f, seq )


def papply( f, seq, pool_size=None, callback=None ):
    """
    >>> l=[]; papply( lambda a, b: a + b, [], 1, callback=l.append ); l
    []
    >>> l=[]; papply( lambda a, b: a + b, [ (1, 2) ], 1, callback=l.append); l
    [3]
    >>> l=[]; papply( lambda a, b: a + b, [ (1, 2), (3, 4) ], 1, callback=l.append ); l
    [3, 7]
    """
    if pool_size is None:
        pool_size = default_pool_size( len( seq ) )
    if pool_size == 1:
        for args in seq:
            result = apply( f, args )
            if callback is not None:
                callback( result )
    else:
        with thread_pool( pool_size ) as pool:
            for args in seq:
                pool.apply_async( f, args, callback=callback )


def default_pool_size( num_tasks ):
    return max( 1, min( num_tasks, multiprocessing.cpu_count( ) * 10 ) )
