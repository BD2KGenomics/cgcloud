from functools import partial
from threading import Thread
import unittest
import subprocess32 as subprocess
import os
import uuid

# Must have tmux, a fork of GNU Screen, installed for this
import sys
import signal

project_root = os.path.dirname( os.path.dirname( __file__ ) )
cgcloud = os.path.join( project_root, 'cgcloud' )
production = False
if production:
    namespace = '/'
    include_master=False
else:
    namespace = '/hannes/'
    include_master=True

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

    # TODO: allow for multiple run()/join() cycles

    session = 'cgcloud-%s' % uuid.uuid4( )
    panes = [ ]

    def log( self, s ):
        sys.stderr.write( s + '\n' )
        sys.stderr.flush( )

    def __init__( self ):
        super( Pane, self ).__init__( )
        self.channel_id = uuid.uuid4( )
        self.index = len( self.panes )
        window = '%s:0' % self.session
        if self.index == 0:
            self.log( "Run 'tmux attach -t %s' to monitor output" % self.session )
            subprocess.check_call(
                [ 'tmux', 'new-session', '-d', '-s', self.session, '-x', '100', '-y', '80' ] )
            self.tmux_id = subprocess.check_output(
                [ 'tmux', 'list-panes', '-t', window, '-F', '#{pane_id}' ] ).strip( )
        else:
            self.tmux_id = subprocess.check_output(
                [ 'tmux', 'split-window', '-v', '-t', window, '-PF', '#{pane_id}' ] ).strip( )
            subprocess.check_call( [ 'tmux',
                'select-layout', '-t', window, 'even-vertical' ] )
        self.panes.append( self )
        self.thread = Thread( target=self._wait )
        self.thread.start( )

    def _wait( self ):
        subprocess.check_call( [ 'tmux', 'wait', str( self.channel_id ) ] )

    def run( self, cmd, ignore_failure=False ):
        operator = ';' if ignore_failure else '&&'
        cmd = '( %s ) %s tmux wait -S %s' % ( cmd, operator, self.channel_id )
        subprocess.check_call( [
            'tmux', 'send-keys', '-t', self.tmux_id, cmd, 'C-m' ] )

    def join( self ):
        self.thread.join( )


class DevEnvTest( unittest.TestCase ):
    """

    """

    def cgcloud( self, op, pane, role, options='', **run_args ):
        cmd = 'export CGCLOUD_NAMESPACE="%s" && %s %s %s %s' % ( namespace, cgcloud, op, role, options )
        return pane.run( cmd, **run_args )

    def test_slave_creation( self ):
        self._test( partial( self.cgcloud, 'create', options='--no-agent' ) )

    def test_slave_stop( self ):
        self._test( partial( self.cgcloud, 'stop' ), reverse=True )

    def test_slave_imaging( self ):
        self._test( partial( self.cgcloud, 'image' ) )

    def test_slave_termination( self ):
        self._test( partial( self.cgcloud, 'terminate', ignore_failure=True ), reverse=True )

    def _test( self, fn, reverse=False ):
        slaves = [ slave
            for slave in subprocess.check_output( [ cgcloud, 'list-roles' ] ).split( '\n' )
            if slave.endswith( '-jenkins-slave' ) ]
        master_pane = Pane( ) if include_master else None
        slave_panes = dict( (slave, Pane( ) ) for slave in slaves )

        def test_master( ):
            if master_pane is not None:
                fn( master_pane, 'jenkins-master' )
                master_pane.join( )

        def test_slaves( ):
            for slave, pane in slave_panes.iteritems( ): fn( pane, slave )
            for pane in slave_panes.itervalues( ): pane.join( )

        tests = [ test_master, test_slaves ]
        if reverse: tests.reverse( )
        for test in tests: test( )


if __name__ == '__main__':
    unittest.main( )

