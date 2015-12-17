# Copyright (C) 2015 UCSC Computational Genomics Lab
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

define help

Supported targets: 'develop', 'sdist', 'clean', 'test' and 'pypi'

The 'develop' target creates an editable install (aka develop mode).

The 'sdist' target creates source distributions for each of the subprojects.

The 'clean' target undoes the effect of 'sdist' and 'develop'.

The 'test' target runs the unit tests.

The 'pypi' target publishes the current commit of the project to PyPI after
asserting that it is being invoked on a continuous integration server, that the
working copy and the index are clean and ensuring .

endef
export help
.PHONY: help
help:
	@echo "$$help"


python=python2.7

develop_projects=lib core jenkins spark mesos toil
sdist_projects=lib agent spark-tools mesos-tools
all_projects=lib core agent jenkins spark spark-tools mesos mesos-tools toil

green=\033[0;32m
normal=\033[0m
red=\033[0;31m


.SUFFIXES:


define _develop
.PHONY: develop_$1
develop_$1: _check_venv $1/version.py $1/MANIFEST.in
	cd $1 && $(python) setup.py egg_info develop
endef
$(foreach project,$(develop_projects),$(eval $(call _develop,$(project))))
.PHONY: develop
develop: $(foreach project,$(develop_projects),develop_$(project))

# Mirrors the intra-project dependencies declared in each setup.py

develop_agent: develop_lib
develop_core: develop_lib
develop_jenkins: develop_lib develop_core
develop_mesos: develop_lib develop_core
develop_spark: develop_lib develop_core
develop_toil: develop_lib develop_core develop_mesos

define _sdist
.PHONY: sdist_$1
sdist_$1: _check_venv $1/version.py $1/MANIFEST.in
	cd $1 && $(python) setup.py sdist
endef
$(foreach project,$(sdist_projects),$(eval $(call _sdist,$(project))))
.PHONY: sdist
sdist: $(foreach project,$(sdist_projects),sdist_$(project))


define _pypi
.PHONY: pypi_$1
pypi_$1: _check_venv _check_running_on_jenkins _check_clean_working_copy $1/version.py $1/MANIFEST.in
	cd $1 && $(python) setup.py egg_info sdist bdist_egg upload
endef
$(foreach project,$(all_projects),$(eval $(call _pypi,$(project))))
.PHONY: pypi
pypi: $(foreach project,$(all_projects),pypi_$(project))


define _clean
.PHONY: clean_$1
# clean depends on version.py since it invokes setup.py
clean_$1: _check_venv $1/version.py
	cd $1 && $(python) setup.py clean --all && rm -rf dist src/*.egg-info MANIFEST.in version.py version.pyc
endef
$(foreach project,$(all_projects),$(eval $(call _clean,$(project))))
.PHONY: clean
clean: $(foreach project,$(all_projects),clean_$(project))


define _undevelop
.PHONY: undevelop_$1
# develop depends on version.py since it invokes setup.py
undevelop_$1: _check_venv $1/version.py
	cd $1 && $(python) setup.py develop -u
endef
$(foreach project,$(all_projects),$(eval $(call _undevelop,$(project))))
.PHONY: undevelop
undevelop: $(foreach project,$(develop_projects),undevelop_$(project))


define _test
.PHONY: test_$1
test_$1: _check_venv _check_nose sdist develop_$1
	cd $1 && $(python) -m nose --verbose
	@echo "$(green)Tests succeeded.$(normal)"
endef
$(foreach project,$(develop_projects),$(eval $(call _test,$(project))))
.PHONY: test
test: $(foreach project,$(develop_projects),test_$(project))


.PHONY: _check_venv
_check_venv:
	@$(python) -c 'import sys; sys.exit( int( not hasattr(sys, "real_prefix") ) )' \
		|| ( echo "$(red)A virtualenv must be active.$(normal)" ; false )


.PHONY: _check_nose
_check_nose: _check_venv
	$(python) -c 'import nose' \
		|| ( echo "$(red)The 'nose' package must be installed.$(normal)" ; false )


.PHONY: _check_clean_working_copy
_check_clean_working_copy:
	@echo "$(green)Checking if your working copy is clean ...$(normal)"
	@git diff --exit-code > /dev/null \
		|| ( echo "$(red)Your working copy looks dirty.$(normal)" ; false )
	@git diff --cached --exit-code > /dev/null \
		|| ( echo "$(red)Your index looks dirty.$(normal)" ; false )
	@test -z "$$(git ls-files --other --exclude-standard --directory)" \
		|| ( echo "$(red)You have are untracked files:$(normal)" \
			; git ls-files --other --exclude-standard --directory \
			; false )


.PHONY: _check_running_on_jenkins
_check_running_on_jenkins:
	@echo "$(green)Checking if running on Jenkins ...$(normal)"
	test -n "$$BUILD_NUMBER" \
		|| ( echo "$(red)This target should only be invoked on Jenkins.$(normal)" ; false )


%/version.py: version.py
	$(python) $< > $@


%/MANIFEST.in: MANIFEST.in
	cp $< $@
