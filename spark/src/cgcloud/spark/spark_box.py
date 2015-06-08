from collections import namedtuple
import json
import re
from textwrap import dedent
from StringIO import StringIO
import logging

from fabric.context_managers import settings
from lxml import etree
from lxml.builder import ElementMaker
from fabric.operations import run, put, os
from bd2k.util.strings import interpolate as fmt

from cgcloud.core import fabric_task
from cgcloud.core.common_iam_policies import ec2_read_only_policy
from cgcloud.core.generic_boxes import GenericUbuntuTrustyBox
from cgcloud.fabric.operations import sudo, remote_open
from cgcloud.lib.util import abreviated_snake_case_class_name

log = logging.getLogger( __name__ )

hadoop_version = '2.6.0'

spark_version = '1.2.1'

user = 'sparkbox'

install_dir = '/opt/sparkbox'

var_dir = '/var/lib/sparkbox'

log_dir = "/var/log/sparkbox"

ephemeral_dir = '/mnt/ephemeral'

persistent_dir = '/mnt/persistent'

hdfs_replication = 1

Service = namedtuple( 'Service', [
    'init_name',
    'description',
    'start_script',
    'stop_script' ] )


def hdfs_service( name ):
    script = '{install_dir}/hadoop/sbin/hadoop-daemon.sh {action} {name}'
    return Service(
        init_name='hdfs-' + name,
        description=fmt( "Hadoop DFS {name} service" ),
        start_script=fmt( script, action='start' ),
        stop_script=fmt( script, action='stop' ) )


def spark_service( name, script_suffix=None ):
    if script_suffix is None: script_suffix = name
    script = '{install_dir}/spark/sbin/{action}-{script_suffix}.sh'
    return Service(
        init_name='spark-' + name,
        description=fmt( "Spark {name} service" ),
        start_script=fmt( script, action='start' ),
        stop_script=fmt( script, action='stop' ) )


hadoop_services = {
    'master': [ hdfs_service( 'namenode' ), hdfs_service( 'secondarynamenode' ) ],
    'slave': [ hdfs_service( 'datanode' ) ] }

spark_services = {
    'master': [ spark_service( 'master' ) ],
    # FIXME: The start-slaves.sh script actually does ssh localhost on a slave so I am not sure
    # this is the right thing to do. OTOH, it is the only script starts Tachyon and sets up the
    # spark:// URL pointing at the master. We would need to duplicate some of its functionality
    # if we wanted to eliminate the ssh call.
    'slave': [ spark_service( 'slave', 'slaves' ) ] }


