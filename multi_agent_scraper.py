import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
import re
from urllib.parse import urljoin, quote as url_quote
import urllib.request
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False

# ==============================================================================
# GLOBAL CONFIGURATION & REPOSITORY BINDING (Project-4.O-pie-pie)
# ==============================================================================
PROJECT_REPO_NAME = os.environ.get("PROJECT_REPO_NAME", "Project-4.O-pie-pie")
DATABASE_FILE = "jobs_database.json"
ADMIN_BOXES_FILE = "admin_boxes.json"

MAX_DB_SIZE_MB = 12.0
MAX_ACTIVE_POSTS = 180
DEFAULT_PRUNE_DAYS = int(os.environ.get("PRUNE_DAYS_COUNT", "2") or "2")
FORCE_PURGE_FLAG = os.environ.get("FORCE_PURGE_OLDEST_2_DAYS", "false").lower() == "true"

# ==============================================================================
# LAYER 1: TARGET SCRAPING WEBSITES (STRICTLY THE 2 WEBSITES & THEIR MIRRORS)
# ==============================================================================
SOURCES = [
    {"name": "SarkariResultMirror", "url": "https://sarkariresult.com.cm/"},
    {"name": "SarkariResultMain", "url": "https://www.sarkariresult.com/"},
    {"name": "FreeJobAlertMain", "url": "https://www.freejobalert.com/government-jobs/"},
    {"name": "FreeJobAlertMirror", "url": "https://www.freejobalert.com/"},
]

ALLOWED_SOURCE_NAMES = {s["name"] for s in SOURCES} | {"Admin Panel"}

SIX_CATEGORIES_ORDER = [
    "latest_jobs",
    "results",
    "admit_cards",
    "answer_keys",
    "syllabus",
    "admissions",
]

CATEGORY_LABELS = {
    "latest_jobs": "Latest Jobs",
    "results": "Result",
    "admit_cards": "Admit Card",
    "answer_keys": "Answer Key",
    "syllabus": "Syllabus",
    "admissions": "Admission",
}

NON_GOVT_KEYWORDS = [
    "ongc", "iocl", "ntpc", "sail", "bhel", "gail", "powergrid", "hpcl",
    "coal india", "hal", "bel", "mdl", "gsl", "goa shipyard", "mazagon",
    "cochin shipyard", "nmdc", "bsnl", "dmrc", "mahametro", "private",
    "apprentice", "semi-govt", "psu", "dccb", "pacs", "markfed",
    "cooperative", "csc", "idbi", "lic", "niacl", "uiic", "ibps", "sbi", "rbi", "nabard",
]

STATE_KEYWORDS = {
    "Maharashtra": ["mpsc", "mumbai", "pune", "nagpur", "maharashtra", "talathi", "gramsevak", "srpf", "mahadiscom", "msedcl", "mahametro", "bmc", "pmc", "arogya sevak", "krishi sevak", "vanrakshak", "mahabhumi", "kotwal", "thane", "bhiwandi"],
    "Uttar Pradesh": ["uppsc", "uppcs", "lucknow", "uttar pradesh", "lekhpal", "up police", "uppbpb", "upsssc", "allahabad", "prayagraj", "uptet", "uppsc ro", "up b.ed", "updeled", "jaunpur"],
    "Bihar": ["bpsc", "bihar", "patna", "csbc", "bssc", "btsc", "btet", "bihar police"],
    "Madhya Pradesh": ["mppsc", "madhya pradesh", "bhopal", "mpesb", "mppeb", "mp police", "indore"],
    "Rajasthan": ["rpsc", "rajasthan", "jaipur", "patwari", "rsmssb", "rssb", "reet"],
    "Delhi": ["dsssb", "delhi police", "dmrc", "delhi metro", "delhi high court"],
    "Haryana": ["hssc", "hpsc", "haryana", "chandigarh", "cet haryana"],
    "Punjab": ["psssb", "ppsc", "punjab"],
    "Gujarat": ["gpsc", "ojas", "gujarat", "gsssb"],
    "Karnataka": ["kpsc", "karnataka", "kea", "bengaluru", "gpstr"],
    "Tamil Nadu": ["tnpsc", "tamil nadu", "chennai", "trb"],
    "West Bengal": ["wbpsc", "west bengal", "kolkata", "wbp"],
    "Jharkhand": ["jssc", "jpsc", "jharkhand", "ranchi"],
    "Chhattisgarh": ["cgpsc", "cgvyapam", "chhattisgarh", "raipur"],
    "Uttarakhand": ["ukpsc", "uksssc", "uttarakhand", "dehradun"],
    "Odisha": ["opsc", "osssc", "ossc", "odisha", "bhubaneswar"],
    "Assam": ["apsc", "assam", "guwahati", "slrc", "lra"],
    "Goa": ["goa shipyard", "gsl", "goa police", "gpsc goa"],
}

BLOCK_DOMAINS = [
    "play.google.com", "apps.apple.com", "whatsapp.com", "t.me", "telegram.me",
    "facebook.com", "twitter.com", "x.com", "youtube.com", "instagram.com",
    "pinterest.com", "linkedin.com", "sarkariresulttools.net", "addtoany.com",
    "google.com", "bing.com", "duckduckgo.com", "yahoo.com", "dmca.com",
    "slate.freejobalert.com", "ai.freejobalert.com", "user.freejobalert.com",
    "colleges.freejobalert.com",
]

AGGREGATOR_HTML_DOMAINS = [
    "sarkariresult.com",
    "sarkariresult.com.cm",
    "freejobalert.com",
    "rojgarresult.com",
    "sarkariexam.com",
    "indgovtjobs.in",
    "mysarkarinaukri.com",
    "jobriya.in",
    "aglasem.com",
]

# STRICT NOISE & MENU ITEM BLOCKER (Eliminates 'Free AI Interview Tool', 'Cutoff Marks', Q&A, etc.)
STRICT_NOISE_PHRASES = [
    "free ai interview tool", "download mobile app", "free mock test",
    "register for job alerts", "last date reminder", "previous papers",
    "image resizer", "pdf to word converter", "image to pdf converter",
    "word to pdf converter", "interview results", "written marks",
    "cutoff marks", "employment news", "anganwadi recruitment",
    "govt jobs without exams", "female govt jobs", "legal govt jobs",
    "sarkari result", "free job alert", "daily quiz", "login",
    "all india govt jobs", "state govt jobs", "teaching jobs",
    "engineering jobs", "police/defence jobs", "latest announcements",
    "others", "tools", "education", "notifications", "latest notifications",
    "search jobs", "psu jobs", "state psc jobs", "sarkari job", "sarkari naukri",
    "forest jobs", "what is the age limit", "what is the qualification",
    "how to apply for", "question:", "answer:", "faq", "frequently asked",
]

# METADATA LABELS BLOCKED FROM ENTERING VACANCY BREAKDOWN TABLES
METADATA_ROW_LABELS = {
    "department", "organisation", "organization", "post name", "total vacancies",
    "total vacancy", "qualification", "medical standard", "application last date",
    "online application start date", "last date to apply online",
    "last date for application fee payment", "official website", "selection stages",
    "selection process", "last date for payment of examination fee",
    "last date for correction/modification", "s. no.", "sl. no.", "sr. no.",
    "exam mode", "mode of exam", "job location", "advertisement no", "advt no",
    "category", "release date", "notification date", "apply start date",
}

MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

OFFICIAL_BOARD_PORTALS = [
    ("goa shipyard", "https://goashipyard.in"),
    ("gsl", "https://goashipyard.in"),
    ("ssc", "https://ssc.gov.in"),
    ("rrb", "https://indianrailways.gov.in"),
    ("railway", "https://indianrailways.gov.in"),
    ("ntpc", "https://indianrailways.gov.in"),
    ("ibps", "https://www.ibps.in"),
    ("sbi", "https://sbi.co.in/web/careers"),
    ("rbi", "https://opportunities.rbi.org.in"),
    ("upsc", "https://upsc.gov.in"),
    ("bpsc", "https://bpsc.bih.nic.in"),
    ("uppsc", "https://uppsc.up.nic.in"),
    ("upsssc", "https://upsssc.gov.in"),
    ("mpsc", "https://mpsc.gov.in"),
    ("police", "https://uppbpb.gov.in"),
    ("ctet", "https://ctet.nic.in"),
    ("neet", "https://neet.nta.nic.in"),
    ("jee", "https://jeemain.nta.nic.in"),
    ("cuet", "https://exams.nta.ac.in"),
    ("ignou", "https://ignouadmission.samarth.edu.in"),
    ("post", "https://indiapostgdsonline.gov.in"),
    ("aiims", "https://aiimsexams.ac.in"),
]


# ==============================================================================
# HELPER FUNCTIONS: CLEANING, NOISE FILTERING & BOARD URL RESOLUTION
# ==============================================================================
def scrub_external_branding(text):
    if not text:
        return ""
    cleaned = re.sub(
        r"(?:sarkari\s*result|free\s*job\s*alert|rojgar\s*result|sarkari\s*exam|indgovtjobs|mysarkarinaukri|jobriya|aglasem)(?:\.com|\.cm|\.in)?",
        "",
        str(text),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(?:scraper|scraped|scraping|agentic\s*ai|bot|rss\s*feed)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Strip any Q&A pattern sentences
    cleaned = re.sub(
        r"(?:Q\s*[:\.]?\s*)?What\s+is\s+the\s+[^?]+\?\s*(?:Ans(?:wer)?\s*[:\.]?\s*)?[^.]+(?:\.|$)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", cleaned).strip(" -–|:")


def is_noise_or_menu_line(text, current_post_title=""):
    if not text:
        return True
    t_clean = text.strip()
    t_low = t_clean.lower()
    if len(t_clean) < 3 or len(t_clean) > 450:
        return True

    # Exact match or substring match against known menu/tool/Q&A noise
    for phrase in STRICT_NOISE_PHRASES:
        if t_low == phrase or phrase in t_low:
            return True

    # Block Question-Answer lines
    if "?" in t_clean and ("answer" in t_low or t_low.startswith("what is") or t_low.startswith("how many") or t_low.startswith("who can")):
        return True

    # Block unrelated job advertisements injected from sidebars (e.g., "GPSTR Teacher Recruitment 2026 Last Date Extended")
    if any(k in t_low for k in ["recruitment 2026", "online form 2026", "last date extended", "apply online"]) and current_post_title:
        title_words = [w for w in re.findall(r"[a-z]{4,}", current_post_title.lower()) if w not in {"recruitment", "online", "form", "posts", "vacancy", "vacancies", "bharti"}]
        if title_words and not any(tw in t_low for tw in title_words[:3]):
            return True

    return False


def is_direct_post_target_url(url, allow_direct_pdf_on_cdn=False):
    if not url or not url.startswith("http") or url.endswith("#"):
        return False
    u_low = url.lower().strip()
    if any(b in u_low for b in BLOCK_DOMAINS):
        return False
    if any(ag in u_low for ag in AGGREGATOR_HTML_DOMAINS):
        if allow_direct_pdf_on_cdn and u_low.split("?")[0].endswith(".pdf"):
            return True
        return False
    return True


def resolve_official_board_url(title_str, fallback_url=""):
    t_low = str(title_str or "").lower()
    for kw, official_url in OFFICIAL_BOARD_PORTALS:
        if kw in t_low:
            return official_url
    if fallback_url and is_direct_post_target_url(fallback_url, allow_direct_pdf_on_cdn=True):
        return fallback_url
    return "https://ssc.gov.in"


# ==============================================================================
# NON-BLOCKING NETWORK ENGINE (CURL_CFFI CHROME-110 + URLLIB FALLBACK)
# ==============================================================================
def blocking_fetch(url, timeout=12):
    if HAS_CFFI:
        try:
            res = cffi_requests.get(
                url, impersonate="chrome110", timeout=timeout, allow_redirects=True
            )
            if res.status_code == 200 and len(res.text) > 150:
                return res.text
        except Exception:
            pass
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


async def safe_fetch_non_blocking(url, loop, semaphore, timeout=16.0):
    if not url or not url.startswith("http"):
        return ""
    async with semaphore:
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, blocking_fetch, url, int(timeout - 2)),
                timeout=timeout,
            )
        except Exception:
            return ""


