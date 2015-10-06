from fabric.operations import run

from cgcloud.core.box import fabric_task
from cgcloud.core.ubuntu_box import UbuntuBox
from cgcloud.fabric.operations import sudo


class DockerBox( UbuntuBox ):
    """
    A box with Docker installed. Uses the curl'ed shell script method as currently recommended at

    https://docs.docker.com/installation/ubuntulinux/#installation
    """

    # FIXME: The curl'ed shell script runs apt-get update twice. We could eliminate both
    # invocations if we added Docker's apt repo in _setup_package_repos. Ultimately, we should
    # reverse engineer the script and port it to the cgcloud way.

    def _post_install_packages( self ):
        super( DockerBox, self )._post_install_packages( )
        self.__setup_docker( )

    def _docker_users( self ):
        return [ self.admin_account( ) ]

    @fabric_task
    def __setup_docker( self ):
        kernel = run( 'uname -r' )
        if tuple( map( int, kernel.split( '.' )[ :2 ] ) ) < (3, 10):
            raise AssertionError( "Need at least kernel version 3.10, found '%s'." % kernel )
        run( 'curl -sSL https://get.docker.com/ | sh' )
        for docker_user in set( self._docker_users( ) ):
            sudo( "usermod -aG docker " + docker_user )
