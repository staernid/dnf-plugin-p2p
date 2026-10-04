import ipaddress
import logging
import secrets
import threading
import time
import trio
import multiaddr
from typing import Dict, List, Optional, Callable, Set, Any, Tuple

# Fallback stub for miniupnpc, which is an optional dependency of py-libp2p
# but is unconditionally imported by it at startup. Since UPnP is disabled
# by default, a dummy mock prevents startup crashes when python3-miniupnpc is not installed.
try:
    import miniupnpc
except ImportError:
    import sys
    class DummyMiniUPnP:
        def __getattr__(self, name):
            return lambda *args, **kwargs: DummyMiniUPnP()
        def __call__(self, *args, **kwargs):
            return self
    sys.modules['miniupnpc'] = DummyMiniUPnP()  # type: ignore[assignment]

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.request_response import JSONCodec, RequestResponse
from libp2p.discovery.events.peerDiscovery import peerDiscovery
from libp2p.utils.address_validation import find_free_port, get_wildcard_address
from libp2p.peer.peerinfo import PeerInfo

logger = logging.getLogger("p2p_libp2p")

PROTOCOL_ID = TProtocol("/dnf-p2p/query/1.0.0")

def extract_ip(addrs) -> Optional[str]:
    """Extract the best IP address from a list of multiaddrs,
    prioritizing physical LAN interfaces over virtual/docker bridges and VPN overlays.
    """
    local_subnets = []
    try:
        import socket, struct
        with open('/proc/net/route') as f:
            for line in f.readlines()[1:]:
                fields = line.strip().split()
                if len(fields) >= 8:
                    iface, dest, mask = fields[0], fields[1], fields[7]
                    if iface.startswith(('lo', 'docker', 'br-', 'virbr', 'tailscale', 'veth')):
                        continue
                    dest_ip = int(dest, 16)
                    mask_ip = int(mask, 16)
                    if mask_ip > 0:
                        dest_str = socket.inet_ntoa(struct.pack('<I', dest_ip))
                        mask_str = socket.inet_ntoa(struct.pack('<I', mask_ip))
                        net = ipaddress.IPv4Network(f'{dest_str}/{mask_str}', strict=False)
                        local_subnets.append(net)
    except Exception:
        pass

    def ip_score(ip: str) -> int:
        if ip in ('127.0.0.1', '::1', '0.0.0.0', '::'):
            return 0
        
        # Check if IPv6
        if ':' in ip:
            if ip.lower().startswith('fe80:'):
                return 5
            return 50
            
        parts = ip.split('.')
        if len(parts) == 4:
            try:
                p0, p1 = int(parts[0]), int(parts[1])
                # Docker bridge range: 172.16.0.0 - 172.31.255.255
                if p0 == 172 and (16 <= p1 <= 31):
                    return 10
                # Podman CNI range: 10.88.0.0/16
                if p0 == 10 and p1 == 88:
                    return 10
                # libvirt bridge range: 192.168.122.0/24
                p2 = int(parts[2])
                if p0 == 192 and p1 == 168 and p2 == 122:
                    return 10
                # Tailscale / CGNAT range: 100.64.0.0 - 100.127.255.255
                if p0 == 100 and (64 <= p1 <= 127):
                    return 20

                # Check if IP belongs to an active local physical subnet
                addr_obj = ipaddress.IPv4Address(ip)
                for net in local_subnets:
                    if addr_obj in net:
                        return 300
            except ValueError:
                pass
        return 200

    best_ip = None
    best_score = -1

    for addr in addrs:
        parts = str(addr).split('/')
        if len(parts) > 2 and parts[1] in ('ip4', 'ip6'):
            ip = parts[2]
            score = ip_score(ip)
            if score > best_score:
                best_score = score
                best_ip = ip

    return best_ip
 
 
class PeerRateLimiter:
    """Thread-safe token-bucket rate limiter per peer ID."""

    def __init__(self, rate: float = 20.0, burst: int = 30, time_func: Optional[Callable[[], float]] = None):
        self.rate = float(rate)
        self.burst = float(burst)
        self.time_func = time_func or time.monotonic
        self._buckets: Dict[str, Tuple[float, float]] = {}  # peer_id -> (tokens, last_time)
        self._lock = threading.Lock()

    def allow(self, peer_id: str) -> bool:
        """Check if request from peer_id is allowed under rate limits."""
        with self._lock:
            now = self.time_func()
            if peer_id not in self._buckets:
                tokens = self.burst
                last_time = now
            else:
                tokens, last_time = self._buckets[peer_id]
                elapsed = max(0.0, now - last_time)
                tokens = min(self.burst, tokens + elapsed * self.rate)
                last_time = now

            if tokens >= 1.0:
                self._buckets[peer_id] = (tokens - 1.0, last_time)
                if len(self._buckets) > 5000:
                    self._cleanup(now)
                return True
            else:
                self._buckets[peer_id] = (tokens, last_time)
                return False

    def _cleanup(self, now: float):
        """Prune inactive buckets older than 300 seconds."""
        cutoff = now - 300.0
        stale = [pid for pid, (_, t) in self._buckets.items() if t < cutoff]
        for pid in stale:
            del self._buckets[pid]

    def reset(self, peer_id: Optional[str] = None):
        """Reset rate limiter state for a specific peer or all peers."""
        with self._lock:
            if peer_id is not None:
                self._buckets.pop(peer_id, None)
            else:
                self._buckets.clear()


