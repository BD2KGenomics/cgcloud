from cgcloud.core.commands import *
from cgcloud.core.generic_boxes import *

BOXES = [
    GenericCentos6Box,
    GenericCentos5Box,
    GenericUbuntuLucidBox,
    GenericUbuntuMaverickBox,
    GenericUbuntuNattyBox,
    GenericUbuntuOneiricBox,
    GenericUbuntuPreciseBox,
    GenericUbuntuQuantalBox,
    GenericUbuntuRaringBox,
    GenericUbuntuSaucyBox,
    GenericUbuntuTrustyBox,
    GenericFedora17Box,
    GenericFedora18Box,
    GenericFedora19Box ]

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
    ListImages,
    RegisterKeyCommand,
    CleanupCommand ]
