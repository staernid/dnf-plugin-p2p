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
