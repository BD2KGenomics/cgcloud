import sys

from setuptools import setup as _setup, find_packages

dependency_base_url = 'git+https://github.com/BD2KGenomics/'


def setup( *args, **kwargs ):
    if 'install_requires' in kwargs:
        kwargs[ 'install_requires' ] = filter( None, kwargs[ 'install_requires' ] )
    _setup( *args, **kwargs )


setup(
    name="cgcloud-agent",
    version="1.0.dev1",
    package_dir={ '': 'src' },
    packages=find_packages( 'src' ),
    entry_points={
        'console_scripts': [
            'cgcloudagent = cgcloud.agent.ui:main' ], },
    install_requires=[
        'cgcloud-lib>=1.0.dev1',
        'bd2k-python-lib>=1.5.dev1',
        'python-daemon>=1.6',
        'boto>=2.9.7',
        'argparse>=1.2.1' if sys.version_info < (2, 7) else None ],
    namespace_packages=[ 'cgcloud' ],
    package_data={
        'cgcloud.agent': [ 'init-script.lsb', 'init-script.upstart' ] },
    dependency_links=[
        dependency_base_url + 'bd2k-python-lib.git@master#egg=bd2k-python-lib-1.5.dev1',
        dependency_base_url + 'cgcloud-lib.git@master#egg=cgcloud-lib-1.0.dev1' ] )
