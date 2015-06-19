from setuptools import setup, find_packages

cgcloud_version = '1.0.dev8'

setup(
    name='cgcloud-spark',
    version=cgcloud_version,

    author='Hannes Schmidt',
    author_email='hannes@ucsc.edu',
    url='https://github.com/BD2KGenomics/cgcloud',
    description='Setup and manage a Apache Spark cluster in EC2',

    package_dir={ '': 'src' },
    packages=find_packages( 'src' ),
    namespace_packages=[ 'cgcloud' ],
    install_requires=[
        'Fabric>=1.7.0',
        'lxml>=3.2.1',
        'bd2k-python-lib>=1.6.dev1',
        'cgcloud-lib==' + cgcloud_version,
        'cgcloud-core==' + cgcloud_version ] )
