from Queue import Queue
from abc import ABCMeta, abstractmethod
from functools import partial
from threading import Thread
import unittest
import os
import uuid
import sys

from bd2k.util.fnmatch import fnmatch

try:
    # Note that subprocess isn't thread-safe so subprocess is actually required. I'm just putting
    # this in a try-except to make the test loader happy.
    from subprocess32 import check_call, check_output
except ImportError:
    from subprocess import check_call, check_output


# This is more of an experiment rather than a full-fledged test. It works on multiple EC2
# instances in parallel, therefore making it well suited for semi-interactive use since you
# don't have to wait as long for errors to show up. It runs all cgcloud invocations in tmux panes
# inside a detached session. The tests print the tmux session ID so you can attach to it while
# the test is running or afterwards for a post-mortem.
#
# Caveats: A successfull test will leave the tmux session running. Each test creates a new
# session so you should clean up once in a while. The easisest way to do so is to run 'tmux
# kill-server'.

# Must have tmux, a fork of GNU Screen, installed for this.

# Subprocess32 a backport of Python 3.2 must also be installed (via pip). 2.7's stock subprocess
# keeps dead-locking on me.

project_root = os.path.dirname( os.path.dirname( __file__ ) )
cgcloud = 'cgcloud'

production = True

if production:
    namespace = '/'
    include_master = False
else:
    namespace = '/hannes/'
    include_master = True


class Pane( object ):
    """
    An abstraction of a tmux pane. A pane represents a terminal that you can run commands in.
    Commands run asynchronously but you can synchronized on them using the result() method. You
    should pre-allocate all panes you need before running commands in any of them. Commands are
    run using the run() method. The join() method blocks until the command finishes. The tmux
    pane remains open after the command finishes so you can do post-portem analysis on it,
    the main reason I wrote this.

    All panes in the interpreter share a single tmux session. The session has only one window but
    panes can be broken out manually after attaching to the session.
    """

    session = 'cgcloud-%s' % uuid.uuid4( )
    panes = [ ]

    def log( self, s ):
        sys.stderr.write( s + '\n' )
        sys.stderr.flush( )

    def __init__( self ):
        super( Pane, self ).__init__( )
        # One tmux channel for success, one for failures. See tmux(1).
        self.channel_ids = tuple( uuid.uuid4( ) for _ in range( 2 ) )
        # A queue between the daemon threads that service the channels and the client code. The
        # queue items are the channel index, 0 for failure, 1 or success.
        self.queue = Queue( maxsize=1 )
        # The pane index.
        self.index = len( self.panes )
        window = '%s:0' % self.session
        if self.index == 0:
            self.log( "Run 'tmux attach -t %s' to monitor output" % self.session )
            check_call(
                [ 'tmux', 'new-session', '-d', '-s', self.session, '-x', '100', '-y', '80' ] )
            self.tmux_id = check_output(
                [ 'tmux', 'list-panes', '-t', window, '-F', '#{pane_id}' ] ).strip( )
        else:
            self.tmux_id = check_output(
                [ 'tmux', 'split-window', '-v', '-t', window, '-PF', '#{pane_id}' ] ).strip( )
            check_call( [ 'tmux', 'select-layout', '-t', window, 'even-vertical' ] )
        self.panes.append( self )
        self.threads = tuple( self._start_thread( i ) for i in range( 2 ) )

    def _start_thread( self, channel_index ):
        thread = Thread( target=partial( self._wait, channel_index ) )
        thread.daemon = True
        thread.start( )
        return thread

    def _wait( self, channel_index ):
        while True:
            check_call( [ 'tmux', 'wait', str( self.channel_ids[ channel_index ] ) ] )
            self.queue.put( channel_index )

    def run( self, cmd, ignore_failure=False ):
        fail_ch, success_ch = self.channel_ids
        if ignore_failure:
            cmd = '( %s ) ; tmux wait -S %s' % (cmd, success_ch)
        else:
            cmd = '( %s ) && tmux wait -S %s || tmux wait -S %s' % (cmd, success_ch, fail_ch)
        check_call( [ 'tmux', 'send-keys', '-t', self.tmux_id, cmd, 'C-m' ] )

    def result( self ):
        return (False, True)[ self.queue.get( ) ]


