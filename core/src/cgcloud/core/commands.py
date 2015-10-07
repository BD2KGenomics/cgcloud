from __future__ import print_function
from abc import abstractmethod
import argparse
import functools
import logging
from operator import itemgetter
import os
import re
import sys

from bd2k.util.exceptions import panic
from boto.ec2.connection import EC2Connection
from boto.ec2.blockdevicemapping import BlockDeviceType
from boto.ec2.group import Group

from fabric.operations import prompt

from cgcloud.core.instance_type import ec2_instance_types
from cgcloud.lib.util import Application
from cgcloud.lib.context import Context
from cgcloud.lib.util import UserError, Command
from cgcloud.core.box import Box

log = logging.getLogger( __name__ )


class ContextCommand( Command ):
    """
    A command that runs in a context. Contexts encapsulate the necessary environment for
    boxes to run in. The most important aspect of a context is its namespace. Namespaces group
    boxes and other resources into isolated groups.
    """

    @abstractmethod
    def run_in_ctx( self, options, ctx ):
        """
        Run this command in the given context.

        :type ctx: Context
        """
        raise NotImplementedError( )

    def __init__( self, application, **kwargs ):
        super( ContextCommand, self ).__init__( application, **kwargs )
        zone = os.environ.get( 'CGCLOUD_ZONE', None )
        self.option( '--zone', '-z', metavar='AVAILABILITY_ZONE',
                     default=zone, dest='availability_zone', required=not bool( zone ),
                     help='The name of the EC2 availability zone to operate in, e.g. us-east-1b, '
                          'us-west-1b or us-west-2c etc. This argument implies the AWS region to '
                          'run in. The value of the environment variable CGCLOUD_ZONE, '
                          'if that variable is present, determines the default.' )
        self.option( '--namespace', '-n', metavar='PREFIX',
                     default=os.environ.get( 'CGCLOUD_NAMESPACE', '/__me__/' ),
                     help='Optional prefix for naming EC2 resource like instances, images, '
                          'volumes, etc. Use this option to create a separate namespace in order '
                          'to avoid collisions, e.g. when running tests. The value of the '
                          'environment variable CGCLOUD_NAMESPACE, if that variable is present, '
                          'overrides the default. The string __me__ anywhere in the namespace '
                          'will be replaced by the name of the IAM user whose credentials are '
                          'used to issue requests to AWS. If the name of that IAM user contains '
                          'the @ character, anything after the first occurrance of that character '
                          'will be discarded before the substitution is done.' )

    def run( self, options ):
        zone = options.availability_zone
        namespace = options.namespace
        ctx = None
        try:
            ctx = Context( availability_zone=zone, namespace=namespace )
        except ValueError as e:
            raise UserError( cause=e )
        except:
            # print the namespace without __me__ substituted
            log.error( "An error occurred. Using zone '%s' and namespace '%s'", zone, namespace )
            raise
        else:
            # print the namespace with __me__ substituted
            log.info( "Using zone '%s' and namespace '%s'", ctx.availability_zone, ctx.namespace )
            return self.run_in_ctx( options, ctx )
        finally:
            if ctx is not None: ctx.close( )


class RoleCommand( ContextCommand ):
    """
    An abstract command that targets boxes of a particular role.  Note that there may be more
    than one box per role. To target a specific box, BoxCommand might be a better choice.
    """

    @abstractmethod
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
                     completer=self.completer,
                     help="The name of the role. Use the list-roles command to show possible "
                          "roles." )

    def completer( self, prefix, **kwargs ):
        return [ role for role in self.application.roles.iterkeys( ) if role.startswith( prefix ) ]

    def run_in_ctx( self, options, ctx ):
        role = options.role
        box_cls = self.application.roles.get( role )
        if box_cls is None: raise UserError( "No such role: '%s'" % role )
        box = box_cls( ctx )
        return self.run_on_box( options, box )


class ListCommand( RoleCommand ):
    """
    List the boxes performing a particular role.
    """

    def run_on_box( self, options, box ):
        for box in box.list( ):
            print( '{role}\t{ordinal}\t{private_ip}\t{ip}\t{id}\t{created_at}\t{state}'.format( **box ) )


# noinspection PyAbstractClass
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


