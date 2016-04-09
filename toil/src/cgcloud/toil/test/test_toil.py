import logging
import os
import tempfile
import time
import unittest
from inspect import getsource
from textwrap import dedent

from bd2k.util.exceptions import panic

from cgcloud.mesos.test import MesosTestCase
from cgcloud.toil.toil_box import ToilLeader, ToilBox
from cgcloud.toil.toil_box import ToilWorker

log = logging.getLogger( __name__ )

leader = ToilLeader.role( )
worker = ToilWorker.role( )
node = ToilBox.role( )

num_workers = 2


class ToilClusterTests( MesosTestCase ):
    """
    Covers the creation of a Toil cluster from scratch and running a simple Toil job that invokes
    Docker on it.
    """
    cleanup = True
    create_image = True

    @classmethod
    def setUpClass( cls ):
        os.environ[ 'CGCLOUD_PLUGINS' ] = 'cgcloud.toil:cgcloud.mesos'
        super( ToilClusterTests, cls ).setUpClass( )
        if cls.create_image:
            cls._cgcloud( 'create', node, '-IT' )

    @classmethod
    def tearDownClass( cls ):
        if cls.cleanup and cls.create_image:
            cls._cgcloud( 'delete-image', node )
        super( ToilClusterTests, cls ).tearDownClass( )

    def test_hello_world( self ):
        shared_dir = self._prepare_shared_dir( )
        self._create_cluster( 1, '--share', shared_dir )
        try:
            self._assert_remote_failure( leader )
            self._wait_for_workers( )
            self._assert_shared_dir( )
            self._assert_s3am( )
            self._hello_world( )
        finally:
            if self.cleanup:
                self._terminate_cluster( )

    @unittest.skip( 'Only for interactive invocation' )
    def test_hello_world_only( self ):
        self._hello_world( )

    def _prepare_shared_dir( self ):
        shared_dir = tempfile.mkdtemp( )
        with open( os.path.join( shared_dir, 'foo' ), 'w' ) as f:
            f.write( 'bar' )
        # Append / so rsync transfers the content of directory not the directory itself
        shared_dir = os.path.join( shared_dir, '' )
        return shared_dir

    def _assert_shared_dir( self ):
        command = 'test "$(cat shared/foo)" == bar'
        self._ssh( leader, command )
        for i in xrange( num_workers ):
            self._ssh( worker, command, ordinal=i )

    def _assert_s3am( self ):
        self._ssh( leader, 's3am --help' )

    def _create_cluster( self, growth, *args ):
        self._cgcloud( 'create-cluster', 'toil', '-s=%d' % (num_workers - growth),
                       '--ssh-opts', self.ssh_opts_str( ), *args )
        if growth:
            self._cgcloud( 'grow-cluster', 'toil', '-s=%d' % growth )

    def _terminate_cluster( self ):
        self._cgcloud( 'terminate-cluster', 'toil' )

    def _hello_world( self ):
        script = 'hello_world.py'

        def hello_world( ):
            # noinspection PyUnresolvedReferences
            from toil.job import Job
            from subprocess import check_output
            import os

            def hello( name ):
                assert os.environ[ 'TOIL_WORKDIR' ] == '/var/lib/toil'
                return check_output( [ 'docker', 'run', '-e', 'FOO=' + name, 'ubuntu',
                                         'bash', '-c', 'echo -n Hello, $FOO!' ] )

            if __name__ == '__main__':
                options = Job.Runner.getDefaultArgumentParser( ).parse_args( )
                job = Job.wrapFn( hello, "world", cores=1, memory=1e6, disk=1e6, cache=1e6 )
                result = Job.Runner.startToil( job, options )
                assert result == 'Hello, world!'

        body = dedent( '\n'.join( getsource( hello_world ).split( '\n' )[ 1: ] ) )
        self._send_file( leader, body, script )

        def hex64( x ):
            return hex( int( x ) )[ 2: ].zfill( 8 )

        # Could use UUID but prefer historical ordering. Time in s plus PID is sufficiently unique.
        job_store = 'test-%s%s-toil-job-store' % (hex64( time.time( ) ), hex64( os.getpid( ) ))
        job_store = ':'.join( ('aws', self.ctx.region, job_store) )
        self._ssh( leader, 'toil', 'clean', job_store )
        try:
            self._ssh( leader, 'python2.7', script,
                       '--batchSystem=mesos',
                       '--mesosMaster=mesos-master:5050',
                       job_store )
        except:
            with panic( log ):
                self._ssh( leader, 'toil', 'clean', job_store )

    def test_persistence( self ):
        # Check that /var/lib/docker is on the persistent volume and that /var/lib/toil can be
        # switched between ephemeral and persistent. [ Would use docstring but confuses pytest ]
        foo = '/var/lib/docker/foo'
        bar = '/var/lib/toil/bar'

        def compare_device( oper ):
            return "test $(stat -c '%d' " + foo + ") " + oper + " $(stat -c '%d' " + bar + ")"

        volume_size_gb = 1
        self._create_cluster( 0, '--ebs-volume-size', str( volume_size_gb ),
                              '-O', 'persist_var_lib_toil=True' )
        try:
            try:
                self._wait_for_workers( )
                for ordinal in range( num_workers ):
                    self._ssh( worker, 'sudo touch ' + foo, admin=True, o=ordinal )
                    self._ssh( worker, 'touch ' + bar, o=ordinal )
                # Ensure both files are on the same device (/mnt/persistent)
                self._ssh( worker, compare_device( "==" ) )
            finally:
                self._terminate_cluster( )
            self._create_cluster( 0, '--ebs-volume-size', str( volume_size_gb ),
                                  '-O', 'persist_var_lib_toil=False' )
            try:
                self._wait_for_workers( )
                for ordinal in range( num_workers ):
                    self._ssh( worker, 'sudo test -f ' + foo, admin=True, o=ordinal )
                    self._ssh( worker, 'touch ' + bar, o=ordinal )
                # Ensure both files are on different devices (/mnt/persistent)
                self._ssh( worker, compare_device( "!=" ) )
            finally:
                if self.cleanup:
                    self._terminate_cluster( )
        finally:
            if self.cleanup:
                self._delete_volumes( )

    def _wait_for_workers( self ):
        self._wait_for_mesos_slaves( leader, num_workers )

    def _delete_volumes( self ):
        pass
