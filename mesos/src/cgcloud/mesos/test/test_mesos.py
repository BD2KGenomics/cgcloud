import os
import logging

from cgcloud.mesos.mesos_box import MesosBox, MesosMaster, MesosSlave
from cgcloud.mesos.test import MesosTestCase

log = logging.getLogger( __name__ )

master = MesosMaster.role( )
slave = MesosSlave.role( )
node = MesosBox.role( )

num_slaves = 2


class MesosClusterTests( MesosTestCase ):
    """
    Covers the creation of a Mesos cluster and running a simple script on it.
    """

    cleanup = True
    create_image = True

    @classmethod
    def setUpClass( cls ):
        os.environ[ 'CGCLOUD_PLUGINS' ] = 'cgcloud.mesos'
        super( MesosClusterTests, cls ).setUpClass( )
        if cls.create_image:
            cls._cgcloud( 'create', node, '-I', '-T' )

    @classmethod
    def tearDownClass( cls ):
        if cls.cleanup and cls.create_image:
            cls._cgcloud( 'delete-image', node )
        super( MesosClusterTests, cls ).tearDownClass( )

    def test_mesos( self ):
        self._create_cluster( )
        try:
            self._assert_remote_failure( master )
            self._wait_for_mesos_slaves( master, num_slaves )
            self._test_mesos( )
        finally:
            if self.cleanup:
                self._terminate_cluster( )

    def _create_cluster( self, *args ):
        self._cgcloud( 'create-cluster', 'mesos', '-s', str( num_slaves ), *args )

    def _terminate_cluster( self ):
        self._cgcloud( 'terminate-cluster', 'mesos' )

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
