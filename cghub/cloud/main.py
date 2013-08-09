import logging
import sys
from operator import itemgetter

import boto
from cghub.cloud.generic_boxes import GenericCentos6Box, GenericCentos5Box, GenericUbuntuPreciseBox

from devenv.build_master import BuildMaster

from box import Box
from util import Command, Application
from environment import Environment


DEBUG_LOG_FILE_NAME = 'cgcloud.log'

# After adding a new box class, add its name to the source list in the generator expression below
BOXES = dict( ( cls.role( ), cls) for cls in [
    BuildMaster,
    GenericCentos6Box,
    GenericCentos5Box,
    GenericUbuntuPreciseBox ] )


def main():
    app = Cgcloud( )
    app.add( ListRolesCommand )
    app.add( CreateCommand )
    app.add( StartCommand )
    app.add( StopCommand )
    app.add( RebootCommand )
    app.add( TerminateCommand )
    app.add( ShowCommand )
    app.add( SshCommand )
    app.add( ListBoxesCommand )
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

    def __init__(self, application, **kwargs):
        defaults = Environment( )
        super( EnvironmentCommand, self ).__init__( application, **kwargs )
        self.option( '--zone', '-z', metavar='AVAILABILITY_ZONE',
                     default=defaults.availability_zone, dest='availability_zone',
                     help='The name of the EC2 availability zone to place EC2 resources into, '
                          'e.g. us-east-1a, us-west-1b or us-west-2c etc. This argument implies '
                          'the AWS region to run in. ' )

        self.option( '--namespace', '-n', metavar='PREFIX',
                     default=defaults.namespace,
                     help='Optional prefix for naming EC2 resource like instances, images, volumes, '
                          'etc. Use this option to create a separate namespace in order to avoid '
                          'collisions, e.g. when running tests. The default represents the root '
                          'namespace.' )

    def run(self, options):
        env = Environment( availability_zone=options.availability_zone,
                           namespace=options.namespace )
        return self.run_in_env( options, env )


class ListRolesCommand( Command ):
    def __init__(self, app):
        super( ListRolesCommand, self ).__init__( app, help='List available roles.' )

    def run(self, options):
        print '\n'.join( BOXES.iterkeys( ) )


class RoleCommand( EnvironmentCommand ):
    def run_on_box(self, options, box):
        raise NotImplementedError( )

    def __init__(self, application, **kwargs):
        super( RoleCommand, self ).__init__( application, **kwargs )
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


class InstanceCommand( RoleCommand ):
    def __init__(self, application, **kwargs):
        super( InstanceCommand, self ).__init__( application, **kwargs )
        self.option( '--ordinal', '-o', default=None, type=int,
                     help='Selects an individual box among the boxes performing the same role. '
                          'The ordinal is an zero-based index into the list of all boxes performing '
                          'the given role, sorted by creation time. This means that the ordinal of '
                          'a box is not fixed, it may change if another box performing the same '
                          'role is terminated. This option is only required if there are multiple '
                          'boxes performing the same role.' )


class CreateCommand( RoleCommand ):
    def __init__(self, application):
        super( CreateCommand, self ).__init__( application,
                                               help='Create an EC2 instance of the specified box, '
                                                    'install OS and additional packages on it, '
                                                    'optionally create an AMI image of it, and/or '
                                                    'terminate it.' )
        self.option( '--ssh-key-name', '-k', metavar='KEY_NAME',
                     required=True,
                     help='The name of the SSH public key to inject into the instance. The '
                          'corresponding public key must be registered in EC2 under the given name '
                          'and a matching private key needs to be present locally.' )

        self.option( '--instance-type', '-t', metavar='TYPE',
                     default='t1.micro',
                     help='The type of EC2 instance to launch for the box, e.g. of t1.micro, '
                          'm1.small, m1.medium, or m1.large etc.' )

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
            box.create( instance_type=options.instance_type,
                        ssh_key_name=options.ssh_key_name )
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
            help='Get a copy of the public key used by Jenkins to connect to slaves.' )

    def run_in_env(self, options, env):
        box = BuildMaster( env )
        box.adopt( ordinal=options.ordinal )
        box.download_jenkins_key( )


class SshCommand( InstanceCommand ):
    def __init__(self, application):
        super( SshCommand, self ).__init__(
            application,
            help='Start an interactive SSH session with the host.' )

    def run_on_box(self, options, box):
        box.adopt( ordinal=options.ordinal )
        box.ssh( )


class LifecycleCommand( InstanceCommand ):
    def __init__(self, application, **kwargs):
        super( LifecycleCommand, self ).__init__(
            application,
            help='Transition the box between states.' )

    def run_on_box(self, options, box):
        box.adopt( ordinal=options.ordinal, wait_ready=False )
        getattr( box, self.name( ) )( )


class StartCommand( LifecycleCommand ): pass


class StopCommand( LifecycleCommand ): pass


class RebootCommand( LifecycleCommand ): pass


class TerminateCommand( LifecycleCommand ): pass


class ShowCommand( InstanceCommand ):
    def __init__(self, application):
        super( ShowCommand, self ).__init__( application,
                                             help='Display the attributes of the EC2 instance' )

    def print_object(self, o, visited=set( ), depth=1):
        _id = id( o )
        if not _id in visited:
            visited.add( _id )
            self.print_dict( o.__dict__, visited, depth )
            visited.remove( _id )
        if depth == 1: sys.stdout.write( '\n' )

    def print_dict(self, d, visited, depth):
        for k, v in sorted( d.iteritems( ), key=itemgetter( 0 ) ):
            k = str( k )
            if k[ 0:1 ] != '_' \
                and k != 'connection' \
                and not isinstance( v, boto.ec2.connection.EC2Connection ):
                sys.stdout.write( '\n%s%s: ' % ('\t' * depth, k) )
                if isinstance( v, basestring ):
                    sys.stdout.write( v.strip( ) )
                elif hasattr( v, 'iteritems' ):
                    self.print_dict( v, visited, depth + 1 )
                elif hasattr( v, '__iter__' ):
                    self.print_dict( dict( enumerate( v ) ), visited, depth + 1 )
                elif isinstance( v, boto.ec2.blockdevicemapping.BlockDeviceType ) \
                    or isinstance( v, boto.ec2.group.Group ):
                    self.print_object( v, visited, depth + 1 )
                else:
                    sys.stdout.write( repr( v ) )

    def run_on_box(self, options, box):
        box.adopt( ordinal=options.ordinal, wait_ready=False )
        self.print_object( box.get_instance( ) )


class ListBoxesCommand( RoleCommand ):
    def run_on_box(self, options, box):
        for instance in box.list( ):
            print( '{role} {ordinal} {id} {created_at}'.format( **instance ) )