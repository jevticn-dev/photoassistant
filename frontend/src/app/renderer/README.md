# renderer

WebGL2 implementacija renderera. **Bez ijedne Angular zavisnosti.**

Puni se u Fazi 1, posle `docs/RENDERER_SPEC.md`.

## Pravilo koje se ne krši

Nijedan `import` iz `@angular/*` u ovom folderu. Nema dekoratora, nema DI, nema signala —
samo funkcije i klase nad `WebGL2RenderingContext` i tipovima šeme izmene.

Razlog nije čistota nego merljivost: ovaj kod mora biti **uporediv sa Python
implementacijom** kroz golden test (isti recept, ista slika, razlika ispod praga ΔE).
Angular zavisnost tu granicu ruši, jer test više ne bi mogao da ga pokrene izolovano.

Granicu čuva `renderer.spec.ts`, po ugledu na `LayerDependencyTests` u backendu i
`test_library_boundary.py` u ML paketu.

## Šta ulazi

| Fajl          | Sadržaj                                                  | Faza |
| ------------- | -------------------------------------------------------- | ---- |
| `types.ts`    | TypeScript model šeme izmene (treći od tri jezika)       | 1    |
| `lut.ts`      | generisanje LUT tabele od 1024 vrednosti iz tačaka krive | 1    |
| `shader.ts`   | fragment shader, redosled operacija iz plana §4.1        | 1    |
| `renderer.ts` | priprema konteksta, tekstura, uniformi; petlja crtanja   | 1    |
