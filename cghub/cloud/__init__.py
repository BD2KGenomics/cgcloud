import os
from cghub.cloud.util import mkdir_p

APPLICATION_NAME = 'cgcloud'


def config_file_path(path_components, mkdir=False):
    """
    Returns the path of a configuration file. In accordance with freedesktop.org's XDG Base
    `Directory Specification <http://standards.freedesktop.org/basedir-spec/basedir-spec-latest
    .html>`_, the configuration files are located in the ~/.config/cgcloud directory.

    :param path_components: EITHER a string containing the desired name of the
    configuration file OR an iterable of strings, the last component of which denotes the desired
    name of the config file, all preceding components denoting a chain of nested subdirectories
    of the config directory.

    :param mkdir: if True, this method ensures that all directories in the returned path exist,
    creating them if necessary

    :return: the full path to the configuration file

    >>> os.environ['HOME']='/home/hannes'

    >>> config_file_path(['bar'])
    '/home/hannes/.config/cgcloud/bar'

    >>> config_file_path(['dir','file'])
    '/home/hannes/.config/cgcloud/dir/file'
    """
    default_config_dir_path = os.path.join( os.path.expanduser( '~' ), '.config' )
    config_dir_path = os.environ.get( 'XDG_CONFIG_HOME', default_config_dir_path )
    app_config_dir_path = os.path.join( config_dir_path, APPLICATION_NAME )
    path = os.path.join( app_config_dir_path, *path_components )
    if mkdir: mkdir_p( os.path.dirname( path ) )
    return path


