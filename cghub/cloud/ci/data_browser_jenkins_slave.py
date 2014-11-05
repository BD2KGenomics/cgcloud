from StringIO import StringIO
import string
import random

from cghub.cloud.core import fabric_task
from cghub.fabric.operations import sudo
from fabric.operations import put, run
from cghub.cloud.ci.jenkins_slave import BUILD_USER

from .generic_jenkins_slaves import UbuntuTrustyGenericJenkinsSlave


class DataBrowserJenkinsSlave( UbuntuTrustyGenericJenkinsSlave ):
    def __init__( self, ctx ):
        super( DataBrowserJenkinsSlave, self ).__init__( ctx )
        self.mysql_root_password = self.generate_password( 8 )
        self.mysql_user_password = self.generate_password( 8 )

    def recommended_instance_type( self ):
        return 'c3.large'

    def generate_password( self, length ):
        charset = string.ascii_uppercase + string.digits + string.ascii_lowercase
        return ''.join( random.choice( charset ) for _ in range( length ) )

    def _setup_package_repos( self ):
        super( DataBrowserJenkinsSlave, self )._setup_package_repos( )
        self.__add_firefox_ppa( )

    @fabric_task
    def __add_firefox_ppa( self ):
        sudo( 'sudo add-apt-repository -y ppa:ubuntu-mozilla-security/ppa' )

    def _pre_install_packages( self ):
        super( DataBrowserJenkinsSlave, self )._pre_install_packages( )
        self.pre_seed_mysql_server_password( )

    @fabric_task
    def pre_seed_mysql_server_password( self ):
        for suffix in ( '', '_again' ):
            self._debconf_set_selection(
                'mysql-server mysql-server/root_password%s select %s' % (
                    suffix, self.mysql_root_password ), quiet=True )
        self.__write_mycnf_password( 'root', self.mysql_root_password )

    def __write_mycnf_password( self, user, password ):
        mycnf = StringIO( '[client]\nuser=%s\npassword=%s' % (user, password ) )
        put( local_path=mycnf, remote_path='~/.my.cnf', mode=0400 )

    def _list_packages_to_install( self ):
        return super( DataBrowserJenkinsSlave, self )._list_packages_to_install( ) + [
            'mysql-server',  # for the browser
            'firefox',  # for the Selenium tests
            'xvfb',  # to run Firefox in headless mode
            'libmysqlclient-dev',  # for mysql-python, one of the browser's dependencies
            'libxml2-dev',  # for lxml, one of the browser's dependencies
            'libxslt-dev' ]  # ditto

    def _post_install_packages( self ):
        super( DataBrowserJenkinsSlave, self )._post_install_packages( )
        self.__create_mysql_user( )
        self.__create_mysql_user_mycnf( )
        self.__setup_browser_prereqs( )

    @fabric_task
    def __setup_browser_prereqs( self ):
        # FIXME: somehow remove hardcoded path (use url to file in BB, command line option, git submodule)?
        put( local_path='/Users/hannes/workspace/cghub/cghub-data-browser/requirements.txt' )
        sudo( "pip install -r requirements.txt" )

    @fabric_task( )
    def __create_mysql_user( self ):
        user = BUILD_USER
        password = self.mysql_user_password
        self.__run_mysql_command(
            "CREATE USER '{user}'@'localhost' IDENTIFIED BY '{password}';".format( **locals( ) ) )
        for prefix in ( 'test_', '' ):
            database = prefix + 'cghub_data_browser'
            self.__run_mysql_command(
                "GRANT ALL PRIVILEGES ON {database} . * TO '{user}'@'localhost';".format(
                    **locals( ) ) )
        self.__run_mysql_command( 'FLUSH PRIVILEGES;' )

    def __run_mysql_command( self, sql ):
        # FIXME: escape quotes in command
        run( 'echo "%s" | mysql' % sql )

    @fabric_task( user=BUILD_USER )
    def __create_mysql_user_mycnf( self ):
        self.__write_mycnf_password( BUILD_USER, self.mysql_user_password )