# ==============================================================================
# LAYER 2: INTENT, JOB FIELD, 6-CATEGORY, SECTOR & STATE CLASSIFIER
# ==============================================================================
class IntentAndMetaClassifierAgent:

    @staticmethod
    def analyze(title, box_heading="", body_snippet=""):
        t = f"{title} {box_heading}".lower()
        full_check = f"{t} {body_snippet[:500].lower()}"

        is_date_extended = any(
            k in t for k in ["date extended", "extended", "last date extended", "re-open", "reopen"]
        )

        if any(k in t for k in ["answer key", "response sheet", "question paper", "objection"]):
            cat_key = "answer_keys"
            intent = "INTENT_ANSWER_KEY"
        elif any(k in t for k in ["result", "merit list", "cutoff", "cut off", "score card", "scorecard", "final selection", "marks", "shortlisted"]):
            cat_key = "results"
            intent = "INTENT_RESULT"
        elif any(k in t for k in ["admit card", "hall ticket", "call letter", "exam city", "exam date", "interview letter", "city intimation"]):
            cat_key = "admit_cards"
            intent = "INTENT_ADMIT_CARD"
        elif any(k in t for k in ["syllabus", "exam pattern", "curriculum"]):
            cat_key = "syllabus"
            intent = "INTENT_SYLLABUS"
        elif any(k in t for k in ["admission", "counselling", "counseling", "cuet", "neet", "jee ", "b.ed", "d.el.ed", "iti ", "polytechnic", "entrance"]):
            cat_key = "admissions"
            intent = "INTENT_ADMISSION"
        else:
            cat_key = "latest_jobs"
            intent = "INTENT_DATE_EXTENDED" if is_date_extended else "INTENT_APPLY"

        # Detect Exam Field / Domain for Quote & Syllabus Synthesis
        if any(k in full_check for k in ["ibps", "sbi", "rbi", "nabard", "bank", "lic", "niacl", "uiic", "idbi", "gramin bank"]):
            exam_field = "Banking"
        elif any(k in full_check for k in ["ssc", "cgl", "chsl", "mts", "selection post", "stenographer", "cpo"]):
            exam_field = "SSC"
        elif any(k in full_check for k in ["rrb", "railway", "ntpc", "group d", "alp", "rpf", "technician", "metro", "dmrc"]):
            exam_field = "Railway"
        elif any(k in full_check for k in ["police", "constable", "sub inspector", "si ", "army", "agniveer", "navy", "air force", "nda", "cds", "capf", "bsf", "crpf", "cisf", "itbp", "ssb", "defence", "home guard"]):
            exam_field = "Police_Defence"
        elif any(k in full_check for k in ["tet", "ctet", "teacher", "tgt", "pgt", "prt", "faculty", "professor", "lecturer", "b.ed", "shikshak"]):
            exam_field = "Teaching"
        elif any(k in full_check for k in ["shipyard", "gsl", "iti", "diploma", "engineer", "gate", "bhel", "ntpc ltd", "ongc", "iocl", "drdo", "isro", "barc", "technical", "non-executive", "tradesman"]):
            exam_field = "Technical_PSU"
        else:
            exam_field = "State_PSC_Civil"

        job_type = "Non-Govt + Semi-Govt" if any(k in full_check for k in NON_GOVT_KEYWORDS) else "Govt"
        sector_code = "non_semi_govt" if job_type != "Govt" else "govt_only"

        state = "All India / Central"
        state_code = "all"
        for s_name, kws in STATE_KEYWORDS.items():
            if any(kw in full_check for kw in kws):
                state = s_name
                state_code = s_name.lower().replace(" ", "_")
                if state_code == "uttar_pradesh":
                    state_code = "up"
                elif state_code == "madhya_pradesh":
                    state_code = "mp"
                elif state_code == "west_bengal":
                    state_code = "wb"
                break

        return {
            "category_key": cat_key,
            "category_label": CATEGORY_LABELS[cat_key],
            "admin_box": CATEGORY_LABELS[cat_key],
            "primary_intent": intent,
            "exam_field": exam_field,
            "is_extended": is_date_extended,
            "job_type": job_type,
            "sector": sector_code,
            "state": state,
            "state_code": state_code,
        }


# ==============================================================================
# LAYER 3: DATE PARSER & MAIN CONTENT ISOLATOR
# ==============================================================================
def parse_any_date_string(text):
    if not text:
        return None
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", str(text), flags=re.IGNORECASE)

    m1 = re.search(
        r"\b(\d{1,2})[\s\/\-\.](Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[\s\/\-\.,]+(202[4-9])\b",
        cleaned,
        re.IGNORECASE,
    )
    if m1:
        day, mon_str, yr = int(m1.group(1)), m1.group(2).lower()[:3], int(m1.group(3))
        mon = MONTH_MAP.get(mon_str, 1)
        try:
            return datetime(yr, mon, day)
        except ValueError:
            pass

    m2 = re.search(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})[\s,]+(202[4-9])\b",
        cleaned,
        re.IGNORECASE,
    )
    if m2:
        mon_str, day, yr = m2.group(1).lower()[:3], int(m2.group(2)), int(m2.group(3))
        mon = MONTH_MAP.get(mon_str, 1)
        try:
            return datetime(yr, mon, day)
        except ValueError:
            pass

    m3 = re.search(r"\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](202[4-9])\b", cleaned)
    if m3:
        d, m, y = int(m3.group(1)), int(m3.group(2)), int(m3.group(3))
        if 1 <= m <= 12 and 1 <= d <= 31:
            try:
                return datetime(y, m, d)
            except ValueError:
                pass

    m4 = re.search(r"\b(202[4-9])-(\d{2})-(\d{2})\b", cleaned)
    if m4:
        try:
            return datetime(int(m4.group(1)), int(m4.group(2)), int(m4.group(3)))
        except ValueError:
            pass

    return None


def isolate_article_main_node(soup):
    """
    Removes global navigation menus, footers, sidebars, and tool links so menu items
    like 'Free AI Interview Tool' or 'Cutoff Marks' never contaminate post boxes.
    """
    for junk_tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "iframe"]):
        junk_tag.decompose()

    for junk_div in soup.find_all(
        ["div", "ul", "section"],
        attrs={
            "class": re.compile(
                r"(sidebar|widget|menu|navbar|footer|header|related|share|social|comment|breadcrumb|advertisement)",
                re.I,
            )
        },
    ):
        junk_div.decompose()

    main_node = (
        soup.find("main")
        or soup.find("article")
        or soup.find("div", attrs={"class": re.compile(r"(entry-content|post-content|article-content|td-post-content|main-content)", re.I)})
        or soup.find("div", attrs={"id": re.compile(r"(post|content|main)", re.I)})
    )
    return main_node if main_node else soup


