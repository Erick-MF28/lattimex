# Copyright (c) 2026 LATTIMEX. Licencia MIT (ver LICENSE).
"""Base de datos local (SQLite) del Planner: flota, operarios, guías, instancias y corridas.

Todo se guarda en la computadora del usuario; nada se envía a LATTIMEX."""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

# Carpeta donde se guardan los resultados completos; la fija el servidor al arrancar.
RESULTS_DIR = Path("data") / "resultados"



def text_field(payload: dict[str, Any], key: str, default: str = "") -> str:
    value = payload.get(key, default)
    return str(value).strip() if value is not None else default


DOOR_CHOICES = ("rear", "left", "right")


def doors_field(payload: dict[str, Any], key: str = "doors") -> str:
    """Puertas reales de la caja, normalizadas a 'rear[,left][,right]'.

    Acepta lista o texto separado por comas. Sin dato utilizable se asume solo
    la trasera: el plan de descarga nunca debe proponer una puerta inexistente.
    """
    value = payload.get(key)
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, (list, tuple)):
        value = []
    chosen = {str(door).strip().lower() for door in value if str(door).strip()}
    invalid = chosen - set(DOOR_CHOICES)
    if invalid:
        raise ValueError(f"Puerta desconocida: {', '.join(sorted(invalid))}")
    return ",".join(door for door in DOOR_CHOICES if door in chosen) or "rear"


def number_field(
    payload: dict[str, Any],
    key: str,
    default: float | None = None,
    minimum: float | None = None,
) -> float | None:
    value = payload.get(key, default)
    if value in (None, ""):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} debe ser numerico") from exc
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(f"{key} fuera de rango")
    return result


