def pytest_configure( config ):
    # One of PyTest's nanny features is to redirect stdin to a thing that refuses to be read
    # from. It is supposed to prevent tests from accidentally getting blocked waiting for user
    # input. I have never in my life had a test that blocked on stdin without it being completely
    #  obvious, even without this nanny redirect. However, I've repeatedly run into issues where
    #  this redirection gets in the way, mainly with Fabric:
    #
    # http://jenkins.cgcloud.info/job/cgcloud/304/testReport/junit/src.cgcloud.core.test.test_core/CoreTests/test_generic_fedora_22_box/
    #
    # This workaround disables that nanny feature.
    capman = config.pluginmanager.get_plugin( 'capturemanager' )
    if capman._capturing.in_ is not None:
        capman._capturing.in_.done( )
        capman._capturing.in_ = None
