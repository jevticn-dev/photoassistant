# RENDERER_SPEC — specifikacija renderera v1

**Status:** predlog, čeka potvrdu vlasnika projekta · **Faza:** 1, zadatak 1
**Šema izmene:** v1 (`docs/edit_schema_v1.md`) · **Redosled operacija:** plan §4.1 (zaključan)

> Ovaj dokument je **izvor istine za obe implementacije** renderera — NumPy
> (`ml/photoassistant/renderer/`) i WebGL2 (`frontend/src/app/renderer/`). Nijedna od njih
> nije referenca za drugu; obe prevode ovaj tekst. Golden test dokazuje da se slažu, ne da
> su tačne — tačnost je obaveza ovog dokumenta i ljudskog pregleda pre koda.
>
> Izmene isključivo kroz ADR (`DECISIONS.md`), aditivno. Vidi `CLAUDE.md`, tvrda pravila.

---

## 1. Definicija

Renderer je **deterministička funkcija**:

```
render(slika, recept) → slika
```

| | Tip | Prostor | Opseg |
|---|---|---|---|
| **ulaz** | `float32[H, W, 3]` | sRGB (gama) | [0, 1] |
| **recept** | šema izmene v1 | — | vidi `docs/edit_schema_v1.md` §3 |
| **izlaz** | `float32[H, W, 3]` | sRGB (gama) | [0, 1] |

Determinizam znači: isti ulaz i isti recept daju isti izlaz, uvek i svuda, u granicama
numeričkog ugovora (§8). Bez oslanjanja na vreme, slučajne brojeve, redosled niti ili
osobine uređaja.

Renderer **ne zna** za FiveK, Lightroom, korisnike ni bazu. Zna samo za šemu v1.

---

## 2. Kolor prostori

### 2.1 sRGB prenosna funkcija

Definisana **deo po deo**. Aproksimacija stepenom 2,2 je zabranjena — odstupanje je
sistematsko i najveće u tamnim tonovima (obrazloženje: `docs/notes/phase-1-concepts.md` §B1).

**Dekodiranje** (sRGB → linearno), `S ≥ 0`:

```
L = S / 12.92                          ako je S ≤ 0.04045
L = ((S + 0.055) / 1.055) ^ 2.4        inače
```

**Kodovanje** (linearno → sRGB), `L ≥ 0`:

```
S = 12.92 · L                          ako je L ≤ 0.0031308
S = 1.055 · L^(1/2.4) − 0.055          inače
```

Obe funkcije se primenjuju **po kanalu, nezavisno**.

**Ponašanje van [0,1]:** kodovanje se primenjuje i na `L > 1` — formula se produžava
analitički i **ne iseca se** na ovom mestu (§4, korak 4). Vrednosti `L < 0` ne mogu nastati:
jedine operacije u linearnom prostoru su množenja pozitivnim brojevima (§3.1, §3.2).

### 2.2 Luma

Gde je potrebna skalarna „svetlina" piksela (maske §7, saturacija §3.6), koristi se
**Rec.709 luma nad gama-kodovanim vrednostima**:

```
Y' = 0.2126·R' + 0.7152·G' + 0.0722·B'
```

Oznaka `Y'` (sa crticom) je namerna: ovo je **luma**, ne luminancija. Luminancija bi tražila
iste koeficijente nad *linearnim* vrednostima. Koristi se luma jer su operacije koje je
troše perceptualne i izvršavaju se u gama prostoru.

### 2.3 Koje operacije idu u koji prostor

| Prostor | Operacije | Razlog |
|---|---|---|
| **linearni** | balans bele, ekspozicija | fizičke: „+1 stop" *jeste* množenje sa 2 |
| **gama** | tonski regioni, kontrast, kriva, saturacija/vibrance | perceptualne: rade nad onim što izgleda svetlo/tamno |

---

## 3. Formule po parametru

Konvencija: `v` je normalizovana vrednost parametra, `v = <parametar> / 100`, pa `v ∈ [−1, 1]`
za sve osim ekspozicije. Neutralna vrednost je uvek `0`.

Svaki parametar počinje sa **Namera** — jednom rečenicom koja kaže *šta operacija treba da
uradi*, pre nego što formula kaže *kako*. Namera je ono što se pregleda i potvrđuje ljudski;
formula je njen prevod. Ako se formula i namera ikad raziđu, **namera je merodavna** i formula
se ispravlja.

### 3.1 `temperature`, `tint` — balans bele

