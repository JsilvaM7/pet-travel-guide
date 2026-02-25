"""
generate_routes.py
Lê a planilha Pet-Travel e gera arquivos HTML individuais em ./routes/
Também gera routes.json e sitemap.xml na raiz.
Requer: pip install gspread google-auth
"""

import os
import re
import json
import unicodedata
from datetime import date
import gspread
from google.oauth2.service_account import Credentials

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES — edite aqui antes de rodar
# ══════════════════════════════════════════════════════════════════════════════
SPREADSHEET_ID       = "1-f9NQ0sqBXA-tpKtRMG9h5aaSt5jK3Q-xoH7Bz8FXE0"
SHEET_NAME           = "Página1"
SERVICE_ACCOUNT_FILE = "pet-travel-pseo-a915ba0649b4.json"
OUTPUT_DIR           = "routes"
SITE_DOMAIN          = "https://pet.e-dolphin.info"   # usado no sitemap.xml

# ── Amazon Associates IDs ─────────────────────────────────────────────────────
AMAZON_BR_TAG  = "petpassport04-20"    # Amazon.com.br
AMAZON_US_TAG  = "petpasspor03c-20"    # Amazon.com  (fallback para outras origens)
AMAZON_UK_TAG  = "petpassportuk-21"    # Amazon.co.uk

# ── Booking.com ───────────────────────────────────────────────────────────────
BOOKING_AID = "seu-aid-booking"        # ← troque pelo seu AID do Booking.com

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ══════════════════════════════════════════════════════════════════════════════
# DADOS DE APOIO
# ══════════════════════════════════════════════════════════════════════════════
FLAGS = {
    "usa": "🇺🇸", "us": "🇺🇸", "united states": "🇺🇸", "united-states": "🇺🇸",
    "uk": "🇬🇧", "united kingdom": "🇬🇧", "united-kingdom": "🇬🇧", "england": "🇬🇧",
    "brazil": "🇧🇷", "brasil": "🇧🇷",
    "portugal": "🇵🇹", "spain": "🇪🇸", "españa": "🇪🇸",
    "germany": "🇩🇪", "france": "🇫🇷", "italy": "🇮🇹",
    "australia": "🇦🇺", "canada": "🇨🇦",
    "japan": "🇯🇵", "japão": "🇯🇵",
    "china": "🇨🇳",
    "uae": "🇦🇪", "dubai": "🇦🇪", "united arab emirates": "🇦🇪",
    "argentina": "🇦🇷", "chile": "🇨🇱", "uruguay": "🇺🇾",
    "mexico": "🇲🇽", "méxico": "🇲🇽",
    "thailand": "🇹🇭", "new zealand": "🇳🇿",
}

ANIMAL_EMOJI = {"dog": "🐕", "cat": "🐈", "bird": "🦜", "rabbit": "🐇"}

COUNTRY_SLUG = {
    "united states": "usa", "united states of america": "usa", "us": "usa",
    "united kingdom": "uk", "great britain": "uk", "england": "uk",
    "united arab emirates": "uae", "emirates": "uae", "dubai": "uae",
    "brasil": "brazil", "deutschland": "germany", "españa": "spain",
    "japão": "japan", "méxico": "mexico", "tailândia": "thailand",
    "new zealand": "new-zealand", "south korea": "south-korea",
    "south africa": "south-africa", "saudi arabia": "saudi-arabia",
}

# ══════════════════════════════════════════════════════════════════════════════
# FUNÇÕES UTILITÁRIAS
# ══════════════════════════════════════════════════════════════════════════════
def normalize_str(text):
    text = unicodedata.normalize('NFD', text)
    return ''.join(c for c in text if unicodedata.category(c) != 'Mn')

def normalize_country(name):
    key = normalize_str(name.lower().strip())
    return COUNTRY_SLUG.get(key, key)

def slugify(text):
    text = normalize_str(text.lower().strip())
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'\s+', '-', text)
    return text

def build_slug(origin, destination, animal):
    return f"{slugify(normalize_country(origin))}-to-{slugify(normalize_country(destination))}-{slugify(animal)}"

def get_flag(country):
    key = normalize_str(country.lower().strip())
    return FLAGS.get(key, "🌍")

def get_animal_emoji(animal):
    return ANIMAL_EMOJI.get(animal.lower().strip(), "🐾")

