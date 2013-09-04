import os.path
from urlparse import urlparse
from fabric.operations import sudo, run
from cghub.cloud.box import fabric_task
from cghub.cloud.package_manager_box import PackageManagerBox

__author__ = 'hannes'


class YumBox( PackageManagerBox ):
    """
    A box that uses redhat's yum package manager
    """

    def _sync_package_repos(self):
        return False

    @fabric_task
    def _install_packages(self, packages):
        """
        yum's error handling is a bit odd: If you pass two packages to install and one fails
        while the other succeeds, yum exits with 0. To work around this, we need to invoke yum
        separately for every package. It gets worse, some older yums exit with 0 even if the
        package doesn't exist:

        $ sudo yum install jasdgjhsadgajshd && echo yes
        $ yes

        :param packages: a list of package names
        """
        for package in packages:
            sudo( 'yum install -d 1 -y %s' % package )
            # make sure it is really installed
            run( 'rpm -q %s' % package )

    @fabric_task
    def _upgrade_installed_packages(self):
        sudo( 'yum update -y -d 1' )

    @fabric_task
    def _rpm_localupdate(self, *rpm_urls):
        """
        Download the RPM at the given URL and run 'yum localupdate' on it.

        :param rpm_url: An HTTP or FTP URL ending in a valid RPM file name.
        """
        quoted_rpms = ' '.join( "'%s'" % os.path.basename( urlparse( rpm_url ).path )
            for rpm_url in rpm_urls )
        for rpm_url in rpm_urls:
            run( "wget '%s'" % rpm_url )
        sudo( 'yum -d 1 -y localupdate %s --nogpgcheck' % quoted_rpms )
        run( 'rm %s' % quoted_rpms )