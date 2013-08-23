from cghub.fabric.operations import sudo
from cghub.cloud.box import fabric_task
from cghub.cloud.devenv.jenkins_master import Jenkins, JenkinsMaster
from cghub.cloud.devenv.source_control_client import SourceControlClient

BUILD_USER = Jenkins.user


class JenkinsSlave( SourceControlClient ):
    """
    A box that represents EC2 instances which can serve as a Jenkins build agent. This class is
    typically used as a mix-in.
    """

    def _post_install_packages(self):
        super( JenkinsSlave, self )._post_install_packages( )
        self.__setup_build_user( )

    @fabric_task
    def __setup_build_user(self):
        """
        Setup a user account that accepts SSH connections from Jenkins such that it can act as a
        Jenkins slave. All build-related files should go into that user's ~/builds directory.
        """
        kwargs = dict(
            user=BUILD_USER,
            key=self._read_config_file( Jenkins.pubkey_config_file,
                                        role=JenkinsMaster.role( ) ).strip( ) )

        # Create the build user
        #
        sudo( 'useradd -m {0}'.format( BUILD_USER ) )
        self._propagate_authorized_keys( BUILD_USER )

        # Ensure that jenkins@build-master can log into this box as the build user
        #
        sudo( "echo '{key}' >> ~/.ssh/authorized_keys".format( **kwargs ),
              user=BUILD_USER,
              sudo_args='-i' )

        self.setup_repo_host_keys( user=BUILD_USER )

        # Setup working directory for all builds in either the build user's home or as a symlink to
        # the ephemeral volume if available. Remember, the ephemeral volume comes back empty every
        # time the box starts.
        #
        if sudo( 'test -d /mnt/ephemeral && mountpoint -q /mnt/ephemeral', quiet=True ).succeeded:
            chown_cmd = "chown -R {user}:{user} /mnt/ephemeral".format( **kwargs )
            # chown ephemeral storage now ...
            sudo( chown_cmd )
            # ... and every time instance boots
            rc_local_path = sudo( 'readlink -f /etc/rc.local' ) # might be a symlink but
            # prepend_remote_shell_script
            # doesn't work with symlinks
            self._prepend_remote_shell_script( script=chown_cmd,
                                               remote_path=rc_local_path,
                                               use_sudo=True,
                                               mirror_local_mode=True )
            sudo( 'chmod +x %s' % rc_local_path )
            # link ephemeral to ~/builds
            sudo( 'ln -snf /mnt/ephemeral ~/builds', user=BUILD_USER, sudo_args='-i' )
        else:
            # No ephemeral storage, just create the ~/builds directory
            sudo( 'mkdir ~/builds', user=BUILD_USER, sudo_args='-i' )
