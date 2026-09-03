# test-dev-senior-smart-online

## Uso local

```bash
cp .env.example .env
uv sync
uv run playwright install chromium
uv run pytest
uv run python -m test_dev_senior_smart_online
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