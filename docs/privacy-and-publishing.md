# Public/private separation and publication gate

This distribution contains only reviewed generic code, methods, blank templates and explicitly synthetic examples. Original personal working records and the old Git history are not part of this tree.

Never publish personal background, income or targets, finances, contacts, relationships, health records, private feedback, identity-linked activity, session history, local configuration or model/provider credentials. Removing a name or calling a real record synthetic does not make it publishable.

`private/`, `business/`, `workspace/`, `data/`, local credentials and runtime records must remain local-only. Test with synthetic fixtures. Do not read those directories as part of a publication scan. Do not upload ignored files as a backup or as CI artifacts.

`.publication-manifest.json` records the exact SHA-256 of each reviewed file. The gate checks Git index contents, rejects unknown paths/symlinks/secret patterns, and can verify every reachable commit. A staged unsafe blob cannot be hidden by a clean worktree. A manifest update requires manual review; matching hashes do not prove absence of all personal information.

Run `python scripts/check_publication.py --history` before publishing. Do not import old branches/tags or merge private working history into this clean repository. Use explicit file lists when staging. Automated checks do not replace human review of text and assets.
