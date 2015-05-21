Note: A lot of this is outdated or applies to CGHub only
========================================================

The CGHub Cloud CI project contains the VM definitions for running a
distributed continuous integration environment in EC2 with one Jenkins master
and multiple slaves. CGHub currently uses CGHub Cloud CI for continuously
building GeneTorrent and the CGHub Data Browser as well as several support
projects.


Quickstart
==========

First, install the code, either in the system python (requiring sudo) or in a local python (change path to pip accordingly)::

   pip install git+ssh://git@bitbucket.org/cghub/cghub-cloud-ci

CGHub Cloud CI is a plugin to `CGhub Cloud Core <https://bitbucket.org/cghub/custom-centos-packages>`_. 
The following environment variable tells the core to load the plugin::

   export CGCLOUD_PLUGINS=cgcloud.bd2k.ci

Running ``cgcloud list-roles`` should now list the additional roles defined in the
plugin::

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

There are five classes of roles: The master role (1), slave roles for building
GeneTorrent (2) and our custom Apache and Python RPMs (3), as well as slave
roles for running the Data Browser Selenium tests (4) and testing of the
GeneTorrent package installation (5).

The master (``jenkins-master``) is a long-running box that hosts the Jenkins
web application. The Jenkins installation (code and data) is cordoned off in
the home directory of a separate ``jenkins`` user. That home directory actually
resides on a secondary EBS volume whose life cycle is independent from that of
the master box, i.e. VM instance. This allows us to update the OS of the master
without having to setup Jenkins from scratch every time we do so.

The remaining roles define the Jenkins slaves. A Jenkins slave is a
short-running box with which the master establishes an SSH connection for the
purpose of triggering a *remote build*. The CGHub Cloud CI plugin (this
project) is used to create the VM images and register them with the master such
that the master can launch a slave instance when needed to run a remote build
on the platform provided by the slave.

The ``*-genetorrent-jenkins-slave`` roles define slaves for building
GeneTorrent. A box performing the ``*-rpmbuild-jenkins-slave`` role is used to
build various custom RPMs in use at CGHub (see the `custom-centos-packages
<https://bitbucket.org/cghub/custom-centos-packages>`_ project). The
``*-generic-jenkins-slave`` roles define slaves for testing the installation of
GeneTorrent from both native ``.rpm`` and ``.deb`` as well as the binary
``.tar.gz`` on the platforms that CGHub supports.


Jenkins
=======

Jenkins is a continuous integration server/web applicaton running on
``jenkins-master``. Jenkins uses so called *build plans* which define for a
particular project where to get the source, how to build and test the source
and which build artifacts to archive. Builds can be run automatically whenever
the source changes, on a fixed schedule or manually. We currently use the
latter as a means to tightly control the cost incurred on AWS. Builds are
executed by an agent. Agents can run locally on the Jenkins master or remotely
on one or more slaves. Jenkins uses plugins to extend and modify the default
behavior. We use the EC2 plugin which allows us to create slaves on demand in
EC2, and the matrix build plugin to run a build in parallel on multiple slaves,
one per target operating system. In addition to the EC2 slaves that are created
on demand from images prepared by this CGHub Cloud CI plugin, there is also a
slave for OS X and one for Windows. These are VMWare virtual machines on a Mac
Mini host that is currently sitting on my desk.

Build Plans
-----------

The ``genetorrent`` build uses selected helper scripts and makefiles from
Mark's `genetorrent-build <https://bitbucket.org/cghub/genetorrent-build>`_
(formerly known as ``client-build``) to build a GeneTorrent source package,
native packages (``.deb`` or ``.rpm``) as well as a binary ``.tar.gz`` package
for all supported Linux distributions. This is the only build plan that checks
out two source trees/Git repositories: ``genetorrent`` itself and
``genetorrent-build``.

Since the Windows and OS X build require special steps, they are built by
separate plans: ``genetorrent-win`` and ``genetorrent-osx``. These two do not
produce a a binary ``.tar.gz`` distribution, only native packages: a NSIS
installer for Windows and a ``.pkg`` for OS X. Neither do they use the
``genetorrent-build`` helper.

The ``genetorrent-installation-tests`` plan downloads the native and binary
``.tar.gz`` packages, installs them and runs a test upload and download against
CGHub. The plan installs the native packages first, then uninstalls them whilst leaving their dependencies in place, and then installs the binary ``.tar.gz``. Starting with GeneTorrent 3.8.7, all exotic dependencies are bundled in the ``.tar.gz``, so this trick is largely unnecessary since the only other dependencies are ``libcurl`` and ``openssl`` and those are already present on a ``*-generic-jenkins-slave``.

