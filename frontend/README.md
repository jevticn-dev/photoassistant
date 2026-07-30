# frontend

Angular 22 SPA (`photoassistant-web`) — editor, preporuke i nalozi.

## Struktura

| Putanja | Sadržaj |
|---|---|
| `src/app/features/<celina>/` | jedna fascikla po celini (`auth`, `projects`, kasnije `editor`, `recommendations`), sa svojim komponentama i rutama; učitavaju se lenjo |
| `src/app/core/` | HTTP interceptor, auth guard, konfiguracija prevoda |
| `src/app/shared/` | deljene komponente i pomoćne funkcije |
| `src/app/renderer/` | **WebGL2 renderer — čist TypeScript, bez Angular zavisnosti** |
| `src/assets/i18n/` | prevodi, učitavaju se u vreme izvršavanja |
| `src/environments/` | adresa API-ja i jezik; ni jedan servis ne sme da je hardkoduje |

`renderer/` je izolovan namerno — mora biti uporediv sa Python implementacijom kroz golden
test. Granicu čuva `renderer.spec.ts`; detalji u `src/app/renderer/README.md`.

## Komande

Iz korena repoa:

```bash
npm --prefix frontend ci        # instalacija iz package-lock.json
npm --prefix frontend start     # dev server na :4200
npm --prefix frontend run build
npm --prefix frontend test
```

## Napomene

- **Zoneless** — `zone.js` nije instaliran. Stanje ide kroz signale, komponente su `OnPush`.
  Razlog nije samo modernost: editor ima WebGL petlju sa `requestAnimationFrame`, koje bi
  `zone.js` presretao i pokretao detekciju promena na svakom frejmu.
- **Svi vidljivi stringovi kroz i18n**, bez izuzetka — uključujući `aria-label`,
  `placeholder` i `title`. Dodavanje srpskog treba da ostane stvar jednog JSON fajla.
- **Frontend zove isključivo .NET API.** ML servis je interni; u razvoju je doduše dostupan
  na `localhost:8000`, pa poziv ka njemu radi lokalno a pukne pod compose-om.
- Testovi se pokreću **vitest**-om, ne karma-om (podrazumevano od Angulara 22).