# ==============================================================================
# LAYER 4: DEEP DOSSIER, REAL VACANCY TABLE & SEPARATE SYLLABUS PARSER
# ==============================================================================
def deep_parse_article_dossier(article_html, article_url, title, exam_field="SSC"):
    dossier = {
        "short_info": "",
        "department": "",
        "dates": {
            "release_date": "",
            "notification_date": "",
            "apply_start_date": "",
            "last_date": "",
            "extended_date": "",
            "fee_last_date": "",
            "exam_date": "",
            "admit_card_date": "",
            "answer_key_date": "",
            "result_date": "",
            "real_post_date_obj": None,
            "last_date_obj": None,
        },
        "fees": [],
        "age_criteria": [],
        "eligibility_list": [],
        "total_vacancy": "",
        "vacancy_number": 0,
        "post_qual_rows": [],         # Clean [Post Name, Qualification, Total Posts]
        "category_vacancy_rows": [],  # Clean [Post Name, UR, OBC, EWS, SC, ST, Total]
        "selection_process": [],
        "exam_pattern_rows": [],      # Clean [Section/Subject, Questions, Marks, Duration]
        "exam_pattern_notes": [],
        "syllabus_by_subject": {},    # { "Subject Name": ["Topic 1", "Topic 2", ...] }
        "links": {
            "apply_link": "",
            "notif_pdf": "",
            "admit_card_link": "",
            "answer_key_link": "",
            "result_link": "",
            "syllabus_link": "",
            "official_site": "",
        },
        "all_extracted_links": [],
    }

    if not article_html:
        return dossier

    full_soup = BeautifulSoup(article_html, "html.parser")
    post_dates_found = []

    # Check meta tags before stripping head
    for meta in full_soup.find_all("meta"):
        prop = (meta.get("property", "") or meta.get("name", "")).lower()
        if any(k in prop for k in ["published_time", "modified_time", "updated_time", "date", "pubdate"]):
            dt = parse_any_date_string(meta.get("content", ""))
            if dt:
                post_dates_found.append(dt)

    soup = isolate_article_main_node(full_soup)
    text_blob = soup.get_text(" ", strip=True)

    # Extract explicit post publish date
    explicit_date_matches = re.findall(
        r"(?:Post Date|Post Update Date|Updated On|Published On|Date of Post|Latest Update)\s*[:\-–]?\s*([0-9]{1,2}[\s\/\-\.][A-Za-z0-9]+[\s\/\-\.,]+202[4-9])",
        text_blob,
        re.IGNORECASE,
    )
    for m_str in explicit_date_matches:
        dt = parse_any_date_string(m_str)
        if dt:
            post_dates_found.append(dt)

    for time_tag in soup.find_all("time"):
        dt = parse_any_date_string(time_tag.get("datetime", "") or time_tag.get_text(" ", strip=True))
        if dt:
            post_dates_found.append(dt)

    # 1. Extract Short Overview
    for p in soup.find_all(["p", "div"]):
        ptxt = scrub_external_branding(re.sub(r"\s+", " ", p.get_text(" ", strip=True)).strip())
        if 60 <= len(ptxt) <= 580 and not is_noise_or_menu_line(ptxt, title):
            if any(k in ptxt.lower() for k in ["short information", "brief information", "has released", "invites online", "notification for", "recruitment", "vacancies", "application"]):
                clean_info = re.sub(r"^(?:short|brief)\s*information\s*[:\-–]?\s*", "", ptxt, flags=re.IGNORECASE).strip()
                dossier["short_info"] = clean_info
                break

    dept_split = re.split(
        r"\b(?:Recruitment|Online Form|Admit Card|Result|Answer Key|Syllabus|Admission|Vacancy|2026|2025)\b",
        title,
        flags=re.IGNORECASE,
    )[0].strip(" -–|:")
    dossier["department"] = dept_split if len(dept_split) >= 3 else title[:45]

    # 2. Parse Structured HTML Tables First (For Accurate Vacancy Distribution & Exam Pattern)
    for tbl in soup.find_all("table"):
        rows = tbl.find_all("tr")
        if not rows:
            continue

        header_cells = [
            scrub_external_branding(re.sub(r"\s+", " ", c.get_text(" ", strip=True)).strip())
            for c in rows[0].find_all(["th", "td"])
        ]
        header_join = " ".join(header_cells).lower()

        # Check if this is an Exam Pattern Table (Subject, Questions, Marks, Duration)
        if any(k in header_join for k in ["subject", "section", "paper"]) and any(k in header_join for k in ["question", "mark", "duration", "time"]):
            for r in rows[1:]:
                c_list = [
                    scrub_external_branding(re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip())
                    for td in r.find_all(["td", "th"])
                ]
                c_list = [c for c in c_list if c]
                if len(c_list) >= 2 and not any( c_list[0].lower() in METADATA_ROW_LABELS for _ in [1] ):
                    if c_list not in dossier["exam_pattern_rows"] and len(dossier["exam_pattern_rows"]) < 10:
                        dossier["exam_pattern_rows"].append(c_list[:4])
            continue

        # Check if this is a Category-Wise Vacancy Table (UR, OBC, EWS, SC, ST, Total)
        if len(header_cells) >= 4 and sum(1 for k in ["ur", "gen", "obc", "ews", "sc", "st", "total"] if k in header_join) >= 3:
            if not dossier["category_vacancy_rows"]:
                dossier["category_vacancy_rows"].append(header_cells[:7])
            for r in rows[1:]:
                c_list = [
                    scrub_external_branding(re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip())
                    for td in r.find_all(["td", "th"])
                ]
                c_list = [c for c in c_list if c != ""]
                if len(c_list) >= 4:
                    first_col_low = c_list[0].lower().strip(" :.-📌")
                    if first_col_low in METADATA_ROW_LABELS or "click here" in " ".join(c_list).lower():
                        continue
                    if c_list not in dossier["category_vacancy_rows"] and len(dossier["category_vacancy_rows"]) < 25:
                        dossier["category_vacancy_rows"].append(c_list[:7])
            continue

        # Check if this is a Post-Wise Vacancy / Qualification Table (Post Name | Vacancy | Qualification)
        for r in rows:
            c_list = [
                scrub_external_branding(re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip())
                for td in r.find_all(["td", "th"])
            ]
            c_list = [c for c in c_list if c != ""]
            if len(c_list) < 2:
                continue
            first_low = re.sub(r"^#\d+\s*", "", c_list[0].lower()).strip(" :.-📌")
            row_joined_low = " ".join(c_list).lower()

            if first_low in METADATA_ROW_LABELS or "click here" in row_joined_low:
                continue
            if first_low in {"post name", "trade name", "name of post", "post", "cadre", "discipline"}:
                continue

            # Check if inline category counts exist inside the cell (e.g., "UR-79, SC-36, ST-03, OBC-72, EWS-32")
            inline_ur = re.search(r"\b(?:UR|Gen(?:eral)?)\s*[:\-]?\s*(\d+)", c_list[1] if len(c_list) > 1 else c_list[0], re.I)
            inline_obc = re.search(r"\bOBC\s*[:\-]?\s*(\d+)", c_list[1] if len(c_list) > 1 else c_list[0], re.I)
            if inline_ur or inline_obc:
                blob_c = " ".join(c_list)
                p_name = re.split(r"\(|\|", blob_c)[0].strip()
                ur_v = (re.search(r"\b(?:UR|Gen)\s*[:\-]?\s*(\d+)", blob_c, re.I) or [None, "0"])[1]
                obc_v = (re.search(r"\bOBC\s*[:\-]?\s*(\d+)", blob_c, re.I) or [None, "0"])[1]
                ews_v = (re.search(r"\bEWS\s*[:\-]?\s*(\d+)", blob_c, re.I) or [None, "0"])[1]
                sc_v = (re.search(r"\bSC\s*[:\-]?\s*(\d+)", blob_c, re.I) or [None, "0"])[1]
                st_v = (re.search(r"\bST\s*[:\-]?\s*(\d+)", blob_c, re.I) or [None, "0"])[1]
                tot_m = re.search(r"\|\s*(\d+)\s*\|", blob_c)
                tot_v = tot_m.group(1) if tot_m else str(sum(int(x) for x in [ur_v, obc_v, ews_v, sc_v, st_v] if x.isdigit()))
                if not dossier["category_vacancy_rows"]:
                    dossier["category_vacancy_rows"].append(["Post Name / Cadre", "UR", "OBC", "EWS", "SC", "ST", "Total"])
                row_cat = [p_name[:55], ur_v, obc_v, ews_v, sc_v, st_v, tot_v]
                if row_cat not in dossier["category_vacancy_rows"]:
                    dossier["category_vacancy_rows"].append(row_cat)

            # Store valid Post/Trade row in post_qual_rows
            if len(c_list[0]) <= 85 and not any(k in first_low for k in ["important date", "application fee", "age limit", "how to apply", "selection process"]):
                if any(k in row_joined_low for k in ["degree", "diploma", "iti", "10th", "12th", "graduate", "post", "vacancy", "assistant", "officer", "clerk", "fitter", "welder", "electrician", "engineer", "executive", "teacher", "constable", "adhikari"]) or (len(c_list) >= 2 and c_list[1].replace(",", "").isdigit()):
                    if c_list[:3] not in dossier["post_qual_rows"] and len(dossier["post_qual_rows"]) < 25:
                        dossier["post_qual_rows"].append(c_list[:3])

    # 3. Scan Table Rows & List Items for Dates, Fees, Age, Selection Process & Links
    for node in soup.find_all(["tr", "li", "p"]):
        row_text = scrub_external_branding(re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip())
        if is_noise_or_menu_line(row_text, title):
            continue
        row_low = row_text.lower()

        # --- A. Dates ---
        dt_in_row = parse_any_date_string(row_text)
        if dt_in_row:
            dt_fmt = dt_in_row.strftime("%d %b %Y")
            if any(k in row_low for k in ["post date", "update date", "published on", "latest update"]):
                post_dates_found.insert(0, dt_in_row)
                if not dossier["dates"]["release_date"]:
                    dossier["dates"]["release_date"] = dt_fmt
            if any(k in row_low for k in ["notification", "advt", "advertisement", "issue date"]):
                if not dossier["dates"]["notification_date"]:
                    dossier["dates"]["notification_date"] = dt_fmt
                post_dates_found.append(dt_in_row)
            if any(k in row_low for k in ["application begin", "start date", "starting date", "apply start", "registration start", "online apply start"]):
                if not dossier["dates"]["apply_start_date"]:
                    dossier["dates"]["apply_start_date"] = dt_fmt
                post_dates_found.append(dt_in_row)
            if any(k in row_low for k in ["last date", "closing date", "apply online last", "end date", "registration last"]):
                if "extended" in row_low:
                    dossier["dates"]["extended_date"] = dt_fmt
                    dossier["dates"]["last_date"] = dt_fmt
                    dossier["dates"]["last_date_obj"] = dt_in_row
                elif "fee" in row_low or "payment" in row_low:
                    if not dossier["dates"]["fee_last_date"]:
                        dossier["dates"]["fee_last_date"] = dt_fmt
                else:
                    if not dossier["dates"]["last_date"]:
                        dossier["dates"]["last_date"] = dt_fmt
                        dossier["dates"]["last_date_obj"] = dt_in_row
            if "extended" in row_low and not dossier["dates"]["extended_date"]:
                dossier["dates"]["extended_date"] = dt_fmt
                dossier["dates"]["last_date"] = dt_fmt
                dossier["dates"]["last_date_obj"] = dt_in_row
            if any(k in row_low for k in ["exam date", "cbt date", "prelims exam", "mains exam", "written exam", "test date"]):
                if not dossier["dates"]["exam_date"]:
                    dossier["dates"]["exam_date"] = dt_fmt
            if any(k in row_low for k in ["admit card", "hall ticket", "call letter"]):
                if not dossier["dates"]["admit_card_date"]:
                    dossier["dates"]["admit_card_date"] = dt_fmt
            if any(k in row_low for k in ["answer key", "objection", "response sheet"]):
                if not dossier["dates"]["answer_key_date"]:
                    dossier["dates"]["answer_key_date"] = dt_fmt
            if any(k in row_low for k in ["result", "merit list", "score card", "scorecard"]):
                if not dossier["dates"]["result_date"]:
                    dossier["dates"]["result_date"] = dt_fmt

        # --- B. Application Fee ---
        if any(k in row_low for k in ["general", "obc", "ews", "sc / st", "sc/st", "application fee", "₹", "rs.", "rs /-", "nil", "exempted", "payment mode"]):
            if len(dossier["fees"]) < 6 and len(row_text) < 170 and "click here" not in row_low:
                if row_text not in dossier["fees"]:
                    dossier["fees"].append(row_text)

        # --- C. Age Limit ---
        if any(k in row_low for k in ["minimum age", "maximum age", "age limit", "age relaxation", "born between", "age as on"]):
            if len(dossier["age_criteria"]) < 6 and len(row_text) < 190 and "click here" not in row_low:
                if row_text not in dossier["age_criteria"]:
                    dossier["age_criteria"].append(row_text)

        # --- D. Eligibility ---
        if any(k in row_low for k in ["bachelor", "degree", "graduate", "10th", "12th", "matric", "intermediate", "diploma", "iti", "b.tech", "b.ed", "pg", "master", "mbbs", "qualification", "eligibility"]):
            if len(dossier["eligibility_list"]) < 8 and len(row_text) < 230 and "click here" not in row_low:
                if row_text not in dossier["eligibility_list"]:
                    dossier["eligibility_list"].append(row_text)

        # --- E. Total Vacancy Count ---
        tot_match = re.search(
            r"(?:Total\s+Vacanc(?:y|ies)|Total\s+Posts?|Vacancy\s+Details\s+Total|No\.\s*of\s*Posts?)\s*[:\-–]?\s*([0-9,]{1,8})\b",
            row_text,
            re.IGNORECASE,
        )
        if tot_match and not dossier["total_vacancy"]:
            raw_num = tot_match.group(1).replace(",", "").strip()
            if raw_num.isdigit() and int(raw_num) > 0:
                dossier["vacancy_number"] = int(raw_num)
                dossier["total_vacancy"] = f"{tot_match.group(1)} Posts"

        # --- F. Clean Selection Process (Strictly Stage-related, Zero Menu Noise) ---
        if any(k in row_low for k in ["stage 1", "stage-1", "tier 1", "tier-1", "phase 1", "prelims", "mains", "written exam", "computer based test", "cbt", "physical efficiency", "pet", "pst", "skill test", "trade test", "document verification", "medical exam", "interview"]):
            if len(dossier["selection_process"]) < 6 and 12 <= len(row_text) <= 190 and "click here" not in row_low:
                if row_text not in dossier["selection_process"]:
                    dossier["selection_process"].append(row_text)

        # --- G. Clean Exam Pattern Notes (With Contradiction Resolver) ---
        if any(k in row_low for k in ["negative marking", "total marks", "total questions", "duration", "minutes", "objective type", "sectional timing"]):
            if len(dossier["exam_pattern_notes"]) < 6 and 10 <= len(row_text) <= 180 and "click here" not in row_low:
                if row_text not in dossier["exam_pattern_notes"]:
                    dossier["exam_pattern_notes"].append(row_text)

        # --- H. Direct Official Links & PDFs ---
        for a in node.find_all("a", href=True):
            href = urljoin(article_url, a["href"].strip())
            a_txt = scrub_external_branding(re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip())
            context = f"{row_low} {a_txt.lower()}"

            if is_direct_post_target_url(href, allow_direct_pdf_on_cdn=True):
                is_pdf = href.lower().split("?")[0].endswith(".pdf")
                if is_pdf or any(k in context for k in ["notification", "advt", "advertisement", "brochure", "short notice", "official notice"]):
                    if any(k in context for k in ["syllabus", "exam pattern"]):
                        if not dossier["links"]["syllabus_link"]:
                            dossier["links"]["syllabus_link"] = href
                    elif any(k in context for k in ["answer key", "response sheet"]):
                        if not dossier["links"]["answer_key_link"]:
                            dossier["links"]["answer_key_link"] = href
                    elif any(k in context for k in ["result", "merit list", "cutoff", "selected list"]):
                        if not dossier["links"]["result_link"]:
                            dossier["links"]["result_link"] = href
                    elif any(k in context for k in ["admit card", "hall ticket", "call letter"]):
                        if not dossier["links"]["admit_card_link"]:
                            dossier["links"]["admit_card_link"] = href
                    else:
                        if not dossier["links"]["notif_pdf"]:
                            dossier["links"]["notif_pdf"] = href

            if is_direct_post_target_url(href, allow_direct_pdf_on_cdn=False):
                if any(k in context for k in ["apply online", "registration", "online form", "candidate login", "apply link", "fill online"]):
                    if not dossier["links"]["apply_link"]:
                        dossier["links"]["apply_link"] = href
                elif any(k in context for k in ["admit card", "hall ticket", "call letter", "exam city", "download admit"]):
                    if not dossier["links"]["admit_card_link"]:
                        dossier["links"]["admit_card_link"] = href
                elif any(k in context for k in ["answer key", "response sheet", "question paper", "objection"]):
                    if not dossier["links"]["answer_key_link"]:
                        dossier["links"]["answer_key_link"] = href
                elif any(k in context for k in ["download result", "check result", "result", "merit list", "score card", "scorecard", "cutoff"]):
                    if not dossier["links"]["result_link"]:
                        dossier["links"]["result_link"] = href
                elif any(k in context for k in ["syllabus", "exam pattern"]):
                    if not dossier["links"]["syllabus_link"]:
                        dossier["links"]["syllabus_link"] = href
                elif any(k in context for k in ["official website", "official portal", "official site"]):
                    if not dossier["links"]["official_site"]:
                        dossier["links"]["official_site"] = href

            if is_direct_post_target_url(href, allow_direct_pdf_on_cdn=True):
                label_clean = re.sub(r"\bclick here\b", "", row_text, flags=re.IGNORECASE).strip(" :-–|") or a_txt or "Official Portal Link"
                if len(label_clean) <= 90 and not is_noise_or_menu_line(label_clean) and not any(x["url"] == href for x in dossier["all_extracted_links"]):
                    dossier["all_extracted_links"].append({"label": label_clean, "url": href})

    # Resolve Contradictory Negative Marking (e.g. if '1/3' or '0.25' exists, drop 'Negative Marking No')
    has_specific_neg = any(
        any(k in note.lower() for k in ["1/3", "1/4", "0.25", "0.50", "0.33", "one-third", "one fourth", "deducted"])
        for note in dossier["exam_pattern_notes"]
    )
    if has_specific_neg:
        dossier["exam_pattern_notes"] = [
            n for n in dossier["exam_pattern_notes"]
            if not re.search(r"negative\s+marking\s*[:\-]?\s*no\b", n, re.I)
        ]

    now = datetime.now()
    valid_post_dates = [d for d in post_dates_found if d <= now + timedelta(days=2)]
    if valid_post_dates:
        chosen_dt = max(valid_post_dates)
        dossier["dates"]["real_post_date_obj"] = chosen_dt
        if not dossier["dates"]["release_date"]:
            dossier["dates"]["release_date"] = chosen_dt.strftime("%d %b %Y")

    if not dossier["total_vacancy"]:
        t_vac = re.search(r"\b([0-9,]{2,7})\s+(?:Posts?|Vacanc(?:y|ies))\b", title, re.IGNORECASE)
        if t_vac:
            raw_n = t_vac.group(1).replace(",", "")
            if raw_n.isdigit():
                dossier["vacancy_number"] = int(raw_n)
                dossier["total_vacancy"] = f"{t_vac.group(1)} Posts"

    return dossier


