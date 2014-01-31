from fnmatch import fnmatch

from cghub.cloud.core import BoxCommand


class RegisterSlaves( BoxCommand ):
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
        self.option( '--clean', '-c', default=False, action='store_true',
                     help='Clear the list of slaves in the master before registering new slaves. '
                          'Beware that this option removes slaves that were registered through '
                          'other means, e.g. via the web UI.' )

    def run_on_box( self, options, master ):
        master.adopt( ordinal=options.ordinal )
        master.register_slaves( [ slave_cls
                                    for role, slave_cls in self.application.boxes.iteritems( )
                                    for role_glob in options.slaves
                                    if fnmatch( role, role_glob ) ], clean=options.clean )


