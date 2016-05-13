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
from bd2k.util.expando import Expando
from bd2k.util.iterables import concat
from boto.ec2.connection import EC2Connection
from boto.ec2.blockdevicemapping import BlockDeviceType
from boto.ec2.group import Group
from fabric.operations import prompt
from cgcloud.lib.ec2 import ec2_instance_types
from cgcloud.lib.util import Application, heredoc
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
        self.default_namespace = os.environ.get( 'CGCLOUD_NAMESPACE', '/__me__/' )
        self.default_zone = os.environ.get( 'CGCLOUD_ZONE', None )
        super( ContextCommand, self ).__init__( application, **kwargs )

        self.option( '--zone', '-z', metavar='ZONE',
                     default=self.default_zone, dest='availability_zone',
                     required=not bool( self.default_zone ),
                     help=heredoc( """The name of the EC2 availability zone to operate in,
                     e.g. us-east-1b, us-west-1b or us-west-2c etc. This argument implies the AWS
                     region to run in. The value of the environment variable CGCLOUD_ZONE,
                     if that variable is present, determines the default.""" ) )

        self.option( '--namespace', '-n', metavar='PREFIX', default=self.default_namespace,
                     help=heredoc( """Optional prefix for naming EC2 resource like instances,
                     images, volumes, etc. Use this option to create a separate namespace in
                     order to avoid collisions, e.g. when running tests. The value of the
                     environment variable CGCLOUD_NAMESPACE, if that variable is present,
                     overrides the default. The string __me__ anywhere in the namespace will be
                     replaced by the name of the IAM user whose credentials are used to issue
                     requests to AWS. If the name of that IAM user contains the @ character,
                     anything after the first occurrance of that character will be discarded
                     before the substitution is done.""" ) )

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
    than one box per role. To target a specific box, InstanceCommand might be a better choice.
    """

    def __init__( self, application, **kwargs ):
        super( RoleCommand, self ).__init__( application, **kwargs )
        self.option( 'role', metavar='ROLE', completer=self.completer,
                     help=heredoc( """The name of the role. Use the list-roles command to show
                     all available roles.""" ) )

    # noinspection PyUnusedLocal
    def completer( self, prefix, **kwargs ):
        return [ role for role in self.application.roles.iterkeys( ) if role.startswith( prefix ) ]

    def run_in_ctx( self, options, ctx ):
        role = self.application.roles.get( options.role )
        if role is None: raise UserError( "No such role: '%s'" % options.role )
        return self.run_on_role( options, ctx, role )

    @abstractmethod
    def run_on_role( self, options, ctx, role ):
        """
        :type options: dict
        :type ctx: Context
        :type role: type[Box]
        """
        raise NotImplementedError( )


class BoxCommand( RoleCommand ):
    """
    An abstract command that runs on a box, i.e. an instance of a role class.
    """

    def run_on_role( self, options, ctx, role ):
        box = role( ctx )
        return self.run_on_box( options, box )

    @abstractmethod
    def run_on_box( self, options, box ):
        """
        Execute this command using the specified parsed command line options on the specified box.

        :type options: dict
        :type box: Box
        """
        raise NotImplementedError( )

    def list( self, boxes, print_header=True ):
        columns = """
            cluster_name
            role_name
            cluster_ordinal
            private_ip_address
            ip_address
            instance_id
            instance_type
            launch_time
            state
            zone""".split( )

        if print_header:
            header = list( columns )
            header.insert( 2, 'ordinal' )
            print( '\t'.join( header ) )

        for ordinal, box in enumerate( boxes ):
            row = [ getattr( box, column ) for column in columns ]
            row.insert( 2, ordinal )
            print( '\t'.join( str( column ) for column in row ) )


class InstanceCommand( BoxCommand ):
    """
    A command that runs on a box bound to a specific EC2 instance.
    """

    def __init__( self, application, **kwargs ):
        super( InstanceCommand, self ).__init__( application, **kwargs )
        self.option( '--cluster-name', '-c', metavar='NAME',
                     help=heredoc( """This option can be used to restrict the selection to boxes
                     that are part of a cluster of the given name. Boxes that are not part of a
                     cluster use their own instance id as the cluster name.""" ) )
        self.begin_mutex()
        self.option( '--ordinal', '-o', default=-1, type=int,
                     help=heredoc( """Selects an individual box from the list of boxes performing
                     the specified role in a cluster of the given name. The ordinal is a
                     zero-based index into the list of all boxes performing the specified role,
                     sorted by creation time. This means that the ordinal of a box is not fixed,
                     it may change if another box performing the specified role is terminated. If
                     the ordinal is negative, it will be converted to a positive ordinal by
                     adding the number of boxes performing the specified role. Passing -1,
                     for example, selects the most recently created box.""" ) )
        self.option( '--instance-id', '-I', default=None, type=str,
                     help=heredoc( """Selects an individual instance. When combined with
                     --cluster-name, the specified instance needs to belong to a cluster of the
                     specified name or an error will be raised.""" ) )
        self.end_mutex()

    wait_ready = True

    def run_on_box( self, options, box ):
        if options.instance_id:
            # Mutual exclusivity is enforced by argparse but we need to unset the default value
            # for the mutual exclusive options.
            options.ordinal = None
        box.bind( ordinal=options.ordinal,
                  cluster_name=options.cluster_name,
                  wait_ready=self.wait_ready,
                  instance_id=options.instance_id )
        self.run_on_instance( options, box )

    @abstractmethod
    def run_on_instance( self, options, box ):
        raise NotImplementedError( )


class ListCommand( BoxCommand ):
    """
    List the boxes performing a particular role.
    """

    def __init__( self, application ):
        super( ListCommand, self ).__init__( application )
        self.option( '--cluster-name', '-c', metavar='NAME',
                     help='Only list boxes belonging to a cluster of the given name.' )

    def run_on_box( self, options, box ):
        boxes = box.list( cluster_name=options.cluster_name )
        self.list( boxes )


class UserCommandMixin( Command ):
    """
    A command that runs as a given user
    """

    def __init__( self, application, **kwargs ):
        super( UserCommandMixin, self ).__init__( application, **kwargs )
        self.begin_mutex( )
        self.option( '--login', '-l', default=None, metavar='USER', dest='user',
                     help=heredoc( """Name of user to login as. The default depends on the role,
                     for most roles the default is the administrative user. Roles that define a
                     second less privileged application user will default to that user. Can't be
                     used together with -a, --admin.""" ) )
        self.option( '--admin', '-a', default=False, action='store_true',
                     help=heredoc( """Force logging in as the administrative user. Can't be used
                     together with -l, --login.""" ) )
        self.end_mutex( )

    @staticmethod
    def _user( box, options ):
        return box.admin_account( ) if options.admin else options.user or box.default_account( )


class SshCommandMixin( UserCommandMixin ):
    def __init__( self, application ):
        super( SshCommandMixin, self ).__init__( application )
        self.option( 'command', metavar='...', nargs=argparse.REMAINDER, default=[ ],
                     help=heredoc( """Additional arguments to pass to ssh. This can be anything
                     that one would normally pass to the ssh program excluding user name and host
                     but including, for example, the remote command to execute.""" ) )

    def ssh( self, options, box ):
        return box.ssh( user=self._user( box, options ), command=options.command )


# NB: The ordering of bases affects ordering of positionals

class SshCommand( SshCommandMixin, InstanceCommand ):
    """
    Start an interactive SSH session on a box.
    """

    def run_on_instance( self, options, box ):
        status = self.ssh( options, box )
        if status != 0:
            sys.exit( status )


class RsyncCommandMixin( UserCommandMixin ):
    """
    Rsync to or from the box
    """

    def __init__( self, application ):
        super( RsyncCommandMixin, self ).__init__( application )
        self.option( '--ssh-opts', '-e', metavar='OPTS', default=None,
                     help=heredoc( """Additional options to pass to ssh. Note that if OPTS starts
                     with a dash you must use the long option followed by an equal sign. For
                     example, to run ssh in verbose mode, use --ssh-opt=-v. If OPTS is to include
                     spaces, it must be quoted to prevent the shell from breaking it up. So to
                     run ssh in verbose mode and log to syslog, you would use --ssh-opt='-v
                     -y'.""" ) )
        self.option( 'args', metavar='...', nargs=argparse.REMAINDER, default=[ ],
                     help=heredoc( """Command line options for rsync(1). The remote path argument
                     must be prefixed with a colon. For example, 'cgcloud.py rsync foo -av :bar
                     .' would copy the file 'bar' from the home directory of the admin user on
                     the box 'foo' to the current directory on the local machine.""" ) )

    def rsync( self, options, box ):
        box.rsync( options.args, user=self._user( box, options ), ssh_opts=options.ssh_opts )


