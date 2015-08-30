from cgcloud.core.commands import *
from cgcloud.core.deprecated import is_deprecated
from cgcloud.core.generic_boxes import *


def __fail_deprecated( artifacts ):
    for artifact in artifacts:
        if is_deprecated( artifact ):
            raise DeprecationWarning( artifact )
    return artifacts


BOXES = __fail_deprecated( [
    GenericCentos6Box,
    GenericUbuntuPreciseBox,
    GenericUbuntuTrustyBox,
    GenericUbuntuUtopicBox,
    GenericUbuntuVividBox,
    GenericFedora21Box,
    GenericFedora22Box ] )

COMMANDS = __fail_deprecated( [
    ListRolesCommand,
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
    ResetSecurityCommand ] )

test_namespace_suffix_length = 8
