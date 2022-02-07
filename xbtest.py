#!/usr/bin/env python3
import subprocess
import sys
from typing import List

# xbps-install --repository=$mirror -r "$root" -S base-voidstrap --cachedir /var/cache/xbps/

VERBOSITY = 2
# TODO: log to stderr
# TODO: make VERBOSITY configurable by -v -vv -vvv


def getpkgname(pkgver: str) -> str:
    return "-".join(pkgver.split("-")[:-1])


def get_recursive_deps(pkgname: str) -> List[str]:
    deps = []
    p = subprocess.run(["xbps-query", "--fulldeptree", "-x", pkgname],
                       capture_output=True)
    assert p.stderr.decode() == ""
    for line in p.stdout.decode().splitlines():
        deps.append(getpkgname(line))
    return deps


def get_installed_pkgs(root: str = "/") -> List[str]:
    p = subprocess.run(["xpkg", "-r", root], capture_output=True)
    assert p.stderr.decode() == ""
    return p.stdout.decode().splitlines()


def get_pkg_files(pkgname: str) -> List[str]:
    # TODO: this is slow, parse /var/db/xbps/.*.plist directly?
    p = subprocess.run(["xbps-query", "-f", pkgname], capture_output=True)
    assert p.stderr.decode() == ""
    files = []
    for line in p.stdout.decode().splitlines():
        if " -> " in line:
            files.append(line.split(" -> ")[0])
        else:
            files.append(line)
    return files


def build_command(root: str, wrap_files: List[str], command: List[str]) \
        -> List[str]:
    cmd = ["bwrap",
           "--unshare-all",
           "--hostname", "test",
           "--bind", root, "/",
           "--dev-bind", "/dev/shm", "/dev/shm"]

    for file in wrap_files:
        cmd += ["--bind", file, file]

    cmd += command
    return cmd


def main() -> int:
    # TODO: proper argument parsing
    root = sys.argv[1]
    pkgname = sys.argv[2]
    command = sys.argv[3:]

    if pkgname not in get_installed_pkgs():
        print(f"{pkgname} not installed")
        return 1

    deps = get_recursive_deps(pkgname)
    if VERBOSITY > 1:
        print("deps:", deps)
    deps.append(pkgname)

    installed_pkgs = get_installed_pkgs(root=root)
    print(installed_pkgs)

    # packages whose files need to be "linked" by bwrap
    wrap_pkgs = []
    for pkg in deps:
        if pkg not in installed_pkgs:
            wrap_pkgs.append(pkg)
    if VERBOSITY > 1:
        print("wrap_pkgs:", wrap_pkgs)

    wrap_files = []
    for pkg in wrap_pkgs:
        wrap_files += get_pkg_files(pkg)
    if VERBOSITY > 1:
        print("wrap_files:", wrap_files)

    cmd = build_command(root, wrap_files, command)
    if VERBOSITY > 1:
        print(cmd)

    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    sys.exit(main())
