# boligvagten 🏠

**Vær først til danske boligannoncer — leje *og* køb.** Boligvagten holder øje
med danske boligsider døgnet rundt og sender en notifikation til din telefon i
samme øjeblik, noget nyt dukker op — for i København måles forskellen på en
fremvisning og ingenting som regel i minutter.

*🇬🇧 [Read this page in English](README.md)*

[![CI](https://github.com/arminpasalic/boligvagten/actions/workflows/ci.yml/badge.svg)](https://github.com/arminpasalic/boligvagten/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/boligvagten)](https://pypi.org/project/boligvagten/)
[![Licens: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![Afhængigheder: ingen](https://img.shields.io/badge/dependencies-none-brightgreen)

```
[2026-07-06T19:09:16] 3 new listing(s):
  • [cej] Nordre Fasanvej 119, 2000 Frederiksberg — 1r, 29m², 6.929 DKK/md
    https://udlejning.cej.dk/boliger/f71591e2...
  • [kereby] Valby Langgade 36, 2500 Valby — 3r, 86m², 17.200 DKK/md
    https://kerebyudlejning.dk/bolig/a8ead8ef...
  • [boligsiden] Gunløgsgade 22, 3. 2, 2300 København S — 2r, 47m², 3.975.000 DKK (ejerudgift 3.645 kr./md)
    https://www.boligsiden.dk/adresse/gunloegsgade-22...
```
*…og samme besked lander på din telefon som push-notifikation.*

## Hvorfor findes det her?

- **Portalerne er ikke nok.** Alle holder øje med boligportal.dk. De private
  administratorer (CEJ, Kereby, City Apartment, …) slår gode lejligheder op på
  deres egne sider, hvor langt færre kigger — boligvagten holder øje med begge
  verdener på én gang.
- **Skal du købe? Samme spil.** Nye salgsannoncer (via Boligsiden) rammer din
  telefon minutter efter de går live — ikke i morgendagens søgeagent-mail.
- **Hastighed vinder.** Populære annoncer samler hundredvis af henvendelser på
  få timer. En øjeblikkelig push-notifikation (og evt. en automatisk udfyldt
  kontaktformular, se nedenfor) sætter dig forrest i køen.
- **Ingen opsætningsbøvl.** Ren Python-standardbibliotek — ingen konti, ingen
  API-nøgler, ingen database, ingen afhængigheder. Én kommando, abonnér på din
  kanal, færdig.
- **Bygget til at blive forket.** Kilder er plug-in-moduler, filtre og byer er
  konfiguration, og parserne er dækket af offline-tests. At få den til at
  overvåge *din* by eller *din* yndlingsside er en lille, dokumenteret ændring.

## Kom i gang

Med [uv](https://docs.astral.sh/uv/) (eller `pipx install boligvagten`):

```bash
uvx boligvagten
```

Eller klon og kør — monitoren er rent standardbibliotek, så der er intet
`pip install`-trin:

```bash
git clone https://github.com/arminpasalic/boligvagten.git
cd boligvagten
python3 monitor.py
```

Første kørsel opretter din personlige `config.py` (i checkoutet, eller i
`~/.config/boligvagten/` når den er installeret), genererer en privat
notifikationskanal og printer præcis, hvad du skal gøre: installér den gratis
[ntfy](https://ntfy.sh)-app, abonnér på dit emne, og lad monitoren køre.
Det er hele opsætningen.

> Notifikationerne kører på den gratis, offentlige [ntfy.sh](https://ntfy.sh)
> (ingen konto nødvendig). Self-hoster du ntfy? Peg `NTFY["server"]` på din
> egen instans i `config.py`.

## Daglige kommandoer

| Kommando | Hvad den gør |
|---|---|
| `boligvagten` | Overvåg konstant, alarmér ved nye annoncer |
| `boligvagten --list` | Engangssøgning: print alt der matcher dine filtre lige nu |
| `boligvagten --once` | Kør ét tjek og stop (praktisk til cron) |
| `boligvagten --test-notify` | Send en testnotifikation til alle kanaler |
| `boligvagten --setup` | Print telefon-opsætningen igen |
| `boligvagten --contact-cej URL` | Tørkør CEJ-kontaktformularen på én annonce |

Kører du fra et klon? `python3 monitor.py` tager de samme flag.

## Konfiguration

Alt ligger i `config.py` — en grundigt kommenteret Python-fil oprettet fra
[config.example.py](config.example.py) ved første kørsel. Den er gitignoreret:
dit emne, dine søgninger og (hvis du slår auto-kontakt til) dine personlige
oplysninger forlader aldrig din maskine.

**Filtre** gælder alle kilder, med valgfrie undtagelser pr. kilde:

```python
FILTERS = {
    "max_price_dkk": 14000,
    "min_rooms": 2,
    "min_size_m2": 50,
    "exclude_keywords": ["studiebolig", "delevenlig"],
    "description_keywords": ["altan"],   # skal stå i den fulde beskrivelse
}
```

Alle nøgler er valgfrie; derudover findes `min_price_dkk`, `max_rooms`,
`max_size_m2`, `include_keywords` og ejerudgiftsgrænser
(`min`/`max_monthly_fee_dkk`) til salgsmarkedet. Ukendte værdier slipper altid
igennem — hellere én notifikation for meget end en overset bolig.

**En anden by?** Søge-URL'en *er* søgningen — by, pris og størrelse ligger i
den. Åbn siden, sæt dine filtre, kopiér URL'en ind i kildens config-post. Hver
post i [config.example.py](config.example.py) dokumenterer sidens særlige
trick (Boligportal: brug din bys side, fx `/lejeboliger/aarhus/`; CEJ: tilføj
én query-param; Boligsiden: redigér de dokumenterede API-params; …).

**Flere søgninger på én gang?** Giv en kilde en liste med `"urls": [...]`.

**Tempo**: intervallerne er tilfældige (60–180 s som standard). Vær høflig —
hurtigere end ~30 s hjælper ingen og risikerer sidernes opmærksomhed.

## Understøttede kilder

| Kilde | Side | Marked | Dækning | Læses via |
|---|---|---|---|---|
| `boligportal` | boligportal.dk | leje | hele Danmark | server-renderet HTML |
| `cej` | udlejning.cej.dk | leje | Sjælland / København | Remix-dataendpoint |
| `kereby` | kerebyudlejning.dk | leje | København | offentligt JSON-API |
| `cityapartment` | cityapartment.dk | leje | København | server-renderet HTML |
| `boligsiden` | boligsiden.dk | **køb** | hele Danmark | offentligt JSON-API |

Mangler der en side? Det er den sjove del — se
[CONTRIBUTING.md](CONTRIBUTING.md): kopiér
[skabelonen](boligvagten/sources/_template.py), skriv én `parse()`-funktion,
registrér den, færdig. PRs er velkomne — eller opret et
[site request](https://github.com/arminpasalic/boligvagten/issues/new?template=site_request.yml).

## Auto-kontakt (CEJ) — valgfrit

CEJ-annoncer oversvømmes af henvendelser næsten øjeblikkeligt. Boligvagten kan
udfylde CEJ's kontaktformular i tre trin automatisk, i samme øjeblik en annonce
dukker op: dine oplysninger, din besked til udlejer, din profil.

Den er **slået fra som standard**, og sikkerhedskontakten `live_send` forbliver
slået fra selv når du aktiverer den — formularen udfyldes og screenshotter
(`cej_phase3.png`), men **indsendes ikke**, før du har tjekket resultatet og
vendt kontakten. **Brug det ansvarligt** — det indsender en rigtig
boligansøgning i dit navn.

## Sådan virker det

Intet framework, fem små moduler: `monitor.py` (poll → diff mod
`seen_listings.json` → alarmér), `sources/` (ét modul pr. side),
`filters.py`, `notify.py`, `contact_cej.py`. Nye annoncer genkendes på ID,
tilstanden overlever genstarter, netværksfejl bakker eksponentielt af, og
hver parser testes offline mod optagne fixtures (`tests/`).

## Relaterede projekter

- [bolig-ping](https://github.com/saattrupdan/bolig_ping) — søgning på
  Boligsidens salgsmarked som engangskommando med e-mail-opsummeringer; kør
  den fra cron hvis e-mail passer dig bedre end push. Boligvagtens
  Boligsiden-understøttelse er inspireret af den.

## Ansvarsfraskrivelse

Boligvagten poller offentligt tilgængelige annoncesider på dine vegne, i et
menneskeligt tempo, til personlig brug. Respektér siderne: hold intervallerne
fornuftige, kør ikke flere aggressive instanser, og tjek betingelserne for de
sider, du slår til. Projektet er ikke tilknyttet nogen af de nævnte sider.

## Licens

[MIT](LICENSE)
