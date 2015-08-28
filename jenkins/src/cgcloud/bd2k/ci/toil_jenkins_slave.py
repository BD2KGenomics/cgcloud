from StringIO import StringIO

from fabric.operations import run, put

from cgcloud.bd2k.ci import UbuntuTrustyGenericJenkinsSlave
from cgcloud.core import fabric_task
from cgcloud.core.common_iam_policies import s3_full_policy, sdb_full_policy
from cgcloud.fabric.operations import sudo
from cgcloud.lib.util import abreviated_snake_case_class_name, heredoc


class ToilJenkinsSlave( UbuntuTrustyGenericJenkinsSlave ):
    """
    A Jenkins slave suitable for running Toil unit tests, specifically the Mesos batch system
    and the AWS job store. Legacy batch systems (parasol, gridengine, ...) are not yet supported.
    """

    @classmethod
    def recommended_instance_type( cls ):
        return "m3.large"

    @fabric_task
    def _setup_package_repos( self ):
        super( ToilJenkinsSlave, self )._setup_package_repos( )
        sudo( "apt-key adv --keyserver keyserver.ubuntu.com --recv E56151BF" )
        distro = run( "lsb_release -is | tr '[:upper:]' '[:lower:]'" )
        codename = run( "lsb_release -cs" )
        run( 'echo "deb http://repos.mesosphere.io/{} {} main"'
             '| sudo tee /etc/apt/sources.list.d/mesosphere.list'.format( distro, codename ) )

    def _list_packages_to_install( self ):
        return super( ToilJenkinsSlave, self )._list_packages_to_install( ) + [
            'mesos',
            'python-dev'
        ]

    def _post_install_packages( self ):
        super( ToilJenkinsSlave, self )._post_install_packages( )
        self.__disable_mesos_daemons( )
        self.__install_mesos_egg( )
        self.__install_parasol( )
        self.__patch_distutils( )

    @fabric_task
    def __disable_mesos_daemons( self ):
        for daemon in ('master', 'slave'):
            sudo( 'echo manual > /etc/init/mesos-%s.override' % daemon )
    @fabric_task
    def __install_parasol( self ):
        run("git clone http://github.com/adderan/parasol-binaries")
        sudo("cp ./parasol-binaries/* /usr/local/bin")

    @fabric_task
    def __install_mesos_egg( self ):
        # FIXME: this is the ubuntu 14.04 version. Wont work with other versions.
        run( "wget http://downloads.mesosphere.io/master/ubuntu/14.04/"
             "mesos-0.22.0-py2.7-linux-x86_64.egg" )
        # we need a newer version of protobuf than comes default on ubuntu
        sudo( "pip install --upgrade protobuf" )
        sudo( "easy_install mesos-0.22.0-py2.7-linux-x86_64.egg" )

    def _get_iam_ec2_role( self ):
        role_name, policies = super( ToilJenkinsSlave, self )._get_iam_ec2_role( )
        role_name += '--' + abreviated_snake_case_class_name( ToilJenkinsSlave )
        policies.update( dict( s3_full=s3_full_policy, sdb_full=sdb_full_policy ) )
        return role_name, policies

    @fabric_task
    def __patch_distutils( self ):
        """
        https://hg.python.org/cpython/rev/cf70f030a744/
        https://bitbucket.org/pypa/setuptools/issues/248/exit-code-is-zero-when-upload-fails
        """
        put( local_path=StringIO( heredoc( """
            --- a/Lib/distutils/command/upload.py
            +++ b/Lib/distutils/command/upload.py
            @@ -10,7 +10,7 @@ import urlparse
             import cStringIO as StringIO
             from hashlib import md5

            -from distutils.errors import DistutilsOptionError
            +from distutils.errors import DistutilsError, DistutilsOptionError
             from distutils.core import PyPIRCCommand
             from distutils.spawn import spawn
             from distutils import log
            @@ -181,7 +181,7 @@ class upload(PyPIRCCommand):
                             self.announce(msg, log.INFO)
                     except socket.error, e:
                         self.announce(str(e), log.ERROR)
            -            return
            +            raise
                     except HTTPError, e:
                         status = e.code
                         reason = e.msg
            @@ -190,5 +190,6 @@ class upload(PyPIRCCommand):
                         self.announce('Server response (%s): %s' % (status, reason),
                                       log.INFO)
                     else:
            -            self.announce('Upload failed (%s): %s' % (status, reason),
            -                          log.ERROR)
            +            msg = 'Upload failed (%s): %s' % (status, reason)
            +            self.announce(msg, log.ERROR)
            +            raise DistutilsError(msg)
        """ ) ), remote_path='distutils.patch' )
        sudo( "sudo patch -d /usr/lib/python2.7 -p2 < distutils.patch" )
        run( 'rm distutils.patch' )
