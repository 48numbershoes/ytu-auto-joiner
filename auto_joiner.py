#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTÜ Otomatik Derse Katılım Botu
================================
Yıldız Teknik Üniversitesi online.yildiz.edu.tr LMS sistemine
ders saati geldiğinde otomatik olarak bağlanır ve Zoom'a katılır.

Kullanım:
    python auto_joiner.py           # Normal mod - zamanlayıcı ile çalışır
    python auto_joiner.py --test    # Test modu - hemen derse katılmayı dener
    python auto_joiner.py --status  # Planlanmış dersleri gösterir
"""

import json
import io
import logging
import os
import sys
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
)
from webdriver_manager.chrome import ChromeDriverManager

# ─── Sabitler ────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
SCHEDULE_FILE = SCRIPT_DIR / "schedule.json"
LOG_FILE = SCRIPT_DIR / "bot.log"
LMS_URL = "https://online.yildiz.edu.tr/?transaction=LMS.CORE.Cockpit.ViewCockpit/0"

# Bot icin ozel Chrome profil dizini (kullanici profili ile cakismaz)
BOT_PROFILE_DIR = SCRIPT_DIR / "bot_chrome_profile"

# Zamanlama
DAKIKA_ONCE = 2  # Dersten kac dakika once katilmayi denesin

# Yeniden deneme
MAX_RETRY = 3
RETRY_ARALIK = 15  # saniye

# Türkçe gün -> cron gün eşlemesi
GUN_MAP = {
    "Pazartesi": "mon",
    "Salı": "tue",
    "Salı": "tue",
    "Çarşamba": "wed",
    "Perşembe": "thu",
    "Cuma": "fri",
    "Cumartesi": "sat",
    "Pazar": "sun",
}

# ─── Loglama ─────────────────────────────────────────────────────────────────

def setup_logging():
    """Konsola ve dosyaya log yazar."""
    # Windows'ta UTF-8 çıktı zorla
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    logger = logging.getLogger("YTU-Bot")
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Konsol
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # Dosya
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


log = setup_logging()

# ─── Program Yükleme ────────────────────────────────────────────────────────

def load_schedule() -> list:
    """schedule.json dosyasından aktif dersleri yükler."""
    if not SCHEDULE_FILE.exists():
        log.error(f"Program dosyası bulunamadı: {SCHEDULE_FILE}")
        log.info("Lütfen schedule.json dosyasını oluşturun. Örnek için README.md'ye bakın.")
        sys.exit(1)

    with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    dersler = data.get("dersler", [])
    aktif_dersler = [d for d in dersler if d.get("aktif", False)]

    log.info(f"Toplam {len(dersler)} ders bulundu, {len(aktif_dersler)} tanesi aktif.")

    for ders in aktif_dersler:
        log.info(f"  📚 {ders['ad']} — {ders['gun']} {ders['saat']}")

    return aktif_dersler


# ─── Tarayıcı Yönetimi ──────────────────────────────────────────────────────


def create_driver() -> webdriver.Chrome:
    """Bot'a ozel Chrome profili ile tarayici baslatir."""
    # Profil kilidini cozmek icin eski surecleri temizle
    try:
        import subprocess
        log.info("Eski Chrome surecleri temizleniyor...")
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe", "/T"], capture_output=True)
        subprocess.run(["taskkill", "/F", "/IM", "chromedriver.exe", "/T"], capture_output=True)
        time.sleep(2)
    except Exception:
        pass

    log.info("Chrome tarayici baslatiliyor...")

    # Bot profil dizinini olustur
    BOT_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    options = Options()
    options.add_experimental_option("detach", True)

    # Bot'un kendi profil dizinini kullan (kullanici Chrome'u ile cakismaz)
    options.add_argument(f"--user-data-dir={BOT_PROFILE_DIR}")

    # Zoom'un otomatik acilmasi icin gerekli izinler
    options.add_experimental_option("prefs", {
        "protocol_handler.excluded_schemes": {
            "zoommtg": True,  # True = Zoom desktop uygulamasini ENGELLE
        },
    })

    # Bazi uyarilari kapat + protokol dialogunu engelle
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-external-intent-requests")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_window_size(1280, 800)
        log.info("[OK] Chrome basariyla baslatildi.")
        return driver
    except WebDriverException as e:
        log.error(f"[HATA] Chrome baslatilamadi: {e}")
        raise


