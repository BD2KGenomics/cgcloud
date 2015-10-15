def roles( ):
    from cgcloud.toil.toil_box import ToilBox, ToilLeader, ToilWorker
    return sorted( locals( ).values( ), key=lambda cls: cls.__name__ )


def command_classes( ):
    from cgcloud.toil.toil_cluster import CreateToilCluster
    return sorted( locals( ).values( ), key=lambda cls: cls.__name__ )