class Command( object ):
    """
    A glorified string template for cgcloud command lines. The default values for the template
    arguments specified at construction can be overriden when the command is actually run,
    i.e. when the template is instantiated. The value for a template parameter can be either a
    static value or a callable taking two arguments, role and ordinal. The callable will be
    evaluated at instantiation time with the role and ordinal of the concrete box cgcloud should
    be run against. A command can be set to ignore failures, in which case a non-zero exit code
    from cgcloud does not fail the test. A command can be 'reverse' which means that it should be
    run against the list of boxes in the reverse order. How exactly "reverse" is implemented
    depends on the client.
    """

    def __init__( self, command, template, ignore_failure=False, reverse=False, **template_args ):
        super( Command, self ).__init__( )
        self.template = "{cgcloud} {command} -n {namespace} " + template
        self.template_args = template_args.copy( )
        self.template_args.update( cgcloud=cgcloud, command=command, namespace=namespace )
        self.ignore_failure = ignore_failure
        self.reverse = reverse

    def run( self, pane, role, ordinal, **template_args ):
        """
        Instantiate this command line template and run it in the specified pane against the box
        of the specified role and ordinal, substituting additional template parameters with the
        given keyword arguments.
        """
        # start with defaults
        _template_args = self.template_args.copy( )
        # update with overrides
        _template_args.update( template_args )
        # expand callables
        _template_args = dict( (k, v( role, ordinal ) if callable( v ) else v)
                                   for k, v in _template_args.iteritems( ) )
        # set role and ordinal
        _template_args.update( role=role, ordinal=ordinal )
        # finally, run the command in the pane
        pane.run( self.template.format( **_template_args ), ignore_failure=self.ignore_failure )


# Factory methods for cgcloud commands:

def create( options="" ):
    return Command( "create", "--never-terminate {options} {role}", options=options )


def recreate( options="" ):
    return Command( "recreate", "--never-terminate {options} {role}", options=options )


def start( options="" ):
    return Command( "start", "-o {ordinal} {options} {role}", options=options )


def stop( options="" ):
    return Command( "stop", "-o {ordinal} {options} {role}", reverse=True, options=options )


def ssh( ssh_command="", options="" ):
    return Command( "ssh", "-o {ordinal} {options} {role} {ssh_command}",
                    ssh_command=ssh_command,
                    options=options )


def rsync( rsync_args, options="" ):
    return Command( "rsync", "-o {ordinal} {options} {role} {rsync_args}",
                    rsync_args=rsync_args,
                    options=options )


def image( options="" ):
    return Command( "image", "-o {ordinal} {options} {role}", options=options )


def terminate( options="" ):
    return Command( "terminate", "-o {ordinal} {options} {role}",
                    ignore_failure=True,
                    reverse=True,
                    options=options )


class BaseTest( unittest.TestCase ):
    __metaclass__ = ABCMeta

    @abstractmethod
    def _execute_command( self, command ):
        pass

    def _list_roles( self, slave_glob ):
        slaves = [ slave
            for slave in check_output( [ cgcloud, 'list-roles' ] ).split( '\n' )
            if fnmatch( slave, slave_glob ) ]
        return slaves

    def _test( self, *commands ):
        for command in commands:
            self._execute_command( command )

class DevEnvTest( BaseTest ):
    """
    Tests the creation of the Jenkins master and its slaves for continuous integration.
    """
    # slave_glob = '*-genetorrent-jenkins-slave'
    # slave_glob = '*-generic-jenkins-slave'
    # slave_glob = '*-rpmbuild-jenkins-slave'
    slave_glob = 'centos5-*-jenkins-slave'

    def _init_panes( self ):
        slave_roles = self._list_roles( self.slave_glob )
        self.master_pane = Pane( ) if include_master else None
        self.slave_panes = dict( (slave_role, Pane( )) for slave_role in slave_roles )

    def test_everything( self ):
        self._init_panes( )
        self._test(
            create( ),
            stop( ),
            image( ),
            start( ),
            terminate( ),
            recreate( ),
            ssh( ),
            terminate( ) )

    def _execute_command( self, command ):
        def test_master( ):
            if self.master_pane is not None:
                command.run( self.master_pane, 'jenkins-master', ordinal=-1 )
                self.assertTrue( self.master_pane.result( ) )

        def test_slaves( ):
            for slave_role, pane in self.slave_panes.iteritems( ):
                command.run( pane, slave_role, ordinal=-1 )
            for pane in self.slave_panes.itervalues( ):
                self.assertTrue( pane.result( ) )

        tests = [ test_master, test_slaves ]

        for test in reversed( tests ) if command.reverse else tests: test( )

