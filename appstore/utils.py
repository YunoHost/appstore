import base64
import json
import os
import shutil
import time
from hashlib import md5
from pathlib import Path
from typing import Any, Callable

import pycmarkgfm
import toml
from emoji import emojize
from flask import request

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS_DIR = PROJECT_ROOT / "translations"
DATA_DIR = PROJECT_ROOT / "data"

CATALOG_PATH = DATA_DIR / "apps.json"
WISHLIST_PATH = DATA_DIR / "apps_repo" / "wishlist.toml"
DASHBOARD_PATH = DATA_DIR / "dashboard.json"
WISHLIST_RATELIMIT_PATH = DATA_DIR / "wishlist_ratelimit.json"

AVAILABLE_LANGUAGES = [
    "en",
    *[path.name for path in Path("translations").iterdir() if path.is_dir()],
]


def get_locale() -> str:
    # try to guess the language from the user accept
    # The best match wins.
    return request.accept_languages.best_match(AVAILABLE_LANGUAGES) or "en"


class FileAutoReload:
    def __init__(self, function: Callable, file: Path) -> None:
        self.function = function
        self.file = file
        self.last_mtime = 0
        self.cache: Any = None

    def __call__(self, *args, **kwargs) -> Any:
        if self.file.stat().st_mtime != self.last_mtime:
            self.last_mtime = self.file.stat().st_mtime
            self.cache = self.function(*args, **kwargs)
        return self.cache


def file_autoreload(file: Path) -> Callable[[Callable], FileAutoReload]:
    return lambda func: FileAutoReload(func, file)


@file_autoreload(CATALOG_PATH)
def get_catalog() -> dict[str, Any]:
    catalog = json.load(CATALOG_PATH.open("r"))
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

    return catalog


@file_autoreload(WISHLIST_PATH)
def get_wishlist() -> dict[str, Any]:
    return toml.load(WISHLIST_PATH.open("r"))


@file_autoreload(DASHBOARD_PATH)
def get_dashboard_data() -> dict[str, Any]:
    return json.load(DASHBOARD_PATH.open("r"))


get_catalog()
get_wishlist()

# We don't load this at launch to avoid miserably crashing if it doesn't exists yet
# get_dashboard_data()


class WishlistRateLimit:
    def __init__(self) -> None:
        self.data: dict[str, int] = {}
        if not WISHLIST_RATELIMIT_PATH.exists():
            WISHLIST_RATELIMIT_PATH.write_text("{}")
        self.read()
        # 15 days ago
        self.limit = 3600 * 24 * 15

    def _digest(self, user: str) -> str:
        return md5(user.encode()).hexdigest()

    def add(self, user: str) -> None:
        self.data[self._digest(user)] = int(time.time())
        self.save()

    def check(self, user: str) -> bool:
        return self.data.get(self._digest(user), 0) > time.time() - self.limit

    def save(self) -> None:
        self.prune()
        json.dump(self.data, WISHLIST_RATELIMIT_PATH.open("w"))

    def read(self) -> None:
        self.read_legacy()
        self.data = json.load(WISHLIST_RATELIMIT_PATH.open("r"))
        self.prune()

    def prune(self) -> None:
        for key, value in self.data.items():
            if value > time.time() - self.limit:
                del self.data[key]

    def read_legacy(self) -> None:
        legacy_dir = PROJECT_ROOT / ".wishlist_ratelimit"
        if not legacy_dir.exists():
            return
        data = {}
        for file in legacy_dir.iterdir():
            if file.is_file():
                data[file.name] = file.stat().st_mtime

        self.data = data
        self.save()
        shutil.rmtree(legacy_dir)


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


def get_app_md_and_screenshots(app_folder, infos):
    locale = get_locale()

    if locale != "en" and os.path.exists(
        os.path.join(app_folder, "doc", f"DESCRIPTION_{locale}.md")
    ):
        description_path = os.path.join(app_folder, "doc", f"DESCRIPTION_{locale}.md")
    elif os.path.exists(os.path.join(app_folder, "doc", "DESCRIPTION.md")):
        description_path = os.path.join(app_folder, "doc", "DESCRIPTION.md")
    else:
        description_path = None
    if description_path:
        with open(description_path) as f:
            infos["full_description_html"] = emojize(
                pycmarkgfm.gfm_to_html(f.read()), language="alias"
            )
    else:
        infos["full_description_html"] = infos["manifest"]["description"][locale]

    if locale != "en" and os.path.exists(
        os.path.join(app_folder, "doc", f"PRE_INSTALL_{locale}.md")
    ):
        pre_install_path = os.path.join(app_folder, "doc", f"PRE_INSTALL_{locale}.md")
    elif os.path.exists(os.path.join(app_folder, "doc", "PRE_INSTALL.md")):
        pre_install_path = os.path.join(app_folder, "doc", "PRE_INSTALL.md")
    else:
        pre_install_path = None
    if pre_install_path:
        with open(pre_install_path) as f:
            infos["pre_install_html"] = emojize(
                pycmarkgfm.gfm_to_html(f.read()), language="alias"
            )

    infos["screenshot"] = None

    screenshots_folder = os.path.join(app_folder, "doc", "screenshots")

    if os.path.exists(screenshots_folder):
        with os.scandir(screenshots_folder) as it:
            for entry in it:
                ext = os.path.splitext(entry.name)[1].replace(".", "").lower()
                if entry.is_file() and ext in ("png", "jpg", "jpeg", "webp", "gif"):
                    with open(entry.path, "rb") as img_file:
                        data = base64.b64encode(img_file.read()).decode("utf-8")
                        infos["screenshot"] = (
                            f"data:image/{ext};charset=utf-8;base64,{data}"
                        )
                    break

    ram_build_requirement = infos["manifest"]["integration"]["ram"]["build"]
    infos["manifest"]["integration"]["ram"]["build_binary"] = human_to_binary(
        ram_build_requirement
    )
