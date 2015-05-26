import logging
from StringIO import StringIO
from fabric.operations import run, put, os
from pkginfo import Installed
from textwrap import dedent
from subprocess import check_output
from collections import namedtuple
from cgcloud.core import fabric_task
from pkg_resources import parse_version
from bd2k.util.strings import interpolate as fmt
from cgcloud.fabric.operations import sudo, remote_open
from fabric.context_managers import settings
from cgcloud.core.generic_boxes import GenericUbuntuTrustyBox

log = logging.getLogger( __name__ )

mesos_version = '0.22'

install_dir = '/opt/mesosbox'

Service = namedtuple( 'Service', [
    'init_name',
    'description',
    'start_script',
    'stop_script' ] )

def mesos_service( name, script_suffix=None ):
    if script_suffix is None: script_suffix = name
    script = 'usr/sbin/mesos-{name}.sh'
    return Service(
        init_name='mesos-' + name,
        description=fmt( "Mesos {name} service" ),
        start_script=fmt( script, action='start' ),
        stop_script=fmt( script, action='stop' ) )

mesos_services = {
    'master': [ mesos_service( 'master' ) ],
    'slave': [ mesos_service( 'slave') ] }

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

        run('echo "deb http://repos.mesosphere.io/{} {} main"'
            ' | sudo tee /etc/apt/sources.list.d/mesosphere.list'.format( distro, codename ) )

        sudo("apt-get -y update")

    def _post_install_packages( self ):
        super( MesosBox, self )._post_install_packages( )
        self.lazy_dirs = set( )
        self.__install_mesos( )
        self.__install_mesos_egg( )
        # self.__setEnv()
        # self.__install_mesosbox_tools()

    @fabric_task
    def __setEnv(self):
        spark_env_sh_path = "~/.profile"
        spark_env = dict(
            MESOS_REGISTRY="in_memory",
            MESOS_MASTER='spark-master' )
        with remote_open( spark_env_sh_path, use_sudo=True ) as spark_env_sh:
            spark_env_sh.append("\n")
            for name, value in spark_env.iteritems( ):
                spark_env_sh.append( fmt( 'export {name}="{value}"\n' ) )


    @fabric_task
    def __install_mesosbox_tools( self ):
        """
        Installs the mesos-master-discovery init script and its companion mesos-tools. The latter
        is a Python package distribution that's included in cgcloud-mesos as a resource. This is
        in contrast to the cgcloud agent, which is a standalone distribution.
        """
        version = Installed( __name__ ).version
        if version and not parse_version( version ).is_prerelease:
            git_ref = version
        else:
            git_ref = check_output( [ 'git', 'rev-parse', '--abbrev-ref', 'HEAD' ],
                                    cwd=os.path.dirname( __file__ ) )
        tools_dir = install_dir + '/tools'
        sudo( fmt( 'mkdir -p {tools_dir}') )
        sudo( fmt( 'chown {admin}:{admin} {tools_dir}' ) ) #is this necessary for mesos?
        run( fmt( 'virtualenv --no-pip {tools_dir}' ) )
        run( fmt( '{tools_dir}/bin/easy_install pip==1.5.2' ) )
        with settings( forward_agent=True ):
            run( fmt( '{tools_dir}/bin/pip install '
                      '--process-dependency-links '  # pip 1.5.x deprecates dependency_links in setup.py
                      'git+https://github.com/BD2KGenomics/cgcloud-mesos-tools.git@{git_ref}' ) )
        sudo( fmt( 'chown -R root:root {tools_dir}' ) )
        mesos_tools = "MesosTools(**%r)" % dict( )
        self._register_init_script(
            "mesosbox",
            heredoc( """
                description "Mesos master discovery"
                console log
                start on runlevel [2345]
                stop on runlevel [016]
                pre-start script
                {tools_dir}/bin/python2.7 - <<END
                import logging
                logging.basicConfig( level=logging.INFO )
                from cgcloud.mesos_tools import MesosTools
                mesos_tools = {mesos_tools}
                mesos_tools.start()
                END
                end script
                post-stop script
                {tools_dir}/bin/python2.7 - <<END
                import logging
                logging.basicConfig( level=logging.INFO )
                from cgcloud.mesos_tools import MesosTools
                mesos_tools = {mesos_tools}
                mesos_tools.stop()
                END
                end script""" ) )
        # script_path = "/usr/local/bin/sparkbox-manage-slaves"
        # put( remote_path=script_path, use_sudo=True, local_path=StringIO( heredoc( """
        #     #!{tools_dir}/bin/python2.7
        #     import sys
        #     import logging
        #     logging.basicConfig( level=logging.INFO )
        #     from cgcloud.spark_tools import SparkTools
        #     spark_tools = {spark_tools}
        #     spark_tools.manage_slaves( slaves_to_add=sys.argv[1:] )""" ) ) )
        # sudo( fmt( "chown root:root {script_path} && chmod 755 {script_path}" ) )

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

    def __register_upstart_jobs( self, service_map ):
        for node_type, services in service_map.iteritems( ):
            start_on = "mesosbox-start-" + node_type
            for service in services:
                self._register_init_script(
                    service.init_name,
                    heredoc( """
                        description "{service.description}"
                        console log
                        start on {start_on}
                        stop on runlevel [016]
                        setuid {user}
                        setgid {user}
                        env USER={user}
                        pre-start exec {service.start_script}
                        post-stop exec {service.stop_script}""" ) )
                start_on = "started " + service.init_name

