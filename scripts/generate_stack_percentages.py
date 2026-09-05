#!/usr/bin/env python3
"""Render actual language-byte shares, including accessible owned private repos.

Only aggregate percentages are published. No source code, repository names,
per-repository totals, URLs or credentials are written to SVGs or logs.
CSS and other unselected languages are excluded from the denominator. This
measures repository code size, not proficiency, commits or personal authorship.
GitHub's languages API reports the default branch. No third-party services.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from generate_profile_cards import card, text

LANGUAGES = (
    ("Go", "#00ADD8"), ("Rust", "#DEA584"),
    ("TypeScript", "#3178C6"), ("Python", "#3776AB"),
    ("PHP", "#A5A8DD"), ("JavaScript", "#F7DF1E"),
)


class DataError(RuntimeError):
    """Messages must be safe for public Actions logs."""


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a private-repository credential to a redirected host.
        return None


def api_get(path: str, token: str) -> object:
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "profile-language-percentages",
               "X-GitHub-Api-Version": "2026-03-10"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request("https://api.github.com" + path, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.build_opener(NoRedirects).open(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if (exc.code == 429 or 500 <= exc.code < 600) and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            # Do not include the request URL, response body or token.
            raise DataError(f"GitHub HTTP {exc.code}; previous stack preserved.") from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            raise DataError("GitHub data unavailable; previous stack preserved.") from None
    raise DataError("GitHub data unavailable; previous stack preserved.")


def list_repositories(path: str, token: str) -> list[dict]:
    repositories: list[dict] = []
    for page in range(1, 101):
        batch = api_get(f"{path}&per_page=100&page={page}", token)
        if not isinstance(batch, list) or any(not isinstance(repo, dict) for repo in batch):
            raise DataError("Invalid repository metadata; previous stack preserved.")
        repositories.extend(batch)
        if len(batch) < 100:
            return repositories
    raise DataError("Incomplete pagination; previous stack preserved.")


def collect_bytes(username: str, public_token: str, private_token: str) -> tuple[dict[str, int], bool]:
    repositories = list_repositories(
        f"/users/{username}/repos?type=owner&sort=full_name", public_token)
    if private_token:
        identity = api_get("/user", private_token)
        if not isinstance(identity, dict) or str(identity.get("login", "")).lower() != username.lower():
            raise DataError("Profile token belongs to a different account; previous stack preserved.")
        repositories += list_repositories(
            "/user/repos?affiliation=owner&visibility=private&sort=full_name", private_token)
    totals = {language: 0 for language, _ in LANGUAGES}
    seen: set[int] = set()
    includes_private = False
    for repo in repositories:
        owner = repo.get("owner")
        if not isinstance(owner, dict):
            raise DataError("Missing repository ownership metadata.")
        if str(owner.get("login", "")).lower() != username.lower() or repo.get("fork") is True:
            continue
        if (repo.get("fork") is not False or type(repo.get("private")) is not bool
                or type(repo.get("id")) is not int or not isinstance(repo.get("name"), str)):
            raise DataError("Invalid repository metadata; previous stack preserved.")
        if repo["id"] in seen:
            continue
        seen.add(repo["id"])
        is_private = repo["private"]
        if is_private and not private_token:
            raise DataError("Private metadata without an authorized token.")
        name = urllib.parse.quote(repo["name"], safe="")
        languages = api_get(f"/repos/{username}/{name}/languages", private_token if is_private else public_token)
        if not isinstance(languages, dict) or any(
            not isinstance(key, str) or type(value) is not int or value < 0
            for key, value in languages.items()
        ):
            raise DataError("Invalid language byte counts; previous stack preserved.")
        for language in totals:
            totals[language] += languages.get(language, 0)
        includes_private |= is_private
    if not sum(totals.values()):
        raise DataError("No selected language bytes found; previous stack preserved.")
    return totals, includes_private


def tenths_percent(totals: dict[str, int]) -> list[int]:
    """Largest-remainder rounding: displayed numeric shares sum to 100.0%."""
    values = [totals[language] for language, _ in LANGUAGES]
    if any(type(value) is not int or value < 0 for value in values) or not sum(values):
        raise DataError("Invalid aggregate language totals.")
    total = sum(values)
    units = [value * 1000 // total for value in values]
    order = sorted(range(len(values)), key=lambda i: (-(values[i] * 1000 % total), i))
    for index in order[:1000 - sum(units)]:
        units[index] += 1
    return units


def render_stack(totals: dict[str, int], includes_private: bool) -> str:
    units = tenths_percent(totals)
    total = sum(totals[name] for name, _ in LANGUAGES)
    body = text(22, 29, "Mi stack de desarrollo", 17, "#C4B5FD", font_weight="700")
    body += text(22, 49, "Distribución del código · 6 lenguajes", 10, "#8B98AA")
    offset = 22.0
    for language, color in LANGUAGES:
        width = 306 * totals[language] / total
        body += f'<rect x="{offset:.4f}" y="66" width="{width:.4f}" height="8" fill="{color}"/>'
        offset += width
    for index, (language, color) in enumerate(LANGUAGES):
        x, y = 22 + (index % 2) * 162, 105 + (index // 2) * 34
        body += f'<circle cx="{x+4}" cy="{y-4}" r="4" fill="{color}"/>'
        body += text(x + 15, y, language, 11)
        share = "<0,1%" if totals[language] > 0 and units[index] == 0 else f"{units[index] / 10:.1f}%".replace(".", ",")
        body += text(x + 143, y, share, 10, "#A8B2C3", text_anchor="end")
    scope = "Públicos + privados accesibles" if includes_private else "Solo repositorios públicos"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    body += text(22, 193, "Bytes de estos 6 lenguajes · sin forks", 10, "#8B98AA")
    body += text(22, 208, f"{scope} · {stamp}", 9, "#8B98AA")
    title = (f"Porcentajes del tamaño de código de Go, Rust, TypeScript, Python, PHP y JavaScript. "
             f"{scope}. Solo repositorios propios y ramas predeterminadas. "
             "CSS y los demás lenguajes no forman parte del total. No mide dominio ni autoría personal.")
    return card(350, title, body)


def main() -> None:
    username = os.environ.get("PROFILE_USERNAME", "Edwinfpirajan")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", username):
        raise DataError("Invalid GitHub username.")
    totals, includes_private = collect_bytes(username, os.environ.get("GITHUB_TOKEN", ""),
                                            os.environ.get("PROFILE_READ_TOKEN", ""))
    svg = render_stack(totals, includes_private)
    destination = Path("profile/stack.svg")
    destination.parent.mkdir(exist_ok=True)
    temporary = destination.with_name(".stack.svg.tmp")
    temporary.write_text(svg, encoding="utf-8")
    temporary.replace(destination)
    print("Updated aggregate stack percentages; private metadata included: " + str(includes_private))


if __name__ == "__main__":
    try:
        main()
    except DataError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        # A traceback could contain a private repository URL or other metadata.
        print("Stack generation failed; no new card published.", file=sys.stderr)
        raise SystemExit(1) from None
