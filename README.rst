Jenkins data volume
===================

The following steps line out how the jenkins-data EBS volume can be recreated:

1. Using the EC2 AWS console, create the volume in the availability zone that
   you wish to run the build-master in

2. Create a a build-master without an attached Jenkins data volume by running

   ::

   cg-ec2-dev-env \
      --build-instance build-master \
      --jenkins-data-volume

3. Using the EC2 AWS console, stop the instance

4. Attache the new volume to the instance

5. Start