import errno
import fcntl
import itertools
import logging
import os
import re
import socket
import stat
import time
from collections import OrderedDict
from grp import getgrnam
from pwd import getpwnam
from subprocess import check_call, check_output, CalledProcessError
from urllib2 import urlopen

import boto.ec2
from bd2k.util import memoize, less_strict_bool
from bd2k.util.files import mkdir_p
from boto.ec2.instance import Instance

from cgcloud.lib.ec2 import EC2VolumeHelper
from cgcloud.lib.util import volume_label_hash

initctl = '/sbin/initctl'

sudo = '/usr/bin/sudo'

log = logging.getLogger( __name__ )


class MesosTools( object ):
    """
    Tools for master discovery and managing the slaves file for Mesos. All of this happens at
    boot time when a node (master or slave) starts up as part of a cluster.

    Master discovery works as follows: All instances in a Mesos cluster are tagged with the
    instance ID of the master. Each instance will look up the private IP of 1) the master
    instance using the EC2 API (via boto) and 2) itself using the instance metadata endpoint. An
    entry for "mesos-master" will be added to /etc/hosts. All configuration files use these names
    instead of hard-coding the IPs. This is all that's needed to boot a working cluster.

    Optionally, a persistent EBS volume is attached, formmatted (if needed) and mounted.
    """

    def __init__( self, user, shared_dir, ephemeral_dir, persistent_dir, lazy_dirs ):
        """
        :param user: the user the services run as
        """
        super( MesosTools, self ).__init__( )
        self.user = user
        self.shared_dir = shared_dir
        self.ephemeral_dir = ephemeral_dir
        self.persistent_dir = persistent_dir
        self.uid = getpwnam( self.user ).pw_uid
        self.gid = getgrnam( self.user ).gr_gid
        self.lazy_dirs = lazy_dirs
        self._patch_boto_config( )

    def _patch_boto_config( self ):
        from boto import config
        def inject_default( name, default ):
            section = 'Boto'
            value = config.get( section, name )

            if value != default:
                if not config.has_section( section ):
                    config.add_section( section )
                config.set( section, name, default )

        # Override the 5xx retry limit default of 6
        inject_default( 'num_retries', '12' )

    def start( self ):
        """
        Invoked at boot time or when the mesosbox service is started.
        """
        while not os.path.exists( '/tmp/cloud-init.done' ):
            log.info( "Waiting for cloud-init to finish ..." )
            time.sleep( 1 )
        log.info( "Starting mesosbox" )
        self.__setup_etc_hosts( )
        self.__mount_ebs_volume( )
        self.__create_lazy_dirs( )

        if self.master_ip == self.node_ip:
            node_type = 'master'
            self.__publish_host_key( )
        else:
            node_type = 'slave'
            self.__get_master_host_key( )
            self.__wait_for_master_ssh( )
            if self.shared_dir:
                self._copy_dir_from_master( self.shared_dir )
            self.__prepare_slave_args( )

        log.info( "Starting %s services" % node_type )
        check_call( [ initctl, 'emit', 'mesosbox-start-%s' % node_type ] )

    def stop( self ):
        """
        Invoked at shutdown time or when the mesosbox service is stopped.
        """
        log.info( "Stopping mesosbox" )
        self.__patch_etc_hosts( { 'mesos-master': None } )

    @classmethod
    @memoize
    def instance_data( cls, path ):
        return urlopen( 'http://169.254.169.254/latest/' + path ).read( )

    @classmethod
    @memoize
    def meta_data( cls, path ):
        return cls.instance_data( 'meta-data/' + path )

    @classmethod
    @memoize
    def user_data( cls ):
        user_data = cls.instance_data( 'user-data' )
        log.info( "User data is '%s'", user_data )
        return user_data

    @property
    @memoize
    def node_ip( self ):
        ip = self.meta_data( 'local-ipv4' )
        log.info( "Local IP is '%s'", ip )
        return ip

    @property
    @memoize
    def instance_id( self ):
        instance_id = self.meta_data( 'instance-id' )
        log.info( "Instance ID is '%s'", instance_id )
        return instance_id

    @property
    @memoize
    def availability_zone( self ):
        zone = self.meta_data( 'placement/availability-zone' )
        log.info( "Availability zone is '%s'", zone )
        return zone

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
    def ec2( self ):
        return boto.ec2.connect_to_region( self.region )

    @property
    @memoize
    def master_id( self ):
        master_id = self.instance_tag( 'leader_instance_id' )
        if not master_id:
            raise RuntimeError( "Instance not tagged with master's instance ID" )
        log.info( "Master's instance ID is '%s'", master_id )
        return master_id

    @property
    @memoize
    def master_ip( self ):
        if self.master_id == self.instance_id:
            master_ip = self.node_ip
            log.info( "I am the master" )
        else:
            log.info( "I am a slave" )
            master_ip = self.master_instance.private_ip_address
        log.info( "Master IP is '%s'", master_ip )
        return master_ip

    @property
    @memoize
    def is_spot_instance( self ):
        result = bool( self.this_instance.spot_instance_request_id )
        log.info( "I am %s spot instance", "a" if result else "not a" )
        return result

    @memoize
    def instance( self, instance_id ):
        """:rtype: Instance"""
        instances = self.ec2.get_only_instances( instance_ids=[ instance_id ] )
        assert len( instances ) == 1
        instance = instances[ 0 ]
        return instance

    @property
    @memoize
    def this_instance( self ):
        """:rtype: Instance"""
        instance = self.instance( self.instance_id )
        log.info( "I am running on %r", instance.__dict__ )
        return instance

    @property
    @memoize
    def master_instance( self ):
        """:rtype: Instance"""
        return self.instance( self.master_id )

    @memoize
    def instance_tag( self, key ):
        """:rtype: str|None"""
        return self.this_instance.tags.get( key )

    def __mount_ebs_volume( self ):
        """
        Attach, format (if necessary) and mount the EBS volume with the same cluster ordinal as
        this node.
        """
        ebs_volume_size = self.instance_tag( 'ebs_volume_size' ) or '0'
        ebs_volume_size = int( ebs_volume_size )
        if ebs_volume_size:
            instance_name = self.instance_tag( 'Name' )
            cluster_ordinal = int( self.instance_tag( 'cluster_ordinal' ) )
            volume_name = '%s__%d' % (instance_name, cluster_ordinal)
            volume = EC2VolumeHelper( ec2=self.ec2,
                                      availability_zone=self.availability_zone,
                                      name=volume_name,
                                      size=ebs_volume_size,
                                      volume_type="gp2" )
            # TODO: handle case where volume is already attached
            device_ext = '/dev/sdf'
            device = '/dev/xvdf'
            volume.attach( self.instance_id, device_ext )

            # Wait for inode to appear and make sure its a block device
            while True:
                try:
                    assert stat.S_ISBLK( os.stat( device ).st_mode )
                    break
                except OSError as e:
                    if e.errno == errno.ENOENT:
                        time.sleep( 1 )
                    else:
                        raise

            # Only format empty volumes
            volume_label = volume_label_hash( volume_name )
            if check_output( [ 'file', '-sL', device ] ).strip( ) == device + ': data':
                check_call( [ 'mkfs', '-t', 'ext4', device ] )
                check_call( [ 'e2label', device, volume_label ] )
            else:
                # If the volume is not empty, verify the file system label
                actual_label = check_output( [ 'e2label', device ] ).strip( )
                if actual_label != volume_label:
                    raise AssertionError(
                        "Expected volume label '%s' (derived from '%s') but got '%s'" %
                        (volume_label, volume_name, actual_label) )
            current_mount_point = self.__mount_point( device )
            if current_mount_point is None:
                mkdir_p( self.persistent_dir )
                check_call( [ 'mount', device, self.persistent_dir ] )
            elif current_mount_point == self.persistent_dir:
                pass
            else:
                raise RuntimeError(
                    "Can't mount device %s on '%s' since it is already mounted on '%s'" % (
                        device, self.persistent_dir, current_mount_point) )
        else:
            # No persistent volume is attached and the root volume is off limits, so we will need
            # to place persistent data on the ephemeral volume.
            self.persistent_dir = self.ephemeral_dir

    def __get_master_host_key( self ):
        log.info( "Getting master's host key" )
        master_host_key = self.master_instance.tags.get( 'ssh_host_key' )
        if master_host_key:
            self.__add_host_keys( [ 'mesos-master:' + master_host_key ] )
        else:
            log.warn( "Could not get master's host key" )

    def __add_host_keys( self, host_keys, globally=None ):
        if globally is None:
            globally = os.geteuid( ) == 0
        if globally:
            known_hosts_path = '/etc/ssh/ssh_known_hosts'
        else:
            known_hosts_path = os.path.expanduser( '~/.ssh/known_hosts' )
        with open( known_hosts_path, 'a+' ) as f:
            fcntl.flock( f, fcntl.LOCK_EX )
            keys = set( _.strip( ) for _ in f.readlines( ) )
            keys.update( ' '.join( _.split( ':' ) ) for _ in host_keys )
            if '' in keys: keys.remove( '' )
            keys = list( keys )
            keys.sort( )
            keys.append( '' )
            f.seek( 0 )
            f.truncate( 0 )
            f.write( '\n'.join( keys ) )

    def __wait_for_master_ssh( self ):
        """
        Wait until the instance represented by this box is accessible via SSH.
        """
        for _ in itertools.count( ):
            s = socket.socket( socket.AF_INET, socket.SOCK_STREAM )
            try:
                s.settimeout( 5 )
                s.connect( ('mesos-master', 22) )
                return
            except socket.error:
                pass
            finally:
                s.close( )

    def _copy_dir_from_master( self, path ):
        log.info( "Copying %s from master" % path )
        if not path.endswith( '/' ):
            path += '/'
        for tries in range( 5 ):
            try:
                check_call( [ sudo, '-u', self.user,
                                'rsync', '-av', 'mesos-master:' + path, path ] )
            except CalledProcessError as e:
                log.warn( "rsync returned %i, retrying in 5s", e.returncode )
                time.sleep( 5 )
            else:
                return
        raise RuntimeError( "Failed to copy %s from master" )

    def __get_host_key( self ):
        with open( '/etc/ssh/ssh_host_ecdsa_key.pub' ) as f:
            return ':'.join( f.read( ).split( )[ :2 ] )

    def __publish_host_key( self ):
        master_host_key = self.__get_host_key( )
        self.ec2.create_tags( [ self.master_id ], dict( ssh_host_key=master_host_key ) )

    def __create_lazy_dirs( self ):
        log.info( "Bind-mounting directory structure" )
        for (parent, name, persistent) in self.lazy_dirs:
            assert parent[ 0 ] == os.path.sep
            logical_path = os.path.join( parent, name )
            if persistent is None:
                tag = 'persist' + logical_path.replace( os.path.sep, '_' )
                persistent = less_strict_bool( self.instance_tag( tag ) )
            location = self.persistent_dir if persistent else self.ephemeral_dir
            physical_path = os.path.join( location, parent[ 1: ], name )
            mkdir_p( physical_path )
            os.chown( physical_path, self.uid, self.gid )
            check_call( [ 'mount', '--bind', physical_path, logical_path ] )

    def __setup_etc_hosts( self ):
        hosts = self.instance_tag( 'etc_hosts_entries' ) or ""
        hosts = parse_etc_hosts_entries( hosts )
        hosts[ 'mesos-master' ] = self.master_ip
        self.__patch_etc_hosts( hosts )

    def __patch_etc_hosts( self, hosts ):
        log.info( "Patching /etc/host" )
        # FIXME: The handling of /etc/hosts isn't atomic
        with open( '/etc/hosts', 'r+' ) as etc_hosts:
            lines = [ line
                for line in etc_hosts.readlines( )
                if not any( host in line for host in hosts.iterkeys( ) ) ]
            for host, ip in hosts.iteritems( ):
                if ip: lines.append( "%s %s\n" % (ip, host) )
            etc_hosts.seek( 0 )
            etc_hosts.truncate( 0 )
            etc_hosts.writelines( lines )

    def __mount_point( self, device ):
        with open( '/proc/mounts' ) as f:
            for line in f:
                line = line.split( )
                if line[ 0 ] == device:
                    return line[ 1 ]
        return None

    def __prepare_slave_args( self ):
        attributes = dict( preemptable=self.is_spot_instance )
        with open( '/var/lib/mesos/slave_args', 'w' ) as f:
            if attributes:
                attributes = ';'.join( '%s:%r' % i for i in attributes.items( ) )
                f.write( "--attributes='%s'" % attributes )

def parse_etc_hosts_entries( hosts ):
    """
    >>> parse_etc_hosts_entries("").items()
    []
    >>> parse_etc_hosts_entries("foo:1.2.3.4").items()
    [('foo', '1.2.3.4')]
    >>> parse_etc_hosts_entries(" foo : 1.2.3.4 , bar : 2.3.4.5 ").items()
    [('foo', '1.2.3.4'), ('bar', '2.3.4.5')]
    """
    return OrderedDict( (ip.strip( ), name.strip( ))
        for ip, name in (entry.split( ':', 1 )
        for entry in hosts.split( ',' ) if entry) )
