import argparse
import base64
import hashlib
import logging
import multiprocessing
import multiprocessing.pool
import os
import re
import struct
import subprocess
import sys
from StringIO import StringIO
from abc import ABCMeta, abstractmethod
from collections import Sequence
from itertools import islice, count
from math import sqrt
from textwrap import dedent

from bd2k.util.iterables import concat
from bd2k.util.strings import interpolate

log = logging.getLogger( __name__ )

try:
    from cgcloud.crypto.PublicKey import RSA
except ImportError:
    from cgcloud_Crypto.PublicKey import RSA

cores = multiprocessing.cpu_count( )


def unpack_singleton( singleton ):
    """
    Expects a iterable with exactly one element and returns that element. If the iterable is
    empty or yields more than one element an exception will be thrown.

    >>> unpack_singleton([0])
    0

    >>> unpack_singleton([])
    Traceback (most recent call last):
    ....
    RuntimeError: Expected singleton, got empty iterable

    >>> unpack_singleton([0,1])
    Traceback (most recent call last):
    ....
    RuntimeError: Expected singleton, got iterable with more than one element
    """
    it = iter( singleton )
    try:
        result = it.next( )
    except StopIteration:
        raise RuntimeError( "Expected singleton, got empty iterable" )
    try:
        it.next( )
        raise RuntimeError( "Expected singleton, got iterable with more than one element" )
    except StopIteration:
        return result


def mean( xs ):
    """
    Return the mean value of a sequence of values.

    >>> mean([2,4,4,4,5,5,7,9])
    5.0
    >>> mean([9,10,11,7,13])
    10.0
    >>> mean([1,1,10,19,19])
    10.0
    >>> mean([10,10,10,10,10])
    10.0
    >>> mean([1,"b"])
    Traceback (most recent call last):
      ...
    ValueError: Input can't have non-numeric elements
    >>> mean([])
    Traceback (most recent call last):
      ...
    ValueError: Input can't be empty
    """
    try:
        return sum( xs ) / float( len( xs ) )
    except TypeError:
        raise ValueError( "Input can't have non-numeric elements" )
    except ZeroDivisionError:
        raise ValueError( "Input can't be empty" )


def std_dev( xs ):
    """
    Returns the standard deviation of the given iterable of numbers.

    From http://rosettacode.org/wiki/Standard_deviation#Python

    An empty list, or a list with non-numeric elements will raise a TypeError.

    >>> std_dev([2,4,4,4,5,5,7,9])
    2.0

    >>> std_dev([9,10,11,7,13])
    2.0

    >>> std_dev([1,1,10,19,19])
    8.049844718999243

    >>> std_dev({1,1,10,19,19}) == std_dev({19,10,1})
    True

    >>> std_dev([10,10,10,10,10])
    0.0

    >>> std_dev([1,"b"])
    Traceback (most recent call last):
    ...
    ValueError: Input can't have non-numeric elements

    >>> std_dev([])
    Traceback (most recent call last):
    ...
    ValueError: Input can't be empty
    """
    m = mean( xs )  # this checks our pre-conditions, too
    return sqrt( sum( (x - m) ** 2 for x in xs ) / float( len( xs ) ) )


def camel_to_snake( s, separator='_' ):
    """
    Converts camel to snake case

    >>> camel_to_snake('CamelCase')
    'camel_case'

    >>> camel_to_snake('Camel_Case')
    'camel_case'

    >>> camel_to_snake('camelCase')
    'camel_case'

    >>> camel_to_snake('USA')
    'usa'

    >>> camel_to_snake('TeamUSA')
    'team_usa'

    >>> camel_to_snake('Team_USA')
    'team_usa'

    >>> camel_to_snake('R2D2')
    'r2_d2'

    >>> camel_to_snake('ToilPre310Box',separator='-')
    'toil-pre-310-box'

    >>> camel_to_snake('Toil310Box',separator='-')
    'toil-310-box'
    """
    s = re.sub( '([a-z0-9])([A-Z])', r'\1%s\2' % separator, s )
    s = re.sub( '([a-z])([A-Z0-9])', r'\1%s\2' % separator, s )
    return s.lower( )


def snake_to_camel( s, separator='_' ):
    """
    Converts snake to camel case

    >>> snake_to_camel('')
    ''

    >>> snake_to_camel('_x____yz')
    'XYz'

    >>> snake_to_camel('camel_case')
    'CamelCase'

    >>> snake_to_camel('r2_d2')
    'R2D2'

    >>> snake_to_camel('m1.small', '.')
    'M1Small'
    """
    return ''.join( [ w.capitalize( ) for w in s.split( separator ) ] )


