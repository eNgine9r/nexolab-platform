from __future__ import annotations

import hashlib
import re
from io import BytesIO
from pathlib import PurePath
from uuid import uuid4

from fastapi import APIRouter, File, Header, HTTPException, Response, UploadFile, status
from PIL import Image, UnidentifiedImageError

from app.refrigeration.models import EquipmentImage, RefrigerationLayoutDraft, RefrigerationLayoutRevision
from app.refrigeration.repository import (
    LayoutImageNotFoundError,
    LayoutNotFoundError,
    LayoutRepositoryError,
    LayoutRevisionNotFoundError,
    LayoutValidationError,
    LayoutVersionConflictError,
    PostgresRefrigerationLayoutRepository,
)
from app.refrigeration.schemas import (
    ApiErrorDetail,
    ApiErrorResponse,
    EquipmentImageResponse,
    LayoutDraftResponse,
    LayoutDraftWrite,
    LayoutHistoryResponse,
    LayoutMutationResponse,
    LayoutRevisionResponse,
    PublishLayoutRequest,
)
from app.refrigeration.storage import ObjectStorage, ObjectStorageError

_ACCEPTED_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}
_ETAG_RE = re.compile(r'^(?:W/)?"layout-draft-v(?P<version>[1-9][0-9]*)"$')


