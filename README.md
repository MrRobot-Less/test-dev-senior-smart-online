## Uso local

```bash
cp .env.example .env
uv sync
uv run playwright install chromium
uv run pytest
uv run python -m smart_online_automation
```

O mesmo comando também está disponível como script instalável:

```bash
uv run smart-online-automation
```

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

Para inspecionar o banco após a execução:

```bash
docker compose exec db psql -U automation -d automation -c "select * from automation_runs;"
```