from fabric.operations import sudo
from cghub.cloud.core.box import fabric_task
from cghub.cloud.core.centos_box import CentosBox
from cghub.cloud.devenv.jenkins_slave import JenkinsSlave
from cghub.cloud.core.fedora_box import FedoraBox
from cghub.cloud.core.generic_boxes import GenericCentos5Box, GenericCentos6Box, GenericUbuntuLucidBox, GenericUbuntuPreciseBox, GenericUbuntuRaringBox, GenericUbuntuOneiricBox, GenericFedora19Box, GenericFedora18Box, GenericFedora17Box
from cghub.cloud.core.ubuntu_box import UbuntuBox


class GenetorrentJenkinsSlave( JenkinsSlave ):
    """
    A Jenkins slave for building GeneTorrent
    """

    def recommended_instance_type(self):
        """
        A micro instance does not have enough RAM to build Boost, so we need to go one up.
        """
        return "m1.small"


class CentosGenetorrentJenkinsSlave( CentosBox, GenetorrentJenkinsSlave ):
    """
    A Jenkins slave for building GeneTorrent on CentOS
    """

    def _list_packages_to_install(self):
        # TODO: List JRE explicitly (it is already installed on RightScale CentOS images)
        return super( CentosGenetorrentJenkinsSlave, self )._list_packages_to_install( ) + [
            'gcc-c++',
            'pkgconfig',
            'xerces-c-devel',
            'libcurl-devel',
            'xqilla-devel',
            'openssl-devel',
            'make',
            'rpm-build',
            'redhat-rpm-config' ]


class Centos5GenetorrentJenkinsSlave( CentosGenetorrentJenkinsSlave, GenericCentos5Box ):
    """
    A Jenkins slave for building GeneTorrent on CentOS 5
    """

    def recommended_instance_type(self):
        return 'm1.medium'


    def _get_package_substitutions(self):
        return super( Centos5GenetorrentJenkinsSlave, self )._get_package_substitutions( ) + [
            ( 'libcurl-devel', 'curl-devel' ) ]

    def _list_packages_to_install(self):
        return super( Centos5GenetorrentJenkinsSlave, self )._list_packages_to_install( ) + [
            # On CentOS 6 this is installed automatically but on 5 it is missing. It is needed
            # for the %{dist} tag in .spec files. Without it, the CentOS 5 RPM build fails in
            # obscure ways since the release-specific conditionals in the genetorrent.spec file
            # don't get executed.
            "buildsys-macros"
        ]

    @fabric_task
    def _post_install_packages(self):
        """
        CentOS 5's autoconf is too old for building genetorrent so we dug up this RPM to replace
        it, the m4 RPM is a dependency of the autoconf RPM.
        """
        super( Centos5GenetorrentJenkinsSlave, self )._post_install_packages( )
        self._yum_local( is_update=True, rpm_urls=[
            'ftp://ftp.pbone.net/mirror/ftp5.gwdg.de/pub/opensuse/repositories/home:/crt0solutions:/extras/CentOS_CentOS-5/x86_64/m4-1.4.11-1.8.crt0.x86_64.rpm',
            'ftp://ftp.pbone.net/mirror/ftp5.gwdg.de/pub/opensuse/repositories/home:/crt0solutions:/extras/CentOS_CentOS-5/noarch/autoconf-2.63-4.2.crt0.noarch.rpm',
            'ftp://ftp.pbone.net/mirror/ftp5.gwdg.de/pub/opensuse/repositories/home:/crt0solutions:/extras/CentOS_CentOS-5/noarch/automake-1.11.1-1.5.crt0.noarch.rpm',
            'http://dl.atrpms.net/el5-x86_64/atrpms/testing/libtool-2.2.6-15.5.el5.1.x86_64.rpm'
        ] )
        self._yum_local( is_update=False, rpm_urls=[
            'http://public-artifacts.cghub.ucsc.edu.s3.amazonaws.com/custom-centos-packages/python27-2.7.2-cghub.x86_64.rpm',
            'http://public-artifacts.cghub.ucsc.edu.s3.amazonaws.com/custom-centos-packages/python27-devel-2.7.2-cghub.x86_64.rpm',
            'http://public-artifacts.cghub.ucsc.edu.s3.amazonaws.com/custom-centos-packages/python27-setuptools-0.6c11-cghub.noarch.rpm'
        ] )
        # Make 2.7 the default
        sudo( 'ln -snf /usr/bin/python2.7 /usr/bin/python' )
        sudo( 'ln -snf /usr/bin/easy_install-2.7 /usr/bin/easy_install' )
        sudo( 'mv /usr/bin/pydoc /usr/bin/pydoc2.4' )


class Centos6GenetorrentJenkinsSlave( CentosGenetorrentJenkinsSlave, GenericCentos6Box ):
    """
    A Jenkins slave for building GeneTorrent on CentOS 6
    """
    pass