def abreviated_snake_case_class_name( cls, root_cls=object ):
    """
    Returns the snake-case (with '-' instead of '_') version of the name of a given class with
    the name of another class removed from the end.

    :param cls: the class whose name to abreviate

    :param root_cls: an ancestor of cls, whose name will be removed from the end of the name of cls

    :return: cls.__name__ with root_cls.__name__ removed, converted to snake case with - as the
    separator

    >>> class Dog: pass
    >>> abreviated_snake_case_class_name(Dog)
    'dog'
    >>> class Dog: pass
    >>> abreviated_snake_case_class_name(Dog,Dog)
    ''
    >>> class BarkingDog(Dog): pass
    >>> abreviated_snake_case_class_name(BarkingDog,Dog)
    'barking'
    >>> class SleepingGrowlingDog(Dog): pass
    >>> abreviated_snake_case_class_name(SleepingGrowlingDog,Dog)
    'sleeping-growling'
    >>> class Lumpi(SleepingGrowlingDog): pass
    >>> abreviated_snake_case_class_name(Lumpi,Dog)
    'lumpi'
    """
    name = cls.__name__
    suffix = root_cls.__name__
    if name.endswith( suffix ): name = name[ :-len( suffix ) ]
    return camel_to_snake( name, separator='-' )


class UserError( RuntimeError ):
    def __init__( self, message=None, cause=None ):
        if message is None == cause is None:
            raise RuntimeError( "Must pass either message or cause." )
        super( UserError, self ).__init__( message if cause is None else cause.message )


def app_name( ):
    return os.path.splitext( os.path.basename( sys.argv[ 0 ] ) )[ 0 ]


class Application( object ):
    """
    An attempt at modularizing command line parsing (argparse). This is an experiment. The
    general idea is to expose an application's functionality on the command line as separate
    subcommands, each subcommmand is represented by a separate class each of which gets its own
    subparser (an argparse concept). This collects both, the subcommand's functionality and the
    code that sets up the command line interface to that functionality under the umbrella of a
    single class.

    >>> class FooCommand( Command ):
    ...     def __init__(self, app):
    ...         super( FooCommand, self ).__init__( app, help='Do some voodoo' )
    ...         self.option( '--verbose', action='store_true' )
    ...
    ...     def run(self, options):
    ...         print 'Voodoo Magic' if options.verbose else 'Juju'

    >>> app = Application()
    >>> app.add( FooCommand )
    >>> app.run( [ "foo", "--verbose" ] ) # foo is the command name
    Voodoo Magic
    >>> app.run( [ "foo" ] )
    Juju
    """

    def __init__( self ):
        """
        Initializes the argument parser
        """
        super( Application, self ).__init__( )
        self.args = None
        self.parser = argparse.ArgumentParser( formatter_class=ArgParseHelpFormatter )
        # noinspection PyProtectedMember
        self.parser._positionals.title = 'Commands'
        # noinspection PyProtectedMember
        self.parser._optionals.title = 'Global options'
        self.subparsers = self.parser.add_subparsers( help='Application commands',
                                                      dest='command_name' )
        self.commands = { }

    def option( self, *args, **kwargs ):
        self._option( self.parser, args, kwargs )

    @classmethod
    def _option( cls, target, args, kwargs ):
        try:
            completer = kwargs.pop( 'completer' )
        except KeyError:
            completer = None
        argument = target.add_argument( *args, **kwargs )
        if completer is not None:
            argument.completer = completer

    def add( self, command_class ):
        """
        Instantiates a command of the specified class and adds it to this application.
        """
        command = command_class( self )
        self.commands[ command.name( ) ] = command

    def run( self, args=None ):
        """
        Parses the command line into an options object using arparse and invokes the requested
        command's run() method with that options object.
        """
        # Pull in bash auto completion if available
        try:
            # noinspection PyUnresolvedReferences
            import argcomplete
        except ImportError:
            pass
        else:
            argcomplete.autocomplete( self.parser )
        self.args = args
        options = self.parser.parse_args( args )
        self.prepare( options )
        command = self.commands[ options.command_name ]
        command.run( options )

    def prepare( self, options ):
        pass


