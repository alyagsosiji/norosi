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
import socket
import struct
import threading
import time
from collections import OrderedDict
from typing import Awaitable, Callable, Optional
import urllib.parse

import aiohttp
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageSequence

import core

# 순수 커스텀 이모지 메시지(1~3개, 앞뒤 공백 및 모바일 제로폭 문자 허용) 매칭용 정규식
CUSTOM_EMOJI_RE = re.compile(r"<(a?):([^:>\s]{1,64}):(\d{15,25})>")
INVISIBLE_CHARS_RE = re.compile(r"[\s\u200b-\u200d\u2060\ufeff\ufe0e\ufe0f\u00a0\u2800]+")
BRAILLE_BLANK = "\u2800"  # '⠀' 마스킹 링크([⠀](url))용 점자 공백 문자

MAX_EMOJIS_PER_MESSAGE = 3
# emote-cdn-rust 표준: 투명 여백 없이 원본 종횡비를 100% 유지하는 160x160 리사이징 박스
EMOTE_TARGET_WIDTH = 160
EMOTE_TARGET_HEIGHT = 160
EMOTE_CDN_DEFAULT_PORT = 53292  # Kamilake/emote-cdn-rust 기본 바인딩 포트
STICKER_TARGET_SIZE = EMOTE_TARGET_WIDTH
DOUBLE_SLOT_SIZE = EMOTE_TARGET_WIDTH
TRIPLE_SLOT_SIZE = EMOTE_TARGET_WIDTH
EMOJI_SLOT_SIZE = EMOTE_TARGET_WIDTH
STATIC_TARGET_SIZE = EMOTE_TARGET_WIDTH
ANIMATED_TARGET_SIZE = EMOTE_TARGET_WIDTH
MULTI_EMOJI_GAP = 8

MAX_UPLOAD_BYTES = 24 * 1024 * 1024  # Discord 25MB 제한 안전 마진
WEBHOOK_NAME = "norosi-emoji-upscale"
USER_AGENT = "emoji-resizer/0.1 (+https://example.local) reqwest/0.12"
CACHE_TTL_SECONDS = 24 * 3600  # 24시간 TTL (emote-cdn-rust 동일)
CACHE_MAX_CAPACITY = 50000     # 인메모리 WebP 바이트 캐시 엔트리 상한 (emote-cdn-rust 동일)
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


