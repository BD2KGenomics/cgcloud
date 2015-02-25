from setuptools import setup, find_packages

setup(
    name="cgcloud-lib",
    version="1.0.dev1",
    packages=find_packages( ),
    install_requires=[
        'boto>=2.9.7'
    ],
    extras_require={
        'PyCrypto': [ 'PyCrypto>=2.3' ] # otherwise the bundled cgcloud_Crypto will be used
    },
    namespace_packages=[ 'cgcloud' ]
)
