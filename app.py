# app.py — HU/RU i18n + több sablon + upsert + validáció + ZIP
# Fordító: Azure Translator (Text Translation v3) – EU régió (West/North Europe) — RU -> HU
# Chat: OpenAI (EU Project) — válasz a választott nyelven + magyar fordítás
#
# Fontos (Translator REST – regionális/custom endpoint):
#   POST {endpoint}/translator/text/v3.0/translate?api-version=3.0&to=hu
#   Fejlécek: Ocp-Apim-Subscription-Key, Ocp-Apim-Subscription-Region, Content-Type: application/json
#   (Ez a helyes path custom endpointtal.)  # Forrás: MS Translator v3 ref.  [1](https://learn.microsoft.com/en-us/answers/questions/5757291/data-privacy-zero-data-retention)[2](https://learn.microsoft.com/en-us/answers/questions/2181252/azure-openai-data-retention-privacy-2025)[3](https://developers.openai.com/api/docs/guides/completions/)
#
# Titkok (secrets) – .streamlit/secrets.toml:
#   AZURE_TRANSLATOR_KEY, AZURE_TRANSLATOR_REGION, AZURE_TRANSLATOR_ENDPOINT
#   OPENAI_API_KEY, OPENAI_PROJECT (opcionális), OPENAI_CHAT_MODEL (opcionális)

import io
import os
import re
import json
import unicodedata
import zipfile
import requests
from pathlib import Path
from datetime import datetime, date
from dateutil.parser import parse as parse_date
import streamlit as st
from docxtpl import DocxTemplate



# ---- Adatkezelő modul -------------------------
from datakezelo import BASE_DIR, create_record, list_records, update_record

# ---- Oldal beállítás ----
st.set_page_config(page_title="Engedély hosszabbítás", page_icon="🗂️", layout="centered")

# =========================
# i18n (HU + RU)
# =========================
I18N_DIR = BASE_DIR / "i18n"

def load_labels(lang: str) -> dict:
    p = I18N_DIR / f"strings_{lang}.json"
    if not p.exists():
        p = I18N_DIR / "strings_hu.json"
    if not p.exists():
        return {
            "app_title": "🗂️ Engedély hosszabbítás – Több sablonos űrlapkitöltés (upsert)",
            "app_caption": "Streamlit + docxtpl + JSON \n Több sablon egyszerre, ZIP \n Upsert: név + szül. dátum",
            "sidebar_hdr_templates": "Elérhető sablonok",
            "sidebar_dbg": "TEMPLATES_DIR: {path} \n Létezik: {exists}",
            "help_header": "ℹ️ Használati útmutató",
            "help_md": "Tedd a sablonokat a templates/ mappába, töltsd ki az űrlapot, válaszd a sablonokat, majd generálj dokumentumot.",
            "form_header": "Adatbekérő űrlap",
            "field_nev": "Név",
            "btn_generate": "📄 Dokumentum generálása",
            "err_fix": "Kérjük, javítsd az alábbi hibá(ka)t:",
            "succ_upsert": "{msg}. {n} dokumentum elkészült.",
            "succ_new": "Új rekord LÉTREHOZVA (ID: {id}) – {nev}",
            "succ_update": "Rekord FRISSÍTVE (ID: {id}) – {nev}",
            "btn_download_doc": "⬇️ Letöltés: {fname}",
            "btn_download_zip": "📦 Összes dokumentum ZIP-ben",
            "table_header": "Felvitt rekordok (utolsó 20 – upsert után)",
            "table_col_id": "ID",
            "table_col_nev": "név",
            "table_col_dob": "szül. dátum",
            "table_col_pass": "útlevél",
            "table_col_perm": "engedély",
            "info_no_records": "Még nincs felvitt rekord.",
            "sidebar_lang": "Nyelv / Язык",
            "chat_header": "💬 Súgó / Chat",
            "chat_placeholder": "Írja ide a kérdését…",
            "chat_lang": "Chat nyelve",
            "chat_note": "A válasz a kiválasztott nyelven és magyar fordításban jelenik meg.",
            "select_templates": "Válassz sablon(oka)t a generáláshoz",
            "err_no_templates": "Nincs sablon a templates/ mappában.",
            "err_no_selection": "Nem választottál sablont. Jelölj ki legalább egyet.",
            "err_required_name": "A név megadása kötelező.",
            "err_invalid_date": "Érvénytelen dátum: {field}",
            "err_past_date": "A(z) {field} nem lehet múltbeli.",
            "ru_latin_notice": "⚠️ Пожалуйста, заполняйте латиницей (A–Z, 0–9) в соответствии с документами. Поля с кириллицей будут автоматически транслитерированы при отправке.",
            "ru_latin_applied": "Az űrlap adatain automatikus latin átírást végeztünk (cirill → latin).",
            "ru_job_translated": "A „Magyarországra jövetel előtti foglalkozás” mezőt oroszról magyarra fordítottuk.",
            "ru_job_translit_fallback": "A „Magyarországra jövetel előtti foglalkozás” mezőnél fordítás helyett latin átírást alkalmaztunk.",
            "ru_skill_translated": "A „Szakképzettség” mezőt oroszról magyarra fordítottuk.",
            "ru_skill_translit_fallback": "A „Szakképzettség” mezőnél fordítás helyett latin átírást alkalmaztunk."
        }
    return json.loads(p.read_text(encoding="utf-8"))

