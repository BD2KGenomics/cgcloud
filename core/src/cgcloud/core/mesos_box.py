from fabric.operations import run
from bd2k.util.strings import interpolate as fmt

from cgcloud.core.box import fabric_task
from cgcloud.core.ubuntu_box import UbuntuBox
from cgcloud.fabric.operations import sudo, pip


class MesosBox( UbuntuBox ):
    """
    A mixin for getting Mesos installed from Mesosphere's Debian repository
    """

    def _mesos_version( self ):
        return '0.25.0'

    @fabric_task
    def _setup_package_repos( self ):
        super( MesosBox, self )._setup_package_repos( )
        sudo( 'apt-key adv --keyserver keyserver.ubuntu.com --recv E56151BF' )
        codename = self.release( ).codename
        sudo( fmt( 'echo "deb http://repos.mesosphere.io/ubuntu {codename} main" '
                   '> /etc/apt/sources.list.d/mesosphere.list' ) )

    def _list_packages_to_install( self ):
        return super( MesosBox, self )._list_packages_to_install( ) + [
            'python2.7',
            'mesos=' + self._mesos_version( ) + '-*' ]

    def _post_install_packages( self ):
        super( MesosBox, self )._post_install_packages( )
        self.__install_mesos_egg( )

    @fabric_task
    def __install_mesos_egg( self ):
        egg = 'mesos-' + self._mesos_version( ) + '-py2.7-linux-x86_64.egg'
        version = self.release( ).version
        run( fmt( 'wget http://downloads.mesosphere.io/master/ubuntu/{version}/{egg}' ) )
        # We need a newer version of protobuf than what comes default on Ubuntu
        pip( 'install --upgrade protobuf', use_sudo=True )
        sudo( 'easy_install -a ' + egg )
        run( 'rm ' + egg )
