# ObsidianSync

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-5.2-092E20?logo=django&logoColor=white)
![Poetry](https://img.shields.io/badge/Poetry-managed-60A5FA?logo=poetry&logoColor=white)
![Ruff](https://img.shields.io/badge/Ruff-linting-D7FF64?logo=ruff&logoColor=111111)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg)

ObsidianSync to aplikacja Django do zarządzania backupami vaultów Obsidiana, historią zmian i cyklicznymi snapshotami.

## Stack

- Django
- Django Unfold
- Poetry
- Ruff
- Pydantic Settings
- SQLite na start


## Szybki start

```bash
poetry install
poetry run python manage.py migrate
poetry run python manage.py createsuperuser
poetry run python manage.py runserver
```

Scheduler możesz odpalić osobno:

```bash
poetry run python manage.py run_snapshot_scheduler --interval-seconds 60
```

## Docker

Najprostszy start:

```bash
cp .env.example .env
mkdir -p var/db var/snapshots vaults
docker compose up --build
```

Plik `.env` jest wymagany, bo `docker-compose.yml` wczytuje go przez `env_file`.

To postawi dwa serwisy:

- `web`: Django na `http://localhost:8000`
- `scheduler`: worker od cyklicznych snapshotów

Pierwszego admina utwórz tak:

```bash
docker compose exec web python manage.py createsuperuser
```

Jeśli chcesz backupować lokalne vaulty z innej ścieżki na komputerze, ustaw w `.env`:

```env
VAULT_HOST_PATH=/path/to/vault
```

Compose podmontuje wtedy ten katalog jako `/vaults` w kontenerze. W panelu `Vault.source_path` ustawiaj ścieżki widoczne z kontenera, np. `/vaults/MyVault`.

Uwaga: mount vaulta jest w trybie zapisu, więc operacje `checkout`, `restore` i `merge` mogą realnie nadpisywać pliki w Twoim vaultcie.

Jeśli nie ustawisz `VAULT_HOST_PATH`, domyślnie użyte będzie lokalne `./vaults`.

Snapshoty i baza SQLite trzymane są w `./var`, więc dane przetrwają restart kontenerów.

Tryb developerski z automatyczną synchronizacją zmian:

```bash
docker compose up --build
docker compose watch
```

`web` używa `sync`, bo Django `runserver` sam przeładuje kod. `scheduler` używa `sync+restart`, bo to długowieczny worker bez autoreloadu.

## Struktura domeny

- `Vault`: źródło danych i polityka backupów
- `BackupSnapshot`: pojedynczy snapshot vaulta
- `VaultDocument`: aktualny stan pliku w systemie
- `DocumentRevision`: kolejne rewizje pliku, z miejscem na diff i metadane

## Bezpieczenstwo

- Przy `DJANGO_DEBUG=false` wlaczane sa bezpieczne cookie dla sesji i CSRF.
- Dla aplikacji produkcyjnej warto ustawic osobna baze danych i reverse proxy z HTTPS.

## Contributing

1. Zrob fork albo branch roboczy.
2. Trzymaj sekrety i lokalne dane poza repo, tylko w `.env` oraz `var/`.
3. Przed commitem uruchom przynajmniej `python -m compileall config backups` i podstawowy smoke test w Dockerze.
4. Przy zmianach w modelach dodawaj migracje razem z kodem.

## Licencja

Projekt jest udostepniony na licencji MIT. Szczegoly sa w [LICENSE](LICENSE).
