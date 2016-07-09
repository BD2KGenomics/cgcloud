import logging
import os

from bd2k.util.exceptions import panic

from cgcloud.core import roles
from cgcloud.core.test import CgcloudTestCase, out_stderr

log = logging.getLogger( __name__ )


class CoreTests( CgcloudTestCase ):
    """
    Tests the typical life-cycle of instances and images
    """
    _multiprocess_shared_ = True

    roles = roles( )

    def _test( self, box_cls ):
        role = box_cls.role( )
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
                self._cgcloud( 'terminate', '--quick', role )

    @classmethod
    def make_tests( cls ):
        for box_cls in cls.roles:
            test_method = (lambda _box_cls: lambda self: cls._test( self, _box_cls ))( box_cls )
            test_method.__name__ = 'test_%s' % box_cls.role( ).replace( '-', '_' )
            setattr( cls, test_method.__name__, test_method )

    def test_illegal_argument( self ):
        # Capture sys.stderr so we don't pollute the log of a successful run with an error message
        with out_stderr( ):
            self.assertRaises( SystemExit,
                               self._cgcloud, 'delete-image', self.roles[ 0 ].role( ), '-1' )

    def test_pytest_capture_workaround( self ):
        # To see this test fail, comment out the workaround in conftest.py and run this test from
        # the command line. Note that when running the test from PyCharm you will not be able to
        # see it fail because PyCharm's runner is hard-wired to disable PyTest's capture.
        from fabric.operations import run
        from fabric.context_managers import settings
        with settings( host_string='localhost' ):
            # We need a command that doesn't exit immediately such that the loop body in Fabric's
            # input_loop() is actually run at least once.
            run( 'sleep 1' )


CoreTests.make_tests( )
