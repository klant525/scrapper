from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import csv

# Thiết lập ChromeOptions cho Selenium
options = webdriver.ChromeOptions()
options.add_argument("--headless")  # Chạy nền không hiện cửa sổ
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

# Khởi tạo trình duyệt Chrome
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=options)

def get_text_by_xpath(driver, xpath, default="Không có dữ liệu"):
    """Hàm lấy text theo XPath với xử lý ngoại lệ."""
    try:
        element = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, xpath))
        )
        return element.text.strip()
    except:
        return default

# Nhập từ khóa và số lượng kết quả cần lấy
search_key = input(">> Nhập từ khóa tìm kiếm: ")
keyword = search_key.replace(" ", "+")
num_results = int(input(">> Nhập số lượng kết quả cần lấy: "))

# Mở Google Maps với từ khóa tìm kiếm
crawl_url = f'https://www.google.com/maps/search/{keyword}'
driver.get(crawl_url)
time.sleep(5)  # Chờ trang tải

# Cuộn để lấy đủ số lượng kết quả
scroll_attempt = 0
max_scroll_attempts = 20
last_count = 0

while True:
    list_result = driver.find_elements(By.CSS_SELECTOR, "a.hfpxzc")
    current_count = len(list_result)

    if current_count >= num_results:
        break

    if current_count == last_count:
        scroll_attempt += 1
        if scroll_attempt >= max_scroll_attempts:
            print("⚠️ Không thể tải đủ kết quả, kết thúc sớm.")
            break
    else:
        scroll_attempt = 0
        last_count = current_count

    try:
        scrollable_div = driver.find_element(By.XPATH, '//div[contains(@class, "m6QErb") and contains(@class, "tLjsW")]')
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scrollable_div)
    except:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.PAGE_DOWN)

    time.sleep(2)

# Lấy danh sách các link chi tiết địa điểm
list_result = driver.find_elements(By.CSS_SELECTOR, "a.hfpxzc")
places = [link.get_attribute("href") for link in list_result[:num_results]]

print("\n🔹 Danh sách địa điểm tìm thấy:")
for idx, place_url in enumerate(places):
    print(f"{idx + 1}. {place_url}")

print("\n🔹 Đang lấy thông tin chi tiết...\n")

# Ghi thông tin vào CSV
with open("google_maps_results.csv", "a", newline="", encoding="utf-8") as csvfile:
    fieldnames = ["Tên địa điểm", "Địa chỉ", "Số điện thoại", "Website"]
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    if csvfile.tell() == 0:
        writer.writeheader()

    for idx, place_url in enumerate(places):
        driver.get(place_url)
        time.sleep(5)

        name = get_text_by_xpath(driver, "//h1")
        address = get_text_by_xpath(driver, "//div[contains(@class, 'Io6YTe') and contains(@class, 'kR99db') and contains(@class, 'fdkmkc')]")
        phone = get_text_by_xpath(driver, "//button[contains(@data-item-id, 'phone')]")
        website = get_text_by_xpath(driver, "//div[contains(@class, 'ITvuef')]//div[contains(@class, 'Io6YTe') and contains(@class, 'kR99db') and contains(@class, 'fdkmkc')]")

        print(f"🔹 Địa điểm {idx + 1}:")
        print(f"   🏷️ Tên: {name}")
        print(f"   📍 Địa chỉ: {address}")
        print(f"   📞 Số điện thoại: {phone}")
        print(f"   🌐 Website: {website}\n")

        writer.writerow({
            "Tên địa điểm": name,
            "Địa chỉ": address,
            "Số điện thoại": phone,
            "Website": website
        })

# Đóng trình duyệt
driver.quit()

print("\n✅ Dữ liệu đã được lưu vào google_maps_results.csv")
