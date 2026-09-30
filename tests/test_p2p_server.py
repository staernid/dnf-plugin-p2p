import threading
import urllib.request
import urllib.parse
import urllib.error
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from p2p_server import P2PProxyHandler

@pytest.fixture
def test_server():
    # Set up mock cache and libp2p node
    mock_cache = MagicMock()
    mock_cache.cache_dir = Path("/tmp/mock_cache_dir")
    
    mock_node = MagicMock()
    
    # Configure handler class variables
    P2PProxyHandler.cache = mock_cache
    P2PProxyHandler.libp2p_node = mock_node
    P2PProxyHandler.cluster_token = None
    
    # Spin up server on ephemeral port
    server = HTTPServer(("127.0.0.1", 0), P2PProxyHandler)
    server_port = server.server_address[1]
    
    # Run server in background thread
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    
    yield server, server_port, mock_cache, mock_node
    
    # Shutdown server
    server.shutdown()
    server.server_close()
    server_thread.join()
    P2PProxyHandler.cluster_token = None

def test_http_handler_cache_hit(test_server):
    server, port, mock_cache, mock_node = test_server
    
    # Mock cache file exists
    temp_file = Path("/tmp/mock_cache_dir/test-package.rpm")
    mock_cache.get_cached_file_by_name.return_value = temp_file
    
    # Patch Path.exists to return True for the cache file and mock size
    from unittest.mock import mock_open
    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "stat") as mock_stat, \
         patch("builtins.open", mock_open(read_data=b"mock-rpm-bytes")):
        
        mock_stat.return_value.st_size = 14
        
        # Make HTTP request
        url = f"http://127.0.0.1:{port}/packages/test-package.rpm"
        response = urllib.request.urlopen(url)
        
        assert response.getcode() == 200
        assert response.headers.get("Content-Type") == "application/x-redhat-package-manager"
        assert response.headers.get("Content-Length") == "14"
        assert response.read() == b"mock-rpm-bytes"

def test_http_handler_peer_fallback(test_server):
    server, port, mock_cache, mock_node = test_server
    mock_cache.get_cached_file_by_name.return_value = None
    
    # Calculate expected hash of b"chunk1chunk2"
    import hashlib
    expected_hash = hashlib.sha256(b"chunk1chunk2").hexdigest()

    # Package does not exist locally
    mock_node.query_peers_for_package.return_value = [
        {"ip": "192.168.1.100", "port": 8888, "hash": expected_hash, "size": 100}
    ]
    
    # Mock requests.get to return a successful download from peer
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Length": "12"}
    mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]
    
    from unittest.mock import mock_open
    with patch.object(Path, "exists", return_value=False), \
         patch.object(Path, "rename") as mock_rename, \
         patch("requests.get", return_value=mock_response) as mock_get, \
         patch("builtins.open", mock_open()):
        
        # Register expected hash in the handler first
        P2PProxyHandler.expected_hashes["test-package.rpm"] = expected_hash
        try:
            # Trigger download from peer
            url = f"http://127.0.0.1:{port}/packages/test-package.rpm"
            response = urllib.request.urlopen(url, timeout=1)
            assert response.getcode() == 200
            assert response.read() == b"chunk1chunk2"
                
            # Assert that it queried the libp2p node and tried to download from the peer
            mock_node.query_peers_for_package.assert_called_with("test-package.rpm")
            mock_get.assert_any_call("http://192.168.1.100:8888/packages/test-package.rpm", stream=True, timeout=15, allow_redirects=False)
        finally:
            P2PProxyHandler.expected_hashes.pop("test-package.rpm", None)


