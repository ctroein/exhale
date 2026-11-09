#!/usr/bin/env python3
"""Prepare a catalogued trained model and metadata for a GitHub release.

This copies and verifies the supplied trained model. It never creates a release
or uploads files. Run from a source checkout; no Exhale installation is needed.
"""

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exhale.analysis.model_store import ensure_model, model_for_method


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="supplied trained checkpoint")
    parser.add_argument("destination", type=Path, help="directory for prepared release assets")
    parser.add_argument("--method", choices=("cellpose", "smp"), default="cellpose")
    args = parser.parse_args()
    model = model_for_method(args.method)
    if not args.source.is_file():
        parser.error("the source trained model does not exist")
    with args.source.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    if args.source.stat().st_size != model.size or checksum != model.sha256:
        parser.error("the supplied model does not match the catalogued release version")
    local = replace(model, url=args.source.resolve().as_uri())
    asset = ensure_model(local, args.destination)
    checksum = asset.with_name(asset.name + ".sha256")
    checksum.write_text(f"{model.sha256}  {asset.name}\n", encoding="utf-8")
    metadata = asset.with_name(asset.name + ".json")
    metadata.write_text(json.dumps(asdict(model), indent=2) + "\n", encoding="utf-8")
    if args.method == "cellpose":
        license_file = asset.with_name(asset.name + ".LICENSE.md")
        license_file.write_bytes(
            (
                Path(__file__).resolve().parents[1] / "exhale/resources/licenses/DINOv3-LICENSE.md"
            ).read_bytes()
        )
        print(f"License: {license_file}")
    print(f"Release asset: {asset}")
    print(f"Checksum: {checksum}")
    print(f"Metadata: {metadata}")
    print(f"Expected download URL: {model.url}")


if __name__ == "__main__":
    main()
