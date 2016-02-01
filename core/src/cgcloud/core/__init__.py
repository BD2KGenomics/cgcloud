from cgcloud.core.deprecated import is_deprecated


def __fail_deprecated( artifacts ):
    for artifact in artifacts:
        if is_deprecated( artifact ):
            raise DeprecationWarning( artifact )
    return artifacts


def roles( ):
    from cgcloud.core.generic_boxes import (GenericCentos6Box,
                                            GenericUbuntuPreciseBox,
                                            GenericUbuntuTrustyBox,
                                            GenericUbuntuVividBox,
                                            GenericFedora21Box,
                                            GenericFedora22Box)
    return __fail_deprecated( sorted( locals( ).values( ), key=lambda cls: cls.__name__ ) )


def command_classes( ):
    from cgcloud.core.commands import (ListRolesCommand,
                                       CreateCommand,
                                       RecreateCommand,
                                       StartCommand,
                                       StopCommand,
                                       RebootCommand,
                                       TerminateCommand,
                                       ImageCommand,
                                       ShowCommand,
                                       SshCommand,
                                       RsyncCommand,
                                       ListCommand,
                                       ListImagesCommand,
                                       DeleteImageCommand,
                                       RegisterKeyCommand,
                                       CleanupCommand,
                                       UpdateInstanceProfile,
                                       ResetSecurityCommand,
                                       ListOptionsCommand)
    from cgcloud.core.cluster_commands import (CreateClusterCommand,
                                               StartClusterCommand,
                                               StopClusterCommand,
                                               TerminateClusterCommand,
                                               SshClusterCommand,
                                               RsyncClusterCommand,
                                               GrowClusterCommand)
    return __fail_deprecated( sorted( locals( ).values( ), key=lambda cls: cls.__name__ ) )


test_namespace_suffix_length = 11