class UbuntuGenetorrentJenkinsSlave( UbuntuBox, GenetorrentJenkinsSlave ):
    """
    A Jenkins slave for building GeneTorrent on Ubuntu
    """

    def _list_packages_to_install(self):
        packages = super( UbuntuGenetorrentJenkinsSlave, self )._list_packages_to_install( )
        return packages + [
            'autoconf',
            'libtool',
            'g++',
            'pkg-config',
            'libxerces-c-dev',
            'libcurl4-openssl-dev',
            'libxqilla-dev',
            'libssl-dev',
            'make',
            'devscripts',
            'debhelper',
            'python-support',
            'openjdk-7-jre-headless' ]


class UbuntuLucidGenetorrentJenkinsSlave( UbuntuGenetorrentJenkinsSlave, GenericUbuntuLucidBox ):
    """
    A Jenkins slave for building GeneTorrent on Ubuntu 10.04 LTS (EOL April 2015)
    """

    def _get_package_substitutions(self):
        return super( UbuntuLucidGenetorrentJenkinsSlave, self )._get_package_substitutions( ) + [
            ('openjdk-7-jre-headless', 'openjdk-6-jre'),
            ('git', 'git-core') ]

    def _pre_install_packages(self):
        super( UbuntuLucidGenetorrentJenkinsSlave, self )._pre_install_packages( )
        # On Lucid, somehow postfix gets pulled in as a dependency kicking the frontend into
        # interactive mode.
        self._debconf_set_selection(
            "postfix postfix/main_mailer_type string 'No configuration'",
            "postfix postfix/mailname string %s" % self.host_name
        )


class UbuntuOneiricGenetorrentJenkinsSlave( UbuntuGenetorrentJenkinsSlave,
                                            GenericUbuntuOneiricBox ):
    """
    A Jenkins slave for building GeneTorrent on Ubuntu 11.10 (EOL May 2013)
    """
    pass


class UbuntuPreciseGenetorrentJenkinsSlave( UbuntuGenetorrentJenkinsSlave,
                                            GenericUbuntuPreciseBox ):
    """
    A Jenkins slave for building GeneTorrent on Ubuntu 12.04 LTS (EOL April 2017)
    """

    def _list_packages_to_install(self):
        return super( UbuntuPreciseGenetorrentJenkinsSlave, self )._list_packages_to_install( ) + [
            'libboost1.48-dev',
            'libboost-filesystem1.48-dev',
            'libboost-system1.48-dev',
            'libboost-program-options1.48-dev',
            'libboost-regex1.48-dev' ]


class UbuntuRaringGenetorrentJenkinsSlave( UbuntuGenetorrentJenkinsSlave, GenericUbuntuRaringBox ):
    """
    A Jenkins slave for building GeneTorrent on Ubuntu 13.04 (EOL January 2014)
    """

    def _list_packages_to_install(self):
        return super( UbuntuRaringGenetorrentJenkinsSlave, self )._list_packages_to_install( ) + [
            'libboost1.49-dev',
            'libboost-filesystem1.49-dev',
            'libboost-system1.49-dev',
            'libboost-program-options1.49-dev',
            'libboost-regex1.49-dev',
        ]


class FedoraGenetorrentJenkinsSlave( FedoraBox, GenetorrentJenkinsSlave ):
    """
    A Jenkins slave for building GeneTorrent on Fedora
    """

    def _list_packages_to_install(self):
        packages = super( FedoraGenetorrentJenkinsSlave, self )._list_packages_to_install( )
        return packages + [
            'autoconf',
            'libtool',
            'gcc-c++',
            'pkgconfig',
            'xerces-c-devel',
            'libcurl-devel',
            'xqilla-devel',
            'openssl-devel',
            'openssl',
            'boost-devel',
            'make',
            'rpm-build',
            'redhat-rpm-config',
            'java-1.7.0-openjdk' ]


    @fabric_task
    def _get_rc_local_path(self):
        rc_local_path = '/etc/rc.d/rc.local'
        sudo( 'test -f {f} || echo "#!/bin/sh" > {f} && chmod +x {f}'.format( f=rc_local_path ) )
        return rc_local_path


class Fedora19GenetorrentJenkinsSlave( FedoraGenetorrentJenkinsSlave, GenericFedora19Box ):
    """
    A Jenkins slave for building GeneTorrent on Fedora 19
    """
    pass


class Fedora18GenetorrentJenkinsSlave( FedoraGenetorrentJenkinsSlave, GenericFedora18Box ):
    """
    A Jenkins slave for building GeneTorrent on Fedora 18
    """
    pass


class Fedora17GenetorrentJenkinsSlave( FedoraGenetorrentJenkinsSlave, GenericFedora17Box ):
    """
    A Jenkins slave for building GeneTorrent on Fedora 17
    """

    def _list_packages_to_install(self):
        return super( Fedora17GenetorrentJenkinsSlave, self )._list_packages_to_install( ) + [
            # This isn't pre-installed on Fedora 17 and without it, autoreconf says things like
            # "libtoolize: can not copy `/usr/share/aclocal/libtool.m4' to `m4/'" since
            # apparently it's using tar to copy files but doesn't deem the user worthy being
            # informed about the absence of a vital prerequisite.
            #
            # http://lists.gnu.org/archive/html/libtool/2009-07/msg00030.html
            #
            # Of course, tar is need for other build steps too, so we would have found out anyhow.
            "tar"
        ]
