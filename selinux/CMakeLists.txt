install(
    FILES
        dnf-plugin-p2p.te
        dnf-plugin-p2p.fc
        dnf-plugin-p2p.if
    DESTINATION
        ${CMAKE_INSTALL_DATADIR}/selinux/packages/dnf-plugin-p2p
)
