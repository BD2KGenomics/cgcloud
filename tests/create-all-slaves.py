from Queue import Queue
from functools import partial
from threading import Thread
import unittest
import os
import uuid
import sys

from subprocess32 import check_call, check_output


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
cgcloud = os.path.join( project_root, 'cgcloud' )
production = True
if production:
    namespace = '/'
    include_master = False
else:
    namespace = '/hannes/'
    include_master = True

# slave_suffix = '-genetorrent-jenkins-slave'
# slave_suffix = '-generic-jenkins-slave'
slave_suffix = '-rpmbuild-jenkins-slave'



class Pane( object ):
    """
    An abstraction of a tmux pane. A pane represents a terminal that you can run commands in.
    Commands run asynchronously but you can synchronized on them using the join() method. You
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
            cmd = '( %s ) ; tmux wait -S %s' % ( cmd, success_ch )
        else:
            cmd = '( %s ) && tmux wait -S %s || tmux wait -S %s' % ( cmd, success_ch, fail_ch )
        check_call( [ 'tmux', 'send-keys', '-t', self.tmux_id, cmd, 'C-m' ] )

    def result( self ):
        return (False, True)[ self.queue.get( ) ]


class DevEnvTest( unittest.TestCase ):
    """

    """

    def setUp( self ):
        super( DevEnvTest, self ).setUp( )
        slaves = [ slave
            for slave in check_output( [ cgcloud, 'list-roles' ] ).split( '\n' )
            if slave.endswith( slave_suffix ) ]
        self.master_pane = Pane( ) if include_master else None
        self.slave_panes = dict( (slave, Pane( ) ) for slave in slaves )

    def test_everything( self ):
        self._create( )
        self._stop( )
        self._image( )
        # self._start( )
        self._terminate( )
        # self._recreate( )

    def _create( self ):
        self._test( partial( self._cgcloud, 'create', options="--never-terminate" ) )

    def _start( self ):
        self._test( partial( self._cgcloud, 'start' ) )

    def _stop( self ):
        self._test( partial( self._cgcloud, 'stop' ), reverse=True )

    def _image( self ):
        self._test( partial( self._cgcloud, 'image' ) )

    def _terminate( self ):
        self._test( partial( self._cgcloud, 'terminate', ignore_failure=True ), reverse=True )

    def _recreate( self ):
        self._test( partial( self._cgcloud, 'recreate', options="--never-terminate" ) )

    def _cgcloud( self, command, pane, role, options='', **run_args ):
        cmd = ' '.join( [ cgcloud, command, '-n', namespace, role, options ] )
        return pane.run( cmd, **run_args )

    def _test( self, command, reverse=False ):
        def test_master( ):
            if self.master_pane is not None:
                command( self.master_pane, 'jenkins-master' )
                self.assertTrue( self.master_pane.result( ) )

        def test_slaves( ):
            for slave, pane in self.slave_panes.iteritems( ): command( pane, slave )
            for pane in self.slave_panes.itervalues( ): self.assertTrue( pane.result( ) )

        tests = [ test_master, test_slaves ]
        if reverse: tests.reverse( )
        for test in tests: test( )


if __name__ == '__main__':
    unittest.main( )

