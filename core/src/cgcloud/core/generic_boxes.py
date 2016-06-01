from urlparse import urlparse

from fabric.operations import run, sudo, os

from cgcloud.core.deprecated import deprecated
from cgcloud.core.box import fabric_task
from cgcloud.core.centos_box import CentosBox
from cgcloud.core.fedora_box import FedoraBox
from cgcloud.core.ubuntu_box import UpstartUbuntuBox, SystemdUbuntuBox


@deprecated
class GenericCentos5Box( CentosBox ):
    """
    Good ole CentOS 5 from 1995, more or less
    """

    def release( self ):
        return '5.8'

    @classmethod
    def recommended_instance_type( cls ):
        # On t1.micro, the agent installation runs out of memory
        return "m1.small"

    @classmethod
    def supported_virtualization_types( cls ):
        return [ 'paravirtual' ]

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
            'ftp://ftp.sudo.ws/pub/sudo/packages/Centos/5/sudo-1.8.14-4.el5.x86_64.rpm' ] )

    def _on_instance_ready( self, first_boot ):
        super( GenericCentos5Box, self )._on_instance_ready( first_boot )
        if self.generation == 0 and first_boot:
            self.__update_sudo( )
            if False:
                self._update_openssh( )

    def _ephemeral_mount_point( self, i ):
        return "/mnt" if i == 0 else None

    # FIXME: These two methods assume that this class is derived from AgentBox.

    def _get_package_substitutions( self ):
        return super( GenericCentos5Box, self )._get_package_substitutions( ) + [
            ('python', 'python26'),
            ('python-devel', 'python26-devel')
        ]

    def _post_install_packages( self ):
        if 'python' in self._list_packages_to_install( ):
            self.__update_python( )
        super( GenericCentos5Box, self )._post_install_packages( )

    @fabric_task
    def __update_python( self ):
        # The pip from the python-pip package is hard-wired to the python 2.4 from the python
        # package. Also it's ancient, fossilized crap. To get an up-to-date pip that is
        # wired to python 2.6 from the python26 package we have to jump though some hoops.
        # First, we need to ignore certs since the CA package on CentOS 5 is, you guessed it,
        # out of date. We do this globally because the downloaded .py scripts execute wget
        # internally. Nevertheless, we got cert errors with github.com and so we are using
        # curl instead to download the scripts from there.
        sudo( 'echo "check_certificate=off" > /root/.wgetrc' )
        # Then install setuptools ...
        run( 'curl -O https://bitbucket.org/pypa/setuptools/raw/bootstrap/ez_setup.py' )
        sudo( 'python2.6 ez_setup.py' )
        # .. and pip.
        run( 'curl -O https://raw.githubusercontent.com/pypa/pip/master/contrib/get-pip.py' )
        sudo( 'python2.6 get-pip.py' )
        sudo( 'rm /root/.wgetrc' )


class GenericCentos6Box( CentosBox ):
    """
    The slightly newer CentOS 6 from 1999 ;-)
    """

    def release( self ):
        return '6.4'

    def _ephemeral_mount_point( self, i ):
        return "/mnt/ephemeral" if i == 0 else None

    def _on_instance_ready( self, first_boot ):
        super( GenericCentos6Box, self )._on_instance_ready( first_boot )
        if self.generation == 0 and first_boot:
            if False:
                self._update_openssh( )


@deprecated
class GenericUbuntuLucidBox( UpstartUbuntuBox ):
    def release( self ):
        return self.Release( codename='lucid', version='10.04' )

    @classmethod
    def supported_virtualization_types( cls ):
        return [ 'paravirtual' ]

    def _get_virtual_block_device_prefix( self ):
        return "/dev/sd"

    @fabric_task
    def __update_sudo( self ):
        """
        See GenericCentos5Box
        """
        url = 'ftp://ftp.sudo.ws/pub/sudo/packages/Ubuntu/10.04/sudo_1.8.14-4_amd64.deb'
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


