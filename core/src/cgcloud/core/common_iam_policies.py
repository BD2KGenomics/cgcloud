ec2_read_only_policy = dict( Version="2012-10-17", Statement=[
    dict( Effect="Allow", Resource="*", Action="ec2:Describe*" ),
    dict( Effect="Allow", Resource="*", Action="autoscaling:Describe*" ),
    dict( Effect="Allow", Resource="*", Action="elasticloadbalancing:Describe*" ),
    dict( Effect="Allow", Resource="*", Action=[
        "cloudwatch:ListMetrics",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:Describe*" ] ) ] )

s3_read_only_policy = dict( Version="2012-10-17", Statement=[
    dict( Effect="Allow", Resource="*", Action=[ "s3:Get*", "s3:List*" ] ) ] )

iam_read_only_policy = dict( Version="2012-10-17", Statement=[
    dict( Effect="Allow", Resource="*", Action=[ "iam:List*", "iam:Get*" ] ) ] )

ec2_full_policy = dict( Version="2012-10-17", Statement=[
    dict( Effect="Allow", Resource="*", Action="ec2:*" ) ] )

s3_full_policy = dict( Version="2012-10-17", Statement=[
    dict( Effect="Allow", Resource="*", Action="s3:*" ) ] )

sdb_full_policy = dict( Version="2012-10-17", Statement=[
    dict( Effect="Allow", Resource="*", Action="sdb:*" ) ] )
