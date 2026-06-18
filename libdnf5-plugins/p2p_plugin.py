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


class P2PSharingPlugin(libdnf5.plugin.IPlugin2_1):
    """
    libdnf5 plugin for peer-to-peer package sharing over local networks.
    
    This plugin enables systems to discover and download RPM packages from
    peers on the local network using multicast discovery, reducing bandwidth
    consumption and improving download performance.
    """

    def __init__(self, data):
        super().__init__(data)
        self.base = self.get_base()
        self.proxy_process = None
        self.proxy_port = 8888
        self.proxy_host = "127.0.0.1"
        self.enabled = False
        self.cache_enabled = True
        self.multicast_group = "224.0.0.1"
        self.multicast_port = 5353

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
        return libdnf5.plugin.Version(0, 1, 0)

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
        logger.info("P2P Sharing Plugin: Initializing")
        
        # Load configuration
        self._load_config()
        
        if not self.enabled:
            logger.info("P2P Sharing Plugin: Disabled in configuration")
            return
        
        # Start the local proxy server
        self._start_proxy_server()
        logger.info(f"P2P Sharing Plugin: Proxy server started on {self.proxy_host}:{self.proxy_port}")

    def _load_config(self):
        """Load plugin configuration from /etc/dnf/libdnf-plugins/p2p-plugin.conf."""
        config_paths = [
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
        """Start the local P2P proxy server process."""
        try:
            # Get the directory where this plugin is installed
            plugin_dir = Path(__file__).parent.parent
            proxy_script = plugin_dir / "p2p-proxy-server" / "p2p_server.py"
            
            # Fallback to system-wide installation
            if not proxy_script.exists():
                proxy_script = Path("/usr/libexec/libdnf-p2p-sharing/p2p_server.py")
            
            if not proxy_script.exists():
                logger.warning(f"P2P Sharing Plugin: Proxy server script not found at {proxy_script}")
                return
            
            self.proxy_process = subprocess.Popen(
                [
                    sys.executable,
                    str(proxy_script),
                    f"--port={self.proxy_port}",
                    f"--host={self.proxy_host}",
                    f"--multicast-group={self.multicast_group}",
                    f"--multicast-port={self.multicast_port}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True  # Run in separate session so it survives plugin shutdown
            )
            logger.debug(f"P2P Sharing Plugin: Proxy server process started (PID: {self.proxy_process.pid})")
        except Exception as e:
            logger.error(f"P2P Sharing Plugin: Failed to start proxy server: {e}")

    def repos_loaded(self):
        """Hook called after repositories are loaded.
        
        Modifies repository base URLs to route through the local P2P proxy.
        """
        if not self.enabled:
            return
        
        try:
            logger.debug("P2P Sharing Plugin: repos_loaded hook called")
            
            # Discover peers on the local network
            peers = self._discover_peers()
            logger.debug(f"P2P Sharing Plugin: Discovered {len(peers)} peers")
            
            if peers or self.cache_enabled:
                # Inject local proxy as the primary download source
                self._inject_proxy_into_repos()
        except Exception as e:
            logger.error(f"P2P Sharing Plugin: Error in repos_loaded hook: {e}")

    def _discover_peers(self):
        """Query the local network for P2P peers using multicast.
        
        Returns:
            list: List of peer addresses (IP:port tuples)
        """
        # This will be implemented in p2p_peer_discovery.py
        # For now, return an empty list
        return []

    def _inject_proxy_into_repos(self):
        """Modify repository base URLs to use the local P2P proxy."""
        try:
            # Note: Direct manipulation of repo baseurls in libdnf5 may require
            # using the appropriate libdnf5 API. This is a placeholder for the logic.
            logger.debug("P2P Sharing Plugin: Injecting proxy into repository configurations")
            
            # TODO: Implement repo URL modification using libdnf5 API
            # This will likely involve iterating through available repos and
            # prepending the proxy URL or using mirror manipulation
        except Exception as e:
            logger.error(f"P2P Sharing Plugin: Failed to inject proxy into repos: {e}")

    def goal_resolved(self, transaction):
        """Hook called when a goal is resolved.
        
        Args:
            transaction: The transaction that was resolved.
        """
        if not self.enabled:
            return
        
        logger.debug("P2P Sharing Plugin: goal_resolved hook called")

    def finish(self):
        """Plugin cleanup - stop the proxy server."""
        logger.info("P2P Sharing Plugin: Finishing")
        
        if self.proxy_process:
            try:
                self.proxy_process.terminate()
                self.proxy_process.wait(timeout=5)
                logger.debug("P2P Sharing Plugin: Proxy server terminated gracefully")
            except subprocess.TimeoutExpired:
                self.proxy_process.kill()
                logger.warning("P2P Sharing Plugin: Proxy server killed forcefully")
            except Exception as e:
                logger.error(f"P2P Sharing Plugin: Error stopping proxy server: {e}")
