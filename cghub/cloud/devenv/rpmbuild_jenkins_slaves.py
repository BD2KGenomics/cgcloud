from cghub.cloud.box import fabric_task
from cghub.cloud.centos_box import CentosBox
from cghub.cloud.devenv.jenkins_slave import JenkinsSlave
from cghub.cloud.generic_boxes import GenericCentos5Box
from cghub.fabric.operations import sudo


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

    @fabric_task
    def _setup_build_user(self):
        super( CentosRpmbuildJenkinsSlave, self )._setup_build_user( )
        # Some RPM builds depend on the product of other RPM builds to be installed so we need to
        # be able to run rpm in between RPM builds
        sudo( "echo 'jenkins ALL=(ALL) NOPASSWD: /bin/rpm' >> /etc/sudoers" )


class Centos5RpmbuildJenkinsSlave(CentosRpmbuildJenkinsSlave, GenericCentos5Box):
    pass