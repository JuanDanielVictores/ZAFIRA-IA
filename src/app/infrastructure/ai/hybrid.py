"""Hybrid try-on: cada tipo de prenda usa el motor donde rinde mejor.

- upper_body y dress -> Gemini (edicion pixel-fiel de la foto original:
  fotorrealista, conserva fondo/cara/resto de ropa intactos).
- lower_body -> IDM-VTON version DressCode via Replicate (geometria de
  piernas confiable; Gemini tiende a no aplicar jean-sobre-jean).

Se activa con AI_BACKEND=hybrid (requiere GEMINI_API_KEY y PROVIDER_*).
"""

from typing import Any


class HybridTryOnModel:
    def __init__(self, *, gemini_model: Any, hosted_model: Any) -> None:
        self._gemini = gemini_model
        self._hosted = hosted_model

    async def generate(
        self,
        *,
        person_image: bytes,
        garment_image: bytes,
        garment_type: str,
        params: dict[str, Any],
    ) -> bytes:
        model = self._hosted if garment_type == "lower_body" else self._gemini
        return await model.generate(
            person_image=person_image,
            garment_image=garment_image,
            garment_type=garment_type,
            params=params,
        )
