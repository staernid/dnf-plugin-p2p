from unittest.mock import MagicMock
import pytest
from p2p_libp2p import P2PLibp2pNode, extract_ip

def test_extract_ip():
    addrs = [
        "/ip4/127.0.0.1/tcp/8000",
        "/ip4/192.168.1.15/tcp/8000",
    ]
    # Should prefer non-loopback IP
    assert extract_ip(addrs) == "192.168.1.15"

    addrs_loopback = [
        "/ip4/127.0.0.1/tcp/8000",
    ]
    # Should fallback to loopback
    assert extract_ip(addrs_loopback) == "127.0.0.1"

    # Should return None if no IPv4 address is present
    assert extract_ip([]) is None

def test_node_init():
    cache_cb = MagicMock(return_value=[])
    node = P2PLibp2pNode(libp2p_port=0, local_http_port=8888, cache_lookup_callback=cache_cb)
    assert node.libp2p_port == 0
    assert node.local_http_port == 8888
    assert node.cache_lookup_callback == cache_cb
    assert node.trio_token is None