def passes_strict_15_day_and_link_gate(dossier, title):
    t_low = title.lower()
    if any(old_yr in t_low for old_yr in ["2020", "2021", "2022", "2023", "2024"]):
        if "2026" not in t_low and "2025" not in t_low:
            return False

    now = datetime.now()
    cutoff_15_days = now - timedelta(days=15)

    post_dt = dossier["dates"].get("real_post_date_obj")
    if not post_dt:
        notif_dt = parse_any_date_string(dossier["dates"].get("notification_date", ""))
        start_dt = parse_any_date_string(dossier["dates"].get("apply_start_date", ""))
        candidates = [d for d in [notif_dt, start_dt] if d and d <= now + timedelta(days=2)]
        if candidates:
            post_dt = max(candidates)
            dossier["dates"]["real_post_date_obj"] = post_dt
            if not dossier["dates"]["release_date"]:
                dossier["dates"]["release_date"] = post_dt.strftime("%d %b %Y")

    if not post_dt or post_dt < cutoff_15_days:
        return False

    links = dossier["links"]
    return any(
        is_direct_post_target_url(u, allow_direct_pdf_on_cdn=True)
        for u in links.values()
        if u
    )


# ==============================================================================
# LAYER 5: OPTION A + OPTION B DOPAMINE EXAM PATTERN, SYLLABUS & QUOTE ENGINE
# (Matches Your Reference Photos: RBI Assistant, SBI PO/Clerk, LRA Syllabus)
# ==============================================================================
DOMAIN_EXAM_BLUEPRINTS = {
    "Banking": {
        "selection_stages": [
            "Phase 1: Preliminary Online Examination (Objective CBT — Qualifying)",
            "Phase 2: Mains Online Examination (Objective + Descriptive Test)",
            "Phase 3: Language Proficiency Test (LPT) / Interview & Document Verification",
        ],
        "pattern_table": [
            ["1. English Language", "30 Qs", "30 Marks", "20 Minutes"],
            ["2. Numerical Ability / Quant", "35 Qs", "35 Marks", "20 Minutes"],
            ["3. Reasoning Ability", "35 Qs", "35 Marks", "20 Minutes"],
            ["Total (Prelims CBT)", "100 Qs", "100 Marks", "60 Minutes"],
        ],
        "pattern_highlights": [
            "Exam Mode: Online Computer Based Test (CBT) with Sectional Timing",
            "Negative Marking: 0.25 Marks (1/4th) deducted for each wrong answer",
            "Mains Pattern: GA/Banking Awareness, English, Reasoning & Computer, Data Analysis & DI (200 Marks)",
        ],
        "syllabus_cards": [
            {
                "subject": "1. Quantitative Aptitude & DI",
                "color": "#15803d",
                "topics": ["Simplification & Approximation", "Missing & Wrong Number Series", "Quadratic Equations", "Data Interpretation (Table, Pie, Bar, Caselet)", "Percentage, Profit & Loss, Discount", "Ratio, Partnership & Ages", "Time & Work, Pipes & Cisterns", "Time, Speed, Distance & Boats"],
            },
            {
                "subject": "2. Reasoning Ability & Puzzles",
                "color": "#ea580c",
                "topics": ["Sitting Arrangement (Linear, Circular, Square)", "Puzzles (Floor, Flat, Box, Month/Day Based)", "Syllogism (Only / Only a Few)", "Inequalities (Coded & Direct)", "Blood Relations & Direction Sense", "Coding-Decoding & Alphanumeric Series", "Input-Output & Data Sufficiency", "Logical & Critical Reasoning"],
            },
            {
                "subject": "3. English Language",
                "color": "#1d4ed8",
                "topics": ["Reading Comprehension (Economy/Finance Tone)", "Cloze Test & Fillers (Double/Triple)", "Error Detection & Sentence Improvement", "Para Jumbles / Sentence Rearrangement", "Word Swap, Connectors & Starters", "Vocabulary, Idioms & Phrasal Verbs"],
            },
            {
                "subject": "4. Banking & General Awareness",
                "color": "#6d28d9",
                "topics": ["Last 6 Months Current Affairs (National & Global)", "RBI Monetary Policy, Repo, CRR, SLR & Basel Norms", "NPCI Digital Products (UPI, CBDC, AePS, NACH)", "Priority Sector Lending (PSL) & NPA Norms", "Union Budget, Economic Survey & Govt Schemes", "Static Banking, Headquarters & Financial Terms"],
            },
        ],
    },
    "SSC": {
        "selection_stages": [
            "Tier-1: Computer Based Examination (Objective MCQs — 200 Marks)",
            "Tier-2: Mains Computer Based Examination (Paper-I Compulsory + Data Entry / Dest)",
            "Stage-3: Document Verification (DV) by User Department & Medical Fitness",
        ],
        "pattern_table": [
            ["1. General Intelligence & Reasoning", "25 Qs", "50 Marks", "Combined"],
            ["2. General Awareness & GK", "25 Qs", "50 Marks", "60 Minutes"],
            ["3. Quantitative Aptitude", "25 Qs", "50 Marks", "(1 Hour)"],
            ["4. English Comprehension", "25 Qs", "50 Marks", "Total Time"],
            ["Total (Tier-1 CBT)", "100 Qs", "200 Marks", "60 Minutes"],
        ],
        "pattern_highlights": [
            "Exam Mode: Online Computer Based Test (TCS Pattern Objective MCQs)",
            "Marking Scheme: +2 Marks for each correct answer | Negative Marking: -0.50 Marks (Tier-1)",
            "Medium of Exam: Bilingual (English & Hindi)",
        ],
        "syllabus_cards": [
            {
                "subject": "1. Quantitative Aptitude (Arith + Adv)",
                "color": "#15803d",
                "topics": ["Percentage, Profit & Loss, Discount", "Simple & Compound Interest, Installments", "Ratio, Mixture, Alligation & Average", "Time & Work, Time Speed & Distance", "Algebra Identities & Surds/Indices", "Geometry (Triangles, Circles, Chords)", "Mensuration 2D & 3D (Prism, Pyramid, Cone)", "Trigonometry, Height & Distance, DI"],
            },
            {
                "subject": "2. General Intelligence & Reasoning",
                "color": "#ea580c",
                "topics": ["Number & Missing Series, Analogy", "Coding-Decoding & Odd One Out", "Syllogism & Venn Diagrams", "Blood Relations & Direction Test", "Dice, Cube & Paper Folding/Cutting", "Mirror/Water Image & Embedded Figures", "Mathematical Operations (BODMAS)", "Seating Arrangement & Matrix"],
            },
            {
                "subject": "3. English Comprehension",
                "color": "#1d4ed8",
                "topics": ["Grammar Error Spotting & Sentence Improvement", "Active-Passive Voice & Direct-Indirect Narration", "Cloze Passage & Reading Comprehension", "One Word Substitution (OWS)", "Idioms & Phrases", "Synonyms, Antonyms & Spellings", "Para Jumbles (PQRS)"],
            },
            {
                "subject": "4. General Awareness & Science",
                "color": "#6d28d9",
                "topics": ["Indian Polity (Articles, Amendments, Writs)", "Ancient, Medieval & Modern History (INC, 1857)", "Indian & World Geography (Rivers, Passes, Soils)", "General Science (Physics, Chemistry, Biology, Vitamins)", "Indian Economy, Five-Year Plans & Budget", "Static GK (Classical/Folk Dances, Festivals, Awards)", "Last 1 Year Current Affairs, Sports & Books"],
            },
        ],
    },
    "Railway": {
        "selection_stages": [
            "Stage 1: 1st Stage Computer Based Test (CBT-1 Screening)",
            "Stage 2: 2nd Stage Computer Based Test (CBT-2) / CBAT / Typing Skill Test",
            "Stage 3: Document Verification (DV) & Railway Medical Fitness Test (A2/B1/C2)",
        ],
        "pattern_table": [
            ["1. General Awareness & Science", "40 Qs", "40 Marks", "Combined"],
            ["2. Mathematics", "30 Qs", "30 Marks", "90 Minutes"],
            ["3. General Intelligence & Reasoning", "30 Qs", "30 Marks", "(1.5 Hours)"],
            ["Total (Railway CBT)", "100 Qs", "100 Marks", "90 Minutes"],
        ],
        "pattern_highlights": [
            "Exam Mode: Online Computer Based Test (Multi-Shift Normalized)",
            "Marking Scheme: +1 Mark per question | Negative Marking: 1/3rd (0.33) Mark per wrong answer",
            "Shortlisting for DV: 1:1 Ratio of RRB-Wise Notified Vacancies",
        ],
        "syllabus_cards": [
            {
                "subject": "1. Mathematics",
                "color": "#15803d",
                "topics": ["Number System, BODMAS, Decimals & Fractions", "LCM, HCF, Ratio & Proportions", "Percentage, Profit & Loss, SI & CI", "Time & Work, Time & Distance, Pipes", "Mensuration, Algebra, Geometry & Trigonometry", "Elementary Statistics (Mean, Median, Mode, SD)"],
            },
            {
                "subject": "2. General Intelligence & Reasoning",
                "color": "#ea580c",
                "topics": ["Analogies, Alphabetical & Number Series", "Coding and Decoding, Mathematical Operations", "Relationships, Syllogism & Jumbling", "Venn Diagram, Data Interpretation & Sufficiency", "Statement-Conclusion & Statement-Assumptions", "Analytical Reasoning, Directions & Classification"],
            },
            {
                "subject": "3. General Science (NCERT 10th Level)",
                "color": "#0284c7",
                "topics": ["Physics: Motion, Work, Energy, Light, Electricity, Units", "Chemistry: Atomic Structure, Periodic Table, Acids/Bases, Metals", "Biology: Human Body Systems, Diseases, Nutrition, Plant Kingdom", "Environmental Science & Basic Computer Applications"],
            },
            {
                "subject": "4. General Awareness & Current Affairs",
                "color": "#6d28d9",
                "topics": ["Current Events of National & International Importance", "Indian Railways History, Zones & DFCCIL Facts", "Indian Polity, Constitution & Governance", "History of India & Freedom Struggle", "Physical, Social & Economic Geography of India", "UN Organizations, Space (ISRO) & Defense Programs"],
            },
        ],
    },
    "Police_Defence": {
        "selection_stages": [
            "Stage 1: Written Examination (OMR / Computer Based Test)",
            "Stage 2: Physical Standard Test (PST — Height/Chest) & Physical Efficiency Test (PET — Running)",
            "Stage 3: Document Verification & Detailed Medical Examination (DME)",
        ],
        "pattern_table": [
            ["1. General Knowledge & Current Affairs", "38 Qs", "76 Marks", "Combined"],
            ["2. Numerical & Mental Ability", "38 Qs", "76 Marks", "120 Minutes"],
            ["3. Mental Aptitude, IQ & Reasoning", "37 Qs", "74 Marks", "(2 Hours)"],
            ["4. General Hindi / English Language", "37 Qs", "74 Marks", "Total Time"],
            ["Total (Written Exam)", "150 Qs", "300 Marks", "120 Minutes"],
        ],
        "pattern_highlights": [
            "Exam Mode: Objective Type Written Exam followed by Physical Endurance Test",
            "Negative Marking: 0.25 / 0.50 Marks deducted per wrong answer as per board rule",
            "Physical Requirement: Qualifying in PST & Running (PET) is mandatory",
        ],
        "syllabus_cards": [
            {
                "subject": "1. General Knowledge & State GK",
                "color": "#1d4ed8",
                "topics": ["Indian Constitution, Fundamental Rights & Police Act", "History, Culture, Geography & Economy of India", "State-Specific GK (Districts, Folk Arts, Rivers, Schemes)", "Internal Security, Human Rights & Cyber Crime", "National & International Current Affairs & Awards"],
            },
            {
                "subject": "2. Reasoning & Mental Aptitude",
                "color": "#ea580c",
                "topics": ["Number/Letter Series, Coding-Decoding & Analogy", "Direction Sense, Blood Relations & Ranking", "Syllogism, Logical Venn Diagrams & Dice", "Public Interest, Law & Order, Communal Harmony", "Rule of Law, Professional Information & Police System"],
            },
            {
                "subject": "3. Numerical Ability (Maths)",
                "color": "#15803d",
                "topics": ["Number System, Simplification, HCF & LCM", "Percentage, Profit & Loss, Discount", "Simple & Compound Interest, Partnership", "Ratio & Proportion, Average", "Time & Work, Time Speed & Distance, Mensuration"],
            },
            {
                "subject": "4. Language (Hindi / English)",
                "color": "#6d28d9",
                "topics": ["Varnmala, Sandhi, Samas & Upsarg-Pratyay", "Tatsam-Tadbhav, Paryayvachi & Vilom Shabd", "Muhavare, Lokoktiyan & Vakyansh ke liye ek shabd", "kaal, Vachya, Avyay & Ashuddhi Shodhan", "Unseen Passage Comprehension & Famous Poets/Authors"],
            },
        ],
    },
    "Technical_PSU": {
        "selection_stages": [
            "Stage 1: Online / Written Computer Based Test (Domain Technical + Aptitude)",
            "Stage 2: Trade Test / Skill & Practical Test (Qualifying in Nature)",
            "Stage 3: Document Verification & Pre-Employment Medical Examination",
        ],
        "pattern_table": [
            ["1. Domain Technical / Trade Subject", "60 Qs", "60 Marks", "Combined"],
            ["2. General Aptitude & Numerical Ability", "15 Qs", "15 Marks", "90–120"],
            ["3. Reasoning & General Awareness", "15 Qs", "15 Marks", "Minutes"],
            ["4. General English", "10 Qs", "10 Marks", "Total Time"],
            ["Total (Technical Exam)", "100 Qs", "100 Marks", "90–120 Mins"],
        ],
        "pattern_highlights": [
            "Exam Mode: Written / Online Objective Test (CBT) + Practical Skill/Trade Test",
            "Weightage: 60%–70% questions from concerned Engineering Diploma / ITI Trade",
            "Skill Test: Practical Trade Test is qualifying in nature",
        ],
        "syllabus_cards": [
            {
                "subject": "1. Core Technical / Trade Discipline",
                "color": "#0369a1",
                "topics": ["Core Trade Theory (Fitter / Welder / Electrician / Machinist / Electronics / Civil / Mech)", "Workshop Calculation, Engineering Drawing & Safety Rules", "Measuring Instruments (Vernier Caliper, Micrometer, Gauges)", "Machines, Thermodynamics / Electrical Circuits / Shipbuilding Basics"],
            },
            {
                "subject": "2. Quantitative Aptitude",
                "color": "#15803d",
                "topics": ["Number System, Fractions, Decimals & Percentage", "Ratio & Proportion, Average, Profit & Loss", "Time & Work, Speed & Distance", "Mensuration (Area, Volume of Cylinder, Cone, Sphere)", "Basic Algebra & Trigonometry"],
            },
            {
                "subject": "3. Reasoning & General Intelligence",
                "color": "#ea580c",
                "topics": ["Number & Alphabet Series, Analogy", "Coding-Decoding & Blood Relations", "Direction Sense & Seating Arrangement", "Non-Verbal Mirror/Water Images & Figure Completion"],
            },
            {
                "subject": "4. General Awareness & English",
                "color": "#6d28d9",
                "topics": ["Current Affairs, Defense PSUs & Indian Economy", "Basic General Science (Physics & Chemistry Laws)", "Indian Polity & Geography", "Basic English Grammar, Articles, Prepositions & Comprehension"],
            },
        ],
    },
    "Teaching": {
        "selection_stages": [
            "Stage 1: Written Objective Examination (Child Pedagogy, Languages & Subject Concerned)",
            "Stage 2: Document Verification / Demo Teaching / Academic Merit List",
        ],
        "pattern_table": [
            ["1. Child Development & Pedagogy", "30 Qs", "30 Marks", "Combined"],
            ["2. Language-I & Language-II", "60 Qs", "60 Marks", "150 Minutes"],
            ["3. Domain Subject (Maths/Science/Social/TGT/PGT)", "60 Qs", "60 Marks", "(2.5 Hours)"],
            ["Total", "150 Qs", "150 Marks", "150 Minutes"],
        ],
        "pattern_highlights": [
            "Exam Mode: Objective Multiple Choice Questions (OMR / CBT)",
            "Focus Area: NEP 2020, NCF, Inclusive Education, Pedagogy & Subject Mastery",
        ],
        "syllabus_cards": [
            {
                "subject": "1. Child Development & Pedagogy",
                "color": "#be123c",
                "topics": ["Theories of Piaget, Vygotsky & Kohlberg", "Concept of Inclusive Education & Special Needs", "NEP 2020, RTE Act 2009 & NCF Guidelines", "Assessment, Evaluation & Learning Motivation"],
            },
            {
                "subject": "2. Language-I & II (Hindi/English)",
                "color": "#1d4ed8",
                "topics": ["Unseen Prose & Poetry Comprehension", "Principles of Language Teaching & Acquisition", "Grammar, Vocabulary, Figures of Speech & Remedial Teaching"],
            },
            {
                "subject": "3. Concerned Subject & GS",
                "color": "#15803d",
                "topics": ["NCERT/SCERT Core Subject Syllabus (Class 6 to 12 Level)", "Indian National Movement, Polity, Geography & Environment", "Basic Arithmetic, Reasoning & Current Affairs"],
            },
        ],
    },
    "State_PSC_Civil": {
        "selection_stages": [
            "Stage 1: Preliminary Examination (General Studies + CSAT / Aptitude)",
            "Stage 2: Mains Written Examination (General Studies + Essay / Optional)",
            "Stage 3: Personality Test / Interview & Document Verification",
        ],
        "pattern_table": [
            ["Paper-I: General Studies (GS) & Current Affairs", "140–150 Qs", "200 Marks", "120 Minutes"],
            ["Paper-II: CSAT / General Hindi / Aptitude", "60–100 Qs", "100–200M", "120 Minutes"],
        ],
        "pattern_highlights": [
            "Exam Mode: Offline OMR / Online Objective Prelims followed by Mains",
            "Negative Marking: 1/3rd (0.33) or 0.25 Marks per wrong answer as per Commission norms",
        ],
        "syllabus_cards": [
            {
                "subject": "1. Indian Polity, History & Culture",
                "color": "#1d4ed8",
                "topics": ["Indian Constitution, Parliament, Judiciary & Panchayati Raj", "Ancient, Medieval & Modern Indian History", "Indian National Movement (1857–1947)", "Art, Culture & State-Specific Heritage"],
            },
            {
                "subject": "2. Geography, Environment & Economy",
                "color": "#15803d",
                "topics": ["Physical, Social & Economic Geography of India & World", "Ecology, Biodiversity, Climate Change & National Parks", "Sustainable Development, Budget, Fiscal & Monetary Policy"],
            },
            {
                "subject": "3. General Science & Current Affairs",
                "color": "#ea580c",
                "topics": ["Everyday Science (Physics, Chemistry, Biology, Space & Biotech)", "National & International Current Events (Last 12 Months)", "Government Welfare Schemes & Census Data"],
            },
            {
                "subject": "4. Aptitude, Reasoning & Language",
                "color": "#6d28d9",
                "topics": ["Comprehension & Interpersonal Communication Skills", "Logical Reasoning, Analytical Ability & Decision Making", "General Mental Ability & Class 10th Level Numeracy / Language"],
            },
        ],
    },
}


