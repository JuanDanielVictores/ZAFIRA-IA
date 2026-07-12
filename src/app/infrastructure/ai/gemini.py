"""Gemini image backend — try-on/avatar composites via Gemini 2.5 Flash Image.

Plain REST over httpx (models/{model}:generateContent with inline images);
no extra SDK dependency. Wire it up with AI_BACKEND=gemini + GEMINI_API_KEY.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from app.domain.exceptions import DomainError

TRYON_PROMPT_TEMPLATE = (
    "Virtual try-on task with two input images.\n"
    "IMAGE 1 is the ONLY real person. It is the sole source of identity. You must "
    "keep this person's face, facial features, facial structure, skin tone, hair, "
    "eyes, expression, body and background EXACTLY as they are — pixel-faithful. "
    "Never alter, beautify, swap, blend or regenerate the face or head of IMAGE 1.\n"
    "IMAGE 2 is a {garment_label} garment product photo. Use it ONLY as a clothing "
    "reference: extract the {garment_label} garment and nothing else. If IMAGE 2 "
    "shows a model, mannequin, face, head, hands or any other person, completely "
    "ignore and discard them — do NOT transfer any facial features, skin or body "
    "from IMAGE 2 onto the result.\n"
    "If IMAGE 2 shows the model wearing SEVERAL layered garments (for example a "
    "jacket or coat over a shirt or t-shirt), the target garment is the "
    "OUTERMOST, TOP layer (the jacket/coat) — extract that one and IGNORE any "
    "inner shirt, t-shirt or top visible underneath it.\n"
    "Output: the person from IMAGE 1, unchanged, now wearing the extracted "
    "{garment_label} garment INSTEAD OF their current {garment_label} clothing. "
    "CRITICAL: first completely REMOVE the person's original {garment_label} "
    "clothing, then dress them with the new garment. The original garment must "
    "NOT remain visible under, over or behind the new one — no layering, no "
    "stacking. If the new garment covers less skin than the original (e.g. "
    "shorts replacing long pants, or a t-shirt replacing a jacket), render the "
    "newly exposed skin naturally: the old garment must be FULLY gone, with no "
    "cuffs, hems, waistband, sleeves or fabric of the original peeking out "
    "below, above or beside the new one. Replace ONLY the {garment_label} "
    "clothing. ALL other clothing the person wears (shirts, pants, shoes, "
    "accessories) must remain EXACTLY as in IMAGE 1 — same fit, same color, "
    "same shape, pixel-faithful, with no restyling or redesign whatsoever.\n"
    "FOOTWEAR & ACCESSORIES: never add, remove, swap, recolor or restyle the "
    "person's shoes, socks, hat, cap, bag, belt, watch, glasses or any "
    "accessory — keep them EXACTLY as in IMAGE 1. If IMAGE 2 shows the garment "
    "on a model wearing shoes or accessories, IGNORE those completely and do "
    "NOT copy them onto the person. Do not invent footwear or accessories that "
    "are not already present in IMAGE 1.\n"
    "MANDATORY: the new {garment_label} garment from IMAGE 2 MUST be clearly "
    "and visibly worn by the person in the output. Returning IMAGE 1 "
    "unchanged, or with the person still wearing their original "
    "{garment_label} clothing, is an INCORRECT result — the garment swap must "
    "always happen. This applies EVEN IF the new garment is the same kind of "
    "clothing OR the same color as what the person already wears (e.g. "
    "swapping jeans for different jeans, or putting a white shirt over an "
    "existing white shirt): you must still perform the replacement and "
    "accurately reproduce the exact color, wash, cut, collar, neckline, "
    "sleeve length, fit and fabric details of the garment in IMAGE 2, not "
    "keep the original one. When the current and new garments look similar "
    "(same colour or same type), pay special attention to the differences in "
    "cut, collar and sleeve length so that the swap is clearly visible in the "
    "output. Return only the final image."
)

AVATAR_PROMPT = (
    "Generate a clean, semi-realistic avatar portrait of the person in the image. "
    "Preserve identity and facial features. Neutral studio background. "
    "Return only the final image."
)

_GARMENT_LABELS = {
    "upper_body": "upper-body",
    "lower_body": "lower-body",
    "dress": "full-body dress",
}


def _detect_mime(image: bytes) -> str:
    if image.startswith(b"\x89PNG"):
        return "image/png"
    if image.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if image[:16].find(b"WEBP") != -1:
        return "image/webp"
    return "image/jpeg"


class GeminiImageClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://generativelanguage.googleapis.com",
        timeout_seconds: int = 120,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport

    async def generate(
        self, *, prompt: str, images: list[bytes], temperature: float = 0.35
    ) -> bytes:
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for image in images:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": _detect_mime(image),
                        "data": base64.b64encode(image).decode(),
                    }
                }
            )

        url = f"{self._base_url}/v1beta/models/{self._model}:generateContent"
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            response = await client.post(
                url,
                json={
                    "contents": [{"parts": parts}],
                    # Temperatura media-baja: equilibrio entre fidelidad (no
                    # alterar prendas ajenas) y accion (no devolver la imagen
                    # sin aplicar la prenda nueva)
                    "generationConfig": {"temperature": temperature},
                },
                headers={"x-goog-api-key": self._api_key},
            )

        if response.status_code == 429:
            raise DomainError(
                "Gemini quota/rate limit exceeded (enable billing or retry later)",
                "RATE_LIMITED",
            )
        if response.status_code >= 500:
            raise DomainError(
                f"Gemini upstream error (HTTP {response.status_code})", "PROVIDER_UNAVAILABLE"
            )
        if response.status_code != 200:
            raise DomainError(
                f"Gemini rejected the request (HTTP {response.status_code})", "PROVIDER_ERROR"
            )
        return self._extract_image(response.json())

    @staticmethod
    def _extract_image(data: dict[str, Any]) -> bytes:
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                inline = part.get("inline_data") or part.get("inlineData") or {}
                if inline.get("data"):
                    return base64.b64decode(inline["data"])
        raise DomainError(
            "Gemini returned no image (safety block or text-only reply)", "GENERATION_REJECTED"
        )


def _mean_diff(a: bytes, b: bytes) -> float:
    """Diferencia media de pixeles (0-255) entre dos imagenes reducidas a
    64x64 gris. ~0 = practicamente identicas (la prenda no se aplico)."""
    from io import BytesIO

    from PIL import Image

    def thumb(data: bytes):
        return Image.open(BytesIO(data)).convert("L").resize((64, 64))

    try:
        ia, ib = thumb(a), thumb(b)
    except Exception:
        return 255.0  # si no se puede comparar, asumir que cambio (no reintentar)
    pa, pb = ia.load(), ib.load()
    total = sum(abs(pa[x, y] - pb[x, y]) for x in range(64) for y in range(64))
    return total / (64 * 64)


# Debajo de este umbral la salida es casi identica a la entrada: la prenda
# no se aplico (no-op) y conviene reintentar una vez.
_NOOP_DIFF_THRESHOLD = 3.0


class GeminiTryOnModel:
    def __init__(self, *, client: GeminiImageClient) -> None:
        self._client = client

    async def generate(
        self,
        *,
        person_image: bytes,
        garment_image: bytes,
        garment_type: str,
        params: dict[str, Any],
    ) -> bytes:
        label = _GARMENT_LABELS.get(garment_type, "upper-body")
        prompt = params.get("prompt")
        if not prompt:
            prompt = TRYON_PROMPT_TEMPLATE.format(garment_label=label)
            # Vestido / enterizo: sustituye TOP y BOTTOM a la vez. Sin esta
            # regla, el prompt asume que la persona ya lleva un vestido y
            # falla cuando lleva blusa + pantalón (Gemini no sabe qué quitar
            # y devuelve la foto sin cambios).
            if garment_type == "dress":
                prompt += (
                    f"\nSPECIAL RULE: the new {label} from IMAGE 2 is a "
                    f"one-piece garment that covers the full body. Remove "
                    f"the person's current upper clothing COMPLETELY — "
                    f"including the body, the collar/neckline, AND the "
                    f"sleeves (long, three-quarter or short) of their "
                    f"shirt, blouse, t-shirt, top, cardigan or sweater — "
                    f"AND their current lower clothing (pants, jeans, "
                    f"skirt, shorts) SIMULTANEOUSLY. Dress them entirely "
                    f"with the new {label}. CRITICAL: if the new {label} "
                    f"has thin straps, short sleeves or no sleeves, the "
                    f"person's arms, shoulders and neckline must appear as "
                    f"BARE SKIN in every part the new dress does not "
                    f"cover — NEVER as leftover sleeves, cuffs or collar "
                    f"from the old top (a common mistake is keeping long "
                    f"sleeves on the arms when the new dress is "
                    f"sleeveless: this is INCORRECT and must not happen). "
                    f"No trace of the original top or bottom must remain "
                    f"visible: no collar, no sleeves (short or long), no "
                    f"cuffs, no waistband, no hem or fabric of the old "
                    f"clothes peeking out anywhere. The final image must "
                    f"show ONLY the new {label} on the person, with bare "
                    f"skin wherever the dress does not reach."
                )
            # El nombre real de la prenda enfoca a Gemini en aplicarla y reduce
            # el no-op (devolver la foto sin cambios) y el aplicar la prenda
            # equivocada. Solo se agrega cuando ZAFIRA-CORE envia garment_des.
            garment_des = str(params.get("garment_des") or "").strip()
            if garment_des:
                prompt += (
                    f'\nThe specific {label} garment to apply, taken from IMAGE 2, '
                    f'is: "{garment_des}". Reproduce that exact garment on the person.'
                )

        result = await self._client.generate(
            prompt=prompt, images=[person_image, garment_image]
        )
        # Guardia anti no-op: si la prenda no se aplico (salida casi identica a
        # la foto de entrada), reintentar UNA vez con mas temperatura para
        # forzar un resultado distinto.
        base_diff = _mean_diff(result, person_image)
        if base_diff < _NOOP_DIFF_THRESHOLD:
            retry = await self._client.generate(
                prompt=prompt,
                images=[person_image, garment_image],
                temperature=0.7,
            )
            # Quedarse con el reintento solo si de verdad cambio algo mas
            if _mean_diff(retry, person_image) >= base_diff:
                result = retry
        return result


class GeminiAvatarModel:
    def __init__(self, *, client: GeminiImageClient) -> None:
        self._client = client

    async def generate(self, *, source_image: bytes, params: dict[str, Any]) -> bytes:
        prompt = params.get("prompt") or AVATAR_PROMPT
        return await self._client.generate(prompt=prompt, images=[source_image])
