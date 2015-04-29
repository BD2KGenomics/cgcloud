import os
from subprocess import check_output
import sys

from pkg_resources import parse_version
from setuptools import setup, find_packages

dependency_links = [ ]

cgcloud_version = '1.0.dev1'


def add_private_dependency( name, version=cgcloud_version, git_ref=None ):
    if git_ref is None:
        if parse_version( version ).is_prerelease:
            git_ref = check_output( [ 'git', 'rev-parse', '--abbrev-ref', 'HEAD' ],
                                    cwd=os.path.dirname( __file__ ) ).strip( )
            # pip checks out individual commits which creates a detached HEAD, so we look at
            # remote branches containing the
            if git_ref == 'HEAD':
                git_ref = check_output( [ 'git', 'branch', '-r', '--contains', 'HEAD' ],
                                        cwd=os.path.dirname( __file__ ) ).strip( )
                assert '\n' not in git_ref
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
        'python-daemon>=1.6',
        'boto>=2.9.7',
        'argparse>=1.2.1' if sys.version_info < (2, 7) else None ] ),
    namespace_packages=[ 'cgcloud' ],
    package_data={
        'cgcloud.agent': [ 'init-script.*' ] },
    dependency_links=dependency_links )
