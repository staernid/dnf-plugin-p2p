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
libdnf5_transaction_mock = MagicMock()

# Set up submodule attributes on parent mock for dotted import resolution
libdnf5_mock.plugin = libdnf5_plugin_mock
libdnf5_mock.base = libdnf5_base_mock
libdnf5_mock.rpm = libdnf5_rpm_mock
libdnf5_mock.conf = libdnf5_conf_mock
libdnf5_mock.transaction = libdnf5_transaction_mock

sys.modules['libdnf5'] = libdnf5_mock
sys.modules['libdnf5.plugin'] = libdnf5_plugin_mock
sys.modules['libdnf5.base'] = libdnf5_base_mock
sys.modules['libdnf5.rpm'] = libdnf5_rpm_mock
sys.modules['libdnf5.conf'] = libdnf5_conf_mock
sys.modules['libdnf5.transaction'] = libdnf5_transaction_mock

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

def test_pre_transaction_reinstall_upgrade():
    import json
    plugin_data = MagicMock()
    plugin = Plugin(plugin_data)
    plugin.enabled = True
    plugin.proxy_host = "127.0.0.1"
    plugin.proxy_port = 8888

    # Mock transaction packages
    # 1. Reinstall package (inbound=True) with repo_id="@System" but having a location and checksum
    tp_reinstall = MagicMock()
    tp_reinstall.get_action.return_value = "REINSTALL"
    pkg_reinstall = MagicMock()
    pkg_reinstall.get_repo_id.return_value = "@System"
    pkg_reinstall.get_location.return_value = "Packages/p/polybar-3.7.1-1.fc40.x86_64.rpm"
    checksum_reinstall = MagicMock()
    checksum_reinstall.get_type_str.return_value = "sha256"
    checksum_reinstall.get_checksum.return_value = "reinstall_hash_123"
    pkg_reinstall.get_checksum.return_value = checksum_reinstall
    tp_reinstall.get_package.return_value = pkg_reinstall

    # 2. Upgrade package (inbound=True) with repo_id="updates" having location and checksum
    tp_upgrade = MagicMock()
    tp_upgrade.get_action.return_value = "UPGRADE"
    pkg_upgrade = MagicMock()
    pkg_upgrade.get_repo_id.return_value = "updates"
    pkg_upgrade.get_location.return_value = "Packages/w/wget-1.21.4-2.fc40.x86_64.rpm"
    checksum_upgrade = MagicMock()
    checksum_upgrade.get_type_str.return_value = "sha256"
    checksum_upgrade.get_checksum.return_value = "upgrade_hash_456"
    pkg_upgrade.get_checksum.return_value = checksum_upgrade
    tp_upgrade.get_package.return_value = pkg_upgrade

    # 3. Outbound package (inbound=False)
    tp_outbound = MagicMock()
    tp_outbound.get_action.return_value = "REPLACED"
    tp_outbound.get_package.return_value = MagicMock()

    transaction = MagicMock()
    transaction.get_transaction_packages.return_value = [tp_reinstall, tp_upgrade, tp_outbound]

    # Mock libdnf5.transaction.transaction_item_action_is_inbound
    import libdnf5.transaction
    def mock_is_inbound(action):
        return action in ("REINSTALL", "UPGRADE")
    libdnf5.transaction.transaction_item_action_is_inbound.side_effect = mock_is_inbound

    # Mock urllib.request.urlopen
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response

        plugin.pre_transaction(transaction)

        # Verify urllib.request.urlopen was called with the correct Request
        mock_urlopen.assert_called_once()
        req_arg = mock_urlopen.call_args[0][0]
        assert req_arg.full_url == "http://127.0.0.1:8888/expected_hashes"
        assert req_arg.get_header("Content-type") == "application/json"
        
        # Load data sent to proxy
        sent_data = json.loads(req_arg.data.decode("utf-8"))
        assert sent_data == {
            "polybar-3.7.1-1.fc40.x86_64.rpm": "reinstall_hash_123",
            "wget-1.21.4-2.fc40.x86_64.rpm": "upgrade_hash_456"
        }

