%{!?dnf_lowest_compatible: %global dnf_lowest_compatible 4.4.3}

Name:           libdnf-p2p-sharing
Version:        0.1.0
Release:        1%{?dist}
Summary:        Peer-to-peer package sharing plugin for libdnf5
License:        GPL-2.0-or-later
URL:            https://github.com/staernid/libdnf-p2p-sharing
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz

BuildRequires:  cmake >= 3.5.0
BuildRequires:  python3-devel
BuildRequires:  python3-pip
BuildRequires:  python3-wheel
BuildRequires:  python3-setuptools
BuildRequires:  python3-hatchling
BuildRequires:  gcc
BuildRequires:  gmp-devel
BuildRequires:  systemd-rpm-macros

%description
Peer-to-peer package sharing plugin for libdnf5.

%package -n python3-libdnf5-plugin-p2p-sharing
Summary:        P2P sharing plugin for libdnf5
BuildArch:      noarch
Requires:       python3-libdnf5
Requires:       python3-%{name}-common = %{version}-%{release}
Requires:       %{name}-proxy = %{version}-%{release}
Provides:       dnf-plugin-p2p = %{version}-%{release}
Provides:       dnf5-plugin-p2p = %{version}-%{release}
Provides:       python3-dnf5-plugin-p2p = %{version}-%{release}

%description -n python3-libdnf5-plugin-p2p-sharing
This package contains the P2P package sharing plugin for libdnf5.

%package -n python3-%{name}-common
Summary:        Common Python modules for libdnf-p2p-sharing
BuildArch:      noarch

%description -n python3-%{name}-common
This package contains the shared Python modules used by the libdnf5 P2P plugin
and the P2P proxy server.

%package proxy
Summary:        P2P proxy server daemon for libdnf-p2p-sharing
Requires:       python3-trio
Requires:       python3-multiaddr
Requires:       python3-aioquic
Requires:       python3-anyio
Requires:       python3-base58
Requires:       python3-cbor2
Requires:       python3-coincurve
Requires:       python3-noiseprotocol
Requires:       python3-protobuf
Requires:       python3-pycryptodome
Requires:       python3-pynacl
Requires:       python3-requests
Requires:       python3-zeroconf
Requires:       python3-trio-websocket
Requires:       python3-morphys
Requires:       python3-lru-dict

%description proxy
This package contains the local P2P proxy server daemon.

%prep
%autosetup

%build
%cmake
%cmake_build

%install
%cmake_install

# Install bundled python dependencies directly into the libexec plugin folder
python3 -m pip install \
    --no-index \
    --find-links=bundled-deps/ \
    --target=%{buildroot}%{_libexecdir}/libdnf-p2p-sharing \
    --no-build-isolation \
    --no-deps \
    fastecdsa py-multibase py-multihash py-multicodec py-cid trio-typing rpcudp libp2p

%files -n python3-libdnf5-plugin-p2p-sharing
%config(noreplace) %{_sysconfdir}/dnf/libdnf5-plugins/python_plugins_loader.d/p2p_plugin.conf
%{_sysconfdir}/profile.d/libdnf-python-plugin.sh
%{python3_sitelib}/libdnf_plugins/p2p_plugin.py
%{python3_sitelib}/libdnf_plugins/__pycache__/p2p_plugin*.pyc

%files -n python3-%{name}-common
%{python3_sitelib}/libdnf_p2p_sharing/

%files proxy
%{_libexecdir}/libdnf-p2p-sharing/
%{_unitdir}/dnf-p2p-proxy.service

%post proxy
%systemd_post dnf-p2p-proxy.service

%preun proxy
%systemd_preun dnf-p2p-proxy.service

%postun proxy
%systemd_postun_with_restart dnf-p2p-proxy.service

%changelog
* Thu Jun 18 2026 libdnf-p2p-sharing contributors - 0.1.0-1
- Initial package release with systemd socket activation and python_plugins_loader updates.
