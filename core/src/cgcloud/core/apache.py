import json
import logging
import os

from bd2k.util.strings import interpolate as fmt
from fabric.operations import run

from cgcloud.core.box import Box
from cgcloud.fabric.operations import sudo

log = logging.getLogger( __name__ )


class ApacheSoftwareBox( Box ):
    """
    A box to be mixed in to ease the hassle of installing Apache Software
    Foundation released software distros.
    """

    def _install_apache_package( self, remote_path, install_dir ):
        """
        Download the given package from an Apache download mirror and extract it to a child 
        directory of the directory at the given path. 

        :param str remote_path: the URL path of the package on the Apache download server and its 
               mirrors.
        
        :param str install_dir: The path to a local directory in which to create the directory 
               containing the extracted package. 
        """
        # TODO: run Fabric tasks with a different manager, so we don't need to catch SystemExit
        components = remote_path.split( '/' )
        package, tarball = components[ 0 ], components[ -1 ]
        # Some mirrors may be down or serve crap, so we may need to retry this a couple of times.
        tries = iter( xrange( 3 ) )
        while True:
            try:
                mirror_url = self.__apache_s3_mirror_url( remote_path )
                if run( "curl -Ofs '%s'" % mirror_url, warn_only=True ).failed:
                    mirror_url = self.__apache_official_mirror_url( remote_path )
                    run( "curl -Ofs '%s'" % mirror_url )
                try:
                    sudo( fmt( 'mkdir -p {install_dir}/{package}' ) )
                    sudo( fmt( 'tar -C {install_dir}/{package} '
                               '--strip-components=1 -xzf {tarball}' ) )
                    return
                finally:
                    run( fmt( 'rm {tarball}' ) )
            except SystemExit:
                if next( tries, None ) is None:
                    raise
                else:
                    log.warn( "Could not download or extract the package, retrying ..." )

    def __apache_official_mirror_url( self, remote_path ):
        url = 'http://www.apache.org/dyn/closer.cgi?path=%s&asjson=1' % remote_path
        mirrors = run( "curl -fs '%s'" % url )
        mirrors = json.loads( mirrors )
        mirror = mirrors[ 'preferred' ]
        url = mirror + remote_path
        return url

    def __apache_s3_mirror_url( self, remote_path ):
        file_name = os.path.basename( remote_path )
        return 'https://s3-us-west-2.amazonaws.com/bd2k-artifacts/cgcloud/' + file_name
