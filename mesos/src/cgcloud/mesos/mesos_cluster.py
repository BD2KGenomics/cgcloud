from cgcloud.core.cluster import Cluster
from cgcloud.mesos.mesos_box import MesosMaster, MesosSlave


class MesosCluster( Cluster ):
    @property
    def worker_role( self ):
        return MesosSlave

    @property
    def leader_role( self ):
        return MesosMaster
