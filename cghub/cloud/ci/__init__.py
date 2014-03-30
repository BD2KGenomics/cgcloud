from cghub.cloud.ci.commands import *
from cghub.cloud.ci.generic_jenkins_slaves import *
from cghub.cloud.ci.genetorrent_jenkins_slaves import *
from cghub.cloud.ci.jenkins_master import *
from cghub.cloud.ci.rpmbuild_jenkins_slaves import *

BOXES = [
    JenkinsMaster,

    UbuntuLucidGenetorrentJenkinsSlave,
    UbuntuPreciseGenetorrentJenkinsSlave,
    UbuntuSaucyGenetorrentJenkinsSlave,
    Centos5GenetorrentJenkinsSlave,
    Centos6GenetorrentJenkinsSlave,
    Fedora19GenetorrentJenkinsSlave,
    Fedora20GenetorrentJenkinsSlave,

    UbuntuLucidGenericJenkinsSlave,
    UbuntuPreciseGenericJenkinsSlave,
    UbuntuSaucyGenericJenkinsSlave,
    Centos5GenericJenkinsSlave,
    Centos6GenericJenkinsSlave,
    Fedora19GenericJenkinsSlave,
    Fedora20GenericJenkinsSlave,

    Centos5RpmbuildJenkinsSlave,
    Centos6RpmbuildJenkinsSlave ]

COMMANDS = [
    RegisterSlaves ]