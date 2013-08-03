import os
from cghub.cloud.util import mkdir_p

APPLICATION_NAME = 'cgcloud'


def config_file_path(file_name, mkdir=False):
    # see http://standards.freedesktop.org/basedir-spec/basedir-spec-latest.html
    default_config_dir_path = os.path.join( os.path.expanduser( '~' ), '.config' )
    config_dir_path = os.environ.get( 'XDG_CONFIG_HOME', default_config_dir_path )
    app_config_dir_path = os.path.join( config_dir_path, APPLICATION_NAME )
    if mkdir: mkdir_p( app_config_dir_path )
    return os.path.join( app_config_dir_path, file_name )


