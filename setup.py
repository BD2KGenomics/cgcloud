from setuptools import setup, find_packages

setup(
    name="cghub-cloud-utils",
    version="0.1",
    packages=find_packages( ),
    scripts=[ 'cgcloud' ],
    install_requires=[ 'boto', 'Fabric', 'PyYAML'],
)
