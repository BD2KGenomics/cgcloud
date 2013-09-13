from StringIO import StringIO
from textwrap import dedent
from fabric.context_managers import settings, hide
from fabric.operations import run, sudo, put, get
from cghub.cloud.box import fabric_task
from cghub.cloud.devenv.source_control_client import SourceControlClient
from cghub.cloud.ubuntu_box import UbuntuBox
from cghub.util import ec2_keypair_fingerprint, UserError


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

    pubkey_config_file = 'jenkins.id_rsa.pub'
    """
    The name of the config file where the jenkins user's public key is stored on the system running
    this code.
    """


jenkins = Jenkins.__dict__


class JenkinsMaster( UbuntuBox, SourceControlClient ):
    """
    An instance of this class represents the build master in EC2
    """

    def release(self):
        return 'raring'

    def create(self, *args, **kwargs):
        self.volume = self.get_or_create_volume( Jenkins.data_volume_name,
                                                 Jenkins.data_volume_size_gb )
        super( JenkinsMaster, self ).create( *args, **kwargs )
        self.attach_volume( self.volume, Jenkins.data_device_ext )

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
        etc_default_jenkins = StringIO( dedent( '''\
            NAME=jenkins
            JAVA=/usr/bin/java
            #JAVA_ARGS="-Xmx256m"
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
        '''.format( **jenkins ) ) )
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

    @fabric_task
    def _post_install_packages(self):
        self._propagate_authorized_keys( Jenkins.user, Jenkins.group )
        ec2_key_pair_name = '{user}@{host}'.format( user=Jenkins.user, host=self.absolute_role( ) )
        ec2_keypair = self.connection.get_key_pair( ec2_key_pair_name )
        if ec2_keypair is None:
            ec2_keypair = self.connection.create_key_pair( ec2_key_pair_name )
            if not ec2_keypair.material:
                raise AssertionError( "Created key pair but didn't get back private key" )
        key_file_exists = sudo( 'test -f %s' % Jenkins.key_path, quiet=True ).succeeded
        #
        # Create an SSH key pair in Jenkin's home and download the public key to local config
        # directory so we can inject it into the slave boxes. Note that this will prompt the user
        # for a passphrase.
        #
        if ec2_keypair.material:
            if key_file_exists:
                # TODO: make this more prominent, e.g. by displaying all warnings at the end
                self._log( 'Warning: Overwriting private key with new one from EC2.' )

            # upload private key
            put( local_path=StringIO( ec2_keypair.material ),
                 remote_path=Jenkins.key_path,
                 use_sudo=True )
            assert ec2_keypair.fingerprint == ec2_keypair_fingerprint( ec2_keypair.material )
            sudo( 'chown {user}:{group} {key_path}'.format( **jenkins ) )
            # so get_keys can download the keys
            sudo( 'chmod go+rx {key_dir_path}'.format( **jenkins ),
                  user=Jenkins.user )
            sudo( 'chmod go= {key_path}'.format( **jenkins ),
                  user=Jenkins.user )
            # generate public key from private key
            sudo( 'ssh-keygen -y -f {key_path} > {key_path}.pub'.format( **jenkins ),
                  user=Jenkins.user )
        else:
            if key_file_exists:
                try:
                    # Must use sudo('cat') since get() doesn't support use_sudo
                    # See https://github.com/fabric/fabric/issues/700
                    with settings( hide( 'stdout' ) ):
                        ssh_privkey = sudo( "cat %s" % Jenkins.key_path, user=Jenkins.user )
                    fingerprint = ec2_keypair_fingerprint( ssh_privkey )
                finally:
                    ssh_privkey = None
                if ec2_keypair.fingerprint != fingerprint:
                    raise UserError(
                        "The fingerprint {ec2_keypair.fingerprint} of key pair {ec2_keypair.name} "
                        "doesn't match the fingerprint {fingerprint} of the private key file "
                        "currently present on the instance. "
                        "Please delete the key pair from EC2 before retrying."
                        .format( key_pair=ec2_keypair, fingerprint=fingerprint ) )
            else:
                raise UserError(
                    "The key pair {ec2_keypair.name} is registered in EC2 but the corresponding "
                    "private key file {key_path} does not exist on the instance. In order to "
                    "create the private key file, the key pair must be created at the same time. "
                    "Please delete the key pair from EC2 before retrying."
                    .format( key_pair=ec2_keypair, **jenkins ) )

        # Store a copy of the public key locally
        #
        self.__get_jenkins_key( )
        self.setup_repo_host_keys( user=Jenkins.user )

    def get_keys(self):
        super( JenkinsMaster, self ).get_keys( )
        self.__get_jenkins_key( )

    @fabric_task
    def __get_jenkins_key(self):
        get( remote_path='%s.pub' % Jenkins.key_path,
             local_path=self._config_file_path( Jenkins.pubkey_config_file, mkdir=True ) )

    def _ssh_args(self, options, user, command ):
        # Add port forwarding to Jenkins' web UI
        options += ( '-L', 'localhost:8080:localhost:8080' )
        return super( JenkinsMaster, self )._ssh_args( options, user, command )
