import os
import time
from unittest import TestCase

from boto.utils import get_instance_metadata

from cgcloud.core import test_namespace_suffix_length
from cgcloud.lib.ec2 import running_on_ec2


class CgcloudTestCase( TestCase ):
    @classmethod
    def setUpClass( cls ):
        super( CgcloudTestCase, cls ).setUpClass( )
        suffix = hex( int( time.time( ) ) )[ 2: ]
        assert len( suffix ) == test_namespace_suffix_length
        os.environ.setdefault( 'CGCLOUD_NAMESPACE', '/test-%s/' % suffix )
        if running_on_ec2( ):
            os.environ.setdefault( 'CGCLOUD_ZONE',
                                   get_instance_metadata( )[ 'placement' ][ 'availability-zone' ] )
