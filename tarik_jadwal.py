from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pytz
import time

# --- Import Selenium ---
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

# ==========================================
# KONFIGURASI GOOGLE SHEETS
# ==========================================
CREDENTIALS_FILE = 'credentials.json' 
SPREADSHEET_NAME = 'Jadwal Gelora Dashboard' 

TARGET_LAPANGAN = [
    "Lapangan Tennis Indoor 1",
    "Lapangan Tennis Indoor 2",
    "Lapangan Tennis Indoor 3",
    "Lapangan Tennis Indoor 4"
]

# ==========================================
# KONFIGURASI LOGIN GELORA
# ==========================================
# Ganti dengan URL halaman login Gelora
LOGIN_URL = 'https://bisnis.gelora.id/BusinessAccount/Login' # <-- Sesuaikan jika salah
# Ganti dengan URL halaman jadwal yang sering Anda buka
JADWAL_URL = 'https://bisnis.gelora.id/TimeTable/DisplayDaily?fieldId=577&venueId=339' # Tanggal akan ditambahkan otomatis
EMAIL_AKUN = 'zaenalarifin807@gmail.com'
PASSWORD_AKUN = 'Aira240279'

def get_html_with_selenium():
    """Membuka browser, login otomatis, dan mengambil HTML jadwal"""
    print("Membuka browser otomatis...")
    
    # Opsi Chrome (Bisa tambahkan '--headless' jika tidak ingin browsernya muncul di layar)
    chrome_options = Options()
    # chrome_options.add_argument("--headless") 
    
    # Jalankan Chrome
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        # 1. Buka halaman Login
        print("Membuka halaman login...")
        driver.get(LOGIN_URL)
        time.sleep(3) # Tunggu loading sebentar
        
        # 2. Cari kolom input menggunakan nama yang benar
        wait = WebDriverWait(driver, 15)
        
        email_input = wait.until(EC.presence_of_element_located((By.NAME, 'Credential'))) 
        password_input = driver.find_element(By.NAME, 'Password') 
        
        # Ketik email
        email_input.send_keys(EMAIL_AKUN)
        
        # Ketik password DAN langsung tekan ENTER di keyboard
        password_input.send_keys(PASSWORD_AKUN + Keys.RETURN)
        
        # CATATAN: Semua kode login_button = ... dan login_button.click() SUDAH DIHAPUS.
        
        print("Sedang login...")
        time.sleep(5) # Tunggu proses login dan loading halaman utama
        
        # 4. Buka halaman Jadwal hari ini
        # Kita format tanggal hari ini (WITA) untuk dimasukkan ke URL
        tz = pytz.timezone('Asia/Makassar')
        tanggal_hari_ini = datetime.now(tz).strftime('%Y-%m-%d')
        target_url = f"{JADWAL_URL}&dateSelection={tanggal_hari_ini}"
        
        print(f"Membuka halaman jadwal tanggal: {tanggal_hari_ini}...")
        driver.get(target_url)
        
        # Tunggu sampai tabel jadwal muncul (Maksimal tunggu 15 detik)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "papan_jadwal_daily"))
        )
        time.sleep(2) # Ekstra tunggu agar data render sempurna
        
        # 5. Ambil HTML-nya!
        print("Berhasil memuat tabel. Mengambil data HTML...")
        html_source = driver.page_source
        return html_source

    except Exception as e:
        print(f"Terjadi kesalahan saat navigasi browser: {e}")
        return None
    finally:
        # Tutup browser
        driver.quit()

def parse_html_to_data(html_content):
    """Membedah HTML (Versi bersih tanpa view-source)"""
    soup = BeautifulSoup(html_content, 'html.parser')
    table = soup.find('table', id='papan_jadwal_daily')
    
    if not table:
        print("Tabel jadwal tidak ditemukan!")
        return []

    tz = pytz.timezone('Asia/Makassar')
    tanggal_hari_ini = datetime.now(tz).strftime('%Y-%m-%d')

    headers = [th.get_text(strip=True) for th in table.find('thead').find_all('th')]
    lapangan_names = headers[1:] 
    
    data_to_export = [['Tanggal', 'Waktu', 'Nama Lapangan', 'Status', 'Nama Pemesan', 'Harga']]
    
    for tr in table.find('tbody').find_all('tr'):
        tds = tr.find_all('td')
        if not tds:
            continue
        
        waktu_mentah = tds[0].get_text(strip=True)
        waktu = " ".join(waktu_mentah.split())
        
        for i, td in enumerate(tds[1:]):
            if i >= len(lapangan_names): break
            lapangan = lapangan_names[i]
            if lapangan not in TARGET_LAPANGAN: continue
            
            is_booked_input = td.find('input', id=lambda x: x and x.endswith('-isBooked'))
            price_input = td.find('input', id=lambda x: x and x.endswith('-price'))
            name_input = td.find('input', id=lambda x: x and x.endswith('-fieldBookingItemName'))
            
            is_booked = is_booked_input['value'] if is_booked_input else 'False'
            price = price_input['value'] if price_input else '0'
            pemesan = name_input['value'] if name_input else '-'
            
            status = 'Terbooking' if is_booked.lower() == 'true' else 'Tersedia'
            data_to_export.append([tanggal_hari_ini, waktu, lapangan, status, pemesan, price])
            
    return data_to_export

def push_to_google_sheets(data):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open(SPREADSHEET_NAME).sheet1
    
    # 1. Ambil semua data yang sudah ada di Sheets saat ini
    existing_data = sheet.get_all_values()
    
    # 2. Ambil tanggal hari ini dari data yang baru di-scrape (Baris ke-2, kolom ke-1)
    tanggal_baru = data[1][0] 
    
    # 3. Logika Pintar (Smart Update)
    if not existing_data:
        # Jika sheet masih benar-benar kosong, langsung pakai data baru
        final_data = data
    else:
        header = existing_data[0]
        
        # Saring data lama: HANYA simpan baris yang tanggalnya BUKAN tanggal hari ini
        # (Ini otomatis menghapus data hari ini yang lama jika Anda melakukan running ulang/update)
        filtered_existing_data = [
            row for row in existing_data[1:] 
            if len(row) > 0 and row[0] != tanggal_baru
        ]
        
        # Gabungkan: Header + Data Lama (yang sudah difilter) + Data Baru (tanpa header)
        final_data = [header] + filtered_existing_data + data[1:]

    # 4. Hapus sheet dan timpa dengan gabungan data riwayat + update terbaru
    sheet.clear()
    sheet.update(values=final_data, range_name='A1')
    
    print(f"Hore! Berhasil menyimpan data. Total ada {len(final_data)-1} baris riwayat jadwal di Google Sheets sekarang!")

if __name__ == "__main__":
    # 1. Jalankan Robot Browser untuk ambil HTML
    html_otomatis = get_html_with_selenium()
    
    if html_otomatis:
        # 2. Ekstrak Datanya
        parsed_data = parse_html_to_data(html_otomatis)
        
        # 3. Kirim ke Sheets
        if len(parsed_data) > 1:
            push_to_google_sheets(parsed_data)
        else:
            print("Gagal memproses data lapangan.")