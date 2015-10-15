def roles( ):
    from cgcloud.jenkins.jenkins_master import JenkinsMaster
    from cgcloud.jenkins.generic_jenkins_slaves import (UbuntuLucidGenericJenkinsSlave,
                                                        Centos5GenericJenkinsSlave,
                                                        Centos6GenericJenkinsSlave,
                                                        Fedora19GenericJenkinsSlave,
                                                        Fedora20GenericJenkinsSlave,
                                                        UbuntuPreciseGenericJenkinsSlave,
                                                        UbuntuTrustyGenericJenkinsSlave)
    from cgcloud.jenkins.cgcloud_jenkins_slave import CgcloudJenkinsSlave
    from cgcloud.jenkins.rpmbuild_jenkins_slaves import (Centos5RpmbuildJenkinsSlave,
                                                         Centos6RpmbuildJenkinsSlave)
    from cgcloud.jenkins.s3am_jenkins_slave import S3amJenkinsSlave
    from cgcloud.jenkins.toil_jenkins_slave import ToilJenkinsSlave
    from cgcloud.jenkins.docker_jenkins_slave import DockerJenkinsSlave
    return sorted( locals( ).values( ), key=lambda cls: cls.__name__ )


def command_classes( ):
    from cgcloud.jenkins.commands import RegisterSlaves
    return sorted( locals( ).values( ), key=lambda cls: cls.__name__ )
