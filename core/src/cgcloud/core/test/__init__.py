import os
import sys
import time
from contextlib import contextmanager
from itertools import ifilter
from struct import pack
from tempfile import mkstemp
from unittest import TestCase

import subprocess32
from bd2k.util.d64 import D64
from bd2k.util.iterables import concat
from boto.utils import get_instance_metadata, logging

from cgcloud.core import test_namespace_suffix_length
from cgcloud.core.cli import main, CGCloud
from cgcloud.lib.context import Context
from cgcloud.lib.ec2 import running_on_ec2

log = logging.getLogger( __name__ )

d64 = D64( '.-' )  # hopefully the dot is supported for all AWS resource names


class CgcloudTestCase( TestCase ):
    """
    A base class for CGCloud test cases. When run with CGCLOUD_NAMESPACE unset, a new test
    namespace will be prepared during setup and cleaned up during teardown. Otherwise,
    the configured namespace will be used and not
    """
    cleanup = True
    ctx = None
    __namespace = None

    @classmethod
    def setUpClass( cls ):
        CGCloud.setup_logging( )
        CGCloud.silence_boto_and_paramiko( )
        super( CgcloudTestCase, cls ).setUpClass( )
        if running_on_ec2( ):
            os.environ.setdefault( 'CGCLOUD_ZONE',
                                   get_instance_metadata( )[ 'placement' ][ 'availability-zone' ] )
        # Using the d64 of a binary string that starts with a 4-byte, big-endian time stamp
        # yields compact names whose lexicographical sorting is consistent with the historical
        # order. We add the process ID so we can run tests concurrently in child processes using
        # the pytest-xdist plugin.
        suffix = d64.encode( pack( '>II', int( time.time( ) ), os.getpid( ) ) )
        assert len( suffix ) == test_namespace_suffix_length
        cls.__namespace = '/test/%s/' % suffix
        os.environ.setdefault( 'CGCLOUD_NAMESPACE', cls.__namespace )
        cls.ctx = Context( os.environ[ 'CGCLOUD_ZONE' ], os.environ[ 'CGCLOUD_NAMESPACE' ] )

    @classmethod
    def tearDownClass( cls ):
        # Only cleanup if the context is using the default test namespace. If another namespace
        # is configured, we can't assume that all resources were created by the test and that
        # they can therefore be removed.
        if cls.cleanup and cls.ctx.namespace == cls.__namespace:
            cls.ctx.reset_namespace_security( )
        super( CgcloudTestCase, cls ).tearDownClass( )

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
def out_stderr():
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
