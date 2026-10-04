import threading
from unittest.mock import MagicMock
import pytest
from p2p_libp2p import P2PLibp2pNode, PeerRateLimiter, extract_ip

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

    # Test IPv6 address extraction
    addrs_ipv6 = [
        "/ip6/::1/tcp/8000",
        "/ip6/2001:db8::1/tcp/8000",
    ]
    # Should prefer non-loopback IPv6
    assert extract_ip(addrs_ipv6) == "2001:db8::1"

    addrs_ipv6_loopback = [
        "/ip6/::1/tcp/8000",
    ]
    assert extract_ip(addrs_ipv6_loopback) == "::1"

    # Should return None if no address is present
    assert extract_ip([]) is None

    # Should prioritize physical LAN over Tailscale CGNAT (100.64.0.0/10)
    addrs_tailscale = [
        "/ip4/100.127.150.94/tcp/8000",
        "/ip4/192.168.1.50/tcp/8000",
    ]
    assert extract_ip(addrs_tailscale) == "192.168.1.50"

    # If only Tailscale is present, should pick Tailscale over loopback or docker
    addrs_tailscale_only = [
        "/ip4/127.0.0.1/tcp/8000",
        "/ip4/172.17.0.1/tcp/8000",
        "/ip4/100.127.150.94/tcp/8000",
    ]
    assert extract_ip(addrs_tailscale_only) == "100.127.150.94"

def test_node_init():
    cache_cb = MagicMock(return_value=[])
    node = P2PLibp2pNode(libp2p_port=0, local_http_port=8888, cache_lookup_callback=cache_cb)
    assert node.libp2p_port == 0
    assert node.local_http_port == 8888
    assert node.cache_lookup_callback == cache_cb
    assert node.peer_discovery_timeout == 2.0
    assert node.max_parallel_peers == 5
    assert node.trio_token is None

    # Custom valid values
    node_custom = P2PLibp2pNode(
        libp2p_port=0,
        local_http_port=8888,
        cache_lookup_callback=cache_cb,
        peer_discovery_timeout=4.5,
        max_parallel_peers=10
    )
    assert node_custom.peer_discovery_timeout == 4.5
    assert node_custom.max_parallel_peers == 10

    # Under-limit/invalid values should be clamped
    node_clamped = P2PLibp2pNode(
        libp2p_port=0,
        local_http_port=8888,
        cache_lookup_callback=cache_cb,
        peer_discovery_timeout=0.0,
        max_parallel_peers=-5
    )
    assert node_clamped.peer_discovery_timeout == 0.1
    assert node_clamped.max_parallel_peers == 1



def test_query_peers_for_package_success_and_timeout():
    import trio
    import time
    from unittest.mock import AsyncMock

    trio_token_holder = {}
    ready_event = threading.Event()
    stop_event = trio.Event()

    async def trio_main():
        trio_token_holder['token'] = trio.lowlevel.current_trio_token()
        ready_event.set()
        await stop_event.wait()

    def run_trio():
        trio.run(trio_main)

    trio_thread = threading.Thread(target=run_trio, daemon=True)
    trio_thread.start()
    ready_event.wait()

    node = P2PLibp2pNode(libp2p_port=0, local_http_port=8888, cache_lookup_callback=None)
    node.trio_token = trio_token_holder['token']

    node.host = MagicMock()
    node.host.connect = AsyncMock()
    node.rr = MagicMock()
    node.rr.send_request = AsyncMock()
    node.codec = MagicMock()

    peer1 = MagicMock()
    peer1.peer_id.to_string.return_value = "peer1"
    peer1.addrs = ["/ip4/192.168.1.100/tcp/8000"]

    peer2 = MagicMock()
    peer2.peer_id.to_string.return_value = "peer2"
    peer2.addrs = ["/ip4/192.168.1.101/tcp/8000"]

    peer3 = MagicMock()
    peer3.peer_id.to_string.return_value = "peer3"
    peer3.addrs = ["/ip4/192.168.1.102/tcp/8000"]

    node.discovered_peers = {
        "peer1": peer1,
        "peer2": peer2,
        "peer3": peer3
    }

    async def send_req_mock(peer_id, protocol_ids, request, codec):
        if peer_id == peer1.peer_id:
            # Peer 1: responds quickly and has the package
            return {"has_package": True, "http_port": 8001, "hash": "hash1", "size": 100}
        elif peer_id == peer2.peer_id:
            # Peer 2: times out (takes 5 seconds, longer than 2.0s timeout)
            await trio.sleep(5.0)
            return {"has_package": True, "http_port": 8002, "hash": "hash2", "size": 200}
        elif peer_id == peer3.peer_id:
            # Peer 3: fails immediately with connection error
            raise ConnectionRefusedError("Connection refused")
        return None

    node.rr.send_request.side_effect = send_req_mock

    # Measure time to ensure the global timeout worked
    start_time = time.time()
    results = node.query_peers_for_package("test-package.rpm")
    duration = time.time() - start_time

    # Clean up Trio loop
    trio.from_thread.run_sync(stop_event.set, trio_token=node.trio_token)
    trio_thread.join()

    # We expect peer1 to succeed
    assert len(results) == 1
    assert results[0]["ip"] == "192.168.1.100"
    assert results[0]["port"] == 8001
    assert results[0]["hash"] == "hash1"
    assert results[0]["size"] == 100

    # Peer 3 should be removed from discovered_peers due to the ConnectionRefusedError
    assert "peer3" not in node.discovered_peers

    # The duration should be around 2.0 seconds (due to move_on_after(2.0)), definitely less than 5.0 seconds
    assert duration < 3.0