def test_main_config_loading_and_override():
    import sys
    from p2p_server import main
    from unittest.mock import patch, MagicMock

    # Create mock node and server to prevent main() from actually running the server
    mock_node_instance = MagicMock()
    mock_server_instance = MagicMock()

    # Define a custom exception to interrupt main() right when it tries to serve_forever()
    class ServeForeverCalled(BaseException):
        pass

    mock_server_instance.serve_forever.side_effect = ServeForeverCalled()

    # Mock command line arguments
    test_argv = ["p2p_server.py", "--config", "/mock/path/p2p_plugin.conf", "--host", "127.0.0.9"]

    with patch("sys.argv", test_argv), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("configparser.ConfigParser.read") as mock_read, \
         patch("configparser.ConfigParser.has_section", return_value=True), \
         patch("configparser.ConfigParser.has_option", side_effect=lambda sec, opt: True), \
         patch("configparser.ConfigParser.get", side_effect=lambda sec, opt: {
             "proxy_host": "127.0.0.2",
             "proxy_port": "9999",
             "peer_discovery_timeout": "4.5",
             "max_parallel_peers": "12",
             "debug": "true",
             "max_cache_size_mb": "512",
             "max_disk_usage_percent": "80.0",
             "force_https": "false",
             "libp2p_port": "7777",
             "cache_dir": "/mock/cache",
             "cluster_token": "my-cluster-token"
         }[opt]), \
         patch("configparser.ConfigParser.getint", side_effect=lambda sec, opt: {
             "proxy_port": 9999,
             "max_parallel_peers": 12,
             "max_cache_size_mb": 512,
             "libp2p_port": 7777,
             "query_rate_burst": 25
         }[opt]), \
         patch("configparser.ConfigParser.getfloat", side_effect=lambda sec, opt: {
             "peer_discovery_timeout": 4.5,
             "max_disk_usage_percent": 80.0,
             "query_rate_limit": 15.0
         }[opt]), \
         patch("configparser.ConfigParser.getboolean", side_effect=lambda sec, opt: {
             "debug": True,
             "force_https": False
         }[opt]), \
         patch("p2p_server.P2PLibp2pNode", return_value=mock_node_instance) as mock_node_cls, \
         patch("p2p_server.P2PCache") as mock_cache_cls, \
         patch("p2p_server.ThreadingHTTPServer", return_value=mock_server_instance) as mock_server_cls:

        try:
            with pytest.raises(ServeForeverCalled):
                main()

            # Assert node initialization parameters
            # `--host 127.0.0.9` should override config file "127.0.0.2"
            # Since `--port` was not specified, it should fall back to config file "9999"
            # Since `--peer-discovery-timeout` was not specified, it should fall back to config file "4.5"
            # Since `--max-parallel-peers` was not specified, it should fall back to config file "12"
            # Since `--libp2p-port` was not specified, it should fall back to config file "7777"
            mock_node_cls.assert_called_once_with(
                libp2p_port=7777,
                local_http_port=9999,
                cache_lookup_callback=mock_cache_cls.return_value.lookup_filename,
                peer_discovery_timeout=4.5,
                max_parallel_peers=12,
                cluster_token="my-cluster-token",
                query_rate_limit=15.0,
                query_rate_burst=25
            )
            assert P2PProxyHandler.cluster_token == "my-cluster-token"

            mock_cache_cls.assert_called_once_with(
                Path("/mock/cache"),
                max_cache_size_mb=512,
                max_disk_usage_percent=80.0
            )

            mock_server_cls.assert_called_once_with(
                ("127.0.0.9", 9999),
                mock_server_cls.call_args[0][1] # P2PProxyHandler
            )

            # Assert force_https setting was set on P2PProxyHandler class
            assert P2PProxyHandler.force_https is False
        finally:
            P2PProxyHandler.cluster_token = None
            P2PProxyHandler.force_https = True




def test_http_handler_force_https_enabled(test_server):
    server, port, mock_cache, mock_node = test_server
    mock_cache.get_cached_file_by_name.return_value = None
    mock_node.query_peers_for_package.return_value = []
    
    import hashlib
    expected_hash = hashlib.sha256(b"chunk1").hexdigest()
    P2PProxyHandler.expected_hashes["test-package.rpm"] = expected_hash
    P2PProxyHandler.force_https = True
    
    # Mock requests.get to return a successful response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Length": "6"}
    mock_response.iter_content.return_value = [b"chunk1"]
    
    from unittest.mock import mock_open
    try:
        with patch.object(Path, "exists", return_value=False), \
             patch.object(Path, "rename") as mock_rename, \
             patch("requests.get", return_value=mock_response) as mock_get, \
             patch("builtins.open", mock_open()):
            
            url = f"http://127.0.0.1:{port}/packages/test-package.rpm?remote_url=http://mirror.foo.com/packages/test-package.rpm"
            response = urllib.request.urlopen(url, timeout=1)
            assert response.getcode() == 200
            assert response.read() == b"chunk1"
                
            # Assert that requests.get was called with the upgraded HTTPS url
            mock_get.assert_any_call("https://mirror.foo.com/packages/test-package.rpm", stream=True, timeout=15)
    finally:
        P2PProxyHandler.expected_hashes.pop("test-package.rpm", None)


