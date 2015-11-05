import logging
from cgcloud.core.cluster import ClusterCommand
from cgcloud.mesos.mesos_box import shared_dir
from cgcloud.toil.toil_box import ToilLeader, ToilWorker

log = logging.getLogger( __name__ )


class CreateToilCluster( ClusterCommand ):

    def __init__( self, application ):
        super( CreateToilCluster, self ).__init__( application,
                                                   leader_role=ToilLeader,
                                                   worker_role=ToilWorker )
        self.option( '--shared-dir', default=None,
                     help='The absolute path to a local directory to distribute onto each node.' )

    def run_on_creation( self, leader, options ):
        local_dir = options.shared_dir
        if local_dir:
            log.info( 'Rsyncing %s to %s on leader', local_dir, shared_dir )
            leader.rsync( args=[ '-r', local_dir, ":" + shared_dir ] )
        super( CreateToilCluster, self ).run_on_creation( leader, options )
