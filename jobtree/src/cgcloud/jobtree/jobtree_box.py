import logging
from cgcloud.core import fabric_task
from cgcloud.mesos.mesos_box import MesosBox, MesosMaster, MesosSlave, Service, mesos_services, mesos_service
from cgcloud.fabric.operations import sudo
from cgcloud.lib.util import abreviated_snake_case_class_name
from cgcloud.core.common_iam_policies import ec2_full_policy, s3_full_policy, sdb_full_policy

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

    def _post_install_packages( self ):
        super( JobTreeBox, self )._post_install_packages( )
        self._install_git( )
        self._install_boto( )
        self.__install_jobtree( )

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
    def _install_git(self):
        sudo("apt-get -y install git") # downloading from git requires git tools.

    @fabric_task
    def _install_boto(self):
        sudo("pip install boto") # downloading from git requires git tools.

    @fabric_task
    def __install_jobtree(self):
        sudo("apt-get -y install python-dev")
        sudo("pip install git+https://github.com/BD2KGenomics/jobTree.git@dag-rebased")
        sudo("chmod +x /usr/local/lib/python2.7/dist-packages/jobTree/batchSystems/mesos/executor.*")
        #sudo("chmod +x /usr/local/lib/python2.7/dist-packages/jobTree/*.py")

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