"""
norosi Bot - 올인원 마스터 대시보드 (All-in-One Master Dashboard) Cog
- 7대 핵심 기능 영역(홈, 가챠, 일정, 음악, 역할·관리, 게임, 통계)을 탭(Tab)으로 자유롭게 오가는 슈퍼 컨트롤 타워
- 명령어 타이핑 없이 드롭다운 및 대화형 버튼 조작으로 68개 모든 기능을 100% 원클릭 조작
- 슬래시 커맨드: /대시보드, /메뉴
- 일반 명령어: !대시보드, !메뉴
"""

import asyncio
import datetime
from typing import Optional, List, Dict, Any

import discord
from discord import app_commands
from discord.ext import commands

import core
from cogs import dday, gacha, music, roles, stats, logger


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

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 대시보드는 **{self.user.display_name}**님의 개인 세션입니다. 본인의 대시보드는 `/대시보드` 또는 `/메뉴`로 열어주세요!",
                ephemeral=True
            )
            return False
        return True

    def refresh_components(self):
        """현재 선택된 탭에 맞춰 상단 드롭다운 및 하단 기능 버튼들을 실시간 재구성"""
        self.clear_items()
        # Row 0: 탭 네비게이션 드롭다운
        self.add_item(DashboardTabSelect(self.current_tab))

        # Row 1, 2, 3: 탭별 전용 인터랙티브 버튼 렌더링
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

        # 공통 새로고침 버튼
        btn_refresh = discord.ui.Button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=2)
        btn_refresh.callback = self._on_refresh_clicked
        self.add_item(btn_refresh)

    # ----------------------------------------------------
    # 탭별 버튼 세팅
    # ----------------------------------------------------
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
        btn_p10 = discord.ui.Button(label="🌈 10회 뽑기 (2,000💎)", style=discord.ButtonStyle.success, row=1)
        btn_p10.callback = self._on_pull_10_clicked
        self.add_item(btn_p10)

        btn_p1 = discord.ui.Button(label="🎲 1회 뽑기 (200💎)", style=discord.ButtonStyle.success, row=1)
        btn_p1.callback = self._on_pull_1_clicked
        self.add_item(btn_p1)

        btn_inv = discord.ui.Button(label="🎒 내 보관함", style=discord.ButtonStyle.primary, row=1)
        btn_inv.callback = self._on_my_inventory_clicked
        self.add_item(btn_inv)

        btn_dup = discord.ui.Button(label="💎 중복 일괄 환전", style=discord.ButtonStyle.secondary, row=1)
        btn_dup.callback = self._on_dup_convert_clicked
        self.add_item(btn_dup)

        btn_deck = discord.ui.Button(label="🎴 덱 편성 & 강화", style=discord.ButtonStyle.primary, row=2)
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

        four_stars = sum(1 for c in user_cards.values() if c.get("rarity") == "rarity_4")
        birthdays = sum(1 for c in user_cards.values() if c.get("rarity") == "rarity_birthday")

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
                diff, d_txt = core.get_dday_info(d_val)
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
        pl_data = self.data.get("playlists", {})
        u_pls = [p for p in pl_data.values() if int(p.get("author_id", 0)) == self.user.id]
        tot_tracks = sum(len(p.get("tracks", [])) for p in u_pls)

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
        if self.guild and isinstance(self.user, discord.Member):
            is_admin = self.user.guild_permissions.administrator or self.user.guild_permissions.manage_roles

        admin_badge = "✅ **관리자 권한 보유** (모든 설정 조작 가능)" if is_admin else "⚠️ **일반 멤버** (일부 기능 제한)"

        embed = discord.Embed(
            title="🎭 역할 & 공지 & 서버 관리 대시보드",
            description=(
                "사진 스타일 맞춤 역할 버튼 제작, 이모지 반응역할 및 스마트 공지를 관리합니다.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **🛡️ 관리 권한 확인:** {admin_badge}\n"
                f"• **📜 등록된 반응역할/버튼 패널:** **`{total_panels}개`**\n"
                f"• **🏷️ 자동 배정 중인 역할 총합:** **`{total_roles}개`**\n"
                "• **✨ 추천 기능:**\n"
                "  - **`[🚀 사진 스타일 역할버튼 제작]`** : 제목/본문/버튼이름/이모지를 자유롭게 넣어 깔끔한 버튼 발행\n"
                "  - **`[🎭 반응역할 종합 스튜디오]`** : 단계별 빌더 및 기존 공지글 바인딩\n"
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
        member_cnt = g.member_count if g else 1
        created_str = g.created_at.strftime("%Y-%m-%d") if g else "알수없음"

        embed = discord.Embed(
            title="📊 서버 통계 & 분석 & 건의 대시보드",
            description=(
                f"**{g.name if g else '개인 DM'}** 서버의 실시간 활동 지표 및 봇 상태입니다.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **👥 서버 멤버 수:** 총 **`{member_cnt:,}명`**\n"
                f"• **📅 서버 개설일:** `{created_str}`\n"
                f"• **🪪 내 가입 순번/역할:** 아래 `[🪪 내 상세 유저정보]` 버튼으로 확인\n"
                f"• **🤖 봇 Uptime & 호스트:** 아래 `[🤖 봇 호스트 상태]` 버튼으로 확인\n"
                f"• **📬 건의함:** 개발자에게 익명 또는 공개로 아이디어 건의\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.from_rgb(52, 152, 219),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text="실시간 서버 분석 보고서 및 건의함을 버튼으로 즉시 열람하세요!")
        return embed

    # ----------------------------------------------------
    # 버튼 콜백 핸들러들
    # ----------------------------------------------------
    async def _on_refresh_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        self.data = await asyncio.to_thread(core.load_data)
        self.refresh_components()
        await interaction.edit_original_response(embed=self.build_current_embed(), view=self)

    # 홈 / 가챠 관련
    async def _on_attendance_clicked(self, interaction: discord.Interaction):
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

    async def _on_pull_10_clicked(self, interaction: discord.Interaction):
        repull_view = gacha.GachaPullAgainView(interaction.user)
        await repull_view._handle_repull(interaction, 10)

    async def _on_pull_1_clicked(self, interaction: discord.Interaction):
        repull_view = gacha.GachaPullAgainView(interaction.user)
        await repull_view._handle_repull(interaction, 1)

    async def _on_my_inventory_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id or 0)
        u_key = str(interaction.user.id)
        user_cards_dict = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})
        view = gacha.MyInventoryView(interaction.user, list(user_cards_dict.values()), items_per_page=5, guild_id=interaction.guild_id or 0)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    async def _on_dup_convert_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id or 0)
        u_key = str(interaction.user.id)
        user_cards_dict = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})

        converted_crystals = 0
        converted_cards_count = 0
        for card_id, card_info in list(user_cards_dict.items()):
            cnt = card_info.get("count", 1)
            is_locked = card_info.get("locked", False)
            if cnt > 1 and not is_locked:
                excess = cnt - 1
                rarity = card_info.get("rarity", "")
                rate = core.DUPLICATE_CRYSTAL_RATES.get(rarity, 20)
                converted_crystals += excess * rate
                converted_cards_count += excess
                card_info["count"] = 1

        if converted_cards_count == 0:
            await interaction.followup.send("ℹ️ 환전 가능한 중복 카드가 없습니다. (잠금🔒 카드는 제외됩니다)", ephemeral=True)
            return

        profile = core.ensure_user_profile(data, u_key, interaction.user.display_name)
        profile["crystals"] = profile.get("crystals", 0) + converted_crystals
        await asyncio.to_thread(core.save_data, data)

        await interaction.followup.send(
            f"🎉 **중복 카드 일괄 환전 완료!**\n"
            f"• 중복 카드 `{converted_cards_count}장` 변환 → **`+{converted_crystals:,}💎`** 획득!\n"
            f"• 현재 보유 크리스탈: **`{profile['crystals']:,}개`**",
            ephemeral=True
        )

    async def _on_deck_edit_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        profile = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
        g_key = str(interaction.guild_id or 0)
        u_key = str(interaction.user.id)
        user_cards_dict = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})
        view = gacha.DeckEditView(interaction.user, profile, user_cards_dict)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    async def _on_pokedex_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id or 0)
        u_key = str(interaction.user.id)
        user_cards_dict = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})
        view = gacha.GachaPokedexView(interaction.user, user_cards_dict)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    async def _on_gacha_rank_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        init_scope = "guild" if interaction.guild else "global"
        view = gacha.GachaRankingView(interaction, data, initial_scope=init_scope, initial_sort="unique")
        await interaction.followup.send(embed=view.build_embed(), view=view)

    async def _on_todo_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        profile = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
        core.ensure_user_todo_today(profile)
        await asyncio.to_thread(core.save_data, data)
        view = dday.TodoTrackerView(interaction.user, profile)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    # 일정 / D-Day 관련
    async def _on_add_dday_clicked(self, interaction: discord.Interaction):
        await interaction.response.send_modal(dday.DDayAddModal(self.bot))

    async def _on_dday_list_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        ddays_dict = data.get("ddays", {})
        embed = dday.build_dday_list_embed(ddays_dict)
        await interaction.followup.send(embed=embed)

    async def _on_birthday_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        bdays = data.get("birthdays", {})
        now = datetime.datetime.now(core.KST)
        embed = dday.build_birthday_board_embed(bdays, now.month)
        await interaction.followup.send(embed=embed)

    async def _on_pomodoro_clicked(self, interaction: discord.Interaction):
        await interaction.response.send_modal(dday.PomodoroSettingsModal())

    async def _on_partner_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        profile = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
        partner_id = profile.get("partner_id")
        partner_member = interaction.guild.get_member(partner_id) if (interaction.guild and partner_id) else None
        view = dday.PartnerStudioView(interaction.user, partner_member, profile)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    async def _on_forecast_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        now = datetime.datetime.now(core.KST)
        view = dday.EventForecastView(interaction.user, now.year, now.month)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    # 음악 관련
    async def _on_playlist_studio_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        view = music.PlaylistStudioView(interaction.user, data)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    async def _on_music_now_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        view = music.MusicRecommendView(self.bot, interaction.user)
        embed = await view.build_recommend_embed()
        await interaction.followup.send(embed=embed, view=view)

    async def _on_audio_test_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        music_cog = self.bot.get_cog("음악")
        if music_cog and hasattr(music_cog, "slash_audio_test"):
            await music_cog.slash_audio_test.callback(music_cog, interaction)
        else:
            await interaction.followup.send("🔊 440Hz 오디오 자가진단은 `/오디오테스트` 명령어로 실행할 수 있습니다.", ephemeral=True)

    # 관리자 관련
    async def _on_quick_role_btn_clicked(self, interaction: discord.Interaction):
        await interaction.response.send_modal(roles.QuickRoleButtonModal(target_channel=interaction.channel))

    async def _on_role_studio_clicked(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        studio = roles.ReactionRoleStudioView(interaction.guild, interaction.user)
        await core.safe_send_response(interaction, embed=studio.build_dashboard_embed(), view=studio, ephemeral=True)

    async def _on_announcement_clicked(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator and not interaction.user.guild_permissions.manage_guild:
            await core.safe_send_response(interaction, "❌ 관리자 또는 서버 관리 권한이 필요합니다.", ephemeral=True)
            return
        await interaction.response.send_modal(logger.AnnouncementModal(interaction.channel))

    async def _on_inactive_audit_clicked(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, "❌ 서버 관리자만 비활성 유저 감사를 실행할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(logger.InactiveAuditModal(self.bot))

    # 게임 관련
    async def _on_recruit_clicked(self, interaction: discord.Interaction):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 모집할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(dday.RecruitModal())

    async def _on_word_chain_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        dday_cog = self.bot.get_cog("D-Day & 라이프")
        if dday_cog and hasattr(dday_cog, "word_chain_cmd"):
            await dday_cog.word_chain_cmd.callback(dday_cog, interaction)
        else:
            await interaction.followup.send("🔤 `/끝말잇기` 명령어로 즉시 단어 대결을 시작할 수 있습니다!")

    async def _on_roulette_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        dday_cog = self.bot.get_cog("D-Day & 라이프")
        if dday_cog and hasattr(dday_cog, "russian_roulette_cmd"):
            await dday_cog.russian_roulette_cmd.callback(dday_cog, interaction)
        else:
            await interaction.followup.send("🔫 `/러시안룰렛` 명령어로 스릴 만점 생존 게임을 시작할 수 있습니다!")

    async def _on_weather_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        dday_cog = self.bot.get_cog("D-Day & 라이프")
        if dday_cog and hasattr(dday_cog, "weather_cmd"):
            await dday_cog.weather_cmd.callback(dday_cog, interaction, "서울")
        else:
            await interaction.followup.send("🌤️ `/날씨 지역:서울` 명령어로 실시간 기상 정보를 확인하세요!")

    async def _on_remind_clicked(self, interaction: discord.Interaction):
        await interaction.response.send_modal(dday.ReminderModal())

    # 통계 관련
    async def _on_server_stats_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        if not interaction.guild:
            await interaction.followup.send("❌ 서버 채널에서만 조회 가능합니다.", ephemeral=True)
            return
        embed = stats.build_server_stats_embed(interaction.guild)
        await interaction.followup.send(embed=embed)

    async def _on_user_info_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        embed = stats.build_user_info_embed(interaction.user, interaction.guild, data)
        await interaction.followup.send(embed=embed)

    async def _on_bot_status_clicked(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        embed = stats.build_bot_status_embed(self.bot, data)
        await interaction.followup.send(embed=embed)

    async def _on_suggestion_clicked(self, interaction: discord.Interaction):
        await interaction.response.send_modal(stats.SuggestionModal())


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
        await interaction.followup.send(embed=view.build_current_embed(), view=view)

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
        await interaction.followup.send(embed=view.build_current_embed(), view=view)

    @commands.command(name="대시보드", aliases=["dashboard", "메뉴", "menu", "리모컨", "컨트롤타워"])
    async def prefix_dashboard(self, ctx: commands.Context):
        """[명령어] 채팅창에서 !대시보드 또는 !메뉴 입력 시 올인원 마스터 대시보드 호출"""
        data = await asyncio.to_thread(core.load_data)
        view = MasterDashboardView(
            bot=self.bot,
            user=ctx.author,
            guild=ctx.guild,
            data=data,
            initial_tab="home"
        )
        await ctx.send(embed=view.build_current_embed(), view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Dashboard(bot))
