# Security remediation — 0.14.0

Implemented in response to the comprehensive security audit. Full file identities and registered plans, descriptor-based non-overwriting installation/cleanup, per-library/state/migration locks, durable commit/rollback recovery, restricted media workers, resource limits and process-group cleanup, diagnostic allowlists, safe local development helpers, verified native dependencies and frozen-engine release gates are now in place.

Validation: all 34 regression scripts passed, including 32 dedicated security cases, compiled Swift diagnostics checks, and actual frozen-engine conversion/commit/rollback. The locked Python environment reported no known advisory matches. The local app passes strict nested signature verification.

Public distribution remains blocked until Developer ID signing/notarization and clean-machine acceptance are completed. The local dependency set requires macOS 26; the package declares its actual native minimum. The coordinator remains unsandboxed while media decoders use restricted workers. Old plans require reanalysis and uncertain historical recovery records require review. See [Security boundaries](SECURITY.md) for limits and commands.