def _handle_login(driver):
    """
    Eger site login sayfasina yonlendirmisse, otomatik giris yapar.
    Login bilgilerini schedule.json'daki 'login' alanindan okur.

    LMS login sayfasi yapisi:
      - URL: /Account/Login
      - Username: input#Username (type=text)
      - Password: input#Password (type=password)
      - RememberMe: input#RememberMe (checkbox)
      - Login: button.btn-primary (type=button, text=Giris)
    """
    try:
        # Login formu var mi kontrol et (sayfa yuklenene kadar bekle)
        username_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "Username"))
        )

        log.info("Login sayfasi tespit edildi, otomatik giris yapiliyor...")

        # Login bilgilerini schedule.json'dan oku
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        login_info = data.get("login", {})
        email = login_info.get("email", "")
        password = login_info.get("sifre", "")

        if not email or not password:
            log.error(
                "[HATA] Login bilgileri bulunamadi! "
                "schedule.json'a 'login' alani ekleyin: "
                '{"login": {"email": "...", "sifre": "..."}}'
            )
            return False

        # E-posta / kullanici adi gir
        username_field.clear()
        username_field.send_keys(email)
        log.info("[OK] Kullanici adi girildi.")
        time.sleep(0.5)

        # Sifre gir
        try:
            password_field = driver.find_element(By.ID, "Password")
            password_field.clear()
            password_field.send_keys(password)
            log.info("[OK] Sifre girildi.")
            time.sleep(0.5)
        except NoSuchElementException:
            log.error("[HATA] Sifre alani bulunamadi!")
            return False

        # Beni hatirla kutusunu isaretle (oturum kalici olsun)
        try:
            remember_me = driver.find_element(By.ID, "RememberMe")
            if not remember_me.is_selected():
                remember_me.click()
                log.info("[OK] 'Beni Hatirla' isaretlendi.")
        except Exception:
            pass

        # Giris butonuna tikla
        try:
            login_button = driver.find_element(By.CSS_SELECTOR,
                "button.btn-primary"
            )
            login_button.click()
            log.info("[OK] Giris butonuna tiklandi.")
            time.sleep(5)  # Login isleminin tamamlanmasini bekle

            # Login basarili mi kontrol et
            if "Login" not in driver.current_url:
                log.info("[OK] Giris basarili!")
                return True
            else:
                log.error("[HATA] Giris basarisiz! Kullanici adi veya sifre yanlis olabilir.")
                return False

        except NoSuchElementException:
            log.error("[HATA] Giris butonu bulunamadi!")
            return False

    except TimeoutException:
        # Login sayfasi degil, zaten giris yapilmis
        log.info("[OK] Zaten giris yapilmis durumda.")
        return True


# ─── Zoom Tarayıcı Katılım ───────────────────────────────────────────────────


