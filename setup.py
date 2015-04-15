import sys

from setuptools import setup, find_packages

dependency_links = [ ]


def add_private_dependency( name, version, git_ref ):
    url = 'git+https://github.com/BD2KGenomics'
    dependency_links.append( '{url}/{name}.git@{git_ref}#egg={name}-{version}'.format( locals( ) ) )
    return "{name}={version}".format( locals( ) )


cgcloud_version = "1.0.dev1"

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
        add_private_dependency( 'cgcloud-lib', cgcloud_version, 'master ' ),
        add_private_dependency( 'bd2k-python-lib', '1.5.dev1', 'master' ),
        'python-daemon>=1.6',
        'boto>=2.9.7',
        'argparse>=1.2.1' if sys.version_info < (2, 7) else None ] ),
    namespace_packages=[ 'cgcloud' ],
    package_data={
        'cgcloud.agent': [ 'init-script.lsb', 'init-script.upstart' ] },
    dependency_links=dependency_links )
