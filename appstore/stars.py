#!/usr/bin/env python3

import json
import os
import shutil
from pathlib import Path

from .utils import DATA_DIR, PROJECT_ROOT

STARS_FILE = DATA_DIR / "stars.json"


class AppstoreStars:
    def __init__(self) -> None:
        self.stars: dict[str, set[int]] = {}
        if not STARS_FILE.exists():
            json.dump({}, STARS_FILE.open("w"))

    def add(self, app: str, user: int) -> None:
        if not app in self.stars:
            self.stars[app] = set()
        self.stars[app].add(user)
        self.save()

    def remove(self, app: str, user: int) -> None:
        self.stars.get(app, set()).remove(user)
        self.save()

    def save(self) -> None:
        data = {app: list(users) for app, users in self.stars.items()}
        json.dump(data, STARS_FILE.open("w"))

    def read(self) -> None:
        self.read_legacy()
        data = json.load(STARS_FILE.open("r"))
        self.stars = {app: set(users) for app, users in data.items()}
        return

    def read_legacy(self) -> None:
        legacy_stars_dir = PROJECT_ROOT / ".stars"
        if not legacy_stars_dir.exists():
            return

        stars = {}
        for folder, _, files in os.walk(legacy_stars_dir):
            app_id = folder.split("/")[-1]
            if not app_id:
                continue
            stars[app_id] = set(files)

        self.stars = stars

        self.save()
        shutil.rmtree(legacy_stars_dir)
