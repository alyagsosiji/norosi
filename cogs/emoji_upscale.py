"""
cogs/emoji_upscale.py - 서버별 커스텀 이모지 & 스티커 160x160 WebP 리사이저 및 웹훅 대리 전송 모듈
- 참고 및 포팅 원본: https://github.com/Kamilake/emote-cdn-rust (License: The Unlicense / Public Domain)
- 기본 상태: 모든 서버 OFF (False)
- 서버 관리자(Administrator / Manage Server) 전용 ON/OFF 및 상태 패널 (/이모지업스케일)
- 원본 종횡비를 100% 유지하며 160x160 박스 내 최대 크기(Lanczos3)로 리사이징 후 WebP(정적/애니메이션) 포맷으로 변환
- 24시간 TTL 메모리 캐시 + SHA-1 ETag(W/"...") + 선택적 HMAC-SHA256 서명 검증(SIGNING_KEY) + HTTP CDN 엔드포인트(/emoji/:id, /e/:id, /sticker/:id, /s/:id) 지원

================================================================================
License Notice for Referenced Implementation (Kamilake/emote-cdn-rust):
This is free and unencumbered software released into the public domain.
Anyone is free to copy, modify, publish, use, compile, sell, or distribute this
software, either in source code form or as a compiled binary, for any purpose,
commercial or non-commercial, and by any means.
For more information, please refer to <https://unlicense.org>
================================================================================
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import enum
import hashlib
import hmac
import io
import os
import re
import struct
import threading
import time
from collections import OrderedDict
from typing import Optional

import aiohttp
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageSequence

import core

# 순수 커스텀 이모지 메시지(1~3개, 앞뒤 공백만 허용) 매칭용 정규식
CUSTOM_EMOJI_RE = re.compile(r"<(a?):([a-zA-Z0-9_]{1,64}):(\d{15,22})>")

MAX_EMOJIS_PER_MESSAGE = 3
# emote-cdn-rust 표준: 160x160 종횡비 유지 리사이징 박스
EMOTE_TARGET_WIDTH = 160
EMOTE_TARGET_HEIGHT = 160
STICKER_TARGET_SIZE = EMOTE_TARGET_WIDTH
DOUBLE_SLOT_SIZE = EMOTE_TARGET_WIDTH
TRIPLE_SLOT_SIZE = EMOTE_TARGET_WIDTH
EMOJI_SLOT_SIZE = EMOTE_TARGET_WIDTH
STATIC_TARGET_SIZE = EMOTE_TARGET_WIDTH
ANIMATED_TARGET_SIZE = EMOTE_TARGET_WIDTH
MULTI_EMOJI_GAP = 8

MAX_UPLOAD_BYTES = 24 * 1024 * 1024  # Discord 25MB 제한 안전 마진
WEBHOOK_NAME = "norosi-emoji-upscale"
USER_AGENT = "emoji-resizer/0.1 (+https://example.local) norosi/1.0"
CACHE_TTL_SECONDS = 24 * 3600  # 24시간 TTL (emote-cdn-rust 동일)
CACHE_MAX_CAPACITY = 4096      # 인메모리 WebP 바이트 캐시 엔트리 상한
RESAMPLE_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)

try:
    from PIL import GifImagePlugin
    GifImagePlugin.LOADING_STRATEGY = GifImagePlugin.LoadingStrategy.RGB_AFTER_DIFFERENT_PALETTE_ONLY
except Exception:
    pass


# ==========================================
# 1. emote-cdn-rust 유틸리티 & 바이너리 포맷 감지기
# ==========================================
class DetectedFormat(enum.Enum):
    WEBP = "WebP"
    PNG = "Png"
    APNG = "Apng"
    GIF = "Gif"
    UNKNOWN = "Unknown"


def clean_id_from_path(raw_id: str) -> str:
    """확장자(.webp, .gif, .png, .jpg, .jpeg)를 제거한 순수 ID 문자열을 반환합니다 (emote-cdn-rust utils::clean_id_from_path)."""
    s = (raw_id or "").strip()
    for ext in (".webp", ".gif", ".png", ".jpg", ".jpeg"):
        if s.lower().endswith(ext):
            s = s[: -len(ext)]
    return s


def validate_id(clean_id: str) -> bool:
    """Discord 이모지/스티커 ID 유효성 검사 (5~30자리 ASCII 숫자, 오픈 프록시 방지)."""
    return bool(clean_id) and clean_id.isascii() and clean_id.isdigit() and (5 <= len(clean_id) <= 30)


def make_etag(data: bytes) -> str:
    """SHA-1 기반 약한 ETag 생성 (emote-cdn-rust utils::make_etag)."""
    digest = hashlib.sha1(data).hexdigest()
    return f'W/"{digest}"'


def format_emoji_src(emoji_id: str) -> str:
    return f"https://cdn.discordapp.com/emojis/{emoji_id}.webp"


def format_sticker_src(sticker_id: str) -> str:
    return f"https://media.discordapp.net/stickers/{sticker_id}.png"


def verify_signature(
    item_id: str,
    ex: Optional[str | int],
    hm: Optional[str],
    signing_key: str,
) -> bool:
    """
    SIGNING_KEY 설정 시 HMAC-SHA256 서명 및 만료 시간(ex) 검증 (emote-cdn-rust auth::verify_signature).
    페이로드 형식: "{id}.{exp}", 서명 인코딩: base64url (no padding).
    """
    if ex is None or not hm or not signing_key:
        return False
    try:
        exp_int = int(ex)
    except (ValueError, TypeError):
        return False

    now_sec = int(time.time())
    if now_sec > exp_int:
        return False

    payload = f"{item_id}.{exp_int}".encode("utf-8")
    expected = hmac.new(signing_key.encode("utf-8"), payload, hashlib.sha256).digest()
    try:
        padded = hm.strip() + "=" * ((4 - len(hm.strip()) % 4) % 4)
        provided = base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception:
        return False

    return hmac.compare_digest(expected, provided)


def is_animated_webp(data: bytes) -> bool:
    """
    WebP 바이너리에서 VP8X 청크의 애니메이션 플래그(비트 1: 0x02)를 검사합니다
    (emote-cdn-rust image_processing::is_animated_webp).
    """
    if len(data) < 12:
        return False
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return False

    pos = 12
    data_len = len(data)
    while pos + 8 <= data_len:
        chunk_id = data[pos : pos + 4]
        chunk_size = struct.unpack_from("<I", data, pos + 4)[0]
        if chunk_id == b"VP8X":
            if pos + 8 < data_len:
                flags = data[pos + 8]
                return (flags & 0x02) != 0
            return False
        pos += 8 + chunk_size + (chunk_size % 2)
    return False


def is_apng(data: bytes) -> bool:
    """
    PNG 시그니처 이후 청크를 순회하며 acTL 청크 존재 여부로 APNG를 판별합니다
    (emote-cdn-rust image_processing::is_apng).
    """
    if len(data) < 8 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    pos = 8
    data_len = len(data)
    while pos + 8 <= data_len:
        chunk_len = struct.unpack_from(">I", data, pos)[0]
        chunk_type = data[pos + 4 : pos + 8]
        if chunk_type == b"acTL":
            return True
        if chunk_type == b"IEND":
            break
        pos += 4 + 4 + chunk_len + 4
    return False


def detect_image_format(data: bytes) -> DetectedFormat:
    """바이너리 시그니처로 WebP / APNG / PNG / GIF 포맷을 감지합니다 (emote-cdn-rust image_processing::detect_image_format)."""
    if not data or len(data) < 12:
        return DetectedFormat.UNKNOWN
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        if is_apng(data):
            return DetectedFormat.APNG
        return DetectedFormat.PNG
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return DetectedFormat.WEBP
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return DetectedFormat.GIF
    return DetectedFormat.UNKNOWN


# ==========================================
# 2. emote-cdn-rust 160x160 종횡비 유지 WebP 이미지 프로세서
# ==========================================
def compute_aspect_dimensions(
    width: int,
    height: int,
    target_width: int = EMOTE_TARGET_WIDTH,
    target_height: int = EMOTE_TARGET_HEIGHT,
) -> tuple[int, int]:
    """
    원본 이미지의 종횡비를 유지하면서 target_width x target_height 박스 내에 맞는 새 크기를 계산합니다
    (emote-cdn-rust resize_animated_webp / resize_apng 비율 계산식 동일).
    """
    if width <= 0 or height <= 0:
        return target_width, target_height
    aspect_ratio = float(width) / float(height)
    target_aspect = float(target_width) / float(target_height)
    if aspect_ratio > target_aspect:
        new_width = target_width
        new_height = max(1, int(float(target_width) / aspect_ratio))
    else:
        new_width = max(1, int(float(target_height) * aspect_ratio))
        new_height = target_height
    return max(1, new_width), max(1, new_height)


def _compute_scaled_size(width: int, height: int, target_size: int = EMOTE_TARGET_WIDTH) -> tuple[int, int]:
    return compute_aspect_dimensions(width, height, target_size, target_size)


def _resize_rgba(
    rgba: Image.Image,
    target_width: int = EMOTE_TARGET_WIDTH,
    target_height: Optional[int] = None,
) -> Image.Image:
    """원본 종횡비를 유지하며 target_width x target_height 박스로 Lanczos3 리사이징합니다."""
    th = target_height if target_height is not None else target_width
    new_w, new_h = compute_aspect_dimensions(rgba.width, rgba.height, target_width, th)
    if (new_w, new_h) == (rgba.width, rgba.height):
        return rgba.copy()
    return rgba.resize((new_w, new_h), RESAMPLE_LANCZOS)


def resize_static_image(
    data: bytes,
    target_width: int = EMOTE_TARGET_WIDTH,
    target_height: int = EMOTE_TARGET_HEIGHT,
) -> bytes:
    """
    정적 이미지(WebP, PNG)를 디코드하여 종횡비를 유지하며 160x160 박스 내 최대 크기로 Lanczos3 리사이즈 후
    WebP 포맷으로 인코딩합니다 (emote-cdn-rust image_processing::resize_static_image).
    """
    with Image.open(io.BytesIO(data)) as img:
        rgba = img.convert("RGBA")
        resized = _resize_rgba(rgba, target_width, target_height)
        out = io.BytesIO()
        resized.save(out, format="WEBP", lossless=True, quality=90, method=4)
        return out.getvalue()


def resize_animated_image_to_webp(
    data: bytes,
    target_width: int = EMOTE_TARGET_WIDTH,
    target_height: int = EMOTE_TARGET_HEIGHT,
    *,
    is_webp_source: bool = False,
) -> bytes:
    """
    애니메이션 WebP / APNG / GIF를 디코드하여 각 프레임을 종횡비 유지 160x160(Lanczos3)으로 리사이즈 후
    애니메이션 WebP(무한 루프 loop=0, lossless=True, quality=70.0, method=4, allow_mixed=True)로 인코딩합니다
    (emote-cdn-rust image_processing::resize_animated_webp / resize_apng).
    """
    with Image.open(io.BytesIO(data)) as img:
        width, height = img.size
        new_width, new_height = compute_aspect_dimensions(width, height, target_width, target_height)

        # 원본이 이미 목표 크기인 애니메이션 WebP라면 재인코딩 없이 원본 바이트 즉시 반환 (emote-cdn-rust 동일)
        if is_webp_source and new_width == width and new_height == height:
            return data

        frames_rgba: list[Image.Image] = []
        durations: list[int] = []

        for frame in ImageSequence.Iterator(img):
            raw_dur = frame.info.get("duration", img.info.get("duration", 100))
            try:
                dur_ms = int(round(float(raw_dur)))
            except (ValueError, TypeError):
                dur_ms = 100
            if dur_ms <= 0:
                dur_ms = 100
            dur_ms = max(1, dur_ms)

            rgba_frame = frame.convert("RGBA")
            if (rgba_frame.width, rgba_frame.height) != (new_width, new_height):
                resized_frame = rgba_frame.resize((new_width, new_height), RESAMPLE_LANCZOS)
            else:
                resized_frame = rgba_frame.copy()
            frames_rgba.append(resized_frame)
            durations.append(dur_ms)

    if not frames_rgba:
        raise ValueError("No frames found in animated image")

    if len(frames_rgba) == 1:
        out = io.BytesIO()
        frames_rgba[0].save(out, format="WEBP", lossless=True, quality=90, method=4)
        return out.getvalue()

    out = io.BytesIO()
    frames_rgba[0].save(
        out,
        format="WEBP",
        save_all=True,
        append_images=frames_rgba[1:],
        duration=durations,
        loop=0,
        lossless=True,
        quality=70,
        method=4,
        minimize_size=False,
        allow_mixed=True,
    )
    webp_bytes = out.getvalue()
    if len(webp_bytes) > MAX_UPLOAD_BYTES:
        out_lossy = io.BytesIO()
        frames_rgba[0].save(
            out_lossy,
            format="WEBP",
            save_all=True,
            append_images=frames_rgba[1:],
            duration=durations,
            loop=0,
            lossless=False,
            quality=75,
            method=4,
            minimize_size=False,
        )
        webp_bytes = out_lossy.getvalue()
    return webp_bytes


def resize_animated_webp(
    data: bytes,
    target_width: int = EMOTE_TARGET_WIDTH,
    target_height: int = EMOTE_TARGET_HEIGHT,
) -> bytes:
    """애니메이션 WebP 리사이징 (실패 시 원본 반환 폴백은 호출부/핸들러에서도 보장)."""
    return resize_animated_image_to_webp(data, target_width, target_height, is_webp_source=True)


def resize_apng(
    data: bytes,
    target_width: int = EMOTE_TARGET_WIDTH,
    target_height: int = EMOTE_TARGET_HEIGHT,
) -> bytes:
    """APNG를 160x160 애니메이션 WebP로 변환합니다."""
    return resize_animated_image_to_webp(data, target_width, target_height, is_webp_source=False)


def process_emote_bytes_to_webp(
    body: bytes,
    target_width: int = EMOTE_TARGET_WIDTH,
    target_height: int = EMOTE_TARGET_HEIGHT,
) -> tuple[bytes, str]:
    """
    emote-cdn-rust handlers::process_image 파이프라인과 동일하게 이미지 포맷을 감지하여
    종횡비를 유지한 160x160 WebP 바이트를 반환합니다.
    """
    fmt = detect_image_format(body)
    if fmt == DetectedFormat.WEBP:
        if is_animated_webp(body):
            try:
                return resize_animated_webp(body, target_width, target_height), "webp"
            except Exception as e:
                # emote-cdn-rust: 애니메이션 WebP 리사이징 실패 시 원본 반환
                print(f"⚠️ [emoji_upscale] Failed to resize animated WebP ({e}), serving original", flush=True)
                return body, "webp"
    elif fmt == DetectedFormat.APNG:
        try:
            return resize_apng(body, target_width, target_height), "webp"
        except Exception as e:
            print(f"⚠️ [emoji_upscale] Failed to convert APNG ({e}), falling back to static", flush=True)
    elif fmt == DetectedFormat.GIF:
        try:
            return resize_animated_image_to_webp(body, target_width, target_height, is_webp_source=False), "webp"
        except Exception as e:
            print(f"⚠️ [emoji_upscale] Failed to convert GIF ({e}), falling back to static", flush=True)

    # 정적 이미지 처리 (WebP, PNG, 폴백): 디코드 -> 종횡비 유지 160x160 리사이즈 -> WebP 인코드
    return resize_static_image(body, target_width, target_height), "webp"


# ==========================================
# 3. 24시간 TTL 인메모리 캐시 (emote-cdn-rust moka::Cache 대응)
# ==========================================
class EmoteMemoryCache:
    """24시간 TTL과 최대 용량 제한을 지원하는 스레드 안전 인메모리 WebP 캐시."""

    def __init__(self, max_capacity: int = CACHE_MAX_CAPACITY, ttl_seconds: int = CACHE_TTL_SECONDS):
        self.max_capacity = max_capacity
        self.ttl_seconds = ttl_seconds
        self._store: OrderedDict[str, tuple[float, bytes, str]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[tuple[bytes, str]]:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, data, actual_src = entry
            if now >= expires_at:
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return data, actual_src

    def insert(self, key: str, data: bytes, actual_src: str = "") -> None:
        now = time.monotonic()
        with self._lock:
            if key in self._store:
                self._store.pop(key, None)
            self._store[key] = (now + self.ttl_seconds, data, actual_src)
            while len(self._store) > self.max_capacity:
                self._store.popitem(last=False)


GLOBAL_EMOTE_CACHE = EmoteMemoryCache()


# ==========================================
# 4. 다중 이모지(1~3개) 조합 및 호환 헬퍼
# ==========================================
def _extract_rgba_frames(
    raw_bytes: bytes,
    slot_size: int = EMOTE_TARGET_WIDTH,
) -> tuple[list[Image.Image], list[int], int]:
    """단일/다중 이모지 처리를 위해 원본 종횡비를 유지한 160x160 RGBA 프레임 시퀀스를 추출합니다."""
    with Image.open(io.BytesIO(raw_bytes)) as img:
        is_animated = getattr(img, "is_animated", False) and getattr(img, "n_frames", 1) > 1
        if not is_animated:
            return [_resize_rgba(img.convert("RGBA"), slot_size, slot_size)], [100], 0

        loop_count = int(img.info.get("loop", 0) or 0)
        resized_frames: list[Image.Image] = []
        durations: list[int] = []
        for frame in ImageSequence.Iterator(img):
            raw_dur = frame.info.get("duration", img.info.get("duration", 100))
            try:
                dur = max(1, int(round(float(raw_dur))))
            except (ValueError, TypeError):
                dur = 100
            if dur < 10:
                dur = 100
            resized_frames.append(_resize_rgba(frame.convert("RGBA"), slot_size, slot_size))
            durations.append(dur)

    if not resized_frames:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            return [_resize_rgba(img.convert("RGBA"), slot_size, slot_size)], [100], 0
    return resized_frames, durations, loop_count


def _compose_horizontal_sprites(sprites: list[Image.Image], gap: int = MULTI_EMOJI_GAP) -> Image.Image:
    """2~3개의 160x160 리사이징된 이모지를 불필요한 여백 없이 가로로 나란히 배치합니다."""
    items = sprites[:MAX_EMOJIS_PER_MESSAGE]
    if len(items) == 1:
        return items[0]
    total_w = sum(sp.width for sp in items) + gap * (len(items) - 1)
    max_h = max(sp.height for sp in items)
    canvas = Image.new("RGBA", (max(1, total_w), max(1, max_h)), (0, 0, 0, 0))
    cur_x = 0
    for sp in items:
        dy = (max_h - sp.height) // 2
        canvas.alpha_composite(sp, (cur_x, dy))
        cur_x += sp.width + gap
    return canvas


def _sample_frame_at_time(frames: list[Image.Image], durations: list[int], t_ms: int) -> Image.Image:
    if len(frames) == 1:
        return frames[0]
    total = sum(durations) or 100
    pos = t_ms % total
    acc = 0
    for fr, d in zip(frames, durations):
        acc += d
        if pos < acc:
            return fr
    return frames[-1]


def build_sticker_strip_bytes(
    raw_items: list[bytes],
    canvas_w: Optional[int] = None,
    canvas_h: Optional[int] = None,
) -> tuple[bytes, str]:
    """
    1~3개의 커스텀 이모지를 emote-cdn-rust 방식(160x160 종횡비 유지 + Lanczos3 + WebP 출력)으로 변환합니다.
    - 단일 이모지(1개): process_emote_bytes_to_webp를 통해 불필요한 여백 없이 정확한 160x160 종횡비 WebP로 변환
    - 복수 이모지(2~3개): 각 이모지를 160x160 종횡비로 리사이징 후 가로 결합하여 WebP로 인코딩
    """
    if not raw_items:
        raise ValueError("empty raw_items")

    items = raw_items[:MAX_EMOJIS_PER_MESSAGE]
    target_w = canvas_w or EMOTE_TARGET_WIDTH
    target_h = canvas_h or EMOTE_TARGET_HEIGHT

    # 단일 이모지는 emote-cdn-rust 파이프라인 그대로 처리
    if len(items) == 1:
        return process_emote_bytes_to_webp(items[0], target_w, target_h)

    extracted = [_extract_rgba_frames(raw, slot_size=target_w) for raw in items]
    has_anim = any(len(frames) > 1 for frames, _, _ in extracted)

    if not has_anim:
        composed = _compose_horizontal_sprites([frames[0] for frames, _, _ in extracted])
        out = io.BytesIO()
        composed.save(out, format="WEBP", lossless=True, quality=90, method=4)
        return out.getvalue(), "webp"

    anim_entries = [(frames, durs, loop) for frames, durs, loop in extracted if len(frames) > 1]
    if len(anim_entries) == 1 and len(anim_entries[0][0]) <= 60:
        base_frames, out_durations, _ = anim_entries[0]
        canvas_frames_rgba = [
            _compose_horizontal_sprites([
                frames[idx] if len(frames) > 1 else frames[0]
                for frames, _, _ in extracted
            ])
            for idx in range(len(base_frames))
        ]
    else:
        max_total = max(sum(durs) for _, durs, _ in anim_entries)
        step_ms = max(40, max_total // 48)
        n_steps = max(2, min(60, (max_total + step_ms - 1) // step_ms))
        out_durations = [step_ms] * n_steps
        canvas_frames_rgba = [
            _compose_horizontal_sprites([
                _sample_frame_at_time(frames, durs, step * step_ms)
                for frames, durs, _ in extracted
            ])
            for step in range(n_steps)
        ]

    out = io.BytesIO()
    canvas_frames_rgba[0].save(
        out,
        format="WEBP",
        save_all=True,
        append_images=canvas_frames_rgba[1:],
        duration=out_durations,
        loop=0,
        lossless=True,
        quality=70,
        method=4,
        minimize_size=False,
        allow_mixed=True,
    )
    return out.getvalue(), "webp"


def upscale_static_emoji_bytes(raw_bytes: bytes, target_size: int = STATIC_TARGET_SIZE) -> tuple[bytes, str]:
    """단일 정적 이모지를 종횡비 유지 160x160 WebP로 변환합니다."""
    return process_emote_bytes_to_webp(raw_bytes, target_size, target_size)


def upscale_animated_emoji_bytes(raw_bytes: bytes, target_size: int = ANIMATED_TARGET_SIZE) -> tuple[bytes, str]:
    """단일 움직이는 이모지를 종횡비 유지 160x160 애니메이션 WebP로 변환합니다."""
    return process_emote_bytes_to_webp(raw_bytes, target_size, target_size)


def extract_pure_custom_emojis(content: str, max_count: int = MAX_EMOJIS_PER_MESSAGE) -> list[dict]:
    """
    메시지 본문이 오직 커스텀 디스코드 이모지(1~max_count개)와 공백으로만 이루어져 있으면
    각 이모지 메타정보 리스트를 반환하고, 일반 텍스트나 표준 이모지가 섞여 있으면 빈 리스트를 반환합니다.
    """
    if not content:
        return []
    stripped = content.strip()
    if not stripped:
        return []

    matches = list(CUSTOM_EMOJI_RE.finditer(stripped))
    if not matches or len(matches) > max_count:
        return []

    leftover = CUSTOM_EMOJI_RE.sub("", stripped).strip()
    if leftover:
        return []

    result = []
    for m in matches:
        is_anim = (m.group(1) == "a")
        name = m.group(2)
        emoji_id = m.group(3)
        result.append({
            "animated": is_anim,
            "name": name,
            "id": emoji_id,
        })
    return result


def sanitize_webhook_username(display_name: str | None) -> str:
    """
    디스코드 웹훅 username 제약(1~80자, 'discord'/'clyde' 금지어 회피)을 안전하게 준수합니다.
    """
    name = (display_name or "").strip()
    for banned in ("discord", "clyde"):
        pattern = re.compile(re.escape(banned), re.IGNORECASE)
        if pattern.search(name):
            name = pattern.sub(lambda m: m.group(0)[0] + "\u200b" + m.group(0)[1:], name)
    name = name[:80].strip()
    return name or "User"


def is_delete_reaction_emoji(emoji: discord.PartialEmoji | discord.Emoji | str | None) -> bool:
    """사용자가 수동으로 단 빨간 엑스(:x:, ❌) 반응인지 판별합니다."""
    if emoji is None:
        return False
    if isinstance(emoji, str):
        raw_name = emoji
        emoji_id = None
    else:
        emoji_id = getattr(emoji, "id", None)
        raw_name = getattr(emoji, "name", "") or ""
    if emoji_id is not None:
        return False
    normalized = raw_name.replace("\ufe0f", "").strip()
    return normalized == "❌"


# ==========================================
# 5. emote-cdn-rust 호환 HTTP 핸들러 (/emoji/:id, /e/:id, /sticker/:id, /s/:id)
# ==========================================
async def fetch_and_resize_cdn_item(
    session: aiohttp.ClientSession,
    item_id: str,
    content_type: str = "emoji",
) -> Optional[tuple[bytes, str]]:
    """
    Discord CDN에서 이모지/스티커 원본(WebP -> PNG 폴백)을 가져와
    160x160 종횡비 유지 WebP로 리사이징하고 24시간 메모리 캐시에 저장합니다
    (emote-cdn-rust handlers::process_emoji / process_sticker / process_image).
    """
    clean_id = clean_id_from_path(item_id)
    if not validate_id(clean_id):
        return None

    cache_key = f"{content_type}:{clean_id}"
    cached = GLOBAL_EMOTE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if content_type == "sticker":
        src_urls = [
            f"https://media.discordapp.com/stickers/{clean_id}.webp?size=160",
            f"https://media.discordapp.com/stickers/{clean_id}.png?size=160",
        ]
    else:
        # emote-cdn-rust 동일: WebP(?size=160&animated=true) 우선 시도 후 PNG 폴백
        src_urls = [
            f"https://cdn.discordapp.com/emojis/{clean_id}.webp?size=160&animated=true",
            f"https://cdn.discordapp.com/emojis/{clean_id}.png?size=160&animated=true",
        ]

    body: Optional[bytes] = None
    actual_src = ""
    headers = {"User-Agent": USER_AGENT}
    for src_url in src_urls:
        try:
            async with session.get(src_url, headers=headers) as resp:
                if 200 <= resp.status < 300:
                    raw = await resp.read()
                    if raw and len(raw) >= 12:
                        body = raw
                        actual_src = src_url
                        break
        except Exception:
            continue

    if not body:
        return None

    try:
        webp_bytes, _ = await asyncio.to_thread(
            process_emote_bytes_to_webp,
            body,
            EMOTE_TARGET_WIDTH,
            EMOTE_TARGET_HEIGHT,
        )
    except Exception:
        return None

    if not webp_bytes:
        return None

    GLOBAL_EMOTE_CACHE.insert(cache_key, webp_bytes, actual_src)
    return webp_bytes, actual_src


async def handle_emote_cdn_http_request(request: web.Request, content_type: str = "emoji") -> web.Response:
    """
    aiohttp 웹 서버에서 /emoji/{id}, /e/{id}, /sticker/{id}, /s/{id} 요청을 처리합니다
    (emote-cdn-rust handlers::emoji_handler / sticker_handler).
    """
    raw_id = request.match_info.get("id") or request.match_info.get("name") or ""
    clean_id = clean_id_from_path(raw_id)
    if not validate_id(clean_id):
        return web.Response(status=400, text="Invalid ID format")

    signing_key = (os.getenv("SIGNING_KEY") or "").strip()
    if signing_key:
        ex_param = request.query.get("ex")
        hm_param = request.query.get("hm")
        if not verify_signature(clean_id, ex_param, hm_param, signing_key):
            return web.Response(status=401, text="Unauthorized")

    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        res = await fetch_and_resize_cdn_item(session, clean_id, content_type=content_type)

    if res is None:
        return web.Response(status=404, text="Not Found")

    webp_bytes, actual_src = res
    etag = make_etag(webp_bytes)
    default_src = format_sticker_src(clean_id) if content_type == "sticker" else format_emoji_src(clean_id)
    server_hdr = f"emoji-resizer/0.1 ({actual_src or default_src})"
    resp_headers = {
        "Content-Type": "image/webp",
        "Cache-Control": "public, max-age=86400",
        "ETag": etag,
        "Server": server_hdr,
    }
    if request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers=resp_headers)
    return web.Response(body=webp_bytes, status=200, headers=resp_headers)


# ==========================================
# 6. 권한 확인 & 설정 대시보드 UI
# ==========================================
def _is_guild_admin(user: discord.abc.User | discord.Member | None) -> bool:
    if isinstance(user, discord.Member):
        perms = user.guild_permissions
        return bool(perms.administrator or perms.manage_guild)
    return False


async def _can_manage_upscale(bot: commands.Bot, interaction: discord.Interaction) -> bool:
    if _is_guild_admin(interaction.user):
        return True
    if hasattr(bot, "is_bot_owner_user"):
        try:
            return await bot.is_bot_owner_user(interaction.user)
        except Exception:
            pass
    return False


def build_emoji_upscale_embed(
    guild: discord.Guild,
    channel: Optional[discord.abc.GuildChannel | discord.Thread],
    enabled: bool,
) -> discord.Embed:
    status_badge = "🟢 **ON (활성화됨)**" if enabled else "🔴 **OFF (비활성화됨 · 기본값)**"
    desc_lines = [
        "커스텀 디스코드 이모지(1~3개)만 포함된 채팅을 보내면 원본 메시지를 삭제한 뒤,",
        "원본 종횡비를 그대로 유지하며 **`160×160` WebP (Lanczos3 · 정적/애니메이션 WebP · 24시간 캐시)** 포맷으로 리사이징하여",
        "**보낸 사람의 프로필 사진과 서버 닉네임**으로 즉시 전송합니다.",
        "• **🗑️ 삭제 방법:** 전송된 이모지 메시지에 직접 `:x:`(❌) 반응을 추가하면 즉시 삭제됩니다.",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"• **🏠 대상 서버:** `{guild.name}`",
        f"• **⚡ 현재 기능 상태:** {status_badge}",
        "• **🖼️ 리사이징 엔진:** `160×160 WebP` (종횡비 유지 · Lanczos3 · Animated WebP 지원)",
        "• **🛡️ 변경 가능 권한:** 서버 관리자 (`Administrator` / `서버 관리`)",
        "• **🔒 기본 동작 정책:** 모든 서버 최초 기본값은 **OFF**입니다.",
    ]

    if channel and guild.me and hasattr(channel, "permissions_for"):
        perms = channel.permissions_for(guild.me)
        missing = []
        if not perms.manage_messages:
            missing.append("메시지 관리(`Manage Messages` - 원본 이모지 삭제용)")
        if not perms.manage_webhooks:
            missing.append("웹후크 관리(`Manage Webhooks` - 발신자 프로필 재전송용)")
        if not perms.attach_files:
            missing.append("파일 첨부(`Attach Files` - WebP 이모지 업로드용)")
        if missing:
            desc_lines.append("")
            desc_lines.append("⚠️ **현재 채널 봇 권한 확인 필요:**")
            for m in missing:
                desc_lines.append(f"  - ❌ `{m}`")
        else:
            desc_lines.append("• **🤖 현재 채널 봇 권한:** ✅ 정상 작동 가능 (메시지 관리 · 웹후크 · 파일 첨부 보유)")

    desc_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    embed = discord.Embed(
        title="🔍 커스텀 이모지 160×160 WebP 리사이저 설정",
        description="\n".join(desc_lines),
        color=discord.Color.from_rgb(87, 242, 135) if enabled else discord.Color.from_rgb(149, 165, 166),
        timestamp=datetime.datetime.now(core.KST),
    )
    embed.set_footer(text="서버 관리자만 아래 버튼 또는 /이모지업스케일 명령어로 ON/OFF를 전환할 수 있습니다.")
    return embed


class EmojiUpscaleConfigView(core.SafeView):
    """서버 관리자 전용 이모지 업스케일 ON/OFF 제어 뷰"""

    def __init__(self, bot: Optional[commands.Bot] = None, guild_id: int = 0):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self._sync_buttons()

    def _sync_buttons(self):
        enabled = core.is_emoji_upscale_enabled(self.guild_id) if self.guild_id else False
        self.btn_enable.disabled = enabled
        self.btn_disable.disabled = not enabled

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await super().interaction_check(interaction)
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return False
        if not self.guild_id:
            self.guild_id = interaction.guild.id
        bot_ref = self.bot or interaction.client
        if not await _can_manage_upscale(bot_ref, interaction):
            await core.safe_send_response(
                interaction,
                "🚨 **권한 부족:** 이모지 업스케일 설정은 **서버 관리자(Administrator / 서버 관리)**만 변경할 수 있습니다.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="🟢 업스케일 켜기 (ON)", style=discord.ButtonStyle.success, row=0)
    async def btn_enable(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        gid = self.guild_id or interaction.guild_id
        await asyncio.to_thread(core.set_emoji_upscale_enabled, gid, True)
        self._sync_buttons()
        emb = build_emoji_upscale_embed(interaction.guild, interaction.channel, True)
        await core.safe_edit_response(interaction, embed=emb, view=self)

    @discord.ui.button(label="🔴 업스케일 끄기 (OFF)", style=discord.ButtonStyle.danger, row=0)
    async def btn_disable(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        gid = self.guild_id or interaction.guild_id
        await asyncio.to_thread(core.set_emoji_upscale_enabled, gid, False)
        self._sync_buttons()
        emb = build_emoji_upscale_embed(interaction.guild, interaction.channel, False)
        await core.safe_edit_response(interaction, embed=emb, view=self)


# ==========================================
# 7. EmojiUpscaleCog 메인 클래스
# ==========================================
class EmojiUpscaleCog(commands.Cog, name="이모지업스케일"):
    """서버별 커스텀 이모지 160x160 WebP 리사이징 & 발신자 프로필 대리 전송 모듈"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._webhook_cache: dict[int, discord.Webhook] = {}
        self._webhook_locks: dict[int, asyncio.Lock] = {}
        self._processed_msgs: OrderedDict[int, float] = OrderedDict()
        self._upscaled_messages: OrderedDict[int, int] = OrderedDict()
        self._deleting_msgs: set[int] = set()

    async def cog_unload(self):
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        self._http_session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            timeout = aiohttp.ClientTimeout(total=12)
            connector = aiohttp.TCPConnector(limit_per_host=32, keepalive_timeout=30.0)
            self._http_session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={"User-Agent": USER_AGENT},
            )
        return self._http_session

    async def _download_emoji_bytes(self, emoji_id: str, animated: bool = False) -> Optional[bytes]:
        """emote-cdn-rust와 동일하게 Discord CDN에서 WebP(?size=160&animated=true), PNG 순으로 다운로드합니다."""
        clean_id = clean_id_from_path(emoji_id)
        if not validate_id(clean_id):
            return None
        session = await self._get_session()
        urls = [
            f"https://cdn.discordapp.com/emojis/{clean_id}.webp?size=160&animated=true",
            f"https://cdn.discordapp.com/emojis/{clean_id}.png?size=160&animated=true",
        ]
        if animated:
            urls.append(f"https://cdn.discordapp.com/emojis/{clean_id}.gif?size=160")

        for url in urls:
            try:
                async with session.get(url) as resp:
                    if 200 <= resp.status < 300:
                        raw = await resp.read()
                        if raw and len(raw) >= 12:
                            return raw
            except Exception:
                continue
        return None

    async def _build_sticker_strip_file(self, emojis: list[dict]) -> Optional[discord.File]:
        items = emojis[:MAX_EMOJIS_PER_MESSAGE]
        if not items:
            return None

        session = await self._get_session()
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", items[0]["name"])[:48] or "emoji"

        # 단일 이모지는 24시간 TTL 인메모리 캐시(fetch_and_resize_cdn_item)를 즉시 활용
        if len(items) == 1:
            res = await fetch_and_resize_cdn_item(session, items[0]["id"], content_type="emoji")
            if not res:
                return None
            webp_bytes, _ = res
            if not webp_bytes or len(webp_bytes) > MAX_UPLOAD_BYTES:
                return None
            return discord.File(io.BytesIO(webp_bytes), filename=f"{safe_name}.webp")

        # 복수 이모지(2~3개)도 조합 키로 24시간 캐시 지원
        combo_key = "combo:" + "+".join(clean_id_from_path(em["id"]) for em in items)
        cached_combo = GLOBAL_EMOTE_CACHE.get(combo_key)
        if cached_combo is not None:
            webp_bytes, _ = cached_combo
            return discord.File(io.BytesIO(webp_bytes), filename=f"{safe_name}.webp")

        raw_list: list[bytes] = []
        for em in items:
            raw = await self._download_emoji_bytes(em["id"], em["animated"])
            if not raw:
                return None
            raw_list.append(raw)

        out_bytes, ext = await asyncio.to_thread(build_sticker_strip_bytes, raw_list)
        if not out_bytes or len(out_bytes) > MAX_UPLOAD_BYTES:
            return None

        GLOBAL_EMOTE_CACHE.insert(combo_key, out_bytes, "combo")
        return discord.File(io.BytesIO(out_bytes), filename=f"{safe_name}.{ext}")

    async def _get_or_create_webhook(self, base_channel: discord.abc.GuildChannel) -> Optional[discord.Webhook]:
        cached = self._webhook_cache.get(base_channel.id)
        if cached is not None:
            return cached

        if len(self._webhook_locks) > 500:
            for k in list(self._webhook_locks.keys())[:100]:
                if not self._webhook_locks[k].locked():
                    self._webhook_locks.pop(k, None)
        lock = self._webhook_locks.setdefault(base_channel.id, asyncio.Lock())
        async with lock:
            cached = self._webhook_cache.get(base_channel.id)
            if cached is not None:
                return cached

            try:
                webhooks = await base_channel.webhooks()
                existing = next((w for w in webhooks if w.name == WEBHOOK_NAME and w.token), None)
                if not existing:
                    existing = next(
                        (w for w in webhooks if w.user and self.bot.user and w.user.id == self.bot.user.id and w.token),
                        None,
                    )
                if not existing:
                    existing = await base_channel.create_webhook(name=WEBHOOK_NAME, reason="이모지 업스케일 대리 전송용 웹훅")
                if len(self._webhook_cache) >= 500:
                    self._webhook_cache.pop(next(iter(self._webhook_cache)), None)
                self._webhook_cache[base_channel.id] = existing
                return existing
            except Exception:
                return None

    def _mark_processed(self, msg_id: int) -> bool:
        """이미 처리 중이거나 처리된 메시지 ID면 False를 반환합니다."""
        if msg_id in self._processed_msgs:
            return False
        self._processed_msgs[msg_id] = datetime.datetime.now().timestamp()
        while len(self._processed_msgs) > 1000:
            self._processed_msgs.popitem(last=False)
        return True

    def _record_upscaled_message(self, webhook_msg_id: int, author_id: int):
        self._upscaled_messages[webhook_msg_id] = author_id
        while len(self._upscaled_messages) > 1000:
            self._upscaled_messages.popitem(last=False)
        rec_fn = getattr(core, "record_emoji_upscale_message", None)
        if callable(rec_fn):
            async def _persist():
                try:
                    await asyncio.to_thread(rec_fn, webhook_msg_id, author_id)
                except Exception:
                    pass
            try:
                asyncio.create_task(_persist())
            except Exception:
                pass

    def _get_upscaled_author_id(self, message_id: int) -> Optional[int]:
        if message_id in self._upscaled_messages:
            return self._upscaled_messages[message_id]
        get_fn = getattr(core, "get_emoji_upscale_message_author", None)
        if callable(get_fn):
            try:
                uid = get_fn(message_id)
                if uid is not None:
                    self._upscaled_messages[message_id] = int(uid)
                    return int(uid)
            except Exception:
                pass
        return None

    def _forget_upscaled_message(self, message_id: int):
        self._upscaled_messages.pop(message_id, None)
        rem_fn = getattr(core, "remove_emoji_upscale_message", None)
        if callable(rem_fn):
            async def _cleanup():
                try:
                    await asyncio.to_thread(rem_fn, message_id)
                except Exception:
                    pass
            try:
                asyncio.create_task(_cleanup())
            except Exception:
                pass

    async def _is_upscale_webhook_message(
        self,
        base_channel: discord.abc.GuildChannel,
        webhook_id: Optional[int],
    ) -> bool:
        if not webhook_id:
            return False
        cached = self._webhook_cache.get(base_channel.id)
        if cached and getattr(cached, "id", None) == webhook_id:
            return True
        try:
            webhooks = await base_channel.webhooks()
            for w in webhooks:
                if w.id == webhook_id:
                    if w.name == WEBHOOK_NAME or (self.bot.user and w.user and w.user.id == self.bot.user.id):
                        if w.token:
                            self._webhook_cache[base_channel.id] = w
                        return True
        except Exception:
            pass
        return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 봇, 웹훅, DM, 시스템 메시지, 첨부파일·스티커 포함 메시지 즉시 무시
        if message.author.bot or message.webhook_id is not None:
            return
        if not message.guild:
            return
        if message.type not in (discord.MessageType.default, discord.MessageType.reply):
            return
        if message.attachments or message.stickers:
            return

        if not message.content or "<" not in message.content or ":" not in message.content:
            return

        # 서버 설정 확인 (기본값 OFF)
        if not core.is_emoji_upscale_enabled(message.guild.id):
            return

        # 순수 커스텀 이모지 메시지(1~3개)인지 검사
        emojis = extract_pure_custom_emojis(message.content)
        if not emojis:
            return

        # 중복 이벤트 방어
        if not self._mark_processed(message.id):
            return

        channel = message.channel
        base_channel = channel.parent if isinstance(channel, discord.Thread) else channel
        if base_channel is None or not hasattr(base_channel, "webhooks"):
            return

        me = message.guild.me
        if not me:
            return
        perms = channel.permissions_for(me)
        if not (perms.manage_messages and perms.manage_webhooks and perms.send_messages and perms.attach_files):
            return

        # 1. 이모지 다운로드 및 160x160 종횡비 유지 WebP 리사이즈 수행 (실패 시 원본 메시지를 절대 삭제하지 않음)
        try:
            sticker_file = await self._build_sticker_strip_file(emojis)
            if not sticker_file:
                return
        except Exception as e:
            print(f"⚠️ [이모지 업스케일 변환 예외] {e}", flush=True)
            return

        # 2. 웹훅 준비
        webhook = await self._get_or_create_webhook(base_channel)
        if not webhook:
            return

        # 3. 원본 메시지 삭제
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

        # 4. 보낸 사람 프로필 사진 & 닉네임으로 웹훅 전송
        sender_name = sanitize_webhook_username(message.author.display_name)
        sender_avatar = message.author.display_avatar.url if hasattr(message.author, "display_avatar") else None
        send_kwargs = {
            "file": sticker_file,
            "username": sender_name,
            "avatar_url": sender_avatar,
            "allowed_mentions": discord.AllowedMentions.none(),
            "wait": True,
        }
        if isinstance(channel, discord.Thread):
            send_kwargs["thread"] = channel

        sent_msg = None
        try:
            sent_msg = await webhook.send(**send_kwargs)
        except discord.NotFound:
            self._webhook_cache.pop(base_channel.id, None)
            fresh_webhook = await self._get_or_create_webhook(base_channel)
            if not fresh_webhook:
                return
            try:
                try:
                    sticker_file.fp.seek(0)
                except Exception:
                    pass
                sent_msg = await fresh_webhook.send(**send_kwargs)
            except Exception as retry_err:
                print(f"⚠️ [이모지 업스케일 웹훅 재전송 실패] {retry_err}", flush=True)
        except Exception as send_err:
            print(f"⚠️ [이모지 업스케일 웹훅 전송 실패] {send_err}", flush=True)

        if sent_msg and getattr(sent_msg, "id", None):
            self._record_upscaled_message(int(sent_msg.id), int(message.author.id))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """사용자가 업스케일된 이모지 메시지에 직접 :x:(❌) 반응을 추가하면 해당 이모지 메시지를 삭제합니다."""
        if not payload.guild_id:
            return
        if self.bot.user and payload.user_id == self.bot.user.id:
            return
        if payload.member and getattr(payload.member, "bot", False):
            return
        if not is_delete_reaction_emoji(payload.emoji):
            return
        if payload.message_id in self._deleting_msgs:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        member = payload.member or guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except Exception:
                member = None
        if member and getattr(member, "bot", False):
            return

        is_mod = False
        if isinstance(member, discord.Member):
            perms = member.guild_permissions
            is_mod = bool(perms.administrator or perms.manage_guild or perms.manage_messages)
        is_owner = False
        if member and hasattr(self.bot, "is_bot_owner_user"):
            try:
                is_owner = await self.bot.is_bot_owner_user(member)
            except Exception:
                is_owner = False

        author_id = self._get_upscaled_author_id(payload.message_id)

        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(payload.channel_id)
            except Exception:
                return
        if channel is None:
            return

        base_channel = channel.parent if isinstance(channel, discord.Thread) else channel
        if base_channel is None:
            return

        target_msg = None
        if author_id is not None:
            if not (payload.user_id == author_id or is_mod or is_owner):
                return
        else:
            if not core.is_emoji_upscale_enabled(payload.guild_id):
                return
            try:
                target_msg = await channel.fetch_message(payload.message_id)
            except Exception:
                return
            if not target_msg or target_msg.webhook_id is None:
                return
            if not await self._is_upscale_webhook_message(base_channel, target_msg.webhook_id):
                return
            if not (is_mod or is_owner):
                return

        self._deleting_msgs.add(payload.message_id)
        try:
            deleted = False
            try:
                if target_msg is not None:
                    await target_msg.delete()
                else:
                    await channel.get_partial_message(payload.message_id).delete()
                deleted = True
            except discord.NotFound:
                deleted = True
            except (discord.Forbidden, discord.HTTPException):
                deleted = False

            if not deleted and hasattr(base_channel, "webhooks"):
                webhook = await self._get_or_create_webhook(base_channel)
                if webhook:
                    del_kwargs = {"thread": channel} if isinstance(channel, discord.Thread) else {}
                    try:
                        await webhook.delete_message(payload.message_id, **del_kwargs)
                        deleted = True
                    except discord.NotFound:
                        deleted = True
                    except Exception:
                        pass

            if deleted:
                self._forget_upscaled_message(payload.message_id)
        finally:
            self._deleting_msgs.discard(payload.message_id)

    @app_commands.command(name="이모지업스케일", description="[서버 관리자 전용] 커스텀 이모지 자동 업스케일 기능을 켜거나 끕니다 (기본값: OFF).")
    @app_commands.guild_only()
    @app_commands.describe(동작="기능 켜기(ON) · 끄기(OFF) · 현재 상태 및 토글 패널 보기")
    @app_commands.choices(동작=[
        app_commands.Choice(name="🟢 켜기 (ON)", value="on"),
        app_commands.Choice(name="🔴 끄기 (OFF)", value="off"),
        app_commands.Choice(name="⚙️ 현재 상태 확인 / 버튼으로 설정", value="status"),
    ])
    async def emoji_upscale_cmd(
        self,
        interaction: discord.Interaction,
        동작: Optional[app_commands.Choice[str]] = None,
    ):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 이 명령어는 디스코드 서버 내에서만 사용할 수 있습니다.", ephemeral=True)
            return

        if not await _can_manage_upscale(self.bot, interaction):
            await core.safe_send_response(
                interaction,
                "🚨 **권한 부족:** `/이모지업스케일` 명령어는 **서버 관리자(Administrator / 서버 관리)**만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        await core.safe_defer(interaction, ephemeral=True)
        mode = 동작.value if 동작 else "status"
        if mode == "on":
            enabled = await asyncio.to_thread(core.set_emoji_upscale_enabled, interaction.guild.id, True)
        elif mode == "off":
            enabled = await asyncio.to_thread(core.set_emoji_upscale_enabled, interaction.guild.id, False)
        else:
            enabled = core.is_emoji_upscale_enabled(interaction.guild.id)

        view = EmojiUpscaleConfigView(bot=self.bot, guild_id=interaction.guild.id)
        emb = build_emoji_upscale_embed(interaction.guild, interaction.channel, enabled)
        await interaction.followup.send(embed=emb, view=view, ephemeral=True)

    @commands.command(name="이모지업스케일", aliases=["emojiupscale", "이모지확대"])
    @commands.guild_only()
    async def prefix_emoji_upscale(self, ctx: commands.Context, 동작: Optional[str] = None):
        is_owner = await self.bot.is_bot_owner_user(ctx.author) if hasattr(self.bot, "is_bot_owner_user") else False
        if not (_is_guild_admin(ctx.author) or is_owner):
            await ctx.reply("🚨 **권한 부족:** 서버 관리자(Administrator / 서버 관리)만 사용할 수 있습니다.", delete_after=8)
            return

        arg = (동작 or "").strip().lower()
        if arg in ("on", "켜기", "활성", "활성화", "true", "1"):
            enabled = await asyncio.to_thread(core.set_emoji_upscale_enabled, ctx.guild.id, True)
        elif arg in ("off", "끄기", "비활성", "비활성화", "false", "0"):
            enabled = await asyncio.to_thread(core.set_emoji_upscale_enabled, ctx.guild.id, False)
        else:
            enabled = core.is_emoji_upscale_enabled(ctx.guild.id)

        view = EmojiUpscaleConfigView(bot=self.bot, guild_id=ctx.guild.id)
        emb = build_emoji_upscale_embed(ctx.guild, ctx.channel, enabled)
        await ctx.send(embed=emb, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(EmojiUpscaleCog(bot))
