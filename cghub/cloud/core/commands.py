import argparse
from operator import itemgetter
import os
import sys

from boto.ec2.connection import EC2Connection
from boto.ec2.blockdevicemapping import BlockDeviceType
from boto.ec2.group import Group

from cghub.cloud.lib.context import Context
from cghub.cloud.lib.util import UserError, Command


class ContextCommand( Command ):
    """
    A command that runs in a context. Contexts encapsulate the necessary environment for
    boxes to run in. The most important aspect of a context is its namespace. Namespaces isolate
    boxes and other resources into separate groups.
    """

    def run_in_ctx( self, options, ctx ):
        """
        Run this command in the given context.

        :type ctx: Context
        """
        raise NotImplementedError( )

    def __init__( self, application, **kwargs ):
        super( ContextCommand, self ).__init__( application, **kwargs )
        self.option( '--zone', '-z', metavar='AVAILABILITY_ZONE',
                     default=os.environ.get( 'CGCLOUD_ZONE', 'us-west-1b' ),
                     dest='availability_zone',
                     help='The name of the EC2 availability zone to operate in, e.g. us-east-1a, '
                          'us-west-1b or us-west-2c etc. This argument implies the AWS region to '
                          'run in. The value of the environment variable CGCLOUD_ZONE, '
                          'if that variable is present, overrides the default.' )
        self.option( '--namespace', '-n', metavar='PREFIX',
                     default=os.environ.get( 'CGCLOUD_NAMESPACE', '/__me__/' ),
                     help='Optional prefix for naming EC2 resource like instances, images, '
                          'volumes, etc. Use this option to create a separate namespace in order '
                          'to avoid collisions, e.g. when running tests. The default represents '
                          'the root namespace. The value of the environment variable '
                          'CGCLOUD_NAMESPACE, if that variable is present, overrides the default. '
                          'The string __me__ anywhere in the namespace will be replaced by the '
                          'name of the IAM user whose credentials are used to issue requests to '
                          'AWS.' )

    def run( self, options ):
        ctx = None
        try:
            ctx = Context( availability_zone=options.availability_zone,
                           namespace=options.namespace )
        except ValueError as e:
            raise UserError( cause=e )
        else:
            return self.run_in_ctx( options, ctx )
        finally:
            if ctx is not None: ctx.close( )


class RoleCommand( ContextCommand ):
    """
    An abstract command that targets boxes of a particular role.  Note that there may be more
    than one box per role. To target a specific box, BoxCommand might be a better choice.
    """

    def run_on_box( self, options, box ):
        """
        Execute this command using the specified parsed command line options on the specified box.

        :param options: the parsed command line options
        :type options: dict
        :param box: the box to operate on
        :type box: Box
        """
        raise NotImplementedError( )

    def __init__( self, application, **kwargs ):
        super( RoleCommand, self ).__init__( application, **kwargs )
        self.option( 'role',
                     metavar='ROLE',
                     help="The name of the role. Use the list-roles command to show possible "
                          "roles." )

    def run_in_ctx( self, options, ctx ):
        role = options.role
        box_cls = self.application.boxes.get( role )
        if box_cls is None: raise UserError( "No such role: '%s'" % role )
        box = box_cls( ctx )
        return self.run_on_box( options, box )


class ListCommand( RoleCommand ):
    """
    List the boxes performing a particular role.
    """

    def run_on_box( self, options, box ):
        for box in box.list( ):
            print( '{role}\t{ordinal}\t{ip}\t{id}\t{created_at}\t{state}'.format( **box ) )


class BoxCommand( RoleCommand ):
    def __init__( self, application, **kwargs ):
        super( BoxCommand, self ).__init__( application, **kwargs )
        self.option( '--ordinal', '-o', default=-1, type=int,
                     help='Selects an individual box from the list of boxes performing the '
                          'specified role. The ordinal is a zero-based index into the list of all '
                          'boxes performing the specified role, sorted by creation time. This '
                          'means that the ordinal of a box is not fixed, it may change if another '
                          'box performing the specified role is terminated. If the ordinal is '
                          'negative, it will be converted to a positive ordinal by adding the '
                          'number of boxes performing the specified role. Passing -1, for example, '
                          'selects the most recently created box.' )


class SshCommand( BoxCommand ):
    """
    Start an interactive SSH session on a box.
    """

    def __init__( self, application ):
        super( SshCommand, self ).__init__( application )
        self.option( '--user', '--login', '-u', '-l', default=None,
                     help="Name of user to login as." )
        self.option( '--command', '-c', nargs=argparse.REMAINDER, default=[ ],
                     help="Additional arguments to pass to ssh. This can be anything that you "
                          "would pass to SSH with the exception of user name or host." )

    def run_on_box( self, options, box ):
        box.adopt( ordinal=options.ordinal )
        i = next( ( i for i, v in enumerate( options.command ) if not v.startswith( '-' ) ),
                  len( options.command ) )
        box.ssh( options=options.command[ :i ], user=options.user, command=options.command[ i: ] )


