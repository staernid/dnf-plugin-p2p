# dnf-plugin-p2p

A libdnf5 plugin for peer-to-peer package sharing over local networks.

## Overview

`dnf-plugin-p2p` enables DNF 5 / libdnf5 to discover and download RPM packages from peers on the local network using a standardized libp2p mDNS discovery network (supporting both IPv4 and IPv6), reducing bandwidth consumption and improving package download performance in environments with multiple systems.

## Installation

### From Copr (Fedora)

Pre-built RPM packages are available in the official Copr repository:

```bash
# Enable the Copr repository
sudo dnf copr enable -y staernid/libdnf-p2p-sharing

# Install
sudo dnf install -y dnf-plugin-p2p
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

## Monitoring & Statistics

A command-line diagnostic tool is provided to monitor the daemon's state, cache efficiency, peer connections, and bandwidth savings:

```bash
# Check proxy status and metrics
dnf-p2p-client status
```

Example Output:

```text
==================================================
           DNF P2P Daemon State & Stats
==================================================
Proxy Address:         http://127.0.0.1:8888
Cache Hits:            15
Cache Misses:          8
Cache Hit Ratio:       65.22% (Total requests: 23)
Cache Size on Disk:    124.50 MB
Discovered Peers:      3
Active P2P Connections: 2
Bandwidth Saved:       87.20 MB
==================================================
```

You can customize the host, port, or configuration file path if the daemon is running on non-default settings:

```bash
dnf-p2p-client --port 8888 status
dnf-p2p-client --config /path/to/p2p_plugin.conf status
```

## Configuration

Edit `/etc/dnf/libdnf5-plugins/python_plugins_loader.d/p2p_plugin.conf`
to change the default values for options like peer_discovery_timeout, max_cache_size_mb, max_disk_usage_percent, etc.

*Note: The local proxy service manages peer discovery over libp2p. Under the hood, the proxy's `py-libp2p` node performs mDNS discovery automatically (over IPv4 and IPv6) to locate nearby nodes and execute secure JSON package queries. HTTPS connections are tunneled securely (without MITM decryption) to maintain TLS integrity, meaning only HTTP repository traffic is cached and shared via P2P.*

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

### 3. CLI Diagnostic Client (`dnf-p2p-client`)

- An executable command-line diagnostic utility (`dnf-p2p-client`) to query the running daemon.
- Retrieves and displays cache efficiency, peer connections, and bandwidth statistics.

## Building Documentation

```bash
make doc-html
make doc-man
```

## License

GNU General Public License v2.0 or later - See LICENSE file

## Contributing

Contributions are welcome. Please submit pull requests or issues on GitHub.
