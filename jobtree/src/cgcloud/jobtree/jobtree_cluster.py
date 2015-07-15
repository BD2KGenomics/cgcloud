import logging
from cgcloud.jobtree.jobtree_box import JobTreeBox, JobTreeLeader
from cgcloud.core.commands import RecreateCommand

log = logging.getLogger( __name__ )

class CreateJobTreeCluster(RecreateCommand):
    def __init__( self, application ):
        super( CreateJobTreeCluster, self ).__init__( application )
        self.option( '--num-slaves', '-s', metavar='NUM',
                     type=int, default=1,
                     help='The number of slaves to start.' )
        # We want --instance-type for the slaves and --master-instance-type for the master and we
        # want --master-instance-type to default to the value of --instance-type.
        super( CreateJobTreeCluster, self ).option(
            '--instance-type', '-t', metavar='TYPE', dest='slave_instance_type',
            default=JobTreeBox.recommended_instance_type( ),
            help='The type of EC2 instance to launch for the slaves, e.g. t2.micro, '
                 'm3.small, m3.medium, or m3.large etc. ' )
        self.option( '--master-instance-type', metavar='TYPE', dest='instance_type',
                     help='The type of EC2 instance to launch for the master, e.g. t2.micro, '
                          'm3.small, m3.medium, or m3.large etc. The default is the instance type '
                          'used for the slaves.' )
        self.option( '--ebs-volume-size', metavar='GB', default=0,
                     help='The size in GB of an EBS volume to be attached to each node for '
                          'persistent data such as that backing HDFS. By default HDFS will be '
                          'backed instance store ( ephemeral) only, or the root volume for '
                          'instance types that do not offer instance store.' )

    def run_on_creation( self, master, options ):
        """
        :type master: MesosMaster
        """
        log.info( "=== Launching workers ===" )
        master.clone( num_slaves=options.num_slaves,
                      slave_instance_type=options.slave_instance_type,
                      ebs_volume_size=options.ebs_volume_size )

    def option( self, *args, **kwargs ):
        option_name = args[ 0 ]
        if option_name == 'role':
            return
        elif option_name == '--instance-type':
            # Suppress the instance type option inherited from the parent so we can roll our own
            return
        super( CreateJobTreeCluster, self ).option( *args, **kwargs )

    def run_in_ctx( self, options, ctx ):
        """
        Override run_in_ctx to hard code role class
        """
        log.info( "=== Launching leader ===" )
        if options.instance_type is None:
            options.instance_type = options.slave_instance_type
        return self.run_on_box( options, JobTreeLeader( ctx ) )