class Command( object ):
    """
    An abstract base class for an applications commands.
    """

    __metaclass__ = ABCMeta

    @abstractmethod
    def run( self, options ):
        """
        Execute this command.

        :param options: the parsed command line arguments
        """
        raise NotImplementedError( )

    def __init__( self, application, **kwargs ):
        """
        Initializes this command.
        :param application: The application this command belongs to.
        :type application: Application
        :param kwargs: optional arguments to the argparse's add_parser() method
        """
        super( Command, self ).__init__( )
        self.application = application
        doc = self.__class__.__doc__
        help_ = doc.split( '\n\n', 1 )[ 0 ] if doc else None
        if not 'help' in kwargs:
            kwargs[ 'help' ] = help_
        if not 'description' in kwargs:
            kwargs[ 'description' ] = doc
        self.parser = application.subparsers.add_parser(
            self.name( ),
            formatter_class=ArgParseHelpFormatter,
            **kwargs )
        # noinspection PyProtectedMember
        self.parser._positionals.title = 'Command arguments'
        # noinspection PyProtectedMember
        self.parser._optionals.title = 'Command options'
        self.group = None

    def option( self, *args, **kwargs ):
        target = self.parser if self.group is None else self.group
        # noinspection PyProtectedMember
        self.application._option( target, args, kwargs )

    def name( self ):
        """
        Returns the name of this command as referred to by the user when invoking it via the
        command line. The command name is the snake-case version (with dashes instead of
        underscores) of this command's class name, minus its 'Command' suffix.

        >>> class FooBarCommand(Command):
        ...    def run( self, options  ):
        ...        pass
        >>> app=Application()
        >>> FooBarCommand(app).name()
        'foo-bar'
        """
        # noinspection PyTypeChecker
        return abreviated_snake_case_class_name( type( self ), Command )

    def begin_mutex( self, **kwargs ):
        self.group = self.parser.add_mutually_exclusive_group( **kwargs )

    def end_mutex( self ):
        self.group = None


class ArgParseHelpFormatter( argparse.ArgumentDefaultsHelpFormatter ):
    # noinspection PyBroadException
    try:
        with open( os.devnull, 'a' ) as devnull:
            rows, columns = map( int, subprocess.check_output( [ 'stty', 'size' ],
                                                               stderr=devnull ).split( ) )
    except:
        rows, columns = None, None

    def __init__( self, *args, **kwargs ):
        super( ArgParseHelpFormatter, self ).__init__( *args,
                                                       width=min( 100, self.columns ),
                                                       max_help_position=30,
                                                       **kwargs )


empty_line_re = re.compile( r'^\s*(#.*)$' )


def prepend_shell_script( script, in_file, out_file ):
    """
    Writes all lines from the specified input to the specified output. Input and output are both
    assumed to be file-like objects. Reading from the input as well as writing to the output
    starts at the current position in the respective file-like object. Unless the given script is
    empty or None, and before writing the first script line from the input, the given script
    will be written to the output, followed by a new line.  A script line is a line that is not
    empty. An empty line is a line that contains only whitespace, a comment or both.

    >>> i,o = StringIO(''), StringIO()
    >>> prepend_shell_script('hello',i,o)
    >>> o.getvalue()
    'hello\\n'

    >>> i,o = StringIO(''), StringIO()
    >>> prepend_shell_script('',i,o)
    >>> o.getvalue()
    ''

    >>> i,o = StringIO('\\n'), StringIO()
    >>> prepend_shell_script('hello',i,o)
    >>> o.getvalue()
    'hello\\n\\n'

    >>> i,o = StringIO('#foo\\n'), StringIO()
    >>> prepend_shell_script('hello',i,o)
    >>> o.getvalue()
    '#foo\\nhello\\n'

    >>> i,o = StringIO(' # foo \\nbar\\n'), StringIO()
    >>> prepend_shell_script('hello',i,o)
    >>> o.getvalue()
    ' # foo \\nhello\\nbar\\n'

    >>> i,o = StringIO('bar\\n'), StringIO()
    >>> prepend_shell_script('hello',i,o)
    >>> o.getvalue()
    'hello\\nbar\\n'

    >>> i,o = StringIO('#foo'), StringIO()
    >>> prepend_shell_script('hello',i,o)
    >>> o.getvalue()
    '#foo\\nhello\\n'

    >>> i,o = StringIO('#foo\\nbar # bla'), StringIO()
    >>> prepend_shell_script('hello',i,o)
    >>> o.getvalue()
    '#foo\\nhello\\nbar # bla\\n'

    >>> i,o = StringIO(' bar # foo'), StringIO()
    >>> prepend_shell_script('hello',i,o)
    >>> o.getvalue()
    'hello\\n bar # foo\\n'
    """

    def write_line( line ):
        out_file.write( line )
        if not line.endswith( '\n' ):
            out_file.write( '\n' )

    line = None
    for line in in_file:
        if not empty_line_re.match( line ): break
        write_line( line )
        line = None
    if script: write_line( script )
    if line: write_line( line )
    for line in in_file:
        write_line( line )


