import os
import sys
import argparse
import platform
import itertools
import logging
from logging.handlers import SysLogHandler, SYSLOG_UDP_PORT

import daemon
from bd2k.util.logging import Utf8SyslogFormatter
from bd2k.util import uid_to_name, gid_to_name, name_to_uid, name_to_gid, shell
from bd2k.util.lockfile import SmartPIDLockFile
from bd2k.util.throttle import LocalThrottle

from cgcloud.lib.context import Context
from cgcloud.agent import Agent

log = logging.getLogger( )

description = "The CGHub Cloud Agent daemon"

exec_path = os.path.abspath( sys.argv[ 0 ] )
exec_name = os.path.basename( exec_path )


def main( ):
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description=description )
    group = parser.add_argument_group( title='functional options' )
    group.add_argument( '--namespace', '-n', metavar='PREFIX',
                        required=True,
                        help='Optional prefix for naming EC2 resource like instances, images, '
                             'volumes, etc. Use this option to create a separate namespace in '
                             'order to avoid collisions, e.g. when running tests. The default '
                             'represents the root namespace. The value of the environment '
                             'variable CGCLOUD_NAMESPACE, if that variable is present, overrides '
                             'the default. The string __me__ anywhere in the namespace will be '
                             'replaced by the name of the IAM user whose credentials are used to '
                             'issue requests to AWS.' )
    default_zone = os.environ.get( 'CGCLOUD_ZONE', None )
    group.add_argument( '--zone', '-z', metavar='AVAILABILITY_ZONE',
                        default=default_zone,
                        required=not default_zone,
                        dest='availability_zone',
                        help='The name of the EC2 availability zone to operate in, '
                             'e.g. us-east-1a, us-west-1b or us-west-2c etc. This argument '
                             'implies the AWS region to run in. The value of the environment '
                             'variable CGCLOUD_ZONE, if that variable is present, overrides the '
                             'default.' )
    group.add_argument( '--interval', '-i', metavar='SECONDS',
                        default=300, type=int,
                        help='' )
    group.add_argument( '--accounts', metavar='PATH', nargs='+',
                        default=[ uid_to_name( os.getuid( ) ) ],
                        help="The names of user accounts whose .ssh/authorized_keys file should "
                             "be managed by this agent. Note that managing another user's "
                             ".ssh/authorized_keys typically requires running the agent as root." )
    default_ec2_keypair_names = os.environ.get( 'CGCLOUD_KEYPAIRS', '' ).split( )
    group.add_argument( '--keypairs', '-k', metavar='EC2_KEYPAIR_NAME',
                        dest='ec2_keypair_names', nargs='+',
                        required=not default_ec2_keypair_names,
                        default=default_ec2_keypair_names,
                        help='The names or name patterns of EC2 key pairs whose public key is to '
                             'be to maintained in the ~/.ssh/authorized_keys files of each '
                             'account listed in the --accounts option. Each argument may be a '
                             'literal name of a keypairs or a shell-style glob in which case '
                             'every key pair whose name matches that glob will be deployed '
                             'to the box. The value of the environment variable CGCLOUD_KEYPAIRS, '
                             'if that variable is present, overrides the default.' )

    group = parser.add_argument_group( title='process options' )
    group.add_argument( '--debug', '-X', default=False, action='store_true',
                        help="Run in debug mode without daemonizing. All other process options "
                             "will be ignored." )
    group.add_argument( '--user', '-u', metavar='UID',
                        default=uid_to_name( os.getuid( ) ),
                        help='The name of the user to run the daemon as.' )
    group.add_argument( '--group', '-g', metavar='GID',
                        default=gid_to_name( os.getgid( ) ),
                        help='The name of the group to run the daemon as.' )
    group.add_argument( '--pid-file', '-p', metavar='PATH',
                        default='./%s.pid' % exec_name,
                        help="The path of the file to which the daemon's process ID will be "
                             "written." )
    log_levels = [ logging.getLevelName( level ) for level in
        ( logging.CRITICAL, logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG ) ]
    group.add_argument( '--log-level', default=logging.getLevelName( logging.INFO ),
                        choices=log_levels, help="The default log level." )
    group.add_argument( '--log-spill', metavar='PATH',
                        default='./%s.log' % exec_name,
                        help="The path of the file to which the daemon's stderr and stdout will "
                             "be redirected. Most of the diagnostic output will go to syslog but "
                             "some might spill over to stderr or stdout, especially on errors "
                             "during daemonization." )

    group = parser.add_argument_group( title='miscellaeneous options' )
    group.add_argument( '--init-script', default=False, action='store_true',
                        help='Instead of starting the daemon, generate an /etc/init.d script for '
                             '%s using the specified options and exit. One would typically '
                             'redirect the output to a file, move that file into place, '
                             'make it executable and run chkconfig to '
                             'update the run levels.' % exec_name )

    group.add_argument( '--init', metavar='NAME', default=None, required=False,
                        choices=[ 'sysv', 'upstart', 'systemd' ],
                        help="The init system invoking this program. This parameter is only "
                             "needed when this program is run as a service under the auspices of "
                             "a init daemon." )

    options = parser.parse_args( )

    # The lock file path will be evaluated by DaemonContext after the chdir to /,
    # so we need to convert a relative path to an absolute one. Also, the init script generation
    # should not use relative paths.
    options.pid_file = os.path.abspath( options.pid_file )
    options.log_spill = os.path.abspath( options.log_spill )

    if options.init_script:
        generate_init_script( options )
        sys.exit( 0 )

    def run( ):
        log.info( "Entering main loop." )
        ctx = Context( availability_zone=options.availability_zone, namespace=options.namespace )
        throttle = LocalThrottle( min_interval=options.interval )
        for i in itertools.count( ):
            throttle.throttle( )
            try:
                log.info( "Starting run %i.", i )
                Agent( ctx, options ).run( )
                log.info( "Completed run %i.", i )
            except (SystemExit, KeyboardInterrupt):
                log.info( 'Terminating.' )
                break
            except:
                log.exception( 'Abandoning run due to exception' )

    formatter = Utf8SyslogFormatter(
        '%s[%%(process)d]: [%%(levelname)s] %%(threadName)s %%(name)s: %%(message)s' % exec_name )
    if options.debug:
        handler = logging.StreamHandler( sys.stderr )
        handler.setFormatter( formatter )
        log.addHandler( handler )
        log.setLevel( logging.DEBUG )
        run( )
    else:
        system = platform.system( )
        if system in ( 'Darwin', 'FreeBSD' ):
            address = '/var/run/syslog'
        elif system == 'Linux':
            address = '/dev/log'
        else:
            address = ( 'localhost', SYSLOG_UDP_PORT )
        handler = SysLogHandler( address=address )
        handler.setFormatter( formatter )
        log.addHandler( handler )
        # getLevelName works in the reverse, too:
        log.setLevel( logging.getLevelName( options.log_level ) )
        log_spill = open( options.log_spill, 'w' ) if options.log_spill else None
        try:
            pid_lock_file = SmartPIDLockFile( options.pid_file )
            with daemon.DaemonContext( uid=name_to_uid( options.user ),
                                       gid=name_to_gid( options.group ),
                                       stderr=log_spill, stdout=log_spill,
                                       files_preserve=[ handler.socket ],
                                       # True needed for systemd (see [1])
                                       detach_process=True if options.init == 'systemd' else None,
                                       pidfile=pid_lock_file ):
                run( )
        finally:
            if log_spill:
                log_spill.close( )