# =========================
# Konstansok és beállítások
# =========================
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"
DEFAULT_TEMPLATE_NAMES = [
    "nyilatkozat_adatokrol_sablon.docx",
    "Mv meghatalmazása cégnek_sablon.docx",
    "Cég meghatalmazása_authorization to NM_OIF_sablon.docx",
    "Cég meghatalmazása authorization to NM_BFKH TAJ_sablon.docx",
    "Befogadó nyilatkozat_sablon.docx",
]

# Kanonikus (HU) értékek
FAMILY_CANON = ["házas", "nőtlen/hajadon", "elvált", "özvegy"]
EDU_CANON = ["középfokú", "felsőfokú"]
YESNO_CANON = ["igen", "nem"]

def get_localized_options(lang: str):
    if lang == "ru":
        family_disp = ["женат/замужем", "неженат/незамужем", "в разводе", "вдова/вдовец"]
        edu_disp = ["среднее", "высшее"]
        yesno_disp = ["да", "нет"]
    else:
        family_disp = FAMILY_CANON
        edu_disp = EDU_CANON
        yesno_disp = YESNO_CANON
    return family_disp, edu_disp, yesno_disp

def to_canonical(lang: str, field: str, value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    if field == "yesno":
        mapping = {
            "hu": {"igen":"igen","nem":"nem"},
            "ru": {"да":"igen","нет":"nem"}
        }
    elif field == "family":
        mapping = {
            "hu": {"házas":"házas","nőtlen/hajadon":"nőtlen/hajadon","elvált":"elvált","özvegy":"özvegy"},
            "ru": {"женат/замужем":"házas","неженат/незамужем":"nőtlen/hajadon","в разводе":"elvált","вдова/вдовец":"özvegy"}
        }
    elif field == "edu":
        mapping = {
            "hu": {"középfokú":"középfokú","felsőfokú":"felsőfokú"},
            "ru": {"среднее":"középfokú","высшее":"felsőfokú"}
        }
    else:
        return v
    return mapping.get(lang, {}).get(v, v)

# =========================
# Transzliteráció (cirill → latin)
# =========================
CYR_TO_LAT = {
 'А':'A','Б':'B','В':'V','Г':'G','Д':'D','Е':'E','Ё':'E','Ж':'Zh','З':'Z','И':'I','Й':'I','К':'K','Л':'L','М':'M',
 'Н':'N','О':'O','П':'P','Р':'R','С':'S','Т':'T','У':'U','Ф':'F','Х':'Kh','Ц':'Ts','Ч':'Ch','Ш':'Sh','Щ':'Shch',
 'Ъ':'','Ы':'Y','Ь':'','Э':'E','Ю':'Yu','Я':'Ya', 'Є':'Ye','Ї':'Yi','І':'I','Ґ':'G',
 'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z','и':'i','й':'i','к':'k','л':'l','м':'m',
 'н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'shch',
 'ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya','є':'ye','ї':'yi','і':'i','ґ':'g'
}
def transliterate_to_latin(text: str) -> str:
    if not text:
        return text
    out = []
    for ch in text:
        out.append(CYR_TO_LAT.get(ch, ch))
    return ''.join(out)

def contains_cyrillic(s: str) -> bool:
    return any('\u0400' <= ch <= '\u04FF' or '\u0500' <= ch <= '\u052F' for ch in (s or ""))

def transliterate_record_fields(record: dict, fields: list[str]) -> tuple[dict, bool]:
    out = dict(record)
    changed = False
    for k in fields:
        v = out.get(k, "")
        if contains_cyrillic(v):
            out[k] = transliterate_to_latin(v)
            changed = True
    return out, changed

# =========================
# Validáció
# =========================
RE_PASSPORT = re.compile(r"^[A-Z0-9]{5,15}$", re.I)

def iso_date(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    dt = parse_date(s, dayfirst=True)
    return dt.date().isoformat()

def validate_record(r: dict, L: dict, ui_lang: str) -> list[str]:
    errors = []
    if not (r.get("nev") or "").strip():
        errors.append(L.get("err_required_name", "A név megadása kötelező."))
    if r.get("utlevel_szam") and not RE_PASSPORT.match(r["utlevel_szam"]):
        base_err = L.get(
            "err_bad_passport",
            "Útlevélszám formátum hibás." if ui_lang == "hu" else "Неверный формат номера паспорта."
        )
        if ui_lang == "ru":
            hint = "Ожидается: 5–15 символов, только латиница и цифры (A–Z, 0–9), без пробелов и знаков. Пример: AB1234567."
        else:
            hint = "Elvárt: 5–15 karakter, csak angol nagybetű és szám (A–Z, 0–9), szóköz és jel nélkül. Példa: AB1234567."
        errors.append(f"{base_err} {hint}")

    for key in ("szuletesi_datum","utlevel_lejarat","tartozkodasi_engedely_lejarat","jelenlegi_engedely_ervenyessege"):
        if r.get(key):
            try:
                r[key] = iso_date(r[key])
            except Exception:
                errors.append(L.get("err_invalid_date", "Érvénytelen dátum: {field}").format(field=key))

    today = date.today().isoformat()
    for key in ("utlevel_lejarat","tartozkodasi_engedely_lejarat","jelenlegi_engedely_ervenyessege"):
        if r.get(key) and r[key] <= today:
            errors.append(L.get("err_past_date", "A(z) {field} nem lehet múltbeli.").format(field=key))
    return errors

# =========================
# DOCX sablonkezelés és ZIP
# =========================
def list_docx_templates(templates_dir: Path):
    if not templates_dir.exists():
        return []
    return sorted([p for p in templates_dir.glob("*.docx") if p.is_file()])

def render_docx_from_template(template_path: Path, context: dict) -> bytes:
    if not template_path.exists():
        raise FileNotFoundError(f"Hiányzik a Word sablon: {template_path}")
    doc = DocxTemplate(str(template_path))
    doc.render(context)
    bio = io.BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio.read()

def sanitize_for_filename(text: str) -> str:
    text = (text or "").strip()
    return text.replace(" ", "_") if text else "dokumentum"

def ascii_sanitize_filename(name: str) -> str:
    name = (name or "").strip()
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return (name or "dokumentum").replace(" ", "_")

# =========================
# Titkok / környezeti változók
# =========================
def _get_secret(name: str, default: str | None = None) -> str | None:
    if name in st.secrets:
        return str(st.secrets[name])
    return os.environ.get(name, default)

# =========================
# Azure Translator — RU -> HU fordítás (HELYES custom path)
# =========================
def translator_translate_to_hungarian(text: str) -> str | None:
    """
    Azure Translator (Text Translation v3) – custom (regionális) endpointtal:
    {endpoint}/translator/text/v3.0/translate?api-version=3.0&to=hu
    Fejlécek: Ocp-Apim-Subscription-Key, Ocp-Apim-Subscription-Region, Content-Type: application/json
    """
    key = _get_secret("AZURE_TRANSLATOR_KEY")
    region = _get_secret("AZURE_TRANSLATOR_REGION")
    endpoint = _get_secret("AZURE_TRANSLATOR_ENDPOINT")

    if not (key and region and endpoint and text):
        return None

    url = endpoint.rstrip("/") + "/translator/text/v3.0/translate?api-version=3.0&to=hu"
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Ocp-Apim-Subscription-Region": region,  # pl. westeurope
        "Content-Type": "application/json"
    }
    body = [{"Text": text}]

    try:
        r = requests.post(url, headers=headers, json=body, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data[0]["translations"][0]["text"]
    except Exception as e:
        # Diagnosztika: ha gond van, lásd az állapotkódot/üzenetet (eltávolítható, ha stabil)
        st.warning(f"Translator hívás sikertelen: {e}")
        try:
            st.caption(f"Válasz: {r.status_code} – {r.text[:500]}")
        except Exception:
            pass
        return None

# =========================
# OpenAI Chat (EU Project) — Chat Completions
# =========================
def openai_available() -> bool:
    return bool(_get_secret("OPENAI_API_KEY"))

def openai_chat(system_prompt: str, user_msg: str, model: str | None = None) -> str:
    """
    OpenAI Chat Completions hívás. Ha van OPENAI_PROJECT, a kérést ahhoz a projekthez kötjük
    (EU Project esetén az adatok EU-ban kerülnek feldolgozásra – a Project routingot fejlécben adjuk meg).
    """
    api_key = _get_secret("OPENAI_API_KEY")
    project = _get_secret("OPENAI_PROJECT")  # opcionális
    model = model or _get_secret("OPENAI_CHAT_MODEL", "gpt-4o-mini")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if project:
        headers["OpenAI-Project"] = project

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg}
        ],
        "temperature": 0.2,
        "top_p": 0.9
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]

