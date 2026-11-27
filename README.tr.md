<p align="right">
  <strong>Dil:</strong> <a href="README.md">English</a> · Türkçe
</p>

# LeadRadar

LeadRadar; potansiyel müşterileri bulmak, dijital varlıklarını denetlemek, onları puanlamak ve bir CRM üzerinden yönetmek için geliştirilmiş, kendi sunucunuzda çalışan bir platformdur. Web tasarım, dijital pazarlama, reklam yönetimi ve benzeri hizmetler satan ajanslar ve serbest çalışanlar için tasarlanmıştır.

LeadRadar **kural tabanlıdır**: yapay zekâ, LLM veya yapay zekâ API'leri kullanmaz. Tüm otomatik sonuçlar belirleyici, kanıta dayalı ve tekrarlanabilirdir. Arayüzün tamamı **Türkçe ve İngilizce** olarak kullanılabilir.

> **Kurulum:** adım adım rehberi izleyin → **[Dokploy kurulumu (Türkçe)](docs/deployment-dokploy.tr.md)** · [Installing on Dokploy (English)](docs/deployment-dokploy.md)

---

## Neler yapar?

- **Keşif:** Seçilen ülke ve sektörlerdeki işletmeleri OpenStreetMap'ten (Geofabrik özet dosyaları) içe aktarır. Şirketleri manuel olarak, web sitesi adresinden (Hızlı Denetim), CSV dosyasından veya isteğe bağlı Apify entegrasyonuyla da ekleyebilirsiniz.
- **Web sitesi denetimi:** HTTP ve TLS kontrolleri, SEO, dönüşüm ve iletişim kontrolleri, kırık bağlantı ve görseller, Playwright ile mobil ve masaüstü ekran görüntüleri, belirleyici görsel kontroller, axe-core erişilebilirlik testleri ve Lighthouse laboratuvar performans ölçümleri.
- **İzleme teknolojisi tespiti:** Google Tag Manager, GA4, Google Ads, Meta Pixel, LinkedIn, TikTok, Microsoft UET, Clarity, Hotjar ve çerez onay platformları. Her sonuç belirsizliğiyle birlikte kaydedilir: "algılanmadı" sonucu, izlemenin olmadığının kanıtı sayılmaz.
- **Reklam araştırması:** Meta, Google, LinkedIn, TikTok, Microsoft ve ChatGPT için birbirinden bağımsız sağlayıcılar. Yalnızca resmi kaynaklar kullanılır; otomasyona izin verilmeyen platformlar "Desteklenmiyor" olarak işaretlenir ve manuel araştırma bağlantısı sunulur. Sonuçlar asla uydurulmaz.
- **Yönetici incelemesi:** Her tam denetim, siz inceleme sorularını yanıtlayana kadar *İşlem gerekli* durumunda bekler. Tasarım kalitesi veya marka gibi öznel değerlendirmeler asla otomatik yapılmaz.
- **Puanlama:** Açıklanabilir potansiyel müşteri puanı, güven puanı ve hizmet fırsatı puanları; yapılandırılabilir puanlama profilleri ve manuel geçersiz kılma.
- **CRM:** Sunucu taraflı filtreleme yapan şirket tablosu, etiketler, kayıtlı filtreler, Kanban süreç görünümü, etkinlik zaman çizelgesi ve takip tarihleri. Sistem genelindeki "İletişime Geçme" listesi yeniden içe aktarmalardan sonra da geçerli kalır.
- **Müşteri raporları:** Özel taslaklar, yönetici onayı; iptal edilebilen, parolayla korunabilen veya süresi dolabilen herkese açık bağlantılar, canlı veya anlık görüntü modu. Türkçe ve İngilizce PDF çıktısı.
- **Operasyon:** PostgreSQL tabanlı kalıcı iş kuyruğu (tarayıcıyı kapatsanız da işler devam eder), izleme ve değişiklik tespiti, veri saklama politikaları, bildirimler, sistem durumu sayfası ve maliyet takibi.

## Mimari özeti

| Servis | Görevi |
|---|---|
| `web` | Next.js yönetim arayüzü. Dışarıya açılan tek servistir; `/api` ve `/r` isteklerini aynı köken üzerinden API'ye iletir. |
| `api` | FastAPI REST API'si ve herkese açık rapor sayfaları. Açılışta veritabanı geçişlerini çalıştırır. |
| `discovery-worker` | Geofabrik içe aktarmaları, CSV/Apify içe aktarmaları, kampanyalar, veri saklama ve zamanlayıcı. |
| `analysis-worker` | Web denetimleri (Chromium, Lighthouse, axe-core), reklam araştırması ve PDF üretimi. |
| PostgreSQL | İş kuyruğu dahil tüm verileri tutan, Dokploy'da ayrı oluşturulan veritabanı servisi. |

Kodda veya ortam değişkenlerinde alan adı tanımlı değildir. Alan adını Dokploy'dan atarsınız ve yeniden derleme gerekmeden istediğiniz zaman değiştirebilirsiniz.

Ayrıntılar (İngilizce): [docs/architecture.md](docs/architecture.md)

## Gereksinimler