class ImageCommand( BoxCommand ):
    """
    Create an AMI image of a box performing a given role. The box must be stopped.
    """

    def run_on_box( self, options, box ):
        box.adopt( ordinal=options.ordinal, wait_ready=False )
        box.image( )


class ShowCommand( BoxCommand ):
    """
    Display the EC2 attributes of the box.
    """

    def print_object( self, o, visited=set( ), depth=1 ):
        _id = id( o )
        if not _id in visited:
            visited.add( _id )
            self.print_dict( o.__dict__, visited, depth )
            visited.remove( _id )
        if depth == 1: sys.stdout.write( '\n' )

    def print_dict( self, d, visited, depth ):
        for k, v in sorted( d.iteritems( ), key=itemgetter( 0 ) ):
            k = str( k )
            if k[ 0:1 ] != '_' \
                and k != 'connection' \
                and not isinstance( v, EC2Connection ):
                sys.stdout.write( '\n%s%s: ' % ('\t' * depth, k) )
                if isinstance( v, str ):
                    sys.stdout.write( v.strip( ) )
                if isinstance( v, unicode ):
                    sys.stdout.write( v.encode( 'utf8' ).strip( ) )
                elif hasattr( v, 'iteritems' ):
                    self.print_dict( v, visited, depth + 1 )
                elif hasattr( v, '__iter__' ):
                    self.print_dict( dict( enumerate( v ) ), visited, depth + 1 )
                elif isinstance( v, BlockDeviceType ) \
                    or isinstance( v, Group ):
                    self.print_object( v, visited, depth + 1 )
                else:
                    sys.stdout.write( repr( v ) )

    def run_on_box( self, options, box ):
        box.adopt( ordinal=options.ordinal, wait_ready=False )
        self.print_object( box.get_instance( ) )


class LifecycleCommand( BoxCommand ):
    """
    Transition a box into a particular state.
    """

    def adopt( self, box, options ):
        box.adopt( ordinal=options.ordinal, wait_ready=False )

    def run_on_box( self, options, box ):
        self.adopt( box, options )
        getattr( box, self.name( ) )( )


class StopCommand( LifecycleCommand ):
    """
    Stop the box, ie. bring it from the running state to the stopped state.
    """
    pass


class RebootCommand( LifecycleCommand ):
    """
    Stop the box, then start it again.
    """
    pass


class TerminateCommand( LifecycleCommand ):
    """
    Terminate the box, ie. delete it permanently.
    """

    def __init__( self, application, **kwargs ):
        super( TerminateCommand, self ).__init__( application, **kwargs )
        self.option( '--quick', '-q', default=False, action='store_true',
                     help="Exit immediately after termination request has been made, don't wait "
                          "until the box is terminated." )

    def run_on_box( self, options, box ):
        self.adopt( box, options )
        box.terminate( wait=not options.quick )


class StartCommand( LifecycleCommand ):
    """
    Start the box, ie. bring it from the stopped state to the running state.
    """
    pass


class ListImages( RoleCommand ):
    """
    List the AMI images that were created from boxes performing a particular role.
    """

    def run_on_box( self, options, box ):
        for ordinal, image in enumerate( box.list_images( ) ):
            print( '{name}\t{ordinal}\t{id}\t{state}'.format( ordinal=ordinal,
                                                              **image.__dict__ ) )


