import os
from unittest import TestCase

import cgcloud
from cgcloud.core.ui import main


class CoreTests( TestCase ):
    boxes = cgcloud.core.BOXES

    @classmethod
    def setUpClass( cls ):
        super( CoreTests, cls ).setUpClass( )
        # FIMXE: use a unique namespace for every run
        os.environ[ 'CGCLOUD_NAMESPACE' ] = '/test/'
        # FIXME: on EC2 detect zone automatically
        os.environ[ 'CGCLOUD_ZONE' ] = 'us-west-2a'

    @classmethod
    def __box_test( cls, box ):
        def box_test( self ):
            role = box.role( )
            main( [ 'create', role ] )
            try:
                main( [ 'stop', role ] )
                main( [ 'image', role ] )
                main( [ 'terminate', role ] )
                main( [ 'recreate', role ] )
                file_name = 'foo-' + role
                main( [ 'ssh', role, 'touch', file_name ] )
                main( [ 'rsync', role, ':' + file_name, '.' ] )
                self.assertTrue( os.path.exists( file_name ) )
                os.unlink( file_name )
                main( [ 'terminate', role ] )
            except:
                main( [ 'terminate', '-q', role ] )

        return box_test

    @classmethod
    def make_tests( cls ):
        for box in cls.boxes:
            test_method = cls.__box_test( box )
            test_method.__name__ = 'test_%s' % box.role( ).replace( '-', '_' )
            setattr( cls, test_method.__name__, test_method )


CoreTests.make_tests( )
