#!/usr/bin/env python3

import sys

import toml

from .utils import PROJECT_ROOT

CONFIG_FILE = PROJECT_ROOT / "config" / "config.toml"


class Config:
    mandatory_config_keys = [
        "DISCOURSE_SSO_SECRET",
        "DISCOURSE_SSO_ENDPOINT",
        "COOKIE_SECRET",
        "CALLBACK_URL_AFTER_LOGIN_ON_DISCOURSE",
        "GITHUB_LOGIN",
        "GITHUB_TOKEN",
        "GITHUB_EMAIL",
        "APPS_CACHE",
    ]

    def __init__(self):
        if not CONFIG_FILE.exists():
            print(
                "You should create a config/config.toml with the appropriate"
                " key/values, cf config/config.toml.example"
            )
            sys.exit(1)

        self.config = toml.load(CONFIG_FILE.open("r"))
        self.validate()

    def validate(self):
        errors = False
        for key in self.mandatory_config_keys:
            if key not in self.config:
                print(f"Missing key in config.toml: {key}")
                errors = True
        if errors:
            sys.exit(1)
