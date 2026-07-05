from __future__ import annotations

import argparse
import sys
from pathlib import Path

from convert_opml_to_xmind import create_xmind_file, parse_opml
from opml_utils import repair_and_validate_opml


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OPML_DIR = ROOT / "outputs" / "opml"
DEFAULT_XMIND_DIR = ROOT / "outputs" / "xmind"


def infer_title(opml_path: Path) -> str | None:
    try:
        root_outline = parse_opml(opml_path)
    except Exception:
        return None

    title = root_outline.get("text") or root_outline.get("title")
    if title:
        return title

    import xml.etree.ElementTree as ET

    tree = ET.parse(opml_path)
    head_title = tree.getroot().findtext("./head/title")
    return head_title or opml_path.stem


def convert_batch(
    opml_dir: Path,
    xmind_dir: Path,
    overwrite: bool = False,
    limit: int | None = None,
) -> int:
    if not opml_dir.exists():
        raise FileNotFoundError(opml_dir)

    xmind_dir.mkdir(parents=True, exist_ok=True)
    opml_files = sorted(path for path in opml_dir.glob("*.opml") if path.is_file())
    if limit is not None:
        opml_files = opml_files[:limit]

    if not opml_files:
        print(f"No OPML files found in {opml_dir}", file=sys.stderr)
        return 1

    successes = 0
    failures: list[str] = []

    print(f"Converting {len(opml_files)} OPML file(s) -> XMind")
    print(f"  OPML dir : {opml_dir}")
    print(f"  XMind dir: {xmind_dir}")

    for index, opml_path in enumerate(opml_files, start=1):
        output_path = xmind_dir / f"{opml_path.stem}.xmind"
        if output_path.exists() and not overwrite:
            print(f"[{index}/{len(opml_files)}] Skipping existing: {output_path.name}")
            successes += 1
            continue

        print(f"[{index}/{len(opml_files)}] {opml_path.name} -> {output_path.name}")
        try:
            repair_and_validate_opml(opml_path)
            create_xmind_file(opml_path, output_path, title=infer_title(opml_path))
            successes += 1
        except Exception as exc:
            failures.append(opml_path.name)
            print(f"  ERROR: {exc}", file=sys.stderr)

    print(f"XMind conversion complete. Successes: {successes}. Failures: {len(failures)}.")
    if failures:
        print("Failed files:", file=sys.stderr)
        for name in failures:
            print(f"  - {name}", file=sys.stderr)
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a folder of OPML files to XMind (.xmind).")
    parser.add_argument("--opml-dir", type=Path, default=DEFAULT_OPML_DIR)
    parser.add_argument("--xmind-dir", type=Path, default=DEFAULT_XMIND_DIR)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    try:
        return convert_batch(
            opml_dir=args.opml_dir,
            xmind_dir=args.xmind_dir,
            overwrite=args.overwrite,
            limit=args.limit,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())