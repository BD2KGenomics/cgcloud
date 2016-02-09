import logging
import time
from StringIO import StringIO
from abc import abstractmethod
from functools import partial

import paramiko
import yaml
from fabric.operations import put
from paramiko import Channel

from cgcloud.core.box import Box, fabric_task
from cgcloud.lib.ec2 import ec2_instance_types
from cgcloud.lib.util import heredoc

log = logging.getLogger( __name__ )


class CloudInitBox( Box ):
    """
    A box that uses Canonical's cloud-init to initialize the EC2 instance.
    """

    def _ephemeral_mount_point( self, i ):
        return '/mnt/ephemeral' + ('' if i == 0 else str( i ))

    @abstractmethod
    def _get_package_installation_command( self, package ):
        """
        Return the command that needs to be invoked to install the given package. The returned
        command is an array whose first element is a path or file name of an executable while the
        remaining elements are arguments to that executable.
        """
        raise NotImplementedError( )

    def _get_virtual_block_device_prefix( self ):
        """
        Return the common prefix of paths representing virtual block devices on this box.
        """
        return '/dev/xvd'

    def _populate_cloud_config( self, instance_type, user_data ):
        """
        Populate cloud-init's configuration for injection into a newly created instance

        :param user_data: a dictionary that will be be serialized into YAML and used as the
        instance's user-data
        """
        # see __wait_for_cloud_init_completion()
        runcmd = user_data.setdefault( 'runcmd', [ ] )
        runcmd.append( [ 'touch', '/tmp/cloud-init.done' ] )

        #
        # Lucid's and Oneiric's cloud-init mount ephemeral storage on /mnt instead of
        # /mnt/ephemeral, Fedora doesn't mount it at all. To keep it consistent across
        # releases and platforms we should be explicit.
        #
        # Also note that Lucid's mountall waits on the disk device. On t1.micro instances this
        # doesn't show up causing Lucid to hang on boot on this type. The cleanest way to handle
        # this is to remove the ephemeral entry on t1.micro instances by specififying [
        # 'ephemeral0', None ]. Unfortunately, there is a bug [1] in cloud-init that causes the
        # removal of the entry to be ineffective. The "nobootwait" option might be a workaround
        # but Fedora stopped supporting it such that now only Ubuntu supports it. A better
        # workaround is to always have the ephemeral entry in fstab, even on micro instances,
        # but to exclude the 'auto' option such that when cloud-init runs 'mount -a', it will not
        # get mounted. We can then mount the filesystem explicitly, except on micro instances.
        #
        # The important thing to keep in mind is that when booting instance B from an image
        # created on a instance A, the fstab from A will be used by B before cloud-init can make
        # its changes to fstab. This behavior is a major cause of problems and the reason why
        # micro instances tend to freeze when booting from images created on non-micro instances
        # since their fstab initially refers to an ephemeral volume that doesn't exist. The
        # nobootwait and nofail flags are really just attempts at working around this issue.
        #
        # [1]: https://bugs.launchpad.net/cloud-init/+bug/1291820
        #
        mounts = user_data.setdefault( 'mounts', [ ] )
        mounts.append(
                [ 'ephemeral0', self._ephemeral_mount_point( 0 ), 'auto', 'defaults,noauto' ] )

        commands = [ ]

        # On instances booted from a stock image we will likely need to install mdadm. And we
        # need to install mdadm on every instance type since an image taken from an instance with
        # one ephemeral volume may be used to spawn an instance with multiple ephemeral volumes.
        if self.generation == 0:
            commands.append( self._get_package_installation_command( 'mdadm' ) )
        num_disks = instance_type.disks
        device_prefix = self._get_virtual_block_device_prefix( )

        def device_name( i ):
            return device_prefix + (chr( ord( 'b' ) + i ))

        if num_disks == 0:
            pass
        elif instance_type.disk_type == 'HDD':
            # For HDDs we assume the disk is formatted and we mount each disk separately
            for i in range( num_disks ):
                mount_point = self._ephemeral_mount_point( i )
                if mount_point is not None:
                    commands.extend( [
                        [ 'mkdir', '-p', mount_point ],
                        [ 'mount', device_name( i ), mount_point ] ] )
        elif num_disks == 1:
            # The r3 family does not format the ephemeral SSD volume so will have to do it
            # manually. Other families may also exhibit that behavior so we will format every SSD
            # volume. It only takes a second *and* ensures that we have a particular type of
            # filesystem, i.e. ext4. We don't know what the device will be (cloud-init determines
            # this at runtime) named so we simply try all possible names.
            if instance_type.disk_type == 'SSD':
                commands.append( [ 'mkfs.ext4', '-E', 'nodiscard', device_name( 0 ) ] )
            mount_point = self._ephemeral_mount_point( 0 )
            commands.extend( [
                [ 'mkdir', '-p', mount_point ],
                [ 'mount', device_name( 0 ), mount_point ] ] )
        elif num_disks > 1:
            # RAID multiple SSDs into one, then format and mount it.
            devices = [ device_name( i ) for i in range( num_disks ) ]
            mount_point = self._ephemeral_mount_point( 0 )
            commands.extend( [
                [ 'mdadm',
                    '--create', '/dev/md0',
                    '--run',  # do not prompt for confirmation
                    '--level', '0',  # RAID 0, i.e. striped
                    '--raid-devices', str( num_disks ) ] + devices,
                # Disable auto scan at boot time, which would otherwise mount device on reboot
                # as md127 before these commands are run.
                'echo "AUTO -all" > /etc/mdadm/mdadm.conf',
                # Copy mdadm.conf into init ramdisk
                [ 'update-initramfs', '-u' ],
                [ 'mkfs.ext4', '-E', 'nodiscard', '/dev/md0' ],
                [ 'mkdir', '-p', mount_point ],
                [ 'mount', '/dev/md0', mount_point ] ] )
        else:
            assert False

        # Prepend commands as a best effort to getting volume preparation done as early as
        # possible in the boot sequence. Note that CloudInit's 'bootcmd' is run on every boot,
        # 'runcmd' only once after instance creation.
        bootcmd = user_data.setdefault( 'bootcmd', [ ] )
        bootcmd[ 0:0 ] = commands

    def _spec_block_device_mapping( self, spec, image ):
        super( CloudInitBox, self )._spec_block_device_mapping( spec, image )
        cloud_config = { }
        instance_type = ec2_instance_types[ spec[ 'instance_type' ] ]
        self._populate_cloud_config( instance_type, cloud_config )
        if cloud_config:
            if 'user_data' in spec:
                raise ReferenceError( "Conflicting user-data" )
            user_data = '#cloud-config\n' + yaml.dump( cloud_config )
            spec[ 'user_data' ] = user_data

    def _on_instance_ready( self, first_boot ):
        super( CloudInitBox, self )._on_instance_ready( first_boot )
        if first_boot:
            self.__wait_for_cloud_init_completion( )
            if self.generation == 0:
                self.__add_per_boot_script( )

    def _cloudinit_boot_script( self, name ):
        return '/var/lib/cloud/scripts/per-boot/cgcloud-' + name

    @fabric_task
    def __add_per_boot_script( self ):
        """
        Ensure that the cloud-init.done file is always created, even on 2nd boot and there-after.
        On the first boot of an instance, the .done file creation is preformed by the runcmd
        stanza in cloud-config. On subsequent boots this per-boot script takes over (runcmd is
        skipped on those boots).
        """
        put( remote_path=self._cloudinit_boot_script( 'done' ), mode=0755, use_sudo=True,
             local_path=StringIO( heredoc( """
                    #!/bin/sh
                    touch /tmp/cloud-init.done""" ) ) )

    def __wait_for_cloud_init_completion( self ):
        """
        Wait for cloud-init to finish its job such as to avoid getting in its way. Without this,
        I've seen weird errors with 'apt-get install' not being able to find any packages.

        Since this method belongs to a mixin, the author of a derived class is responsible for
        invoking this method before any other setup action.
        """
        # /var/lib/cloud/instance/boot-finished is only being written by newer cloud-init releases.
        # For example, it isn't being written by the cloud-init for Lucid. We must use our own file
        # created by a runcmd, see _populate_cloud_config()
        #
        # This function is called on every node in a cluster during that cluster's creation. For
        # that reason we want to avoid contention on the lock in @fabric_task that's protecting
        # the thread-unsafe Fabric code. This contention is aggravated by the fact that,
        # for some unkown reason, the first SSH connection to a node takes unusually long. With a
        # lock serialising all calls to this method we have to wait for the delay for every node
        # in sequence, in O(N) time. Paramiko, OTOH, is thread-safe allowing us to do the wait
        # in concurrently, in O(1) time.

        command = ';'.join( [
            'echo -n "Waiting for cloud-init to finish ..."',
            'while [ ! -e /tmp/cloud-init.done ]',
            'do echo -n "."',
            'sleep 1 ',
            'done ',
            'echo "... cloud-init done."' ] )

        self._run( command )

    def _run( self, cmd ):
        def stream( name, recv_ready, recv, logger ):
            i = 0
            r = ''
            try:
                while recv_ready( ):
                    s = recv( 1024 )
                    if not s: break
                    i += 1
                    ls = s.splitlines( )
                    # Prepend partial line from previous iteration to first line from this
                    # iteration. Note that the first line may be a partial line, too.
                    ls[ 0 ] = r + ls[ 0 ]
                    # Log all complete lines
                    for l in ls[ :-1 ]:
                        logger( "%s: %s", name, l )
                    r = ls[ -1 ]
            finally:
                # No chance to complete the partial line anytime soon, so log it.
                if r: logger( r )
            return i

        client = self._ssh_client( )
        try:
            with client.get_transport( ).open_session( ) as chan:
                assert isinstance( chan, Channel )
                chan.exec_command( cmd )
                streams = (
                    partial( stream, 'stderr', chan.recv_stderr_ready, chan.recv_stderr, log.warn ),
                    partial( stream, 'stdout', chan.recv_ready, chan.recv, log.info ))
                while sum( stream( ) for stream in streams ) or not chan.exit_status_ready( ):
                    time.sleep( paramiko.common.io_sleep )
                assert 0 == chan.recv_exit_status( )
        finally:
            client.close( )
