def roles( ):
    from cgcloud.bd2k.ci.jenkins_master import JenkinsMaster
    from cgcloud.bd2k.ci.generic_jenkins_slaves import (UbuntuLucidGenericJenkinsSlave,
                                                        Centos5GenericJenkinsSlave,
                                                        Centos6GenericJenkinsSlave,
                                                        Fedora19GenericJenkinsSlave,
                                                        Fedora20GenericJenkinsSlave,
                                                        UbuntuPreciseGenericJenkinsSlave,
                                                        UbuntuTrustyGenericJenkinsSlave)
    from cgcloud.bd2k.ci.cgcloud_jenkins_slave import CgcloudJenkinsSlave
    from cgcloud.bd2k.ci.rpmbuild_jenkins_slaves import (Centos5RpmbuildJenkinsSlave,
                                                         Centos6RpmbuildJenkinsSlave)
    from cgcloud.bd2k.ci.s3am_jenkins_slave import S3amJenkinsSlave
    from cgcloud.bd2k.ci.toil_jenkins_slave import ToilJenkinsSlave
    from cgcloud.bd2k.ci.docker_jenkins_slave import DockerJenkinsSlave
    return sorted( locals( ).values( ), key=lambda cls: cls.__name__ )


def command_classes( ):
    from cgcloud.bd2k.ci.commands import RegisterSlaves
    return sorted( locals( ).values( ), key=lambda cls: cls.__name__ )
