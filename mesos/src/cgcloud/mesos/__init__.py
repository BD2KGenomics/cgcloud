def roles( ):
    from cgcloud.mesos.mesos_box import MesosBox, MesosMaster, MesosSlave
    return sorted( locals( ).values( ), key=lambda cls: cls.__name__ )


def cluster_types( ):
    from cgcloud.mesos.mesos_cluster import MesosCluster
    return sorted( locals( ).values( ), key=lambda cls: cls.__name__ )
