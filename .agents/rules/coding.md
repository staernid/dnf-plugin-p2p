---
trigger: always_on
glob: "**/*.{py,md,ini,conf,sh}"
description: Code quality, concurrency, testing, and performance guidelines for the dnf-plugin-p2p repository.
---

# Coding and Testing Rules for dnf-plugin-p2p

This document defines core guidelines, development practices, and architecture rules for agents working on the `dnf-plugin-p2p` project.

---

## 1. Project Architecture & Concurrency Boundaries
The codebase consists of:
*   **The DNF5 Plugin (`plugins/p2p_plugin.py`)**: Intercepts repo configuration and redirects package queries to the local HTTP proxy.
*   **The HTTP Proxy Server (`p2p-proxy-server/p2p_server.py`)**: A multi-threaded, synchronous HTTP server utilizing Python's standard library `HTTPServer` and `ThreadingMixIn`.
*   **The libp2p Node (`p2p-proxy-server/p2p_libp2p.py`)**: An asynchronous P2P networking node powered by `py-libp2p` and the `Trio` event loop.

### Concurrency Rules:
*   **Thread Safety**: The HTTP handler spins up a new thread for each connection. Access to the cache index or any shared state must be protected using thread locks (e.g. `self.lock = threading.RLock()` in `P2PCache`).
*   **Synchronous to Asynchronous Bridge**: Because the HTTP proxy is synchronous/multi-threaded and the libp2p node is asynchronous/Trio-based, communication from the HTTP handler thread to the libp2p node must go through thread-safe channels (e.g. `trio.from_thread.run` or thread-safe callbacks).

---

## 2. Testing Guidelines

### Running Tests:
*   **Do not run `pytest` globally**: The repository contains `py-libp2p-src` as a sub-source directory. Running `pytest` without path limits will attempt to collect tests from `py-libp2p-src`, resulting in missing module dependency and collection failures.
*   **Rule**: Always target the `tests/` directory specifically:
    ```bash
    .venv/bin/pytest tests/
    ```

### Mocking & Writing Tests:
*   **HTTP Response Validation**: The HTTP handler transmits the status code and headers *before* attempting to open the cached package file. A bad mock on file opening will cause an exception *after* the client receives `200 OK`. The client might register success, masking a silent failure.
*   **Rule**: When mocking file operations or cache hits in tests:
    1.  Ensure `builtins.open` is mocked correctly (e.g., using `mock_open(read_data=...)`).
    2.  Assert both the HTTP response status code AND the correctness of the response body.
*   **Cache Tests**: Write unit tests for `P2PCache` in `tests/test_p2p_cache.py` and verify file hash computations are only performed once.

---

## 3. Performance & I/O Optimizations

*   **Avoid Redundant Hash Calculations**: Calculating SHA-256 hashes of large RPM packages (100MB+) is CPU and disk-bound.
    *   **Rule**: The HTTP proxy server must delegate caching to `P2PCache.add_to_cache` without calculating the hash beforehand. Let `P2PCache` compute the hash once, verify it (if an expected hash is provided), and use it for indexing.
*   **Concurrent Peer Queries**:
    *   **Rule**: Do not query peers sequentially in a loop. When querying multiple local peers, query them concurrently (e.g. using Trio nurseries or parallel tasks) with a global timeout to prevent DNF from hanging on stale or offline peers.

---

## 4. Configuration and Environment Guidelines

*   **Respect User Configuration**: Daemon components should respect the settings defined in `/etc/dnf/libdnf5-plugins/python_plugins_loader.d/p2p_plugin.conf` (e.g. `peer_discovery_timeout`, `max_parallel_peers`).
*   **Port Consistency**: Ensure default libp2p ports match standard specifications (e.g. advertising on port `8000` to align with the hardcoded mDNS discovery configurations).
*   **User Privileges**: DNF read-only commands (like `list`, `search`, `info`) are often run by non-root users. The DNF plugin must avoid initiating systemd services (e.g., calling `systemctl start dnf-p2p-proxy.service`) when run by a non-root user to avoid unnecessary Polkit authorization prompts.
