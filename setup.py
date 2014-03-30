from setuptools import setup, find_packages

setup(
    name="cghub-cloud-ci",
    version="1.0.dev1",
    packages=find_packages( ),
    install_requires=[
        'cghub-cloud-lib>=1.0.dev1',
        'cghub-cloud-core>=1.0.dev1',
        'Fabric>=1.7.0',
        'lxml>=3.2.1'
    ],
    tests_require=[
        'subprocess32'
    ],
    namespace_packages=[
        'cghub', 'cghub.cloud'
    ],
    dependency_links=[
        'hg+ssh://hg@bitbucket.org/cghub/cghub-cloud-core@default#egg=cghub-cloud-core-1.0.dev1'
        'hg+ssh://hg@bitbucket.org/cghub/cghub-cloud-lib@default#egg=cghub-cloud-lib-1.0.dev1'
    ],
)
