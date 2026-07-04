# DNF P2P Package Sharing Plugin - Design Specification

This document outlines the architecture, integration lifecycle, protocols, and developer post-mortem for `dnf-plugin-p2p`.

---

## 1. System Architecture

The system enables peer-to-peer sharing of RPM packages over a local network (LAN) for systems running **DNF 5**.

```mermaid
graph TD
    DNF["DNF5 / libdnf5 CLI"]
    Plugin["libdnf5 Plugin (p2p_plugin.py)"]
    Proxy["P2P Proxy Daemon (p2p_server.py)"]
    Libp2p["libp2p Node (p2p_libp2p.py)"]
    Cache["Local Cache (/var/cache/dnf-plugin-p2p)"]
    Peer["LAN Peer Proxy"]
    Upstream["Upstream Mirrors (HTTPS)"]

    DNF -->|1. Intercept / Call Hooks| Plugin
    Plugin -->|2. Register Hashes (POST)| Proxy
    DNF -->|3. Plaintext HTTP Request| Proxy
    Proxy -->|4. Check Cache| Cache
    Proxy -->|5. Find Peers / Query| Libp2p
    Libp2p -->|6. JSON Query (libp2p)| Peer
    Proxy -->|7. HTTP Download| Peer
    Proxy -->|8. Fallback (HTTPS)| Upstream
```

### Components
1. **libdnf5 Plugin (`plugins/p2p_plugin.py`)**: A Python-based plugin loaded by DNF 5's Python Plugins Loader. Rewrites repository base URLs to route through the local proxy and registers expected transaction hashes.
2. **P2P Proxy Daemon (`p2p-proxy-server/`)**: A background service containing:
   - **HTTP Proxy Server (`p2p_server.py`)**: Serves local client and remote peer package requests.
   - **libp2p Node (`p2p_libp2p.py`)**: Runs in a background Trio event loop thread; handles peer discovery via mDNS (port 8000/TCP) and protocol queries.
   - **Local Cache (`p2p_cache.py`)**: Saves downloaded packages securely under `/var/cache/dnf-plugin-p2p`.
3. **Diagnostics CLI (`dnf-p2p-client`)**: Queries stats and peer connection state from the local proxy.

---

## 2. DNF 5 Plugin Lifecycle Hooks

The plugin inherits from `libdnf5.plugin.IPlugin` and overrides the following methods:

1. **`init`**:
   - Performs a `/ping` health check on `http://127.0.0.1:8888`. If inactive and run by `root`, starts the systemd service. If inactive and non-root, bypasses proxying to avoid Polkit auth prompts.
2. **`pre_base_setup`**:
   - Disables `zchunk` compression (`config.zchunk = False`) because delta range requests cannot be reliably parsed/served via P2P.
3. **`repos_configured`**:
   - Loops through remote repos, redirects their proxy to `http://127.0.0.1:8888`, and downgrades `https://` URLs to `http://` in-memory. Plaintext HTTP allows the proxy to inspect paths and extract filenames.
4. **`pre_transaction`**:
   - Executed before packages are downloaded. Collects target package names and their expected SHA-256 hashes, then sends them to the local proxy via `POST /expected_hashes`.

---

## 3. Communication Protocols

### 3.1 Daemon HTTP APIs (Port 8888, Local Only)
- `GET /ping`: Responds with `pong` (health check).
- `POST /expected_hashes`: Receives a JSON map of `{filename: sha256_hash}`.
- `GET /stats`: Returns JSON server state (hits, misses, discovered/active peers, bandwidth saved).
- `GET /packages/<filename>`: Streams target RPM. External peers querying this endpoint are forbidden from using the `remote_url` query parameter to prevent Server-Side Request Forgery (SSRF).

### 3.2 Peer-to-Peer Protocol (Port 8000/TCP, Protocol `/dnf-p2p/query/1.0.0`)
- Peers exchange JSON query messages:
  - **Request**: `{"package": "filename.rpm"}`
  - **Response**: `{"has_package": true, "http_port": 8888, "hash": "sha256", "size": 12345}`

---

## 4. Wrong Paths Went Down (Post-Mortem)

During development and debugging, several misleading assumptions and design regressions occurred:

### 4.1 SWIG Abstract Class Error (`IPlugin2_1`)
- **Wrong Path**: We attempted to inherit our python plugin class from `libdnf5.plugin.IPlugin2_1` to utilize DNF 5 API 2.1 features.
- **Root Cause**: In C++/SWIG, `IPlugin2_1` is treated as an abstract class. The SWIG Python mapping lacks a concrete constructor, leading to `AttributeError: No constructor defined - class is abstract` inside the python plugin loader.
- **Resolution**: Reverted the base class to `libdnf5.plugin.IPlugin` (API 2.0). SWIG director structures successfully bind and forward all callbacks (including `pre_transaction`) when inheriting from the non-abstract parent class.

### 4.2 Ineffective Hook Method (`goal_resolved`)
- **Wrong Path**: The original implementation used the `goal_resolved(self, transaction)` hook method to collect transaction hashes.
- **Root Cause**: `goal_resolved` is not defined in the base `IPlugin` class, but rather in `IPlugin2_1`. Because the DNF 5 Python Plugins Loader only binds hooks present on `IPlugin` (API 2.0), the python implementation of `goal_resolved` was completely ignored by DNF. The proxy server never received expected hashes and bypassed P2P sharing entirely for real transactions.
- **Resolution**: Replaced it with the `pre_transaction(self, transaction)` hook, which is part of the `IPlugin` class and executes successfully before package downloads begin.

### 4.3 Misleading Cache Hit Optimization with `tsflags=test`
- **Wrong Path**: When executing dry-run transactions (`--setopt=tsflags=test`) to verify hash registration, we observed that `pre_transaction` was occasionally not executed. We assumed that DNF 5's bindings completely blocked parameter forwarding.
- **Root Cause**: If the target packages were already present in DNF 5's local cache `/var/cache/libdnf5/` (e.g., from previous test commands), DNF 5 optimizations bypassed the download loop entirely, meaning `pre_transaction` was never triggered.
- **Resolution**: Cleared DNF 5's cache directory (e.g., `sudo dnf clean all` and deleting specific cached package files) before running transaction tests. This forces DNF 5 to schedule package downloads, consistently triggering `pre_transaction` and registering hashes.

### 4.4 DNF 5 Download Timing & Relaxed Hash Verification
- **Wrong Path**: Requiring expected package hashes to be pre-registered by the DNF plugin before the proxy would allow P2P querying, downloads, and caching.
- **Root Cause**: In DNF 5, package downloads are executed during the transaction preparation phase, which occurs *before* the transaction execution phase (where `pre_transaction` is called). Therefore, in any clean DNF transaction, package GET requests arrive at the proxy before the plugin can register their hashes.
- **Resolution**: Relaxed the validation restriction. If the expected hash has not been pre-registered, the proxy still queries peers and downloads via P2P. It validates the package against the peer's self-reported hash to ensure transfer integrity, caches it, and serves it. Final package authenticity is fully guaranteed by DNF 5's internal GPG signature validation which executes before packages are installed. This allows P2P package sharing to function transparently for all DNF commands (such as `dnf install`, `dnf download`, etc.).
