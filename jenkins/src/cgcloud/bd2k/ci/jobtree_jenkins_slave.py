from fabric.operations import run

from cgcloud.bd2k.ci import UbuntuTrustyGenericJenkinsSlave
from cgcloud.core import fabric_task
from cgcloud.core.common_iam_policies import s3_full_policy, sdb_full_policy
from cgcloud.fabric.operations import sudo
from cgcloud.lib.util import abreviated_snake_case_class_name


class JobtreeJenkinsSlave( UbuntuTrustyGenericJenkinsSlave ):
    """
    A Jenkins slave suitable for running jobTree unit tests, specifically the Mesos batch system
    and the AWS job store. Legacy batch systems (parasol, gridengine, ...) are not yet supported.
    """

    @classmethod
    def recommended_instance_type( cls ):
        return "m3.large"

    @fabric_task
    def _setup_package_repos( self ):
        super( JobtreeJenkinsSlave, self )._setup_package_repos( )
        sudo( "apt-key adv --keyserver keyserver.ubuntu.com --recv E56151BF" )
        distro = run( "lsb_release -is | tr '[:upper:]' '[:lower:]'" )
        codename = run( "lsb_release -cs" )
        run( 'echo "deb http://repos.mesosphere.io/{} {} main"'
             '| sudo tee /etc/apt/sources.list.d/mesosphere.list'.format( distro, codename ) )

    def _list_packages_to_install( self ):
        return super( JobtreeJenkinsSlave, self )._list_packages_to_install( ) + [
            'mesos',
            'python-dev'
        ]

    def _post_install_packages( self ):
        super( JobtreeJenkinsSlave, self )._post_install_packages( )
        self.__disable_mesos_daemons( )
        self.__install_mesos_egg( )

    @fabric_task
    def __disable_mesos_daemons( self ):
        for daemon in ('master', 'slave'):
            sudo( 'echo manual > /etc/init/mesos-%s.override' % daemon )

    @fabric_task
    def __install_mesos_egg( self ):
        # FIXME: this is the ubuntu 14.04 version. Wont work with other versions.
        run(
            "wget http://downloads.mesosphere.io/master/ubuntu/14.04/mesos-0.22.0-py2.7-linux-x86_64.egg" )
        # we need a newer version of protobuf than comes default on ubuntu
        sudo( "pip install --upgrade protobuf" )
        sudo( "easy_install mesos-0.22.0-py2.7-linux-x86_64.egg" )

    def _get_iam_ec2_role( self ):
        role_name, policies = super( JobtreeJenkinsSlave, self )._get_iam_ec2_role( )
        role_name += '--' + abreviated_snake_case_class_name( JobtreeJenkinsSlave )
        policies.update( dict( s3_full=s3_full_policy, sdb_full=sdb_full_policy ) )
        return role_name, policies
