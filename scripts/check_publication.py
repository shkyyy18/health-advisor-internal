"""Fail-closed publication audit of Git index and optional reachable history.

Reads Git objects only, never local private files. Prints locations/types, not
matched secrets. Hashes document review boundaries, not a guarantee of privacy.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

MANIFEST = ".publication-manifest.json"
LIMIT = 2_000_000
BLOCKED = {"private", "local", "data", "logs", "exports", "workspace", "business", "sessions", "node_modules", ".venv", ".codex", "secrets"}
PATTERNS = {
    "service-key": re.compile(rb"\bsk-[A-Za-z0-9_-]{24,}\b"),
    "github-token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b"),
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "aws-key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
}

class GateError(Exception):
    pass

def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if r.returncode:
        raise GateError("Git audit command failed")
    return r.stdout

def safe_path(name):
    if not isinstance(name, str) or not name or "\\" in name:
        return False
    p = PurePosixPath(name)
    return (not p.is_absolute() and name == p.as_posix()
            and not any(x in {"..", ".", ""} or x.lower() in BLOCKED for x in p.parts)
            and not any(x.lower().startswith(".env") and x != ".env.example" for x in p.parts)
            and ":" not in name and "\x00" not in name
            and not name.lower().endswith((".db", ".sqlite", ".sqlite3", ".bundle", ".key", ".pem"))
            and p.name.lower() not in {"健康顾问-项目记忆.md", "config.toml", "auth.json"})

def parse_manifest(raw):
    def no_duplicate_keys(pairs):
        d = {}
        for k, v in pairs:
            if k in d:
                raise GateError("Duplicate manifest key")
            d[k] = v
        return d
    try:
        m = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicate_keys)
    except (ValueError, UnicodeError) as exc:
        raise GateError("Invalid manifest encoding/JSON") from exc
    if not isinstance(m, dict) or set(m) != {"schema_version", "files"} or m["schema_version"] != 1:
        raise GateError("Invalid manifest schema")
    if not isinstance(m["files"], dict) or not m["files"]:
        raise GateError("Empty or invalid manifest files")
    for name, digest in m["files"].items():
        if not safe_path(name) or name == MANIFEST or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise GateError("Unsafe manifest entry")
    return m["files"]

def entries(repo, commit=None):
    args = ["ls-tree", "-r", "-z", commit] if commit else ["ls-files", "--stage", "-z"]
    out = {}
    for record in git(repo, *args).split(b"\0"):
        if not record:
            continue
        meta, raw_name = record.split(b"\t", 1)
        name = raw_name.decode("utf-8")
        mode, middle, last = meta.decode("ascii").split()
        if commit:
            if middle != "blob":
                raise GateError("Non-blob entry")
            oid = last
        else:
            if last != "0":
                raise GateError("Unresolved index entry")
            oid = middle
        if mode not in {"100644", "100755"}:
            raise GateError("Symlink or unsupported file type")
        out[name] = oid
    return out

def audit(repo, history=False):
    issues = []
    cache = {}
    def blob(oid):
        if oid not in cache:
            if int(git(repo, "cat-file", "-s", oid)) > LIMIT:
                raise GateError("Oversized file")
            cache[oid] = git(repo, "cat-file", "blob", oid)
        return cache[oid]
    snapshots = [("index", None)]
    if history:
        # Unborn clean repositories have an empty rev-list, not an implicit pass
        # for a missing manifest: the index is always checked first.
        snapshots += [(c[:12], c) for c in git(repo, "rev-list", "--all").decode("ascii").split()]
    for label, commit in snapshots:
        try:
            tree = entries(repo, commit)
            if MANIFEST not in tree:
                raise GateError("Missing publication manifest")
            approved = parse_manifest(blob(tree[MANIFEST]))
            if set(tree) != set(approved) | {MANIFEST}:
                raise GateError("Unreviewed or missing paths")
            for name, digest in approved.items():
                raw = blob(tree[name])
                if hashlib.sha256(raw).hexdigest() != digest:
                    issues.append(f"{label}: review hash mismatch: {name}")
                for kind, pattern in PATTERNS.items():
                    if pattern.search(raw):
                        issues.append(f"{label}: possible {kind}: {name}")
                if name.endswith(".png"):
                    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                        issues.append(f"{label}: invalid PNG: {name}")
                else:
                    try:
                        text = raw.decode("utf-8-sig")
                        if "\x00" in text:
                            issues.append(f"{label}: unexpected binary: {name}")
                    except UnicodeError:
                        issues.append(f"{label}: non-UTF-8: {name}")
        except (GateError, ValueError, UnicodeError, OSError):
            issues.append(f"{label}: publication boundary check failed")
    return issues

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    try:
        issues = audit(args.repo, args.history)
    except (GateError, OSError, ValueError, UnicodeError):
        print("FAIL: unable to complete publication audit", file=sys.stderr)
        return 2
    if issues:
        print("FAIL: publication blocked; no matched values printed", file=sys.stderr)
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1
    print("PASS: index" + (" and reachable history" if args.history else "") + "; manual privacy review still required")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
