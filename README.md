# ZAFIRA-IA

> Microservicio interno de IA para la plataforma ZAFIRA: genera avatares semi-realistas a partir de una foto y hace try-on virtual de prendas sobre el avatar.

**ZAFIRA-IA** es consumido **exclusivamente** por el backend Django (ZAFIRA-CORE) vía HTTP interno firmado con HMAC. Nunca se expone a la app móvil ni al público.

```
App móvil  →  ZAFIRA-CORE (Django)  →  Celery  →  ZAFIRA-IA (FastAPI)  →  Modelos IA + Object Storage
                                                        │
                                                        ├── Backend stub (passthrough, default)
                                                        ├── Backend hosted (API estilo Replicate)
                                                        └── S3 / MinIO (bucket zafira-media)
```

ZAFIRA-CORE sube la foto del usuario al storage, encola una tarea Celery y esa tarea llama a ZAFIRA-IA con una URL (pública o presignada) de la imagen. ZAFIRA-IA descarga la imagen, ejecuta el modelo configurado, persiste el resultado en el bucket compartido y devuelve la *key* del objeto generado.

---

## 🧱 Stack

| Capa | Tecnología |
|------|-----------|
| Framework | FastAPI + uvicorn |
| Validación | Pydantic v2 |
| Auth | HMAC-SHA256 (X-CLIENT-ID / X-TIMESTAMP / X-SIGNATURE) |
| Storage | boto3 (S3 / MinIO) |
| HTTP saliente | httpx |
| Linting | Ruff |
| Tests | pytest + pytest-cov |

Sin base de datos: el servicio es **stateless** en el MVP. El estado (avatares, try-ons, jobs) vive en ZAFIRA-CORE.

---

## 🏗️ Arquitectura por capas

Calco de la arquitectura de `aether`:

```
src/app/
├── domain/           ← Excepciones de dominio (cero dependencias externas)
├── application/      ← Use cases + DTOs (orquestan, no conocen HTTP ni boto3)
│   ├── dto/                avatar.py, tryon.py, health.py
│   └── use_cases/          avatar/generate.py, tryon/generate.py
├── infrastructure/   ← Adaptadores concretos
│   ├── ai/                 base.py (Protocols), stub.py, hosted.py
│   ├── http/               image_fetcher.py (descarga con guardas)
│   ├── storage/            base.py (Protocol), s3_client.py (boto3)
│   └── security/           hmac_verifier.py (sin imports de FastAPI)
└── interfaces/       ← Rutas HTTP, dependencias, seguridad
    ├── api/v1/             avatar/router.py, tryon/router.py
    ├── security/           hmac_auth.py (Depends), openapi.py
    ├── dependencies.py     factories (settings, fetcher, storage, modelos)
    └── health.py
```

Los use cases reciben `fetcher`, `model` y `storage` como interfaces (`Protocol`), por lo que los backends son intercambiables sin tocar la lógica.

---

## 🔌 Endpoints

| Endpoint | Auth | Descripción |
|----------|------|-------------|
| `GET /` | ❌ | Metadata del servicio |
| `GET /health` | ❌ | Liveness/readiness probe |
| `POST /api/v1/avatar` | HMAC ✅ | Genera avatar desde una foto |
| `POST /api/v1/tryon` | HMAC ✅ | Try-on virtual de una prenda |

### `POST /api/v1/avatar`

Request:

```json
{
  "external_ref": "9f4e2c1a-7b3d-4f6a-9c1e-2d8b5a0f3e7c",
  "source_image_url": "https://media.zafira.app/uploads/selfie.jpg",
  "params": {}
}
```

Response `200`:

```json
{
  "external_ref": "9f4e2c1a-7b3d-4f6a-9c1e-2d8b5a0f3e7c",
  "avatar_image_key": "avatars/9f4e2c1a-7b3d-4f6a-9c1e-2d8b5a0f3e7c.png",
  "meta": {"model": "StubAvatarModel", "size_bytes": 482133}
}
```

### `POST /api/v1/tryon`

Request:

```json
{
  "external_ref": "5b2d8e0c-1f4a-4c7b-8d3e-9a6f2c5e1b4d",
  "person_image_url": "https://media.zafira.app/avatars/user-1.png",
  "garment_image_url": "https://media.zafira.app/products/jacket-77.jpg",
  "garment_type": "upper_body",
  "params": {}
}
```

`garment_type` ∈ `upper_body` | `lower_body` | `dress`.

Response `200`:

```json
{
  "external_ref": "5b2d8e0c-1f4a-4c7b-8d3e-9a6f2c5e1b4d",
  "result_image_key": "tryons/5b2d8e0c-1f4a-4c7b-8d3e-9a6f2c5e1b4d.png",
  "meta": {"model": "StubTryOnModel", "size_bytes": 391024}
}
```

