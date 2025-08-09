import os, time, csv, requests, random
from flask import Flask, render_template, request, jsonify, send_file
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

BASE_DIR = os.path.dirname(__file__)
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))

# Config blockchain API
BLOCKCHAIN_API = os.environ.get('BLOCKCHAIN_API', 'http://127.0.0.1:5000/add')

def get_text_by_xpath(driver, xpath, default='Không có dữ liệu', timeout=3):
    """Lấy text từ element với timeout ngắn hơn"""
    try:
        element = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, xpath))
        )
        return element.text.strip() or default
    except (TimeoutException, NoSuchElementException):
        return default

def wait_for_results_to_load(driver, min_results=5, max_wait=10):
    """Đợi kết quả load với timeout"""
    start_time = time.time()
    while time.time() - start_time < max_wait:
        results = driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc')
        if len(results) >= min_results:
            return True
        time.sleep(0.5)
    return False

def human_like_scroll(driver, element, distance=300):
    """Scroll như người thật với mouse wheel events"""
    try:
        # Sử dụng ActionChains để tạo mouse wheel events
        from selenium.webdriver.common.action_chains import ActionChains
        actions = ActionChains(driver)
        
        # Click vào element trước để focus
        actions.move_to_element(element).click().perform()
        time.sleep(0.2)
        
        # Simulate mouse wheel scroll (nhiều scroll nhỏ)
        scroll_steps = distance // 50  # Chia thành nhiều scroll nhỏ
        for i in range(scroll_steps):
            driver.execute_script(f"""
                arguments[0].dispatchEvent(new WheelEvent('wheel', {{
                    deltaY: 50,
                    bubbles: true,
                    cancelable: true,
                    view: window
                }}));
            """, element)
            time.sleep(random.uniform(0.05, 0.15))  # Delay ngắn giữa các wheel event
            
    except Exception as e:
        print(f"Lỗi human-like scroll: {e}")
        # Fallback
        driver.execute_script("arguments[0].scrollTop += arguments[1]", element, distance)

