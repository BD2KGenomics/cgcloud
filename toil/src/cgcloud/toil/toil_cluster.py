from cgcloud.core.cluster import Cluster
from cgcloud.toil.toil_box import ToilLeader, ToilWorker


class ToilCluster( Cluster ):
    @property
    def worker_role( self ):
        return ToilWorker

    @property
    def leader_role( self ):
        return ToilLeader
