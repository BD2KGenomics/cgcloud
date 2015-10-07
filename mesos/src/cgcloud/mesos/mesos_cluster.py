import logging

from cgcloud.core.commands import ClusterCommand
from cgcloud.mesos.mesos_box import MesosMaster

log = logging.getLogger( __name__ )


class CreateMesosCluster( ClusterCommand ):
    """
    Start a cluster of mesos-box instances, by recreating the master from a mesos-box image
    first, then cloning the master into the slaves.
    """

    def __init__( self, application ):
        super( CreateMesosCluster, self ).__init__( application )


    def run_in_ctx( self, options, ctx ):
        """
        Override run_in_ctx to hard code role class
        """
        log.info( "=== Launching master ===" )
        if options.instance_type is None:
            options.instance_type = options.slave_instance_type
        return self.run_on_box( options, MesosMaster( ctx,
                                                      ebs_volume_size=options.ebs_volume_size ) )

    def run_on_creation( self, master, options ):
        """
        :type master: MesosMaster
        """
        log.info( "=== Launching slaves ===" )
        master.clone( num_slaves=options.num_slaves,
                      slave_instance_type=options.slave_instance_type,
                      ebs_volume_size=options.ebs_volume_size )
