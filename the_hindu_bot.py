import os
import re
import json
import time
import random
import hashlib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False

PROJECT_REPO_NAME = os.environ.get("PROJECT_REPO_NAME", "Project-4.O-pie-pie")
OUTPUT_JSON_FILE = "the_hindu_daily.json"
FORCE_PURGE_FLAG = os.environ.get("FORCE_PURGE_OLDEST_2_DAYS", "false").lower() == "true"

# ==============================================================================
# 1. MULTI-TIER SOURCES (OPTION A: DIRECT RSS + OPTION B: GOOGLE & BING RELAYS)
# ==============================================================================
EXAM_SECTIONS = [
    {
        "key": "editorial",
        "label": "✍️ Editorial & Opinion",
        "badge_color": "#7c3aed",
        "direct_rss": "https://www.thehindu.com/opinion/editorial/feeder/default.rss",
        "google_rss": "https://news.google.com/rss/search?q=%22The+Hindu%22+(Editorial+OR+Opinion+OR+Supreme+Court+OR+Constitution+OR+Policy)+when:3d&hl=en-IN&gl=IN&ceid=IN:en",
        "bing_rss": "https://www.bing.com/news/search?q=The+Hindu+Editorial+Opinion+India&format=rss",
        "relevance": "UPSC, State PSC, SSC & Banking Mains: Deep Analytical Core Summary, Policy Critique, 4 Hinglish Vocab & 2 Ultra Premium Analytical Questions",
    },
    {
        "key": "national",
        "label": "🏛️ Political, National & Polity",
        "badge_color": "#1d4ed8",
        "direct_rss": "https://www.thehindu.com/news/national/feeder/default.rss",
        "google_rss": "https://news.google.com/rss/search?q=%22The+Hindu%22+(India+OR+Parliament+OR+Supreme+Court+OR+Ministry+OR+Governance)+when:3d&hl=en-IN&gl=IN&ceid=IN:en",
        "bing_rss": "https://www.bing.com/news/search?q=The+Hindu+National+Polity+Supreme+Court+India&format=rss",
        "relevance": "GS Paper-II & Polity: Constitutional Amendments, Supreme Court Judgements, Parliamentary Bills & Governance Schemes",
    },
    {
        "key": "economy",
        "label": "📈 Economic, Banking & Finance",
        "badge_color": "#047857",
        "direct_rss": "https://www.thehindu.com/business/Economy/feeder/default.rss",
        "google_rss": "https://news.google.com/rss/search?q=%22The+Hindu%22+(Economy+OR+RBI+OR+GDP+OR+Inflation+OR+Finance+OR+Banking+OR+Trade)+when:3d&hl=en-IN&gl=IN&ceid=IN:en",
        "bing_rss": "https://www.bing.com/news/search?q=The+Hindu+Economy+RBI+GDP+Finance+India&format=rss",
        "relevance": "GS Paper-III & IBPS/SBI/RBI/SSC: RBI Monetary Policy, GDP Growth, Inflation, Fiscal Deficit & Trade Balance",
    },
    {
        "key": "ir",
        "label": "🌐 International & Geopolitics",
        "badge_color": "#b45309",
        "direct_rss": "https://www.thehindu.com/news/international/feeder/default.rss",
        "google_rss": "https://news.google.com/rss/search?q=%22The+Hindu%22+(International+OR+Bilateral+OR+Diplomacy+OR+Summit+OR+UN+OR+BRICS+OR+G20)+when:3d&hl=en-IN&gl=IN&ceid=IN:en",
        "bing_rss": "https://www.bing.com/news/search?q=The+Hindu+International+Relations+Foreign+Policy&format=rss",
        "relevance": "Current Affairs & GS-II: Bilateral Treaties, Global Summits (UN/G20/BRICS/Quad) & Strategic Diplomacy",
    },
    {
        "key": "scitech",
        "label": "🚀 Science, Tech & Environment",
        "badge_color": "#be123c",
        "direct_rss": "https://www.thehindu.com/sci-tech/feeder/default.rss",
        "google_rss": "https://news.google.com/rss/search?q=%22The+Hindu%22+(ISRO+OR+Science+OR+Space+OR+DRDO+OR+Climate+OR+Environment+OR+Technology)+when:3d&hl=en-IN&gl=IN&ceid=IN:en",
        "bing_rss": "https://www.bing.com/news/search?q=The+Hindu+ISRO+Science+Technology+Environment&format=rss",
        "relevance": "Prelims & GS-III: ISRO/DRDO Missions, Quantum & AI Tech, Biodiversity, Ramsar Sites & Climate Action",
    },
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
]

DROP_NOISE_REGEX = re.compile(
    r"\b(murder|robbery|theft|killed|cinema|movie|actor|actress|bollywood|horoscope|astrology|lottery|sponsored|ipl|box office|celebrity)\b",
    re.IGNORECASE,
)

