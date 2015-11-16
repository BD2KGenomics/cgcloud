def roles( ):
    from cgcloud.spark.spark_box import SparkBox, SparkSlave, SparkMaster
    return sorted( locals( ).values( ), key=lambda cls: cls.__name__ )


def cluster_types( ):
    from cgcloud.spark.spark_cluster import SparkCluster
    return sorted( locals( ).values( ), key=lambda cls: cls.__name__ )
