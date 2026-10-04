# Security

Do not post credentials or private data in issues. Report suspected vulnerabilities privately through the repository owner's GitHub contact/profile.

- Deployment configuration, database backups, uploaded files, chat attachments, datasets and trained model weights are private runtime assets. They are excluded from Git and release packages.
- Generate unique secrets with `scripts/configure.py`. Production rejects example signing/database/storage secrets; terminate HTTPS at a reverse proxy and restrict the exposed application port.
- Treat PyTorch `.pt` files as executable input. Only trusted administrators with `model:manage` may upload checkpoints. Do not load checkpoints from untrusted sources. This release is intended for a trusted project team; do not grant model-management permissions to arbitrary public users.
- LLM and embedding features send supplied content to the configured provider. Configure provider credentials and data handling deliberately. Never put API keys into frontend build variables.
- The private history archive is excluded from the public repository. Automated secret and dependency scans are part of release verification, but do not replace deployment-specific review.

Version 0.1.x is the currently maintained line.
