python=/usr/bin/env python2.7
sudo=

develop_projects=lib core jenkins spark mesos jobtree
sdist_projects=lib agent spark-tools mesos-tools
all_projects=lib core agent jenkins spark spark-tools mesos mesos-tools jobtree

all: develop sdist

no_sudo:
	@test "$$(id -u)" != "0" || ( echo "\033[0;31mDon't run me as 'sudo make'. Use 'make sudo=sudo' instead.\033[0m" && false )

develop: no_sudo
	$(python) each_setup.py "egg_info" $(develop_projects)
	$(sudo) $(python) each_setup.py "develop" $(develop_projects)

sdist: no_sudo
	$(python) each_setup.py "sdist" $(sdist_projects)

pypi: no_sudo
	@echo "\033[0;32mChecking if your working copy is clean ...\033[0m"
	git diff --exit-code
	git diff --cached --exit-code
	test -z "$(git ls-files --other --exclude-standard --directory)"
	@echo "\033[0;32mLooks like your working copy is clean. Uploading to PyPI ...\033[0m"
	$(python) each_setup.py "register sdist bdist_egg upload" $(all_projects)
	@echo "\033[0;32mLooks like the upload to PyPI was successful.\033[0m"
	@echo "\033[0;32mNow tag this release in git and bump the version in every setup.py.\033[0m"

clean: no_sudo
	$(sudo) $(python) each_setup.py "develop -u" $(develop_projects)
	$(python) each_setup.py "clean --all" $(all_projects)
	for i in $(all_projects); do rm -rf $$i/dist $$i/src/*.egg-info; done

test: no_sudo develop sdist
	@echo "\033[0;32mChecking if nose is installed. If this fails, you need to 'pip install nose'.\033[0m"
	python -c 'import nose'
	@echo "\033[0;32mLooks good. Running tests.\033[0m"
	for i in $(develop_projects); do ( cd $${i} && $(python) -m nose --verbose ) || fail=1 ; done ; test ! "$$fail"
	@echo "\033[0;32mTests succeeded.\033[0m"