def build_checklist(req_text):
    parts = re.split(r'[·\n]+', req_text)
    items = [p.strip() for p in parts if len(p.strip()) > 6]
    if not items:
        return f'<li class="check-item"><span class="check-icon">✓</span>{req_text}</li>'
    return "\n".join(
        f'<li class="check-item"><span class="check-icon">✓</span>{item}</li>'
        for item in items
    )

# ══════════════════════════════════════════════════════════════════════════════
# LÓGICA DE AFILIADOS
# ══════════════════════════════════════════════════════════════════════════════
def get_amazon_url(origin: str, animal: str) -> str:
    """
    Redirecionamento inteligente por origem:
    - Brazil  → amazon.com.br  + AMAZON_BR_TAG
    - UK      → amazon.co.uk   + AMAZON_UK_TAG
    - Qualquer outra → amazon.com + AMAZON_US_TAG
    """
    origin_key = normalize_str(origin.lower().strip())
    query = f"pet+travel+{animal.lower()}+carrier+accessories"

    if origin_key in ("brazil", "brasil"):
        return f"https://www.amazon.com.br/s?k={query}&tag={AMAZON_BR_TAG}"
    elif origin_key in ("uk", "united-kingdom", "united kingdom", "england"):
        return f"https://www.amazon.co.uk/s?k={query}&tag={AMAZON_UK_TAG}"
    else:
        return f"https://www.amazon.com/s?k={query}&tag={AMAZON_US_TAG}"

def get_booking_url(destination: str) -> str:
    """Booking.com com destino dinâmico."""
    dest = destination.replace(" ", "+")
    return (
        f"https://www.booking.com/search.html"
        f"?ss={dest}&aid={BOOKING_AID}"
        f"&label=petpassport-{slugify(destination)}"
    )

