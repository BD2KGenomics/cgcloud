# coding=utf-8
import fnmatch
import os
import re
import socket
import itertools

from boto import ec2, s3, iam
from boto.exception import S3ResponseError
from boto.s3.key import Key
from cghub.util import memoize

from cghub.cloud.lib.util import ec2_keypair_fingerprint, UserError, mkdir_p, app_name


class Context:
    """
    Encapsulates all EC2-specific settings used by components in this project
    """
    s3_bucket_name = 'cghub-cloud-utils.cghub.ucsc.edu'

    availability_zone_re = re.compile( r'^([a-z]{2}-[a-z]+-[1-9][0-9]*)([a-z])$' )
    path_prefix_re = re.compile( r'^(/([0-9a-zA-Z.-][_0-9a-zA-Z.-]*))*' )
    path_re = re.compile( path_prefix_re.pattern + '/?$' )
    namespace_re = re.compile( path_prefix_re.pattern + '/$' )


    def __init__( self, availability_zone='us-west-1b', namespace=None ):
        """
        Create an Context object.

        :param availability_zone: The availability zone to place EC2 resources like volumes and
        instances into. The AWS region to operate in is implied by this parameter since the
        region is a prefix of the availability zone string

        :param namespace: The prefix for names of EC2 resources. The namespace is string starting
        in '/' followed by zero or more components, separated by '/'. Components are non-empty
        strings consisting only of alphanumeric characters, '.', '-' or '_'. Components my not
        start with '_'. The namespace argument will be encoded as ASCII. Unicode strings that
        can't be encoded as ASCII will be rejected.


        >>> ctx = Context(namespace=None)
        >>> ctx.namespace == '/%s/' % ctx.iam_user_name()
        True

        >>> Context(namespace='/').namespace
        '/'

        >>> Context(namespace='/foo/').namespace
        '/foo/'

        >>> Context(namespace='/foo/bar/').namespace
        '/foo/bar/'

        >>> Context(namespace='')
        Traceback (most recent call last):
        ....
        ValueError: Invalid namespace ''

        >>> Context(namespace='foo')
        Traceback (most recent call last):
        ....
        ValueError: Invalid namespace 'foo'

        >>> Context(namespace='/foo')
        Traceback (most recent call last):
        ....
        ValueError: Invalid namespace '/foo'

        >>> Context(namespace='//foo/')
        Traceback (most recent call last):
        ....
        ValueError: Invalid namespace '//foo/'

        >>> Context(namespace='/foo//')
        Traceback (most recent call last):
        ....
        ValueError: Invalid namespace '/foo//'

        >>> Context(namespace='han//nes')
        Traceback (most recent call last):
        ....
        ValueError: Invalid namespace 'han//nes'

        >>> Context(namespace='/_foo/')
        Traceback (most recent call last):
        ....
        ValueError: Invalid namespace '/_foo/'

        >>> Context(namespace=u'/foo/').namespace
        '/foo/'

        >>> Context(namespace=u'/föo/').namespace
        Traceback (most recent call last):
        ....
        ValueError: 'ascii' codec can't encode characters in position 2-3: ordinal not in range(128)

        >>> import string
        >>> component = string.ascii_letters + string.digits + '-_.'
        >>> namespace = '/' + component + '/'
        >>> Context(namespace=namespace).namespace == namespace
        True
        """
        self.availability_zone = availability_zone
        m = self.availability_zone_re.match( availability_zone )
        if not m:
            raise ValueError( "Can't extract region from availability zone '%s'"
                              % availability_zone )
        self.region = m.group( 1 )

        if namespace is None:
            user_name = self.iam_user_name( )
            namespace = '/' if user_name is None else '/%s/' % user_name
        try:
            namespace = namespace.encode( 'ascii' )
        except UnicodeEncodeError as e:
            raise ValueError( e )
        if not re.match( self.namespace_re, namespace ):
            raise ValueError( "Invalid namespace '%s'" % namespace )

        self.namespace = namespace

    def is_absolute_name( self, name ):
        return self.namespace is None or name[ 0:1 ] == '/'

    def absolute_name( self, name ):
        """
        Returns the absolute form of the specified resource name. If the specified name is
        already absolute, that name will be returned unchanged, otherwise the given name will be
        prefixed with the namespace this object was configured with.

        Relative names starting with underscores are disallowed.

        >>> ctx = Context(namespace='/')
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

        >>> ctx = Context(namespace='/foo/')
        >>> ctx.absolute_name('bar')
        '/foo/bar'
        >>> ctx.absolute_name('bar/')
        '/foo/bar/'
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
        if not self.path_re.match( result ):
            raise ValueError( "Invalid path '%s'" % result )
        return result


    def config_file_path( self, path_components, mkdir=False ):
        """
        Returns the absolute path to a local configuration file. If this context is
        namespace-aware, configuration files will be located in a namespace-specific subdirectory.

        >>> os.environ['HOME']='/home/foo'

        >>> ctx = Context(namespace='/')
        >>> ctx.config_file_path(['foo'])
        '/home/foo/.config/docrunner/_namespaces/_root/foo'
        >>> ctx.config_file_path(['foo','bar'])
        '/home/foo/.config/docrunner/_namespaces/_root/foo/bar'

        >>> ctx = Context(namespace='/hannes/')
        >>> ctx.config_file_path(['foo'])
        '/home/foo/.config/docrunner/_namespaces/hannes/foo'
        >>> ctx.config_file_path(['foo','bar'])
        '/home/foo/.config/docrunner/_namespaces/hannes/foo/bar'

        >>> ctx = Context(namespace='/hannes/test/')
        >>> ctx.config_file_path(['foo'])
        '/home/foo/.config/docrunner/_namespaces/hannes/test/foo'
        >>> ctx.config_file_path(['foo','bar'])
        '/home/foo/.config/docrunner/_namespaces/hannes/test/foo/bar'

        """
        if self.namespace is not None:
            bare_ns = self.namespace[ 1:-1 ]
            if not bare_ns:
                path_components[ 0:0 ] = [ '_root' ]
            else:
                path_components[ 0:0 ] = bare_ns.split( '/' )
            path_components[ 0:0 ] = [ '_namespaces' ]
        file_path = config_file_path( path_components, mkdir=mkdir )
        return file_path

    @staticmethod
    def ssh_pubkey_s3_key( fingerprint ):
        return 'ssh_pubkey:%s' % fingerprint

    def upload_ssh_pubkey( self, ssh_pubkey, fingerprint ):
        s3_conn = s3.connect_to_region( self.region )
        try:
            bucket = s3_conn.lookup( self.s3_bucket_name )
            if bucket is None:
                bucket = s3_conn.create_bucket( self.s3_bucket_name,
                                                location=self.region )
            s3_entry = Key( bucket )
            s3_entry.key = self.ssh_pubkey_s3_key( fingerprint )
            s3_entry.set_contents_from_string( ssh_pubkey )
        finally:
            s3_conn.close( )

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
        ec2_conn = ec2.connect_to_region( self.region )
        try:
            fingerprint = ec2_keypair_fingerprint( ssh_pubkey )
            ec2_keypair = ec2_conn.get_key_pair( ec2_keypair_name )
            if ec2_keypair is not None:
                if ec2_keypair.name != ec2_keypair_name:
                    raise AssertionError( "Key pair names don't match." )
                if ec2_keypair.fingerprint != fingerprint:
                    if force:
                        ec2_conn.delete_key_pair( ec2_keypair_name )
                        ec2_keypair = None
                    else:
                        raise UserError(
                            "Key pair %s already exists in EC2, but its fingerprint %s is "
                            "different from the fingerprint %s of the key to be imported. Use "
                            "the force option to overwrite the existing key pair." %
                            ( ec2_keypair.name, ec2_keypair.fingerprint, fingerprint ) )

            self.upload_ssh_pubkey( ssh_pubkey, fingerprint )

            if ec2_keypair is None:
                ec2_keypair = ec2_conn.import_key_pair( ec2_keypair_name, ssh_pubkey )
            assert ec2_keypair.fingerprint == fingerprint
            return ec2_keypair
        finally:
            ec2_conn.close( )

    def expand_keypair_globs( self, globs, ec2_connection=None ):
        """
        Returns a list of EC2 key pair objects matching the specified globs. The order of the
        objects in the returned list will be consistent with the order of the globs and it will
        not contain any elements more than once. In other words, the returned set will start with
        all key pairs matching the first glob, followed by key pairs matching the second glob but
        not the first glob and so on.

        :rtype: list of Keypair
        """
        if ec2_connection is None:
            ec2_conn = ec2.connect_to_region( self.region )
        else:
            ec2_conn = ec2_connection
        try:
            result = [ ]
            keypairs = dict( (keypair.name, keypair) for keypair in ec2_conn.get_all_key_pairs( ) )
            for glob in globs:
                i = len( result )
                for name, keypair in keypairs.iteritems( ):
                    if fnmatch.fnmatch( name, glob ):
                        result.append( keypair )

                # since we can't modify the set during iteration
                for keypair in result[ i: ]:
                    keypairs.pop( keypair.name )
            return result
        finally:
            if ec2_conn != ec2_connection:
                ec2_conn.close( )

    def download_ssh_pubkey( self, ec2_keypair ):
        s3_conn = s3.connect_to_region( self.region )
        try:
            try:
                bucket = s3_conn.get_bucket( self.s3_bucket_name )
                s3_entry = Key( bucket )
                s3_entry.key = self.ssh_pubkey_s3_key( ec2_keypair.fingerprint )
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
            if fingerprint_len == 20: # 160 bit SHA-1
                # The fingerprint is that of a private key. We can't get at the private key so we
                # can't verify the public key either. So this is inherently insecure. However,
                # remember that the only reason why we are dealing with n EC2-generated private
                # key is that the Jenkins' EC2 plugin expects a 20 byte fingerprint. See
                # https://issues.jenkins-ci.org/browse/JENKINS-20142 for details. Once that issue
                # is fixed, we can switch back to just using imported keys and 16-byte fingerprints.
                pass
            elif fingerprint_len == 16: # 128 bit MD5
                fingerprint = ec2_keypair_fingerprint( ssh_pubkey )
                if ec2_keypair.fingerprint != fingerprint:
                    raise UserError(
                        "Fingerprint mismatch for key %s! Expected %s but got %s. The EC2 keypair "
                        "doesn't match the public key stored in S3." %
                        ( ec2_keypair.name, ec2_keypair.fingerprint, fingerprint ) )
            return ssh_pubkey
        finally:
            s3_conn.close( )

    @staticmethod
    def to_sns_name( name ):
        """
        :type name: str|unicode

        >>> Context.to_sns_name('/foo/bar')
        '_2ffoo_2fbar'
        >>> Context.to_sns_name('/foo\\tbar')
        '_2ffoo_09bar'
        >>> Context.to_sns_name('_')
        '_5f'
        >>> Context.to_sns_name('-') == '-'
        True
        >>> import string
        >>> Context.to_sns_name(string.ascii_letters) == string.ascii_letters
        True
        >>> Context.to_sns_name(string.digits) == string.digits
        True
        """

        def f( c ):
            """
            :type c: str
            """
            if c.isalpha( ) or c == '-' or c.isdigit( ):
                return c
            else:
                return "_" + hex( ord( c ) )[ 2: ].zfill( 2 )

        return ''.join( map( f, name.encode( 'ascii' ) ) )


    @staticmethod
    def from_sns_name( name ):
        """
        :type name: str|unicode

        >>> Context.from_sns_name( '_2ffoo_2fbar' )
        '/foo/bar'

        >>> Context.from_sns_name( '_2ffoo_09bar' )
        '/foo\\tbar'

        >>> Context.from_sns_name( 'foo_bar' ) # 0xBA is not a valid ASCII code point
        Traceback (most recent call last):
        ....
        UnicodeDecodeError: 'ascii' codec can't decode byte 0xba in position 3: ordinal not in range(128)

        >>> Context.from_sns_name('-') == '-'
        True

        >>> import string
        >>> Context.from_sns_name(string.ascii_letters) == string.ascii_letters
        True

        >>> Context.from_sns_name(string.digits) == string.digits
        True
        """
        subs = name.split( '_' )
        return ''.join( itertools.chain( ( subs[ 0 ], ),
                                         ( chr( int( sub[ :2 ], 16 ) ) + sub[ 2: ]
                                             for sub in subs[ 1: ] ) ) ).encode( 'ascii' )

    def agent_topic_name( self ):
        return self.to_sns_name( self.absolute_name( "cghub_cloud_agent" ) )

    def agent_queue_name( self ):
        return self.to_sns_name(
            self.agent_topic_name( ) + "/" + socket.gethostname( ).replace( '.', '-' ) )

    @staticmethod
    @memoize
    def iam_user_name( ):
        conn = None
        try:
            conn = iam.connect_to_region( 'universal' )
            return conn.get_user( )[ 'get_user_response' ][ 'get_user_result' ][ 'user' ][
                'user_name' ]
        except:
            return None
        finally:
            if conn is not None:
                conn.close( )


def config_file_path( path_components, mkdir=False ):
    """
    Returns the path of a configuration file. In accordance with freedesktop.org's XDG Base
    `Directory Specification <http://standards.freedesktop.org/basedir-spec/basedir-spec-latest
    .html>`_, the configuration files are located in the ~/.config/cgcloud directory.

    :param path_components: EITHER a string containing the desired name of the
    configuration file OR an iterable of strings, the last component of which denotes the desired
    name of the config file, all preceding components denoting a chain of nested subdirectories
    of the config directory.

    :param mkdir: if True, this method ensures that all directories in the returned path exist,
    creating them if necessary

    :return: the full path to the configuration file

    >>> os.environ['HOME']='/home/foo'

    >>> config_file_path(['bar'])
    '/home/foo/.config/cgcloud/bar'

    >>> config_file_path(['dir','file'])
    '/home/foo/.config/cgcloud/dir/file'
    """
    default_config_dir_path = os.path.join( os.path.expanduser( '~' ), '.config' )
    config_dir_path = os.environ.get( 'XDG_CONFIG_HOME', default_config_dir_path )
    app_config_dir_path = os.path.join( config_dir_path, app_name( ) )
    path = os.path.join( app_config_dir_path, *path_components )
    if mkdir: mkdir_p( os.path.dirname( path ) )
    return path