**Prostor:** linearni · **Korak:** 2 · **Opseg:** −100..+100

> **Namera:** pomeriti odnos boja ka toplom ili hladnom (`temperature`) i ka zelenom ili
> magenti (`tint`), **bez promene ukupne svetline** — za svetlinu postoji ekspozicija.
> Neutralna siva mora ostati jednako svetla posle operacije.

Balans bele je **čisto hromatska** operacija: menja odnos kanala, ne ukupnu svetlinu. Za
svetlinu postoji ekspozicija.

```
t = temperature / 100
u = tint / 100

m_R = 2 ^ ( +K_WB · t )
m_G = 2 ^ ( −K_WB · u )
m_B = 2 ^ ( −K_WB · t )

Y_m = 0.2126·m_R + 0.7152·m_G + 0.0722·m_B      (luminancija množilaca)

R ← R · (m_R / Y_m)
G ← G · (m_G / Y_m)
B ← B · (m_B / Y_m)
```

**Konstanta:** `K_WB = 0.5`. Na `temperature = +100` daje `m_R/m_B = 2` — dvostruko više
crvenog nego plavog pre normalizacije.

**Smer:** `temperature > 0` = toplije (više crvenog, manje plavog). `tint > 0` = ka magenti
(manje zelenog; normalizacija time relativno podiže crveno i plavo).

**Normalizacija sa `Y_m`** je ono što čini operaciju hromatskom: množioci se dele svojom
luminancijom, pa neutralna siva zadržava svetlinu.

**Ovo nije Kelvin.** Naša skala je sopstvena i normalizovana; prevod iz Kelvina u ovu skalu
radi ingestion (plan §3, `docs/edit_schema_v1.md` §3, napomena uz tabelu).

### 3.2 `exposure` — ekspozicija

**Prostor:** linearni · **Korak:** 3 · **Opseg:** −5..+5 (stopovi, **ne** deli se sa 100)

> **Namera:** promeniti ukupnu količinu svetla tako da `+1` znači **dvostruko svetla**, isto
> kao jedan stop na fotoaparatu. Odnosi boja ostaju nepromenjeni.

```
R ← R · 2^exposure
G ← G · 2^exposure
B ← B · 2^exposure
```

Jedan stop = dvostruko svetla. Vrednosti smeju preći 1,0 — isecanja ovde nema (§8).

### 3.3 `highlights`, `shadows`, `whites`, `blacks` — tonski regioni

**Prostor:** gama · **Korak:** 5 · **Opseg:** −100..+100

> **Namera:** posvetliti ili potamniti **samo deo tonskog opsega** — `blacks` i `shadows`
> tamni kraj, `highlights` i `whites` svetli — tako da srednji tonovi ostanu uglavnom
> netaknuti i da se na granici regiona **ne pojavi vidljiv prelaz** u glatkom gradijentu.
> Nijansa se ne menja, samo svetlina.

Sva četiri parametra dele jedan mehanizam: pomeraj svetline otežan maskom po lumi. Maske su
definisane u §7.

**Sva četiri se računaju iz iste, unapred izračunate lume i primenjuju se jednim sabiranjem.**
Time je operacija nezavisna od redosleda četiri parametra — nema pitanja „šta se primenjuje
prvo", pa nema ni mesta gde dve implementacije mogu da se raziđu.

```
Y' = 0.2126·R' + 0.7152·G' + 0.0722·B'          (jednom, pre bilo kakve izmene)

Δ = K_REG · (   (highlights/100) · w_hi(Y')
              + (shadows/100)    · w_sh(Y')
              + (whites/100)     · w_wh(Y')
              + (blacks/100)     · w_bl(Y')  )

R' ← R' + Δ
G' ← G' + Δ
B' ← B' + Δ
```

**Konstanta:** `K_REG = 0.25`. Na `blacks = +100` i `Y' = 0` daje pomeraj `+0.25` — crna
tačka podignuta na četvrtinu opsega.

Pomeraj je **isti za sva tri kanala**, pa operacija menja svetlinu a ne nijansu.

### 3.4 `contrast` — kontrast

**Prostor:** gama · **Korak:** 6 · **Opseg:** −100..+100

> **Namera:** razmaknuti svetlo od tamnog oko srednje sive — svetlo svetlije, tamno tamnije,
> **sredina nepomerena** — ili suprotno pri negativnoj vrednosti. Ni pri jednoj vrednosti se
> ne sme izaći iz opsega niti obrnuti redosled tonova.

