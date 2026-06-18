Installation
============

Requirements
------------

* Fedora 41 or later / Red Hat Enterprise Linux 10 or later
* DNF 5 / libdnf5
* Python 3.9 or later
* ``py-libp2p`` and its dependencies (Trio, etc.)

Building from Source
--------------------

To build and install the plugin from source, run:

.. code-block:: bash

    mkdir build && cd build
    cmake ..
    make
    sudo make install

This will install:

1. The libdnf5 python plugin to the python plugin directory.
2. The proxy server executable to ``/usr/libexec/libdnf-p2p-sharing/p2p_server.py``.
3. The systemd service ``dnf-p2p-proxy.service``.
4. Configuration templates to ``/etc/dnf/libdnf5-plugins/``.
