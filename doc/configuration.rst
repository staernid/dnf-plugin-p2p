Configuration
=============

Plugin Configuration
--------------------

The plugin configuration is loaded from:
``/etc/dnf/libdnf5-plugins/python_plugins_loader.d/p2p_plugin.conf``

.. code-block:: ini

    [main]
    name = p2p_plugin
    enabled = 1

    [p2p]
    # Enable P2P sharing
    enabled = true

    # Local proxy server port
    proxy_port = 8888

    # Local proxy server host
    proxy_host = 127.0.0.1

    # Enable caching for sharing with peers
    cache_enabled = true

    # Enable debug logging (prints plugin messages to stderr)
    debug = false

Configuration options:

* **[main] / enabled**: Enables or disables the DNF5 loading mechanism for
  the python plugin (``1`` for enabled, ``0`` for disabled).
* **[p2p] / enabled**: Enables P2P package sharing via the proxy.
* **[p2p] / proxy_port**: Port for the local proxy HTTP server
  (default: ``8888``).
* **[p2p] / proxy_host**: Bind address for the local proxy
  (default: ``127.0.0.1``).
* **[p2p] / cache_enabled**: Enables caching packages locally to serve to
  other peers.
* **[p2p] / debug**: Enables verbose ``>>>`` debug messages printed to
  stderr during DNF operations (default: ``false``).

.. note::

   The plugin requires no changes to any ``/etc/yum.repos.d/`` repo files.
   All URL rewrites happen in-memory during the ``repos_configured`` hook.


Service Management
------------------

The P2P proxy server is managed by systemd:

.. code-block:: bash

    # Enable and start the service
    sudo systemctl enable --now dnf-p2p-proxy.service

    # Check service status
    systemctl status dnf-p2p-proxy.service

    # View real-time service logs
    journalctl -u dnf-p2p-proxy.service -f

Service Overrides
~~~~~~~~~~~~~~~~~

The systemd service may require overrides for two settings:

1. **Bind address** — must be ``0.0.0.0`` so peers can download packages
   over the LAN (default in the unit is ``127.0.0.1``).
2. **libp2p port** — must be ``8000`` to match the port advertised by
   mDNS discovery.

Create a drop-in override:

.. code-block:: bash

    sudo systemctl edit dnf-p2p-proxy.service

With the following content:

.. code-block:: ini

    [Service]
    ExecStart=
    ExecStart=/usr/bin/python3 /usr/libexec/dnf-plugin-p2p/p2p_server.py \
        --host=0.0.0.0 --port=8888 --libp2p-port=8000 \
        --cache-dir=/var/cache/dnf-plugin-p2p

Then reload and restart:

.. code-block:: bash

    sudo systemctl daemon-reload
    sudo systemctl restart dnf-p2p-proxy.service