S-kriva oko srednje sive, izražena kao mešanje identiteta i `smoothstep` oblika:

```
s = contrast / 100
S(x) = x² · (3 − 2x)

x ← x + s · ( S(x) − x )          po kanalu, nezavisno
```

Osobine, sve proverljive:

- `s = 0` → `x ← x`, **tačan identitet** (ne približan)
- `s > 0` → ka `S(x)`: tamno tamnije, svetlo svetlije, `0.5` nepomereno
- `s < 0` → od `S(x)`: smanjuje kontrast
- monotono za svako `s ∈ [−1, 1]`; na `s = −1` izvod je `2 − 6x + 6x²`, čiji je minimum
  `0.5 > 0`
- ostaje u [0,1] za ulaz iz [0,1]
- primenjeno po kanalu → neutralna siva ostaje neutralna
- **bez trigonometrije** — polinom trećeg stepena

### 3.5 `tone_curve` — master tonska kriva

**Prostor:** gama · **Korak:** 7 · **Format:** tačke u [0,1]²

> **Namera:** dozvoliti **proizvoljno** preslikavanje ulazne svetline u izlaznu — ono što
> nijedna kombinacija slajdera ne može izraziti — kao poslednja globalna reč o svetlini.
> Primenjuje se **isto na sva tri kanala**, pa siva ostaje siva i balans boja se ne pomera.

Kriva se ne računa po pikselu. Iz kontrolnih tačaka se gradi LUT od 1024 vrednosti (§6), pa
se po pikselu radi samo pretraga i linearna interpolacija.

**Ista LUT se primenjuje na sva tri kanala.** Posledica: `R = G = B` ostaje jednako — kriva
menja svetlinu i kontrast, ne balans boja. Kriva po kanalu je kandidat za šemu 2.

### 3.6 `saturation`, `vibrance` — zasićenost

**Prostor:** gama · **Korak:** 9 · **Opseg:** −100..+100

> **Namera:** pojačati ili oslabiti intenzitet boja — `saturation` jednako na sve, `vibrance`
> **jače na blede a slabije na već zasićene**, da živi tonovi (koža, nebo) ne odu u
> neprirodno. Neutralno siv piksel se ne dira ni u jednom slučaju.

Oba parametra skaliraju odstojanje piksela od njegove sive vrednosti. Razlika je što je
vibrance **otežan trenutnom zasićenošću** — manje deluje na već zasićene piksele.

Kao i kod tonskih regiona, oba se računaju iz **istog, pre-izmenskog** stanja piksela i
primenjuju jednim skaliranjem, pa redosled među njima ne postoji.

```
Y'   = 0.2126·R' + 0.7152·G' + 0.0722·B'
mx   = max(R', G', B')
mn   = min(R', G', B')
p    = (mx − mn) / max(mx, ε)                   zasićenost piksela, ∈ [0, 1]

g = (saturation / 100) + (vibrance / 100) · (1 − p)

R' ← Y' + (R' − Y') · (1 + g)
G' ← Y' + (G' − Y') · (1 + g)
B' ← Y' + (B' − Y') · (1 + g)
```

**Konstanta:** `ε = 1e-6` (§8).

Osobine:

- oba na 0 → `g = 0` → `x ← Y' + (x − Y')·1 = x`, **tačan identitet**
- `saturation = −100` → `g = −1` → sve postaje `Y'`, potpuno sivo
- potpuno zasićen piksel (`p = 1`) → vibrance ne deluje, samo saturation
- neutralno siv piksel (`R'=G'=B'`) → `x − Y' = 0`, ništa se ne dešava ni pri kom `g`

---

## 4. Redosled operacija

Fiksiran planom §4.1. **Menja se isključivo kroz ADR** (`CLAUDE.md`, tvrda pravila).

| # | Operacija | Prostor | Parametri |
|---|---|---|---|
| 1 | dekodiranje sRGB → linearno | → linearni | — |
| 2 | balans bele | linearni | `temperature`, `tint` |
| 3 | ekspozicija | linearni | `exposure` |
| 4 | kodovanje linearno → sRGB | → gama | — |
| 5 | tonski regioni | gama | `highlights`, `shadows`, `whites`, `blacks` |
| 6 | kontrast | gama | `contrast` |
| 7 | master tonska kriva (LUT) | gama | `tone_curve` |
| 8 | *[slot: HSL — šema 2]* | gama | — |
| 9 | saturacija / vibrance | gama | `saturation`, `vibrance` |
| 10 | *[slot: split toning — šema 2]* | gama | — |
| 11 | isecanje u [0,1] | gama | — |