def _compose_horizontal_sprites(
    sprites: list[Image.Image],
    gap: int = MULTI_EMOJI_GAP,
) -> Image.Image:
    """
    투명 여백 패딩 없이 1~3개의 160x160 종횡비 유지 리사이징된 이모지를 원본 비율 그대로 배치합니다.
    - 1개: 원본 종횡비가 유지된(최대 160x160) 이미지를 투명 패딩 없이 그대로 반환
    - 2~3개: 각 이모지의 종횡비를 유지한 채 가로로만 나란히 결합
    """
    items = sprites[:MAX_EMOJIS_PER_MESSAGE]
    if not items:
        return Image.new("RGBA", (EMOTE_TARGET_WIDTH, EMOTE_TARGET_HEIGHT), (0, 0, 0, 0))
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
    1~3개의 커스텀 이모지를 투명 캔버스 패딩 없이 emote-cdn-rust 방식(160x160 종횡비 유지 + Lanczos3 + WebP 출력)으로 변환합니다.
    - 단일 이모지(1개): process_emote_bytes_to_webp를 통해 투명 패딩 없이 정확한 원본 종횡비(최대 160x160) WebP로 변환
    - 복수 이모지(2~3개): 각 이모지를 160x160 종횡비로 리사이징 후 가로 결합하여 WebP로 인코딩
    """
    if not raw_items:
        raise ValueError("empty raw_items")

    items = raw_items[:MAX_EMOJIS_PER_MESSAGE]
    target_w = canvas_w or EMOTE_TARGET_WIDTH
    target_h = canvas_h or EMOTE_TARGET_HEIGHT

    # 단일 이모지는 emote-cdn-rust 파이프라인(투명 패딩 없음, 종횡비 100% 유지 160x160 WebP) 그대로 처리
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
            _compose_horizontal_sprites(
                [
                    frames[idx] if len(frames) > 1 else frames[0]
                    for frames, _, _ in extracted
                ]
            )
            for idx in range(len(base_frames))
        ]
    else:
        max_total = max(sum(durs) for _, durs, _ in anim_entries)
        step_ms = max(40, max_total // 48)
        n_steps = max(2, min(60, (max_total + step_ms - 1) // step_ms))
        out_durations = [step_ms] * n_steps
        canvas_frames_rgba = [
            _compose_horizontal_sprites(
                [
                    _sample_frame_at_time(frames, durs, step * step_ms)
                    for frames, durs, _ in extracted
                ]
            )
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
    webp_bytes = out.getvalue()
    if len(webp_bytes) > MAX_UPLOAD_BYTES:
        out_lossy = io.BytesIO()
        canvas_frames_rgba[0].save(
            out_lossy,
            format="WEBP",
            save_all=True,
            append_images=canvas_frames_rgba[1:],
            duration=out_durations,
            loop=0,
            lossless=False,
            quality=75,
            method=4,
            minimize_size=False,
        )
        webp_bytes = out_lossy.getvalue()
    return webp_bytes, "webp"


def upscale_static_emoji_bytes(raw_bytes: bytes, target_size: int = STATIC_TARGET_SIZE) -> tuple[bytes, str]:
    """단일 정적 이모지를 종횡비 유지 160x160 WebP로 변환합니다."""
    return process_emote_bytes_to_webp(raw_bytes, target_size, target_size)


def upscale_animated_emoji_bytes(raw_bytes: bytes, target_size: int = ANIMATED_TARGET_SIZE) -> tuple[bytes, str]:
    """단일 움직이는 이모지를 종횡비 유지 160x160 애니메이션 WebP로 변환합니다."""
    return process_emote_bytes_to_webp(raw_bytes, target_size, target_size)


def get_emote_cdn_base_url() -> str:
    """
    emote-cdn-rust 호환 외부 CDN 베이스 URL을 반환합니다.
    우선순위: 환경변수(EMOTE_CDN_BASE_URL / KAMIBOT_CDN_URL) -> DB 설정(settings.emote_cdn_base_url) -> 기본값(https://cdn.kamibot.app)
    """
    for env_key in ("EMOTE_CDN_BASE_URL", "KAMIBOT_CDN_URL", "CDN_BASE_URL"):
        env_val = (os.getenv(env_key) or "").strip().rstrip("/")
        if env_val.startswith(("http://", "https://")):
            return env_val
    try:
        data = core.get_cached_data_ro()
        cfg_url = str(core.as_dict(data.get("settings")).get("emote_cdn_base_url") or "").strip().rstrip("/")
        if cfg_url.startswith(("http://", "https://")):
            return cfg_url
    except Exception:
        pass
    return "https://cdn.kamibot.app"


def get_emote_cdn_signing_key() -> str:
    """SIGNING_KEY 환경변수 또는 DB 설정에서 HMAC-SHA256 서명 키를 조회합니다."""
    for env_key in ("SIGNING_KEY", "EMOTE_CDN_SIGNING_KEY"):
        env_val = (os.getenv(env_key) or "").strip()
        if env_val:
            return env_val
    try:
        data = core.get_cached_data_ro()
        return str(core.as_dict(data.get("settings")).get("emote_cdn_signing_key") or "").strip()
    except Exception:
        return ""


def sign_emote_id(clean_id: str, signing_key: str, ttl_seconds: int = CACHE_TTL_SECONDS) -> tuple[int, str]:
    """
    emote-cdn-rust (src/auth/mod.rs) 호환 HMAC-SHA256 서명(ex, hm)을 생성합니다.
    페이로드: "{id}.{exp}", 인코딩: URL_SAFE_NO_PAD base64.
    """
    exp = int(time.time()) + max(60, int(ttl_seconds))
    payload = f"{clean_id}.{exp}".encode("utf-8")
    digest = hmac.new(signing_key.encode("utf-8"), payload, hashlib.sha256).digest()
    hm = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return exp, hm


def generate_emote_cdn_url(
    item_id: str,
    content_type: str = "emoji",
    dup_index: int = 0,
    base_url: Optional[str] = None,
) -> str:
    """
    emote-cdn-rust 엔드포인트 URL(/e/{id}.webp 또는 /s/{id}.webp)을 생성합니다.
    - SIGNING_KEY가 설정된 경우 ?ex={exp}&hm={hm} 쿼리 파라미터를 자동 부착합니다.
    - 한 메시지에 동일 이모지가 여러 번 포함된 경우 dup_index로 URL 중복 언펄 생략을 방지합니다.
    """
    clean_id = clean_id_from_path(item_id)
    cdn_base = (base_url or get_emote_cdn_base_url()).strip().rstrip("/")
    route_prefix = "s" if content_type == "sticker" else "e"
    url = f"{cdn_base}/{route_prefix}/{clean_id}.webp"

    params: list[str] = []
    signing_key = get_emote_cdn_signing_key()
    if signing_key:
        exp, hm = sign_emote_id(clean_id, signing_key)
        params.append(f"ex={exp}")
        params.append(f"hm={hm}")
    if dup_index > 0:
        params.append(f"v={dup_index}")

    if params:
        url = f"{url}?{'&'.join(params)}"
    return url


def generate_wsrv_emote_webp_url(
    item_id: str,
    actual_src: str = "",
    content_type: str = "emoji",
    dup_index: int = 0,
) -> str:
    """
    외부 emote-cdn-rust 서버에 SIGNING_KEY가 설정되어 있지 않은 환경에서도
    emote-cdn-rust와 동일하게 투명 여백 없이 원본 종횡비를 유지한 160x160 Lanczos3 WebP(애니메이션 포함)를
    제공하는 공개 .webp CDN 엔드포인트 URL을 생성합니다.
    """
    clean_id = clean_id_from_path(item_id)
    if actual_src and actual_src.startswith(("http://", "https://")):
        src = actual_src
    elif content_type == "sticker":
        src = f"https://media.discordapp.net/stickers/{clean_id}.png?size=160"
    else:
        src = f"https://cdn.discordapp.com/emojis/{clean_id}.webp?size=160&animated=true"

    quoted_src = urllib.parse.quote(src, safe="")
    url = (
        f"https://wsrv.nl/{clean_id}.webp"
        f"?url={quoted_src}&w={EMOTE_TARGET_WIDTH}&h={EMOTE_TARGET_HEIGHT}&fit=inside&output=webp&n=-1"
    )
    if dup_index > 0:
        url = f"{url}&v={dup_index}"
    return url


def extract_pure_custom_emojis(content: str, max_count: int = MAX_EMOJIS_PER_MESSAGE) -> list[dict]:
    """
    메시지 본문이 오직 커스텀 디스코드 이모지(1~max_count개)와 공백(모바일 제로폭/변형 선택자 포함)으로만 이루어져 있으면
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

    leftover = INVISIBLE_CHARS_RE.sub("", CUSTOM_EMOJI_RE.sub("", stripped))
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


_FRESH_AUTHOR_CACHE: OrderedDict[tuple[int, int], tuple[float, object]] = OrderedDict()
_FRESH_AUTHOR_TTL_SECONDS = 180.0
_FRESH_AUTHOR_MAX_ENTRIES = 2000
_PREFER_EXTERNAL_AVATAR_PROXY = False
_WEBHOOK_AVATAR_EDIT_LOCKS: dict[int, asyncio.Lock] = {}
_WEBHOOK_UPLOADED_AVATAR_STATE: dict[int, tuple[int, str]] = {}
_MAX_AVATAR_DOWNLOAD_BYTES = 2 * 1024 * 1024


def invalidate_fresh_author_cache(user_id: int, guild_id: Optional[int] = None) -> None:
    """멤버/유저 프로필이 변경되었을 때 캐시된 최신 Member 정보를 즉시 무효화합니다."""
    if guild_id is not None:
        _FRESH_AUTHOR_CACHE.pop((int(guild_id), int(user_id)), None)
        return
    uid = int(user_id)
    for k in [key for key in _FRESH_AUTHOR_CACHE.keys() if key[1] == uid]:
        _FRESH_AUTHOR_CACHE.pop(k, None)


async def resolve_fresh_author(
    guild: Optional[discord.Guild],
    author: object,
    *,
    force_refresh: bool = False,
) -> object:
    """
    discord.py의 Member._update_from_message()는 서버 전용 프사(guild_avatar) 해시를
    자동 갱신하지 않아 삭제/변경된 옛 guild_avatar URL(404 -> Clyde 폴백)이 남을 수 있습니다.
    짧은 TTL(3분)로 guild.fetch_member() 결과를 캐싱해 항상 최신 서버/전역 프사를 보장합니다.
    """
    uid = getattr(author, "id", None)
    gid = getattr(guild, "id", None) if guild is not None else None
    if not uid or not gid or not hasattr(guild, "fetch_member"):
        return author

    cache_key = (int(gid), int(uid))
    now = time.monotonic()
    if not force_refresh:
        cached = _FRESH_AUTHOR_CACHE.get(cache_key)
        if cached is not None:
            ts, cached_member = cached
            if (now - ts) < _FRESH_AUTHOR_TTL_SECONDS:
                _FRESH_AUTHOR_CACHE.move_to_end(cache_key)
                return cached_member
            _FRESH_AUTHOR_CACHE.pop(cache_key, None)

    try:
        fresh = await asyncio.wait_for(guild.fetch_member(int(uid)), timeout=3.0)
        if fresh is not None:
            _FRESH_AUTHOR_CACHE[cache_key] = (now, fresh)
            _FRESH_AUTHOR_CACHE.move_to_end(cache_key)
            while len(_FRESH_AUTHOR_CACHE) > _FRESH_AUTHOR_MAX_ENTRIES:
                _FRESH_AUTHOR_CACHE.popitem(last=False)
            return fresh
    except Exception:
        pass
    return author


def _clean_discord_avatar_url(asset: object) -> Optional[str]:
    """
    Discord 웹훅 avatar_url 규격에 맞춰 쿼리 스트링(?size=...)이 없는 정적 .png CDN URL을 반환합니다.
    기본 아바타(/embed/avatars/{idx}.png)에는 절대 ?size 파라미터를 붙이지 않습니다.
    """
    if asset is None:
        return None
    raw_url = getattr(asset, "url", None)
    if not raw_url or not isinstance(raw_url, str):
        return None
    base = raw_url.split("?", 1)[0].strip()
    if not base:
        return None
    if "/embed/avatars/" in base:
        return base
    lower = base.lower()
    for ext in (".gif", ".webp", ".jpeg", ".jpg"):
        if lower.endswith(ext):
            base = base[: -len(ext)] + ".png"
            break
    return base


def _build_wsrv_avatar_url(cdn_png_url: str) -> str:
    """Discord 웹훅 서버가 cdn.discordapp.com 직호출을 누락할 때 사용하는 256x256 정적 .png 프록시 URL."""
    fetch_src = cdn_png_url
    if "/embed/avatars/" not in cdn_png_url and "?" not in cdn_png_url:
        fetch_src = f"{cdn_png_url}?size=256"
    tag = hashlib.sha1(cdn_png_url.encode("utf-8")).hexdigest()[:12]
    encoded = urllib.parse.quote(fetch_src, safe="")
    return f"https://wsrv.nl/av_{tag}.png?url={encoded}&w=256&h=256&fit=cover&output=png"


def build_webhook_avatar_candidates(author: object) -> tuple[list[str], bool]:
    """
    웹훅 대리 전송용 아바타 후보 URL 목록과 커스텀 아바타 보유 여부를 반환합니다.
    - 1024px 초과 아바타의 무음 드롭을 막기 위해 `?size=256` 정적 PNG와 `wsrv.nl/av_{tag}.png` 프록시를 함께 제공합니다.
    - 이전에 Discord가 cdn.discordapp.com 직호출을 드롭/404 처리한 적이 있으면 wsrv PNG를 최우선으로 배치합니다.
    """
    guild_av = getattr(author, "guild_avatar", None)
    global_av = getattr(author, "avatar", None)
    display_av = getattr(author, "display_avatar", None)
    default_av = getattr(author, "default_avatar", None)

    custom_assets: list[object] = []
    if guild_av is not None:
        custom_assets.append(guild_av)
    if global_av is not None:
        custom_assets.append(global_av)
    if not custom_assets and display_av is not None:
        disp_clean = _clean_discord_avatar_url(display_av)
        if disp_clean and "/embed/avatars/" not in disp_clean:
            custom_assets.append(display_av)

    has_custom_avatar = bool(custom_assets)
    candidates: list[str] = []

    def _add(url: Optional[str]) -> None:
        if url and url not in candidates:
            candidates.append(url)

    for asset in custom_assets:
        clean_png = _clean_discord_avatar_url(asset)
        if not clean_png:
            continue
        sized_png = f"{clean_png}?size=256" if "/embed/avatars/" not in clean_png else clean_png
        wsrv_png = _build_wsrv_avatar_url(clean_png)
        if _PREFER_EXTERNAL_AVATAR_PROXY:
            _add(wsrv_png)
            _add(sized_png)
            _add(clean_png)
        else:
            _add(sized_png)
            _add(wsrv_png)
            _add(clean_png)

    _add(_clean_discord_avatar_url(default_av))
    if not candidates:
        _add(_clean_discord_avatar_url(display_av))
    return candidates, has_custom_avatar


def resolve_webhook_avatar_url(author: object) -> Optional[str]:
    """웹훅/임베드에서 기본 프사(Clyde) 폴백을 막기 위해 서버/전역 프로필을 안정적인 PNG URL로 반환합니다."""
    candidates, _ = build_webhook_avatar_candidates(author)
    return candidates[0] if candidates else None


def _normalize_avatar_to_png_bytes(raw: bytes) -> Optional[bytes]:
    """다운로드한 아바타 이미지를 256x256 이하 정적 PNG 바이트로 정규화합니다."""
    if not raw or len(raw) > _MAX_AVATAR_DOWNLOAD_BYTES:
        return None
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.seek(0)
            frame = im.convert("RGBA")
            if frame.width > 256 or frame.height > 256:
                frame.thumbnail((256, 256), RESAMPLE_LANCZOS)
            out = io.BytesIO()
            frame.save(out, format="PNG", optimize=True)
            return out.getvalue()
    except Exception:
        return None


async def _download_avatar_png_bytes(
    author: object,
    *,
    session: Optional[aiohttp.ClientSession] = None,
) -> Optional[bytes]:
    """최후 폴백(webhook.edit(avatar=bytes))을 위해 작성자 아바타를 정적 PNG 바이트로 다운로드합니다."""
    guild_av = getattr(author, "guild_avatar", None)
    global_av = getattr(author, "avatar", None)
    display_av = getattr(author, "display_avatar", None)

    # 1순위: discord.py Asset.read() 직접 사용 (가장 안정적)
    for asset in (guild_av, global_av, display_av):
        if asset is None or not hasattr(asset, "read"):
            continue
        target_asset = asset
        if hasattr(asset, "replace") and "/embed/avatars/" not in str(getattr(asset, "url", "")):
            try:
                target_asset = asset.replace(format="png", size=256)
            except Exception:
                target_asset = asset
        try:
            raw = await asyncio.wait_for(target_asset.read(), timeout=6.0)
            if raw and len(raw) <= _MAX_AVATAR_DOWNLOAD_BYTES:
                png = await asyncio.to_thread(_normalize_avatar_to_png_bytes, raw)
                if png:
                    return png
        except Exception:
            continue

    # 2순위: aiohttp IPv4 직접 다운로드
    download_urls: list[str] = []
    for asset in (guild_av, global_av, display_av):
        clean = _clean_discord_avatar_url(asset)
        if not clean:
            continue
        if "/embed/avatars/" not in clean:
            sized = f"{clean}?size=256"
            if sized not in download_urls:
                download_urls.append(sized)
            wsrv = _build_wsrv_avatar_url(clean)
            if wsrv not in download_urls:
                download_urls.append(wsrv)
        elif clean not in download_urls:
            download_urls.append(clean)

    if not download_urls:
        return None

    own_session = session is None or session.closed
    if own_session:
        timeout = aiohttp.ClientTimeout(total=8)
        connector = aiohttp.TCPConnector(family=socket.AF_INET, limit=8)
        http = aiohttp.ClientSession(timeout=timeout, connector=connector, headers={"User-Agent": USER_AGENT})
    else:
        http = session

    try:
        for url in download_urls:
            try:
                async with http.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if 200 <= resp.status < 300:
                        if resp.content_length and resp.content_length > _MAX_AVATAR_DOWNLOAD_BYTES:
                            continue
                        raw = await resp.content.read(_MAX_AVATAR_DOWNLOAD_BYTES + 1)
                        if raw and len(raw) <= _MAX_AVATAR_DOWNLOAD_BYTES:
                            png = await asyncio.to_thread(_normalize_avatar_to_png_bytes, raw)
                            if png:
                                return png
            except Exception:
                continue
    finally:
        if own_session:
            try:
                await http.close()
            except Exception:
                pass
    return None


def _is_webhook_avatar_dropped(
    sent_msg: object,
    webhook: discord.Webhook,
    author_id: Optional[int],
) -> bool:
    """Discord가 avatar_url을 드롭해 Clyde(avatar=None/'None') 또는 직전 유저의 웹훅 기본 프사로 폴백했는지 판정합니다."""
    if sent_msg is None:
        return False
    msg_author = getattr(sent_msg, "author", None)
    if msg_author is None:
        return False
    msg_avatar = getattr(msg_author, "avatar", None)
    if msg_avatar is None:
        return True
    cur_key = str(getattr(msg_avatar, "key", "") or "").strip()
    if not cur_key or cur_key.lower() == "none":
        return True
    wh_id = getattr(webhook, "id", None)
    if wh_id is not None and author_id is not None:
        prev = _WEBHOOK_UPLOADED_AVATAR_STATE.get(int(wh_id))
        if prev is not None:
            prev_uid, prev_key = prev
            if prev_uid != int(author_id) and cur_key == prev_key:
                return True
    return False


async def _check_webhook_avatar_cdn_ok(
    avatar_url: str,
    *,
    session: Optional[aiohttp.ClientSession] = None,
) -> bool:
    """
    Discord가 반환한 웹훅 메시지 아바타 URL이 실제로 CDN에서 HTTP 200 이미지로 서빙되는지 검증합니다.
    (콜드 캐시/변환 실패 시 Discord가 non-null 해시를 반환하고 CDN은 404를 내려 회색 Clyde가 뜨는 현상 방지)
    네트워크 일시 오류/타임아웃 시에는 오탐 삭제를 막기 위해 True를 반환합니다.
    """
    if not avatar_url or not avatar_url.startswith("https://cdn.discordapp.com/"):
        return True
    check_url = avatar_url.split("?", 1)[0] + "?size=64"
    own_session = session is None or session.closed
    if own_session:
        timeout = aiohttp.ClientTimeout(total=4)
        connector = aiohttp.TCPConnector(family=socket.AF_INET, limit=4)
        http = aiohttp.ClientSession(timeout=timeout, connector=connector, headers={"User-Agent": USER_AGENT})
    else:
        http = session
    try:
        async with http.get(check_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=3)) as resp:
            if resp.status >= 400:
                return False
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if ctype and not ctype.startswith("image/"):
                return False
            return True
    except Exception:
        return True
    finally:
        if own_session:
            try:
                await http.close()
            except Exception:
                pass


