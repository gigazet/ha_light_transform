"""Package only distributable integration files."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components" / "light_transform"
DESTINATION = ROOT / "dist" / "light_transform.zip"


def main() -> None:
    DESTINATION.parent.mkdir(exist_ok=True)
    with ZipFile(DESTINATION, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(SOURCE.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".json", ".png"}:
                archive.write(path, path.relative_to(SOURCE.parent))
        archive.write(ROOT / "LICENSE", "light_transform/LICENSE")
    with ZipFile(DESTINATION) as archive:
        assert archive.testzip() is None
        assert "light_transform/manifest.json" in archive.namelist()
    print(DESTINATION)


if __name__ == "__main__":
    main()