class LoadTest( BaseTest ):
    key_file = '~/MORDOR1.pem'  # local path, this will copied to each box
    role = 'load-test-box'  # name of the cgcloud role
    base_url = 'https://stage.cghub.ucsc.edu/cghub/data/analysis/download/'
    instance_type = "m3.2xlarge"
    if False:
        uuids = [
            "b08210ce-b0c1-4d6a-8762-0f981c27d692",
            "ffb4cff4-06ea-4332-8002-9aff51d5d388",
            "5c07378f-cafe-42db-a66e-d608f2f0e982",
            "7fffef66-627f-43f7-96b3-6672e1cb6b59",
            "7ec3fa29-bbec-4d08-839b-c1cd60909ed0",
            "4714ee84-26cd-48e7-860d-a115af0fca48",
            "9266e7ca-c6f9-4187-ab8b-f11f6c65bc71",
            "9cd637b0-9b68-4fd7-bd9e-fa41e5329242",
            "71ec0937-7812-4b35-87de-77174fdb28bc",
            "d49add54-27d2-4d77-b719-19f4d77c10c3" ]
    else:
        uuids = [
            "7c619bf2-6470-4e01-9391-1c5db775537e",  # 166GBs
            "27a1b0dc-3f1a-4606-9bd7-8b7a0a89e066",  # 166GBs
            "027d9b42-cf22-429a-9741-da6049a5f192",  # 166GBs
            "0600bae1-2d63-41fd-9dee-b5d3cd21b3ee",  # 166GBs
            "c3cf7d48-e0c1-4605-a951-34ad83916361",  # 166GBs
            # "4c87ef17-3d1b-478f-842f-4bb855abdda1", # 166GBs, unauthorized for MORDOR1.pem
            "44806b1a-2d77-4b67-9774-67e8a5555f88",  # 166GBs
            "727e2955-67a3-431c-9c7c-547e6b8b7c95",  # 166GBs
            "99728596-1409-4d5e-b2dc-744b5ba2aeab",  # 166GBs
            # "c727c612-1be1-8c27-e040-ad451e414a7f" # >500GBs, causes 409 during download, maybe fixed now
        ]
    num_instances = len( uuids )
    num_children = 8

    def test_load( self ):
        self._init_panes( )
        self._test(
            # recreate( "-t %s" % self.instance_type ),
            # rsync( '-v %s :' % self.key_file ),
            # ssh( self._gtdownload ),
            terminate( '-q' ),
        )

    def _gtdownload( self, role, ordinal ):
        return "gtdownload -d {base_url}{uuid} -c {key_file} -vv --null-storage --max-children {num_children}".format(
            base_url=self.base_url,
            uuid=self.uuids[ ordinal ],
            key_file=os.path.basename( self.key_file ),
            num_children=self.num_children )

    def _init_panes( self ):
        self.panes = [ Pane( ) for _ in range( 0, self.num_instances ) ]

    def _execute_command( self, command ):
        for i, pane in enumerate( self.panes ):
            command.run( pane, self.role, ordinal=(i - self.num_instances) )
        for pane in self.panes:
            self.assertTrue( pane.result( ) )

class TrackerStressTest( BaseTest ):
    role = 'load-test-box'  # name of the cgcloud role
    stress_tracker_script = '/Users/hannes/workspace/cghub/tests/stress_tracker'
    instance_type = 'm3.2xlarge'
    num_instances = 8

    def test_tracker_stress( self ):
        self._init_panes( )
        self._test(
            # recreate( '-t %s' % self.instance_type ),
            # rsync( '-v %s :' % self.stress_tracker_script ),
            # ssh( 'python %s' % os.path.basename( self.stress_tracker_script ) ),
            terminate( '-q' ),
        )

    def _init_panes( self ):
        self.panes = [ Pane( ) for _ in range( 0, self.num_instances ) ]

    def _execute_command( self, command ):
        for i, pane in enumerate( self.panes ):
            command.run( pane, self.role, ordinal=(i - self.num_instances) )
        for pane in self.panes:
            self.assertTrue( pane.result( ) )


if __name__ == '__main__':
    unittest.main( )
