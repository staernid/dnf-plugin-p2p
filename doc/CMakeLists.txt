# Documentation build configuration

find_program(SPHINX_BUILD NAMES sphinx-build sphinx-build-3 REQUIRED)

ADD_CUSTOM_TARGET (doc-html
    PYTHONPATH=${CMAKE_SOURCE_DIR} ${SPHINX_BUILD} -b html
    ${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_CURRENT_BINARY_DIR}
    COMMENT "Building HTML documentation")

ADD_CUSTOM_TARGET (doc-man
    PYTHONPATH=${CMAKE_SOURCE_DIR} ${SPHINX_BUILD} -b man
    ${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_CURRENT_BINARY_DIR}
    COMMENT "Building man pages")

ADD_CUSTOM_TARGET (doc)
ADD_DEPENDENCIES (doc doc-html doc-man)

INSTALL(FILES ${CMAKE_CURRENT_BINARY_DIR}/libdnf-p2p-sharing.8
    DESTINATION share/man/man8 OPTIONAL)

