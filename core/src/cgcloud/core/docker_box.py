import logging

from fabric.operations import run

from bd2k.util.strings import interpolate as fmt

from cgcloud.core.box import fabric_task
from cgcloud.core.ubuntu_box import UbuntuBox
from cgcloud.fabric.operations import sudo
from cgcloud.lib.util import heredoc

log = logging.getLogger( __name__ )


class DockerBox( UbuntuBox ):
    """
    A mixin for Docker. Based on the official shell script from

    https://docs.docker.com/installation/ubuntulinux/#installation
    """

    @fabric_task
    def _setup_package_repos( self ):
        assert run( 'test -e /usr/lib/apt/methods/https', warn_only=True ).succeeded, \
            "Need HTTPS support in apt-get in order to install from the Docker repository"
        super( DockerBox, self )._setup_package_repos( )
        sudo( ' '.join( [ 'apt-key', 'adv',
                            '--keyserver', 'hkp://p80.pool.sks-keyservers.net:80',
                            '--recv-keys', '58118E89F3A912897C070ADBF76221572C52609D' ] ) )
        codename = self.release().codename
        sudo( fmt( 'echo deb https://apt.dockerproject.org/repo ubuntu-{codename} main '
                   '> /etc/apt/sources.list.d/docker.list' ) )

    @fabric_task
    def _list_packages_to_install( self ):
        kernel = run( 'uname -r' )
        kernel_version = tuple( map( int, kernel.split( '.' )[ :2 ] ) )
        assert kernel_version >= (3, 10), \
            "Need at least kernel version 3.10, found '%s'." % kernel
        kernel = run( 'uname -r' )
        assert kernel.endswith( '-generic' ), \
            'Current kernel is not supported by the linux-image-extra-virtual package.'
        packages = super( DockerBox, self )._list_packages_to_install( )
        packages += [ 'docker-engine', 'linux-image-extra-' + kernel, 'linux-image-extra-virtual' ]
        if run( 'cat /sys/module/apparmor/parameters/enabled' ).lower( ).startswith( 'y' ):
            packages += [ 'apparmor' ]
        return packages

    def _post_install_packages( self ):
        super( DockerBox, self )._post_install_packages( )
        self.__setup_docker( )

    def _docker_users( self ):
        return [ self.admin_account( ) ]

    def docker_data_prefix( self ):
        return self._ephemeral_mount_point( 0 )

    @fabric_task
    def __setup_docker( self ):
        for docker_user in set( self._docker_users( ) ):
            sudo( "usermod -aG docker " + docker_user )
        prefix = self.docker_data_prefix( )
        if prefix is not None:
            self._run_init_script( 'docker', 'stop' )
            # Backup initial state of data directory so we can initialize an empty ephemeral volume
            sudo( 'tar -czC /var/lib docker > /var/lib/docker.tar.gz' )
            # Then delete it and recreate it as an empty directory to serve as the bind mount point
            sudo( 'rm -rf /var/lib/docker && mkdir /var/lib/docker' )
            self._register_init_script(
                "dockerbox",
                heredoc( """
                    description "Placement of /var/lib/docker"
                    console log
                    start on starting docker
                    stop on stopped docker
                    pre-start script
                        # Make script idempotent
                        if ! mountpoint -q {prefix}/var/lib/docker; then
                            # Prefix must refer to a separate volume, e.g. ephemeral or EBS
                            if mountpoint -q {prefix}; then
                                mkdir -p {prefix}/var/lib
                                # If /var/lib/docker has files ...
                                if python -c 'import os, sys; sys.exit( 0 if os.listdir( sys.argv[1] ) else 1 )' /var/lib/docker; then
                                    # ... move it to prefix ...
                                    mv /var/lib/docker {prefix}/var/lib
                                    # ... and recreate it as an empty mount point, ...
                                    mkdir -p /var/lib/docker
                                else
                                    # ... otherwise untar the initial backup.
                                    tar -xzC {prefix}/var/lib < /var/lib/docker.tar.gz
                                fi
                                # Now bind mount it into /var/lib/docker
                                mount --bind {prefix}/var/lib/docker /var/lib/docker
                            fi
                        fi
                    end script""" ) )
            self._run_init_script( 'docker', 'start' )
