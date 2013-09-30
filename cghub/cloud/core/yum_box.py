import os.path
from urlparse import urlparse
from fabric.operations import sudo, run
from cghub.cloud.core.box import fabric_task
from cghub.cloud.core.package_manager_box import PackageManagerBox

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
    def _yum_local(self, is_update, rpm_urls ):
        """
        Download the RPM at the given URL and run 'yum localupdate' on it.

        :param rpm_urls: A list of HTTP or FTP URLs ending in a valid RPM file name.
        """
        for rpm_url in rpm_urls:
            run( "wget '%s'" % rpm_url )
            rpm = os.path.basename( urlparse( rpm_url ).path )
            sudo( "yum -d 1 -y %s '%s' --nogpgcheck"
                  % ( 'localupdate' if is_update else 'localinstall', rpm ) )
            # extract package name from RPM, then check if package is actually installed
            # since we can't rely on yum to report errors
            run( "rpm -q $(rpm -qp --queryformat '%%{N}' '%s')" % rpm )
            run( "rm '%s'" % rpm )
