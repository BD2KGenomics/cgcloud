from setuptools import setup, find_packages

setup(
    name="cgcloud-lib",
    version="1.0.dev1",
    package_dir={ '': 'src' },
    packages=find_packages( 'src' ),
    install_requires=[
        'boto>=2.36.0'
    ],
    extras_require={
        'PyCrypto': [ 'PyCrypto>=2.3' ] # otherwise the bundled cgcloud_Crypto will be used
    },
    namespace_packages=[ 'cgcloud' ]
)
