from cghub.cloud.devenv.commands import *
from cghub.cloud.devenv.genetorrent_jenkins_slaves import *
from cghub.cloud.devenv.jenkins_master import *
from cghub.cloud.devenv.rpmbuild_jenkins_slaves import *

BOXES = [
    JenkinsMaster,
    UbuntuLucidGenetorrentJenkinsSlave,
    UbuntuOneiricGenetorrentJenkinsSlave,
    UbuntuPreciseGenetorrentJenkinsSlave,
    UbuntuRaringGenetorrentJenkinsSlave,
    Centos5GenetorrentJenkinsSlave,
    Centos6GenetorrentJenkinsSlave,
    Fedora19GenetorrentJenkinsSlave,
    Fedora20GenetorrentJenkinsSlave,
    Centos5RpmbuildJenkinsSlave,
    Centos6RpmbuildJenkinsSlave ]

COMMANDS = [
    RegisterSlaves ]