def test_diagnostic_check_success():
    import trio
    from unittest.mock import AsyncMock, patch

    node = P2PLibp2pNode(libp2p_port=0, local_http_port=8888, cache_lookup_callback=None)
    node.host = MagicMock()
    node.host.connect = AsyncMock()
    node.rr = MagicMock()
    node.codec = MagicMock()

    peerinfo = MagicMock()
    peerinfo.peer_id.to_string.return_value = "peer1"
    peerinfo.addrs = ["/ip4/192.168.1.100/tcp/8000"]
    node.discovered_peers["peer1"] = peerinfo
    node.tested_peers.add("peer1")

    # Mock libp2p query response
    node.rr.send_request = AsyncMock(return_value={"http_port": 8889})

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"OK"

    async def run_test():
        with patch("requests.get", return_value=mock_response) as mock_get:
            await node._run_diagnostic_check_async(peerinfo)
            mock_get.assert_called_once_with("http://192.168.1.100:8889/packages/p2p-diagnostic.txt", timeout=3, allow_redirects=False)

    trio.run(run_test)


def test_diagnostic_check_retry_and_failure():
    import trio
    from unittest.mock import AsyncMock, patch

    node = P2PLibp2pNode(libp2p_port=0, local_http_port=8888, cache_lookup_callback=None)
    node.host = MagicMock()
    node.host.connect = AsyncMock()
    node.rr = MagicMock()
    node.codec = MagicMock()

    peerinfo = MagicMock()
    peerinfo.peer_id.to_string.return_value = "peer1"
    peerinfo.addrs = ["/ip4/192.168.1.100/tcp/8000"]
    node.discovered_peers["peer1"] = peerinfo
    node.tested_peers.add("peer1")

    # Mock libp2p query response
    node.rr.send_request = AsyncMock(return_value={"http_port": 8889})

    # Test Case 1: First attempt fails, second succeeds
    fail_response = MagicMock()
    fail_response.raise_for_status.side_effect = Exception("HTTP error")
    
    success_response = MagicMock()
    success_response.status_code = 200
    success_response.content = b"OK"

    async def run_test_retry():
        # First call raises error, second returns success
        with patch("requests.get", side_effect=[fail_response, success_response]) as mock_get:
            await node._run_diagnostic_check_async(peerinfo)
            assert mock_get.call_count == 2
            # Peer should still be in discovered_peers
            assert "peer1" in node.discovered_peers

    trio.run(run_test_retry)

    # Test Case 2: All attempts fail (logs CRITICAL and removes peer)
    node.discovered_peers["peer1"] = peerinfo
    node.tested_peers.add("peer1")

    async def run_test_failure():
        with patch("requests.get", side_effect=Exception("Connection refused")) as mock_get, \
             patch.object(node, "remove_peer", wraps=node.remove_peer) as mock_remove:
            await node._run_diagnostic_check_async(peerinfo)
            assert mock_get.call_count == 3
            mock_remove.assert_called_once_with("peer1")
            assert "peer1" not in node.discovered_peers
            assert "peer1" not in node.tested_peers

    trio.run(run_test_failure)


def test_peer_rate_limiter_tokens_and_burst():
    limiter = PeerRateLimiter(rate=10.0, burst=5)
    # Burst allows 5 requests
    for i in range(5):
        assert limiter.allow("peer1") is True, f"Request {i+1} should be allowed"
    # 6th immediate request should be denied
    assert limiter.allow("peer1") is False

    # A different peer has its own bucket
    assert limiter.allow("peer2") is True


def test_peer_rate_limiter_recovery():
    current_time = 100.0

    def clock():
        return current_time

    limiter = PeerRateLimiter(rate=2.0, burst=2, time_func=clock)
    assert limiter.allow("peerA") is True
    assert limiter.allow("peerA") is True
    assert limiter.allow("peerA") is False

    # Advance time by 0.5s: 2.0 * 0.5 = 1 token added
    current_time += 0.5
    assert limiter.allow("peerA") is True
    assert limiter.allow("peerA") is False

    # Advance time by 2.0s: max burst (2) tokens added
    current_time += 2.0
    assert limiter.allow("peerA") is True
    assert limiter.allow("peerA") is True
    assert limiter.allow("peerA") is False

    # Test reset
    limiter.reset("peerA")
    assert limiter.allow("peerA") is True


