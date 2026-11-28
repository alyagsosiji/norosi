"""
cogs/community.py - 관리자/커뮤니티 편의 & 보안 기능 6종
1. #8  📌 자동 고정 메시지 (/고정메시지 - 관리자 전용)
2. #12 🔗 SNS 링크 미리보기 보정 & 추적 파라미터 제거 (/링크미리보기)
3. #42 🚨 동시 입장(Raid) · 봇 테러 비상 방어 모드 (/비상모드 - 관리자 전용)
4. #48 ✍️ 한 줄씩 이어 쓰는 릴레이 소설 (/릴레이소설)
5. #11 🔊 임시 음성방 자동 생성기 — Join to Create (/임시음성방)
6. 🗓️ 예약 이벤트 신청표 (RSVP · 대기열 자동 승격 · 15분 전 자동 리마인드)
"""


from __future__ import annotations

import asyncio
from collections import OrderedDict
import datetime
import re
import time
import urllib.parse
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import community_core
import core
import sns_embed_core
from cogs.emoji_upscale import (
    build_reply_quote_header,
    is_delete_reaction_emoji,
    prewarm_webhook_avatar_cache,
    resolve_fresh_author,
    resolve_webhook_avatar_url,
    sanitize_webhook_username,
    send_webhook_with_verified_avatar,
)

CLEAN_LINK_WEBHOOK_NAME = "norosi-clean-link"

_MEDIA_UNFURL_HOSTS = frozenset({
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "music.youtube.com",
    "open.spotify.com",
    "soundcloud.com",
    "m.soundcloud.com",
    "twitch.tv",
    "www.twitch.tv",
    "clips.twitch.tv",
})


# ==========================================
# 🛡️ community_core 버전 호환성 자동 보정 (구버전 community_core.py 환경에서도 AttributeError 원천 차단)
# ==========================================
def _ensure_community_core_compat() -> None:
    if not hasattr(community_core, "STICKY_COLOR_MAP"):
        community_core.STICKY_COLOR_MAP = {
            "gold": 0xF1C40F,
            "blue": 0x3498DB,
            "green": 0x2ECC71,
            "pink": 0xFF69B4,
            "purple": 0x9B59B6,
            "red": 0xE74C3C,
        }
    if not hasattr(community_core, "STICKY_COLOR_LABELS"):
        community_core.STICKY_COLOR_LABELS = {
            "gold": "🌟 골드 (노랑)",
            "blue": "💙 블루 (파랑)",
            "green": "💚 그린 (초록)",
            "pink": "🩷 핑크 (분홍)",
            "purple": "💜 퍼플 (보라)",
            "red": "❤️ 레드 (빨강)",
        }
    if not hasattr(community_core, "RAID_ACTION_LABELS"):
        community_core.RAID_ACTION_LABELS = {
            "timeout": "⏳ 60분 타임아웃(활동 제한)",
            "kick": "👢 즉시 추방 (Kick)",
            "quarantine": "🔒 격리 역할 부여 (신규 격리)",
        }
    if not hasattr(community_core, "get_relay_completed_list") and hasattr(community_core, "get_completed_relay_novels"):
        community_core.get_relay_completed_list = community_core.get_completed_relay_novels
    if not hasattr(community_core, "get_relay_archives") and hasattr(community_core, "get_completed_relay_novels"):
        community_core.get_relay_archives = community_core.get_completed_relay_novels
    if not hasattr(community_core, "get_active_relay") and hasattr(community_core, "get_active_relay_novel"):
        def _compat_get_active_relay(data: dict, guild_id: int, channel_id: int = 0):
            if channel_id:
                st = community_core.get_active_relay_novel(data, guild_id, channel_id)
                if st:
                    return st
            g_root = core.as_dict(core.as_dict(data.get("relay_novels")).get(str(guild_id)))
            act = core.as_dict(g_root.get("active_channels"))
            for st in act.values():
                if isinstance(st, dict):
                    return st
            return None
        community_core.get_active_relay = _compat_get_active_relay


_ensure_community_core_compat()


# ==========================================
# 헬퍼: 관리자 권한 & 로그/알림 채널 탐색
# ==========================================
def _is_guild_admin(member: discord.abc.User, *, need_admin: bool = False, perm_attr: str = "manage_guild") -> bool:
    if core.BOT_OWNER_ID and getattr(member, "id", 0) == core.BOT_OWNER_ID:
        return True
    guild = getattr(member, "guild", None)
    if guild and getattr(guild, "owner_id", None) == getattr(member, "id", 0):
        return True
    perms = getattr(member, "guild_permissions", None)
    if not perms:
        return False
    if perms.administrator:
        return True
    if need_admin:
        return False
    return bool(getattr(perms, perm_attr, False))


def _is_strict_server_admin(member: discord.abc.User) -> bool:
    """서버 관리자(Administrator), 서버 소유자, 봇 주인 여부만 엄격히 확인합니다."""
    return _is_guild_admin(member, need_admin=True)


def _resolve_raid_alert_channel(guild: discord.Guild, cfg: dict, data: dict) -> Optional[discord.TextChannel]:
    cid = cfg.get("alert_channel_id")
    if cid:
        ch = guild.get_channel(int(cid))
        if isinstance(ch, discord.TextChannel) and ch.permissions_for(guild.me).send_messages:
            return ch

    # 서버 로그 설정의 mod_admin / members 채널 폴백
    s_logs = core.as_dict(core.as_dict(data.get("server_logs")).get(str(guild.id)))
    channels_map = core.as_dict(s_logs.get("channels"))
    for key in ("mod_admin", "members"):
        raw_id = channels_map.get(key)
        if raw_id and str(raw_id).isdigit():
            ch = guild.get_channel(int(raw_id))
            if isinstance(ch, discord.TextChannel) and ch.permissions_for(guild.me).send_messages:
                return ch
    legacy_id = s_logs.get("channel_id")
    if legacy_id and str(legacy_id).isdigit():
        ch = guild.get_channel(int(legacy_id))
        if isinstance(ch, discord.TextChannel) and ch.permissions_for(guild.me).send_messages:
            return ch

    sys_ch = getattr(guild, "system_channel", None)
    if isinstance(sys_ch, discord.TextChannel) and sys_ch.permissions_for(guild.me).send_messages:
        return sys_ch
    return None


def _build_sticky_embed(cfg: dict) -> discord.Embed:
    color_val = community_core.STICKY_COLOR_MAP.get(cfg.get("color", "gold"), 0xF1C40F)
    title_str = (cfg.get("title") or "").strip()
    embed = discord.Embed(
        title=title_str or None,
        description=cfg.get("content") or "",
        color=discord.Color(color_val),
    )
    return embed


def _build_relay_active_embed(story: dict) -> discord.Embed:
    turns = story.get("turns") or []
    cur_cnt = len(turns)
    max_turns = int(story.get("max_turns", 10) or 10)
    bar = community_core.format_relay_progress_bar(cur_cnt, max_turns)
    blind = bool(story.get("blind_mode", True))
    allow_consec = bool(story.get("allow_consecutive", False))
    last_turn = turns[-1] if turns else {}
    mode_label = "🔒 블라인드 모드 (직전 1줄만 공개)" if blind else "📖 전체 공개 모드"
    turn_rule = "자유 연속 작성 허용" if allow_consec else "연속 작성 금지 (번갈아 이어쓰기)"

    if blind:
        body = (
            f"### ✍️ 마지막으로 이어진 문장 ({cur_cnt}번째 줄)\n"
            f"> {last_turn.get('text', '')}\n\n"
            f"*(이전 줄거리는 완결 시 한 번에 공개됩니다! 직전 문장만 보고 상상력을 발휘해 이어 보세요!)*"
        )
    else:
        preview_lines = [f"**{i}.** {t.get('text', '')}" for i, t in enumerate(turns[-8:], start=max(1, cur_cnt - 7))]
        prefix = "*(... 앞부분 생략)*\n" if cur_cnt > 8 else ""
        body = "### 📖 지금까지의 줄거리\n" + prefix + "\n".join(preview_lines)

    embed = discord.Embed(
        title=f"✍️ 릴레이 소설: 『{story.get('title', '무제')}』",
        description=(
            f"• **진행률:** {bar} **`{cur_cnt} / {max_turns}턴`**\n"
            f"• **진행 방식:** {mode_label} · `{turn_rule}`\n"
            f"• **최근 작성자:** {last_turn.get('user_name', '작가')}\n"
            "────────────────\n"
            f"{body}"
        ),
        color=discord.Color.from_rgb(155, 89, 182),
        timestamp=datetime.datetime.now(core.KST),
    )
    embed.set_footer(text="아래 [✍️ 다음 줄 이어쓰기] 버튼을 눌러 한 줄을 보태 보세요!")
    return embed


def build_relay_novel_embed(guild_or_story, story: Optional[dict] = None) -> discord.Embed:
    """대시보드 및 외부 호출 호환용 헬퍼: (guild, story) 또는 (story,) 모두 지원"""
    target_story = story if isinstance(story, dict) else (guild_or_story if isinstance(guild_or_story, dict) else {})
    return _build_relay_active_embed(target_story)


def _build_relay_completed_embed(completed: dict) -> discord.Embed:
    turns = completed.get("turns") or []
    authors: list[str] = []
    seen_ids: set[int] = set()
    for t in turns:
        uid = int(t.get("user_id", 0) or 0)
        uname = t.get("user_name", "작가")
        if uid and uid not in seen_ids:
            seen_ids.add(uid)
            authors.append(f"<@{uid}>")
        elif not uid and uname not in authors:
            authors.append(uname)

    story_body = community_core.format_relay_full_story(completed)
    embed = discord.Embed(
        title=f"📕 완결 릴레이 소설: 『{completed.get('title', '무제')}』",
        description=(
            f"🎉 총 **{len(turns)}턴**의 문장이 모여 한 편의 릴레이 소설이 완성되었습니다!\n"
            f"👥 **참여 작가 ({len(authors)}명):** {', '.join(authors) if authors else completed.get('creator_name', '작가')}\n"
            "────────────────\n"
            f"{story_body}"
        ),
        color=discord.Color.gold(),
        timestamp=datetime.datetime.now(core.KST),
    )
    embed.set_footer(text="/설정 (🎮 미니게임 ➔ ✍️ 한 줄 릴레이 소설)에서 언제든 다시 읽어볼 수 있습니다.")
    return embed


