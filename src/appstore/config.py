#!/usr/bin/env python3

import tomllib
from pathlib import Path

from pydantic import BaseModel, ValidationError


class Config(BaseModel):
    class Config:
        validate_default = True
        extra = "forbid"

    github_login: str
    github_email: str
    github_token: str

    discourse_sso_secret: str
    discourse_sso_endpoint: str
    callback_url_after_login_on_discourse: str

    cookie_secret: str

    data_dir: Path

    def __init__(self, path: Path) -> None:
        try:
            config = tomllib.load(path.open("rb"))
            super().__init__(**config)

        except FileNotFoundError:
            raise RuntimeError(f"Config file {path} not found!") from None

        except tomllib.TOMLDecodeError as err:
            raise RuntimeError(
                f"Config file {path} has invalid TOML syntax:\n{err}"
            ) from None

        except ValidationError as err:
            raise RuntimeError(
                f"Invalid config file {path}:\n{err}"
            ) from None
