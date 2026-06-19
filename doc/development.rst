Development
===========

Project Structure
-----------------

* ``plugins/``: The DNF5 plugin written in Python.
* ``p2p-proxy-server/``: The proxy daemon, libp2p nodes, and local cache handlers.
* ``tests/``: Pytest suites testing proxy servers and libp2p nodes.
* ``systemd/``: Systemd service configuration files.
* ``doc/``: Sphinx documentation source files.


Coding & Concurrency Guidelines
--------------------------------

* **Thread Safety**: The HTTP proxy server (``p2p-proxy-server/p2p_server.py``) is a multi-threaded, synchronous HTTP server utilizing Python's ``HTTPServer`` and ``ThreadingMixIn``. Access to the cache index or any shared state must be protected using thread locks (e.g. ``self.lock = threading.RLock()`` in ``P2PCache``).
* **Asynchronous boundaries**: The libp2p node (``p2p-proxy-server/p2p_libp2p.py``) runs on the ``Trio`` event loop in a background thread. Communication from HTTP handler threads to the libp2p node must use thread-safe channels (e.g. ``trio.from_thread.run`` or thread-safe callbacks).
* **Non-Root Privilege Checks**: The DNF plugin must avoid initiating systemd services (e.g., calling ``systemctl start dnf-p2p-proxy.service``) when run by a non-root user to avoid console Polkit authorization prompts on query commands like ``dnf search``.


Testing Guidelines
------------------

Unit tests are written with ``pytest``.

Running Tests
~~~~~~~~~~~~~

Do not run ``pytest`` globally without path limits, as the repository contains ``py-libp2p-src`` as a sub-source directory, which will result in module collection failures.

Always target the ``tests/`` directory specifically:

.. code-block:: bash

    pytest tests/

Mocking Rules
~~~~~~~~~~~~~

* **HTTP Response Validation**: The HTTP handler transmits the status code and headers before opening the cached package file. A bad mock on file opening will cause an exception after the client receives ``200 OK``, which may pass silently in the test client.
* **Rule**: When mocking file operations or cache hits in tests:
  1. Ensure ``builtins.open`` is mocked correctly (e.g. using ``mock_open(read_data=...)``).
  2. Patch file movement and existence checks (e.g., ``Path.rename``, ``Path.exists``) so tests do not throw disk exceptions.
  3. Assert both the HTTP response status code AND the correctness of the response body.


Performance Guidelines
----------------------

* **Avoid Redundant Hash Calculations**: Calculating SHA-256 hashes of large RPM packages is CPU and disk-bound. The HTTP proxy server must delegate caching to ``P2PCache.add_to_cache`` without calculating the hash beforehand.
* **Concurrent Peer Queries**: Do not query peers sequentially in a loop. When querying multiple local peers, query them concurrently using Trio nurseries with a global timeout to prevent DNF from hanging on stale or offline peers.


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
