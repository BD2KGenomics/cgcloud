# Not doing this as a dict or namedtuple such that I can document each required attribute
import os
import re
from cghub.cloud import config_file_path


class Environment:
    """
    Encapsulates all EC2-specific settings used by components in this project
    """

    availability_zone_re = re.compile( r'^([a-z]{2}-[a-z]+-[1-9][0-9]*)([a-z])$' )

    def __init__(self,
                 availability_zone='us-west-1b',
                 instance_type='t1.micro',
                 ssh_key_name=None,
                 namespace='/'):
        """
        Create an Environment object.

        :param availability_zone: The availability zone to place EC2 resources like volumes and
        instances into. The AWS region to operate in is implied by this parameter since the
        region is a prefix of the availability zone string

        :param instance_type: The type of instance to create, e.g. m1.small or t1.micro.

        :param ssh_key_name: The name of the SSH public key to inject into the instance

        :param namespace: An optional prefix for names of EC2 resources. Unless the namespace is
        None, all relative resource names will be prefixed with the given namespace,
        making them absolute. A relative name is a one that doesn't start with a slash. A
        namespace of None disables the prefixing and the distinction between relative and
        absolute names. If the namespace is not None, it should be a string starting and ending
        in a slash, although those will be added automatically if they are missing. The part of
        the namespace between the two slashes is referred to as the bare namespace. A bare
        namespace may not start with an underscore.


        >>> Environment(namespace=None).namespace is None
        True

        >>> Environment(namespace='').namespace
        '/'

        >>> Environment(namespace='/').namespace
        '/'

        >>> Environment(namespace='hannes').namespace
        '/hannes/'

        >>> Environment(namespace='/hannes').namespace
        '/hannes/'

        >>> Environment(namespace='/hannes/').namespace
        '/hannes/'

        >>> Environment(namespace='/_hannes/').namespace
        Traceback (most recent call last):
        ....
        RuntimeError: Bare namespace may not start with _

        >>> Environment(namespace='_hannes').namespace
        Traceback (most recent call last):
        ....
        RuntimeError: Bare namespace may not start with _
        """

        self.availability_zone = availability_zone
        m = self.availability_zone_re.match( availability_zone )
        if not m:
            raise RuntimeError(
                "Can't extract region from availability-zone '%s'" % availability_zone )
        self.region = m.group( 1 )
        self.instance_type = instance_type
        self.ssh_key_name = ssh_key_name
        if namespace is not None:
            if namespace[ 0:1 ] != '/': namespace = '/' + namespace
            if namespace[ -1: ] != '/': namespace += '/'
            if namespace[ 1:2 ] == '_':
                raise RuntimeError( 'Bare namespace may not start with _' )
        self.namespace = namespace

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
            raise RuntimeError( 'Resource names may not start with _' )
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