def _join_zoom_from_browser(driver):
    """
    Zoom web client sayfasinda derse katilir.
    Dogrudan /wc/join/ URL'sine gidildigi icin
    modal dialoglari ve katilim adimlarini isler.

    Beklenen akis:
      1. Cookie popup → kapat
      2. Isim gir (varsa)
      3. "Katil" butonuna tikla
      4. Kamera/mikrofon modali → "Mikrofon ve kamera olmadan devam et"
      5. Derse katilim tamamlandi
    """
    log.info("Zoom web client'ta katilim islemleri basliyor...")

    try:
        # 1. Cookie popup varsa kapat
        try:
            cookie_btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.XPATH,
                    "//button[contains(text(), 'TÜM ÇEREZLERİ KABUL')] | "
                    "//button[contains(text(), 'Kabul')] | "
                    "//button[contains(text(), 'Accept')]"
                ))
            )
            cookie_btn.click()
            log.info("[OK] Cookie popup'i kapatildi.")
            time.sleep(1)
        except TimeoutException:
            pass

        # 2. Isim alani varsa doldur
        try:
            name_field = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "inputname"))
            )
            name_field.clear()
            name_field.send_keys("MEHMETHAN AKARSU")
            log.info("[OK] Isim girildi.")
            time.sleep(1)
        except TimeoutException:
            pass

        # 3. Kamera/Mikrofon modali — "Mikrofon ve kamera olmadan devam et"
        try:
            no_av_link = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH,
                    "//*[contains(text(), 'Mikrofon ve kamera olmadan devam et')] | "
                    "//*[contains(text(), 'mikrofon ve kamera olmadan')] | "
                    "//*[contains(text(), 'without microphone')] | "
                    "//*[contains(text(), 'Join without')] | "
                    "//a[contains(@class, 'link-btn')]"
                ))
            )
            no_av_link.click()
            log.info("[OK] 'Mikrofon ve kamera olmadan devam et' secildi!")
            time.sleep(3)

            # Modal'in kapanmasini bekle
            try:
                WebDriverWait(driver, 10).until(
                    EC.invisibility_of_element_located((By.XPATH,
                        "//div[contains(@class, 'zm-modal')]"
                    ))
                )
                log.info("[OK] Modal kapandi.")
            except TimeoutException:
                log.info("Modal hala gorunuyor olabilir, devam ediliyor...")
                time.sleep(2)

        except TimeoutException:
            log.info("Kamera/mikrofon modali bulunamadi, devam ediliyor...")

        # 4. "Katil" / "Join" butonu (modal kapandiktan sonra)
        try:
            join_btn = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH,
                    "//button[contains(@class, 'preview-join-button')] | "
                    "//button[contains(text(), 'Katıl')] | "
                    "//button[contains(text(), 'Join')] | "
                    "//button[@id='joinBtn']"
                ))
            )
            # JavaScript click — modal overlay'i bypass eder
            driver.execute_script("arguments[0].click();", join_btn)
            log.info("[OK] 'Katil' butonuna tiklandi!")
            time.sleep(5)
        except TimeoutException:
            log.info("Katil butonu bulunamadi, zaten katilim olmus olabilir.")

        # 5. Modal tekrar gelirse kapat (Toplantiya girdikten sonra cikan asil ses/kamera secimi)
        try:
            xpath_av = (
                "//*[contains(text(), 'Mikrofon ve kamera olmadan devam et')] | "
                "//*[contains(text(), 'mikrofon ve kamera olmadan')] | "
                "//*[contains(text(), 'without microphone')] | "
                "//*[contains(text(), 'Join without')]"
            )
            
            # Gizli (onceki adimdan kalan) butona tiklamamak icin sadece 'is_displayed()' olanlari hedefliyoruz
            visible_link = WebDriverWait(driver, 20).until(
                lambda d: next((el for el in d.find_elements(By.XPATH, xpath_av) if el.is_displayed()), None)
            )
            
            if visible_link:
                driver.execute_script("arguments[0].click();", visible_link)
                log.info("[OK] Ders-ici (3.) modal da kapatildi!")
                time.sleep(3)
        except TimeoutException:
            pass

        log.info("[BASARILI] Zoom dersine tarayicidan katilim tamamlandi!")

        # 6. "Got it" / "This meeting is being recorded" uyarısı varsa kapat
        try:
            recording_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH,
                    "//button[contains(text(), 'Got it')] | "
                    "//button[contains(text(), 'Anladım')] | "
                    "//button[contains(text(), 'Tamam')] | "
                    "//button[contains(@class, 'zm-btn--primary')]"
                ))
            )
            driver.execute_script("arguments[0].click();", recording_btn)
            log.info("[OK] 'Kayit uyarisi' (Got it/Tamam) kapatildi.")
        except TimeoutException:
            pass

    except Exception as e:
        log.error(f"[HATA] Zoom katiliminda hata: {e}")
        try:
            ss = SCRIPT_DIR / f"debug_zoom_{datetime.now().strftime('%H%M%S')}.png"
            driver.save_screenshot(str(ss))
            log.info(f"Debug screenshot: {ss}")
        except Exception:
            pass


