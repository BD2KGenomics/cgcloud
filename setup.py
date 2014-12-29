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
        'git+ssh://git@bitbucket.org/cghub/cghub-cloud-core@master#egg=cghub-cloud-core-1.0.dev1'
        'git+ssh://git@bitbucket.org/cghub/cghub-cloud-lib@master#egg=cghub-cloud-lib-1.0.dev1'
    ],
)
