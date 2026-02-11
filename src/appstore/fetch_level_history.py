#!/usr/bin/env python3

import io
import json
import shutil
from datetime import datetime
from functools import cache
from pathlib import Path

import toml
import tqdm
from git import IndexObject, Repo

from .config import Config


@cache
def time_points_until_today() -> list[datetime]:
    year = 2017
    month = 1
    day = 1
    today = datetime.today()
    date = datetime(year, month, day)

    dates = []

    while date < today:
        dates.append(date)

        day += 14
        if day > 15:
            day = 1
            month += 1

        if month > 12:
            month = 1
            year += 1

        date = datetime(year, month, day)

    return dates


def read_git_file(file: IndexObject) -> str:
    with io.BytesIO(file.data_stream.read()) as file_io:
        return file_io.read().decode("utf-8")


def get_lists_history(temp_dir: Path) -> None:
    print("Fetching the apps repository...")
    apps = Repo.clone_from("https://github.com/YunoHost/apps", temp_dir / "apps")

    print("Constructing level history...")
    progressbar = tqdm.tqdm(time_points_until_today(), ascii=" ·#")
    for t in progressbar:
        time_str = t.strftime("%Y-%m-%d")
        d_label = t.strftime("%d %b %Y")
        progressbar.set_description_str(d_label)

        # Fetch repo at this date
        commit_sha = apps.git.rev_list("-1", f"--before={time_str}", apps.active_branch)
        commit = apps.commit(commit_sha)

        try:
            if t < datetime(2019, 4, 4):
                # Merge community and official
                community = json.loads(read_git_file(commit.tree / "community.json"))
                official = json.loads(read_git_file(commit.tree / "official.json"))
                for key in official:
                    official[key]["state"] = "official"
                merged = {}
                merged.update(community)
                merged.update(official)

            elif "apps.toml" in commit.tree:
                merged = toml.loads(read_git_file(commit.tree / "apps.toml"))
            else:
                merged = json.loads(read_git_file(commit.tree / "apps.json"))
        except (toml.TomlDecodeError, json.JSONDecodeError):
            merged = {}

        # Save it
        merged_file = temp_dir / f"merged_lists.json.{time_str}"
        merged_file.write_text(json.dumps(merged))


def make_count_summary(temp_dir: Path, output: Path) -> None:
    history = []

    last_time_point_str = time_points_until_today()[-1].strftime("%Y-%m-%d")
    last_time_point_file = temp_dir / f"merged_lists.json.{last_time_point_str}"
    json_at_last_time_point = json.loads(last_time_point_file.read_text())

    relevant_apps_to_track = [
        app
        for app, infos in json_at_last_time_point.items()
        if infos.get("state") in ["working", "official"]
    ]

    print("Constructing count summary...")
    progressbar = tqdm.tqdm(time_points_until_today(), ascii=" ·#")
    for t in progressbar:
        time_str = t.strftime("%Y-%m-%d")
        d_label = t.strftime("%d %b %Y")
        progressbar.set_description_str(d_label)

        # Load corresponding json
        time_file = temp_dir / f"merged_lists.json.{time_str}"
        time_data = json.loads(time_file.read_text())

        summary = {}
        summary["date"] = d_label
        for level in range(0, 10):
            summary[f"level-{level}"] = len(
                [
                    k
                    for k, infos in time_data.items()
                    if infos.get("state") in ["working", "official"]
                    and infos.get("level", None) == level
                ]
            )

        history.append(summary)

        for app in relevant_apps_to_track:
            infos = time_data.get(app, {})

            if not infos or infos.get("state") not in ["working", "official"]:
                level = -1
            else:
                level = infos.get("level", -1)
                try:
                    level = int(level)
                except ValueError:
                    level = -1

    output.write_text(json.dumps(history))


def make_news(temp_dir: Path, output: Path) -> None:
    news_per_date = {}
    previous_time_data = {}

    def level(infos: dict[str, int | str]) -> int:
        lev = infos.get("level")
        if lev is None or (isinstance(lev, str) and not lev.isdigit()):
            return -1
        return int(lev)

    print("Constructing news...")
    progressbar = tqdm.tqdm(time_points_until_today(), ascii=" ·#")
    for t in progressbar:
        time_str = t.strftime("%Y-%m-%d")
        d_label = t.strftime("%d %b %Y")
        progressbar.set_description_str(d_label)

        # Load corresponding json
        time_file = temp_dir / f"merged_lists.json.{time_str}"
        time_data = json.loads(time_file.read_text())

        apps_current = {
            k
            for k, infos in time_data.items()
            if infos.get("state") in ["working", "official"] and level(infos) != -1
        }
        apps_current_good = {
            k
            for k, infos in time_data.items()
            if k in apps_current and level(infos) > 4
        }
        apps_current_broken = {
            k
            for k, infos in time_data.items()
            if k in apps_current and level(infos) <= 4
        }

        apps_previous = {
            k
            for k, infos in previous_time_data.items()
            if infos.get("state") in ["working", "official"] and level(infos) != -1
        }
        apps_previous_good = {
            k
            for k, infos in previous_time_data.items()
            if k in apps_previous and level(infos) > 4
        }
        apps_previous_broken = {
            k
            for k, infos in previous_time_data.items()
            if k in apps_previous and level(infos) <= 4
        }

        news_per_date[d_label] = {
            "broke": [
                [app, time_data[app]["url"]]
                for app in set(apps_previous_good & apps_current_broken)
            ],
            "repaired": [
                [app, time_data[app]["url"]]
                for app in set(apps_previous_broken & apps_current_good)
            ],
            "added": [
                [app, time_data[app]["url"]]
                for app in set(apps_current - apps_previous)
            ],
            "removed": [
                [app, previous_time_data[app]["url"]]
                for app in set(apps_previous - apps_current)
            ],
        }

        previous_time_data = time_data

    output.write_text(json.dumps(news_per_date))


def main() -> None:
    config = Config(Path.cwd() / "config.toml")

    temp_dir = config.data_dir / "fetch_level_history_temp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    get_lists_history(temp_dir)

    make_count_summary(temp_dir, config.data_dir / "history.json")
    make_news(temp_dir, config.data_dir / "news.json")


if __name__ == "__main__":
    main()