# NB: The ordering of bases affects ordering of positionals

class RsyncCommand( RsyncCommandMixin, InstanceCommand ):
    def run_on_instance( self, options, box ):
        self.rsync( options, box )


class ImageCommand( InstanceCommand ):
    """
    Create an AMI image of a box performing a given role. The box must be stopped.
    """

    wait_ready = False

    def run_on_instance( self, options, box ):
        box.image( )


class ShowCommand( InstanceCommand ):
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

    wait_ready = False

    def run_on_instance( self, options, box ):
        self.print_object( box.instance )


class LifecycleCommand( InstanceCommand ):
    """
    Transition an instance box into a particular state.
    """
    wait_ready = False

    def run_on_instance( self, options, box ):
        getattr( box, self.name( ) )( )


class StartCommand( LifecycleCommand ):
    """
    Start the box, ie. bring it from the stopped state to the running state.
    """
    pass


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
        self.option( '--quick', '-Q', default=False, action='store_true',
                     help=heredoc( """Exit immediately after termination request has been made,
                     don't wait until the box is terminated.""" ) )

    def run_on_instance( self, options, box ):
        box.terminate( wait=not options.quick )


class ListImagesCommand( BoxCommand ):
    """
    List the AMI images that were created from boxes performing a particular role.
    """

    def run_on_box( self, options, box ):
        for ordinal, image in enumerate( box.list_images( ) ):
            print( '{name}\t{ordinal}\t{id}\t{state}'.format( ordinal=ordinal,
                                                              **image.__dict__ ) )


