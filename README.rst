The CGCloud project is aimed at automating the creation and management of
virtual machines (*instances*) and virtual machine images (*AMIs*) in Amazon
EC2. It belongs in the same family of tools as Puppet, Chef and Vagrant but its
closest of kin is probably Ansible because the VM setup is done via SSH,
keeping the VM on a short leash until it is fully set up. It shines when it
comes to managing a wide variety of guest Linux distributions. To customize an
AMI managed by CGCloud you write object-oriented Python code that utilizes
inheritance to organize VM definitions, also known as ``roles``.

Additionally, CGCloud maintains SSH keys on running instances. While EC2 only
supports specifying a single key when an instance is launched, CGCloud Core
allows you to manage multiple keys over the entire lifecycle of the VM. This
makes it easy to collaborate on EC2 instances within a team.

With CGCloud, virtual machine and other associated cloud resources such as EBS
volumes exist inside a *namespace* that. Cloud resources belonging to different
namespaces are logically separated from each other. Namespaces are typically
used to demarcate deployment environments (e.g. development, test, staging,
production) or to isolate experiments performed by different users.

CGCloud installs an agent in each VM. The agent is a daemon that performs
maintenance tasks such as keeping the list of authorized SSH keys up-to-date.
All agents listen on an SNS/SQS queue for management commands and execute them
close to real-time.

Prerequisites
=============

To install and use CGCloud, you need

* Python ≧ 2.7.x

* pip_

* Git_

* Mac OS X: Xcode_ and the `Xcode Command Line Tools`_ (needed during the
  installation of cgcloud-core for compiling the PyCrypto dependency)

.. _pip: https://pip.readthedocs.org/en/latest/installing.html
.. _Git: http://git-scm.com/
.. _Xcode: https://itunes.apple.com/us/app/xcode/id497799835?mt=12
.. _Xcode Command Line Tools: http://stackoverflow.com/questions/9329243/xcode-4-4-command-line-tools

Quick Start
===========

Installation
------------

Once the prerequisites are installed, use ``pip`` to install cgcloud-core::

   sudo pip install git+https://github.com/BD2KGenomics/cgcloud-core.git

If you get

::

   Could not find any downloads that satisfy the requirement cgcloud-...

try adding ``--process-dependency-links`` after ``install``. This is a known
`issue`_ with pip 1.5.x.

.. _issue: https://mail.python.org/pipermail/distutils-sig/2014-January/023453.html

If you get an error message during the installation of the ``lxml`` dependency,
you might have to install the ``libxml2`` and ``libxslt`` headers. On Ubuntu,
for example, run::

   apt-get install libxml2-dev libxslt-dev

The installer places the ``cgcloud`` executable on your ``PATH``. You should be
able to invoke it now::

   cgcloud --help
   
Configure Boto
--------------

Boto is the AWS client library for Python that CGCloud uses. If you've already
installed, correctly configured and successfully used Boto, you can probably
skip this step.

Ask your AWS admin to setup an IAM account in AWS for you and log into
`Amazon's EC2 console <https://console.aws.amazon.com/ec2/>`_.

Go to the IAM console (see main menu, under Services) and create an
access key:

1. Select the row representing your IAM account
2. Click the *Security Credentials* tab
3. Click *Manage Access Keys*
4. Click *Create Access Key*
5. Click *Show User Security Credentials*, leave the page open
6. Create ``~/.boto`` with the following contents::

      [Credentials]
      aws_access_key_id = PASTE YOUR ACCESS KEY ID HERE
      aws_secret_access_key = PASTE YOUR SECRET ACCESS KEY HERE

7. Click *Close Window*

Register your public SSH key
----------------------------

Note: This step is not the same as registering your key pair with EC2. In order
to be able to manage the team members' public SSH keys, CGCloud needs to know
the contents of the public key pair. EC2 only exposes the fingerprint via its
REST API, not the actual key. For this purpose, CGCloud maintains public keys
in a special S3 bucket. The following procedure registers your public key with
S3 *and* uploads it to that S3 bucket.

Register your SSH key in EC2 and S3 by running::

    cgcloud register-key ~/.ssh/id_rsa.pub

The above command uploads the given public key to EC2 and S3 and sets the name
of the key pair in EC2 to your IAM user account name. In S3 your public key
will be stored under its fingerprint. If you don't have an SSH key, you can
create one using the ``ssh-keygen`` command.

Start your first box
--------------------

That's it, you're ready to create your first *box*, i.e. EC2 instance or VM:

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
disambiguate by specifying an ordinal. Use ``cgcloud list`` to view all running
instances and their ordinals.

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
---------------------

While creating an image is a viable mechanism to preserve manual modifications
to a box, it is not the best possible way. The problem with it is that you will
be stuck with the base image release the box was created from. You will also be
stuck at whatever customizations specified by the role in the version of
``cgcloud create`` you were using. If either the base image or the role
definition in CGCloud is updated, you will not benefit from those updates.
Therefore, the preferred way of customizing a box is by *scripting* the
customizations. This is typically done by creating a CGCloud plugin, i.e. a
Python package with VM definitions aka ``roles``. A role is a subclass of the
Box class while a box (aka VM aka EC2 instance) is an instance of that class.
The workhorse design pattern formed by the Box class is *Template Method*.

Creating an image makes sense even if you didn't make any modifications after
``cgcloud create``. It captures all role-specific customizations made by
``cgcloud create``, thereby protecting them from changes in the role
definition, the underlying base image and package updates in the Linux
distribution used by the box. This is key to CGCloud's philosophy: It gives you
a way to *create* an up-to-date image with all the latest software according to
your requirements **and** it allows you reliably reproduce the exact result of
that step. The fact that ``recreate`` is much faster than ``create`` is icing
on the cake.
