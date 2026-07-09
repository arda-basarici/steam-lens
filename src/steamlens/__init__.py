"""SteamLens — aspect, event-investigation, and evaluation over Steam reviews.

The package is built in four strata that import strictly downward —
``contracts`` (the plain-data spine) → ``core`` (pure transforms) → shells
(Steam/LLM/store I/O) → entry shells (pipeline, serve, studies). The dependency
law is enforced by the import-graph test, which doubles as the two-track wall.
See ARCHITECTURE.md for the module map and DESIGN.md for the reasoning.
"""
