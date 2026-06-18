# libdnf-p2p-sharing

A libdnf5 plugin for peer-to-peer package sharing over local networks.

## Overview

`libdnf-p2p-sharing` enables DNF 5 / libdnf5 to discover and download RPM packages from peers on the local network using multicast queries, reducing bandwidth consumption and improving package download performance in environments with multiple systems.

## Architecture

The plugin consists of two main components:

### 1. libdnf5 Plugin (`libdnf5-plugins/p2p_plugin.py`)

- Hooks into the libdnf5 plugin system
- Discovers P2P peers via multicast on the local network
- Manages the local HTTP proxy server
- Intercepts package downloads and routes them through the local P2P proxy

### 2. P2P Proxy Server (`p2p-proxy-server/`)

- Local HTTP/FTP proxy daemon running on each system
- Handles incoming requests for packages
- Queries local cache for available files
- Falls back to remote mirrors if packages are not available locally
- Serves packages to other peers on the network

## How It Works

1. **Plugin Initialization**: The libdnf5 plugin starts the local P2P proxy server on startup
2. **Peer Discovery**: Uses multicast (224.0.0.1:5353) to query for peers with cached packages
3. **Download Interception**: Modifies repository base URLs to route through the local proxy
4. **Proxy Operation**: For each package request:
   - Checks if available locally (in cache)
   - Queries discovered peers for the package
   - Downloads from fastest available peer
   - Falls back to remote repository if needed
   - Caches the package locally for future peer requests

## Installation

```bash
mkdir build && cd build
cmake ..
make
sudo make install
```

## Configuration

Edit `/etc/dnf/libdnf-plugins/p2p-plugin.conf`:

```ini
[main]
enabled = 1

[p2p]
# Enable P2P sharing
enabled = true

# Local proxy server port
proxy_port = 8888

# Multicast group for peer discovery
multicast_group = 224.0.0.1
multicast_port = 5353

# Enable caching for sharing with peers
cache_enabled = true

# Timeout for peer discovery queries (seconds)
peer_discovery_timeout = 2

# Maximum number of peers to query in parallel
max_parallel_peers = 5
```

## Usage

Once installed and configured, the plugin operates transparently. No special commands are required:

```bash
dnf install package-name
# Plugin will automatically try P2P peers before remote mirrors
```

## Building Documentation

```bash
make doc-html
make doc-man
```

## License

GNU General Public License v2.0 or later - See LICENSE file

## Contributing

Contributions are welcome. Please submit pull requests or issues on GitHub.
