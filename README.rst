The CGCloud Spark project lets you setup a functioning Apache Spark cluster in
EC2 in just minutes, independently of the number of nodes. It is a plugin to
CGCloud. Apache Spark includes a spark-ec2 script that lets you build a cluster
in EC2. CGCloud Spark differs from spark-ec2 in the following ways:

* Setup time does not scale linearly with the number of nodes. Setting up a 100
  node cluster takes just as long as setting up a 10 node cluster (2-3 min, as
  opposed to 45min with spark-ec2). This is made possible by baking all
  required software into a single AMI. All slave nodes boot up concurrently and
  autonomously in just a few minutes.

* The Spark services (master and worker) run as an unprivileged user, not root
  as with spark-ec2. Ditto for the HDFS services (namenode, datanode and
  secondarynamenode).

* The Spark and Hadoop services bind to the instances' private IPs only, not
  the public IPs as with spark-ec2. The various web UIs are exposed via SSH
  tunneling.

* Nodes can be added easily, simply by booting up new instances from the AMI.
  They will join the cluster automatically.

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
