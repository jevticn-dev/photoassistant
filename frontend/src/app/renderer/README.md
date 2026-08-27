# renderer

WebGL2 implementacija renderera. **Bez ijedne Angular zavisnosti.**

Prevod dokumenta `docs/RENDERER_SPEC.md`. Drugi prevod istog dokumenta je NumPy implementacija
u `ml/photoassistant/renderer/`; nijedna od te dve nije referenca za drugu. Golden test
dokazuje da se slažu.

## Pravilo koje se ne krši

Nijedan `import` iz `@angular/*` u ovom folderu. Nema dekoratora, nema DI, nema signala —
samo funkcije i klase nad `WebGL2RenderingContext` i tipovima šeme izmene.

Razlog nije čistota nego merljivost: ovaj kod mora biti **uporediv sa Python
implementacijom** kroz golden test (isti recept, ista slika, razlika ispod praga ΔE).
Angular zavisnost tu granicu ruši, jer test više ne bi mogao da ga pokrene izolovano.

Granicu čuva `boundary.spec.ts`, po ugledu na `LayerDependencyTests` u backendu i
`test_library_boundary.py` u ML paketu. Zavisnost ide u jednom smeru: test stranica
(`features/renderer-lab/`) uvozi renderer, renderer ne zna da Angular postoji.

## Šta je unutra

| Fajl          | Sadržaj                                                              |
| ------------- | -------------------------------------------------------------------- |
| `schema.ts`   | TypeScript model šeme izmene (treći od tri jezika), sa validacijom   |
| `curve.ts`    | Fritsch–Carlson interpolacija i LUT od 1024 vrednosti (spec §6)      |
| `shader.ts`   | GLSL ES 3.00 program — ceo redosled operacija iz plana §4.1          |
| `pipeline.ts` | množioci balansa bele, skala ekspozicije, pravilo preskakanja (§4.1) |
| `renderer.ts` | kontekst, teksture, uniforme, crtanje, čitanje piksela               |
| `index.ts`    | javna površina modula                                                |

## Testovi

| Fajl                       | Gde radi | Šta tvrdi                                            |
| -------------------------- | -------- | ---------------------------------------------------- |
| `boundary.spec.ts`         | jsdom    | nema Angular uvoza                                   |
| `schema.spec.ts`           | jsdom    | saglasnost nad `fixtures/edits/`, pravila validacije |
| `curve.spec.ts`            | jsdom    | interpolacija i LUT, iste tvrdnje kao Python strana  |
| `pipeline.spec.ts`         | jsdom    | množioci balansa bele, pravilo preskakanja           |
| `renderer.browser.spec.ts` | chromium | **namere** iz spec §3, kroz stvarni GPU              |

```bash
npm --prefix frontend test              # jsdom, bez browsera
npm --prefix frontend run test:browser  # chromium kroz Playwright
npm --prefix frontend run golden        # renderuje sve kombinacije za golden test
```

Golden test saglasnosti ide u dva koraka, jer ΔE postoji samo u Pythonu:

```bash
npm --prefix frontend run golden                        # browser upisuje PNG-ove
uv run --project ml --extra service pytest ml/tests/golden   # Python meri ΔE
```

Dve komande zato što `*.browser.spec.ts` traži pravi WebGL2 kontekst, a ostalo ne. jsdom
nema WebGL; `headless-gl` je odbačen jer implementira WebGL 1.0, pa ne može ni da prevede
GLSL ES 3.00.
