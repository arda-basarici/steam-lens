"""The store's typed failures.

``SchemaVersionError`` fires at open, when the file on disk claims a schema
the running code doesn't know — an operator problem (wrong file, older code),
caught before any query runs. Write-side misuse (a naive datetime handed to
the ledger) is deliberately not a store error: that is a caller bug and
raises plain ``ValueError`` at the offending call. The read-boundary error
for values failing contract reconstruction arrives with the first
record-reading surface (the label pool).
"""

from __future__ import annotations


class StoreError(Exception):
    """Base for the store's typed failures — catchable as one family."""


class SchemaVersionError(StoreError):
    """The opened file's schema version is ahead of what this code understands.

    Raised at open, before any query. Carries both numbers in its message so
    the mismatch is diagnosable from the traceback alone. The reverse case —
    the file *behind* the code — is not an error: the migration runner brings
    the file forward.
    """
