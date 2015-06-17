import logging
import re
import os
import fcntl
from grp import getgrnam
from pwd import getpwnam
import socket
from urllib2 import urlopen
from subprocess import check_call, call, check_output
import time
import itertools

from bd2k.util.files import mkdir_p
import boto.ec2
from bd2k.util import memoize

from cgcloud.lib.ec2 import EC2VolumeHelper

initctl = '/sbin/initctl'

sudo = '/usr/bin/sudo'

log = logging.getLogger( __name__ )


class MesosTools( object ):

    def __init__( self, user):
        super( MesosTools, self ).__init__( )
        self.user=user
        self.uid = getpwnam( self.user ).pw_uid
        self.gid = getgrnam( self.user ).gr_gid

    def start(self):
        while not os.path.exists( '/tmp/cloud-init.done' ):
            log.info( "Waiting for cloud-init to finish ..." )
            time.sleep( 1 )

        self.__patch_etc_hosts( { 'mesos-master': self.master_ip } )

        if self.master_ip == self.node_ip:
            node_type = 'master'
        else:
            node_type = 'slave'

        log_path='/var/log/mesosbox/mesos{}'.format(node_type)
        mkdir_p(log_path)
        os.chown( log_path, self.uid, self.gid )

        log.info( "Starting %s services" % node_type )
        check_call( [initctl, 'emit', 'mesosbox-start-%s' % node_type ] )

    def stop( self ):
        log.info( "Stopping mesosbox" )
        self.__patch_etc_hosts( { 'mesos-master': None } )

    def __patch_etc_hosts( self, hosts ):
        log.info( "Patching /etc/host" )
        # FIXME: The handling of /etc/hosts isn't atomic
        with open( '/etc/hosts', 'r+' ) as etc_hosts:
            lines = [ line
                for line in etc_hosts.readlines( )
                if not any( host in line for host in hosts.iterkeys( ) ) ]
            for host, ip in hosts.iteritems( ):
                if ip: lines.append( "%s %s\n" % ( ip, host ) )
            etc_hosts.seek( 0 )
            etc_hosts.truncate( 0 )
            etc_hosts.writelines( lines )

    def __get_instance_tag( self, instance_id, key ):
        """
        :rtype: str
        """
        tags = self.ec2.get_all_tags( filters={ 'resource-id': instance_id, 'key': key } )
        return tags[ 0 ].value if tags else None

    @classmethod
    def meta_data( cls, path ):
        return cls.instance_data( 'meta-data/' + path )

    @classmethod
    def instance_data( cls, path ):
        return urlopen( 'http://169.254.169.254/latest/' + path ).read( )

    @property
    @memoize
    def ec2( self ):
        return boto.ec2.connect_to_region( self.region )

    @property
    @memoize
    def master_ip( self ):
        if self.master_id == self.instance_id:
            master_ip = self.node_ip
            log.info( "I am the master" )
        else:
            log.info( "I am a slave" )
            reservations = self.ec2.get_all_reservations( instance_ids=[ self.master_id ] )
            instances = (i for r in reservations for i in r.instances if i.id == self.master_id)
            master_instance = next( instances )
            assert next( instances, None ) is None
            master_ip = master_instance.private_ip_address
        log.info( "Master IP is '%s'", master_ip )
        return master_ip

    @property
    @memoize
    def instance_id( self ):
        instance_id = self.meta_data( 'instance-id' )
        log.info( "Instance ID is '%s'", instance_id )
        return instance_id

    @property
    @memoize
    def node_ip( self ):
        ip = self.meta_data( 'local-ipv4' )
        log.info( "Local IP is '%s'", ip )
        return ip

    @property
    @memoize
    def master_id( self ):
        while True:
            master_id = self.__get_instance_tag( self.instance_id, 'mesos_master' )
            if master_id:
                log.info( "Master's instance ID is '%s'", master_id )
                return master_id
            log.warn( "Instance not tagged with master's instance ID, retrying" )
            time.sleep( 5 )
    @property
    @memoize
    def region( self ):
        m = re.match( r'^([a-z]{2}-[a-z]+-[1-9][0-9]*)([a-z])$', self.availability_zone )
        assert m
        region = m.group( 1 )
        log.info( "Region is '%s'", region )
        return region

    @property
    @memoize
    def availability_zone( self ):
        zone = self.meta_data( 'placement/availability-zone' )
        log.info( "Availability zone is '%s'", zone )
        return zone