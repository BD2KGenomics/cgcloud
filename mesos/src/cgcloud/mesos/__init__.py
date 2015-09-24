def roles( ):
    from cgcloud.mesos.mesos_box import MesosBox, MesosMaster, MesosSlave
    return [ MesosBox, MesosMaster, MesosSlave ]


def command_classes( ):
    from cgcloud.mesos.mesos_cluster import CreateMesosCluster
    return [ CreateMesosCluster ]
