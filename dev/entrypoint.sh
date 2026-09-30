#!/bin/bash
set -e

# Link py-libp2p in editable mode if not already installed
if [ -d "/workspace/py-libp2p-src" ] && ! python3 -c "import libp2p" >/dev/null 2>&1; then
    echo "[entrypoint] Installing py-libp2p-src in editable mode..."
    pip3 install --break-system-packages --no-deps -e /workspace/py-libp2p-src >/dev/null 2>&1 || true
fi

# Detect python site-packages path
PYTHON_LIB=$(python3 -c "import site; print(site.getsitepackages()[0])")

# Ensure target directories exist
mkdir -p "$PYTHON_LIB/libdnf_plugins"
mkdir -p /etc/dnf/libdnf5-plugins/python_plugins_loader.d
mkdir -p /usr/libexec/dnf-plugin-p2p
mkdir -p /var/cache/dnf-plugin-p2p
mkdir -p /var/log

# Link plugin into python loader path
ln -sf /workspace/plugins/p2p_plugin.py "$PYTHON_LIB/libdnf_plugins/p2p_plugin.py"
ln -sfn /workspace/plugins/libdnf_p2p_sharing "$PYTHON_LIB/libdnf_p2p_sharing"

# Link configuration
if [ -f /workspace/etc/p2p_plugin.conf ]; then
    ln -sf /workspace/etc/p2p_plugin.conf /etc/dnf/libdnf5-plugins/python_plugins_loader.d/p2p_plugin.conf
elif [ -f /workspace/etc/p2p-plugin.conf ]; then
    ln -sf /workspace/etc/p2p-plugin.conf /etc/dnf/libdnf5-plugins/python_plugins_loader.d/p2p_plugin.conf
fi

# Link proxy daemon and helper client
ln -sf /workspace/p2p-proxy-server/p2p_server.py /usr/libexec/dnf-plugin-p2p/p2p_server.py
ln -sf /workspace/p2p-proxy-server/p2p_cache.py /usr/libexec/dnf-plugin-p2p/p2p_cache.py
ln -sf /workspace/p2p-proxy-server/p2p_libp2p.py /usr/libexec/dnf-plugin-p2p/p2p_libp2p.py
ln -sf /workspace/p2p-proxy-server/__init__.py /usr/libexec/dnf-plugin-p2p/__init__.py
ln -sf /workspace/p2p-proxy-server/dnf-p2p-client /usr/bin/dnf-p2p-client
chmod +x /usr/bin/dnf-p2p-client

# Execute custom command if provided
if [ $# -gt 0 ]; then
    exec "$@"
fi

# Default: start proxy daemon and tail logs
echo "[entrypoint] Starting dnf-p2p-proxy daemon on $(hostname)..."
python3 /usr/libexec/dnf-plugin-p2p/p2p_server.py --host 0.0.0.0 --debug >> /var/log/p2p-proxy.log 2>&1 &
PROXY_PID=$!
echo "[entrypoint] Proxy server started with PID $PROXY_PID"

# Trap termination signals to stop cleanly
trap "echo '[entrypoint] Shutting down...'; kill -TERM $PROXY_PID 2>/dev/null; exit 0" SIGTERM SIGINT

# Keep container alive and follow logs
tail -f /var/log/p2p-proxy.log &
wait $PROXY_PID
