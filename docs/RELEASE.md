# v0.1.0 release acceptance

Release scope: reviewed public source for trusted-team evaluation, with independently supplied model weights and provider credentials.

Required gates:

1. Backend regression and security tests pass against the release dependency versions.
2. Frontend tests and production build pass; npm audit has no known vulnerabilities.
3. PostgreSQL/pgvector upgrades an empty database to the single Alembic head.
4. Full development and production Compose configurations are valid. Images build, all required infrastructure is healthy, authenticated API/file lifecycle smoke passes through Nginx, and the CPU inference engine executes without a supplied private checkpoint.
5. Published Git history and release package contain no credentials, private teaching/report material, machine-specific local records, checkpoints or user/runtime data. Run Gitleaks with fully redacted output and dependency auditing; keep raw audit evidence private.
6. Source package uses only reviewed tracked files, opens successfully and has a SHA-256 checksum. Missing deployment scripts, unresolved conflict markers and duplicate API routes are rejected.

CI run results for each commit provide executable acceptance evidence. A release must reference the tested commit, rather than inheriting older validation claims from the private project's internal notes.

The private fork archive preserves the original project history. The public source starts from a clean snapshot because historical teaching documents contained credential-like material. Original copyright and attribution are preserved in NOTICE.md; no project-level open-source license is inferred.

Weights and business datasets are intentionally absent. Install a trusted licensed checkpoint through administrator model management to perform domain-specific detection. The CI's synthetic model verifies inference execution only. Real LLM/embedding calls require account credentials and are outside the automated release gate.

For backup/restore use the scripts only with an explicitly selected Compose file and private environment. Restoration overwrites business data and requires `-Confirm`. Test restoration on an isolated deployment before relying on it. Do not publish backups.
