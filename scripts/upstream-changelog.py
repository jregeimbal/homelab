#!/usr/bin/env python3
"""Upstream base changelog diff + breaking-change gate.

Compares the hermes-agent upstream base between what the manifests currently
pin (old: each HelmRelease's `spec.values` image tag, sha suffix stripped) and
what the Dockerfile `FROM` line now references (new).  Fetches the GitHub
compare API between the two tags, scans every commit message and the patch
text of `*changelog*`-named files for breaking markers
(`BREAKING`, `removed`, `no longer`, `requires`, case-insensitive), and writes
an optional JSON result and a markdown PR comment.

Exit codes: 0 no upstream change, or change without breaking markers;
10 breaking change detected; 2 fetch/parse failure.
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

# Breaking markers (case-insensitive, per plan Global Constraints).
BREAKING_RE = re.compile(r"breaking|removed|no longer|requires", re.IGNORECASE)

# Trailing "-<7+ hex>" sha suffix segment (e.g. -6e01c6c, or a full 40-char sha).
_SHA_SUFFIX_RE = re.compile(r"-(?:[0-9a-fA-F]){7,}$")

# Filenames matching *changelog* (case-insensitive) are scanned in their patch.
_CHANGELOG_NAME_RE = re.compile(r"changelog", re.IGNORECASE)

MAX_COMMENT_CHARS = 30000
TRUNCATION_MARKER = "… [truncated]"
MAX_COMMITS_LISTED = 50


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


def _changelog_files(payload: dict) -> list[dict]:
    return [
        f
        for f in payload.get("files") or []
        if _CHANGELOG_NAME_RE.search(str(f.get("filename", "")))
    ]


def classify(payload: dict) -> dict:
    """Summarize a GitHub compare payload, scanning for breaking markers.

    Breaking markers are matched against every commit message line and against
    the patch text of files whose filename matches `*changelog*`
    (case-insensitive).
    """
    commits = [
        (str(c.get("sha", "")), str((c.get("commit") or {}).get("message", "")))
        for c in payload.get("commits") or []
    ]
    files = [str(f.get("filename", "")) for f in payload.get("files") or []]

    breaking: list[str] = []
    seen: set[str] = set()

    def note(line: str) -> None:
        line = line.rstrip("\n")
        if line.strip() and line not in seen:
            seen.add(line)
            breaking.append(line)

    for sha, message in commits:
        for line in message.splitlines():
            if BREAKING_RE.search(line):
                note(f"{sha[:7]}: {line.strip()}" if line.strip() else line)
    changelog_files = _changelog_files(payload)
    for f in changelog_files:
        for line in str(f.get("patch") or "").splitlines():
            if BREAKING_RE.search(line):
                note(line)

    changelog_diff = "\n\n".join(
        f"### {f.get('filename')}\n\n{f.get('patch') or ''}" for f in changelog_files
    )
    return {
        "ahead_by": payload.get("ahead_by", 0),
        "behind_by": payload.get("behind_by", 0),
        "commits": commits,
        "files": files,
        "changelog_diff": changelog_diff,
        "breaking": breaking,
        "breaking_detected": bool(breaking),
    }


def render_comment(repo: str, old: str, new: str, cls: dict) -> str:
    """Render the markdown PR comment (capped at 30 000 chars total)."""
    lines: list[str] = ["## Upstream hermes-agent diff", ""]
    lines.append(f"- base tag: `{old}` → `{new}` (repo `{repo}`)")
    lines.append(f"- `+{cls['ahead_by']} commits` (behind by {cls['behind_by']})")
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

    if cls["breaking"]:
        lines.append("### Breaking markers detected")
        lines.append("")
        for line in cls["breaking"]:
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
    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump(cls, f, indent=2)
            f.write("\n")
    if args.out_comment_file:
        with open(args.out_comment_file, "w", encoding="utf-8") as f:
            f.write(render_comment(args.repo, old, new, cls))

    print(
        f"upstream base {old} → {new}: "
        f"{cls['ahead_by']} commits ahead, {cls['behind_by']} behind"
    )
    if cls["breaking_detected"]:
        print(f"breaking markers detected in {len(cls['breaking'])} line(s):")
        for line in cls["breaking"][:20]:
            print(f"  {line}")
        print("See the PR comment for the full diff.")
        return 10
    print("no breaking markers detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())