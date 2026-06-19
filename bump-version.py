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
    parser = argparse.ArgumentParser(description="Bump dnf-plugin-p2p version")
    parser.add_argument("version", help="New version (e.g., 0.3.0)")
    parser.add_argument(
        "--author",
        default="dnf-plugin-p2p contributors <none@example.com>",
        help="Author for the RPM changelog entry"
    )
    return parser.parse_args()

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

def bump_docs(path: Path, version: str):
    print(f"Updating {path}...")
    content = path.read_text()
    
    # 0.2.0 -> 0.2 for short version
    parts = version.split(".")
    short_version = f"{parts[0]}.{parts[1]}"
    
    content = re.sub(
        r"^(version\s*=\s*)'[^']+'",
        rf"\g<1>'{short_version}'",
        content,
        flags=re.MULTILINE
    )
    content = re.sub(
        r"^(release\s*=\s*)'[^']+'",
        rf"\g<1>'{version}'",
        content,
        flags=re.MULTILINE
    )
    path.write_text(content)

def bump_doc_dev(path: Path, version: str):
    print(f"Updating {path}...")
    content = path.read_text()
    # Replace the hardcoded version in tarball commands
    content = re.sub(
        r"dnf-plugin-p2p-\d+\.\d+\.\d+",
        f"dnf-plugin-p2p-{version}",
        content
    )
    path.write_text(content)

def main():
    args = parse_args()
    version = args.version
    
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        print(f"Error: Version '{version}' does not match SemVer format X.Y.Z", file=sys.stderr)
        sys.exit(1)
        
    root = Path(__file__).parent.resolve()
    
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
    
    # Bump in docs config
    bump_docs(root / "doc/conf.py", version)
    bump_doc_dev(root / "doc/development.rst", version)
    
    print("\nVersion bumped successfully!")
    print(f"Suggested commands to commit and release:")
    print(f"  git add .")
    print(f"  git commit -m \"Bump version to {version}\"")
    print(f"  git tag -s v{version} -m \"Release v{version}\"")
    print(f"  git push origin master v{version}")

if __name__ == "__main__":
    main()
