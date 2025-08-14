import os
import time
import csv
import random
import tempfile
import shutil
import socket

from flask import Flask, render_template, request, jsonify, send_file
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

BASE_DIR = os.path.dirname(__file__)
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))

# -------------------- helpers --------------------
def get_text_by_xpath(driver, xpath, default='Không có dữ liệu', timeout=3):
    try:
        element = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, xpath))
        )
        return element.text.strip() or default
    except (TimeoutException, NoSuchElementException):
        return default

def wait_for_results_to_load(driver, min_results=5, max_wait=10):
    start_time = time.time()
    while time.time() - start_time < max_wait:
        results = driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc')
        if len(results) >= min_results:
            return True
        time.sleep(0.5)
    return False

def human_like_scroll(driver, element, distance=300):
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        actions = ActionChains(driver)
        actions.move_to_element(element).click().perform()
        time.sleep(0.2)

        scroll_steps = max(1, distance // 50)
        for _ in range(scroll_steps):
            driver.execute_script("""
                arguments[0].dispatchEvent(new WheelEvent('wheel', {
                    deltaY: 50, bubbles: true, cancelable: true, view: window
                }));
            """, element)
            time.sleep(random.uniform(0.05, 0.15))
    except Exception as e:
        print(f"Lỗi human-like scroll: {e}")
        driver.execute_script("arguments[0].scrollTop += arguments[1]", element, distance)

def find_results_sidebar(driver):
    print("Đang tìm sidebar results...")
    try:
        all_links = driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc')
        print(f"Tìm thấy {len(all_links)} result links")
        if all_links:
            first_link = all_links[0]
            current_element = first_link
            for level in range(10):
                try:
                    parent = current_element.find_element(By.XPATH, "./..")
                    scroll_height = driver.execute_script("return arguments[0].scrollHeight", parent)
                    client_height = driver.execute_script("return arguments[0].clientHeight", parent)
                    overflow_y = driver.execute_script("return window.getComputedStyle(arguments[0]).overflowY", parent)
                    tag_name = parent.tag_name
                    class_name = parent.get_attribute('class') or 'no-class'
                    print(f"Level {level}: {tag_name}.{class_name[:50]} - ScrollH:{scroll_height}, ClientH:{client_height}, OverflowY:{overflow_y}")
                    if (scroll_height > client_height and scroll_height > 100 and overflow_y in ['auto', 'scroll', 'overlay']):
                        print(f"✓ Tìm thấy scrollable container ở level {level}: {class_name[:50]}")
                        return parent
                    current_element = parent
                except Exception as e:
                    print(f"Lỗi ở level {level}: {e}")
                    break
    except Exception as e:
        print(f"Lỗi khi trace parent: {e}")

    selectors_to_try = [
        "[data-value='Search results']",
        "div[role='main']",
        ".m6QErb.DxyBCb.kA9KIf.dS8AEf",
        ".m6QErb",
        ".siAUzd.Tj2rMd",
        ".lXJj5c.Hk4XGb",
        ".m6QErb[role='feed']",
        ".m6QErb[aria-label*='results']",
        "div[style*='overflow']",
        "div[style*='scroll']",
    ]
    for selector in selectors_to_try:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for elem in elements:
                scroll_height = driver.execute_script("return arguments[0].scrollHeight", elem)
                client_height = driver.execute_script("return arguments[0].clientHeight", elem)
                if scroll_height > client_height and scroll_height > 200:
                    class_name = elem.get_attribute('class') or elem.tag_name
                    print(f"✓ Fallback tìm thấy: {selector} -> {class_name[:50]}")
                    return elem
        except:
            continue

    print("⚠ Không tìm thấy sidebar, sử dụng body")
    return driver.find_element(By.TAG_NAME, 'body')

def scroll_and_collect_places(driver, target_count, max_scrolls=50):
    places_urls = set()
    scroll_count = 0
    consecutive_no_new = 0
    print(f"Bắt đầu thu thập {target_count} địa điểm...")

    if not wait_for_results_to_load(driver):
        print("Không thể load kết quả ban đầu")
        return list(places_urls)

    scrollable_element = find_results_sidebar(driver)

    initial_results = driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc')
    for link in initial_results:
        href = link.get_attribute('href')
        if href and 'maps/place' in href:
            places_urls.add(href)
    print(f"Thu thập ban đầu: {len(places_urls)} địa điểm")

    print("🧪 Test scroll...")
    initial_scroll_top = driver.execute_script("return arguments[0].scrollTop", scrollable_element)
    driver.execute_script("arguments[0].scrollTop += 100", scrollable_element)
    time.sleep(0.5)
    new_scroll_top = driver.execute_script("return arguments[0].scrollTop", scrollable_element)

    if new_scroll_top == initial_scroll_top:
        print("⚠ Element không scroll được, thử tìm element khác...")
        try:
            results_container = driver.find_element(By.CSS_SELECTOR, 'a.hfpxzc').find_element(
                By.XPATH, "./ancestor::div[contains(@style,'overflow') or contains(@style,'scroll')]"
            )
            scrollable_element = results_container
            print("✓ Tìm thấy ancestor container có overflow")
        except:
            print("⚠ Sử dụng body làm fallback")
            scrollable_element = driver.find_element(By.TAG_NAME, 'body')
    else:
        print(f"✓ Element scroll OK: {initial_scroll_top} -> {new_scroll_top}")

    while len(places_urls) < target_count and scroll_count < max_scrolls:
        previous_count = len(places_urls)
        print(f"🔄 Scroll {scroll_count + 1}...")
        scroll_before = driver.execute_script("return arguments[0].scrollTop", scrollable_element)

        try:
            if scroll_count % 4 == 0:
                print("  Method: Smooth scroll animation")
                driver.execute_script("""
                    arguments[0].scrollTo({
                        top: arguments[0].scrollTop + 800,
                        behavior: 'smooth'
                    });
                """, scrollable_element)
                time.sleep(3)
            elif scroll_count % 4 == 1:
                print("  Method: Step scroll")
                for _ in range(8):
                    driver.execute_script("arguments[0].scrollTop += 100", scrollable_element)
                    time.sleep(random.uniform(0.1, 0.3))
            elif scroll_count % 4 == 2:
                print("  Method: Mouse wheel events")
                human_like_scroll(driver, scrollable_element, random.randint(600, 1000))
            else:
                print("  Method: Combined scroll")
                from selenium.webdriver.common.action_chains import ActionChains
                actions = ActionChains(driver)
                actions.move_to_element(scrollable_element).click().perform()
                time.sleep(0.2)
                for _ in range(random.randint(5, 8)):
                    scrollable_element.send_keys(Keys.PAGE_DOWN)
                    time.sleep(random.uniform(0.2, 0.5))

            scroll_after = driver.execute_script("return arguments[0].scrollTop", scrollable_element)
            print(f"  Scroll position: {scroll_before} -> {scroll_after} (+{scroll_after - scroll_before})")
            if scroll_after == scroll_before:
                print("  ⚠ Scroll không thay đổi position, thử scroll window")
                driver.execute_script("window.scrollBy(0, 800);")
                time.sleep(1)
        except Exception as e:
            print(f"  ❌ Lỗi scroll: {e}")
            driver.execute_script("arguments[0].scrollTop += 800", scrollable_element)
            time.sleep(1)

        time.sleep(random.uniform(2, 3))

        try:
            current_results = driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc')
            if current_results and len(current_results) > 3:
                from selenium.webdriver.common.action_chains import ActionChains
                actions = ActionChains(driver)
                actions.move_to_element(current_results[-1]).perform()
                time.sleep(0.5)
        except:
            pass

        current_results = driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc')
        for link in current_results:
            href = link.get_attribute('href')
            if href and 'maps/place' in href:
                places_urls.add(href)

        new_count = len(places_urls)
        print(f"📊 Results: {previous_count} -> {new_count} (+{new_count - previous_count})")

        if new_count == previous_count:
            consecutive_no_new += 1
            print(f"⏸ Không có kết quả mới ({consecutive_no_new}/6)")
            if consecutive_no_new == 3:
                print("🔍 Thử tìm nút 'Xem thêm'...")
                more_buttons = [
                    'button[jsaction*="pane.resultList.moreResults"]',
                    '.VfPpkd-LgbsSe[jsaction*="moreResults"]'
                ]
                for selector in more_buttons:
                    try:
                        more_button = driver.find_element(By.CSS_SELECTOR, selector)
                        if more_button.is_displayed():
                            driver.execute_script("arguments[0].click();", more_button)
                            print("✓ Đã click nút 'Xem thêm'")
                            time.sleep(3)
                            consecutive_no_new = 0
                            break
                    except:
                        continue
            elif consecutive_no_new >= 6:
                print("🛑 Đã hết kết quả, dừng scroll")
                break
        else:
            consecutive_no_new = 0

        if len(places_urls) >= target_count:
            print("🎯 Đã đủ số lượng mục tiêu")
            break

        scroll_count += 1
        if scroll_count % 3 == 0:
            current_elements = len(driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc'))
            scroll_pos = driver.execute_script("return arguments[0].scrollTop", scrollable_element)
            scroll_max = driver.execute_script("return arguments[0].scrollHeight - arguments[0].clientHeight", scrollable_element)
            pct = (scroll_pos / max(scroll_max, 1) * 100.0)
            print(f"📈 Progress: DOM elements: {current_elements}, Unique URLs: {len(places_urls)}")
            print(f"   Scroll: {scroll_pos}/{scroll_max} ({pct:.1f}%)")

    final_places = list(places_urls)[:target_count]
    print(f"✅ Hoàn thành: {len(final_places)} địa điểm")
    return final_places

def extract_place_info(driver, place_url, timeout=8):
    try:
        driver.get(place_url)
        time.sleep(random.uniform(2, 4))
        WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.TAG_NAME, 'h1')))

        name = get_text_by_xpath(driver, '//h1[@class="DUwDvf lfPIob"]', 'Không có tên')
        if name == 'Không có tên':
            name = get_text_by_xpath(driver, '//h1', 'Không có tên')

        address_selectors = [
            "//div[contains(@class, 'Io6YTe') and contains(@class,'fdkmkc')]",
            "//button[@data-item-id='address']//div[contains(@class, 'fontBodyMedium')]",
            "//div[contains(@class, 'rogA2c')]//div[2]",
        ]
        address = 'Không có địa chỉ'
        for selector in address_selectors:
            address = get_text_by_xpath(driver, selector, 'Không có địa chỉ')
            if address != 'Không có địa chỉ':
                break

        phone_selectors = [
            "//button[contains(@data-item-id, 'phone')]//div[contains(@class, 'fontBodyMedium')]",
            "//button[contains(@data-item-id, 'phone')]",
            "//a[starts-with(@href, 'tel:')]",
        ]
        phone = 'Không có số điện thoại'
        for selector in phone_selectors:
            phone = get_text_by_xpath(driver, selector, 'Không có số điện thoại')
            if phone != 'Không có số điện thoại' and phone.strip():
                break

        website_selectors = [
            "//a[contains(@data-item-id, 'authority')]",
            "//button[contains(@data-item-id, 'authority')]//div[contains(@class, 'fontBodyMedium')]",
            "//a[contains(@href, 'http') and not(contains(@href, 'google'))]",
        ]
        website = 'Không có website'
        for selector in website_selectors:
            element_text = get_text_by_xpath(driver, selector, 'Không có website')
            if element_text != 'Không có website' and 'http' in element_text:
                website = element_text
                break
            try:
                elem = driver.find_element(By.XPATH, selector)
                href = elem.get_attribute('href')
                if href and 'http' in href and 'google' not in href:
                    website = href
                    break
            except:
                continue

        return {
            'Tên địa điểm': name,
            'Địa chỉ': address,
            'Số điện thoại': phone,
            'Website': website
        }
    except Exception as e:
        print(f"Lỗi khi extract thông tin từ {place_url}: {e}")
        return {
            'Tên địa điểm': 'Lỗi lấy dữ liệu',
            'Địa chỉ': 'Lỗi lấy dữ liệu',
            'Số điện thoại': 'Lỗi lấy dữ liệu',
            'Website': 'Lỗi lấy dữ liệu'
        }

