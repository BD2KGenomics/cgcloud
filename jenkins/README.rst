The CGCloud Jenkins project contains the roles for running a distributed
continuous integration environment in EC2 with one Jenkins master VM and
multiple slave VMs. A Jenkins slave is a machine that the master delegates
builds to. Slaves are launched on demand and are shutdown after a certain
amount of idle time. The different slave roles are blueprints for setting up a
slave VM that has the necessary prerequisites for running a particular Jenkins
build.


Quickstart
==========

Activate the virtualenv cgcloud was installed in and install
``cgcloud-jenkins``::

   ::

      cd
      virtualenv cgcloud
      source cgcloud/bin/activate
      pip install cgcloud-jenkins
      export CGCLOUD_PLUGINS="cgcloud.jenkins:$CGCLOUD_PLUGINS"

If you get ``DistributionNotFound: No distributions matching the version for
cgcloud-jenkins``, try running ``pip install --pre cgcloud-jenkins``.

Running ``cgcloud list-roles`` should now list the additional roles defined in
the plugin::

   ...
   jenkins-master
   ubuntu-lucid-genetorrent-jenkins-slave
   ubuntu-precise-genetorrent-jenkins-slave
   ubuntu-saucy-genetorrent-jenkins-slave
   ubuntu-trusty-genetorrent-jenkins-slave
   centos5-genetorrent-jenkins-slave
   centos6-genetorrent-jenkins-slave
   fedora19-genetorrent-jenkins-slave
   fedora20-genetorrent-jenkins-slave
   ubuntu-lucid-generic-jenkins-slave
   ubuntu-precise-generic-jenkins-slave
   ubuntu-saucy-generic-jenkins-slave
   ubuntu-trusty-generic-jenkins-slave
   centos5-generic-jenkins-slave
   centos6-generic-jenkins-slave
   fedora19-generic-jenkins-slave
   fedora20-generic-jenkins-slave
   centos5-rpmbuild-jenkins-slave
   centos6-rpmbuild-jenkins-slave
   load-test-box
   data-browser-jenkins-slave

Master And Slave Roles
======================

The plugin defines a role for the master (``jenkins-master``) and various slave
roles for running builds for certain building CGL projects. There are also a
bunch of generic slaves that are not customized for a particular project.

The master (``jenkins-master``) is a long-running box that hosts the Jenkins
web application. The Jenkins installation (code and data) is cordoned off in
the home directory of a separate ``jenkins`` user. That home directory actually
resides on a secondary EBS volume whose life cycle is independent from that of
the master box, i.e. VM instance. This allows us to update the OS of the master
without having to setup Jenkins from scratch every time we do so.

The remaining roles define the Jenkins slaves. A Jenkins slave is a
short-running box with which the master establishes an SSH connection for the
purpose of triggering a *remote build*. The CGCLoud Jenkins plugin (this
project) is used to create the VM images and register them with the master such
that the master can launch a slave instance when needed to run a remote build
on the platform provided by the slave.

Jenkins
=======

Jenkins is a continuous integration server/web applicaton running on the
``jenkins-master``. Jenkins uses so called *projects* that define where to get
the source, how to build and test the source and which build artifacts to
archive. Builds can be run automatically whenever a push is made, on a fixed
schedule or manually. Builds are executed by an agent. Agents can run locally
on the Jenkins master or remotely on one or more slaves. Jenkins uses its own
plugin system to extend and modify the default behavior. We use the EC2 plugin
which allows us to create slaves on demand in EC2 from images created by
cgcloud in conjunction with this project. Mind the distinction between CGCloud
Jenkins which is plugs into CGCLoud and the hundreds of plugins that extend
Jenkins.

The Jenkins web UI can always be accessed by tunneling port 8080 through SSH.
Running `cgcloud ssh jenkins-master` sets up the necessary port forwarding.
Authorization and authentication in Jenkins itself is disabled on a fresh
instance but can be enabled and further customized using Jenkins plugins. Note:
Anyone with SSH access to the master can access Jenkins and do anything with it.

Tutorial: Creating a Continuous Integration Environment
=======================================================

In this tutorial we'll create a continuous integration environment consisting
of a Jenkins master and several slaves. The tutorial assumes that you completed
the Quickstart section of the CGCloud README.

Creating The Master
-------------------

Create the Jenkins master instance::

   cgcloud create jenkins-master
   
As a test, SSH into the master as the administrative user::

   cgcloud ssh -a jenkins-master
   exit
   
The administrative user has ``sudo`` privileges. Its name varies from platform
to platform but ``cgcloud`` keeps track of that for you. For yet another test,
SSH into the master as the *jenkins* user::

   cgcloud ssh jenkins-master
   
This is the user that the Jenkins server runs as. 

Next, create an image of the master such that you can always recreate a 100%
identical clone::

   cgcloud stop jenkins-master
   cgcloud image jenkins-master
   cgcloud terminate jenkins-master
   cgcloud recreate jenkins-master
   
The first command is necessary to stop the master because only a stopped
instance can be imaged. The ``image`` command creates the actual AMI image. The
``terminate`` command disposes of the instance. This will delete the ``/``
partition while leaving the ``/var/lib/jenkins`` partition around. The latter
is stored on a separate EBS volume called ``jenkins-data``. In other words, the
``terminate`` command leaves us with two things: 1) the AMI for a master box
and 2) the Jenkins data volume. The ``recreate`` command then creates a new
instance from the most recently created image *and* attaches the
``jenkins-data`` volume that instance.

Creating The Slaves
-------------------

Open a new shell window and create the first slave::

   cgcloud list-roles
   cgcloud create docker-jenkins-slave
   
SSH into it::

   cgcloud ssh -a docker-jenkins-slave

Notice that 

 * The admin user has sudo rights::
 
    sudo whoami
 
 * The builds directory in the Jenkins user's home is symbolically linked to
   ephemeral storage::
   
         sudo ls -l ~jenkins
   
 * git and docker are installed::
   
      git --version
      docker --version
      exit

Now stop, image and terminate the box::

   cgcloud stop docker-jenkins-slave
   cgcloud image docker-jenkins-slave
   cgcloud terminate docker-jenkins-slave

Finally, register all slaves with the master::

   cgcloud register-slaves jenkins-master docker-jenkins-slave

The ``register-slaves`` command adds a section to Jenkins' config.xml defines
how to spawn an EC2 instance of ``docker-jenkins-slave`` from the AMI we just
created. The slave description also associates the slave with the label
``docker``. If a project definition requests to be run on slaves labelled
``docker``, an instance will be created from the AMI. Once the instance is up,
the Jenkins master will launch the agent on via SSH. Finally, the master will
ask the agent to run a build for that project. If a slave labelled ``docker``
already exists, it will be used instead of creating a new one. You can
customize how may concurrent builds run on each slave by increasing the number
of agents running on a slave. By default only one slave per role will be
launched but you can configure Jenkins to launch more than one if the queue
contains multiple builds for a given label.