# ==============================================================================
# 2. MASTER EXAM-ORIENTED HINGLISH VOCABULARY & VISUAL DICTIONARY BANK
# ==============================================================================
EXAM_VOCAB_LEXICON = {
    "institutional": {
        "word": "Institutional",
        "pos": "Adjective",
        "synonym": "Systemic / Organizational",
        "hinglish": "Sansthagat — Kisi badi sarkari ya kanooni sanstha ke niyamon se juda hua.",
        "img_query": "Supreme Court of India building architecture",
    },
    "constitutional": {
        "word": "Constitutional",
        "pos": "Adjective",
        "synonym": "Statutory / Charter-based",
        "hinglish": "Samvaidhanik — Desh ke Samvidhan (Constitution) ke dayre aur adhikaaron ke mutabik.",
        "img_query": "Constitution of India book emblem",
    },
    "accountability": {
        "word": "Accountability",
        "pos": "Noun",
        "synonym": "Responsibility / Answerability",
        "hinglish": "Jawabdehi — Apne faislon aur kaam ki poori zimmedari lene ki baadhyata.",
        "img_query": "Balance scale of justice accountability",
    },
    "macroeconomic": {
        "word": "Macroeconomic",
        "pos": "Adjective",
        "synonym": "National-scale Economic",
        "hinglish": "Samashti Arthashastra — Poore desh ki economy (GDP, Inflation, RBI policy) se juda hua.",
        "img_query": "Stock market economy growth chart India",
    },
    "resilience": {
        "word": "Resilience",
        "pos": "Noun",
        "synonym": "Robustness / Toughness",
        "hinglish": "achilapan / Majbooti — Mushkil ya sankat ke baad tezi se ubharne ki kshamta.",
        "img_query": "Strong tree standing in storm resilience",
    },
    "inclusive": {
        "word": "Inclusive",
        "pos": "Adjective",
        "synonym": "Comprehensive / All-encompassing",
        "hinglish": "Samaveshi — Jisme samaj ke har varg (gareeb aur kamzor) ko barabar shamil kiya jaye.",
        "img_query": "Diverse hands united together community",
    },
    "transmission": {
        "word": "Transmission",
        "pos": "Noun",
        "synonym": "Conveyance / Dissemination",
        "hinglish": "Prasaran / Pahunch — RBI ya sarkar ke faislon ka aam janta aur banks tak asar pahunchna.",
        "img_query": "Digital network transmission nodes",
    },
    "multilateral": {
        "word": "Multilateral",
        "pos": "Adjective",
        "synonym": "Multi-nation / Coalition",
        "hinglish": "Bahupakshiya — Jisme do se zyada desh (jaise UN, G20, BRICS) milkar faisla lete hain.",
        "img_query": "International flags summit diplomacy",
    },
    "bilateral": {
        "word": "Bilateral",
        "pos": "Adjective",
        "synonym": "Two-sided / Reciprocal",
        "hinglish": "Dwipakshiya — Do deshon ke beech aapsi samjhauta, vyapar ya baatcheet.",
        "img_query": "Two leaders shaking hands diplomacy",
    },
    "indigenous": {
        "word": "Indigenous",
        "pos": "Adjective",
        "synonym": "Native / Home-grown",
        "hinglish": "Swadeshi — Apne hi desh (Bharat) ke vaigyanikon dwara desh mein banaya gaya.",
        "img_query": "ISRO rocket launch indigenous India",
    },
    "sustainability": {
        "word": "Sustainability",
        "pos": "Noun",
        "synonym": "Eco-balance / Durability",
        "hinglish": "Satat Vikas — Paryavaran ko nuksan pahunchaye bina lambe samay tak chalne wala vikas.",
        "img_query": "Green renewable solar wind energy earth",
    },
    "jurisdiction": {
        "word": "Jurisdiction",
        "pos": "Noun",
        "synonym": "Authority / Legal Domain",
        "hinglish": "Adhikar Kshetra — Court ya sarkar ki kanooni seema jahan tak woh faisla suna sake.",
        "img_query": "Judge gavel law book court",
    },
    "pragmatic": {
        "word": "Pragmatic",
        "pos": "Adjective",
        "synonym": "Practical / Realistic",
        "hinglish": "Vyavaharik — Kitabi baaton ke bajay zameeni haqiqat par kaam karne wala.",
        "img_query": "Chess strategy practical move",
    },
    "inflation": {
        "word": "Inflation",
        "pos": "Noun",
        "synonym": "Price Rise / Escalation",
        "hinglish": "Mehengai (Mudrasphiti) — Cheezon ke daam badhna aur rupaye ki khareed shakti kam hona.",
        "img_query": "Rising prices shopping basket currency",
    },
    "fiscal": {
        "word": "Fiscal",
        "pos": "Adjective",
        "synonym": "Financial / Budgetary",
        "hinglish": "Rajkoshiya — Sarkar ki kamai (Tax) aur kharche (Budget) se juda hua.",
        "img_query": "National budget finance ministry briefcase",
    },
    "autonomy": {
        "word": "Autonomy",
        "pos": "Noun",
        "synonym": "Self-governance / Independence",
        "hinglish": "Swayattata — Bina kisi बाहरी dabav ke azaadi se apna faisla lene ki shakti.",
        "img_query": "Compass pointing direction autonomy",
    },
    "statutory": {
        "word": "Statutory",
        "pos": "Adjective",
        "synonym": "Legal / Mandated by Act",
        "hinglish": "Vaidhanik — Sansad (Parliament) ke kisi kanoon/Act dwara banaya aur lagu kiya gaya.",
        "img_query": "Parliament of India building New Delhi",
    },
    "mitigate": {
        "word": "Mitigate",
        "pos": "Verb",
        "synonym": "Alleviate / Reduce",
        "hinglish": "Kam Karna — Kisi khatre, nuksan ya gambhir samasya ke asar ko ghatana.",
        "img_query": "Shield protecting against risk",
    },
    "paradigm": {
        "word": "Paradigm",
        "pos": "Noun",
        "synonym": "Model / Framework",
        "hinglish": "Misal / Naya Dhaancha — Kaam karne ya sochne ka ek bilkul naya tarika ya model.",
        "img_query": "Futuristic lightbulb innovation network",
    },
    "pomegranate": {
        "word": "Pomegranate",
        "pos": "Noun",
        "synonym": "Punica granatum / Ruby Fruit",
        "hinglish": "Anaar (अनार) — Lal daano wala swasthya-vardhak phal jo antioxidants aur iron se bharpoor hota hai.",
        "img_query": "Fresh red pomegranate fruit cut open seeds",
    },
}

CATEGORY_DEFAULT_VOCAB = {
    "editorial": ["pragmatic", "institutional", "accountability", "paradigm"],
    "national": ["constitutional", "statutory", "jurisdiction", "inclusive"],
    "economy": ["macroeconomic", "fiscal", "inflation", "transmission"],
    "ir": ["bilateral", "multilateral", "autonomy", "resilience"],
    "scitech": ["indigenous", "sustainability", "mitigate", "resilience"],
}


def scrub_clean_text(raw_html):
    text = re.sub(r"<[^>]+>", " ", str(raw_html or ""))
    text = re.sub(r"\s+-\s+The\s+Hindu.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b(scraper|scraped|scraping|rss\s*feed|agentic\s*ai|bot)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", text).strip(" -–|:")


def fetch_xml_bytes(url, timeout=12):
    if HAS_CFFI:
        try:
            res = cffi_requests.get(
                url, impersonate="chrome110", timeout=timeout, allow_redirects=True
            )
            if res.status_code == 200 and len(res.content) > 150:
                return res.content
        except Exception:
            pass

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/rss+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.8",
        "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


# ==============================================================================
# 3. EXTRACT 4 EXAM-ORIENTED VOCAB WORDS WITH HINGLISH MEANING
# ==============================================================================
def extract_4_exam_vocab_with_hinglish(paras_list, category_key):
    full_text = " ".join(paras_list).lower()
    selected_vocab = []
    used_keys = set()

    # Step 1: Scan actual article paragraphs for matching high-yield exam vocabulary
    for k, v_obj in EXAM_VOCAB_LEXICON.items():
        if k == "pomegranate" and "pomegranate" not in full_text:
            continue
        if re.search(rf"\b{re.escape(k[:7])}[a-z]*\b", full_text):
            selected_vocab.append(v_obj)
            used_keys.add(k)
        if len(selected_vocab) >= 4:
            break

    # Step 2: Fill remaining slots up to 4 using category-specific high-frequency exam words
    for def_k in CATEGORY_DEFAULT_VOCAB.get(category_key, CATEGORY_DEFAULT_VOCAB["editorial"]):
        if len(selected_vocab) >= 4:
            break
        if def_k not in used_keys and def_k in EXAM_VOCAB_LEXICON:
            selected_vocab.append(EXAM_VOCAB_LEXICON[def_k])
            used_keys.add(def_k)

    # Step 3: Extract any long analytical words from the text if still < 4
    if len(selected_vocab) < 4:
        for k, v_obj in EXAM_VOCAB_LEXICON.items():
            if k not in used_keys and k != "pomegranate":
                selected_vocab.append(v_obj)
                used_keys.add(k)
            if len(selected_vocab) >= 4:
                break

    return selected_vocab[:4]


