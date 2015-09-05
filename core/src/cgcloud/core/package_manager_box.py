from abc import abstractmethod
from itertools import chain

from cgcloud.core.box import Box


class PackageManagerBox( Box ):
    """
    A box that uses a package manager like apt-get or yum.
    """

    @abstractmethod
    def _sync_package_repos( self ):
        """
        Update the cached package descriptions from remote package repositories,
        e.g. apt-get update on Ubuntu
        """
        raise NotImplementedError( )

    @abstractmethod
    def _upgrade_installed_packages( self ):
        """
        Update all installed package to their lates version, e.g. apt-get update on Ubuntu.
        """
        raise NotImplementedError( )

    @abstractmethod
    def _install_packages( self, packages ):
        """
        Install the given packages

        :param packages: A list of package names
        """
        raise NotImplementedError( )

    def _setup_package_repos( self ):
        """
        Set up additional remote package repositories.
        """
        pass

    def _list_packages_to_install( self ):
        """
        Return the list of packages to be installed.
        """
        return [ 'htop' ]

    def _pre_install_packages( self ):
        """
        Invoked immediately before package installation.
        """
        pass

    def _post_install_packages( self ):
        """
        Invoked immediately after package installation.
        """
        pass

    def _get_package_substitutions( self ):
        """
        Return a list of package substitutions. Each substitution is a tuple of two elements. The
        first element, aka the original, is the name of a package to be installed, the second
        element, aka the substitutes, is an iterable of names of the packages that should be used
        instead. An empty iterable will prevent the original from being installed. If the second
        element is an instance of basestring, it will be treated like a singleton of that string.
        If the second ekement is None, it will be treated like an empty iterable. Substitutes are
        subjected to substitution, too. The dictionary may contain cycles.

        The returned list will be passed to the dict() constructor. If it contains more than one
        tuple with the same first element, only the last entry will be significant. For example,
        [ ('a','b'), ('a','c') ] is equivalent to [ ('a','c') ].
        """
        return [ ]

    def setup( self, upgrade_installed_packages=False ):
        """
        :param upgrade_installed_packages:
            Bring the package repository as well as any installed packages up to date, i.e. do
            what on Ubuntu is achieved by doing 'sudo apt-get update ; sudo apt-get upgrade'.
        """
        self._setup_package_repos( )
        self._sync_package_repos( )
        self._pre_install_packages( )
        substitutions = dict( self._get_package_substitutions( ) )
        packages = self._list_packages_to_install( )
        packages = list( self.__substitute_packages( substitutions, packages ) )
        self._install_packages( packages )
        self._post_install_packages( )
        if upgrade_installed_packages:
            self._upgrade_installed_packages( )
            # The upgrade might involve a kernel update, so we'll reboot to be safe
            self.reboot( )

    @abstractmethod
    def _ssh_service_name( self ):
        raise NotImplementedError( )

    def _substitute_package( self, package ):
        """
        Return the set of packages that substitute the given package on this box.
        """
        substitutions = dict( self._get_package_substitutions( ) )
        return self.__substitute_packages( substitutions, [ package ] )

    @classmethod
    def __substitute_package( cls, substitutions, package, history=None ):
        """
        Apply the given substitutions map on the package argument. Handles cycles as well as None
        keys and values.

        >>> substitute_package = PackageManagerBox._PackageManagerBox__substitute_package
        >>> substitute_package( {}, 'a' )
        set(['a'])
        >>> substitute_package( { 'a': 'a' }, 'a' )
        set(['a'])
        >>> substitute_package( { 'a': None }, 'a' )
        set([])
        >>> substitute_package( { 'a': [] }, 'a' )
        set([])
        >>> substitute_package( { 'a': 'b' }, 'a' )
        set(['b'])
        >>> substitute_package( { 'a': ['b'] }, 'a' )
        set(['b'])
        >>> substitute_package( { 'a': 'b' }, 'b' )
        set(['b'])
        >>> substitute_package( { 'a': ['b'] }, 'b' )
        set(['b'])
        >>> substitute_package( { 'a': 'b' }, 'a' )
        set(['b'])
        >>> substitute_package( { 'a': 'b', 'b':'c', 'c':'a' }, 'a' )
        set(['a'])
        >>> substitute_package( { 'a':['a','b'], 'b':['b','c'], 'c':['c','a'] }, 'a' ) == {'a','b','c'}
        True
        >>> substitute_package( { 'a':['a','b'], 'b':None }, 'a' )
        set(['a'])
        >>> substitute_package( { 'a':['a','b'], 'b':[] }, 'a' )
        set(['a'])
        >>> substitute_package( { 'a':['a','b'], 'b':'c' }, 'a' ) ==  {'a', 'c'}
        True
        """
        if not isinstance( package, basestring ):
            raise ValueError( "Package must be a string" )
        if history is None:
            history = { package }
        else:
            if package in history: return { package }
            history.add( package )
        try:
            substitutes = substitutions[ package ]
        except KeyError:
            return { package }
        if substitutes is None: return set( )
        elif isinstance( substitutes, basestring ):
            substitute = substitutes
            return cls.__substitute_package( substitutions, substitute, history )
        else:
            return cls.__substitute_packages( substitutions, substitutes, history )

    @classmethod
    def __substitute_packages( cls, substitutions, substitutes, history=None ):
        return set( chain.from_iterable(
            cls.__substitute_package( substitutions, substitute, history )
                for substitute in substitutes ) )


