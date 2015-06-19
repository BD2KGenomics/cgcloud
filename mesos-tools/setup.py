from setuptools import setup, find_packages

cgcloud_version = '1.0.dev8'

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
        'bd2k-python-lib>=1.6.dev1',
        'cgcloud-lib==' + cgcloud_version,
        'boto>=2.36.0' ] )
