from cgcloud.core import test_namespace_suffix_length
from cgcloud.core.common_iam_policies import ec2_full_policy
from cgcloud.core.ubuntu_box import Python27UpdateUbuntuBox
from cgcloud.lib.util import abreviated_snake_case_class_name

from cgcloud.jenkins.generic_jenkins_slaves import UbuntuTrustyGenericJenkinsSlave


class CgcloudJenkinsSlave( UbuntuTrustyGenericJenkinsSlave, Python27UpdateUbuntuBox ):
    """
    A Jenkins slave for runing CGCloud's unit tests
    """

    @classmethod
    def recommended_instance_type( cls ):
        return "m3.xlarge"

    def _list_packages_to_install( self ):
        return super( CgcloudJenkinsSlave, self )._list_packages_to_install( ) + [
            # for PyCrypto:
            'python-dev',
            'autoconf',
            'automake',
            'binutils',
            'gcc',
            'make',
            'libyaml-dev'
        ]

    def _get_iam_ec2_role( self ):
        role_name, policies = super( CgcloudJenkinsSlave, self )._get_iam_ec2_role( )
        role_name += '--' + abreviated_snake_case_class_name( CgcloudJenkinsSlave )
        cgcloud_bucket_arn = "arn:aws:s3:::%s" % self.ctx.s3_bucket_name
        # This is a bit convoluted, but it is still better than optionally allowing wildcards in
        # the name validation in Context.absolute_name(). The ? wildcard is not very well
        # documented but I found evidence for it here:
        # http://docs.aws.amazon.com/IAM/latest/UserGuide/PolicyVariables.html#policy-vars-specialchars
        test_namespace_suffix_pattern = "?" * test_namespace_suffix_length
        pass_role_arn = self._role_arn( role_prefix='test/testnamespacesuffixpattern/' )
        pass_role_arn = pass_role_arn.replace( 'testnamespacesuffixpattern',
                                               test_namespace_suffix_pattern )
        policies.update( dict(
            ec2_full=ec2_full_policy,  # FIXME: Be more specific
            iam_cgcloud_jenkins_slave_pass_role=dict( Version="2012-10-17", Statement=[
                # This assumes that if instance lives in /, then tests running on the instance
                # will run in /test-5571439d. If the instance lives in /foo, then tests running
                # on the instance will run in /foo/test-5571439d.
                dict( Effect="Allow",
                      Resource=pass_role_arn,
                      Action="iam:PassRole" ) ] ),
            register_keypair=dict( Version="2012-10-17", Statement=[
                dict( Effect="Allow", Resource="arn:aws:s3:::*", Action="s3:ListAllMyBuckets" ),
                dict( Effect="Allow", Action="s3:*", Resource=[
                    cgcloud_bucket_arn,
                    cgcloud_bucket_arn + "/*" ] ),
                dict( Effect="Allow",
                      Resource='arn:aws:sns:*:%s:cgcloud-agent-notifications' % self.ctx.account,
                      Action=[ "sns:Publish", "sns:CreateTopic" ] ) ] ),
            iam_cgcloud_jenkins_slave=dict( Version="2012-10-17", Statement=[
                dict( Effect="Allow", Resource="*", Action=[
                    "iam:ListRoles",
                    "iam:CreateRole",
                    "iam:DeleteRole",
                    "iam:ListRolePolicies",
                    "iam:DeleteRolePolicy",
                    "iam:GetRolePolicy",
                    "iam:PutRolePolicy",
                    "iam:ListInstanceProfiles",
                    "iam:GetInstanceProfile",
                    "iam:CreateInstanceProfile",
                    "iam:DeleteInstanceProfile",
                    "iam:RemoveRoleFromInstanceProfile",
                    "iam:AddRoleToInstanceProfile",
                    "iam:DeleteInstanceProfile" ] ) ] ) ) )
        return role_name, policies
