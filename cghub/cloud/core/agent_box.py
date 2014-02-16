from StringIO import StringIO
import base64
from distutils.version import LooseVersion
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
    def __has_multi_file_authorized_keys( self ):
        self.has_multi_file_authorized_keys( run( 'ssh -V' ) )

    @staticmethod
    def has_multi_file_authorized_keys( version ):
        """
        >>> AgentBox.has_multi_file_authorized_keys( 'OpenSSH_6.2p2, OSSLShim 0.9.8r 8 Dec 2011' )
        True
        >>> AgentBox.has_multi_file_authorized_keys( 'OpenSSH_5.9, Bla, Bla' )
        True
        >>> AgentBox.has_multi_file_authorized_keys( 'OpenSSH_5.9p1, Bla, Bla' )
        True
        >>> AgentBox.has_multi_file_authorized_keys( 'OpenSSH_5.8, Bla, Bla' )
        False
        >>> AgentBox.has_multi_file_authorized_keys( 'Bla, Bla' )
        Traceback (most recent call last):
        ....
        RuntimeError: Can't determine OpenSSH version from 'Bla'
        """
        version = version.split( ',' )[ 0 ]
        prefix = 'OpenSSH_'
        if version.startswith( prefix ):
            return LooseVersion( version[ len( prefix ): ] ) >= LooseVersion( '5.9' )
        else:
            raise RuntimeError( "Can't determine OpenSSH version from '%s'" % version )

    @fabric_task
    def _post_install_packages( self ):
        super( AgentBox, self )._post_install_packages( )
        sudo( 'pip install --upgrade pip==1.5.2' ) # lucid & centos5 have an ancient pip
        sudo( 'pip install --upgrade virtualenv' )
        self.setup_repo_host_keys( )
        run( 'virtualenv ~/agent' )
        with settings( forward_agent=True ):
            run( '~/agent/bin/pip install '
                 '--process-dependency-links '  # pip 1.5.x deprecates dependency_links in setup.py
                 '--allow-external argparse '  # needed on CentOS 5 and 6 for some reason
                 'hg+ssh://hg@bitbucket.org/cghub/cghub-cloud-agent@default' )
        authorized_keys = run( 'echo ~/authorized_keys' )
        kwargs = dict(
            availability_zone=self.ctx.availability_zone,
            namespace=self.ctx.namespace,
            ec2_keypair_globs=' '.join(
                shell.quote( glob ) for glob in self.ec2_keypair_globs ),
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
        script = self.__gunzip_base64_decode( script )
        self._register_init_script( script, 'cgcloudagent' )
        self._run_init_script( 'cgcloudagent' )

        sshd_config_path = '/etc/ssh/sshd_config'
        sshd_config = sudo( 'gzip -c %s | base64' % sshd_config_path )
        sshd_config = StringIO( self.__gunzip_base64_decode( sshd_config ) )
        if self.__has_multi_file_authorized_keys( ):
            patch_method = self.__patch_sshd_config
        else:
            patch_method = self.__patch_sshd_config2
        patch_method( sshd_config, authorized_keys )
        put( remote_path=sshd_config_path, local_path=sshd_config, use_sudo=True )

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

    @staticmethod
    def __patch_sshd_config( sshd_config, authorized_keys ):
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
        >>> AgentBox._AgentBox__patch_sshd_config(f, 'foo')
        >>> f.getvalue()
        'bla\\nAuthorizedKeysFile foo bar\\nbla'

        A single commented statement:

        >>> f = StringIO('bla\\n # AuthorizedKeysFile bar\\nbla' )
        >>> AgentBox._AgentBox__patch_sshd_config(f, 'foo')
        >>> f.getvalue()
        'bla\\nAuthorizedKeysFile foo bar\\nbla'

        A single active statement and two commented statements:

        >>> f = StringIO('AuthorizedKeysFile bar1\\n#AuthorizedKeysFile bar2\\n#AuthorizedKeysFile bar3' )
        >>> AgentBox._AgentBox__patch_sshd_config(f, 'foo')
        >>> f.getvalue()
        'AuthorizedKeysFile foo bar1\\n#AuthorizedKeysFile bar2\\n#AuthorizedKeysFile bar3'

        Two commented statements:

        >>> f = StringIO('#AuthorizedKeysFile bar1\\n#AuthorizedKeysFile bar2' )
        >>> AgentBox._AgentBox__patch_sshd_config(f, 'foo')
        Traceback (most recent call last):
        ....
        RuntimeError: Ambiguous AuthorizedKeysFile statements

        Two active statements:

        >>> f = StringIO('AuthorizedKeysFile bar1\\nAuthorizedKeysFile bar2' )
        >>> AgentBox._AgentBox__patch_sshd_config(f, 'foo')
        Traceback (most recent call last):
        ....
        RuntimeError: Ambiguous AuthorizedKeysFile statements

        No statements, add one:

        >>> f = StringIO('bla\\n' )
        >>> AgentBox._AgentBox__patch_sshd_config(f, 'foo')
        >>> f.getvalue()
        'bla\\nAuthorizedKeysFile foo\\n'
        """
        statement = 'AuthorizedKeysFile'
        sshd_config.seek( 0 )
        lines = sshd_config.readlines( )
        regex = re.compile( r'(\s*#)?\s*%s\s+(.*)$' % statement )
        matches = [ ( i, regex.match( line ) ) for i, line in enumerate( lines ) ]
        commented_lines = [ (i, m) for i, m in matches if m and m.group( 1 ) ]
        active_lines = [ (i, m) for i, m in matches if m and not m.group( 1 ) ]
        if len( active_lines ) == 1:
            i, m = active_lines[ 0 ]
        elif len( active_lines ) == 0 and len( commented_lines ) == 1:
            i, m = commented_lines[ 0 ]
        elif len( active_lines ) == 0 and len( commented_lines ) == 0:
            i, m = None, None
        else:
            raise RuntimeError( "Ambiguous %s statements" % statement )
        if i is None:
            lines.append( "%s %s\n" % ( statement, authorized_keys) )
        else:
            lines[ i ] = '%s %s %s\n' % ( statement, authorized_keys, m.group( 2 ) )
        sshd_config.truncate( 0 )
        sshd_config.writelines( lines )

    @staticmethod
    def __patch_sshd_config2( sshd_config, authorized_keys ):
        """
        Adds the undocumented AuthorizedKeysFile2 statement to the given config file. If there
        already is such a statement, an exception will raised. If there are one or more commented
        statements, the last one will be uncommented and modified to refer to the given
        authorized keys file. If there are neither commented or active statements, one will be
        appended to the end of the file.

        This method targets OpenSSH installations prior to 5.9 in which the AuthorizedKeysFile
        statement was extended to support multiple files and the AuthorizedKeysFile2 statement
        was deprecated.

        A single statement, don't override it

        >>> f = StringIO('bla\\n AuthorizedKeysFile2 bar\\nbla' )
        >>> AgentBox._AgentBox__patch_sshd_config2(f, 'foo')
        Traceback (most recent call last):
        ....
        RuntimeError: AuthorizedKeysFile2 statement already present

        A single commented statement, modify it:

        >>> f = StringIO('bla\\n # AuthorizedKeysFile2 bar\\nbla' )
        >>> AgentBox._AgentBox__patch_sshd_config2(f, 'foo')
        >>> f.getvalue()
        'bla\\nAuthorizedKeysFile2 foo\\nbla'

        No statements, add one:

        >>> f = StringIO('bla\\n' )
        >>> AgentBox._AgentBox__patch_sshd_config2(f, 'foo')
        >>> f.getvalue()
        'bla\\nAuthorizedKeysFile2 foo\\n'
        """
        statement = 'AuthorizedKeysFile2'
        sshd_config.seek( 0 )
        lines = sshd_config.readlines( )
        regex = re.compile( r'(\s*#)?\s*(%s\s+)(.*)$' % statement )
        matches = [ ( i, regex.match( line ) ) for i, line in enumerate( lines ) ]
        commented_lines = [ (i, m) for i, m in matches if m and m.group( 1 ) ]
        active_lines = [ (i, m) for i, m in matches if m and not m.group( 1 ) ]
        if len( active_lines ) > 0:
            raise RuntimeError( "%s statement already present" % statement )
        elif len( commented_lines ) > 0:
            i, m = commented_lines[ -1 ]
            lines[ i ] = '%s%s\n' % ( m.group( 2 ), authorized_keys )
        else:
            lines.append( '%s %s\n' % ( statement, authorized_keys ) )

        sshd_config.truncate( 0 )
        sshd_config.writelines( lines )

    def _get_iam_ec2_role( self ):
        role_name, policies = super( AgentBox, self )._get_iam_ec2_role( )
        policies.update( {
            'ec2_read_only': {
                "Version": "2012-10-17",
                "Statement": [
                    { "Effect": "Allow", "Resource": "*", "Action": "ec2:Describe*" },
                    { "Effect": "Allow", "Resource": "*", "Action": "autoscaling:Describe*" },
                    { "Effect": "Allow", "Resource": "*",
                        "Action": "elasticloadbalancing:Describe*" },
                    { "Effect": "Allow", "Resource": "*", "Action": [
                        "cloudwatch:ListMetrics",
                        "cloudwatch:GetMetricStatistics",
                        "cloudwatch:Describe*" ] } ] },
            's3_read_only': {
                "Version": "2012-10-17",
                "Statement": [
                    { "Effect": "Allow", "Resource": "*",
                        "Action": [ "s3:Get*", "s3:List*" ] } ] },
            'iam_read_only': {
                "Version": "2012-10-17",
                "Statement": [
                    { "Effect": "Allow", "Resource": "*",
                        "Action": [ "iam:List*", "iam:Get*" ] } ] },
            'sqs_custom': {
                "Version": "2012-10-17",
                "Statement": [
                    { "Effect": "Allow", "Resource": "*", "Action": [
                        "sqs:Get*",
                        "sqs:List*",
                        "sqs:CreateQueue",
                        "sqs:SetQueueAttributes",
                        "sqs:ReceiveMessage",
                        "sqs:DeleteMessageBatch" ] } ] },
            'sns_custom': {
                "Version": "2012-10-17",
                "Statement": [
                    { "Effect": "Allow", "Resource": "*", "Action": [
                        "sns:Get*",
                        "sns:List*",
                        "sns:CreateTopic",
                        "sns:Subscribe" ] } ] }
        } )
        return role_name + '-agent', policies

