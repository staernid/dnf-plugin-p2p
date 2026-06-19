#!/usr/bin/env python3
# p2p_server.py - P2P HTTP proxy server for package sharing
#
# Copyright (C) 2024 libdnf-p2p-sharing contributors
# Licensed under GNU General Public License v2.0 or later
#

import argparse
import logging
import os
import socket
import sys
import threading
import urllib.parse
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path
from typing import Optional


# Set up local paths relative to this script
sys.path.append(str(Path(__file__).parent))

from p2p_cache import P2PCache
from p2p_libp2p import P2PLibp2pNode

logger = logging.getLogger("p2p_server")


class ClientDisconnected(Exception):
    """Exception raised when the proxy client disconnects during an operation."""
    pass


class P2PProxyHandler(BaseHTTPRequestHandler):
    """HTTP request handler for P2P package proxy."""
    
    cache: P2PCache = None
    libp2p_node: P2PLibp2pNode = None
    force_https: bool = True

    def do_CONNECT(self):
        """Handle HTTP CONNECT requests to tunnel HTTPS traffic."""
        self.close_connection = True
        address = self.path.split(':')
        host = address[0]
        try:
            port = int(address[1])
        except (IndexError, ValueError):
            port = 443

        logger.debug(f"CONNECT tunnel request to {host}:{port}")
        try:
            # Connect to the destination server
            dest_socket = socket.create_connection((host, port), timeout=10)
            dest_socket.settimeout(None)
            self.request.settimeout(None)
            
            # Send HTTP response headers to client
            self.send_response(200, 'Connection Established')
            self.end_headers()


            # Bidirectional data relay function
            def relay(source, destination):
                try:
                    while True:
                        data = source.recv(8192)
                        if not data:
                            break
                        destination.sendall(data)
                except Exception:
                    pass
                finally:
                    try:
                        source.close()
                    except Exception:
                        pass
                    try:
                        destination.close()
                    except Exception:
                        pass

            # Start thread to relay destination to client
            t = threading.Thread(target=relay, args=(dest_socket, self.request), daemon=True)
            t.start()
            # Relay client to destination in current thread
            relay(self.request, dest_socket)

        except Exception as e:
            logger.error(f"CONNECT tunnel failed for {host}:{port}: {e}")
            try:
                self.send_error(502, f"Bad Gateway: {e}")
            except Exception:
                pass

    def do_GET(self):
        """Handle GET requests for packages and metadata."""
        try:
            parsed_path = urllib.parse.urlparse(self.path)
            
            # Health check endpoint to verify proxy identity/status
            if parsed_path.path == "/ping":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", "4")
                self.end_headers()
                try:
                    self.wfile.write(b"pong")
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
                    raise ClientDisconnected() from e
                return

            filename = Path(parsed_path.path).name
            logger.info(f"GET request for {filename}")
            
            # Parse remote URL from parameters
            query_params = urllib.parse.parse_qs(parsed_path.query)
            remote_url = query_params.get("remote_url", [None])[0]
            if not remote_url and (self.path.startswith("http://") or self.path.startswith("https://")):
                remote_url = self.path

            # Automatically upgrade HTTP mirror URLs to HTTPS to secure internet traffic
            if self.force_https and remote_url and remote_url.startswith("http://"):
                parsed_remote = urllib.parse.urlparse(remote_url)
                if parsed_remote.hostname not in ("127.0.0.1", "localhost"):
                    remote_url = remote_url.replace("http://", "https://", 1)

            # Only cache and peer-query package files (.rpm, .drpm).
            # Metadata and other non-package files are streamed directly.
            if not filename.endswith((".rpm", ".drpm")):
                if remote_url:
                    logger.info(f"Bypassing cache/P2P for non-package file {filename}, streaming directly")
                    self._stream_remote(remote_url)
                else:
                    self.send_error(404, f"File {filename} not found and no remote_url specified.")
                return

            # 1. Check if package is in local cache
            cache_file = self.cache.get_cached_file_by_name(filename)
            if cache_file:
                logger.info(f"Serving {filename} from local cache")
                self._serve_file(cache_file)
                return

            # 2. Query peers for the package
            peers = self.libp2p_node.query_peers_for_package(filename)
            if peers:
                for peer in peers:
                    peer_ip = peer["ip"]
                    peer_port = peer["port"]
                    peer_url = f"http://{peer_ip}:{peer_port}/packages/{filename}"
                    logger.info(f"Attempting to download {filename} from peer {peer_ip}:{peer_port}")
                    if self._download_and_serve(peer_url, filename):
                        return
                logger.warning(f"Failed to fetch {filename} from any peers. Falling back to remote mirror.")

            # 3. Fallback to remote mirror
            if remote_url:
                logger.info(f"Downloading {filename} from remote mirror: {remote_url}")
                if self._download_and_serve(remote_url, filename):
                    return
            
            self.send_error(404, f"File {filename} not found locally, on peers, or no remote_url specified.")
        except ClientDisconnected:
            logger.info(f"Client connection closed, stopping GET processing for {filename if 'filename' in locals() else self.path}")

    def do_HEAD(self):
        """Handle HEAD requests."""
        parsed_path = urllib.parse.urlparse(self.path)
        
        # Health check endpoint
        if parsed_path.path == "/ping":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "4")
            self.end_headers()
            return

        filename = Path(parsed_path.path).name

        
        # Parse remote URL from parameters
        query_params = urllib.parse.parse_qs(parsed_path.query)
        remote_url = query_params.get("remote_url", [None])[0]
        if not remote_url and (self.path.startswith("http://") or self.path.startswith("https://")):
            remote_url = self.path

        # Automatically upgrade HTTP mirror URLs to HTTPS to secure internet traffic
        if self.force_https and remote_url and remote_url.startswith("http://"):
            parsed_remote = urllib.parse.urlparse(remote_url)
            if parsed_remote.hostname not in ("127.0.0.1", "localhost"):
                remote_url = remote_url.replace("http://", "https://", 1)

        # Check local cache (only if it is a package file)
        if filename.endswith((".rpm", ".drpm")):
            cache_file = self.cache.get_cached_file_by_name(filename)
            if cache_file:
                self.send_response(200)
                self.send_header("Content-Type", "application/x-redhat-package-manager")
                self.send_header("Content-Length", str(cache_file.stat().st_size))
                self.end_headers()
                return

        # Fallback to remote URL for metadata
        if remote_url:
            try:
                response = requests.head(remote_url, timeout=5)
                self.send_response(response.status_code)
                for header, value in response.headers.items():
                    if header.lower() in ["content-length", "content-type", "last-modified"]:
                        self.send_header(header, value)
                self.end_headers()
                return
            except Exception as e:
                logger.error(f"Error handling HEAD for remote: {e}")
        
        self.send_error(404, "File Not Found")

    def _serve_file(self, file_path: Path):
        """Helper to serve a file from disk."""
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-redhat-package-manager")
            self.send_header("Content-Length", str(file_path.stat().st_size))
            self.end_headers()
            with open(file_path, 'rb') as f:
                while chunk := f.read(65536):
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
                        raise ClientDisconnected() from e
        except ClientDisconnected:
            raise
        except Exception as e:
            logger.error(f"Error serving file: {e}")

    @staticmethod
    def _rewrite_metalink_urls(content: bytes) -> bytes:
        """Rewrite only <url> element text in metalink XML from https:// to http://.

        Uses a regex that targets only the URL text inside <url ...>...</url>
        elements, leaving checksums and all other content untouched.
        """
        import re
        # Match <url ...>https://...</url> and rewrite only the URL text
        def _rewrite_url_element(match):
            prefix = match.group(1)
            url_text = match.group(2)
            suffix = match.group(3)
            rewritten = url_text.replace(b"https://", b"http://")
            return prefix + rewritten + suffix

        # Regex: capture <url ...> prefix, URL text, and </url> suffix
        pattern = rb'(<url[^>]*>)(https://[^<]+)(</url>)'
        return re.sub(pattern, _rewrite_url_element, content)

    def _stream_remote(self, url: str) -> bool:
        """Stream a file from a remote URL to the client without caching it."""
        try:
            # Check if this is a metalink/mirrorlist that needs URL rewriting
            is_metalink = "metalink" in url or "mirrorlist" in url
            
            # Forward key headers from the client (Range for zchunk, etc.)
            forwarded_headers = {}
            for hdr in ("Range", "If-Range", "If-None-Match", "If-Modified-Since"):
                val = self.headers.get(hdr)
                if val:
                    forwarded_headers[hdr] = val
            
            response = requests.get(url, stream=not is_metalink, timeout=15,
                                    headers=forwarded_headers if forwarded_headers else None)
            
            if is_metalink:
                # Rewrite mirror URLs from HTTPS to HTTP so DNF sends GETs through proxy
                content = response.content
                modified_content = self._rewrite_metalink_urls(content)
                try:
                    self.send_response(response.status_code)
                    for header, value in response.headers.items():
                        if header.lower() == "content-length":
                            self.send_header(header, str(len(modified_content)))
                        elif header.lower() in ["content-type", "last-modified", "etag"]:
                            self.send_header(header, value)
                    self.end_headers()
                    self.wfile.write(modified_content)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
                    raise ClientDisconnected() from e
                return True

            try:
                self.send_response(response.status_code)
                for header, value in response.headers.items():
                    if header.lower() in ["content-type", "content-length", "content-range",
                                          "last-modified", "etag", "accept-ranges"]:
                        self.send_header(header, value)
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
                raise ClientDisconnected() from e

            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
                        raise ClientDisconnected() from e
            return True
        except ClientDisconnected:
            raise
        except Exception as e:
            logger.error(f"Error streaming from {url}: {e}")
            return False

    def _download_and_serve(self, url: str, filename: str) -> bool:
        """Download file from URL, stream it to client, and save to cache."""
        temp_file = self.cache.cache_dir / f"{filename}.tmp"
        success = False
        try:
            response = requests.get(url, stream=True, timeout=15)
            if response.status_code != 200:
                logger.warning(f"Download source {url} returned status {response.status_code}")
                return False

            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/x-redhat-package-manager")
                if "Content-Length" in response.headers:
                    self.send_header("Content-Length", response.headers["Content-Length"])
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
                raise ClientDisconnected() from e

            with open(temp_file, 'wb') as tmp_f:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        try:
                            self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
                            raise ClientDisconnected() from e
                        tmp_f.write(chunk)
            success = True
            return True
        except ClientDisconnected:
            raise
        except Exception as e:
            logger.error(f"Error downloading or serving package from {url}: {e}")
            return False
        finally:
            if success:
                final_file = self.cache.cache_dir / filename
                try:
                    temp_file.rename(final_file)
                    # Add to cache index
                    self.cache.add_to_cache(final_file, None, {"source": url})
                    logger.info(f"Successfully cached {filename}")
                except Exception as e:
                    logger.error(f"Failed to register {filename} in cache: {e}")
            else:
                if temp_file.exists():
                    temp_file.unlink()

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
    # Silence verbose dependencies
    logging.getLogger("trio").setLevel(logging.WARNING)
    logging.getLogger("libp2p").setLevel(logging.WARNING)
    logging.getLogger("multiaddr").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _get_systemd_socket():
    """Return a socket inherited from systemd via socket activation, or None.

    Systemd passes pre-bound sockets as file descriptors starting at 3.
    It signals this via LISTEN_FDS=<n> and LISTEN_PID=<pid>.
    """
    import os
    import socket as _socket

    listen_fds = int(os.environ.get("LISTEN_FDS", 0))
    listen_pid = int(os.environ.get("LISTEN_PID", 0))

    if listen_fds < 1 or listen_pid != os.getpid():
        return None

    # First fd is SD_LISTEN_FDS_START = 3
    fd = 3
    sock = _socket.fromfd(fd, _socket.AF_INET, _socket.SOCK_STREAM)
    # fromfd() dups the fd; close the original so we don't leak it
    os.close(fd)
    sock.setblocking(True)
    return sock


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server."""
    daemon_threads = True


def main():
    """Main entry point for the P2P proxy server."""
    # Hardcoded default values
    try:
        is_root = os.geteuid() == 0
    except AttributeError:
        is_root = False

    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 8888
    DEFAULT_LIBP2P_PORT = 8000
    DEFAULT_CACHE_DIR = "/var/cache/dnf-plugin-p2p" if is_root else str(Path.home() / ".cache" / "dnf-plugin-p2p")
    DEFAULT_PEER_DISCOVERY_TIMEOUT = 2.0
    DEFAULT_MAX_PARALLEL_PEERS = 5
    DEFAULT_DEBUG = False
    DEFAULT_MAX_CACHE_SIZE_MB = 1024
    DEFAULT_MAX_DISK_USAGE_PERCENT = 90.0
    DEFAULT_FORCE_HTTPS = True

    parser = argparse.ArgumentParser(
        description="P2P HTTP proxy server for DNF package sharing"
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to the configuration file"
    )
    parser.add_argument(
        "--host",
        default=None,
        help=f"Host to bind to (default: {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"HTTP proxy port (default: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--libp2p-port",
        type=int,
        default=None,
        help=f"libp2p listener port (default: {DEFAULT_LIBP2P_PORT})"
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help=f"Package cache directory (default: {DEFAULT_CACHE_DIR})"
    )
    parser.add_argument(
        "--peer-discovery-timeout",
        type=float,
        default=None,
        help=f"Timeout for peer discovery queries in seconds (default: {DEFAULT_PEER_DISCOVERY_TIMEOUT})"
    )
    parser.add_argument(
        "--max-parallel-peers",
        type=int,
        default=None,
        help=f"Maximum number of parallel peer queries (default: {DEFAULT_MAX_PARALLEL_PEERS})"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=None,
        help="Enable debug logging"
    )
    parser.add_argument(
        "--max-cache-size-mb",
        type=int,
        default=None,
        help=f"Maximum cache size in MB (default: {DEFAULT_MAX_CACHE_SIZE_MB})"
    )
    parser.add_argument(
        "--max-disk-usage-percent",
        type=float,
        default=None,
        help=f"Maximum disk usage percentage (default: {DEFAULT_MAX_DISK_USAGE_PERCENT})"
    )
    parser.add_argument(
        "--no-force-https",
        action="store_false",
        dest="force_https",
        default=None,
        help="Disable automatic upgrading of HTTP mirror URLs to HTTPS"
    )
    
    args = parser.parse_args()

    # Load config file
    config_paths = []
    if args.config:
        config_paths.append(Path(args.config))
    else:
        config_paths.extend([
            Path("/etc/dnf/libdnf5-plugins/python_plugins_loader.d/p2p_plugin.conf"),
            Path("/etc/dnf/libdnf5-plugins/p2p-plugin.conf"),
            Path("/etc/dnf/libdnf5-plugins/p2p_plugin.conf"),
            Path("/etc/dnf/libdnf-plugins/p2p-plugin.conf"),
            Path("/etc/dnf/plugins/p2p-plugin.conf"),
        ])

    config_values = {}
    for path in config_paths:
        if path.exists():
            try:
                from configparser import ConfigParser
                config = ConfigParser()
                config.read(path)
                if config.has_section("p2p"):
                    if config.has_option("p2p", "proxy_host"):
                        config_values["host"] = config.get("p2p", "proxy_host")
                    if config.has_option("p2p", "proxy_port"):
                        try:
                            config_values["port"] = config.getint("p2p", "proxy_port")
                        except ValueError:
                            pass
                    if config.has_option("p2p", "peer_discovery_timeout"):
                        try:
                            config_values["peer_discovery_timeout"] = config.getfloat("p2p", "peer_discovery_timeout")
                        except ValueError:
                            pass
                    if config.has_option("p2p", "max_parallel_peers"):
                        try:
                            config_values["max_parallel_peers"] = config.getint("p2p", "max_parallel_peers")
                        except ValueError:
                            pass
                    if config.has_option("p2p", "debug"):
                        try:
                            config_values["debug"] = config.getboolean("p2p", "debug")
                        except ValueError:
                            pass
                    if config.has_option("p2p", "max_cache_size_mb"):
                        try:
                            config_values["max_cache_size_mb"] = config.getint("p2p", "max_cache_size_mb")
                        except ValueError:
                            pass
                    if config.has_option("p2p", "max_disk_usage_percent"):
                        try:
                            config_values["max_disk_usage_percent"] = config.getfloat("p2p", "max_disk_usage_percent")
                        except ValueError:
                            pass
                    if config.has_option("p2p", "force_https"):
                        try:
                            config_values["force_https"] = config.getboolean("p2p", "force_https")
                        except ValueError:
                            pass
                    if config.has_option("p2p", "libp2p_port"):
                        try:
                            config_values["libp2p_port"] = config.getint("p2p", "libp2p_port")
                        except ValueError:
                            pass
                    if config.has_option("p2p", "cache_dir"):
                        config_values["cache_dir"] = config.get("p2p", "cache_dir")
                break
            except Exception as e:
                # Can't use logger yet because logging isn't set up
                print(f"Warning: Failed to load config from {path}: {e}", file=sys.stderr)

    # Merge configuration values
    host = args.host if args.host is not None else config_values.get("host", DEFAULT_HOST)
    port = args.port if args.port is not None else config_values.get("port", DEFAULT_PORT)
    libp2p_port = args.libp2p_port if args.libp2p_port is not None else config_values.get("libp2p_port", DEFAULT_LIBP2P_PORT)
    cache_dir = args.cache_dir if args.cache_dir is not None else config_values.get("cache_dir", DEFAULT_CACHE_DIR)
    debug = args.debug if args.debug is not None else config_values.get("debug", DEFAULT_DEBUG)
    peer_discovery_timeout = args.peer_discovery_timeout if args.peer_discovery_timeout is not None else config_values.get("peer_discovery_timeout", DEFAULT_PEER_DISCOVERY_TIMEOUT)
    max_parallel_peers = args.max_parallel_peers if args.max_parallel_peers is not None else config_values.get("max_parallel_peers", DEFAULT_MAX_PARALLEL_PEERS)
    max_cache_size_mb = args.max_cache_size_mb if args.max_cache_size_mb is not None else config_values.get("max_cache_size_mb", DEFAULT_MAX_CACHE_SIZE_MB)
    max_disk_usage_percent = args.max_disk_usage_percent if args.max_disk_usage_percent is not None else config_values.get("max_disk_usage_percent", DEFAULT_MAX_DISK_USAGE_PERCENT)
    force_https = args.force_https if args.force_https is not None else config_values.get("force_https", DEFAULT_FORCE_HTTPS)

    setup_logging(debug=debug)
    
    # Initialize cache
    cache_path = Path(cache_dir).expanduser()
    cache = P2PCache(cache_path, max_cache_size_mb=max_cache_size_mb, max_disk_usage_percent=max_disk_usage_percent)
    
    # Start libp2p node
    logger.info("Initializing libp2p node...")
    libp2p_node = P2PLibp2pNode(
        libp2p_port=libp2p_port,
        local_http_port=port,
        cache_lookup_callback=cache.lookup_filename,
        peer_discovery_timeout=peer_discovery_timeout,
        max_parallel_peers=max_parallel_peers
    )
    libp2p_node.start()

    # Pass dependencies to handler
    P2PProxyHandler.cache = cache
    P2PProxyHandler.libp2p_node = libp2p_node
    P2PProxyHandler.force_https = force_https
    
    # Create HTTP server — prefer systemd-passed socket for socket activation
    try:
        sd_sock = _get_systemd_socket()
        if sd_sock is not None:
            logger.info("Using systemd socket-activated fd")
            server = ThreadingHTTPServer(server_address=(host, port),
                                         RequestHandlerClass=P2PProxyHandler,
                                         bind_and_activate=False)
            server.socket = sd_sock
            server.server_address = sd_sock.getsockname()
        else:
            server = ThreadingHTTPServer((host, port), P2PProxyHandler)

        logger.info(f"P2P proxy HTTP server listening on http://{host}:{port}")
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down P2P proxy server")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error in HTTP server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()


