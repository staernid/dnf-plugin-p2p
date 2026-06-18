CMAKE_MINIMUM_REQUIRED (VERSION 3.5.0...4.0.2)
PROJECT (libdnf-p2p-sharing NONE)

cmake_policy(SET CMP0148 OLD)
FIND_PACKAGE (PythonInterp 3 EXACT REQUIRED)

EXECUTE_PROCESS(COMMAND ${PYTHON_EXECUTABLE} -c "from sys import stdout; from sysconfig import get_path; stdout.write(get_path('purelib'))" OUTPUT_VARIABLE PYTHON_INSTALL_DIR)
MESSAGE(STATUS "Python install dir is ${PYTHON_INSTALL_DIR}")

SET (SYSCONFDIR /etc)

ADD_SUBDIRECTORY (doc)
ADD_SUBDIRECTORY (etc)
ADD_SUBDIRECTORY (libdnf5-plugins)
ADD_SUBDIRECTORY (p2p-proxy-server)
ADD_SUBDIRECTORY (po)
