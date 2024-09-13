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

    if [ -d ".cache/tools" ]; then
        git -C .cache/tools pull
    else
        git clone https://github.com/YunoHost/apps-tools.git .cache/tools
    fi

    .cache/tools/app_caches.py -l .cache/apps/ -c .apps_cache -d -j20

    venv/bin/python3 fetch_main_dashboard.py 2>&1 | grep -v 'Following Github server redirection'

    venv/bin/python3 fetch_level_history.py
}

set_cron() {
    cat <<EOF > /etc/cron.d/appstore
# Every 2 hours
0 */2 * * * root $SCRIPT_DIR/maintenance.sh
EOF
}

main() {
    cd "$SCRIPT_DIR"

    commit="$(git rev-parse HEAD)"

    if ! git pull &>/dev/null; then
        sendxmpppy "[appstore] Couldn't pull, maybe local changes are present?"
        exit 1
    fi

    set_cron

    sudo -u appstore bash -c "$(declare -f fetch_catalog_and_level_history); fetch_catalog_and_level_history"

    if [[ "$(git rev-parse HEAD)" != "$commit" ]]; then
        if ! restart_store; then
            sendxmpppy "[appstore] Uhoh, failed to (re)start the appstore service?"
            exit 1
        fi
    fi
}

main
