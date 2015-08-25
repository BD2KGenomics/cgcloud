def deprecated( artifact ):
    # TODO: print a warning when deprecated class or function is used
    artifact.__cgcloud_core_deprecated__ = True
    return artifact


def is_deprecated( artifact ):
    return getattr( artifact, '__cgcloud_core_deprecated__ ', False )
