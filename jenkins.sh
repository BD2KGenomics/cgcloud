virtualenv venv
. venv/bin/activate

pip install nose
# https://github.com/nose-devs/nose/issues/2
pip install git+https://github.com/rberrelleza/nose-xunitmp.git
export NOSE_WITH_XUNITMP=1
export NOSE_XUNIT_FILE=nosetests.xml
export NOSE_PROCESSES=16
export NOSE_PROCESS_TIMEOUT=3600

export CGCLOUD_ME=jenkins@jenkins-master
# We want to use -k/--keep-going such that make doesn't fail the build on the first subproject for
# which the tests fail and keeps testing the other projects. Unfortunately, that takes away the
# convenience of specifiying multiple targets in one make invocation since make would not stop on a
# failing target.
for target in $make_targets; do
    make --jobs=8 --output-sync --keep-going $target
done
