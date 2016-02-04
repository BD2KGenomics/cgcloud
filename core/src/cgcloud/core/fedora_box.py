from abc import abstractmethod
import re
from operator import attrgetter

from fabric.operations import sudo

from cgcloud.core.box import fabric_task
from cgcloud.core.agent_box import AgentBox
from cgcloud.core.cloud_init_box import CloudInitBox
from cgcloud.core.rc_local_box import RcLocalBox
from cgcloud.core.yum_box import YumBox


class FedoraBox( YumBox, AgentBox, CloudInitBox, RcLocalBox ):
    """
    A box that boots of an official Fedora cloud AMI
    """

    @abstractmethod
    def release( self ):
        """
        :return: the version number of the Fedora release, e.g. 17
        :rtype: int
        """
        raise NotImplementedError

    def admin_account( self ):
        return "fedora" if self.release( ) >= 19 else "ec2-user"

    def _base_image( self, virtualization_type ):
        release = self.release( )
        name = None
        if release < 21:
            name = 'Fedora-x86_64-%i-*' % release
        elif release == 21:
            name = 'Fedora-Cloud-Base-*-21.x86_64-*'
        else:
            name = 'Fedora-Cloud-Base-%s-*.x86_64-*' % release
        images = self.ctx.ec2.get_all_images(
            owners=[ '125523088429' ],
            filters={
                'name': name,
                'root-device-type': 'ebs',
                'virtualization-type': virtualization_type } )
        images = [ i for i in images if not re.search( 'Alpha|Beta', i.name ) ]
        if not images:
            raise self.NoSuchImageException(
                "Can't find any AMIs for Fedora %i and virtualization type %s" % (
                    release, virtualization_type ) )
        images.sort( key=attrgetter( 'name' ), reverse=True )
        if False:
            if len( images ) > 1:
                raise RuntimeError(
                    "Found more than one AMI for Fedora %i and virtualization type %s" % (
                    release, virtualization_type ) )
        return images[0]

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

    @fabric_task
    def _get_rc_local_path( self ):
        rc_local_path = '/etc/rc.d/rc.local'
        sudo( 'test -f {f} || echo "#!/bin/sh" > {f} && chmod +x {f}'.format( f=rc_local_path ) )
        return rc_local_path
