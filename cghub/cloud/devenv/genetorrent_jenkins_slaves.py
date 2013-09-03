from fabric.operations import sudo
from cghub.cloud.box import fabric_task
from cghub.cloud.centos_box import CentosBox
from cghub.cloud.devenv.jenkins_slave import JenkinsSlave
from cghub.cloud.fedora_box import FedoraBox
from cghub.cloud.generic_boxes import GenericCentos5Box, GenericCentos6Box, GenericUbuntuLucidBox, GenericUbuntuPreciseBox, GenericUbuntuRaringBox, GenericUbuntuOneiricBox, GenericFedora19Box, GenericFedora18Box, GenericFedora17Box
from cghub.cloud.ubuntu_box import UbuntuBox


class GenetorrentJenkinsSlave( JenkinsSlave ):
    """
    A Jenkins slave for building GeneTorrent
    """

    def recommended_instance_type(self):
        """
        A micro instance does not have enough RAM to build Boost, so we need to go one up.
        """
        return "m1.small"


class CentosGenetorrentJenkinsSlave( CentosBox, GenetorrentJenkinsSlave ):
    """
    A Jenkins slave for building GeneTorrent on CentOS
    """

    def _list_packages_to_install(self):
        # TODO: List JRE explicitly (it is already installed on RightScale CentOS images)
        return super( CentosGenetorrentJenkinsSlave, self )._list_packages_to_install( ) + [
            'gcc-c++',
            'pkgconfig',
            'xerces-c-devel',
            'libcurl-devel',
            'xqilla-devel',
            'openssl-devel',
            'make',
            'rpm-build',
            'redhat-rpm-config' ]


class Centos5GenetorrentJenkinsSlave( CentosGenetorrentJenkinsSlave, GenericCentos5Box ):
    """
    A Jenkins slave for building GeneTorrent on CentOS 5
    """
    pass


class Centos6GenetorrentJenkinsSlave( CentosGenetorrentJenkinsSlave, GenericCentos6Box ):
    """
    A Jenkins slave for building GeneTorrent on CentOS 6
    """
    pass


class UbuntuGenetorrentJenkinsSlave( UbuntuBox, GenetorrentJenkinsSlave ):
    """
    A Jenkins slave for building GeneTorrent on Ubuntu
    """

    def _list_packages_to_install(self):
        packages = super( UbuntuGenetorrentJenkinsSlave, self )._list_packages_to_install( )
        return packages + [
            'autoconf',
            'libtool',
            'g++',
            'pkg-config',
            'libxerces-c-dev',
            'libcurl4-openssl-dev',
            'libxqilla-dev',
            'libssl-dev',
            'make',
            'devscripts',
            'debhelper',
            'python-support',
            'openjdk-7-jre-headless' ]


class UbuntuLucidGenetorrentJenkinsSlave( UbuntuGenetorrentJenkinsSlave, GenericUbuntuLucidBox ):
    """
    A Jenkins slave for building GeneTorrent on Ubuntu 10.04 LTS (EOL April 2015)
    """

    def _populate_package_substitutions(self, map):
        map.update( {
            'git': 'git-core',
            'openjdk-7-jre-headless': 'openjdk-6-jre'
        } )
        super( UbuntuLucidGenetorrentJenkinsSlave, self )._populate_package_substitutions( map )


    def __substitute_package(self, package):
        # Lucid doesn't have git, but git-core which was obsoleted in favor of git on newer
        # releases
        package = super( UbuntuLucidGenetorrentJenkinsSlave, self ).__substitute_package( package )
        return self.substitutions.get( package, package )

    def _pre_install_packages(self):
        super( UbuntuLucidGenetorrentJenkinsSlave, self )._pre_install_packages( )
        # On Lucid, somehow postfix gets pulled in as a dependency kicking the frontend into
        # interactive mode.
        self._debconf_set_selection(
            "postfix postfix/main_mailer_type string 'No configuration'",
            "postfix postfix/mailname string %s" % self.host_name
        )


class UbuntuOneiricGenetorrentJenkinsSlave( UbuntuGenetorrentJenkinsSlave,
                                            GenericUbuntuOneiricBox ):
    """
    A Jenkins slave for building GeneTorrent on Ubuntu 11.10 (EOL May 2013)
    """
    pass


class UbuntuPreciseGenetorrentJenkinsSlave( UbuntuGenetorrentJenkinsSlave,
                                            GenericUbuntuPreciseBox ):
    """
    A Jenkins slave for building GeneTorrent on Ubuntu 12.04 LTS (EOL April 2017)
    """
    pass


class UbuntuRaringGenetorrentJenkinsSlave( UbuntuGenetorrentJenkinsSlave, GenericUbuntuRaringBox ):
    """
    A Jenkins slave for building GeneTorrent on Ubuntu 13.04 (EOL January 2014)
    """
    pass


class FedoraGenetorrentJenkinsSlave( FedoraBox, GenetorrentJenkinsSlave ):
    """
    A Jenkins slave for building GeneTorrent on Fedora
    """

    def _list_packages_to_install(self):
        packages = super( FedoraGenetorrentJenkinsSlave, self )._list_packages_to_install( )
        return packages + [
            'autoconf',
            'libtool',
            'gcc-c++',
            'pkgconfig',
            'xerces-c-devel',
            'libcurl-devel',
            'xqilla-devel',
            'openssl-devel',
            'boost-devel',
            'make',
            'rpm-build',
            'redhat-rpm-config',
            'java' ]


    @fabric_task
    def _get_rc_local_path(self):
        rc_local_path = '/etc/rc.local'
        sudo( 'test -f {f} || touch {f} && chmod +x {f}'.format( f=rc_local_path ) )
        return rc_local_path


class Fedora19GenetorrentJenkinsSlave( FedoraGenetorrentJenkinsSlave, GenericFedora19Box ):
    """
    A Jenkins slave for building GeneTorrent on Fedora 19
    """
    pass


class Fedora18GenetorrentJenkinsSlave( FedoraGenetorrentJenkinsSlave, GenericFedora18Box ):
    """
    A Jenkins slave for building GeneTorrent on Fedora 18
    """
    pass


class Fedora17GenetorrentJenkinsSlave( FedoraGenetorrentJenkinsSlave, GenericFedora17Box ):
    """
    A Jenkins slave for building GeneTorrent on Fedora 17
    """
    pass