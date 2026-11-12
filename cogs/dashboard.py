"""
norosi Bot - 올인원 마스터 대시보드 (All-in-One Master Dashboard) Cog
- 7대 핵심 기능 영역(홈, 가챠, 일정, 음악, 역할·관리, 게임, 통계)을 탭(Tab)으로 자유롭게 오가는 슈퍼 컨트롤 타워
- 모든 상호작용(모달/뷰/슬래시 콜백) 시그니처 불일치 버그 완벽 해결본
"""

import asyncio
import datetime
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import core
from cogs import dday, gacha, music, roles, stats, logger


# ==========================================
# 📝 대시보드 전용 모달: 빠른 D-Day 등록
# ==========================================
class DashboardDDayAddModal(core.SafeModal, title="📅 새 D-Day 일정 등록"):
    d_name = discord.ui.TextInput(
        label="D-Day 일정 이름",
        placeholder="예: 기말고사, 프로세카 이벤트 마감, 생일, 기념일",
        required=True,
        max_length=50
    )
    d_date = discord.ui.TextInput(
        label="목표 날짜 (YYYY-MM-DD)",
        placeholder="예: 2026-11-20",
        required=True,
        max_length=10
    )
    d_start = discord.ui.TextInput(
        label="진행률 시작일 (YYYY-MM-DD, 비워두면 오늘)",
        placeholder="예: 2026-11-01 (은하수 잔디 진행률 0% 기준일)",
        required=False,
        max_length=10
    )
    d_emoji = discord.ui.TextInput(
        label="대표 이모지 (기본: 🌠)",
        placeholder="예: 🌠, 🔥, 🎶, 🎯, 🎂",
        required=False,
        default="🌠",
        max_length=5
    )

    def __init__(self, dashboard_view: "MasterDashboardView"):
        super().__init__()
        self.dashboard_view = dashboard_view

    async def on_submit(self, interaction: discord.Interaction):
        target_val = self.d_date.value.strip()
        start_val = self.d_start.value.strip() or core.get_today_str()
        try:
            target_dt = datetime.datetime.strptime(target_val, "%Y-%m-%d").date()
            start_dt = datetime.datetime.strptime(start_val, "%Y-%m-%d").date()
        except ValueError:
            await core.safe_send_response(interaction, "❌ 날짜 형식은 `YYYY-MM-DD` (예: `2026-11-20`)로 입력해 주세요.", ephemeral=True)
            return

        if start_dt > target_dt:
            start_val = min(core.get_today_str(), target_val)

        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        name_val = self.d_name.value.strip()
        emoji_val = (self.d_emoji.value.strip() or "🌠")

        existing = data.setdefault("ddays", {}).get(name_val, {})
        data["ddays"][name_val] = {
            "date": target_val,
            "repeat": existing.get("repeat", False),
            "start_date": start_val,
            "emoji": emoji_val,
            "channel_id": existing.get("channel_id"),
            "category_id": existing.get("category_id")
        }
        await asyncio.to_thread(core.save_data, data)

        if hasattr(self.dashboard_view.bot, "update_all_dday_channels"):
            try:
                await self.dashboard_view.bot.update_all_dday_channels()
            except Exception:
                pass

        _, diff_str = core.get_dday_info(target_val)
        await interaction.followup.send(
            f"🎉 **새 D-Day 일정이 성공적으로 등록되었습니다!**\n"
            f"• **일정:** {emoji_val} **`{name_val}`**\n"
            f"• **목표일:** `{target_val}` (**`{diff_str}`**)\n"
            f"• 대시보드의 `[🔄 새로고침]` 버튼을 누르면 현황판에 즉시 반영됩니다.",
            ephemeral=True
        )


