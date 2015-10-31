from cgcloud.core.ubuntu_box import Python27UpdateUbuntuBox
from cgcloud.jenkins.generic_jenkins_slaves import UbuntuTrustyGenericJenkinsSlave
from cgcloud.core.box import fabric_task
from cgcloud.core.common_iam_policies import s3_full_policy
from cgcloud.fabric.operations import remote_sudo_popen
from cgcloud.lib.util import abreviated_snake_case_class_name, heredoc


class S3amJenkinsSlave( UbuntuTrustyGenericJenkinsSlave, Python27UpdateUbuntuBox ):
    """
    A Jenkins slave for running the S3AM build
    """

    @classmethod
    def recommended_instance_type( cls ):
        return "m4.xlarge"

    def _list_packages_to_install( self ):
        return super( S3amJenkinsSlave, self )._list_packages_to_install( ) + [
            'python-dev',
            'gcc', 'make', 'libcurl4-openssl-dev'  # pycurl
        ]

    def _post_install_packages( self ):
        super( S3amJenkinsSlave, self )._post_install_packages( )
        self.__patch_asynchat( )

    def _get_iam_ec2_role( self ):
        role_name, policies = super( S3amJenkinsSlave, self )._get_iam_ec2_role( )
        role_name += '--' + abreviated_snake_case_class_name( S3amJenkinsSlave )
        policies.update( dict( s3_full=s3_full_policy ) )
        return role_name, policies

    @fabric_task
    def __patch_asynchat( self ):
        """
        This bites us in pyftpdlib during S3AM unit tests:

        http://jenkins.cgcloud.info/job/s3am/13/testReport/junit/src.s3am.test.s3am_tests/CoreTests/test_copy/

        The patch is from

        https://hg.python.org/cpython/rev/d422062d7d36
        http://bugs.python.org/issue16133
        Fixed in 2.7.9: https://hg.python.org/cpython/raw-file/v2.7.9/Misc/NEWS
        """
        if self._remote_python_version() < (2,7,9):
            with remote_sudo_popen( 'patch -d /usr/lib/python2.7 -p2' ) as patch:
                patch.write( heredoc( '''
                    diff --git a/Lib/asynchat.py b/Lib/asynchat.py
                    --- a/Lib/asynchat.py
                    +++ b/Lib/asynchat.py
                    @@ -46,12 +46,17 @@ method) up to the terminator, and then c
                     you - by calling your self.found_terminator() method.
                     """

                    +import asyncore
                    +import errno
                     import socket
                    -import asyncore
                     from collections import deque
                     from sys import py3kwarning
                     from warnings import filterwarnings, catch_warnings

                    +_BLOCKING_IO_ERRORS = (errno.EAGAIN, errno.EALREADY, errno.EINPROGRESS,
                    +                       errno.EWOULDBLOCK)
                    +
                    +
                     class async_chat (asyncore.dispatcher):
                         """This is an abstract class.  You must derive from this class, and add
                         the two methods collect_incoming_data() and found_terminator()"""
                    @@ -109,6 +114,8 @@ class async_chat (asyncore.dispatcher):
                             try:
                                 data = self.recv (self.ac_in_buffer_size)
                             except socket.error, why:
                    +            if why.args[0] in _BLOCKING_IO_ERRORS:
                    +                return
                                 self.handle_error()
                                 return''' ) )
