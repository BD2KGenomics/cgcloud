from collections import namedtuple

IT = namedtuple( 'IT', [ 'name', 'cores', 'ecu', 'memory', 'disks', 'disk_type', 'disk_capacity' ] )

_ec2_instance_types = [
    # current generation instance types
    IT( name='t2.micro', cores='1', ecu='variable', memory='1', disks=0, disk_type=None, disk_capacity=0 ),
    IT( name='t2.small', cores='1', ecu='variable', memory='2', disks=0, disk_type=None, disk_capacity=0 ),
    IT( name='t2.medium', cores='2', ecu='variable', memory='4', disks=0, disk_type=None, disk_capacity=0 ),
    IT( name='m3.medium', cores='1', ecu='3', memory='3.75', disks=1, disk_type='SSD', disk_capacity=4 ),
    IT( name='m3.large', cores='2', ecu='6.5', memory='7.5', disks=1, disk_type='SSD', disk_capacity=32 ),
    IT( name='m3.xlarge', cores='4', ecu='13', memory='15', disks=2, disk_type='SSD', disk_capacity=40 ),
    IT( name='m3.2xlarge', cores='8', ecu='26', memory='30', disks=2, disk_type='SSD', disk_capacity=80 ),
    IT( name='c4.large', cores='2', ecu='8', memory='3.75', disks=0, disk_type=None, disk_capacity=0 ),
    IT( name='c4.xlarge', cores='4', ecu='16', memory='7.5', disks=0, disk_type=None, disk_capacity=0 ),
    IT( name='c4.2xlarge', cores='8', ecu='31', memory='15', disks=0, disk_type=None, disk_capacity=0 ),
    IT( name='c4.4xlarge', cores='16', ecu='62', memory='30', disks=0, disk_type=None, disk_capacity=0 ),
    IT( name='c4.8xlarge', cores='36', ecu='132', memory='60', disks=0, disk_type=None, disk_capacity=0 ),
    IT( name='c3.large', cores='2', ecu='7', memory='3.75', disks=2, disk_type='SSD', disk_capacity=16 ),
    IT( name='c3.xlarge', cores='4', ecu='14', memory='7.5', disks=2, disk_type='SSD', disk_capacity=40 ),
    IT( name='c3.2xlarge', cores='8', ecu='28', memory='15', disks=2, disk_type='SSD', disk_capacity=80 ),
    IT( name='c3.4xlarge', cores='16', ecu='55', memory='30', disks=2, disk_type='SSD', disk_capacity=160 ),
    IT( name='c3.8xlarge', cores='32', ecu='108', memory='60', disks=2, disk_type='SSD', disk_capacity=320 ),
    IT( name='g2.2xlarge', cores='8', ecu='26', memory='15', disks=1, disk_type='SSD', disk_capacity=60 ),
    IT( name='r3.large', cores='2', ecu='6.5', memory='15', disks=1, disk_type='SSD', disk_capacity=32 ),
    IT( name='r3.xlarge', cores='4', ecu='13', memory='30.5', disks=1, disk_type='SSD', disk_capacity=80 ),
    IT( name='r3.2xlarge', cores='8', ecu='26', memory='61', disks=1, disk_type='SSD', disk_capacity=160 ),
    IT( name='r3.4xlarge', cores='16', ecu='52', memory='122', disks=1, disk_type='SSD', disk_capacity=320 ),
    IT( name='r3.8xlarge', cores='32', ecu='104', memory='244', disks=2, disk_type='SSD', disk_capacity=320 ),
    IT( name='i2.xlarge', cores='4', ecu='14', memory='30.5', disks=1, disk_type='SSD', disk_capacity=800 ),
    IT( name='i2.2xlarge', cores='8', ecu='27', memory='61', disks=2, disk_type='SSD', disk_capacity=800 ),
    IT( name='i2.4xlarge', cores='16', ecu='53', memory='122', disks=4, disk_type='SSD', disk_capacity=800 ),
    IT( name='i2.8xlarge', cores='32', ecu='104', memory='244', disks=8, disk_type='SSD', disk_capacity=800 ),
    IT( name='d2.xlarge', cores='4', ecu='14', memory='30.5', disks=3, disk_type='HDD', disk_capacity=2000 ),
    IT( name='d2.2xlarge', cores='8', ecu='28', memory='61', disks=6, disk_type='HDD', disk_capacity=2000 ),
    IT( name='d2.4xlarge', cores='16', ecu='56', memory='122', disks=12, disk_type='HDD', disk_capacity=2000 ),
    IT( name='d2.8xlarge', cores='36', ecu='116', memory='244', disks=24, disk_type='HDD', disk_capacity=2000 ),
    # previous generation instance types
    IT( name='m1.small', cores='1', ecu='1', memory='1.7', disks=1, disk_type='HDD', disk_capacity=160 ),
    IT( name='m1.medium', cores='1', ecu='2', memory='3.75', disks=1, disk_type='HDD', disk_capacity=410 ),
    IT( name='m1.large', cores='2', ecu='4', memory='7.5', disks=2, disk_type='HDD', disk_capacity=420 ),
    IT( name='m1.xlarge', cores='4', ecu='8', memory='15', disks=4, disk_type='HDD', disk_capacity=420 ),
    IT( name='c1.medium', cores='2', ecu='5', memory='1.7', disks=1, disk_type='HDD', disk_capacity=350 ),
    IT( name='c1.xlarge', cores='8', ecu='20', memory='7', disks=4, disk_type='HDD', disk_capacity=420 ),
    IT( name='cc2.8xlarge', cores='32', ecu='88', memory='60.5', disks=4, disk_type='HDD', disk_capacity=840 ),
    IT( name='m2.xlarge', cores='2', ecu='6.5', memory='17.1', disks=1, disk_type='HDD', disk_capacity=420 ),
    IT( name='m2.2xlarge', cores='4', ecu='13', memory='34.2', disks=1, disk_type='HDD', disk_capacity=850 ),
    IT( name='m2.4xlarge', cores='8', ecu='26', memory='68.4', disks=2, disk_type='HDD', disk_capacity=840 ),
    IT( name='cr1.8xlarge', cores='32', ecu='88', memory='244', disks=2, disk_type='SSD', disk_capacity=120 ),
    IT( name='hi1.4xlarge', cores='16', ecu='35', memory='60.5', disks=2, disk_type='SSD', disk_capacity=1024 ),
    IT( name='hs1.8xlarge', cores='16', ecu='35', memory='117', disks=24, disk_type='HDD', disk_capacity=2048 ),
    IT( name='t1.micro', cores='1', ecu='variable', memory='0.615', disks=0, disk_type=None, disk_capacity=0 ) ]


ec2_instance_types = dict( ( _.name, _ ) for _ in _ec2_instance_types )
