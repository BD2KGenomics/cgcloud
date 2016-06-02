import glob
import itertools
import logging
import os
import subprocess
import sys

log = logging.getLogger( __name__ )

# A "keyword" is an argument to pytest's -k option. It acts as a selector for tests. Each of the 
# keywords in the list below will be run concurrently. Once they are done, everything else will 
# be run sequentially. Please note that keywords are match as substrings: Foo will match Foo, 
# FooBar and BarFoo. 
#
try:
    if not os.getcwd( ) in sys.path:
        sys.path.append( os.getcwd( ) )
    from tests import parallelizable_keywords
except ImportError:
    parallelizable_keywords = [ ]


def run_tests( index, keywords=None, args=None ):
    cmd = [ sys.executable, '-m', 'pytest', '--capture=no', '-vv',
            '--junitxml', 'nosetests-%s.xml' % index ]
    if keywords:
        cmd.extend( [ '-k', keywords ] )
    if args:
        cmd.extend( args )
    log.info( 'Running %r', cmd )
    return subprocess.Popen( cmd )


def main( args ):
    for name in glob.glob( 'nosetests-*.xml' ):
        os.unlink( name )
    num_failures = 0
    index = itertools.count( )
    pids = set( )
    # PyTest thinks that absence of tests constitutes an error. 
    # Luckily it has a distinct status code (5) for that.
    ok_statuses = (0, 5)
    try:
        for keyword in parallelizable_keywords:
            process = run_tests( index=str( next( index ) ),
                                 keywords=keyword,
                                 args=args )
            pids.add( process.pid )
        while pids:
            pid, status = os.wait( )
            pids.remove( pid )
            if os.WIFEXITED( status ):
                status = os.WEXITSTATUS( status )
                if status not in ok_statuses:
                    num_failures += 1
            else:
                num_failures += 1
    except:
        for pid in pids:
            os.kill( pid, 15 )
        raise

    if parallelizable_keywords:
        everything_else = ' and '.join( 'not ' + keyword for keyword in parallelizable_keywords )
    else:
        everything_else = None

    process = run_tests( index=str( next( index ) ),
                         keywords=everything_else,
                         args=args )
    if process.wait( ) not in ok_statuses:
        num_failures += 1

    import xml.etree.ElementTree as ET
    testsuites = ET.Element( 'testsuites' )
    for name in glob.glob( 'nosetests-*.xml' ):
        log.info( "Reading test report %s", name )
        tree = ET.parse( name )
        testsuites.append( tree.getroot( ) )
        os.unlink( name )
    name = 'nosetests.xml'
    log.info( 'Writing aggregate test report %s', name )
    ET.ElementTree( testsuites ).write( name, xml_declaration=True )

    if num_failures:
        log.error( '%i out %i child processes failed', num_failures, next( index ) )

    return num_failures


if __name__ == '__main__':
    logging.basicConfig( level=logging.INFO )
    sys.exit( main( sys.argv[ 1: ] ) )