def create_refrigeration_router(
    repository: PostgresRefrigerationLayoutRepository,
    storage: ObjectStorage,
    *,
    image_max_bytes: int,
    signed_url_seconds: int,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/equipment", tags=["refrigeration-layouts"])

    @router.get(
        "/{equipment_id}/layout/draft",
        response_model=LayoutDraftResponse,
        responses={503: {"model": ApiErrorResponse}},
    )
    def get_draft(equipment_id: str, response: Response) -> LayoutDraftResponse:
        draft = repository.get_or_create_draft(equipment_id)
        response.headers["ETag"] = _draft_etag(draft.version)
        return _draft_response(repository, storage, draft, signed_url_seconds)

    @router.put(
        "/{equipment_id}/layout/draft",
        response_model=LayoutDraftResponse,
        responses={409: {"model": ApiErrorResponse}, 422: {"model": ApiErrorResponse}},
    )
    def save_draft(
        equipment_id: str,
        payload: LayoutDraftWrite,
        response: Response,
        if_match: str = Header(alias="If-Match"),
    ) -> LayoutDraftResponse:
        expected = _parse_if_match(if_match)
        try:
            draft = repository.save_draft(
                equipment_id=equipment_id,
                expected_version=expected,
                image_id=payload.image_id,
                placements=payload.placements,
            )
        except LayoutRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = _draft_etag(draft.version)
        return _draft_response(repository, storage, draft, signed_url_seconds)

    @router.post(
        "/{equipment_id}/layout/publish",
        response_model=LayoutMutationResponse,
        status_code=status.HTTP_201_CREATED,
        responses={409: {"model": ApiErrorResponse}, 422: {"model": ApiErrorResponse}},
    )
    def publish_layout(
        equipment_id: str,
        payload: PublishLayoutRequest,
        response: Response,
        if_match: str = Header(alias="If-Match"),
    ) -> LayoutMutationResponse:
        expected = _parse_if_match(if_match)
        try:
            result = repository.publish(
                equipment_id=equipment_id,
                expected_version=expected,
                actor_id=payload.actor_id,
            )
        except LayoutRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = _draft_etag(result.draft.version)
        return LayoutMutationResponse(
            draft=_draft_response(repository, storage, result.draft, signed_url_seconds),
            published=_revision_response(repository, storage, result.published, signed_url_seconds),
        )

    @router.get(
        "/{equipment_id}/layout/published",
        response_model=LayoutRevisionResponse,
        responses={404: {"model": ApiErrorResponse}},
    )
    def get_published(equipment_id: str) -> LayoutRevisionResponse:
        revision = repository.get_published(equipment_id)
        if revision is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "layout_not_published", "message": "layout has no published revision"},
            )
        return _revision_response(repository, storage, revision, signed_url_seconds)

    @router.get(
        "/{equipment_id}/layout/history",
        response_model=LayoutHistoryResponse,
    )
    def get_history(equipment_id: str) -> LayoutHistoryResponse:
        return LayoutHistoryResponse(
            items=[
                _revision_response(repository, storage, item, signed_url_seconds)
                for item in repository.list_history(equipment_id)
            ]
        )

    @router.post(
        "/{equipment_id}/layout/history/{revision_id}/restore",
        response_model=LayoutDraftResponse,
        responses={404: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
    )
    def restore_revision(
        equipment_id: str,
        revision_id: str,
        response: Response,
        if_match: str = Header(alias="If-Match"),
    ) -> LayoutDraftResponse:
        expected = _parse_if_match(if_match)
        try:
            draft = repository.restore(
                equipment_id=equipment_id,
                revision_id=revision_id,
                expected_version=expected,
            )
        except LayoutRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = _draft_etag(draft.version)
        return _draft_response(repository, storage, draft, signed_url_seconds)

    @router.post(
        "/{equipment_id}/images",
        response_model=EquipmentImageResponse,
        status_code=status.HTTP_201_CREATED,
        responses={413: {"model": ApiErrorResponse}, 415: {"model": ApiErrorResponse}},
    )
    async def upload_image(
        equipment_id: str,
        file: UploadFile = File(...),
        actor_id: str = Header(alias="X-Actor-Id", min_length=1, max_length=128),
    ) -> EquipmentImageResponse:
        content = await file.read(image_max_bytes + 1)
        if len(content) > image_max_bytes:
            raise _api_http_error(413, "image_too_large", "equipment image exceeds the configured limit")
        media_type, extension, width_px, height_px = _inspect_image(content, file.content_type)
        checksum = hashlib.sha256(content).hexdigest()
        image_id = str(uuid4())
        storage_key = f"equipment-images/{image_id}{extension}"
        try:
            stored = storage.put(
                key=storage_key,
                content=content,
                media_type=media_type,
                checksum_sha256=checksum,
            )
        except ObjectStorageError as error:
            raise _api_http_error(503, "object_storage_unavailable", str(error)) from error
        try:
            image = repository.create_image(
                image_id=image_id,
                equipment_id=equipment_id,
                storage_key=storage_key,
                original_filename=PurePath(file.filename or f"equipment{extension}").name[:255],
                media_type=media_type,
                size_bytes=len(content),
                width_px=width_px,
                height_px=height_px,
                checksum_sha256=checksum,
                object_etag=stored.etag,
                created_by=actor_id,
            )
        except Exception:
            try:
                storage.delete(storage_key)
            finally:
                raise
        return _image_response(storage, image, signed_url_seconds)

    return router


def _inspect_image(content: bytes, declared_media_type: str | None) -> tuple[str, str, int, int]:
    if not content:
        raise _api_http_error(415, "invalid_image", "equipment image is empty")
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        with Image.open(BytesIO(content)) as image:
            image_format = image.format
            width_px, height_px = image.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise _api_http_error(415, "invalid_image", "file content is not a supported image") from error
    if image_format not in _ACCEPTED_FORMATS:
        raise _api_http_error(415, "unsupported_image_type", "only JPEG, PNG and WebP are supported")
    media_type, extension = _ACCEPTED_FORMATS[image_format]
    if declared_media_type and declared_media_type != media_type:
        raise _api_http_error(415, "image_media_type_mismatch", "declared media type does not match image bytes")
    if width_px <= 0 or height_px <= 0:
        raise _api_http_error(415, "invalid_image_dimensions", "image dimensions must be positive")
    return media_type, extension, width_px, height_px


def _parse_if_match(value: str) -> int:
    match = _ETAG_RE.fullmatch(value.strip())
    if match is None:
        raise _api_http_error(
            428,
            "layout_version_required",
            'If-Match must contain a draft ETag such as W/"layout-draft-v3"',
        )
    return int(match.group("version"))


def _draft_etag(version: int) -> str:
    return f'W/"layout-draft-v{version}"'


def _repository_http_error(error: LayoutRepositoryError) -> HTTPException:
    if isinstance(error, LayoutVersionConflictError):
        return _api_http_error(
            409,
            error.code,
            str(error),
            expected_version=error.expected_version,
            actual_version=error.actual_version,
        )
    if isinstance(error, LayoutValidationError):
        return _api_http_error(422, error.code, str(error), issues=error.issues)
    if isinstance(error, (LayoutNotFoundError, LayoutImageNotFoundError, LayoutRevisionNotFoundError)):
        return _api_http_error(404, error.code, str(error))
    return _api_http_error(500, error.code, str(error))


def _api_http_error(
    status_code: int,
    code: str,
    message: str,
    *,
    expected_version: int | None = None,
    actual_version: int | None = None,
    issues: list[str] | None = None,
) -> HTTPException:
    detail = ApiErrorDetail(
        code=code,
        message=message,
        expected_version=expected_version,
        actual_version=actual_version,
        issues=issues,
    ).model_dump(exclude_none=True)
    return HTTPException(status_code=status_code, detail=detail)


def _draft_response(
    repository: PostgresRefrigerationLayoutRepository,
    storage: ObjectStorage,
    draft: RefrigerationLayoutDraft,
    signed_url_seconds: int,
) -> LayoutDraftResponse:
    image = (
        _image_response(storage, repository.get_image(draft.equipment_id, draft.image_id), signed_url_seconds)
        if draft.image_id
        else None
    )
    return LayoutDraftResponse(
        id=draft.id,
        equipment_id=draft.equipment_id,
        version=draft.version,
        image=image,
        placements=draft.placements,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


def _revision_response(
    repository: PostgresRefrigerationLayoutRepository,
    storage: ObjectStorage,
    revision: RefrigerationLayoutRevision,
    signed_url_seconds: int,
) -> LayoutRevisionResponse:
    image = repository.get_image(revision.equipment_id, revision.image_id)
    return LayoutRevisionResponse(
        id=revision.id,
        equipment_id=revision.equipment_id,
        revision=revision.revision,
        source_draft_version=revision.source_draft_version,
        image=_image_response(storage, image, signed_url_seconds),
        placements=revision.placements,
        published_by=revision.published_by,
        published_at=revision.published_at,
    )


def _image_response(
    storage: ObjectStorage, image: EquipmentImage, signed_url_seconds: int
) -> EquipmentImageResponse:
    try:
        content_url = storage.signed_get_url(image.storage_key, expires_seconds=signed_url_seconds)
    except ObjectStorageError as error:
        raise _api_http_error(503, "object_storage_unavailable", str(error)) from error
    return EquipmentImageResponse(
        id=image.id,
        equipment_id=image.equipment_id,
        original_filename=image.original_filename,
        media_type=image.media_type,
        size_bytes=image.size_bytes,
        width_px=image.width_px,
        height_px=image.height_px,
        checksum_sha256=image.checksum_sha256,
        object_etag=image.object_etag,
        created_by=image.created_by,
        created_at=image.created_at,
        content_url=content_url,
    )
