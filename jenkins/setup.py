from __future__ import absolute_import

from setuptools import find_packages

from _setup import _setup
from version import cgcloud_version, fabric_version

_setup(
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
        'Fabric==' + fabric_version ] )
