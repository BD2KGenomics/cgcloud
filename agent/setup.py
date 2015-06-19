import sys

from setuptools import setup, find_packages

cgcloud_version = '1.0.dev8'

setup(
    name='cgcloud-agent',
    version=cgcloud_version,

    author='Hannes Schmidt',
    author_email='hannes@ucsc.edu',
    url='https://github.com/BD2KGenomics/cgcloud',
    description='Management of ~/.ssh/authorized_keys for a fleet of EC2 instances',

    package_dir={ '': 'src' },
    packages=find_packages( 'src' ),
    namespace_packages=[ 'cgcloud' ],
    package_data={
        'cgcloud.agent': [ 'init-script.*' ] },
    entry_points={
        'console_scripts': [
            'cgcloudagent = cgcloud.agent.ui:main' ], },
    install_requires=filter( None, [
        'bd2k-python-lib==1.6.dev1',
        'cgcloud-lib==' + cgcloud_version,
        'boto>=2.36.0',
        'python-daemon>=2.0.5',
        'argparse>=1.2.1' if sys.version_info < (2, 7) else None ] ) )
