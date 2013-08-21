from fabric.operations import sudo
from cghub.cloud.box import fabric_task
from cghub.cloud.unix_box import UnixBox


class SourceControlClient( UnixBox ):
    """
    A box that uses source control software
    """
    @fabric_task
    def setup_repo_host_keys(self, user):
        # Pre-seed the host keys from bitbucket and github, such that ssh doesn't prompt during
        # the initial checkouts.
        #
        for host in [ 'bitbucket.org', 'github.org' ]:
            sudo( 'ssh-keyscan -t rsa {host} >> ~{user}/.ssh/known_hosts'.format( host=host,
                                                                                  user=user ),
                  user=user )

    def _list_packages_to_install(self):
        return super( SourceControlClient, self )._list_packages_to_install( ) + [
            'git',
            'subversion',
            'mercurial' ]