def find_results_sidebar(driver):
    """Tìm chính xác sidebar chứa kết quả tìm kiếm"""
    print("Đang tìm sidebar results...")
    
    # Debug: In ra tất cả elements có chứa results
    try:
        all_links = driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc')
        print(f"Tìm thấy {len(all_links)} result links")
        
        if all_links:
            # Trace lên parent để tìm scrollable container
            first_link = all_links[0]
            current_element = first_link
            
            # Traverse lên parent nodes để tìm scrollable container
            for level in range(10):  # Tối đa 10 level
                try:
                    parent = current_element.find_element(By.XPATH, "./..")
                    scroll_height = driver.execute_script("return arguments[0].scrollHeight", parent)
                    client_height = driver.execute_script("return arguments[0].clientHeight", parent)
                    overflow = driver.execute_script("return window.getComputedStyle(arguments[0]).overflow", parent)
                    overflow_y = driver.execute_script("return window.getComputedStyle(arguments[0]).overflowY", parent)
                    
                    tag_name = parent.tag_name
                    class_name = parent.get_attribute('class') or 'no-class'
                    
                    print(f"Level {level}: {tag_name}.{class_name[:50]} - ScrollH:{scroll_height}, ClientH:{client_height}, Overflow:{overflow_y}")
                    
                    # Kiểm tra có scrollable không
                    if (scroll_height > client_height and 
                        scroll_height > 100 and  # Đảm bảo có content đáng kể
                        overflow_y in ['auto', 'scroll', 'overlay']):
                        print(f"✓ Tìm thấy scrollable container ở level {level}: {class_name[:50]}")
                        return parent
                        
                    current_element = parent
                except Exception as e:
                    print(f"Lỗi ở level {level}: {e}")
                    break
    except Exception as e:
        print(f"Lỗi khi trace parent: {e}")
    
    # Fallback: Thử các selector cụ thể cho Google Maps 2024
    selectors_to_try = [
        # Sidebar results container (thường dùng)
        "[data-value='Search results']",
        "div[role='main']",
        ".m6QErb.DxyBCb.kA9KIf.dS8AEf",
        ".m6QErb",
        ".siAUzd.Tj2rMd", 
        ".lXJj5c.Hk4XGb",
        # Results feed container
        ".m6QErb[role='feed']",
        ".m6QErb[aria-label*='results']",
        # Generic scrollable containers
        "div[style*='overflow']",
        "div[style*='scroll']"
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
    """Cuộn và thu thập địa điểm với human-like scrolling"""
    places_urls = set()
    scroll_count = 0
    consecutive_no_new = 0
    
    print(f"Bắt đầu thu thập {target_count} địa điểm...")
    
    # Đợi trang load ban đầu
    if not wait_for_results_to_load(driver):
        print("Không thể load kết quả ban đầu")
        return list(places_urls)
    
    # Tìm chính xác scrollable container
    scrollable_element = find_results_sidebar(driver)
    
    # Thu thập URLs ban đầu
    initial_results = driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc')
    for link in initial_results:
        href = link.get_attribute('href')
        if href and 'maps/place' in href:
            places_urls.add(href)
    print(f"Thu thập ban đầu: {len(places_urls)} địa điểm")
    
    # Test scroll trước khi bắt đầu
    print("🧪 Test scroll...")
    initial_scroll_top = driver.execute_script("return arguments[0].scrollTop", scrollable_element)
    driver.execute_script("arguments[0].scrollTop += 100", scrollable_element)
    time.sleep(0.5)
    new_scroll_top = driver.execute_script("return arguments[0].scrollTop", scrollable_element)
    
    if new_scroll_top == initial_scroll_top:
        print("⚠ Element không scroll được, thử tìm element khác...")
        # Thử scroll trực tiếp trên results container
        try:
            results_container = driver.find_element(By.CSS_SELECTOR, 'a.hfpxzc').find_element(By.XPATH, "./ancestor::div[contains(@style,'overflow') or contains(@style,'scroll')]")
            scrollable_element = results_container
            print("✓ Tìm thấy ancestor container có overflow")
        except:
            print("⚠ Sử dụng body làm fallback")
            scrollable_element = driver.find_element(By.TAG_NAME, 'body')
    else:
        print(f"✓ Element scroll OK: {initial_scroll_top} -> {new_scroll_top}")
    
    while len(places_urls) < target_count and scroll_count < max_scrolls:
        previous_count = len(places_urls)
        
        # Scroll với visual feedback
        print(f"🔄 Scroll {scroll_count + 1}...")
        scroll_before = driver.execute_script("return arguments[0].scrollTop", scrollable_element)
        
        # Human-like scrolling với nhiều kỹ thuật
        try:
            if scroll_count % 4 == 0:
                # Method 1: Smooth scroll animation
                print("  Method: Smooth scroll animation")
                driver.execute_script("""
                    arguments[0].scrollTo({
                        top: arguments[0].scrollTop + 800,
                        behavior: 'smooth'
                    });
                """, scrollable_element)
                time.sleep(3)  # Đợi animation hoàn thành
                
            elif scroll_count % 4 == 1:
                # Method 2: Step scroll với delays
                print("  Method: Step scroll")
                for step in range(8):
                    driver.execute_script("arguments[0].scrollTop += 100", scrollable_element)
                    time.sleep(random.uniform(0.1, 0.3))
                    
            elif scroll_count % 4 == 2:
                # Method 3: Mouse wheel events
                print("  Method: Mouse wheel events")
                human_like_scroll(driver, scrollable_element, random.randint(600, 1000))
                
            else:
                # Method 4: Combined approach
                print("  Method: Combined scroll")
                from selenium.webdriver.common.action_chains import ActionChains
                actions = ActionChains(driver)
                
                # Click để focus
                actions.move_to_element(scrollable_element).click().perform()
                time.sleep(0.2)
                
                # Scroll với keyboard
                for _ in range(random.randint(5, 8)):
                    scrollable_element.send_keys(Keys.PAGE_DOWN)
                    time.sleep(random.uniform(0.2, 0.5))
            
            # Check scroll position
            scroll_after = driver.execute_script("return arguments[0].scrollTop", scrollable_element)
            print(f"  Scroll position: {scroll_before} -> {scroll_after} (+{scroll_after - scroll_before})")
            
            # Nếu không scroll được thì thử method khác
            if scroll_after == scroll_before:
                print("  ⚠ Scroll không thay đổi position, thử scroll window")
                driver.execute_script("window.scrollBy(0, 800);")
                time.sleep(1)
                
        except Exception as e:
            print(f"  ❌ Lỗi scroll: {e}")
            driver.execute_script("arguments[0].scrollTop += 800", scrollable_element)
            time.sleep(1)
        
        # Đợi loading và trigger lazy loading
        time.sleep(random.uniform(2, 3))
        
        # Trigger hover trên kết quả cuối
        try:
            current_results = driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc')
            if current_results and len(current_results) > 3:
                from selenium.webdriver.common.action_chains import ActionChains
                actions = ActionChains(driver)
                actions.move_to_element(current_results[-1]).perform()
                time.sleep(0.5)
        except:
            pass
        
        # Thu thập các link hiện tại
        current_results = driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc')
        for link in current_results:
            href = link.get_attribute('href')
            if href and 'maps/place' in href:
                places_urls.add(href)
        
        new_count = len(places_urls)
        print(f"📊 Results: {previous_count} -> {new_count} (+{new_count - previous_count})")
        
        # Kiểm tra có thêm kết quả mới không
        if new_count == previous_count:
            consecutive_no_new += 1
            print(f"⏸ Không có kết quả mới ({consecutive_no_new}/6)")
            
            if consecutive_no_new == 3:
                print("🔍 Thử tìm nút 'Xem thêm'...")
                # Thử click "Xem thêm kết quả"
                more_buttons = [
                    'button[jsaction*="pane.resultList.moreResults"]',
                    'button:contains("Xem thêm")',
                    'span:contains("Show more results")',
                    '.VfPpkd-LgbsSe[jsaction*="moreResults"]'
                ]
                
                for selector in more_buttons:
                    try:
                        if ':contains(' in selector:
                            continue  # Skip jQuery selectors
                        
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
        
        # Nếu đã đủ số lượng thì dừng
        if len(places_urls) >= target_count:
            print("🎯 Đã đủ số lượng mục tiêu")
            break
            
        scroll_count += 1
        
        # Progress report chi tiết
        if scroll_count % 3 == 0:
            current_elements = len(driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc'))
            scroll_pos = driver.execute_script("return arguments[0].scrollTop", scrollable_element)
            scroll_max = driver.execute_script("return arguments[0].scrollHeight - arguments[0].clientHeight", scrollable_element)
            print(f"📈 Progress: DOM elements: {current_elements}, Unique URLs: {len(places_urls)}")
            print(f"   Scroll: {scroll_pos}/{scroll_max} ({scroll_pos/max(scroll_max,1)*100:.1f}%)")
    
    final_places = list(places_urls)[:target_count]
    print(f"✅ Hoàn thành: {len(final_places)} địa điểm (scroll {scroll_count} lần)")
    return final_places

def extract_place_info(driver, place_url, timeout=8):
    """Extract thông tin từ một địa điểm với error handling tốt hơn"""
    try:
        driver.get(place_url)
        time.sleep(random.uniform(2, 4))  # Random delay
        
        # Đợi trang load
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.TAG_NAME, 'h1'))
        )
        
        # Lấy thông tin với multiple selectors
        name = get_text_by_xpath(driver, '//h1[@class="DUwDvf lfPIob"]', 'Không có tên')
        if name == 'Không có tên':
            name = get_text_by_xpath(driver, '//h1', 'Không có tên')
        
        # Address với nhiều selector khác nhau
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
        
        # Phone với nhiều selector
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
        
        # Website với nhiều selector
        website_selectors = [
            "//a[contains(@data-item-id, 'authority')]",
            "//button[contains(@data-item-id, 'authority')]//div[contains(@class, 'fontBodyMedium')]",
            "//a[contains(@href, 'http') and not(contains(@href, 'google'))]",
        ]
        website = 'Không có website'
        for selector in website_selectors:
            element = get_text_by_xpath(driver, selector, 'Không có website')
            if element != 'Không có website' and 'http' in element:
                website = element
                break
            # Thử lấy href attribute
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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    search_key = request.form.get('search_key', '').strip()
    if not search_key:
        return jsonify({'error': 'Vui lòng nhập từ khóa tìm kiếm'}), 400
        
    try:
        num_results = int(request.form.get('num_results', '10') or 10)
        if num_results <= 0 or num_results > 100:  # Giới hạn max 100
            return jsonify({'error': 'Số lượng kết quả phải từ 1 đến 100'}), 400
    except ValueError:
        return jsonify({'error': 'Số lượng kết quả không hợp lệ'}), 400
    
    lat = request.form.get('lat', '').strip()
    lng = request.form.get('lng', '').strip()

    keyword = search_key.replace(' ', '+')

    # Setup Chrome với options tối ưu cho scroll
    options = webdriver.ChromeOptions()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    # Thêm các options để tối ưu scroll
    options.add_argument('--disable-web-security')
    options.add_argument('--allow-running-insecure-content')
    options.add_argument('--window-size=1920,1080')
    
    # Uncomment dòng dưới nếu muốn chạy headless
    # options.add_argument('--headless=new')

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    # Set window size để scroll tốt hơn
    driver.set_window_size(1920, 1080)
    
    try:
        # Tạo URL tìm kiếm
        if lat and lng:
            try:
                lat_float = float(lat)
                lng_float = float(lng)
                crawl_url = f'https://www.google.com/maps/search/{keyword}/@{lat_float},{lng_float},14z'
            except ValueError:
                crawl_url = f'https://www.google.com/maps/search/{keyword}'
        else:
            crawl_url = f'https://www.google.com/maps/search/{keyword}'

        print(f"Đang truy cập: {crawl_url}")
        driver.get(crawl_url)
        
        # Đợi lâu hơn để trang load hoàn toàn
        time.sleep(5)
        
        # Đợi sidebar results load
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'a.hfpxzc'))
            )
        except TimeoutException:
            print("Timeout waiting for results")

        # Thu thập danh sách địa điểm
        places_urls = scroll_and_collect_places(driver, num_results)
        
        if not places_urls:
            return jsonify({'error': 'Không tìm thấy kết quả nào'}), 404

        # Chuẩn bị file CSV
        data_file = os.path.join(BASE_DIR, '..', 'data', 'google_maps_results.csv')
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

                # Gửi lên blockchain với error handling
                try:
                    response = requests.post(BLOCKCHAIN_API, json=result, timeout=5)
                    if response.status_code != 200:
                        print(f'Blockchain API returned status {response.status_code}')
                except Exception as e:
                    print(f'Blockchain POST error: {e}')

                # Delay ngẫu nhiên giữa các request
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

@app.route('/download', methods=['GET'])
def download_csv():
    data_file = os.path.join(BASE_DIR, '..', 'data', 'google_maps_results.csv')
    if os.path.exists(data_file):
        return send_file(data_file, as_attachment=True, download_name='google_maps_results.csv')
    return jsonify({'error': 'Không tìm thấy file dữ liệu'}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)