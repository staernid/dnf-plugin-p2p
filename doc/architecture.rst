Architecture
============

The ``libdnf-p2p-sharing`` system consists of two primary layers:

1. **libdnf5 Plugin**: Integrates with the DNF5 lifecycle, starting the proxy and injecting proxy configuration into repositories early (at the ``repos_configured`` hook).
2. **P2P Proxy Daemon**: Multi-threaded HTTP proxy utilizing ``py-libp2p`` and mDNS to cache and share packages on local networks.

Data Flow Diagram
-----------------

.. code-block:: text

    +-------------------+           +-------------------+
    |      DNF5 /       |           |   Remote Mirror   |
    |     libdnf5       |           | (Upstream Source) |
    +---------+---------+           +---------+---------+
              |                               ^
        (HTTP/HTTPS)                          | (Fallback / CONNECT)
              v                               |
    +---------+---------+                     |
    |    P2P Proxy      +---------------------+
    |  (Port 8888)      |
    +----+---------+----+
         |         ^
         |         | (mDNS Discovery / JSON Query)
         v         |
    +----+---------+----+           +-------------------+
    |    libp2p Node    |<--------->|   Remote P2P      |
    |  (Port 8000)      |           |     Peers         |
    +-------------------+           +-------------------+

HTTPS Tunneling
---------------

The local proxy server acts as a transparent tunnel for HTTPS requests using the HTTP ``CONNECT`` protocol. This preserves TLS security for GPG keys and secure metadata endpoints while allowing uninterrupted concurrent repository queries thanks to the multi-threaded server architecture.

P2P Networking (libp2p)
-----------------------

A background ``py-libp2p`` node runs in a Trio event loop and automatically discovers local network peers using mDNS. Package availability queries are exchanged using a custom JSON Request-Response protocol over the ``/dnf-p2p/query/1.0.0`` protocol ID.
