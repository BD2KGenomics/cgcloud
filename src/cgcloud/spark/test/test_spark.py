import os
import time
import logging
import unittest
from tempfile import mkstemp
import itertools

from cgcloud.core.ui import main
from cgcloud.spark.spark_box import heredoc, install_dir
from cgcloud.spark import SparkBox, SparkMaster, SparkSlave

log = logging.getLogger( __name__ )

master = SparkMaster.role( )
slave = SparkSlave.role( )

num_slaves = 2


class ClusterTests( unittest.TestCase ):
    """
    Tests the typical life-cycle of instances and images
    """

    @classmethod
    def setUpClass( cls ):
        super( ClusterTests, cls ).setUpClass( )
        # FIMXE: use a unique namespace for every run
        os.environ.setdefault( 'CGCLOUD_NAMESPACE', '/test/' )
        # FIXME: on EC2 detect zone automatically
        os.environ.setdefault( 'CGCLOUD_ZONE', 'us-west-2a' )

    def test_cluster( self ):
        cleanup = True
        role = SparkBox.role( )
        self._cgcloud( 'create', role, '-I', '-T' )
        try:
            self._cgcloud( 'create-spark-cluster', '-s', str( num_slaves ) )
            try:
                # Proof that failed remote commands lead to test failures
                self._ssh( master, 'true' )
                try:
                    self._ssh( master, 'false' )
                    self.fail( )
                except SystemExit as e:
                    self.assertEqual( e.code, 1 )
                self._wait_for_slaves( )
                self._word_count( )
            finally:
                if cleanup:
                    for i in xrange( num_slaves ):
                        self._cgcloud( 'terminate', slave )
                    self._cgcloud( 'terminate', master )
        finally:
            if cleanup:
                self._cgcloud( 'delete-image', role )

    def _wait_for_slaves( self ):
        expiration = time.time( ) + 600
        while True:
            try:
                self._ssh( master, 'test $(cat %s/spark/conf/slaves | wc -l) = %s' % (
                install_dir, num_slaves ) )
                if time.time( ) >= expiration:
                    self.fail( "Cluster didn't come up in time" )
                break
            except SystemExit:
                time.sleep( 5 )
        # The slaves add themselves to the slaves file before the workers start up. Wait a
        # bit for the services to start.
        # FIXME: This is, of course, still racy.
        time.sleep( 60 )

    @unittest.skip( 'Only for interactive invocation' )
    def test_word_count_only( self ):
        self._word_count( )

    def _word_count( self ):
        self._ssh( master, 'hdfs dfs -rm -r -f -skipTrash /test.txt /test.txt.counts' )
        self._ssh( master, 'rm -rf test.txt test.txt.counts' )
        self._ssh( master, 'curl -o test.txt https://www.apache.org/licenses/LICENSE-2.0.txt' )
        self._ssh( master, 'hdfs dfs -put -f test.txt /' )
        script, script_path = mkstemp( )
        try:
            script = os.fdopen( script, 'w' )
            script.write( heredoc( """
                import sys
                from pyspark import SparkContext
                sc = SparkContext(appName="PythonPi")
                file = sc.textFile( "hdfs://spark-master/test.txt" )
                counts = ( file
                    .flatMap( lambda line: line.split( " " ) )
                    .map( lambda word: (word, 1) )
                    .reduceByKey( lambda a, b: a + b ) )
                counts.saveAsTextFile( "hdfs://spark-master/test.txt.counts" )""" ) )
            script.close( )
            self._rsync( master, script_path, ':wordcount.py' )
        except:
            script.close( )
            raise
        finally:
            os.unlink( script_path )
        self._ssh( master, 'spark-submit --executor-memory 512m wordcount.py' )
        self._ssh( master, 'hdfs dfs -get /test.txt.counts' )
        self._ssh( master, 'test -f test.txt.counts/_SUCCESS' )
        for i in xrange( num_slaves ):
            self._ssh( master, 'test -s test.txt.counts/part-%05d' % i )

    ssh_opts = [ '-o', 'UserKnownHostsFile=/dev/null', '-o', 'StrictHostKeyChecking=no' ]

    def _ssh( self, role, *args ):
        self._cgcloud( 'ssh',
                       '-l', 'sparkbox',
                       role,
                       *itertools.chain( self.ssh_opts, args ) )

    def _rsync( self, role, *args ):
        self._cgcloud( 'rsync',
                       '--ssh-opts=' + ' '.join( self.ssh_opts ),
                       '-l', 'sparkbox',
                       role,
                       *args )

    def _cgcloud( self, *args ):
        log.info( "Running %r" % (args,) )
        main( args )
