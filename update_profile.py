"""Refresh the generated README sections; stdlib-only unless Kaggle is connected."""

import argparse
import copy
import html
import json
import math
import os
from pathlib import Path
import re
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,150}\Z")
NAMES = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\Z")


def text(value):
    value = " ".join(str(value or "").split()).replace("—", ": ")
    return re.sub(r"([\\`*_\[\]()!|])", r"\\\1", html.escape(value, quote=False))


def stamp(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).isoformat()
    except (TypeError, ValueError):
        return "1970-01-01T00:00:00+00:00"


def date(value):
    return datetime.fromisoformat(stamp(value)).astimezone(IST).strftime("%d %b %Y").lstrip("0")


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def warn(message, error=None):
    # API exception messages can contain request details; log only the error type.
    print(f"::warning::{message}" + (f" ({type(error).__name__})" if error else ""))


def github(path):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "github-profile-updater", "X-GitHub-Api-Version": "2022-11-28"}
    if os.environ.get("PROFILE_GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["PROFILE_GITHUB_TOKEN"]
    with urlopen(Request("https://api.github.com" + path, headers=headers), timeout=30) as response:
        return json.load(response)


def repositories(user):
    rows, page = [], 1
    while True:
        batch = github(f"/users/{user}/repos?type=owner&sort=pushed&per_page=100&page={page}")
        rows.extend(batch)
        if len(batch) < 100:
            return sorted(rows, key=lambda row: row.get("pushed_at") or "", reverse=True)
        page += 1


def merge_score(row, score, checked, source, direction):
    score = number(score)
    if score is None:
        return
    previous = number(row.get("public_score"))
    if previous is None or (direction == "min" and score < previous) or (direction == "max" and score > previous) or (
        direction not in {"min", "max"} and stamp(checked) >= stamp(row.get("score_at"))
    ):
        row.update(public_score=score, score_at=stamp(checked), score_source=source,
                   score_kind="Best public" if direction in {"min", "max"} else "Latest public")


def repository_results(repos, config, snapshot):
    for repo in repos:
        name = repo["name"]
        try:
            entries = github(f"/repos/{config['github_user']}/{name}/contents")
            for entry in entries:
                filename = entry["name"]
                if entry["type"] != "file" or not (
                    filename == "profile-results.json" or filename.startswith("submission") and "result" in filename and filename.endswith(".json")
                ):
                    continue
                try:
                    branch = quote(repo["default_branch"], safe="")
                    raw = f"https://raw.githubusercontent.com/{config['github_user']}/{name}/{branch}/{quote(filename, safe='')}"
                    with urlopen(raw, timeout=30) as response:
                        records = json.load(response)
                    for record in records if isinstance(records, list) else [records]:
                        if not isinstance(record, dict) or record.get("status") != "COMPLETE":
                            continue
                        slug = record.get("competition", "")
                        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
                            continue
                        row = snapshot["competitions"].setdefault(slug, {"title": slug.replace("-", " ").title(), "metric": "Score"})
                        source = f"{repo['html_url']}/blob/{branch}/{quote(filename, safe='')}"
                        checked = record.get("checked_at_utc") or record.get("submitted_at_utc") or record.get("submitted_at")
                        merge_score(row, record.get("public_score"), checked, source, config["score_directions"].get(slug))
                except Exception as error:
                    warn(f"Could not read a result record in {name}; kept verified results", error)
        except HTTPError as error:
            if error.code != 404:
                warn(f"Could not check results in {name}; kept verified results", error)
        except Exception as error:
            warn(f"Could not check results in {name}; kept verified results", error)


def kaggle_results(api, config, snapshot, now):
    page_token = None
    while True:
        response = api.competitions_list(group="entered", category="all", page_size=100, page_token=page_token)
        if response is None:
            raise RuntimeError("Empty Kaggle response")
        for competition in response.competitions or []:
            slug = urlparse(competition.ref).path.rstrip("/").rsplit("/", 1)[-1]
            if not SLUG.fullmatch(slug) or not competition.user_has_entered:
                continue
            row = snapshot["competitions"].setdefault(slug, {})
            row["title"] = competition.title or slug.replace("-", " ").title()
            row.setdefault("metric", competition.evaluation_metric or "Score")
            source = f"https://www.kaggle.com/competitions/{slug}/leaderboard"
            rank, teams = competition.user_rank, competition.team_count
            if row.get("rank_kind") != "Completed" and isinstance(rank, int) and isinstance(teams, int) and 0 < rank <= teams:
                row.update(rank=rank, teams=teams, rank_kind="Public", rank_at=now, rank_source=source)
            try:
                page = 1
                while True:
                    submissions = api.competition_submissions(slug, page_number=page, page_size=100)
                    if submissions is None:
                        raise RuntimeError("Empty submissions response")
                    for submission in submissions:
                        status = str(getattr(submission.status, "name", submission.status))
                        if status not in {"COMPLETE", "SubmissionStatus.COMPLETE"}:
                            continue
                        merge_score(row, submission.public_score, submission.date, source, config["score_directions"].get(slug))
                    if len(submissions) < 100:
                        break
                    page += 1
            except Exception as error:
                warn(f"Could not refresh public scores for {slug}; kept verified scores", error)
        page_token = response.next_page_token
        if not page_token:
            break
    snapshot["kaggle_checked_at"] = now
    try:
        kernels = api.kernels_list(user=config["kaggle_user"], page_size=20, sort_by="dateRun")
        if kernels is None:
            raise RuntimeError("Empty public notebooks response")
        snapshot["notebooks"] = [
            {"title": kernel.title, "url": f"https://www.kaggle.com/code/{kernel.ref}", "updated_at": stamp(kernel.last_run_time)}
            for kernel in kernels if not kernel.is_private and kernel.author.lower() == config["kaggle_user"].lower()
            and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_-]+", kernel.ref)
        ][:3]
    except Exception as error:
        warn("Could not refresh public notebooks; kept the last public list", error)


