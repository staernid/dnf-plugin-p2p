#!/usr/bin/env python3
# p2p_cache.py - Local package cache management for P2P sharing
#
# Copyright (C) 2024 libdnf-p2p-sharing contributors
# Licensed under GNU General Public License v2.0 or later
#

import logging
import hashlib
import threading
from pathlib import Path
from typing import Optional, Dict, List
import os
import json
import time
import shutil

logger = logging.getLogger(__name__)


class P2PCache:
    """Manages the local package cache for P2P sharing with LRU eviction."""

    def __init__(self, cache_dir: Path, max_cache_size_mb: int = 1024, max_disk_usage_percent: float = 90.0):
        """Initialize the cache manager.
        
        Args:
            cache_dir: Path to the cache directory
            max_cache_size_mb: Maximum cache size in MB (0 or less to disable)
            max_disk_usage_percent: Maximum disk usage percentage (0 or less to disable)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_cache_size_mb = max_cache_size_mb
        self.max_disk_usage_percent = max_disk_usage_percent
        self.index = {}  # {hash: cache_entry}
        self.lock = threading.RLock()
        self._load_cache_index()

    def _load_cache_index(self) -> None:
        """Load the cache index from disk."""
        try:
            index_file = self.cache_dir / ".p2p_index"
            if index_file.exists():
                with self.lock:
                    with open(index_file, 'r') as f:
                        self.index = json.load(f)
                
                # Check and populate missing metadata for integrity
                modified = False
                with self.lock:
                    for package_hash, info in list(self.index.items()):
                        filename = info.get("filename")
                        if not filename:
                            del self.index[package_hash]
                            modified = True
                            continue
                        
                        cache_file = self.cache_dir / filename
                        if not cache_file.exists():
                            del self.index[package_hash]
                            modified = True
                            continue
                        
                        if "size" not in info:
                            info["size"] = cache_file.stat().st_size
                            modified = True
                        
                        if "last_accessed" not in info:
                            info["last_accessed"] = cache_file.stat().st_mtime
                            modified = True
                    
                    if modified:
                        self._save_cache_index()
                        
                logger.debug(f"Loaded cache index with {len(self.index)} entries")
        except Exception as e:
            logger.warning(f"Failed to load cache index: {e}")
            with self.lock:
                self.index = {}

    def _save_cache_index(self) -> None:
        """Save the cache index to disk."""
        try:
            index_file = self.cache_dir / ".p2p_index"
            with self.lock:
                with open(index_file, 'w') as f:
                    json.dump(self.index, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save cache index: {e}")

    def get_file_hash(self, file_path: Path, algorithm: str = "sha256") -> str:
        """Calculate the hash of a file.
        
        Args:
            file_path: Path to the file
            algorithm: Hash algorithm to use (default: sha256)
        
        Returns:
            Hex digest of the file hash
        """
        try:
            hasher = hashlib.new(algorithm)
            with open(file_path, 'rb') as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            logger.error(f"Failed to calculate hash for {file_path}: {e}")
            return None

    def add_to_cache(self, file_path: Path, package_hash: Optional[str] = None, package_info: Optional[Dict] = None) -> bool:
        """Add a package file to the cache.
        
        Args:
            file_path: Path to the package file
            package_hash: Hash of the package (optional, for verification)
            package_info: Dictionary with package metadata (optional)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if not file_path.exists():
                logger.error(f"File not found: {file_path}")
                return False
            
            # Calculate and verify the hash
            file_hash = self.get_file_hash(file_path)
            if file_hash is None:
                return False
            
            if package_hash is not None and file_hash != package_hash:
                logger.warning(f"Hash mismatch for {file_path}: {file_hash} != {package_hash}")
                return False
            
            # Copy to cache
            cache_file = self.cache_dir / file_path.name
            if not cache_file.exists():
                shutil.copy2(file_path, cache_file)
                logger.debug(f"Added to cache: {cache_file}")
            
            # Update index
            with self.lock:
                self.index[file_hash] = {
                    "filename": file_path.name,
                    "size": file_path.stat().st_size,
                    "last_accessed": time.time(),
                    **(package_info or {})
                }
                self.evict_if_needed()
                self._save_cache_index()
            return True
        except Exception as e:
            logger.error(f"Failed to add file to cache: {e}")
            return False

    def get_cached_file(self, package_hash: str) -> Optional[Path]:
        """Get a cached file by its hash and update its last accessed time.
        
        Args:
            package_hash: Hash of the package
        
        Returns:
            Path to the cached file, or None if not found
        """
        with self.lock:
            if package_hash in self.index:
                filename = self.index[package_hash].get("filename")
                if filename:
                    cache_file = self.cache_dir / filename
                    if cache_file.exists():
                        self.index[package_hash]["last_accessed"] = time.time()
                        self._save_cache_index()
                        return cache_file
                    else:
                        logger.warning(f"Cached file no longer exists: {cache_file}")
                        del self.index[package_hash]
                        self._save_cache_index()
        return None

    def get_cached_file_by_name(self, filename: str) -> Optional[Path]:
        """Get a cached file by its filename and update its last accessed time.
        
        Args:
            filename: Name of the package file
            
        Returns:
            Path to the cached file, or None if not found
        """
        with self.lock:
            for package_hash, info in self.index.items():
                if info.get("filename") == filename:
                    cache_file = self.cache_dir / filename
                    if cache_file.exists():
                        info["last_accessed"] = time.time()
                        self._save_cache_index()
                        return cache_file
                    else:
                        logger.warning(f"Cached file no longer exists: {cache_file}")
                        del self.index[package_hash]
                        self._save_cache_index()
                        return None
            
            # Fallback check on disk (if file exists but index missed it)
            cache_file = self.cache_dir / filename
            if cache_file.exists():
                file_hash = self.get_file_hash(cache_file)
                if file_hash:
                    self.index[file_hash] = {
                        "filename": filename,
                        "size": cache_file.stat().st_size,
                        "last_accessed": time.time()
                    }
                    self._save_cache_index()
                    return cache_file
        return None

    def lookup_filename(self, filename: str) -> Optional[Dict]:
        """Look up a package in the cache by its filename.
        
        Args:
            filename: Name of the package file
            
        Returns:
            Dict containing 'hash' and 'size' if found, else None
        """
        with self.lock:
            for package_hash, info in list(self.index.items()):
                if info.get("filename") == filename:
                    cache_file = self.cache_dir / filename
                    if cache_file.exists():
                        info["last_accessed"] = time.time()
                        self._save_cache_index()
                        return {
                            "hash": package_hash,
                            "size": info.get("size", 0)
                        }
                    else:
                        logger.warning(f"Cached file no longer exists: {cache_file}")
                        try:
                            del self.index[package_hash]
                            self._save_cache_index()
                        except KeyError:
                            pass
                        break
        return None

    def list_cached_files(self) -> List[Dict]:
        """Get a list of all cached files.
        
        Returns:
            List of cache entries with metadata
        """
        with self.lock:
            entries = []
            for hash_val, info in self.index.items():
                cache_file = self.cache_dir / info["filename"]
                if cache_file.exists():
                    entries.append({
                        "hash": hash_val,
                        "path": str(cache_file),
                        **info
                    })
            return entries

    def get_disk_usage_percent(self) -> float:
        """Get the disk usage percentage of the file system containing cache_dir."""
        try:
            usage = shutil.disk_usage(self.cache_dir)
            return (usage.used / usage.total) * 100.0
        except Exception as e:
            logger.warning(f"Failed to get disk usage: {e}")
            return 0.0

    def evict_if_needed(self) -> None:
        """Evict cached files based on LRU policy when limits are exceeded."""
        with self.lock:
            # Sort entries by last_accessed ascending (oldest first)
            # We filter only existing files
            valid_entries = []
            for package_hash, info in list(self.index.items()):
                filename = info.get("filename")
                if filename:
                    cache_file = self.cache_dir / filename
                    if cache_file.exists():
                        valid_entries.append((package_hash, info))
                    else:
                        del self.index[package_hash]
            
            # Sort valid entries by last_accessed time
            valid_entries.sort(key=lambda x: x[1].get("last_accessed", 0))
            
            # Calculate total cache size
            total_size = sum(info.get("size", 0) for _, info in valid_entries)
            
            max_size_bytes = self.max_cache_size_mb * 1024 * 1024
            evicted_count = 0
            
            for package_hash, info in valid_entries:
                # Check if we are within limits
                size_limit_ok = (self.max_cache_size_mb <= 0) or (total_size <= max_size_bytes)
                disk_limit_ok = True
                if self.max_disk_usage_percent > 0:
                    disk_limit_ok = (self.get_disk_usage_percent() <= self.max_disk_usage_percent)
                
                if size_limit_ok and disk_limit_ok:
                    break
                
                # Evict this entry
                filename = info.get("filename")
                cache_file = self.cache_dir / filename
                try:
                    if cache_file.exists():
                        file_size = info.get("size", cache_file.stat().st_size)
                        cache_file.unlink()
                        total_size -= file_size
                        logger.info(f"Evicted from cache (LRU): {filename} ({file_size} bytes)")
                    del self.index[package_hash]
                    evicted_count += 1
                except Exception as e:
                    logger.error(f"Failed to evict {filename}: {e}")
            
            if evicted_count > 0:
                self._save_cache_index()

