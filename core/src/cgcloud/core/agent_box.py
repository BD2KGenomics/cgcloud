import base64
import zlib
from bd2k.util.iterables import concat

from fabric.context_managers import settings
from fabric.operations import run

from bd2k.util import shell, less_strict_bool
from bd2k.util.strings import interpolate as fmt

from cgcloud.core.init_box import AbstractInitBox
from cgcloud.core.common_iam_policies import *
from cgcloud.fabric.operations import sudo, pip
from cgcloud.core.package_manager_box import PackageManagerBox
from cgcloud.lib.util import abreviated_snake_case_class_name
from cgcloud.core.box import fabric_task


class AgentBox( PackageManagerBox, AbstractInitBox ):
    """
    A box on which to install the agent.
    """

    def other_accounts( self ):
        """
        Returns the names of accounts for which, in addition to the account returned by
        Box.username(), authorized SSH keys should be managed by this agent.
        """
        return [ ]

    agent_depends_on_pycrypto = False

    def __init__( self, ctx ):
        super( AgentBox, self ).__init__( ctx )
        self._enable_agent = None

    @property
    def enable_agent( self ):
        if self._enable_agent is None:
            raise RuntimeError(
                "Enable_agent property hasn't been set. Must call _set_instance_options() before "
                "using this instance." )
        return self._enable_agent

    def _set_instance_options( self, options ):
        super( AgentBox, self )._set_instance_options( options )
        self._enable_agent = less_strict_bool( options.get( 'enable_agent' ) )

    def _get_instance_options( self ):
        return self.__get_options( super( AgentBox, self )._get_instance_options( ) )

    def _get_image_options( self ):
        return self.__get_options( super( AgentBox, self )._get_image_options( ) )

    def __get_options( self, options ):
        return dict( options, enable_agent=str( self.enable_agent ) )

    def _manages_keys_internally( self ):
        return self.enable_agent

    def _list_packages_to_install( self ):
        packages = super( AgentBox, self )._list_packages_to_install( )
        if self.enable_agent:
            packages += [
                'python',
                'python-pip' ]
            if self.agent_depends_on_pycrypto:
                packages += [
                    'python-dev',
                    'autoconf',
                    'automake',
                    'binutils',
                    'gcc',
                    'make' ]
        return packages

    @fabric_task
    def _post_install_packages( self ):
        super( AgentBox, self )._post_install_packages( )
        if self.enable_agent:
            self.__setup_agent( )

    def _enable_agent_metrics( self ):
        """
        Overide this in a subclass to enable reporting of additional CloudWatch metrics like disk
        space and memory. The metric collection requires the psutil package which in turn
        requires a compiler and Python headers to be installed.
        """
        return False

    def __setup_agent( self ):
        availability_zone = self.ctx.availability_zone
        namespace = self.ctx.namespace
        ec2_keypair_globs = ' '.join( shell.quote( _ ) for _ in self.ec2_keypair_globs )
        accounts = ' '.join( [ self.admin_account( ) ] + self.other_accounts( ) )
        admin_account = self.admin_account( )
        run_dir = '/var/run/cgcloudagent'
        log_dir = '/var/log'
        install_dir = '/opt/cgcloudagent'

        # Lucid & CentOS 5 have an ancient pip
        pip( 'install --upgrade pip==1.5.2', use_sudo=True )
        pip( 'install --upgrade virtualenv', use_sudo=True )
        sudo( fmt( 'mkdir -p {install_dir}' ) )
        sudo( fmt( 'chown {admin_account}:{admin_account} {install_dir}' ) )
        # By default, virtualenv installs the latest version of pip. We want a specific
        # version, so we tell virtualenv not to install pip and then install that version of
        # pip using easy_install.
        run( fmt( 'virtualenv --no-pip {install_dir}' ) )
        run( fmt( '{install_dir}/bin/easy_install pip==1.5.2' ) )

        with settings( forward_agent=True ):
            venv_pip = install_dir + '/bin/pip'
            if self._enable_agent_metrics( ):
                pip( path=venv_pip, args='install psutil==3.4.1' )
            with self._project_artifacts( 'agent' ) as artifacts:
                pip( path=venv_pip,
                     args=concat( 'install',
                                  '--allow-external', 'argparse',  # needed on CentOS 5 and 6
                                  artifacts ) )

        sudo( fmt( 'mkdir {run_dir}' ) )
        script = self.__gunzip_base64_decode( run( fmt(
            '{install_dir}/bin/cgcloudagent'
            ' --init-script'
            ' --zone {availability_zone}'
            ' --namespace {namespace}'
            ' --accounts {accounts}'
            ' --keypairs {ec2_keypair_globs}'
            ' --user root'
            ' --group root'
            ' --pid-file {run_dir}/cgcloudagent.pid'
            ' --log-spill {log_dir}/cgcloudagent.out'
            '| gzip -c | base64' ) ) )
        self._register_init_script( 'cgcloudagent', script )
        self._run_init_script( 'cgcloudagent' )

    def _get_iam_ec2_role( self ):
        role_name, policies = super( AgentBox, self )._get_iam_ec2_role( )
        if self.enable_agent:
            role_name += '--' + abreviated_snake_case_class_name( AgentBox )
            policies.update( dict(
                ec2_read_only=ec2_read_only_policy,
                s3_read_only=s3_read_only_policy,
                iam_read_only=iam_read_only_policy,
                sqs_agent=dict( Version="2012-10-17", Statement=[
                    dict( Effect="Allow", Resource="*", Action=[
                        "sqs:Get*",
                        "sqs:List*",
                        "sqs:CreateQueue",
                        "sqs:SetQueueAttributes",
                        "sqs:ReceiveMessage",
                        "sqs:DeleteMessage" ] ) ] ),
                sns_agent=dict( Version="2012-10-17", Statement=[
                    dict( Effect="Allow", Resource="*", Action=[
                        "sns:Get*",
                        "sns:List*",
                        "sns:CreateTopic",
                        "sns:Subscribe" ] ) ] ),
                cloud_watch=dict( Version='2012-10-17', Statement=[
                    dict( Effect='Allow', Resource='*', Action=[
                        'cloudwatch:Get*',
                        'cloudwatch:List*',
                        'cloudwatch:PutMetricData' ] ) ] ) ) )
        return role_name, policies

    @staticmethod
    def __gunzip_base64_decode( s ):
        """
        Fabric doesn't have get( ..., use_sudo=True ) [1] so we need to use

        sudo( 'cat ...' )

        to download protected files. However it also munges line endings [2] so to be safe we

        sudo( 'cat ... | gzip | base64' )

        and this method unravels that.

        [1]: https://github.com/fabric/fabric/issues/700
        [2]: https://github.com/trehn/blockwart/issues/39
        """
        # See http://stackoverflow.com/questions/2695152/in-python-how-do-i-decode-gzip-encoding#answer-2695466
        # for the scoop on 16 + zlib.MAX_WBITS.
        return zlib.decompress( base64.b64decode( s ), 16 + zlib.MAX_WBITS )
