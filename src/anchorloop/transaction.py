from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .command import display_command
from .project_lock import ProjectLock
from .safe_fs import AnchorError, SafeProjectFS


TRANSACTION_SCHEMA_VERSION = 1
DEFAULT_COMPLETED_RECEIPT_RETENTION = 128
TRANSACTION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
EVENT_ID_KEY = "event_id"
TRANSACTION_ID_KEY = "transaction_id"


class TransactionError(AnchorError):
    """Raised when a durable transaction record is invalid or unsafe."""


class TransactionRecoveryRequired(TransactionError):
    """Raised after durable preparation when replay did not finish."""


@dataclass(frozen=True)
class TransactionResult:
    transaction_id: str
    applied_operations: int
    delivered_events: int
    already_committed: bool = False


@dataclass(frozen=True)
class RecoveryReport:
    recovered_transactions: int
    already_committed_transactions: int
    delivered_events: int


@dataclass(frozen=True)
class TransactionHealth:
    pending_transactions: int
    outbox_events: int
    event_log_exists: bool


class ProjectTransaction:
    """Builder for one redo-only, write-ahead project transaction."""

    def __init__(
        self,
        manager: TransactionManager,
        transaction_id: str,
        command: str | None,
    ) -> None:
        self.manager = manager
        self.transaction_id = transaction_id
        self.command = command
        self._operations: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._paths: set[str] = set()
        self._committed = False

    def write_bytes(self, path: str | Path, content: bytes) -> ProjectTransaction:
        relative = self.manager._operation_path(path)
        self._reserve_path(relative)
        encoded = base64.b64encode(content).decode("ascii")
        self._operations.append(
            {
                "kind": "write",
                "path": relative,
                "content_base64": encoded,
                "content_size": len(content),
                "content_sha256": hashlib.sha256(content).hexdigest(),
            }
        )
        return self

    def write_text(
        self,
        path: str | Path,
        content: str,
        *,
        encoding: str = "utf-8",
    ) -> ProjectTransaction:
        return self.write_bytes(path, content.encode(encoding))

    def write_json(self, path: str | Path, value: Any) -> ProjectTransaction:
        try:
            content = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
        except (TypeError, ValueError) as error:
            raise TransactionError("Transaction JSON value is not serializable.") from error
        return self.write_text(path, content)

    def delete(self, path: str | Path) -> ProjectTransaction:
        relative = self.manager._operation_path(path)
        self._reserve_path(relative)
        self._operations.append({"kind": "delete", "path": relative})
        return self

    def emit_event(self, event: dict[str, Any]) -> ProjectTransaction:
        if not isinstance(event, dict):
            raise TransactionError("Transaction events must be JSON objects.")
        if EVENT_ID_KEY in event or TRANSACTION_ID_KEY in event:
            raise TransactionError(
                f"Transaction events may not define reserved keys '{EVENT_ID_KEY}' or "
                f"'{TRANSACTION_ID_KEY}'."
            )
        self._events.append(_json_copy(event, label="Transaction event"))
        return self

    def commit(self) -> TransactionResult:
        if self._committed:
            raise TransactionError("This ProjectTransaction instance has already been committed.")
        result = self.manager.commit(self)
        self._committed = True
        return result

    @property
    def operations(self) -> tuple[dict[str, Any], ...]:
        return tuple(_json_copy(operation, label="Transaction operation") for operation in self._operations)

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(_json_copy(event, label="Transaction event") for event in self._events)

    def _reserve_path(self, relative: str) -> None:
        key = os.path.normcase(relative)
        if key in self._paths:
            raise TransactionError(f"A transaction may mutate a path only once: {relative}")
        self._paths.add(key)


