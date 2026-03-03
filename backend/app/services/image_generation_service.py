"""Image generation provider abstraction for Fal.ai and Kie.ai."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Optional, Sequence

import httpx

from app.core.config import settings

try:
    import fal_client
except ImportError:  # pragma: no cover - optional dependency
    fal_client = None


class ImageGenerationError(RuntimeError):
    """Raised when image generation fails."""


@dataclass
class ImageJob:
    """Normalized image generation job."""

    prompt: str
    width: int
    height: int
    model: str = "nano-banana-pro"
    use_product_image: bool = False
    product_shots: Optional[list[str]] = None
    provider: str = "auto"


def _safe_ratio(width: int, height: int) -> float:
    if width <= 0 or height <= 0:
        return 1.0
    return width / height


def pick_closest_ratio(
    width: int,
    height: int,
    allowed_ratios: Sequence[str],
    fallback: str = "1:1",
) -> str:
    """Map width/height into the closest provider-supported ratio string."""
    if not allowed_ratios:
        return fallback

    target = _safe_ratio(width, height)
    best = fallback
    best_delta = float("inf")

    for ratio in allowed_ratios:
        try:
            left, right = ratio.split(":")
            ratio_value = float(left) / float(right)
        except Exception:
            continue

        delta = abs(target - ratio_value)
        if delta < best_delta:
            best = ratio
            best_delta = delta

    return best


class ImageGenerationService:
    """Generate images with provider failover and bounded concurrency."""

    KIE_NANO_RATIOS = (
        "1:1",
        "9:16",
        "16:9",
        "3:4",
        "4:3",
        "3:2",
        "2:3",
        "5:4",
        "4:5",
        "21:9",
        "auto",
    )
    KIE_IMAGEN4_RATIOS = ("1:1", "16:9", "9:16", "3:4", "4:3")

    def __init__(
        self,
        fal_api_key: Optional[str] = None,
        kie_api_key: Optional[str] = None,
        default_provider: Optional[str] = None,
        kie_base_url: Optional[str] = None,
        max_concurrency: Optional[int] = None,
        retry_attempts: Optional[int] = None,
        kie_poll_interval: Optional[float] = None,
        kie_max_poll_attempts: Optional[int] = None,
    ) -> None:
        self.fal_api_key = fal_api_key if fal_api_key is not None else settings.FAL_AI_API_KEY
        self.kie_api_key = kie_api_key if kie_api_key is not None else settings.KIE_AI_API_KEY
        self.default_provider = (default_provider or settings.IMAGE_PROVIDER or "auto").lower().strip()
        self.kie_base_url = (kie_base_url or settings.KIE_API_BASE_URL or "https://api.kie.ai").rstrip("/")
        self.max_concurrency = max(1, int(max_concurrency or settings.IMAGE_GEN_MAX_CONCURRENCY))
        self.retry_attempts = max(1, int(retry_attempts or settings.IMAGE_GEN_RETRY_ATTEMPTS))
        self.kie_poll_interval = float(kie_poll_interval or settings.KIE_POLL_INTERVAL_SECONDS)
        self.kie_max_poll_attempts = int(kie_max_poll_attempts or settings.KIE_MAX_POLL_ATTEMPTS)

    @property
    def fal_enabled(self) -> bool:
        return bool(self.fal_api_key and fal_client)

    @property
    def kie_enabled(self) -> bool:
        return bool(self.kie_api_key)

    async def generate_batch(self, jobs: list[ImageJob]) -> list[str]:
        """Generate a batch of images with bounded concurrency."""
        if not jobs:
            return []

        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _run(job: ImageJob) -> str:
            async with semaphore:
                return await self._generate_with_retry(job)

        tasks = [_run(job) for job in jobs]
        return await asyncio.gather(*tasks)

    async def _generate_with_retry(self, job: ImageJob) -> str:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                return await self._generate_single(job)
            except Exception as exc:
                last_error = exc
                if attempt < self.retry_attempts:
                    await asyncio.sleep(min(1.0 * attempt, 3.0))
        raise ImageGenerationError(f"Image generation failed after retries: {last_error}") from last_error

    async def _generate_single(self, job: ImageJob) -> str:
        provider = self._resolve_provider(job.provider, job.model)
        if provider == "kie":
            return await self._generate_with_kie(job)
        if provider == "fal":
            return await self._generate_with_fal(job)
        raise ImageGenerationError(f"Unsupported provider: {provider}")

    def _resolve_provider(self, provider_hint: str, model: str) -> str:
        hint = (provider_hint or "auto").lower().strip()
        if hint == "auto":
            hint = self.default_provider
        if hint in ("", "auto"):
            # Prefer Kie when configured because it supports both nano-banana and imagen4.
            if self.kie_enabled:
                return "kie"
            if self.fal_enabled:
                return "fal"
            raise ImageGenerationError("No image provider configured. Set KIE_AI_API_KEY or FAL_AI_API_KEY.")

        if hint == "kie":
            if not self.kie_enabled:
                raise ImageGenerationError("Kie provider requested but KIE_AI_API_KEY is not configured.")
            return "kie"

        if hint == "fal":
            if not self.fal_enabled:
                raise ImageGenerationError("Fal provider requested but FAL_AI_API_KEY is not configured.")
            if model == "imagen4":
                raise ImageGenerationError(
                    "Fal provider does not support imagen4 in this project. Use provider='kie' for imagen4."
                )
            return "fal"

        raise ImageGenerationError(f"Invalid provider '{hint}'. Expected one of: auto, kie, fal.")

    async def _generate_with_fal(self, job: ImageJob) -> str:
        os.environ["FAL_KEY"] = self.fal_api_key

        if job.use_product_image and job.product_shots:
            model_id = "fal-ai/nano-banana-pro/edit"
            arguments = {
                "prompt": job.prompt,
                "image_urls": job.product_shots,
                "aspect_ratio": f"{job.width}:{job.height}",
                "output_format": "png",
            }
        else:
            model_id = "fal-ai/nano-banana-pro"
            arguments = {
                "prompt": job.prompt,
                "image_size": {"width": job.width, "height": job.height},
            }

        handler = await fal_client.submit_async(model_id, arguments=arguments)
        result = await handler.get()
        images = result.get("images") or []
        if not images or not images[0].get("url"):
            raise ImageGenerationError("Fal returned no image URL.")
        return images[0]["url"]

    def _build_kie_payload(self, job: ImageJob) -> dict[str, Any]:
        if job.use_product_image and job.product_shots:
            ratio = pick_closest_ratio(job.width, job.height, self.KIE_NANO_RATIOS)
            return {
                "model": "google/nano-banana-edit",
                "input": {
                    "prompt": job.prompt,
                    "image_urls": job.product_shots,
                    "output_format": "png",
                    "image_size": ratio,
                },
            }

        if job.model == "imagen4":
            ratio = pick_closest_ratio(job.width, job.height, self.KIE_IMAGEN4_RATIOS)
            return {
                "model": "google/imagen4",
                "input": {
                    "prompt": job.prompt,
                    "aspect_ratio": ratio,
                },
            }

        ratio = pick_closest_ratio(job.width, job.height, self.KIE_NANO_RATIOS)
        return {
            "model": "google/nano-banana",
            "input": {
                "prompt": job.prompt,
                "output_format": "png",
                "image_size": ratio,
            },
        }

    async def _generate_with_kie(self, job: ImageJob) -> str:
        payload = self._build_kie_payload(job)
        headers = {"Authorization": f"Bearer {self.kie_api_key}"}

        timeout = httpx.Timeout(
            connect=settings.IMAGE_GEN_TIMEOUT_SECONDS,
            read=settings.IMAGE_GEN_TIMEOUT_SECONDS,
            write=settings.IMAGE_GEN_TIMEOUT_SECONDS,
            pool=settings.IMAGE_GEN_TIMEOUT_SECONDS,
        )

        async with httpx.AsyncClient(timeout=timeout) as client:
            create_resp = await client.post(
                f"{self.kie_base_url}/api/v1/jobs/createTask",
                json=payload,
                headers=headers,
            )
            create_resp.raise_for_status()
            create_data = create_resp.json()

            if create_data.get("code") != 200:
                raise ImageGenerationError(
                    f"Kie createTask failed: code={create_data.get('code')} msg={create_data.get('msg')}"
                )

            task_id = (create_data.get("data") or {}).get("taskId")
            if not task_id:
                raise ImageGenerationError("Kie createTask returned no taskId.")

            for attempt in range(self.kie_max_poll_attempts):
                poll_resp = await client.get(
                    f"{self.kie_base_url}/api/v1/jobs/recordInfo",
                    params={"taskId": task_id},
                    headers=headers,
                )
                poll_resp.raise_for_status()
                poll_data = poll_resp.json()

                if poll_data.get("code") != 200:
                    raise ImageGenerationError(
                        f"Kie recordInfo failed: code={poll_data.get('code')} msg={poll_data.get('msg')}"
                    )

                data = poll_data.get("data") or {}
                state = data.get("state")

                if state == "success":
                    return self._extract_kie_url(data)

                if state == "fail":
                    fail_msg = data.get("failMsg") or poll_data.get("msg") or "unknown failure"
                    fail_code = data.get("failCode") or "unknown"
                    raise ImageGenerationError(f"Kie task failed: {fail_code} {fail_msg}")

                # waiting / queuing / generating
                if attempt < self.kie_max_poll_attempts - 1:
                    await asyncio.sleep(self.kie_poll_interval)

        raise ImageGenerationError("Kie task polling timed out.")

    @staticmethod
    def _extract_kie_url(task_data: dict[str, Any]) -> str:
        result_json = task_data.get("resultJson")
        parsed: Any = {}

        if isinstance(result_json, str) and result_json.strip():
            parsed = json.loads(result_json)
        elif isinstance(result_json, dict):
            parsed = result_json

        result_urls = []
        if isinstance(parsed, dict):
            result_urls = parsed.get("resultUrls") or parsed.get("result_urls") or []
        if not result_urls:
            result_urls = task_data.get("resultUrls") or task_data.get("result_urls") or []

        if not result_urls:
            raise ImageGenerationError("Kie task succeeded but returned no result URL.")

        url = result_urls[0]
        if not isinstance(url, str) or not url:
            raise ImageGenerationError("Kie returned an invalid result URL.")
        return url
