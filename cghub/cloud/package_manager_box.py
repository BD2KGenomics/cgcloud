from cghub.cloud.box import Box


class PackageManagerBox( Box ):
    """
    A box that uses a package manager like apt-get or yum.
    """

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

    def _populate_package_substitutions(self, substitutions):
        """
        Populate the package substitution dictionary with entries. An entry's key is the name of
        a package to be installed, the corresponding value is the name of the substitute package
        that will be installed instead. The dictionary may contain cycles, None keys and None
        value.  Note that substitutes are subjected to substitution, too. An entry with a None
        value will cause the package referred to by the entry's key to be ignored. An entry with
        a None key will cause any ignored packages to be substituted with the package referred to
        by the entry's value, a less common scenario.
        """
        pass

    def setup(self, upgrade_installed_packages=False):
        self._setup_package_repos( )
        self._sync_package_repos( )
        self._pre_install_packages( )
        substitutions = { }
        self._populate_package_substitutions( substitutions )
        packages = self._list_packages_to_install( )
        packages = ( substitute_package( substitutions, p ) for p in packages )
        packages = [ p for p in packages if p is not None ]
        self._install_packages( packages )
        self._post_install_packages( )
        if upgrade_installed_packages:
            self._upgrade_installed_packages( )
            # The upgrade might involve a kernel update, so we'll reboot to be safe
            self.reboot( )


def substitute_package(substitutions, package):
    """
    Apply the given substitutions map on the package argument. Handles cycles as well as None
    keys and values.

    >>> substitute_package( {}, None ) is None
    True
    >>> substitute_package( { None: 'a' }, None )
    'a'
    >>> substitute_package( { 'a': 'a' }, 'a' )
    'a'
    >>> substitute_package( { 'a': None }, 'a' ) is None
    True
    >>> substitute_package( { 'a': 'b' }, 'b' )
    'b'
    >>> substitute_package( { 'a': 'b' }, 'a' )
    'b'
    >>> substitute_package( { 'a': None, None:'c', 'c':'a' }, 'a' )
    'c'
    >>> substitute_package( { 'a': None, None:'c', 'c':'a' }, None )
    'a'
    >>> substitute_package( { 'a': None, None:'c', 'c':'a' }, 'c' ) is None
    True
    """
    history = set( )
    while True:
        history.add( package )
        try:
            substitution = substitutions[ package ]
        except KeyError:
            return package
        if substitution in history: return package
        package = substitution
    return package

