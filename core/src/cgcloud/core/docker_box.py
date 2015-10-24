from fabric.operations import run, os

from cgcloud.core.box import fabric_task
from cgcloud.core.ubuntu_box import UbuntuBox
from cgcloud.fabric.operations import sudo
from cgcloud.lib.util import heredoc


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

    def docker_data_prefix( self ):
        return self._ephemeral_mount_point( 0 )

    @fabric_task
    def __setup_docker( self ):
        kernel = run( 'uname -r' )
        if tuple( map( int, kernel.split( '.' )[ :2 ] ) ) < (3, 10):
            raise AssertionError( "Need at least kernel version 3.10, found '%s'." % kernel )
        run( 'curl -sSL https://get.docker.com/ | sh' )
        for docker_user in set( self._docker_users( ) ):
            sudo( "usermod -aG docker " + docker_user )
        prefix = self.docker_data_prefix( )
        if prefix is not None:
            self._run_init_script( 'docker', 'stop' )
            sudo( 'tar -czC /var/lib docker > /var/lib/docker.tar.gz' )
            sudo( 'rm -rf /var/lib/docker && mkdir /var/lib/docker' )
            self._register_init_script(
                "dockerbox",
                heredoc( """
                    description "Placement of /var/lib/docker"
                    console log
                    start on starting docker
                    stop on stopped docker
                    pre-start script
                        if ! mountpoint -q {prefix}/var/lib/docker; then
                            # Make script idempotent
                            if mountpoint -q {prefix}; then
                                # Prefix must be a mount-point
                                mkdir -p {prefix}/var/lib
                                # If /var/lib/docker has files ...
                                if python -c 'import os, sys; sys.exit( 0 if os.listdir( sys.argv[1] ) else 1 )' /var/lib/docker; then
                                    # ... move it to prefix ...
                                    mv /var/lib/docker {prefix}/var/lib
                                    # ... and recreate it as an empty mount point, ...
                                    mkdir -p /var/lib/docker
                                else
                                    # ... otherwise untar the initial backup into prefix.
                                    tar -xzC {prefix}/var/lib < /var/lib/docker.tar.gz
                                fi
                                mount --bind {prefix}/var/lib/docker /var/lib/docker
                            fi
                        fi
                    end script
                    """ ) )
            self._run_init_script( 'docker', 'start' )
