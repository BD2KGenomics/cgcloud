import logging
from cgcloud.core.cluster import ClusterCommand
from cgcloud.toil.toil_box import ToilLeader, ToilWorker

log = logging.getLogger( __name__ )


class CreateToilCluster( ClusterCommand ):

    def __init__( self, application ):
        super( CreateToilCluster, self ).__init__( application,
                                                   leader_role=ToilLeader,
                                                   worker_role=ToilWorker )

