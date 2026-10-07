# PhotoAssistant

Sistem preporuke stilova obrade fotografija sa web editorom.

Korisnik učita fotografiju, a sistem mu na osnovu njenog sadržaja predlaže **tri stilski
različita predloga obrade**. Predlozi se primenjuju i doteruju u editoru sa live
preview-om, a rad se čuva nedestruktivno po projektima — svaka sačuvana verzija je
kompletan „recept", ne izmenjena slika.

Predlozi se ne generišu iz pravila nego se uče iz primera: offline pipeline obrađuje
25.000 ekspertskih obrada iz [MIT-Adobe FiveK](https://data.csail.mit.edu/graphics/fivek/)
dataseta, rekonstruiše svaku od njih kao skup parametara sopstvene šeme izmene, i
indeksira ih vektorski. Umesto jednog „optimalnog" rešenja sistem nudi više različitih,
jer je obrada fotografije subjektivna.

Diplomski rad — Prirodno-matematički fakultet, Univerzitet u Kragujevcu.
**Status:** ceo korisnički put radi od kraja do kraja; rad na aplikaciji se nastavlja.

## Šta aplikacija ume

- **Registracija i prijava** (ASP.NET Core Identity + JWT).
- **Upload fotografije** — iz nje se prave dve izvedene kopije: 512 px za pretragu i
  2048 px za editor. Upload otvara projekat.
- **Tri predloga obrade** — fotografija se koduje CLIP-om, u bazi se nađu slične scene, a iz
  njihovih ekspertskih obrada biraju se tri. Sličice predloga crta pregledač, istim
  rendererom kojim radi editor, pa je ono što se bira tačno ono što se dobija.
- **Editor sa živim prikazom** — svi parametri šeme izmene i tonska kriva sa kontrolnim
  tačkama, nad 2048 px kopijom kroz WebGL2, bez ijednog poziva serveru po pomeraju slajdera.
  Poređenje pre/posle, undo/redo, rad na uskim ekranima.
- **Verzije** — svaka sačuvana verzija je ceo recept. Ranija verzija se otvara iz trake sa
  leve strane, a vraćanje na nju pravi **novu** verziju: istorija se ne prepisuje.
- **Export pune rezolucije** — renderuje se netaknuti original, u pozadini, kroz red poslova.
  Izlaz je PNG, bez gubitaka. Svi izvezeni fajlovi projekta su dostupni sa njegove kartice.

## Kako radi

```
upload → derivati (512 / 2048) → embedding sadržaja → pretraga sličnih fotografija
       → bazen kandidat-obrada → izbor tri → editor → verzije → export
```

Obrada je opisana **šemom izmene** — verzionisanim JSON zapisom sa 11 parametara
(balans bele, tonske korekcije, boja, tonska kriva). Isti zapis koriste svi delovi
sistema, pa je „recept" prenosiv između pipeline-a, baze, editora i exporta.

Ključna posledica: obrade iz dataseta se ne prevode iz Lightroom parametara, nego se
**rekonstruišu iz rezultata** — traže se vrednosti naših parametara koje nad polaznom
slikom daju najbliži rezultat ekspertskoj verziji. Sistem bi radio isto da je obrada
nastala u bilo kom drugom alatu.

Renderer postoji u dve implementacije — NumPy za server i pipeline, WebGL2 za live preview
u pregledaču. Obe prevode istu specifikaciju ([`docs/RENDERER_SPEC.md`](docs/RENDERER_SPEC.md)),
a njihova saglasnost se dokazuje testom nad fiksnim skupom slika i recepata: 295 kombinacija,
najgori piksel ΔE 0,108 uz prag 3.

## Tehnologije

| Sloj | Tehnologija |
|---|---|
| Frontend | Angular 22 (zoneless, signali), Angular CDK, WebGL2 renderer |
| Backend | .NET 10, ASP.NET Core Identity + JWT, Clean Architecture |
| ML servis | Python 3.14, FastAPI, NumPy, PyTorch (CLIP) |
| Baza | PostgreSQL 18 + pgvector (HNSW) |
| Skladište | MinIO (S3 API) |

## Struktura

```
backend/    .NET API — jedina javna vrata (auth, projekti, istorija, orkestracija)
frontend/   Angular SPA sa editorom
ml/         Python paket (biblioteka) + FastAPI servis (interni)
pipeline/   offline skripte koje uvoze isti Python paket
fixtures/   deljeni test podaci za testove saglasnosti
infra/      docker-compose, nginx, init skripte baze
docs/       specifikacija renderera i dokumenti za mentore
sandbox/    istraživačke skripte, nisu deo isporuke
```

## Pokretanje, od početka

Aplikacija se sastoji od dva dela koji nastaju različito: **servisi** se podižu jednom
komandom, a **korpus** — 25.000 obrada nad kojima preporuka radi — pravi se jednom, offline
pipeline-om nad FiveK datasetom. Bez korpusa aplikacija radi, ali predlozi nemaju iz čega da
se biraju. Koraci ispod su redom kojim se izvode.

Potrebno: Docker, [uv](https://docs.astral.sh/uv/) (Python okruženje za pipeline), oko 60 GB
slobodnog prostora (arhiva dataseta ~50 GB, izvedene kopije ~12 GB), i stabilna veza — pipeline
preuzima oko 1,6 TB. Sve komande se izvršavaju iz korena repoa.

### 1. Konfiguracija

```bash
cp .env.example .env        # popuniti vrednosti; FIVEK_DATASET_PATH za sada može ostati prazan
```

Vrednosti koje sadrže razmak (npr. putanju do dataseta) staviti pod navodnike; bez toga se fajl
ne može učitati iz shell-a.

### 2. Servisi

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d
docker compose --env-file .env -f infra/docker-compose.yml ps    # čekati da svi budu healthy
```

Prvo pokretanje gradi tri slike (ML slika je oko 2 GB, jer nosi PyTorch) i traje desetak
minuta. Pri pokretanju API **migrira bazu**, a pomoćni kontejner pravi tri bucket-a u
skladištu — to su preduslovi za pipeline, pa ovaj korak ide pre njega.

Aplikacija je od ovog trenutka dostupna na http://localhost:4200, ali sa praznim korpusom.

### 3. Dataset

Sa [stranice FiveK dataseta](https://data.csail.mit.edu/graphics/fivek/) preuzeti arhivu (oko
50 GB) i raspakovati je, pa u `.env` postaviti `FIVEK_DATASET_PATH` na raspakovani direktorijum.
Pipeline iz nje čita katalog `raw_photos/fivek.lrcat` i spiskove `filesAdobe.txt` i
`filesAdobeMIT.txt`; same fotografije i ekspertske obrade preuzima zasebno, u koraku 4.

FiveK je pod **istraživačkom licencom bez komercijalne upotrebe**. Njegove slike se ne nalaze u
repozitorijumu ni u test podacima, i ne ulaze u isporuku.

Direktorijum dataseta pipeline samo čita; katalog je SQLite baza i otvara se isključivo za
čitanje.

### 4. Korpus

Komande same postavljaju Python okruženje (`uv run`); samo korak 4.5 traži `--extra
embeddings`, jer jedino on pokreće CLIP. Pipeline sam čita `.env`. Svaki korak je ponovljiv i
nastavlja tamo gde je stao — stanje se vodi u bazi, pa se prekinut korak prosto pokrene ponovo.

| | Korak | Šta radi | Trajanje |
|---|---|---|---|
| 4.1 | `uv run --project ml python -m pipeline.parse_catalogue` | čita katalog: 5.000 fotografija, 25.000 obrada | sekunde |
| 4.2 | `uv run --project ml python -m pipeline.fetch_derive` | preuzima polaznu i pet ekspertskih verzija svake fotografije, pravi 512 px i 2048 px kopije u skladište, a original briše | ~9 h |
| 4.3 | `uv run --project ml python -m pipeline.fit_all` | za svaku ekspertsku obradu traži vrednosti naših parametara koje daju najbliži rezultat | jedna noć |
| 4.4 | `uv run --project ml python -m pipeline.refit_worst --confirm` | detaljnija pretraga nad najgorih 5%; nikad ne pogoršava | ~3 h, opciono |
| 4.5 | `uv run --project ml --extra embeddings python -m pipeline.embed_all --content` | CLIP vektor svake fotografije, za pretragu po sadržaju | minuti |
| 4.6 | `uv run --project ml python -m pipeline.embed_all --style` | stilski otisak svake obrade | minuti |
| 4.7 | `uv run --project ml python -m pipeline.publish --confirm` | upisuje 19 obrada koje šema ne ume da predstavi i proverava da je sve potpuno | sekunde |

**Redosled je obavezan.** Otisak u 4.6 se računa iz recepata, pa mora doći posle fitovanja *i*
posle 4.4, koji prepisuje recepte najgorih 5% — otisci izračunati pre toga opisivali bi recepte
koji više ne postoje, i ništa to ne bi prijavilo. Konstante skaliranja otiska su u repozitorijumu
(`pipeline/reports/fingerprint_scaling.json`) i ne računaju se ponovo.

`pipeline.publish --verify` pre 4.7 pokazuje šta nedostaje, bez ikakvog upisa.

Za manji korpus, `fetch_derive` i `fit_all` primaju `--experts` (npr. `--experts c` za jednog
eksperta — oko trećine prenosa). Merenja u radu su izvedena nad svih pet.

### 5. Gotovo

Posle koraka 4 aplikacija na http://localhost:4200 daje predloge. Servisi ne moraju da se
restartuju — preporuka korpus čita iz baze na svaki zahtev.

| | Adresa |
|---|---|
| Aplikacija | http://localhost:4200 |
| Health | http://localhost:4200/health |
| API dokumentacija (van produkcije) | http://localhost:8080/scalar/v1 |
| OpenAPI dokument (van produkcije) | http://localhost:8080/openapi/v1.json |
| MinIO konzola | http://localhost:9001 |

ML servis namerno nema objavljen port — interni je i dostupan samo .NET API-ju, a nginx
proksira isključivo `/api/` i `/health`. Prvi zahtev za predloge preuzima CLIP težine (oko
600 MB) u volumen `mlcache`, pa traje nekoliko sekundi duže.

### Zaustavljanje

```bash
docker compose --env-file .env -f infra/docker-compose.yml down      # podaci ostaju
```

> **`down -v` briše i volumene** — bazu sa korpusom i skladište sa izvedenim kopijama, čija
> ponovna izgradnja je ceo korak 4. Ne koristiti je kao način zaustavljanja.

## Razvoj

Za svakodnevni rad u Dockeru rade samo baza i skladište, a servisi lokalno:

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d postgres minio

dotnet run --project backend/src/PhotoAssistant.Api --urls http://localhost:8080
npm --prefix frontend start                                   # http://localhost:4200
```

ML servis pokrenut lokalno **ne čita `.env` sam**, a u kontejneru mu promenljive daje compose.
Na hostu se postavljaju iz `.env`, uz preimenovanje u imena koja kontejner koristi:

```bash
set -a; source .env; set +a
export POSTGRES_HOST=$POSTGRES_HOST_LOCAL S3_ENDPOINT=$S3_ENDPOINT_LOCAL \
       S3_ACCESS_KEY=$MINIO_ROOT_USER S3_SECRET_KEY=$MINIO_ROOT_PASSWORD
uv run --project ml --extra service --extra embeddings uvicorn service.main:app --port 8000
```

`--extra embeddings` je potreban za predloge, jer oni na svaki zahtev računaju CLIP vektor;
bez njega servis radi, ali `POST /recommend` odbija.

Dve zamke:

- `dotnet build` ne uspeva dok lokalni API radi, jer drži svoje DLL-ove — prvo ga zaustaviti.
- Dev server ne primećuje **novu** lenjo učitanu rutu; posle dodavanja rute ga restartovati.

## Testovi

```bash
dotnet test backend/PhotoAssistant.slnx
uv run --project ml --extra service pytest ml/tests pipeline/tests
uv run --project ml --extra service ruff check ml fixtures pipeline
npm --prefix frontend test
npm --prefix frontend run format:check
```

Testovi shadera se izvršavaju u pravom pregledaču, pa prvi put traže Playwright:

```bash
npx --prefix frontend playwright install chromium
npm --prefix frontend run test:browser
```

Saglasnost dva renderera se meri u dva koraka, jer se ΔE računa samo u Pythonu — prvi
renderuje u pregledaču, drugi poredi:

```bash
npm --prefix frontend run golden
uv run --project ml --extra service pytest ml/tests/golden
```

Backend integracioni testovi traže podignut Postgres kontejner i koriste zasebnu bazu, da
razvojni podaci ostanu netaknuti.