def partition_seq( seq, size ):
    """
    Splits a sequence into an iterable of subsequences. All subsequences are of the given size,
    except the last one, which may be smaller. If the input list is modified while the returned
    list is processed, the behavior of the program is undefined.

    :param seq: the list to split
    :param size: the desired size of the sublists, must be > 0
    :type size: int
    :return: an iterable of sublists

    >>> list(partition_seq("",1))
    []
    >>> list(partition_seq("abcde",2))
    ['ab', 'cd', 'e']
    >>> list(partition_seq("abcd",2))
    ['ab', 'cd']
    >>> list(partition_seq("abcde",1))
    ['a', 'b', 'c', 'd', 'e']
    >>> list(partition_seq("abcde",0))
    Traceback (most recent call last):
    ...
    ValueError: Size must be greater than 0
    >>> l=[1,2,3,4]
    >>> i = iter( partition_seq(l,2) )
    >>> l.pop(0)
    1
    >>> i.next()
    [2, 3]
    """
    if size < 1:
        raise ValueError( 'Size must be greater than 0' )
    return (seq[ pos:pos + size ] for pos in xrange( 0, len( seq ), size ))


def ec2_keypair_fingerprint( ssh_key, reject_private_keys=False ):
    """
    Computes the fingerrint of a public or private OpenSSH key in the way Amazon does it for
    keypairs resulting from either importing a SSH public key or generating a new keypair.

    :param ssh_key: a RSA public key in OpenSSH format, or an RSA private key in PEM format

    :return: The fingerprint of the key, in pairs of two hex digits with a colon between
    pairs.

    >>> ssh_pubkey = 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCvdDMvcwC1/5ByUhO1wh1sG6ficwgGHRab/p'\\
    ... 'm6LN60rgxv+u2eJRao2esGB9Oyt863+HnjKj/NBdaiHTHcAHNq/TapbvEjgHaKgrVdfeMdQbJhWjJ97rql9Yn8k'\\
    ... 'TNsXOeSyTW7rIKE0zeQkrwhsztmATumbQmJUMR7uuI31BxhQUfD/CoGZQrxFalWLDZcrcYY13ynplaNA/Hd/vP6'\\
    ... 'qWO5WC0dTvzROEp7VwzJ7qeN2kP1JTh+kgVRoYd9mSm6x9UVjY6jQtZHa01Eg05sFraWgvNAvKhk9LS9Kiwhq8D'\\
    ... 'xHdWdTamnGLtwXYQbn7RjG3UADAiTOWk+QSmU2igZvQ2F hannes@soe.ucsc.edu\\n'
    >>> ec2_keypair_fingerprint(ssh_pubkey)
    'a5:5a:64:8a:1e:3f:4e:46:cd:1f:e9:b3:fc:cf:c5:19'

    >>> # This is not a private key that is in use, in case you were wondering
    >>> ssh_private_key = \\
    ... '-----BEGIN RSA PRIVATE KEY-----\\n'+\\
    ... 'MIIEpQIBAAKCAQEAi3shPK00+/6dwW8u+iDkUYiwIKl/lv0Ay5IstLszwb3CA4mVRlyq769HzE8f\\n'\\
    ... 'cnzQUX/NI8y9MTO0UNt2JDMJWW5L49jmvxV0TjxQjKg8KcNzYuHsEny3k8LxezWMsmwlrrC89O6e\\n'\\
    ... 'oo6boc8ForSdjVdIlJbvWu/82dThyFgTjWd5B+1O93xw8/ejqY9PfZExBeqpKjm58OUByTpVhvWe\\n'\\
    ... 'jmbZ9BL60XJhwz9bDTrlKpjcGsMZ74G6XfQAhyyqXYeD/XOercCSJgQ/QjYKcPE9yMRyucHyuYZ8\\n'\\
    ... 'HKzmG+u4p5ffnFb43tKzWCI330JQcklhGTldyqQHDWA41mT1QMoWfwIDAQABAoIBAF50gryRWykv\\n'\\
    ... 'cuuUfI6ciaGBXCyyPBomuUwicC3v/Au+kk1M9Y7RoFxyKb/88QHZ7kTStDwDITfZmMmM5QN8oF80\\n'\\
    ... 'pyXkM9bBE6MLi0zFfQCXQGN9NR4L4VGqGVfjmqUVQat8Omnv0fOpeVFpXZqij3Mw4ZDmaa7+iA+H\\n'\\
    ... '72J56ru9i9wcBNqt//Kh5BXARekp7tHzklYrlqJd03ftDRp9GTBIFAsaPClTBpnPVhwD/rAoJEhb\\n'\\
    ... 'KM9g/EMjQ28cUMQSHSwOyi9Rg/LtwFnER4u7pnBz2tbJFvLlXE96IQbksQL6/PTJ9H6Zpp+1fDcI\\n'\\
    ... 'k/MKSQZtQOgfV8V1wlvHX+Q0bxECgYEA4LHj6o4usINnSy4cf6BRLrCA9//ePa8UjEK2YDC5rQRV\\n'\\
    ... 'huFWqWJJSjWI9Ofjh8mZj8NvTJa9RW4d4Rn6F7upOuAer9obwfrmi4BEQSbvUwxQIuHOZ6itH/0L\\n'\\
    ... 'klqQBuhJeyr3W+2IhudJUQz9MEoddOfYIybXqkF7XzDl2x6FcjcCgYEAnunySmjt+983gUKK9DgK\\n'\\
    ... '/k1ki41jCAcFlGd8MbLEWkJpwt3FJFiyq6vVptoVH8MBnVAOjDneP6YyNBv5+zm3vyMuVJtKNcAP\\n'\\
    ... 'MAxrl5/gyIBHRxD+avoqpQX/17EmrFsbMaG8IM0ZWB2lSDt45sDvpmSlcTjzrHIEGoBbOzkOefkC\\n'\\
    ... 'gYEAgmS5bxSz45teBjLsNuRCOGYVcdX6krFXq03LqGaeWdl6CJwcPo/bGEWZBQbM86/6fYNcw4V2\\n'\\
    ... 'sSQGEuuQRtWQj6ogJMzd7uQ7hhkZgvWlTPyIRLXloiIw1a9zV6tWiaujeOamRaLC6AawdWikRbG9\\n'\\
    ... 'BmrE8yFHZnY5sjQeL9q2dmECgYEAgp5w1NCirGCxUsHLTSmzf4tFlZ9FQxficjUNVBxIYJguLkny\\n'\\
    ... '/Qka8xhuqJKgwlabQR7IlmIKV+7XXRWRx/mNGsJkFo791GhlE21iEmMLdEJcVAGX3X57BuGDhVrL\\n'\\
    ... 'GuhX1dfGtn9e0ZqsfE7F9YWodfBMPGA/igK9dLsEQg2H5KECgYEAvlv0cPHP8wcOL3g9eWIVCXtg\\n'\\
    ... 'aQ+KiDfk7pihLnHTJVZqXuy0lFD+O/TqxGOOQS/G4vBerrjzjCXXXxi2FN0kDJhiWlRHIQALl6rl\\n'\\
    ... 'i2LdKfL1sk1IA5PYrj+LmBuOLpsMHnkoH+XRJWUJkLvowaJ0aSengQ2AD+icrc/EIrpcdjU=\\n'+\\
    ... '-----END RSA PRIVATE KEY-----\\n'
    >>> ec2_keypair_fingerprint(ssh_private_key)
    'ac:23:ae:c3:9a:a3:78:b1:0f:8a:31:dd:13:cc:b1:8e:fb:51:42:f8'
    """
    rsa_key = RSA.importKey( ssh_key )
    is_private_key = rsa_key.has_private( )
    if is_private_key and reject_private_keys:
        raise ValueError( 'Private keys are disallowed' )
    der_rsa_key = rsa_key.exportKey( format='DER', pkcs=(8 if is_private_key else 1) )
    key_hash = (hashlib.sha1 if is_private_key else hashlib.md5)( der_rsa_key )
    return ':'.join( partition_seq( key_hash.hexdigest( ), 2 ) )


