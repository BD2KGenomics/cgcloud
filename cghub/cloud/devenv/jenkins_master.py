from StringIO import StringIO
from textwrap import dedent

from lxml import etree
from fabric.context_managers import settings, hide
from fabric.operations import run, sudo, put, get
from cghub.cloud.lib.util import ec2_keypair_fingerprint, UserError, private_to_public_key

from cghub.cloud.core.box import fabric_task
from cghub.cloud.core.source_control_client import SourceControlClient
from cghub.cloud.core.ubuntu_box import UbuntuBox


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

    key_dir_path = '%s/.ssh' % home
    """
    The path to the directory containing the jenkins user's SSH keys on the EC2 instance.
    """

    key_path = '%s/id_rsa' % key_dir_path
    """
    The path to the file where the jenkins user's public key is stored on the EC2 instance.
    This public key will be deployed on the build servers such that Jenkins can launch
    its build agents on those servers.
    """


jenkins = Jenkins.__dict__


class JenkinsMaster( UbuntuBox, SourceControlClient ):
    """
    An instance of this class represents the build master in EC2
    """

    def __init__(self, env):
        super( JenkinsMaster, self ).__init__( env )
        self.volume = None

    def release(self):
        return 'raring'

    def create(self, *args, **kwargs):
        self.volume = self.get_or_create_volume( Jenkins.data_volume_name,
                                                 Jenkins.data_volume_size_gb )
        super( JenkinsMaster, self ).create( *args, **kwargs )

    def _on_instance_running(self, first_boot):
        if first_boot:
            self.attach_volume( self.volume, Jenkins.data_device_ext )
        super( JenkinsMaster, self )._on_instance_running( first_boot )

    @fabric_task
    def _setup_package_repos(self):
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

    def _list_packages_to_install(self):
        return super( JenkinsMaster, self )._list_packages_to_install( ) + [
            'ec2-api-tools'
        ]

    @fabric_task
    def _install_packages(self, packages):
        super( JenkinsMaster, self )._install_packages( packages )
        #
        # Use confold so it doesn't get hung up on our pre-staged /etc/default/jenkins
        #
        sudo( 'apt-get -q -y -o Dpkg::Options::=--force-confold install jenkins' )

    @fabric_task
    def _pre_install_packages(self):
        #
        # Pre-stage the defaults file for Jenkins. It differs from the maintainer's version in the
        # following ways: (please document all changes in this comment)
        #
        # 1) cruft was removed
        # 2) --httpListenAddress=127.0.0.1 was added to make Jenkins listen locally only
        #
        instance_type = self.get_instance( ).instance_type
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
    def ec2_keypair_name(cls, env):
        return Jenkins.user + '@' + env.absolute_name( cls.role( ) )

    def __create_jenkins_keypair(self):
        ec2_keypair_name = self.ec2_keypair_name( self.env )
        ec2_keypair = self.connection.get_key_pair( ec2_keypair_name )
        if ec2_keypair is None:
            ec2_keypair = self.connection.create_key_pair( ec2_keypair_name )
            if not ec2_keypair.material:
                raise AssertionError( "Created key pair but didn't get back private key" )
        key_file_exists = sudo( 'test -f %s' % Jenkins.key_path, quiet=True ).succeeded
        #
        # Create an SSH key pair in Jenkin's home and upload the public key to S3.
        #
        if ec2_keypair.material:
            ssh_privkey = ec2_keypair.material
            if key_file_exists:
                # TODO: make this more prominent, e.g. by displaying all warnings at the end
                self._log( 'Warning: Overwriting private key with new one from EC2.' )
                # store private key on box
            put( local_path=StringIO( ssh_privkey ),
                 remote_path=Jenkins.key_path,
                 use_sudo=True )
            assert ec2_keypair.fingerprint == ec2_keypair_fingerprint( ssh_privkey )
            sudo( 'chown {user}:{group} {key_path}'.format( **jenkins ) )
            sudo( 'chmod go= {key_path}'.format( **jenkins ), user=Jenkins.user )
            ssh_pubkey = private_to_public_key( ssh_privkey )
            # Note that we are uploading the public key using the private key's fingerprint
            self.env.upload_ssh_pubkey( ssh_pubkey, ec2_keypair.fingerprint )
        else:
            if key_file_exists:
                # Must use sudo('cat') since get() doesn't support use_sudo
                # See https://github.com/fabric/fabric/issues/700
                with settings( hide( 'stdout' ) ):
                    ssh_privkey = sudo( "cat %s" % Jenkins.key_path, user=Jenkins.user )
                fingerprint = ec2_keypair_fingerprint( ssh_privkey )
                if ec2_keypair.fingerprint != fingerprint:
                    raise UserError(
                        "The fingerprint {ec2_keypair.fingerprint} of key pair {ec2_keypair.name} "
                        "doesn't match the fingerprint {fingerprint} of the private key file "
                        "currently present on the instance. "
                        "Please delete the key pair from EC2 before retrying."
                        .format( key_pair=ec2_keypair, fingerprint=fingerprint ) )
                ssh_pubkey = self.env.download_ssh_pubkey( ec2_keypair )
                if ssh_pubkey != private_to_public_key( ssh_privkey ):
                    raise RuntimeError( "The private key on the data volume doesn't match the "
                                        "public key in EC2." )
            else:
                raise UserError(
                    "The key pair {ec2_keypair.name} is registered in EC2 but the corresponding "
                    "private key file {key_path} does not exist on the instance. In order to "
                    "create the private key file, the key pair must be created at the same time. "
                    "Please delete the key pair from EC2 before retrying."
                    .format( key_pair=ec2_keypair, **jenkins ) )

    @fabric_task
    def _post_install_packages(self):
        self._propagate_authorized_keys( Jenkins.user, Jenkins.group )
        self.__create_jenkins_keypair( )
        self.setup_repo_host_keys( user=Jenkins.user )

    def _ssh_args(self, options, user, command):
        # Add port forwarding to Jenkins' web UI
        options += ( '-L', 'localhost:8080:localhost:8080' )
        return super( JenkinsMaster, self )._ssh_args( options, user, command )

    @fabric_task( user=Jenkins.user )
    def register_slaves(self, slave_clss):
        jenkins_config_file = StringIO( )
        jenkins_config_path = '~/config.xml'
        get( local_path=jenkins_config_file,
             remote_path=jenkins_config_path )
        jenkins_config_file.seek( 0 )
        parser = etree.XMLParser( remove_blank_text=True )
        jenkins_config = etree.parse( jenkins_config_file, parser )
        templates = jenkins_config.find( './/hudson.plugins.ec2.EC2Cloud/templates' )
        for slave_cls in slave_clss:
            slave = slave_cls( self.env )
            images = slave.list_images( )
            try:
                image = images[ -1 ]
            except IndexError:
                raise UserError( "No images for '%s'" % slave_cls.role( ) )
            new_template = slave.slave_config_template( image )
            description = new_template.find( 'description' ).text
            found = False
            for old_template in templates.findall( 'hudson.plugins.ec2.SlaveTemplate' ):
                if old_template.find( 'description' ).text == description:
                    if found:
                        raise RuntimeError( 'More than one existing slave definition for %s. '
                                            'Fix and try again' % description )
                    i = templates.index( old_template )
                    templates[ i ] = new_template
                    found = True
            if not found:
                templates.append( new_template )

        jenkins_config_file.truncate( 0 )
        jenkins_config.write( jenkins_config_file,
                              encoding=jenkins_config.docinfo.encoding,
                              xml_declaration=True,
                              pretty_print=True )
        put( local_path=jenkins_config_file,
             remote_path=jenkins_config_path )
        run( "java -jar /var/cache/jenkins/war/WEB-INF/jenkins-cli.jar "
             "-s http://localhost:8080/ "
             "reload-configuration" )

    def _image_block_device_mapping(self):
        # Do not include the data volume in the snapshot
        bdm = self.get_instance( ).block_device_mapping
        bdm[ Jenkins.data_device_ext ].no_device = True
        return bdm
