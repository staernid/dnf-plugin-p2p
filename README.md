<img src="./assets/preview-banner.jpg" alt="dnf-plugin-p2p banner" width="100%" />

---

## Overview

`dnf-plugin-p2p` enables systems running **DNF 5 / libdnf5** on a local network (LAN) to discover, cache, and share downloaded RPM packages peer-to-peer (P2P). This accelerates package installations and significantly reduces external internet bandwidth consumption without requiring repository configuration changes or infrastructure mirrors.

---

## Architecture & Seams

```
DNF 5 CLI / libdnf5
       │
       ▼ (in-memory URL rewrite: https:// -> http://127.0.0.1:8888)
[libdnf5 Plugin] ──(HTTP control)──► [P2P Proxy Daemon] ◄──(mDNS / libp2p)──► [LAN Peers]
 (plugins/p2p_plugin.py)               (p2p_server.py:8888)                     (libp2p:8000)
                                              │
                                      [Local Cache / LRU]
                                 (/var/cache/dnf-plugin-p2p)
```

The system comprises four decoupled components:

1. **DNF 5 Plugin (`plugins/p2p_plugin.py`)**:
   - Hooks into libdnf5 via `libdnf5.plugin.IPlugin` (API 2.0).
   - Rewrites repository URLs from `https://` to local proxy endpoints (`http://127.0.0.1:8888`).
   - Disables delta compression (`config.zchunk = False`) to ensure full package interoperability.
   - Registers expected target SHA-256 package hashes with the local proxy for integrity verification.
2. **HTTP Proxy Daemon (`p2p-proxy-server/p2p_server.py`)**:
   - Multi-threaded proxy listening on `0.0.0.0:8888` (supports systemd socket activation).
   - Serves verified packages directly from local cache or LAN peers.
   - Automatically upgrades outbound mirror connections to HTTPS.
   - Rewrites metalink/mirrorlist payloads from `https://` to `http://` so subsequent package fetches route via P2P.
   - For large packages (>50MB) and 2+ available peers, executes **Swarm Chunk Downloads** concurrently over HTTP Range headers (`bytes=start-end`).
3. **P2P Discovery & Query (`p2p-proxy-server/p2p_libp2p.py`)**:
   - Autonomous `py-libp2p` node running in a background Trio event loop thread.
   - Advertises and discovers LAN peers via mDNS; communicates over protocol `/dnf-p2p/query/1.0.0`.
   - Ranks candidate peers by RTT latency to prioritize the fastest transfer source.
   - Enforces per-peer token-bucket rate limiting on incoming queries.
4. **Local LRU Cache (`p2p-proxy-server/p2p_cache.py`)**:
   - Thread-safe disk cache stored in `/var/cache/dnf-plugin-p2p`.
   - Enforces configurable size limits (`max_cache_size_mb`) and filesystem disk thresholds (`max_disk_usage_percent`), automatically evicting least-recently-used packages.
   - Validates SHA-256 checksums before serving or caching.

---

## Security & Hardening Boundaries

- **Localhost Control Endpoints**: Control endpoints (`/ping`, `/expected_hashes`, `/stats`) are strictly forbidden for remote IPs (returns HTTP 403) to prevent SSRF and control hijacking.
- **Remote Request Isolation**: Remote clients are restricted to downloading verified packages via `GET /packages/<filename>`. Arbitrary remote proxying via `remote_url` query parameters is rejected with HTTP 403 for remote IPs.
- **Cluster Token (PSK) Mutual Authentication**: Environments requiring restricted peer access can configure a shared `cluster_token`. Nodes reject unauthorized libp2p queries and HTTP package requests missing a matching `X-Cluster-Token` header.
- **Outbound HTTPS Upgrade**: Transparently upgrades upstream HTTP mirror URLs to HTTPS (`force_https = True`), protecting mirror traffic against plaintext eavesdropping and tampering.
- **SSRF Mitigation**: Peer discovery strictly validates reported addresses against unprivileged port ranges (1024-65535) and rejects cloud metadata (`169.254.169.254`), loopback, link-local, and reserved IP ranges.
- **Query Rate Limiting**: Protects against LAN broadcast query flooding using an in-memory token-bucket limiter per peer ID.
- **SELinux Hardening**: Packaged SELinux module (`dnf-plugin-p2p.te`) confines the proxy daemon under `dnf_p2p_t`, restricting file access to `dnf_p2p_cache_t` and limiting network binds to authorized ports.

