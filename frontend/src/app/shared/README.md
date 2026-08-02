# shared

Komponente i pomoćne funkcije koje koristi više od jedne celine iz `features/`.

Prazan do Faze 4 — dok ne postoje dve celine koje nešto dele, ovde nema šta da stoji.

**Pravilo koje sprečava da postane odlagalište:** ovde se premešta tek kad drugi
`feature` stvarno zatraži isti kod. Ne unapred, „jer će verovatno zatrebati" — takav kod se
oblikuje prema jedinom postojećem korisniku i posle smeta drugom.

Suprotan smer je zabranjen: `feature` ne uvozi iz drugog `feature`-a.
