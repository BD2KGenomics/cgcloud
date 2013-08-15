import re
from fabric.operations import run, sudo
from box import Box
from distutils.version import LooseVersion

ADMIN_USER = 'admin'


class CentosBox( Box ):
    """
    A box representing EC2 instances that boots of a RightScale CentOS AMI. Most of the
    complexity in this class stems from a workaround for RightScale's handling of the root
    account. RightScale does not offer a non-root admin account, so after the instance boots for
    the first time, we create an admin account and disable SSH and console logins to the root
    account, just like on Canonical's Ubuntu AMIs. The instance is tagged with the name of the
    admin account such that we can look it up later.
    """

    def __init__(self, env, release):
        super( CentosBox, self ).__init__( env )
        self._username = None
        images = self.connection.get_all_images( owners='411009282317',
                                                 filters={
                                                     'name': 'RightImage_CentOS_%s_x64*' % release,
                                                     'root-device-type': 'ebs' } )
        if not images:
            raise RuntimeError( "Can't find any suitable CentOS AMIs" )

        max_version = None
        base_image = None
        for image in images:
            match = re.match( 'RightImage_CentOS_(\d+(?:\.\d+)*)_x64_v(\d+(?:\.\d+)*)_EBS',
                              image.name )
            if match:
                assert match.group( 1 ) == release
                version = LooseVersion( match.group( 2 ) )
                if max_version is None or max_version < version:
                    max_version = version
                    base_image = image

        if not base_image:
            raise RuntimeError( "Can't find AMI matching CentOS %s" % release )

        self.base_image = base_image
        ':type: boto.ec2.image.Image'

    def username(self):
        if self._username is None:
            self._username = self.get_instance( ).tags.get( 'admin_user', 'root' )
        return self._username

    def _set_username(self, admin_user):
        self._username = admin_user
        self.get_instance( ).add_tag( 'admin_user', admin_user )

    def image_id(self):
        return self.base_image.id

    def setup(self, update=False):
        if self.username( ) == 'root':
            self._execute( self.__create_admin )
            self._set_username( ADMIN_USER )
            self._execute( self.__setup_admin )
        if update:
            self._execute( self._update )
            self.reboot( )

    def __create_admin(self):
        # don't clear screen on logout, it's annoying
        run( r"sed -i -r 's!^(/usr/bin/)?clear!# \0!' /etc/skel/.bash_logout ~/.bash_logout" )
        # Imitate the security model of Canonical's Ubuntu AMIs: Create an admin user that can sudo
        # without password and disable root logins via console and ssh.
        run( 'useradd -m {0}'.format( ADMIN_USER ) )
        self._propagate_authorized_keys( ADMIN_USER )
        run( 'rm ~/.ssh/authorized_keys' )
        run( 'echo "{0}  ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers'.format( ADMIN_USER ) )
        run( 'passwd -l root' )
        run( 'echo PermitRootLogin no >> /etc/ssh/sshd_config' )

    def __setup_admin(self):
        run( "echo 'export PATH=\"/usr/local/sbin:/usr/sbin:/sbin:$PATH\"' >> ~/.bash_profile" )

    def _update(self):
        sudo( 'yum update -y -d 1' )