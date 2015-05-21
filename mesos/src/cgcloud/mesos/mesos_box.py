import logging
from fabric.operations import run, put, os

from cgcloud.core import fabric_task
from cgcloud.fabric.operations import sudo, remote_open
from cgcloud.core.generic_boxes import GenericUbuntuTrustyBox

log = logging.getLogger( __name__ )

mesos_version = '0.22'


class MesosBox(GenericUbuntuTrustyBox):
    """
    Node in a mesos cluster. Both workers and masters are based on this initial setup. Those specific roles
    are determined at boot time. Worker nodes need to be passed the master's ip and port before starting up.
    """
    def __init__( self, ctx ):
        super( MesosBox, self ).__init__( ctx )

    @fabric_task
    def _setup_package_repos( self ):
        super( MesosBox, self )._setup_package_repos( )
        sudo("apt-key adv --keyserver keyserver.ubuntu.com --recv E56151BF")
        distro=run("lsb_release -is | tr '[:upper:]' '[:lower:]'")
        codename=run("lsb_release -cs")

        run('echo "deb http://repos.mesosphere.io/{DISTRO} {CODENAME} main""'
            ' | sudo tee /etc/apt/sources.list.d/mesosphere.list'.format( distro, codename ) )

        sudo("apt-get -y update")

    def _post_install_packages( self ):
        super( MesosBox, self )._post_install_packages( )
        self.lazy_dirs = set( )
        self.__install_mesos( )
        self.__install_mesos_egg( )

    @fabric_task
    def __install_mesos(self):
        sudo("apt-get -y install mesos")

    @fabric_task
    def __install_mesos_egg(self):
        # FIXME: this is the ubuntu 14.04 version. Wont work with other versions.
        run("wget http://downloads.mesosphere.io/master/ubuntu/14.04/mesos-0.22.0-py2.7-linux-x86_64.egg")

        # we need a newer version of protobuf than comes default on ubuntu
        sudo("pip install --upgrade protobuf")
        sudo("easy_install mesos-0.22.0-py2.7-linux-x86_64.egg")


class MesosMaster(MesosBox):

    def __init__( self, ctx):
        super( MesosMaster, self ).__init__( ctx )

    def _populate_instance_tags( self, tags_dict ):
        super( MesosMaster, self )._populate_instance_tags( tags_dict )
        tags_dict[ 'mesos_master' ] = self.instance_id