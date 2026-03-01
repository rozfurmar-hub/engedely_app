# datakezelo.py
from __future__ import annotations
import json
import shutil
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

# ============== Beállítások ==============
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
JSON_PATH = DATA_DIR / "adatok.json"
BACKUP_DIR = DATA_DIR / "backups"
MAX_BACKUPS = 7  # ennyi backupot tartunk meg (forgatás)

# Kötelező mezők minimál validációhoz
REQUIRED_FIELDS = ["nev"]

# Opcionális: kulcsok, melyek (ha nem üresek) dátumként normalizálhatók
DATE_FIELDS = [
    "szuletesi_datum",
    "utlevel_lejarat",
    "tartozkodasi_engedely_lejarat",
    "jelenlegi_engedely_ervenyessege",
]

# ============== Segédfüggvények ==============
def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if not JSON_PATH.exists():
        _atomic_write_json(JSON_PATH, [])

def _atomic_write_json(path: Path, data: Any) -> None:
    """
    Biztonságos JSON írás: temp fájlba írunk, majd atomikusan cseréljük.
    Így áramkimaradás esetén sem sérül a fő fájl.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent), suffix=".tmp") as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.flush()
    tmp_path = Path(tmp.name)
    tmp_path.replace(path)  # atomikus csere a legtöbb FS-en

def _now_str() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def _normalize_date(value: str) -> str:
    """
    Nagyon egyszerű normalizálás: ha üres → "", ha van tartalom és hasonlít dátumra,
    próbáljuk YYYY-MM-DD formára hozni. Ha nem sikerül, az eredetit hagyjuk.
    (A részletes parsolás maradhat az app.py-ban, vagy ide is beépíthető.)
    """
    v = (value or "").strip()
    if not v:
        return ""
    # Itt csak egy lightweight normalizálást hagyunk; igény esetén beköthető dateutil.
    # Tegyük fel, hogy már app.py-ban egységesítettük. Itt csak visszaadjuk:
    return v

def _validate_record(rec: Dict[str, Any]) -> List[str]:
    """
    Minimál validáció: ellenőrzi a REQUIRED_FIELDS mezőket.
    Dátum mezőket (ha vannak) "egységesnek" tekinti (app-ban normalizálunk).
    """
    errors = []
    for key in REQUIRED_FIELDS:
        if not str(rec.get(key, "")).strip():
            errors.append(f"Hiányzó kötelező mező: {key}")
    # dátum "normalizálás" (non-destructive)
    for key in DATE_FIELDS:
        if key in rec:
            rec[key] = _normalize_date(str(rec[key]))
    return errors

def _load_all() -> List[Dict[str, Any]]:
    _ensure_dirs()
    with JSON_PATH.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
        except json.JSONDecodeError:
            # sérült fájl esetén próbáljuk visszaállítani utolsó backupból
            restore_ok = restore_latest_backup()
            if restore_ok:
                with JSON_PATH.open("r", encoding="utf-8") as f2:
                    return json.load(f2)
            return []

def _backup() -> None:
    """Forgó biztonsági mentés az adatokhoz."""
    ts = _now_str()
    dest = BACKUP_DIR / f"adatok_{ts}.json"
    shutil.copy2(JSON_PATH, dest)
    # Forgatás
    backups = sorted(BACKUP_DIR.glob("adatok_*.json"))
    if len(backups) > MAX_BACKUPS:
        for old in backups[: len(backups) - MAX_BACKUPS]:
            try:
                old.unlink()
            except Exception:
                pass

def restore_latest_backup() -> bool:
    """Visszaállítás a legfrissebb backupból (ha van)."""
    backups = sorted(BACKUP_DIR.glob("adatok_*.json"))
    if not backups:
        return False
    latest = backups[-1]
    shutil.copy2(latest, JSON_PATH)
    return True

# ============== Nyilvános API ==============
def list_records() -> List[Dict[str, Any]]:
    """Listázza az összes rekordot."""
    return _load_all()

def create_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Új rekord beszúrása.
    Hozzáadunk egy generált 'id' mezőt (id=timestamp+számláló), és mentjük.
    """
    data = _load_all()
    # Generáljunk egyszerű, ütközésálló azonosítót
    base = _now_str()
    counter = 1
    new_id = f"{base}"
    existing_ids = {str(x.get("id", "")) for x in data}
    while new_id in existing_ids:
        counter += 1
        new_id = f"{base}_{counter}"

    record = dict(record)  # másolat
    record["id"] = new_id

    errors = _validate_record(record)
    if errors:
        raise ValueError(" ; ".join(errors))

    # Backup az írás előtt
    if JSON_PATH.exists():
        _backup()

    data.append(record)
    _atomic_write_json(JSON_PATH, data)
    return record

def get_record(rec_id: str) -> Optional[Dict[str, Any]]:
    """Egy rekord lekérése id alapján."""
    data = _load_all()
    for r in data:
        if str(r.get("id")) == str(rec_id):
            return r
    return None

def update_record(rec_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """
    Részleges frissítés. Csak a megadott mezőket írjuk felül.
    Validációt futtatunk, majd mentjük.
    """
    data = _load_all()
    idx = next((i for i, r in enumerate(data) if str(r.get("id")) == str(rec_id)), None)
    if idx is None:
        raise KeyError(f"Nincs ilyen id: {rec_id}")

    updated = dict(data[idx])
    updated.update(patch)

    errors = _validate_record(updated)
    if errors:
        raise ValueError(" ; ".join(errors))

    if JSON_PATH.exists():
        _backup()
    data[idx] = updated
    _atomic_write_json(JSON_PATH, data)
    return updated

def delete_record(rec_id: str) -> bool:
    """Rekord törlése id alapján. True ha történt törlés."""
    data = _load_all()
    new_data = [r for r in data if str(r.get("id")) != str(rec_id)]
    if len(new_data) == len(data):
        return False
    if JSON_PATH.exists():
        _backup()
    _atomic_write_json(JSON_PATH, new_data)
    return True

def export_csv(csv_path: Path) -> Path:
    """
    Egyszerű CSV export a jelenlegi rekordokról.
    A kulcsokat a rekordokból gyűjti (unió).
    """
    rows = _load_all()
    if not rows:
        # üres CSV is legyen létrehozva egy alap fejléc nélkül
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text("", encoding="utf-8")
        return csv_path

    # fejléckulcsok előállítása (összes eltérő kulcs uniója)
    keys = set()
    for r in rows:
        keys.update(r.keys())
    header = sorted(keys)

    import csv
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in header})
    return csv_path
