from operator import attrgetter
import os
from boto import sns, sqs, ec2

from hashlib import sha1

from boto.s3.connection import S3Connection
from boto.sqs.connection import SQSConnection
from boto.sns.connection import SNSConnection
from boto.ec2.connection import EC2Connection
from cghub.cloud.lib.environment import Environment
from cghub.util.throttle import LocalThrottle


class Agent( object ):
    def __init__(self, env, options):
        """
        :type env: Environment
        """
        super( Agent, self ).__init__( )
        self.options = options
        self.env = env
        self.fingerprints = None
        self.sns = self.aws_connect( sns )
        """
        :type: SNSConnection
        """
        self.sqs = self.aws_connect( sqs )
        """
        :type: SQSConnection
        """
        self.ec2 = self.aws_connect( ec2 )
        """
        :type: EC2Connection
        """
        response = self.sns.create_topic( self.env.topic_name )
        topic_arn = response[ 'CreateTopicResponse' ][ 'CreateTopicResult' ][ 'TopicArn' ]

        queue_name = self.env.agent_queue_name( )
        self.queue = self.sqs.get_queue( queue_name )
        if self.queue is None:
            # The create_queue API call handles races gracefully,
            # the conditional above is just an optimization.
            self.queue = self.sqs.create_queue( queue_name )
        self.sns.subscribe_sqs_queue( topic_arn, self.queue )

    def aws_connect(self, aws_module):
        conn = aws_module.connect_to_region( self.env.region )
        if conn is None:
            raise RuntimeError( "%s couldn't connect to region %s" % (
                aws_module.__name__, self.env.region ) )
        return conn

    def run(self):
        throttle = LocalThrottle( min_interval=self.options.interval )
        # first call always returns immediately
        throttle.throttle( )
        # Always update keys initially
        self.update_ssh_keys( )
        while True:
            # Do long polling for messages
            messages = self.queue.get_messages( num_messages=100,
                                                wait_time_seconds=20, # the maximum permitted
                                                visibility_timeout=10 )
            if messages:
                # Greedily comsume all accrued messages ...
                self.queue.delete_message_batch( messages )
                # ... and update the keys.
                self.update_ssh_keys( )
            else:
                # Without messages update if throttle interval has passed
                if throttle.throttle( wait=False ):
                    self.update_ssh_keys( )

    def update_ssh_keys(self):
        keypairs = self.env.expand_keypair_globs( self.options.keypairs )
        fingerprints = [ keypair.fingerprint for keypair in keypairs ]
        fingerprints.sort( )
        if fingerprints != self.fingerprints:
            ssh_keys = set( )
            for keypair in keypairs:
                ssh_key = self.env.download_ssh_pubkey( keypair )
                ssh_keys.add( ssh_key )
            local_ssh_keys = set( )
            if os.path.isfile( self.options.authorized_keys_path ):
                with open( self.options.authorized_keys_path ) as f:
                    for l in f.readlines( ):
                        if not l.isspace( ):
                            local_ssh_keys.add( l.strip( ) )
            if local_ssh_keys != ssh_keys:
                with open( self.options.authorized_keys_path, 'w' ) as f:
                    f.writelines( ssh_key + '\n' for ssh_key in ssh_keys )
            self.fingerprints = fingerprints