class UserCommand( BoxCommand ):
    """
    A command that runs as a given user
    """

    def __init__( self, application, **kwargs ):
        super( UserCommand, self ).__init__( application, **kwargs )
        self.begin_mutex( )
        self.option( '--user', '--login', '-u', '-l', default=None,
                     help="Name of user to login as. The default depends on the role, for most "
                          "roles the default is the administrative user. Roles that define a "
                          "second less privileged application user will default to that user." )
        self.option( '--admin', '-a', default=False, action='store_true',
                     help="Force logging in as the administrative user." )
        self.end_mutex( )

    @staticmethod
    def _user( box, options ):
        return box.admin_account( ) if options.admin else options.user or box.default_account( )


class SshCommand( UserCommand ):
    """
    Start an interactive SSH session on a box.
    """

    def __init__( self, application ):
        super( SshCommand, self ).__init__( application )
        # FIXME: Create bug report about the following:
        # cgcloud.py ssh generic-ubuntu-saucy-box --zone us-east-1b
        # doesn't work since argparse puts '--zone us-east-1b' into the 'command' positional. This
        # is bad because ignoring the --zone option will cause cgcloud.py to use the default zone and
        # either use the wrong instance or complain about a missing instance. In either case it is
        # not apparent that --zone needs to precede the ROLE argument.
        # Changing nargs=argparse.REMAINDER to nargs='*' and invoking with
        # cgcloud.py ssh generic-ubuntu-saucy-box --zone us-east-1b -- ls -l
        # doesn't work for some other reason (probably a bug in argparse). It will complain about
        # cgcloud.py: error: unrecognized arguments: -- ls -l
        self.option( 'command', metavar='...', nargs=argparse.REMAINDER, default=[ ],
                     help="Additional arguments to pass to ssh. This can be anything that one "
                          "would normally pass to the ssh program excluding user name and host "
                          "but including, for example, the remote command to execute." )

    def run_on_box( self, options, box ):
        box.adopt( ordinal=options.ordinal )
        status = box.ssh( user=self._user( box, options ), command=options.command )
        if status != 0:
            sys.exit( status )


class RsyncCommand( UserCommand ):
    """
    Rsync to or from the box
    """

    def __init__( self, application ):
        super( RsyncCommand, self ).__init__( application )
        self.option( '--ssh-opts', '-e', default=None, metavar="OPTS",
                     help="Additional options to pass to ssh. Note that if OPTS starts with a "
                          "dash you must use the long option followed by an equal sign. For "
                          "example, to run ssh in verbose mode, use --ssh-opt=-v. If OPTS is to "
                          "include spaces, it must be quoted to prevent the shell from breaking "
                          "it up. So to run ssh in verbose mode and log to syslog, you would use "
                          "--ssh-opt='-v -y'." )
        self.option( 'args', metavar='...', nargs=argparse.REMAINDER, default=[ ],
                     help="Command line options for rsync(1). The remote path argument must be "
                          "prefixed with a colon. For example, 'cgcloud.py rsync foo -av "
                          ":bar .' would copy the file 'bar' from the home directory of the admin "
                          "user on the box 'foo' to the current directory on the local machine." )

    def run_on_box( self, options, box ):
        box.adopt( ordinal=options.ordinal )
        box.rsync( options.args, user=self._user( box, options ), ssh_opts=options.ssh_opts )


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


