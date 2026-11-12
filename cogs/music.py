import os
import sys
import re
import copy
import time
import random
import asyncio
import queue
import threading
import datetime
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
import core

# PCMVolumeTransformer가 하위 오디오 소스의 _current_error를 투명하게 전달하도록 확장
if not hasattr(discord.PCMVolumeTransformer, "_current_error"):
    discord.PCMVolumeTransformer._current_error = property(lambda self: getattr(self.original, "_current_error", None))

# 디스코드 음성 전송용 libopus 라이브러리 초기 로드 보장
try:
    core.ensure_opus_loaded()
except Exception:
    pass


def _parse_platform_input(raw_val: str, default_plat: str = "YouTube") -> str:
    """한글/영문 플랫폼 입력값을 표준 플랫폼 키('YouTube' | 'Spotify' | 'SoundCloud')로 정규화"""
    v = (raw_val or "").strip().lower()
    if not v:
        return default_plat if default_plat in core.PLAYLIST_PLATFORMS else "YouTube"
    if any(k in v for k in ("스튜디오", "스포", "spotify", "sp", "🟢")):
        return "Spotify"
    if any(k in v for k in ("사운드", "사클", "soundcloud", "sc", "☁")):
        return "SoundCloud"
    if any(k in v for k in ("유튜브", "유튭", "youtube", "yt", "📺")):
        return "YouTube"
    return default_plat if default_plat in core.PLAYLIST_PLATFORMS else "YouTube"


def _get_track_url_for_platform(trk: dict, plat: str) -> str:
    """선택한 플랫폼(YouTube / Spotify / SoundCloud)에 맞는 곡 바로가기 링크 반환"""
    norm = core.normalize_playlist_track(trk)
    if plat == "Spotify":
        return norm["sp_url"]
    if plat == "SoundCloud":
        return norm["sc_url"]
    if plat == "YouTube":
        return norm["yt_url"]
    return norm["url"]


