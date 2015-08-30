from abc import abstractmethod
import contextlib
import csv
import logging
import urllib2

from fabric.operations import sudo

from box import fabric_task
from cgcloud.core.init_box import UpstartBox, SystemdBox
from cgcloud.core.agent_box import AgentBox
from cgcloud.core.cloud_init_box import CloudInitBox
from cgcloud.core.package_manager_box import PackageManagerBox
from cgcloud.core.rc_local_box import RcLocalBox
from cgcloud.fabric.operations import remote_sudo_popen

BASE_URL = 'http://cloud-images.ubuntu.com'

log = logging.getLogger( __name__ )


class UbuntuBox( AgentBox, PackageManagerBox, CloudInitBox, RcLocalBox ):
    """
    A box representing EC2 instances that boot from one of Ubuntu's cloud-image AMIs
    """

    @abstractmethod
    def release( self ):
        """
        :return: the code name of the Ubuntu release, e.g. "precise"
        """
        raise NotImplementedError( )

    def _get_debconf_selections( self ):
        """
        Override in concrete a subclass to add custom debconf selections.

        :return: A list of lines to be piped to debconf-set-selections (no newline at the end)
        :rtype: list[str]
        """
        return [ ]

    def admin_account( self ):
        return 'ubuntu'

    class TemplateDict( dict ):
        def matches( self, other ):
            return all( v == other.get( k ) for k, v in self.iteritems( ) )

    def _base_image( self, virtualization_type ):
        release = self.release( )
        template = self.TemplateDict( release=release, purpose='server', release_type='release',
                                      storage_type='ebs', arch='amd64', region=self.ctx.region,
                                      hypervisor=virtualization_type )
        url = '%s/query/%s/server/released.current.txt' % (BASE_URL, release)
        matches = [ ]
        with contextlib.closing( urllib2.urlopen( url ) ) as stream:
            images = csv.DictReader( stream,
                                     fieldnames=[
                                         'release', 'purpose', 'release_type', 'release_date',
                                         'storage_type', 'arch', 'region', 'ami_id', 'aki_id',
                                         'dont_know', 'hypervisor' ],
                                     delimiter='\t' )
            for image in images:
                if template.matches( image ):
                    matches.append( image )
        if len( matches ) < 1:
            raise self.NoSuchImageException(
                "Can't find Ubuntu AMI for release %s and virtualization type %s" % (
                    release, virtualization_type) )
        if len( matches ) > 1:
            raise RuntimeError( 'More than one matching image: %s' % matches )
        image_info = matches[ 0 ]
        image_id = image_info[ 'ami_id' ]
        return self.ctx.ec2.get_image( image_id )

    apt_get = 'DEBIAN_FRONTEND=readline apt-get -q -y'

    @fabric_task
    def _sync_package_repos( self ):
        for i in range( 5 ):
            cmd = self.apt_get + ' update'
            result = sudo( cmd, warn_only=True )
            if result.succeeded: return
            # https://bugs.launchpad.net/ubuntu/+source/apt/+bug/972077
            # https://lists.debian.org/debian-dak/2012/05/threads.html#00006
            if 'Hash Sum mismatch' in result:
                log.warn( "Detected race condition during in '%s'" )
            else:
                raise RuntimeError( "Command '%s' failed" % cmd )
        raise RuntimeError( "Command '%s' repeatedly failed with race condition. Giving up." )

    @fabric_task
    def _upgrade_installed_packages( self ):
        sudo( '%s upgrade' % self.apt_get )

    @fabric_task
    def _install_packages( self, packages ):
        packages = " ".join( packages )
        sudo( '%s --no-install-recommends install %s' % (self.apt_get, packages) )

    def _get_package_installation_command( self, package ):
        return [ 'apt-get', 'install', '-y', '--no-install-recommends' ] + list(
            self._substitute_package( package ) )

    def _pre_install_packages( self ):
        super( UbuntuBox, self )._pre_install_packages( )
        debconf_selections = self._get_debconf_selections( )
        if debconf_selections:
            self.__debconf_set_selections( debconf_selections )

    @fabric_task
    def __debconf_set_selections( self, debconf_selections ):
        with remote_sudo_popen( 'debconf-set-selections' ) as f:
            f.write( '\n'.join( debconf_selections ) )

    def _ssh_service_name( self ):
        return 'ssh'


class UpstartUbuntuBox( UbuntuBox, UpstartBox ):
    pass


class SystemdUbuntuBox( UbuntuBox, SystemdBox ):
    pass
