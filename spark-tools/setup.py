from __future__ import absolute_import

from setuptools import setup, find_packages

from version import cgcloud_version, bd2k_python_lib_version

setup(
    name="cgcloud-spark-tools",
    version=cgcloud_version,

    author='Hannes Schmidt',
    author_email='hannes@ucsc.edu',
    url='https://github.com/BD2KGenomics/cgcloud',
    description='Setup and manage a Apache Spark cluster in EC2',

    package_dir={ '': 'src' },
    packages=find_packages( 'src' ),
    namespace_packages=[ 'cgcloud' ],
    install_requires=[
        'bd2k-python-lib==' + bd2k_python_lib_version,
        'cgcloud-lib==' + cgcloud_version,
        'boto>=2.36.0' ] )
