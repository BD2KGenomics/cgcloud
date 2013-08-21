import contextlib
import csv
import urllib2
from fabric.operations import sudo, run
from box import fabric_task
from cghub.cloud.unix_box import UnixBox

BASE_URL = 'http://cloud-images.ubuntu.com'


class TemplateDict( dict ):
    def matches(self, other):
        return all( v == other.get( k ) for k, v in self.iteritems( ) )


class UbuntuBox( UnixBox ):
    """
    A box representing EC2 instances that boot from one of Ubuntu's cloud-image AMIs
    """

    def release(self):
        """
        :return: the code name of the Ubuntu release, e.g. "precise"
        """
        raise NotImplementedError()

    def __init__(self, env):
        super( UbuntuBox, self ).__init__( env )
        release = self.release()
        self._log( "Looking up AMI for Ubuntu release %s ..." % release, newline=False )
        self.base_image = self.__find_image(
            template=TemplateDict( release=release,
                                   purpose='server',
                                   release_type='release',
                                   storage_type='ebs',
                                   arch='amd64',
                                   region=env.region,
                                   hypervisor='paravirtual' ),
            url='%s/query/%s/server/released.current.txt' % ( BASE_URL, release ),
            fields=[
                'release', 'purpose', 'release_type', 'release_date',
                'storage_type', 'arch', 'region', 'ami_id', 'aki_id',
                'dont_know', 'hypervisor' ] )
        self._log( ", found %s." % self.image_id() )

    @staticmethod
    def __find_image(template, url, fields):
        matches = [ ]
        with contextlib.closing( urllib2.urlopen( url ) ) as stream:
            images = csv.DictReader( stream, fields, delimiter='\t' )
            for image in images:
                if template.matches( image ):
                    matches.append( image )
        if len( matches ) < 1:
            raise RuntimeError( 'No matching images' )
        if len( matches ) > 1:
            raise RuntimeError( 'More than one matching images: %s' % matches )
        match = matches[ 0 ]
        return match

    def username(self):
        return 'ubuntu'

    def image_id(self):
        return self.base_image[ 'ami_id' ]

    def setup(self, upgrade_installed_packages=False):
        self.wait_for_cloud_init_completion()
        super( UbuntuBox, self ).setup( upgrade_installed_packages )

    @fabric_task
    def wait_for_cloud_init_completion(self):
        """
        Wait for Ubuntu's cloud-init to finish its job such as to avoid getting in its way.
        Without this, I've seen weird errors with 'apt-get install' not being able to find any
        packages.
        """
        run( 'echo -n "Waiting for cloud-init to finish ..." ; '
             'while [ ! -e /var/lib/cloud/instance/boot-finished ]; do '
             'echo -n "."; '
             'sleep 1; '
             'done; '
             'echo ", done."' )

    @fabric_task
    def _sync_package_repos(self):
        sudo( 'apt-get -q update' )

    @fabric_task
    def _upgrade_installed_packages(self):
        sudo( 'apt-get -q -y upgrade' )

    @fabric_task
    def _install_packages(self, packages ):
        packages = " ".join( packages )
        sudo( 'apt-get -q -y install ' + packages )
