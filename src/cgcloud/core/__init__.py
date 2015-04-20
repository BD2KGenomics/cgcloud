from cgcloud.core.commands import *
from cgcloud.core.generic_boxes import *

BOXES = [
    GenericCentos6Box,
    GenericCentos5Box,
    GenericUbuntuLucidBox,
    GenericUbuntuPreciseBox,
    GenericUbuntuSaucyBox,
    GenericUbuntuTrustyBox,
    GenericUbuntuUtopicBox,
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
