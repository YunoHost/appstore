import base64
import datetime
import hashlib
import hmac
import json
import random
import re
import string
import sys
import textwrap
import time
import tomllib
import urllib.parse
from pathlib import Path

import tomlkit
from flask import (
    Flask,
    Response,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
)
from flask_babel import Babel
from flask_babel import gettext as _
from github import Github, InputGitAuthor
from slugify import slugify

from .stars import AppstoreStars
from .utils import (
    get_app_md_and_screenshots,
    get_catalog,
    get_dashboard_data,
    get_locale,
    get_wishlist,
    set_data_dir,
)
from .wishlist_ratelimit import WishlistRateLimit

app = Flask(__name__, static_url_path="/assets", static_folder="assets")

MAIN_CI = "bookworm"

try:
    config_file = Path("config.toml")
    config = tomllib.load(config_file.open("rb"))
except (OSError, tomllib.TOMLDecodeError):
    print(
        "You should create a config.toml with the appropriate key/values, "
        "cf config.toml.example"
    )
    sys.exit(1)

mandatory_config_keys = [
    "DISCOURSE_SSO_SECRET",
    "DISCOURSE_SSO_ENDPOINT",
    "COOKIE_SECRET",
    "CALLBACK_URL_AFTER_LOGIN_ON_DISCOURSE",
    "GITHUB_LOGIN",
    "GITHUB_TOKEN",
    "GITHUB_EMAIL",
    "DATA_DIR",
]

for key in mandatory_config_keys:
    if key not in config:
        print(f"Missing key in config.toml: {key}")
        sys.exit(1)

if app.config.get("DEBUG"):
    app.config["TEMPLATES_AUTO_RELOAD"] = True

# This is the secret key used for session signing
app.secret_key = config["COOKIE_SECRET"]

babel = Babel(app, locale_selector=get_locale)


DATA_DIR = Path(config["DATA_DIR"])
set_data_dir(DATA_DIR)

STARS = AppstoreStars(DATA_DIR / "stars.json")
STARS.read()
WISHLIST_RATELIMIT = WishlistRateLimit(DATA_DIR / "wishlist_ratelimit")


@app.template_filter("localize")
def localize(d: str) -> str:
    if not isinstance(d, dict):
        return d
    locale = get_locale()
    if locale in d:
        return d[locale]
    return d["en"]


@app.template_filter("days_ago")
def days_ago(timestamp: int | float) -> int:
    now = datetime.datetime.now(tz=datetime.UTC)
    then = datetime.datetime.fromtimestamp(timestamp, tz=datetime.UTC)
    return (now - then).days


@app.template_filter("hours_ago")
def hours_ago(timestamp: int | float) -> str:
    now = datetime.datetime.now(tz=datetime.UTC)
    then = datetime.datetime.fromtimestamp(timestamp, tz=datetime.UTC)
    minutes, _ = divmod((now - then).total_seconds(), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}:{int(minutes):02d}h"


@app.template_filter("format_datetime")
def format_datetime(value: str, format_: str = "%d %b %Y %I:%M %p") -> str:
    if value is None:
        return ""
    then = datetime.datetime.strptime(value, "%d %b %Y").replace(tzinfo=datetime.UTC)
    return then.strftime(format_)


@app.context_processor
def utils():
    d = {
        "user": session.get("user", {}),
        "locale": get_locale(),
    }

    if app.config.get("DEBUG"):
        d["tailwind_local"] = open("assets/tailwind-local.css").read()

    return d


###############################################################################


@app.route("/favicon.ico")
def favicon() -> Response:
    return send_from_directory("assets", "favicon.png")


@app.route("/")
def index() -> Response:
    return render_template(
        "index.html",
        catalog=get_catalog(),
    )


@app.route("/catalog")
def browse_catalog() -> Response:
    return render_template(
        "catalog.html",
        init_sort=request.args.get("sort"),
        init_search=request.args.get("search"),
        init_category=request.args.get("category"),
        init_starsonly=request.args.get("starsonly"),
        catalog=get_catalog(),
        timestamp_now=int(time.time()),
        stars=STARS.stars,
    )


@app.route("/popularity.json")
def popularity_json() -> Response:
    return {app: len(stars) for app, stars in STARS.stars.items()}


@app.route("/app/<string:app_id>")
def app_info(app_id: string) -> Response:
    infos = get_catalog()["apps"].get(app_id)
    app_folder = DATA_DIR / "apps_cache" / app_id
    if not infos or not app_folder.exists():
        return f"App {app_id} not found", 404

    get_app_md_and_screenshots(app_folder, infos)

    return render_template(
        "app.html",
        app_id=app_id,
        infos=infos,
        catalog=get_catalog(),
        stars=STARS.stars,
    )


