dnf-plugin-p2p Documentation
=============================

Overview
--------

``dnf-plugin-p2p`` enables DNF 5 / libdnf5 to discover and download RPM
packages from peers on the local network using libp2p mDNS discovery,
reducing bandwidth consumption and improving download performance in
multi-system environments.

No configuration of DNF repositories is required — the plugin
transparently rewrites URLs in-memory and routes traffic through a local
proxy that handles peer discovery, caching, and upstream fallback.


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

    sudo dnf copr enable staernid/libdnf-p2p-sharing
    sudo dnf install -y dnf-plugin-p2p dnf-plugin-p2p-proxy python3-dnf-plugin-p2p-common

2. Enable the proxy service::

    sudo systemctl enable --now dnf-p2p-proxy.service

3. Use DNF normally::

    sudo dnf install tmux
    # The plugin automatically checks local peers before remote mirrors


Features
--------

- **Zero Configuration**: Works out of the box — no repo file changes needed.
- **Automatic Peer Discovery**: Finds other systems on the LAN via mDNS.
- **Transparent Integration**: All standard DNF commands work unchanged.
- **Local Caching**: Downloaded packages are cached and shared with peers.
- **Upstream Fallback**: Falls back to remote mirrors if no peer has a package.
- **Security Preserved**: Upstream internet traffic is always HTTPS.


License
-------

GNU General Public License v2.0 or later
