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
from cgcloud.lib.util import volume_label_hash
from bd2k.util.files import mkdir_p
import boto.ec2
from bd2k.util import memoize

from cgcloud.lib.ec2 import EC2VolumeHelper

initctl = '/sbin/initctl'

sudo = '/usr/bin/sudo'

log = logging.getLogger( __name__ )

shared_dir='/home/mesosbox/shared/'


class MesosTools( object ):
    def __init__( self, user, ephemeral_dir, persistent_dir, lazy_dirs):
        super( MesosTools, self ).__init__( )
        self.user=user
        self.uid = getpwnam( self.user ).pw_uid
        self.gid = getgrnam( self.user ).gr_gid
        self.ephemeral_dir = ephemeral_dir
        self.persistent_dir = persistent_dir
        self.lazy_dirs = lazy_dirs

    def start(self):
        while not os.path.exists( '/tmp/cloud-init.done' ):
            log.info( "Waiting for cloud-init to finish ..." )
            time.sleep( 1 )

        self.__patch_etc_hosts( { 'mesos-master': self.master_ip } )
        self.__mount_ebs_volume( )
        self.__create_lazy_dirs( )

        if self.master_ip == self.node_ip:
            node_type = 'master'
        else:
            node_type = 'slave'

        self._copy_dir_from_master(shared_dir)

        log_path='/var/log/mesosbox/mesos{}'.format(node_type)
        mkdir_p(log_path)
        os.chown( log_path, self.uid, self.gid )
        os.chown( "/mesos/workspace", self.uid, self.gid)

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

    def _copy_dir_from_master(self, dir):
        if dir:
            mkdir_p(dir)
            while True:
                try:
                    check_call( ['sudo','-u','mesosbox','rsync','-r','-e', 'ssh -o StrictHostKeyChecking=no', "mesos-master:"+dir, dir] )
                except:
                    log.warning("Failed to rsync specified directory, trying again in 10 sec")
                    time.sleep(10)
                else:
                    break
            os.chown( dir, self.uid, self.gid )

    def __create_lazy_dirs( self ):
        log.info( "Bind-mounting directory structure" )
        for (parent, name, persistent) in self.lazy_dirs:
            assert parent[ 0 ] == os.path.sep
            location = self.persistent_dir if persistent else self.ephemeral_dir
            physical_path = os.path.join( location, parent[ 1: ], name )
            mkdir_p( physical_path )
            os.chown( physical_path, self.uid, self.gid )
            logical_path = os.path.join( parent, name )
            check_call( [ 'mount', '--bind', physical_path, logical_path ] )

    def __mount_ebs_volume( self ):
        """
        Attach, format (if necessary) and mount the EBS volume with the same cluster ordinal as
        this node.
        """
        ebs_volume_size = self.__get_instance_tag( self.instance_id, 'ebs_volume_size' ) or '0'
        ebs_volume_size = int( ebs_volume_size )
        if ebs_volume_size:
            instance_name = self.__get_instance_tag( self.instance_id, 'Name' )
            cluster_ordinal = int( self.__get_instance_tag( self.instance_id, 'cluster_ordinal' ) )
            volume_name = '%s__%d' % ( instance_name, cluster_ordinal )
            volume = EC2VolumeHelper( ec2=self.ec2,
                                      availability_zone=self.availability_zone,
                                      name=volume_name,
                                      size=ebs_volume_size )
            # TODO: handle case where volume is already attached
            volume.attach( self.instance_id, '/dev/sdf' )

            # Only format empty volumes
            volume_label = volume_label_hash( volume_name )
            while True:
                try:
                    if check_output( [ 'file', '-sL', '/dev/xvdf' ] ).strip( ) == '/dev/xvdf: data':
                        check_call( [ 'mkfs', '-t', 'ext4', '/dev/xvdf' ] )
                        check_call( [ 'e2label', '/dev/xvdf', volume_label ] )
                except:
                    time.sleep(1)
                else:
                    break
            if check_output( [ 'file', '-sL', '/dev/xvdf' ] ).strip( ) != '/dev/xvdf: data':
                # if the volume is not empty, verify the file system label
                actual_label = check_output( [ 'e2label', '/dev/xvdf' ] ).strip( )
                if actual_label != volume_label:
                    raise AssertionError(
                        "Expected volume label '%s' (derived from '%s') but got '%s'" %
                        ( volume_label, volume_name, actual_label ) )
            current_mount_point = self.__mount_point( '/dev/xvdf' )
            if current_mount_point is None:
                mkdir_p(self.persistent_dir)
                check_call( [ 'mount', '/dev/xvdf', self.persistent_dir ] ) #this is failing cuz it aint exist. create & go? yep!
            elif current_mount_point == self.persistent_dir:
                pass
            else:
                raise RuntimeError(
                    "Can't mount device /dev/xvdf on '%s' since it is already mounted on '%s'" % (
                        self.persistent_dir, current_mount_point) )
        else:
            # No persistent volume is attached and the root volume is off limits, so we will need
            # to place persistent data on the ephemeral volume.
            self.persistent_dir = self.ephemeral_dir

    def __mount_point( self, device ):
        with open( '/proc/mounts' ) as f:
            for line in f:
                line = line.split( )
                if line[ 0 ] == device:
                    return line[ 1 ]
        return None

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