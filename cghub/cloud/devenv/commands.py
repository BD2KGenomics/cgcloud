from fnmatch import fnmatch

from cghub.cloud import BoxCommand


class GetKeys( BoxCommand ):
    """
    Get a copy of the public keys that identify users on the box.
    """

    def run_on_box(self, options, box):
        box.adopt( ordinal=options.ordinal )
        box.get_keys( )


class RegisterSlaves( BoxCommand ):
    """
    Adds the specified slave images to Jenkins' EC2 configuration on the given master to the
    extend that the specified master can spawn later these slaves to run builds as needed.
    """

    def __init__(self, application, **kwargs):
        super( RegisterSlaves, self ).__init__( application, **kwargs )
        self.option( '--slaves', '-s', metavar='ROLE_GLOB',
                     nargs='*', default=[ '*-jenkins-slave' ],
                     help='A list of roles names or role name patterns (shell globs) of the '
                          'slaves that should be added to the Jenkins config. For each matching '
                          'slave, the most recently created image will be registered using the '
                          'recommended instance type for that slave.' )

    def run_on_box(self, options, master):
        master.adopt( ordinal=options.ordinal )
        master.register_slaves( [ slave_cls
            for role, slave_cls in self.application.boxes.iteritems( )
            for role_glob in options.slaves
            if fnmatch( role, role_glob ) ] )


