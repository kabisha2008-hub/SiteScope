import os
import re
import json
import csv
import io
import sqlite3
import secrets
import ipaddress
import socket
from collections import deque, Counter
from datetime import datetime
from urllib.parse import urlparse, urljoin, urldefrag, parse_qsl, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, abort, make_response
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "sitescope.db")
USER_AGENT = "SiteScopeSEOAnalyzer/2.1"
MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_MAX_PAGES = 30


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                results TEXT NOT NULL DEFAULT '[]',
                recommendations TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                audit_data TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(reports)")}
        if "audit_data" not in columns:
            db.execute("ALTER TABLE reports ADD COLUMN audit_data TEXT NOT NULL DEFAULT '{}'")


def safe_public_url(raw_url):
    raw_url = (raw_url or "").strip()
    if not raw_url:
        raise ValueError("Enter a website URL.")
    if "://" not in raw_url:
        raw_url = "https://" + raw_url
    parsed = urlparse(raw_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Enter a valid HTTP or HTTPS URL.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing embedded credentials are not allowed.")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise ValueError("Local URLs are not allowed.")
    try:
        addresses = socket.getaddrinfo(host, None)
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if not ip.is_global:
                raise ValueError("Private or local network addresses are not allowed.")
    except socket.gaierror:
        raise ValueError("The website hostname could not be resolved.")
    return raw_url


def fetch_page(url, timeout=(4, 12)):
    current = url
    for _ in range(5):
        current = safe_public_url(current)
        response = requests.get(
            current, timeout=timeout, allow_redirects=False,
            headers={"User-Agent": USER_AGENT}, stream=True
        )
        if response.is_redirect:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise ValueError("Website returned an invalid redirect.")
            current = urljoin(current, location)
            continue
        content = bytearray()
        try:
            for chunk in response.iter_content(chunk_size=8192):
                content.extend(chunk)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise ValueError("A page is too large to scan (2 MB limit).")
        finally:
            response.close()
        return current, response.status_code, response.headers, bytes(content)
    raise ValueError("Too many redirects.")


def normalized_url(raw_url):
    parsed = urlparse(raw_url)
    path = parsed.path or "/"
    # Keep query strings because they can identify distinct pages, but remove fragments.
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path,
                       parsed.params, parsed.query, ""))


def same_site(url, root_host):
    """Treat the apex domain and its www alias as one site.

    Other subdomains (for example, policies.example.com) are external by
    default. This keeps the crawl scope predictable and avoids false pages.
    """
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    root = (root_host or "").lower().rstrip(".")
    root = root.removeprefix("www.")
    return host in {root, "www." + root}