class TransactionManager:
    """Durable multi-file replay and event-outbox coordinator.

    Callers must hold ``ProjectLock`` across recovery, all state reads and
    validation, transaction construction, and commit. A prepared journal is a
    durable intent: recovery replays its final values instead of rolling them
    back. Operations and event delivery are therefore idempotent.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        completed_receipt_retention: int = DEFAULT_COMPLETED_RECEIPT_RETENTION,
    ) -> None:
        if (
            not isinstance(completed_receipt_retention, int)
            or isinstance(completed_receipt_retention, bool)
            or completed_receipt_retention < 1
        ):
            raise ValueError("Completed transaction receipt retention must be a positive integer.")
        self.fs = SafeProjectFS(Path(root))
        self.root = self.fs.root
        self.completed_receipt_retention = completed_receipt_retention
        self.anchor_dir = self.fs.path(".anchor")
        self.pending_dir = self.fs.path(".anchor", "transactions", "pending")
        self.completed_dir = self.fs.path(".anchor", "transactions", "completed")
        self.outbox_dir = self.fs.path(".anchor", "outbox")
        self.event_log_path = self.fs.path(".anchor", "events.jsonl")

    def begin(
        self,
        *,
        transaction_id: str | None = None,
        command: str | None = None,
    ) -> ProjectTransaction:
        identifier = transaction_id or uuid4().hex
        self._validate_transaction_id(identifier)
        normalized_command = command.strip() if command and command.strip() else None
        return ProjectTransaction(self, identifier, normalized_command)

    def commit(self, transaction: ProjectTransaction) -> TransactionResult:
        ProjectLock.assert_held(self.root)
        if transaction.manager is not self:
            raise TransactionError("A transaction must be committed by the manager that created it.")
        if not transaction.operations and not transaction.events:
            raise TransactionError("A transaction must contain at least one operation or event.")

        self._ensure_directories()
        record = self._record_for(transaction)
        identifier = record[TRANSACTION_ID_KEY]
        digest = record["spec_digest"]
        pending_path = self._pending_path(identifier)
        receipt_path = self._receipt_path(identifier)
        self._assert_no_unrelated_recovery(identifier)
        self._preflight_record(record)

        if self.fs.exists(receipt_path):
            self._validate_receipt(self._read_json(receipt_path), identifier, digest)
            if self.fs.exists(pending_path):
                pending = self._read_and_validate_record(pending_path)
                if pending["spec_digest"] != digest:
                    raise TransactionError(
                        f"Completed transaction '{identifier}' conflicts with its pending journal."
                    )
                self.fs.unlink(pending_path)
                _fsync_directory(pending_path.parent)
            delivered = self._flush_outbox(transaction_ids={identifier})
            result = TransactionResult(identifier, 0, delivered, already_committed=True)
            self._prune_completed_receipts()
            return result

        if self.fs.exists(pending_path):
            durable = self._read_and_validate_record(pending_path)
            if durable["spec_digest"] != digest:
                raise TransactionError(
                    f"Transaction ID '{identifier}' already belongs to a different durable intent."
                )
            record = durable
        else:
            self._write_json(pending_path, record)

        try:
            applied, delivered = self._apply_record(record, pending_path)
        except Exception as error:
            if isinstance(error, TransactionRecoveryRequired):
                raise
            raise TransactionRecoveryRequired(
                f"Transaction '{identifier}' was durably prepared but did not finish. "
                "Keep the project lock and call TransactionManager.recover(), or retry the "
                "mutating command with the same transaction ID."
            ) from error
        result = TransactionResult(identifier, applied, delivered)
        self._prune_completed_receipts()
        return result

    def _preflight_record(self, record: dict[str, Any]) -> None:
        """Reject static filesystem corruption before any application state changes."""

        for operation in record["operations"]:
            path = self.fs.path(operation["path"])
            if self.fs.exists(path) and not self.fs.is_file(path):
                raise TransactionError(f"Transaction target must be a regular file: {path}")
        # Event delivery is part of the same durable intent. Validate the log
        # before writing the journal so a pre-existing link/corrupt record does
        # not leave a newly started task waiting for repair.
        logged_events, _ = self._read_event_log()
        for event in record["events"]:
            event_id = event[EVENT_ID_KEY]
            if event_id in logged_events and logged_events[event_id] != _digest(event):
                raise TransactionError(
                    f"Event log already contains conflicting content for transaction '{record[TRANSACTION_ID_KEY]}'."
                )

    def recover(self) -> RecoveryReport:
        """Replay all prepared journals and deliver every durable outbox event."""

        ProjectLock.assert_held(self.root)
        self._ensure_directories()
        recovered_records: list[tuple[Path, dict[str, Any]]] = []
        already_committed = 0

        pending = [
            (path, self._read_and_validate_record(path))
            for path in self.fs.glob(self.pending_dir, "*.json")
        ]
        pending.sort(key=lambda item: (item[1]["created_at"], item[0].name))
        for pending_path, record in pending:
            identifier = record[TRANSACTION_ID_KEY]
            receipt_path = self._receipt_path(identifier)
            if self.fs.exists(receipt_path):
                self._validate_receipt(
                    self._read_json(receipt_path), identifier, record["spec_digest"]
                )
                self.fs.unlink(pending_path)
                _fsync_directory(pending_path.parent)
                already_committed += 1
                continue

            self._stage_record(record)
            recovered_records.append((pending_path, record))

        delivered = self._flush_outbox()
        for pending_path, record in recovered_records:
            self._write_receipt_and_finish(record, pending_path)
        report = RecoveryReport(len(recovered_records), already_committed, delivered)
        self._prune_completed_receipts()
        return report

    def inspect(self) -> TransactionHealth:
        """Validate durable recovery state without creating, deleting, or repairing files."""

        pending_paths = self.fs.glob(self.pending_dir, "*.json") if self.fs.exists(self.pending_dir) else []
        outbox_paths = self.fs.glob(self.outbox_dir, "*.json") if self.fs.exists(self.outbox_dir) else []
        for path in pending_paths:
            self._read_and_validate_record(path)
        for path in outbox_paths:
            self._validate_outbox_record(self._read_json(path), path)
        event_log_exists = self.fs.exists(self.event_log_path)
        if event_log_exists:
            self._read_event_log(repair_torn_tail=False)
        return TransactionHealth(len(pending_paths), len(outbox_paths), event_log_exists)

    def _record_for(self, transaction: ProjectTransaction) -> dict[str, Any]:
        events = []
        for index, event in enumerate(transaction.events):
            payload = dict(event)
            payload[EVENT_ID_KEY] = f"{transaction.transaction_id}:{index:04d}"
            payload[TRANSACTION_ID_KEY] = transaction.transaction_id
            events.append(payload)

        specification = {
            TRANSACTION_ID_KEY: transaction.transaction_id,
            "command": transaction.command,
            "operations": list(transaction.operations),
            "events": events,
        }
        created_at = _timestamp()
        return {
            "schema_version": TRANSACTION_SCHEMA_VERSION,
            **specification,
            "created_at": created_at,
            "spec_digest": _digest(specification),
            "journal_digest": _digest({**specification, "created_at": created_at}),
        }

    def _assert_no_unrelated_recovery(self, identifier: str) -> None:
        for path in self.fs.glob(self.pending_dir, "*.json"):
            if path != self._pending_path(identifier):
                raise TransactionRecoveryRequired(
                    "Another durable transaction is unfinished. Call TransactionManager.recover() "
                    "under the project lock before starting a new mutation."
                )
        for path in self.fs.glob(self.outbox_dir, "*.json"):
            record = self._validate_outbox_record(self._read_json(path), path)
            if record[TRANSACTION_ID_KEY] != identifier:
                raise TransactionRecoveryRequired(
                    "A durable event outbox is unfinished. Call TransactionManager.recover() under "
                    "the project lock before starting a new mutation."
                )

    def _apply_record(self, record: dict[str, Any], pending_path: Path) -> tuple[int, int]:
        applied = self._stage_record(record)
        delivered = self._flush_outbox(transaction_ids={record[TRANSACTION_ID_KEY]})
        self._write_receipt_and_finish(record, pending_path)
        return applied, delivered

    def _stage_record(self, record: dict[str, Any]) -> int:
        applied = sum(1 for operation in record["operations"] if self._apply_operation(operation))
        for event in record["events"]:
            self._persist_outbox_event(event, transaction_created_at=record["created_at"])
        return applied

    def _write_receipt_and_finish(self, record: dict[str, Any], pending_path: Path) -> None:
        identifier = record[TRANSACTION_ID_KEY]
        receipt = {
            "schema_version": TRANSACTION_SCHEMA_VERSION,
            TRANSACTION_ID_KEY: identifier,
            "spec_digest": record["spec_digest"],
            "committed_at": _timestamp(),
        }
        receipt["receipt_digest"] = _digest(receipt)
        self._write_json(self._receipt_path(identifier), receipt)
        self.fs.unlink(pending_path, missing_ok=True)
        _fsync_directory(pending_path.parent)

    def _prune_completed_receipts(self) -> int:
        """Keep a bounded idempotency window without touching pending work.

        Unreadable or malformed receipts are left for ``doctor`` instead of
        being guessed at and deleted. Garbage collection is maintenance after
        a successful transaction, so a cleanup failure never changes the
        command's committed result.
        """

        try:
            pending_ids = {path.stem for path in self.fs.glob(self.pending_dir, "*.json")}
            valid: list[tuple[datetime, str, Path]] = []
            protected: set[Path] = set()
            for path in self.fs.glob(self.completed_dir, "*.json"):
                try:
                    receipt = self._read_json(path)
                    identifier = receipt.get(TRANSACTION_ID_KEY)
                    if not isinstance(identifier, str) or path.name != f"{identifier}.json":
                        continue
                    self._validate_transaction_id(identifier)
                    self._validate_receipt(receipt, identifier, None)
                    committed_at = _parse_timestamp(
                        receipt["committed_at"],
                        label=f"Completed transaction timestamp for '{identifier}'",
                    )
                except AnchorError:
                    continue
                if identifier in pending_ids:
                    protected.add(path)
                else:
                    valid.append((committed_at, path.name, path))

            valid.sort(key=lambda item: (item[0], item[1]), reverse=True)
            keep = max(0, self.completed_receipt_retention - len(protected))
            removed = 0
            for _, _, path in valid[keep:]:
                try:
                    self.fs.unlink(path)
                except AnchorError:
                    continue
                removed += 1
            if removed:
                _fsync_directory(self.completed_dir)
            return removed
        except AnchorError:
            return 0

    def _apply_operation(self, operation: dict[str, Any]) -> bool:
        path = self.fs.path(operation["path"])
        if operation["kind"] == "delete":
            if not self.fs.exists(path):
                return False
            self.fs.unlink(path)
            _fsync_directory(path.parent)
            return True

        content = self._decode_operation_content(operation)
        if self.fs.exists(path) and self.fs.read_bytes(path) == content:
            return False
        self.fs.atomic_write_bytes(path, content)
        return True

    def _persist_outbox_event(self, event: dict[str, Any], *, transaction_created_at: str) -> None:
        event_id = event[EVENT_ID_KEY]
        record = {
            "schema_version": TRANSACTION_SCHEMA_VERSION,
            EVENT_ID_KEY: event_id,
            TRANSACTION_ID_KEY: event[TRANSACTION_ID_KEY],
            "transaction_created_at": transaction_created_at,
            "payload": event,
            "payload_digest": _digest(event),
        }
        record["record_digest"] = _digest(record)
        path = self._outbox_path(event_id)
        if self.fs.exists(path):
            current = self._read_json(path)
            if current != record:
                raise TransactionError(f"Durable outbox event '{event_id}' has conflicting content.")
            return
        self._write_json(path, record)

    def _flush_outbox(self, *, transaction_ids: set[str] | None = None) -> int:
        logged_events, log_content = self._read_event_log()
        delivered = 0
        outbox = [
            (path, self._validate_outbox_record(self._read_json(path), path))
            for path in self.fs.glob(self.outbox_dir, "*.json")
        ]
        if transaction_ids is not None:
            outbox = [item for item in outbox if item[1][TRANSACTION_ID_KEY] in transaction_ids]
        outbox.sort(key=lambda item: self._outbox_order_key(item[1]))
        for path, record in outbox:
            event_id = record[EVENT_ID_KEY]
            if event_id in logged_events:
                if logged_events[event_id] != record["payload_digest"]:
                    raise TransactionError(
                        f"Event log contains conflicting content for durable event '{event_id}'."
                    )
            else:
                prefix = "\n" if log_content and not log_content.endswith(("\n", "\r")) else ""
                line = json.dumps(
                    record["payload"], sort_keys=True, separators=(",", ":"), allow_nan=False
                ) + "\n"
                self.fs.append_text(self.event_log_path, prefix + line)
                _fsync_directory(self.event_log_path.parent)
                log_content += prefix + line
                logged_events[event_id] = record["payload_digest"]
                delivered += 1
            self.fs.unlink(path)
            _fsync_directory(path.parent)
        return delivered

    def _read_event_log(self, *, repair_torn_tail: bool = True) -> tuple[dict[str, str], str]:
        if not self.fs.exists(self.event_log_path):
            return {}, ""
        content = self.fs.read_text(self.event_log_path)
        event_ids: dict[str, str] = {}
        lines = content.splitlines(keepends=True)
        offset = 0
        for index, line in enumerate(lines):
            raw = line.rstrip("\r\n")
            if not raw.strip():
                offset += len(line)
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError as error:
                if any(item.rstrip("\r\n").strip() for item in lines[index + 1 :]):
                    raise TransactionError(
                        f"Event log is corrupt before its final record: {self.event_log_path}"
                    ) from error
                if not repair_torn_tail:
                    raise TransactionRecoveryRequired(
                        "Event log has a torn final record. Run: "
                        f"{display_command('doctor --repair')}"
                    ) from error
                content = content[:offset]
                self.fs.atomic_write_text(self.event_log_path, content)
                break
            if not isinstance(event, dict):
                raise TransactionError(f"Event log entries must be JSON objects: {self.event_log_path}")
            event_id = event.get(EVENT_ID_KEY)
            if isinstance(event_id, str) and event_id:
                digest = _digest(event)
                if event_id in event_ids and event_ids[event_id] != digest:
                    raise TransactionError(
                        f"Event log contains conflicting records for event '{event_id}'."
                    )
                event_ids[event_id] = digest
            offset += len(line)
        return event_ids, content

    def _read_and_validate_record(self, path: Path) -> dict[str, Any]:
        record = self._read_json(path)
        expected_keys = {
            "schema_version",
            TRANSACTION_ID_KEY,
            "command",
            "operations",
            "events",
            "created_at",
            "spec_digest",
            "journal_digest",
        }
        if set(record) != expected_keys:
            raise TransactionError(f"Transaction journal fields are invalid at {path}.")
        if record.get("schema_version") != TRANSACTION_SCHEMA_VERSION:
            raise TransactionError(f"Unsupported transaction journal schema at {path}.")
        identifier = record.get(TRANSACTION_ID_KEY)
        if not isinstance(identifier, str):
            raise TransactionError(f"Transaction journal has no valid ID at {path}.")
        self._validate_transaction_id(identifier)
        if path.name != f"{identifier}.json":
            raise TransactionError(f"Transaction journal ID does not match its filename: {path}")
        command = record.get("command")
        if command is not None and not isinstance(command, str):
            raise TransactionError(f"Transaction command must be text at {path}.")
        if not isinstance(record.get("created_at"), str) or not record["created_at"]:
            raise TransactionError(f"Transaction journal has no creation timestamp at {path}.")
        _validate_timestamp(record["created_at"], label=f"Transaction journal timestamp at {path}")
        operations = record.get("operations")
        events = record.get("events")
        if not isinstance(operations, list) or not isinstance(events, list):
            raise TransactionError(f"Transaction journal operations/events are invalid at {path}.")

        seen_paths: set[str] = set()
        for operation in operations:
            self._validate_operation(operation, seen_paths, path)
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                raise TransactionError(f"Transaction event is not an object at {path}.")
            expected_id = f"{identifier}:{index:04d}"
            if event.get(EVENT_ID_KEY) != expected_id or event.get(TRANSACTION_ID_KEY) != identifier:
                raise TransactionError(f"Transaction event identity is invalid at {path}.")
            _json_copy(event, label="Transaction event")

        specification = {
            TRANSACTION_ID_KEY: identifier,
            "command": command,
            "operations": operations,
            "events": events,
        }
        if record.get("spec_digest") != _digest(specification):
            raise TransactionError(f"Transaction journal digest does not match its content at {path}.")
        journal_content = {**specification, "created_at": record["created_at"]}
        if record.get("journal_digest") != _digest(journal_content):
            raise TransactionError(f"Transaction journal metadata digest is invalid at {path}.")
        return record

    def _validate_operation(
        self,
        operation: Any,
        seen_paths: set[str],
        journal_path: Path,
    ) -> None:
        if not isinstance(operation, dict) or operation.get("kind") not in {"write", "delete"}:
            raise TransactionError(f"Transaction operation is invalid at {journal_path}.")
        expected_keys = (
            {"kind", "path", "content_base64", "content_size", "content_sha256"}
            if operation["kind"] == "write"
            else {"kind", "path"}
        )
        if set(operation) != expected_keys:
            raise TransactionError(f"Transaction operation fields are invalid at {journal_path}.")
        relative = operation.get("path")
        if not isinstance(relative, str) or self._operation_path(relative) != relative:
            raise TransactionError(f"Transaction operation path is invalid at {journal_path}.")
        path_key = os.path.normcase(relative)
        if path_key in seen_paths:
            raise TransactionError(f"Transaction journal mutates a path more than once at {journal_path}.")
        seen_paths.add(path_key)
        if operation["kind"] == "write":
            self._decode_operation_content(operation)

    @staticmethod
    def _decode_operation_content(operation: dict[str, Any]) -> bytes:
        encoded = operation.get("content_base64")
        expected_size = operation.get("content_size")
        expected_digest = operation.get("content_sha256")
        if not isinstance(encoded, str) or not isinstance(expected_size, int) or expected_size < 0:
            raise TransactionError("Transaction write payload metadata is invalid.")
        if not isinstance(expected_digest, str):
            raise TransactionError("Transaction write payload digest is invalid.")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise TransactionError("Transaction write payload is not valid base64.") from error
        if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_digest:
            raise TransactionError("Transaction write payload does not match its size or digest.")
        return content

    def _validate_outbox_record(self, record: dict[str, Any], path: Path) -> dict[str, Any]:
        expected_keys = {
            "schema_version",
            EVENT_ID_KEY,
            TRANSACTION_ID_KEY,
            "transaction_created_at",
            "payload",
            "payload_digest",
            "record_digest",
        }
        if set(record) != expected_keys:
            raise TransactionError(f"Durable outbox record fields are invalid at {path}.")
        if record.get("schema_version") != TRANSACTION_SCHEMA_VERSION:
            raise TransactionError(f"Unsupported outbox schema at {path}.")
        event_id = record.get(EVENT_ID_KEY)
        transaction_id = record.get(TRANSACTION_ID_KEY)
        transaction_created_at = record.get("transaction_created_at")
        payload = record.get("payload")
        if (
            not isinstance(event_id, str)
            or not isinstance(transaction_id, str)
            or not isinstance(transaction_created_at, str)
            or not transaction_created_at
            or not isinstance(payload, dict)
        ):
            raise TransactionError(f"Invalid durable outbox record at {path}.")
        if payload.get(EVENT_ID_KEY) != event_id or payload.get(TRANSACTION_ID_KEY) != transaction_id:
            raise TransactionError(f"Outbox event identity does not match its payload at {path}.")
        _validate_timestamp(transaction_created_at, label=f"Outbox transaction timestamp at {path}")
        if record.get("payload_digest") != _digest(payload):
            raise TransactionError(f"Outbox event digest does not match its payload at {path}.")
        digest_content = {key: value for key, value in record.items() if key != "record_digest"}
        if record.get("record_digest") != _digest(digest_content):
            raise TransactionError(f"Outbox record digest does not match its metadata at {path}.")
        if path != self._outbox_path(event_id):
            raise TransactionError(f"Outbox event ID does not match its filename at {path}.")
        return record

    @staticmethod
    def _outbox_order_key(record: dict[str, Any]) -> tuple[str, str, int]:
        event_id = record[EVENT_ID_KEY]
        transaction_id = record[TRANSACTION_ID_KEY]
        prefix = f"{transaction_id}:"
        if not event_id.startswith(prefix):
            raise TransactionError(f"Outbox event ID is invalid: {event_id}")
        try:
            event_index = int(event_id[len(prefix) :])
        except ValueError as error:
            raise TransactionError(f"Outbox event sequence is invalid: {event_id}") from error
        return record["transaction_created_at"], transaction_id, event_index

    @staticmethod
    def _validate_receipt(
        receipt: dict[str, Any],
        identifier: str,
        digest: str | None,
    ) -> None:
        expected_keys = {
            "schema_version",
            TRANSACTION_ID_KEY,
            "spec_digest",
            "committed_at",
            "receipt_digest",
        }
        if (
            set(receipt) != expected_keys
            or receipt.get("schema_version") != TRANSACTION_SCHEMA_VERSION
            or receipt.get(TRANSACTION_ID_KEY) != identifier
            or not isinstance(receipt.get("spec_digest"), str)
            or (digest is not None and receipt.get("spec_digest") != digest)
        ):
            raise TransactionError(f"Completed transaction receipt conflicts for '{identifier}'.")
        committed_at = receipt.get("committed_at")
        if not isinstance(committed_at, str):
            raise TransactionError(f"Completed transaction receipt timestamp is invalid for '{identifier}'.")
        _validate_timestamp(committed_at, label=f"Completed transaction timestamp for '{identifier}'")
        digest_content = {key: value for key, value in receipt.items() if key != "receipt_digest"}
        if receipt.get("receipt_digest") != _digest(digest_content):
            raise TransactionError(f"Completed transaction receipt digest is invalid for '{identifier}'.")

    def _operation_path(self, path: str | Path) -> str:
        candidate = Path(path)
        if candidate.is_absolute():
            managed = self.fs.validate(candidate)
        else:
            managed = self.fs.path(candidate)
        relative = managed.relative_to(self.root)
        if not relative.parts:
            raise TransactionError("A transaction cannot replace the project root.")
        normalized = relative.as_posix()
        reserved = (
            ".anchor/transactions",
            ".anchor/outbox",
        )
        if normalized == ".anchor/events.jsonl" or any(
            normalized == prefix or normalized.startswith(prefix + "/") for prefix in reserved
        ):
            raise TransactionError(f"Transaction path is reserved for recovery internals: {normalized}")
        if normalized == ".anchor/project.lock":
            raise TransactionError(f"Transaction path is reserved for project locking: {normalized}")
        return normalized

    def _ensure_directories(self) -> None:
        directories = (
            self.anchor_dir,
            self.fs.path(".anchor", "transactions"),
            self.pending_dir,
            self.completed_dir,
            self.outbox_dir,
        )
        for directory in directories:
            existed = self.fs.exists(directory)
            self.fs.ensure_directory(directory)
            if not existed:
                _fsync_directory(directory.parent)
        _fsync_directory(self.anchor_dir.parent)

    def _pending_path(self, identifier: str) -> Path:
        self._validate_transaction_id(identifier)
        return self.fs.path(self.pending_dir.relative_to(self.root), f"{identifier}.json")

    def _receipt_path(self, identifier: str) -> Path:
        self._validate_transaction_id(identifier)
        return self.fs.path(self.completed_dir.relative_to(self.root), f"{identifier}.json")

    def _outbox_path(self, event_id: str) -> Path:
        filename = hashlib.sha256(event_id.encode("utf-8")).hexdigest() + ".json"
        return self.fs.path(self.outbox_dir.relative_to(self.root), filename)

    @staticmethod
    def _validate_transaction_id(identifier: str) -> None:
        if not isinstance(identifier, str):
            raise TransactionError("Transaction ID must be text.")
        portable_stem = identifier.split(".", 1)[0].upper()
        if (
            not TRANSACTION_ID_PATTERN.fullmatch(identifier)
            or identifier.endswith(".")
            or portable_stem in WINDOWS_RESERVED_NAMES
        ):
            raise TransactionError(
                "Transaction ID must be a portable 1-128 character filename using letters, digits, "
                "'.', '_' or '-'; letters must be lowercase."
            )

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            value = json.loads(self.fs.read_text(path))
        except json.JSONDecodeError as error:
            raise TransactionError(f"Durable transaction state is invalid JSON at {path}.") from error
        if not isinstance(value, dict):
            raise TransactionError(f"Durable transaction state must be an object at {path}.")
        return value

    def _write_json(self, path: Path, value: dict[str, Any]) -> None:
        self.fs.atomic_write_text(
            path, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )


def _json_copy(value: Any, *, label: str) -> Any:
    try:
        return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise TransactionError(f"{label} is not JSON serializable.") from error


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _validate_timestamp(value: str, *, label: str) -> None:
    _parse_timestamp(value, label=label)


def _parse_timestamp(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise TransactionError(f"{label} is invalid.") from error
    if parsed.tzinfo is None:
        raise TransactionError(f"{label} must include a timezone.")
    return parsed.astimezone(UTC)


def _fsync_directory(path: Path) -> None:
    """Persist a newly created or removed directory entry where supported."""

    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # Windows does not expose portable directory fsync through os.open().
        pass
    finally:
        os.close(descriptor)