def private_to_public_key( private_ssh_key ):
    """
    Returns the public key in OpenSSH format (as used in the authorized_keys file) for a given
    private RSA key in PEM format.
    >>> ssh_private_key = \\
    ... '-----BEGIN RSA PRIVATE KEY-----\\n'+\\
    ... 'MIIEpQIBAAKCAQEAi3shPK00+/6dwW8u+iDkUYiwIKl/lv0Ay5IstLszwb3CA4mVRlyq769HzE8f\\n'+\\
    ... 'cnzQUX/NI8y9MTO0UNt2JDMJWW5L49jmvxV0TjxQjKg8KcNzYuHsEny3k8LxezWMsmwlrrC89O6e\\n'+\\
    ... 'oo6boc8ForSdjVdIlJbvWu/82dThyFgTjWd5B+1O93xw8/ejqY9PfZExBeqpKjm58OUByTpVhvWe\\n'+\\
    ... 'jmbZ9BL60XJhwz9bDTrlKpjcGsMZ74G6XfQAhyyqXYeD/XOercCSJgQ/QjYKcPE9yMRyucHyuYZ8\\n'+\\
    ... 'HKzmG+u4p5ffnFb43tKzWCI330JQcklhGTldyqQHDWA41mT1QMoWfwIDAQABAoIBAF50gryRWykv\\n'+\\
    ... 'cuuUfI6ciaGBXCyyPBomuUwicC3v/Au+kk1M9Y7RoFxyKb/88QHZ7kTStDwDITfZmMmM5QN8oF80\\n'+\\
    ... 'pyXkM9bBE6MLi0zFfQCXQGN9NR4L4VGqGVfjmqUVQat8Omnv0fOpeVFpXZqij3Mw4ZDmaa7+iA+H\\n'+\\
    ... '72J56ru9i9wcBNqt//Kh5BXARekp7tHzklYrlqJd03ftDRp9GTBIFAsaPClTBpnPVhwD/rAoJEhb\\n'+\\
    ... 'KM9g/EMjQ28cUMQSHSwOyi9Rg/LtwFnER4u7pnBz2tbJFvLlXE96IQbksQL6/PTJ9H6Zpp+1fDcI\\n'+\\
    ... 'k/MKSQZtQOgfV8V1wlvHX+Q0bxECgYEA4LHj6o4usINnSy4cf6BRLrCA9//ePa8UjEK2YDC5rQRV\\n'+\\
    ... 'huFWqWJJSjWI9Ofjh8mZj8NvTJa9RW4d4Rn6F7upOuAer9obwfrmi4BEQSbvUwxQIuHOZ6itH/0L\\n'+\\
    ... 'klqQBuhJeyr3W+2IhudJUQz9MEoddOfYIybXqkF7XzDl2x6FcjcCgYEAnunySmjt+983gUKK9DgK\\n'+\\
    ... '/k1ki41jCAcFlGd8MbLEWkJpwt3FJFiyq6vVptoVH8MBnVAOjDneP6YyNBv5+zm3vyMuVJtKNcAP\\n'+\\
    ... 'MAxrl5/gyIBHRxD+avoqpQX/17EmrFsbMaG8IM0ZWB2lSDt45sDvpmSlcTjzrHIEGoBbOzkOefkC\\n'+\\
    ... 'gYEAgmS5bxSz45teBjLsNuRCOGYVcdX6krFXq03LqGaeWdl6CJwcPo/bGEWZBQbM86/6fYNcw4V2\\n'+\\
    ... 'sSQGEuuQRtWQj6ogJMzd7uQ7hhkZgvWlTPyIRLXloiIw1a9zV6tWiaujeOamRaLC6AawdWikRbG9\\n'+\\
    ... 'BmrE8yFHZnY5sjQeL9q2dmECgYEAgp5w1NCirGCxUsHLTSmzf4tFlZ9FQxficjUNVBxIYJguLkny\\n'+\\
    ... '/Qka8xhuqJKgwlabQR7IlmIKV+7XXRWRx/mNGsJkFo791GhlE21iEmMLdEJcVAGX3X57BuGDhVrL\\n'+\\
    ... 'GuhX1dfGtn9e0ZqsfE7F9YWodfBMPGA/igK9dLsEQg2H5KECgYEAvlv0cPHP8wcOL3g9eWIVCXtg\\n'+\\
    ... 'aQ+KiDfk7pihLnHTJVZqXuy0lFD+O/TqxGOOQS/G4vBerrjzjCXXXxi2FN0kDJhiWlRHIQALl6rl\\n'+\\
    ... 'i2LdKfL1sk1IA5PYrj+LmBuOLpsMHnkoH+XRJWUJkLvowaJ0aSengQ2AD+icrc/EIrpcdjU=\\n'+\\
    ... '-----END RSA PRIVATE KEY-----\\n'
    >>> ssh_pubkey = 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCLeyE8rTT7/p3Bby76IORRiLA'\\
    ... 'gqX+W/QDLkiy0uzPBvcIDiZVGXKrvr0fMTx9yfNBRf80jzL0xM7RQ23YkMwlZbkvj2Oa/FXROPFC'\\
    ... 'MqDwpw3Ni4ewSfLeTwvF7NYyybCWusLz07p6ijpuhzwWitJ2NV0iUlu9a7/zZ1OHIWBONZ3kH7U7'\\
    ... '3fHDz96Opj099kTEF6qkqObnw5QHJOlWG9Z6OZtn0EvrRcmHDP1sNOuUqmNwawxnvgbpd9ACHLKp'\\
    ... 'dh4P9c56twJImBD9CNgpw8T3IxHK5wfK5hnwcrOYb67inl9+cVvje0rNYIjffQlBySWEZOV3KpAc'\\
    ... 'NYDjWZPVAyhZ/'
    >>> private_to_public_key(ssh_private_key) == ssh_pubkey
    True
    """
    rsa_key = RSA.importKey( private_ssh_key )
    if rsa_key.has_private( ):
        return rsa_key.publickey( ).exportKey( format='OpenSSH' )
    else:
        raise ValueError( 'Expected private key' )


