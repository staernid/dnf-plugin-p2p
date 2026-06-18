#!/usr/bin/env python3
# peer_discovery.py - Multicast peer discovery for P2P sharing
#
# Copyright (C) 2024 libdnf-p2p-sharing contributors
# Licensed under GNU General Public License v2.0 or later
#

import socket
import struct
import logging
import json
from typing import List, Dict, Tuple
import threading
import time

logger = logging.getLogger(__name__)


class P2PPeerDiscovery:
    """Handles multicast discovery of P2P peers on the local network."""

    def __init__(self, multicast_group: str = "224.0.0.1", multicast_port: int = 5353):
        """Initialize peer discovery.
        
        Args:
            multicast_group: Multicast IP address (default: 224.0.0.1)
            multicast_port: Multicast port (default: 5353)
        """
        self.multicast_group = multicast_group
        self.multicast_port = multicast_port
        self.peers = {}  # {peer_id: peer_info}
        self.lock = threading.Lock()

    def query_peers(self, query: str, timeout: float = 2.0) -> List[Dict]:
        """Send a multicast query and collect responses from peers.
        
        Args:
            query: Query string (e.g., package hash or name)
            timeout: Timeout for collecting responses (seconds)
        
        Returns:
            List of peer information dictionaries containing responses
        """
        responses = []
        
        try:
            # Create UDP socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Join multicast group
            mreq = struct.pack('4sL', socket.inet_aton(self.multicast_group), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            
            # Set socket timeout
            sock.settimeout(timeout)
            
            # Send query
            query_msg = json.dumps({
                "type": "query",
                "query": query,
                "timestamp": time.time()
            })
            
            sock.sendto(query_msg.encode(), (self.multicast_group, self.multicast_port))
            logger.debug(f"Sent peer discovery query: {query}")
            
            # Collect responses
            try:
                while True:
                    data, addr = sock.recvfrom(4096)
                    response = json.loads(data.decode())
                    
                    if response.get("type") == "response":
                        peer_info = {
                            "address": addr[0],
                            "port": response.get("port"),
                            "has_package": response.get("has_package", False),
                            "package_hash": response.get("hash"),
                            "package_size": response.get("size"),
                            "timestamp": response.get("timestamp")
                        }
                        responses.append(peer_info)
                        logger.debug(f"Peer response from {addr[0]}: {peer_info}")
            except socket.timeout:
                pass  # Normal timeout, stop collecting responses
            finally:
                sock.close()
        
        except Exception as e:
            logger.error(f"Error during peer discovery: {e}")
        
        return responses

    def register_peer(self, peer_id: str, peer_info: Dict) -> None:
        """Register a peer in the local peer list.
        
        Args:
            peer_id: Unique identifier for the peer
            peer_info: Dictionary containing peer information
        """
        with self.lock:
            self.peers[peer_id] = peer_info
            logger.debug(f"Registered peer: {peer_id}")

    def get_peers(self) -> List[Dict]:
        """Get list of known peers.
        
        Returns:
            List of peer information dictionaries
        """
        with self.lock:
            return list(self.peers.values())
