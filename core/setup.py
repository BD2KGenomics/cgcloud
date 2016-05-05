from __future__ import absolute_import

from setuptools import setup, find_packages

from version import cgcloud_version, bd2k_python_lib_dep, boto_dep, fabric_dep

setup( name='cgcloud-core',
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
       install_requires=[ bd2k_python_lib_dep,
                          'cgcloud-lib==' + cgcloud_version,
                          'futures==3.0.4',
                          # such that cgcloud-lib can use the futures backport for its thread_pool
                          boto_dep,
                          fabric_dep,
                          'paramiko==1.16.0',
                          'futures==3.0.4',
                          'PyYAML==3.11',
                          'subprocess32==3.2.7' ],
       test_suite='cgcloud.core.test' )
