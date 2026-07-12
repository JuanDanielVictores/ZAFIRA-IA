"""Avatar router — synchronous avatar generation."""

from fastapi import APIRouter, Depends

from app.application.dto.avatar import AvatarRequest, AvatarResponse
from app.application.use_cases.avatar.generate import GenerateAvatarUseCase
from app.interfaces.dependencies import get_generate_avatar_use_case
from app.interfaces.openapi_tags import OPENAPI_TAG_AVATAR

router = APIRouter()


@router.post(
    "",
    response_model=AvatarResponse,
    summary="Generate a semi-realistic avatar from a user photo",
    description=(
        "Downloads the source photo, runs the configured avatar model and stores the "
        "result in object storage under `avatars/{external_ref}.png`. Synchronous: the "
        "response returns once the image is persisted."
    ),
    tags=[OPENAPI_TAG_AVATAR],
)
async def generate_avatar(
    request: AvatarRequest,
    use_case: GenerateAvatarUseCase = Depends(get_generate_avatar_use_case),
) -> AvatarResponse:
    return await use_case.execute(request)
