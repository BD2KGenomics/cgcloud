from collections import OrderedDict
from importlib import import_module
import logging
import os

from cgcloud.lib.util import Application, app_name

import cgcloud.core

PACKAGES = [ cgcloud.core ] + [ import_module( package_name )
    for package_name in os.environ.get( 'CGCLOUD_PLUGINS', "" ).split( ":" )
    if package_name ]

DEBUG_LOG_FILE_NAME = '%s.{pid}.log' % app_name( )


def main( ):
    app = Cgcloud( )
    for package in PACKAGES:
        for command in package.COMMANDS:
            app.add( command )
    app.run( )


class Cgcloud( Application ):
    def __init__( self ):
        super( Cgcloud, self ).__init__( )
        self.option( '--debug',
                     default=False, action='store_true',
                     help='Write debug log to %s in current directory.' % DEBUG_LOG_FILE_NAME )
        self.boxes = OrderedDict( )
        for package in PACKAGES:
            for box_cls in package.BOXES:
                self.boxes[ box_cls.role( ) ] = box_cls

    def prepare( self, options ):
        if options.debug:
            logging.basicConfig( filename=DEBUG_LOG_FILE_NAME.format( pid=os.getpid( ) ),
                                 level=logging.DEBUG )