class MesosMaster(MesosBox):

    def __init__( self, ctx, ebs_volume_size=0):
        super( MesosMaster, self ).__init__( ctx )
        self.preparation_args=None
        self.preparation_kwargs=None
        self.ebs_volume_size = ebs_volume_size

    def _populate_instance_tags( self, tags_dict ):
        super( MesosMaster, self )._populate_instance_tags( tags_dict )
        tags_dict[ 'mesos_master' ] = self.instance_id


    def prepare( self, *args, **kwargs ):
        # Stash away arguments to prepare() so we can use them when cloning the slaves
        self.preparation_args = args
        self.preparation_kwargs = kwargs
        return super( MesosBox, self ).prepare( *args, **kwargs )

    def _post_install_packages( self ):
        super( MesosMaster, self )._post_install_packages( )


    def clone( self, num_slaves, slave_instance_type, ebs_volume_size ):
        """
        Create a number of slave boxes that are connected to this master.
        """
        master = self
        first_slave = MesosSlave( master.ctx, num_slaves, master.instance_id, ebs_volume_size )
        args = master.preparation_args
        kwargs = master.preparation_kwargs.copy( )
        kwargs[ 'instance_type' ] = slave_instance_type
        first_slave.prepare( *args, **kwargs )
        other_slaves = first_slave.create( wait_ready=False,
                                           cluster_ordinal=master.cluster_ordinal + 1 )
        all_slaves = [ first_slave ] + other_slaves
        return all_slaves


class MesosSlave( MesosBox ):
    """
    A MesosBox that serves as the Mesos slave. Slaves are cloned from a master box by
    calling the MesosMaster.clone() method.
    """

    def __init__( self, ctx, num_slaves=1, mesos_master_id=None, ebs_volume_size=0 ):
        super( MesosSlave, self ).__init__( ctx )
        self.num_slaves = num_slaves
        self.mesos_master_id = mesos_master_id
        self.ebs_volume_size = ebs_volume_size

    def _populate_instance_creation_args( self, image, kwargs ):
        kwargs.update( dict( min_count=self.num_slaves, max_count=self.num_slaves ) )
        return super( MesosSlave, self )._populate_instance_creation_args( image, kwargs )

    def _populate_instance_tags( self, tags_dict ):
        super( MesosSlave, self )._populate_instance_tags( tags_dict )
        if self.mesos_master_id:
            tags_dict[ 'mesos_master' ] = self.mesos_master_id

def heredoc( s ):
    if s[ 0 ] == '\n': s = s[ 1: ]
    if s[ -1 ] != '\n': s += '\n'
    return fmt( dedent( s ), skip_frames=1 )