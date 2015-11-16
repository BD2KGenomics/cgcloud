def roles( ):
    from cgcloud.toil.toil_box import (ToilBox, ToilLatestBox, ToilLeader, ToilWorker)
    return sorted( locals( ).values( ), key=lambda cls: cls.__name__ )


def cluster_types( ):
    from cgcloud.toil.toil_cluster import ToilCluster
    return sorted( locals( ).values( ), key=lambda cls: cls.__name__ )