async def _is_webhook_avatar_broken_live(
    sent_msg: object,
    webhook: discord.Webhook,
    author_id: Optional[int],
    *,
    session: Optional[aiohttp.ClientSession] = None,
) -> tuple[bool, str]:
    """동기 검사(avatar=None/'None'/타유저 충돌) + Discord CDN 실제 200 응답 검증을 결합합니다."""
    if _is_webhook_avatar_dropped(sent_msg, webhook, author_id):
        msg_av = getattr(getattr(sent_msg, "author", None), "avatar", None)
        return True, f"meta_dropped(avatar={getattr(msg_av, 'key', None)!r})"
    msg_av = getattr(getattr(sent_msg, "author", None), "avatar", None)
    av_url = getattr(msg_av, "url", None) if msg_av is not None else None
    if isinstance(av_url, str) and av_url.startswith("https://cdn.discordapp.com/"):
        cdn_ok = await _check_webhook_avatar_cdn_ok(av_url, session=session)
        if not cdn_ok:
            return True, f"cdn_404({av_url})"
    return False, "ok"


async def send_webhook_with_verified_avatar(
    webhook: discord.Webhook,
    author: object,
    send_fn: Callable[[discord.Webhook, Optional[str]], Awaitable[Optional[discord.Message]]],
    *,
    guild: Optional[discord.Guild] = None,
    session: Optional[aiohttp.ClientSession] = None,
    thread: Optional[discord.Thread] = None,
    on_webhook_updated: Optional[Callable[[discord.Webhook], None]] = None,
) -> Optional[discord.Message]:
    """
    웹훅 전송 결과의 sent_msg.author.avatar 메타데이터 + 실제 Discord CDN 200 응답을 즉시 검증합니다.
    커스텀 프사가 있는 유저인데 Discord가 avatar_url을 드롭하거나 404 해시(회색 Clyde)를 내려준 경우:
      1) guild.fetch_member()로 최신 guild_avatar/avatar 해시 강제 갱신
      2) 대체 후보 URL(wsrv.nl 256x256 .png 프록시 -> 전역 프사 등)로 자동 재전송 후 Clyde 메시지 삭제
         (wsrv.nl이 성공하면 이후 요청도 첫 시도부터 wsrv.nl을 우선 사용하도록 자동 학습)
      3) 모든 URL 후보가 드롭되면 최후 폴백으로 작성자 PNG 바이트를 webhook.edit(avatar=bytes)로 업로드 후 전송
    """
    global _PREFER_EXTERNAL_AVATAR_PROXY

    candidates, has_custom_avatar = build_webhook_avatar_candidates(author)
    first_url = candidates[0] if candidates else None
    sent_msg = await send_fn(webhook, first_url)
    if sent_msg is None or not has_custom_avatar:
        return sent_msg

    author_id = getattr(author, "id", None)
    broken, reason = await _is_webhook_avatar_broken_live(
        sent_msg, webhook, author_id, session=session
    )
    if not broken:
        return sent_msg

    print(
        f"⚠️ [webhook_avatar] Clyde/깨진 프사 감지 (user={author_id}, reason={reason}, url={first_url}) -> 자동 복구 시도",
        flush=True,
    )

    async def _delete_bad_msg(msg: object) -> None:
        msg_id = getattr(msg, "id", None)
        if msg_id:
            core.mark_suppressed_delete_log(int(msg_id))
        try:
            if msg_id and hasattr(webhook, "delete_message"):
                if thread is not None:
                    await webhook.delete_message(int(msg_id), thread=thread)
                else:
                    await webhook.delete_message(int(msg_id))
                return
        except Exception:
            pass
        try:
            if hasattr(msg, "delete"):
                await msg.delete()
        except Exception:
            pass

    # 1단계: 최신 서버/전역 아바타 해시 강제 갱신 후 미시도 후보 URL 재시도
    fresh_author = await resolve_fresh_author(guild, author, force_refresh=True) if guild is not None else author
    fresh_candidates, still_custom = build_webhook_avatar_candidates(fresh_author)
    if not still_custom:
        return sent_msg

    tried = {first_url} if first_url else set()
    retry_urls = [u for u in fresh_candidates if u not in tried]

    for cand_url in retry_urls[:3]:
        tried.add(cand_url)
        try:
            retry_msg = await send_fn(webhook, cand_url)
        except Exception:
            continue
        if retry_msg is None:
            continue
        await _delete_bad_msg(sent_msg)
        sent_msg = retry_msg
        retry_broken, _ = await _is_webhook_avatar_broken_live(
            sent_msg, webhook, author_id, session=session
        )
        if not retry_broken:
            if (
                cand_url.startswith("https://wsrv.nl/")
                and first_url
                and first_url.startswith("https://cdn.discordapp.com/")
            ):
                _PREFER_EXTERNAL_AVATAR_PROXY = True
            print(f"✅ [webhook_avatar] 대체 URL 복구 성공 (user={author_id}, url={cand_url})", flush=True)
            return sent_msg

    # 2단계 최후 폴백: 아바타 PNG 바이트 직접 다운로드 -> webhook.edit(avatar=bytes) -> avatar_url 미지정 전송
    png_bytes = await _download_avatar_png_bytes(fresh_author, session=session)
    if png_bytes and hasattr(webhook, "edit"):
        wh_id = int(getattr(webhook, "id", 0) or 0)
        if len(_WEBHOOK_AVATAR_EDIT_LOCKS) > 500:
            for k in list(_WEBHOOK_AVATAR_EDIT_LOCKS.keys())[:100]:
                if not _WEBHOOK_AVATAR_EDIT_LOCKS[k].locked():
                    _WEBHOOK_AVATAR_EDIT_LOCKS.pop(k, None)
        lock = _WEBHOOK_AVATAR_EDIT_LOCKS.setdefault(wh_id, asyncio.Lock())
        async with lock:
            try:
                edited_wh = await webhook.edit(avatar=png_bytes)
                active_wh = edited_wh if edited_wh is not None else webhook
                if on_webhook_updated is not None and edited_wh is not None:
                    try:
                        on_webhook_updated(edited_wh)
                    except Exception:
                        pass
                edited_key = getattr(getattr(active_wh, "avatar", None), "key", None)
                if wh_id and author_id is not None and edited_key:
                    _WEBHOOK_UPLOADED_AVATAR_STATE[wh_id] = (int(author_id), str(edited_key))
                retry_msg = await send_fn(active_wh, None)
                if retry_msg is not None:
                    await _delete_bad_msg(sent_msg)
                    print(f"✅ [webhook_avatar] webhook.edit 직접 업로드 복구 성공 (user={author_id})", flush=True)
                    return retry_msg
            except Exception as edit_err:
                print(f"⚠️ [webhook_avatar] webhook.edit 최후 폴백 실패: {edit_err}", flush=True)

    return sent_msg