def test_http_handler_force_https_disabled(test_server):
    server, port, mock_cache, mock_node = test_server
    mock_cache.get_cached_file_by_name.return_value = None
    mock_node.query_peers_for_package.return_value = []
    
    import hashlib
    expected_hash = hashlib.sha256(b"chunk1").hexdigest()
    P2PProxyHandler.expected_hashes["test-package.rpm"] = expected_hash
    P2PProxyHandler.force_https = False
    
    # Mock requests.get to return a successful response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Length": "6"}
    mock_response.iter_content.return_value = [b"chunk1"]
    
    from unittest.mock import mock_open
    try:
        with patch.object(Path, "exists", return_value=False), \
             patch.object(Path, "rename") as mock_rename, \
             patch("requests.get", return_value=mock_response) as mock_get, \
             patch("builtins.open", mock_open()):
            
            url = f"http://127.0.0.1:{port}/packages/test-package.rpm?remote_url=http://mirror.foo.com/packages/test-package.rpm"
            response = urllib.request.urlopen(url, timeout=1)
            assert response.getcode() == 200
            assert response.read() == b"chunk1"
                
            # Assert that requests.get was called with the original HTTP url
            mock_get.assert_any_call("http://mirror.foo.com/packages/test-package.rpm", stream=True, timeout=15)
    finally:
        P2PProxyHandler.expected_hashes.pop("test-package.rpm", None)


def test_http_handler_remote_client_denied(test_server):
    server, port, mock_cache, mock_node = test_server
    with patch.object(P2PProxyHandler, "_is_local_client", return_value=False):
        # Remote client tries to access non-packages path
        url = f"http://127.0.0.1:{port}/invalid-path"
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(url, timeout=1)
        assert excinfo.value.code == 403
        
        # Remote client tries to access with remote_url parameter
        url = f"http://127.0.0.1:{port}/packages/test.rpm?remote_url=http://unsafe.com"
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(url, timeout=1)
        assert excinfo.value.code == 403

        # Remote client requests uncached package
        mock_cache.get_cached_file_by_name.return_value = None
        url = f"http://127.0.0.1:{port}/packages/uncached.rpm"
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(url, timeout=1)
        assert excinfo.value.code == 404


def test_http_handler_diagnostic_endpoint(test_server):
    server, port, mock_cache, mock_node = test_server
    
    # 1. Local GET request
    url = f"http://127.0.0.1:{port}/packages/p2p-diagnostic.txt"
    response = urllib.request.urlopen(url, timeout=1)
    assert response.getcode() == 200
    assert response.headers.get("Content-Type") == "text/plain"
    assert response.headers.get("Content-Length") == "2"
    assert response.read() == b"OK"

    # 2. Local HEAD request
    req = urllib.request.Request(url, method="HEAD")
    response_head = urllib.request.urlopen(req, timeout=1)
    assert response_head.getcode() == 200
    assert response_head.headers.get("Content-Type") == "text/plain"
    assert response_head.headers.get("Content-Length") == "2"
    assert response_head.read() == b""

    # 3. Remote client GET request (should be allowed and succeed)
    with patch.object(P2PProxyHandler, "_is_local_client", return_value=False):
        response_remote = urllib.request.urlopen(url, timeout=1)
        assert response_remote.getcode() == 200
        assert response_remote.read() == b"OK"


def test_http_handler_expected_hash_mismatch(test_server):
    server, port, mock_cache, mock_node = test_server
    mock_cache.get_cached_file_by_name.return_value = None
    
    # Mock requests.get to return chunk1, chunk2 (which doesn't match the expected_hash)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Length": "12"}
    mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]

    from unittest.mock import mock_open
    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "rename") as mock_rename, \
         patch.object(Path, "unlink") as mock_unlink, \
         patch("requests.get", return_value=mock_response) as mock_get, \
         patch("builtins.open", mock_open()):
        
        P2PProxyHandler.expected_hashes["bad-package.rpm"] = "wrong_hash_value"
        try:
            url = f"http://127.0.0.1:{port}/packages/bad-package.rpm?remote_url=http://mirror.foo.com/bad-package.rpm"
            response = urllib.request.urlopen(url, timeout=1)
            assert response.read() == b"chunk1chunk2"
            
            # Since hash verification failed, it should not rename or add to cache
            mock_rename.assert_not_called()
            mock_cache.add_to_cache.assert_not_called()
            # It should unlink the temp file
            mock_unlink.assert_called_once()
        finally:
            P2PProxyHandler.expected_hashes.pop("bad-package.rpm", None)


