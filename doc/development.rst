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

The project includes an RPM spec file (``dnf-plugin-p2p.spec``) and a root ``Makefile`` to simplify package builds.

To build packages:

1. **Create the source tarball**:
   Reads the current version from the spec file and packages files under ``build/rpmbuild/SOURCES/``:

   .. code-block:: bash

       make tarball

2. **Build the Source RPM (SRPM)**:
   Downloads external PyPI sources and generates the SRPM:

   .. code-block:: bash

       make srpm

3. **Build the binary RPMs**:
   Compiles and packages the RPMs locally:

   .. code-block:: bash

       make rpm


Versioning, Tagging, and GitOps
-------------------------------

To ensure predictable releases and stable package builds, this project adheres to a structured Versioning, Tagging, and GitOps process.

Versioning Strategy
~~~~~~~~~~~~~~~~~~~

We use `Semantic Versioning (SemVer) <https://semver.org/>`_. The single source of truth for the project version is the ``Version`` tag in ``dnf-plugin-p2p.spec``. All other version definitions must be synchronized:

1. **RPM Spec file**: ``dnf-plugin-p2p.spec`` -> ``Version: X.Y.Z``
2. **CMake Project**: ``CMakeLists.txt`` -> ``PROJECT (dnf-plugin-p2p VERSION X.Y.Z NONE)``
3. **DNF Plugin**: ``plugins/p2p_plugin.py`` -> ``get_version()`` returns ``libdnf5.plugin.Version(X, Y, Z)``
4. **Shared Package**: ``plugins/libdnf_p2p_sharing/__init__.py`` -> ``__version__ = "X.Y.Z"``
5. **Proxy Daemon**: ``p2p-proxy-server/__init__.py`` -> ``__version__ = "X.Y.Z"``
6. **Documentation**: ``doc/conf.py`` -> ``version = 'X.Y'`` and ``release = 'X.Y.Z'``

Git Tagging & Release Workflow
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every release must be tagged in Git to trigger release builds.

1. **Bump Version**: Run the automated helper command via the Makefile to sync versions across all files and update the spec changelog:

   .. code-block:: bash

       make bump-version V=0.3.0

2. **Commit and Tag**: Follow the instructions printed by the script to commit changes and push the signed tag:

   .. code-block:: bash

       git add .
       git commit -m "Bump version to 0.3.0"
       git tag -s v0.3.0 -m "Release v0.3.0"
       git push origin master v0.3.0

3. **Release Asset Generation**: A GitHub Action workflow detects the tag, builds the release source tarball, and uploads it to a newly created GitHub Release.

Continuous Integration & Delivery (GitOps)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **GitHub Actions CI**: Runs on every pull request and push to ``master``:
  * Runs python unit tests via ``pytest tests/``.
  * Validates the RPM spec file format using ``rpmlint``.
  * Builds a dry-run source RPM (SRPM) using ``.copr/Makefile`` to guarantee build pipeline integrity.
* **Fedora COPR CD**:
  * **Stable Repository** (``staernid/dnf-plugin-p2p``): Configured via Copr's SCM integration to build only when a new release tag (``v*``) is pushed. Copr retrieves the release tarball directly from GitHub and triggers the build.
  * **Development Repository** (``staernid/dnf-plugin-p2p-testing``): Automatically builds on every commit to ``master`` to provide the latest development packages.
