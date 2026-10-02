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

### Uden terminal: hent og dobbeltklik

1. Hent `boligvagten-<version>.zip` fra
   [seneste udgivelse](https://github.com/arminpasalic/boligvagten/releases/latest)
   og pak den ud.
2. Dobbeltklik på **Start Boligvagten** (`.command` på macOS, `.bat` på
   Windows).
3. Boligvagten åbner i din browser. Sæt dine søgninger, filtre og beskeder
   til telefonen op dér, og tryk Gem.

Lad fanen være åben, så længe du vil have besked. Lukker du den, stopper
Boligvagten; dine indstillinger og listen over sete boliger gemmes i
`~/.config/boligvagten/` til næste gang.

Der installeres ingenting. Har computeren ikke Python 3.9 eller nyere, hentes
en midlertidig kopi, som slettes igen, når Boligvagten stopper. Første gang
kan macOS eller Windows advare om filen: se trinene i
[README.md](README.md#no-terminal-download-and-double-click) eller i
`README.txt` i zip-filen.

### Auto-kontakt (valgfrit)

Boligvagten kan udfylde udlejerens kontaktformular hos CEJ og Kereby, så snart
en ny bolig dukker op. På siden vælger du for hver side **Fra**, **Kun test**
(udfyld og gem et billede, send intet) eller **Send**, og **Prøv nu** viser,
hvad der ville blive sendt. Alt er slået fra som standard. Kræver en browser,
som hentes midlertidigt (ca. 150 MB) og slettes igen, når Boligvagten stopper.

### Fra terminalen

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
| kereby.dk | leje | København |
| cityapartment.dk | leje | København |
| boligsiden.dk | **køb** | hele Danmark |

Mangler der en side? Opret et
[site request](https://github.com/arminpasalic/boligvagten/issues/new?template=site_request.yml)
— eller skriv selv modulet på ~40 linjer.

---

Resten af dokumentationen er på engelsk: **[README.md](README.md)** (alle
kommandoer, filtre og CEJ-autokontakt) ·
[CONTRIBUTING.md](CONTRIBUTING.md) · [CHANGELOG.md](CHANGELOG.md)
