from StringIO import StringIO
from textwrap import dedent
from fabric.operations import run, sudo, put, get
from cghub.cloud import config_file_path
from cghub.cloud.ubuntu_ec2_box import UbuntuEc2Box

# EC2's name of the block device to which to attach the Jenkins data volume
JENKINS_DATA_DEVICE_EXT = '/dev/sdf'

# The kernel's name of the block device to which to attach the Jenkins data volume
JENKINS_DATA_DEVICE_INT = '/dev/xvdf'

# The value of the Name tag of the Jenkins data volume
JENKINS_DATA_VOLUME_NAME = 'jenkins-data'

# The label of the file system on the Jenkins data volume
JENKINS_DATA_VOLUME_FS_LABEL = JENKINS_DATA_VOLUME_NAME

# The size of the Jenkins data volume
JENKINS_DATA_VOLUME_SIZE_GB = 100

JENKINS_HOME = '/var/lib/jenkins'


class BuildMaster( UbuntuEc2Box ):
    """
    An instance of this class represents the build master in our EC2 build environment
    """

    @staticmethod
    def name():
        return 'build-master'

    def __init__(self, ec2_options):
        super( BuildMaster, self ).__init__( 'precise', ec2_options )

    def setup(self, update=False):
        self.volume = self.ensure_volume_exists( JENKINS_DATA_VOLUME_NAME,
                                                 JENKINS_DATA_VOLUME_SIZE_GB )
        self.create( )
        self.attach_volume( self.volume, JENKINS_DATA_DEVICE_EXT )
        if update:
            self.execute( self.update_upgrade )
            self.reboot( )
        self.execute( self.setup_jenkins )

    def setup_jenkins(self):
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
            JENKINS_USER=jenkins
            JENKINS_WAR=/usr/share/jenkins/jenkins.war
            JENKINS_HOME="%s"
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
        ''' % JENKINS_HOME ) )
        put( etc_default_jenkins, '/etc/default/jenkins', use_sudo=True, mode=0644 )
        sudo( 'chown root:root /etc/default/jenkins' )

        #
        # Prepare data volume if necessary
        #
        sudo( 'mkdir -p %s' % JENKINS_HOME )
        # Only format empty volumes
        if sudo( 'file -sL %s' % JENKINS_DATA_DEVICE_INT ) == '%s: data' % JENKINS_DATA_DEVICE_INT:
            sudo( 'mkfs -t ext4 %s' % JENKINS_DATA_DEVICE_INT )
            sudo( 'e2label %s %s' % ( JENKINS_DATA_DEVICE_INT, JENKINS_DATA_VOLUME_FS_LABEL ) )
        else:
            # if the volume is not empty, verify the file system label
            label = sudo( 'e2label %s' % JENKINS_DATA_DEVICE_INT )
            if label != JENKINS_DATA_VOLUME_FS_LABEL:
                raise RuntimeError( "Unexpected volume label: '%s'" % label )

        #
        # Mount data volume permanently
        #
        sudo( "echo 'LABEL=%(fs_label)s %(mount_point)s ext4 defaults 0 2' >> /etc/fstab"
              % dict( mount_point=JENKINS_HOME, fs_label=JENKINS_DATA_VOLUME_FS_LABEL ) )
        sudo( 'mount -a' )

        #
        # Install Jenkins and source control scripts
        #
        run( "wget -q -O - 'http://pkg.jenkins-ci.org/debian/jenkins-ci.org.key' "
             "| sudo apt-key add -" )
        sudo( "echo deb http://pkg.jenkins-ci.org/debian binary/ "
              "> /etc/apt/sources.list.d/jenkins.list" )
        sudo( 'apt-get update' )
        # Use confold so it doesn't get hung up on our pre-staged /etc/default/jenkins
        sudo( 'apt-get install -y -o Dpkg::Options::=--force-confold '
              'jenkins git subversion mercurial' )

        #
        # Create an SSH key pair in Jenkin's home and download the public key to local config
        # directory the so we can inject it into the slave boxes. Note that this will prompt
        # the user for a passphrase.
        #
        if sudo( 'test -f %s/.ssh/id_rsa' % JENKINS_HOME, quiet=True ).failed:
            sudo( 'ssh-keygen -f %s/.ssh/id_rsa' % JENKINS_HOME, user='jenkins' )
            sudo( 'sudo chmod go+rx %s/.ssh' % JENKINS_HOME ) # so we can download the pub key
            self._log( 'Remember to configure Jenkins via its web UI to actually use the key.' )

        #
        # Store a copy of the public key locally
        #
        self._download_jenkins_key( )

    @classmethod
    def download_jenkins_key(cls, ec2_options):
        box = cls( ec2_options )
        box.adopt( )
        box.execute( box._download_jenkins_key )

    def _download_jenkins_key(self):
        local_key_path = config_file_path( 'jenkins.id_rsa.pub' )
        get( '%s/.ssh/id_rsa.pub' % JENKINS_HOME, local_key_path )

