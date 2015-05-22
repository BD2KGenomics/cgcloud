TODO: More to come

If you are a (potential) user of CGCloud, start with the [CGCloud Core
README](core/README.rst) and then optionally move on to

 * [CGCloud Jenkins](jenkins/README.rst)
 * [CGCloud Spark](spark/README.rst)
 * [CGCloud Mesos](mesos/README.rst)

If you are a developer, clone this repository and run `make` from the project
root. That will set the project up in development mode and create source
distributions (aka sdists) for the components to be installed on remote boxes.
In development mode, these components are not installed from PyPI but are
instead uploaded to the box in sdist form and installed directly from the sdist.
