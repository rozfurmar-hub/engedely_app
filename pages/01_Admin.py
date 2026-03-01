# pages/01_Admin.py
# ------------------------------------------------------
# Jelszóval védett admin oldal:
# - Összes beküldött rekord táblázatban
# - Szűrés névre és születési dátumra (YYYY-MM-DD)
# - CSV export (a szűrt nézetből)
# - JSON-ok ZIP export
# - Fájllista + feldolgozási statisztika + kihagyott fájlok okkal
# - Frissítés gomb (st.rerun)
#
# Megjegyzés: a Streamlit Cloud fájlrendszere nem tartós tároló.
# Exportálj rendszeresen CSV/ZIP-be, vagy kössünk be tartós tárat.

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any, Tuple

import pandas as pd
import streamlit as st

# A projektszintű BASE_DIR: a repo gyökerére kell mutatnia (ahol a data/ is van)
from datakezelo import BASE_DIR


# ========== Segédek / titkolvasás ==========

def _get_secret(name: str, default: str | None = None) -> str | None:
    if name in st.secrets:
        return str(st.secrets[name])
    import os
    return os.environ.get(name, default)


# ========== Jogosultság ==========

def _admin_password_ok() -> bool:
    required = _get_secret("APP_ADMIN_PASSWORD")
    if not required:
        return False
    if "admin_auth" not in st.session_state:
        st.session_state["admin_auth"] = False
    return st.session_state["admin_auth"]


def _login_box() -> None:
    st.sidebar.header("Admin bejelentkezés")
    pwd = st.sidebar.text_input("Jelszó", type="password")
    if st.sidebar.button("Belépés", use_container_width=True):
        if pwd and pwd == _get_secret("APP_ADMIN_PASSWORD"):
            st.session_state["admin_auth"] = True
            st.toast("Sikeres bejelentkezés.", icon="✅")
        else:
            st.session_state["admin_auth"] = False
            st.sidebar.error("Hibás jelszó.")


# ========== JSON normalizálás (robosztus) ==========

def _coerce_record(obj: Any) -> Tuple[dict, str]:
    """
    Megpróbáljuk egységes DICTré alakítani a beolvasott JSON-t.
    Visszatér: (rekord_dict, figyelmeztetés_szöveg).
    Ha nem sikerül értelmezni, egy minimális sort adunk vissza és jelzést.
    """
    # 1) dict eset: ha payload/record/data alatt van, bontsuk ki
    if isinstance(obj, dict):
        for k in ("payload", "record", "data"):
            inner = obj.get(k)
            if isinstance(inner, dict):
                return inner, ""
        return obj, ""
    # 2) lista: első elem, ha dict
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict):
            return obj[0], ""
        # lista, de nem dict elemek -> nem értelmezhető
        return {"_raw": json.dumps(obj, ensure_ascii=False)}, "Lista, de nincs benne dict; nyers tartalom mentve."
    # 3) ismeretlen típus
    return {"_raw": str(obj)}, "Nem dict/list JSON; nyers tartalom mentve."


def _load_all_records() -> Tuple[list[dict], list[str], list[str]]:
    """
    Beolvassa a data/ mappa összes .json fájlját.
    Visszatér:
      - items: normalizált rekordok listája (dict)
      - skipped: kihagyott fájlnevek listája (ha JSON hiba)
      - notes: megjegyzések listája (pl. szokatlan szerkezet)
    """
    items: list[dict] = []
    skipped: list[str] = []
    notes: list[str] = []

    data_dir: Path = BASE_DIR / "data"
    if not data_dir.exists():
        return items, skipped, notes

    for p in sorted(data_dir.glob("*.json")):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            skipped.append(p.name)
            continue

        rec, warn = _coerce_record(raw)
        # ha az azonosító a külsőben volt, vegyük át
        if "id" not in rec and isinstance(raw, dict) and "id" in raw:
            rec["id"] = raw.get("id")
        # minimális „name” --> „nev” átvezetés (ha csak így szerepel)
        if "nev" not in rec and "name" in rec:
            rec["nev"] = rec.get("name", "")

        items.append(rec)
        if warn:
            notes.append(f"{p.name}: {warn}")

    return items, skipped, notes


