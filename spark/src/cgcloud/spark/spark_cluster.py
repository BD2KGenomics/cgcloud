import logging

from cgcloud.core.cluster import ClusterCommand
from cgcloud.spark.spark_box import SparkMaster, SparkSlave

log = logging.getLogger( __name__ )


class CreateSparkCluster( ClusterCommand ):
    """
    Start a cluster of spark-box instances, by recreating the master from a spark-box image
    first, then cloning the master into the slaves.
    """

    def __init__( self, application ):
        super( CreateSparkCluster, self ).__init__( application=application,
                                                    leader_role=SparkMaster,
                                                    worker_role=SparkSlave,
                                                    leader='master',
                                                    worker='slave' )
