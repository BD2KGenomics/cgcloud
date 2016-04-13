from StringIO import StringIO
import time
import re

from fabric.operations import run, put

from cgcloud.core.mesos_box import MesosBox
from cgcloud.core.ubuntu_box import Python27UpdateUbuntuBox
from cgcloud.jenkins.generic_jenkins_slaves import UbuntuTrustyGenericJenkinsSlave
from cgcloud.jenkins.jenkins_master import Jenkins
from cgcloud.core.box import fabric_task
from cgcloud.core.common_iam_policies import s3_full_policy, sdb_full_policy
from cgcloud.core.docker_box import DockerBox
from cgcloud.fabric.operations import sudo, remote_sudo_popen
from cgcloud.lib.util import abreviated_snake_case_class_name, heredoc


class ToilJenkinsSlave( UbuntuTrustyGenericJenkinsSlave,
                        Python27UpdateUbuntuBox,
                        DockerBox,
                        MesosBox ):
    """
    A Jenkins slave suitable for running Toil unit tests, specifically the Mesos batch system and
    the AWS job store. Legacy batch systems (parasol, gridengine, ...) are not yet supported.
    """

    @classmethod
    def recommended_instance_type( cls ):
        return "m3.large"

    def _list_packages_to_install( self ):
        return super( ToilJenkinsSlave, self )._list_packages_to_install( ) + [
            'python-dev', 'gcc', 'make',
            'libffi-dev',  # pynacl -> toil, Azure client-side encryption
            'libcurl4-openssl-dev',  # pycurl -> SPARQLWrapper -> rdflib>=4.2.0 -> cwltool -> toil
            'slurm-llnl', # SLURM
        ] + [ 'gridengine-' + p for p in ('common', 'master', 'client', 'exec') ]

    def _get_debconf_selections( self ):
        return super( ToilJenkinsSlave, self )._get_debconf_selections( ) + [
            'gridengine-master shared/gridenginemaster string localhost',
            'gridengine-master shared/gridenginecell string default',
            'gridengine-master shared/gridengineconfig boolean true' ]

    def _post_install_packages( self ):
        super( ToilJenkinsSlave, self )._post_install_packages( )
        self.setup_repo_host_keys( )
        self.__disable_mesos_daemons( )
        self.__install_parasol( )
        self.__patch_distutils( )
        self.__configure_gridengine( )
        self.__configure_slurm( )

    @fabric_task
    def _setup_build_user( self ):
        super( ToilJenkinsSlave, self )._setup_build_user( )
        # Allow mount and umount such that Toil tests can use an isolated loopback filesystem for
        # TMPDIR (and therefore Toil's work directory), thereby preventing the tracking of
        # left-over files from being skewed by other activities on the ephemeral file system,
        # like build logs, creation of .pyc files, etc.
        for prog in ('mount', 'umount'):
            sudo( "echo 'jenkins ALL=(ALL) NOPASSWD: /bin/%s' >> /etc/sudoers" % prog )

    @fabric_task
    def __disable_mesos_daemons( self ):
        for daemon in ('master', 'slave'):
            sudo( 'echo manual > /etc/init/mesos-%s.override' % daemon )

    @fabric_task
    def __install_parasol( self ):
        run( "git clone https://github.com/BD2KGenomics/parasol-binaries.git" )
        sudo( "cp parasol-binaries/* /usr/local/bin" )
        run( "rm -rf parasol-binaries" )

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
        Fixed in 2.7.8: https://hg.python.org/cpython/raw-file/v2.7.8/Misc/NEWS
        """
        if self._remote_python_version( ) < (2, 7, 8):
            with remote_sudo_popen( 'patch -d /usr/lib/python2.7 -p2' ) as patch:
                patch.write( heredoc( """
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
                    +            raise DistutilsError(msg)""" ) )

    @fabric_task
    def __configure_gridengine( self ):
        """
        Configure the GridEngine daemons (master and exec) and creata a default queue. Ensure
        that the queue is updated to reflect the number of cores actually available.
        """

        ws = re.compile( r'\s+' )
        nl = re.compile( r'[\r\n]+' )

        def qconf( opt, **kwargs ):
            return qconf_dict( opt, kwargs )

        def qconf_dict( opt, d=None, file_name='qconf.tmp' ):
            if d:
                # qconf can't read from stdin for some reason, neither -, /dev/stdin or /dev/fd/0 works
                s = '\n'.join( ' '.join( i ) for i in d.iteritems( ) ) + '\n'
                put( remote_path=file_name, local_path=StringIO( s ) )
                sudo( ' '.join( [ 'qconf', opt, file_name ] ) )
                run( ' '.join( [ 'rm', file_name ] ) )
            else:
                return dict( tuple( ws.split( l, 1 ) )
                                 for l in nl.split( run( 'SGE_SINGLE_LINE=1 qconf ' + opt ) )
                                 if l and not l.startswith( '#' ) )

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
               usage_scaling='NONE', report_variables='NONE' )

        # Add a parallel environment
        qconf( '-Ap', pe_name='smp', slots='999', user_lists='NONE', xuser_lists='NONE',
               start_proc_args='/bin/true', stop_proc_args='/bin/true', allocation_rule='$pe_slots',
               control_slaves='FALSE', job_is_first_task='TRUE', urgency_slots='min',
               accounting_summary='FALSE' )

        # Add a queue, the slots and processors will be adjusted dynamically, by an init script
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

        # Enable on-demand scheduling. This will eliminate the long time that jobs spend waiting
        # in the qw state. There is no -Asconf so we have to fake it using -ssconf and -Msconf.
        sconf = qconf( '-ssconf' )
        sconf.update( dict( flush_submit_sec='1', flush_finish_sec='1',
                            schedule_interval='0:0:1' ) )
        qconf_dict( '-Msconf', sconf )

        # Enable immediate flushing of the accounting file. The SGE batch system in Toil uses the
        #  qacct program to determine the exit code of a finished job. The qacct program reads
        # the accounting file. By default, this file is written to every 15 seconds which means
        # that it may take up to 15 seconds before a finished job is seen by Toil. An
        # accounting_flush_time value of 00:00:00 causes the accounting file to be flushed
        # immediately, allowing qacct to report the status of finished jobs immediately. Again,
        # there is no -Aconf, so we fake it with -sconf and -Mconf. Also, the file name has to be
        # 'global'.
        conf = qconf( '-sconf' )
        params = dict( tuple( e.split( '=' ) ) for e in conf[ 'reporting_params' ].split( ' ' ) )
        params[ 'accounting_flush_time' ] = '00:00:00'
        conf[ 'reporting_params' ] = ' '.join( '='.join( e ) for e in params.iteritems( ) )
        qconf_dict( '-Mconf', conf, file_name='global' )

        # Register an init-script that ensures GridEngine uses localhost instead of hostname
        path = '/var/lib/gridengine/default/common/'
        self._register_init_script( 'gridengine-pre', heredoc( """
            description "GridEngine pre-start configuration"
            console log
            start on filesystem
            pre-start script
                echo localhost > {path}/act_qmaster ; chown sgeadmin:sgeadmin {path}/act_qmaster
                echo localhost `hostname -f` > {path}/host_aliases
            end script""" ) )

        # Register an init-script that adjust the queue config to reflect the number of cores
        self._register_init_script( 'gridengine-post', heredoc( """
            description "GridEngine post-start configuration"
            console log
            # I would rather depend on the gridengine daemons but don't know how as they are
            # started by SysV init scripts. Supposedly the 'rc' job is run last.
            start on started rc
            pre-start script
                cores=$(grep -c '^processor' /proc/cpuinfo)
                qconf -mattr queue processors $cores `qselect`
                qconf -mattr queue slots $cores `qselect`
            end script""" ) )

        # Run pre-start script
        for daemon in ('exec', 'master'):
            sudo( '/etc/init.d/gridengine-%s stop' % daemon )
        sudo( "killall -9 -r 'sge_.*'", warn_only=True )  # the exec daemon likes to hang
        self._run_init_script( 'gridengine-pre' )
        for daemon in ('master', 'exec'):
            sudo( '/etc/init.d/gridengine-%s start' % daemon )

        # Run post-start script
        self._run_init_script( 'gridengine-post' )
        while 'execd is in unknown state' in run( 'qstat -f -q all.q -explain a', warn_only=True ):
            time.sleep( 1 )

    @fabric_task
    def __configure_slurm( self ):
        """
        Configures SLURM in a single-node configuration with text-file accounting
        :return:
        """
        # Create munge key and start
        sudo('/usr/sbin/create-munge-key')
        sudo('/usr/sbin/service munge start')

        # slurm.conf needs cpus and memory in order to handle jobs with these resource requests
        cpus = int(run('/usr/bin/nproc'))
        memory = int(run('cat /proc/meminfo | grep MemTotal | awk \'{print $2}\'')) / 1024
        slurm_acct_file = '/var/log/slurm-llnl/slurm-acct.txt'

        slurm_conf = heredoc("""
            ClusterName=jenkins-testing
            ControlMachine=localhost
            SlurmUser=slurm
            SlurmctldPort=6817
            SlurmdPort=6818
            StateSaveLocation=/tmp
            SlurmdSpoolDir=/tmp/slurmd
            SwitchType=switch/none
            MpiDefault=none
            SlurmctldPidFile=/var/run/slurmctld.pid
            SlurmdPidFile=/var/run/slurmd.pid
            ProctrackType=proctrack/pgid
            CacheGroups=0
            ReturnToService=0
            SlurmctldTimeout=300
            SlurmdTimeout=300
            InactiveLimit=0
            MinJobAge=300
            KillWait=30
            Waittime=0
            SchedulerType=sched/backfill
            SelectType=select/cons_res
            FastSchedule=1

            # LOGGING
            SlurmctldDebug=3
            SlurmdDebug=3
            JobCompType=jobcomp/none

            # ACCOUNTING
            AccountingStorageLoc={slurm_acct_file}
            AccountingStorageType=accounting_storage/filetxt
            AccountingStoreJobComment=YES
            JobAcctGatherFrequency=30
            JobAcctGatherType=jobacct_gather/linux

            # COMPUTE NODES
            NodeName=localhost CPUs={cpus:d} State=UNKNOWN RealMemory={memory:d}
            PartitionName=debug Nodes=localhost Default=YES MaxTime=INFINITE State=UP
        """)
        slurm_conf_tmp = '/tmp/slurm.conf'
        slurm_conf_file = '/etc/slurm-llnl/slurm.conf'
        # Put config file in: /etc/slurm-llnl/slurm.conf
        put( remote_path=slurm_conf_tmp, local_path=StringIO( slurm_conf ) )
        sudo( 'mkdir -p /etc/slurm-llnl')
        sudo( 'mv %s %s' % (slurm_conf_tmp, slurm_conf_file ) )
        sudo('chown root:root %s' % slurm_conf_file )

        # Touch the accounting job file and make sure it's owned by slurm user
        sudo('mkdir -p /var/log/slurm-llnl')
        sudo('touch %s' % slurm_acct_file)
        sudo('chown slurm:slurm %s' % slurm_acct_file)
        sudo('chmod 644 %s' % slurm_acct_file)

        # Start slurm services
        sudo('/usr/sbin/service slurm-llnl start')

        # Ensure partition is up
        sudo('scontrol update NodeName=localhost State=Down')
        sudo('scontrol update NodeName=localhost State=Resume')

    def _docker_users( self ):
        return super( ToilJenkinsSlave, self )._docker_users( ) + [ self.default_account( ) ]
