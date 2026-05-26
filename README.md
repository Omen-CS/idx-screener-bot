# IDX Momentum Screener Bot

Telegram bot yang secara otomatis memindai saham Indonesia (IDX) dan mengirim sinyal momentum trading.

## Fitur

- **BPJS** (Beli Pagi Jual Sore) — scan intraday momentum pagi hari (09:00 WIB)
- **BSJP** (Beli Sore Jual Pagi) — scan overnight continuation sore hari (14:00 WIB)
- Scan otomatis via scheduler (APScheduler)
- Scan manual via command Telegram
- Ranking berdasarkan scoring system
- Filter untuk menghindari pump-and-dump

## Stack Teknologi

- Python 3.11+
- python-telegram-bot v20
- yfinance (data pasar real)
- pandas + numpy (kalkulasi)
- ta (indikator teknikal)
- APScheduler (penjadwalan)
- Railway (deployment)

---

## Setup Cepat

### 1. Clone & Install

```bash
git clone <your-repo>
cd idx-screener-bot

pip install -r requirements.txt
```

### 2. Konfigurasi Environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

**Cara mendapatkan Bot Token:**
1. Buka Telegram, cari `@BotFather`
2. Kirim `/newbot`
3. Ikuti instruksi, copy token yang diberikan

**Cara mendapatkan Chat ID:**
1. Cari `@userinfobot` di Telegram
2. Kirim `/start`
3. Bot akan memberikan ID kamu

Untuk grup: forward pesan dari grup ke `@userinfobot` atau gunakan prefix `-` (contoh: `-1001234567890`)

### 3. Jalankan Lokal

```bash
python main.py
```

---

## Deploy ke Railway

### Option A: Deploy via GitHub

1. Push project ke GitHub
2. Buka [railway.app](https://railway.app)
3. New Project → Deploy from GitHub Repo
4. Pilih repo kamu
5. Set environment variables di Railway dashboard:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
6. Deploy otomatis!

### Option B: Deploy via Railway CLI

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Init project
railway init

# Set env vars
railway variables set TELEGRAM_BOT_TOKEN=your_token
railway variables set TELEGRAM_CHAT_ID=your_chat_id

# Deploy
railway up
```

---

## Perintah Bot

| Perintah | Fungsi |
|----------|--------|
| `/start` | Tampilkan welcome message dan daftar perintah |
| `/bpjs` | Jalankan scan BPJS manual |
| `/bsjp` | Jalankan scan BSJP manual |
| `/scan` | Jalankan kedua scan sekaligus |
| `/top` | Tampilkan kandidat terbaik dalam format ringkasan |

---

## Scanner Logic

### BPJS — Intraday Morning Momentum

**Waktu:** 09:00 WIB (otomatis) atau manual via `/bpjs`

**Kriteria:**
1. Relative volume > 3x rata-rata 5 hari
2. Price sudah bergerak 2%-7% dari open
3. Break morning high (30 menit pertama)
4. Candle bullish
5. Higher low structure
6. Di atas EMA20
7. Di atas VWAP
8. Nilai transaksi > 1 Miliar IDR

**Hindari:**
- RSI > 85
- Upper wick besar
- Saham illiquid
- Pump-and-dump

**Scoring (100 poin):**
- +25 Volume Explosion
- +25 Breakout Strength
- +20 Bullish Structure
- +15 Above VWAP
- +15 Momentum Continuation

---

### BSJP — Afternoon Close Setup

**Waktu:** 14:00 WIB (otomatis) atau manual via `/bsjp`

**Kriteria:**
1. Close dekat day high (≥92% dari range)
2. Volume jam terakhir kuat
3. Break daily resistance
4. Higher low structure
5. Upper wick kecil
6. EMA20 bullish
7. Candle bullish
8. Pola accumulation sore

**Hindari:**
- Weak close
- Afternoon dump
- Panic selling
- Choppy structure

**Scoring (100 poin):**
- +30 Strong Close
- +25 Breakout Quality
- +20 Accumulation Volume
- +15 Bullish Trend
- +10 Low Selling Pressure

---

## Struktur Proyek

```
project/
├── bot/
│   ├── handlers/          # Command handlers Telegram
│   │   ├── start.py       # /start
│   │   ├── scan.py        # /scan
│   │   ├── bpjs.py        # /bpjs
│   │   ├── bsjp.py        # /bsjp
│   │   └── top.py         # /top
│   └── utils/
│       └── formatter.py   # Format pesan Telegram
│
├── screener/
│   ├── indicators.py      # EMA, RSI, VWAP, dll
│   ├── scanner.py         # Orkestrasi scan utama
│   ├── scoring.py         # Sistem scoring BPJS/BSJP
│   ├── patterns.py        # Deteksi pola candle/struktur
│   └── tickers.py         # Daftar ticker IDX
│
├── services/
│   ├── market_data.py     # Fetching data dari yfinance
│   ├── scheduler_service.py # APScheduler jobs
│   └── telegram_service.py  # Kirim pesan via Bot API
│
├── config/
│   └── settings.py        # Konfigurasi terpusat
│
├── logs/                  # Log files
├── main.py                # Entry point
├── requirements.txt
├── Procfile
├── runtime.txt
├── railway.json
└── .env.example
```

---

## Konfigurasi

Semua parameter bisa diubah di `config/settings.py`:

```python
# Threshold BPJS
BPJS_MIN_RELATIVE_VOLUME = 3.0    # Ubah jika ingin lebih/kurang sensitif
BPJS_MIN_PRICE_MOVE_PCT = 2.0     # Minimum move dari open
BPJS_MIN_TRADED_VALUE_IDR = 1_000_000_000  # Minimum likuiditas

# Threshold BSJP
BSJP_CLOSE_NEAR_HIGH_RATIO = 0.92  # Seberapa dekat close dari high
BSJP_MIN_LAST_HOUR_VOL_RATIO = 1.5 # Volume jam terakhir vs rata-rata

# Umum
TOP_N_RESULTS = 10                 # Jumlah hasil per scan
MIN_SCORE_THRESHOLD = 50           # Score minimum untuk masuk alert
```

---

## Disclaimer

⚠️ **BUKAN SARAN KEUANGAN**

Bot ini adalah alat screening teknikal. Sinyal yang dihasilkan tidak menjamin profit. Selalu lakukan riset sendiri (DYOR) sebelum trading. Trading saham mengandung risiko kerugian. Penulis tidak bertanggung jawab atas keputusan trading yang dibuat berdasarkan output bot ini.

---

## Lisensi

MIT License — bebas digunakan dan dimodifikasi.
