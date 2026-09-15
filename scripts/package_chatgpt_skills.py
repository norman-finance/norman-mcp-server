"""Build the ChatGPT-only skill upload without changing other connector packages."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def build_package(destination: Path) -> int:
    root = Path(__file__).resolve().parents[1]
    sources = sorted((root / "skills").glob("*/SKILL.md"))
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as package:
        for source in sources:
            override = root / "chatgpt" / "skills" / source.parent.name / "SKILL.md"
            package.write(
                override if override.is_file() else source, f"skills/{source.parent.name}/SKILL.md"
            )
    return len(sources)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(f"Packaged {build_package(args.output)} skills in {args.output.name}")
