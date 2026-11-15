#!/usr/bin/env python3
"""Upstream base changelog diff + breaking-change gate.

Compares the hermes-agent upstream base between what the manifests currently
pin (old: each HelmRelease's `spec.values` image tag, sha suffix stripped) and
what the Dockerfile `FROM` line now references (new). Fetches the GitHub
compare API between the two tags plus the upstream release notes for `new`,
and classifies every signal into two tiers:

* **hard** — unambiguous breaking markers: a conventional-commits `type!:`
  subject, a `BREAKING CHANGE:` footer, or a `BREAKING` word in a *added*
  changelog line / release-notes heading. These block the PR (exit 10).
* **soft** — heuristic keywords (`breaking`, `removed`, `no longer`,
  `requires`) found in commit *subjects* and *added* changelog lines only.
  These are listed in the PR comment for human review but never block: loose
  keyword hits in commit bodies ("...no longer lazily downloads...",
  "requires a pnpm pin") and in *removed* diff lines were the main source of
  false-positive blocks (see v0.23.0 → v0.23.1, 15/15 noise).

Exit codes: 0 no upstream change, or change without hard breaking signals;
10 hard breaking signal detected; 2 fetch/parse failure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml

GITHUB_API = "https://api.github.com"
DEFAULT_REPO = "nousresearch/hermes-agent"

# Soft heuristic keywords — review tier only, never blocking on their own.
SOFT_RE = re.compile(r"breaking|removed|no longer|requires", re.IGNORECASE)
# Hard: conventional-commits breaking subject, e.g. `feat!: x` or `fix(core)!: x`.
CONVENTIONAL_BANG_RE = re.compile(r"^[A-Za-z]+(\([^)]*\))?!(\s|:)")
# Hard: `BREAKING CHANGE:` / `BREAKING-CHANGE:` footer line (conventional-commits).
BREAKING_FOOTER_RE = re.compile(r"^\s*BREAKING[ -]CHANGE\s*:", re.IGNORECASE)
# Hard: literal BREAKING word in an *added* changelog line or a release-notes heading.
BREAKING_WORD_RE = re.compile(r"\bBREAKING\b", re.IGNORECASE)

# Trailing "-<7+ hex>" sha suffix segment (e.g. -6e01c6c, or a full 40-char sha).
_SHA_SUFFIX_RE = re.compile(r"-(?:[0-9a-fA-F]){7,}$")

# Filenames matching *changelog* (case-insensitive) are scanned in their patch.
_CHANGELOG_NAME_RE = re.compile(r"changelog", re.IGNORECASE)

MAX_COMMENT_CHARS = 30000
TRUNCATION_MARKER = "… [truncated]"
MAX_COMMITS_LISTED = 50
MAX_SOFT_LISTED = 25


def base_from_dockerfile(path: str) -> tuple[str, str]:
    """Return `(repo, tag)` from the first `FROM` line of the Dockerfile."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if not parts or parts[0].upper() != "FROM":
                continue
            ref = None
            for tok in parts[1:]:
                if tok.startswith("--"):
                    continue  # --platform=... etc.
                ref = tok.split("#", 1)[0].strip()
                break
            if not ref:
                raise RuntimeError(f"could not parse an image ref from FROM line: {line.strip()!r}")
            repo, sep, tag = ref.rpartition(":")
            if not sep:  # no explicit tag → docker's implicit :latest
                repo, tag = ref, "latest"
            return repo, tag
    raise RuntimeError(f"no FROM line found in {path}")


def strip_sha(tag: str) -> str:
    """Strip a trailing `-<7+ hex>` sha suffix segment from an image tag.

    `v2026.9.24-6e01c6c` → `v2026.9.24`; a tag without such a suffix is
    returned unchanged (the segment must be entirely hex and at least 7 long).
    """
    return _SHA_SUFFIX_RE.sub("", tag)


def _image_repo_tag(image) -> tuple[str | None, str | None]:
    """Extract (repo, tag) from a values `image` entry, string or dict form."""
    if isinstance(image, str):
        repo, sep, tag = image.rpartition(":")
        if not sep:
            return image, None
        return repo, tag
    if isinstance(image, dict):
        return image.get("repository"), image.get("tag")
    return None, None


