def roles( ):
    from cgcloud.spark.spark_box import SparkBox, SparkSlave, SparkMaster
    return [ SparkBox, SparkMaster, SparkSlave ]


def command_classes( ):
    from cgcloud.spark.spark_cluster import CreateSparkCluster
    return [ CreateSparkCluster ]
