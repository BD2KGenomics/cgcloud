def roles( ):
    from cgcloud.mesos.mesos_box import MesosBox, MesosMaster, MesosSlave
    return sorted( locals( ).values( ), key=lambda cls: cls.__name__ )


def command_classes( ):
    from cgcloud.mesos.mesos_cluster import CreateMesosCluster
    return sorted( locals( ).values( ), key=lambda cls: cls.__name__ )
