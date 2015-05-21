import os
import sys

from pkg_resources import parse_version
from setuptools import setup, find_packages

dependency_links = [ ]

cgcloud_version = '1.0.dev1'

try:
    from subprocess import check_output
except ImportError:
    # check_output is not available in Python 2.6
    from subprocess import Popen, PIPE, CalledProcessError
    def check_output(*popenargs, **kwargs):
        if 'stdout' in kwargs:
            raise ValueError('stdout argument not allowed, it will be overridden.')
        process = Popen(stdout=PIPE, *popenargs, **kwargs)
        output, unused_err = process.communicate()
        retcode = process.poll()
        if retcode:
            cmd = kwargs.get("args")
            if cmd is None:
                cmd = popenargs[0]
            raise CalledProcessError(retcode, cmd, output=output)
        return output


def add_private_dependency( name, version=cgcloud_version, git_ref=None ):
    if git_ref is None:
        if parse_version( version ).is_prerelease:
            project_dir = os.path.dirname( os.path.abspath( __file__ ) )
            git_ref = check_output( [ 'git', 'rev-parse', '--abbrev-ref', 'HEAD' ],
                                    cwd=project_dir ).strip( )
            # pip checks out individual commits which creates a detached HEAD, so we look at
            # remote branches containing the commit
            if git_ref == 'HEAD':
                git_ref = check_output( [ 'git', 'branch', '-r', '--contains', 'HEAD' ],
                                        cwd=project_dir ).strip( )
                # Just take the first branch
                # FIXME: this is, of course, silly
                git_ref = git_ref.split('\n')[0]
                # Split remote from branch name
                git_ref = git_ref.split( '/' )
                assert len( git_ref ) == 2
                git_ref = git_ref[ 1 ]
        else:
            git_ref = version
    url = 'git+https://github.com/BD2KGenomics'
    dependency_links.append(
        '{url}/{name}.git@{git_ref}#egg={name}-{version}'.format( **locals( ) ) )
    return '{name}=={version}'.format( **locals( ) )


setup(
    name='cgcloud-agent',
    version=cgcloud_version,

    author='Hannes Schmidt',
    author_email='hannes@ucsc.edu',
    url='https://github.com/BD2KGenomics/cgcloud-agent',
    description='Management of ~/.ssh/authorized_keys for a fleet of EC2 instances',

    package_dir={ '': 'src' },
    packages=find_packages( 'src' ),
    entry_points={
        'console_scripts': [
            'cgcloudagent = cgcloud.agent.ui:main' ], },
    install_requires=filter( None, [
        add_private_dependency( 'bd2k-python-lib', '1.5' ),
        add_private_dependency( 'cgcloud-lib' ),
        # The agent is installed in a virtualenv so we can be specific with the versions
        'python-daemon>=2.0.5',
        'boto==2.36.0',
        'argparse==1.2.1' if sys.version_info < (2, 7) else None ] ),
    namespace_packages=[ 'cgcloud' ],
    package_data={
        'cgcloud.agent': [ 'init-script.*' ] },
    dependency_links=dependency_links )
