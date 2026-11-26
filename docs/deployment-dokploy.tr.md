<p align="right">
  <strong>Dil:</strong> <a href="deployment-dokploy.md">English</a> · Türkçe
</p>

# LeadRadar'ı Dokploy'a kurma — adım adım

Bu rehber, boş bir sunucudan HTTPS ve yönetici hesabıyla çalışan bir LeadRadar'a kadar sizi götürür. Adımları sırasıyla izleyin. Her adımda **nereye** tıklayacağınız ve **ne** gireceğiniz yazıyor.

> Dokploy'un arayüzü sürümden sürüme değişebilir; bir butonun adı biraz farklı olabilir. Etiket tutmazsa en yakın karşılığını arayın. Kavramlar (proje, veritabanı servisi, compose servisi, ortam değişkenleri, alan adları) aynı kalır.

← [README](../README.tr.md) sayfasına dön

---

## Genel bakış

Şunları oluşturacaksınız:

1. Her şeyi bir arada tutmak için Dokploy'da bir **proje**.
2. LeadRadar'ın tüm verilerini tutan bir **PostgreSQL veritabanı servisi**.
3. Bu GitHub deposundan dört konteyner çalıştıran bir **Compose servisi**: `web`, `api`, `discovery-worker` ve `analysis-worker`.
4. `web` konteynerine atanmış bir **alan adı**.

Tahmini süre: 30–45 dakika; bunun çoğu ilk derlemenin bitmesini beklemekle geçer.

---

## Bölüm A — Hazırlık

