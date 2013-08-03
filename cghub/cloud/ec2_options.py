from collections import namedtuple

# Not doing this as a dict or namedtuple such that I can document each required attribute
import re


class Ec2Options:
    """
    Encapsulates all EC2-specific settings used by components in this project
    """

    availability_zone_re = re.compile( r'^([a-z]{2}-[a-z]+-[1-9][0-9]*)([a-z])$' )

    def __init__(self, availability_zone, instance_type, ssh_key_name):
        """
        Create an Ec2Options object.

        :param availability_zone:
            The availability zone to place EC2 resources like volumes and instances into. The AWS
            region to operate in is implied by this parameter since the region is a prefix of the
            availability zone string
        :param instance_type:
            The type of instance to create, e.g. m1.small or t1.micro.
        :param ssh_key_name:
            The name of the SSH public key to inject into the instance
        """

        self.availability_zone = availability_zone
        m = self.availability_zone_re.match( availability_zone )
        if not m:
            raise RuntimeError( "Can't extract region from availability-zone '%s'" % availability_zone )
        self.region = m.group( 1 )
        self.instance_type = instance_type
        self.ssh_key_name = ssh_key_name
