# OpenStreetMap eşleştirme kuralları

[English](osm-rules.md) · [Türkçe](osm-rules.tr.md)

Bu rehber, **Veri Kaynakları → Sektörler** bölümünde bir sektör için **OSM eşleştirme kuralı** tanımlamayı ve hedef pazarınıza uygun OpenStreetMap etiketlerini bulmayı açıklar. Danışmanlık firmaları için eksiksiz bir uygulama örneği de içerir.

## 1. Amaç

Keşif sırasında LeadRadar, OpenStreetMap (OSM) verisini okur ve her yerin hangi sektöre ait olduğuna karar verir. Bu karar, her sektörle birlikte saklanan eşleştirme kurallarına göre verilir.

- En az bir **etkin kuralı olan** sektör OpenStreetMap'ten içe aktarılır.
- **Kuralı olmayan** sektör **Manuel** olarak gösterilir. OSM içe aktarmalarında atlanır; bu sektördeki şirketler CSV içe aktarma, Hızlı Denetim, isteğe bağlı Apify entegrasyonu veya elle eklenir.

Kurallar isteğe bağlıdır. Hedeflediğiniz işletmelerin OpenStreetMap'te kayıtlı olma ihtimali yüksekse ekleyin.

## 2. OpenStreetMap bir yeri nasıl tanımlar?

OSM'deki her yer, *etiketlerden* oluşur. Etiket, bir **anahtar** ve bir **değer** çiftidir. Örneğin bir diş kliniği şu etiketleri taşıyabilir:

```text
name    = Smile Dental
amenity = dentist
website = https://smile-dental.example
```

Kural, bu etiketler hakkında bir ifadedir; örneğin "`amenity` anahtarı `dentist` değerine eşittir".

## 3. Kural formundaki alanlar

| Alan | Açıklama |
|---|---|
| **Anahtar** | Kuralın benzersiz kimliği, örneğin `consulting_office`. Yalnızca küçük harf, rakam ve `_` kullanılır. Kural oluşturulduktan sonra değiştirilemez. Bir OSM etiketi *değildir*. |
| **Sınıflandırma** | **Kesin**: eşleşen yerler doğrudan sektöre atanır. **İnceleme adayı**: eşleşen yerler içe aktarılır ancak sektörlerinin onaylanması için işaretlenir. |
| **Açıklama** | Ekibiniz için serbest metin not. |
| **Koşullar** | JSON olarak yazılan eşleştirme mantığı (bkz. bölüm 4). |
| **Etkin** | Devre dışı kurallar dikkate alınmaz. |

> *Anahtar* sözcüğü bu formda iki ayrı anlamda geçer. Kuralın **Anahtar** alanı kuralın kendi kimliğidir. Koşulların içindeki `key` ise denetlenen OSM etiketinin adıdır.

## 4. Koşulları yazma

Koşullar, en fazla üç gruptan oluşan bir JSON nesnesidir. Her grup bir koşul listesidir.

| Grup | Anlamı |
|---|---|
| `all` | Tüm koşullar doğru olmalıdır (mantıksal VE). |
| `any` | En az bir koşul doğru olmalıdır (mantıksal VEYA). |
| `exclude` | Hiçbir koşul doğru olmamalıdır. İstenmeyen sonuçları elemek için kullanılır. |

Her koşul şu parçalardan oluşur:

| Parça | Açıklama |
|---|---|
| `key` | Denetlenecek OSM etiketinin adı, örneğin `office`. |
| `op` | Karşılaştırma türü (aşağıdaki tabloya bakın). |
| `value` | Karşılaştırılacak değer. `exists` için kullanılmaz. |

| `op` | Anlamı | Örnek |
|---|---|---|
| `eq` | Etiket değeri `value` ile birebir aynıdır. | `{"key": "office", "op": "eq", "value": "consulting"}` |
| `in` | Etiket değeri listedeki değerlerden biridir. | `{"key": "office", "op": "in", "value": ["tax_advisor", "accountant"]}` |
| `exists` | Değeri ne olursa olsun etiket mevcuttur. | `{"key": "name", "op": "exists"}` |
| `regex` | Etiket değeri bir desenle eşleşen bir bölüm içerir. Büyük/küçük harf ayrımı yoktur; desen değerin herhangi bir yerinde eşleşebilir. Alternatifleri `\|` ile ayırın. | `{"key": "name", "op": "regex", "value": "danışman\|consult"}` |

Bir yerde etiket hiç yoksa koşul yanlış kabul edilir.

## 5. Öneriler

1. **Yapısal bir etiketle başlayın.** Her kural, `name` dışında en az bir OSM etiketi üzerinde koşul içermelidir (örneğin `office`, `amenity`, `shop`). İçe aktarma önce yerleri etiket anahtarına göre filtrelediği için yalnızca `name` kullanan kurallar desteklenmez.
2. **Yapısal etiketi `all` listesinde `name` koşulundan önce yazın.**
3. **Aynı etiketin birden fazla değeri için `in` kullanın.** Farklı etiket anahtarlarını karıştıran `any` listelerinden kaçının: ön seçim için `any` listesinin yalnızca ilk anahtarı kullanılır.
4. **Ad zorunlu kılın:** `{"key": "name", "op": "exists"}`. Adı olmayan yerler iletişim çalışmasında işe yaramaz.
5. **Zincirleri ve istenmeyen türleri `exclude` ile eleyin.** `{"key": "brand:wikidata", "op": "exists"}` markalı zincirlerin çoğunu dışarıda bırakır.
6. **Ada dayalı kurallarda İnceleme adayı seçin.** Adlar belirsiz olabilir; insan kontrolü verinin güvenilirliğini korur.
7. **İçe aktarmadan önce test edin.** Bkz. bölüm 7.

