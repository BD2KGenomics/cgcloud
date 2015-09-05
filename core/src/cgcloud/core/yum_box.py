import os.path
from urlparse import urlparse

from fabric.operations import sudo, run

from cgcloud.core.init_box import SysvInitdBox
from cgcloud.core.box import fabric_task
from cgcloud.core.package_manager_box import PackageManagerBox


class YumBox( PackageManagerBox, SysvInitdBox ):
    """
    A box that uses redhat's yum package manager
    """

    def _sync_package_repos( self ):
        return False

    @fabric_task
    def _install_packages( self, packages ):
        """
        yum's error handling is a bit odd: If you pass two packages to install and one fails
        while the other succeeds, yum exits with 0. To work around this, we need to invoke rpm to
        check for successful installation separately of every package. Also, beware that some
        older yums exit with 0 even if the package doesn't exist:

        $ sudo yum install jasdgjhsadgajshd && echo yes
        $ yes

        :param packages: a list of package names
        """
        sudo( 'yum install -d 1 -y %s' % ' '.join( "'%s'" % package for package in packages ) )
        # make sure it is really installed
        for package in packages:
            run( 'rpm -q %s' % package )

    def _get_package_installation_command( self, package ):
        return [ 'yum', 'install', '-d', '1', '-y' ] + list( self._substitute_package( package ) )

    @fabric_task
    def _upgrade_installed_packages( self ):
        sudo( 'yum update -y -d 1' )

    @fabric_task
    def _yum_remove( self, package ):
        sudo( "yum -d 1 -y remove '%s'" % package )

    @fabric_task
    def _yum_local( self, is_update, rpm_urls ):
        """
        Download the RPM at the given URL and run 'yum localupdate' on it.

        :param rpm_urls: A list of HTTP or FTP URLs ending in a valid RPM file name.
        """
        rpms = [ ]
        for rpm_url in rpm_urls:
            run( "wget '%s'" % rpm_url )
            rpm = os.path.basename( urlparse( rpm_url ).path )
            rpms.append( rpm )

        sudo( "yum -d 1 -y local{command} {rpms} --nogpgcheck".format(
            command='update' if is_update else 'install',
            rpms=' '.join( "'%s'" % rpm for rpm in rpms ) ) )

        for rpm in rpms:
            # extract package name from RPM, then check if package is actually installed
            # since we can't rely on yum to report errors
            run( "rpm -q $(rpm -qp --queryformat '%%{N}' '%s')" % rpm )
            run( "rm '%s'" % rpm )

    def _get_package_substitutions( self ):
        return super( YumBox, self )._get_package_substitutions( ) + [
            ( 'python-dev', 'python-devel' ),
        ]

    def _ssh_service_name( self ):
        return 'sshd'