Errores de dominio (descarga fallida, content-type no imagen, proveedor caído) responden `422` con `{"detail": "...", "code": "IMAGE_FETCH_ERROR" | "PROVIDER_TIMEOUT" | ...}`.

---

## 🔐 Autenticación HMAC

Todos los endpoints `/api/v1/*` exigen tres headers:

| Header | Descripción |
|--------|-------------|
| `X-CLIENT-ID` | Identificador registrado en `HMAC_ALLOWED_CLIENTS` (ej. `zafira-core`) |
| `X-TIMESTAMP` | Epoch Unix en segundos (ventana de ±`HMAC_CLOCK_SKEW_SECONDS`) |
| `X-SIGNATURE` | `hex(HMAC-SHA256(body_utf8 + timestamp, secret))` |

La comparación de firmas es *constant-time* (`hmac.compare_digest`). Ejemplo de firma desde Python (así lo hace la tarea Celery en ZAFIRA-CORE):

```python
import hashlib, hmac, json, time
import httpx

CLIENT_ID = "zafira-core"
SECRET = "change-me-in-production"

body = json.dumps({
    "external_ref": "9f4e2c1a-7b3d-4f6a-9c1e-2d8b5a0f3e7c",
    "source_image_url": "https://media.zafira.app/uploads/selfie.jpg",
    "params": {},
}).encode()

timestamp = str(int(time.time()))
signature = hmac.new(SECRET.encode(), (body.decode() + timestamp).encode(), hashlib.sha256).hexdigest()

response = httpx.post(
    "http://zafira-ia:8000/api/v1/avatar",
    content=body,
    headers={
        "Content-Type": "application/json",
        "X-CLIENT-ID": CLIENT_ID,
        "X-TIMESTAMP": timestamp,
        "X-SIGNATURE": signature,
    },
)
```

> Importante: firmar exactamente los **bytes crudos** del body que se envían — cualquier re-serialización JSON invalida la firma.

Si `HMAC_ALLOWED_CLIENTS` no está configurada, el servicio **se niega a arrancar** (fail-fast en el lifespan); no existe ningún cliente/secret por defecto.

### 🛡️ Supuesto de confianza sobre las URLs

ZAFIRA-IA descarga las imágenes de las URLs que recibe (`source_image_url`, `person_image_url`, `garment_image_url`) **confiando en que el único caller es ZAFIRA-CORE**, que las genera él mismo (presigned URLs de su storage). No hay denylist SSRF — en local las URLs de MinIO son loopback, así que bloquear rangos privados rompería dev. Si algún día ZAFIRA-CORE propaga URLs derivadas de input de usuario sin validar, este servicio se convertiría en un proxy hacia la red interna: en ese momento hay que añadir validación de esquema/destino aquí.

---

## ⚙️ Variables de entorno

| Variable | Requerida | Descripción |
|----------|-----------|-------------|
| `HMAC_ALLOWED_CLIENTS` | ✅ | JSON `{"client_id": "secret"}` |
| `HMAC_CLOCK_SKEW_SECONDS` | ➖ | Ventana de reloj (default: 60) |
| `AI_BACKEND` | ➖ | `stub` (default) \| `hosted` |
| `PROVIDER_BASE_URL` | hosted | Base URL del proveedor (ej. `https://api.replicate.com/v1`) |
| `PROVIDER_API_KEY` | hosted | API key del proveedor |
| `AVATAR_MODEL_REF` | hosted | Versión del modelo de avatar |
| `TRYON_MODEL_REF` | hosted | Versión del modelo de try-on |
| `PROVIDER_TIMEOUT_SECONDS` | ➖ | Timeout total de la predicción (default: 180) |
| `STORAGE_ENDPOINT_URL` | ➖ | Endpoint S3/MinIO (vacío = AWS S3) |
| `STORAGE_ACCESS_KEY` | ✅ | Access key del storage |
| `STORAGE_SECRET_KEY` | ✅ | Secret key del storage |
| `STORAGE_BUCKET` | ➖ | Bucket destino (default: `zafira-media`) |
| `STORAGE_REGION` | ➖ | Región del storage |
| `API_DOCS_ENABLED` | ➖ | Habilita `/docs` y `/redoc` (default: true) |

---

## 🚀 Cómo correr

### 📋 Prerrequisitos

| Herramienta | Versión | Para qué |
|-------------|---------|----------|
| 🐍 Python | **3.12.x** (ver `.python-version` → `3.12.11`) | Runtime |
| 📦 Poetry | ≥ 2.0 | Gestión de dependencias y del entorno virtual |
| 🔧 pyenv | (opcional, recomendado) | Fijar la versión exacta de Python |

