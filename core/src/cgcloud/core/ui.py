from collections import OrderedDict
from importlib import import_module
import logging
import os
import sys

from cgcloud.lib.util import Application, app_name
import cgcloud.core

log = logging.getLogger( __name__ )


def main( args=None ):
    """
    This is the cgcloud entrypoint. It should be installed via setuptools.setup( entry_points=... )
    """
    packages = [ cgcloud.core ] + [ import_module( package_name )
        for package_name in os.environ.get( 'CGCLOUD_PLUGINS', "" ).split( ":" )
        if package_name ]
    app = CGCloud( packages )
    for package in packages:
        for command in package.COMMANDS:
            app.add( command )
    app.run( args )


class CGCloud( Application ):
    debug_log_file_name = '%s.{pid}.log' % app_name( )

    def __init__( self, packages ):
        super( CGCloud, self ).__init__( )
        self.option( '--debug',
                     default=False, action='store_true',
                     help='Write debug log to %s in current directory.' % self.debug_log_file_name )
        self.boxes = OrderedDict( )
        for package in packages:
            for box_cls in package.BOXES:
                self.boxes[ box_cls.role( ) ] = box_cls

    def prepare( self, options ):
        root_logger = logging.getLogger( )
        if len( root_logger.handlers ) == 0:
            root_logger.setLevel( logging.INFO )
            stream_handler = logging.StreamHandler( sys.stderr )
            stream_handler.setFormatter( logging.Formatter( "%(levelname)s: %(message)s" ) )
            stream_handler.setLevel( logging.INFO )
            root_logger.addHandler( stream_handler )
            if options.debug:
                root_logger.setLevel( logging.DEBUG )
                file_name = self.debug_log_file_name.format( pid=os.getpid( ) )
                file_handler = logging.FileHandler( file_name )
                file_handler.setLevel( logging.DEBUG )
                file_handler.setFormatter( logging.Formatter(
                    '%(asctime)s: %(levelname)s: %(name)s: %(message)s' ) )
                root_logger.addHandler( file_handler )
            else:
                # There are quite a few cases where we expect AWS requests to fail, but it seems
                # that boto handles these by logging the error *and* raising an exception. We
                # don't want to confuse the user with those error messages.
                logging.getLogger( 'boto' ).setLevel( logging.CRITICAL )
                logging.getLogger( 'paramiko' ).setLevel( logging.WARN )
