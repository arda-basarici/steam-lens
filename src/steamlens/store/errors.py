"""The store's typed failures — schema mismatch, rejected writes, corrupt reads.

Three kinds because the store fails for three different reasons with three
different audiences. ``SchemaVersionError`` fires at open, when the file on
disk claims a schema the running code doesn't know — an operator problem
(wrong file, older code), caught before any query runs. ``StoreDataError``
fires on read, when a stored value fails reconstruction into its contract — a
data problem, surfaced with the offending value. A rejected write (duplicate
envelope under its version key, an unrecorded run or review behind a foreign
key) raises plain ``StoreError`` — a logic problem in the calling driver,
worth crashing on. Write-side *misuse* (a naive datetime handed to a surface)
is none of these: that is a caller bug and raises ``ValueError`` at the
offending call.
"""

from __future__ import annotations


class StoreError(Exception):
    """Base for the store's typed failures — catchable as one family.

    Raised directly when the database rejects a write the surfaces promise to
    fail loud on: a duplicate envelope or failure mark under its version key,
    or a reference to a run or review that was never recorded.
    """


class SchemaVersionError(StoreError):
    """The opened file's schema version is ahead of what this code understands.

    Raised at open, before any query. Carries both numbers in its message so
    the mismatch is diagnosable from the traceback alone. The reverse case —
    the file *behind* the code — is not an error: the migration runner brings
    the file forward.
    """


class StoreDataError(StoreError):
    """A stored value failed reconstruction into its contract on read.

    The read boundary treats the file as raw external data: enum values pass
    through their enum constructor, timestamps must parse timezone-aware. A
    value failing either check raises this instead of letting a corrupt row
    cross into the pipeline.
    """
