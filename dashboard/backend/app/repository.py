import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Iterator

from .settings import DATABASE_PATH, DEFAULT_THRESHOLD


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self) -> None:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(DATABASE_PATH, timeout=20)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS predictions (
                    record_id TEXT PRIMARY KEY,
                    produced_at TEXT,
                    part TEXT,
                    part_no TEXT,
                    part_name TEXT NOT NULL,
                    equip_cd TEXT,
                    equip_name TEXT,
                    supported INTEGER NOT NULL,
                    unsupported_reason TEXT,
                    defect_probability REAL,
                    threshold REAL NOT NULL,
                    predicted_label INTEGER,
                    prediction TEXT NOT NULL,
                    inspection_status TEXT,
                    model_version TEXT NOT NULL,
                    process_values TEXT NOT NULL DEFAULT '{}',
                    predictable INTEGER NOT NULL DEFAULT 1,
                    missing_features TEXT NOT NULL DEFAULT '[]',
                    input_warnings TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS prediction_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL,
                    produced_at TEXT,
                    part TEXT,
                    part_name TEXT NOT NULL,
                    equip_cd TEXT,
                    equip_name TEXT,
                    supported INTEGER NOT NULL,
                    defect_probability REAL,
                    threshold REAL NOT NULL,
                    predicted_label INTEGER,
                    prediction TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    replay_sequence INTEGER,
                    replay_cycle INTEGER,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS prediction_events_created_idx
                    ON prediction_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS prediction_events_equipment_idx
                    ON prediction_events(equip_cd, id DESC);

                CREATE TABLE IF NOT EXISTS inspections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL UNIQUE,
                    worker_id TEXT NOT NULL,
                    worker_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    actual_label TEXT,
                    defect_type TEXT,
                    checked_items TEXT NOT NULL DEFAULT '[]',
                    action TEXT,
                    additional_inspection INTEGER NOT NULL DEFAULT 0,
                    evaluation TEXT,
                    FOREIGN KEY (record_id) REFERENCES predictions(record_id)
                );

                CREATE TABLE IF NOT EXISTS threshold_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    previous_threshold REAL NOT NULL,
                    new_threshold REAL NOT NULL,
                    changed_by TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    changed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO app_state(key, value) VALUES ('current_threshold', ?)",
                (str(DEFAULT_THRESHOLD),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO app_state(key, value) VALUES ('demo_cursor', '0')"
            )
            cursor_value = connection.execute(
                "SELECT value FROM app_state WHERE key = 'demo_cursor'"
            ).fetchone()["value"]
            connection.execute(
                "INSERT OR IGNORE INTO app_state(key, value) VALUES ('demo_sequence', ?)",
                (cursor_value,),
            )

        self._migrate()
    def get_state(self, key: str, default: str) -> str:
        with self.connection() as connection:
            row = connection.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: Any) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO app_state(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def current_threshold(self) -> float:
        return float(self.get_state("current_threshold", str(DEFAULT_THRESHOLD)))

    def demo_cursor(self) -> int:
        return int(self.get_state("demo_cursor", "0"))

    def demo_sequence(self) -> int:
        return int(self.get_state("demo_sequence", "0"))

    def _migrate(self) -> None:
        """기존 DB에 나중에 추가된 컬럼을 보강한다."""
        additions = {
            "predictable": "INTEGER NOT NULL DEFAULT 1",
            "missing_features": "TEXT NOT NULL DEFAULT '[]'",
            "input_warnings": "TEXT NOT NULL DEFAULT '[]'",
        }
        with self.connection() as connection:
            existing = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(predictions)").fetchall()
            }
            for column, definition in additions.items():
                if column not in existing:
                    connection.execute(
                        f"ALTER TABLE predictions ADD COLUMN {column} {definition}"
                    )

            # 검색 조건으로 쓰는 컬럼에 인덱스를 만든다
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS predictions_produced_idx ON predictions (produced_at);
                CREATE INDEX IF NOT EXISTS predictions_prediction_idx ON predictions (prediction);
                CREATE INDEX IF NOT EXISTS predictions_part_name_idx ON predictions (part_name);
                CREATE INDEX IF NOT EXISTS predictions_probability_idx ON predictions (defect_probability);
                """
            )

    def save_prediction(
        self,
        result: dict[str, Any],
        replay_sequence: int | None = None,
        replay_cycle: int | None = None,
    ) -> dict[str, Any]:
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT * FROM predictions WHERE record_id = ?", (result["record_id"],)
            ).fetchone()
            if not existing:
                connection.execute(
                    """
                    INSERT INTO predictions (
                        record_id, produced_at, part, part_no, part_name, equip_cd, equip_name,
                        supported, unsupported_reason, defect_probability, threshold,
                        predicted_label, prediction, inspection_status, model_version,
                        process_values, predictable, missing_features, input_warnings, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result["record_id"], result.get("produced_at"), result.get("part"),
                        result.get("part_no"), result["part_name"], result.get("equip_cd"),
                        result.get("equip_name"), int(result["supported"]),
                        result.get("unsupported_reason"), result.get("defect_probability"),
                        result["threshold"], result.get("predicted_label"), result["prediction"],
                        result.get("inspection_status"), result["model_version"],
                        json.dumps(result.get("process_values", {}), ensure_ascii=False),
                        int(result.get("predictable", True)),
                        json.dumps(result.get("missing_features", []), ensure_ascii=False),
                        json.dumps(result.get("input_warnings", []), ensure_ascii=False),
                        result["created_at"],
                    ),
                )

            connection.execute(
                """
                INSERT INTO prediction_events (
                    record_id, produced_at, part, part_name, equip_cd, equip_name,
                    supported, defect_probability, threshold, predicted_label, prediction,
                    model_version, replay_sequence, replay_cycle, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result["record_id"], result.get("produced_at"), result.get("part"),
                    result["part_name"], result.get("equip_cd"), result.get("equip_name"),
                    int(result["supported"]), result.get("defect_probability"),
                    result["threshold"], result.get("predicted_label"), result["prediction"],
                    result["model_version"], replay_sequence, replay_cycle, result["created_at"],
                ),
            )
            row = connection.execute(
                "SELECT * FROM predictions WHERE record_id = ?", (result["record_id"],)
            ).fetchone()
        return self._prediction_row(row)

    def list_prediction_events(
        self,
        limit: int = 60,
        offset: int = 0,
        equip_cd: str | None = None,
    ) -> dict[str, Any]:
        conditions = ["supported = 1", "defect_probability IS NOT NULL"]
        params: list[Any] = []
        if equip_cd:
            conditions.append("equip_cd = ?")
            params.append(equip_cd)
        where_clause = " AND ".join(conditions)

        with self.connection() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) AS count FROM prediction_events WHERE {where_clause}",
                params,
            ).fetchone()["count"]
            rows = connection.execute(
                f"""
                SELECT * FROM prediction_events
                WHERE {where_clause}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            ).fetchall()

        items = []
        for row in rows:
            item = dict(row)
            item["event_id"] = item.pop("id")
            item["supported"] = bool(item["supported"])
            items.append(item)
        return {"items": items, "total": int(total), "limit": limit, "offset": offset}

    def list_predictions(self, limit: int = 50, equip_cd: str | None = None) -> list[dict[str, Any]]:
        with self.connection() as connection:
            if equip_cd:
                rows = connection.execute(
                    "SELECT * FROM predictions WHERE equip_cd = ? ORDER BY rowid DESC LIMIT ?",
                    (equip_cd, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM predictions ORDER BY rowid DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._prediction_row(row) for row in rows]

    # 판정 상태 묶음: 화면에서 고르는 값 -> predictions.prediction 값 목록
    PREDICTION_STATES = {
        "risk": ("불량 위험",),
        "normal": ("정상",),
        "unavailable": ("데이터 결측", "모델 지원 대상 아님", "모델 입력 범주 미지원"),
    }

    def search_predictions(
        self,
        keyword: str | None = None,
        prediction_state: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        equip_cd: str | None = None,
        limit: int = 60,
        offset: int = 0,
    ) -> dict[str, Any]:
        """예측 이력을 기간 · 판정 상태 · 키워드로 검색한다.

        키워드는 제품 ID, 제품명, 제품번호를 부분 일치로 찾는다. 기간은
        `produced_at` 문자열이 `YYYY-MM-DD HH:MM:SS` 형식이므로 날짜 접두사
        비교로 처리한다.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                "(record_id LIKE ? OR part_name LIKE ? OR IFNULL(part_no, '') LIKE ? OR IFNULL(part, '') LIKE ?)"
            )
            params.extend([like, like, like, like])

        if prediction_state and prediction_state != "all":
            values = self.PREDICTION_STATES.get(prediction_state)
            if values:
                conditions.append(f"prediction IN ({', '.join('?' for _ in values)})")
                params.extend(values)

        if date_from:
            conditions.append("produced_at >= ?")
            params.append(f"{date_from} 00:00:00")
        if date_to:
            conditions.append("produced_at <= ?")
            params.append(f"{date_to} 23:59:59")
        if equip_cd and equip_cd != "all":
            conditions.append("equip_cd = ?")
            params.append(equip_cd)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        with self.connection() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) AS count FROM predictions {where_clause}", params
            ).fetchone()["count"]
            rows = connection.execute(
                f"SELECT * FROM predictions {where_clause} ORDER BY rowid DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()

        return {
            "items": [self._prediction_row(row) for row in rows],
            "total": int(total),
            "limit": limit,
            "offset": offset,
        }

    def get_prediction(self, record_id: str) -> dict[str, Any] | None:
        """제품 하나의 예측 행을 반환한다.

        추이 그래프는 `prediction_events`를 쓰는데 여기에는 공정값과 검사 상태가
        없다. 점을 눌러 상세를 열 때 이 메서드로 원본 행을 가져온다.
        """
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM predictions WHERE record_id = ?", (record_id,)
            ).fetchone()
        return self._prediction_row(row) if row else None

    def list_inspection_queue(
        self, limit: int = 500, equip_cd: str | None = None
    ) -> list[dict[str, Any]]:
        """Return active inspection work independently of the recent-feed limit."""
        with self.connection() as connection:
            equipment_filter = "AND equip_cd = ?" if equip_cd else ""
            params = (equip_cd, limit) if equip_cd else (limit,)
            rows = connection.execute(
                f"""
                SELECT * FROM predictions
                WHERE inspection_status IN ('검사 대기', '검사 중')
                {equipment_filter}
                ORDER BY
                    CASE inspection_status WHEN '검사 중' THEN 0 ELSE 1 END,
                    defect_probability DESC,
                    rowid ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._prediction_row(row) for row in rows]

    def get_prediction(self, record_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM predictions WHERE record_id = ?", (record_id,)
            ).fetchone()
        return self._prediction_row(row) if row else None

    def summary(self, total_sample: int, equip_cd: str | None = None) -> dict[str, Any]:
        with self.connection() as connection:
            where_clause = "WHERE equip_cd = ?" if equip_cd else ""
            params = (equip_cd,) if equip_cd else ()
            counts = connection.execute(
                f"""
                SELECT
                    COUNT(*) AS received,
                    SUM(CASE WHEN supported = 1 THEN 1 ELSE 0 END) AS supported,
                    SUM(CASE WHEN supported = 0 THEN 1 ELSE 0 END) AS unsupported,
                    SUM(CASE WHEN predicted_label = 1 THEN 1 ELSE 0 END) AS risk,
                    SUM(CASE WHEN predicted_label = 0 THEN 1 ELSE 0 END) AS normal,
                    SUM(CASE WHEN inspection_status = '검사 대기' THEN 1 ELSE 0 END) AS waiting,
                    SUM(CASE WHEN inspection_status = '검사 중' THEN 1 ELSE 0 END) AS inspecting,
                    SUM(CASE WHEN inspection_status = '검사 완료' THEN 1 ELSE 0 END) AS completed
                FROM predictions {where_clause}
                """
                , params
            ).fetchone()
            inspections = connection.execute(
                f"""
                SELECT
                    SUM(CASE WHEN i.evaluation = 'TP' THEN 1 ELSE 0 END) AS tp,
                    SUM(CASE WHEN i.evaluation = 'FP' THEN 1 ELSE 0 END) AS fp,
                    SUM(CASE WHEN i.evaluation = 'FN' THEN 1 ELSE 0 END) AS fn,
                    SUM(CASE WHEN i.evaluation = 'TN' THEN 1 ELSE 0 END) AS tn
                FROM inspections i
                JOIN predictions p ON p.record_id = i.record_id
                WHERE i.completed_at IS NOT NULL {"AND p.equip_cd = ?" if equip_cd else ""}
                """,
                params,
            ).fetchone()
        result = {key: int(counts[key] or 0) for key in counts.keys()}
        result["operating"] = {key: int(inspections[key] or 0) for key in inspections.keys()}
        result["current_threshold"] = self.current_threshold()
        result["demo_cursor"] = self.demo_cursor()
        result["demo_total"] = total_sample
        result["demo_cycle"] = self.demo_sequence() // total_sample if total_sample else 0
        result["equipment_filter"] = equip_cd
        return result

    def equipment_summary(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    equip_cd,
                    MAX(equip_name) AS equip_name,
                    COUNT(*) AS received,
                    SUM(CASE WHEN supported = 1 THEN 1 ELSE 0 END) AS supported,
                    SUM(CASE WHEN predicted_label = 1 THEN 1 ELSE 0 END) AS risk,
                    SUM(CASE WHEN inspection_status = '검사 대기' THEN 1 ELSE 0 END) AS waiting,
                    SUM(CASE WHEN inspection_status = '검사 중' THEN 1 ELSE 0 END) AS inspecting,
                    MAX(produced_at) AS last_received
                FROM predictions
                WHERE equip_cd IS NOT NULL
                GROUP BY equip_cd
                ORDER BY equip_cd
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def update_threshold(self, threshold: float, actor: str, reason: str) -> dict[str, Any]:
        with self._lock:
            previous = self.current_threshold()
            changed_at = now_iso()
            with self.connection() as connection:
                connection.execute(
                    "UPDATE app_state SET value = ? WHERE key = 'current_threshold'",
                    (str(threshold),),
                )
                connection.execute(
                    """
                    INSERT INTO threshold_history(
                        previous_threshold, new_threshold, changed_by, reason, changed_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (previous, threshold, actor, reason, changed_at),
                )
        return {
            "previous_threshold": previous,
            "new_threshold": threshold,
            "changed_by": actor,
            "reason": reason,
            "changed_at": changed_at,
        }

    def threshold_history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM threshold_history ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def start_inspection(self, record_id: str, worker_id: str, worker_name: str) -> dict[str, Any]:
        with self._lock, self.connection() as connection:
            prediction = connection.execute(
                "SELECT * FROM predictions WHERE record_id = ?", (record_id,)
            ).fetchone()
            if not prediction:
                raise KeyError("예측 이력을 찾을 수 없습니다.")
            if prediction["inspection_status"] != "검사 대기":
                raise ValueError("검사 대기 상태의 제품만 검사를 시작할 수 있습니다.")
            started_at = now_iso()
            connection.execute(
                """
                INSERT INTO inspections(record_id, worker_id, worker_name, started_at)
                VALUES (?, ?, ?, ?)
                """,
                (record_id, worker_id, worker_name, started_at),
            )
            connection.execute(
                "UPDATE predictions SET inspection_status = '검사 중' WHERE record_id = ?",
                (record_id,),
            )
            row = connection.execute(
                "SELECT * FROM inspections WHERE record_id = ?", (record_id,)
            ).fetchone()
        return self._inspection_row(row)

    def complete_inspection(self, record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self.connection() as connection:
            inspection = connection.execute(
                "SELECT * FROM inspections WHERE record_id = ?", (record_id,)
            ).fetchone()
            if not inspection:
                raise KeyError("시작된 검사를 찾을 수 없습니다.")
            if inspection["completed_at"]:
                raise ValueError("이미 완료된 검사입니다.")
            if inspection["worker_id"] != payload["worker_id"]:
                raise PermissionError("검사 담당자만 결과를 입력할 수 있습니다.")
            prediction = connection.execute(
                "SELECT predicted_label FROM predictions WHERE record_id = ?", (record_id,)
            ).fetchone()
            actual_defect = payload["actual_label"] == "불량"
            predicted_defect = prediction["predicted_label"] == 1
            evaluation = ("TP" if actual_defect else "FP") if predicted_defect else ("FN" if actual_defect else "TN")
            completed_at = now_iso()
            connection.execute(
                """
                UPDATE inspections SET
                    completed_at = ?, actual_label = ?, defect_type = ?, checked_items = ?,
                    action = ?, additional_inspection = ?, evaluation = ?
                WHERE record_id = ?
                """,
                (
                    completed_at, payload["actual_label"], payload.get("defect_type"),
                    json.dumps(payload.get("checked_items", []), ensure_ascii=False),
                    payload["action"], int(payload.get("additional_inspection", False)),
                    evaluation, record_id,
                ),
            )
            connection.execute(
                "UPDATE predictions SET inspection_status = '검사 완료' WHERE record_id = ?",
                (record_id,),
            )
            row = connection.execute(
                "SELECT * FROM inspections WHERE record_id = ?", (record_id,)
            ).fetchone()
        return self._inspection_row(row)

    def list_inspections(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    i.*,
                    p.part,
                    p.part_name,
                    p.part_no,
                    p.equip_cd,
                    p.equip_name,
                    p.produced_at,
                    p.defect_probability,
                    p.prediction
                FROM inspections i JOIN predictions p ON p.record_id = i.record_id
                ORDER BY i.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._inspection_row(row) for row in rows]

    def reset_demo(self) -> None:
        with self._lock, self.connection() as connection:
            connection.execute("DELETE FROM prediction_events")
            connection.execute("DELETE FROM inspections")
            connection.execute("DELETE FROM predictions")
            connection.execute("DELETE FROM threshold_history")
            connection.execute("UPDATE app_state SET value = '0' WHERE key = 'demo_cursor'")
            connection.execute("UPDATE app_state SET value = '0' WHERE key = 'demo_sequence'")
            connection.execute(
                "UPDATE app_state SET value = ? WHERE key = 'current_threshold'",
                (str(DEFAULT_THRESHOLD),),
            )

    @staticmethod
    def _prediction_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["supported"] = bool(result["supported"])
        result["predictable"] = bool(result.get("predictable", 1))
        result["process_values"] = json.loads(result["process_values"] or "{}")
        result["missing_features"] = json.loads(result.get("missing_features") or "[]")
        result["input_warnings"] = json.loads(result.get("input_warnings") or "[]")
        return result

    @staticmethod
    def _inspection_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["additional_inspection"] = bool(result.get("additional_inspection"))
        result["checked_items"] = json.loads(result.get("checked_items") or "[]")
        return result


repository = Repository()
