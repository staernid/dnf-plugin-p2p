Development
===========

Project Structure
-----------------

* ``plugins/``: The DNF5 plugin written in Python.
* ``p2p-proxy-server/``: The proxy daemon, libp2p nodes, and local cache handlers.
* ``tests/``: Pytest suites testing proxy servers and libp2p nodes.
* ``systemd/``: Systemd service configuration files.
* ``doc/``: Sphinx documentation source files.
* ``dnf-p2p-helper``: Deployment, verification, and LAN testing CLI helper.
* ``patches/``: Patch files applied to bundled dependencies (e.g. py-libp2p) during RPM build.


Coding & Concurrency Guidelines
--------------------------------

* **Thread Safety**: The HTTP proxy server (``p2p_server.py``) is a multi-threaded, synchronous HTTP server utilizing Python's ``HTTPServer`` and ``ThreadingMixIn``. Access to the cache index or shared state must be protected using thread locks (e.g. ``threading.RLock()``).
* **Asynchronous boundaries**: The libp2p node (``p2p_libp2p.py``) runs on the ``Trio`` event loop in a background thread. Communication from HTTP handler threads to the libp2p node must use thread-safe channels (e.g. ``trio.from_thread.run`` or thread-safe callbacks).
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


Development and Deployment Helper
---------------------------------

The root ``dnf-p2p-helper`` script automates RPM packaging, local/remote service deployment, and LAN P2P integration testing:

**Local and Remote Deployment**:
Compiles the latest RPM packages, signs them, copies them to target systems, installs/reinstalls them, and restarts the ``dnf-p2p-proxy.service``:

.. code-block:: bash

    ./dnf-p2p-helper localhost t495s

**LAN Package Sharing Verification**:
Triggers a bidirectional P2P package sharing test between the local host and a remote node to verify LAN peer discovery, connection establishment, and package transmission:

.. code-block:: bash

    ./dnf-p2p-helper test t495s


Upstream Patches (py-libp2p)
----------------------------

We carry local patches against the bundled ``py-libp2p`` submodule in the ``patches/`` directory.
These fix upstream bugs that have not yet been merged.

Current patches:

* ``0001-fix-peerstore-crash-on-expired-peer-gc.patch``: Fixes a crash in
  ``PeerStore.maybe_delete_peer_record()`` where ``self.addrs()`` raises
  ``PeerStoreError`` for expired peers, killing the libp2p event loop and the
  entire proxy daemon.

**How patches are applied:**

