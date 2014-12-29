from setuptools import setup, find_packages

setup(
    name="cghub-cloud-core",
    version="1.0.dev1",
    packages=find_packages( ),
    scripts=[ 'cgcloud' ],
    install_requires=[
        'cghub-python-lib>=1.4.dev1',
        'cghub-cloud-lib>=1.0.dev1',
        'boto>=2.16.0',
        'Fabric>=1.7.0',
        'PyYAML>=3.10',
        'PyCrypto>=2.6' ],
    namespace_packages=[
        'cghub', 'cghub.cloud'
    ],
    dependency_links=[
        'git+ssh://git@bitbucket.org/cghub/cghub-python-lib@master#egg=cghub-python-lib-1.5.dev1',
        'git+ssh://git@bitbucket.org/cghub/cghub-cloud-lib@master#egg=cghub-cloud-lib-1.0.dev1'
    ],
)
