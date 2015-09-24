import logging
import os
import itertools
from subprocess import check_call

from bd2k.util.exceptions import panic

from cgcloud.core import roles
from cgcloud.core.test import CgcloudTestCase
from cgcloud.core.cli import main

log = logging.getLogger( __name__ )


class CoreTests( CgcloudTestCase ):
    """
    Tests the typical life-cycle of instances and images
    """
    _multiprocess_shared_ = True

    roles = roles()

    @classmethod
    def __box_test( cls, box ):
        def box_test( self ):
            """
            :type self: CoreTests
            """
            role = box.role( )
            self._cgcloud( 'create', role )
            try:
                self._cgcloud( 'stop', role )
                self._cgcloud( 'image', role )
                try:
                    self._cgcloud( 'terminate', role )
                    self._cgcloud( 'recreate', role )
                    file_name = 'foo-' + role
                    self._ssh( role, 'touch', file_name )
                    self._rsync( role, ':' + file_name, '.' )
                    self.assertTrue( os.path.exists( file_name ) )
                    os.unlink( file_name )
                    self._cgcloud( 'terminate', role )
                finally:
                    self._cgcloud( 'delete-image', role )
            except:
                with panic( log ):
                    self._cgcloud( 'terminate', '-q', role )

        return box_test

    def _cgcloud( self, *args ):
        log.info( "Running %r" % (args,) )
        if os.environ.get( 'CGCLOUD_TEST_EXEC', "" ):
            check_call( ('cgcloud',) + args )
        else:
            main( args )

    ssh_opts = [ '-o', 'UserKnownHostsFile=/dev/null', '-o', 'StrictHostKeyChecking=no' ]

    def _ssh( self, role, *args ):
        self._cgcloud( 'ssh', role, *(itertools.chain( self.ssh_opts, args )) )

    def _rsync( self, role, *args ):
        self._cgcloud( 'rsync', '--ssh-opts=' + ' '.join( self.ssh_opts ), role, *args )

    @classmethod
    def make_tests( cls ):
        for box in cls.roles:
            test_method = cls.__box_test( box )
            test_method.__name__ = 'test_%s' % box.role( ).replace( '-', '_' )
            setattr( cls, test_method.__name__, test_method )

    def test_illegal_argument( self ):
        try:
            self._cgcloud( 'delete-image', self.roles[ 0 ].role( ), '-1' )
            self.fail( )
        except SystemExit:
            pass


CoreTests.make_tests( )
