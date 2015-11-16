from cgcloud.core.cluster import Cluster
from cgcloud.spark.spark_box import SparkMaster, SparkSlave


class SparkCluster( Cluster ):
    @property
    def worker_role( self ):
        return SparkSlave

    @property
    def leader_role( self ):
        return SparkMaster
