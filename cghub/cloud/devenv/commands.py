from cghub.cloud import BoxCommand


class GetKeysCommand( BoxCommand ):
    """
    Get a copy of the public keys that identify users on the box.
    """

    def run_on_box(self, options, box):
        box.adopt( ordinal=options.ordinal )
        box.get_keys( )



class RegisterSlavesWithMasterCommand( BoxCommand ):
    """
    Adds the given slave AMIs to Jenkins' config.xml on the master
    """
    pass # TODO: implement this