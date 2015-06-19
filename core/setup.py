import os
from subprocess import check_output

from pkg_resources import parse_version
from setuptools import setup, find_packages

cgcloud_version = '1.0.dev8'

setup(
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
            'cgcloud = cgcloud.core.ui:main' ], },
    install_requires=[
        'bd2k-python-lib>=1.6.dev1',
        'cgcloud-lib==' + cgcloud_version,
        'boto>=2.36.0',
        'Fabric>=1.7.0',
        'PyYAML>=3.10' ],
    test_suite='cgcloud.core.test' )
