Development
===========

Project Structure
-----------------

* ``plugins/``: The DNF5 plugin written in Python.
* ``p2p-proxy-server/``: The proxy daemon, libp2p nodes, and local cache handlers.
* ``tests/``: Pytest suites testing proxy servers and libp2p nodes.
* ``systemd/``: Systemd service configuration files.
* ``doc/``: Sphinx documentation source files.

Running Tests
-------------

Unit tests are written with pytest. To run the tests, make sure you have the dependencies installed:

.. code-block:: bash

    pip install pytest requests trio py-libp2p
    pytest tests/

Building RPM Packages
---------------------

The project includes an RPM spec file (``libdnf-p2p-sharing.spec``) to build packages for Fedora/RHEL.

To build the RPM:

1. Create a source tarball:

   .. code-block:: bash

       tar --exclude-vcs --exclude='./build' --exclude='./.venv' \
           --transform 's/^\./libdnf-p2p-sharing-0.1.0/' \
           -czf build/rpmbuild/SOURCES/libdnf-p2p-sharing-0.1.0.tar.gz .

2. Build the package:

   .. code-block:: bash

       cp libdnf-p2p-sharing.spec build/rpmbuild/SPECS/
       rpmbuild --define "_topdir $(pwd)/build/rpmbuild" -bb build/rpmbuild/SPECS/libdnf-p2p-sharing.spec
