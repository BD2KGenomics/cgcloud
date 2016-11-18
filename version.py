cgcloud_version = '1.6.0a1'
bd2k_python_lib_dep = 'bd2k-python-lib>=1.14a1.dev37'
boto_dep = 'boto==2.38.0'
fabric_dep = 'Fabric==1.10.3'
s3am_dep = 's3am==2.0a1.dev105'


def main( ):
    import os
    from pkg_resources import parse_version
    is_release_build = not parse_version( cgcloud_version ).is_prerelease
    suffix = '' if is_release_build else '.dev' + os.environ.get( 'BUILD_NUMBER', '0' )
    for name, value in globals( ).items( ):
        if name.startswith( 'cgcloud_' ):
            value += suffix
        if name.split( '_' )[ -1 ] in ('dep', 'version'):
            print "%s='%s'" % (name, value)


if __name__ == '__main__':
    main( )
