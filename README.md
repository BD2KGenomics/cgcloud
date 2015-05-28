TODO: More to come

Users
=====

If you are a (potential) user of CGCloud, start with the [CGCloud Core
README](core/README.rst) and then optionally move on to

 * [CGCloud Jenkins](jenkins/README.rst)
 * [CGCloud Spark](spark/README.rst)
 * [CGCloud Mesos](mesos/README.rst)

Developers
==========

If you are a developer, clone this repository and run `make` from the project
root. That will set up the project in development mode and create source
distributions (aka sdists) for the components to be installed on remote boxes.
In development mode, these components are not installed from PyPI but are
instead uploaded to the box in sdist form and installed directly from the sdist.

After changes to the agent, spark-tools or mesos-tools you should run `make`
again. Otherwise, `cgcloud create` will install a stale version of these on the
remote box.

Depending on your Python installation, certain steps in the Makefile may
require root privileges. Don't run `sudo make` because that will create files
owned by root in the source tree. Instead use `make sudo=sudo`. If you did
accidentially run `sudo make`, run `sudo make clean` to delete those files
first and then run `make sudo=sudo`.

To have `make` use a particular Python interpreter, pass the `python` variable
to it, e.g. `make python=/usr/bin/python2.7`.
