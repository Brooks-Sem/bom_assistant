import json
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from models import ArtifactRecord, TaskRecord

_BASE_DIR = Path(__file__).parent
DB_PATH = _BASE_DIR / "data" / "bom_assistant.db"
BLOB_ROOT = _BASE_DIR / "data" / "blobs"
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _Store:
    def __init__(self, db_path: Path = DB_PATH, blob_root: Path = BLOB_ROOT) -> None:
        self._db_path = db_path
        self._blob_root = blob_root
        db_path.parent.mkdir(parents=True, exist_ok=True)
        blob_root.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with _LOCK:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id        TEXT PRIMARY KEY,
                    parent_task_id TEXT REFERENCES tasks(task_id),
                    task_type      TEXT NOT NULL,
                    status         TEXT NOT NULL,
                    company_name   TEXT,
                    source_label   TEXT,
                    user_instruction TEXT NOT NULL DEFAULT '',
                    summary        TEXT NOT NULL DEFAULT '',
                    row_count      INTEGER NOT NULL DEFAULT 0,
                    metadata_json  TEXT,
                    created_at     TEXT NOT NULL,
                    updated_at     TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_created
                    ON tasks(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_tasks_company
                    ON tasks(company_name);

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id   TEXT PRIMARY KEY,
                    task_id       TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    artifact_type TEXT NOT NULL,
                    version       INTEGER NOT NULL DEFAULT 1,
                    storage_key   TEXT NOT NULL,
                    file_name     TEXT NOT NULL,
                    content_type  TEXT NOT NULL,
                    metadata_json TEXT,
                    created_at    TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_artifacts_task
                    ON artifacts(task_id);
                CREATE INDEX IF NOT EXISTS idx_artifacts_type_ver
                    ON artifacts(task_id, artifact_type, version DESC);
            """)


class TaskStore(_Store):

    def create(
        self,
        *,
        task_type: str,
        status: str,
        parent_task_id: str | None = None,
        company_name: str | None = None,
        source_label: str | None = None,
        user_instruction: str = "",
        summary: str = "",
        row_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> TaskRecord:
        now = _now()
        rec = TaskRecord(
            task_id=str(uuid.uuid4()),
            parent_task_id=parent_task_id,
            task_type=task_type,
            status=status,
            company_name=company_name,
            source_label=source_label,
            user_instruction=user_instruction,
            summary=summary,
            row_count=row_count,
            metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
            created_at=now,
            updated_at=now,
        )
        with self._conn() as c:
            c.execute(
                """INSERT INTO tasks
                   (task_id, parent_task_id, task_type, status, company_name,
                    source_label, user_instruction, summary, row_count,
                    metadata_json, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rec.task_id, rec.parent_task_id, rec.task_type, rec.status,
                    rec.company_name, rec.source_label, rec.user_instruction,
                    rec.summary, rec.row_count, rec.metadata_json,
                    rec.created_at, rec.updated_at,
                ),
            )
        return rec

    def get(self, task_id: str) -> TaskRecord | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        return TaskRecord(**dict(row)) if row else None

    def search(self, filters: dict[str, Any] | None = None) -> list[TaskRecord]:
        f = filters or {}
        clauses = ["1=1"]
        params: list[Any] = []

        if v := f.get("company_name"):
            clauses.append("company_name LIKE ?")
            params.append(f"%{v}%")
        if v := f.get("task_type"):
            clauses.append("task_type=?")
            params.append(v)
        if v := f.get("status"):
            clauses.append("status=?")
            params.append(v)
        if v := f.get("date_from"):
            clauses.append("date(created_at)>=date(?)")
            params.append(v)
        if v := f.get("date_to"):
            clauses.append("date(created_at)<=date(?)")
            params.append(v)
        keywords = [str(kw).strip() for kw in (f.get("keywords") or []) if str(kw).strip()]
        if keywords:
            kw_parts = []
            for kw in keywords:
                like = f"%{kw}%"
                kw_parts.append("(company_name LIKE ? OR source_label LIKE ? OR summary LIKE ? OR user_instruction LIKE ?)")
                params.extend([like, like, like, like])
            clauses.append(f"({' OR '.join(kw_parts)})")

        limit = min(max(int(f.get("limit", 20)), 1), 50)
        sql = f"SELECT * FROM tasks WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [TaskRecord(**dict(r)) for r in rows]


class ArtifactStore(_Store):

    def save(
        self,
        *,
        task_id: str,
        artifact_type: str,
        version: int = 1,
        file_name: str = "",
        content_type: str,
        source_path: str | None = None,
        content: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRecord:
        aid = str(uuid.uuid4())
        target_dir = self._blob_root / task_id
        target_dir.mkdir(parents=True, exist_ok=True)

        if source_path:
            src = Path(source_path)
            resolved_name = file_name or src.name
            dest = target_dir / f"{aid}{src.suffix.lower()}"
            shutil.copy2(src, dest)
            storage_key = dest.as_posix()
        elif content is not None:
            ext = ".json" if artifact_type == "normalized_bom" else ".bin"
            resolved_name = file_name or f"{artifact_type}{ext}"
            dest = target_dir / f"{aid}{ext}"
            if isinstance(content, (dict, list)):
                dest.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                dest.write_bytes(content if isinstance(content, bytes) else str(content).encode())
            storage_key = dest.as_posix()
        else:
            raise ValueError("source_path or content required")

        rec = ArtifactRecord(
            artifact_id=aid,
            task_id=task_id,
            artifact_type=artifact_type,
            version=version,
            storage_key=storage_key,
            file_name=resolved_name,
            content_type=content_type,
            metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
            created_at=_now(),
        )
        with self._conn() as c:
            c.execute(
                """INSERT INTO artifacts
                   (artifact_id, task_id, artifact_type, version, storage_key,
                    file_name, content_type, metadata_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    rec.artifact_id, rec.task_id, rec.artifact_type, rec.version,
                    rec.storage_key, rec.file_name, rec.content_type,
                    rec.metadata_json, rec.created_at,
                ),
            )
        return rec

    def get_latest_bom(self, task_id: str) -> tuple[ArtifactRecord, dict] | None:
        with self._conn() as c:
            row = c.execute(
                """SELECT * FROM artifacts
                   WHERE task_id=? AND artifact_type='normalized_bom'
                   ORDER BY version DESC LIMIT 1""",
                (task_id,),
            ).fetchone()
        if not row:
            return None
        rec = ArtifactRecord(**dict(row))
        payload = json.loads(Path(rec.storage_key).read_text(encoding="utf-8"))
        return rec, payload

    def get_by_task(self, task_id: str) -> list[ArtifactRecord]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM artifacts WHERE task_id=? ORDER BY version DESC",
                (task_id,),
            ).fetchall()
        return [ArtifactRecord(**dict(r)) for r in rows]
