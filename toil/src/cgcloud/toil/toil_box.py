import logging

from cgcloud.core.box import fabric_task
from cgcloud.core.docker_box import DockerBox
from cgcloud.mesos.mesos_box import MesosBoxSupport, MesosMaster, MesosSlave, user
from cgcloud.fabric.operations import pip
from cgcloud.lib.util import abreviated_snake_case_class_name
from cgcloud.core.common_iam_policies import ec2_full_policy, s3_full_policy, sdb_full_policy

log = logging.getLogger( __name__ )


class ToilBox( MesosBoxSupport, DockerBox ):
    def __init__( self, ctx ):
        super( ToilBox, self ).__init__( ctx )
        self.lazy_dirs = set( )

    def _post_install_packages( self ):
        super( ToilBox, self )._post_install_packages( )
        self.__upgrade_pip( )
        self.__install_toil( )
        self.__install_s3am( )

    def _list_packages_to_install( self ):
        return super( ToilBox, self )._list_packages_to_install( ) + [
            'python-dev', 'gcc', 'make',
            'libcurl4-openssl-dev' ]  # Only for S3AM

    def _docker_users( self ):
        return super( ToilBox, self )._docker_users( ) + [ user ]

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

    def _setup_mesos( self ):
        super( ToilBox, self )._setup_mesos( )
        self._lazy_mkdir( '/var/lib', 'toil', persistent=True )

    @fabric_task
    def __install_s3am( self ):
        pip( 'install --pre s3am', use_sudo=True )

    @fabric_task
    def __upgrade_pip( self ):
        # Older versions of pip don't support the 'extra' mechanism used by Toil's setup.py
        pip( 'install --upgrade pip', use_sudo=True )

    @fabric_task
    def __install_toil( self ):
        pip( 'install toil[aws,mesos]', use_sudo=True )


class ToilLeader( ToilBox, MesosMaster ):
    def __init__( self, ctx ):
        super( ToilLeader, self ).__init__( ctx )
        pass

    def _post_install_packages( self ):
        super( ToilLeader, self )._post_install_packages( )

    def clone( self, num_slaves, slave_instance_type, ebs_volume_size ):
        """
        Create a number of slave boxes that are connected to this master.
        """
        master = self
        first_slave = ToilWorker( master.ctx, num_slaves, master.instance_id, ebs_volume_size )
        args = master.preparation_args
        kwargs = master.preparation_kwargs.copy( )
        kwargs[ 'instance_type' ] = slave_instance_type
        first_slave.prepare( *args, **kwargs )
        other_slaves = first_slave.create( wait_ready=False,
                                           cluster_ordinal=master.cluster_ordinal + 1 )
        all_slaves = [ first_slave ] + other_slaves
        return all_slaves


class ToilWorker( ToilBox, MesosSlave ):
    def __init__( self, ctx, num_slaves=1, mesos_master_id=None, ebs_volume_size=0 ):
        super( ToilWorker, self ).__init__( ctx )
        self.num_slaves = num_slaves
        self.mesos_master_id = mesos_master_id
        self.ebs_volume_size = ebs_volume_size