def extract_page_data(url, status, headers, content, root_host):
    soup = BeautifulSoup(content, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    description = description_tag.get("content", "").strip() if description_tag else ""
    h1s = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    h2_count = len(soup.find_all("h2"))
    images = soup.find_all("img")
    missing_alt = sum(1 for image in images if not image.has_attr("alt"))
    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in (value if isinstance(value, (list, tuple)) else str(value).lower().split()))
    canonical = urljoin(url, canonical_tag.get("href", "")) if canonical_tag and canonical_tag.get("href") else ""
    robots_tags = soup.find_all("meta", attrs={"name": re.compile(r"^(robots|googlebot|bingbot)$", re.I)})
    robots_content = " ".join(tag.get("content", "") for tag in robots_tags).lower()
    x_robots = headers.get("X-Robots-Tag", "").lower()
    links = []
    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        absolute = normalized_url(urljoin(url, href))
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        anchor_text = tag.get_text(" ", strip=True)
        if not anchor_text:
            anchor_text = (tag.get("aria-label") or tag.get("title") or "").strip()
        if not anchor_text:
            image = tag.find("img", alt=True)
            if image:
                anchor_text = (image.get("alt") or "").strip()
        rel_values = tag.get("rel") or []
        if isinstance(rel_values, str):
            rel_values = rel_values.split()
        links.append({
            "url": absolute,
            "anchor": anchor_text[:140],
            "nofollow": "nofollow" in [str(value).lower() for value in rel_values]
        })
    text = soup.get_text(" ", strip=True)
    words = re.findall(r"\b[\w'-]+\b", text)
    h1_positions = [int(h.name[1]) for h in soup.find_all(re.compile(r"^h[1-6]$"))]
    heading_jump = any(b - a > 1 for a, b in zip(h1_positions, h1_positions[1:]))
    og_title = soup.find("meta", property="og:title")
    og_description = soup.find("meta", property="og:description")
    twitter_card = soup.find("meta", attrs={"name": "twitter:card"})
    json_ld = soup.find_all("script", type="application/ld+json")
    hreflang = soup.find_all("link", rel=lambda value: value and "alternate" in value,
                             hreflang=True)
    viewport_tag = soup.find(
        "meta", attrs={"name": re.compile(r"^viewport$", re.I)}
    )
    return {
        "url": url, "status": status, "title": title, "description": description,
        "title_length": len(title), "description_length": len(description),
        "h1_count": len(h1s), "h1": h1s[:3], "h2_count": h2_count,
        "images": len(images), "missing_alt": missing_alt,
        "canonical": canonical, "canonical_count": len(soup.find_all("link", rel=lambda value: value and "canonical" in (value if isinstance(value, (list, tuple)) else str(value).lower().split()))), "noindex": bool(re.search(r"(^|[,;\s])noindex([,;\s]|$)", robots_content + " " + x_robots)),
        "word_count": len(words), "links": links,
        "internal_links": sum(1 for link in links if same_site(link["url"], root_host)),
        "external_links": sum(1 for link in links if not same_site(link["url"], root_host)),
        "nofollow_links": sum(1 for link in links if link["nofollow"]),
        "heading_jump": heading_jump,
        "og_title": bool(og_title and og_title.get("content", "").strip()),
        "og_description": bool(og_description and og_description.get("content", "").strip()),
        "twitter_card": bool(twitter_card and twitter_card.get("content", "").strip()),
        "structured_data": len(json_ld),
        "hreflang_count": len(hreflang),
        "viewport": bool(viewport_tag),
    }


def fetch_text_file(url):
    """Fetch a text/XML resource; return empty text when unavailable."""
    try:
        final_url, status, headers, content = fetch_page(url)
        if status == 200:
            return content.decode("utf-8", errors="replace")
    except (ValueError, requests.RequestException):
        pass
    return ""


