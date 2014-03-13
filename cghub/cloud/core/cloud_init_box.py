from fabric.operations import run
import yaml
from cghub.cloud.core.box import Box, fabric_task

__author__ = 'hannes'


class CloudInitBox( Box ):
    """
    A box that uses Canonical's cloud-init to initialize the EC2 instance.
    """

    def _ephemeral_mount_point( self ):
        return '/mnt/ephemeral'

    def _populate_cloud_config( self, instance_type, user_data ):
        """
        Populate cloud-init's configuration for injection into a newly created instance

        :param user_data: a dictionary that will be be serialized into YAML and used as the
        instance's user-data
        """
        #
        # see __wait_for_cloud_init_completion()
        #
        user_data.setdefault( 'runcmd', [ ] ).append( [ 'touch', '/tmp/cloud-init.done' ] )
        #
        # Lucid's and Oneiric's cloud-init mount ephemeral storage on /mnt instead of
        # /mnt/ephemeral, Fedora doesn't mount it at all. To keep it consistent across
        # releases and platforms we should be explicit.
        #
        # Also note that Lucid's mountall waits on the disk device. On t1.micro instances this
        # doesn't show up causing Lucid to hang on boot on this type. The cleanest way to handle
        # this is to remove the ephemeral entry on t1.micro instances. Unfortunately, there is a
        # bug [1] in cloud-init that causes the removal of the entry to be skipped. The
        # nobootwait option should be a viable workaround. It's supported on recent Ubuntu and
        # Fedora releases (I checked Fedora 19 and Ubuntu Lucid). It's only documented on Ubuntu
        # for some reason.
        #
        # [1]: https://bugs.launchpad.net/cloud-init/+bug/1291820
        #
        user_data.setdefault( 'mounts', [ ] ).append(
            [ 'ephemeral0', None ] if instance_type == 't1.micro' else
            [ 'ephemeral0', self._ephemeral_mount_point( ), 'auto', 'defaults,nobootwait' ] )

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
