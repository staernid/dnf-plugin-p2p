# Agent Development Guide

`dnf-plugin-p2p` enables peer-to-peer RPM sharing on local networks (LAN) for systems running DNF 5 / libdnf5 without repository configuration changes.

---

## Architecture & Seams

The project consists of three deep modules with clean seams:

```
DNF 5 CLI / libdnf5
       │
       ▼ (in-memory URL rewrite: https:// -> http://127.0.0.1:8888)
[libdnf5 Plugin] ──(HTTP control)──► [P2P Proxy Daemon] ◄──(mDNS / JSON query)──► [LAN Peers]
 (plugins/p2p_plugin.py)               (p2p_server.py:8888)                          (libp2p:8000)
                                              │
                                      [Local Cache / LRU]
                                 (/var/cache/dnf-plugin-p2p)
```

### 1. DNF 5 Plugin (`plugins/p2p_plugin.py`)
- **Interface**: Hooks into DNF 5 via `libdnf5.plugin.IPlugin`.
- **Seam**: In-memory repository URL rewriting (`https://` to `http://`), disables zchunk delta compression (`config.zchunk = False`), and `/ping` health-checks the proxy daemon.
- **Invariant**: Must inherit from `libdnf5.plugin.IPlugin` (API 2.0). Never inherit from `IPlugin2_1` (SWIG abstract class without constructor, crashes at runtime).
- **Invariant**: Never attempt service management (`systemctl`) when executed by non-root users to avoid Polkit authorization prompts during read-only DNF operations.

### 2. HTTP Proxy Daemon (`p2p-proxy-server/p2p_server.py`)
- **Interface**: Multi-threaded synchronous HTTP server (`HTTPServer` + `ThreadingMixIn`) listening on `0.0.0.0:8888`.
- **Seam**: Intercepts `.rpm` requests, checks local cache, queries LAN peers via libp2p, or falls back to upstream mirrors (upgrading connection to HTTPS). Rewrites metalink XML URLs from `https://` to `http://`.
- **Security Invariant**: Control endpoints (`/ping`, `/expected_hashes`, `/stats`) and queries with `remote_url` query parameters are strictly forbidden for remote IPs (returns 403) to prevent SSRF and remote cache poisoning.
- **Timing Invariant**: In DNF 5, package downloads execute during transaction preparation *before* `pre_transaction` registers expected hashes. The proxy queries peers and verifies transfers against the peer's self-reported hash; package integrity is fully guaranteed by DNF 5's internal GPG signature check before installation.

### 3. P2P Discovery (`p2p-proxy-server/p2p_libp2p.py`)
- **Interface**: `py-libp2p` node running in a background Trio event loop thread.
- **Seam**: Discovers LAN peers via mDNS; exchanges package availability over protocol `/dnf-p2p/query/1.0.0`.
- **Invariant**: The libp2p TCP listener must bind to port `8000` (`py-libp2p`'s `MDNSDiscovery` hardcodes the advertised port to 8000). Crosses thread boundaries to HTTP workers via thread-safe async helpers.

### 4. Local Cache (`p2p-proxy-server/p2p_cache.py`)
- **Interface**: Thread-safe LRU cache under `/var/cache/dnf-plugin-p2p`.
- **Seam**: Enforces size and filesystem disk-percentage limits, evicting oldest packages. Validates SHA-256 before serving.

---

## Verification & Testing Boundaries

- **Run unit tests**:
  ```bash
  pytest tests/
  ```
- **Run automated multi-node integration tests**:
  ```bash
  make dev-test
  ```
  Spins up isolated Fedora 44 containers (`peer1`, `peer2`, and `mock-repo`), validates mDNS peer discovery, direct P2P package sharing, and real `dnf5 install` via `p2p_plugin.py`.
- **Local container development commands**:
  - `make dev-build`: Build the Fedora development image (`dnf-p2p-dev:latest`).
  - `make dev-up`: Start `peer1`, `peer2`, and `mock-repo` in the background with local code mounted.
  - `make dev-down`: Stop and remove dev containers.
  - `make dev-shell PEER=1`: Open an interactive shell inside `peer1` (or `PEER=2`).
  - `make dev-logs`: Tail logs from peer daemons.
- **Rule**: Never run bare `pytest` without specifying `tests/`. The bundled `py-libp2p-src/` submodule will cause collection failures.
- **Mocking Rule**: The HTTP proxy transmits headers before streaming package content. When mocking file operations, ensure file open/read mocks succeed to avoid silently failing HTTP 200 streams.
- **Manual Network Testing Warning**: Do NOT manually touch, SSH into, or modify remote physical laptops on the local network. All testing and multi-node validation is fully automated using `make dev-test` in isolated local containers.

---

## Build, Submodule & Packaging

- **Bundled Submodule**: `py-libp2p-src` is tracked as a git submodule with patches in `patches/`.
  - Apply patches locally: `make patch-libp2p`
- **RPM Build**: `make srpm` and `make rpm` automatically package local patches and build RPMs.
- **Version Single Source of Truth**: The `Version:` field in `dnf-plugin-p2p.spec`.
  - Use `python3 bump-version.py <X.Y.Z>` to synchronize the version across the spec file, `CMakeLists.txt`, and Python modules.
