# QUANTX AI — Enterprise AI Trading Platform

## Cara pakai dokumen ini
Paste seluruh isi file ini (dari sini sampai akhir) sebagai pesan pertama ke
`ecc-autonomous`. Simpan file ini di root repo sebagai `docs/VISION.md` —
setiap sesi baru ke depannya, cukup rujuk balik ke `docs/VISION.md` +
`docs/RELEASE-PLAN.md` (dijelaskan di bawah), tidak perlu paste ulang semuanya.

---

## Peran kamu

Kamu adalah tim engineering lengkap untuk QuantX AI: Lead Software Architect,
Principal Engineer, Product Manager, UX Architect, Security Engineer, DevOps
Engineer, AI Engineer, dan Technical Writer sekaligus. Ini bukan demo, bukan
proyek portofolio, bukan sekadar MVP asal jalan — kode, arsitektur, dan
dokumentasi harus setara standar yang dipegang tim engineering di Google,
Stripe, Bloomberg, atau OpenAI.

Standar itu artinya: setiap yang kamu klaim selesai harus benar-benar
dijalankan dan diverifikasi (bukan diasumsikan selesai), bukan berarti kamu
membangun semua fitur sekaligus tanpa fondasi yang solid.

## Visi produk (north star — dibangun bertahap, lihat Release Plan di bawah)

**Tujuan:** platform trading algoritmik berbasis AI, mencakup: analisis
pasar, pengembangan strategi, paper trading, manajemen portofolio,
manajemen risiko, dukungan keputusan berbasis AI, intelijen berita,
backtesting, optimasi strategi, dan (fase jauh ke depan, tetap OFF secara
default) live trading dengan uang sungguhan.

**Rilis pertama: web only.** Tidak ada Android/iOS/desktop/Telegram di fase
awal manapun.

## Prinsip arsitektur (berlaku sejak baris kode pertama)

- Clean Architecture, DDD, SOLID
- Repository Pattern, Dependency Injection, Unit of Work
- Domain Events + Event Bus (in-process dulu, bukan message broker terpisah,
  sampai ada bukti nyata butuh itu)
- **Modular Monolith — bukan microservices.** Batas antar modul jelas lewat
  package/namespace, bukan lewat network call, sampai ada alasan konkret
  untuk memisah jadi layanan sendiri.
- CQRS hanya diterapkan di modul yang benar-benar butuh (mis. reporting
  berat), bukan dipaksakan di semua tempat sejak awal.

## Stack

**Backend:** Python, FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL, Redis,
Celery, WebSocket, Pydantic v2, JWT + OAuth2, OpenAPI/REST.

**Frontend:** Next.js, React, TypeScript, TailwindCSS, shadcn/ui, React
Query, Zustand, React Hook Form, Framer Motion, Recharts.

**Auth:** Email login, Google login, GitHub login, 2FA, JWT + refresh token,
RBAC dengan permission granular.

## Domain data (skema produksi, bukan draft)

Users, Roles, Permissions, Trading Accounts, Strategies, Orders, Positions,
Trades, Portfolio, Assets, Risk Profiles, Notifications, News, Signals,
Watchlists, Market Data, Logs, Audit Logs, System Settings, AI Models, AI
Memory.

## Modul aplikasi (daftar lengkap — urutan pembangunan ada di Release Plan)

Dashboard, Portfolio, Trading, Market, Watchlist, Strategies, AI Assistant,
Risk Management, Backtesting, Optimization, Paper Trading, News
Intelligence, Market Intelligence, Economic Calendar, Notifications,
Reports, Analytics, Settings, Profile, Admin Panel.

## Dashboard (isi minimum)

Nilai portofolio, profit hari ini/bulan ini, alokasi aset, posisi terbuka,
trade terbaru, ringkasan pasar, fear & greed index, top movers, rekomendasi
AI, skor risiko, grafik performa, feed berita, system health.

## Fitur AI (dibangun bertahap — jangan dipaksa semua di rilis pertama)

Market Intelligence Engine, News Intelligence Engine, Sentiment Engine,
Whale Tracking, Pattern Recognition, Technical Analysis Engine, Fundamental
Analysis Engine, Portfolio Advisor, Risk Advisor, Strategy Optimizer,
Adaptive Learning, Decision Engine, Memory Engine.

## Manajemen risiko (WAJIB ada sejak slice trading pertama, tidak boleh ditunda)

Daily loss limit, max drawdown, position limit, exposure limit, kill switch,
circuit breaker, slippage control, spread protection, risk scoring,
validation layer di setiap jalur order.

## Keamanan (non-negotiable)

OWASP Top 10, rate limiting, CSRF protection, CORS yang benar, validasi
input di setiap boundary, enkripsi data sensitif, secrets lewat environment
variable/secrets manager (tidak pernah hardcode), audit trail untuk setiap
aksi yang mengubah state finansial.

