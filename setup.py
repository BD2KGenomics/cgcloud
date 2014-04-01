import sys

from setuptools import setup as _setup, find_packages


def setup(*args, **kwargs):
    if 'install_requires' in kwargs:
        kwargs[ 'install_requires' ] = filter( None, kwargs[ 'install_requires' ] )
    _setup( *args, **kwargs )


setup(
    name="cghub-cloud-agent",
    version="1.0.dev1",
    packages=find_packages( ),
    scripts=[ 'cgcloudagent' ],
    install_requires=[
        'cghub-cloud-lib>=1.0.dev1',
        'cghub-python-lib>=1.4.dev1',
        'python-daemon>=1.6',
        'boto>=2.9.7',
        'argparse>=1.2.1' if sys.version_info < (2,7) else None
    ],
    dependency_links=[
        'hg+ssh://hg@bitbucket.org/cghub/cghub-python-lib@default#egg=cghub-python-lib-1.5.dev1',
        'hg+ssh://hg@bitbucket.org/cghub/cghub-cloud-lib@default#egg=cghub-cloud-lib-1.0.dev1'
    ],
    namespace_packages=[
        'cghub', 'cghub.cloud'
    ],
    package_data={
        'cghub.cloud.agent': [ 'init-script.lsb', 'init-script.upstart' ]
    },
)
