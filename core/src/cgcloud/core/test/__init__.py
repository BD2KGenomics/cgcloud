import os
import time
from unittest import TestCase

from boto.utils import get_instance_metadata

from cgcloud.core import test_namespace_suffix_length
from cgcloud.lib.context import Context
from cgcloud.lib.ec2 import running_on_ec2


class CgcloudTestCase( TestCase ):
    """
    A base class for CGCloud test cases
    """
    cleanup = True
    ctx = None
    namespace = None

    @classmethod
    def setUpClass( cls ):
        super( CgcloudTestCase, cls ).setUpClass( )
        if running_on_ec2( ):
            os.environ.setdefault( 'CGCLOUD_ZONE',
                                   get_instance_metadata( )[ 'placement' ][ 'availability-zone' ] )
        suffix = hex( int( time.time( ) ) )[ 2: ]
        assert len( suffix ) == test_namespace_suffix_length
        cls.namespace = '/test/%s/' % suffix
        os.environ.setdefault( 'CGCLOUD_NAMESPACE', cls.namespace )

    @classmethod
    def tearDownClass( cls ):
        ctx = Context( os.environ[ 'CGCLOUD_ZONE' ], os.environ[ 'CGCLOUD_NAMESPACE' ] )
        # Only cleanup if the context is using the default test namespace. If another namespace
        # is configured, we can't assume that all resources were created by the test and that
        # they can therefore be removed.
        if cls.cleanup and ctx.namespace == cls.namespace:
            ctx.reset_namespace_security()
        super( CgcloudTestCase, cls ).tearDownClass( )