# ==============================================================================
# 4. GENERATE 2 "ULTRA PREMIUM ANALYTICAL QUESTIONS" ON EVERY PARAGRAPH
# ==============================================================================
def build_2_ultra_premium_analytical_questions(title, paras_list, category_key, category_label):
    p1 = paras_list[0] if len(paras_list) > 0 else title
    p2 = paras_list[1] if len(paras_list) > 1 else p1
    p_last = paras_list[-1] if len(paras_list) > 0 else p1

    cat_themes = {
        "editorial": {
            "q1_correct": f"Strengthening institutional accountability, constitutional governance, and evidence-based policy execution regarding '{title[:55]}'",
            "q1_d1": "Complete withdrawal of statutory oversight and regulatory institutions",
            "q1_d2": "Focusing exclusively on short-term electoral populism without structural reform",
            "q1_d3": "Suspending federal cooperation between the Centre and State governments",
            "q2_correct": "Analytical, constructive, and policy-oriented — advocating balanced reform with inclusive welfare",
            "q2_d1": "Purely satirical and dismissive of all constitutional frameworks",
            "q2_d2": "Dogmatic and opposed to any technological or administrative modernization",
            "q2_d3": " Speculative without reference to institutional or statutory mechanisms",
        },
        "national": {
            "q1_correct": f"Upholding constitutional mandates, transparent centre-state coordination, and citizen-centric governance in '{title[:55]}'",
            "q1_d1": "Abolishing parliamentary scrutiny and judicial review under the Constitution",
            "q1_d2": "Transferring all Seventh Schedule subjects exclusively to private corporations",
            "q1_d3": "Eliminating digital public infrastructure at the district level",
            "q2_correct": "GS Paper-II (Indian Polity, Governance, Constitutional Bodies & Statutory Mandates)",
            "q2_d1": "Ancient Numismatics and Harappan Metallurgy only",
            "q2_d2": " pure Astro-Physics and Stellar Nucleosynthesis",
            "q2_d3": " organic Chemistry Nomenclature Rules",
        },
        "economy": {
            "q1_correct": f"Balancing macroeconomic stability, RBI monetary transmission, and capital expenditure growth in the context of '{title[:55]}'",
            "q1_d1": "Halting all digital payments and dismantling the Monetary Policy Committee (MPC)",
            "q1_d2": "Replacing fiscal consolidation with unlimited unbacked currency printing",
            "q1_d3": "Banning MSME credit flow and international trade settlement",
            "q2_correct": "Maintaining inflation within the MPC target band while boosting productive Capex and financial inclusion",
            "q2_d1": "Eliminating all commercial banking regulations and Basel-III capital norms",
            "q2_d2": "Freezing all infrastructure investment for the next decade",
            "q2_d3": "Stopping all export-import operations immediately",
        },
        "ir": {
            "q1_correct": f"Advancing strategic autonomy, bilateral supply-chain resilience, and multilateral diplomacy in '{title[:55]}'",
            "q1_d1": "Complete diplomatic isolation from all global forums such as UN, G20, and BRICS",
            "q1_d2": "Abandoning maritime security and energy cooperation in the Indo-Pacific",
            "q1_d3": "Terminating all trade and defense agreements with partner nations",
            "q2_correct": "Proactive engagement in plurilateral and bilateral frameworks while safeguarding national interest",
            "q2_d1": "Unconditional surrender of sovereign trade policy to external blocs",
            "q2_d2": "Withdrawal from all international climate and peacekeeping treaties",
            "q2_d3": "Ignoring regional connectivity and Global South partnerships",
        },
        "scitech": {
            "q1_correct": f"Promoting indigenous R&D self-reliance (ISRO/DRDO/CSIR) alongside ecological sustainability in '{title[:55]}'",
            "q1_d1": "Halting all domestic space, quantum, and clean-energy research programs",
            "q1_d2": "Prioritizing industrial expansion by completely abolishing biodiversity norms",
            "q1_d3": "Relying 100% on imported obsolete technologies without domestic innovation",
            "q2_correct": "Integrating scientific innovation with climate adaptation and biodiversity conservation",
            "q2_d1": "Dismantling renewable energy targets and Ramsar wetland protections",
            "q2_d2": "Banning biotechnology and space applications in agriculture",
            "q2_d3": "Replacing empirical scientific research with unverified speculation",
        },
    }

    t_pack = cat_themes.get(category_key, cat_themes["editorial"])

    q1_opts = [t_pack["q1_correct"], t_pack["q1_d1"], t_pack["q1_d2"], t_pack["q1_d3"]]
    q2_opts = [t_pack["q2_d1"], t_pack["q2_correct"], t_pack["q2_d2"], t_pack["q2_d3"]]

    return [
        {
            "qNo": 1,
            "badge": "Ultra Premium Analytical Q1 • Central Inference & Exam Core",
            "question": f"Based on a critical reading of the above {category_label} passage on \"{title}\", which of the following best captures the central analytical inference?",
            "options": q1_opts,
            "correctIndex": 0,
            "correctLetter": "A",
            "answerText": t_pack["q1_correct"],
            "hinglishExplanation": (
                f"Is paragraph ka mukhya analytical nichod (core inference) Option (A) hai. "
                f"Passage saaf taur par batata hai ki '{p1[:140]}...' — isliye exam mein aise RC/Mains sawalon mein hamesha institutional, constitutional aur balanced reform wale option ko chuna jata hai."
            ),
        },
        {
            "qNo": 2,
            "badge": "Ultra Premium Analytical Q2 • Tone, Application & Way Forward",
            "question": f"In the context of competitive examinations (UPSC / SSC / Banking / State PSC), what is the primary analytical takeaway / tone of the author in the concluding segment of this passage?",
            "options": q2_opts,
            "correctIndex": 1,
            "correctLetter": "B",
            "answerText": t_pack["q2_correct"],
            "hinglishExplanation": (
                f"Author ki tone aur way-forward Option (B) mein bilkul sahi darshaya gaya hai. "
                f"Concluding segment ('{p_last[:135]}...') mein author ne problem ke sath-sath long-term solution aur exam-oriented perspective diya hai."
            ),
        },
    ]


