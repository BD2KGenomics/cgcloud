import os
import re
from boto import ec2, s3
from boto.exception import S3ResponseError
from boto.s3.key import Key
from cghub.util import ec2_keypair_fingerprint, UserError, mkdir_p, app_name


class Environment:
    """
    Encapsulates all EC2-specific settings used by components in this project
    """
    s3_bucket_name = 'cghub-cloud-utils.cghub.ucsc.edu'

    availability_zone_re = re.compile( r'^([a-z]{2}-[a-z]+-[1-9][0-9]*)([a-z])$' )

    def __init__(self, availability_zone='us-west-1b', namespace='/'):
        """
        Create an Environment object.

        :param availability_zone: The availability zone to place EC2 resources like volumes and
        instances into. The AWS region to operate in is implied by this parameter since the
        region is a prefix of the availability zone string

        :param namespace: An optional prefix for names of EC2 resources. Unless the namespace is
        None, all relative resource names will be prefixed with the given namespace,
        making them absolute. A relative name is a one that doesn't start with a slash. A
        namespace of '' or None disables the prefixing and the distinction between relative and
        absolute names. If the namespace is not None or '', it should be a string starting and
        ending in a slash, although those will be added automatically if they are missing. A
        namespace may contain the '/' character in positions other than at the beginning or end
        of the namespace.. The parts of the namespace in between the '/' are referred to as
        components. Components may not start with an underscore. Empty components are removed.


        >>> Environment(namespace=None).namespace is None
        True

        >>> Environment(namespace='').namespace is None
        True

        >>> Environment(namespace='/').namespace
        '/'

        >>> Environment(namespace='hannes').namespace
        '/hannes/'

        >>> Environment(namespace='/hannes').namespace
        '/hannes/'

        >>> Environment(namespace='/hannes/').namespace
        '/hannes/'

        >>> Environment(namespace='//////').namespace
        '/'

        >>> Environment(namespace='h//a//n//n//e//s').namespace
        '/h/a/n/n/e/s/'

        >>> Environment(namespace='/_hannes/').namespace
        Traceback (most recent call last):
        ....
        RuntimeError: Namespace component may not start with '_'

        >>> Environment(namespace='/han/_nes/').namespace
        Traceback (most recent call last):
        ....
        RuntimeError: Namespace component may not start with '_'

        >>> Environment(namespace='_hannes').namespace
        Traceback (most recent call last):
        ....
        RuntimeError: Namespace component may not start with '_'
        """

        self.availability_zone = availability_zone
        m = self.availability_zone_re.match( availability_zone )
        if not m:
            raise UserError( "Can't extract region from availability-zone '%s'"
                             % availability_zone )
        self.region = m.group( 1 )
        if namespace == '':
            namespace = None
        if namespace is not None:
            namespace = self.__normalize_namespace( namespace )
        self.namespace = namespace

    def __normalize_namespace(self, namespace):
        components = [ c for c in namespace.split( '/' ) if c ]
        if any( c[ 0:1 ] == '_' for c in components ):
            raise UserError( "Namespace component may not start with '_'" )
        namespace = '/' + '/'.join( components ) + '/' if components else '/'
        return namespace

    def is_absolute_name(self, name):
        return self.namespace is None or name[ 0:1 ] == '/'

    def absolute_name(self, name):
        """
        Returns the absolute form of the specified resource name. If the specified name is
        already absolute, that name will be returned unchanged, otherwise the given name will be
        prefixed with the namespace this object was configured with, unless the namespace is None.

        Relative names starting with underscores are disallowed.

        >>> env = Environment(namespace='/')
        >>> env.absolute_name('foo')
        '/foo'
        >>> env.absolute_name('/foo')
        '/foo'
        >>> env.absolute_name('')
        '/'
        >>> env.absolute_name('/')
        '/'
        >>> env.absolute_name('_foo')
        Traceback (most recent call last):
        ....
        RuntimeError: Resource names may not start with _

        >>> env = Environment(namespace='/hannes/')
        >>> env.absolute_name('foo')
        '/hannes/foo'
        >>> env.absolute_name('/foo')
        '/foo'
        >>> env.absolute_name('')
        '/hannes/'
        >>> env.absolute_name('/')
        '/'
        >>> env.absolute_name('_foo')
        Traceback (most recent call last):
        ....
        RuntimeError: Resource names may not start with _

        >>> env = Environment(namespace=None)
        >>> env.absolute_name('foo')
        'foo'
        >>> env.absolute_name('/foo')
        '/foo'
        >>> env.absolute_name('')
        ''
        >>> env.absolute_name('/')
        '/'
        >>> env.absolute_name('_foo')
        Traceback (most recent call last):
        ....
        RuntimeError: Resource names may not start with _
        """
        if name[ 0:1 ] == '_':
            raise UserError( 'Resource names may not start with _' )
        if self.is_absolute_name( name ):
            return name
        else:
            return self.namespace + name


    def config_file_path(self, path_components, mkdir=False):
        """
        Returns the absolute path to a local configuration file. If this environment is
        namespace-aware, configuration files will be located in a namespace-specific subdirectory.

        >>> os.environ['HOME']='/home/hannes'

        >>> env = Environment(namespace='/')
        >>> env.config_file_path(['foo'])
        '/home/hannes/.config/cgcloud/_namespaces/_root/foo'
        >>> env.config_file_path(['foo','bar'])
        '/home/hannes/.config/cgcloud/_namespaces/_root/foo/bar'

        >>> env = Environment(namespace='/hannes/')
        >>> env.config_file_path(['foo'])
        '/home/hannes/.config/cgcloud/_namespaces/hannes/foo'
        >>> env.config_file_path(['foo','bar'])
        '/home/hannes/.config/cgcloud/_namespaces/hannes/foo/bar'

        >>> env = Environment(namespace=None)
        >>> env.config_file_path(['foo'])
        '/home/hannes/.config/cgcloud/foo'
        >>> env.config_file_path(['foo','bar'])
        '/home/hannes/.config/cgcloud/foo/bar'

        >>> env = Environment(namespace='/hannes/test/')
        >>> env.config_file_path(['foo'])
        '/home/hannes/.config/cgcloud/_namespaces/hannes/test/foo'
        >>> env.config_file_path(['foo','bar'])
        '/home/hannes/.config/cgcloud/_namespaces/hannes/test/foo/bar'

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


    def ssh_pubkey_s3_key(self, fingerprint):
        return 'ssh_pubkey:%s' % fingerprint

    def upload_ssh_pubkey(self, ec2_keypair_name, ssh_pubkey, force=False):
        """
        Import the given OpenSSH public key  as a 'key pair' into EC2. The term 'key pair' is
        misleading since imported 'key pairs' are really just public keys. For generated EC2 key
        pairs Amazon also stores the private key, so the name makes more sense for those.

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
            s3_conn = s3.connect_to_region( self.region )
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

                bucket = s3_conn.lookup( self.s3_bucket_name )
                if bucket is None:
                    bucket = s3_conn.create_bucket( self.s3_bucket_name,
                                                    location=self.region )
                s3_entry = Key( bucket )
                s3_entry.key = self.ssh_pubkey_s3_key( fingerprint )
                s3_entry.set_contents_from_string( ssh_pubkey )

                if ec2_keypair is None:
                    ec2_keypair = ec2_conn.import_key_pair( ec2_keypair_name, ssh_pubkey )
                assert ec2_keypair.fingerprint == fingerprint
                return ec2_keypair
            finally:
                s3_conn.close( )
        finally:
            ec2_conn.close( )

    def download_ssh_pubkey(self, ec2_keypair_name):
        ec2_conn = ec2.connect_to_region( self.region )
        try:
            s3_conn = s3.connect_to_region( self.region )
            try:
                keypair = ec2_conn.get_key_pair( ec2_keypair_name )
                if keypair is None:
                    raise UserError( "No such EC2 key pair: %s" % ec2_keypair_name )
                if keypair.name != ec2_keypair_name:
                    raise AssertionError( "Key pair names don't match." )
                try:
                    bucket = s3_conn.get_bucket( self.s3_bucket_name )
                    s3_entry = Key( bucket )
                    s3_entry.key = self.ssh_pubkey_s3_key( keypair.fingerprint )
                    ssh_pubkey = s3_entry.get_contents_as_string( )
                except S3ResponseError as e:
                    if e.status == 404:
                        raise UserError(
                            "There is no matching SSH pub key stored in S3 for EC2 key pair %s. "
                            "Has it been uploaded using the upload-key command?" %
                            ec2_keypair_name )
                    else:
                        raise
                fingerprint = ec2_keypair_fingerprint( ssh_pubkey )
                if keypair.fingerprint != fingerprint:
                    raise UserError(
                        "Fingerprint mismatch for key %s! Expected %s but got %s. The EC2 keypair "
                        "doesn't match the public key stored in S3." %
                        ( keypair.name, keypair.fingerprint, fingerprint ) )
                else:
                    return ssh_pubkey
            finally:
                s3_conn.close( )
        finally:
            ec2_conn.close( )


def config_file_path(path_components, mkdir=False):
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

    >>> os.environ['HOME']='/home/hannes'

    >>> config_file_path(['bar'])
    '/home/hannes/.config/cgcloud/bar'

    >>> config_file_path(['dir','file'])
    '/home/hannes/.config/cgcloud/dir/file'
    """
    default_config_dir_path = os.path.join( os.path.expanduser( '~' ), '.config' )
    config_dir_path = os.environ.get( 'XDG_CONFIG_HOME', default_config_dir_path )
    app_config_dir_path = os.path.join( config_dir_path, app_name( ) )
    path = os.path.join( app_config_dir_path, *path_components )
    if mkdir: mkdir_p( os.path.dirname( path ) )
    return path


