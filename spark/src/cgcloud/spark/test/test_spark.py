import os
import time
import logging
import unittest
from tempfile import mkstemp
import itertools

from cgcloud.core.test import CgcloudTestCase
from cgcloud.core.cli import main
from cgcloud.lib.util import heredoc
from cgcloud.spark.spark_box import install_dir, SparkBox, SparkMaster, SparkSlave

log = logging.getLogger( __name__ )

master = SparkMaster.role( )
slave = SparkSlave.role( )
role = SparkBox.role( )

num_slaves = 2

cleanup = True
create_image = True


class ClusterTests( CgcloudTestCase ):
    """
    Tests the typical life-cycle of instances and images
    """

    @classmethod
    def setUpClass( cls ):
        os.environ[ 'CGCLOUD_PLUGINS' ] = 'cgcloud.spark'
        super( ClusterTests, cls ).setUpClass( )
        if create_image:
            cls._cgcloud( 'create', role, '-I', '-T' )

    @classmethod
    def tearDownClass( cls ):
        if cleanup and create_image:
            cls._cgcloud( 'delete-image', role )
        super( ClusterTests, cls ).tearDownClass( )

    def test_wordcount( self ):
        self._create_cluster( )
        try:
            self._assert_remote_failure( )
            self._wait_for_slaves( )
            self._word_count( )
        finally:
            if cleanup:
                self._terminate_cluster( )

    # FIXME: Delete volumes

    def test_persistence( self ):
        volume_size_gb = 1
        self._create_cluster( '--ebs-volume-size', str( volume_size_gb ) )
        try:
            self._wait_for_slaves( )
            # Create and checksum a random file taking up 75% of the cluster's theoretical
            # storage capacity an  replication factor of 1.
            test_file_size_mb = volume_size_gb * 1024 * num_slaves * 3 / 4
            self._ssh( master, 'dd if=/dev/urandom bs=1M count=%d '
                               '| tee >(md5sum > test.bin.md5) '
                               '| hdfs dfs -put -f - /test.bin' % test_file_size_mb )
            self._ssh( master, 'hdfs dfs -put -f test.bin.md5 /' )
        finally:
            self._terminate_cluster( )
        self._create_cluster( '--ebs-volume-size', str( volume_size_gb ) )
        try:
            self._wait_for_slaves( )
            self._ssh( master, 'test "$(hdfs dfs -cat /test.bin.md5)" '
                               '== "$(hdfs dfs -cat /test.bin | md5sum)"' )
        finally:
            if cleanup:
                self._terminate_cluster( )

    def _create_cluster( self, *args ):
        self._cgcloud( 'create-spark-cluster', '-s', str( num_slaves ), *args )

    def _terminate_cluster( self ):
        for i in xrange( num_slaves ):
            self._cgcloud( 'terminate', slave )
        self._cgcloud( 'terminate', master )

    def _assert_remote_failure( self ):
        """
        Proof that failed remote commands lead to test failures
        """
        self._ssh( master, 'true' )
        try:
            self._ssh( master, 'false' )
            self.fail( )
        except SystemExit as e:
            self.assertEqual( e.code, 1 )

    def _wait_for_slaves( self ):
        delay = 5
        expiration = time.time( ) + 10 * 60
        commands = [ 'test $(cat %s/spark/conf/slaves | wc -l) = %s' % (install_dir, num_slaves),
            "hdfs dfsadmin -report -live | fgrep 'Live datanodes (%s)'" % num_slaves ]
        for command in commands:
            while True:
                try:
                    self._ssh( master, command )
                except SystemExit:
                    if time.time( ) + delay >= expiration:
                        self.fail( "Cluster didn't come up in time" )
                    time.sleep( delay )
                else:
                    break

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
                file = sc.textFile( "/test.txt" )
                counts = ( file
                    .flatMap( lambda line: line.split( " " ) )
                    .map( lambda word: (word, 1) )
                    .reduceByKey( lambda a, b: a + b ) )
                counts.saveAsTextFile( "/test.txt.counts" )""" ) )
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

    @classmethod
    def _ssh( cls, role, *args ):
        cls._cgcloud( 'ssh',
                      '-l', 'sparkbox',
                      role,
                      *itertools.chain( cls.ssh_opts, args ) )

    @classmethod
    def _rsync( cls, role, *args ):
        cls._cgcloud( 'rsync',
                      '--ssh-opts=' + ' '.join( cls.ssh_opts ),
                      '-l', 'sparkbox',
                      role,
                      *args )

    @classmethod
    def _cgcloud( cls, *args ):
        log.info( "Running %r" % (args,) )
        main( args )
