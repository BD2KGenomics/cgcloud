import os
import sys
import time
from StringIO import StringIO
from contextlib import contextmanager
from fcntl import fcntl, F_GETFL, F_SETFL
from pipes import quote
from threading import Thread

from bd2k.util.expando import Expando
from bd2k.util.iterables import concat
from bd2k.util.strings import interpolate as fmt
from fabric.operations import sudo as real_sudo, get, put, run
from fabric.state import env
import fabric.io
import fabric.operations


def sudo( command, sudo_args=None, **kwargs ):
    """
    Work around https://github.com/fabric/fabric/issues/503
    """
    if sudo_args is not None:
        old_prefix = env.sudo_prefix
        env.sudo_prefix = '%s %s' % (old_prefix, sudo_args)
    try:
        return real_sudo( command, **kwargs )
    finally:
        if sudo_args is not None:
            env.sudo_prefix = old_prefix


def runv( *args, **kwargs ):
    run( command=join_argv( args ), **kwargs )


def sudov( *args, **kwargs ):
    sudo( command=join_argv( args ), **kwargs )


def pip( args, path='pip', use_sudo=False ):
    """
    Run pip.

    :param args: a string or sequence of strings to be passed to pip as command line arguments.
    If given a sequence of strings, its elements will be quoted if necessary and joined with a
    single space in between.

    :param path: the path to pip

    :param use_sudo: whther to run pip as sudo
    """
    if isinstance( args, (str, unicode) ):
        command = path + ' ' + args
    else:
        command = join_argv( concat( path, args ) )
    # Disable pseudo terminal creation to prevent pip from spamming output with progress bar.
    kwargs = Expando( pty=False )
    if use_sudo:
        f = sudo
        # Set HOME so pip's cache doesn't go into real user's home, potentially creating files
        # not owned by that user (older versions of pip) or printing a warning about caching
        # being disabled.
        kwargs.sudo_args = '-H'
    else:
        f = run
    f( command, **kwargs )


def join_argv( command ):
    return ' '.join( map( quote, command ) )


def virtualenv( name, distributions=None, pip_distribution='pip', executable=None ):
    """
    Installs a set of distributions (aka PyPI packages) into a virtualenv under /opt and
    optionally links an executable from that virtualenv into /usr/loca/bin.

    :param name: the name of the directory under /opt that will hold the virtualenv

    :param distributions: a list of distributions to be installed into the virtualenv. Defaults
    to [ name ]. You can also list other "pip install" options, like --pre.

    :param pip_distribution: if non-empty, the distribution and optional version spec to upgrade
    pip to. Defaults to the latest version of pip. Set to empty string to prevent pip from being
    upgraded. Downgrades from the system-wide pip version currently don't work.

    :param executable: The name of an executable in the virtualenv's bin directory that should be
    symlinked into /usr/local/bin. The executable must be provided by the distributions that are
    installed in the virtualenv.
    """
    # FIXME: consider --no-pip and easy_installing pip to support downgrades
    if distributions is None:
        distributions = [ name ]
    venv = '/opt/' + name
    admin = run( 'whoami' )
    sudo( fmt( 'mkdir -p {venv}' ) )
    sudo( fmt( 'chown {admin}:{admin} {venv}' ) )
    try:
        run( fmt( 'virtualenv {venv}' ) )
        if pip_distribution:
            pip( path=venv + '/bin/pip', args=[ 'install', '--upgrade', pip_distribution ] )
        pip( path=venv + '/bin/pip', args=concat( 'install', distributions ) )
    finally:
        sudo( fmt( 'chown -R root:root {venv}' ) )
    if executable:
        sudo( fmt( 'ln -snf {venv}/bin/{executable} /usr/local/bin/' ) )


@contextmanager
def remote_open( remote_path, use_sudo=False ):
    """
    Equivalent of open( remote_path, "a+" ) as if run on the remote system
    """
    buf = StringIO( )
    get( remote_path=remote_path, local_path=buf )
    yield buf
    buf.seek( 0 )
    put( local_path=buf, remote_path=remote_path, use_sudo=use_sudo )


# noinspection PyPep8Naming
class remote_popen( object ):
    """
    A context manager that yields a file handle and a

    >>> from fabric.context_managers import hide, settings
    >>> with settings(host_string='localhost'):
    ...     with hide( 'output' ):
    ...          # Disable shell since it may print additional stuff to console
    ...          with remote_popen( 'sort -n', shell=False ) as f:
    ...              f.write( '\\n'.join( map( str, [ 3, 2, 1] ) ) )
    [localhost] run: sort -n
    3
    2
    1

    Above is the echoed input, below the sorted output.

    >>> print f.result
    1
    2
    3
    """

    def __init__( self, *args, **kwargs ):
        try:
            if kwargs[ 'pty' ]:
                raise RuntimeError( "The 'pty' keyword argument must be omitted or set to False" )
        except KeyError:
            kwargs[ 'pty' ] = False
        self.args = args
        self.kwargs = kwargs
        # FIXME: Eliminate this buffer and have caller write directly into the pipe
        self.stdin = StringIO( )
        self.stdin.result = None

    def __enter__( self ):
        return self.stdin

    def __exit__( self, exc_type, exc_val, exc_tb ):
        if exc_type is None:
            _r, _w = os.pipe( )

            def copy( ):
                with os.fdopen( _w, 'w' ) as w:
                    w.write( self.stdin.getvalue( ) )

            t = Thread( target=copy )
            t.start( )
            try:
                _stdin = sys.stdin.fileno( )
                _old_stdin = os.dup( _stdin )
                os.close( _stdin )
                assert _stdin == os.dup( _r )
                # monkey-patch Fabric
                _input_loop = fabric.operations.input_loop
                fabric.operations.input_loop = input_loop
                try:
                    self.stdin.result = self._run( )
                finally:
                    fabric.operations.input_loop = _input_loop
                    os.close( _stdin )
                    os.dup( _old_stdin )
            finally:
                t.join( )
        return False

    def _run( self ):
        return run( *self.args, **self.kwargs )


# noinspection PyPep8Naming
class remote_sudo_popen( remote_popen ):
    def _run( self ):
        sudo( *self.args, **self.kwargs )


# Version of Fabric's input_loop that handles EOF on stdin and reads more greedily with
# non-blocking mode.

# TODO: We should open a ticket for this.

from select import select
from fabric.network import ssh


def input_loop( chan, using_pty ):
    opts = fcntl( sys.stdin.fileno( ), F_GETFL )
    fcntl( sys.stdin.fileno( ), F_SETFL, opts | os.O_NONBLOCK )
    try:
        while not chan.exit_status_ready( ):
            r, w, x = select( [ sys.stdin ], [ ], [ ], 0.0 )
            have_char = (r and r[ 0 ] == sys.stdin)
            if have_char and chan.input_enabled:
                # Send all local stdin to remote end's stdin
                bytes = sys.stdin.read( )
                if bytes is None:
                    pass
                elif not bytes:
                    chan.shutdown_write( )
                    break
                else:
                    chan.sendall( bytes )
                    # Optionally echo locally, if needed.
                    if not using_pty and env.echo_stdin:
                        # Not using fastprint() here -- it prints as 'user'
                        # output level, don't want it to be accidentally hidden
                        sys.stdout.write( bytes )
                        sys.stdout.flush( )
            time.sleep( ssh.io_sleep )
    finally:
        fcntl( sys.stdin.fileno( ), F_SETFL, opts )
