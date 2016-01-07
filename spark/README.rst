The CGCloud plugin for Spark lets you setup a fully configured Apache
Spark cluster in EC2 in just minutes, regardless of the number of nodes. While
Apache Spark already comes with a script called ``spark-ec2`` that lets you
build a cluster in EC2, CGCloud Spark differs from ``spark-ec2`` in the
following ways:

* Tachyon or Yarn are not included

* Setup time does not scale linearly with the number of nodes. Setting up a 100
  node cluster takes just as long as setting up a 10 node cluster (2-3 min, as
  opposed to 45min with ``spark-ec2``). This is made possible by baking all
  required software into a single AMI. All slave nodes boot up concurrently and
  join the cluster autonomously in just a few minutes.
  
* Unlike with ``spark-ec2``, the cluster can be stopped and started via the EC2
  API or the EC2 console, without involvement of cgcloud.

* The Spark services (master and worker) run as an unprivileged user, not root
  as with spark-ec2. Ditto for the HDFS services (namenode, datanode and
  secondarynamenode).

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


Prerequisites
=============

The ``cgcloud-spark`` package requires that the ``cgcloud-core`` package and
its prerequisites_ are present.

.. _prerequisites: ../core#prerequisites


Installation
============

Read the entire section before pasting any commands and ensure that all
prerequisites are installed. It is recommended to install this plugin into the 
virtualenv you created for CGCloud::

   source ~/cgcloud/bin/activate
   pip install cgcloud-spark

If you get ``DistributionNotFound: No distributions matching the version for
cgcloud-spark``, try running ``pip install --pre cgcloud-spark``.

Be sure to configure_ ``cgcloud-core`` before proceeding.

.. _configure: ../core/README.rst#configuration

Configuration
=============

Modify your ``.profile`` or ``.bash_profile`` by adding the following line::

   export CGCLOUD_PLUGINS="cgcloud.spark:$CGCLOUD_PLUGINS"

Login and out (or, on OS X, start a new Terminal tab/window).

Verify the installation by running::

   cgcloud list-roles

The output should include the ``spark-box`` role.

Usage
=====

Create a single ``t2.micro`` box to serve as the template for the cluster
nodes::

   cgcloud create -IT spark-box

The ``I`` option stops the box once it is fully set up and takes an image (AMI)
of it. The ``T`` option terminates the box after that.

Now create a cluster by booting a master and the slaves from that AMI::

   cgcloud create-cluster spark -s 2 -t m3.large
   
This will launch a master and two slaves using the ``m3.large`` instance type.

SSH into the master::

   cgcloud ssh spark-master
   
... or the first slave::

   cgcloud ssh -o 0 spark-slave
   
... or the second slave::

   cgcloud ssh -o 1 spark-slave

