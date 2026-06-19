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

    # Maximum package cache size in MB (0 or less to disable size limits)
    max_cache_size_mb = 1024

    # Maximum disk usage percentage for the cache file system (0 or less to disable disk space checks)
    max_disk_usage_percent = 90.0

    # Enable debug logging (prints plugin messages to stderr)
    debug = false

    # Force upgrading of upstream HTTP mirror URLs to HTTPS (default: true)
    force_https = true

    # libp2p listener port (default: 8000)
    libp2p_port = 8000

    # Package cache directory (default: /var/cache/dnf-plugin-p2p when root)
    cache_dir = /var/cache/dnf-plugin-p2p

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
* **[p2p] / max_cache_size_mb**: Maximum size of the package cache in MB.
  If the cache exceeds this size, the oldest packages are evicted using an LRU
  policy (default: ``1024``).
* **[p2p] / max_disk_usage_percent**: Maximum disk usage percentage for the
  cache filesystem. If usage goes above this threshold, the oldest packages
  are evicted using an LRU policy (default: ``90.0``).
* **[p2p] / debug**: Enables verbose ``>>>`` debug messages printed to
  stderr during DNF operations (default: ``false``).
* **[p2p] / force_https**: Force upgrading upstream HTTP mirror URLs to HTTPS
  to secure internet traffic. Set to ``false`` to allow using internal mirrors
  over plain HTTP (default: ``true``).
* **[p2p] / libp2p_port**: Port for the libp2p listener and mDNS discovery
  (default: ``8000``).
* **[p2p] / cache_dir**: Package cache directory path (default:
  ``/var/cache/dnf-plugin-p2p`` when run as root, otherwise
  ``~/.cache/dnf-plugin-p2p``).

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

Service Customization
~~~~~~~~~~~~~~~~~~~~~

The background daemon is fully configurable via the main configuration file
``/etc/dnf/libdnf5-plugins/python_plugins_loader.d/p2p_plugin.conf``.
Changes to settings such as ``proxy_host`` (e.g. set to ``0.0.0.0`` to share with the LAN),
``proxy_port``, ``libp2p_port``, or the cache limits will be read directly by the
systemd service on startup.

If you need to change command-line parameters that are not exposed in the
configuration file, you can create a systemd drop-in override:

.. code-block:: bash

    sudo systemctl edit dnf-p2p-proxy.service

With the following content to add custom arguments:

.. code-block:: ini

    [Service]
    ExecStart=
    ExecStart=/usr/bin/python3 /usr/libexec/dnf-plugin-p2p/p2p_server.py \
        --config=/etc/dnf/libdnf5-plugins/python_plugins_loader.d/p2p_plugin.conf \
        --debug

Then reload and restart:

.. code-block:: bash

    sudo systemctl daemon-reload
    sudo systemctl restart dnf-p2p-proxy.service