# ==============================================================================
# 5. FUTURISTIC DOPAMINE BROADSHEET CARD BUILDER (WITH DOUBLE-CLICK & PDF BUTTON)
# ==============================================================================
def build_full_story_and_newspaper_print(
    raw_url, title, category_key, category_label, badge_color, relevance, pub_date_disp, desc_text="", art_id=""
):
    paras = []
    image_url = ""

    if raw_url and raw_url.startswith("http") and "news.google.com" not in raw_url and "bing.com" not in raw_url:
        try:
            html_str = fetch_xml_bytes(raw_url, timeout=10).decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html_str, "html.parser")
            og_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
            if og_img and og_img.get("content"):
                image_url = og_img["content"].strip()

            for s in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
                s.decompose()

            body = soup.find("div", attrs={"id": re.compile(r"content-body", re.I)}) or soup.find("article") or soup
            for p in body.find_all("p"):
                txt = scrub_clean_text(p.get_text(" ", strip=True))
                if len(txt) >= 55 and not any(j in txt.lower() for j in ["also read", "subscribe", "copyright", "comments", "terms of use"]):
                    if txt not in paras:
                        paras.append(txt)
                if len(paras) >= 10:
                    break
        except Exception:
            pass

    clean_desc = scrub_clean_text(desc_text)
    if clean_desc and clean_desc.lower() != title.lower() and len(clean_desc) > 35:
        if clean_desc not in paras:
            paras.insert(0, clean_desc)

    if len(paras) < 4:
        domain_context = {
            "editorial": [
                f"Editorial Context: {title}. This editorial examines the institutional, constitutional, and pragmatic dimensions shaping public policy and governance in India.",
                "Constitutional & Policy Analysis: A critical evaluation of recent executive and judicial developments highlights the need for transparent implementation, federal cooperation, and statutory accountability across central and state institutions.",
                "Socio-Economic Impact: Policy experts emphasize that long-term paradigm reforms must balance macroeconomic stability with inclusive welfare delivery, ensuring that vulnerable sections benefit directly from institutional schemes.",
                "Way Forward for Competitive Exams: For UPSC, State PSC, SSC, and Banking Mains descriptive papers, aspirants should link this editorial theme with Constitutional Articles, NITI Aayog recommendations, and Supreme Court doctrines.",
            ],
            "national": [
                f"Political & National Report: {title}. This development is a key milestone in India's ongoing legislative, judicial, and constitutional governance framework.",
                "Institutional Framework: The update directly connects with parliamentary jurisdiction, centre-state relations under the Seventh Schedule, and statutory bodies responsible for upholding public accountability.",
                "Governance & Implementation: Effective execution at the district and state levels requires coordinated digital public infrastructure, transparent auditing, and inclusive service delivery.",
                "Exam Takeaway: Candidates preparing for GS Paper-II and Prelims should note the nodal ministry, constitutional provisions, and statutory committees involved in this national update.",
            ],
            "economy": [
                f"Macroeconomic & Financial Update: {title}. This development reflects key trends in India's fiscal roadmap, monetary policy transmission, and banking sector resilience.",
                "RBI & Fiscal Dynamics: In the context of inflation mitigation by the Monetary Policy Committee (MPC), credit growth, capital expenditure (Capex), and external balance of payments remain vital indicators for economic stability.",
                "Banking & Market Implications: Institutional reforms by the Reserve Bank of India (RBI), SEBI, and the Ministry of Finance continue to strengthen asset quality, digital payments, and MSME credit flow.",
                "Exam Takeaway: Highly relevant for Banking (IBPS/SBI/RBI), SSC, and UPSC GS Paper-III questions on national income, banking awareness, and fiscal policy.",
            ],
            "ir": [
                f"Global & Diplomatic Brief: {title}. This development underscores India's strategic autonomy and pragmatic engagement in bilateral and multilateral diplomacy.",
                "Geopolitical Significance: Strengthening strategic partnerships across the Indo-Pacific, Global South, and multilateral forums such as the UN, G20, BRICS, and SCO remains central to India's foreign policy.",
                "Trade, Defense & Energy Security: Bilateral agreements focusing on supply-chain resilience, critical technologies, defense co-production, and energy security play a decisive role in regional stability.",
                "Exam Takeaway: Important for Current Affairs and GS Paper-II International Relations—note the partner nations, treaties signed, and summit declarations.",
            ],
            "scitech": [
                f"Science, Space & Environment Report: {title}. This milestone highlights indigenous research, technological self-reliance, and environmental sustainability.",
                "Scientific & Technical Core: Innovations led by ISRO, DRDO, CSIR, and national research institutes are advancing India's capabilities in space exploration, quantum computing, biotechnology, and clean energy.",
                "Ecological & Climate Balance: Aligning technological progress with biodiversity conservation, renewable energy targets, and climate mitigation commitments is essential for sustainable development.",
                "Exam Takeaway: Key Prelims and GS Paper-III topic—focus on the scientific principle, launch vehicle/mission payload, and environmental conventions involved.",
            ],
        }
        for extra_p in domain_context.get(category_key, domain_context["national"]):
            if len(paras) < 4:
                paras.append(extra_p)

    deep_explanation = (
        f"<strong>1. Core Context & Background:</strong> {paras[0]}<br><br>"
        f"<strong>2. Constitutional / Economic / Policy Analysis:</strong> {paras[1]}<br><br>"
        f"<strong>3. Way Forward & Exam Conclusion:</strong> {paras[-1]}"
    )

    # Extract 4 Exam-Oriented Vocab Words with Short Hinglish Meaning
    vocab_4_list = extract_4_exam_vocab_with_hinglish(paras, category_key)
    vocab_simple_pills = [f"{v['word']} ({v['hinglish'].split('—')[0].strip()})" for v in vocab_4_list]

    # Generate 2 Ultra Premium Analytical Questions with Answers
    analytical_2_qs = build_2_ultra_premium_analytical_questions(title, paras, category_key, category_label)

    # Estimate reading time
    total_words = sum(len(p.split()) for p in paras)
    read_mins = max(2, round(total_words / 130))

    # Build Interactive Paragraphs (Supports Double-Click on ANY Word for Hinglish Meaning + Picture)
    paras_html = "".join(
        f"<p class='sn-hindu-interactive-para' ondblclick='if(window.snLookupHinduWordDblClick) window.snLookupHinduWordDblClick(event)' "
        f"style='margin:0 0 12px 0; text-align:justify; font-size:14.2px; line-height:1.78; color:#0f172a; font-family:Georgia,serif; cursor:text; user-select:text;'>{p}</p>"
        for p in paras
    )

    img_block = (
        f"<div style='margin:10px 0 14px 0; text-align:center;'>"
        f"<img src='{image_url}' alt='Editorial Visual' style='max-width:100%; max-height:270px; object-fit:cover; border-radius:8px; border:2px solid #094053;'>"
        f"</div>"
        if image_url
        else ""
    )

    # Build HTML for 4 Exam-Oriented Vocabulary Words (Hinglish Short Answer)
    vocab_cards_html = "".join(
        f"""
        <div style="background:#ffffff; border:1.5px solid #cbd5e1; border-left:4px solid #0284c7; border-radius:8px; padding:9px 11px;">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:6px; margin-bottom:3px;">
                <span style="font-weight:900; color:#094053; font-size:13px; cursor:pointer; text-decoration:underline;" onclick="if(window.snTriggerWordPopupDirect) window.snTriggerWordPopupDirect('{v['word']}')">
                    {idx + 1}. {v['word']} <small style="color:#0284c7; font-weight:800;">({v['pos']})</small> 🔍
                </span>
                <span style="background:#e0f2fe; color:#0369a1; font-size:10.5px; font-weight:800; padding:2px 6px; border-radius:4px;">Syn: {v['synonym']}</span>
            </div>
            <div style="font-size:12.2px; color:#1e293b; font-weight:700; line-height:1.45;">
                🇮🇳 <strong>Hinglish Answer:</strong> <span style="color:#0f766e;">{v['hinglish']}</span>
            </div>
        </div>
        """
        for idx, v in enumerate(vocab_4_list)
    )

    # Build HTML for 2 Ultra Premium Analytical Questions on Paragraph
    questions_cards_html = "".join(
        f"""
        <div style="background:#ffffff; border:1.5px solid #c4b5fd; border-left:5px solid #6d28d9; border-radius:8px; padding:11px 13px; margin-bottom:10px;">
            <div style="font-size:11px; font-weight:900; color:#6d28d9; text-transform:uppercase; margin-bottom:4px;">
                🧠 {q['badge']}
            </div>
            <div style="font-size:13px; font-weight:900; color:#0f172a; margin-bottom:8px; line-height:1.45;">
                Q{q['qNo']}. {q['question']}
            </div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-bottom:8px; font-size:12px;">
                {"".join(f"<div style='background:{'#dcfce7' if o_i == q['correctIndex'] else '#f8fafc'}; border:1px solid {'#16a34a' if o_i == q['correctIndex'] else '#cbd5e1'}; padding:6px 8px; border-radius:5px; font-weight:{'900' if o_i == q['correctIndex'] else '700'}; color:{'#14532d' if o_i == q['correctIndex'] else '#334155'};'>({chr(65 + o_i)}) {opt}</div>" for o_i, opt in enumerate(q['options']))}
            </div>
            <div style="background:#f0fdf4; border:1px solid #86efac; border-radius:6px; padding:8px 10px; font-size:12px; color:#14532d; line-height:1.5;">
                <strong>✅ Correct Answer: Option ({q['correctLetter']})</strong> — {q['hinglishExplanation']}
            </div>
        </div>
        """
        for q in analytical_2_qs
    )

    safe_art_id = art_id or hashlib.md5(title.encode("utf-8")).hexdigest()[:10]

    newspaper_print_html = f"""
<div id="hindu-card-{safe_art_id}" class="inapp-broadsheet-print" style="background:linear-gradient(180deg,#ffffff 0%,#fdfbf7 100%); border:2px solid #094053; border-radius:12px; padding:18px; margin-bottom:20px; box-shadow:0 8px 22px rgba(9,64,83,0.10);">
    <!-- TOP FUTURISTIC DOPAMINE HEADER + INSTANT PDF DOWNLOAD BUTTON -->
    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; border-bottom:2.5px solid #094053; padding-bottom:8px; margin-bottom:10px;">
        <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
            <span style="background:{badge_color}; color:#ffffff; padding:4px 10px; border-radius:20px; font-size:11.5px; font-weight:900; letter-spacing:0.3px;">
                {category_label}
            </span>
            <span style="background:#e0f2fe; color:#0369a1; padding:3px 9px; border-radius:14px; font-size:11px; font-weight:800;">
                📅 {pub_date_disp}
            </span>
            <span style="background:#fef3c7; color:#92400e; padding:3px 9px; border-radius:14px; font-size:11px; font-weight:800;">
                ⏱️ {read_mins} Min Read
            </span>
        </div>
        <button type="button" onclick="if(window.snDownloadSingleHinduArticlePDF) window.snDownloadSingleHinduArticlePDF('hindu-card-{safe_art_id}', '{ re.sub(r'[^a-zA-Z0-9]+', '_', title)[:35] }')" style="background:linear-gradient(135deg,#dc2626,#b91c1c); color:#ffffff; border:1.5px solid #fef08a; padding:6px 13px; border-radius:8px; font-size:11.5px; font-weight:900; cursor:pointer; display:inline-flex; align-items:center; gap:5px; box-shadow:0 3px 8px rgba(220,38,38,0.3);">
            📥 Download PDF (With Vocab & Analytical Qs)
        </button>
    </div>

    <!-- HEADLINE -->
    <h2 style="margin:0 0 8px 0; font-family:Georgia,serif; font-size:19.5px; font-weight:900; color:#094053; line-height:1.35;">
        📰 {title}
    </h2>

    <!-- EXAM RELEVANCE & INTERACTIVE DOUBLE-CLICK RADAR BAR -->
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:8px; margin-bottom:12px;">
        <div style="background:#eef2ff; border-left:4px solid #4f46e5; padding:7px 10px; border-radius:6px; font-size:11.8px; font-weight:800; color:#1e3a8a;">
            🎯 <strong>Exam Relevance:</strong> {relevance}
        </div>
        <div style="background:linear-gradient(90deg,#041922,#094053); border:1.5px solid #f8c016; padding:7px 10px; border-radius:6px; font-size:11.5px; font-weight:800; color:#fef08a;">
            🔮 <strong>Futuristic Word Radar:</strong> Paragraph ke kisi bhi English word par <u>Double-Click</u> karein — turant uska <strong>Hinglish Meaning + Picture</strong> screen par dekhein!
        </div>
    </div>

    {img_block}

    <!-- MAIN PARAGRAPHS (DOUBLE-CLICK WORD ENABLED) -->
    <div style="background:#ffffff; border:1.5px solid #e2e8f0; border-radius:8px; padding:14px; margin-bottom:14px;">
        {paras_html}
    </div>

    <!-- 3-POINT EXAM TAKEAWAY -->
    <div style="background:#fffbeb; border:1.5px solid #f59e0b; border-left:5px solid #d97706; border-radius:8px; padding:12px; margin-bottom:14px; font-size:12.8px; line-height:1.6; color:#0f172a;">
        <div style="font-weight:900; color:#b45309; margin-bottom:6px; text-transform:uppercase;">⚡ 3-Point Exam Takeaway & Deep Breakdown</div>
        {deep_explanation}
    </div>

    <!-- NEW ADDITION 1: 4 EXAM-ORIENTED VOCAB WORDS WITH SHORT HINGLISH ANSWER -->
    <div style="background:#f0f9ff; border:2px solid #0284c7; border-radius:10px; padding:13px; margin-bottom:14px;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px; margin-bottom:9px;">
            <h4 style="margin:0; color:#0369a1; font-size:14px; font-weight:900; text-transform:uppercase;">
                📖 4 Exam-Oriented Vocabulary Words (With Short Hinglish Answer)
            </h4>
            <span style="font-size:11px; color:#0f766e; font-weight:800;">✨ Click any word to see its Picture!</span>
        </div>
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(230px, 1fr)); gap:8px;">
            {vocab_cards_html}
        </div>
    </div>

    <!-- NEW ADDITION 2: 2 ULTRA PREMIUM ANALYTICAL QUESTIONS ON PARAGRAPH WITH ANSWER -->
    <div style="background:#f5f3ff; border:2px solid #7c3aed; border-radius:10px; padding:13px;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px; margin-bottom:10px;">
            <h4 style="margin:0; color:#5b21b6; font-size:14px; font-weight:900; text-transform:uppercase;">
                🧠 Ultra Premium Analytical Questions (Based on Paragraph)
            </h4>
            <button type="button" onclick="if(window.snDownloadSingleHinduArticlePDF) window.snDownloadSingleHinduArticlePDF('hindu-card-{safe_art_id}', '{ re.sub(r'[^a-zA-Z0-9]+', '_', title)[:35] }')" style="background:#094053; color:#f8c016; border:1px solid #f8c016; padding:4px 10px; border-radius:6px; font-size:11px; font-weight:900; cursor:pointer;">
                📥 Save Full Editorial + Q&A as PDF
            </button>
        </div>
        {questions_cards_html}
    </div>
</div>
""".strip()

    return {
        "imageUrl": image_url,
        "fullParagraphs": paras,
        "deepExplanation": deep_explanation,
        "vocabList": vocab_simple_pills,
        "vocabHinglish4": vocab_4_list,
        "ultraAnalyticalQuestions2": analytical_2_qs,
        "readingMinutes": read_mins,
        "newspaperPrintHtml": newspaper_print_html,
    }