# =========================
# UI – Nyelvválasztó és feliratok
# =========================
# A kiválasztott nyelvet session_state-ben tároljuk
if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "hu"  # induláskor magyar

ui_lang = st.session_state["ui_lang"]
L = load_labels(ui_lang)

st.title(L["app_title"])
st.caption(L["app_caption"])


# Oldalsáv: sablonok
st.sidebar.header(L["sidebar_hdr_templates"])
available_templates = list_docx_templates(TEMPLATES_DIR)
if not available_templates:
    st.sidebar.warning(L["err_no_templates"])
else:
    for p in available_templates:
        st.sidebar.write(f"• {p.name}")
st.sidebar.caption(L["sidebar_dbg"].format(path=TEMPLATES_DIR, exists=TEMPLATES_DIR.exists()))

# Használati útmutató
with st.expander(L["help_header"], expanded=False):
    st.markdown(L["help_md"])

# RU UI esetén figyelmeztetés a latin kitöltésre
if ui_lang == "ru":
    st.warning(L.get("ru_latin_notice", "Пожалуйста, заполняйте латиницей (A–Z, 0–9)."))

# =========================
# I18n opciók (legördülők) és kanonikusítás
# =========================
family_disp, edu_disp, yesno_disp = get_localized_options(ui_lang)