**Aturan keras soal uang sungguhan:** jalur eksekusi order ke exchange
nyata (bukan paper trading) harus ada strukturnya di kode sejak awal, tapi
**wajib default OFF** lewat flag config eksplisit, sampai saya yang
menyalakannya secara manual. Ini bukan permintaan approval ke kamu — ini
default aman yang harus ada di kode itu sendiri.

## Observability

Structured logging, metrics, tracing, audit logs, health checks, monitoring
dasar — sejak slice pertama, bukan ditambahkan belakangan sebagai
"technical debt".

## Testing & CI/CD

Unit test, integration test, API test, frontend test, E2E test untuk
setiap modul yang kamu klaim selesai. GitHub Actions untuk lint, format,
test, security scan, build, deployment pipeline.

## Dokumentasi wajib

Architecture overview, ERD, API docs (OpenAPI), development guide, coding
standards, security guide, deployment guide, testing guide, Architecture
Decision Records per keputusan besar, CHANGELOG, dan `docs/RELEASE-PLAN.md`
(lihat di bawah) yang selalu kamu perbarui statusnya.

## User experience

Kualitas setara Bloomberg Terminal / TradingView / Stripe Dashboard /
Linear — bukan template dashboard admin generik. Dark mode + light mode,
tipografi jelas, spacing konsisten, animasi halus dan bertujuan (bukan
dekorasi kosong). Ikuti pedoman anti-pola generik yang sudah jadi standar
kerjamu (hindari gradient generik, hero copy besar tanpa isi, card
bertumpuk card).

## Aturan kerja (non-negotiable)

Jangan pernah membuat kode placeholder, implementasi TODO, atau
pseudo-code. Setiap fitur yang kamu klaim selesai harus benar-benar
lengkap dan sudah diverifikasi jalan (dijalankan, bukan cuma dibaca
ulang). Setiap commit ikut conventional commits. Jangan pindah ke fitur
berikutnya sebelum fitur saat ini benar-benar selesai dan tervalidasi.

Untuk setiap fitur yang kamu bangun, urutannya: (1) jelaskan alasannya,
(2) rancang arsitekturnya, (3) daftar file yang akan dibuat/diubah,
(4) implementasi, (5) test, (6) update dokumentasi, (7) catat perbaikan
yang bisa dilakukan ke depan.

## Non-functional requirements & standar operasional (yang sering dilewatkan)

Ini yang sebenarnya membedakan "daftar fitur lengkap" dari sistem yang
benar-benar dipercaya berjalan di produksi. Tanpa ini, platform tetap
terlihat lengkap tapi rapuh begitu dipakai sungguhan:

- **Idempotency order.** Setiap permintaan buka/tutup posisi harus punya
  idempotency key. Kalau request diulang (retry jaringan, klik dobel),
  sistem tidak boleh membuat order duplikat. Ini bukan opsional untuk
  sistem trading — order duplikat = kerugian nyata.
- **Waktu & urutan kejadian.** Semua timestamp disimpan UTC di database,
  dikonversi ke lokal cuma di frontend. Order dan trade harus punya urutan
  yang bisa direkonstruksi ulang (sequence number atau timestamp presisi
  tinggi), bukan cuma "created_at" biasa.
- **Reproduksibilitas backtesting.** Data historis yang dipakai backtest
  harus di-snapshot (versi/tanggal tetap), supaya hasil backtest yang sama
  bisa direproduksi ulang kapan saja — bukan menghitung ulang dari data
  yang terus berubah.
- **Pemisahan environment.** Config dev/staging/production terpisah jelas
  (bukan cuma satu file `.env` yang diubah manual). Kredensial exchange
  sandbox dan kredensial produksi (kalau nanti Fase 5 aktif) tidak boleh
  bisa tertukar karena kesalahan konfigurasi.
- **Backup & disaster recovery untuk data trading.** Riwayat trade,
  posisi, dan strategi adalah data yang tidak boleh hilang — minimal ada
  strategi backup database yang didokumentasikan (bukan harus rumit,
  cukup jelas dan teruji sekali).
- **Governance biaya.** Karena ini berjalan di budget infrastruktur minim,
  setiap panggilan ke API eksternal (harga real-time, AI inference, data
  berita) harus dicatat biayanya. Pakai skill `ECC\skills\cost-report`
  (lewat command `/cost-report`) untuk melacak ini secara berkala — jangan
  sampai satu fitur AI diam-diam menghabiskan seluruh budget bulanan.
- **Disclaimer legal di UI.** Karena ini platform trading (meski masih
  paper trading), wajib ada teks yang jelas di footer/halaman terkait:
  bukan nasihat keuangan, risiko trading ditanggung pengguna sendiri.
  Ini bukan fitur estetika — ini perlindungan dasar buat kamu sebagai
  pembuatnya.
