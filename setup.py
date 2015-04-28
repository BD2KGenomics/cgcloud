import os
from subprocess import check_output

from pkg_resources import parse_version
from setuptools import setup, find_packages

dependency_links = [ ]

cgcloud_version = '1.0.dev1'


def add_private_dependency( name, version=cgcloud_version, git_ref=None ):
    if git_ref is None:
        if parse_version( version ).is_prerelease:
            git_ref = check_output( [ 'git', 'rev-parse', '--abbrev-ref', 'HEAD' ],
                                    cwd=os.path.dirname( __file__ ) )
        else:
            git_ref = version
    url = 'git+https://github.com/BD2KGenomics'
    dependency_links.append(
        '{url}/{name}.git@{git_ref}#egg={name}-{version}'.format( **locals( ) ) )
    return '{name}=={version}'.format( **locals( ) )


setup(
    name="cgcloud-sparkbox-tools",
    version=cgcloud_version,

    author='Hannes Schmidt',
    author_email='hannes@ucsc.edu',
    url='https://github.com/BD2KGenomics/cgcloud-spark',
    description='Setup and manage a Apache Spark cluster in EC2',

    packages=find_packages( ),
    install_requires=[
        add_private_dependency( 'bd2k-python-lib', '1.6.dev1' ),
        'boto>=2.9.7'
    ],
    namespace_packages=[ 'cgcloud' ],
    dependency_links=dependency_links,
)
