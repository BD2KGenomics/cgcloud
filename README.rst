CGHub Cloud Utils (officially, cghub-cloud-utils) manages virtual machines in Amazon's Elastic
Compute Cloud. Each virtual machine (*box*) is automatically provisioned with operating system and
application software such that it can function in one of several predefined *roles*, e.g. as a
continuous integration server, for running tests or as a build server for creating platform-specific
builds of CGHub's client applications. Multiple boxes performing a variety of roles can collaborate
with each other inside a *namespace*. Cloud resources such as EC2 instances, volumes and images can
be isolated from each other by using separate namespaces.

Quickstart
==========

To install and use cghub-cloud-utils, you need

* Python ≧ 2.7.x
* pip_
* Mercurial_ (``hg``)
* Mac OS X: Xcode_ and the `_Xcode Command Line Tools`_ (needed during the installation of cghub-cloud-utils for compiling the PyCrypto dependency)
* A Bitbucket account and membership in the ``cghub`` (see steps 1 and 2 of our `Bitbucket Guide`_) * Your public SSH key registered in Bitbucket (see steps 3 and 4 of our `Bitbucket Guide`_)

.. _pip: https://pip.readthedocs.org/en/latest/installing.html
.. _Mercurial: http://mercurial.selenic.com/
.. _Xcode: https://itunes.apple.com/us/app/xcode/id497799835?mt=12
.. _Xcode Command Line Tools: http://stackoverflow.com/questions/9329243/xcode-4-4-command-line-tools
.. _Bitbucket Guide: http://cgwiki.soe.ucsc.edu/index.php/Bitbucket_Repositories

Once those are installed, use ``pip`` to install cghub-cloud-utils::

   sudo pip install hg+ssh://bitbucket.org/cghub/cghub-cloud-utils/

At the moment, the project is hosted in a *private* repository on Bitbucket, meaning that you will
be asked to enter your Bitbucket credentials.

If you get an error message during the installation of the ``lxml`` dependency, you might have to install the ``libxml2`` and ``libxslt`` headers. On Ubuntu, for example, run::

   apt-get install libxml2-dev libxslt-dev

The installer places the ``cgcloud`` executable on your PATH. You should be able to invoke it now::

   cgcloud --help

Ask your EC2 admin to setup an IAM account in AWS for you and log into `Amazon's EC2 console
<https://console.aws.amazon.com/ec2/>`_

Create access keys on `Amazon's IAM console <https://console.aws.amazon.com/iam/home?#users>`_:

TODO: need to update links to point to cghub account

1. Select the row representing your IAM account
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

Register your SSH key in EC2 by running::

    cgcloud upload-key -k $(whoami) ~/.ssh/id_rsa.pub


TODO: Mention ssh-keygen

Note that the above command uses your current login to name the key pair. You might want to
substitute ``$(whoami)``with a different name. Consider using the local part of your email address,
i.e. the part before the ``@``. Please be aware that in addition to uploading your SSH public key to EC2, the above command also creates an S3 key in a bucket that is readable to all admins in the CGHub AWS account as well as the IAM account used by Jenkins.

That's it.

Now, let's say we want to create the ``jenkins-master``, i.e. the machine that runs the
Jenkins continuous integration server::

   export CGCLOUD_NAMESPACE=$(whoami)
   export CGCLOUD_KEYPAIRS=$(whoami)
   cgcloud create jenkins-master

SSH into the build master::

   cgcloud ssh jenkins-master

This will SSH into the master and setup a port forwarding to Jenkins' web UI. Point your
browser at http://localhost:8080/ and start exploring Jenkins.

Uninstallation
==============

::

    sudo pip uninstall cghub-cloud-utils

Motivation
==========

TODO

Tutorial
========

In this tutorial we'll create an continuous integration environment for GeneTorrent consisting of a Jenkins master and several slaves, one slave for each target platform of GeneTorrent. The tutorial assumes that 

* You completed the quick start
* You have an account on Bitbucket
* You registered your SSH public key on Bitbucket
* Your Bitbucket account is member of the *cghub* team on Bitbucket
* You have nothing listening on port 8080 locally

Select a cgcloud namespace and list the SSH keys to be injected into the boxes::

   export CGCLOUD_NAMESPACE=/
   export CGCLOUD_KEYPAIRS="hannes cwilks markd"

This means that we will be working in the root namespace and that we and our two esteemed
colleagues should be able to SSH into the boxes. The name of our own key pair must be listed first,
as the primary key pair. If you'd rather walk through this tutorial without affecting the root
namespace (and thereby risking interference with other team members), set ``CGCLOUD_NAMESPACE`` to a value unlikely to be used by anyone else::

   export CGCLOUD_NAMESPACE=$(whoami)

