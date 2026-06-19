#!/usr/bin/env python3
# p2p_plugin.py - libdnf5 plugin for P2P package sharing
#
# Copyright (C) 2024 libdnf-p2p-sharing contributors
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU General Public License v.2, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY expressed or implied, including the implied warranties of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.  You should have received a copy of the
# GNU General Public License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.
#

import libdnf5
import libdnf5.plugin
import libdnf5.base
import subprocess
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class Plugin(libdnf5.plugin.IPlugin):
    """
    libdnf5 plugin for peer-to-peer package sharing over local networks.
    
    This plugin enables systems to discover and download RPM packages from
    peers on the local network using multicast discovery, reducing bandwidth
    consumption and improving download performance.
    """

    def __init__(self, data):
        super().__init__(data)
        logger.debug("P2P Sharing Plugin: Instantiated")
        self.base = self.get_base()
        self.proxy_process = None
        self.proxy_port = 8888
        self.proxy_host = "127.0.0.1"
        self.enabled = False
        self.debug = False
        self.cache_enabled = True
        self.multicast_group = "224.0.0.1"
        self.multicast_port = 5353

    def _print(self, message):
        """Print message to stderr only if debug mode is enabled."""
        if self.debug:
            print(message, file=sys.stderr)

    @staticmethod
    def get_api_version():
        """Return the plugin API version."""
        return libdnf5.PluginAPIVersion(2, 1)

    @staticmethod
    def get_name():
        """Return the plugin name."""
        return "p2p-sharing"

    @staticmethod
    def get_version():
        """Return the plugin version."""
        return libdnf5.plugin.Version(0, 2, 1)

    @staticmethod
    def get_attributes():
        """Return array of plugin attributes."""
        return [
            "author.name",
            "author.email",
            "description",
            None
        ]

    def get_attribute(self, name):
        """Get the value of a specific plugin attribute."""
        attributes = {
            "author.name": "libdnf-p2p-sharing contributors",
            "author.email": "none@example.com",
            "description": "Peer-to-peer package sharing plugin for libdnf5"
        }
        return attributes.get(name, None)

    def init(self):
        """Plugin initialization - load configuration and start proxy server."""
        # Load configuration first to check debug and enabled settings
        self._load_config()
        
        self._print(">>> P2P PLUG-IN INITIALIZED <<<")
        logger.info("P2P Sharing Plugin: Initializing")
        
        if not self.enabled:
            self._print(">>> P2P PLUG-IN DISABLED (check config) <<<")
            logger.info("P2P Sharing Plugin: Disabled in configuration")
            return
        
        # Start the local proxy server
        self._print(">>> P2P PLUG-IN STARTING PROXY SERVER <<<")
        self._start_proxy_server()
        logger.info(f"P2P Sharing Plugin: Proxy server started on {self.proxy_host}:{self.proxy_port}")

    def pre_base_setup(self):
        """Hook called before base setup. Disable zchunk so metadata downloads
        use plain .xml.gz instead of .xml.zck, which requires multi-range HTTP
        requests that the P2P proxy cannot relay correctly."""
        if not self.enabled:
            return
        try:
            config = self.base.get_config()
            config.zchunk = False
            logger.debug("P2P Sharing Plugin: Disabled zchunk for proxy compatibility")
        except Exception as e:
            logger.error(f"P2P Sharing Plugin: Failed to disable zchunk: {e}")

    def _load_config(self):
        """Load plugin configuration from /etc/dnf/libdnf5-plugins/python_plugins_loader.d/p2p_plugin.conf."""
        config_paths = [
            Path("/etc/dnf/libdnf5-plugins/python_plugins_loader.d/p2p_plugin.conf"),
            Path("/etc/dnf/libdnf5-plugins/p2p-plugin.conf"),
            Path("/etc/dnf/libdnf5-plugins/p2p_plugin.conf"),
            Path("/etc/dnf/libdnf-plugins/p2p-plugin.conf"),
            Path("/etc/dnf/plugins/p2p-plugin.conf"),  # Fallback
        ]
        
        try:
            from configparser import ConfigParser
            config = ConfigParser()
            
            for config_path in config_paths:
                if config_path.exists():
                    logger.debug(f"Loading config from {config_path}")
                    config.read(config_path)
                    break
            
            # Load settings from [p2p] section
            if config.has_section("p2p"):
                if config.has_option("p2p", "enabled"):
                    self.enabled = config.getboolean("p2p", "enabled")
                
                if config.has_option("p2p", "debug"):
                    self.debug = config.getboolean("p2p", "debug")
                
                if config.has_option("p2p", "proxy_port"):
                    self.proxy_port = config.getint("p2p", "proxy_port")
                
                if config.has_option("p2p", "proxy_host"):
                    self.proxy_host = config.get("p2p", "proxy_host")
                
                if config.has_option("p2p", "cache_enabled"):
                    self.cache_enabled = config.getboolean("p2p", "cache_enabled")
                
                if config.has_option("p2p", "multicast_group"):
                    self.multicast_group = config.get("p2p", "multicast_group")
                
                if config.has_option("p2p", "multicast_port"):
                    self.multicast_port = config.getint("p2p", "multicast_port")
        except Exception as e:
            logger.warning(f"P2P Sharing Plugin: Failed to load configuration: {e}")

    def _start_proxy_server(self):
        """Ensure the P2P proxy systemd service is active."""
        import socket
        try:
            # Check if proxy is already active and listening
            with socket.create_connection((self.proxy_host, self.proxy_port), timeout=0.1):
                self._print(">>> P2P PROXY ALREADY ACTIVE <<<")
                logger.info("P2P Sharing Plugin: proxy is already active")
                return
        except (ConnectionRefusedError, socket.timeout, OSError):
            pass

        import os
        try:
            is_root = os.geteuid() == 0
        except AttributeError:
            # Fallback for systems/environments where geteuid is not available
            is_root = False

        if not is_root:
            self._print(">>> P2P PROXY NOT ACTIVE (skipping start because run as non-root) <<<")
            logger.info("P2P Sharing Plugin: Proxy not active and skipping auto-start because run as non-root")
            return

        try:
            result = subprocess.run(
                ["systemctl", "start", "dnf-p2p-proxy.service"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                self._print(">>> P2P PROXY SERVICE STARTED <<<")
                logger.info("P2P Sharing Plugin: dnf-p2p-proxy.service started")
            else:
                logger.info(
                    f"P2P Sharing Plugin: systemctl start failed (perhaps run as non-root) "
                    f"(rc={result.returncode}): {result.stderr.strip()}"
                )
        except FileNotFoundError:
            logger.error("P2P Sharing Plugin: systemctl not found — is systemd running?")
        except subprocess.TimeoutExpired:
            logger.error("P2P Sharing Plugin: systemctl start timed out")
        except Exception as e:
            logger.error(f"P2P Sharing Plugin: Failed to start proxy service: {e}")

    def repos_configured(self):
        """Hook called after repositories are configured but before loading metadata.
        
        Modifies repository configurations to route downloads through our local P2P proxy.
        """
        self._print(">>> P2P PLUG-IN REPOS CONFIGURED <<<")
        if not self.enabled:
            return True
        
        # Check if local proxy is active and responding to identity/health checks
        import urllib.request
        proxy_active = False
        try:
            url = f"http://{self.proxy_host}:{self.proxy_port}/ping"
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200 and response.read() == b"pong":
                    proxy_active = True
        except Exception:
            pass

        if not proxy_active:
            self._print(">>> P2P PROXY NOT ACTIVE OR CONFLICTING SERVICE: BYPASSING <<<")
            logger.warning("P2P Sharing Plugin: Local proxy is not active or responding. Bypassing P2P proxy for safety.")
            return True


        try:
            logger.info("P2P Sharing Plugin: Configuring repository proxy settings")
            query = libdnf5.repo.RepoQuery(self.base)
            query.filter_enabled(True)
            
            proxy_url = f"http://{self.proxy_host}:{self.proxy_port}"
            for repo in query:
                # Only proxy remote repositories
                if not repo.is_local():
                    config = repo.get_config()
                    config.proxy = proxy_url
                    
                    # Rewrite metalink/mirrorlist/baseurl in-memory to HTTP so DNF5 sends GET requests to localhost proxy.
                    if config.metalink and config.metalink.startswith("https://"):
                        config.metalink = config.metalink.replace("https://", "http://", 1)
                    if config.mirrorlist and config.mirrorlist.startswith("https://"):
                        config.mirrorlist = config.mirrorlist.replace("https://", "http://", 1)
                    if config.baseurl:
                        new_baseurls = []
                        for url in config.baseurl:
                            if url.startswith("https://"):
                                new_baseurls.append(url.replace("https://", "http://", 1))
                            else:
                                new_baseurls.append(url)
                        config.baseurl = tuple(new_baseurls)
                    
                    self._print(f">>> Proxied repo {repo.get_id()} through {proxy_url} <<<")
                    logger.debug(f"P2P Sharing Plugin: Proxied repo {repo.get_id()} through {proxy_url}")
        except Exception as e:
            logger.error(f"P2P Sharing Plugin: Error in repos_configured hook: {e}")
        return True


    def goal_resolved(self, transaction):
        """Hook called when a goal is resolved."""
        pass

    def finish(self):
        """Plugin cleanup — proxy daemon is intentionally left running across DNF5 invocations."""
        logger.debug("P2P Sharing Plugin: Finish hook called (proxy daemon continues running)")


