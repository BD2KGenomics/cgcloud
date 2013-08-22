from cghub.cloud.box import Box


class UnixBox( Box ):
    def _sync_package_repos(self):
        """
        Update the cached package descriptions from remote package repositories,
        e.g. apt-get update on Ubuntu
        """
        raise NotImplementedError( )

    def _upgrade_installed_packages(self):
        """
        Update all installed package to their lates version, e.g. apt-get update on Ubuntu.
        """
        raise NotImplementedError( )

    def _install_packages(self, packages):
        """
        Install the given packages

        :param packages: A list of package names
        """
        raise NotImplementedError( )

    def _setup_package_repos(self):
        """
        Set up additional remote package repositories.
        """
        pass

    def _list_packages_to_install(self):
        """
        Return the list of packages to be installed.
        """
        return [ 'htop' ]

    def _pre_install_packages(self):
        """
        Invoked immediately before package installation.
        """
        pass

    def _post_install_packages(self):
        """
        Invoked immediately after package installation.
        """
        pass

    def setup(self, upgrade_installed_packages=False):
        self._sync_package_repos( )
        self._pre_install_packages( )
        packages = self._list_packages_to_install( )
        self._install_packages( packages )
        self._post_install_packages( )
        if upgrade_installed_packages:
            self._upgrade_installed_packages( )
            # The upgrade might involve a kernel update, so we'll reboot to be safe
            self.reboot( )

