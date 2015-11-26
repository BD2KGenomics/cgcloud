cgcloud_version = '1.2.1'
bd2k_python_lib_version = '1.10.dev5'

if __name__ == '__main__':
    import os
    is_release_build = os.environ.get('is_release_build') == 'true'
    suffix = '' if is_release_build else '.dev' + os.environ.get( 'BUILD_NUMBER', '0' )
    print "cgcloud_version='%s'" % ( cgcloud_version + suffix, )
    print "bd2k_python_lib_version = '%s'" % bd2k_python_lib_version
