from __future__ import absolute_import
import sys

from setuptools import setup
from setuptools.command.test import test as TestCommand


class PyTest( TestCommand ):
    user_options = [ ('pytest-args=', 'a', "Arguments to pass to py.test") ]

    def initialize_options( self ):
        TestCommand.initialize_options( self )
        self.pytest_args = [ ]

    def finalize_options( self ):
        TestCommand.finalize_options( self )
        self.test_args = [ ]
        self.test_suite = True

    def run_tests( self ):
        import pytest
        # Sanitize command line arguments to avoid confusing Toil code attempting to parse them
        sys.argv[ 1: ] = [ ]
        errno = pytest.main( self.pytest_args )
        sys.exit( errno )


def _setup( **kwargs ):
    kwargs.setdefault( 'cmdclass', { } )[ 'test' ] = PyTest
    kwargs.setdefault( 'tests_require', [ ] ).append( 'pytest==2.8.2' )
    setup( **kwargs )