# =========================
# Űrlap
# =========================
st.subheader(L["form_header"])

# --- Nyelvválasztó az űrlap címe alatt ---
new_lang = st.selectbox(
    "Nyelv / Язык",
    ["hu", "ru"],
    index=["hu", "ru"].index(ui_lang),
    format_func=lambda x: {"hu": "Magyar", "ru": "Русский"}.get(x, x),
    key="ui_lang_selector"
)
if new_lang != ui_lang:
    st.session_state["ui_lang"] = new_lang
    st.rerun()  # azonnal újrarenderelünk, hogy minden felirat váltson

with st.form("adaturlap", clear_on_submit=False):
    nev = st.text_input(L["field_nev"], placeholder="pl. Veréb Gábor" if ui_lang == "hu" else "")
    szuletesi_nev = st.text_input(L.get("field_szuletesi_nev", "Születési név"))
    szuletesi_datum = st.text_input(L.get("field_szuletesi_datum", "Születési dátum"),
        placeholder=L.get("ph_szuletesi_datum", "YYYY-MM-DD"))
    szuletesi_hely = st.text_input(L.get("field_szuletesi_hely", "Születési hely"),
        placeholder=L.get("ph_szuletesi_hely", "város, ország"))
    anyja_leanykori_neve = st.text_input(L.get("field_anyja", "Anyja leánykori neve"))
    csaladi_allapot_disp = st.selectbox(L.get("field_csaladi_allapot", "Családi állapot"),
        options=[""] + family_disp, index=0)
    vegzettseg_disp = st.selectbox(L.get("field_vegzettseg", "Végzettség"),
        options=[""] + edu_disp, index=0)
    szakkepzettseg = st.text_input(L.get("field_szakkepzettseg", "Szakképzettség"),
        placeholder=L.get("ph_szakkepzettseg", "pl. villanyszerelő, könyvelő"))
    prev_addr = st.text_input(L.get("field_prev_addr", "Magyarországra jövetel előtti lakcím"))
    prev_job = st.text_input(L.get("field_prev_job", "Magyarországra jövetel előtti foglalkozás"))
    utlevel_szam = st.text_input(L.get("field_utlevel_szam", "Útlevél száma"))
    utlevel_lejarat = st.text_input(L.get("field_utlevel_lejarat", "Útlevél lejárata"),
        placeholder=L.get("ph_date", "YYYY-MM-DD"))
    teng_szam = st.text_input(L.get("field_teng_szam", "Tartózkodási engedély száma"))
    teng_lejarat = st.text_input(L.get("field_teng_lejarat", "Tartózkodási engedély lejárata"),
        placeholder=L.get("ph_date", "YYYY-MM-DD"))
    fertozo_betegseg_disp = st.selectbox(L.get("field_fertozo", "Van-e fertőző betegsége?"),
        options=[""] + yesno_disp, index=0)
    kiskoru_gyermek_magyarorszagon_disp = st.selectbox(L.get("field_kiskoru", "Kiskorú gyermeke Magyarországon van-e?"),
        options=[""] + yesno_disp, index=0)
    lakcim = st.text_input(L.get("field_lakcim", "Lakcím (magyar)"))

    # Sablonválasztás
    template_labels = [p.name for p in available_templates]
    defaults = [name for name in template_labels if name in DEFAULT_TEMPLATE_NAMES]
    selected_labels = st.multiselect(L["select_templates"], options=template_labels, default=defaults)

    submitted = st.form_submit_button(L["btn_generate"])