@app.route("/app/<string:app_id>/<string:action>")
def star_app(app_id: str, action: str) -> Response:
    assert action in ["star", "unstar"]
    if app_id not in get_catalog()["apps"] and app_id not in get_wishlist():
        return _("App %(app_id)s not found", app_id=app_id), 404
    if not session.get("user", {}):
        title = _("You must be logged in to be able to star an app")
        paragraph = (
            _(
                "Note that, due to various abuses, we restricted login on the app "
                "store to 'trust level 1' users.<br/><br/>'Trust level 1' is obtained "
                "after interacting a minimum with the forum, and more specifically: "
                "entering at least 5 topics, reading at least 30 posts, and spending "
                "at least 10 minutes reading posts."
            ),
        )
        return f"{title}<br/><br/>{paragraph}", 401

    user = session.get("user", {})["id"]

    if action == "star":
        STARS.add(app_id, user)

    elif action == "unstar":
        STARS.remove(app_id, user)

    location = f"/app/{app_id}" if app_id in get_catalog()["apps"] else "/wishlist"
    return redirect(location)


@app.route("/wishlist")
def browse_wishlist() -> Response:
    return render_template(
        "wishlist.html",
        wishlist=get_wishlist(),
        stars=STARS.stars,
    )


@app.route("/wishlist/add", methods=["GET", "POST"])
def add_to_wishlist() -> Response:
    if request.method == "POST":
        user = session.get("user", {})
        if not user:
            title = _("You must be logged in to submit an app to the wishlist")
            paragraph = _(
                "Note that, due to various abuses, we restricted login on the app "
                "store to 'trust level 1' users.<br/><br/>'Trust level 1' is obtained "
                "after interacting a minimum with the forum, and more specifically: "
                "entering at least 5 topics, reading at least 30 posts, and spending "
                "at least 10 minutes reading posts."
            )
            return render_template(
                "wishlist_add.html",
                csrf_token=None,
                successmsg=None,
                errormsg=f"{title}<br/><br/>{paragraph}",
            )
        csrf_token = request.form["csrf_token"]

        if csrf_token != session.get("csrf_token"):
            errormsg = _("Invalid CSRF token, please refresh the page and try again")
            return render_template(
                "wishlist_add.html",
                csrf_token=csrf_token,
                successmsg=None,
                errormsg=errormsg,
            )

        name = request.form["name"].strip().replace("\n", "")
        description = request.form["description"].strip().replace("\n", "")
        upstream = request.form["upstream"].strip().replace("\n", "")
        website = request.form["website"].strip().replace("\n", "")
        license_ = request.form["license"].strip().replace("\n", "")

        boring_keywords_to_check_for_people_not_reading_the_instructions = [
            "free",
            "open source",
            "open-source",
            "self-hosted",
            "simple",
            "lightweight",
            "light-weight",
            "léger",
            "best",
            "most",
            "fast",
            "rapide",
            "flexible",
            "puissante",
            "puissant",
            "powerful",
            "secure",
        ]

        checks = [
            (
                WISHLIST_RATELIMIT.check(session["user"]["username"])
                or session["user"]["bypass_ratelimit"],
                _(
                    "Proposing wishlist additions is limited to once every 15 days "
                    "per user. Please try again in a few days."
                ),
            ),
            (len(name) >= 3, _("App name should be at least 3 characters")),
            (len(name) <= 30, _("App name should be less than 30 characters")),
            (
                len(description) >= 5,
                _("App description should be at least 5 characters"),
            ),
            (
                len(description) <= 100,
                _("App description should be less than 100 characters"),
            ),
            (
                len(upstream) >= 10,
                _("Upstream code repo URL should be at least 10 characters"),
            ),
            (
                len(upstream) <= 150,
                _("Upstream code repo URL should be less than 150 characters"),
            ),
            (
                len(license_) >= 10,
                _("License URL should be at least 10 characters"),
            ),
            (
                len(license_) <= 250,
                _("License URL should be less than 250 characters"),
            ),
            (len(website) <= 150, _("Website URL should be less than 150 characters")),
            (
                re.match(r"^[\w\.\-\(\)\ ]+$", name),
                _("App name contains special characters"),
            ),
            (
                all(
                    keyword not in description.lower()
                    for keyword in boring_keywords_to_check_for_people_not_reading_the_instructions
                ),
                _(
                    "Please focus on what the app does, without using marketing, "
                    "fuzzy terms, or repeating that the app is 'free' and "
                    "'self-hostable'. English language is preferred."
                ),
            ),
            (
                description.lower().split()[0] != name
                and (
                    len(description.split()) == 1
                    or description.lower().split()[1] not in ["is", "est"]
                ),
                _("No need to repeat the name of the app. Focus on what the app does."),
            ),
        ]

        for check, errormsg in checks:
            if not check:
                return render_template(
                    "wishlist_add.html",
                    csrf_token=csrf_token,
                    successmsg=None,
                    errormsg=errormsg,
                )

        slug = slugify(name)
        github = Github(config["GITHUB_TOKEN"])
        author = InputGitAuthor(config["GITHUB_LOGIN"], config["GITHUB_EMAIL"])
        repo = github.get_repo("Yunohost/apps")
        current_wishlist_rawtoml = repo.get_contents(
            "wishlist.toml", ref=repo.default_branch
        )
        current_wishlist_sha = current_wishlist_rawtoml.sha
        current_wishlist_rawtoml = current_wishlist_rawtoml.decoded_content.decode()
        new_wishlist = tomlkit.loads(current_wishlist_rawtoml)

        if slug in new_wishlist:
            url = f"https://apps.yunohost.org/wishlist?search={slug}"
            return render_template(
                "wishlist_add.html",
                csrf_token=csrf_token,
                successmsg=None,
                errormsg=_(
                    "An entry with the name %(slug)s already exists in the wishlist, "
                    "instead, you can <a href='%(url)s'>add a star to the app to "
                    "show your interest</a>.",
                    slug=slug,
                    url=url,
                ),
            )

        rejectedlist_rawtoml = repo.get_contents(
            "rejectedlist.toml", ref=repo.default_branch
        )
        rejectedlist_rawtoml = rejectedlist_rawtoml.decoded_content.decode()
        rejectedlist = tomlkit.loads(rejectedlist_rawtoml)

        for rejectedinfo in rejectedlist.values():
            if upstream.strip("/ ") in rejectedinfo["upstream"]:
                return render_template(
                    "wishlist_add.html",
                    csrf_token=csrf_token,
                    successmsg=None,
                    errormsg=_(
                        "We're sorry, but this app is listed among the already "
                        "declined apps. The specified reason is:"
                        "<br /><q>%(reason)s</q>",
                        reason=rejectedinfo["reason"],
                    ),
                )

        app_catalog = get_catalog()["apps"]

        if slug in app_catalog:
            url = f"https://apps.yunohost.org/app/{slug}"
            return render_template(
                "wishlist_add.html",
                csrf_token=csrf_token,
                successmsg=None,
                errormsg=_(
                    "An app with the name %(slug)s already exists in the catalog, "
                    "<a href='%(url)s'>you can see its page here</a>.",
                    slug=slug,
                    url=url,
                ),
            )

        new_wishlist[slug] = {
            "name": name,
            "description": description,
            "upstream": upstream,
            "website": website,
        }

        new_wishlist = dict(sorted(new_wishlist.items()))
        new_wishlist_rawtoml = tomlkit.dumps(new_wishlist)
        new_branch = f"add-to-wishlist-{slug}"
        try:
            # Get the commit base for the new branch, and create it
            commit_sha = repo.get_branch(repo.default_branch).commit.sha
            repo.create_git_ref(ref=f"refs/heads/{new_branch}", sha=commit_sha)
        except Exception as e:
            print("… Failed to create branch ?")
            print(e)
            url = "https://github.com/YunoHost/apps/pulls?q=is%3Apr+is%3Aopen+label%3AWishlist"
            errormsg = _(
                "Failed to create the pull request to add the app to the wishlist… "
                "Maybe there's already <a href='%(url)s'>a waiting PR for this "
                "app</a>? Else, please report the issue to the YunoHost team.",
                url=url,
            )
            return render_template(
                "wishlist_add.html",
                csrf_token=csrf_token,
                successmsg=None,
                errormsg=errormsg,
            )

        message = f"Add {name} to wishlist"
        repo.update_file(
            "wishlist.toml",
            message=message,
            content=new_wishlist_rawtoml,
            sha=current_wishlist_sha,
            branch=new_branch,
            author=author,
        )

        # Wait a bit to preserve the API rate limit
        time.sleep(1.5)

        body = textwrap.dedent(f"""
            ### Add {name} to wishlist

            Proposed by **{session["user"]["username"]}**

            Website: {website}
            Upstream repo: {upstream}
            License: {license_}
            Description: {description}

            - [ ] Confirm app is self-hostable and generally makes sense to
                  possibly integrate in YunoHost
            - [ ] Confirm app's license is opensource/free software
                  (or not-totally-free-upstream, case by case TBD)
            - [ ] Description describes clearly and concisely what the app is/does

            Regular Contributors and Admins can comment with `!reject <reason>` to
            remove the proposed app from the wishlist and put it in the rejectedlist
            with the appropriate reason.
        """)

        # Open the PR
        pr = repo.create_pull(
            title=message,
            body=body,
            head=new_branch,
            base=repo.default_branch,
        )
        pr.add_to_labels("Wishlist")

        url = f"https://github.com/YunoHost/apps/pull/{pr.number}"

        successmsg = _(
            "Your proposed app has succesfully been submitted. It must now be "
            "validated by the YunoHost team. You can track progress here: "
            "<a href='%(url)s'>%(url)s</a>",
            url=url,
        )

        WISHLIST_RATELIMIT.add(session["user"]["username"])

        return render_template(
            "wishlist_add.html",
            successmsg=successmsg,
        )
    letters = string.ascii_lowercase + string.digits
    csrf_token = "".join(random.choice(letters) for i in range(16))
    session["csrf_token"] = csrf_token
    return render_template(
        "wishlist_add.html",
        csrf_token=csrf_token,
        successmsg=None,
        errormsg=None,
    )