Creating The Continuous Integration Master
------------------------------------------

Create the Jenkins master instance::

   cgcloud create jenkins-master
   
As a test, SSH into the master as the administrative user::

   cgcloud ssh jenkins-master
   exit
   
The administrative user has ``sudo`` privileges. Its name varies from platform to platform but
cgcloud keeps track of that for you. For yet another test, SSH into the master as the *jenkins*
user::

   cgcloud ssh jenkins-master -l jenkins
   
This is the user that the Jenkins server runs as. 

This is possibly not the first time that a ``jenkins-master`` box is created in the
$CGCLOUD_NAMESPACE namespace. If a ``jenkins-master`` box existed in that namespace before, the
volume containing all of Jenkins' data (configurations, build plans, build output, etc.) will still
be around. That is, unless someone deleted it, of course. Creating a ``jenkins-master`` in a
namespace will reuse the ``jenkins-data`` volume from that namespace if it already exists. If it
doesn't, it will be automatically created and you will have to setup Jenkins from scratch. Otherwisem, you should skip ahead to :ref:`creating-slaves`.

Setting Up Jenkins
------------------

Jenkins needs checkout access to the source code repositories so we need to tell BitBucket about the *jenkins* user's public key::

   cat ~/.ssh/id_rsa.pub
   exit
   
Paste the key as a *Deployment key* (under the repository settings) for the GeneTorrent, GeneTorrent Build and Jenkins Config repositories. Our recommended naming convention for deployment keys, and cgcloud keys in general, is ``user@namespace/role`` so we should use ``jenkins@/jenkins-master`` as the name of the deployment key in Bitbucket.

Stop Jenkins and checkout the Jenkins configuration from Bitbucket::

   cgcloud ssh jenkins-master
   sudo /etc/init.d/jenkins stop
   exit
   cgcloud ssh jenkins-master -l jenkins
   git init .
   git remote add -t \* -f origin git@bitbucket.org:cghub/jenkins-config.git
   git checkout -f master
   exit

We can't just use ``git clone`` since we want to merge the repository contents with the current
local directory rather than completely wiping the local directory as ``git clone`` would have us do.

If you skip this step, Jenkins will run with its default, empty configuration and you will have to
configure the various build plans for GeneTorrent yourself.

TODO: Setting up Jenkins from scratch should be documented, but somewhere else.

Start Jenkins again::

   cgcloud ssh jenkins-master
   sudo /etc/init.d/jenkins start
   exit

.. _creating-slaves:

Creating The Continuous Integration Slaves
------------------------------------------

A slave is a box that is used by the master to run builds on. GeneTorrent needs to be built on various platforms, for each of which we will have to create a slave.

SSH into the master as the ``jenkins`` user::

   cgcloud ssh jenkins-master -l jenkins
   
Then point your browser at Jenkins' web UI at http://localhost:8080/. The ``cgcloud ssh
jenkins-master`` command automatically opens a local port forwarding to Jenkins' web server.

Open a new shell window and create the first slave::

   cgcloud list-roles
   cgcloud create centos5-genetorrent-jenkins-slave
   
SSH into it::

   cgcloud ssh centos5-genetorrent-jenkins-slave

Notice that 

 * The admin user has sudo rights::
 
    sudo whoami
 
 * The builds directory in the Jenkins user's home is symbolically linked to ephemeral
   storage::
   
         sudo ls -l ~jenkins
   
 * git is installed::
   
      git --version
      exit

Now stop, image and terminate the box::

   cgcloud stop centos5-genetorrent-jenkins-slave
   cgcloud image centos5-genetorrent-jenkins-slave
   cgcloud terminate centos5-genetorrent-jenkins-slave
   cgcloud register-slaves jenkins-master centos5-genetorrent-jenkins-slave

The ``register-slaves`` command adds a section to Jenkins' config.xml that tells Jenkins how to
spawn an instance of this slave from the image we just created. To put that change into effect,

::
   
      cgcloud ssh jenkins-master -l jenkins

and click *Manage Jenkins* in the Jenkins web UI and *Reload Configuration from Disk**.

Repeat this for all other slaves::

   for slave in $(./cgcloud list-roles | grep jenkins-slave | grep -v centos5-genetorrent-jenkins-slave); do
       cgcloud create $slave --image --terminate
   done

Note how the above command makes use of the ``--image`` and ``--terminate`` options to combine the creation of a box with image creation and termination into a single command.
