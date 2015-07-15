from cgcloud.jobtree.jobtree_box import JobTreeBox, JobTreeLeader, JobTreeWorker
from cgcloud.jobtree.jobtree_cluster import CreateJobTreeCluster

BOXES = [ JobTreeBox, JobTreeLeader, JobTreeWorker ]
COMMANDS = [ CreateJobTreeCluster ]