def _clean_reply_preview_text(raw_text: str, max_len: int = 38) -> str:
    """답장 원문 텍스트를 한 줄의 안전한 미리보기 문자열로 정리합니다."""
    if not raw_text:
        return ""
    # 마스킹 점자 링크([⠀](url)) 제거
    cleaned = re.sub(r"\[\u2800\]\([^)]+\)", "", raw_text)
    # 커스텀 이모지 <a:name:id> -> :name:
    cleaned = CUSTOM_EMOJI_RE.sub(lambda m: f":{m.group(2)}:", cleaned)
    # 마크다운 특수문자 및 개행 정리
    cleaned = re.sub(r"[\r\n\t]+", " ", cleaned)
    cleaned = re.sub(r"[*_`~|<>[\]]+", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1].rstrip() + "…"
    return cleaned


async def build_reply_quote_header(
    message: discord.Message,
    channel: discord.abc.Messageable,
) -> tuple[str, discord.AllowedMentions]:
    """
    웹훅 대리 전송 시에도 원본 작성자 프사/닉네임을 유지하면서 답장 맥락을 보여주는
    클릭 가능한 인용 헤더(`-# ↩️ ...`)와 안전한 AllowedMentions를 생성합니다.
    """
    ref = message.reference
    if ref is None or ref.message_id is None:
        return "", discord.AllowedMentions.none()

    ref_msg_id = int(ref.message_id)
    ref_ch_id = int(ref.channel_id or getattr(channel, "id", 0) or 0)
    ref_guild_id = int(ref.guild_id or (message.guild.id if message.guild else 0) or 0)
    jump_url = f"https://discord.com/channels/{ref_guild_id}/{ref_ch_id}/{ref_msg_id}"

    ref_msg = None
    resolved = getattr(ref, "resolved", None)
    if isinstance(resolved, discord.Message):
        ref_msg = resolved
    elif getattr(ref, "cached_message", None) is not None:
        ref_msg = ref.cached_message
    elif ref_ch_id == getattr(channel, "id", None) and hasattr(channel, "fetch_message"):
        try:
            ref_msg = await asyncio.wait_for(channel.fetch_message(ref_msg_id), timeout=2.0)
        except Exception:
            ref_msg = None

    if ref_msg is None:
        return f"-# ↩️ [답장 원문 보기](<{jump_url}>)", discord.AllowedMentions.none()

    ref_author = getattr(ref_msg, "author", None)
    raw_ref_name = getattr(ref_author, "display_name", None) or getattr(ref_author, "name", None) or "원본 메시지"
    safe_ref_name = re.sub(r"[\[\]\r\n<>]+", "", sanitize_webhook_username(raw_ref_name))[:32].strip() or "원본 메시지"

    preview = _clean_reply_preview_text(getattr(ref_msg, "content", "") or "")
    if not preview:
        if getattr(ref_msg, "attachments", None) or getattr(ref_msg, "stickers", None):
            preview = "첨부/스티커"
        elif getattr(ref_msg, "embeds", None):
            preview = "임베드"

    # 원본 답장에서 멘션 알림이 켜져 있었고 실제 유저에게 보낸 답장인 경우에만 멘션 보존
    mention_target_id: Optional[int] = None
    if (
        ref_author is not None
        and getattr(ref_author, "id", None)
        and getattr(ref_msg, "webhook_id", None) is None
        and not getattr(ref_author, "bot", False)
    ):
        mentioned_ids = {getattr(u, "id", None) for u in (getattr(message, "mentions", None) or ())}
        if ref_author.id in mentioned_ids:
            mention_target_id = int(ref_author.id)

    if mention_target_id is not None:
        header = (
            f"-# ↩️ <@{mention_target_id}> · [답장 원문](<{jump_url}>) · {preview}"
            if preview
            else f"-# ↩️ <@{mention_target_id}> · [답장 원문](<{jump_url}>)"
        )
        allowed = discord.AllowedMentions(
            everyone=False,
            roles=False,
            users=[discord.Object(id=mention_target_id)],
        )
        return header, allowed

    header = (
        f"-# ↩️ [{safe_ref_name}](<{jump_url}>) · {preview}"
        if preview
        else f"-# ↩️ [{safe_ref_name}](<{jump_url}>)님에게 답장"
    )
    return header, discord.AllowedMentions.none()


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
# 5. emote-cdn-rust 호환 HTTP 핸들러 (/emoji/:id, /e/:id, /sticker/:id, /s/:id, /:name)
# ==========================================
EMOTE_CDN_INDEX_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Emote CDN (160x160 WebP Resizer)</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.6; background-color: #f5f5f5; }
        .container { background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #333; border-bottom: 2px solid #5865f2; padding-bottom: 10px; }
        .endpoint { background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #5865f2; }
        code { background: #e9ecef; padding: 2px 6px; border-radius: 3px; font-family: monospace; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Discord CDN Resizer (160x160 WebP)</h1>
        <p>Discord 이모지와 스티커를 투명 여백 없이 원본 종횡비를 유지하며 160x160(Lanczos3) WebP로 리사이징하여 제공합니다.</p>
        <div class="endpoint"><strong>GET /healthz</strong> — 서버 상태 확인</div>
        <div class="endpoint"><strong>GET /emoji/{id}</strong> · <strong>GET /e/{id}.webp</strong> · <strong>GET /{id}.webp</strong> — 이모지 160x160 WebP 리사이징</div>
        <div class="endpoint"><strong>GET /sticker/{id}</strong> · <strong>GET /s/{id}.webp</strong> — 스티커 160x160 WebP 리사이징</div>
    </div>
</body>
</html>"""


async def handle_emote_index_http_request(_request: web.Request) -> web.Response:
    """emote-cdn-rust handlers::index_handler 동일."""
    return web.Response(text=EMOTE_CDN_INDEX_HTML, content_type="text/html", charset="utf-8")


MAX_CDN_DOWNLOAD_BYTES = 8 * 1024 * 1024  # 8MB
_CDN_SHARED_SESSION: Optional[aiohttp.ClientSession] = None
_CDN_SEMAPHORES: dict[int, asyncio.Semaphore] = {}


def _get_cdn_semaphore() -> asyncio.Semaphore:
    loop_id = id(asyncio.get_running_loop())
    sem = _CDN_SEMAPHORES.get(loop_id)
    if sem is None:
        sem = asyncio.Semaphore(8)
        _CDN_SEMAPHORES[loop_id] = sem
    return sem


async def _get_cdn_shared_session() -> aiohttp.ClientSession:
    global _CDN_SHARED_SESSION
    if _CDN_SHARED_SESSION is None or _CDN_SHARED_SESSION.closed:
        timeout = aiohttp.ClientTimeout(total=10)
        connector = aiohttp.TCPConnector(limit=32, limit_per_host=16, keepalive_timeout=30.0)
        _CDN_SHARED_SESSION = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers={"User-Agent": USER_AGENT},
        )
    return _CDN_SHARED_SESSION


def _can_decode_with_pillow(raw: bytes) -> bool:
    """Pillow(libwebp 등)가 해당 이미지의 첫 프레임을 오류 없이 디코드할 수 있는지 검사합니다."""
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            return True
    except Exception:
        return False


async def fetch_and_resize_cdn_item(
    session: aiohttp.ClientSession,
    item_id: str,
    content_type: str = "emoji",
) -> Optional[tuple[bytes, str]]:
    """
    Discord CDN에서 이모지/스티커 원본(WebP -> PNG 폴백)을 가져와
    투명 여백 없이 160x160 종횡비 유지 WebP로 리사이징하고 24시간 메모리 캐시에 저장합니다
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
        # emote-cdn-rust handlers::process_sticker 동일: PNG(?size=160) 우선 시도 후 WebP 폴백
        src_urls = [
            f"https://media.discordapp.net/stickers/{clean_id}.png?size=160",
            f"https://media.discordapp.net/stickers/{clean_id}.webp?size=160",
        ]
    else:
        # emote-cdn-rust handlers::process_emoji 동일: WebP(?size=160&animated=true) 우선 시도 후 PNG 폴백
        src_urls = [
            f"https://cdn.discordapp.com/emojis/{clean_id}.webp?size=160&animated=true",
            f"https://cdn.discordapp.com/emojis/{clean_id}.png?size=160&animated=true",
        ]

    body: Optional[bytes] = None
    actual_src = ""
    headers = {"User-Agent": USER_AGENT}
    for src_url in src_urls:
        try:
            async with session.get(src_url, headers=headers, allow_redirects=False) as resp:
                if 200 <= resp.status < 300:
                    if resp.content_length and resp.content_length > MAX_CDN_DOWNLOAD_BYTES:
                        continue
                    raw = await resp.content.read(MAX_CDN_DOWNLOAD_BYTES + 1)
                    if raw and 12 <= len(raw) <= MAX_CDN_DOWNLOAD_BYTES:
                        body = raw
                        actual_src = src_url
                        break
        except Exception:
            continue

    if not body:
        return None

    # 알 수 없는 포맷이면 415 처리를 위해 None 반환 (emote-cdn-rust DetectedFormat::Unknown)
    fmt = detect_image_format(body)
    if fmt == DetectedFormat.UNKNOWN:
        return None

    # 일부 디스코드 애니메이션 WebP는 libwebp WebPAnimDecoder 생성 실패("could not create decoder object")가 발생하므로
    # 이 경우 원본 .gif?size=160 으로 자동 폴백해 깨짐·경고 없이 160x160 애니메이션 WebP로 변환합니다.
    if content_type == "emoji" and fmt == DetectedFormat.WEBP and is_animated_webp(body):
        can_decode = await asyncio.to_thread(_can_decode_with_pillow, body)
        if not can_decode:
            gif_url = f"https://cdn.discordapp.com/emojis/{clean_id}.gif?size=160"
            try:
                async with session.get(gif_url, headers=headers, allow_redirects=False) as gif_resp:
                    if 200 <= gif_resp.status < 300:
                        if not gif_resp.content_length or gif_resp.content_length <= MAX_CDN_DOWNLOAD_BYTES:
                            gif_raw = await gif_resp.content.read(MAX_CDN_DOWNLOAD_BYTES + 1)
                            if gif_raw and 12 <= len(gif_raw) <= MAX_CDN_DOWNLOAD_BYTES and detect_image_format(gif_raw) == DetectedFormat.GIF:
                                body = gif_raw
                                actual_src = gif_url
            except Exception:
                pass

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


async def handle_emote_favicon_http_request(_request: web.Request) -> web.Response:
    """emote-cdn-rust handlers::favicon_handler 동일 (204 No Content)."""
    return web.Response(status=204)


async def handle_emote_cdn_http_request(request: web.Request, content_type: str = "emoji") -> web.Response:
    """
    aiohttp 웹 서버에서 /emoji/{id}, /e/{id}, /sticker/{id}, /s/{id}, /{name} 요청을 처리합니다
    (emote-cdn-rust handlers::emoji_handler / sticker_handler / legacy_handler).
    """
    raw_id = request.match_info.get("id") or request.match_info.get("name") or ""
    clean_id = clean_id_from_path(raw_id)
    if not validate_id(clean_id):
        return web.Response(status=400, text="Invalid ID format")

    signing_key = get_emote_cdn_signing_key()
    if signing_key:
        ex_param = request.query.get("ex")
        hm_param = request.query.get("hm")
        if not verify_signature(clean_id, ex_param, hm_param, signing_key):
            return web.Response(status=401, text="Unauthorized")

    async with _get_cdn_semaphore():
        session = await _get_cdn_shared_session()
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
    status_badge = "🟢 **ON** (활성화됨)" if enabled else "🔴 **OFF** (비활성화됨 · 기본값)"
    cdn_base = get_emote_cdn_base_url()
    has_sig = bool(get_emote_cdn_signing_key())
    sig_badge = "🔐 HMAC-SHA256 서명 활성" if has_sig else "⚡ 자동 WebP CDN 폴백 활성"
    desc_lines = [
        "커스텀 디스코드 이모지(1~3개)만 포함된 채팅을 보내면 원본 메시지를 삭제한 뒤,",
        "투명 여백 패딩 없이 **원본 종횡비를 100% 유지한 `160×160` WebP** (`emote-cdn-rust` · Lanczos3 · 24시간 캐시)로 변환하여",
        "**보낸 사람의 프로필 사진과 서버 닉네임**으로 즉시 전송합니다.",
        "• **📱 모바일 & 데스크탑 완벽 호환:** 투명 캔버스 없이 `160×160` 박스 내 원본 비율(`compute_aspect_dimensions` · Lanczos3)로 리사이징된 WebP CDN 언펄을 사용하여 **모바일과 데스크탑 모두에서 화면이 가득 차지 않고 스티커 크기(`160×160`)와 원본 종횡비·애니메이션이 그대로 유지**됩니다.",
        "• **🗑️ 삭제 방법:** 전송된 이모지 메시지에 직접 `:x:`(❌) 반응을 추가하면 즉시 삭제됩니다.",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"• **🏠 대상 서버:** `{guild.name}`",
        f"• **⚡ 현재 기능 상태:** {status_badge}",
        f"• **🌐 연동 CDN 엔드포인트:** `{cdn_base}/e/{{id}}.webp` ({sig_badge})",
        "• **🖼️ 리사이징 엔진:** `160×160 WebP` (투명 패딩 없음 · 원본 종횡비 유지 · Lanczos3 · Animated WebP / APNG 지원)",
        "• **🛡️ 변경 가능 권한:** **서버 관리자** (`Administrator` / `서버 관리`)",
        "• **🔒 기본 동작 정책:** 모든 서버 최초 기본값은 **OFF** 입니다.",
    ]

    if channel and guild.me and hasattr(channel, "permissions_for"):
        perms = channel.permissions_for(guild.me)
        missing = []
        if not perms.manage_messages:
            missing.append("메시지 관리(`Manage Messages` - 원본 이모지 삭제용)")
        if not perms.manage_webhooks:
            missing.append("웹후크 관리(`Manage Webhooks` - 발신자 프로필 재전송용)")
        can_send = perms.send_messages_in_threads if isinstance(channel, discord.Thread) else perms.send_messages
        if not can_send:
            missing.append("메시지 보내기(`Send Messages` - 채널/스레드 전송용)")
        if missing:
            desc_lines.append("")
            desc_lines.append("⚠️ **현재 채널 봇 권한 확인 필요:**")
            for m in missing:
                desc_lines.append(f"  - ❌ `{m}`")
        else:
            desc_lines.append("• **🤖 현재 채널 봇 권한:** ✅ 정상 작동 가능 (메시지 관리 · 웹후크 보유)")

    desc_lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    embed = discord.Embed(
        title="🔍 커스텀 이모지 160×160 WebP 리사이저 설정",
        description="\n".join(desc_lines),
        color=discord.Color.from_rgb(87, 242, 135) if enabled else discord.Color.from_rgb(149, 165, 166),
        timestamp=datetime.datetime.now(core.KST),
    )
    embed.set_footer(text="서버 관리자만 아래 버튼(/설정 → 고급 → 이모지 업스케일)으로 ON/OFF를 전환할 수 있습니다.")
    return embed


class EmoteCdnConfigModal(core.SafeModal, title="🌐 Emote CDN 서버 & 서명 키 설정"):
    cdn_url_input = discord.ui.TextInput(
        label="emote-cdn-rust 서버 주소 (비우면 기본값 복원)",
        placeholder="https://cdn.kamibot.app",
        required=False,
        max_length=200,
    )
    signing_key_input = discord.ui.TextInput(
        label="SIGNING_KEY (선택 · HMAC-SHA256 서명 키)",
        placeholder="비워두면 기존 키 유지 ('초기화' 입력 시 서명 키 삭제)",
        required=False,
        max_length=256,
    )

    def __init__(self, parent_view: "EmojiUpscaleConfigView"):
        super().__init__()
        self.parent_view = parent_view
        self.cdn_url_input.default = get_emote_cdn_base_url()

    async def on_submit(self, interaction: discord.Interaction):
        bot_ref = self.parent_view.bot or interaction.client
        if not bot_ref or not hasattr(bot_ref, "is_bot_owner_user") or not await bot_ref.is_bot_owner_user(interaction.user):
            await core.safe_send_response(
                interaction,
                "🚨 **권한 부족:** 전역 Emote CDN 서버 주소 및 서명 키 변경은 **👑 봇 주인(소유자) 전용**입니다.",
                ephemeral=True,
            )
            return

        raw_url = (self.cdn_url_input.value or "").strip().rstrip("/")
        raw_key = (self.signing_key_input.value or "").strip()
        if raw_url:
            if not raw_url.startswith("https://"):
                await core.safe_send_response(
                    interaction,
                    "❌ 보안상 CDN 서버 주소는 `https://`로 시작해야 합니다. (예: `https://cdn.kamibot.app`)",
                    ephemeral=True,
                )
                return
            if not await asyncio.to_thread(core.is_safe_external_url, raw_url):
                await core.safe_send_response(
                    interaction,
                    "❌ 내부 네트워크(루프백·사설망·링크로컬) 또는 안전하지 않은 주소는 CDN 서버로 설정할 수 없습니다.",
                    ephemeral=True,
                )
                return

        await core.safe_defer(interaction, ephemeral=True)

        def _save_cdn_config():
            with core._DATA_LOCK:
                data = core.load_data()
                settings_d = core.ensure_dict_path(data, "settings")
                if raw_url:
                    settings_d["emote_cdn_base_url"] = raw_url
                else:
                    settings_d.pop("emote_cdn_base_url", None)
                if raw_key in ("초기화", "삭제", "reset", "clear", "none"):
                    settings_d.pop("emote_cdn_signing_key", None)
                elif raw_key:
                    settings_d["emote_cdn_signing_key"] = raw_key
                core.save_data(data)

        await asyncio.to_thread(_save_cdn_config)
        gid = self.parent_view.guild_id or (interaction.guild.id if interaction.guild else 0)
        enabled = core.is_emoji_upscale_enabled(gid) if gid else False
        if interaction.guild:
            emb = build_emoji_upscale_embed(interaction.guild, interaction.channel, enabled)
            await core.safe_edit_response(interaction, embed=emb, view=self.parent_view)
        await interaction.followup.send(
            f"✅ **Emote CDN 설정이 적용되었습니다!** (주소: `{get_emote_cdn_base_url()}`)",
            ephemeral=True,
        )


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
        if not await super().interaction_check(interaction):
            return False
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return False
        if not self.guild_id:
            self.guild_id = interaction.guild.id
        bot_ref = self.bot or interaction.client
        if not await _can_manage_upscale(bot_ref, interaction):
            await core.safe_send_response(
                interaction,
                "🚨 **권한 부족:** 이모지 업스케일 설정은 **서버 관리자**(`Administrator` / `서버 관리`)만 변경할 수 있습니다.",
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

    @discord.ui.button(label="🌐 CDN 서버 주소 설정 (봇주 전용)", style=discord.ButtonStyle.secondary, row=0)
    async def btn_cdn_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot_ref = self.bot or interaction.client
        if not bot_ref or not hasattr(bot_ref, "is_bot_owner_user") or not await bot_ref.is_bot_owner_user(interaction.user):
            await core.safe_send_response(
                interaction,
                "🚨 **권한 부족:** 전역 Emote CDN 서버 주소 및 서명 키 설정은 **👑 봇 주인(소유자) 전용**입니다.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(EmoteCdnConfigModal(self))


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
        self._verified_cdn_urls: OrderedDict[str, tuple[float, str]] = OrderedDict()

    async def cog_unload(self):
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        self._http_session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            timeout = aiohttp.ClientTimeout(total=12)
            connector = aiohttp.TCPConnector(family=socket.AF_INET, limit_per_host=32, keepalive_timeout=30.0)
            self._http_session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={"User-Agent": USER_AGENT},
            )
        return self._http_session

    async def _download_emoji_bytes(self, emoji_id: str, animated: bool = False) -> Optional[bytes]:
        """Discord CDN에서 WebP(?size=160&animated=true) 우선 다운로드, 디코드 불가 애니메이션 WebP는 GIF로 안전 폴백합니다."""
        clean_id = clean_id_from_path(emoji_id)
        if not validate_id(clean_id):
            return None
        session = await self._get_session()
        urls = [f"https://cdn.discordapp.com/emojis/{clean_id}.webp?size=160&animated=true"]
        if animated:
            urls.append(f"https://cdn.discordapp.com/emojis/{clean_id}.gif?size=160")
        urls.append(f"https://cdn.discordapp.com/emojis/{clean_id}.png?size=160&animated=true")

        fallback_raw: Optional[bytes] = None
        for url in urls:
            try:
                async with session.get(url, allow_redirects=False) as resp:
                    if 200 <= resp.status < 300:
                        if resp.content_length and resp.content_length > MAX_CDN_DOWNLOAD_BYTES:
                            continue
                        raw = await resp.content.read(MAX_CDN_DOWNLOAD_BYTES + 1)
                        if raw and 12 <= len(raw) <= MAX_CDN_DOWNLOAD_BYTES:
                            if is_animated_webp(raw) and not await asyncio.to_thread(_can_decode_with_pillow, raw):
                                fallback_raw = raw
                                continue
                            return raw
            except Exception:
                continue
        return fallback_raw

    async def _verify_url_returns_webp(self, url: str) -> bool:
        """해당 URL이 실제로 HTTP 200 OK 및 유효한 이미지(WebP/PNG/GIF)를 반환하는지 검증합니다."""
        if not await asyncio.to_thread(core.is_safe_external_url, url):
            return False
        session = await self._get_session()
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5), allow_redirects=False) as resp:
                if 200 <= resp.status < 300:
                    if resp.content_length and resp.content_length > MAX_CDN_DOWNLOAD_BYTES:
                        return False
                    raw = await resp.content.read(MAX_CDN_DOWNLOAD_BYTES + 1)
                    if raw and 12 <= len(raw) <= MAX_CDN_DOWNLOAD_BYTES and detect_image_format(raw) != DetectedFormat.UNKNOWN:
                        return True
                return False
        except Exception:
            return False

    async def _resolve_working_emote_cdn_url(self, emoji_id: str, dup_index: int = 0) -> Optional[str]:
        """
        emote-cdn-rust 가이드에 따라 투명 여백 없이 원본 종횡비를 유지한 160x160 WebP URL을 반환합니다.
        1) 먼저 Discord CDN에서 원본을 가져와 로컬 emote-cdn-rust 160x160 WebP 캐시(GLOBAL_EMOTE_CACHE)를 예열하고 유효성을 검증합니다.
        2) 설정된 emote-cdn-rust 서버(예: https://cdn.kamibot.app/e/{id}.webp)가 200 OK를 반환하면 해당 URL을 최우선 사용합니다.
        3) 만약 외부 서버에 SIGNING_KEY가 필요하여 401 등이 반환되면, 동일한 160x160 종횡비 유지(fit=inside · Lanczos3 · WebP · 애니메이션 유지 · 투명 패딩 없음) 공개 .webp 엔드포인트 URL을 검증 후 반환합니다.
        """
        clean_id = clean_id_from_path(emoji_id)
        if not validate_id(clean_id):
            return None

        session = await self._get_session()
        local_res = await fetch_and_resize_cdn_item(session, clean_id, content_type="emoji")
        if local_res is None:
            return None
        _, actual_src = local_res

        now_mono = time.monotonic()
        url_cache_key = f"{clean_id}:{dup_index}:{get_emote_cdn_base_url()}:{bool(get_emote_cdn_signing_key())}"
        cached_url_entry = self._verified_cdn_urls.get(url_cache_key)
        if cached_url_entry is not None:
            exp_mono, cached_url = cached_url_entry
            if now_mono < exp_mono:
                self._verified_cdn_urls.move_to_end(url_cache_key)
                return cached_url
            self._verified_cdn_urls.pop(url_cache_key, None)

        # 1차: 설정된 emote-cdn-rust 서버 URL 검증
        primary_url = generate_emote_cdn_url(clean_id, content_type="emoji", dup_index=dup_index)
        if await self._verify_url_returns_webp(primary_url):
            self._verified_cdn_urls[url_cache_key] = (now_mono + 3600, primary_url)
            while len(self._verified_cdn_urls) > 5000:
                self._verified_cdn_urls.popitem(last=False)
            return primary_url

        # 2차: 투명 여백 없는 160x160 종횡비 유지 Lanczos3 WebP 공개 CDN URL 검증
        fallback_url = generate_wsrv_emote_webp_url(
            clean_id,
            actual_src=actual_src,
            content_type="emoji",
            dup_index=dup_index,
        )
        if await self._verify_url_returns_webp(fallback_url):
            self._verified_cdn_urls[url_cache_key] = (now_mono + 3600, fallback_url)
            while len(self._verified_cdn_urls) > 5000:
                self._verified_cdn_urls.popitem(last=False)
            return fallback_url

        return None

    async def _prepare_upscaled_masked_link(self, emojis: list[dict]) -> Optional[str]:
        """
        1~3개의 커스텀 이모지를 투명 여백 없는 160x160 종횡비 유지 WebP 마스킹 링크([⠀](url))로 변환합니다.
        - 모바일과 데스크탑 모두에서 파일 첨부(attachments)로 인한 가로 100% 확대 없이,
          원본 종횡비를 그대로 유지한 스티커 크기(160x160 박스)로 렌더링됩니다.
        """
        items = emojis[:MAX_EMOJIS_PER_MESSAGE]
        if not items:
            return None

        seen_counts: dict[str, int] = {}
        masked_links: list[str] = []

        for em in items:
            clean_id = clean_id_from_path(em["id"])
            if not validate_id(clean_id):
                return None
            occ = seen_counts.get(clean_id, 0)
            seen_counts[clean_id] = occ + 1

            verified_url = await self._resolve_working_emote_cdn_url(clean_id, dup_index=occ)
            if not verified_url:
                return None
            masked_links.append(f"[{BRAILLE_BLANK}]({verified_url})")

        if not masked_links:
            return None
        return " ".join(masked_links)

    async def _build_sticker_strip_payload(self, emojis: list[dict]) -> Optional[tuple[bytes, str]]:
        """
        1~3개의 커스텀 이모지를 투명 캔버스 패딩 없이 emote-cdn-rust(160x160 종횡비 유지 · Lanczos3 · WebP)로 변환하고
        24시간 TTL 인메모리 캐시(GLOBAL_EMOTE_CACHE)에 저장하여 (바이트, 파일명) 튜플로 반환합니다.
        """
        items = emojis[:MAX_EMOJIS_PER_MESSAGE]
        if not items:
            return None

        session = await self._get_session()
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", items[0]["name"])[:48] or "emoji"

        if len(items) == 1:
            res = await fetch_and_resize_cdn_item(session, items[0]["id"], content_type="emoji")
            if not res:
                return None
            webp_bytes, _ = res
            if not webp_bytes or len(webp_bytes) > MAX_UPLOAD_BYTES:
                return None
            return webp_bytes, f"{safe_name}.webp"

        combo_key = "combo:" + "+".join(clean_id_from_path(em["id"]) for em in items)
        cached_combo = GLOBAL_EMOTE_CACHE.get(combo_key)
        if cached_combo is not None:
            webp_bytes, ext_meta = cached_combo
            ext = ext_meta if ext_meta in ("webp", "gif", "png") else "webp"
            if webp_bytes and len(webp_bytes) <= MAX_UPLOAD_BYTES:
                return webp_bytes, f"{safe_name}.{ext}"

        raw_list: list[bytes] = []
        for em in items:
            raw = await self._download_emoji_bytes(em["id"], em["animated"])
            if not raw:
                return None
            raw_list.append(raw)

        out_bytes, ext = await asyncio.to_thread(build_sticker_strip_bytes, raw_list)
        if not out_bytes or len(out_bytes) > MAX_UPLOAD_BYTES:
            return None

        GLOBAL_EMOTE_CACHE.insert(combo_key, out_bytes, ext)
        return out_bytes, f"{safe_name}.{ext}"

    async def _build_sticker_strip_file(self, emojis: list[dict]) -> Optional[discord.File]:
        res = await self._build_sticker_strip_payload(emojis)
        if not res:
            return None
        out_bytes, filename = res
        return discord.File(io.BytesIO(out_bytes), filename=filename)

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
        self._processed_msgs[msg_id] = time.time()
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
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if (
            getattr(before, "guild_avatar", None) != getattr(after, "guild_avatar", None)
            or getattr(before, "nick", None) != getattr(after, "nick", None)
            or getattr(before, "avatar", None) != getattr(after, "avatar", None)
        ):
            invalidate_fresh_author_cache(after.id, after.guild.id if after.guild else None)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        if (
            getattr(before, "avatar", None) != getattr(after, "avatar", None)
            or getattr(before, "global_name", None) != getattr(after, "global_name", None)
            or getattr(before, "name", None) != getattr(after, "name", None)
        ):
            invalidate_fresh_author_cache(after.id)

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

        # 순수 커스텀 이모지 메시지(1~3개, 모바일 제로폭 문자 허용)인지 검사
        emojis = extract_pure_custom_emojis(message.content)
        if not emojis:
            return

        # 중복 이벤트 방어
        if not self._mark_processed(message.id):
            return

        channel = message.channel
        base_channel = channel.parent if isinstance(channel, discord.Thread) else channel
        if base_channel is None:
            return

        is_reply = (
            message.type == discord.MessageType.reply
            and message.reference is not None
            and message.reference.message_id is not None
        )

        me = message.guild.me
        if not me:
            return
        perms = channel.permissions_for(me)
        can_send = perms.send_messages_in_threads if isinstance(channel, discord.Thread) else perms.send_messages
        can_use_webhook = hasattr(base_channel, "webhooks") and perms.manage_webhooks
        if not perms.manage_messages:
            return
        if is_reply:
            if not (can_use_webhook or can_send):
                return
        else:
            if not can_use_webhook:
                return

        # 1. emote-cdn-rust 가이드 방식(투명 여백 없음 · 160x160 원본 종횡비 유지 · Lanczos3 · WebP)
        #    200 OK 검증된 마스킹 링크([⠀](url)) 우선 준비 -> 외부 네트워크 차단 시에만 160x160 WebP 직접 전송 폴백
        masked_content: Optional[str] = None
        fallback_payload: Optional[tuple[bytes, str]] = None
        try:
            masked_content = await self._prepare_upscaled_masked_link(emojis)
            if not masked_content:
                fallback_payload = await self._build_sticker_strip_payload(emojis)
                if not fallback_payload:
                    return
        except Exception as e:
            print(f"⚠️ [이모지 업스케일 변환 예외] {e}", flush=True)
            return

        # 2. 일반·답장 모두 웹훅 우선 준비 (보낸 사람 프로필 사진 & 서버 닉네임 유지)
        #    웹훅 권한이 없거나 생성 실패 시에만 답장을 앱(봇) 네이티브 답장으로 안전 폴백
        webhook = await self._get_or_create_webhook(base_channel) if can_use_webhook else None
        if not webhook:
            if not (is_reply and can_send):
                return

        fresh_author = await resolve_fresh_author(message.guild, message.author) if webhook is not None else message.author
        reply_quote_header = ""
        reply_quote_allowed = discord.AllowedMentions.none()
        if is_reply and webhook is not None:
            reply_quote_header, reply_quote_allowed = await build_reply_quote_header(message, channel)

        # 3. 원본 메시지 삭제 (이모지 업스케일 치환 삭제에 한해 서버 삭제 로그 억제)
        core.mark_suppressed_delete_log(message.id)
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            core.consume_suppressed_delete_log(message.id)
            return

        sent_msg = None

        # 4-A. 웹훅 전송 (일반 메시지 + 답장 메시지 모두 보낸 사람 실제 프사 & 서버 닉네임으로 전송)
        if webhook is not None:
            sender_name = sanitize_webhook_username(
                getattr(fresh_author, "display_name", None) or message.author.display_name
            )
            thread_obj = channel if isinstance(channel, discord.Thread) else None
            wh_allowed = reply_quote_allowed if is_reply else discord.AllowedMentions.none()
            content_to_send: Optional[str] = None
            if masked_content:
                content_to_send = (
                    f"{reply_quote_header}\n{masked_content}"
                    if (is_reply and reply_quote_header)
                    else masked_content
                )
            elif is_reply and reply_quote_header:
                content_to_send = reply_quote_header

            async def _send_via_webhook(wh: discord.Webhook, avatar_url: Optional[str]):
                kw: dict = {
                    "username": sender_name,
                    "allowed_mentions": wh_allowed,
                    "wait": True,
                }
                if avatar_url is not None:
                    kw["avatar_url"] = avatar_url
                if thread_obj is not None:
                    kw["thread"] = thread_obj
                if masked_content:
                    return await wh.send(content=content_to_send, **kw)
                assert fallback_payload is not None
                out_bytes, filename = fallback_payload
                if content_to_send:
                    kw["content"] = content_to_send
                return await wh.send(
                    file=discord.File(io.BytesIO(out_bytes), filename=filename),
                    **kw,
                )

            http_session = await self._get_session()

            def _cache_updated_wh(updated_wh: discord.Webhook) -> None:
                self._webhook_cache[base_channel.id] = updated_wh

            try:
                sent_msg = await send_webhook_with_verified_avatar(
                    webhook,
                    fresh_author,
                    _send_via_webhook,
                    guild=message.guild,
                    session=http_session,
                    thread=thread_obj,
                    on_webhook_updated=_cache_updated_wh,
                )
            except discord.NotFound:
                self._webhook_cache.pop(base_channel.id, None)
                fresh_webhook = await self._get_or_create_webhook(base_channel)
                if fresh_webhook:
                    try:
                        sent_msg = await send_webhook_with_verified_avatar(
                            fresh_webhook,
                            fresh_author,
                            _send_via_webhook,
                            guild=message.guild,
                            session=http_session,
                            thread=thread_obj,
                            on_webhook_updated=_cache_updated_wh,
                        )
                    except Exception as retry_err:
                        print(f"⚠️ [이모지 업스케일 웹훅 재전송 실패] {retry_err}", flush=True)
            except Exception as send_err:
                print(f"⚠️ [이모지 업스케일 웹훅 전송 실패] {send_err}", flush=True)

            if sent_msg and getattr(sent_msg, "id", None):
                self._record_upscaled_message(int(sent_msg.id), int(message.author.id))
            return

        # 4-B. 웹훅 권한 부재 시 답장 폴백: 앱(봇) 네이티브 답장 전송
        if is_reply:
            reply_ref = discord.MessageReference(
                message_id=message.reference.message_id,
                channel_id=message.reference.channel_id or channel.id,
                guild_id=message.reference.guild_id or message.guild.id,
                fail_if_not_exists=False,
            )
            mention_target = bool(message.mentions)
            safe_sender = discord.utils.escape_markdown(
                sanitize_webhook_username(message.author.display_name)
            )
            reply_allowed = discord.AllowedMentions(
                everyone=False,
                roles=False,
                users=False,
                replied_user=mention_target,
            )
            try:
                if masked_content:
                    sent_msg = await channel.send(
                        content=f"-# {safe_sender}\n{masked_content}",
                        reference=reply_ref,
                        mention_author=mention_target,
                        allowed_mentions=reply_allowed,
                    )
                else:
                    assert fallback_payload is not None
                    out_bytes, filename = fallback_payload
                    sent_msg = await channel.send(
                        content=f"-# {safe_sender}",
                        file=discord.File(io.BytesIO(out_bytes), filename=filename),
                        reference=reply_ref,
                        mention_author=mention_target,
                        allowed_mentions=reply_allowed,
                    )
            except Exception as reply_err:
                print(f"⚠️ [이모지 업스케일 앱 답장 전송 실패] {reply_err}", flush=True)

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
                "🚨 **권한 부족:** `/이모지업스케일` 명령어는 **서버 관리자**(`Administrator` / `서버 관리`)만 사용할 수 있습니다.",
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
        await interaction.followup.send(embed=emb, view=view, ephemeral=True, wait=True)

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