**Canlı kullanım (önerilen):**
- En az 4 vCPU, 6 GB RAM ve 40 GB boş diske sahip bir Linux sunucu (Ubuntu 24.04 ile test edildi)
- Sunucuda kurulu [Dokploy](https://dokploy.com)
- Sunucuya yönlendirilmiş bir alan adı veya alt alan adı
- Bu depoya erişimi olan bir GitHub hesabı

**Yerel geliştirme:**
- Python 3.13, Node.js 22 ve PostgreSQL 16

## Kurulum

Proje, veritabanı, uygulama, ortam değişkenleri, alan adı, HTTPS, ilk yönetici, yedekleme ve güncelleme adımlarını içeren tam rehber:

- **Türkçe:** [docs/deployment-dokploy.tr.md](docs/deployment-dokploy.tr.md)
- **English:** [docs/deployment-dokploy.md](docs/deployment-dokploy.md)

## Yerel geliştirme

```bash
# 1. Backend
cd apps/api
python -m venv .venv && . .venv/bin/activate
pip install -e ".[discovery,analysis,dev]"
python -m playwright install chromium
export DATABASE_URL=postgresql://postgres@127.0.0.1:5432/leadradar
export APP_ENV=development
export $(../../scripts/generate-secrets.sh | grep -v '^#' | grep -v POSTGRES | xargs)
python -m leadradar.cli migrate        # tabloları ve varsayılan verileri oluşturur
python -m leadradar.cli create-admin   # yönetici hesabınızı oluşturur
python -m leadradar.cli serve --port 8000

# 2. Worker'lar (ayrı terminallerde, aynı ortam değişkenleriyle)
python -m leadradar.cli worker analysis
python -m leadradar.cli worker discovery   # not: ilk OSM içe aktarmalarını başlatır

# 3. Frontend
cd apps/web
npm ci
API_INTERNAL_URL=http://127.0.0.1:8000 npm run dev
```

Ardından http://localhost:3000 adresini açın.

## Testler

```bash
cd apps/api && TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/leadradar_test python -m pytest
cd apps/web && npm run check:i18n && npm run lint && npm run typecheck && npm run build
BASE_URL=http://127.0.0.1:3000 E2E_EMAIL=siz@ornek.com E2E_PASSWORD=... node tests/e2e/smoke.mjs
```

## Depo yapısı

```text
apps/api/               `leadradar` Python paketi: API, worker'lar, modüller, veritabanı geçişleri, testler
apps/web/               Next.js yönetim arayüzü
infrastructure/docker/  Dockerfile'lar (web; api / discovery / analysis hedefleri)
docs/                   Kurulum, mimari, güvenlik, puanlama, sağlayıcılar, sınırlamalar
scripts/                Gizli anahtar üretici, ülke kataloğu üretici
tests/e2e/              Tarayıcı duman testi
compose.yml             Dokploy uyumlu Compose dosyası (PostgreSQL ayrı bir servistir)
.env.example            Ortam değişkeni şablonu
```

## Dokümantasyon

| Belge | İçerik |
|---|---|
| [Dokploy kurulumu](docs/deployment-dokploy.tr.md) · [English](docs/deployment-dokploy.md) | Adım adım kurulum, alan adı değişikliği, güncelleme, yedekleme, kurtarma |
| [OSM eşleştirme kuralları](docs/osm-rules.tr.md) · [English](docs/osm-rules.md) | Sektör kurallarının yazımı, danışmanlık firmaları örneği ve OSM etiketlerinin nerede bulunacağı |
| [Mimari](docs/architecture.md) (EN) | Servisler, veri akışı, iş kuyruğu, tasarım kararları |
| [Güvenlik](docs/security.md) (EN) | Kimlik doğrulama, CSRF, SSRF koruması, herkese açık rapor güvenliği |
| [Puanlama](docs/scoring.md) (EN) | Potansiyel müşteri, güven ve hizmet puanlarının nasıl hesaplandığı |
| [Reklam sağlayıcıları](docs/advertising-providers.md) (EN) | Her reklam platformunun neye izin verdiği ve nedeni |
| [Veri ve sınırlamalar](docs/data-and-limitations.md) (EN) | OpenStreetMap kapsamı, lisans, gizlilik, depolama |
| [Uygulama durumu](docs/implementation-plan.md) (EN) | Neyin test edildiği, neyin henüz doğrulanması gerektiği |

## Önemli notlar

- LeadRadar asla e-posta veya mesaj göndermez, denetlenen sitelerde form göndermez.
- Herkese açık iletişim bilgileri, pazarlama mesajı gönderme izni anlamına gelmez. "İletişime Geçme" özellikleri gizlilik yönetimini destekler ancak tek başına GDPR veya KVKK uyumluluğunu garanti etmez.
- `robots.txt` ve `noindex`, uygulamayı arama motorlarının dışında tutar ancak bir erişim kontrolü **değildir**; her özel sayfa giriş gerektirir.

## Lisans ve atıflar

- LeadRadar'ın kendisi [MIT Lisansı](LICENSE) ile yayımlanmıştır: telif hakkı bildirimi korunduğu sürece ticari amaçlar dahil kullanabilir, değiştirebilir ve dağıtabilirsiniz. Herhangi bir garanti verilmez.
- Harita verileri © OpenStreetMap katkıda bulunanlar, [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/) kapsamında. Atıf, uygulamada ve OSM verisi içeren raporlarda gösterilir.
- Geist yazı tipleri: SIL Open Font License 1.1.
- Ülke bayrakları: [flag-icons](https://github.com/lipis/flag-icons) (MIT).
- Ülke adları: iso-codes projesi, `pycountry` üzerinden (LGPL-2.1); yalnızca üretici betikte kullanılır.