def volume_label_hash( s ):
    """
    Linux volume labels are typically limited to 12 or 16 characters while the strings we want to
    use for them are longer, usually a namespaced role name with additional data at the end. This
    hash function returns a 12-character string that is reasonably representative of the input
    string.

    >>> volume_label_hash( 'hannes_spark-master__0' )
    'i0u77fnocoo'
    >>> volume_label_hash( '' )
    'PZ2FQWP48Ho'
    >>> volume_label_hash( ' ' )
    'oIf03JUELnY'
    >>> volume_label_hash( '1' )
    'yQYSos_Mpxk'
    """
    h = hashlib.md5( s )
    h = h.digest( )
    assert len( h ) == 16
    hi, lo = struct.unpack( '!QQ', h )
    h = hi ^ lo
    h = struct.pack( '!Q', h )
    assert len( h ) == 8
    h = base64.urlsafe_b64encode( h )
    assert h[ -1 ] == '='
    return h[ :-1 ]


def prefix_lines( text, prefix ):
    """
    Prefix each non-empty line in the given text with the given prefix.

    >>> prefix_lines('',' ')
    ''
    >>> prefix_lines(' ',' ')
    '  '
    >>> prefix_lines('\\n',' ')
    '\\n'
    >>> prefix_lines('x',' ')
    ' x'
    >>> prefix_lines('x\\n',' ')
    ' x\\n'
    >>> prefix_lines('x\\ny\\n', ' ' )
    ' x\\n y\\n'
    >>> prefix_lines('x\\ny', ' ' )
    ' x\\n y'
    """
    return '\n'.join( prefix + l if l else l for l in text.split( '\n' ) )


