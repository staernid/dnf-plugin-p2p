Installation
============

Requirements
------------

* Fedora 41 or later / Red Hat Enterprise Linux 10 or later
* DNF 5 / libdnf5
* Python 3.9 or later
* ``py-libp2p`` and its dependencies (Trio, etc.)

From Copr (Fedora)
------------------

Pre-built RPM packages are available in the official Copr repository:

.. code-block:: bash

    # Enable the Copr repository
    sudo dnf copr enable staernid/libdnf-p2p-sharing

    # Install the packages
    sudo dnf install -y dnf-plugin-p2p dnf-plugin-p2p-proxy python3-dnf-plugin-p2p-common

Building from Source
--------------------

To build and install the plugin from source:

.. code-block:: bash

    mkdir build && cd build
    cmake ..
    make
    sudo make install

This will install:

1. The libdnf5 python plugin to the python plugin directory.
2. The proxy server scripts to ``/usr/libexec/dnf-plugin-p2p/``.
3. The systemd service ``dnf-p2p-proxy.service``.
4. Configuration templates to ``/etc/dnf/libdnf5-plugins/``.

Post-Install Setup
------------------

After installation, enable and start the P2P proxy daemon:

.. code-block:: bash

    sudo systemctl enable --now dnf-p2p-proxy.service

The plugin will start working immediately — no DNF repo configuration
changes are needed. All repository traffic is transparently routed
through the local proxy.