@app.route("/dash")
def dash() -> Response:
    # Sort by popularity by default
    stars = STARS.stars
    data = dict(
        sorted(
            get_dashboard_data().items(),
            key=lambda app: len(stars.get(app[0], [])),
            reverse=True,
        )
    )

    return render_template(
        "dash.html", data=data, stars=stars, last_data_update=get_dashboard_data.mtime
    )


@app.route("/charts")
def charts() -> Response:
    dashboard_data = get_dashboard_data()
    level_summary = {}
    for i in range(9):
        level_summary[i] = len(
            [
                infos
                for infos in dashboard_data.values()
                if infos.get("ci_results", {}).get(MAIN_CI).get("level") == i
            ]
        )
    level_summary["unknown"] = len(
        [
            infos
            for infos in dashboard_data.values()
            if infos.get("ci_results", {}).get(MAIN_CI).get("level") in [None, "?"]
        ]
    )

    return render_template(
        "charts.html",
        level_summary=level_summary,
        history=json.load((DATA_DIR / "history.json").open()),
        news_per_date=json.load((DATA_DIR / "news.json").open()),
    )


@app.route("/news.rss")
def news_rss() -> Response:
    news_per_date = json.load((DATA_DIR / "news.json").open())

    # Keepy only the last N entries
    news_per_date = dict(reversed(list(news_per_date.items())[-2:]))

    rss_xml = render_template(
        "news_rss.xml", news_per_date=news_per_date, catalog=get_catalog()
    )
    response = make_response(rss_xml)
    response.headers["Content-Type"] = "application/rss+xml"
    response.headers["Content-Disposition"] = "inline; filename=news_rss.xml"
    return response


