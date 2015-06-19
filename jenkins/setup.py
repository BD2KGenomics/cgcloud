import os
from subprocess import check_output

from pkg_resources import parse_version
from setuptools import setup, find_packages

cgcloud_version = '1.0.dev8'

setup(
    name='cgcloud-jenkins',
    version=cgcloud_version,

    author="Hannes Schmidt",
    author_email="hannes@ucsc.edu",
    url='https://github.com/BD2KGenomics/cgcloud',
    description='Setup and manage a Jenkins continuous integration cluster in EC2',

    package_dir={ '': 'src' },
    packages=find_packages( 'src' ),
    namespace_packages=[ 'cgcloud' ],
    install_requires=[
        'cgcloud-lib==' + cgcloud_version,
        'cgcloud-core=='  + cgcloud_version,
        'Fabric>=1.7.0',
        'lxml>=3.2.1' ] )
