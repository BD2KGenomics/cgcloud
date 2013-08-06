import argparse
import os
import re
import errno


def unpack_singleton(singleton):
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


def camel_to_snake(s, separator='_'):
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
    """
    return re.sub( '([a-z0-9])([A-Z])', r'\1%s\2' % separator, s ).lower( )


def mkdir_p(path):
    """
    The equivalent of mkdir -p
    """
    try:
        os.makedirs( path )
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir( path ):
            pass
        else:
            raise


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

    def __init__(self):
        """
        Initializes the argument parser
        """
        super( Application, self ).__init__( )
        self.parser = argparse.ArgumentParser(
            formatter_class=argparse.ArgumentDefaultsHelpFormatter
        )
        self.subparsers = self.parser.add_subparsers( help='Application commands',
                                                      dest='command_name' )
        self.commands = { }

    def option(self, *args, **kwargs):
        self.parser.add_argument( *args, **kwargs )

    def add(self, command_cls):
        """
        Instantiates a command of the specified class and adds it to this application.
        """
        command = command_cls( self )
        self.commands[ command.name( ) ] = command

    def run(self, args=None):
        """
        Parses the command line into an options object using arparse and invokes the requested
        command's run() method with that options object.
        """
        options = self.parser.parse_args( args )
        self.prepare( options )
        command = self.commands[ options.command_name ]
        command.run( options )

    def prepare(self, options):
        pass


class Command( object ):
    """
    An abstract base class for an applications commands.
    """

    def run(self, options):
        """
        Execute this command.

        :param options: the parsed command line arguments
        """
        raise NotImplementedError( )

    def __init__(self, application, **kwargs):
        """
        Initializes this command.
        :param application: The application this command belongs to.
        :type application: Application
        :param kwargs: optional arguments to the argparse's add_parser() method

        >>> cmd = Command(Application(),help='A command that does something')
        >>> cmd.
        """
        super( Command, self ).__init__( )
        self.parser = application.subparsers.add_parser(
            self.name( ),
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            **kwargs )
        self.group = None

    def option(self, *args, **kwargs):
        target = self.parser if self.group is None else self.group
        target.add_argument( *args, **kwargs )

    def name(self):
        """
        Returns the name of this command as referred to by the user when invoking it via the
        command line. The command name is the snake-case version (with dashes instead of
        underscores) of this command's class name, minus its 'Command' suffix.

        >>> class FooBarCommand(Command): pass
        >>> app=Application()
        >>> FooBarCommand(app).name()
        'foo-bar'
        """
        name = self.__class__.__name__
        suffix = Command.__name__
        if name.endswith( suffix ): name = name[ :-len( suffix ) ]
        return camel_to_snake( name, separator='-' )

    def begin_mutex(self, **kwargs):
        self.group = self.parser.add_mutually_exclusive_group( **kwargs )

    def end_mutex(self):
        self.group = None