# INTENT + FIELD AWARE UNIQUE QUOTE GENERATOR
def generate_unique_intent_quote(title, primary_intent, exam_field, used_quotes_set, counter_seed):
    clean_exam = re.sub(
        r"\b(online form|recruitment|2026|2025|apply online|download|notification|various posts)\b",
        "",
        title,
        flags=re.IGNORECASE,
    )
    clean_exam = re.sub(r"\s+", " ", clean_exam).strip(" -–|:")[:42] or title[:38]

    field_ hooks = {
        "Banking": "Speed Math, DI aur Seating Puzzles par aaj se apni pakad lohe jaisi banayein",
        "SSC": "PYQs, Calculation Speed aur 100% Conceptual Accuracy se Merit List mein top karein",
        "Railway": "NCERT Science, Maths aur Reasoning ke har ek topic ko apna sabse bada hathiyar banayein",
        "Police_Defence": "Written Exam ki taiyari aur Physical Ground ki daud—dono mein aaj apna 100% paseena bahayein",
        "Technical_PSU": "Apne Core Technical Trade aur Aptitude ki mehnat se is PSU mein apni seat pakki karein",
        "Teaching": "Pedagogy aur Subject Mastery se aane wali peedhi ke निर्माता banein",
        "State_PSC_Civil": "GS, State GK aur Answer Writing ke atoot anushasan se Adhikari ki kursi hasil karein",
    }
    f_hook = field_hooks.get(exam_field, field_hooks["SSC"])

    intent_frames = {
        "INTENT_APPLY": [
            f"🔥 [{clean_exam} Mission]: Form bharna sirf pehla kadam hai—{f_hook}!",
            f"🎯 [{clean_exam} Lakshya]: Lakhon aavedan aayenge, par chayan unhi ka hoga jo aaj Day-1 se {f_hook.lower()}!",
            f"⚡ [{clean_exam} Sankalp]: Yeh sirf ek notification nahi, aapke parivar ke sapno ka Appointment Letter hai—{f_hook.lower()}!",
        ],
        "INTENT_DATE_EXTENDED": [
            f"⏳ [{clean_exam} Extended Window]: Aakhiri mauka mila hai! Bina ek pal gawaye aaj hi form lock karein aur {f_hook.lower()}!",
        ],
        "INTENT_ADMIT_CARD": [
            f"⚔️ [{clean_exam} Admit Card Out]: Ranbhoomi ka bulawa aa chuka hai! Ab naye topics chhodkar {f_hook.lower()}!",
            f"⏱️ [{clean_exam} Final Sprint]: Hall Ticket haath mein hai—Exam Hall ka pressure wahi jeetega jo aakhiri dino mein {f_hook.lower()}!",
        ],
        "INTENT_ANSWER_KEY": [
            f"🔍 [{clean_exam} Response Sheet Audit]: Har ek sawal ka post-mortem karein, apna raw score janchein aur agle charan ke liye {f_hook.lower()}!",
        ],
        "INTENT_RESULT": [
            f"🏆 [{clean_exam} Result Milestone]: Parinaam ghoshit ho chuka hai! Apna Roll Number check karein aur Document Verification / Next Stage ke liye kamar kas lein!",
        ],
        "INTENT_SYLLABUS": [
            f"📘 [{clean_exam} Official Blueprint]: Toppers alag kitabein nahi padhte, wo syllabus ke har ek topic ko ungliyon par yaad rakhte hain—{f_hook.lower()}!",
        ],
        "INTENT_ADMISSION": [
            f"🎓 [{clean_exam} Admission Alert]: Apne documents, rank card aur counselling choices ko samay se pehle lock karein!",
        ],
    }

    frames = intent_frames.get(primary_intent, intent_frames["INTENT_APPLY"])
    for idx in range(len(frames)):
        candidate = frames[(counter_seed + idx) % len(frames)]
        if candidate.lower() not in used_quotes_set:
            used_quotes_set.add(candidate.lower())
            return candidate

    sig_hash = hashlib.md5(f"{clean_exam}_{primary_intent}_{counter_seed}".encode("utf-8")).hexdigest()[:4].upper()
    unique_q = f"🌟 [{clean_exam} | Target #{sig_hash}]: {f_hook}—aaj ka har ek ghanta aapke selection ki neev rakhega!"
    used_quotes_set.add(unique_q.lower())
    return unique_q