def _to_dataframe(items: list[dict]) -> pd.DataFrame:
    cols = [
        "id", "nev", "szuletesi_nev", "szuletesi_datum", "szuletesi_hely",
        "anyja_leanykori_neve", "csaladi_allapot", "vegzettseg",
        "szakkepzettseg", "magyarorszagra_erkezese_elotti_lakcim",
        "magyarorszagra_erkezese_elotti_foglalkozas",
        "utlevel_szam", "utlevel_lejarat",
        "tartozkodasi_engedely_szam", "tartozkodasi_engedely_lejarat",
        "jelenlegi_engedely_szama", "jelenlegi_engedely_ervenyessege",
        "fertozo_betegseg", "kiskoru_gyermek_magyarorszagon",
        "lakcim"
    ]
    if not items:
        return pd.DataFrame(columns=cols)

    norm = []
    for r in items:
        if not isinstance(r, dict):
            # védősín – elvileg ide nem jutunk a _coerce_record miatt
            r = {"_raw": str(r)}
        row = {c: r.get(c, "") for c in cols}
        # ha csak _raw van, legalább tegyük a 'nev' oszlopba a nyers mintát
        if not row["nev"]:
            row["nev"] = r.get("name", r.get("_raw", ""))
        norm.append(row)

    df = pd.DataFrame(norm, columns=cols)
    if "id" in df.columns:
        df = df.sort_values(by="id", ascending=False, kind="stable")
    return df


# ========== Letöltések ==========

def _csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def _json_zip_bytes() -> bytes:
    buf = io.BytesIO()
    data_dir = BASE_DIR / "data"
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if data_dir.exists():
            for p in sorted(data_dir.glob("*.json")):
                zf.write(p, arcname=p.name)
    buf.seek(0)
    return buf.getvalue()


# ========== Oldal ==========

st.set_page_config(page_title="Admin – Engedély hosszabbítás", page_icon="🔐", layout="wide")
st.title("🔐 Admin felület – beküldött rekordok")

# Belépés
if not _admin_password_ok():
    _login_box()
    st.stop()

st.success("Admin mód aktív. Az összes rekord megjelenítve.")

# Frissítés + fájllista
c_refresh, c_list = st.columns([1, 2])
with c_refresh:
    if st.button("🔄 Frissítés (adatok újraolvasása)", use_container_width=True):
        st.rerun()  # új Streamlit API

with c_list:
    with st.expander("Fájllista a data/ mappában", expanded=False):
        data_dir = BASE_DIR / "data"
        if data_dir.exists():
            files = sorted([p.name for p in data_dir.glob("*.json")])
            st.write(f"Fájlok száma: **{len(files)}**")
            st.write(files[:100])
        else:
            st.warning("A `data/` mappa nem létezik.")

# Adatok beolvasása
items, skipped, notes = _load_all_records()
total = len(items) + len(skipped)

with st.expander("Feldolgozási statisztika", expanded=False):
    st.write(f"Összes .json fájl: **{total}**")
    st.write(f"Sikeresen beolvasva: **{len(items)}**")
    st.write(f"Kihagyva (JSON hiba): **{len(skipped)}**")
    if skipped:
        st.warning("Kihagyott fájlok (nem sikerült JSON-ként beolvasni):")
        st.write(skipped)
    if notes:
        st.info("Megjegyzések szokatlan szerkezetekről:")
        for n in notes[:50]:
            st.write("• " + n)

# Nyers minták (max 5)
with st.expander("Nyers minta (debug)", expanded=False):
    for i, it in enumerate(items[:5], start=1):
        st.markdown(f"**Minta #{i}**")
        st.code(json.dumps(it, ensure_ascii=False, indent=2), language="json")

# Szűrők
with st.expander("Szűrés", expanded=True):
    c1, c2 = st.columns([2, 1])
    name_filter = c1.text_input("Szűrés névre (részsztring)", placeholder="pl. 'Nagy'")
    dob_filter = c2.text_input("Szűrés születési dátumra (YYYY-MM-DD)", placeholder="pl. 1990-05-12")

# Táblázat
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

st.info(
    "Megjegyzés: a Streamlit Cloud fájlrendszere nem tartós. "
    "Exportálj rendszeresen, vagy kössünk be tartós tárat (pl. Google Sheets / adatbázis)."
)
