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

    def __install_apache_package( self, path ):
        """
        Download the given file from an Apache download mirror.

        Some mirrors may be down or serve crap, so we may need to retry this a couple of times.
        """
        assert path is not None

        # TODO: run Fabric tasks with a different manager, so we don't need to catch SystemExit
        components = path.split( '/' )
        package, tarball = components[ 0 ], components[ -1 ]
        tries = iter( xrange( 3 ) )
        while True:
            try:
                mirror_url = self.__apache_s3_mirror_url( path )
                if run( "curl -Ofs '%s'" % mirror_url, warn_only=True ).failed:
                    mirror_url = self.__apache_official_mirror_url( path )
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

    # FIMXE: this might have more general utility

    def __apache_official_mirror_url( self, path ):
        mirrors = run( "curl -fs 'http://www.apache.org/dyn/closer.cgi?path=%s&asjson=1'" % path )
        mirrors = json.loads( mirrors )
        mirror = mirrors[ 'preferred' ]
        url = mirror + path
        return url

    def __apache_s3_mirror_url( self, path ):
        file_name = os.path.basename( path )
        return 'https://s3-us-west-2.amazonaws.com/bd2k-artifacts/cgcloud/' + file_name