class SparkBox( GenericUbuntuTrustyBox ):
    """
    A node in a Spark cluster. Workers and the master undergo the same setup. Whether a node acts
    as a master or a slave is determined at boot time, via user data. All slave nodes will be
    passed the IP of the master node. This implies that the master is started first. As soon as
    its private IP is assigned, typically seconds after the reservation has been submitted,
    the slaves can be started up.
    """

    def other_accounts( self ):
        return super( SparkBox, self ).other_accounts( ) + [ user ]

    def __init__( self, ctx ):
        super( SparkBox, self ).__init__( ctx )
        self.lazy_dirs = None

    def _populate_security_group( self, group_name ):
        return super( SparkBox, self )._populate_security_group( group_name ) + [
            dict( ip_protocol='tcp', from_port=0, to_port=65535,
                  src_security_group_name=group_name ),
            dict( ip_protocol='udp', from_port=0, to_port=65535,
                  src_security_group_name=group_name ) ]

    @fabric_task
    def _setup_package_repos( self ):
        super( SparkBox, self )._setup_package_repos( )
        sudo( 'add-apt-repository -y ppa:webupd8team/java' )
        sudo( 'echo debconf shared/accepted-oracle-license-v1-1 select true '
              '| sudo debconf-set-selections' )
        sudo( 'echo debconf shared/accepted-oracle-license-v1-1 seen true '
              '| sudo debconf-set-selections' )

    def _list_packages_to_install( self ):
        return super( SparkBox, self )._list_packages_to_install( ) + [
            'oracle-java7-set-default' ]

    def _pre_install_packages( self ):
        super( SparkBox, self )._pre_install_packages( )
        self.__setup_application_user( )

    def _post_install_packages( self ):
        super( SparkBox, self )._post_install_packages( )
        self._propagate_authorized_keys( user, user )
        self.__setup_ssh_config( )
        self.__create_spark_keypair( )
        self.lazy_dirs = set( )
        self.__install_hadoop( )
        self.__install_spark( )
        self.__install_sparkbox_tools( )
        self.__setup_path( )

    @fabric_task
    def __setup_ssh_config( self ):
        with remote_open( '/etc/ssh/ssh_config', use_sudo=True ) as f:
            f.write( heredoc( """
                Host spark-master
                    CheckHostIP no
                    HashKnownHosts no""" ) )

    @fabric_task
    def __setup_application_user( self ):
        sudo( fmt( 'useradd '
                   '--home /home/{user} '
                   '--create-home '
                   '--user-group '
                   '--shell /bin/bash {user}' ) )

    def __ec2_keypair_name( self, ctx ):
        return user + '@' + ctx.to_aws_name( self.role( ) )

    @fabric_task( user=user )
    def __create_spark_keypair( self ):
        self._provide_imported_keypair( ec2_keypair_name=self.__ec2_keypair_name( self.ctx ),
                                        private_key_path=fmt( "/home/{user}/.ssh/id_rsa" ),
                                        overwrite_ec2=True )
        # This trick allows us to roam freely within the cluster as the app user while still
        # being able to have keypairs in authorized_keys managed by cgcloudagent such that
        # external users can login as the app user, too. The trick depends on AuthorizedKeysFile
        # defaulting to or being set to .ssh/autorized_keys and .ssh/autorized_keys2 in sshd_config
        run( "cd .ssh && cat id_rsa.pub >> authorized_keys2" )

    @fabric_task
    def __install_sparkbox_tools( self ):
        """
        Installs the spark-master-discovery init script and its companion spark-tools. The latter
        is a Python package distribution that's included in cgcloud-spark as a resource. This is
        in contrast to the cgcloud agent, which is a standalone distribution.
        """
        tools_dir = install_dir + '/tools'
        admin = self.admin_account( )
        sudo( fmt( 'mkdir -p {tools_dir} {persistent_dir} {ephemeral_dir}' ) )
        sudo( fmt( 'chown {admin}:{admin} {tools_dir}' ) )
        run( fmt( 'virtualenv --no-pip {tools_dir}' ) )
        run( fmt( '{tools_dir}/bin/easy_install pip==1.5.2' ) )
        spark_tools_artifacts = ' '.join( self._project_artifacts( 'spark-tools' ) )
        with settings( forward_agent=True ):
            run( fmt( '{tools_dir}/bin/pip install {spark_tools_artifacts}' ) )
        sudo( fmt( 'chown -R root:root {tools_dir}' ) )
        spark_tools = "SparkTools(**%r)" % dict( user=user,
                                                 install_dir=install_dir,
                                                 ephemeral_dir=ephemeral_dir,
                                                 persistent_dir=persistent_dir,
                                                 lazy_dirs=self.lazy_dirs )
        self._register_init_script(
            "sparkbox",
            heredoc( """
                description "Spark/HDFS master discovery"
                console log
                start on runlevel [2345]
                stop on runlevel [016]
                pre-start script
                {tools_dir}/bin/python2.7 - <<END
                import logging
                logging.basicConfig( level=logging.INFO )
                from cgcloud.spark_tools import SparkTools
                spark_tools = {spark_tools}
                spark_tools.start()
                end script
                post-stop script
                {tools_dir}/bin/python2.7 - <<END
                import logging
                logging.basicConfig( level=logging.INFO )
                from cgcloud.spark_tools import SparkTools
                spark_tools = {spark_tools}
                spark_tools.stop()
                END
                end script""" ) )
        script_path = "/usr/local/bin/sparkbox-manage-slaves"
        put( remote_path=script_path, use_sudo=True, local_path=StringIO( heredoc( """
            #!{tools_dir}/bin/python2.7
            import sys
            import logging
            logging.basicConfig( level=logging.INFO )
            from cgcloud.spark_tools import SparkTools
            spark_tools = {spark_tools}
            spark_tools.manage_slaves( slaves_to_add=sys.argv[1:] )""" ) ) )
        sudo( fmt( "chown root:root {script_path} && chmod 755 {script_path}" ) )

    @fabric_task
    def __setup_path( self ):
        globally = True
        if globally:
            with remote_open( '/etc/environment', use_sudo=True ) as f:
                new_path = [ fmt( '{install_dir}/{package}/bin' )
                    for package in ('spark', 'hadoop') ]
                self.__patch_etc_environment( f, new_path )
        else:
            for _user in ( user, self.admin_account( ) ):
                with settings( user=_user ):
                    with remote_open( '~/.profile' ) as f:
                        f.write( '\n' )
                        for package in ('spark', 'hadoop'):
                            # We don't include sbin here because too many file names collide in
                            # Spark's and Hadoop's sbin
                            f.write( fmt( 'PATH="$PATH:{install_dir}/{package}/bin"\n' ) )

    env_entry_re = re.compile( r'^\s*([^=\s]+)\s*=\s*"?(.*?)"?\s*$' )

    @classmethod
    def __patch_etc_environment( cls, env_file, dirs ):
        r"""
        >>> f=StringIO('FOO = " BAR " \n  PATH =foo:bar\nBLA="FASEL"')
        >>> f.seek(0,2) # seek to end as if file was opened with 'a'
        >>> SparkBox._SparkBox__patch_etc_environment( f, [ "new" ] )
        >>> f.getvalue()
        'BLA="FASEL"\nFOO=" BAR "\nPATH="foo:bar:new"\n'
        """

        def parse_entry( s ):
            m = cls.env_entry_re.match( s )
            return m.group( 1 ), m.group( 2 )

        env_file.seek( 0 )
        env = dict( parse_entry( _ ) for _ in env_file.read( ).splitlines( ) )
        path = env[ 'PATH' ].split( ':' )
        path.extend( dirs )
        env[ 'PATH' ] = ':'.join( path )
        env_file.seek( 0 )
        env_file.truncate( 0 )
        for var in sorted( env.items( ) ): env_file.write( '%s="%s"\n' % var )

    @fabric_task
    def __install_hadoop( self ):
        # Download and extract Hadoop
        path = fmt( 'hadoop/common/hadoop-{hadoop_version}/hadoop-{hadoop_version}.tar.gz' )
        self.__install_apache_package( path )

        # Add environment variables to hadoop_env.sh
        hadoop_env = dict(
            HADOOP_LOG_DIR=self.__lazy_mkdir( log_dir, "hadoop" ),
            JAVA_HOME='/usr/lib/jvm/java-7-oracle' )
        hadoop_env_sh_path = fmt( "{install_dir}/hadoop/etc/hadoop/hadoop-env.sh" )
        with remote_open( hadoop_env_sh_path, use_sudo=True ) as hadoop_env_sh:
            hadoop_env_sh.write( '\n' )
            for name, value in hadoop_env.iteritems( ):
                hadoop_env_sh.write( fmt( 'export {name}="{value}"\n' ) )

        # Configure HDFS
        hdfs_dir = var_dir + "/hdfs"
        put( use_sudo=True,
             remote_path=fmt( '{install_dir}/hadoop/etc/hadoop/hdfs-site.xml' ),
             local_path=StringIO( self.__to_hadoop_xml_config( {
                 'dfs.replication': str( hdfs_replication ),
                 'dfs.permissions': 'false',
                 'dfs.name.dir': self.__lazy_mkdir( hdfs_dir, 'name', persistent=True ),
                 'dfs.data.dir': self.__lazy_mkdir( hdfs_dir, 'data', persistent=True ),
                 'fs.checkpoint.dir': self.__lazy_mkdir( hdfs_dir, 'checkpoint', persistent=True ),
                 'dfs.namenode.http-address': 'spark-master:50070',
                 'dfs.namenode.secondary.http-address': 'spark-master:50090' } ) ) )

        # Configure Hadoop
        put( use_sudo=True,
             remote_path=fmt( '{install_dir}/hadoop/etc/hadoop/core-site.xml' ),
             local_path=StringIO( self.__to_hadoop_xml_config( {
                 'fs.default.name': 'hdfs://spark-master:8020' } ) ) )

        # Make shell auto completion easier
        sudo( fmt( 'find {install_dir}/hadoop -name "*.cmd" | xargs rm' ) )

        # Install upstart jobs
        self.__register_upstart_jobs( hadoop_services )

    @fabric_task( user=user )
    def __format_hdfs( self ):
        run( fmt( '{install_dir}/hadoop/bin/hadoop namenode -format -nonInteractive' ) )

    def __start_services( self ):
        # This should trigger the launch of the Hadoop and Spark services
        self._run_init_script( 'sparkbox' )

    def __lazy_mkdir( self, parent, name, persistent=False ):
        """
        __lazy_mkdir( '/foo', 'dir', True ) creates /foo/dir now and ensures that
        /mnt/persistent/foo/dir is created and bind-mounted into /foo/dir when the box starts.
        Likewise, __lazy_mkdir( '/foo', 'dir', False) creates /foo/dir now and ensures that
        /mnt/ephemeral/foo/dir is created and bind-mounted into /foo/dir when the box starts.
        Note that at start-up time, /mnt/persistent may be reassigned  to /mnt/ephemeral if no
        EBS volume is mounted at /mnt/persistent.
        """
        assert '/' not in name
        assert parent.startswith( '/' )
        for location in ( persistent_dir, ephemeral_dir ):
            assert location.startswith( '/' )
            assert not location.startswith( parent ) and not parent.startswith( location )
        logical_path = parent + '/' + name
        sudo( 'mkdir -p "%s"' % logical_path )
        self.lazy_dirs.add( ( parent, name, persistent ) )
        return logical_path

    @fabric_task
    def __install_spark( self ):
        # Download and extract Spark
        path = fmt( 'spark/spark-{spark_version}/spark-{spark_version}-bin-hadoop2.4.tgz' )
        self.__install_apache_package( path )

        spark_dir = var_dir + "/spark"

        # Add environment variables to spark_env.sh
        spark_env_sh_path = fmt( "{install_dir}/spark/conf/spark-env.sh" )
        sudo( fmt( "cp {spark_env_sh_path}.template {spark_env_sh_path}" ) )
        spark_env = dict(
            SPARK_LOG_DIR=self.__lazy_mkdir( log_dir, "spark" ),
            SPARK_WORKER_DIR=self.__lazy_mkdir( spark_dir, "work" ),
            SPARK_LOCAL_DIRS=self.__lazy_mkdir( spark_dir, "local" ),
            JAVA_HOME='/usr/lib/jvm/java-7-oracle',
            SPARK_MASTER_IP='spark-master',
            HADOOP_CONF_DIR=fmt( "{install_dir}/hadoop/etc/hadoop" ) )
        with remote_open( spark_env_sh_path, use_sudo=True ) as spark_env_sh:
            spark_env_sh.write( '\n' )
            for name, value in spark_env.iteritems( ):
                spark_env_sh.write( fmt( 'export {name}="{value}"\n' ) )

        # Configure Spark properties
        spark_defaults = {
            'spark.eventLog.enabled': 'true',
            'spark.eventLog.dir': self.__lazy_mkdir( spark_dir, "history" ),
            'spark.master': 'spark://spark-master:7077'
        }
        spark_defaults_conf_path = fmt( "{install_dir}/spark/conf/spark-defaults.conf" )
        sudo( fmt( "cp {spark_defaults_conf_path}.template {spark_defaults_conf_path}" ) )
        with remote_open( spark_defaults_conf_path, use_sudo=True ) as spark_defaults_conf:
            for name, value in spark_defaults.iteritems( ):
                spark_defaults_conf.write( fmt( "{name}\t{value}\n" ) )

        # Make shell auto completion easier
        sudo( fmt( 'find {install_dir}/spark -name "*.cmd" | xargs rm' ) )

        # Install upstart jobs
        self.__register_upstart_jobs( spark_services )

    def __register_upstart_jobs( self, service_map ):
        for node_type, services in service_map.iteritems( ):
            start_on = "sparkbox-start-" + node_type
            for service in services:
                self._register_init_script(
                    service.init_name,
                    heredoc( """
                        description "{service.description}"
                        console log
                        start on {start_on}
                        stop on runlevel [016]
                        setuid {user}
                        setgid {user}
                        env USER={user}
                        pre-start exec {service.start_script}
                        post-stop exec {service.stop_script}""" ) )
                start_on = "started " + service.init_name

    def __install_apache_package( self, path ):
        """
        Download the given file from an Apache download mirror.

        Some mirrors may be down or serve crap, so we may need to retry this a couple of times.
        """
        # TODO: run Fabric tasks with a different manager, so we don't need to catch SystemExit
        components = path.split( '/' )
        package, tarball = components[ 0 ], components[ -1 ]
        tries = iter( xrange( 3 ) )
        while True:
            try:
                mirror_url = self.__apache_s3_mirror_url( path )
                if run( "curl -Ofs '%s'" % mirror_url, warn_only=True ).failed:
                    mirror_url = self.__apache_official_mirror_url( path )
                    run( "curl -Ofs '%s'" % mirror_url )
                try:
                    sudo( fmt( 'mkdir -p {install_dir}/{package}' ) )
                    sudo( fmt( 'tar -C {install_dir}/{package} '
                               '--strip-components=1 -xzf {tarball}' ) )
                    return
                finally:
                    run( fmt( 'rm {tarball}' ) )
            except SystemExit:
                if next( tries, None ) is None:
                    raise
                else:
                    log.warn( "Could not download or extract the package, retrying ..." )

    # FIMXE: this might have more general utility

    def __apache_official_mirror_url( self, path ):
        mirrors = run( "curl -fs 'http://www.apache.org/dyn/closer.cgi?path=%s&asjson=1'" % path )
        mirrors = json.loads( mirrors )
        mirror = mirrors[ 'preferred' ]
        url = mirror + path
        return url

    def __apache_s3_mirror_url( self, path ):
        return 'https://s3-us-west-2.amazonaws.com/bd2k-artifacts/cgcloud/' + os.path.basename(
            path )

    @staticmethod
    def __to_hadoop_xml_config( properties ):
        """
        >>> print SparkBox._SparkBox__to_hadoop_xml_config( {'foo' : 'bar'} )
        <?xml version='1.0' encoding='utf-8'?>
        <?xml-stylesheet type='text/xsl' href='configuration.xsl'?>
        <configuration>
          <property>
            <name>foo</name>
            <value>bar</value>
          </property>
        </configuration>
        <BLANKLINE>
        """
        E = ElementMaker( )
        tree = etree.ElementTree(
            E.configuration(
                *(E.property( E.name( name ), E.value( value ) )
                    for name, value in properties.iteritems( )) ) )
        tree.getroot( ).addprevious( etree.ProcessingInstruction(
            "xml-stylesheet", "type='text/xsl' href='configuration.xsl'" ) )
        return etree.tostring( tree, pretty_print=True, xml_declaration=True, encoding='utf-8' )

    def _get_iam_ec2_role( self ):
        role_name, policies = super( SparkBox, self )._get_iam_ec2_role( )
        role_name += '--' + abreviated_snake_case_class_name( SparkBox )
        policies.update( dict(
            ec2_read_only=ec2_read_only_policy,
            ec2_spark_box=dict( Version="2012-10-17", Statement=[
                dict( Effect="Allow", Resource="*", Action="ec2:CreateTags" ),
                dict( Effect="Allow", Resource="*", Action="ec2:CreateVolume" ),
                dict( Effect="Allow", Resource="*", Action="ec2:AttachVolume" ) ] ) ) )
        return role_name, policies

    def _image_name_prefix( self ):
        # Make this class and its subclasses use the same image
        return "spark-box"

    def _security_group_name( self ):
        # Make this class and its subclasses use the same security group
        return "spark-box"


