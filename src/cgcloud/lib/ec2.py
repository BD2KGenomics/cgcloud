from contextlib import contextmanager
import logging
import time

from boto.exception import EC2ResponseError

a_short_time = 5

a_long_time = 60 * 60

log = logging.getLogger( __name__ )


def __not_found( e ):
    return e.error_code.ends_with( '.NotFound' )


@contextmanager
def retry_ec2_request( retry_every=a_short_time,
           retry_for=10 * a_short_time,
           retry_while=__not_found ):
    if retry_for > 0:
        expiration = time.time( ) + retry_for
        while True:
            try:
                yield
            except EC2ResponseError as e:
                if ( expiration is None or time.time( ) < expiration ) and retry_while( e ):
                    log.info( '... got %s, trying again in %is ...' %
                              ( e.error_code, a_short_time ) )
                    time.sleep( retry_every )
                else:
                    raise
            else:
                break
    else:
        yield

