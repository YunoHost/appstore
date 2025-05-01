#!/usr/bin/env python3

import json
import os
import shutil
from pathlib import Path


class AppstoreStars:
    def __init__(self, stars_file: Path) -> None:
        self.path: Path = stars_file
        self.stars: dict[str, set[int]] = {}
        if not self.path.exists():
            json.dump({}, self.path.open("w"))

    def add(self, app: str, user: int) -> None:
        if app not in self.stars:
            self.stars[app] = set()
        self.stars[app].add(user)
        self.save()

    def remove(self, app: str, user: int) -> None:
        self.stars.get(app, set()).remove(user)
        self.save()

    def save(self) -> None:
        data = {app: list(users) for app, users in self.stars.items()}
        json.dump(data, self.path.open("w"))

    def read(self) -> None:
        self.read_legacy()
        data = json.load(self.path.open("r"))
        self.stars = {app: set(users) for app, users in data.items()}

    def read_legacy(self) -> None:
        legacy_stars_dir = self.path.parent / "stars"
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