Routine Development Tasks
=========================


Viewing all EC2 VM instances
----------------------------

This topic applies to CGhub Cloud in general, not just the CI plugin.

1) Log into the `Amazon AWS console <https://cghub.signin.aws.amazon.com/console/>`_

2) Navigate to the EC2 console via *Services* in the main menu 

3) Select the *Instances* link on the sidebar

Ask an IAM admin (currently Chris, Haifang and Hannes) to create an IAM account for you.

Creating an IAM account
-----------------------

This topic applies to CGhub Cloud in general, not just the CI plugin.

1) Log into the `Amazon AWS console <https://cghub.signin.aws.amazon.com/console/>`_

2) Navigate to the IAM console via *Services* in the main menu 

3) Create a new user, using an existing user as a template. Current convention
is to make every user and admin, but that should probably be changed by now.

In order to be able to use ``cgloud``, the new user must create an access key
using the IAM console and upload their SSH public key using ``cgcloud
register-key``. Both of these steps are described in the README of the `CGHub
Cloud Core project <https://bitbucket.org/cghub/cghub-cloud-core>`_.

Stopping the master
-------------------

To save cost, it is recommended that the master is kept in a
stopped state unless a GeneTorrent or Data Browser release is in the works.

.. note:: 
   ... that *stopping* an instance—aka *box* in cgcloud lingo—is different to
   *terminating* it. Stopping an instance is like shutting down a physical
   computer and turning it off. The data on the hard disk stays around.
   Launching an instance is like buying a new computer. Terminating it would be
   akin to throwing it away, including the hard disks and the data on them.

Use the EC2 console to stop the instance or run ``cgcloud stop
jenkins-master``.

Starting the master
-------------------

Run ``cgcloud start jenkins-master``. If the master is already running, you will get a harmless exception.

Accessing the Jenkins Web UI
----------------------------

Running 

::

   cgcloud ssh jenkins-master -l jenkins

will SSH into the master as the ``jenkins`` user **and** setup a port
forwarding to the Jenkins' web UI running on the master. Point your browser at
http://localhost:8080/ to access the web UI.

Triggering a Build
------------------

In the Jenkins web UI, click the icon the last column of the build plan listing for the plan you want to build. If the build is a matrix build, you will be asked which slaves to build on.

Examining Builds
----------------

1) Access the Jenkins web UI

2) Click on a build plan

3) Click on a particular build

4) Examine the build output

5) Examine the archived log artifacts. The genetorrent-build helper redirects
   the output of each major build step to a separate ``.log`` file. These files
   are archived by Jenkins.

6) Examine the generated packages on S3. The packages are archived into the
   `s3://public-artifacts.cghub.ucsc.edu/ <http://public-artifacts.cghub.ucsc.edu.s3-website-us-west-1.amazonaws.com/?prefix=>`_
   bucket. The above link is powered by a little JS file that makes any S3
   bucket browsable on the web. Don't share this link outside of CGHub.
   GeneTorrent releases should be distributed via CGHub's website. See next two
   sections on how to get them there.

Copying Build Artifacts
-----------------------

Install ``s3cmd``. Use its ``sync`` command to download the build artifacts
from S3. For example, ::

   s3cmd --verbose --exclude '*' --include 'genetorrent-win/build-69/**' sync s3://public-artifacts.cghub.ucsc.edu/ .
   
Releasing GeneTorrent
---------------------

Make sure all GeneTorrent builds (``genetorrent``,
``genetorrent-installation-tests``, ``genetorrent-win`` and
``genetorrent-osx``) succeed. Then identify the official release build for each
of these plans. Typically this will be the last build on each plan.

1) Tag the commit that was used by the release build. Use the version number
   for the tag name. Add the version number to the description of the build in
   Jenkins. Use previous releases as a guide.

2) Copy the artifacts produced by the ``genetorrent``, ``genetorrent-win`` and
   ``genetorrrent-osx`` plans. See previous section for details.

3) Put them into ``/cghub/tcga/www/html/ws/downloads/GeneTorrent/$version`` on
   app01 in staging. Use a previous releases as a guide.

4) Modify software/downloads.html in `cghub-website
   <https://bitbucket.org/cghub/cghub-website>`_ to refer to the new version.
   Ditto for submitters.html. Commit, push and deploy to
   ``/cghub/tcga/www/html/ws/public`` on app01 on staging.

5) Test

