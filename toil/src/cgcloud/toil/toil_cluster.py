import logging
from cgcloud.toil.toil_box import ToilLeader
from cgcloud.core.commands import ClusterCommand

log = logging.getLogger( __name__ )
shared_dir="/home/mesosbox/shared/"


class CreateToilCluster(ClusterCommand):
    def __init__( self, application ):
        super( CreateToilCluster, self ).__init__( application )
        self.option( '--shared-dir', default=None,
                     help='The absolute path to a local directory to distribute onto each node.' )

    def run_on_creation( self, master, options ):
        """
        :type master: ToilMaster
        """
        dir = options.shared_dir
        if dir:
            log.info("Rsyncing selected directory to master")
            master.rsync( args=[ '-r', dir, ":" + shared_dir ] )
        log.info( "=== Launching workers ===" )
        master.clone( num_slaves=options.num_slaves,
                      slave_instance_type=options.slave_instance_type,
                      ebs_volume_size=options.ebs_volume_size)

    def run_in_ctx( self, options, ctx ):
        """
        Override run_in_ctx to hard code role class
        """
        log.info( "=== Launching leader ===" )
        if options.instance_type is None:
            options.instance_type = options.slave_instance_type
        return self.run_on_box( options, ToilLeader( ctx) )
