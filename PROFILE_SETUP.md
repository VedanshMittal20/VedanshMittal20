# Profile maintenance

The README uses a locally stored banner and native Markdown, without external stats-image services.

## Automatic updates

`Refresh profile` runs at approximately **09:47 and 21:47 India time** each day, on relevant profile edits, and from **Actions > Refresh profile > Run workflow**. Scheduled jobs can be delayed. GitHub may disable scheduled workflows on a public repository after 60 days without repository activity; re-enable from Actions if that happens.

All public repositories are discovered, including later additions. Forks, archived repositories, and the profile repository are excluded. The three most recently pushed projects are featured; six appear in recent work. `profile.json` provides the existing projects' titles, summaries, and stacks. New repositories use their actual name, description, and primary language. Add a useful repository description when you create a project.

Kaggle result records are discovered in every repository's root when named `submission*result*.json` or `profile-results.json`. The EV and House Prices projects already use this format:

```json
{
  "competition": "competition-slug",
  "status": "COMPLETE",
  "public_score": 0.12345,
  "submitted_at_utc": "2026-10-07T12:00:00Z"
}
```

`profile-results.json` can contain one record or a list. Keep credentials and private scores out of these files. Known competitions use the `min` / `max` settings in `profile.json` to select the best public score. Unknown metrics display the latest confirmed public score until their direction is configured. Local validation metrics are never treated as Kaggle scores.

## Connect Kaggle once

To discover joined competitions, live public ranks, uncommitted scores, and public notebooks automatically:

1. Open [Kaggle API settings](https://www.kaggle.com/settings/api). Use a token for `vedanshmittal2076`.
2. Open [this repository's Actions secrets](https://github.com/VedanshMittal20/VedanshMittal20/settings/secrets/actions).
3. Add **`KAGGLE_API_TOKEN`**. Paste the token directly into GitHub; keep it out of chat and source files.
4. Run **Refresh profile** from Actions.

The workflow can update this profile repository. The updater only lists Kaggle competitions, submissions, and public notebooks. It never submits predictions, joins competitions, changes teams, or accepts rules. Treat the token as an account credential: its permissions come from Kaggle even though this updater only reads. Revoke it in Kaggle and remove the GitHub secret to disconnect.

Without that secret, GitHub discovery and repository-backed score updates still work. Previously verified standings retain their check dates. API failures preserve the last successful public data and produce an Actions warning. Completed placements are never overwritten by public ranks. Newly closed competitions keep the label `Public` until their completed result is independently verified.

## Editing

Edit the biography, skills, extra work, and contact sections directly. Content between the `PROJECTS`, `KAGGLE`, `REPOS`, and `UPDATED` markers is generated; keep all marker pairs intact. Update verified completed ranks in `profile-snapshot.json` with `rank_kind: "Completed"`, the source URL, and actual check date.

Run `python update_profile.py --self-test` for the small offline check. Run `python update_profile.py` for a manual refresh. GitHub needs no Python dependencies. For Kaggle, install `requirements-profile.txt` and set `KAGGLE_API_TOKEN`. Credentials never go into the snapshot.

## Initial evidence

Verified on 7 October 2026:

- [EV completed result](https://www.kaggle.com/vedanshmittal2076/competitions): **294 / 3,575**. Best recorded public ROC AUC: **0.94646**. The public score and completed placement are different measures.
- [House Prices public leaderboard](https://www.kaggle.com/competitions/house-prices-advanced-regression-techniques/leaderboard): **93 / 3,937**, **0.11649**. This supersedes the historical rank 80 recorded on 1 October in the project README.
- [Traffic Flow Bench public leaderboard](https://www.kaggle.com/competitions/2026-ieee-big-data-traffic-flow-bench/leaderboard): **119 / 351**, **0.85114**. Active standings can change.

The banner was created with the built-in image-generation tool. Prompt direction: a graphite GitHub banner, Geist-style white typography, one cyan accent, sculptural chrome lattice, and the exact text “Data into models. Models into products.”