Slotovi 8 i 10 su u šemi 1 **prazni i preskaču se bezuslovno**. Postoje da bi njihovo
kasnije popunjavanje bilo aditivna izmena, ne promena redosleda.

### 4.1 Pravilo preskakanja

Operacija sa neutralnim parametrima **se ne izvršava**. Ovo nije optimizacija nego uslov
tačnosti: bez njega bi neutralan recept prošao kroz aritmetiku i vratio vrednosti različite
od ulaza u poslednjim bitovima.

| Operacija | Preskače se ako |
|---|---|
| 2 — balans bele | `temperature == 0 && tint == 0` |
| 3 — ekspozicija | `exposure == 0` |
| 5 — tonski regioni | sva četiri parametra `== 0` |
| 6 — kontrast | `contrast == 0` |
| 7 — kriva | `points == [[0,0], [1,1]]` |
| 9 — saturacija/vibrance | `saturation == 0 && vibrance == 0` |

**Koraci 1 i 4 se preskaču zajedno**, ako i samo ako su preskočena **oba** koraka 2 i 3.

Ovo je najlakše prevideti, a nosi ceo test identiteta: dekodiranje pa kodovanje nije tačna
inverzija u konačnoj preciznosti. Ako se izvrši bez potrebe, `neutral.json` više ne vraća
bit-identičan ulaz.

**Posledica:** nad `neutral.json` se ne izvršava **nijedna** aritmetička operacija. Izlaz je
ulaz, doslovno. Isecanje (korak 11) nad ulazom koji je već u [0,1] ništa ne menja.

---

## 5. Isecanje

Isecanje u [0,1] postoji **tačno jednom**, u koraku 11:

```
x ← min(max(x, 0), 1)
```

Međurezultati smeju izaći iz opsega i **ne smeju se isecati usput**. Konkretno: ekspozicija
`+2` nad vrednošću `0.5` daje `2.0` u linearnom prostoru; da se to isecalo na koraku 4,
izgubila bi se zaliha u svetlima koju korak 5 (`highlights` u negativnom smeru) treba da
vrati.

---

## 6. LUT — tonska kriva

### 6.1 Ulaz i validacija

Kontrolne tačke iz `tone_curve.points`. Zahtevi:

1. najmanje dve tačke
2. sortirane strogo rastuće po `x`
3. prva tačka ima `x = 0`, poslednja `x = 1` — kriva mora biti definisana na celom opsegu
4. sve vrednosti u [0,1]

Recept koji ih ne ispunjava se **odbija pri parsiranju**, ne popravlja.

### 6.2 Interpolacija — monotona kubna (Fritsch–Carlson)

Za `n` tačaka `(x_i, y_i)`:

**Korak 1 — sekantni nagibi**, za `i = 0 … n−2`:

```
Δ_i = (y_{i+1} − y_i) / (x_{i+1} − x_i)
```

**Korak 2 — početni tangenti**, za `i = 0 … n−1`:

```
m_0     = Δ_0
m_i     = (Δ_{i−1} + Δ_i) / 2          za 0 < i < n−1
m_{n−1} = Δ_{n−2}
```

**Korak 3 — ispravka monotonosti**, za svaki segment `i = 0 … n−2`:

```
ako je Δ_i == 0:
    m_i = 0;  m_{i+1} = 0
inače:
    α = m_i / Δ_i
    β = m_{i+1} / Δ_i
    ako je α² + β² > 9:
        τ = 3 / sqrt(α² + β²)
        m_i     = τ · α · Δ_i
        m_{i+1} = τ · β · Δ_i
```

Segmenti se obrađuju **rastućim redom po `i`**, i ispravka jednog segmenta ostaje vidljiva
narednom. Redosled je deo specifikacije, ne detalj implementacije.

**Korak 4 — Hermite evaluacija** na segmentu `[x_i, x_{i+1}]`, sa `h = x_{i+1} − x_i` i
`t = (x − x_i) / h`:

```
h00 = 2t³ − 3t² + 1
h10 = t³ − 2t² + t
h01 = −2t³ + 3t²
h11 = t³ − t²

y = h00·y_i + h10·h·m_i + h01·y_{i+1} + h11·h·m_{i+1}
```