# ─── Derse Katılma ───────────────────────────────────────────────────────────

def join_class(ders_adi: str, ders_kodu: str = "", bitis_saat: str = None):
    """
    LMS'e gidip derse katılır.

    Akış:
      1. Etkinlik Akışı sekmesine git
      2. Ders koduna göre ders kartını bul ve tıkla
      3. Canlı Ders sayfasında "Derse Katıl" butonunu bul ve tıkla
      4. Zoom açılır
    """
    log.info(f"--- Derse katilim baslatiliyor: {ders_adi} ({ders_kodu}) ---")

    driver = None
    try:
        driver = create_driver()

        # ── ADIM 1: LMS ana sayfasina git ────────────────────────────────
        log.info(f"LMS'ye gidiliyor: {LMS_URL}")
        driver.get(LMS_URL)
        time.sleep(4)

        # ── ADIM 1.5: Login gerekiyorsa otomatik giris yap ───────────
        if not _handle_login(driver):
            log.error("[HATA] Login yapilamadi, islem iptal ediliyor.")
            return
        # ── ADIM 2: "Etkinlik Akisi" sekmesine tikla ────────────────────
        log.info("'Etkinlik Akisi' sekmesi araniyor...")
        try:
            etkinlik_tab = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH,
                    "//a[contains(text(), 'ETKİNLİK AKIŞI')] | "
                    "//a[contains(text(), 'Etkinlik Akışı')] | "
                    "//a[contains(text(), 'ETKINLIK AKISI')] | "
                    "//span[contains(text(), 'ETKİNLİK AKIŞI')]/.. | "
                    "//div[contains(text(), 'ETKİNLİK AKIŞI')]"
                ))
            )
            etkinlik_tab.click()
            log.info("[OK] 'Etkinlik Akisi' sekmesine tiklandi.")
            time.sleep(4)  # Icerigin yuklenmesini bekle
        except TimeoutException:
            log.warning("'Etkinlik Akisi' sekmesi bulunamadi, sayfa zaten acik olabilir.")

        # ── ADIM 3: Ders kartini bul ve tikla ────────────────────────────
        log.info(f"Ders karti araniyor: {ders_kodu} / {ders_adi}...")

        ders_karti_bulundu = False
        try:
            # Ders koduna gore kart ara (orn: "MAT1072")
            # Etkinlik akisindaki kartlarda ders kodu gorunuyor
            xpath_ders = (
                f"//*[contains(text(), '{ders_kodu}')]//ancestor::a | "
                f"//*[contains(text(), '{ders_kodu}')]//ancestor::div[contains(@class, 'event') or contains(@class, 'card') or contains(@class, 'item') or @onclick] | "
                f"//a[contains(., '{ders_kodu}')] | "
                f"//div[contains(., '{ders_kodu}') and (contains(@class, 'event') or contains(@class, 'card') or contains(@class, 'item'))]"
            )

            ders_karti = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, xpath_ders))
            )
            log.info(f"[OK] Ders karti bulundu: {ders_kodu}")

            # Karta tikla — ders detay sayfasi acilacak
            ders_karti.click()
            ders_karti_bulundu = True
            log.info("[OK] Ders detay sayfasi aciliyor...")
            time.sleep(4)

        except TimeoutException:
            log.warning(f"Ders karti ({ders_kodu}) tiklanamadi, dogrudan ders adi ile deneniyor...")

            # Ders adi ile de dene
            try:
                xpath_ad = (
                    f"//*[contains(text(), '{ders_adi}')]//ancestor::a | "
                    f"//a[contains(., '{ders_adi}')] | "
                    f"//*[contains(text(), '{ders_adi}')]"
                )
                ders_karti = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, xpath_ad))
                )
                ders_karti.click()
                ders_karti_bulundu = True
                log.info(f"[OK] Ders karti bulundu (isim ile): {ders_adi}")
                time.sleep(4)
            except TimeoutException:
                log.error(f"[HATA] Ders karti bulunamadi: {ders_kodu} / {ders_adi}")

        # ── ADIM 4: "Canli Ders" sekmesinin acik oldugundan emin ol ──────
        if ders_karti_bulundu:
            try:
                canli_ders_tab = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH,
                        "//a[contains(text(), 'CANLI DERS')] | "
                        "//a[contains(text(), 'Canlı Ders')] | "
                        "//a[contains(text(), 'CANLI DERS')]"
                    ))
                )
                canli_ders_tab.click()
                log.info("[OK] 'Canli Ders' sekmesine tiklandi.")
                time.sleep(3)
            except TimeoutException:
                log.info("'Canli Ders' sekmesi zaten acik olabilir, devam ediliyor...")

        # ── ADIM 5: "Derse Katil" butonunu bul ve tikla ─────────────────
        log.info("'Derse Katil' butonu araniyor...")
        buton_bulundu = False

        for attempt in range(MAX_RETRY):
            try:
                katil_button = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.XPATH,
                        "//button[contains(text(), 'Derse Katıl')] | "
                        "//a[contains(text(), 'Derse Katıl')] | "
                        "//button[contains(text(), 'DERSE KATIL')] | "
                        "//a[contains(text(), 'DERSE KATIL')] | "
                        "//input[@value='Derse Katıl'] | "
                        "//button[contains(text(), 'Katıl')] | "
                        "//a[contains(text(), 'Katıl')] | "
                        "//td//a[contains(@href, 'zoom')] | "
                        "//td//button[contains(@onclick, 'zoom')] | "
                        "//*[contains(@class, 'join')]"
                    ))
                )

                log.info("[OK] 'Derse Katil' butonu bulundu! Tiklaniyor...")
                eski_pencere_sayisi = len(driver.window_handles)
                katil_button.click()
                buton_bulundu = True
                time.sleep(5)

                # Yeni sekme actiysa, oraya gec ve Zoom URL'sini al
                import re
                zoom_url = None

                if len(driver.window_handles) > eski_pencere_sayisi:
                    driver.switch_to.window(driver.window_handles[-1])
                    zoom_url = driver.current_url
                    log.info(f"[OK] Yeni sekmede URL: {zoom_url}")

                    # Chrome protokol popup'ini kapat (pyautogui ile Escape)
                    try:
                        import pyautogui
                        time.sleep(1)
                        pyautogui.press('escape')
                        log.info("[OK] Chrome popup'i kapatildi (Escape).")
                    except Exception:
                        pass

                if zoom_url and "zoom" in zoom_url:
                    # /w/MEETING_ID -> /wc/join/MEETING_ID
                    wc_url = re.sub(r'/w/(\d+)', r'/wc/join/\1', zoom_url)
                    log.info(f"[OK] Web client URL: {wc_url}")

                    # Dogrudan web client'a git (popup YOK!)
                    driver.get(wc_url)
                    log.info("[OK] Zoom web client'a yonlendirildi!")
                    time.sleep(5)

                    # Web client katilim islemleri
                    _join_zoom_from_browser(driver)
                else:
                    log.info(f"Zoom URL bulunamadi, mevcut URL: {driver.current_url}")

                break

            except TimeoutException:
                remaining = MAX_RETRY - attempt - 1
                if remaining > 0:
                    log.warning(
                        f"Buton bulunamadi, {RETRY_ARALIK}s sonra tekrar denenecek "
                        f"({remaining} deneme kaldi)..."
                    )
                    time.sleep(RETRY_ARALIK)
                    driver.refresh()
                    time.sleep(3)
                else:
                    log.error(
                        f"[HATA] {ders_adi} dersi icin 'Derse Katil' butonu bulunamadi. "
                        f"Ders henuz baslamamis olabilir."
                    )

        if not buton_bulundu:
            # Sayfanin ekran goruntusunu kaydet (debug icin)
            try:
                screenshot_path = SCRIPT_DIR / f"debug_{ders_kodu}_{datetime.now().strftime('%H%M%S')}.png"
                driver.save_screenshot(str(screenshot_path))
                log.info(f"Debug ekran goruntusu kaydedildi: {screenshot_path}")
            except Exception:
                pass

    except WebDriverException as e:
        log.error(f"[HATA] Tarayici hatasi: {e}")
    except Exception as e:
        log.error(f"[HATA] Beklenmeyen hata: {e}")
    finally:
        if driver:
            if buton_bulundu:
                # Zoom tarayicida acik, bitis saatine kadar bekle
                if bitis_saat:
                    try:
                        simdi = datetime.now()
                        bitis_obj = datetime.strptime(bitis_saat, "%H:%M")
                        bitis_vakti = simdi.replace(hour=bitis_obj.hour, minute=bitis_obj.minute, second=0, microsecond=0)
                        
                        # Eger bitis vakti gectiyse (gece dersi vb.), yarına atama yapma, sadece bekleme
                        bekleme_suresi = (bitis_vakti - simdi).total_seconds()
                        
                        if bekleme_suresi > 0:
                            log.info(f"Zoom tarayicida acik. Ders {bitis_saat}'de bitecek ({int(bekleme_suresi/60)} dk kaldi).")
                            time.sleep(bekleme_suresi)
                            log.info("Ders bitis saati geldi.")
                        else:
                            log.info(f"Ders bitis saati ({bitis_saat}) zaten gecmis veya su an.")
                    except Exception as e:
                        log.error(f"Bitis saati hesaplama hatasi: {e}")
                        log.info("Otomatik kapanma devre disi, tarayici acik kalacak.")
                        # Eski davranis: hic kapatma
                        pass
                else:
                    log.info("Bitis saati belirtilmemis, tarayici acik kalacak.")
                    return # Kapatmadan cik (detach modu devrede)
            else:
                # Buton bulunamadiysa biraz bekle ve kapat
                time.sleep(10)

            try:
                driver.quit()
                log.info("Tarayici kapatildi.")
            except Exception:
                pass