# [1]: http://echorand.me/2013/08/02/notes-on-writing-systemd-unit-files-for-beakers-daemon-processes/


def generate_init_script( options ):
    from pkg_resources import resource_string
    import cgcloud.agent
    import platform

    distro, version, codename = map( str.lower, platform.linux_distribution( ) )

    console = None
    if distro == 'ubuntu':
        quote_level = 1
        if codename < 'vivid':
            script = 'init-script.upstart'
            # Lucid's version of upstart doesn't support "console log", Precise's does, don't know
            # about the versions in between
            console = 'output' if codename < 'precise' else 'log'
        else:
            script = 'init-script.systemd'
    else:
        script = 'init-script.lsb'
        quote_level = 2

    init_script = resource_string( cgcloud.agent.__name__, script )

    args = [ '--namespace', options.namespace,
               '--zone', options.availability_zone,
               '--interval', str( options.interval ),
               '--accounts' ] + options.accounts + [
               '--keypairs' ] + options.ec2_keypair_names + [
               '--user', options.user,
               '--group', options.group,
               '--pid-file', options.pid_file,
               '--log-level', options.log_level,
               '--log-spill', options.log_spill ]
    variables = vars( options ).copy( )
    variables.update( dict( args=' '.join( shell.quote( arg, level=quote_level ) for arg in args ),
                            exec_path=exec_path,
                            exec_name=exec_name,
                            console=console,
                            description=description ) )
    print init_script % variables
