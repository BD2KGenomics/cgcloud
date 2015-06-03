from cgcloud.bd2k.ci.cgcloud_jenkins_slave import *
from cgcloud.bd2k.ci.commands import *
from cgcloud.bd2k.ci.generic_jenkins_slaves import *
from cgcloud.bd2k.ci.jenkins_master import *
from cgcloud.bd2k.ci.jobtree_jenkins_slave import *
from cgcloud.bd2k.ci.rpmbuild_jenkins_slaves import *

BOXES = [
    JenkinsMaster,

    UbuntuLucidGenericJenkinsSlave,
    UbuntuPreciseGenericJenkinsSlave,
    UbuntuTrustyGenericJenkinsSlave,
    Centos5GenericJenkinsSlave,
    Centos6GenericJenkinsSlave,
    Fedora19GenericJenkinsSlave,
    Fedora20GenericJenkinsSlave,

    Centos5RpmbuildJenkinsSlave,
    Centos6RpmbuildJenkinsSlave,

    CgcloudJenkinsSlave,
    JobtreeJenkinsSlave]

COMMANDS = [
    RegisterSlaves ]
