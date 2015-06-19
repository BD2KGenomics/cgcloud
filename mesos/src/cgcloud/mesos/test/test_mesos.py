import os
import time
import logging
import itertools

from cgcloud.core.test import CgcloudTestCase
from cgcloud.core.ui import main
from cgcloud.lib.ec2 import UnexpectedResourceState
from cgcloud.mesos import MesosBox, MesosMaster, MesosSlave

log = logging.getLogger( __name__ )

master = MesosMaster.role( )
slave = MesosSlave.role( )
role = MesosBox.role( )

num_slaves = 2

cleanup =True
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
            cls._cgcloud( 'create', role, '-I', '-T' )

    @classmethod
    def tearDownClass( cls ):
        if cleanup and create_image:
            cls._cgcloud( 'delete-image', role )
        super( ClusterTests, cls ).tearDownClass( )

    def test_mesos_execute( self ):
        self._create_cluster( )
        try:
            self._assert_remote_failure( )
            self._wait_for_slaves( )
            self._mesos_execute( )
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
                pass # to be expected if slaves aren't fully up yet
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
        commands = ["test $(less /var/log/mesosbox/mesosmaster/mesos-master.INFO | grep -c 'Registering slave at') = %s" % num_slaves]
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

    def _mesos_execute( self ):
        self._ssh( master, "mesos execute --master=mesos-master:5050 --name=Test --command='touch test.txt'>>'/home/ubuntu/taskoutput.txt'")
        self._ssh( master, "test $(less /home/ubuntu/taskoutput.txt | grep -c TASK_FINISHED)=1")

    ssh_opts = [ '-o', 'UserKnownHostsFile=/dev/null', '-o', 'StrictHostKeyChecking=no' ]

    @classmethod
    def _ssh( cls, role, *args ):
        cls._cgcloud( 'ssh',
                      role,
                      *itertools.chain( cls.ssh_opts, args ) )

    @classmethod
    def _rsync( cls, role, *args ):
        cls._cgcloud( 'rsync',
                      '--ssh-opts=' + ' '.join( cls.ssh_opts ),
                      '-l', 'mesosbox',
                      role,
                      *args )

    @classmethod
    def _cgcloud( cls, *args ):
        log.info( "Running %r" % (args,) )
        main( args )
