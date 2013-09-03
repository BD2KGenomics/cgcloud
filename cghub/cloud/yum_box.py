from fabric.operations import sudo
from cghub.cloud.box import fabric_task
from cghub.cloud.package_manager_box import PackageManagerBox

__author__ = 'hannes'


class YumBox(PackageManagerBox):
    """
    A box that uses redhat's yum package manager
    """
    def _sync_package_repos(self):
        return False

    @fabric_task
    def _install_packages(self, packages):
        # yum's error handling is a bit odd: If you pass two packages to install and one fails while
        # the other succeeds, yum exits with 0. To work around this, we need to invoke yum separately
        # for every package.
        for package in packages:
            sudo( 'yum install -d 1 -y %s' % package )

    @fabric_task
    def _upgrade_installed_packages(self):
        sudo( 'yum update -y -d 1' )