def test_http_handler_cache_corruption_eviction(test_server):
    server, port, mock_cache, mock_node = test_server
    
    # Package is supposedly cached
    cached_file = Path("/tmp/mock_cache_dir/corrupted.rpm")
    mock_cache.get_cached_file_by_name.return_value = cached_file
    
    # Mock get_file_hash to return incorrect hash
    mock_cache.get_file_hash.return_value = "incorrect_hash"
    
    # Register a correct expected hash
    P2PProxyHandler.expected_hashes["corrupted.rpm"] = "correct_hash"
    
    # Mock requests.get fallback
    mock_response = MagicMock()
    mock_response.status_code = 404
    
    with patch.object(Path, "unlink") as mock_unlink, \
         patch("requests.get", return_value=mock_response):
        
        url = f"http://127.0.0.1:{port}/packages/corrupted.rpm"
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(url, timeout=1)
        
        # Unlink should be called to evict the corrupted package from disk
        mock_unlink.assert_called_once()
        P2PProxyHandler.expected_hashes.pop("corrupted.rpm", None)


def test_http_handler_stats(test_server):
    import json
    server, port, mock_cache, mock_node = test_server
    
    # Reset stats
    with P2PProxyHandler.stats_lock:
        P2PProxyHandler.cache_hits = 0
        P2PProxyHandler.cache_misses = 0
        P2PProxyHandler.bandwidth_saved = 0

    # 1. Access stats endpoint (empty stats)
    url = f"http://127.0.0.1:{port}/stats"
    response = urllib.request.urlopen(url)
    assert response.getcode() == 200
    data = json.loads(response.read().decode('utf-8'))
    assert data["cache_hits"] == 0
    assert data["cache_misses"] == 0
    assert data["cache_hit_miss_ratio"] == 0.0
    assert data["bandwidth_saved_bytes"] == 0

    # 2. Simulate a cache hit
    temp_file = Path("/tmp/mock_cache_dir/test-package.rpm")
    mock_cache.get_cached_file_by_name.return_value = temp_file
    
    from unittest.mock import mock_open
    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "stat") as mock_stat, \
         patch("builtins.open", mock_open(read_data=b"mock-rpm-bytes")):
        
        mock_stat.return_value.st_size = 14
        
        url_hit = f"http://127.0.0.1:{port}/packages/test-package.rpm"
        urllib.request.urlopen(url_hit)
        
    # Check stats again
    response = urllib.request.urlopen(url)
    data = json.loads(response.read().decode('utf-8'))
    assert data["cache_hits"] == 1
    assert data["cache_misses"] == 0
    assert data["cache_hit_miss_ratio"] == 1.0
    assert data["bandwidth_saved_bytes"] == 14


def test_http_handler_peer_fallback_ipv6(test_server):
    server, port, mock_cache, mock_node = test_server
    mock_cache.get_cached_file_by_name.return_value = None
    
    import hashlib
    expected_hash = hashlib.sha256(b"chunk1").hexdigest()

    # Package does not exist locally; peer has IPv6 address
    mock_node.query_peers_for_package.return_value = [
        {"ip": "2001:db8::1", "port": 8888, "hash": expected_hash, "size": 100}
    ]
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Length": "6"}
    mock_response.iter_content.return_value = [b"chunk1"]
    
    from unittest.mock import mock_open
    with patch.object(Path, "exists", return_value=False), \
         patch.object(Path, "rename") as mock_rename, \
         patch("requests.get", return_value=mock_response) as mock_get, \
         patch("builtins.open", mock_open()):
        
        P2PProxyHandler.expected_hashes["ipv6-package.rpm"] = expected_hash
        try:
            url = f"http://127.0.0.1:{port}/packages/ipv6-package.rpm"
            response = urllib.request.urlopen(url, timeout=1)
            assert response.getcode() == 200
            assert response.read() == b"chunk1"
            
            # Assert that requests.get was called with bracket-enclosed IPv6 address
            mock_get.assert_any_call("http://[2001:db8::1]:8888/packages/ipv6-package.rpm", stream=True, timeout=15, allow_redirects=False)
        finally:
            P2PProxyHandler.expected_hashes.pop("ipv6-package.rpm", None)