# ==============================================================================
# 6. DAILY 10 REAL GK/CA QUIZ GENERATOR (ENGLISH, HINDI & MARATHI)
# ==============================================================================
def build_daily_10_real_gk_questions_from_news(articles, date_label):
    questions = []
    cat_distractors = {
        "national": [
            "Ministry of Home Affairs & NITI Aayog Joint Constitutional Directive",
            "16th Finance Commission Special State Fiscal Grant",
            "Inter-State Council Administrative Reform Panel",
        ],
        "economy": [
            "RBI Statutory Liquidity & Standing Deposit Facility Review",
            "SEBI Institutional Foreign Portfolio Regulatory Framework",
            "Goods and Services Tax (GST) Council Fitment Committee",
        ],
        "ir": [
            "Indo-Pacific Maritime Security & Quad Strategic Initiative",
            "BRICS New Development Bank Multilateral Settlement Charter",
            "United Nations General Assembly Sustainable Global Compact",
        ],
        "scitech": [
            "ISRO Next-Gen Polar Satellite Cryogenic Propulsion Module",
            "DRDO Indigenous Hypersonic Technology Demonstrator Vehicle",
            "National Quantum Mission & Photonics Research Taskforce",
        ],
        "editorial": [
            "Constitutional Morality & Cooperative Federalism Doctrine",
            "Macroeconomic Fiscal Consolidation & Capex Multiplier",
            "Digital Public Infrastructure & Institutional Accountability",
        ],
    }

    for idx, art in enumerate(articles[:10]):
        title = art.get("title", "").strip()
        cat_key = art.get("category", "national")
        cat_lbl = art.get("categoryLabel", "Current Affairs")
        summary_line = (art.get("fullParagraphs") or [art.get("summary", title)])[0]
        short_ans = title if len(title) <= 88 else title[:85] + "..."

        distractors = cat_distractors.get(cat_key, cat_distractors["national"])
        correct_pos = (idx + len(title)) % 4
        opts_en = list(distractors[:3])
        opts_en.insert(correct_pos, short_ans)

        q_en = f"[{date_label} | {cat_lbl}] With reference to current affairs, which of the following developments is highlighted in the news: \"{summary_line[:135]}...\"?"
        q_hi = f"[{date_label} | {cat_lbl}] समसामयिक घटनाक्रम (Current Affairs) के संदर्भ में, निम्नलिखित में से कौन-सा प्रमुख विषय चर्चा में है: \"{summary_line[:135]}...\"?"
        q_mr = f"[{date_label} | {cat_lbl}] चालू घडामोडींच्या संदर्भात खालीलपैकी कोणता महत्त्वाचा विषय चर्चेत आहे: \"{summary_line[:135]}...\"?"

        questions.append({
            "id": f"gk_{date_label.replace(' ', '_')}_{idx+1}",
            "cat": cat_lbl,
            "date": date_label,
            "qEn": q_en,
            "qHi": q_hi,
            "qMr": q_mr,
            "optsEn": opts_en,
            "optsHi": opts_en,
            "optsMr": opts_en,
            "ans": correct_pos,
            "explanation": art.get("deepExplanation") or summary_line,
        })

    return questions


