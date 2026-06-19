%global debug_package %{nil}
%{!?dnf_lowest_compatible: %global dnf_lowest_compatible 4.4.3}

Name:           libdnf-p2p-sharing
Version:        0.1.0
Release:        1%{?dist}
Summary:        Peer-to-peer package sharing plugin for libdnf5
License:        GPL-2.0-or-later
URL:            https://github.com/staernid/libdnf-p2p-sharing
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz
Source1:        https://files.pythonhosted.org/packages/fc/21/d5585856169c595d99a596dd8000afae40053f9f5c955d8ec8fb2ec3247c/fastecdsa-2.3.2.tar.gz
Source2:        https://files.pythonhosted.org/packages/bc/52/5ed393ab49df7e3b03995d3c4e53bae1e8c2ca40909cf25a41b346c09a38/py_multibase-2.0.0.tar.gz
Source3:        https://files.pythonhosted.org/packages/11/3d/ed68b0eccd0654f7f3c163d9b3d428f903e5e3e884ab1f0d0a16ba6a4f11/py_multihash-3.0.0.tar.gz
Source4:        https://files.pythonhosted.org/packages/5e/26/ef24db0fbfec080b72c5ac4a1000da3a4d696a1e31862c695d683097a1b5/py_multicodec-1.0.0.tar.gz
Source5:        https://files.pythonhosted.org/packages/96/8e/68c2bd0346247570e8e01e8c170a0237884e95cdfa43989527b71adaa978/py_cid-0.5.0.tar.gz
Source6:        https://files.pythonhosted.org/packages/b5/74/a87aafa40ec3a37089148b859892cbe2eef08d132c816d58a60459be5337/trio-typing-0.10.0.tar.gz
Source7:        https://files.pythonhosted.org/packages/39/5b/99ee4dd6080d857f029ad209860d461305f5fba9fef2316548a1d131e4c2/rpcudp-5.0.1.tar.gz
Source8:        https://files.pythonhosted.org/packages/98/b7/3d6a5eb9f1788da09371ee1be08768b72fdcd956cee0f3f92a8ef1819862/libp2p-0.6.0.tar.gz

BuildRequires:  cmake >= 3.5.0
BuildRequires:  python3-sphinx
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

%package -n libdnf5-plugin-p2p-sharing
Summary:        P2P sharing plugin for libdnf5
BuildArch:      noarch
Requires:       python3-libdnf5-python-plugins-loader
Requires:       python3-%{name}-common = %{version}-%{release}
Requires:       %{name}-proxy = %{version}-%{release}
Provides:       dnf-plugin-p2p = %{version}-%{release}
Provides:       dnf5-plugin-p2p = %{version}-%{release}
Provides:       python3-dnf5-plugin-p2p = %{version}-%{release}
Provides:       python3-libdnf5-plugin-p2p-sharing = %{version}-%{release}
Obsoletes:      python3-libdnf5-plugin-p2p-sharing < %{version}-%{release}

%description -n libdnf5-plugin-p2p-sharing
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
Provides:       bundled(python3dist(fastecdsa)) = 2.3.2
Provides:       bundled(python3dist(py-multibase)) = 2.0.0
Provides:       bundled(python3dist(py-multihash)) = 3.0.0
Provides:       bundled(python3dist(py-multicodec)) = 1.0.0
Provides:       bundled(python3dist(py-cid)) = 0.5.0
Provides:       bundled(python3dist(trio-typing)) = 0.10.0
Provides:       bundled(python3dist(rpcudp)) = 5.0.1
Provides:       bundled(python3dist(libp2p)) = 0.6.0

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
# This pulls the pre-downloaded PyPI tarballs from %{_sourcedir}
python3 -m pip install \
    --no-index \
    --find-links=%{_sourcedir} \
    --target=%{buildroot}%{_libexecdir}/libdnf-p2p-sharing \
    --no-build-isolation \
    --no-deps \
    fastecdsa py-multibase py-multihash py-multicodec py-cid trio-typing rpcudp libp2p

%files -n libdnf5-plugin-p2p-sharing
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
