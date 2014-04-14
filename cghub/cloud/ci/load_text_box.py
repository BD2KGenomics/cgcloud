from cghub.cloud.core import GenericUbuntuSaucyBox, fabric_task
from fabric.operations import run, sudo


class LoadTestBox( GenericUbuntuSaucyBox ):
    """

    """
    def _post_install_packages( self ):
        super( LoadTestBox, self )._post_install_packages( )
        self.__install_genetorrent( )

    def recommended_instance_type( self ):
        return "m3.2xlarge"

    @fabric_task
    def __install_genetorrent( self ):
        run( 'curl -O http://public-artifacts.cghub.ucsc.edu.s3.amazonaws.com/genetorrent/'
             'platform=saucy,provisioning=genetorrent/'
             'build-91/genetorrent-common_3.8.5-ubuntu2.91-13.10_amd64.deb' )
        run( 'curl -O http://public-artifacts.cghub.ucsc.edu.s3.amazonaws.com/genetorrent/'
             'platform=saucy,provisioning=genetorrent/'
             'build-91/genetorrent-download_3.8.5-ubuntu2.91-13.10_amd64.deb' )
        sudo( 'dpkg -i '
              'genetorrent-common_3.8.5-ubuntu2.91-13.10_amd64.deb '
              'genetorrent-download_3.8.5-ubuntu2.91-13.10_amd64.deb', warn_only=True )
        sudo( 'apt-get -q -y install --fix-broken' )
