import os, time, csv, requests
from flask import Flask, render_template, request, jsonify, send_file
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

BASE_DIR = os.path.dirname(__file__)
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))

# Config blockchain API
BLOCKCHAIN_API = os.environ.get('BLOCKCHAIN_API', 'http://127.0.0.1:5000/add')

def get_text_by_xpath(driver, xpath, default='Không có dữ liệu'):
    try:
        element = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.XPATH, xpath)))
        return element.text.strip()
    except:
        return default

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    search_key = request.form.get('search_key', '')
    num_results = int(request.form.get('num_results', '10') or 10)
    lat = request.form.get('lat')
    lng = request.form.get('lng')

    keyword = search_key.replace(' ', '+')

    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    # Nếu có tọa độ thì giới hạn khu vực tìm kiếm
    if lat and lng:
        crawl_url = f'https://www.google.com/maps/search/{keyword}/@{lat},{lng},14z'
    else:
        crawl_url = f'https://www.google.com/maps/search/{keyword}'

    driver.get(crawl_url)
    time.sleep(4)

    # Cuộn lấy đủ kết quả
    places = []
    scroll_attempts = 0
    while len(places) < num_results and scroll_attempts < 25:
        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.END)
        time.sleep(1.5)
        list_result = driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc')
        places = list({link.get_attribute('href') for link in list_result if link.get_attribute('href')})
        scroll_attempts += 1

    places = list(places)[:num_results]

    # Lưu file CSV
    data_file = os.path.join(BASE_DIR, '..', 'data', 'google_maps_results.csv')
    os.makedirs(os.path.dirname(data_file), exist_ok=True)
    file_exists = os.path.exists(data_file)

    results = []
    with open(data_file, 'a', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['Tên địa điểm','Địa chỉ','Số điện thoại','Website']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        for place_url in places:
            driver.get(place_url)
            time.sleep(3)
            name = get_text_by_xpath(driver, '//h1')
            address = get_text_by_xpath(driver, "//div[contains(@class, 'Io6YTe') and contains(@class,'fdkmkc')]")
            phone = get_text_by_xpath(driver, "//button[contains(@data-item-id, 'phone')]")
            website = get_text_by_xpath(driver, "//a[contains(@data-item-id, 'authority') or contains(@href, 'http')]")

            result = {'Tên địa điểm': name, 'Địa chỉ': address, 'Số điện thoại': phone, 'Website': website}
            results.append(result)
            writer.writerow(result)

            # Gửi lên blockchain
            try:
                requests.post(BLOCKCHAIN_API, json=result, timeout=5)
            except Exception as e:
                print('Blockchain POST error:', e)

    driver.quit()
    return jsonify(results)

@app.route('/download', methods=['GET'])
def download_csv():
    data_file = os.path.join(BASE_DIR, '..', 'data', 'google_maps_results.csv')
    if os.path.exists(data_file):
        return send_file(data_file, as_attachment=True)
    return 'No data', 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