# Badges
@app.route("/integration/<string:app>")
@app.route("/integration/<string:app>.svg")
@app.route("/badge/<string:type>/<string:app>")
@app.route("/badge/<string:type>/<string:app>.svg")
def badge(app: str, type: str = "integration") -> Response:
    data = get_dashboard_data()
    catalog = get_catalog()["apps"]

    catalog_level = catalog.get(app, {}).get("level")
    main_ci_level = (
        data.get(app, {}).get("ci_results", {}).get(MAIN_CI, {}).get("level", "?")
    )

    if type == "integration":
        if app in catalog and main_ci_level:
            badge = f"level{main_ci_level}"
        else:
            badge = "unknown"
    elif type == "state":
        if app not in catalog:
            badge = "state-unknown"
        elif catalog_level in [None, "?"]:
            badge = "state-just-got-added-to-catalog"
        elif catalog_level in [0, -1]:
            badge = "state-broken"
        else:
            badge = "state-working"
    elif type == "maintained":
        if app in catalog and catalog.get(app, {}).get("maintained") is False:
            badge = "unmaintained"
        else:
            badge = "empty"
    elif type == "cilevel":
        if app in catalog and main_ci_level:
            badge = f"level{main_ci_level}_v2"
        else:
            badge = "unknown_v2"
    else:
        badge = "empty"

    svg = Path(f"assets/badges/{badge}.svg").read_text()
    response = make_response(svg)
    response.content_type = "image/svg+xml"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"

    return response


###############################################################################
#                        Session / SSO using Discourse                        #
###############################################################################


