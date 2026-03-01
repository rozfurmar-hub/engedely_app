# pages/01_Admin.py
import io
import json
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

# A gyökérben lévő segédek importja
from datakezelo import BASE_DIR  # BASE_DIR-nek a repo gyökerére kell mutatnia

# ----------------------------
# Közművek
# ----------------------------
def _get_secret(name: str, default: str | None = None) -> str | None:
    # Egységes secrets olvasó, ugyanúgy mint az app.py-ban
    if name in st.secrets:
        return str(st.secrets[name])
    import os
    return os.environ.get(name, default)

def _admin_password_ok() -> bool:
    """Egyszerű jelszó-ellenőrzés a titok alapján."""
    required = _get_secret("APP_ADMIN_PASSWORD")
    if not required:
        return False
    if "admin_auth" not in st.session_state:
        st.session_state["admin_auth"] = False
    return st.session_state["admin_auth"]

def _login_box():
    """Bejelentkezés UI (oldalsávon)."""
    st.sidebar.header("Admin bejelentkezés")
    pwd = st.sidebar.text_input("Jelszó", type="password")
    if st.sidebar.button("Belépés", use_container_width=True):
        if pwd and pwd == _get_secret("APP_ADMIN_PASSWORD"):
            st.session_state["admin_auth"] = True
            st.toast("Sikeres bejelentkezés.", icon="✅")
        else:
            st.session_state["admin_auth"] = False
            st.sidebar.error("Hibás jelszó.")

def _load_all_records() -> list[dict]:
    """Összes JSON rekord beolvasása a data/ mappából."""
    items: list[dict] = []
    data_dir = BASE_DIR / "data"
    if not data_dir.exists():
        return items
    for p in sorted(data_dir.glob("*.json")):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            # Ha a JSON szerkezete eltér (pl. {"id":..., "payload":{...}}),
            # itt érdemes igazítani. A kód az egyszintű dictet feltételezi.
            items.append(obj)
        except Exception:
            continue
    return items

def _to_dataframe(items: list[dict]) -> pd.DataFrame:
    """Normalizált DataFrame a fontos oszlopokkal."""
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
    norm = []
    for r in items:
        row = {c: r.get(c, "") for c in cols}
        norm.append(row)
    df = pd.DataFrame(norm)
    if "id" in df.columns:
        df = df.sort_values(by="id", ascending=False, kind="stable")
    return df

def _csv_bytes(df: pd.DataFrame) -> bytes:
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

# ----------------------------
# Oldal tartalma
# ----------------------------
st.set_page_config(page_title="Admin – Engedély hosszabbítás", page_icon="🔐", layout="wide")
st.title("🔐 Admin felület – beküldött rekordok")

# Bejelentkezés
if not _admin_password_ok():
    _login_box()
    st.stop()

# Ha beléptünk:
st.success("Admin mód aktív. Az összes rekord megjelenítve.")

# Adatbetöltés
items = _load_all_records()
if not items:
    st.info("Jelenleg nincs elérhető rekord a `data/` mappában.")
    st.stop()

# Szűrők
with st.expander("Szűrés", expanded=True):
    col1, col2 = st.columns([2, 1])
    name_filter = col1.text_input("Szűrés névre (részsztring)", placeholder="pl. 'Nagy'")
    dob_filter = col2.text_input("Szűrés születési dátumra (YYYY-MM-DD)", placeholder="pl. 1990-05-12")

df = _to_dataframe(items)

if name_filter:
    df = df[df["nev"].astype(str).str.contains(name_filter, case=False, na=False)]
if dob_filter:
    df = df[df["szuletesi_datum"] == dob_filter]

st.caption(f"Találatok száma: {len(df)}")
st.dataframe(df, use_container_width=True, height=480)

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
    "Megjegyzés: a Streamlit Cloud fájlrendszere nem hosszú távú tárolásra való. "
    "Javasolt rendszeresen letölteni a CSV-t/ZIP-et, vagy hosszú távra külső "
    "tárolót (pl. adatbázis / Google Sheets) használni."
)