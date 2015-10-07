def roles( ):
    from cgcloud.toil.toil_box import ToilBox, ToilLeader, ToilWorker
    return [ ToilBox, ToilLeader, ToilWorker ]


def command_classes( ):
    from cgcloud.toil.toil_cluster import CreateToilCluster
    return [ CreateToilCluster ]