# =========================
# Beküldés feldolgozása (Translator fordítás + transzliteráció + upsert)
# =========================
if submitted:
    errors = []
    if not available_templates:
        errors.append(L["err_no_templates"])
    if not selected_labels:
        errors.append(L["err_no_selection"])

    # A display értékeket kanonikus magyarra képezzük
    csaladi_allapot = to_canonical(ui_lang, "family", csaladi_allapot_disp)
    vegzettseg = to_canonical(ui_lang, "edu", vegzettseg_disp)
    fertozo_betegseg = to_canonical(ui_lang, "yesno", fertozo_betegseg_disp)
    kiskoru_gyermek_magyarorszagon = to_canonical(ui_lang, "yesno", kiskoru_gyermek_magyarorszagon_disp)

    record = {
        "nev": (nev or "").strip(),
        "szuletesi_nev": (szuletesi_nev or "").strip(),
        "szuletesi_datum": (szuletesi_datum or "").strip(),
        "szuletesi_hely": (szuletesi_hely or "").strip(),
        "anyja_leanykori_neve": (anyja_leanykori_neve or "").strip(),
        "csaladi_allapot": csaladi_allapot,
        "vegzettseg": vegzettseg,
        "szakkepzettseg": (szakkepzettseg or "").strip(),
        "magyarorszagra_erkezese_elotti_lakcim": (prev_addr or "").strip(),
        "magyarorszagra_erkezese_elotti_foglalkozas": (prev_job or "").strip(),
        "utlevel_szam": (utlevel_szam or "").strip(),
        "utlevel_lejarat": (utlevel_lejarat or "").strip(),
        "tartozkodasi_engedely_szam": (teng_szam or "").strip(),
        "tartozkodasi_engedely_lejarat": (teng_lejarat or "").strip(),
        "fertozo_betegseg": fertozo_betegseg,
        "kiskoru_gyermek_magyarorszagon": kiskoru_gyermek_magyarorszagon,
        "lakcim": (lakcim or "").strip()
    }

    # 1) RU UI esetén: két kulcsmező fordítása Azure Translatorral (RU -> HU)
    if ui_lang == "ru":
        # a) Foglalkozás
        job_val = record.get("magyarorszagra_erkezese_elotti_foglalkozas", "")
        if contains_cyrillic(job_val):
            hu_job = translator_translate_to_hungarian(job_val)
            if hu_job:
                record["magyarorszagra_erkezese_elotti_foglalkozas"] = hu_job
                st.info(L.get("ru_job_translated", "A foglalkozás mező magyarra fordítva."))
            else:
                record["magyarorszagra_erkezese_elotti_foglalkozas"] = transliterate_to_latin(job_val)
                st.info(L.get("ru_job_translit_fallback", "Foglalkozás: latin átírás (fordítás nem elérhető)."))

        # b) Szakképzettség
        skill_val = record.get("szakkepzettseg", "")
        if contains_cyrillic(skill_val):
            hu_skill = translator_translate_to_hungarian(skill_val)
            if hu_skill:
                record["szakkepzettseg"] = hu_skill
                st.info(L.get("ru_skill_translated", "A „Szakképzettség” mező magyarra fordítva."))
            else:
                record["szakkepzettseg"] = transliterate_to_latin(skill_val)
                st.info(L.get("ru_skill_translit_fallback", "Szakképzettség: latin átírás (fordítás nem elérhető)."))

    # 2) RU: a többi szabad szöveg transliterációja (kivéve a fenti 2 mezőt)
    if ui_lang == "ru":
        to_trans = [
            "nev","szuletesi_nev","szuletesi_hely",
            "magyarorszagra_erkezese_elotti_lakcim","lakcim"
        ]
        record, changed = transliterate_record_fields(record, to_trans)
        if changed:
            st.info(L.get("ru_latin_applied", "Automatikus latin átírás történt."))

    # Szerveroldali validáció
    errors.extend(validate_record(record, L, ui_lang))

    if errors:
        st.error(L["err_fix"] + "\n- " + "\n- ".join(errors))
    else:
        try:
            # UPSERT (név + szül. dátum)
            key_name = record.get("nev", "").strip().lower()
            key_dob = record.get("szuletesi_datum", "").strip()
            existing = None
            for r in list_records():
                if (r.get("nev","").strip().lower() == key_name and
                   (r.get("szuletesi_datum","").strip() == key_dob)):
                    existing = r
                    break

            if existing:
                saved = update_record(existing["id"], record)
                upsert_msg = L["succ_update"].format(id=saved.get("id"), nev=record.get("nev"))
            else:
                saved = create_record(record)
                upsert_msg = L["succ_new"].format(id=saved.get("id"), nev=record.get("nev"))

            st.success(f"Mentve. Rekord ID: {saved.get('id')}")

            # Dokumentumok
            generated_docs = []
            who = sanitize_for_filename(record.get("nev", "dokumentum"))
            when = datetime.now().strftime("%Y%m%d_%H%M")
            for label in selected_labels:
                tpath = next((p for p in available_templates if p.name == label), None)
                if not tpath:
                    st.error(f"A kiválasztott sablon nem található: {label}")
                    continue
                doc_bytes = render_docx_from_template(tpath, record)
                out_name = f"{tpath.stem}_{who}_{when}.docx"
                generated_docs.append((out_name, doc_bytes))

            if not generated_docs:
                st.error("Nem sikerült dokumentumot generálni.")
            else:
                st.success(L["succ_upsert"].format(msg=upsert_msg, n=len(generated_docs)))
                for fname, data in generated_docs:
                    st.download_button(
                        label=L["btn_download_doc"].format(fname=fname),
                        data=data,
                        file_name=fname,
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"dl_{fname}"
                    )

                # ZIP
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for fname, data in generated_docs:
                        inner_name = ascii_sanitize_filename(Path(fname).name)
                        zf.writestr(inner_name, data)
                zip_bytes = zip_buffer.getvalue()
                zip_name = ascii_sanitize_filename(f"osszes_dokumentum_{who}_{when}.zip")
                st.download_button(
                    label=L["btn_download_zip"],
                    data=zip_bytes,
                    file_name=zip_name,
                    mime="application/zip",
                    key="dl_zip_all"
                )

        except Exception as e:
            st.error(f"Váratlan hiba történt: {e}")

