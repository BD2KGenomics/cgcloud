The CGhub Cloud Core project is aimed at automating the creation and management
of VMs and VM images in Amazon EC2. It belongs in the same family of tools such
as Puppet, Chef and Vagrant but it's closest of kin is probably Ansible because
the VM setup is done via SSH, keeping the VM on a short leash until it is fully
set up. It shines when it comes to managing a wide variety of guest
distributions. To customize a VM image managed by cghub-cloud-core you
object-oriented Python code that utilizes inheritance to organize VM
definitions. 

CGhub Cloud Core maintains SSH keys on running instances. Where EC2 only
supports specifying a single key when an instance is launched, CGhub Cloud Core
allows you to manage multiple keys over the entire lifecycle of the VM.

Multiple VMs performing a variety of roles collaborate with each other inside a
*namespace*. Cloud resources such as EC2 instances, volumes and images
belonging to different namespaces are logically separated from each other.
Namespaces are typically used to demarcate deployment environments (e.g.
development, test, staging, production) or to isolate experiments performed by
different users.

The CGHub Cloud Core installs an agent in each VM. The agent is a daemon that
performs maintenance tasks such as keeping the list of authorized SSH keys
up-to-date. All agents listen on an SNS/SQS queue for management commands and
execute them close to real time.

Prerequisites
=============

To install and use cghub-cloud-core, you need

* Python ≧ 2.7.x

* pip_

* Git_

* Mac OS X: Xcode_ and the `Xcode Command Line Tools`_ (needed during the
  installation of cghub-cloud-core for compiling the PyCrypto dependency)

.. _pip: https://pip.readthedocs.org/en/latest/installing.html
.. _Git: http://git-scm.com/
.. _Xcode: https://itunes.apple.com/us/app/xcode/id497799835?mt=12
.. _Xcode Command Line Tools: http://stackoverflow.com/questions/9329243/xcode-4-4-command-line-tools

Quick Start
===========

Once the prerequisites are installed, use ``pip`` to install cghub-cloud-core::

   sudo pip install git+ssh://git@bitbucket.org/cghub/cghub-cloud-core

If you get

   ::

      Could not find any downloads that satisfy the requirement cghub-cloud-...

try adding ``--process-dependency-links`` after ``install``. This is a known
`issue`_ with pip 1.5.x.

.. _issue: https://mail.python.org/pipermail/distutils-sig/2014-January/023453.html

If you get an error message during the installation of the ``lxml`` dependency,
you might have to install the ``libxml2`` and ``libxslt`` headers. On Ubuntu,
for example, run::

   apt-get install libxml2-dev libxslt-dev

The installer places the ``cgcloud`` executable on your PATH. You should be
able to invoke it now::

   cgcloud --help

Ask your AWS admin to setup an IAM account in AWS for you and log into
`Amazon's EC2 console <https://console.aws.amazon.com/ec2/>`_. CGHubbies should
use `this link <https://cghub.signin.aws.amazon.com/console/>`_ instead.

Next, go to the IAM console (see main menu, under Services) and create an
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

Register your SSH key in EC2 by running::

    cgcloud register-key -k $(whoami) ~/.ssh/id_rsa.pub

If you don't have an SSH key, you can create one using the ``ssh-keygen``
command.

.. important:: Many people who don't understand how SSH is supposed to be used,
   create a key on every system they log into. This is extremely unsafe. There
   should only be a single key identifying you. I sometimes use one key per
   persona, e.g. a key for my personal activities and additionally, one key per
   employer. Furthermore, that private key should only reside on a machine that
   you control physical access too. And the private key must be protected by a
   passphrase that is either memorized or stored in a password vault.

Note that the above command uses your current login to name the key pair. You
might want to substitute ``$(whoami)``with a different name. Consider using the
local part of your email address, i.e. the part before the ``@``.

That's it, you're ready to create your first VM, aka *box*:

   export CGCLOUD_NAMESPACE=/$(whoami)/
   export CGCLOUD_KEYPAIRS=$(whoami)
   cgcloud create generic-ubuntu-trusty-box

This will create a Ubuntu Trusty VM from scratch by starting a stock Ubuntu VM
and then further customizing the VM by running additional commands via SSH. 

Login to the newly created VM::

   cgcloud ssh generic-ubuntu-trusty-box

The astute reader will notice that it is not necessary to remember the public
hostname assigned to the box. As long as there is only one box per role, you
can refer to the box by using the role's name. Also note it isn't necessary to
specify the account name of the administrative user to log in as. The stock
images for the various Linux distributions use different account names but
cgcloud conveniently hides these differences.

Use ``cgcloud rsync`` to copy files to the
box::

   cgcloud rsync generic-ubuntu-trusty-box -av ~/mystuff :
   
The ``cgcloud rsync`` command behaves like a prefix to the ``rsync`` command
with one important difference: While with rsync you would specify the remote
hostname followed by a colon, with ``cgcloud rsync`` simply leave the hostname
blank and just type a colon.

You can now stop the box with ``cgcloud stop``, start it again using ``cgcloud
start`` or terminate it using ``cgcloud terminate``. Note while a stopped
instance is much cheaper than a running instance, it is not free. Only the
``terminate`` command will reduce the operating cost incurred by the instance
to zero. 

If you want to preserve the modifications you made to the box such that you can
spawn another box in the future just like it, stop the box and then create an
image of it using the ``cgcloud image`` command. You may then use the ``cgcloud recreate`` command to bring up a box.

.. note::

   While creating an image is a viable mechanism to preserve manual
   modifications to a box, it is not the best possible way. The problem with it
   is that you will be stuck with the version of the base image the box was
   created from. You will also be stuck at whatever customizations were
   performed by the version of ``cgcloud create`` you were using. If either the
   base image or cgcloud is updated, you will not benefit from those updates.
   Therefore, the preferred way of customizing an instance is by *scripting*
   them. This is typically done by creating a plugin to cgcloud. A plugin is a
   Python package with VM definitions. A VM definition is a subclass of the Box
   class. The workhorse design pattern formed by the Box class is *Template
   Method*.

Uninstallation
==============

::

    sudo pip uninstall cghub-cloud-core

