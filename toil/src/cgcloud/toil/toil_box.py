import logging
from cgcloud.core import fabric_task
from cgcloud.mesos.mesos_box import MesosBox, MesosMaster, MesosSlave
from cgcloud.fabric.operations import sudo
from bd2k.util.strings import interpolate as fmt
from cgcloud.lib.util import abreviated_snake_case_class_name
from cgcloud.core.common_iam_policies import ec2_full_policy, s3_full_policy, sdb_full_policy
from fabric.context_managers import settings
from textwrap import dedent

log = logging.getLogger( __name__ )

mesos_version = '0.22'

user = 'mesosbox'

install_dir = '/opt/mesosbox'

log_dir = '/var/log/mesosbox/'

ephemeral_dir = '/mnt/ephemeral'

persistent_dir = '/mnt/persistent'

class ToilBox(MesosBox):
    def __init__( self, ctx):
        super( ToilBox, self ).__init__( ctx)
        self.lazy_dirs=set()

    def _pre_install_packages( self ):
        super( ToilBox, self)._pre_install_packages()

    def _post_install_packages( self ):
        super( ToilBox, self )._post_install_packages( )
        self._install_boto( )
        self._upgrade_pip( )
        self.__install_toil( )
        self._docker_group(user=user)

    def _list_packages_to_install( self ):
        # packages to apt-get
        # FIXME: GIT WILL BECOME UNNECESSARY UPON COMPLETION OF https://github.com/BD2KGenomics/toil/issues/215
        return super( ToilBox, self )._list_packages_to_install( ) + [
            'git', 'python-dev','docker.io']

    def _get_iam_ec2_role( self ):
        role_name, policies = super( ToilBox, self )._get_iam_ec2_role( )
        role_name += '--' + abreviated_snake_case_class_name( ToilBox )
        policies.update( dict(
            ec2_full=ec2_full_policy,
            s3_full=s3_full_policy,
            sbd_full=sdb_full_policy,
            ec2_toil_box=dict( Version="2012-10-17", Statement=[
                dict( Effect="Allow", Resource="*", Action="ec2:CreateTags" ),
                dict( Effect="Allow", Resource="*", Action="ec2:CreateVolume" ),
                dict( Effect="Allow", Resource="*", Action="ec2:AttachVolume" ) ] ) ) )
        return role_name, policies

    @fabric_task
    def _docker_group(self, user=user):
        sudo("gpasswd -a {} docker".format(user))
        sudo("service docker.io restart")

    @fabric_task
    def _install_boto(self):
        # FIXME: boto will be automatically installed upon the completion of https://github.com/BD2KGenomics/toil/issues/207
        sudo("pip install boto") # downloading from git requires git tools.

    @fabric_task
    def _upgrade_pip(self):
        # old version of pip doesn't seem to recognize toil's 'extra' syntax
        sudo("pip install --upgrade pip")

    @fabric_task
    def __install_toil(self):
        sudo("pip install toil[aws,mesos]")

class ToilLeader(ToilBox, MesosMaster):
    def __init__( self, ctx):
        super( ToilLeader, self ).__init__( ctx)
        pass

    def _post_install_packages( self ):
        super( ToilLeader, self )._post_install_packages( )

    def clone( self, num_slaves, slave_instance_type, ebs_volume_size):
        """
        Create a number of slave boxes that are connected to this master.
        """
        master = self
        first_slave = ToilWorker( master.ctx, num_slaves, master.instance_id, ebs_volume_size)
        args = master.preparation_args
        kwargs = master.preparation_kwargs.copy( )
        kwargs[ 'instance_type' ] = slave_instance_type
        first_slave.prepare( *args, **kwargs )
        other_slaves = first_slave.create( wait_ready=False,
                                           cluster_ordinal=master.cluster_ordinal + 1 )
        all_slaves = [ first_slave ] + other_slaves
        return all_slaves

class ToilWorker(ToilBox, MesosSlave):
    def __init__( self, ctx, num_slaves=1, mesos_master_id=None, ebs_volume_size=0):
        super( ToilWorker, self ).__init__( ctx)
        self.num_slaves = num_slaves
        self.mesos_master_id = mesos_master_id
        self.ebs_volume_size = ebs_volume_size

def heredoc( s ):
    if s[ 0 ] == '\n': s = s[ 1: ]
    if s[ -1 ] != '\n': s += '\n'
    return fmt( dedent( s ), skip_frames=1 )