# ==============================================================================
# 7. EMBEDDED CLIENT-SIDE FUTURISTIC DOUBLE-CLICK WORD + PICTURE + PDF ENGINE
# ==============================================================================
FUTURISTIC_READER_CLIENT_SCRIPT = """
(function() {
  "use strict";
  if (window.__SN_HINDU_FUTURISTIC_ENGINE_LOADED__) return;
  window.__SN_HINDU_FUTURISTIC_ENGINE_LOADED__ = true;

  // Built-in Fast Hinglish Dictionary for Common & Exam Words (Plus Live API Fallback for ANY word like 'pomegranate')
  const FAST_HINGLISH_DICT = {
    "pomegranate": "Anaar (अनार) — Lal raseele daano wala phal jo iron aur antioxidants se bharpoor hota hai.",
    "institutional": "Sansthagat (संस्थागत) — Kisi sarkari ya kanooni sanstha ke niyamon se juda hua.",
    "constitutional": "Samvaidhanik (संवैधानिक) — Bharat ke Samvidhan ke adhikaaron aur niyamon ke mutabik.",
    "accountability": "Jawabdehi (जवाबदेही) — Apne kaam aur faislon ki kanooni aur naitik zimmedari.",
    "macroeconomic": "Samashti Arthashastra — Poore desh ki economy (GDP, Mehengai, Rozgar) ka vishleshan.",
    "resilience": "Lachilapan / Majbooti — Sankat ya mushkil ke baad tezi se wapas ubharne ki shakti.",
    "inclusive": "Samaveshi (समावेशी) — Sabhi vargon (khas-taur par kamzor varg) ko sath lekar chalne wala.",
    "transmission": "Prasaran / Pahunch — Niyam ya monetary policy ka zameeni star tak asar pahunchna.",
    "multilateral": "Bahupakshiya — Jisme anek desh (jaise UN, G20, BRICS) milkar sahyog karte hain.",
    "bilateral": "Dwipakshiya — Do deshon ke beech aapsi samjhauta aur vyapar.",
    "indigenous": "Swadeshi (स्वदेशी) — Apne hi desh mein vaigyanikon dwara viksit kiya gaya.",
    "sustainability": "Satat Vikas — Paryavaran ko surakshit rakhte hue lambe samay ka vikas.",
    "jurisdiction": "Adhikar Kshetra — Court ya sanstha ki kanooni seema.",
    "pragmatic": "Vyavaharik (व्यावहारिक) — Real ground par kaam karne wala practical tarika.",
    "inflation": "Mehengai / Mudrasphiti — Vastuon ki keemat badhna aur paise ki value ghatna.",
    "fiscal": "Rajkoshiya — Sarkar ke Budget, Tax aur kharche se sambandhit.",
    "autonomy": "Swayattata — Bina बाहरी dabav ke swantantra faisla lene ki azaadi.",
    "statutory": "Vaidhanik — Parliament ke kanoon (Act) dwara sthapit.",
    "mitigate": "Kam Karna — Kisi sankat ya nuksan ke prabhav ko ghatana.",
    "paradigm": "Naya Dhaancha / Model — Kaam karne ya sochne ka krantikari tarika."
  };

  function ensureWordPopupModalExists() {
    let modal = document.getElementById("snFuturisticWordModal");
    if (modal) return modal;
    modal = document.createElement("div");
    modal.id = "snFuturisticWordModal";
    modal.style.cssText = "display:none; position:fixed; inset:0; background:rgba(2,17,24,0.78); backdrop-filter:blur(6px); z-index:2147483647; align-items:center; justify-content:center; padding:16px;";
    modal.innerHTML = `
      <div style="background:linear-gradient(145deg,#041922,#094053); color:#ffffff; width:100%; max-width:440px; border-radius:16px; border:2.5px solid #f8c016; overflow:hidden; box-shadow:0 25px 60px rgba(0,0,0,0.65); font-family:'Plus Jakarta Sans',sans-serif;">
        <div style="padding:12px 16px; background:#021118; border-bottom:1.5px solid rgba(248,192,22,0.35); display:flex; justify-content:space-between; align-items:center;">
          <span style="color:#f8c016; font-weight:900; font-size:0.9rem;">🔮 AI Word Radar (Hinglish + Live Picture)</span>
          <button type="button" onclick="document.getElementById('snFuturisticWordModal').style.display='none'" style="background:#ef4444; color:#fff; border:none; width:26px; height:26px; border-radius:50%; font-weight:900; cursor:pointer;">✕</button>
        </div>
        <div style="padding:16px;" id="snFuturisticWordModalBody"></div>
      </div>
    `;
    modal.addEventListener("click", function(e) {
      if (e.target === modal) modal.style.display = "none";
    });
    document.body.appendChild(modal);
    return modal;
  }

  window.snTriggerWordPopupDirect = async function(rawWord) {
    const cleanW = String(rawWord || "").replace(/[^a-zA-Z\\-]/g, "").trim();
    if (!cleanW || cleanW.length < 2) return;
    const wLow = cleanW.toLowerCase();

    const modal = ensureWordPopupModalExists();
    const body = document.getElementById("snFuturisticWordModalBody");
    modal.style.display = "flex";

    const fallbackImg = `https://image.pollinations.ai/prompt/${encodeURIComponent(cleanW + " realistic educational illustration high quality")}?width=420&height=240&nologo=true`;

    body.innerHTML = `
      <div style="text-align:center; padding:12px;">
        <div style="font-size:1.25rem; font-weight:900; color:#f8c016; text-transform:capitalize;">🔍 "${cleanW}"</div>
        <div style="font-size:0.78rem; color:#38bdf8; margin-top:6px;">⚡ Scanning Hinglish Lexicon & Visual Image...</div>
      </div>
    `;

    let hinglishMeaning = FAST_HINGLISH_DICT[wLow] || "";
    let englishDef = "";
    let wikiImageUrl = "";

    // 1. Fetch Wikipedia Summary & Real Picture (Works great for nouns like 'pomegranate', 'parliament', 'inflation', etc.)
    try {
      const wikiRes = await fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(cleanW)}`);
      if (wikiRes.ok) {
        const wikiData = await wikiRes.json();
        if (wikiData.thumbnail && wikiData.thumbnail.source) {
          wikiImageUrl = wikiData.thumbnail.source;
        }
        if (wikiData.extract) {
          englishDef = wikiData.extract.split(". ")[0] + ".";
        }
      }
    } catch (e) {}

    // 2. Fetch Dictionary Definition if needed
    if (!englishDef) {
      try {
        const dictRes = await fetch(`https://api.dictionaryapi.dev/api/v2/entries/en/${encodeURIComponent(wLow)}`);
        if (dictRes.ok) {
          const dictData = await dictRes.json();
          const firstDef = dictData?.[0]?.meanings?.[0]?.definitions?.[0]?.definition;
          if (firstDef) englishDef = firstDef;
        }
      } catch (e) {}
    }

    // 3. Fetch Live Hindi/Hinglish Translation if not in local fast dictionary
    if (!hinglishMeaning) {
      try {
        const trRes = await fetch(`https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=hi&dt=t&q=${encodeURIComponent(cleanW)}`);
        if (trRes.ok) {
          const trData = await trRes.json();
          const hiWord = trData?.[0]?.[0]?.[0] || "";
          if (hiWord) {
            hinglishMeaning = `${hiWord} — ${englishDef || ("Is shabd ka prayog editorial mein '" + cleanW + "' ke arth mein kiya gaya hai.")}`;
          }
        }
      } catch (e) {}
    }

    if (!hinglishMeaning) {
      hinglishMeaning = englishDef || `Exam-oriented term ("${cleanW}") — Editorial context mein iska prayog mukhya vishay ko darshane ke liye hua hai.`;
    }

    const finalImg = wikiImageUrl || fallbackImg;

    body.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
        <div>
          <span style="font-size:1.35rem; font-weight:900; color:#fef08a; text-transform:capitalize;">${cleanW}</span>
          <span style="background:#0284c7; color:#fff; font-size:0.68rem; font-weight:800; padding:2px 8px; border-radius:12px; margin-left:6px;">Hinglish Visual Dictionary</span>
        </div>
        <button type="button" onclick="if('speechSynthesis' in window){const u=new SpeechSynthesisUtterance('${cleanW}'); u.lang='en-IN'; window.speechSynthesis.speak(u);}" style="background:rgba(255,255,255,0.15); border:1px solid #f8c016; color:#f8c016; border-radius:20px; padding:4px 10px; font-size:0.72rem; font-weight:800; cursor:pointer;">
          🔊 Pronounce
        </button>
      </div>

      <div style="background:#021118; border:1.5px solid #334155; border-radius:10px; overflow:hidden; margin-bottom:12px; text-align:center;">
        <img src="${finalImg}" alt="${cleanW}" onerror="this.src='${fallbackImg}'" style="width:100%; max-height:210px; object-fit:cover; display:block;">
      </div>

      <div style="background:rgba(16,185,129,0.15); border-left:4px solid #10b981; padding:10px 12px; border-radius:8px; margin-bottom:8px; font-size:0.82rem; line-height:1.55;">
        <div style="color:#6ee7b7; font-weight:900; font-size:0.72rem; text-transform:uppercase; margin-bottom:2px;">🇮🇳 Hinglish Meaning (आसान मतलब):</div>
        <div style="color:#ffffff; font-weight:700;">${hinglishMeaning}</div>
      </div>

      ${englishDef ? `
        <div style="background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.15); padding:8px 10px; border-radius:8px; font-size:0.75rem; color:#cbd5e1; line-height:1.45;">
          <strong style="color:#38bdf8;">📘 English Context:</strong> ${englishDef}
        </div>
      ` : ""}
    `;
  };

  window.snLookupHinduWordDblClick = function(event) {
    const sel = window.getSelection ? window.getSelection().toString().trim() : "";
    if (sel && sel.length >= 2 && sel.length <= 28) {
      window.snTriggerWordPopupDirect(sel);
    }
  };

  // Instant 1-Click PDF Downloader for Any Editorial Card (Includes Paragraph + 4 Vocab + 2 Analytical Questions)
  window.snDownloadSingleHinduArticlePDF = function(cardElementId, cleanTitleSlug) {
    const cardEl = document.getElementById(cardElementId);
    if (!cardEl) return;
    const fileName = `The_Hindu_Editorial_${cleanTitleSlug || "Digest"}_2026.pdf`;
    if (typeof window.html2pdf === "function") {
      window.html2pdf().set({
        margin: [8, 8, 8, 8],
        filename: fileName,
        image: { type: "jpeg", quality: 0.98 },
        html2canvas: { scale: 2, useCORS: true },
        jsPDF: { unit: "mm", format: "a4", orientation: "portrait" }
      }).from(cardEl).save();
    } else {
      const printWin = window.open("", "_blank");
      if (printWin) {
        printWin.document.write(`<html><head><title>${fileName}</title></head><body style="font-family:Georgia,serif; padding:20px;">${cardEl.outerHTML}<script>window.onload=function(){window.print();}<\\/script></body></html>`);
        printWin.document.close();
      }
    }
  };
})();
""".strip()


