# 🎓 YTÜ Otomatik Derse Katılım Botu

Yıldız Teknik Üniversitesi online ders sistemine (`online.yildiz.edu.tr`) otomatik katılım sağlayan Python botu.

## 🚀 Kurulum

```bash
# 1. Bağımlılıkları yükle
pip install -r requirements.txt

# 2. Ders programını düzenle
# schedule.json dosyasını aç ve derslerini ekle
```

## 📋 Ders Programı (schedule.json)

```json
{
  "dersler": [
    {
      "ad": "Fizik II",
      "gun": "Pazartesi",
      "saat": "09:00",
      "aktif": true
    }
  ]
}
```

- **aktif**: `true` → bot bu derse katılır, `false` → atlanır
- **gun**: Pazartesi, Salı, Çarşamba, Perşembe, Cuma, Cumartesi, Pazar
- **saat**: 24 saat formatı (ör: `"14:30"`)

## 🎮 Kullanım

```bash
# Normal mod - zamanlayıcı başlar, ders saatinde otomatik katılır
python auto_joiner.py

# Test modu - hemen LMS'ye gidip "Derse Katıl" butonunu arar
python auto_joiner.py --test

# Aktif dersleri göster
python auto_joiner.py --status

# Farklı Chrome profili kullan
python auto_joiner.py --profile "Profile 1"
```

## ⚡ Önemli Notlar

1. **Chrome kapalı olmalı** — Selenium çalışırken Chrome tarayıcısı kapalı olmalı
2. **Zoom ayarı** — Zoom > Settings > Audio > ✅ "Mute my microphone when joining a meeting"
3. **Oturum** — Chrome'da `online.yildiz.edu.tr`'ye daha önce giriş yapmış olmalısınız
4. **Zamanlama** — Bot dersten **2 dakika önce** otomatik olarak katılır

## 📁 Dosyalar

| Dosya | Açıklama |
|-------|----------|
| `auto_joiner.py` | Ana otomasyon scripti |
| `schedule.json` | Haftalık ders programı |
| `bot.log` | Çalışma logları |
| `requirements.txt` | Python bağımlılıkları |