def build_dopamine_todo_strategy(title, exam_field, primary_intent):
    """
    Builds a Checkbox To-Do Study Plan matching your reference photo (Banking Exam 60/90 Days Challenge To-Do List).
    """
    if primary_intent in ["INTENT_RESULT", "INTENT_ANSWER_KEY"]:
        return {
            "mode": "POST_RESULT_DV",
            "heading": "🏆 POST-RESULT & DOCUMENT VERIFICATION (DV) TO-DO CHECKLIST",
            "month_1": "Download Official Merit List / Answer Key PDF and verify your Roll Number & Category Cut-Off.",
            "month_2": "Organize Original 10th/12th/Degree Certificates, Valid OBC/EWS/SC/ST Caste Certificate & Domicile.",
            "month_3": "Prepare 8 Passport Photographs, Aadhar/PAN ID Proof & Medical Fitness readiness for final joining.",
            "todo_boxes": [
                {"title": "1. Score & Merit Verification", "color": "#15803d", "items": ["☑ Verify Roll Number in Merit PDF", "☑ Compare Raw Score with Category Cut-Off", "☑ Check Objection Window (if Answer Key)"]},
                {"title": "2. Mandatory DV Documents", "color": "#1d4ed8", "items": ["☑ 10th, 12th & Graduation Original Marksheets", "☑ Valid Central/State Caste & EWS Certificate", "☑ Printout of Submitted Online Application Form"]},
            ],
        }
    if primary_intent == "INTENT_ADMIT_CARD":
        return {
            "mode": "ADMIT_30_DAY_SPRINT",
            "heading": "⚡ FINAL 30-DAY ADMIT CARD REVISION & EXAM HALL TO-DO LIST",
            "month_1": "Days 1–10 (Formula & Concept Revision): Revise all high-weightage formulas, grammar rules & 6-month Current Affairs.",
            "month_2": "Days 11–20 (Shift-Timed Mocks): Attempt 1 Full Mock daily at the exact shift time printed on your Admit Card.",
            "month_3": "Days 21–30 (Accuracy Lock & Hall Readiness): Review Error Notebook, lock 90%+ accuracy & print Admit Card + ID.",
            "todo_boxes": [
                {"title": "1. Speed Math & Reasoning Sprint", "color": "#1d4ed8", "items": ["☑ Revise Tables 1–40, Squares 1–50 & Cubes 1–30", "☑ Solve 25 PYQ Arithmetic & 4 Seating Puzzles Daily", "☑ Practice 20 Coding-Decoding & Syllogism Sets"]},
                {"title": "2. GK/CA, Language & Mock Test", "color": "#ea580c", "items": ["☑ Revise Last 6 Months Current Affairs Capsule", "☑ Attempt 1 Full Shift-Time Mock Test Daily", "☑ Analyze Wrong Questions & Update Error Log"]},
            ],
        }

    return {
        "mode": "MASTER_90_DAY_PLAN",
        "heading": f"🎯 90-DAY MASTER PREPARATION TO-DO ROADMAP ({exam_field.replace('_', ' ').upper()})",
        "month_1": "Month 1 (Days 1–30 | Foundation & Syllabus Decoding): Complete topic-wise concepts, build short formula notes & solve 50 questions daily.",
        "month_2": "Month 2 (Days 31–60 | Speed, PYQs & Sectional Mastery): Solve last 5 years' Official PYQs with timer & attempt 3 sectional mocks weekly.",
        "month_3": "Month 3 (Days 61–90 | Full-Length Mocks & Error Log): Attempt 1 Full Mock daily, revise Error Notebook & lock 90%+ accuracy.",
        "todo_boxes": [
            {"title": "1. Quantitative Aptitude & Speed Math", "color": "#1d4ed8", "items": ["☑ Revise Tables 1–50, Square Roots, Cube Roots & Fractions", "☑ Speed Math: 20 Simplification, Series & Quadratic Daily", "☑ Arithmetic/Advance: 30 Chapter-wise PYQ Questions Daily"]},
            {"title": "2. Reasoning Ability & Puzzles", "color": "#15803d", "items": ["☑ 4 Sets of Seating Arrangement & Floor/Box Puzzles Daily", "☑ 20 Questions of Coding-Decoding, Syllogism & Blood Relation", "☑ Non-Verbal, Series & Analytical Reasoning Practice"]},
            {"title": "3. English / Language Mastery", "color": "#be123c", "items": ["☑ Read 1 Editorial Daily (The Hindu In-App Reader Tool)", "☑ 20 Grammar Error Spotting & Cloze Test Questions", "☑ 15 New Vocabulary, Idioms & One-Word Substitutions"]},
            {"title": "4. General Awareness & Daily Mock", "color": "#ea580c", "items": ["☑ Daily 10 GK/CA Quiz + Static GK & Constitutional Articles", "☑ 1 Full-Length Timed Mock Test + Deep Mistake Analysis", "☑ Revise Wrong Questions Notebook before sleeping"]},
        ],
    }


def calculate_high_rush_score(title, dossier, is_today_last_date, is_extended):
    score = 50
    t_low = title.lower()
    post_dt = dossier["dates"].get("real_post_date_obj")
    if post_dt:
        days_ago = max(0, (datetime.now() - post_dt).days)
        score += max(0, (15 - days_ago) * 2)

    if any(k in t_low for k in ["ssc", "rrb", "railway", "ntpc", "group d", "ibps", "sbi", "upsc", "police", "constable", "bpsc", "uppsc", "mpsc", "ctet", "neet", "cuet", "jee", "agniveer", "gds", "india post", "shipyard", "gsl"]):
        score += 20

    vac_num = dossier.get("vacancy_number", 0)
    if vac_num >= 10000:
        score += 25
    elif vac_num >= 2000:
        score += 18
    elif vac_num >= 500:
        score += 10
    elif vac_num >= 50:
        score += 6

    if is_today_last_date:
        score += 22
    if is_extended:
        score += 15
    return score


