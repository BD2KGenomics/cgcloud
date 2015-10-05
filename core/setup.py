from __future__ import absolute_import

from setuptools import setup, find_packages

from version import cgcloud_version

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
            'cgcloud = cgcloud.core.cli:main' ], },
    install_requires=[
        'bd2k-python-lib==1.8.dev2',
        'cgcloud-lib==' + cgcloud_version,
        'boto>=2.36.0',
        'Fabric>=1.7.0',
        'PyYAML>=3.10' ],
    test_suite='cgcloud.core.test' )
