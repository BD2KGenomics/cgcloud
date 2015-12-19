import logging

from bd2k.util.iterables import concat

from cgcloud.core.box import fabric_task
from cgcloud.core.cluster import ClusterBox, ClusterWorker, ClusterLeader
from cgcloud.core.common_iam_policies import ec2_full_policy, s3_full_policy, sdb_full_policy
from cgcloud.core.docker_box import DockerBox
from cgcloud.fabric.operations import pip, remote_sudo_popen
from cgcloud.lib.util import abreviated_snake_case_class_name, heredoc
from cgcloud.mesos.mesos_box import MesosBoxSupport, user, persistent_dir

log = logging.getLogger( __name__ )


class ToilBox( MesosBoxSupport, DockerBox, ClusterBox ):
    """
    A box with Mesos, Toil and their dependencies installed.
    """

    def _list_packages_to_install( self ):
        return super( ToilBox, self )._list_packages_to_install( ) + [
            'python-dev', 'gcc', 'make',
            'libcurl4-openssl-dev',  # Only for S3AM
            'libffi-dev' ]  # pynacl -> toil, Azure client-side encryption

    def _post_install_mesos( self ):
        super( ToilBox, self )._post_install_mesos( )
        # Override this method instead of _post_install_packages() such that this is run before
        self.__install_toil( )

    def _docker_users( self ):
        return super( ToilBox, self )._docker_users( ) + [ user ]

    def _docker_data_prefixes( self ):
        # We prefer Docker to be stored on the persistent volume if there is one
        return concat( persistent_dir, super( ToilBox, self )._docker_data_prefixes( ) )

    @fabric_task
    def _setup_docker( self ):
        super( ToilBox, self )._setup_docker( )
        # The docker and dockerbox init jobs depend on /mnt/persistent which is set up by the
        # mesosbox job. Adding a dependency of the docker job on mesosbox should satsify that
        # dependency.
        with remote_sudo_popen( 'patch -d /etc/init' ) as patch:
            patch.write( heredoc( """
                --- docker.conf.orig	2015-12-18 23:28:48.693072560 +0000
                +++ docker.conf	2015-12-18 23:40:30.553072560 +0000
                @@ -1,6 +1,6 @@
                 description "Docker daemon"

                -start on (local-filesystems and net-device-up IFACE!=lo)
                +start on (local-filesystems and net-device-up IFACE!=lo and started mesosbox)
                 stop on runlevel [!2345]
                 limit nofile 524288 1048576
                 limit nproc 524288 1048576""" ) )

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
    def __install_toil( self ):
        # Older versions of pip don't support the 'extra' mechanism used by Toil's setup.py
        pip( 'install --upgrade pip', use_sudo=True )
        pip( 'install --pre s3am', use_sudo=True )
        pip( concat( 'install', self._toil_pip_args( ) ), use_sudo=True )
        self._lazy_mkdir( '/var/lib', 'toil', persistent=True )

    def _toil_pip_args( self ):
        return [ 'toil[aws,mesos,encryption]==3.1.1' ]


class ToilLatestBox( ToilBox ):
    def _toil_pip_args( self ):
        return [ '--pre', 'toil[aws,mesos,encryption]<=3.2.0' ]


class ToilLeader( ToilBox, ClusterLeader ):
    pass


class ToilWorker( ToilBox, ClusterWorker ):
    pass
