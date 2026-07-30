# ml

Python paket `photoassistant` (biblioteka) i `service/` (interni FastAPI servis).

Biblioteku uvoze i servis i offline pipeline (`pipeline/`), pa renderer, fitovanje
i embeddinzi postoje jednom.

## Dva načina instalacije

Zavisnosti su podeljene tako da granica iz protokola §4.4 bude činjenica, ne dogovor:

| Komanda | Šta dobija | Kome služi |
|---|---|---|
| `uv sync --project ml` | samo biblioteku (`pydantic`) | offline pipeline |
| `uv sync --project ml --extra service` | + FastAPI, uvicorn, pydantic-settings | servis i testovi |

`--extra service` se **mora navesti eksplicitno** — `uv` nema podešavanje kojim se extra
uključuje po podrazumevanom (`default-groups` postoji, ekvivalent za extras ne).

## Komande

Iz korena repoa:

```bash
uv sync --project ml --extra service
uv run --project ml --extra service pytest ml/tests
uv run --project ml --extra service ruff check ml
uv run --project ml --extra service uvicorn service.main:app --reload --port 8000
```

Health: `http://localhost:8000/health` · OpenAPI: `http://localhost:8000/docs`
