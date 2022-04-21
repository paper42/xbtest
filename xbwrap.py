#!/usr/bin/env python3
import subprocess
import sys
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

# xbps-install --repository=$mirror -r "$root" -S base-voidstrap --cachedir /var/cache/xbps/

VERBOSITY = 1
XBWRAPDIR = "/var/lib/xbwrap"
# TODO: log to stderr
# TODO: make VERBOSITY configurable by -v -vv -vvv


def getpkgname(pkgver: str) -> str:
    return "-".join(pkgver.split("-")[:-1])


class XBPS():
    def __init__(self, root: str = "/") -> None:
        if shutil.which("xbps-query") is None:
            raise RuntimeError("xbps-query not found in $PATH")
        self.root = root


    def get_deps(self,
                 pkgname: str,
                 recursive: bool = False,
                 repomode: bool = False) -> List[str]:
        deps = []
        # FIXME: xbps-query -x always returns 0 even when the package isn't installed
        cmd = ["xbps-query", "-r", self.root]
        if repomode:
            cmd.append("-R")
        if recursive:
            cmd.append("--fulldeptree")
        cmd += ["-x", pkgname]
        p = subprocess.run(cmd, capture_output=True)
        assert p.stderr.decode() == ""
        for line in p.stdout.decode().splitlines():
            deps.append(getpkgname(line))
        return deps

    def get_installed_pkgs(self) -> List[str]:
        p = subprocess.run(["xbps-query", "-r", self.root, "-l"],
                           capture_output=True)
        assert p.stderr.decode() == ""
        out = []
        for line in p.stdout.decode().splitlines():
            out.append(line.split(" ")[1])
        return out

    def get_files(self, pkgname: str) -> List[str]:
        # TODO: this is slow, parse /var/db/xbps/.*.plist directly?
        p = subprocess.run(["xbps-query",
                            "-r", self.root,
                            "-f", pkgname], capture_output=True)
        assert p.stderr.decode() == ""
        files = []
        for line in p.stdout.decode().splitlines():
            if " -> " in line:
                files.append(line.split(" -> ")[0])
            else:
                files.append(line)
        return files


class Environment:
    def __init__(self, root: Path) -> None:
        if shutil.which("bwrap") is None:
            raise RuntimeError("bwrap not found in $PATH")
        self.root = root
        if os.stat(root).st_dev != os.stat("/").st_dev:
            raise RuntimeError(f"{root} is not on the same fs as /")

    def build(self, wrap_files: List[str]) -> None:
        for file in wrap_files:
            rootpath = Path(f"{self.root}/{file}").absolute()
            os.makedirs(rootpath.parent, exist_ok=True)
            os.link(file, rootpath, follow_symlinks=False)

    def destroy(self) -> None:
        shutil.rmtree(self.root)

    def run_cmd(self, command: List[str]) -> int:
        cmd = ["bwrap",
               "--unshare-all",
               "--hostname", "test",
               "--bind", str(self.root), "/",
               "--dev-bind", "/dev", "/dev",
               "--bind", "/proc", "/proc"] + command
        if VERBOSITY > 1:
            print(" ".join(cmd))
        return subprocess.run(cmd).returncode


class XBEnv():
    def __init__(self, root: Optional[Path] = None) -> None:
        if root is None:
            root = Path(tempfile.mkdtemp(dir=XBWRAPDIR))
        elif root.is_dir():
            raise RuntimeError(f"{root} already exists")
        else:
            os.mkdir(root)

        self.xbps = XBPS("/")  # we want xbps on the host system
        self.env = Environment(root)

    def build(self, pkgname: str) -> None:
        installed_pkgs = []
        for pkg in self.xbps.get_installed_pkgs():
            installed_pkgs.append(getpkgname(pkg))

        if VERBOSITY > 1:
            print("installed_pkgs:", ", ".join(installed_pkgs))

        deps = [pkgname] + \
            self.xbps.get_deps(pkgname, recursive=True)

        # TODO: musl
        # base-minimal without having to have base-minimal installed
        base_deps = ["base-files", "coreutils", "findutils", "diffutils",
                     "dash", "grep", "gzip", "sed", "gawk", "util-linux",
                     "which", "tar", "shadow", "procps-ng", "iana-etc",
                     "xbps", "nvi", "tzdata", "runit-void", "removed-packages",
                     "glibc-locales"]
        deps += base_deps
        for dep in base_deps:
            deps += self.xbps.get_deps(dep, recursive=True)

        deps = list(dict.fromkeys(deps))  # remove duplicates
        if VERBOSITY > 1:
            print("deps:", ", ".join(deps))

        for dep in deps:
            if dep not in installed_pkgs:
                raise RuntimeError(f"{dep} not installed")

        wrap_files = []
        for pkg in deps:
            wrap_files += self.xbps.get_files(pkg)
        if VERBOSITY > 2:
            print("wrap_files:", wrap_files)

        self.env.build(wrap_files)

    def run_cmd(self, cmd: List[str]) -> int:
        return self.env.run_cmd(cmd)

    def destroy(self) -> None:
        self.env.destroy()


def main() -> int:
    # TODO: proper argument parsing
    pkgname = sys.argv[1]
    command = sys.argv[2:]

    xbenv = XBEnv()

    xbenv.build(pkgname)

    retcode = xbenv.run_cmd(command)
    xbenv.destroy()
    return retcode


if __name__ == "__main__":
    sys.exit(main())
