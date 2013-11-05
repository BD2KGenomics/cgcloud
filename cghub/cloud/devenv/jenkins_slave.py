from lxml.builder import E

from cghub.cloud.lib.util import snake_to_camel, UserError

from cghub.fabric.operations import sudo
from cghub.cloud.core.box import fabric_task
from cghub.cloud.devenv.jenkins_master import Jenkins, JenkinsMaster
from cghub.cloud.core.source_control_client import SourceControlClient


BUILD_USER = Jenkins.user
BUILD_DIR = '/home/jenkins/builds'


class JenkinsSlave( SourceControlClient ):
    """
    A box that represents EC2 instances which can serve as a Jenkins build agent. This class is
    typically used as a mix-in.
    """

    def _post_install_packages(self):
        super( JenkinsSlave, self )._post_install_packages( )
        self._setup_build_user( )

    @fabric_task
    def _get_rc_local_path(self):
        """
        Return the canonical path to /etc/rc.local or an equivalent shell script that gets
        executed during boot up. The last component in the path must not be be a symlink,
        other components may be.
        """
        # might be a symlink but prepend_remote_shell_script doesn't work with symlinks
        return sudo( 'readlink -f /etc/rc.local' )

    def __get_master_pubkey(self):
        ec2_keypair_name = JenkinsMaster.ec2_keypair_name( self.ctx )
        ec2_keypair = self.connection.get_key_pair( ec2_keypair_name )
        if ec2_keypair is None:
            raise UserError( "Missing EC2 keypair named '%s'. You must create the master before "
                             "creating slaves." % ec2_keypair_name )
        return self.ctx.download_ssh_pubkey( ec2_keypair )

    @fabric_task
    def _setup_build_user(self):
        """
        Setup a user account that accepts SSH connections from Jenkins such that it can act as a
        Jenkins slave.
        """
        kwargs = dict(
            user=BUILD_USER,
            dir=BUILD_DIR,
            ephemeral=self._ephemeral_mount_point( ),
            pubkey=self.__get_master_pubkey( ).strip( ) )

        # Create the build user
        #
        sudo( 'useradd -m -s /bin/bash {0}'.format( BUILD_USER ) )
        self._propagate_authorized_keys( BUILD_USER )

        # Ensure that jenkins@build-master can log into this box as the build user
        #
        sudo( "echo '{pubkey}' >> ~/.ssh/authorized_keys".format( **kwargs ),
              user=BUILD_USER,
              sudo_args='-i' )

        self.setup_repo_host_keys( user=BUILD_USER )

        # Setup working directory for all builds in either the build user's home or as a symlink to
        # the ephemeral volume if available. Remember, the ephemeral volume comes back empty every
        # time the box starts.
        #
        if sudo( 'test -d {ephemeral} && mountpoint -q {ephemeral}'.format( **kwargs ),
                 quiet=True ).succeeded:
            chown_cmd = "chown -R {user}:{user} {ephemeral}".format( **kwargs )
            # chown ephemeral storage now ...
            sudo( chown_cmd )
            # ... and every time instance boots
            rc_local_path = self._get_rc_local_path( )
            self._prepend_remote_shell_script( script=chown_cmd,
                                               remote_path=rc_local_path,
                                               use_sudo=True,
                                               mirror_local_mode=True )
            sudo( 'chmod +x %s' % rc_local_path )
            # link build directory as symlink to ephemeral volume
            sudo( 'ln -snf {ephemeral} {dir}'.format( **kwargs ),
                  user=BUILD_USER,
                  sudo_args='-i' )
        else:
            # No ephemeral storage, just create the build directory
            sudo( 'mkdir {dir}'.format( **kwargs ), user=BUILD_USER, sudo_args='-i' )

    def __jenkins_labels(self):
        labels = self.role( ).split( '-' )
        return [ l for l in labels if l not in [ 'jenkins', 'slave' ] ]

    def slave_config_template(self, image):
        """
        Returns the slave template, i.e. a fragment of Jenkins configuration that,
        if added to the master's main config file, controls how EC2 instances of this slave box
        are created and managed by the master.

        :param image: the image to boot slave instances from
        :type image: boto.ec2.image.Image

        :return: an XML element containing the slave template
        :rtype: lxml.etree._Element
        """
        creation_kwargs = { }
        self._populate_instance_creation_args( image, creation_kwargs )
        return E( 'hudson.plugins.ec2.SlaveTemplate',
                  E.ami( image.id ),
                  # By convention we use the description element as the primary identifier. We
                  # don't need to use the absolute role name since we are not going to mix slaves
                  # from different namespaces:
                  E.description( self.role( ) ),
                  E.zone( self.ctx.availability_zone ),
                  # Using E.foo('') instead of just E.foo() yields <foo></foo> instead of <foo/>,
                  # consistent with how Jenkins serializes its config:
                  E.securityGroups( '' ),
                  E.remoteFS( BUILD_DIR ),
                  E.sshPort( '22' ),
                  E.type( snake_to_camel( self.recommended_instance_type( ),
                                          separator='.' ) ),
                  E.labels( ' '.join( self.__jenkins_labels( ) ) ),
                  E.mode( 'EXCLUSIVE' ),
                  E.initScript( 'while ! touch %s/.writable; do sleep 1; done' % BUILD_DIR ),
                  E.userData( creation_kwargs.get( 'user_data', '' ) ),
                  E.numExecutors( '1' ),
                  E.remoteAdmin( BUILD_USER ),
                  E.rootCommandPrefix( '' ),
                  E.jvmopts( '' ),
                  E.subnetId( '' ),
                  E.idleTerminationMinutes( '30' ),
                  E.instanceCap( '1' ),
                  E.stopOnTerminate( 'false' ),
                  E.tags(
                      E( 'hudson.plugins.ec2.EC2Tag',
                         E.name( 'Name' ),
                         E.value( self.absolute_role( ) )
                      ) ),
                  E.usePrivateDnsName( 'false' ) )
