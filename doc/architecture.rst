Architecture
============

The ``dnf-plugin-p2p`` system consists of three primary components:

1. **libdnf5 Plugin** (``plugins/p2p_plugin.py``): Integrates with the DNF5
   lifecycle, starting the proxy and injecting proxy configuration into
   repositories at the ``repos_configured`` hook.
2. **P2P Proxy Daemon** (``p2p-proxy-server/``): Multi-threaded HTTP proxy
   utilizing ``py-libp2p`` and mDNS to cache and share packages on local
   networks.
3. **Diagnostics CLI Client** (``dnf-p2p-client``): A command-line utility
   for administrators to check the status, caching efficiency, and network
   activity of the proxy daemon.


Data Flow
---------

.. code-block:: text

    +-------------------+           +-------------------+
    |      DNF5 /       |           |   Remote Mirror   |
    |     libdnf5       |           |  (HTTPS upstream) |
    +---------+---------+           +---------+---------+
              |                               ^
        (HTTP via proxy)                      | (HTTPS, upgraded by proxy)
              v                               |
    +---------+---------+                     |
    |    P2P Proxy      +---------------------+
    |  (Port 8888)      |
    +----+---------+----+
         |         ^
         |         | (mDNS Discovery / JSON Query)
         v         |
    +----+---------+----+           +-------------------+
    |    libp2p Node    |<--------->|   LAN P2P Peers   |
    |  (Port 8000)      |           |                   |
    +-------------------+           +-------------------+


Plugin Lifecycle Hooks
----------------------

The plugin uses several libdnf5 hooks to set up the P2P pipeline:

``init``
    Loads configuration from ``p2p_plugin.conf``, starts the
    ``dnf-p2p-proxy.service`` if not already running.

``pre_base_setup``
    Disables zchunk (``config.zchunk = False``). See `Zchunk
    Incompatibility`_ below.

``repos_configured``
    For every enabled remote repository:

    - Sets ``config.proxy`` to ``http://127.0.0.1:8888``.
    - Rewrites ``metalink``, ``mirrorlist``, and ``baseurl`` URLs from
      ``https://`` to ``http://`` **in-memory only** (no repo files are
      modified on disk). This forces DNF to send plaintext ``GET`` requests
      through the proxy instead of opaque ``CONNECT`` tunnels.

``goal_resolved``
    Once the transaction goals are resolved, the plugin queries the package database
    for the expected SHA-256 checksums of all packages scheduled to be downloaded.
    These expected hashes are then registered with the proxy server via a local
    ``POST /expected_hashes`` API call to establish a cryptographically secure
    trust expectation.


HTTPS Handling
--------------

A core design challenge is that Fedora repositories default to HTTPS
everywhere (metalink URLs, mirror URLs). When DNF uses HTTPS, it sends
``CONNECT`` tunnel requests to the proxy, which are end-to-end encrypted.
The proxy cannot inspect the traffic to identify ``.rpm`` downloads or
serve them from cache/peers.

The solution is a two-part URL rewrite:

1. **Plugin side** — rewrites all repository URLs from ``https://`` to
   ``http://`` in-memory at the ``repos_configured`` hook. DNF then sends
   plaintext ``GET`` requests to the proxy.

2. **Proxy side** — before fetching anything from the internet, upgrades
   the URL back to ``https://`` for all non-localhost hosts. Upstream
   traffic remains encrypted; only the localhost hop is HTTP.

For metalink responses specifically, the proxy uses XML-aware regex to
rewrite ``<url>`` element text from ``https://`` to ``http://`` so that
subsequent mirror downloads also come through as ``GET`` requests.
Checksums and other XML content are left untouched.


Zchunk Incompatibility
----------------------

Zchunk (``.xml.zck``) is a delta-compression format used by Fedora for
repository metadata. It relies on HTTP Range requests to download only
changed chunks. The simple HTTP proxy cannot correctly relay these
multi-range requests, causing checksum validation failures.

The plugin disables zchunk in ``pre_base_setup``, forcing DNF to download
full ``.xml.gz`` metadata files instead. These are slightly larger but
work reliably through the proxy. This trade-off is acceptable because:

