"""Collect installed, locked dependency notices without guessing missing grants.

Run with the project's Python after `uv sync --frozen --extra dev`.
Outputs inventory.json and verbatim notices to the supplied output directory.
This inventories package evidence; it does not certify legal compliance.
"""

import argparse
import hashlib
import json
import re
import tomllib
from importlib import metadata
from pathlib import Path


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def is_notice(file):
    """Include named notices and all files in distribution license directories."""
    if re.match(r"(?i)^(licen[sc]e|copying|notice|authors)([._-].*)?$", file.name):
        return True
    return "licenses" in file.parts and any(
        part.endswith(".dist-info") for part in file.parts
    )


def collect_notice(dist, file, package_directory, output):
    source = dist.locate_file(file)
    if not source.is_file():
        return None

    output_root = output.resolve()
    relative = Path(package_directory, *file.parts)
    target = (output_root / relative).resolve()

    if not target.is_relative_to(output_root):
        raise ValueError(f"Notice path escapes output directory: {file}")

    target.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    target.write_bytes(data)
    return {
        "path": target.relative_to(output_root).as_posix(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def collect_package(package, installed, output):
    name, version = package["name"], package["version"]
    row = {
        "name": name,
        "version": version,
        "sdist": package.get("sdist"),
        "files": [],
    }
    dist = installed.get(canonical(name))
    if dist is None or dist.version != version:
        row["status"] = "missing-or-wrong-installed-version"
        return row
    row["declared_license"] = dist.metadata.get(
        "License-Expression"
    ) or dist.metadata.get("License")
    for file in dist.files or []:
        if not is_notice(file):
            continue
        notice = collect_notice(dist, file, name + "-" + version, output)
        if notice is not None:
            row["files"].append(notice)
    row["status"] = "notices-collected" if row["files"] else "missing-license-text"
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path("uv.lock"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lock = tomllib.loads(args.lock.read_text())
    installed = {canonical(d.metadata["Name"]): d for d in metadata.distributions()}
    rows = [
        collect_package(package, installed, args.output)
        for package in lock["package"]
        if not {"virtual", "editable"}.intersection(package.get("source", {}))
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "inventory.json").write_text(
        json.dumps(
            {
                "lock_sha256": hashlib.sha256(args.lock.read_bytes()).hexdigest(),
                "scope": "Locked Python packages; native binaries, OS packages and hosted source access require separate verification.",
                "packages": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    for row in rows:
        if row["status"] != "notices-collected":
            print(row["name"], row["version"], row["status"])
    print(f"Inventoried {len(rows)} locked packages in {args.output}")


if __name__ == "__main__":
    main()
