# PYTHON_ARGCOMPLETE_OK

from collections import OrderedDict
from importlib import import_module
import logging
import os
import sys
import imp

from cgcloud.lib.util import Application, app_name
import cgcloud.core

log = logging.getLogger( __name__ )


def main( args=None ):
    """
    This is the cgcloud entrypoint. It should be installed via setuptools.setup( entry_points=... )
    """
    plugins = [ cgcloud.core ] + [ import_module( plugin )
        for plugin in os.environ.get( 'CGCLOUD_PLUGINS', "" ).split( ":" )
        if plugin ]
    app = CGCloud( plugins )
    for plugin in plugins:
        for command_class in plugin.command_classes( ):
            app.add( command_class )
    app.run( args )


class CGCloud( Application ):
    """
    The main CLI application
    """
    debug_log_file_name = '%s.{pid}.log' % app_name( )

    def __init__( self, plugins ):
        super( CGCloud, self ).__init__( )
        self.option( '--debug',
                     default=False, action='store_true',
                     help='Write debug log to %s in current directory.' % self.debug_log_file_name )
        self.option( '--script', '-s', metavar='PATH',
                     help='The path to a Python script with additional role definitions.' )
        self.roles = OrderedDict( )
        for plugin in plugins:
            self._import_plugin_roles( plugin )

    def _import_plugin_roles( self, plugin ):
        for role in plugin.roles( ):
            self.roles[ role.role( ) ] = role

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
        if options.script:
            plugin = imp.load_source( os.path.splitext( os.path.basename( options.script ) )[ 0 ],
                                      options.script )
            self._import_plugin_roles( plugin )
