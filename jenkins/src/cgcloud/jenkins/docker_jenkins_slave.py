from cgcloud.jenkins.generic_jenkins_slaves import UbuntuTrustyGenericJenkinsSlave
from cgcloud.core.docker_box import DockerBox


class DockerJenkinsSlave(UbuntuTrustyGenericJenkinsSlave, DockerBox):

    def _list_packages_to_install(self):
        # packages to apt-get
        return super(DockerJenkinsSlave, self)._list_packages_to_install() + ['make']

    def _docker_users(self):
        return super(DockerJenkinsSlave, self)._docker_users() + ['jenkins']

    @classmethod
    def recommended_instance_type(cls):
        return 'm3.large'
