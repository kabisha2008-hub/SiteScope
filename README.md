# SiteScope – Website SEO Analyzer

SiteScope is a Flask-based web application designed to analyze websites and identify SEO-related issues through automated website crawling and SEO audits.

## Features

- Website crawling and SEO analysis
- SEO health score with weighted checks
- Page title and meta description analysis
- Heading structure analysis (H1, H2)
- Image ALT attribute checking
- Canonical URL analysis
- Robots.txt and XML sitemap detection
- Internal and external link analysis
- Broken internal link sampling
- Orphan page candidate identification
- Duplicate title detection
- Thin content identification
- SEO audit reports
- User registration and login
- Dashboard to manage reports
- CSV report export

## Technologies Used

- Python
- Flask
- HTML
- CSS
- JavaScript
- SQLite
- BeautifulSoup
- Requests

## Installation and Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/kabisha2008-hub/SiteScope.git
   ```

2. Open the project folder:

   ```bash
   cd SiteScope
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Run the application:

   ```bash
   python app.py
   ```

5. Open your browser and visit:

   `http://127.0.0.1:5000/`

## Project Structure

```text
SiteScope/
│
├── static/
├── templates/
├── app.py
├── requirements.txt
├── README.md
└── .gitignore
```

## Important Note

SEO scores are estimates based on the checks performed by SiteScope. Broken-link analysis may use sampling and does not guarantee that every link has been verified.

## Developer

**Kabisha Nattudurai**

GitHub: https://github.com/kabisha2008-hub

---

*SiteScope – Making Website SEO Analysis Easier.*