# ==========================================
# 1. 📌 고정 메시지 설정 모달 (#8)
# ==========================================
class StickyConfigModal(core.SafeModal, title="📌 자동 고정 메시지 설정"):
    title_input = discord.ui.TextInput(
        label="고정 메시지 제목 (선택 · 비워두면 제목 생략)",
        placeholder="비워두면 제목 없이 본문만 표시됩니다 (예: 📌 채널 이용 안내)",
        required=False,
        max_length=120,
    )
    content_input = discord.ui.TextInput(
        label="고정 메시지 본문 내용",
        placeholder="새 채팅이 올라와도 채널 맨 아래에 항상 고정될 안내 문구를 입력하세요.",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1800,
    )
    interval_input = discord.ui.TextInput(
        label="몇 개 메시지 이후 갱신 (1~100 · 기본 1)",
        placeholder="예: 1 (매 메시지마다) / 5 (5개 메시지 쌓인 뒤)",
        required=False,
        max_length=4,
    )
    delay_input = discord.ui.TextInput(
        label="마지막 메시지 후 대기 초 (0~600초 · 0=즉시)",
        placeholder="예: 0 (즉시) / 5 (마지막 채팅 5초 뒤 조용할 때 갱신)",
        required=False,
        max_length=4,
    )

    def __init__(
        self,
        channel: discord.abc.GuildChannel,
        *,
        interval: int = 1,
        delay_sec: int = 0,
        trigger_mode: str = "count",
        cooldown_sec: int = 3,
        color: str = "gold",
        existing: Optional[dict] = None,
        parent_view: Optional["StickyDetailConfigView"] = None,
    ):
        super().__init__()
        self.channel = channel
        self.interval = int((existing or {}).get("interval", interval) or 1)
        self.delay_sec = int((existing or {}).get("delay_sec", delay_sec) or 0)
        self.trigger_mode = str((existing or {}).get("trigger_mode") or trigger_mode or "count")
        self.cooldown_sec = int((existing or {}).get("cooldown_sec", cooldown_sec) or 3)
        self.color = str((existing or {}).get("color") or color or "gold")
        self.parent_view = parent_view
        if existing:
            self.title_input.default = existing.get("title", "")[:120]
            self.content_input.default = existing.get("content", "")[:1800]
        self.interval_input.default = str(self.interval)
        self.delay_input.default = str(self.delay_sec)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not _is_guild_admin(interaction.user, perm_attr="manage_messages"):
            await core.safe_send_response(interaction, "❌ 메시지 관리 또는 관리자 권한이 필요합니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True, thinking=True)
        guild_id = interaction.guild.id
        channel_id = self.channel.id
        title_val = self.title_input.value
        content_val = self.content_input.value

        raw_iv = (self.interval_input.value or "").strip()
        parsed_iv = int(raw_iv) if raw_iv.isdigit() else self.interval
        parsed_iv = max(1, min(100, parsed_iv))

        raw_dl = (self.delay_input.value or "").strip()
        parsed_dl = int(raw_dl) if raw_dl.isdigit() else self.delay_sec
        parsed_dl = max(0, min(600, parsed_dl))

        eff_mode = self.trigger_mode
        if parsed_dl > 0 and parsed_iv > 1:
            eff_mode = "both"
        elif parsed_dl > 0 and eff_mode == "count":
            eff_mode = "delay"
        elif parsed_dl == 0 and eff_mode in ("delay", "both"):
            eff_mode = "count"

        def _get_prev_id():
            with core._DATA_LOCK:
                d = core.load_data()
                prev = community_core.get_sticky_config(d, guild_id, channel_id)
                return prev.get("last_message_id") if prev else None

        prev_msg_id = await asyncio.to_thread(_get_prev_id)
        if prev_msg_id:
            try:
                old_msg = await self.channel.fetch_message(int(prev_msg_id))
                await old_msg.delete()
            except Exception:
                pass

        preview_cfg = {
            "title": (title_val or "").strip()[:120],
            "content": (content_val or "").strip()[:1800],
            "color": self.color if self.color in community_core.STICKY_COLOR_MAP else "gold",
            "interval": parsed_iv,
            "delay_sec": parsed_dl,
            "trigger_mode": eff_mode,
        }
        try:
            posted = await self.channel.send(embed=_build_sticky_embed(preview_cfg))
        except discord.Forbidden:
            await interaction.followup.send(f"❌ {self.channel.mention} 채널에 메시지를 전송할 권한이 없습니다.", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"❌ 고정 메시지 전송 중 오류가 발생했습니다: `{e}`", ephemeral=True)
            return

        def _save_sticky():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.set_sticky_config(
                    data,
                    guild_id,
                    channel_id,
                    title_val,
                    content_val,
                    color=self.color,
                    interval=parsed_iv,
                    delay_sec=parsed_dl,
                    trigger_mode=eff_mode,
                    cooldown_sec=self.cooldown_sec,
                    updated_by=interaction.user.id,
                    last_message_id=posted.id,
                )
                cfg["last_posted_ts"] = time.time()
                cfg["enabled"] = True
                core.save_data(data)
                return dict(cfg)

        cfg = await asyncio.to_thread(_save_sticky)
        if self.parent_view is not None:
            self.parent_view.cfg = cfg
            self.parent_view._refresh_components()
            await interaction.followup.send(
                content=(
                    f"✅ {self.channel.mention} 채널에 **자동 고정 메시지**가 등록되어 하단에 게시되었습니다!\n"
                    f"• **갱신 조건:** {community_core.format_sticky_trigger_summary(cfg)} · "
                    f"**색상:** `{community_core.STICKY_COLOR_LABELS.get(cfg['color'], cfg['color'])}`"
                ),
                embed=self.parent_view.build_embed(),
                view=self.parent_view,
                ephemeral=True,
            )
            return

        view = StickyDetailConfigView(interaction.user.id, interaction.guild, self.channel, cfg)
        await interaction.followup.send(
            content=(
                f"✅ {self.channel.mention} 채널에 **자동 고정 메시지**가 등록되어 하단에 게시되었습니다!\n"
                f"아래 상세 설정 패널에서 **갱신 방식·메시지 개수·대기 시간(초)·색상**을 언제든 선택해 바꿀 수 있습니다."
            ),
            embed=view.build_embed(),
            view=view,
            ephemeral=True,
        )


class StickyDetailConfigView(core.SafeView):
    """자동 고정 메시지 상세 설정 패널 (갱신 방식·몇 개 메시지 이후·마지막 메시지 몇 초 뒤·색상·제목/본문 선택)"""

    def __init__(
        self,
        admin_id: int = 0,
        guild: Optional[discord.Guild] = None,
        channel: Optional[discord.abc.GuildChannel] = None,
        cfg: Optional[dict] = None,
    ):
        super().__init__(timeout=600)
        self.admin_id = admin_id
        self.guild = guild
        self.channel = channel
        self.cfg: dict = dict(cfg) if isinstance(cfg, dict) else {}
        self._refresh_components()

    def _ensure_context(self, interaction: discord.Interaction) -> bool:
        if self.guild is None:
            self.guild = interaction.guild
        if self.channel is None and isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            self.channel = interaction.channel
        if not self.cfg and self.guild and self.channel:
            d = core.get_cached_data_ro()
            found = community_core.get_sticky_config(d, self.guild.id, self.channel.id)
            if isinstance(found, dict):
                self.cfg = dict(found)
        return bool(self.guild and self.channel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not interaction.guild or not _is_guild_admin(interaction.user, perm_attr="manage_messages"):
            await core.safe_send_response(interaction, "❌ 메시지 관리 또는 서버 관리자 권한이 필요합니다.", ephemeral=True)
            return False
        self._ensure_context(interaction)
        return True

    def _refresh_components(self):
        mode = str(self.cfg.get("trigger_mode") or "count")
        iv = max(1, int(self.cfg.get("interval", 1) or 1))
        dl = max(0, int(self.cfg.get("delay_sec", 0) or 0))
        color = str(self.cfg.get("color") or "gold")
        enabled = bool(self.cfg.get("enabled", True)) if self.cfg else False

        self.mode_select.options = [
            discord.SelectOption(
                label=lbl,
                value=k,
                default=(mode == k),
            )
            for k, lbl in community_core.STICKY_TRIGGER_MODE_LABELS.items()
        ]

        iv_presets = [1, 2, 3, 5, 10, 15, 20, 30, 50]
        if iv not in iv_presets:
            iv_presets = sorted(set(iv_presets + [iv]))
        self.interval_select.options = [
            discord.SelectOption(
                label=f"💬 {n}개 메시지 이후 갱신" + (" (매 메시지마다)" if n == 1 else ""),
                value=str(n),
                default=(iv == n),
            )
            for n in iv_presets[:25]
        ]

        dl_presets = [0, 3, 5, 10, 15, 30, 60, 120, 300]
        if dl not in dl_presets:
            dl_presets = sorted(set(dl_presets + [dl]))
        self.delay_select.options = [
            discord.SelectOption(
                label=("⚡ 대기 시간 없음 (0초 · 조건 충족 즉시)" if s == 0 else f"⏱️ 마지막 메시지로부터 {s}초 뒤 갱신"),
                value=str(s),
                default=(dl == s),
            )
            for s in dl_presets[:25]
        ]

        self.color_select.options = [
            discord.SelectOption(
                label=f"🎨 임베드 색상: {lbl}",
                value=k,
                default=(color == k),
            )
            for k, lbl in community_core.STICKY_COLOR_LABELS.items()
        ]

        if self.cfg:
            self.btn_toggle.disabled = False
            self.btn_remove.disabled = False
            self.btn_toggle.label = "⏸️ 일시 중지" if enabled else "🟢 다시 켜기"
            self.btn_toggle.style = discord.ButtonStyle.secondary if enabled else discord.ButtonStyle.success
        else:
            self.btn_toggle.disabled = True
            self.btn_remove.disabled = True
            self.btn_toggle.label = "🔄 켜기/중지"
            self.btn_toggle.style = discord.ButtonStyle.secondary

    def build_embed(self) -> discord.Embed:
        ch_mention = self.channel.mention if self.channel else "현재 채널"
        if not self.cfg:
            return discord.Embed(
                title="📌 자동 고정 메시지 상세 설정",
                description=(
                    f"대상 채널: {ch_mention}\n"
                    f"현재 등록된 자동 고정 메시지가 없습니다.\n\n"
                    f"아래 **`[✏️ 제목·본문·수치 작성]`** 버튼을 눌러 고정 메시지를 등록하고,\n"
                    f"드롭다운에서 **갱신 방식 · 메시지 개수 · 마지막 메시지 후 대기 초 · 색상**을 자유롭게 선택하세요!"
                ),
                color=discord.Color.gold(),
            )
        enabled = bool(self.cfg.get("enabled", True))
        status_str = "🟢 활성화 (작동 중)" if enabled else "🔴 일시 중지됨"
        title_str = (self.cfg.get("title") or "").strip() or "*(제목 없음 — 본문만 표시)*"
        content_preview = (self.cfg.get("content") or "").strip()
        if len(content_preview) > 300:
            content_preview = content_preview[:300] + "…"
        color_key = str(self.cfg.get("color") or "gold")
        color_lbl = community_core.STICKY_COLOR_LABELS.get(color_key, color_key)
        color_val = community_core.STICKY_COLOR_MAP.get(color_key, 0xF1C40F)

        embed = discord.Embed(
            title="📌 자동 고정 메시지 상세 설정 패널",
            description=(
                f"• **대상 채널:** {ch_mention} (`{status_str}`)\n"
                f"• **갱신 조건:** {community_core.format_sticky_trigger_summary(self.cfg)}\n"
                f"• **메시지 기준:** `{self.cfg.get('interval', 1)}개` 메시지 이후 · "
                f"**대기 시간:** 마지막 메시지로부터 `{self.cfg.get('delay_sec', 0)}초` 뒤\n"
                f"• **임베드 색상:** `{color_lbl}`\n"
                f"• **제목:** {title_str}\n"
                f"• **본문 미리보기:**\n>>> {content_preview or '*(내용 없음)*'}"
            ),
            color=discord.Color(color_val),
        )
        return embed

    async def _update_cfg_fields(self, interaction: discord.Interaction, **updates):
        if not self._ensure_context(interaction):
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = self.guild.id
        channel_id = self.channel.id

        def _mutate():
            with core._DATA_LOCK:
                data = core.load_data()
                cur = community_core.get_sticky_config(data, guild_id, channel_id)
                if not cur:
                    return None
                for k, v in updates.items():
                    cur[k] = v
                if cur.get("trigger_mode") in ("delay", "both") and int(cur.get("delay_sec", 0) or 0) <= 0:
                    cur["delay_sec"] = 5
                cur["updated_by"] = interaction.user.id
                cur["updated_at"] = datetime.datetime.now(core.KST).isoformat()
                core.save_data(data)
                return dict(cur)

        updated = await asyncio.to_thread(_mutate)
        if not updated:
            for k, v in updates.items():
                self.cfg[k] = v
            self._refresh_components()
            await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
            await core.safe_send_response(
                interaction,
                "ℹ️ 아직 본문이 등록되지 않았습니다. `[✏️ 제목·본문·수치 작성]` 버튼을 눌러 고정 메시지를 게시해 주세요!",
                ephemeral=True,
            )
            return

        self.cfg = updated
        self._refresh_components()
        # 색상 등 시각 항목 변경 시 채널에 게시된 현재 고정 메시지도 즉시 갱신
        if ("color" in updates) and updated.get("last_message_id") and self.channel:
            try:
                live_msg = await self.channel.fetch_message(int(updated["last_message_id"]))
                await live_msg.edit(embed=_build_sticky_embed(updated))
            except Exception:
                pass
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.select(placeholder="⚙️ 갱신 작동 방식 선택 (개수 기준 / 초 뒤 대기 / 복합)...", row=0)
    async def mode_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        chosen = select.values[0]
        extra = {}
        if chosen in ("delay", "both") and int(self.cfg.get("delay_sec", 0) or 0) <= 0:
            extra["delay_sec"] = 5
        await self._update_cfg_fields(interaction, trigger_mode=chosen, **extra)

    @discord.ui.select(placeholder="💬 몇 개 메시지 이후 갱신할지 선택 (1~50개)...", row=1)
    async def interval_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        iv = max(1, min(100, int(select.values[0])))
        cur_mode = str(self.cfg.get("trigger_mode") or "count")
        dl = int(self.cfg.get("delay_sec", 0) or 0)
        new_mode = "both" if (cur_mode == "delay" and iv > 1 and dl > 0) else cur_mode
        await self._update_cfg_fields(interaction, interval=iv, trigger_mode=new_mode)

    @discord.ui.select(placeholder="⏱️ 마지막 메시지로부터 몇 초 뒤 갱신할지 선택 (0~300초)...", row=2)
    async def delay_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        dl = max(0, min(600, int(select.values[0])))
        iv = max(1, int(self.cfg.get("interval", 1) or 1))
        if dl == 0:
            new_mode = "count"
        elif iv > 1:
            new_mode = "both"
        else:
            new_mode = "delay"
        await self._update_cfg_fields(interaction, delay_sec=dl, trigger_mode=new_mode)

    @discord.ui.select(placeholder="🎨 고정 메시지 임베드 색상 선택...", row=3)
    async def color_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await self._update_cfg_fields(interaction, color=select.values[0])

    @discord.ui.button(label="✏️ 제목·본문·수치 작성", style=discord.ButtonStyle.primary, row=4)
    async def btn_edit_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._ensure_context(interaction):
            return
        modal = StickyConfigModal(
            self.channel,
            interval=int(self.cfg.get("interval", 1) or 1),
            delay_sec=int(self.cfg.get("delay_sec", 0) or 0),
            trigger_mode=str(self.cfg.get("trigger_mode") or "count"),
            cooldown_sec=int(self.cfg.get("cooldown_sec", 3) or 3),
            color=str(self.cfg.get("color") or "gold"),
            existing=self.cfg or None,
            parent_view=self,
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🔄 켜기/중지", style=discord.ButtonStyle.secondary, row=4)
    async def btn_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._ensure_context(interaction):
            return
        new_state = not bool(self.cfg.get("enabled", True))
        await self._update_cfg_fields(interaction, enabled=new_state)

    @discord.ui.button(label="🗑️ 고정 해제", style=discord.ButtonStyle.danger, row=4)
    async def btn_remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._ensure_context(interaction):
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = self.guild.id
        channel_id = self.channel.id

        def _rem():
            with core._DATA_LOCK:
                d = core.load_data()
                removed = community_core.remove_sticky_config(d, guild_id, channel_id)
                if removed:
                    core.save_data(d)
                return removed

        removed = await asyncio.to_thread(_rem)
        if removed and removed.get("last_message_id"):
            try:
                old_msg = await self.channel.fetch_message(int(removed["last_message_id"]))
                await old_msg.delete()
            except Exception:
                pass
        self.cfg = {}
        self._refresh_components()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


# ==========================================
# 2. 🔗 링크 미리보기 UI & 삭제 버튼 (#12)
# ==========================================
class LinkCleanupView(core.SafeView):
    """원본 작성자 또는 관리자가 봇의 링크 변환 답글을 지울 수 있는 영구 버튼"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="링크 메시지 닫기",
        style=discord.ButtonStyle.secondary,
        emoji="🗑️",
        custom_id="norosi:LinkCleanupView:delete",
        row=0,
    )
    async def delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        allowed = _is_guild_admin(interaction.user, perm_attr="manage_messages")
        if not allowed and interaction.message and interaction.message.reference:
            ref = interaction.message.reference
            ref_msg = ref.resolved if isinstance(ref.resolved, discord.Message) else None
            if ref_msg is None and ref.message_id and interaction.channel:
                try:
                    ref_msg = await interaction.channel.fetch_message(ref.message_id)
                except Exception:
                    ref_msg = None
            if ref_msg and ref_msg.author.id == interaction.user.id:
                allowed = True

        if not allowed:
            await core.safe_send_response(
                interaction,
                "❌ 원본 링크를 올린 작성자 또는 메시지 관리 권한을 가진 관리자만 삭제할 수 있습니다.",
                ephemeral=True,
            )
            return

        await core.safe_defer(interaction, ephemeral=True)
        try:
            if interaction.message:
                await interaction.message.delete()
        except Exception as e:
            await interaction.followup.send(f"❌ 메시지 삭제 실패: `{e}`", ephemeral=True)


class LinkPreviewChannelIgnoreSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="링크 변환에서 제외/포함할 텍스트 채널을 선택하세요...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1,
            max_values=1,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "LinkPreviewConfigView" = self.view
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 설정할 수 있습니다.", ephemeral=True)
            return
        if not _is_guild_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 서버 관리자만 설정할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        ch = self.values[0]
        guild_id = interaction.guild.id

        def _toggle_ignore():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.get_link_preview_config(data, guild_id)
                ignored = set(cfg["ignored_channels"])
                if ch.id in ignored:
                    ignored.remove(ch.id)
                    msg = f"✅ <#{ch.id}> 채널의 링크 미리보기/정리 제외가 **해제**되었습니다."
                else:
                    ignored.add(ch.id)
                    msg = f"🚫 <#{ch.id}> 채널이 링크 미리보기/정리 **제외 목록**에 추가되었습니다."
                cfg["ignored_channels"] = sorted(ignored)
                saved = community_core.save_link_preview_config(data, guild_id, cfg)
                core.save_data(data)
                return saved, msg

        saved, msg = await asyncio.to_thread(_toggle_ignore)
        view.cfg = saved
        await interaction.edit_original_response(embed=view.build_embed(), view=view)
        await interaction.followup.send(msg, ephemeral=True)


class LinkPreviewConfigView(core.SafeView):
    def __init__(self, author_id: int = 0, guild: Optional[discord.Guild] = None, cfg: Optional[dict] = None):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.guild = guild
        self.cfg = cfg if isinstance(cfg, dict) else community_core.get_link_preview_config(core.get_cached_data(), getattr(guild, "id", 0))
        self.add_item(LinkPreviewChannelIgnoreSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if interaction.user.id != self.author_id and not _is_guild_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 관리자만 설정 패널을 조작할 수 있습니다.", ephemeral=True)
            return False
        if self.guild is None and interaction.guild:
            self.guild = interaction.guild
        if interaction.guild:
            self.cfg = community_core.get_link_preview_config(core.get_cached_data(), interaction.guild.id)
        return True

    def build_embed(self) -> discord.Embed:
        c = self.cfg
        gname = getattr(self.guild, "name", None) or "서버"
        ignored_str = ", ".join(f"<#{cid}>" for cid in c.get("ignored_channels", [])) or "없음"
        embed = discord.Embed(
            title=f"🔗 [{gname}] SNS 링크 미리보기 & 추적 제거 설정",
            description=(
                "• **전체 기능:** " + ("🟢 활성화됨" if c["enabled"] else "🔴 비활성화됨") + "\n"
                "• **SNS 리치 카드 보정:** " + ("🟢 켜짐" if c["sns_preview"] else "⚪ 꺼짐")
                + " *(X/Twitter, Instagram, TikTok, Threads, Reddit, Pixiv, Bluesky, YouTube Shorts, Facebook, Pinterest)*\n"
                "• **추적 파라미터 제거:** " + ("🟢 켜짐" if c["strip_tracking"] else "⚪ 꺼짐")
                + " *(`?si=`, `?igsh=`, `?utm_*`, `?fbclid=`, `?s=&t=` 등)*\n"
                "• **원본 삭제 · 깔끔 치환:** " + ("🟢 켜짐 *(이모지 업스케일 방식)*" if c["suppress_original"] else "⚪ 꺼짐 *(답글만 표시)*") + "\n"
                f"• **제외된 채널:** {ignored_str}\n\n"
                "💡 일반 메시지는 작성자 프로필·닉네임 웹훅으로, 답장 메시지는 앱 네이티브 답장으로 깔끔 치환됩니다.\n"
                "💡 치환된 메시지에 ❌(`:x:`) 반응을 달면 작성자/관리자가 즉시 삭제할 수 있으며, `<링크>` · `||스포일러||` · `코드블록` 은 자동 제외됩니다."
            ),
            color=discord.Color.blue() if c["enabled"] else discord.Color.dark_grey(),
            timestamp=datetime.datetime.now(core.KST),
        )
        return embed

    async def _toggle_key(self, interaction: discord.Interaction, key: str):
        guild_id = getattr(self.guild, "id", 0) or interaction.guild_id or 0
        if not guild_id:
            await core.safe_send_response(interaction, "❌ 서버 정보를 확인할 수 없습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)

        def _do_toggle():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.get_link_preview_config(data, guild_id)
                cfg[key] = not cfg.get(key, True)
                saved = community_core.save_link_preview_config(data, guild_id, cfg)
                core.save_data(data)
                return saved

        self.cfg = await asyncio.to_thread(_do_toggle)
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="전체 ON/OFF", style=discord.ButtonStyle.primary, emoji="⚡", row=0)
    async def toggle_enabled(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle_key(interaction, "enabled")

    @discord.ui.button(label="SNS 미리보기", style=discord.ButtonStyle.secondary, emoji="🖼️", row=0)
    async def toggle_sns(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle_key(interaction, "sns_preview")

    @discord.ui.button(label="추적 태그 제거", style=discord.ButtonStyle.secondary, emoji="🧹", row=0)
    async def toggle_tracking(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle_key(interaction, "strip_tracking")

    @discord.ui.button(label="원본 삭제·치환", style=discord.ButtonStyle.secondary, emoji="✨", row=1)
    async def toggle_suppress(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle_key(interaction, "suppress_original")


# ==========================================
# 3. 🚨 동시 입장(Raid) 비상 방어 UI (#42)
# ==========================================
class RaidAlertControlView(core.SafeView):
    """비상모드 알림 임베드에 첨부되는 영구 제어 버튼"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="비상모드 즉시 해제",
        style=discord.ButtonStyle.success,
        emoji="🔓",
        custom_id="norosi:RaidAlertControlView:unlock",
        row=0,
    )
    async def unlock_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not _is_guild_admin(interaction.user, need_admin=True):
            await core.safe_send_response(interaction, "❌ 서버 관리자(Administrator)만 비상모드를 해제할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild.id

        def _read_cfg():
            with core._DATA_LOCK:
                d = core.load_data()
                return community_core.get_raid_defense_config(d, guild_id)

        cfg = await asyncio.to_thread(_read_cfg)
        if not cfg["lockdown_active"]:
            await interaction.followup.send("ℹ️ 현재 비상모드가 이미 해제된 상태입니다.", ephemeral=True)
            return

        restored_invites = False
        if cfg.get("invites_paused_by_bot") and interaction.guild.me.guild_permissions.manage_guild:
            try:
                await interaction.guild.edit(invites_disabled=False, reason=f"비상모드 해제 ({interaction.user})")
                restored_invites = True
            except Exception:
                pass

        def _save_unlock():
            with core._DATA_LOCK:
                data = core.load_data()
                fresh_cfg = community_core.get_raid_defense_config(data, guild_id)
                fresh_cfg["lockdown_active"] = False
                fresh_cfg["invites_paused_by_bot"] = False
                community_core.save_raid_defense_config(data, guild_id, fresh_cfg)
                core.save_data(data)

        await asyncio.to_thread(_save_unlock)
        community_core.RAID_TRACKER.clear_guild(guild_id)

        note = " · 서버 초대 링크도 함께 복구되었습니다." if restored_invites else ""
        if interaction.message:
            try:
                done_embed = discord.Embed(
                    title="🔓 서버 비상 방어 모드 해제 완료",
                    description=f"👮 **해제 관리자:** {interaction.user.mention}{note}",
                    color=discord.Color.green(),
                    timestamp=datetime.datetime.now(core.KST),
                )
                await interaction.message.edit(embed=done_embed, view=None)
            except Exception:
                pass
        await interaction.followup.send(f"🔓 비상모드가 해제되었습니다{note}", ephemeral=True)

    @discord.ui.button(
        label="최근 차단 기록",
        style=discord.ButtonStyle.secondary,
        emoji="📋",
        custom_id="norosi:RaidAlertControlView:logs",
        row=0,
    )
    async def view_logs_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not _is_guild_admin(interaction.user, need_admin=True):
            await core.safe_send_response(interaction, "❌ 서버 관리자(Administrator)만 조회할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        cfg = community_core.get_raid_defense_config(data, interaction.guild.id)
        logs = cfg.get("blocked_log") or []
        if not logs:
            await interaction.followup.send("📭 최근 비상 방어로 제재된 입장 기록이 없습니다.", ephemeral=True)
            return
        lines = [
            f"• `[{entry.get('ts', '-')}]` <@{entry.get('user_id', 0)}> (`{entry.get('user_name', '')}`) → **{entry.get('action', '')}** ({entry.get('reason', '')})"
            for entry in reversed(logs[-15:])
        ]
        embed = discord.Embed(
            title=f"🛡️ [{interaction.guild.name}] 최근 비상 방어 조치 기록",
            description="\n".join(lines),
            color=discord.Color.orange(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


class RaidThresholdModal(core.SafeModal, title="⚙️ 레이드 감지 기준 설정"):
    threshold_input = discord.ui.TextInput(
        label="감지 인원 수 (3~30명)",
        placeholder="예: 5 (10초 내 5명 이상 동시 입장 시 발동)",
        required=True,
        max_length=3,
    )
    window_input = discord.ui.TextInput(
        label="감지 시간 창(초, 5~60초)",
        placeholder="예: 10",
        required=True,
        max_length=3,
    )
    min_age_input = discord.ui.TextInput(
        label="신규 계정 자동 방어 기준(일, 0=사용 안 함)",
        placeholder="예: 3 (가입 3일 미만 계정이 레이드 외 일반 입장 시에도 격리/타임아웃, 0이면 미사용)",
        required=True,
        max_length=3,
    )

    def __init__(self, parent_view: "RaidDefenseConfigView"):
        super().__init__()
        self.parent_view = parent_view
        cfg = parent_view.cfg if isinstance(getattr(parent_view, "cfg", None), dict) else {}
        self.threshold_input.default = str(cfg.get("threshold", 5))
        self.window_input.default = str(cfg.get("window_sec", 10))
        self.min_age_input.default = str(cfg.get("min_account_age_days", 0))

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not _is_guild_admin(interaction.user, need_admin=True):
            await core.safe_send_response(interaction, "❌ 서버 관리자(Administrator)만 레이드 감지 기준을 설정할 수 있습니다.", ephemeral=True)
            return
        try:
            th = int(self.threshold_input.value.strip())
            win = int(self.window_input.value.strip())
            age = int(self.min_age_input.value.strip())
        except ValueError:
            await core.safe_send_response(interaction, "❌ 숫자만 입력해 주세요.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        guild_id = interaction.guild.id

        def _save_thresholds():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.get_raid_defense_config(data, guild_id)
                cfg["threshold"] = max(3, min(30, th))
                cfg["window_sec"] = max(5, min(60, win))
                cfg["min_account_age_days"] = max(0, min(365, age))
                saved = community_core.save_raid_defense_config(data, guild_id, cfg)
                core.save_data(data)
                return saved

        self.parent_view.cfg = await asyncio.to_thread(_save_thresholds)
        await interaction.edit_original_response(embed=self.parent_view.build_embed(), view=self.parent_view)


class RaidAlertChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="🚨 긴급 알림을 받을 채널 선택...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1,
            max_values=1,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "RaidDefenseConfigView" = self.view
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 설정할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        ch = self.values[0]
        guild_id = interaction.guild.id

        def _save_alert_ch():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.get_raid_defense_config(data, guild_id)
                cfg["alert_channel_id"] = ch.id
                saved = community_core.save_raid_defense_config(data, guild_id, cfg)
                core.save_data(data)
                return saved

        view.cfg = await asyncio.to_thread(_save_alert_ch)
        await interaction.edit_original_response(embed=view.build_embed(), view=view)


class RaidQuarantineRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="🔒 '격리 역할 부여' 대응 시 지급할 역할 선택...",
            min_values=1,
            max_values=1,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "RaidDefenseConfigView" = self.view
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 설정할 수 있습니다.", ephemeral=True)
            return
        role = self.values[0]
        if role.is_default() or role.managed or role.permissions.administrator or role.permissions.manage_guild or role.permissions.manage_roles:
            await core.safe_send_response(interaction, "❌ 관리자/서버관리 권한이 포함된 역할이나 봇 전용 역할은 격리 역할로 지정할 수 없습니다.", ephemeral=True)
            return
        if interaction.guild.me and role >= interaction.guild.me.top_role:
            await core.safe_send_response(interaction, "❌ 봇의 최고 역할보다 높거나 같은 역할은 부여할 수 없습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        guild_id = interaction.guild.id

        def _save_qrole():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.get_raid_defense_config(data, guild_id)
                cfg["quarantine_role_id"] = role.id
                saved = community_core.save_raid_defense_config(data, guild_id, cfg)
                core.save_data(data)
                return saved

        view.cfg = await asyncio.to_thread(_save_qrole)
        await interaction.edit_original_response(embed=view.build_embed(), view=view)


class RaidActionSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="60분 타임아웃 (채팅/음성 차단)", value="timeout", emoji="⏳"),
            discord.SelectOption(label="즉시 추방 (Kick)", value="kick", emoji="👢"),
            discord.SelectOption(label="격리 역할 부여", value="quarantine", emoji="🔒"),
        ]
        super().__init__(placeholder="⚔️ 감지·비상모드 시 자동 대응 방식 선택", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        view: "RaidDefenseConfigView" = self.view
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 설정할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        guild_id = interaction.guild.id
        action_val = self.values[0]

        def _save_action():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.get_raid_defense_config(data, guild_id)
                cfg["action"] = action_val
                saved = community_core.save_raid_defense_config(data, guild_id, cfg)
                core.save_data(data)
                return saved

        view.cfg = await asyncio.to_thread(_save_action)
        await interaction.edit_original_response(embed=view.build_embed(), view=view)


class RaidDefenseConfigView(core.SafeView):
    def __init__(self, author_id: int = 0, guild: Optional[discord.Guild] = None, cfg: Optional[dict] = None):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.guild = guild
        self.cfg = cfg if isinstance(cfg, dict) else community_core.get_raid_defense_config(core.get_cached_data(), getattr(guild, "id", 0))
        self.add_item(RaidActionSelect())
        self.add_item(RaidAlertChannelSelect())
        self.add_item(RaidQuarantineRoleSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not _is_guild_admin(interaction.user, need_admin=True):
            await core.safe_send_response(interaction, "❌ 서버 관리자(Administrator)만 비상 방어 설정을 변경할 수 있습니다.", ephemeral=True)
            return False
        if self.guild is None and interaction.guild:
            self.guild = interaction.guild
        if interaction.guild:
            self.cfg = community_core.get_raid_defense_config(core.get_cached_data(), interaction.guild.id)
        return True

    def build_embed(self) -> discord.Embed:
        c = self.cfg
        gname = getattr(self.guild, "name", None) or "서버"
        gid = getattr(self.guild, "id", 0) or 0
        rate = community_core.RAID_TRACKER.current_rate(gid, c.get("window_sec", 10)) if gid else 0
        alert_str = f"<#{c['alert_channel_id']}>" if c.get("alert_channel_id") else "자동 (서버로그/시스템 채널)"
        qrole_str = f"<@&{c['quarantine_role_id']}>" if c.get("quarantine_role_id") else "미지정 *(미지정 시 60분 타임아웃으로 폴백)*"
        age_str = f"`{c['min_account_age_days']}일 미만`" if c.get("min_account_age_days", 0) > 0 else "사용 안 함 (`0일`)"
        lock_str = "🚨 **비상 잠금 발동 중!**" if c.get("lockdown_active") else "🟢 평상시 (정상)"
        embed = discord.Embed(
            title=f"🛡️ [{gname}] 동시 입장(Raid) · 테러 비상 방어 설정",
            description=(
                f"• **현재 상태:** {lock_str}\n"
                f"• **실시간 입장 빈도:** 최근 `{c['window_sec']}초` 내 **`{rate}명`** 입장 (임계치: `{c['threshold']}명`)\n"
                f"• **자동 레이드 감지:** {'🟢 활성화됨' if c['enabled'] else '🔴 비활성화됨'}\n"
                f"• **감지 임계값:** **`{c['window_sec']}초` 내 `{c['threshold']}명` 이상 동시 입장**\n"
                f"• **발동 시 대응 조치:** `{community_core.RAID_ACTION_LABELS.get(c['action'], c['action'])}`\n"
                f"• **발동 시 초대 일시정지:** {'🟢 자동 중지 시도' if c['pause_invites'] else '⚪ 사용 안 함'}\n"
                f"• **신규 계정 자동 방어:** {age_str}\n"
                f"• **긴급 알림 채널:** {alert_str}\n"
                f"• **격리 역할:** {qrole_str}"
            ),
            color=discord.Color.red() if c.get("lockdown_active") else (discord.Color.green() if c["enabled"] else discord.Color.dark_grey()),
            timestamp=datetime.datetime.now(core.KST),
        )
        logs = c.get("blocked_log") or []
        if logs:
            recent_txt = "\n".join(
                f"• `[{b.get('ts', '-')}]` `{b.get('user_name', '')}` — **{b.get('action', '')}** ({b.get('reason', '')})"
                for b in reversed(logs[-5:])
            )
            embed.add_field(name="🛡️ 최근 방어 조치 (최대 5건)", value=recent_txt[:1024], inline=False)
        return embed

    @discord.ui.button(label="자동감지 ON/OFF", style=discord.ButtonStyle.primary, emoji="🤖", row=0)
    async def toggle_auto(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = getattr(self.guild, "id", 0) or interaction.guild_id or 0
        if not guild_id:
            await core.safe_send_response(interaction, "❌ 서버 정보를 확인할 수 없습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)

        def _do_toggle():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.get_raid_defense_config(data, guild_id)
                cfg["enabled"] = not cfg.get("enabled", False)
                saved = community_core.save_raid_defense_config(data, guild_id, cfg)
                core.save_data(data)
                return saved

        self.cfg = await asyncio.to_thread(_do_toggle)
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="초대 중지 ON/OFF", style=discord.ButtonStyle.secondary, emoji="⛔", row=0)
    async def toggle_pause_invites(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = getattr(self.guild, "id", 0) or interaction.guild_id or 0
        if not guild_id:
            await core.safe_send_response(interaction, "❌ 서버 정보를 확인할 수 없습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)

        def _do_toggle():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.get_raid_defense_config(data, guild_id)
                cfg["pause_invites"] = not cfg.get("pause_invites", True)
                saved = community_core.save_raid_defense_config(data, guild_id, cfg)
                core.save_data(data)
                return saved

        self.cfg = await asyncio.to_thread(_do_toggle)
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="인원/시간/계정연령 설정", style=discord.ButtonStyle.secondary, emoji="⚙️", row=0)
    async def edit_threshold(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RaidThresholdModal(self))

    @discord.ui.button(label="수동 비상잠금 발동", style=discord.ButtonStyle.danger, emoji="🚨", row=4)
    async def manual_lockdown_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("CommunityCog") if interaction.client else None
        if cog and hasattr(cog, "raid_lockdown_cmd"):
            await cog.raid_lockdown_cmd.callback(cog, interaction, 사유="관리자 설정 패널에서 수동 비상잠금 발동")
            return
        await core.safe_send_response(interaction, "❌ 비상모드 모듈을 찾을 수 없습니다.", ephemeral=True)

    @discord.ui.button(label="비상잠금 해제", style=discord.ButtonStyle.success, emoji="🔓", row=4)
    async def manual_unlock_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("CommunityCog") if interaction.client else None
        if cog and hasattr(cog, "raid_unlock_cmd"):
            await cog.raid_unlock_cmd.callback(cog, interaction)
            return
        await core.safe_send_response(interaction, "❌ 비상모드 모듈을 찾을 수 없습니다.", ephemeral=True)

    @discord.ui.button(label="차단 기록 & 상태 새로고침", style=discord.ButtonStyle.secondary, emoji="📋", row=4)
    async def refresh_raid_status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = getattr(self.guild, "id", 0) or interaction.guild_id or 0
        if not guild_id:
            await core.safe_send_response(interaction, "❌ 서버 정보를 확인할 수 없습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        self.cfg = community_core.get_raid_defense_config(data, guild_id)
        await interaction.edit_original_response(embed=self.build_embed(), view=self)


# ==========================================
# 4. ✍️ 한 줄씩 이어 쓰는 릴레이 소설 UI (#48)
# ==========================================
class RelayWriteModal(core.SafeModal, title="✍️ 릴레이 소설 다음 줄 이어쓰기"):
    sentence_input = discord.ui.TextInput(
        label="이어 쓸 한 문장 입력 (2~280자)",
        placeholder="이전 문장의 분위기를 살려 흥미진진하거나 엉뚱하게 이어 보세요!",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=280,
    )

    def __init__(self, last_line: str = ""):
        super().__init__()
        if last_line:
            hint = last_line if len(last_line) <= 85 else (last_line[:82] + "...")
            self.sentence_input.placeholder = f"직전 문장: \"{hint}\""

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 참여할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        guild_id = interaction.guild.id
        channel_id = interaction.channel.id
        sentence_val = self.sentence_input.value

        def _append_turn():
            with core._DATA_LOCK:
                data = core.load_data()
                ok, msg, story_obj, is_completed = community_core.append_relay_turn(
                    data,
                    guild_id,
                    channel_id,
                    interaction.user.id,
                    interaction.user.display_name,
                    sentence_val,
                )
                if ok and story_obj:
                    core.save_data(data)
                return ok, msg, story_obj, is_completed

        ok, msg, story_obj, is_completed = await asyncio.to_thread(_append_turn)
        if not ok or not story_obj:
            await interaction.followup.send(f"⚠️ {msg}", ephemeral=True)
            return

        if is_completed:
            completed_embed = _build_relay_completed_embed(story_obj)
            try:
                await interaction.edit_original_response(embed=completed_embed, view=None)
            except Exception:
                if interaction.message:
                    try:
                        await interaction.message.edit(embed=completed_embed, view=None)
                    except Exception:
                        pass
            await interaction.followup.send(
                f"🎉 {interaction.user.mention}님이 마지막 줄을 작성해 **『{story_obj.get('title')}』** 릴레이 소설이 완결되었습니다!"
            )
        else:
            active_embed = _build_relay_active_embed(story_obj)
            live_view = RelayNovelView()
            try:
                await interaction.edit_original_response(embed=active_embed, view=live_view)
            except Exception:
                if interaction.message:
                    try:
                        await interaction.message.edit(embed=active_embed, view=live_view)
                    except Exception:
                        pass
            await interaction.followup.send(
                f"✍️ {interaction.user.mention}님이 `{len(story_obj['turns'])} / {story_obj['max_turns']}턴`을 작성했습니다!",
                ephemeral=True,
            )


class RelayNovelView(core.SafeView):
    """릴레이 소설 영구 버튼 View (재시작 후에도 이어쓰기 가능)"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="다음 줄 이어쓰기",
        style=discord.ButtonStyle.primary,
        emoji="✍️",
        custom_id="norosi:RelayNovelView:write",
        row=0,
    )
    async def write_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 참여할 수 있습니다.", ephemeral=True)
            return
        data = await asyncio.to_thread(core.load_data)
        story = community_core.get_active_relay_novel(data, interaction.guild.id, interaction.channel.id)
        if not story:
            await core.safe_send_response(interaction, "ℹ️ 이 소설은 이미 완결되었거나 종료되었습니다.", ephemeral=True)
            return
        turns = story.get("turns") or []
        if not story.get("allow_consecutive", False) and turns:
            if int(turns[-1].get("user_id", 0)) == interaction.user.id:
                await core.safe_send_response(
                    interaction,
                    "⏳ 직전 문장을 본인이 작성했어요! 다른 멤버가 한 줄 작성한 뒤 이어서 참여해 주세요.",
                    ephemeral=True,
                )
                return
        last_line = turns[-1].get("text", "") if turns else ""
        await interaction.response.send_modal(RelayWriteModal(last_line=last_line))

    @discord.ui.button(
        label="줄거리 확인",
        style=discord.ButtonStyle.secondary,
        emoji="📖",
        custom_id="norosi:RelayNovelView:preview",
        row=0,
    )
    async def preview_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 확인할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        story = community_core.get_active_relay_novel(data, interaction.guild.id, interaction.channel.id)
        if not story:
            await interaction.followup.send("ℹ️ 현재 진행 중인 릴레이 소설이 없습니다.", ephemeral=True)
            return
        is_blind = bool(story.get("blind_mode", True))
        is_creator_or_admin = (int(story.get("creator_id", 0)) == interaction.user.id) or _is_guild_admin(interaction.user, perm_attr="manage_messages")
        if is_blind and not is_creator_or_admin:
            last_t = (story.get("turns") or [{}])[-1]
            await interaction.followup.send(
                f"🔒 현재 **블라인드 모드**로 진행 중이라 완결 전까지는 개설자와 관리자만 전체를 열람할 수 있습니다!\n\n"
                f"**직전 문장 ({len(story.get('turns', []))}번째 줄):**\n> {last_t.get('text', '')}",
                ephemeral=True,
            )
            return
        full_txt = community_core.format_relay_full_story(story)
        embed = discord.Embed(
            title=f"📖 『{story.get('title', '무제')}』 현재 원고 ({len(story.get('turns', []))} / {story.get('max_turns', 10)}턴)",
            description=full_txt,
            color=discord.Color.purple(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="지금 완결하기",
        style=discord.ButtonStyle.success,
        emoji="🏁",
        custom_id="norosi:RelayNovelView:finish",
        row=0,
    )
    async def finish_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        guild_id = interaction.guild.id
        channel_id = interaction.channel.id
        is_admin = _is_guild_admin(interaction.user, perm_attr="manage_messages")

        def _finish_story():
            with core._DATA_LOCK:
                data = core.load_data()
                story = community_core.get_active_relay_novel(data, guild_id, channel_id)
                if not story:
                    return "none", "ℹ️ 이미 완결되었거나 종료된 소설입니다.", None
                if int(story.get("creator_id", 0)) != interaction.user.id and not is_admin:
                    return "denied", "❌ 소설 개설자 또는 메시지 관리 권한을 가진 관리자만 조기 완결할 수 있습니다.", None
                ok, msg, completed = community_core.finish_relay_novel_early(data, guild_id, channel_id)
                if not ok or not completed:
                    return "err", f"⚠️ {msg}", None
                core.save_data(data)
                return "ok", msg, completed

        status, msg, completed = await asyncio.to_thread(_finish_story)
        if status != "ok" or not completed:
            await interaction.followup.send(msg, ephemeral=True)
            return
        completed_embed = _build_relay_completed_embed(completed)
        if interaction.message:
            try:
                await interaction.message.edit(embed=completed_embed, view=None)
            except Exception:
                pass
        await interaction.followup.send(f"🏁 {interaction.user.mention}님이 **『{completed.get('title')}』** 릴레이 소설을 완결했습니다!")


class RelayArchiveSelect(discord.ui.Select):
    def __init__(self, novels: list[dict]):
        options = [
            discord.SelectOption(
                label=f"{i}. {n.get('title', '무제')[:70]}",
                value=str(i - 1),
                description=f"{len(n.get('turns', []))}턴 · 개설: {n.get('creator_name', '작가')[:25]}",
            )
            for i, n in enumerate(novels[:25], start=1)
        ]
        super().__init__(
            placeholder="📚 읽어볼 완결 릴레이 소설을 선택하세요",
            options=options,
            custom_id="norosi:RelayArchiveView:select",
        )

    async def callback(self, interaction: discord.Interaction):
        view: "RelayArchiveView" = self.view
        await core.safe_defer(interaction)
        if not view.novels and interaction.guild:
            getter = getattr(community_core, "get_completed_relay_novels", getattr(community_core, "get_relay_completed_list", None))
            if getter:
                view.novels = getter(core.get_cached_data(), interaction.guild.id)
        idx = int(self.values[0])
        if 0 <= idx < len(view.novels):
            view.current_idx = idx
            await interaction.edit_original_response(embed=_build_relay_completed_embed(view.novels[idx]), view=view)


class RelayArchiveView(core.SafeView):
    def __init__(self, novels_or_guild=None, guild_id_or_novels=0, initial_idx: int = 0):
        super().__init__(timeout=600)
        self.current_idx = max(0, int(initial_idx or 0))
        if isinstance(novels_or_guild, list):
            novels = novels_or_guild
            guild_id = int(guild_id_or_novels or 0) if isinstance(guild_id_or_novels, int) else 0
        elif isinstance(guild_id_or_novels, list):
            novels = guild_id_or_novels
            guild_id = getattr(novels_or_guild, "id", 0) or 0
        else:
            novels = None
            guild_id = getattr(novels_or_guild, "id", 0) or (int(guild_id_or_novels or 0) if isinstance(guild_id_or_novels, int) else 0)

        if novels is None and guild_id:
            getter = getattr(community_core, "get_completed_relay_novels", getattr(community_core, "get_relay_completed_list", None))
            if getter:
                novels = getter(core.get_cached_data(), guild_id)
        self.novels = novels or []
        if self.novels:
            self.add_item(RelayArchiveSelect(self.novels))

    def build_embed(self) -> discord.Embed:
        if self.novels:
            idx = min(self.current_idx, len(self.novels) - 1)
            return _build_relay_completed_embed(self.novels[idx])
        return discord.Embed(
            title="📕 완결 릴레이 소설 서재",
            description="아직 완결된 릴레이 소설이 없습니다. `/설정` (`✍️ 한 줄 릴레이 소설`)에서 첫 작품을 만들어 보세요!",
            color=discord.Color.gold(),
        )


# ==========================================
# 5. 🔊 임시 음성방 자동 생성기 — Join to Create UI (#11)
# ==========================================
def _build_temp_voice_panel_embed(
    channel: Optional[discord.VoiceChannel],
    room_info: dict,
) -> discord.Embed:
    ch_name = getattr(channel, "name", None) or room_info.get("room_name") or "임시 음성방"
    owner_id = int(room_info.get("owner_id", 0) or 0)
    owner_txt = f"<@{owner_id}>" if owner_id else str(room_info.get("owner_name") or "방장")
    limit_val = getattr(channel, "user_limit", None)
    if limit_val is None:
        limit_val = int(room_info.get("user_limit", 0) or 0)
    limit_txt = "무제한 (`0명`)" if int(limit_val or 0) <= 0 else f"최대 **`{limit_val}명`**"
    locked = bool(room_info.get("locked", False))
    hidden = bool(room_info.get("hidden", False))
    cur_members = len([m for m in getattr(channel, "members", []) if not m.bot]) if channel else 0

    embed = discord.Embed(
        title=f"🎛️ {ch_name} — 음성방 리모컨",
        description=(
            f"• **현재 방장:** 👑 {owner_txt}\n"
            f"• **현재 인원 / 정원:** `{cur_members}명` / {limit_txt}\n"
            f"• **입장 잠금:** {'🔒 **잠김** (방장·관리자만 입장)' if locked else '🔓 **열림** (누구나 입장 가능)'}\n"
            f"• **채널 노출:** {'👻 **숨김** (일반 멤버에게 채널 비공개)' if hidden else '👁️ **공개** (채널 목록에 표시)'}\n"
            "────────────────\n"
            "💡 **모든 인원이 퇴장하면 이 음성방은 자동으로 깔끔하게 삭제됩니다.**\n"
            "💡 원래 방장이 퇴장한 상태라면 방 안의 다른 멤버가 `[👑 방장 인계받기]`를 누를 수 있어요!"
        ),
        color=discord.Color.from_rgb(88, 101, 242),
        timestamp=datetime.datetime.now(core.KST),
    )
    embed.set_footer(text="방장 전용 리모컨 · /설정 (👤 개인 ➔ 🎛️ 내 임시음성방 리모컨)으로 언제든 다시 호출 가능")
    return embed


def _resolve_member_temp_voice_channel(
    interaction: discord.Interaction,
    target_channel_id: int = 0,
) -> Optional[discord.VoiceChannel]:
    if not interaction.guild:
        return None
    if target_channel_id:
        ch = interaction.guild.get_channel(int(target_channel_id))
        if isinstance(ch, discord.VoiceChannel):
            return ch
    if isinstance(interaction.channel, discord.VoiceChannel):
        return interaction.channel
    voice_state = getattr(interaction.user, "voice", None)
    if voice_state and isinstance(voice_state.channel, discord.VoiceChannel):
        return voice_state.channel
    return None


class TempVoiceRenameModal(core.SafeModal, title="✏️ 임시 음성방 이름 변경"):
    name_input = discord.ui.TextInput(
        label="새 음성방 이름 (2~90자)",
        placeholder="예: 🎮 롤 내전 5인방 / ☕ 새벽 수다방",
        required=True,
        min_length=2,
        max_length=90,
    )

    def __init__(self, voice_channel: discord.VoiceChannel):
        super().__init__()
        self.voice_channel = voice_channel
        self.name_input.default = (voice_channel.name or "")[:90]

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버에서만 사용할 수 있습니다.", ephemeral=True)
            return
        new_name = " ".join(self.name_input.value.strip().splitlines())[:90]
        if len(new_name) < 2:
            await core.safe_send_response(interaction, "❌ 방 이름은 2글자 이상 입력해 주세요.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild.id
        ch_id = self.voice_channel.id

        try:
            await asyncio.wait_for(
                self.voice_channel.edit(name=new_name, reason=f"임시 음성방 이름 변경 ({interaction.user})"),
                timeout=6.0,
            )
        except asyncio.TimeoutError:
            await interaction.followup.send(
                "⏳ 디스코드 채널 이름 변경 쿨타임(10분당 2회 제한)에 걸렸습니다. 잠시 후 다시 시도해 주세요!",
                ephemeral=True,
            )
            return
        except discord.Forbidden:
            await interaction.followup.send("❌ 봇에게 채널 관리 권한이 부족하여 이름을 변경할 수 없습니다.", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"❌ 방 이름 변경 실패: `{e}`", ephemeral=True)
            return

        def _update_name():
            with core._DATA_LOCK:
                data = core.load_data()
                updated = community_core.update_temp_voice_room(data, guild_id, ch_id, room_name=new_name)
                if updated:
                    core.save_data(data)
                return updated

        updated_room = await asyncio.to_thread(_update_name)
        if updated_room and interaction.message:
            try:
                await interaction.message.edit(
                    embed=_build_temp_voice_panel_embed(self.voice_channel, updated_room),
                    view=TempVoiceControlView(ch_id),
                )
            except Exception:
                pass
        await interaction.followup.send(f"✅ 음성방 이름 변경 완료: **`{new_name}`**", ephemeral=True)


class TempVoiceLimitModal(core.SafeModal, title="👥 음성방 최대 인원수 설정"):
    limit_input = discord.ui.TextInput(
        label="최대 인원수 (0 = 무제한, 1~99명)",
        placeholder="예: 5 (0을 입력하면 인원 제한 해제)",
        required=True,
        max_length=2,
    )

    def __init__(self, voice_channel: discord.VoiceChannel):
        super().__init__()
        self.voice_channel = voice_channel
        self.limit_input.default = str(voice_channel.user_limit or 0)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버에서만 사용할 수 있습니다.", ephemeral=True)
            return
        try:
            limit_val = int(self.limit_input.value.strip())
        except ValueError:
            await core.safe_send_response(interaction, "❌ 0부터 99 사이의 숫자만 입력해 주세요.", ephemeral=True)
            return
        limit_val = max(0, min(99, limit_val))

        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild.id
        ch_id = self.voice_channel.id

        try:
            await self.voice_channel.edit(
                user_limit=limit_val,
                reason=f"임시 음성방 정원 변경 ({interaction.user})",
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ 봇에게 채널 관리 권한이 부족합니다.", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"❌ 인원 제한 변경 실패: `{e}`", ephemeral=True)
            return

        def _update_limit():
            with core._DATA_LOCK:
                data = core.load_data()
                updated = community_core.update_temp_voice_room(data, guild_id, ch_id, user_limit=limit_val)
                if updated:
                    core.save_data(data)
                return updated

        updated_room = await asyncio.to_thread(_update_limit)
        if updated_room and interaction.message:
            try:
                await interaction.message.edit(
                    embed=_build_temp_voice_panel_embed(self.voice_channel, updated_room),
                    view=TempVoiceControlView(ch_id),
                )
            except Exception:
                pass
        limit_label = "무제한" if limit_val == 0 else f"최대 {limit_val}명"
        await interaction.followup.send(f"👥 음성방 정원 설정 완료: **`{limit_label}`**", ephemeral=True)


class TempVoiceTemplateModal(core.SafeModal, title="⚙️ 임시 음성방 기본 템플릿 설정"):
    template_input = discord.ui.TextInput(
        label="자동 생성 방 이름 템플릿 ({user} = 닉네임)",
        placeholder="예: 🔊 {user}님의 음성방",
        required=True,
        max_length=80,
    )
    default_limit_input = discord.ui.TextInput(
        label="생성 시 기본 최대 인원 (0 = 무제한, 1~99)",
        placeholder="예: 0",
        required=True,
        max_length=2,
    )

    def __init__(self, parent_view: "TempVoiceSetupView"):
        super().__init__()
        self.parent_view = parent_view
        cfg = parent_view.cfg if isinstance(getattr(parent_view, "cfg", None), dict) else {}
        self.template_input.default = str(cfg.get("name_template") or community_core.DEFAULT_TEMP_VOICE_TEMPLATE)[:80]
        self.default_limit_input.default = str(cfg.get("default_limit", 0) or 0)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not _is_guild_admin(interaction.user, perm_attr="manage_channels"):
            await core.safe_send_response(interaction, "❌ 채널 관리 또는 서버 관리자 권한이 필요합니다.", ephemeral=True)
            return
        try:
            def_limit = int(self.default_limit_input.value.strip())
        except ValueError:
            await core.safe_send_response(interaction, "❌ 기본 인원은 0~99 사이의 숫자로 입력해 주세요.", ephemeral=True)
            return
        tpl_val = (self.template_input.value or community_core.DEFAULT_TEMP_VOICE_TEMPLATE).strip()[:80]
        def_limit = max(0, min(99, def_limit))

        await core.safe_defer(interaction)
        guild_id = interaction.guild.id

        def _save_tpl():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.get_temp_voice_config(data, guild_id)
                cfg["name_template"] = tpl_val
                cfg["default_limit"] = def_limit
                saved = community_core.save_temp_voice_config(data, guild_id, cfg)
                core.save_data(data)
                return saved

        self.parent_view.cfg = await asyncio.to_thread(_save_tpl)
        await interaction.edit_original_response(embed=self.parent_view.build_embed(), view=self.parent_view)


class TempVoiceControlView(core.SafeView):
    """임시 음성방 내부 채팅에 전송되는 영구 리모컨 View"""

    def __init__(self, channel_id: int = 0):
        super().__init__(timeout=None)
        self.channel_id = int(channel_id or 0)

    async def _check_owner_or_admin(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[discord.VoiceChannel], Optional[dict]]:
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버에서만 사용할 수 있습니다.", ephemeral=True)
            return None, None
        vc = _resolve_member_temp_voice_channel(interaction, self.channel_id)
        if not vc:
            await core.safe_send_response(
                interaction,
                "❌ 제어할 임시 음성방에 접속해 있거나 해당 음성방 채팅에서 버튼을 눌러 주세요.",
                ephemeral=True,
            )
            return None, None

        data = await asyncio.to_thread(core.load_data)
        room = community_core.get_temp_voice_room(data, interaction.guild.id, vc.id)
        if not room:
            await core.safe_send_response(
                interaction,
                "ℹ️ 이 채널은 자동 생성된 임시 음성방이 아니거나 이미 등록이 해제되었습니다.",
                ephemeral=True,
            )
            return None, None

        is_owner = int(room.get("owner_id", 0) or 0) == interaction.user.id
        is_admin = _is_guild_admin(interaction.user, perm_attr="manage_channels")
        if not is_owner and not is_admin:
            await core.safe_send_response(
                interaction,
                f"❌ 현재 방장(<@{room.get('owner_id', 0)}>) 또는 채널 관리자만 조작할 수 있습니다.\n"
                "*(방장이 이미 퇴장했다면 `[👑 방장 인계받기]` 버튼을 눌러 방장이 될 수 있어요!)*",
                ephemeral=True,
            )
            return None, None
        return vc, room

    @discord.ui.button(
        label="방 제목 변경",
        style=discord.ButtonStyle.primary,
        emoji="✏️",
        custom_id="norosi:TempVoiceControlView:rename",
        row=0,
    )
    async def rename_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, room = await self._check_owner_or_admin(interaction)
        if not vc or not room:
            return
        await interaction.response.send_modal(TempVoiceRenameModal(vc))

    @discord.ui.button(
        label="인원 제한",
        style=discord.ButtonStyle.secondary,
        emoji="👥",
        custom_id="norosi:TempVoiceControlView:limit",
        row=0,
    )
    async def limit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, room = await self._check_owner_or_admin(interaction)
        if not vc or not room:
            return
        await interaction.response.send_modal(TempVoiceLimitModal(vc))

    @discord.ui.button(
        label="방 잠금 / 해제",
        style=discord.ButtonStyle.secondary,
        emoji="🔒",
        custom_id="norosi:TempVoiceControlView:lock",
        row=0,
    )
    async def lock_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, room = await self._check_owner_or_admin(interaction)
        if not vc or not room or not interaction.guild:
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild.id
        new_locked = not bool(room.get("locked", False))

        everyone_role = interaction.guild.default_role
        overwrites = dict(vc.overwrites)
        ev_ow = overwrites.get(everyone_role, discord.PermissionOverwrite())
        ev_ow.connect = False if new_locked else None
        overwrites[everyone_role] = ev_ow
        for cur_m in vc.members:
            if not cur_m.bot:
                m_ow = overwrites.get(cur_m, discord.PermissionOverwrite())
                m_ow.connect = True
                m_ow.view_channel = True
                overwrites[cur_m] = m_ow
        if isinstance(interaction.user, discord.Member):
            owner_ow = overwrites.get(interaction.user, discord.PermissionOverwrite())
            owner_ow.connect = True
            owner_ow.view_channel = True
            owner_ow.manage_channels = True
            owner_ow.move_members = True
            overwrites[interaction.user] = owner_ow

        try:
            await vc.edit(overwrites=overwrites, reason=f"임시 음성방 잠금 토글 ({interaction.user})")
        except discord.Forbidden:
            await interaction.followup.send("❌ 봇에게 채널 권한을 수정할 권한이 없습니다.", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"❌ 방 잠금 상태 변경 실패: `{e}`", ephemeral=True)
            return

        def _save_lock():
            with core._DATA_LOCK:
                data = core.load_data()
                updated = community_core.update_temp_voice_room(data, guild_id, vc.id, locked=new_locked)
                if updated:
                    core.save_data(data)
                return updated

        updated_room = await asyncio.to_thread(_save_lock) or room
        if interaction.message:
            try:
                await interaction.message.edit(embed=_build_temp_voice_panel_embed(vc, updated_room), view=self)
            except Exception:
                pass
        state_msg = "🔒 **음성방이 잠겼습니다!** 이제 새로운 멤버가 임의로 들어올 수 없습니다." if new_locked else "🔓 **음성방 잠금이 해제되었습니다!**"
        await interaction.followup.send(state_msg, ephemeral=True)

    @discord.ui.button(
        label="방 숨기기 / 해제",
        style=discord.ButtonStyle.secondary,
        emoji="👻",
        custom_id="norosi:TempVoiceControlView:hide",
        row=1,
    )
    async def hide_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, room = await self._check_owner_or_admin(interaction)
        if not vc or not room or not interaction.guild:
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild.id
        new_hidden = not bool(room.get("hidden", False))

        everyone_role = interaction.guild.default_role
        overwrites = dict(vc.overwrites)
        ev_ow = overwrites.get(everyone_role, discord.PermissionOverwrite())
        ev_ow.view_channel = False if new_hidden else None
        overwrites[everyone_role] = ev_ow
        for cur_m in vc.members:
            if not cur_m.bot:
                m_ow = overwrites.get(cur_m, discord.PermissionOverwrite())
                m_ow.view_channel = True
                m_ow.connect = True
                overwrites[cur_m] = m_ow
        if isinstance(interaction.user, discord.Member):
            owner_ow = overwrites.get(interaction.user, discord.PermissionOverwrite())
            owner_ow.view_channel = True
            owner_ow.connect = True
            owner_ow.manage_channels = True
            owner_ow.move_members = True
            overwrites[interaction.user] = owner_ow

        try:
            await vc.edit(overwrites=overwrites, reason=f"임시 음성방 숨김 토글 ({interaction.user})")
        except discord.Forbidden:
            await interaction.followup.send("❌ 봇에게 채널 권한을 수정할 권한이 없습니다.", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"❌ 방 숨김 상태 변경 실패: `{e}`", ephemeral=True)
            return

        def _save_hide():
            with core._DATA_LOCK:
                data = core.load_data()
                updated = community_core.update_temp_voice_room(data, guild_id, vc.id, hidden=new_hidden)
                if updated:
                    core.save_data(data)
                return updated

        updated_room = await asyncio.to_thread(_save_hide) or room
        if interaction.message:
            try:
                await interaction.message.edit(embed=_build_temp_voice_panel_embed(vc, updated_room), view=self)
            except Exception:
                pass
        state_msg = "👻 **음성방이 숨김 처리되었습니다!**" if new_hidden else "👁️ **음성방 숨김이 해제되어 채널 목록에 공개됩니다!**"
        await interaction.followup.send(state_msg, ephemeral=True)

    @discord.ui.button(
        label="방장 인계받기",
        style=discord.ButtonStyle.success,
        emoji="👑",
        custom_id="norosi:TempVoiceControlView:claim",
        row=1,
    )
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await core.safe_send_response(interaction, "❌ 서버 멤버만 사용할 수 있습니다.", ephemeral=True)
            return
        vc = _resolve_member_temp_voice_channel(interaction, self.channel_id)
        if not vc:
            await core.safe_send_response(interaction, "❌ 먼저 해당 임시 음성방에 입장해 주세요.", ephemeral=True)
            return
        if interaction.user not in vc.members and not _is_guild_admin(interaction.user, perm_attr="manage_channels"):
            await core.safe_send_response(interaction, "❌ 현재 이 음성방에 접속 중인 멤버만 방장을 인계받을 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild.id
        data = await asyncio.to_thread(core.load_data)
        room = community_core.get_temp_voice_room(data, guild_id, vc.id)
        if not room:
            await interaction.followup.send("ℹ️ 등록된 임시 음성방 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        cur_owner_id = int(room.get("owner_id", 0) or 0)
        if cur_owner_id == interaction.user.id:
            await interaction.followup.send("👑 이미 이 음성방의 방장입니다!", ephemeral=True)
            return

        owner_still_here = any(m.id == cur_owner_id for m in vc.members)
        if owner_still_here and not _is_guild_admin(interaction.user, perm_attr="manage_channels"):
            await interaction.followup.send(
                f"❌ 현재 방장(<@{cur_owner_id}>)이 아직 음성방에 남아 있어 인계받을 수 없습니다!",
                ephemeral=True,
            )
            return

        overwrites = dict(vc.overwrites)
        old_owner_member = interaction.guild.get_member(cur_owner_id) if cur_owner_id else None
        if old_owner_member and old_owner_member in overwrites:
            old_ow = overwrites[old_owner_member]
            old_ow.manage_channels = None
            old_ow.move_members = None
            overwrites[old_owner_member] = old_ow
        new_ow = overwrites.get(interaction.user, discord.PermissionOverwrite())
        new_ow.connect = True
        new_ow.view_channel = True
        new_ow.manage_channels = True
        new_ow.move_members = True
        overwrites[interaction.user] = new_ow
        try:
            await vc.edit(overwrites=overwrites, reason=f"임시 음성방 방장 인계 ({interaction.user})")
        except Exception:
            pass

        def _claim_owner():
            with core._DATA_LOCK:
                d = core.load_data()
                updated = community_core.update_temp_voice_room(
                    d,
                    guild_id,
                    vc.id,
                    owner_id=interaction.user.id,
                    owner_name=interaction.user.display_name,
                )
                if updated:
                    core.save_data(d)
                return updated

        updated_room = await asyncio.to_thread(_claim_owner) or room
        if interaction.message:
            try:
                await interaction.message.edit(embed=_build_temp_voice_panel_embed(vc, updated_room), view=self)
            except Exception:
                pass
        await interaction.followup.send(f"👑 {interaction.user.mention}님이 이 음성방의 **새 방장**이 되었습니다!", ephemeral=True)


class TempVoiceCategorySelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="1️⃣ [서버 관리자] 임시방이 생성될 카테고리를 먼저 지정하세요...",
            channel_types=[discord.ChannelType.category],
            min_values=1,
            max_values=1,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "TempVoiceSetupView" = self.view
        if not interaction.guild or not _is_strict_server_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 카테고리 지정 및 자동생성 채널 관리는 **서버 관리자**만 가능합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        selected = self.values[0]
        guild_id = interaction.guild.id

        def _save_cat():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.get_temp_voice_config(data, guild_id)
                cfg["category_id"] = selected.id
                saved = community_core.save_temp_voice_config(data, guild_id, cfg)
                core.save_data(data)
                return saved

        view.cfg = await asyncio.to_thread(_save_cat)
        await interaction.edit_original_response(embed=view.build_embed(), view=view)
        await interaction.followup.send(
            f"✅ <#{selected.id}> 카테고리가 **임시 음성방 지정 카테고리**로 설정되었습니다!\n"
            "이제 위쪽 **[➕ 지정 카테고리에 자동채널 생성]** 버튼을 누르거나 아래 **2️⃣번 드롭다운**에서 자동생성 트리거 채널을 추가하세요.",
            ephemeral=True,
        )


class TempVoiceGeneratorSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="2️⃣ [서버 관리자 전용] 자동생성(입장 트리거) 음성 채널 추가...",
            channel_types=[discord.ChannelType.voice],
            min_values=1,
            max_values=1,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "TempVoiceSetupView" = self.view
        if not interaction.guild or not _is_strict_server_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 자동생성 채널 추가는 **서버 관리자(Administrator)** 만 가능합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        selected = self.values[0]
        real_ch = interaction.guild.get_channel(selected.id)
        cat_id = getattr(real_ch, "category_id", None)
        guild_id = interaction.guild.id

        def _save_gen():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.get_temp_voice_config(data, guild_id)
                community_core.add_temp_voice_generator_channel(cfg, selected.id)
                if not cfg.get("category_id") and cat_id:
                    cfg["category_id"] = cat_id
                cfg["enabled"] = True
                saved = community_core.save_temp_voice_config(data, guild_id, cfg)
                core.save_data(data)
                return saved

        view.cfg = await asyncio.to_thread(_save_gen)
        await interaction.edit_original_response(embed=view.build_embed(), view=view)
        await interaction.followup.send(
            f"✅ <#{selected.id}> 채널이 **임시 음성방 자동생성(Join-to-Create) 채널**로 추가되어 활성화되었습니다!",
            ephemeral=True,
        )


class TempVoiceGeneratorRemoveSelect(discord.ui.Select):
    def __init__(self, guild: Optional[discord.Guild], gen_ids: list[int]):
        options: list[discord.SelectOption] = []
        for gid in gen_ids[:10]:
            ch = guild.get_channel(int(gid)) if guild else None
            ch_name = f"#{ch.name}" if ch else f"삭제된 채널 ({gid})"
            options.append(
                discord.SelectOption(
                    label=f"제거: {ch_name}"[:100],
                    value=str(gid),
                    description="선택 시 자동생성(트리거) 채널 목록에서 제외합니다.",
                    emoji="➖",
                )
            )
        super().__init__(
            placeholder="3️⃣ 등록된 자동생성(트리거) 채널 개별 제거 (서버 관리자)...",
            min_values=1,
            max_values=1,
            options=options,
            row=4,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "TempVoiceSetupView" = self.view
        if not interaction.guild or not _is_strict_server_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 자동생성 채널 관리는 **서버 관리자**만 가능합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        target_cid = int(self.values[0])
        guild_id = interaction.guild.id

        def _remove_one():
            with core._DATA_LOCK:
                d = core.load_data()
                cfg = community_core.get_temp_voice_config(d, guild_id)
                rem = community_core.remove_temp_voice_generator_channel(cfg, target_cid)
                if not rem:
                    cfg["enabled"] = False
                saved = community_core.save_temp_voice_config(d, guild_id, cfg)
                core.save_data(d)
                return saved

        view.cfg = await asyncio.to_thread(_remove_one)
        await interaction.edit_original_response(embed=view.build_embed(), view=view)
        await interaction.followup.send(
            f"➖ <#{target_cid}> 채널을 임시 음성방 자동생성 목록에서 제외했습니다.",
            ephemeral=True,
        )


class TempVoiceCategoryChannelModal(discord.ui.Modal, title="📁 새 카테고리 & 자동생성 채널 만들기"):
    cat_name_input = discord.ui.TextInput(
        label="생성할 카테고리 이름",
        default="🔊 임시 음성방",
        placeholder="예: 🔊 임시 음성방",
        required=True,
        max_length=50,
    )
    gen_name_input = discord.ui.TextInput(
        label="자동생성(입장 트리거) 음성 채널 이름",
        default="➕ 방 만들기",
        placeholder="예: ➕ 방 만들기",
        required=True,
        max_length=50,
    )

    def __init__(self, parent_view: "TempVoiceSetupView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not _is_strict_server_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 자동생성 채널 추가는 **서버 관리자**만 가능합니다.", ephemeral=True)
            return
        if not interaction.guild.me.guild_permissions.manage_channels:
            await core.safe_send_response(interaction, "❌ 봇에게 **채널 관리(Manage Channels)** 권한이 필요합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        guild = interaction.guild
        cat_name = (self.cat_name_input.value or "🔊 임시 음성방").strip()[:50] or "🔊 임시 음성방"
        gen_name = (self.gen_name_input.value or "➕ 방 만들기").strip()[:50] or "➕ 방 만들기"
        try:
            new_cat = await guild.create_category(
                name=cat_name,
                reason=f"임시 음성방 전용 카테고리 개설 ({interaction.user})",
            )
            new_gen = await guild.create_voice_channel(
                name=gen_name,
                category=new_cat,
                reason=f"임시 음성방 자동생성 채널 개설 ({interaction.user})",
            )
        except Exception as e:
            await interaction.followup.send(f"❌ 카테고리/음성 채널 생성 실패: `{e}`", ephemeral=True)
            return

        guild_id = guild.id

        def _save_both():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.get_temp_voice_config(data, guild_id)
                cfg["category_id"] = new_cat.id
                community_core.add_temp_voice_generator_channel(cfg, new_gen.id)
                cfg["enabled"] = True
                saved = community_core.save_temp_voice_config(data, guild_id, cfg)
                core.save_data(data)
                return saved

        self.parent_view.cfg = await asyncio.to_thread(_save_both)
        await interaction.edit_original_response(embed=self.parent_view.build_embed(), view=self.parent_view)
        await interaction.followup.send(
            f"🎉 **{new_cat.name}** 카테고리와 {new_gen.mention} 자동생성 채널이 개설되어 즉시 활성화되었습니다!",
            ephemeral=True,
        )


class TempVoiceSetupView(core.SafeView):
    """서버 관리자 전용 임시 음성방 생성기(Join-to-Create) 설정 대시보드"""

    def __init__(self, author_id: int = 0, guild: Optional[discord.Guild] = None, cfg: Optional[dict] = None):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.guild = guild
        self.cfg = cfg if isinstance(cfg, dict) else community_core.get_temp_voice_config(core.get_cached_data(), getattr(guild, "id", 0))
        self._remove_select: Optional[TempVoiceGeneratorRemoveSelect] = None
        self.add_item(TempVoiceCategorySelect())
        self.add_item(TempVoiceGeneratorSelect())
        self._refresh_remove_select()

    def _refresh_remove_select(self) -> None:
        if self._remove_select is not None:
            try:
                self.remove_item(self._remove_select)
            except Exception:
                pass
            self._remove_select = None
        c = self.cfg if isinstance(self.cfg, dict) else {}
        gen_ids = c.get("generator_channel_ids") or ([c["generator_channel_id"]] if c.get("generator_channel_id") else [])
        if gen_ids:
            self._remove_select = TempVoiceGeneratorRemoveSelect(self.guild, [int(x) for x in gen_ids if str(x).isdigit()])
            self.add_item(self._remove_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not _is_strict_server_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 임시 음성방 설정 및 자동생성 채널 추가는 **서버 관리자(Administrator)** 만 가능합니다.", ephemeral=True)
            return False
        if self.guild is None and interaction.guild:
            self.guild = interaction.guild
        if interaction.guild:
            self.cfg = community_core.get_temp_voice_config(core.get_cached_data(), interaction.guild.id)
        return True

    def build_embed(self) -> discord.Embed:
        self._refresh_remove_select()
        c = self.cfg
        gname = getattr(self.guild, "name", None) or "서버"
        gen_ids = c.get("generator_channel_ids") or ([c["generator_channel_id"]] if c.get("generator_channel_id") else [])
        gen_str = " · ".join(f"<#{gid}>" for gid in gen_ids) if gen_ids else "⚠️ 미지정 *(카테고리 지정 후 위 버튼으로 생성하거나 2️⃣번 드롭다운에서 추가)*"
        cat_id = c.get("category_id")
        cat_str = f"<#{cat_id}>" if cat_id else "⚠️ 미지정 *(아래 1️⃣번 드롭다운에서 카테고리를 먼저 지정해 주세요)*"
        limit_val = int(c.get("default_limit", 0) or 0)
        limit_str = "무제한 (`0명`)" if limit_val <= 0 else f"`{limit_val}명`"
        active_cnt = len(c.get("active_rooms") or {})
        example_name = community_core.format_temp_voice_room_name(c.get("name_template", ""), "홍길동", 1)

        me = getattr(self.guild, "me", None)
        if me is not None:
            p_ch = "✅ 채널 관리" if me.guild_permissions.manage_channels else "❌ 채널 관리(부족)"
            p_mv = "✅ 멤버 이동" if me.guild_permissions.move_members else "❌ 멤버 이동(부족)"
            perm_diag_str = f"{p_ch} · {p_mv}"
        else:
            perm_diag_str = "ℹ️ 서버에서 실행 시 자동 진단"

        embed = discord.Embed(
            title=f"🔊 [{gname}] 임시 음성방 자동 생성기 (서버 관리자 전용)",
            description=(
                f"• **기능 상태:** {'🟢 **활성화됨**' if c.get('enabled') else '🔴 **비활성화됨**'}\n"
                f"• **지정된 카테고리:** {cat_str}\n"
                f"• **자동생성(입장 트리거) 채널 (`{len(gen_ids)}개`):** {gen_str}\n"
                f"• **방 이름 템플릿:** `{c.get('name_template')}` *(예: `{example_name}`)*\n"
                f"• **기본 최대 인원:** {limit_str}\n"
                f"• **현재 활성 임시방:** **`{active_cnt}개`**\n"
                f"• **봇 필수 권한 진단:** {perm_diag_str}\n\n"
                "💡 **설정 순서:**\n"
                "1️⃣ 아래 드롭다운에서 **카테고리를 지정**한 뒤 **[➕ 지정 카테고리에 자동채널 생성]** 버튼을 누르거나,\n"
                "2️⃣ **[📁 새 카테고리+자동채널 생성]** 버튼으로 카테고리부터 한 번에 만들 수 있습니다.\n"
                "*(자동생성 채널 추가·제거·설정은 서버 관리자만 가능하며, 멤버가 해당 채널에 입장하면 지정된 카테고리에 개인 음성방이 자동 생성됩니다.)*"
            ),
            color=discord.Color.green() if c.get("enabled") else discord.Color.dark_grey(),
            timestamp=datetime.datetime.now(core.KST),
        )
        return embed

    @discord.ui.button(label="지정 카테고리에 자동채널 생성", style=discord.ButtonStyle.success, emoji="➕", row=0)
    async def auto_create_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not _is_strict_server_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 자동생성 채널 추가는 **서버 관리자**만 가능합니다.", ephemeral=True)
            return
        if not interaction.guild.me.guild_permissions.manage_channels:
            await core.safe_send_response(interaction, "❌ 봇에게 **채널 관리(Manage Channels)** 권한이 필요합니다.", ephemeral=True)
            return

        guild = interaction.guild
        cat_id = self.cfg.get("category_id")
        target_cat = guild.get_channel(int(cat_id)) if cat_id else None
        if not isinstance(target_cat, discord.CategoryChannel):
            await core.safe_send_response(
                interaction,
                "⚠️ **카테고리가 아직 지정되지 않았습니다!**\n"
                "먼저 아래 **1️⃣ 카테고리 지정** 드롭다운에서 카테고리를 선택하거나, 옆의 **[📁 새 카테고리+자동채널 생성]** 버튼을 눌러주세요.",
                ephemeral=True,
            )
            return

        await core.safe_defer(interaction)
        try:
            new_gen = await guild.create_voice_channel(
                name="➕ 방 만들기",
                category=target_cat,
                reason=f"지정 카테고리에 임시 음성방 자동생성 채널 개설 ({interaction.user})",
            )
        except Exception as e:
            await interaction.followup.send(f"❌ 음성 채널 생성 실패: `{e}`", ephemeral=True)
            return

        guild_id = guild.id

        def _save_auto():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.get_temp_voice_config(data, guild_id)
                cfg["category_id"] = target_cat.id
                community_core.add_temp_voice_generator_channel(cfg, new_gen.id)
                cfg["enabled"] = True
                saved = community_core.save_temp_voice_config(data, guild_id, cfg)
                core.save_data(data)
                return saved

        self.cfg = await asyncio.to_thread(_save_auto)
        await interaction.edit_original_response(embed=self.build_embed(), view=self)
        await interaction.followup.send(
            f"🎉 지정된 **{target_cat.name}** 카테고리에 {new_gen.mention} 자동생성 채널이 추가되었으며 즉시 활성화되었습니다!\n"
            "이제 멤버들이 저 채널에 접속하면 해당 카테고리에 자동으로 개인 음성방이 만들어집니다.",
            ephemeral=True,
        )

    @discord.ui.button(label="새 카테고리+자동채널 생성", style=discord.ButtonStyle.primary, emoji="📁", row=0)
    async def create_cat_and_channel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_strict_server_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 자동생성 채널 추가는 **서버 관리자**만 가능합니다.", ephemeral=True)
            return
        await interaction.response.send_modal(TempVoiceCategoryChannelModal(self))

    @discord.ui.button(label="기능 ON/OFF", style=discord.ButtonStyle.secondary, emoji="⚡", row=0)
    async def toggle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return
        gen_ids = self.cfg.get("generator_channel_ids") or ([self.cfg["generator_channel_id"]] if self.cfg.get("generator_channel_id") else [])
        if not self.cfg.get("enabled") and (not self.cfg.get("category_id") or not gen_ids):
            await core.safe_send_response(
                interaction,
                "⚠️ 기능을 켜려면 먼저 **1️⃣ 카테고리를 지정**하고 **자동생성 음성 채널**을 생성하거나 추가해 주세요!",
                ephemeral=True,
            )
            return
        await core.safe_defer(interaction)
        guild_id = interaction.guild.id

        def _toggle():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.get_temp_voice_config(data, guild_id)
                cfg["enabled"] = not cfg.get("enabled", False)
                saved = community_core.save_temp_voice_config(data, guild_id, cfg)
                core.save_data(data)
                return saved

        self.cfg = await asyncio.to_thread(_toggle)
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="이름 템플릿 / 기본 정원", style=discord.ButtonStyle.secondary, emoji="⚙️", row=3)
    async def edit_template_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TempVoiceTemplateModal(self))

    @discord.ui.button(label="빈 임시방 정리", style=discord.ButtonStyle.secondary, emoji="🧹", row=3)
    async def cleanup_empty_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return
        await core.safe_defer(interaction)
        guild = interaction.guild
        guild_id = guild.id
        data = await asyncio.to_thread(core.load_data)
        cfg = community_core.get_temp_voice_config(data, guild_id)
        active_rooms = dict(cfg.get("active_rooms") or {})
        cleaned_ids: list[int] = []

        for ch_id_s in list(active_rooms.keys()):
            ch_id = int(ch_id_s)
            ch = guild.get_channel(ch_id)
            if not isinstance(ch, discord.VoiceChannel):
                cleaned_ids.append(ch_id)
                continue
            non_bots = [m for m in ch.members if not m.bot]
            if len(non_bots) == 0 and not community_core.is_temp_voice_generator_channel(cfg, ch_id):
                try:
                    await ch.delete(reason="빈 임시 음성방 수동 정리")
                except Exception:
                    pass
                cleaned_ids.append(ch_id)

        def _commit_cleanup():
            with core._DATA_LOCK:
                d = core.load_data()
                for cid in cleaned_ids:
                    community_core.remove_temp_voice_room(d, guild_id, cid)
                fresh = community_core.get_temp_voice_config(d, guild_id)
                core.save_data(d)
                return fresh

        self.cfg = await asyncio.to_thread(_commit_cleanup)
        await interaction.edit_original_response(embed=self.build_embed(), view=self)
        await interaction.followup.send(f"🧹 빈 임시 음성방 `{len(cleaned_ids)}개`를 정리했습니다.", ephemeral=True)

    @discord.ui.button(label="자동생성 채널 목록 초기화", style=discord.ButtonStyle.danger, emoji="🗑️", row=3)
    async def clear_generators_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not _is_strict_server_admin(interaction.user):
            return
        await core.safe_defer(interaction)
        guild_id = interaction.guild.id

        def _clear_gens():
            with core._DATA_LOCK:
                d = core.load_data()
                cfg = community_core.get_temp_voice_config(d, guild_id)
                community_core.clear_temp_voice_generator_channels(cfg)
                cfg["enabled"] = False
                saved = community_core.save_temp_voice_config(d, guild_id, cfg)
                core.save_data(d)
                return saved

        self.cfg = await asyncio.to_thread(_clear_gens)
        await interaction.edit_original_response(embed=self.build_embed(), view=self)
        await interaction.followup.send("🗑️ 등록된 자동생성(트리거) 채널 목록을 초기화했습니다.", ephemeral=True)


# ==========================================
# 6. 🗓️ 예약 이벤트 신청표 (RSVP · 대기열 자동 승격 · 15분 전 자동 리마인드)
# ==========================================
_EVENT_ID_FOOTER_RE = re.compile(r"ID:\s*(ev_[0-9a-f]{8})")


def _format_rsvp_mentions(uid_list: list[int], limit: int = 18) -> str:
    if not uid_list:
        return "*(없음)*"
    shown = [f"<@{uid}>" for uid in uid_list[:limit]]
    if len(uid_list) > limit:
        shown.append(f"외 `{len(uid_list) - limit}명`")
    return " · ".join(shown)


def build_event_rsvp_embed(event: dict) -> discord.Embed:
    status = str(event.get("status") or "open")
    going = community_core._normalize_uid_list(event.get("going"))
    waitlist = community_core._normalize_uid_list(event.get("waitlist"))
    maybe = community_core._normalize_uid_list(event.get("maybe"))
    declined = community_core._normalize_uid_list(event.get("declined"))
    max_slots = max(0, int(event.get("max_slots") or 0))
    start_ts = int(event.get("start_ts") or 0)
    host_id = int(event.get("host_id") or 0)
    ev_id = str(event.get("id") or "")

    is_full = max_slots > 0 and len(going) >= max_slots
    if status == "cancelled":
        badge = "❌ 취소됨"
        color = 0xE74C3C
    elif status == "closed":
        badge = "🔒 모집 마감"
        color = 0x95A5A6
    elif is_full:
        badge = "🟠 정원 마감 (대기 가능)"
        color = 0xF39C12
    else:
        badge = "🟢 모집 중"
        color = 0x2ECC71

    cap_txt = f"`{len(going)} / {max_slots}명`" if max_slots > 0 else f"`{len(going)}명` (무제한)"
    time_txt = f"<t:{start_ts}:F> (<t:{start_ts}:R>)" if start_ts > 0 else "미정"
    desc_body = (event.get("description") or "").strip()

    lines = [
        f"**상태:** {badge}  ·  **주최자:** <@{host_id}>",
        f"🕒 **시작 시각:** {time_txt}",
        f"👥 **참가 정원:** {cap_txt}",
    ]
    if desc_body:
        lines.append(f"━━━━━━━━━━━━━━━━\n📝 {desc_body}")

    embed = discord.Embed(
        title=f"🗓️ {event.get('title') or '예약 이벤트'}",
        description="\n".join(lines),
        color=color,
        timestamp=datetime.datetime.now(core.KST),
    )
    embed.add_field(
        name=f"✅ 참가 확정 ({len(going)}명)",
        value=_format_rsvp_mentions(going),
        inline=False,
    )
    if waitlist:
        embed.add_field(
            name=f"⏳ 대기열 ({len(waitlist)}명 · 빈자리 시 자동 승격)",
            value=_format_rsvp_mentions(waitlist),
            inline=False,
        )
    embed.add_field(
        name=f"🤔 보류 ({len(maybe)}명)",
        value=_format_rsvp_mentions(maybe),
        inline=True,
    )
    embed.add_field(
        name=f"❌ 불참 ({len(declined)}명)",
        value=_format_rsvp_mentions(declined),
        inline=True,
    )
    embed.set_footer(text=f"⏰ 시작 15분 전 자동 리마인드  |  ID: {ev_id}")
    return embed


class EventRSVPView(core.SafeView):
    """예약 이벤트 신청표 카드 뷰 (재부팅 후에도 message_id/footer로 자동 복구)"""

    def __init__(
        self,
        guild_id: Optional[int] = None,
        event_id: str = "",
        *,
        disabled_rsvp: bool = False,
    ):
        super().__init__(timeout=None)
        self.guild_id = int(guild_id) if guild_id else 0
        self.event_id = str(event_id or "")
        self.disabled_rsvp = bool(disabled_rsvp)
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        # Row 0: 참가 / 보류 / 불참
        b_go = discord.ui.Button(
            label="참가",
            emoji="✅",
            style=discord.ButtonStyle.success,
            disabled=self.disabled_rsvp,
            row=0,
            custom_id="norosi:EventRSVPView:go",
        )
        b_go.callback = self._make_rsvp_cb("going")
        self.add_item(b_go)

        b_mb = discord.ui.Button(
            label="보류",
            emoji="🤔",
            style=discord.ButtonStyle.secondary,
            disabled=self.disabled_rsvp,
            row=0,
            custom_id="norosi:EventRSVPView:mb",
        )
        b_mb.callback = self._make_rsvp_cb("maybe")
        self.add_item(b_mb)

        b_no = discord.ui.Button(
            label="불참",
            emoji="❌",
            style=discord.ButtonStyle.danger,
            disabled=self.disabled_rsvp,
            row=0,
            custom_id="norosi:EventRSVPView:no",
        )
        b_no.callback = self._make_rsvp_cb("declined")
        self.add_item(b_no)

        # Row 1: 새로고침 / 마감·취소
        b_rf = discord.ui.Button(
            label="새로고침",
            emoji="🔄",
            style=discord.ButtonStyle.secondary,
            row=1,
            custom_id="norosi:EventRSVPView:rf",
        )
        b_rf.callback = self._on_refresh
        self.add_item(b_rf)

        b_cl = discord.ui.Button(
            label="마감·취소",
            emoji="🔒",
            style=discord.ButtonStyle.secondary,
            disabled=self.disabled_rsvp,
            row=1,
            custom_id="norosi:EventRSVPView:cl",
        )
        b_cl.callback = self._on_close_or_cancel
        self.add_item(b_cl)

        b_ping = discord.ui.Button(
            label="참가자 호출",
            emoji="📣",
            style=discord.ButtonStyle.primary,
            disabled=self.disabled_rsvp,
            row=1,
            custom_id="norosi:EventRSVPView:ping",
        )
        b_ping.callback = self._on_ping_going
        self.add_item(b_ping)

    def _resolve_event_sync(self, data: dict, interaction: discord.Interaction) -> Optional[dict]:
        gid = self.guild_id or (interaction.guild.id if interaction.guild else 0)
        if not gid:
            return None
        if self.event_id:
            ev = community_core.get_guild_event(data, gid, self.event_id)
            if ev:
                return ev
        msg = interaction.message
        if msg:
            ev = community_core.find_guild_event_by_message_id(data, gid, msg.id)
            if ev:
                self.event_id = str(ev.get("id") or "")
                return ev
            for emb in getattr(msg, "embeds", []) or []:
                ft = getattr(getattr(emb, "footer", None), "text", "") or ""
                m = _EVENT_ID_FOOTER_RE.search(ft)
                if m:
                    ev = community_core.get_guild_event(data, gid, m.group(1))
                    if ev:
                        self.event_id = str(ev.get("id") or "")
                        return ev
        return None

    def _make_rsvp_cb(self, action: str):
        async def _cb(interaction: discord.Interaction):
            if not interaction.guild:
                await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
                return

            def _apply():
                with core._DATA_LOCK:
                    d = core.load_data()
                    ev = self._resolve_event_sync(d, interaction)
                    if not ev:
                        return None, "missing", None
                    res, promoted = community_core.update_event_rsvp(ev, interaction.user.id, action)
                    if res != "closed":
                        core.save_data(d)
                    return dict(ev), res, promoted

            ev_copy, res, promoted_uid = await asyncio.to_thread(_apply)
            if not ev_copy or res == "missing":
                await core.safe_send_response(interaction, "❌ 해당 이벤트 정보를 찾을 수 없습니다.", ephemeral=True)
                return
            if res == "closed":
                self.disabled_rsvp = True
                self._build_buttons()
                await core.safe_edit_response(interaction, embed=build_event_rsvp_embed(ev_copy), view=self)
                await interaction.followup.send("🔒 이미 마감되거나 취소된 이벤트입니다.", ephemeral=True)
                return

            await core.safe_edit_response(interaction, embed=build_event_rsvp_embed(ev_copy), view=self)
            msg_map = {
                "going": "✅ **참가 확정**으로 등록되었습니다!",
                "waitlist": "⏳ 정원이 가득 차서 **대기열**에 등록되었습니다. 빈자리가 나면 자동 승격됩니다!",
                "maybe": "🤔 **보류** 상태로 변경되었습니다.",
                "declined": "❌ **불참** 상태로 변경되었습니다.",
            }
            await interaction.followup.send(msg_map.get(res, "✅ 반영되었습니다."), ephemeral=True)

            if promoted_uid and interaction.channel:
                try:
                    await interaction.channel.send(
                        f"🎉 <@{promoted_uid}>님이 **`{ev_copy['title']}`** 이벤트 대기열에서 **✅ 참가 확정**으로 자동 승격되었습니다!"
                    )
                except Exception:
                    pass

        return _cb

    async def _on_refresh(self, interaction: discord.Interaction):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return

        def _load():
            d = core.load_data()
            ev = self._resolve_event_sync(d, interaction)
            return dict(ev) if ev else None

        ev_copy = await asyncio.to_thread(_load)
        if not ev_copy:
            await core.safe_send_response(interaction, "❌ 이벤트 정보를 찾을 수 없습니다.", ephemeral=True)
            return
        self.disabled_rsvp = (str(ev_copy.get("status") or "open") != "open")
        self._build_buttons()
        await core.safe_edit_response(interaction, embed=build_event_rsvp_embed(ev_copy), view=self)

    async def _on_ping_going(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return

        def _check_ping():
            with core._DATA_LOCK:
                d = core.load_data()
                ev = self._resolve_event_sync(d, interaction)
                if not ev:
                    return None, "missing"
                is_host = int(ev.get("host_id") or 0) == interaction.user.id
                is_adm = _is_guild_admin(interaction.user, perm_attr="manage_guild")
                if not (is_host or is_adm):
                    return dict(ev), "denied"
                now_ts = time.time()
                if now_ts - float(ev.get("last_ping_ts", 0.0) or 0.0) < 120.0:
                    return dict(ev), "cooldown"
                ev["last_ping_ts"] = now_ts
                core.save_data(d)
                return dict(ev), "ok"

        ev_copy, state = await asyncio.to_thread(_check_ping)
        if state == "missing" or not ev_copy:
            await core.safe_send_response(interaction, "❌ 이벤트 정보를 찾을 수 없습니다.", ephemeral=True)
            return
        if state == "denied":
            await core.safe_send_response(interaction, "❌ 이벤트 주최자 또는 서버 관리자만 참가자를 호출할 수 있습니다.", ephemeral=True)
            return
        if state == "cooldown":
            await core.safe_send_response(interaction, "⏳ 참가자 호출은 2분에 한 번만 보낼 수 있습니다.", ephemeral=True)
            return
        going = community_core._normalize_uid_list(ev_copy.get("going"))
        if not going:
            await core.safe_send_response(interaction, "ℹ️ 현재 `✅ 참가` 확정 멤버가 없습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        mentions = " ".join(f"<@{u}>" for u in going[:30])
        await interaction.channel.send(
            content=f"📣 **[{ev_copy.get('title', '이벤트')}] 참가 확정 멤버 호출!** ({interaction.user.mention})\n{mentions}",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        await interaction.followup.send(f"✅ 참가 확정 멤버 `{len(going)}명`에게 알림을 보냈습니다.", ephemeral=True)

    async def _on_close_or_cancel(self, interaction: discord.Interaction):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return

        def _check_and_close():
            with core._DATA_LOCK:
                d = core.load_data()
                ev = self._resolve_event_sync(d, interaction)
                if not ev:
                    return None, "missing"
                is_host = int(ev.get("host_id") or 0) == interaction.user.id
                is_adm = _is_guild_admin(interaction.user, perm_attr="manage_guild")
                if not (is_host or is_adm):
                    return dict(ev), "denied"
                if str(ev.get("status") or "open") != "open":
                    return dict(ev), "already"
                community_core.set_guild_event_status(d, interaction.guild.id, ev["id"], "closed")
                core.save_data(d)
                return dict(ev), "closed"

        ev_copy, state = await asyncio.to_thread(_check_and_close)
        if state == "missing" or not ev_copy:
            await core.safe_send_response(interaction, "❌ 이벤트 정보를 찾을 수 없습니다.", ephemeral=True)
            return
        if state == "denied":
            await core.safe_send_response(interaction, "❌ 이벤트 주최자 또는 서버 관리자만 마감할 수 있습니다.", ephemeral=True)
            return
        self.disabled_rsvp = True
        self._build_buttons()
        await core.safe_edit_response(interaction, embed=build_event_rsvp_embed(ev_copy), view=self)
        await interaction.followup.send(f"🔒 **`{ev_copy['title']}`** 이벤트 모집을 마감했습니다.", ephemeral=True)


class EventCreateModal(core.SafeModal, title="🗓️ 새 예약 이벤트 생성"):
    ev_title = discord.ui.TextInput(
        label="이벤트 제목",
        placeholder="예: 주말 프로세카 협동 라이브 / 내전 토너먼트",
        required=True,
        max_length=80,
    )
    ev_datetime = discord.ui.TextInput(
        label="시작 일시 (KST)",
        placeholder="예: 내일 21:00 / 05-15 20:30 / 2026-05-15 21:00 / +2시간",
        required=True,
        max_length=40,
    )
    ev_max_slots = discord.ui.TextInput(
        label="최대 참가 정원 (숫자, 0 또는 비우면 무제한)",
        placeholder="예: 5 (초과 시 자동 대기열 등록)",
        required=False,
        max_length=3,
    )
    ev_desc = discord.ui.TextInput(
        label="상세 안내 / 준비물 / 음성방 안내 (선택)",
        style=discord.TextStyle.paragraph,
        placeholder="참여 방법이나 주의사항을 자유롭게 적어주세요.",
        required=False,
        max_length=450,
    )

    def __init__(self, target_channel: discord.abc.Messageable):
        super().__init__()
        self.target_channel = target_channel

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 이벤트를 생성할 수 있습니다.", ephemeral=True)
            return

        start_dt, err = community_core.parse_kst_event_datetime(self.ev_datetime.value or "")
        if err or not start_dt:
            await core.safe_send_response(interaction, f"❌ {err}", ephemeral=True)
            return

        raw_slots = (self.ev_max_slots.value or "").strip()
        max_slots = 0
        if raw_slots:
            if not raw_slots.isdigit():
                await core.safe_send_response(interaction, "❌ 최대 정원은 숫자로만 입력해 주세요. (무제한은 `0` 또는 공백)", ephemeral=True)
                return
            max_slots = int(raw_slots)
            if max_slots == 1 or max_slots > 100:
                await core.safe_send_response(interaction, "❌ 정원은 `0(무제한)` 또는 `2 ~ 100` 사이로 입력해 주세요.", ephemeral=True)
                return

        await core.safe_defer(interaction, ephemeral=True)
        ch_id = getattr(self.target_channel, "id", 0) or (interaction.channel.id if interaction.channel else 0)

        def _create():
            with core._DATA_LOCK:
                d = core.load_data()
                ev = community_core.create_guild_event(
                    d,
                    interaction.guild.id,
                    ch_id,
                    interaction.user.id,
                    interaction.user.display_name,
                    self.ev_title.value or "",
                    start_dt,
                    max_slots=max_slots,
                    description=self.ev_desc.value or "",
                )
                core.save_data(d)
                return dict(ev)

        ev = await asyncio.to_thread(_create)
        rsvp_view = EventRSVPView(guild_id=interaction.guild.id, event_id=ev["id"])
        rsvp_embed = build_event_rsvp_embed(ev)

        sent_msg = None
        try:
            sent_msg = await self.target_channel.send(embed=rsvp_embed, view=rsvp_view)
        except Exception as e:
            await interaction.followup.send(f"❌ 채널에 이벤트 신청표를 게시하지 못했습니다: {e}", ephemeral=True)
            return

        if sent_msg:
            def _bind_msg():
                with core._DATA_LOCK:
                    d = core.load_data()
                    community_core.set_guild_event_message_id(d, interaction.guild.id, ev["id"], sent_msg.id)
                    core.save_data(d)

            await asyncio.to_thread(_bind_msg)

        await interaction.followup.send(
            f"✅ **`{ev['title']}`** 예약 이벤트 신청표를 게시했습니다!\n"
            f"🕒 시작: <t:{ev['start_ts']}:F> (<t:{ev['start_ts']}:R>) · ⏰ 시작 15분 전 자동 리마인드 예약 완료",
            ephemeral=True,
        )


class EventHubView(core.SafeView):
    """서버 예약 이벤트(RSVP) 목록 조회 및 새 이벤트 생성 허브 뷰"""

    def __init__(
        self,
        guild: Optional[discord.Guild] = None,
        user: Optional[discord.abc.User] = None,
        events: Optional[list[dict]] = None,
    ):
        super().__init__(timeout=None)
        self.guild = guild
        self.user = user
        self.events: list[dict] = list(events) if events is not None else []
        self._rebuild_items()

    def _rebuild_items(self):
        self.clear_items()
        if self.events:
            opts = []
            for ev in self.events[:20]:
                going_cnt = len(community_core._normalize_uid_list(ev.get("going")))
                max_s = int(ev.get("max_slots") or 0)
                cap = f"{going_cnt}/{max_s}명" if max_s > 0 else f"{going_cnt}명"
                opts.append(
                    discord.SelectOption(
                        label=str(ev.get("title") or "이벤트")[:80],
                        value=str(ev.get("id") or ""),
                        description=f"참가 {cap} · 주최 {str(ev.get('host_name') or '')[:20]}"[:100],
                        emoji="🗓️",
                    )
                )
            sel = discord.ui.Select(
                placeholder="🔍 신청표를 열거나 다시 볼 이벤트를 선택하세요...",
                options=opts,
                row=0,
                custom_id="norosi:EventHubView:select",
            )
            sel.callback = self._on_event_selected
            self.add_item(sel)

        # Row 1: 새 이벤트 만들기 / 새로고침
        b_new = discord.ui.Button(
            label="새 이벤트",
            emoji="➕",
            style=discord.ButtonStyle.success,
            row=1,
            custom_id="norosi:EventHubView:create",
        )
        b_new.callback = self._on_create_clicked
        self.add_item(b_new)

        b_ref = discord.ui.Button(
            label="새로고침",
            emoji="🔄",
            style=discord.ButtonStyle.primary,
            row=1,
            custom_id="norosi:EventHubView:refresh",
        )
        b_ref.callback = self._on_refresh_clicked
        self.add_item(b_ref)

    def build_embed(self) -> discord.Embed:
        g_name = self.guild.name if self.guild else "서버"
        if not self.events:
            body = (
                "현재 예정된 예약 이벤트가 없습니다.\n"
                "아래 **`[➕ 새 이벤트]`** 버튼을 눌러 RSVP 신청표를 만들어 보세요!\n\n"
                "• ✅ 참가 / 🤔 보류 / ❌ 불참 원클릭 집계\n"
                "• ⏳ 정원 초과 시 대기열 등록 및 빈자리 자동 승격\n"
                "• ⏰ 시작 15분 전 참가자 자동 리마인드 알림"
            )
        else:
            lines = []
            for idx, ev in enumerate(self.events[:10], 1):
                going_cnt = len(community_core._normalize_uid_list(ev.get("going")))
                wait_cnt = len(community_core._normalize_uid_list(ev.get("waitlist")))
                max_s = int(ev.get("max_slots") or 0)
                cap = f"`{going_cnt}/{max_s}명`" if max_s > 0 else f"`{going_cnt}명`"
                wait_txt = f" *(대기 {wait_cnt})*" if wait_cnt else ""
                start_ts = int(ev.get("start_ts") or 0)
                t_txt = f"<t:{start_ts}:f> (<t:{start_ts}:R>)" if start_ts > 0 else "미정"
                lines.append(f"`{idx}.` **{ev.get('title')}** — {cap}{wait_txt}\n　└ 🕒 {t_txt} · 주최 <@{ev.get('host_id')}>")
            body = "\n".join(lines)

        embed = discord.Embed(
            title=f"🗓️ {g_name} 예약 이벤트 신청표 (RSVP)",
            description=body,
            color=0x3498DB,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text=f"진행 중 이벤트 {len(self.events)}건  |  드롭다운에서 이벤트를 선택하면 바로 신청할 수 있습니다.")
        return embed

    async def _on_create_clicked(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 이벤트를 생성할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(EventCreateModal(interaction.channel))

    async def _on_refresh_clicked(self, interaction: discord.Interaction):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        self.guild = interaction.guild
        data = await asyncio.to_thread(core.load_data)
        self.events = community_core.get_guild_events(data, interaction.guild.id, include_closed=False)
        self._rebuild_items()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_event_selected(self, interaction: discord.Interaction):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        vals = (interaction.data or {}).get("values") or []
        ev_id = vals[0] if vals else ""
        data = await asyncio.to_thread(core.load_data)
        ev = community_core.get_guild_event(data, interaction.guild.id, ev_id)
        if not ev:
            await core.safe_send_response(interaction, "❌ 선택한 이벤트를 찾을 수 없습니다.", ephemeral=True)
            return
        rsvp_view = EventRSVPView(
            guild_id=interaction.guild.id,
            event_id=ev["id"],
            disabled_rsvp=(str(ev.get("status") or "open") != "open"),
        )
        await core.safe_send_response(interaction, embed=build_event_rsvp_embed(ev), view=rsvp_view, ephemeral=False)


async def open_guild_event_hub_from_interaction(interaction: discord.Interaction, *, ephemeral: bool = False):
    """어느 뷰(/설정 등)에서든 예약 이벤트 신청표 허브를 여는 공통 헬퍼"""
    if not interaction.guild:
        await core.safe_send_response(interaction, "❌ 예약 이벤트 기능은 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
        return
    data = await asyncio.to_thread(core.load_data)
    events = community_core.get_guild_events(data, interaction.guild.id, include_closed=False)
    view = EventHubView(guild=interaction.guild, user=interaction.user, events=events)
    embed = view.build_embed()
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, view=view, ephemeral=ephemeral, wait=True)
    else:
        await core.safe_send_response(interaction, embed=embed, view=view, ephemeral=ephemeral)


# ==========================================
# 7. 👋 웰컴 / 작별 이미지 카드 자동 생성 (서버 관리자 설정)
# ==========================================
async def _fetch_member_avatar_bytes(member: discord.abc.User) -> Optional[bytes]:
    try:
        asset = getattr(member, "display_avatar", None) or getattr(member, "avatar", None)
        if asset is None:
            return None
        return await asyncio.wait_for(asset.with_size(256).read(), timeout=4.0)
    except Exception:
        return None


def _build_welcome_or_goodbye_embed(
    guild: discord.Guild,
    member: discord.abc.User,
    cfg: dict,
    *,
    is_goodbye: bool = False,
    has_banner_file: bool = False,
) -> discord.Embed:
    m_count = int(getattr(guild, "member_count", 0) or len(getattr(guild, "members", []) or []) or 1)
    u_mention = getattr(member, "mention", str(member))
    u_name = getattr(member, "display_name", str(member))
    template = cfg.get("goodbye_message") if is_goodbye else cfg.get("welcome_message")
    body = community_core.format_welcome_text(
        str(template or ""),
        user_mention=u_mention,
        username=u_name,
        server_name=guild.name,
        member_count=m_count,
    )
    rgb = (237, 66, 69) if is_goodbye else community_core.hex_to_rgb_tuple(str(cfg.get("accent_color") or "#5865F2"))
    color_val = (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]

    raw_title_key = "goodbye_title" if is_goodbye else "welcome_title"
    default_title = community_core.DEFAULT_GOODBYE_TITLE if is_goodbye else community_core.DEFAULT_WELCOME_TITLE
    norm_title = community_core.normalize_welcome_embed_title(cfg.get(raw_title_key), default_title)
    title_str = (
        community_core.format_welcome_text(
            norm_title,
            user_mention=u_name,
            username=u_name,
            server_name=guild.name,
            member_count=m_count,
        )[:256]
        if norm_title
        else None
    )

    embed = discord.Embed(
        title=title_str or None,
        description=body,
        color=color_val,
        timestamp=datetime.datetime.now(core.KST),
    )
    av = getattr(member, "display_avatar", None)
    if av and not has_banner_file:
        embed.set_thumbnail(url=av.url)
    if has_banner_file:
        fname = "goodbye_banner.png" if is_goodbye else "welcome_banner.png"
        embed.set_image(url=f"attachment://{fname}")
    return embed


class WelcomeChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="1️⃣ 환영(입장) 카드가 발송될 텍스트 채널 선택...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "WelcomeConfigView" = self.view
        if not interaction.guild or not _is_guild_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 서버 관리자 권한이 필요합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        selected = self.values[0]
        guild_id = interaction.guild.id

        def _save():
            with core._DATA_LOCK:
                d = core.load_data()
                cfg = community_core.get_welcome_config(d, guild_id)
                cfg["welcome_channel_id"] = selected.id
                if not cfg.get("goodbye_channel_id"):
                    cfg["goodbye_channel_id"] = selected.id
                cfg["welcome_enabled"] = True
                saved = community_core.save_welcome_config(d, guild_id, cfg)
                core.save_data(d)
                return saved

        view.cfg = await asyncio.to_thread(_save)
        await interaction.edit_original_response(embed=view.build_embed(), view=view)
        await interaction.followup.send(f"✅ 환영 알림 채널이 <#{selected.id}> 채널로 설정되어 활성화되었습니다!", ephemeral=True)


class GoodbyeChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="2️⃣ 작별(퇴장) 카드가 발송될 텍스트 채널 선택...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "WelcomeConfigView" = self.view
        if not interaction.guild or not _is_guild_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 서버 관리자 권한이 필요합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        selected = self.values[0]
        guild_id = interaction.guild.id

        def _save():
            with core._DATA_LOCK:
                d = core.load_data()
                cfg = community_core.get_welcome_config(d, guild_id)
                cfg["goodbye_channel_id"] = selected.id
                cfg["goodbye_enabled"] = True
                saved = community_core.save_welcome_config(d, guild_id, cfg)
                core.save_data(d)
                return saved

        view.cfg = await asyncio.to_thread(_save)
        await interaction.edit_original_response(embed=view.build_embed(), view=view)
        await interaction.followup.send(f"✅ 작별 알림 채널이 <#{selected.id}> 채널로 설정되어 활성화되었습니다!", ephemeral=True)


class WelcomeAutoRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="3️⃣ 입장 시 자동 부여할 역할 선택 (여러 개 선택·추가 가능, 최대 10개)...",
            min_values=1,
            max_values=10,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "WelcomeConfigView" = self.view
        if not interaction.guild or not _is_guild_admin(interaction.user, perm_attr="manage_roles"):
            await core.safe_send_response(interaction, "❌ 역할 관리 또는 서버 관리자 권한이 필요합니다.", ephemeral=True)
            return
        valid_roles: list[discord.Role] = []
        skipped_default_or_managed: list[str] = []
        skipped_high: list[str] = []
        for role in self.values:
            if role.is_default() or role.managed:
                skipped_default_or_managed.append(role.name)
                continue
            if interaction.guild.me and role >= interaction.guild.me.top_role:
                skipped_high.append(role.name)
                continue
            valid_roles.append(role)

        if not valid_roles:
            reasons: list[str] = []
            if skipped_default_or_managed:
                reasons.append("기본 역할(`@everyone`)이나 봇·연동 전용 역할은 지정할 수 없습니다.")
            if skipped_high:
                reasons.append(f"**{', '.join(skipped_high)}** 역할이 봇의 최상위 역할보다 높거나 같아 자동 부여할 수 없습니다. 서버 설정에서 봇 역할을 더 위로 올려주세요.")
            await core.safe_send_response(interaction, "❌ " + "\n⚠️ ".join(reasons), ephemeral=True)
            return

        await core.safe_defer(interaction)
        guild_id = interaction.guild.id
        selected_ids = [r.id for r in valid_roles]

        def _save():
            with core._DATA_LOCK:
                d = core.load_data()
                cfg = community_core.get_welcome_config(d, guild_id)
                all_ids, added_ids, removed_ids = community_core.update_welcome_auto_roles(cfg, selected_ids)
                saved = community_core.save_welcome_config(d, guild_id, cfg)
                core.save_data(d)
                return saved, all_ids, added_ids, removed_ids

        view.cfg, all_ids, added_ids, removed_ids = await asyncio.to_thread(_save)
        await interaction.edit_original_response(embed=view.build_embed(), view=view)

        notes: list[str] = []
        if added_ids:
            mentions = " · ".join(f"<@&{rid}>" for rid in added_ids)
            notes.append(f"✅ 자동 부여 역할 추가: {mentions}")
        if removed_ids:
            mentions = " · ".join(f"<@&{rid}>" for rid in removed_ids)
            notes.append(f"➖ 자동 부여 역할 개별 해제: {mentions}")
        if not added_ids and not removed_ids:
            notes.append("ℹ️ 선택한 역할이 이미 목록에 등록되어 있거나 최대 개수(10개)에 도달했습니다.")
        total_mentions = " · ".join(f"<@&{rid}>" for rid in all_ids) if all_ids else "없음"
        notes.append(f"📌 **현재 자동 부여 역할 (`{len(all_ids)}개`):** {total_mentions}")
        if skipped_high:
            notes.append(f"⚠️ 봇 역할보다 높은 역할 제외됨: `{', '.join(skipped_high)}`")
        if skipped_default_or_managed:
            notes.append(f"⚠️ 기본/연동 전용 역할 제외됨: `{', '.join(skipped_default_or_managed)}`")
        await interaction.followup.send("\n".join(notes), ephemeral=True)


class WelcomeTemplateModal(discord.ui.Modal, title="✏️ 임베드 제목(비움=숨김) 및 본문 멘트 설정"):
    welcome_title_input = discord.ui.TextInput(
        label="환영 임베드 제목 (비우거나 '없음' 입력 시 숨김)",
        placeholder="예: 🎉 {server} · 신규 멤버 환영합니다! (비우면 제목 삭제)",
        required=False,
        max_length=150,
    )
    welcome_input = discord.ui.TextInput(
        label="환영 본문 멘트 ({user} {username} {server} {count})",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=400,
    )
    goodbye_title_input = discord.ui.TextInput(
        label="작별 임베드 제목 (비우거나 '없음' 입력 시 숨김)",
        placeholder="예: 👋 {server} · 멤버 퇴장 안내 (비우면 제목 삭제)",
        required=False,
        max_length=150,
    )
    goodbye_input = discord.ui.TextInput(
        label="작별 본문 멘트 ({username} {server} {count})",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=400,
    )

    def __init__(self, parent_view: "WelcomeConfigView"):
        super().__init__()
        self.parent_view = parent_view
        c = parent_view.cfg
        w_t = c.get("welcome_title")
        g_t = c.get("goodbye_title")
        self.welcome_title_input.default = community_core.DEFAULT_WELCOME_TITLE if w_t is None else str(w_t)
        self.welcome_input.default = str(c.get("welcome_message") or community_core.DEFAULT_WELCOME_MSG)
        self.goodbye_title_input.default = community_core.DEFAULT_GOODBYE_TITLE if g_t is None else str(g_t)
        self.goodbye_input.default = str(c.get("goodbye_message") or community_core.DEFAULT_GOODBYE_MSG)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not _is_guild_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 서버 관리자 권한이 필요합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        guild_id = interaction.guild.id
        w_title = community_core.normalize_welcome_embed_title(self.welcome_title_input.value or "", community_core.DEFAULT_WELCOME_TITLE)
        g_title = community_core.normalize_welcome_embed_title(self.goodbye_title_input.value or "", community_core.DEFAULT_GOODBYE_TITLE)
        w_msg = (self.welcome_input.value or "").strip() or community_core.DEFAULT_WELCOME_MSG
        g_msg = (self.goodbye_input.value or "").strip() or community_core.DEFAULT_GOODBYE_MSG

        def _save():
            with core._DATA_LOCK:
                d = core.load_data()
                cfg = community_core.get_welcome_config(d, guild_id)
                cfg["welcome_title"] = w_title
                cfg["goodbye_title"] = g_title
                cfg["welcome_message"] = w_msg
                cfg["goodbye_message"] = g_msg
                saved = community_core.save_welcome_config(d, guild_id, cfg)
                core.save_data(d)
                return saved

        self.parent_view.cfg = await asyncio.to_thread(_save)
        await core.safe_edit_response(interaction, embed=self.parent_view.build_embed(), view=self.parent_view)
        w_t_disp = f"`{w_title}`" if w_title else "**`숨김(제목 없음)`**"
        g_t_disp = f"`{g_title}`" if g_title else "**`숨김(제목 없음)`**"
        await core.safe_send_response(
            interaction,
            f"✅ 임베드 제목 및 본문 멘트가 저장되었습니다!\n• **환영 제목:** {w_t_disp}\n• **작별 제목:** {g_t_disp}",
            ephemeral=True,
        )


class WelcomeBannerCardModal(discord.ui.Modal, title="🎨 카드 안 환영·작별 멘트 및 배너 색상 설정"):
    welcome_sub_input = discord.ui.TextInput(
        label="카드 안 환영 멘트 ({username} {server} {count})",
        placeholder="예: {count}번째 멤버로 함께하게 되었어요!",
        required=True,
        max_length=80,
    )
    goodbye_sub_input = discord.ui.TextInput(
        label="카드 안 작별 멘트 ({username} {server} {count})",
        placeholder="예: {server} 서버와 함께해 주셔서 감사합니다.",
        required=True,
        max_length=80,
    )
    welcome_badge_input = discord.ui.TextInput(
        label="카드 안 환영 상단 배지 문구",
        placeholder="예: WELCOME · 서버 신규 멤버 입장",
        required=True,
        max_length=50,
    )
    goodbye_badge_input = discord.ui.TextInput(
        label="카드 안 작별 상단 배지 문구",
        placeholder="예: GOODBYE · 다음에 또 만나요",
        required=True,
        max_length=50,
    )
    color_input = discord.ui.TextInput(
        label="배너 색상 (블루·그린·골드·핑크·퍼플·레드·민트·하늘·주황 또는 #HEX)",
        required=True,
        max_length=16,
    )

    def __init__(self, parent_view: "WelcomeConfigView"):
        super().__init__()
        self.parent_view = parent_view
        c = parent_view.cfg
        self.welcome_sub_input.default = str(c.get("welcome_card_subtitle") or c.get("banner_subtitle") or community_core.DEFAULT_WELCOME_SUBTITLE)
        self.goodbye_sub_input.default = str(c.get("goodbye_card_subtitle") or community_core.DEFAULT_GOODBYE_SUBTITLE)
        self.welcome_badge_input.default = str(c.get("welcome_card_badge") or community_core.DEFAULT_WELCOME_BADGE)
        self.goodbye_badge_input.default = str(c.get("goodbye_card_badge") or community_core.DEFAULT_GOODBYE_BADGE)
        self.color_input.default = str(c.get("accent_color") or "#5865F2")

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not _is_guild_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 서버 관리자 권한이 필요합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        guild_id = interaction.guild.id
        w_sub = (self.welcome_sub_input.value or "").strip() or community_core.DEFAULT_WELCOME_SUBTITLE
        g_sub = (self.goodbye_sub_input.value or "").strip() or community_core.DEFAULT_GOODBYE_SUBTITLE
        w_badge = (self.welcome_badge_input.value or "").strip() or community_core.DEFAULT_WELCOME_BADGE
        g_badge = (self.goodbye_badge_input.value or "").strip() or community_core.DEFAULT_GOODBYE_BADGE
        col_hex = community_core._normalize_hex_color(self.color_input.value or "#5865F2")

        def _save():
            with core._DATA_LOCK:
                d = core.load_data()
                cfg = community_core.get_welcome_config(d, guild_id)
                cfg["banner_subtitle"] = w_sub
                cfg["welcome_card_subtitle"] = w_sub
                cfg["goodbye_card_subtitle"] = g_sub
                cfg["welcome_card_badge"] = w_badge
                cfg["goodbye_card_badge"] = g_badge
                cfg["accent_color"] = col_hex
                saved = community_core.save_welcome_config(d, guild_id, cfg)
                core.save_data(d)
                return saved

        self.parent_view.cfg = await asyncio.to_thread(_save)
        await core.safe_edit_response(interaction, embed=self.parent_view.build_embed(), view=self.parent_view)
        await core.safe_send_response(
            interaction,
            (
                f"✅ **카드 이미지 안 환영·작별 멘트**와 포인트 색상(`{col_hex}`)이 저장되었습니다!\n"
                f"• **카드 안 환영 멘트:** `{w_sub}` (배지: `{w_badge}`)\n"
                f"• **카드 안 작별 멘트:** `{g_sub}` (배지: `{g_badge}`)"
            ),
            ephemeral=True,
        )


class WelcomeConfigView(core.SafeView):
    """서버 관리자 전용 웰컴/작별 이미지 배너 카드 및 자동 역할 설정 뷰"""

    def __init__(self, author_id: int = 0, guild: Optional[discord.Guild] = None, cfg: Optional[dict] = None):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.guild = guild
        self.cfg = cfg if isinstance(cfg, dict) else community_core.get_welcome_config(core.get_cached_data(), getattr(guild, "id", 0))
        self.add_item(WelcomeChannelSelect())
        self.add_item(GoodbyeChannelSelect())
        self.add_item(WelcomeAutoRoleSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not _is_guild_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 서버 관리자 권한이 필요합니다.", ephemeral=True)
            return False
        if self.guild is None and interaction.guild:
            self.guild = interaction.guild
        if interaction.guild:
            self.cfg = community_core.get_welcome_config(core.get_cached_data(), interaction.guild.id)
        return True

    def build_embed(self) -> discord.Embed:
        c = self.cfg
        gname = getattr(self.guild, "name", None) or "서버"
        w_ch = f"<#{c['welcome_channel_id']}>" if c.get("welcome_channel_id") else "⚠️ 미지정"
        g_ch_id = c.get("goodbye_channel_id") or c.get("welcome_channel_id")
        g_ch = f"<#{g_ch_id}>" if g_ch_id else "⚠️ 미지정"
        role_ids = c.get("auto_role_ids") or ([c["auto_role_id"]] if c.get("auto_role_id") else [])
        r_str = (
            f"(`{len(role_ids)}개`) " + " · ".join(f"<@&{rid}>" for rid in role_ids)
            if role_ids
            else "없음 *(아래 3️⃣번 드롭다운에서 최대 10개까지 다중 선택 가능)*"
        )
        rgb = community_core.hex_to_rgb_tuple(str(c.get("accent_color") or "#5865F2"))
        color_val = (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]

        w_title_raw = c.get("welcome_title")
        g_title_raw = c.get("goodbye_title")
        w_title_disp = f"`{w_title_raw}`" if w_title_raw else "**`숨김 (제목 없음)`**"
        g_title_disp = f"`{g_title_raw}`" if g_title_raw else "**`숨김 (제목 없음)`**"
        w_sub_disp = c.get("welcome_card_subtitle") or c.get("banner_subtitle") or community_core.DEFAULT_WELCOME_SUBTITLE
        g_sub_disp = c.get("goodbye_card_subtitle") or community_core.DEFAULT_GOODBYE_SUBTITLE
        w_badge_disp = c.get("welcome_card_badge") or community_core.DEFAULT_WELCOME_BADGE
        g_badge_disp = c.get("goodbye_card_badge") or community_core.DEFAULT_GOODBYE_BADGE

        embed = discord.Embed(
            title=f"👋 [{gname}] 환영 / 작별 배너 카드 & 자동 역할 설정",
            description=(
                f"• **입장 환영 알림:** {'🟢 **ON**' if c.get('welcome_enabled') else '🔴 **OFF**'} (채널: {w_ch})\n"
                f"• **퇴장 작별 알림:** {'🟢 **ON**' if c.get('goodbye_enabled') else '🔴 **OFF**'} (채널: {g_ch})\n"
                f"• **고해상도 PNG 배너 카드:** {'🖼️ **사용함 (ON)**' if c.get('banner_enabled', True) else '📝 **텍스트 임베드만 (OFF)**'}\n"
                f"• **입장 시 자동 부여 역할:** {r_str}\n"
                f"• **배너 포인트 색상:** `{c.get('accent_color', '#5865F2')}` *(프리셋: 블루·그린·골드·핑크·퍼플·레드·민트·하늘·주황)*\n"
                "━━━━━━━━━━━━━━━━\n"
                f"📌 **[임베드 제목 설정]** *(비우거나 `없음` 입력 시 제목 제거)*\n"
                f"• **환영 임베드 제목:** {w_title_disp}\n"
                f"• **작별 임베드 제목:** {g_title_disp}\n\n"
                f"🖼️ **[카드 이미지 안 텍스트]** *(`[🎨 카드 안 멘트·색상]` 버튼으로 변경)*\n"
                f"• **카드 안 환영 멘트:** `{w_sub_disp}` *(배지: `{w_badge_disp}`)*\n"
                f"• **카드 안 작별 멘트:** `{g_sub_disp}` *(배지: `{g_badge_disp}`)*\n\n"
                f"💬 **[임베드 본문 멘트 미리보기]** *(`[✏️ 제목·본문 편집]` 버튼으로 변경)*\n"
                f"• **환영 본문:** {c.get('welcome_message')}\n"
                f"• **작별 본문:** {c.get('goodbye_message')}\n\n"
                "💡 치환 변수: `{user}`(멘션), `{username}`(닉네임), `{server}`(서버명), `{count}`(현재 인원수)\n"
                "💡 **다중 자동 역할 팁:** 3️⃣번 드롭다운에서 여러 역할을 한 번에 선택하거나 추가로 더할 수 있으며, 이미 등록된 역할 1개만 다시 선택하면 해당 역할만 개별 해제됩니다."
            ),
            color=color_val,
            timestamp=datetime.datetime.now(core.KST),
        )
        return embed

    @discord.ui.button(label="환영 알림 ON/OFF", style=discord.ButtonStyle.success, emoji="👋", row=0)
    async def toggle_welcome_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return
        if not self.cfg.get("welcome_enabled") and not self.cfg.get("welcome_channel_id"):
            await core.safe_send_response(interaction, "⚠️ 먼저 아래 **1️⃣ 환영 카드가 발송될 텍스트 채널**을 선택해 주세요!", ephemeral=True)
            return
        await core.safe_defer(interaction)
        guild_id = interaction.guild.id

        def _toggle():
            with core._DATA_LOCK:
                d = core.load_data()
                cfg = community_core.get_welcome_config(d, guild_id)
                cfg["welcome_enabled"] = not cfg.get("welcome_enabled", False)
                saved = community_core.save_welcome_config(d, guild_id, cfg)
                core.save_data(d)
                return saved

        self.cfg = await asyncio.to_thread(_toggle)
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="작별 알림 ON/OFF", style=discord.ButtonStyle.primary, emoji="🚪", row=0)
    async def toggle_goodbye_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return
        if not self.cfg.get("goodbye_enabled") and not (self.cfg.get("goodbye_channel_id") or self.cfg.get("welcome_channel_id")):
            await core.safe_send_response(interaction, "⚠️ 먼저 아래 **2️⃣ 작별 카드가 발송될 텍스트 채널**을 선택해 주세요!", ephemeral=True)
            return
        await core.safe_defer(interaction)
        guild_id = interaction.guild.id

        def _toggle():
            with core._DATA_LOCK:
                d = core.load_data()
                cfg = community_core.get_welcome_config(d, guild_id)
                cfg["goodbye_enabled"] = not cfg.get("goodbye_enabled", False)
                saved = community_core.save_welcome_config(d, guild_id, cfg)
                core.save_data(d)
                return saved

        self.cfg = await asyncio.to_thread(_toggle)
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="이미지 배너 ON/OFF", style=discord.ButtonStyle.secondary, emoji="🖼️", row=0)
    async def toggle_banner_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return
        await core.safe_defer(interaction)
        guild_id = interaction.guild.id

        def _toggle():
            with core._DATA_LOCK:
                d = core.load_data()
                cfg = community_core.get_welcome_config(d, guild_id)
                cfg["banner_enabled"] = not cfg.get("banner_enabled", True)
                saved = community_core.save_welcome_config(d, guild_id, cfg)
                core.save_data(d)
                return saved

        self.cfg = await asyncio.to_thread(_toggle)
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="제목·본문 편집", style=discord.ButtonStyle.secondary, emoji="✏️", row=0)
    async def edit_modal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WelcomeTemplateModal(self))

    @discord.ui.button(label="카드 안 멘트·색상", style=discord.ButtonStyle.secondary, emoji="🎨", row=0)
    async def edit_banner_card_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WelcomeBannerCardModal(self))

    @discord.ui.button(label="환영 미리보기", style=discord.ButtonStyle.secondary, emoji="🧪", row=4)
    async def preview_test_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        av_bytes = await _fetch_member_avatar_bytes(member)
        m_count = int(getattr(guild, "member_count", 0) or len(getattr(guild, "members", []) or []) or 1)
        file_obj = None
        if self.cfg.get("banner_enabled", True):
            png_bytes = await asyncio.to_thread(
                community_core.render_welcome_banner_png,
                guild.name,
                member.display_name,
                m_count,
                av_bytes,
                is_goodbye=False,
                accent_hex=str(self.cfg.get("accent_color") or "#5865F2"),
                subtitle=str(self.cfg.get("welcome_card_subtitle") or self.cfg.get("banner_subtitle") or ""),
                badge_text=str(self.cfg.get("welcome_card_badge") or ""),
            )
            if png_bytes:
                import io
                file_obj = discord.File(io.BytesIO(png_bytes), filename="welcome_banner.png")
        preview_embed = _build_welcome_or_goodbye_embed(
            guild,
            member,
            self.cfg,
            is_goodbye=False,
            has_banner_file=(file_obj is not None),
        )
        if file_obj:
            await interaction.followup.send(content="🧪 **실제 입장 시 발송될 환영 카드 미리보기입니다:**", embed=preview_embed, file=file_obj, ephemeral=True)
        else:
            await interaction.followup.send(content="🧪 **실제 입장 시 발송될 환영 카드 미리보기입니다:**", embed=preview_embed, ephemeral=True)

    @discord.ui.button(label="작별 미리보기", style=discord.ButtonStyle.secondary, emoji="🚪", row=4)
    async def preview_goodbye_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        av_bytes = await _fetch_member_avatar_bytes(member)
        m_count = int(getattr(guild, "member_count", 0) or len(getattr(guild, "members", []) or []) or 1)
        file_obj = None
        if self.cfg.get("banner_enabled", True):
            png_bytes = await asyncio.to_thread(
                community_core.render_welcome_banner_png,
                guild.name,
                member.display_name,
                m_count,
                av_bytes,
                is_goodbye=True,
                accent_hex="#ED4245",
                subtitle=str(self.cfg.get("welcome_card_subtitle") or self.cfg.get("banner_subtitle") or ""),
                goodbye_subtitle=str(self.cfg.get("goodbye_card_subtitle") or ""),
                badge_text=str(self.cfg.get("goodbye_card_badge") or ""),
            )
            if png_bytes:
                import io
                file_obj = discord.File(io.BytesIO(png_bytes), filename="goodbye_banner.png")
        preview_embed = _build_welcome_or_goodbye_embed(
            guild,
            member,
            self.cfg,
            is_goodbye=True,
            has_banner_file=(file_obj is not None),
        )
        if file_obj:
            await interaction.followup.send(content="🚪 **실제 퇴장 시 발송될 작별 카드 미리보기입니다:**", embed=preview_embed, file=file_obj, ephemeral=True)
        else:
            await interaction.followup.send(content="🚪 **실제 퇴장 시 발송될 작별 카드 미리보기입니다:**", embed=preview_embed, ephemeral=True)

    @discord.ui.button(label="작별=환영채널 통일", style=discord.ButtonStyle.secondary, emoji="🔗", row=4)
    async def sync_channel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return
        w_ch = self.cfg.get("welcome_channel_id")
        if not w_ch:
            await core.safe_send_response(interaction, "⚠️ 먼저 환영 알림 채널을 지정해 주세요.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        guild_id = interaction.guild.id

        def _sync():
            with core._DATA_LOCK:
                d = core.load_data()
                cfg = community_core.get_welcome_config(d, guild_id)
                cfg["goodbye_channel_id"] = cfg.get("welcome_channel_id")
                saved = community_core.save_welcome_config(d, guild_id, cfg)
                core.save_data(d)
                return saved

        self.cfg = await asyncio.to_thread(_sync)
        await interaction.edit_original_response(embed=self.build_embed(), view=self)
        await interaction.followup.send(f"🔗 작별 알림 채널도 <#{w_ch}> 채널로 통일했습니다.", ephemeral=True)

    @discord.ui.button(label="자동 역할 해제", style=discord.ButtonStyle.danger, emoji="🗑️", row=4)
    async def clear_role_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return
        await core.safe_defer(interaction)
        guild_id = interaction.guild.id

        def _clear():
            with core._DATA_LOCK:
                d = core.load_data()
                cfg = community_core.get_welcome_config(d, guild_id)
                community_core.clear_welcome_auto_roles(cfg)
                saved = community_core.save_welcome_config(d, guild_id, cfg)
                core.save_data(d)
                return saved

        self.cfg = await asyncio.to_thread(_clear)
        await interaction.edit_original_response(embed=self.build_embed(), view=self)
        await interaction.followup.send("🗑️ 신규 멤버 자동 부여 역할 목록을 모두 해제했습니다.", ephemeral=True)


# ==========================================
# 8. ⏳ 실시간 카운트다운 타이머 임베드 (서버 관리자 전용)
# ==========================================
_COUNTDOWN_ID_FOOTER_RE = re.compile(r"ID:\s*(cd_[0-9a-f]{8})")


def _build_countdown_card_embed(timer: dict) -> discord.Embed:
    status = str(timer.get("status") or "active")
    title_raw = str(timer.get("title") or "카운트다운 이벤트")
    desc_raw = str(timer.get("description") or "").strip()
    target_ts = int(timer.get("target_ts") or 0)
    subs = community_core._normalize_uid_list(timer.get("subscribers"))
    creator_id = int(timer.get("creator_id") or 0)

    if status == "completed":
        title = f"🚀 [시간 도달] {title_raw}"
        color = 0x2ECC71
        time_block = (
            f"• **목표 시각:** <t:{target_ts}:F>\n"
            f"• **진행률:** `[██████████] 100%`\n"
            f"• **상태:** 🎉 **카운트다운이 종료되어 지금 시작합니다!**"
        )
    elif status == "cancelled":
        title = f"🛑 [취소됨] {title_raw}"
        color = 0x95A5A6
        time_block = f"• **목표 시각:** <t:{target_ts}:F>\n• **상태:** ⚪ 관리자에 의해 취소된 카운트다운입니다."
    else:
        title = f"⏳ {title_raw}"
        color = 0x5865F2
        now_ts = int(time.time())
        start_ts = 0
        raw_created = str(timer.get("created_at") or "")
        if raw_created:
            try:
                start_ts = int(datetime.datetime.fromisoformat(raw_created).timestamp())
            except Exception:
                start_ts = 0
        if start_ts <= 0 or start_ts >= target_ts:
            start_ts = max(1, target_ts - 3600)
        total_span = max(1, target_ts - start_ts)
        elapsed = max(0, min(total_span, now_ts - start_ts))
        pct = int(round((elapsed / total_span) * 100))
        filled = max(0, min(10, int(round(pct / 10))))
        bar_str = "█" * filled + "░" * (10 - filled)
        time_block = (
            f"• **남은 시간:** 🔥 **<t:{target_ts}:R>**\n"
            f"• **목표 시각:** <t:{target_ts}:F>\n"
            f"• **진행률:** `[{bar_str}] {pct}%`\n"
            f"• **시작 알림 예약:** **`{len(subs)}명`** *(아래 [🔔 시작 알림 받기] 클릭)*"
        )

    lines: list[str] = []
    if desc_raw:
        lines.append(desc_raw)
        lines.append("━━━━━━━━━━━━━━━━")
    lines.append(time_block)
    if creator_id:
        lines.append(f"• **등록 관리자:** <@{creator_id}>")

    embed = discord.Embed(
        title=title,
        description="\n".join(lines),
        color=color,
        timestamp=datetime.datetime.now(core.KST),
    )
    embed.set_footer(text=f"실시간 카운트다운 타이머  |  ID: {timer.get('timer_id', 'cd_00000000')}")
    return embed


class CountdownCardView(core.SafeView):
    """채널에 게시된 실시간 카운트다운 카드 하단 버튼 (멤버 알림 구독 + 대기 명단 + 관리자 연장/종료)"""

    def __init__(self, timer_id: str = "", disabled_all: bool = False):
        super().__init__(timeout=None)
        self.timer_id = timer_id
        if disabled_all:
            for item in self.children:
                if isinstance(item, discord.ui.Button) and getattr(item, "custom_id", "") != "norosi:CountdownCardView:subscribers":
                    item.disabled = True

    def _resolve_timer_id(self, interaction: discord.Interaction) -> str:
        if self.timer_id:
            return self.timer_id
        msg = interaction.message
        if msg and msg.embeds:
            ft = getattr(msg.embeds[0].footer, "text", "") or ""
            m = _COUNTDOWN_ID_FOOTER_RE.search(ft)
            if m:
                return m.group(1)
        return ""

    @discord.ui.button(
        label="시작 알림 받기",
        emoji="🔔",
        style=discord.ButtonStyle.primary,
        custom_id="norosi:CountdownCardView:subscribe",
        row=0,
    )
    async def subscribe_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild.id
        tid = self._resolve_timer_id(interaction)
        msg_id = interaction.message.id if interaction.message else 0

        def _toggle_sub():
            with core._DATA_LOCK:
                d = core.load_data()
                t = community_core.get_countdown_timer(d, guild_id, tid) if tid else community_core.find_countdown_timer_by_message(d, guild_id, msg_id)
                if not t or str(t.get("status") or "active") != "active":
                    return None, False, 0
                added, cnt = community_core.toggle_countdown_subscriber(d, guild_id, t["timer_id"], interaction.user.id)
                core.save_data(d)
                return dict(t), added, cnt

        timer_obj, added, cnt = await asyncio.to_thread(_toggle_sub)
        if not timer_obj:
            await interaction.followup.send("ℹ️ 이미 종료되었거나 취소된 카운트다운입니다.", ephemeral=True)
            return
        if interaction.message:
            try:
                await interaction.message.edit(embed=_build_countdown_card_embed(timer_obj), view=self)
            except Exception:
                pass
        if added:
            await interaction.followup.send(f"🔔 **시작 알림 예약 완료!** 카운트다운이 끝나면 멘션으로 알려드릴게요. (현재 `{cnt}명` 대기 중)", ephemeral=True)
        else:
            await interaction.followup.send(f"🔕 시작 알림 예약을 취소했습니다. (현재 `{cnt}명` 대기 중)", ephemeral=True)

    @discord.ui.button(
        label="알림 대기 명단",
        emoji="👥",
        style=discord.ButtonStyle.secondary,
        custom_id="norosi:CountdownCardView:subscribers",
        row=0,
    )
    async def subscribers_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild.id
        tid = self._resolve_timer_id(interaction)
        msg_id = interaction.message.id if interaction.message else 0

        def _read_subs():
            d = core.load_data()
            t = community_core.get_countdown_timer(d, guild_id, tid) if tid else community_core.find_countdown_timer_by_message(d, guild_id, msg_id)
            return dict(t) if t else None

        timer_obj = await asyncio.to_thread(_read_subs)
        if not timer_obj:
            await interaction.followup.send("❌ 해당 카운트다운 정보를 찾을 수 없습니다.", ephemeral=True)
            return
        subs = community_core._normalize_uid_list(timer_obj.get("subscribers"))
        if not subs:
            await interaction.followup.send("📭 아직 시작 알림을 신청한 멤버가 없습니다. **[🔔 시작 알림 받기]** 버튼을 눌러 첫 번째로 예약해 보세요!", ephemeral=True)
            return
        mentions = " · ".join(f"<@{u}>" for u in subs[:40])
        extra = f" 외 `{len(subs) - 40}명`" if len(subs) > 40 else ""
        await interaction.followup.send(
            f"👥 **[{timer_obj.get('title', '카운트다운')}] 시작 알림 대기 명단 (`{len(subs)}명`):**\n{mentions}{extra}",
            ephemeral=True,
        )

    @discord.ui.button(
        label="+10분 연장 (관리자)",
        emoji="⏰",
        style=discord.ButtonStyle.secondary,
        custom_id="norosi:CountdownCardView:extend10",
        row=0,
    )
    async def extend_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not _is_guild_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 카운트다운 시간 연장은 **서버 관리자**만 가능합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild.id
        tid = self._resolve_timer_id(interaction)
        msg_id = interaction.message.id if interaction.message else 0

        def _extend():
            with core._DATA_LOCK:
                d = core.load_data()
                t = community_core.get_countdown_timer(d, guild_id, tid) if tid else community_core.find_countdown_timer_by_message(d, guild_id, msg_id)
                if not t or str(t.get("status") or "active") != "active":
                    return None
                updated = community_core.extend_countdown_timer(d, guild_id, t["timer_id"], 600)
                core.save_data(d)
                return dict(updated) if updated else None

        timer_obj = await asyncio.to_thread(_extend)
        if not timer_obj:
            await interaction.followup.send("ℹ️ 이미 종료되었거나 취소된 카운트다운입니다.", ephemeral=True)
            return
        if interaction.message:
            try:
                await interaction.message.edit(embed=_build_countdown_card_embed(timer_obj), view=self)
            except Exception:
                pass
        await interaction.followup.send(f"⏰ 목표 시각을 **10분 연장**했습니다! (<t:{timer_obj['target_ts']}:R>)", ephemeral=True)

    @discord.ui.button(
        label="타이머 취소 (관리자)",
        emoji="🛑",
        style=discord.ButtonStyle.danger,
        custom_id="norosi:CountdownCardView:cancel",
        row=0,
    )
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not _is_guild_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 카운트다운 취소는 **서버 관리자**만 가능합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild.id
        tid = self._resolve_timer_id(interaction)
        msg_id = interaction.message.id if interaction.message else 0

        def _cancel():
            with core._DATA_LOCK:
                d = core.load_data()
                t = community_core.get_countdown_timer(d, guild_id, tid) if tid else community_core.find_countdown_timer_by_message(d, guild_id, msg_id)
                if not t:
                    return None
                updated = community_core.cancel_countdown_timer(d, guild_id, t["timer_id"])
                core.save_data(d)
                return dict(updated) if updated else None

        timer_obj = await asyncio.to_thread(_cancel)
        if not timer_obj:
            await interaction.followup.send("❌ 해당 카운트다운 정보를 찾을 수 없습니다.", ephemeral=True)
            return
        if interaction.message:
            try:
                await interaction.message.edit(
                    embed=_build_countdown_card_embed(timer_obj),
                    view=CountdownCardView(timer_obj["timer_id"], disabled_all=True),
                )
            except Exception:
                pass
        await interaction.followup.send("🛑 카운트다운 타이머를 취소했습니다.", ephemeral=True)


class CountdownTargetChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="📢 카운트다운 카드를 게시할 채널 선택 (기본: 현재 채널)...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "CountdownStudioView" = self.view
        if not interaction.guild or not _is_guild_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 서버 관리자 권한이 필요합니다.", ephemeral=True)
            return
        view.target_channel_id = self.values[0].id
        await core.safe_edit_response(interaction, embed=view.build_embed(), view=view)


class CountdownMentionRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="🔔 카운트다운 종료 시 멘션할 역할 선택 (선택 사항)...",
            min_values=1,
            max_values=1,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "CountdownStudioView" = self.view
        if not interaction.guild or not _is_guild_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 서버 관리자 권한이 필요합니다.", ephemeral=True)
            return
        role = self.values[0]
        view.mention_target = "@everyone" if role.is_default() else f"<@&{role.id}>"
        await core.safe_edit_response(interaction, embed=view.build_embed(), view=view)


class CountdownTimerManageSelect(discord.ui.Select):
    """스튜디오 내에서 개별 진행 중 타이머를 선택해 +10분 연장하거나 즉시 취소하는 드롭다운"""

    def __init__(self, active_timers: list[dict]):
        options: list[discord.SelectOption] = []
        for t in active_timers[:12]:
            tid = str(t.get("timer_id") or "")
            if not tid:
                continue
            title_s = str(t.get("title") or "카운트다운")[:45]
            options.append(
                discord.SelectOption(
                    label=f"[+10분 연장] {title_s}"[:100],
                    value=f"extend:{tid}",
                    description=f"ID: {tid} · 목표 시각을 10분 뒤로 연장합니다.",
                    emoji="⏰",
                )
            )
            options.append(
                discord.SelectOption(
                    label=f"[즉시 취소] {title_s}"[:100],
                    value=f"cancel:{tid}",
                    description=f"ID: {tid} · 해당 카운트다운 타이머만 즉시 취소합니다.",
                    emoji="🛑",
                )
            )
        super().__init__(
            placeholder="🎛️ 개별 카운트다운 선택 관리 (+10분 연장 / 즉시 취소)...",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=4,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "CountdownStudioView" = self.view
        if not interaction.guild or not _is_guild_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 서버 관리자 권한이 필요합니다.", ephemeral=True)
            return
        raw_val = str(self.values[0] or "")
        if ":" not in raw_val:
            return
        action, tid = raw_val.split(":", 1)
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild.id

        def _apply_one():
            with core._DATA_LOCK:
                d = core.load_data()
                t = community_core.get_countdown_timer(d, guild_id, tid)
                if not t or str(t.get("status") or "active") != "active":
                    return None, community_core.get_guild_countdown_timers(d, guild_id, active_only=True)
                if action == "extend":
                    updated = community_core.extend_countdown_timer(d, guild_id, tid, 600)
                else:
                    updated = community_core.cancel_countdown_timer(d, guild_id, tid)
                core.save_data(d)
                fresh_list = community_core.get_guild_countdown_timers(d, guild_id, active_only=True)
                return (dict(updated) if updated else None), fresh_list

        target_timer, fresh_active = await asyncio.to_thread(_apply_one)
        view.active_timers = fresh_active
        if target_timer:
            ch = interaction.guild.get_channel(int(target_timer.get("channel_id") or 0))
            msg_id = int(target_timer.get("message_id") or 0)
            if isinstance(ch, discord.TextChannel) and msg_id:
                try:
                    orig_msg = await ch.fetch_message(msg_id)
                    await orig_msg.edit(
                        embed=_build_countdown_card_embed(target_timer),
                        view=CountdownCardView(target_timer["timer_id"], disabled_all=(action == "cancel")),
                    )
                except Exception:
                    pass
        await interaction.edit_original_response(embed=view.build_embed(), view=view)
        if not target_timer:
            await interaction.followup.send("ℹ️ 해당 타이머는 이미 종료되었거나 취소되었습니다.", ephemeral=True)
        elif action == "extend":
            await interaction.followup.send(
                f"⏰ **{target_timer.get('title')}** 타이머를 **+10분 연장**했습니다! (<t:{target_timer.get('target_ts')}:R>)",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"🛑 **{target_timer.get('title')}** 타이머를 즉시 취소했습니다.",
                ephemeral=True,
            )


class CountdownCreateModal(discord.ui.Modal, title="⏳ 실시간 카운트다운 타이머 발행"):
    title_input = discord.ui.TextInput(
        label="카운트다운 제목 (시험·방송·내전·점검 등)",
        placeholder="예: 🎮 저녁 발로란트 5:5 내전 시작 / 📺 특별 라이브 방송",
        required=True,
        max_length=80,
    )
    time_input = discord.ui.TextInput(
        label="목표 시간 (예: 30분, 1시간 30분, 21:00, 내일 20:00)",
        placeholder="30분 / 2시간 / 21:30 / 내일 20:00 / 2026-11-27 20:00",
        required=True,
        max_length=40,
    )
    desc_input = discord.ui.TextInput(
        label="상세 안내 문구 (선택)",
        style=discord.TextStyle.paragraph,
        placeholder="시간이 되면 알림 예약자 및 지정 역할에게 자동으로 시작 알림이 발송됩니다.",
        required=False,
        max_length=600,
    )

    def __init__(self, studio_view: "CountdownStudioView", default_time: str = ""):
        super().__init__()
        self.studio_view = studio_view
        if default_time:
            self.time_input.default = default_time

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not _is_guild_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 카운트다운 발행은 **서버 관리자**만 가능합니다.", ephemeral=True)
            return
        target_ts = community_core.parse_countdown_time_spec(self.time_input.value)
        if not target_ts:
            await core.safe_send_response(
                interaction,
                "❌ 시간 형식을 인식하지 못했거나 이미 지난 시각입니다.\n"
                "👉 입력 예시: `30분`, `1시간 30분`, `2시간`, `21:00`, `내일 20:00`, `2026-11-27 20:00`",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        ch_id = self.studio_view.target_channel_id or (interaction.channel.id if interaction.channel else 0)
        target_ch = guild.get_channel(int(ch_id))
        if not isinstance(target_ch, discord.TextChannel):
            await core.safe_send_response(interaction, "❌ 카운트다운을 게시할 텍스트 채널을 찾을 수 없습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        title_str = (self.title_input.value or "카운트다운 이벤트").strip()
        desc_str = (self.desc_input.value or "").strip()
        mention_target = self.studio_view.mention_target

        def _create_record():
            with core._DATA_LOCK:
                d = core.load_data()
                rec = community_core.create_countdown_timer(
                    d,
                    guild.id,
                    target_ch.id,
                    interaction.user.id,
                    title=title_str,
                    target_ts=target_ts,
                    description=desc_str,
                    mention_target=mention_target,
                )
                core.save_data(d)
                return dict(rec)

        timer_rec = await asyncio.to_thread(_create_record)
        card_view = CountdownCardView(timer_rec["timer_id"])
        try:
            sent_msg = await target_ch.send(embed=_build_countdown_card_embed(timer_rec), view=card_view)
        except Exception as e:
            await interaction.followup.send(f"❌ {target_ch.mention} 채널에 카운트다운 메시지를 보내지 못했습니다: `{e}`", ephemeral=True)
            return

        def _bind_msg_id():
            with core._DATA_LOCK:
                d = core.load_data()
                t = community_core.get_countdown_timer(d, guild.id, timer_rec["timer_id"])
                if t:
                    t["message_id"] = sent_msg.id
                core.save_data(d)
                return community_core.get_guild_countdown_timers(d, guild.id, active_only=True)

        self.studio_view.active_timers = await asyncio.to_thread(_bind_msg_id)
        try:
            await interaction.edit_original_response(embed=self.studio_view.build_embed(), view=self.studio_view)
        except Exception:
            pass
        await interaction.followup.send(
            f"✅ {target_ch.mention} 채널에 **{title_str}** 실시간 카운트다운(<t:{target_ts}:R>)을 게시했습니다!",
            ephemeral=True,
        )


class CountdownStudioView(core.SafeView):
    """서버 관리자 전용 실시간 카운트다운 타이머 스튜디오 뷰"""

    def __init__(
        self,
        author_id: int = 0,
        guild: Optional[discord.Guild] = None,
        target_channel_id: int = 0,
        active_timers: Optional[list[dict]] = None,
    ):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.guild = guild
        self.target_channel_id = target_channel_id
        self.mention_target = "none"
        self.active_timers = (
            active_timers
            if isinstance(active_timers, list)
            else community_core.get_guild_countdown_timers(core.get_cached_data(), getattr(guild, "id", 0), active_only=True)
        )
        self._manage_select: Optional[CountdownTimerManageSelect] = None
        self.add_item(CountdownTargetChannelSelect())
        self.add_item(CountdownMentionRoleSelect())
        self._refresh_manage_select()

    def _refresh_manage_select(self) -> None:
        if self._manage_select is not None:
            try:
                self.remove_item(self._manage_select)
            except Exception:
                pass
            self._manage_select = None
        valid_timers = [t for t in (self.active_timers or []) if isinstance(t, dict) and t.get("timer_id")]
        if valid_timers:
            self._manage_select = CountdownTimerManageSelect(valid_timers)
            self.add_item(self._manage_select)

    def _restore_from_message(self, interaction: discord.Interaction):
        msg = getattr(interaction, "message", None)
        if msg and msg.embeds:
            desc = getattr(msg.embeds[0], "description", "") or ""
            m_ch = re.search(r"발송 대상 채널:\*\*\s*<#(\d+)>", desc)
            if m_ch:
                self.target_channel_id = int(m_ch.group(1))
            m_line = next((ln for ln in desc.splitlines() if "종료 시 멘션 대상:" in ln), "")
            if "@here" in m_line:
                self.mention_target = "here"
            elif "@everyone" in m_line:
                self.mention_target = "@everyone"
            else:
                m_role = re.search(r"<@&(\d+)>", m_line)
                if m_role:
                    self.mention_target = f"<@&{m_role.group(1)}>"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not _is_guild_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 실시간 카운트다운 스튜디오는 **서버 관리자**만 사용할 수 있습니다.", ephemeral=True)
            return False
        if self.guild is None and interaction.guild:
            self.guild = interaction.guild
        if not self.target_channel_id and isinstance(interaction.channel, discord.TextChannel):
            self.target_channel_id = interaction.channel.id
        if interaction.guild:
            self.active_timers = community_core.get_guild_countdown_timers(core.get_cached_data(), interaction.guild.id, active_only=True)
        return True

    def build_embed(self) -> discord.Embed:
        self._refresh_manage_select()
        gname = getattr(self.guild, "name", None) or "서버"
        ch_str = f"<#{self.target_channel_id}>" if self.target_channel_id else "현재 채널"
        m_label_map = {
            "none": "🔕 추가 역할 멘션 없음 *(알림 구독자만 멘션)*",
            "here": "📢 `@here` (현재 접속 중인 멤버) + 알림 구독자",
            "@everyone": "📣 `@everyone` (서버 전체) + 알림 구독자",
        }
        m_str = m_label_map.get(self.mention_target, f"🎭 {self.mention_target} 역할 + 알림 구독자")

        if not self.active_timers:
            timer_list_txt = "*(현재 진행 중인 카운트다운이 없습니다. 위 버튼으로 새 타이머를 발행해 보세요!)*"
        else:
            lines = []
            for idx, t in enumerate(self.active_timers[:10], start=1):
                ts = int(t.get("target_ts") or 0)
                subs_cnt = len(community_core._normalize_uid_list(t.get("subscribers")))
                lines.append(
                    f"`{idx}.` **{t.get('title')}** — <t:{ts}:R> (<t:{ts}:t>)\n"
                    f"　└ 채널: <#{t.get('channel_id')}> · 알림 대기 `{subs_cnt}명` · ID `{t.get('timer_id')}`"
                )
            timer_list_txt = "\n".join(lines)

        embed = discord.Embed(
            title=f"⏳ [{gname}] 실시간 카운트다운 타이머 스튜디오 (서버 관리자)",
            description=(
                f"• **발송 대상 채널:** {ch_str}\n"
                f"• **종료 시 멘션 대상:** {m_str}\n"
                f"• **진행 중 카운트다운:** **`{len(self.active_timers)}건`**\n"
                "━━━━━━━━━━━━━━━━\n"
                f"**[진행 중인 카운트다운 목록]**\n{timer_list_txt}\n\n"
                "💡 **활용 팁:** 내전·방송·시험·이벤트 시작 전 카운트다운 임베드를 띄워두면 디스코드 화면에서 초 단위로 남은 시간이 실시간 표시되며, "
                "시간이 되면 알림을 신청한 멤버들에게 자동으로 시작 알림을 보내줍니다."
            ),
            color=0x5865F2,
            timestamp=datetime.datetime.now(core.KST),
        )
        return embed

    @discord.ui.button(label="새 카운트다운 발행", style=discord.ButtonStyle.success, emoji="⏳", row=0)
    async def open_create_modal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CountdownCreateModal(self))

    @discord.ui.button(label="10분 뒤", style=discord.ButtonStyle.primary, emoji="⚡", row=0)
    async def preset_10m_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CountdownCreateModal(self, default_time="10분"))

    @discord.ui.button(label="30분 뒤", style=discord.ButtonStyle.primary, emoji="⚡", row=0)
    async def preset_30m_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CountdownCreateModal(self, default_time="30분"))

    @discord.ui.button(label="1시간 뒤", style=discord.ButtonStyle.primary, emoji="⚡", row=0)
    async def preset_1h_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CountdownCreateModal(self, default_time="1시간"))

    @discord.ui.button(label="2시간 뒤", style=discord.ButtonStyle.primary, emoji="⚡", row=0)
    async def preset_2h_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CountdownCreateModal(self, default_time="2시간"))

    @discord.ui.button(label="종료 멘션 방식 전환", style=discord.ButtonStyle.secondary, emoji="🔔", row=3)
    async def cycle_mention_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        order = ["none", "here", "@everyone"]
        cur_idx = order.index(self.mention_target) if self.mention_target in order else -1
        self.mention_target = order[(cur_idx + 1) % len(order)]
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="진행 중 타이머 전체 취소", style=discord.ButtonStyle.danger, emoji="🛑", row=3)
    async def cancel_all_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild.id

        def _cancel_all():
            with core._DATA_LOCK:
                d = core.load_data()
                active = community_core.get_guild_countdown_timers(d, guild_id, active_only=True)
                cancelled_list = []
                for t in active:
                    updated = community_core.cancel_countdown_timer(d, guild_id, t["timer_id"])
                    if updated:
                        cancelled_list.append(dict(updated))
                core.save_data(d)
                return cancelled_list

        cancelled_timers = await asyncio.to_thread(_cancel_all)
        for t in cancelled_timers:
            ch = interaction.guild.get_channel(int(t.get("channel_id") or 0))
            msg_id = int(t.get("message_id") or 0)
            if isinstance(ch, discord.TextChannel) and msg_id:
                try:
                    orig_msg = await ch.fetch_message(msg_id)
                    await orig_msg.edit(
                        embed=_build_countdown_card_embed(t),
                        view=CountdownCardView(t["timer_id"], disabled_all=True),
                    )
                except Exception:
                    pass
        self.active_timers = []
        await interaction.edit_original_response(embed=self.build_embed(), view=self)
        await interaction.followup.send(f"🛑 진행 중이던 카운트다운 `{len(cancelled_timers)}건`을 모두 취소했습니다.", ephemeral=True)

    @discord.ui.button(label="새로고침", style=discord.ButtonStyle.secondary, emoji="🔄", row=3)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        self.active_timers = community_core.get_guild_countdown_timers(data, interaction.guild.id, active_only=True)
        await interaction.edit_original_response(embed=self.build_embed(), view=self)


# ==========================================
# 메인 CommunityCog
# ==========================================
class CommunityCog(commands.Cog):
    """고정메시지(#8) · SNS 링크 보정(#12) · 레이드 비상방어(#42) · 릴레이 소설(#48) · 임시 음성방(#11) · 예약 이벤트 RSVP · 환영배너 · 카운트다운"""

    sticky_group = app_commands.Group(
        name="고정메시지",
        description="[관리자 전용] 새 채팅이 올라와도 채널 맨 아래에 항상 유지되는 자동 고정 메시지 관리",
        guild_only=True,
        default_permissions=discord.Permissions(manage_messages=True),
    )
    link_group = app_commands.Group(
        name="링크미리보기",
        description="[관리자] SNS 링크(X·인스타·틱톡·픽시브 등) 미리보기 보정 및 추적 태그 제거 설정",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )
    raid_group = app_commands.Group(
        name="비상모드",
        description="[관리자 전용] 동시 입장(Raid) · 봇 테러 감지 및 서버 긴급 잠금 방어",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )
    relay_group = app_commands.Group(
        name="릴레이소설",
        description="한 줄씩 번갈아 이어 쓰는 채널 협동 릴레이 소설",
        guild_only=True,
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._sticky_locks: dict[int, asyncio.Lock] = {}
        self._sticky_delay_tasks: dict[int, asyncio.Task] = {}
        self._raid_locks: dict[int, asyncio.Lock] = {}
        self._temp_voice_locks: dict[int, asyncio.Lock] = {}
        self._temp_voice_user_cd: dict[tuple[int, int], float] = {}
        self._last_sticky_post_ts: dict[int, float] = {}
        self._last_raid_alert_ts: dict[int, float] = {}
        self._link_webhook_cache: dict[int, discord.Webhook] = {}
        self._link_webhook_locks: dict[int, asyncio.Lock] = {}
        self._processed_link_msgs: OrderedDict[int, float] = OrderedDict()
        self._clean_link_messages: OrderedDict[int, int] = OrderedDict()
        self._deleting_clean_link_msgs: set[int] = set()

    async def cog_load(self):
        if not self.event_reminder_loop.is_running():
            self.event_reminder_loop.start()
        if not self.countdown_timer_loop.is_running():
            self.countdown_timer_loop.start()

    def cog_unload(self):
        if self.event_reminder_loop.is_running():
            self.event_reminder_loop.cancel()
        if self.countdown_timer_loop.is_running():
            self.countdown_timer_loop.cancel()
        for t in list(self._sticky_delay_tasks.values()):
            t.cancel()
        self._sticky_delay_tasks.clear()

    @tasks.loop(seconds=20)
    async def countdown_timer_loop(self):
        """실시간 카운트다운 타이머 종료 시각 도달 감지 및 시작 알림 발송 루프"""
        try:
            def _collect_due():
                with core._DATA_LOCK:
                    d = core.load_data()
                    due = community_core.collect_due_countdown_timers(d)
                    if due:
                        core.save_data(d)
                    return [dict(item) for item in due]

            due_timers = await asyncio.to_thread(_collect_due)
            for t in due_timers:
                ch = self.bot.get_channel(int(t.get("channel_id") or 0))
                if not isinstance(ch, discord.TextChannel):
                    continue
                msg_id = int(t.get("message_id") or 0)
                if msg_id:
                    try:
                        orig_msg = await ch.fetch_message(msg_id)
                        await orig_msg.edit(
                            embed=_build_countdown_card_embed(t),
                            view=CountdownCardView(t["timer_id"], disabled_all=True),
                        )
                    except Exception:
                        pass

                mention_parts: list[str] = []
                m_target = str(t.get("mention_target") or "none").strip()
                if m_target == "here":
                    mention_parts.append("@here")
                elif m_target == "@everyone":
                    mention_parts.append("@everyone")
                elif m_target.startswith("<@&"):
                    mention_parts.append(m_target)

                subs = community_core._normalize_uid_list(t.get("subscribers"))
                for uid in subs[:30]:
                    u_m = f"<@{uid}>"
                    if u_m not in mention_parts:
                        mention_parts.append(u_m)

                ping_text = " ".join(mention_parts) if mention_parts else ""
                done_embed = discord.Embed(
                    title=f"🚀 카운트다운 종료! — {t.get('title')}",
                    description=(
                        (f"{t.get('description')}\n━━━━━━━━━━━━━━━━\n" if t.get("description") else "")
                        + f"🕒 목표 시각(<t:{int(t.get('target_ts') or 0)}:F>)에 도달하여 지금 시작합니다!"
                    ),
                    color=0x2ECC71,
                    timestamp=datetime.datetime.now(core.KST),
                )
                try:
                    await ch.send(
                        content=ping_text or None,
                        embed=done_embed,
                        allowed_mentions=discord.AllowedMentions(everyone=True, users=True, roles=True),
                    )
                except Exception:
                    pass
        except Exception:
            pass

    @countdown_timer_loop.before_loop
    async def _before_countdown_timer_loop(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def event_reminder_loop(self):
        """예약 이벤트 시작 15분 전 자동 리마인드 및 시작 알림 발송 루프"""
        try:
            def _collect():
                with core._DATA_LOCK:
                    d = core.load_data()
                    due = community_core.collect_due_event_reminders(d)
                    if due:
                        core.save_data(d)
                    return [(dict(ev), kind) for ev, kind in due]

            due_list = await asyncio.to_thread(_collect)
            for ev, kind in due_list:
                ch = self.bot.get_channel(int(ev.get("channel_id") or 0))
                if not ch:
                    continue
                going = community_core._normalize_uid_list(ev.get("going"))
                mentions = " ".join(f"<@{u}>" for u in going[:25]) if going else f"<@{ev.get('host_id')}>"
                start_ts = int(ev.get("start_ts") or 0)
                if kind == "15m":
                    title = f"⏰ 15분 뒤 이벤트 시작! — {ev.get('title')}"
                    desc = f"🕒 시작 시각: <t:{start_ts}:F> (<t:{start_ts}:R>)\n참가 확정 멤버 여러분, 곧 시작하니 준비해 주세요!"
                    color = 0xF39C12
                else:
                    title = f"🚀 이벤트가 시작됩니다! — {ev.get('title')}"
                    desc = f"🕒 시작 시각: <t:{start_ts}:F>\n참가자 여러분 모두 모여주세요!"
                    color = 0x2ECC71
                embed = discord.Embed(title=title, description=desc, color=color, timestamp=datetime.datetime.now(core.KST))
                try:
                    await ch.send(content=mentions, embed=embed)
                except Exception:
                    pass
        except Exception:
            pass

    @event_reminder_loop.before_loop
    async def _before_event_reminder_loop(self):
        await self.bot.wait_until_ready()

    async def _execute_sticky_repost(self, channel: discord.abc.Messageable, guild_id: int, channel_id: int):
        lock = self._get_sticky_lock(channel_id)
        async with lock:
            def _prepare():
                with core._DATA_LOCK:
                    data = core.load_data()
                    cfg = community_core.get_sticky_config(data, guild_id, channel_id)
                    if not cfg or not cfg.get("enabled", True):
                        return None, None
                    return dict(cfg), cfg.get("last_message_id")

            cfg_snapshot, old_msg_id = await asyncio.to_thread(_prepare)
            if not cfg_snapshot:
                return

            if old_msg_id:
                try:
                    old_msg = await channel.fetch_message(int(old_msg_id))
                    await old_msg.delete()
                except Exception:
                    pass

            try:
                posted = await channel.send(embed=_build_sticky_embed(cfg_snapshot))
                self._last_sticky_post_ts[channel_id] = time.monotonic()

                def _commit():
                    with core._DATA_LOCK:
                        data = core.load_data()
                        cfg = community_core.get_sticky_config(data, guild_id, channel_id)
                        if not cfg or not cfg.get("enabled", True):
                            return
                        cfg["last_message_id"] = posted.id
                        cfg["msg_count"] = 0
                        cfg["last_posted_ts"] = time.time()
                        core.save_data(data)

                await asyncio.to_thread(_commit)
            except Exception:
                pass

    def _schedule_delayed_sticky(self, channel: discord.abc.Messageable, guild_id: int, channel_id: int, wait_sec: float):
        prev_task = self._sticky_delay_tasks.pop(channel_id, None)
        if prev_task and not prev_task.done():
            prev_task.cancel()

        async def _runner():
            try:
                await asyncio.sleep(max(0.5, float(wait_sec)))
                await self._execute_sticky_repost(channel, guild_id, channel_id)
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        self._sticky_delay_tasks[channel_id] = asyncio.create_task(_runner())

    def _get_sticky_lock(self, channel_id: int) -> asyncio.Lock:
        lock = self._sticky_locks.get(channel_id)
        if lock is None:
            lock = asyncio.Lock()
            self._sticky_locks[channel_id] = lock
        return lock

    def _get_raid_lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._raid_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._raid_locks[guild_id] = lock
        return lock

    def _get_temp_voice_lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._temp_voice_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._temp_voice_locks[guild_id] = lock
        return lock


    # ------------------------------------------
    # #8 관리자 자동 고정 메시지 커맨드
    # ------------------------------------------
    @sticky_group.command(name="설정", description="[관리자] 지정 채널 하단에 항상 유지될 고정 메시지(개수·대기초·색상)를 상세 설정합니다.")
    @app_commands.describe(
        채널="고정 메시지를 유지할 텍스트 채널 (미입력 시 현재 채널)",
        방식="갱신 작동 방식 (메시지 개수 기준 / 마지막 메시지 몇 초 뒤 / 복합 조건)",
        간격="몇 개의 메시지 이후 하단으로 갱신할지 설정 (1~100, 기본 1)",
        대기초="마지막 메시지로부터 몇 초 뒤에 갱신할지 설정 (0~600초, 0=즉시)",
        색상="고정 메시지 임베드 색상",
        제목="(선택) 제목을 바로 입력하려면 작성 (비워두면 제목 생략 가능)",
        내용="(선택) 본문을 바로 입력하려면 작성 (미입력 시 상세 설정 패널 열림)",
    )
    @app_commands.choices(
        방식=[
            app_commands.Choice(name=label, value=key)
            for key, label in community_core.STICKY_TRIGGER_MODE_LABELS.items()
        ],
        색상=[
            app_commands.Choice(name=label, value=key)
            for key, label in community_core.STICKY_COLOR_LABELS.items()
        ],
    )
    async def sticky_set_cmd(
        self,
        interaction: discord.Interaction,
        채널: Optional[discord.TextChannel] = None,
        방식: Optional[app_commands.Choice[str]] = None,
        간격: Optional[app_commands.Range[int, 1, 100]] = 1,
        대기초: Optional[app_commands.Range[int, 0, 600]] = 0,
        색상: Optional[app_commands.Choice[str]] = None,
        제목: Optional[str] = None,
        내용: Optional[str] = None,
    ):
        if not interaction.guild or not _is_guild_admin(interaction.user, perm_attr="manage_messages"):
            await core.safe_send_response(interaction, "❌ 메시지 관리 또는 관리자 권한이 필요합니다.", ephemeral=True)
            return

        target_ch = 채널 or interaction.channel
        if not isinstance(target_ch, (discord.TextChannel, discord.Thread)):
            await core.safe_send_response(interaction, "❌ 텍스트 채널 또는 스레드에서만 고정 메시지를 설정할 수 있습니다.", ephemeral=True)
            return

        color_val = 색상.value if 색상 else "gold"
        interval_val = int(간격 or 1)
        delay_val = int(대기초 or 0)
        mode_val = 방식.value if 방식 else ("both" if (delay_val > 0 and interval_val > 1) else ("delay" if delay_val > 0 else "count"))

        if not 내용:
            data = await asyncio.to_thread(core.load_data)
            existing = community_core.get_sticky_config(data, interaction.guild.id, target_ch.id)
            modal = StickyConfigModal(
                target_ch,
                interval=interval_val,
                delay_sec=delay_val,
                trigger_mode=mode_val,
                color=color_val,
                existing=existing,
            )
            if 제목:
                modal.title_input.default = 제목[:120]
            await interaction.response.send_modal(modal)
            return

        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild.id
        channel_id = target_ch.id

        def _get_prev_id():
            with core._DATA_LOCK:
                d = core.load_data()
                prev = community_core.get_sticky_config(d, guild_id, channel_id)
                return prev.get("last_message_id") if prev else None

        prev_msg_id = await asyncio.to_thread(_get_prev_id)
        if prev_msg_id:
            try:
                old_msg = await target_ch.fetch_message(int(prev_msg_id))
                await old_msg.delete()
            except Exception:
                pass

        preview_cfg = {
            "title": (제목 or "").strip()[:120],
            "content": (내용 or "").strip()[:1800],
            "color": color_val if color_val in community_core.STICKY_COLOR_MAP else "gold",
            "interval": max(1, min(30, int(interval_val or 1))),
        }
        try:
            posted = await target_ch.send(embed=_build_sticky_embed(preview_cfg))
        except discord.Forbidden:
            await interaction.followup.send(f"❌ {target_ch.mention} 채널에 메시지를 보낼 권한이 없습니다.", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"❌ 고정 메시지 전송 중 오류가 발생했습니다: `{e}`", ephemeral=True)
            return

        self._last_sticky_post_ts[target_ch.id] = time.monotonic()

        def _save_sticky():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.set_sticky_config(
                    data,
                    guild_id,
                    channel_id,
                    제목 or "",
                    내용,
                    color=color_val,
                    interval=interval_val,
                    delay_sec=delay_val,
                    trigger_mode=mode_val,
                    updated_by=interaction.user.id,
                    last_message_id=posted.id,
                )
                cfg["last_posted_ts"] = time.time()
                core.save_data(data)
                return cfg

        cfg = await asyncio.to_thread(_save_sticky)
        await interaction.followup.send(
            f"✅ {target_ch.mention} 채널에 **자동 고정 메시지**가 등록되었습니다! (`{cfg['interval']}개` 메시지마다 갱신)",
            ephemeral=True,
        )

    @sticky_group.command(name="토글", description="[관리자] 채널의 자동 고정 메시지를 일시 중지하거나 다시 켭니다.")
    @app_commands.describe(상태="켜기/끄기 선택", 채널="대상 채널 (미입력 시 현재 채널)")
    @app_commands.choices(상태=[
        app_commands.Choice(name="🟢 켜기 (활성화)", value="on"),
        app_commands.Choice(name="🔴 끄기 (일시 중지)", value="off"),
    ])
    async def sticky_toggle_cmd(
        self,
        interaction: discord.Interaction,
        상태: app_commands.Choice[str],
        채널: Optional[discord.TextChannel] = None,
    ):
        if not interaction.guild or not _is_guild_admin(interaction.user, perm_attr="manage_messages"):
            await core.safe_send_response(interaction, "❌ 메시지 관리 또는 관리자 권한이 필요합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        target_ch = 채널 or interaction.channel
        if not target_ch:
            await interaction.followup.send("❌ 대상 채널을 찾을 수 없습니다.", ephemeral=True)
            return
        guild_id = interaction.guild.id
        channel_id = target_ch.id
        enabled_val = (상태.value == "on")

        def _toggle_sticky():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.toggle_sticky_config(data, guild_id, channel_id, enabled_val)
                if not cfg:
                    return None
                core.save_data(data)
                return cfg

        cfg = await asyncio.to_thread(_toggle_sticky)
        if not cfg:
            await interaction.followup.send(f"ℹ️ {target_ch.mention} 채널에 등록된 고정 메시지가 없습니다.", ephemeral=True)
            return
        state_str = "🟢 활성화" if cfg["enabled"] else "🔴 일시 중지"
        await interaction.followup.send(f"✅ {target_ch.mention} 채널의 자동 고정 메시지가 **{state_str}** 상태로 변경되었습니다.", ephemeral=True)

    @sticky_group.command(name="해제", description="[관리자] 채널의 자동 고정 메시지를 삭제하고 해제합니다.")
    @app_commands.describe(채널="고정 메시지를 해제할 채널 (미입력 시 현재 채널)")
    async def sticky_remove_cmd(
        self,
        interaction: discord.Interaction,
        채널: Optional[discord.TextChannel] = None,
    ):
        if not interaction.guild or not _is_guild_admin(interaction.user, perm_attr="manage_messages"):
            await core.safe_send_response(interaction, "❌ 메시지 관리 또는 관리자 권한이 필요합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        target_ch = 채널 or interaction.channel
        if not target_ch:
            await interaction.followup.send("❌ 대상 채널을 찾을 수 없습니다.", ephemeral=True)
            return
        guild_id = interaction.guild.id
        channel_id = target_ch.id

        def _remove_sticky():
            with core._DATA_LOCK:
                data = core.load_data()
                removed = community_core.remove_sticky_config(data, guild_id, channel_id)
                if not removed:
                    return None
                core.save_data(data)
                return removed

        removed = await asyncio.to_thread(_remove_sticky)
        if not removed:
            await interaction.followup.send(f"ℹ️ {target_ch.mention} 채널에 등록된 고정 메시지가 없습니다.", ephemeral=True)
            return
        if removed.get("last_message_id"):
            try:
                old_msg = await target_ch.fetch_message(int(removed["last_message_id"]))
                await old_msg.delete()
            except Exception:
                pass
        await interaction.followup.send(f"🗑️ {target_ch.mention} 채널의 자동 고정 메시지가 완전히 해제되었습니다.", ephemeral=True)

    @sticky_group.command(name="목록", description="[관리자] 서버에 등록된 모든 자동 고정 메시지 목록을 확인합니다.")
    async def sticky_list_cmd(self, interaction: discord.Interaction):
        if not interaction.guild or not _is_guild_admin(interaction.user, perm_attr="manage_messages"):
            await core.safe_send_response(interaction, "❌ 메시지 관리 또는 관리자 권한이 필요합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild = interaction.guild
        guild_id = guild.id

        def _load_and_clean_stickies():
            with core._DATA_LOCK:
                d = core.load_data()
                raw_stickies = dict(community_core.get_guild_stickies(d, guild_id))
                ghost_cids: list[int] = []
                for ch_id_s in list(raw_stickies.keys()):
                    if not str(ch_id_s).isdigit() or guild.get_channel(int(ch_id_s)) is None:
                        if str(ch_id_s).isdigit():
                            ghost_cids.append(int(ch_id_s))
                        raw_stickies.pop(ch_id_s, None)
                if ghost_cids:
                    for gcid in ghost_cids:
                        community_core.remove_sticky_config(d, guild_id, gcid)
                    core.save_data(d)
                return raw_stickies, len(ghost_cids)

        g_stickies, cleaned_cnt = await asyncio.to_thread(_load_and_clean_stickies)
        if not g_stickies:
            clean_note = f" *(삭제된 채널의 유령 설정 `{cleaned_cnt}건` 자동 정리됨)*" if cleaned_cnt else ""
            await interaction.followup.send(
                f"📭 이 서버에 등록된 자동 고정 메시지가 없습니다.{clean_note} `/설정` (`⚙️ 고급` ➔ `📌 자동 고정메시지 관리`)에서 추가해 보세요!",
                ephemeral=True,
            )
            return
        lines = []
        for ch_id_s, cfg in g_stickies.items():
            if not isinstance(cfg, dict):
                continue
            status = "🟢" if cfg.get("enabled", True) else "🔴"
            color_badge = community_core.STICKY_COLOR_LABELS.get(str(cfg.get("color") or "gold"), "🟡 골드")
            trig_summary = community_core.format_sticky_trigger_summary(cfg)
            lines.append(
                f"{status} <#{ch_id_s}> — **{cfg.get('title') or '(제목 없음)'}** (`{trig_summary}` · {color_badge})\n"
                f"└ *{str(cfg.get('content', ''))[:60]}*"
            )
        footer_note = f"총 {len(lines)}개 채널 운영 중"
        if cleaned_cnt:
            footer_note += f" · 삭제된 채널 유령 데이터 {cleaned_cnt}건 자동 청소됨"
        embed = discord.Embed(
            title=f"📌 [{guild.name}] 자동 고정 메시지 목록",
            description="\n\n".join(lines[:20]),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=footer_note)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------
    # #12 SNS 링크 미리보기 & 추적 제거 커맨드
    # ------------------------------------------
    @link_group.command(name="설정", description="[관리자] SNS 링크 미리보기 보정 및 추적 파라미터 제거 설정 패널을 엽니다.")
    async def link_config_cmd(self, interaction: discord.Interaction):
        if not interaction.guild or not _is_guild_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 서버 관리 권한이 필요합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        cfg = community_core.get_link_preview_config(data, interaction.guild.id)
        view = LinkPreviewConfigView(interaction.user.id, interaction.guild, cfg)
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)

    @link_group.command(name="채널제외", description="[관리자] 특정 채널에서 자동 링크 변환/정리 기능을 제외하거나 다시 포함합니다.")
    @app_commands.describe(채널="제외/포함할 텍스트 채널 (미입력 시 현재 채널)")
    async def link_ignore_channel_cmd(
        self,
        interaction: discord.Interaction,
        채널: Optional[discord.TextChannel] = None,
    ):
        if not interaction.guild or not _is_guild_admin(interaction.user):
            await core.safe_send_response(interaction, "❌ 서버 관리 권한이 필요합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        target_ch = 채널 or interaction.channel
        if not target_ch:
            await interaction.followup.send("❌ 대상 채널을 찾을 수 없습니다.", ephemeral=True)
            return
        guild_id = interaction.guild.id
        target_ch_id = target_ch.id
        target_ch_mention = target_ch.mention

        def _toggle_ignore_cmd():
            with core._DATA_LOCK:
                data = core.load_data()
                cfg = community_core.get_link_preview_config(data, guild_id)
                ignored = set(cfg["ignored_channels"])
                if target_ch_id in ignored:
                    ignored.remove(target_ch_id)
                    res_msg = f"✅ {target_ch_mention} 채널의 링크 자동 변환 제외가 해제되었습니다."
                else:
                    ignored.add(target_ch_id)
                    res_msg = f"🚫 {target_ch_mention} 채널이 링크 자동 변환 **제외 목록**에 추가되었습니다."
                cfg["ignored_channels"] = sorted(ignored)
                community_core.save_link_preview_config(data, guild_id, cfg)
                core.save_data(data)
                return res_msg

        res_msg = await asyncio.to_thread(_toggle_ignore_cmd)
        await interaction.followup.send(res_msg, ephemeral=True)

    # ------------------------------------------
    # #42 동시 입장(Raid) 비상 방어 커맨드
    # ------------------------------------------
    @raid_group.command(name="설정", description="[관리자] 동시 입장(Raid) 자동 감지 및 비상 방어 설정 패널을 엽니다.")
    async def raid_config_cmd(self, interaction: discord.Interaction):
        if not interaction.guild or not _is_guild_admin(interaction.user, need_admin=True):
            await core.safe_send_response(interaction, "❌ 서버 관리자(Administrator) 권한이 필요합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        cfg = community_core.get_raid_defense_config(data, interaction.guild.id)
        view = RaidDefenseConfigView(interaction.user.id, interaction.guild, cfg)
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)

    @raid_group.command(name="발동", description="[관리자] 수동으로 즉시 서버 비상 방어(잠금) 모드를 발동합니다.")
    @app_commands.describe(사유="비상모드 발동 사유 (선택)")
    async def raid_lockdown_cmd(self, interaction: discord.Interaction, 사유: Optional[str] = None):
        if not interaction.guild or not _is_guild_admin(interaction.user, need_admin=True):
            await core.safe_send_response(interaction, "❌ 서버 관리자(Administrator) 권한이 필요합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild.id
        reason_txt = (사유 or "관리자 수동 비상 잠금 발동").strip()[:200]

        def _read_cfg():
            with core._DATA_LOCK:
                d = core.load_data()
                return community_core.get_raid_defense_config(d, guild_id)

        init_cfg = await asyncio.to_thread(_read_cfg)
        invites_paused, paused_by_bot_now = await self._pause_invites_if_enabled(interaction.guild, init_cfg, reason_txt)

        def _save_lockdown():
            with core._DATA_LOCK:
                data = core.load_data()
                fresh_cfg = community_core.get_raid_defense_config(data, guild_id)
                if paused_by_bot_now:
                    fresh_cfg["invites_paused_by_bot"] = True
                fresh_cfg["lockdown_active"] = True
                fresh_cfg["lockdown_by"] = interaction.user.mention
                fresh_cfg["lockdown_reason"] = reason_txt[:200]
                fresh_cfg["lockdown_started_at"] = datetime.datetime.now(core.KST).isoformat()
                saved_cfg = community_core.save_raid_defense_config(data, guild_id, fresh_cfg)
                core.save_data(data)
                return saved_cfg, data

        cfg, data = await asyncio.to_thread(_save_lockdown)

        alert_ch = _resolve_raid_alert_channel(interaction.guild, cfg, data)
        if alert_ch and alert_ch.id != (interaction.channel.id if interaction.channel else 0):
            try:
                await alert_ch.send(
                    embed=self._build_raid_alert_embed(interaction.guild, cfg, invites_paused, recent_count=0),
                    view=RaidAlertControlView(),
                )
            except Exception:
                pass
        await interaction.followup.send(
            embed=self._build_raid_alert_embed(interaction.guild, cfg, invites_paused, recent_count=0),
            view=RaidAlertControlView(),
            ephemeral=True,
            wait=True,
        )

    @raid_group.command(name="해제", description="[관리자] 발동 중인 서버 비상 방어 모드를 해제합니다.")
    async def raid_unlock_cmd(self, interaction: discord.Interaction):
        if not interaction.guild or not _is_guild_admin(interaction.user, need_admin=True):
            await core.safe_send_response(interaction, "❌ 서버 관리자(Administrator) 권한이 필요합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild.id

        def _read_cfg():
            with core._DATA_LOCK:
                d = core.load_data()
                return community_core.get_raid_defense_config(d, guild_id)

        cfg = await asyncio.to_thread(_read_cfg)
        if not cfg["lockdown_active"]:
            await interaction.followup.send("ℹ️ 현재 비상모드가 활성화되어 있지 않습니다.", ephemeral=True)
            return

        restored = False
        if cfg.get("invites_paused_by_bot") and interaction.guild.me.guild_permissions.manage_guild:
            try:
                await interaction.guild.edit(invites_disabled=False, reason=f"비상모드 해제 ({interaction.user})")
                restored = True
            except Exception:
                pass

        def _save_unlock():
            with core._DATA_LOCK:
                data = core.load_data()
                fresh_cfg = community_core.get_raid_defense_config(data, guild_id)
                fresh_cfg["lockdown_active"] = False
                fresh_cfg["invites_paused_by_bot"] = False
                community_core.save_raid_defense_config(data, guild_id, fresh_cfg)
                core.save_data(data)

        await asyncio.to_thread(_save_unlock)
        community_core.RAID_TRACKER.clear_guild(guild_id)
        msg = "🔓 비상 방어 모드가 해제되었습니다." + (" (일시 중지된 초대 링크도 복구됨)" if restored else "")
        await interaction.followup.send(msg, ephemeral=True)

    @raid_group.command(name="상태", description="[관리자] 현재 비상 방어 설정과 최근 차단·감지 현황을 조회합니다.")
    async def raid_status_cmd(self, interaction: discord.Interaction):
        if not interaction.guild or not _is_guild_admin(interaction.user, need_admin=True):
            await core.safe_send_response(interaction, "❌ 서버 관리자(Administrator) 권한이 필요합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        cfg = community_core.get_raid_defense_config(data, interaction.guild.id)
        rate = community_core.RAID_TRACKER.current_rate(interaction.guild.id, cfg["window_sec"])
        view = RaidDefenseConfigView(interaction.user.id, interaction.guild, cfg)
        embed = view.build_embed()
        embed.add_field(
            name="📈 실시간 입장 빈도",
            value=f"최근 `{cfg['window_sec']}초` 내 입장: **`{rate}명`** (임계치: `{cfg['threshold']}명`)",
            inline=False,
        )
        logs = cfg.get("blocked_log") or []
        if logs:
            recent_txt = "\n".join(
                f"• `[{b.get('ts', '-')}]` `{b.get('user_name', '')}` — **{b.get('action', '')}** ({b.get('reason', '')})"
                for b in reversed(logs[-5:])
            )
            embed.add_field(name="🛡️ 최근 방어 조치 (최대 5건)", value=recent_txt, inline=False)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True, wait=True)

    # ------------------------------------------
    # #48 한 줄씩 이어 쓰는 릴레이 소설 커맨드
    # ------------------------------------------
    @relay_group.command(name="시작", description="현재 채널에서 한 줄씩 이어 쓰는 새 릴레이 소설을 시작합니다.")
    @app_commands.describe(
        제목="릴레이 소설 제목",
        첫문장="이야기의 포문을 여는 첫 문장 (2~280자)",
        목표턴="완결까지 총 몇 줄을 쓸지 설정 (3~30턴, 기본 10턴)",
        공개모드="블라인드(직전 1줄만 보고 이어쓰기) vs 전체 공개",
        연속작성="한 사람이 연달아 여러 줄을 쓸 수 있는지 여부 (기본: 금지)",
    )
    @app_commands.choices(
        공개모드=[
            app_commands.Choice(name="🔒 블라인드 모드 (직전 1줄만 공개 — 추천!)", value="blind"),
            app_commands.Choice(name="📖 전체 공개 모드 (모든 줄거리 보임)", value="open"),
        ],
        연속작성=[
            app_commands.Choice(name="🔁 번갈아 쓰기 (연속 작성 금지)", value="no"),
            app_commands.Choice(name="✍️ 자유롭게 이어쓰기 (연속 작성 허용)", value="yes"),
        ],
    )
    async def relay_start_cmd(
        self,
        interaction: discord.Interaction,
        제목: str,
        첫문장: str,
        목표턴: Optional[app_commands.Range[int, 3, 30]] = 10,
        공개모드: Optional[app_commands.Choice[str]] = None,
        연속작성: Optional[app_commands.Choice[str]] = None,
    ):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 시작할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        guild_id = interaction.guild.id
        channel_id = interaction.channel.id
        blind = (공개모드.value != "open") if 공개모드 else True
        allow_consec = (연속작성.value == "yes") if 연속작성 else False

        def _start_story():
            with core._DATA_LOCK:
                data = core.load_data()
                ok, msg, story = community_core.start_relay_novel(
                    data,
                    guild_id,
                    channel_id,
                    interaction.user.id,
                    interaction.user.display_name,
                    제목,
                    첫문장,
                    max_turns=int(목표턴 or 10),
                    blind_mode=blind,
                    allow_consecutive=allow_consec,
                )
                if ok and story:
                    core.save_data(data)
                return ok, msg, story

        ok, msg, story = await asyncio.to_thread(_start_story)
        if not ok or not story:
            await interaction.followup.send(f"⚠️ {msg}", ephemeral=True)
            return

        sent = await interaction.followup.send(embed=_build_relay_active_embed(story), view=RelayNovelView(), wait=True)
        if sent:
            def _set_msg_id():
                with core._DATA_LOCK:
                    data = core.load_data()
                    active = community_core.get_active_relay_novel(data, guild_id, channel_id)
                    if active and active.get("id") == story.get("id"):
                        active["message_id"] = sent.id
                        core.save_data(data)

            await asyncio.to_thread(_set_msg_id)

    @relay_group.command(name="현황", description="현재 채널에서 진행 중인 릴레이 소설 카드와 이어쓰기 버튼을 불러옵니다.")
    async def relay_status_cmd(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        guild_id = interaction.guild.id
        channel_id = interaction.channel.id
        data = await asyncio.to_thread(core.load_data)
        story = community_core.get_active_relay_novel(data, guild_id, channel_id)
        if not story:
            await interaction.followup.send(
                "ℹ️ 현재 이 채널에서 진행 중인 릴레이 소설이 없습니다. `/설정` (`✍️ 한 줄 릴레이 소설`)에서 새 이야기를 열어보세요!",
                ephemeral=True,
            )
            return
        sent = await interaction.followup.send(embed=_build_relay_active_embed(story), view=RelayNovelView(), wait=True)
        if sent:
            def _update_msg_id():
                with core._DATA_LOCK:
                    d = core.load_data()
                    active = community_core.get_active_relay_novel(d, guild_id, channel_id)
                    if active and active.get("id") == story.get("id"):
                        active["message_id"] = sent.id
                        core.save_data(d)

            await asyncio.to_thread(_update_msg_id)

    @relay_group.command(name="목록", description="이 서버에서 완결된 릴레이 소설 명작집을 다시 읽어봅니다.")
    async def relay_list_cmd(self, interaction: discord.Interaction):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버에서만 조회할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        completed = community_core.get_completed_relay_novels(data, interaction.guild.id)
        if not completed:
            await interaction.followup.send("📭 아직 완결된 릴레이 소설이 없습니다. `/설정` (`✍️ 한 줄 릴레이 소설`)에서 첫 작품을 만들어 보세요!", ephemeral=True)
            return
        view = RelayArchiveView(completed)
        await interaction.followup.send(embed=_build_relay_completed_embed(completed[0]), view=view, wait=True)

    @relay_group.command(name="중단", description="[개설자/관리자] 현재 채널에서 진행 중인 릴레이 소설을 취소하고 중단합니다.")
    async def relay_cancel_cmd(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild.id
        channel_id = interaction.channel.id
        is_admin = _is_guild_admin(interaction.user, perm_attr="manage_messages")

        def _cancel_story():
            with core._DATA_LOCK:
                data = core.load_data()
                story = community_core.get_active_relay_novel(data, guild_id, channel_id)
                if not story:
                    return "none", None
                if int(story.get("creator_id", 0)) != interaction.user.id and not is_admin:
                    return "denied", None
                removed = community_core.cancel_relay_novel(data, guild_id, channel_id)
                core.save_data(data)
                return "ok", removed

        status, removed = await asyncio.to_thread(_cancel_story)
        if status == "none":
            await interaction.followup.send("ℹ️ 현재 이 채널에서 진행 중인 릴레이 소설이 없습니다.", ephemeral=True)
            return
        if status == "denied":
            await interaction.followup.send("❌ 소설 개설자 또는 관리자만 중단할 수 있습니다.", ephemeral=True)
            return
        title_s = removed.get("title", "릴레이 소설") if removed else "릴레이 소설"
        await interaction.followup.send(f"🛑 진행 중이던 릴레이 소설 **『{title_s}』** 연재를 종료했습니다.", ephemeral=True)

    # ------------------------------------------
    # 내부 헬퍼: 레이드 방어 집행
    # ------------------------------------------
    def _build_raid_alert_embed(self, guild: discord.Guild, cfg: dict, invites_paused: bool, recent_count: int) -> discord.Embed:
        pause_txt = "⛔ **서버 초대 링크 일시 중지됨**" if invites_paused else ("⚠️ 초대 중지 미적용 (권한 부족 또는 설정 꺼짐)" if cfg.get("pause_invites") else "⚪ 초대 유지 설정")
        recent_line = f"• **감지된 동시 입장:** `{recent_count}명` / `{cfg['window_sec']}초`\n" if recent_count > 0 else ""
        embed = discord.Embed(
            title="🚨 [비상 방어 모드 발동] 서버 잠금(Lockdown) 활성화!",
            description=(
                f"• **발동 주체:** {cfg.get('lockdown_by', '시스템')}\n"
                f"• **발동 사유:** `{cfg.get('lockdown_reason') or '사유 없음'}`\n"
                f"{recent_line}"
                f"• **신규 입장 대응:** `{community_core.RAID_ACTION_LABELS.get(cfg['action'], cfg['action'])}`\n"
                f"• **초대 상태:** {pause_txt}\n\n"
                "비상모드가 켜져 있는 동안 새로 입장하는 계정은 설정된 방어 조치가 자동 적용됩니다.\n"
                "상황이 진정되면 아래 **`[🔓 비상모드 즉시 해제]`** 버튼을 눌러 주세요!"
            ),
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(core.KST),
        )
        return embed

    async def _pause_invites_if_enabled(
        self,
        guild: discord.Guild,
        cfg: dict,
        reason: str,
    ) -> tuple[bool, bool]:
        invites_paused = False
        paused_by_bot_now = False
        if cfg.get("pause_invites", True) and guild.me and guild.me.guild_permissions.manage_guild:
            try:
                if not guild.invites_disabled:
                    await guild.edit(invites_disabled=True, reason=f"비상모드 발동: {reason}")
                    paused_by_bot_now = True
                invites_paused = True
            except Exception:
                invites_paused = False
        return invites_paused, paused_by_bot_now

    async def _apply_raid_action(self, member: discord.Member, cfg: dict, reason: str) -> str:
        guild = member.guild
        me = guild.me
        if not me or member.top_role >= me.top_role or member.id == guild.owner_id:
            return "권한 우선순위로 건너뜀"

        action = cfg.get("action", "timeout")
        if action == "kick" and me.guild_permissions.kick_members:
            try:
                await member.kick(reason=reason)
                return "추방(Kick)"
            except Exception:
                pass

        if action == "quarantine" and cfg.get("quarantine_role_id") and me.guild_permissions.manage_roles:
            q_role = guild.get_role(int(cfg["quarantine_role_id"]))
            if q_role and q_role < me.top_role:
                try:
                    await member.add_roles(q_role, reason=reason)
                    return f"격리 역할({q_role.name})"
                except Exception:
                    pass

        # 기본 및 폴백: 타임아웃
        if me.guild_permissions.moderate_members:
            try:
                mins = int(cfg.get("timeout_min", 60) or 60)
                until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=mins)
                await member.timeout(until, reason=reason)
                return f"타임아웃({mins}분)"
            except Exception:
                pass
        return "조치 권한 부족(감지 기록만 남김)"

    async def _get_or_create_link_webhook(self, base_channel: discord.abc.GuildChannel) -> Optional[discord.Webhook]:
        cached = self._link_webhook_cache.get(base_channel.id)
        if cached is not None:
            return cached

        if len(self._link_webhook_locks) > 500:
            for k in list(self._link_webhook_locks.keys())[:100]:
                if not self._link_webhook_locks[k].locked():
                    self._link_webhook_locks.pop(k, None)
        lock = self._link_webhook_locks.setdefault(base_channel.id, asyncio.Lock())
        async with lock:
            cached = self._link_webhook_cache.get(base_channel.id)
            if cached is not None:
                return cached
            try:
                webhooks = await base_channel.webhooks()
                existing = next((w for w in webhooks if w.name == CLEAN_LINK_WEBHOOK_NAME and w.token), None)
                if not existing:
                    existing = next(
                        (w for w in webhooks if w.user and self.bot.user and w.user.id == self.bot.user.id and w.token),
                        None,
                    )
                if not existing:
                    existing = await base_channel.create_webhook(
                        name=CLEAN_LINK_WEBHOOK_NAME,
                        reason="클린 링크 깔끔 치환 전송용 웹훅",
                    )
                if len(self._link_webhook_cache) >= 500:
                    self._link_webhook_cache.pop(next(iter(self._link_webhook_cache)), None)
                self._link_webhook_cache[base_channel.id] = existing
                return existing
            except Exception:
                return None

    def _mark_link_processed(self, msg_id: int) -> bool:
        if msg_id in self._processed_link_msgs:
            return False
        self._processed_link_msgs[msg_id] = time.time()
        while len(self._processed_link_msgs) > 1000:
            self._processed_link_msgs.popitem(last=False)
        return True

    def _record_clean_link_message(self, sent_msg_id: int, author_id: int):
        self._clean_link_messages[sent_msg_id] = author_id
        while len(self._clean_link_messages) > 1000:
            self._clean_link_messages.popitem(last=False)

    @staticmethod
    def _build_clean_link_open_view(items: list[dict]) -> Optional[discord.ui.View]:
        view = discord.ui.View(timeout=None)
        added = 0
        for it in items[:3]:
            raw_url = str(it.get("canonical") or it.get("cleaned") or "")
            url = sns_embed_core._sanitize_discord_url(raw_url)
            if not url or len(url) > 512:
                continue
            label_base = str(it.get("service") or "링크")[:24]
            icon = "🔗" if it.get("kind") == "sns" else "🧹"
            view.add_item(
                discord.ui.Button(
                    style=discord.ButtonStyle.link,
                    label=f"{label_base} 열기",
                    emoji=icon,
                    url=url,
                )
            )
            added += 1
        return view if added > 0 else None

    @staticmethod
    def _needs_native_media_unfurl(items: list[dict]) -> bool:
        for it in items:
            if it.get("kind") == "sns":
                return True
            try:
                host = urllib.parse.urlsplit(str(it.get("cleaned") or "")).netloc.lower()
            except Exception:
                host = ""
            if host in _MEDIA_UNFURL_HOSTS:
                return True
        return False

    @staticmethod
    def _build_tracking_clean_embed(
        sender_name: str,
        sender_avatar: Optional[str],
        replaced_text: str,
        items: list[dict],
    ) -> discord.Embed:
        all_stripped: list[str] = []
        for it in items:
            for p in it.get("stripped_params") or []:
                if p not in all_stripped:
                    all_stripped.append(p)
        tag_line = (
            "\n\n🧹 **제거된 추적 태그:** " + ", ".join(f"`{p}`" for p in all_stripped[:6])
            if all_stripped
            else ""
        )
        embed = discord.Embed(
            description=(replaced_text + tag_line)[:4096],
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST),
        )
        if sender_avatar:
            embed.set_author(name=sender_name, icon_url=sender_avatar)
        else:
            embed.set_author(name=sender_name)
        embed.set_footer(text="클린 링크 변환됨  ·  ❌ 반응으로 삭제 가능")
        return embed

    async def _handle_clean_link_message(self, message: discord.Message, link_cfg: dict):
        replaced_masked, items = community_core.replace_urls_with_clean_links(
            message.content, link_cfg, canonical_plain=False
        )
        if not items or not self._mark_link_processed(message.id):
            return
        replaced_canonical, _ = community_core.replace_urls_with_clean_links(
            message.content, link_cfg, canonical_plain=True
        )

        channel = message.channel
        base_channel = channel.parent if isinstance(channel, discord.Thread) else channel
        me = message.guild.me
        if not me or base_channel is None:
            return

        perms = channel.permissions_for(me)
        can_send = perms.send_messages_in_threads if isinstance(channel, discord.Thread) else perms.send_messages
        can_use_webhook = hasattr(base_channel, "webhooks") and perms.manage_webhooks
        is_reply = bool(message.reference and message.reference.message_id)
        has_media = bool(message.attachments or message.stickers)
        want_replace = bool(link_cfg.get("suppress_original", True)) and (not has_media) and (len(replaced_canonical) <= 1800)

        can_replace_now = bool(want_replace and perms.manage_messages and (can_use_webhook or (is_reply and can_send)))
        webhook = await self._get_or_create_link_webhook(base_channel) if (can_replace_now and can_use_webhook) else None
        use_webhook = webhook is not None

        fresh_author = await resolve_fresh_author(message.guild, message.author) if use_webhook else message.author
        sender_name = sanitize_webhook_username(
            getattr(fresh_author, "display_name", None) or message.author.display_name
        )
        sender_avatar = resolve_webhook_avatar_url(fresh_author)
        safe_sender = discord.utils.escape_markdown(sender_name)

        reply_quote_header = ""
        reply_quote_allowed = discord.AllowedMentions.none()
        if is_reply and use_webhook:
            reply_quote_header, reply_quote_allowed = await build_reply_quote_header(message, channel)

        v2_sender_prefix = (
            reply_quote_header
            if (is_reply and use_webhook)
            else (f"-# {safe_sender}" if is_reply else "")
        )

        # 1) Components V2 리치 카드 사전 추출 (원본 삭제 전에 미리 준비해 실패 시 메시지 유실 원천 차단)
        primary = items[0]
        primary_url = primary.get("canonical") or primary.get("cleaned") or primary.get("original")
        primary_platform = primary.get("platform") or sns_embed_core.detect_sns_platform(primary_url) or "web"
        v2_layout = None
        v2_files: list[discord.File] = []
        post_data = None
        try:
            post_data = await sns_embed_core.fetch_sns_post_data(primary_url, platform=primary_platform)
            if post_data is not None:
                v2_layout, v2_files = await sns_embed_core.build_sns_components_v2_payload(
                    post_data,
                    top_text=replaced_canonical,
                    sender_prefix=v2_sender_prefix,
                )
        except Exception as e:
            print(f"⚠️ [clean_link] V2 build failed ({primary_platform}): {e}", flush=True)
            v2_layout = None
            v2_files = []

        # 2) 폴백 준비 (Instagram은 oginstagram.com 네이티브 Component Embed, 대용량 영상·API 실패 시 프록시 임베드)
        needs_unfurl = self._needs_native_media_unfurl(items)
        open_view = None if primary_platform == "instagram" else self._build_clean_link_open_view(items)
        stripped_note = ""
        if needs_unfurl and primary_platform != "instagram":
            stripped_all = [p for it in items for p in (it.get("stripped_params") or [])]
            if stripped_all:
                uniq_p = list(dict.fromkeys(stripped_all))[:4]
                stripped_note = "\n-# 🧹 추적 태그 제거됨 (" + ", ".join(uniq_p) + ")"
        clean_embed = (
            None
            if needs_unfurl
            else self._build_tracking_clean_embed(sender_name, sender_avatar, replaced_masked, items)
        )

        # 3) 이모지 업스케일 방식 치환 (일반·답장 모두 작성자 웹훅 우선, 웹훅 권한 없을 때만 앱 네이티브 답장 폴백)
        if can_replace_now and (use_webhook or (is_reply and can_send)):
            if use_webhook and webhook is not None:
                await prewarm_webhook_avatar_cache(fresh_author)
            core.mark_suppressed_delete_log(message.id)
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                core.consume_suppressed_delete_log(message.id)
                return

            sent_msg = None
            if use_webhook and webhook is not None:
                thread_obj = channel if isinstance(channel, discord.Thread) else None
                wh_allowed = reply_quote_allowed if is_reply else discord.AllowedMentions.none()

                async def _send_wh_with_retry(wh: discord.Webhook, avatar_url: Optional[str]):
                    base_wh_kwargs: dict = {
                        "username": sender_name,
                        "allowed_mentions": wh_allowed,
                        "wait": True,
                    }
                    if avatar_url is not None:
                        base_wh_kwargs["avatar_url"] = avatar_url
                    if thread_obj is not None:
                        base_wh_kwargs["thread"] = thread_obj

                    # 1순위: Components V2 리치 카드 (스크린샷 동일 포맷)
                    if v2_layout is not None:
                        try:
                            for f in v2_files:
                                f.reset()
                            kw_v2 = dict(base_wh_kwargs)
                            kw_v2["view"] = v2_layout
                            if v2_files:
                                kw_v2["files"] = v2_files
                            return await wh.send(**kw_v2)
                        except discord.HTTPException as e:
                            print(f"⚠️ [clean_link] V2 webhook failed ({primary_platform}): {e}", flush=True)
                            if post_data is not None and post_data.author_avatar:
                                try:
                                    v2_no_av, v2_no_av_files = await sns_embed_core.build_sns_components_v2_payload(
                                        post_data,
                                        top_text=replaced_canonical,
                                        sender_prefix=v2_sender_prefix,
                                        include_avatar_thumbnail=False,
                                    )
                                    if v2_no_av is not None:
                                        kw_v2_2 = dict(base_wh_kwargs)
                                        kw_v2_2["view"] = v2_no_av
                                        if v2_no_av_files:
                                            kw_v2_2["files"] = v2_no_av_files
                                        return await wh.send(**kw_v2_2)
                                except Exception:
                                    pass
                    # 2순위: 프록시 마스킹 링크([공식URL](oginstagram/fxtwitter 등)) 또는 추적제거 임베드
                    kw_fb = dict(base_wh_kwargs)
                    if clean_embed is not None:
                        if is_reply and reply_quote_header:
                            kw_fb["content"] = reply_quote_header
                        kw_fb["embed"] = clean_embed
                    else:
                        kw_fb["content"] = (
                            f"{reply_quote_header}\n{replaced_masked}{stripped_note}"
                            if (is_reply and reply_quote_header)
                            else f"{replaced_masked}{stripped_note}"
                        )
                    if open_view is not None:
                        kw_fb["view"] = open_view
                    try:
                        return await wh.send(**kw_fb)
                    except discord.HTTPException:
                        if "view" in kw_fb:
                            kw_fb.pop("view", None)
                            return await wh.send(**kw_fb)
                        raise

                def _cache_updated_link_wh(updated_wh: discord.Webhook) -> None:
                    self._link_webhook_cache[base_channel.id] = updated_wh

                try:
                    sent_msg = await send_webhook_with_verified_avatar(
                        webhook,
                        fresh_author,
                        _send_wh_with_retry,
                        guild=message.guild,
                        thread=thread_obj,
                        on_webhook_updated=_cache_updated_link_wh,
                    )
                except discord.NotFound:
                    self._link_webhook_cache.pop(base_channel.id, None)
                    fresh_wh = await self._get_or_create_link_webhook(base_channel)
                    if fresh_wh:
                        try:
                            sent_msg = await send_webhook_with_verified_avatar(
                                fresh_wh,
                                fresh_author,
                                _send_wh_with_retry,
                                guild=message.guild,
                                thread=thread_obj,
                                on_webhook_updated=_cache_updated_link_wh,
                            )
                        except Exception:
                            pass
                except Exception:
                    pass
            elif is_reply:
                reply_ref = discord.MessageReference(
                    message_id=message.reference.message_id,
                    channel_id=message.reference.channel_id or channel.id,
                    guild_id=message.reference.guild_id or message.guild.id,
                    fail_if_not_exists=False,
                )
                mention_target = bool(message.mentions)
                reply_allowed = discord.AllowedMentions(
                    everyone=False,
                    roles=False,
                    users=False,
                    replied_user=mention_target,
                )
                if v2_layout is not None:
                    try:
                        for f in v2_files:
                            f.reset()
                        v2_kw: dict = {
                            "view": v2_layout,
                            "reference": reply_ref,
                            "mention_author": mention_target,
                            "allowed_mentions": reply_allowed,
                        }
                        if v2_files:
                            v2_kw["files"] = v2_files
                        sent_msg = await channel.send(**v2_kw)
                    except discord.HTTPException as e:
                        print(f"⚠️ [clean_link] V2 reply failed: {e}", flush=True)
                        if post_data is not None and post_data.author_avatar:
                            try:
                                v2_no_av, v2_no_av_files = await sns_embed_core.build_sns_components_v2_payload(
                                    post_data,
                                    top_text=replaced_canonical,
                                    sender_prefix=f"-# {safe_sender}",
                                    include_avatar_thumbnail=False,
                                )
                                if v2_no_av is not None:
                                    kw2 = {
                                        "view": v2_no_av,
                                        "reference": reply_ref,
                                        "mention_author": mention_target,
                                        "allowed_mentions": reply_allowed,
                                    }
                                    if v2_no_av_files:
                                        kw2["files"] = v2_no_av_files
                                    sent_msg = await channel.send(**kw2)
                            except Exception:
                                sent_msg = None
                        else:
                            sent_msg = None
                if sent_msg is None:
                    send_kwargs: dict = {
                        "reference": reply_ref,
                        "mention_author": mention_target,
                        "allowed_mentions": reply_allowed,
                    }
                    if clean_embed is not None:
                        send_kwargs["embed"] = clean_embed
                    else:
                        send_kwargs["content"] = f"-# {safe_sender}\n{replaced_masked}{stripped_note}"
                    if open_view is not None:
                        send_kwargs["view"] = open_view
                    try:
                        sent_msg = await channel.send(**send_kwargs)
                    except Exception:
                        pass

            if sent_msg and getattr(sent_msg, "id", None):
                self._record_clean_link_message(int(sent_msg.id), int(message.author.id))
            return

        # 폴백 (첨부파일/스티커 포함, 치환 옵션 OFF, 또는 웹훅/삭제 권한 부재 시): 원본 보존 + 깔끔 답글
        if link_cfg.get("suppress_original", True) and perms.manage_messages:
            try:
                await message.edit(suppress=True)
            except Exception:
                pass

        if v2_layout is not None:
            try:
                for f in v2_files:
                    f.reset()
                v2_reply_kw: dict = {"view": v2_layout, "mention_author": False}
                if v2_files:
                    v2_reply_kw["files"] = v2_files
                sent_reply = await message.reply(**v2_reply_kw)
                if sent_reply and getattr(sent_reply, "id", None):
                    self._record_clean_link_message(int(sent_reply.id), int(message.author.id))
                return
            except discord.HTTPException as e:
                print(f"⚠️ [clean_link] V2 fallback reply failed: {e}", flush=True)
                if post_data is not None and post_data.author_avatar:
                    try:
                        v2_no_av, v2_no_av_files = await sns_embed_core.build_sns_components_v2_payload(
                            post_data,
                            top_text=replaced_canonical,
                            sender_prefix="",
                            include_avatar_thumbnail=False,
                        )
                        if v2_no_av is not None:
                            kw2 = {"view": v2_no_av, "mention_author": False}
                            if v2_no_av_files:
                                kw2["files"] = v2_no_av_files
                            sent_reply = await message.reply(**kw2)
                            if sent_reply and getattr(sent_reply, "id", None):
                                self._record_clean_link_message(int(sent_reply.id), int(message.author.id))
                            return
                    except Exception:
                        pass
            except Exception:
                pass

        if clean_embed is not None:
            try:
                await message.reply(embed=clean_embed, view=LinkCleanupView(), mention_author=False)
            except Exception:
                pass
            return

        link_lines = []
        for it in items:
            if it.get("canonical") and it["canonical"] != it["cleaned"]:
                link_lines.append(f"<{it['canonical']}>[\u2800]({it['cleaned']})")
            else:
                icon = "🔗" if it["kind"] == "sns" else "🧹"
                label = str(it["service"]).replace("[", "(").replace("]", ")")
                link_lines.append(f"[{icon} {label}]({it['cleaned']})")
        body = "\n".join(link_lines) + stripped_note
        try:
            await message.reply(body, view=LinkCleanupView(), mention_author=False)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """치환된 클린 링크 메시지에 작성자/관리자가 ❌(:x:) 반응을 달면 즉시 삭제합니다."""
        if not payload.guild_id:
            return
        if self.bot.user and payload.user_id == self.bot.user.id:
            return
        if payload.member and getattr(payload.member, "bot", False):
            return
        if not is_delete_reaction_emoji(payload.emoji):
            return
        author_id = self._clean_link_messages.get(payload.message_id)
        if author_id is None or payload.message_id in self._deleting_clean_link_msgs:
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

        is_mod = bool(isinstance(member, discord.Member) and _is_guild_admin(member, perm_attr="manage_messages"))
        is_owner = False
        if member and hasattr(self.bot, "is_bot_owner_user"):
            try:
                is_owner = await self.bot.is_bot_owner_user(member)
            except Exception:
                is_owner = False
        if not (payload.user_id == author_id or is_mod or is_owner):
            return

        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(payload.channel_id)
            except Exception:
                return
        if channel is None:
            return
        base_channel = channel.parent if isinstance(channel, discord.Thread) else channel

        self._deleting_clean_link_msgs.add(payload.message_id)
        try:
            deleted = False
            try:
                await channel.get_partial_message(payload.message_id).delete()
                deleted = True
            except discord.NotFound:
                deleted = True
            except (discord.Forbidden, discord.HTTPException):
                deleted = False

            if not deleted and base_channel is not None and hasattr(base_channel, "webhooks"):
                wh = await self._get_or_create_link_webhook(base_channel)
                if wh:
                    del_kwargs = {"thread": channel} if isinstance(channel, discord.Thread) else {}
                    try:
                        await wh.delete_message(payload.message_id, **del_kwargs)
                        deleted = True
                    except Exception:
                        pass

            if deleted:
                self._clean_link_messages.pop(payload.message_id, None)
        finally:
            self._deleting_clean_link_msgs.discard(payload.message_id)

    # ------------------------------------------
    # 리스너 1: on_message (#8 고정메시지 + #12 링크보정)
    # ------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or message.webhook_id:
            return

        cached = core.get_cached_data_ro()

        # 1) #12 SNS 링크 미리보기 개선 & 추적 파라미터 제거 ("http" 미포함 일반 채팅은 정규식 검사 즉시 생략)
        if message.content and "http" in message.content:
            try:
                link_cfg = community_core.get_link_preview_config(cached, message.guild.id)
                if link_cfg.get("enabled", False) and message.channel.id not in link_cfg.get("ignored_channels", []):
                    await self._handle_clean_link_message(message, link_cfg)
            except Exception:
                pass

        # 2) #8 자동 고정 메시지 (Sticky Message)
        try:
            sticky_cfg = community_core.get_sticky_config(cached, message.guild.id, message.channel.id)
            if sticky_cfg and sticky_cfg.get("enabled", True) and core.is_guild_feature_enabled(message.guild.id, "feat_admin_sticky", cached):
                guild_id = message.guild.id
                channel_id = message.channel.id
                msg_id = message.id
                def _tick_sticky():
                    with core._DATA_LOCK:
                        data = core.load_data()
                        cfg = community_core.get_sticky_config(data, guild_id, channel_id)
                        if not cfg or not cfg.get("enabled", True):
                            return "skip", 0
                        if cfg.get("last_message_id") and int(cfg["last_message_id"]) == msg_id:
                            return "skip", 0

                        cfg["msg_count"] = int(cfg.get("msg_count", 0) or 0) + 1
                        mode = str(cfg.get("trigger_mode") or "count")
                        interval = max(1, int(cfg.get("interval", 1) or 1))
                        delay_sec = max(0, int(cfg.get("delay_sec", 0) or 0))
                        cd = max(2, int(cfg.get("cooldown_sec", 3) or 3))
                        now_ts = time.time()
                        last_ts = float(cfg.get("last_posted_ts", 0.0) or 0.0)
                        core.save_data(data)

                        need_cnt = 1 if mode == "delay" else interval
                        if cfg["msg_count"] < need_cnt:
                            return "skip", 0
                        if mode in ("delay", "both") and delay_sec > 0:
                            return "delay", delay_sec
                        if (now_ts - last_ts) < cd:
                            return "skip", 0
                        return "post", 0

                act, wait_s = await asyncio.to_thread(_tick_sticky)
                if act == "delay":
                    self._schedule_delayed_sticky(message.channel, guild_id, channel_id, wait_s)
                elif act == "post":
                    prev_t = self._sticky_delay_tasks.pop(channel_id, None)
                    if prev_t and not prev_t.done():
                        prev_t.cancel()
                    await self._execute_sticky_repost(message.channel, guild_id, channel_id)
        except Exception:
            pass

    # ------------------------------------------
    # 리스너 2: on_member_join (#42 동시 입장 Raid 방어 + 👋 환영 배너 카드 & 자동 역할)
    # ------------------------------------------
    async def _handle_member_welcome(self, member: discord.Member):
        if not member.guild or member.bot:
            return
        guild = member.guild
        cached = core.get_cached_data()
        w_cfg = community_core.get_welcome_config(cached, guild.id)

        # 1) 입장 시 자동 역할 부여 (다중 역할 지원)
        role_ids = w_cfg.get("auto_role_ids") or ([w_cfg["auto_role_id"]] if w_cfg.get("auto_role_id") else [])
        if role_ids and guild.me and guild.me.guild_permissions.manage_roles:
            roles_to_add: list[discord.Role] = []
            for rid in role_ids:
                if not str(rid or "").isdigit():
                    continue
                role_obj = guild.get_role(int(rid))
                if (
                    role_obj
                    and not role_obj.is_default()
                    and not role_obj.managed
                    and role_obj < guild.me.top_role
                    and role_obj not in roles_to_add
                ):
                    roles_to_add.append(role_obj)
            if roles_to_add:
                try:
                    await member.add_roles(*roles_to_add, reason="신규 멤버 입장 자동 역할 부여")
                except Exception:
                    pass

        # 2) 환영 메시지 & PNG 배너 카드 발송
        if not w_cfg.get("welcome_enabled"):
            return
        ch_id = w_cfg.get("welcome_channel_id")
        if not ch_id:
            return
        ch = guild.get_channel(int(ch_id))
        if not isinstance(ch, discord.TextChannel):
            return
        if guild.me and not ch.permissions_for(guild.me).send_messages:
            return

        file_obj = None
        if w_cfg.get("banner_enabled", True):
            av_bytes = await _fetch_member_avatar_bytes(member)
            m_count = int(getattr(guild, "member_count", 0) or len(getattr(guild, "members", []) or []) or 1)
            png_bytes = await asyncio.to_thread(
                community_core.render_welcome_banner_png,
                guild.name,
                member.display_name,
                m_count,
                av_bytes,
                is_goodbye=False,
                accent_hex=str(w_cfg.get("accent_color") or "#5865F2"),
                subtitle=str(w_cfg.get("welcome_card_subtitle") or w_cfg.get("banner_subtitle") or ""),
                badge_text=str(w_cfg.get("welcome_card_badge") or ""),
            )
            if png_bytes:
                import io
                file_obj = discord.File(io.BytesIO(png_bytes), filename="welcome_banner.png")

        embed = _build_welcome_or_goodbye_embed(
            guild,
            member,
            w_cfg,
            is_goodbye=False,
            has_banner_file=(file_obj is not None),
        )
        try:
            if file_obj:
                await ch.send(content=member.mention, embed=embed, file=file_obj)
            else:
                await ch.send(content=member.mention, embed=embed)
        except Exception:
            pass

    async def _handle_member_goodbye(self, member: discord.Member):
        if not member.guild or member.bot:
            return
        guild = member.guild
        cached = core.get_cached_data()
        w_cfg = community_core.get_welcome_config(cached, guild.id)
        if not w_cfg.get("goodbye_enabled"):
            return
        ch_id = w_cfg.get("goodbye_channel_id") or w_cfg.get("welcome_channel_id")
        if not ch_id:
            return
        ch = guild.get_channel(int(ch_id))
        if not isinstance(ch, discord.TextChannel):
            return
        if guild.me and not ch.permissions_for(guild.me).send_messages:
            return

        file_obj = None
        if w_cfg.get("banner_enabled", True):
            av_bytes = await _fetch_member_avatar_bytes(member)
            m_count = int(getattr(guild, "member_count", 0) or len(getattr(guild, "members", []) or []) or 1)
            png_bytes = await asyncio.to_thread(
                community_core.render_welcome_banner_png,
                guild.name,
                member.display_name,
                m_count,
                av_bytes,
                is_goodbye=True,
                accent_hex=str(w_cfg.get("accent_color") or "#5865F2"),
                subtitle=str(w_cfg.get("welcome_card_subtitle") or w_cfg.get("banner_subtitle") or ""),
                goodbye_subtitle=str(w_cfg.get("goodbye_card_subtitle") or ""),
                badge_text=str(w_cfg.get("goodbye_card_badge") or ""),
            )
            if png_bytes:
                import io
                file_obj = discord.File(io.BytesIO(png_bytes), filename="goodbye_banner.png")

        embed = _build_welcome_or_goodbye_embed(
            guild,
            member,
            w_cfg,
            is_goodbye=True,
            has_banner_file=(file_obj is not None),
        )
        try:
            if file_obj:
                await ch.send(embed=embed, file=file_obj)
            else:
                await ch.send(embed=embed)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if not member.guild or member.bot:
            return
        await self._handle_member_goodbye(member)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.guild or member.bot:
            return

        guild_id = member.guild.id
        cached = core.get_cached_data()
        quick_cfg = community_core.get_raid_defense_config(cached, guild_id)
        if not quick_cfg["lockdown_active"] and not quick_cfg["enabled"] and quick_cfg["min_account_age_days"] <= 0:
            await self._handle_member_welcome(member)
            return

        lock = self._get_raid_lock(guild_id)
        async with lock:
            def _read_cfg():
                with core._DATA_LOCK:
                    d = core.load_data()
                    return community_core.get_raid_defense_config(d, guild_id)

            cfg = await asyncio.to_thread(_read_cfg)

            # 1) 이미 비상 잠금(Lockdown) 중이면 즉시 차단/조치
            if cfg["lockdown_active"]:
                act_res = await self._apply_raid_action(member, cfg, reason=f"비상 방어 잠금 중 입장 ({cfg.get('lockdown_reason', 'Raid')})")

                def _log_lockdown_block():
                    with core._DATA_LOCK:
                        data = core.load_data()
                        fresh_cfg = community_core.get_raid_defense_config(data, guild_id)
                        community_core.append_raid_blocked_log(fresh_cfg, member.id, str(member), act_res, "비상 잠금 중 입장")
                        community_core.save_raid_defense_config(data, guild_id, fresh_cfg)
                        core.save_data(data)

                await asyncio.to_thread(_log_lockdown_block)
                return

            # 2) 자동 감지 활성 시 슬라이딩 윈도우 검사
            if cfg["enabled"]:
                triggered, recent_ids = community_core.RAID_TRACKER.record_join(
                    guild_id,
                    member.id,
                    cfg["window_sec"],
                    cfg["threshold"],
                )
                if triggered:
                    reason_txt = f"{cfg['window_sec']}초 내 {len(recent_ids)}명 동시 입장(Raid) 감지"
                    paused_ok, paused_by_bot_now = await self._pause_invites_if_enabled(member.guild, cfg, reason_txt)

                    action_records: list[tuple[int, str, str]] = []
                    for uid in recent_ids:
                        target_m = member.guild.get_member(uid)
                        if target_m and not target_m.bot:
                            act_res = await self._apply_raid_action(target_m, cfg, reason=reason_txt)
                            action_records.append((target_m.id, str(target_m), act_res))

                    def _save_auto_lockdown():
                        with core._DATA_LOCK:
                            data = core.load_data()
                            fresh_cfg = community_core.get_raid_defense_config(data, guild_id)
                            if paused_by_bot_now:
                                fresh_cfg["invites_paused_by_bot"] = True
                            fresh_cfg["lockdown_active"] = True
                            fresh_cfg["lockdown_by"] = "🤖 자동 레이드 감지기"
                            fresh_cfg["lockdown_reason"] = reason_txt[:200]
                            fresh_cfg["lockdown_started_at"] = datetime.datetime.now(core.KST).isoformat()
                            for rec_uid, rec_name, rec_res in action_records:
                                community_core.append_raid_blocked_log(fresh_cfg, rec_uid, rec_name, rec_res, reason_txt)
                            saved_cfg = community_core.save_raid_defense_config(data, guild_id, fresh_cfg)
                            core.save_data(data)
                            return saved_cfg, data

                    saved_cfg, data = await asyncio.to_thread(_save_auto_lockdown)

                    now_m = time.monotonic()
                    if now_m - self._last_raid_alert_ts.get(guild_id, 0.0) >= 10.0:
                        self._last_raid_alert_ts[guild_id] = now_m
                        alert_ch = _resolve_raid_alert_channel(member.guild, saved_cfg, data)
                        if alert_ch:
                            try:
                                await alert_ch.send(
                                    embed=self._build_raid_alert_embed(member.guild, saved_cfg, paused_ok, recent_count=len(recent_ids)),
                                    view=RaidAlertControlView(),
                                )
                            except Exception:
                                pass
                    return

            # 3) 개별 신규 계정 생성일(min_account_age_days) 방어 옵션
            min_age = int(cfg.get("min_account_age_days", 0) or 0)
            if min_age > 0 and member.created_at:
                age_days = (datetime.datetime.now(datetime.timezone.utc) - member.created_at).days
                if age_days < min_age:
                    reason_txt = f"신규 계정 기준 미달 (가입 {age_days}일 < {min_age}일)"
                    act_res = await self._apply_raid_action(member, cfg, reason=reason_txt)

                    def _save_new_age_block():
                        with core._DATA_LOCK:
                            data = core.load_data()
                            fresh_cfg = community_core.get_raid_defense_config(data, guild_id)
                            community_core.append_raid_blocked_log(fresh_cfg, member.id, str(member), act_res, reason_txt)
                            saved_cfg = community_core.save_raid_defense_config(data, guild_id, fresh_cfg)
                            core.save_data(data)
                            return saved_cfg, data

                    saved_cfg, data = await asyncio.to_thread(_save_new_age_block)
                    alert_ch = _resolve_raid_alert_channel(member.guild, saved_cfg, data)
                    if alert_ch:
                        try:
                            warn_embed = discord.Embed(
                                title="⚠️ 신규 계정 자동 방어 조치",
                                description=(
                                    f"• **대상:** {member.mention} (`{member}` / ID: `{member.id}`)\n"
                                    f"• **사유:** `{reason_txt}`\n"
                                    f"• **조치 결과:** `{act_res}`"
                                ),
                                color=discord.Color.orange(),
                                timestamp=datetime.datetime.now(core.KST),
                            )
                            await alert_ch.send(embed=warn_embed)
                        except Exception:
                            pass
                    return

        await self._handle_member_welcome(member)

    # ------------------------------------------
    # #11 임시 음성방 자동 생성기 (/임시음성방 & on_voice_state_update)
    # ------------------------------------------
    @app_commands.command(
        name="임시음성방",
        description="🔊 입장 시 개인 음성방이 자동 생성되는 '임시 음성방(Join-to-Create)' 설정 및 방장 리모컨을 엽니다.",
    )
    @app_commands.describe(
        메뉴="열어볼 메뉴 선택 (자동 / 리모컨 호출 / 관리자 설정 패널)",
    )
    @app_commands.choices(메뉴=[
        app_commands.Choice(name="🎛️ 내 임시 음성방 리모컨 호출 (방장/멤버용)", value="remote"),
        app_commands.Choice(name="⚙️ 생성기 채널 & 자동 생성 설정 (서버 관리자 전용)", value="setup"),
    ])
    async def temp_voice_slash_cmd(
        self,
        interaction: discord.Interaction,
        메뉴: Optional[app_commands.Choice[str]] = None,
    ):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return

        mode = 메뉴.value if 메뉴 else "auto"
        vc = _resolve_member_temp_voice_channel(interaction)
        data = await asyncio.to_thread(core.load_data)
        cfg = community_core.get_temp_voice_config(data, interaction.guild.id)
        room = community_core.get_temp_voice_room(data, interaction.guild.id, vc.id) if vc else None

        if mode == "remote" or (mode == "auto" and room is not None):
            if not vc or not room:
                await core.safe_send_response(
                    interaction,
                    "ℹ️ 현재 자동 생성된 임시 음성방에 접속해 있지 않습니다.\n"
                    + (f"👉 <#{cfg['generator_channel_id']}> 채널에 입장하면 나만의 음성방이 바로 만들어집니다!" if cfg.get("generator_channel_id") else "👉 서버 관리자가 `/설정` (`⚙️ 고급` ➔ `🔊 임시음성방 설정`)에서 카테고리와 자동생성 채널을 먼저 설정할 수 있습니다."),
                    ephemeral=True,
                )
                return
            await core.safe_defer(interaction)
            await interaction.followup.send(
                embed=_build_temp_voice_panel_embed(vc, room),
                view=TempVoiceControlView(vc.id),
                wait=True,
            )
            return

        if not _is_strict_server_admin(interaction.user):
            gen_ch_id = cfg.get("generator_channel_id")
            guide = (
                f"🔊 <#{gen_ch_id}> 음성 채널에 입장하시면 자동으로 개인 음성방이 생성됩니다!\n"
                "생성된 방 안에 들어간 상태에서 `/설정` (`🎛️ 내 임시음성방 리모컨`)을 누르면 **방장 리모컨**을 다시 띄울 수 있습니다."
                if gen_ch_id and cfg.get("enabled")
                else "ℹ️ 임시 음성방 카테고리 지정 및 자동생성 채널 추가는 **서버 관리자(Administrator)** 만 가능합니다."
            )
            await core.safe_send_response(interaction, guide, ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        setup_view = TempVoiceSetupView(interaction.user.id, interaction.guild, cfg)
        await interaction.followup.send(embed=setup_view.build_embed(), view=setup_view, ephemeral=True, wait=True)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if not member.guild:
            return
        if before.channel == after.channel:
            return

        guild = member.guild
        guild_id = guild.id
        cached = core.get_cached_data()
        quick_cfg = community_core.get_temp_voice_config(cached, guild_id)

        before_id = before.channel.id if isinstance(before.channel, discord.VoiceChannel) else 0
        after_id = after.channel.id if isinstance(after.channel, discord.VoiceChannel) else 0

        is_leaving_temp = str(before_id) in (quick_cfg.get("active_rooms") or {})
        is_joining_gen = (
            not member.bot
            and bool(quick_cfg.get("enabled"))
            and after_id > 0
            and community_core.is_temp_voice_generator_channel(quick_cfg, after_id)
        )

        if not is_leaving_temp and not is_joining_gen:
            return

        lock = self._get_temp_voice_lock(guild_id)
        async with lock:
            # 1) 기존 임시 음성방에서 퇴장 시 빈 방 자동 삭제 또는 방장 퇴장 시 인계 안내
            if is_leaving_temp and isinstance(before.channel, discord.VoiceChannel):
                old_vc = guild.get_channel(before_id)
                if isinstance(old_vc, discord.VoiceChannel):
                    non_bot_members = [m for m in old_vc.members if not m.bot]
                    if len(non_bot_members) == 0 and not community_core.is_temp_voice_generator_channel(quick_cfg, before_id):
                        def _pop_room():
                            with core._DATA_LOCK:
                                d = core.load_data()
                                community_core.remove_temp_voice_room(d, guild_id, before_id)
                                core.save_data(d)

                        await asyncio.to_thread(_pop_room)
                        try:
                            await old_vc.delete(reason="임시 음성방 전원 퇴장으로 자동 삭제")
                        except Exception:
                            pass
                    elif len(non_bot_members) > 0:
                        room_info = (quick_cfg.get("active_rooms") or {}).get(str(before_id))
                        if isinstance(room_info, dict) and int(room_info.get("owner_id") or 0) == member.id:
                            try:
                                await old_vc.send(
                                    content=(
                                        f"👑 방장({member.mention})님이 퇴장했습니다! "
                                        "방에 남아 계신 멤버 중 누구든 아래 **[👑 방장 인계받기]** 버튼을 누르면 새 방장이 될 수 있습니다."
                                    ),
                                    view=TempVoiceControlView(old_vc.id),
                                )
                            except Exception:
                                pass
                else:
                    def _pop_missing():
                        with core._DATA_LOCK:
                            d = core.load_data()
                            community_core.remove_temp_voice_room(d, guild_id, before_id)
                            core.save_data(d)

                    await asyncio.to_thread(_pop_missing)

            # 2) 생성기 음성채널(Join-to-Create) 입장 시 새 임시 음성방 생성 & 이동
            if is_joining_gen and isinstance(after.channel, discord.VoiceChannel):
                now_m = time.monotonic()
                cd_key = (guild_id, member.id)
                if now_m - self._temp_voice_user_cd.get(cd_key, 0.0) < 4.0:
                    return
                self._temp_voice_user_cd[cd_key] = now_m

                if not guild.me or not guild.me.guild_permissions.manage_channels:
                    return

                def _read_fresh_cfg():
                    with core._DATA_LOCK:
                        d = core.load_data()
                        return community_core.get_temp_voice_config(d, guild_id)

                fresh_cfg = await asyncio.to_thread(_read_fresh_cfg)
                if not fresh_cfg.get("enabled") or not community_core.is_temp_voice_generator_channel(fresh_cfg, after_id):
                    return

                # 관리자가 지정한 category_id를 최우선으로 사용하고, 없을 때만 생성기 채널의 카테고리로 폴백
                target_category = None
                if fresh_cfg.get("category_id"):
                    cat_obj = guild.get_channel(int(fresh_cfg["category_id"]))
                    if isinstance(cat_obj, discord.CategoryChannel):
                        target_category = cat_obj
                if target_category is None:
                    target_category = after.channel.category

                room_idx = len(fresh_cfg.get("active_rooms") or {}) + 1
                room_name = community_core.format_temp_voice_room_name(
                    fresh_cfg.get("name_template", community_core.DEFAULT_TEMP_VOICE_TEMPLATE),
                    member.display_name,
                    room_idx,
                )
                def_limit = max(0, min(99, int(fresh_cfg.get("default_limit", 0) or 0)))

                overwrites = {}
                if target_category:
                    overwrites = dict(target_category.overwrites)
                overwrites[guild.me] = discord.PermissionOverwrite(
                    view_channel=True,
                    connect=True,
                    manage_channels=True,
                    move_members=True,
                    send_messages=True,
                )
                overwrites[member] = discord.PermissionOverwrite(
                    view_channel=True,
                    connect=True,
                    manage_channels=True,
                    move_members=True,
                )

                try:
                    new_vc = await guild.create_voice_channel(
                        name=room_name,
                        category=target_category,
                        user_limit=def_limit,
                        overwrites=overwrites,
                        reason=f"임시 음성방 자동 생성 (방장: {member})",
                    )
                except Exception:
                    return

                def _register_new_room():
                    with core._DATA_LOCK:
                        d = core.load_data()
                        entry = community_core.register_temp_voice_room(
                            d,
                            guild_id,
                            new_vc.id,
                            member.id,
                            member.display_name,
                            room_name=room_name,
                            user_limit=def_limit,
                        )
                        core.save_data(d)
                        return entry

                room_entry = await asyncio.to_thread(_register_new_room)

                # 유저를 새로 생성된 음성방으로 즉시 이동 (이미 나갔다면 방 삭제)
                try:
                    if member.voice and member.voice.channel:
                        await member.move_to(new_vc, reason="임시 음성방 자동 이동")
                    else:
                        raise RuntimeError("User left voice before move")
                except Exception:
                    def _rollback_room():
                        with core._DATA_LOCK:
                            d = core.load_data()
                            community_core.remove_temp_voice_room(d, guild_id, new_vc.id)
                            core.save_data(d)

                    await asyncio.to_thread(_rollback_room)
                    try:
                        await new_vc.delete(reason="생성 직후 유저 이탈로 임시 음성방 회수")
                    except Exception:
                        pass
                    return

                # 음성 채널 내 텍스트 채팅에 방장 리모컨 카드 전송
                try:
                    panel_msg = await new_vc.send(
                        content=f"👑 {member.mention}님의 전용 임시 음성방이 개설되었습니다! 아래 리모컨으로 방을 자유롭게 설정하세요.",
                        embed=_build_temp_voice_panel_embed(new_vc, room_entry),
                        view=TempVoiceControlView(new_vc.id),
                    )
                    if panel_msg:
                        def _save_panel_msg_id():
                            with core._DATA_LOCK:
                                d = core.load_data()
                                community_core.update_temp_voice_room(d, guild_id, new_vc.id, panel_message_id=panel_msg.id)
                                core.save_data(d)

                        await asyncio.to_thread(_save_panel_msg_id)
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        """디스코드에서 채널·카테고리가 직접 삭제되었을 때 연관된 유령 DB 설정을 자동 정리합니다."""
        guild = getattr(channel, "guild", None)
        if not guild:
            return
        guild_id = guild.id
        ch_id = channel.id
        ch_id_s = str(ch_id)

        prev_t = self._sticky_delay_tasks.pop(ch_id, None)
        if prev_t and not prev_t.done():
            prev_t.cancel()

        def _cleanup_deleted_channel():
            with core._DATA_LOCK:
                d = core.load_data()
                changed = False

                # 1) 임시 음성방 (활성 임시방 / 생성기 채널 / 지정 카테고리)
                tv_root = core.as_dict(d.get("temp_voice_configs"))
                tv_raw = tv_root.get(str(guild_id))
                if isinstance(tv_raw, dict):
                    tv_cfg = community_core.get_temp_voice_config(d, guild_id)
                    tv_mod = False
                    if ch_id_s in (tv_cfg.get("active_rooms") or {}):
                        community_core.remove_temp_voice_room(d, guild_id, ch_id)
                        tv_cfg = community_core.get_temp_voice_config(d, guild_id)
                        tv_mod = True
                    if community_core.is_temp_voice_generator_channel(tv_cfg, ch_id):
                        rem = community_core.remove_temp_voice_generator_channel(tv_cfg, ch_id)
                        if not rem:
                            tv_cfg["enabled"] = False
                        tv_mod = True
                    if int(tv_cfg.get("category_id") or 0) == ch_id:
                        tv_cfg["category_id"] = None
                        tv_mod = True
                    if tv_mod:
                        community_core.save_temp_voice_config(d, guild_id, tv_cfg)
                        changed = True

                # 2) 자동 고정 메시지(Sticky)
                if community_core.remove_sticky_config(d, guild_id, ch_id):
                    changed = True

                # 3) 실시간 카운트다운 타이머
                cd_root = core.as_dict(d.get("countdown_timers"))
                cd_g = cd_root.get(str(guild_id))
                if isinstance(cd_g, dict):
                    for t in cd_g.values():
                        if isinstance(t, dict) and int(t.get("channel_id") or 0) == ch_id and t.get("status") == "active":
                            t["status"] = "cancelled"
                            changed = True

                # 4) 진행 중인 릴레이 소설
                if community_core.get_active_relay_novel(d, guild_id, ch_id):
                    community_core.cancel_relay_novel(d, guild_id, ch_id)
                    changed = True

                # 5) 환영 / 작별 배너 설정 채널
                w_root = core.as_dict(d.get("welcome_configs"))
                w_raw = w_root.get(str(guild_id))
                if isinstance(w_raw, dict):
                    w_cfg = community_core.get_welcome_config(d, guild_id)
                    w_mod = False
                    if int(w_cfg.get("welcome_channel_id") or 0) == ch_id:
                        w_cfg["welcome_channel_id"] = None
                        w_cfg["welcome_enabled"] = False
                        w_mod = True
                    if int(w_cfg.get("goodbye_channel_id") or 0) == ch_id:
                        w_cfg["goodbye_channel_id"] = None
                        if not w_cfg.get("welcome_channel_id"):
                            w_cfg["goodbye_enabled"] = False
                        w_mod = True
                    if w_mod:
                        community_core.save_welcome_config(d, guild_id, w_cfg)
                        changed = True

                # 6) 링크 미리보기 제외 채널
                lp_root = core.as_dict(d.get("link_preview_configs"))
                lp_raw = lp_root.get(str(guild_id))
                if isinstance(lp_raw, dict):
                    lp_cfg = community_core.get_link_preview_config(d, guild_id)
                    if ch_id in (lp_cfg.get("ignored_channels") or []):
                        lp_cfg["ignored_channels"] = [x for x in lp_cfg["ignored_channels"] if x != ch_id]
                        community_core.save_link_preview_config(d, guild_id, lp_cfg)
                        changed = True

                # 7) 레이드 비상 방어 알림 채널
                rd_root = core.as_dict(d.get("raid_defense_configs"))
                rd_raw = rd_root.get(str(guild_id))
                if isinstance(rd_raw, dict):
                    rd_cfg = community_core.get_raid_defense_config(d, guild_id)
                    if int(rd_cfg.get("alert_channel_id") or 0) == ch_id:
                        rd_cfg["alert_channel_id"] = None
                        community_core.save_raid_defense_config(d, guild_id, rd_cfg)
                        changed = True

                if changed:
                    core.save_data(d)

        await asyncio.to_thread(_cleanup_deleted_channel)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        """디스코드에서 역할이 삭제되었을 때 환영 자동 역할 목록 및 비상방어 격리 역할을 자동 정리합니다."""
        guild = getattr(role, "guild", None)
        if not guild:
            return
        guild_id = guild.id
        role_id = role.id

        def _cleanup_deleted_role():
            with core._DATA_LOCK:
                d = core.load_data()
                changed = False

                # 1) 환영 자동 부여 역할 (다중 역할 목록 포함)
                w_root = core.as_dict(d.get("welcome_configs"))
                if isinstance(w_root.get(str(guild_id)), dict):
                    w_cfg = community_core.get_welcome_config(d, guild_id)
                    r_ids = list(w_cfg.get("auto_role_ids") or [])
                    if role_id in r_ids or int(w_cfg.get("auto_role_id") or 0) == role_id:
                        community_core.remove_welcome_auto_role(w_cfg, role_id)
                        community_core.save_welcome_config(d, guild_id, w_cfg)
                        changed = True

                # 2) 레이드 비상 방어 격리 역할
                rd_root = core.as_dict(d.get("raid_defense_configs"))
                if isinstance(rd_root.get(str(guild_id)), dict):
                    rd_cfg = community_core.get_raid_defense_config(d, guild_id)
                    if int(rd_cfg.get("quarantine_role_id") or 0) == role_id:
                        rd_cfg["quarantine_role_id"] = None
                        community_core.save_raid_defense_config(d, guild_id, rd_cfg)
                        changed = True

                if changed:
                    core.save_data(d)

        await asyncio.to_thread(_cleanup_deleted_role)


async def setup(bot: commands.Bot):
    await bot.add_cog(CommunityCog(bot))

