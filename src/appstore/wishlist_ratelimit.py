import json
import shutil
import time
from hashlib import md5
from pathlib import Path


class WishlistRateLimit:
    def __init__(self, path: Path) -> None:
        self.path: Path = path
        self.data: dict[str, int] = {}
        self.path.mkdir(exist_ok=True)

        # 15 days ago
        self.limit = 3600 * 24 * 15
        self.prune()

    def _digest(self, user: str) -> str:
        return md5(user.encode()).hexdigest()

    def _file(self, user: str) -> Path:
        return self.path / self._digest(user)

    def add(self, user: str) -> None:
        self._file(user).touch()
        self.prune()

    def check(self, user: str) -> bool:
        file = self._file(user)
        return not (file.exists() and (file.stat().st_mtime > time.time() - self.limit))

    def prune(self) -> None:
        for file in self.path.iterdir():
            if file.stat().st_mtime > time.time() - self.limit:
                file.unlink()
