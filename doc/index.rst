libdnf-p2p-sharing Documentation
=================================

Overview
--------

The ``libdnf-p2p-sharing`` plugin enables DNF 5 and libdnf5 to discover and download
RPM packages from peers on the local network, reducing bandwidth consumption and
improving package download performance in multi-system environments.

Contents
--------

.. toctree::
   :maxdepth: 2

   installation
   configuration
   usage
   architecture
   development

Quick Start
-----------

1. Install the plugin::

    cmake .
    make
    sudo make install

2. Enable it in configuration::

    sudo nano /etc/dnf/libdnf-plugins/p2p-plugin.conf
    # Set: enabled = true

3. Run DNF normally::

    dnf install package-name
    # The plugin will automatically try P2P peers before remote mirrors

Features
--------

- **Multicast Peer Discovery**: Automatically finds other systems on the local network with cached packages
- **Transparent Integration**: Works seamlessly with existing DNF commands
- **Local Caching**: Keeps downloaded packages available for sharing with peers
- **Fallback Support**: Falls back to remote mirrors if packages aren't available locally
- **Configurable**: Easily customize proxy port, multicast settings, and caching options

License
-------

GNU General Public License v2.0 or later
