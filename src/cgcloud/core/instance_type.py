from collections import namedtuple

InstanceType = namedtuple( 'InstanceType', [ 'name', 'num_ephemeral_drives' ] )

_ec2_instance_types = [
    InstanceType( 't2.micro', 0 ),
    InstanceType( 't2.small', 0 ),
    InstanceType( 't2.medium', 0 ),
    InstanceType( 'm3.medium', 1 ),
    InstanceType( 'm3.large', 1 ),
    InstanceType( 'm3.xlarge', 2 ),
    InstanceType( 'm3.2xlarge', 2 ),
    InstanceType( 'c3.large', 2 ),
    InstanceType( 'c3.xlarge', 2 ),
    InstanceType( 'c3.2xlarge', 2 ),
    InstanceType( 'c3.4xlarge', 2 ),
    InstanceType( 'c3.8xlarge', 2 ),
    InstanceType( 'g2.2xlarge', 1 ),
    InstanceType( 'r3.large', 1 ),
    InstanceType( 'r3.xlarge', 1 ),
    InstanceType( 'r3.2xlarge', 1 ),
    InstanceType( 'r3.4xlarge', 1 ),
    InstanceType( 'r3.8xlarge', 2 ),
    InstanceType( 'i2.xlarge', 1 ),
    InstanceType( 'i2.2xlarge', 2 ),
    InstanceType( 'i2.4xlarge', 4 ),
    InstanceType( 'i2.8xlarge', 8 ),
    InstanceType( 'hs1.8xlarge', 24 )
]

ec2_instance_types = dict( ( _.name, _ ) for _ in _ec2_instance_types )
