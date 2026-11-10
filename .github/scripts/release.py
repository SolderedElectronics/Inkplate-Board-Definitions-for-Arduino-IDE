#!/usr/bin/env python3
"""Add a new board package release to package_Inkplate_Boards_index.json.

Usage:
    python3 .github/scripts/release.py <core-folder> [--upstream-version X.Y.Z]

<core-folder> is the prepared core, e.g. Inkplate_Motion_core-2.0.0/ (folder name must end in -<version>).
The script:
  1. reads the version from platform.txt and board names from boards.txt; package, architecture
     and display name come from earlier releases with the same zip prefix,
  2. zips the folder (no .DS_Store/__MACOSX, executable bits kept) next to it,
  3. copies toolsDependencies and any missing tool blocks from the upstream index
     (Espressif for esp32, ST for stm32) for the upstream core version,
  4. adds the new platform entry to the index and prints the `gh release create` command.
The upstream core version comes from `upstream.version=` in platform.txt or --upstream-version.
Nothing is published: create the GitHub release first, then commit and push the index.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
import zipfile

REPO = "SolderedElectronics/Inkplate-Board-Definitions-for-Arduino-IDE"
INDEX = "package_Inkplate_Boards_index.json"

# architecture -> (our packager, release tag prefix, upstream index URL)
UPSTREAM = {
    "esp32": ("soldered-inkplate-boards", "esp32",
              "https://espressif.github.io/arduino-esp32/package_esp32_index.json"),
    "stm32": ("Inkplate_Motion", "motion",
              "https://raw.githubusercontent.com/stm32duino/BoardManagerFiles/main/package_stmicroelectronics_index.json"),
}
SKIP = {".DS_Store", "__MACOSX", "Thumbs.db"}


def die(msg):
    sys.exit(f"error: {msg}")


def read_props(path):
    props = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^([^#=\s][^=]*)=(.*)$", line.rstrip("\n"))
        if m:
            props[m.group(1).strip()] = m.group(2).strip()
    return props


def board_names(boards_txt):
    # Top-level board entries are "<id>.name=<name>" with no further dots in the key.
    return [{"name": v} for k, v in read_props(boards_txt).items() if re.fullmatch(r"[^.]+\.name", k)]


def make_zip(folder, zip_path):
    root = os.path.basename(folder)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP)
            for name in sorted(filenames):
                if name in SKIP or name.startswith("._"):
                    continue
                path = os.path.join(dirpath, name)
                arc = os.path.join(root, os.path.relpath(path, folder))
                info = zipfile.ZipInfo.from_file(path, arc)
                info.create_system = 3  # Unix, so arduino-cli restores the permission bits
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(path, "rb") as f:
                    zf.writestr(info, f.read())


def sha256_and_size(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "SHA-256:" + h.hexdigest(), str(os.path.getsize(path))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--upstream-version")
    ap.add_argument("--index", default=INDEX)
    args = ap.parse_args()

    # shortcut: Windows has no Unix permission bits, so .sh/.py lose +x in the zip; run on macOS/Linux.
    if os.name == "nt":
        die("run this on macOS or Linux, Windows would drop the executable bits of the scripts")

    folder = os.path.abspath(args.folder.rstrip("/\\"))
    base = os.path.basename(folder)
    props = read_props(os.path.join(folder, "platform.txt"))
    version = props.get("version")
    if not version:
        die("platform.txt has no version=")
    if not base.endswith("-" + version):
        die(f"folder name '{base}' does not end with '-{version}' from platform.txt")
    prefix = base[: -len(version)]  # e.g. "Inkplate_Motion_core-"

    upstream_version = args.upstream_version or props.get("upstream.version")
    if not upstream_version:
        die("no upstream.version= in platform.txt, pass --upstream-version")

    boards = board_names(os.path.join(folder, "boards.txt"))
    if not boards:
        die("no boards found in boards.txt")

    with open(args.index, encoding="utf-8") as f:
        index = json.load(f)

    # Package, architecture and display name come from earlier releases of the same zip prefix.
    ours = [(p, pl) for p in index["packages"] for pl in p["platforms"]
            if pl["archiveFileName"].startswith(prefix) and pl["archiveFileName"][len(prefix):-4].replace(".", "").isdigit()]
    if not ours:
        die(f"no earlier '{prefix}<version>.zip' release in {args.index}")
    pkg, previous = ours[0]
    arch, name = previous["architecture"], previous["name"]
    if arch not in UPSTREAM or UPSTREAM[arch][0] != pkg["name"]:
        die(f"no upstream mapping for package {pkg['name']} / {arch}")
    _, tag_prefix, upstream_url = UPSTREAM[arch]
    if any(pl["version"] == version and pl["architecture"] == arch for pl in pkg["platforms"]):
        die(f"version {version} is already in the index")

    with urllib.request.urlopen(urllib.request.Request(upstream_url, headers={"User-Agent": "release.py"})) as r:
        upstream = json.load(r)
    up_pkg, up_pl = next(((p, pl) for p in upstream["packages"] for pl in p["platforms"]
                          if pl["architecture"] == arch and pl["version"] == upstream_version), (None, None))
    if not up_pl:
        die(f"upstream {arch} {upstream_version} not found in {upstream_url}")

    # Tools of the upstream packager move to ours; others (e.g. arduino:dfu-util) are built into the IDE, keep them.
    deps = [dict(d, packager=pkg["name"]) if d["packager"] == up_pkg["name"] else dict(d)
            for d in up_pl["toolsDependencies"]]
    have = {(t["name"], t["version"]) for t in pkg["tools"]}
    want = {(d["name"], d["version"]) for d in deps if d["packager"] == pkg["name"]}
    new_tools = [t for t in up_pkg["tools"] if (t["name"], t["version"]) in want - have]
    missing = want - have - {(t["name"], t["version"]) for t in new_tools}
    if missing:
        die(f"upstream index does not define tools {sorted(missing)}")

    zip_path = os.path.join(os.path.dirname(folder), base + ".zip")
    make_zip(folder, zip_path)
    checksum, size = sha256_and_size(zip_path)

    tag = f"{tag_prefix}-{version}"
    pkg["platforms"].insert(0, {
        "help": previous["help"],
        "category": previous["category"],
        "url": f"https://github.com/{REPO}/releases/download/{tag}/{base}.zip",
        "archiveFileName": base + ".zip",
        "checksum": checksum,
        "size": size,
        "version": version,
        "name": name,
        "architecture": arch,
        "boards": boards,
        "toolsDependencies": deps,
    })
    pkg["tools"][0:0] = new_tools

    with open(args.index, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=4, ensure_ascii=False)
        f.write("\n")

    # Self-check: the written index parses and points at the zip we just built.
    entry = next(pl for p in json.load(open(args.index, encoding="utf-8"))["packages"] if p["name"] == pkg["name"]
                 for pl in p["platforms"] if pl["version"] == version and pl["architecture"] == arch)
    assert (entry["checksum"], entry["size"]) == sha256_and_size(zip_path)

    print(f"Added {name} {version} ({arch}, upstream {upstream_version}): {len(boards)} board(s), "
          f"{len(deps)} tool dependencies, {len(new_tools)} new tool block(s)")
    print(f"Zip: {zip_path} ({size} bytes, {checksum})")
    print("\nNext steps:")
    print(f'  1. gh release create {tag} "{zip_path}" --repo {REPO} --target dev --prerelease '
          f'--title "{name} {version}" --notes "..."')
    print(f"  2. python3 .github/scripts/validate_index.py {args.index}")
    print("  3. commit and push the index to dev, test, then publish the release and merge dev into main")


if __name__ == "__main__":
    main()
