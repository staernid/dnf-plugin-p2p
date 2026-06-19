import threading
import urllib.request
import urllib.parse
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
    
    # Package does not exist locally
    mock_node.query_peers_for_package.return_value = [
        {"ip": "192.168.1.100", "port": 8888, "hash": "somehash", "size": 100}
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
        
        # Trigger download from peer
        url = f"http://127.0.0.1:{port}/packages/test-package.rpm"
        response = urllib.request.urlopen(url, timeout=1)
        assert response.getcode() == 200
        assert response.read() == b"chunk1chunk2"
            
        # Assert that it queried the libp2p node and tried to download from the peer
        mock_node.query_peers_for_package.assert_called_with("test-package.rpm")
        mock_get.assert_any_call("http://192.168.1.100:8888/packages/test-package.rpm", stream=True, timeout=15)


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
             "cache_dir": "/mock/cache"
         }[opt]), \
         patch("configparser.ConfigParser.getint", side_effect=lambda sec, opt: {
             "proxy_port": 9999,
             "max_parallel_peers": 12,
             "max_cache_size_mb": 512,
             "libp2p_port": 7777
         }[opt]), \
         patch("configparser.ConfigParser.getfloat", side_effect=lambda sec, opt: {
             "peer_discovery_timeout": 4.5,
             "max_disk_usage_percent": 80.0
         }[opt]), \
         patch("configparser.ConfigParser.getboolean", side_effect=lambda sec, opt: {
             "debug": True,
             "force_https": False
         }[opt]), \
         patch("p2p_server.P2PLibp2pNode", return_value=mock_node_instance) as mock_node_cls, \
         patch("p2p_server.P2PCache") as mock_cache_cls, \
         patch("p2p_server.ThreadingHTTPServer", return_value=mock_server_instance) as mock_server_cls:

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
            max_parallel_peers=12
        )

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


def test_http_handler_force_https_enabled(test_server):
    server, port, mock_cache, mock_node = test_server
    mock_cache.get_cached_file_by_name.return_value = None
    mock_node.query_peers_for_package.return_value = []
    
    P2PProxyHandler.force_https = True
    
    # Mock requests.get to return a successful response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Length": "6"}
    mock_response.iter_content.return_value = [b"chunk1"]
    
    from unittest.mock import mock_open
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


def test_http_handler_force_https_disabled(test_server):
    server, port, mock_cache, mock_node = test_server
    mock_cache.get_cached_file_by_name.return_value = None
    mock_node.query_peers_for_package.return_value = []
    
    P2PProxyHandler.force_https = False
    
    # Mock requests.get to return a successful response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Length": "6"}
    mock_response.iter_content.return_value = [b"chunk1"]
    
    from unittest.mock import mock_open
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


