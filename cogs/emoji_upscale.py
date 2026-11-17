"""
cogs/emoji_upscale.py - 서버별 커스텀 이모지 고품질 업스케일 & 발신자 프로필/닉네임 웹훅 대리 전송 모듈
- 기본 상태: 모든 서버 OFF (False)
- 서버 관리자(Administrator / Manage Server) 전용 ON/OFF 및 상태 패널 (/이모지업스케일)
- 정적 PNG/WebP 및 움직이는 GIF(<a:...>) 모두 투명 배경·프레임 손실·깨짐 없이 고해상도로 업스케일 후
  원본 메시지 삭제 및 발신자의 서버 닉네임·프로필 아바타를 적용한 웹훅으로 재전송
"""

import asyncio
import datetime
import io
import re
from collections import OrderedDict
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageSequence

import core

# 순수 커스텀 이모지 메시지(1~3개, 앞뒤 공백만 허용) 매칭용 정규식
CUSTOM_EMOJI_RE = re.compile(r"<(a?):([a-zA-Z0-9_]{1,64}):(\d{15,22})>")

MAX_EMOJIS_PER_MESSAGE = 3
STICKER_TARGET_SIZE = 160   # 디스코드 원본 스티커 표시 크기 (160x160px)
TRIPLE_SLOT_SIZE = 128      # 3개 연속 전송 시 각 이모지 최대 크기
EMOJI_SLOT_SIZE = STICKER_TARGET_SIZE
STATIC_TARGET_SIZE = STICKER_TARGET_SIZE
ANIMATED_TARGET_SIZE = STICKER_TARGET_SIZE
MAX_UPLOAD_BYTES = 24 * 1024 * 1024  # Discord 25MB 제한 안전 마진
WEBHOOK_NAME = "norosi-emoji-upscale"
RESAMPLE_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)

try:
    from PIL import GifImagePlugin
    GifImagePlugin.LOADING_STRATEGY = GifImagePlugin.LoadingStrategy.RGB_AFTER_DIFFERENT_PALETTE_ONLY
except Exception:
    pass


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
    # zero-width space로 금지어 포함 여부만 부드럽게 우회하여 원형 닉네임 가독성 유지
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


def _compute_scaled_size(width: int, height: int, target_size: int) -> tuple[int, int]:
    """비율을 유지하면서 긴 변을 디스코드 스티커 크기(target_size, 기본 160px)로 맞춥니다."""
    if width <= 0 or height <= 0:
        return target_size, target_size
    longest = max(width, height)
    final_long = max(1, min(target_size, 512))
    scale = final_long / float(longest)
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    return new_w, new_h


def _resize_rgba(rgba: Image.Image, target_size: int) -> Image.Image:
    """원본 이모지 비율·윤곽선·투명도를 변형 없이 그대로 유지하며 target_size로 리사이즈합니다."""
    new_w, new_h = _compute_scaled_size(rgba.width, rgba.height, target_size)
    if (new_w, new_h) == (rgba.width, rgba.height):
        return rgba.copy()
    return rgba.resize((new_w, new_h), RESAMPLE_LANCZOS)


def _rgba_frame_to_transparent_gif_frame(rgba_frame: Image.Image) -> Image.Image:
    """WebP 미지원 환경 폴백용: 투명 배경을 깨짐 없이 보존하는 GIF 팔레트('P') 프레임으로 변환합니다."""
    alpha = rgba_frame.getchannel("A")
    # 완전 투명 영역을 검정(0,0,0) 대신 중립 배경색으로 채워 팔레트 외곽선 번짐 최소화
    neutral_bg = Image.new("RGBA", rgba_frame.size, (49, 51, 56, 255))
    neutral_bg.alpha_composite(rgba_frame)
    rgb = neutral_bg.convert("RGB")
    quant_method = getattr(getattr(Image, "Quantize", Image), "FASTOCTREE", 2)
    dither_none = getattr(getattr(Image, "Dither", Image), "NONE", 0)
    try:
        p_frame = rgb.quantize(colors=255, method=quant_method, dither=dither_none)
    except TypeError:
        p_frame = rgb.quantize(colors=255, method=quant_method)
    mask = alpha.point(lambda a: 255 if a < 32 else 0)
    p_frame.paste(255, mask=mask)
    p_frame.info["transparency"] = 255
    return p_frame


