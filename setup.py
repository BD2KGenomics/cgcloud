from setuptools import setup, find_packages

setup(
    name="cghub-cloud-utils",
    version="0.1",
    packages=find_packages( ),
    scripts=[ 'cgcloud' ],
    install_requires=[
        'boto>=2.9.7',
        'Fabric>=1.7.0',
        'PyYAML>=3.10',
        'PyCrypto>=2.6',
        'lxml>=3.2.1' ],
    namespace_packages=[
        'cghub', 'cghub.cloud'
    ]
)
