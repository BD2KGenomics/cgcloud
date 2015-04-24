from contextlib import contextmanager
import logging
import time

from boto.exception import EC2ResponseError

a_short_time = 5

a_long_time = 60 * 60

log = logging.getLogger( __name__ )


def not_found( e ):
    return e.error_code.endswith( '.NotFound' )


def true( _ ):
    return True


def false( _ ):
    return False


def retry_ec2( retry_after=a_short_time,
               retry_for=10 * a_short_time,
               retry_while=not_found ):
    """
    Retry an EC2 operation while the failure matches a given predicate and until a given timeout
    expires, waiting a given amount of time in between attempts. This function is a generator
    that yields contextmanagers. See doctests below for example usage.

    :param retry_after: the delay in seconds between attempts

    :param retry_for: the timeout in seconds.

    :param retry_while: a callable with one argument, an instance of EC2ResponseError, returning
    True if another attempt should be made or False otherwise

    :return: a generator yielding contextmanagers

    Retry for a limited amount of time:
    >>> i = 0
    >>> for attempt in retry_ec2( retry_after=0, retry_for=.1, retry_while=true ):
    ...     with attempt:
    ...         i += 1
    ...         raise EC2ResponseError( 'foo', 'bar' )
    Traceback (most recent call last):
    ...
    EC2ResponseError: EC2ResponseError: foo bar
    <BLANKLINE>
    >>> i > 1
    True

    Do exactly one attempt:
    >>> i = 0
    >>> for attempt in retry_ec2( retry_for=0 ):
    ...     with attempt:
    ...         i += 1
    ...         raise EC2ResponseError( 'foo', 'bar' )
    Traceback (most recent call last):
    ...
    EC2ResponseError: EC2ResponseError: foo bar
    <BLANKLINE>
    >>> i
    1

    Don't retry on success
    >>> i = 0
    >>> for attempt in retry_ec2( retry_after=0, retry_for=.1, retry_while=true ):
    ...     with attempt:
    ...         i += 1
    >>> i
    1

    Don't retry on unless condition returns
    >>> i = 0
    >>> for attempt in retry_ec2( retry_after=0, retry_for=.1, retry_while=false ):
    ...     with attempt:
    ...         i += 1
    ...         raise EC2ResponseError( 'foo', 'bar' )
    Traceback (most recent call last):
    ...
    EC2ResponseError: EC2ResponseError: foo bar
    <BLANKLINE>
    >>> i
    1
    """
    if retry_for > 0:
        go = [ None ]

        @contextmanager
        def repeated_attempt( ):
            try:
                yield
            except EC2ResponseError as e:
                if time.time( ) + retry_after < expiration and retry_while( e ):
                    log.info(
                        '... got %s, trying again in %is ...' % ( e.error_code, retry_after ) )
                    time.sleep( retry_after )
                else:
                    raise
            else:
                go.pop( )

        expiration = time.time( ) + retry_for
        while go:
            yield repeated_attempt( )
    else:
        @contextmanager
        def single_attempt( ):
            yield

        yield single_attempt( )
