from __future__ import absolute_import

from setuptools import setup, find_packages

from version import cgcloud_version, bd2k_python_lib_version, boto_version

setup(
    name="cgcloud-mesos-tools",
    version=cgcloud_version,

    author='Christopher Ketchum',
    author_email='cketchum@ucsc.edu',
    url='https://github.com/BD2KGenomics/cgcloud',
    description='Setup and manage an Apache Mesos cluster in EC2',

    package_dir={ '': 'src' },
    packages=find_packages( 'src' ),
    namespace_packages=[ 'cgcloud' ],
    install_requires=[
        'bd2k-python-lib==' + bd2k_python_lib_version,
        'cgcloud-lib==' + cgcloud_version,
        'boto==' + boto_version ] )
