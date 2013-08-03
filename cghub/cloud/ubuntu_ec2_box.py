import contextlib
import csv
import urllib2
from fabric.operations import sudo
from ec2_box import Ec2Box

BASE_URL = 'http://cloud-images.ubuntu.com'


class TemplateDict( dict ):
    def matches(self, other):
        return all( v == other.get( k ) for k, v in self.iteritems( ) )


class UbuntuEc2Box( Ec2Box ):
    """
    An EC2 instance that boots from one of Ubuntu's cloud-image AMIs
    """

    def __init__(self, release, ec2_options):
        super( UbuntuEc2Box, self ).__init__( ec2_options )
        self.base_image = self.__find_image(
            template=TemplateDict( release=release,
                                   purpose='server',
                                   release_type='release',
                                   storage_type='ebs',
                                   arch='amd64',
                                   region=ec2_options.region,
                                   hypervisor='paravirtual' ),
            url='%s/query/%s/server/released.current.txt' % ( BASE_URL, release ),
            fields=[
                'release', 'purpose', 'release_type', 'release_date',
                'storage_type', 'arch', 'region', 'ami_id', 'aki_id', 'dont_know', 'hypervisor' ] )

    def username(self):
        return 'ubuntu'

    def image_id(self):
        return self.base_image[ 'ami_id' ]

    def setup(self, update=False):
        self.create( )
        if update:
            self.execute( self.update_upgrade )
            self.reboot( )

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

    def update_upgrade(self):
        """
        Bring package repository index up-to-date, install upgrades for installed packages.
        """
        sudo( 'apt-get update' )
        sudo( 'apt-get upgrade -y' )
