from cghub.cloud.centos_box import CentosBox
from cghub.cloud.ubuntu_box import UbuntuBox


class GenericCentos5Box( CentosBox ):
    def release(self):
        return '5.8'


class GenericCentos6Box( CentosBox ):
    def release(self):
        return '6.4'

class GenericLucidBox( UbuntuBox ):
    """
    10.04
    """
    def release(self):
        return 'lucid'

class GenericMaverickBox( UbuntuBox ):
    """
    10.10
    """
    def release(self):
        return 'maverick'

class GenericNattyBox( UbuntuBox ):
    """
    11.04
    """
    def release(self):
        return 'natty'

class GenericOneiricBox( UbuntuBox ):
    """
    11.10
    """
    def release(self):
        return 'oneiric'

class GenericPreciseBox( UbuntuBox ):
    """
    12.04
    """
    def release(self):
        return 'precise'

class GenericQuantalBox( UbuntuBox ):
    """
    12.10
    """
    def release(self):
        return 'quantal'

class GenericRaringBox( UbuntuBox ):
    """
    13.04
    """
    def release(self):
        return 'raring'

class GenericSaucyBox( UbuntuBox ):
    """
    13.10
    """
    def release(self):
        return 'saucy'
