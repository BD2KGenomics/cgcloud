from cghub.cloud.centos_box import CentosBox
from cghub.cloud.devenv.jenkins_slave import JenkinsSlave
from cghub.cloud.generic_boxes import GenericCentos5Box, GenericCentos6Box, GenericLucidBox, GenericPreciseBox, GenericRaringBox, GenericOneiricBox
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
            'g++',
            'pkg-config',
            'libxerces-c-dev',
            'libcurl4-openssl-dev',
            'libxqilla-dev',
            'libssl-dev',
            'make',
            'devscripts',
            'debhelper',
            'python-support' ]


class Ubuntu10GenetorrentJenkinsSlave( UbuntuGenetorrentJenkinsSlave, GenericLucidBox ):
    """
    A Jenkins slave for building GeneTorrent on Ubuntu 10.04
    """
    pass


class Ubuntu11GenetorrentJenkinsSlave( UbuntuGenetorrentJenkinsSlave, GenericOneiricBox ):
    """
    A Jenkins slave for building GeneTorrent on Ubuntu 11.10

    I'd rather use Natty as it is the LTS release but historically our Ubuntu 11 package had been
    for 11.10, aka Oneiric.
    """
    pass


class Ubuntu12GenetorrentJenkinsSlave( UbuntuGenetorrentJenkinsSlave, GenericPreciseBox ):
    """
    A Jenkins slave for building GeneTorrent on Ubuntu 12.04
    """
    pass


class Ubuntu13GenetorrentJenkinsSlave( UbuntuGenetorrentJenkinsSlave, GenericRaringBox ):
    """
    A Jenkins slave for building GeneTorrent on Ubuntu 13.04
    """
    pass
