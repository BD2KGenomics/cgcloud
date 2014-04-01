import re
from operator import attrgetter

from cghub.cloud.core.agent_box import AgentBox
from cghub.cloud.core.cloud_init_box import CloudInitBox
from cghub.cloud.core.yum_box import YumBox


class FedoraBox( YumBox, AgentBox, CloudInitBox ):
    """
    A box that boots of an official Fedora cloud AMI
    """

    def release( self ):
        """
        :return: the version number of the Fedora release, e.g. 17
        :rtype: int
        """
        raise NotImplementedError

    def username( self ):
        return "fedora" if self.release( ) >= 19 else "ec2-user"

    def _base_image( self ):
        release = self.release( )
        images = self.ctx.ec2.get_all_images( owners=[ '125523088429' ],
                                              filters={
                                                  'name': 'Fedora-x86_64-%i-*' % release,
                                                  'root-device-type': 'ebs' } )
        images = [ i for i in images if not re.search( 'Alpha|Beta', i.name ) ]
        if not images:
            raise RuntimeError( "Can't find any suitable AMIs for Fedora %i" % release )
        images.sort( key=attrgetter( 'name' ), reverse=True )
        if False:
            if len( images ) > 1:
                raise RuntimeError( "Found more than one AMI for Fedora %i" % release )

        return images[ 0 ]

    def _list_packages_to_install( self ):
        return super( FedoraBox, self )._list_packages_to_install( ) + [
            'redhat-lsb' # gets us lsb_release
        ]

    def _get_package_substitutions( self ):
        return super( FedoraBox, self )._get_package_substitutions( ) + [
            # Without openssl-devel, the httplib module disables HTTPS support. The underlying
            # 'import _ssl' fails with ImportError: /usr/lib64/python2.7/lib-dynload/_ssl.so:
            # symbol SSLeay_version, version OPENSSL_1.0.1 not defined in file libcrypto.so.10
            # with link time reference. This packet substitution ensures that if Python is to be installed, openssl-devel is too.
            ( 'python', ( 'python', 'openssl-devel' ) )
        ]
