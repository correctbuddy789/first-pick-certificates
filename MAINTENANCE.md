# Versioning and maintenance

This package is a frozen research-software snapshot accompanying *When Can a
Ranking Audit Stop? Certifying First Picks with Unresolved Eligibility*.
Use the [v1.1.0 release](https://github.com/correctbuddy789/first-pick-certificates/releases/tag/v1.1.0),
packaged manifest, and checksum to identify the exact evaluated files.

The resource uses versioned tags and an [issue tracker](https://github.com/correctbuddy789/first-pick-certificates/issues) for
reproducible bug reports, documentation corrections, and proposed extensions.
The corresponding author is Tushar Nain
(`tushar@grapevine.in`). Reports should include the package version, Python
version, command, and a small synthetic input. Do not share applicant records
or private research data.

Corrections will be described in the changelog and distributed in a new
version. Published release assets and their tag are immutable. The core
algorithms, examples, and verifiers use Python's standard library and no
external services; figure regeneration additionally requires Matplotlib.
Schema 1.0 is documented in `REUSE.md`. Incompatible schema changes should
receive a new schema version rather than silently reinterpreting old inputs.

This is a research reference implementation. No response-time target,
continuing development schedule, or indefinite support period is promised.
The released snapshot remains the reproduction record if active development
stops.