class ListImagesCommand( RoleCommand ):
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
        default_ec2_keypairs = os.environ.get( 'CGCLOUD_KEYPAIRS', '__me__' ).split( )
        self.option( '--keypairs', '-k', metavar='EC2_KEYPAIR_NAME',
                     dest='ec2_keypair_names', nargs='+',
                     default=default_ec2_keypairs,
                     help="The names of EC2 key pairs whose public key is to be to injected into "
                          "the box to facilitate SSH logins. For the first listed argument, "
                          "the so called primary key pair, a matching private key needs to be "
                          "present locally. All other arguments may use shell-style globs in "
                          "which case every key pair whose name matches one of the globs will be "
                          "deployed to the box. The cgcloudagent program that will typically be "
                          "installed on a box, keeps the deployed list of authorized keys up to "
                          "date in case matching keys are added or removed from EC2. The value of "
                          "the environment variable CGCLOUD_KEYPAIRS, if that variable is "
                          "present, overrides the default for this option. The string __me__ "
                          "anywhere in an argument will be substituted with the name of the IAM "
                          "user whose credentials are used to issue requests to AWS. An argument "
                          "beginning with a single @ will be looked up as the name of an IAM "
                          "user. If that user exists, the name will be used as the name of a key "
                          "pair. Otherwise an exception is raised. An argument beginning with @@ "
                          "will be looked up as an IAM group and the name of each user in that "
                          "group will be used as the name of a keypair. Note that the @ and @@ "
                          "substitutions depend on the convention that the user and the "
                          "corresponding key pair have the same name. They only require the "
                          "respective user or group to exist, while the key pair may be missing. "
                          "If such a missing key pair is later added, cgcloudagent will "
                          "automatically add that key pair's public to the list of SSH keys "
                          "authorized to login to the box. Shell-style globs can not be combined "
                          "with @ or @@ substitutions within one argument." )

        self.option( '--instance-type', '-t', metavar='TYPE',
                     default=os.environ.get( 'CGCLOUD_INSTANCE_TYPE', None ),
                     choices=ec2_instance_types.keys( ),
                     help='The type of EC2 instance to launch for the box, e.g. t2.micro, m3.small, '
                          'm3.medium, or m3.large etc. The value of the environment variable '
                          'CGCLOUD_INSTANCE_TYPE, if that variable is present, overrides the '
                          'default, an instance type appropriate for the role.' )

        self.option( '--virtualization-type', metavar='TYPE',
                     default=None, choices=Box.virtualization_types,
                     help="The virtualization type to be used for the instance. This affects the "
                          "choice of image (AMI) the instance is created from. The default depends "
                          "on the instance type, but generally speaking, 'hvm' will be used for "
                          "newer instance types." )

        self.option( '--spot-bid',
                     default=None, type=float,
                     help="The maximum price to pay for the specified instance type, in dollars "
                          "per hour as a floating point value, 1.23 for example. Only bids under "
                          "double the instance type's average price for the past week will be "
                          "accepted. By default on-demand instances are used. Note that some "
                          "instance types are not available on the spot market!")

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

    @abstractmethod
    def run_on_creation( self, box, options ):
        """
        Run on the given box after it was created.
        """
        raise NotImplementedError( )

    @abstractmethod
    def instance_options( self, options ):
        """
        Return dict with instance options to be passed box.create()
        """
        raise NotImplementedError( )

    def run_on_box( self, options, box ):
        try:
            resolve_me = functools.partial( box.ctx.resolve_me, drop_hostname=False )
            box.prepare( ec2_keypair_globs=map( resolve_me, options.ec2_keypair_names ),
                         instance_type=options.instance_type,
                         virtualization_type=options.virtualization_type,
                         **self.instance_options( options ) )
            box.create( wait_ready=True )
            self.run_on_creation( box, options )
        except:
            if options.terminate is not False:
                with panic( ):
                    box.terminate( wait=False )
            else:
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
                     help='The desired name of the EC2 key pair. The name should associate the '
                          'key with you in a way that it is obvious to other users in your '
                          'organization.  The string __me__ anywhere in the key pair name will be '
                          'replaced with the name of the IAM user whose credentials are used to '
                          'issue requests to AWS.' )

    def run_in_ctx( self, options, ctx ):
        with open( options.ssh_public_key ) as f:
            ssh_public_key = f.read( )
        try:
            ctx.register_ssh_pubkey( ec2_keypair_name=ctx.resolve_me( options.ec2_keypair_name,
                                                                      drop_hostname=False ),
                                     ssh_pubkey=ssh_public_key,
                                     force=options.force )
        except ValueError as e:
            raise UserError( cause=e )


class ListRolesCommand( Command ):
    """
    List available roles. A role is a template for a box. A box is a virtual machines in EC2,
    also known as an instance.
    """

    def run( self, options ):
        print( '\n'.join( self.application.roles.iterkeys( ) ) )