> ⚠️ **Un solo entorno virtual: el `.venv/` que crea Poetry.** Por `poetry.toml`
> (`in-project = true`) el venv vive **dentro del proyecto** (`.venv/`), construido sobre
> el Python **3.12.11** que aporta pyenv. **No crees un pyenv-virtualenv aparte** (tipo
> `pyenv virtualenv ... zafira-ia`): sería redundante, y si nace de un Python 3.11 Poetry
> lo rechazará (`Current Python version ... is not allowed by the project (^3.12)`).
> El rol de cada pieza:
> - **pyenv** → solo provee el Python 3.12.11 base (una *versión*, no un virtualenv).
> - **`.python-version`** → fija ese 3.12.11 al entrar a la carpeta.
> - **Poetry** → crea y administra `.venv/`. Es tu único entorno. ✅

### 1️⃣ Instalación (común a WSL y Windows)

```bash
# Asegurar Python 3.12 (con pyenv)
pyenv install 3.12.11   # solo si no lo tienes aún
pyenv local 3.12.11     # escribe/respeta .python-version en la carpeta

# Instalar dependencias → crea .venv/ dentro del proyecto
make install            # equivale a: poetry install

# Configurar entorno (variables)
cp .env.example .env    # 🪟 Windows PowerShell: Copy-Item .env.example .env

# Verificar que todo arranca
make test               # ✅ 18 tests, sin red ni MinIO (usan fakes)
make dev                # 🌐 servidor de desarrollo en http://127.0.0.1:8002
```

> 💡 Si tu prompt muestra otro entorno (p.ej. `(zafira-ia)`) ejecuta `pyenv deactivate`
> y abre una terminal nueva: debe quedar `py 3.12.11`, no un virtualenv 3.11.

### 🐧 WSL (Ubuntu sobre Windows) — recomendado

```bash
# Toolchain de Python (si NO usas pyenv)
sudo apt update && sudo apt install -y python3.12 python3.12-venv pipx
pipx install poetry

# Dentro del repo (ver nota de filesystem abajo)
make install
cp .env.example .env
make dev    # 🌐 http://127.0.0.1:8002
```

> 📂 **Trabaja en el filesystem nativo de WSL** (`~/Project_development/...`), **nunca bajo
> `/mnt/c/...`**: el I/O de Poetry y pytest es mucho más rápido y evitas problemas de permisos.

Comprobar que responde:

```bash
curl http://127.0.0.1:8002/health   # → {"status":"ok","version":"0.1.0"}
# 📖 Docs interactivas (API_DOCS_ENABLED=true): http://127.0.0.1:8002/docs
```

### 🪟 Windows nativo (PowerShell)

```powershell
# Instalar Python 3.12 (winget) y Poetry
winget install Python.Python.3.12
py -3.12 -m pip install --user pipx
py -3.12 -m pipx ensurepath
pipx install poetry

# Reabre la terminal para refrescar el PATH, luego en el repo:
poetry install
Copy-Item .env.example .env
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8002
```

> ⚠️ `make` no viene con Windows. Usa los comandos `poetry run ...` directamente, o instala
> `make` (`winget install GnuWin32.Make` / `choco install make`). Los targets viven en el
> `Makefile`: `dev`, `lint`, `test`.

### 🧠 Configuración en PyCharm

#### 🎯 Paso clave: seleccionar el intérprete (el `.venv` de Poetry)

El objetivo es que PyCharm use **el `.venv/` del proyecto** (Python 3.12.11), **no** un
pyenv-virtualenv ni un Python global. Como el venv es in-project, basta con apuntarlo.

**🐧 Si trabajas en WSL (PyCharm Professional):**

