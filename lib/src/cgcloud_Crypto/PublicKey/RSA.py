# -*- coding: utf-8 -*-
#
#  PublicKey/RSA.py : RSA public key primitive
#
# Written in 2008 by Dwayne C. Litzenberger <dlitz@dlitz.net>
#
# ===================================================================
# The contents of this file are dedicated to the public domain.  To
# the extent that dedication to the public domain is not available,
# everyone is granted a worldwide, perpetual, royalty-free,
# non-exclusive license to exercise all rights associated with the
# contents of this file for any purpose whatsoever.
# No rights are reserved.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# ===================================================================

"""RSA public-key cryptography algorithm (signature and encryption).

RSA_ is the most widespread and used public key algorithm. Its security is
based on the difficulty of factoring large integers. The algorithm has
withstood attacks for 30 years, and it is therefore considered reasonably
secure for new designs.

The algorithm can be used for both confidentiality (encryption) and
authentication (digital signature). It is worth noting that signing and
decryption are significantly slower than verification and encryption.
The cryptograhic strength is primarily linked to the length of the modulus *n*.
In 2012, a sufficient length is deemed to be 2048 bits. For more information,
see the most recent ECRYPT_ report.

Both RSA ciphertext and RSA signature are as big as the modulus *n* (256
bytes if *n* is 2048 bit long).

This module provides facilities for generating fresh, new RSA keys, constructing
them from known components, exporting them, and importing them.

    >>> from cgcloud_Crypto.PublicKey import RSA
    >>>
    >>> key = RSA.generate(2048)
    >>> f = open('mykey.pem','w')
    >>> f.write(key.exportKey('PEM'))
    >>> f.close()
    ...
    >>> f = open('mykey.pem','r')
    >>> key = RSA.importKey(f.read())

Even though you may choose to  directly use the methods of an RSA key object
to perform the primitive cryptographic operations (e.g. `_RSAobj.encrypt`),
it is recommended to use one of the standardized schemes instead (like
`Crypto.Cipher.PKCS1_v1_5` or `Crypto.Signature.PKCS1_v1_5`).

.. _RSA: http://en.wikipedia.org/wiki/RSA_%28algorithm%29
.. _ECRYPT: http://www.ecrypt.eu.org/documents/D.SPA.17.pdf

:sort: generate,construct,importKey,error
"""

__revision__ = "$Id$"

__all__ = ['generate', 'construct', 'error', 'importKey', 'RSAImplementation',
    '_RSAobj', 'oid' , 'algorithmIdentifier' ]

import sys
if sys.version_info[0] == 2 and sys.version_info[1] == 1:
    from cgcloud_Crypto.Util.py21compat import *
from cgcloud_Crypto.Util.py3compat import *

from cgcloud_Crypto.Util.number import bytes_to_long, long_to_bytes

from cgcloud_Crypto.PublicKey import _slowmath
from cgcloud_Crypto.IO import PKCS8, PEM

from cgcloud_Crypto.Util.asn1 import *

import binascii
import struct

from cgcloud_Crypto.Util.number import inverse

try:
    from cgcloud_Crypto.PublicKey import _fastmath
except ImportError:
    _fastmath = None

def decode_der(obj_class, binstr):
    """Instantiate a DER object class, decode a DER binary string in it, and
    return the object."""
    der = obj_class()
    der.decode(binstr)
    return der

