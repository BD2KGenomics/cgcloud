from fabric.operations import sudo, run
from cghub.cloud.box import Box
from cghub.cloud.devenv.build_master import Jenkins, BuildMaster

BUILD_USER = Jenkins.user


class BuildServer( Box ):
    """
    A box that represents EC2 instances which can serve as a Jenkins build agent. This class is
    typically used as a mix-in.
    """

    def setup_build_user(self):
        """
        Setup a user account that accepts SSH connections from Jenkins such that it can act as a
        Jenkins slave. All build-related files should go into that user's ~/builds directory.
        """
        # Create the build user
        #
        sudo( 'useradd -m {0}'.format( BUILD_USER ) )
        self._propagate_authorized_keys( BUILD_USER )

        # Ensure that jenkins@build-master can log into this box as the build user
        #
        jenkins_key = self._read_config_file( Jenkins.pubkey_config_file, role=BuildMaster.role( ) )
        sudo( "echo '{key}' >> ~{user}/.ssh/authorized_keys".format( key=jenkins_key,
                                                                     user=BUILD_USER ) )

        # Setup working directory for all builds in either the build user's home or as a symlink to
        # the ephemeral volume if available. Remember, the ephemeral volume comes back empty every
        # time the box starts.
        #
        if sudo( 'test -d /mnt/ephemeral && mountpoint -q /mnt/ephemeral', quiet=True ).succeeded:
            sudo( "chown -R {0}:{0} /mnt/ephemeral".format( BUILD_USER ) )
            sudo( "ln -snf /mnt/ephemeral ~{0}/builds".format( BUILD_USER ), user=BUILD_USER )
        else:
            sudo( "mkdir ~{0}/builds".format( BUILD_USER ), user=BUILD_USER )

