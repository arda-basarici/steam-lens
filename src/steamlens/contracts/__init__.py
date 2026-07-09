"""The plain-data spine — every record that crosses a module seam.

Frozen, slotted dataclasses only. This package imports nothing (not even the
rest of ``steamlens``), so it sits at the base of the dependency law. Raw
external data is validated into these records at the shells, never here — once
built, a record is trusted by construction. See DESIGN's contract-modeling
decision for the reasoning; the record set fills in with the extraction+eval
milestone.
"""
