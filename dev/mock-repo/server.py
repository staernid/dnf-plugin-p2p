#!/usr/bin/env python3
import http.server
import os
import subprocess
import socketserver
import sys
from pathlib import Path

REPO_DIR = Path("/repo")
PORT = 8080

def build_test_rpm_and_repo():
    REPO_DIR.mkdir(parents=True, exist_ok=True)
    rpms_dir = REPO_DIR / "packages"
    rpms_dir.mkdir(exist_ok=True)

    rpm_path = rpms_dir / "test-p2p-pkg-1.0.0-1.fc44.noarch.rpm"
    if not rpm_path.exists():
        print("[mock-repo] Building test RPM...")
        spec_content = """
Name: test-p2p-pkg
Version: 1.0.0
Release: 1.fc44
Summary: Test package for dnf-plugin-p2p
License: MIT
BuildArch: noarch

%description
A test RPM package for validating dnf-plugin-p2p transfers.

%install
mkdir -p %{buildroot}/usr/share/test-p2p
echo "Hello from dnf-plugin-p2p automated testing!" > %{buildroot}/usr/share/test-p2p/hello.txt

%files
/usr/share/test-p2p/hello.txt
"""
        spec_file = Path("/tmp/test-p2p-pkg.spec")
        spec_file.write_text(spec_content)
        
        build_topdir = Path("/tmp/rpmbuild")
        build_topdir.mkdir(exist_ok=True)
        for d in ["BUILD", "RPMS", "SOURCES", "SPECS", "SRPMS"]:
            (build_topdir / d).mkdir(exist_ok=True)

        res = subprocess.run([
            "rpmbuild",
            "--define", f"_topdir {build_topdir}",
            "-bb", str(spec_file)
        ], capture_output=True, text=True)

        if res.returncode != 0:
            print(f"[mock-repo] Error building RPM: {res.stderr}", file=sys.stderr)
            sys.exit(1)

        built_rpms = list((build_topdir / "RPMS").glob("*/*.rpm"))
        if not built_rpms:
            print("[mock-repo] No RPM built!", file=sys.stderr)
            sys.exit(1)

        import shutil
        shutil.copy(built_rpms[0], rpm_path)
        print(f"[mock-repo] Generated RPM: {rpm_path.name}")

    print("[mock-repo] Generating repodata with createrepo_c...")
    subprocess.run(["createrepo_c", str(REPO_DIR)], check=True)
    print("[mock-repo] Repodata generated.")

class DualDirectoryHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_DIR), **kwargs)

    def log_message(self, format, *args):
        print(f"[mock-repo HTTP] {args[0]} - {args[1]}")

def main():
    import signal
    build_test_rpm_and_repo()
    os.chdir(str(REPO_DIR))
    with socketserver.TCPServer(("", PORT), DualDirectoryHandler) as httpd:
        def shutdown_handler(signum, frame):
            print("[mock-repo] Shutting down...")
            threading.Thread(target=httpd.shutdown).start()
        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGINT, shutdown_handler)
        print(f"[mock-repo] Serving repository at http://0.0.0.0:{PORT}/ ...")
        httpd.serve_forever()

if __name__ == "__main__":
    import threading
    main()