# ==============================================================================
# LAYER 6: MASTER POST SYNTHESIZER (LEFT-RIGHT DOPAMINE UI + WORD-TO-WORD TEXT)
# ==============================================================================
class MasterSynthesizer:

    @staticmethod
    def build_post(raw_title, source_name, meta, dossier, used_quotes_set, counter_seed):
        title = scrub_external_branding(raw_title)
        links = dossier["links"]
        primary_url = (
            links["apply_link"]
            or links["result_link"]
            or links["admit_card_link"]
            or links["answer_key_link"]
            or links["notif_pdf"]
            or links["syllabus_link"]
            or links["official_site"]
        )
        if not primary_url:
            return None

        ist_tz = timezone(timedelta(hours=5, minutes=30))
        now_today_date = datetime.now(ist_tz).date()
        last_dt_obj = dossier["dates"].get("last_date_obj")
        is_today_last_date = bool(last_dt_obj and last_dt_obj.date() == now_today_date)
        is_closing_near_7_days = bool(
            last_dt_obj and 0 <= (last_dt_obj.date() - now_today_date).days <= 7
        )
        is_extended = bool(meta["is_extended"] or dossier["dates"].get("extended_date"))

        right_end_tag = ""
        right_end_badge_html = ""
        if is_today_last_date:
            right_end_tag = "Today Last Date"
            right_end_badge_html = "<span style='background:#dc2626; color:#ffffff; font-size:10.5px; font-weight:900; padding:2px 7px; border-radius:4px; margin-left:6px;'>⏳ Today Last Date</span>"
        elif is_extended:
            right_end_tag = "Date Extended"
            right_end_badge_html = "<span style='background:#fee2e2; color:#991b1b; font-size:10.5px; font-weight:800; padding:2px 7px; border-radius:4px; border:1px solid #fca5a5; margin-left:6px;'>📅 Date Extended</span>"
        elif is_closing_near_7_days:
            right_end_tag = "Closing Soon"
            right_end_badge_html = "<span style='background:#fef3c7; color:#b45309; font-size:10.5px; font-weight:800; padding:2px 7px; border-radius:4px; border:1px solid #fde68a; margin-left:6px;'>⏰ Closing Soon</span>"

        rush_score = calculate_high_rush_score(title, dossier, is_today_last_date, is_extended)
        intent_sig = f"{hashlib.md5(title.lower().encode('utf-8')).hexdigest()[:10]}__{meta['primary_intent']}"
        job_id = hashlib.md5(intent_sig.encode("utf-8")).hexdigest()[:12]

        post_dt_obj = dossier["dates"].get("real_post_date_obj")
        post_timestamp = int(post_dt_obj.timestamp()) if post_dt_obj else int(datetime.now(ist_tz).timestamp())
        now_str = datetime.now(ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")

        exam_field = meta.get("exam_field", "SSC")
        blueprint = DOMAIN_EXAM_BLUEPRINTS.get(exam_field, DOMAIN_EXAM_BLUEPRINTS["SSC"])

        quote = generate_unique_intent_quote(
            title, meta["primary_intent"], exam_field, used_quotes_set, counter_seed
        )
        strategy = build_dopamine_todo_strategy(title, exam_field, meta["primary_intent"])

        d_map = dossier["dates"]
        calendar_display_date = d_map["release_date"] or d_map["notification_date"] or d_map["apply_start_date"] or datetime.now(ist_tz).strftime("%d %b %Y")

        # Merge scraped Selection Process / Pattern with Domain Blueprint (Option A + Option B)
        clean_selection = dossier["selection_process"] if len(dossier["selection_process"]) >= 2 else blueprint["selection_stages"]
        pattern_table_rows = dossier["exam_pattern_rows"] if len(dossier["exam_pattern_rows"]) >= 2 else blueprint["pattern_table"]
        pattern_highlights = dossier["exam_pattern_notes"] if len(dossier["exam_pattern_notes"]) >= 2 else blueprint["pattern_highlights"]
        syllabus_cards = blueprint["syllabus_cards"]

        # Clean Post-Wise Qualification Rows
        clean_post_name = re.split(r"[-–|]", title)[0].replace("Online Form", "").replace("Recruitment", "").strip() or title[:40]
        post_qual_rows = dossier["post_qual_rows"]
        if not post_qual_rows:
            if dossier["eligibility_list"]:
                for idx_e, el_str in enumerate(dossier["eligibility_list"][:6]):
                    if ":" in el_str and len(el_str.split(":", 1)[0]) < 55:
                        p_n, p_q = el_str.split(":", 1)
                        post_qual_rows.append([p_n.strip(), p_q.strip(), dossier["total_vacancy"] or "As per Notice"])
                    else:
                        p_lbl = clean_post_name if idx_e == 0 else f"{clean_post_name} (Post Group {idx_e + 1})"
                        post_qual_rows.append([p_lbl, el_str, dossier["total_vacancy"] or "As per Notice"])
            else:
                post_qual_rows.append([
                    clean_post_name,
                    "10th / 12th / ITI / Diploma / Bachelor Degree in relevant discipline from a recognized Board or University (Refer Official Notification PDF).",
                    dossier["total_vacancy"] or "Various Posts",
                ])

        category_vacancy_rows = dossier["category_vacancy_rows"]

        fee_gen = dossier["fees"][0] if len(dossier["fees"]) > 0 else "Refer Official Notification PDF"
        fee_sc = dossier["fees"][1] if len(dossier["fees"]) > 1 else "SC / ST / PwBD / Ex-SM: As per Rules"
        age_str = " | ".join(dossier["age_criteria"][:2]) if dossier["age_criteria"] else "Minimum 18 Years | Maximum Age & Relaxation as per Recruitment Rules"
        short_qual_str = post_qual_rows[0][1] if post_qual_rows else "See Post-Wise Qualification Box Below"

        # Build Word-to-Word Plain Text for Admin Panel Editor (Zero HTML Code!)
        plain_short_lines = [
            f"Post Title: {title}",
            f"Organization / Board: {dossier['department']} ({meta['state']})",
            f"Category: {meta['category_label']} | Sector: {meta['job_type']}",
            f"Total Vacancy: {dossier['total_vacancy'] or 'Various Posts'}",
            f"Release Date: {calendar_display_date} | Apply Start Date: {d_map['apply_start_date'] or calendar_display_date}",
            f"Last Date to Apply: {d_map['last_date'] or 'As per Official Notice'} | Exam Date: {d_map['exam_date'] or 'Notify Soon'}",
            f"Application Fee (Gen/OBC/EWS): {fee_gen}",
            f"Application Fee (SC/ST/PH): {fee_sc}",
            f"Age Limit: {age_str}",
            f"Qualification Summary: {short_qual_str}",
        ]
        if dossier["short_info"]:
            plain_short_lines.insert(1, f"Overview: {dossier['short_info']}")
        plain_short_text = "\n".join(plain_short_lines)

        plain_full_lines = [
            "=== 1. POST-WISE QUALIFICATION & ELIGIBILITY ===",
            *[f"• {r[0]} : {r[1]}" + (f" ({r[2]})" if len(r) > 2 and r[2] else "") for r in post_qual_rows],
            "",
            "=== 2. SELECTION PROCESS ===",
            *[f"• {s}" for s in clean_selection],
            "",
            "=== 3. EXAM PATTERN ===",
            *[f"• {' | '.join(r)}" for r in pattern_table_rows],
            *[f"• {h}" for h in pattern_highlights],
            "",
            "=== 4. DETAILED SUBJECT-WISE SYLLABUS ===",
            *[f"• {c['subject']}: {', '.join(c['topics'])}" for c in syllabus_cards],
            "",
            f"=== 5. {strategy['heading']} ===",
            f"• {strategy['month_1']}",
            f"• {strategy['month_2']}",
            f"• {strategy['month_3']}",
        ]
        plain_full_text = "\n".join(plain_full_lines)

        # Google Search Rich Results Schema (Targeting Top Search Widgets: job, naukri, vacancy, sarkari result, etc.)
        google_schema = {
            "@context": "https://schema.org/",
            "@type": "JobPosting",
            "title": title,
            "description": dossier["short_info"] or plain_short_text,
            "identifier": {
                "@type": "PropertyValue",
                "name": dossier["department"],
                "value": job_id,
            },
            "datePosted": (post_dt_obj or datetime.now(ist_tz)).strftime("%Y-%m-%d"),
            "validThrough": (last_dt_obj or (datetime.now(ist_tz) + timedelta(days=30))).strftime("%Y-%m-%d"),
            "employmentType": "FULL_TIME",
            "hiringOrganization": {
                "@type": "Organization",
                "name": dossier["department"],
                "sameAs": links["official_site"] or primary_url,
            },
            "jobLocation": {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressRegion": meta["state"],
                    "addressCountry": "IN",
                },
            },
            "keywords": "sarkari naukri, sarkari result, free job alert, govt job, vacancy 2026, sarkari naukar, recruitment, online form",
            "directApply": True,
        }

        return {
            "id": job_id,
            "intent_signature": intent_sig,
            "title": title,
            "overview": dossier["short_info"] or f"{title} official notification, post-wise eligibility, exam pattern, syllabus and direct links.",
            "summary": dossier["short_info"],
            "dept": dossier["department"],
            "category": meta["category_key"],
            "category_label": meta["category_label"],
            "admin_box": meta["admin_box"],
            "primary_intent": meta["primary_intent"],
            "exam_field": exam_field,
            "job_type": meta["job_type"],
            "sector": meta["sector"],
            "state": meta["state_code"],
            "state_name": meta["state"],
            "scope": "central" if meta["state_code"] == "all" else "state",
            "unique_quote": quote,
            "source": source_name,
            "isVerified": True,
            "isAutoPublished": True,
            "adminSeen": False,
            "date": calendar_display_date,
            "post_date": calendar_display_date,
            "releaseDate": d_map["release_date"] or calendar_display_date,
            "notificationDate": d_map["notification_date"] or calendar_display_date,
            "lastDate": d_map["last_date"] or "As per Official Notice",
            "post_timestamp": post_timestamp,
            "isExtended": is_extended,
            "isTodayLastDate": is_today_last_date,
            "isClosingNear7Days": is_closing_near_7_days,
            "rightEndTag": right_end_tag,
            "rightEndBadgeHtml": right_end_badge_html,
            "rushScore": rush_score,
            "isTrendingTop6": False,
            "total_vacancy": dossier["total_vacancy"] or "Various Posts",
            "totalPosts": dossier["total_vacancy"] or "Various Posts",
            "qual": short_qual_str,
            "feeGen": fee_gen,
            "feeSc": fee_sc,
            "ageLimitText": age_str,
            "important_dates": {
                "release_date": d_map["release_date"] or calendar_display_date,
                "notification_date": d_map["notification_date"] or calendar_display_date,
                "apply_start_date": d_map["apply_start_date"] or calendar_display_date,
                "last_date": d_map["last_date"],
                "extended_date": d_map["extended_date"],
                "fee_last_date": d_map["fee_last_date"],
                "exam_date": d_map["exam_date"],
                "admit_card_date": d_map["admit_card_date"],
                "answer_key_date": d_map["answer_key_date"],
                "result_date": d_map["result_date"],
            },
            "dates": {
                "start": d_map["apply_start_date"] or calendar_display_date,
                "end": d_map["last_date"] or "Check Notice",
                "exam": d_map["exam_date"] or "As per Schedule",
            },
            "application_fee": dossier["fees"] if dossier["fees"] else [f"Gen / OBC / EWS: {fee_gen}", f"SC / ST / Reserved: {fee_sc}"],
            "age_criteria": dossier["age_criteria"] if dossier["age_criteria"] else [age_str],
            "eligibility_list": dossier["eligibility_list"] if dossier["eligibility_list"] else [short_qual_str],
            "post_qual_rows": post_qual_rows,
            "category_vacancy_rows": category_vacancy_rows,
            "vacancy_rows": category_vacancy_rows if category_vacancy_rows else post_qual_rows,
            "selection_process": clean_selection,
            "exam_pattern_table": pattern_table_rows,
            "exam_pattern_highlights": pattern_highlights,
            "exam_pattern": [f"{' | '.join(r)}" for r in pattern_table_rows] + pattern_highlights,
            "syllabus_cards": syllabus_cards,
            "exam_strategy_90_days": strategy,
            "plain_short_description": plain_short_text,
            "plain_full_description": plain_full_text,
            "social_links": {
                "whatsapp": "",
                "telegram": "",
                "instagram": "",
                "facebook": "",
            },
            "link": primary_url,
            "url": primary_url,
            "apply_link": links["apply_link"] or primary_url,
            "applyUrl": links["apply_link"] or primary_url,
            "notif_url": links["notif_pdf"],
            "notifUrl": links["notif_pdf"],
            "download_pdf": links["notif_pdf"],
            "admit_card_link": links["admit_card_link"],
            "answer_key_link": links["answer_key_link"],
            "result_link": links["result_link"],
            "syllabus_link": links["syllabus_link"],
            "official_website": links["official_site"] or primary_url,
            "webUrl": links["official_site"] or primary_url,
            "all_links": dossier["all_extracted_links"],
            "google_schema": google_schema,
            "updated_at": now_str,
            "updatedAt": datetime.now(ist_tz).isoformat(),
            "status": "published",
        }


# ==============================================================================
# LAYER 7: OPTION A (AUTOMATIC OLDEST 2-DAYS STORAGE PRUNER)
# ==============================================================================
def prune_oldest_two_days_storage(posts_list, force_prune=False, prune_days=2):
    """
    Option A & Option B Storage Manager:
    Automatically deletes the oldest N days (default: 2 days) of posts when storage size,
    post count, or manual admin trigger requires cleanup.
    """
    if not posts_list:
        return posts_list, 0

    file_size_mb = 0.0
    if os.path.exists(DATABASE_FILE):
        try:
            file_size_mb = os.path.getsize(DATABASE_FILE) / (1024 * 1024)
        except Exception:
            file_size_mb = 0.0

    needs_pruning = (
        force_prune
        or FORCE_PURGE_FLAG
        or file_size_mb >= MAX_DB_SIZE_MB
        or len(posts_list) > MAX_ACTIVE_POSTS
    )

    if not needs_pruning:
        return posts_list, 0

    # Group posts by calendar day bucket (YYYY-MM-DD) from post_timestamp
    day_buckets = set()
    for p in posts_list:
        ts = p.get("post_timestamp", 0)
        if ts > 0:
            day_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            day_buckets.add(day_str)

    sorted_days = sorted(day_buckets)
    if len(sorted_days) <= prune_days:
        # If total distinct days <= 2, trim oldest 20% posts safely
        posts_sorted = sorted(posts_list, key=lambda x: x.get("post_timestamp", 0), reverse=True)
        keep_cnt = max(20, int(len(posts_sorted) * 0.8))
        removed = len(posts_list) - keep_cnt
        return posts_sorted[:keep_cnt], removed

    oldest_days_to_delete = set(sorted_days[:prune_days])
    retained = []
    removed = 0
    for p in posts_list:
        ts = p.get("post_timestamp", 0)
        day_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts > 0 else ""
        if day_str in oldest_days_to_delete:
            removed += 1
        else:
            retained.append(p)

    print(
        f"🧹 [Storage Guard] Deleted {removed} posts from oldest {prune_days} day(s): {sorted(oldest_days_to_delete)}"
    )
    return retained, removed


# ==============================================================================
# LAYER 8: PARALLEL SCRAPING PIPELINE + OPTION B CLOUD BACKUP
# ==============================================================================
def detect_box_heading_for_anchor(a_tag):
    parent = a_tag.find_parent(["div", "td", "table", "section", "ul"])
    for _ in range(4):
        if not parent:
            break
        heading = parent.find(["h1", "h2", "h3", "h4", "th", "caption"])
        if heading:
            htxt = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip()
            if 3 <= len(htxt) <= 45:
                return htxt
        parent = parent.parent
    return ""


async def process_single_candidate(
    text, href, src_name, box_heading, used_quotes_set, counter_seed, loop, semaphore
):
    try:
        article_html = await safe_fetch_non_blocking(href, loop, semaphore, timeout=16.0)
        if not article_html:
            return None

        meta = IntentAndMetaClassifierAgent.analyze(text, box_heading, article_html[:600])
        dossier = deep_parse_article_dossier(article_html, href, text, meta["exam_field"])

        if not passes_strict_15_day_and_link_gate(dossier, text):
            return None

        return MasterSynthesizer.build_post(
            text, src_name, meta, dossier, used_quotes_set, counter_seed
        )
    except Exception:
        return None


async def process_aggregator(src, seen_titles, used_quotes_set, loop, semaphore):
    posts = []
    html = await safe_fetch_non_blocking(src["url"], loop, semaphore, timeout=18.0)
    if not html:
        return posts

    soup = BeautifulSoup(html, "html.parser")
    candidates = []

    for a in soup.find_all("a", href=True):
        text = scrub_external_branding(re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip())
        href = urljoin(src["url"], a["href"].strip())
        t_low = text.lower()

        if len(text) < 14 or len(text) > 145:
            continue
        if is_noise_or_menu_line(text):
            continue
        if not href.startswith("http") or any(b in href.lower() for b in BLOCK_DOMAINS):
            continue

        norm = re.sub(r"[^a-z0-9]+", " ", t_low).strip()[:35]
        if norm in seen_titles:
            continue

        if any(
            kw in t_low
            for kw in [
                "recruitment", "online form", "result", "admit card", "answer key",
                "vacancy", "bharti", "2026", "notification", "syllabus", "merit list",
                "cutoff", "hall ticket", "admission", "counselling", "extended",
                "apprentice", "officer", "clerk", "constable", "engineer", "teacher", "executive",
            ]
        ):
            seen_titles.add(norm)
            box_heading = detect_box_heading_for_anchor(a)
            candidates.append((text, href, src["name"], box_heading))

    tasks = [
        asyncio.wait_for(
            process_single_candidate(
                text, href, s_name, box_h, used_quotes_set, idx, loop, semaphore
            ),
            timeout=25.0,
        )
        for idx, (text, href, s_name, box_h) in enumerate(candidates[:50])
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, dict) and r:
            posts.append(r)

    print(f"   ✅ {src['name']}: Verified {len(posts)} clean posts")
    return posts


