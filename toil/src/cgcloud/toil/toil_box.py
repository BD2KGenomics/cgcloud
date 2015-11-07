from abc import abstractmethod
import logging
import os
from bd2k.util.iterables import concat

from cgcloud.core.box import fabric_task
from cgcloud.core.cluster import ClusterBox, ClusterWorker, ClusterLeader
from cgcloud.core.docker_box import DockerBox
from cgcloud.mesos.mesos_box import MesosBoxSupport, user
from cgcloud.fabric.operations import pip
from cgcloud.lib.util import abreviated_snake_case_class_name
from cgcloud.core.common_iam_policies import ec2_full_policy, s3_full_policy, sdb_full_policy

log = logging.getLogger( __name__ )


class ToilBox( MesosBoxSupport, DockerBox, ClusterBox ):
    """
    A box with Mesos, Toil and their dependencies installed.
    """

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

    @fabric_task
    def __install_s3am( self ):
        pip( 'install --pre s3am', use_sudo=True )

    @fabric_task
    def __upgrade_pip( self ):
        # Older versions of pip don't support the 'extra' mechanism used by Toil's setup.py
        pip( 'install --upgrade pip', use_sudo=True )

    @fabric_task
    def __install_toil( self ):
        pip( concat( 'install', self._toil_pip_args( ) ), use_sudo=True )
        self._lazy_mkdir( '/var/lib', 'toil', persistent=True )

    def _toil_pip_args( self ):
        return [ 'toil[aws,mesos]==3.0.6' ]


class ToilLatestBox( ToilBox ):
    def _list_packages_to_install( self ):
        return super( ToilLatestBox, self )._list_packages_to_install( ) + [
            'libffi-dev' ]  # pynacl -> toil, Azure client-side encryption

    def _toil_pip_args( self ):
        return [ '--pre', 'toil[aws,mesos,encryption]<=3.1.0' ]


class ToilLeader( ToilBox, ClusterLeader ):
    pass


class ToilWorker( ToilBox, ClusterWorker ):
    pass
