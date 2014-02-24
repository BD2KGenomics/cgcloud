from cghub.cloud.devenv.commands import *
from cghub.cloud.devenv.generic_jenkins_slaves import *
from cghub.cloud.devenv.genetorrent_jenkins_slaves import *
from cghub.cloud.devenv.jenkins_master import *
from cghub.cloud.devenv.rpmbuild_jenkins_slaves import *

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