import time

from cgcloud.core.test import CgcloudTestCase
from cgcloud.mesos.mesos_box import log_dir


class MesosTestCase( CgcloudTestCase ):
    """
    Common functionality between Toil and Mesos tests
    """

    def _wait_for_mesos_slaves( self, master, num_slaves ):
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
