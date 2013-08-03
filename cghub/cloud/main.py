import logging

from cghub.cloud.devenv.build_master import BuildMaster
from cghub.cloud.util import Command, Application
from ec2_options import Ec2Options


# After adding a new box class, add its name to the source list in the generator expression below
BOXES = dict( ( cls.name( ), cls) for cls in [ BuildMaster ] )


def main():
    app = Cgcloud( )
    app.add( ListCommand )
    app.add( SetupCommand )
    app.add( GetJenkinsKeyCommand )
    app.run( )


class Cgcloud( Application ):
    def __init__(self):
        super( Cgcloud, self ).__init__( )
        self.option( '--debug', default='False', action='store_true' )

    def prepare(self, options):
        if options.debug:
            logging.basicConfig( filename="cgcloud.log", level=logging.DEBUG )


class Ec2Command( Command ):
    def __init__(self, application, **kwargs):
        super( Ec2Command, self ).__init__( application, **kwargs )
        self.option( '--ssh-key-name', '-k', metavar='KEY_NAME',
                     required=True,
                     help='The name of the SSH public key to inject into the instance. The '
                          'corresponding public key must be registered in EC2 under the given name '
                          'and a matching private key needs to be present locally.' )

        self.option( '--zone', '-z', metavar='AVAILABILITY_ZONE',
                     default='us-west-1b', dest='availability_zone',
                     help='The name of the EC2 availability zone to place EC2 resources into, '
                          'e.g. us-east-1a, us-west-1b or us-west-2c etc. This argument implies '
                          'the AWS region to run in. ' )

        self.option( '--instance-type', '-t', metavar='TYPE',
                     default='t1.micro',
                     help='The type of EC2 instance to launch for the box, e.g. of t1.micro, '
                          'm1.small, m1.medium, or m1.large etc.' )

    def ec2_options(self, options):
        return Ec2Options(
            availability_zone=options.availability_zone,
            instance_type=options.instance_type,
            ssh_key_name=options.ssh_key_name )


class ListCommand( Command ):
    def __init__(self, app):
        super( ListCommand, self ).__init__( app, help='List known box names' )

    def run(self, options):
        print '\n'.join( BOXES.iterkeys( ) )


class SetupCommand( Ec2Command ):
    def __init__(self, application):
        super( SetupCommand, self ).__init__( application,
                                              help='Build a box and optionally image it' )
        self.option( 'box_name', metavar='BOX' )
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

    def run(self, options):
        box_name = options.box_name
        box_cls = BOXES.get( box_name )
        if box_cls is None:
            raise RuntimeError( "No such box name: '%s'" % box_name )
        box_cls.create_and_setup( self.ec2_options( options ),
                                  update=options.update,
                                  image=options.image,
                                  terminate=options.terminate )


class GetJenkinsKeyCommand( Ec2Command ):
    def __init__(self, application, **kwargs):
        super( GetJenkinsKeyCommand, self ).__init__(
            application,
            help='Get a copy of the public key used by Jenkins to connect to slaves.' )

    def run(self, options):
        BuildMaster.download_jenkins_key( self.ec2_options( options ) )