### Adım 1. Sunucuyu kontrol edin
- Ubuntu 24.04 (veya Dokploy'un desteklediği başka bir Linux)
- En az **4 vCPU, 6 GB RAM, 40 GB boş disk**. OpenStreetMap içe aktarmaları geçici olarak birkaç GB disk kullanır; boş alan rezervin altına düşecekse LeadRadar indirmeyi başlatmaz (varsayılan rezerv 15 GB).
- İnternete açık **80** ve **443** portları.

### Adım 2. Dokploy'u kurun (zaten kuruluysa atlayın)
Sunucuya SSH ile bağlanın ve resmi kurulum betiğini çalıştırın:
```bash
curl -sSL https://dokploy.com/install.sh | sh
```
Kurulum bitince tarayıcıda `http://<sunucu-ip>:3000` adresini açın ve Dokploy yönetici hesabınızı oluşturun.

> **Güvenlik önerisi:** Dokploy'a HTTPS'li kendi alan adını atadıktan sonra 3000 portunu güvenlik duvarında kapatın.

### Adım 3. Alan adınızı sunucuya yönlendirin
Alan adı sağlayıcınızın DNS panelinde bir **A kaydı** (IPv6 kullanıyorsanız ayrıca **AAAA** kaydı) oluşturun:

| Tür | Ad | Değer |
|---|---|---|
| A | `leads` (`leads.ornek.com` için) veya `@` | sunucunuzun genel IP adresi |

DNS'in yayılması birkaç dakika sürebilir. `ping leads.ornek.com` komutuyla kontrol edebilirsiniz.

### Adım 4. GitHub'ı Dokploy'a bağlayın
1. Dokploy'da **Settings → Git** sayfasını açın (bazı sürümlerde **Git Providers**).
2. **GitHub → Create GitHub App**'e tıklayın ve adımları izleyin. GitHub, uygulamayı onaylamanızı ve kurmanızı ister.
3. Kurulum sırasında uygulamaya **LeadRadar deposuna** (veya tüm depolara) erişim verin.
4. Dokploy'a döndüğünüzde GitHub sağlayıcısı bağlı olarak görünmelidir.

### Adım 5. Gizli anahtarları üretin
Kendi bilgisayarınızda (veya sunucuda), deponun bir kopyasında şunu çalıştırın:
```bash
./scripts/generate-secrets.sh
```
Üç değer yazdırır:
```
SESSION_SECRET=...
APP_ENCRYPTION_KEY=...
POSTGRES_PASSWORD=...
```
**Bunları bir parola yöneticisine kaydedin.** Sonraki adımlarda bunlara ihtiyacınız olacak; bir yedeği geri yüklerken de `APP_ENCRYPTION_KEY` tekrar gerekir.

Depo bilgisayarınızda yoksa Python 3 olan herhangi bir yerde şunu çalıştırabilirsiniz:
```bash
python3 -c "import secrets,base64;print('SESSION_SECRET='+secrets.token_urlsafe(48));print('APP_ENCRYPTION_KEY='+base64.urlsafe_b64encode(secrets.token_bytes(32)).decode());print('POSTGRES_PASSWORD='+secrets.token_urlsafe(24))"
```

---

## Bölüm B — Projeyi ve veritabanını oluşturun

### Adım 6. Proje oluşturun
1. Dokploy'da **Projects** sayfasını açın.
2. **Create Project**'e tıklayın.
3. Adını `LeadRadar` yapın ve **Create**'e tıklayın.

### Adım 7. PostgreSQL veritabanını oluşturun
1. `LeadRadar` projesini açın.
2. **Create Service → Database**'e tıklayın.
3. **PostgreSQL**'i seçin.
4. Formu doldurun:

   | Alan | Değer |
   |---|---|
   | Name | `leadradar-db` |
   | Database Name | `leadradar` |
   | Database User | `leadradar` |
   | Database Password | 5. adımdaki `POSTGRES_PASSWORD` |
   | Docker Image | `postgres:16` (veya daha yenisi) |

5. **Create**'e tıklayın.
6. Veritabanı sayfasında **Deploy**'a tıklayın ve durum **running** olana kadar bekleyin.
7. Harici port (**External Port**) **ayarlamayın**; veritabanı yalnızca iç ağda kalmalıdır.

### Adım 8. İç bağlantı adresini kopyalayın
1. Veritabanı sayfasında **Internal Credentials** (veya **Internal Connection URL**) bölümünü bulun.
2. **İç host** adını (`leadradar-db-abc123` gibi görünür) veya iç bağlantı adresinin tamamını kopyalayın.
3. `DATABASE_URL` değerinizi şu biçimde oluşturun:
   ```
   postgresql://leadradar:<POSTGRES_PASSWORD>@<iç-host>:5432/leadradar
   ```
   Örnek: `postgresql://leadradar:Xy7...@leadradar-db-abc123:5432/leadradar`

> Parola `@`, `:` veya `/` gibi karakterler içeriyorsa bunları URL kodlamasıyla yazın ya da bu karakterleri içermeyen bir parola üretin. 5. adımda üretilen parolalar URL için güvenlidir.

### Adım 9. Veritabanı yedeklemeyi açın (önerilir)
1. Veritabanı sayfasında **Backups** sekmesini açın.
2. S3 uyumlu bir hedef ekleyin; henüz yoksa önce Dokploy **Settings → S3 Destinations**'tan oluşturun.
3. Günlük bir yedek zamanlayın, örneğin `0 3 * * *`.

Veritabanı **her şeyi** tutar: şirketler, CRM, kanıt ekran görüntüleri, raporlar ve ayarlar.

---

## Bölüm C — Uygulamayı oluşturun ve yapılandırın

### Adım 10. Compose servisini oluşturun
1. `LeadRadar` projesinde **Create Service → Compose**'a tıklayın.
2. Adını `leadradar-app` yapın.
3. Compose türü: **Docker Compose**.
4. **Create**'e tıklayın.

### Adım 11. Depoyu bağlayın
1. `leadradar-app`'i açın, **General** sekmesine gelin.
2. Provider: **GitHub**.
3. **Depoyu** (LeadRadar) ve kurmak istediğiniz **dalı** seçin, örneğin `main`.
4. **Compose Path:** `./compose.yml`
5. **Save**'e tıklayın.

### Adım 12. Ortam değişkenlerini ekleyin
1. **Environment** sekmesini açın.
2. Aşağıdakini yapıştırın ve değerleri kendinizinkilerle değiştirin:
   ```
   DATABASE_URL=postgresql://leadradar:<POSTGRES_PASSWORD>@<iç-host>:5432/leadradar
   SESSION_SECRET=<5. adımdan>
   APP_ENCRYPTION_KEY=<5. adımdan>
   APP_ENV=production
   LOG_LEVEL=INFO
   EGRESS_DENY_CIDRS=<sunucunuzun genel IP adresi>/32
   ```
3. **Save**'e tıklayın.

Değişkenlerin anlamı:

| Değişken | Zorunlu | Amacı |
|---|---|---|
| `DATABASE_URL` | evet | 8. adımdaki veritabanı bağlantısı |
| `SESSION_SECRET` | evet | Oturumları ve herkese açık rapor jetonlarını imzalar. Değiştirilirse herkesin oturumu kapanır ve paylaşılmış rapor bağlantıları çalışmaz. |
| `APP_ENCRYPTION_KEY` | evet | Kayıtlı sağlayıcı jetonlarını ve 2FA gizli anahtarlarını şifreler. **Asla kaybetmeyin.** |
| `EGRESS_DENY_CIDRS` | şiddetle önerilir | Denetim tarayıcısının genel IP üzerinden kendi sunucunuza ulaşmasını engeller; Dokploy panelini korur. |
| `APP_ENV` | hayır | `production` olarak bırakın. |
| `TRUSTED_PROXIES` | hayır | Yalnızca Docker ağlarınız alışılmadık adres aralıkları kullanıyorsa değiştirin. |

**Alan adı değişkeni yoktur.** Alan adı 14. adımda ayarlanır.

### Adım 13. İlk dağıtım
1. `leadradar-app` sayfasının üstündeki **Deploy**'a tıklayın.
2. **Deployments** sekmesini açın ve günlükleri izlemek için çalışan dağıtıma tıklayın.
3. İlk derleme **10–20 dakika** sürer; Chromium, Lighthouse ve Python ile Node bağımlılıkları indirilir. Sonraki derlemeler önbellek sayesinde daha hızlıdır.
4. Derleme bitince **Logs** (veya **Monitoring**) sekmesini açın ve her servisi tek tek seçin:
   - `api`: `migrations and seeds applied` ve ardından istek günlükleri görünmeli.
   - `discovery-worker`: `starting worker` ve `scheduler lock acquired` görünmeli.
   - `analysis-worker`: `starting worker` görünmeli.

Derleme başarısız olursa [Sorun giderme](#sorun-giderme) bölümüne bakın.

---

## Bölüm D — Alan adı ve HTTPS

### Adım 14. Alan adını `web` servisine atayın
1. `leadradar-app`'te **Domains** sekmesini açın.
2. **Add Domain**'e tıklayın.
3. Formu doldurun:

   | Alan | Değer |
   |---|---|
   | Service Name | **`web`** (önemli: `api` değil) |
   | Host | `leads.ornek.com` |
   | Path | `/` |
   | Container Port | **`3000`** |
   | HTTPS | **açık** |
   | Certificate | **Let's Encrypt** |

4. **Create**'e (veya **Save**'e) tıklayın.
5. Dokploy isterse yeniden dağıtın (**Deploy**).

`api`, `discovery-worker` veya `analysis-worker` için alan adı **eklemeyin**. `web` konteyneri `/api` ve `/r` isteklerini API'ye iç ağdan iletir.

### Adım 15. Çalıştığını kontrol edin
1. `https://leads.ornek.com` adresini açın. Sertifikanın verilmesi bir dakika kadar sürebilir.
2. **LeadRadar giriş sayfasını** ve henüz yönetici olmadığını söyleyen bir mesaj görmelisiniz.
3. `https://leads.ornek.com/robots.txt` adresini açın; `Disallow: /` görünmelidir.

---

## Bölüm E — İlk kullanım

### Adım 16. İlk yöneticiyi oluşturun
Herkese açık kayıt yoktur; yönetici sunucuda oluşturulur.

**Seçenek 1 — Dokploy terminali.** `leadradar-app`'te konteyner terminalini açın (Dokploy sürümünüzde varsa **Logs/Monitoring** içinde `api` konteynerini seçip **Terminal**'e tıklayın) ve şunu çalıştırın:
```bash
python -m leadradar.cli create-admin
```

