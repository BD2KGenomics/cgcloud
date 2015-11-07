import logging

from cgcloud.core.cluster import ClusterCommand
from cgcloud.mesos.mesos_box import MesosMaster, MesosSlave
from cgcloud.mesos.mesos_box import shared_dir

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
        self.option( '--shared-dir', default=None,
                     help='The absolute path to a local directory to distribute onto each node.' )

    def run_on_creation( self, leader, options ):
        local_dir = options.shared_dir
        if local_dir:
            log.info( 'Rsyncing %s to %s on leader', local_dir, shared_dir )
            leader.rsync( args=[ '-r', local_dir, ":" + shared_dir ] )
        super( CreateMesosCluster, self ).run_on_creation( leader, options )