def test_client_cli(test_server):
    server, port, mock_cache, mock_node = test_server
    
    # Reset stats
    with P2PProxyHandler.stats_lock:
        P2PProxyHandler.cache_hits = 5
        P2PProxyHandler.cache_misses = 5
        P2PProxyHandler.bandwidth_saved = 1000

    import subprocess
    import sys
    
    client_path = Path(__file__).parent.parent / "p2p-proxy-server" / "dnf-p2p-client"
    
    # Run: python3 dnf-p2p-client --host 127.0.0.1 --port <port> status
    result = subprocess.run(
        [sys.executable, str(client_path), "--host", "127.0.0.1", "--port", str(port), "status"],
        capture_output=True,
        text=True,
        check=True
    )
    
    assert "Cache Hits:            5" in result.stdout
    assert "Cache Misses:          5" in result.stdout
    assert "Cache Hit Ratio:       50.00%" in result.stdout
    assert "Bandwidth Saved:       1000 B" in result.stdout


def test_http_handler_metadata_stream_identity(test_server):
    server, port, mock_cache, mock_node = test_server
    P2PProxyHandler.force_https = False
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Length": "18", "Content-Type": "application/xml"}
    mock_response.iter_content.return_value = [b"<xml>content</xml>"]
    
    with patch("requests.get", return_value=mock_response) as mock_get:
        # Request metadata file (ends with .xml, so it is streamed and bypassed from cache/P2P)
        url = f"http://127.0.0.1:{port}/repodata/repomd.xml?remote_url=http://mirror.foo.com/repodata/repomd.xml"
        response = urllib.request.urlopen(url, timeout=1)
        assert response.getcode() == 200
        assert response.read() == b"<xml>content</xml>"
        
        # Verify requests.get was called with the Accept-Encoding: identity header
        mock_get.assert_called_once_with(
            "http://mirror.foo.com/repodata/repomd.xml",
            stream=True,
            timeout=15,
            headers={"Accept-Encoding": "identity"}
        )


def test_http_handler_metadata_head_identity(test_server):
    server, port, mock_cache, mock_node = test_server
    P2PProxyHandler.force_https = False
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Length": "18", "Content-Type": "application/xml"}
    
    with patch("requests.head", return_value=mock_response) as mock_head:
        # Send HEAD request for metadata file
        url = f"http://127.0.0.1:{port}/repodata/repomd.xml?remote_url=http://mirror.foo.com/repodata/repomd.xml"
        req = urllib.request.Request(url, method="HEAD")
        response = urllib.request.urlopen(req, timeout=1)
        assert response.getcode() == 200
        
        # Verify requests.head was called with the Accept-Encoding: identity header
        mock_head.assert_called_once_with(
            "http://mirror.foo.com/repodata/repomd.xml",
            timeout=5,
            headers={"Accept-Encoding": "identity"}
        )


def test_client_status_cmd(test_server):
    import importlib.util
    from importlib.machinery import SourceFileLoader
    client_path = Path(__file__).parent.parent / "p2p-proxy-server" / "dnf-p2p-client"
    loader = SourceFileLoader("dnf_p2p_client", str(client_path))
    spec = importlib.util.spec_from_loader("dnf_p2p_client", loader)
    client_module = importlib.util.module_from_spec(spec)
    loader.exec_module(client_module)

    server, port, mock_cache, mock_node = test_server
    mock_node.num_discovered_peers = 3
    mock_node.num_active_peers = 2
    mock_cache.index = {
        "hash1": {"filename": "pkg1.rpm", "size": 100}
    }

    # Mock command line arguments
    args = MagicMock()
    args.config = None
    args.host = "127.0.0.1"
    args.port = port

    with patch("sys.stdout") as mock_stdout:
        rc = client_module.cmd_status(args)
        assert rc == 0