1. 📂 **Abre el proyecto desde WSL** — `File → Remote Development → WSL`, o abre la ruta
   `\\wsl$\Ubuntu\home\<usuario>\Project_development\Django\ZAFIRA-IA`. Edita siempre la
   copia en WSL, no una en `C:\`.
2. ⚙️ Ve a `File → Settings → Project: ZAFIRA-IA → Python Interpreter`.
3. ➕ Pulsa **Add Interpreter → On WSL**. Elige tu distro (Ubuntu) y espera a que conecte.
4. 🔌 Selecciona **Poetry Environment → Existing** y en *Interpreter* pon la ruta:
   ```
   /home/<usuario>/Project_development/Django/ZAFIRA-IA/.venv/bin/python
   ```
   (Si eliges *New environment* con el ejecutable de Poetry, PyCharm reusará igualmente el
   `.venv` in-project porque así está configurado en `poetry.toml`.)
5. ✅ Acepta. Abajo a la derecha debe aparecer **Python 3.12 (zafira-ia) [.venv]**.

**🪟 Si trabajas en Windows nativo:**

1. ⚙️ `File → Settings → Project → Python Interpreter → Add Interpreter → Add Local Interpreter`.
2. 🔌 Pestaña **Poetry Environment → Existing environment** y apunta a:
   ```
   <ruta-del-proyecto>\.venv\Scripts\python.exe
   ```
3. ✅ Acepta y confirma que PyCharm muestra ese intérprete del `.venv`.

> 🚫 **Nunca** selecciones `~/.pyenv/versions/zafira-ia/...` ni un Python del sistema:
> solo el `.venv` del proyecto garantiza Python 3.12.11 y las dependencias correctas.

#### ▶️ Run Configuration para el servidor (uvicorn)

`Run → Edit Configurations… → ➕ → Python`:

| Campo | Valor |
|-------|-------|
| **Name** | `dev (uvicorn)` |
| ⚪ **Module name** (no *Script path*) | `uvicorn` |
| **Parameters** | `app.main:app --reload --host 0.0.0.0 --port 8002` |
| **Working directory** | la raíz del proyecto |
| **Python interpreter** | el `.venv` configurado arriba |
| **Environment variables** | añade `PYTHONPATH=src` 👇 |

> 🔑 `PYTHONPATH=src` es **obligatorio**: el paquete `app` vive bajo `src/`, así que sin
> esto uvicorn no encuentra `app.main`. Para cargar el `.env` instala el plugin **EnvFile**
> y márcalo en la pestaña *EnvFile*, o copia las variables en *Environment variables*.

Pulsa ▶️ y abre http://127.0.0.1:8002/docs.

#### 🧪 Tests y 🧹 Ruff

- **pytest**: `Settings → Tools → Python Integrated Tools → Testing → Default test runner: pytest`.
  Luego click derecho sobre `tests/` → *Run*. La config (cobertura, asyncio) vive en `pyproject.toml`.
- **Ruff**: instala el plugin *Ruff* y apúntalo a `.venv/bin/ruff` (o `.venv\Scripts\ruff.exe`)
  para formatear y lintar al guardar.

> ℹ️ **Nota:** el proyecto está bajo una carpeta `Django/` por convención del repositorio
> padre, **pero es un servicio FastAPI**. No configures un "Django Server" en PyCharm —
> usa la Run Configuration de uvicorn de arriba.

### 🐳 Docker

```bash
# Producción (multi-stage, non-root, puerto 8000 interno)
docker build -t zafira-ia:local .

# Desarrollo (hot reload, .env montado)
docker build -f DockerfileEnv -t zafira-ia-dev:local .
docker run --rm -p 8002:8000 --env-file .env zafira-ia-dev:local
```

---

## 🤖 Backends de IA

### `stub` (default)

Modelos *passthrough*: devuelven la imagen de entrada tal cual. Validan el pipeline completo (descarga → modelo → upload al storage) sin GPU ni red de proveedor. Es el backend para desarrollo local, CI y para integrar ZAFIRA-CORE end-to-end antes de pagar inferencia real.

> Nota: las keys de salida (`avatars/<external_ref>.png`, `tryons/<external_ref>.png`) asumen que el modelo produce PNG, como harán las implementaciones reales. En modo stub la extensión es nominal: si la imagen de entrada era JPEG, los bytes guardados siguen siendo JPEG.

### `hosted`

Esqueleto httpx contra una API de predicciones estilo Replicate: crea la predicción (`POST /predictions`), hace *polling* hasta estado terminal (con timeout) y descarga el output. Para activarlo:

1. `AI_BACKEND=hosted` + `PROVIDER_BASE_URL` + `PROVIDER_API_KEY`.
2. **Avatar** — apuntar `AVATAR_MODEL_REF` a la versión del modelo elegido (**InstantID** o **PhotoMaker** en Replicate) y mapear su *input schema* en `HostedAvatarModel.generate` (`src/app/infrastructure/ai/hosted.py` — los `TODO` marcan los puntos exactos).
3. **Try-on** — lo mismo con `TRYON_MODEL_REF` (**CatVTON** o **IDM-VTON**) en `HostedTryOnModel.generate` (típicamente las keys `person_image`/`garment_image`/`category` cambian de nombre según el modelo).

Como los modelos corren en la infraestructura del proveedor, este servicio no necesita librerías ML pesadas ni GPU.

---

## 🗺️ Roadmap — Fase 2

- **Modo jobs asíncrono**: `POST /api/v1/avatar/jobs` devuelve `202` + `job_id` inmediato; la generación corre en background y ZAFIRA-IA hace `POST` al webhook de ZAFIRA-CORE firmado con HMAC (mismo patrón `BACKOFFICE_*` de aether). Necesario cuando la inferencia real supere los timeouts HTTP razonables.
- Endpoint de *polling* `GET /api/v1/.../jobs/{job_id}` como fallback si el callback se pierde.
- Idempotencia por `external_ref` (requiere persistencia ligera de jobs).
