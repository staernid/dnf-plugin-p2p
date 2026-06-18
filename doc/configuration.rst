Configuration
=============

Plugin Configuration
--------------------

The plugin configuration is loaded from:
``/etc/dnf/libdnf5-plugins/python_plugins_loader.d/p2p_plugin.conf``

Configuration options:

* **[main] / enabled**: Enables or disables the DNF5 loading mechanism for the python plugin (1 for enabled, 0 for disabled).
* **[p2p] / enabled**: Enables P2P package sharing via the proxy.
* **[p2p] / proxy_port**: Port for the local proxy HTTP server (default: ``8888``).
* **[p2p] / proxy_host**: Bind address for the local proxy (default: ``127.0.0.1``).
* **[p2p] / cache_enabled**: Enables caching packages locally to serve to other peers.

Proxy Service
-------------

The local P2P proxy server is managed by systemd. To enable and start it:

.. code-block:: bash

    sudo systemctl enable --now dnf-p2p-proxy.service

To view status or logs:

.. code-block:: bash

    sudo systemctl status dnf-p2p-proxy.service
    journalctl -u dnf-p2p-proxy.service -f
