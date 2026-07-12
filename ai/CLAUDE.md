# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ZAFIRA-IA is an internal **FastAPI** microservice (not Django, despite the parent
directory path) for avatar generation and virtual try-on. It is consumed **only** by
ZAFIRA-CORE (Django/Celery) over signed internal HTTP — never exposed to the public or
the mobile app. It is **stateless**: no database; all job/avatar/try-on state lives in
ZAFIRA-CORE. The request flow:

```
ZAFIRA-CORE → ZAFIRA-IA: download image from a (trusted) URL → run AI model → upload result to S3/MinIO → return the object key
```

## Commands

```bash
make install   # poetry install
make dev       # uvicorn on port 8002 (CORE=8000, aether=8001) with --reload
make lint      # ruff format . && ruff check .
make test      # pytest (config in pyproject.toml: coverage on, fail-under 30, warnings-as-errors)
```

Run a single test: `poetry run pytest tests/test_avatar.py::test_name`.
`pytest` auto-discovers `src` on the path and runs async tests automatically
(`asyncio_mode = auto`). Tests force `AI_BACKEND=stub` and fake HMAC creds via
`tests/conftest.py`, so they need no network, GPU, or MinIO.

## Architecture (layered, dependency-inverted)

`src/app/` follows strict layering — outer layers depend inward only:

- **domain/** — `DomainError(message, code)` only. Zero external deps.
- **application/** — use cases (`avatar/generate.py`, `tryon/generate.py`) + DTOs. Use
  cases orchestrate `fetcher → model → storage` and know nothing about HTTP or boto3.
- **infrastructure/** — concrete adapters behind `Protocol` interfaces:
  `ai/base.py` (Protocols) with `stub.py`/`hosted.py` implementations, `http/image_fetcher.py`,
  `storage/{base,s3_client}.py`, `security/hmac_verifier.py` (no FastAPI imports).
- **interfaces/** — FastAPI routers (`api/v1/`), `dependencies.py` (the composition root /
  factories), `security/hmac_auth.py` (the `Depends`), `main.py` (`create_app`).

Use cases receive `fetcher`, `model`, and `storage` as Protocols, so backends swap
without touching logic. **`interfaces/dependencies.py` is the only place that wires
concrete classes to interfaces** — add new backends there. AI model factories are
`@lru_cache`d and pick stub vs. hosted from `settings.ai_backend`.

## Key conventions & gotchas

- **Auth desconectada (temporal)**: los routers `/api/v1/*` NO exigen autenticación;
  ZAFIRA-CORE llama directo por localhost. El verificador HMAC sigue disponible en
  `infrastructure/security/hmac_verifier.py` + `interfaces/security/hmac_auth.py`
  (dormant, sin cablear). Para reactivarlo: volver a agregar
  `dependencies=[Depends(verify_hmac_request)]` en los routers y el fail-fast de
  `load_allowed_clients` en el lifespan de `main.py`.
- **Error handling**: raise `DomainError(msg, code)` from any layer. The handler in
  `main.py` converts it to HTTP `422` with `{"detail", "code"}`. Don't raise `HTTPException`
  from use cases or infrastructure.
- **AI backends**: `stub` (default) is passthrough — returns the input image unchanged,
  exercising the full fetch→model→upload pipeline. `hosted` is a Replicate-style skeleton;
  wiring a real model means filling the `TODO`s in `infrastructure/ai/hosted.py` (input
  schema mapping) and setting `PROVIDER_*` + `*_MODEL_REF` env vars.
- **Output keys** assume PNG (`avatars/<external_ref>.png`, `tryons/<external_ref>.png`);
  in stub mode the extension is nominal (bytes are whatever was downloaded).
- **No SSRF denylist** in `image_fetcher.py` — it trusts that ZAFIRA-CORE is the only
  caller and the only URL source (presigned storage URLs). It does guard content-type
  (`image/*`), HTTP status, and a 15 MB streamed size cap. If CORE ever forwards
  user-derived URLs, add scheme/destination validation here.
- **Config**: all settings in `config.py` via pydantic-settings, read from env /
  `.env` (see `.env.example`), accessed through the `@lru_cache`d `get_settings()`.

## Lint/format

Ruff, line-length 100, double quotes, `E501` ignored, `B008` ignored under
`interfaces/**` (FastAPI `Depends()` in defaults). Run `make lint` before committing.
