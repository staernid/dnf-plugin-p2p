Usage
=====

Transparent Operation
---------------------

Once installed and configured, the P2P sharing plugin operates transparently during standard DNF5 package management commands. No user interaction or special parameters are required:

.. code-block:: bash

    sudo dnf5 install tmux
    sudo dnf5 upgrade

The plugin will automatically route all enabled repositories through the local proxy.

Verifying P2P Operations
------------------------

To verify that the proxy is intercepting requests, check the systemd logs:

.. code-block:: bash

    journalctl -u dnf-p2p-proxy.service -f

You will see:

* ``CONNECT`` logs for secure HTTPS metadata and repository updates (which are tunneled transparently).
* ``GET`` logs for RPM packages. If a peer has the package, it will be downloaded directly from them. If not, the proxy falls back to downloading from the upstream mirror and caches it.
