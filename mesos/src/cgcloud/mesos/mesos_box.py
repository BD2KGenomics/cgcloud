import logging
from collections import namedtuple

from fabric.context_managers import settings
from fabric.operations import run
from bd2k.util.strings import interpolate as fmt

from cgcloud.core.box import fabric_task
from cgcloud.fabric.operations import sudo, remote_open
from cgcloud.core.common_iam_policies import ec2_read_only_policy
from cgcloud.core.generic_boxes import GenericUbuntuTrustyBox
from cgcloud.lib.util import abreviated_snake_case_class_name, heredoc

log = logging.getLogger( __name__ )

mesos_version = '0.22'

user = 'mesosbox'

install_dir = '/opt/mesosbox'

log_dir = '/var/log/mesosbox'

ephemeral_dir = '/mnt/ephemeral'

persistent_dir = '/mnt/persistent'

shared_dir = '/home/mesosbox/shared'

work_dir = '/var/lib/mesos'

Service = namedtuple( 'Service', [
    'init_name',
    'description',
    'start_script',
    'command',
    'stop_script' ] )


def mesos_service( name, *flags ):
    command = ('/usr/sbin/mesos-{name}', '--log_dir={log_dir}/mesos') + flags
    return Service(
        init_name='mesosbox-' + name,
        description=fmt( 'Mesos {name} service' ),
        start_script='',
        command=fmt( ' '.join( command ) ),
        stop_script='' )


mesos_services = {
    'master': [ mesos_service( 'master',
                               '--registry=in_memory' ) ],
    'slave': [ mesos_service( 'slave',
                              "--master=mesos-master:5050",
                              "--no-switch_user",
                              "--work_dir=" + work_dir ) ] }


