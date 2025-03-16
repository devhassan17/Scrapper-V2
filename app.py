from flask import Flask, render_template, send_file, redirect, url_for, request
import requests
import sqlite3
import xml.etree.ElementTree as ET
from fpdf import FPDF
import datetime
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
scheduler = BackgroundScheduler()

# List of sitemap sources
SITEMAP_SOURCES = {
    "bedrijvengidsen": "https://bedrijvengidsen-nederland.nl/sitemap_index.xml",
    "zorggids": "https://zorggids-nederland.nl/sitemap_index.xml",
    "bedrijvenpagina": "https://bedrijvenpagina-online.nl/sitemap_index.xml",
    "onderwijsgids": "https://onderwijsgids-nederland.nl/sitemap_index.xml",
}

# Function to extract sitemap URLs

def get_sitemap_urls(sitemap_url):
    response = requests.get(sitemap_url)
    if response.status_code != 200:
        print(f"Failed to fetch {sitemap_url}")
        return []
    root = ET.fromstring(response.content)
    namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    return [elem.text for elem in root.findall('.//ns:loc', namespaces)]

# Function to extract company URLs
def get_company_urls_ordered(sitemap_urls):
    def extract_number(url):
        parts = url.split("-sitemap")[-1].split(".xml")[0]
        return int(parts) if parts.isdigit() else float('inf')  # Assign non-numbered sitemaps the highest priority

    ordered_sitemaps = sorted(
        [url for url in sitemap_urls if "bedrijven-" in url],
        key=extract_number
    )

    company_urls = []
    for sitemap_url in ordered_sitemaps:
        print(f"Fetching: {sitemap_url}")
        company_urls.extend(get_sitemap_urls(sitemap_url))

    return [url for url in company_urls if "/bedrijven/" in url]

# Initialize database for each company
def setup_database():
    conn = sqlite3.connect("companies.db")
    cursor = conn.cursor()
    
    for company in SITEMAP_SOURCES.keys():
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {company} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE,
                scraped_at TEXT
            )
        """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS last_checked (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            new_count INTEGER
        )
    """)
    
    conn.commit()
    conn.close()

# Save company URLs to separate tables
def save_to_database(urls, table_name):
    conn = sqlite3.connect("companies.db")
    cursor = conn.cursor()
    new_records = []
    scraped_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for url in urls:
        try:
            cursor.execute(f"INSERT INTO {table_name} (url, scraped_at) VALUES (?, ?)", (url, scraped_at))
            new_records.append(url)
        except sqlite3.IntegrityError:
            pass  # Ignore duplicates
    cursor.execute("INSERT INTO last_checked (timestamp, new_count) VALUES (?, ?)", (scraped_at, len(new_records)))
    conn.commit()
    conn.close()
    return new_records

# Fetch companies for a given source
def fetch_companies(source):
    conn = sqlite3.connect("companies.db")
    cursor = conn.cursor()
    cursor.execute(f"SELECT id, url FROM {source} ORDER BY id DESC")
    companies = cursor.fetchall()
    conn.close()
    return companies

# Generate PDF report
def generate_pdf():
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, "Scraped Companies", ln=True, align='C')
    
    for source in SITEMAP_SOURCES.keys():
        pdf.cell(200, 10, f"{source.capitalize()} Companies", ln=True, align='L')
        companies = fetch_companies(source)
        for company in companies:
            pdf.cell(200, 10, company[1], ln=True)
    
    pdf.output("companies.pdf")
    return "companies.pdf"

@app.route('/')
def index():
    return render_template("index.html", sources=SITEMAP_SOURCES.keys())

@app.route('/companies/<source>')
def companies(source):
    companies = fetch_companies(source)
    return render_template("companies.html", companies=companies, source=source)

@app.route('/download')
def download():
    pdf_file = generate_pdf()
    return send_file(pdf_file, as_attachment=True)

@app.route('/fetch_new')
def fetch_new():
    return manual_fetch_new()

# Manual fetch
def manual_fetch_new():
    new_records_total = 0
    for name, url in SITEMAP_SOURCES.items():
        all_sitemap_urls = get_sitemap_urls(url)
        company_urls = get_company_urls_ordered(all_sitemap_urls)
        new_records = save_to_database(company_urls, name)
        new_records_total += len(new_records)
    return f"{new_records_total} new records added."

# Auto fetch
def auto_fetch():
    with app.app_context():
        print("Auto fetching new companies...")
        manual_fetch_new()

if __name__ == "__main__":
    setup_database()
    manual_fetch_new()
    scheduler.add_job(auto_fetch, "interval", hours=1)
    scheduler.start()
    app.run(debug=True)