class CreationCommand( BoxCommand ):
    def __init__( self, application ):
        super( CreationCommand, self ).__init__( application )
        default_ec2_keypairs = os.environ.get( 'CGCLOUD_KEYPAIRS', '__me__' ).split( )
        self.option( '--keypairs', '-k', metavar='NAME',
                     dest='ec2_keypair_names', nargs='+',
                     default=default_ec2_keypairs,
                     help=heredoc( """The names of EC2 key pairs whose public key is to be
                     injected into the box to facilitate SSH logins. For the first listed
                     argument, the so called primary key pair, a matching private key needs to be
                     present locally. All other arguments may use shell-style globs in which case
                     every key pair whose name matches one of the globs will be deployed to the
                     box. The cgcloudagent program that will typically be installed on a box
                     keeps the deployed list of authorized keys up to date in case matching keys
                     are added or removed from EC2. The value of the environment variable
                     CGCLOUD_KEYPAIRS, if that variable is present, overrides the default for
                     this option. The string __me__ anywhere in an argument will be substituted
                     with the name of the IAM user whose credentials are used to issue requests
                     to AWS. An argument beginning with a single @ will be looked up as the name
                     of an IAM user. If that user exists, the name will be used as the name of a
                     key pair. Otherwise an exception is raised. An argument beginning with @@
                     will be looked up as an IAM group and the name of each user in that group
                     will be used as the name of a keypair. Note that the @ and @@ substitutions
                     depend on the convention that the user and the corresponding key pair have
                     the same name. They only require the respective user or group to exist,
                     while the key pair may be missing. If such a missing key pair is later
                     added, cgcloudagent will automatically add that key pair's public to the
                     list of SSH keys authorized to login to the box. Shell-style globs can not
                     be combined with @ or @@ substitutions within one argument.""" ) )

        self.option( '--instance-type', '-t', metavar='TYPE', choices=ec2_instance_types.keys( ),
                     default=os.environ.get( 'CGCLOUD_INSTANCE_TYPE', None ),
                     help=heredoc( """The type of EC2 instance to launch for the box,
                     e.g. t2.micro, m3.small, m3.medium, or m3.large etc. The value of the
                     environment variable CGCLOUD_INSTANCE_TYPE, if that variable is present,
                     overrides the default, an instance type appropriate for the role.""" ) )

        self.option( '--virtualization-type', metavar='TYPE', choices=Box.virtualization_types,
                     help=heredoc( """The virtualization type to be used for the instance. This
                     affects the choice of image (AMI) the instance is created from. The default
                     depends on the instance type, but generally speaking, 'hvm' will be used for
                     newer instance types.""" ) )

        self.option( '--spot-bid', metavar='AMOUNT', type=float,
                     help=heredoc( """The maximum price to pay for the specified instance type,
                     in dollars per hour as a floating point value, 1.23 for example. Only bids
                     under double the instance type's average price for the past week will be
                     accepted. By default on-demand instances are used. Note that some instance
                     types are not available on the spot market!""" ) )

        self.option( '--vpc', metavar='VPC_ID', type=str, dest='vpc_id',
                     help=heredoc( """The ID of a VPC to create the instance and associated 
                     security group in. If this option is absent and the AWS account has a 
                     default VPC, the default VPC will be used. This is the most common case. If 
                     this option is absent and the AWS account has EC2 Classic enabled and the 
                     selected instance type supports EC2 classic mode, no VPC will be used. If 
                     this option is absent and the AWS account has no default VPC and an instance 
                     type that only supports VPC is used, an exception will be raised.""" ) )

        self.option( '--subnet', metavar='SUBNET_ID', type=str, dest='subnet_id',
                     help=heredoc( """The ID of a subnet to allocate the instance's private IP 
                     address from. Can't be combined with --spot-auto-zone. The specified subnet 
                     must belong to the specified VPC (or the default VPC if none was given) and 
                     reside in the availability zone given via CGCLOUD_ZONE or --zone. If this 
                     option is absent, cgcloud will attempt to choose a subnet automatically.""" ) ) 

        self.option( '--spot-launch-group', metavar='NAME',
                     help=heredoc( """The name of an EC2 spot instance launch group. If
                     specified, the spot request will only be fullfilled once all instances in
                     the group can be launched. Furthermore, if any instance in the group needs
                     to be terminated by Amazon, so will the remaining ones, even if their bid is
                     higher than the market price.""" ) )

        self.option( '--spot-auto-zone', default=False, action='store_true',
                     help=heredoc( """Ignore --zone/CGCLOUD_ZONE and instead choose the best EC2
                     availability zone for spot instances based on a heuristic.""" ) )

        self.option( '--spot-timeout', metavar='SECONDS', type=float,
                     help=heredoc( """The maximum time to wait for spot instance requests to
                     enter the active state. Requests that are not active when the timeout fires
                     will be cancelled.""" ) )

        self.option( '--spot-tentative', default=False, action='store_true',
                     help=heredoc( """Give up on a spot request at the earliest indication of it
                     not being fulfilled immediately.""" ) )

        self.option( '--list', default=False, action='store_true',
                     help=heredoc( """List all instances created by this command on success.""" ) )

        option_name_re = re.compile( r'^[A-Za-z][0-9A-Za-z_]*$' )

        def option( o ):
            l = o.split( '=', 1 )
            if len( l ) != 2:
                raise ValueError( "An option must be of the form NAME=VALUE. '%s' is not." % o )
            k, v = l
            if not option_name_re.match( k ):
                raise ValueError( "An option name must start with a letter and contain only "
                                  "letters, digits and underscore. '%s' does not." % o )
            return k, v

        self.option( '--option', '-O', metavar='NAME=VALUE',
                     type=option, action='append', default=[ ], dest='role_options',
                     help=heredoc( """Set a role-specific option for the instance. To see a list
                     of options for a role, use the list-options command.""" ) )

        self.begin_mutex( )

        self.option( '--terminate', '-T',
                     default=None, action='store_true',
                     help=heredoc( """Terminate the box when setup is complete. The default is to
                     leave the box running except when errors occur.""" ) )

        self.option( '--never-terminate', '-N',
                     default=None, dest='terminate', action='store_false',
                     help=heredoc( """Never terminate the box, even after errors. This may be
                     useful for a post-mortem diagnosis.""" ) )

        self.end_mutex( )

    @abstractmethod
    def run_on_creation( self, box, options ):
        """
        Run on the given box after it was created.
        """
        raise NotImplementedError( )

    def preparation_kwargs( self, options, box ):
        """
        Return dict with keyword arguments to be passed box.prepare()
        """
        role_options = box.get_role_options( )
        supported_options = set( option.name for option in role_options )
        actual_options = set( name for name, value in options.role_options )
        for name in actual_options - supported_options:
            raise UserError( "Options %s not supported by role '%s'." % (name, box.role( )) )
        resolve_me = functools.partial( box.ctx.resolve_me, drop_hostname=False )
        return dict( options.role_options,
                     ec2_keypair_globs=map( resolve_me, options.ec2_keypair_names ),
                     instance_type=options.instance_type,
                     virtualization_type=options.virtualization_type,
                     vpc_id=options.vpc_id,
                     subnet_id=options.subnet_id,
                     spot_bid=options.spot_bid,
                     spot_launch_group=options.spot_launch_group,
                     spot_auto_zone=options.spot_auto_zone )

    def creation_kwargs( self, options, box ):
        return dict( terminate_on_error=options.terminate is not False,
                     spot_timeout=options.spot_timeout,
                     spot_tentative=options.spot_tentative )

    def run_on_box( self, options, box ):
        """
        :type box: Box
        """
        spec = box.prepare( **self.preparation_kwargs( options, box ) )
        box.create( spec, **self.creation_kwargs( options, box ) )
        try:
            self.run_on_creation( box, options )
        except:
            if options.terminate is not False:
                with panic( log ):
                    box.terminate( wait=False )
            raise
        else:
            if options.list:
                self.list( [ box ] )
            if options.terminate is True:
                box.terminate( )
            else:
                self.log_ssh_hint( options )

    # noinspection PyUnresolvedReferences
    def log_ssh_hint( self, options ):
        hint = self.ssh_hint( options )

        def opt( name, value, default ):
            return name + ' ' + value if value != default else None

        cmd = concat( hint.executable,
                      hint.command,
                      (opt( **option ) for option in hint.options),
                      hint.args )
        cmd = ' '.join( filter( None, cmd ) )
        log.info( "Run '%s' to start using this %s.", cmd, hint.object )

    def ssh_hint( self, options ):
        x = Expando
        return x( executable=os.path.basename( sys.argv[ 0 ] ),
                  command='ssh',
                  options=[
                      x( name='-n', value=options.namespace, default=self.default_namespace ),
                      x( name='-z', value=options.availability_zone, default=self.default_zone ) ],
                  args=[ options.role ],
                  object='box' )