# noinspection PyAbstractClass
class ImageCommandMixin( Command ):
    """
    Any command that accepts an image ordinal or AMI ID.

    >>> app = Application()
    >>> class FooCmd( ImageCommandMixin ):
    ...     def run(self, options):
    ...         pass
    >>> cmd = FooCmd( app, '--foo', '-f' )
    >>> cmd.ordinal_or_ami_id( "bar" )
    Traceback (most recent call last):
    ...
    ValueError
    >>> cmd.ordinal_or_ami_id( "" )
    Traceback (most recent call last):
    ...
    ValueError
    >>> cmd.ordinal_or_ami_id( "-1")
    -1
    >>> cmd.ordinal_or_ami_id( "ami-4dcced7d")
    'ami-4dcced7d'
    >>> cmd.ordinal_or_ami_id( "ami-4dCCED7D")
    'ami-4dcced7d'
    >>> cmd.ordinal_or_ami_id( "amI-4dCCED7D")
    Traceback (most recent call last):
    ...
    ValueError
    >>> cmd.ordinal_or_ami_id( "ami-4dcced7")
    Traceback (most recent call last):
    ...
    ValueError
    >>> cmd.ordinal_or_ami_id( "ami-4dCCED7DD")
    Traceback (most recent call last):
    ...
    ValueError
    """
    ami_id_re = re.compile( r'^ami-([0-9a-fA-F]{8})$' )

    def ordinal_or_ami_id( self, s ):
        try:
            return int( s )
        except ValueError:
            if self.ami_id_re.match( s ):
                return s.lower( )
            else:
                raise ValueError( )

    def __init__( self, application, long_image_option, short_image_option ):
        super( ImageCommandMixin, self ).__init__( application )
        self.option( long_image_option, short_image_option, metavar='ORDINAL_OR_AMI_ID',
                     type=self.ordinal_or_ami_id, default=-1,  # default to the last one
                     help="An image ordinal, i.e. the index of an image in the list of images for "
                          "the given role, sorted by creation time. Use the list-images command "
                          "to print a list of images for a given role. If the ordinal is "
                          "negative, it will be converted to a positive ordinal by adding the "
                          "total number of images for this role. Passing -1, for example, "
                          "selects the most recently created image. Alternatively, an AMI ID, "
                          "e.g. 'ami-4dcced7d' can be passed in as well." )


class DeleteImageCommand( ImageCommandMixin, RoleCommand ):
    def __init__( self, application ):
        super( DeleteImageCommand, self ).__init__( application, '--image', '-i' )
        self.begin_mutex( )
        self.option( '--keep-snapshot', '-K',
                     default=False, action='store_true',
                     help="Do not delete the EBS volume snapshot associated with the given image. "
                          "This will leave an orphaned snapshot which should be removed at a "
                          "later time using the 'cgcloud cleanup' command." )
        self.option( '--quick', '-q', default=False, action='store_true',
                     help="Exit immediately after deregistration request has been made, "
                          "don't wait until the image is deregistered. Implies --keep-snapshot." )
        self.end_mutex( )

    def run_on_box( self, options, box ):
        box.delete_image( options.image,
                          wait=not options.quick,
                          delete_snapshot=not options.keep_snapshot )


class RecreateCommand( ImageCommandMixin, CreationCommand ):
    """
    Recreate a box from an image that was taken from an earlier incarnation of the box
    """

    def __init__( self, application ):
        super( RecreateCommand, self ).__init__( application, '--boot-image', '-i' )

    def instance_options( self, options ):
        return dict( image_ref=options.boot_image,
                     price=options.spot_bid)

    def run_on_creation( self, box, options ):
        pass

