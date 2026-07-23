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
    "ROLE: You are an expert virtual try-on retoucher. Perform ONE precise "
    "garment swap on a real photo and return a single photorealistic image.\n\n"
    "INPUTS:\n"
    "- IMAGE 1: the real person. It is the ONLY source of identity and the base "
    "of the result.\n"
    "- IMAGE 2: a {garment_label} garment product photo, used ONLY as a clothing "
    "reference.\n\n"
    "GOAL: Show the exact person from IMAGE 1 now wearing the {garment_label} "
    "garment from IMAGE 2, IN PLACE OF their current {garment_label} clothing. "
    "The new garment must be clearly and visibly worn in the output.\n\n"
    "KEEP FROM IMAGE 1 — do not change:\n"
    "1. IDENTITY: face, facial features, facial structure, skin tone, hair, "
    "eyes, expression and the person's body shape and proportions — "
    "pixel-faithful. Never alter, beautify, swap, blend or regenerate the face "
    "or head.\n"
    "2. POSE, camera angle and BACKGROUND: exactly as in IMAGE 1.\n"
    "3. FRAMING: keep the SAME framing, composition, zoom and aspect ratio as "
    "IMAGE 1. If IMAGE 1 shows the person FULL-LENGTH (head to feet), the "
    "output MUST also show the FULL body from head to feet. Never crop, zoom "
    "in, re-center or cut off the head, legs, feet or shoes — the feet and "
    "footwear visible in IMAGE 1 must stay fully visible in the result.\n"
    "4. EVERYTHING NOT BEING REPLACED: all other clothing, plus the person's "
    "shoes, socks, hat, cap, bag, belt, watch, glasses and any accessory — keep "
    "EXACTLY as in IMAGE 1 (same fit, color and shape, pixel-faithful). Never "
    "add, remove, swap, recolor, restyle or invent any of them.\n\n"
    "EXTRACT FROM IMAGE 2 — the new garment only:\n"
    "1. Copy ONLY the {garment_label} garment: its exact color, fabric, "
    "pattern, cut, collar/neckline, sleeve length and fit.\n"
    "2. If IMAGE 2 shows a model, mannequin, face, head, hands, shoes or "
    "accessories, IGNORE and discard them completely — never transfer any face, "
    "skin, body, footwear or accessory from IMAGE 2 onto the result.\n"
    "3. If IMAGE 2 shows several layered garments (e.g. a jacket or coat over a "
    "shirt or t-shirt), the target is the OUTERMOST, TOP layer (the "
    "jacket/coat) — extract that one and ignore any inner top underneath.\n"
    "4. If IMAGE 2 shows the garment from the BACK or SIDE, use it only to "
    "learn color, fabric and design and infer its front realistically. The "
    "person keeps THEIR exact pose and camera angle — never mirror or copy the "
    "garment photo's orientation onto the person.\n\n"
    "REPLACE — do not layer:\n"
    "First COMPLETELY REMOVE the person's original {garment_label} clothing, "
    "including its collar, sleeves, cuffs, waistband and hems; then dress them "
    "in the new garment. No part of the original {garment_label} garment may "
    "remain visible under, over or beside the new one: no layering, no "
    "stacking, no leftover collar, sleeve, cuff, waistband or hem peeking out. "
    "Drawing the new garment ON TOP of the original one is a COMMON MISTAKE and "
    "is INCORRECT. If the new garment covers less skin than the original (e.g. "
    "shorts replacing long pants, or a t-shirt replacing a jacket), render the "
    "newly exposed skin naturally.\n\n"
    "MANDATORY OUTCOME:\n"
    "The garment swap MUST happen. Returning IMAGE 1 unchanged, or with the "
    "person still wearing their original {garment_label} clothing, is a "
    "FAILURE. This holds EVEN IF the new garment is the same type or color as "
    "what the person already wears (e.g. jeans for different jeans, or a white "
    "shirt over an existing white shirt): still perform the replacement and "
    "reproduce the new garment's exact color, wash, cut, collar, neckline, "
    "sleeve length, fit and fabric. When the old and new garments look similar, "
    "focus on their differences in cut, collar and sleeve length so the swap is "
    "clearly visible.\n"
    "Return only the final image."
)

