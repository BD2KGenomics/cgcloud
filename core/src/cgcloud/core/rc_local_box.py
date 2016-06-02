from collections import namedtuple
from contextlib import closing
from StringIO import StringIO

import re
from fabric.operations import get, put, sudo

from cgcloud.lib.util import prepend_shell_script
from cgcloud.core.box import fabric_task, Box

InitCommand = namedtuple( "InitCommand", [ "command", "provides", "depends" ] )


class RcLocalBox( Box ):
    """
    A mixin for implementing Box._register_init_command(), i.e. the ability to run an arbitrary
    command everytime a box is booted, using the rc.local mechanism that most distributions
    provide.
    """

    def __init__( self, ctx ):
        super( RcLocalBox, self ).__init__( ctx )
        self._init_commands = [ ]

    @fabric_task
    def _register_init_command( self, cmd ):
        rc_local_path = self._get_rc_local_path( )
        self._prepend_remote_shell_script( script=cmd,
                                           remote_path=rc_local_path,
                                           use_sudo=True,
                                           mirror_local_mode=True )
        sudo( 'chown root:root {0} && chmod +x {0}'.format( rc_local_path ) )

    @fabric_task
    def _get_rc_local_path( self ):
        """
        Return the canonical path to /etc/rc.local or an equivalent shell script that gets
        executed during boot up. The last component in the path must not be be a symlink,
        other components may be.
        """
        # might be a symlink but prepend_remote_shell_script doesn't work with symlinks
        return sudo( 'readlink -f /etc/rc.local' )

    @fabric_task
    def _prepend_remote_shell_script( self, script, remote_path, **put_kwargs ):
        """
        Insert the given script into the remote file at the given path before the first script
        line. See prepend_shell_script() for a definition of script line.

        :param script: the script to be inserted
        :param remote_path: the path to the file on the remote host
        :param put_kwargs: arguments passed to Fabric's put operation
        """
        with closing( StringIO( ) ) as out_file:
            with closing( StringIO( ) ) as in_file:
                get( remote_path=remote_path, local_path=in_file )
                in_file.seek( 0 )
                prepend_shell_script( '\n' + script, in_file, out_file )
            out_file.seek( 0 )
            put( remote_path=remote_path, local_path=out_file, **put_kwargs )

    env_entry_re = re.compile( r'^\s*([^=\s]+)\s*=\s*"?(.*?)"?\s*$' )

    @classmethod
    def _patch_etc_environment( cls, env_file, dirs=None, dirs_var='PATH', env_pairs=None ):
        r"""
        Patch /etc/environment by A) adding a list of directories to a PATH o PATH-like variable 
        and/or B) adding other environment variables to it.
        
        :param env_file: A seekable file handle to /etc/environment or a file of that format
         
        :param list dirs: A list of directory paths to be added to the /etc/environment entry for 
               PATH, or the entry referenced by dirs_var
                
        :param str dirs_var: The name of the variable to append `dirs` to
        
        :param dict env_pairs: A dictionary with other environment variable to append 
        
        >>> f=StringIO( 'FOO = " BAR " \n  PATH =foo:bar\nBLA="FASEL"' )
        >>> f.seek( 0, 2 ) # seek to end as if file was opened with mode 'a'
        >>> RcLocalBox._patch_etc_environment( f, dirs=[ "new1" ] )
        >>> f.getvalue()
        'BLA="FASEL"\nFOO=" BAR "\nPATH="foo:bar:new1"\n'
        >>> RcLocalBox._patch_etc_environment( f, dirs=[ "new2" ], dirs_var='PATH2' )
        >>> f.getvalue()
        'BLA="FASEL"\nFOO=" BAR "\nPATH="foo:bar:new1"\nPATH2="new2"\n'
        """

        def parse_entry( s ):
            m = cls.env_entry_re.match( s )
            return m.group( 1 ), m.group( 2 )

        env_file.seek( 0 )
        env = dict( parse_entry( _ ) for _ in env_file.read( ).splitlines( ) )

        # Do we have directories to add to a path?
        if dirs is not None:
            path = filter( None, env.get( dirs_var, '' ).split( ':' ) )
            path.extend( dirs )
            env[ dirs_var ] = ':'.join( path )

        # Do we have other environment variables to write?
        if env_pairs is not None:
            for (k, v) in env_pairs.iteritems():
                env[k] = v

        env_file.seek( 0 )
        env_file.truncate( 0 )
        for var in sorted( env.items( ) ): 
            env_file.write( '%s="%s"\n' % var )


# FIXME: This is here for an experimental feature (ordering commands that depend on each other)

if False:
    def toposort2( data ):
        """
        Dependencies are expressed as a dictionary whose keys are items and whose values are a set
        of dependent items. Output is a list of sets in topological order. The first set consists of
        items with no dependences, each subsequent set consists of items that depend upon items in
        the preceeding sets.

        >>> toposort2({
        ...     2: {11},
        ...     9: {11, 8},
        ...     10: {11, 3},
        ...     11: {7, 5},
        ...     8: {7, 3},
        ...     }) )
        [3, 5, 7]
        [8, 11]
        [2, 9, 10]

        """

        from functools import reduce

        # Ignore self dependencies.
        for k, v in data.items( ):
            v.discard( k )
        # Find all items that don't depend on anything.
        extra_items_in_deps = reduce( set.union, data.itervalues( ) ) - set( data.iterkeys( ) )
        # Add empty dependences where needed
        data.update( { item: set( ) for item in extra_items_in_deps } )
        while True:
            ordered = set( item for item, dep in data.iteritems( ) if not dep )
            if not ordered:
                break
            yield ordered
            data = { item: (dep - ordered)
                for item, dep in data.iteritems( )
                if item not in ordered }
        assert not data, "Cyclic dependencies exist among these items:\n%s" % '\n'.join(
            repr( x ) for x in data.iteritems( ) )
