The CGCloud project is aimed at automating the creation and management of
virtual machines (*instances*) and virtual machine images (*AMIs*) in Amazon
EC2. Additionally, CGCloud maintains SSH keys on running instances—not just
the one-time injection of a single key at launch time, but the continuous, near
real-time management of a configurable set of keys for a fleet of instances.

CGCloud can group instances, AMIs and other related cloud resources such as EBS
volumes in isolated namespaces. Each user can have their own namespace or all
users can share a root namespace. The production, test and staging environments
can coexist in separate namespaces, all within one EC2 region.

CGCloud can be extended with plugins. There is a plugin for setting up a
continuous integration environment consisting of a continually running Jenkins
master and several Jenkins slaves that are launched on demand. There also is a
plugin for quickly creating large Apache Spark clusters.

Prerequisites
=============

To install and use CGCloud, you need

* Python ≧ 2.7.x

* pip_ and virtualenv_

* Git_

* Mac OS X: Xcode_ and the `Xcode Command Line Tools`_ (needed during the
  installation of cgcloud-core for compiling the PyCrypto dependency)

.. _pip: https://pip.readthedocs.org/en/latest/installing.html
.. _virtualenv: https://virtualenv.pypa.io/en/latest/installation.html
.. _Git: http://git-scm.com/
.. _Xcode: https://itunes.apple.com/us/app/xcode/id497799835?mt=12
.. _Xcode Command Line Tools: http://stackoverflow.com/questions/9329243/xcode-4-4-command-line-tools

Installation
============

Read the entire section before pasting any commands and ensure that all
prerequisites are installed. It is recommended to install CGCloud into a
virtualenv. Create a virtualenv and use ``pip`` to install
the ``cgcloud-core`` package::

   virtualenv cgcloud
   source cgcloud/bin/activate
   pip install cgcloud-core

If you get an error about ``yaml.h`` being missing you may need to install
libyaml (via HomeBrew on OS X) or libyaml-dev (via apt-get or yum on Linux).

If you get::

   AttributeError: 'tuple' object has no attribute 'is_prerelease'

you may need to upgrade setuptools::

   sudo pip install --upgrade setuptools

If, on Mountain Lion, you get::

   clang: error: unknown argument: '-mno-fused-madd' [-Wunused-command-line-argument-hard-error-in-future]
   clang: note: this will be a hard error (cannot be downgraded to a warning) in the future
   error: command 'clang' failed with exit status 1

try the following work-around::
   
   export CFLAGS=-Qunused-arguments
   export CPPFLAGS=-Qunused-arguments

The installer places the ``cgcloud`` executable into the ``bin`` directory of
the virtualenv or, if you didn't create a virtualenv for cgcloud, into a
directory on your ``PATH``. You should be able to invoke it now::

   cgcloud --help

Configuration
=============

Access keys
-----------

Ask your AWS admin to setup an IAM account in AWS for you. Log into Amazon's
IAM console and generate an `access key`_ for yourself. While your IAM username
and password are used to authenticate yourself for interactive use via the AWS
console, the access key is used for programmatic access via ``cgcloud``.

Once you have an access key, create ``~/.boto`` on you local computer with the
following contents::

   [Credentials]
   aws_access_key_id = PASTE_YOUR_ACCESS_KEY_ID_HERE
   aws_secret_access_key = PASTE_YOUR_SECRET_ACCESS_KEY_HERE
   
.. _access key: http://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSGettingStartedGuide/AWSCredentials.html

EC2 region and availability zone
--------------------------------

Edit your ``~/.profile`` or ``~/.bash_profile`` and add the following line::

   export CGCLOUD_ZONE=us-west-2a
   
This configures both the region ``us-west-2`` and the availability zone within
that region: ``a``. Instead of ``us-west-2a`` you could use ``us-east-1a`` or
any other zone in any other EC2 region.

Public SSH key
--------------
If you don't have an
SSH key, you can create one using the ``ssh-keygen`` command.

Register your SSH key in EC2 by running::

   cgcloud register-key ~/.ssh/id_rsa.pub

The above command imports the given public key to EC2 as a key pair (I know,
the terminology is confusing) but also uploads it to S3, see next paragraph for
an explanation. The name of the key pair in EC2 will be set to your IAM user
account name. In S3 the public key will be stored under its fingerprint.

Note: Importing your key pair using the EC2 console is not equivalent to
``cgcloud register-key`` . In order to be able to manage key pairs within a
team, CGCloud needs to know the contents of the public key for every team
member's key pair. But EC2 only exposes a fingerprint via its REST API, not the
actual public key. For this purpose, CGCloud maintains those public keys in a
special S3 bucket. Using ``cgcloud register-key`` makes sure that the public
key is imported to EC2 *and* uploaded to that special S3 bucket. Also note that
while that S3 bucket is globally visible and the public keys stored therein
apply across regions, the corresponding key pair in EC2 is only visible within
a zone. So when you switch to a different region, you will have to use
``cgcloud register-key`` again to import the key pair into that EC2 region.

Multi-user SSH logins
---------------------

By default, CGCloud only injects your public key into the boxes that it
creates. This means that only you can SSH into those boxes. If you want other
people to be able to SSH into boxes created by you, you can specify a list of
key pairs to be injected into boxes. You can do so as using the ``-k`` command
line option to ``cgcloud create`` or by setting the ``CGCLOUD_KEYPAIRS``
environment variable. The latter will inject those key pairs by default into
every box that you create. The default for ``-k`` is the special string
``__me__`` which is substituted with the name of the current IAM user. This
only works your IAM user account and your SSH key pair in EC2 have the same
name, a practice that is highly recommended. The ``cgcloud register-key``
command follows that convention by default.