def test_client_test_transfer_cmd(test_server):
    import importlib.util
    from importlib.machinery import SourceFileLoader
    client_path = Path(__file__).parent.parent / "p2p-proxy-server" / "dnf-p2p-client"
    loader = SourceFileLoader("dnf_p2p_client", str(client_path))
    spec = importlib.util.spec_from_loader("dnf_p2p_client", loader)
    client_module = importlib.util.module_from_spec(spec)
    loader.exec_module(client_module)

    server, port, mock_cache, mock_node = test_server

    # Set up cache file
    pkg_file = Path("/tmp/mock_cache_dir/test-package-cli.rpm")
    mock_cache.get_cached_file_by_name.return_value = pkg_file
    
    import hashlib
    expected_content = "dummy-package-content"
    expected_hash = hashlib.sha256(expected_content.encode()).hexdigest()
    mock_cache.get_file_hash.return_value = expected_hash

    args = MagicMock()
    args.config = None
    args.host = "127.0.0.1"
    args.port = port
    args.filename = "test-package-cli.rpm"
    args.hash = expected_hash
    args.expected_content = expected_content

    from unittest.mock import mock_open
    try:
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "stat") as mock_stat, \
             patch("builtins.open", mock_open(read_data=expected_content.encode())):
            
            mock_stat.return_value.st_size = len(expected_content)

            rc = client_module.cmd_test_transfer(args)
            assert rc == 0
            
            # Verify the hash was registered in expected_hashes dict
            assert P2PProxyHandler.expected_hashes.get("test-package-cli.rpm") == expected_hash
    finally:
        P2PProxyHandler.expected_hashes.pop("test-package-cli.rpm", None)


def test_http_handler_range_request(test_server):
    import io
    server, port, mock_cache, mock_node = test_server

    temp_file = Path("/tmp/mock_cache_dir/test-package.rpm")
    mock_cache.get_cached_file_by_name.return_value = temp_file

    file_bytes = b"0123456789abcdef"  # 16 bytes

    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "stat") as mock_stat, \
         patch("builtins.open", lambda *a, **kw: io.BytesIO(file_bytes)):

        mock_stat.return_value.st_size = 16

        # Test partial range: bytes=0-4
        url = f"http://127.0.0.1:{port}/packages/test-package.rpm"
        req = urllib.request.Request(url, headers={"Range": "bytes=0-4"})
        with urllib.request.urlopen(req) as resp:
            assert resp.getcode() == 206
            assert resp.headers.get("Content-Range") == "bytes 0-4/16"
            assert resp.headers.get("Content-Length") == "5"
            assert resp.headers.get("Accept-Ranges") == "bytes"
            assert resp.read() == b"01234"

        # Test suffix range: bytes=-6 (last 6 bytes)
        req = urllib.request.Request(url, headers={"Range": "bytes=-6"})
        with urllib.request.urlopen(req) as resp:
            assert resp.getcode() == 206
            assert resp.headers.get("Content-Range") == "bytes 10-15/16"
            assert resp.headers.get("Content-Length") == "6"
            assert resp.read() == b"abcdef"

        # Test unsatisfiable range: bytes=50-100
        req = urllib.request.Request(url, headers={"Range": "bytes=50-100"})
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 416
        assert exc_info.value.headers.get("Content-Range") == "bytes */16"


def test_http_handler_head_accept_ranges(test_server):
    server, port, mock_cache, mock_node = test_server

    temp_file = Path("/tmp/mock_cache_dir/test-package.rpm")
    mock_cache.get_cached_file_by_name.return_value = temp_file

    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "stat") as mock_stat:

        mock_stat.return_value.st_size = 42

        url = f"http://127.0.0.1:{port}/packages/test-package.rpm"
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req) as resp:
            assert resp.getcode() == 200
            assert resp.headers.get("Content-Length") == "42"
            assert resp.headers.get("Accept-Ranges") == "bytes"


def test_http_handler_peer_ssrf_filtering(test_server):
    server, port, mock_cache, mock_node = test_server
    mock_cache.get_cached_file_by_name.return_value = None

    # Peers with loopback, link-local metadata IP, and privileged port
    mock_node.query_peers_for_package.return_value = [
        {"ip": "127.0.0.1", "port": 8888, "hash": "dummy"},
        {"ip": "169.254.169.254", "port": 8888, "hash": "dummy"},
        {"ip": "192.168.1.50", "port": 22, "hash": "dummy"},
        {"ip": "224.0.0.1", "port": 8888, "hash": "dummy"},
    ]

    with patch.object(Path, "exists", return_value=False), \
         patch("requests.get") as mock_get:

        url = f"http://127.0.0.1:{port}/packages/malicious-check.rpm"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(url, timeout=1)
        # Should return 404 since no valid peers were contacted and no remote_url was provided
        assert exc_info.value.code == 404
        # Assert requests.get was NEVER called for any of the unsafe peer IPs/ports
        assert mock_get.call_count == 0


