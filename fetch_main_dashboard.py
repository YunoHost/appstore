#!/usr/bin/env python3

import json
import sys
from functools import cache
from pathlib import Path
from typing import Any, Tuple, Optional
import multiprocessing

import requests
import toml
import tqdm
from github import Github
from tqdm.contrib.logging import logging_redirect_tqdm

sys.path.append(Path(__file__).resolve().parent)

from utils import get_catalog

APPSTORE_PATH = Path(__file__).resolve().parent


@cache
def config() -> dict[str, Any]:
    try:
        config = toml.loads((APPSTORE_PATH / "config.toml").read_text())
        return config
    except Exception:
        raise RuntimeError(
            "You should create a config.toml with the appropriate key/values, cf config.toml.example"
        )


@cache
def github_api() -> Github:
    github_token = config().get("GITHUB_TOKEN")

    if github_token is None:
        raise RuntimeError("You should add a GITHUB_TOKEN to config.toml")

    return Github(github_token)


@cache
def catalog() -> dict:
    return get_catalog()


def _ci_apps_main_results() -> dict:
    return requests.get(
        "https://ci-apps.yunohost.org/ci/api/results", timeout=30
    ).json()


def _ci_apps_nextdebian_results() -> dict:
    return requests.get(
        "https://ci-apps-bookworm.yunohost.org/ci/api/results", timeout=30
    ).json()


ci_apps_main_results = _ci_apps_main_results()
ci_apps_nextdebian_results = _ci_apps_nextdebian_results()


def get_app_ci_results(results: dict[str, dict], name: str) -> Optional[dict]:
    app_results = results.get(name)
    if app_results:
        return {
            "level": app_results["level"],
            "timestamp": app_results["timestamp"],
        }
    else:
        return {}


def get_github_infos(github_orga_and_repo: str) -> Tuple[str, dict]:

    repo = github_api().get_repo(github_orga_and_repo)
    infos = {}

    pulls = [p for p in repo.get_pulls()]

    infos["nb_prs"] = len(pulls)
    infos["nb_issues"] = repo.open_issues_count - infos["nb_prs"]

    testings = [p for p in pulls if p.head.ref == "testing"]
    testing = testings[0] if testings else None
    ci_auto_updates = [p for p in pulls if p.head.ref.startswith("ci-auto-update")]
    ci_auto_update = (
        sorted(ci_auto_updates, key=lambda p: p.created_at, reverse=True)[0]
        if ci_auto_updates
        else None
    )

    for p in ([testing] if testing else []) + (
        [ci_auto_update] if ci_auto_update else []
    ):

        if p.head.label != "YunoHost-Apps:testing" and not (
            p.user.login == "yunohost-bot" and p.head.ref.startswith("ci-auto-update-")
        ):
            continue

        infos["testing" if p.head.ref == "testing" else "ci-auto-update"] = {
            "branch": p.head.ref,
            "url": p.html_url,
            "timestamp_created": int(p.created_at.timestamp()),
            "timestamp_updated": int(p.updated_at.timestamp()),
            "statuses": [
                {
                    "state": s.state,
                    "context": s.context,
                    "url": s.target_url,
                    "timestamp": int(s.updated_at.timestamp()),
                }
                for s in repo.get_commit(p.head.sha).get_combined_status().statuses
            ],
        }

    return repo.name, infos


def get_consolidated_infos(name_and_infos: Tuple[str, dict]) -> Tuple[str, dict]:
    name, infos = name_and_infos
    if infos["state"] != "working":
        return None

    data = {
        "public_level": infos["level"],
        "url": infos["git"]["url"],
        "timestamp_latest_commit": infos["lastUpdate"],
        "maintainers": infos["manifest"]["maintainers"],
        "antifeatures": infos["antifeatures"],
        "packaging_format": infos["manifest"]["packaging_format"],
        "ci_results": {
            "main": get_app_ci_results(ci_apps_main_results, name),
            "nextdebian": get_app_ci_results(ci_apps_nextdebian_results, name),
        },
    }

    if infos["git"]["url"].lower().startswith("https://github.com/"):
        org_and_name = infos["git"]["url"].lower().replace("https://github.com/", "")
        _, github_infos = get_github_infos(org_and_name)
        data.update(github_infos)

    return name, data


def main() -> None:
    consolidated_infos = {}

    with multiprocessing.Pool(processes=10) as pool:
        with logging_redirect_tqdm():
            tasks = pool.imap(get_consolidated_infos, catalog()["apps"].items())

            for result in tqdm.tqdm(
                tasks, total=len(catalog()["apps"].keys()), ascii=" ·#"
            ):
                if result is None:
                    continue
                name, infos = result
                if infos is None:
                    continue
                consolidated_infos[name] = infos

    dashboard_file = APPSTORE_PATH / ".cache" / "dashboard.json"
    dashboard_file.write_text(json.dumps(consolidated_infos))


if __name__ == "__main__":
    main()