def old_bases(manifest_paths: list[str]) -> tuple[str, str]:
    """Collect the pinned upstream base from each manifest's `spec.values`.

    Reads both image forms — a plain `image: repo:tag` string and the
    Helm-style `image: {repository, tag}` dict — plus a separate top-level
    `tag`/`repository` key if present.  Strips any sha suffix and returns
    `(repo, min(tags))` (date-based tags sort lexicographically).
    """
    repos: list[str] = []
    tags: list[str] = []
    for path in manifest_paths:
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        values = (doc or {}).get("spec", {}).get("values") or {}
        pairs = [_image_repo_tag(values.get("image"))]
        if values.get("tag") is not None:
            pairs.append((values.get("repository"), values["tag"]))
        for repo, tag in pairs:
            if tag is None:
                continue
            stripped = strip_sha(str(tag))
            tags.append(stripped)
            if repo:
                repos.append(str(repo))
    if not tags:
        raise RuntimeError("no image tag found in the given manifests")
    return (repos[0] if repos else ""), min(tags)


def fetch_compare(repo: str, old_tag: str, new_tag: str, token: str | None = None) -> dict:
    """`GET https://api.github.com/repos/{repo}/compare/{old}...{new}`.

    Adds an Authorization header when `token` is given; raises `RuntimeError`
    with the HTTP status + body on 4xx/5xx (and on network failure).
    """
    url = f"{GITHUB_API}/repos/{repo}/compare/{urllib.parse.quote(old_tag, safe='')}...{urllib.parse.quote(new_tag, safe='')}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code} from {url}: {body}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"fetch failed for {url}: {e.reason}") from None
    except (OSError, ValueError) as e:  # read timeout / reset mid-body, bad JSON
        raise RuntimeError(f"fetch failed for {url}: {e}") from None


def fetch_release(repo: str, tag: str, token: str | None = None) -> dict | None:
    """`GET /repos/{repo}/releases/tags/{tag}` → `{"tag", "body"}` or None.

    Advisory source: None when no release exists for the tag (404 — e.g.
    canary tags) or when the fetch fails.  The gate must not fail (exit 2)
    because an optional secondary source is unavailable; the compare scan
    still runs either way.
    """
    url = f"{GITHUB_API}/repos/{repo}/releases/tags/{urllib.parse.quote(tag, safe='')}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {"tag": tag, "body": str(data.get("body") or "")}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        print(f"warning: release-notes fetch failed (HTTP {e.code}) for {repo}@{tag}; skipping")
        return None
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"warning: release-notes fetch failed for {repo}@{tag}: {e}; skipping")
        return None


def _changelog_files(payload: dict) -> list[dict]:
    return [
        f
        for f in payload.get("files") or []
        if _CHANGELOG_NAME_RE.search(str(f.get("filename", "")))
    ]


def _deduping_append(lines: list[str], seen: set[str], line: str) -> None:
    line = line.rstrip("\n")
    if line.strip() and line not in seen:
        seen.add(line)
        lines.append(line)


def _iter_changelog_added(payload: dict):
    """Yield (filename, text) for *added* lines in each *changelog* patch.

    Only lines starting with `+` (excluding the `+++` header) are yielded —
    removed/reworded lines no longer fire the gate.
    """
    for f in _changelog_files(payload):
        filename = str(f.get("filename", ""))
        for line in str(f.get("patch") or "").splitlines():
            if not line.startswith("+") or line.startswith("+++"):
                continue
            yield filename, line[1:]


