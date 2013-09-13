from cghub.cloud.commands import *
from cghub.cloud.generic_boxes import *

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
    ListCommand,
    ListImages,
    UploadKeyCommand ]
