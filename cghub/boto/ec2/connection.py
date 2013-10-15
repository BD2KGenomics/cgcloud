from boto import ec2
from boto.ec2.image import Image

# work around https://github.com/boto/boto/issues/1766

class EC2Connection( ec2.connection.EC2Connection ):
    def create_image(self, instance_id, name,
                     description=None,
                     no_reboot=False,
                     dry_run=False,
                     block_device_map=None):
        params = {
            'InstanceId': instance_id,
            'Name': name }
        if description:
            params[ 'Description' ] = description
        if no_reboot:
            params[ 'NoReboot' ] = 'true'
        if dry_run:
            params[ 'DryRun' ] = 'true'
        # This is missing in boto 2.13
        if block_device_map:
            block_device_map.ec2_build_list_params( params )
        img = self.get_object( 'CreateImage', params, Image, verb='POST' )
        return img.id
