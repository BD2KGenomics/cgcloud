from fabric.operations import sudo
from cghub.cloud.devenv.build_server import BuildServer
from cghub.cloud.generic_boxes import GenericCentos6Box


class CentosGenetorrentBuildServer( GenericCentos6Box, BuildServer ):
    """
    A box representing EC2 instances that GeneTorrent is built on
    """

    @staticmethod
    def role():
        return "centos-genetorrent-build-server"

    def setup(self, update=False):
        super( CentosGenetorrentBuildServer, self ).setup( update )
        self._execute( self.setup_genetorrent_build_requirements )

    def setup_genetorrent_build_requirements(self):
        self.setup_build_user( )
        # yum's error handling is a bit odd: If you pass two packages to install and one fails while
        # the other succeeds, yum exits with 0. To work around this, we need to invoke yum separately
        # for every package.
        packages = 'gcc-c++ pkgconfig xerces-c-devel libcurl-devel xqilla-devel openssl-devel ' \
                   'make rpm-build redhat-rpm-config'.split( )
        for package in packages:
            sudo( 'yum install -d 1 -y %s' % package )

    def recommended_instance_type(self):
        """
        A micro instance does not have enough RAM to build Boost, so we need to go one up.
        """
        return "m1.small"

