from cgcloud.toil.toil_box import ToilBox, ToilLeader, ToilWorker
from cgcloud.toil.toil_cluster import CreateToilCluster

BOXES = [ ToilBox, ToilLeader, ToilWorker ]
COMMANDS = [ CreateToilCluster ]