6) Copy ``/cghub/tcga/www/html/ws/downloads/GeneTorrent/$version`` from stage
   to production.

7) Deploy the cghub-website update to /cghub/tcga/www/html/ws/public on app01
   in production.
   
Running Data Browser Selenium Tests
-----------------------------------

1) Commit and push your changes. 

2) Access the Jenkins web UI. 

3) Trigger the ``cghub-data-browser`` build.

Adding a slave
--------------

Let's say a new LTS Ubuntu platform is released and CGHub wants to support it.
Generally speaking, you first need to create a new Box subclass for that
distribution. Look at ``genetorrent-jenkins-slaves.py`` and
``generic-jenkins-slaves.py``.

.. note:: 

   Oddly, the genetorrent slaves are not derived from the generic slaves, even
   though a genetorrent slave is true superset of the generic slave for the
   same distribution. This should be fixed at some point.
   
Then ``cgcloud create`` that instance. Configure the genetorrent build plan on
the master to include the new Ubuntu LTS release as a target distribution.
Trigger the genetorrent build, unchecking all but the new distribution. Examine
the build output. You now might have to tweak the new slave definition. For
example if a build dependency is missing, you need to include it in the slave
definition. Make the change, ``cgcloud terminate`` the slave and then ``cgcloud
create`` it again.

You may also need to modify the ``genetorrent`` source itself or or
``genetorrent-build``. You may want to make those changes in a branch first. In
Jenkins, configure the ``genetorrent``, ``genetorrent-win`` and
``genetorrent-osx`` plans to checkout that branch instead of the master branch.
Commit and push the changes and trigger the build again. Rinse and repeat as
needed.

Once the ``genetorrent`` build succeeds on the new slave, trigger the
``genetorrent-installation-tests`` build. It defaults to testing the artifacts
produced by the most recent ``genetorrent`` build. Fix any failures. Once both
plans succeed for the new slave, image the slave, recreate it form the image
and build both plans again on that new instance. There is always the slight
chance that something works on a slave ``create``\ d from scratch but on one
``recreate``\ d from an image.

Trigger both plans for all new slaves. Also trigger the genetorrent-win and
genetorrent-osx plans. Once those four plans succeed, merge the branch into the
master and rebuild the four plans again.


Security, Authentication & Authorization
========================================

All boxes (VM instances) use the default ``security group`` (AWS lingo for
firewall profile) which only opens incoming TCP port 22. The Jenkins web UI
needs to be accessed by tunneling port 8080 through SSH. Authorization and
authentication in Jenkins itself is disabled. Anyone with SSH access to the
master can access Jenkins and do anything with it.

There are two ways for person to get SSH access to the master. They ask an IAM
admin to create an IAM account on AWS after which they generate an AWS access
key for themselves and use that to register their SSH key with ``cgcloud``.
Alternatively, they ask someone with an IAM account and an AWS access key to
register their SSH key for them.

Any agent box, i.e. any box created by a subclass of AgentBox runs the CGHub
Cloud Agent daemon. Agent boxes use `IAM roles
<http://docs.aws.amazon.com/IAM/latest/UserGuide/roles-usingrole-ec2instance.html>`_ 
to authenticate themselves against AWS. This allows the agent to use the
required AWS services (e.g. SNS, S3 and SQS) without storing secret access keys
on the box. At the time the CGHub Cloud Agent was implemented, the EC2 Jenkins
plugin did not support IAM roles. So while the CGHub Cloud Agent running on the
master does use an IAM role, the Jenkins EC2 plugin running on the same master
does not and is configured to use a separate access key instead, an access key
tied to a special IAM user representing Jenkins.

The Unix account that Jenkins runs as has its own SSH key pair. This key pair
is used to authenticate Jenkins against BitBucket for the purpose of checking
out a source tree. To authorize Jenkins to checkout a private repository, the
public SSH key (``~jenkins/.ssh/id_rsa.pub`` on ``jenkins-master``) must be
registered under the Deployment Keys section of that repository's settings page
on BitBucket. Most slaves inherit that key from the master via SSH agent
forwarding, except for the Windows slave because SSH forwarding didn't work
with Cygwin's Windows port of the OpenSSH server. Instead, the Windows slave
has its own SSH key pair. If a project is to be built on the Windows slave, the
SSH key belonging to the ``jenkins`` user on the Windows slave needs to be
registered as a deployment key for that project, in addition to the master's
SSH key. The only other non-EC2 slave, the Mac OS X slave does not have that
problem.


