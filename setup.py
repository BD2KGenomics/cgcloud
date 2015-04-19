from setuptools import setup, find_packages

cgcloud_version = '1.0.dev1'

setup(
    name='cgcloud-lib',
    version=cgcloud_version,

    author='Hannes Schmidt',
    author_email='hannes@ucsc.edu',
    url='https://github.com/BD2KGenomics/cgcloud-lib',
    description='Components shared between cgcloud-core and cgcloud-agent',

    package_dir={ '': 'src' },
    packages=find_packages( 'src' ),
    install_requires=[
        'boto>=2.36.0'
    ],
    extras_require={
        'PyCrypto': [ 'PyCrypto>=2.3' ]  # otherwise the bundled cgcloud_Crypto will be used
    },
    setup_requires=[
        'nose>=1.3.4' ],
    namespace_packages=[ 'cgcloud' ] )
