import base64
import textwrap
from cghub.util import snake_to_camel
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

    @fabric_task
    def _setup_build_user(self):
        """
        Setup a user account that accepts SSH connections from Jenkins such that it can act as a
        Jenkins slave. All build-related files should go into that user's ~/builds directory.
        """
        kwargs = dict(
            user=BUILD_USER,
            ephemeral=self._ephemeral_mount_point( ),
            key=self._read_config_file( Jenkins.pubkey_config_file,
                                        role=JenkinsMaster.role( ) ).strip( ) )

        # Create the build user
        #
        sudo( 'useradd -m -s /bin/bash {0}'.format( BUILD_USER ) )
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
            # link ephemeral to ~/builds
            sudo( 'ln -snf {ephemeral} ~/builds'.format( **kwargs ), user=BUILD_USER,
                  sudo_args='-i' )
        else:
            # No ephemeral storage, just create the ~/builds directory
            sudo( 'mkdir ~/builds', user=BUILD_USER, sudo_args='-i' )

    def __jenkins_labels(self):
        labels = self.role( ).split( '-' )
        return [ l for l in labels if l not in [ 'jenkins', 'slave' ] ]

    def __build_jenkins_slave_template(self, image_id=None):
        instance = self.get_instance( )
        if image_id is None:
            image_id = instance.image_id
        user_data = instance.get_attribute( 'userData' )[ 'userData' ] # odd
        user_data = '' if user_data is None else base64.b64decode( user_data )
        kwargs = dict( image_id=image_id,
                       role=self.role( ),
                       zone=self.env.availability_zone,
                       builds='/home/jenkins/builds',
                       instance_type=snake_to_camel( self.recommended_instance_type( ),
                                                     separator='.' ),
                       labels=" ".join( self.__jenkins_labels( ) ),
                       instance_name=self.absolute_role( ),
                       user_data=user_data )
        return textwrap.dedent( """
            <hudson.plugins.ec2.SlaveTemplate>
              <ami>{image_id}</ami>
              <description>{role}</description>
              <zone>{zone}</zone>
              <securityGroups></securityGroups>
              <remoteFS>{builds}</remoteFS>
              <sshPort>22</sshPort>
              <type>{instance_type}</type>
              <labels>{labels}</labels>
              <mode>EXCLUSIVE</mode>
              <initScript>while ! touch {builds}/.writable; do sleep 1; done</initScript>
              <userData><![CDATA[{user_data}]]></userData>
              <numExecutors>1</numExecutors>
              <remoteAdmin>jenkins</remoteAdmin>
              <rootCommandPrefix></rootCommandPrefix>
              <jvmopts></jvmopts>
              <subnetId></subnetId>
              <idleTerminationMinutes>30</idleTerminationMinutes>
              <instanceCap>1</instanceCap>
              <stopOnTerminate>false</stopOnTerminate>
              <tags>
                <hudson.plugins.ec2.EC2Tag>
                  <name>Name</name>
                  <value>{instance_name}</value>
                </hudson.plugins.ec2.EC2Tag>
              </tags>
              <usePrivateDnsName>false</usePrivateDnsName>
            </hudson.plugins.ec2.SlaveTemplate>
        """ ).format( **kwargs )

    def image(self):
        image_id = super( JenkinsSlave, self ).image( )
        self._log( 'In order to configure the Jenkins master to use this image for spawning '
                   'slaves, paste the following XML fragment into %s/config.xml on the '
                   'jenkins-master box. The fragment should be pasted as a child element of '
                   '//hudson.plugins.ec2.EC2Cloud/templates, overwriting an existing child of '
                   'the same description if such a child exists.' % Jenkins.home )
        self._log( self.__build_jenkins_slave_template( image_id ) )
        return image_id
