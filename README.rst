The CGCloud Spark project lets you setup a functioning Apache Spark cluster in
EC2 in just minutes, independently of the number of nodes. It is a plugin to
CGCloud. Apache Spark includes a spark-ec2 script that lets you build a cluster
in EC2. CGCloud Spark differs from spark-ec2 in the following ways:

* Setup time does not scale linearly with the number of nodes. Setting up a 100
  node cluster takes just as long as setting up a 10 node cluster (2-3 min, as
  opposed to 45min with spark-ec2). This is made possible by baking all
  required software into a single AMI. All slave nodes boot up concurrently and
  autonomously in just a few minutes.
  
* Unlike with spark-ec2, the cluster can be stopped and started via the EC2 API
  or the EC2 console, without involvement of cgcloud.

* The Spark services (master and worker) run as an unprivileged user, not root
  as with spark-ec2. Ditto for the HDFS services (namenode, datanode and
  secondarynamenode).

* The Spark and Hadoop services bind to the instances' private IPs only, not
  the public IPs as with spark-ec2. The various web UIs are exposed via SSH
  tunneling.
  
* The Spark and Hadoop services are started automatically as the instance boots
  up, via a regular init script.

* Nodes can be added easily, simply by booting up new instances from the AMI.
  They will join the cluster automatically. HDFS may have to be rebalanced
  after that.

* You can customize the AMI that cluster nodes boot from by subclassing the
  SparkMaster and SparkSlave classes.

* CGCloud Spark uses the CGCLoud Agent which takes care of maintaining a list
  of authorized keypairs on each node.

* CGCloud Spark is based on the official Ubuntu Trusty 14.04 LTS, not the
  Amazon Linux AMI.

* CGCloud Spark does not yet support EBS-backed HDFS storage, only instance
  store.
  
* Tachyon and Yarn have not been tested but will soon be supported.

* Instance types with more than one ephemeral store will be supported soon.


Prerequisites
=============

The ``cgcloud-spark`` has the same prerequisites_ as the ``cgcloud-core``
package. Installing ``cgcloud-spark`` will automatically install
``cgcloud-core`` and its dependencies.

.. _prerequisites: https://github.com/BD2KGenomics/cgcloud-core#prerequisites


Installation
============

Read the entire section before pasting any commands! Once the prerequisites are
installed, use ``pip`` to install ``cgcloud-spark``::

   sudo pip install git+https://github.com/BD2KGenomics/cgcloud-spark.git

On OS X systems with a Python that was installed via HomeBrew, you should omit
`sudo`. You can find out if that applies to your system by running ``which
python``. If it prints ``/usr/local/bin/python`` you are most likely using a
HomeBrew Python and should therefore omit ``sudo``. If it prints
``/usr/bin/python`` you need to run ``pip`` with ``sudo``.

If you get

::

   Could not find any downloads that satisfy the requirement cgcloud-...

try adding ``--process-dependency-links`` after ``install``. This is a known
`issue`_ with pip 1.5.x.

.. _issue: https://mail.python.org/pipermail/distutils-sig/2014-January/023453.html

Modify your ``.profile`` or ``.bash_profile`` by adding the following line::

   export CGCLOUD_PLUGINS=cgcloud.spark

Login and out (or, on OX X, start a new Terminal tab/window).

Verify the installation by running::

   cgcloud list-roles

The output should include the ``spark-box`` role.

Usage
=====

Create a single ``t2.micro`` box to serve as the template for the cluster
nodes::

   cgcloud create spark-box -I -T

The ``-I`` switch stops the box once it is fully set up and takes an AMI of it.
The ``-T`` switch terminates it.

Create a cluster by booting a master and the slaves from that AMI::

   cgcloud start-spark-cluster -s 2 -t m3.large
   
This will launch a master and two slaves using the ``m3.large`` instance type.

SSH into the master::

   cgcloud ssh spark-master
   
... or the first slave::

   cgcloud ssh spark-slave -o 0
   
... or the second slave::

   cgcloud ssh spark-slave -o 1
