# coding=utf-8
from contextlib import contextmanager
import json
import os
import urllib
import re
import socket
import itertools
import logging

from boto import ec2, iam, sns, sqs, vpc
from boto.s3.key import Key as S3Key
from boto.exception import S3ResponseError, BotoServerError
from boto.s3.connection import S3Connection
from boto.sqs.connection import SQSConnection
from boto.sns.connection import SNSConnection
from boto.ec2.connection import EC2Connection

from boto.vpc import VPCConnection

from boto.iam.connection import IAMConnection

from boto.ec2.keypair import KeyPair

from bd2k.util import fnmatch

from bd2k.util import memoize

from boto.utils import get_instance_metadata

from cgcloud.lib.message import Message
from cgcloud.lib.util import ec2_keypair_fingerprint, UserError

log = logging.getLogger( __name__ )


class Context( object ):
    """
    Encapsulates all EC2-specific settings used by components in this project
    """
    availability_zone_re = re.compile( r'^([a-z]{2}-[a-z]+-[1-9][0-9]*)([a-z])$' )

    name_prefix_re = re.compile( r'^(/([0-9a-zA-Z.-][_0-9a-zA-Z.-]*))*' )
    name_re = re.compile( name_prefix_re.pattern + '/?$' )
    namespace_re = re.compile( name_prefix_re.pattern + '/$' )

    def __init__( self, availability_zone, namespace ):
        """
        Create an Context object.

        :param availability_zone: The availability zone to place EC2 resources like volumes and
        instances into. The AWS region to operate in is implied by this parameter since the
        region is a prefix of the availability zone string

        :param namespace: The prefix for names of EC2 resources. The namespace is string starting
        in '/' followed by zero or more components, separated by '/'. Components are non-empty
        strings consisting only of alphanumeric characters, '.', '-' or '_' and that don't start
        with '_'. The namespace argument will be encoded as ASCII. Unicode strings that can't be
        encoded as ASCII will be rejected.

        A note about our namespaces vs IAM's resource paths. IAM paths don't provide namespace
        isolation. In other words, it is not possible to have two users of the same name in two
        different paths. The by itself name has to be unique. For that reason, IAM resource paths
        are pretty much useless.

        >>> ctx = Context( 'us-west-1b', None )
        Traceback (most recent call last):
        ....
        ValueError: Need namespace

        >>> Context('us-west-1b', namespace='/').namespace
        '/'

        >>> Context('us-west-1b', namespace='/foo/').namespace
        '/foo/'

        >>> Context('us-west-1b', namespace='/foo/bar/').namespace
        '/foo/bar/'

        >>> Context('us-west-1b', namespace='')
        Traceback (most recent call last):
        ....
        ValueError: Invalid namespace ''

        >>> Context('us-west-1b', namespace='foo')
        Traceback (most recent call last):
        ....
        ValueError: Invalid namespace 'foo'

        >>> Context('us-west-1b', namespace='/foo')
        Traceback (most recent call last):
        ....
        ValueError: Invalid namespace '/foo'

        >>> Context('us-west-1b', namespace='//foo/')
        Traceback (most recent call last):
        ....
        ValueError: Invalid namespace '//foo/'

        >>> Context('us-west-1b', namespace='/foo//')
        Traceback (most recent call last):
        ....
        ValueError: Invalid namespace '/foo//'

        >>> Context('us-west-1b', namespace='han//nes')
        Traceback (most recent call last):
        ....
        ValueError: Invalid namespace 'han//nes'

        >>> Context('us-west-1b', namespace='/_foo/')
        Traceback (most recent call last):
        ....
        ValueError: Invalid namespace '/_foo/'

        >>> Context('us-west-1b', namespace=u'/foo/').namespace
        '/foo/'

        >>> Context('us-west-1b', namespace=u'/föo/').namespace
        Traceback (most recent call last):
        ....
        ValueError: 'ascii' codec can't encode characters in position 2-3: ordinal not in range(128)

        >>> import string
        >>> component = string.ascii_letters + string.digits + '-_.'
        >>> namespace = '/' + component + '/'
        >>> Context('us-west-1b', namespace=namespace).namespace == namespace
        True
        """
        super( Context, self ).__init__( )

        self.__iam = None
        self.__ec2 = None
        self.__s3 = None
        self.__sns = None
        self.__sqs = None

        self.availability_zone = availability_zone
        m = self.availability_zone_re.match( availability_zone )
        if not m:
            raise ValueError( "Can't extract region from availability zone '%s'"
                              % availability_zone )
        self.region = m.group( 1 )

        if namespace is None:
            raise ValueError( 'Need namespace' )
        try:
            namespace = namespace.encode( 'ascii' )
        except UnicodeEncodeError as e:
            raise ValueError( e )

        namespace = self.resolve_me( namespace )

        if not re.match( self.namespace_re, namespace ):
            raise ValueError( "Invalid namespace '%s'" % namespace )

        self.namespace = namespace

    @property
    def iam( self ):
        """
        :rtype: IAMConnection
        """
        if self.__iam is None:
            self.__iam = self.__aws_connect( iam, 'universal' )
        return self.__iam

    @property
    def ec2( self ):
        """
        :rtype: EC2Connection
        """
        if self.__ec2 is None:
            self.__ec2 = self.__aws_connect( ec2 )
        return self.__ec2

    @property
    def vpc( self ):
        """
        :rtype: VPCConnection
        """
        if self.__vpc is None:
            self.__vpc = self.__aws_connect( vpc )
        return self.__vpc

    @property
    def s3( self ):
        """
        :rtype: S3Connection
        """
        if self.__s3 is None:
            # We let S3 route buckets to regions for us. If we connected to a specific region,
            # bucket lookups (HEAD request against bucket URL) would fail with 301 status but
            # without a Location header.
            self.__s3 = S3Connection( )
        return self.__s3

    @property
    def sns( self ):
        """
        :rtype: SNSConnection
        """
        if self.__sns is None:
            self.__sns = self.__aws_connect( sns )
        return self.__sns

    @property
    def sqs( self ):
        """
        :rtype: SQSConnection
        """
        if self.__sqs is None:
            self.__sqs = self.__aws_connect( sqs )
        return self.__sqs

    def __aws_connect( self, aws_module, region=None, **kwargs ):
        if region is None:
            region = self.region
        conn = aws_module.connect_to_region( region, **kwargs )
        if conn is None:
            raise RuntimeError( "%s couldn't connect to region %s" % (
                aws_module.__name__, region) )
        return conn

    def __enter__( self ):
        return self

    def __exit__( self, exc_type, exc_val, exc_tb ):
        self.close( )

    def close( self ):
        if self.__ec2 is not None: self.__ec2.close( )
        if self.__s3 is not None: self.__s3.close( )
        if self.__iam is not None: self.__iam.close( )
        if self.__sns is not None: self.__sns.close( )
        if self.__sqs is not None: self.__sqs.close( )

    @staticmethod
    def is_absolute_name( name ):
        """
        Returns True if the given name starts with a namespace.
        """
        return name[ 0:1 ] == '/'

    def absolute_name( self, name ):
        """
        Returns the absolute form of the specified resource name. If the specified name is
        already absolute, that name will be returned unchanged, otherwise the given name will be
        prefixed with the namespace this object was configured with.

        Relative names starting with underscores are disallowed.

        >>> ctx = Context( 'us-west-1b', namespace='/' )
        >>> ctx.absolute_name('bar')
        '/bar'
        >>> ctx.absolute_name('/bar')
        '/bar'
        >>> ctx.absolute_name('')
        '/'
        >>> ctx.absolute_name('/')
        '/'
        >>> ctx.absolute_name('_bar')
        Traceback (most recent call last):
        ....
        ValueError: Invalid path '/_bar'
        >>> ctx.absolute_name('/_bar')
        Traceback (most recent call last):
        ....
        ValueError: Invalid path '/_bar'

        >>> ctx = Context( 'us-west-1b', namespace='/foo/' )
        >>> ctx.absolute_name('bar')
        '/foo/bar'
        >>> ctx.absolute_name('bar/')
        '/foo/bar/'
        >>> ctx.absolute_name('bar1/bar2')
        '/foo/bar1/bar2'
        >>> ctx.absolute_name('/bar')
        '/bar'
        >>> ctx.absolute_name('')
        '/foo/'
        >>> ctx.absolute_name('/')
        '/'
        >>> ctx.absolute_name('_bar')
        Traceback (most recent call last):
        ....
        ValueError: Invalid path '/foo/_bar'
        >>> ctx.absolute_name('/_bar')
        Traceback (most recent call last):
        ....
        ValueError: Invalid path '/_bar'
        """
        if self.is_absolute_name( name ):
            result = name
        else:
            result = self.namespace + name
        if not self.name_re.match( result ):
            raise ValueError( "Invalid path '%s'" % result )
        return result

    def to_aws_name( self, name ):
        """
        Returns a transliteration of the name that safe to use for resource names on AWS. If the
        given name is relative, it converted to its absolute form before the transliteration.

        The transliteration uses two consequitive '_' to encode a single '_' and a single '_' to
        separate the name components. AWS-safe names are by definition absolute such that the
        leading separator can be removed. This leads to fairly readable AWS-safe names,
        especially for names in the root namespace, where the transliteration is the identity
        function if the input does not contain any '_'.

        This scheme only works if name components don't start with '_'. Without that condition,
        '/_' would become '___' the inverse of which is '_/'.

        >>> ctx = Context( 'us-west-1b', namespace='/' )

        >>> ctx.to_aws_name( 'foo' )
        'foo'
        >>> ctx.from_aws_name( 'foo' )
        'foo'

        Illegal paths that would introduce ambiguity need to raise an exception
        >>> ctx.to_aws_name('/_')
        Traceback (most recent call last):
        ....
        ValueError: Invalid path '/_'
        >>> ctx.to_aws_name('/_/')
        Traceback (most recent call last):
        ....
        ValueError: Invalid path '/_/'
        >>> ctx.from_aws_name('___')
        Traceback (most recent call last):
        ....
        ValueError: Invalid path '/_/'

        >>> ctx.to_aws_name( 'foo_bar')
        'foo__bar'
        >>> ctx.from_aws_name( 'foo__bar')
        'foo_bar'

        >>> ctx.to_aws_name( '/sub_ns/foo_bar')
        'sub__ns_foo__bar'
        >>> ctx.to_aws_name( 'sub_ns/foo_bar')
        'sub__ns_foo__bar'
        >>> ctx.from_aws_name( 'sub__ns_foo__bar' )
        'sub_ns/foo_bar'

        >>> ctx.to_aws_name( 'g_/' )
        'g___'
        >>> ctx.from_aws_name( 'g___' )
        'g_/'

        >>> ctx = Context( 'us-west-1b', namespace='/this_ns/' )

        >>> ctx.to_aws_name( 'foo' )
        'this__ns_foo'
        >>> ctx.from_aws_name( 'this__ns_foo' )
        'foo'

        >>> ctx.to_aws_name( 'foo_bar')
        'this__ns_foo__bar'
        >>> ctx.from_aws_name( 'this__ns_foo__bar')
        'foo_bar'

        >>> ctx.to_aws_name( '/other_ns/foo_bar' )
        'other__ns_foo__bar'
        >>> ctx.from_aws_name( 'other__ns_foo__bar' )
        '/other_ns/foo_bar'

        >>> ctx.to_aws_name( 'other_ns/foo_bar' )
        'this__ns_other__ns_foo__bar'
        >>> ctx.from_aws_name( 'this__ns_other__ns_foo__bar' )
        'other_ns/foo_bar'

        >>> ctx.to_aws_name( '/this_ns/foo_bar' )
        'this__ns_foo__bar'
        >>> ctx.from_aws_name( 'this__ns_foo__bar' )
        'foo_bar'
        """
        name = self.absolute_name( name )
        assert name.startswith( '/' )
        return name[ 1: ].replace( '_', '__' ).replace( '/', '_' )

    def from_aws_name( self, name ):
        """
        The inverse of to_aws_name(), except that the namespace is stripped from the input if it
        is relative to this context's name space.

        >>> zone = 'us-west-1b'
        >>> Context( zone, namespace='/foo/' ).from_aws_name('bar__x')
        '/bar_x'
        >>> Context( zone, namespace='/foo_x/' ).from_aws_name('foo__x_bar')
        'bar'
        >>> Context( zone, namespace='/' ).from_aws_name('foo__x_bar__x')
        'foo_x/bar_x'
        >>> Context( zone, namespace='/bla/' ).from_aws_name('foo__x_bar__x')
        '/foo_x/bar_x'
        """
        name = '_'.join( s.replace( '_', '/' ) for s in name.split( '__' ) )
        name = '/' + name
        if not self.name_re.match( name ):
            raise ValueError( "Invalid path '%s'" % name )
        if name.startswith( self.namespace ):
            name = name[ len( self.namespace ): ]
        return name

    def contains_name( self, name ):
        return not self.is_absolute_name( name ) or name.startswith( self.namespace )

    def contains_aws_name( self, aws_name ):
        return self.contains_name( self.from_aws_name( aws_name ) )

    @property
    @memoize
    def account( self ):
        try:
            arn = self.iam.get_user( ).arn
        except:
            # Agent boxes run with IAM role credentials instead of user credentials.
            arn = get_instance_metadata( )[ 'iam' ][ 'info' ][ 'InstanceProfileArn' ]
        _, partition, service, region, account, resource = arn.split( ':', 6 )
        return account

    @property
    @memoize
    def s3_bucket_name( self ):
        return self.account + '-cgcloud'

    ssh_pubkey_s3_key_prefix = 'ssh_pubkey:'

    def upload_ssh_pubkey( self, ssh_pubkey, fingerprint ):
        bucket = self.s3.lookup( self.s3_bucket_name )
        if bucket is None:
            bucket = self.s3.create_bucket( self.s3_bucket_name,
                                            location=self.region )
        s3_entry = S3Key( bucket )
        s3_entry.key = self.ssh_pubkey_s3_key_prefix + fingerprint
        s3_entry.set_contents_from_string( ssh_pubkey )

    def register_ssh_pubkey( self, ec2_keypair_name, ssh_pubkey, force=False ):
        """
        Import the given OpenSSH public key  as a 'key pair' into EC2.

        There is no way to get to the actual public key once it has been imported to EC2.
        Openstack lets you do that and I don't see why Amazon decided to omit this functionality.
        To work around this, we store the public key in S3, identified by the public key's
        fingerprint. As long as we always check the fingerprint of the downloaded public SSH key
        against that of the EC2 keypair key, this method is resilient against malicious
        modifications of the keys stored in S3.

        :param ec2_keypair_name: the desired name of the EC2 key pair

        :param ssh_pubkey: the SSH public key in OpenSSH's native format, i.e. format that is used in ~/
        .ssh/authorized_keys

        :param force: overwrite existing EC2 keypair of the given name
        """
        fingerprint = ec2_keypair_fingerprint( ssh_pubkey, reject_private_keys=True )
        ec2_keypair = self.ec2.get_key_pair( ec2_keypair_name )
        if ec2_keypair is not None:
            if ec2_keypair.name != ec2_keypair_name:
                raise AssertionError( "Key pair names don't match." )
            if ec2_keypair.fingerprint != fingerprint:
                if force:
                    self.ec2.delete_key_pair( ec2_keypair_name )
                    ec2_keypair = None
                else:
                    raise UserError(
                        "Key pair %s already exists in EC2, but its fingerprint %s is "
                        "different from the fingerprint %s of the key to be imported. Use "
                        "the force option to overwrite the existing key pair." %
                        (ec2_keypair.name, ec2_keypair.fingerprint, fingerprint) )

        if ec2_keypair is None:
            ec2_keypair = self.ec2.import_key_pair( ec2_keypair_name, ssh_pubkey )
        assert ec2_keypair.fingerprint == fingerprint

        self.upload_ssh_pubkey( ssh_pubkey, fingerprint )
        self.__publish_key_update_agent_message( )
        return ec2_keypair

    def expand_keypair_globs( self, globs ):
        """
        Returns a list of EC2 key pair objects matching the specified globs. The order of the
        objects in the returned list will be consistent with the order of the globs and it will
        not contain any elements more than once. In other words, the returned list will start
        with all key pairs matching the first glob, followed by key pairs matching the second
        glob but not the first glob and so on.

        :rtype: list of KeyPair
        """

        def iam_lookup( glob ):
            if glob.startswith( '@@' ):
                return (_.user_name for _ in self.iam.get_group( 'developers' ).users)
            elif glob.startswith( '@' ):
                return (self.iam.get_user( glob[ 1: ] ).user_name,)
            else:
                return (glob,)

        globs = itertools.chain.from_iterable( map( iam_lookup, globs ) )

        result = [ ]
        keypairs = dict( (keypair.name, keypair) for keypair in self.ec2.get_all_key_pairs( ) )
        for glob in globs:
            i = len( result )
            for name, keypair in keypairs.iteritems( ):
                if fnmatch.fnmatch( name, glob ):
                    result.append( keypair )

            # since we can't modify the set during iteration
            for keypair in result[ i: ]:
                keypairs.pop( keypair.name )
        return result

    def download_ssh_pubkey( self, ec2_keypair ):
        try:
            bucket = self.s3.get_bucket( self.s3_bucket_name )
            s3_entry = S3Key( bucket )
            s3_entry.key = self.ssh_pubkey_s3_key_prefix + ec2_keypair.fingerprint
            ssh_pubkey = s3_entry.get_contents_as_string( )
        except S3ResponseError as e:
            if e.status == 404:
                raise UserError(
                    "There is no matching SSH pub key stored in S3 for EC2 key pair %s. Has "
                    "it been registered, e.g using the cgcloud's register-key command?" %
                    ec2_keypair.name )
            else:
                raise
        fingerprint_len = len( ec2_keypair.fingerprint.split( ':' ) )
        if fingerprint_len == 20:  # 160 bit SHA-1
            # The fingerprint is that of a private key. We can't get at the private key so we
            # can't verify the public key either. So this is inherently insecure. However,
            # remember that the only reason why we are dealing with n EC2-generated private
            # key is that the Jenkins' EC2 plugin expects a 20 byte fingerprint. See
            # https://issues.jenkins-ci.org/browse/JENKINS-20142 for details. Once that issue
            # is fixed, we can switch back to just using imported keys and 16-byte fingerprints.
            pass
        elif fingerprint_len == 16:  # 128 bit MD5
            fingerprint = ec2_keypair_fingerprint( ssh_pubkey )
            if ec2_keypair.fingerprint != fingerprint:
                raise UserError(
                    "Fingerprint mismatch for key %s! Expected %s but got %s. The EC2 keypair "
                    "doesn't match the public key stored in S3." %
                    (ec2_keypair.name, ec2_keypair.fingerprint, fingerprint) )
        return ssh_pubkey

    @property
    @memoize
    def iam_user_name( self ):
        try:
            return self.iam.get_user( ).user_name
        except:
            return None

    current_user_placeholder = '__me__'

    @staticmethod
    def drop_hostname( email ):
        """
        >>> Context.drop_hostname("foo")
        'foo'
        >>> Context.drop_hostname("foo@bar.com")
        'foo'
        >>> Context.drop_hostname("")
        ''
        >>> Context.drop_hostname("@")
        ''
        """
        try:
            n = email.index( "@" )
        except ValueError:
            return email
        else:
            return email[ 0:n ]

    def resolve_me( self, s, drop_hostname=True ):
        placeholder = self.current_user_placeholder
        if placeholder in s:
            me = os.environ.get( 'CGCLOUD_ME' ) or self.iam_user_name
            if drop_hostname:
                me = self.drop_hostname( me )
            return s.replace( placeholder, me )
        else:
            return s

    def setup_iam_ec2_role( self, role_name, policies ):
        aws_role_name = self.to_aws_name( role_name )
        try:
            self.iam.create_role( aws_role_name, assume_role_policy_document=json.dumps( {
                "Version": "2012-10-17",
                "Statement": [ {
                    "Effect": "Allow",
                    "Principal": { "Service": [ "ec2.amazonaws.com" ] },
                    "Action": [ "sts:AssumeRole" ] }
                ] } ) )
        except BotoServerError as e:
            if e.status == 409 and e.error_code == 'EntityAlreadyExists':
                pass
            else:
                raise

        self.__setup_entity_policies( aws_role_name, policies,
                                      list_policies=self.iam.list_role_policies,
                                      delete_policy=self.iam.delete_role_policy,
                                      get_policy=self.iam.get_role_policy,
                                      put_policy=self.iam.put_role_policy )

        return aws_role_name

    def setup_iam_user_policies( self, user_name, policies ):
        try:
            self.iam.create_user( user_name )
        except BotoServerError as e:
            if e.status == 409 and e.error_code == 'EntityAlreadyExists':
                pass
            else:
                raise

        self.__setup_entity_policies( user_name, policies,
                                      list_policies=self.iam.get_all_user_policies,
                                      delete_policy=self.iam.delete_user_policy,
                                      get_policy=self.iam.get_user_policy,
                                      put_policy=self.iam.put_user_policy )

    def __setup_entity_policies( self, entity_name, policies,
                                 list_policies, delete_policy, get_policy, put_policy ):
        # Delete superfluous policies
        policy_names = set( list_policies( entity_name ).policy_names )
        for policy_name in policy_names.difference( set( policies.keys( ) ) ):
            delete_policy( entity_name, policy_name )

        # Create expected policies
        for policy_name, policy in policies.iteritems( ):
            current_policy = None
            try:
                current_policy = json.loads( urllib.unquote(
                    get_policy( entity_name, policy_name ).policy_document ) )
            except BotoServerError as e:
                if e.status == 404 and e.error_code == 'NoSuchEntity':
                    pass
                else:
                    raise
            if current_policy != policy:
                put_policy( entity_name, policy_name, json.dumps( policy ) )

    _agent_topic_name = "cgcloud-agent-notifications"

    @property
    def agent_queue_name( self ):
        host_qualifier = socket.gethostname( ).replace( '.', '-' )
        return self._agent_topic_name + '/' + host_qualifier

    @property
    @memoize
    def agent_topic_arn( self ):
        """
        The ARN of the SNS topic on which the agents listen for messages and returns its ARN.
        """
        # Note that CreateTopic is idempotent
        return self.sns.create_topic( self._agent_topic_name )[
            'CreateTopicResponse' ][ 'CreateTopicResult' ][ 'TopicArn' ]

    def publish_agent_message( self, message ):
        """
        :type message: Message
        """
        self.sns.publish( self.agent_topic_arn, message.to_sns( ) )

    def __publish_key_update_agent_message( self ):
        self.publish_agent_message( Message( type=Message.TYPE_UPDATE_SSH_KEYS ) )

    def cleanup( self ):
        """
        Delete all

        - IAM instance profiles,
        - IAM roles,
        - IAM policies and
        - EC2 security groups

        associated with this context, or rather the namespace this context represents.
        """

        @contextmanager
        def out_exception( object_type, object_name ):
            try:
                try:
                    yield
                except ValueError as e:
                    if e.message.startswith( 'Invalid path' ):
                        pass
                    else:
                        raise
            except:
                log.warn( "Failed to remove %s '%s'", object_type, object_name, exc_info=True )

        for p in self.iam.list_instance_profiles( ).instance_profiles:
            with out_exception( 'instance profile', p.instance_profile_name ):
                if self.contains_aws_name( p.instance_profile_name ):
                    # currently EC2 allows only one role per profile
                    if p.roles:
                        self.iam.remove_role_from_instance_profile( p.instance_profile_name,
                                                                    p.roles.member.role_name )
                    self.iam.delete_instance_profile( p.instance_profile_name )
        for r in self.iam.list_roles( ).roles:
            with out_exception( 'role', r.role_name ):
                if self.contains_aws_name( r.role_name ):
                    for policy_name in self.iam.list_role_policies( r.role_name ).policy_names:
                        self.iam.delete_role_policy( r.role_name, policy_name )
                    self.iam.delete_role( r.role_name )
        for sg in self.ec2.get_all_security_groups( ):
            with out_exception( 'security group', sg.name ):
                if self.contains_aws_name( sg.name ):
                    sg.delete( )
