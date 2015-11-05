import logging

from cgcloud.core.cluster import ClusterCommand
from cgcloud.mesos.mesos_box import MesosMaster, MesosSlave

log = logging.getLogger( __name__ )


class CreateMesosCluster( ClusterCommand ):
    """
    Start a cluster of mesos-box instances, by recreating the master from a mesos-box image
    first, then cloning the master into the slaves.
    """

    def __init__( self, application ):
        super( CreateMesosCluster, self ).__init__( application,
                                                    leader_role=MesosMaster,
                                                    worker_role=MesosSlave,
                                                    leader='master',
                                                    worker='slave' )
