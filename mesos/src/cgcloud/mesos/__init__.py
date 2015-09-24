def roles( ):
    from cgcloud.mesos.mesos_box import MesosBox, MesosMaster, MesosSlave
    return [ MesosBox, MesosMaster, MesosSlave ]


def commands( ):
    from cgcloud.mesos.mesos_cluster import CreateMesosCluster
    return [ CreateMesosCluster ]
