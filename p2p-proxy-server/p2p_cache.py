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

logger = logging.getLogger(__name__)


class P2PCache:
    """Manages the local package cache for P2P sharing."""

    def __init__(self, cache_dir: Path):
        """Initialize the cache manager.
        
        Args:
            cache_dir: Path to the cache directory
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index = {}  # {hash: cache_entry}
        self.lock = threading.RLock()
        self._load_cache_index()

    def _load_cache_index(self) -> None:
        """Load the cache index from disk."""
        try:
            index_file = self.cache_dir / ".p2p_index"
            if index_file.exists():
                import json
                with self.lock:
                    with open(index_file, 'r') as f:
                        self.index = json.load(f)
                logger.debug(f"Loaded cache index with {len(self.index)} entries")
        except Exception as e:
            logger.warning(f"Failed to load cache index: {e}")
            with self.lock:
                self.index = {}

    def _save_cache_index(self) -> None:
        """Save the cache index to disk."""
        try:
            import json
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

    def add_to_cache(self, file_path: Path, package_hash: str, package_info: Dict) -> bool:
        """Add a package file to the cache.
        
        Args:
            file_path: Path to the package file
            package_hash: Hash of the package (for verification)
            package_info: Dictionary with package metadata
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if not file_path.exists():
                logger.error(f"File not found: {file_path}")
                return False
            
            # Verify the hash
            file_hash = self.get_file_hash(file_path)
            if file_hash != package_hash:
                logger.warning(f"Hash mismatch for {file_path}: {file_hash} != {package_hash}")
                return False
            
            # Copy to cache
            cache_file = self.cache_dir / file_path.name
            if not cache_file.exists():
                import shutil
                shutil.copy2(file_path, cache_file)
                logger.debug(f"Added to cache: {cache_file}")
            
            # Update index
            with self.lock:
                self.index[package_hash] = {
                    "filename": file_path.name,
                    "size": file_path.stat().st_size,
                    **package_info
                }
                self._save_cache_index()
            return True
        except Exception as e:
            logger.error(f"Failed to add file to cache: {e}")
            return False

    def get_cached_file(self, package_hash: str) -> Optional[Path]:
        """Get a cached file by its hash.
        
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
                        return cache_file
                    else:
                        logger.warning(f"Cached file no longer exists: {cache_file}")
                        del self.index[package_hash]
                        self._save_cache_index()
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

