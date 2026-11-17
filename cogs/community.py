"""
cogs/community.py - 관리자/커뮤니티 편의 & 보안 기능 4종
1. #8  📌 자동 고정 메시지 (/고정메시지 - 관리자 전용)
2. #12 🔗 SNS 링크 미리보기 보정 & 추적 파라미터 제거 (/링크미리보기)
3. #42 🚨 동시 입장(Raid) · 봇 테러 비상 방어 모드 (/비상모드 - 관리자 전용)
4. #48 ✍️ 한 줄씩 이어 쓰는 릴레이 소설 (/릴레이소설)
"""

from __future__ import annotations

import asyncio
import datetime
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import community_core
import core


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
    perms = getattr(member, "guild_permissions", None)
    if not perms:
        return False
    if perms.administrator:
        return True
    if need_admin:
        return False
    return bool(getattr(perms, perm_attr, False))


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
    embed = discord.Embed(
        title=cfg.get("title") or "📌 채널 고정 안내",
        description=cfg.get("content") or "",
        color=discord.Color(color_val),
    )
    interval = int(cfg.get("interval", 1) or 1)
    footer_note = "📌 자동 고정 메시지" if interval == 1 else f"📌 자동 고정 메시지 · {interval}개 대화마다 하단 갱신"
    embed.set_footer(text=footer_note)
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
            "───────────────────────────────────────\n"
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
            "───────────────────────────────────────\n"
            f"{story_body}"
        ),
        color=discord.Color.gold(),
        timestamp=datetime.datetime.now(core.KST),
    )
    embed.set_footer(text="/릴레이소설 목록 에서 언제든 다시 읽어볼 수 있습니다.")
    return embed


