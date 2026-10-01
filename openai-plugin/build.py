"""Build the complete OpenAI upload from this manifest and the canonical skills."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def build(output: Path) -> Path:
    source = Path(__file__).resolve().parent
    repository = source.parent
    manifest = json.loads((source / "plugin.json").read_text())
    prefix = manifest["name"] + "/"
    files = {
        "plugin.json": (source / "plugin.json").read_bytes(),
        "mcp.json": (source / "mcp.json").read_bytes(),
        "assets/icon.png": (source / "assets/icon.png").read_bytes(),
    }
    # Include every canonical skill and its references, with custom additions
    # taking precedence. Exclude caches, symlinks and executable artifacts.
    for root in (repository / "skills", source / "skills"):
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            if path.suffix not in {".md", ".yaml", ".yml", ".json"}:
                continue
            if any(
                part.startswith(".") or part == "__pycache__"
                for part in path.relative_to(root).parts
            ):
                continue
            files["skills/" + path.relative_to(root).as_posix()] = path.read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            entry = ZipInfo(prefix + name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, content)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="ZIP destination outside the plugin directory")
    print(build(parser.parse_args().output))
