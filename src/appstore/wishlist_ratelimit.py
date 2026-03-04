import json
import shutil
import time
from hashlib import md5
from pathlib import Path


class WishlistRateLimit:
    def __init__(self, path: Path) -> None:
        self.path: Path = path
        self.data: dict[str, int] = {}
        if not self.path.exists():
            self.path.write_text("{}")
        self.read()

        # 15 days ago
        self.limit = 3600 * 24 * 15
        self.prune()

    def _digest(self, user: str) -> str:
        return md5(user.encode()).hexdigest()

    def _file(self, user: str) -> Path:
        return self.path / self._digest(user)

    def add(self, user: str) -> None:
        self.data[self._digest(user)] = int(time.time())
        self.save()

    def check(self, user: str) -> bool:
        return self.data.get(self._digest(user), 0) > time.time() - self.limit

    def save(self) -> None:
        self.prune()
        json.dump(self.data, self.path.open("w"))

    def read(self) -> None:
        self.read_legacy()
        self.data = json.load(self.path.open("r"))
        self.prune()

    def prune(self) -> None:
        for key, value in self.data.items():
            if value > time.time() - self.limit:
                del self.data[key]

    def read_legacy(self) -> None:
        legacy_dir = self.path.parent / "wishlist_ratelimit"
        if not legacy_dir.exists():
            return
        data = {}
        for file in legacy_dir.iterdir():
            if file.is_file():
                data[file.name] = file.stat().st_mtime

        self.data = data
        self.save()
        shutil.rmtree(legacy_dir)
