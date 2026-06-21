set(SYSTEMD_UNIT_DIR "/usr/lib/systemd/system"
    CACHE STRING "Directory for systemd unit files")
set(SYSUSERS_DIR "/usr/lib/sysusers.d"
    CACHE STRING "Directory for sysusers.d config files")

install(
    FILES
        dnf-p2p-proxy.service
    DESTINATION
        ${SYSTEMD_UNIT_DIR}
)

install(
    FILES
        sysusers.d/dnf-p2p.conf
    DESTINATION
        ${SYSUSERS_DIR}
)