**Seçenek 2 — SSH.** Sunucuya bağlanın ve şunları çalıştırın:
```bash
docker ps --format '{{.Names}}' | grep api          # api konteynerinin adını bulun
docker exec -it <api-konteyner-adı> python -m leadradar.cli create-admin
```

E-posta adresinizi ve en az 12 karakterlik bir parolayı girin, ardından parolayı tekrarlayın. `administrator ... created` mesajını göreceksiniz.

Daha sonra başka yönetici eklemek için aynı komutu `--additional` ile çalıştırın.

### Adım 17. Giriş yapın ve hesabınızı güvenceye alın
1. `https://leads.ornek.com` adresinden giriş yapın.
2. **Ayarlar → Hesap ve güvenlik** sayfasını açın.
3. **2FA'yı etkinleştir**'e tıklayın, QR kodunu bir doğrulama uygulamasıyla (Google Authenticator, 1Password, Aegis vb.) tarayın ve kodu girin.
4. **10 kurtarma kodunu** güvenli bir yere kaydedin. Yalnızca bir kez gösterilirler.

### Adım 18. Ayarları gözden geçirin
**Ayarlar → Genel:**
- **İzin verilen host'lar** (önerilir): `leads.ornek.com` yazın. Bundan sonra başka host adlarıyla gelen istekler reddedilir.
- **Herkese açık rapor kökeni** (isteğe bağlı): yalnızca herkese açık raporlar farklı bir alan adı kullanacaksa.
- **Rapor markası**: ajansınızın adı ve iletişim satırı.
- **Öncelikli ülkeler**, **Hariç tutulan alan adları**: hedef pazarınıza göre ayarlayın.