class RegisterKeyCommand( ContextCommand ):
    """
    Upload an OpenSSH public key for future injection into boxes. The public key will be imported
    into EC2 as a keypair and stored verbatim in S3.
    """

    def __init__( self, application, **kwargs ):
        super( RegisterKeyCommand, self ).__init__( application, **kwargs )
        self.option( 'ssh_public_key', metavar='KEY_FILE',
                     help=heredoc( """Path of file containing the SSH public key to upload to the
                     EC2 keypair.""" ) )
        self.option( '--force', '-F', default=False, action='store_true',
                     help='Overwrite potentially existing EC2 key pair' )
        self.option( '--keypair', '-k', metavar='NAME',
                     dest='ec2_keypair_name', default='__me__',
                     help=heredoc( """The desired name of the EC2 key pair. The name should
                     associate the key with you in a way that it is obvious to other users in
                     your organization.  The string __me__ anywhere in the key pair name will be
                     replaced with the name of the IAM user whose credentials are used to issue
                     requests to AWS.""" ) )

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
        log.info( "If you are expecting to see more roles listed above, you may need to set/change "
                  "the CGCLOUD_PLUGINS environment variable." )


# noinspection PyAbstractClass
class ImageReferenceCommand( Command ):
    """
    Any command that accepts an image ordinal or AMI ID.

    >>> app = Application()
    >>> class FooCmd( ImageReferenceCommand ):
    ...     long_image_option = '--foo'
    ...     short_image_option = '-f'
    ...     def run(self, options):
    ...         pass
    >>> cmd = FooCmd( app )
    >>> cmd.ordinal_or_ami_id( 'bar' )
    Traceback (most recent call last):
    ...
    ValueError
    >>> cmd.ordinal_or_ami_id( '' )
    Traceback (most recent call last):
    ...
    ValueError
    >>> cmd.ordinal_or_ami_id( '-1')
    -1
    >>> cmd.ordinal_or_ami_id( 'ami-4dcced7d')
    'ami-4dcced7d'
    >>> cmd.ordinal_or_ami_id( 'ami-4dCCED7D')
    'ami-4dcced7d'
    >>> cmd.ordinal_or_ami_id( 'amI-4dCCED7D')
    Traceback (most recent call last):
    ...
    ValueError
    >>> cmd.ordinal_or_ami_id( 'ami-4dcced7')
    Traceback (most recent call last):
    ...
    ValueError
    >>> cmd.ordinal_or_ami_id( 'ami-4dCCED7DD')
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

    long_image_option = None
    short_image_option = None

    def __init__( self, application ):
        super( ImageReferenceCommand, self ).__init__( application )
        self.option( self.long_image_option, self.short_image_option, metavar='IMAGE',
                     type=self.ordinal_or_ami_id, default=-1,  # default to the last one
                     help=heredoc( """An image ordinal, i.e. the index of an image in the list of
                     images for the given role, sorted by creation time. Use the list-images
                     command to print a list of images for a given role. If the ordinal is
                     negative, it will be converted to a positive ordinal by adding the total
                     number of images for this role. Passing -1, for example, selects the most
                     recently created image. Alternatively, an AMI ID, e.g. 'ami-4dcced7d' can be
                     passed in as well.""" ) )


class DeleteImageCommand( ImageReferenceCommand, BoxCommand ):
    long_image_option = '--image'
    short_image_option = '-i'

    def __init__( self, application ):
        super( DeleteImageCommand, self ).__init__( application )
        self.begin_mutex( )
        self.option( '--keep-snapshot', '-K',
                     default=False, action='store_true',
                     help=heredoc( """Do not delete the EBS volume snapshot associated with the
                     given image. This will leave an orphaned snapshot which should be removed at
                     a later time using the 'cgcloud cleanup' command.""" ) )
        self.option( '--quick', '-Q', default=False, action='store_true',
                     help=heredoc( """Exit immediately after deregistration request has been made,
                     don't wait until the image is deregistered. Implies --keep-snapshot.""" ) )
        self.end_mutex( )

    def run_on_box( self, options, box ):
        box.delete_image( options.image,
                          wait=not options.quick,
                          delete_snapshot=not options.keep_snapshot )


