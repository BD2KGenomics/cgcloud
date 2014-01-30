from urlparse import urlparse
from fabric.operations import run, sudo, os
from cghub.cloud.core.box import fabric_task
from cghub.cloud.core.centos_box import CentosBox
from cghub.cloud.core.fedora_box import FedoraBox
from cghub.cloud.core.ubuntu_box import UbuntuBox


class GenericCentos5Box( CentosBox ):
    """
    Good ole CentOS 5 from 1995, more or less
    """

    def release( self ):
        return '5.8'

    def __update_sudo( self ):
        """
        5.8 has sudo 1.7.2p1 whose -i switch is horribly broken. For example,

        sudo -u jenkins -i bash -c 'echo bla >> ~/foo'

        doesn't work as expected. In sudo 1.8.7, it does. We do need sudo -i in some of the
        subclasses (see cghub.fabric.operations for how we hack -i into Fabric 1.7.x) and so we
        install a newer version of the sudo rpm from the sudo maintainer.

        This method should to be invoked early on during setup.
        """
        self._yum_local( is_update=True, rpm_urls=[
            'ftp://ftp.sudo.ws/pub/sudo/packages/Centos/5/sudo-1.8.9-5.el5.x86_64.rpm' ] )

    def _on_instance_ready( self, first_boot ):
        super( GenericCentos5Box, self )._on_instance_ready( first_boot )
        if self.generation == 0 and first_boot:
            self.__update_sudo( )
            if False:
                self._update_openssh( )

    def _ephemeral_mount_point( self ):
        return "/mnt"

    # FIXME: These two methods assume that this class is derived from AgentBox.

    def _get_package_substitutions( self ):
        return super( GenericCentos5Box, self )._get_package_substitutions( ) + [
            ( 'python', 'python26' ),
            ( 'python-devel', 'python26-devel' )
        ]

    @fabric_task
    def _post_install_packages( self ):
        # The pip from the python-pip package is hard-wired to the python 2.4 from the python
        # package. Also it's ancient, fossilized crap. To get an up-to-date pip that is wired to
        # python 2.6 from the python26 package we have to jump though some hoops. First,
        # we need to ignore certs since the CA package on CentOS 5 is, you guessed it, out of date.
        sudo( 'echo "check_certificate=off" > /root/.wgetrc' )
        # Then install setuptools ...
        run( 'wget https://bitbucket.org/pypa/setuptools/raw/bootstrap/ez_setup.py' )
        sudo( 'python26 ez_setup.py' )
        # .. and pip.
        run( 'wget https://raw.github.com/pypa/pip/master/contrib/get-pip.py' )
        sudo( 'python26 get-pip.py' )
        super( GenericCentos5Box, self )._post_install_packages( )


class GenericCentos6Box( CentosBox ):
    """
    The slightly newer CentOS 6 from 1999 ;-)
    """

    def release( self ):
        return '6.4'

    def _ephemeral_mount_point( self ):
        return "/mnt/ephemeral"

    def _on_instance_ready( self, first_boot ):
        super( GenericCentos6Box, self )._on_instance_ready( first_boot )
        if self.generation == 0 and first_boot:
            if False:
                self._update_openssh( )


class GenericUbuntuLucidBox( UbuntuBox ):
    """
    10.04 LTS
    """

    def release( self ):
        return 'lucid'

    @fabric_task
    def __update_sudo( self ):
        """
        See GenericCentos5Box
        """
        url = 'ftp://ftp.sudo.ws/pub/sudo/packages/Ubuntu/10.04/sudo_1.8.9-5_amd64.deb'
        package = os.path.basename( urlparse( url ).path )
        run( 'wget ' + url )
        sudo( 'sudo dpkg --force-confold -i ' + package )
        run( 'rm ' + package )

    def _on_instance_ready( self, first_boot ):
        super( GenericUbuntuLucidBox, self )._on_instance_ready( first_boot )
        if self.generation == 0 and first_boot:
            self.__update_sudo( )

    def _get_package_substitutions( self ):
        return super( GenericUbuntuLucidBox, self )._get_package_substitutions( ) + [
            ('git', 'git-core') ]


class GenericUbuntuMaverickBox( UbuntuBox ):
    """
    10.10
    """

    def release( self ):
        return 'maverick'


class GenericUbuntuNattyBox( UbuntuBox ):
    """
    11.04
    """

    def release( self ):
        return 'natty'


class GenericUbuntuOneiricBox( UbuntuBox ):
    """
    11.10
    """

    def release( self ):
        return 'oneiric'


class GenericUbuntuPreciseBox( UbuntuBox ):
    """
    12.04 LTS
    """

    def release( self ):
        return 'precise'


class GenericUbuntuQuantalBox( UbuntuBox ):
    """
    12.10
    """

    def release( self ):
        return 'quantal'


class GenericUbuntuRaringBox( UbuntuBox ):
    """
    13.04
    """

    def release( self ):
        return 'raring'


class GenericUbuntuSaucyBox( UbuntuBox ):
    """
    13.10
    """

    def release( self ):
        return 'saucy'


class GenericFedora17Box( FedoraBox ):
    """
    This one doesn't work since the AMI was deleted by the Fedora guys
    """

    def release( self ):
        return 17


class GenericFedora18Box( FedoraBox ):
    """
    This one doesn't work since the AMI was deleted by the Fedora guys
    """

    def release( self ):
        return 18


class GenericFedora19Box( FedoraBox ):
    def release( self ):
        return 19


class GenericFedora20Box( FedoraBox ):
    def release( self ):
        return 20