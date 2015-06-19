import os
from pkg_resources import parse_version
from setuptools import setup, find_packages

cgcloud_version = '1.0.dev8'

setup(
    name='cgcloud-lib',
    version=cgcloud_version,

    author='Hannes Schmidt',
    author_email='hannes@ucsc.edu',
    url='https://github.com/BD2KGenomics/cgcloud',
    description='Components shared between cgcloud-core and cgcloud-agent',

    package_dir={ '': 'src' },
    packages=find_packages( 'src' ),
    namespace_packages=[ 'cgcloud' ],
    install_requires=[
        'bd2k-python-lib>=1.6.dev1',
        'boto>=2.36.0' ] )
