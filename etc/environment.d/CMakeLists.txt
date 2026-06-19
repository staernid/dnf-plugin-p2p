configure_file(
    libdnf-python-plugin.conf.in
    ${CMAKE_CURRENT_BINARY_DIR}/libdnf-python-plugin.conf
    @ONLY
)

install(
    FILES
        ${CMAKE_CURRENT_BINARY_DIR}/libdnf-python-plugin.conf
    DESTINATION
        ${SYSCONFDIR}/environment.d
)