def parse_sitemap_xml(xml_text):
    """Accept only valid sitemap urlset or sitemapindex XML documents."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, ValueError):
        return "", []
    kind = root.tag.rsplit("}", 1)[-1].lower()
    if kind not in {"urlset", "sitemapindex"}:
        return "", []
    locs = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() == "loc" and node.text:
            loc = node.text.strip()
            if loc:
                locs.append(loc)
    return kind, locs


def crawl_site(start_url, max_pages=DEFAULT_MAX_PAGES):
    start_url = safe_public_url(start_url)
    parsed = urlparse(start_url)
    root_host = (parsed.hostname or "").lower()
    start_url = normalized_url(start_url)
    root_origin = f"{parsed.scheme}://{parsed.netloc}"

    robots_text = fetch_text_file(urljoin(root_origin, "/robots.txt"))
    robots_found = bool(robots_text.strip()) and not robots_text.lstrip().lower().startswith(("<!doctype html", "<html"))
    sitemap_urls = re.findall(r"(?im)^\s*Sitemap:\s*(\S+)", robots_text)
    if not sitemap_urls:
        sitemap_urls = [
            urljoin(root_origin, "/sitemap.xml"),
            urljoin(root_origin, "/sitemap_index.xml")
        ]

    sitemap_found = False
    sitemap_page_urls = []
    sitemap_queue = deque(sitemap_urls[:5])
    checked_sitemaps = set()

    while sitemap_queue and len(checked_sitemaps) < 10:
        sitemap_url = sitemap_queue.popleft()
        try:
            sitemap_url = normalized_url(safe_public_url(sitemap_url))
        except ValueError:
            continue
        if sitemap_url in checked_sitemaps:
            continue
        checked_sitemaps.add(sitemap_url)
        sitemap_text = fetch_text_file(sitemap_url)
        if not sitemap_text:
            continue
        kind, locations = parse_sitemap_xml(sitemap_text)
        if not kind:
            continue
        sitemap_found = True
        if kind == "sitemapindex":
            for child in locations:
                if len(sitemap_queue) + len(checked_sitemaps) < 10:
                    sitemap_queue.append(child)
        else:
            sitemap_page_urls.extend(locations)

    queue = deque([start_url])
    seeded = 0
    for sitemap_page in sitemap_page_urls:
        if seeded >= max_pages:
            break
        try:
            candidate = normalized_url(safe_public_url(sitemap_page))
            if same_site(candidate, root_host):
                queue.append(candidate)
                seeded += 1
        except ValueError:
            continue

    seen, crawled_urls = set(), set()
    pages, errors = [], []
    while queue and len(pages) < max_pages:
        target = normalized_url(queue.popleft())
        if target in seen:
            continue
        seen.add(target)
        if not same_site(target, root_host):
            continue
        try:
            final_url, status, headers, content = fetch_page(target)
            final_url = normalized_url(final_url)
            if not same_site(final_url, root_host):
                errors.append({"url": target, "error": "Redirected outside the selected site scope."})
                continue
            if final_url in crawled_urls:
                continue
            crawled_urls.add(final_url)
            page = extract_page_data(final_url, status, headers, content, root_host)
            pages.append(page)
            if status < 400:
                for link in page["links"]:
                    linked = link["url"]
                    if same_site(linked, root_host) and linked not in seen and len(seen) + len(queue) < max_pages * 4:
                        queue.append(linked)
        except (ValueError, requests.RequestException) as error:
            errors.append({"url": target, "error": str(error)[:180]})

    return {
        "pages": pages, "errors": errors,
        "robots_found": robots_found,
        "robots_preview": robots_text[:1200],
        "sitemap_found": sitemap_found,
        "sitemap_urls": len(set(sitemap_page_urls)),
        "max_pages": max_pages, "root_host": root_host
    }


def verify_internal_links(links, root_host, already_crawled, limit=25):
    """Verify a bounded sample of unique internal URLs outside the crawl inventory."""
    candidates, seen = [], set()
    for link in links:
        target = link["url"]
        if not same_site(target, root_host) or target in already_crawled or target in seen:
            continue
        seen.add(target)
        candidates.append(target)

    checked, broken, unverified = [], [], []
    for target in candidates[:limit]:
        try:
            final_url, status, headers, content = fetch_page(target, timeout=(3, 5))
            item = {"url": target, "final_url": final_url, "status": status}
            checked.append(item)
            if status >= 400:
                broken.append(item)
        except (ValueError, requests.RequestException) as error:
            unverified.append({"url": target, "error": str(error)[:140]})

    return {
        "checked": checked, "broken": broken, "unverified": unverified,
        "not_checked": max(0, len(candidates) - min(len(candidates), limit))
    }


def audit_website(url, max_pages=DEFAULT_MAX_PAGES):
    crawl = crawl_site(url, max_pages)
    pages = crawl["pages"]
    if not pages:
        raise ValueError("No pages could be crawled. Check the URL or website access settings.")

    home = pages[0]
    results = []

    def add(name, passed, detail):
        results.append({
            "name": name, "status": "pass" if passed else "warning",
            "passed": bool(passed), "detail": detail
        })

    add("Homepage HTTP status", home["status"] == 200,
        f"Homepage returned HTTP {home['status']}.")
    add("HTTPS", home["url"].startswith("https://"),
        "Website uses HTTPS." if home["url"].startswith("https://") else "Use HTTPS to secure the website.")
    add("Page title", bool(home["title"]), f"Title: {home['title'] or 'Missing'}.")
    add("Title length", 30 <= home["title_length"] <= 60,
        f"Homepage title contains {home['title_length']} characters; use roughly 30–60 as a guideline.")
    add("Meta description", bool(home["description"]),
        f"Meta description contains {home['description_length']} characters." if home["description"] else "Add a unique meta description.")
    add("Description length", 120 <= home["description_length"] <= 160,
        f"Homepage description contains {home['description_length']} characters; roughly 120–160 is a guideline.")
    add("H1 heading", home["h1_count"] == 1,
        f"Found {home['h1_count']} H1 headings; use one clear primary heading.")
    add("Image alt text", home["missing_alt"] == 0,
        f"{home['missing_alt']} of {home['images']} homepage images are missing an alt attribute.")
    add("Canonical URL", bool(home["canonical"]),
        "Canonical URL found." if home["canonical"] else "No canonical link element was detected.")
    add("Mobile viewport", home["viewport"],
        "Viewport meta tag found." if home["viewport"] else "Add a mobile viewport meta tag.")
    add("Indexability", not home["noindex"],
        "No noindex directive detected." if not home["noindex"] else "A noindex directive was detected on the homepage.")
    add("Robots.txt", crawl["robots_found"],
        "A non-empty robots.txt file was found." if crawl["robots_found"] else "robots.txt was not found or returned an empty response.")
    add("XML sitemap", crawl["sitemap_found"],
        f"Valid XML sitemap detected with {crawl['sitemap_urls']} listed URL(s)." if crawl["sitemap_found"] else "No valid XML sitemap was detected at the declared or common sitemap paths.")
    add("Open Graph metadata", home["og_title"] and home["og_description"],
        "Open Graph title and description found." if home["og_title"] and home["og_description"] else "Add og:title and og:description for better social sharing previews.")
    add("Twitter card", home["twitter_card"],
        "Twitter card metadata found." if home["twitter_card"] else "Consider adding a twitter:card metadata tag.")
    add("Structured data", home["structured_data"] > 0,
        f"Found {home['structured_data']} JSON-LD block(s)." if home["structured_data"] else "No JSON-LD structured data detected; add relevant schema where appropriate.")
    add("Heading hierarchy", not home["heading_jump"],
        "No skipped heading levels detected on the homepage." if not home["heading_jump"] else "Review heading levels; avoid jumping over levels (for example H2 to H4).")

    inbound = Counter()
    broken = []
    anchorless = 0
    internal_total = external_total = nofollow_total = 0
    all_internal_links = []
    page_map = {p["url"]: p for p in pages}

    for page in pages:
        for link in page["links"]:
            if same_site(link["url"], crawl["root_host"]):
                internal_total += 1
                all_internal_links.append(link)
                inbound[link["url"]] += 1
                if not link["anchor"]:
                    anchorless += 1
                target_page = page_map.get(link["url"])
                if target_page and target_page["status"] >= 400:
                    broken.append({
                        "url": link["url"], "final_url": link["url"],
                        "status": target_page["status"], "source": page["url"]
                    })
            else:
                external_total += 1
            if link["nofollow"]:
                nofollow_total += 1

    crawled_destinations = set(page_map)
    verification = verify_internal_links(
        all_internal_links, crawl["root_host"], crawled_destinations, limit=25
    )
    known_broken_urls = {item["url"] for item in broken}
    for item in verification["broken"]:
        if item["url"] not in known_broken_urls:
            broken.append(item)
            known_broken_urls.add(item["url"])

    title_counts = Counter(p["title"].strip().lower() for p in pages if p["title"].strip())
    duplicate_titles = [title for title, count in title_counts.items() if count > 1]
    missing_titles = sum(1 for p in pages if not p["title"])
    missing_descriptions = sum(1 for p in pages if not p["description"])
    missing_h1 = sum(1 for p in pages if p["h1_count"] == 0)
    multi_h1 = sum(1 for p in pages if p["h1_count"] > 1)
    noindex_pages = sum(1 for p in pages if p["noindex"])
    thin_pages = [p for p in pages if p["word_count"] < 100]
    orphan_candidates = [
        p["url"] for p in pages
        if p["url"] != home["url"] and inbound[p["url"]] == 0
    ]

    add("Internal linking", internal_total > 0,
        f"Found {internal_total} internal link occurrence(s) across {len(pages)} crawled page(s).")
    broken_detail = (
        f"Found {len(broken)} broken internal destination(s) with HTTP errors."
        if broken else
        f"No broken internal links found in {len(verification['checked'])} additional sampled destinations and the crawled pages."
    )
    if verification["not_checked"] or verification["unverified"]:
        broken_detail += (
            f" {verification['not_checked']} destination(s) were not checked due to the sample limit; "
            f"{len(verification['unverified'])} could not be verified."
        )
    add("Broken internal links", len(broken) == 0, broken_detail)
    add("Unique page titles", not duplicate_titles,
        "No duplicate page titles detected in the crawl." if not duplicate_titles else f"Found {len(duplicate_titles)} duplicate title value(s).")
    add("Page descriptions", missing_descriptions == 0,
        f"{missing_descriptions} of {len(pages)} crawled pages are missing meta descriptions.")
    add("Page H1 coverage", missing_h1 == 0 and multi_h1 == 0,
        f"{missing_h1} page(s) have no H1 and {multi_h1} page(s) have multiple H1 headings. Multiple H1s are a review suggestion, not automatically a search penalty.")
    add("Orphan page candidates", not orphan_candidates,
        "No orphan candidates found within the crawl." if not orphan_candidates else f"Found {len(orphan_candidates)} crawled page(s) with no inbound internal links; verify these as possible orphan pages.")
    add("Thin content candidates", not thin_pages,
        "No pages under 100 words detected." if not thin_pages else f"Found {len(thin_pages)} page(s) with fewer than 100 words; review whether they satisfy search intent.")

    # Weighted in-house score: critical crawl/indexability checks count more than optional enhancements.
    weights = {
        "Homepage HTTP status": 8, "HTTPS": 5, "Page title": 6,
        "Title length": 3, "Meta description": 5, "Description length": 2,
        "H1 heading": 4, "Image alt text": 4, "Canonical URL": 3,
        "Mobile viewport": 5, "Indexability": 8, "Robots.txt": 2,
        "XML sitemap": 3, "Open Graph metadata": 1, "Twitter card": 1,
        "Structured data": 2, "Heading hierarchy": 2, "Internal linking": 5,
        "Broken internal links": 8, "Unique page titles": 4,
        "Page descriptions": 5, "Page H1 coverage": 4,
        "Orphan page candidates": 2, "Thin content candidates": 2
    }
    total_weight = sum(weights.get(item["name"], 1) for item in results)
    score = round(
        sum(weights.get(item["name"], 1) for item in results if item["passed"])
        / max(total_weight, 1) * 100
    )
    recommendations = [item["detail"] for item in results if not item["passed"]]

    page_rows = []
    for page in pages:
        page_rows.append({
            "url": page["url"], "status": page["status"], "title": page["title"],
            "word_count": page["word_count"], "internal_links": page["internal_links"],
            "external_links": page["external_links"], "images": page["images"],
            "missing_alt": page["missing_alt"], "inbound_links": inbound[page["url"]],
            "noindex": page["noindex"]
        })

    audit_data = {
        "pages_crawled": len(pages), "pages_limit": max_pages,
        "internal_links": internal_total, "external_links": external_total,
        "nofollow_links": nofollow_total, "broken_links": broken,
        "broken_links_checked": len(verification["checked"]),
        "broken_links_unverified": len(verification["unverified"]),
        "broken_links_not_checked": verification["not_checked"],
        "anchorless_links": anchorless, "orphan_candidates": orphan_candidates,
        "duplicate_titles": duplicate_titles, "missing_titles": missing_titles,
        "missing_descriptions": missing_descriptions, "noindex_pages": noindex_pages,
        "thin_pages": [{"url": p["url"], "word_count": p["word_count"]} for p in thin_pages],
        "crawl_errors": crawl["errors"], "robots_found": crawl["robots_found"],
        "sitemap_found": crawl["sitemap_found"], "sitemap_urls": crawl["sitemap_urls"],
        "page_rows": page_rows,
        "note": (
            "The score is SiteScope's weighted estimate, not a Google ranking score. "
            "A crawl is limited to the selected page cap. Broken-link checks include crawled "
            "destinations plus a bounded sample of up to 25 additional internal destinations; "
            "remaining links may be unverified. Orphan results are candidates based only on "
            "inbound links found within this crawl. Internal scope includes the apex domain "
            "and www alias; other subdomains are treated as external."
        )
    }
    return home["url"], score, results, recommendations, audit_data


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 8:
            flash("Enter your name, a valid email, and a password of at least 8 characters.", "error")
            return redirect(url_for("register"))
        try:
            with get_db() as db:
                db.execute("INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
                           (name, email, generate_password_hash(password)))
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("That email is already registered.", "error")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))
        flash("Incorrect email or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
    with get_db() as db:
        reports = db.execute("SELECT * FROM reports WHERE user_id = ? ORDER BY id DESC",
                             (session["user_id"],)).fetchall()
    scores = [report["score"] for report in reports]
    return render_template("dashboard.html",
                           user={"name": session.get("user_name", "User")},
                           reports=reports, total=len(reports),
                           average_score=round(sum(scores) / len(scores)) if scores else 0)


@app.route("/analyze", methods=["POST"])
def analyze():
    if "user_id" not in session:
        return redirect(url_for("login"))
    url = request.form.get("url", "").strip()
    try:
        max_pages = int(request.form.get("max_pages", DEFAULT_MAX_PAGES))
        max_pages = max(1, min(max_pages, 100))
        final_url, score, results, recommendations, audit_data = audit_website(url, max_pages)
        with get_db() as db:
            cursor = db.execute("""
                INSERT INTO reports
                (user_id, url, score, results, recommendations, created_at, audit_data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (session["user_id"], final_url, score, json.dumps(results),
                  json.dumps(recommendations), datetime.now().strftime("%Y-%m-%d %H:%M"),
                  json.dumps(audit_data)))
            report_id = cursor.lastrowid
        flash("Website crawl and SEO audit completed.", "success")
        return redirect(url_for("view_report", report_id=report_id))
    except (ValueError, requests.RequestException) as error:
        flash(str(error) or "Unable to scan this website.", "error")
    except Exception:
        app.logger.exception("Website audit failed")
        flash("The audit failed. Please check the URL and try again.", "error")
    return redirect(url_for("dashboard"))


