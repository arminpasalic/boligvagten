# boligvagten 🏠

**Vær først til danske boligannoncer — leje *og* køb.** Boligvagten holder øje
med danske boligsider døgnet rundt og sender en push-notifikation til din
telefon i samme øjeblik, noget nyt dukker op — for forskellen på en
fremvisning og ingenting måles som regel i minutter.

```
[2026-07-06T19:09:16] 2 new listing(s):
  • [kereby] Valby Langgade 36, 2500 Valby — 3r, 86m², 17.200 DKK/md
  • [boligsiden] Gunløgsgade 22, 3. 2, 2300 København S — 2r, 47m², 3.975.000 DKK (ejerudgift 3.645 kr./md)
```

## Kom i gang

```bash
uvx --from git+https://github.com/arminpasalic/boligvagten.git boligvagten
```

Første kørsel opretter din `config.py`, genererer en privat alarmkanal og
viser præcis, hvad du skal gøre: installér den gratis
[ntfy](https://ntfy.sh)-app, abonnér på dit emne, og lad monitoren køre.
Filtre (pris, værelser, m², nøgleord) og byer sættes i `config.py` — se
[config.example.py](config.example.py), som er kommenteret hele vejen.

## Kilder

| Kilde | Marked | Dækning |
|---|---|---|
| boligportal.dk | leje | hele Danmark |
| udlejning.cej.dk | leje | Sjælland / København |
| kerebyudlejning.dk | leje | København |
| cityapartment.dk | leje | København |
| boligsiden.dk | **køb** | hele Danmark |

Mangler der en side? Opret et
[site request](https://github.com/arminpasalic/boligvagten/issues/new?template=site_request.yml)
— eller skriv selv modulet på ~40 linjer.

---

Resten af dokumentationen er på engelsk: **[README.md](README.md)** (alle
kommandoer, filtre og CEJ-autokontakt) ·
[CONTRIBUTING.md](CONTRIBUTING.md) · [CHANGELOG.md](CHANGELOG.md)