def _extract_rgba_frames(raw_bytes: bytes, slot_size: int = EMOJI_SLOT_SIZE) -> tuple[list[Image.Image], list[int], int]:
    """정적 또는 움직이는 이모지 바이트에서 원본 모양 그대로의 RGBA 프레임 리스트·지연시간·반복횟수를 추출합니다."""
    with Image.open(io.BytesIO(raw_bytes)) as img:
        is_animated = getattr(img, "is_animated", False) and getattr(img, "n_frames", 1) > 1
        if not is_animated:
            rgba = img.convert("RGBA")
            return [_resize_rgba(rgba, slot_size)], [100], 0

        loop_count = int(img.info.get("loop", 0) or 0)
        composited_frames: list[Image.Image] = []
        durations: list[int] = []

        # Pillow ImageSequence.Iterator가 GIF/WebP 프레임 시퀀스 합성을 직접 처리하므로
        # 이중 alpha_composite 없이 그대로 RGBA 변환하여 원본 형태/모양을 100% 보존합니다.
        for frame in ImageSequence.Iterator(img):
            dur = int(frame.info.get("duration", img.info.get("duration", 80)) or 80)
            if dur < 20:
                dur = 80
            frame_rgba = frame.convert("RGBA")
            composited_frames.append(_resize_rgba(frame_rgba, slot_size))
            durations.append(dur)

    if not composited_frames:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            rgba = img.convert("RGBA")
            return [_resize_rgba(rgba, slot_size)], [100], 0
    return composited_frames, durations, loop_count


def _get_slot_size_for_count(count: int) -> int:
    """이모지 개수(1~3)에 맞는 각 이모지 목표 크기(px) 반환."""
    if count >= 3:
        return TRIPLE_SLOT_SIZE
    return STICKER_TARGET_SIZE


