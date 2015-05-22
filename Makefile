all: develop sdist

develop_projects=lib core jenkins spark mesos
sdist_projects=lib agent spark-tools mesos-tools
all_projects=lib core agent jenkins spark spark-tools mesos mesos-tools

develop:
	python each_setup.py "develop" $(develop_projects)

sdist:
	python each_setup.py "sdist" $(sdist_projects)

clean:
	python each_setup.py "develop -u" $(develop_projects)
	python each_setup.py "clean --all" $(all_projects)
	for i in $(all_projects); do rm -rf $${i}/dist $${i}/src/*.egg-info; done
