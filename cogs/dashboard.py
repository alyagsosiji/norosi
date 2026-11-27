"""
cogs/dashboard.py - norosi 통합 설정 (/설정) 컨트롤 허브 (Component V2 스타일 계층형 내비게이션 & 통합 페이지네이션)
- 1단계 (홈): [🌐 일반] · [⚙️ 고급] · [🎮 미니게임] · [👤 개인] 4대 메인 카테고리 버튼 + 개인 커스텀 즐겨찾기 단축바 + 통합 페이지네이션
- 2단계 (카테고리 내부): 카테고리별 세부 기능 버튼 (페이지당 6개, 총 15페이지 · 90개 기능) + [⬅️ 뒤로가기] + [◀ 이전 / 📄 현재·통합 / 다음 ▶]
- 3단계 (세부 제어판): 도감/랭킹/티켓/픽업/백업/초기화 등 하위 버튼 패널 + [⬅️ 뒤로가기] + [🏠 설정 홈으로]
- 권한 3단계 완벽 분리: [👤 일반 이용자] / [🛡️ 서버 관리자] / [👑 봇 주인] 배지 표시 및 서버 측 이중 권한 검증
"""

import os
import re
import copy
import random
import asyncio
import datetime
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, Callable, Awaitable, List, Dict, Any, Tuple

import core
import genshin_core
import hsr_core
import fishing_core
import economy_core
import life_core
import other_life_core
import community_core
import routine_core

from cogs import (
    gacha,
    genshin,
    hsr,
    fishing,
    economy,
    life,
    other_life,
    community,
    dday,
    music,
    roles,
    logger,
    stats,
    emoji_upscale,
    routine,
    help as help_cog,
)


# ==========================================
# 권한 등급 상수 및 헬퍼 함수
# ==========================================
PERM_USER = "user"      # 👤 일반 이용자 (누구나 사용 가능)
PERM_ADMIN = "admin"    # 🛡️ 서버 관리자 (Administrator / Manage Guild / Manage Roles / Manage Channels / Manage Messages)
PERM_OWNER = "owner"    # 👑 봇 주인 (Bot Owner 전용 시스템/글로벌 픽업/백업/터미널 제어)

PERM_BADGES = {
    PERM_USER: "👤 일반 이용자",
    PERM_ADMIN: "🛡️ 서버 관리자 전용",
    PERM_OWNER: "👑 봇 주인 전용",
}

PERM_SHORT_BADGES = {
    PERM_USER: "👤일반",
    PERM_ADMIN: "🛡️관리자",
    PERM_OWNER: "👑봇주인",
}

CATEGORY_ORDER = ["general", "advanced", "minigame", "personal"]

CATEGORY_INFO = {
    "general": {
        "label": "🌐 일반",
        "title": "🌐 일반 설정 & 공통 기능",
        "emoji": "🌐",
        "perm_summary": "👤 일반 이용자 (누구나 사용 가능)",
        "color": (0, 204, 221),
        "short_desc": "출석체크 · 달력 · D-Day · 생일 · 프로세카 미래시 · 음악 · 날씨 · 서버통계 · 파티모집",
    },
    "advanced": {
        "label": "⚙️ 고급",
        "title": "⚙️ 고급 설정 (서버 관리자 & 봇 주인 제어판)",
        "emoji": "⚙️",
        "perm_summary": "🛡️ 서버 관리자 (1~3p)  ·  👑 봇 주인 전용 (4p)",
        "color": (237, 66, 69),
        "short_desc": "역할버튼 · 반응역할 · 공지 · 1:1티켓 · 임시음성방 · 고정글 · 레이드방어 · 업스케일 · 감사로그 · 백업 · 픽업",
    },
    "minigame": {
        "label": "🎮 미니게임",
        "title": "🎮 미니게임 & 4대 가챠/생활 허브",
        "emoji": "🎮",
        "perm_summary": "👤 일반 이용자 (누구나 플레이 가능)",
        "color": (87, 242, 135),
        "short_desc": "프로세카 · 원신 · 스타레일 · 통합 낚시 & 대회 · 농장/펫/요리 · 타인의 삶 · 끝말잇기 · 룰렛 · 도감/랭킹",
    },
    "personal": {
        "label": "👤 개인",
        "title": "👤 개인 맞춤 설정 & 보관함/집중 허브",
        "emoji": "👤",
        "perm_summary": "👤 일반 이용자 (본인 데이터 관리)",
        "color": (155, 89, 182),
        "short_desc": "통합 PNG 프로필카드 · 오시 · 칭호/배지 · 송금 · 4대 보관함 & 덱/파티 · 오늘목표 · 집중모드 · 비밀디데이 · 파트너",
    },
}

# 3단계 세부 제어판(sub_mode) → 직속 부모 (카테고리, 페이지 인덱스) 매핑
# 봇 재시작·구버전 메시지 복구 시에도 홈이 아닌 직전 부모 페이지로 복귀하도록 보장합니다.
SUB_MODE_PARENT_MAP: Dict[str, Tuple[str, int]] = {
    "admin_dday": ("advanced", 2),
    "admin_music_sched": ("advanced", 2),
    "admin_reset": ("advanced", 2),
    "admin_sticky": ("advanced", 1),
    "admin_ticket": ("advanced", 0),
    "bday_partner": ("personal", 2),
    "fishing_personal": ("personal", 1),
    "gi_banner_hub": ("minigame", 1),
    "gi_personal": ("personal", 1),
    "hsr_banner_hub": ("minigame", 1),
    "hsr_personal": ("personal", 1),
    "life_personal_hub": ("minigame", 2),
    "music_voice": ("general", 1),
    "owner_backup_sync": ("advanced", 3),
    "owner_gi_pickup": ("advanced", 3),
    "owner_hsr_pickup": ("advanced", 3),
    "owner_sekai_pickup": ("advanced", 3),
    "owner_terminal": ("advanced", 3),
    "pokedex_hub": ("minigame", 3),
    "ranking_hub": ("minigame", 3),
    "relay_novel": ("general", 2),
    "sekai_deck": ("personal", 1),
    "sekai_pull_hub": ("minigame", 0),
    "sekai_schedule": ("general", 0),
}

_NAV_CAT_TO_CODE: Dict[str, str] = {
    "home": "h",
    "general": "g",
    "advanced": "a",
    "minigame": "m",
    "personal": "p",
}
_NAV_CODE_TO_CAT: Dict[str, str] = {v: k for k, v in _NAV_CAT_TO_CODE.items()}


def detect_user_perm_tier_sync(user: Optional[discord.abc.User], guild: Optional[discord.Guild]) -> str:
    """동기 컨텍스트(임베드/버튼 렌더링)에서 호출자의 권한 등급(owner / admin / user) 판별"""
    if not user:
        return PERM_USER
    if core.BOT_OWNER_ID and user.id == core.BOT_OWNER_ID:
        return PERM_OWNER
    extra_owners = os.getenv("BOT_OWNER_IDS", "")
    if extra_owners:
        try:
            owner_ids = {int(x.strip()) for x in extra_owners.split(",") if x.strip().isdigit()}
            if user.id in owner_ids:
                return PERM_OWNER
        except Exception:
            pass
    if guild:
        if getattr(guild, "owner_id", None) == user.id:
            return PERM_ADMIN
        perms = getattr(user, "guild_permissions", None)
        if perms and (
            perms.administrator
            or perms.manage_guild
            or perms.manage_roles
            or perms.manage_channels
            or perms.manage_messages
        ):
            return PERM_ADMIN
    return PERM_USER


# ==========================================
# 📝 대시보드 전용 보조 모달 & 선택 뷰
# ==========================================
class DashboardDDayAddModal(core.SafeModal, title="📅 새 D-Day 일정 & 전광판 채널 등록"):
    d_name = discord.ui.TextInput(
        label="D-Day 일정 이름",
        placeholder="예: 기말고사, 프로세카 주년, 자격증 시험",
        required=True,
        max_length=40,
    )
    d_date = discord.ui.TextInput(
        label="목표 날짜 (YYYY-MM-DD)",
        placeholder="예: 2026-12-25",
        required=True,
        max_length=10,
    )
    d_emoji = discord.ui.TextInput(
        label="대표 이모지 (선택, 기본: 🌠)",
        placeholder="예: 🌠, 🔥, 🎂, 🎯",
        required=False,
        default="🌠",
        max_length=5,
    )
    d_plus_one = discord.ui.TextInput(
        label="지나간 날짜 +1일 / 매년반복 옵션 (선택)",
        placeholder="+1일 계산 시 '+1', 매년 반복 시 '반복' 입력 (예: +1 반복)",
        required=False,
        max_length=20,
    )
    d_channel_opt = discord.ui.TextInput(
        label="전광판 음성채널 자동 생성 여부 (예/아니오)",
        placeholder="기본 '예' (채널 생성을 원치 않으면 '아니오' 입력)",
        default="예",
        required=False,
        max_length=10,
    )

    def __init__(self, dashboard_view: "MasterDashboardView"):
        super().__init__()
        self.dashboard_view = dashboard_view

    async def on_submit(self, interaction: discord.Interaction):
        name_val = self.d_name.value.strip()
        date_val = self.d_date.value.strip()
        emoji_val = self.d_emoji.value.strip() or "🌠"
        opt_raw = (self.d_plus_one.value or "").strip().lower()
        use_plus_one = any(k in opt_raw for k in ("+1", "예", "y", "yes", "true", "적용"))
        use_repeat = any(k in opt_raw for k in ("반복", "매년", "repeat", "annual"))
        ch_raw = (self.d_channel_opt.value or "예").strip().lower()
        make_channel = ch_raw not in ("아니오", "n", "no", "false", "0", "끄기", "안함")

        try:
            datetime.datetime.strptime(date_val, "%Y-%m-%d")
        except ValueError:
            await core.safe_send_response(
                interaction,
                "❌ 날짜 형식이 올바르지 않습니다. `YYYY-MM-DD` (예: `2026-12-25`) 형식으로 입력해 주세요.",
                ephemeral=True,
            )
            return

        bot_ref = self.dashboard_view.bot or interaction.client
        dday_cog = next((c for c in bot_ref.cogs.values() if hasattr(c, "_create_or_update_dday")), None)
        if dday_cog:
            if make_channel and interaction.guild is not None:
                from cogs.dday import DDayCategoryPickView
                pick_view = DDayCategoryPickView(
                    bot_instance=bot_ref,
                    user=interaction.user,
                    guild=interaction.guild,
                    pending_dday={
                        "name": name_val,
                        "date": date_val,
                        "emoji": emoji_val,
                        "repeat": use_repeat,
                        "plus_one": use_plus_one,
                    },
                    parent_view=self.dashboard_view,
                    mode="create",
                )
                await core.safe_send_response(
                    interaction,
                    embed=pick_view.build_embed(),
                    view=pick_view,
                    ephemeral=True,
                )
                return

            await dday_cog._create_or_update_dday(
                interaction,
                이름=name_val,
                날짜=date_val,
                카테고리=None,
                이모지=emoji_val,
                시작일=None,
                매년반복=use_repeat,
                채널생성=False,
                플러스1=use_plus_one,
            )
            self.dashboard_view.data = await asyncio.to_thread(core.load_data)
            self.dashboard_view.refresh_components()
            if self.dashboard_view.message:
                try:
                    await self.dashboard_view.message.edit(
                        embed=self.dashboard_view.build_current_embed(),
                        view=self.dashboard_view,
                    )
                except Exception:
                    pass
            return

        await core.safe_defer(interaction, ephemeral=True)
        try:
            datetime.datetime.strptime(date_val, "%Y-%m-%d")
        except ValueError:
            await interaction.followup.send(
                "❌ 날짜 형식이 올바르지 않습니다. `YYYY-MM-DD` (예: `2026-12-25`) 형식으로 입력해 주세요.",
                ephemeral=True,
            )
            return

        def _save_dday():
            with core._DATA_LOCK:
                data = core.load_data()
                ddays_dict = core.ensure_dict_path(data, "ddays")
                s_key = core.resolve_dday_storage_key(ddays_dict, name_val, interaction.guild_id)
                existing = core.as_dict(ddays_dict.get(s_key))
                ddays_dict[s_key] = {
                    "display_name": name_val,
                    "date": date_val,
                    "start_date": existing.get("start_date") or min(core.get_today_str(), date_val),
                    "emoji": emoji_val,
                    "channel_id": existing.get("channel_id"),
                    "category_id": existing.get("category_id"),
                    "guild_id": interaction.guild_id or existing.get("guild_id"),
                    "repeat": use_repeat,
                    "plus_one": use_plus_one,
                }
                core.save_data(data)
                return data

        data = await asyncio.to_thread(_save_dday)
        _, dday_str = core.get_dday_info(date_val, plus_one=use_plus_one)
        self.dashboard_view.data = data
        self.dashboard_view.refresh_components()
        await interaction.followup.send(
            f"✅ **{emoji_val} {name_val}** 일정이 성공적으로 등록되었습니다! (현재 상태: **`{dday_str}`**)",
            ephemeral=True,
        )


