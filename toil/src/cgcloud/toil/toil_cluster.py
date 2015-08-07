import logging
from cgcloud.toil.toil_box import ToilBox, ToilLeader
from cgcloud.mesos.mesos_cluster import CreateMesosCluster
from subprocess import check_call

log = logging.getLogger( __name__ )
shared_dir="/home/ubuntu/shared/"
class CreateToilCluster(CreateMesosCluster):
    def __init__( self, application ):
        super( CreateToilCluster, self ).__init__( application )
        self.option( '--dir_to_copy', default=None,
                     help='The path of a local directory to distribute onto each node.' )

    def run_on_creation( self, master, options ):
        """
        :type master: ToilMaster
        """
        dir = options.dir_to_copy
        if dir:
            check_call( ['rsync','-r','-e', 'ssh -o StrictHostKeyChecking=no', dir, "ubuntu@"+str(master.ip_address)+":"+shared_dir] )
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