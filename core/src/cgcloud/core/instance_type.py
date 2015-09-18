from collections import namedtuple

InstanceType = namedtuple( 'InstanceType', [
    'name', # the API name of the instance type
    'cores', # the number of cores
    'ecu', # the computational power of the core times the number of cores
    'memory', # RAM in GB
    'virtualization_types', # the supported virtualization types, in order of preference
    'disks', # the number of ephemeral (aka 'instance store') volumes
    'disk_type', # the type of ephemeral volume
    'disk_capacity' # the capacity of each ephemeral volume in GB
] )

hvm = 'hvm' # hardware virtualization
pv = 'paravirtual' # para-virtualization
ssd = 'SSD' # solid-state disk
hdd = 'HDD' # spinning disk
variable_ecu = -1 # variable ecu

_ec2_instance_types = [
    # current generation instance types
    InstanceType( 't2.micro', 1, variable_ecu, 1, [ hvm ], 0, None, 0 ),
    InstanceType( 't2.small', 1, variable_ecu, 2, [ hvm ], 0, None, 0 ),
    InstanceType( 't2.medium', 2, variable_ecu, 4, [ hvm ], 0, None, 0 ),
    InstanceType( 't2.large', 2, variable_ecu, 8, [ hvm ], 0, None, 0 ),

    InstanceType( 'm3.medium', 1, 3, 3.75, [ hvm, pv ], 1, ssd, 4 ),
    InstanceType( 'm3.large', 2, 6.5, 7.5, [ hvm, pv ], 1, ssd, 32 ),
    InstanceType( 'm3.xlarge', 4, 13, 15, [ hvm, pv ], 2, ssd, 40 ),
    InstanceType( 'm3.2xlarge', 8, 26, 30, [ hvm, pv ], 2, ssd, 80 ),

    InstanceType( 'm4.large', 2, 6.5, 8, [ hvm ], 0, None, 0 ),
    InstanceType( 'm4.xlarge', 4, 13, 16, [ hvm ], 0, None, 0 ),
    InstanceType( 'm4.2xlarge', 8, 26, 32, [ hvm ], 0, None, 0 ),
    InstanceType( 'm4.4xlarge', 16, 53.5, 64, [ hvm ], 0, None, 0 ),
    InstanceType( 'm4.10xlarge', 40, 124.5, 160, [ hvm ], 0, None, 0 ),

    InstanceType( 'c4.large', 2, 8, 3.75, [ hvm ], 0, None, 0 ),
    InstanceType( 'c4.xlarge', 4, 16, 7.5, [ hvm ], 0, None, 0 ),
    InstanceType( 'c4.2xlarge', 8, 31, 15, [ hvm ], 0, None, 0 ),
    InstanceType( 'c4.4xlarge', 16, 62, 30, [ hvm ], 0, None, 0 ),
    InstanceType( 'c4.8xlarge', 36, 132, 60, [ hvm ], 0, None, 0 ),

    InstanceType( 'c3.large', 2, 7, 3.75, [ hvm, pv ], 2, ssd, 16 ),
    InstanceType( 'c3.xlarge', 4, 14, 7.5, [ hvm, pv ], 2, ssd, 40 ),
    InstanceType( 'c3.2xlarge', 8, 28, 15, [ hvm, pv ], 2, ssd, 80 ),
    InstanceType( 'c3.4xlarge', 16, 55, 30, [ hvm, pv ], 2, ssd, 160 ),
    InstanceType( 'c3.8xlarge', 32, 108, 60, [ hvm, pv ], 2, ssd, 320 ),

    InstanceType( 'g2.2xlarge', 8, 26, 15, [ hvm ], 1, ssd, 60 ),

    InstanceType( 'r3.large', 2, 6.5, 15, [ hvm ], 1, ssd, 32 ),
    InstanceType( 'r3.xlarge', 4, 13, 30.5, [ hvm ], 1, ssd, 80 ),
    InstanceType( 'r3.2xlarge', 8, 26, 61, [ hvm ], 1, ssd, 160 ),
    InstanceType( 'r3.4xlarge', 16, 52, 122, [ hvm ], 1, ssd, 320 ),
    InstanceType( 'r3.8xlarge', 32, 104, 244, [ hvm ], 2, ssd, 320 ),

    InstanceType( 'i2.xlarge', 4, 14, 30.5, [ hvm ], 1, ssd, 800 ),
    InstanceType( 'i2.2xlarge', 8, 27, 61, [ hvm ], 2, ssd, 800 ),
    InstanceType( 'i2.4xlarge', 16, 53, 122, [ hvm ], 4, ssd, 800 ),
    InstanceType( 'i2.8xlarge', 32, 104, 244, [ hvm ], 8, ssd, 800 ),

    InstanceType( 'd2.xlarge', 4, 14, 30.5, [ hvm ], 3, hdd, 2000 ),
    InstanceType( 'd2.2xlarge', 8, 28, 61, [ hvm ], 6, hdd, 2000 ),
    InstanceType( 'd2.4xlarge', 16, 56, 122, [ hvm ], 12, hdd, 2000 ),
    InstanceType( 'd2.8xlarge', 36, 116, 244, [ hvm ], 24, hdd, 2000 ),

    # previous generation instance types
    InstanceType( 'm1.small', 1, 1, 1.7, [ pv ], 1, hdd, 160 ),
    InstanceType( 'm1.medium', 1, 2, 3.75, [ pv ], 1, hdd, 410 ),
    InstanceType( 'm1.large', 2, 4, 7.5, [ pv ], 2, hdd, 420 ),
    InstanceType( 'm1.xlarge', 4, 8, 15, [ pv ], 4, hdd, 420 ),

    InstanceType( 'c1.medium', 2, 5, 1.7, [ pv ], 1, hdd, 350 ),
    InstanceType( 'c1.xlarge', 8, 20, 7, [ pv ], 4, hdd, 420 ),

    InstanceType( 'cc2.8xlarge', 32, 88, 60.5, [ hvm ], 4, hdd, 840 ),

    InstanceType( 'm2.xlarge', 2, 6.5, 17.1, [ pv ], 1, hdd, 420 ),
    InstanceType( 'm2.2xlarge', 4, 13, 34.2, [ pv ], 1, hdd, 850 ),
    InstanceType( 'm2.4xlarge', 8, 26, 68.4, [ pv ], 2, hdd, 840 ),

    InstanceType( 'cr1.8xlarge', 32, 88, 244, [ hvm ], 2, ssd, 120 ),

    InstanceType( 'hi1.4xlarge', 16, 35, 60.5, [ hvm, pv ], 2, ssd, 1024 ),

    InstanceType( 'hs1.8xlarge', 16, 35, 117, [ hvm, pv ], 24, hdd, 2048 ),

    InstanceType( 't1.micro', 1, variable_ecu, 0.615, [ pv ], 0, None, 0 ) ]

ec2_instance_types = dict( ( _.name, _ ) for _ in _ec2_instance_types )