@deprecated
class GenericUbuntuMaverickBox( UpstartUbuntuBox ):
    def release( self ):
        return self.Release( codename='maverick', version='10.10' )

    @classmethod
    def supported_virtualization_types( cls ):
        return [ 'paravirtual' ]


@deprecated
class GenericUbuntuNattyBox( UpstartUbuntuBox ):
    def release( self ):
        return self.Release( codename='natty', version='11.04' )

    @classmethod
    def supported_virtualization_types( cls ):
        return [ 'paravirtual' ]


@deprecated
class GenericUbuntuOneiricBox( UpstartUbuntuBox ):
    def release( self ):
        return self.Release( codename='oneiric', version='11.10' )

    @classmethod
    def supported_virtualization_types( cls ):
        return [ 'paravirtual' ]


class GenericUbuntuPreciseBox( UpstartUbuntuBox ):
    def release( self ):
        return self.Release( codename='precise', version='12.04' )


@deprecated
class GenericUbuntuQuantalBox( UpstartUbuntuBox ):
    def release( self ):
        return self.Release( codename='quantal', version='12.10' )


@deprecated
class GenericUbuntuRaringBox( UpstartUbuntuBox ):
    def release( self ):
        return self.Release( codename='raring', version='13.04' )


@deprecated
class GenericUbuntuSaucyBox( UpstartUbuntuBox ):
    def release( self ):
        return self.Release( codename='saucy', version='13.10' )


class GenericUbuntuTrustyBox( UpstartUbuntuBox ):
    def release( self ):
        return self.Release( codename='trusty', version='14.04' )


@deprecated
class GenericUbuntuUtopicBox( UpstartUbuntuBox ):
    def release( self ):
        return self.Release( codename='utopic', version='14.10' )


class GenericUbuntuVividBox( SystemdUbuntuBox ):
    def release( self ):
        return self.Release( codename='vivid', version='15.04' )


@deprecated
class GenericFedora17Box( FedoraBox ):
    """
    This one doesn't work since the AMI was deleted by the Fedora guys
    """

    def release( self ):
        return 17


@deprecated
class GenericFedora18Box( FedoraBox ):
    """
    This one doesn't work since the AMI was deleted by the Fedora guys
    """

    def release( self ):
        return 18


@deprecated
class GenericFedora19Box( FedoraBox ):
    def release( self ):
        return 19

    @classmethod
    def recommended_instance_type( cls ):
        # On t1.micro, the agent installation runs out of memory
        return "m1.small"

    @classmethod
    def supported_virtualization_types( cls ):
        return [ 'paravirtual' ]


@deprecated
class GenericFedora20Box( FedoraBox ):
    def release( self ):
        return 20

    @classmethod
    def recommended_instance_type( cls ):
        # On t1.micro, the agent installation runs out of memory
        return "m1.small"

    @classmethod
    def supported_virtualization_types( cls ):
        return [ 'paravirtual' ]

    # FIXME: Consider pulling this up

    def _populate_cloud_config( self, instance_type, user_data ):
        super( GenericFedora20Box, self )._populate_cloud_config( instance_type, user_data )
        user_data[ 'bootcmd' ][ 0:0 ] = [
            self._get_package_installation_command( 'yum-plugin-fastestmirror' ),
            [ 'yum', 'clean', 'all' ] ]


class GenericFedora21Box( FedoraBox ):
    def release( self ):
        return 21


class GenericFedora22Box( FedoraBox ):
    def release( self ):
        return 22

    def _on_instance_ready( self, first_boot ):
        if first_boot:
            self.__fix_stupid_locale_problem( )
        super( GenericFedora22Box, self )._on_instance_ready( first_boot )

    @fabric_task
    def __fix_stupid_locale_problem( self ):
        """
        The bug:
        https://bugzilla.redhat.com/show_bug.cgi?id=1261249

        The workaround:
        https://www.banym.de/linux/fedora/problems-with-missing-locale-files-on-fedora-20-made-libvirtd-service-not-starting
        """
        sudo( 'localedef -c -i en_US -f UTF-8 en_US.UTF-8' )
