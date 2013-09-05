from cghub.cloud.centos_box import CentosBox
from cghub.cloud.devenv.jenkins_slave import JenkinsSlave
from cghub.cloud.generic_boxes import GenericCentos5Box


class CentosRpmbuildJenkinsSlave( CentosBox, JenkinsSlave ):
    """
    A Jenkins slave for building GeneTorrent on CentOS
    """

    def _list_packages_to_install(self):
        return super( CentosRpmbuildJenkinsSlave, self )._list_packages_to_install( ) + [
            'rpmdevtools',
            'tk-devel',
            'tcl-devel',
            'expat-devel',
            'db4-devel',
            'gdbm-devel',
            'sqlite-devel',
            'bzip2-devel',
            'openssl-devel',
            'ncurses-devel',
            'readline-devel' ]


class Centos5RpmbuildJenkinsSlave(CentosRpmbuildJenkinsSlave, GenericCentos5Box):
    pass