# =========================
# Chat – automatikus tájékoztató válasz HU/RU, e-mail küldés nélkül
# =========================
st.divider()
st.subheader(L["chat_header"])
chat_lang = st.selectbox(
    L["chat_lang"],
    ["hu", "ru"],
    index=0,
    format_func=lambda x: {"hu": "Magyar", "ru": "Русский"}.get(x, x)
)
st.caption(L["chat_note"])

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []

# Meglévő üzenetek megjelenítése
for m in st.session_state["chat_history"]:
    st.chat_message(m["role"]).markdown(m["content"])

user_msg = st.chat_input(L["chat_placeholder"])
if user_msg:
    # 1) Felhasználó üzenetének megjelenítése és naplózása
    st.chat_message("user").markdown(user_msg)
    st.session_state["chat_history"].append({"role": "user", "content": user_msg})

    # 2) Automatikus standard válasz a kiválasztott nyelven
    if chat_lang == "ru":
        auto_reply = (
            "**Спасибо за ваш вопрос!**\n\n"
            "Пожалуйста, свяжитесь с **Марией Надь** по следующим контактам:\n"
            "📧 maria.nagy@hungaria-xxx.com\n"
            "📞 тел.: +36 30 2323232"
        )
    else:
        auto_reply = (
            "**Köszönjük kérdését!**\n\n"
            "Kérjük, keresse **Nagy Máriát** az alábbi elérhetőségeken:\n"
            "📧 maria.nagy@hungaria-xxx.com\n"
            "📞 tel.: +36 30 2323232"
        )


    st.chat_message("assistant").markdown(auto_reply)
    st.session_state["chat_history"].append({"role": "assistant", "content": auto_reply})

# =========================
# Alsó szekció – rekordlista
# =========================
st.divider()
st.subheader(L["table_header"])
try:
    recs = list_records()
    if recs:
        L_title_id = L.get("table_col_id","ID")
        L_title_nev = L.get("table_col_nev","név")
        L_title_dob = L.get("table_col_dob","szül. dátum")
        L_title_pass = L.get("table_col_pass","útlevél")
        L_title_perm = L.get("table_col_perm","engedély")
        miniview = [
            {
                L_title_id: r.get("id", ""),
                L_title_nev: r.get("nev", ""),
                L_title_dob: r.get("szuletesi_datum", ""),
                L_title_pass: r.get("utlevel_szam", ""),
                L_title_perm: r.get("jelenlegi_engedely_szama", "")
            }
            for r in recs[-20:]
        ]
        st.dataframe(miniview, use_container_width=True)
    else:
        st.info(L["info_no_records"])
except Exception as e:
    st.error(f"Nem sikerült betölteni a rekordokat: {e}")