class LocalStore:
    """Persistencia local; no contiene logica de ninguno de los solvers."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            brand TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            plate TEXT NOT NULL DEFAULT '',
            model_year INTEGER,
            cargo_length_cm REAL NOT NULL,
            cargo_width_cm REAL NOT NULL,
            cargo_height_cm REAL NOT NULL,
            max_volume_cm3 REAL NOT NULL,
            max_weight_kg REAL NOT NULL,
            km_per_liter REAL NOT NULL,
            doors TEXT NOT NULL DEFAULT 'rear',
            insurance_annual_mxn REAL NOT NULL DEFAULT 0,
            depreciation_monthly_mxn REAL NOT NULL DEFAULT 0,
            maintenance_per_km_mxn REAL NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS operators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT '',
            cost_per_day_mxn REAL NOT NULL DEFAULT 0,
            cost_per_hour_mxn REAL NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS instances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            depot_lat REAL NOT NULL,
            depot_lng REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'lista',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS guides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id INTEGER NOT NULL REFERENCES instances(id) ON DELETE CASCADE,
            tracking_code TEXT NOT NULL,
            recipient_name TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            address TEXT NOT NULL DEFAULT '',
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            length_cm REAL,
            width_cm REAL,
            height_cm REAL,
            volume_cm3 REAL NOT NULL,
            weight_kg REAL NOT NULL DEFAULT 0,
            fragile INTEGER NOT NULL DEFAULT 0,
            stackable INTEGER NOT NULL DEFAULT 1,
            keep_upright INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_guides_instance ON guides(instance_id);
        CREATE TABLE IF NOT EXISTS planning_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id INTEGER NOT NULL REFERENCES instances(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_runs_instance ON planning_runs(instance_id);
        CREATE TABLE IF NOT EXISTS planning_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            active_instance_id INTEGER REFERENCES instances(id) ON DELETE SET NULL,
            active_run_id INTEGER REFERENCES planning_runs(id) ON DELETE SET NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT OR IGNORE INTO planning_state (id) VALUES (1);
        CREATE TABLE IF NOT EXISTS results_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            active_run_id INTEGER REFERENCES planning_runs(id) ON DELETE SET NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT OR IGNORE INTO results_state (id) VALUES (1);
        CREATE TABLE IF NOT EXISTS route_tracking_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            state_json TEXT NOT NULL DEFAULT '{"records":[],"progress":[]}',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT OR IGNORE INTO route_tracking_state (id) VALUES (1);
        CREATE TABLE IF NOT EXISTS capture_draft (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            draft_json TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT OR IGNORE INTO capture_draft (id) VALUES (1);
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
        with self._lock, self.connect() as connection:
            connection.executescript(schema)
            instance_columns = {row[1] for row in connection.execute("PRAGMA table_info(instances)")}
            if "depot_name" not in instance_columns:
                connection.execute("ALTER TABLE instances ADD COLUMN depot_name TEXT NOT NULL DEFAULT 'Centro de distribución'")
            if "depot_address" not in instance_columns:
                connection.execute("ALTER TABLE instances ADD COLUMN depot_address TEXT NOT NULL DEFAULT ''")
            guide_columns = {row[1] for row in connection.execute("PRAGMA table_info(guides)")}
            if "fragile" not in guide_columns:
                connection.execute("ALTER TABLE guides ADD COLUMN fragile INTEGER NOT NULL DEFAULT 0")
            if "stackable" not in guide_columns:
                connection.execute("ALTER TABLE guides ADD COLUMN stackable INTEGER NOT NULL DEFAULT 1")
            if "keep_upright" not in guide_columns:
                connection.execute("ALTER TABLE guides ADD COLUMN keep_upright INTEGER NOT NULL DEFAULT 0")
            vehicle_columns = {row[1] for row in connection.execute("PRAGMA table_info(vehicles)")}
            if "doors" not in vehicle_columns:
                # Puertas reales de la caja. Las unidades dadas de alta antes de
                # esta version se quedan con la trasera: es lo mas restrictivo y
                # evita planes de descarga por una puerta que no existe.
                connection.execute("ALTER TABLE vehicles ADD COLUMN doors TEXT NOT NULL DEFAULT 'rear'")
            # La base nueva empieza vacía: el Planner ofrece cargar el ejemplo de Querétaro.

    @staticmethod
    def row_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in row.keys()}

    def list_vehicles(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM vehicles WHERE active = 1 ORDER BY name, id"
            ).fetchall()
        return [self.row_dict(row) for row in rows]

    def save_vehicle(self, payload: dict[str, Any], vehicle_id: int | None = None) -> dict[str, Any]:
        name = text_field(payload, "name")
        if not name:
            raise ValueError("El vehiculo requiere nombre")
        cargo_length = number_field(payload, "cargo_length_cm", minimum=0.01)
        cargo_width = number_field(payload, "cargo_width_cm", minimum=0.01)
        cargo_height = number_field(payload, "cargo_height_cm", minimum=0.01)
        computed_volume = float(cargo_length * cargo_width * cargo_height)
        max_volume = number_field(payload, "max_volume_cm3", computed_volume, minimum=0.01)
        max_weight = number_field(payload, "max_weight_kg", minimum=0.01)
        km_per_liter = number_field(payload, "km_per_liter", minimum=0.01)
        year_value = payload.get("model_year")
        model_year = None if year_value in (None, "") else int(year_value)
        if model_year is not None and not 1900 <= model_year <= 2200:
            raise ValueError("model_year fuera de rango")
        doors = doors_field(payload)
        values = (
            name,
            text_field(payload, "brand"),
            text_field(payload, "model"),
            text_field(payload, "plate"),
            model_year,
            cargo_length,
            cargo_width,
            cargo_height,
            max_volume,
            max_weight,
            km_per_liter,
            number_field(payload, "insurance_annual_mxn", 0, 0),
            number_field(payload, "depreciation_monthly_mxn", 0, 0),
            number_field(payload, "maintenance_per_km_mxn", 0, 0),
            doors,
        )
        with self._lock, self.connect() as connection:
            if vehicle_id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO vehicles (
                        name, brand, model, plate, model_year,
                        cargo_length_cm, cargo_width_cm, cargo_height_cm,
                        max_volume_cm3, max_weight_kg, km_per_liter,
                        insurance_annual_mxn, depreciation_monthly_mxn,
                        maintenance_per_km_mxn, doors
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                vehicle_id = int(cursor.lastrowid)
            else:
                cursor = connection.execute(
                    """
                    UPDATE vehicles SET
                        name=?, brand=?, model=?, plate=?, model_year=?,
                        cargo_length_cm=?, cargo_width_cm=?, cargo_height_cm=?,
                        max_volume_cm3=?, max_weight_kg=?, km_per_liter=?,
                        insurance_annual_mxn=?, depreciation_monthly_mxn=?,
                        maintenance_per_km_mxn=?, doors=?, active=1
                    WHERE id=?
                    """,
                    (*values, vehicle_id),
                )
                if cursor.rowcount == 0:
                    raise KeyError("Vehiculo inexistente")
            row = connection.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
        return self.row_dict(row)

    def delete_vehicle(self, vehicle_id: int) -> None:
        with self._lock, self.connect() as connection:
            cursor = connection.execute("UPDATE vehicles SET active=0 WHERE id=?", (vehicle_id,))
            if cursor.rowcount == 0:
                raise KeyError("Vehiculo inexistente")

    def list_operators(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM operators WHERE active = 1 ORDER BY name, id"
            ).fetchall()
        return [self.row_dict(row) for row in rows]

    def save_operator(self, payload: dict[str, Any], operator_id: int | None = None) -> dict[str, Any]:
        name = text_field(payload, "name")
        if not name:
            raise ValueError("El operario requiere nombre")
        values = (
            name,
            text_field(payload, "phone"),
            number_field(payload, "cost_per_day_mxn", 0, 0),
            number_field(payload, "cost_per_hour_mxn", 0, 0),
        )
        with self._lock, self.connect() as connection:
            if operator_id is None:
                cursor = connection.execute(
                    "INSERT INTO operators (name, phone, cost_per_day_mxn, cost_per_hour_mxn) VALUES (?, ?, ?, ?)",
                    values,
                )
                operator_id = int(cursor.lastrowid)
            else:
                cursor = connection.execute(
                    """
                    UPDATE operators SET name=?, phone=?, cost_per_day_mxn=?,
                        cost_per_hour_mxn=?, active=1 WHERE id=?
                    """,
                    (*values, operator_id),
                )
                if cursor.rowcount == 0:
                    raise KeyError("Operario inexistente")
            row = connection.execute("SELECT * FROM operators WHERE id=?", (operator_id,)).fetchone()
        return self.row_dict(row)

    def delete_operator(self, operator_id: int) -> None:
        with self._lock, self.connect() as connection:
            cursor = connection.execute("UPDATE operators SET active=0 WHERE id=?", (operator_id,))
            if cursor.rowcount == 0:
                raise KeyError("Operario inexistente")

    @staticmethod
    def validate_guide(payload: dict[str, Any], index: int) -> dict[str, Any]:
        lat = number_field(payload, "lat")
        lng = number_field(payload, "lng")
        if lat is None or not -90 <= lat <= 90 or lng is None or not -180 <= lng <= 180:
            raise ValueError(f"Guia {index}: coordenadas invalidas")
        dimensions = [
            number_field(payload, "length_cm", None, 0.01),
            number_field(payload, "width_cm", None, 0.01),
            number_field(payload, "height_cm", None, 0.01),
        ]
        if all(value is not None for value in dimensions):
            volume = float(dimensions[0] * dimensions[1] * dimensions[2])
        else:
            dimensions = [None, None, None]
            volume = number_field(payload, "volume_cm3", None, 0.01)
        if volume is None:
            raise ValueError(f"Guia {index}: indique dimensiones o volumen")
        return {
            "tracking_code": text_field(payload, "tracking_code", f"GUIA-{index:04d}"),
            "recipient_name": text_field(payload, "recipient_name"),
            "phone": text_field(payload, "phone"),
            "address": text_field(payload, "address"),
            "lat": lat,
            "lng": lng,
            "length_cm": dimensions[0],
            "width_cm": dimensions[1],
            "height_cm": dimensions[2],
            "volume_cm3": volume,
            "weight_kg": number_field(payload, "weight_kg", 0, 0),
            "fragile": 1 if payload.get("fragile") in (True, 1, "1", "true", "si", "sí") else 0,
            "stackable": 0 if payload.get("stackable") in (False, 0, "0", "false", "no") else 1,
            "keep_upright": 1 if payload.get("keep_upright") in (True, 1, "1", "true", "si", "sí") else 0,
            "notes": text_field(payload, "notes"),
        }

    def create_instance(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = text_field(payload, "name")
        if not name:
            raise ValueError("La instancia requiere nombre")
        depot_lat = number_field(payload, "depot_lat")
        depot_lng = number_field(payload, "depot_lng")
        depot_name = text_field(payload, "depot_name", "Centro de distribución")
        depot_address = text_field(payload, "depot_address")
        if not depot_name:
            raise ValueError("El centro de distribucion requiere nombre")
        if depot_lat is None or not -90 <= depot_lat <= 90:
            raise ValueError("Latitud del centro invalida")
        if depot_lng is None or not -180 <= depot_lng <= 180:
            raise ValueError("Longitud del centro invalida")
        raw_guides = payload.get("guides")
        if not isinstance(raw_guides, list) or not raw_guides:
            raise ValueError("La instancia requiere al menos una guia")
        guides = [self.validate_guide(guide, index) for index, guide in enumerate(raw_guides, 1)]
        with self._lock, self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO instances (name, depot_lat, depot_lng, depot_name, depot_address) VALUES (?, ?, ?, ?, ?)",
                (name, depot_lat, depot_lng, depot_name, depot_address),
            )
            instance_id = int(cursor.lastrowid)
            connection.executemany(
                """
                INSERT INTO guides (
                    instance_id, tracking_code, recipient_name, phone, address,
                    lat, lng, length_cm, width_cm, height_cm, volume_cm3,
                    weight_kg, fragile, stackable, keep_upright, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        instance_id, guide["tracking_code"], guide["recipient_name"],
                        guide["phone"], guide["address"], guide["lat"], guide["lng"],
                        guide["length_cm"], guide["width_cm"], guide["height_cm"],
                        guide["volume_cm3"], guide["weight_kg"], guide["fragile"],
                        guide["stackable"], guide["keep_upright"], guide["notes"],
                    )
                    for guide in guides
                ],
            )
        return self.get_instance(instance_id)

    def update_instance(self, instance_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        name = text_field(payload, "name")
        if not name:
            raise ValueError("La instancia requiere nombre")
        depot_lat = number_field(payload, "depot_lat")
        depot_lng = number_field(payload, "depot_lng")
        depot_name = text_field(payload, "depot_name", "Centro de distribución")
        depot_address = text_field(payload, "depot_address")
        if not depot_name:
            raise ValueError("El centro de distribucion requiere nombre")
        if depot_lat is None or not -90 <= depot_lat <= 90:
            raise ValueError("Latitud del centro invalida")
        if depot_lng is None or not -180 <= depot_lng <= 180:
            raise ValueError("Longitud del centro invalida")
        raw_guides = payload.get("guides")
        if not isinstance(raw_guides, list) or not raw_guides:
            raise ValueError("La instancia requiere al menos una guia")
        guides = [self.validate_guide(guide, index) for index, guide in enumerate(raw_guides, 1)]
        with self._lock, self.connect() as connection:
            if connection.execute("SELECT 1 FROM instances WHERE id=?", (instance_id,)).fetchone() is None:
                raise KeyError("Instancia inexistente")
            connection.execute(
                "UPDATE instances SET name=?, depot_lat=?, depot_lng=?, depot_name=?, depot_address=? WHERE id=?",
                (name, depot_lat, depot_lng, depot_name, depot_address, instance_id),
            )
            existing_ids = {
                int(row[0])
                for row in connection.execute(
                    "SELECT id FROM guides WHERE instance_id=?", (instance_id,)
                ).fetchall()
            }
            kept_ids: set[int] = set()
            for raw, guide in zip(raw_guides, guides):
                raw_id = raw.get("id")
                guide_id = int(raw_id) if raw_id not in (None, "") else None
                values = (
                    guide["tracking_code"], guide["recipient_name"], guide["phone"],
                    guide["address"], guide["lat"], guide["lng"], guide["length_cm"],
                    guide["width_cm"], guide["height_cm"], guide["volume_cm3"],
                    guide["weight_kg"], guide["fragile"], guide["stackable"],
                    guide["keep_upright"], guide["notes"],
                )
                if guide_id is not None:
                    if guide_id not in existing_ids:
                        raise ValueError(f"Guia {guide_id} no pertenece a la instancia")
                    connection.execute(
                        """
                        UPDATE guides SET tracking_code=?, recipient_name=?, phone=?,
                            address=?, lat=?, lng=?, length_cm=?, width_cm=?,
                            height_cm=?, volume_cm3=?, weight_kg=?, fragile=?,
                            stackable=?, keep_upright=?, notes=?
                        WHERE id=? AND instance_id=?
                        """,
                        (*values, guide_id, instance_id),
                    )
                    kept_ids.add(guide_id)
                else:
                    cursor = connection.execute(
                        """
                        INSERT INTO guides (
                            instance_id, tracking_code, recipient_name, phone, address,
                            lat, lng, length_cm, width_cm, height_cm, volume_cm3,
                            weight_kg, fragile, stackable, keep_upright, notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (instance_id, *values),
                    )
                    kept_ids.add(int(cursor.lastrowid))
            removed_ids = existing_ids - kept_ids
            if removed_ids:
                placeholders = ",".join("?" for _ in removed_ids)
                connection.execute(
                    f"DELETE FROM guides WHERE instance_id=? AND id IN ({placeholders})",
                    (instance_id, *sorted(removed_ids)),
                )
            connection.execute(
                """
                UPDATE planning_state
                SET active_run_id=NULL, updated_at=CURRENT_TIMESTAMP
                WHERE active_instance_id=?
                """,
                (instance_id,),
            )
        return self.get_instance(instance_id)

    def list_instances(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT i.*, COUNT(g.id) AS guide_count,
                    COALESCE(SUM(g.volume_cm3), 0) AS total_volume_cm3,
                    COALESCE(SUM(g.weight_kg), 0) AS total_weight_kg
                FROM instances i
                LEFT JOIN guides g ON g.instance_id = i.id
                GROUP BY i.id
                ORDER BY i.id DESC
                """
            ).fetchall()
        return [self.row_dict(row) for row in rows]

    def get_instance(self, instance_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
            if row is None:
                raise KeyError("Instancia inexistente")
            guides = connection.execute(
                "SELECT * FROM guides WHERE instance_id=? ORDER BY id",
                (instance_id,),
            ).fetchall()
        result = self.row_dict(row)
        result["guides"] = [self.row_dict(guide) for guide in guides]
        return result

    def delete_instance(self, instance_id: int) -> None:
        """Borra la instancia, sus guías, sus ejecuciones y los archivos de resultados."""
        with self._lock, self.connect() as connection:
            runs = [int(r[0]) for r in connection.execute(
                "SELECT id FROM planning_runs WHERE instance_id=?", (instance_id,)).fetchall()]
            cursor = connection.execute("DELETE FROM instances WHERE id=?", (instance_id,))
            if cursor.rowcount == 0:
                raise KeyError("Instancia inexistente")
        self._delete_run_files(runs)

    def delete_guide(self, instance_id: int, guide_id: int) -> None:
        with self._lock, self.connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM guides WHERE instance_id=?", (instance_id,)).fetchone()[0]
            if total <= 1:
                raise ValueError("La instancia requiere al menos una guia; elimine la instancia completa")
            cursor = connection.execute("DELETE FROM guides WHERE id=? AND instance_id=?", (guide_id, instance_id))
            if cursor.rowcount == 0:
                raise KeyError("Guia inexistente")

    @staticmethod
    def _delete_run_files(run_ids: list[int]) -> None:
        for run_id in run_ids:
            path = RESULTS_DIR / f"ejecucion_{run_id:06d}.json"
            if path.exists():
                path.unlink()

    def delete_run(self, run_id: int) -> None:
        with self._lock, self.connect() as connection:
            cursor = connection.execute("DELETE FROM planning_runs WHERE id=?", (run_id,))
            if cursor.rowcount == 0:
                raise KeyError("Ejecucion inexistente")
        self._delete_run_files([run_id])

    def delete_all_runs(self) -> int:
        with self._lock, self.connect() as connection:
            runs = [int(r[0]) for r in connection.execute("SELECT id FROM planning_runs").fetchall()]
            connection.execute("DELETE FROM planning_runs")
        self._delete_run_files(runs)
        return len(runs)

    def save_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        instance_id = int(payload.get("instance_id", 0))
        result = payload.get("result")
        if not instance_id or not isinstance(result, dict) or not isinstance(result.get("routes"), list):
            raise ValueError("Ejecucion incompleta")
        name = text_field(payload, "name", "Ejecucion LATTIMEX")
        with self._lock, self.connect() as connection:
            if connection.execute("SELECT 1 FROM instances WHERE id=?", (instance_id,)).fetchone() is None:
                raise KeyError("Instancia inexistente")
            cursor = connection.execute(
                "INSERT INTO planning_runs (instance_id, name, result_json) VALUES (?, ?, ?)",
                (instance_id, name, json.dumps(result, ensure_ascii=False)),
            )
            run_id = int(cursor.lastrowid)
            connection.execute(
                """
                UPDATE planning_state
                SET active_instance_id=?, active_run_id=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=1
                """,
                (instance_id, run_id),
            )
            connection.execute(
                """
                UPDATE results_state
                SET active_run_id=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=1
                """,
                (run_id,),
            )
        item = self.get_run(run_id, prefer_file=False)
        RESULTS_DIR.mkdir(exist_ok=True)
        (RESULTS_DIR / f"ejecucion_{run_id:06d}.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
        return item

    def list_runs(self) -> list[dict[str, Any]]:
        results = []
        RESULTS_DIR.mkdir(exist_ok=True)
        for path in RESULTS_DIR.glob("ejecucion_*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                results.append({key: item.get(key) for key in ("id","instance_id","name","created_at","instance_name")} | {"summary": item.get("result",{}).get("summary",{})})
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(results, key=lambda item: int(item.get("id") or 0), reverse=True)

    def get_run(self, run_id: int, prefer_file: bool = True) -> dict[str, Any]:
        file_path = RESULTS_DIR / f"ejecucion_{run_id:06d}.json"
        if prefer_file and file_path.is_file():
            return json.loads(file_path.read_text(encoding="utf-8"))
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT r.id, r.instance_id, r.name, r.created_at, i.name AS instance_name,
                    r.result_json
                FROM planning_runs r
                JOIN instances i ON i.id = r.instance_id
                WHERE r.id=?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError("Ejecucion inexistente")
        item = self.row_dict(row)
        item["result"] = json.loads(item.pop("result_json"))
        return item

    def get_planning_state(self) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT active_instance_id, active_run_id, updated_at FROM planning_state WHERE id=1"
            ).fetchone()
        return self.row_dict(row)

    def set_planning_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        instance_value = payload.get("active_instance_id")
        run_value = payload.get("active_run_id")
        instance_id = None if instance_value in (None, "") else int(instance_value)
        run_id = None if run_value in (None, "") else int(run_value)
        with self._lock, self.connect() as connection:
            if instance_id is not None and connection.execute(
                "SELECT 1 FROM instances WHERE id=?", (instance_id,)
            ).fetchone() is None:
                raise KeyError("Instancia inexistente")
            if run_id is not None:
                row = connection.execute(
                    "SELECT instance_id FROM planning_runs WHERE id=?", (run_id,)
                ).fetchone()
                if row is None:
                    raise KeyError("Ejecucion inexistente")
                if instance_id is None:
                    instance_id = int(row["instance_id"])
                elif int(row["instance_id"]) != instance_id:
                    raise ValueError("La ejecucion no pertenece a la instancia activa")
            connection.execute(
                """
                UPDATE planning_state
                SET active_instance_id=?, active_run_id=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=1
                """,
                (instance_id, run_id),
            )
        return self.get_planning_state()

    def get_results_state(self) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT active_run_id, updated_at FROM results_state WHERE id=1"
            ).fetchone()
        return self.row_dict(row)

    def set_results_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        run_value = payload.get("active_run_id")
        run_id = None if run_value in (None, "") else int(run_value)
        with self._lock, self.connect() as connection:
            if run_id is not None and connection.execute(
                "SELECT 1 FROM planning_runs WHERE id=?", (run_id,)
            ).fetchone() is None:
                raise KeyError("Ejecucion inexistente")
            connection.execute(
                """
                UPDATE results_state
                SET active_run_id=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=1
                """,
                (run_id,),
            )
        return self.get_results_state()

    def get_route_tracking_state(self) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT state_json, updated_at FROM route_tracking_state WHERE id=1"
            ).fetchone()
        try:
            state = json.loads(row["state_json"])
        except (TypeError, json.JSONDecodeError):
            state = {"records": [], "progress": []}
        return {
            "records": state.get("records", []),
            "progress": state.get("progress", []),
            "updated_at": row["updated_at"],
        }

    def set_route_tracking_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        records, progress = payload.get("records"), payload.get("progress")
        if not isinstance(records, list) or not isinstance(progress, list):
            raise ValueError("El seguimiento requiere records y progress")
        if len(records) > 100 or len(progress) > 20_000:
            raise ValueError("El seguimiento local supera el limite permitido")
        state_json = json.dumps(
            {"records": records, "progress": progress}, ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(state_json.encode("utf-8")) > 4_000_000:
            raise ValueError("El seguimiento local es demasiado grande")
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                UPDATE route_tracking_state
                SET state_json=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=1
                """,
                (state_json,),
            )
        return self.get_route_tracking_state()

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.connect() as connection:
            row = connection.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
        try:
            return json.loads(row["value_json"]) if row else default
        except json.JSONDecodeError:
            return default

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=CURRENT_TIMESTAMP
                """,
                (key, json.dumps(value, ensure_ascii=False, separators=(",", ":"))),
            )

    FUEL_DEFAULTS = {"mode": "auto", "fuel_type": "regular", "manual_price": 24.5, "auto": None}

    def get_fuel(self) -> dict[str, Any]:
        """Configuración de combustible y el precio que se usa (automático de la CRE o manual)."""
        from .fuel import STALE_HOURS
        cfg = {**self.FUEL_DEFAULTS, **(self.get_setting("fuel", {}) or {})}
        auto = cfg.get("auto") or None
        auto_price = (auto or {}).get("prices", {}).get(cfg["fuel_type"])
        age_h = (time.time() - float(auto.get("fetched_epoch", 0))) / 3600 if auto else None
        if cfg["mode"] == "auto" and auto_price:
            price, source = float(auto_price), "auto"
        else:
            price, source = float(cfg["manual_price"]), "manual"
        # Si se consultó sin centro de distribución (mediana nacional) y ya hay uno, conviene repetir.
        recenter = bool(auto) and not auto.get("center") and self.fuel_center() is not None
        return {**cfg, "effective_price": round(price, 2), "effective_source": source,
                "stale": cfg["mode"] == "auto" and (age_h is None or age_h > STALE_HOURS or recenter)}

    def set_fuel(self, payload: dict[str, Any]) -> dict[str, Any]:
        from .fuel import FUEL_TYPES
        cfg = {**self.FUEL_DEFAULTS, **(self.get_setting("fuel", {}) or {})}
        if "mode" in payload:
            if payload["mode"] not in ("auto", "manual"):
                raise ValueError("mode debe ser auto o manual")
            cfg["mode"] = payload["mode"]
        if "fuel_type" in payload:
            if payload["fuel_type"] not in FUEL_TYPES:
                raise ValueError("fuel_type debe ser regular, premium o diesel")
            cfg["fuel_type"] = payload["fuel_type"]
        if "manual_price" in payload:
            price = number_field(payload, "manual_price")
            if price is None or not 1 <= price <= 200:
                raise ValueError("El precio manual debe estar entre 1 y 200 MXN/L")
            cfg["manual_price"] = round(price, 2)
        if "auto" in payload:
            cfg["auto"] = payload["auto"]
        self.set_setting("fuel", cfg)
        return self.get_fuel()

    def fuel_center(self) -> tuple[float, float] | None:
        """Centro de distribución de la operación activa (o de la más reciente) para buscar precios."""
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT i.depot_lat, i.depot_lng FROM planning_state s JOIN instances i ON i.id = s.active_instance_id
                WHERE s.id = 1
                """
            ).fetchone() or connection.execute(
                "SELECT depot_lat, depot_lng FROM instances ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return (float(row[0]), float(row[1])) if row else None

    def get_capture_draft(self) -> dict[str, Any]:
        """Captura de guías aún no guardada como instancia (sobrevive a cerrar el Planner)."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT draft_json, updated_at FROM capture_draft WHERE id=1"
            ).fetchone()
        try:
            draft = json.loads(row["draft_json"]) if row["draft_json"] else None
        except json.JSONDecodeError:
            draft = None
        return {"draft": draft, "updated_at": row["updated_at"]}

    def set_capture_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        draft = payload.get("draft")
        if draft is not None:
            if not isinstance(draft, dict) or not isinstance(draft.get("guides", []), list):
                raise ValueError("El borrador requiere un objeto con la lista guides")
            if len(draft.get("guides", [])) > 5000:
                raise ValueError("El borrador supera el limite de 5000 guias")
        draft_json = None if draft is None else json.dumps(
            draft, ensure_ascii=False, separators=(",", ":"))
        if draft_json is not None and len(draft_json.encode("utf-8")) > 4_000_000:
            raise ValueError("El borrador es demasiado grande")
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE capture_draft SET draft_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=1",
                (draft_json,),
            )
        return self.get_capture_draft()


