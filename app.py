from flask import Flask, render_template, request, send_file
import csv
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

app = Flask(__name__)

# Hàm lấy dữ liệu từ XPath
def get_text_by_xpath(driver, xpath, default="Không có dữ liệu"):
    try:
        element = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, xpath))
        )
        return element.text.strip()
    except:
        return default

@app.route('/', methods=['GET', 'POST'])
def index():
    results = []  # Lưu kết quả để hiển thị trên giao diện

    if request.method == 'POST':
        search_key = request.form['search_key']
        num_results = int(request.form['num_results'])
        keyword = search_key.replace(" ", "+")

        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        crawl_url = f'https://www.google.com/maps/search/{keyword}'
        driver.get(crawl_url)
        time.sleep(5)

        # Cuộn để tải thêm kết quả
        for _ in range(5):
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.PAGE_DOWN)
            time.sleep(2)

        list_result = driver.find_elements(By.CSS_SELECTOR, "a.hfpxzc")
        places = [link.get_attribute("href") for link in list_result[:num_results]]

        file_path = "google_maps_results.csv"
        file_exists = True

        # Kiểm tra file có tồn tại không
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                pass
        except FileNotFoundError:
            file_exists = False

        with open(file_path, "a", newline="", encoding="utf-8") as csvfile:
            fieldnames = ["Tên địa điểm", "Địa chỉ", "Số điện thoại", "Website"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            # Nếu file chưa tồn tại, ghi header
            if not file_exists:
                writer.writeheader()

            # Lấy thông tin chi tiết từng địa điểm
            for place_url in places:
                driver.get(place_url)
                time.sleep(5)

                name = get_text_by_xpath(driver, "//h1")
                address = get_text_by_xpath(driver, "//div[contains(@class, 'Io6YTe') and contains(@class, 'kR99db') and contains(@class, 'fdkmkc')]")
                phone = get_text_by_xpath(driver, "//button[contains(@data-item-id, 'phone')]")
                website = get_text_by_xpath(driver, "//div[contains(@class, 'ITvuef')]//div[contains(@class, 'Io6YTe') and contains(@class, 'kR99db') and contains(@class, 'fdkmkc')]")

                result = {
                    "Tên địa điểm": name,
                    "Địa chỉ": address,
                    "Số điện thoại": phone,
                    "Website": website
                }
                results.append(result)  # Lưu vào danh sách hiển thị
                writer.writerow(result)  # Ghi vào file CSV

        driver.quit()

    return render_template("index.html", results=results)

@app.route('/download')
def download_csv():
    return send_file("google_maps_results.csv", as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, port=8080)