The most useful shortcut for ``-k`` and ``CGCLOUD_KEYPAIRS`` however is to list
the name of an IAM group by prefixing the group name with ``@@``. Assuming that
there exists an IAM group called ``developers``, adding the following line to
your ``.profile`` or ``.bash_profile``::

   export CGCLOUD_KEYPAIRS="__me__ @@developers"

will inject your own key pair and the key pair of every user in the
``developers`` IAM group into every box that you create. Obviously, this only
works if EC2 key pairs and IAM usernames are identical. If a user is removed
from the IAM group or their key pair deleted from EC2, and within minutes his
or her key pair will automatically be removed from every box that is running
the agent. Unless you specifically tell CGCloud not to, it installs the agent
on boxes by default.

First steps
===========

You're now ready to create your first *box* aka EC2 instance or VM::

   cgcloud create generic-ubuntu-trusty-box

This creates a Ubuntu Trusty instance from a stock Ubuntu AMI and then further
customizes it by running additional commands via SSH. It'll take a few minutes.
The ``generic-ubuntu-trusty-box`` argument denotes a *role*, i.e. a blueprint
for an instance. You can use ``cgcloud list-roles`` to see the available roles.

Now login to the newly created box::

   cgcloud ssh generic-ubuntu-trusty-box

The astute reader will notice that it is not necessary to remember the public
hostname assigned to the box. As long as there is only one box per role, you
can refer to the box by using the role's name. Otherwise you will need to
disambiguate by specifying an ordinal using the ``-o`` option. Use ``cgcloud
list`` to view all running instances and their ordinals.

Also note that it isn't necessary to specify the account name of the
administrative user to log in as, e.g. ``ec2-user``, ``root`` or ``ubuntu`` .
The stock images for the various Linux distributions use different account
names but CGCloud conveniently hides these differences.

In order to copy files to and from the box you can use ``cgcloud rsync``::

   cgcloud rsync generic-ubuntu-trusty-box -av ~/mystuff :
   
The ``cgcloud rsync`` command behaves like a prefix to the ``rsync`` command
with one important difference: With rsync you would specify the remote hostname
followed by a colon, with ``cgcloud rsync`` you simply leave the hostname blank
and only specify a colon followed by the remote path. If you omit the remote
path, the home directory of the administrative user will be used.

You can now stop the box with ``cgcloud stop``, start it again using ``cgcloud
start`` or terminate it using ``cgcloud terminate``. Note while a stopped
instance is much cheaper than a running instance, it is not free. Only the
``terminate`` command will reduce the operating cost incurred by the instance
to zero. 

If you want to preserve the modifications you made to the box such that you can
spawn another box in the future just like it, stop the box and then create an
image of it using the ``cgcloud image`` command. You may then use the ``cgcloud
recreate`` command to bring up a box.

Philosophical remarks
=====================

While creating an image is a viable mechanism to preserve manual modifications
to a box, it is not the best possible way. The problem with it is that you will
be stuck with the base image release the box was created from. You will also be
stuck with the customizations performed by the particular version of
``cgcloud`` you were using. If either the base image or the role definition in
CGCloud is updated, you will not benefit from those updates. Therefore, the
preferred way of customizing a box is by *scripting* the customizations. This
is typically done by creating a CGCloud plugin, i.e. a Python package with VM
definitions aka ``roles``. A role is a subclass of the Box class while a box
(aka VM aka EC2 instance) is an instance of that class. The prominent design
patterns formed by Box and its derived classes are *Template Method* and
*Mix-in*. The mix-in pattern introduces a sensitivity to Python's method
resolution order so you need to be aware of that.

Creating an image makes sense even if you didn't make any modifications after
``cgcloud create``. It captures all role-specific customizations made by
``cgcloud create``, thereby protecting them from changes in the role
definition, the underlying base image and package updates in the Linux
distribution used by the box. This is key to CGCloud's philosophy: It gives you
a way to *create* an up-to-date image with all the latest software according to
your requirements **and** it allows you reliably reproduce the exact result of
that step. The fact that ``recreate`` is much faster than ``create`` is icing
on the cake.


Building & Testing
==================

First, clone this repository and ``cd`` into it. To run the tests use

* ``python setup.py nosetests --with-doctest``,
* ``python setup.py test``,
* ``nosetest`` or
* ``python -m unittest discover -s src``.

We prefer the way listed first as it installs all requirements **and** runs the
tests under Nose, a test runner superior to ``unittest`` that can run tests in
parallel and produces Xunit-like test reports. For example, on continuous
integration we use

::

   virtualenv env
   env/bin/python setup.py nosetests --processes=16 --process-timeout=900

To make an editable_ install, also known as *development mode*, use ``python
setup.py develop``. To remove the editable install ``python setup.py develop
-u``.

.. _editable: http://pythonhosted.org//setuptools/setuptools.html#development-mode

Troubleshooting
===============

If you get the following error::

   ERROR: Exception: Incompatible ssh peer (no acceptable kex algorithm)
   ERROR: Traceback (most recent call last):
   ERROR:   File "/usr/local/lib/python2.7/site-packages/paramiko/transport.py", line 1585, in run
   ERROR:     self._handler_table[ptype](self, m)
   ERROR:   File "/usr/local/lib/python2.7/site-packages/paramiko/transport.py", line 1664, in _negotiate_keys
   ERROR:     self._parse_kex_init(m)
   ERROR:   File "/usr/local/lib/python2.7/site-packages/paramiko/transport.py", line 1779, in _parse_kex_init
   ERROR:     raise SSHException('Incompatible ssh peer (no acceptable kex algorithm)')
   ERROR: SSHException: Incompatible ssh peer (no acceptable kex algorithm)

try upgrading paramiko::

   pip install --upgrade paramiko
   
See also https://github.com/fabric/fabric/issues/1212