# Outfit completo en UNA generación: tres imágenes (persona + torso + pierna).
# Hereda todas las reglas del prompt individual que arreglaron bugs reales:
# identidad pixel-fiel, ignorar al modelo de la tienda, remover lo original,
# no tocar calzado/accesorios y prohibido devolver la imagen sin cambios.
OUTFIT_PROMPT_TEMPLATE = (
    "ROLE: You are an expert virtual try-on retoucher. Perform TWO precise "
    "garment swaps on a real photo, at the same time, and return a single "
    "photorealistic image.\n\n"
    "INPUTS:\n"
    "- IMAGE 1: the real person. It is the ONLY source of identity and the base "
    "of the result.\n"
    "- IMAGE 2: a {garment_a} garment product photo. IMAGE 3: a {garment_b} "
    "garment product photo. Both are used ONLY as clothing references.\n\n"
    "GOAL: Show the exact person from IMAGE 1 now wearing BOTH new garments AT "
    "THE SAME TIME: the {garment_a} garment from IMAGE 2 IN PLACE OF their "
    "current {garment_a} clothing, and the {garment_b} garment from IMAGE 3 IN "
    "PLACE OF their current {garment_b} clothing. Both new garments must be "
    "clearly and visibly worn together in the output.\n\n"
    "KEEP FROM IMAGE 1 — do not change:\n"
    "1. IDENTITY: face, facial features, facial structure, skin tone, hair, "
    "eyes, expression and the person's body shape and proportions — "
    "pixel-faithful. Never alter, beautify, swap, blend or regenerate the face "
    "or head.\n"
    "2. POSE, camera angle and BACKGROUND: exactly as in IMAGE 1.\n"
    "3. FRAMING: keep the SAME framing, composition, zoom and aspect ratio as "
    "IMAGE 1. If IMAGE 1 shows the person FULL-LENGTH (head to feet), the "
    "output MUST also show the FULL body from head to feet. Never crop, zoom "
    "in, re-center or cut off the head, legs, feet or shoes.\n"
    "4. Shoes, socks, hat, cap, bag, belt, watch, glasses and any accessory: "
    "keep EXACTLY as in IMAGE 1. Never add, remove, swap, recolor or restyle "
    "them.\n\n"
    "EXTRACT FROM IMAGE 2 AND IMAGE 3 — the new garments only:\n"
    "1. Use each garment photo ONLY to copy that garment's exact color, fabric, "
    "pattern, cut, collar/neckline, sleeve length and fit.\n"
    "2. If IMAGE 2 or IMAGE 3 shows a model, mannequin, face, head, hands, "
    "shoes or accessories, IGNORE and discard them completely — never transfer "
    "any face, skin, body, footwear or accessory onto the result.\n"
    "3. If a garment photo shows several layered garments, the target is the "
    "OUTERMOST, TOP layer. If a garment photo shows the garment from the BACK "
    "or SIDE, use it only for color, fabric and design and infer its front "
    "realistically — the person keeps THEIR exact pose and camera angle.\n\n"
    "REPLACE — do not layer:\n"
    "First COMPLETELY REMOVE the person's original {garment_a} AND {garment_b} "
    "clothing — including collars, sleeves, cuffs, waistbands and hems — then "
    "dress them in the two new garments. No fabric of the original clothes may "
    "remain visible anywhere: no layering, no stacking, no leftover collar, "
    "sleeve, cuff, waistband or hem. Drawing a new garment ON TOP of the "
    "original one is INCORRECT. If a new garment covers less skin than the "
    "original, render the newly exposed skin naturally.\n\n"
    "MANDATORY OUTCOME:\n"
    "BOTH swaps MUST happen. Returning the person unchanged, or with only ONE "
    "of the two garments applied, is a FAILURE. This holds EVEN IF a new "
    "garment is the same type or color as what the person already wears: still "
    "perform BOTH replacements and reproduce each garment's exact color, cut, "
    "fit and details from IMAGE 2 and IMAGE 3.\n"
    "Return only the final image."
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


# Lado máximo enviado a Gemini. Las fotos de teléfono llegan en 3-12 MB;
# reducirlas baja segundos de subida/procesamiento sin afectar la calidad
# del try-on (Gemini genera a ~1024px de todos modos).
_MAX_IMAGE_SIDE = 1280


def _shrink_image(image: bytes, max_side: int | None = None) -> bytes:
    """Reduce la imagen a max_side (default _MAX_IMAGE_SIDE) si es más grande;
    si algo falla, devuelve los bytes originales (nunca rompe una generación)."""
    limit = max_side or _MAX_IMAGE_SIDE
    try:
        from io import BytesIO

        from PIL import Image

        source = Image.open(BytesIO(image))
        if max(source.size) <= limit:
            return image
        source.thumbnail((limit, limit))
        if source.mode not in ("RGB", "L"):
            source = source.convert("RGB")
        output = BytesIO()
        source.save(output, format="JPEG", quality=90)
        return output.getvalue()
    except Exception:
        return image


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
            image = _shrink_image(image)
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

    async def generate_text(
        self,
        *,
        prompt: str,
        images: list[bytes],
        model: str | None = None,
        timeout: float | None = None,
    ) -> str:
        """Respuesta de TEXTO sobre imágenes (verificación de calidad con un
        modelo barato). Nunca genera imagen. `timeout` corto para que la
        verificación jamás alargue el tiempo total de la prueba."""
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for image in images:
            image = _shrink_image(image)
            parts.append(
                {
                    "inline_data": {
                        "mime_type": _detect_mime(image),
                        "data": base64.b64encode(image).decode(),
                    }
                }
            )
        url = f"{self._base_url}/v1beta/models/{model or self._model}:generateContent"
        async with httpx.AsyncClient(
            timeout=timeout or self._timeout, transport=self._transport
        ) as client:
            response = await client.post(
                url,
                json={
                    "contents": [{"parts": parts}],
                    # Veredicto de una palabra: determinista y rápido
                    "generationConfig": {"temperature": 0, "maxOutputTokens": 10},
                },
                headers={"x-goog-api-key": self._api_key},
            )
        if response.status_code != 200:
            raise DomainError(
                f"Gemini text check failed (HTTP {response.status_code})", "PROVIDER_ERROR"
            )
        for candidate in response.json().get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if part.get("text"):
                    return str(part["text"])
        return ""

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
    try:
        from io import BytesIO

        from PIL import Image

        def thumb(data: bytes):
            return Image.open(BytesIO(data)).convert("L").resize((64, 64))

        ia, ib = thumb(a), thumb(b)
    except Exception:
        return 255.0  # si no se puede comparar, asumir que cambio (no reintentar)
    pa, pb = ia.load(), ib.load()
    total = sum(abs(pa[x, y] - pb[x, y]) for x in range(64) for y in range(64))
    return total / (64 * 64)


# Debajo de este umbral la salida es casi identica a la entrada: la prenda
# no se aplico (no-op) y conviene reintentar una vez.
_NOOP_DIFF_THRESHOLD = 3.0

# Modelo barato de visión para la verificación de calidad (~1s, ~medio
# centavo): revisa que las prendas estén puestas y sin la original asomando.
_VERIFIER_MODEL = "gemini-2.5-flash-lite"
# Tope de tiempo del inspector: si Flash-Lite está lento hoy y no responde en
# este plazo, se ACEPTA el resultado (la guardia de píxeles ya validó el
# no-op). Así la verificación nunca alarga la prueba más de ~unos segundos.
_VERIFIER_TIMEOUT_SECONDS = 2.5


def _check_item(label: str, description) -> str:
    description = str(description or "").strip()
    return f"the new {label} garment" + (f' ("{description}")' if description else "")


def _quality_prompt(checks: list[str]) -> str:
    # Benévolo a propósito: cada BAD cuesta una regeneración (~12s y $0.04),
    # así que solo debe dispararse ante fallos EVIDENTES, nunca ante dudas.
    listed = "; ".join(checks)
    return (
        "You are inspecting a virtual try-on image. The person should be "
        f"wearing: {listed}. Answer 'BAD' ONLY if you are CERTAIN of a clear "
        "failure: a listed garment is completely absent, or two garments of "
        "the same type are obviously layered (two collars, a second "
        "waistband, the old shirt clearly visible under the new one). Small "
        "imperfections, exact color/style differences from the description, "
        "or any doubt do NOT count as failures — the description is only "
        "context. If in doubt, answer 'OK'. Reply with one word only: OK or "
        "BAD."
    )


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
        extra_garment_image: bytes | None = None,
        extra_garment_type: str | None = None,
    ) -> bytes:
        # Outfit completo (torso + pierna) en UNA generación: mitad de tiempo
        # y de costo frente al encadenado de dos llamadas.
        if extra_garment_image is not None:
            prompt = params.get("prompt") or self._outfit_prompt(
                garment_type, extra_garment_type, params
            )
            checks = [
                _check_item(
                    _GARMENT_LABELS.get(garment_type, "upper-body"),
                    params.get("garment_des"),
                ),
                _check_item(
                    _GARMENT_LABELS.get(extra_garment_type or "lower_body", "lower-body"),
                    params.get("extra_garment_des"),
                ),
            ]
            return await self._generate_with_quality_guard(
                prompt, [person_image, garment_image, extra_garment_image], checks
            )

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

        return await self._generate_with_quality_guard(
            prompt,
            [person_image, garment_image],
            [_check_item(label, params.get("garment_des"))],
        )

    def _outfit_prompt(
        self,
        garment_type: str,
        extra_garment_type: str | None,
        params: dict[str, Any],
    ) -> str:
        garment_a = _GARMENT_LABELS.get(garment_type, "upper-body")
        garment_b = _GARMENT_LABELS.get(extra_garment_type or "lower_body", "lower-body")
        prompt = OUTFIT_PROMPT_TEMPLATE.format(garment_a=garment_a, garment_b=garment_b)
        garment_des = str(params.get("garment_des") or "").strip()
        if garment_des:
            prompt += (
                f'\nThe specific {garment_a} garment in IMAGE 2 is: "{garment_des}". '
                f"Reproduce that exact garment on the person."
            )
        extra_des = str(params.get("extra_garment_des") or "").strip()
        if extra_des:
            prompt += (
                f'\nThe specific {garment_b} garment in IMAGE 3 is: "{extra_des}". '
                f"Reproduce that exact garment on the person."
            )
        return prompt

    async def _passes_quality_check(self, result: bytes, checks: list[str]) -> bool:
        """Inspector semántico: un modelo barato mira el resultado y confirma
        que las prendas están puestas y sin la original asomando (layering).
        Desactivable con TRYON_QUALITY_CHECK=false (modo máxima velocidad)."""
        import os

        if os.getenv("TRYON_QUALITY_CHECK", "true").lower() != "true":
            return True
        try:
            answer = await self._client.generate_text(
                # Miniatura 512px: para el veredicto basta y ahorra ~2s de subida
                prompt=_quality_prompt(checks),
                images=[_shrink_image(result, max_side=512)],
                model=_VERIFIER_MODEL,
                timeout=_VERIFIER_TIMEOUT_SECONDS,
            )
        except Exception:
            # Timeout o error: se acepta el resultado (la guardia de píxeles ya
            # corrió). La verificación jamás debe tumbar ni alargar una prueba.
            return True
        return "bad" not in answer.strip().lower()

    async def _generate_with_quality_guard(
        self, prompt: str, images: list[bytes], checks: list[str]
    ) -> bytes:
        """Genera y valida en DOS capas: píxeles (¿cambió algo respecto a la
        foto original?) y semántica (¿las prendas están puestas, sin layering?).
        Máximo UN reintento total para acotar tiempo y costo."""
        import logging
        import time

        # El logger de uvicorn siempre es visible en docker logs
        log = logging.getLogger("uvicorn.error")
        person_image = images[0]

        started = time.monotonic()
        result = await self._client.generate(prompt=prompt, images=images)
        gen_seconds = time.monotonic() - started

        base_diff = _mean_diff(result, person_image)
        started = time.monotonic()
        passed = base_diff >= _NOOP_DIFF_THRESHOLD and await self._passes_quality_check(
            result, checks
        )
        check_seconds = time.monotonic() - started
        log.info(
            "tryon guard: gen=%.1fs diff=%.1f check=%.1fs verdict=%s",
            gen_seconds,
            base_diff,
            check_seconds,
            "OK" if passed else "RETRY",
        )
        if passed:
            return result

        # No-op o prenda mal aplicada: reintentar UNA vez con más temperatura
        started = time.monotonic()
        retry = await self._client.generate(prompt=prompt, images=images, temperature=0.7)
        retry_diff = _mean_diff(retry, person_image)
        retry_passed = retry_diff >= _NOOP_DIFF_THRESHOLD and await self._passes_quality_check(
            retry, checks
        )
        log.info(
            "tryon guard retry: %.1fs diff=%.1f verdict=%s",
            time.monotonic() - started,
            retry_diff,
            "OK" if retry_passed else "BEST-EFFORT",
        )
        if retry_passed:
            return retry
        # Ninguno pasó la inspección: mejor esfuerzo (el que más cambió)
        return retry if retry_diff >= base_diff else result


class GeminiAvatarModel:
    def __init__(self, *, client: GeminiImageClient) -> None:
        self._client = client

    async def generate(self, *, source_image: bytes, params: dict[str, Any]) -> bytes:
        prompt = params.get("prompt") or AVATAR_PROMPT
        return await self._client.generate(prompt=prompt, images=[source_image])
