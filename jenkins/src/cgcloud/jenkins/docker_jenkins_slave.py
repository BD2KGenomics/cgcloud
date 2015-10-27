from cgcloud.core.ubuntu_box import Python27UpdateUbuntuBox
from cgcloud.jenkins.generic_jenkins_slaves import UbuntuTrustyGenericJenkinsSlave
from cgcloud.core.docker_box import DockerBox


class DockerJenkinsSlave( UbuntuTrustyGenericJenkinsSlave, DockerBox, Python27UpdateUbuntuBox ):
    """
    A box for running the cgl-docker-lib builds on. Probably a bit of a misnomer but so far the
    only cgl-docker-lib particular is the dependency on make.
    """

    def _list_packages_to_install( self ):
        return super( DockerJenkinsSlave, self )._list_packages_to_install( ) + [ 'make' ]

    def _docker_users( self ):
        return super( DockerJenkinsSlave, self )._docker_users( ) + [ 'jenkins' ]

    @classmethod
    def recommended_instance_type( cls ):
        return 'm3.large'
