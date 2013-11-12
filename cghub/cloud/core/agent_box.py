from fabric.context_managers import settings
from fabric.operations import sudo, run
from cghub.cloud.core.box import fabric_task
from cghub.cloud.core.source_control_client import SourceControlClient


class AgentBox( SourceControlClient ):
    """
    A box on which to install the agent. It inherits SourceControlClient because we would like to
    install the agent directly from its source repository.
    """

    def _list_packages_to_install( self ):
        return super( AgentBox, self )._list_packages_to_install( ) + [
            'python',
            'python-pip',
            # for PyCrypto:
            'python-dev',
            'autoconf',
            'automake',
            'binutils',
            'gcc',
            'make'
        ]

    @fabric_task
    def _post_install_packages( self ):
        super( AgentBox, self )._post_install_packages( )
        sudo( 'pip install --upgrade pip' ) # some distros (lucid & centos5 ) have an ancient pip
        sudo( 'pip install --upgrade virtualenv' )
        self.setup_repo_host_keys( )
        run( 'virtualenv ~/agent' )
        with settings( forward_agent=True ):
            run( '~/agent/bin/pip install hg+ssh://hg@bitbucket.org/cghub/cghub-cloud-agent'
                 '@default'
                 '#egg=cghub-cloud-agent-1.0.dev1' )
        kwargs = dict(
            availability_zone=self.ctx.availability_zone,
            namespace=self.ctx.namespace,
            ec2_keypair_globs=' '.join( "'%s'" % glob for glob in self.ec2_keypair_globs ),
            authorized_keys='~/authorized_keys',
            user=self.username( ),
            group=self.username( ) )
        script = run( '~/agent/bin/cgcloudagent --init-script'
                      ' --zone {availability_zone}'
                      ' --namespace {namespace}'
                      ' --authorized-keys-file {authorized_keys}'
                      ' --keypairs {ec2_keypair_globs}'
                      ' --user {user}'
                      ' --group {group}'.format( **kwargs ) )
        script = script.replace( '\r', '' ) # don't know how these get in there
        self._register_init_script( script, 'cgcloudagent' )
        sudo( '/etc/init.d/cgcloudagent start' )