class DashboardPomodoroModal(core.SafeModal, title="⏳ 뽀모도로 집중모드 타이머 시작"):
    focus_min = discord.ui.TextInput(
        label="집중 시간 (분, 1~180)",
        placeholder="예: 25",
        default="25",
        required=True,
        max_length=3,
    )
    break_min = discord.ui.TextInput(
        label="휴식 시간 (분, 1~60)",
        placeholder="예: 5",
        default="5",
        required=True,
        max_length=2,
    )
    cycles = discord.ui.TextInput(
        label="반복 세트 수 (1~10)",
        placeholder="예: 4",
        default="2",
        required=True,
        max_length=2,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        try:
            f_m = max(1, min(180, int(self.focus_min.value.strip())))
            b_m = max(1, min(60, int(self.break_min.value.strip())))
            c_cnt = max(1, min(10, int(self.cycles.value.strip())))
        except ValueError:
            await core.safe_send_response(interaction, "❌ 시간과 세트 수는 숫자로만 입력해 주세요.", ephemeral=True)
            return

        target_cog = next((c for c in self.bot.cogs.values() if hasattr(c, "pomodoro_cmd")), None)
        if target_cog:
            choice_start = app_commands.Choice(name="▶️ 집중모드 시작", value="start")
            await target_cog.pomodoro_cmd.callback(
                target_cog,
                interaction,
                동작=choice_start,
                집중시간=f_m,
                휴식시간=b_m,
                세트수=c_cnt,
                음성채널=None,
            )
        else:
            await core.safe_send_response(interaction, "❌ 집중모드 모듈을 찾을 수 없습니다.", ephemeral=True)


class DashboardHardcoreStudyModal(core.SafeModal, title="🔥 하드코어 스터디 타이머 시작"):
    study_goal = discord.ui.TextInput(
        label="오늘의 집중 스터디 목표",
        placeholder="예: 자격증 기출 2회독 / 알고리즘 코딩 / 시험 공부",
        default="자격증 / 집중 코딩",
        required=True,
        max_length=60,
    )
    target_min = discord.ui.TextInput(
        label="목표 집중 시간 (분, 50~600)",
        placeholder="예: 100 (50분 집중 + 10분 휴식 사이클)",
        default="100",
        required=True,
        max_length=3,
    )
    voice_opts = discord.ui.TextInput(
        label="음성 안내 & 자동 음소거 옵션 (기본: 둘다 켜기)",
        placeholder="'안내끄기' 또는 '음소거끄기' 입력 가능 (비우면 둘 다 ON)",
        required=False,
        max_length=30,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        try:
            t_min = max(50, min(600, int(self.target_min.value.strip())))
        except ValueError:
            t_min = 100
        opt_raw = (self.voice_opts.value or "").strip().lower()
        use_tts = "안내끄" not in opt_raw
        use_mute = "음소거끄" not in opt_raw

        target_cog = next((c for c in self.bot.cogs.values() if hasattr(c, "hardcore_study_cmd")), None)
        if target_cog:
            choice_start = app_commands.Choice(name="🔥 하드코어 스터디 시작", value="start")
            await target_cog.hardcore_study_cmd.callback(
                target_cog,
                interaction,
                동작=choice_start,
                목표=self.study_goal.value.strip() or "자격증 / 집중 코딩",
                목표시간=t_min,
                음성채널=None,
                음성안내=use_tts,
                자동음소거=use_mute,
            )
        else:
            await core.safe_send_response(interaction, "❌ 스터디 모듈을 찾을 수 없습니다.", ephemeral=True)


class DashboardInactiveAuditModal(core.SafeModal, title="👻 비활성(잠수) 유저 스캔"):
    days_input = discord.ui.TextInput(
        label="비활성 기준 미활동 일수 (7 / 14 / 30 / 60 / 90)",
        placeholder="예: 30 (최근 30일 이상 출석/채팅 기록 없는 멤버 조회)",
        default="30",
        required=True,
        max_length=3,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        try:
            d_val = max(1, min(365, int(self.days_input.value.strip())))
        except ValueError:
            d_val = 30

        target_cog = next((c for c in self.bot.cogs.values() if hasattr(c, "inactive_users_cmd")), None)
        if target_cog:
            choice_days = app_commands.Choice(name=f"⏳ 최근 {d_val}일 이상 미활동", value=d_val)
            await target_cog.inactive_users_cmd.callback(target_cog, interaction, 기준일수=choice_days)
        else:
            await core.safe_send_response(interaction, "❌ 감사 모듈을 찾을 수 없습니다.", ephemeral=True)


class DashboardMessagePurgeModal(core.SafeModal, title="🧹 채널 메시지 조건부 일괄 청소"):
    count_input = discord.ui.TextInput(
        label="검사 및 삭제할 메시지 개수 (1~100)",
        placeholder="예: 30",
        default="20",
        required=True,
        max_length=3,
    )
    keyword_input = discord.ui.TextInput(
        label="포함 키워드 필터 (선택, 비워두면 전체 대상)",
        placeholder="특정 단어가 포함된 메시지만 지우려면 입력",
        required=False,
        max_length=60,
    )
    bot_only_input = discord.ui.TextInput(
        label="세부 필터 (봇 / 미디어 / 특정유저 닉네임·ID)",
        placeholder="'봇', '미디어(사진/파일)', 또는 특정 유저명/ID 입력",
        required=False,
        max_length=40,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        perms = interaction.user.guild_permissions
        is_owner = await self.bot.is_bot_owner_user(interaction.user)
        if not (perms.administrator or perms.manage_messages or is_owner):
            await core.safe_send_response(interaction, "❌ **메시지 관리(Manage Messages)** 또는 **서버 관리자** 권한이 필요합니다.", ephemeral=True)
            return

        try:
            limit_cnt = max(1, min(100, int(self.count_input.value.strip())))
        except ValueError:
            await core.safe_send_response(interaction, "❌ 삭제할 메시지 개수는 1~100 사이의 숫자로 입력해 주세요.", ephemeral=True)
            return

        kw = (self.keyword_input.value or "").strip() or None
        flt_raw = (self.bot_only_input.value or "").strip()
        flt_low = flt_raw.lower()
        bots_only = flt_low in ("예", "y", "yes", "true", "1", "bot", "봇")
        media_only = flt_low in ("미디어", "media", "사진", "파일", "첨부", "이미지")
        target_user_id: Optional[int] = None
        target_user_name_q: Optional[str] = None
        if flt_raw and not bots_only and not media_only:
            clean_id = flt_raw.strip("<@!>")
            if clean_id.isdigit():
                target_user_id = int(clean_id)
            else:
                target_user_name_q = flt_low

        if not isinstance(interaction.channel, (discord.TextChannel, discord.VoiceChannel, discord.Thread)):
            await core.safe_send_response(interaction, "❌ 텍스트 채널 또는 스레드에서만 사용할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)

        def _check(m: discord.Message) -> bool:
            if bots_only and not m.author.bot:
                return False
            if media_only and not (m.attachments or m.embeds):
                return False
            if target_user_id is not None and m.author.id != target_user_id:
                return False
            if target_user_name_q and (
                target_user_name_q not in m.author.display_name.lower()
                and target_user_name_q not in m.author.name.lower()
            ):
                return False
            if kw and kw.lower() not in (m.content or "").lower():
                return False
            return True

        try:
            deleted = await interaction.channel.purge(limit=limit_cnt, check=_check)
            await interaction.followup.send(
                f"🧹 {interaction.channel.mention} 채널에서 최근 `{limit_cnt}개` 메시지 중 조건에 맞는 **`{len(deleted)}개`** 메시지를 삭제했습니다!",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ 봇에게 `메시지 관리(Manage Messages)` 권한이 없습니다.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 메시지 청소 중 오류 발생: `{e}`", ephemeral=True)


class DashboardSekaiSearchModal(core.SafeModal, title="🔍 내 보유 프로세카 카드 키워드 검색"):
    keyword = discord.ui.TextInput(
        label="검색할 캐릭터 이름, 카드명, 유닛 또는 등급",
        placeholder="예: 카나데, 미쿠, 니고, ★4, 생일, 페스",
        required=True,
        max_length=50,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        gacha_cog = next((c for c in self.bot.cogs.values() if hasattr(c, "my_characters_cmd")), None)
        if gacha_cog:
            await gacha_cog.my_characters_cmd.callback(
                gacha_cog,
                interaction,
                유저=None,
                캐릭터=None,
                검색어=self.keyword.value.strip(),
            )
        else:
            await core.safe_send_response(interaction, "❌ 가챠 모듈을 찾을 수 없습니다.", ephemeral=True)


class DashboardTicketCustomPanelModal(core.SafeModal, title="🎫 커스텀 1:1 문의 티켓 패널 생성"):
    panel_title = discord.ui.TextInput(
        label="티켓 패널 임베드 제목",
        placeholder="예: 🎫 서버 운영진 1:1 비공개 문의 & 건의 센터",
        default="🎫 1:1 비공개 문의 & 건의 티켓 센터",
        required=True,
        max_length=80,
    )
    panel_desc = discord.ui.TextInput(
        label="티켓 패널 안내 설명 문구",
        style=discord.TextStyle.paragraph,
        placeholder="예: 아래 [📩 1:1 문의 열기] 버튼을 누르면 운영진과 본인만 볼 수 있는 비공개 티켓 채널이 열립니다.",
        required=False,
        max_length=800,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        ticket_cog = next((c for c in self.bot.cogs.values() if hasattr(c, "ticket_panel_cmd")), None)
        if ticket_cog:
            await ticket_cog.ticket_panel_cmd.callback(
                ticket_cog,
                interaction,
                채널=interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None,
                제목=self.panel_title.value.strip(),
                설명=(self.panel_desc.value or "").strip() or None,
            )
        else:
            await core.safe_send_response(interaction, "❌ 티켓 모듈을 찾을 수 없습니다.", ephemeral=True)


class DashboardTicketMemberModal(core.SafeModal, title="👥 현재 티켓 채널에 멤버 추가/제거"):
    member_query = discord.ui.TextInput(
        label="대상 멤버 닉네임, @멘션 또는 디스코드 ID",
        placeholder="예: @홍길동 또는 123456789012345678",
        required=True,
        max_length=50,
    )
    action_type = discord.ui.TextInput(
        label="동작 선택 ('추가' 또는 '제거')",
        placeholder="티켓에 초대하려면 '추가', 내보내려면 '제거' 입력",
        default="추가",
        required=True,
        max_length=10,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 티켓 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        q_raw = self.member_query.value.strip()
        clean_id = q_raw.strip("<@!>")
        target_member = None
        if clean_id.isdigit():
            target_member = interaction.guild.get_member(int(clean_id))
        if target_member is None:
            q_low = q_raw.lower()
            target_member = next(
                (m for m in interaction.guild.members if q_low in m.display_name.lower() or q_low in m.name.lower()),
                None,
            )
        if target_member is None:
            await core.safe_send_response(interaction, f"❌ 서버에서 `{q_raw}` 멤버를 찾을 수 없습니다.", ephemeral=True)
            return

        act_raw = (self.action_type.value or "추가").strip().lower()
        is_remove = act_raw in ("제거", "삭제", "내보내기", "remove", "del", "out")
        ticket_cog = next((c for c in self.bot.cogs.values() if hasattr(c, "ticket_add_member_cmd")), None)
        if not ticket_cog:
            await core.safe_send_response(interaction, "❌ 티켓 모듈을 찾을 수 없습니다.", ephemeral=True)
            return
        if is_remove and hasattr(ticket_cog, "ticket_remove_member_cmd"):
            await ticket_cog.ticket_remove_member_cmd.callback(ticket_cog, interaction, 멤버=target_member)
        else:
            await ticket_cog.ticket_add_member_cmd.callback(ticket_cog, interaction, 멤버=target_member)


class DashboardMorningMusicPrefsModal(core.SafeModal, title="🌅 오전 7시 모닝 음악 추천 상세 설정"):
    platform_input = discord.ui.TextInput(
        label="추천 플랫폼 (all / youtube / spotify / soundcloud)",
        placeholder="예: all, youtube, spotify, soundcloud",
        default="all",
        required=True,
        max_length=20,
    )
    genre_input = discord.ui.TextInput(
        label="선호 음악 장르/분위기 (선택)",
        placeholder="예: 프로세카, 보컬로이드, J-POP, 시티팝, 로파이",
        required=False,
        max_length=80,
    )
    artist_input = discord.ui.TextInput(
        label="선호 아티스트/유닛 (선택)",
        placeholder="예: 25시 밤 코드로, 하츠네 미쿠, YOASOBI",
        required=False,
        max_length=80,
    )
    playlist_url = discord.ui.TextInput(
        label="커스텀 플레이리스트 링크 (선택, 초기화는 '초기화')",
        placeholder="유튜브/스포티파이/사클 플리 URL (지정 시 해당 플리에서 선곡)",
        required=False,
        max_length=300,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        music_cog = next((c for c in self.bot.cogs.values() if hasattr(c, "set_music_prefs")), None)
        if not music_cog:
            await core.safe_send_response(interaction, "❌ 음악 모듈을 찾을 수 없습니다.", ephemeral=True)
            return
        plat_raw = (self.platform_input.value or "all").strip().lower()
        plat_map = {
            "all": "랜덤 (YouTube + Spotify + SoundCloud)",
            "youtube": "유튜브 (YouTube) 전용",
            "spotify": "스포티파이 (Spotify) 전용",
            "soundcloud": "사운드클라우드 (SoundCloud) 전용",
        }
        if plat_raw not in plat_map:
            plat_raw = "all"
        p_choice = app_commands.Choice(name=plat_map[plat_raw], value=plat_raw)
        ch_obj = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None
        if ch_obj is None and interaction.guild and interaction.guild.text_channels:
            ch_obj = interaction.guild.text_channels[0]
        if ch_obj is None:
            await core.safe_send_response(interaction, "❌ 모닝 음악을 전송할 텍스트 채널을 찾을 수 없습니다.", ephemeral=True)
            return
        raw_pl = (self.playlist_url.value or "").strip()
        if raw_pl.lower() in ("초기화", "제거", "삭제", "reset", "none", "clear"):
            raw_pl = ""
        await music_cog.set_music_prefs.callback(
            music_cog,
            interaction,
            채널=ch_obj,
            플랫폼=p_choice,
            장르=(self.genre_input.value or "").strip() or None,
            아티스트=(self.artist_input.value or "").strip() or None,
            플레이리스트링크=raw_pl or None,
        )


class DashboardGenshinProfileModal(core.SafeModal, title="✏️ 원신 여행자 프로필 설정"):
    fav_char = discord.ui.TextInput(
        label="대표(오시) 원신 캐릭터 이름 (선택)",
        placeholder="예: 푸리나, 나히다, 라이덴 쇼군, 아를레키노",
        required=False,
        max_length=40,
    )
    bio_text = discord.ui.TextInput(
        label="여행자 상태 메시지 (선택, 최대 60자)",
        placeholder="예: 별과 심연을 향하여! 픽뚫 없는 기원 기원합니다 ✨",
        required=False,
        max_length=60,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        gi_cog = self.bot.get_cog("GenshinCog")
        if gi_cog and hasattr(gi_cog, "profile_cmd"):
            fav_raw = (self.fav_char.value or "").strip() or None
            resolved_fav = fav_raw
            if fav_raw:
                data = core.get_cached_data()
                u_data = genshin_core.ensure_genshin_user(data, interaction.guild_id or 0, interaction.user.id)
                u_items = core.as_dict(u_data.get("items"))
                matched_k = next(
                    (
                        k for k, v in u_items.items()
                        if isinstance(v, dict)
                        and v.get("kind") == "char"
                        and (k == fav_raw or fav_raw.lower() in str(v.get("name", "")).lower())
                    ),
                    fav_raw,
                )
                resolved_fav = matched_k
            await gi_cog.profile_cmd.callback(
                gi_cog,
                interaction,
                대상=None,
                대표캐릭터=resolved_fav,
                상태문구=(self.bio_text.value or "").strip() or None,
            )
        else:
            await core.safe_send_response(interaction, "❌ 원신 모듈을 찾을 수 없습니다.", ephemeral=True)


class DashboardHSRProfileModal(core.SafeModal, title="✏️ 스타레일 개척자 프로필 설정"):
    fav_char = discord.ui.TextInput(
        label="대표(오시) 스타레일 캐릭터 이름 (선택)",
        placeholder="예: 반디, 아케론, 카프카, 비소, 로빈",
        required=False,
        max_length=40,
    )
    bio_text = discord.ui.TextInput(
        label="개척자 상태 메시지 (선택, 최대 60자)",
        placeholder="예: 이 여정이 언젠가 뭇별에 닿기를! 🚂",
        required=False,
        max_length=60,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        hsr_cog = self.bot.get_cog("HSRCog")
        if hsr_cog and hasattr(hsr_cog, "profile_cmd"):
            fav_raw = (self.fav_char.value or "").strip() or None
            resolved_fav = fav_raw
            if fav_raw:
                data = core.get_cached_data()
                u_data = hsr_core.ensure_hsr_user(data, interaction.guild_id or 0, interaction.user.id)
                u_items = core.as_dict(u_data.get("items"))
                matched_k = next(
                    (
                        k for k, v in u_items.items()
                        if isinstance(v, dict)
                        and v.get("kind") == "char"
                        and (k == fav_raw or fav_raw.lower() in str(v.get("name", "")).lower())
                    ),
                    fav_raw,
                )
                resolved_fav = matched_k
            await hsr_cog.profile_cmd.callback(
                hsr_cog,
                interaction,
                대상=None,
                대표캐릭터=resolved_fav,
                상태문구=(self.bio_text.value or "").strip() or None,
            )
        else:
            await core.safe_send_response(interaction, "❌ 스타레일 모듈을 찾을 수 없습니다.", ephemeral=True)


class DashboardSekaiOwnerPickupModal(core.SafeModal, title="🎛️ [봇주인] 프로세카 수동 픽업 배너 설정"):
    mode_input = discord.ui.TextInput(
        label="배너 모드 (normal / fes / birthday / auto_event)",
        placeholder="normal(일반), fes(페스 ★4 2배), birthday(생일), auto_event",
        default="normal",
        required=True,
        max_length=20,
    )
    unit_input = discord.ui.TextInput(
        label="픽업 유닛 선택 (선택, 예: 25시, 나이트 코드에서.)",
        placeholder="버츄얼 싱어 / Leo/need / MORE MORE JUMP! / Vivid BAD SQUAD 등",
        required=False,
        max_length=40,
    )
    chars_input = discord.ui.TextInput(
        label="픽업 대상 캐릭터 이름 (선택)",
        placeholder="예: 요이사키 카나데",
        required=False,
        max_length=120,
    )
    limited_and_title = discord.ui.TextInput(
        label="한정카드 포함 여부 ('한정포함' 또는 '한정제외', 선택)",
        placeholder="예: 한정포함",
        required=False,
        max_length=100,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        gacha_cog = next((c for c in self.bot.cogs.values() if hasattr(c, "set_pickup_cmd")), None)
        if not gacha_cog:
            await core.safe_send_response(interaction, "❌ 가챠 모듈을 찾을 수 없습니다.", ephemeral=True)
            return
        m_raw = (self.mode_input.value or "normal").strip().lower()
        mode_choice = None
        banner_choice = None
        if m_raw in ("auto_event", "event_sync"):
            mode_choice = app_commands.Choice(name="🎯 현재 한섭 이벤트에 자동 맞추기 (실시간 DB)", value="event_sync")
        elif m_raw == "reset":
            mode_choice = app_commands.Choice(name="🧹 픽업 초기화 (전체 해제)", value="reset")
        else:
            if m_raw not in ("normal", "fes", "birthday"):
                m_raw = "normal"
            banner_choice = app_commands.Choice(name=m_raw, value=m_raw)
            mode_choice = app_commands.Choice(name="🎛️ 수동 설정 (유닛 / 캐릭터 직접 선택)", value="manual")

        u_raw = (self.unit_input.value or "").strip()
        unit_choice = None
        if u_raw:
            unit_list = getattr(core, "UNIT_ORDER", [
                "버츄얼 싱어", "Leo/need", "MORE MORE JUMP!", "Vivid BAD SQUAD", "원더랜즈×쇼타임", "25시, 나이트 코드에서."
            ])
            matched_u = next((u for u in unit_list if u_raw.lower() in u.lower() or u.lower() in u_raw.lower()), u_raw)
            unit_choice = app_commands.Choice(name=matched_u, value=matched_u)

        lt_raw = (self.limited_and_title.value or "").strip()
        inc_lim: bool = True
        if lt_raw:
            left = lt_raw.split("|", 1)[0].strip().lower()
            if left in ("한정제외", "상시만", "false", "no", "0"):
                inc_lim = False

        raw_char = (self.chars_input.value or "").strip()
        if "," in raw_char:
            raw_char = raw_char.split(",", 1)[0].strip()

        await gacha_cog.set_pickup_cmd.callback(
            gacha_cog,
            interaction,
            모드=mode_choice,
            유닛=unit_choice,
            캐릭터=raw_char or None,
            한정포함=inc_lim,
            배너=banner_choice,
        )


class DashboardGenshinOwnerPickupModal(core.SafeModal, title="🎛️ [봇주인] 원신 글로벌 픽업 상세 설정"):
    preset_or_title = discord.ui.TextInput(
        label="프리셋 ID 또는 커스텀 배너 이름 (선택)",
        placeholder="예: time_rotation, latest, fontaine_archon 또는 배너명",
        required=False,
        max_length=80,
    )
    five_stars = discord.ui.TextInput(
        label="5성 픽업 캐릭터 ① / ② (쉼표 구분, 선택)",
        placeholder="예: 푸리나, 나히다 (전반/후반 5성 픽업)",
        required=False,
        max_length=80,
    )
    four_stars = discord.ui.TextInput(
        label="4성 픽업 캐릭터 (쉼표 구분 3명, 선택)",
        placeholder="예: 베넷, 행추, 피슬",
        required=False,
        max_length=80,
    )
    weapons_5 = discord.ui.TextInput(
        label="신의 주조 5성 픽업 무기 2종 (쉼표 구분, 선택)",
        placeholder="예: 고요히 샘솟는 빛, 떠오르는 천일밤의 꿈",
        required=False,
        max_length=100,
    )
    artifacts_5 = discord.ui.TextInput(
        label="성유물 기원 5성 픽업 성유물 (쉼표 구분, 선택)",
        placeholder="예: 황금 극단, 그림자 사냥꾼",
        required=False,
        max_length=100,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        gi_cog = self.bot.get_cog("GenshinCog")
        if not gi_cog or not hasattr(gi_cog, "setup_pickup_cmd"):
            await core.safe_send_response(interaction, "❌ 원신 모듈을 찾을 수 없습니다.", ephemeral=True)
            return
        pt_raw = (self.preset_or_title.value or "").strip()
        preset_keys = set(getattr(genshin_core, "GENSHIN_BANNER_PRESETS", {}).keys()) | {"time_rotation", "reset"}
        preset_val = pt_raw if pt_raw in preset_keys else None
        banner_name = None if preset_val else (pt_raw or None)

        chars, weapons = genshin_core.load_genshin_kr_db()
        def _match_gi_char(q: str) -> Optional[str]:
            if not q:
                return None
            ql = q.lower()
            found = next((c["id"] for c in chars if c["id"].lower() == ql or c.get("name", "").lower() == ql), None)
            if not found:
                found = next((c["id"] for c in chars if ql in c.get("name", "").lower() or ql in c["id"].lower()), q)
            return found

        def _match_gi_weapon(q: str) -> Optional[str]:
            if not q:
                return None
            ql = q.lower()
            found = next((w["id"] for w in weapons if w["id"].lower() == ql or w.get("name", "").lower() == ql), None)
            if not found:
                found = next((w["id"] for w in weapons if ql in w.get("name", "").lower() or ql in w["id"].lower()), q)
            return found

        def _match_gi_art(q: str) -> Optional[str]:
            if not q:
                return None
            ql = q.lower()
            arts = getattr(genshin_core, "GENSHIN_ARTIFACTS", []) or []
            found = next((a["id"] for a in arts if a["id"].lower() == ql or a.get("name", "").lower() == ql), None)
            if not found:
                found = next((a["id"] for a in arts if ql in a.get("name", "").lower() or ql in a["id"].lower()), q)
            return found

        f5_parts = [p.strip() for p in (self.five_stars.value or "").split(",") if p.strip()]
        p5_1 = _match_gi_char(f5_parts[0]) if len(f5_parts) >= 1 else None
        p5_2 = _match_gi_char(f5_parts[1]) if len(f5_parts) >= 2 else None

        f4_parts = [p.strip() for p in (self.four_stars.value or "").split(",") if p.strip()]
        f4_1 = _match_gi_char(f4_parts[0]) if len(f4_parts) >= 1 else None
        f4_2 = _match_gi_char(f4_parts[1]) if len(f4_parts) >= 2 else None
        f4_3 = _match_gi_char(f4_parts[2]) if len(f4_parts) >= 3 else None

        w_parts = [p.strip() for p in (self.weapons_5.value or "").split(",") if p.strip()]
        w1 = _match_gi_weapon(w_parts[0]) if len(w_parts) >= 1 else None
        w2 = _match_gi_weapon(w_parts[1]) if len(w_parts) >= 2 else None

        a_parts = [p.strip() for p in (self.artifacts_5.value or "").split(",") if p.strip()]
        a1 = _match_gi_art(a_parts[0]) if len(a_parts) >= 1 else None
        a2 = _match_gi_art(a_parts[1]) if len(a_parts) >= 2 else None

        await gi_cog.setup_pickup_cmd.callback(
            gi_cog,
            interaction,
            프리셋=preset_val,
            캐릭터1=p5_1,
            캐릭터2=p5_2,
            사성1=f4_1,
            사성2=f4_2,
            사성3=f4_3,
            무기1=w1,
            무기2=w2,
            성유물1=a1,
            성유물2=a2,
            배너이름=banner_name,
        )


class DashboardHSROwnerPickupModal(core.SafeModal, title="🎛️ [봇주인] 스타레일 글로벌 픽업 상세 설정"):
    preset_or_title = discord.ui.TextInput(
        label="프리셋 ID 또는 커스텀 배너 이름 (선택)",
        placeholder="예: time_rotation, latest, penacony_dream, fate_collab",
        required=False,
        max_length=80,
    )
    five_stars = discord.ui.TextInput(
        label="5성 픽업 캐릭터 ① / ② (쉼표 구분, 선택)",
        placeholder="예: 반디, 완·매 (전반/후반 5성 픽업)",
        required=False,
        max_length=80,
    )
    four_stars = discord.ui.TextInput(
        label="4성 픽업 캐릭터 (쉼표 구분 3명, 선택)",
        placeholder="예: 갤러거, 페라, 정운",
        required=False,
        max_length=80,
    )
    lightcones_5 = discord.ui.TextInput(
        label="세월의 응고 5성 픽업 광추 (쉼표 구분, 선택)",
        placeholder="예: 꿈이 어디로 돌아가야 하는지, 거울 속 지난날의 나",
        required=False,
        max_length=100,
    )
    relics_5 = discord.ui.TextInput(
        label="터널 유물 5성 픽업 세트 (쉼표 구분, 선택)",
        placeholder="예: 곤충 재앙을 잠재우는 철기군, 선구자",
        required=False,
        max_length=100,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        hsr_cog = self.bot.get_cog("HSRCog")
        if not hsr_cog or not hasattr(hsr_cog, "setup_pickup_cmd"):
            await core.safe_send_response(interaction, "❌ 스타레일 모듈을 찾을 수 없습니다.", ephemeral=True)
            return
        pt_raw = (self.preset_or_title.value or "").strip()
        preset_keys = set(getattr(hsr_core, "HSR_BANNER_PRESETS", {}).keys()) | {"time_rotation", "reset"}
        preset_val = pt_raw if pt_raw in preset_keys else None
        banner_name = None if preset_val else (pt_raw or None)

        chars, lcs = hsr_core.load_hsr_kr_db()
        def _match_hsr_char(q: str) -> Optional[str]:
            if not q:
                return None
            ql = q.lower()
            found = next((c["id"] for c in chars if c["id"].lower() == ql or c.get("name", "").lower() == ql), None)
            if not found:
                found = next((c["id"] for c in chars if ql in c.get("name", "").lower() or ql in c["id"].lower()), q)
            return found

        def _match_hsr_lc(q: str) -> Optional[str]:
            if not q:
                return None
            ql = q.lower()
            found = next((l["id"] for l in lcs if l["id"].lower() == ql or l.get("name", "").lower() == ql), None)
            if not found:
                found = next((l["id"] for l in lcs if ql in l.get("name", "").lower() or ql in l["id"].lower()), q)
            return found

        def _match_hsr_relic(q: str) -> Optional[str]:
            if not q:
                return None
            ql = q.lower()
            rels = getattr(hsr_core, "HSR_RELICS", []) or []
            found = next((r["id"] for r in rels if r["id"].lower() == ql or r.get("name", "").lower() == ql), None)
            if not found:
                found = next((r["id"] for r in rels if ql in r.get("name", "").lower() or ql in r["id"].lower()), q)
            return found

        f5_parts = [p.strip() for p in (self.five_stars.value or "").split(",") if p.strip()]
        p5_1 = _match_hsr_char(f5_parts[0]) if len(f5_parts) >= 1 else None
        p5_2 = _match_hsr_char(f5_parts[1]) if len(f5_parts) >= 2 else None

        f4_parts = [p.strip() for p in (self.four_stars.value or "").split(",") if p.strip()]
        f4_1 = _match_hsr_char(f4_parts[0]) if len(f4_parts) >= 1 else None
        f4_2 = _match_hsr_char(f4_parts[1]) if len(f4_parts) >= 2 else None
        f4_3 = _match_hsr_char(f4_parts[2]) if len(f4_parts) >= 3 else None

        lc_parts = [p.strip() for p in (self.lightcones_5.value or "").split(",") if p.strip()]
        lc1 = _match_hsr_lc(lc_parts[0]) if len(lc_parts) >= 1 else None
        lc2 = _match_hsr_lc(lc_parts[1]) if len(lc_parts) >= 2 else None

        r_parts = [p.strip() for p in (self.relics_5.value or "").split(",") if p.strip()]
        r1 = _match_hsr_relic(r_parts[0]) if len(r_parts) >= 1 else None
        r2 = _match_hsr_relic(r_parts[1]) if len(r_parts) >= 2 else None

        await hsr_cog.setup_pickup_cmd.callback(
            hsr_cog,
            interaction,
            프리셋=preset_val,
            캐릭터1=p5_1,
            캐릭터2=p5_2,
            사성1=f4_1,
            사성2=f4_2,
            사성3=f4_3,
            광추1=lc1,
            광추2=lc2,
            유물1=r1,
            유물2=r2,
            배너이름=banner_name,
        )


class OshiQuickSelectView(core.SafeView):
    """26인 프로세카 캐릭터 중 최애(오시)를 드롭다운으로 즉시 선택하는 뷰"""

    def __init__(self, user: Optional[discord.abc.User] = None, parent_dashboard: Optional["MasterDashboardView"] = None):
        super().__init__(timeout=300)
        self.user = user
        self.parent_dashboard = parent_dashboard

        char_unit_map = {c["name"]: c.get("unit", "세카이") for c in core.CHARACTER_MAP.values()}
        all_chars = list(char_unit_map.keys())
        group_a = all_chars[:14]
        group_b = all_chars[14:]

        sel_a = discord.ui.Select(
            placeholder="💖 [그룹 A] 버츄얼 싱어 · 레오니 · 모모점 선택...",
            options=[
                discord.SelectOption(
                    label=ch_name,
                    value=ch_name,
                    description=char_unit_map.get(ch_name, "세카이"),
                    emoji="🌟",
                )
                for ch_name in group_a
            ],
            row=0,
            custom_id="norosi:OshiQuickSelectView:oshi_group_a",
        )
        sel_a.callback = self._on_select_oshi
        self.add_item(sel_a)

        if group_b:
            sel_b = discord.ui.Select(
                placeholder="💖 [그룹 B] 비배스 · 원더쇼 · 니고 선택...",
                options=[
                    discord.SelectOption(
                        label=ch_name,
                        value=ch_name,
                        description=char_unit_map.get(ch_name, "세카이"),
                        emoji="🎶",
                    )
                    for ch_name in group_b
                ],
                row=1,
                custom_id="norosi:OshiQuickSelectView:oshi_group_b",
            )
            sel_b.callback = self._on_select_oshi
            self.add_item(sel_b)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 오시 설정 창만 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    async def _on_select_oshi(self, interaction: discord.Interaction):
        picked = (interaction.data.get("values") or [None])[0] if isinstance(interaction.data, dict) else None
        if not picked:
            await core.safe_defer(interaction, ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)

        def _save():
            with core._DATA_LOCK:
                data = core.load_data()
                prof = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
                prof["oshi"] = picked
                core.save_data(data)
                return data

        data = await asyncio.to_thread(_save)
        if self.parent_dashboard:
            self.parent_dashboard.data = data
            if self.parent_dashboard.message:
                try:
                    await self.parent_dashboard.message.edit(
                        embed=self.parent_dashboard.build_current_embed(),
                        view=self.parent_dashboard,
                    )
                except Exception:
                    pass

        unit_name = next((c.get("unit", "세카이") for c in core.CHARACTER_MAP.values() if c.get("name") == picked), "세카이")
        embed = discord.Embed(
            title="💖 최애(오시) 캐릭터 설정 완료!",
            description=(
                f"**{interaction.user.display_name}**님의 대표 오시 캐릭터가 **`{picked}`** ({unit_name})로 변경되었습니다!\n"
                "• `/설정` (`👤 개인` ➔ `🪪 내 통합 프로필` 및 `🎨 비주얼 프로필 카드`)에 우선 반영됩니다.\n"
                "• `/설정` (`📅 일일 출석체크`) 시 오시 캐릭터의 세카이 보이스 대사가 매칭됩니다."
            ),
            color=discord.Color.from_rgb(255, 105, 180),
            timestamp=datetime.datetime.now(core.KST),
        )
        await interaction.edit_original_response(embed=embed, view=self)


class CrystalTransferAmountModal(core.SafeModal, title="💸 크리스탈 송금 금액 입력"):
    amount_input = discord.ui.TextInput(
        label="송금할 크리스탈 금액 (10 ~ 5,000💎)",
        placeholder="예: 500 (5% 송금 수수료 자동 차감)",
        required=True,
        max_length=5,
    )

    def __init__(self, target_member: discord.abc.User):
        super().__init__()
        self.target_member = target_member

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amount_input.value.strip().replace(",", ""))
        except ValueError:
            await core.safe_send_response(interaction, "❌ 금액은 숫자로만 입력해 주세요.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        ok, msg, _ = await asyncio.to_thread(
            economy_core.transfer_crystals,
            interaction.user.id,
            interaction.user.display_name,
            self.target_member.id,
            self.target_member.display_name,
            amt,
            bool(getattr(self.target_member, "bot", False)),
        )
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)
            return
        embed = discord.Embed(
            title="💸 크리스탈 송금 영수증",
            description=msg,
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="송금 수수료 5% 차감 · 일일 한도 5,000💎")
        await interaction.followup.send(embed=embed)


class CrystalTransferUserSelectView(core.SafeView):
    """크리스탈을 송금할 대상을 UserSelect 드롭다운으로 선택하는 뷰"""

    def __init__(self, user: Optional[discord.abc.User] = None):
        super().__init__(timeout=600)
        self.user = user
        u_sel = discord.ui.UserSelect(
            placeholder="💸 크리스탈을 송금할 서버 멤버를 선택하세요...",
            min_values=1,
            max_values=1,
            row=0,
            custom_id="norosi:CrystalTransferUserSelectView:user_select",
        )
        u_sel.callback = self._on_user_picked
        self.add_item(u_sel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 송금 창만 조작할 수 있습니다.", ephemeral=True)
            return False
        if self.user is None:
            self.user = interaction.user
        return True

    async def _on_user_picked(self, interaction: discord.Interaction):
        resolved_users = (
            interaction.data.get("resolved", {}).get("users", {})
            if isinstance(interaction.data, dict)
            else {}
        )
        uid_str = (interaction.data.get("values") or [None])[0] if isinstance(interaction.data, dict) else None
        if not uid_str or not str(uid_str).isdigit():
            await core.safe_send_response(interaction, "❌ 대상을 확인할 수 없습니다.", ephemeral=True)
            return
        target_id = int(uid_str)
        target_obj = (interaction.guild.get_member(target_id) if interaction.guild else None) or interaction.client.get_user(target_id)
        if target_obj is None:
            u_raw = resolved_users.get(str(target_id), {})
            if u_raw:
                try:
                    target_obj = await interaction.client.fetch_user(target_id)
                except Exception:
                    pass
        if target_obj is None:
            await core.safe_send_response(interaction, "❌ 선택한 유저 정보를 불러올 수 없습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(CrystalTransferAmountModal(target_obj))


class CardEnhanceQuickModal(core.SafeModal, title="🔨 보유 프로세카 카드 빠른 강화"):
    card_query = discord.ui.TextInput(
        label="강화할 카드 ID 또는 캐릭터/카드명",
        placeholder="예: 101 또는 카나데",
        required=True,
        max_length=60,
    )
    step_mode = discord.ui.TextInput(
        label="강화 단계 (1 / 10 / MAX)",
        placeholder="1, 10, 또는 MAX 입력 (기본: MAX)",
        default="MAX",
        required=True,
        max_length=10,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        raw_step = (self.step_mode.value or "MAX").strip().upper()
        if raw_step not in ("1", "10", "MAX"):
            raw_step = "MAX"
        gacha_cog = self.bot.get_cog("GachaCog")
        if gacha_cog and hasattr(gacha_cog, "enhance_card_cmd"):
            choice_obj = app_commands.Choice(name=f"강화 ({raw_step})", value=raw_step)
            await gacha_cog.enhance_card_cmd.callback(
                gacha_cog,
                interaction,
                카드선택=self.card_query.value.strip(),
                강화단계=choice_obj,
            )
        else:
            await core.safe_send_response(interaction, "❌ 가챠 모듈을 찾을 수 없습니다.", ephemeral=True)


class RelayStartQuickModal(core.SafeModal, title="✍️ 새 협동 릴레이 소설 시작"):
    novel_title = discord.ui.TextInput(
        label="릴레이 소설 제목",
        placeholder="예: 자정의 세카이에서 생긴 일",
        required=True,
        max_length=80,
    )
    first_line = discord.ui.TextInput(
        label="이야기를 여는 첫 문장 (2~280자)",
        style=discord.TextStyle.paragraph,
        placeholder="예: 시계탑 바늘이 12시를 가리키자 교실 창문 너머로 푸른 별똥별이 떨어졌다.",
        required=True,
        min_length=2,
        max_length=280,
    )
    max_turns = discord.ui.TextInput(
        label="완결까지 목표 줄 수 (3~30, 기본 10)",
        default="10",
        required=False,
        max_length=2,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        try:
            turns = max(3, min(30, int((self.max_turns.value or "10").strip())))
        except ValueError:
            turns = 10
        comm_cog = next((c for c in self.bot.cogs.values() if hasattr(c, "relay_start_cmd")), None)
        if comm_cog:
            await comm_cog.relay_start_cmd.callback(
                comm_cog,
                interaction,
                제목=self.novel_title.value.strip(),
                첫문장=self.first_line.value.strip(),
                목표턴=turns,
                공개모드=None,
                연속작성=None,
            )
        else:
            await core.safe_send_response(interaction, "❌ 릴레이 소설 모듈을 찾을 수 없습니다.", ephemeral=True)


class PartnerProposeUserSelectView(core.SafeView):
    """/설정 안에서 파트너를 신청할 유저를 UserSelect로 선택하는 뷰"""

    def __init__(self, user: Optional[discord.abc.User] = None, bot: Optional[commands.Bot] = None):
        super().__init__(timeout=600)
        self.user = user
        self.bot = bot
        u_sel = discord.ui.UserSelect(
            placeholder="💌 파트너(짝꿍)를 신청할 서버 멤버를 선택하세요...",
            min_values=1,
            max_values=1,
            row=0,
            custom_id="norosi:PartnerProposeUserSelectView:user_select",
        )
        u_sel.callback = self._on_user_picked
        self.add_item(u_sel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 파트너 신청 창만 조작할 수 있습니다.", ephemeral=True)
            return False
        if self.user is None:
            self.user = interaction.user
        return True

    async def _on_user_picked(self, interaction: discord.Interaction):
        uid_str = (interaction.data.get("values") or [None])[0] if isinstance(interaction.data, dict) else None
        if not uid_str or not str(uid_str).isdigit():
            await core.safe_send_response(interaction, "❌ 대상을 확인할 수 없습니다.", ephemeral=True)
            return
        target_id = int(uid_str)
        target_obj = (interaction.guild.get_member(target_id) if interaction.guild else None) or interaction.client.get_user(target_id)
        if target_obj is None:
            try:
                target_obj = await interaction.client.fetch_user(target_id)
            except Exception:
                pass
        if target_obj is None:
            await core.safe_send_response(interaction, "❌ 선택한 유저 정보를 불러올 수 없습니다.", ephemeral=True)
            return
        bot_ref = self.bot or interaction.client
        dday_cog = next((c for c in bot_ref.cogs.values() if hasattr(c, "partner_cmd")), None)
        if dday_cog:
            choice_req = app_commands.Choice(name="💌 파트너 신청하기", value="request")
            await dday_cog.partner_cmd.callback(dday_cog, interaction, 동작=choice_req, 유저=target_obj)
        else:
            await core.safe_send_response(interaction, "❌ 파트너 모듈을 찾을 수 없습니다.", ephemeral=True)


class CardTradeUserSelectView(core.SafeView):
    """/설정 안에서 1:1 카드 교환 상대방을 UserSelect로 선택해 교환 장터 스튜디오를 여는 뷰"""

    def __init__(self, user: Optional[discord.abc.User] = None, bot: Optional[commands.Bot] = None):
        super().__init__(timeout=600)
        self.user = user
        self.bot = bot
        u_sel = discord.ui.UserSelect(
            placeholder="🔄 1:1 카드를 교환할 서버 멤버를 선택하세요 (100💎)...",
            min_values=1,
            max_values=1,
            row=0,
            custom_id="norosi:CardTradeUserSelectView:user_select",
        )
        u_sel.callback = self._on_user_picked
        self.add_item(u_sel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 카드 교환 창만 조작할 수 있습니다.", ephemeral=True)
            return False
        if self.user is None:
            self.user = interaction.user
        return True

    async def _on_user_picked(self, interaction: discord.Interaction):
        uid_str = (interaction.data.get("values") or [None])[0] if isinstance(interaction.data, dict) else None
        if not uid_str or not str(uid_str).isdigit():
            await core.safe_send_response(interaction, "❌ 대상을 확인할 수 없습니다.", ephemeral=True)
            return
        target_id = int(uid_str)
        target_obj = (interaction.guild.get_member(target_id) if interaction.guild else None) or interaction.client.get_user(target_id)
        if target_obj is None:
            try:
                target_obj = await interaction.client.fetch_user(target_id)
            except Exception:
                pass
        if target_obj is None:
            await core.safe_send_response(interaction, "❌ 선택한 유저 정보를 불러올 수 없습니다.", ephemeral=True)
            return
        gacha_cog = next((c for c in self.bot.cogs.values() if hasattr(c, "card_trade_cmd")), None)
        if gacha_cog:
            await gacha_cog.card_trade_cmd.callback(gacha_cog, interaction, 상대유저=target_obj, 내카드=None, 상대카드=None)
        else:
            await core.safe_send_response(interaction, "❌ 가챠 모듈을 찾을 수 없습니다.", ephemeral=True)


class CardGiftQuickModal(core.SafeModal, title="🎁 파트너에게 보유 카드 선물 (50💎)"):
    card_query = discord.ui.TextInput(
        label="선물할 보유 카드 ID 또는 캐릭터/카드명",
        placeholder="예: 101 또는 카나데",
        required=True,
        max_length=60,
    )
    gift_msg = discord.ui.TextInput(
        label="파트너에게 함께 전할 선물 메시지 (선택)",
        placeholder="예: 생일 축하해! 이 카드 선물할게 💖",
        required=False,
        max_length=100,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        gacha_cog = next((c for c in self.bot.cogs.values() if hasattr(c, "card_gift_cmd")), None)
        if not gacha_cog:
            await core.safe_send_response(interaction, "❌ 가챠 모듈을 찾을 수 없습니다.", ephemeral=True)
            return
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id or 0)
        u_key = str(interaction.user.id)
        u_cards = core.safe_get_dict(data, "gacha_users", g_key, u_key, "cards")
        cid, _ = gacha.GachaCog._find_user_card_by_query(u_cards, self.card_query.value.strip())
        await gacha_cog.card_gift_cmd.callback(
            gacha_cog,
            interaction,
            내카드=cid or self.card_query.value.strip(),
            메시지=(self.gift_msg.value or "").strip() or None,
        )


class SekaiDeckCustomModal(core.SafeModal, title="✏️ 프로세카 5인 유닛 덱 직접 편성"):
    slot1 = discord.ui.TextInput(label="1번 슬롯 (👑 리더) 카드 ID 또는 이름", placeholder="예: 101 또는 카나데", required=True, max_length=50)
    slot2 = discord.ui.TextInput(label="2번 슬롯 카드 ID 또는 이름 (선택)", placeholder="비워두면 1인/일부 슬롯만 편성", required=False, max_length=50)
    slot3 = discord.ui.TextInput(label="3번 슬롯 카드 ID 또는 이름 (선택)", required=False, max_length=50)
    slot4 = discord.ui.TextInput(label="4번 슬롯 카드 ID 또는 이름 (선택)", required=False, max_length=50)
    slot5 = discord.ui.TextInput(label="5번 슬롯 카드 ID 또는 이름 (선택)", required=False, max_length=50)

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        gacha_cog = next((c for c in self.bot.cogs.values() if hasattr(c, "set_deck_cmd")), None)
        if not gacha_cog:
            await core.safe_send_response(interaction, "❌ 가챠 모듈을 찾을 수 없습니다.", ephemeral=True)
            return
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id or 0)
        u_key = str(interaction.user.id)
        u_cards = core.safe_get_dict(data, "gacha_users", g_key, u_key, "cards")
        raw_inputs = [self.slot1.value, self.slot2.value, self.slot3.value, self.slot4.value, self.slot5.value]
        resolved_ids: List[Optional[str]] = []
        for q in raw_inputs:
            q_s = (q or "").strip()
            if not q_s:
                resolved_ids.append(None)
                continue
            cid, _ = gacha.GachaCog._find_user_card_by_query(u_cards, q_s)
            resolved_ids.append(cid or q_s)
        await gacha_cog.set_deck_cmd.callback(
            gacha_cog,
            interaction,
            리더=resolved_ids[0] or "",
            멤버2=resolved_ids[1],
            멤버3=resolved_ids[2],
            멤버4=resolved_ids[3],
            멤버5=resolved_ids[4],
        )


class SekaiDeckManageView(core.SafeView):
    """5인 유닛 덱 현황 창에서 자동 최고 종합력 편성 또는 직접 편성을 수행하는 뷰"""

    def __init__(self, user: discord.abc.User, bot: commands.Bot):
        super().__init__(timeout=600)
        self.user = user
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 덱 편성 창만 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⚡ 최고 종합력 5인 자동 편성", style=discord.ButtonStyle.success, emoji="⚡", row=0)
    async def auto_deck_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id or 0)
        u_key = str(interaction.user.id)
        u_cards = core.safe_get_dict(data, "gacha_users", g_key, u_key, "cards")
        if not u_cards:
            await interaction.followup.send("❌ 보유한 카드가 없습니다. 프로세카 뽑기로 먼저 카드를 획득해 주세요!", ephemeral=True)
            return
        sorted_items = sorted(
            [(str(cid), c) for cid, c in u_cards.items() if isinstance(c, dict)],
            key=lambda item: (-core.get_card_power(item[1]), -int(item[1].get("star_num", 1))),
        )
        chosen_ids: List[str] = []
        chosen_chars = set()
        for cid, c in sorted_items:
            char_ident = c.get("char_id") or c.get("char_name")
            if char_ident in chosen_chars:
                continue
            chosen_chars.add(char_ident)
            chosen_ids.append(cid)
            if len(chosen_ids) >= 5:
                break
        if not chosen_ids:
            await interaction.followup.send("❌ 편성 가능한 카드를 찾을 수 없습니다.", ephemeral=True)
            return
        profile = core.ensure_user_profile(data, u_key, interaction.user.display_name)
        profile["deck"] = chosen_ids
        await asyncio.to_thread(core.save_data, data)

        total_power = 0
        lines = []
        for idx, cid in enumerate(chosen_ids, start=1):
            c = u_cards[cid]
            p_val = core.get_card_power(c)
            total_power += p_val
            badge = "👑 **[리더]**" if idx == 1 else f"🎸 **[슬롯 {idx}]**"
            lines.append(f"{badge} **{c.get('rarity_label', '★1')} [{c.get('prefix', '')}] {c.get('char_name', '')}** (`Lv.{c.get('level', 1)}` · `⚔️ {p_val:,}`)")
        embed = discord.Embed(
            title=f"⚡ {interaction.user.display_name}님의 최고 종합력 5인 덱 자동 편성 완료! (⚔️ {total_power:,})",
            description="\n".join(lines),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST),
        )
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="5인 직접 편성", style=discord.ButtonStyle.primary, emoji="✏️", row=0)
    async def manual_deck_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SekaiDeckCustomModal(self.bot))


class BotBannerModal(core.SafeModal, title="🖼️ [봇주 전용] 봇 프로필 배너 변경/초기화"):
    banner_url = discord.ui.TextInput(
        label="배너 이미지 URL (초기화 시 '초기화' 입력)",
        placeholder="https://... (PNG/JPG/GIF/WEBP) 또는 '초기화'",
        required=True,
        max_length=400,
    )

    async def on_submit(self, interaction: discord.Interaction):
        import bot as bot_mod
        raw = (self.banner_url.value or "").strip()
        if raw.lower() in ("초기화", "제거", "삭제", "reset", "none", "clear"):
            await bot_mod.set_bot_banner_slash(interaction, 이미지=None, 이미지url=None, 초기화=True)
        else:
            await bot_mod.set_bot_banner_slash(interaction, 이미지=None, 이미지url=raw, 초기화=False)

# ==========================================
# ⭐ 나만의 `/설정` 홈 즐겨찾기 단축바 카탈로그 & 편집 뷰
# ==========================================
HOME_SHORTCUT_CATALOG: List[Dict[str, Any]] = [
    {"key": "att", "label": "출석체크", "emoji": "📅", "style": discord.ButtonStyle.success, "desc": "오늘 출석 도장 & 크리스탈 수령", "cb_name": "_act_attendance"},
    {"key": "prof", "label": "프로필카드", "emoji": "🪪", "style": discord.ButtonStyle.primary, "desc": "통합 PNG 프로필 카드 발급", "cb_name": "_act_profile_card_png"},
    {"key": "p10", "label": "프세카10연", "emoji": "🌈", "style": discord.ButtonStyle.secondary, "desc": "프로세카 10연차 즉시 뽑기", "cb_name": "_act_sekai_pull_10"},
    {"key": "fish", "label": "낚시 출조", "emoji": "🎣", "style": discord.ButtonStyle.secondary, "desc": "호수·강·바다 낚시 출조", "cb_name": "_act_fishing_cast"},
    {"key": "rank", "label": "통합 랭킹", "emoji": "🏆", "style": discord.ButtonStyle.primary, "desc": "전 분야 8종 서버 랭킹 허브", "cb_name": "_act_ranking_hub"},
    {"key": "routine", "label": "일일 루틴", "emoji": "☀️", "style": discord.ButtonStyle.success, "desc": "오늘의 일일 루틴 한눈에 보기", "cb_name": "_act_daily_routine"},
    {"key": "weekly", "label": "주간 미션", "emoji": "🎯", "style": discord.ButtonStyle.primary, "desc": "통합 주간 미션 & 올클리어 보상", "cb_name": "_act_weekly_missions"},
    {"key": "radio", "label": "무드 라디오", "emoji": "📻", "style": discord.ButtonStyle.primary, "desc": "6대 분위기 원클릭 음성 라디오", "cb_name": "_act_mood_radio"},
    {"key": "event", "label": "예약 이벤트", "emoji": "🗓️", "style": discord.ButtonStyle.primary, "desc": "RSVP 참가 신청표 & 자동 리마인드", "cb_name": "_act_guild_events"},
    {"key": "pl", "label": "플리스튜디오", "emoji": "💿", "style": discord.ButtonStyle.secondary, "desc": "내 플레이리스트 제작 & 자동재생", "cb_name": "_act_playlist_studio"},
    {"key": "gi10", "label": "원신 10연", "emoji": "🌠", "style": discord.ButtonStyle.secondary, "desc": "원신 기원 10연차 뽑기", "cb_name": "_act_gi_pull_10"},
    {"key": "hsr10", "label": "스타레일10", "emoji": "🚄", "style": discord.ButtonStyle.secondary, "desc": "스타레일 워프 10연차 뽑기", "cb_name": "_act_hsr_warp_10"},
    {"key": "farm", "label": "개인 농장", "emoji": "🌾", "style": discord.ButtonStyle.success, "desc": "개인 농장 작물 재배 & 수확", "cb_name": "_act_life_farm"},
    {"key": "todo", "label": "오늘 목표", "emoji": "🌱", "style": discord.ButtonStyle.success, "desc": "오늘 할 일 & 은하수 잔디 보드", "cb_name": "_act_todo_grass"},
    {"key": "pomo", "label": "뽀모도로", "emoji": "⏳", "style": discord.ButtonStyle.secondary, "desc": "집중/휴식 스터디 타이머 실행", "cb_name": "_act_pomodoro"},
    {"key": "weather", "label": "실시간날씨", "emoji": "🌤️", "style": discord.ButtonStyle.secondary, "desc": "기상청 기온·미세먼지 조회", "cb_name": "_act_weather"},
    {"key": "dday", "label": "D-Day보드", "emoji": "📋", "style": discord.ButtonStyle.secondary, "desc": "서버 D-Day 일정 전광판", "cb_name": "_act_dday_list"},
    {"key": "dday_past", "label": "지나간D-Day", "emoji": "🕰️", "style": discord.ButtonStyle.secondary, "desc": "지나간 D-Day 추억 보관소 전체 조회", "cb_name": "_sub_dday_past"},
    {"key": "showcase", "label": "쇼케이스", "emoji": "🌟", "style": discord.ButtonStyle.secondary, "desc": "내 수집품 통합 자랑 카드", "cb_name": "_act_showcase"},
    {"key": "exchange", "label": "화폐 환전", "emoji": "💱", "style": discord.ButtonStyle.secondary, "desc": "골드⇄크리스탈 안전 환전소", "cb_name": "_act_currency_exchange"},
    {"key": "battle", "label": "즉석 대전", "emoji": "🎲", "style": discord.ButtonStyle.success, "desc": "하이로우 주사위 & 초성 퀴즈", "cb_name": "_act_mini_battle_hub"},
    {"key": "sponsor", "label": "후원하기", "emoji": "💖", "style": discord.ButtonStyle.secondary, "desc": "팀 봉화 (소유주 : 아시) 후원 · 봇 운영 지원", "cb_name": "_act_sponsor"},
    {"key": "search", "label": "기능 검색", "emoji": "🔍", "style": discord.ButtonStyle.primary, "desc": "키워드로 130+ 기능 즉시 검색 & 실행", "cb_name": "_act_feature_search"},
    {"key": "achievements", "label": "업적 뱃지", "emoji": "🏅", "style": discord.ButtonStyle.primary, "desc": "크로스 기능 12종 업적·뱃지 달성 현황", "cb_name": "_act_achievements"},
]
HOME_SHORTCUT_MAP: Dict[str, Dict[str, Any]] = {item["key"]: item for item in HOME_SHORTCUT_CATALOG}
HOME_SHORTCUT_KEYS: set[str] = set(HOME_SHORTCUT_MAP.keys())


class DashboardFeatureSearchModal(core.SafeModal, title="🔍 /설정 통합 기능 검색"):
    keyword_input = discord.ui.TextInput(
        label="찾을 기능 키워드",
        placeholder="예: 낚시, 라디오, 티켓, 환전, 날씨, 업적, 후원...",
        required=True,
        min_length=1,
        max_length=40,
    )

    def __init__(self, parent_view: "MasterDashboardView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        kw = (self.keyword_input.value or "").strip()
        if not kw:
            await core.safe_send_response(interaction, "❌ 검색할 키워드를 입력해 주세요.", ephemeral=True)
            return
        matches = search_dashboard_features(self.parent_view, kw)
        view = DashboardSearchResultView(self.parent_view, kw, matches, owner_id=interaction.user.id)
        await core.safe_send_response(interaction, embed=view.build_embed(), view=view, ephemeral=True)


def search_dashboard_features(dashboard_view: "MasterDashboardView", kw: str) -> List[Dict[str, Any]]:
    """/설정 전체 4대 카테고리 페이지 및 홈 단축바에서 키워드와 일치하는 실행 항목을 검색합니다."""
    tokens = [t.lower() for t in str(kw or "").split() if t.strip()]
    if not tokens:
        return []
    cat_labels = {
        "general": "🌐 일반",
        "advanced": "⚙️ 고급",
        "minigame": "🎮 미니게임",
        "personal": "👤 개인",
    }
    matches: List[Dict[str, Any]] = []
    seen_labels: set[str] = set()
    for cat_key, pages in (dashboard_view._pages_cache or {}).items():
        for p_idx, page in enumerate(pages, start=1):
            for item in page.get("items", []):
                lbl = str(item.get("label") or "")
                desc = str(item.get("desc") or "")
                haystack = f"{lbl} {desc} {page.get('page_title', '')}".lower()
                if all(tok in haystack for tok in tokens):
                    if lbl in seen_labels:
                        continue
                    seen_labels.add(lbl)
                    matches.append({
                        "cat_label": cat_labels.get(cat_key, cat_key),
                        "page_num": p_idx,
                        "item": item,
                    })
    # 홈 단축키(업적/후원 등)도 함께 검색 보강
    for sc_item in HOME_SHORTCUT_CATALOG:
        if sc_item["key"] == "search":
            continue
        lbl = sc_item["label"]
        haystack = f"{lbl} {sc_item['desc']}".lower()
        if all(tok in haystack for tok in tokens) and lbl not in seen_labels:
            cb = getattr(dashboard_view, sc_item["cb_name"], None)
            if callable(cb):
                seen_labels.add(lbl)
                matches.append({
                    "cat_label": "🏠 홈 바로가기",
                    "page_num": 1,
                    "item": {
                        "label": lbl,
                        "emoji": sc_item["emoji"],
                        "style": sc_item["style"],
                        "perm": PERM_USER,
                        "desc": sc_item["desc"],
                        "cb": cb,
                    },
                })
    return matches


class DashboardSearchResultView(core.SafeView):
    """통합 기능 검색 결과 즉시 실행 뷰 (최대 10개 원클릭 버튼 + 다시 검색 + 설정 홈)"""

    def __init__(
        self,
        parent_view: Optional["MasterDashboardView"] = None,
        keyword: str = "",
        matches: Optional[List[Dict[str, Any]]] = None,
        owner_id: int = 0,
    ):
        super().__init__(timeout=600)
        self.parent_view = parent_view
        self.keyword = keyword
        self.matches = (matches or [])[:10]
        self.owner_id = owner_id

        for idx, m in enumerate(self.matches):
            item = m["item"]
            row = 0 if idx < 5 else 1
            btn = discord.ui.Button(
                label=str(item.get("label") or "실행")[:40],
                emoji=item.get("emoji") or "▶️",
                style=item.get("style") or discord.ButtonStyle.secondary,
                row=row,
            )
            cb = item.get("cb")

            async def _on_click(inter: discord.Interaction, _cb=cb):
                if callable(_cb):
                    await _cb(inter)
                else:
                    await core.safe_send_response(inter, "❌ 실행할 수 없는 항목입니다.", ephemeral=True)

            btn.callback = _on_click
            self.add_item(btn)

        nav_row = 2 if len(self.matches) > 5 else (1 if self.matches else 0)
        again_btn = discord.ui.Button(
            label="🔍 다시 검색",
            style=discord.ButtonStyle.primary,
            row=nav_row,
        )
        again_btn.callback = self._on_search_again
        self.add_item(again_btn)

        home_btn = discord.ui.Button(
            label="🏠 /설정 홈 열기",
            style=discord.ButtonStyle.secondary,
            row=nav_row,
        )
        home_btn.callback = self._on_open_dashboard_home
        self.add_item(home_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.owner_id and interaction.user.id != self.owner_id:
            await core.safe_send_response(
                interaction,
                "❌ 본인이 검색한 결과 창에서만 버튼을 조작할 수 있습니다.",
                ephemeral=True,
            )
            return False
        return True

    async def _ensure_parent_view(self, interaction: discord.Interaction) -> "MasterDashboardView":
        if self.parent_view is None:
            data = await asyncio.to_thread(core.load_data)
            self.parent_view = MasterDashboardView(
                bot=interaction.client,
                user=interaction.user,
                guild=interaction.guild,
                data=data,
            )
        return self.parent_view

    async def _on_search_again(self, interaction: discord.Interaction):
        pv = await self._ensure_parent_view(interaction)
        await interaction.response.send_modal(DashboardFeatureSearchModal(pv))

    async def _on_open_dashboard_home(self, interaction: discord.Interaction):
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        view = MasterDashboardView(
            bot=interaction.client,
            user=interaction.user,
            guild=interaction.guild,
            data=data,
            initial_tab="home",
        )
        msg = await interaction.followup.send(embed=view.build_current_embed(), view=view, ephemeral=True, wait=True)
        view.message = msg

    def build_embed(self) -> discord.Embed:
        if not self.matches:
            return discord.Embed(
                title=f"🔍 기능 검색 결과: {self.keyword}",
                description=(
                    "일치하는 기능을 찾지 못했습니다.\n"
                    "• 더 짧은 키워드로 다시 검색해 보세요! *(예: `디데이`, `낚시`, `라디오`, `티켓`, `환전`, `업적`, `후원`)*"
                ),
                color=discord.Color.orange(),
                timestamp=datetime.datetime.now(core.KST),
            )
        num_icons = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        lines = []
        for idx, m in enumerate(self.matches, start=1):
            it = m["item"]
            nb = num_icons[idx - 1] if idx <= 10 else f"`{idx:02d}.`"
            perm_tag = " `👑봇주`" if it.get("perm") == PERM_OWNER else (" `🛡️관리자`" if it.get("perm") == PERM_ADMIN else "")
            lbl_clean = re.sub(r"^\[(?:봇주인|서버관리자)\]\s*", "", str(it.get("label") or "-")).strip()
            desc_clean = re.sub(r"^\[[^\]]+\]\s*", "", str(it.get("desc") or "")).strip()
            if len(desc_clean) > 65:
                desc_clean = desc_clean[:64].rstrip() + "…"
            lines.append(
                f"{nb} {it.get('emoji', '•')} **{lbl_clean}**{perm_tag}  ·  `{m['cat_label']} {m['page_num']}p`\n"
                f"　└ {desc_clean}"
            )
        embed = discord.Embed(
            title=f"🔍 기능 검색 결과: {self.keyword} ({len(self.matches)}건)",
            description="\n".join(lines)[:4096],
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST),
        )
        return embed


class HomeShortcutEditView(core.SafeView):
    """유저별 `/설정` 홈 2번째 줄(Row 1) 즐겨찾기 단축바(최대 5개) 커스터마이징 뷰"""

    def __init__(
        self,
        bot: Optional[commands.Bot] = None,
        user: Optional[discord.abc.User] = None,
        guild: Optional[discord.Guild] = None,
        data: Optional[dict] = None,
        parent_view: Optional["MasterDashboardView"] = None,
    ):
        super().__init__(timeout=300)
        self.bot = bot
        self.user = user
        self.guild = guild
        self.data = data if isinstance(data, dict) else core.get_cached_data()
        self.parent_view = parent_view
        uid = self.user.id if self.user else 0
        self.selected_keys: List[str] = core.get_user_home_shortcuts(
            self.data, uid, valid_keys=HOME_SHORTCUT_KEYS
        )
        self._rebuild_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                "❌ 본인이 연 즐겨찾기 편집창만 조작할 수 있습니다. `/설정`에서 직접 열어주세요.",
                ephemeral=True,
            )
            return False
        return True

    def _rebuild_items(self):
        self.clear_items()
        opts = [
            discord.SelectOption(
                label=f"{item['label']}",
                value=item["key"],
                description=item["desc"][:100],
                emoji=item["emoji"],
                default=(item["key"] in self.selected_keys),
            )
            for item in HOME_SHORTCUT_CATALOG[:25]
        ]
        sel = discord.ui.Select(
            placeholder="⭐ 홈 단축바에 배치할 기능 1~5개를 선택하세요...",
            min_values=1,
            max_values=5,
            options=opts,
            row=0,
            custom_id="norosi:HomeShortcutEditView:select",
        )
        sel.callback = self._on_select_changed
        self.add_item(sel)

        btn_save = discord.ui.Button(
            label="저장 & 적용",
            emoji="💾",
            style=discord.ButtonStyle.success,
            row=1,
            custom_id="norosi:HomeShortcutEditView:save",
        )
        btn_save.callback = self._on_save_clicked
        self.add_item(btn_save)

        btn_reset = discord.ui.Button(
            label="기본값 복원",
            emoji="🔄",
            style=discord.ButtonStyle.secondary,
            row=1,
            custom_id="norosi:HomeShortcutEditView:reset",
        )
        btn_reset.callback = self._on_reset_clicked
        self.add_item(btn_reset)

        btn_clear = discord.ui.Button(
            label="단축바 숨기기",
            emoji="🗑️",
            style=discord.ButtonStyle.danger,
            row=1,
            custom_id="norosi:HomeShortcutEditView:clear",
        )
        btn_clear.callback = self._on_clear_clicked
        self.add_item(btn_clear)

        btn_home = discord.ui.Button(
            label="설정 홈으로",
            emoji="🏠",
            style=discord.ButtonStyle.primary,
            row=1,
            custom_id="norosi:HomeShortcutEditView:home",
        )
        btn_home.callback = self._on_go_home_clicked
        self.add_item(btn_home)

    def build_embed(self) -> discord.Embed:
        preview_chips = "  ".join(
            f"`[{HOME_SHORTCUT_MAP[k]['emoji']} {HOME_SHORTCUT_MAP[k]['label']}]`"
            for k in self.selected_keys
            if k in HOME_SHORTCUT_MAP
        )
        is_default = (self.selected_keys == core.DEFAULT_HOME_SHORTCUTS)
        badge = "기본 프리셋" if is_default else f"커스텀 ({len(self.selected_keys)}개)"
        embed = discord.Embed(
            title="⭐ 나만의 /설정 홈 즐겨찾기 단축바 편집",
            description=(
                "자주 쓰는 기능 **1~5개**를 골라 `/설정` 홈 화면 2번째 줄 단축 버튼으로 고정할 수 있습니다.\n"
                "아래 드롭다운에서 원하는 기능을 고른 뒤 `[💾 저장 & 적용]`을 눌러주세요!\n\n"
                f"📌 **현재 선택 미리보기 ({badge})**\n"
                f"{preview_chips or '*(선택 없음)*'}"
            ),
            color=0xF1C40F,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="설정은 내 계정에 저장되어 모든 서버의 /설정 홈에 자동 적용됩니다.")
        return embed

    async def _on_select_changed(self, interaction: discord.Interaction):
        vals = (interaction.data or {}).get("values") or []
        cleaned = [v for v in vals if v in HOME_SHORTCUT_KEYS][:5]
        if cleaned:
            self.selected_keys = cleaned
        self._rebuild_items()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_save_clicked(self, interaction: discord.Interaction):
        uid = interaction.user.id
        uname = interaction.user.display_name
        keys_to_save = list(self.selected_keys)

        def _commit():
            with core._DATA_LOCK:
                d = core.load_data()
                saved = core.set_user_home_shortcuts(
                    d, uid, keys_to_save, user_name=uname, valid_keys=HOME_SHORTCUT_KEYS
                )
                core.save_data(d)
                return d, saved

        new_data, saved_keys = await asyncio.to_thread(_commit)
        self.data = new_data
        self.selected_keys = saved_keys
        self._rebuild_items()

        if self.parent_view is not None:
            self.parent_view.data = new_data
            self.parent_view.current_category = "home"
            self.parent_view.sub_mode = None
            self.parent_view.refresh_components()
            if self.parent_view.message:
                try:
                    await self.parent_view.message.edit(
                        embed=self.parent_view.build_current_embed(),
                        view=self.parent_view,
                    )
                except Exception:
                    pass

        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        chips = " · ".join(f"{HOME_SHORTCUT_MAP[k]['emoji']}{HOME_SHORTCUT_MAP[k]['label']}" for k in saved_keys if k in HOME_SHORTCUT_MAP)
        await interaction.followup.send(f"✅ 나만의 홈 단축바가 저장·적용되었습니다!\n> {chips}", ephemeral=True)

    async def _on_reset_clicked(self, interaction: discord.Interaction):
        uid = interaction.user.id
        uname = interaction.user.display_name

        def _commit_reset():
            with core._DATA_LOCK:
                d = core.load_data()
                saved = core.set_user_home_shortcuts(
                    d, uid, [], user_name=uname, valid_keys=HOME_SHORTCUT_KEYS
                )
                core.save_data(d)
                return d, saved

        new_data, saved_keys = await asyncio.to_thread(_commit_reset)
        self.data = new_data
        self.selected_keys = saved_keys
        self._rebuild_items()

        if self.parent_view is not None:
            self.parent_view.data = new_data
            self.parent_view.current_category = "home"
            self.parent_view.sub_mode = None
            self.parent_view.refresh_components()
            if self.parent_view.message:
                try:
                    await self.parent_view.message.edit(
                        embed=self.parent_view.build_current_embed(),
                        view=self.parent_view,
                    )
                except Exception:
                    pass

        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        await interaction.followup.send("🔄 홈 단축바를 기본 프리셋 5종으로 복원했습니다.", ephemeral=True)

    async def _on_clear_clicked(self, interaction: discord.Interaction):
        uid = interaction.user.id
        uname = interaction.user.display_name

        def _commit_clear():
            with core._DATA_LOCK:
                d = core.load_data()
                prof = core.ensure_user_profile(d, uid, uname)
                prof["home_shortcuts_disabled"] = True
                prof.pop("home_shortcuts", None)
                core.save_data(d)
                return d

        new_data = await asyncio.to_thread(_commit_clear)
        self.data = new_data
        self.selected_keys = []
        self._rebuild_items()

        if self.parent_view is not None:
            self.parent_view.data = new_data
            self.parent_view.current_category = "home"
            self.parent_view.sub_mode = None
            self.parent_view.refresh_components()
            if self.parent_view.message:
                try:
                    await self.parent_view.message.edit(
                        embed=self.parent_view.build_current_embed(),
                        view=self.parent_view,
                    )
                except Exception:
                    pass

        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        await interaction.followup.send("🗑️ 홈 즐겨찾기 단축바를 숨겼습니다. (`[🔄 기본값 복원]`으로 언제든 다시 켤 수 있습니다)", ephemeral=True)

    async def _on_go_home_clicked(self, interaction: discord.Interaction):
        data = await asyncio.to_thread(core.load_data)
        view = MasterDashboardView(
            bot=self.bot or interaction.client,
            user=interaction.user,
            guild=interaction.guild,
            data=data,
            initial_tab="home",
        )
        await core.safe_edit_response(interaction, embed=view.build_current_embed(), view=view)


# 🎛️ 통합 설정 허브 뷰 (MasterDashboardView / SettingsHubView)
# ==========================================
class MasterDashboardView(core.SafeView):
    """
    Component V2 스타일 계층형 통합 `/설정` 뷰:
    - 1단계 (홈 `current_category == 'home'`):
      [🌐 일반] · [⚙️ 고급] · [🎮 미니게임] · [👤 개인] 4대 카테고리 진입 버튼 + 개인 커스텀 즐겨찾기 단축바 + 통합 페이지네이션
    - 2단계 (카테고리 내부 `current_category in ('general', 'advanced', 'minigame', 'personal')`):
      세부 기능 버튼 (페이지당 6개, 총 15페이지 · 90종 기능) + 카테고리 스위처 + [⬅️ 뒤로가기] + [◀ 이전 / 📄 페이지 / 다음 ▶]
    - 3단계 (`sub_mode is not None`):
      도감/랭킹/티켓/픽업/백업/초기화 등 세부 제어 패널 + [⬅️ 뒤로가기] + [🏠 설정 홈으로]
    """

    def __init__(
        self,
        bot: Optional[commands.Bot] = None,
        user: Optional[discord.abc.User] = None,
        guild: Optional[discord.Guild] = None,
        data: Optional[dict] = None,
        initial_tab: str = "home",
        initial_page: int = 0,
    ):
        super().__init__(timeout=900)
        self.bot = bot
        self.user = user
        self.guild = guild
        self.data = data if isinstance(data, dict) else core.get_cached_data()
        self.message: Optional[discord.Message] = None

        # 레거시 탭 키 호환 매핑 (기존 코드/복구 핸들러 완벽 호환)
        mapped_cat, mapped_page = self._resolve_initial_target(initial_tab, initial_page)
        self.current_category: str = mapped_cat
        self.current_page: int = mapped_page
        tk_norm = (initial_tab or "").strip().lower()
        if tk_norm in ("ranking", "rank", "랭킹"):
            self.sub_mode: Optional[str] = "ranking_hub"
        elif tk_norm in ("pokedex", "codex", "도감"):
            self.sub_mode = "pokedex_hub"
        else:
            self.sub_mode = None

        # 직전 화면 복귀용 네비게이션 히스토리 스택 [(category, page, sub_mode), ...]
        self._nav_history: List[Tuple[str, int, Optional[str]]] = []

        self._pages_cache: Dict[str, List[Dict[str, Any]]] = self._build_catalog_pages()
        self.refresh_components()

    def _current_nav_state(self) -> Tuple[str, int, Optional[str]]:
        return (self.current_category, self.current_page, self.sub_mode)

    def _push_nav_history(self, state: Optional[Tuple[str, int, Optional[str]]] = None):
        entry = state if state is not None else self._current_nav_state()
        if not self._nav_history or self._nav_history[-1] != entry:
            self._nav_history.append(entry)
            if len(self._nav_history) > 25:
                self._nav_history = self._nav_history[-25:]

    @staticmethod
    def _encode_nav_state(state: Tuple[str, int, Optional[str]]) -> str:
        cat, page, sub = state
        code = _NAV_CAT_TO_CODE.get(cat, "h")
        if sub:
            return f"{code}{page}.{sub}"
        return f"{code}{page}"

    @staticmethod
    def _decode_nav_state(token: str) -> Optional[Tuple[str, int, Optional[str]]]:
        token = (token or "").strip()
        if not token:
            return None
        sub: Optional[str] = None
        head = token
        if "." in token:
            head, sub_part = token.split(".", 1)
            sub = sub_part or None
            if sub and sub not in SUB_MODE_PARENT_MAP:
                return None
        if len(head) < 2:
            return None
        cat = _NAV_CODE_TO_CAT.get(head[0])
        page_s = head[1:]
        if not cat or not page_s.isdigit():
            return None
        return (cat, int(page_s), sub)

    def _get_back_button_custom_id(self) -> str:
        """직전 화면 히스토리 스택을 custom_id에 압축 인코딩 (봇 재시작·타임아웃 복구 후에도 이전 화면 유지)"""
        prefix = "norosi:Settings:nav_back:"
        max_payload = 100 - len(prefix)
        states: List[Tuple[str, int, Optional[str]]] = list(self._nav_history)
        if not states:
            if self.sub_mode is not None:
                p_cat, p_page = SUB_MODE_PARENT_MAP.get(
                    self.sub_mode, (self.current_category, self.current_page)
                )
                states = [(p_cat, p_page, None)]
            else:
                states = [("home", 0, None)]

        encoded_rev: List[str] = []
        cur_len = 0
        for st in reversed(states):
            tok = self._encode_nav_state(st)
            add_len = len(tok) + (1 if encoded_rev else 0)
            if cur_len + add_len > max_payload:
                break
            encoded_rev.append(tok)
            cur_len += add_len
        if not encoded_rev:
            return "norosi:Settings:nav_back:h0"
        encoded_rev.reverse()
        return f"{prefix}{'|'.join(encoded_rev)}"

    @staticmethod
    def _resolve_initial_target(tab_key: str, page_idx: int = 0) -> Tuple[str, int]:
        tk = (tab_key or "home").strip().lower()
        if tk in ("home", "main", "홈"):
            return "home", 0
        if tk in ("ranking", "rank", "랭킹"):
            return "minigame", 3
        if tk in ("pokedex", "codex", "도감"):
            return "minigame", 3
        if tk in ("general", "일반", "life"):
            return "general", max(0, min(2, page_idx))
        if tk == "music":
            return "general", 1
        if tk == "stats":
            return "general", 2
        if tk in ("advanced", "admin", "고급", "관리"):
            return "advanced", max(0, min(3, page_idx))
        if tk in ("minigame", "미니게임", "gacha"):
            return "minigame", max(0, min(3, page_idx))
        if tk in ("genshin", "hsr"):
            return "minigame", 1
        if tk == "fishing":
            return "minigame", 2
        if tk == "game":
            return "minigame", 3
        if tk in ("personal", "개인", "profile"):
            return "personal", max(0, min(3, page_idx))
        return "home", 0

    @property
    def current_tab(self) -> str:
        """하위 호환 프로퍼티"""
        return self.current_category

    @current_tab.setter
    def current_tab(self, val: str):
        cat, pg = self._resolve_initial_target(val, 0)
        self.current_category = cat
        self.current_page = pg
        self.sub_mode = None

    def _hydrate_context(self, interaction: discord.Interaction):
        if self.bot is None:
            self.bot = interaction.client
        if self.user is None:
            self.user = interaction.user
        if self.guild is None and interaction.guild is not None:
            self.guild = interaction.guild
        if not self.data:
            self.data = core.get_cached_data()

    def _restore_from_message(self, interaction: discord.Interaction):
        self._hydrate_context(interaction)
        msg = getattr(interaction, "message", None)
        if not msg:
            return
        restored = False
        is_home = False
        restored_sub: Optional[str] = None
        restored_cat_page: Optional[Tuple[str, int]] = None
        parsed_history: Optional[List[Tuple[str, int, Optional[str]]]] = None

        def _parse_nav_back_cid(cid_val: str) -> Optional[List[Tuple[str, int, Optional[str]]]]:
            if not cid_val.startswith("norosi:Settings:nav_back:"):
                return None
            payload = cid_val[len("norosi:Settings:nav_back:"):]
            hist: List[Tuple[str, int, Optional[str]]] = []
            for tok in payload.split("|"):
                dec = self._decode_nav_state(tok)
                if dec is not None:
                    hist.append(dec)
            return hist or None

        for row in getattr(msg, "components", []) or []:
            for comp in getattr(row, "children", []):
                cid = getattr(comp, "custom_id", "") or ""
                if cid in ("norosi:Settings:quick_jump_select", "norosi:Settings:cat_general"):
                    is_home = True
                elif cid.startswith("norosi:Settings:sub_") and restored_sub is None:
                    rest = cid[len("norosi:Settings:sub_"):]
                    if "_" in rest:
                        sub_name, idx_s = rest.rsplit("_", 1)
                        if idx_s.isdigit():
                            restored_sub = sub_name
                elif cid.startswith("norosi:Settings:act_") and restored_cat_page is None:
                    rest = cid[len("norosi:Settings:act_"):]
                    parts = rest.rsplit("_", 2)
                    if len(parts) == 3:
                        cat, page_s, _idx = parts
                        if page_s.isdigit():
                            restored_cat_page = (cat, int(page_s))
                elif cid.startswith("norosi:Settings:nav_back:") and parsed_history is None:
                    parsed_history = _parse_nav_back_cid(cid)

        if parsed_history is None and isinstance(getattr(interaction, "data", None), dict):
            clicked_cid = interaction.data.get("custom_id") or ""
            parsed_history = _parse_nav_back_cid(clicked_cid)

        if is_home:
            self.current_category = "home"
            self.current_page = 0
            self.sub_mode = None
            self._nav_history = []
            restored = True
        elif restored_sub is not None:
            self.sub_mode = restored_sub
            if parsed_history:
                self._nav_history = parsed_history
                top_cat, top_page, _top_sub = parsed_history[-1]
                self.current_category = top_cat
                self.current_page = top_page
            else:
                p_cat, p_page = SUB_MODE_PARENT_MAP.get(restored_sub, ("home", 0))
                self.current_category = p_cat
                self.current_page = p_page
                self._nav_history = []
            restored = True
        elif restored_cat_page is not None:
            self.current_category, self.current_page = restored_cat_page
            self.sub_mode = None
            self._nav_history = parsed_history if parsed_history else []
            restored = True

        if restored:
            self.refresh_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        self._hydrate_context(interaction)
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 설정 패널은 **{self.user.display_name}**님의 세션입니다.\n"
                "👉 본인의 설정 패널은 **`/설정`** 명령어로 언제든 새로 열 수 있습니다!",
                ephemeral=True,
            )
            return False
        return True

    def _find_cog_with_attr(self, attr_name: str):
        if not self.bot:
            return None
        return next((c for c in self.bot.cogs.values() if hasattr(c, attr_name)), None)

    # ----------------------------------------------------
    # 🛡️ 권한 검증 (일반 이용자 / 서버 관리자 / 봇 주인)
    # ----------------------------------------------------
    async def check_bot_owner_permission(self, interaction: discord.Interaction, action_name: str = "봇 주인 전용 기능") -> bool:
        bot_ref = self.bot or interaction.client
        is_owner = await bot_ref.is_bot_owner_user(interaction.user) if hasattr(bot_ref, "is_bot_owner_user") else (
            bool(core.BOT_OWNER_ID and interaction.user.id == core.BOT_OWNER_ID)
        )
        if is_owner:
            return True
        embed = discord.Embed(
            title="👑 [봇 주인 전용] 접근 제한 안내",
            description=(
                f"**`{action_name}`** 기능은 **👑 봇 주인(Bot Owner)** 만 조작할 수 있는 시스템/글로벌 설정입니다.\n\n"
                "• **👤 일반 이용자:** `🌐 일반`, `🎮 미니게임`, `👤 개인` 카테고리의 모든 기능 이용 가능\n"
                "• **🛡️ 서버 관리자:** `⚙️ 고급 (1~3페이지)`의 서버 관리 기능 이용 가능\n"
                "• **👑 봇 주인:** `⚙️ 고급 (4페이지)` 글로벌 픽업 · VM 터미널 · 전체 DB 백업 제어 가능"
            ),
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(core.KST),
        )
        await core.safe_send_response(interaction, embed=embed, ephemeral=True)
        return False

    async def check_admin_permission(
        self,
        interaction: discord.Interaction,
        action_name: str = "서버 관리자 기능",
        require_roles_perm: bool = False,
        require_channels_perm: bool = False,
        require_messages_perm: bool = False,
        require_strict_admin: bool = False,
    ) -> bool:
        perms = getattr(interaction.user, "guild_permissions", None)
        if not interaction.guild or perms is None:
            await core.safe_send_response(
                interaction,
                f"❌ **`{action_name}`** 기능은 디스코드 서버 채널 내에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return False

        bot_ref = self.bot or interaction.client
        is_owner = await bot_ref.is_bot_owner_user(interaction.user) if hasattr(bot_ref, "is_bot_owner_user") else (
            bool(core.BOT_OWNER_ID and interaction.user.id == core.BOT_OWNER_ID)
        )
        is_guild_owner = (getattr(interaction.guild, "owner_id", None) == interaction.user.id)

        if is_owner or is_guild_owner or perms.administrator:
            has_user_perm = True
        elif require_strict_admin:
            has_user_perm = False
        elif require_roles_perm:
            has_user_perm = perms.manage_roles or perms.manage_guild
        elif require_channels_perm:
            has_user_perm = perms.manage_channels or perms.manage_guild
        elif require_messages_perm:
            has_user_perm = perms.manage_messages or perms.manage_guild
        else:
            has_user_perm = (
                perms.manage_guild
                or perms.manage_roles
                or perms.manage_channels
                or perms.manage_messages
            )

        if not has_user_perm:
            req_txt = "서버 관리자(Administrator)" if require_strict_admin else "서버 관리자(Administrator / 서버·역할·채널 관리)"
            embed = discord.Embed(
                title="🛡️ [서버 관리자 전용] 권한 부족 안내",
                description=(
                    f"**`{action_name}`** 설정은 **{req_txt}** 권한을 보유한 관리자만 변경할 수 있습니다.\n\n"
                    "• 현재 회원님은 **`🌐 일반`**, **`🎮 미니게임`**, **`👤 개인`** 카테고리의 모든 기능을 자유롭게 이용하실 수 있습니다!"
                ),
                color=discord.Color.orange(),
                timestamp=datetime.datetime.now(core.KST),
            )
            await core.safe_send_response(interaction, embed=embed, ephemeral=True)
            return False

        if require_roles_perm and interaction.guild.me:
            bot_perms = interaction.guild.me.guild_permissions
            if not (bot_perms.manage_roles or bot_perms.administrator):
                await core.safe_send_response(
                    interaction,
                    "⚠️ **봇 권한 확인 필요:** 봇에게 서버 설정 > 역할에서 **`역할 관리(Manage Roles)`** 권한을 부여해 주세요!",
                    ephemeral=True,
                )
                return False

        return True

    # ----------------------------------------------------
    # 🗂️ 4대 카테고리 × 15페이지 (총 90개 기능) 통합 카탈로그
    # ----------------------------------------------------
    def _build_catalog_pages(self) -> Dict[str, List[Dict[str, Any]]]:
        return {
            # ==========================================
            # 1. 🌐 일반 (General) — 3 Pages (18 items)
            # ==========================================
            "general": [
                {
                    "page_title": "📅 출석체크 · D-Day · 생일 · 프로세카 일정",
                    "perm": PERM_USER,
                    "items": [
                        {
                            "label": "오늘 출석체크",
                            "emoji": "📅",
                            "style": discord.ButtonStyle.success,
                            "perm": PERM_USER,
                            "desc": "하루 1회 서버별 출석 도장 및 크리스탈(100~2000💎) 수령",
                            "cb": self._act_attendance,
                        },
                        {
                            "label": "월간 출석달력",
                            "emoji": "🗓️",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "이번 달 출석 캘린더 및 7/14/21/28일 개근 마일스톤 확인",
                            "cb": self._act_att_calendar,
                        },
                        {
                            "label": "출석체크 랭킹",
                            "emoji": "🏆",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "현재 서버 및 전체 서버 누적·연속 출석 순위표",
                            "cb": self._act_att_ranking,
                        },
                        {
                            "label": "D-Day 전광판",
                            "emoji": "📋",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "등록된 모든 D-Day 은하수 잔디 진행률 보드 · 지나간 디데이(추억 보관소)",
                            "cb": self._act_dday_list,
                        },
                        {
                            "label": "생일 전광판",
                            "emoji": "🎂",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "다가오는 서버 멤버 생일 목록 확인 및 내 생일 등록(+500💎)",
                            "cb": self._act_birthday_board,
                        },
                        {
                            "label": "프로세카 미래시·이벤트",
                            "emoji": "🔭",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "프로세카 한섭 미래시 캘린더 및 한섭/일섭 실시간 이벤트",
                            "cb": self._act_sekai_schedule_hub,
                        },
                    ],
                },
                {
                    "page_title": "🎵 음악 추천 · 플리 · 무드 라디오 · 음성 컨트롤",
                    "perm": PERM_USER,
                    "items": [
                        {
                            "label": "플리 스튜디오",
                            "emoji": "💿",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "유튜브·스포티파이·사클 플레이리스트 제작·가져오기·자동재생",
                            "cb": self._act_playlist_studio,
                        },
                        {
                            "label": "무드 음성 라디오",
                            "emoji": "📻",
                            "style": discord.ButtonStyle.success,
                            "perm": PERM_USER,
                            "desc": "로파이·프세카·새벽감성·시티팝·게임OST·피아노 6대 원클릭 라디오",
                            "cb": self._act_mood_radio,
                        },
                        {
                            "label": "지금 음악추천",
                            "emoji": "🎧",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "현재 시간대 감성에 어울리는 프로세카/보컬로이드 곡 즉시 선곡",
                            "cb": self._act_music_now,
                        },
                        {
                            "label": "내 애청곡 보관함",
                            "emoji": "❤️",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "하트(❤️)로 스크랩한 추천 음악 목록 조회 및 셔플 감상",
                            "cb": self._act_music_vault,
                        },
                        {
                            "label": "배속·헤드셋·음성방",
                            "emoji": "⏩",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "재생 배속(0.75x~2.0x), 봇 헤드셋 토글, 내 임시음성방 리모컨",
                            "cb": self._act_music_voice_hub,
                        },
                        {
                            "label": "440Hz 오디오 진단",
                            "emoji": "🔊",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "음성채널 DAVE E2EE 암호화 및 비프음 출력 자가진단",
                            "cb": self._act_audio_test,
                        },
                    ],
                },
                {
                    "page_title": "📊 서버 통계 · 파티 · 예약 이벤트 · 날씨 · 협동",
                    "perm": PERM_USER,
                    "items": [
                        {
                            "label": "실시간 서버통계",
                            "emoji": "📊",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "서버 일간/주간 채팅량, 활성 채널 Top3, 음성 통화 현황 분석",
                            "cb": self._act_server_stats,
                        },
                        {
                            "label": "게임 파티모집",
                            "emoji": "🎮",
                            "style": discord.ButtonStyle.success,
                            "perm": PERM_USER,
                            "desc": "프로세카·원신·롤·발로란트 등 자유 양식 팀원 실시간 모집",
                            "cb": self._act_recruit,
                        },
                        {
                            "label": "예약 이벤트 RSVP",
                            "emoji": "🗓️",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "참가·보류·불참 신청표, 정원 대기열 자동승격, 15분 전 자동 리마인드",
                            "cb": self._act_guild_events,
                        },
                        {
                            "label": "실시간 날씨",
                            "emoji": "🌤️",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "기상청/ECMWF 실시간 기온·체감온도·미세먼지·강수확률 조회",
                            "cb": self._act_weather,
                        },
                        {
                            "label": "협동 릴레이소설",
                            "emoji": "✍️",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "한 줄씩 이어 쓰는 채널 협동 릴레이 소설 시작·이어쓰기·명작집",
                            "cb": self._act_relay_novel_hub,
                        },
                        {
                            "label": "봇 건의 & 피드백",
                            "emoji": "📬",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "개발진/운영진에게 익명 또는 계정 공개로 건의사항 전달",
                            "cb": self._act_suggestion,
                        },
                    ],
                },
            ],

            # ==========================================
            # 2. ⚙️ 고급 (Advanced) — 4 Pages (24 items)
            #    * 1~3페이지: 🛡️ 서버 관리자 전용
            #    * 4페이지: 👑 봇 주인 전용 (+ 호스트 상태)
            # ==========================================
            "advanced": [
                {
                    "page_title": "🛡️ [서버 관리자] 역할 · 공지 · 1:1 티켓 관리",
                    "perm": PERM_ADMIN,
                    "items": [
                        {
                            "label": "역할버튼 빠른제작",
                            "emoji": "🚀",
                            "style": discord.ButtonStyle.success,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] 팝업 모달로 사진 스타일 역할 부여 버튼 즉시 발행",
                            "cb": self._act_admin_quick_role,
                        },
                        {
                            "label": "반응역할 스튜디오",
                            "emoji": "🎭",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] 이모지/버튼 반응역할 생성, 기존 메시지 바인딩 및 관리",
                            "cb": self._act_admin_role_studio,
                        },
                        {
                            "label": "반응역할 전체목록",
                            "emoji": "📜",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] 서버에 등록된 모든 반응역할 패널 조회 및 해제",
                            "cb": self._act_admin_role_list,
                        },
                        {
                            "label": "스마트 공지발송",
                            "emoji": "📢",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] 6대 테마 컬러·추천 템플릿·사전 미리보기 공지 스튜디오",
                            "cb": self._act_admin_announce,
                        },
                        {
                            "label": "1:1 문의티켓 설정",
                            "emoji": "🎫",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] 1:1 비공개 문의 티켓 패널 설치 및 담당자 역할 설정",
                            "cb": self._act_admin_ticket_hub,
                        },
                        {
                            "label": "티켓 내역 조회",
                            "emoji": "📋",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] 서버의 진행 중 / 종료된 1:1 문의 티켓 전체 목록",
                            "cb": self._act_admin_ticket_list,
                        },
                    ],
                },
                {
                    "page_title": "🛡️ [서버 관리자] 음성방 · 고정글 · 보안 · 업스케일 · 감사로그",
                    "perm": PERM_ADMIN,
                    "items": [
                        {
                            "label": "임시음성방 설정",
                            "emoji": "🔊",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] 입장 시 자동 생성·퇴장 시 삭제되는 임시 음성방 설정",
                            "cb": self._act_admin_temp_voice,
                        },
                        {
                            "label": "자동 고정메시지",
                            "emoji": "📌",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] 채널 하단에 항상 유지되는 안내 고정 메시지(Sticky) 관리",
                            "cb": self._act_admin_sticky_hub,
                        },
                        {
                            "label": "SNS 링크보정 설정",
                            "emoji": "🔗",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] X/인스타/픽시브 임베드 보정 및 추적 파라미터 제거 설정",
                            "cb": self._act_admin_link_fix,
                        },
                        {
                            "label": "레이드 비상방어",
                            "emoji": "🚨",
                            "style": discord.ButtonStyle.danger,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] 동시 입장(Raid) 자동 감지 및 서버 긴급 잠금(Lockdown)",
                            "cb": self._act_admin_raid_def,
                        },
                        {
                            "label": "이모지 업스케일",
                            "emoji": "🔍",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] 커스텀 이모지 160px Lanczos3 WebP 자동 업스케일 ON/OFF",
                            "cb": self._act_admin_emoji_upscale,
                        },
                        {
                            "label": "실시간 감사로그",
                            "emoji": "📜",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] 메시지 삭제/수정·입퇴장·음성 등 7대 감사 로그 채널 · 상세/요약 버전 설정",
                            "cb": self._act_admin_audit_log,
                        },
                    ],
                },
                {
                    "page_title": "🛡️ [서버 관리자] 메시지 청소 · 잠수 감사 · 스케줄 · 데이터 초기화",
                    "perm": PERM_ADMIN,
                    "items": [
                        {
                            "label": "채널 메시지청소",
                            "emoji": "🧹",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] 채널 메시지를 개수·키워드·봇·미디어·특정유저 조건으로 일괄 삭제",
                            "cb": self._act_admin_purge,
                        },
                        {
                            "label": "비활성 멤버감사",
                            "emoji": "👻",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] 최근 7~90일간 출석·채팅 기록이 없는 잠수 멤버 스캔",
                            "cb": self._act_admin_inactive,
                        },
                        {
                            "label": "D-Day & 채널 설정",
                            "emoji": "📅",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] 새 D-Day·전광판 채널 추가, 카테고리/9시 알림채널 설정, 삭제",
                            "cb": self._act_admin_dday_hub,
                        },
                        {
                            "label": "음악 스케줄러 설정",
                            "emoji": "🌅",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] 오전 7시 모닝 음악추천 채널·장르 및 맞춤 시간 음악알람 설정",
                            "cb": self._act_admin_music_sched_hub,
                        },
                        {
                            "label": "[봇주인] GitHub 배포알림",
                            "emoji": "🐙",
                            "style": discord.ButtonStyle.danger,
                            "perm": PERM_OWNER,
                            "desc": "[👑봇주인 전용] GitHub Push 및 Actions 배포 알림 수신 채널 원클릭 연동",
                            "cb": self._act_admin_github_webhook,
                        },
                        {
                            "label": "서버 데이터초기화",
                            "emoji": "⚠️",
                            "style": discord.ButtonStyle.danger,
                            "perm": PERM_ADMIN,
                            "desc": "[🛡️서버관리자] 서버 D-Day/음악 · 프로세카 · 원신 · 스타레일 데이터 초기화",
                            "cb": self._act_admin_reset_hub,
                        },
                    ],
                },
                {
                    "page_title": "👑 [봇 주인 전용] 글로벌 픽업 · VM 터미널 · GitHub 연동 · 봇 상태 · DB 백업",
                    "perm": PERM_OWNER,
                    "items": [
                        {
                            "label": "[봇주인] 프로세카 픽업",
                            "emoji": "🎯",
                            "style": discord.ButtonStyle.danger,
                            "perm": PERM_OWNER,
                            "desc": "[👑봇주인 전용] 한섭 실시간 이벤트 픽업 자동 연동 및 페스/생일/수동 픽업 제어",
                            "cb": self._act_owner_sekai_pickup_hub,
                        },
                        {
                            "label": "[봇주인] 원신 픽업",
                            "emoji": "🌠",
                            "style": discord.ButtonStyle.danger,
                            "perm": PERM_OWNER,
                            "desc": "[👑봇주인 전용] 원신 기원 KST 2시간 자동 로테이션 및 수동 배너 픽업 제어",
                            "cb": self._act_owner_gi_pickup_hub,
                        },
                        {
                            "label": "[봇주인] 스타레일 픽업",
                            "emoji": "🚄",
                            "style": discord.ButtonStyle.danger,
                            "perm": PERM_OWNER,
                            "desc": "[👑봇주인 전용] 스타레일 워프 KST 2시간 자동 로테이션 및 수동 픽업 제어",
                            "cb": self._act_owner_hsr_pickup_hub,
                        },
                        {
                            "label": "[봇주인] 터미널·GitHub",
                            "emoji": "🖥️",
                            "style": discord.ButtonStyle.danger,
                            "perm": PERM_OWNER,
                            "desc": "[👑봇주인 전용] VM 서버 터미널 로그(상세/요약 버전) 및 GitHub 배포알림 채널 연동",
                            "cb": self._act_owner_terminal_hub,
                        },
                        {
                            "label": "[봇주인] 백업 & 동기화",
                            "emoji": "💾",
                            "style": discord.ButtonStyle.danger,
                            "perm": PERM_OWNER,
                            "desc": "[👑봇주인 전용] 전체 DB / 서버 구조 JSON 백업 및 슬래시 명령어 즉시 동기화",
                            "cb": self._act_owner_backup_sync_hub,
                        },
                        {
                            "label": "[봇주인] 봇 상태 진단",
                            "emoji": "🤖",
                            "style": discord.ButtonStyle.danger,
                            "perm": PERM_OWNER,
                            "desc": "[👑봇주인 전용] 봇 호스트 RAM, CPU, 디스크, 핑, 업타임 상태 진단 (상세/요약 버전)",
                            "cb": self._act_bot_host_status,
                        },
                    ],
                },
            ],

            # ==========================================
            # 3. 🎮 미니게임 (Minigames) — 4 Pages (24 items)
            # ==========================================
            "minigame": [
                {
                    "page_title": "🎤 프로젝트 세카이 가챠 & 세카이 컨텐츠",
                    "perm": PERM_USER,
                    "items": [
                        {
                            "label": "프로세카 10회 뽑기",
                            "emoji": "🌈",
                            "style": discord.ButtonStyle.success,
                            "perm": PERM_USER,
                            "desc": "한섭 10연차 (사전등록 ★1 지급 · 50/100pt 게이지 · 200배지 천장 · 특훈 전/후 전환)",
                            "cb": self._act_sekai_pull_10,
                        },
                        {
                            "label": "가챠등록·천장·셀렉트",
                            "emoji": "🔮",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "사전등록(★1 지급) · 단차 · 200배지 천장 · 셀렉트(특수티켓) · 캐랭 · 운명 · 연습",
                            "cb": self._act_sekai_pull_hub,
                        },
                        {
                            "label": "세카이 라이브",
                            "emoji": "⚔️",
                            "style": discord.ButtonStyle.success,
                            "perm": PERM_USER,
                            "desc": "5인 유닛 덱 & 3D 의상 시너지 라이브 플레이 (전체 랭크 상승 · 스탬프 보상)",
                            "cb": self._act_sekai_live,
                        },
                        {
                            "label": "마스터 랭크 돌파",
                            "emoji": "🏆",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "중복 카드(0💎)·크리스탈 마스터 랭크(✦1~5) 돌파 & 특훈 전·후 감상 · 헤어 해금",
                            "cb": self._act_sekai_master_rank,
                        },
                        {
                            "label": "3D 의상실 & 헤어",
                            "emoji": "👗",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "캐릭터별 3D 의상 착용, 어나더 컬러·특훈 전/후 전환 및 새 의상 제작(300💎)",
                            "cb": self._act_sekai_wardrobe,
                        },
                        {
                            "label": "마이세카이 미니룸",
                            "emoji": "🏠",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "세카이 미니룸 테마·가구 배치, 오시 액자(특훈 전/후) 및 출석 추가 크리스탈 보너스",
                            "cb": self._act_sekai_myroom,
                        },
                    ],
                },
                {
                    "page_title": "🌠 원신 기원 & 🚄 붕괴: 스타레일 워프",
                    "perm": PERM_USER,
                    "items": [
                        {
                            "label": "원신 10회 기원",
                            "emoji": "🌠",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "원신 캐릭터 이벤트 기원 10연차 즉시 실행 (90천장·포착된 광휘)",
                            "cb": self._act_gi_pull_10,
                        },
                        {
                            "label": "원신 배너·무기·성유물",
                            "emoji": "🧭",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "캐릭터①② · 무기(운명의궤도) · 성유물 · 상시 · 리세마라 연습 기원 허브",
                            "cb": self._act_gi_banner_hub,
                        },
                        {
                            "label": "원신 페이몬 상점",
                            "emoji": "🧚",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "스타라이트 월간 ★4 캐릭터·무기 및 스타더스트 인연·경험치 교환",
                            "cb": self._act_gi_shop,
                        },
                        {
                            "label": "스타레일 10회 워프",
                            "emoji": "🚆",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "붕괴: 스타레일 캐릭터 이벤트 워프 10연차 즉시 실행",
                            "cb": self._act_hsr_warp_10,
                        },
                        {
                            "label": "스타레일 배너·광추·유물",
                            "emoji": "🎁",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "캐릭터①② · 광추 · 터널유물 · 상시(300선택) · 리세마라 연습 워프 허브",
                            "cb": self._act_hsr_banner_hub,
                        },
                        {
                            "label": "스타레일 상점",
                            "emoji": "🛍️",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "별빛 교환(5성 광추), 헤르타의 상점(채권 광추·중첩기), 잔재 교환",
                            "cb": self._act_hsr_shop,
                        },
                    ],
                },
                {
                    "page_title": "🎣 통합 낚시 (36,700종) & 🌾 농장·펫·요리 생활",
                    "perm": PERM_USER,
                    "items": [
                        {
                            "label": "낚시 출조 (3대수역)",
                            "emoji": "🎣",
                            "style": discord.ButtonStyle.success,
                            "perm": PERM_USER,
                            "desc": "🏞️호수·🌊강·⚓바다 13개 세부 수역 출조 & 입질 타이밍 미니게임",
                            "cb": self._act_fishing_cast,
                        },
                        {
                            "label": "주말·제철 낚시대회",
                            "emoji": "🏅",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "실시간 낚시 토너먼트 순위표 & 계절 한정 제철 어종 보너스 확인",
                            "cb": self._act_fishing_tourney,
                        },
                        {
                            "label": "내 프라이빗 수족관",
                            "emoji": "🐠",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "포획한 대물을 어항에 전시하고 시간당 낚시 골드(🪙) 패시브 수익 수확",
                            "cb": self._act_fishing_aquarium,
                        },
                        {
                            "label": "낚시 장비·미끼상점",
                            "emoji": "🛒",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "낚싯대 6티어·릴 5티어 업그레이드, 특급 미끼 및 어항 확장권 구매",
                            "cb": self._act_fishing_shop,
                        },
                        {
                            "label": "생활 통합 대시보드",
                            "emoji": "🌿",
                            "style": discord.ButtonStyle.success,
                            "perm": PERM_USER,
                            "desc": "개인 농장 · 서버 공동농장 · 펫 돌보기 · 생선 요리 통합 현황판",
                            "cb": self._act_life_dashboard,
                        },
                        {
                            "label": "농장·공동농장·펫·요리",
                            "emoji": "🌾",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "개인농장 · 서버 공동농장 · 6종 펫 육성 · 생선 요리 · 활성 버프 허브",
                            "cb": self._act_life_personal_hub,
                        },
                    ],
                },
                {
                    "page_title": "👶 타인의 삶 & 🎲 캐주얼 미니게임 · 통합 도감/랭킹",
                    "perm": PERM_USER,
                    "items": [
                        {
                            "label": "타인의 삶 플레이",
                            "emoji": "👶",
                            "style": discord.ButtonStyle.success,
                            "perm": PERM_USER,
                            "desc": "0세부터 노년까지 살아가는 스토리 인생 시뮬레이션 (1,000종 멀티엔딩)",
                            "cb": self._act_other_life_play,
                        },
                        {
                            "label": "타인의 삶 엔딩도감",
                            "emoji": "📜",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "해금한 멀티 엔딩 도감 수집률 및 내가 살아온 인생 연대기 아카이브",
                            "cb": self._act_other_life_codex,
                        },
                        {
                            "label": "실시간 끝말잇기",
                            "emoji": "🔤",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "표준 두음법칙이 자동 적용되는 1:1 / 멀티 단어 배틀 (+150💎)",
                            "cb": self._act_word_chain,
                        },
                        {
                            "label": "스릴 러시안룰렛",
                            "emoji": "🔫",
                            "style": discord.ButtonStyle.danger,
                            "perm": PERM_USER,
                            "desc": "6연발 실린더 생존 서바이벌 게임 (생존 시 보너스 크리스탈 획득)",
                            "cb": self._act_roulette,
                        },
                        {
                            "label": "통합 도감 & 확률표",
                            "emoji": "📖",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "프로세카 · 원신 · 스타레일 · 낚시 · 타인의삶 도감 및 확률표 허브",
                            "cb": self._act_pokedex_hub,
                        },
                        {
                            "label": "통합 랭킹 보드",
                            "emoji": "🏆",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "가챠 · 원신 · 스타레일 · 낚시 · 타인의삶 · 순자산 서버 랭킹 허브",
                            "cb": self._act_ranking_hub,
                        },
                    ],
                },
            ],

            # ==========================================
            # 4. 👤 개인 (Personal) — 4 Pages (24 items)
            # ==========================================
            "personal": [
                {
                    "page_title": "🪪 내 프로필 · 오시 · 칭호/배지 · 크리스탈 송금",
                    "perm": PERM_USER,
                    "items": [
                        {
                            "label": "통합 PNG 프로필카드",
                            "emoji": "🪪",
                            "style": discord.ButtonStyle.success,
                            "perm": PERM_USER,
                            "desc": "프로세카·원신·스타레일·낚시·생활·칭호·배지 고화질 PNG 카드 발급",
                            "cb": self._act_profile_card_png,
                        },
                        {
                            "label": "프로세카 내 프로필",
                            "emoji": "🎸",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "오시 일러스트(특훈 전/후), 5인 덱, 마이세카이, 라이브·전체 랭크 종합 프로필",
                            "cb": self._act_sekai_profile,
                        },
                        {
                            "label": "최애(오시) 설정",
                            "emoji": "💖",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "26인 프로세카 캐릭터 중 내 대표 오시 캐릭터를 드롭다운으로 설정",
                            "cb": self._act_oshi_setup,
                        },
                        {
                            "label": "칭호 상점 & 배지",
                            "emoji": "🏷️",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "한정 칭호 구매·장착 및 업적 자동 해금 배지 쇼케이스 열람",
                            "cb": self._act_title_shop,
                        },
                        {
                            "label": "크리스탈 송금",
                            "emoji": "💸",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "서버 멤버를 선택해 보유 크리스탈 송금 (수수료 5% · 일일 5,000💎)",
                            "cb": self._act_crystal_transfer,
                        },
                        {
                            "label": "내 디스코드 정보",
                            "emoji": "📊",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "내 디스코드 가입일, 서버 입장 순번(#N번째), 보유 역할, 활동량 조회",
                            "cb": self._act_user_info,
                        },
                    ],
                },
                {
                    "page_title": "🎒 4대 게임 개인 보관함 · 덱/파티 편성 · 카드 강화",
                    "perm": PERM_USER,
                    "items": [
                        {
                            "label": "프로세카 보관함",
                            "emoji": "🎒",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "보유 카드 조회(★3·★4 기본 특훈 전 · 특훈 전/후 버튼 전환 · ★3 우선 정렬 · 🔒잠금)",
                            "cb": self._act_sekai_inv,
                        },
                        {
                            "label": "중복카드 일괄환전",
                            "emoji": "💎",
                            "style": discord.ButtonStyle.success,
                            "perm": PERM_USER,
                            "desc": "2장 이상 중복 보유 카드(원본·잠금 제외)를 성급별 크리스탈로 환전",
                            "cb": self._act_sekai_dup_convert,
                        },
                        {
                            "label": "5인 덱 & 카드강화",
                            "emoji": "🎴",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "내 프로세카 5인 유닛 덱 현황 확인 및 보유 카드 레벨업 강화",
                            "cb": self._act_sekai_deck_hub,
                        },
                        {
                            "label": "원신 보관함 & 파티",
                            "emoji": "🌠",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "원신 보유 캐릭터·무기·성유물 육성 및 4인 원소 공명 파티 편성",
                            "cb": self._act_gi_personal_hub,
                        },
                        {
                            "label": "스타레일 보관함·편대",
                            "emoji": "🚄",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "스타레일 보유 캐릭터·광추·유물 육성 및 4인 개척 편대 시너지 편성",
                            "cb": self._act_hsr_personal_hub,
                        },
                        {
                            "label": "낚시 가방 & 퀘스트",
                            "emoji": "👜",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "포획한 물고기 보관함 판매·잠금 및 일일 낚시 의뢰 3종 보상 수령",
                            "cb": self._act_fishing_personal_hub,
                        },
                    ],
                },
                {
                    "page_title": "🌱 오늘목표 잔디 · 집중 스터디 · 개인 일정 · 파트너",
                    "perm": PERM_USER,
                    "items": [
                        {
                            "label": "오늘목표 & 은하수잔디",
                            "emoji": "🌱",
                            "style": discord.ButtonStyle.success,
                            "perm": PERM_USER,
                            "desc": "오늘의 할 일(To-Do) 체크리스트 관리 및 최근 7일 은하수 잔디 보드",
                            "cb": self._act_todo_grass,
                        },
                        {
                            "label": "뽀모도로 집중모드",
                            "emoji": "⏳",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "집중/휴식 스터디 타이머 실행 및 음성채널 자동 음소거 제어",
                            "cb": self._act_pomodoro,
                        },
                        {
                            "label": "하드코어 스터디",
                            "emoji": "🔥",
                            "style": discord.ButtonStyle.danger,
                            "perm": PERM_USER,
                            "desc": "50분 집중/10분 휴식 음성 안내 사이클 & 은하수 보라잔디(🟪) 획득",
                            "cb": self._act_hardcore_study,
                        },
                        {
                            "label": "개인 스마트 알림예약",
                            "emoji": "⏰",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "지정한 시각이나 N분 뒤에 나에게 DM/채널 멘션으로 개인 알림 발송",
                            "cb": self._act_reminder_hub,
                        },
                        {
                            "label": "나만의 비밀 D-Day",
                            "emoji": "🔒",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "나만 볼 수 있는 비공개 개인 D-Day 및 목표일 오전 9시 타임캡슐",
                            "cb": self._act_secret_dday,
                        },
                        {
                            "label": "내 생일 & 파트너",
                            "emoji": "💑",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "내 생일 등록/수정(+500💎) 및 연인·친구 파트너 공동 D-Day·공유음악",
                            "cb": self._act_bday_partner_hub,
                        },
                    ],
                },
                {
                    "page_title": "☀️ 일일 루틴 · 주간 미션 · 환전소 · 쇼케이스 · 즉석 대전",
                    "perm": PERM_USER,
                    "items": [
                        {
                            "label": "오늘의 일일 루틴",
                            "emoji": "☀️",
                            "style": discord.ButtonStyle.success,
                            "perm": PERM_USER,
                            "desc": "출석·낚시 의뢰·농장·공동농장·운명뽑기·목표 한눈에 확인 및 가능 보상 일괄 수령",
                            "cb": self._act_daily_routine,
                        },
                        {
                            "label": "통합 주간 미션",
                            "emoji": "🎯",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "주간 출석·낚시·농장·도감 미션 달성률 확인 및 올클리어 보상 수령",
                            "cb": self._act_weekly_missions,
                        },
                        {
                            "label": "골드⇄크리스탈 환전",
                            "emoji": "💱",
                            "style": discord.ButtonStyle.primary,
                            "perm": PERM_USER,
                            "desc": "낚시 골드(500🪙➔100💎) · 크리스탈(100💎➔450🪙) 일일 한도 안전 환전소",
                            "cb": self._act_currency_exchange,
                        },
                        {
                            "label": "내 수집품 쇼케이스",
                            "emoji": "🏆",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "프로세카 5인 덱 · 원신/스타레일 파티 · 수족관 대물 · 타인의 삶 통합 자랑 카드",
                            "cb": self._act_showcase,
                        },
                        {
                            "label": "파트너 농장 물주기",
                            "emoji": "💑",
                            "style": discord.ButtonStyle.secondary,
                            "perm": PERM_USER,
                            "desc": "파트너의 개인 농장에 대신 물을 주고 양쪽 모두 우정 보너스(+50💎·+100🪙) 획득",
                            "cb": self._act_partner_farm_water,
                        },
                        {
                            "label": "즉석 미니 대전",
                            "emoji": "🎲",
                            "style": discord.ButtonStyle.success,
                            "perm": PERM_USER,
                            "desc": "채널 멤버들과 바로 붙는 하이로우 주사위 대결(무료/50💎) & 72종 초성 퀴즈",
                            "cb": self._act_mini_battle_hub,
                        },
                    ],
                },
            ],
        }

    # ----------------------------------------------------
    # 🔢 통합 페이지네이션 인덱스 계산 헬퍼 (총 15페이지)
    # ----------------------------------------------------
    def _get_flat_pages(self) -> List[Tuple[str, int]]:
        flat: List[Tuple[str, int]] = []
        for cat_k in CATEGORY_ORDER:
            pages = self._pages_cache.get(cat_k, [])
            for p_idx in range(len(pages)):
                flat.append((cat_k, p_idx))
        return flat

    def _get_global_page_info(self, category: str, page: int) -> Tuple[int, int]:
        flat = self._get_flat_pages()
        total = len(flat)
        try:
            idx = flat.index((category, page))
            return idx + 1, total
        except ValueError:
            return 1, total

    def _step_global_page(self, delta: int):
        flat = self._get_flat_pages()
        if not flat:
            return
        if self.current_category == "home":
            target_idx = 0 if delta > 0 else (len(flat) - 1)
        else:
            try:
                cur_idx = flat.index((self.current_category, self.current_page))
            except ValueError:
                cur_idx = 0
            target_idx = (cur_idx + delta) % len(flat)
        self.current_category, self.current_page = flat[target_idx]
        self.sub_mode = None

    # ----------------------------------------------------
    # 🧩 동적 UI 컴포넌트 빌더 (1단계 홈 / 2단계 카테고리 / 3단계 세부패널)
    # ----------------------------------------------------
    def refresh_components(self):
        self.clear_items()
        caller_tier = detect_user_perm_tier_sync(self.user, self.guild)

        # [3단계] 세부 제어판(Sub-View) 활성 상태
        if self.sub_mode is not None:
            self._build_sub_mode_components(caller_tier)
            return

        # [1단계] /설정 홈 화면 (4대 메인 카테고리 버튼 + 개인 커스텀 단축바 + 통합 페이지네이션)
        if self.current_category == "home":
            # Row 0: 일반, 고급, 미니게임, 개인 (핵심 4대 버튼)
            btn_gen = discord.ui.Button(
                label="일반",
                emoji="🌐",
                style=discord.ButtonStyle.primary,
                row=0,
                custom_id="norosi:Settings:cat_general",
            )
            btn_gen.callback = self._make_cat_enter_cb("general")
            self.add_item(btn_gen)

            adv_style = discord.ButtonStyle.danger if caller_tier in (PERM_ADMIN, PERM_OWNER) else discord.ButtonStyle.secondary
            btn_adv = discord.ui.Button(
                label="고급",
                emoji="⚙️",
                style=adv_style,
                row=0,
                custom_id="norosi:Settings:cat_advanced",
            )
            btn_adv.callback = self._make_cat_enter_cb("advanced")
            self.add_item(btn_adv)

            btn_mini = discord.ui.Button(
                label="미니게임",
                emoji="🎮",
                style=discord.ButtonStyle.success,
                row=0,
                custom_id="norosi:Settings:cat_minigame",
            )
            btn_mini.callback = self._make_cat_enter_cb("minigame")
            self.add_item(btn_mini)

            btn_pers = discord.ui.Button(
                label="개인",
                emoji="👤",
                style=discord.ButtonStyle.primary,
                row=0,
                custom_id="norosi:Settings:cat_personal",
            )
            btn_pers.callback = self._make_cat_enter_cb("personal")
            self.add_item(btn_pers)

            # Row 1: 개인 커스텀 즐겨찾기 단축바 (기본 5종, 유저별 최대 5개 자유 편집 가능)
            uid = self.user.id if self.user else 0
            shortcut_keys = core.get_user_home_shortcuts(
                self.data, uid, valid_keys=HOME_SHORTCUT_KEYS
            )
            for s_key in shortcut_keys[:5]:
                s_meta = HOME_SHORTCUT_MAP.get(s_key)
                if not s_meta:
                    continue
                q_cb = getattr(self, s_meta["cb_name"], None)
                if not q_cb:
                    continue
                qb = discord.ui.Button(
                    label=s_meta["label"],
                    emoji=s_meta["emoji"],
                    style=s_meta["style"],
                    row=1,
                    custom_id=f"norosi:Settings:q_{s_key}",
                )
                qb.callback = q_cb
                self.add_item(qb)

            # Row 2: 올인원 빠른 실행 · 즐겨찾기 편집 · 라디오 · 이벤트 · 랭킹 · 도감 셀렉터
            quick_sel = discord.ui.Select(
                placeholder="🔍 빠른 실행 · 즐겨찾기 편집 · 랭킹 · 도감...",
                custom_id="norosi:Settings:quick_jump_select",
                row=2,
                options=[
                    discord.SelectOption(label="🔍 통합 기능 검색 (키워드 점프)", value="feature_search", description="키워드로 130+ 기능 즉시 실행"),
                    discord.SelectOption(label="⭐ 홈 즐겨찾기 단축바 편집", value="home_shortcuts", description="홈 버튼 5개 커스텀"),
                    discord.SelectOption(label="🏅 내 업적 & 뱃지 (12종)", value="achievements", description="크로스 기능 업적 달성 현황"),
                    discord.SelectOption(label="📅 D-Day 채널·알림 설정", value="admin_dday", description="전광판 채널·카테고리·9시 알림"),
                    discord.SelectOption(label="🕰️ 지나간 D-Day 보관소", value="dday_past"),
                    discord.SelectOption(label="📻 무드 음성 라디오", value="mood_radio", description="6대 분위기 BGM"),
                    discord.SelectOption(label="🗓️ 예약 이벤트 신청표", value="guild_events", description="RSVP·대기열·알림"),
                    discord.SelectOption(label="🏆 전 분야 통합 랭킹", value="ranking_hub", description="8대 순위표"),
                    discord.SelectOption(label="📅 출석체크 랭킹", value="att_rank"),
                    discord.SelectOption(label="🎤 프로세카 가챠 랭킹", value="sekai_rank"),
                    discord.SelectOption(label="🌠 원신 수집 랭킹", value="gi_rank"),
                    discord.SelectOption(label="🚄 스타레일 워프 랭킹", value="hsr_rank"),
                    discord.SelectOption(label="🎣 낚시 대물·대회 랭킹", value="fish_rank"),
                    discord.SelectOption(label="👶 타인의 삶 엔딩 랭킹", value="ol_rank"),
                    discord.SelectOption(label="🏦 통합 순자산 랭킹", value="eco_rank"),
                    discord.SelectOption(label="📖 5대 통합 도감·확률표", value="pokedex_hub"),
                    discord.SelectOption(label="🎒 프로세카 카드 보관함", value="sekai_inv"),
                    discord.SelectOption(label="✨ 프로세카 마스터 랭크", value="sekai_mr"),
                    discord.SelectOption(label="👗 캐릭터 3D 의상실", value="sekai_costume"),
                    discord.SelectOption(label="⚔️ 세카이 협동 라이브", value="sekai_live"),
                    discord.SelectOption(label="💿 플레이리스트 스튜디오", value="music_pl"),
                    discord.SelectOption(label="🌤️ 실시간 기상청 날씨", value="weather"),
                    discord.SelectOption(label="🔤 끝말잇기 대결", value="wordchain"),
                    discord.SelectOption(label="🔫 러시안 룰렛", value="roulette"),
                    discord.SelectOption(label="💖 팀 봉화 후원하기", value="sponsor", description="소유주 : 아시 · 봇 운영 지원"),
                ],
            )
            quick_sel.callback = self._on_home_quick_jump_selected
            self.add_item(quick_sel)

            # Row 3: 통합 페이지네이션 시작 바 + 도움말 + 새로고침
            flat_total = len(self._get_flat_pages())
            prev_btn = discord.ui.Button(
                label="◀",
                style=discord.ButtonStyle.secondary,
                row=3,
                custom_id="norosi:Settings:nav_prev",
            )
            prev_btn.callback = self._on_prev_page_clicked
            self.add_item(prev_btn)

            ind_btn = discord.ui.Button(
                label=f"🏠 홈 {flat_total}p",
                style=discord.ButtonStyle.secondary,
                disabled=True,
                row=3,
                custom_id="norosi:Settings:nav_ind",
            )
            ind_btn.callback = core.safe_defer
            self.add_item(ind_btn)

            next_btn = discord.ui.Button(
                label="▶",
                style=discord.ButtonStyle.secondary,
                row=3,
                custom_id="norosi:Settings:nav_next",
            )
            next_btn.callback = self._on_next_page_clicked
            self.add_item(next_btn)

            help_btn = discord.ui.Button(
                label="도움말",
                emoji="📖",
                style=discord.ButtonStyle.secondary,
                row=3,
                custom_id="norosi:Settings:nav_help",
            )
            help_btn.callback = self._act_open_help
            self.add_item(help_btn)

            ref_btn = discord.ui.Button(
                label="새로고침",
                emoji="🔄",
                style=discord.ButtonStyle.primary,
                row=3,
                custom_id="norosi:Settings:nav_refresh",
            )
            ref_btn.callback = self._on_refresh_clicked
            self.add_item(ref_btn)

            return

        # [2단계] 카테고리 내부 화면 (일반 / 고급 / 미니게임 / 개인)
        cat_pages = self._pages_cache.get(self.current_category, [])
        if not cat_pages:
            self.current_category = "general"
            cat_pages = self._pages_cache["general"]

        self.current_page = max(0, min(self.current_page, len(cat_pages) - 1))
        page_obj = cat_pages[self.current_page]
        items = page_obj.get("items", [])

        # Row 0 & Row 1: 현재 페이지의 기능 버튼 6개 (각 줄에 3개씩 깔끔하게 배치)
        for idx, item in enumerate(items[:6]):
            row_num = 0 if idx < 3 else 1
            req_perm = item.get("perm", PERM_USER)
            btn_label = item["label"]
            btn_emoji = item["emoji"]
            btn_style = item["style"]

            # 권한 시각적 구분: 권한이 부족한 항목은 🔒 아이콘과 회색 스타일로 명확히 표시 (클릭 시 친절한 권한 안내)
            if req_perm == PERM_OWNER and caller_tier != PERM_OWNER:
                btn_label = f"🔒 {btn_label}"
                btn_style = discord.ButtonStyle.secondary
            elif req_perm == PERM_ADMIN and caller_tier == PERM_USER:
                btn_label = f"🔒 {btn_label}"
                btn_style = discord.ButtonStyle.secondary

            b = discord.ui.Button(
                label=btn_label[:80],
                emoji=btn_emoji,
                style=btn_style,
                row=row_num,
                custom_id=f"norosi:Settings:act_{self.current_category}_{self.current_page}_{idx}",
            )
            b.callback = item["cb"]
            self.add_item(b)

        # Row 2: 4대 카테고리 빠른 전환 바 (일반 · 고급 · 미니게임 · 개인)
        for cat_key in CATEGORY_ORDER:
            c_meta = CATEGORY_INFO[cat_key]
            c_pages_cnt = len(self._pages_cache.get(cat_key, []))
            is_cur = (cat_key == self.current_category)
            c_btn = discord.ui.Button(
                label=f"{c_meta['label'].split(' ', 1)[-1]} {c_pages_cnt}p",
                emoji=c_meta["emoji"],
                style=discord.ButtonStyle.primary if is_cur else discord.ButtonStyle.secondary,
                row=2,
                custom_id=f"norosi:Settings:switch_{cat_key}",
            )
            c_btn.callback = self._make_cat_enter_cb(cat_key)
            self.add_item(c_btn)

        # Row 3: [⬅️ 뒤로] + 통합 페이지네이션 [◀] [📄 N/M · G/T] [▶] + [🔄 새로고침]
        back_btn = discord.ui.Button(
            label="뒤로",
            emoji="⬅️",
            style=discord.ButtonStyle.danger,
            row=3,
            custom_id=self._get_back_button_custom_id(),
        )
        back_btn.callback = self._on_back_clicked
        self.add_item(back_btn)

        prev_btn = discord.ui.Button(
            label="◀",
            style=discord.ButtonStyle.secondary,
            row=3,
            custom_id="norosi:Settings:nav_prev",
        )
        prev_btn.callback = self._on_prev_page_clicked
        self.add_item(prev_btn)

        global_cur, global_tot = self._get_global_page_info(self.current_category, self.current_page)
        ind_btn = discord.ui.Button(
            label=f"📄 {self.current_page + 1}/{len(cat_pages)} ({global_cur}/{global_tot})",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            row=3,
            custom_id="norosi:Settings:nav_ind",
        )
        self.add_item(ind_btn)

        next_btn = discord.ui.Button(
            label="▶",
            style=discord.ButtonStyle.secondary,
            row=3,
            custom_id="norosi:Settings:nav_next",
        )
        next_btn.callback = self._on_next_page_clicked
        self.add_item(next_btn)

        ref_btn = discord.ui.Button(
            label="새로고침",
            emoji="🔄",
            style=discord.ButtonStyle.primary,
            row=3,
            custom_id="norosi:Settings:nav_refresh",
        )
        ref_btn.callback = self._on_refresh_clicked
        self.add_item(ref_btn)

        # Row 4: 현재 카테고리 내 페이지 번호 직접 이동 버튼 (1p / 2p / 3p / 4p)
        short_labels = self._get_category_page_short_labels(self.current_category, len(cat_pages))
        core.sync_page_number_buttons(
            self,
            current_page=self.current_page,
            total_pages=len(cat_pages),
            row=4,
            on_select=self._on_page_num_selected,
            zero_indexed=True,
            max_buttons=5,
            active_style=discord.ButtonStyle.success,
            label_fn=lambda p_idx, is_act: f"● {short_labels[p_idx]}" if is_act else short_labels[p_idx],
            custom_id_prefix=f"norosi:Settings:catpage_{self.current_category}",
        )

    @staticmethod
    def _get_category_page_short_labels(cat_key: str, total_pages: int) -> List[str]:
        preset = {
            "general": ["1p 출석·일정", "2p 음악·플리", "3p 통계·소통"],
            "advanced": ["1p 역할·공지", "2p 티켓·음성", "3p 보안·청소", "4p 👑봇주인"],
            "minigame": ["1p 프세카", "2p 원신·스타", "3p 낚시·생활", "4p 게임·도감"],
            "personal": ["1p 프로필", "2p 보관함", "3p 목표·파트너", "4p 루틴·대전"],
        }.get(cat_key, [])
        return [preset[i] if i < len(preset) else f"{i + 1}p" for i in range(total_pages)]

    async def _on_page_num_selected(self, interaction: discord.Interaction, target_page: int):
        target_state = (self.current_category, target_page, None)
        if self._current_nav_state() != target_state:
            self._push_nav_history()
        self.current_page = target_page
        self.sub_mode = None
        self.refresh_components()
        await core.safe_edit_response(interaction, embed=self.build_current_embed(), view=self)

    def _make_cat_enter_cb(self, cat_key: str) -> Callable[[discord.Interaction], Awaitable[None]]:
        async def _cb(interaction: discord.Interaction):
            target_state = (cat_key, 0, None)
            if self._current_nav_state() != target_state:
                self._push_nav_history()
            self.current_category = cat_key
            self.current_page = 0
            self.sub_mode = None
            self.refresh_components()
            await core.safe_edit_response(interaction, embed=self.build_current_embed(), view=self)
        return _cb

    async def _on_back_clicked(self, interaction: discord.Interaction):
        if self._nav_history:
            prev_cat, prev_page, prev_sub = self._nav_history.pop()
            self.current_category = prev_cat
            self.current_page = prev_page
            self.sub_mode = prev_sub
        elif self.sub_mode is not None:
            p_cat, p_page = SUB_MODE_PARENT_MAP.get(
                self.sub_mode, (self.current_category, self.current_page)
            )
            self.current_category = p_cat
            self.current_page = p_page
            self.sub_mode = None
        else:
            self.current_category = "home"
            self.current_page = 0
        self.refresh_components()
        await core.safe_edit_response(interaction, embed=self.build_current_embed(), view=self)

    async def _on_home_clicked(self, interaction: discord.Interaction):
        self._nav_history.clear()
        self.sub_mode = None
        self.current_category = "home"
        self.current_page = 0
        self.refresh_components()
        await core.safe_edit_response(interaction, embed=self.build_current_embed(), view=self)

    async def _on_prev_page_clicked(self, interaction: discord.Interaction):
        prev_state = self._current_nav_state()
        self._step_global_page(-1)
        if self._current_nav_state() != prev_state:
            self._push_nav_history(prev_state)
        self.refresh_components()
        await core.safe_edit_response(interaction, embed=self.build_current_embed(), view=self)

    async def _on_next_page_clicked(self, interaction: discord.Interaction):
        prev_state = self._current_nav_state()
        self._step_global_page(1)
        if self._current_nav_state() != prev_state:
            self._push_nav_history(prev_state)
        self.refresh_components()
        await core.safe_edit_response(interaction, embed=self.build_current_embed(), view=self)

    async def _on_home_quick_jump_selected(self, interaction: discord.Interaction):
        val = (interaction.data.get("values") or [None])[0] if isinstance(interaction.data, dict) else None
        if not val:
            await core.safe_defer(interaction, ephemeral=True)
            return
        jump_map = {
            "feature_search": self._act_feature_search,
            "home_shortcuts": self._act_home_shortcuts,
            "achievements": self._act_achievements,
            "admin_dday": self._sub_dday_setup_board,
            "dday_past": self._sub_dday_past,
            "mood_radio": self._act_mood_radio,
            "guild_events": self._act_guild_events,
            "ranking_hub": self._act_ranking_hub,
            "att_rank": self._act_att_ranking,
            "sekai_rank": self._act_sekai_rank,
            "gi_rank": self._act_gi_rank,
            "hsr_rank": self._act_hsr_rank,
            "fish_rank": self._act_fishing_rank,
            "ol_rank": self._act_other_life_rank,
            "eco_rank": self._act_economy_rank,
            "pokedex_hub": self._act_pokedex_hub,
            "sekai_inv": self._act_sekai_inv,
            "sekai_mr": self._act_sekai_master_rank,
            "sekai_costume": self._act_sekai_wardrobe,
            "sekai_live": self._act_sekai_live,
            "music_pl": self._act_playlist_studio,
            "weather": self._act_weather,
            "wordchain": self._act_word_chain,
            "roulette": self._act_roulette,
            "sponsor": self._act_sponsor,
        }
        handler = jump_map.get(val)
        if handler:
            await handler(interaction)
        else:
            await core.safe_defer(interaction, ephemeral=True)

    async def _on_refresh_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            self.data = await asyncio.to_thread(core.load_data)
            self.refresh_components()
            await interaction.edit_original_response(embed=self.build_current_embed(), view=self)
        except Exception as e:
            await core.safe_send_response(interaction, f"⚠️ 새로고침 중 오류 발생: {e}", ephemeral=True)

    # ----------------------------------------------------
    # 🧩 3단계 세부 제어판(Sub-Mode) 버튼 구성
    # ----------------------------------------------------
    def _get_sub_mode_definition(self) -> Dict[str, Any]:
        defs: Dict[str, Dict[str, Any]] = {
            "sekai_schedule": {
                "title": "🔭 프로세카 미래시 & 실시간 이벤트 제어판",
                "desc": "한국 서버(KR) 다가오는 이벤트 미래시 달력과 한섭/일섭 실시간 이벤트·배너를 확인합니다.",
                "perm": PERM_USER,
                "buttons": [
                    ("한섭 미래시 캘린더", "📅", discord.ButtonStyle.primary, self._sub_sekai_forecast_cal),
                    ("한섭(KR) 실시간 이벤트", "🇰🇷", discord.ButtonStyle.success, self._sub_sekai_live_kr),
                    ("일섭(JP) 실시간 이벤트", "🇯🇵", discord.ButtonStyle.secondary, self._sub_sekai_live_jp),
                ],
            },
            "music_voice": {
                "title": "⏩ 음성채널 재생 배속 · 헤드셋 · 내 임시음성방 리모컨",
                "desc": "현재 음성채널 플레이리스트의 배속(0.75x ~ 2.0x), 봇 헤드셋 상태, 그리고 내가 방장인 임시음성방을 제어합니다.",
                "perm": PERM_USER,
                "buttons": [
                    ("0.75x 감성 배속", "🐢", discord.ButtonStyle.secondary, self._make_speed_cb(0.75)),
                    ("1.0x 표준 배속", "▶️", discord.ButtonStyle.primary, self._make_speed_cb(1.0)),
                    ("1.25x 경쾌 배속", "⚡", discord.ButtonStyle.success, self._make_speed_cb(1.25)),
                    ("1.5x 나이트코어", "🚀", discord.ButtonStyle.secondary, self._make_speed_cb(1.5)),
                    ("2.0x 초고속 배속", "🔥", discord.ButtonStyle.secondary, self._make_speed_cb(2.0)),
                    ("봇 헤드셋 토글", "🎧", discord.ButtonStyle.secondary, self._act_music_headset_toggle),
                    ("440Hz 오디오 진단", "🔊", discord.ButtonStyle.secondary, self._act_audio_test),
                    ("내 임시음성방 리모컨", "🎛️", discord.ButtonStyle.primary, self._act_my_temp_voice_remote),
                ],
            },
            "relay_novel": {
                "title": "✍️ 채널 협동 릴레이 소설 제어판",
                "desc": "현재 채널에서 멤버들과 한 줄씩 번갈아 이어 쓰는 릴레이 소설을 시작하거나 명작집을 열람합니다.",
                "perm": PERM_USER,
                "buttons": [
                    ("새 릴레이소설 시작", "🆕", discord.ButtonStyle.success, self._sub_relay_start),
                    ("현재 채널 소설 현황/이어쓰기", "📖", discord.ButtonStyle.primary, self._sub_relay_status),
                    ("완결 릴레이소설 명작집", "📚", discord.ButtonStyle.secondary, self._sub_relay_archive),
                    ("진행 중 소설 중단", "🛑", discord.ButtonStyle.danger, self._sub_relay_cancel),
                ],
            },
            "admin_ticket": {
                "title": "🎫 [서버 관리자] 1:1 비공개 문의 티켓 제어판",
                "desc": "서버의 1:1 문의 티켓 패널을 생성하거나 담당자 역할·카테고리·로그채널·방식을 설정하고 티켓 멤버를 관리합니다.",
                "perm": PERM_ADMIN,
                "buttons": [
                    ("현재 채널에 티켓패널 생성", "📌", discord.ButtonStyle.success, self._sub_ticket_create_panel),
                    ("커스텀 제목/설명 패널 생성", "✏️", discord.ButtonStyle.primary, self._sub_ticket_custom_panel),
                    ("담당자·채널·방식 통합 설정", "⚙️", discord.ButtonStyle.primary, self._sub_ticket_role_config),
                    ("서버 티켓 전체 목록", "📋", discord.ButtonStyle.secondary, self._act_admin_ticket_list),
                    ("현재 티켓 멤버 추가/제거", "👥", discord.ButtonStyle.secondary, self._sub_ticket_member_modal),
                    ("현재 티켓 채널 닫기", "🔒", discord.ButtonStyle.danger, self._sub_ticket_close_current),
                ],
            },
            "admin_sticky": {
                "title": "📌 [서버 관리자] 채널 자동 고정메시지(Sticky) 제어판",
                "desc": "대화가 올라와도 채널 맨 아래에 항상 유지되는 공지/안내 고정 메시지를 설정·일시중지·해제합니다.",
                "perm": PERM_ADMIN,
                "buttons": [
                    ("고정메시지 상세 설정 패널", "⚙️", discord.ButtonStyle.success, self._sub_sticky_detail_panel),
                    ("현재 채널 제목·본문 빠른작성", "✏️", discord.ButtonStyle.primary, self._sub_sticky_set),
                    ("현재 채널 켜기/일시중지 토글", "🔄", discord.ButtonStyle.secondary, self._sub_sticky_toggle),
                    ("서버 고정메시지 목록", "📋", discord.ButtonStyle.secondary, self._sub_sticky_list),
                    ("현재 채널 고정메시지 해제", "🗑️", discord.ButtonStyle.danger, self._sub_sticky_remove),
                ],
            },
            "admin_dday": {
                "title": "📅 [서버 관리자] 서버 공식 D-Day & 전광판 관리",
                "desc": "서버 D-Day 일정을 등록/삭제하고 전광판 음성채널, 기본 카테고리, 오전 9시 알림 채널을 설정합니다.",
                "perm": PERM_ADMIN,
                "buttons": [
                    ("채널·카테고리·알림 설정", "📺", discord.ButtonStyle.success, self._sub_dday_setup_board),
                    ("새 D-Day & 전광판 등록", "➕", discord.ButtonStyle.primary, self._act_add_dday_modal),
                    ("D-Day 전광판 & 삭제", "📋", discord.ButtonStyle.primary, self._act_dday_list),
                    ("지나간 D-Day 보관소", "🕰️", discord.ButtonStyle.secondary, self._sub_dday_past),
                    ("현재 채널 9시 알림 지정", "🔔", discord.ButtonStyle.secondary, self._sub_dday_set_alert_ch),
                    ("현재 카테고리 기본지정", "📁", discord.ButtonStyle.secondary, self._sub_dday_set_default_cat),
                ],
            },
            "admin_music_sched": {
                "title": "🌅 [서버 관리자] 모닝 음악추천 & 맞춤 시간 음악알람",
                "desc": "오전 7시 정기 음악 추천 채널·장르·아티스트·플리링크를 지정하거나 맞춤 시각(HH:MM) 음악 알람을 관리합니다.",
                "perm": PERM_ADMIN,
                "buttons": [
                    ("현재 채널을 7시 모닝추천 지정", "🌅", discord.ButtonStyle.success, self._sub_music_set_morning_ch),
                    ("모닝음악 장르·아티스트·플리 설정", "🎛️", discord.ButtonStyle.primary, self._sub_music_prefs_modal),
                    ("맞춤 시각 음악알람 스케줄러", "⏰", discord.ButtonStyle.primary, self._sub_music_custom_sched),
                ],
            },
            "admin_reset": {
                "title": "⚠️ [서버 관리자] 서버 데이터 초기화 안전 제어판",
                "desc": "선택한 게임/시스템의 현재 서버 데이터를 초기화합니다. (클릭 시 2차 확인창이 표시됩니다)",
                "perm": PERM_ADMIN,
                "buttons": [
                    ("D-Day & 음악설정 초기화", "📅", discord.ButtonStyle.danger, self._sub_reset_dday),
                    ("프로세카 서버 보관함 초기화", "🎤", discord.ButtonStyle.danger, self._sub_reset_sekai),
                    ("원신 서버 보관함 초기화", "🌠", discord.ButtonStyle.danger, self._sub_reset_genshin),
                    ("스타레일 서버 보관함 초기화", "🚄", discord.ButtonStyle.danger, self._sub_reset_hsr),
                ],
            },
            "owner_sekai_pickup": {
                "title": "🎯 [봇 주인 전용] 프로세카 글로벌 픽업 & 셀렉트 티켓 제어판",
                "desc": "프로세카 한섭 실시간 이벤트 자동 연동, 페스/생일 전환, 수동 픽업 및 유저별 셀렉트 리스트 특수 티켓을 지급·관리합니다.",
                "perm": PERM_OWNER,
                "buttons": [
                    ("한섭 실시간 이벤트 자동맞춤", "🎯", discord.ButtonStyle.success, self._sub_owner_sekai_auto),
                    ("컬러풀 페스 (★4 6% 2배)", "🎊", discord.ButtonStyle.primary, self._sub_owner_sekai_fes),
                    ("생일 기념 배너 전환", "🎂", discord.ButtonStyle.primary, self._sub_owner_sekai_bday),
                    ("셀렉트 티켓 지급·관리", "🎟️", discord.ButtonStyle.success, self._sub_owner_sekai_select_tickets),
                    ("수동 유닛·캐릭터·한정 설정", "🎛️", discord.ButtonStyle.secondary, self._sub_owner_sekai_custom_modal),
                    ("기본 상시 픽업으로 초기화", "🔄", discord.ButtonStyle.secondary, self._sub_owner_sekai_reset),
                    ("현재 배너 확률표 확인", "📊", discord.ButtonStyle.secondary, self._sub_sekai_rates),
                ],
            },
            "owner_gi_pickup": {
                "title": "🌠 [봇 주인 전용] 원신 기원 글로벌 픽업 제어판",
                "desc": "원신 이벤트 기원 배너를 KST 2시간 주기 자동 로테이션이나 프리셋/수동 5성·4성·무기·성유물로 설정합니다.",
                "perm": PERM_OWNER,
                "buttons": [
                    ("KST 2시간 자동 로테이션 적용", "⏰", discord.ButtonStyle.success, self._sub_owner_gi_auto),
                    ("수동 5성·4성·무기·성유물 설정", "🎛️", discord.ButtonStyle.primary, self._sub_owner_gi_custom_modal),
                    ("원신 기본 픽업 초기화", "🔄", discord.ButtonStyle.secondary, self._sub_owner_gi_reset),
                    ("현재 원신 확률 & 픽업 확인", "📊", discord.ButtonStyle.secondary, self._sub_gi_rates),
                ],
            },
            "owner_hsr_pickup": {
                "title": "🚄 [봇 주인 전용] 스타레일 워프 글로벌 픽업 제어판",
                "desc": "붕괴: 스타레일 이벤트 워프 배너를 KST 2시간 주기 자동 로테이션이나 프리셋/수동 5성·4성·광추·유물로 설정합니다.",
                "perm": PERM_OWNER,
                "buttons": [
                    ("KST 2시간 자동 로테이션 적용", "⏰", discord.ButtonStyle.success, self._sub_owner_hsr_auto),
                    ("수동 5성·4성·광추·유물 설정", "🎛️", discord.ButtonStyle.primary, self._sub_owner_hsr_custom_modal),
                    ("스타레일 기본 픽업 초기화", "🔄", discord.ButtonStyle.secondary, self._sub_owner_hsr_reset),
                    ("현재 스타레일 확률 & 픽업 확인", "📊", discord.ButtonStyle.secondary, self._sub_hsr_rates),
                ],
            },
            "owner_terminal": {
                "title": "🖥️ [봇 주인 전용] VM 터미널 로그 & GitHub 배포 알림 제어판",
                "desc": "VM 서버의 실시간 터미널 출력(stdout/stderr)을 상세 버전 또는 요약 버전으로 중계하고, GitHub 배포 알림 채널을 연동·해제합니다.",
                "perm": PERM_OWNER,
                "buttons": [
                    ("터미널로그 연동 · 상세 버전", "📋", discord.ButtonStyle.success, self._sub_owner_term_bind_detailed),
                    ("터미널로그 연동 · 요약 버전", "⚡", discord.ButtonStyle.primary, self._sub_owner_term_bind_summary),
                    ("현재 서버 터미널로그 해제", "🛑", discord.ButtonStyle.danger, self._sub_owner_term_unbind),
                    ("현재 채널 GitHub 배포알림 연동", "🐙", discord.ButtonStyle.primary, self._act_admin_github_webhook),
                    ("현재 서버 GitHub 배포알림 해제", "🚫", discord.ButtonStyle.secondary, self._sub_owner_github_unbind),
                ],
            },
            "owner_backup_sync": {
                "title": "💾 [봇 주인 전용] 서버/DB 백업 · 슬래시 동기화 · 봇 배너",
                "desc": "현재 서버 구조 또는 봇 전체 DB를 JSON으로 백업하고 슬래시 명령어 동기화 및 봇 프로필 배너를 제어합니다.",
                "perm": PERM_OWNER,
                "buttons": [
                    ("현재 서버 구조 JSON 백업", "🏢", discord.ButtonStyle.primary, self._sub_owner_backup_guild),
                    ("봇 전체 DB JSON 백업", "🗄️", discord.ButtonStyle.success, self._sub_owner_backup_db),
                    ("슬래시 명령어 즉시 동기화 패널", "⚡", discord.ButtonStyle.secondary, self._sub_owner_sync_panel),
                    ("봇 프로필 배너 변경/초기화", "🖼️", discord.ButtonStyle.secondary, self._sub_owner_bot_banner),
                ],
            },
            "pokedex_hub": {
                "title": "📖 5대 게임 통합 도감 & 배너 확률표 허브",
                "desc": "프로세카 · 원신 · 스타레일 · 통합 낚시 · 타인의 삶 도감 수집률과 배너 확률표를 열람합니다.",
                "perm": PERM_USER,
                "buttons": [
                    ("프로세카 카드도감", "🎤", discord.ButtonStyle.primary, self._act_sekai_pokedex),
                    ("원신 티바트 도감", "🌠", discord.ButtonStyle.primary, self._act_gi_pokedex),
                    ("스타레일 은하 아카이브", "🚄", discord.ButtonStyle.primary, self._act_hsr_pokedex),
                    ("낚시 36,700종 어류도감", "🎣", discord.ButtonStyle.success, self._act_fishing_pokedex),
                    ("타인의 삶 1,000엔딩 도감", "📜", discord.ButtonStyle.secondary, self._act_other_life_codex),
                    ("프로세카 배너 확률표", "📊", discord.ButtonStyle.secondary, self._sub_sekai_rates),
                    ("원신 기원 확률표", "📊", discord.ButtonStyle.secondary, self._sub_gi_rates),
                    ("스타레일 워프 확률표", "📊", discord.ButtonStyle.secondary, self._sub_hsr_rates),
                ],
            },
            "ranking_hub": {
                "title": "🏆 전 분야 서버 통합 랭킹 허브 (8대 순위표)",
                "desc": "출석체크 · 프로세카 · 원신 · 스타레일 · 낚시 대물 · 주말 낚시대회 · 타인의 삶 · 통합 순자산 순위표를 즉시 확인합니다.",
                "perm": PERM_USER,
                "buttons": [
                    ("출석체크 랭킹 Top 10", "📅", discord.ButtonStyle.success, self._act_att_ranking),
                    ("프로세카 가챠랭킹", "🎤", discord.ButtonStyle.primary, self._act_sekai_rank),
                    ("원신 수집·명예의전당", "🌠", discord.ButtonStyle.primary, self._act_gi_rank),
                    ("스타레일 워프랭킹", "🚄", discord.ButtonStyle.primary, self._act_hsr_rank),
                    ("낚시 최대어(cm·kg) 랭킹", "🎣", discord.ButtonStyle.success, self._act_fishing_rank),
                    ("주말·제철 낚시대회 순위", "🏅", discord.ButtonStyle.success, self._act_fishing_tourney),
                    ("타인의 삶 엔딩랭킹", "👶", discord.ButtonStyle.secondary, self._act_other_life_rank),
                    ("통합 순자산·크리스탈 랭킹", "🏦", discord.ButtonStyle.secondary, self._act_economy_rank),
                ],
            },
            "sekai_pull_hub": {
                "title": "🔮 프로세카 가챠 등록 · 뽑기 · 천장 교환 · 셀렉트 리스트 · 캐랭 허브",
                "desc": "사전 등록(★1 26종 기본 지급) · 10연차/단차(기본 특훈 전 표시 & 특훈 전·후 버튼 전환) · 200배지 천장교환 · 셀렉트 리스트 · 캐랭 깃발 · 운명 · 연습 · 생일 무료단차를 실행합니다.",
                "perm": PERM_USER,
                "buttons": [
                    ("프로세카 가챠 등록 (★1 지급)", "📝", discord.ButtonStyle.success, self._act_sekai_register),
                    ("프로세카 10회 연속뽑기", "🌈", discord.ButtonStyle.success, self._act_sekai_pull_10),
                    ("프로세카 1회 단차뽑기", "🎵", discord.ButtonStyle.primary, self._act_sekai_pull_1),
                    ("200배지 천장 교환소", "🏅", discord.ButtonStyle.success, self._sub_sekai_ceiling_exchange),
                    ("셀렉트 리스트 가챠 (티켓)", "🎟️", discord.ButtonStyle.primary, self._sub_sekai_select_list),
                    ("캐릭터 랭크 & 칭호 깃발", "🚩", discord.ButtonStyle.primary, self._act_sekai_char_rank),
                    ("일일 운명 다시뽑기 (3세트 택1)", "🔮", discord.ButtonStyle.primary, self._sub_sekai_destiny_reroll),
                    ("리세마라 연습 시뮬레이터", "🧪", discord.ButtonStyle.secondary, self._sub_sekai_reroll_sim),
                    ("오늘의 생일 무료 단차", "🎂", discord.ButtonStyle.secondary, self._sub_sekai_bday_free),
                    ("현재 배너 상세 확률표", "📊", discord.ButtonStyle.secondary, self._sub_sekai_rates),
                ],
            },
            "gi_banner_hub": {
                "title": "🌠 원신 배너별 기원 · 운명의 궤도 · 리세마라 연습 허브",
                "desc": "캐릭터 이벤트 기원 ①/②, 신의 주조(무기), 성유물 기원, 상시 기원 및 무료 리세마라 연습 기원을 실행합니다.",
                "perm": PERM_USER,
                "buttons": [
                    ("캐릭터 기원 ① (10연차)", "🌠", discord.ButtonStyle.primary, self._make_gi_pull_cb("char1", 10, False)),
                    ("캐릭터 기원 ② (10연차)", "✨", discord.ButtonStyle.primary, self._make_gi_pull_cb("char2", 10, False)),
                    ("신의 주조 무기 (10연차)", "⚔️", discord.ButtonStyle.success, self._make_gi_pull_cb("weapon", 10, False)),
                    ("비경 성유물 기원 (10연차)", "👑", discord.ButtonStyle.secondary, self._make_gi_pull_cb("artifact", 10, False)),
                    ("상시 세상 여행 (10연차)", "🌍", discord.ButtonStyle.secondary, self._make_gi_pull_cb("standard", 10, False)),
                    ("캐릭터 기원 ① (1회 단차)", "💫", discord.ButtonStyle.secondary, self._make_gi_pull_cb("char1", 1, False)),
                    ("리세마라 연습모드 (10연 무료)", "🧪", discord.ButtonStyle.secondary, self._make_gi_pull_cb("char1", 10, True)),
                    ("운명의 궤도 (무기 정가 지정)", "🧭", discord.ButtonStyle.primary, self._act_gi_fate),
                ],
            },
            "hsr_banner_hub": {
                "title": "🚄 스타레일 배너별 워프 · 상시 300 선택 · 연습 허브",
                "desc": "캐릭터 이벤트 워프 ①/②, 세월의 응고(광추), 터널 유물 워프, 상시 워프 및 무료 리세마라 연습 워프를 실행합니다.",
                "perm": PERM_USER,
                "buttons": [
                    ("캐릭터 워프 ① (10연차)", "🚆", discord.ButtonStyle.primary, self._make_hsr_warp_cb("char1", 10, False)),
                    ("캐릭터 워프 ② (10연차)", "🌠", discord.ButtonStyle.primary, self._make_hsr_warp_cb("char2", 10, False)),
                    ("세월의 응고 광추 (10연차)", "⚔️", discord.ButtonStyle.success, self._make_hsr_warp_cb("lightcone", 10, False)),
                    ("터널 유물 워프 (10연차)", "👑", discord.ButtonStyle.secondary, self._make_hsr_warp_cb("relic", 10, False)),
                    ("상시 별무리 워프 (10연차)", "🌌", discord.ButtonStyle.secondary, self._make_hsr_warp_cb("standard", 10, False)),
                    ("캐릭터 워프 ① (1회 단차)", "🎫", discord.ButtonStyle.secondary, self._make_hsr_warp_cb("char1", 1, False)),
                    ("리세마라 연습모드 (10연 무료)", "🧪", discord.ButtonStyle.secondary, self._make_hsr_warp_cb("char1", 10, True)),
                    ("상시 300회 5성 선택권", "🎁", discord.ButtonStyle.primary, self._act_hsr_300),
                ],
            },
            "life_personal_hub": {
                "title": "🌿 농장 · 공동농장 · 펫 육성 · 생선 요리 · 통합 버프 허브",
                "desc": "개인 농장 파종/수확, 서버 공동농장 협동 물주기, 6종 펫 입양/교감, 생선 요리 제작 및 활성 버프를 관리합니다.",
                "perm": PERM_USER,
                "buttons": [
                    ("생활 통합 대시보드", "🌿", discord.ButtonStyle.success, self._act_life_dashboard),
                    ("개인 농장 (파종·물주기·수확)", "🌾", discord.ButtonStyle.primary, self._act_life_farm),
                    ("서버 공동농장 (협동 농사)", "🏡", discord.ButtonStyle.primary, self._sub_life_coop_farm),
                    ("펫 입양 & 돌보기 (6종)", "🐾", discord.ButtonStyle.secondary, self._sub_life_pet),
                    ("생선 요리 & 요리도감", "🍳", discord.ButtonStyle.secondary, self._sub_life_cook),
                    ("내 활성 통합 버프 확인", "✨", discord.ButtonStyle.secondary, self._sub_life_buffs),
                    ("오늘의 일일 루틴 허브", "☀️", discord.ButtonStyle.success, self._act_daily_routine),
                ],
            },
            "sekai_deck": {
                "title": "🎴 프로세카 5인 유닛 덱 & 카드 강화 · 캐랭 깃발 · 교환 · 선물",
                "desc": "내 5인 덱 구성을 확인·편성(자동/직접)하고 보유 카드를 검색·강화·마스터랭크·캐랭 깃발 관리하거나 1:1 교환·선물합니다.",
                "perm": PERM_USER,
                "buttons": [
                    ("내 5인 덱 현황 & 편성", "🎴", discord.ButtonStyle.primary, self._sub_sekai_deck_view),
                    ("보유 카드 레벨업 강화", "🔨", discord.ButtonStyle.success, self._sub_sekai_card_enhance),
                    ("마스터 랭크(✦MR) 돌파", "🏆", discord.ButtonStyle.secondary, self._act_sekai_master_rank),
                    ("캐릭터 랭크 & 칭호 깃발", "🚩", discord.ButtonStyle.primary, self._act_sekai_char_rank),
                    ("중복 카드 크리스탈 환전", "💎", discord.ButtonStyle.secondary, self._act_sekai_dup_convert),
                    ("1:1 카드 교환 장터 (100💎)", "🔄", discord.ButtonStyle.primary, self._sub_sekai_card_trade),
                    ("파트너 카드 선물 (50💎)", "🎁", discord.ButtonStyle.secondary, self._sub_sekai_card_gift),
                    ("내 보유 카드 키워드 검색", "🔍", discord.ButtonStyle.secondary, self._sub_sekai_card_search),
                    ("특수 뽑기·천장·셀렉트", "🔮", discord.ButtonStyle.secondary, self._act_sekai_pull_hub),
                ],
            },
            "gi_personal": {
                "title": "🌠 원신 개인 보관함 · 4인 파티 · 여행자 프로필",
                "desc": "보유한 원신 캐릭터(운명의 자리)·무기(재련)·성유물을 관리하고 4인 파티와 여행자 프로필을 설정합니다.",
                "perm": PERM_USER,
                "buttons": [
                    ("원신 보관함 (육성·잠금)", "🎒", discord.ButtonStyle.primary, self._act_gi_inv),
                    ("원신 4인 파티 편성", "⚔️", discord.ButtonStyle.success, self._act_gi_party),
                    ("원신 여행자 프로필 조회", "🪪", discord.ButtonStyle.primary, self._sub_gi_profile),
                    ("여행자 프로필 설정 (대표캐/문구)", "✏️", discord.ButtonStyle.secondary, self._sub_gi_profile_edit),
                    ("원신 운명의 궤도", "🧭", discord.ButtonStyle.secondary, self._act_gi_fate),
                    ("원신 페이몬 상점", "🧚", discord.ButtonStyle.secondary, self._act_gi_shop),
                    ("배너별 기원 & 연습모드", "🌠", discord.ButtonStyle.secondary, self._act_gi_banner_hub),
                ],
            },
            "hsr_personal": {
                "title": "🚄 스타레일 개인 보관함 · 4인 편대 · 개척자 프로필",
                "desc": "보유한 스타레일 캐릭터(성혼)·광추(중첩)·유물을 관리하고 4인 개척 편대와 개척자 프로필을 설정합니다.",
                "perm": PERM_USER,
                "buttons": [
                    ("스타레일 보관함 (육성·잠금)", "🎒", discord.ButtonStyle.primary, self._act_hsr_inv),
                    ("스타레일 4인 개척 편대", "🚄", discord.ButtonStyle.success, self._act_hsr_party),
                    ("스타레일 개척자 프로필 조회", "🪪", discord.ButtonStyle.primary, self._sub_hsr_profile),
                    ("개척자 프로필 설정 (대표캐/문구)", "✏️", discord.ButtonStyle.secondary, self._sub_hsr_profile_edit),
                    ("상시 300회 5성 선택", "🎁", discord.ButtonStyle.secondary, self._act_hsr_300),
                    ("스타레일 별빛·헤르타 상점", "🛍️", discord.ButtonStyle.secondary, self._act_hsr_shop),
                    ("배너별 워프 & 연습모드", "🚆", discord.ButtonStyle.secondary, self._act_hsr_banner_hub),
                ],
            },
            "fishing_personal": {
                "title": "👜 낚시 가방 · 어시장 시세 · 협동 레이드 · 강화 공방 · 수족관",
                "desc": "잡은 물고기 스마트 정리/판매, 실시간 어시장 시세, 서버 협동 보스 레이드, 장비 강화/미끼 제작 공방, PNG 수족관을 한 번에 엽니다.",
                "perm": PERM_USER,
                "buttons": [
                    ("내 물고기 가방 (스마트정리·선물)", "👜", discord.ButtonStyle.primary, self._sub_fishing_bag),
                    ("실시간 어시장 시세 & 특가", "📈", discord.ButtonStyle.success, self._sub_fishing_market),
                    ("서버 협동 대어 보스 레이드", "🐙", discord.ButtonStyle.danger, self._sub_fishing_raid),
                    ("장비 강화·미끼 제작 공방", "🔨", discord.ButtonStyle.primary, self._sub_fishing_workshop),
                    ("내 프라이빗 수족관 (PNG·먹이)", "🐠", discord.ButtonStyle.secondary, self._act_fishing_aquarium),
                    ("일일 낚시 퀘스트 (3종)", "📜", discord.ButtonStyle.success, self._sub_fishing_quest),
                    ("내 낚시꾼 라이선스 프로필", "🪪", discord.ButtonStyle.secondary, self._sub_fishing_profile),
                    ("실시간 낚시 기상 & 조황 예보", "🌤️", discord.ButtonStyle.secondary, self._sub_fishing_env),
                    ("낚시 장비·미끼 상점", "🛒", discord.ButtonStyle.secondary, self._act_fishing_shop),
                ],
            },
            "bday_partner": {
                "title": "🎂 내 생일 등록 & 💑 파트너 스튜디오",
                "desc": "내 생일을 등록해 당일 자정 축하와 +500💎 보너스를 받고, 파트너 신청/해제 및 공동 D-Day·공유 음악·농장 물주기를 관리합니다.",
                "perm": PERM_USER,
                "buttons": [
                    ("생일 전광판 & 내 생일 등록", "🎂", discord.ButtonStyle.success, self._act_birthday_board),
                    ("내 파트너 스튜디오 열기", "💑", discord.ButtonStyle.primary, self._act_partner_studio),
                    ("파트너 농장 대신 물주기", "💧", discord.ButtonStyle.success, self._act_partner_farm_water),
                    ("파트너(짝꿍) 신청하기", "💌", discord.ButtonStyle.primary, self._sub_partner_propose),
                    ("파트너 관계 해제하기", "💔", discord.ButtonStyle.danger, self._sub_partner_break),
                    ("나만의 비밀 D-Day 보드", "🔒", discord.ButtonStyle.secondary, self._act_secret_dday),
                ],
            },
        }
        return defs.get(self.sub_mode or "", defs["pokedex_hub"])

    def _build_sub_mode_components(self, caller_tier: str):
        sub_def = self._get_sub_mode_definition()
        req_perm = sub_def.get("perm", PERM_USER)
        buttons = sub_def.get("buttons", [])

        capped_buttons = buttons[:12]
        per_row = 3 if len(capped_buttons) <= 6 else 4
        for idx, (b_label, b_emoji, b_style, b_cb) in enumerate(capped_buttons):
            row_num = idx // per_row
            eff_label = b_label
            eff_style = b_style
            if req_perm == PERM_OWNER and caller_tier != PERM_OWNER:
                eff_label = f"🔒 {b_label}"
                eff_style = discord.ButtonStyle.secondary
            elif req_perm == PERM_ADMIN and caller_tier == PERM_USER:
                eff_label = f"🔒 {b_label}"
                eff_style = discord.ButtonStyle.secondary

            btn = discord.ui.Button(
                label=eff_label[:80],
                emoji=b_emoji,
                style=eff_style,
                row=row_num,
                custom_id=f"norosi:Settings:sub_{self.sub_mode}_{idx}",
            )
            btn.callback = b_cb
            self.add_item(btn)

        nav_row = min(4, ((len(capped_buttons) - 1) // per_row + 1) if capped_buttons else 1)
        # Nav Row: [⬅️ 뒤로가기] [🏠 설정 홈으로] [🔄 새로고침]
        back_btn = discord.ui.Button(
            label="뒤로가기",
            emoji="⬅️",
            style=discord.ButtonStyle.danger,
            row=nav_row,
            custom_id=self._get_back_button_custom_id(),
        )
        back_btn.callback = self._on_back_clicked
        self.add_item(back_btn)

        home_btn = discord.ui.Button(
            label="설정 홈으로",
            emoji="🏠",
            style=discord.ButtonStyle.secondary,
            row=nav_row,
            custom_id="norosi:Settings:nav_home",
        )
        home_btn.callback = self._on_home_clicked
        self.add_item(home_btn)

        ref_btn = discord.ui.Button(
            label="새로고침",
            emoji="🔄",
            style=discord.ButtonStyle.primary,
            row=nav_row,
            custom_id="norosi:Settings:nav_refresh",
        )
        ref_btn.callback = self._on_refresh_clicked
        self.add_item(ref_btn)

    # ----------------------------------------------------
    # 🎨 임베드 빌더 (Component V2 컨테이너 스타일)
    # ----------------------------------------------------
    def build_embed(self) -> discord.Embed:
        """QuickMenuHubView 등 외부 호출자와의 100% 호환용 별칭"""
        return self.build_current_embed()

    def build_current_embed(self) -> discord.Embed:
        if not self.data:
            self.data = core.get_cached_data()

        if self.sub_mode is not None:
            return self._build_sub_mode_embed()
        if self.current_category == "home":
            return self._build_home_embed()
        return self._build_category_page_embed(self.current_category, self.current_page)

    def _format_caller_tier_banner(self) -> str:
        tier = detect_user_perm_tier_sync(self.user, self.guild)
        if tier == PERM_OWNER:
            return "👑 **내 권한 등급: `봇 주인 (Bot Owner)`** — `일반` · `미니게임` · `개인` · `고급(서버관리자 + 봇주인 시스템)` 전체 제어 가능"
        if tier == PERM_ADMIN:
            return "🛡️ **내 권한 등급: `서버 관리자 (Server Admin)`** — `일반` · `미니게임` · `개인` + `고급(서버 관리 1~3p)` 제어 가능 (`봇주인 전용` 제외)"
        return "👤 **내 권한 등급: `일반 이용자 (Member)`** — `일반` · `미니게임` · `개인` 전체 이용 가능 (`고급` 카테고리는 관리자/봇주인 전용)"

    def _build_home_embed(self) -> discord.Embed:
        u_key = str(self.user.id if self.user else 0)
        g_key = str(self.guild.id if self.guild else 0)
        u_name = self.user.display_name if self.user else "노로시 유저"

        profile = core.ensure_user_profile(self.data, u_key, u_name)
        crystals = int(profile.get("crystals", 0))
        oshi = profile.get("oshi") or "미설정"
        today_str = core.get_today_str()

        guild_att = core.safe_get_dict(self.data, "guild_attendance", g_key, u_key) if self.guild else core.as_dict(profile.get("attendance"))
        is_attended = (guild_att.get("last_date") == today_str)

        sekai_cards = len(core.safe_get_dict(self.data, "gacha_users", g_key, u_key, "cards"))
        gi_items = len(core.as_dict(core.safe_get_dict(self.data, "genshin_users", g_key, u_key).get("items")))
        hsr_items = len(core.as_dict(core.safe_get_dict(self.data, "hsr_users", g_key, u_key).get("items")))
        dday_cnt = len(core.filter_guild_ddays(self.data.get("ddays"), self.guild))

        flat_total = len(self._get_flat_pages())

        shortcut_keys = core.get_user_home_shortcuts(self.data, u_key, valid_keys=HOME_SHORTCUT_KEYS)
        sc_badge = (
            "숨김"
            if not shortcut_keys
            else ("기본 프리셋" if shortcut_keys == core.DEFAULT_HOME_SHORTCUTS else f"커스텀 {len(shortcut_keys)}종")
        )

        tier = detect_user_perm_tier_sync(self.user, self.guild)
        tier_short = PERM_BADGES.get(tier, "👤 일반 이용자")
        att_short = f"✅ 출석 (`{guild_att.get('streak', 0)}일`)" if is_attended else "⏳ 미출석"

        desc_lines = [
            f"👋 **{u_name}**님  ·  {tier_short}",
            f"💎 `{crystals:,}`  ·  💖 `{oshi}`  ·  📅 D-Day `{dday_cnt}개`  ·  {att_short}",
            f"🎮 수집: 프세카 `{sekai_cards}` · 원신 `{gi_items}` · 스타레일 `{hsr_items}`  ·  ⭐ 단축바 `{sc_badge}`",
            "",
            "💡 **빠른 찾기:** 아래 드롭다운 맨 위 **`🔍 통합 기능 검색`** 으로 키워드 점프!",
        ]

        embed = discord.Embed(
            title="⚙️ norosi 통합 설정 허브",
            description="\n".join(desc_lines),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.add_field(
            name="🌐 일반 (3p)",
            value="출석 · D-Day · 생일 · 플레이리스트 · 무드라디오 · 서버통계 · 파티 · 예약이벤트 · 날씨",
            inline=False,
        )
        embed.add_field(
            name="⚙️ 고급 (4p · 관리자/봇주)",
            value="역할 · 공지 · 티켓 · 임시음성방 · **D-Day 채널·알림 설정** · 음악알람 · 보안 · 로그 · 픽업/진단/백업",
            inline=False,
        )
        embed.add_field(
            name="🎮 미니게임 (4p)",
            value="프로세카 · 원신 · 스타레일 · 낚시(3.6만종) · 농장 · 펫 · 요리 · 타인의삶 · 끝말잇기 · 룰렛",
            inline=False,
        )
        embed.add_field(
            name="👤 개인 (4p)",
            value="PNG 프로필카드 · 칭호 · 송금 · 4대 보관함/덱 · 오늘목표 · 파트너 · 일일루틴 · 주간미션 · 업적 · 환전",
            inline=False,
        )
        if self.user and hasattr(self.user, "display_avatar"):
            embed.set_thumbnail(url=self.user.display_avatar.url)
        embed.set_footer(
            text=f"상단 4개 버튼으로 카테고리 이동  ·  ◀/▶ 전체 {flat_total}p 탐색"
        )
        return embed

    def _build_context_summary_for_page(self, category: str, page: int) -> str:
        """현재 열람 중인 카테고리·페이지에 맞는 실시간 상태 요약 블록 생성"""
        u_key = str(self.user.id if self.user else 0)
        g_key = str(self.guild.id if self.guild else 0)
        u_name = self.user.display_name if self.user else "유저"
        profile = core.ensure_user_profile(self.data, u_key, u_name)

        if category == "general":
            if page == 0:
                dday_cnt = len(core.filter_guild_ddays(self.data.get("ddays"), self.guild))
                bday_cnt = len(core.as_dict(self.data.get("birthdays")))
                return f"📌 이 서버 D-Day `{dday_cnt}개` · 생일 등록 `{bday_cnt}명`"
            if page == 1:
                pls = core.ensure_user_playlists(profile, u_name)
                vc_txt = "🎶 음성 연결됨" if getattr(self.guild, "voice_client", None) else "⏸️ 음성 대기 중"
                return f"🎵 내 플리 `{len(pls)}개` · 애청곡 `{len(profile.get('liked_music', []))}곡` · {vc_txt}"
            g_cnt = getattr(self.guild, "member_count", 1) if self.guild else 1
            return f"📊 서버 멤버 `{g_cnt:,}명` · 파티 모집 · 날씨 · 릴레이소설"

        if category == "advanced":
            tier = detect_user_perm_tier_sync(self.user, self.guild)
            tier_label = PERM_BADGES.get(tier, "👤 일반")
            if page < 3:
                access_ok = "✅ 조작 가능" if tier in (PERM_ADMIN, PERM_OWNER) else "🔒 관리자 전용"
                return f"🛡️ 서버 관리자 영역 · 내 권한: {tier_label} ({access_ok})"
            access_ok = "✅ 조작 가능" if tier == PERM_OWNER else "🔒 봇 주인 전용"
            return f"👑 봇 주인 영역 · 내 권한: {tier_label} ({access_ok})"

        if category == "minigame":
            if page == 0:
                crystals = int(profile.get("crystals", 0))
                u_gacha = core.safe_get_dict(self.data, "gacha_users", g_key, u_key)
                cards_cnt = len(core.as_dict(u_gacha.get("cards")))
                sekai_pulls = core.get_proseka_user_total_pulls(u_gacha)
                return f"🎤 크리스탈 `{crystals:,}💎` · 보유 카드 `{cards_cnt:,}종` · 누적 뽑기 `{sekai_pulls:,}회`"
            if page == 1:
                gi_u = core.safe_get_dict(self.data, "genshin_users", g_key, u_key)
                hsr_u = core.safe_get_dict(self.data, "hsr_users", g_key, u_key)
                return (
                    f"🌠 원신 `{gi_u.get('pity_char', 0)}/90` · "
                    f"🚄 스타레일 `{hsr_u.get('pity_char', 0)}/90` (상시 `{hsr_u.get('standard_total_pulls', 0)}/300`)"
                )
            if page == 2:
                return "🎣 어종 `36,700종` 낚시 · 토너먼트 · 개인/공동 농장 · 펫 육성"
            return "🎲 타인의 삶 `1,000종` 엔딩 · 끝말잇기 · 러시안룰렛 · 통합 도감/랭킹"

        # personal
        if page == 0:
            crystals = int(profile.get("crystals", 0))
            oshi = profile.get("oshi") or "미설정"
            return f"🪪 보유 `{crystals:,}💎` · 오시 `{oshi}` · PNG 프로필카드 즉시 발급"
        if page == 1:
            deck_cnt = len(profile.get("deck", []))
            return f"🎒 프로세카 5인 덱 `{deck_cnt}/5장` · 원신/스타레일/낚시 보관함"
        if page == 2:
            todo = core.ensure_user_todo_today(profile)
            tasks_list = [t for t in (todo.get("tasks") or []) if isinstance(t, dict)]
            done_cnt = sum(1 for t in tasks_list if t.get("done"))
            partner_id = profile.get("partner_id")
            p_txt = f"<@{partner_id}>" if partner_id else "미등록"
            return f"🌱 오늘 목표 `{done_cnt}/{len(tasks_list)}` · 💑 파트너 {p_txt}"
        return "☀️ 일일 루틴 · 주간 미션 · 🪙⇄💎 환전소 · 업적 쇼케이스 · 미니대전"

    def _build_category_page_embed(self, category: str, page: int) -> discord.Embed:
        cat_meta = CATEGORY_INFO.get(category, CATEGORY_INFO["general"])
        cat_pages = self._pages_cache.get(category, [])
        page = max(0, min(page, len(cat_pages) - 1))
        page_obj = cat_pages[page]
        items = page_obj.get("items", [])

        global_cur, global_tot = self._get_global_page_info(category, page)
        r, g, b = cat_meta["color"]

        num_badges = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"]
        item_lines = []
        for idx, it in enumerate(items[:6]):
            nb = num_badges[idx] if idx < len(num_badges) else "•"
            it_perm = it.get("perm", PERM_USER)
            perm_suffix = (
                " `👑봇주`" if it_perm == PERM_OWNER
                else (" `🛡️관리자`" if it_perm == PERM_ADMIN else "")
            )
            lbl_clean = re.sub(r"^\[(?:봇주인|서버관리자)\]\s*", "", str(it.get("label") or "")).strip()
            desc_clean = re.sub(r"^\[[^\]]+\]\s*", "", str(it.get("desc") or "")).strip()
            item_lines.append(
                f"{nb} {it['emoji']} **{lbl_clean}**{perm_suffix}\n"
                f"　└ {desc_clean}"
            )

        ctx_line = self._build_context_summary_for_page(category, page)
        short_labels = self._get_category_page_short_labels(category, len(cat_pages))
        page_tabs = "  ·  ".join(
            f"**`{lbl}`**" if i == page else f"{lbl}"
            for i, lbl in enumerate(short_labels)
        )

        desc_lines = [
            f"📑 {page_tabs}",
            f"> {ctx_line}",
            "",
            f"### {page_obj['page_title']}",
            "\n\n".join(item_lines),
        ]

        embed = discord.Embed(
            title=f"{cat_meta['title']} ({page + 1}/{len(cat_pages)}p)",
            description="\n".join(desc_lines),
            color=discord.Color.from_rgb(r, g, b),
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text=f"전체 {global_cur}/{global_tot}p")
        return embed

    def _build_sub_mode_embed(self) -> discord.Embed:
        sub_def = self._get_sub_mode_definition()
        if self.current_category == "home":
            r, g, b = (0, 204, 221)
            breadcrumb = f"🧭 `홈` › **{sub_def['title']}**"
        else:
            cat_meta = CATEGORY_INFO.get(self.current_category, CATEGORY_INFO["general"])
            r, g, b = cat_meta["color"]
            breadcrumb = f"🧭 `홈` › **{cat_meta['label']}** `{self.current_page + 1}p` › **{sub_def['title']}**"

        req_perm = sub_def.get("perm", PERM_USER)
        perm_txt = PERM_BADGES.get(req_perm, "👤 일반 이용자")

        btn_lines = [
            f"• {b_emoji} **{b_label}**"
            for b_label, b_emoji, _, _ in sub_def.get("buttons", [])
        ]

        desc_lines = [
            breadcrumb,
            f"🔐 권한: `{perm_txt}`",
            f"> {sub_def.get('desc', '')}",
            "",
            "### 🎛️ 실행 가능한 세부 기능",
            "\n".join(btn_lines),
        ]

        embed = discord.Embed(
            title=sub_def["title"],
            description="\n".join(desc_lines),
            color=discord.Color.from_rgb(r, g, b),
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="⬅️ 이전 화면  ·  🏠 설정 홈  ·  🔄 새로고침")
        return embed

    async def _enter_sub_mode(self, interaction: discord.Interaction, mode_key: str):
        if self.sub_mode != mode_key:
            self._push_nav_history()
        self.sub_mode = mode_key
        self.refresh_components()
        await core.safe_edit_response(interaction, embed=self.build_current_embed(), view=self)

    # ==========================================================
    # 🌐 1. 일반 (General) 콜백 구현부
    # ==========================================================
    async def _act_attendance(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            embed, file, view = await dday.execute_and_build_attendance_response(interaction, self.bot or interaction.client)
            self.data = await asyncio.to_thread(core.load_data)
            self.refresh_components()
            try:
                if interaction.message:
                    await interaction.message.edit(embed=self.build_current_embed(), view=self)
            except Exception:
                pass
            if file:
                await interaction.followup.send(embed=embed, file=file, view=view, wait=True)
            else:
                await interaction.followup.send(embed=embed, view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 출석체크 처리 중 오류: {e}", ephemeral=True)

    async def _act_att_calendar(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            guild_id = interaction.guild_id or 0
            guild_name = interaction.guild.name if interaction.guild else "개인 메시지(DM)"
            cal_info = await asyncio.to_thread(
                core.build_monthly_attendance_calendar,
                guild_id,
                guild_name,
                interaction.user.id,
                interaction.user.display_name,
            )
            view = dday.AttendanceCalendarView(self.bot or interaction.client, interaction.user, cal_info)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 출석 달력 로드 중 오류: {e}", ephemeral=True)

    async def _act_att_ranking(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            init_scope = "guild" if interaction.guild else "global"
            view = dday.AttendanceRankingView(interaction, data, initial_scope=init_scope, initial_sort="total")
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 출석 랭킹 조회 중 오류: {e}", ephemeral=True)

    async def _act_dday_list(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            view = dday.DDayListBoardView(self.bot or interaction.client, interaction.user, data, guild=interaction.guild)
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ D-Day 전광판 조회 중 오류: {e}", ephemeral=True)

    async def _act_birthday_board(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            view = dday.BirthdayBoardView(interaction.user, interaction.guild, data)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 생일 전광판 조회 중 오류: {e}", ephemeral=True)

    async def _act_sekai_schedule_hub(self, interaction: discord.Interaction):
        await self._enter_sub_mode(interaction, "sekai_schedule")

    async def _sub_sekai_forecast_cal(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            now = datetime.datetime.now(core.KST)
            view = dday.EventForecastView(interaction.user, now.year, now.month)
            embed = await asyncio.to_thread(view.build_embed)
            await interaction.followup.send(embed=embed, view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 미래시 조회 중 오류: {e}", ephemeral=True)

    async def _sub_sekai_live_kr(self, interaction: discord.Interaction):
        await self._send_sekai_live_event(interaction, "kr")

    async def _sub_sekai_live_jp(self, interaction: discord.Interaction):
        await self._send_sekai_live_event(interaction, "jp")

    async def _send_sekai_live_event(self, interaction: discord.Interaction, server_code: str):
        try:
            await core.safe_defer(interaction)
            info = await asyncio.to_thread(core.fetch_live_event_and_gacha_info, server_code)
            ev = info.get("event")
            gachas = info.get("gachas", [])
            embed = discord.Embed(
                title=f"🎶 프로세카 {info.get('server_label', server_code.upper())} 실시간 이벤트 & 가챠",
                color=discord.Color.from_rgb(0, 204, 221),
                timestamp=datetime.datetime.now(core.KST),
            )
            if ev:
                ev_name = ev.get("name", "제목 없음")
                ev_type = core.EVENT_TYPE_MAP.get(ev.get("eventType", ""), "🎵 이벤트")
                start_ms = ev.get("startAt", 0)
                end_ms = ev.get("aggregateAt") or ev.get("closedAt") or 0
                start_dt = datetime.datetime.fromtimestamp(start_ms / 1000, tz=core.KST).strftime("%Y-%m-%d %H:%M") if start_ms else "-"
                end_dt = datetime.datetime.fromtimestamp(end_ms / 1000, tz=core.KST).strftime("%Y-%m-%d %H:%M") if end_ms else "-"
                galaxy_bar = core.get_timestamp_galaxy_bar(start_ms, end_ms)
                embed.add_field(
                    name=f"🏆 [{info.get('event_status', '진행중')}] {ev_name}",
                    value=f"• **종류:** {ev_type} (ID: `{ev.get('id')}`)\n• **기간:** `{start_dt}` ~ `{end_dt}` (KST)\n└ {galaxy_bar}",
                    inline=False,
                )
            if gachas:
                g_lines = []
                for g_item in gachas[:5]:
                    g_name = g_item.get("name", "가챠")
                    g_end_ms = g_item.get("endAt", 0)
                    g_end_dt = datetime.datetime.fromtimestamp(g_end_ms / 1000, tz=core.KST).strftime("%m/%d %H:%M") if g_end_ms else "-"
                    g_lines.append(f"• **{g_name}** (종료: `{g_end_dt}`)")
                embed.add_field(name=f"🎰 진행 중인 가챠 배너 ({len(gachas)}개)", value="\n".join(g_lines), inline=False)
            view = gacha.EventInfoView(self.bot or interaction.client, interaction.user)
            await interaction.followup.send(embed=embed, view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 실시간 이벤트 조회 오류: {e}", ephemeral=True)

    async def _act_playlist_studio(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            view = music.PlaylistStudioView(interaction.user, interaction.user, data)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 플레이리스트 스튜디오 오류: {e}", ephemeral=True)

    async def _act_music_now(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            prefs = core.get_guild_music_prefs(data, interaction.guild_id)
            track_info, err = await core.get_recommended_music(prefs)
            if err or not track_info:
                await interaction.followup.send(f"❌ **음악 선곡 실패:** {err or '추천 곡을 찾을 수 없습니다.'}", ephemeral=True)
                return
            bot_ref = self.bot or interaction.client
            embed, view = bot_ref.build_music_embed_and_view(track_info, prefs, is_morning=False)
            await interaction.followup.send(embed=embed, view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 음악 추천 중 오류: {e}", ephemeral=True)

    async def _act_home_shortcuts(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction, ephemeral=True)
            data = await asyncio.to_thread(core.load_data)
            edit_view = HomeShortcutEditView(
                bot=self.bot or interaction.client,
                user=interaction.user,
                guild=interaction.guild,
                data=data,
                parent_view=self,
            )
            await interaction.followup.send(embed=edit_view.build_embed(), view=edit_view, ephemeral=True, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 홈 즐겨찾기 편집기 로드 오류: {e}", ephemeral=True)

    async def _act_mood_radio(self, interaction: discord.Interaction):
        try:
            from cogs.music import open_mood_radio_from_interaction
            await open_mood_radio_from_interaction(interaction, ephemeral=False)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 무드 음성 라디오 로드 오류: {e}", ephemeral=True)

    async def _act_guild_events(self, interaction: discord.Interaction):
        try:
            from cogs.community import open_guild_event_hub_from_interaction
            await open_guild_event_hub_from_interaction(interaction, ephemeral=False)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 예약 이벤트 신청표 로드 오류: {e}", ephemeral=True)

    async def _act_music_vault(self, interaction: discord.Interaction):
        try:
            music_cog = self._find_cog_with_attr("my_music_library_cmd")
            if music_cog:
                await music_cog.my_music_library_cmd.callback(music_cog, interaction)
            else:
                await core.safe_send_response(interaction, "❌ 음악 모듈을 찾을 수 없습니다.", ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 내 음악보관함 로드 오류: {e}", ephemeral=True)

    async def _act_music_voice_hub(self, interaction: discord.Interaction):
        await self._enter_sub_mode(interaction, "music_voice")

    def _make_speed_cb(self, speed_val: float) -> Callable[[discord.Interaction], Awaitable[None]]:
        async def _cb(interaction: discord.Interaction):
            try:
                music_cog = self._find_cog_with_attr("playback_speed_cmd")
                if music_cog:
                    await music_cog.playback_speed_cmd.callback(music_cog, interaction, 속도=str(speed_val))
                else:
                    await core.safe_send_response(interaction, "❌ 음악 모듈을 찾을 수 없습니다.", ephemeral=True)
            except Exception as e:
                await core.safe_send_response(interaction, f"❌ 배속 변경 오류: {e}", ephemeral=True)
        return _cb

    async def _act_music_headset_toggle(self, interaction: discord.Interaction):
        try:
            music_cog = self._find_cog_with_attr("headset_toggle_cmd")
            if music_cog:
                await music_cog.headset_toggle_cmd.callback(music_cog, interaction, 모드=None)
            else:
                await core.safe_send_response(interaction, "❌ 음악 모듈을 찾을 수 없습니다.", ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 헤드셋 제어 오류: {e}", ephemeral=True)

    async def _act_audio_test(self, interaction: discord.Interaction):
        try:
            voice_state = interaction.user.voice if isinstance(interaction.user, discord.Member) else None
            if not voice_state or not voice_state.channel:
                await core.safe_send_response(
                    interaction,
                    "❌ 먼저 오디오를 진단할 **음성채널**에 입장하신 뒤 버튼을 눌러주세요!",
                    ephemeral=True,
                )
                return
            music_cog = self._find_cog_with_attr("audio_test_cmd")
            if music_cog:
                await music_cog.audio_test_cmd.callback(music_cog, interaction)
            else:
                await core.safe_send_response(interaction, "❌ 오디오 진단 모듈을 찾을 수 없습니다.", ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 오디오 진단 중 오류: {e}", ephemeral=True)

    async def _act_server_stats(self, interaction: discord.Interaction):
        try:
            if not interaction.guild:
                await core.safe_send_response(interaction, "❌ 서버 채널에서만 조회할 수 있습니다.", ephemeral=True)
                return
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            embed = stats.build_server_stats_embed(interaction.guild, data)
            view = stats.ServerStatsDashboardView(interaction.guild, data, user=interaction.user)
            await interaction.followup.send(embed=embed, view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 서버 통계 생성 중 오류: {e}", ephemeral=True)

    async def _act_recruit(self, interaction: discord.Interaction):
        try:
            if not interaction.guild:
                await core.safe_send_response(interaction, "❌ 서버 채널에서만 모집할 수 있습니다.", ephemeral=True)
                return
            await interaction.response.send_modal(stats.RecruitModal())
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 파티 모집 모달 열기 실패: {e}", ephemeral=True)

    async def _act_weather(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            w_info, err = await asyncio.to_thread(core.fetch_accurate_weather_sync, "서울")
            if err or not w_info:
                await interaction.followup.send(f"❌ **날씨 조회 실패:** {err}", ephemeral=True)
                return
            view = stats.WeatherRefreshView("서울", w_info, user=interaction.user)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 날씨 조회 중 오류: {e}", ephemeral=True)

    async def _act_relay_novel_hub(self, interaction: discord.Interaction):
        await self._enter_sub_mode(interaction, "relay_novel")

    async def _sub_relay_start(self, interaction: discord.Interaction):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(RelayStartQuickModal(self.bot or interaction.client))

    async def _sub_relay_status(self, interaction: discord.Interaction):
        comm_cog = self._find_cog_with_attr("relay_status_cmd")
        if comm_cog:
            await comm_cog.relay_status_cmd.callback(comm_cog, interaction)
        else:
            await core.safe_send_response(interaction, "❌ 릴레이 소설 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_relay_archive(self, interaction: discord.Interaction):
        comm_cog = self._find_cog_with_attr("relay_list_cmd")
        if comm_cog:
            await comm_cog.relay_list_cmd.callback(comm_cog, interaction)
        else:
            await core.safe_send_response(interaction, "❌ 릴레이 소설 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_relay_cancel(self, interaction: discord.Interaction):
        comm_cog = self._find_cog_with_attr("relay_cancel_cmd")
        if comm_cog:
            await comm_cog.relay_cancel_cmd.callback(comm_cog, interaction)
        else:
            await core.safe_send_response(interaction, "❌ 릴레이 소설 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _act_suggestion(self, interaction: discord.Interaction):
        try:
            sugg_view = stats.SuggestionTypeSelectView(self.bot or interaction.client)
            await core.safe_send_response(interaction, embed=sugg_view.build_overview_embed(), view=sugg_view, ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 건의함 열기 실패: {e}", ephemeral=True)

    async def _act_sponsor(self, interaction: discord.Interaction):
        try:
            bot_ref = self.bot or interaction.client
            bot_user = getattr(bot_ref, "user", None) if bot_ref else None
            embed = stats.build_sponsor_embed(bot_user)
            view = stats.SponsorView()
            await core.safe_send_response(interaction, embed=embed, view=view, ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 후원 안내 열기 실패: {e}", ephemeral=True)

    async def _act_feature_search(self, interaction: discord.Interaction):
        try:
            await interaction.response.send_modal(DashboardFeatureSearchModal(self))
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 기능 검색 창 열기 실패: {e}", ephemeral=True)

    async def _act_achievements(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction, ephemeral=True)
            gid = interaction.guild_id or 0
            view = routine.ShowcaseView(interaction.user, gid, tab="badges")
            await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 업적·뱃지 현황 로드 실패: {e}", ephemeral=True)

    async def _act_open_help(self, interaction: discord.Interaction):
        try:
            embed = help_cog.build_help_embed("all", "", 0)
            view = help_cog.HelpCategoryView(bot_instance=self.bot or interaction.client, category="all", search_kw="", author=interaction.user)
            await core.safe_send_response(interaction, embed=embed, view=view, ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 도움말 열기 실패: {e}", ephemeral=True)

    # ==========================================================
    # ⚙️ 2. 고급 (Advanced) 콜백 구현부 (서버 관리자 vs 봇 주인 엄격 분리)
    # ==========================================================
    async def _act_admin_quick_role(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="사진 스타일 역할버튼 제작", require_roles_perm=True):
            return
        await interaction.response.send_modal(roles.QuickRoleButtonModal(target_channel=interaction.channel))

    async def _act_admin_role_studio(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="반응역할 종합 스튜디오", require_roles_perm=True):
            return
        studio = roles.ReactionRoleStudioView(interaction.guild, interaction.user)
        await core.safe_send_response(interaction, embed=studio.build_dashboard_embed(), view=studio, ephemeral=True)

    async def _act_admin_role_list(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="반응역할 전체 목록", require_roles_perm=True):
            return
        roles_cog = self._find_cog_with_attr("slash_list_reaction_roles")
        if roles_cog:
            await roles_cog.slash_list_reaction_roles.callback(roles_cog, interaction)
        else:
            await core.safe_defer(interaction, ephemeral=True)
            data = await asyncio.to_thread(core.load_data)
            guild_rr = core.get_guild_reaction_roles(data, interaction.guild.id)
            if not guild_rr:
                await interaction.followup.send("📭 현재 서버에 등록된 반응역할 패널이 없습니다.", ephemeral=True)
                return
            entries = list(guild_rr.items())
            view = roles.ReactionRoleListView(interaction.guild.id, entries)
            await interaction.followup.send(embed=view.build_embed(interaction.guild), view=view, ephemeral=True, wait=True)

    async def _act_admin_announce(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="스마트 공지 발송"):
            return
        await core.safe_defer(interaction, ephemeral=True)
        preview_view = logger.AnnouncementPreviewView(
            author=interaction.user,
            guild=interaction.guild,
            target_channel=interaction.channel,
            title="서버 공식 소식 및 안내사항",
            content=(
                "안녕하세요, 서버 멤버 여러분!\n\n"
                "하단의 **`[✏️ 내용/제목 수정]`** 버튼을 눌러 본문을 작성하거나,\n"
                "**`[📋 추천 공지 템플릿 불러오기]`** 드롭다운에서 템플릿을 선택해 보세요!"
            ),
        )
        await interaction.followup.send(
            content=preview_view.build_preview_content(),
            embed=preview_view.build_embed(),
            view=preview_view,
            ephemeral=True,
            wait=True,
        )

    async def _act_admin_ticket_hub(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="1:1 문의 티켓 설정"):
            return
        await self._enter_sub_mode(interaction, "admin_ticket")

    async def _sub_ticket_create_panel(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="1:1 티켓 패널 생성"):
            return
        ticket_cog = self._find_cog_with_attr("ticket_panel_cmd")
        if ticket_cog:
            await ticket_cog.ticket_panel_cmd.callback(ticket_cog, interaction, 채널=None, 제목=None, 설명=None)
        else:
            await core.safe_send_response(interaction, "❌ 티켓 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_ticket_role_config(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="1:1 티켓 역할 설정"):
            return
        ticket_cog = self._find_cog_with_attr("ticket_config_cmd")
        if ticket_cog:
            await ticket_cog.ticket_config_cmd.callback(
                ticket_cog,
                interaction,
                패널채널=None,
                담당자역할=None,
                카테고리=None,
                로그채널=None,
                방식=None,
                최대티켓수=None,
            )
        else:
            await core.safe_send_response(interaction, "❌ 티켓 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _act_admin_ticket_list(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="1:1 티켓 내역 조회"):
            return
        ticket_cog = self._find_cog_with_attr("ticket_list_cmd")
        if ticket_cog:
            await ticket_cog.ticket_list_cmd.callback(ticket_cog, interaction)
        else:
            await core.safe_send_response(interaction, "❌ 티켓 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _act_admin_temp_voice(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="임시 음성방 설정", require_channels_perm=True):
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        cfg = community_core.get_temp_voice_config(data, interaction.guild.id)
        setup_view = community.TempVoiceSetupView(interaction.user.id, interaction.guild, cfg)
        await interaction.followup.send(embed=setup_view.build_embed(), view=setup_view, ephemeral=True, wait=True)

    async def _act_admin_sticky_hub(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="자동 고정메시지 관리", require_messages_perm=True):
            return
        await self._enter_sub_mode(interaction, "admin_sticky")

    async def _sub_sticky_detail_panel(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="고정메시지 상세 설정", require_messages_perm=True):
            return
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await core.safe_send_response(interaction, "❌ 텍스트 채널 또는 스레드에서만 설정할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        existing = community_core.get_sticky_config(data, interaction.guild.id, interaction.channel.id)
        view = community.StickyDetailConfigView(interaction.user.id, interaction.guild, interaction.channel, existing)
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)

    async def _sub_sticky_set(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="고정메시지 설정", require_messages_perm=True):
            return
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await core.safe_send_response(interaction, "❌ 텍스트 채널 또는 스레드에서만 설정할 수 있습니다.", ephemeral=True)
            return
        data = await asyncio.to_thread(core.load_data)
        existing = community_core.get_sticky_config(data, interaction.guild.id, interaction.channel.id)
        modal = community.StickyConfigModal(interaction.channel, interval=1, color="gold", existing=existing)
        await interaction.response.send_modal(modal)

    async def _sub_sticky_list(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="고정메시지 목록", require_messages_perm=True):
            return
        comm_cog = self._find_cog_with_attr("sticky_list_cmd")
        if comm_cog:
            await comm_cog.sticky_list_cmd.callback(comm_cog, interaction)
        else:
            await core.safe_send_response(interaction, "❌ 커뮤니티 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_sticky_remove(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="고정메시지 해제", require_messages_perm=True):
            return
        comm_cog = self._find_cog_with_attr("sticky_remove_cmd")
        if comm_cog:
            await comm_cog.sticky_remove_cmd.callback(comm_cog, interaction, 채널=None)
        else:
            await core.safe_send_response(interaction, "❌ 커뮤니티 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _act_admin_link_fix(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="SNS 링크보정 설정"):
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        cfg = community_core.get_link_preview_config(data, interaction.guild.id)
        view = community.LinkPreviewConfigView(interaction.user.id, interaction.guild, cfg)
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)

    async def _act_admin_raid_def(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="레이드 비상방어 설정", require_strict_admin=True):
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        cfg = community_core.get_raid_defense_config(data, interaction.guild.id)
        view = community.RaidDefenseConfigView(interaction.user.id, interaction.guild, cfg)
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)

    async def _act_admin_emoji_upscale(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="이모지 업스케일 설정"):
            return
        await core.safe_defer(interaction, ephemeral=True)
        enabled = core.is_emoji_upscale_enabled(interaction.guild.id)
        view = emoji_upscale.EmojiUpscaleConfigView(bot=self.bot or interaction.client, guild_id=interaction.guild.id)
        emb = emoji_upscale.build_emoji_upscale_embed(interaction.guild, interaction.channel, enabled)
        await interaction.followup.send(embed=emb, view=view, ephemeral=True, wait=True)

    async def _act_admin_audit_log(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="실시간 감사로그 설정"):
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild.id)
        logs_dict = core.ensure_dict_path(data, "server_logs")
        if not isinstance(logs_dict.get(g_key), dict):
            logs_dict[g_key] = {"channel_id": None, "enabled": False, "events": {}}
        guild_cfg = logs_dict[g_key]
        hub_view = logger.ServerLogHubView(interaction.guild, guild_cfg)
        await interaction.followup.send(embed=hub_view.build_embed(), view=hub_view, ephemeral=True, wait=True)

    async def _act_admin_purge(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="채널 메시지 청소", require_messages_perm=True):
            return
        await interaction.response.send_modal(DashboardMessagePurgeModal(self.bot or interaction.client))

    async def _act_admin_inactive(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="비활성 멤버 감사", require_strict_admin=True):
            return
        await interaction.response.send_modal(DashboardInactiveAuditModal(self.bot or interaction.client))

    async def _act_admin_dday_hub(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="서버 D-Day 관리", require_channels_perm=True):
            return
        await self._enter_sub_mode(interaction, "admin_dday")

    async def _act_add_dday_modal(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="새 D-Day 등록", require_channels_perm=True):
            return
        await interaction.response.send_modal(DashboardDDayAddModal(self))

    async def _sub_dday_past(self, interaction: discord.Interaction):
        dday_cog = self._find_cog_with_attr("past_dday_cmd")
        if dday_cog:
            await dday_cog.past_dday_cmd.callback(dday_cog, interaction)
        else:
            await core.safe_send_response(interaction, "❌ D-Day 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_dday_set_alert_ch(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="D-Day 알림채널 설정", require_channels_perm=True):
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await core.safe_send_response(interaction, "❌ 텍스트 채널에서만 지정할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)

        def _save_ch():
            with core._DATA_LOCK:
                data = core.load_data()
                core.set_guild_setting(data, interaction.guild_id, "dday_alert_channel_id", interaction.channel.id)
                core.save_data(data)

        await asyncio.to_thread(_save_ch)
        await interaction.followup.send(
            f"✅ 매일 오전 9시 D-Day 정기 브리핑 채널이 {interaction.channel.mention} 채널로 설정되었습니다!",
            ephemeral=True,
        )

    async def _act_admin_music_sched_hub(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="음악 스케줄러 설정"):
            return
        await self._enter_sub_mode(interaction, "admin_music_sched")

    async def _sub_music_set_morning_ch(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="모닝 음악추천 채널 설정"):
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await core.safe_send_response(interaction, "❌ 텍스트 채널에서만 지정할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)

        def _save_m():
            with core._DATA_LOCK:
                data = core.load_data()
                if interaction.guild_id:
                    g_prefs_map = core.ensure_dict_path(data, "guild_music_prefs")
                    g_key = str(interaction.guild_id)
                    base_p = core.as_dict(g_prefs_map.get(g_key)) or copy.deepcopy(core.get_guild_music_prefs(data, interaction.guild_id))
                    base_p["channel_id"] = interaction.channel.id
                    g_prefs_map[g_key] = base_p
                else:
                    prefs = core.ensure_dict_path(data, "music_prefs")
                    prefs["channel_id"] = interaction.channel.id
                core.save_data(data)

        await asyncio.to_thread(_save_m)
        await interaction.followup.send(
            f"🌅 매일 오전 7시 모닝 음악 추천 채널이 {interaction.channel.mention} 채널로 설정되었습니다!",
            ephemeral=True,
        )

    async def _sub_music_custom_sched(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="맞춤 음악알람 스케줄러"):
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        schedules = data.get("music_schedules") if isinstance(data.get("music_schedules"), list) else []
        view = music.MusicScheduleHubView(schedules, interaction.channel, guild=interaction.guild)
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)

    async def _act_admin_github_webhook(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="GitHub 연동 및 배포알림"):
            return
        logger_cog = self._find_cog_with_attr("_execute_github_webhook")
        if logger_cog:
            await logger_cog._execute_github_webhook(interaction, 채널=None, 역할멘션=None, 연동해제=False, 동작=None)
        else:
            await core.safe_send_response(interaction, "❌ 로거 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_owner_github_unbind(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="GitHub 배포알림 연동 해제"):
            return
        logger_cog = self._find_cog_with_attr("_execute_github_webhook")
        if logger_cog:
            await logger_cog._execute_github_webhook(interaction, 채널=None, 역할멘션=None, 연동해제=True, 동작="disable")
        else:
            await core.safe_send_response(interaction, "❌ 로거 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _act_admin_reset_hub(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="서버 데이터 초기화", require_strict_admin=True):
            return
        await self._enter_sub_mode(interaction, "admin_reset")

    async def _sub_reset_dday(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="D-Day/음악 데이터 초기화", require_strict_admin=True):
            return
        view = dday.ResetConfirmView(self.bot or interaction.client)
        await core.safe_send_response(
            interaction,
            "⚠️ **정말로 모든 D-Day(생성된 전광판 채널 포함) 및 음악 설정을 초기화하시겠습니까?**",
            view=view,
            ephemeral=True,
        )

    async def _sub_reset_sekai(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="프로세카 서버 보관함 초기화", require_strict_admin=True):
            return
        view = gacha.GuildGachaResetConfirmView(interaction.guild)
        await core.safe_send_response(
            interaction,
            f"⚠️ **정말로 `{interaction.guild.name}` 서버의 모든 유저 프로세카 캐릭터 보관함을 초기화하시겠습니까?**",
            view=view,
            ephemeral=True,
        )

    async def _sub_reset_genshin(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="원신 서버 데이터 초기화", require_strict_admin=True):
            return
        view = genshin.GenshinGuildResetConfirmView(interaction.guild.id, interaction.user)
        await core.safe_send_response(
            interaction,
            f"⚠️ **정말로 `{interaction.guild.name}` 서버의 원신 기원/보관함 데이터를 초기화하시겠습니까?**",
            view=view,
            ephemeral=True,
        )

    async def _sub_reset_hsr(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="스타레일 서버 데이터 초기화", require_strict_admin=True):
            return
        view = hsr.HSRGuildResetConfirmView(interaction.guild.id, interaction.user)
        await core.safe_send_response(
            interaction,
            f"⚠️ **정말로 `{interaction.guild.name}` 서버의 스타레일 워프/보관함 데이터를 초기화하시겠습니까?**",
            view=view,
            ephemeral=True,
        )

    # ----------------------------------------------------
    # 👑 [봇 주인 전용] (Page 4 of Advanced)
    # ----------------------------------------------------
    async def _act_owner_sekai_pickup_hub(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="프로세카 글로벌 픽업 설정"):
            return
        await self._enter_sub_mode(interaction, "owner_sekai_pickup")

    async def _sub_owner_sekai_auto(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="프로세카 한섭 이벤트 자동 픽업"):
            return
        gacha_cog = self._find_cog_with_attr("set_pickup_cmd")
        if gacha_cog:
            choice_auto = app_commands.Choice(name="🎯 현재 한섭 이벤트에 자동 맞추기 (실시간 DB)", value="event_sync")
            await gacha_cog.set_pickup_cmd.callback(
                gacha_cog,
                interaction,
                모드=choice_auto,
                유닛=None,
                캐릭터=None,
                한정포함=True,
                배너=None,
            )
        else:
            await core.safe_send_response(interaction, "❌ 가챠 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_owner_sekai_reset(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="프로세카 픽업 초기화"):
            return
        gacha_cog = self._find_cog_with_attr("set_pickup_cmd")
        if gacha_cog:
            choice_reset = app_commands.Choice(name="🧹 픽업 초기화 (전체 해제)", value="reset")
            await gacha_cog.set_pickup_cmd.callback(
                gacha_cog,
                interaction,
                모드=choice_reset,
                유닛=None,
                캐릭터=None,
                한정포함=True,
                배너=None,
            )
        else:
            await core.safe_send_response(interaction, "❌ 가챠 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _act_owner_gi_pickup_hub(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="원신 글로벌 픽업 설정"):
            return
        await self._enter_sub_mode(interaction, "owner_gi_pickup")

    async def _sub_owner_gi_auto(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="원신 KST 자동 로테이션 설정"):
            return
        bot_ref = self.bot or interaction.client
        gi_cog = bot_ref.get_cog("GenshinCog") or self._find_cog_with_attr("setup_pickup_cmd")
        if gi_cog and hasattr(gi_cog, "setup_pickup_cmd"):
            await gi_cog.setup_pickup_cmd.callback(gi_cog, interaction, 프리셋="time_rotation")
        else:
            await core.safe_send_response(interaction, "❌ 원신 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_owner_gi_reset(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="원신 기본 픽업 초기화"):
            return
        bot_ref = self.bot or interaction.client
        gi_cog = bot_ref.get_cog("GenshinCog") or self._find_cog_with_attr("setup_pickup_cmd")
        if gi_cog and hasattr(gi_cog, "setup_pickup_cmd"):
            await gi_cog.setup_pickup_cmd.callback(gi_cog, interaction, 프리셋="reset")
        else:
            await core.safe_send_response(interaction, "❌ 원신 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _act_owner_hsr_pickup_hub(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="스타레일 글로벌 픽업 설정"):
            return
        await self._enter_sub_mode(interaction, "owner_hsr_pickup")

    async def _sub_owner_hsr_auto(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="스타레일 KST 자동 로테이션 설정"):
            return
        bot_ref = self.bot or interaction.client
        hsr_cog = bot_ref.get_cog("HSRCog")
        if hsr_cog and hasattr(hsr_cog, "setup_pickup_cmd"):
            await hsr_cog.setup_pickup_cmd.callback(hsr_cog, interaction, 프리셋="time_rotation")
        else:
            await core.safe_send_response(interaction, "❌ 스타레일 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_owner_hsr_reset(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="스타레일 기본 픽업 초기화"):
            return
        bot_ref = self.bot or interaction.client
        hsr_cog = bot_ref.get_cog("HSRCog")
        if hsr_cog and hasattr(hsr_cog, "setup_pickup_cmd"):
            await hsr_cog.setup_pickup_cmd.callback(hsr_cog, interaction, 프리셋="reset")
        else:
            await core.safe_send_response(interaction, "❌ 스타레일 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _act_owner_terminal_hub(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="VM 터미널 실시간 로그 연동"):
            return
        await self._enter_sub_mode(interaction, "owner_terminal")

    async def _bind_owner_term_with_mode(self, interaction: discord.Interaction, mode: str = "detailed"):
        if not await self.check_bot_owner_permission(interaction, action_name="터미널 로그 채널 연동"):
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await core.safe_send_response(interaction, "❌ 텍스트 채널에서만 지정할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        g_key = str(interaction.guild_id or "global")
        ch_id = interaction.channel.id
        norm_mode = "summary" if mode == "summary" else "detailed"

        def _bind():
            with core._DATA_LOCK:
                data = core.load_data()
                s_dict = core.ensure_dict_path(data, "settings")
                t_map = core.ensure_dict_path(data, "settings", "terminal_log_channels")
                t_modes = core.ensure_dict_path(data, "settings", "terminal_log_modes")
                t_map[g_key] = ch_id
                t_modes[g_key] = norm_mode
                s_dict["terminal_log_channel_id"] = ch_id
                s_dict["terminal_log_default_mode"] = norm_mode
                core.save_data(data)
                return len(t_map)

        cnt = await asyncio.to_thread(_bind)
        mode_label = "⚡ 요약 버전" if norm_mode == "summary" else "📋 상세 버전"
        await interaction.followup.send(
            f"🖥️ **VM 서버 터미널 실시간 로그 채널 지정 완료:** 이제부터 터미널(`stdout`/`stderr`) 로그가 {interaction.channel.mention} 채널에 **{mode_label}**으로 기록됩니다! (연동 서버: `{cnt}개`)",
            ephemeral=True,
        )

    async def _sub_owner_term_bind_detailed(self, interaction: discord.Interaction):
        await self._bind_owner_term_with_mode(interaction, "detailed")

    async def _sub_owner_term_bind_summary(self, interaction: discord.Interaction):
        await self._bind_owner_term_with_mode(interaction, "summary")

    async def _sub_owner_term_bind(self, interaction: discord.Interaction):
        await self._bind_owner_term_with_mode(interaction, "detailed")

    async def _sub_owner_term_unbind(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="터미널 로그 채널 해제"):
            return
        await core.safe_defer(interaction, ephemeral=True)
        g_key = str(interaction.guild_id or "global")

        def _unbind():
            with core._DATA_LOCK:
                data = core.load_data()
                s_dict = core.ensure_dict_path(data, "settings")
                t_map = core.ensure_dict_path(data, "settings", "terminal_log_channels")
                t_modes = core.ensure_dict_path(data, "settings", "terminal_log_modes")
                t_map.pop(g_key, None)
                t_modes.pop(g_key, None)
                if not t_map:
                    s_dict["terminal_log_channel_id"] = None
                core.save_data(data)

        await asyncio.to_thread(_unbind)
        await interaction.followup.send("🛑 현재 서버의 VM 터미널 실시간 로그 전송이 해제되었습니다.", ephemeral=True)

    async def _act_owner_backup_sync_hub(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="전체 DB 백업 & 슬래시 동기화"):
            return
        await self._enter_sub_mode(interaction, "owner_backup_sync")

    async def _sub_owner_backup_guild(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="서버 구조 JSON 백업"):
            return
        stats_cog = self._find_cog_with_attr("server_backup_cmd")
        if stats_cog:
            choice_g = app_commands.Choice(name="🏢 현재 서버 구조 백업", value="guild")
            await stats_cog.server_backup_cmd.callback(stats_cog, interaction, 모드=choice_g)
        else:
            await core.safe_send_response(interaction, "❌ 백업 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_owner_backup_db(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="전체 봇 DB JSON 백업"):
            return
        stats_cog = self._find_cog_with_attr("server_backup_cmd")
        if stats_cog:
            choice_db = app_commands.Choice(name="🗄️ 봇 전체 DB 백업", value="db")
            await stats_cog.server_backup_cmd.callback(stats_cog, interaction, 모드=choice_db)
        else:
            await core.safe_send_response(interaction, "❌ 백업 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_owner_sync_panel(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="슬래시 명령어 동기화"):
            return
        import bot as bot_mod
        sync_view = bot_mod.SyncControlView(author=interaction.user, guild=interaction.guild)
        embed = discord.Embed(
            title="⚡ [봇 주인 전용] 슬래시 명령어 즉시 동기화 제어판",
            description="현재 서버에 슬래시 명령어를 0초 즉시 반영하거나 글로벌 전역 동기화를 실행할 수 있습니다.",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(core.KST),
        )
        await core.safe_send_response(interaction, embed=embed, view=sync_view, ephemeral=True)

    async def _sub_owner_bot_banner(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="봇 프로필 배너 변경/초기화"):
            return
        await interaction.response.send_modal(BotBannerModal())

    async def _act_bot_host_status(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="봇 상태(호스트 시스템 리소스) 진단"):
            return
        stats_cog = self._find_cog_with_attr("host_system_stats_cmd")
        if stats_cog:
            await stats_cog.host_system_stats_cmd.callback(stats_cog, interaction)
        else:
            await core.safe_send_response(interaction, "❌ 통계 모듈을 찾을 수 없습니다.", ephemeral=True)

    # ==========================================================
    # 🎮 3. 미니게임 (Minigames) 콜백 구현부
    # ==========================================================
    async def _act_sekai_pull_10(self, interaction: discord.Interaction):
        try:
            repull_view = gacha.GachaPullAgainView(interaction.user)
            await repull_view._handle_repull(interaction, 10)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 프로세카 10회 뽑기 오류: {e}", ephemeral=True)

    async def _act_sekai_pull_1(self, interaction: discord.Interaction):
        try:
            repull_view = gacha.GachaPullAgainView(interaction.user)
            await repull_view._handle_repull(interaction, 1)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 프로세카 1회 뽑기 오류: {e}", ephemeral=True)

    async def _act_sekai_live(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            view = gacha.SekaiLiveView(interaction.user, guild_id=interaction.guild_id or 0)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 세카이 라이브 열기 오류: {e}", ephemeral=True)

    async def _act_sekai_master_rank(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            view = gacha.MasterRankView(interaction.user, guild_id=interaction.guild_id or 0)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 마스터 랭크 창 열기 오류: {e}", ephemeral=True)

    async def _act_sekai_char_rank(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            view = gacha.CharacterRankView(interaction.user, guild_id=interaction.guild_id or 0)
            embed, file_obj = await view.build_embed_and_file()
            if file_obj:
                await interaction.followup.send(embed=embed, file=file_obj, view=view, wait=True)
            else:
                await interaction.followup.send(embed=embed, view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 캐릭터 랭크 창 열기 오류: {e}", ephemeral=True)

    async def _act_sekai_wardrobe(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            view = gacha.CharacterCostumeWardrobeView(interaction.user, guild_id=interaction.guild_id or 0)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 3D 의상실 열기 오류: {e}", ephemeral=True)

    async def _act_sekai_myroom(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            view = gacha.MySekaiHubView(interaction.user, interaction.user, interaction.guild_id or 0, data)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 마이세카이 미니룸 열기 오류: {e}", ephemeral=True)

    async def _act_gi_pull_10(self, interaction: discord.Interaction):
        try:
            pv = genshin.GenshinPullAgainView(interaction.user, banner_key="char1", skip_anim=False, practice=False, last_count=10)
            await pv._run_repull_with_cooldown(interaction, 10)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 원신 기원 실행 오류: {e}", ephemeral=True)

    async def _act_gi_fate(self, interaction: discord.Interaction):
        try:
            v = genshin.GenshinFatePathView(interaction.guild_id or 0, interaction.user)
            await core.safe_send_response(interaction, embed=v.build_embed(), view=v, ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 운명의 궤도 로드 오류: {e}", ephemeral=True)

    async def _act_gi_shop(self, interaction: discord.Interaction):
        try:
            v = genshin.GenshinShopView(interaction.guild_id or 0, interaction.user)
            await core.safe_send_response(interaction, embed=v.build_embed(), view=v)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 페이몬 상점 로드 오류: {e}", ephemeral=True)

    async def _act_hsr_warp_10(self, interaction: discord.Interaction):
        try:
            wv = hsr.HSRWarpAgainView(interaction.user, banner_key="char1", skip_anim=False, practice=False, last_count=10)
            await wv._run_rewarp_with_cooldown(interaction, 10)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 스타레일 워프 실행 오류: {e}", ephemeral=True)

    async def _act_hsr_300(self, interaction: discord.Interaction):
        try:
            v = hsr.HSRStandard300View(interaction.guild_id or 0, interaction.user)
            await core.safe_send_response(interaction, embed=v.build_embed(), view=v, ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 상시 300회 보상 로드 오류: {e}", ephemeral=True)

    async def _act_hsr_shop(self, interaction: discord.Interaction):
        try:
            v = hsr.HSRShopView(interaction.guild_id or 0, interaction.user)
            await core.safe_send_response(interaction, embed=v.build_embed(), view=v)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 스타레일 상점 로드 오류: {e}", ephemeral=True)

    async def _act_fishing_cast(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            guild_id = interaction.guild_id or 0
            summary = await asyncio.to_thread(
                fishing_core.update_user_fishing_prefs,
                guild_id,
                interaction.user.id,
                interaction.user.display_name,
            )
            view = fishing.FishingCastView(interaction.user, guild_id=guild_id, summary=summary)
            msg = await interaction.followup.send(embed=view.build_dashboard_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 낚시 출조 창 열기 실패: {e}", ephemeral=True)

    async def _act_fishing_tourney(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            guild_id = interaction.guild_id or 0
            status = await asyncio.to_thread(fishing_core.get_fishing_tournament_status, guild_id)
            view = fishing.FishingTournamentView(interaction.user, guild_id=guild_id, status=status, tab="live")
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 낚시 대회 전광판 열기 실패: {e}", ephemeral=True)

    async def _act_fishing_aquarium(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            guild_id = interaction.guild_id or 0
            summary = await asyncio.to_thread(
                fishing_core.get_user_fishing_summary,
                guild_id,
                interaction.user.id,
                interaction.user.display_name,
            )
            view = fishing.FishingAquariumView(interaction.user, interaction.user, guild_id=guild_id, summary=summary)
            msg = await view.send_initial(interaction, ephemeral=False)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 수족관 열기 실패: {e}", ephemeral=True)

    async def _act_fishing_shop(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            guild_id = interaction.guild_id or 0
            summary = await asyncio.to_thread(
                fishing_core.get_user_fishing_summary,
                guild_id,
                interaction.user.id,
                interaction.user.display_name,
            )
            view = fishing.FishingShopView(interaction.user, guild_id=guild_id, category="rod", summary=summary)
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 낚시 상점 열기 실패: {e}", ephemeral=True)

    async def _act_life_dashboard(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            ov = await asyncio.to_thread(
                life_core.get_life_overview,
                interaction.guild_id or 0,
                interaction.user.id,
                interaction.user.display_name,
            )
            view = life.LifeDashboardView(interaction.user, interaction.guild, overview=ov)
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 생활 대시보드 열기 실패: {e}", ephemeral=True)

    async def _act_life_farm(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            gid = interaction.guild_id or 0
            ov = await asyncio.to_thread(
                life_core.get_life_overview,
                gid,
                interaction.user.id,
                interaction.user.display_name,
            )
            view = life.FarmView(interaction.user, gid, overview=ov)
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 개인 농장 열기 실패: {e}", ephemeral=True)

    async def _act_other_life_play(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            gid = interaction.guild_id or 0
            u_state, _, idle_logs = await asyncio.to_thread(
                other_life_core.get_other_life_state,
                gid,
                interaction.user.id,
                interaction.user.display_name,
            )
            view = other_life.OtherLifeGameView(interaction.user, gid, user_state=u_state, idle_logs=idle_logs)
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 타인의 삶 시작 실패: {e}", ephemeral=True)

    async def _act_other_life_codex(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            gid = interaction.guild_id or 0
            u_state, _, _ = await asyncio.to_thread(
                other_life_core.get_other_life_state,
                gid,
                interaction.user.id,
                interaction.user.display_name,
            )
            view = other_life.OtherLifeCollectionView(interaction.user, gid, user_state=u_state)
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 타인의 삶 엔딩도감 열기 실패: {e}", ephemeral=True)

    async def _act_other_life_rank(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            gid = interaction.guild_id or 0
            view = other_life.OtherLifeRankingView(interaction.user, gid)
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 타인의 삶 랭킹 조회 실패: {e}", ephemeral=True)

    async def _act_word_chain(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            first_word = random.choice(["세카이", "음악", "별자리", "피아노", "출석", "콘서트", "하늘", "무지개", "기차", "바다"])
            view = stats.WordChainGameView(interaction.user, None, first_word)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 끝말잇기 시작 오류: {e}", ephemeral=True)

    async def _act_roulette(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            view = stats.RussianRouletteView(interaction.user, bullets=1, bet_crystals=0)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 러시안룰렛 시작 오류: {e}", ephemeral=True)

    async def _act_pokedex_hub(self, interaction: discord.Interaction):
        await self._enter_sub_mode(interaction, "pokedex_hub")

    async def _act_ranking_hub(self, interaction: discord.Interaction):
        await self._enter_sub_mode(interaction, "ranking_hub")

    async def _act_sekai_pokedex(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            guild_id = interaction.guild_id or 0
            stats_data = await asyncio.to_thread(core.get_card_pokedex_stats, guild_id, interaction.user.id)
            view = gacha.CardPokedexView(interaction.user, stats_data, guild_id=guild_id, initial_tab="char_rates")
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 프로세카 카드도감 로드 오류: {e}", ephemeral=True)

    async def _act_gi_pokedex(self, interaction: discord.Interaction):
        try:
            v = genshin.GenshinPokedexView(interaction.guild_id or 0, interaction.user, tab="owned")
            await core.safe_send_response(interaction, embed=v.build_embed(), view=v)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 원신 도감 로드 오류: {e}", ephemeral=True)

    async def _act_hsr_pokedex(self, interaction: discord.Interaction):
        try:
            v = hsr.HSRPokedexView(interaction.guild_id or 0, interaction.user, tab="owned")
            await core.safe_send_response(interaction, embed=v.build_embed(), view=v)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 스타레일 도감 로드 오류: {e}", ephemeral=True)

    async def _act_fishing_pokedex(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            guild_id = interaction.guild_id or 0
            st = await asyncio.to_thread(fishing_core.get_fishing_pokedex_stats, guild_id, interaction.user.id)
            view = fishing.FishingPokedexView(interaction.user, guild_id=guild_id, tab="lake", stats=st)
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 낚시 도감 로드 오류: {e}", ephemeral=True)

    async def _sub_sekai_rates(self, interaction: discord.Interaction):
        gacha_cog = self._find_cog_with_attr("proseka_rate_list_cmd")
        if gacha_cog:
            await gacha_cog.proseka_rate_list_cmd.callback(gacha_cog, interaction, 배너=None)
        else:
            await core.safe_send_response(interaction, "❌ 가챠 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_gi_rates(self, interaction: discord.Interaction):
        v = genshin.GenshinRateView(banner_key="char1")
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v, ephemeral=True)

    async def _sub_hsr_rates(self, interaction: discord.Interaction):
        v = hsr.HSRRateView(banner_key="char1")
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v, ephemeral=True)

    async def _act_sekai_rank(self, interaction: discord.Interaction):
        gacha_cog = self._find_cog_with_attr("gacha_ranking_cmd")
        if gacha_cog:
            await gacha_cog.gacha_ranking_cmd.callback(gacha_cog, interaction)
        else:
            await core.safe_send_response(interaction, "❌ 가챠 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _act_gi_rank(self, interaction: discord.Interaction):
        v = genshin.GenshinRankingView(interaction.guild_id or 0, mode="ranking")
        await core.safe_send_response(interaction, embed=v.build_embed(interaction.guild), view=v)

    async def _act_hsr_rank(self, interaction: discord.Interaction):
        v = hsr.HSRRankingView(interaction.guild_id or 0, mode="ranking")
        await core.safe_send_response(interaction, embed=v.build_embed(interaction.guild), view=v)

    async def _act_fishing_rank(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        view = fishing.FishingRankingView(interaction.user, guild_id=interaction.guild_id or 0)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    async def _act_economy_rank(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        lb = await asyncio.to_thread(economy_core.get_economy_leaderboard, guild_id)
        view = economy.EconomyLeaderboardView(interaction.user, guild_id, "net_worth", lb=lb)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    # ==========================================================
    # 👤 4. 개인 (Personal) 콜백 구현부
    # ==========================================================
    async def _act_profile_card_png(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            await economy._send_profile_card(interaction.followup.send, interaction.user, interaction.guild_id or 0)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 통합 프로필카드 생성 오류: {e}", ephemeral=True)

    async def _act_sekai_profile(self, interaction: discord.Interaction):
        try:
            gacha_cog = self._find_cog_with_attr("my_profile_cmd")
            if gacha_cog:
                await gacha_cog.my_profile_cmd.callback(gacha_cog, interaction, None)
            else:
                await core.safe_send_response(interaction, "❌ 프로필 모듈을 찾을 수 없습니다.", ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 프로세카 내 프로필 조회 오류: {e}", ephemeral=True)

    async def _act_oshi_setup(self, interaction: discord.Interaction):
        try:
            view = OshiQuickSelectView(interaction.user, parent_dashboard=self)
            embed = discord.Embed(
                title="💖 나의 최애(오시) 프로세카 캐릭터 설정",
                description="아래 드롭다운 메뉴(그룹 A / 그룹 B)에서 대표 오시 캐릭터를 선택하면 즉시 반영됩니다!",
                color=discord.Color.from_rgb(255, 105, 180),
                timestamp=datetime.datetime.now(core.KST),
            )
            await core.safe_send_response(interaction, embed=embed, view=view, ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 오시 설정 창 열기 실패: {e}", ephemeral=True)

    async def _act_title_shop(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            stats_data = await asyncio.to_thread(
                economy_core.get_title_shop_state,
                interaction.guild_id or 0,
                interaction.user.id,
                interaction.user.display_name,
            )
            view = economy.TitleStudioView(interaction.user, interaction.guild_id or 0, stats=stats_data)
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 칭호 상점 열기 실패: {e}", ephemeral=True)

    async def _act_crystal_transfer(self, interaction: discord.Interaction):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 송금할 수 있습니다.", ephemeral=True)
            return
        view = CrystalTransferUserSelectView(interaction.user)
        embed = discord.Embed(
            title="💸 크리스탈 송금 대상 선택",
            description="아래 유저 선택 드롭다운에서 크리스탈을 받을 서버 멤버를 선택하면 금액 입력 창이 열립니다.\n*(수수료 5% · 일일 송금 한도 5,000💎)*",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(core.KST),
        )
        await core.safe_send_response(interaction, embed=embed, view=view, ephemeral=True)

    async def _act_user_info(self, interaction: discord.Interaction):
        stats_cog = self._find_cog_with_attr("user_profile_info_cmd")
        if stats_cog:
            await stats_cog.user_profile_info_cmd.callback(stats_cog, interaction, interaction.user)
        else:
            await core.safe_send_response(interaction, "❌ 유저정보 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _act_sekai_inv(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            g_key = str(interaction.guild_id or 0)
            u_key = str(interaction.user.id)
            user_cards_dict = core.safe_get_dict(data, "gacha_users", g_key, u_key, "cards")
            view = gacha.MyInventoryView(
                interaction.user,
                [c for c in user_cards_dict.values() if isinstance(c, dict)],
                items_per_page=10,
                guild_id=interaction.guild_id or 0,
            )
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 프로세카 보관함 로드 오류: {e}", ephemeral=True)

    async def _act_sekai_dup_convert(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction, ephemeral=True)
            guild_id = interaction.guild_id or 0
            preview = await asyncio.to_thread(core.preview_duplicate_cards, guild_id, interaction.user.id)
            view = gacha.DuplicateConvertConfirmView(
                guild_id,
                interaction.user,
                preview,
                parent_menu_view=self,
                parent_menu_message=interaction.message,
            )
            await core.safe_send_response(interaction, embed=view.build_preview_embed(), view=view, ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 중복 카드 환전 오류: {e}", ephemeral=True)

    async def _act_sekai_deck_hub(self, interaction: discord.Interaction):
        await self._enter_sub_mode(interaction, "sekai_deck")

    async def _sub_sekai_deck_view(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction, ephemeral=True)
            data = await asyncio.to_thread(core.load_data)
            profile = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
            deck_ids = profile.get("deck", [])
            g_key = str(interaction.guild_id or 0)
            u_key = str(interaction.user.id)
            user_cards_dict = core.safe_get_dict(data, "gacha_users", g_key, u_key, "cards")

            deck_cards_lines = []
            for slot_idx, cid in enumerate(deck_ids, start=1):
                cinfo = core.as_dict(user_cards_dict.get(str(cid)) or user_cards_dict.get(cid))
                cname = cinfo.get("char_name", "미상")
                cprefix = cinfo.get("prefix", "")
                rlabel = cinfo.get("rarity_label", "★1")
                deck_cards_lines.append(
                    f"**슬롯 {slot_idx} (리더)**: {rlabel} [{cprefix}] **{cname}** (`ID: {cid}`)"
                    if slot_idx == 1
                    else f"**슬롯 {slot_idx}**: {rlabel} [{cprefix}] {cname} (`ID: {cid}`)"
                )

            desc = (
                "현재 편성된 5인 유닛 덱 목록입니다:\n\n" + "\n".join(deck_cards_lines)
                + "\n\n💡 아래 **`[⚡ 최고 종합력 5인 자동 편성]`** 또는 **`[✏️ 카드 ID·이름으로 5인 직접 편성]`** 버튼으로 즉시 편성을 변경할 수 있습니다!"
                if deck_cards_lines
                else "현재 편성된 덱이 없습니다.\n아래 **`[⚡ 최고 종합력 5인 자동 편성]`** 또는 **`[✏️ 카드 ID·이름으로 5인 직접 편성]`** 버튼을 눌러 5장을 편성해 보세요!"
            )
            embed = discord.Embed(
                title=f"🎴 {interaction.user.display_name}님의 5인 유닛 덱 현황 & 편성",
                description=desc,
                color=discord.Color.from_rgb(235, 69, 158),
                timestamp=datetime.datetime.now(core.KST),
            )
            deck_view = SekaiDeckManageView(interaction.user, self.bot or interaction.client)
            await interaction.followup.send(embed=embed, view=deck_view, ephemeral=True, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 덱 현황 조회 오류: {e}", ephemeral=True)

    async def _sub_sekai_card_enhance(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CardEnhanceQuickModal(self.bot or interaction.client))

    async def _sub_sekai_card_trade(self, interaction: discord.Interaction):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 1:1 카드 교환을 이용할 수 있습니다.", ephemeral=True)
            return
        view = CardTradeUserSelectView(interaction.user, self.bot or interaction.client)
        embed = discord.Embed(
            title="🔄 프로세카 1:1 카드 교환 장터 (100💎)",
            description="아래 드롭다운에서 **카드를 교환할 서버 멤버**를 선택하면 1:1 카드 교환 스튜디오가 열립니다!",
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST),
        )
        await core.safe_send_response(interaction, embed=embed, view=view, ephemeral=True)

    async def _sub_sekai_card_gift(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CardGiftQuickModal(self.bot or interaction.client))

    async def _act_gi_personal_hub(self, interaction: discord.Interaction):
        await self._enter_sub_mode(interaction, "gi_personal")

    async def _act_gi_inv(self, interaction: discord.Interaction):
        v = genshin.GenshinInventoryView(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v)

    async def _act_gi_party(self, interaction: discord.Interaction):
        v = genshin.GenshinPartyView(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v)

    async def _act_hsr_personal_hub(self, interaction: discord.Interaction):
        await self._enter_sub_mode(interaction, "hsr_personal")

    async def _act_hsr_inv(self, interaction: discord.Interaction):
        v = hsr.HSRInventoryView(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v)

    async def _act_hsr_party(self, interaction: discord.Interaction):
        v = hsr.HSRPartyView(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v)

    async def _act_fishing_personal_hub(self, interaction: discord.Interaction):
        await self._enter_sub_mode(interaction, "fishing_personal")

    async def _sub_fishing_bag(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary,
            guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        view = fishing.FishingBagView(interaction.user, guild_id=guild_id, summary=summary)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    async def _sub_fishing_quest(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary,
            guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        view = fishing.FishingQuestView(interaction.user, guild_id=guild_id, summary=summary)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    async def _sub_fishing_profile(self, interaction: discord.Interaction):
        fishing_cog = self._find_cog_with_attr("fishing_profile_cmd")
        if fishing_cog:
            await fishing_cog.fishing_profile_cmd.callback(fishing_cog, interaction, 유저=None)
        else:
            await core.safe_send_response(interaction, "❌ 낚시 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_fishing_market(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            guild_id = interaction.guild_id or 0
            view = fishing.FishingMarketView(interaction.user, guild_id=guild_id)
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 어시장 시세 열기 실패: {e}", ephemeral=True)

    async def _sub_fishing_raid(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            guild_id = interaction.guild_id or 0
            status = await asyncio.to_thread(fishing_core.get_fishing_boss_status, guild_id)
            view = fishing.FishingBossRaidView(interaction.user, guild_id=guild_id, status=status)
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 보스 레이드 전광판 열기 실패: {e}", ephemeral=True)

    async def _sub_fishing_workshop(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            guild_id = interaction.guild_id or 0
            summary = await asyncio.to_thread(
                fishing_core.get_user_fishing_summary,
                guild_id,
                interaction.user.id,
                interaction.user.display_name,
            )
            view = fishing.FishingShopView(interaction.user, guild_id=guild_id, category="enhance", summary=summary)
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 강화·제작 공방 열기 실패: {e}", ephemeral=True)

    async def _act_todo_grass(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            profile = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
            core.ensure_user_todo_today(profile)
            await asyncio.to_thread(core.save_data, data)
            view = dday.TodoTrackerView(interaction.user, profile)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 오늘 목표 보드 로드 오류: {e}", ephemeral=True)

    async def _act_pomodoro(self, interaction: discord.Interaction):
        try:
            key = (interaction.guild_id or 0, interaction.user.id)
            if key in core.ACTIVE_POMODORO_TASKS:
                task_info = core.ACTIVE_POMODORO_TASKS.pop(key, None)
                if task_info:
                    task_info["task"].cancel()
                    v_ch = task_info.get("voice_channel")
                    muted_ids = task_info.get("muted_member_ids", set())
                    if v_ch:
                        for member in v_ch.members:
                            if not member.bot and (not muted_ids or member.id in muted_ids):
                                try:
                                    await member.edit(mute=False, reason="집중모드 수동 중지")
                                except Exception:
                                    pass
                await core.safe_send_response(
                    interaction,
                    "⏹️ **실행 중이던 뽀모도로 집중모드가 중지되었으며 음소거가 해제되었습니다!**",
                    ephemeral=True,
                )
                return
            await interaction.response.send_modal(DashboardPomodoroModal(self.bot or interaction.client))
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 집중모드 실행 오류: {e}", ephemeral=True)

    async def _act_hardcore_study(self, interaction: discord.Interaction):
        try:
            key = (interaction.guild_id or 0, interaction.user.id)
            if key in core.ACTIVE_HARDCORE_STUDY_TASKS:
                task_info = core.ACTIVE_HARDCORE_STUDY_TASKS.pop(key, None)
                if task_info:
                    task_info["task"].cancel()
                    v_ch = task_info.get("voice_channel")
                    muted_ids = task_info.get("muted_member_ids", set())
                    if v_ch:
                        for member in v_ch.members:
                            if not member.bot and (not muted_ids or member.id in muted_ids):
                                try:
                                    await member.edit(mute=False, reason="하드코어 스터디 수동 중지")
                                except Exception:
                                    pass
                    vc = task_info.get("voice_client")
                    if vc and vc.is_connected():
                        try:
                            await vc.disconnect()
                        except Exception:
                            pass
                await core.safe_send_response(
                    interaction,
                    "⏹️ **실행 중이던 하드코어 스터디가 중지되었으며 음소거가 해제되었습니다!**",
                    ephemeral=True,
                )
                return

            await interaction.response.send_modal(DashboardHardcoreStudyModal(self.bot or interaction.client))
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 하드코어 스터디 실행 오류: {e}", ephemeral=True)

    async def _act_reminder_hub(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction, ephemeral=True)
            data = await asyncio.to_thread(core.load_data)
            view = dday.ReminderHubView(interaction.user, interaction.channel_id, interaction.guild_id, data)
            await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 알림 예약 허브 로드 오류: {e}", ephemeral=True)

    async def _act_secret_dday(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction, ephemeral=True)
            data = await asyncio.to_thread(core.load_data)
            prof = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
            view = dday.SecretDDayHubView(interaction.user, core.as_dict(prof.get("secret_ddays")))
            await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 비밀 D-Day 보드 로드 오류: {e}", ephemeral=True)

    async def _act_bday_partner_hub(self, interaction: discord.Interaction):
        await self._enter_sub_mode(interaction, "bday_partner")

    async def _act_partner_studio(self, interaction: discord.Interaction):
        try:
            data = await asyncio.to_thread(core.load_data)
            profile = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
            partner_id = profile.get("partner_id")
            if not partner_id:
                view = PartnerProposeUserSelectView(interaction.user, self.bot or interaction.client)
                embed = discord.Embed(
                    title="💌 파트너(짝꿍) 신청하기",
                    description="현재 등록된 파트너가 없습니다.\n아래 드롭다운에서 소중한 친구나 연인을 선택해 **파트너를 신청**해 보세요! 💖",
                    color=discord.Color.from_rgb(255, 105, 180),
                    timestamp=datetime.datetime.now(core.KST),
                )
                await core.safe_send_response(interaction, embed=embed, view=view, ephemeral=True)
                return
            await core.safe_defer(interaction, ephemeral=True)
            view = dday.PartnerHubView(interaction.user, partner_id, data)
            await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 파트너 스튜디오 조회 오류: {e}", ephemeral=True)

    async def _sub_partner_propose(self, interaction: discord.Interaction):
        view = PartnerProposeUserSelectView(interaction.user, self.bot or interaction.client)
        embed = discord.Embed(
            title="💌 파트너(짝꿍) 신청 대상 선택",
            description="아래 드롭다운에서 파트너를 맺을 서버 멤버를 선택하면 상대방에게 파트너 수락 버튼이 발송됩니다!",
            color=discord.Color.from_rgb(255, 105, 180),
            timestamp=datetime.datetime.now(core.KST),
        )
        await core.safe_send_response(interaction, embed=embed, view=view, ephemeral=True)

    async def _sub_partner_break(self, interaction: discord.Interaction):
        dday_cog = self._find_cog_with_attr("partner_cmd")
        if dday_cog:
            choice_brk = app_commands.Choice(name="💔 파트너 해제하기", value="break")
            await dday_cog.partner_cmd.callback(dday_cog, interaction, 동작=choice_brk)
        else:
            await core.safe_send_response(interaction, "❌ 파트너 모듈을 찾을 수 없습니다.", ephemeral=True)

    # ----------------------------------------------------
    # 🧩 추가 통합된 슬래시 명령어 세부 콜백
    # ----------------------------------------------------
    async def _act_my_temp_voice_remote(self, interaction: discord.Interaction):
        comm_cog = self._find_cog_with_attr("temp_voice_slash_cmd")
        if comm_cog:
            choice_remote = app_commands.Choice(name="🎛️ 내 임시 음성방 리모컨 호출 (방장/멤버용)", value="remote")
            await comm_cog.temp_voice_slash_cmd.callback(comm_cog, interaction, 메뉴=choice_remote)
        else:
            await core.safe_send_response(interaction, "❌ 임시 음성방 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_ticket_custom_panel(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="커스텀 티켓 패널 생성"):
            return
        await interaction.response.send_modal(DashboardTicketCustomPanelModal(self.bot or interaction.client))

    async def _sub_ticket_member_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DashboardTicketMemberModal(self.bot or interaction.client))

    async def _sub_ticket_close_current(self, interaction: discord.Interaction):
        ticket_cog = self._find_cog_with_attr("ticket_close_cmd")
        if ticket_cog:
            await ticket_cog.ticket_close_cmd.callback(ticket_cog, interaction)
        else:
            await core.safe_send_response(interaction, "❌ 티켓 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_sticky_toggle(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="고정메시지 토글", require_messages_perm=True):
            return
        comm_cog = self._find_cog_with_attr("sticky_toggle_cmd")
        if comm_cog:
            data = core.get_cached_data()
            cur_enabled = True
            if interaction.guild and interaction.channel:
                cfg = community_core.get_sticky_config(data, interaction.guild.id, interaction.channel.id)
                if cfg:
                    cur_enabled = bool(cfg.get("enabled", True))
            next_val = "off" if cur_enabled else "on"
            next_name = "🔴 끄기 (일시 중지)" if next_val == "off" else "🟢 켜기 (활성화)"
            choice_st = app_commands.Choice(name=next_name, value=next_val)
            await comm_cog.sticky_toggle_cmd.callback(comm_cog, interaction, 상태=choice_st, 채널=None)
        else:
            await core.safe_send_response(interaction, "❌ 커뮤니티 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_dday_setup_board(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="D-Day 채널·알림 설정", require_channels_perm=True):
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        view = dday.DDayChannelSetupView(self.bot or interaction.client, interaction.user, interaction.guild, data)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        view.message = msg

    async def _sub_dday_set_default_cat(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="D-Day 기본 카테고리 지정", require_channels_perm=True):
            return
        cat = getattr(interaction.channel, "category", None)
        if not cat:
            await core.safe_send_response(interaction, "❌ 현재 채널이 속한 카테고리가 없습니다. 카테고리 내부 채널에서 실행해 주세요!", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        def _save_default_cat():
            with core._DATA_LOCK:
                data = core.load_data()
                core.set_guild_setting(data, interaction.guild_id, "default_category_id", cat.id)
                core.save_data(data)
        await asyncio.to_thread(_save_default_cat)
        await interaction.followup.send(
            f"✅ D-Day 전광판 기본 카테고리 지정 완료: 📁 **`{cat.name}`**",
            ephemeral=True,
        )

    async def _sub_music_prefs_modal(self, interaction: discord.Interaction):
        if not await self.check_admin_permission(interaction, action_name="모닝 음악 추천 상세 설정"):
            return
        await interaction.response.send_modal(DashboardMorningMusicPrefsModal(self.bot or interaction.client))

    async def _sub_owner_sekai_fes(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="프로세카 컬러풀 페스 전환"):
            return
        gacha_cog = self._find_cog_with_attr("set_pickup_cmd")
        if gacha_cog:
            choice_fes = app_commands.Choice(name="🎊 컬러풀 페스티벌 (★4 2배 · 6.0%!)", value="fes")
            await gacha_cog.set_pickup_cmd.callback(
                gacha_cog,
                interaction,
                모드=None,
                유닛=None,
                캐릭터=None,
                한정포함=True,
                배너=choice_fes,
            )
        else:
            await core.safe_send_response(interaction, "❌ 가챠 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_owner_sekai_bday(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="프로세카 생일 배너 전환"):
            return
        gacha_cog = self._find_cog_with_attr("set_pickup_cmd")
        if gacha_cog:
            choice_bday = app_commands.Choice(name="🎂 생일 / 기념일 스페셜 (생일한정 UP!)", value="birthday")
            await gacha_cog.set_pickup_cmd.callback(
                gacha_cog,
                interaction,
                모드=None,
                유닛=None,
                캐릭터=None,
                한정포함=True,
                배너=choice_bday,
            )
        else:
            await core.safe_send_response(interaction, "❌ 가챠 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_owner_sekai_custom_modal(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="프로세카 수동 픽업 설정"):
            return
        await interaction.response.send_modal(DashboardSekaiOwnerPickupModal(self.bot or interaction.client))

    async def _sub_owner_sekai_select_tickets(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="셀렉트 리스트 특수 티켓 지급·관리"):
            return
        try:
            await core.safe_defer(interaction, ephemeral=True)
            view = gacha.OwnerSelectTicketGrantView(interaction.user)
            msg_obj = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
            view.message = msg_obj
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 셀렉트 티켓 제어판 열기 오류: {e}", ephemeral=True)

    async def _sub_owner_gi_custom_modal(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="원신 수동 픽업 설정"):
            return
        await interaction.response.send_modal(DashboardGenshinOwnerPickupModal(self.bot or interaction.client))

    async def _sub_owner_hsr_custom_modal(self, interaction: discord.Interaction):
        if not await self.check_bot_owner_permission(interaction, action_name="스타레일 수동 픽업 설정"):
            return
        await interaction.response.send_modal(DashboardHSROwnerPickupModal(self.bot or interaction.client))

    async def _act_sekai_register(self, interaction: discord.Interaction):
        try:
            ok, msg, _ = await asyncio.to_thread(
                core.register_proseka_gacha_user, interaction.guild_id or 0, interaction.user.id
            )
            await core.safe_send_response(interaction, f"{'🎉' if ok else 'ℹ️'} {msg}", ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 프로세카 등록 오류: {e}", ephemeral=True)

    async def _act_sekai_pull_hub(self, interaction: discord.Interaction):
        await self._enter_sub_mode(interaction, "sekai_pull_hub")

    async def _sub_sekai_ceiling_exchange(self, interaction: discord.Interaction):
        try:
            if not await gacha.ensure_proseka_registered(interaction):
                return
            await core.safe_defer(interaction)
            view = gacha.GachaCeilingExchangeView(interaction.user, guild_id=interaction.guild_id or 0)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 천장 교환소 열기 오류: {e}", ephemeral=True)

    async def _sub_sekai_select_list(self, interaction: discord.Interaction):
        try:
            if not await gacha.ensure_proseka_registered(interaction):
                return
            await core.safe_defer(interaction)
            view = gacha.SelectListGachaView(interaction.user, guild_id=interaction.guild_id or 0)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 셀렉트 리스트 가챠 열기 오류: {e}", ephemeral=True)

    async def _sub_sekai_destiny_reroll(self, interaction: discord.Interaction):
        gacha_cog = self._find_cog_with_attr("proseka_pull_cmd")
        if gacha_cog:
            choice_dest = app_commands.Choice(name="🔮 운명 다시 뽑기 (1일 1회 · 3세트 중 택1)", value="destiny")
            await gacha_cog.proseka_pull_cmd.callback(gacha_cog, interaction, 횟수=None, 배너=None, 연출=None, 모드=choice_dest)
        else:
            await core.safe_send_response(interaction, "❌ 가챠 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_sekai_reroll_sim(self, interaction: discord.Interaction):
        gacha_cog = self._find_cog_with_attr("proseka_pull_cmd")
        if gacha_cog:
            choice_sim = app_commands.Choice(name="🧪 리세마라 연습 모드 (저장 안 됨 · 무쿨타임)", value="practice")
            await gacha_cog.proseka_pull_cmd.callback(gacha_cog, interaction, 횟수=None, 배너=None, 연출=None, 모드=choice_sim)
        else:
            await core.safe_send_response(interaction, "❌ 가챠 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_sekai_bday_free(self, interaction: discord.Interaction):
        gacha_cog = self._find_cog_with_attr("proseka_pull_cmd")
        if gacha_cog:
            choice_bday = app_commands.Choice(name="🎂 오늘의 생일 무료 단차 (생일 당일 1회)", value="birthday_free")
            await gacha_cog.proseka_pull_cmd.callback(gacha_cog, interaction, 횟수=None, 배너=None, 연출=None, 모드=choice_bday)
        else:
            await core.safe_send_response(interaction, "❌ 가챠 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_sekai_card_search(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DashboardSekaiSearchModal(self.bot or interaction.client))

    async def _act_gi_banner_hub(self, interaction: discord.Interaction):
        await self._enter_sub_mode(interaction, "gi_banner_hub")

    def _make_gi_pull_cb(self, banner_key: str, count: int, practice: bool) -> Callable[[discord.Interaction], Awaitable[None]]:
        async def _cb(interaction: discord.Interaction):
            try:
                pv = genshin.GenshinPullAgainView(
                    interaction.user,
                    banner_key=banner_key,
                    skip_anim=False,
                    practice=practice,
                    last_count=count,
                )
                await pv._run_repull_with_cooldown(interaction, count)
            except Exception as e:
                await core.safe_send_response(interaction, f"❌ 원신 기원 실행 오류: {e}", ephemeral=True)
        return _cb

    async def _act_hsr_banner_hub(self, interaction: discord.Interaction):
        await self._enter_sub_mode(interaction, "hsr_banner_hub")

    def _make_hsr_warp_cb(self, banner_key: str, count: int, practice: bool) -> Callable[[discord.Interaction], Awaitable[None]]:
        async def _cb(interaction: discord.Interaction):
            try:
                wv = hsr.HSRWarpAgainView(
                    interaction.user,
                    banner_key=banner_key,
                    skip_anim=False,
                    practice=practice,
                    last_count=count,
                )
                await wv._run_rewarp_with_cooldown(interaction, count)
            except Exception as e:
                await core.safe_send_response(interaction, f"❌ 스타레일 워프 실행 오류: {e}", ephemeral=True)
        return _cb

    async def _act_life_personal_hub(self, interaction: discord.Interaction):
        await self._enter_sub_mode(interaction, "life_personal_hub")

    async def _sub_life_coop_farm(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            ov = await asyncio.to_thread(
                life_core.get_life_overview,
                interaction.guild_id or 0,
                interaction.user.id,
                interaction.user.display_name,
            )
            view = life.CommunityFarmView(interaction.user, interaction.guild, overview=ov)
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 공동 농장 열기 실패: {e}", ephemeral=True)

    async def _sub_life_pet(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            gid = interaction.guild_id or 0
            ov = await asyncio.to_thread(
                life_core.get_life_overview,
                gid,
                interaction.user.id,
                interaction.user.display_name,
            )
            view = life.PetCareView(interaction.user, gid, overview=ov)
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 펫 돌보기 창 열기 실패: {e}", ephemeral=True)

    async def _sub_life_cook(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            gid = interaction.guild_id or 0
            ov = await asyncio.to_thread(
                life_core.get_life_overview,
                gid,
                interaction.user.id,
                interaction.user.display_name,
            )
            view = life.CookingView(interaction.user, gid, overview=ov)
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 요리 주방 열기 실패: {e}", ephemeral=True)

    async def _sub_life_buffs(self, interaction: discord.Interaction):
        life_cog = self._find_cog_with_attr("life_buffs")
        if life_cog:
            await life_cog.life_buffs.callback(life_cog, interaction)
        else:
            await core.safe_send_response(interaction, "❌ 생활 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_gi_profile(self, interaction: discord.Interaction):
        bot_ref = self.bot or interaction.client
        gi_cog = bot_ref.get_cog("GenshinCog") if bot_ref else None
        if gi_cog and hasattr(gi_cog, "profile_cmd"):
            await gi_cog.profile_cmd.callback(gi_cog, interaction, 대상=None, 대표캐릭터=None, 상태문구=None)
        else:
            await core.safe_send_response(interaction, "❌ 원신 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_gi_profile_edit(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DashboardGenshinProfileModal(self.bot or interaction.client))

    async def _sub_hsr_profile(self, interaction: discord.Interaction):
        bot_ref = self.bot or interaction.client
        hsr_cog = bot_ref.get_cog("HSRCog") if bot_ref else None
        if hsr_cog and hasattr(hsr_cog, "profile_cmd"):
            await hsr_cog.profile_cmd.callback(hsr_cog, interaction, 대상=None, 대표캐릭터=None, 상태문구=None)
        else:
            await core.safe_send_response(interaction, "❌ 스타레일 모듈을 찾을 수 없습니다.", ephemeral=True)

    async def _sub_hsr_profile_edit(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DashboardHSRProfileModal(self.bot or interaction.client))

    async def _sub_fishing_env(self, interaction: discord.Interaction):
        fishing_cog = self._find_cog_with_attr("fishing_env_cmd")
        if fishing_cog:
            await fishing_cog.fishing_env_cmd.callback(fishing_cog, interaction)
        else:
            await core.safe_send_response(interaction, "❌ 낚시 모듈을 찾을 수 없습니다.", ephemeral=True)

    # ----------------------------------------------------
    # ☀️ 일일 루틴 · 주간 미션 · 환전소 · 쇼케이스 · 파트너 농장 · 즉석 미니 대전
    # ----------------------------------------------------
    async def _act_daily_routine(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            gid = interaction.guild_id or 0
            st = await asyncio.to_thread(
                routine_core.get_daily_routine_status, gid, interaction.user.id, interaction.user.display_name
            )
            view = routine.DailyRoutineHubView(self.bot or interaction.client, interaction.user, gid, status=st)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 일일 루틴 허브 로드 오류: {e}", ephemeral=True)

    async def _act_weekly_missions(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            gid = interaction.guild_id or 0
            view = routine.WeeklyMissionView(interaction.user, gid)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 주간 미션 보드 로드 오류: {e}", ephemeral=True)

    async def _act_currency_exchange(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            gid = interaction.guild_id or 0
            view = routine.CurrencyExchangeView(interaction.user, gid)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 환전소 로드 오류: {e}", ephemeral=True)

    async def _act_showcase(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            gid = interaction.guild_id or 0
            view = routine.ShowcaseView(interaction.user, gid)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 수집품 쇼케이스 로드 오류: {e}", ephemeral=True)

    async def _act_partner_farm_water(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            gid = interaction.guild_id or 0
            ok, msg = await asyncio.to_thread(
                routine_core.water_partner_farm, gid, interaction.user.id, interaction.user.display_name
            )
            await interaction.followup.send(msg, ephemeral=not ok)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 파트너 농장 물주기 오류: {e}", ephemeral=True)

    async def _act_mini_battle_hub(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            view = routine.MiniBattleHubView(interaction.user)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 즉석 미니 대전 로드 오류: {e}", ephemeral=True)


# 외부 참조용 별칭
SettingsHubView = MasterDashboardView
core.SAFE_VIEW_REGISTRY["Settings"] = MasterDashboardView


# ==========================================
# 🚀 Dashboard (설정) Cog 메인 클래스
# ==========================================
class Dashboard(commands.Cog, name="설정"):
    """norosi 봇의 모든 기능을 [일반 · 고급 · 미니게임 · 개인] 4대 카테고리와 통합 페이지네이션으로 제어하는 모듈"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    _CATEGORY_ALIASES = {
        "home": "home", "홈": "home", "메인": "home",
        "general": "general", "일반": "general",
        "advanced": "advanced", "고급": "advanced", "관리자": "advanced",
        "minigame": "minigame", "미니게임": "minigame", "게임": "minigame",
        "personal": "personal", "개인": "personal",
        "ranking": "ranking", "랭킹": "ranking", "순위": "ranking",
        "pokedex": "pokedex", "도감": "pokedex", "확률": "pokedex",
    }

    @app_commands.command(
        name="설정",
        description="⚙️ [일반 · 고급 · 미니게임 · 개인] 4대 카테고리 및 키워드 검색으로 모든 봇 기능을 제어합니다.",
    )
    @app_commands.describe(
        카테고리="바로 진입할 카테고리 선택 (미선택 시 4대 카테고리 홈 화면 열림)",
        검색="찾고 싶은 기능 키워드 입력 시 원클릭 실행 버튼 표시 (예: 로그, 환전, 일일루틴, 라디오, 복권)",
    )
    @app_commands.choices(
        카테고리=[
            app_commands.Choice(name="🏠 [홈] 통합 설정 메인 (일반·고급·미니게임·개인)", value="home"),
            app_commands.Choice(name="🌐 [일반] 출석·일정·음악·날씨·통계·모집 (3페이지)", value="general"),
            app_commands.Choice(name="⚙️ [고급] 서버 관리자 & 봇 주인 전용 설정 (4페이지)", value="advanced"),
            app_commands.Choice(name="🎮 [미니게임] 프로세카·원신·스타레일·낚시·농장·게임 (4페이지)", value="minigame"),
            app_commands.Choice(name="👤 [개인] 프로필·보관함·목표·루틴·환전·대전 (4페이지)", value="personal"),
            app_commands.Choice(name="🏆 [랭킹] 전 분야 서버 통합 랭킹 보드 바로가기 (8종)", value="ranking"),
            app_commands.Choice(name="📖 [도감] 5대 게임 통합 도감 & 배너 확률표 바로가기", value="pokedex"),
        ]
    )
    async def slash_settings(
        self,
        interaction: discord.Interaction,
        카테고리: Optional[app_commands.Choice[str]] = None,
        검색: Optional[str] = None,
    ):
        kw_clean = (검색 or "").strip()
        if kw_clean:
            await core.safe_defer(interaction, ephemeral=True)
            data = await asyncio.to_thread(core.load_data)
            dash_view = MasterDashboardView(
                bot=self.bot,
                user=interaction.user,
                guild=interaction.guild,
                data=data,
                initial_tab="home",
            )
            matches = search_dashboard_features(dash_view, kw_clean)
            s_view = DashboardSearchResultView(dash_view, kw_clean, matches, owner_id=interaction.user.id)
            await interaction.followup.send(embed=s_view.build_embed(), view=s_view, ephemeral=True, wait=True)
            return

        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        init_cat = 카테고리.value if 카테고리 else "home"
        view = MasterDashboardView(
            bot=self.bot,
            user=interaction.user,
            guild=interaction.guild,
            data=data,
            initial_tab=init_cat,
        )
        msg = await interaction.followup.send(embed=view.build_current_embed(), view=view, wait=True)
        view.message = msg

async def setup(bot: commands.Bot):
    await bot.add_cog(Dashboard(bot))
