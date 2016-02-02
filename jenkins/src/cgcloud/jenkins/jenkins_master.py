from StringIO import StringIO
from contextlib import contextmanager
import logging
from textwrap import dedent
from xml.etree import ElementTree

from fabric.context_managers import hide

from fabric.operations import run, sudo, put, get

from cgcloud.lib.ec2 import EC2VolumeHelper
from cgcloud.lib.util import UserError, abreviated_snake_case_class_name
from cgcloud.core.box import fabric_task
from cgcloud.core.generic_boxes import GenericUbuntuTrustyBox
from cgcloud.core.source_control_client import SourceControlClient

log = logging.getLogger( __name__ )


# FIXME: __create_jenkins_keypair and __inject_aws_credentials fail when the Jenkins volume is fresh
# since certain files like config.xml don't exist (because Jenkins hasn't written them out yet or
# because the plugin isn't installed yet. The workaround is to install all stop the instance (

# FIXME: __create_jenkins_keypair still uses the old configuration section to inject the private
# key into Jenkins. Since then Jenkins switched to a new credentials system rendering the old
# method ineffective. We should switch to the new system or remove the code. After all it is easy
# enought to configure the credentials by hand.

class Jenkins:
    user = 'jenkins'
    """
    The name of the user account that Jenkins runs as. Note that we are not free to chose this as
    it is determined by the jenkins package for Ubuntu
    """

    group = 'nogroup'
    """
    The name of the group that Jenkins runs as.
    """

    data_device_ext = '/dev/sdf'
    """
    EC2's name of the block device to which to attach the Jenkins data volume
    """

    data_device_int = '/dev/xvdf'
    """
    The kernel's name of the block device to which to attach the Jenkins data volume
    """

    data_volume_name = 'jenkins-data'
    """
    The value of the Name tag of the Jenkins data volume
    """

    data_volume_fs_label = data_volume_name
    """
    The label of the file system on the Jenkins data volume
    """

    data_volume_size_gb = 100
    """
    The size of the Jenkins data volume
    """

    home = '/var/lib/jenkins'
    """
    The jenkins user's home directory on the build master
    """


jenkins = vars( Jenkins )


