The CGCloud plugin for Mesos lets you setup a fully configured Apache Mesos
cluster in EC2 in just minutes, regardless of the number of nodes.


Prerequisites
=============

The ``cgcloud-mesos`` package requires that the ``cgcloud-core`` package and
its prerequisites_ are present.

.. _prerequisites: ../core#prerequisites


Installation
============

Read the entire section before pasting any commands and ensure that all
prerequisites are installed. It is recommended to install this plugin into the 
virtualenv you created for CGCloud::

   source ~/cgcloud/bin/activate
   pip install cgcloud-mesos

If you get ``DistributionNotFound: No distributions matching the version for
cgcloud-mesos``, try running ``pip install --pre cgcloud-mesos``.

Be sure to configure_ ``cgcloud-core`` before proceeding.

.. _configure: ../core/README.rst#configuration

Configuration
=============

Modify your ``.profile`` or ``.bash_profile`` by adding the following line::

   export CGCLOUD_PLUGINS="cgcloud.mesos:$CGCLOUD_PLUGINS"

Login and out (or, on OS X, start a new Terminal tab/window).

Verify the installation by running::

   cgcloud list-roles

The output should include the ``mesos-box`` role.

Usage
=====

Create a single ``t2.micro`` box to serve as the template for the cluster
nodes::

   cgcloud create -IT mesos-box

The ``I`` option stops the box once it is fully set up and takes an image (AMI)
of it. The ``T`` option terminates the box after that.

Now create a cluster by booting a master and the slaves from that AMI::

   cgcloud create-cluster mesos -s 2 -t m3.large
   
This will launch a master and two slaves using the ``m3.large`` instance type.

SSH into the master::

   cgcloud ssh mesos-master
   
... or the first slave::

   cgcloud ssh -o 0 mesos-slave
   
... or the second slave::

   cgcloud ssh -o 1 mesos-slave

