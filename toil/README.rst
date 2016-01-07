The CGCloud plugin for Toil lets you setup a fully configured Toil/Mesos
cluster in EC2 in just minutes, regardless of the number of nodes.


Prerequisites
=============

The ``cgcloud-toil`` package requires that the ``cgcloud-core`` package and
its prerequisites_ are present.

.. _prerequisites: ../core#prerequisites


Installation
============

Read the entire section before pasting any commands and ensure that all
prerequisites are installed. It is recommended to install this plugin into the 
virtualenv you created for CGCloud::

   source ~/cgcloud/bin/activate
   pip install cgcloud-toil

If you get ``DistributionNotFound: No distributions matching the version for
cgcloud-toil``, try running ``pip install --pre cgcloud-toil``.

Be sure to configure_ ``cgcloud-core`` before proceeding.

.. _configure: ../core/README.rst#configuration

Configuration
=============

Modify your ``.profile`` or ``.bash_profile`` by adding the following line::

   export CGCLOUD_PLUGINS="cgcloud.toil:$CGCLOUD_PLUGINS"

Login and out (or, on OS X, start a new Terminal tab/window).

Verify the installation by running::

   cgcloud list-roles

The output should include the ``toil-box`` role.

Usage
=====

Create a single ``t2.micro`` box to serve as the template for the cluster
nodes::

   cgcloud create -IT toil-box

The ``I`` option stops the box once it is fully set up and takes an image (AMI)
of it. The ``T`` option terminates the box after that.

Substitute ``toil-latest-box`` for ``toil-box`` if you want to use the latest
unstable release of Toil.

Now create a cluster by booting a leader and the workers from that AMI::

   cgcloud create-cluster toil -s 2 -t m3.large
   
This will launch a leader and two workers using the ``m3.large`` instance type.

SSH into the leader::

   cgcloud ssh toil-leader
   
... or the first worker::

   cgcloud ssh -o 0 toil-worker
   
... or the second worker::

   cgcloud ssh -o 1 toil-worker