def test_query_handler_rate_limiting():
    import trio

    node = P2PLibp2pNode(
        libp2p_port=0,
        local_http_port=8888,
        cache_lookup_callback=lambda pkg: {"hash": "h", "size": 10},
        query_rate_limit=1.0,
        query_rate_burst=2
    )
    context = MagicMock()
    context.peer_id.to_string.return_value = "peer_flood"

    async def run_test():
        res1 = await node.query_handler({"package": "pkg.rpm"}, context)
        assert res1.get("has_package") is True
        assert res1.get("rate_limited") is None

        res2 = await node.query_handler({"package": "pkg.rpm"}, context)
        assert res2.get("has_package") is True
        assert res2.get("rate_limited") is None

        # Exceeding burst limit triggers rate limiting
        res3 = await node.query_handler({"package": "pkg.rpm"}, context)
        assert res3.get("has_package") is False
        assert res3.get("rate_limited") is True

    trio.run(run_test)


def test_query_handler_cluster_token():
    import trio

    token = "secret-cluster-psk-12345"
    node = P2PLibp2pNode(
        libp2p_port=0,
        local_http_port=8888,
        cache_lookup_callback=lambda pkg: {"hash": "abc", "size": 50},
        cluster_token=token
    )
    context = MagicMock()
    context.peer_id.to_string.return_value = "peer_client"

    async def run_test():
        # Missing token
        res_no_token = await node.query_handler({"package": "pkg.rpm"}, context)
        assert res_no_token == {"has_package": False, "unauthorized": True}

        # Invalid token
        res_bad_token = await node.query_handler({"package": "pkg.rpm", "cluster_token": "wrong"}, context)
        assert res_bad_token == {"has_package": False, "unauthorized": True}

        # Valid token
        res_ok = await node.query_handler({"package": "pkg.rpm", "cluster_token": token}, context)
        assert res_ok.get("has_package") is True
        assert res_ok.get("hash") == "abc"
        assert res_ok.get("unauthorized") is None

    trio.run(run_test)


def test_query_peers_and_diagnostic_sends_cluster_token():
    import trio
    from unittest.mock import AsyncMock, patch

    token = "test-cluster-token"
    node = P2PLibp2pNode(
        libp2p_port=0,
        local_http_port=8888,
        cache_lookup_callback=None,
        cluster_token=token
    )
    node.host = MagicMock()
    node.host.connect = AsyncMock()
    node.rr = MagicMock()
    node.rr.send_request = AsyncMock(return_value={"http_port": 8889, "has_package": True})
    node.codec = MagicMock()

    peerinfo = MagicMock()
    peerinfo.peer_id.to_string.return_value = "peer1"
    peerinfo.addrs = ["/ip4/192.168.1.100/tcp/8000"]
    node.discovered_peers["peer1"] = peerinfo

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"OK"

    async def run_test():
        with patch("requests.get", return_value=mock_response) as mock_get:
            await node._run_diagnostic_check_async(peerinfo)
            # Check libp2p ping request had cluster_token
            node.rr.send_request.assert_called_with(
                peer_id=peerinfo.peer_id,
                protocol_ids=[node.rr.send_request.call_args[1]["protocol_ids"][0]],
                request={"package": "__p2p_diagnostic_ping__", "cluster_token": token},
                codec=node.codec
            )
            # Check HTTP GET had X-Cluster-Token header
            mock_get.assert_called_once_with(
                "http://192.168.1.100:8889/packages/p2p-diagnostic.txt",
                timeout=3,
                allow_redirects=False,
                headers={"X-Cluster-Token": token}
            )

    trio.run(run_test)


def test_node_uses_wildcard_listener():
    from unittest.mock import patch, MagicMock
    import trio

    node = P2PLibp2pNode(libp2p_port=8000, local_http_port=8888, cache_lookup_callback=None)

    mock_host = MagicMock()
    captured_addrs = []

    class MockRunContext:
        def __init__(self, listen_addrs):
            captured_addrs.extend(listen_addrs)

        async def __aenter__(self):
            return mock_host

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_host.run.side_effect = lambda listen_addrs: MockRunContext(listen_addrs)
    mock_host.get_id().to_string.return_value = "local_peer"
    mock_host.get_peerstore().peer_ids.return_value = []
    from unittest.mock import AsyncMock
    mock_host.get_peerstore().start_cleanup_task = AsyncMock()

    async def run_test():
        async def cancel_after():
            await trio.sleep(0.05)
            nursery.cancel_scope.cancel()

        with patch("p2p_libp2p.new_host", return_value=mock_host), \
             patch("p2p_libp2p.peerDiscovery"):
            async with trio.open_nursery() as nursery:
                nursery.start_soon(cancel_after)
                await node._async_run()

    trio.run(run_test)

    assert len(captured_addrs) == 1
    addr_str = str(captured_addrs[0])
    assert "0.0.0.0" in addr_str
    assert "8000" in addr_str


