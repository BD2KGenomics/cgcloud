import sys

from setuptools import setup as _setup, find_packages


def setup(*args, **kwargs):
    if 'install_requires' in kwargs:
        kwargs[ 'install_requires' ] = filter( None, kwargs[ 'install_requires' ] )
    _setup( *args, **kwargs )


setup(
    name="cgcloud-agent",
    version="1.0.dev1",
    packages=find_packages( ),
    scripts=[ 'cgcloudagent' ],
    install_requires=[
        'cgcloud-lib>=1.0.dev1',
        'bd2k-python-lib>=1.5.dev1',
        'python-daemon>=1.6',
        'boto>=2.9.7',
        'argparse>=1.2.1' if sys.version_info < (2,7) else None
    ],
    dependency_links=[
        'git+ssh://git@github.com:BD2KGenomics/bd2k-python-lib.git@master#egg=bd2k-python-lib-1.5.dev1',
        'git+ssh://git@github.com:BD2KGenomics/cgcloud-lib.git@master#egg=cgcloud-lib-1.0.dev1'
    ],
    namespace_packages=[
        'cgcloud'
    ],
    package_data={
        'cgcloud.agent': [ 'init-script.lsb', 'init-script.upstart' ]
    },
)
