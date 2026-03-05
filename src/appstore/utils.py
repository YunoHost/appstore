import base64
import json
import tomllib
from pathlib import Path
from typing import Any

import pycmarkgfm
from emoji import emojize
from flask import request

TRANSLATIONS_DIR = (Path(__file__).parent / "translations").resolve()
AVAILABLE_LANGUAGES = [
    "en",
    *[path.name for path in TRANSLATIONS_DIR.iterdir() if path.is_dir()],
]

DATA_DIR: Path | None = None


def set_data_dir(data_dir: Path) -> None:
    global DATA_DIR
    DATA_DIR = Path(data_dir)


def get_locale() -> str:
    # try to guess the language from the user accept
    # The best match wins.
    return request.accept_languages.best_match(AVAILABLE_LANGUAGES) or "en"


def get_catalog():
    assert DATA_DIR is not None, "Please call utils.set_data_dir!"
    path = DATA_DIR / "apps.json"
    mtime = path.stat().st_mtime
    if get_catalog.mtime_catalog != mtime:
        get_catalog.mtime_catalog = mtime

        catalog = json.load(path.open())
        catalog["categories"] = {c["id"]: c for c in catalog["categories"]}
        catalog["antifeatures"] = {c["id"]: c for c in catalog["antifeatures"]}

        category_color = {
            "synchronization": "sky",
            "publishing": "yellow",
            "communication": "amber",
            "office": "lime",
            "productivity_and_management": "purple",
            "small_utilities": "black",
            "reading": "emerald",
            "education": "pink",
            "multimedia": "fuchsia",
            "social_media": "rose",
            "games": "violet",
            "dev": "stone",
            "system_tools": "black",
            "iot": "orange",
            "wat": "teal",
        }

        for id_, category in catalog["categories"].items():
            category["color"] = category_color[id_]

        get_catalog.cache_catalog = catalog

    return get_catalog.cache_catalog


get_catalog.mtime_catalog: float | None = None


def get_wishlist() -> dict[str, dict[str, str | int]]:
    assert DATA_DIR is not None, "Please call utils.set_data_dir!"
    path = DATA_DIR / "apps" / "wishlist.toml"
    mtime = path.stat().st_mtime
    if get_wishlist.mtime_wishlist != mtime:
        get_wishlist.mtime_wishlist = mtime
        get_wishlist.cache_wishlist = tomllib.load(path.open("rb"))

    return get_wishlist.cache_wishlist


get_wishlist.mtime_wishlist = None


def get_dashboard_data():
    assert DATA_DIR is not None, "Please call utils.set_data_dir!"
    path = DATA_DIR / "dashboard.json"
    mtime = path.stat().st_mtime
    if get_dashboard_data.mtime != mtime:
        get_dashboard_data.mtime = mtime
        dashboard_data = json.load(path.open())
        get_dashboard_data.cache = dashboard_data

    return get_dashboard_data.cache


get_dashboard_data.mtime = None
# We don't load this at launch to avoid miserably crashing if it doesn't exists yet
# get_dashboard_data()


def human_to_binary(size: str) -> int:
    symbols = ("K", "M", "G", "T", "P", "E", "Z", "Y")
    factor = {}
    for i, s in enumerate(symbols):
        factor[s] = 1 << (i + 1) * 10

    suffix = size[-1]
    size = size[:-1]

    if suffix not in symbols:
        raise Exception(f"Invalid size suffix '{suffix}', expected one of {symbols}")

    try:
        size_ = float(size)
    except Exception:
        raise Exception(f"Failed to convert size {size} to float")

    return int(size_ * factor[suffix])


def get_app_md_and_screenshots(app_folder: Path | str, infos: dict[str, Any]) -> None:
    locale = get_locale()
    app_folder = Path(app_folder)

    def get_value(files: list[Path], default: str) -> str:
        for file in files:
            if file.exists():
                return emojize(
                    pycmarkgfm.gfm_to_html(file.read_text()), language="alias"
                )
        return default

    infos["full_description_html"] = get_value(
        [
            app_folder / "doc" / f"DESCRIPTION_{locale}.md",
            app_folder / "doc" / "DESCRIPTION.md",
        ],
        infos["manifest"]["description"][locale],
    )

    pre_install = get_value(
        [
            app_folder / "doc" / f"PRE_INSTALL_{locale}.md",
            app_folder / "doc" / "PRE_INSTALL.md",
        ],
        "",
    )
    if pre_install:
        infos["pre_install_html"] = pre_install

    infos["screenshot"] = None
    screenshots_folder = app_folder / "doc" / "screenshots"
    if screenshots_folder.exists():
        for file in screenshots_folder.iterdir():
            ext = file.suffix.lower()
            if file.is_file() and ext in ("png", "jpg", "jpeg", "webp", "gif"):
                data = base64.b64encode(file.read_bytes()).decode("utf-8")
                infos["screenshot"] = f"data:image/{ext};charset=utf-8;base64,{data}"
                break

    ram_build_requirement = infos["manifest"]["integration"]["ram"]["build"]
    infos["manifest"]["integration"]["ram"]["build_binary"] = human_to_binary(
        ram_build_requirement
    )