def replace_block(readme, name, body):
    start, end = f"<!-- {name}:START -->", f"<!-- {name}:END -->"
    if readme.count(start) != 1 or readme.count(end) != 1 or readme.index(start) > readme.index(end):
        raise ValueError(f"Expected exactly one ordered marker pair for {name}")
    before, rest = readme.split(start)
    _, after = rest.split(end)
    return before + start + "\n" + body.strip() + "\n" + end + after


def render(repos, config, snapshot, now, readme):
    sections = []
    for repo in repos[:config["featured_count"]]:
        info = config["projects"].get(repo["name"], {})
        title = info.get("title") or repo["name"].replace("-", " ")
        description = info.get("description") or repo.get("description") or "Explore the source code and latest work in this repository."
        stack = info.get("stack") or repo.get("language") or "Source & documentation"
        section = f"### [{text(title)}]({repo['html_url']})\n\n{text(description)}\n\n`{stack.replace('`', '')}`"
        result = snapshot["competitions"].get(info.get("competition"), {})
        if number(result.get("public_score")) is not None:
            section += f"\n\n**{text(result.get('score_kind', 'Public'))} {text(result.get('metric', 'score'))}: {result['public_score']:.5f}** · [Result record]({result['score_source']})"
        sections.append(section)
    readme = replace_block(readme, "PROJECTS", "\n\n".join(sections) or "New public projects will appear here as they are published.")

    lines = [f"Team entries on [Kaggle](https://www.kaggle.com/{config['kaggle_user']}). Public scores and completed placements are labeled separately.",
             "", "| Competition | Verified public score | Standing |", "| :--- | :--- | :--- |"]
    for slug, row in snapshot["competitions"].items():
        score = number(row.get("public_score"))
        score_cell = f"[{score:.5f}]({row['score_source']}) {text(row.get('metric', 'Score'))}<br><sub>{text(row.get('score_kind', 'Public'))}</sub>" if score is not None else "Awaiting a scored submission"
        rank, teams = row.get("rank"), row.get("teams")
        rank_cell = f"[{rank:,} / {teams:,}]({row['rank_source']})<br><sub>{text(row['rank_kind'])} · {date(row['rank_at'])}</sub>" if isinstance(rank, int) and isinstance(teams, int) and 0 < rank <= teams else "No verified placement yet"
        lines.append(f"| [{text(row.get('title', slug))}](https://www.kaggle.com/competitions/{slug}) | {score_cell} | {rank_cell} |")
    if snapshot.get("notebooks"):
        lines += ["", "**Latest public notebooks**", ""]
        lines += [f"- [{text(item['title'])}]({item['url']}) · {date(item['updated_at'])}" for item in snapshot["notebooks"]]
    readme = replace_block(readme, "KAGGLE", "\n".join(lines))

    recent = [f"- **[{text(config['projects'].get(repo['name'], {}).get('title') or repo['name'])}]({repo['html_url']})** · {text(repo.get('language') or 'Documentation')} · updated {date(repo['pushed_at'])}" for repo in repos[:config["recent_count"]]]
    recent += ["", f"[Explore all repositories](https://github.com/{config['github_user']}?tab=repositories)."]
    readme = replace_block(readme, "REPOS", "\n".join(recent))
    languages = {}
    for repo in repos:
        if repo.get("language"):
            languages[repo["language"]] = languages.get(repo["language"], 0) + 1
    summary = " · ".join(f"{text(language)} {count}" for language, count in sorted(languages.items(), key=lambda item: -item[1]))
    footer = f"<sub>{len(repos)} public projects · primary languages by repository: {summary or 'not reported'}<br>Projects checked {date(now)}. Standings retain their own verification dates.</sub>"
    return replace_block(readme, "UPDATED", footer)


