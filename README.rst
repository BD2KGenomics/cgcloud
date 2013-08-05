CGHub Cloud Utils (officially, cghub-cloud-utils) manages virtual machines in Amazon's Elastic
Compute Cloud. Each virtual machine (*box*) is automatically provisioned with operating system and
application software such that it can function in one of several predefined *roles*, e.g. as a
continuous integration server, for running tests or as a build server for creating
platform-specific builds of CGHub's client applications. Multiple boxes performing a variety of
roles can collaborate with each other inside a *namespace*. Cloud resources such as EC2
instances, volumes and images can be isolated from each other by using separate namespaces.

Quickstart
==========

To install cghub-cloud-utils, you need Python 2.7.x and `pip <http://www.pip-installer.org/en/latest/installing.html#installing-globally>`_::

   sudo pip install hg+https://bitbucket.org/cghub/cghub-cloud-utils/

At the moment, the project is hosted in a private repository on Bitbucket and you will be prompted
to enter your Bitbucket credentials.

The installer places the ``cgcloud`` executable on your PATH so should be able to invoke it now::

   cgcloud --help

Next, log into `Amazon's EC2 console
<https://console.aws.amazon.com/ec2/home?region=us-west-1#s=KeyPairs>`_ and register your SSH key
pair in a region of your choice (at the moment, CGHub uses the us-west-1 region). Ask your a CGHub
EC2 admin (Hannes or Paul) to setup an account in AWS for you. If you don't have a key pair yet,
create one using ``ssh-keygen`` and paste the contents of ``~/.ssh/id_rsa.pub into`` the EC2
console. As the name of the key pair, use your login name or the the part before the ``@`` in your
UCSC email address.

Create access keys on `Amazon's IAM console <https://console.aws.amazon.com/iam/home?#users>`_:

1. Select the row that represents yourself
2. Click the *Security Credentials* tab
3. Click *Manage Access Keys*
4. Click *Create Access Key*
5. Click *Show User Security Credentials*, leave the page open
6. Create ``~/.boto`` with the following contents

   ::

      [Credentials]
      aws_access_key_id = PASTE YOUR ACCESS KEY ID HERE
      aws_secret_access_key = PASTE YOUR SECRET ACCESS KEY HERE

7. Click *Close Window*

That's it.

Now, let's say we want to create the ``build-master``, i.e. the machine that runs the
Jenkins continuous integration server::

   cgcloud setup build-master -k YOUR_KEY_PAIR_NAME

SSH into the build master::

   cgcloud ssh build-master
   
This will SSH into the build master and setup a port forwarding to Jenkins' web UI. Point your
browser at http://localhost:8080/.

Uninstallation
==============

::

    sudo pip uninstall cghub-cloud-utils

Motivation
==========

TODO