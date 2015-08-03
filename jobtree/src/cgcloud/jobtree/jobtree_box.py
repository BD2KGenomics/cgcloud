import logging
from cgcloud.core import fabric_task
from cgcloud.mesos.mesos_box import MesosBox, MesosMaster
from cgcloud.fabric.operations import sudo
from bd2k.util.strings import interpolate as fmt
from cgcloud.lib.util import abreviated_snake_case_class_name
from cgcloud.core.common_iam_policies import ec2_full_policy, s3_full_policy, sdb_full_policy
from fabric.context_managers import settings
from textwrap import dedent

log = logging.getLogger( __name__ )

mesos_version = '0.22'

user = 'jobtreebox'

install_dir = '/opt/mesosbox'

log_dir = '/var/log/mesosbox/'

ephemeral_dir = '/mnt/ephemeral'

persistent_dir = '/mnt/persistent'

class JobTreeBox(MesosBox):
    def __init__( self, ctx ):
        super( JobTreeBox, self ).__init__( ctx )
        self.lazy_dirs=set()

    def _pre_install_packages( self ):
        super( JobTreeBox, self)._pre_install_packages()

    def _post_install_packages( self ):
        super( JobTreeBox, self )._post_install_packages( )
        self._install_git( )
        self._install_boto( )
        self.__install_jobtree( )
        self._install_docker( )
        self._docker_group( )

    def _get_iam_ec2_role( self ):
        role_name, policies = super( JobTreeBox, self )._get_iam_ec2_role( )
        role_name += '--' + abreviated_snake_case_class_name( JobTreeBox )
        policies.update( dict(
            ec2_full=ec2_full_policy,
            s3_full=s3_full_policy,
            sbd_full=sdb_full_policy,
            ec2_jobtree_box=dict( Version="2012-10-17", Statement=[
                dict( Effect="Allow", Resource="*", Action="ec2:CreateTags" ),
                dict( Effect="Allow", Resource="*", Action="ec2:CreateVolume" ),
                dict( Effect="Allow", Resource="*", Action="ec2:AttachVolume" ) ] ) ) )
        return role_name, policies

    @fabric_task
    def _setup_application_user( self ):
        # changed from __ to _ to prevent name mangling.
        # overridden so that the method will access our module level 'user' variable.
        sudo( fmt( 'useradd '
                   '--home /home/{user} '
                   '--create-home '
                   '--user-group '
                   '--shell /bin/bash {user}' ) )
    @fabric_task
    def _propagate_authorized_keys( self, user_discarded, group=None ):
        # overridden, throw away passed in user so that we get jobtreebox user
        super(JobTreeBox, self)._propagate_authorized_keys(user, user)

    @fabric_task
    def _docker_group(self):
        sudo("gpasswd -a {} docker".format(user))
        sudo("sudo service docker.io restart")

    @fabric_task
    def _install_docker(self):
        sudo("apt-get -y install docker.io")

    @fabric_task
    def _install_git(self):
        sudo("apt-get -y install git") # downloading from git requires git tools.

    @fabric_task
    def _install_boto(self):
        sudo("pip install boto") # downloading from git requires git tools.

    @fabric_task
    def __install_jobtree(self):
        sudo("apt-get -y install python-dev")
        sudo("pip install git+https://github.com/BD2KGenomics/toil.git@master")
        sudo("chmod +x /usr/local/lib/python2.7/dist-packages/toil/batchSystems/mesos/executor.py")

    @fabric_task
    def _install_mesosbox_tools( self ):
        """
        Installs the mesos-master-discovery init script and its companion mesos-tools. The latter
        is a Python package distribution that's included in cgcloud-mesos as a resource. This is
        in contrast to the cgcloud agent, which is a standalone distribution.
        """
        tools_dir = install_dir + '/tools'
        sudo( fmt( 'mkdir -p {tools_dir}') )
        sudo( fmt( 'virtualenv --no-pip {tools_dir}' ) )
        sudo( fmt( '{tools_dir}/bin/easy_install pip==1.5.2' ) )

        mesos_tools_artifacts = ' '.join( self._project_artifacts( 'mesos-tools' ) )
        with settings( forward_agent=True ):
            sudo( fmt( '{tools_dir}/bin/pip install {mesos_tools_artifacts}' ) )

        mesos_tools = "MesosTools(**%r)" % dict(user=user, persistent_dir=persistent_dir, ephemeral_dir=ephemeral_dir,
                                                lazy_dirs=self.lazy_dirs)
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

    def _register_upstart_jobs( self, service_map ):
        for node_type, services in service_map.iteritems( ):
            start_on = "mesosbox-start-" + node_type
            for service in services: # FIXME: include chdir to logging directory in this script
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
                        exec {service.action}""" ) )
                start_on = "started " + service.init_name

class JobTreeLeader(JobTreeBox, MesosMaster):
    def __init__( self, ctx ):
        super( JobTreeLeader, self ).__init__( ctx )

    def _post_install_packages( self ):
        super( JobTreeLeader, self )._post_install_packages( )

    def clone( self, num_slaves, slave_instance_type, ebs_volume_size ):
        """
        Create a number of slave boxes that are connected to this master.
        """
        master = self
        first_slave = JobTreeWorker( master.ctx, num_slaves, master.instance_id, ebs_volume_size )
        args = master.preparation_args
        kwargs = master.preparation_kwargs.copy( )
        kwargs[ 'instance_type' ] = slave_instance_type
        first_slave.prepare( *args, **kwargs )
        other_slaves = first_slave.create( wait_ready=False,
                                           cluster_ordinal=master.cluster_ordinal + 1 )
        all_slaves = [ first_slave ] + other_slaves
        return all_slaves

class JobTreeWorker(JobTreeBox):
    def __init__( self, ctx, num_slaves=1, mesos_master_id=None, ebs_volume_size=0 ):
        super( JobTreeWorker, self ).__init__( ctx )
        self.num_slaves = num_slaves
        self.mesos_master_id = mesos_master_id
        self.ebs_volume_size = ebs_volume_size

    def _populate_instance_creation_args( self, image, kwargs ):
        kwargs.update( dict( min_count=self.num_slaves, max_count=self.num_slaves ) )
        return super( JobTreeWorker, self )._populate_instance_creation_args( image, kwargs )

    def _populate_instance_tags( self, tags_dict ):
        super( JobTreeWorker, self )._populate_instance_tags( tags_dict )
        if self.mesos_master_id:
            tags_dict[ 'mesos_master' ] = self.mesos_master_id
            tags_dict[ 'ebs_volume_size' ] = self.ebs_volume_size

def heredoc( s ):
    if s[ 0 ] == '\n': s = s[ 1: ]
    if s[ -1 ] != '\n': s += '\n'
    return fmt( dedent( s ), skip_frames=1 )