from fabric.operations import run
import yaml

from cgcloud.core.box import Box, fabric_task
from cgcloud.core.instance_type import ec2_instance_types


class CloudInitBox( Box ):
    """
    A box that uses Canonical's cloud-init to initialize the EC2 instance.
    """

    def _ephemeral_mount_point( self ):
        return '/mnt/ephemeral'

    def _ephemeral_preparation( self, ephemeral_mount_point, instance_type ):
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
        commands = [ ]
        instance_type = ec2_instance_types[ instance_type ]
        if instance_type.disks == 0:
            pass
        elif instance_type.disks > 0:
            # The r3 family does not format the ephemeral SSD volume so will have to do it
            # manually. Other families may also exhibit that behavior so we will format every SSD
            # volume. It only takes a second *and* ensures that we have a particular type of
            # filesystem, i.e. ext4. We don't know what the device will be (cloud-init determines
            # this at runtime) named so we simply try all possible names.
            if instance_type.disk_type == 'SSD':
                for device_name in ('sdb', 'xvdb'):
                    commands.append( [ 'mkfs.ext4', '-E', 'nodiscard', '/dev/' + device_name ] )
            commands.append( [ 'mount', ephemeral_mount_point ] )
        else:
            assert False
        return commands

    def _ephemeral_device_name( self ):
        return 'ephemeral0'

    def _populate_cloud_config( self, instance_type, user_data ):
        """
        Populate cloud-init's configuration for injection into a newly created instance

        :param user_data: a dictionary that will be be serialized into YAML and used as the
        instance's user-data
        """
        #
        # see __wait_for_cloud_init_completion()
        #
        runcmd = user_data.setdefault( 'runcmd', [ ] )
        runcmd.append( [ 'touch', '/tmp/cloud-init.done' ] )

        ephemeral_mount_point = self._ephemeral_mount_point( )
        user_data.setdefault( 'mounts', [ ] ).append(
            [ self._ephemeral_device_name( ), ephemeral_mount_point, 'auto', 'defaults,noauto' ] )
        #
        # prepend mount command as best effort to getting this done ASAP
        #
        runcmd[ 0:0 ] = self._ephemeral_preparation( ephemeral_mount_point, instance_type )

    def _populate_instance_creation_args( self, image, kwargs ):
        super( CloudInitBox, self )._populate_instance_creation_args( image, kwargs )
        #
        # Setup instance storage. Since some AMI', e.g. Fedora, omit the block device mapping for
        # instance storage, we force one here, such that cloud-init can mount it.
        #
        cloud_config = { }
        self._populate_cloud_config( kwargs[ 'instance_type' ], cloud_config )
        if cloud_config:
            if 'user_data' in kwargs:
                raise ReferenceError( "Conflicting user-data" )
            user_data = '#cloud-config\n' + yaml.dump( cloud_config )
            kwargs[ 'user_data' ] = user_data

    def _on_instance_ready( self, first_boot ):
        super( CloudInitBox, self )._on_instance_ready( first_boot )
        if first_boot:
            # cloud-init is run on every boot, but only on the first boot will it invoke the user
            # script that signals completion
            self.__wait_for_cloud_init_completion( )

    @fabric_task
    def __wait_for_cloud_init_completion( self ):
        """
        Wait for cloud-init to finish its job such as to avoid getting in its way. Without this,
        I've seen weird errors with 'apt-get install' not being able to find any packages.

        Since this method belongs to a mixin, the author of a derived class is responsible for
        invoking this method before any other setup action.
        """
        #
        # /var/lib/cloud/instance/boot-finished is only being written by newer cloud-init releases.
        # For example, it isn't being written by the cloud-init for Lucid. We must use our own file
        # created by a runcmd, see _populate_cloud_config()
        #
        run( 'echo -n "Waiting for cloud-init to finish ..." ; '
             'while [ ! -e /tmp/cloud-init.done ]; do '
             'echo -n "."; '
             'sleep 1; '
             'done; '
             'echo ", done."' )
