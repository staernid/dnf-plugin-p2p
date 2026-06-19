# dnf-plugin-p2p

A libdnf5 plugin for peer-to-peer package sharing over local networks.

## Overview

`dnf-plugin-p2p` enables DNF 5 / libdnf5 to discover and download RPM packages from peers on the local network using a standardized libp2p mDNS discovery network, reducing bandwidth consumption and improving package download performance in environments with multiple systems.

## Architecture

The plugin consists of two main components:

### 1. libdnf5 Plugin (`plugins/p2p_plugin.py`)

- Hooks into the libdnf5 plugin system.
- Intercepts repository configurations at the `repos_configured` stage (before metadata downloads start).
- Automatically routes all repository downloads and metadata requests through the local P2P proxy.

### 2. P2P Proxy Server (`p2p-proxy-server/`)

- A multi-threaded local HTTP proxy daemon (`p2p_server.py`) running on each system.
- Handles incoming package requests and transparently tunnels HTTPS connections using the HTTP `CONNECT` method.
- Coordinates checks against the local cache, queries local peers over the libp2p network, and falls back to upstream mirrors when necessary.
- Features automatic URL resolution to proxy absolute URLs without explicit query parameters.

## How It Works

1. **Plugin Initialization**: The libdnf5 plugin checks and starts the local P2P proxy server daemon on startup. It performs a lightweight `/ping` health check to verify the proxy is active and authentic before routing traffic, automatically bypassing the proxy for safety if the service is unavailable or if another service conflicts with the port.
2. **Peer Discovery**: Uses `py-libp2p` with mDNS for automatic zero-configuration local peer discovery.
3. **Download Interception**: Modifies repository configurations early to route traffic through the local proxy.
4. **Proxy Operation**:
   - **HTTPS Connections**: Transparently tunneled to the original mirror via the `CONNECT` protocol.
   - **HTTP Package Requests (.rpm, .drpm)**:
     - Checks if the file is available in the local cache.
     - Queries discovered peers via the libp2p Request-Response protocol (`/dnf-p2p/query/1.0.0`).
     - Downloads and streams the package from the fastest available peer.
     - Falls back to upstream remote repository mirrors if unavailable on the P2P network.
     - Caches the downloaded package locally to share with other peers.
   - **HTTP Metadata and Non-Package Requests**:
     - Streamed directly from the upstream remote repository mirror without local caching or peer querying, ensuring repository metadata remains fresh and preventing transaction signature mismatches.


## Installation

### From Copr (Fedora)

Pre-built RPM packages are available in the official Copr repository:

```bash
# Enable the Copr repository
sudo dnf copr enable staernid/libdnf-p2p-sharing

# Install the packages
sudo dnf install -y dnf-plugin-p2p dnf-plugin-p2p-proxy python3-dnf-plugin-p2p-common
```

### From Source

To compile and install the plugin from source:

```bash
mkdir build && cd build
cmake ..
make
sudo make install
```

## Service Management

The P2P proxy server runs as a systemd service. After installation, enable and start the daemon:

```bash
# Enable and start the service
sudo systemctl enable --now dnf-p2p-proxy.service

# Check service status
systemctl status dnf-p2p-proxy.service

# View real-time service logs
journalctl -u dnf-p2p-proxy.service -f
```


## Configuration

Edit `/etc/dnf/libdnf5-plugins/python_plugins_loader.d/p2p_plugin.conf`:

```ini
[main]
name = p2p_plugin
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

*Note: The local proxy service manages peer discovery over libp2p. Under the hood, the proxy's `py-libp2p` node performs mDNS discovery automatically to locate nearby nodes and execute secure JSON package queries. HTTPS connections are tunneled securely (without MITM decryption) to maintain TLS integrity, meaning only HTTP repository traffic is cached and shared via P2P.*

## Building Documentation

```bash
make doc-html
make doc-man
```

## License

GNU General Public License v2.0 or later - See LICENSE file

## Contributing

Contributions are welcome. Please submit pull requests or issues on GitHub.