class SparkMaster( SparkBox ):
    """
    A SparkBox that serves as the Spark/Hadoop master
    """

    def __init__( self, ctx, ebs_volume_size=0 ):
        super( SparkMaster, self ).__init__( ctx )
        self.preparation_args = None
        self.preparation_kwargs = None
        self.ebs_volume_size = ebs_volume_size

    def prepare( self, *args, **kwargs ):
        # Stash awat arguments to prepare() so we can use them when cloning the slaves
        self.preparation_args = args
        self.preparation_kwargs = kwargs
        return super( SparkBox, self ).prepare( *args, **kwargs )

    def _populate_instance_tags( self, tags_dict ):
        super( SparkMaster, self )._populate_instance_tags( tags_dict )
        tags_dict[ 'spark_master' ] = self.instance_id
        tags_dict[ 'ebs_volume_size' ] = self.ebs_volume_size

    def _post_install_packages( self ):
        super( SparkMaster, self )._post_install_packages( )
        # If a master is setup from a base image (via Box.setup()) we can start the services. A
        # generic SparkBox would block waiting for the spark_master tag.
        self.__start_services( )

    def clone( self, num_slaves, slave_instance_type, ebs_volume_size ):
        """
        Create a number of slave boxes that are connected to this master.
        """
        master = self
        first_slave = SparkSlave( master.ctx, num_slaves, master.instance_id, ebs_volume_size )
        args = master.preparation_args
        kwargs = master.preparation_kwargs.copy( )
        kwargs[ 'instance_type' ] = slave_instance_type
        first_slave.prepare( *args, **kwargs )
        other_slaves = first_slave.create( wait_ready=False,
                                           cluster_ordinal=master.cluster_ordinal + 1 )
        all_slaves = [ first_slave ] + other_slaves
        return all_slaves


class SparkSlave( SparkBox ):
    """
    A SparkBox that serves as the Spark/Hadoop slave. Slaves are cloned from a master box by
    calling the SparkMaster.clone() method.
    """

    def __init__( self, ctx, num_slaves=1, spark_master_id=None, ebs_volume_size=0 ):
        super( SparkSlave, self ).__init__( ctx )
        self.num_slaves = num_slaves
        self.spark_master_id = spark_master_id
        self.ebs_volume_size = ebs_volume_size

    def _populate_instance_creation_args( self, image, kwargs ):
        kwargs.update( dict( min_count=self.num_slaves, max_count=self.num_slaves ) )
        return super( SparkSlave, self )._populate_instance_creation_args( image, kwargs )

    def _populate_instance_tags( self, tags_dict ):
        super( SparkSlave, self )._populate_instance_tags( tags_dict )
        if self.spark_master_id:
            tags_dict[ 'spark_master' ] = self.spark_master_id
            tags_dict[ 'ebs_volume_size' ] = self.ebs_volume_size


def heredoc( s ):
    if s[ 0 ] == '\n': s = s[ 1: ]
    if s[ -1 ] != '\n': s += '\n'
    return fmt( dedent( s ), skip_frames=1 )
