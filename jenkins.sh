virtualenv venv
. venv/bin/activate

pip install pytest==2.9.2

export CGCLOUD_ME=jenkins@jenkins-master

make develop sdist

# We want to use -k/--keep-going such that make doesn't fail the build on the first subproject for
# which the tests fail and keeps testing the other projects. Unfortunately, that takes away the
# convenience of specifiying multiple targets in one make invocation since make would not stop on a
# failing target.
( for target in $make_targets; do
    ( if [ "$target" = test ]; then
        make --jobs --keep-going $target
    else
        make $target
    fi ) || exit
done )
