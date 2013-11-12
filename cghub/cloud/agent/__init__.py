import os

from cghub.cloud.lib.context import Context
from cghub.util.throttle import LocalThrottle


class Agent( object ):
    def __init__( self, ctx, options ):
        """
        :type ctx: Context
        """
        super( Agent, self ).__init__( )
        self.ctx = ctx
        self.options = options
        self.fingerprints = None

        topic_name = self.ctx.agent_topic_name
        response = self.ctx.sns.create_topic( topic_name )
        topic_arn = response[ 'CreateTopicResponse' ][ 'CreateTopicResult' ][ 'TopicArn' ]

        queue_name = self.ctx.agent_queue_name
        self.queue = self.ctx.sqs.get_queue( queue_name )
        if self.queue is None:
            # The create_queue API call handles races gracefully,
            # the conditional above is just an optimization.
            self.queue = self.ctx.sqs.create_queue( queue_name )
        self.ctx.sns.subscribe_sqs_queue( topic_arn, self.queue )

    def run( self ):
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

    def update_ssh_keys( self ):
        keypairs = self.ctx.expand_keypair_globs( self.options.keypairs )
        fingerprints = [ keypair.fingerprint for keypair in keypairs ]
        fingerprints.sort( )
        if fingerprints != self.fingerprints:
            ssh_keys = set( )
            for keypair in keypairs:
                ssh_key = self.ctx.download_ssh_pubkey( keypair )
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