@app.route("/login_using_discourse")
def login_using_discourse() -> Response:
    """
    Send auth request to Discourse:
    """

    (
        nonce,
        url,
        uri_to_redirect_to_after_login,
    ) = create_nonce_and_build_url_to_login_on_discourse_sso()

    session.clear()
    session["nonce"] = nonce
    if uri_to_redirect_to_after_login:
        session["uri_to_redirect_to_after_login"] = uri_to_redirect_to_after_login

    return redirect(url)


@app.route("/sso_login_callback")
def sso_login_callback() -> Response:
    computed_sig = hmac.new(
        config["DISCOURSE_SSO_SECRET"].encode(),
        msg=request.args["sso"].encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    if computed_sig != request.args["sig"]:
        return "Invalid signature from discourse!?", 401

    response = base64.b64decode(request.args["sso"].encode()).decode()

    user_data = urllib.parse.parse_qs(response)
    if user_data["nonce"][0] != session.get("nonce"):
        return "Invalid nonce", 401

    uri_to_redirect_to_after_login = session.get("uri_to_redirect_to_after_login")

    if "trust_level_1" not in user_data["groups"][0].split(","):
        title = _("Unfortunately, login was denied.")
        paragraph = (
            _(
                "Note that, due to various abuses, we restricted login on the app "
                "store to 'trust level 1' users.<br/><br/>'Trust level 1' is obtained "
                "after interacting a minimum with the forum, and more specifically: "
                "entering at least 5 topics, reading at least 30 posts, and spending "
                "at least 10 minutes reading posts."
            ),
        )
        return (f"{title}<br/><br/>{paragraph}", 403)

    bypass_ratelimit = "staff" in user_data["groups"][0].split(",")

    session.clear()
    session["user"] = {
        "id": user_data["external_id"][0],
        "username": user_data["username"][0],
        "avatar_url": user_data["avatar_url"][0] if "avatar_url" in user_data else "",
        "bypass_ratelimit": bypass_ratelimit,
    }

    if uri_to_redirect_to_after_login:
        response = f"/{uri_to_redirect_to_after_login}"
    else:
        response = "/"
    return redirect(response)


@app.route("/toggle_packaging")
def toggle_packaging() -> Response:
    if session and "user" in session:
        user = session["user"]
        if not session["user"].get("packaging_enabled"):
            # Use this trick to force the change to be registered
            # because this session["user"]["foobar"] = value doesn't
            # actually change the state ? idk
            user["packaging_enabled"] = True
            session["user"] = user
            return redirect("/dash")
        user["packaging_enabled"] = False
        session["user"] = user
    return redirect("/")


@app.route("/logout")
def logout() -> Response:
    session.clear()

    # Only use the current referer URI if it's on the same domain as the current route
    # to avoid XSS or whatever...
    referer = request.environ.get("HTTP_REFERER")
    if referer:
        referer = referer.removeprefix("http://").removeprefix("https://")
        if "/" not in referer:
            referer = referer + "/"

        domain, uri = referer.split("/", 1)
        if domain == request.environ.get("HTTP_HOST"):
            return redirect("/" + uri)

    return redirect("/")


def create_nonce_and_build_url_to_login_on_discourse_sso() -> tuple[
    str, str, str | None
]:
    """
    Redirect the user to
    DISCOURSE_ROOT_URL/session/sso_provider?sso=URL_ENCODED_PAYLOAD&sig=HEX_SIGNATURE
    """

    nonce = "".join([str(random.randint(0, 9)) for i in range(99)])

    # Only use the current referer URI if it's on the same domain as the current route
    # to avoid XSS or whatever...
    referer = request.environ.get("HTTP_REFERER")
    uri_to_redirect_to_after_login = None
    if referer:
        referer = referer.removeprefix("http://").removeprefix("https://")
        if "/" not in referer:
            referer = referer + "/"

        domain, uri = referer.split("/", 1)
        if domain == request.environ.get("HTTP_HOST"):
            uri_to_redirect_to_after_login = uri

    url_data = {
        "nonce": nonce,
        "return_sso_url": config["CALLBACK_URL_AFTER_LOGIN_ON_DISCOURSE"],
    }
    url_encoded = urllib.parse.urlencode(url_data)
    payload = base64.b64encode(url_encoded.encode()).decode()
    sig = hmac.new(
        config["DISCOURSE_SSO_SECRET"].encode(),
        msg=payload.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()
    data = {"sig": sig, "sso": payload}
    url = f"{config['DISCOURSE_SSO_ENDPOINT']}?{urllib.parse.urlencode(data)}"

    return nonce, url, uri_to_redirect_to_after_login
