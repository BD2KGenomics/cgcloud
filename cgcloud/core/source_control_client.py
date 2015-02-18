from fabric.operations import run

from cgcloud.fabric.operations import sudo
from cgcloud.core.box import fabric_task
from cgcloud.core.package_manager_box import PackageManagerBox


class SourceControlClient( PackageManagerBox ):
    """
    A box that uses source control software
    """

    @fabric_task
    def setup_repo_host_keys(self, user=None):
        #
        # Pre-seed the host keys from bitbucket and github, such that ssh doesn't prompt during
        # the initial checkouts.
        #
        for host in [ 'bitbucket.org', 'github.com' ]:
            command = 'ssh-keyscan -t rsa %s >> ~/.ssh/known_hosts' % host
            if user is None:
                run( command )
            elif user == 'root':
                sudo( command )
            else:
                sudo( command, user=user, sudo_args='-i' )

    def _list_packages_to_install(self):
        return super( SourceControlClient, self )._list_packages_to_install( ) + [
            'git',
            'subversion',
            'mercurial' ]
