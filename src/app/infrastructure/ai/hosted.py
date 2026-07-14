"""Hosted backend — Replicate-style prediction API skeleton (create → poll → download).

The actual models run on the provider's infrastructure, so this module needs no
heavy ML dependencies. Wire it up by setting AI_BACKEND=hosted plus the
PROVIDER_* / *_MODEL_REF environment variables.
"""

from __future__ import annotations

import asyncio
import base64
import secrets
import time
from typing import Any

import httpx

from app.domain.exceptions import DomainError

_POLL_INTERVAL_SECONDS = 2.0
_TERMINAL_STATUSES = {"succeeded", "failed", "canceled"}


def _as_data_uri(image: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(image).decode()


class HostedPredictionClient:
    """Minimal async client for a Replicate-style API: POST /predictions, poll until
    terminal status, then download the output artifact."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_ref: str,
        timeout_seconds: int = 180,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_ref = model_ref
        self._timeout = timeout_seconds

    @property
    def model_ref(self) -> str:
        return self._model_ref

    async def run(self, input_payload: dict[str, Any]) -> bytes:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            prediction = await self._create_prediction(client, input_payload)
            output_url = await self._poll_until_done(client, prediction)
            return await self._download_output(client, output_url)

    async def _create_prediction(
        self, client: httpx.AsyncClient, input_payload: dict[str, Any]
    ) -> dict[str, Any]:
        # Tres formas de referenciar el modelo en Replicate:
        #   "owner/name:version" -> /predictions con {"version": hash} (modelos comunidad)
        #   "owner/name"         -> /models/{owner}/{name}/predictions (modelos oficiales)
        #   hash de version      -> /predictions con {"version": hash}
        if ":" in self._model_ref:
            version = self._model_ref.split(":", 1)[1]
            url = f"{self._base_url}/predictions"
            body: dict[str, Any] = {"version": version, "input": input_payload}
        elif "/" in self._model_ref:
            url = f"{self._base_url}/models/{self._model_ref}/predictions"
            body = {"input": input_payload}
        else:
            url = f"{self._base_url}/predictions"
            body = {"version": self._model_ref, "input": input_payload}

        response = await client.post(url, json=body)
        if response.status_code == 402:
            raise DomainError(
                "Provider requires billing/credit (HTTP 402)", "RATE_LIMITED"
            )
        if response.status_code == 429:
            raise DomainError("Provider rate limit (HTTP 429)", "RATE_LIMITED")
        if response.status_code not in (200, 201):
            raise DomainError(
                f"Provider rejected prediction (HTTP {response.status_code}): "
                f"{response.text[:200]}",
                "PROVIDER_ERROR",
            )
        return response.json()

    async def _poll_until_done(self, client: httpx.AsyncClient, prediction: dict[str, Any]) -> str:
        poll_url = prediction.get("urls", {}).get("get") or (
            f"{self._base_url}/predictions/{prediction.get('id', '')}"
        )
        deadline = time.monotonic() + self._timeout

        status = prediction.get("status", "")
        while status not in _TERMINAL_STATUSES:
            if time.monotonic() >= deadline:
                raise DomainError("Provider prediction timed out", "PROVIDER_TIMEOUT")
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            response = await client.get(poll_url)
            if response.status_code != 200:
                raise DomainError(
                    f"Provider poll failed (HTTP {response.status_code})", "PROVIDER_ERROR"
                )
            prediction = response.json()
            status = prediction.get("status", "")

        if status != "succeeded":
            raise DomainError(f"Provider prediction ended as '{status}'", "PROVIDER_FAILED")

        output = prediction.get("output")
        url = output[0] if isinstance(output, list) and output else output
        if not isinstance(url, str):
            raise DomainError("Provider returned no downloadable output", "PROVIDER_BAD_OUTPUT")
        return url

    async def _download_output(self, client: httpx.AsyncClient, url: str) -> bytes:
        response = await client.get(url)
        if response.status_code != 200:
            raise DomainError(
                f"Could not download provider output (HTTP {response.status_code})",
                "PROVIDER_ERROR",
            )
        return response.content


class HostedAvatarModel:
    """Identity-preserving avatar generation on a hosted provider.

    TODO: point AVATAR_MODEL_REF to the chosen model version (InstantID or
    PhotoMaker on Replicate) and map its exact input schema in ``generate``.
    """

    def __init__(self, *, client: HostedPredictionClient) -> None:
        self._client = client

    async def generate(self, *, source_image: bytes, params: dict[str, Any]) -> bytes:
        # TODO: rename keys to match the final model input schema.
        payload: dict[str, Any] = {"image": _as_data_uri(source_image), **params}
        return await self._client.run(payload)


# IDM-VTON usa nombres de categoria propios
_IDM_VTON_CATEGORIES = {
    "upper_body": "upper_body",
    "lower_body": "lower_body",
    "dress": "dresses",
}

_GARMENT_DESCRIPTIONS = {
    "upper_body": "upper body garment (shirt, t-shirt, blouse or jacket)",
    "lower_body": "lower body garment (pants, jeans, shorts or skirt)",
    "dress": "full body dress",
}


class HostedTryOnModel:
    """Garment try-on on a hosted provider (Replicate).

    Modelos soportados via TRYON_MODEL_REF:
      - "kwai-kolors/kolors-virtual-try-on"  (Kolors — inputs human_img/garment_img)
      - cualquier ref que contenga "idm-vton" (IDM-VTON — inputs human_img/garm_img
        + category explicita, mejor para prendas lower_body)
    """

    def __init__(self, *, client: HostedPredictionClient) -> None:
        self._client = client

    async def generate(
        self,
        *,
        person_image: bytes,
        garment_image: bytes,
        garment_type: str,
        params: dict[str, Any],
        extra_garment_image: bytes | None = None,
        extra_garment_type: str | None = None,
    ) -> bytes:
        if extra_garment_image is not None:
            raise DomainError(
                "El outfit en una llamada solo está soportado por el backend gemini",
                "OUTFIT_NOT_SUPPORTED",
            )
        ref = self._client.model_ref.lower()
        if "idm-vton" in ref:
            category = _IDM_VTON_CATEGORIES.get(garment_type, "upper_body")
            payload: dict[str, Any] = {
                "human_img": _as_data_uri(person_image),
                "garm_img": _as_data_uri(garment_image),
                "category": category,
                # La version base de IDM-VTON es de torso: pantalones y
                # vestidos requieren la version DressCode del modelo
                "force_dc": category in ("lower_body", "dresses"),
                "garment_des": _GARMENT_DESCRIPTIONS.get(garment_type, "garment"),
                # crop=True: sin esto, fotos que no son 3:4 se deforman
                # (cabeza/cuerpo estirados)
                "crop": True,
                # mas pasos = mejor detalle en brazos/manos
                "steps": 40,
                # seed aleatoria: el default fijo (42) repite los mismos
                # artefactos en cada reintento
                "seed": secrets.randbelow(2**31),
                **params,
            }
        else:
            # Kolors Virtual Try-On (default)
            payload = {
                "human_img": _as_data_uri(person_image),
                "garment_img": _as_data_uri(garment_image),
                **params,
            }
        return await self._client.run(payload)
