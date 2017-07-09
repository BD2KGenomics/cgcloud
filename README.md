CGCloud lets you automate the creation, management and provisioning of VMs and
clusters of VMs in Amazon EC2. While allowing for easy programmatic
customization of VMs in development, it also provides rock-solid
reproducibility in production.

Features
========

 * Works with base images of all actively supported releases of Ubuntu and
   Fedora, and some releases of CentOS
 
 * Lets you share VMs between multiple users, keeping the set of authorized SSH
   keys synchronized on all VMs in real-time as users/keypairs are added or
   removed from AWS.
 
 * Offers isolation between users, teams and deployments via namespaces
 
 * Lets you stand up a distributed, continuous integration infrastructure using
   one long-running Jenkins master and multiple on-demand Jenkins slaves
 
 * Lets you create an HDFS-backed Apache Spark cluster of any number of nodes
   in just three minutes, independently of the number of nodes, with our
   without attached EBS volumes
 
 * Lets you create a Mesos cluster of any number of Nodes
 
 * Supports running Spark, Mesos and Toil workers on the spot market
 
 * Is easily extensible via a simple plugin architecture
 
 * VMs created by CGCloud optionally report memory and disk utilization as 
   custom CloudWatch metrics
 
So what does it not offer? What are its limitations? First and foremost, it is
strictly tied to AWS and EC2. Other cloud providers are not supported and
probably will not be in the near future. It does not have a GUI. It is written
in Python and if you want to customize it, you will need to know Python. It
makes extreme use of multiple inheritance. Some people
frown at that since it will make it likely that your own customizations break
between releases of CGCloud. While allowing CGCloud to be extremely
[DRY](https://en.wikipedia.org/wiki/Don%27t_repeat_yourself), multiple
inheritance also increases the complexity and steepens the learning curve.

Where to go from here?
======================

If you are a (potential) **user** of CGCloud, head on over to the [CGCloud Core
README](core/README.rst) and then move on to

 * [CGCloud Jenkins](jenkins/README.rst)
 
 * [CGCloud Spark](spark/README.rst)
 
 * [CGCloud Mesos](mesos/README.rst)

 * [CGCloud Toil](toil/README.rst)

If you are a **developer**, make sure you have pip and virtualenv, clone this
repository and perform the following steps from the project root::

	virtualenv venv
	source venv/bin/activate
	make develop sdist

That will set up the project in development mode inside a virtualenv and create
source distributions (aka sdists) for those components that are be installed on
remote boxes. In development mode, these components are not installed from PyPI
but are instead directly uploaded to the box in sdist form and then installed
from the sdist.

After pulling changes from the remote, you need to run `make develop sdist` again.
This step is easy to forget because you often get by without it.

Specifically, `make develop` is necessary after any of the setup.py or
version.py files have changed, and `make sdist` is necessary after changes to
the agent, spark-tools or mesos-tools subprojects. Otherwise, `cgcloud create`
will install a stale version of these on the remote box.

To run the unittests, `pip install pytest` and then do `make test`.