class MesosBox( GenericUbuntuTrustyBox ):
    """
    A node in a Mesos cluster. Both slaves and masters are based on this initial setup. Those
    specific roles are determined at boot time. Worker nodes need to be passed the master's IP
    and port before starting up.
    """

    def other_accounts( self ):
        return super( MesosBox, self ).other_accounts( ) + [ user ]

    def default_account( self ):
        return user

    def __init__( self, ctx ):
        super( MesosBox, self ).__init__( ctx )
        self.lazy_dirs = set()

    def _populate_security_group( self, group_name ):
        return super( MesosBox, self )._populate_security_group( group_name ) + [
            dict( ip_protocol='tcp', from_port=0, to_port=65535,
                  src_security_group_name=group_name ),
            dict( ip_protocol='udp', from_port=0, to_port=65535,
                  src_security_group_name=group_name ) ]

    @fabric_task
    def _setup_package_repos( self ):
        super( MesosBox, self )._setup_package_repos( )
        sudo( "apt-key adv --keyserver keyserver.ubuntu.com --recv E56151BF" )
        distro = run( "lsb_release -is" ).lower( )
        codename = run( "lsb_release -cs" )

        sudo( fmt(
            'echo "deb http://repos.mesosphere.io/{distro} {codename} main" | sudo tee /etc/apt/sources.list.d/mesosphere.list' ) )

    def _list_packages_to_install( self ):
        return super( MesosBox, self )._list_packages_to_install( ) + [
            'mesos=0.21.1-1.1.ubuntu1404' ]

    def _pre_install_packages( self ):
        super( MesosBox, self )._pre_install_packages( )
        self.__setup_application_user( )

    def _post_install_packages( self ):
        super( MesosBox, self )._post_install_packages( )
        self._propagate_authorized_keys( user, user )
        self.__setup_ssh_config( )
        self.__create_mesos_keypair( )
        self.__setup_shared_dir( )
        self.__install_mesos_egg( )
        self._setup_mesos( )
        self.__install_mesosbox_tools( )
        self._register_upstart_jobs( mesos_services )

    @fabric_task
    def __setup_ssh_config( self ):
        with remote_open( '/etc/ssh/ssh_config', use_sudo=True ) as f:
            f.write( heredoc( """
                Host spark-master
                    CheckHostIP no
                    HashKnownHosts no""" ) )

    @fabric_task
    def __setup_application_user( self ):
        sudo( fmt( 'useradd '
                   '--home /home/{user} '
                   '--create-home '
                   '--user-group '
                   '--shell /bin/bash {user}' ) )

    def __ec2_keypair_name( self, ctx ):
        return user + '@' + ctx.to_aws_name( self.role( ) )

    @fabric_task( user=user )
    def __create_mesos_keypair( self ):
        self._provide_imported_keypair( ec2_keypair_name=self.__ec2_keypair_name( self.ctx ),
                                        private_key_path=fmt( "/home/{user}/.ssh/id_rsa" ),
                                        overwrite_ec2=True )
        # This trick allows us to roam freely within the cluster as the app user while still
        # being able to have keypairs in authorized_keys managed by cgcloudagent such that
        # external users can login as the app user, too. The trick depends on AuthorizedKeysFile
        # defaulting to or being set to .ssh/autorized_keys and .ssh/autorized_keys2 in sshd_config
        run( "cd .ssh && cat id_rsa.pub >> authorized_keys2" )

    @fabric_task
    def __install_mesosbox_tools( self ):
        """
        Installs the mesos-master-discovery init script and its companion mesos-tools. The latter
        is a Python package distribution that's included in cgcloud-mesos as a resource. This is
        in contrast to the cgcloud agent, which is a standalone distribution.
        """
        tools_dir = install_dir + '/tools'
        sudo( fmt( 'mkdir -p {tools_dir}' ) )

        sudo( fmt( 'virtualenv --no-pip {tools_dir}' ) )
        sudo( fmt( '{tools_dir}/bin/easy_install pip==1.5.2' ) )

        mesos_tools_artifacts = ' '.join( self._project_artifacts( 'mesos-tools' ) )
        with settings( forward_agent=True ):
            sudo( fmt( '{tools_dir}/bin/pip install {mesos_tools_artifacts}' ), pty=False )

        mesos_tools = "MesosTools(**%r)" % dict( user=user,
                                                 shared_dir=shared_dir,
                                                 ephemeral_dir=ephemeral_dir,
                                                 persistent_dir=persistent_dir,
                                                 lazy_dirs=self.lazy_dirs )
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

    @fabric_task
    def _lazy_mkdir( self, parent, name, persistent=False ):
        """
        __lazy_mkdir( '/foo', 'dir', True ) creates /foo/dir now and ensures that
        /mnt/persistent/foo/dir is created and bind-mounted into /foo/dir when the box starts.
        Likewise, __lazy_mkdir( '/foo', 'dir', False) creates /foo/dir now and ensures that
        /mnt/ephemeral/foo/dir is created and bind-mounted into /foo/dir when the box starts.
        Note that at start-up time, /mnt/persistent may be reassigned  to /mnt/ephemeral if no
        EBS volume is mounted at /mnt/persistent.
        """
        assert '/' not in name
        assert parent.startswith( '/' )
        for location in (persistent_dir, ephemeral_dir):
            assert location.startswith( '/' )
            assert not location.startswith( parent ) and not parent.startswith( location )
        logical_path = parent + '/' + name
        sudo( 'mkdir -p "%s"' % logical_path )
        self.lazy_dirs.add( (parent, name, persistent) )
        return logical_path

    @fabric_task
    def __install_mesos_egg( self ):
        run( 'wget http://downloads.mesosphere.io'
             '/master/ubuntu/14.04/mesos-0.22.0-py2.7-linux-x86_64.egg' )
        # We need a newer version of protobuf than comes by default on Ubuntu
        sudo( "pip install --upgrade protobuf", pty=False )
        sudo( "easy_install mesos-0.22.0-py2.7-linux-x86_64.egg" )

    @fabric_task( user=user )
    def __setup_shared_dir( self ):
        run( fmt( 'mkdir -p {shared_dir} && chmod 700 {shared_dir}' ) )

    @fabric_task
    def _setup_mesos( self ):
        sudo( "rm /etc/init/mesos-{master,slave}.conf" )
        self._lazy_mkdir( log_dir, 'mesos', persistent=False )
        self._lazy_mkdir( '/var/lib', 'mesos', persistent=True )

    def _register_upstart_jobs( self, service_map ):
        for node_type, services in service_map.iteritems( ):
            start_on = "mesosbox-start-" + node_type
            # FIXME: Include chdir to logging directory in this script
            for service in services:
                self._register_init_script(
                    service.init_name,
                    heredoc( """
                        description "{service.description}"
                        console log
                        respawn
                        umask 022
                        limit nofile 8000 8192
                        setuid {user}
                        setgid {user}
                        env USER={user}
                        env PYTHONPATH=/home/ubuntu/
                        start on {start_on}
                        stop on runlevel [016]
                        exec {service.command}""" ) )
                start_on = "started " + service.init_name

    def _get_iam_ec2_role( self ):
        role_name, policies = super( MesosBox, self )._get_iam_ec2_role( )
        role_name += '--' + abreviated_snake_case_class_name( MesosBox )
        policies.update( dict(
            ec2_read_only=ec2_read_only_policy,
            ec2_mesos_box=dict( Version="2012-10-17", Statement=[
                dict( Effect="Allow", Resource="*", Action="ec2:CreateTags" ),
                dict( Effect="Allow", Resource="*", Action="ec2:CreateVolume" ),
                dict( Effect="Allow", Resource="*", Action="ec2:AttachVolume" ) ] ) ) )
        return role_name, policies

    def _image_name_prefix( self ):
        # Make this class and its subclasses use the same image
        return "mesos-box"

    def _security_group_name( self ):
        # Make this class and its subclasses use the same security group
        return "mesos-box"


class MesosMaster( MesosBox ):
    """
    A MesosBox that serves as the Mesos master
    """

    def __init__( self, ctx, ebs_volume_size=0 ):
        super( MesosMaster, self ).__init__( ctx )
        self.preparation_args = None
        self.preparation_kwargs = None
        self.ebs_volume_size = ebs_volume_size

    def prepare( self, *args, **kwargs ):
        # Stash away arguments to prepare() so we can use them when cloning the slaves
        self.preparation_args = args
        self.preparation_kwargs = kwargs
        return super( MesosBox, self ).prepare( *args, **kwargs )

    def _populate_instance_tags( self, tags_dict ):
        super( MesosMaster, self )._populate_instance_tags( tags_dict )
        tags_dict[ 'mesos_master' ] = self.instance_id
        if self.ebs_volume_size:
            tags_dict[ 'ebs_volume_size' ] = self.ebs_volume_size

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
        if self.ebs_volume_size:
            tags_dict[ 'ebs_volume_size' ] = self.ebs_volume_size
