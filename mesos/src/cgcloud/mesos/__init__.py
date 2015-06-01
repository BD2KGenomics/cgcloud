from cgcloud.mesos.mesos_box import MesosBox, MesosMaster, MesosSlave
from cgcloud.mesos.mesos_cluster import CreateMesosCluster

BOXES = [ MesosBox, MesosMaster, MesosSlave ]
COMMANDS = [ CreateMesosCluster ]