"""Distributable artwork and package contents."""

from zipfile import ZipFile

import pytest
from PIL import Image

from scripts import package_integration


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("icon.png", (256, 256)),
        ("icon@2x.png", (512, 512)),
        ("logo.png", (1024, 320)),
        ("logo@2x.png", (2048, 640)),
    ],
)
def test_brand_assets(name, size):
    path = package_integration.SOURCE / "brand" / name
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        assert image.format == "PNG"
        assert image.size == size
        assert image.mode == "RGBA"
        assert image.getchannel("A").getextrema() == (0, 255)
        assert not image.info


def test_package_includes_locales_artwork_and_license(tmp_path, monkeypatch):
    destination = tmp_path / "dist" / "light_transform.zip"
    monkeypatch.setattr(package_integration, "DESTINATION", destination)
    package_integration.main()
    with ZipFile(destination) as archive:
        names = set(archive.namelist())
        assert {
            "light_transform/manifest.json",
            "light_transform/translations/en.json",
            "light_transform/translations/uk.json",
            "light_transform/brand/icon.png",
            "light_transform/brand/icon@2x.png",
            "light_transform/brand/logo.png",
            "light_transform/brand/logo@2x.png",
            "light_transform/LICENSE",
        } <= names
        assert all(name.startswith("light_transform/") for name in names)
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
        assert archive.testzip() is None
