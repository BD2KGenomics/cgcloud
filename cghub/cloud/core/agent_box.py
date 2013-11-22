from StringIO import StringIO
import base64
from cghub.util import shell, ilen
from fabric.context_managers import settings
from fabric.operations import sudo, run, get, put
import re
import zlib
from cghub.cloud.core.box import fabric_task
from cghub.cloud.core.source_control_client import SourceControlClient


class AgentBox( SourceControlClient ):
    """
    A box on which to install the agent. It inherits SourceControlClient because we would like to
    install the agent directly from its source repository.
    """

    def _manages_keys_internally( self ):
        return True

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
        authorized_keys = run( 'echo ~/authorized_keys' )
        kwargs = dict(
            availability_zone=self.ctx.availability_zone,
            namespace=self.ctx.namespace,
            ec2_keypair_globs=' '.join( shell.quote( glob ) for glob in self.ec2_keypair_globs ),
            authorized_keys=authorized_keys,
            user=self.username( ),
            group=self.username( ) )
        script = run( '~/agent/bin/cgcloudagent --init-script'
                      ' --zone {availability_zone}'
                      ' --namespace {namespace}'
                      ' --authorized-keys-file {authorized_keys}'
                      ' --keypairs {ec2_keypair_globs}'
                      ' --user {user}'
                      ' --group {group}'
                      '| gzip -c | base64'.format( **kwargs ) )
        script = self.gunzip_base64_decode( script )
        self._register_init_script( script, 'cgcloudagent' )
        sudo( '/etc/init.d/cgcloudagent start' )

        sshd_config_path = '/etc/ssh/sshd_config'
        sshd_config = sudo( 'gzip -c %s | base64' % sshd_config_path )
        sshd_config = StringIO( self.gunzip_base64_decode( sshd_config ) )
        self.patch_sshd_config( sshd_config, authorized_keys )
        put( remote_path=sshd_config_path, local_path=sshd_config, use_sudo=True )

    @staticmethod
    def gunzip_base64_decode( s ):
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

    @staticmethod
    def patch_sshd_config( sshd_config, authorized_keys ):
        """
        Modifies the AuthorizedKeysFile statement in the given file-like object containing a
        valid sshd_config file to include the given path. If the AuthorizedKeysFile statement is
        commented out using a # character, it will be activated by removing the # character
        assuming that the commented statement represents the default. If there are more than one
        active statement or no active statement and more than one commented statement,
        an exception is thrown since it would be unsafe to chose one of them for modification.

        TODO: Consider disambiguating multiple active statements by simply using the last one

        A single active statement:

        >>> f = StringIO('bla\\n AuthorizedKeysFile bar\\nbla' )
        >>> AgentBox.patch_sshd_config(f, 'foo')
        >>> f.getvalue()
        'bla\\nAuthorizedKeysFile foo bar\\nbla'

        A single commented statement:

        >>> f = StringIO('bla\\n # AuthorizedKeysFile bar\\nbla' )
        >>> AgentBox.patch_sshd_config(f, 'foo')
        >>> f.getvalue()
        'bla\\nAuthorizedKeysFile foo bar\\nbla'

        A single active statement and two commented statements:

        >>> f = StringIO('AuthorizedKeysFile bar1\\n#AuthorizedKeysFile bar2\\n#AuthorizedKeysFile bar3' )
        >>> AgentBox.patch_sshd_config(f, 'foo')
        >>> f.getvalue()
        'AuthorizedKeysFile foo bar1\\n#AuthorizedKeysFile bar2\\n#AuthorizedKeysFile bar3'

        Two commented statements:

        >>> f = StringIO('#AuthorizedKeysFile bar1\\n#AuthorizedKeysFile bar2' )
        >>> AgentBox.patch_sshd_config(f, 'foo')
        Traceback (most recent call last):
        ....
        RuntimeError: Ambiguous AuthorizedKeysFile statements

        Two active statements statements:

        >>> f = StringIO('AuthorizedKeysFile bar1\\nAuthorizedKeysFile bar2' )
        >>> AgentBox.patch_sshd_config(f, 'foo')
        Traceback (most recent call last):
        ....
        RuntimeError: Ambiguous AuthorizedKeysFile statements
        """
        sshd_config.seek( 0 )
        lines = sshd_config.readlines( )
        regex = re.compile( r'(\s*#)?\s*(AuthorizedKeysFile\s+)(.*)$' )
        matches = [ ( i, regex.match( line ) ) for i, line in enumerate( lines ) ]
        commented_lines = [ (i, m) for i, m in matches if m and m.group( 1 ) ]
        active_lines = [ (i, m) for i, m in matches if m and not m.group( 1 ) ]
        if len( active_lines ) == 1:
            i, m = active_lines[ 0 ]
        elif len( active_lines ) == 0 and len( commented_lines ) == 1:
            i, m = commented_lines[ 0 ]
        else:
            raise RuntimeError( "Ambiguous AuthorizedKeysFile statements" )
        lines[ i ] = '%s%s %s\n' % ( m.group( 2 ), authorized_keys, m.group( 3 ) )
        sshd_config.truncate( 0 )
        sshd_config.writelines( lines )
