import inspect
import unittest
import sys


class TestReraise(unittest.TestCase):

    def foo( self ):
        try:
            self.line_of_primary_exc = inspect.currentframe().f_lineno + 1
            raise ValueError( "primary" )
        except Exception:
            exc_type, exc_value, exc_traceback = sys.exc_info( )
            try:
                raise RuntimeError( "secondary" )
            except Exception:
                pass
            raise exc_type, exc_value, exc_traceback

    def test_reraise(self):
        try:
            self.foo( )
        except:
            exc_type, exc_value, exc_traceback = sys.exc_info( )
            self.assertEquals( exc_type, ValueError )
            self.assertEquals( exc_value.message, "primary" )
            while exc_traceback.tb_next is not None:
                exc_traceback = exc_traceback.tb_next
            self.assertEquals( exc_traceback.tb_lineno, self.line_of_primary_exc )


