INSTALL (FILES p2p_plugin.py DESTINATION ${PYTHON_INSTALL_DIR}/libdnf-plugins)
INSTALL (FILES __init__.py DESTINATION ${PYTHON_INSTALL_DIR}/libdnf_p2p_sharing)

ADD_SUBDIRECTORY (libdnf_p2p_sharing)
