cgcloud_version = '1.4a1'
bd2k_python_lib_version = '1.11.dev6'
boto_version = '2.38.0'
fabric_version = '1.10.2'

if __name__ == '__main__':
    import os
    from pkg_resources import parse_version
    is_release_build = not parse_version(cgcloud_version).is_prerelease
    suffix = '' if is_release_build else '.dev' + os.environ.get( 'BUILD_NUMBER', '0' )
    for name, value in globals().items():
        if name.startswith('cgcloud_'):
            value += suffix
        if name.endswith('_version'):
            print "%s='%s'" % ( name, value )
