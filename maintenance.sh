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

main() {
    cd "$SCRIPT_DIR"

    commit="$(git rev-parse HEAD)"

    if ! git pull &>/dev/null; then
        sendxmpppy "[apps repo] Couldn't pull, maybe local changes are present?"
        exit 1
    fi

    if [[ "$(git rev-parse HEAD)" == "$commit" ]]; then
        return
    fi

    if ! restart_store; then
        sendxmpppy "[appstore] Uhoh, failed to (re)start the appstore service?"
        exit 1
    fi
}

main
