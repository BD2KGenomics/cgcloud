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

Now, let's say we want to create the ``jenkins-master``, i.e. the machine that runs the
Jenkins continuous integration server::

   cgcloud create jenkins-master -k YOUR_KEY_PAIR_NAME

SSH into the build master::

   cgcloud ssh jenkins-master
   
This will SSH into the master and setup a port forwarding to Jenkins' web UI. Point your
browser at http://localhost:8080/.

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

* you completed the quick start
* you have an account on Bitbucket
* you registered your SSH public key on Bitbucket
* your Bitbucket account is member of the *cghub* team on Bitbucket
* have nothing listening on port 8080 locally

Select a cgcloud namespace and list the SSH keys to be injected into the boxes::

   export CGCLOUD_NAMESPACE=/
   export CGCLOUD_KEYPAIRS="hannes cwilks markd"

This means that we will be working in the root namespace and that we and our two esteemed colleagues should be able to SSH into the boxes. Our own key pair must be listed first, as the primary key pair. If you just want walk through this tutorial without affecting the root namespace, set CGCLOUD_NAMESPACE to an arbitrary value that is unlikely to be used by anyone else::

   export CGCLOUD_NAMESPACE=hannes

Creating the CI master
----------------------

Create the Jenkins master instance:

   cgcloud create jenkins-master
   
For fun, SSH into the master as the administrative user::

   cgcloud ssh jenkins-master
   exit
   
The administrative user has ``sudo`` privileges. Its name varies from platform to platform but cgcloud keeps track of that for you. For even more fun, SSH into the master as the *jenkins* user::

   cgcloud ssh jenkins-master -l jenkins
   
This is the user that the Jenkins server runs as. 

This is possibly not the first time that a ``jenkins-master`` box is created in the root namespace. If a ``jenkins-master`` box existed in the root namespace before, the volume containing all of Jenkins' data (configurations, build plans, build output, etc.) will still be around unless someone deleted it of course. Creating a ``jenkins-master`` in a namespace will reuse the ``jenkins-data`` volume in that namespace if it already exists. If it doesn't, it will be automatically created. You may skip to :ref:`creating-slaves`.

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

We can't just use ``git clone`` since we want to merge the repository contents with the current local directory rather than completely wiping the local directory which ``git clone`` would have us do.

If you skip this step, Jenkins will run with its default, empty configuration and you will have to configure the various build plans for GeneTorrent yourself. TODO: Setting up Jenkins from scratch should be documented, but somewhere else.

Start Jenkins again::

   cgcloud ssh jenkins-master
   sudo /etc/init.d/jenkins start
   exit

.. _creating-slaves:

Creating The Slaves
-------------------

SSH into the master as the ``jenkins`` user again::

   cgcloud ssh jenkins-master -l jenkins
   
Then point your browser at Jenkins' web UI at http://localhost:8080/. The ``cgcloud ssh jenkins-master`` command automatically opens a local port forwarding to Jenkins' web server.

Open a new shell window and create the first slave::

   cgcloud list-roles
   cgcloud create centos5-genetorrent-jenkins-slave
   
SSH into it and look around. Notice how the builds directory in the Jenkins user's home is symbolically linked to ephemeral storage::

   cgcloud ssh centos5-genetorrent-jenkins-slave
   sudo whoami
   git --version
   sudo ls -l ~jenkins
   exit

Now stop, image and terminate the box::

   cgcloud stop centos5-genetorrent-jenkins-slave
   cgcloud create-image centos5-genetorrent-jenkins-slave
   cgcloud terminate centos5-genetorrent-jenkins-slave

The ``create-image`` command prints an XML fragment of Jenkins configuration. Paste that fragment
into Jenkins' ``config.xml``::

    cgcloud ssh jenkins-master -l jenkins
    vim config.xml

Then in the Jenkins web UI, click *Manage Jenkins* and *Reload Configuration from Disk**.

    ::

        exit

Alternatively, add the slave via the Jenkins UI directly, if, for example, you know that only the
AMI ID has changed but the rest of the slave configuration stayed the same:

1. Click *Manage Jenkins*
2. Click *Configure System*
3. Scroll down to the *Cloud* section
4. Make the necessary changes interactively

The *Description* field of each AMI section should be set to the role name, e.g.
``centos5-genetorrent-jenkins-slave``. If this is a new slave role, say, for a new platform, add a
new AMI to the Jenkins configuration using an existing AMI as the template. Make sure you click the
*Advanced* button to reveal all fields.

Repeat this for all other slaves::

   for slave in $(./cgcloud list-roles | grep jenkins-slave | grep -v centos5-genetorrent-jenkins-slave); do
       cgcloud create $slave --image --terminate
   done

Note how the above command makes use of the ``--image`` and ``--terminate`` options to combine the creation of a box with image creation and termination into a single command.



Image master, too

