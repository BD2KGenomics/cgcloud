from setuptools import setup, find_packages

setup(
    name="cgcloud.py-core",
    version="1.0.dev1",
    packages=find_packages( ),
    entry_points={
        'console_scripts': [
            'cgcloud = main:main'
        ],
    },
    install_requires=[
        'bd2k-python-lib>=1.5.dev1',
        'cgcloud-lib>=1.0.dev1',
        'boto>=2.16.0',
        'Fabric>=1.7.0',
        'PyYAML>=3.10',
        'PyCrypto>=2.6' ],
    namespace_packages=[
        'cgcloud'
    ],
    dependency_links=[
        'git+ssh://git@github.com:BD2KGenomics/bd2k-python-lib.git@master#egg=bd2k-python-lib-1.5.dev1',
        'git+ssh://git@github.com:BD2KGenomics/cgcloud-lib.git@master#egg=cgcloud-lib-1.0.dev1'
    ],
)
