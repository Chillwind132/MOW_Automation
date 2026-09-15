# MOW Automation

Python automation for **Men of War: Assault Squad 2**: host matches,
record results, and review games and ratings in your browser.

> [!NOTE]
> **Alpha software.** There are rough edges and some development slop. All core
> MOW interfaces are implemented and working: lobby control, match recording,
> replay results, chat, and review.

---

<img width="1658" height="796" alt="image" src="https://github.com/user-attachments/assets/2c3f77a4-19f5-4112-806e-f5072148c90f" />

<img width="1665" height="923" alt="image" src="https://github.com/user-attachments/assets/da5758d9-56a5-44fe-b6a6-82454d03360d" />


## Setup

Use Windows with Python, Steam, and Men of War: Assault Squad 2 installed.
The native bridge targets engine **3.262.1**. The automatic-host example below
requires Robz Realism and the specified map and armies to be available. Enable
the mod in-game first and select the map in the multiplayer lobby before your
first automatic run: `--expected-map` checks the remembered map; it does not
download or select it for you.

Install dependencies with `py -m pip install -r requirements.txt`.

Open PowerShell in the project root. The supported entry point is
`headless_host.py`. Keep the controller terminal open while recording or hosting.

**Sample results:** [examples/rankbot.sqlite3](examples/rankbot.sqlite3) contains
real match statistics and ratings with anonymized identities. On a fresh
installation, create `data/` and copy this file to `data/rankbot.sqlite3`
to explore the review UI. **Do not overwrite an existing database.**
See [sample data notes](examples/README.md) for what is included.

## 1. Record while you play or host manually

```powershell
py headless_host.py friends-host --record-only
```

Launches or attaches to the game and records matches. You control the lobby and
play normally. Record-only mode observes through Frida; it does not change game
settings, start matches, or send chat. Finals come from completed saved replays.

## 2. Host automatically

```powershell
py headless_host.py friends-host --minimize --min-players 4 --rating-profile robz-battle-zones --expected-map "multi/3v3_big_desert_town:battle_zones" --team-a-army rus_guard --team-b-army ger
```

Runs a minimized spectator host for four playing slots, with Russian Guards on
Team A and Germany on Team B. All ready players
on opposing teams can unanimously type `/start` to start early.

After saving a completed match and returning to the lobby, automatic hosting
restarts the game and prepares a new lobby. 

## 3. Review saved results

```powershell
py headless_host.py review --serve
```

Opens a local browser service for saved matches, player statistics, and ratings.
Keep its terminal open; the page refreshes every five seconds. Use the match
settings button to record a winner and reason when the result is undetermined.

Your results stay in `data/rankbot.sqlite3`.

---

Ctrl+C stops the controller or review service. Stopping the controller leaves
the game open; an independent replay watcher may continue importing finals.

## Documentation

- [Operating guide](docs/README.md): hosting options, optional game master, and troubleshooting
- [Controls and data](docs/REFERENCE.md): status, hold, stop, and database queries
- [Rating policy](docs/RATINGS.md)
- [Project structure](docs/STRUCTURE.md) and [module contracts](docs/MODULES.md)
- [Public-release notes](docs/PUBLISHING.md)
