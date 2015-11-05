from fnmatch import fnmatch
import os

from cgcloud.core.commands import InstanceCommand


class RegisterSlaves( InstanceCommand ):
    """
    Adds the specified slave images to Jenkins' EC2 configuration on the given master to the
    extend that the specified master can spawn later these slaves to run builds as needed.
    """

    def __init__( self, application, **kwargs ):
        super( RegisterSlaves, self ).__init__( application, **kwargs )
        self.option( '--slaves', '-s', metavar='ROLE_GLOB',
                     nargs='*', default=[ '*-jenkins-slave' ],
                     help='A list of roles names or role name patterns (shell globs) of the '
                          'slaves that should be added to the Jenkins config. For each matching '
                          'slave, the most recently created image will be registered using the '
                          'recommended instance type for that slave.' )
        self.option( '--clean', '-C', default=False, action='store_true',
                     help='Clear the list of slaves in the master before registering new slaves. '
                          'Beware that this option removes slaves that were registered through '
                          'other means, e.g. via the web UI.' )
        self.option( '--instance-type', '-t', metavar='TYPE',
                     default=os.environ.get( 'CGCLOUD_INSTANCE_TYPE', None ),
                     help='The type of EC2 instance to register the slave with, e.g. t1.micro, '
                          'm1.small, m1.medium, or m1.large etc. The value of the environment '
                          'variable CGCLOUD_INSTANCE_TYPE, if that variable is present, overrides '
                          'the default, an instance type appropriate for the role.' )

    def run_on_instance( self, options, master ):
        master.register_slaves( [ slave_cls
                                    for role, slave_cls in self.application.roles.iteritems( )
                                    for role_glob in options.slaves
                                    if fnmatch( role, role_glob ) ],
                                clean=options.clean,
                                instance_type=options.instance_type )


