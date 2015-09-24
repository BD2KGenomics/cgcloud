from fabric.operations import run, put

from cgcloud.bd2k.ci.generic_jenkins_slaves import UbuntuTrustyGenericJenkinsSlave
from cgcloud.bd2k.ci.jenkins_master import Jenkins
from cgcloud.core.box import fabric_task
from cgcloud.core.common_iam_policies import s3_full_policy, sdb_full_policy



class CactusJenkinsSlave( UbuntuTrustyGenericJenkinsSlave ):

    def _list_packages_to_install( self ):
        return super( CactusJenkinsSlave, self )._list_packages_to_install( ) + [ 'docker.io' ]

    @fabric_task
    def _setup_benchmarks( self ):
        run ( "git clone http://github.com/joelarmstrong/cactusBenchmarks" )
        run( "cd cactusBenchmarks && git checkout ci" )
        run ( "cd cactusBenchmarks && ./testRegions/download_test_regions.sh" )
        sudo ( "cactusBenchmarks/bin/run.sh --tests evolverMammmals masterBuild")
        
    def _post_install_packages ( self ):
        super( CactusJenkinsSlave, self )._post_install_packages( )
        self._setup_benchmarks( )


        
