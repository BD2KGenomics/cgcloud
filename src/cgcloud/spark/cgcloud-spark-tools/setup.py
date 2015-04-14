from setuptools import setup, find_packages

dependency_base_url = 'git+https://github.com/BD2KGenomics/'

setup(
    name="cgcloud-spark-tools",
    version="1.0.dev1",
    packages=find_packages( ),
    install_requires=[
        'boto>=2.9.7',
        'bd2k-python-lib>=1.5.dev1'
    ],
    namespace_packages=[ 'cgcloud' ],
    dependency_links=[
        dependency_base_url + 'bd2k-python-lib.git@master#egg=bd2k-python-lib-1.5.dev1'
    ]
)