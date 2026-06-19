Usage
=====

Transparent Operation
---------------------

Once installed and configured, the P2P sharing plugin operates
transparently during standard DNF5 package management commands. No user
interaction or special parameters are required:

.. code-block:: bash

    sudo dnf install tmux
    sudo dnf upgrade

The plugin will automatically:

1. Route all enabled repositories through the local proxy.
2. Rewrite repository URLs in-memory to enable transparent interception.
3. Check the local cache and query LAN peers before downloading from
   upstream mirrors.


How It Works (User Perspective)
-------------------------------

1. **Plugin Initialization**: On every DNF operation, the plugin checks
   whether the local P2P proxy is running. If not and the command is run with
   root privileges, it starts the ``dnf-p2p-proxy.service``. When run as a
   non-root user, the auto-start is bypassed to prevent console Polkit authentication
   prompts. A ``/ping`` health check verifies the proxy is active and authentic
   before routing traffic; if the service is unavailable, the plugin transparently
   falls back to normal DNF behavior.

2. **Peer Discovery**: The proxy's ``py-libp2p`` node uses mDNS for
   automatic zero-configuration local peer discovery. No manual peer
   setup is needed.

3. **Package Downloads**: When DNF downloads a ``.rpm`` package:

   - The proxy checks its local cache first.
   - Then queries discovered peers via the libp2p network.
   - If a peer has the package, downloads it directly from the LAN.
   - Otherwise, downloads from upstream mirrors and caches it locally.

4. **Metadata**: Repository metadata (repodata, GPG keys, etc.) is always
   fetched fresh from upstream mirrors — it is never cached or shared
   via P2P to prevent staleness or signature issues.


Verifying P2P Operations
-------------------------

To verify that the proxy is intercepting requests and P2P is working,
check the systemd logs:

.. code-block:: bash

    journalctl -u dnf-p2p-proxy.service -f

You will see:

* ``Discovered peer: <PeerID> at [<Multiaddr>]`` — peers found on the LAN.
* ``GET request for <package>.rpm`` — package download intercepted.
* ``Peer <PeerID> at <IP>:<port> has package <filename>`` — peer has
  the package.
* ``Attempting to download <filename> from peer <IP>:<port>`` — P2P
  download in progress.
* ``Successfully cached <filename>`` — package cached for future peers.
* ``Downloading <filename> from remote mirror: <URL>`` — fallback to
  upstream (no peer had it).

Example log showing successful P2P transfer:

.. code-block:: text

    GET request for trader-7.21-1.fc44.x86_64.rpm
    Peer 16Uiu2HAm... at 192.168.178.29:8888 has package trader-7.21-1.fc44.x86_64.rpm
    Attempting to download trader-7.21-1.fc44.x86_64.rpm from peer 192.168.178.29:8888
    Successfully cached trader-7.21-1.fc44.x86_64.rpm


Troubleshooting
---------------

**Plugin prints debug messages during DNF operations**
    Set ``debug = false`` in ``p2p_plugin.conf`` under the ``[p2p]``
    section.

**Peers are discovered but connections fail**
    Ensure the libp2p port is set to ``8000`` (which is the default) and
    the proxy is configured to bind to ``0.0.0.0`` (via ``proxy_host`` in
    ``p2p_plugin.conf``) so it accepts incoming connections from the local
    network. See :doc:`configuration` for details.

**Metadata checksum errors (zchunk)**
    The plugin should automatically disable zchunk. If you see
    ``Unable to validate zchunk checksums`` errors, verify the updated
    plugin is installed.

**RPM Fusion checksum warnings**
    Warnings like ``Downloading successful, but checksum doesn't match``
    for RPM Fusion mirrors are pre-existing mirror sync issues, not
    caused by the plugin. DNF retries with other mirrors automatically.
