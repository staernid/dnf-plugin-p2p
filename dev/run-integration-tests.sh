#!/usr/bin/env bash
# run-integration-tests.sh - Automated multi-node integration test runner for dnf-plugin-p2p
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/compose.yaml"

# Determine compose command (docker compose or podman-compose)
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose -f $COMPOSE_FILE"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose -f $COMPOSE_FILE"
elif command -v podman-compose >/dev/null 2>&1; then
    COMPOSE="podman-compose -f $COMPOSE_FILE"
else
    echo "Error: neither docker compose nor podman-compose found."
    exit 1
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

pass_count=0
fail_count=0

assert_step() {
    local name="$1"
    local status="$2"
    local details="$3"

    if [ "$status" -eq 0 ]; then
        echo -e "${GREEN}✓ PASS:${NC} $name"
        pass_count=$((pass_count + 1))
    else
        echo -e "${RED}✗ FAIL:${NC} $name"
        if [ -n "$details" ]; then
            echo -e "  ${YELLOW}Details:${NC} $details"
        fi
        fail_count=$((fail_count + 1))
    fi
}

echo -e "${BLUE}=== Starting DNF P2P Integration Test Environment ===${NC}"
$COMPOSE up -d --build

cleanup() {
    if [ "${PRESERVE_CONTAINERS:-0}" != "1" ]; then
        echo -e "\n${BLUE}=== Cleaning up containers ===${NC}"
        $COMPOSE down -v
    else
        echo -e "\n${YELLOW}Preserving containers as requested (PRESERVE_CONTAINERS=1)${NC}"
    fi
}
trap cleanup EXIT

echo -e "\n${BLUE}=== Step 1: Health & Ping Verification ===${NC}"
# Wait for mock-repo
echo "Waiting for mock-repo..."
repo_ready=0
for i in {1..20}; do
    if docker exec dnf-p2p-peer1 curl -s http://mock-repo:8080/repodata/repomd.xml | grep -q "revision" >/dev/null 2>&1; then
        repo_ready=1
        break
    fi
    sleep 1
done
assert_step "Mock RPM repository is healthy and serving repodata" "$([ $repo_ready -eq 1 ] && echo 0 || echo 1)"

# Wait for peer1, peer2, and peer3 proxy daemons
echo "Waiting for proxy daemons on peer1, peer2, and peer3..."
peer1_ready=0
peer2_ready=0
peer3_ready=0
for i in {1..20}; do
    if docker exec dnf-p2p-peer1 curl -s --max-time 1 http://127.0.0.1:8888/ping 2>/dev/null | grep -q "pong"; then
        peer1_ready=1
    fi
    if docker exec dnf-p2p-peer2 curl -s --max-time 1 http://127.0.0.1:8888/ping 2>/dev/null | grep -q "pong"; then
        peer2_ready=1
    fi
    if docker exec dnf-p2p-peer3 curl -s --max-time 1 http://127.0.0.1:8888/ping 2>/dev/null | grep -q "pong"; then
        peer3_ready=1
    fi
    if [ $peer1_ready -eq 1 ] && [ $peer2_ready -eq 1 ] && [ $peer3_ready -eq 1 ]; then
        break
    fi
    sleep 1
done
assert_step "Peer 1 proxy daemon active and responding pong" "$([ $peer1_ready -eq 1 ] && echo 0 || echo 1)"
assert_step "Peer 2 proxy daemon active and responding pong" "$([ $peer2_ready -eq 1 ] && echo 0 || echo 1)"
assert_step "Peer 3 proxy daemon active and responding pong" "$([ $peer3_ready -eq 1 ] && echo 0 || echo 1)"