Tutorial: Creating a Continuous Integration Environment
=======================================================

In this tutorial we'll create a continuous integration environment for
GeneTorrent consisting of a Jenkins master and several slaves, one slave for
each target platform of GeneTorrent. Note that this is not a routine task. It's
most likely that you will need to *add* a slave rather than create the master
and all slaves from scratch. There is a dedicated section for that above but it
is very high-level. Be sure to read this section too.

The tutorial assumes that

* You completed the quick start for `CGhub Cloud Core <https://bitbucket.org/cghub/custom-centos-packages>`_

* You have nothing listening on port 8080 locally

First, select the cgcloud namespace you want to be working in::

   export CGCLOUD_NAMESPACE=/

The above setting means that we will be working in the root namespace. If you'd
rather walk through this tutorial without affecting the root namespace (and
thereby risking interference with other team members), set
``CGCLOUD_NAMESPACE`` to a value that's unlikely to be used by anyone else. For
example,::

   export CGCLOUD_NAMESPACE=$(whoami)

Creating The Master
-------------------

Create the Jenkins master instance::

   cgcloud create jenkins-master
   
As a test, SSH into the master as the administrative user::

   cgcloud ssh jenkins-master
   exit
   
The administrative user has ``sudo`` privileges. Its name varies from platform
to platform but ``cgcloud`` keeps track of that for you. For yet another test,
SSH into the master as the *jenkins* user::

   cgcloud ssh jenkins-master -l jenkins
   
This is the user that the Jenkins server runs as. 

This is possibly not the first time that a ``jenkins-master`` box is created in
the $CGCLOUD_NAMESPACE namespace. If a ``jenkins-master`` box existed in that
namespace before, the volume containing all of Jenkins' data (configurations,
build plans, build output, etc.) will still be around. That is, unless someone
deleted it, of course. Creating a ``jenkins-master`` in a namespace will reuse
the ``jenkins-data`` volume from that namespace if it already exists. If it
doesn't, it will be automatically created and Jenkins will be setup with a
default configuration.

Next, create an image of the master such that you can always recreate a 10% identical clone::

   cgcloud stop jenkins-master
   cgcloud image jenkins-master
   cgcloud terminate jenkins-master
   cgcloud recreate jenkins-master
   
The first command is necessary to stop the master because only stopped instance
can be imaged. The ``image`` command create the actual AMI image. The
``terminate`` command disposes of the instance. This will delete the ``/``
partition while leaving the ``/var/lib/jenkins`` partition around. The former
is tied to the instance, the latter is a an EBS volume with an independent
lifecycle. In other words the ``terminate`` command leaves us with the AMI for a master box and the Jenkins data volume. The ``recreate`` command then creates a new instance from the most recently created image *and* attaches EBS volume containing the Jenkins data to that instance.

Creating The Slaves
-------------------

Open a new shell window and create the first slave::

   cgcloud list-roles
   cgcloud create centos5-genetorrent-jenkins-slave
   
SSH into it::

   cgcloud ssh centos5-genetorrent-jenkins-slave

Notice that 

 * The admin user has sudo rights::
 
    sudo whoami
 
 * The builds directory in the Jenkins user's home is symbolically linked to
   ephemeral storage::
   
         sudo ls -l ~jenkins
   
 * git is installed::
   
      git --version
      exit

Now stop, image and terminate the box::

   cgcloud stop centos5-genetorrent-jenkins-slave
   cgcloud image centos5-genetorrent-jenkins-slave
   cgcloud terminate centos5-genetorrent-jenkins-slave

::
   
      cgcloud ssh jenkins-master -l jenkins

and click *Manage Jenkins* in the Jenkins web UI and *Reload Configuration from
Disk**.

Repeat this for all other slaves::

   for slave in $(./cgcloud list-roles \
      | grep jenkins-slave \
      | grep -v centos5-genetorrent-jenkins-slave); do
      cgcloud create $slave --image --terminate
   done

Note how the above command makes use of the ``--image`` and ``--terminate``
options to combine the creation of a box with image creation and termination
into a single command.

This is a time-consuming method. There is a integration test in cghub-cloud-ci
that creates all slaves in parallel using ``tmux``. Very fancy stuff. Look at
``create-all-slaves.py``. You might have to comment out the creation of the
master.

Finally, register all slaves with the master::

   cgcloud register-slaves jenkins-master centos5-genetorrent-jenkins-slave

The ``register-slaves`` command adds a section to Jenkins' config.xml that
tells Jenkins how to spawn an instance of this slave from the image we just
created.