def self_test():
    row = {}
    merge_score(row, 0, "2026-01-01", "https://example.com/result", "max")
    assert row["public_score"] == 0
    merge_score(row, "nan", "2026-01-02", "bad", "max")
    merge_score(row, True, "2026-01-02", "bad", "max")
    assert row["public_score"] == 0
    merge_score(row, 0.94, "2026-01-03", "higher", "max")
    merge_score(row, 0.92, "2026-01-04", "worse", "max")
    assert row["public_score"] == 0.94
    merge_score(row, 0.11, "2026-01-05", "lower", "min")
    merge_score(row, 0.12, "2026-01-06", "worse", "min")
    assert row["public_score"] == 0.11
    merge_score(row, 0.9, "2025-01-01", "older", None)
    assert row["public_score"] == 0.11
    assert "&lt;script&gt;" in text("<script> [x]|y") and "\\|" in text("x|y")
    original = "keep\n<!-- X:START -->old<!-- X:END -->\ntail"
    updated = replace_block(original, "X", "new")
    assert updated.startswith("keep\n") and updated.endswith("\ntail")
    assert replace_block(updated, "X", "new") == updated
    try:
        replace_block(original + "<!-- X:END -->", "X", "new")
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate markers must fail")
    assert date("2026-10-06T23:30:00Z") == "7 Oct 2026"
    config = {"kaggle_user": "user", "score_directions": {"test": "max"}}
    competition = SimpleNamespace(ref="https://www.kaggle.com/competitions/test", title="Test", evaluation_metric="AUC", user_has_entered=True, user_rank=5, team_count=10)
    api = SimpleNamespace(
        competitions_list=lambda **kwargs: SimpleNamespace(competitions=[competition], next_page_token=""),
        competition_submissions=lambda *args, **kwargs: [SimpleNamespace(status="COMPLETE", public_score="0", date="2026-10-07")],
        kernels_list=lambda **kwargs: [SimpleNamespace(is_private=True, author="user", ref="user/private", title="private", last_run_time="2026-10-07")],
    )
    snapshot = {"competitions": {"test": {"rank_kind": "Completed", "rank": 2, "teams": 10}}, "notebooks": []}
    kaggle_results(api, config, snapshot, "2026-10-07T06:00:00+00:00")
    assert snapshot["competitions"]["test"]["rank"] == 2
    assert snapshot["competitions"]["test"]["public_score"] == 0
    assert not snapshot["notebooks"]
    print("Profile updater self-check passed")


def main():
    config = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
    if not NAMES.fullmatch(config["github_user"]) or not NAMES.fullmatch(config["kaggle_user"]):
        raise ValueError("Invalid account name")
    snapshot = copy.deepcopy(json.loads((ROOT / "profile-snapshot.json").read_text(encoding="utf-8")))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for name in ("PROJECTS", "KAGGLE", "REPOS", "UPDATED"):
        replace_block(readme, name, "")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    repos = [repo for repo in repositories(config["github_user"]) if not repo["fork"] and not repo["archived"] and repo["name"].lower() != config["github_user"].lower() and NAMES.fullmatch(repo["name"])]
    repository_results(repos, config, snapshot)
    snapshot["github_checked_at"] = now
    if os.environ.get("KAGGLE_API_TOKEN"):
        try:
            from kaggle.api.kaggle_api_extended import KaggleApi
            api = KaggleApi()
            api.authenticate()
            kaggle_results(api, config, snapshot, now)
        except Exception as error:
            warn("Kaggle sync unavailable; kept the last verified public snapshot", error)
    else:
        warn("KAGGLE_API_TOKEN is not set; repository-backed results refreshed, direct Kaggle standings preserved")
    result = render(repos, config, snapshot, now, readme)
    for filename, content in (("README.md", result), ("profile-snapshot.json", json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")):
        path = ROOT / filename
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)
    print(f"Updated {len(repos)} public projects and {len(snapshot['competitions'])} competitions")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    if parser.parse_args().self_test:
        self_test()
    else:
        main()
