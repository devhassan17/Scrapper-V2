from flask import Flask, render_template, send_file, jsonify, request, redirect, url_for , session
import sqlite3
import xml.etree.ElementTree as ET
from fpdf import FPDF
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import aiohttp
import asyncio
import certifi
import ssl
from datetime import timedelta
import re  # For regex parsing

app = Flask(__name__)
app.secret_key = "Qwerty123!@#" 
app.permanent_session_lifetime = timedelta(days=1) 
scheduler = BackgroundScheduler()

USERNAME = "Justin"
PASSWORD = "Justin123!@#Scrapper"

# List of sitemap sources
SITEMAP_SOURCES = {
    "zorggids": "https://zorggids-nederland.nl/sitemap_index.xml",
    "bedrijvengidsen": "https://bedrijvengidsen-nederland.nl/sitemap_index.xml",
    "bedrijvenpagina": "https://bedrijvenpagina-online.nl/sitemap_index.xml",
    "onderwijsgids": "https://onderwijsgids-nederland.nl/sitemap_index.xml",
}

# Function to extract sitemap URLs asynchronously
async def get_sitemap_urls(sitemap_url):
    # Use certifi's certificate bundle
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.get(sitemap_url) as response:
            if response.status != 200:
                print(f"Failed to fetch {sitemap_url} (Status: {response.status})")
                return []
            content = await response.text()
            root = ET.fromstring(content)
            namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            return [elem.text for elem in root.findall('.//ns:loc', namespaces)]

# Function to extract company URLs asynchronously
async def get_company_urls_ordered(sitemap_urls):
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
        urls = await get_sitemap_urls(sitemap_url)
        company_urls.extend(urls)

    return [url for url in company_urls if "/bedrijven/" in url]

# Asynchronous function to check for the presence of an image with the class 'swiper-slide-image'
async def check_image_presence(session, url):
    try:
        # Use certifi's certificate bundle
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        async with session.get(url, ssl=ssl_context) as response:
            if response.status == 200:
                content = await response.text()
                # Use regex to check for the presence of the image class
                if re.search(r'<img[^>]*class="[^"]*\bswiper-slide-image\b[^"]*"', content):
                    return (url, 1)  # Verified
                else:
                    return (url, 0)  # Not Verified
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return (url, 0)  # Not Verified in case of any error

# Function to check if user is logged in
def is_logged_in():
    return session.get("logged_in")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username == USERNAME and password == PASSWORD:
            session.permanent = True  # Enables session lifetime tracking
            session["logged_in"] = True
            return redirect(url_for("index"))
        else:
            return "Invalid credentials, try again!"

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# Protect all existing routes
def login_required(func):
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper

# Initialize database for each company
def setup_database():
    conn = sqlite3.connect("companies.db")
    cursor = conn.cursor()
    
    for company in SITEMAP_SOURCES.keys():
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {company} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE,
                scraped_at TEXT,
                verified INTEGER DEFAULT 0  -- 0 for Not Verified, 1 for Verified
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
            cursor.execute(f"INSERT INTO {table_name} (url, scraped_at, verified) VALUES (?, ?, ?)", (url, scraped_at, 0))  # Default status: Not Verified
            new_records.append(url)
        except sqlite3.IntegrityError:
            pass  # Ignore duplicates
    cursor.execute("INSERT INTO last_checked (timestamp, new_count) VALUES (?, ?)", (scraped_at, len(new_records)))
    conn.commit()
    conn.close()
    return new_records

# Fetch companies for a given source
def fetch_companies(source, status="all"):
    conn = sqlite3.connect("companies.db")
    cursor = conn.cursor()
    if status == "verified":
        cursor.execute(f"SELECT id, url, verified FROM {source} WHERE verified = 1 ORDER BY id DESC")
    elif status == "not_verified":
        cursor.execute(f"SELECT id, url, verified FROM {source} WHERE verified = 0 ORDER BY id DESC")
    else:
        cursor.execute(f"SELECT id, url, verified FROM {source} ORDER BY id DESC")
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
            pdf.cell(200, 10, f"{company[1]} - {'Verified' if company[2] else 'Not Verified'}", ln=True)
    
    pdf.output("companies.pdf")
    return "companies.pdf"

@app.route('/')
@login_required
def index():
    return render_template("index.html", sources=SITEMAP_SOURCES.keys())

