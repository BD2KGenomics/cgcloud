import os
import sys
from contextlib import contextmanager
from itertools import ifilter
from tempfile import mkstemp

import subprocess32
from bd2k.util.iterables import concat
from boto.utils import logging

from cgcloud.core.cli import main, CGCloud
from cgcloud.lib.test import CgcloudTestCase

log = logging.getLogger( __name__ )


class CoreTestCase( CgcloudTestCase ):
    @classmethod
    def setUpClass( cls ):
        CGCloud.setup_logging( )
        CGCloud.silence_boto_and_paramiko( )
        super( CoreTestCase, cls ).setUpClass( )

    ssh_opts = ('-o', 'UserKnownHostsFile=/dev/null', '-o', 'StrictHostKeyChecking=no')

    @classmethod
    def ssh_opts_str( cls ):
        return ' '.join( cls.ssh_opts )

    def _assert_remote_failure( self, role ):
        """
        Proof that failed remote commands lead to test failures
        """
        self._ssh( role, 'true' )
        try:
            self._ssh( role, 'false' )
            self.fail( )
        except SystemExit as e:
            self.assertEqual( e.code, 1 )

    @classmethod
    def _ssh( cls, role, *args, **kwargs ):
        cls._cgcloud( *concat( 'ssh', dict_to_opts( kwargs ), role, cls.ssh_opts, args ) )

    @classmethod
    def _rsync( cls, role, *args, **kwargs ):
        cls._cgcloud( *concat( 'rsync',
                               dict_to_opts( kwargs, ssh_opts=cls.ssh_opts_str( ) ),
                               role, args ) )

    def _send_file( self, role, content, name ):
        script, script_path = mkstemp( )
        try:
            os.write( script, content )
        except:
            os.close( script )
            raise
        else:
            os.close( script )
            self._rsync( role, script_path, ':' + name )
        finally:
            os.unlink( script_path )

    @classmethod
    def _cgcloud( cls, *args ):
        log.info( 'Running %r', args )
        if os.environ.get( 'CGCLOUD_TEST_EXEC', "" ):
            subprocess32.check_call( concat( 'cgcloud', args ) )
        else:
            main( args )


@contextmanager
def out_stderr( ):
    with open( os.devnull, 'a' ) as f:
        f, sys.stderr = sys.stderr, f
        try:
            yield
        finally:
            f, sys.stderr = sys.stderr, f


def dict_to_opts( d=None, **kwargs ):
    """
    >>> list( dict_to_opts( dict( foo=True ) ) )
    ['--foo']
    >>> list( dict_to_opts( dict( foo=False) ) )
    []
    >>> list( dict_to_opts( foo=True ) )
    ['--foo']
    >>> list( dict_to_opts( dict( foo_bar=1 ), x=3 ) )
    ['--foo-bar=1', '-x=3']
    """
    if d is None:
        d = kwargs
    elif kwargs:
        d = dict( d, **kwargs )

    def to_opt( k, v ):
        s = '--' + k.replace( '_', '-' ) if len( k ) > 1 else '-' + k
        if v is True:
            return s
        elif v is False:
            return None
        else:
            return s + '=' + str( v )

    return ifilter( None, (to_opt( k, v ) for k, v in d.iteritems( )) )
