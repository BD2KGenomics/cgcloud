from __future__ import absolute_import

from setuptools import find_packages

from _setup import _setup
from version import cgcloud_version, bd2k_python_lib_version, boto_version, fabric_version

_setup(
    name='cgcloud-core',
    version=cgcloud_version,

    author='Hannes Schmidt',
    author_email='hannes@ucsc.edu',
    url='https://github.com/BD2KGenomics/cgcloud',
    description='Efficient and reproducible software deployment for EC2 instances',

    package_dir={ '': 'src' },
    packages=find_packages( 'src', exclude=[ '*.test' ] ),
    namespace_packages=[ 'cgcloud' ],
    entry_points={
        'console_scripts': [
            'cgcloud = cgcloud.core.cli:main' ], },
    install_requires=[
        'bd2k-python-lib==' + bd2k_python_lib_version,
        'cgcloud-lib==' + cgcloud_version,
        'boto==' + boto_version,
        'Fabric==' + fabric_version,
        'PyYAML==3.11' ],
    tests_require=[
        'pytest-xdist==1.13.1',
        'pytest-timeout==0.5',
        # https://github.com/pytest-dev/pytest/issues/707
        'execnet==1.4.1'
    ] )
