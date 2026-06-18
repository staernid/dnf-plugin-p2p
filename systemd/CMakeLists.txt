set(SYSTEMD_UNIT_DIR "/usr/lib/systemd/system"
    CACHE STRING "Directory for systemd unit files")

install(
    FILES
        dnf-p2p-proxy.service
    DESTINATION
        ${SYSTEMD_UNIT_DIR}
)
