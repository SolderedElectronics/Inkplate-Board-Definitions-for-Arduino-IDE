#!/usr/bin/env python3
"""Validate package_Inkplate_Boards_index.json.

Checks:
  - every platform archive downloads and matches its checksum and size
  - every toolsDependency resolves to a tool in the index (packager "arduino" is built into the IDE)
  - every tool used by the newest platform of each package installs on macOS, Windows and Linux x86_64
  - every download URL of those tools is reachable
Missing native arm64 builds (Apple Silicon, Linux aarch64) are warnings, because the IDE
falls back to x86_64 under Rosetta on macOS but not on Linux.
"""
import hashlib
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

INDEX = sys.argv[1] if len(sys.argv) > 1 else "package_Inkplate_Boards_index.json"
BUILTIN_PACKAGERS = {"arduino"}

REQUIRED_HOSTS = {
    "macOS": r"(x86_64|i[3-6]86|arm64|aarch64)-apple-darwin",
    "Windows": r"(i[3-6]86|x86_64)-(w64-)?mingw32",
    "Linux x86_64": r"x86_64-.*linux-gnu",
}
NATIVE_HOSTS = {
    "macOS arm64": r"(arm64|aarch64)-apple-darwin",
    "Linux aarch64": r"aarch64-.*linux-gnu",
}

errors, warnings = [], []


def version_key(v):
    return [int(x) if x.isdigit() else x for x in re.split(r"[.\-]", v)]


def open_url(url, method="GET", headers=None):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "index-validator", **(headers or {})})
    return urllib.request.urlopen(req, timeout=120)


def check_archive(pkg, pl):
    label = f"{pkg} {pl['name']} {pl['version']}"
    try:
        h, size = hashlib.sha256(), 0
        with open_url(pl["url"]) as r:
            while chunk := r.read(1 << 20):
                h.update(chunk)
                size += len(chunk)
    except Exception as e:
        return f"{label}: download failed ({e}) {pl['url']}"
    if f"SHA-256:{h.hexdigest()}" != pl["checksum"]:
        return f"{label}: checksum mismatch, got SHA-256:{h.hexdigest()}"
    if str(size) != str(pl["size"]):
        return f"{label}: size mismatch, got {size}, index says {pl['size']}"
    print(f"ok   {label}")
    return None


def check_reachable(url):
    try:
        # Some hosts reject HEAD, so ask for the first byte only.
        with open_url(url, headers={"Range": "bytes=0-0"}):
            return None
    except Exception as e:
        return f"unreachable ({e}) {url}"


def matches(hosts, pattern):
    return "all" in hosts or any(re.fullmatch(pattern, h) for h in hosts)


def main():
    with open(INDEX) as f:
        index = json.load(f)

    archive_jobs, url_jobs = [], []
    for pkg in index["packages"]:
        name = pkg["name"]
        tools = {(t["name"], t["version"]): t for t in pkg.get("tools", [])}
        platforms = pkg["platforms"]
        newest = {}
        for pl in platforms:
            archive_jobs.append((name, pl))
            arch = pl["architecture"]
            if arch not in newest or version_key(pl["version"]) > version_key(newest[arch]["version"]):
                newest[arch] = pl
            for dep in pl.get("toolsDependencies", []):
                if dep["packager"] in BUILTIN_PACKAGERS:
                    continue
                if dep["packager"] != name or (dep["name"], dep["version"]) not in tools:
                    errors.append(f"{name} {pl['version']}: missing tool {dep['packager']}:{dep['name']}@{dep['version']}")

        for pl in newest.values():
            for dep in pl.get("toolsDependencies", []):
                tool = tools.get((dep["name"], dep["version"]))
                if dep["packager"] != name or tool is None:
                    continue
                hosts = [s["host"] for s in tool["systems"]]
                tag = f"{name} {pl['version']}: tool {dep['name']}@{dep['version']}"
                for os_name, pattern in REQUIRED_HOSTS.items():
                    if not matches(hosts, pattern):
                        errors.append(f"{tag} has no {os_name} build")
                for os_name, pattern in NATIVE_HOSTS.items():
                    if not matches(hosts, pattern):
                        warnings.append(f"{tag} has no native {os_name} build")
                url_jobs += [(tag, s["url"]) for s in tool["systems"]]

    with ThreadPoolExecutor(8) as ex:
        errors.extend(e for e in ex.map(lambda j: check_archive(*j), archive_jobs) if e)
        unique = sorted(set(url_jobs), key=lambda j: j[1])
        errors.extend(f"{tag}: {e}" for (tag, _), e in zip(unique, ex.map(lambda j: check_reachable(j[1]), unique)) if e)

    for w in sorted(set(warnings)):
        print(f"::warning::{w}")
    for e in errors:
        print(f"::error::{e}")
    print(f"{len(errors)} error(s), {len(set(warnings))} warning(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