---

## Quick Start

### 1. Installation

#### From Fedora Copr
```bash
sudo dnf copr enable -y staernid/dnf-plugin-p2p
sudo dnf install -y dnf-plugin-p2p
```

#### From Source
```bash
git clone --recurse-submodules https://github.com/staernid/libdnf-p2p-sharing.git
cd libdnf-p2p-sharing
mkdir build && cd build
cmake ..
make
sudo make install
```

### 2. Service & Firewall Configuration

Allow mDNS discovery (`5353/udp`), libp2p queries (`8000/tcp`), and HTTP transfers (`8888/tcp`):
```bash
sudo firewall-cmd --add-port=5353/udp --add-port=8000/tcp --add-port=8888/tcp --permanent
sudo firewall-cmd --reload

# Start and enable the proxy daemon
sudo systemctl enable --now dnf-p2p-proxy.service
```

### 3. Verification & Diagnostics

Run DNF normally:
```bash
sudo dnf install -y htop
```

Inspect proxy status, cache hit ratio, active peers, and saved LAN bandwidth:
```bash
dnf-p2p-client status
```

---

## Configuration Reference

Configuration file location:
`/etc/dnf/libdnf5-plugins/python_plugins_loader.d/p2p_plugin.conf`

```ini
[p2p]
# IP address for the HTTP proxy to bind (default: 0.0.0.0)
bind_host = 0.0.0.0

# Port for HTTP proxy server (default: 8888)
proxy_port = 8888

# Port for libp2p discovery listener (default: 8000)
libp2p_port = 8000

# Cache storage directory
cache_dir = /var/cache/dnf-plugin-p2p

# Maximum cache size on disk in megabytes (default: 1024)
max_cache_size_mb = 1024

# Maximum disk usage percentage before eviction begins (default: 90.0)
max_disk_usage_percent = 90.0

# Timeout in seconds when discovering LAN peers for a package (default: 2.0)
peer_discovery_timeout = 2.0

# Maximum concurrent peer queries per request (default: 5)
max_parallel_peers = 5

# Upgrade upstream mirror HTTP requests to HTTPS (default: true)
force_https = true

# Optional Pre-Shared Key (PSK) for cluster mutual authentication (default: none)
# cluster_token = your-secure-cluster-token

# libp2p incoming query rate limit in queries/sec per peer (default: 20.0)
query_rate_limit = 20.0

# libp2p incoming query rate burst capacity per peer (default: 30)
query_rate_burst = 30

# Enable verbose debug logging (default: false)
debug = false
```

---

## Development & Automated Testing

Testing uses isolated Fedora 44 containers to validate mDNS mesh discovery, direct peer sharing, hostile peer recovery, and live `dnf5` transactions without modifying host configurations or physical network interfaces.

- **Run Unit Tests**:
  ```bash
  pytest tests/
  ```
- **Run Automated Multi-Node Integration Test**:
  ```bash
  make dev-test
  ```
- **Development Containers**:
  - `make dev-build`: Build development container image (`dnf-p2p-dev:latest`).
  - `make dev-up`: Spin up `mock-repo`, `peer1`, `peer2`, and `peer3` in the background with local repository mounted.
  - `make dev-down`: Stop and remove dev containers and test volumes.
  - `make dev-logs`: Follow logs across all peer proxy daemons.
  - `make dev-shell PEER=1`: Open an interactive shell inside `peer1` (or `PEER=2`, `PEER=3`).

---

## Packaging

- **Build SRPM**:
  ```bash
  make srpm
  ```
- **Build Binary RPMs**:
  ```bash
  make rpm
  ```
- **Synchronize Version**:
  ```bash
  python3 bump-version.py <X.Y.Z>
  ```

---

## License

GNU General Public License v2.0 or later.
