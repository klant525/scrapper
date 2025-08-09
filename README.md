SCRAPPER_fixed - fixed project scaffold
======================================

Structure:
- crawler/: Flask app that scrapes Google Maps and POSTs records to blockchain API
  - app.py (run: python app.py)
  - templates/index.html (frontend with AJAX)
- blockchain_scrapper/: Blockchain API (Flask)
  - app_blockchain.py (run: python app_blockchain.py)
  - blockchain.py (blockchain implementation)
  - blockchain_data.json (sample)
- data/: output CSV goes here
- requirements.txt

Quick start (on your laptop):
1) Create venv and activate:
   python -m venv .venv
   .\.venv\Scripts\activate  (Windows PowerShell: .\.venv\Scripts\Activate.ps1)
2) Install deps:
   pip install -r requirements.txt
3) Start blockchain API:
   cd blockchain_scrapper
   python app_blockchain.py
4) In another terminal start scraper app:
   cd crawler
   python app.py
5) Open browser to: http://127.0.0.1:8080

Notes:
- If you want crawler to send records to blockchain on LAN use environment variable:
  set BLOCKCHAIN_API=http://192.168.0.105:5000/add
- Selenium will download ChromeDriver automatically (webdriver-manager). Ensure Chrome is installed.
