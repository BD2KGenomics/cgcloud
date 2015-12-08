cgcloud_version = '1.2.3a1'
bd2k_python_lib_version = '1.10.dev5'
boto_version = '2.38.0'
fabric_version = '1.10.2'

if __name__ == '__main__':
    import os
    is_release_build = os.environ.get('is_release_build') == 'true'
    suffix = '' if is_release_build else '.dev' + os.environ.get( 'BUILD_NUMBER', '0' )
    for name, value in globals().items():
        if name.startswith('cgcloud_'):
            value += suffix
        if name.endswith('_version'):
            print "%s='%s'" % ( name, value )