def test_http_handler_corrupt_peer_payload_fallback(test_server):
    import requests
    server, port, mock_cache, mock_node = test_server
    mock_cache.get_cached_file_by_name.return_value = None

    import hashlib
    good_content = b"good_valid_rpm_bytes"
    corrupt_content = b"corrupt_invalid_bytes"
    expected_hash = hashlib.sha256(good_content).hexdigest()

    mock_node.query_peers_for_package.return_value = [
        {"ip": "192.168.1.100", "port": 8888, "hash": expected_hash, "size": len(corrupt_content)}
    ]

    peer_response = MagicMock()
    peer_response.status_code = 200
    peer_response.headers = {"Content-Length": str(len(corrupt_content))}
    peer_response.iter_content.return_value = [corrupt_content]

    mirror_response = MagicMock()
    mirror_response.status_code = 200
    mirror_response.headers = {"Content-Length": str(len(good_content))}
    mirror_response.iter_content.return_value = [good_content]

    P2PProxyHandler.expected_hashes["test-corrupt.rpm"] = expected_hash
    P2PProxyHandler.force_https = False

    def fake_get(url, **kwargs):
        if "192.168.1.100" in url:
            return peer_response
        return mirror_response

    from unittest.mock import mock_open
    try:
        with patch.object(Path, "exists", return_value=False), \
             patch.object(Path, "rename"), \
             patch("requests.get", side_effect=fake_get) as mock_get, \
             patch("builtins.open", mock_open()):

            url = f"http://127.0.0.1:{port}/packages/test-corrupt.rpm?remote_url=http://mirror.example.com/packages/test-corrupt.rpm"
            response = urllib.request.urlopen(url, timeout=1)
            assert response.getcode() == 200
            assert response.read() == good_content
            # Verify peer was attempted first, then fallback to mirror
            assert mock_get.call_count == 2
    finally:
        P2PProxyHandler.expected_hashes.pop("test-corrupt.rpm", None)


def test_http_handler_peer_disconnect_fallback(test_server):
    import requests
    server, port, mock_cache, mock_node = test_server
    mock_cache.get_cached_file_by_name.return_value = None

    import hashlib
    good_content = b"clean_upstream_rpm"
    expected_hash = hashlib.sha256(good_content).hexdigest()

    mock_node.query_peers_for_package.return_value = [
        {"ip": "192.168.1.100", "port": 8888, "hash": expected_hash, "size": 100}
    ]

    mirror_response = MagicMock()
    mirror_response.status_code = 200
    mirror_response.headers = {"Content-Length": str(len(good_content))}
    mirror_response.iter_content.return_value = [good_content]

    P2PProxyHandler.expected_hashes["test-disconnect.rpm"] = expected_hash
    P2PProxyHandler.force_https = False

    def fake_get(url, **kwargs):
        if "192.168.1.100" in url:
            raise requests.exceptions.ConnectionError("Peer dropped connection")
        return mirror_response

    from unittest.mock import mock_open
    try:
        with patch.object(Path, "exists", return_value=False), \
             patch.object(Path, "rename"), \
             patch("requests.get", side_effect=fake_get) as mock_get, \
             patch("builtins.open", mock_open()):

            url = f"http://127.0.0.1:{port}/packages/test-disconnect.rpm?remote_url=http://mirror.example.com/packages/test-disconnect.rpm"
            response = urllib.request.urlopen(url, timeout=1)
            assert response.getcode() == 200
            assert response.read() == good_content
            assert mock_get.call_count == 2
    finally:
        P2PProxyHandler.expected_hashes.pop("test-disconnect.rpm", None)


def test_http_handler_swarm_download(test_server):
    import requests
    server, port, mock_cache, mock_node = test_server
    mock_cache.get_cached_file_by_name.return_value = None

    import hashlib
    chunk1 = b"SWARM_CHUNK_1_DATA_"
    chunk2 = b"SWARM_CHUNK_2_DATA_"
    full_content = chunk1 + chunk2
    full_hash = hashlib.sha256(full_content).hexdigest()

    # 2 peers have the package
    mock_node.query_peers_for_package.return_value = [
        {"ip": "192.168.1.101", "port": 8888, "hash": full_hash, "size": len(full_content), "rtt_ms": 1.2},
        {"ip": "192.168.1.102", "port": 8888, "hash": full_hash, "size": len(full_content), "rtt_ms": 1.8},
    ]

    def fake_get(url, headers=None, **kwargs):
        resp = MagicMock()
        resp.status_code = 206
        if "192.168.1.101" in url:
            resp.content = chunk1
        else:
            resp.content = chunk2
        return resp

    orig_threshold = P2PProxyHandler.swarm_threshold
    P2PProxyHandler.swarm_threshold = 10
    P2PProxyHandler.expected_hashes["swarm-pkg.rpm"] = full_hash

    from unittest.mock import mock_open
    try:
        with patch.object(Path, "exists", return_value=False), \
             patch.object(Path, "rename"), \
             patch("requests.get", side_effect=fake_get) as mock_get, \
             patch("builtins.open", mock_open()):

            url = f"http://127.0.0.1:{port}/packages/swarm-pkg.rpm"
            response = urllib.request.urlopen(url, timeout=1)
            assert response.getcode() == 200
            assert response.read() == full_content
            # Verify both peers were contacted in parallel
            assert mock_get.call_count == 2
    finally:
        P2PProxyHandler.swarm_threshold = orig_threshold
        P2PProxyHandler.expected_hashes.pop("swarm-pkg.rpm", None)


