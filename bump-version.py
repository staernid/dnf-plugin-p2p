#!/usr/bin/env python3
"""
bump-version.py
Automates bumping the version string across all files in the dnf-plugin-p2p project.
Usage:
    python bump-version.py <new_version> [--author "Name <email>"]
"""

import sys
import re
import argparse
import datetime
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(description="Bump or verify dnf-plugin-p2p version")
    parser.add_argument(
        "version",
        nargs="?",
        default=None,
        help="New version (e.g., 0.3.5)"
    )
    parser.add_argument(
        "--author",
        default="dnf-plugin-p2p contributors <none@example.com>",
        help="Author for the RPM changelog entry"
    )
    parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help="Check that versions across all project files are synchronized"
    )
    return parser.parse_args()


def get_file_versions(root: Path) -> dict:
    versions = {}

    # 1. Spec file
    spec_path = root / "dnf-plugin-p2p.spec"
    if spec_path.exists():
        match = re.search(r"^Version:\s+(\S+)", spec_path.read_text(), re.MULTILINE)
        versions["dnf-plugin-p2p.spec"] = match.group(1) if match else None

    # 2. CMakeLists.txt
    cmake_path = root / "CMakeLists.txt"
    if cmake_path.exists():
        match = re.search(r"PROJECT\s*\(\s*dnf-plugin-p2p\s+VERSION\s+(\S+)", cmake_path.read_text())
        versions["CMakeLists.txt"] = match.group(1) if match else None

    # 3. plugins/p2p_plugin.py
    plugin_path = root / "plugins/p2p_plugin.py"
    if plugin_path.exists():
        match = re.search(r"return\s+libdnf5\.plugin\.Version\((\d+),\s*(\d+),\s*(\d+)\)", plugin_path.read_text())
        versions["plugins/p2p_plugin.py"] = f"{match.group(1)}.{match.group(2)}.{match.group(3)}" if match else None

    # 4. plugins/libdnf_p2p_sharing/__init__.py
    plugin_init = root / "plugins/libdnf_p2p_sharing/__init__.py"
    if plugin_init.exists():
        match = re.search(r"^__version__\s*=\s*\"([^\"]+)\"", plugin_init.read_text(), re.MULTILINE)
        versions["plugins/libdnf_p2p_sharing/__init__.py"] = match.group(1) if match else None

    # 5. p2p-proxy-server/__init__.py
    server_init = root / "p2p-proxy-server/__init__.py"
    if server_init.exists():
        match = re.search(r"^__version__\s*=\s*\"([^\"]+)\"", server_init.read_text(), re.MULTILINE)
        versions["p2p-proxy-server/__init__.py"] = match.group(1) if match else None

    return versions


def check_versions(root: Path) -> int:
    versions = get_file_versions(root)
    print("Checking version synchronization across project files:")
    all_matched = True
    first_ver = None

    for filepath, ver in versions.items():
        status = ver if ver else "NOT FOUND / UNPARSEABLE"
        print(f"  - {filepath:40s}: {status}")
        if not ver:
            all_matched = False
        elif first_ver is None:
            first_ver = ver
        elif ver != first_ver:
            all_matched = False

    if all_matched and first_ver:
        print(f"\nSUCCESS: All files are synchronized at version {first_ver}")
        return 0
    else:
        print("\nERROR: Version mismatch or unparseable version detected!", file=sys.stderr)
        return 1


def bump_spec(path: Path, version: str, author: str):
    print(f"Updating {path}...")
    content = path.read_text()
    
    # 1. Update Version definition
    content = re.sub(
        r"^(Version:\s+)\S+",
        rf"\g<1>{version}",
        content,
        flags=re.MULTILINE
    )
    
    # 2. Reset Release to 1
    content = re.sub(
        r"^(Release:\s+)\S+",
        r"\g<1>1%{?dist}",
        content,
        flags=re.MULTILINE
    )
    
    # 3. Add Changelog entry
    # Format: * Fri Jun 19 2026 dnf-plugin-p2p contributors - 0.2.0-1
    # - Release 0.2.0
    now = datetime.datetime.now()
    date_str = now.strftime("%a %b %d %Y")
    changelog_entry = f"* {date_str} {author} - {version}-1\n- Release {version}\n\n"
    
    if "%changelog" in content:
        content = content.replace("%changelog\n", f"%changelog\n{changelog_entry}")
    else:
        content += f"\n%changelog\n{changelog_entry}"
        
    path.write_text(content)

def bump_cmake(path: Path, version: str):
    print(f"Updating {path}...")
    content = path.read_text()
    content = re.sub(
        r"(PROJECT\s*\(\s*dnf-plugin-p2p\s+VERSION\s+)\S+",
        rf"\g<1>{version}",
        content
    )
    path.write_text(content)

def bump_plugin(path: Path, version: str):
    print(f"Updating {path}...")
    content = path.read_text()
    
    # Parse version parts
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid semver version: {version}")
    major, minor, patch = parts
    
    content = re.sub(
        r"return\s+libdnf5\.plugin\.Version\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)",
        f"return libdnf5.plugin.Version({major}, {minor}, {patch})",
        content
    )
    path.write_text(content)

def bump_init_files(paths: list[Path], version: str):
    for path in paths:
        if path.exists():
            print(f"Updating {path}...")
            content = path.read_text()
            content = re.sub(
                r"^(__version__\s*=\s*)\"[^\"]+\"",
                rf'\g<1>"{version}"',
                content,
                flags=re.MULTILINE
            )
            path.write_text(content)


def main():
    args = parse_args()
    root = Path(__file__).parent.resolve()

    if args.check:
        sys.exit(check_versions(root))

    if not args.version:
        print("Error: Version argument required when not running with --check", file=sys.stderr)
        sys.exit(1)

    version = args.version
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        print(f"Error: Version '{version}' does not match SemVer format X.Y.Z", file=sys.stderr)
        sys.exit(1)

    # Bump in spec file
    bump_spec(root / "dnf-plugin-p2p.spec", version, args.author)

    # Bump in CMakeLists.txt
    bump_cmake(root / "CMakeLists.txt", version)

    # Bump in python plugin
    bump_plugin(root / "plugins/p2p_plugin.py", version)

    # Bump in package init files
    bump_init_files([
        root / "plugins/libdnf_p2p_sharing/__init__.py",
        root / "p2p-proxy-server/__init__.py"
    ], version)

    # Verify everything synchronized cleanly
    print("\nVerifying version synchronization:")
    if check_versions(root) != 0:
        print("Warning: Version check failed after bump!", file=sys.stderr)
        sys.exit(1)

    print(f"\nVersion bumped successfully to {version}!")
    print("Suggested commands to commit and release:")
    print("  git add .")
    print(f'  git commit -m "Bump version to {version}"')
    print(f'  git tag -s v{version} -m "Release v{version}"')
    print(f"  git push origin master v{version}")


if __name__ == "__main__":
    main()

