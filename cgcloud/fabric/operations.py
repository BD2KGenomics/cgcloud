from fabric.operations import sudo as real_sudo
from fabric.state import env


def sudo(command, sudo_args=None, **kwargs):
    """
    Work around https://github.com/fabric/fabric/issues/503
    """
    if sudo_args is not None:
        old_prefix = env.sudo_prefix
        env.sudo_prefix = '%s %s' % ( old_prefix, sudo_args )
    try:
        return real_sudo( command, **kwargs )
    finally:
        if sudo_args is not None:
            env.sudo_prefix = old_prefix