# ==========================================
# 1. 📌 고정 메시지 설정 모달 (#8)
# ==========================================
class StickyConfigModal(core.SafeModal, title="📌 자동 고정 메시지 설정"):
    title_input = discord.ui.TextInput(
        label="고정 메시지 제목",
        placeholder="예: 📌 거래 채널 이용 규칙 안내",
        required=True,
        max_length=120,
    )
    content_input = discord.ui.TextInput(
        label="고정 메시지 본문 내용",
        placeholder="새 채팅이 올라와도 채널 맨 아래에 항상 고정될 안내 문구를 입력하세요.",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1800,
    )

    def __init__(
        self,
        channel: discord.abc.GuildChannel,
        *,
        interval: int = 1,
        color: str = "gold",
        existing: Optional[dict] = None,
    ):
        super().__init__()
        self.channel = channel
        self.interval = interval
        self.color = color
        if existing:
            self.title_input.default = existing.get("title", "")[:120]
            self.content_input.default = existing.get("content", "")[:1800]

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not _is_guild_admin(interaction.user, perm_attr="manage_messages"):
            await core.safe_send_response(interaction, "❌ 메시지 관리 또는 관리자 권한이 필요합니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True, thinking=True)
        guild_id = interaction.guild.id
        channel_id = self.channel.id
        title_val = self.title_input.value
        content_val = self.content_input.value

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
            "title": (title_val or "📌 채널 안내").strip()[:120],
            "content": (content_val or "").strip()[:1800],
            "color": self.color if self.color in community_core.STICKY_COLOR_MAP else "gold",
            "interval": max(1, min(30, int(self.interval or 1))),
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
                    interval=self.interval,
                    updated_by=interaction.user.id,
                    last_message_id=posted.id,
                )
                cfg["last_posted_ts"] = time.time()
                core.save_data(data)
                return cfg

        cfg = await asyncio.to_thread(_save_sticky)
        await interaction.followup.send(
            f"✅ {self.channel.mention} 채널에 **자동 고정 메시지**가 등록되어 하단에 게시되었습니다!\n"
            f"• **갱신 간격:** `{cfg['interval']}개` 메시지마다 자동 갱신 · **색상:** `{community_core.STICKY_COLOR_LABELS.get(cfg['color'], cfg['color'])}`",
            ephemeral=True,
        )


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
        custom_id="link_preview:delete",
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
        return True

    def build_embed(self) -> discord.Embed:
        c = self.cfg
        gname = getattr(self.guild, "name", None) or "서버"
        ignored_str = ", ".join(f"<#{cid}>" for cid in c.get("ignored_channels", [])) or "없음"
        embed = discord.Embed(
            title=f"🔗 [{gname}] SNS 링크 미리보기 & 추적 제거 설정",
            description=(
                "• **전체 기능:** " + ("🟢 활성화됨" if c["enabled"] else "🔴 비활성화됨") + "\n"
                "• **SNS 미리보기 보정:** " + ("🟢 켜짐" if c["sns_preview"] else "⚪ 꺼짐")
                + " *(X/Twitter, Instagram, TikTok, Threads, Reddit, Pixiv, Bluesky)*\n"
                "• **추적 파라미터 제거:** " + ("🟢 켜짐" if c["strip_tracking"] else "⚪ 꺼짐")
                + " *(`?si=`, `?igsh=`, `?utm_*`, `?fbclid=`, `?s=&t=` 등)*\n"
                "• **원본 깨진 임베드 숨김:** " + ("🟢 켜짐" if c["suppress_original"] else "⚪ 꺼짐") + "\n"
                f"• **제외된 채널:** {ignored_str}\n\n"
                "💡 `<링크>`, `||스포일러||`, `` `코드` `` 안의 링크는 자동으로 건너뜁니다."
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

    @discord.ui.button(label="원본 임베드 숨김", style=discord.ButtonStyle.secondary, emoji="🙈", row=1)
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
        custom_id="raid_defense:unlock",
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
        custom_id="raid_defense:logs",
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
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 설정할 수 있습니다.", ephemeral=True)
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
        await core.safe_defer(interaction)
        role = self.values[0]
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
        return True

    def build_embed(self) -> discord.Embed:
        c = self.cfg
        gname = getattr(self.guild, "name", None) or "서버"
        alert_str = f"<#{c['alert_channel_id']}>" if c.get("alert_channel_id") else "자동 (서버로그/시스템 채널)"
        qrole_str = f"<@&{c['quarantine_role_id']}>" if c.get("quarantine_role_id") else "미지정 *(미지정 시 60분 타임아웃으로 폴백)*"
        age_str = f"`{c['min_account_age_days']}일 미만`" if c.get("min_account_age_days", 0) > 0 else "사용 안 함 (`0일`)"
        lock_str = "🚨 **비상 잠금 발동 중!**" if c.get("lockdown_active") else "🟢 평상시 (정상)"
        embed = discord.Embed(
            title=f"🛡️ [{gname}] 동시 입장(Raid) · 테러 비상 방어 설정",
            description=(
                f"• **현재 상태:** {lock_str}\n"
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
        embed.set_footer(text="/비상모드 발동 · /비상모드 해제로 수동 제어할 수도 있습니다.")
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
        custom_id="relay_novel:write",
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
        custom_id="relay_novel:preview",
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
        custom_id="relay_novel:finish",
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
        super().__init__(timeout=180)
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
            description="아직 완결된 릴레이 소설이 없습니다. `/릴레이소설 시작`으로 첫 작품을 만들어 보세요!",
            color=discord.Color.gold(),
        )


# ==========================================
# 메인 CommunityCog
# ==========================================
class CommunityCog(commands.Cog):
    """고정메시지(#8) · SNS 링크 보정(#12) · 레이드 비상방어(#42) · 릴레이 소설(#48)"""

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
        self._raid_locks: dict[int, asyncio.Lock] = {}
        self._last_sticky_post_ts: dict[int, float] = {}
        self._last_raid_alert_ts: dict[int, float] = {}

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

    # ------------------------------------------
    # #8 관리자 자동 고정 메시지 커맨드
    # ------------------------------------------
    @sticky_group.command(name="설정", description="[관리자] 지정 채널 하단에 항상 유지될 고정 메시지를 설정합니다.")
    @app_commands.describe(
        채널="고정 메시지를 유지할 텍스트 채널 (미입력 시 현재 채널)",
        간격="몇 개의 대화마다 하단으로 재전송할지 설정 (1~30, 기본 1)",
        색상="고정 메시지 임베드 색상",
        제목="(선택) 제목을 바로 입력하려면 작성 (미입력 시 입력 팝업 열림)",
        내용="(선택) 본문을 바로 입력하려면 작성 (미입력 시 입력 팝업 열림)",
    )
    @app_commands.choices(색상=[
        app_commands.Choice(name=label, value=key)
        for key, label in community_core.STICKY_COLOR_LABELS.items()
    ])
    async def sticky_set_cmd(
        self,
        interaction: discord.Interaction,
        채널: Optional[discord.TextChannel] = None,
        간격: Optional[app_commands.Range[int, 1, 30]] = 1,
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

        if not (제목 and 내용):
            data = await asyncio.to_thread(core.load_data)
            existing = community_core.get_sticky_config(data, interaction.guild.id, target_ch.id)
            modal = StickyConfigModal(target_ch, interval=interval_val, color=color_val, existing=existing)
            if 제목:
                modal.title_input.default = 제목[:120]
            if 내용:
                modal.content_input.default = 내용[:1800]
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
            "title": (제목 or "📌 채널 안내").strip()[:120],
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
                    제목,
                    내용,
                    color=color_val,
                    interval=interval_val,
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
        data = await asyncio.to_thread(core.load_data)
        g_stickies = community_core.get_guild_stickies(data, interaction.guild.id)
        if not g_stickies:
            await interaction.followup.send("📭 이 서버에 등록된 자동 고정 메시지가 없습니다. `/고정메시지 설정`으로 추가해 보세요!", ephemeral=True)
            return
        lines = []
        for ch_id_s, cfg in g_stickies.items():
            if not isinstance(cfg, dict):
                continue
            status = "🟢" if cfg.get("enabled", True) else "🔴"
            lines.append(
                f"{status} <#{ch_id_s}> — **{cfg.get('title', '안내')}** (`{cfg.get('interval', 1)}메시지마다`)\n"
                f"└ *{str(cfg.get('content', ''))[:60]}*"
            )
        embed = discord.Embed(
            title=f"📌 [{interaction.guild.name}] 자동 고정 메시지 목록",
            description="\n\n".join(lines[:20]),
            color=discord.Color.gold(),
        )
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
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)

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
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)

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
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

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

        sent = await interaction.followup.send(embed=_build_relay_active_embed(story), view=RelayNovelView())
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
                "ℹ️ 현재 이 채널에서 진행 중인 릴레이 소설이 없습니다. `/릴레이소설 시작`으로 새 이야기를 열어보세요!",
                ephemeral=True,
            )
            return
        sent = await interaction.followup.send(embed=_build_relay_active_embed(story), view=RelayNovelView())
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
            await interaction.followup.send("📭 아직 완결된 릴레이 소설이 없습니다. `/릴레이소설 시작`으로 첫 작품을 만들어 보세요!", ephemeral=True)
            return
        view = RelayArchiveView(completed)
        await interaction.followup.send(embed=_build_relay_completed_embed(completed[0]), view=view)

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
        await interaction.followup.send(f"🛑 진행 중이던 릴레이 소설 **『{title_s}』**이(가) 중단되었습니다.", ephemeral=True)

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

    # ------------------------------------------
    # 리스너 1: on_message (#8 고정메시지 + #12 링크보정)
    # ------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or message.webhook_id:
            return

        cached = core.get_cached_data()

        # 1) #12 SNS 링크 미리보기 개선 & 추적 파라미터 제거
        try:
            link_cfg = community_core.get_link_preview_config(cached, message.guild.id)
            if link_cfg.get("enabled", True) and message.channel.id not in link_cfg.get("ignored_channels", []):
                items = community_core.extract_and_transform_urls(message.content, link_cfg)
                if items:
                    if link_cfg.get("suppress_original", True):
                        me = message.guild.me
                        if me and message.channel.permissions_for(me).manage_messages:
                            try:
                                await message.edit(suppress=True)
                            except Exception:
                                pass

                    sns_lines = []
                    track_lines = []
                    for it in items:
                        if it["kind"] == "sns":
                            sns_lines.append(f"🔗 **{it['service']} 미리보기:** {it['cleaned']}")
                        else:
                            params_str = ", ".join(f"`{p}`" for p in it.get("stripped_params", [])[:4])
                            tag_note = f" *(추적 태그 {params_str} 제거)*" if params_str else ""
                            track_lines.append(f"🧹 **클린 링크:** {it['cleaned']}{tag_note}")

                    body = "\n".join(sns_lines + track_lines)
                    try:
                        await message.reply(body, view=LinkCleanupView(), mention_author=False)
                    except Exception:
                        pass
        except Exception:
            pass

        # 2) #8 자동 고정 메시지 (Sticky Message)
        try:
            sticky_cfg = community_core.get_sticky_config(cached, message.guild.id, message.channel.id)
            if sticky_cfg and sticky_cfg.get("enabled", True):
                guild_id = message.guild.id
                channel_id = message.channel.id
                msg_id = message.id
                lock = self._get_sticky_lock(channel_id)
                async with lock:
                    def _tick_or_prepare():
                        with core._DATA_LOCK:
                            data = core.load_data()
                            cfg = community_core.get_sticky_config(data, guild_id, channel_id)
                            if not cfg or not cfg.get("enabled", True):
                                return "skip", None, None
                            if cfg.get("last_message_id") and int(cfg["last_message_id"]) == msg_id:
                                return "skip", None, None

                            cfg["msg_count"] = int(cfg.get("msg_count", 0) or 0) + 1
                            interval = max(1, int(cfg.get("interval", 1) or 1))
                            cd = max(2, int(cfg.get("cooldown_sec", 3) or 3))
                            now_ts = time.time()
                            last_ts = float(cfg.get("last_posted_ts", 0.0) or 0.0)

                            if cfg["msg_count"] < interval or (now_ts - last_ts) < cd:
                                core.save_data(data)
                                return "skip", None, None

                            return "post", dict(cfg), cfg.get("last_message_id")

                    action_mode, cfg_snapshot, old_msg_id = await asyncio.to_thread(_tick_or_prepare)
                    if action_mode != "post" or not cfg_snapshot:
                        return

                    if old_msg_id:
                        try:
                            old_msg = await message.channel.fetch_message(int(old_msg_id))
                            await old_msg.delete()
                        except Exception:
                            pass

                    try:
                        posted = await message.channel.send(embed=_build_sticky_embed(cfg_snapshot))
                        self._last_sticky_post_ts[channel_id] = time.monotonic()

                        def _commit_sticky_post():
                            with core._DATA_LOCK:
                                data = core.load_data()
                                cfg = community_core.get_sticky_config(data, guild_id, channel_id)
                                if not cfg or not cfg.get("enabled", True):
                                    return
                                cfg["last_message_id"] = posted.id
                                cfg["msg_count"] = 0
                                cfg["last_posted_ts"] = time.time()
                                core.save_data(data)

                        await asyncio.to_thread(_commit_sticky_post)
                    except Exception:
                        pass
        except Exception:
            pass

    # ------------------------------------------
    # 리스너 2: on_member_join (#42 동시 입장 Raid 방어)
    # ------------------------------------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.guild or member.bot:
            return

        guild_id = member.guild.id
        cached = core.get_cached_data()
        quick_cfg = community_core.get_raid_defense_config(cached, guild_id)
        if not quick_cfg["lockdown_active"] and not quick_cfg["enabled"] and quick_cfg["min_account_age_days"] <= 0:
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


async def setup(bot: commands.Bot):
    await bot.add_cog(CommunityCog(bot))