**Ayarlar → Kaynaklar:** varsayılanlar temkinlidir ve 4 vCPU / 6 GB sunucuya uygundur. Başlangıçta olduğu gibi bırakın.

### Adım 19. İlk içe aktarmaları kontrol edin
İlk dağıtım, başlangıç ülkelerinin her biri için **bir kez** içe aktarmayı otomatik olarak sıraya aldı: Türkiye, Hollanda, Almanya, Birleşik Krallık ve ABD.
1. **Arka Plan İşleri** sayfasını açın. Alt `Özet içe aktarma` işleri oluşturan `Ülke içe aktarma` işlerini göreceksiniz.
2. İçe aktarmalar **teker teker** çalışır. Büyük ülkeler bölgelere ayrılır (örneğin ABD eyaletleri, Almanya'nın eyaletleri), bu yüzden tam bir içe aktarma **birkaç saat** sürer.
3. **Keşif** sayfasında şunları yapabilirsiniz:
   - içe aktarmaları duraklatmak, iptal etmek veya yeniden denemek,
   - ülkeleri etkinleştirmek veya devre dışı bırakmak (devre dışı bırakmak gelecekteki içe aktarmaları durdurur, mevcut şirketler korunur),
   - başka ülke ve sektörler için içe aktarma başlatmak.
4. Ham `.osm.pbf` dosyaları her özet işlendikten sonra otomatik olarak silinir.

### Adım 20. İlk denetiminiz
1. Üst çubuktaki **Hızlı Denetim**'e tıklayın.
2. Bir web sitesi adresi girin ve **Tam denetim**'i seçin.
3. İş **Arka Plan İşleri**'nde görünür. Bittiğinde şirket **İşlem gerekli** durumuna geçer.
4. **İnceleme Kuyruğu**'nu açın; inceleme sorularını yanıtlayın, sezgisel bulguları doğrulayın ve ekran görüntülerini raporlar için onaylayın.
5. **İncelemeyi tamamla**'ya tıklayın. Nihai puan ve öneriler hesaplanır.
6. Şirket sayfasında **Raporlar** sekmesini açın, bir rapor oluşturun, bir sürümü onaylayın ve herkese açık bağlantı oluşturun.

Kurulum tamamlandı.

---

## Bakım

### LeadRadar'ı güncelleme
1. Önce veritabanını yedekleyin (9. adım veya **Backups → Run now**).
2. Yeni kodu dağıtılan dala gönderin ya da `leadradar-app`'te **Deploy**'a tıklayın.
3. `api` konteyneri açılırken veritabanı geçişleri otomatik çalışır. Geçişler veritabanında kilit aldığı için birden fazla konteynerin aynı anda açılması güvenlidir.
4. `api` günlüklerinde `migrations and seeds applied` mesajını kontrol edin.

**General** sekmesinden (Autodeploy) push sonrası otomatik dağıtımı açabilirsiniz. Bunu yalnızca push etmeden önce her zaman yedek alıyorsanız yapın.

### Alan adını değiştirme
1. Yeni alan adının DNS kaydını sunucuya yönlendirin (3. adım).
2. `leadradar-app` → **Domains**'te yeni alan adını `web` servisi, `3000` portu ve HTTPS ile ekleyin.
3. LeadRadar'da **Ayarlar → Genel** sayfasında **İzin verilen host'lar**'ı ve ayarlıysa **Herkese açık rapor kökeni**'ni güncelleyin.
4. Yeniden derleme veya ortam değişkeni değişikliği gerekmez.
5. **Daha önce paylaşılmış rapor bağlantıları eski alan adını gösterir.** Bu bağlantılar çalışmaya devam etsin istiyorsanız eski alan adını yönlendirmede tutun veya yeni alan adına yönlendirin.

### Manuel yedekleme ve geri yükleme
Yedekleme (sunucuda):
```bash
docker ps --format '{{.Names}}' | grep leadradar-db        # veritabanı konteynerini bulun
docker exec <db-konteyneri> pg_dump -U leadradar -Fc leadradar > leadradar-$(date +%F).dump
```
Boş veya mevcut bir veritabanına geri yükleme:
```bash
docker exec -i <db-konteyneri> pg_restore -U leadradar -d leadradar --clean --if-exists < leadradar-YYYY-AA-GG.dump
```
`APP_ENCRYPTION_KEY` ve `SESSION_SECRET` değerlerini yedeklerinizle birlikte saklayın; geri yüklenen veriler aynı anahtarı gerektirir.

### Başarısız bir dağıtımdan kurtarma

| Durum | Yapılacak |
|---|---|
| Derleme başarısız oldu | Önceki konteynerler çalışmaya devam eder. Dağıtım günlüğünü okuyun, sorunu düzeltin ve yeniden dağıtın. |
| Güncellemeden sonra `api` sürekli yeniden başlıyor | Günlüklerine bakın. Bir veritabanı geçişi başarısız olduysa önceki commit'i veya dalı dağıtın; veritabanı değiştiyse yedeği geri yükleyin. |
| Bir worker iş sırasında çöktü | Bir şey yapmanız gerekmez. İş kiralaması sona erer ve iş yaklaşık 3 dakika içinde otomatik olarak yeniden sıraya alınır. |
| Disk doldu | Eski Docker imajlarını silin (`docker image prune`), **Ayarlar → Veri saklama**'dan ekran görüntüsü saklama süresini kısaltın ve temizliği çalıştırın. |

---

## Sorun giderme

| Sorun | Muhtemel neden ve çözüm |
|---|---|
| Sayfa "Bad Gateway" veya 502 gösteriyor | Alan adı yanlış servise veya porta atanmış. Servis `web`, port `3000` olmalıdır. |
| "invalid_host" hatası | **İzin verilen host'lar** listesinde kullandığınız alan adı yok. Listeyi sunucudan temizleyin: `docker exec -it <api> python -m leadradar.cli set-setting security.allowed_hosts '[]'` |
| `api` günlüklerinde "DATABASE_URL ..." veya bağlantı reddedildi hatası | `DATABASE_URL` içindeki iç host veya parola yanlış ya da veritabanı servisi çalışmıyor. |
| `APP_ENCRYPTION_KEY must decode to 32 bytes` | Anahtar eksik kopyalanmış. 5. adımdaki biçimde yeni bir anahtar üretin. |
| Giriş yapılıyor ama hemen oturum kapanıyor | `http://` kullanıyorsunuz; `APP_ENV=production` güvenli çerezler kullanır. `https://` ile girin. |
| 2FA cihazı kayboldu | `docker exec -it <api> python -m leadradar.cli reset-mfa siz@ornek.com` komutunu çalıştırın; ardından bir kurtarma kodu kullanın veya 2FA'yı yeniden kurun. |
| İçe aktarmalar başlamıyor | `discovery-worker`'ın çalıştığını ve ülkenin **Keşif** sayfasında etkin olduğunu kontrol edin. Boş disk alanını kontrol edin; varsayılan rezerv 15 GB'tır. |
| Denetimler "Sırada" kalıyor | `analysis-worker`'ın çalıştığını kontrol edin. **Ayarlar → Sistem durumu** sayfası worker sinyallerini gösterir. |

Daha fazla bilgi (İngilizce): [Mimari](architecture.md) · [Güvenlik](security.md) · [Veri ve sınırlamalar](data-and-limitations.md)

← [README](../README.tr.md) sayfasına dön · [English version of this guide](deployment-dokploy.md)