@app.route('/companies/<source>')
@login_required
def companies(source):
    companies = fetch_companies(source)
    return render_template("companies.html", companies=companies, source=source)

@app.route('/filter_companies/<source>/<status>')
@login_required
def filter_companies(source, status):
    companies = fetch_companies(source, status)
    return render_template("companies.html", companies=companies, source=source, filter_status=status)

@app.route('/download')
@login_required
def download():
    pdf_file = generate_pdf()
    return send_file(pdf_file, as_attachment=True)

@app.route('/start_filtering/<source>')
@login_required
async def start_filtering(source):
    print(f"Filtering started for source: {source}")  # Log when filtering starts
    companies = fetch_companies(source)  # Fetch all companies
    print(f"Total companies to process: {len(companies)}")  # Log the number of companies

    async with aiohttp.ClientSession() as session:
        tasks = []
        for company in companies:
            url = company[1]
            tasks.append(check_image_presence(session, url))
        
        results = await asyncio.gather(*tasks)
        
        for url, status in results:
            update_company_status(source, url, status)
            print(f"Processed: {url} - {'Verified' if status == 1 else 'Not Verified'}")  # Log each URL's status
    
    print(f"Filtering completed for source: {source}")  # Log when filtering is done
    return jsonify({"message": "Filtering process completed!"})

def update_company_status(source, url, status):
    conn = sqlite3.connect("companies.db")
    cursor = conn.cursor()
    cursor.execute(f"UPDATE {source} SET verified = ? WHERE url = ?", (status, url))
    conn.commit()
    conn.close()

# Automatically fetch URLs from sitemap on app start
async def fetch_urls_on_start():
    for source, sitemap_url in SITEMAP_SOURCES.items():
        print(f"Fetching URLs for {source}...")
        sitemap_urls = await get_sitemap_urls(sitemap_url)
        company_urls = await get_company_urls_ordered(sitemap_urls)
        save_to_database(company_urls, source)
        print(f"Saved {len(company_urls)} URLs for {source}.")

# Function to check for new URLs in sitemap
async def check_for_new_urls():
    print("Checking for new URLs in sitemaps...")
    for source, sitemap_url in SITEMAP_SOURCES.items():
        print(f"Checking {source}...")
        sitemap_urls = await get_sitemap_urls(sitemap_url)
        company_urls = await get_company_urls_ordered(sitemap_urls)
        new_urls = save_to_database(company_urls, source)
        if new_urls:
            print(f"New URLs found for {source}: {len(new_urls)}")
        else:
            print(f"No new URLs found for {source}.")

# Schedule the task to check for new URLs every week

@app.route('/update_status', methods=['POST'])
@login_required
def update_status():
    # Get form data
    source = request.form.get('source')
    company_id = request.form.get('id')
    new_status = request.form.get('status')

    if not all([source, company_id, new_status]):
        return jsonify({"error": "Missing required fields"}), 400

    conn = sqlite3.connect("companies.db")
    cursor = conn.cursor()
    cursor.execute(f"UPDATE {source} SET verified = ? WHERE id = ?", (new_status, company_id))
    conn.commit()
    conn.close()

    # Redirect back to the companies page
    return redirect(url_for('companies', source=source))


@app.route('/new_records')
@login_required
def new_records():
    new_records = []
    for source in SITEMAP_SOURCES.keys():
        conn = sqlite3.connect("companies.db")
        cursor = conn.cursor()
        cursor.execute(f"SELECT url FROM {source} WHERE scraped_at >= datetime('now', '-7 days')")
        new_records.extend([row[0] for row in cursor.fetchall()])
        conn.close()
    return render_template("new_records.html", new_records=new_records, count=len(new_records))

@app.route('/fetch_new_urls')
@login_required
async def fetch_new_urls():
    new_urls = await check_for_new_urls()  # Trigger function to check for new URLs
    
    if new_urls:  # Agar naye URLs mil gaye
        return {"message": "New records successfully added"}  # Sirf tab message return hoga
    else: 
         return {"message": "No new records found"}  
      # Agar koi naya record nahi mila, to empty JSON response


if __name__ == "__main__":
    setup_database()
    asyncio.run(fetch_urls_on_start())  # Fetch URLs on app start
    scheduler.add_job(check_for_new_urls, 'interval', weeks=1)
    scheduler.start()
    app.run(debug=True)