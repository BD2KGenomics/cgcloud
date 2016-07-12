import os
import time
from struct import pack
from unittest import TestCase

from boto.utils import get_instance_metadata

from cgcloud.lib import aws_d64, test_namespace_suffix_length
from cgcloud.lib.context import Context
from cgcloud.lib.ec2 import running_on_ec2


class CgcloudTestCase( TestCase ):
    """
    A base class for CGCloud test cases. When run with CGCLOUD_NAMESPACE unset, a new test
    namespace will be prepared during setup and cleaned up during teardown. Otherwise,
    the configured namespace will be used but not cleaned up.
    """
    __namespace = None
    cleanup = True
    ctx = None

    @classmethod
    def setUpClass( cls ):
        super( CgcloudTestCase, cls ).tearDownClass( )
        if running_on_ec2( ):
            os.environ.setdefault( 'CGCLOUD_ZONE',
                                   get_instance_metadata( )[ 'placement' ][ 'availability-zone' ] )
        # Using the d64 of a binary string that starts with a 4-byte, big-endian time stamp
        # yields compact names whose lexicographical sorting is consistent with the historical
        # order. We add the process ID so we can run tests concurrently in child processes using
        # the pytest-xdist plugin.
        suffix = aws_d64.encode( pack( '>II', int( time.time( ) ), os.getpid( ) ) )
        assert len( suffix ) == test_namespace_suffix_length
        cls.__namespace = '/test/%s/' % suffix
        os.environ.setdefault( 'CGCLOUD_NAMESPACE', cls.__namespace )
        cls.ctx = Context( availability_zone=os.environ[ 'CGCLOUD_ZONE' ],
                           namespace=os.environ[ 'CGCLOUD_NAMESPACE' ] )

    @classmethod
    def tearDownClass( cls ):
        # Only cleanup if the context is using the default test namespace. If another namespace
        # is configured, we can't assume that all resources were created by the test and that
        # they can therefore be removed.
        if cls.cleanup and cls.ctx.namespace == cls.__namespace:
            cls.ctx.reset_namespace_security( )
        super( CgcloudTestCase, cls ).setUpClass( )
