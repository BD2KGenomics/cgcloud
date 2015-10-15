def roles( ):
    from cgcloud.spark.spark_box import SparkBox, SparkSlave, SparkMaster
    return sorted( locals( ).values( ), key=lambda cls: cls.__name__ )


def command_classes( ):
    from cgcloud.spark.spark_cluster import CreateSparkCluster
    return sorted( locals( ).values( ), key=lambda cls: cls.__name__ )
