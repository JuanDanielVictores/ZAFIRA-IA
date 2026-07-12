"""Try-on router — synchronous virtual try-on generation."""

from fastapi import APIRouter, Depends

from app.application.dto.tryon import TryOnRequest, TryOnResponse
from app.application.use_cases.tryon.generate import GenerateTryOnUseCase
from app.interfaces.dependencies import get_generate_tryon_use_case
from app.interfaces.openapi_tags import OPENAPI_TAG_TRYON

router = APIRouter()


@router.post(
    "",
    response_model=TryOnResponse,
    summary="Render a garment over an avatar (virtual try-on)",
    description=(
        "Downloads the person and garment images, runs the configured try-on model and "
        "stores the result in object storage under `tryons/{external_ref}.png`. "
        "Synchronous: the response returns once the image is persisted."
    ),
    tags=[OPENAPI_TAG_TRYON],
)
async def generate_tryon(
    request: TryOnRequest,
    use_case: GenerateTryOnUseCase = Depends(get_generate_tryon_use_case),
) -> TryOnResponse:
    return await use_case.execute(request)
