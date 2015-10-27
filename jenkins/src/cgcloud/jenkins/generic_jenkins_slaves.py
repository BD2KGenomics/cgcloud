from cgcloud.core.generic_boxes import *
from cgcloud.fabric.operations import sudo

from cgcloud.jenkins.jenkins_slave import JenkinsSlave
from cgcloud.core.ubuntu_box import UbuntuBox


class GenericJenkinsSlave( JenkinsSlave ):
    """
    A generic Jenkins slave
    """
    pass


class CentosGenericJenkinsSlave( CentosBox, GenericJenkinsSlave ):
    """
    A generic Jenkins slave for CentOS
    """

    def _list_packages_to_install( self ):
        # TODO: List JRE explicitly (it is already installed on RightScale CentOS images)
        return super( CentosGenericJenkinsSlave, self )._list_packages_to_install( ) + [ ]

    @fabric_task
    def _setup_build_user( self ):
        super( CentosGenericJenkinsSlave, self )._setup_build_user( )
        sudo( "echo 'Defaults:jenkins !requiretty' >> /etc/sudoers" )
        sudo( "echo 'jenkins ALL=(ALL) NOPASSWD: /bin/rpm' >> /etc/sudoers" )
        sudo( "echo 'jenkins ALL=(ALL) NOPASSWD: /usr/bin/yum' >> /etc/sudoers" )

    @fabric_task
    def _post_install_packages( self ):
        super( CentosGenericJenkinsSlave, self )._post_install_packages( )
        # FIXME: These are public but we should rebuild them and host them within our control
        self._yum_local( is_update=False, rpm_urls=[
            'http://public-artifacts.cghub.ucsc.edu.s3.amazonaws.com/custom-centos-packages/python27-2.7.2-cghub.x86_64.rpm',
            'http://public-artifacts.cghub.ucsc.edu.s3.amazonaws.com/custom-centos-packages/python27-devel-2.7.2-cghub.x86_64.rpm',
            'http://public-artifacts.cghub.ucsc.edu.s3.amazonaws.com/custom-centos-packages/python27-setuptools-0.6c11-cghub.noarch.rpm'
        ] )


class Centos5GenericJenkinsSlave( CentosGenericJenkinsSlave, GenericCentos5Box ):
    """
    A generic Jenkins slave for CentOS 5
    """
    pass


class Centos6GenericJenkinsSlave( CentosGenericJenkinsSlave, GenericCentos6Box ):
    """
    A generic Jenkins slave for CentOS 6
    """
    pass


class UbuntuGenericJenkinsSlave( UbuntuBox, GenericJenkinsSlave ):
    """
    A generic Jenkins slave for Ubuntu
    """

    def _list_packages_to_install( self ):
        return super( UbuntuGenericJenkinsSlave, self )._list_packages_to_install( ) + [
            'openjdk-7-jre-headless',
            'gdebi-core' ]  # comes in handy when installing .deb's with dependencies

    @fabric_task
    def _setup_build_user( self ):
        super( UbuntuGenericJenkinsSlave, self )._setup_build_user( )
        sudo( "echo 'Defaults:jenkins !requiretty' >> /etc/sudoers" )
        for prog in ('apt-get', 'dpkg', 'gdebi'):
            sudo( "echo 'jenkins ALL=(ALL) NOPASSWD: /usr/bin/%s' >> /etc/sudoers" % prog )

    def _get_debconf_selections( self ):
        # On Lucid, somehow postfix gets pulled in as a dependency kicking the frontend into
        # interactive mode. The same happens when installing GridEngine.
        return super( UbuntuGenericJenkinsSlave, self )._get_debconf_selections( ) + [
            "postfix postfix/main_mailer_type string 'No configuration'",
            "postfix postfix/mailname string %s" % self.host_name
        ]


class UbuntuLucidGenericJenkinsSlave( UbuntuGenericJenkinsSlave, GenericUbuntuLucidBox ):
    """
    A generic Jenkins slave for Ubuntu 10.04 LTS (EOL April 2015)
    """

    def _setup_package_repos( self ):
        super( UbuntuLucidGenericJenkinsSlave, self )._setup_package_repos( )
        self.__add_git_ppa( )
        self.__add_python_ppa( )

    @fabric_task
    def __add_git_ppa( self ):
        sudo( 'add-apt-repository -y ppa:git-core/ppa' )

    @fabric_task
    def __add_python_ppa( self ):
        sudo( 'apt-add-repository -y ppa:fkrull/deadsnakes/ubuntu' )

    def _list_packages_to_install( self ):
        return super( UbuntuLucidGenericJenkinsSlave, self )._list_packages_to_install( ) + [
            'python2.7',
            'python2.7-dev'
        ]

    def _get_package_substitutions( self ):
        return super( UbuntuLucidGenericJenkinsSlave, self )._get_package_substitutions( ) + [
            ('openjdk-7-jre-headless', 'openjdk-6-jre') ]


class UbuntuPreciseGenericJenkinsSlave( UbuntuGenericJenkinsSlave, GenericUbuntuPreciseBox ):
    """
    A generic Jenkins slave for Ubuntu 12.04 LTS (EOL April 2017)
    """
    pass


class UbuntuTrustyGenericJenkinsSlave( UbuntuGenericJenkinsSlave, GenericUbuntuTrustyBox ):
    """
    A generic Jenkins slave for Ubuntu 14.04 LTS (EOL April 2019)
    """
    pass


class FedoraGenericJenkinsSlave( FedoraBox, GenericJenkinsSlave ):
    """
    A generic Jenkins slave for Fedora
    """

    def _list_packages_to_install( self ):
        return super( FedoraGenericJenkinsSlave, self )._list_packages_to_install( ) + [
            'java-1.7.0-openjdk' ]

    @fabric_task
    def _setup_build_user( self ):
        super( FedoraGenericJenkinsSlave, self )._setup_build_user( )
        sudo( "echo 'Defaults:jenkins !requiretty' >> /etc/sudoers" )
        sudo( "echo 'jenkins ALL=(ALL) NOPASSWD: /bin/rpm' >> /etc/sudoers" )
        sudo( "echo 'jenkins ALL=(ALL) NOPASSWD: /usr/bin/yum' >> /etc/sudoers" )


class Fedora19GenericJenkinsSlave( FedoraGenericJenkinsSlave, GenericFedora19Box ):
    """
    A generic Jenkins slave for Fedora 19
    """
    pass


class Fedora20GenericJenkinsSlave( FedoraGenericJenkinsSlave, GenericFedora20Box ):
    """
    A generic Jenkins slave for Fedora 20
    """
    pass
