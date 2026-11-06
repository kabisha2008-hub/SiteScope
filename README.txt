SITESCOPE ADVANCED SEO ANALYZER

1. Install Python 3.10+.
2. Open a terminal in this folder.
3. Run: pip install -r requirements.txt
4. Run: python app.py
5. Open: http://127.0.0.1:5000

Existing SQLite data is preserved when the updated app starts. The app adds an audit_data column automatically.

New capabilities:
- Same-domain website crawler (10/30/50/100 page options)
- Internal and external link counts
- Inbound internal link counts and orphan-page candidates
- Confirmed broken internal links when destination pages are crawled
- Duplicate titles, missing descriptions/H1, thin-content candidates
- robots.txt and XML sitemap discovery
- Open Graph, Twitter card, JSON-LD, hreflang checks
- Heading hierarchy, word count, noindex and image-alt checks
- CSV export for crawled page inventory

Crawl limitations: this is a lightweight HTML crawler, not a full browser renderer. JavaScript-rendered links may not be discovered. Broken links are confirmed only for destination URLs included in the crawl. The page cap is limited to 100. Use only on websites you are authorized to inspect.