### 6.3 Gradnja tabele

```
N = 1024

za i = 0 … N−1:
    x      = i / (N − 1)
    lut[i] = clamp( evaluate(x), 0, 1 )
```

Odatle `lut[0] = y_0` i `lut[N−1] = y_{n−1}`, tj. krajevi krive su tačno pogođeni.

### 6.4 Primena po pikselu

```
t = clamp(x, 0, 1) · (N − 1)
i = clamp( floor(t), 0, N − 2 )
f = t − i

y = lut[i] · (1 − f) + lut[i+1] · f
```

Ulaz se **iseca pre pretrage**, jer posle koraka 5 i 6 sme biti van [0,1]. To je jedino
mesto pre koraka 11 gde se iseca, i tiče se isključivo indeksa tabele.

### 6.5 Obaveza WebGL2 implementacije

LUT se **ne sme** čitati kroz `GL_LINEAR` filtriranje teksture. OpenGL ES specifikacija
dopušta računanje težine interpolacije u ograničenoj preciznosti; rezultat se razlikuje
između uređaja i ne može se reprodukovati u NumPy-ju.

Obavezno: `NEAREST` filtriranje, dva `texelFetch` poziva, interpolacija ručno po formuli
§6.4.

### 6.6 Zašto LUT uopšte postoji

Težak deo (§6.2) izvršava se **1024 puta ukupno**, a ne po pikselu. Time se najosetljiviji
deo saglasnosti svodi na dva niza od 1024 broja, koja se mogu porediti direktno, bez slike.
Obrazloženje u `docs/notes/phase-1-concepts.md` §A2 i §B2.

---

## 7. Maske tonskih regiona

### 7.1 Osnovna funkcija

```
smoothstep(e0, e1, x):
    t = clamp( (x − e0) / (e1 − e0), 0, 1 )
    return t² · (3 − 2t)
```

`C¹` neprekidna na oba kraja. Oštar prag je zabranjen: proizvodi vidljivu konturu duž linija
iste svetline (rub u nebu ili na koži gde ga u sceni nema).

### 7.2 Četiri maske

Sve nad lumom `Y' ∈ [0,1]`, skraćeno `S(a,b) = smoothstep(a, b, Y')`:

```
w_bl(Y') = 1 − S(0.00, 0.25)                        blacks
w_sh(Y') = S(0.00, 0.25) · ( 1 − S(0.25, 0.60) )    shadows
w_hi(Y') = S(0.40, 0.75) · ( 1 − S(0.75, 1.00) )    highlights
w_wh(Y') = S(0.75, 1.00)                            whites
```

### 7.3 Ponašanje

| `Y'` | `w_bl` | `w_sh` | `w_hi` | `w_wh` |
|---|---|---|---|---|
| 0.00 | 1.000 | 0.000 | 0.000 | 0.000 |
| 0.25 | 0.000 | 1.000 | 0.000 | 0.000 |
| 0.50 | 0.000 | 0.198 | 0.198 | 0.000 |
| 0.75 | 0.000 | 0.000 | 1.000 | 0.000 |
| 1.00 | 0.000 | 0.000 | 0.000 | 1.000 |

Dve osobine su namerne i vredi ih proveriti u testu:

- **`w_bl + w_sh = 1` na celom [0, 0.25]** i **`w_hi + w_wh = 1` na celom [0.75, 1]** — parovi
  koji dele kraj opsega predaju jedan drugom težinu bez rupe i bez preklapanja.
- **Srednji tonovi su zaštićeni**: na `Y' = 0.5` ukupna težina sva četiri je `0.3965`, i
  `w_sh` i `w_hi` su tu tačno jednaki (`0.1983`) jer je `0.5` na istom relativnom mestu u oba
  prozora. Sredina pripada krivi i kontrastu, ne regionalnim slajderima.

Domeni: `blacks` [0, 0.25] · `shadows` [0, 0.60] · `highlights` [0.40, 1.00] ·
`whites` [0.75, 1.00]. Preklapanje `shadows`/`highlights` na [0.40, 0.60] je malo sa obe
strane i namerno — bez njega bi postojala svetlina koju nijedan regionalni slajder ne dohvata.

### 7.4 Priznata granica tačnosti

Lightroomove maske su **sadržajno adaptivne** — gledaju lokalno okruženje piksela. Naše su
čiste funkcije lume tog piksela.

