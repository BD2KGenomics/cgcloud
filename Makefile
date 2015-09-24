python=/usr/bin/env python2.7
sudo=

develop_projects=lib core jenkins spark mesos toil
sdist_projects=lib agent spark-tools mesos-tools
all_projects=lib core agent jenkins spark spark-tools mesos mesos-tools toil

all: develop sdist

green=\033[0;32m
normal=\033[0m
red=\033[0;31m

no_sudo:
	@test "$$(id -u)" != "0" || ( echo "$(red)Don't run me as 'sudo make'. Use 'make sudo=sudo' instead.$(normal)" && false )

develop: no_sudo
	$(python) each_setup.py "egg_info" $(develop_projects)
	$(sudo) $(python) each_setup.py "develop" $(develop_projects)

sdist: no_sudo
	$(python) each_setup.py "sdist" $(sdist_projects)

pypi: no_sudo check_running_on_jenkins check_clean_working_copy
	$(python) each_setup.py "egg_info --tag-build=.dev$$BUILD_NUMBER register sdist bdist_egg upload" $(all_projects)

pypi_stable: no_sudo check_running_on_jenkins check_clean_working_copy
	$(python) each_setup.py "egg_info register sdist bdist_egg upload" $(all_projects)

clean: no_sudo
	$(sudo) $(python) each_setup.py "develop -u" $(develop_projects)
	$(python) each_setup.py "clean --all" $(all_projects)
	for i in $(all_projects); do rm -rf $$i/dist $$i/src/*.egg-info; done

test: no_sudo develop sdist
	@echo "$(green)Checking if nose is installed. If this fails, you need to 'pip install nose'.$(normal)"
	python -c 'import nose'
	@echo "$(green)Looks good. Running tests.$(normal)"
	for i in $(develop_projects); do ( cd $${i} && $(python) -m nose --verbose ) || fail=1 ; done ; test ! "$$fail"
	@echo "$(green)Tests succeeded.$(normal)"

check_clean_working_copy:
	@echo "$(green)Checking if your working copy is clean ...$(normal)"
	@git diff --exit-code > /dev/null \
		|| ( echo "$(red)Your working copy looks dirty.$(normal)" ; false )
	@git diff --cached --exit-code > /dev/null \
		|| ( echo "$(red)Your index looks dirty.$(normal)" ; false )
	@test -z "$$(git ls-files --other --exclude-standard --directory)" \
		|| ( echo "$(red)You have are untracked files:$(normal)" \
			; git ls-files --other --exclude-standard --directory \
			; false )

check_running_on_jenkins:
	@echo "$(green)Checking if running on Jenkins ...$(normal)"
	test -n "$$BUILD_NUMBER" \
		|| ( echo "$(red)This target should only be invoked on Jenkins.$(normal)" ; false )

