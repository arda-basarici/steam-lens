"""The pure transforms — every number-bearing step, as data in → data out.

Modules here hold the logic the product's honesty rests on (normalization,
classification parsing, aggregation, sampling policy, …) as pure functions over
the ``contracts`` records: no I/O, no clients, no store. That is the dependency
law's rank for this package — ``core`` imports only ``contracts`` — and it is
what lets the same code run under the offline studies, the runtime pipeline,
and the eval harness without forking.

Unlike ``contracts``, the submodules are the named units here (``core.normalize``,
``core.classify``, …): each is one stage of the engine, and callers import from
the stage they mean (``from steamlens.core.normalize import normalize_label``).
"""
