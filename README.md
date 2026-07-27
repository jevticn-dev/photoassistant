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
**Status: u izradi.**

## Kako radi

```
upload → normalizacija → embedding sadržaja → pretraga sličnih fotografija
       → bazen kandidat-obrada → izbor tri međusobno različite → editor → export
```

Obrada je opisana **šemom izmene** — verzionisanim JSON zapisom sa 11 parametara
(balans bele, tonske korekcije, boja, tonska kriva). Isti zapis koriste svi delovi
sistema, pa je „recept" prenosiv između pipeline-a, baze, editora i exporta.

Ključna posledica: obrade iz dataseta se ne prevode iz Lightroom parametara, nego se
**rekonstruišu iz rezultata** — traže se vrednosti naših parametara koje nad polaznom
slikom daju najbliži rezultat ekspertskoj verziji. Sistem bi radio isto da je obrada
nastala u bilo kom drugom alatu.

## Tehnologije

| Sloj | Tehnologija |
|---|---|
| Frontend | Angular 22, WebGL2 renderer za live preview |
| Backend | .NET 10, ASP.NET Core Identity + JWT, Clean Architecture |
| ML servis | Python 3.14, FastAPI, NumPy, PyTorch |
| Baza | PostgreSQL 18 + pgvector (HNSW) |
| Skladište | MinIO (S3 API) |

Renderer postoji u dve implementacije — NumPy za server i pipeline, WebGL2 za live preview
u browseru. Obe prevode istu specifikaciju, a njihova saglasnost se dokazuje testom nad
fiksnim skupom slika i recepata.

## Struktura

```
backend/    .NET API — jedina javna vrata (auth, projekti, istorija, orkestracija)
frontend/   Angular SPA sa editorom
ml/         Python paket (biblioteka) + FastAPI servis (interni)
pipeline/   offline skripte koje uvoze isti Python paket
fixtures/   deljeni test podaci za testove saglasnosti
infra/      docker-compose i konfiguracija okruženja
docs/       dokumentacija
sandbox/    istraživačke skripte, nisu deo isporuke
```

## Pokretanje

Dokumentuje se kad skelet bude kompletan.