def heredoc( s, indent=None ):
    """
    Here-documents [1] for Python. Unindents the given string and interpolates format()-like
    placeholders with local variables from the calling method's stack frame. The interpolation
    part is a bit like black magic but it is tremendously useful.

    [1]: https://en.wikipedia.org/wiki/Here_document

    >>> x, y = 42, 7
    >>> heredoc( '''
    ...     x is {x}
    ...     y is {y}
    ... ''' )
    'x is 42\\ny is 7\\n'
    """
    if s[ 0 ] == '\n': s = s[ 1: ]
    if s[ -1 ] != '\n': s += '\n'
    s = dedent( s )
    if indent is not None:
        s = prefix_lines( s, indent )
    return interpolate( s, skip_frames=1 )


try:
    # noinspection PyUnresolvedReferences
    from concurrent.futures import ThreadPoolExecutor
except ImportError:
    # Fall back to the old implementation that uses the undocument thread pool in
    # multiprocessing. It does not allow interruption via Ctrl-C.
    from contextlib import contextmanager


    @contextmanager
    def thread_pool( size ):
        """
        A context manager that yields a thread pool of the given size. On normal closing,
        this context manager closes the pool and joins all threads in it. On exceptions, the pool
        will be terminated but threads won't be joined.
        """
        pool = multiprocessing.pool.ThreadPool( processes=size )
        try:
            yield pool
        except:
            pool.terminate( )
            raise
        else:
            pool.close( )
            pool.join( )
else:
    # If the futures backport is installed, use that as it is documented and handles Ctrl-C more
    # gracefully.
    # noinspection PyPep8Naming
    class thread_pool( object ):
        """
        A context manager that yields a thread pool of the given size. On normal closing,
        this context manager closes the pool and joins all threads in it. On exceptions, the pool
        will be terminated but threads won't be joined.
        """

        def __init__( self, size ):
            self.executor = ThreadPoolExecutor( size )

        def __enter__( self ):
            return self

        # noinspection PyUnusedLocal
        def __exit__( self, exc_type, exc_val, exc_tb ):
            self.executor.shutdown( wait=exc_type is None )

        def apply_async( self, fn, args, callback=None ):
            future = self.executor.submit( fn, *args )
            if callback is not None:
                future.add_done_callback( lambda f: callback( f.result( ) ) )

        def map( self, fn, iterable ):
            return list( self.executor.map( fn, iterable ) )


def pmap( f, seq, pool_size=cores ):
    """
    Apply the given function to each element of the given sequence and return a sequence of the
    result of each function application. Do so in parallel, using a thread pool no larger than
    the given size.

    :param callable f: the function to be applied

    :param Sequence seq: the input sequence

    :param int pool_size: the desired pool size, if absent the number of CPU cores will be used.
    The actual pool size may be smaller if the input sequence is small. A pool size of 0 will
    make this function behave exactly like the map() builtin, i.e. the function will be applied
    serially in the current thread.

    >>> pmap( lambda (a, b): a + b, [], pool_size=0 )
    []
    >>> pmap( lambda (a, b): a + b, [ (1, 2) ], pool_size=0 )
    [3]
    >>> pmap( lambda (a, b): a + b, [ (1, 2), (3, 4) ], pool_size=0 )
    [3, 7]
    >>> pmap( lambda a, b: a + b, [ (1, 2), (3, 4) ], pool_size=0 )
    Traceback (most recent call last):
    ...
    TypeError: <lambda>() takes exactly 2 arguments (1 given)
    >>> pmap( lambda (a, b): a + b, [], pool_size=1 )
    []
    >>> pmap( lambda (a, b): a + b, [ (1, 2) ], pool_size=1 )
    [3]
    >>> pmap( lambda (a, b): a + b, [ (1, 2), (3, 4) ], pool_size=1 )
    [3, 7]
    >>> pmap( lambda a, b: a + b, [ (1, 2), (3, 4) ], pool_size=1 )
    Traceback (most recent call last):
    ...
    TypeError: <lambda>() takes exactly 2 arguments (1 given)
    >>> pmap( lambda (a, b): a + b, [], pool_size=2 )
    []
    >>> pmap( lambda (a, b): a + b, [ (1, 2) ], pool_size=2 )
    [3]
    >>> pmap( lambda (a, b): a + b, [ (1, 2), (3, 4) ], pool_size=2 )
    [3, 7]
    >>> pmap( lambda a, b: a + b, [ (1, 2), (3, 4) ], pool_size=2 )
    Traceback (most recent call last):
    ...
    TypeError: <lambda>() takes exactly 2 arguments (1 given)
    """
    __check_pool_size( pool_size )
    n = len( seq )
    if n:
        if pool_size == 0:
            return map( f, seq )
        else:
            with thread_pool( min( pool_size, n ) ) as pool:
                return pool.map( f, seq )
    else:
        return [ ]