echo -e "\n${BLUE}=== Step 2: mDNS & libp2p Peer Discovery (3-Node Mesh) ===${NC}"
echo "Waiting for peer1, peer2, and peer3 to discover each other via mDNS..."
discovery_ok=0
for i in {1..25}; do
    p1_peers=$(docker exec dnf-p2p-peer1 curl -s http://127.0.0.1:8888/stats 2>/dev/null | grep -o '"discovered_peers": [0-9]*' | awk '{print $2}' || echo "0")
    p2_peers=$(docker exec dnf-p2p-peer2 curl -s http://127.0.0.1:8888/stats 2>/dev/null | grep -o '"discovered_peers": [0-9]*' | awk '{print $2}' || echo "0")
    p3_peers=$(docker exec dnf-p2p-peer3 curl -s http://127.0.0.1:8888/stats 2>/dev/null | grep -o '"discovered_peers": [0-9]*' | awk '{print $2}' || echo "0")
    if [ "${p1_peers:-0}" -ge 2 ] && [ "${p2_peers:-0}" -ge 2 ] && [ "${p3_peers:-0}" -ge 2 ]; then
        discovery_ok=1
        break
    fi
    sleep 1
done
assert_step "3-Node mDNS discovery mesh (peer1=$p1_peers, peer2=$p2_peers, peer3=$p3_peers)" "$([ $discovery_ok -eq 1 ] && echo 0 || echo 1)"

echo -e "\n${BLUE}=== Step 3: Diagnostic Package Sharing Test ===${NC}"
TEST_CONTENT="TEST_RPM_PAYLOAD_$(date +%s)_$RANDOM"
TEST_FILENAME="test-diag-pkg-$RANDOM.rpm"

# Seed test file on peer1
docker exec dnf-p2p-peer1 bash -c "echo -n '$TEST_CONTENT' > /var/cache/dnf-plugin-p2p/$TEST_FILENAME"
TEST_HASH=$(docker exec dnf-p2p-peer1 sha256sum "/var/cache/dnf-plugin-p2p/$TEST_FILENAME" | awk '{print $1}')
echo "Seeded $TEST_FILENAME ($TEST_HASH) in peer1 cache"

# Request from peer2 using dnf-p2p-client
transfer_out=$(docker exec dnf-p2p-peer2 dnf-p2p-client test-transfer \
    --filename "$TEST_FILENAME" \
    --hash "$TEST_HASH" \
    --expected-content "$TEST_CONTENT" 2>&1 || true)

transfer_status=1
if echo "$transfer_out" | grep -q "VERIFIED"; then
    transfer_status=0
fi
assert_step "Peer 2 downloads and verifies seeded package from Peer 1" "$transfer_status" "$transfer_out"

echo -e "\n${BLUE}=== Step 4: Real DNF 5 Transaction via Plugin ===${NC}"
# Step 4a: Cache the real mock RPM on peer1
echo "Fetching test-p2p-pkg into peer1 cache..."
docker exec dnf-p2p-peer1 dnf5 download --destdir=/var/cache/dnf-plugin-p2p -y test-p2p-pkg >/dev/null 2>&1
cached_rpm=$(docker exec dnf-p2p-peer1 ls /var/cache/dnf-plugin-p2p | grep "test-p2p-pkg" || true)
echo "Cached in peer1: $cached_rpm"

# Step 4b: Install on peer2 via DNF 5
echo "Installing test-p2p-pkg on peer2 via dnf5 install..."
dnf_out=$(docker exec dnf-p2p-peer2 dnf5 install -y test-p2p-pkg 2>&1 || true)
install_ok=0
if docker exec dnf-p2p-peer2 rpm -q test-p2p-pkg >/dev/null 2>&1; then
    install_ok=1
fi
assert_step "Peer 2 installs test-p2p-pkg via DNF 5 through P2P plugin" "$([ $install_ok -eq 1 ] && echo 0 || echo 1)" "$dnf_out"

# Verify installed payload
installed_text=$(docker exec dnf-p2p-peer2 cat /usr/share/test-p2p/hello.txt 2>/dev/null || echo "")
hello_ok=0
if echo "$installed_text" | grep -q "Hello from dnf-plugin-p2p"; then
    hello_ok=1
fi
assert_step "Installed RPM payload verified on peer2" "$([ $hello_ok -eq 1 ] && echo 0 || echo 1)"

echo -e "\n${BLUE}=== Step 5: Bandwidth & Transfer Stats ===${NC}"
p2_stats=$(docker exec dnf-p2p-peer2 dnf-p2p-client status 2>&1 || true)
echo "$p2_stats"
stats_ok=0
if echo "$p2_stats" | grep -q "Bandwidth Saved"; then
    stats_ok=1
fi
assert_step "Peer 2 statistics show bandwidth metrics" "$([ $stats_ok -eq 1 ] && echo 0 || echo 1)"

echo -e "\n${BLUE}=== Step 6: Hostile / Corrupt Peer Fallback Verification ===${NC}"
CORRUPT_FILENAME="test-corrupt-payload-$RANDOM.rpm"
docker exec dnf-p2p-peer1 bash -c "echo -n 'CORRUPTED_GARBAGE_BYTES' > /var/cache/dnf-plugin-p2p/$CORRUPT_FILENAME"
GENUINE_CONTENT="GENUINE_CLEAN_RPM_CONTENT_$RANDOM"
docker exec dnf-p2p-mock-repo bash -c "echo -n '$GENUINE_CONTENT' > /repo/packages/$CORRUPT_FILENAME"
GENUINE_HASH=$(docker exec dnf-p2p-mock-repo sha256sum "/repo/packages/$CORRUPT_FILENAME" | awk '{print $1}')

# Register expected genuine hash on peer2: dictionary of {filename: hash}
docker exec dnf-p2p-peer2 curl -s -X POST -H "Content-Type: application/json" \
    -d "{\"$CORRUPT_FILENAME\": \"$GENUINE_HASH\"}" \
    http://127.0.0.1:8888/expected_hashes >/dev/null 2>&1 || true

# Peer 2 requests the package through its proxy with remote_url fallback
fallback_content=$(docker exec dnf-p2p-peer2 curl -s \
    "http://127.0.0.1:8888/packages/$CORRUPT_FILENAME?remote_url=http://mock-repo:8080/packages/$CORRUPT_FILENAME" || true)

fallback_ok=0
if [ "$fallback_content" = "$GENUINE_CONTENT" ]; then
    fallback_ok=1
fi
assert_step "Peer 2 rejects corrupted peer bytes and seamlessly falls back to upstream mirror" "$([ $fallback_ok -eq 1 ] && echo 0 || echo 1)"

echo -e "\n${BLUE}=== Step 7: Cache Eviction Under Pressure Verification ===${NC}"
evict_test_out=$(docker exec dnf-p2p-peer2 python3 -c "
import tempfile
from pathlib import Path
import sys
sys.path.append('/usr/libexec/dnf-plugin-p2p')
from p2p_cache import P2PCache

with tempfile.TemporaryDirectory() as td:
    cache = P2PCache(Path(td), max_cache_size_mb=1, max_disk_usage_percent=0)
    f1 = Path(td) / 'pkg1.rpm'
    f1.write_bytes(b'A' * 600 * 1024)
    cache.add_to_cache(f1)
    f2 = Path(td) / 'pkg2.rpm'
    f2.write_bytes(b'B' * 600 * 1024)
    cache.add_to_cache(f2)
    # pkg1 should be evicted because 1.2MB > 1MB
    assert cache.lookup_filename('pkg1.rpm') is None
    assert cache.lookup_filename('pkg2.rpm') is not None
print('CACHE_EVICTION_VERIFIED')
" 2>&1 || true)

evict_ok=0
if echo "$evict_test_out" | grep -q "CACHE_EVICTION_VERIFIED"; then
    evict_ok=1
fi
assert_step "Cache eviction under size pressure evicts oldest entries without error" "$([ $evict_ok -eq 1 ] && echo 0 || echo 1)" "$evict_test_out"

echo -e "\n${BLUE}=== Step 8: Remote Only Resilience ===${NC}"
REMOTE_PKG="test-remote-only-$RANDOM.rpm"
docker exec dnf-p2p-mock-repo bash -c "echo -n 'REMOTE_PKG_DATA' > /repo/packages/$REMOTE_PKG"
resilient_status=$(docker exec dnf-p2p-peer2 curl -s -o /dev/null -w "%{http_code}" \
    "http://127.0.0.1:8888/packages/$REMOTE_PKG?remote_url=http://mock-repo:8080/packages/$REMOTE_PKG" || true)

resilient_ok=0
if [ "$resilient_status" = "200" ]; then
    resilient_ok=1
fi
assert_step "Peer proxy handles non-peer files with clean remote fallback (HTTP 200)" "$([ $resilient_ok -eq 1 ] && echo 0 || echo 1)"


echo -e "\n${BLUE}=======================================${NC}"
echo -e "${BLUE}       INTEGRATION TEST SUMMARY        ${NC}"
echo -e "${BLUE}=======================================${NC}"
echo -e "Total: $((pass_count + fail_count)) | ${GREEN}Passed: $pass_count${NC} | ${RED}Failed: $fail_count${NC}"

if [ "$fail_count" -gt 0 ]; then
    echo -e "\n${RED}FAILURE: Some integration tests failed!${NC}"
    echo "Dumping recent proxy logs from peer1:"
    docker exec dnf-p2p-peer1 tail -n 30 /var/log/p2p-proxy.log 2>/dev/null || true
    echo "Dumping recent proxy logs from peer2:"
    docker exec dnf-p2p-peer2 tail -n 30 /var/log/p2p-proxy.log 2>/dev/null || true
    echo "Dumping recent proxy logs from peer3:"
    docker exec dnf-p2p-peer3 tail -n 30 /var/log/p2p-proxy.log 2>/dev/null || true
    exit 1
else
    echo -e "\n${GREEN}SUCCESS: All integration tests passed cleanly!${NC}"
    exit 0
fi