class CreationCommand( RoleCommand ):
    def __init__( self, application ):
        super( CreationCommand, self ).__init__( application )
        default_ec2_keypairs = os.environ.get( 'CGCLOUD_KEYPAIRS', '__me__ *' ).split( )
        self.option( '--keypairs', '-k', metavar='EC2_KEYPAIR_NAME',
                     dest='ec2_keypair_names', nargs='+',
                     default=default_ec2_keypairs,
                     help='The names of EC2 key pairs whose public key is to be to injected into '
                          'the box to facilitate SSH logins. For the first listed argument, '
                          'the so called primary key pair, a matching private key needs to be '
                          'present locally. All other arguments may use shell-style globs in '
                          'which case every key pair whose name matches one of the globs will be '
                          'deployed to the box. The cgcloud agent that will typically be '
                          'installed on a box, will keep the deployed list of authorized keys up '
                          'to date in case matching keys are added or removed from EC2. The value '
                          'of the environment variable CGCLOUD_KEYPAIRS, if that variable is '
                          'present, overrides the default. The string __me__ anywhere in a key '
                          'pair name will be replaced with the name of the IAM user whose '
                          'credentials are used to issue requests to AWS.' )

        self.option( '--instance-type', '-t', metavar='TYPE',
                     default=os.environ.get( 'CGCLOUD_INSTANCE_TYPE', None ),
                     help='The type of EC2 instance to launch for the box, e.g. t1.micro, m1.small, '
                          'm1.medium, or m1.large etc. The value of the environment variable '
                          'CGCLOUD_INSTANCE_TYPE, if that variable is present, overrides the '
                          'default, an instance type appropriate for the role.' )

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

    def run_on_creation( self, box, options ):
        """
        Run on the given box after it was created.
        """
        raise NotImplementedError( )

    def run_on_box( self, options, box ):
        try:
            box.create( ec2_keypair_globs=map( box.ctx.resolve_me, options.ec2_keypair_names ),
                        instance_type=options.instance_type,
                        boot_image=options.boot_image )
            self.run_on_creation( box, options )
        except:
            if options.terminate is not False:
                box.terminate( wait=False )
            raise
        else:
            if options.terminate is True:
                box.terminate( )


class RegisterKeyCommand( ContextCommand ):
    """
    Upload an OpenSSH public key for future injection into boxes. The public key will be imported
    into EC2 as a keypair and stored verbatim in S3.
    """

    def __init__( self, application, **kwargs ):
        super( RegisterKeyCommand, self ).__init__( application, **kwargs )
        self.option( 'ssh_public_key', metavar='KEY_FILE',
                     help='Path of file containing the SSH public key to upload to the EC2 '
                          'keypair.' )
        self.option( '--force', '-F', default=False, action='store_true',
                     help='Overwrite potentially existing EC2 key pair' )
        self.option( '--keypair', '-k', metavar='NAME',
                     dest='ec2_keypair_name', default='__me__',
                     help='The desired name of the EC2 key pair. The name should associate '
                          'the key with you in a way that it is obvious to other users in '
                          'your organization.  The string __me__ anywhere in the key pair name '
                          'will be replaced with the name of the IAM user whose credentials are '
                          'used to issue requests to AWS.' )

    def run_in_ctx( self, options, ctx ):
        with open( options.ssh_public_key ) as f:
            ssh_public_key = f.read( )
        ctx.register_ssh_pubkey( ec2_keypair_name=ctx.resolve_me( options.ec2_keypair_name ),
                                 ssh_pubkey=ssh_public_key,
                                 force=options.force )


class ListRolesCommand( Command ):
    """
    List available roles. A role is a template for a box. A box is a virtual machines in EC2,
    also known as an instance.
    """

    def run( self, options ):
        print '\n'.join( self.application.boxes.iterkeys( ) )


class RecreateCommand( CreationCommand ):
    """
    Recreate a box from an image that was taken from an earlier incarnation of the box
    """

    def __init__( self, application ):
        super( RecreateCommand, self ).__init__( application )
        self.option( '--boot-image', '-i', metavar='ORDINAL',
                     type=int, default=-1, # default to the last one
                     help='An image ordinal, i.e. the index of an image in the list of images '
                          'created from previous incarnations performing the given role, '
                          'sorted by creation time. Use the list-images command to see a list of '
                          'images. If the ordinal is negative, it will be converted to a positive '
                          'ordinal by adding number of images created from boxes performing the '
                          'specified role. Passing -1, for example, selects the most recently '
                          'created box.If the image ordinal is negative, it will be subtracted '
                          'from the number of images created from boxes performing the specified '
                          'role. Passing -1, for example, selects image that was created most '
                          'recently.' )

    def run_on_creation( self, box, options ):
        pass


class CreateCommand( CreationCommand ):
    """
    Create a box performing the specified role, install an OS and additional packages on it and
    optionally create an AMI image of it.
    """

    def __init__( self, application ):
        super( CreateCommand, self ).__init__( application )
        self.option( '--boot-image', '-i', metavar='IMAGE_ID',
                     help='An image ID (aka AMI ID) from which to create the box. This is argument '
                          'optional and the default is determined automatically based on the role.' )
        self.option( '--image', '-I',
                     default=False, action='store_true',
                     help='Create an image of the box when setup is complete.' )
        self.option( '--update', '-U',
                     default=False, action='store_true',
                     help="Bring the package repository as well as any installed packages up to "
                          "date, i.e. do what on Ubuntu is achieved by doing "
                          "'sudo apt-get update ; sudo apt-get upgrade'." )

    def run_on_creation( self, box, options ):
        box.setup( options.update )
        if options.image:
            box.stop( )
            box.image( )
            if options.terminate is not True:
                box.start( )

