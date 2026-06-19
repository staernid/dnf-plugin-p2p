import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
from p2p_cache import P2PCache


@pytest.fixture
def temp_cache_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_add_to_cache_without_hash(temp_cache_dir):
    cache = P2PCache(temp_cache_dir)
    
    # Create a dummy package file to cache
    pkg_file = temp_cache_dir / "test-pkg-1.0-1.noarch.rpm"
    content = b"dummy rpm file content"
    pkg_file.write_bytes(content)
    
    # Pre-calculate hash
    expected_hash = cache.get_file_hash(pkg_file)
    
    # Spy on get_file_hash to check call count
    with patch.object(cache, "get_file_hash", wraps=cache.get_file_hash) as mock_get_hash:
        success = cache.add_to_cache(pkg_file, package_hash=None, package_info={"source": "http://mirror.example.com"})
        
        assert success is True
        mock_get_hash.assert_called_once()
        
        # Verify the file is in cache index and file copy exists in cache
        cached_file = cache.get_cached_file(expected_hash)
        assert cached_file is not None
        assert cached_file.exists()
        assert cached_file.read_bytes() == content


def test_add_to_cache_with_matching_hash(temp_cache_dir):
    cache = P2PCache(temp_cache_dir)
    
    pkg_file = temp_cache_dir / "test-pkg-2.0-1.noarch.rpm"
    content = b"dummy rpm file content 2"
    pkg_file.write_bytes(content)
    
    # Pre-calculate hash
    expected_hash = cache.get_file_hash(pkg_file)
    
    with patch.object(cache, "get_file_hash", wraps=cache.get_file_hash) as mock_get_hash:
        success = cache.add_to_cache(pkg_file, package_hash=expected_hash, package_info={"source": "http://mirror.example.com"})
        
        assert success is True
        # In add_to_cache, it should only call get_file_hash once.
        mock_get_hash.assert_called_once()
        
        cached_file = cache.get_cached_file(expected_hash)
        assert cached_file is not None
        assert cached_file.exists()


def test_add_to_cache_with_mismatching_hash(temp_cache_dir):
    cache = P2PCache(temp_cache_dir)
    
    pkg_file = temp_cache_dir / "test-pkg-3.0-1.noarch.rpm"
    content = b"dummy rpm file content 3"
    pkg_file.write_bytes(content)
    
    wrong_hash = "wrong_hash_value"
    
    with patch.object(cache, "get_file_hash", wraps=cache.get_file_hash) as mock_get_hash:
        success = cache.add_to_cache(pkg_file, package_hash=wrong_hash, package_info={"source": "http://mirror.example.com"})
        
        assert success is False
        mock_get_hash.assert_called_once()
        
        cached_file = cache.get_cached_file(wrong_hash)
        assert cached_file is None


def test_cache_lru_eviction_by_size(temp_cache_dir):
    # Set limit to 1 MB
    cache = P2PCache(temp_cache_dir, max_cache_size_mb=1, max_disk_usage_percent=0)
    
    # Create two files of 600 KB each
    file1 = temp_cache_dir / "pkg1.rpm"
    file1.write_bytes(b"a" * (600 * 1024))
    
    file2 = temp_cache_dir / "pkg2.rpm"
    file2.write_bytes(b"b" * (600 * 1024))
    
    # Add first file
    assert cache.add_to_cache(file1) is True
    hash1 = cache.get_file_hash(file1)
    assert cache.get_cached_file(hash1) is not None
    
    # Wait a bit or mock time to ensure distinct access times
    import time
    time.sleep(0.01)
    
    # Add second file (this should trigger eviction of file1)
    assert cache.add_to_cache(file2) is True
    hash2 = cache.get_file_hash(file2)
    
    # Verify file1 is evicted and file2 is present
    assert cache.get_cached_file(hash1) is None
    assert cache.get_cached_file(hash2) is not None


def test_get_cached_file_updates_lru(temp_cache_dir):
    # Set limit to 1 MB
    cache = P2PCache(temp_cache_dir, max_cache_size_mb=1, max_disk_usage_percent=0)
    
    # Create three files of 400 KB each (adding all three exceeds 1MB)
    file1 = temp_cache_dir / "pkg1.rpm"
    file1.write_bytes(b"a" * (400 * 1024))
    
    file2 = temp_cache_dir / "pkg2.rpm"
    file2.write_bytes(b"b" * (400 * 1024))
    
    file3 = temp_cache_dir / "pkg3.rpm"
    file3.write_bytes(b"c" * (400 * 1024))
    
    # Add file1 and file2
    assert cache.add_to_cache(file1) is True
    hash1 = cache.get_file_hash(file1)
    
    import time
    time.sleep(0.01)
    assert cache.add_to_cache(file2) is True
    hash2 = cache.get_file_hash(file2)
    
    # Access file1 to update its last_accessed time to be newer than file2
    time.sleep(0.01)
    assert cache.get_cached_file(hash1) is not None
    
    # Add file3 (this should trigger eviction of file2, since file1 was accessed more recently)
    time.sleep(0.01)
    assert cache.add_to_cache(file3) is True
    hash3 = cache.get_file_hash(file3)
    
    # Verify file2 is evicted, while file1 and file3 remain
    assert cache.get_cached_file(hash2) is None
    assert cache.get_cached_file(hash1) is not None
    assert cache.get_cached_file(hash3) is not None


def test_cache_lru_eviction_by_disk_usage(temp_cache_dir):
    cache = P2PCache(temp_cache_dir, max_cache_size_mb=0, max_disk_usage_percent=90.0)
    
    file1 = temp_cache_dir / "pkg1.rpm"
    file1.write_bytes(b"a" * 1024)
    
    assert cache.add_to_cache(file1) is True
    hash1 = cache.get_file_hash(file1)
    
    # Mock disk usage to return >90% usage first, then <=90% usage
    with patch.object(cache, "get_disk_usage_percent", side_effect=[95.0, 85.0]):
        # Adding a new file should trigger eviction due to high disk usage
        file2 = temp_cache_dir / "pkg2.rpm"
        file2.write_bytes(b"b" * 1024)
        
        assert cache.add_to_cache(file2) is True
        hash2 = cache.get_file_hash(file2)
        
        # Verify file1 (oldest) was evicted, but file2 remains
        assert cache.get_cached_file(hash1) is None
        assert cache.get_cached_file(hash2) is not None


def test_index_auto_healing(temp_cache_dir):
    # 1. Create a cache dir with a file
    pkg_file = temp_cache_dir / "test-pkg.rpm"
    pkg_file.write_bytes(b"test content")
    
    # 2. Write a corrupted/incomplete index file
    import json
    index_data = {
        "some_hash": {
            "filename": "test-pkg.rpm"
            # size and last_accessed are missing
        },
        "non_existent_hash": {
            "filename": "ghost.rpm",
            "size": 100,
            "last_accessed": 12345.0
        }
    }
    with open(temp_cache_dir / ".p2p_index", 'w') as f:
        json.dump(index_data, f)
        
    # 3. Instantiate cache - it should trigger healing
    cache = P2PCache(temp_cache_dir)
    
    # Verify non_existent_hash was deleted
    assert "non_existent_hash" not in cache.index
    
    # Verify some_hash was healed with size and last_accessed
    assert "some_hash" in cache.index
    assert cache.index["some_hash"]["size"] == pkg_file.stat().st_size
    assert "last_accessed" in cache.index["some_hash"]
