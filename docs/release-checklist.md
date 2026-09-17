# Clean distribution release checklist

Historical checks from the personal working project are not release evidence for this distribution.

- [ ] Review every code, documentation and synthetic fixture change.
- [ ] Review screenshots visually; never include real health data.
- [ ] Run isolated tests and syntax checks on this tree.
- [ ] Stage explicit reviewed files and update the SHA-256 publication manifest.
- [ ] Run `python scripts/check_publication.py --history`.
- [ ] Publish only to an approved clean-history remote; never merge personal history.
- [ ] Verify fresh-clone tests and remote CI before announcing a release.
- [ ] Configure private vulnerability reporting and branch protection.

Live services, scheduled jobs, cloud credentials and real databases are outside this checklist. Do not stop or alter a running personal deployment as part of publication.
