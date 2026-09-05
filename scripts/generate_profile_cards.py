#!/usr/bin/env python3
"""Generate profile SVGs from public GitHub REST metadata, using only stdlib.

No private repository content is requested. Language shares count repositories
by their primary language (excluding forks), not lines of code or expertise.
GITHUB_TOKEN is optional and only raises the API rate limit for these GETs.
"""
from __future__ import annotations

import collections
import datetime as dt
import html
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request


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

    counts = collections.Counter(repo["language"] for repo in own if isinstance(repo.get("language"), str) and repo["language"])
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    items = ranked if len(ranked) <= 6 else ranked[:5] + [("Otros", sum(count for _, count in ranked[5:]))]
    total = sum(counts.values())
    palette = {"TypeScript": "#3178C6", "JavaScript": "#F7DF1E", "Python": "#3776AB", "Go": "#00ADD8", "Rust": "#DEA584", "HTML": "#E34F26", "CSS": "#A78BFA", "PHP": "#777BB4", "Vue": "#4FC08D", "C#": "#B388FF", "Java": "#ED8B00", "Otros": "#64748B"}
    body = text(22, 29, "Lenguajes en mis repos", 17, "#C4B5FD", font_weight="700")
    body += text(22, 49, "Lenguaje principal por repositorio · sin forks", 10, "#8B98AA")
    if total:
        offset = 22.0
        for language, count in items:
            width = 306 * count / total
            color = palette.get(language, "#38BDF8")
            body += f'<rect x="{offset:.3f}" y="66" width="{width:.3f}" height="8" fill="{color}"/>'
            offset += width
        for index, (language, count) in enumerate(items):
            x, y = 22 + (index % 2) * 162, 105 + (index // 2) * 34
            color = palette.get(language, "#38BDF8")
            body += f'<circle cx="{x+4}" cy="{y-4}" r="4" fill="{color}"/>'
            label = language if len(language) <= 13 else language[:12] + "…"
            body += text(x + 15, y, label, 11)
            body += text(x + 143, y, f"{count / total:.0%}", 10, "#A8B2C3", text_anchor="end")
    else:
        body += text(22, 112, "Sin lenguajes públicos detectados.", 12)
    body += text(22, 207, "Proporción por repositorio, no por líneas.", 10, "#8B98AA")
    return {"stats.svg": stats, "top-langs.svg": card(350, f"Lenguajes principales de {total} repositorios públicos sin forks de {username}", body)}


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
    print(f"Generated {len(cards)} cards from public metadata for {username}.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Profile card generation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
