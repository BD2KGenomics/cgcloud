python=/usr/bin/env python2.7
sudo=

develop_projects=lib core jenkins spark mesos toil
sdist_projects=lib agent spark-tools mesos-tools
all_projects=lib core agent jenkins spark spark-tools mesos mesos-tools toil

green=\033[0;32m
normal=\033[0m
red=\033[0;31m

.SUFFIXES:

.PHONY: all
all: develop sdist

.PHONY: no_sudo
no_sudo:
	@test "$$(id -u)" != "0" || ( echo "$(red)Don't run me as 'sudo make'. Use 'make sudo=sudo' instead.$(normal)" && false )

define _develop
.PHONY: develop_$1
develop_$1: no_sudo $1/version.py $1/MANIFEST.in
	cd $1 && $(python) setup.py egg_info
	cd $1 && $(sudo) $(python) setup.py develop
endef
$(foreach project,$(develop_projects),$(eval $(call _develop,$(project))))

.PHONY: develop
develop: $(foreach project,$(develop_projects),develop_$(project))


define _sdist
.PHONY: sdist_$1
sdist_$1: no_sudo $1/version.py $1/MANIFEST.in
	cd $1 && $(python) setup.py sdist
endef
$(foreach project,$(sdist_projects),$(eval $(call _sdist,$(project))))

.PHONY: sdist
sdist: $(foreach project,$(sdist_projects),sdist_$(project))


define _pypi
.PHONY: pypi_$1
pypi_$1: no_sudo check_running_on_jenkins check_clean_working_copy $1/version.py $1/MANIFEST.in
	cd $1 && $(python) setup.py "egg_info --tag-build=.dev$$$$BUILD_NUMBER register sdist bdist_egg upload"
endef
$(foreach project,$(all_projects),$(eval $(call _pypi,$(project))))

.PHONY: pypi
pypi: $(foreach project,$(all_projects),pypi_$(project))


define _pypi_stable
.PHONY: pypi_stable_$1
pypi_stable_$1: no_sudo check_running_on_jenkins check_clean_working_copy $1/version.py $1/MANIFEST.in
	cd $1 && $(python) setup.py egg_info register sdist bdist_egg upload
endef 
$(foreach project,$(all_projects),$(eval $(call _pypi_stable,$(project))))

.PHONY: pypi_stable
pypi_stable: $(foreach project,$(all_projects),pypi_stable_$(project))


define _clean
.PHONY: clean_$1
clean_$1: no_sudo
	cd $1 && $(python) setup.py clean --all && rm -rf dist src/*.egg-info MANIFEST.in version.py
endef
$(foreach project,$(all_projects),$(eval $(call _clean,$(project))))

define _undevelop
.PHONY: undevelop_$1
undevelop_$1: no_sudo
	cd $1 && $(sudo) $(python) setup.py develop -u
endef
$(foreach project,$(all_projects),$(eval $(call _undevelop,$(project))))

.PHONY: clean
clean: $(foreach project,$(all_projects),clean_$(project)) $(foreach project,$(develop_projects),undevelop_$(project))


define _test
.PHONY: test_$1
test_$1: no_sudo nose sdist develop_$1
	cd $1 && $(python) -m nose --verbose
	@echo "$(green)Tests succeeded.$(normal)"
endef
$(foreach project,$(develop_projects),$(eval $(call _test,$(project))))

.PHONY: test
test: $(foreach project,$(develop_projects),test_$(project))


.PHONY: nose
nose:
	@echo "$(green)Checking if nose is installed. If this fails, you need to 'pip install nose'.$(normal)"
	python -c 'import nose'
	@echo "$(green)Looks good. Running tests.$(normal)"


.PHONY: check_clean_working_copy
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


.PHONY: check_running_on_jenkins
check_running_on_jenkins:
	@echo "$(green)Checking if running on Jenkins ...$(normal)"
	test -n "$$BUILD_NUMBER" \
		|| ( echo "$(red)This target should only be invoked on Jenkins.$(normal)" ; false )


%/version.py: version.py
	cp $< $@


%/MANIFEST.in: MANIFEST.in
	cp $< $@
