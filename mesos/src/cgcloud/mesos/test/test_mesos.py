import os
import time
import logging

from bd2k.util.iterables import flatten, cons

from cgcloud.core.test import CgcloudTestCase
from cgcloud.core.cli import main
from cgcloud.lib.ec2 import UnexpectedResourceState
from cgcloud.mesos.mesos_box import MesosBox, MesosMaster, MesosSlave, log_dir

log = logging.getLogger( __name__ )

master = MesosMaster.role( )
slave = MesosSlave.role( )
box = MesosBox.role( )

num_slaves = 2

cleanup = True
create_image = True


class ClusterTests( CgcloudTestCase ):
    """
    Tests the typical life-cycle of instances and images
    """

    @classmethod
    def setUpClass( cls ):
        os.environ[ 'CGCLOUD_PLUGINS' ] = 'cgcloud.mesos'
        super( ClusterTests, cls ).setUpClass( )
        if create_image:
            cls._cgcloud( 'create', box, '-I', '-T' )

    @classmethod
    def tearDownClass( cls ):
        if cleanup and create_image:
            cls._cgcloud( 'delete-image', box )
        super( ClusterTests, cls ).tearDownClass( )

    def test_mesos( self ):
        self._create_cluster( )
        try:
            self._assert_remote_failure( )
            self._wait_for_slaves( )
            self._test_mesos( )
        finally:
            if cleanup:
                self._terminate_cluster( )

    def _create_cluster( self, *args ):
        self._cgcloud( 'create-mesos-cluster', '-s', str( num_slaves ), *args )

    def _terminate_cluster( self ):
        i = 0
        while i < num_slaves:
            try:
                self._cgcloud( 'terminate', slave )
                i += 1
            except UnexpectedResourceState:
                pass  # to be expected if slaves aren't fully up yet
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
        commands = [
            'test "$(grep -c \'Registering slave at\' %s/mesos/mesos-master.INFO)" = "%s"' % (
                log_dir, num_slaves) ]
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

    def _test_mesos( self ):
        for i in xrange( num_slaves ):
            self._ssh( slave, 'test ! -f cgcloud_test.tmp', ordinal=i )
        # This is probabalistic: we hope that if we do ten times as many tasks as there are nodes
        # chances are that we hit each node at least once.
        num_tasks = num_slaves * 10
        for i in xrange( num_tasks ):
            self._ssh( master, 'mesos execute '
                               '--master=mesos-master:5050 '
                               '--name=cgcloud_test '
                               '--command="touch $(pwd)/cgcloud_test.tmp" '
                               '>> mesos_execute.out' )
        self._ssh( master, 'test "$(grep -c TASK_FINISHED mesos_execute.out)" = %i' % num_tasks )
        for i in xrange( num_slaves ):
            self._ssh( slave, 'test -f cgcloud_test.tmp', ordinal=i )

    ssh_opts = ('-o', 'UserKnownHostsFile=/dev/null', '-o', 'StrictHostKeyChecking=no')

    @classmethod
    def _ssh( cls, role, *args, **kwargs ):
        cls._cgcloud( *cons( 'ssh', dict_to_opts( kwargs ), role, cls.ssh_opts, args ) )

    @classmethod
    def _cgcloud( cls, *args ):
        log.info( "Running %r" % (args,) )
        main( args )


def dict_to_opts( d ):
    """
    >>> list( dict_to_opts( dict( foo=None ) ) )
    ['--foo']
    >>> list( dict_to_opts( dict( foo_bar=1 ) ) )
    ['--foo-bar', '1']
    """

    def to_opt( k ):
        return '--' + k.replace( '_', '-' )

    def to_arg( v ):
        return v if v is None else str( v )

    def skip_none( xs ):
        return (x for x in xs if x is not None)

    return skip_none( flatten( (to_opt( k ), to_arg( v )) for k, v in d.iteritems( ) ) )