## 6. Uygulama örneği: danışmanlık firmaları

Amaç: yönetim, eğitim, vize, vergi veya finans gibi her türlü danışmanlık hizmeti veren işletmeleri bulmak. OSM'de bunların tümünü kapsayan tek bir etiket yoktur; bu nedenle birbirini tamamlayan üç kural kullanılır.

**Kural 1 – Etiketlenmiş danışmanlık ofisleri** (Kesin, anahtar `consulting_office`)

```json
{
  "all": [
    {"key": "office", "op": "eq", "value": "consulting"},
    {"key": "name", "op": "exists"}
  ]
}
```

**Kural 2 – Finans, vergi ve hukuk danışmanları** (Kesin, anahtar `finance_tax_advisors`)

```json
{
  "all": [
    {"key": "office", "op": "in", "value": ["financial_advisor", "tax_advisor", "accountant", "lawyer"]},
    {"key": "name", "op": "exists"}
  ]
}
```

**Kural 3 – Adından tanınan danışmanlık işletmeleri** (İnceleme adayı, anahtar `name_consulting`)

```json
{
  "all": [
    {"key": "office", "op": "in", "value": ["company", "travel_agent", "educational_institution", "yes"]},
    {"key": "name", "op": "regex", "value": "danışman|danisman|müşavir|musavir|consult|advis|visa|vize"}
  ],
  "exclude": [
    {"key": "brand:wikidata", "op": "exists"}
  ]
}
```

Eğitim ve vize danışmanlıklarının çoğunlukla özel bir etiketi yoktur. Genellikle genel ofis, seyahat acentesi veya eğitim kurumu olarak haritalanırlar; bu nedenle yalnızca adlarından tanınabilirler. Desendeki sözcükleri hedef ülkelerinizin dillerine göre uyarlayın.

## 7. Kuralı test etme

**Veri Kaynakları** sayfasındaki **Etiketleri test et** panelini kullanın. Örnek bir yerin etiketlerini her satıra bir `anahtar=değer` olacak şekilde girin:

```text
name=Aksoy Danışmanlık
office=company
```

Panel, eşleşen sektörleri ve kuralları listeler. Hiçbir şey kaydedilmez.

## 8. Doğru etiketleri bulma

| Kaynak | Kullanım |
|---|---|
| [openstreetmap.org](https://www.openstreetmap.org) | Bildiğiniz bir işletmeyi haritada bulun ve **Özellikleri sorgula** düğmesine (soru işaretli ok) tıklayın. Yerin gerçek etiketlerini gösterir. |
| [TagInfo](https://taginfo.openstreetmap.org) | Bir anahtarı veya `anahtar=değer` çiftini (örneğin `office=consulting`) aratın; ne sıklıkla kullanıldığını ve hangi etiketlerle birlikte göründüğünü görürsünüz. Düşük sayı, etiketin az kullanıldığını gösterir. |
| [OSM Wiki – Map features](https://wiki.openstreetmap.org/wiki/Map_features) | Etiketlerin konulara göre gruplandığı resmi katalog. |
| [OSM Wiki – Key:office](https://wiki.openstreetmap.org/wiki/Key:office) | Profesyonel hizmetlerin büyük bölümünü kapsayan `office` anahtarının tüm değerleri. |
| [Overpass Turbo](https://overpass-turbo.eu) | Seçtiğiniz bölgede bir etiket için sorgu çalıştırır ve sonuçları haritada gösterir. |
| [Geofabrik indirmeleri](https://download.geofabrik.de) | LeadRadar'ın içe aktardığı veri dosyaları. |

Etiket kullanımı zamanla değişir. Bir kuralı kurmadan önce etiketi TagInfo veya wiki üzerinden doğrulayın.

## 9. Kapsam ve alternatifler

OpenStreetMap gönüllülerce sürdürülür. Profesyonel hizmet ofisleri, mağaza veya restoranlara kıyasla çok daha eksik haritalanır; ayrıca kayıtta web sitesi veya telefon bulunmaması, işletmenin bunlara sahip olmadığı anlamına gelmez. OSM kurallarının pazarın yalnızca bir bölümünü bulacağını varsayın.

Daha geniş bir liste için OSM kurallarını şunlarla birlikte kullanın:

- satın aldığınız veya kendiniz derlediğiniz listenin **CSV içe aktarması**,
- tek tek web siteleri için **Hızlı Denetim**,
- isteğe bağlı **Apify** entegrasyonu (örneğin bir harita veri aracı); kullanım koşullarına ve bütçe sınırlarınıza tabidir.

## 10. Sık yapılan hatalar

| Belirti | Olası neden |
|---|---|
| Kural hiç eşleşmiyor. | Yalnızca `name` kullanılmış veya etiket değeri OSM'de farklı yazılmış. Etiketleri test et paneli ve TagInfo ile kontrol edin. |
| Kural çok fazla sonuç getiriyor. | Desen çok kısa (örneğin `ad`). Daha uzun sözcükler kullanın veya `exclude` grubu ekleyin. |
| Form "geçersiz koşul" hatası veriyor. | JSON hatalı (eksik virgül veya tırnak) ya da `eq`, `in`, `exists`, `regex` dışında bir operatör kullanılmış. |
| Eşleşmesi beklenen yer içe aktarmadan sonra yok. | Yerin `name` etiketi yok, ülke veya bölge henüz içe aktarılmadı ya da veri değişmediği için atlandı (*Değişmemiş olsa da yeniden indir* seçeneğini kullanın). |
