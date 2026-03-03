"""Unit tests for image generation provider logic."""

import pytest

from app.services import image_generation_service as svc_module
from app.services.image_generation_service import (
    ImageGenerationError,
    ImageGenerationService,
    ImageJob,
    pick_closest_ratio,
)


def test_pick_closest_ratio_exact_match():
    ratio = pick_closest_ratio(1080, 1080, ("1:1", "16:9", "9:16"))
    assert ratio == "1:1"


def test_pick_closest_ratio_nearest_supported():
    ratio = pick_closest_ratio(1200, 628, ("1:1", "16:9", "4:3"))
    assert ratio == "16:9"


def test_build_kie_payload_for_imagen4():
    service = ImageGenerationService(kie_api_key="test-key")
    job = ImageJob(prompt="test", width=1080, height=1080, model="imagen4")

    payload = service._build_kie_payload(job)

    assert payload["model"] == "google/imagen4"
    assert payload["input"]["aspect_ratio"] == "1:1"


def test_build_kie_payload_for_edit():
    service = ImageGenerationService(kie_api_key="test-key")
    job = ImageJob(
        prompt="edit me",
        width=1080,
        height=1350,
        model="nano-banana-pro",
        use_product_image=True,
        product_shots=["https://example.com/image.png"],
    )

    payload = service._build_kie_payload(job)

    assert payload["model"] == "google/nano-banana-edit"
    assert payload["input"]["image_urls"] == ["https://example.com/image.png"]
    assert payload["input"]["image_size"] == "4:5"


def test_resolve_provider_auto_prefers_kie():
    service = ImageGenerationService(
        kie_api_key="kie-key",
        fal_api_key="fal-key",
        default_provider="auto",
    )
    assert service._resolve_provider("auto", "nano-banana-pro") == "kie"


def test_resolve_provider_fal_imagen4_raises(monkeypatch):
    monkeypatch.setattr(svc_module, "fal_client", object())
    service = ImageGenerationService(kie_api_key="", fal_api_key="fal-key")
    with pytest.raises(ImageGenerationError):
        service._resolve_provider("fal", "imagen4")


def test_extract_kie_url_from_result_json():
    data = {"resultJson": '{"resultUrls":["https://example.com/final.png"]}'}
    url = ImageGenerationService._extract_kie_url(data)
    assert url == "https://example.com/final.png"