class RecreateCommand( ImageReferenceCommand, CreationCommand ):
    """
    Recreate a box from an image that was taken from an earlier incarnation of the box
    """
    long_image_option = '--boot-image'
    short_image_option = '-i'

    def __init__( self, application ):
        super( RecreateCommand, self ).__init__( application )
        self.option( '--quick', '-Q', default=False, action='store_true',
                     help=heredoc( """Don't wait for the box to become running or reachable via
                     SSH. If the agent is disabled in the boot image (this is uncommon,
                     see the --no-agent option to the 'create' command), no additional SSH
                     keypairs will be deployed.""" ) )

    def preparation_kwargs( self, options, box ):
        return dict( super( RecreateCommand, self ).preparation_kwargs( options, box ),
                     image_ref=options.boot_image )

    def creation_kwargs( self, options, box ):
        return dict( super( RecreateCommand, self ).creation_kwargs( options, box ),
                     wait_ready=not options.quick )

    def run_on_creation( self, box, options ):
        pass


class CreateCommand( CreationCommand ):
    """
    Create a box performing the specified role, install an OS and additional packages on it and
    optionally create an AMI image of it.
    """

    def __init__( self, application ):
        super( CreateCommand, self ).__init__( application )
        self.option( '--boot-image', '-i', metavar='AMI_ID',
                     help=heredoc( """The AMI ID of the image from which to create the box. This
                     argument is optional and the default is determined automatically based on
                     the role. Typically, this option does not need to be used.""" ) )
        self.option( '--no-agent',
                     default=False, action='store_true',
                     help=heredoc( """Don't install the cghub-cloud-agent package on the box. One
                     note-worthy effect of using this option this is that the SSH keys will be
                     installed initially, but not maintained over time.""" ) )
        self.option( '--create-image', '-I',
                     default=False, action='store_true',
                     help='Create an image of the box as soon as setup completes.' )
        # FIXME: Take a second look at this: Does it work. Is it necessary?
        self.option( '--upgrade', '-U',
                     default=False, action='store_true',
                     help=heredoc( """Bring the package repository as well as any installed
                     packages up to date, i.e. do what on Ubuntu is achieved by doing 'sudo
                     apt-get update ; sudo apt-get upgrade'.""" ) )

    def preparation_kwargs( self, options, box ):
        return dict( super( CreateCommand, self ).preparation_kwargs( options, box ),
                     image_ref=options.boot_image,
                     enable_agent=not options.no_agent )

    def run_on_creation( self, box, options ):
        box.setup( upgrade_installed_packages=options.upgrade )
        if options.create_image:
            box.stop( )
            box.image( )
            if options.terminate is not True:
                box.start( )


class ListOptionsCommand( RoleCommand ):
    def run_on_role( self, options, ctx, role ):
        role_options = role.get_role_options( )
        if role_options:
            for option in role_options:
                print( "{name}: {help}".format( **option.to_dict( ) ) )
        else:
            print( 'The role %s does not define any options' % role.role( ) )


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
    """
    Delete security-related objects like IAM instance profiles or EC2 security groups in a
    namespace and its children.
    """

    def run_in_ctx( self, options, ctx ):
        message = ("Do you really want to delete all IAM instance profiles, IAM roles and EC2 "
                   "security groups in namespace %s and its children? Although these resources "
                   "will be created on-the-fly for newly created boxes, existing boxes will "
                   "likely be impacted negatively." % ctx.namespace)
        if 'yes' == prompt( message + ' (yes/no)', default='no' ):
            ctx.reset_namespace_security( )


class UpdateInstanceProfile( InstanceCommand ):
    """
    Update the instance profile and associated IAM roles for a given role.

    This command ensures that a box of this role has accurate and up-to-date privileges to
    interact with AWS resources. The instance profile is updated whenever a box is created. Use
    this command to update the instance profile for existing boxes.
    """

    def run_on_instance( self, options, box ):
        box.get_instance_profile_arn( )
