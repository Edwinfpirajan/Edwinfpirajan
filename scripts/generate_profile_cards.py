#!/usr/bin/env python3
"""Generate the public activity card and a curated language-stack card.

Only activity statistics are calculated from public GitHub REST metadata.
The language card is an explicit personal selection, not a repository ranking
or a measure of expertise. No private repository content is requested.
GITHUB_TOKEN is optional and only raises the API rate limit for these GETs.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

# Deliberate profile selection, independent of repository visibility and counts.
# Do not attach inferred percentages or proficiency scores to these languages.
FEATURED_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("Go", "#00ADD8"),
    ("Rust", "#DEA584"),
    ("TypeScript", "#3178C6"),
    ("Python", "#3776AB"),
    ("PHP", "#9296CE"),
    ("JavaScript", "#F7DF1E"),
)


def api_get(path: str) -> object:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "public-profile-cards"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub API returned HTTP {exc.code}; existing cards are preserved.") from None


def get_public_data(username: str) -> tuple[dict, list[dict]]:
    profile = api_get(f"/users/{username}")
    if not isinstance(profile, dict) or not {"public_repos", "followers"} <= profile.keys():
        raise ValueError("Invalid public profile response")
    repositories: list[dict] = []
    for page in range(1, 101):
        batch = api_get(f"/users/{username}/repos?type=owner&per_page=100&page={page}")
        if not isinstance(batch, list) or any(not isinstance(repo, dict) for repo in batch):
            raise ValueError("Invalid repository response")
        repositories.extend(repo for repo in batch if repo.get("private") is False)
        if len(batch) < 100:
            return profile, repositories
    raise RuntimeError("Pagination limit reached; refusing to publish incomplete statistics")


def text(x: int | float, y: int, value: object, size: int = 12, color: str = "#C9D1D9", **attrs: str) -> str:
    extras = " ".join(f'{key.replace("_", "-")}="{html.escape(str(val), quote=True)}"' for key, val in attrs.items())
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" {extras}>{html.escape(str(value))}</text>'


def card(width: int, title: str, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="220" viewBox="0 0 {width} 220" role="img" aria-labelledby="title">'
            f'<title id="title">{html.escape(title)}</title>'
            f'<rect x="0.5" y="0.5" width="{width-1}" height="219" rx="14" fill="#0D1117" stroke="#30363D"/>'
            f'<g font-family="Arial, Helvetica, sans-serif">{body}</g></svg>\n')


def render_language_card() -> str:
    """Render six equally sized labels; positions and colors encode no metrics."""
    body = text(22, 29, "Lenguajes con los que trabajo", 17, "#C4B5FD", font_weight="700")
    body += text(22, 49, "Stack de desarrollo · selección personal", 10, "#8B98AA")
    for index, (language, color) in enumerate(FEATURED_LANGUAGES):
        x = 22 + (index % 2) * 162
        y = 68 + (index // 2) * 41
        body += f'<rect x="{x}" y="{y}" width="144" height="34" rx="8" fill="#131A24" stroke="#263040"/>'
        body += f'<circle cx="{x+15}" cy="{y+17}" r="4" fill="{color}"/>'
        body += text(x + 28, y + 22, language, 12, "#E6EDF3", font_weight="600")
    body += text(22, 207, "Backend · escritorio · aplicaciones web", 10, "#8B98AA")
    return card(350, "Stack de desarrollo: Go, Rust, TypeScript, Python, PHP y JavaScript. Selección personal, no estadísticas de repositorios.", body)


def render_cards(username: str, profile: dict, repositories: list[dict]) -> dict[str, str]:
    own = [repo for repo in repositories if repo.get("fork") is False]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    body = text(24, 29, "Mi actividad pública", 18, "#C4B5FD", font_weight="700")
    body += text(24, 49, f"@{username}", 11, "#8B98AA")
    metrics = [(int(profile["public_repos"]), "Repositorios públicos"),
               (len(own), "Repositorios sin forks"),
               (sum(int(repo.get("stargazers_count", 0)) for repo in own), "Estrellas recibidas · sin forks"),
               (int(profile["followers"]), "Seguidores")]
    for index, (number, label) in enumerate(metrics):
        x = 24 + (index % 2) * 235
        y = 92 + (index // 2) * 67
        body += text(x, y, f"{number:,}".replace(",", " "), 29, "#F0F3FA", font_weight="700")
        body += text(x, y + 21, label, 11, "#A8B2C3")
    body += text(24, 207, f"GitHub REST · Actualizado {stamp} UTC", 10, "#8B98AA")
    stats = card(480, f"Estadísticas públicas de {username}", body)

    # Keep the existing filename so the README and workflow stay compatible.
    return {"stats.svg": stats, "top-langs.svg": render_language_card()}


def main() -> None:
    username = os.environ.get("PROFILE_USERNAME", "Edwinfpirajan")
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", username):
        raise ValueError("Invalid GitHub username")
    profile, repositories = get_public_data(username)
    cards = render_cards(username, profile, repositories)
    output = Path("profile")
    output.mkdir(exist_ok=True)
    # Render everything before replacing tracked SVGs. Failures never become error cards.
    for name, svg in cards.items():
        temporary = output / f".{name}.tmp"
        temporary.write_text(svg, encoding="utf-8")
        temporary.replace(output / name)
    print(f"Generated public activity and curated language-stack cards for {username}.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Profile card generation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