# ══════════════════════════════════════════════════════════════════════════════
# GERADOR DE HTML
# ══════════════════════════════════════════════════════════════════════════════
def generate_html(row, slug, amazon_url, booking_url):
    origin      = row.get("Origin", "")
    destination = row.get("Destination", "")
    animal      = row.get("Animal", "")
    req_breve   = row.get("Requirements (Breve)", "No requirements found.")
    detailed    = row.get("Detailed_Requirements", "")

    origin_flag  = get_flag(origin)
    dest_flag    = get_flag(destination)
    animal_emoji = get_animal_emoji(animal)
    checklist    = build_checklist(req_breve)
    detailed_html = (
        f"<p>{detailed}</p>" if detailed
        else "<p style='opacity:.6;font-style:italic'>Please verify detailed requirements with the official veterinary authority of the destination country before traveling.</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Pet Travel: {origin} to {destination} ({animal}) — PetPassport</title>
  <meta name="description" content="Official pet import requirements for traveling with your {animal.lower()} from {origin} to {destination}. Microchip, vaccines, quarantine rules and more."/>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700;900&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet"/>
  <style>
    :root {{
      --cream: #F5F0E8; --forest: #1C3A2B;
      --sage: #4A7C59;  --gold: #C9A84C;
      --mist: #E8EFE9;  --orange: #E07B2A;
      --blue: #2563EB;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'DM Sans', sans-serif; background: var(--cream); color: var(--forest); }}
    body::before {{
      content: ''; position: fixed; inset: 0; pointer-events: none; z-index: 0;
      background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.04'/%3E%3C/svg%3E");
    }}
    nav {{
      position: fixed; top: 0; left: 0; right: 0; z-index: 100;
      display: flex; align-items: center; justify-content: space-between;
      padding: 1.25rem 3rem;
      background: rgba(245,240,232,0.88); backdrop-filter: blur(12px);
      border-bottom: 1px solid rgba(74,124,89,0.15);
    }}
    .logo {{ font-family:'Playfair Display',serif; font-size:1.4rem; font-weight:900; color:var(--forest); text-decoration:none; }}
    .logo span {{ color: var(--sage); }}
    .breadcrumb {{ font-size:0.78rem; opacity:0.55; display:flex; align-items:center; gap:0.4rem; }}
    .breadcrumb a {{ color:var(--forest); text-decoration:none; }}

    /* HERO */
    .hero {{ position:relative; z-index:1; background:var(--forest); padding:9rem 3rem 5rem; overflow:hidden; }}
    .blob {{ position:absolute; border-radius:50%; filter:blur(80px); opacity:0.2; pointer-events:none; }}
    .blob-1 {{ width:500px; height:500px; background:var(--sage); top:-150px; right:-100px; }}
    .blob-2 {{ width:300px; height:300px; background:var(--gold); bottom:-80px; left:5%; }}
    .hero-inner {{ max-width:900px; margin:0 auto; position:relative; z-index:2; }}
    .back-link {{ display:inline-flex; align-items:center; gap:0.4rem; margin-bottom:2rem; font-size:0.85rem; color:var(--cream); opacity:0.6; text-decoration:none; transition:opacity .2s; }}
    .back-link:hover {{ opacity:1; }}
    .route-display {{ display:flex; align-items:center; gap:2rem; margin-bottom:2rem; }}
    .country-block {{ text-align:center; }}
    .country-flag {{ font-size:4rem; line-height:1; display:block; margin-bottom:0.5rem; }}
    .country-name {{ font-size:0.75rem; font-weight:500; text-transform:uppercase; letter-spacing:0.1em; color:rgba(245,240,232,0.6); }}
    .route-arrow {{ font-size:2rem; color:var(--gold); display:flex; flex-direction:column; align-items:center; gap:0.25rem; }}
    .route-arrow span {{ font-size:0.65rem; opacity:0.5; text-transform:uppercase; letter-spacing:0.08em; color:var(--cream); }}
    .hero h1 {{ font-family:'Playfair Display',serif; font-weight:900; color:var(--cream); font-size:clamp(2rem,5vw,3.5rem); line-height:1.1; letter-spacing:-0.02em; margin-bottom:1rem; }}
    .meta-chip {{ display:inline-flex; align-items:center; gap:0.4rem; margin-right:0.5rem; margin-top:0.5rem; background:rgba(245,240,232,0.1); border:1px solid rgba(245,240,232,0.2); color:var(--cream); font-size:0.8rem; padding:0.35rem 0.85rem; border-radius:100px; }}

    /* CONTENT */
    .content {{ position:relative; z-index:1; max-width:900px; margin:0 auto; padding:4rem 3rem; }}
    .card {{ background:white; border-radius:24px; padding:2.5rem; box-shadow:0 4px 40px rgba(28,58,43,0.08); margin-bottom:2rem; }}
    .card-label {{ font-size:0.7rem; font-weight:500; text-transform:uppercase; letter-spacing:0.12em; color:var(--sage); margin-bottom:1rem; }}
    .card h2 {{ font-family:'Playfair Display',serif; font-size:1.4rem; font-weight:700; margin-bottom:1.5rem; }}

    /* CHECKLIST */
    .check-list {{ list-style:none; display:flex; flex-direction:column; gap:0.85rem; }}
    .check-item {{ display:flex; align-items:flex-start; gap:0.85rem; font-size:0.95rem; line-height:1.5; padding-bottom:0.85rem; border-bottom:1px solid rgba(74,124,89,0.08); }}
    .check-item:last-child {{ border-bottom:none; padding-bottom:0; }}
    .check-icon {{ flex-shrink:0; width:22px; height:22px; background:var(--mist); color:var(--sage); border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:0.7rem; font-weight:700; margin-top:0.1rem; }}

    /* CTA CARD */
    .cta-card {{ background:var(--forest); border-radius:24px; padding:2.5rem; margin-bottom:2rem; }}
    .cta-card h3 {{ font-family:'Playfair Display',serif; font-size:1.6rem; font-weight:700; color:var(--cream); margin-bottom:0.5rem; }}
    .cta-card p {{ font-size:0.9rem; color:rgba(245,240,232,0.6); line-height:1.6; margin-bottom:1.5rem; }}
    .btn-row {{ display:flex; gap:1rem; flex-wrap:wrap; }}

    /* BOTÃO AMAZON — laranja */
    .btn-amazon {{
      background: #FF9900; color: #111; font-family:'DM Sans',sans-serif;
      font-size:0.95rem; font-weight:700; padding:0.9rem 1.75rem; border-radius:14px;
      text-decoration:none; display:inline-flex; align-items:center; gap:0.5rem;
      transition:transform .15s, box-shadow .15s; flex-shrink:0;
    }}
    .btn-amazon:hover {{ transform:translateY(-2px); box-shadow:0 8px 24px rgba(255,153,0,0.4); }}

    /* BOTÃO BOOKING — azul */
    .btn-booking {{
      background: #003580; color: white; font-family:'DM Sans',sans-serif;
      font-size:0.95rem; font-weight:700; padding:0.9rem 1.75rem; border-radius:14px;
      text-decoration:none; display:inline-flex; align-items:center; gap:0.5rem;
      transition:transform .15s, box-shadow .15s; flex-shrink:0;
    }}
    .btn-booking:hover {{ transform:translateY(-2px); box-shadow:0 8px 24px rgba(0,53,128,0.4); }}

    /* BOTÃO PDF — ghost */
    .btn-ghost {{
      background:rgba(245,240,232,0.1); color:var(--cream); font-family:'DM Sans',sans-serif;
      font-size:0.95rem; font-weight:500; padding:0.9rem 1.75rem; border-radius:14px;
      border:1px solid rgba(245,240,232,0.2); cursor:pointer; display:inline-flex; align-items:center; gap:0.5rem;
      transition:background .2s; flex-shrink:0;
    }}
    .btn-ghost:hover {{ background:rgba(245,240,232,0.18); }}

    /* CARD DE HOTEL — azul escuro */
    .hotel-card {{
      background: #003580; border-radius:24px; padding:2.5rem; margin-bottom:2rem;
      display:flex; align-items:center; justify-content:space-between; gap:2rem; flex-wrap:wrap;
    }}
    .hotel-card h3 {{ font-family:'Playfair Display',serif; font-size:1.4rem; font-weight:700; color:white; margin-bottom:0.5rem; }}
    .hotel-card p {{ font-size:0.9rem; color:rgba(255,255,255,0.65); line-height:1.6; max-width:420px; }}

    /* CARD DE SEGURO — âmbar/ouro */
    .insurance-card {{
      background: linear-gradient(135deg, #92400e, #b45309);
      border-radius:24px; padding:2.5rem; margin-bottom:2rem;
      display:flex; align-items:center; justify-content:space-between; gap:2rem; flex-wrap:wrap;
    }}
    .insurance-card h3 {{ font-family:'Playfair Display',serif; font-size:1.4rem; font-weight:700; color:white; margin-bottom:0.5rem; }}
    .insurance-card p {{ font-size:0.9rem; color:rgba(255,255,255,0.75); line-height:1.6; max-width:420px; }}

    /* CARD AMAZON */
    .amazon-card {{
      background: #131921; border-radius:24px; padding:2.5rem; margin-bottom:2rem;
      display:flex; align-items:center; justify-content:space-between; gap:2rem; flex-wrap:wrap;
    }}
    .amazon-card h3 {{ font-family:'Playfair Display',serif; font-size:1.4rem; font-weight:700; color:white; margin-bottom:0.5rem; }}
    .amazon-card p {{ font-size:0.9rem; color:rgba(255,255,255,0.6); line-height:1.6; max-width:420px; }}

    /* BOTÃO SEGURO */
    .btn-insurance {{
      background: white; color: #92400e; font-family:'DM Sans',sans-serif;
      font-size:0.95rem; font-weight:700; padding:0.9rem 1.75rem; border-radius:14px;
      text-decoration:none; display:inline-flex; align-items:center; gap:0.5rem;
      transition:transform .15s, box-shadow .15s; flex-shrink:0; white-space:nowrap;
    }}
    .btn-insurance:hover {{ transform:translateY(-2px); box-shadow:0 8px 24px rgba(0,0,0,0.2); }}

    .disclaimer {{ margin-top:2rem; font-size:0.78rem; opacity:0.45; line-height:1.6; text-align:center; }}
    footer {{ z-index:1; position:relative; border-top:1px solid rgba(74,124,89,0.15); padding:2rem 3rem; text-align:center; font-size:0.78rem; opacity:0.45; }}

    @media print {{
      .no-print {{ display:none !important; }}
      nav {{ display:none; }}
      .hero {{ padding:2rem; }}
      .content {{ padding:1rem; }}
      body::before {{ display:none; }}
    }}
    @media (max-width:640px) {{
      nav {{ padding:1rem 1.5rem; }}
      .hero {{ padding:7rem 1.5rem 3rem; }}
      .content {{ padding:2rem 1.5rem; }}
      .route-display {{ gap:1rem; }}
      .country-flag {{ font-size:2.5rem; }}
      .btn-row {{ flex-direction:column; }}
    }}
  </style>
</head>
<body>

<nav class="no-print">
  <a href="../index.html" class="logo">Pet<span>Passport</span></a>
  <div class="breadcrumb">
    <a href="../index.html">Home</a> /
    <a href="#">{origin}</a> /
    <span>{origin} → {destination}</span>
  </div>
</nav>

<section class="hero">
  <div class="blob blob-1"></div>
  <div class="blob blob-2"></div>
  <div class="hero-inner">
    <a href="../index.html" class="back-link no-print">← Back to search</a>
    <div class="route-display">
      <div class="country-block">
        <span class="country-flag">{origin_flag}</span>
        <span class="country-name">{origin}</span>
      </div>
      <div class="route-arrow"><span>traveling</span>✈<span>with pet</span></div>
      <div class="country-block">
        <span class="country-flag">{dest_flag}</span>
        <span class="country-name">{destination}</span>
      </div>
    </div>
    <h1>Bringing your {animal.lower()} from {origin} to {destination} {animal_emoji}</h1>
    <div>
      <span class="meta-chip">🐾 {animal}</span>
      <span class="meta-chip">🌍 International route</span>
      <span class="meta-chip">✅ Requirements verified</span>
    </div>
  </div>
</section>

<main class="content">

  <!-- Requirements card -->
  <div class="card">
    <p class="card-label">Official import requirements</p>
    <h2>What you need to enter {destination} with a {animal.lower()}</h2>
    <ul class="check-list">
      {checklist}
    </ul>
  </div>

  <!-- Detailed checklist -->
  <div class="card">
    <p class="card-label">📋 Detailed checklist</p>
    <h2>Documentation & preparation</h2>
    <div style="font-size:0.95rem; line-height:1.7; color:#374151;">
      {detailed_html}
    </div>
  </div>

  <!-- WHERE TO STAY — Booking.com -->
  <div class="hotel-card no-print">
    <div>
      <p class="card-label" style="color:rgba(255,255,255,0.5);">🏨 Accommodation</p>
      <h3>Where to Stay</h3>
      <p>Traveling to {destination}? Search thousands of Pet-Friendly hotels and find the perfect place for you and your {animal.lower()}.</p>
    </div>
    <a href="{booking_url}" class="btn-booking" target="_blank" rel="noopener sponsored">
      🏨 Find Pet-Friendly Hotels in {destination}
    </a>
  </div>

  <!-- HEALTH & SAFETY — Insurance placeholder -->
  <div class="insurance-card no-print">
    <div>
      <p class="card-label" style="color:rgba(255,255,255,0.5);">🛡️ Health & Safety</p>
      <h3>Travel Insurance</h3>
      <p>Important: Travel insurance with pet coverage is required for this route. Make sure your {animal.lower()} is covered before departure.</p>
    </div>
    <a href="#" class="btn-insurance" target="_blank" rel="noopener sponsored">
      🛡️ Get a Quote
    </a>
  </div>

  <!-- SHOP ON AMAZON -->
  <div class="amazon-card no-print">
    <div>
      <p class="card-label" style="color:rgba(255,255,255,0.4);">🛒 Travel Essentials</p>
      <h3>Shop for Your Trip</h3>
      <p>Carriers, crates, travel bowls, health accessories — everything your {animal.lower()} needs, shipped from your local Amazon.</p>
    </div>
    <a href="{amazon_url}" class="btn-amazon" target="_blank" rel="noopener sponsored">
      🛒 Shop on Amazon
    </a>
  </div>

  <!-- PDF -->
  <div style="text-align:center; margin-bottom:2rem;" class="no-print">
    <button onclick="window.print()" class="btn-ghost" style="background:var(--forest); border:none; cursor:pointer;">
      📄 Save this guide as PDF
    </button>
  </div>

  <p class="disclaimer">
    ⚠️ Requirements change frequently. Always verify current rules with the official veterinary authority of {destination} before traveling. This page is for informational purposes only.
  </p>
</main>

<footer>© 2025 PetPassport · {origin} to {destination} · {animal} travel requirements</footer>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# GERADOR DE SITEMAP
# ══════════════════════════════════════════════════════════════════════════════
def generate_sitemap(slugs: list[str]):
    today = date.today().isoformat()
    urls = f"""  <url>
    <loc>{SITE_DOMAIN}/</loc>
    <lastmod>{today}</lastmod>
    <priority>1.0</priority>
  </url>\n"""

    for slug in slugs:
        urls += f"""  <url>
    <loc>{SITE_DOMAIN}/routes/{slug}.html</loc>
    <lastmod>{today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>\n"""

    sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls}</urlset>"""

    with open("sitemap.xml", "w", encoding="utf-8") as f:
        f.write(sitemap)
    print(f"🗺️  sitemap.xml gerado com {len(slugs) + 1} URLs.")


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-PUSH PARA O GITHUB
# ══════════════════════════════════════════════════════════════════════════════
import base64
import urllib.request
import urllib.error

# ─────────────────────────────────────────────────────────────────────────────
# ⚠️  COLE SEU NOVO TOKEN AQUI — nunca compartilhe com ninguém
GITHUB_TOKEN = "cole-seu-novo-token-aqui"
GITHUB_REPO  = "JsilvaM7/pet-travel-guide"    # usuário/repositório
GITHUB_BRANCH = "main"
# ─────────────────────────────────────────────────────────────────────────────

def _gh_request(method: str, path: str, body: dict | None = None):
    """Faz uma chamada à GitHub API."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {GITHUB_TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())

def _get_sha(filepath_in_repo: str) -> str | None:
    """Retorna o SHA do arquivo no GitHub (necessário para atualizar)."""
    res = _gh_request("GET", f"contents/{filepath_in_repo}?ref={GITHUB_BRANCH}")
    return res.get("sha")

def push_file(local_path: str, repo_path: str, commit_msg: str):
    """Envia um arquivo local para o GitHub (cria ou atualiza)."""
    with open(local_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    sha = _get_sha(repo_path)  # None se arquivo não existe ainda

    body = {
        "message": commit_msg,
        "content": content_b64,
        "branch":  GITHUB_BRANCH,
    }
    if sha:
        body["sha"] = sha

    res = _gh_request("PUT", f"contents/{repo_path}", body)

    if "content" in res:
        print(f"  ✅ GitHub: {repo_path}")
    else:
        print(f"  ⚠️  Erro em {repo_path}: {res.get('message', res)}")

def push_all_to_github(generated: list[str]):
    """Faz push de todos os arquivos gerados para o GitHub."""
    if GITHUB_TOKEN == "cole-seu-novo-token-aqui":
        print("\n⚠️  Token do GitHub não configurado. Pulando auto-push.")
        print("   Edite a linha GITHUB_TOKEN no script e rode novamente.")
        return

    print(f"\n🚀 Enviando arquivos para GitHub ({GITHUB_REPO})...")
    today = date.today().isoformat()
    commit = f"pSEO auto-update: {len(generated)} routes · {today}"

    # Arquivos da raiz
    for fname in ["routes.json", "sitemap.xml"]:
        if os.path.exists(fname):
            push_file(fname, fname, commit)

    # HTMLs das rotas
    for slug in generated:
        local = os.path.join(OUTPUT_DIR, f"{slug}.html")
        repo  = f"routes/{slug}.html"
        if os.path.exists(local):
            push_file(local, repo, commit)

    print(f"\n🎉 Push concluído! Acesse: https://{SITE_DOMAIN.replace('https://', '')}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    creds  = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet  = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
    rows   = sheet.get_all_records()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    generated = []

    for row in rows:
        origin      = str(row.get("Origin", "")).strip()
        destination = str(row.get("Destination", "")).strip()
        animal      = str(row.get("Animal", "")).strip()
        if not origin or not destination:
            continue

        slug        = (str(row.get("Slug", "")).strip() or build_slug(origin, destination, animal)).lower()
        amazon_url  = get_amazon_url(origin, animal)
        booking_url = get_booking_url(destination)

        html     = generate_html(row, slug, amazon_url, booking_url)
        filepath = os.path.join(OUTPUT_DIR, f"{slug}.html")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        generated.append(slug)
        print(f"✅ {filepath}  |  Amazon: {amazon_url[:50]}...")

    # routes.json
    with open("routes.json", "w", encoding="utf-8") as f:
        json.dump(generated, f, indent=2, ensure_ascii=False)
    print(f"\n📄 routes.json gerado com {len(generated)} rotas.")

    # sitemap.xml
    generate_sitemap(generated)

    print(f"\n🎉 {len(generated)} páginas geradas em ./{OUTPUT_DIR}/")

    # Auto-push para o GitHub
    push_all_to_github(generated)

if __name__ == "__main__":
    main()