class _RSAobj():
    """Class defining an actual RSA key.

    :undocumented: __getstate__, __setstate__, __repr__, __getattr__
    """
    #: Dictionary of RSA parameters.
    #:
    #: A public key will only have the following entries:
    #:
    #:  - **n**, the modulus.
    #:  - **e**, the public exponent.
    #:
    #: A private key will also have:
    #:
    #:  - **d**, the private exponent.
    #:  - **p**, the first factor of n.
    #:  - **q**, the second factor of n.
    #:  - **u**, the CRT coefficient (1/p) mod q.
    keydata = ['n', 'e', 'd', 'p', 'q', 'u']

    def __init__(self, implementation, key, randfunc=None):
        self.implementation = implementation
        self.key = key
        # if randfunc is None:
        #     randfunc = Random.new().read
        # self._randfunc = randfunc

    def __getattr__(self, attrname):
        if attrname in self.keydata:
            # For backward compatibility, allow the user to get (not set) the
            # RSA key parameters directly from this object.
            return getattr(self.key, attrname)
        else:
            raise AttributeError("%s object has no %r attribute" % (self.__class__.__name__, attrname,))

    def has_private(self):
        return self.key.has_private()

    def size(self):
        return self.key.size()

    def can_blind(self):
        return True

    def can_encrypt(self):
        return True

    def can_sign(self):
        return True

    def publickey(self):
        return self.implementation.construct((self.key.n, self.key.e))

    def exportKey(self, format='PEM', passphrase=None, pkcs=1, protection=None):
        """Export this RSA key.

        :Parameters:
          format : string
            The format to use for wrapping the key:

            - *'DER'*. Binary encoding.
            - *'PEM'*. Textual encoding, done according to `RFC1421`_/`RFC1423`_.
            - *'OpenSSH'*. Textual encoding, done according to OpenSSH specification.
              Only suitable for public keys (not private keys).

          passphrase : string
            For private keys only. The pass phrase used for deriving the encryption
            key.

          pkcs : integer
            For *DER* and *PEM* format only.
            The PKCS standard to follow for assembling the components of the key.
            You have two choices:

            - **1** (default): the public key is embedded into
              an X.509 ``SubjectPublicKeyInfo`` DER SEQUENCE.
              The private key is embedded into a `PKCS#1`_
              ``RSAPrivateKey`` DER SEQUENCE.
            - **8**: the private key is embedded into a `PKCS#8`_
              ``PrivateKeyInfo`` DER SEQUENCE. This value cannot be used
              for public keys.

          protection : string
            The encryption scheme to use for protecting the private key.

            If ``None`` (default), the behavior depends on ``format``:

            - For *DER*, the *PBKDF2WithHMAC-SHA1AndDES-EDE3-CBC*
              scheme is used. The following operations are performed:

                1. A 16 byte Triple DES key is derived from the passphrase
                   using `Crypto.Protocol.KDF.PBKDF2` with 8 bytes salt,
                   and 1 000 iterations of `Crypto.Hash.HMAC`.
                2. The private key is encrypted using CBC.
                3. The encrypted key is encoded according to PKCS#8.

            - For *PEM*, the obsolete PEM encryption scheme is used.
              It is based on MD5 for key derivation, and Triple DES for encryption.

            Specifying a value for ``protection`` is only meaningful for PKCS#8
            (that is, ``pkcs=8``) and only if a pass phrase is present too.

            The supported schemes for PKCS#8 are listed in the
            `Crypto.IO.PKCS8` module (see ``wrap_algo`` parameter).

        :Return: A byte string with the encoded public or private half
          of the key.
        :Raise ValueError:
            When the format is unknown or when you try to encrypt a private
            key with *DER* format and PKCS#1.
        :attention:
            If you don't provide a pass phrase, the private key will be
            exported in the clear!

        .. _RFC1421:    http://www.ietf.org/rfc/rfc1421.txt
        .. _RFC1423:    http://www.ietf.org/rfc/rfc1423.txt
        .. _`PKCS#1`:   http://www.ietf.org/rfc/rfc3447.txt
        .. _`PKCS#8`:   http://www.ietf.org/rfc/rfc5208.txt
        """
        if passphrase is not None:
            passphrase = tobytes(passphrase)
        if format=='OpenSSH':
               eb = long_to_bytes(self.e)
               nb = long_to_bytes(self.n)
               if bord(eb[0]) & 0x80: eb=bchr(0x00)+eb
               if bord(nb[0]) & 0x80: nb=bchr(0x00)+nb
               keyparts = [ b('ssh-rsa'), eb, nb ]
               keystring = b('').join([ struct.pack(">I",len(kp))+kp for kp in keyparts])
               return b('ssh-rsa ')+binascii.b2a_base64(keystring)[:-1]

        # DER format is always used, even in case of PEM, which simply
        # encodes it into BASE64.
        if self.has_private():
                binary_key = newDerSequence(
                        0,
                        self.n,
                        self.e,
                        self.d,
                        self.p,
                        self.q,
                        self.d % (self.p-1),
                        self.d % (self.q-1),
                        inverse(self.q, self.p)
                    ).encode()
                if pkcs==1:
                    keyType = 'RSA PRIVATE'
                    if format=='DER' and passphrase:
                        raise ValueError("PKCS#1 private key cannot be encrypted")
                else: # PKCS#8
                    if format=='PEM' and protection is None:
                        keyType = 'PRIVATE'
                        binary_key = PKCS8.wrap(binary_key, oid, None)
                    else:
                        keyType = 'ENCRYPTED PRIVATE'
                        if not protection:
                            protection = 'PBKDF2WithHMAC-SHA1AndDES-EDE3-CBC'
                        binary_key = PKCS8.wrap(binary_key, oid, passphrase, protection)
                        passphrase = None
        else:
                keyType = "RSA PUBLIC"
                binary_key = newDerSequence(
                    algorithmIdentifier,
                    newDerBitString(
                        newDerSequence( self.n, self.e )
                        )
                    ).encode()
        if format=='DER':
            return binary_key
        if format=='PEM':
            pem_str = PEM.encode(binary_key, keyType+" KEY", passphrase, self._randfunc)
            return tobytes(pem_str)
        raise ValueError("Unknown key format '%s'. Cannot export the RSA key." % format)

