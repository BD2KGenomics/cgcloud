from StringIO import StringIO
import time

from fabric.operations import run, put

from cgcloud.bd2k.ci import UbuntuTrustyGenericJenkinsSlave, Jenkins
from cgcloud.core import fabric_task
from cgcloud.core.common_iam_policies import s3_full_policy, sdb_full_policy
from cgcloud.fabric.operations import sudo
from cgcloud.lib.util import abreviated_snake_case_class_name, heredoc


class ToilJenkinsSlave( UbuntuTrustyGenericJenkinsSlave ):
    """
    A Jenkins slave suitable for running Toil unit tests, specifically the Mesos batch system and
    the AWS job store. Legacy batch systems (parasol, gridengine, ...) are not yet supported.
    """

    @classmethod
    def recommended_instance_type( cls ):
        return "m3.large"

    @fabric_task
    def _setup_package_repos( self ):
        super( ToilJenkinsSlave, self )._setup_package_repos( )
        sudo( "apt-key adv --keyserver keyserver.ubuntu.com --recv E56151BF" )
        distro = run( "lsb_release -is | tr '[:upper:]' '[:lower:]'" )
        codename = run( "lsb_release -cs" )
        run( 'echo "deb http://repos.mesosphere.io/{} {} main"'
             '| sudo tee /etc/apt/sources.list.d/mesosphere.list'.format( distro, codename ) )

    def _list_packages_to_install( self ):
        return super( ToilJenkinsSlave, self )._list_packages_to_install( ) + [
            'mesos', 'python-dev', 'build-essential' ] + [
                   'gridengine-' + p for p in ('common', 'master', 'client', 'exec') ]

    def _get_debconf_selections( self ):
        return super( ToilJenkinsSlave, self )._get_debconf_selections( ) + [
            'gridengine-master shared/gridenginemaster string localhost',
            'gridengine-master shared/gridenginecell string default',
            'gridengine-master shared/gridengineconfig boolean true' ]

    def _post_install_packages( self ):
        super( ToilJenkinsSlave, self )._post_install_packages( )
        self.setup_repo_host_keys()
        self.__disable_mesos_daemons( )
        self.__install_mesos_egg( )
        self.__install_parasol( )
        self.__patch_distutils( )
        self.__configurel_gridengine( )

    @fabric_task
    def __disable_mesos_daemons( self ):
        for daemon in ('master', 'slave'):
            sudo( 'echo manual > /etc/init/mesos-%s.override' % daemon )

    @fabric_task
    def __install_mesos_egg( self ):
        # FIXME: this is the ubuntu 14.04 version. Wont work with other versions.
        run( "wget http://downloads.mesosphere.io/master/ubuntu/14.04/"
             "mesos-0.22.0-py2.7-linux-x86_64.egg" )
        # we need a newer version of protobuf than comes default on ubuntu
        sudo( "pip install --upgrade protobuf", pty=False )
        sudo( "easy_install mesos-0.22.0-py2.7-linux-x86_64.egg" )

    @fabric_task
    def __install_parasol( self ):
        run( "git clone git@github.com:BD2KGenomics/parasol-binaries.git" )
        sudo( "cp parasol-binaries/* /usr/local/bin" )

    def _get_iam_ec2_role( self ):
        role_name, policies = super( ToilJenkinsSlave, self )._get_iam_ec2_role( )
        role_name += '--' + abreviated_snake_case_class_name( ToilJenkinsSlave )
        policies.update( dict( s3_full=s3_full_policy, sdb_full=sdb_full_policy ) )
        return role_name, policies

    @fabric_task
    def __patch_distutils( self ):
        """
        https://hg.python.org/cpython/rev/cf70f030a744/
        https://bitbucket.org/pypa/setuptools/issues/248/exit-code-is-zero-when-upload-fails
        """
        # FIXME: use remote popen()
        put( remote_path='distutils.patch', local_path=StringIO( heredoc( """
            --- a/Lib/distutils/command/upload.py
            +++ b/Lib/distutils/command/upload.py
            @@ -10,7 +10,7 @@ import urlparse
             import cStringIO as StringIO
             from hashlib import md5

            -from distutils.errors import DistutilsOptionError
            +from distutils.errors import DistutilsError, DistutilsOptionError
             from distutils.core import PyPIRCCommand
             from distutils.spawn import spawn
             from distutils import log
            @@ -181,7 +181,7 @@ class upload(PyPIRCCommand):
                             self.announce(msg, log.INFO)
                     except socket.error, e:
                         self.announce(str(e), log.ERROR)
            -            return
            +            raise
                     except HTTPError, e:
                         status = e.code
                         reason = e.msg
            @@ -190,5 +190,6 @@ class upload(PyPIRCCommand):
                         self.announce('Server response (%s): %s' % (status, reason),
                                       log.INFO)
                     else:
            -            self.announce('Upload failed (%s): %s' % (status, reason),
            -                          log.ERROR)
            +            msg = 'Upload failed (%s): %s' % (status, reason)
            +            self.announce(msg, log.ERROR)
            +            raise DistutilsError(msg)""" ) ) )
        sudo( "sudo patch -d /usr/lib/python2.7 -p2 < distutils.patch" )
        run( 'rm distutils.patch' )

    @fabric_task
    def __configurel_gridengine( self ):
        def qconf( arg, **kwargs ):
            # qconf can't read from stdin for some reason, neither -, /dev/stdin or /dev/fd/0 works
            tmp = 'qconf.tmp'
            put( remote_path=tmp,
                 local_path=StringIO( '\n'.join( ' '.join( i ) for i in kwargs.iteritems( ) ) ) )
            sudo( ' '.join( [ 'qconf', arg, tmp ] ) )
            run( ' '.join( [ 'rm', tmp ] ) )

        # Add the user defined in fname to the Sun Grid Engine cluster.
        qconf( '-Auser', name=Jenkins.user, oticket='0', fshare='0', delete_time='0',
               default_project='NONE' )
        # Adds users to Sun Grid Engine user access lists (ACLs).
        sudo( 'qconf -au %s arusers' % Jenkins.user )
        # Add hosts hostname to the list of hosts allowed to submit Sun Grid Engine jobs and
        # control their behavior only.
        sudo( 'qconf -as localhost' )
        # Remove all currently defined execution hosts
        run( 'for i in `qconf -sel`; do sudo qconf -de $i ; done' )
        # Add an execution host
        qconf( '-Ae', hostname='localhost', load_scaling='NONE', complex_values='NONE',
               user_lists='arusers', xuser_lists='NONE', projects='NONE', xprojects='NONE',
               usage_scaling='NONE', report_variables='NONE' );
        # Add a parallel environment
        qconf( '-Ap', pe_name='smp', slots='999', user_lists='NONE', xuser_lists='NONE',
               start_proc_args='/bin/true', stop_proc_args='/bin/true', allocation_rule='$pe_slots',
               control_slaves='FALSE', job_is_first_task='TRUE', urgency_slots='min',
               accounting_summary='FALSE' )
        # Add a q, the slots and processors will be adjusted dynamically, by an init script
        qconf( '-Aq', qname='all.q', processors='1', slots='1', hostlist='localhost', seq_no='0',
               load_thresholds='np_load_avg=1.75', suspend_thresholds='NONE', nsuspend='1',
               suspend_interval='00:05:00', priority='0', min_cpu_interval='00:05:00',
               qtype='BATCH INTERACTIVE', ckpt_list='NONE', pe_list='make smp', rerun='FALSE',
               tmpdir='/tmp', shell='/bin/bash', prolog='NONE', epilog='NONE',
               shell_start_mode='posix_compliant', starter_method='NONE', suspend_method='NONE',
               resume_method='NONE', terminate_method='NONE', notify='00:00:60', owner_list='NONE',
               user_lists='arusers', xuser_lists='NONE', subordinate_list='NONE',
               complex_values='NONE', projects='NONE', xprojects='NONE', calendar='NONE',
               initial_state='default', s_rt='INFINITY', h_rt='INFINITY', s_cpu='INFINITY',
               h_cpu='INFINITY', s_fsize='INFINITY', h_fsize='INFINITY', s_data='INFINITY',
               h_data='INFINITY', s_stack='INFINITY', h_stack='INFINITY', s_core='INFINITY',
               h_core='INFINITY', s_rss='INFINITY', h_rss='INFINITY', s_vmem='INFINITY',
               h_vmem='INFINITY' )

        self._register_init_script( 'gridengine-conf', heredoc( """
            description "GridEngine auto-configuration"
            console log
            # I would rather depend on the gridengine daemons but don't know how as they are
            # started by SysV init scripts. Supposedly the 'rc' job is run last.
            start on started rc
            pre-start script
                cores=$(grep -c '^processor' /proc/cpuinfo)
                qconf -mattr queue processors $cores `qselect`
                qconf -mattr queue slots $cores `qselect`
            end script""" ) )

        for daemon in ('exec', 'master'):
            sudo( '/etc/init.d/gridengine-%s stop' % daemon )
        sudo( "killall -9 -r 'sge_.*'" )  # the exec daemon likes to hang
        act_qmaster = '/var/lib/gridengine/default/common/act_qmaster'
        sudo( 'echo localhost > ' + act_qmaster )
        sudo( 'chown sgeadmin:sgeadmin ' + act_qmaster )
        sudo( 'echo localhost `hostname -f` > /var/lib/gridengine/default/common/host_aliases' )
        for daemon in ('master', 'exec'):
            sudo( '/etc/init.d/gridengine-%s start' % daemon )
        self._run_init_script( 'gridengine-conf' )
        while 'execd is in unknown state' in run( 'qstat -f -q all.q -explain a', warn_only=True ):
            time.sleep( 1 )