# -------------------- utils --------------------
def _free_port():
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def _build_chrome(options_headless=True):
    # tạo profile tạm cho mỗi phiên
    chrome_profile = tempfile.mkdtemp(dir="/tmp", prefix="chrome-profile-")
    opts = webdriver.ChromeOptions()
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-blink-features=AutomationControlled')
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option('useAutomationExtension', False)
    opts.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    opts.add_argument('--disable-web-security')
    opts.add_argument('--allow-running-insecure-content')
    opts.add_argument('--window-size=1920,1080')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--single-process')
    # profile & tránh first-run
    opts.add_argument(f'--user-data-dir={chrome_profile}')
    opts.add_argument('--profile-directory=Default')
    opts.add_argument('--no-first-run')
    opts.add_argument('--no-default-browser-check')
    opts.add_argument(f'--remote-debugging-port={_free_port()}')
    if options_headless:
        opts.add_argument('--headless=new')

    driver = None
    try:
        driver = webdriver.Chrome(options=opts)  # Selenium Manager tự chọn driver
        driver.set_window_size(1920, 1080)
        return driver, chrome_profile
    except Exception as e:
        # nếu lỗi, dọn profile
        shutil.rmtree(chrome_profile, ignore_errors=True)
        raise e

# -------------------- routes --------------------
@app.route('/')
def index():
    # Render template nếu có, nếu không trả về string
    tpl = os.path.join(BASE_DIR, 'templates', 'index.html')
    if os.path.exists(tpl):
        return render_template('index.html')
    return "Google Maps Scraper API"