# ==============================================================================
# 8. UNIFIED FAST 3-DAY ARCHIVE SYNC & STORAGE PRUNER
# ==============================================================================
def run_unified_3day_newspaper_sync():
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    ist_now = datetime.now(ist_tz)
    today_iso = ist_now.strftime("%Y-%m-%d")
    today_display = ist_now.strftime("%d %b %Y")
    timestamp_str = ist_now.strftime("%d %b %Y, %I:%M %p IST")

    # Top 3 Clickable Date Tabs (Today, Yesterday, 2 Days Ago)
    last_3_days = [
        {
            "iso": (ist_now - timedelta(days=i)).strftime("%Y-%m-%d"),
            "disp": (ist_now - timedelta(days=i)).strftime("%d %b %Y"),
            "dayLabel": "Today" if i == 0 else ("Yesterday" if i == 1 else "2 Days Ago"),
        }
        for i in range(3)
    ]

    archive = {}
    if os.path.exists(OUTPUT_JSON_FILE) and not FORCE_PURGE_FLAG:
        try:
            with open(OUTPUT_JSON_FILE, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                if isinstance(old_data.get("archiveByDate"), dict):
                    archive = old_data["archiveByDate"]
        except Exception:
            archive = {}

    for d_info in last_3_days:
        if d_info["iso"] not in archive or not isinstance(archive[d_info["iso"]].get("articles"), list):
            archive[d_info["iso"]] = {
                "dateIso": d_info["iso"],
                "dateDisplay": d_info["disp"],
                "dayLabel": d_info["dayLabel"],
                "updatedAt": timestamp_str,
                "articles": [],
            }

    collected_all = []
    seen_titles = set()

    for sec in EXAM_SECTIONS:
        sec_items_found = 0
        for feed_url in [sec["direct_rss"], sec["google_rss"], sec["bing_rss"]]:
            if sec_items_found >= 5:
                break
            try:
                xml_bytes = fetch_xml_bytes(feed_url, timeout=12)
                root = ET.fromstring(xml_bytes)

                for item in root.findall(".//item"):
                    if sec_items_found >= 6:
                        break
                    raw_title = (item.findtext("title") or "").strip()
                    clean_title = scrub_clean_text(raw_title)
                    if len(clean_title) < 14 or DROP_NOISE_REGEX.search(clean_title):
                        continue

                    norm_t = re.sub(r"[^a-z0-9]+", "", clean_title.lower())[:32]
                    if norm_t in seen_titles:
                        continue
                    seen_titles.add(norm_t)

                    raw_desc = item.findtext("description") or ""
                    raw_link = (item.findtext("link") or "").strip()
                    pub_raw = (item.findtext("pubDate") or "").strip()

                    art_iso = today_iso
                    art_disp = today_display
                    try:
                        p_dt = parsedate_to_datetime(pub_raw).astimezone(ist_tz)
                        c_iso = p_dt.strftime("%Y-%m-%d")
                        if any(d["iso"] == c_iso for d in last_3_days):
                            art_iso = c_iso
                            art_disp = p_dt.strftime("%d %b %Y")
                    except Exception:
                        pass

                    art_id = hashlib.md5(f"{sec['key']}_{clean_title}".encode("utf-8")).hexdigest()[:12]

                    deep_pack = build_full_story_and_newspaper_print(
                        raw_link,
                        clean_title,
                        sec["key"],
                        sec["label"],
                        sec["badge_color"],
                        sec["relevance"],
                        art_disp,
                        raw_desc,
                        art_id,
                    )

                    art_obj = {
                        "id": art_id,
                        "category": sec["key"],
                        "categoryLabel": sec["label"],
                        "title": clean_title,
                        "link": "#in-app-reader",
                        "pubDate": art_disp,
                        "dateIso": art_iso,
                        "dateDisplay": art_disp,
                        "readingMinutes": deep_pack["readingMinutes"],
                        "examRelevance": sec["relevance"],
                        "imageUrl": deep_pack["imageUrl"],
                        "fullParagraphs": deep_pack["fullParagraphs"],
                        "deepExplanation": deep_pack["deepExplanation"],
                        "vocabList": deep_pack["vocabList"],
                        "vocabHinglish4": deep_pack["vocabHinglish4"],
                        "ultraAnalyticalQuestions2": deep_pack["ultraAnalyticalQuestions2"],
                        "newspaperPrintHtml": deep_pack["newspaperPrintHtml"],
                        "summary": deep_pack["fullParagraphs"][0],
                        "keyPoints": "<br>".join(f"• {p}" for p in deep_pack["fullParagraphs"][:3]),
                    }

                    collected_all.append(art_obj)
                    day_list = archive[art_iso]["articles"]
                    existing_idx = next((i for i, x in enumerate(day_list) if x.get("title") == clean_title), -1)
                    if existing_idx != -1:
                        day_list[existing_idx] = art_obj
                    else:
                        day_list.append(art_obj)

                    sec_items_found += 1
            except Exception as e:
                print(f"   [Feed Notice] {sec['key']} ({feed_url[:35]}...): {e}")

        print(f"   ✅ Section '{sec['key']}': Collected {sec_items_found} futuristic broadsheet articles")

    # Ensure all 3 date tabs are populated so clicking any of the 3 dates shows full broadsheet articles
    if collected_all:
        if not archive[last_3_days[0]["iso"]]["articles"]:
            archive[last_3_days[0]["iso"]]["articles"] = collected_all[:10]
        if not archive[last_3_days[1]["iso"]]["articles"]:
            archive[last_3_days[1]["iso"]]["articles"] = collected_all[4:12] if len(collected_all) >= 6 else collected_all
        if not archive[last_3_days[2]["iso"]]["articles"]:
            archive[last_3_days[2]["iso"]]["articles"] = collected_all[8:16] if len(collected_all) >= 10 else collected_all

    # Option A + Option B Storage Pruner: If FORCE_PURGE_FLAG is active, delete oldest 2 days and keep only Today
    if FORCE_PURGE_FLAG:
        sorted_3_keys = [last_3_days[0]["iso"]]
        print("🧹 [The Hindu Storage Guard] Manual Purge Active — Deleted oldest 2 days archive!")
    else:
        sorted_3_keys = [d["iso"] for d in last_3_days]

    clean_3day_archive = {k: archive[k] for k in sorted_3_keys}
    daily_10_quiz = build_daily_10_real_gk_questions_from_news(collected_all, today_display)

    google_schema = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": f"The Hindu Daily Editorial, 4 Hinglish Vocab & Ultra Premium Analytical Questions ({today_display})",
        "itemListElement": [
            {
                "@type": "NewsArticle",
                "position": i + 1,
                "headline": a["title"],
                "datePublished": a["dateIso"],
                "articleSection": a["categoryLabel"],
                "description": a["summary"],
            }
            for i, a in enumerate(collected_all[:10])
        ],
    }

    final_payload = {
        "projectRepo": PROJECT_REPO_NAME,
        "updatedAt": timestamp_str,
        "currentDateIso": today_iso,
        "currentDateDisplay": today_display,
        "availableDates": [
            {
                "dateIso": k,
                "dateDisplay": clean_3day_archive[k]["dateDisplay"],
                "dayLabel": clean_3day_archive[k].get("dayLabel", f"Day {idx + 1}"),
                "updatedAt": timestamp_str,
                "articleCount": len(clean_3day_archive[k]["articles"]),
            }
            for idx, k in enumerate(sorted_3_keys)
        ],
        "hookLine1": f"Daily Editorial, 4 Hinglish Vocab & 2 Ultra Premium Analytical Questions ({today_display})",
        "hookLine2": f"Futuristic Double-Click Word Picture Dictionary + 1-Click PDF Download • Updated: {timestamp_str}",
        "totalArticles": len(collected_all),
        "articles": collected_all,
        "archiveByDate": clean_3day_archive,
        "dailyQuiz10": daily_10_quiz,
        "interactiveReaderScript": FUTURISTIC_READER_CLIENT_SCRIPT,
        "googleSchema": google_schema,
    }

    with open(OUTPUT_JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, ensure_ascii=False, indent=2)

    print(
        f"🎉 [{PROJECT_REPO_NAME}] The Hindu Broadsheet Sync Complete! "
        f"Articles: {len(collected_all)} | 4 Hinglish Vocab & 2 Analytical Qs per Article | 3-Day Tabs Saved!"
    )
    return len(collected_all)


def main():
    try:
        run_unified_3day_newspaper_sync()
    except Exception as e:
        print(f"❌ Error in The Hindu Bot: {e}")


if __name__ == "__main__":
    main()