- Metadata downloads are small compared to package downloads.
- The P2P savings on large ``.rpm`` packages far outweigh the metadata
  overhead.


P2P Networking (libp2p)
-----------------------

A background ``py-libp2p`` node runs in a Trio event loop and
automatically discovers local network peers using mDNS. Package
availability queries are exchanged using a custom JSON Request-Response
protocol over the ``/dnf-p2p/query/1.0.0`` protocol ID.

.. important::

   The libp2p TCP listener **must** be on port ``8000`` because
   ``py-libp2p``'s ``MDNSDiscovery`` hardcodes the advertised port to
   ``8000``. If the listener runs on a different port, peers will discover
   the node but fail to connect. The systemd service override sets
   ``--libp2p-port=8000`` to ensure this.

The proxy's HTTP server **must** bind to ``0.0.0.0`` (not just
``127.0.0.1``) so that peers can download packages from it over the LAN.
The systemd service override sets ``--host=0.0.0.0`` for this purpose.


Package Download Flow
---------------------

When DNF requests an ``.rpm`` or ``.drpm`` file through the proxy:

1. **Local cache check** — if the file exists in
   ``/var/cache/dnf-plugin-p2p/``, serve it immediately.
2. **Peer query** — ask all discovered libp2p peers if they have the
   file. If a peer responds positively, download from
   ``http://<peer-ip>:8888/packages/<filename>``.
3. **Upstream fallback** — if no peer has it, download from the original
   mirror URL (upgraded to HTTPS), stream to the client, and cache
   locally for future peer requests.

Non-package files (metadata, repodata) are streamed directly from the
upstream mirror without caching or peer querying.


Security & Package Integrity
----------------------------

To prevent cache poisoning, Server-Side Request Forgery (SSRF), and unauthorized LAN access, the proxy server implements the following security controls:

- **Localhost Control Locking**: HTTP operations modifying proxy state (such as registering expected hashes via ``POST /expected_hashes``) are strictly locked to the loopback interface (``127.0.0.1`` / ``::1``). Remote requests to these paths are rejected with HTTP 403 Forbidden.
- **SSRF Mitigation**: Remote clients requesting package downloads via the proxy are not permitted to pass a ``remote_url`` parameter, ensuring the proxy cannot be used as an open internet gateway or for internal port scanning.
- **Cryptographic Verification**: During peer or mirror downloads, the proxy computes the SHA-256 hash of the received stream on-the-fly. If the hash does not match the expected hash registered by the local DNF transaction, the download is immediately aborted, and the temporary file is unlinked.
- **Self-Healing Cache Validation**: Before serving a package from the local cache, the proxy validates the file's hash against the registered expected hash. If corruption or tampering is detected, the file is automatically evicted from the disk and the cache index, forcing a clean fallback download.
- **Privilege Demotion**: The background proxy daemon runs as an unprivileged system user (``dnf-p2p``) to adhere to the principle of least privilege.


Diagnostics & Observability
---------------------------

The proxy daemon exposes local-only GET endpoints at ``/stats`` and ``/status``:

- Access is strictly restricted to loopback clients (``127.0.0.1`` / ``::1``) to prevent exposing metrics to the network.
- Returns JSON metadata including cache hit/miss counts, cache hit ratio, total cache size on disk, active/discovered libp2p peers, and cumulative bandwidth saved.
- Administrators can query these statistics in a user-friendly format using the ``dnf-p2p-client`` command-line tool.


IPv6 Support
------------

Zero-configuration LAN discovery and transfers fully support dual-stack and IPv6-only environments:

- The libp2p node listens on both IPv4 and IPv6 network interfaces, including the IPv6 wildcard address ``/ip6/::/tcp/<port>``.
- During peer discovery, the mDNS protocol broadcasts and resolves both IPv4 and IPv6 peer addresses.
- The address extraction mechanism automatically identifies reachable IPv6 addresses, wrapping them in square brackets (e.g., ``http://[2001:db8::1]:8888/``) to generate valid HTTP URLs for package transfers.
