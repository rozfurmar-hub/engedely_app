# pages/01_Admin.py
# -----------------
# Egyszerű, jelszóval védett admin felület:
# - összes beküldött rekord megjelenítése táblázatban
# - szűrés névre és születési dátumra (YYYY-MM-DD)
# - letöltés CSV-ben (a szűrt nézet alapján)
# - nyers JSON-ok letöltése ZIP-ben
# Megjegyzés: a Streamlit Cloud fájlrendszere nem hosszú távú tárolásra való.
# Javasolt rendszeresen exportálni.

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# A projekt gyökerét (BASE_DIR) a datakezelo.py szolgáltatja.
# Ennek a repo gyökerére kell mutatnia, ahol a "data/" mappa is található.
from datakezelo import BASE_DIR


# ========== Közművek / titkolvasás ==========

def _get_secret(name: str, default: str | None = None) -> str | None:
    """Egységes titkolvasás (Streamlit Secrets -> környezeti változó)."""
    if name in st.secrets:
        return str(st.secrets[name])
    import os
    return os.environ.get(name, default)


# ========== Jogosultság / bejelentkezés ==========

def _admin_password_ok() -> bool:
    """Egyszerű jelszó-ellenőrzés a titok alapján."""
    required = _get_secret("APP_ADMIN_PASSWORD")
    if not required:
        return False
    if "admin_auth" not in st.session_state:
        st.session_state["admin_auth"] = False
    return st.session_state["admin_auth"]


def _login_box() -> None:
    """Bejelentkezés UI (oldalsáv)."""
    st.sidebar.header("Admin bejelentkezés")
    pwd = st.sidebar.text_input("Jelszó", type="password")
    if st.sidebar.button("Belépés", use_container_width=True):
        if pwd and pwd == _get_secret("APP_ADMIN_PASSWORD"):
            st.session_state["admin_auth"] = True
            st.toast("Sikeres bejelentkezés.", icon="✅")
        else:
            st.session_state["admin_auth"] = False
            st.sidebar.error("Hibás jelszó.")


# ========== Rekordok beolvasása / normalizálása ==========

def _coerce_record(obj: Any) -> dict:
    """
    Beolvasott JSON bármilyen alakját egységes dictté alakítja.
    Kezelt esetek:
      - dict: visszaadjuk (ha payload/record/data alatt van a tartalom, azt bontjuk ki)
      - list: ha az első elem dict, azt vesszük
      - egyéb: üres dict
    """
    # 1) dict
    if isinstance(obj, dict):
        for k in ("payload", "record", "data"):
            inner = obj.get(k)
            if isinstance(inner, dict):
                return inner
        return obj

    # 2) lista -> első elem, ha dict
    if isinstance(obj, list) and obj:
        first = obj[0]
        if isinstance(first, dict):
            return first

    # 3) nem értelmezhető
    return {}


def _load_all_records() -> list[dict]:
    """Összes JSON rekord beolvasása a data/ mappából egységesített dict formában."""
    items: list[dict] = []
    data_dir: Path = BASE_DIR / "data"
    if not data_dir.exists():
        return items

    for p in sorted(data_dir.glob("*.json")):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            rec = _coerce_record(raw)
            if rec:
                # ha az azonosító a külső objektumban volt, vegyük át
                if "id" not in rec and isinstance(raw, dict) and "id" in raw:
                    rec["id"] = raw.get("id")
                items.append(rec)
        except Exception:
            # hibás JSON: kihagyjuk
            continue
    return items


def _to_dataframe(items: list[dict]) -> pd.DataFrame:
    """Normalizált DataFrame a fontos oszlopokkal – robusztus vegyes struktúrákra."""
    if not items:
        return pd.DataFrame()

    cols = [
        "id", "nev", "szuletesi_nev", "szuletesi_datum", "szuletesi_hely",
        "anyja_leanykori_neve", "csaladi_allapot", "vegzettseg",
        "szakkepzettseg", "magyarorszagra_erkezese_elotti_lakcim",
        "magyarorszagra_erkezese_elotti_foglalkozas",
        "utlevel_szam", "utlevel_lejarat",
        "tartozkodasi_engedely_szam", "tartozkodasi_engedely_lejarat",
        "jelenlegi_engedely_szama", "jelenlegi_engedely_ervenyessege",
        "fertozo_betegseg", "kiskoru_gyermek_magyarorszagon",
        "lakcim",
    ]

    norm: list[dict] = []
    for r in items:
        if not isinstance(r, dict):
            r = _coerce_record(r)
        row = {c: r.get(c, "") for c in cols}
        # Fallback név: ha csak "name" kulcs van
        if not row["nev"]:
            row["nev"] = r.get("name", "")
        norm.append(row)

    df = pd.DataFrame(norm)
    if "id" in df.columns:
        # Szöveges id esetén is stabil rendezés
        df = df.sort_values(by="id", ascending=False, kind="stable")
    return df


