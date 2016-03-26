import logging
from abc import ABCMeta, abstractproperty

from cgcloud.core.box import Box
from cgcloud.lib.util import (abreviated_snake_case_class_name, papply, thread_pool)

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

    def apply( self, f, cluster_name=None, ordinal=None, leader_first=True, skip_leader=False,
               wait_ready=True, operation='operation', pool_size=None, callback=None ):
        """
        Apply a callable to the leader and each worker. The callable may be applied to multiple
        workers concurrently.
        """
        # Look up the leader first, even if leader_first is False or skip_leader is True. That
        # way we fail early if the cluster doesn't exist.
        leader = self.leader_role( self.ctx )
        leader.bind( cluster_name=cluster_name, ordinal=ordinal, wait_ready=wait_ready )
        first_worker = self.worker_role( self.ctx )

        def apply_leader( ):
            if not skip_leader:
                log.info( '=== Performing %s on leader ===', operation )
                result = f( leader )
                if callback is not None:
                    callback( result )

        def apply_workers( ):
            log.info( '=== Performing %s on workers ===', operation )
            workers = first_worker.list( leader_instance_id=leader.instance_id,
                                         wait_ready=wait_ready )
            # zip() creates the singleton tuples that papply() expects
            papply( f, seq=zip( workers ), pool_size=pool_size, callback=callback )

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
                     ebs_volume_size=str( self.ebs_volume_size ),
                     leader_instance_id=self.instance_id)

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
    def _get_instance_options( self ):
        return dict( super( ClusterLeader, self )._get_instance_options( ) )


class ClusterWorker( ClusterBox ):
    """
    A mixin for a box that serves as a leader in a cluster
    """

    def __init__( self, ctx ):
        super( ClusterWorker, self ).__init__( ctx )
        self.leader_instance_id = None

    def _set_instance_options( self, options ):
        super( ClusterWorker, self )._set_instance_options( options )
        self.leader_instance_id = options.get( 'leader_instance_id' )
        if self.cluster_name is None:
            self.cluster_name = self.leader_instance_id

    def _get_instance_options( self ):
        return dict( super( ClusterWorker, self )._get_instance_options( ),
                     leader_instance_id=self.leader_instance_id )