def _paste_sprites_on_sticker_canvas(
    sprites: list[Image.Image],
    canvas_w: Optional[int] = None,
    canvas_h: Optional[int] = None,
) -> Image.Image:
    """1~3개의 이모지를 불필요한 투명 여백 없이 실제 크기(160px 스티커 기준)에 딱 맞게 배치합니다."""
    items = sprites[:MAX_EMOJIS_PER_MESSAGE]
    slot_size = _get_slot_size_for_count(len(items))
    fitted: list[Image.Image] = []
    for sp in items:
        if sp.width > slot_size or sp.height > slot_size or max(sp.width, sp.height) != slot_size:
            fitted.append(_resize_rgba(sp, slot_size))
        else:
            fitted.append(sp)

    if len(fitted) == 1 and canvas_w is None and canvas_h is None:
        return fitted[0].copy()

    gap = 8
    tight_w = sum(sp.width for sp in fitted) + gap * max(0, len(fitted) - 1)
    tight_h = max(sp.height for sp in fitted)
    w = canvas_w or tight_w
    h = canvas_h or tight_h

    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    cur_x = 0
    for sp in fitted:
        dy = max(0, (h - sp.height) // 2)
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
    1~3개의 커스텀 이모지를 불필요한 투명 여백 없이 실제 크기 자체를 디스코드 스티커 크기(160px / 3개 시 128px)로 맞춥니다.
    정적 이모지는 무손실 PNG, 움직이는 이모지는 8-bit 알파를 보존하는 애니메이션 WebP(미지원 시 GIF 폴백)로 출력합니다.
    """
    if not raw_items:
        raise ValueError("empty raw_items")

    items = raw_items[:MAX_EMOJIS_PER_MESSAGE]
    slot_size = _get_slot_size_for_count(len(items))

    extracted = [_extract_rgba_frames(raw, slot_size=slot_size) for raw in items]
    has_anim = any(len(frames) > 1 for frames, _, _ in extracted)

    if not has_anim:
        canvas = _paste_sprites_on_sticker_canvas([frames[0] for frames, _, _ in extracted], canvas_w, canvas_h)
        out = io.BytesIO()
        canvas.save(out, format="PNG", optimize=True)
        return out.getvalue(), "png"

    # 애니메이션 프레임 타임라인 구성
    anim_entries = [(frames, durs, loop) for frames, durs, loop in extracted if len(frames) > 1]
    if len(anim_entries) == 1:
        base_frames, out_durations, loop_count = anim_entries[0]
        canvas_frames_rgba = []
        for idx in range(len(base_frames)):
            sprites = [
                frames[idx] if len(frames) > 1 else frames[0]
                for frames, _, _ in extracted
            ]
            canvas_frames_rgba.append(_paste_sprites_on_sticker_canvas(sprites, canvas_w, canvas_h))
    else:
        max_total = max(sum(durs) for _, durs, _ in anim_entries)
        step_ms = max(40, max_total // 48)
        n_steps = max(2, min(60, (max_total + step_ms - 1) // step_ms))
        out_durations = [step_ms] * n_steps
        loop_count = anim_entries[0][2]
        canvas_frames_rgba = []
        for step in range(n_steps):
            t_ms = step * step_ms
            sprites = [_sample_frame_at_time(frames, durs, t_ms) for frames, durs, _ in extracted]
            canvas_frames_rgba.append(_paste_sprites_on_sticker_canvas(sprites, canvas_w, canvas_h))

    # 1순위: 풀 8-bit 알파·원본 색상을 100% 보존하는 Animated WebP
    try:
        for webp_opts in (
            {"lossless": True, "method": 4},
            {"lossless": False, "quality": 92, "method": 4},
        ):
            out = io.BytesIO()
            canvas_frames_rgba[0].save(
                out,
                format="WEBP",
                save_all=True,
                append_images=canvas_frames_rgba[1:],
                duration=out_durations,
                loop=loop_count,
                **webp_opts,
            )
            webp_bytes = out.getvalue()
            if webp_bytes and len(webp_bytes) <= MAX_UPLOAD_BYTES:
                return webp_bytes, "webp"
    except Exception:
        pass

    # 2순위 폴백: 투명 GIF (용량 초과 방지용 단계적 스케일)
    base_w, base_h = canvas_frames_rgba[0].size
    last_bytes = b""
    for scale in (1.0, 0.85, 0.75):
        sw = max(64, int(round(base_w * scale)))
        sh = max(64, int(round(base_h * scale)))
        p_frames: list[Image.Image] = []
        for c_rgba in canvas_frames_rgba:
            fr = c_rgba if scale == 1.0 else c_rgba.resize((sw, sh), RESAMPLE_LANCZOS)
            p_frames.append(_rgba_frame_to_transparent_gif_frame(fr))

        out = io.BytesIO()
        p_frames[0].save(
            out,
            format="GIF",
            save_all=True,
            append_images=p_frames[1:],
            duration=out_durations,
            loop=loop_count,
            disposal=2,
            transparency=255,
            optimize=False,
        )
        last_bytes = out.getvalue()
        if len(last_bytes) <= MAX_UPLOAD_BYTES:
            return last_bytes, "gif"

    return last_bytes, "gif"


def upscale_static_emoji_bytes(raw_bytes: bytes, target_size: int = STATIC_TARGET_SIZE) -> tuple[bytes, str]:
    """단일 정적 이모지를 실제 160px 스티커 크기로 변환합니다."""
    return build_sticker_strip_bytes([raw_bytes])


def upscale_animated_emoji_bytes(raw_bytes: bytes, target_size: int = ANIMATED_TARGET_SIZE) -> tuple[bytes, str]:
    """단일 움직이는 이모지를 실제 160px 스티커 크기로 변환합니다."""
    return build_sticker_strip_bytes([raw_bytes])


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


def build_emoji_upscale_embed(guild: discord.Guild, channel: Optional[discord.abc.GuildChannel | discord.Thread], enabled: bool) -> discord.Embed:
    status_badge = "🟢 **ON (활성화됨)**" if enabled else "🔴 **OFF (비활성화됨 · 기본값)**"
    desc_lines = [
        "커스텀 디스코드 이모지(1~3개)만 포함된 채팅을 보내면 원본 메시지를 삭제한 뒤,",
        "이모지를 디스코드 스티커 크기(160px · 정적 PNG / 무손실 애니메이션 WebP)로 원본 모양 그대로 변환하여",
        "**보낸 사람의 프로필 사진과 서버 닉네임**으로 다시 전송합니다.",
        "• **🗑️ 삭제 방법:** 전송된 이모지 메시지에 직접 `:x:`(❌) 반응을 추가하면 즉시 삭제됩니다.",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"• **🏠 대상 서버:** `{guild.name}`",
        f"• **⚡ 현재 기능 상태:** {status_badge}",
        "• **🛡️ 변경 가능 권한:** 서버 관리자 (`Administrator` / `서버 관리`)",
        "• **🔒 기본 동작 정책:** 모든 서버 최초 기본값은 **OFF**입니다.",
    ]

    # 현재 채널 봇 권한 사전 진단
    if channel and guild.me and hasattr(channel, "permissions_for"):
        perms = channel.permissions_for(guild.me)
        missing = []
        if not perms.manage_messages:
            missing.append("메시지 관리(`Manage Messages` - 원본 이모지 삭제용)")
        if not perms.manage_webhooks:
            missing.append("웹후크 관리(`Manage Webhooks` - 발신자 프로필 재전송용)")
        if not perms.attach_files:
            missing.append("파일 첨부(`Attach Files` - 업스케일 이미지 업로드용)")
        if missing:
            desc_lines.append("")
            desc_lines.append("⚠️ **현재 채널 봇 권한 확인 필요:**")
            for m in missing:
                desc_lines.append(f"  - ❌ `{m}`")
        else:
            desc_lines.append("• **🤖 현재 채널 봇 권한:** ✅ 정상 작동 가능 (메시지 관리 · 웹후크 · 파일 첨부 보유)")

    desc_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    embed = discord.Embed(
        title="🔍 커스텀 이모지 업스케일 설정",
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


class EmojiUpscaleCog(commands.Cog, name="이모지업스케일"):
    """서버별 커스텀 이모지 고화질 업스케일 & 발신자 프로필 대리 전송 모듈"""

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
            self._http_session = aiohttp.ClientSession(timeout=timeout)
        return self._http_session

    async def _download_emoji_bytes(self, emoji_id: str, animated: bool) -> Optional[bytes]:
        session = await self._get_session()
        if animated:
            urls = [
                f"https://cdn.discordapp.com/emojis/{emoji_id}.webp?size=512&animated=true",
                f"https://cdn.discordapp.com/emojis/{emoji_id}.webp?size=256&animated=true",
                f"https://cdn.discordapp.com/emojis/{emoji_id}.webp?size=128&animated=true",
                f"https://cdn.discordapp.com/emojis/{emoji_id}.gif?size=512&quality=lossless",
                f"https://cdn.discordapp.com/emojis/{emoji_id}.gif?size=256",
                f"https://cdn.discordapp.com/emojis/{emoji_id}.gif?size=128",
            ]
        else:
            urls = [
                f"https://cdn.discordapp.com/emojis/{emoji_id}.png?size=512&quality=lossless",
                f"https://cdn.discordapp.com/emojis/{emoji_id}.webp?size=512&quality=lossless",
                f"https://cdn.discordapp.com/emojis/{emoji_id}.png?size=256",
                f"https://cdn.discordapp.com/emojis/{emoji_id}.png?size=128",
            ]

        for url in urls:
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        raw = await resp.read()
                        if raw and len(raw) > 16:
                            return raw
            except Exception:
                continue
        return None

    async def _build_sticker_strip_file(self, emojis: list[dict]) -> Optional[discord.File]:
        raw_list: list[bytes] = []
        for em in emojis[:MAX_EMOJIS_PER_MESSAGE]:
            raw = await self._download_emoji_bytes(em["id"], em["animated"])
            if not raw:
                return None
            raw_list.append(raw)

        out_bytes, ext = await asyncio.to_thread(build_sticker_strip_bytes, raw_list)
        if not out_bytes or len(out_bytes) > MAX_UPLOAD_BYTES:
            return None

        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", emojis[0]["name"])[:48] or "emoji"
        return discord.File(io.BytesIO(out_bytes), filename=f"{safe_name}.{ext}")

    async def _get_or_create_webhook(self, base_channel: discord.abc.GuildChannel) -> Optional[discord.Webhook]:
        cached = self._webhook_cache.get(base_channel.id)
        if cached is not None:
            return cached

        lock = self._webhook_locks.setdefault(base_channel.id, asyncio.Lock())
        async with lock:
            cached = self._webhook_cache.get(base_channel.id)
            if cached is not None:
                return cached

            try:
                webhooks = await base_channel.webhooks()
                existing = next((w for w in webhooks if w.name == WEBHOOK_NAME and w.token), None)
                if not existing:
                    # 채널 웹훅 한도(15개) 대비해 기존 봇이 만든 웹훅 중 token 있는 것 재사용 시도
                    existing = next((w for w in webhooks if w.user and self.bot.user and w.user.id == self.bot.user.id and w.token), None)
                if not existing:
                    existing = await base_channel.create_webhook(name=WEBHOOK_NAME, reason="이모지 업스케일 대리 전송용 웹훅")
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

        # 1. 이모지 다운로드 및 480x160 스티커 스트립 변환 먼저 수행 (실패 시 원본 메시지를 절대 삭제하지 않음)
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

        # 4. 보낸 사람 프로필 사진 & 닉네임으로 웹훅 전송 (버튼/자동 반응 추가 없이 순수 이미지만 전송)
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
            # 캐시된 웹훅이 삭제된 경우 캐시 무효화 후 1회 재생성 재시도
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
            # 재시작 전 등 매핑에 없는 메시지의 경우 업스케일 활성화 서버의 전용 웹훅 메시지인지 확인
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
            same_sender_fallback = bool(
                member and target_msg.author.display_name == sanitize_webhook_username(member.display_name)
            )
            if not (is_mod or is_owner or same_sender_fallback):
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
