virtualenv env
. env/bin/activate

pip install nose
# https://github.com/nose-devs/nose/issues/2
pip install git+https://github.com/rberrelleza/nose-xunitmp.git
export NOSE_WITH_XUNITMP=1
export NOSE_XUNIT_FILE=nosetests.xml

export CGCLOUD_ME=jenkins@jenkins-master
make -k $make_targets
