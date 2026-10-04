# Changelog

## 0.1.0 — 2026-10-04

- First reviewed public source release of SSDD: Steel Defect Agent.
- Integrated upstream development, resource-lifecycle PR and original steel-defect local work.
- Combined detection, training, administration, RAG, agent history and file lifecycle workflows; excluded the separate GUI/HCI project.
- Repaired deployment scripts, full-stack Compose, container paths, migration chain, WebSocket proxying and cleanup scheduling.
- Removed default administrator credentials; restricted executable checkpoint uploads to trusted model administrators.
- Served object downloads through scoped, expiring application URLs so private storage remains accessible through the gateway without exposing its internal service port.
- Updated vulnerable dependencies, added packaging checks and full-stack CI smoke verification.

This is an initial source release for trusted-team evaluation. It is not a certification of model accuracy, GPU throughput, provider uptime or production hardening for unrestricted public signup. Supply licensed model weights and provider configuration for those features.
