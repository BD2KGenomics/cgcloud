from cgcloud.bd2k.ci.jobtree_jenkins_slave import JobtreeJenkinsSlave

class ToilScriptsJenkinsSlave( JobtreeJenkinsSlave ):
    def _list_packages_to_install( self ):
        return super( JobtreeJenkinsSlave, self )._list_packages_to_install( ) + [
            'samtools', 'docker.io', 'unzip'
        ]