@app.route("/report/<int:report_id>")
def view_report(report_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    with get_db() as db:
        report = db.execute("SELECT * FROM reports WHERE id = ? AND user_id = ?",
                            (report_id, session["user_id"])).fetchone()
    if not report:
        abort(404)
    results = json.loads(report["results"] or "[]")
    recommendations = json.loads(report["recommendations"] or "[]")
    try:
        audit_data = json.loads(report["audit_data"] or "{}")
    except (TypeError, json.JSONDecodeError):
        audit_data = {}
    return render_template("report.html", report=report, results=results,
                           recommendations=recommendations, audit_data=audit_data)


@app.route("/report/<int:report_id>/export.csv")
def export_report(report_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    with get_db() as db:
        report = db.execute("SELECT * FROM reports WHERE id = ? AND user_id = ?",
                            (report_id, session["user_id"])).fetchone()
    if not report:
        abort(404)
    data = json.loads(report["audit_data"] or "{}")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["URL", "HTTP status", "Title", "Word count", "Inbound internal links",
                     "Internal links", "External links", "Images", "Images missing alt", "Noindex"])
    for page in data.get("page_rows", []):
        writer.writerow([page.get("url"), page.get("status"), page.get("title"),
                         page.get("word_count"), page.get("inbound_links"),
                         page.get("internal_links"), page.get("external_links"),
                         page.get("images"), page.get("missing_alt"), page.get("noindex")])
    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="sitescope-report-{report_id}.csv"'
    return response


@app.route("/delete-report/<int:report_id>", methods=["POST"])
def delete_report(report_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    with get_db() as db:
        db.execute("DELETE FROM reports WHERE id = ? AND user_id = ?",
                   (report_id, session["user_id"]))
    flash("Report deleted.", "success")
    return redirect(url_for("dashboard"))


init_db()
if __name__ == "__main__":
    app.run(debug=True)
