from setuptools import setup, find_packages

setup(
    name="cghub-cloud-agent",
    version="0.1.dev1",
    packages=find_packages( ),
    scripts=[ 'cgcloudagent' ],
    install_requires=[
        'cghub-cloud-lib>=1.0.dev1',
        'cghub-python-lib>=1.2.dev1',
        'python-daemon>=1.6',
        'boto>=2.9.7'
    ],
    dependency_links=[
        'hg+ssh://hg@bitbucket.org/cghub/cghub-python-lib@default#egg=cghub-python-lib-1.2.dev1',
        'hg+ssh://hg@bitbucket.org/cghub/cghub-cloud-lib@default#egg=cghub-cloud-lib-1.0.dev1'
    ],
    namespace_packages=[
        'cghub', 'cghub.cloud'
    ]
)
