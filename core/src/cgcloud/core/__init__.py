from cgcloud.core.commands import *
from cgcloud.core.generic_boxes import *

BOXES = [
    GenericCentos6Box,
    GenericCentos5Box,
    GenericUbuntuLucidBox,
    GenericUbuntuPreciseBox,
    GenericUbuntuTrustyBox,
    GenericUbuntuUtopicBox,
    GenericUbuntuVividBox,
    GenericFedora19Box,
    GenericFedora20Box ]

COMMANDS = [
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
    UpdateInstanceProfile ]

test_namespace_suffix_length = 8