# ==========================================
# ⏱️ 대시보드 전용 모달: 뽀모도로 타이머 설정
# ==========================================
class DashboardPomodoroModal(core.SafeModal, title="⏳ 뽀모도로 집중모드 타이머 설정"):
    focus_time = discord.ui.TextInput(
        label="집중 시간 (분 단위, 1~180분)",
        placeholder="기본값: 25",
        default="25",
        required=True,
        max_length=3
    )
    rest_time = discord.ui.TextInput(
        label="휴식 시간 (분 단위, 1~60분)",
        placeholder="기본값: 5",
        default="5",
        required=True,
        max_length=2
    )
    sets_count = discord.ui.TextInput(
        label="반복 세트 수 (1~10세트)",
        placeholder="기본값: 1",
        default="1",
        required=True,
        max_length=2
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        try:
            f_min = int(self.focus_time.value.strip())
            r_min = int(self.rest_time.value.strip())
            s_cnt = int(self.sets_count.value.strip())
        except ValueError:
            await core.safe_send_response(interaction, "❌ 시간과 세트 수는 정수 숫자로만 입력해 주세요.", ephemeral=True)
            return

        f_min = max(1, min(180, f_min))
        r_min = max(1, min(60, r_min))
        s_cnt = max(1, min(10, s_cnt))

        target_cog = next((c for c in self.bot.cogs.values() if hasattr(c, "pomodoro_cmd")), None)
        if target_cog:
            choice_start = app_commands.Choice(name="🔥 집중모드 시작", value="start")
            await target_cog.pomodoro_cmd.callback(
                target_cog,
                interaction,
                동작=choice_start,
                집중시간=f_min,
                휴식시간=r_min,
                세트수=s_cnt,
                음성채널=None
            )
        else:
            await core.safe_send_response(interaction, "❌ 집중모드 모듈을 찾을 수 없습니다. `/집중모드` 명령어를 이용해 주세요.", ephemeral=True)


# ==========================================
# 👻 대시보드 전용 모달: 비활성 유저 기준일수 입력
# ==========================================
class DashboardInactiveAuditModal(core.SafeModal, title="👻 비활성(잠수) 유저 스캔"):
    days_input = discord.ui.TextInput(
        label="미활동 기준 일수 (7 / 14 / 30 / 60 / 90)",
        placeholder="예: 30 (최근 30일 이상 무활동 멤버 스캔)",
        default="30",
        required=True,
        max_length=3
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.days_input.value.strip()
        days_val = int(raw) if raw.isdigit() else 30
        days_val = max(1, min(365, days_val))

        logger_cog = next((c for c in self.bot.cogs.values() if hasattr(c, "inactive_users_cmd")), None)
        if logger_cog:
            choice_obj = app_commands.Choice(name=f"⏳ 최근 {days_val}일 이상 미활동", value=days_val)
            await logger_cog.inactive_users_cmd.callback(logger_cog, interaction, 기준일수=choice_obj)
        else:
            await core.safe_send_response(interaction, "❌ 감사 로그 모듈을 찾을 수 없습니다. `/비활성유저조회` 명령어를 이용해 주세요.", ephemeral=True)


# ==========================================
# 🧭 마스터 대시보드 카테고리 네비게이션 드롭다운
# ==========================================
class DashboardTabSelect(discord.ui.Select):
    def __init__(self, current_tab: str = "home"):
        options = [
            discord.SelectOption(
                label="🧭 종합 관제 대시보드",
                value="home",
                description="내 출석, 크리스탈, 오시, D-Day, 오늘 목표 한눈에 보기",
                emoji="🧭",
                default=(current_tab == "home")
            ),
            discord.SelectOption(
                label="🎮 카드·뽑기·덱 대시보드",
                value="gacha",
                description="10회/1회 가챠, 보관함, 중복 변환, 덱 편성, 카드 도감",
                emoji="🎮",
                default=(current_tab == "gacha")
            ),
            discord.SelectOption(
                label="📅 D-Day·생일·집중 대시보드",
                value="life",
                description="D-Day 현황, 생일 전광판, 뽀모도로 타이머, 파트너, 미래시",
                emoji="📅",
                default=(current_tab == "life")
            ),
            discord.SelectOption(
                label="🎵 플레이리스트·사운드 대시보드",
                value="music",
                description="내 플리 관리, 감성 추천곡 선곡, 오디오 진단, 볼륨 제어",
                emoji="🎵",
                default=(current_tab == "music")
            ),
            discord.SelectOption(
                label="🎭 역할버튼·공지·서버관리 대시보드",
                value="admin",
                description="사진 스타일 역할 버튼 제작, 반응역할 스튜디오, 공지 발송",
                emoji="🎭",
                default=(current_tab == "admin")
            ),
            discord.SelectOption(
                label="🎲 미니게임·모집·날씨 대시보드",
                value="game",
                description="파티원 모집, 끝말잇기, 러시안룰렛, 실시간 날씨, 알림 예약",
                emoji="🎲",
                default=(current_tab == "game")
            ),
            discord.SelectOption(
                label="📊 서버통계·유저정보 대시보드",
                value="stats",
                description="서버 실시간 통계 보드, 내 활동량 정보, 봇 상태, 건의함",
                emoji="📊",
                default=(current_tab == "stats")
            ),
        ]
        super().__init__(
            placeholder="🔍 이동할 기능 대시보드를 선택하세요...",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        view: "MasterDashboardView" = self.view
        selected_tab = self.values[0]
        view.current_tab = selected_tab
        view.refresh_components()
        embed = view.build_current_embed()
        await interaction.response.edit_message(embed=embed, view=view)


# ==========================================
# 🎛️ 올인원 마스터 대시보드 뷰 (MasterDashboardView)
# ==========================================
class MasterDashboardView(core.SafeView):
    """norosi 봇의 모든 기능을 통합 제어하는 슈퍼 대시보드 뷰"""

    def __init__(self, bot: commands.Bot, user: discord.Member, guild: Optional[discord.Guild], data: dict, initial_tab: str = "home"):
        super().__init__(timeout=600)
        self.bot = bot
        self.user = user
        self.guild = guild
        self.data = data
        self.current_tab = initial_tab
        self.refresh_components()

    def _find_cog_with_attr(self, attr_name: str):
        for cog in self.bot.cogs.values():
            if hasattr(cog, attr_name):
                return cog
        return None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await super().interaction_check(interaction)
        if interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 대시보드는 **{self.user.display_name}**님의 개인 세션입니다. 본인의 대시보드는 `/대시보드` 또는 `/메뉴`로 열어주세요!",
                ephemeral=True
            )
            return False
        return True

    async def check_admin_permission(self, interaction: discord.Interaction, action_name: str = "이 작업", require_roles_perm: bool = False) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await core.safe_send_response(
                interaction,
                f"❌ **{action_name}**(은)는 개인 DM이 아닌 **디스코드 서버 채널** 내에서만 실행하실 수 있습니다.",
                ephemeral=True
            )
            return False

        is_owner = await self.bot.is_bot_owner_user(interaction.user)
        user_perms = interaction.user.guild_permissions
        is_admin = is_owner or user_perms.administrator or user_perms.manage_guild or (require_roles_perm and user_perms.manage_roles)

        if not is_admin:
            role_hint = "역할 관리(Manage Roles) 또는 " if require_roles_perm else ""
            await core.safe_send_response(
                interaction,
                f"🚨 **관리자 권한 부족:** **{action_name}**(은)는 서버의 **{role_hint}관리자(Administrator)** 또는 **서버 관리(Manage Server)** 권한이 있는 멤버만 조작할 수 있습니다.",
                ephemeral=True
            )
            return False

        if require_roles_perm and interaction.guild.me:
            bot_perms = interaction.guild.me.guild_permissions
            if not bot_perms.administrator and not bot_perms.manage_roles:
                await core.safe_send_response(
                    interaction,
                    "⚠️ **봇 권한 부족:** 봇에게 **역할 관리(Manage Roles)** 권한이 부여되어 있지 않아 역할을 지급하거나 버튼을 만들 수 없습니다.\n"
                    "👉 서버 설정 > [역할] 메뉴에서 `norosi` 봇 역할에 **'역할 관리'** 권한을 체크해 주세요!",
                    ephemeral=True
                )
                return False

        return True

    def refresh_components(self):
        self.clear_items()
        self.add_item(DashboardTabSelect(self.current_tab))

        if self.current_tab == "home":
            self._setup_home_buttons()
        elif self.current_tab == "gacha":
            self._setup_gacha_buttons()
        elif self.current_tab == "life":
            self._setup_life_buttons()
        elif self.current_tab == "music":
            self._setup_music_buttons()
        elif self.current_tab == "admin":
            self._setup_admin_buttons()
        elif self.current_tab == "game":
            self._setup_game_buttons()
        elif self.current_tab == "stats":
            self._setup_stats_buttons()

        btn_refresh = discord.ui.Button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=2)
        btn_refresh.callback = self._on_refresh_clicked
        self.add_item(btn_refresh)

    def _setup_home_buttons(self):
        btn_att = discord.ui.Button(label="📅 즉시 출석체크", style=discord.ButtonStyle.primary, row=1)
        btn_att.callback = self._on_attendance_clicked
        self.add_item(btn_att)

        btn_pull = discord.ui.Button(label="🎰 10회 뽑기", style=discord.ButtonStyle.success, row=1)
        btn_pull.callback = self._on_pull_10_clicked
        self.add_item(btn_pull)

        btn_todo = discord.ui.Button(label="🌱 오늘 목표 체크", style=discord.ButtonStyle.secondary, row=1)
        btn_todo.callback = self._on_todo_clicked
        self.add_item(btn_todo)

        btn_dup = discord.ui.Button(label="💎 중복 일괄 환전", style=discord.ButtonStyle.secondary, row=1)
        btn_dup.callback = self._on_dup_convert_clicked
        self.add_item(btn_dup)

        btn_music = discord.ui.Button(label="🎧 감성 음악 추천", style=discord.ButtonStyle.secondary, row=2)
        btn_music.callback = self._on_music_now_clicked
        self.add_item(btn_music)

    def _setup_gacha_buttons(self):
        btn_p10 = discord.ui.Button(label="🌈 10회 뽑기", style=discord.ButtonStyle.success, row=1)
        btn_p10.callback = self._on_pull_10_clicked
        self.add_item(btn_p10)

        btn_p1 = discord.ui.Button(label="🎲 1회 뽑기", style=discord.ButtonStyle.success, row=1)
        btn_p1.callback = self._on_pull_1_clicked
        self.add_item(btn_p1)

        btn_inv = discord.ui.Button(label="🎒 내 보관함", style=discord.ButtonStyle.primary, row=1)
        btn_inv.callback = self._on_my_inventory_clicked
        self.add_item(btn_inv)

        btn_dup = discord.ui.Button(label="💎 중복 일괄 환전", style=discord.ButtonStyle.secondary, row=1)
        btn_dup.callback = self._on_dup_convert_clicked
        self.add_item(btn_dup)

        btn_deck = discord.ui.Button(label="🎴 덱 편성 현황", style=discord.ButtonStyle.primary, row=2)
        btn_deck.callback = self._on_deck_edit_clicked
        self.add_item(btn_deck)

        btn_pokedex = discord.ui.Button(label="📖 카드 도감", style=discord.ButtonStyle.secondary, row=2)
        btn_pokedex.callback = self._on_pokedex_clicked
        self.add_item(btn_pokedex)

        btn_rank = discord.ui.Button(label="🏆 가챠 랭킹", style=discord.ButtonStyle.secondary, row=2)
        btn_rank.callback = self._on_gacha_rank_clicked
        self.add_item(btn_rank)

    def _setup_life_buttons(self):
        btn_add_dday = discord.ui.Button(label="➕ 새 D-Day 등록", style=discord.ButtonStyle.primary, row=1)
        btn_add_dday.callback = self._on_add_dday_clicked
        self.add_item(btn_add_dday)

        btn_dday_list = discord.ui.Button(label="📋 D-Day 전체 목록", style=discord.ButtonStyle.secondary, row=1)
        btn_dday_list.callback = self._on_dday_list_clicked
        self.add_item(btn_dday_list)

        btn_bday = discord.ui.Button(label="🎂 멤버 생일 전광판", style=discord.ButtonStyle.secondary, row=1)
        btn_bday.callback = self._on_birthday_clicked
        self.add_item(btn_bday)

        btn_pomo = discord.ui.Button(label="⏳ 뽀모도로 집중모드", style=discord.ButtonStyle.primary, row=1)
        btn_pomo.callback = self._on_pomodoro_clicked
        self.add_item(btn_pomo)

        btn_partner = discord.ui.Button(label="💑 파트너 관리", style=discord.ButtonStyle.secondary, row=2)
        btn_partner.callback = self._on_partner_clicked
        self.add_item(btn_partner)

        btn_forecast = discord.ui.Button(label="📅 미래시 달력", style=discord.ButtonStyle.secondary, row=2)
        btn_forecast.callback = self._on_forecast_clicked
        self.add_item(btn_forecast)

    def _setup_music_buttons(self):
        btn_pl = discord.ui.Button(label="💿 플레이리스트 스튜디오", style=discord.ButtonStyle.primary, row=1)
        btn_pl.callback = self._on_playlist_studio_clicked
        self.add_item(btn_pl)

        btn_rec = discord.ui.Button(label="🎲 감성 음악 선곡", style=discord.ButtonStyle.success, row=1)
        btn_rec.callback = self._on_music_now_clicked
        self.add_item(btn_rec)

        btn_audio = discord.ui.Button(label="🔊 440Hz 오디오 자가진단", style=discord.ButtonStyle.secondary, row=1)
        btn_audio.callback = self._on_audio_test_clicked
        self.add_item(btn_audio)

    def _setup_admin_buttons(self):
        btn_quick_btn = discord.ui.Button(label="🚀 사진 스타일 역할버튼 제작", style=discord.ButtonStyle.primary, emoji="🚀", row=1)
        btn_quick_btn.callback = self._on_quick_role_btn_clicked
        self.add_item(btn_quick_btn)

        btn_studio = discord.ui.Button(label="🎭 반응역할 종합 스튜디오", style=discord.ButtonStyle.secondary, row=1)
        btn_studio.callback = self._on_role_studio_clicked
        self.add_item(btn_studio)

        btn_notice = discord.ui.Button(label="📢 스마트 공지 발송", style=discord.ButtonStyle.secondary, row=1)
        btn_notice.callback = self._on_announcement_clicked
        self.add_item(btn_notice)

        btn_audit = discord.ui.Button(label="🛡️ 비활성 유저 감사", style=discord.ButtonStyle.secondary, row=2)
        btn_audit.callback = self._on_inactive_audit_clicked
        self.add_item(btn_audit)

    def _setup_game_buttons(self):
        btn_recruit = discord.ui.Button(label="🎮 파티/팀원 모집", style=discord.ButtonStyle.primary, row=1)
        btn_recruit.callback = self._on_recruit_clicked
        self.add_item(btn_recruit)

        btn_word = discord.ui.Button(label="🔤 끝말잇기 시작", style=discord.ButtonStyle.success, row=1)
        btn_word.callback = self._on_word_chain_clicked
        self.add_item(btn_word)

        btn_roulette = discord.ui.Button(label="🔫 러시안룰렛", style=discord.ButtonStyle.danger, row=1)
        btn_roulette.callback = self._on_roulette_clicked
        self.add_item(btn_roulette)

        btn_weather = discord.ui.Button(label="🌤️ 실시간 날씨", style=discord.ButtonStyle.secondary, row=1)
        btn_weather.callback = self._on_weather_clicked
        self.add_item(btn_weather)

        btn_remind = discord.ui.Button(label="⏰ 스마트 알림 예약", style=discord.ButtonStyle.secondary, row=2)
        btn_remind.callback = self._on_remind_clicked
        self.add_item(btn_remind)

    def _setup_stats_buttons(self):
        btn_sstats = discord.ui.Button(label="📊 서버 실시간 통계", style=discord.ButtonStyle.primary, row=1)
        btn_sstats.callback = self._on_server_stats_clicked
        self.add_item(btn_sstats)

        btn_uinfo = discord.ui.Button(label="🪪 내 상세 유저정보", style=discord.ButtonStyle.secondary, row=1)
        btn_uinfo.callback = self._on_user_info_clicked
        self.add_item(btn_uinfo)

        btn_bstat = discord.ui.Button(label="🤖 봇 호스트 상태", style=discord.ButtonStyle.secondary, row=1)
        btn_bstat.callback = self._on_bot_status_clicked
        self.add_item(btn_bstat)

        btn_sugg = discord.ui.Button(label="📬 건의사항 보내기", style=discord.ButtonStyle.secondary, row=2)
        btn_sugg.callback = self._on_suggestion_clicked
        self.add_item(btn_sugg)

    # ----------------------------------------------------
    # 탭별 대시보드 임베드 빌더
    # ----------------------------------------------------
    def build_current_embed(self) -> discord.Embed:
        if self.current_tab == "home":
            return self.build_home_embed()
        elif self.current_tab == "gacha":
            return self.build_gacha_embed()
        elif self.current_tab == "life":
            return self.build_life_embed()
        elif self.current_tab == "music":
            return self.build_music_embed()
        elif self.current_tab == "admin":
            return self.build_admin_embed()
        elif self.current_tab == "game":
            return self.build_game_embed()
        elif self.current_tab == "stats":
            return self.build_stats_embed()
        return self.build_home_embed()

    def build_home_embed(self) -> discord.Embed:
        g_key = str(self.guild.id if self.guild else 0)
        u_key = str(self.user.id)
        today_str = core.get_today_str()

        profile = core.ensure_user_profile(self.data, u_key, self.user.display_name)
        guild_att = self.data.get("guild_attendance", {}).get(g_key, {}).get(u_key, {})
        checked_today = (guild_att.get("last_date") == today_str)

        crystals = profile.get("crystals", 0)
        oshi_name = profile.get("oshi") or "미설정 (`/오시설정`)"
        partner_id = profile.get("partner_id")
        partner_tag = f"<@{partner_id}>" if partner_id else "미등록 (`/파트너`)"

        todo = core.ensure_user_todo_today(profile)
        tasks_list = todo.get("tasks", [])
        done_cnt = sum(1 for t in tasks_list if t.get("done"))
        tot_cnt = len(tasks_list)
        grass_bar, _ = core.get_todo_galaxy_grass(profile)

        user_cards = self.data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})
        unique_cnt = len(user_cards)
        dup_excess = sum(max(0, c.get("count", 1) - 1) for c in user_cards.values() if not c.get("locked", False))

        ddays_dict = self.data.get("ddays", {})
        nearest_dday_str = "등록된 일정 없음 (`/디데이추가`)"
        upcoming = []
        for d_name, d_info in ddays_dict.items():
            date_val = d_info.get("date")
            if not date_val:
                continue
            try:
                diff, d_txt = core.get_dday_info(date_val)
                if diff >= 0:
                    upcoming.append((diff, d_name, date_val, d_txt))
            except Exception:
                continue
        if upcoming:
            upcoming.sort(key=lambda x: x[0])
            _, n_name, n_date, n_txt = upcoming[0]
            nearest_dday_str = f"**{n_name}** (`{n_date}` · **`{n_txt}`**)"

        guild_label = self.guild.name if self.guild else "개인 메시지(DM)"
        ms_bonus = core.get_my_sekai_daily_bonus(profile)
        att_badge = (
            f"✅ **오늘 출석 완료** (연속 `{guild_att.get('streak', 1)}일 🔥` / 누적 `{guild_att.get('total_days', 1)}일`)"
            if checked_today else
            f"⬜ **오늘 미출석** (`[📅 즉시 출석체크]` 버튼으로 `+{100 + ms_bonus}💎` 받기!)"
        )

        embed = discord.Embed(
            title=f"🧭 {self.user.display_name}님의 norosi 종합 관제 대시보드",
            description=(
                "norosi 봇의 모든 기능을 한곳에서 시각적으로 제어할 수 있는 올인원 마스터 컨트롤 타워입니다.\n"
                "**상단 드롭다운**을 눌러 기능 탭을 전환하거나 **하단 핫키 버튼**으로 즉시 실행하세요!\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **🏠 `{guild_label}` 출석:** {att_badge}\n"
                f"• **💎 보유 크리스탈:** **`{crystals:,}개`** (마이세카이 일일 보너스 `+{ms_bonus}💎`)\n"
                f"• **💖 오시 캐릭터:** `{oshi_name}`  ·  **💑 파트너:** {partner_tag}\n"
                f"• **🎒 보유 캐릭터:** `{unique_cnt:,}종` (환전 가능 중복: `{dup_excess:,}장`)\n"
                f"• **📅 가장 가까운 D-Day:** {nearest_dday_str}\n"
                f"• **🌱 오늘 목표 달성률 (`{done_cnt}/{tot_cnt}`):** {grass_bar}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_thumbnail(url=self.user.display_avatar.url)
        embed.set_footer(text="💡 상단 드롭다운에서 가챠, 일정, 음악, 역할, 게임, 통계 대시보드로 이동할 수 있습니다.")
        return embed

    def build_gacha_embed(self) -> discord.Embed:
        g_key = str(self.guild.id if self.guild else 0)
        u_key = str(self.user.id)
        profile = core.ensure_user_profile(self.data, u_key, self.user.display_name)
        crystals = profile.get("crystals", 0)

        user_cards = self.data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})
        total_unique = len(user_cards)
        total_cards_count = sum(c.get("count", 1) for c in user_cards.values())
        dup_excess = sum(max(0, c.get("count", 1) - 1) for c in user_cards.values() if not c.get("locked", False))

        four_stars = sum(1 for c in user_cards.values() if c.get("rarity_type") == "rarity_4")
        birthdays = sum(1 for c in user_cards.values() if c.get("rarity_type") == "rarity_birthday")

        deck = profile.get("deck", [])
        deck_str = ", ".join(f"`{cid}`" for cid in deck) if deck else "편성된 덱 없음 (`/덱편성`)"

        embed = discord.Embed(
            title="🎮 프로세카 카드 & 가챠 대시보드",
            description=(
                f"**{self.user.display_name}**님의 카드 컬렉션 및 뽑기 종합 현황입니다.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **💎 보유 크리스탈:** **`{crystals:,}개`**\n"
                f"• **🎒 보유 카드 현황:** 총 `{total_cards_count:,}장` (고유 수집: `{total_unique:,}종`)\n"
                f"• **🌟 최고 희귀도 보유:** ★4 카드 **`{four_stars}장`**  ·  🎂 생일 카드 **`{birthdays}장`**\n"
                f"• **💎 환전 가능 중복:** **`{dup_excess}장`** *(아래 `[💎 중복 일괄 환전]` 버튼으로 크리스탈 수령)*\n"
                f"• **🎴 현재 편성 덱:** {deck_str}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.from_rgb(235, 69, 158),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text="버튼을 눌러 10회 뽑기, 보관함, 중복 환전, 덱 편성, 도감을 바로 실행하세요!")
        return embed

    def build_life_embed(self) -> discord.Embed:
        ddays_dict = self.data.get("ddays", {})
        active_cnt = len(ddays_dict)

        lines = []
        for name, info in list(ddays_dict.items())[:5]:
            d_val = info.get("date")
            try:
                _, d_txt = core.get_dday_info(d_val)
                lines.append(f"• **{name}** (`{d_val}`): **`{d_txt}`**")
            except Exception:
                pass
        dday_summary = "\n".join(lines) if lines else "*(등록된 D-Day 일정이 없습니다)*"

        bdays = self.data.get("birthdays", {})
        now = datetime.datetime.now(core.KST)
        this_month_bdays = []
        for uid_s, binfo in bdays.items():
            b_mm = binfo.get("month")
            b_dd = binfo.get("day")
            if b_mm == now.month:
                this_month_bdays.append(f"<@{uid_s}> ({b_mm}월 {b_dd}일)")
        bday_summary = ", ".join(this_month_bdays[:6]) if this_month_bdays else f"*(이번 {now.month}월 생일자 없음)*"

        embed = discord.Embed(
            title="📅 라이프 & D-Day & 집중 대시보드",
            description=(
                "서버의 모든 기념일, 시험, 생일 전광판 및 뽀모도로 집중모드를 제어합니다.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **📌 등록된 D-Day 전광판:** 총 `{active_cnt}개`\n"
                f"{dday_summary}\n\n"
                f"• **🎂 이번 {now.month}월 생일 멤버:**\n"
                f"{bday_summary}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.from_rgb(87, 242, 135),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text="D-Day 추가/목록, 생일 등록, 뽀모도로 타이머, 파트너 관리를 버튼으로 실행하세요!")
        return embed

    def build_music_embed(self) -> discord.Embed:
        u_key = str(self.user.id)
        profile = core.ensure_user_profile(self.data, u_key, self.user.display_name)
        u_pls = core.ensure_user_playlists(profile, self.user.display_name)
        tot_tracks = sum(len(p.get("tracks", [])) for p in u_pls if isinstance(p, dict))

        vc_status = "❌ 미연결 (대기 중)"
        if self.guild and self.guild.voice_client:
            vc = self.guild.voice_client
            if vc.is_playing():
                vc_status = f"🎶 재생 중 (채널: `{vc.channel.name}`)"
            else:
                vc_status = f"⏸️ 연결 대기 (채널: `{vc.channel.name}`)"

        embed = discord.Embed(
            title="🎵 음악 & 플레이리스트 대시보드",
            description=(
                "유튜브·스포티파이·사운드클라우드 기반 나만의 플레이리스트 및 고음질 음성 컨트롤 허브입니다.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **💿 내 플레이리스트:** **`{len(u_pls)}개`** (총 수록곡: `{tot_tracks}곡`)\n"
                f"• **🔊 현재 음성 연결 상태:** {vc_status}\n"
                "• **🎧 지원 플랫폼:** YouTube, Spotify, SoundCloud, MP3 직링크\n"
                "• **🛡️ DAVE 음성 엔진:** Discord Audio/Video End-to-End Encryption 최신 표준 적용\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.from_rgb(155, 89, 182),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text="플레이리스트 스튜디오, 감성 음악 추천, 440Hz 오디오 진단을 즉시 실행하세요!")
        return embed

    def build_admin_embed(self) -> discord.Embed:
        guild_id = self.guild.id if self.guild else 0
        guild_rr = core.get_guild_reaction_roles(self.data, guild_id)
        total_panels = len(guild_rr)
        total_roles = sum(len(c.get("roles", [])) for c in guild_rr.values())

        is_admin = False
        is_bot_ready = False
        if self.guild and isinstance(self.user, discord.Member):
            is_admin = (
                self.user.guild_permissions.administrator or
                self.user.guild_permissions.manage_roles or
                self.user.guild_permissions.manage_guild
            )
            if self.guild.me:
                is_bot_ready = self.guild.me.guild_permissions.manage_roles or self.guild.me.guild_permissions.administrator

        admin_badge = "✅ **관리자 권한 보유** (모든 설정 조작 가능)" if is_admin else "⚠️ **일반 멤버** (관리자 전용 기능 조작 제한)"
        bot_badge = "✅ **정상 가동 중** (Manage Roles 보유)" if is_bot_ready else "⚠️ **권한 부족** (봇에게 '역할 관리' 권한 필요)"

        embed = discord.Embed(
            title="🎭 역할 & 공지 & 서버 관리 대시보드",
            description=(
                "사진 스타일 맞춤 역할 버튼 제작, 이모지 반응역할 및 스마트 공지를 관리합니다.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **🛡️ 내 관리 권한:** {admin_badge}\n"
                f"• **🤖 봇 역할 권한:** {bot_badge}\n"
                f"• **📜 등록된 반응역할/버튼 패널:** **`{total_panels}개`**\n"
                f"• **🏷️ 자동 배정 중인 역할 총합:** **`{total_roles}개`**\n"
                "• **✨ 추천 기능:**\n"
                "  - **`[🚀 사진 스타일 역할버튼 제작]`** : 제목/본문/버튼이름/이모지를 자유롭게 넣어 깔끔한 버튼 발행\n"
                "  - **`[🎭 반응역할 종합 스튜디오]`** : 단계별 빌더 및 기존 공지글 바인딩\n"
                "  - **`[📢 스마트 공지 발송]`** : 공지 채널에 알림 임베드 미리보기 및 즉시 전송\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.from_rgb(88, 101, 242),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text="서버 관리자 및 역할 관리자 전용 기능 • norosi Admin Engine")
        return embed

    def build_game_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🎲 미니게임 & 파티 모집 & 유틸 대시보드",
            description=(
                "서버 멤버들과 함께 즐기는 미니게임 및 스마트 편의성 도구 허브입니다.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "• **🎮 파티/팀원 모집:** 프로세카, 롤, 발로란트 등 자유 양식 팀원 모집 및 대기열\n"
                "• **🔤 끝말잇기:** 표준 두음법칙 자동 적용 실시간 단어 대결 (+150💎)\n"
                "• **🔫 러시안룰렛:** 6연발 실린더 서바이벌 스릴 게임\n"
                "• **🌤️ 실시간 날씨:** 기상청/ECMWF 초정밀 실시간 날씨·미세먼지·강수확률\n"
                "• **⏰ 스마트 알림예약:** 일정 시간 후 나에게 DM 또는 채널로 알림 전송\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.from_rgb(241, 196, 15),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text="하단 버튼을 누르면 해당 게임이나 유틸리티가 즉시 대화창으로 시작됩니다!")
        return embed

    def build_stats_embed(self) -> discord.Embed:
        g = self.guild
        member_cnt = getattr(g, "member_count", None) or 1
        member_str = f"{member_cnt:,}" if isinstance(member_cnt, int) else str(member_cnt)
        if g and getattr(g, "created_at", None):
            try:
                created_str = g.created_at.strftime("%Y-%m-%d")
            except Exception:
                created_str = str(g.created_at)[:10]
        else:
            created_str = "알수없음"

        g_name = getattr(g, "name", "개인 DM")

        embed = discord.Embed(
            title="📊 서버 통계 & 분석 & 건의 대시보드",
            description=(
                f"**{g_name}** 서버의 실시간 활동 지표 및 봇 상태입니다.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **👥 서버 멤버 수:** 총 **`{member_str}명`**\n"
                f"• **📅 서버 개설일:** `{created_str}`\n"
                f"• **🪪 내 가입 순번/역할:** 아래 `[🪪 내 상세 유저정보]` 버튼으로 확인\n"
                f"• **🤖 봇 Uptime & 호스트:** 아래 `[🤖 봇 호스트 상태]` 버튼으로 확인 (관리자 전용)\n"
                f"• **📬 건의함:** 개발자에게 익명 또는 공개로 아이디어 건의\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.from_rgb(52, 152, 219),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text="실시간 서버 분석 보고서 및 건의함을 버튼으로 즉시 열람하세요!")
        return embed

    # ----------------------------------------------------
    # 버튼 콜백 핸들러들 (철저한 예외 방어 & 권한 검사)
    # ----------------------------------------------------
    async def _on_refresh_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            self.data = await asyncio.to_thread(core.load_data)
            self.refresh_components()
            await interaction.edit_original_response(embed=self.build_current_embed(), view=self)
        except Exception as e:
            await core.safe_send_response(interaction, f"⚠️ 새로고침 중 오류 발생: {e}", ephemeral=True)

    async def _on_attendance_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            embed, file, view = await dday.execute_and_build_attendance_response(interaction, self.bot)
            self.data = await asyncio.to_thread(core.load_data)
            self.refresh_components()
            try:
                await interaction.message.edit(embed=self.build_current_embed(), view=self)
            except Exception:
                pass
            if file:
                await interaction.followup.send(embed=embed, file=file, view=view)
            else:
                await interaction.followup.send(embed=embed, view=view)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 출석체크 처리 중 오류: {e}", ephemeral=True)

    async def _on_pull_10_clicked(self, interaction: discord.Interaction):
        try:
            repull_view = gacha.GachaPullAgainView(interaction.user)
            await repull_view._handle_repull(interaction, 10)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 가챠 실행 중 오류: {e}", ephemeral=True)

    async def _on_pull_1_clicked(self, interaction: discord.Interaction):
        try:
            repull_view = gacha.GachaPullAgainView(interaction.user)
            await repull_view._handle_repull(interaction, 1)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 가챠 실행 중 오류: {e}", ephemeral=True)

    async def _on_my_inventory_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            g_key = str(interaction.guild_id or 0)
            u_key = str(interaction.user.id)
            user_cards_dict = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})
            view = gacha.MyInventoryView(interaction.user, list(user_cards_dict.values()), items_per_page=5, guild_id=interaction.guild_id or 0)
            await interaction.followup.send(embed=view.build_embed(), view=view)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 보관함 조회 중 오류: {e}", ephemeral=True)

    async def _on_dup_convert_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction, ephemeral=True)
            guild_id = interaction.guild_id or 0
            res = await asyncio.to_thread(core.execute_duplicate_card_conversion, guild_id, interaction.user.id)
            if res["converted_count"] == 0:
                await interaction.followup.send("ℹ️ 환전 가능한 중복 카드가 없습니다. (잠금🔒 카드는 제외됩니다)", ephemeral=True)
                return

            self.data = await asyncio.to_thread(core.load_data)
            try:
                await interaction.message.edit(embed=self.build_current_embed(), view=self)
            except Exception:
                pass

            await interaction.followup.send(
                f"🎉 **중복 카드 일괄 환전 완료!**\n"
                f"• 중복 카드 `{res['converted_count']}장` 변환 → **`+{res['gained_crystals']:,}💎`** 획득!\n"
                f"• 현재 보유 크리스탈: **`{res['current_crystals']:,}개`**",
                ephemeral=True
            )
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 중복 환전 중 오류: {e}", ephemeral=True)

    async def _on_deck_edit_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            profile = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
            deck_ids = profile.get("deck", [])
            g_key = str(interaction.guild_id or 0)
            u_key = str(interaction.user.id)
            user_cards_dict = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})

            deck_cards_lines = []
            for slot_idx, cid in enumerate(deck_ids, start=1):
                cinfo = user_cards_dict.get(cid, {})
                cname = cinfo.get("char_name", "미상")
                cprefix = cinfo.get("prefix", "")
                rlabel = cinfo.get("rarity_label", "★1")
                deck_cards_lines.append(
                    f"**슬롯 {slot_idx} (리더)**: {rlabel} [{cprefix}] **{cname}** (`{cid}`)"
                    if slot_idx == 1 else
                    f"**슬롯 {slot_idx}**: {rlabel} [{cprefix}] {cname} (`{cid}`)"
                )

            if not deck_cards_lines:
                desc = "현재 편성된 덱이 없습니다.\n채팅창에 **`/덱편성`** 명령어를 입력하여 보유한 카드 중 원하는 5장을 선택해 덱을 꾸며보세요!"
            else:
                desc = "현재 구성된 5인 유닛 덱 목록입니다:\n\n" + "\n".join(deck_cards_lines) + "\n\n💡 덱 멤버를 바꾸거나 순서를 변경하시려면 **`/덱편성`** 명령어를 사용해 주세요!"

            embed = discord.Embed(
                title=f"🎴 {interaction.user.display_name}님의 5인 유닛 덱 현황",
                description=desc,
                color=discord.Color.from_rgb(235, 69, 158),
                timestamp=datetime.datetime.now(core.KST)
            )
            embed.set_footer(text="/덱편성 명령어로 보유 카드 자동완성을 통해 간편하게 변경할 수 있습니다.")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 덱 정보 조회 중 오류: {e}", ephemeral=True)

    async def _on_pokedex_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            guild_id = interaction.guild_id or 0
            stats_data = await asyncio.to_thread(core.get_card_pokedex_stats, guild_id, interaction.user.id)
            view = gacha.CardPokedexView(interaction.user, stats_data, guild_id=guild_id, initial_tab="char_rates")
            await interaction.followup.send(embed=view.build_embed(), view=view)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 카드 도감 로드 중 오류: {e}", ephemeral=True)

    async def _on_gacha_rank_clicked(self, interaction: discord.Interaction):
        try:
            gacha_cog = self._find_cog_with_attr("gacha_ranking_cmd")
            if gacha_cog:
                await gacha_cog.gacha_ranking_cmd.callback(gacha_cog, interaction)
            else:
                await core.safe_send_response(interaction, "🏆 가챠 랭킹은 `/가챠랭킹` 명령어로 확인하실 수 있습니다.", ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 랭킹 조회 중 오류: {e}", ephemeral=True)

    async def _on_todo_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            profile = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
            core.ensure_user_todo_today(profile)
            await asyncio.to_thread(core.save_data, data)
            view = dday.TodoTrackerView(interaction.user, profile)
            await interaction.followup.send(embed=view.build_embed(), view=view)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 목표 체크 중 오류: {e}", ephemeral=True)

    # 일정 / D-Day 관련
    async def _on_add_dday_clicked(self, interaction: discord.Interaction):
        try:
            await interaction.response.send_modal(DashboardDDayAddModal(self))
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ D-Day 등록 모달 열기 실패: {e}", ephemeral=True)

    async def _on_dday_list_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            ddays_dict = data.get("ddays", {})
            view = dday.DDayListBoardView(ddays_dict, self.bot)
            await interaction.followup.send(embed=view.build_embed(), view=view)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ D-Day 목록 조회 중 오류: {e}", ephemeral=True)

    async def _on_birthday_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            view = dday.BirthdayBoardView(interaction.user, interaction.guild, data)
            await interaction.followup.send(embed=view.build_embed(), view=view)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 생일 전광판 조회 중 오류: {e}", ephemeral=True)

    async def _on_pomodoro_clicked(self, interaction: discord.Interaction):
        try:
            key = (interaction.guild_id or 0, interaction.user.id)
            if key in core.ACTIVE_POMODORO_TASKS:
                task_info = core.ACTIVE_POMODORO_TASKS.pop(key, None)
                if task_info:
                    task_info["task"].cancel()
                    v_ch = task_info.get("voice_channel")
                    if v_ch:
                        for member in v_ch.members:
                            if not member.bot:
                                try:
                                    await member.edit(mute=False, reason="집중모드 수동 중지")
                                except Exception:
                                    pass
                await core.safe_send_response(interaction, "⏹️ **실행 중이던 뽀모도로 집중모드가 중지되었으며 음소거가 해제되었습니다!**", ephemeral=True)
                return

            await interaction.response.send_modal(DashboardPomodoroModal(self.bot))
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 뽀모도로 모달 열기 실패: {e}", ephemeral=True)

    async def _on_partner_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            profile = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
            partner_id = profile.get("partner_id")
            partner_member = interaction.guild.get_member(int(partner_id)) if (interaction.guild and partner_id) else None
            view = dday.PartnerStudioView(interaction.user, partner_member, profile)
            await interaction.followup.send(embed=view.build_embed(), view=view)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 파트너 스튜디오 조회 중 오류: {e}", ephemeral=True)

    async def _on_forecast_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            now = datetime.datetime.now(core.KST)
            view = dday.EventForecastView(interaction.user, now.year, now.month)
            await interaction.followup.send(embed=view.build_embed(), view=view)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 미래시 조회 중 오류: {e}", ephemeral=True)

    # 음악 관련
    async def _on_playlist_studio_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            view = music.PlaylistStudioView(interaction.user, interaction.user, data)
            await interaction.followup.send(embed=view.build_embed(), view=view)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 플레이리스트 스튜디오 오류: {e}", ephemeral=True)

    async def _on_music_now_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            prefs = data.get("music_prefs", core.DEFAULT_CONFIG["music_prefs"])
            track_info, err = await core.get_recommended_music(prefs)
            if err or not track_info:
                await interaction.followup.send(f"❌ **음악 선곡 실패:** {err or '추천 곡을 찾을 수 없습니다.'}", ephemeral=True)
                return
            embed, view = self.bot.build_music_embed_and_view(track_info, prefs, is_morning=False)
            await interaction.followup.send(embed=embed, view=view)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 음악 선곡 중 오류: {e}", ephemeral=True)

    async def _on_audio_test_clicked(self, interaction: discord.Interaction):
        try:
            voice_state = interaction.user.voice if isinstance(interaction.user, discord.Member) else None
            if not voice_state or not voice_state.channel:
                await core.safe_send_response(
                    interaction,
                    "❌ 먼저 오디오를 테스트할 **음성채널**에 입장하신 뒤 버튼을 눌러주세요!",
                    ephemeral=True
                )
                return

            music_cog = self._find_cog_with_attr("audio_test_cmd")
            if music_cog:
                await music_cog.audio_test_cmd.callback(music_cog, interaction)
            else:
                await core.safe_send_response(interaction, "🔊 440Hz 오디오 자가진단은 `/오디오테스트` 명령어로 실행할 수 있습니다.", ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 오디오 테스트 실행 중 오류: {e}", ephemeral=True)

    # 관리자 관련 (logger.AnnouncementPreviewView 및 DashboardInactiveAuditModal 정확히 연결)
    async def _on_quick_role_btn_clicked(self, interaction: discord.Interaction):
        try:
            if not await self.check_admin_permission(interaction, action_name="사진 스타일 역할버튼 제작", require_roles_perm=True):
                return
            await interaction.response.send_modal(roles.QuickRoleButtonModal(target_channel=interaction.channel))
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 역할 버튼 제작 모달 열기 실패: {e}", ephemeral=True)

    async def _on_role_studio_clicked(self, interaction: discord.Interaction):
        try:
            if not await self.check_admin_permission(interaction, action_name="반응역할 종합 스튜디오", require_roles_perm=True):
                return
            studio = roles.ReactionRoleStudioView(interaction.guild, interaction.user)
            await core.safe_send_response(interaction, embed=studio.build_dashboard_embed(), view=studio, ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 반응역할 스튜디오 열기 실패: {e}", ephemeral=True)

    async def _on_announcement_clicked(self, interaction: discord.Interaction):
        try:
            if not await self.check_admin_permission(interaction, action_name="스마트 공지 발송", require_roles_perm=False):
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
                )
            )
            await interaction.followup.send(
                content=preview_view.build_preview_content(),
                embed=preview_view.build_embed(),
                view=preview_view,
                ephemeral=True
            )
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 공지 스튜디오 열기 실패: {e}", ephemeral=True)

    async def _on_inactive_audit_clicked(self, interaction: discord.Interaction):
        try:
            if not await self.check_admin_permission(interaction, action_name="비활성 유저 감사", require_roles_perm=False):
                return
            await interaction.response.send_modal(DashboardInactiveAuditModal(self.bot))
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 비활성 유저 감사 모달 열기 실패: {e}", ephemeral=True)

    # 게임 관련
    async def _on_recruit_clicked(self, interaction: discord.Interaction):
        try:
            if not interaction.guild:
                await core.safe_send_response(interaction, "❌ 서버 채널에서만 모집할 수 있습니다.", ephemeral=True)
                return
            await interaction.response.send_modal(stats.RecruitModal())
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 파티 모집 모달 열기 실패: {e}", ephemeral=True)

    async def _on_word_chain_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            first_word = random.choice(["세카이", "음악", "별자리", "피아노", "출석", "콘서트", "하늘", "무지개", "기차", "바다"])
            view = stats.WordChainGameView(interaction.user, None, first_word)
            await interaction.followup.send(embed=view.build_embed(), view=view)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 끝말잇기 시작 중 오류: {e}", ephemeral=True)

    async def _on_roulette_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            view = stats.RussianRouletteView(interaction.user, bullets=1, bet_crystals=0)
            await interaction.followup.send(embed=view.build_embed(), view=view)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 러시안룰렛 시작 중 오류: {e}", ephemeral=True)

    async def _on_weather_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            w_info, err = await asyncio.to_thread(core.fetch_accurate_weather_sync, "서울")
            if err or not w_info:
                await interaction.followup.send(f"❌ **날씨 조회 실패:** {err}", ephemeral=True)
                return
            view = stats.WeatherRefreshView("서울", w_info)
            await interaction.followup.send(embed=view.build_embed(), view=view)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 날씨 조회 중 오류: {e}", ephemeral=True)

    async def _on_remind_clicked(self, interaction: discord.Interaction):
        try:
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            view = dday.ReminderHubView(interaction.user, interaction.channel_id, interaction.guild_id, data)
            await interaction.followup.send(embed=view.build_embed(), view=view)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 알림 예약 허브 로드 중 오류: {e}", ephemeral=True)

    # 통계 관련
    async def _on_server_stats_clicked(self, interaction: discord.Interaction):
        try:
            if not interaction.guild:
                await core.safe_send_response(interaction, "❌ 서버 채널에서만 조회 가능합니다.", ephemeral=True)
                return
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            embed = stats.build_server_stats_embed(interaction.guild, data)
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 서버 통계 생성 중 오류: {e}", ephemeral=True)

    async def _on_user_info_clicked(self, interaction: discord.Interaction):
        try:
            stats_cog = self._find_cog_with_attr("user_profile_info_cmd")
            if stats_cog:
                await stats_cog.user_profile_info_cmd.callback(stats_cog, interaction, interaction.user)
            else:
                await core.safe_send_response(interaction, "🪪 내 정보는 `/유저정보` 명령어로 확인하실 수 있습니다.", ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 유저 정보 조회 중 오류: {e}", ephemeral=True)

    async def _on_bot_status_clicked(self, interaction: discord.Interaction):
        try:
            is_owner = await self.bot.is_bot_owner_user(interaction.user)
            is_admin = False
            if interaction.guild and isinstance(interaction.user, discord.Member):
                is_admin = interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild

            if not (is_owner or is_admin):
                await core.safe_send_response(
                    interaction,
                    "🚨 **권한 부족:** 봇 호스트 상태 및 시스템 리소스 모니터링은 **서버 관리자(Manage Server)** 또는 **봇 소유자**만 열람할 수 있습니다.",
                    ephemeral=True
                )
                return

            stats_cog = self._find_cog_with_attr("host_system_stats_cmd")
            if stats_cog:
                await stats_cog.host_system_stats_cmd.callback(stats_cog, interaction)
            else:
                await core.safe_send_response(interaction, "🤖 봇 상태는 `/봇상태` 명령어로 확인하실 수 있습니다.", ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 봇 상태 조회 중 오류: {e}", ephemeral=True)

    async def _on_suggestion_clicked(self, interaction: discord.Interaction):
        try:
            await interaction.response.send_modal(stats.SuggestionSubmitModal(bot=self.bot, is_anonymous=False))
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 건의함 모달 열기 실패: {e}", ephemeral=True)


# ==========================================
# 🚀 Dashboard Cog 메인 클래스
# ==========================================
class Dashboard(commands.Cog, name="대시보드"):
    """norosi 봇의 모든 기능을 한곳에서 시각적으로 제어하는 올인원 마스터 대시보드 모듈"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="대시보드", description="모든 봇 기능(가챠, 일정, 음악, 역할, 게임, 통계)을 시각적으로 제어하는 올인원 마스터 대시보드를 엽니다.")
    @app_commands.describe(탭="초기에 열람할 기능 대시보드 탭 (기본: 종합 관제)")
    @app_commands.choices(탭=[
        app_commands.Choice(name="🧭 [홈] 종합 관제 대시보드", value="home"),
        app_commands.Choice(name="🎮 [가챠] 카드·뽑기·덱 대시보드", value="gacha"),
        app_commands.Choice(name="📅 [일정] D-Day·생일·집중 대시보드", value="life"),
        app_commands.Choice(name="🎵 [음악] 플레이리스트·사운드 대시보드", value="music"),
        app_commands.Choice(name="🎭 [역할] 역할버튼·공지 대시보드", value="admin"),
        app_commands.Choice(name="🎲 [게임] 미니게임·모집·날씨 대시보드", value="game"),
        app_commands.Choice(name="📊 [통계] 서버분석·유저정보 대시보드", value="stats"),
    ])
    async def slash_dashboard(self, interaction: discord.Interaction, 탭: Optional[app_commands.Choice[str]] = None):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        init_tab = 탭.value if 탭 else "home"
        view = MasterDashboardView(
            bot=self.bot,
            user=interaction.user,
            guild=interaction.guild,
            data=data,
            initial_tab=init_tab
        )
        msg = await interaction.followup.send(embed=view.build_current_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="메뉴", description="명령어 타이핑 없이 버튼 하나로 모든 봇 기능을 1초 만에 실행하는 슈퍼 대시보드 리모컨을 엽니다.")
    async def slash_menu(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        view = MasterDashboardView(
            bot=self.bot,
            user=interaction.user,
            guild=interaction.guild,
            data=data,
            initial_tab="home"
        )
        msg = await interaction.followup.send(embed=view.build_current_embed(), view=view, wait=True)
        view.message = msg

    @commands.command(name="대시보드", aliases=["dashboard", "메뉴", "menu", "리모컨", "컨트롤타워"])
    async def prefix_dashboard(self, ctx: commands.Context):
        data = await asyncio.to_thread(core.load_data)
        view = MasterDashboardView(
            bot=self.bot,
            user=ctx.author,
            guild=ctx.guild,
            data=data,
            initial_tab="home"
        )
        msg = await ctx.send(embed=view.build_current_embed(), view=view)
        view.message = msg


async def setup(bot: commands.Bot):
    await bot.add_cog(Dashboard(bot))