# ─── Zamanlayıcı ─────────────────────────────────────────────────────────────

def setup_scheduler(dersler: list) -> BlockingScheduler:
    """APScheduler ile ders programini zamanlar."""
    scheduler = BlockingScheduler()

    for ders in dersler:
        gun = ders["gun"]
        saat_str = ders["saat"]
        ad = ders["ad"]
        kod = ders.get("kod", "")

        bitis = ders.get("bitis")

        cron_gun = GUN_MAP.get(gun)
        if not cron_gun:
            log.error(f"Gecersiz gun: '{gun}' -- {ad} dersi atlandi.")
            continue

        # Saati parse et
        try:
            saat_obj = datetime.strptime(saat_str, "%H:%M")
        except ValueError:
            log.error(f"Gecersiz saat formati: '{saat_str}' -- {ad} dersi atlandi.")
            continue

        # Dersten DAKIKA_ONCE dakika once calistir
        erken = saat_obj - timedelta(minutes=DAKIKA_ONCE)

        trigger = CronTrigger(
            day_of_week=cron_gun,
            hour=erken.hour,
            minute=erken.minute,
        )

        scheduler.add_job(
            join_class,
            trigger=trigger,
            args=[ad, kod, bitis],
            id=f"ders_{kod or ad.replace(' ', '_')}",
            name=f"{kod} {ad} ({gun} {saat_str})",
            misfire_grace_time=300,  # 5 dakika tolerans
        )

        erken_str = erken.strftime("%H:%M")
        log.info(
            f"  {kod} {ad} -> {gun} {erken_str}'de tetiklenecek "
            f"(ders saati: {saat_str})"
        )

    return scheduler


