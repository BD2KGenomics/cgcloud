from cgcloud.bd2k.ci.generic_jenkins_slaves import UbuntuTrustyGenericJenkinsSlave
from cgcloud.core.common_iam_policies import s3_full_policy
from cgcloud.lib.util import abreviated_snake_case_class_name


class S3amJenkinsSlave( UbuntuTrustyGenericJenkinsSlave ):
    """
    A Jenkins slave for running the S3AM build
    """

    @classmethod
    def recommended_instance_type( cls ):
        return "m4.xlarge"

    def _list_packages_to_install( self ):
        return super( S3amJenkinsSlave, self )._list_packages_to_install( ) + [
            'python-dev',
            'gcc', 'make', 'libcurl4-openssl-dev' # pycurl
        ]

    def _get_iam_ec2_role( self ):
        role_name, policies = super( S3amJenkinsSlave, self )._get_iam_ec2_role( )
        role_name += '--' + abreviated_snake_case_class_name( S3amJenkinsSlave )
        policies.update( dict( s3_full=s3_full_policy ) )
        return role_name, policies
