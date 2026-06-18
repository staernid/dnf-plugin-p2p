#!/usr/bin/env python3
# p2p_peer_discovery.py - Multicast peer discovery for P2P proxy server
#
# Copyright (C) 2024 libdnf-p2p-sharing contributors
# Licensed under GNU General Public License v2.0 or later
#

import socket
import struct
import logging
import json
import threading
from typing import List, Dict, Callable
import time

logger = logging.getLogger(__name__)


class P2PPeerDiscoveryServer:
    """Handles multicast peer discovery for the P2P proxy server."""

    def __init__(
        self,
        multicast_group: str = "224.0.0.1",
        multicast_port: int = 5353,
        local_port: int = 8888,
        cache_callback: Callable = None
    ):
        """Initialize the peer discovery server.
        
        Args:
            multicast_group: Multicast IP address
            multicast_port: Multicast port
            local_port: Local port this server is listening on
            cache_callback: Callback to get cached files info
        """
        self.multicast_group = multicast_group
        self.multicast_port = multicast_port
        self.local_port = local_port
        self.cache_callback = cache_callback
        self.running = False
        self.thread = None

    def start(self) -> None:
        """Start listening for peer discovery queries."""
        self.running = True
        self.thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.thread.start()
        logger.info("Peer discovery server started")

    def stop(self) -> None:
        """Stop listening for peer discovery queries."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Peer discovery server stopped")

    def _listen_loop(self) -> None:
        """Main listening loop for multicast queries."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Bind to the multicast port
            sock.bind(('', self.multicast_port))
            
            # Join multicast group
            mreq = struct.pack('4sL', socket.inet_aton(self.multicast_group), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            
            logger.debug(f"Listening on multicast {self.multicast_group}:{self.multicast_port}")
            
            while self.running:
                try:
                    sock.settimeout(1.0)
                    data, addr = sock.recvfrom(4096)
                    self._handle_query(data, addr, sock)
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        logger.error(f"Error in discovery loop: {e}")
        except Exception as e:
            logger.error(f"Failed to start discovery server: {e}")
        finally:
            try:
                sock.close()
            except:
                pass

    def _handle_query(self, data: bytes, addr: tuple, sock: socket.socket) -> None:
        """Handle an incoming peer discovery query.
        
        Args:
            data: Query data
            addr: Address of the querying peer
            sock: UDP socket to use for response
        """
        try:
            query = json.loads(data.decode())
            
            if query.get("type") != "query":
                return
            
            query_string = query.get("query", "")
            logger.debug(f"Query from {addr[0]}: {query_string}")
            
            # Get list of cached files
            cached_files = self.cache_callback() if self.cache_callback else []
            
            # Check if we have the requested package
            response = {
                "type": "response",
                "port": self.local_port,
                "timestamp": time.time(),
                "cached_count": len(cached_files)
            }
            
            # If query matches a cached file, indicate we have it
            for cached_file in cached_files:
                if query_string in cached_file.get("filename", "") or \
                   query_string in cached_file.get("hash", ""):
                    response["has_package"] = True
                    response["hash"] = cached_file.get("hash")
                    response["size"] = cached_file.get("size")
                    break
            
            # Send response back to the querying peer
            response_data = json.dumps(response).encode()
            sock.sendto(response_data, addr)
            logger.debug(f"Sent response to {addr[0]}: {response}")
        
        except Exception as e:
            logger.error(f"Error handling query from {addr[0]}: {e}")
