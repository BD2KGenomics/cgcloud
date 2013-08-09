from cghub.cloud.centos_box import CentosBox
from cghub.cloud.ubuntu_box import UbuntuBox


class GenericCentos5Box( CentosBox ):
    def __init__(self, env):
        super( GenericCentos5Box, self ).__init__( env, release='5.8' )

    @staticmethod
    def role():
        return 'generic-centos-5'


class GenericCentos6Box( CentosBox ):
    def __init__(self, env):
        super( GenericCentos5Box, self ).__init__( env, release='6.4' )

    @staticmethod
    def role():
        return 'generic-centos-6'


class GenericUbuntuPreciseBox( UbuntuBox ):
    def __init__(self, env):
        super( GenericUbuntuPreciseBox, self ).__init__( env, 'precise' )

    @staticmethod
    def role():
        return 'generic-ubuntu-precise'