# ==========================================
# 음악 추천 & 보관함 & 맞춤 타이머 모달/뷰 클래스
# ==========================================
class MusicRecommendView(core.SafeView):
    def __init__(self, track_info, bot_instance, prefs, is_morning=False):
        super().__init__(timeout=3600)
        self.bot_instance = bot_instance
        self.prefs = prefs
        self.is_morning = is_morning
        self.track_info = dict(track_info)

        self.add_item(discord.ui.Button(
            label=f"{track_info['platform']}에서 바로 듣기",
            url=track_info["url"],
            style=discord.ButtonStyle.link
        ))

    @discord.ui.button(label="🔄 다른 곡 추천받기", style=discord.ButtonStyle.secondary)
    async def shuffle_music(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        latest_prefs = (await asyncio.to_thread(core.load_data)).get("music_prefs", self.prefs)
        track_info, error = await core.get_recommended_music(latest_prefs)
        if error or not track_info:
            await interaction.followup.send(f"❌ **다른 곡 추천 실패:** {error}", ephemeral=True)
            return
        embed, view = self.bot_instance.build_music_embed_and_view(track_info, latest_prefs, is_morning=self.is_morning)
        await interaction.edit_original_response(embed=embed, view=view)

    @discord.ui.button(label="❤️ 보관함에 담기", style=discord.ButtonStyle.danger)
    async def like_music(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(interaction.user.id)

        # 프로필 무결성 보장 (attendance, crystals 등이 초기화되지 않도록 보호)
        profile = core.ensure_user_profile(data, u_key, interaction.user.display_name)
        liked_list = profile.setdefault("liked_music", [])

        found_idx = next((i for i, t in enumerate(liked_list) if t.get("url") == self.track_info.get("url")), None)
        if found_idx is not None:
            liked_list.pop(found_idx)
            await asyncio.to_thread(core.save_data, data)
            await interaction.followup.send(
                f"💔 **{self.track_info['title']}** 곡을 보관함에서 삭제했습니다.",
                ephemeral=True
            )
            return

        saved_item = dict(self.track_info)
        saved_item["added_at"] = core.get_now_datetime_str()
        saved_item["added_by"] = interaction.user.display_name
        liked_list.append(saved_item)
        await asyncio.to_thread(core.save_data, data)

        await interaction.followup.send(
            f"❤️ **{self.track_info['title']}** 곡이 보관함에 저장되었습니다!\n*(💡 다시 버튼을 누르면 보관함에서 언제든 삭제할 수 있습니다)*",
            ephemeral=True
        )

    @discord.ui.button(label="💿 내 플리에 추가", style=discord.ButtonStyle.success)
    async def add_to_playlist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(interaction.user.id)
        profile = core.ensure_user_profile(data, u_key, interaction.user.display_name)
        pls = core.ensure_user_playlists(profile, interaction.user.display_name)
        target_pl = pls[0]

        plat = _parse_platform_input(self.track_info.get("platform", ""), target_pl.get("platform", "Spotify"))
        norm_trk = core.normalize_playlist_track({
            "title": self.track_info.get("title", "제목 없음"),
            "artist": self.track_info.get("artist", "아티스트 미지정"),
            "platform": plat,
            "url": self.track_info.get("url", ""),
            "image": self.track_info.get("image"),
            "memo": "추천 음악에서 담은 곡 ✨",
        })
        if any(t.get("title") == norm_trk["title"] and t.get("artist") == norm_trk["artist"] for t in target_pl["tracks"]):
            await interaction.followup.send(
                f"ℹ️ **{norm_trk['title']}** 곡은 이미 `{target_pl['emoji']} {target_pl['name']}` 플레이리스트에 들어있습니다! (`/플레이리스트`에서 확인)",
                ephemeral=True
            )
            return

        target_pl["tracks"].append(norm_trk)
        target_pl["updated_at"] = core.get_today_str()
        await asyncio.to_thread(core.save_data, data)
        await interaction.followup.send(
            f"💿 **{norm_trk['title']}** — `{norm_trk['artist']}` 곡을 **`{target_pl['emoji']} {target_pl['name']}`** 플레이리스트에 추가했습니다!\n"
            f"*(💡 `/플레이리스트` 명령어로 편집하거나 채널에 공유할 수 있습니다)*",
            ephemeral=True
        )

    @discord.ui.button(label="📚 내 음악보관함 열기", style=discord.ButtonStyle.primary)
    async def open_my_library(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(interaction.user.id)
        liked_list = data.get("user_profiles", {}).get(u_key, {}).get("liked_music", [])
        view = MusicLibraryPaginationView(f"❤️ {interaction.user.display_name}님의 나만의 음악 보관함", liked_list, items_per_page=5)
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)


class MusicLibraryPaginationView(core.SafeView):
    """음악 보관함 페이징 + 보관함 전용 랜덤 셔플 버튼 (개인 및 파트너 공유 보관함 겸용)"""
    def __init__(self, title_str: str, music_list: list, items_per_page=5):
        super().__init__(timeout=600)
        self.title_str = title_str
        self.music_list = sorted(music_list, key=lambda x: x.get("added_at", ""), reverse=True)
        self.items_per_page = items_per_page
        self.current_page = 0
        self.update_buttons()

    @property
    def max_page(self):
        if not self.music_list:
            return 0
        return (len(self.music_list) - 1) // self.items_per_page

    def update_buttons(self):
        is_first = (self.current_page <= 0)
        is_last = (self.current_page >= self.max_page)
        self.back_5.disabled = is_first
        self.prev_page.disabled = is_first
        self.next_page.disabled = is_last
        self.forward_5.disabled = is_last
        self.shuffle_my_library.disabled = (len(self.music_list) == 0)

    def build_embed(self):
        self.update_buttons()
        start_idx = self.current_page * self.items_per_page
        page_items = self.music_list[start_idx:start_idx + self.items_per_page]

        embed = discord.Embed(
            title=self.title_str,
            color=discord.Color.from_rgb(255, 105, 180),
            timestamp=datetime.datetime.now(core.KST)
        )
        if not page_items:
            embed.description = "📭 보관함이 비어 있습니다.\n추천 음악의 **`❤️ 보관함에 담기`** 버튼을 눌러 좋아하는 곡을 저장해 보세요!"
        else:
            lines = []
            for idx, m in enumerate(page_items, start=start_idx + 1):
                by_str = f" · 💖 {m['added_by']}" if m.get("added_by") else ""
                lines.append(
                    f"**{idx}. [{m.get('title', '제목 없음')}]({m.get('url', 'https://open.spotify.com')})**\n"
                    f"   └ 🎤 `{m.get('artist', '-')}` · 🌐 `{m.get('platform', '-')}` · 🕒 `{m.get('added_at', '-')[:10]}`{by_str}"
                )
            embed.description = "\n\n".join(lines)
            embed.set_footer(text=f"페이지 {self.current_page + 1} / {self.max_page + 1} • 총 {len(self.music_list)}곡 보관 중 (🔀 버튼으로 보관함 내 랜덤 선곡)")
        return embed

    @discord.ui.button(label="⏪ -5", style=discord.ButtonStyle.secondary, row=0)
    async def back_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 5)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.primary, row=0)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = min(self.max_page, self.current_page + 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="+5 ⏩", style=discord.ButtonStyle.secondary, row=0)
    async def forward_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = min(self.max_page, self.current_page + 5)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔀 보관함 셔플 뽑기", style=discord.ButtonStyle.success, row=0)
    async def shuffle_my_library(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.music_list:
            await core.safe_send_response(interaction, content="📭 보관함에 저장된 곡이 없습니다!", ephemeral=True)
            return

        chosen = random.choice(self.music_list)
        platform_name = chosen.get("platform", "Music")
        is_spotify = (platform_name == "Spotify")
        embed_color = discord.Color.from_rgb(29, 185, 84) if is_spotify else discord.Color.from_rgb(255, 85, 0)

        embed = discord.Embed(
            title=f"🔀 보관함 랜덤 셔플 곡 ({platform_name})",
            description=(
                f"### [{chosen.get('title', '제목 없음')}]({chosen.get('url', 'https://open.spotify.com')})\n"
                f"🎤 **아티스트:** `{chosen.get('artist', '알 수 없는 아티스트')}`"
            ),
            color=embed_color,
            url=chosen.get("url", "https://open.spotify.com"),
            timestamp=datetime.datetime.now(core.KST)
        )
        if chosen.get("image"):
            embed.set_thumbnail(url=chosen["image"])
        embed.set_footer(text=f"보관일: {chosen.get('added_at', '-')[:10]} • 보관함({len(self.music_list)}곡) 내 랜덤 추천")

        link_view = discord.ui.View(timeout=600)
        link_view.add_item(discord.ui.Button(
            label=f"{platform_name}에서 바로 듣기",
            url=chosen.get("url", "https://open.spotify.com"),
            style=discord.ButtonStyle.link
        ))
        await core.safe_send_response(interaction, embed=embed, view=link_view)


def _normalize_music_time_str(time_str: str):
    raw = (time_str or "").strip()
    m = re.match(r"^(\d{1,2}):(\d{1,2})$", raw)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mn <= 59:
            return f"{h:02d}:{mn:02d}"
    return None


class MusicScheduleAddModal(core.SafeModal, title="⏰ 새 맞춤 음악 추천 타이머 추가"):
    sched_time = discord.ui.TextInput(
        label="추천받을 시간 (24시간제 HH:MM 또는 H:MM)",
        placeholder="예: 08:30, 9:00, 15:00, 22:30",
        required=True,
        max_length=5
    )
    sched_name = discord.ui.TextInput(
        label="알림 타이머 이름",
        placeholder="예: 오후 3시 노동요, 밤 10시 수면 음악",
        default="맞춤 음악 추천",
        required=True,
        max_length=40
    )
    sched_genre = discord.ui.TextInput(
        label="테마/장르 키워드 (선택)",
        placeholder="예: lofi, pop, piano, chill (비워두면 시간대 감성 자동)",
        required=False,
        max_length=40
    )

    def __init__(self, hub_view, default_channel: discord.abc.GuildChannel):
        super().__init__()
        self.hub_view = hub_view
        self.default_channel = default_channel

    async def on_submit(self, interaction: discord.Interaction):
        clean_time = _normalize_music_time_str(self.sched_time.value)
        if not clean_time:
            await core.safe_send_response(
                interaction,
                "❌ 올바른 24시간제 시간 형식(예: `08:30`, `9:00`, `15:00`, `22:00`)으로 입력해 주세요. (00:00 ~ 23:59)",
                ephemeral=True
            )
            return

        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        schedules = data.setdefault("music_schedules", [])
        sched_id = f"sched_{int(time.time())}_{random.randint(100, 999)}"
        ch_id = self.default_channel.id if self.default_channel else (interaction.channel_id or 0)
        genre_val = self.sched_genre.value.strip() if self.sched_genre.value and self.sched_genre.value.strip() else None

        schedules.append({
            "id": sched_id,
            "time": clean_time,
            "channel_id": ch_id,
            "guild_id": interaction.guild_id or 0,
            "name": self.sched_name.value.strip() or "맞춤 음악 추천",
            "genre": genre_val,
            "last_sent": ""
        })
        await asyncio.to_thread(core.save_data, data)

        self.hub_view.set_schedules(schedules)
        await interaction.edit_original_response(embed=self.hub_view.build_embed(), view=self.hub_view)


class MusicScheduleHubView(core.SafeView):
    """슬래시 인자 없이도 버튼과 모달로 음악 알림 타이머를 추가·삭제할 수 있는 관리 뷰 (현재 서버 타이머만 표시)"""
    def __init__(self, schedules: list, default_channel: discord.abc.GuildChannel, guild: discord.Guild = None):
        super().__init__(timeout=600)
        self.default_channel = default_channel
        self.guild = guild or getattr(default_channel, "guild", None)
        self.schedules = []
        self.set_schedules(schedules)

    def set_schedules(self, all_schedules: list):
        """전체 타이머 중 현재 서버 소속 타이머만 필터링하여 보드에 반영"""
        self.schedules = [s for s in (all_schedules or []) if core.is_schedule_in_guild(s, self.guild)]
        self.update_delete_select()

    def update_delete_select(self):
        if not self.schedules:
            self.delete_select.options = [discord.SelectOption(label="등록된 알림 타이머가 없습니다", value="NONE")]
            self.delete_select.disabled = True
        else:
            opts = []
            for idx, s in enumerate(sorted(self.schedules, key=lambda x: x.get("time", ""))[:25], start=1):
                label = f"{idx}. [{s.get('time', '-')}] {s.get('name', '음악 알림')}"[:95]
                desc = f"장르: {s.get('genre') or '감성 자동'} | 클릭 시 즉시 삭제"[:95]
                opts.append(discord.SelectOption(label=label, value=str(s.get("id")), description=desc, emoji="🗑️"))
            self.delete_select.options = opts
            self.delete_select.disabled = False

    def build_embed(self):
        guild_name = self.guild.name if self.guild else "현재 서버"
        embed = discord.Embed(
            title=f"⏰ [{guild_name}] 맞춤형 자동 음악 추천 타이머 관리 보드",
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        if not self.schedules:
            embed.description = (
                "📭 현재 이 서버에 등록된 맞춤 음악 알림 타이머가 없습니다.\n"
                "아래 **`[➕ 새 알림 타이머 추가]`** 버튼을 눌러 원하는 시간과 테마를 등록해 보세요!"
            )
        else:
            lines = []
            for idx, s in enumerate(sorted(self.schedules, key=lambda x: x.get("time", "")), start=1):
                lines.append(
                    f"**{idx}. `{s.get('time')}` — {s.get('name', '음악 알림')}**\n"
                    f"   └ 📢 채널: <#{s.get('channel_id')}> · 🎸 테마: `{s.get('genre') or '요일·시간대 감성 자동'}`"
                )
            embed.description = "\n\n".join(lines)[:4000]
        embed.set_footer(text=f"총 {len(self.schedules)}개 타이머 등록됨 • 아래 버튼으로 추가하거나 드롭다운에서 바로 삭제할 수 있습니다.")
        return embed

    @discord.ui.button(label="➕ 새 알림 타이머 추가", style=discord.ButtonStyle.primary, row=0)
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MusicScheduleAddModal(self, self.default_channel or interaction.channel))

    @discord.ui.select(placeholder="🗑️ 삭제할 음악 알림 타이머를 선택하세요...", row=1, options=[discord.SelectOption(label="선택", value="NONE")])
    async def delete_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        if val == "NONE":
            await core.safe_defer(interaction)
            return
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        schedules = data.get("music_schedules", [])
        data["music_schedules"] = [
            s for s in schedules
            if not (str(s.get("id")) == val and core.is_schedule_in_guild(s, self.guild))
        ]
        await asyncio.to_thread(core.save_data, data)

        self.set_schedules(data["music_schedules"])
        await interaction.edit_original_response(embed=self.build_embed(), view=self)


# ==========================================
# 💿 커스텀 음악 플레이리스트 (유튜브 / 스포티파이 / 사운드클라우드 선택 & 공유 시스템)
# ==========================================
class PlaylistCreateEditModal(core.SafeModal):
    pl_name = discord.ui.TextInput(
        label="플레이리스트 이름",
        placeholder="예: 새벽 감성 코딩 플리, 프로세카 명곡 모음",
        required=True,
        max_length=50
    )
    pl_platform = discord.ui.TextInput(
        label="기본 스트리밍 플랫폼 (유튜브 / 스포티파이 / 사운드클라우드)",
        placeholder="유튜브, 스포티파이, 사운드클라우드 중 하나 입력",
        default="유튜브",
        required=True,
        max_length=25
    )
    pl_emoji = discord.ui.TextInput(
        label="대표 이모지 (선택)",
        placeholder="예: 🎧, 🌙, 🔥, 🌸, 🎸",
        default="🎧",
        required=False,
        max_length=8
    )
    pl_desc = discord.ui.TextInput(
        label="플레이리스트 한줄 소개 / 분위기",
        placeholder="예: 밤에 집중할 때 듣기 좋은 띵곡 리스트 ✨",
        required=False,
        max_length=120
    )

    def __init__(self, studio_view: "PlaylistStudioView", is_edit: bool = False, parent_message: Optional[discord.Message] = None):
        super().__init__(title="✏️ 플레이리스트 정보 수정" if is_edit else "📁 새 음악 플레이리스트 만들기")
        self.studio_view = studio_view
        self.is_edit = is_edit
        self.parent_message = parent_message or getattr(studio_view, "message", None)
        if is_edit:
            cur_pl = studio_view.get_current_playlist()
            self.pl_name.default = cur_pl.get("name", "나만의 대표 플레이리스트")
            plat_ko = {"YouTube": "유튜브", "Spotify": "스포티파이", "SoundCloud": "사운드클라우드"}.get(cur_pl.get("platform", "YouTube"), "유튜브")
            self.pl_platform.default = plat_ko
            self.pl_emoji.default = cur_pl.get("emoji", "🎧")
            self.pl_desc.default = cur_pl.get("desc", "")
        else:
            cur_plat = studio_view.get_current_playlist().get("platform", "YouTube")
            self.pl_platform.default = {"YouTube": "유튜브", "Spotify": "스포티파이", "SoundCloud": "사운드클라우드"}.get(cur_plat, "유튜브")

    async def on_submit(self, interaction: discord.Interaction):
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(self.studio_view.owner.id)
        profile = core.ensure_user_profile(data, u_key, self.studio_view.owner.display_name)
        pls = core.ensure_user_playlists(profile, self.studio_view.owner.display_name)

        clean_name = self.pl_name.value.strip() or "나만의 플레이리스트"
        clean_plat = _parse_platform_input(self.pl_platform.value, "YouTube")
        clean_emoji = (self.pl_emoji.value or "🎧").strip()[:8] or "🎧"
        clean_desc = (self.pl_desc.value or "나만의 감성 음악 플레이리스트 ✨").strip()
        today_s = core.get_today_str()

        if self.is_edit:
            target = next((p for p in pls if p["id"] == self.studio_view.current_pl_id), pls[0])
            target["name"] = clean_name
            target["platform"] = clean_plat
            target["emoji"] = clean_emoji
            target["desc"] = clean_desc
            target["updated_at"] = today_s
        else:
            if len(pls) >= 20:
                await interaction.followup.send("❌ 플레이리스트는 1인당 최대 **20개**까지만 생성할 수 있습니다.", ephemeral=True)
                return
            new_id = f"pl_{int(time.time())}_{random.randint(100, 999)}"
            new_pl = {
                "id": new_id,
                "name": clean_name,
                "desc": clean_desc,
                "emoji": clean_emoji,
                "platform": clean_plat,
                "tracks": [],
                "likes": [],
                "share_count": 0,
                "created_at": today_s,
                "updated_at": today_s,
            }
            pls.append(new_pl)
            self.studio_view.current_pl_id = new_id
            self.studio_view.current_page = 0

        await asyncio.to_thread(core.save_data, data)
        self.studio_view.data = data
        if self.parent_message:
            try:
                await self.parent_message.edit(embed=self.studio_view.build_embed(), view=self.studio_view)
            except Exception:
                pass
        else:
            try:
                await interaction.edit_original_response(embed=self.studio_view.build_embed(), view=self.studio_view)
            except Exception:
                pass

        action_msg = f"✏️ **`{clean_name}`** 플레이리스트 정보가 수정되었습니다!" if self.is_edit else f"📁 새 플레이리스트 **`{clean_emoji} {clean_name}`**이(가) 생성되었습니다!"
        await interaction.followup.send(action_msg, ephemeral=True)


class PlaylistAddTrackModal(core.SafeModal, title="➕ 플레이리스트에 새 곡 추가"):
    track_input = discord.ui.TextInput(
        label="곡 제목 또는 스트리밍 링크(URL)",
        placeholder="예: 군청찬가, YOASOBI - 아이돌, 또는 유튜브/스포티파이/사클 링크",
        required=True,
        max_length=200
    )
    artist_input = discord.ui.TextInput(
        label="아티스트 / 가수명 (선택 · 링크 입력 시 생략 가능)",
        placeholder="예: Eve, 25시 나이트 코드에서, IU",
        required=False,
        max_length=80
    )
    platform_input = discord.ui.TextInput(
        label="플랫폼 선택 (유튜브 / 스포티파이 / 사운드클라우드)",
        placeholder="유튜브, 스포티파이, 사운드클라우드 중 하나 입력",
        default="유튜브",
        required=True,
        max_length=25
    )
    memo_input = discord.ui.TextInput(
        label="곡 한줄 메모 / 추천 코멘트 (선택)",
        placeholder="예: 도입부 피아노가 너무 좋은 띵곡!",
        required=False,
        max_length=100
    )

    def __init__(self, studio_view: "PlaylistStudioView", parent_message: Optional[discord.Message] = None):
        super().__init__()
        self.studio_view = studio_view
        self.parent_message = parent_message or getattr(studio_view, "message", None)
        cur_plat = studio_view.get_current_playlist().get("platform", "YouTube")
        self.platform_input.default = {"YouTube": "유튜브", "Spotify": "스포티파이", "SoundCloud": "사운드클라우드"}.get(cur_plat, "유튜브")

    async def on_submit(self, interaction: discord.Interaction):
        await core.safe_defer(interaction, ephemeral=True)
        raw_val = (self.track_input.value or "").strip()
        if "http://" in raw_val or "https://" in raw_val:
            m_u = re.search(r"https?://[^\s<>\"']+", raw_val)
            if m_u:
                raw_val = m_u.group(0)

        # 만약 입력한 값이 단일 곡이 아닌 순수 플레이리스트 링크(YouTube, Spotify, SoundCloud)라면 자동으로 일괄 수록곡 추가
        # (단, watch?v=...&list=... 처럼 영상 ID가 포함된 링크는 사용자가 해당 영상 1곡만 추가하려는 것이므로 단일 곡으로 처리)
        is_pl, pl_plat = core.is_playlist_url(raw_val, allow_watch_with_list=False)
        if is_pl:
            meta, pl_tracks, err = await core.extract_playlist_from_url(raw_val, max_tracks=100)
            if err or not pl_tracks:
                await interaction.followup.send(f"❌ 플레이리스트 링크 추출 실패: {err or '수록곡 없음'}", ephemeral=True)
                return
            data = await asyncio.to_thread(core.load_data)
            u_key = str(self.studio_view.owner.id)
            profile = core.ensure_user_profile(data, u_key, self.studio_view.owner.display_name)
            try:
                target_pl, added_cnt, _ = core.import_playlist_into_profile_sync(
                    profile,
                    self.studio_view.owner.display_name,
                    meta,
                    pl_tracks,
                    target_pl_id=self.studio_view.current_pl_id
                )
            except Exception as e:
                await interaction.followup.send(f"❌ 플레이리스트 추가 실패: {e}", ephemeral=True)
                return

            await asyncio.to_thread(core.save_data, data)
            self.studio_view.data = data
            self.studio_view.current_page = max(0, (len(target_pl["tracks"]) - 1) // self.studio_view.items_per_page)
            if self.parent_message:
                try:
                    await self.parent_message.edit(embed=self.studio_view.build_embed(), view=self.studio_view)
                except Exception:
                    pass
            else:
                try:
                    await interaction.edit_original_response(embed=self.studio_view.build_embed(), view=self.studio_view)
                except Exception:
                    pass

            p_meta = core.PLAYLIST_PLATFORMS.get(target_pl.get("platform", "YouTube"), core.PLAYLIST_PLATFORMS["YouTube"])
            await interaction.followup.send(
                f"🔗 {p_meta['emoji']} 감지된 **{meta.get('platform')}** 플레이리스트 링크로부터 "
                f"**`{target_pl['emoji']} {target_pl['name']}`**에 수록곡 **총 {added_cnt}곡**을 일괄 추가했습니다!",
                ephemeral=True
            )
            return

        cur_pl = self.studio_view.get_current_playlist()
        chosen_plat = _parse_platform_input(self.platform_input.value, cur_pl.get("platform", "YouTube"))

        resolved_track = await core.resolve_playlist_track(
            raw_val,
            artist_hint=self.artist_input.value or "",
            preferred_platform=chosen_plat,
            memo=self.memo_input.value or ""
        )

        data = await asyncio.to_thread(core.load_data)
        u_key = str(self.studio_view.owner.id)
        profile = core.ensure_user_profile(data, u_key, self.studio_view.owner.display_name)
        pls = core.ensure_user_playlists(profile, self.studio_view.owner.display_name)
        target_pl = next((p for p in pls if p["id"] == self.studio_view.current_pl_id), pls[0])

        if len(target_pl["tracks"]) >= 100:
            await interaction.followup.send("❌ 하나의 플레이리스트에는 최대 **100곡**까지만 담을 수 있습니다.", ephemeral=True)
            return

        target_pl["tracks"].append(resolved_track)
        target_pl["updated_at"] = core.get_today_str()
        await asyncio.to_thread(core.save_data, data)

        self.studio_view.data = data
        self.studio_view.current_page = max(0, (len(target_pl["tracks"]) - 1) // self.studio_view.items_per_page)
        if self.parent_message:
            try:
                await self.parent_message.edit(embed=self.studio_view.build_embed(), view=self.studio_view)
            except Exception:
                pass
        else:
            try:
                await interaction.edit_original_response(embed=self.studio_view.build_embed(), view=self.studio_view)
            except Exception:
                pass

        p_meta = core.PLAYLIST_PLATFORMS.get(resolved_track["platform"], core.PLAYLIST_PLATFORMS["YouTube"])
        await interaction.followup.send(
            f"✅ {p_meta['emoji']} **[{resolved_track['title']}]({resolved_track['url']})** — `{resolved_track['artist']}` 곡이 "
            f"**`{target_pl['emoji']} {target_pl['name']}`** 플레이리스트에 추가되었습니다!",
            ephemeral=True
        )


class PlaylistImportUrlModal(core.SafeModal, title="🔗 플리 링크로 통째로 가져오기"):
    url_input = discord.ui.TextInput(
        label="유튜브 / 스포티파이 / 사운드클라우드 플리 링크",
        placeholder="https://www.youtube.com/playlist?list=... 또는 https://open.spotify.com/playlist/...",
        required=True,
        max_length=300
    )
    custom_name = discord.ui.TextInput(
        label="새 플레이리스트 이름 (선택 · 비워두면 링크 제목)",
        placeholder="예: 2026 팝 명곡 모음 (기존 플리에 추가 시 비워두기)",
        required=False,
        max_length=50
    )
    mode_input = discord.ui.TextInput(
        label="가져오기 방식 (1: 새 플리로 생성 / 2: 현재 플리에 추가)",
        placeholder="1 또는 2 입력 (기본: 1 - 새 플레이리스트로 자동 생성)",
        default="1",
        required=False,
        max_length=5
    )

    def __init__(self, studio_view: "PlaylistStudioView", parent_message: Optional[discord.Message] = None, default_mode: str = "1"):
        super().__init__()
        self.studio_view = studio_view
        self.parent_message = parent_message or getattr(studio_view, "message", None)
        self.mode_input.default = default_mode

    async def on_submit(self, interaction: discord.Interaction):
        await core.safe_defer(interaction, ephemeral=True)
        raw_url = (self.url_input.value or "").strip()
        m_u = re.search(r"https?://[^\s<>\"']+", raw_url)
        if m_u:
            raw_url = m_u.group(0)
        is_pl, plat = core.is_playlist_url(raw_url)
        if not is_pl:
            await interaction.followup.send(
                "❌ 입력하신 링크가 유효한 **YouTube, Spotify, SoundCloud** 플레이리스트나 앨범 링크가 아닙니다.\n"
                "• 유튜브: `https://www.youtube.com/playlist?list=...` 또는 `&list=...`\n"
                "• 스포티파이: `https://open.spotify.com/playlist/...` 또는 `.../album/...`\n"
                "• 사운드클라우드: `https://soundcloud.com/.../sets/...`",
                ephemeral=True
            )
            return

        meta, tracks, err = await core.extract_playlist_from_url(raw_url, max_tracks=100)
        if err or not tracks:
            await interaction.followup.send(f"❌ 플레이리스트에서 곡을 추출하지 못했습니다: {err or '수록곡 없음'}", ephemeral=True)
            return

        mode_choice = (self.mode_input.value or "1").strip()
        target_pl_id = self.studio_view.current_pl_id if mode_choice == "2" else None
        custom_n = (self.custom_name.value or "").strip() or None

        data = await asyncio.to_thread(core.load_data)
        u_key = str(self.studio_view.owner.id)
        profile = core.ensure_user_profile(data, u_key, self.studio_view.owner.display_name)

        try:
            target_pl, count, action_msg = core.import_playlist_into_profile_sync(
                profile,
                self.studio_view.owner.display_name,
                meta,
                tracks,
                target_pl_id=target_pl_id,
                custom_name=custom_n
            )
        except Exception as e:
            await interaction.followup.send(f"❌ 플레이리스트 가져오기 실패: {e}", ephemeral=True)
            return

        await asyncio.to_thread(core.save_data, data)
        self.studio_view.data = data
        self.studio_view.current_pl_id = target_pl["id"]
        self.studio_view.current_page = 0

        if self.parent_message:
            try:
                await self.parent_message.edit(embed=self.studio_view.build_embed(), view=self.studio_view)
            except Exception:
                pass
        else:
            try:
                await interaction.edit_original_response(embed=self.studio_view.build_embed(), view=self.studio_view)
            except Exception:
                pass

        p_meta = core.PLAYLIST_PLATFORMS.get(target_pl["platform"], core.PLAYLIST_PLATFORMS["YouTube"])
        await interaction.followup.send(
            f"🎉 {p_meta['emoji']} {action_msg}\n"
            f"• 플랫폼: **{meta.get('platform')}**\n"
            f"• 원본 총 곡 수: **`{meta.get('total_count', count)}곡`** 중 **`{count}곡`** 등록 완료!\n"
            f"하단의 **`[🔊 음성채널 순차 자동재생]`** 버튼을 눌러 바로 감상하실 수 있습니다 ✨",
            ephemeral=True
        )



class PulseBeepAudioSource(discord.AudioSource):
    """
    디스코드의 잡음 제거(Krisp / WebRTC Noise Suppression) 필터를 완벽히 통과하도록
    880Hz 고주파 비프음을 펄스 형태(0.36초 비프 + 0.14초 무음, 5초간 10회 반복)로
    메모리에서 즉시 생성하여 송출하는 무결점 자가진단 오디오 소스
    """
    def __init__(self, duration_sec: float = 5.0, freq: float = 880.0):
        import math, struct
        self.sample_rate = 48000
        self.channels = 2
        self.samples_per_frame = 960  # 20ms = 960 samples
        self.total_frames = int(duration_sec * 50)  # 5초 = 250 frames
        self.current_frame = 0

        frames_pcm = bytearray()
        phase = 0.0
        phase_increment = (2.0 * math.pi * freq) / self.sample_rate

        # 25프레임(0.5초) 주기: 18프레임(0.36초) 비프 발청 + 7프레임(0.14초) 무음
        # 지속음이 아닌 리드미컬한 펄스로 Discord Krisp 노이즈 게이트가 음소거하지 못하도록 방지
        for f in range(self.total_frames):
            is_active = (f % 25) < 18
            for _ in range(self.samples_per_frame):
                if is_active:
                    val = int(24000 * math.sin(phase))  # 충분히 크고 선명한 음량 (~75%)
                    sample = struct.pack("<h", val)
                    frames_pcm.extend(sample * 2)  # stereo
                    phase += phase_increment
                    if phase > 2.0 * math.pi:
                        phase -= 2.0 * math.pi
                else:
                    frames_pcm.extend(b"\x00\x00\x00\x00")  # stereo silence

        self.full_bytes = bytes(frames_pcm)
        self.frame_size = self.samples_per_frame * 4  # 3840 bytes

    def read(self) -> bytes:
        if self.current_frame >= self.total_frames:
            return b""
        start = self.current_frame * self.frame_size
        end = start + self.frame_size
        self.current_frame += 1
        return self.full_bytes[start:end]

    def is_opus(self) -> bool:
        return False


class SineWaveAudioSource(discord.AudioSource):
    """FFmpeg 없이 순수 파이썬으로 880Hz 테스트 사운드를 생성하는 무의존성 오디오 소스"""
    def __init__(self, duration_sec: float = 5.0, freq: float = 880.0):
        import math, struct
        self.sample_rate = 48000
        self.channels = 2
        self.samples_per_frame = 960  # 20ms = 960 samples
        self.total_frames = int(duration_sec * 50)
        self.current_frame = 0

        frames_pcm = bytearray()
        phase = 0.0
        phase_increment = (2.0 * math.pi * freq) / self.sample_rate
        for _ in range(self.total_frames):
            for _ in range(self.samples_per_frame):
                val = int(24000 * math.sin(phase))  # 충분히 선명하게 들리는 음량 (~75%)
                sample = struct.pack("<h", val)
                frames_pcm.extend(sample * 2)  # stereo
                phase += phase_increment
                if phase > 2.0 * math.pi:
                    phase -= 2.0 * math.pi

        self.full_bytes = bytes(frames_pcm)
        self.frame_size = self.samples_per_frame * 4  # 3840 bytes

    def read(self) -> bytes:
        if self.current_frame >= self.total_frames:
            return b""
        start = self.current_frame * self.frame_size
        end = start + self.frame_size
        self.current_frame += 1
        return self.full_bytes[start:end]

    def is_opus(self) -> bool:
        return False


def get_test_beep_source() -> tuple[discord.AudioSource, str]:
    """
    3중 안전망으로 구성된 최강의 오디오 테스트 소스 생성기:
    1순위: 사전에 고품질 48kHz Opus로 렌더링된 assets/audio/test_beep.opus (FFmpegOpusAudio)
           -> C 라이브러리 libopus.so 런타임 인코딩 오류 제로, WebRTC 완벽 호환
    2순위: 사전에 고품질 48kHz WAV로 렌더링된 assets/audio/test_beep.wav (FFmpegPCMAudio)
    3순위: 순수 파이썬 메모리 펄스 비프음 PulseBeepAudioSource (무의존성 폴백)
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    opus_path = os.path.join(base_dir, "assets", "audio", "test_beep.opus")
    wav_path = os.path.join(base_dir, "assets", "audio", "test_beep.wav")
    ffmpeg_exe = core.get_ffmpeg_executable()

    if os.path.exists(wav_path):
        try:
            return discord.FFmpegPCMAudio(wav_path, executable=ffmpeg_exe), "FFmpegPCMAudio (고음량 48kHz 팡파르 화음)"
        except Exception:
            pass

    if os.path.exists(opus_path):
        try:
            return discord.FFmpegOpusAudio(opus_path, executable=ffmpeg_exe), "FFmpegOpusAudio (네이티브 Opus 스트림)"
        except Exception:
            pass

    return PulseBeepAudioSource(duration_sec=5.0, freq=880.0), "PulseBeepAudioSource (순수 파이썬 메모리 펄스)"


def _format_duration_mmss(sec: int) -> str:
    if not sec or sec <= 0:
        return "실시간 스트림"
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"



# ==========================================
# 🛡️ 고음질 무지연 사전 버퍼링 오디오 소스 (네트워크 끊김·속도 튐·이상 소음 원천 방지)
# ==========================================
class JitterFreeAudioBuffer(discord.AudioSource):
    """
    네트워크 지터 및 FFmpeg I/O 지연을 완벽하게 흡수하는 무지연 인메모리 사전 버퍼링 오디오 소스.
    - 백그라운드 스레드가 FFmpeg 출력을 약 5초(250 프레임) 분량 선독(Pre-fetch)하여 큐에 유지합니다.
    - 재생 시작 전 0.5초(25 프레임) 분량의 쿠션 버퍼를 사전 확보한 후 음성 패킷을 공급하므로,
      Discord AudioPlayer 스레드가 20ms마다 프레임을 요구할 때 메모리에서 0.00001초 즉시 반환됩니다.
    - 네트워크 일시 지연 시에도 패킷 버스트(순간 과속 재생) 및 패킷 결핍(뚝뚝 끊김/로봇 소음)을 원천 방지합니다.
    """
    def __init__(self, original: discord.AudioSource, prefetch_frames: int = 25, max_frames: int = 250):
        self.original = original
        self.queue: queue.Queue[bytes] = queue.Queue(maxsize=max_frames)
        self._stopped = threading.Event()
        self._eof = threading.Event()
        self._ready = threading.Event()
        self.prefetch_frames = prefetch_frames

        self._thread = threading.Thread(target=self._worker, daemon=True, name="NorosiAudioBufferWorker")
        self._thread.start()

        # 재생 시작 전 0.5초(25프레임) 분량의 쿠션 버퍼를 최대 2.5초간 안전하게 대기
        self._ready.wait(timeout=2.5)

    def _worker(self):
        while not self._stopped.is_set():
            try:
                chunk = self.original.read()
                if not chunk:
                    self._eof.set()
                    self._ready.set()
                    break
                while not self._stopped.is_set():
                    try:
                        self.queue.put(chunk, timeout=0.1)
                        if self.queue.qsize() >= self.prefetch_frames:
                            self._ready.set()
                        break
                    except queue.Full:
                        continue
            except Exception:
                self._eof.set()
                self._ready.set()
                break

    def read(self) -> bytes:
        if self._stopped.is_set():
            return b""
        try:
            return self.queue.get(timeout=0.2)
        except queue.Empty:
            if self._eof.is_set():
                return b""
            # 극심한 네트워크 순단 발생 시 오디오 플레이어 조기 종료를 막기 위한 20ms 무음 쿠션
            return b"\x00" * 3840

    @property
    def _current_error(self):
        return getattr(self.original, "_current_error", None)

    def is_opus(self) -> bool:
        return getattr(self.original, "is_opus", lambda: False)()

    def cleanup(self):
        self._stopped.set()
        try:
            self.original.cleanup()
        except Exception:
            pass
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except Exception:
                break


# ==========================================
# 🔊 음성채널 플레이리스트 순차 자동재생 엔진 (GuildVoicePlaylistPlayer)
# ==========================================
_VOICE_PLAYERS: dict[int, "GuildVoicePlaylistPlayer"] = {}


def get_voice_player(bot: commands.Bot, guild: discord.Guild) -> "GuildVoicePlaylistPlayer":
    gid = guild.id
    if gid not in _VOICE_PLAYERS:
        _VOICE_PLAYERS[gid] = GuildVoicePlaylistPlayer(bot, guild)
    else:
        _VOICE_PLAYERS[gid].bot = bot
        _VOICE_PLAYERS[gid].guild = guild
    return _VOICE_PLAYERS[gid]


class GuildVoicePlaylistPlayer:
    """
    서버(Guild)별 음성채널 플레이리스트 자동재생 상태 및 FFmpeg 스트리밍 컨트롤러.
    - 플레이리스트의 1번 곡부터 마지막 곡까지 순번대로 자동 실행(Auto-Next)합니다.
    - 편의성 설정: 반복 모드(전체 반복 / 1곡 반복 / 반복 끔), 볼륨 조절(10%~200%), 셔플, 특정 트랙 점프,
      곡 변경 시 자동 알림 토글, 무인 음성채널 자동 퇴장 및 취침 예약 타이머(Sleep Timer)를 지원합니다.
    """
    def __init__(self, bot: commands.Bot, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.voice_client: Optional[discord.VoiceClient] = None
        self.text_channel: Optional[discord.abc.Messageable] = None
        self.control_message: Optional[discord.Message] = None

        self.playlist_owner_id: int = 0
        self.playlist_owner_name: str = ""
        self.playlist_id: str = "pl_default"
        self.playlist_name: str = "나만의 대표 플레이리스트"
        self.playlist_emoji: str = "🎧"
        self.playlist_platform: str = "YouTube"

        self.tracks: list[dict] = []
        self.current_index: int = 0
        self.current_stream_meta: Optional[dict] = None
        self.track_started_at: float = 0.0

        # 편의성 설정 상태
        self.loop_mode: str = "all"  # "all"(플리 전체 순환) | "one"(현재 곡 반복) | "off"(1회 완주 후 종료)
        self.volume: float = 0.20    # 기본 음량 20% (0.20)
        self.auto_announce: bool = True  # 다음 곡 자동 전환 시 대시보드 실시간 갱신
        self.deaf_mode: bool = True  # 기본값: 헤드셋 끄기 (청각 차단 On / deafen)
        self.playback_speed: float = 1.0  # 기본값: 1.0배속 (0.5x ~ 2.0x 지원)
        self.is_playing_flag: bool = False
        self.is_paused_flag: bool = False
        self._stop_requested: bool = False
        self._skip_lock = asyncio.Lock()
        self._play_generation: int = 0
        self._sleep_task: Optional[asyncio.Task] = None
        self.sleep_until_ts: Optional[float] = None

    @property
    def current_track(self) -> Optional[dict]:
        if 0 <= self.current_index < len(self.tracks):
            return self.tracks[self.current_index]
        return None

    def set_sleep_timer(self, minutes: int):
        if self._sleep_task and not self._sleep_task.done():
            self._sleep_task.cancel()
        if minutes <= 0:
            self.sleep_until_ts = None
            self._sleep_task = None
            return
        self.sleep_until_ts = time.time() + (minutes * 60)

        async def _timer_job():
            try:
                await asyncio.sleep(minutes * 60)
                ch = self.text_channel
                await self.stop_and_disconnect()
                if ch:
                    try:
                        await ch.send(f"🌙 **취침 예약 타이머(`{minutes}분`)**가 완료되어 음성채널 자동재생을 마치고 퇴장했습니다.")
                    except Exception:
                        pass
            except asyncio.CancelledError:
                pass

        self._sleep_task = asyncio.create_task(_timer_job())

    async def set_deafen(self, enable: bool) -> bool:
        """봇의 헤드셋 끄기(청각 차단 / deafen) 상태를 변경합니다."""
        self.deaf_mode = enable
        vc = self.guild.voice_client
        if vc and vc.is_connected():
            try:
                cur_ch = vc.channel
                await self.guild.change_voice_state(channel=cur_ch, self_mute=False, self_deaf=enable)
                return True
            except Exception as e:
                print(f"⚠️ 헤드셋 상태 변경 예외: {e}", flush=True)
                return False
        return True

    async def toggle_deafen(self) -> bool:
        """봇의 헤드셋 끄기(청각 차단) 상태를 반전 토글하고 새 상태(True: 끔/차단, False: 켬/해제)를 반환합니다."""
        new_state = not self.deaf_mode
        await self.set_deafen(new_state)
        return new_state

    async def set_playback_speed(self, speed: float) -> tuple[bool, str]:
        """플레이어의 재생 배속(0.5x ~ 2.0x)을 설정하고 현재 곡을 새로운 속도로 매끄럽게 재적용합니다."""
        val = round(max(0.5, min(2.0, float(speed))), 2)
        self.playback_speed = val
        vc = self.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()) and self.current_stream_meta:
            await self.skip_to(self.current_index)
        await self.refresh_control_panel()
        return True, f"⚡ 재생 속도가 **`{val}배속`**으로 설정되었습니다!"

    async def ensure_connected(self, target_vc: discord.abc.Connectable, self_deaf: Optional[bool] = None) -> tuple[bool, str]:
        # libopus 라이브러리 사전 로드 보장
        core.ensure_opus_loaded()

        if self_deaf is not None:
            self.deaf_mode = self_deaf

        # 0) 봇에게 해당 음성채널의 연결(Connect) 및 말하기(Speak) 권한이 있는지 사전 검사
        me = self.guild.me or self.guild.get_member(self.bot.user.id)
        if me and hasattr(target_vc, "permissions_for"):
            perms = target_vc.permissions_for(me)
            if not perms.connect:
                return False, f"🚨 봇에게 **{target_vc.name}** 음성채널의 **'연결(Connect)'** 권한이 없습니다!"
            if not perms.speak:
                return False, f"🚨 봇에게 **{target_vc.name}** 음성채널의 **'말하기(Speak)'** 권한이 허용되어 있지 않습니다! (채널 권한 설정에서 봇의 '말하기'를 켜주세요)"

        try:
            vc = self.guild.voice_client
            if vc and vc.is_connected():
                if vc.channel.id != target_vc.id:
                    await vc.move_to(target_vc)
                self.voice_client = vc
            else:
                self.voice_client = await target_vc.connect(timeout=15.0, self_deaf=self.deaf_mode, self_mute=False)
                await asyncio.sleep(0.4)

            # 1) 디스코드 게이트웨이 레벨에서 헤드셋(self_deaf) 및 마이크(self_mute) 상태 확실히 동기화
            try:
                cur_ch = self.voice_client.channel if (self.voice_client and self.voice_client.channel) else target_vc
                await self.guild.change_voice_state(channel=cur_ch, self_mute=False, self_deaf=self.deaf_mode)
            except Exception:
                pass

            # 2) 서버 강제 음소거 해제 시도
            try:
                me = self.guild.me
                if me and me.voice and me.voice.mute:
                    await me.edit(mute=False)
            except Exception:
                pass

            # 3) 디스코드 음성 프로토콜 동기화 및 DAVE E2EE 세션 준비 대기
            if self.voice_client and hasattr(self.voice_client, "_connection"):
                conn = self.voice_client._connection
                dave_ver = getattr(conn, "dave_protocol_version", 0)
                if dave_ver > 0:
                    # DAVE 프로토콜 활성화 채널: MLS 키 교환 완료(can_encrypt) 대기 (최대 5초)
                    for _ in range(25):
                        if getattr(conn, "can_encrypt", False):
                            break
                        await asyncio.sleep(0.2)
                    # 타임아웃 후에도 can_encrypt가 False인 경우 패킷 폐기 방지를 위해 패스스루 모드 시도
                    if not getattr(conn, "can_encrypt", False):
                        dave_sess = getattr(conn, "dave_session", None)
                        if dave_sess and hasattr(dave_sess, "set_passthrough_mode"):
                            try:
                                dave_sess.set_passthrough_mode(True, 120)
                            except Exception:
                                pass
                else:
                    # 일반 표준 음성 채널: DAVE 미사용 (XChaCha20-Poly1305 표준 암호화 채널), 지연 없이 즉시 통과
                    pass

            return True, "연결 성공"
        except Exception as e:
            err_str = str(e)
            if "davey" in err_str:
                err_str = "디스코드 최신 E2EE 음성 통신에 필요한 `davey` 라이브러리가 서버에 설치되어 있지 않거나 비호환 버전입니다. (서버 터미널에서 `pip install \"davey>=0.1.6,<0.2.0\" \"discord.py[voice]>=2.7.1\"` 실행 필요)"
            elif "PyNaCl" in err_str or "nacl" in err_str:
                err_str = "음성 패킷 암호화 라이브러리(`PyNaCl`)가 서버에 설치되어 있지 않습니다. (서버 터미널에서 `pip install PyNaCl` 실행 필요)"

            return False, f"음성채널 연결 실패: {err_str}"

    async def start_playlist(
        self,
        voice_channel: discord.abc.Connectable,
        text_channel: discord.abc.Messageable,
        owner: discord.abc.User,
        playlist_data: dict,
        start_index: int = 0
    ) -> tuple[bool, str]:
        tracks = [core.normalize_playlist_track(t) for t in playlist_data.get("tracks", []) if isinstance(t, dict)]
        if not tracks:
            return False, "플레이리스트에 수록된 곡이 없습니다! 먼저 곡을 추가해 주세요."

        ok, err_msg = await self.ensure_connected(voice_channel, self_deaf=True)
        if not ok:
            return False, err_msg

        self.text_channel = text_channel
        self.playlist_owner_id = owner.id
        self.playlist_owner_name = owner.display_name
        self.playlist_id = str(playlist_data.get("id", "pl_default"))
        self.playlist_name = str(playlist_data.get("name", "플레이리스트"))
        self.playlist_emoji = str(playlist_data.get("emoji", "🎧"))
        self.playlist_platform = str(playlist_data.get("platform", "YouTube"))
        self.tracks = tracks
        self.current_index = max(0, min(start_index, len(tracks) - 1))
        self._stop_requested = False
        self._play_generation += 1

        await self._play_current_index(initial=True)
        return True, f"🔊 **{ getattr(voice_channel, 'name', '음성채널') }**에서 **`{self.playlist_emoji} {self.playlist_name}`** ({len(tracks)}곡) 순번 자동재생을 시작합니다!"

    async def _report_playback_error(self, err_text: str):
        """스트리밍 도중 오류 발생 시 텍스트 채널에 상태 안내"""
        if not self.text_channel:
            return
        try:
            embed = discord.Embed(
                title="⚠️ 오디오 스트리밍 안내",
                description=(
                    f"현재 곡 스트리밍 중 일시적인 연결 지연이 감지되었습니다.\n"
                    f"```\n{err_text[:300]}\n```\n"
                    f"💡 자동으로 다음 순번 트랙으로 전환을 시도합니다."
                ),
                color=0xE67E22
            )
            await self.text_channel.send(embed=embed)
        except Exception:
            pass

    async def _play_current_index(self, initial: bool = False, retry_count: int = 0):
        if self._stop_requested or not self.tracks:
            return

        self._play_generation += 1
        my_gen = self._play_generation

        vc = self.guild.voice_client
        if not vc or not vc.is_connected():
            self.is_playing_flag = False
            return
        self.voice_client = vc

        if not (0 <= self.current_index < len(self.tracks)):
            if self.loop_mode == "all" and self.tracks:
                self.current_index = 0
            else:
                self.is_playing_flag = False
                self.current_stream_meta = None
                await self.refresh_control_panel()
                return

        target_track = self.tracks[self.current_index]
        stream_meta, err = await core.resolve_voice_stream(target_track)

        # 스트림 변환 중 사용자가 스킵하거나 멈춘 경우 무시
        if my_gen != self._play_generation or self._stop_requested:
            return

        if err or not stream_meta or not stream_meta.get("stream_url"):
            # 현재 곡 추출 실패 시 텍스트 채널에 안내 메시지 전송 후 다음 순번 곡으로 자동 전환
            bad_title = target_track.get("title", "알 수 없는 곡")
            bad_artist = target_track.get("artist", "")
            bad_label = f"{bad_title} — {bad_artist}" if bad_artist and bad_artist != "아티스트 미지정" else bad_title
            if self.text_channel:
                try:
                    await self.text_channel.send(
                        f"⚠️ **#{self.current_index + 1}. `{bad_label}`** 스트리밍 링크를 불러오지 못해 다음 곡으로 자동 전환합니다. *(사유: {err or '오디오 스트림 없음'})*"
                    )
                except Exception:
                    pass

            if retry_count + 1 < len(self.tracks):
                self.current_index = (self.current_index + 1) % len(self.tracks)
                await self._play_current_index(initial=initial, retry_count=retry_count + 1)
                return
            else:
                self.is_playing_flag = False
                if self.text_channel:
                    try:
                        await self.text_channel.send("⚠️ 플레이리스트의 모든 수록곡 오디오 스트림을 불러올 수 없어 재생을 중단했습니다.")
                    except Exception:
                        pass
                return

        self.current_stream_meta = stream_meta
        self.track_started_at = time.time()
        self.is_playing_flag = True
        self.is_paused_flag = False

        ffmpeg_exe = core.get_ffmpeg_executable()
        core.ensure_opus_loaded()

        # 모든 FFmpeg 환경(Debian/Ubuntu/imageio-ffmpeg)에서 가장 완벽하게 호환되는 표준 스트리밍 옵션
        ua = stream_meta.get("user_agent")
        if ua:
            before_opts = f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin -user_agent "{ua}"'
        else:
            before_opts = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin"

        # 배속(playback_speed) 적용: 1.0배속이 아닐 경우 FFmpeg atempo 오디오 필터 적용
        # asetpts=PTS-STARTPTS를 함께 적용하여 원격 스트림 타임스탬프 불연속으로 인한 속도 튐/이상 음정 원천 차단
        speed = getattr(self, "playback_speed", 1.0)
        if abs(speed - 1.0) > 0.01:
            out_opts = f'-vn -filter:a "asetpts=PTS-STARTPTS,atempo={speed}"'
        else:
            out_opts = "-vn"

        # 1순위: FFmpeg PCM 오디오 + 5초 무지연 사전 버퍼링 + 실시간 볼륨 조절기 (디스코드 권장 최고음질)
        # 2순위: FFmpegOpusAudio 폴백
        try:
            raw_audio = discord.FFmpegPCMAudio(
                stream_meta["stream_url"],
                executable=ffmpeg_exe,
                before_options=before_opts,
                options=out_opts
            )
            buffered_audio = JitterFreeAudioBuffer(raw_audio, prefetch_frames=25, max_frames=250)
            source = discord.PCMVolumeTransformer(buffered_audio, volume=max(0.05, min(self.volume, 2.0)))
        except Exception:
            source = discord.FFmpegOpusAudio(
                stream_meta["stream_url"],
                executable=ffmpeg_exe,
                before_options=before_opts,
                options=out_opts
            )

        # 이미 재생 중이면 내부 stop 플래그를 잠시 보호하며 교체
        if vc.is_playing() or vc.is_paused():
            self._stop_requested = True
            vc.stop()
            await asyncio.sleep(0.15)
            self._stop_requested = False

        # 재생 준비 도중 스킵이나 정지 지시가 있었다면 중단
        if my_gen != self._play_generation or self._stop_requested:
            return

        # 발화 상태(Speaking Indicator) 사전 활성화로 첫 오디오 패킷 드롭 방지
        try:
            if hasattr(vc, "ws") and vc.ws:
                await vc.ws.speak(discord.SpeakingState.voice)
        except Exception:
            pass

        def _after_track(play_error: Optional[Exception]):
            # 이전 재생 세대의 콜백이거나 중지 상태면 즉시 무시
            if my_gen != self._play_generation or self._stop_requested:
                return
            if play_error:
                print(f"⚠️ [음성 재생 오류] {play_error}", flush=True)
                if self.text_channel:
                    self.bot.loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(self._report_playback_error(str(play_error)))
                    )
            self.bot.loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._on_track_finished(my_gen))
            )

        vc.play(source, after=_after_track)

        # 0.7초 후 음성 송출 상태 워치독 (소리 즉시 끊김 조기 감지)
        async def _verify_playback():
            await asyncio.sleep(0.7)
            if not self._stop_requested and my_gen == self._play_generation and vc and vc.is_connected():
                if not vc.is_playing() and not self.is_paused_flag and self.is_playing_flag:
                    print("⚠️ [오디오 스트림 조기 끊김 감지] URL 만료 또는 코덱 오류 가능성", flush=True)

        asyncio.create_task(_verify_playback())

        if not initial and self.auto_announce:
            await self.refresh_control_panel()


    async def _on_track_finished(self, gen: Optional[int] = None):
        async with self._skip_lock:
            if gen is not None and gen != self._play_generation:
                return
            if self._stop_requested or not self.tracks:
                return
            vc = self.guild.voice_client
            if not vc or not vc.is_connected():
                self.is_playing_flag = False
                return

            # 음성채널에 봇 혼자만 남았는지 체크 (무인 자동 퇴장 편의 기능)
            human_members = [m for m in vc.channel.members if not m.bot]
            if len(human_members) == 0:
                ch = self.text_channel
                await self.stop_and_disconnect()
                if ch:
                    try:
                        await ch.send("🔇 음성채널에 듣고 계신 멤버가 없어 플레이리스트 자동재생을 마치고 퇴장했습니다.")
                    except Exception:
                        pass
                return

            if self.loop_mode == "one":
                # 현재 순번 그대로 다시 재생
                pass
            elif self.current_index + 1 < len(self.tracks):
                self.current_index += 1
            elif self.loop_mode == "all":
                self.current_index = 0
            else:
                # 1회 순차 완주 완료
                self.is_playing_flag = False
                self.current_stream_meta = None
                await self.refresh_control_panel()
                if self.text_channel:
                    try:
                        await self.text_channel.send(
                            f"✅ **`{self.playlist_emoji} {self.playlist_name}`** 플레이리스트 (`{len(self.tracks)}곡`) 마지막 순번까지 모두 재생 완료했습니다!"
                        )
                    except Exception:
                        pass
                return

            await self._play_current_index(initial=False)

    async def skip_to(self, target_idx: int):
        async with self._skip_lock:
            if not self.tracks:
                return
            self._play_generation += 1
            self.current_index = target_idx % len(self.tracks)
            await self._play_current_index(initial=False)

    async def toggle_pause(self) -> str:
        vc = self.guild.voice_client
        if not vc or not vc.is_connected():
            return "음성채널에 연결되어 있지 않습니다."
        if vc.is_playing():
            vc.pause()
            self.is_paused_flag = True
            return "⏸️ 일시정지됨"
        elif vc.is_paused():
            vc.resume()
            self.is_paused_flag = False
            return "▶️ 다시 재생 중"
        else:
            await self._play_current_index(initial=False)
            return "▶️ 현재 곡 재생 시작"

    def adjust_volume(self, delta: float) -> int:
        self.volume = round(max(0.05, min(2.00, self.volume + delta)), 2)
        vc = self.guild.voice_client
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = self.volume
        return int(round(self.volume * 100))

    async def stop_and_disconnect(self):
        self._stop_requested = True
        self._play_generation += 1
        self.is_playing_flag = False
        self.is_paused_flag = False
        self.current_stream_meta = None
        if self._sleep_task and not self._sleep_task.done():
            self._sleep_task.cancel()
        self.sleep_until_ts = None

        vc = self.guild.voice_client
        if vc:
            try:
                if vc.is_playing() or vc.is_paused():
                    vc.stop()
                await vc.disconnect(force=True)
            except Exception:
                pass
        self.voice_client = None
        await self.refresh_control_panel()

    async def refresh_control_panel(self):
        if not self.control_message:
            return
        try:
            ctrl_view = VoicePlayerControlView(self)
            await self.control_message.edit(embed=ctrl_view.build_embed(), view=ctrl_view)
        except Exception:
            pass


class VoicePlayerControlView(core.SafeView):
    """
    음성채널 실시간 플레이리스트 자동재생 리모컨 대시보드 뷰.
    - 순번대로 자동 실행되는 현재 곡 정보, 진행 상태, 다음 예정 곡(Up Next) 표시
    - [⏮️ 이전 곡] [⏯️ 일시정지/재생] [⏭️ 다음 곡] [🔁 반복모드] [⏹️ 정지/퇴장]
    - [🔉 볼륨 -15%] [🔊 볼륨 +15%] [🔀 순번 셔플] [🌙 취침타이머] [💿 현재 곡 내 플리에 담기]
    - 드롭다운: 원하는 순번의 곡으로 즉시 점프 재생
    """
    def __init__(self, player: GuildVoicePlaylistPlayer):
        super().__init__(timeout=3600)
        self.player = player
        self.update_components()

    def update_components(self):
        vc = self.player.guild.voice_client
        connected = bool(vc and vc.is_connected())
        has_tracks = len(self.player.tracks) > 0

        self.prev_track_btn.disabled = not (connected and has_tracks)
        self.pause_resume_btn.disabled = not (connected and has_tracks)
        self.next_track_btn.disabled = not (connected and has_tracks)
        self.stop_btn.disabled = not connected

        if self.player.is_paused_flag:
            self.pause_resume_btn.label = "▶️ 재생"
            self.pause_resume_btn.style = discord.ButtonStyle.success
        else:
            self.pause_resume_btn.label = "⏸️ 일시정지"
            self.pause_resume_btn.style = discord.ButtonStyle.primary

        loop_labels = {
            "all": ("🔁 전체 순환", discord.ButtonStyle.success),
            "one": ("🔂 1곡 반복", discord.ButtonStyle.primary),
            "off": ("➡️ 1회 순차재생", discord.ButtonStyle.secondary),
        }
        lbl, st = loop_labels.get(self.player.loop_mode, loop_labels["all"])
        self.loop_btn.label = lbl
        self.loop_btn.style = st

        vol_pct = int(round(self.player.volume * 100))
        self.vol_down_btn.label = f"🔉 -15% ({vol_pct}%)"
        self.vol_up_btn.label = f"🔊 +15% ({vol_pct}%)"
        self.vol_down_btn.disabled = not connected
        self.vol_up_btn.disabled = not connected
        self.shuffle_queue_btn.disabled = not (connected and len(self.player.tracks) > 1)

        if self.player.sleep_until_ts and self.player.sleep_until_ts > time.time():
            rem_min = max(1, int((self.player.sleep_until_ts - time.time()) // 60) + 1)
            self.sleep_timer_btn.label = f"🌙 타이머 ({rem_min}분 남음)"
            self.sleep_timer_btn.style = discord.ButtonStyle.primary
        else:
            self.sleep_timer_btn.label = "🌙 취침타이머"
            self.sleep_timer_btn.style = discord.ButtonStyle.secondary

        # 트랙 점프 드롭다운 (최대 25곡 표시, 현재 순번 주변 우선)
        if not has_tracks:
            self.jump_select.options = [discord.SelectOption(label="재생 대기열이 비어 있습니다", value="NONE")]
            self.jump_select.disabled = True
        else:
            opts = []
            total = len(self.player.tracks)
            start_i = max(0, min(self.player.current_index - 5, max(0, total - 25)))
            end_i = min(total, start_i + 25)
            for idx in range(start_i, end_i):
                t = self.player.tracks[idx]
                is_cur = (idx == self.player.current_index)
                prefix = "▶️ [재생중]" if is_cur else f"#{idx + 1:02d}."
                t_plat = t.get("platform", "YouTube")
                t_emoji = "🔊" if is_cur else core.PLAYLIST_PLATFORMS.get(t_plat, core.PLAYLIST_PLATFORMS["YouTube"])["emoji"]
                opts.append(discord.SelectOption(
                    label=f"{prefix} {t.get('title', '제목 없음')}"[:95],
                    value=str(idx),
                    description=f"아티스트: {t.get('artist', '-')} | 선택 시 이 순번부터 즉시 재생"[:95],
                    emoji=t_emoji,
                    default=is_cur
                ))
            self.jump_select.options = opts
            self.jump_select.disabled = not connected
            self.jump_select.placeholder = f"🎵 곡 순번 바로 이동 (현재 {self.player.current_index + 1}번 / 총 {total}곡)..."

        # Row 3: 헤드셋 끄기(청각 차단) 토글, 오디오 재연결 및 배속 조절 버튼
        self.toggle_deaf_btn.disabled = not connected
        if self.player.deaf_mode:
            self.toggle_deaf_btn.label = "🎧 헤드셋: 끔 (차단 On)"
            self.toggle_deaf_btn.style = discord.ButtonStyle.secondary
        else:
            self.toggle_deaf_btn.label = "🎧 헤드셋: 켬 (차단 Off)"
            self.toggle_deaf_btn.style = discord.ButtonStyle.success
        self.refresh_audio_btn.disabled = not connected

        speed = getattr(self.player, "playback_speed", 1.0)
        self.speed_toggle_btn.label = f"⚡ 배속: {speed}x"
        self.speed_toggle_btn.style = discord.ButtonStyle.primary if abs(speed - 1.0) > 0.01 else discord.ButtonStyle.secondary
        self.speed_toggle_btn.disabled = not connected

    def build_embed(self) -> discord.Embed:
        self.update_components()
        vc = self.player.guild.voice_client
        connected = bool(vc and vc.is_connected())
        vc_name = vc.channel.name if (connected and vc.channel) else "연결 종료됨"
        p_meta = core.PLAYLIST_PLATFORMS.get(self.player.playlist_platform, core.PLAYLIST_PLATFORMS["YouTube"])
        r, g, b = p_meta["color"]

        cur_t = self.player.current_track
        total_cnt = len(self.player.tracks)
        cur_num = self.player.current_index + 1 if cur_t else 0
        vol_pct = int(round(self.player.volume * 100))
        loop_desc = {"all": "🔁 전곡 순환 자동재생", "one": "🔂 현재 곡 무한반복", "off": "➡️ 마지막 순번까지 1회 자동재생"}.get(self.player.loop_mode, "🔁 전곡 순환")
        deaf_badge = "🎧 **헤드셋:** `끄기 (차단 On)`" if self.player.deaf_mode else "🎧 **헤드셋:** `켜기 (차단 Off)`"
        speed = getattr(self.player, "playback_speed", 1.0)
        speed_badge = f"⚡ **배속:** `{speed}x`" if abs(speed - 1.0) > 0.01 else "⚡ **배속:** `1.0x (기본)`"

        if not connected or not cur_t:
            embed = discord.Embed(
                title=f"⏹️ [{self.player.playlist_name}] 음성채널 자동재생 종료",
                description=(
                    "음성채널 자동재생이 정지되었거나 완료되었습니다.\n"
                    "`/플레이리스트` 스튜디오에서 **`[🔊 음성채널 순차 자동재생]`** 버튼을 누르면 언제든 다시 시작할 수 있습니다!"
                ),
                color=discord.Color.dark_grey(),
                timestamp=datetime.datetime.now(core.KST)
            )
            return embed

        t_norm = core.normalize_playlist_track(cur_t)
        s_meta = self.player.current_stream_meta or {}
        dur_str = _format_duration_mmss(s_meta.get("duration", 0))
        status_badge = "⏸️ **일시정지 중**" if self.player.is_paused_flag else "🔊 **음성채널 실시간 스트리밍 중**"

        sleep_str = ""
        if self.player.sleep_until_ts and self.player.sleep_until_ts > time.time():
            rem_m = max(1, int((self.player.sleep_until_ts - time.time()) // 60) + 1)
            sleep_str = f"  |  🌙 **취침예약:** `{rem_m}분 후 종료`"

        embed = discord.Embed(
            title=f"🔊 [{vc_name}] {self.player.playlist_emoji} {self.player.playlist_name} — 순차 자동재생 대시보드",
            description=(
                f"{status_badge}  ·  **순번 `{cur_num:02d} / {total_cnt:02d}번 곡`**  ·  {deaf_badge}\n\n"
                f"### 🎶 [{t_norm['title']}]({t_norm['url']})\n"
                f"• 🎤 **아티스트:** `{t_norm['artist']}`  |  ⏱️ **길이:** `{dur_str}`\n"
                f"• 🎛️ **반복 설정:** `{loop_desc}`  |  🔊 **볼륨:** `{vol_pct}%`  |  {speed_badge}{sleep_str}\n"
                f"• 🔗 **원본 바로가기:** [📺YouTube]({t_norm['yt_url']}) · [🟢Spotify]({t_norm['sp_url']}) · [☁️SoundCloud]({t_norm['sc_url']})"
            ),
            color=discord.Color.from_rgb(r, g, b),
            timestamp=datetime.datetime.now(core.KST)
        )

        # 다음 순번 대기열 미리보기 (Up Next)
        upcoming_lines = []
        for offset in range(1, min(6, total_cnt)):
            nxt_idx = self.player.current_index + offset
            if nxt_idx >= total_cnt:
                if self.player.loop_mode == "all":
                    nxt_idx = nxt_idx % total_cnt
                else:
                    break
            nt = self.player.tracks[nxt_idx]
            nt_emoji = core.PLAYLIST_PLATFORMS.get(nt.get("platform", "YouTube"), core.PLAYLIST_PLATFORMS["YouTube"])["emoji"]
            upcoming_lines.append(f"`#{nxt_idx + 1:02d}.` {nt_emoji} **{nt.get('title', '제목 없음')}** — `{nt.get('artist', '-')}`")

        if upcoming_lines:
            embed.add_field(
                name="⏭️ 다음 자동재생 순번 대기열 (Up Next)",
                value="\n".join(upcoming_lines),
                inline=False
            )
        else:
            embed.add_field(
                name="⏭️ 다음 자동재생 순번 대기열",
                value="현재 곡이 마지막 순번입니다." if self.player.loop_mode == "off" else "단일 곡 반복 재생 중입니다.",
                inline=False
            )

        thumb = s_meta.get("image") or t_norm.get("image")
        if thumb:
            embed.set_thumbnail(url=thumb)

        embed.set_footer(text=f"플리: {self.player.playlist_owner_name} • 💡 소리가 안 들릴 땐 봇 우클릭 > [사용자 음량 100%] 확인 • [v2.8-Live]")
        return embed

    # Row 0: 핵심 재생 컨트롤 (이전곡 / 일시정지·재생 / 다음곡 / 반복모드 / 정지·퇴장)
    @discord.ui.button(label="⏮️ 이전 곡", style=discord.ButtonStyle.secondary, row=0)
    async def prev_track_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        new_idx = (self.player.current_index - 1) % max(1, len(self.player.tracks))
        await self.player.skip_to(new_idx)
        try:
            await interaction.edit_original_response(embed=self.build_embed(), view=self)
        except Exception:
            pass

    @discord.ui.button(label="⏸️ 일시정지", style=discord.ButtonStyle.primary, row=0)
    async def pause_resume_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        await self.player.toggle_pause()
        try:
            await interaction.edit_original_response(embed=self.build_embed(), view=self)
        except Exception:
            pass

    @discord.ui.button(label="⏭️ 다음 곡", style=discord.ButtonStyle.secondary, row=0)
    async def next_track_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        new_idx = (self.player.current_index + 1) % max(1, len(self.player.tracks))
        await self.player.skip_to(new_idx)
        try:
            await interaction.edit_original_response(embed=self.build_embed(), view=self)
        except Exception:
            pass

    @discord.ui.button(label="🔁 전체 순환", style=discord.ButtonStyle.success, row=0)
    async def loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        order = ["all", "one", "off"]
        cur = self.player.loop_mode
        self.player.loop_mode = order[(order.index(cur) + 1) % len(order)] if cur in order else "all"
        try:
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        except Exception:
            pass

    @discord.ui.button(label="⏹️ 정지/퇴장", style=discord.ButtonStyle.danger, row=0)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        await self.player.stop_and_disconnect()
        try:
            await interaction.edit_original_response(embed=self.build_embed(), view=self)
        except Exception:
            pass

    # Row 1: 편의성 설정 (볼륨 조절 / 대기열 셔플 / 취침 예약 타이머 / 현재 곡 내 플리에 스크랩)
    @discord.ui.button(label="🔉 -15%", style=discord.ButtonStyle.secondary, row=1)
    async def vol_down_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.adjust_volume(-0.15)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔊 +15%", style=discord.ButtonStyle.secondary, row=1)
    async def vol_up_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.adjust_volume(+0.15)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔀 순번 셔플", style=discord.ButtonStyle.secondary, row=1)
    async def shuffle_queue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.player.tracks) > 1:
            cur_track = self.player.current_track
            rest = [t for i, t in enumerate(self.player.tracks) if i != self.player.current_index]
            random.shuffle(rest)
            self.player.tracks = ([cur_track] if cur_track else []) + rest
            self.player.current_index = 0
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🌙 취침타이머", style=discord.ButtonStyle.secondary, row=1)
    async def sleep_timer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 클릭 시 0분(해제) -> 15분 -> 30분 -> 60분 순환
        now_ts = time.time()
        rem = (self.player.sleep_until_ts - now_ts) / 60.0 if (self.player.sleep_until_ts and self.player.sleep_until_ts > now_ts) else 0
        if rem <= 0:
            next_min = 15
        elif rem <= 16:
            next_min = 30
        elif rem <= 31:
            next_min = 60
        else:
            next_min = 0
        self.player.set_sleep_timer(next_min)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="💿 이 곡 내 플리에 담기", style=discord.ButtonStyle.success, row=1)
    async def grab_current_track_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cur_t = self.player.current_track
        if not cur_t:
            await core.safe_send_response(interaction, "❌ 현재 재생 중인 곡이 없습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
        my_pls = core.ensure_user_playlists(prof, interaction.user.display_name)
        my_pl = my_pls[0]
        norm_t = core.normalize_playlist_track(cur_t)
        if len(my_pl.get("tracks", [])) >= 100:
            await interaction.followup.send(f"❌ 내 플레이리스트(`{my_pl['emoji']} {my_pl['name']}`)가 최대 곡 수(100곡)에 도달했습니다.", ephemeral=True)
            return
        if any(t.get("title") == norm_t["title"] and t.get("artist") == norm_t["artist"] for t in my_pl["tracks"]):
            await interaction.followup.send(f"ℹ️ **{norm_t['title']}** 곡은 이미 `{my_pl['emoji']} {my_pl['name']}`에 들어있습니다!", ephemeral=True)
            return
        my_pl["tracks"].append(copy.deepcopy(norm_t))
        my_pl["updated_at"] = core.get_today_str()
        await asyncio.to_thread(core.save_data, data)
        await interaction.followup.send(
            f"💿 현재 재생 중인 **{norm_t['title']}** — `{norm_t['artist']}` 곡을 내 **`{my_pl['emoji']} {my_pl['name']}`**에 저장했습니다!",
            ephemeral=True
        )

    # Row 2: 원하는 순번의 곡으로 즉시 점프하는 드롭다운
    @discord.ui.select(placeholder="🎵 곡 순번 바로 이동...", row=2, options=[discord.SelectOption(label="곡 선택", value="0")])
    async def jump_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        if val == "NONE" or not val.isdigit():
            await core.safe_defer(interaction)
            return
        await core.safe_defer(interaction)
        await self.player.skip_to(int(val))
        try:
            await interaction.edit_original_response(embed=self.build_embed(), view=self)
        except Exception:
            pass

    # Row 3: 헤드셋(청각 차단) 토글 및 오디오 스트림 재연결
    @discord.ui.button(label="🎧 헤드셋: 끔", style=discord.ButtonStyle.secondary, row=3)
    async def toggle_deaf_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        new_state = await self.player.toggle_deafen()
        try:
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        except Exception:
            pass

    @discord.ui.button(label="🔄 오디오 재연결", style=discord.ButtonStyle.primary, emoji="🔄", row=3)
    async def refresh_audio_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        await self.player.skip_to(self.player.current_index)
        try:
            await interaction.edit_original_response(embed=self.build_embed(), view=self)
        except Exception:
            pass

    @discord.ui.button(label="⚡ 배속: 1.0x", style=discord.ButtonStyle.secondary, row=3)
    async def speed_toggle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        speeds = [1.0, 1.25, 1.5, 1.75, 2.0, 0.5, 0.75]
        cur = getattr(self.player, "playback_speed", 1.0)
        try:
            nxt_idx = (speeds.index(cur) + 1) % len(speeds)
        except ValueError:
            nxt_idx = 0
        nxt_speed = speeds[nxt_idx]
        await self.player.set_playback_speed(nxt_speed)
        try:
            await interaction.edit_original_response(embed=self.build_embed(), view=self)
        except Exception:
            pass


async def start_voice_playlist_from_interaction(
    interaction: discord.Interaction,
    owner: discord.abc.User,
    playlist_data: dict,
    start_index: int = 0
):
    """어느 뷰(스튜디오, 공유 카드, 상세 카드, 슬래시 명령어)에서든 원클릭으로 음성채널 자동재생을 시작하는 공통 헬퍼"""
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await core.safe_send_response(interaction, "❌ 음성채널 자동재생은 서버(길드) 채널에서만 사용할 수 있습니다.", ephemeral=True)
        return

    voice_state = interaction.user.voice
    if not voice_state or not voice_state.channel:
        await core.safe_send_response(
            interaction,
            "🔊 먼저 **디스코드 음성채널**에 입장하신 뒤 버튼을 눌러주세요!\n*(유저님이 들어가 계신 음성채널로 봇이 찾아가서 1번 곡부터 순번대로 자동 재생합니다)*",
            ephemeral=True
        )
        return

    tracks = playlist_data.get("tracks", [])
    if not tracks:
        await core.safe_send_response(
            interaction,
            "⚠️ 플레이리스트에 수록된 곡이 없습니다! 먼저 **`[➕ 곡 추가]`**로 곡을 담은 뒤 자동재생을 실행해 주세요.",
            ephemeral=True
        )
        return

    await core.safe_defer(interaction)
    player = get_voice_player(interaction.client, interaction.guild)
    ok, msg = await player.start_playlist(
        voice_channel=voice_state.channel,
        text_channel=interaction.channel,
        owner=owner,
        playlist_data=playlist_data,
        start_index=start_index
    )
    if not ok:
        await interaction.followup.send(f"❌ **음성채널 재생 실패:** {msg}", ephemeral=True)
        return

    ctrl_view = VoicePlayerControlView(player)
    sent_msg = await interaction.followup.send(content=msg, embed=ctrl_view.build_embed(), view=ctrl_view, wait=True)
    player.control_message = sent_msg


async def start_voice_playlist_from_context(
    ctx: commands.Context,
    owner: discord.abc.User,
    playlist_data: dict,
    start_index: int = 0
):
    """접두사(Prefix) 명령어에서 음성채널 자동재생을 시작하는 공통 헬퍼"""
    if not ctx.guild or not isinstance(ctx.author, discord.Member):
        await ctx.send("❌ 음성채널 자동재생은 서버 채널에서만 사용할 수 있습니다.")
        return

    voice_state = ctx.author.voice
    if not voice_state or not voice_state.channel:
        await ctx.send(
            "🔊 먼저 **디스코드 음성채널**에 입장하신 뒤 명령어를 입력해 주세요!\n*(유저님이 계신 음성채널로 봇이 찾아가서 1번 곡부터 순번대로 자동 재생합니다)*"
        )
        return

    tracks = playlist_data.get("tracks", [])
    if not tracks:
        await ctx.send(
            "⚠️ 플레이리스트에 수록된 곡이 없습니다! 먼저 곡을 담은 뒤 자동재생을 실행해 주세요."
        )
        return

    player = get_voice_player(ctx.bot, ctx.guild)
    ok, msg = await player.start_playlist(
        voice_channel=voice_state.channel,
        text_channel=ctx.channel,
        owner=owner,
        playlist_data=playlist_data,
        start_index=start_index
    )
    if not ok:
        await ctx.send(f"❌ **음성채널 재생 실패:** {msg}")
        return

    ctrl_view = VoicePlayerControlView(player)
    sent_msg = await ctx.send(content=msg, embed=ctrl_view.build_embed(), view=ctrl_view)
    player.control_message = sent_msg


class PlaylistReorderModal(core.SafeModal, title="🔢 곡 순번 변경 (자동재생 순서 조정)"):
    from_num = discord.ui.TextInput(
        label="이동할 곡의 현재 순번 (숫자)",
        placeholder="예: 3 (3번 곡을 이동하고 싶을 때)",
        required=True,
        max_length=4
    )
    to_num = discord.ui.TextInput(
        label="바꾸고 싶은 목표 순번 (숫자)",
        placeholder="예: 1 (1번 첫 곡 위치로 옮기고 싶을 때)",
        required=True,
        max_length=4
    )

    def __init__(self, studio_view: "PlaylistStudioView", parent_message: Optional[discord.Message] = None):
        super().__init__()
        self.studio_view = studio_view
        self.parent_message = parent_message

    async def on_submit(self, interaction: discord.Interaction):
        s_from = (self.from_num.value or "").strip()
        s_to = (self.to_num.value or "").strip()
        if not s_from.isdigit() or not s_to.isdigit():
            await core.safe_send_response(interaction, "❌ 순번은 숫자로만 입력해 주세요. (예: `3` ➔ `1`)", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, self.studio_view.owner.id, self.studio_view.owner.display_name)
        pls = core.ensure_user_playlists(prof, self.studio_view.owner.display_name)
        target_pl = next((p for p in pls if p["id"] == self.studio_view.current_pl_id), pls[0])
        tracks = target_pl.get("tracks", [])

        total = len(tracks)
        if total < 2:
            await interaction.followup.send("ℹ️ 순번을 변경하려면 최소 2곡 이상 수록되어 있어야 합니다.", ephemeral=True)
            return

        idx_from = int(s_from) - 1
        idx_to = max(0, min(total - 1, int(s_to) - 1))
        if not (0 <= idx_from < total):
            await interaction.followup.send(f"❌ 현재 순번은 `1` ~ `{total}` 사이의 숫자여야 합니다.", ephemeral=True)
            return

        moved_track = tracks.pop(idx_from)
        tracks.insert(idx_to, moved_track)
        target_pl["updated_at"] = core.get_today_str()
        await asyncio.to_thread(core.save_data, data)

        self.studio_view.data = data
        self.studio_view.current_page = idx_to // self.studio_view.items_per_page
        if self.parent_message:
            try:
                await self.parent_message.edit(embed=self.studio_view.build_embed(), view=self.studio_view)
            except Exception:
                pass
        else:
            try:
                await interaction.edit_original_response(embed=self.studio_view.build_embed(), view=self.studio_view)
            except Exception:
                pass

        await interaction.followup.send(
            f"🔢 **{moved_track.get('title')}** 곡의 재생 순번을 **`#{idx_from + 1:02d}번` ➔ `#{idx_to + 1:02d}번`**으로 변경했습니다!",
            ephemeral=True
        )


class PlaylistBulkAddModal(core.SafeModal, title="📋 여러 곡 한꺼번에 연속 추가"):
    bulk_lines = discord.ui.TextInput(
        label="한 줄에 한 곡씩 입력 (아티스트 - 곡제목 또는 링크, 최대 10줄)",
        style=discord.TextStyle.paragraph,
        placeholder="YOASOBI - 아이돌\nEve - 군청찬가\nIU - 밤편지\nhttps://youtu.be/...",
        required=True,
        max_length=1000
    )

    def __init__(self, studio_view: "PlaylistStudioView", parent_message: Optional[discord.Message] = None):
        super().__init__()
        self.studio_view = studio_view
        self.parent_message = parent_message

    async def on_submit(self, interaction: discord.Interaction):
        raw_lines = [ln.strip() for ln in (self.bulk_lines.value or "").splitlines() if ln.strip()]
        if not raw_lines:
            await core.safe_send_response(interaction, "❌ 추가할 곡 목록을 입력해 주세요.", ephemeral=True)
            return
        lines_to_process = raw_lines[:10]

        await core.safe_defer(interaction, ephemeral=True)
        cur_pl = self.studio_view.get_current_playlist()
        pref_plat = cur_pl.get("platform", "YouTube")

        resolved_list = []
        for ln in lines_to_process:
            tr = await core.resolve_playlist_track(ln, preferred_platform=pref_plat)
            resolved_list.append(tr)

        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, self.studio_view.owner.id, self.studio_view.owner.display_name)
        pls = core.ensure_user_playlists(prof, self.studio_view.owner.display_name)
        target_pl = next((p for p in pls if p["id"] == self.studio_view.current_pl_id), pls[0])
        existing_tracks = target_pl.setdefault("tracks", [])

        added = 0
        skipped_dup = 0
        for tr in resolved_list:
            if len(existing_tracks) >= 100:
                break
            if any(_track_matches(tr, et) for et in existing_tracks):
                skipped_dup += 1
                continue
            existing_tracks.append(tr)
            added += 1

        target_pl["updated_at"] = core.get_today_str()
        await asyncio.to_thread(core.save_data, data)

        self.studio_view.data = data
        self.studio_view.current_page = max(0, (len(target_pl["tracks"]) - 1) // self.studio_view.items_per_page)
        if self.parent_message:
            try:
                await self.parent_message.edit(embed=self.studio_view.build_embed(), view=self.studio_view)
            except Exception:
                pass
        else:
            try:
                await interaction.edit_original_response(embed=self.studio_view.build_embed(), view=self.studio_view)
            except Exception:
                pass

        dup_text = f" (중복 {skipped_dup}곡 자동 제외)" if skipped_dup > 0 else ""
        await interaction.followup.send(
            f"✅ 총 **`{added}곡`**을 순번대로 **`{target_pl['emoji']} {target_pl['name']}`** 플레이리스트에 일괄 추가했습니다!{dup_text}",
            ephemeral=True
        )


def _extract_track_identity(t: dict) -> tuple[str, str]:
    """곡의 고유 식별자 추출 (플랫폼별 영상/트랙 ID 또는 정제된 메타데이터)"""
    if not isinstance(t, dict):
        return ("none", "")

    # 1. YouTube 영상 ID 우선 추출
    for key in ("yt_url", "url"):
        val = str(t.get(key) or "")
        m = re.search(r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})", val)
        if m:
            return ("yt", m.group(1))

    # 2. Spotify 트랙 ID 추출
    for key in ("sp_url", "url"):
        val = str(t.get(key) or "")
        m = re.search(r"spotify\.com/track/([a-zA-Z0-9]+)", val)
        if m:
            return ("sp", m.group(1))

    # 3. 제목 및 아티스트 정제 매칭
    title = str(t.get("title") or "").strip().lower()
    artist = str(t.get("artist") or "").strip().lower()
    clean_title = re.sub(r'[\(\[\{](?:feat\.?|official|remastered|explicit|mv|m/v|lyrics|가사|full ver\.?|audio).*?[\)\]\}]', '', title, flags=re.IGNORECASE).strip()
    clean_title = re.sub(r'[\s_+\-–—]+', ' ', clean_title).strip()
    clean_artist = re.sub(r'[\s_+\-–—]+', ' ', artist).strip()
    if clean_artist in ("아티스트 미지정", "알 수 없는 아티스트", "-", "none", ""):
        clean_artist = ""
    return ("meta", f"{clean_title}::{clean_artist}")


def _track_matches(t1: dict, t2: dict) -> bool:
    """두 곡이 동일한 곡인지 정밀 판별 (ID 또는 제목+아티스트)"""
    k1 = _extract_track_identity(t1)
    k2 = _extract_track_identity(t2)
    if k1[0] in ("yt", "sp") and k1 == k2:
        return True

    t1_title = re.sub(r'[\(\[\{].*?[\)\]\}]', '', str(t1.get("title", ""))).strip().lower()
    t2_title = re.sub(r'[\(\[\{].*?[\)\]\}]', '', str(t2.get("title", ""))).strip().lower()
    t1_clean = re.sub(r'[\s_+\-–—]+', '', t1_title)
    t2_clean = re.sub(r'[\s_+\-–—]+', '', t2_title)

    if t1_clean and t1_clean == t2_clean:
        a1 = str(t1.get("artist", "")).strip().lower()
        a2 = str(t2.get("artist", "")).strip().lower()
        if not a1 or not a2 or a1 in ("아티스트 미지정", "-") or a2 in ("아티스트 미지정", "-"):
            return True
        a1_c = re.sub(r'[\s_+\-–—]+', '', a1)
        a2_c = re.sub(r'[\s_+\-–—]+', '', a2)
        if a1_c in a2_c or a2_c in a1_c:
            return True

    return False


def _track_key(t: dict) -> tuple:
    """곡 식별용 고유 키 (선택 삭제 및 딕셔너리 키용)"""
    kind, ident = _extract_track_identity(t)
    if kind in ("yt", "sp") and ident:
        return (kind, ident)
    return (str(t.get("title", "")).strip().lower(), str(t.get("artist", "")).strip().lower())


async def _load_owner_target_playlist(studio_view: "PlaylistStudioView"):
    """최신 데이터를 불러와 스튜디오에서 선택된 플레이리스트를 반환합니다."""
    data = await asyncio.to_thread(core.load_data)
    prof = core.ensure_user_profile(data, studio_view.owner.id, studio_view.owner.display_name)
    pls = core.ensure_user_playlists(prof, studio_view.owner.display_name)
    target_pl = next((p for p in pls if p["id"] == studio_view.current_pl_id), pls[0])
    return data, prof, pls, target_pl


async def _commit_and_refresh_studio(studio_view: "PlaylistStudioView", data: dict, parent_message: Optional[discord.Message] = None):
    """데이터를 저장하고 원본 스튜디오 패널을 즉시 새로고침합니다."""
    await asyncio.to_thread(core.save_data, data)
    studio_view.data = data
    if studio_view.current_page > studio_view.max_page:
        studio_view.current_page = studio_view.max_page
    target_msg = parent_message or getattr(studio_view, "message", None)
    if target_msg:
        try:
            await target_msg.edit(embed=studio_view.build_embed(), view=studio_view)
        except Exception:
            pass


def _remove_tracks_by_selection(tracks: list, selections: list) -> list:
    """
    selections: [(index, track_key), ...]
    해당 index의 곡이 key와 일치하면 그 곡을, 순서가 바뀌었다면 같은 key의 첫 곡을 삭제합니다.
    tracks 리스트를 제자리에서 수정하고, 삭제된 곡 목록을 반환합니다.
    """
    remove_idx = set()
    for idx, key in selections:
        if 0 <= idx < len(tracks) and idx not in remove_idx and _track_key(tracks[idx]) == key:
            remove_idx.add(idx)
            continue
        for j, t in enumerate(tracks):
            if j not in remove_idx and _track_key(t) == key:
                remove_idx.add(j)
                break
    removed = [tracks[i] for i in sorted(remove_idx)]
    tracks[:] = [t for i, t in enumerate(tracks) if i not in remove_idx]
    return removed


def _parse_index_spec(spec: str, total: int) -> list:
    """'3', '1, 4, 7', '10-15', '2 5~8', '3번', '3번곡' 형식의 번호 입력을 0-based 인덱스 목록으로 변환합니다."""
    result = set()
    for token in re.split(r"[,\s/]+", (spec or "").strip()):
        if not token:
            continue
        token = token.replace("~", "-").replace("번곡", "").replace("번", "").replace("곡", "").replace("#", "").strip()
        m = re.fullmatch(r"(\d+)-(\d+)", token)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            for n in range(a, b + 1):
                if 1 <= n <= total:
                    result.add(n - 1)
        elif token.isdigit():
            n = int(token)
            if 1 <= n <= total:
                result.add(n - 1)
    return sorted(result)


def _format_removed_preview(removed: list, limit: int = 10) -> str:
    lines = [f"• ~~{t.get('title', '제목 없음')}~~ — `{t.get('artist', '-')}`" for t in removed[:limit]]
    if len(removed) > limit:
        lines.append(f"*…외 {len(removed) - limit}곡*")
    return "\n".join(lines)


class PlaylistTrackDeleteView(core.SafeView):
    """
    🗑️ 곡 골라서 삭제하기 뷰
    - 드롭다운에서 원하는 곡을 여러 개 체크 (25곡 단위 페이지, 페이지 이동 시 선택 유지)
    - [이 페이지 전체 선택] / [선택 해제] / [🔢 번호로 삭제] 지원
    - [🗑️ 선택한 N곡 삭제] 클릭 시 확정 삭제 후 스튜디오 패널 자동 새로고침
    """
    PAGE_SIZE = 25

    def __init__(self, studio_view: "PlaylistStudioView", parent_message: Optional[discord.Message] = None):
        super().__init__(timeout=600)
        self.studio_view = studio_view
        self.parent_message = parent_message
        self.page = 0
        self.selected: dict = {}  # index -> track_key
        self._rebuild()

    def _tracks(self) -> list:
        return self.studio_view.get_current_playlist().get("tracks", [])

    @property
    def max_page(self) -> int:
        n = len(self._tracks())
        return max(0, (n - 1) // self.PAGE_SIZE)

    def _rebuild(self):
        tracks = self._tracks()
        self.page = min(self.page, self.max_page)
        start = self.page * self.PAGE_SIZE
        chunk = tracks[start:start + self.PAGE_SIZE]

        if not chunk:
            self.track_multi_select.options = [discord.SelectOption(label="삭제할 곡이 없습니다", value="NONE")]
            self.track_multi_select.min_values = 1
            self.track_multi_select.max_values = 1
            self.track_multi_select.disabled = True
        else:
            opts = []
            for i, t in enumerate(chunk, start=start):
                is_sel = i in self.selected
                opts.append(discord.SelectOption(
                    label=f"#{i + 1:02d}. {t.get('title', '제목 없음')}"[:95],
                    value=str(i),
                    description=f"{t.get('artist', '-')}"[:95],
                    emoji="🗑️" if is_sel else "🎵",
                    default=is_sel
                ))
            self.track_multi_select.options = opts
            self.track_multi_select.min_values = 0
            self.track_multi_select.max_values = len(opts)
            self.track_multi_select.disabled = False

        self.track_multi_select.placeholder = f"🗑️ 삭제할 곡 선택 (페이지 {self.page + 1}/{self.max_page + 1} · 여러 곡 체크 가능)"
        self.prev_page_btn.disabled = self.page <= 0
        self.next_page_btn.disabled = self.page >= self.max_page
        self.select_page_btn.disabled = not chunk
        n_sel = len(self.selected)
        self.clear_sel_btn.disabled = n_sel == 0
        self.confirm_delete_btn.disabled = n_sel == 0
        self.confirm_delete_btn.label = f"🗑️ 선택한 {n_sel}곡 삭제" if n_sel else "🗑️ 삭제할 곡을 먼저 선택하세요"

    def build_content(self) -> str:
        cur_pl = self.studio_view.get_current_playlist()
        tracks = self._tracks()
        n_sel = len(self.selected)
        header = (
            f"🗑️ **곡 골라서 삭제하기** — `{cur_pl.get('emoji', '🎧')} {cur_pl.get('name')}` (총 {len(tracks)}곡)\n"
            "• 아래 드롭다운에서 지울 곡을 **여러 개 체크**한 뒤 **`[🗑️ 선택한 N곡 삭제]`**를 누르세요.\n"
            "• 25곡이 넘으면 **`◀ ▶`**로 페이지를 넘겨도 선택이 유지됩니다.\n"
            "• 번호를 알고 있다면 **`[🔢 번호로 삭제]`**에서 `1, 4, 7-10`처럼 한 번에 지울 수 있어요."
        )
        if not n_sel:
            return header + "\n\n📭 **선택된 곡:** 없음"
        lines = []
        for idx in sorted(self.selected)[:10]:
            if 0 <= idx < len(tracks):
                t = tracks[idx]
                lines.append(f"`#{idx + 1:02d}` {t.get('title', '제목 없음')} — `{t.get('artist', '-')}`")
        if n_sel > 10:
            lines.append(f"*…외 {n_sel - 10}곡*")
        return header + f"\n\n🗑️ **선택된 곡 ({n_sel}곡):**\n" + "\n".join(lines)

    async def _refresh(self, interaction: discord.Interaction):
        self._rebuild()
        await interaction.response.edit_message(content=self.build_content(), view=self)

    @discord.ui.select(placeholder="🗑️ 삭제할 곡 선택...", min_values=0, max_values=1, row=0,
                       options=[discord.SelectOption(label="불러오는 중", value="NONE")])
    async def track_multi_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        tracks = self._tracks()
        start = self.page * self.PAGE_SIZE
        page_range = set(range(start, min(start + self.PAGE_SIZE, len(tracks))))
        for idx in list(self.selected):
            if idx in page_range:
                self.selected.pop(idx, None)
        for v in select.values:
            if v == "NONE":
                continue
            idx = int(v)
            if 0 <= idx < len(tracks):
                self.selected[idx] = _track_key(tracks[idx])
        await self._refresh(interaction)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        await self._refresh(interaction)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.max_page, self.page + 1)
        await self._refresh(interaction)

    @discord.ui.button(label="☑️ 이 페이지 전체 선택", style=discord.ButtonStyle.secondary, row=1)
    async def select_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        tracks = self._tracks()
        start = self.page * self.PAGE_SIZE
        for idx in range(start, min(start + self.PAGE_SIZE, len(tracks))):
            self.selected[idx] = _track_key(tracks[idx])
        await self._refresh(interaction)

    @discord.ui.button(label="↩️ 선택 해제", style=discord.ButtonStyle.secondary, row=1)
    async def clear_sel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.selected.clear()
        await self._refresh(interaction)

    @discord.ui.button(label="🗑️ 선택한 곡 삭제", style=discord.ButtonStyle.danger, row=2)
    async def confirm_delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.studio_view.owner.id:
            await core.safe_send_response(interaction, "❌ 플레이리스트 소유자 본인만 곡을 삭제할 수 있습니다.", ephemeral=True)
            return
        if not self.selected:
            await core.safe_send_response(interaction, "ℹ️ 먼저 삭제할 곡을 선택해 주세요.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        data, _prof, _pls, target_pl = await _load_owner_target_playlist(self.studio_view)
        removed = _remove_tracks_by_selection(target_pl["tracks"], list(self.selected.items()))
        if not removed:
            await interaction.edit_original_response(content="ℹ️ 선택한 곡이 이미 삭제되었거나 찾을 수 없습니다.", view=None)
            return
        target_pl["updated_at"] = core.get_today_str()
        await _commit_and_refresh_studio(self.studio_view, data, self.parent_message)
        self.selected.clear()
        await interaction.edit_original_response(
            content=(
                f"✅ **`{target_pl['emoji']} {target_pl['name']}`**에서 **{len(removed)}곡**을 삭제했습니다! "
                f"(남은 곡: {len(target_pl['tracks'])}곡)\n{_format_removed_preview(removed)}"
            ),
            view=None
        )

    @discord.ui.button(label="🔢 번호로 삭제", style=discord.ButtonStyle.primary, row=2)
    async def delete_by_number_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PlaylistDeleteByNumberModal(self.studio_view, parent_message=self.parent_message))


class PlaylistDeleteByNumberModal(core.SafeModal, title="🔢 번호로 곡 삭제"):
    spec_input = discord.ui.TextInput(
        label="삭제할 곡 번호 (쉼표 · 범위 입력 가능)",
        placeholder="예: 3   /   1, 4, 7   /   10-15   /   2, 5~8",
        required=True,
        max_length=200
    )

    def __init__(self, studio_view: "PlaylistStudioView", parent_message: Optional[discord.Message] = None):
        super().__init__()
        self.studio_view = studio_view
        self.parent_message = parent_message

    async def on_submit(self, interaction: discord.Interaction):
        await core.safe_defer(interaction, ephemeral=True)
        data, _prof, _pls, target_pl = await _load_owner_target_playlist(self.studio_view)
        tracks = target_pl["tracks"]
        indices = _parse_index_spec(self.spec_input.value, len(tracks))
        if not indices:
            await interaction.followup.send(
                f"❌ 올바른 곡 번호가 없습니다. 현재 플레이리스트는 **1 ~ {len(tracks)}번**까지 있습니다.\n"
                "예시: `3`, `1, 4, 7`, `10-15`",
                ephemeral=True
            )
            return
        idx_set = set(indices)
        removed = [t for i, t in enumerate(tracks) if i in idx_set]
        target_pl["tracks"] = [t for i, t in enumerate(tracks) if i not in idx_set]
        target_pl["updated_at"] = core.get_today_str()
        await _commit_and_refresh_studio(self.studio_view, data, self.parent_message)
        await interaction.followup.send(
            f"✅ **`{target_pl['emoji']} {target_pl['name']}`**에서 **{len(removed)}곡**을 삭제했습니다! "
            f"(남은 곡: {len(target_pl['tracks'])}곡)\n{_format_removed_preview(removed)}",
            ephemeral=True
        )


class PlaylistSearchModal(core.SafeModal, title="🔍 플레이리스트 곡 검색"):
    keyword_input = discord.ui.TextInput(
        label="검색어 (곡 제목 · 아티스트 · 메모)",
        placeholder="예: 아이유, YOASOBI, 밤편지",
        required=True,
        max_length=60
    )

    def __init__(self, studio_view: "PlaylistStudioView", parent_message: Optional[discord.Message] = None):
        super().__init__()
        self.studio_view = studio_view
        self.parent_message = parent_message

    async def on_submit(self, interaction: discord.Interaction):
        kw = (self.keyword_input.value or "").strip().lower()
        cur_pl = self.studio_view.get_current_playlist()
        tracks = cur_pl.get("tracks", [])
        matches = [
            (i, t) for i, t in enumerate(tracks)
            if kw in str(t.get("title", "")).lower() or kw in str(t.get("artist", "")).lower() or kw in str(t.get("memo", "")).lower()
        ]
        if not matches:
            await core.safe_send_response(interaction, f"🔍 **`{self.keyword_input.value}`**와(과) 일치하는 곡이 없습니다.", ephemeral=True)
            return
        view = PlaylistSearchResultView(self.studio_view, matches, parent_message=self.parent_message)
        await core.safe_send_response(interaction, view.build_content(self.keyword_input.value), view=view, ephemeral=True)


class PlaylistSearchResultView(core.SafeView):
    """검색 결과에서 곡을 골라 상세(재생 / 순번 이동 / 삭제)를 열거나, 검색된 곡을 한 번에 삭제하는 뷰"""
    def __init__(self, studio_view: "PlaylistStudioView", matches: list, parent_message: Optional[discord.Message] = None):
        super().__init__(timeout=300)
        self.studio_view = studio_view
        self.matches = matches[:25]
        self.total_matches = len(matches)
        self.parent_message = parent_message
        self.result_select.options = [
            discord.SelectOption(
                label=f"#{i + 1:02d}. {t.get('title', '제목 없음')}"[:95],
                value=str(i),
                description=f"{t.get('artist', '-')} · 선택 시 재생/순번 변경/삭제"[:95],
                emoji="🎵"
            )
            for i, t in self.matches
        ]
        self.delete_all_matches_btn.label = f"🗑️ 검색된 {len(self.matches)}곡 모두 삭제"

    def build_content(self, keyword: str) -> str:
        lines = [f"`#{i + 1:02d}` **{t.get('title', '제목 없음')}** — `{t.get('artist', '-')}`" for i, t in self.matches[:15]]
        more = f"\n*…외 {self.total_matches - 15}곡*" if self.total_matches > 15 else ""
        return f"🔍 **`{keyword}`** 검색 결과 **{self.total_matches}곡**\n" + "\n".join(lines) + more

    @discord.ui.select(placeholder="🎵 곡을 선택하면 재생 / 순번 변경 / 삭제 메뉴가 열립니다...", row=0,
                       options=[discord.SelectOption(label="결과 없음", value="NONE")])
    async def result_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        idx = int(select.values[0])
        cur_pl = self.studio_view.get_current_playlist()
        tracks = cur_pl.get("tracks", [])
        if not (0 <= idx < len(tracks)):
            await core.safe_send_response(interaction, "❌ 선택한 곡을 찾을 수 없습니다.", ephemeral=True)
            return
        detail_view = PlaylistTrackDetailView(
            tracks[idx], self.studio_view.owner.id, cur_pl["id"],
            parent_studio=self.studio_view, parent_message=self.parent_message
        )
        await core.safe_send_response(interaction, embed=detail_view.build_embed(), view=detail_view, ephemeral=True)

    @discord.ui.button(label="🗑️ 검색된 곡 모두 삭제", style=discord.ButtonStyle.danger, row=1)
    async def delete_all_matches_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.studio_view.owner.id:
            await core.safe_send_response(interaction, "❌ 플레이리스트 소유자 본인만 곡을 삭제할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        data, _prof, _pls, target_pl = await _load_owner_target_playlist(self.studio_view)
        removed = _remove_tracks_by_selection(target_pl["tracks"], [(i, _track_key(t)) for i, t in self.matches])
        target_pl["updated_at"] = core.get_today_str()
        await _commit_and_refresh_studio(self.studio_view, data, self.parent_message)
        await interaction.edit_original_response(
            content=f"✅ 검색된 곡 중 **{len(removed)}곡**을 삭제했습니다!\n{_format_removed_preview(removed)}",
            view=None
        )


class PlaylistClearConfirmView(core.SafeView):
    """플레이리스트 전체 비우기 확인 뷰"""
    def __init__(self, studio_view: "PlaylistStudioView", parent_message: Optional[discord.Message] = None):
        super().__init__(timeout=60)
        self.studio_view = studio_view
        self.parent_message = parent_message

    @discord.ui.button(label="💣 네, 전부 비울게요", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        data, _prof, _pls, target_pl = await _load_owner_target_playlist(self.studio_view)
        cnt = len(target_pl["tracks"])
        target_pl["tracks"] = []
        target_pl["updated_at"] = core.get_today_str()
        self.studio_view.current_page = 0
        await _commit_and_refresh_studio(self.studio_view, data, self.parent_message)
        await interaction.edit_original_response(content=f"🧹 **`{target_pl['name']}`**의 수록곡 **{cnt}곡**을 모두 비웠습니다.", view=None)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="↩️ 전체 비우기를 취소했습니다.", view=None)


class PlaylistConvenienceView(core.SafeView):
    """
    [⚙️ 순번·편의기능] 버튼 클릭 시 열리는 플레이리스트 편의성 도구 모음 뷰
    - 🔢 곡 순번 직접 지정 이동 (모달)
    - 📋 여러 곡 한꺼번에 연속 추가 (모달) / 🔗 플리 링크로 대량 추가
    - 🗑️ 곡 골라서 삭제 (다중 선택) / 🔢 번호로 삭제
    - 🔀 트랙 순번 랜덤 섞기 / 🔤 가나다순 정렬 / 🎤 아티스트순 / 🔄 역순 정렬
    - 🔍 곡 검색 / 🧹 중복 곡 정리 / 📄 플리 복제 / 📃 목록 내보내기 / 💣 전체 비우기
    - 🎛️ 음성채널 리모컨 열기
    """
    def __init__(self, studio_view: "PlaylistStudioView", parent_message: Optional[discord.Message] = None):
        super().__init__(timeout=300)
        self.studio_view = studio_view
        self.parent_message = parent_message

    async def _save_and_refresh_parent(self, data: dict):
        await _commit_and_refresh_studio(self.studio_view, data, self.parent_message)

    # Row 0: 추가 · 이동 · 삭제
    @discord.ui.button(label="🔢 순번 변경", style=discord.ButtonStyle.primary, row=0)
    async def reorder_modal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PlaylistReorderModal(self.studio_view, parent_message=self.parent_message))

    @discord.ui.button(label="📋 여러 곡 추가", style=discord.ButtonStyle.success, row=0)
    async def bulk_add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PlaylistBulkAddModal(self.studio_view, parent_message=self.parent_message))

    @discord.ui.button(label="🔗 플리 링크로 추가", style=discord.ButtonStyle.success, row=0)
    async def bulk_import_url_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PlaylistImportUrlModal(self.studio_view, parent_message=self.parent_message, default_mode="2"))

    @discord.ui.button(label="🗑️ 곡 골라서 삭제", style=discord.ButtonStyle.danger, row=0)
    async def pick_delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.studio_view.get_current_playlist().get("tracks"):
            await core.safe_send_response(interaction, "📭 삭제할 곡이 없습니다.", ephemeral=True)
            return
        del_view = PlaylistTrackDeleteView(self.studio_view, parent_message=self.parent_message)
        await core.safe_send_response(interaction, del_view.build_content(), view=del_view, ephemeral=True)

    @discord.ui.button(label="🔢 번호로 삭제", style=discord.ButtonStyle.danger, row=0)
    async def number_delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PlaylistDeleteByNumberModal(self.studio_view, parent_message=self.parent_message))

    # Row 1: 정렬 · 리모컨
    @discord.ui.button(label="🔤 제목순", style=discord.ButtonStyle.secondary, row=1)
    async def sort_title_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        data, _prof, _pls, target_pl = await _load_owner_target_playlist(self.studio_view)
        target_pl["tracks"].sort(key=lambda x: str(x.get("title", "")).lower())
        await self._save_and_refresh_parent(data)
        await interaction.edit_original_response(
            content="✅ 플레이리스트 수록곡 순번을 **제목 가나다/알파벳순**으로 정렬했습니다!\n*(아래 편의 도구를 계속 사용할 수 있습니다)*",
            view=self
        )

    @discord.ui.button(label="🎤 아티스트순", style=discord.ButtonStyle.secondary, row=1)
    async def sort_artist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        data, _prof, _pls, target_pl = await _load_owner_target_playlist(self.studio_view)
        target_pl["tracks"].sort(key=lambda x: (str(x.get("artist", "")).lower(), str(x.get("title", "")).lower()))
        await self._save_and_refresh_parent(data)
        await interaction.edit_original_response(
            content="✅ 플레이리스트 수록곡 순번을 **아티스트 이름순**으로 정렬했습니다!\n*(아래 편의 도구를 계속 사용할 수 있습니다)*",
            view=self
        )

    @discord.ui.button(label="🔄 역순", style=discord.ButtonStyle.secondary, row=1)
    async def reverse_order_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        data, _prof, _pls, target_pl = await _load_owner_target_playlist(self.studio_view)
        target_pl["tracks"].reverse()
        await self._save_and_refresh_parent(data)
        await interaction.edit_original_response(
            content="✅ 플레이리스트 수록곡 순번을 **역순**으로 뒤집었습니다!\n*(아래 편의 도구를 계속 사용할 수 있습니다)*",
            view=self
        )

    @discord.ui.button(label="🔀 순번 섞기", style=discord.ButtonStyle.secondary, row=1)
    async def shuffle_order_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        data, _prof, _pls, target_pl = await _load_owner_target_playlist(self.studio_view)
        random.shuffle(target_pl["tracks"])
        await self._save_and_refresh_parent(data)
        await interaction.edit_original_response(
            content="✅ 플레이리스트 수록곡 순번을 **랜덤으로 골고루 섞었습니다!**\n*(아래 편의 도구를 계속 사용할 수 있습니다)*",
            view=self
        )

    @discord.ui.button(label="🎛️ 음성리모컨", style=discord.ButtonStyle.secondary, row=1)
    async def voice_remote_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        player = get_voice_player(interaction.client, interaction.guild)
        ctrl_view = VoicePlayerControlView(player)
        await core.safe_send_response(interaction, embed=ctrl_view.build_embed(), view=ctrl_view, ephemeral=True)

    # Row 2: 관리 도구
    @discord.ui.button(label="🔍 곡 검색", style=discord.ButtonStyle.primary, row=2)
    async def search_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PlaylistSearchModal(self.studio_view, parent_message=self.parent_message))

    @discord.ui.button(label="🧹 중복 곡 정리", style=discord.ButtonStyle.secondary, row=2)
    async def dedupe_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        data, _prof, _pls, target_pl = await _load_owner_target_playlist(self.studio_view)
        kept, removed = [], []
        for t in target_pl.get("tracks", []):
            if any(_track_matches(t, kept_t) for kept_t in kept):
                removed.append(t)
            else:
                kept.append(t)
        if not removed:
            await interaction.edit_original_response(
                content="✨ 중복된 곡이 없습니다! 플레이리스트가 이미 깔끔해요.",
                view=self
            )
            return
        target_pl["tracks"] = kept
        target_pl["updated_at"] = core.get_today_str()
        await self._save_and_refresh_parent(data)
        await interaction.edit_original_response(
            content=f"🧹 중복 곡 **{len(removed)}곡**을 정리했습니다! (첫 번째 곡만 남김)\n{_format_removed_preview(removed)}\n*(아래 편의 도구를 계속 사용할 수 있습니다)*",
            view=self
        )

    @discord.ui.button(label="📄 플리 복제", style=discord.ButtonStyle.secondary, row=2)
    async def duplicate_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        data, _prof, pls, target_pl = await _load_owner_target_playlist(self.studio_view)
        if len(pls) >= 20:
            await interaction.edit_original_response(
                content="❌ 플레이리스트는 1인당 최대 **20개**까지만 만들 수 있습니다.",
                view=self
            )
            return
        today_s = core.get_today_str()
        new_pl = copy.deepcopy(target_pl)
        new_pl["id"] = f"pl_{int(time.time())}_{random.randint(100, 999)}"
        new_pl["name"] = f"{target_pl.get('name', '플레이리스트')} (복사본)"[:50]
        new_pl["likes"] = []
        new_pl["share_count"] = 0
        new_pl["created_at"] = today_s
        new_pl["updated_at"] = today_s
        for n, t in enumerate(new_pl.get("tracks", []), start=1):
            t["id"] = f"trk_{int(time.time())}_{n}_{random.randint(100, 999)}"
        pls.append(new_pl)
        self.studio_view.current_pl_id = new_pl["id"]
        self.studio_view.current_page = 0
        await self._save_and_refresh_parent(data)
        await interaction.edit_original_response(
            content=f"📄 **`{new_pl['emoji']} {new_pl['name']}`**을(를) 만들었습니다! ({len(new_pl.get('tracks', []))}곡 복제)\n*(스튜디오가 복제된 플레이리스트로 자동 전환되었습니다)*",
            view=self
        )

    @discord.ui.button(label="📃 목록 내보내기", style=discord.ButtonStyle.secondary, row=2)
    async def export_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        import io
        cur_pl = self.studio_view.get_current_playlist()
        tracks = cur_pl.get("tracks", [])
        if not tracks:
            await core.safe_send_response(interaction, "📭 내보낼 곡이 없습니다.", ephemeral=True)
            return
        lines = [f"{cur_pl.get('emoji', '🎧')} {cur_pl.get('name')} — 총 {len(tracks)}곡", ""]
        for i, t in enumerate(tracks, start=1):
            lines.append(f"{i:02d}. {t.get('artist', '-')} - {t.get('title', '제목 없음')} | {t.get('url', '')}")
        buf = io.BytesIO("\n".join(lines).encode("utf-8"))
        safe_name = re.sub(r"[^\w가-힣\- ]", "", str(cur_pl.get("name", "playlist")))[:40].strip() or "playlist"
        await core.safe_send_response(
            interaction,
            "📃 플레이리스트 수록곡 목록을 텍스트 파일로 내보냈습니다! (`!플리가져오기`나 `[📋 여러 곡 추가]`에 재사용 가능)",
            file=discord.File(buf, filename=f"{safe_name}.txt"),
            ephemeral=True
        )

    @discord.ui.button(label="💣 전체 비우기", style=discord.ButtonStyle.danger, row=2)
    async def clear_all_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cur_pl = self.studio_view.get_current_playlist()
        cnt = len(cur_pl.get("tracks", []))
        if not cnt:
            await core.safe_send_response(interaction, "📭 이미 비어 있는 플레이리스트입니다.", ephemeral=True)
            return
        await core.safe_send_response(
            interaction,
            f"⚠️ 정말 **`{cur_pl.get('name')}`**의 수록곡 **{cnt}곡**을 모두 비우시겠어요? (되돌릴 수 없습니다)",
            view=PlaylistClearConfirmView(self.studio_view, parent_message=self.parent_message),
            ephemeral=True
        )


class PlaylistTrackDetailView(core.SafeView):
    """플레이리스트 내 개별 곡 선택 시: 3대 플랫폼 바로 듣기 + 이 곡부터 음성채널 재생 + 순번 이동(⬆️/⬇️/⏫) + 삭제 뷰"""
    def __init__(self, track: dict, owner_id: int, playlist_id: str, parent_studio: Optional["PlaylistStudioView"] = None, parent_message: Optional[discord.Message] = None):
        super().__init__(timeout=600)
        self.track = core.normalize_playlist_track(track)
        self.owner_id = owner_id
        self.playlist_id = playlist_id
        self.parent_studio = parent_studio
        self.parent_message = parent_message

        # Row 0: 유튜브 / 스포티파이 / 사운드클라우드 3사 바로 듣기 링크 버튼
        self.add_item(discord.ui.Button(
            label="📺 YouTube에서 듣기",
            url=self.track["yt_url"],
            style=discord.ButtonStyle.link,
            row=0
        ))
        self.add_item(discord.ui.Button(
            label="🟢 Spotify에서 듣기",
            url=self.track["sp_url"],
            style=discord.ButtonStyle.link,
            row=0
        ))
        self.add_item(discord.ui.Button(
            label="☁️ SoundCloud에서 듣기",
            url=self.track["sc_url"],
            style=discord.ButtonStyle.link,
            row=0
        ))

        if parent_studio is None:
            self.remove_item(self.move_top_btn)
            self.remove_item(self.move_up_btn)
            self.remove_item(self.move_down_btn)
            self.remove_item(self.delete_track_btn)

    def _get_track_position_info(self) -> tuple[int, int]:
        if not self.parent_studio:
            return 0, 0
        tracks = self.parent_studio.get_current_playlist().get("tracks", [])
        idx = next((i for i, t in enumerate(tracks) if t.get("id") == self.track.get("id")), -1)
        return idx + 1, len(tracks)

    def build_embed(self) -> discord.Embed:
        plat = self.track.get("platform", "YouTube")
        p_meta = core.PLAYLIST_PLATFORMS.get(plat, core.PLAYLIST_PLATFORMS["YouTube"])
        r, g, b = p_meta["color"]
        pos_num, total_num = self._get_track_position_info()
        pos_line = f"\n🔢 **현재 재생 순번:** **`#{pos_num:02d}번`** / 총 `{total_num}곡`" if pos_num > 0 else ""
        memo_line = f"\n💬 **코멘트:** `\"{self.track['memo']}\"`" if self.track.get("memo") else ""
        embed = discord.Embed(
            title=f"{p_meta['emoji']} {self.track['title']}",
            description=(
                f"🎤 **아티스트:** `{self.track['artist']}`\n"
                f"🌐 **등록 플랫폼:** `{p_meta['label']}`"
                f"{pos_line}{memo_line}\n\n"
                f"🔗 **원클릭 멀티 플랫폼 바로가기:**\n"
                f"└ [📺 유튜브 바로가기]({self.track['yt_url']}) · [🟢 스포티파이 바로가기]({self.track['sp_url']}) · [☁️ 사운드클라우드 바로가기]({self.track['sc_url']})"
            ),
            color=discord.Color.from_rgb(r, g, b),
            url=self.track["url"],
            timestamp=datetime.datetime.now(core.KST)
        )
        if self.track.get("image"):
            embed.set_thumbnail(url=self.track["image"])
        embed.set_footer(text=f"수록일: {self.track.get('added_at', '-')[:10]} • [🔊 이 곡부터 음성채널 재생] 또는 순번 이동(⬆️/⬇️) 가능!")
        return embed

    @discord.ui.button(label="🔊 이 순번부터 음성채널 재생", style=discord.ButtonStyle.success, row=1)
    async def play_from_here_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, self.owner_id)
        pls = core.ensure_user_playlists(prof)
        target_pl = next((p for p in pls if p["id"] == self.playlist_id), pls[0])
        tracks = target_pl.get("tracks", [])
        start_idx = next((i for i, t in enumerate(tracks) if t.get("id") == self.track.get("id")), 0)
        owner_user = self.parent_studio.owner if self.parent_studio else interaction.user
        await start_voice_playlist_from_interaction(interaction, owner_user, target_pl, start_index=start_idx)

    async def _shift_track(self, interaction: discord.Interaction, mode: str):
        if interaction.user.id != self.owner_id:
            await core.safe_send_response(interaction, "❌ 플레이리스트 소유자 본인만 순번을 조정할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, self.owner_id, interaction.user.display_name)
        pls = core.ensure_user_playlists(prof, interaction.user.display_name)
        target_pl = next((p for p in pls if p["id"] == self.playlist_id), pls[0])
        tracks = target_pl.get("tracks", [])
        idx = next((i for i, t in enumerate(tracks) if t.get("id") == self.track.get("id")), -1)
        if idx < 0:
            await interaction.followup.send("❌ 해당 곡을 찾을 수 없습니다.", ephemeral=True)
            return

        if mode == "top":
            new_idx = 0
        elif mode == "up":
            new_idx = max(0, idx - 1)
        else:
            new_idx = min(len(tracks) - 1, idx + 1)

        item = tracks.pop(idx)
        tracks.insert(new_idx, item)
        target_pl["updated_at"] = core.get_today_str()
        await asyncio.to_thread(core.save_data, data)

        if self.parent_studio:
            self.parent_studio.data = data
            self.parent_studio.current_page = new_idx // self.parent_studio.items_per_page
            if self.parent_message:
                try:
                    await self.parent_message.edit(embed=self.parent_studio.build_embed(), view=self.parent_studio)
                except Exception:
                    pass

        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="⏫ 1번(맨 위)으로", style=discord.ButtonStyle.secondary, row=1)
    async def move_top_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._shift_track(interaction, "top")

    @discord.ui.button(label="⬆️ 위로", style=discord.ButtonStyle.secondary, row=1)
    async def move_up_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._shift_track(interaction, "up")

    @discord.ui.button(label="⬇️ 아래로", style=discord.ButtonStyle.secondary, row=1)
    async def move_down_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._shift_track(interaction, "down")

    @discord.ui.button(label="🗑️ 삭제", style=discord.ButtonStyle.danger, row=1)
    async def delete_track_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await core.safe_send_response(interaction, "❌ 플레이리스트 소유자 본인만 곡을 삭제할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        profile = core.ensure_user_profile(data, self.owner_id, interaction.user.display_name)
        pls = core.ensure_user_playlists(profile, interaction.user.display_name)
        target_pl = next((p for p in pls if p["id"] == self.playlist_id), pls[0])

        before_len = len(target_pl["tracks"])
        target_pl["tracks"] = [t for t in target_pl["tracks"] if t.get("id") != self.track.get("id")]
        if len(target_pl["tracks"]) == before_len:
            await interaction.followup.send("ℹ️ 이미 삭제된 곡입니다.", ephemeral=True)
            return

        target_pl["updated_at"] = core.get_today_str()
        await asyncio.to_thread(core.save_data, data)

        self.delete_track_btn.disabled = True
        self.delete_track_btn.label = "🗑️ 삭제됨"
        await interaction.edit_original_response(view=self)

        if self.parent_studio:
            self.parent_studio.data = data
            if self.parent_studio.current_page > self.parent_studio.max_page:
                self.parent_studio.current_page = self.parent_studio.max_page
            if self.parent_message:
                try:
                    await self.parent_message.edit(embed=self.parent_studio.build_embed(), view=self.parent_studio)
                except Exception:
                    pass

        await interaction.followup.send(f"✅ **`{self.track.get('title')}`** 곡을 플레이리스트에서 삭제했습니다!", ephemeral=True)


class ImportLikedMusicView(core.SafeView):
    """내 음악보관함(하트 누른 곡)에서 원하는 곡들을 골라 플레이리스트로 한 번에 가져오는 뷰"""
    def __init__(self, studio_view: "PlaylistStudioView", liked_music: list, parent_message: Optional[discord.Message] = None):
        super().__init__(timeout=300)
        self.studio_view = studio_view
        self.liked_music = list(reversed(liked_music))[:25]
        self.parent_message = parent_message

        opts = []
        for idx, m in enumerate(self.liked_music, start=1):
            title = str(m.get("title", "제목 없음"))[:60]
            artist = str(m.get("artist", "-"))[:35]
            plat = str(m.get("platform", "Spotify"))
            opts.append(discord.SelectOption(
                label=f"{idx}. {title}"[:95],
                value=str(idx - 1),
                description=f"{artist} · {plat}"[:95],
                emoji="❤️"
            ))
        self.import_select.options = opts
        self.import_select.max_values = min(10, len(opts))

    @discord.ui.select(placeholder="❤️ 플레이리스트에 담을 보관함 곡을 선택하세요 (최대 10곡 동시 선택)...", min_values=1, max_values=1, row=0)
    async def import_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(self.studio_view.owner.id)
        profile = core.ensure_user_profile(data, u_key, self.studio_view.owner.display_name)
        pls = core.ensure_user_playlists(profile, self.studio_view.owner.display_name)
        target_pl = next((p for p in pls if p["id"] == self.studio_view.current_pl_id), pls[0])

        added_cnt = 0
        for idx_str in select.values:
            idx = int(idx_str)
            if 0 <= idx < len(self.liked_music):
                src = self.liked_music[idx]
                plat = _parse_platform_input(src.get("platform", ""), target_pl.get("platform", "Spotify"))
                norm_t = core.normalize_playlist_track({
                    "title": src.get("title", "제목 없음"),
                    "artist": src.get("artist", "아티스트 미지정"),
                    "platform": plat,
                    "url": src.get("url", ""),
                    "image": src.get("image"),
                    "memo": "❤️ 내 음악보관함에서 가져온 곡",
                })
                if not any(t.get("title") == norm_t["title"] and t.get("artist") == norm_t["artist"] for t in target_pl["tracks"]):
                    target_pl["tracks"].append(norm_t)
                    added_cnt += 1

        target_pl["updated_at"] = core.get_today_str()
        await asyncio.to_thread(core.save_data, data)
        self.studio_view.data = data

        if self.parent_message:
            try:
                await self.parent_message.edit(embed=self.studio_view.build_embed(), view=self.studio_view)
            except Exception:
                pass

        await interaction.edit_original_response(
            content=f"✅ 선택한 곡 중 **`{added_cnt}곡`**을 **`{target_pl['emoji']} {target_pl['name']}`** 플레이리스트에 담았습니다!",
            view=None
        )


class SharedPlaylistView(core.SafeView):
    """
    [공유하기] 버튼 클릭 시 채널에 전송되는 공개 플레이리스트 쇼케이스 뷰.
    서버 멤버 누구나 페이지를 넘기며 감상하고, [🔊 음성채널 순차 자동재생]으로 함께 듣거나,
    플랫폼(유튜브/스포티파이/사운드클라우드) 전환, 좋아요(❤️), 내 플레이리스트로 스크랩(📥)할 수 있습니다.
    """
    def __init__(self, owner: discord.User, playlist_data: dict, items_per_page: int = 5):
        super().__init__(timeout=3600)
        self.owner = owner
        self.playlist = copy.deepcopy(playlist_data)
        self.display_platform = self.playlist.get("platform", "YouTube")
        if self.display_platform not in core.PLAYLIST_PLATFORMS:
            self.display_platform = "YouTube"
        self.items_per_page = items_per_page
        self.current_page = 0
        self.update_components()

    @property
    def max_page(self) -> int:
        tracks = self.playlist.get("tracks", [])
        if not tracks:
            return 0
        return (len(tracks) - 1) // self.items_per_page

    def get_page_tracks(self) -> list:
        tracks = self.playlist.get("tracks", [])
        start = self.current_page * self.items_per_page
        return tracks[start:start + self.items_per_page]

    def update_components(self):
        tracks = self.playlist.get("tracks", [])
        self.prev_btn.disabled = (self.current_page <= 0)
        self.next_btn.disabled = (self.current_page >= self.max_page)
        self.page_btn.label = f"📄 {self.current_page + 1} / {self.max_page + 1}"
        self.shuffle_btn.disabled = (len(tracks) == 0)
        self.voice_play_shared_btn.disabled = (len(tracks) == 0)

        p_meta = core.PLAYLIST_PLATFORMS.get(self.display_platform, core.PLAYLIST_PLATFORMS["YouTube"])
        self.platform_view_btn.label = f"🌐 듣기 플랫폼: {p_meta['short']}"
        self.platform_view_btn.emoji = p_meta["emoji"]

        likes_cnt = len(self.playlist.get("likes", []))
        self.like_pl_btn.label = f"좋아요 ({likes_cnt})"

        page_tracks = self.get_page_tracks()
        if not page_tracks:
            self.track_select.options = [discord.SelectOption(label="수록된 곡이 없습니다", value="NONE")]
            self.track_select.disabled = True
        else:
            opts = []
            start_idx = self.current_page * self.items_per_page
            for idx, t in enumerate(page_tracks, start=start_idx + 1):
                t_plat = t.get("platform", "YouTube")
                t_emoji = core.PLAYLIST_PLATFORMS.get(t_plat, core.PLAYLIST_PLATFORMS["YouTube"])["emoji"]
                label = f"{idx:02d}. {t.get('title', '제목 없음')}"[:95]
                desc = f"{t.get('artist', '-')} · 이 순번부터 음성채널 재생 또는 링크 듣기"[:95]
                opts.append(discord.SelectOption(label=label, value=str(t.get("id")), description=desc, emoji=t_emoji))
            self.track_select.options = opts
            self.track_select.disabled = False

    def build_embed(self) -> discord.Embed:
        self.update_components()
        tracks = self.playlist.get("tracks", [])
        p_meta = core.PLAYLIST_PLATFORMS.get(self.display_platform, core.PLAYLIST_PLATFORMS["YouTube"])
        r, g, b = p_meta["color"]
        likes_cnt = len(self.playlist.get("likes", []))
        share_cnt = int(self.playlist.get("share_count", 1))

        embed = discord.Embed(
            title=f"📢 {self.playlist.get('emoji', '🎧')} [{self.owner.display_name}님의 공유 플리] {self.playlist.get('name', '플레이리스트')}",
            description=(
                f"> 💬 *\"{self.playlist.get('desc', '함께 듣고 싶은 나만의 음악 플레이리스트 ✨')}\"*\n\n"
                f"• 👤 **제작자:** {self.owner.mention}  |  ❤️ **추천수:** **`{likes_cnt:,}개`** (공유 `{share_cnt:,}회`)\n"
                f"• 🌐 **현재 선택 플랫폼:** **{p_meta['label']}** *(하단 버튼으로 유튜브·스포티파이·사클 전환 가능)*\n"
                f"• 💿 **총 수록곡:** **`{len(tracks):,}곡`** *(하단 **[🔊 음성채널 자동재생]** 클릭 시 1번부터 순차 재생!)*"
            ),
            color=discord.Color.from_rgb(r, g, b),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_author(name=f"{self.owner.display_name}님의 뮤직 쇼케이스", icon_url=self.owner.display_avatar.url)

        page_tracks = self.get_page_tracks()
        if not page_tracks:
            embed.add_field(name="📭 수록곡 없음", value="아직 플레이리스트에 담긴 곡이 없습니다.", inline=False)
        else:
            start_idx = self.current_page * self.items_per_page
            lines = []
            for idx, raw_t in enumerate(page_tracks, start=start_idx + 1):
                t = core.normalize_playlist_track(raw_t)
                orig_emoji = core.PLAYLIST_PLATFORMS.get(t["platform"], core.PLAYLIST_PLATFORMS["YouTube"])["emoji"]
                active_url = _get_track_url_for_platform(t, self.display_platform)
                memo_str = f"\n   └ 💬 *\"{t['memo']}\"*" if t.get("memo") else ""
                lines.append(
                    f"**`#{idx:02d}.`** {orig_emoji} **[{t['title']}]({active_url})** — `{t['artist']}`\n"
                    f"   └ 🔗 [📺YouTube]({t['yt_url']}) · [🟢Spotify]({t['sp_url']}) · [☁️SoundCloud]({t['sc_url']}){memo_str}"
                )
            embed.add_field(
                name=f"🎶 순번별 수록곡 리스트 (페이지 {self.current_page + 1} / {self.max_page + 1})",
                value="\n\n".join(lines)[:1020],
                inline=False
            )
            first_img = next((t.get("image") for t in page_tracks if t.get("image")), None)
            if first_img:
                embed.set_thumbnail(url=first_img)

        embed.set_footer(text="[🔊 음성채널 자동재생]을 누르면 봇이 음성채널로 찾아와 1번 곡부터 순번대로 틀어줍니다!")
        return embed

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="📄 1 / 1", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = min(self.max_page, self.current_page + 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🌐 듣기 플랫폼: YouTube", style=discord.ButtonStyle.primary, row=0)
    async def platform_view_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        order = ["YouTube", "Spotify", "SoundCloud"]
        cur_idx = order.index(self.display_platform) if self.display_platform in order else 0
        self.display_platform = order[(cur_idx + 1) % len(order)]
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔀 랜덤 1곡 추천", style=discord.ButtonStyle.secondary, row=0)
    async def shuffle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        tracks = self.playlist.get("tracks", [])
        if not tracks:
            await core.safe_send_response(interaction, "📭 플레이리스트에 수록된 곡이 없습니다.", ephemeral=True)
            return
        chosen = random.choice(tracks)
        detail_view = PlaylistTrackDetailView(chosen, self.owner.id, self.playlist.get("id", "pl_default"))
        embed = detail_view.build_embed()
        embed.title = f"🔀 [{self.playlist.get('name')}] 랜덤 추천곡 — {chosen.get('title')}"
        await core.safe_send_response(interaction, embed=embed, view=detail_view, ephemeral=True)

    @discord.ui.select(placeholder="🎧 수록곡 선택 (음성채널 재생 및 3대 플랫폼 바로 듣기)...", row=1, options=[discord.SelectOption(label="곡 선택", value="NONE")])
    async def track_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        if val == "NONE":
            await core.safe_defer(interaction)
            return
        chosen = next((t for t in self.playlist.get("tracks", []) if str(t.get("id")) == val), None)
        if not chosen:
            await core.safe_send_response(interaction, "❌ 선택한 곡 정보를 찾을 수 없습니다.", ephemeral=True)
            return
        detail_view = PlaylistTrackDetailView(chosen, self.owner.id, self.playlist.get("id", "pl_default"))
        await core.safe_send_response(interaction, embed=detail_view.build_embed(), view=detail_view, ephemeral=True)

    @discord.ui.button(label="🔊 음성채널 자동재생", style=discord.ButtonStyle.success, row=2)
    async def voice_play_shared_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await start_voice_playlist_from_interaction(interaction, self.owner, self.playlist, start_index=0)

    @discord.ui.button(label="좋아요 (0)", emoji="❤️", style=discord.ButtonStyle.danger, row=2)
    async def like_pl_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        owner_prof = core.ensure_user_profile(data, self.owner.id, self.owner.display_name)
        pls = core.ensure_user_playlists(owner_prof, self.owner.display_name)
        target_pl = next((p for p in pls if p["id"] == self.playlist.get("id")), None)

        u_str = str(interaction.user.id)
        likes = self.playlist.setdefault("likes", [])
        if u_str in likes:
            likes.remove(u_str)
            action_msg = f"💔 **{self.playlist.get('name')}** 플레이리스트 좋아요를 취소했습니다."
        else:
            likes.append(u_str)
            action_msg = f"❤️ **{self.owner.display_name}**님의 **`{self.playlist.get('name')}`** 플레이리스트에 좋아요를 눌렀습니다!"

        if target_pl is not None:
            target_pl["likes"] = list(likes)
            await asyncio.to_thread(core.save_data, data)

        await interaction.edit_original_response(embed=self.build_embed(), view=self)
        await interaction.followup.send(action_msg, ephemeral=True)

    @discord.ui.button(label="📥 내 플리로 스크랩", style=discord.ButtonStyle.secondary, row=2)
    async def clone_pl_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.owner.id:
            await core.safe_send_response(interaction, "ℹ️ 본인이 만든 플레이리스트입니다! `/플레이리스트`에서 관리할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        my_prof = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
        my_pls = core.ensure_user_playlists(my_prof, interaction.user.display_name)

        if len(my_pls) >= 20:
            await interaction.followup.send("❌ 내 플레이리스트 슬롯(최대 20개)이 가득 찼습니다. `/플레이리스트`에서 안 쓰는 플리를 정리해 주세요.", ephemeral=True)
            return

        today_s = core.get_today_str()
        cloned_pl = {
            "id": f"pl_{int(time.time())}_{random.randint(100, 999)}",
            "name": f"[{self.owner.display_name}] {self.playlist.get('name', '공유 플리')}"[:50],
            "desc": self.playlist.get("desc", "공유받은 플레이리스트 ✨"),
            "emoji": self.playlist.get("emoji", "🎧"),
            "platform": self.playlist.get("platform", "YouTube"),
            "tracks": copy.deepcopy(self.playlist.get("tracks", [])),
            "likes": [],
            "share_count": 0,
            "created_at": today_s,
            "updated_at": today_s,
        }
        my_pls.append(cloned_pl)
        await asyncio.to_thread(core.save_data, data)

        await interaction.followup.send(
            f"📥 **{self.owner.display_name}**님의 **`{self.playlist.get('name')}`** 플레이리스트(`{len(cloned_pl['tracks'])}곡`)를 내 보관함으로 통째로 복사했습니다!\n"
            f"👉 `/플레이리스트` 명령어를 입력하거나 옆의 **`[🛠️ 나도 플리 만들기]`** 버튼을 눌러 확인해 보세요!",
            ephemeral=True
        )

    @discord.ui.button(label="🛠️ 나도 플리 만들기", style=discord.ButtonStyle.primary, row=2)
    async def open_my_studio_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        studio = PlaylistStudioView(interaction.user, interaction.user, data)
        await interaction.followup.send(embed=studio.build_embed(), view=studio, ephemeral=True)


class PlaylistStudioView(core.SafeView):
    """
    이용자가 직접 디스코드 봇 내에서 플레이리스트를 생성·편집하고,
    플랫폼(유튜브 / 스포티파이 / 사운드클라우드)을 선택해 곡을 담으며,
    [🔊 음성채널 순차 자동재생] 및 [📢 채널에 공유하기]를 실행할 수 있는 올인원 스튜디오 뷰
    """
    def __init__(self, viewer: discord.User, owner: discord.User, data: dict, initial_pl_id: Optional[str] = None, items_per_page: int = 5):
        super().__init__(timeout=600)
        self.viewer = viewer
        self.owner = owner
        self.is_owner = (viewer.id == owner.id)
        self.data = data
        self.items_per_page = items_per_page
        self.current_page = 0

        pls = self.get_playlists()
        if initial_pl_id and any(p["id"] == initial_pl_id for p in pls):
            self.current_pl_id = initial_pl_id
        else:
            self.current_pl_id = pls[0]["id"]

        self.update_components()

    def get_playlists(self) -> list:
        profile = core.ensure_user_profile(self.data, self.owner.id, self.owner.display_name)
        return core.ensure_user_playlists(profile, self.owner.display_name)

    def get_current_playlist(self) -> dict:
        pls = self.get_playlists()
        found = next((p for p in pls if p["id"] == self.current_pl_id), None)
        if not found:
            self.current_pl_id = pls[0]["id"]
            return pls[0]
        return found

    @property
    def max_page(self) -> int:
        tracks = self.get_current_playlist().get("tracks", [])
        if not tracks:
            return 0
        return (len(tracks) - 1) // self.items_per_page

    def get_page_tracks(self) -> list:
        tracks = self.get_current_playlist().get("tracks", [])
        start = self.current_page * self.items_per_page
        return tracks[start:start + self.items_per_page]

    def update_components(self):
        pls = self.get_playlists()
        cur_pl = self.get_current_playlist()
        tracks = cur_pl.get("tracks", [])
        plat = cur_pl.get("platform", "YouTube")
        p_meta = core.PLAYLIST_PLATFORMS.get(plat, core.PLAYLIST_PLATFORMS["YouTube"])

        self.prev_btn.disabled = (self.current_page <= 0)
        self.next_btn.disabled = (self.current_page >= self.max_page)
        self.page_btn.label = f"📄 {self.current_page + 1} / {self.max_page + 1}"
        self.shuffle_btn.disabled = (len(tracks) == 0)
        self.voice_autoplay_btn.disabled = (len(tracks) == 0)

        self.platform_cycle_btn.label = f"플랫폼: {p_meta['short']}"
        self.platform_cycle_btn.emoji = p_meta["emoji"]

        # Row 1: 플레이리스트 선택 드롭다운
        pl_opts = []
        for idx, p in enumerate(pls[:25], start=1):
            p_cnt = len(p.get("tracks", []))
            p_plat = p.get("platform", "YouTube")
            is_sel = (p["id"] == cur_pl["id"])
            pl_opts.append(discord.SelectOption(
                label=f"{idx}. {p.get('name', '플레이리스트')} ({p_cnt}곡)"[:95],
                value=str(p["id"]),
                description=f"기본 플랫폼: {p_plat} | {p.get('desc', '')}"[:95],
                emoji=p.get("emoji", "🎧"),
                default=is_sel
            ))
        self.playlist_select.options = pl_opts
        self.playlist_select.placeholder = f"📁 플레이리스트 전환 (현재: {cur_pl.get('name')} · 총 {len(pls)}개)..."

        # Row 2: 수록곡 선택 드롭다운
        page_tracks = self.get_page_tracks()
        if not page_tracks:
            self.track_select.options = [discord.SelectOption(label="수록된 곡이 없습니다 — 아래 [➕ 곡 추가] 버튼을 눌러보세요!", value="NONE")]
            self.track_select.disabled = True
        else:
            t_opts = []
            start_idx = self.current_page * self.items_per_page
            for idx, t in enumerate(page_tracks, start=start_idx + 1):
                t_plat = t.get("platform", "YouTube")
                t_emoji = core.PLAYLIST_PLATFORMS.get(t_plat, core.PLAYLIST_PLATFORMS["YouTube"])["emoji"]
                t_opts.append(discord.SelectOption(
                    label=f"#{idx:02d}. {t.get('title', '제목 없음')}"[:95],
                    value=str(t.get("id")),
                    description=f"{t.get('artist', '-')} · 이 순번부터 재생 / 순번 변경(⬆️⬇️) / 삭제"[:95],
                    emoji=t_emoji
                ))
            self.track_select.options = t_opts
            self.track_select.disabled = False

        # 소유자 여부에 따른 편집 버튼 제어
        self.add_track_btn.label = f"➕ 곡 추가 ({p_meta['short']})"
        self.add_track_btn.disabled = not self.is_owner
        self.import_liked_btn.disabled = not self.is_owner
        self.create_pl_btn.disabled = not self.is_owner
        self.edit_pl_btn.disabled = not self.is_owner
        self.delete_pl_btn.disabled = (not self.is_owner) or (len(pls) <= 1 and len(tracks) == 0)
        self.convenience_tools_btn.disabled = not self.is_owner
        self.import_url_btn.disabled = not self.is_owner
        self.delete_tracks_btn.disabled = (not self.is_owner) or (len(tracks) == 0)

    def build_embed(self) -> discord.Embed:
        self.update_components()
        pls = self.get_playlists()
        cur_pl = self.get_current_playlist()
        tracks = cur_pl.get("tracks", [])
        plat = cur_pl.get("platform", "YouTube")
        p_meta = core.PLAYLIST_PLATFORMS.get(plat, core.PLAYLIST_PLATFORMS["YouTube"])
        r, g, b = p_meta["color"]
        likes_cnt = len(cur_pl.get("likes", []))
        share_cnt = int(cur_pl.get("share_count", 0))

        embed = discord.Embed(
            title=f"{cur_pl.get('emoji', '🎧')} {self.owner.display_name}님의 플레이리스트 — {cur_pl.get('name')}",
            description=(
                f"> 💬 *\"{cur_pl.get('desc', '나만의 감성 음악 플레이리스트 ✨')}\"*\n\n"
                f"• 🌐 **선택된 스트리밍 플랫폼:** **{p_meta['label']}**\n"
                f"• 💿 **수록곡 수:** **`{len(tracks):,} / 100곡`**  |  📁 **보유 플리:** `{len(pls)} / 20개`\n"
                f"• ❤️ **받은 좋아요:** `{likes_cnt:,}개`  |  📢 **공유 횟수:** `{share_cnt:,}회`\n"
                f"• 🔊 **음성채널 자동실행:** 하단 **`[🔊 음성채널 순차 자동재생]`** 클릭 시 `#01번`부터 순서대로 재생!"
            ),
            color=discord.Color.from_rgb(r, g, b),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_author(name=f"{self.owner.display_name}님의 뮤직 스튜디오", icon_url=self.owner.display_avatar.url)

        page_tracks = self.get_page_tracks()
        if not page_tracks:
            embed.add_field(
                name="📭 아직 수록된 곡이 없습니다!",
                value=(
                    "1️⃣ 상단 **`[🌐 플랫폼]`** 버튼으로 **유튜브 / 스포티파이 / 사운드클라우드** 중 원하는 플랫폼을 고르세요.\n"
                    "2️⃣ 아래 **`[➕ 곡 추가]`** 또는 **`[🔗 플리 링크 가져오기]`**로 링크를 넣어 수록곡을 한 번에 담으세요!\n"
                    "3️⃣ 음성채널에 입장한 뒤 **`[🔊 음성채널 순차 자동재생]`**을 누르면 1번 곡부터 자동 실행됩니다!"
                ),
                inline=False
            )
        else:
            start_idx = self.current_page * self.items_per_page
            lines = []
            for idx, raw_t in enumerate(page_tracks, start=start_idx + 1):
                t = core.normalize_playlist_track(raw_t)
                orig_emoji = core.PLAYLIST_PLATFORMS.get(t["platform"], core.PLAYLIST_PLATFORMS["YouTube"])["emoji"]
                active_url = _get_track_url_for_platform(t, plat)
                memo_str = f"\n   └ 💬 *\"{t['memo']}\"*" if t.get("memo") else ""
                lines.append(
                    f"**`#{idx:02d}.`** {orig_emoji} **[{t['title']}]({active_url})** — `{t['artist']}`\n"
                    f"   └ 🔗 [📺YouTube]({t['yt_url']}) · [🟢Spotify]({t['sp_url']}) · [☁️SoundCloud]({t['sc_url']}){memo_str}"
                )
            field_text = ""
            for entry_line in lines:
                if len(field_text) + len(entry_line) + 2 > 1020:
                    field_text += "\n*(이하 생략...)*"
                    break
                field_text = f"{field_text}\n\n{entry_line}".strip() if field_text else entry_line

            embed.add_field(
                name=f"🎶 자동재생 순번별 수록곡 목록 (페이지 {self.current_page + 1} / {self.max_page + 1})",
                value=field_text or "수록곡을 불러올 수 없습니다.",
                inline=False
            )
            first_img = next((t.get("image") for t in page_tracks if t.get("image")), None)
            if first_img:
                embed.set_thumbnail(url=first_img)

        embed.set_footer(text="[🔊 음성채널 순차 자동재생]으로 보이스룸에서 함께 감상하거나 [⚙️ 순번·편의기능]에서 순서를 조정해 보세요!")
        return embed

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="📄 1 / 1", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = min(self.max_page, self.current_page + 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="플랫폼: YouTube", emoji="📺", style=discord.ButtonStyle.primary, row=0)
    async def platform_cycle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        order = ["YouTube", "Spotify", "SoundCloud"]
        cur_pl = self.get_current_playlist()
        cur_plat = cur_pl.get("platform", "YouTube")
        next_plat = order[(order.index(cur_plat) + 1) % len(order)] if cur_plat in order else "YouTube"
        cur_pl["platform"] = next_plat

        try:
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=self.build_embed(), view=self)
            else:
                await interaction.edit_original_response(embed=self.build_embed(), view=self)
        except Exception:
            pass

        if interaction.user.id == self.owner.id:
            async def _bg_save():
                try:
                    data = await asyncio.to_thread(core.load_data)
                    prof = core.ensure_user_profile(data, self.owner.id, self.owner.display_name)
                    pls = core.ensure_user_playlists(prof, self.owner.display_name)
                    target = next((p for p in pls if p["id"] == self.current_pl_id), pls[0] if pls else None)
                    if target:
                        target["platform"] = next_plat
                    await asyncio.to_thread(core.save_data, data)
                    self.data = data
                except Exception as e:
                    logger.warning(f"플랫폼 변경 비동기 저장 중 예외 발생: {e}")
            asyncio.create_task(_bg_save())

    @discord.ui.button(label="🔀 랜덤 선곡", style=discord.ButtonStyle.secondary, row=0)
    async def shuffle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cur_pl = self.get_current_playlist()
        tracks = cur_pl.get("tracks", [])
        if not tracks:
            await core.safe_send_response(interaction, "📭 플레이리스트에 수록된 곡이 없습니다.", ephemeral=True)
            return
        chosen = random.choice(tracks)
        detail_view = PlaylistTrackDetailView(
            chosen,
            self.owner.id,
            cur_pl["id"],
            parent_studio=self if interaction.user.id == self.owner.id else None,
            parent_message=interaction.message
        )
        embed = detail_view.build_embed()
        embed.title = f"🔀 [{cur_pl.get('name')}] 랜덤 선곡 — {chosen.get('title')}"
        await core.safe_send_response(interaction, embed=embed, view=detail_view, ephemeral=True)

    @discord.ui.select(placeholder="📁 내 플레이리스트 전환...", row=1, options=[discord.SelectOption(label="기본 플레이리스트", value="pl_default")])
    async def playlist_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        if val == "NONE":
            await core.safe_defer(interaction)
            return
        pls = self.get_playlists()
        if any(p["id"] == val for p in pls):
            self.current_pl_id = val
        else:
            self.current_pl_id = pls[0]["id"]
        self.current_page = 0
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.select(placeholder="🎵 수록곡 선택 (이 순번부터 음성채널 재생 / 순번 변경 / 삭제)...", row=2, options=[discord.SelectOption(label="수록곡 없음", value="NONE")])
    async def track_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        if val == "NONE":
            await core.safe_defer(interaction)
            return
        cur_pl = self.get_current_playlist()
        chosen = next((t for t in cur_pl.get("tracks", []) if str(t.get("id")) == val), None)
        if not chosen:
            await core.safe_send_response(interaction, "❌ 선택한 곡을 찾을 수 없습니다.", ephemeral=True)
            return
        detail_view = PlaylistTrackDetailView(
            chosen,
            self.owner.id,
            cur_pl["id"],
            parent_studio=self if interaction.user.id == self.owner.id else None,
            parent_message=interaction.message
        )
        await core.safe_send_response(interaction, embed=detail_view.build_embed(), view=detail_view, ephemeral=True)

    @discord.ui.button(label="➕ 곡 추가", style=discord.ButtonStyle.primary, row=3)
    async def add_track_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner.id:
            await core.safe_send_response(interaction, "❌ 플레이리스트 소유자 본인만 곡을 추가할 수 있습니다.", ephemeral=True)
            return
        self.message = interaction.message
        await interaction.response.send_modal(PlaylistAddTrackModal(self, parent_message=interaction.message))

    @discord.ui.button(label="❤️ 보관함 곡 담기", style=discord.ButtonStyle.secondary, row=3)
    async def import_liked_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner.id:
            await core.safe_send_response(interaction, "❌ 플레이리스트 소유자 본인만 이용할 수 있습니다.", ephemeral=True)
            return
        self.message = interaction.message
        data = await asyncio.to_thread(core.load_data)
        self.data = data
        liked = data.get("user_profiles", {}).get(str(self.owner.id), {}).get("liked_music", [])
        if not liked:
            await core.safe_send_response(
                interaction,
                "📭 아직 `/내음악보관함`에 하트(❤️)를 눌러 저장한 곡이 없습니다!\n"
                "`/음악지금추천`에서 마음에 드는 곡에 `❤️ 보관함에 담기`를 누르거나 **`[➕ 곡 추가]`** 버튼으로 직접 곡을 추가해 보세요.",
                ephemeral=True
            )
            return
        imp_view = ImportLikedMusicView(self, liked, parent_message=interaction.message)
        await core.safe_send_response(
            interaction,
            "❤️ **내 음악보관함**에서 현재 플레이리스트로 가져올 곡들을 선택해 주세요 (최대 10곡 동시 선택 가능):",
            view=imp_view,
            ephemeral=True
        )

    @discord.ui.button(label="📁 새 플리", style=discord.ButtonStyle.secondary, row=3)
    async def create_pl_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner.id:
            await core.safe_send_response(interaction, "❌ 본인만 새 플레이리스트를 만들 수 있습니다.", ephemeral=True)
            return
        self.message = interaction.message
        await interaction.response.send_modal(PlaylistCreateEditModal(self, is_edit=False, parent_message=interaction.message))

    @discord.ui.button(label="✏️ 플리 수정", style=discord.ButtonStyle.secondary, row=3)
    async def edit_pl_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner.id:
            await core.safe_send_response(interaction, "❌ 플레이리스트 소유자 본인만 수정할 수 있습니다.", ephemeral=True)
            return
        self.message = interaction.message
        await interaction.response.send_modal(PlaylistCreateEditModal(self, is_edit=True, parent_message=interaction.message))

    @discord.ui.button(label="🗑️ 플리 삭제", style=discord.ButtonStyle.danger, row=3)
    async def delete_pl_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner.id:
            await core.safe_send_response(interaction, "❌ 플레이리스트 소유자 본인만 삭제할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, self.owner.id, self.owner.display_name)
        pls = core.ensure_user_playlists(prof, self.owner.display_name)
        cur_pl = next((p for p in pls if p["id"] == self.current_pl_id), pls[0])
        deleted_name = cur_pl.get("name", "플레이리스트")

        if len(pls) <= 1:
            pls[0]["tracks"] = []
            pls[0]["name"] = "나만의 대표 플레이리스트"
            pls[0]["desc"] = "좋아하는 유튜브·스포티파이·사운드클라우드 곡들을 모아둔 리스트입니다 ✨"
            pls[0]["updated_at"] = core.get_today_str()
            self.current_pl_id = pls[0]["id"]
        else:
            prof["playlists"] = [p for p in pls if p["id"] != self.current_pl_id]
            self.current_pl_id = prof["playlists"][0]["id"]

        self.current_page = 0
        await asyncio.to_thread(core.save_data, data)
        self.data = data
        await interaction.edit_original_response(embed=self.build_embed(), view=self)
        await interaction.followup.send(f"🗑️ **`{deleted_name}`** 플레이리스트를 정리했습니다.", ephemeral=True)

    # Row 4: 음성채널 순차 자동재생 & 채널 공유 & 순번/편의기능 & 음성리모컨
    @discord.ui.button(label="🔊 음성채널 순차 자동재생", style=discord.ButtonStyle.success, row=4)
    async def voice_autoplay_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cur_pl = self.get_current_playlist()
        await start_voice_playlist_from_interaction(interaction, self.owner, cur_pl, start_index=0)

    @discord.ui.button(label="📢 채널에 공유하기", style=discord.ButtonStyle.primary, row=4)
    async def share_pl_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, self.owner.id, self.owner.display_name)
        pls = core.ensure_user_playlists(prof, self.owner.display_name)
        cur_pl = next((p for p in pls if p["id"] == self.current_pl_id), pls[0])

        if not cur_pl.get("tracks"):
            await interaction.followup.send(
                "⚠️ 아직 플레이리스트에 담긴 곡이 없습니다! **`[➕ 곡 추가]`** 버튼으로 최소 1곡 이상 담은 뒤 공유해 보세요.",
                ephemeral=True
            )
            return

        cur_pl["share_count"] = int(cur_pl.get("share_count", 0)) + 1
        await asyncio.to_thread(core.save_data, data)
        self.data = data

        shared_view = SharedPlaylistView(self.owner, cur_pl)
        shared_embed = shared_view.build_embed()

        try:
            await interaction.edit_original_response(embed=self.build_embed(), view=self)
        except Exception:
            pass

        if interaction.channel:
            await interaction.channel.send(
                content=f"🎧 {interaction.user.mention}님이 나만의 커스텀 플레이리스트 **`{cur_pl.get('emoji', '🎧')} {cur_pl.get('name')}`**을(를) 공유했습니다!",
                embed=shared_embed,
                view=shared_view
            )
            await interaction.followup.send("✅ 현재 채널에 플레이리스트를 멋지게 공유했습니다!", ephemeral=True)
        else:
            await interaction.followup.send(embed=shared_embed, view=shared_view)

    @discord.ui.button(label="🔗 플리 링크 가져오기", style=discord.ButtonStyle.secondary, row=4)
    async def import_url_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner.id:
            await core.safe_send_response(interaction, "❌ 플레이리스트 소유자 본인만 이용할 수 있습니다.", ephemeral=True)
            return
        self.message = interaction.message
        await interaction.response.send_modal(PlaylistImportUrlModal(self, parent_message=interaction.message))

    @discord.ui.button(label="⚙️ 순번·편의기능", style=discord.ButtonStyle.secondary, row=4)
    async def convenience_tools_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner.id:
            await core.safe_send_response(interaction, "❌ 플레이리스트 소유자 본인만 순번 및 일괄 편집 도구를 사용할 수 있습니다.", ephemeral=True)
            return
        conv_view = PlaylistConvenienceView(self, parent_message=interaction.message)
        await core.safe_send_response(
            interaction,
            "⚙️ **플레이리스트 편의성 도구 모음**\n"
            "• **추가/이동:** `🔢 순번 변경` · `📋 여러 곡 추가` · `🔗 플리 링크로 추가`\n"
            "• **삭제:** `🗑️ 곡 골라서 삭제`(여러 곡 체크) · `🔢 번호로 삭제`(예: `1, 4, 7-10`) · `💣 전체 비우기`\n"
            "• **정렬:** `🔤 제목순` · `🎤 아티스트순` · `🔄 역순` · `🔀 순번 섞기`\n"
            "• **관리:** `🔍 곡 검색` · `🧹 중복 곡 정리` · `📄 플리 복제` · `📃 목록 내보내기(.txt)` · `🎛️ 음성리모컨`",
            view=conv_view,
            ephemeral=True
        )

    @discord.ui.button(label="🗑️ 곡 삭제", style=discord.ButtonStyle.danger, row=4)
    async def delete_tracks_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner.id:
            await core.safe_send_response(interaction, "❌ 플레이리스트 소유자 본인만 곡을 삭제할 수 있습니다.", ephemeral=True)
            return
        if not self.get_current_playlist().get("tracks"):
            await core.safe_send_response(interaction, "📭 삭제할 곡이 없습니다.", ephemeral=True)
            return
        self.message = interaction.message
        del_view = PlaylistTrackDeleteView(self, parent_message=interaction.message)
        await core.safe_send_response(interaction, del_view.build_content(), view=del_view, ephemeral=True)


# ==========================================
# 음악 Cog 명령어 등록
# ==========================================
class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """음성채널에 봇 혼자만 남겨졌을 때 리소스를 아끼고 자동으로 재생을 정리하는 편의 기능"""
        if not member.guild:
            return
        vc = member.guild.voice_client
        if not vc or not vc.is_connected() or not vc.channel:
            return
        # 봇 자신이 강제 퇴장/이동된 경우 또는 채널 내 일반 유저가 0명이 된 경우 체크
        human_cnt = sum(1 for m in vc.channel.members if not m.bot)
        if human_cnt == 0:
            player = _VOICE_PLAYERS.get(member.guild.id)
            if player and player.is_playing_flag:
                await asyncio.sleep(5)
                vc_now = member.guild.voice_client
                if vc_now and vc_now.is_connected() and vc_now.channel:
                    if sum(1 for m in vc_now.channel.members if not m.bot) == 0:
                        ch = player.text_channel
                        await player.stop_and_disconnect()
                        if ch:
                            try:
                                await ch.send("🔇 음성채널에 모든 멤버가 퇴장하여 플레이리스트 자동재생을 마치고 대기 모드로 전환했습니다.")
                            except Exception:
                                pass

    @app_commands.command(name="플레이리스트", description="유튜브·스포티파이·사운드클라우드로 나만의 플레이리스트를 만들고 음성채널 순차 자동재생 및 공유를 실행합니다.")
    @app_commands.autocomplete(플리선택=core.user_playlist_autocomplete)
    @app_commands.describe(
        동작="(선택) 스튜디오 열기 / 음성채널 순차 자동재생 / 곡 추가 / 플리 링크 통째로 가져오기 / 새 플리 생성 / 채널 공유",
        플랫폼="(선택) 기본 스트리밍 플랫폼 선택 (유튜브 / 스포티파이 / 사운드클라우드)",
        플리선택="(선택) 열거나 음성채널에서 재생/추가/공유할 내 플레이리스트 선택",
        곡제목또는링크="(곡 추가/가져오기 시) 곡 제목 또는 유튜브·스포티파이·사클 플리 링크 / (새 플리 생성 시) 플레이리스트 이름",
        아티스트="(빠른 곡 추가 시) 아티스트명 / (새 플리 생성 시) 플레이리스트 한줄 설명",
        유저="(선택) 다른 유저가 만든 플레이리스트를 구경하거나 내 음성채널에서 재생합니다."
    )
    @app_commands.choices(
        동작=[
            app_commands.Choice(name="🧭 내 플레이리스트 스튜디오 열기 (곡 관리·순번·자동재생·공유)", value="studio"),
            app_commands.Choice(name="🔗 링크로 플레이리스트 통째로 가져오기", value="import_url"),
            app_commands.Choice(name="🔊 음성채널에서 플리 1번 곡부터 순번대로 자동재생 시작", value="voice_play"),
            app_commands.Choice(name="🎛️ 현재 음성채널 재생 리모컨/대기열 열기", value="voice_remote"),
            app_commands.Choice(name="⏹️ 음성채널 자동재생 정지 및 퇴장", value="voice_stop"),
            app_commands.Choice(name="➕ 선택한 플레이리스트에 빠른 곡 추가", value="add_track"),
            app_commands.Choice(name="🗑️ 선택한 플레이리스트에서 곡 삭제하기", value="delete_tracks"),
            app_commands.Choice(name="📁 새 플레이리스트 만들기", value="create_pl"),
            app_commands.Choice(name="📢 현재 채널에 내 플레이리스트 바로 공유하기", value="share")
        ],
        플랫폼=[
            app_commands.Choice(name="📺 유튜브 (YouTube)", value="YouTube"),
            app_commands.Choice(name="🟢 스포티파이 (Spotify)", value="Spotify"),
            app_commands.Choice(name="☁️ 사운드클라우드 (SoundCloud)", value="SoundCloud")
        ]
    )
    async def playlist_cmd(
        self,
        interaction: discord.Interaction,
        동작: Optional[app_commands.Choice[str]] = None,
        플랫폼: Optional[app_commands.Choice[str]] = None,
        플리선택: Optional[str] = None,
        곡제목또는링크: Optional[str] = None,
        아티스트: Optional[str] = None,
        유저: Optional[discord.User] = None
    ):
        target_user = 유저 or interaction.user
        mode = 동작.value if 동작 else ("add_track" if 곡제목또는링크 else "studio")

        if mode == "voice_remote":
            if not interaction.guild:
                await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
                return
            player = get_voice_player(self.bot, interaction.guild)
            ctrl_view = VoicePlayerControlView(player)
            await core.safe_send_response(interaction, embed=ctrl_view.build_embed(), view=ctrl_view)
            return

        if mode == "voice_stop":
            if not interaction.guild:
                await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
                return
            await core.safe_defer(interaction)
            player = get_voice_player(self.bot, interaction.guild)
            await player.stop_and_disconnect()
            await interaction.followup.send("⏹️ 음성채널 플레이리스트 자동재생을 정지하고 퇴장했습니다.")
            return

        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, target_user.id, target_user.display_name)
        pls = core.ensure_user_playlists(prof, target_user.display_name)
        selected_pl = next((p for p in pls if p["id"] == 플리선택 or p["name"] == 플리선택), pls[0])

        # 플랫폼 파라미터가 지정된 경우(본인 플리일 때) 즉시 반영
        if 플랫폼 and target_user.id == interaction.user.id:
            selected_pl["platform"] = 플랫폼.value
            await asyncio.to_thread(core.save_data, data)

        if mode == "voice_play":
            await start_voice_playlist_from_interaction(interaction, target_user, selected_pl, start_index=0)
            return

        await core.safe_defer(interaction)

        # 만약 곡제목또는링크가 플레이리스트 링크(YouTube / Spotify / SoundCloud)이거나 동작이 import_url인 경우 자동 처리
        raw_target_str = (곡제목또는링크 or "").strip()
        allow_watch = (mode == "import_url")
        is_pl, pl_plat = core.is_playlist_url(raw_target_str, allow_watch_with_list=allow_watch)
        if (is_pl or mode == "import_url") and target_user.id == interaction.user.id:
            if not raw_target_str:
                await interaction.followup.send("❌ 가져올 플레이리스트 링크(URL)를 `곡제목또는링크`에 입력해 주세요.", ephemeral=True)
                return
            meta, tracks, err = await core.extract_playlist_from_url(raw_target_str, max_tracks=100)
            if err or not tracks:
                await interaction.followup.send(f"❌ 플레이리스트에서 곡을 추출하지 못했습니다: {err or '수록곡 없음'}", ephemeral=True)
                return

            # mode == "add_track" 이거나 플리선택이 지정되어 기존 플리에 담는 경우
            target_pl_id = selected_pl["id"] if (mode == "add_track" and 플리선택) else None
            try:
                target_pl, count, action_msg = core.import_playlist_into_profile_sync(
                    prof,
                    target_user.display_name,
                    meta,
                    tracks,
                    target_pl_id=target_pl_id,
                    custom_name=아티스트 or None
                )
            except Exception as e:
                await interaction.followup.send(f"❌ 플레이리스트 가져오기 실패: {e}", ephemeral=True)
                return

            await asyncio.to_thread(core.save_data, data)
            studio = PlaylistStudioView(interaction.user, target_user, data, initial_pl_id=target_pl["id"])
            embed = studio.build_embed()
            embed.set_author(name=f"🎉 플레이리스트 일괄 가져오기 완료! ({meta['platform']})", icon_url=target_user.display_avatar.url)
            sent_msg = await interaction.followup.send(
                content=f"🎉 **{action_msg}**\n하단의 **`[🔊 음성채널 순차 자동재생]`** 버튼을 눌러 바로 감상하실 수 있습니다 ✨",
                embed=embed,
                view=studio,
                wait=True
            )
            studio.message = sent_msg
            return

        if mode == "create_pl" and target_user.id == interaction.user.id:
            if len(pls) >= 20:
                await interaction.followup.send("❌ 플레이리스트는 1인당 최대 **20개**까지만 만들 수 있습니다.", ephemeral=True)
                return
            if 곡제목또는링크 and 곡제목또는링크.strip():
                today_s = core.get_today_str()
                new_id = f"pl_{int(time.time())}_{random.randint(100, 999)}"
                new_plat = 플랫폼.value if 플랫폼 else "YouTube"
                new_pl = {
                    "id": new_id,
                    "name": 곡제목또는링크.strip()[:50],
                    "desc": (아티스트 or "나만의 감성 음악 플레이리스트 ✨").strip()[:120],
                    "emoji": "🎧",
                    "platform": new_plat,
                    "tracks": [],
                    "likes": [],
                    "share_count": 0,
                    "created_at": today_s,
                    "updated_at": today_s,
                }
                pls.append(new_pl)
                await asyncio.to_thread(core.save_data, data)
                selected_pl = new_pl

        elif mode == "add_track" and target_user.id == interaction.user.id:
            if not 곡제목또는링크 or not 곡제목또는링크.strip():
                studio = PlaylistStudioView(interaction.user, target_user, data, initial_pl_id=selected_pl["id"])
                await interaction.followup.send(
                    "ℹ️ 추가할 곡 제목이 입력되지 않아 플레이리스트 스튜디오를 열었습니다. 아래 **`[➕ 곡 추가]`** 버튼을 눌러보세요!",
                    embed=studio.build_embed(),
                    view=studio
                )
                return
            tracks_list = selected_pl.setdefault("tracks", [])
            if len(tracks_list) >= 100:
                await interaction.followup.send("❌ 하나의 플레이리스트에는 최대 **100곡**까지만 담을 수 있습니다.", ephemeral=True)
                return
            use_plat = 플랫폼.value if 플랫폼 else selected_pl.get("platform", "YouTube")
            resolved = await core.resolve_playlist_track(
                곡제목또는링크.strip(),
                artist_hint=(아티스트 or "").strip(),
                preferred_platform=use_plat
            )
            is_dup = any(_track_matches(resolved, et) for et in tracks_list)
            tracks_list.append(resolved)
            selected_pl["updated_at"] = core.get_today_str()
            await asyncio.to_thread(core.save_data, data)

        elif mode == "delete_tracks" and target_user.id == interaction.user.id:
            tracks = selected_pl.get("tracks", [])
            if not tracks:
                await interaction.followup.send(f"📭 **`{selected_pl['emoji']} {selected_pl['name']}`**에 삭제할 곡이 없습니다.", ephemeral=True)
                return
            if 곡제목또는링크 and 곡제목또는링크.strip():
                raw_in = 곡제목또는링크.strip()
                indices = _parse_index_spec(raw_in, len(tracks))
                if indices:
                    idx_set = set(indices)
                    removed = [t for i, t in enumerate(tracks) if i in idx_set]
                    selected_pl["tracks"] = [t for i, t in enumerate(tracks) if i not in idx_set]
                else:
                    kw = raw_in.lower()
                    removed = []
                    kept = []
                    for t in tracks:
                        if kw in str(t.get("title", "")).lower() or kw in str(t.get("artist", "")).lower() or str(t.get("id")) == kw:
                            removed.append(t)
                        else:
                            kept.append(t)
                    if not removed:
                        await interaction.followup.send(
                            f"❌ **`{selected_pl['name']}`**에서 **`{곡제목또는링크}`**에 해당하는 곡 번호나 제목을 찾지 못했습니다.\n"
                            f"• 번호 입력 예시: `3`, `1, 4, 7`, `10-15`",
                            ephemeral=True
                        )
                        return
                    selected_pl["tracks"] = kept

                selected_pl["updated_at"] = core.get_today_str()
                await asyncio.to_thread(core.save_data, data)
                studio = PlaylistStudioView(interaction.user, target_user, data, initial_pl_id=selected_pl["id"])
                await interaction.followup.send(
                    f"✅ **`{selected_pl['emoji']} {selected_pl['name']}`**에서 **{len(removed)}곡**을 삭제했습니다!\n"
                    f"{_format_removed_preview(removed)}",
                    embed=studio.build_embed(),
                    view=studio
                )
                return
            else:
                studio = PlaylistStudioView(interaction.user, target_user, data, initial_pl_id=selected_pl["id"])
                del_view = PlaylistTrackDeleteView(studio)
                await interaction.followup.send(del_view.build_content(), view=del_view, ephemeral=True)
                return

        elif mode == "share":
            if not selected_pl.get("tracks"):
                studio = PlaylistStudioView(interaction.user, target_user, data, initial_pl_id=selected_pl["id"])
                await interaction.followup.send(
                    "⚠️ 아직 플레이리스트에 담긴 곡이 없습니다! 먼저 **`[➕ 곡 추가]`** 버튼으로 곡을 담은 뒤 공유해 주세요.",
                    embed=studio.build_embed(),
                    view=studio
                )
                return
            selected_pl["share_count"] = int(selected_pl.get("share_count", 0)) + 1
            await asyncio.to_thread(core.save_data, data)
            shared_view = SharedPlaylistView(target_user, selected_pl)
            await interaction.followup.send(
                content=f"🎧 {interaction.user.mention}님이 플레이리스트 **`{selected_pl.get('emoji', '🎧')} {selected_pl.get('name')}`**을(를) 공유했습니다!",
                embed=shared_view.build_embed(),
                view=shared_view
            )
            return

        studio = PlaylistStudioView(interaction.user, target_user, data, initial_pl_id=selected_pl["id"])
        if mode == "add_track" and 곡제목또는링크:
            studio.current_page = max(0, (len(selected_pl["tracks"]) - 1) // studio.items_per_page)
        sent_msg = await interaction.followup.send(embed=studio.build_embed(), view=studio, wait=True)
        studio.message = sent_msg

    @app_commands.command(name="플리가져오기", description="유튜브·스포티파이·사운드클라우드 플레이리스트 링크를 입력하면 통째로 나만의 플레이리스트로 변환합니다.")
    @app_commands.autocomplete(기존플리선택=core.user_playlist_autocomplete)
    @app_commands.describe(
        링크="가져올 유튜브/스포티파이/사운드클라우드 플레이리스트 또는 앨범 링크 (URL)",
        이름="(선택) 새로 생성할 플레이리스트 이름 (미입력 시 원본 플리 제목으로 자동 지정)",
        기존플리선택="(선택) 새 플리 대신 기존에 있던 플레이리스트에 곡들을 이어서 담고 싶을 때 선택"
    )
    async def import_playlist_cmd(
        self,
        interaction: discord.Interaction,
        링크: str,
        이름: Optional[str] = None,
        기존플리선택: Optional[str] = None
    ):
        await core.safe_defer(interaction)
        raw_url = (링크 or "").strip()
        m_u = re.search(r"https?://[^\s<>\"']+", raw_url)
        if m_u:
            raw_url = m_u.group(0)
        if "list=rd" in raw_url.lower():
            await interaction.followup.send(
                "⚠️ 유튜브 자동 생성 믹스/라디오(`&list=RD...`) 링크는 유저 맞춤 임시 목록이어서 외부 일괄 가져오기를 지원하지 않습니다.\n"
                "유튜브 정규 공개 플레이리스트(`https://www.youtube.com/playlist?list=PL...`) 링크를 입력하시거나, 개별 곡 링크로 담아주세요!",
                ephemeral=True
            )
            return

        is_pl, plat = core.is_playlist_url(raw_url, allow_watch_with_list=True)
        if not is_pl:
            await interaction.followup.send(
                "❌ 입력하신 링크가 유효한 **YouTube, Spotify, SoundCloud** 플레이리스트나 앨범 링크가 아닙니다.\n"
                "• 유튜브: `https://www.youtube.com/playlist?list=...` 또는 `&list=...`\n"
                "• 스포티파이: `https://open.spotify.com/playlist/...` 또는 `.../album/...`\n"
                "• 사운드클라우드: `https://soundcloud.com/.../sets/...`",
                ephemeral=True
            )
            return

        meta, tracks, err = await core.extract_playlist_from_url(raw_url, max_tracks=100)
        if err or not tracks:
            await interaction.followup.send(f"❌ 플레이리스트에서 곡을 추출하지 못했습니다: {err or '수록곡 없음'}", ephemeral=True)
            return

        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
        target_pl_id = None
        if 기존플리선택:
            pls = core.ensure_user_playlists(prof, interaction.user.display_name)
            if any(p["id"] == 기존플리선택 for p in pls):
                target_pl_id = 기존플리선택

        try:
            target_pl, count, action_msg = core.import_playlist_into_profile_sync(
                prof,
                interaction.user.display_name,
                meta,
                tracks,
                target_pl_id=target_pl_id,
                custom_name=이름
            )
        except Exception as e:
            await interaction.followup.send(f"❌ 플레이리스트 생성/추가 실패: {e}", ephemeral=True)
            return

        await asyncio.to_thread(core.save_data, data)
        studio = PlaylistStudioView(interaction.user, interaction.user, data, initial_pl_id=target_pl["id"])
        embed = studio.build_embed()
        embed.set_author(name=f"🎉 플레이리스트 일괄 가져오기 완료! ({meta['platform']})", icon_url=interaction.user.display_avatar.url)
        sent = await interaction.followup.send(
            content=f"🎉 **{action_msg}**\n하단의 **`[🔊 음성채널 순차 자동재생]`** 버튼을 눌러 음성채널에서 바로 감상하실 수 있습니다 ✨",
            embed=embed,
            view=studio,
            wait=True
        )
        studio.message = sent

    @app_commands.command(name="플리곡삭제", description="내 플레이리스트에서 원하는 곡을 선택하거나 번호(예: 3 / 1,4,7 / 10-15) 또는 제목으로 삭제합니다.")
    @app_commands.autocomplete(플리선택=core.user_playlist_autocomplete, 곡=core.user_playlist_track_autocomplete)
    @app_commands.describe(
        곡="(선택) 삭제할 곡을 선택하거나 곡 번호(예: 3, 1-5, 1,4,7), 제목 입력 (미입력 시 곡 선택 삭제창 호출)",
        플리선택="(선택) 곡을 삭제할 내 플레이리스트 선택 (기본: 대표 플리)"
    )
    async def delete_playlist_track_cmd(
        self,
        interaction: discord.Interaction,
        곡: Optional[str] = None,
        플리선택: Optional[str] = None
    ):
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
        pls = core.ensure_user_playlists(prof, interaction.user.display_name)
        target_pl = next((p for p in pls if p["id"] == 플리선택 or p["name"] == 플리선택), pls[0])
        tracks = target_pl.get("tracks", [])

        if not tracks:
            await interaction.followup.send(f"📭 **`{target_pl['emoji']} {target_pl['name']}`**에 삭제할 곡이 없습니다.", ephemeral=True)
            return

        studio = PlaylistStudioView(interaction.user, interaction.user, data, initial_pl_id=target_pl["id"])

        if not 곡 or not 곡.strip():
            del_view = PlaylistTrackDeleteView(studio)
            await interaction.followup.send(del_view.build_content(), view=del_view, ephemeral=True)
            return

        raw_in = 곡.strip()
        matched_by_id = [t for t in tracks if str(t.get("id")) == raw_in]
        if matched_by_id:
            removed = matched_by_id
            target_pl["tracks"] = [t for t in tracks if str(t.get("id")) != raw_in]
        else:
            indices = _parse_index_spec(raw_in, len(tracks))
            if indices:
                idx_set = set(indices)
                removed = [t for i, t in enumerate(tracks) if i in idx_set]
                target_pl["tracks"] = [t for i, t in enumerate(tracks) if i not in idx_set]
            else:
                kw = raw_in.lower()
                removed = []
                kept = []
                for t in tracks:
                    if kw in str(t.get("title", "")).lower() or kw in str(t.get("artist", "")).lower():
                        removed.append(t)
                    else:
                        kept.append(t)
                if not removed:
                    await interaction.followup.send(
                        f"❌ **`{target_pl['name']}`**에서 **`{곡}`**에 해당하는 곡 번호나 제목을 찾지 못했습니다.\n"
                        f"• 번호 입력 예시: `3`, `1, 4, 7`, `10-15`\n"
                        f"• 곡 제목이나 아티스트명을 입력하거나 자동완성 목록에서 선택해 보세요.",
                        ephemeral=True
                    )
                    return
                target_pl["tracks"] = kept

        target_pl["updated_at"] = core.get_today_str()
        await _commit_and_refresh_studio(studio, data)
        await interaction.followup.send(
            f"✅ **`{target_pl['emoji']} {target_pl['name']}`**에서 **{len(removed)}곡**을 삭제했습니다! (남은 곡: {len(target_pl['tracks'])}곡)\n"
            f"{_format_removed_preview(removed)}",
            ephemeral=True
        )


    @app_commands.command(name="플리재생", description="내 음성채널에서 플레이리스트를 1번 곡부터 순번대로 즉시 자동재생합니다.")
    @app_commands.autocomplete(플리선택=core.user_playlist_autocomplete)
    @app_commands.describe(
        플리선택="(선택) 재생할 플레이리스트 선택 (기본: 내 대표 플레이리스트)",
        시작순번="(선택) 몇 번째 곡부터 재생할지 지정 (기본값: 1)",
        유저="(선택) 다른 유저의 플레이리스트를 재생할 경우 유저 선택"
    )
    async def play_playlist_cmd(
        self,
        interaction: discord.Interaction,
        플리선택: Optional[str] = None,
        시작순번: Optional[int] = 1,
        유저: Optional[discord.User] = None
    ):
        target_user = 유저 or interaction.user
        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, target_user.id, target_user.display_name)
        pls = core.ensure_user_playlists(prof, target_user.display_name)
        selected_pl = next((p for p in pls if p["id"] == 플리선택 or p["name"] == 플리선택), pls[0])

        idx = max(0, (시작순번 or 1) - 1)
        if idx >= len(selected_pl.get("tracks", [])):
            idx = 0

        await start_voice_playlist_from_interaction(interaction, target_user, selected_pl, start_index=idx)


    @app_commands.command(name="플리곡추가", description="내 플레이리스트에 곡(제목 또는 유튜브·스포티파이·사클 링크)을 빠르게 추가합니다.")
    @app_commands.autocomplete(플리선택=core.user_playlist_autocomplete)
    @app_commands.describe(
        곡="곡 제목 또는 영상/트랙 링크 (유튜브·스포티파이·사클 플레이리스트 링크 입력 시 통째로 일괄 추가)",
        아티스트="(선택) 아티스트명 (검색 정확도 향상)",
        플리선택="(선택) 곡을 추가할 플레이리스트 선택 (기본: 대표 플리)",
        중복허용="(선택) 이미 등록된 곡이어도 중복으로 추가할지 여부 (기본: 거짓)"
    )
    async def add_playlist_track_cmd(
        self,
        interaction: discord.Interaction,
        곡: str,
        아티스트: Optional[str] = None,
        플리선택: Optional[str] = None,
        중복허용: Optional[bool] = False
    ):
        await core.safe_defer(interaction, ephemeral=True)
        raw_val = (곡 or "").strip()
        if "http://" in raw_val or "https://" in raw_val:
            m_u = re.search(r"https?://[^\s<>\"']+", raw_val)
            if m_u:
                raw_val = m_u.group(0)
        if not raw_val:
            await interaction.followup.send("❌ 추가할 곡 제목이나 링크를 입력해 주세요.", ephemeral=True)
            return

        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
        pls = core.ensure_user_playlists(prof, interaction.user.display_name)
        target_pl = next((p for p in pls if p["id"] == 플리선택 or p["name"] == 플리선택), pls[0])

        is_pl, pl_plat = core.is_playlist_url(raw_val, allow_watch_with_list=False)
        if is_pl:
            meta, pl_tracks, err = await core.extract_playlist_from_url(raw_val, max_tracks=100)
            if err or not pl_tracks:
                await interaction.followup.send(f"❌ 플레이리스트 링크 추출 실패: {err or '수록곡 없음'}", ephemeral=True)
                return
            try:
                target_pl, added_cnt, action_msg = core.import_playlist_into_profile_sync(
                    prof,
                    interaction.user.display_name,
                    meta,
                    pl_tracks,
                    target_pl_id=target_pl["id"],
                    skip_duplicates=not (중복허용 or False)
                )
            except Exception as e:
                await interaction.followup.send(f"❌ 플레이리스트 추가 실패: {e}", ephemeral=True)
                return
            await asyncio.to_thread(core.save_data, data)
            studio = PlaylistStudioView(interaction.user, interaction.user, data, initial_pl_id=target_pl["id"])
            await interaction.followup.send(
                content=f"🎉 **{action_msg}** (총 {len(target_pl['tracks'])}곡 수록)",
                embed=studio.build_embed(),
                view=studio
            )
            return

        existing_tracks = target_pl.setdefault("tracks", [])
        if len(existing_tracks) >= 100:
            await interaction.followup.send("❌ 하나의 플레이리스트에는 최대 **100곡**까지만 담을 수 있습니다.", ephemeral=True)
            return

        resolved = await core.resolve_playlist_track(
            raw_val,
            artist_hint=(아티스트 or "").strip(),
            preferred_platform=target_pl.get("platform", "YouTube")
        )

        is_dup = any(_track_matches(resolved, et) for et in existing_tracks)
        if is_dup and not 중복허용:
            await interaction.followup.send(
                f"⚠️ **`{resolved['title']}`**은(는) 이미 **`{target_pl['emoji']} {target_pl['name']}`**에 등록되어 있습니다!\n"
                f"• 그래도 추가하려면 `/플리곡추가` 실행 시 `중복허용: 참`으로 설정해 주세요.",
                ephemeral=True
            )
            return

        existing_tracks.append(resolved)
        target_pl["updated_at"] = core.get_today_str()
        await asyncio.to_thread(core.save_data, data)

        studio = PlaylistStudioView(interaction.user, interaction.user, data, initial_pl_id=target_pl["id"])
        studio.current_page = max(0, (len(existing_tracks) - 1) // studio.items_per_page)
        p_meta = core.PLAYLIST_PLATFORMS.get(target_pl.get("platform", "YouTube"), core.PLAYLIST_PLATFORMS["YouTube"])

        dup_note = " *(중복 곡)*" if is_dup else ""
        await interaction.followup.send(
            content=f"✅ {p_meta['emoji']} **`{target_pl['emoji']} {target_pl['name']}`**의 **#{len(existing_tracks)}번째 곡**으로 추가되었습니다!{dup_note}\n"
                    f"🎵 **{resolved.get('title', '제목 없음')}** — `{resolved.get('artist', '-')}`",
            embed=studio.build_embed(),
            view=studio
        )

    @app_commands.command(name="플리목록", description="내(또는 특정 유저의) 모든 플레이리스트 목록과 수록곡 현황을 확인합니다.")
    @app_commands.describe(유저="(선택) 플레이리스트 목록을 확인할 유저 (미지정 시 내 목록)")
    async def list_playlists_cmd(self, interaction: discord.Interaction, 유저: Optional[discord.User] = None):
        target_user = 유저 or interaction.user
        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, target_user.id, target_user.display_name)
        pls = core.ensure_user_playlists(prof, target_user.display_name)

        embed = discord.Embed(
            title=f"📁 {target_user.display_name}님의 플레이리스트 보관함 ({len(pls)}/20)",
            description="원하는 플레이리스트를 선택하여 스튜디오를 열거나 바로 감상해 보세요 ✨",
            color=0x5865F2,
            timestamp=datetime.now(KST)
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)

        for i, pl in enumerate(pls, start=1):
            p_plat = pl.get("platform", "YouTube")
            p_meta = core.PLAYLIST_PLATFORMS.get(p_plat, core.PLAYLIST_PLATFORMS["YouTube"])
            t_cnt = len(pl.get("tracks", []))
            likes = len(pl.get("likes", []))
            desc = pl.get("desc") or "설명 없음"
            embed.add_field(
                name=f"{i}. {pl.get('emoji', '🎧')} {pl.get('name', '플레이리스트')} ({p_meta['emoji']} {p_plat})",
                value=f"• 수록곡: **{t_cnt}곡** | 좋아요: **{likes}개**\n• 설명: *{desc[:60]}*",
                inline=False
            )

        studio = PlaylistStudioView(interaction.user, target_user, data, initial_pl_id=pls[0]["id"])
        await core.safe_send_response(interaction, embed=embed, view=studio)


    @app_commands.command(name="음악알림추가", description="원하는 시간(HH:MM)과 채널을 여러 개 등록해 맞춤형 자동 음악 추천 알람을 받습니다.")
    @app_commands.autocomplete(삭제할알림=core.music_schedule_autocomplete)
    @app_commands.describe(
        동작="(선택) 미선택 시 버튼으로 조작 가능한 타이머 관리 보드를 엽니다.",
        시간="(추가 시) 음악을 추천받을 시간 (24시간제 HH:MM 형식, 예: 22:00, 15:30)",
        채널="(추가 시) 음악 추천을 받을 텍스트 채널 (미지정 시 현재 채널)",
        이름="(추가 시) 알림 이름 (예: 밤 10시 수면 음악, 오후 3시 노동요)",
        장르="(추가 시/선택) 추천받을 테마 키워드 (예: sleep, lofi, pop, piano / 미입력 시 감성 자동 맞춤)",
        삭제할알림="(삭제 시) 목록에서 삭제할 음악 알림을 선택하세요."
    )
    @app_commands.choices(동작=[
        app_commands.Choice(name="🧭 인터랙티브 타이머 관리 보드 열기", value="hub"),
        app_commands.Choice(name="➕ 새 음악 알림 타이머 추가", value="add"),
        app_commands.Choice(name="📋 등록된 음악 알림 타이머 목록", value="list"),
        app_commands.Choice(name="🗑️ 음악 알림 타이머 삭제", value="delete")
    ])
    async def custom_music_schedule_cmd(
        self,
        interaction: discord.Interaction,
        동작: app_commands.Choice[str] = None,
        시간: str = None,
        채널: discord.TextChannel = None,
        이름: str = "맞춤 음악 추천",
        장르: str = None,
        삭제할알림: str = None
    ):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        schedules = data.setdefault("music_schedules", [])
        target_ch = 채널 or interaction.channel
        mode = 동작.value if 동작 else ("add" if 시간 else "hub")

        if mode in ("hub", "list"):
            hub_view = MusicScheduleHubView(schedules, target_ch, interaction.guild)
            await interaction.followup.send(embed=hub_view.build_embed(), view=hub_view)
            return

        if mode == "add":
            if not 시간:
                hub_view = MusicScheduleHubView(schedules, target_ch, interaction.guild)
                await interaction.followup.send(
                    "ℹ️ `시간(HH:MM)`이 입력되지 않아 타이머 관리 보드를 열었습니다. **`[➕ 새 알림 타이머 추가]`** 버튼을 눌러보세요!",
                    embed=hub_view.build_embed(),
                    view=hub_view
                )
                return
            clean_time = _normalize_music_time_str(시간)
            if not clean_time:
                await interaction.followup.send("❌ 시간은 24시간제 `HH:MM` 형식(예: `9:00`, `09:00`, `15:30`, `22:00`)으로 입력해 주세요.", ephemeral=True)
                return
            sched_id = f"sched_{int(time.time())}_{random.randint(100, 999)}"
            ch_id = target_ch.id if target_ch else (interaction.channel_id or 0)
            schedules.append({
                "id": sched_id,
                "time": clean_time,
                "channel_id": ch_id,
                "guild_id": interaction.guild_id or 0,
                "name": 이름,
                "genre": 장르.strip() if 장르 and 장르.strip() else None,
                "last_sent": ""
            })
            await asyncio.to_thread(core.save_data, data)

            hub_view = MusicScheduleHubView(schedules, target_ch, interaction.guild)
            embed = hub_view.build_embed()
            embed.title = f"✅ 새 음악 타이머 등록 완료 (`{clean_time}` — {이름})"
            await interaction.followup.send(embed=embed, view=hub_view)

        elif mode == "delete":
            if not 삭제할알림:
                hub_view = MusicScheduleHubView(schedules, target_ch, interaction.guild)
                await interaction.followup.send("ℹ️ 아래 드롭다운 메뉴에서 삭제할 음악 알림을 선택해 주세요.", embed=hub_view.build_embed(), view=hub_view)
                return
            before_cnt = len(schedules)
            data["music_schedules"] = [
                s for s in schedules
                if not (s.get("id") == 삭제할알림 and core.is_schedule_in_guild(s, interaction.guild))
            ]
            if len(data["music_schedules"]) == before_cnt:
                await interaction.followup.send("❌ 현재 서버에서 해당 알림을 찾을 수 없습니다.", ephemeral=True)
                return
            await asyncio.to_thread(core.save_data, data)
            hub_view = MusicScheduleHubView(data["music_schedules"], target_ch, interaction.guild)
            await interaction.followup.send("🗑️ 선택한 음악 알림 타이머가 삭제되었습니다.", embed=hub_view.build_embed(), view=hub_view)

    @app_commands.command(name="음악추천설정", description="매일 오전 7시 음악 추천을 받을 채널과 조건을 설정합니다.")
    @app_commands.describe(
        채널="매일 오전 7시 추천 음악을 전송받을 텍스트 채널을 선택하세요.",
        플랫폼="추천받을 사이트 선택 (기본: 모두 랜덤)",
        장르="원하는 장르 (선택사항, 예: lofi, pop, k-pop, jazz)",
        아티스트="원하는 아티스트 (선택사항, 예: IU, Charlie Puth)",
        플레이리스트링크="YouTube, Spotify 또는 SoundCloud 플레이리스트 URL (입력 시 해당 플리 안에서만 랜덤 추천)"
    )
    @app_commands.choices(플랫폼=[
        app_commands.Choice(name="랜덤 (YouTube + Spotify + SoundCloud)", value="all"),
        app_commands.Choice(name="유튜브 (YouTube) 전용", value="youtube"),
        app_commands.Choice(name="스포티파이 (Spotify) 전용", value="spotify"),
        app_commands.Choice(name="사운드클라우드 (SoundCloud) 전용", value="soundcloud")
    ])
    async def set_music_prefs(
        self,
        interaction: discord.Interaction,
        채널: discord.TextChannel,
        플랫폼: app_commands.Choice[str] = None,
        장르: str = None,
        아티스트: str = None,
        플레이리스트링크: str = None
    ):
        if 플레이리스트링크 and not any(k in 플레이리스트링크 for k in ("youtube.com/", "youtu.be/", "spotify.com/", "soundcloud.com/")):
            await core.safe_send_response(
                interaction,
                content="❌ 플레이리스트 링크는 **YouTube, Spotify** 또는 **SoundCloud** 주소여야 합니다.",
                ephemeral=True
            )
            return

        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        selected_platform = 플랫폼.value if 플랫폼 else "all"
        data["music_prefs"] = {
            "channel_id": 채널.id,
            "platform": selected_platform,
            "genre": 장르,
            "artist": 아티스트,
            "playlist_url": 플레이리스트링크
        }
        await asyncio.to_thread(core.save_data, data)

        embed = discord.Embed(title="🎧 모닝 음악 추천 설정 완료", color=discord.Color.from_rgb(0, 204, 221))
        embed.add_field(name="📢 전송 채널", value=채널.mention, inline=False)
        if 플레이리스트링크:
            embed.add_field(
                name="🔗 지정 플레이리스트",
                value=f"내일 오전 7시부터 [입력하신 플레이리스트]({플레이리스트링크}) 안의 곡들 중 랜덤으로 추천합니다!",
                inline=False
            )
        else:
            platform_label = 플랫폼.name if 플랫폼 else "랜덤 (Spotify + SoundCloud)"
            embed.add_field(name="🌐 플랫폼", value=f"`{platform_label}`", inline=True)
            embed.add_field(name="🎸 장르", value=f"`{장르 if 장르 else '요일·시간대별 감성 자동'}`", inline=True)
            embed.add_field(name="🎤 아티스트", value=f"`{아티스트 if 아티스트 else '랜덤 (미지정)'}`", inline=True)

        await core.safe_send_response(interaction, embed=embed)

    @app_commands.command(name="음악지금추천", description="현재 설정된 조건으로 추천 음악을 즉시 1곡 뽑아봅니다.")
    async def test_music_now(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        prefs = data.get("music_prefs", core.DEFAULT_CONFIG["music_prefs"])
        track_info, error = await core.get_recommended_music(prefs)

        if error or not track_info:
            await interaction.followup.send(f"❌ **음악 추천 실패:** {error}")
            return

        embed, view = self.bot.build_music_embed_and_view(track_info, prefs, is_morning=False)
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="내음악보관함", description="추천 음악에서 하트(❤️)를 눌러 보관함에 담은 곡들을 확인하고 셔플로 뽑아 듣습니다.")
    async def my_music_library_cmd(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(interaction.user.id)
        liked_list = data.get("user_profiles", {}).get(u_key, {}).get("liked_music", [])

        view = MusicLibraryPaginationView(f"❤️ {interaction.user.display_name}님의 나만의 음악 보관함", liked_list, items_per_page=5)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    @app_commands.command(name="오디오테스트", description="음성채널에 접속하여 봇의 오디오 출력, DAVE 암호화 및 비프음(소리)을 즉시 점검합니다.")
    async def audio_test_cmd(self, interaction: discord.Interaction):
        """
        Krisp 잡음 제거를 통과하는 880Hz 펄스 비프음을 5초 동안 재생하여
        1) 봇의 음성 게이트웨이 연결,
        2) 디스코드 DAVE 종단간 암호화(E2EE) 및 일반 채널 암호화 상태,
        3) PyNaCl & libopus 패킷 인코딩,
        4) 사용자 디스코드 클라이언트 음량/권한 설정을 완벽하게 자가진단합니다.
        """
        voice_state = interaction.user.voice if isinstance(interaction.user, discord.Member) else None
        if not voice_state or not voice_state.channel:
            await core.safe_send_response(
                interaction,
                "❌ 먼저 오디오를 테스트할 **음성채널**에 입장하신 뒤 `/오디오테스트` 명령어를 실행해 주세요!",
                ephemeral=True
            )
            return

        await core.safe_defer(interaction)

        # 시스템 환경 진단
        opus_ok = core.ensure_opus_loaded()
        ffmpeg_path = core.get_ffmpeg_executable()
        has_dave_flag = getattr(discord.voice_client, "has_dave", False)
        has_nacl_flag = getattr(discord.voice_client, "has_nacl", False)

        player = get_voice_player(self.bot, interaction.guild)
        # 꼬인 기존 음성 세션(청각차단 잔여 플래그 등)을 강제 리셋하여 클린 세션 생성
        if interaction.guild.voice_client and interaction.guild.voice_client.is_connected():
            try:
                await interaction.guild.voice_client.disconnect(force=True)
                await asyncio.sleep(0.3)
            except Exception:
                pass
        await player.set_deafen(False)
        ok, msg = await player.ensure_connected(voice_state.channel, self_deaf=False)
        if not ok:
            await interaction.followup.send(f"❌ **음성채널 연결 실패:** {msg}")
            return

        vc = player.voice_client

        # 라이브러리 버전 정확 추출 (importlib.metadata 기반)
        davey_ver = "미설치"
        try:
            import importlib.metadata
            davey_ver = importlib.metadata.version("davey")
        except Exception:
            if has_dave_flag:
                davey_ver = "정상 로드됨"

        nacl_ver = "미설치"
        try:
            import importlib.metadata
            nacl_ver = importlib.metadata.version("PyNaCl")
        except Exception:
            if has_nacl_flag:
                nacl_ver = "정상 작동"

        transport_mode = getattr(vc, "mode", "알 수 없음")

        # DAVE E2EE 프로토콜 버전 및 암호화 상태 정밀 판별
        dave_ver = 0
        can_encrypt = False
        session_ready = False

        if vc and hasattr(vc, "_connection"):
            conn = vc._connection
            dave_ver = getattr(conn, "dave_protocol_version", 0)

            def _check_encrypt() -> bool:
                ce = getattr(conn, "can_encrypt", None)
                if ce is None and hasattr(conn, "dave_session"):
                    ce = getattr(conn.dave_session, "can_encrypt", None)
                if ce is None and hasattr(vc, "ws"):
                    ce = getattr(vc.ws, "can_encrypt", None)
                if callable(ce):
                    try:
                        return bool(ce())
                    except Exception:
                        return False
                return bool(ce)

            if dave_ver > 0 and not _check_encrypt():
                # DAVE 프로토콜 채널: MLS 키 교환 완료(can_encrypt) 최대 3초 대기
                for _ in range(15):
                    if _check_encrypt():
                        break
                    await asyncio.sleep(0.2)

            can_encrypt = _check_encrypt()
            dave_sess = getattr(conn, "dave_session", None)
            session_ready = getattr(dave_sess, "ready", False) if dave_sess else False

        if dave_ver == 0:
            dave_desc = "✅ 일반 표준 음성 모드 (이 채널은 DAVE E2EE 미적용 채널입니다)"
        elif can_encrypt or session_ready:
            dave_desc = f"🔒 v{dave_ver} DAVE E2EE 종단간 암호화 가동 중 (Ready)"
        else:
            dave_desc = f"⚠️ v{dave_ver} DAVE E2EE 키 교환 대기 (패스스루 모드)"

        # 3중 안전망으로 사전 렌더링된 고품질 비프음 소스 획득 (Opus 우선, WAV 및 순수 파이썬 폴백)
        source, engine_name = get_test_beep_source()
        source_vol = source if source.is_opus() else discord.PCMVolumeTransformer(source, volume=1.3)

        if vc.is_playing() or vc.is_paused():
            player._stop_requested = True
            vc.stop()
            await asyncio.sleep(0.15)
            player._stop_requested = False

        try:
            if hasattr(vc, "ws") and vc.ws:
                await vc.ws.speak(discord.SpeakingState.voice)
            await asyncio.sleep(0.3)
        except Exception:
            pass

        play_error_box = []
        def _after(err):
            if err:
                play_error_box.append(str(err))

        vc.play(source_vol, after=_after)

        # 0.6초 대기 후 백그라운드 AudioPlayer 스레드가 정상 재생 중인지 검증
        await asyncio.sleep(0.6)
        is_actively_playing = vc.is_playing()

        embed = discord.Embed(
            title="🔊 봇 오디오 및 음성 파이프라인 정밀 진단",
            description=(
                f"**{voice_state.channel.name}** 음성채널에서 **5.0초간 고음량 C-메이저 팡파르 화음 멜로디(도-미-솔-도)**을 재생 중입니다!\n\n"
                f"### 🎧 소리가 정상적으로 들리시나요?\n"
                f"• **도-미-솔-도 화음 멜로디가 들림:** 봇의 음성 송출 / 패킷 암호화 / 네트워크가 100% 정상 작동 중입니다. 이제 `/플레이리스트`의 음성채널 자동재생을 마음껏 즐기실 수 있습니다!\n"
                f"• **소리가 전혀 안 들림:** 아래 진단 결과 및 **[소리가 안 날 때 필수 조치]**를 꼭 확인해 주세요."
            ),
            color=discord.Color.green() if is_actively_playing else discord.Color.gold(),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.add_field(
            name="📊 시스템 모듈 진단 결과",
            value=(
                f"• **음성 채널 모드:** `{dave_desc}`\n"
                f"• **트랜스포트 암호화:** `{transport_mode}`\n"
                f"• **오디오 재생 엔진:** `{engine_name}`\n"
                f"• **실시간 송출 상태:** `{'🟢 현재 음성 패킷 정상 송출 중 (is_playing: True)' if is_actively_playing else '⚠️ 송출 조기 종료됨 (원인 확인 필요)'}`\n"
                f"• **라이브러리 버전:** `discord.py v{discord.__version__}` | `davey: {davey_ver}` | `PyNaCl: {nacl_ver}`\n"
                f"• **libopus 오디오 인코더:** `{'✅ 정상 로드됨' if opus_ok else '❌ 미로드'}`\n"
                f"• **헤드셋 상태:** `🔊 헤드셋 켬 (청각차단 해제됨)`"
            ),
            inline=False
        )

        if davey_ver.startswith("0.2"):
            embed.add_field(
                name="🚨 치명적 버전 비호환 감지 (초록불만 켜지고 소리 안 나는 원인!)",
                value=(
                    f"현재 서버에 설치된 `davey v{davey_ver}`은 discord.py와의 호환성 버그(Issue #10549)로 인해 "
                    f"음성 패킷이 깨져 디스코드 앱에서 무음(Silent) 처리됩니다!\n"
                    f"서버 터미널에서 아래 명령어로 `davey 0.1.7`로 다운그레이드해야 정상 출력됩니다:\n"
                    f"`/home/ubuntu/norosi/venv/bin/pip install \"davey>=0.1.6,<0.2.0\" && sudo systemctl restart norosi`"
                ),
                inline=False
            )

        if play_error_box:
            embed.add_field(
                name="🚨 실시간 오디오 스레드 오류 감지",
                value=f"```\n{play_error_box[0]}\n```",
                inline=False
            )

        embed.add_field(
            name="⚠️ 소리가 안 날 때 필수 조치 (체크리스트)",
            value=(
                "1. **디스코드 앱 봇 볼륨 확인 (가장 많은 원인!):**\n"
                "   음성방 참가자 목록에서 **봇 프로필을 우클릭** ➔ **[사용자 음량]** 슬라이더가 0%로 되어 있지 않은지 확인 (100%로 올려주세요!)\n"
                "2. **개인 음소거 확인:**\n"
                "   봇 프로필 우클릭 시 **[음소거]** 항목에 체크가 되어 있다면 해제해 주세요.\n"
                "3. **디스코드 출력 장치 확인:**\n"
                "   디스코드 설정 ➔ [음성 및 비디오] ➔ [출력 장치]가 실제 이어폰/스피커로 올바르게 선택되어 있는지 확인\n"
                "4. **Krisp 잡음 제거 필터:**\n"
                "   통화방 우측 하단의 물결 모양 아이콘(잡음 제거)을 잠시 끄고 들어보세요.\n"
                "5. **음성 채널 지역 설정:**\n"
                "   음성 채널 우클릭 ➔ [채널 편집] ➔ [지역 재정의]를 `대한민국 (South Korea)` 또는 `싱가포르`로 변경해 보세요."
            ),
            inline=False
        )
        embed.set_footer(text="오디오 진단 완료 • 5.0초 후 테스트 톤이 종료됩니다. (텍스트 명령어 !오디오테스트 지원)")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="헤드셋", description="봇의 헤드셋 끄기(청각 차단 / deafen) 상태를 켜거나 끕니다.")
    @app_commands.describe(모드="설정할 헤드셋 모드 ('토글', '끄기', '켜기' 중 선택)")
    @app_commands.choices(모드=[
        app_commands.Choice(name="🔄 현재 상태 반전 (토글)", value="toggle"),
        app_commands.Choice(name="🎧 헤드셋 끄기 (빨간 사선 청각차단 On - 권장)", value="deaf_on"),
        app_commands.Choice(name="🔊 헤드셋 켜기 (청각차단 해제 Off)", value="deaf_off"),
    ])
    async def headset_toggle_cmd(self, interaction: discord.Interaction, 모드: Optional[app_commands.Choice[str]] = None):
        """봇의 헤드셋 끄기(청각 차단 / deafen) 상태를 실시간 제어"""
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 이 명령어는 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return

        player = get_voice_player(self.bot, interaction.guild)
        choice_val = 모드.value if 모드 else "toggle"

        if choice_val == "deaf_on":
            await player.set_deafen(True)
        elif choice_val == "deaf_off":
            await player.set_deafen(False)
        else:
            await player.toggle_deafen()

        state_str = "🎧 **헤드셋 끄기 (청각 차단 On / 빨간 사선)**" if player.deaf_mode else "🔊 **헤드셋 켜기 (청각 차단 Off / 일반)**"
        guide_str = (
            "음악 봇은 서버 트래픽과 패킷 안정성을 위해 '헤드셋 끄기(청각 차단)'가 기본 권장 사양입니다.\n"
            "언제든 `/헤드셋` 명령어 또는 플레이리스트 제어 패널에서 자유롭게 변경하실 수 있습니다."
        )

        embed = discord.Embed(
            title="🎧 봇 헤드셋(청각 차단) 설정 변경",
            description=f"현재 봇의 음성 상태가 {state_str} 상태로 변경되었습니다.\n\n💡 {guide_str}",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text=f"설정 변경자: {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="배속", description="플레이리스트의 재생 속도(배속)를 조절합니다. (기본: 1.0배속)")
    @app_commands.describe(속도="설정할 재생 속도 (0.5배속 ~ 2.0배속)")
    @app_commands.choices(속도=[
        app_commands.Choice(name="⚡ 1.0배속 (표준 / 기본값)", value="1.0"),
        app_commands.Choice(name="⚡ 1.25배속 (조금 빠르게)", value="1.25"),
        app_commands.Choice(name="⚡ 1.5배속 (빠르게)", value="1.5"),
        app_commands.Choice(name="⚡ 1.75배속 (매우 빠르게)", value="1.75"),
        app_commands.Choice(name="⚡ 2.0배속 (2배속)", value="2.0"),
        app_commands.Choice(name="🐌 0.75배속 (조금 느리게)", value="0.75"),
        app_commands.Choice(name="🐌 0.5배속 (0.5배속)", value="0.5"),
    ])
    async def playback_speed_cmd(self, interaction: discord.Interaction, 속도: str = "1.0"):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 음성채널 배속 설정은 서버(길드)에서만 사용할 수 있습니다.", ephemeral=True)
            return

        try:
            val = float(속도)
        except ValueError:
            val = 1.0

        player = get_voice_player(self.bot, interaction.guild)
        ok, msg = await player.set_playback_speed(val)
        embed = discord.Embed(
            title="⚡ 플레이리스트 재생 배속 설정",
            description=f"{msg}\n\n💡 리모컨 대시보드의 **`[⚡ 배속]`** 버튼으로도 원클릭 순환 변경이 가능합니다.",
            color=discord.Color.green() if val == 1.0 else discord.Color.gold(),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text=f"설정 변경자: {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    # ==========================================
    # 디스코드 캐시 문제와 무관하게 100% 즉시 작동하는 텍스트 접두사 명령어 (Prefix: !)
    # ==========================================
    @commands.command(name="오디오테스트", aliases=["소리테스트", "audiotest", "test", "비프음"])
    async def prefix_audio_test(self, ctx: commands.Context):
        """채팅창에 !오디오테스트 입력 시 즉시 880Hz 펄스 비프음 5.0초 재생 및 오디오 파이프라인 정밀 진단"""
        voice_state = ctx.author.voice if isinstance(ctx.author, discord.Member) else None
        if not voice_state or not voice_state.channel:
            await ctx.send("❌ 먼저 오디오를 테스트할 **음성채널**에 입장하신 뒤 `!오디오테스트` 명령어를 입력해 주세요!")
            return

        status_msg = await ctx.send("⏳ **[오디오 진단]** 음성채널 연결 및 5초 비프음 재생 준비 중...")

        opus_ok = core.ensure_opus_loaded()
        ffmpeg_path = core.get_ffmpeg_executable()
        has_dave_flag = getattr(discord.voice_client, "has_dave", False)
        has_nacl_flag = getattr(discord.voice_client, "has_nacl", False)

        player = get_voice_player(self.bot, ctx.guild)
        # 꼬인 기존 음성 세션(청각차단 잔여 플래그 등)을 강제 리셋하여 클린 세션 생성
        if ctx.guild.voice_client and ctx.guild.voice_client.is_connected():
            try:
                await ctx.guild.voice_client.disconnect(force=True)
                await asyncio.sleep(0.3)
            except Exception:
                pass
        await player.set_deafen(False)
        ok, msg = await player.ensure_connected(voice_state.channel, self_deaf=False)
        if not ok:
            await status_msg.edit(content=f"❌ **음성채널 연결 실패:** {msg}")
            return

        vc = player.voice_client

        # 라이브러리 버전 정확 추출 (importlib.metadata 기반)
        davey_ver = "미설치"
        try:
            import importlib.metadata
            davey_ver = importlib.metadata.version("davey")
        except Exception:
            if has_dave_flag:
                davey_ver = "정상 로드됨"

        nacl_ver = "미설치"
        try:
            import importlib.metadata
            nacl_ver = importlib.metadata.version("PyNaCl")
        except Exception:
            if has_nacl_flag:
                nacl_ver = "정상 작동"

        transport_mode = getattr(vc, "mode", "알 수 없음")

        # DAVE E2EE 프로토콜 버전 및 암호화 상태 정밀 판별
        dave_ver = 0
        can_encrypt = False
        session_ready = False

        if vc and hasattr(vc, "_connection"):
            conn = vc._connection
            dave_ver = getattr(conn, "dave_protocol_version", 0)

            def _check_encrypt() -> bool:
                ce = getattr(conn, "can_encrypt", None)
                if ce is None and hasattr(conn, "dave_session"):
                    ce = getattr(conn.dave_session, "can_encrypt", None)
                if ce is None and hasattr(vc, "ws"):
                    ce = getattr(vc.ws, "can_encrypt", None)
                if callable(ce):
                    try:
                        return bool(ce())
                    except Exception:
                        return False
                return bool(ce)

            if dave_ver > 0 and not _check_encrypt():
                # DAVE 프로토콜 채널: MLS 키 교환 완료(can_encrypt) 최대 3초 대기
                for _ in range(15):
                    if _check_encrypt():
                        break
                    await asyncio.sleep(0.2)

            can_encrypt = _check_encrypt()
            dave_sess = getattr(conn, "dave_session", None)
            session_ready = getattr(dave_sess, "ready", False) if dave_sess else False

        if dave_ver == 0:
            dave_desc = "✅ 일반 표준 음성 모드 (이 채널은 DAVE E2EE 미적용 채널입니다)"
        elif can_encrypt or session_ready:
            dave_desc = f"🔒 v{dave_ver} DAVE E2EE 종단간 암호화 가동 중 (Ready)"
        else:
            dave_desc = f"⚠️ v{dave_ver} DAVE E2EE 키 교환 대기 (패스스루 모드)"

        # 3중 안전망으로 사전 렌더링된 고품질 비프음 소스 획득 (Opus 우선, WAV 및 순수 파이썬 폴백)
        source, engine_name = get_test_beep_source()
        source_vol = source if source.is_opus() else discord.PCMVolumeTransformer(source, volume=1.3)

        if vc.is_playing() or vc.is_paused():
            player._stop_requested = True
            vc.stop()
            await asyncio.sleep(0.15)
            player._stop_requested = False

        try:
            if hasattr(vc, "ws") and vc.ws:
                await vc.ws.speak(discord.SpeakingState.voice)
            await asyncio.sleep(0.3)
        except Exception:
            pass

        play_error_box = []
        def _after(err):
            if err:
                play_error_box.append(str(err))

        vc.play(source_vol, after=_after)

        # 0.6초 대기 후 백그라운드 AudioPlayer 스레드가 정상 재생 중인지 검증
        await asyncio.sleep(0.6)
        is_actively_playing = vc.is_playing()

        embed = discord.Embed(
            title="🔊 봇 오디오 및 음성 파이프라인 정밀 진단 (!오디오테스트)",
            description=(
                f"**{voice_state.channel.name}** 음성채널에서 **5.0초간 고음량 C-메이저 팡파르 화음 멜로디(도-미-솔-도)**을 재생 중입니다!\n\n"
                f"### 🎧 소리가 정상적으로 들리시나요?\n"
                f"• **도-미-솔-도 화음 멜로디가 들림:** 봇의 음성 송출 / 패킷 암호화 / 네트워크가 100% 정상 작동 중입니다. 이제 `!플레이리스트` 또는 `/플레이리스트` 자동재생을 안심하고 사용하실 수 있습니다!\n"
                f"• **소리가 전혀 안 들림:** 아래 진단 결과 및 **[소리가 안 날 때 필수 조치]**를 꼭 확인해 주세요."
            ),
            color=discord.Color.green() if is_actively_playing else discord.Color.gold(),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.add_field(
            name="📊 시스템 모듈 진단 결과",
            value=(
                f"• **음성 채널 모드:** `{dave_desc}`\n"
                f"• **트랜스포트 암호화:** `{transport_mode}`\n"
                f"• **오디오 재생 엔진:** `{engine_name}`\n"
                f"• **실시간 송출 상태:** `{'🟢 현재 음성 패킷 정상 송출 중 (is_playing: True)' if is_actively_playing else '⚠️ 송출 조기 종료됨 (원인 확인 필요)'}`\n"
                f"• **라이브러리 버전:** `discord.py v{discord.__version__}` | `davey: {davey_ver}` | `PyNaCl: {nacl_ver}`\n"
                f"• **libopus 오디오 인코더:** `{'✅ 정상 로드됨' if opus_ok else '❌ 미로드'}`\n"
                f"• **헤드셋 상태:** `🔊 헤드셋 켬 (청각차단 해제됨)`"
            ),
            inline=False
        )

        if davey_ver.startswith("0.2"):
            embed.add_field(
                name="🚨 치명적 버전 비호환 감지 (초록불만 켜지고 소리 안 나는 원인!)",
                value=(
                    f"현재 서버에 설치된 `davey v{davey_ver}`은 discord.py와의 호환성 버그(Issue #10549)로 인해 "
                    f"음성 패킷이 깨져 디스코드 앱에서 무음(Silent) 처리됩니다!\n"
                    f"서버 터미널에서 아래 명령어로 `davey 0.1.7`로 다운그레이드해야 정상 출력됩니다:\n"
                    f"`/home/ubuntu/norosi/venv/bin/pip install \"davey>=0.1.6,<0.2.0\" && sudo systemctl restart norosi`"
                ),
                inline=False
            )

        if play_error_box:
            embed.add_field(
                name="🚨 실시간 오디오 스레드 오류 감지",
                value=f"```\n{play_error_box[0]}\n```",
                inline=False
            )

        embed.add_field(
            name="⚠️ 소리가 안 날 때 필수 조치 (체크리스트)",
            value=(
                "1. **디스코드 앱 봇 볼륨 확인 (가장 많은 원인!):**\n"
                "   음성방 참가자 목록에서 **봇 프로필을 우클릭** ➔ **[사용자 음량]** 슬라이더가 0%로 되어 있지 않은지 확인 (100%로 올려주세요!)\n"
                "2. **개인 음소거 확인:**\n"
                "   봇 프로필 우클릭 시 **[음소거]** 항목에 체크가 되어 있다면 해제해 주세요.\n"
                "3. **디스코드 출력 장치 확인:**\n"
                "   디스코드 설정 ➔ [음성 및 비디오] ➔ [출력 장치]가 실제 이어폰/스피커로 올바르게 선택되어 있는지 확인\n"
                "4. **Krisp 잡음 제거 필터:**\n"
                "   통화방 우측 하단의 물결 모양 아이콘(잡음 제거)을 잠시 끄고 들어보세요.\n"
                "5. **음성 채널 지역 설정:**\n"
                "   음성 채널 우클릭 ➔ [채널 편집] ➔ [지역 재정의]를 `대한민국 (South Korea)` 또는 `싱가포르`로 변경해 보세요."
            ),
            inline=False
        )
        embed.set_footer(text="오디오 진단 완료 • 5.0초 후 테스트 톤이 종료됩니다. (!플레이리스트로 음악 바로 재생)")
        await status_msg.edit(content=None, embed=embed)

    @commands.command(name="플레이리스트", aliases=["플리", "playlist"])
    async def prefix_playlist_studio(self, ctx: commands.Context, *, 링크또는곡: Optional[str] = None):
        """채팅창에 !플레이리스트 또는 !플리 [링크] 입력 시 즉시 플레이리스트 스튜디오 패널 호출 또는 링크에서 플레이리스트 자동 생성"""
        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, ctx.author.id, ctx.author.display_name)
        playlists = core.ensure_user_playlists(prof, ctx.author.display_name)

        if 링크또는곡 and 링크또는곡.strip():
            raw_target = 링크또는곡.strip()
            is_pl, plat = core.is_playlist_url(raw_target)
            if is_pl:
                status_msg = await ctx.send(f"⏳ **{plat}** 플레이리스트 링크를 분석하고 수록곡들을 가져오는 중입니다...")
                meta, tracks, err = await core.extract_playlist_from_url(raw_target, max_tracks=100)
                if err or not tracks:
                    await status_msg.edit(content=f"❌ 플레이리스트에서 곡을 추출하지 못했습니다: {err or '수록곡 없음'}")
                    return
                try:
                    target_pl, count, action_msg = core.import_playlist_into_profile_sync(
                        prof, ctx.author.display_name, meta, tracks, target_pl_id=None, custom_name=None
                    )
                except Exception as e:
                    await status_msg.edit(content=f"❌ 플레이리스트 생성 실패: {e}")
                    return
                await asyncio.to_thread(core.save_data, data)
                studio = PlaylistStudioView(ctx.author, ctx.author, data, initial_pl_id=target_pl["id"])
                embed = studio.build_embed()
                embed.set_author(name=f"🎉 플레이리스트 일괄 가져오기 완료! ({meta['platform']})", icon_url=ctx.author.display_avatar.url)
                await status_msg.edit(
                    content=f"🎉 **{action_msg}**\n하단의 **`[🔊 음성채널 순차 자동재생]`** 버튼을 눌러 바로 감상하실 수 있습니다 ✨",
                    embed=embed,
                    view=studio
                )
                studio.message = status_msg
                return
            else:
                # 단일 곡 또는 영상 링크를 대표 플레이리스트에 빠른 추가
                target_pl = playlists[0]
                existing_tracks = target_pl.setdefault("tracks", [])
                if len(existing_tracks) >= 100:
                    await ctx.send("❌ 플레이리스트에는 최대 **100곡**까지만 담을 수 있습니다.")
                    return
                status_msg = await ctx.send(f"🔍 **`{raw_target}`** 음원 정보를 불러오는 중입니다...")
                resolved = await core.resolve_playlist_track(
                    raw_target,
                    preferred_platform=target_pl.get("platform", "YouTube")
                )
                is_dup = any(_track_matches(resolved, et) for et in existing_tracks)
                existing_tracks.append(resolved)
                target_pl["updated_at"] = core.get_today_str()
                await asyncio.to_thread(core.save_data, data)
                studio = PlaylistStudioView(ctx.author, ctx.author, data, initial_pl_id=target_pl["id"])
                studio.current_page = max(0, (len(existing_tracks) - 1) // studio.items_per_page)
                p_meta = core.PLAYLIST_PLATFORMS.get(target_pl.get("platform", "YouTube"), core.PLAYLIST_PLATFORMS["YouTube"])
                dup_note = " *(중복 곡)*" if is_dup else ""
                await status_msg.edit(
                    content=f"✅ {p_meta['emoji']} **`{target_pl['emoji']} {target_pl['name']}`**의 **#{len(existing_tracks)}번째 곡**으로 추가되었습니다!{dup_note}\n"
                            f"🎵 **{resolved.get('title', '제목 없음')}** — `{resolved.get('artist', '-')}`",
                    embed=studio.build_embed(),
                    view=studio
                )
                studio.message = status_msg
                return

        pl = playlists[0]
        view = PlaylistStudioView(ctx.author, ctx.author, data, initial_pl_id=pl["id"])
        embed = view.build_embed()
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

    @commands.command(name="플리재생", aliases=["플레이리스트재생", "플리자동재생", "playpl", "plplay"])
    async def prefix_play_playlist(self, ctx: commands.Context, *, 순번또는이름: Optional[str] = None):
        """채팅창에 !플리재생 또는 !플리재생 [순번/이름] 입력 시 음성채널에서 플레이리스트 자동재생 즉시 시작"""
        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, ctx.author.id, ctx.author.display_name)
        pls = core.ensure_user_playlists(prof, ctx.author.display_name)

        target_pl = pls[0]
        start_idx = 0
        if 순번또는이름 and 순번또는이름.strip():
            arg = 순번또는이름.strip()
            clean_num = arg.replace("번곡", "").replace("번", "").replace("곡", "").replace("#", "").strip()
            if clean_num.isdigit():
                start_idx = max(0, int(clean_num) - 1)
            else:
                found = next((p for p in pls if arg.lower() in p.get("name", "").lower() or p.get("id") == arg), None)
                if found:
                    target_pl = found

        await start_voice_playlist_from_context(ctx, ctx.author, target_pl, start_index=start_idx)

    @commands.command(name="플리추가", aliases=["곡추가", "addtrack", "pladd", "플리곡추가"])
    async def prefix_add_track(self, ctx: commands.Context, *, 곡제목또는링크: str):
        """채팅창에 !플리추가 [곡제목 또는 링크] 입력 시 내 대표 플레이리스트에 즉시 곡 추가"""
        raw_val = (곡제목또는링크 or "").strip()
        if "http://" in raw_val or "https://" in raw_val:
            m_u = re.search(r"https?://[^\s<>\"']+", raw_val)
            if m_u:
                raw_val = m_u.group(0)
        if not raw_val:
            await ctx.send("❌ 추가할 곡 제목이나 링크를 입력해 주세요. 예: `!플리추가 NewJeans Hype Boy` 또는 `!플리추가 https://youtu.be/...`")
            return

        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, ctx.author.id, ctx.author.display_name)
        pls = core.ensure_user_playlists(prof, ctx.author.display_name)
        target_pl = pls[0]

        is_pl, plat = core.is_playlist_url(raw_val, allow_watch_with_list=False)
        if is_pl:
            status_msg = await ctx.send(f"⏳ **{plat}** 플레이리스트 링크를 분석하고 수록곡들을 가져오는 중입니다...")
            meta, tracks, err = await core.extract_playlist_from_url(raw_val, max_tracks=100)
            if err or not tracks:
                await status_msg.edit(content=f"❌ 플레이리스트에서 곡을 추출하지 못했습니다: {err or '수록곡 없음'}")
                return
            try:
                target_pl, count, action_msg = core.import_playlist_into_profile_sync(
                    prof, ctx.author.display_name, meta, tracks, target_pl_id=target_pl["id"], skip_duplicates=True
                )
            except Exception as e:
                await status_msg.edit(content=f"❌ 플레이리스트 추가 실패: {e}")
                return
            await asyncio.to_thread(core.save_data, data)
            studio = PlaylistStudioView(ctx.author, ctx.author, data, initial_pl_id=target_pl["id"])
            await status_msg.edit(
                content=f"🎉 **{action_msg}** (총 {len(target_pl['tracks'])}곡 수록)",
                embed=studio.build_embed(),
                view=studio
            )
            return

        existing_tracks = target_pl.setdefault("tracks", [])
        if len(existing_tracks) >= 100:
            await ctx.send("❌ 플레이리스트에는 최대 **100곡**까지만 담을 수 있습니다.")
            return

        status_msg = await ctx.send(f"🔍 **`{raw_val}`** 음원 정보를 불러오는 중입니다...")
        resolved = await core.resolve_playlist_track(
            raw_val,
            preferred_platform=target_pl.get("platform", "YouTube")
        )
        is_dup = any(_track_matches(resolved, et) for et in existing_tracks)
        existing_tracks.append(resolved)
        target_pl["updated_at"] = core.get_today_str()
        await asyncio.to_thread(core.save_data, data)

        studio = PlaylistStudioView(ctx.author, ctx.author, data, initial_pl_id=target_pl["id"])
        studio.current_page = max(0, (len(existing_tracks) - 1) // studio.items_per_page)
        p_meta = core.PLAYLIST_PLATFORMS.get(target_pl.get("platform", "YouTube"), core.PLAYLIST_PLATFORMS["YouTube"])
        dup_note = " *(중복 곡)*" if is_dup else ""
        await status_msg.edit(
            content=f"✅ {p_meta['emoji']} **`{target_pl['emoji']} {target_pl['name']}`**의 **#{len(existing_tracks)}번째 곡**으로 추가되었습니다!{dup_note}\n"
                    f"🎵 **{resolved.get('title', '제목 없음')}** — `{resolved.get('artist', '-')}`",
            embed=studio.build_embed(),
            view=studio
        )

    @commands.command(name="플리목록", aliases=["플리리스트", "내플리", "pllist", "playlists"])
    async def prefix_list_playlists(self, ctx: commands.Context):
        """채팅창에 !플리목록 입력 시 내 모든 플레이리스트 목록과 수록곡 현황 확인"""
        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, ctx.author.id, ctx.author.display_name)
        pls = core.ensure_user_playlists(prof, ctx.author.display_name)

        embed = discord.Embed(
            title=f"📁 {ctx.author.display_name}님의 플레이리스트 보관함 ({len(pls)}/20)",
            description="원하는 플레이리스트를 선택하여 스튜디오를 열거나 바로 감상해 보세요 ✨",
            color=0x5865F2,
            timestamp=datetime.now(KST)
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)

        for i, pl in enumerate(pls, start=1):
            p_plat = pl.get("platform", "YouTube")
            p_meta = core.PLAYLIST_PLATFORMS.get(p_plat, core.PLAYLIST_PLATFORMS["YouTube"])
            t_cnt = len(pl.get("tracks", []))
            likes = len(pl.get("likes", []))
            desc = pl.get("desc") or "설명 없음"
            embed.add_field(
                name=f"{i}. {pl.get('emoji', '🎧')} {pl.get('name', '플레이리스트')} ({p_meta['emoji']} {p_plat})",
                value=f"• 수록곡: **{t_cnt}곡** | 좋아요: **{likes}개**\n• 설명: *{desc[:60]}*",
                inline=False
            )

        studio = PlaylistStudioView(ctx.author, ctx.author, data, initial_pl_id=pls[0]["id"])
        await ctx.send(embed=embed, view=studio)

    @commands.command(name="플리가져오기", aliases=["플레이리스트가져오기", "플리링크", "importpl"])
    async def prefix_playlist_import(self, ctx: commands.Context, 링크: str, *, 이름: Optional[str] = None):
        """채팅창에 !플리가져오기 [링크] [새 플리 이름] 입력 시 링크를 통째로 플레이리스트로 자동 생성"""
        raw_url = (링크 or "").strip()
        m_u = re.search(r"https?://[^\s<>\"']+", raw_url)
        if m_u:
            raw_url = m_u.group(0)
        if "list=rd" in raw_url.lower():
            await ctx.send(
                "⚠️ 유튜브 자동 생성 믹스/라디오(`&list=RD...`) 링크는 유저 맞춤 임시 목록이어서 외부 일괄 가져오기를 지원하지 않습니다.\n"
                "유튜브 정규 공개 플레이리스트(`https://www.youtube.com/playlist?list=PL...`) 링크를 입력하시거나, 개별 곡 링크로 담아주세요!"
            )
            return

        is_pl, plat = core.is_playlist_url(raw_url, allow_watch_with_list=True)
        if not is_pl:
            await ctx.send(
                "❌ 유효한 **YouTube, Spotify, SoundCloud** 플레이리스트나 앨범 링크가 아닙니다.\n"
                "• 유튜브: `https://www.youtube.com/playlist?list=...` 또는 `&list=...`\n"
                "• 스포티파이: `https://open.spotify.com/playlist/...` 또는 `.../album/...`\n"
                "• 사운드클라우드: `https://soundcloud.com/.../sets/...`"
            )
            return

        status_msg = await ctx.send(f"⏳ **{plat}** 플레이리스트 링크에서 수록곡을 추출하는 중입니다...")
        meta, tracks, err = await core.extract_playlist_from_url(raw_url, max_tracks=100)
        if err or not tracks:
            await status_msg.edit(content=f"❌ 플레이리스트에서 곡을 추출하지 못했습니다: {err or '수록곡 없음'}")
            return

        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, ctx.author.id, ctx.author.display_name)
        try:
            target_pl, count, action_msg = core.import_playlist_into_profile_sync(
                prof, ctx.author.display_name, meta, tracks, target_pl_id=None, custom_name=이름
            )
        except Exception as e:
            await status_msg.edit(content=f"❌ 플레이리스트 생성 실패: {e}")
            return

        await asyncio.to_thread(core.save_data, data)
        studio = PlaylistStudioView(ctx.author, ctx.author, data, initial_pl_id=target_pl["id"])
        embed = studio.build_embed()
        embed.set_author(name=f"🎉 플레이리스트 일괄 가져오기 완료! ({meta['platform']})", icon_url=ctx.author.display_avatar.url)
        await status_msg.edit(
            content=f"🎉 **{action_msg}**\n하단의 **`[🔊 음성채널 순차 자동재생]`** 버튼을 눌러 바로 감상하실 수 있습니다 ✨",
            embed=embed,
            view=studio
        )
        studio.message = status_msg

    @commands.command(name="플리곡삭제", aliases=["플리삭제", "곡삭제", "deltrack", "trackdel"])
    async def prefix_delete_track(self, ctx: commands.Context, *, 곡번호또는이름: Optional[str] = None):
        """채팅창에 !플리삭제 [번호 또는 곡제목] 입력 시 해당 곡 즉시 삭제 (미입력 시 곡 선택 삭제창 호출)"""
        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, ctx.author.id, ctx.author.display_name)
        pls = core.ensure_user_playlists(prof, ctx.author.display_name)
        target_pl = pls[0]
        tracks = target_pl.get("tracks", [])

        if not tracks:
            await ctx.send(f"📭 **`{target_pl['emoji']} {target_pl['name']}`**에 삭제할 곡이 없습니다.")
            return

        studio = PlaylistStudioView(ctx.author, ctx.author, data, initial_pl_id=target_pl["id"])

        if not 곡번호또는이름 or not 곡번호또는이름.strip():
            del_view = PlaylistTrackDeleteView(studio)
            msg = await ctx.send(del_view.build_content(), view=del_view)
            del_view.parent_message = msg
            return

        raw_in = 곡번호또는이름.strip()
        indices = _parse_index_spec(raw_in, len(tracks))
        if indices:
            idx_set = set(indices)
            removed = [t for i, t in enumerate(tracks) if i in idx_set]
            target_pl["tracks"] = [t for i, t in enumerate(tracks) if i not in idx_set]
        else:
            kw = raw_in.lower()
            removed = []
            kept = []
            for t in tracks:
                if kw in str(t.get("title", "")).lower() or kw in str(t.get("artist", "")).lower():
                    removed.append(t)
                else:
                    kept.append(t)
            if not removed:
                await ctx.send(
                    f"❌ **`{target_pl['name']}`**에서 **`{곡번호또는이름}`**에 해당하는 곡 번호나 제목을 찾지 못했습니다.\n"
                    f"• 번호 예시: `!플리삭제 3` 또는 `!플리삭제 1, 4, 7-10`"
                )
                return
            target_pl["tracks"] = kept

        target_pl["updated_at"] = core.get_today_str()
        await _commit_and_refresh_studio(studio, data)
        await ctx.send(
            f"✅ **`{target_pl['emoji']} {target_pl['name']}`**에서 **{len(removed)}곡**을 삭제했습니다! (남은 곡: {len(target_pl['tracks'])}곡)\n"
            f"{_format_removed_preview(removed)}"
        )

    @commands.command(name="헤드셋", aliases=["deaf", "청각차단", "헤드폰"])
    async def prefix_headset_toggle(self, ctx: commands.Context):
        """채팅창에 !헤드셋 입력 시 봇의 헤드셋 끄기(청각 차단 / deafen) 즉시 토글"""
        if not ctx.guild:
            return
        player = get_voice_player(self.bot, ctx.guild)
        new_state = await player.toggle_deafen()
        st = "🎧 **헤드셋 끄기 (청각 차단 On / 빨간 사선)**" if new_state else "🔊 **헤드셋 켜기 (청각 차단 Off / 일반)**"
        await ctx.send(f"✅ 봇의 음성 상태가 {st} 상태로 변경되었습니다.")

    @commands.command(name="배속", aliases=["속도", "speed", "배속설정"])
    async def prefix_playback_speed(self, ctx: commands.Context, 속도: Optional[str] = None):
        """채팅창에 !배속 [0.5 ~ 2.0] 입력 시 음성 재생 배속 변경 (기본값: 1.0)"""
        if not ctx.guild:
            return
        player = get_voice_player(self.bot, ctx.guild)
        if not 속도 or not 속도.strip():
            cur = getattr(player, "playback_speed", 1.0)
            await ctx.send(f"⚡ 현재 재생 배속: **`{cur}x`** (기본: `1.0x`)\n• 변경 예시: `!배속 1.25` 또는 `!배속 1.5`, `!배속 1.0`")
            return
        try:
            val = float(속도.replace("x", "").replace("배", "").strip())
        except ValueError:
            await ctx.send("❌ 유효한 숫자를 입력해 주세요! (예: `!배속 1.25`, `!배속 1.5`, `!배속 1.0`)")
            return
        ok, msg = await player.set_playback_speed(val)
        await ctx.send(f"✅ {msg}")




async def setup(bot):
    try:
        core.ensure_opus_loaded()
    except Exception:
        pass
    await bot.add_cog(MusicCog(bot))
