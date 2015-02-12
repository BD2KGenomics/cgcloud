from setuptools import setup, find_packages

setup(
    name="cgcloud-lib",
    version="1.0.dev1",
    packages=find_packages( ),
    install_requires=[
        'PyCrypto>=2.3',
        'boto>=2.9.7'
    ],
    namespace_packages=[ 'cgcloud' ]
)