# ========== Letöltések ==========

def _csv_bytes(df: pd.DataFrame) -> bytes:
    """A szűrt táblázat CSV-be (UTF-8 BOM-mal, hogy Excel barátságos legyen)."""
    return df.to_csv(index=False).encode("utf-8-sig")


def _json_zip_bytes() -> bytes:
    """A data/*.json fájlok ZIP-be csomagolva letöltéshez."""
    buf = io.BytesIO()
    data_dir = BASE_DIR / "data"
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if data_dir.exists():
            for p in sorted(data_dir.glob("*.json")):
                zf.write(p, arcname=p.name)
    buf.seek(0)
    return buf.getvalue()


# ========== Oldal tartalma ==========

st.set_page_config(page_title="Admin – Engedély hosszabbítás", page_icon="🔐", layout="wide")
st.title("🔐 Admin felület – beküldött rekordok")

# Bejelentkezés
if not _admin_password_ok():
    _login_box()
    st.stop()

st.success("Admin mód aktív. Az összes rekord megjelenítve.")

# Adatbetöltés
items = _load_all_records()
if not items:
    st.info("Jelenleg nincs elérhető rekord a `data/` mappában.")
    st.stop()

# (Opcionális) nyers minták megjelenítése – hibaelhárításnál hasznos
with st.expander("Nyers minta (debug)", expanded=False):
    for i, it in enumerate(items[:5], start=1):
        st.markdown(f"**Minta #{i}**")
        st.code(json.dumps(it, ensure_ascii=False, indent=2), language="json")

# Szűrők
with st.expander("Szűrés", expanded=True):
    c1, c2 = st.columns([2, 1])
    name_filter = c1.text_input("Szűrés névre (részsztring)", placeholder="pl. 'Nagy'")
    dob_filter = c2.text_input("Szűrés születési dátumra (YYYY-MM-DD)", placeholder="pl. 1990-05-12")

df = _to_dataframe(items)

if name_filter:
    df = df[df["nev"].astype(str).str.contains(name_filter, case=False, na=False)]
if dob_filter:
    df = df[df["szuletesi_datum"] == dob_filter]

st.caption(f"Találatok száma: {len(df)}")
st.dataframe(df, use_container_width=True, height=520)

# Letöltések
lc1, lc2 = st.columns(2)
with lc1:
    st.download_button(
        "⬇️ Összes (szűrt) rekord CSV-ben",
        data=_csv_bytes(df),
        file_name="osszes_rekord.csv",
        mime="text/csv",
        use_container_width=True,
    )
with lc2:
    st.download_button(
        "⬇️ Nyers JSON-ok ZIP-ben",
        data=_json_zip_bytes(),
        file_name="rekordok_json.zip",
        mime="application/zip",
        use_container_width=True,
    )

# ---- Frissítés és fájllista diagnosztika ----
c_refresh, c_list = st.columns([1, 2])
with c_refresh:
    if st.button("🔄 Frissítés (adatok újraolvasása)", use_container_width=True):
        st.experimental_rerun()

with c_list:
    with st.expander("Fájllista a data/ mappában", expanded=False):
        data_dir = BASE_DIR / "data"
        if data_dir.exists():
            files = sorted([p.name for p in data_dir.glob("*.json")])
            st.write(f"Fájlok száma: **{len(files)}**")
            st.write(files[:100])  # legfeljebb 100 név
        else:
            st.warning("A `data/` mappa nem létezik.")

st.info(
    "Megjegyzés: a Streamlit Cloud fájlrendszere nem hosszú távú tárolásra való. "
    "Javasolt rendszeresen letölteni a CSV/ZIP exportot, vagy beállítani külső tartós tárolót "
    "(pl. adatbázis, Google Sheets)."
)