def show_status(dersler: list):
    """Aktif ders programini gosterir."""
    print("\n+===========================================================+")
    print("|         YTU Otomatik Derse Katilim Botu                    |")
    print("+===========================================================+")

    if not dersler:
        print("|  Aktif ders bulunamadi!                                   |")
        print("|  schedule.json dosyasini duzenleyin.                      |")
    else:
        print(f"|  {len(dersler)} aktif ders planlanmis:                                |")
        print("+-----------------------------------------------------------+")
        for ders in dersler:
            kod = ders.get('kod', '').ljust(10)
            ad = ders['ad'][:18].ljust(18)
            gun_saat = f"{ders['gun'][:4]} {ders['saat']}".ljust(12)
            print(f"|  {kod} {ad} | {gun_saat}    |")

    print("+===========================================================+\n")


# ─── Ana Program ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="YTÜ Otomatik Derse Katılım Botu",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python auto_joiner.py           Normal mod - zamanlayıcı başlar
  python auto_joiner.py --test    Hemen derse katılmayı dener
  python auto_joiner.py --status  Planlanmış dersleri gösterir
        """,
    )
    parser.add_argument("--test", action="store_true", help="Test modu: hemen katilmayi dener")
    parser.add_argument("--ders", type=str, default=None,
                        help="Test icin ders kodu (orn: MAT1072)")
    parser.add_argument("--status", action="store_true", help="Aktif ders programini gosterir")
    parser.add_argument("--profile", type=str, default=None,
                        help="Chrome profil adi (varsayilan: Default)")

    args = parser.parse_args()

    # Chrome profili override
    global CHROME_PROFILE
    if args.profile:
        CHROME_PROFILE = args.profile
        log.info(f"Chrome profili: {CHROME_PROFILE}")

    # Program yukle
    dersler = load_schedule()

    if args.status:
        show_status(dersler)
        return

    if args.test:
        log.info("TEST MODU -- Hemen derse katilim deneniyor...")
        if args.ders:
            # Belirli bir ders kodu ile test et
            ders_bilgi = next((d for d in dersler if d.get("kod") == args.ders), None)
            if ders_bilgi:
                join_class(ders_bilgi["ad"], ders_bilgi["kod"], ders_bilgi.get("bitis"))
            else:
                log.info(f"Ders kodu '{args.ders}' schedule.json'da bulunamadi, genel test yapiliyor...")
                join_class("TEST DERS", args.ders)
        elif dersler:
            # Ilk aktif dersi test et
            ilk_ders = dersler[0]
            log.info(f"Ilk aktif ders test ediliyor: {ilk_ders['ad']} ({ilk_ders.get('kod', '')})")
            join_class(ilk_ders["ad"], ilk_ders.get("kod", ""))
        else:
            join_class("TEST DERS", "")
        return

    if not dersler:
        log.warning("⚠️  Aktif ders bulunamadı! schedule.json dosyasını düzenleyin.")
        log.info("Örnek: Bir dersin 'aktif' değerini true yapın.")
        return

    # Zamanlayıcıyı başlat
    show_status(dersler)
    log.info("🚀 Zamanlayıcı başlatılıyor... (Durdurmak için Ctrl+C)")
    log.info(f"📍 Dersten {DAKIKA_ONCE} dakika önce otomatik katılım yapılacak.")
    log.info("")

    scheduler = setup_scheduler(dersler)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("\n👋 Bot durduruldu. Görüşmek üzere!")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