class JenkinsMaster( GenericUbuntuTrustyBox, SourceControlClient ):
    """
    An instance of this class represents the build master in EC2
    """

    def __init__( self, ctx ):
        super( JenkinsMaster, self ).__init__( ctx )
        self.volume = None

    @classmethod
    def recommended_instance_type( cls ):
        return "m3.large"

    def other_accounts( self ):
        return super( JenkinsMaster, self ).other_accounts( ) + [ Jenkins.user ]

    def default_account( self ):
        return Jenkins.user

    def prepare( self, *args, **kwargs ):
        self.volume = EC2VolumeHelper( ec2=self.ctx.ec2,
                                       name=self.ctx.to_aws_name( Jenkins.data_volume_name ),
                                       size=Jenkins.data_volume_size_gb,
                                       availability_zone=self.ctx.availability_zone )
        return super( JenkinsMaster, self ).prepare( *args, **kwargs )

    def _on_instance_running( self, first_boot ):
        if first_boot:
            self.volume.attach( self.instance_id, device=Jenkins.data_device_ext )
        super( JenkinsMaster, self )._on_instance_running( first_boot )

    @fabric_task
    def _setup_package_repos( self ):
        #
        # Jenkins
        #
        super( JenkinsMaster, self )._setup_package_repos( )
        run( "wget -q -O - 'http://pkg.jenkins-ci.org/debian/jenkins-ci.org.key' "
             "| sudo apt-key add -" )
        sudo( "echo deb http://pkg.jenkins-ci.org/debian binary/ "
              "> /etc/apt/sources.list.d/jenkins.list" )
        #
        # Enable multiverse sources
        #
        sudo( 'apt-add-repository multiverse' )

    def _list_packages_to_install( self ):
        packages = super( JenkinsMaster, self )._list_packages_to_install( )
        return packages + [
            'ec2-api-tools' ]

    @fabric_task
    def _install_packages( self, packages ):
        super( JenkinsMaster, self )._install_packages( packages )
        # work around https://issues.jenkins-ci.org/browse/JENKINS-20407
        sudo( 'mkdir /var/run/jenkins' )
        # Use confold so it doesn't get hung up on our pre-staged /etc/default/jenkins
        sudo( 'apt-get -q -y -o Dpkg::Options::=--force-confold install jenkins' )

    @fabric_task
    def _pre_install_packages( self ):
        #
        # Pre-stage the defaults file for Jenkins. It differs from the maintainer's version in the
        # following ways: (please document all changes in this comment)
        #
        # 1) cruft was removed
        # 2) --httpListenAddress=127.0.0.1 was added to make Jenkins listen locally only
        #
        instance_type = self.instance.instance_type
        etc_default_jenkins = StringIO( dedent( '''\
            NAME=jenkins
            JAVA=/usr/bin/java
            JAVA_ARGS="-Xmx{jvm_heap_size}"
            #JAVA_ARGS="-Djava.net.preferIPv4Stack=true" # make jenkins listen on IPv4 address
            PIDFILE=/var/run/jenkins/jenkins.pid
            JENKINS_USER={user}
            JENKINS_WAR=/usr/share/jenkins/jenkins.war
            JENKINS_HOME="{home}"
            RUN_STANDALONE=true

            # log location.  this may be a syslog facility.priority
            JENKINS_LOG=/var/log/jenkins/$NAME.log
            #JENKINS_LOG=daemon.info

            # See http://github.com/jenkinsci/jenkins/commit/2fb288474e980d0e7ff9c4a3b768874835a3e92e
            MAXOPENFILES=8192

            HTTP_PORT=8080
            AJP_PORT=-1
            JENKINS_ARGS="\\
                --webroot=/var/cache/jenkins/war \\
                --httpPort=$HTTP_PORT \\
                --ajp13Port=$AJP_PORT \\
                --httpListenAddress=127.0.0.1 \\
            "
        '''.format( jvm_heap_size='256m' if instance_type == 't1.micro' else '1G',
                    **jenkins ) ) )
        put( etc_default_jenkins, '/etc/default/jenkins', use_sudo=True, mode=0644 )
        sudo( 'chown root:root /etc/default/jenkins' )
        #
        # Prepare data volume if necessary
        #
        sudo( 'mkdir -p %s' % Jenkins.home )
        # Only format empty volumes
        if sudo( 'file -sL %s' % Jenkins.data_device_int ) == '%s: data' % Jenkins.data_device_int:
            sudo( 'mkfs -t ext4 %s' % Jenkins.data_device_int )
            sudo( 'e2label {data_device_int} {data_volume_fs_label}'.format( **jenkins ) )
        else:
            # if the volume is not empty, verify the file system label
            label = sudo( 'e2label %s' % Jenkins.data_device_int )
            if label != Jenkins.data_volume_fs_label:
                raise AssertionError( "Unexpected volume label: '%s'" % label )

        #
        # Mount data volume permanently
        #
        sudo( "echo 'LABEL={data_volume_fs_label} {home} ext4 defaults 0 2' "
              ">> /etc/fstab".format( **jenkins ) )
        sudo( 'mount -a' )
        # in case the UID is different on the volume
        sudo( 'useradd -d {home} -g {group} -s /bin/bash {user}'.format( **jenkins ) )
        sudo( 'chown -R {user} {home}'.format( **jenkins ) )

    @classmethod
    def ec2_keypair_name( cls, ctx ):
        return Jenkins.user + '@' + ctx.to_aws_name( cls.role( ) )

    @fabric_task( user=Jenkins.user )
    def __create_jenkins_keypair( self ):
        key_path = '%s/.ssh/id_rsa' % Jenkins.home
        ec2_keypair_name = self.ec2_keypair_name( self.ctx )
        ssh_privkey, ssh_pubkey = self._provide_generated_keypair( ec2_keypair_name, key_path )
        with self.__patch_jenkins_config( ) as config:
            text_by_xpath = { './/hudson.plugins.ec2.EC2Cloud/privateKey/privateKey': ssh_privkey }
            for xpath, text in text_by_xpath.iteritems( ):
                for element in config.iterfind( xpath ):
                    if element.text != text:
                        element.text = text

    @fabric_task
    def _post_install_packages( self ):
        super( JenkinsMaster, self )._post_install_packages( )
        self._propagate_authorized_keys( Jenkins.user, Jenkins.group )
        self.setup_repo_host_keys( user=Jenkins.user )
        self.__create_jenkins_keypair( )

    def _ssh_args( self, user, command ):
        # Add port forwarding to Jenkins' web UI
        command = [ '-L', 'localhost:8080:localhost:8080' ] + command
        return super( JenkinsMaster, self )._ssh_args( user, command )

    @fabric_task( user=Jenkins.user )
    def register_slaves( self, slave_clss, clean=False, instance_type=None ):
        with self.__patch_jenkins_config( ) as config:
            templates = config.find( './/hudson.plugins.ec2.EC2Cloud/templates' )
            if templates is None:
                raise UserError(
                    "Can't find any configuration for the Jenkins Amazon EC2 plugin. Make sure it is "
                    "installed and configured on the %s in %s." % (
                        self.role( ), self.ctx.namespace) )
            template_element_name = 'hudson.plugins.ec2.SlaveTemplate'
            if clean:
                for old_template in templates.findall( template_element_name ):
                    templates.getchildren( ).remove( old_template )
            for slave_cls in slave_clss:
                slave = slave_cls( self.ctx )
                images = slave.list_images( )
                try:
                    image = images[ -1 ]
                except IndexError:
                    raise UserError( "No images for '%s'" % slave_cls.role( ) )
                new_template = slave.slave_config_template( image, instance_type )
                description = new_template.find( 'description' ).text
                found = False
                for old_template in templates.findall( template_element_name ):
                    if old_template.find( 'description' ).text == description:
                        if found:
                            raise RuntimeError( 'More than one existing slave definition for %s. '
                                                'Fix and try again' % description )
                        i = templates.getchildren( ).index( old_template )
                        templates[ i ] = new_template
                        found = True
                if not found:
                    templates.append( new_template )
                # newer versions of Jenkins add class="empty-list" attribute if there are no templates
                if templates.attrib.get( 'class' ) == 'empty-list':
                    templates.attrib.pop( 'class' )

    def _image_block_device_mapping( self ):
        # Do not include the data volume in the snapshot
        bdm = self.instance.block_device_mapping
        bdm[ Jenkins.data_device_ext ].no_device = True
        return bdm

    def _get_iam_ec2_role( self ):
        role_name, policies = super( JenkinsMaster, self )._get_iam_ec2_role( )
        role_name += '--' + abreviated_snake_case_class_name( JenkinsMaster )
        policies.update( dict(
            ec2_full=dict(
                Version="2012-10-17",
                Statement=[
                    # FIXME: Be more specific
                    dict( Effect="Allow", Resource="*", Action="ec2:*" ) ] ),
            jenkins_master_iam_pass_role=dict(
                Version="2012-10-17",
                Statement=[
                    dict( Effect="Allow", Resource=self._role_arn( ), Action="iam:PassRole" ) ] ),
            jenkins_master_s3=dict(
                Version="2012-10-17",
                Statement=[
                    dict( Effect="Allow", Resource="arn:aws:s3:::*", Action="s3:ListAllMyBuckets" ),
                    dict( Effect="Allow", Action="s3:*", Resource=[
                        "arn:aws:s3:::public-artifacts.cghub.ucsc.edu",
                        "arn:aws:s3:::public-artifacts.cghub.ucsc.edu/*" ] ) ] ) ) )
        return role_name, policies

    @contextmanager
    def __patch_jenkins_config( self ):
        """
        A context manager that retrieves the Jenkins configuration XML, deserializes it into an
        XML ElementTree, yields the XML tree, then serializes the tree and saves it back to
        Jenkins.
        """
        config_file = StringIO( )
        if run( 'test -f ~/config.xml', quiet=True ).succeeded:
            fresh_instance = False
            get( remote_path='~/config.xml', local_path=config_file )
        else:
            # Get the in-memory config as the on-disk one may be absent on a fresh instance.
            # Luckily, a fresh instance won't have any configured security.
            fresh_instance = True
            config_url = 'http://localhost:8080/computer/(master)/config.xml'
            with hide( 'output' ):
                config_file.write( run( 'curl "%s"' % config_url ) )
        config_file.seek( 0 )
        config = ElementTree.parse( config_file )

        yield config

        config_file.truncate( 0 )
        config.write( config_file, encoding='utf-8', xml_declaration=True )
        if fresh_instance:
            self.__service_jenkins( 'stop' )
        try:
            put( local_path=config_file, remote_path='~/config.xml' )
        finally:
            if fresh_instance:
                self.__service_jenkins( 'start' )
            else:
                log.warn( 'Visit the Jenkins web UI and click Manage Jenkins - Reload '
                          'Configuration from Disk' )


    @fabric_task
    def __service_jenkins( self, command ):
        sudo( 'service jenkins %s' % command )