def test_cluster_token_http_enforcement(test_server):
    server, port, mock_cache, mock_node = test_server
    token = "secret-psk-token-999"
    P2PProxyHandler.cluster_token = token

    try:
        url = f"http://127.0.0.1:{port}/packages/p2p-diagnostic.txt"

        # 1. Localhost client should be exempt even without token
        resp_local = urllib.request.urlopen(url, timeout=1)
        assert resp_local.getcode() == 200
        assert resp_local.read() == b"OK"

        # 2. Remote client without token -> 401
        with patch.object(P2PProxyHandler, "_is_local_client", return_value=False):
            with pytest.raises(urllib.error.HTTPError) as exc_no_token:
                urllib.request.urlopen(url, timeout=1)
            assert exc_no_token.value.code == 401

            # 3. Remote client with wrong token -> 401
            req_bad = urllib.request.Request(url, headers={"X-Cluster-Token": "wrong-token"})
            with pytest.raises(urllib.error.HTTPError) as exc_bad_token:
                urllib.request.urlopen(req_bad, timeout=1)
            assert exc_bad_token.value.code == 401

            # 4. Remote client with valid token -> 200
            req_valid = urllib.request.Request(url, headers={"X-Cluster-Token": token})
            resp_valid = urllib.request.urlopen(req_valid, timeout=1)
            assert resp_valid.getcode() == 200
            assert resp_valid.read() == b"OK"

            # 5. Remote client HEAD with valid token -> 200
            req_head = urllib.request.Request(url, headers={"X-Cluster-Token": token}, method="HEAD")
            resp_head = urllib.request.urlopen(req_head, timeout=1)
            assert resp_head.getcode() == 200

            # 6. Remote client HEAD without token -> 401
            req_head_no_tok = urllib.request.Request(url, method="HEAD")
            with pytest.raises(urllib.error.HTTPError) as exc_head:
                urllib.request.urlopen(req_head_no_tok, timeout=1)
            assert exc_head.value.code == 401
    finally:
        P2PProxyHandler.cluster_token = None


def test_download_from_peer_sends_cluster_token(test_server):
    server, port, mock_cache, mock_node = test_server
    token = "outbound-psk-token"
    P2PProxyHandler.cluster_token = token
    mock_cache.get_cached_file_by_name.return_value = None

    import hashlib
    content = b"peer-test-content"
    pkg_hash = hashlib.sha256(content).hexdigest()

    mock_node.query_peers_for_package.return_value = [
        {"ip": "192.168.1.50", "port": 8888, "hash": pkg_hash, "size": len(content)}
    ]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Length": str(len(content))}
    mock_response.iter_content.return_value = [content]

    from unittest.mock import mock_open
    try:
        with patch.object(Path, "exists", return_value=False), \
             patch.object(Path, "rename"), \
             patch("requests.get", return_value=mock_response) as mock_get, \
             patch("builtins.open", mock_open()):

            P2PProxyHandler.expected_hashes["test-pkg.rpm"] = pkg_hash
            url = f"http://127.0.0.1:{port}/packages/test-pkg.rpm"
            resp = urllib.request.urlopen(url, timeout=1)
            assert resp.getcode() == 200
            assert resp.read() == content

            # Verify requests.get had X-Cluster-Token header
            mock_get.assert_called_with(
                "http://192.168.1.50:8888/packages/test-pkg.rpm",
                stream=True,
                timeout=15,
                allow_redirects=False,
                headers={"X-Cluster-Token": token}
            )
    finally:
        P2PProxyHandler.cluster_token = None
        P2PProxyHandler.expected_hashes.pop("test-pkg.rpm", None)