class RSAImplementation(object):
    """
    An RSA key factory.

    This class is only internally used to implement the methods of the `Crypto.PublicKey.RSA` module.

    :sort: __init__,generate,construct,importKey
    :undocumented: _g*, _i*
    """

    def __init__(self, **kwargs):
        """Create a new RSA key factory.

        :Keywords:
         use_fast_math : bool
                                Specify which mathematic library to use:

                                - *None* (default). Use fastest math available.
                                - *True* . Use fast math.
                                - *False* . Use slow math.
         default_randfunc : callable
                                Specify how to collect random data:

                                - *None* (default). Use Random.new().read().
                                - not *None* . Use the specified function directly.
        :Raise RuntimeError:
            When **use_fast_math** =True but fast math is not available.
        """
        use_fast_math = kwargs.get('use_fast_math', None)
        if use_fast_math is None:   # Automatic
            if _fastmath is not None:
                self._math = _fastmath
            else:
                self._math = _slowmath

        elif use_fast_math:     # Explicitly select fast math
            if _fastmath is not None:
                self._math = _fastmath
            else:
                raise RuntimeError("fast math module not available")

        else:   # Explicitly select slow math
            self._math = _slowmath

        self.error = self._math.error

        self._default_randfunc = kwargs.get('default_randfunc', None)
        self._current_randfunc = None

    def construct(self, tup):
        """Construct an RSA key from a tuple of valid RSA components.

        The modulus **n** must be the product of two primes.
        The public exponent **e** must be odd and larger than 1.

        In case of a private key, the following equations must apply:

        - e != 1
        - p*q = n
        - e*d = 1 mod (p-1)(q-1)
        - p*u = 1 mod q

        :Parameters:
         tup : tuple
                    A tuple of long integers, with at least 2 and no
                    more than 6 items. The items come in the following order:

                    1. RSA modulus (n).
                    2. Public exponent (e).
                    3. Private exponent (d). Only required if the key is private.
                    4. First factor of n (p). Optional.
                    5. Second factor of n (q). Optional.
                    6. CRT coefficient, (1/p) mod q (u). Optional.
        
        :Return: An RSA key object (`_RSAobj`).
        """
        key = self._math.rsa_construct(*tup)
        return _RSAobj(self, key)

    def _importKeyDER(self, extern_key, passphrase=None):
        """Import an RSA key (public or private half), encoded in DER form."""

        try:

            der = decode_der(DerSequence, extern_key)

            # Try PKCS#1 first, for a private key
            if len(der) == 9 and der.hasOnlyInts() and der[0] == 0:
                # ASN.1 RSAPrivateKey element
                del der[6:]     # Remove d mod (p-1),
                                # d mod (q-1), and
                                # q^{-1} mod p
                der.append(inverse(der[4], der[5]))  # Add p^{-1} mod q
                del der[0]      # Remove version
                return self.construct(der[:])

            # Keep on trying PKCS#1, but now for a public key
            if len(der) == 2:
                try:
                    # The DER object is an RSAPublicKey SEQUENCE with
                    # two elements
                    if der.hasOnlyInts():
                        return self.construct(der[:])
                    # The DER object is a SubjectPublicKeyInfo SEQUENCE
                    # with two elements: an 'algorithmIdentifier' and a
                    # 'subjectPublicKey'BIT STRING.
                    # 'algorithmIdentifier' takes the value given at the
                    # module level.
                    # 'subjectPublicKey' encapsulates the actual ASN.1
                    # RSAPublicKey element.
                    if der[0] == algorithmIdentifier:
                        bitmap = decode_der(DerBitString, der[1])
                        rsaPub = decode_der(DerSequence, bitmap.value)
                        if len(rsaPub) == 2 and rsaPub.hasOnlyInts():
                            return self.construct(rsaPub[:])
                except (ValueError, EOFError):
                    pass

            # Try PKCS#8 (possibly encrypted)
            k = PKCS8.unwrap(extern_key, passphrase)
            if k[0] == oid:
                return self._importKeyDER(k[1], passphrase)

        except (ValueError, EOFError):
            pass

        raise ValueError("RSA key format is not supported")

    def importKey(self, extern_key, passphrase=None):
        """Import an RSA key (public or private half), encoded in standard
        form.

        :Parameter extern_key:
            The RSA key to import, encoded as a string.

            An RSA public key can be in any of the following formats:

            - X.509 ``subjectPublicKeyInfo`` DER SEQUENCE (binary or PEM
              encoding)
            - `PKCS#1`_ ``RSAPublicKey`` DER SEQUENCE (binary or PEM encoding)
            - OpenSSH (textual public key only)

            An RSA private key can be in any of the following formats:

            - PKCS#1 ``RSAPrivateKey`` DER SEQUENCE (binary or PEM encoding)
            - `PKCS#8`_ ``PrivateKeyInfo`` or ``EncryptedPrivateKeyInfo``
              DER SEQUENCE (binary or PEM encoding)
            - OpenSSH (textual public key only)

            For details about the PEM encoding, see `RFC1421`_/`RFC1423`_.

            The private key may be encrypted by means of a certain pass phrase
            either at the PEM level or at the PKCS#8 level.
        :Type extern_key: string

        :Parameter passphrase:
            In case of an encrypted private key, this is the pass phrase from
            which the decryption key is derived.
        :Type passphrase: string

        :Return: An RSA key object (`_RSAobj`).

        :Raise ValueError/IndexError/TypeError:
            When the given key cannot be parsed (possibly because the pass
            phrase is wrong).

        .. _RFC1421: http://www.ietf.org/rfc/rfc1421.txt
        .. _RFC1423: http://www.ietf.org/rfc/rfc1423.txt
        .. _`PKCS#1`: http://www.ietf.org/rfc/rfc3447.txt
        .. _`PKCS#8`: http://www.ietf.org/rfc/rfc5208.txt
        """
        extern_key = tobytes(extern_key)
        if passphrase is not None:
            passphrase = tobytes(passphrase)

        if extern_key.startswith(b('-----')):
            # This is probably a PEM encoded key.
            (der, marker, enc_flag) = PEM.decode(tostr(extern_key), passphrase)
            if enc_flag:
                passphrase = None
            return self._importKeyDER(der, passphrase)

        if extern_key.startswith(b('ssh-rsa ')):
                # This is probably an OpenSSH key
                keystring = binascii.a2b_base64(extern_key.split(b(' '))[1])
                keyparts = []
                while len(keystring) > 4:
                    l = struct.unpack(">I", keystring[:4])[0]
                    keyparts.append(keystring[4:4 + l])
                    keystring = keystring[4 + l:]
                e = bytes_to_long(keyparts[1])
                n = bytes_to_long(keyparts[2])
                return self.construct([n, e])

        if bord(extern_key[0]) == 0x30:
                # This is probably a DER encoded key
                return self._importKeyDER(extern_key, passphrase)

        raise ValueError("RSA key format is not supported")

#: `Object ID`_ for the RSA encryption algorithm. This OID often indicates
#: a generic RSA key, even when such key will be actually used for digital
#: signatures.
#:
#: .. _`Object ID`: http://www.alvestrand.no/objectid/1.2.840.113549.1.1.1.html
oid = "1.2.840.113549.1.1.1"

#: This is the standard DER object that qualifies a cryptographic algorithm
#: in ASN.1-based data structures (e.g. X.509 certificates).
algorithmIdentifier = DerSequence(
  [DerObjectId(oid).encode(),      # algorithm field
  DerNull().encode()]              # parameters field
  ).encode()
 
_impl = RSAImplementation()
#:
#: Construct an RSA key object from a tuple of valid RSA components.
#:
#: See `RSAImplementation.construct`.
#:
construct = _impl.construct
#:
#: Import an RSA key (public or private half), encoded in standard form.
#:
#: See `RSAImplementation.importKey`.
#:
importKey = _impl.importKey
error = _impl.error

# vim:set ts=4 sw=4 sts=4 expandtab:

