import logging
import secrets
import threading
import trio
import multiaddr
from typing import Dict, List, Optional, Callable

# Fallback stub for miniupnpc, which is an optional dependency of py-libp2p
# but is unconditionally imported by it at startup. Since UPnP is disabled
# by default, a dummy mock prevents startup crashes when python3-miniupnpc is not installed.
try:
    import miniupnpc
except ImportError:
    import sys
    from unittest.mock import MagicMock
    sys.modules['miniupnpc'] = MagicMock()

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.request_response import JSONCodec, RequestResponse
from libp2p.discovery.events.peerDiscovery import peerDiscovery
from libp2p.utils.address_validation import find_free_port, get_available_interfaces
from libp2p.peer.peerinfo import PeerInfo

logger = logging.getLogger("p2p_libp2p")

PROTOCOL_ID = TProtocol("/dnf-p2p/query/1.0.0")

def extract_ip(addrs) -> Optional[str]:
    """Extract first non-loopback IPv4 or IPv6 address from a list of multiaddrs."""
    # First pass: look for non-loopback IPv4
    for addr in addrs:
        parts = str(addr).split('/')
        if len(parts) > 2 and parts[1] == 'ip4':
            ip = parts[2]
            if ip != '127.0.0.1':
                return ip
    # Second pass: look for non-loopback IPv6
    for addr in addrs:
        parts = str(addr).split('/')
        if len(parts) > 2 and parts[1] == 'ip6':
            ip = parts[2]
            if ip != '::1':
                return ip
    # Third pass: loopback IPv4
    for addr in addrs:
        parts = str(addr).split('/')
        if len(parts) > 2 and parts[1] == 'ip4':
            return parts[2]
    # Fourth pass: loopback IPv6
    for addr in addrs:
        parts = str(addr).split('/')
        if len(parts) > 2 and parts[1] == 'ip6':
            return parts[2]
    return None

class P2PLibp2pNode:
    """A thread-safe wrapper around py-libp2p for local peer discovery and querying."""

    def __init__(self, libp2p_port: int, local_http_port: int, cache_lookup_callback: Callable[[str], Optional[Dict]],
                 peer_discovery_timeout: float = 2.0, max_parallel_peers: int = 5):
        self.libp2p_port = libp2p_port
        self.local_http_port = local_http_port
        self.cache_lookup_callback = cache_lookup_callback
        self.peer_discovery_timeout = max(0.1, peer_discovery_timeout)
        self.max_parallel_peers = max(1, max_parallel_peers)
        self.discovered_peers: Dict[str, PeerInfo] = {}
        self.trio_token = None
        self.host = None
        self.rr = None
        self.codec = None
        self._started_event = threading.Event()

    @property
    def num_discovered_peers(self) -> int:
        """Return the number of discovered peers."""
        return len(self.discovered_peers)

    @property
    def num_active_peers(self) -> int:
        """Return the number of active peer connections."""
        if self.host:
            try:
                return len(self.host.get_connected_peers())
            except Exception:
                pass
        return 0

    def start(self):
        """Start the libp2p node in a background thread running Trio."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        # Wait for the node to initialize
        if not self._started_event.wait(timeout=15):
            logger.error("Timed out waiting for libp2p node to start")
            raise RuntimeError("Failed to start libp2p node")

    def _run_loop(self):
        try:
            trio.run(self._async_run)
        except Exception as e:
            logger.error(f"Error in libp2p trio run loop: {e}", exc_info=True)

    async def _async_run(self):
        self.trio_token = trio.lowlevel.current_trio_token()
        
        port = self.libp2p_port
        if port <= 0:
            port = find_free_port()
        listen_addrs = get_available_interfaces(port)
        # Ensure we explicitly listen on the IPv6 wildcard address
        try:
            ipv6_wildcard = multiaddr.Multiaddr(f"/ip6/::/tcp/{port}")
            if ipv6_wildcard not in listen_addrs:
                listen_addrs.append(ipv6_wildcard)
                logger.info(f"Added IPv6 wildcard listener: /ip6/::/tcp/{port}")
        except Exception as e:
            logger.warning(f"Failed to add IPv6 wildcard listener: {e}")

        # Generate a stable-enough keypair for this session
        secret = secrets.token_bytes(32)
        key_pair = create_new_key_pair(secret)

        # Register the peer discovery event handler
        def on_peer_discovery(peerinfo: PeerInfo):
            peer_id_str = peerinfo.peer_id.to_string()
            if peer_id_str != self.host.get_id().to_string():
                logger.info(f"Discovered peer: {peer_id_str} at {peerinfo.addrs}")
                self.discovered_peers[peer_id_str] = peerinfo

        peerDiscovery.register_peer_discovered_handler(on_peer_discovery)

        self.host = new_host(key_pair=key_pair, enable_mDNS=True)
        self.rr = RequestResponse(self.host)
        self.codec = JSONCodec()

        async def query_handler(request: dict, context) -> dict:
            package_name = request.get("package", "")
            logger.debug(f"Received query request for package: {package_name} from {context.peer_id}")
            
            # Response must indicate if we have the package
            response = {
                "has_package": False,
                "http_port": self.local_http_port
            }
            if self.cache_lookup_callback:
                p_info = self.cache_lookup_callback(package_name)
                if p_info:
                    response["has_package"] = True
                    response["hash"] = p_info.get("hash", "")
                    response["size"] = p_info.get("size", 0)
                    logger.info(f"We HAVE the package {package_name}. Responding positively.")
            return response

        self.rr.set_handler(PROTOCOL_ID, handler=query_handler, codec=self.codec)

        # Signal that the node is ready
        self._started_event.set()

        async with self.host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
            nursery.start_soon(self.host.get_peerstore().start_cleanup_task, 60)
            logger.info(f"libp2p node running with PeerID: {self.host.get_id().to_string()}")
            await trio.sleep_forever()

    def query_peers_for_package(self, package_name: str) -> List[Dict]:
        """Query all discovered peers for a package. Thread-safe."""
        if not self.trio_token:
            logger.warning("libp2p node not fully started, cannot query peers")
            return []

        async def do_query():
            results = []
            peer_ids = list(self.discovered_peers.keys())
            logger.debug(f"Querying {len(peer_ids)} discovered peers for {package_name}")
            limit = trio.CapacityLimiter(self.max_parallel_peers)

            async def query_peer(peer_id_str: str):
                async with limit:
                    peerinfo = self.discovered_peers.get(peer_id_str)
                    if not peerinfo:
                        return
                    try:
                        logger.debug(f"Connecting to peer {peer_id_str}...")
                        await self.host.connect(peerinfo)

                        logger.debug(f"Sending query request to {peer_id_str}...")
                        response = await self.rr.send_request(
                            peer_id=peerinfo.peer_id,
                            protocol_ids=[PROTOCOL_ID],
                            request={"package": package_name},
                            codec=self.codec
                        )

                        if response and response.get("has_package"):
                            ip = extract_ip(peerinfo.addrs)
                            if ip:
                                results.append({
                                    "ip": ip,
                                    "port": response.get("http_port"),
                                    "hash": response.get("hash"),
                                    "size": response.get("size")
                                })
                                logger.info(f"Peer {peer_id_str} at {ip}:{response.get('http_port')} has package {package_name}")
                    except Exception as e:
                        logger.warning(f"Failed to query peer {peer_id_str}: {e}")
                        # Remove unresponsive peer
                        self.discovered_peers.pop(peer_id_str, None)

            with trio.move_on_after(self.peer_discovery_timeout):
                async with trio.open_nursery() as nursery:
                    for peer_id_str in peer_ids:
                        nursery.start_soon(query_peer, peer_id_str)
            return results

        try:
            return trio.from_thread.run(do_query, trio_token=self.trio_token)
        except Exception as e:
            logger.error(f"Error querying peers from thread: {e}")
            return []