Posledica (plan §4.2): fitovanje u Fazi 2 neće uvek savršeno reprodukovati ekspertski edit.
Master kriva pokupi većinu ostatka, a **ostatak greške se meri i prijavljuje**, ne skriva se
kao pretpostavka.

---

## 8. Numerički ugovor

### 8.1 Preciznost

**`float32` u obe implementacije.** NumPy podrazumevano računa u `float64` — mora se
eksplicitno tražiti `float32`. GLSL ES 3.0 fragment shader mora navesti
`precision highp float;` **eksplicitno**, jer je podrazumevana preciznost u fragment shaderu
`mediump`.

### 8.2 Dozvoljene funkcije

Renderer koristi isključivo: `+ − · /`, `pow`, `exp2`, `min`, `max`, `floor`, `sqrt`.

**Bez trigonometrije, bez logaritama, bez `exp`.** Ovo je namerno ograničenje: `sin`, `cos` i
`asin` razlikuju se u poslednjim bitovima između NumPy-ja i GLSL implementacija, i trošile bi
budžet ΔE ni za šta. Sve formule u ovom dokumentu su izabrane tako da to ograničenje poštuju.

### 8.3 Konstante

| Oznaka | Vrednost | Gde |
|---|---|---|
| `K_WB` | `0.5` | §3.1, jačina balansa bele |
| `K_REG` | `0.25` | §3.3, jačina tonskih regiona |
| `ε` | `1e-6` | §3.6, zaštita deljenja |
| `N` | `1024` | §6.3, veličina LUT-a |

### 8.4 Kvantizacija

Izlaz renderera je `float32` u [0,1]. Za poređenje i prikaz kvantizuje se na 8 bita:

```
out8 = floor( x · 255 + 0.5 )
```

`readPixels` iz `RGBA8` framebuffera vraća već kvantizovane cele brojeve — GPU je zaokružio
sam. NumPy strana mora primeniti **isto** pravilo, inače se poredi 8-bitni izlaz sa
neprekidnim i razlika je sistematska, na svakom pikselu, u istom smeru.

Granični slučaj: OpenGL specifikacija ne propisuje ponašanje pri tačnoj polovini. Razlika od
jednog LSB-a na retkim pikselima je unutar tolerancije §8.5.

### 8.5 Šta je tolerancija a šta nije

| Slučaj | Kriterijum |
|---|---|
| netrivijalan recept | `srednji ΔE < 1`, `maksimalni ΔE < 3` (CIEDE2000) |
| `neutral.json` | **bit-identičnost** ulazu, u obe implementacije |

Bit-identičnost za neutralan recept nije stroža bez razloga — po §4.1 se nad njim ne
izvršava nijedna operacija. Ako taj test padne, greška je u logici preskakanja, ne u
preciznosti.

---

## 9. Šta ovaj dokument ne pokriva

| Šta | Gde pripada |
|---|---|
| ΔE, CIELAB, CIEDE2000 | merni alat, ne renderer — `ml/photoassistant/renderer/color.py`, Faza 1 zadatak 3 |
| fitovanje parametara na par pre/posle | plan §4.3, Faza 2 |
| prevod FiveK jedinica u našu skalu | plan §3, `docs/edit_schema_v1.md` §4, Faza 2 |
| HSL, split toning, kriva po kanalu | šema 2; slotovi 8 i 10 rezervisani |
| učitavanje slika, upravljanje teksturama, `MAX_TEXTURE_SIZE` | implementacioni sloj, plan §11 |
| crop, izoštravanje, uklanjanje šuma | prostorne operacije, van per-piksel modela |

---

## 10. Otvorena pitanja za potvrdu

Konstante iz §8.3 i pragovi maski iz §7.2 su **izbor, ne izvedena vrednost**. Birani su tako
da daju upotrebljiv raspon na krajevima opsega i da maske lepo predaju težinu jedna drugoj,
ali nisu kalibrisani podacima — dataset se ne dodiruje do Faze 2.

Provera dolazi sama, u Fazi 2: ako se fitovane vrednosti nekog parametra gomilaju na `±100`,
skala tog parametra je preslaba i konstanta se koriguje. Ako se gomilaju oko nule, prejaka je.
Takva korekcija je izmena ovog dokumenta i traži ADR.

Za `whites` ne postoji direktan FiveK izvor (`docs/edit_schema_v1.md` §3, napomena) — postoji
radi simetrije editora i kao stepen slobode pri fitovanju. Očekivano je da mu fitovanje
dodeljuje male vrednosti.
