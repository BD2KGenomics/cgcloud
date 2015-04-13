from StringIO import StringIO
from contextlib import contextmanager

from fabric.operations import sudo as real_sudo, get, put
from fabric.state import env


def sudo( command, sudo_args=None, **kwargs ):
    """
    Work around https://github.com/fabric/fabric/issues/503
    """
    if sudo_args is not None:
        old_prefix = env.sudo_prefix
        env.sudo_prefix = '%s %s' % ( old_prefix, sudo_args )
    try:
        return real_sudo( command, **kwargs )
    finally:
        if sudo_args is not None:
            env.sudo_prefix = old_prefix


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
