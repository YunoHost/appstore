#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

update_venv() {
    if [ -d "venv" ]; then
        venv/bin/pip install -r requirements.txt >/dev/null
    fi
}

restart_store() {
    chown -R appstore store
    update_venv

    pushd assets >/dev/null
        ./tailwindcss-linux-x64 --input tailwind-local.css --output tailwind.css --minify
    popd >/dev/null

    systemctl restart appstore
    sleep 3
    systemctl --quiet is-active appstore
}

fetch_catalog_and_level_history() {
    curl https://app.yunohost.org/default/v3/apps.json > .cache/apps.json

    if [ -d ".cache/apps" ]; then
        git -C .cache/apps pull
    else
        git clone https://github.com/YunoHost/apps.git .cache/apps
    fi

    venv/bin/python3 fetch_level_history.py
}

main() {
    cd "$SCRIPT_DIR"

    commit="$(git rev-parse HEAD)"

    if ! git pull &>/dev/null; then
        sendxmpppy "[apps repo] Couldn't pull, maybe local changes are present?"
        exit 1
    fi

    fetch_catalog_and_level_history

    if [[ "$(git rev-parse HEAD)" != "$commit" ]]; then
        if ! restart_store; then
            sendxmpppy "[appstore] Uhoh, failed to (re)start the appstore service?"
            exit 1
        fi
    fi
}

main
