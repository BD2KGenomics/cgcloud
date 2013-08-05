import logging

from devenv.build_master import BuildMaster
from util import Command, Application
from environment import Environment


DEBUG_LOG_FILE_NAME = 'cgcloud.log'

# After adding a new box class, add its name to the source list in the generator expression below
BOXES = dict( ( cls.role( ), cls) for cls in [ BuildMaster ] )


def main():
    app = Cgcloud( )
    app.add( ListCommand )
    app.add( SetupCommand )
    app.add( SshCommand )
    app.add( GetJenkinsKeyCommand )
    app.run( )


class Cgcloud( Application ):
    def __init__(self):
        super( Cgcloud, self ).__init__( )
        self.option( '--debug',
                     default=False, action='store_true',
                     help='Write debug log to %s in current directory.' % DEBUG_LOG_FILE_NAME )

    def prepare(self, options):
        if options.debug:
            logging.basicConfig( filename=DEBUG_LOG_FILE_NAME, level=logging.DEBUG )


class EnvironmentCommand( Command ):
    def run_in_env(self, options, env):
        raise NotImplementedError( )

    def __init__(self, application, ssh_key_required=True, **kwargs):
        defaults = Environment( )
        super( EnvironmentCommand, self ).__init__( application, **kwargs )
        self.option( '--ssh-key-name', '-k', metavar='KEY_NAME',
                     required=ssh_key_required, default=defaults.ssh_key_name,
                     help='The name of the SSH public key to inject into the instance. The '
                          'corresponding public key must be registered in EC2 under the given name '
                          'and a matching private key needs to be present locally.' )

        self.option( '--zone', '-z', metavar='AVAILABILITY_ZONE',
                     default=defaults.availability_zone, dest='availability_zone',
                     help='The name of the EC2 availability zone to place EC2 resources into, '
                          'e.g. us-east-1a, us-west-1b or us-west-2c etc. This argument implies '
                          'the AWS region to run in. ' )

        self.option( '--instance-type', '-t', metavar='TYPE',
                     default=defaults.instance_type,
                     help='The type of EC2 instance to launch for the box, e.g. of t1.micro, '
                          'm1.small, m1.medium, or m1.large etc.' )

        self.option( '--namespace', '-n', metavar='PREFIX',
                     default=defaults.namespace,
                     help='Optional prefix for box names, image names, etc. '
                          'Use this option to create a separate namespace in order to avoid '
                          'collisions, e.g. when running tests.' )

    def run(self, options):
        env = Environment( availability_zone=options.availability_zone,
                           instance_type=options.instance_type,
                           ssh_key_name=options.ssh_key_name,
                           namespace=options.namespace )
        return self.run_in_env( options, env )


class ListCommand( Command ):
    def __init__(self, app):
        super( ListCommand, self ).__init__( app, help='List known box names' )

    def run(self, options):
        print '\n'.join( BOXES.iterkeys( ) )


class BoxCommand( EnvironmentCommand ):
    def run_on_box(self, options, box):
        raise NotImplementedError( )

    def __init__(self, application, **kwargs):
        super( BoxCommand, self ).__init__( application, **kwargs )
        self.option( 'role',
                     metavar='ROLE',
                     help="The role name of the box to perform this command on. "
                          "Use the list command to show valid roles." )

    def run_in_env(self, options, env):
        role = options.role
        box_cls = BOXES.get( role )
        if box_cls is None: raise RuntimeError( "No such role: '%s'" % role )
        box = box_cls( env )
        return self.run_on_box( options, box )


class SetupCommand( BoxCommand ):
    def __init__(self, application):
        super( SetupCommand, self ).__init__( application,
                                              help='Create an EC2 instance of the specified box, '
                                                   'install OS and additional packages on it, '
                                                   'optionally create an AMI image of it, and/or '
                                                   'terminate it.' )
        self.option( '--image', '-I',
                     default=False, action='store_true',
                     help='Create an image of the box when setup is complete.' )

        self.option( '--update', '-U',
                     default=False, action='store_true',
                     help="Bring the package repository as well as any installed packages up to "
                          "date, i.e. do what on Ubuntu is achieved by doing "
                          "'sudo apt-get update ; sudo apt-get upgrade'." )

        self.begin_mutex( )

        self.option( '--terminate', '-T',
                     default=None, action='store_true',
                     help='Terminate the box when setup is complete. The default is to leave the '
                          'box running except when errors occur.' )

        self.option( '--never-terminate', '-N',
                     default=None, dest='terminate', action='store_false',
                     help='Never terminate the box, even after errors. This may be useful for '
                          'post-mortem analysis.' )

        self.end_mutex( )

    def run_on_box(self, options, box):
        try:
            box.create( )
            box.setup( options.update )
            if options.image:
                box.stop( )
                box.create_image( )
                if options.terminate is not True:
                    box.start( )
        except:
            if options.terminate is not False:
                box.terminate( wait=False )
            raise
        else:
            if options.terminate is True:
                box.terminate( )


class GetJenkinsKeyCommand( EnvironmentCommand ):
    def __init__(self, application):
        super( GetJenkinsKeyCommand, self ).__init__(
            application,
            ssh_key_required=False,
            help='Get a copy of the public key used by Jenkins to connect to slaves.' )

    def run_in_env(self, options, env):
        box = BuildMaster( env )
        box.adopt( )
        box.download_jenkins_key( )


class SshCommand( BoxCommand ):
    def __init__(self, application):
        super( SshCommand, self ).__init__(
            application,
            ssh_key_required=False,
            help='Start an interactive SSH session with the host.' )

    def run_on_box(self, options, box):
        box.adopt( )
        box.ssh( )

