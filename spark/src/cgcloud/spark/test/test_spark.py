from inspect import getsource
import os
from textwrap import dedent
import time
import logging
import unittest
from tempfile import mkstemp

from cgcloud.core.test import CgcloudTestCase
from cgcloud.lib.util import heredoc
from cgcloud.spark.spark_box import install_dir, SparkBox, SparkMaster, SparkSlave

log = logging.getLogger( __name__ )

master = SparkMaster.role( )
slave = SparkSlave.role( )
node = SparkBox.role( )

num_slaves = 2


class SparkClusterTests( CgcloudTestCase ):
    """
    Covers the creation of a Spark cluster from scratch and running a simple Spark job on it.
    Also covers persistant HDFS between two cluster incarnations.
    """
    cleanup = True
    create_image = True

    @classmethod
    def setUpClass( cls ):
        os.environ[ 'CGCLOUD_PLUGINS' ] = 'cgcloud.spark'
        super( SparkClusterTests, cls ).setUpClass( )
        if cls.create_image:
            cls._cgcloud( 'create', node, '-IT' )

    @classmethod
    def tearDownClass( cls ):
        if cls.cleanup and cls.create_image:
            cls._cgcloud( 'delete-image', node )
        super( SparkClusterTests, cls ).tearDownClass( )

    def test_wordcount( self ):
        self._create_cluster( )
        try:
            self._assert_remote_failure( master )
            self._wait_for_slaves( )
            self._word_count( )
        finally:
            if self.cleanup:
                self._terminate_cluster( )

    def test_persistence( self ):
        volume_size_gb = 1
        self._create_cluster( '--ebs-volume-size', str( volume_size_gb ) )
        try:
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
                if self.cleanup:
                    self._terminate_cluster( )
        finally:
            if self.cleanup:
                self._delete_volumes( )

    def _create_cluster( self, *args ):
        self._cgcloud( 'create-cluster', 'spark', '-s', str( num_slaves ), *args )

    def _terminate_cluster( self ):
        self._cgcloud( 'terminate-cluster', 'spark' )

    def _wait_for_slaves( self ):
        delay = 5
        expiration = time.time( ) + 10 * 60
        commands = [
            'test $(cat %s/spark/conf/slaves | wc -l) = %s' % (install_dir, num_slaves),
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

        def word_count( ):
            # noinspection PyUnresolvedReferences
            from pyspark import SparkContext
            sc = SparkContext( appName='PythonPi' )
            input = sc.textFile( '/test.txt' )
            counts = (input
                .flatMap( lambda line: line.split( " " ) )
                .map( lambda word: (word, 1) )
                .reduceByKey( lambda a, b: a + b ))
            counts.saveAsTextFile( '/test.txt.counts' )

        script = 'wordcount.py'
        body = dedent( '\n'.join( getsource( word_count ).split( '\n' )[ 1: ] ) )
        self._send_file( master, body, script )

        self._ssh( master, 'spark-submit --driver-memory 64m --executor-memory 64m ' + script )
        self._ssh( master, 'hdfs dfs -get /test.txt.counts' )
        self._ssh( master, 'test -f test.txt.counts/_SUCCESS' )
        for i in xrange( num_slaves ):
            self._ssh( master, 'test -s test.txt.counts/part-%05d' % i )

    def _delete_volumes( self ):
        pass