- **Incident log ringan.** Kalau ada kegagalan sistem (misal koneksi
  exchange putus di tengah strategi jalan), catat kejadiannya di
  `docs/INCIDENTS.md`: apa yang terjadi, dampaknya, apa yang diperbaiki.
  Tidak perlu proses formal rumit, cukup konsisten dicatat.

Terapkan poin-poin ini sejak Fase 0-1, bukan ditunda ke fase lanjutan —
inilah yang sebenarnya dimaksud "enterprise-grade": bukan menu fitur yang
banyak, tapi hal-hal di atas yang jarang terlihat sampai sesuatu gagal.

## Tiga hal teknis spesifik-trading yang sering terlewat

- **Rate limit sisi exchange, bukan cuma sisi kita.** Testnet/sandbox
  exchange punya limit permintaan sendiri (mis. berapa kali per menit
  boleh polling harga). Kalau strategi/loop polling melebihi itu, akun
  bisa kena throttle atau ban sementara. Implementasikan backoff (delay
  bertahap) saat exchange menolak karena rate limit, jangan cuma retry
  langsung berulang.
- **Reconnect WebSocket dengan backoff.** Koneksi harga real-time via
  WebSocket akan terputus sesekali (jaringan, restart server exchange).
  Sistem harus otomatis coba sambung ulang dengan jeda yang meningkat
  (mis. 1s, 2s, 5s, 10s, lalu tetap di situ), dan tampilkan status
  "terputus/menyambung ulang" di UI — jangan diam-diam gagal tanpa
  indikasi ke user.
- **Definition of Done eksplisit untuk Fase 0 dan Fase 1** (supaya
  evaluator punya tolok ukur konkret, bukan menilai "kelihatan selesai"):
  - Fase 0 selesai kalau: user bisa daftar+login, skema DB ter-migrate
    bersih dari nol, CI hijau (lint+test) di commit terakhir, ada
    endpoint health-check yang benar-benar dicek jalan.
  - Fase 1 selesai kalau: user bisa login → lihat harga real-time
    (WebSocket benar-benar mengalir, dites dengan reconnect di atas) →
    jalankan 1 strategi sederhana di paper trading → strategi itu
    benar-benar mengeksekusi minimal 1 order simulasi → order itu
    muncul di dashboard dengan P&L yang terhitung benar → risk limit
    (daily loss limit minimal) benar-benar menghentikan strategi kalau
    limit itu dilanggar (diuji dengan skenario yang sengaja memicu itu,
    bukan cuma dibaca kodenya).

---

Bangun visi di atas **secara bertahap**, bukan sekaligus. Buat file
`docs/RELEASE-PLAN.md` di awal kerja berisi tabel fase seperti ini, lalu
perbarui statusnya setiap kali sebuah fase selesai:

- **Fase 0 — Fondasi:** scaffold monorepo, auth (email + JWT, Google/GitHub
  boleh menyusul), skema database inti (Users, Trading Accounts, Assets),
  CI dasar (lint+test), observability dasar. Tidak ada fitur trading sama
  sekali di fase ini — cuma fondasi yang benar-benar solid.
- **Fase 1 — MVP Paper Trading:** modul Dashboard (versi minimum), Trading,
  Portfolio, Watchlist, Paper Trading, Risk Management (semua kontrol wajib
  di atas harus aktif). Ini rilis pertama yang harus benar-benar bisa
  dipakai end-to-end: login → lihat harga → jalankan 1 strategi sederhana
  di paper trading → lihat hasilnya di dashboard.
- **Fase 2 — Intelijen:** News Intelligence, Market Intelligence, satu AI
  engine dulu (mis. Technical Analysis Engine) yang benar-benar terhubung
  ke keputusan trading, bukan sekadar tampilan.
- **Fase 3 — Analisis lanjutan:** Backtesting, Strategy Optimization,
  Analytics, Reports.
- **Fase 4 — Perluasan AI & admin:** sisa AI engine, Admin Panel, RBAC
  granular penuh, Economic Calendar, Notifications lengkap.
- **Fase 5 — Live trading (jauh ke depan):** hanya dikerjakan kalau saya
  minta eksplisit nanti. Sampai saat itu, jalurnya tetap ada di kode tapi
  mati secara default sesuai aturan keamanan di atas.

**Untuk sesi kerja pertama ini: kerjakan Fase 0 dan Fase 1 sampai benar-benar
selesai dan tervalidasi (bisa dijalankan end-to-end, semua test hijau,
semua kontrol risiko aktif). Jangan mulai Fase 2 ke atas di sesi ini** —
lebih baik Fase 0-1 benar-benar solid daripada 5 fase sekaligus tapi
dangkal semua.

Jalankan penuh secara otonom dari Plan sampai Report tanpa berhenti minta
approval saya di tengah jalan. Kalau kamu harus pindah ke task baru karena
context penuh, tulis handoff lengkap dulu ke `docs/RELEASE-PLAN.md` dan
`gan-harness/handoff.md` sebelum berhenti.