* **RPM build** (``make rpm``): The spec file declares each patch as a ``Source``
  (e.g. ``Source10:``) and applies it with ``patch -p1`` to the bundled libp2p
  install tree during ``%install`` (after ``pip install``).
  The ``make srpm`` target automatically copies ``patches/*.patch`` into
  ``build/rpmbuild/SOURCES/``.

* **Local development** (``make patch-libp2p``): Runs ``git apply`` for each
  patch file against the ``py-libp2p-src/`` submodule. Already-applied patches
  are skipped.

**Updating the submodule:**

.. code-block:: bash

    # 1. Fetch and checkout latest upstream
    cd py-libp2p-src
    git fetch origin
    git checkout origin/main

    # 2. Re-apply patches
    cd ..
    make patch-libp2p

    # 3. If a patch fails (upstream fixed the bug), remove it from patches/
    #    and delete the SourceN line from dnf-plugin-p2p.spec

    # 4. Stage the updated submodule pointer
    git add py-libp2p-src

**Adding a new patch:**

1. Make your fix inside ``py-libp2p-src/``.
2. Generate a patch: ``cd py-libp2p-src && git diff > ../patches/NNNN-short-description.patch``
3. Add a ``SourceN:`` line to ``dnf-plugin-p2p.spec`` (use the next available number).
4. Add a corresponding ``patch -p1 --no-backup-if-mismatch < %{SOURCEN}`` line in the ``%install`` section.
5. Document the patch in this file.


Versioning and GitOps
---------------------

The single source of truth for the project version is the ``Version`` tag in ``dnf-plugin-p2p.spec``. All other version definitions must be synchronized:

1. **RPM Spec file**: ``dnf-plugin-p2p.spec`` -> ``Version: X.Y.Z``
2. **CMake Project**: ``CMakeLists.txt`` -> ``PROJECT (dnf-plugin-p2p VERSION X.Y.Z NONE)``
3. **DNF Plugin**: ``plugins/p2p_plugin.py`` -> ``get_version()`` returns ``libdnf5.plugin.Version(X, Y, Z)``
4. **Shared Package**: ``plugins/libdnf_p2p_sharing/__init__.py`` -> ``__version__ = "X.Y.Z"``
5. **Proxy Daemon**: ``p2p-proxy-server/__init__.py`` -> ``__version__ = "X.Y.Z"``
6. **Documentation**: ``doc/conf.py`` -> ``version = 'X.Y'`` and ``release = 'X.Y.Z'``


Common Pitfalls & Post-Mortem (Wrong Paths Went Down)
-----------------------------------------------------

During development, several incorrect assumptions led to development blockages:

1. **SWIG Abstract Class Issue (Subclassing IPlugin2_1)**:
   * **Wrong Path**: Inheriting the Python DNF 5 plugin from ``libdnf5.plugin.IPlugin2_1`` to match DNF 5 API 2.1 specifications.
   * **Result**: SWIG maps ``IPlugin2_1`` as an abstract C++ class without exposing a constructor to Python, leading to runtime failures: ``AttributeError: No constructor defined - class is abstract``.
   * **Fix**: Reverted the base class to ``libdnf5.plugin.IPlugin`` (API 2.0). SWIG director classes successfully bind and forward all callbacks (including ``pre_transaction``) through this base class.

2. **Inactive Hook (goal_resolved)**:
   * **Wrong Path**: Implementing ``goal_resolved(self, transaction)`` to register expected hashes.
   * **Result**: Because the DNF 5 Python Plugins Loader only binds hooks present on ``IPlugin`` (API 2.0) and does not know about ``IPlugin2_1`` methods like ``goal_resolved``, the python implementation was silently bypassed, resulting in no P2P sharing.
   * **Fix**: Replaced with the ``pre_transaction(self, transaction)`` hook which is fully supported in ``IPlugin``.

3. **Dry-Run Cache Optimization (tsflags=test)**:
   * **Wrong Path**: Testing expected hash registration with ``--setopt=tsflags=test`` repeatedly, assuming ``pre_transaction`` hook binding was broken because the hook was not being invoked.
   * **Result**: When DNF 5 detects that packages are already present in its download cache directory, it skips transaction downloading and does not fire the ``pre_transaction`` hook.
   * **Fix**: Clear DNF 5's cache directory (e.g. ``sudo dnf clean all`` and deleting package files) before running transaction tests to force DNF 5 to schedule downloads and trigger the hook.

4. **DNF 5 Download Timing & Expected Hash Mismatch**:
   * **Wrong Path**: Enforcing strictly that P2P queries/downloads are blocked unless the expected hash was registered by the plugin before the download request arrives at the proxy.
   * **Result**: In DNF 5, package downloads are executed during the transaction preparation phase, which is *before* the transaction execution phase (where the ``pre_transaction`` hook is called). As a result, clean transactions would always bypass P2P sharing because hashes were registered too late.
   * **Fix**: Relaxed the restriction on the proxy daemon. If the expected hash is not yet registered, the proxy still queries peers and verifies downloaded packages against the peer's self-reported hash to guarantee transit integrity. Operating system package security is fully guaranteed by DNF 5's GPG signature verification checks which run on the downloaded RPMs before they are installed. This allows P2P sharing to work out-of-the-box for all DNF commands.
