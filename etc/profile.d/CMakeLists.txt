configure_file(
    libdnf-python-plugin.sh.in
    ${CMAKE_CURRENT_BINARY_DIR}/libdnf-python-plugin.sh
    @ONLY
)

install(
    FILES
        ${CMAKE_CURRENT_BINARY_DIR}/libdnf-python-plugin.sh
    DESTINATION
        ${SYSCONFDIR}/profile.d
)