def classify(payload: dict) -> dict:
    """Summarize a GitHub compare payload, classifying breaking signals.

    Hard signals (block): conventional `type!:` subjects, `BREAKING CHANGE:`
    footers, `BREAKING` in added changelog lines.  Soft signals (review only):
    heuristic keywords in commit subjects and added changelog lines.  Commit
    message *bodies* are not keyword-scanned — loose hits in prose were the
    main false-positive source.
    """
    commits = [
        (str(c.get("sha", "")), str((c.get("commit") or {}).get("message", "")))
        for c in payload.get("commits") or []
    ]
    files = [str(f.get("filename", "")) for f in payload.get("files") or []]

    hard: list[str] = []
    soft: list[str] = []
    seen: set[str] = set()

    for sha, message in commits:
        lines = message.splitlines()
        subject = lines[0].strip() if lines else ""
        if CONVENTIONAL_BANG_RE.match(subject):
            _deduping_append(hard, seen, f"{sha[:7]}: {subject}")
        for line in lines[1:]:
            if BREAKING_FOOTER_RE.match(line):
                _deduping_append(hard, seen, f"{sha[:7]}: {line.strip()}")
        if SOFT_RE.search(subject):
            _deduping_append(soft, seen, f"{sha[:7]}: {subject}")

    for filename, line in _iter_changelog_added(payload):
        text = line.strip()
        if not text:
            continue
        if BREAKING_WORD_RE.search(text):
            _deduping_append(hard, seen, f"{filename}: {text}")
        elif SOFT_RE.search(text):
            _deduping_append(soft, seen, f"{filename}: {text}")

    changelog_diff = "\n\n".join(
        f"### {f.get('filename')}\n\n{f.get('patch') or ''}" for f in _changelog_files(payload)
    )
    return {
        "ahead_by": payload.get("ahead_by", 0),
        "behind_by": payload.get("behind_by", 0),
        "commits": commits,
        "files": files,
        "changelog_diff": changelog_diff,
        "hard": hard,
        "soft": soft,
        "breaking": hard,  # back-compat alias for consumers of --out-json
        "breaking_detected": bool(hard),
    }


def classify_release(body: str) -> dict:
    """Classify upstream release-notes text (same two tiers).

    Hard: a heading containing `BREAKING` (its body lines are hard too, until
    a sibling-or-higher non-breaking heading), or a `BREAKING CHANGE:` footer
    line.  Soft: heuristic keyword lines outside a breaking section.
    """
    hard: list[str] = []
    soft: list[str] = []
    seen: set[str] = set()
    breaking_level = 0  # heading level of the current breaking section, 0 = none
    for raw in body.splitlines():
        text = raw.strip()
        if not text:
            continue
        if raw.lstrip().startswith("#"):
            level = len(raw) - len(raw.lstrip("#"))
            if BREAKING_WORD_RE.search(text):
                breaking_level = level
                _deduping_append(hard, seen, text)
            elif breaking_level and level <= breaking_level:
                breaking_level = 0
            continue
        if BREAKING_FOOTER_RE.match(raw) or breaking_level:
            _deduping_append(hard, seen, text)
        elif SOFT_RE.search(text):
            _deduping_append(soft, seen, text)
    return {"hard": hard, "soft": soft}


