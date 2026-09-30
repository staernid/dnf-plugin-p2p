FROM fedora:44

# Install DNF5, plugin loader, python packages, build tools, and diagnostic utilities
RUN dnf5 install -y \
    dnf5 \
    dnf5-plugins \
    libdnf5 \
    libdnf5-cli \
    python3 \
    python3-devel \
    python3-pip \
    python3-libdnf5 \
    python3-libdnf5-python-plugins-loader \
    python3-aioquic \
    python3-anyio \
    python3-base58 \
    python3-cbor2 \
    python3-coincurve \
    python3-noiseprotocol \
    python3-pynacl \
    python3-requests \
    python3-zeroconf \
    python3-trio-websocket \
    python3-morphys \
    python3-lru-dict \
    python3-trio \
    python3-httpx \
    python3-netaddr \
    python3-dnspython \
    python3-psutil \
    gcc \
    gmp-devel \
    createrepo_c \
    rpm-build \
    iproute \
    iputils \
    procps-ng \
    curl \
    hostname \
    net-tools \
    && dnf5 clean all

# Install py-libp2p dependencies not available as native Fedora RPMs
RUN pip3 install --break-system-packages \
    miniupnpc \
    "multiaddr>=0.0.11" \
    "protobuf>=5" \
    fastecdsa \
    py-multibase \
    py-multihash \
    py-multicodec \
    py-cid \
    trio-typing \
    rpcudp \
    pycryptodome \
    hatchling \
    setuptools \
    pytest

# Create required cache, plugin, and libexec directories
RUN mkdir -p /var/cache/dnf-plugin-p2p \
    /usr/libexec/dnf-plugin-p2p \
    /etc/dnf/libdnf5-plugins/python_plugins_loader.d \
    /var/log \
    /workspace

WORKDIR /workspace

# Default command
CMD ["/workspace/dev/entrypoint.sh"]
