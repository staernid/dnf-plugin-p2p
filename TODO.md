Based on a review of the implementation, there are a few areas where things are either **missing**, **redundant**, or **done in a way that will bottleneck performance**. 

Here is the list of key issues:

---

### 1. [DONE] Redundant Hash Calculations (Double-Hashing Overhead)
When a package is successfully downloaded from a mirror or peer, the proxy server hashes the file **twice in immediate succession**:
* In `p2p_server.py` (`_download_and_serve`):
  ```python
  file_hash = self.cache.get_file_hash(final_file)
  self.cache.add_to_cache(final_file, file_hash, {"source": url})
  ```
* Then, inside `p2p_cache.py` (`add_to_cache`):
  ```python
  file_hash = self.get_file_hash(file_path)
  if file_hash != package_hash:  # package_hash is the one we just passed in!
  ```
For large RPM packages (e.g. 100+ MB), reading and calculating the SHA-256 hash twice consecutively creates significant CPU and disk I/O overhead.

---

### 2. [DONE] Sequential, Blocking Peer Queries
In `p2p_libp2p.py`, `query_peers_for_package` queries discovered peers in a simple sequential `for` loop:
```python
for peer_id_str in peer_ids:
    # ...
    await self.host.connect(peerinfo)
    response = await self.rr.send_request(...)
```
* **The Problem:** If there are 5 local peers and 4 of them are stale or offline, the connection attempts will time out one by one. This blocks DNF's package download pipeline sequentially, causing DNF to hang for seconds for every single package.
* **A Better Way:** Since the node runs under the Trio event loop, these queries should be run **in parallel** (e.g., using `trio.open_nursery()`) with a strict global timeout (e.g., `trio.fail_after(2.0)`).

---

### 3. [DONE] Ignored User Configuration
The DNF configuration file (`/etc/dnf/libdnf5-plugins/python_plugins_loader.d/p2p_plugin.conf`) contains settings like:
```ini
peer_discovery_timeout = 2
max_parallel_peers = 5
```
* **The Problem:** The background proxy server daemon (`p2p_server.py`) is started by systemd and **never reads this configuration file**. It only takes a few basic command-line arguments (port, host, cache-dir).
* **The Result:** The timeout and concurrency limits defined in the configuration file are completely ignored by the daemon that actually handles the network queries.

---

### 4. No Cache Eviction or Size Limits
The cache manager (`p2p_cache.py`) handles writing files to `/var/cache/dnf-plugin-p2p/`, but it lacks any mechanism to prune them.
* **The Problem:** There is no maximum cache size limit, total disk space percentage check, or LRU (Least Recently Used) eviction policy.
* **The Result:** The cache directory will grow indefinitely until the host machine runs out of disk space.

---

### 5. Forced HTTPS Upgrades Can Break Internal Mirrors
In `p2p_server.py`, the proxy automatically rewrites all non-localhost upstream HTTP mirrors to HTTPS:
```python
if remote_url and remote_url.startswith("http://"):
    parsed_remote = urllib.parse.urlparse(remote_url)
    if parsed_remote.hostname not in ("127.0.0.1", "localhost"):
        remote_url = remote_url.replace("http://", "https://", 1)
```

### 6. Default Systemd Service Port Configuration Bug
* **The issue:** In `p2p_libp2p.py`, if the `libp2p_port` option is `0` (the default), it binds to a random free port. However, `py-libp2p`'s `MDNSDiscovery` hardcodes the advertised port to `8000`.
* **The bug:** In `systemd/dnf-p2p-proxy.service`, the default `ExecStart` command does **not** specify `--libp2p-port=8000`. This means the daemon binds to a random port by default. Other nodes discover it via mDNS, try to connect on port 8000, and immediately fail to connect.
* **The fix:** The systemd service file's `ExecStart` command should explicitly default to `--libp2p-port=8000`.

---

### 7. Polkit Authorization Block on Non-Root DNF Commands
* **The issue:** Non-root users frequently run read-only DNF commands (e.g. `dnf search`, `dnf list`, `dnf info`). During plugin initialization (`plugins/p2p_plugin.py`), the plugin runs:
  ```python
  subprocess.run(["systemctl", "start", "dnf-p2p-proxy.service"])
  ```
* **The problem:** Running `systemctl start` as a non-root user triggers a Polkit prompt asking for the root/admin password in the console. For simple queries that shouldn't require root permissions, this blocks the terminal and disrupts the user experience.
* **The fix:** The plugin should check `os.geteuid() == 0` first and only attempt to start the systemd service if running as root.

---

### 8. Hardcoded Python Version in Shell/Environment Files
* **The issue:** Both `/etc/profile.d/libdnf-python-plugin.sh` and `/etc/environment.d/libdnf-python-plugin.conf` hardcode the Python path:
  ```bash
  export LIBDNF_PYTHON_PLUGIN_DIR=/usr/lib/python3.14/site-packages/libdnf_plugins
  ```
* **The problem:** If the OS is upgraded (e.g. from Fedora 41 to Fedora 42, transitioning from Python 3.13 to 3.14 or 3.15), these configurations point to a non-existent or wrong directory and break the plugin loader.
* **The fix:** This path should be dynamically generated during the RPM build/installation step (e.g. using `python3 -c "import sys; print(sys.path)"` or CMake python detection variables).

---

### 9. Broken Test Mocking (Silent Test Failures)
* **The issue:** In `tests/test_p2p_server.py` (`test_http_handler_cache_hit`), the mock for `builtins.open` is nested incorrectly:
  ```python
  patch("builtins.open", patch("io.BytesIO", return_value=b"mock-rpm-bytes"))
  ```
  This passes a `patch` context manager object as the replacement for `open()`, which is not callable and will throw an exception when the handler attempts to run `with open(...)`.
* **Why the test still passes:** The HTTP server sends the status code and headers (`200 OK`) *before* opening the file:
  ```python
  self.send_response(200)
  self.end_headers()
  with open(file_path, 'rb') as f:  # Throws exception here
  ```
  The exception is caught inside the handler's catch-all `except Exception as e:` block and logged, but because the headers were already transmitted, the test client (`urllib.request.urlopen`) registers a `200` success and the test passes silently without receiving any package bytes.
* **The fix:** Correctly mock the file opener using `mock_open` (e.g., `mock_open(read_data=b"mock-rpm-bytes")`) and assert the response body content in the test.

---