def papply( f, seq, pool_size=cores, callback=None ):
    """
    Apply the given function to each element of the given sequence, optionally invoking the given
    callback with the result of each application. Do so in parallel, using a thread pool no
    larger than the given size.

    :param callable f: the function to be applied

    :param Sequence seq: the input sequence

    :param int pool_size: the desired pool size, if absent the number of CPU cores will be used.
    The actual pool size may be smaller if the input sequence is small.A pool size of 0 will make
    this function emulate the apply() builtin, i.e. f (and the callback, if provided) will be
    invoked serially in the current thread.

    :param callable callback: an optional function to be invoked with the return value of f

    >>> l=[]; papply( lambda a, b: a + b, [], pool_size=0, callback=l.append ); l
    []
    >>> l=[]; papply( lambda a, b: a + b, [ (1, 2) ], pool_size=0, callback=l.append); l
    [3]
    >>> l=[]; papply( lambda a, b: a + b, [ (1, 2), (3, 4) ], pool_size=0, callback=l.append ); l
    [3, 7]
    >>> l=[]; papply( lambda a, b: a + b, [], pool_size=1, callback=l.append ); l
    []
    >>> l=[]; papply( lambda a, b: a + b, [ (1, 2) ], pool_size=1, callback=l.append); l
    [3]
    >>> l=[]; papply( lambda a, b: a + b, [ (1, 2), (3, 4) ], pool_size=1, callback=l.append ); l
    [3, 7]
    >>> l=[]; papply( lambda a, b: a + b, [], pool_size=2, callback=l.append ); l
    []
    >>> l=[]; papply( lambda a, b: a + b, [ (1, 2) ], pool_size=2, callback=l.append); l
    [3]
    >>> l=[]; papply( lambda a, b: a + b, [ (1, 2), (3, 4) ], pool_size=2, callback=l.append ); l
    [3, 7]
    """
    __check_pool_size( pool_size )
    n = len( seq )
    if n:
        if pool_size == 0:
            for args in seq:
                result = apply( f, args )
                if callback is not None:
                    callback( result )
        else:
            with thread_pool( min( pool_size, n ) ) as pool:
                for args in seq:
                    pool.apply_async( f, args, callback=callback )


def __check_pool_size( pool_size ):
    if pool_size < 0:
        raise ValueError( 'Pool size must be >= 0' )


def allocate_cluster_ordinals( num, used ):
    """
    Return an iterator containing a given number of unused cluster ordinals. The result is
    guaranteed to yield each ordinal exactly once, i.e. the result is set-like. The argument
    set and the result iterator will be disjoint. The sum of all ordinals in the argument and
    the result is guaranteed to be minimal, i.e. the function will first fill the gaps in the
    argument before allocating higher values. The result will yield ordinal in ascending order.

    :param int num: the number of ordinal to allocate
    :param set[int] used: a set of currently used ordinal
    :rtype: iterator

    >>> f = allocate_cluster_ordinals

    >>> list(f(0,set()))
    []
    >>> list(f(1,set()))
    [0]
    >>> list(f(0,{0}))
    []
    >>> list(f(1,{0}))
    [1]
    >>> list(f(0,{0,1}))
    []
    >>> list(f(1,{0,1}))
    [2]
    >>> list(f(0,{0,2}))
    []
    >>> list(f(1,{0,2}))
    [1]
    >>> list(f(2,{0,2}))
    [1, 3]
    >>> list(f(3,{0,2}))
    [1, 3, 4]
    """
    assert isinstance( used, set )
    first_free = max( used ) + 1 if used else 0
    complete = set( range( 0, len( used ) ) )
    gaps = sorted( complete - used )
    return islice( concat( gaps, count( first_free ) ), num )
