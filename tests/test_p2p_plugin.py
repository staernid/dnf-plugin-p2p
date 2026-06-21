import sys
from unittest.mock import MagicMock, patch

# Clear any cached p2p_plugin imports to force a reload with the new mocks
if "p2p_plugin" in sys.modules:
    del sys.modules["p2p_plugin"]

# Mock libdnf5 modules before importing the plugin
class MockIPlugin:
    def __init__(self, data):
        pass
    def get_base(self):
        return MagicMock()

libdnf5_mock = MagicMock()
libdnf5_plugin_mock = MagicMock()
libdnf5_plugin_mock.IPlugin = MockIPlugin
libdnf5_base_mock = MagicMock()
libdnf5_rpm_mock = MagicMock()
libdnf5_conf_mock = MagicMock()

# Set up submodule attributes on parent mock for dotted import resolution
libdnf5_mock.plugin = libdnf5_plugin_mock
libdnf5_mock.base = libdnf5_base_mock
libdnf5_mock.rpm = libdnf5_rpm_mock
libdnf5_mock.conf = libdnf5_conf_mock

sys.modules['libdnf5'] = libdnf5_mock
sys.modules['libdnf5.plugin'] = libdnf5_plugin_mock
sys.modules['libdnf5.base'] = libdnf5_base_mock
sys.modules['libdnf5.rpm'] = libdnf5_rpm_mock
sys.modules['libdnf5.conf'] = libdnf5_conf_mock

# Add plugins dir to sys.path
if "plugins" not in sys.path:
    sys.path.append("plugins")
from p2p_plugin import Plugin

def test_start_proxy_server_already_active():
    plugin_data = MagicMock()
    plugin = Plugin(plugin_data)
    plugin.proxy_host = "127.0.0.1"
    plugin.proxy_port = 8888

    with patch("socket.create_connection") as mock_connect, \
         patch("subprocess.run") as mock_run:
        # Make the context manager work
        mock_connect.return_value.__enter__.return_value = MagicMock()
        
        plugin._start_proxy_server()
        
        mock_connect.assert_called_once_with(("127.0.0.1", 8888), timeout=0.1)
        mock_run.assert_not_called()

def test_start_proxy_server_as_non_root():
    plugin_data = MagicMock()
    plugin = Plugin(plugin_data)
    plugin.proxy_host = "127.0.0.1"
    plugin.proxy_port = 8888

    # socket.create_connection raises ConnectionRefusedError
    # os.geteuid returns 1000 (non-root)
    with patch("socket.create_connection", side_effect=ConnectionRefusedError), \
         patch("os.geteuid", return_value=1000), \
         patch("subprocess.run") as mock_run:
        plugin._start_proxy_server()
        mock_run.assert_not_called()

def test_start_proxy_server_as_root():
    plugin_data = MagicMock()
    plugin = Plugin(plugin_data)
    plugin.proxy_host = "127.0.0.1"
    plugin.proxy_port = 8888

    # socket.create_connection raises ConnectionRefusedError
    # os.geteuid returns 0 (root)
    with patch("socket.create_connection", side_effect=ConnectionRefusedError), \
         patch("os.geteuid", return_value=0), \
         patch("subprocess.run") as mock_run:
        
        mock_run.return_value.returncode = 0
        plugin._start_proxy_server()
        mock_run.assert_called_once_with(
            ["systemctl", "start", "dnf-p2p-proxy.service"],
            capture_output=True, text=True, timeout=10
        )
