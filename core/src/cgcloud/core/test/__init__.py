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

    @classmethod
    def setUpClass( cls ):
        super( CgcloudTestCase, cls ).setUpClass( )
        if running_on_ec2( ):
            os.environ.setdefault( 'CGCLOUD_ZONE',
                                   get_instance_metadata( )[ 'placement' ][ 'availability-zone' ] )
        suffix = hex( int( time.time( ) ) )[ 2: ]
        assert len( suffix ) == test_namespace_suffix_length
        namespace = '/test/%s/' % suffix
        os.environ.setdefault( 'CGCLOUD_NAMESPACE', namespace )

    @classmethod
    def tearDownClass( cls ):
        ctx = Context( os.environ[ 'CGCLOUD_ZONE' ], os.environ[ 'CGCLOUD_NAMESPACE' ] )
        if cls.cleanup: ctx.cleanup()
        super( CgcloudTestCase, cls ).tearDownClass( )