FALLBACK_RSS_FEEDS = [
    {
        "cat": "latest_jobs",
        "label": "Latest Jobs",
        "q": "https://news.google.com/rss/search?q=(SSC+OR+RRB+OR+IBPS+OR+SBI+OR+UPSC+OR+Police+OR+PSC+OR+AIIMS+OR+Shipyard+OR+Bank)+%22Recruitment%22+OR+%22Online+Form%22+OR+%22Vacancy%22+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
    },
    {
        "cat": "results",
        "label": "Result",
        "q": "https://news.google.com/rss/search?q=(SSC+OR+RRB+OR+IBPS+OR+SBI+OR+UPSC+OR+BPSC+OR+UPPSC+OR+MPSC+OR+India+Post)+%22Result%22+OR+%22Merit+List%22+OR+%22Scorecard%22+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
    },
    {
        "cat": "admit_cards",
        "label": "Admit Card",
        "q": "https://news.google.com/rss/search?q=(SSC+OR+RRB+OR+IBPS+OR+SBI+OR+UPSC+OR+Police+OR+CTET)+%22Admit+Card%22+OR+%22Hall+Ticket%22+OR+%22Call+Letter%22+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
    },
    {
        "cat": "answer_keys",
        "label": "Answer Key",
        "q": "https://news.google.com/rss/search?q=(SSC+OR+RRB+OR+IBPS+OR+CTET+OR+BPSC+OR+UPPSC)+%22Answer+Key%22+OR+%22Response+Sheet%22+when:14d&hl=en-IN&gl=IN&ceid=IN:en",
    },
    {
        "cat": "syllabus",
        "label": "Syllabus",
        "q": "https://news.google.com/rss/search?q=(SSC+OR+RRB+OR+IBPS+OR+UPSC+OR+MPSC+OR+RBI+OR+Police)+%22Syllabus%22+OR+%22Exam+Pattern%22+when:15d&hl=en-IN&gl=IN&ceid=IN:en",
    },
    {
        "cat": "admissions",
        "label": "Admission",
        "q": "https://news.google.com/rss/search?q=(NEET+OR+JEE+OR+CUET+OR+IGNOU+OR+B.Ed+OR+ITI+OR+Counselling)+%22Admission%22+OR+%22Registration%22+when:10d&hl=en-IN&gl=IN&ceid=IN:en",
    },
]


def fetch_option_b_cloud_backup(seen_titles, used_quotes_set):
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist_tz)
    backup_posts = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }

    for feed in FALLBACK_RSS_FEEDS:
        try:
            req = urllib.request.Request(feed["q"], headers=headers)
            with urllib.request.urlopen(req, timeout=14) as resp:
                xml_bytes = resp.read()
            root = ET.fromstring(xml_bytes)

            count_in_cat = 0
            for item in root.findall(".//item"):
                if count_in_cat >= 8:
                    break
                raw_title = (item.findtext("title") or "").strip()
                clean_title = scrub_external_branding(re.split(r"\s+-\s+", raw_title)[0].strip())
                if len(clean_title) < 15 or len(clean_title) > 140 or is_noise_or_menu_line(clean_title):
                    continue

                norm_key = re.sub(r"[^a-z0-9]+", " ", clean_title.lower()).strip()[:35]
                if norm_key in seen_titles:
                    continue
                seen_titles.add(norm_key)

                pub_str = (item.findtext("pubDate") or "").strip()
                try:
                    pub_dt = parsedate_to_datetime(pub_str).astimezone(ist_tz).replace(tzinfo=None)
                except Exception:
                    pub_dt = now_ist.replace(tzinfo=None)

                if (now_ist.replace(tzinfo=None) - pub_dt).days > 15:
                    continue

                rel_date_str = pub_dt.strftime("%d %b %Y")
                board_url = resolve_official_board_url(clean_title)
                meta = IntentAndMetaClassifierAgent.analyze(clean_title, feed["label"], clean_title)
                meta["category_key"] = feed["cat"]
                meta["category_label"] = feed["label"]

                dossier = {
                    "short_info": f"Official notification for {clean_title}. Check important dates, post-wise eligibility, exam pattern, syllabus and direct official links below.",
                    "department": clean_title.split()[0] + " Recruitment Board",
                    "dates": {
                        "release_date": rel_date_str,
                        "notification_date": rel_date_str,
                        "apply_start_date": rel_date_str,
                        "last_date": "",
                        "extended_date": "",
                        "fee_last_date": "",
                        "exam_date": "",
                        "admit_card_date": "",
                        "answer_key_date": "",
                        "result_date": "",
                        "real_post_date_obj": pub_dt,
                        "last_date_obj": None,
                    },
                    "fees": [],
                    "age_criteria": [],
                    "eligibility_list": [],
                    "total_vacancy": "",
                    "vacancy_number": 0,
                    "post_qual_rows": [],
                    "category_vacancy_rows": [],
                    "selection_process": [],
                    "exam_pattern_rows": [],
                    "exam_pattern_notes": [],
                    "syllabus_by_subject": {},
                    "links": {
                        "apply_link": board_url if feed["cat"] in ["latest_jobs", "admissions"] else "",
                        "notif_pdf": board_url,
                        "admit_card_link": board_url if feed["cat"] == "admit_cards" else "",
                        "answer_key_link": board_url if feed["cat"] == "answer_keys" else "",
                        "result_link": board_url if feed["cat"] == "results" else "",
                        "syllabus_link": board_url if feed["cat"] == "syllabus" else "",
                        "official_site": board_url,
                    },
                    "all_extracted_links": [
                        {"label": f"Official {feed['label']} Direct Portal", "url": board_url},
                        {"label": "Official Recruitment Board Website", "url": board_url},
                    ],
                }

                vac_m = re.search(r"\b([0-9,]{2,7})\s+(?:Posts?|Vacanc(?:y|ies))\b", clean_title, re.IGNORECASE)
                if vac_m:
                    raw_n = vac_m.group(1).replace(",", "")
                    if raw_n.isdigit():
                        dossier["vacancy_number"] = int(raw_n)
                    dossier["total_vacancy"] = f"{vac_m.group(1)} Posts"

                synthesized = MasterSynthesizer.build_post(
                    clean_title,
                    "SarkariResultMain",
                    meta,
                    dossier,
                    used_quotes_set,
                    len(backup_posts) + 1,
                )
                if synthesized:
                    backup_posts.append(synthesized)
                    count_in_cat += 1
        except Exception:
            pass

    return backup_posts


async def main_async():
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist_tz)
    now_ist_str = now_ist.strftime("%Y-%m-%d %I:%M:%S %p IST")
    cutoff_15_ts = int((now_ist.replace(tzinfo=None) - timedelta(days=15)).timestamp())

    existing = []
    if os.path.exists(DATABASE_FILE):
        try:
            with open(DATABASE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    existing = data
        except Exception:
            existing = []

    posts_by_signature = {}
    used_quotes_set = set()
    seen_titles = set()

    for j in existing:
        if not isinstance(j, dict):
            continue
        if j.get("source") not in ALLOWED_SOURCE_NAMES:
            continue
        p_ts = j.get("post_timestamp", 0)
        if not p_ts:
            dt = parse_any_date_string(j.get("releaseDate") or j.get("post_date") or "")
            p_ts = int(dt.timestamp()) if dt else 0
            j["post_timestamp"] = p_ts

        if p_ts < cutoff_15_ts:
            continue

        prim_link = j.get("link") or j.get("applyUrl") or ""
        if not is_direct_post_target_url(prim_link, allow_direct_pdf_on_cdn=True):
            continue

        # Clean any legacy repeated fake rows from existing database records
        if "vacancy_rows" in j and isinstance(j["vacancy_rows"], list):
            j["vacancy_rows"] = [
                r for r in j["vacancy_rows"]
                if isinstance(r, list) and len(r) >= 2 and str(r[0]).lower().strip(" :.-📌") not in METADATA_ROW_LABELS
            ]

        sig = j.get("intent_signature") or j.get("id", "")
        j["status"] = "published"
        posts_by_signature[sig] = j
        if q := j.get("unique_quote"):
            used_quotes_set.add(q.lower())
        if t := j.get("title"):
            seen_titles.add(re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()[:35])

    loop = asyncio.get_running_loop()
    semaphore = asyncio.Semaphore(25)

    # Option A: Direct Scrape from the 2 Websites & Their Mirrors
    agg_tasks = [
        process_aggregator(src, seen_titles, used_quotes_set, loop, semaphore)
        for src in SOURCES
    ]
    agg_results = await asyncio.gather(*agg_tasks, return_exceptions=True)

    new_added = 0
    repost_updated = 0

    for res in agg_results:
        if isinstance(res, list):
            for post in res:
                sig = post["intent_signature"]
                if sig not in posts_by_signature:
                    posts_by_signature[sig] = post
                    new_added += 1
                else:
                    old_p = posts_by_signature[sig]
                    post["adminSeen"] = old_p.get("adminSeen", False)
                    posts_by_signature[sig] = post
                    repost_updated += 1

    # Option B: Cloud Self-Healing Backup
    backup_items = fetch_option_b_cloud_backup(seen_titles, used_quotes_set)
    for b_post in backup_items:
        sig = b_post["intent_signature"]
        if sig not in posts_by_signature:
            posts_by_signature[sig] = b_post
            new_added += 1

    all_valid_posts = list(posts_by_signature.values())

    # Apply Option A + Option B Storage Pruner (Auto-delete Oldest 2 Days if needed)
    all_valid_posts, pruned_count = prune_oldest_two_days_storage(
        all_valid_posts, force_prune=FORCE_PURGE_FLAG, prune_days=DEFAULT_PRUNE_DAYS
    )

    for p in all_valid_posts:
        p["isTrendingTop6"] = False
        p["status"] = "published"
        p["lastCheckedIst"] = now_ist_str

    top_6_trending = sorted(
        all_valid_posts,
        key=lambda x: (x.get("rushScore", 0), x.get("post_timestamp", 0)),
        reverse=True,
    )[:6]

    trending_cards_payload = []
    for tp in top_6_trending:
        tp["isTrendingTop6"] = True
        trending_cards_payload.append({
            "id": tp["id"],
            "title": tp["title"],
            "sub": tp.get("rightEndTag") or tp.get("category_label", "Apply Online"),
            "url": tp.get("link", ""),
            "details": tp.get("overview", ""),
            "rushScore": tp.get("rushScore", 0),
            "active": True,
        })

    sorted_final_db = []
    category_counts = {}
    unseen_auto_count = 0

    for cat_key in SIX_CATEGORIES_ORDER:
        cat_posts = [p for p in all_valid_posts if p.get("category") == cat_key]
        cat_posts.sort(
            key=lambda x: (x.get("post_timestamp", 0), x.get("rushScore", 0)),
            reverse=True,
        )
        category_counts[cat_key] = len(cat_posts)
        sorted_final_db.extend(cat_posts)

    for p in sorted_final_db:
        if p.get("isAutoPublished", True) and not p.get("adminSeen", False):
            unseen_auto_count += 1

    with open(DATABASE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted_final_db, f, ensure_ascii=False, indent=2)

    # Preserve existing social_links in admin_boxes.json if admin already saved them
    saved_social_links = {"whatsapp": "", "telegram": "", "instagram": "", "facebook": ""}
    if os.path.exists(ADMIN_BOXES_FILE):
        try:
            with open(ADMIN_BOXES_FILE, "r", encoding="utf-8") as old_bf:
                old_box_data = json.load(old_bf)
                if isinstance(old_box_data.get("social_links"), dict):
                    saved_social_links.update(old_box_data["social_links"])
        except Exception:
            pass

    boxes_payload = {
        "project_repo": PROJECT_REPO_NAME,
        "updated_at": now_ist_str,
        "window_days": 15,
        "pruned_posts_last_run": pruned_count,
        "unseen_auto_published_count": unseen_auto_count,
        "category_counts": category_counts,
        "trending_top_6": trending_cards_payload,
        "standard_boxes": list(CATEGORY_LABELS.values()),
        "social_links": saved_social_links,
        "new_custom_boxes": [],
    }
    with open(ADMIN_BOXES_FILE, "w", encoding="utf-8") as bf:
        json.dump(boxes_payload, bf, ensure_ascii=False, indent=2)

    print(
        f"🎉 [{PROJECT_REPO_NAME}] Sync Complete at {now_ist_str}! "
        f"Added: {new_added} | Updated: {repost_updated} | Pruned Old: {pruned_count} "
        f"| Total Live Posts: {len(sorted_final_db)}"
    )


def main():
    try:
        asyncio.run(asyncio.wait_for(main_async(), timeout=220.0))
    except asyncio.TimeoutError:
        print("⚠️ Reached max timeout window. Verified posts saved cleanly.")


if __name__ == "__main__":
    main()
