from setuptools import setup, find_packages

setup(
    name="cghub-cloud-utils",
    version="1.0.dev1",
    packages=find_packages( ),
    scripts=[ 'cgcloud' ],
    install_requires=[
        'cghub-python-lib>=1.4.dev1',
        'cghub-cloud-lib>=1.0.dev1',
        'boto>=2.16.0',
        'Fabric>=1.7.0',
        'PyYAML>=3.10',
        'PyCrypto>=2.6',
        'lxml>=3.2.1' ],
    tests_require=[
        'subprocess32'
    ],
    namespace_packages=[
        'cghub', 'cghub.cloud'
    ],
    dependency_links=[
        'hg+ssh://hg@bitbucket.org/cghub/cghub-python-lib@default#egg=cghub-python-lib-1.4.dev1',
        'hg+ssh://hg@bitbucket.org/cghub/cghub-cloud-lib@default#egg=cghub-cloud-lib-1.0.dev1'
    ],
)
