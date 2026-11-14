"""The storefront records — each game's store facts and tag block, latest capture only.

Two independent records per game, both keyed by app id: the metadata of one
appdetails read (genres, categories, platforms, release date, the short
description) and the tag block of one store page. Each is replaced whole when
it is captured again, inside one transaction, so a reader never sees one
capture's genres beside another's platforms. No history is kept here; an
earlier state of the library is a dated copy of the file.

They live beside the reports and not on them. A report is a frozen sample,
and these facts describe the game on the day they were read: "runs on Mac"
should be as fresh as the last capture, whatever the report's age.

Reads trust nothing, like every store surface: a stored timestamp or date
re-enters the contracts through a parser that names the row when it fails.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date

from steamlens.contracts import (
    StorefrontLabel,
    StorefrontMetadata,
    StorefrontTag,
    StorefrontTagCapture,
)
from steamlens.store.convert import parse_utc_isoformat, utc_isoformat
from steamlens.store.errors import StoreDataError


class StorefrontRecords:
    """Table-backed store facts, constructed by ``Store`` with its connection.

    >>> from datetime import UTC, datetime
    >>> from steamlens.store import Store
    >>> store = Store(":memory:")
    >>> store.storefront.metadata(1145360) is None
    True
    >>> store.storefront.put_tags(StorefrontTagCapture(
    ...     app_id=1145360,
    ...     tags=(StorefrontTag(tag_id=42804, name="Action Roguelike", count=1466),),
    ...     captured_at=datetime(2026, 11, 14, tzinfo=UTC),
    ... ))
    >>> [tag.name for tag in store.storefront.tags(1145360).tags]
    ['Action Roguelike']
    >>> store.close()
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def put_metadata(self, metadata: StorefrontMetadata) -> None:
        """Record one game's store metadata, replacing any earlier capture whole."""
        cursor = self._conn.cursor()
        cursor.execute("BEGIN")
        try:
            for table in ("storefront_genres", "storefront_categories", "storefront_metadata"):
                # Table names are this module's literals, never caller input.
                cursor.execute(f"DELETE FROM {table} WHERE app_id = ?", (metadata.app_id,))
            cursor.execute(
                "INSERT INTO storefront_metadata (app_id, windows, mac, linux,"
                " release_date_text, release_date, coming_soon, short_description,"
                " captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    metadata.app_id,
                    int(metadata.windows),
                    int(metadata.mac),
                    int(metadata.linux),
                    metadata.release_date_text,
                    None if metadata.release_date is None else metadata.release_date.isoformat(),
                    int(metadata.coming_soon),
                    metadata.short_description,
                    utc_isoformat(metadata.captured_at),
                ),
            )
            cursor.executemany(
                "INSERT INTO storefront_genres (app_id, position, genre_id, description)"
                " VALUES (?, ?, ?, ?)",
                _label_rows(metadata.app_id, metadata.genres),
            )
            cursor.executemany(
                "INSERT INTO storefront_categories (app_id, position, category_id,"
                " description) VALUES (?, ?, ?, ?)",
                _label_rows(metadata.app_id, metadata.categories),
            )
            cursor.execute("COMMIT")
        except BaseException:
            cursor.execute("ROLLBACK")
            raise

    def metadata(self, app_id: int) -> StorefrontMetadata | None:
        """The latest stored metadata for ``app_id``, or ``None`` when never captured."""
        row = self._conn.execute(
            "SELECT windows, mac, linux, release_date_text, release_date, coming_soon,"
            " short_description, captured_at FROM storefront_metadata WHERE app_id = ?",
            (app_id,),
        ).fetchone()
        if row is None:
            return None
        context = f"storefront_metadata[{app_id}]"
        return StorefrontMetadata(
            app_id=app_id,
            genres=self._labels("storefront_genres", "genre_id", app_id),
            categories=self._labels("storefront_categories", "category_id", app_id),
            windows=bool(row[0]),
            mac=bool(row[1]),
            linux=bool(row[2]),
            release_date_text=None if row[3] is None else str(row[3]),
            release_date=None if row[4] is None else _parse_date(str(row[4]), context),
            coming_soon=bool(row[5]),
            short_description=str(row[6]),
            captured_at=parse_utc_isoformat(str(row[7]), context=context),
        )

    def put_tags(self, capture: StorefrontTagCapture) -> None:
        """Record one game's tag block, replacing any earlier capture whole.

        An empty ``tags`` is stored as a capture with no rows, so "the page
        carried no tags" stays distinct from "never read".
        """
        cursor = self._conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute("DELETE FROM storefront_tags WHERE app_id = ?", (capture.app_id,))
            cursor.execute(
                "DELETE FROM storefront_tag_captures WHERE app_id = ?", (capture.app_id,)
            )
            cursor.execute(
                "INSERT INTO storefront_tag_captures (app_id, captured_at) VALUES (?, ?)",
                (capture.app_id, utc_isoformat(capture.captured_at)),
            )
            cursor.executemany(
                "INSERT INTO storefront_tags (app_id, position, tag_id, name, count)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    (capture.app_id, position, tag.tag_id, tag.name, tag.count)
                    for position, tag in enumerate(capture.tags)
                ),
            )
            cursor.execute("COMMIT")
        except BaseException:
            cursor.execute("ROLLBACK")
            raise

    def tags(self, app_id: int) -> StorefrontTagCapture | None:
        """The latest stored tag block for ``app_id``, or ``None`` when never captured."""
        row = self._conn.execute(
            "SELECT captured_at FROM storefront_tag_captures WHERE app_id = ?", (app_id,)
        ).fetchone()
        if row is None:
            return None
        rows = self._conn.execute(
            "SELECT tag_id, name, count FROM storefront_tags WHERE app_id = ?"
            " ORDER BY position",
            (app_id,),
        ).fetchall()
        return StorefrontTagCapture(
            app_id=app_id,
            tags=tuple(
                StorefrontTag(tag_id=int(tag_id), name=str(name), count=int(count))
                for tag_id, name, count in rows
            ),
            captured_at=parse_utc_isoformat(
                str(row[0]), context=f"storefront_tag_captures[{app_id}]"
            ),
        )

    def _labels(self, table: str, id_column: str, app_id: int) -> tuple[StorefrontLabel, ...]:
        """One game's genre or category rows in the store's order."""
        # Table and column names are this module's literals, never caller input.
        rows = self._conn.execute(
            f"SELECT {id_column}, description FROM {table} WHERE app_id = ? ORDER BY position",
            (app_id,),
        ).fetchall()
        return tuple(
            StorefrontLabel(id=int(label_id), description=str(description))
            for label_id, description in rows
        )


def _label_rows(
    app_id: int, labels: Sequence[StorefrontLabel]
) -> list[tuple[int, int, int, str]]:
    """Child-table rows for one game's labels, numbered in the given order."""
    return [
        (app_id, position, label.id, label.description)
        for position, label in enumerate(labels)
    ]


def _parse_date(text: str, context: str) -> date:
    """The calendar date stored as ``text``; ``StoreDataError`` naming the row if it isn't one."""
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise StoreDataError(f"{context}: unparseable release date {text!r}") from exc
