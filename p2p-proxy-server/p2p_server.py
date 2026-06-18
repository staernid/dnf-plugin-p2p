#!/usr/bin/env python3
# p2p_server.py - P2P HTTP proxy server for package sharing
#
# Copyright (C) 2024 libdnf-p2p-sharing contributors
# Licensed under GNU General Public License v2.0 or later
#

import argparse
import logging
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import json
import urllib.parse
from typing import Optional

logger = logging.getLogger(__name__)


class P2PProxyHandler(BaseHTTPRequestHandler):
    """HTTP request handler for P2P package proxy."""

    def do_GET(self):
        """Handle GET requests for packages."""
        # Parse the request path
        parsed_path = urllib.parse.urlparse(self.path)
        logger.debug(f"GET request: {parsed_path.path}")
        
        # TODO: Implement proxy logic
        # 1. Check if package is in local cache
        # 2. Query peers for the package
        # 3. Download from peer or remote mirror
        # 4. Serve the file
        
        self.send_error(501, "Not Implemented")

    def do_HEAD(self):
        """Handle HEAD requests."""
        logger.debug(f"HEAD request: {self.path}")
        # TODO: Implement HEAD request handling
        self.send_error(501, "Not Implemented")

    def log_message(self, format, *args):
        """Override logging for cleaner output."""
        logger.info("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), format % args))


def setup_logging(debug: bool = False) -> None:
    """Configure logging for the proxy server."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def main():
    """Main entry point for the P2P proxy server."""
    parser = argparse.ArgumentParser(
        description="P2P HTTP proxy server for DNF package sharing"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8888,
        help="Port to bind to (default: 8888)"
    )
    parser.add_argument(
        "--multicast-group",
        default="224.0.0.1",
        help="Multicast group for peer discovery (default: 224.0.0.1)"
    )
    parser.add_argument(
        "--multicast-port",
        type=int,
        default=5353,
        help="Multicast port for peer discovery (default: 5353)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    setup_logging(debug=args.debug)
    
    logger.info(f"Starting P2P proxy server on {args.host}:{args.port}")
    
    # Create and start HTTP server
    try:
        server = HTTPServer((args.host, args.port), P2PProxyHandler)
        logger.info(f"P2P proxy server listening on {args.host}:{args.port}")
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down P2P proxy server")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