class P2PLibp2pNode:
    """A thread-safe wrapper around py-libp2p for local peer discovery and querying."""

    def __init__(self, libp2p_port: int, local_http_port: int, cache_lookup_callback: Callable[[str], Optional[Dict]],
                 peer_discovery_timeout: float = 2.0, max_parallel_peers: int = 5,
                 cluster_token: Optional[str] = None,
                 query_rate_limit: float = 20.0, query_rate_burst: int = 30):
        self.libp2p_port = libp2p_port
        self.local_http_port = local_http_port
        self.cache_lookup_callback = cache_lookup_callback
        self.peer_discovery_timeout = max(0.1, peer_discovery_timeout)
        self.max_parallel_peers = max(1, max_parallel_peers)
        self.cluster_token = cluster_token
        self.query_rate_limit = max(0.1, float(query_rate_limit))
        self.query_rate_burst = max(1, int(query_rate_burst))
        self.rate_limiter = PeerRateLimiter(rate=self.query_rate_limit, burst=self.query_rate_burst)
        self.discovered_peers: Dict[str, PeerInfo] = {}
        self.trio_token: Optional[trio.lowlevel.TrioToken] = None
        self.host: Any = None
        self.rr: Any = None
        self.codec: Any = None
        self._started_event = threading.Event()
        self.tested_peers: Set[str] = set()
        self.nursery: Optional[trio.Nursery] = None
        self._pending_peer_discoveries: List[PeerInfo] = []
        self._pending_lock = threading.Lock()

    def remove_peer(self, peer_id_str: str):
        """Remove a peer from discovered and tested sets to allow re-testing if rediscovered."""
        self.discovered_peers.pop(peer_id_str, None)
        self.tested_peers.discard(peer_id_str)

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
        listen_addrs = [get_wildcard_address(port)]

        # Generate a stable-enough keypair for this session
        secret = secrets.token_bytes(32)
        key_pair = create_new_key_pair(secret)

        # Register the peer discovery event handler
        def on_peer_discovery(peerinfo: PeerInfo):
            with self._pending_lock:
                if self.trio_token and self.nursery:
                    try:
                        trio.from_thread.run_sync(
                            self.nursery.start_soon,
                            self._on_peer_discovered_async,
                            peerinfo,
                            trio_token=self.trio_token
                        )
                    except Exception as e:
                        logger.error(f"Failed to schedule peer discovery event in Trio loop: {e}")
                else:
                    self._pending_peer_discoveries.append(peerinfo)

        peerDiscovery.register_peer_discovered_handler(on_peer_discovery)

        self.host = new_host(key_pair=key_pair, enable_mDNS=True)
        self.rr = RequestResponse(self.host)
        self.codec = JSONCodec()

        self.rr.set_handler(PROTOCOL_ID, handler=self.query_handler, codec=self.codec)

        async with self.host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
            self.nursery = nursery
            # Drain any peer discoveries queued before nursery was ready
            with self._pending_lock:
                pending = list(self._pending_peer_discoveries)
                self._pending_peer_discoveries.clear()
            for p_info in pending:
                nursery.start_soon(self._on_peer_discovered_async, p_info)

            # Signal that the node is ready
            self._started_event.set()

            async def sync_peerstore_peers():
                while True:
                    await trio.sleep(2)
                    try:
                        peer_ids = self.host.get_peerstore().peer_ids()
                        for pid in peer_ids:
                            pid_str = pid.to_string()
                            if pid_str != self.host.get_id().to_string() and pid_str not in self.discovered_peers:
                                pinfo = self.host.get_peerstore().peer_info(pid)
                                if pinfo and pinfo.addrs:
                                    nursery.start_soon(self._on_peer_discovered_async, pinfo)
                    except Exception as e:
                        logger.debug(f"Peerstore sync check error: {e}")

            nursery.start_soon(sync_peerstore_peers)
            nursery.start_soon(self.host.get_peerstore().start_cleanup_task, 60)
            logger.info(f"libp2p node running with PeerID: {self.host.get_id().to_string()}")
            await trio.sleep_forever()

    async def query_handler(self, request: dict, context) -> dict:
        """Handle incoming libp2p package queries with rate limiting and cluster auth."""
        package_name = request.get("package", "")
        peer_id = context.peer_id
        peer_id_str = peer_id.to_string()
        logger.info(f"Received query request for package: {package_name} from {peer_id_str}")

        # Check query rate limit per peer ID
        if not self.rate_limiter.allow(peer_id_str):
            logger.warning(f"Rate limited query from {peer_id_str} for package {package_name}")
            return {"has_package": False, "rate_limited": True}

        # Check cluster token authentication if enabled
        if self.cluster_token:
            req_token = request.get("cluster_token")
            if not isinstance(req_token, str) or not secrets.compare_digest(req_token, self.cluster_token):
                logger.warning(f"Unauthorized query from {peer_id_str}: invalid or missing cluster token")
                return {"has_package": False, "unauthorized": True}

        # Thread-safe/async-safe update: if we don't have this peer in discovered list, add it
        if peer_id_str not in self.discovered_peers:
            try:
                if self.host:
                    peerinfo = self.host.get_peerstore().peer_info(peer_id)
                    if peerinfo and peerinfo.addrs:
                        await self._on_peer_discovered_async(peerinfo)
            except Exception as e:
                logger.debug(f"Failed to dynamically discover connecting peer {peer_id_str}: {e}")
        
        # Response must indicate if we have the package
        response: Dict[str, Any] = {
            "has_package": False,
            "http_port": self.local_http_port
        }
        if package_name == "__p2p_diagnostic_ping__":
            return response

        if self.cache_lookup_callback is not None:
            p_info = self.cache_lookup_callback(package_name)
            if p_info:
                response["has_package"] = True
                response["hash"] = p_info.get("hash", "")
                response["size"] = p_info.get("size", 0)
                logger.info(f"We HAVE the package {package_name}. Responding positively.")
        return response

    def query_peers_for_package(self, package_name: str) -> List[Dict]:
        """Query all discovered peers for a package. Thread-safe."""
        if not self.trio_token:
            logger.warning("libp2p node not fully started, cannot query peers")
            return []

        async def do_query():
            results = []
            peer_ids = list(self.discovered_peers.keys())
            logger.info(f"Querying {len(peer_ids)} discovered peers for {package_name}")
            limit = trio.CapacityLimiter(self.max_parallel_peers)

            async def query_peer(peer_id_str: str):
                async with limit:
                    peerinfo = self.discovered_peers.get(peer_id_str)
                    if not peerinfo:
                        return
                    try:
                        logger.info(f"Connecting to peer {peer_id_str}...")
                        await self.host.connect(peerinfo)

                        start_time = trio.current_time()
                        req_payload: Dict[str, Any] = {"package": package_name}
                        if self.cluster_token:
                            req_payload["cluster_token"] = self.cluster_token
                        response = await self.rr.send_request(
                            peer_id=peerinfo.peer_id,
                            protocol_ids=[PROTOCOL_ID],
                            request=req_payload,
                            codec=self.codec
                        )
                        rtt_ms = (trio.current_time() - start_time) * 1000.0

                        if response and response.get("has_package"):
                            ip = extract_ip(peerinfo.addrs)
                            if ip:
                                results.append({
                                    "ip": ip,
                                    "port": response.get("http_port"),
                                    "hash": response.get("hash"),
                                    "size": response.get("size"),
                                    "rtt_ms": rtt_ms
                                })
                                logger.info(
                                    f"Peer {peer_id_str} at {ip}:{response.get('http_port')} has package {package_name} "
                                    f"(RTT: {rtt_ms:.1f}ms)"
                                )
                    except Exception as e:
                        logger.warning(f"Failed to query peer {peer_id_str}: {e}")
                        # Remove unresponsive peer
                        self.remove_peer(peer_id_str)

            with trio.move_on_after(self.peer_discovery_timeout):
                async with trio.open_nursery() as nursery:
                    for peer_id_str in peer_ids:
                        nursery.start_soon(query_peer, peer_id_str)

            # Sort peers by lowest RTT (fastest peer first)
            results.sort(key=lambda x: x.get("rtt_ms", float("inf")))
            return results

        try:
            return trio.from_thread.run(do_query, trio_token=self.trio_token)
        except Exception as e:
            logger.error(f"Error querying peers from thread: {e}")
            return []

    async def _on_peer_discovered_async(self, peerinfo: PeerInfo):
        """Handle peer discovery inside the Trio event loop."""
        peer_id_str = peerinfo.peer_id.to_string()
        if peer_id_str != self.host.get_id().to_string():
            logger.info(f"Discovered peer: {peer_id_str} at {peerinfo.addrs}")
            self.discovered_peers[peer_id_str] = peerinfo
            if peer_id_str not in self.tested_peers:
                self.tested_peers.add(peer_id_str)
                if self.nursery:
                    self.nursery.start_soon(self._run_diagnostic_check_async, peerinfo)

    # TODO: maybe rethink - automatically triggering an HTTP request (requests.get) to a peer's self-reported IP/port upon discovery represents a significant security/SSRF risk.
    # A malicious peer could connect to our node and cause us to send requests to local ports or internal services on the LAN (e.g., port scanning or service exploitation).
    async def _run_diagnostic_check_async(self, peerinfo: PeerInfo):
        """Connect to peer, query HTTP port via libp2p, and transfer diagnostic file via HTTP."""
        peer_id_str = peerinfo.peer_id.to_string()
        logger.info(f"Starting P2P diagnostic connection and transfer check for peer {peer_id_str}")
        url = None
        try:
            # 1. Connect to peer
            await self.host.connect(peerinfo)

            # 2. Get HTTP port
            ping_payload: Dict[str, Any] = {"package": "__p2p_diagnostic_ping__"}
            if self.cluster_token:
                ping_payload["cluster_token"] = self.cluster_token
            response = await self.rr.send_request(
                peer_id=peerinfo.peer_id,
                protocol_ids=[PROTOCOL_ID],
                request=ping_payload,
                codec=self.codec
            )
            if not response or "http_port" not in response:
                raise RuntimeError(f"Invalid response from peer query: {response}")

            http_port = response["http_port"]
            ip = extract_ip(peerinfo.addrs)
            if not ip:
                raise RuntimeError(f"Could not extract IP address from peer addresses: {peerinfo.addrs}")

            # SSRF Protection: Ensure peer-reported HTTP port is non-privileged
            try:
                port_num = int(http_port)
                if port_num < 1024 or port_num > 65535:
                    raise ValueError(f"Port {port_num} is outside the allowed non-privileged range (1024-65535)")
            except (ValueError, TypeError) as e:
                raise RuntimeError(f"SSRF Protection: Peer reported invalid or privileged port {http_port}: {e}")

            # SSRF Protection: Validate IP address
            try:
                parsed_ip = ipaddress.ip_address(ip)
            except ValueError as e:
                raise RuntimeError(f"SSRF Protection: Invalid IP address {ip}: {e}")

            if parsed_ip.is_loopback or parsed_ip.is_link_local or parsed_ip.is_multicast or parsed_ip.is_unspecified or parsed_ip.is_reserved:
                raise RuntimeError(f"SSRF Protection: Rejecting diagnostic request to non-routable address {ip}")

            if ip == "169.254.169.254":
                raise RuntimeError(f"SSRF Protection: Rejecting cloud metadata endpoint {ip}")

            if ":" in ip:
                url = f"http://[{ip}]:{http_port}/packages/p2p-diagnostic.txt"
            else:
                url = f"http://{ip}:{http_port}/packages/p2p-diagnostic.txt"

            # 3. HTTP GET to fetch diagnostic file (with 3 retries)
            max_retries = 3
            last_err = None
            for attempt in range(1, max_retries + 1):
                try:
                    logger.debug(f"Attempting diagnostic HTTP GET from {url} (attempt {attempt}/{max_retries})")
                    
                    def fetch():
                        import requests
                        kwargs: Dict[str, Any] = {"timeout": 3, "allow_redirects": False}
                        if self.cluster_token:
                            kwargs["headers"] = {"X-Cluster-Token": self.cluster_token}
                        r = requests.get(url, **kwargs)
                        r.raise_for_status()
                        return r.content

                    content = await trio.to_thread.run_sync(fetch)
                    if content != b"OK":
                        raise RuntimeError(f"Unexpected diagnostic file content: {content}")
                    last_err = None
                    break
                except Exception as ex:
                    last_err = ex
                    if attempt < max_retries:
                        await trio.sleep(1.0)

            if last_err:
                raise last_err

            logger.info(f"Diagnostic check SUCCESS: successfully transferred diagnostic file from peer {peer_id_str} at {url}")

        except Exception as e:
            logger.critical(
                "\n"
                "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
                "P2P SYSTEM ERROR: DIAGNOSTIC FILE TRANSFER FAILED between hosts!\n"
                f"Failed to fetch diagnostic file from peer {peer_id_str} at {url or 'unknown URL'}.\n"
                f"Error details: {e}\n"
                "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
            )
            # Remove peer from discovered list so it can be re-discovered/re-tested
            self.remove_peer(peer_id_str)