def render_comment(repo: str, old: str, new: str, cls: dict, release: dict | None = None) -> str:
    """Render the markdown PR comment (capped at 30 000 chars total)."""
    lines: list[str] = ["## Upstream hermes-agent diff", ""]
    lines.append(f"- base tag: `{old}` → `{new}` (repo `{repo}`)")
    lines.append(f"- `+{cls['ahead_by']} commits` (behind by {cls['behind_by']})")
    if len(cls["commits"]) < cls["ahead_by"]:
        lines.append(
            f"- ⚠️ compare API truncated: only {len(cls['commits'])} of {cls['ahead_by']} commits "
            "were scanned for breaking markers — the upstream release notes for the new tag "
            "are scanned as a second source and are summarized below"
        )
    lines.append("")

    commits = cls["commits"]
    if commits:
        lines.append(f"### Commits ({len(commits)})")
        lines.append("")
        for sha, message in commits[:MAX_COMMITS_LISTED]:
            first = message.splitlines()[0] if message.splitlines() else ""
            lines.append(f"- `{sha[:7]}` {first}")
        if len(commits) > MAX_COMMITS_LISTED:
            lines.append(f"- … and {len(commits) - MAX_COMMITS_LISTED} more")
        lines.append("")

    if cls["hard"]:
        lines.append("### ⛔ Breaking changes (blocking)")
        lines.append("")
        for line in cls["hard"]:
            lines.append(f"> {line}")
        lines.append("")

    if cls["soft"]:
        lines.append("### ⚠️ Possible breaking changes (review — not blocking)")
        lines.append("")
        for line in cls["soft"][:MAX_SOFT_LISTED]:
            lines.append(f"> {line}")
        if len(cls["soft"]) > MAX_SOFT_LISTED:
            lines.append(f"> … and {len(cls['soft']) - MAX_SOFT_LISTED} more")
        lines.append("")

    if release is not None and (release.get("hard") or release.get("soft")):
        lines.append(f"### Release notes (`{release.get('tag')}`)")
        lines.append("")
        for line in (release.get("hard") or [])[:MAX_SOFT_LISTED]:
            lines.append(f"> ⛔ {line}")
        for line in (release.get("soft") or [])[:MAX_SOFT_LISTED]:
            lines.append(f"> {line}")
        lines.append("")

    if cls["changelog_diff"]:
        lines.append("### Changelog diff")
        lines.append("")
        lines.append("```diff")
        lines.append(cls["changelog_diff"].rstrip("\n"))
        lines.append("```")
        lines.append("")

    text = "\n".join(lines).rstrip() + "\n"
    if len(text) > MAX_COMMENT_CHARS:
        text = text[: MAX_COMMENT_CHARS - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
    return text


def render_no_change_comment(repo: str, old: str, new: str) -> str:
    """Short PR comment body for the old == new (no upstream change) path."""
    return (
        "## Upstream hermes-agent diff\n\n"
        "No upstream base change — the manifest pin and the Dockerfile base "
        f"tag both resolve to `{new}` (repo `{repo}`).\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diff the upstream hermes-agent base (old manifest pin vs Dockerfile FROM)."
    )
    parser.add_argument("--dockerfile", default="Dockerfile", help="Dockerfile to read the new base from")
    parser.add_argument("--manifests", nargs="+", required=True, help="HelmRelease manifest paths (old base)")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="upstream GitHub repo OWNER/NAME")
    parser.add_argument("--token", default=None, help="GitHub token (Authorization header)")
    parser.add_argument("--out-json", default=None, help="write the classification result to this path")
    parser.add_argument("--out-comment-file", default=None, help="write the markdown PR comment to this path")
    args = parser.parse_args(argv)

    try:
        new_repo, new_tag = base_from_dockerfile(args.dockerfile)
        old_repo, old = old_bases(args.manifests)
    except (RuntimeError, OSError, yaml.YAMLError) as e:
        print(f"upstream changelog parse failed: {e}")
        return 2

    new = strip_sha(new_tag)
    if old == new:
        print(f"no upstream base change (Dockerfile {new_repo}:{new_tag}, manifests {old_repo}:{old})")
        if args.out_comment_file:
            with open(args.out_comment_file, "w", encoding="utf-8") as f:
                f.write(render_no_change_comment(args.repo, old, new))
        return 0

    try:
        payload = fetch_compare(args.repo, old, new, args.token)
    except RuntimeError as e:
        print(f"upstream changelog fetch failed: {e}")
        return 2

    cls = classify(payload)
    release = fetch_release(args.repo, new, args.token)
    rcls = classify_release(release["body"]) if release else None

    if args.out_json:
        out = dict(cls)
        if rcls is not None:
            out["release"] = {"tag": new, **rcls}
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
            f.write("\n")
    if args.out_comment_file:
        comment_release = {"tag": new, **rcls} if rcls is not None else None
        with open(args.out_comment_file, "w", encoding="utf-8") as f:
            f.write(render_comment(args.repo, old, new, cls, comment_release))

    combined_hard = cls["hard"] + ((rcls or {}).get("hard", []))
    combined_soft = cls["soft"] + ((rcls or {}).get("soft", []))

    print(
        f"upstream base {old} → {new}: "
        f"{cls['ahead_by']} commits ahead, {cls['behind_by']} behind"
    )
    if len(cls["commits"]) < cls["ahead_by"]:
        print(f"warning: compare API truncated; only {len(cls['commits'])} commits scanned")
    if combined_hard:
        print(f"blocking breaking change(s) detected in {len(combined_hard)} line(s):")
        for line in combined_hard[:20]:
            print(f"  {line}")
        print("See the PR comment for the full diff.")
        return 10
    if combined_soft:
        print(
            f"no blocking breaking change(s); {len(combined_soft)} possible breaking "
            "line(s) listed for review in the PR comment"
        )
    else:
        print("no breaking markers detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())