@app.route('/search', methods=['POST'])
def search():
    search_key = (request.form.get('search_key') or '').strip()
    if not search_key:
        return jsonify({'error': 'Vui lòng nhập từ khóa tìm kiếm'}), 400

    try:
        num_results = int(request.form.get('num_results', '10') or 10)
        if num_results <= 0 or num_results > 100:
            return jsonify({'error': 'Số lượng kết quả phải từ 1 đến 100'}), 400
    except ValueError:
        return jsonify({'error': 'Số lượng kết quả không hợp lệ'}), 400

    lat = (request.form.get('lat') or '').strip()
    lng = (request.form.get('lng') or '').strip()
    keyword = search_key.replace(' ', '+')

    driver, chrome_profile = _build_chrome(options_headless=True)  # bật headless trong container
    try:
        if lat and lng:
            try:
                lat_float = float(lat); lng_float = float(lng)
                crawl_url = f'https://www.google.com/maps/search/{keyword}/@{lat_float},{lng_float},14z'
            except ValueError:
                crawl_url = f'https://www.google.com/maps/search/{keyword}'
        else:
            crawl_url = f'https://www.google.com/maps/search/{keyword}'

        print(f"Đang truy cập: {crawl_url}")
        driver.get(crawl_url)
        time.sleep(5)

        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'a.hfpxzc'))
            )
        except TimeoutException:
            print("Timeout waiting for results")

        places_urls = scroll_and_collect_places(driver, num_results)
        if not places_urls:
            return jsonify({'error': 'Không tìm thấy kết quả nào'}), 404

        data_file = os.path.join(BASE_DIR, 'data', 'google_maps_results.csv')
        os.makedirs(os.path.dirname(data_file), exist_ok=True)
        file_exists = os.path.exists(data_file)

        results = []
        successful_extracts = 0
        with open(data_file, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['Tên địa điểm','Địa chỉ','Số điện thoại','Website']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()

            for i, place_url in enumerate(places_urls, 1):
                print(f"Đang xử lý địa điểm {i}/{len(places_urls)}")
                result = extract_place_info(driver, place_url)
                results.append(result)
                writer.writerow(result)
                if result['Tên địa điểm'] != 'Lỗi lấy dữ liệu':
                    successful_extracts += 1
                if i < len(places_urls):
                    time.sleep(random.uniform(1, 3))

        print(f"Hoàn thành! Thu thập thành công {successful_extracts}/{len(places_urls)} địa điểm")
        return jsonify({
            'results': results,
            'total_found': len(places_urls),
            'successful_extracts': successful_extracts,
            'message': f'Đã thu thập {successful_extracts}/{len(places_urls)} địa điểm thành công'
        })
    except Exception as e:
        print(f"Lỗi trong quá trình search: {e}")
        return jsonify({'error': f'Có lỗi xảy ra: {str(e)}'}), 500
    finally:
        try:
            driver.quit()
        except:
            pass
        shutil.rmtree(chrome_profile, ignore_errors=True)

@app.route('/download', methods=['GET'])
def download_csv():
    data_file = os.path.join(BASE_DIR, 'data', 'google_maps_results.csv')
    if os.path.exists(data_file):
        return send_file(data_file, as_attachment=True, download_name='google_maps_results.csv')
    return jsonify({'error': 'Chưa có dữ liệu để tải'}), 404

# -------------------- entrypoint --------------------
if __name__ == '__main__':
    # Tắt debug & reloader trong container để tránh spawn 2 process (gây lock profile)
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)
