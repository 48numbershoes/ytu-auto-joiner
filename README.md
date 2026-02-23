# YTU Auto Joiner 🎓

YTÜ (Yıldız Teknik Üniversitesi) LMS üzerinden canlı derslere **otomatik katılım** botu.

## Ne Yapar?

- ⏰ Ders programına göre otomatik olarak derslere katılır
- 🔐 LMS'ye otomatik giriş yapar
- 🖥️ Zoom'u **tarayıcıdan** açar (masaüstü uygulaması gerekmez)
- 🔇 Mikrofon ve kamera **kapalı** olarak katılır
- 📋 Tüm işlemleri loglar (`bot.log`)

## Kurulum

### 1. Gereksinimler

- Python 3.10+
- Google Chrome

### 2. Bağımlılıkları Yükle

```bash
pip install -r requirements.txt
```

### 3. Ders Programını Ayarla

`schedule.example.json` dosyasını kopyala ve bilgilerini doldur:

```bash
copy schedule.example.json schedule.json
```

`schedule.json` içeriği:

```json
{
  "login": {
    "email": "OGRENCI_NUMARASI@std.yildiz.edu.tr",
    "sifre": "SIFREN"
  },
  "dersler": [
    {
      "ders_adi": "Matematik 2",
      "ders_kodu": "MAT1072",
      "gun": "Pazartesi",
      "saat": "09:00",
      "aktif": true
    }
  ]
}
```

> ⚠️ `schedule.json` dosyası `.gitignore`'da — kişisel bilgilerin paylaşılmaz.

## Kullanım

### Normal Mod (Zamanlayıcı)

```bash
python auto_joiner.py
```

Bot ders saatlerini bekler ve zamanı gelince otomatik katılır.

### Test Modu

Hemen bir derse katılmayı denemek için:

```bash
python auto_joiner.py --test --ders MAT1072
```

## Nasıl Çalışır?

```
1. LMS'ye giriş yap
2. Etkinlik Akışı → Ders kartını bul
3. Canlı Ders → "Derse Katıl" butonuna tıkla
4. Zoom URL'sini web client formatına dönüştür
5. Mikrofon/kamera olmadan katıl
6. Tarayıcıda 90dk açık kal
```

## Dosya Yapısı

```
├── auto_joiner.py          # Ana bot kodu
├── schedule.json           # Ders programı + login (GİZLİ)
├── schedule.example.json   # Örnek config
├── requirements.txt        # Python bağımlılıkları
├── .gitignore
└── README.md
```

## Notlar

- İlk çalıştırmada Chrome profili oluşturulur (`bot_chrome_profile/`)
- Giriş yapıldıktan sonra oturum profilde kalır
- Her ders için ayrı Chrome penceresi açılır
- `bot.log` dosyasından tüm işlemleri takip edebilirsin