class ClusterCommand( RecreateCommand ):
    def __init__( self, application ):
        super( ClusterCommand, self ).__init__( application)

        self.option( '--num-slaves', '-s', metavar='NUM',
                     type=int, default=1,
                     help='The number of slaves to start.' )
        # We want --instance-type for the slaves and --master-instance-type for the master and we
        # want --master-instance-type to default to the value of --instance-type.
        super( ClusterCommand, self ).option(
            '--instance-type', '-t', metavar='TYPE', dest='slave_instance_type',
            default="t2.micro",
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
        self.option( '--master-on-demand',dest='master_on_demand', default=None, action='store_true',
                     help='Use this option to insure that the master instance will be an '
                          'on demand instance type, even if the spod-bid argument is passed. '
                          'Using this flag can create a cluster of spot slaves with an on demand '
                          'master.' )

    def run_on_box( self, options, box ):
        try:
            resolve_me = functools.partial( box.ctx.resolve_me, drop_hostname=False )
            box.prepare( ec2_keypair_globs=map( resolve_me, options.ec2_keypair_names ),
                         instance_type=options.instance_type,
                         virtualization_type=options.virtualization_type,
                         master_on_demand=options.master_on_demand,
                         **self.instance_options( options ) )
            box.create( wait_ready=True )
            self.run_on_creation( box, options )
        except:
            if options.terminate is not False:
                with panic( ):
                    box.terminate( wait=False )
            else:
                raise
        else:
            if options.terminate is True:
                box.terminate( )

    def option( self, *args, **kwargs ):
        option_name = args[ 0 ]
        if option_name == 'role':
            return
        elif option_name == '--instance-type':
            # Suppress the instance type option inherited from the parent so we can roll our own
            return
        super( ClusterCommand, self ).option( *args, **kwargs )

class CreateCommand( CreationCommand ):
    """
    Create a box performing the specified role, install an OS and additional packages on it and
    optionally create an AMI image of it.
    """

    def __init__( self, application ):
        super( CreateCommand, self ).__init__( application )
        self.option( '--boot-image', '-i', metavar='AMI_ID',
                     help='The AMI ID of the image from which to create the box. This argument is '
                          'optional and the default is determined automatically based on the '
                          'role. Typically, this option does not need to be used.' )
        self.option( '--no-agent',
                     default=False, action='store_true',
                     help="Don't install the cghub-cloud-agent package on the box. One "
                          "note-worthy effect of using this option this is that the SSH keys will "
                          "be installed initially, but not maintained over time." )
        self.option( '--create-image', '-I',
                     default=False, action='store_true',
                     help='Create an image of the box as soon as setup completes.' )
        # FIXME: Take a second look at this: Does it work. Is it necessary?
        self.option( '--upgrade', '-U',
                     default=False, action='store_true',
                     help="Bring the package repository as well as any installed packages up to "
                          "date, i.e. do what on Ubuntu is achieved by doing "
                          "'sudo apt-get update ; sudo apt-get upgrade'." )
    def instance_options( self, options ):
        return dict( image_ref=options.boot_image,
                     enable_agent=not options.no_agent,
                     price=options.spot_bid)

    def run_on_creation( self, box, options ):
        box.setup( upgrade_installed_packages=options.upgrade )
        if options.create_image:
            box.stop( )
            box.image( )
            if options.terminate is not True:
                box.start( )


class CleanupCommand( ContextCommand ):
    """
    Lists and optionally deletes unused AWS resources after prompting for confirmation.
    """

    def run_in_ctx( self, options, ctx ):
        self.cleanup_image_snapshots( ctx )
        self.cleanup_ssh_pubkeys( ctx )

    @staticmethod
    def cleanup_ssh_pubkeys( ctx ):
        unused_fingerprints = ctx.unused_fingerprints( )
        if unused_fingerprints:
            print( 'The following public keys in S3 are not referenced by any EC2 keypairs:' )
            for fingerprint in unused_fingerprints:
                print( fingerprint )
            if 'yes' == prompt( 'Delete these public keys from S3? (yes/no)', default='no' ):
                ctx.delete_fingerprints( unused_fingerprints )
        else:
            print( 'No orphaned public keys in S3.' )

    @staticmethod
    def cleanup_image_snapshots( ctx ):
        unused_snapshots = ctx.unused_snapshots( )
        if unused_snapshots:
            print( 'The following snapshots are not referenced by any images:' )
            for snapshot_id in unused_snapshots:
                print( snapshot_id )
            if 'yes' == prompt( 'Delete these snapshots? (yes/no)', default='no' ):
                ctx.delete_snapshots( unused_snapshots )
        else:
            print( 'No unused EBS volume snapshots in EC2.' )


class ResetSecurityCommand( ContextCommand ):
    def run_in_ctx( self, options, ctx ):
        message = ('Do you really want to delete all IAM instance profiles, IAM roles and EC2 '
                   'security groups in namespace %s and its children? Although these resources '
                   'will be created on-the-fly for newly created boxes, existing boxes will '
                   'likely be impacted negatively.' % ctx.namespace)
        if 'yes' == prompt( message + ' (yes/no)', default='no' ):
            ctx.reset_namespace_security( )


class UpdateInstanceProfile( BoxCommand ):
    """
    Update the instance profile and associated IAM roles for a given role.

    This command ensures that a box of this role has accurate and up-to-date privileges to
    interact with AWS resources. The instance profile is updated whenever a box is created. Use
    this command to update the instance profile for existing boxes.
    """

    def run_on_box( self, options, box ):
        box.adopt( ordinal=options.ordinal )
        box._get_instance_profile_arn( )
