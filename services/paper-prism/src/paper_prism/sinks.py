"""Persistence sinks (PRD §3.2 step 5, §4).

- LocalJsonSink: writes documents as JSON under ./output for local P1 validation.
- FirestoreSink: writes to the real `runs` / `run_status` collections.

Both are idempotent: deterministic doc IDs mean re-runs overwrite (PRD §3.3).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Protocol

from .models import RunDocument, RunStatus

log = logging.getLogger("paper_prism.sinks")


class Sink(Protocol):
    def write_run(self, doc: RunDocument) -> None: ...
    def write_status(self, status: RunStatus) -> None: ...


class LocalJsonSink:
    def __init__(self, output_dir: str = "output") -> None:
        self.runs_dir = os.path.join(output_dir, "runs")
        self.status_dir = os.path.join(output_dir, "run_status")
        os.makedirs(self.runs_dir, exist_ok=True)
        os.makedirs(self.status_dir, exist_ok=True)

    def write_run(self, doc: RunDocument) -> None:
        path = os.path.join(self.runs_dir, f"{doc.doc_id}.json")
        _dump(path, doc.to_dict())
        log.info("wrote %s (%d papers)", path, len(doc.papers))

    def write_status(self, status: RunStatus) -> None:
        path = os.path.join(self.status_dir, f"{status.doc_id}.json")
        _dump(path, status.to_dict())
        log.info("wrote %s", path)


class FirestoreSink:
    def __init__(self, project: str | None = None, database: str | None = None) -> None:
        from google.cloud import firestore  # imported lazily

        # `database` selects a named (non-default) Firestore database; None uses
        # the "(default)" database. `google.cloud.firestore` treats None as the
        # default, so passing it through is safe when unset.
        kwargs: dict[str, str] = {}
        if project:
            kwargs["project"] = project
        if database:
            kwargs["database"] = database
        self.db = firestore.Client(**kwargs)

    def write_run(self, doc: RunDocument) -> None:
        self.db.collection("runs").document(doc.doc_id).set(doc.to_dict())
        log.info("Firestore: runs/%s (%d papers)", doc.doc_id, len(doc.papers))

    def write_status(self, status: RunStatus) -> None:
        self.db.collection("run_status").document(status.doc_id).set(status.to_dict())
        log.info("Firestore: run_status/%s", status.doc_id)


def build_sink(
    name: str,
    output_dir: str,
    project: str | None,
    database: str | None = None,
) -> Sink:
    if name == "firestore":
        return FirestoreSink(project, database)
    return LocalJsonSink(output_dir)


def _dump(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, default=_json_default)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    raise TypeError(f"not JSON serializable: {type(value)}")
