import io
import re
import copy
import time
import asyncio
import datetime
import discord
from discord import app_commands
from discord.ext import commands
import core
from cogs.music import MusicLibraryPaginationView, PlaylistStudioView
from cogs.gacha import (
    GachaPullAgainView,
    MyInventoryView,
    DuplicateConvertConfirmView,
    CardPokedexView,
    EventForecastView,
    EventInfoView,
    MySekaiHubView,
    CharacterCostumeWardrobeView,
    MasterRankView,
    SekaiLiveView
)
from cogs.stats import RecruitModal, SuggestionTypeSelectView
from cogs.help import build_help_embed, HelpCategoryView


# ==========================================
# 출석 완료 임베드 생성 헬퍼, 월간 출석 캘린더 뷰 & 바로가기 뷰
# ==========================================
async def execute_and_build_attendance_response(interaction: discord.Interaction, bot_instance):
    guild_id = interaction.guild_id or 0
    guild_name = interaction.guild.name if interaction.guild else "개인 메시지(DM)"
    user_id = interaction.user.id
    user_name = interaction.user.display_name

    res = await asyncio.to_thread(core.process_user_attendance, guild_id, guild_name, user_id, user_name)
    cal_info = await asyncio.to_thread(core.build_monthly_attendance_calendar, guild_id, guild_name, user_id, user_name)

    guild_stats = res["guild_stats"]
    global_stats = res["global_stats"]
    oshi_name = res["oshi"]
    total_crystals = res.get("crystals", 0)
    gained_crystals = res.get("gained_crystals", 100)
    milestone_bonus = res.get("milestone_bonus", 0)
    my_sekai_bonus = res.get("my_sekai_bonus", 0)
    life_bonus = res.get("life_bonus", 0)
    life_bonus_reasons = res.get("life_bonus_reasons", [])
    newly_claimed = res.get("newly_claimed_milestones", [])
    quick_view = AttendanceQuickActionView(bot_instance, interaction.user)

    ms_summary_lines = []
    for m in cal_info.get("milestones", []):
        if m["achieved"]:
            ms_summary_lines.append(f"{m['emoji']} **{m['title']} (`{m['days']}일`)** — ✅ **`+{m['reward']:,}💎 수령 완료`**")
        else:
            ms_summary_lines.append(f"{m['emoji']} **{m['title']} (`{m['days']}일`)** — ⏳ `+{m['reward']:,}💎` *(남은 출석 `{m['remaining_days']}일`)*")

    # 현재 서버에서 오늘(00:00 이후) 이미 출석한 경우
    if res["already_checked"]:
        rem_time_str = core.get_time_until_midnight_str()
        bonus_notice = (
            f"\n🎉 **미수령 개근 마일스톤 보너스 `+{milestone_bonus:,}💎`가 추가 지급되었습니다!**"
            if milestone_bonus > 0 else ""
        )
        dup_embed = discord.Embed(
            title=f"⏳ {user_name}님, 오늘 `{guild_name}` 출석은 이미 완료되었습니다!",
            description=(
                "출석체크는 **각 서버별로 하루 1회(자정 `00:00` 초기화)** 진행할 수 있습니다.\n"
                "*(다른 디스코드 서버에서는 오늘 아직 출석하지 않았다면 추가로 출석 가능합니다!)*"
                f"{bonus_notice}\n\n"
                f"• **🏠 `{guild_name}` 서버 기록:** 누적 **`{guild_stats.get('total_days', 1):,}일`** · 연속 **`{guild_stats.get('streak', 1):,}일 🔥`**\n"
                f"• **🗓️ 이번 달(`{cal_info['month']}월`) 출석:** **`{cal_info['month_count']}/{cal_info['days_in_month']}일`** ({cal_info['month_rate']:.1f}%)\n"
                f"• **💎 보유 크리스탈:** **`{total_crystals:,}개`** (🏠 마이세카이 이자: `+{my_sekai_bonus}💎/일`) · **⏰ 자정까지:** `{rem_time_str}`"
            ),
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(core.KST)
        )
        dup_embed.set_thumbnail(url=interaction.user.display_avatar.url)
        dup_embed.add_field(
            name=f"🗓️ {cal_info['year']}년 {cal_info['month']}월 출석 캘린더 (🌟오늘 · ✅출석 · ·미출석)",
            value=f"```text\n{cal_info['calendar_text']}\n```",
            inline=False
        )
        dup_embed.add_field(
            name="🎁 이번 달 개근 보상 마일스톤",
            value="\n".join(ms_summary_lines),
            inline=False
        )
        dup_embed.set_footer(text="아래 버튼으로 월간 캘린더 상세, 출석 랭킹, 카드도감, 통합 설정(/설정)을 바로 열어보세요!")
        return dup_embed, None, quick_view

    # 현재 서버 오늘 첫 출석 성공 시
    preferred_card = None
    if oshi_name:
        oshi_char_id = next((cid for cid, info in core.CHARACTER_MAP.items() if info["name"] == oshi_name), None)
        if oshi_char_id:
            oshi_cos = core.get_user_equipped_costume(guild_id, user_id, oshi_char_id)
            if oshi_cos and oshi_cos.get("card_id") and oshi_cos.get("card_id") > 0:
                if oshi_cos.get("origin_char_id") == oshi_char_id:
                    preferred_card = next((c for c in core.PROSEKA_KR_CARDS if c.get("id") == oshi_cos["card_id"]), None)
                else:
                    preferred_card = next((c for c in core.PROSEKA_KR_CARDS if c.get("char_id") == oshi_char_id and c.get("rarity_type") == "rarity_4"), None)

    quote_info = core.get_random_proseka_quote(preferred_oshi=oshi_name, preferred_card=preferred_card)
    is_oshi_match = (oshi_name and quote_info.get("char_name") == oshi_name)
    oshi_badge = " 💖**[내 오시 등장!]**" if is_oshi_match else ""

    milestone_banner = ""
    if newly_claimed:
        m_titles = ", ".join(f"{m['emoji']}{m['title']}(+{m['reward']}💎)" for m in newly_claimed)
        milestone_banner = f"\n🎊 **개근 마일스톤 달성 축하 보너스:** **{m_titles}** 추가 지급!"
    if my_sekai_bonus > 0:
        milestone_banner += f"\n🏠 **마이세카이 미니 룸 이자 보너스:** **`+{my_sekai_bonus:,}💎`** 추가 지급!"
    if life_bonus > 0:
        l_reasons = ", ".join(life_bonus_reasons) if life_bonus_reasons else "동반 펫·공동농장·요리 버프"
        milestone_banner += f"\n🐾 **생활 컨텐츠(펫/공동농장/요리) 출석 보너스:** **`+{life_bonus:,}💎`** ({l_reasons})"

    embed = discord.Embed(
        title=f"🌟 {user_name}님, `{guild_name}` 오늘의 출석체크 완료! (+{gained_crystals:,} 💎)",
        description=(
            f"💬 **오늘의 세카이 메시지** — **{quote_info['char_name']}** ({quote_info['unit']}){oshi_badge}\n"
            f"> **\"{quote_info['quote']}\"**\n"
            f"└ 🏷️ 출처: `{quote_info['source']}`"
            f"{milestone_banner}"
        ),
        color=discord.Color.from_rgb(255, 105, 180) if is_oshi_match else discord.Color.from_rgb(0, 204, 221),
        timestamp=datetime.datetime.now(core.KST)
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.add_field(
        name=f"🏠 {guild_name} 서버 출석",
        value=f"누적 **`{guild_stats.get('total_days', 1):,}일`** · 연속 **`{guild_stats.get('streak', 1):,}일 🔥`**\n*(최고 연속 `{guild_stats.get('max_streak', 1):,}일`)*",
        inline=True
    )
    breakdown_parts = ["기본 100"]
    if my_sekai_bonus > 0:
        breakdown_parts.append(f"🏠{my_sekai_bonus}")
    if life_bonus > 0:
        breakdown_parts.append(f"🐾{life_bonus}")
    if milestone_bonus > 0:
        breakdown_parts.append(f"🎁{milestone_bonus}")
    sekai_sub = f" ({' + '.join(breakdown_parts)})" if len(breakdown_parts) > 1 else ""
    embed.add_field(
        name="💎 크리스탈 & 통합 기록",
        value=f"**`+{gained_crystals:,}개 획득!`**{sekai_sub}\n보유: **`{total_crystals:,}개`** · 통합 `{global_stats.get('total_days', 1):,}회`",
        inline=True
    )
    embed.add_field(
        name=f"🗓️ {cal_info['year']}년 {cal_info['month']}월 출석 캘린더 ({cal_info['month_count']}/{cal_info['days_in_month']}일 출석)",
        value=f"```text\n{cal_info['calendar_text']}\n```\n└ {cal_info['month_bar']}",
        inline=False
    )
    embed.add_field(
        name="🎁 이번 달 개근 보상 마일스톤 현황",
        value="\n".join(ms_summary_lines),
        inline=False
    )
    embed.set_footer(text="각 서버별 1일 1회(00:00 KST 초기화) • 아래 버튼으로 캘린더, 랭킹, 카드도감을 바로 확인하세요!")

    card_obj = quote_info.get("card")
    if card_obj:
        img_bytes, filename = await asyncio.to_thread(core.fetch_proseka_card_image_bytes, card_obj, "auto")
        if img_bytes and filename:
            file = discord.File(io.BytesIO(img_bytes), filename=filename)
            embed.set_image(url=f"attachment://{filename}")
            return embed, file, quick_view
        else:
            embed.set_image(url=core.get_proseka_card_image_url(card_obj, "auto"))

    return embed, None, quick_view


class AttendanceCalendarView(core.SafeView):
    """이번 달 출석 날짜 시각적 달력과 개근 보상 마일스톤(7/14/21/28일)을 보여주는 전용 뷰"""
    def __init__(self, bot_instance, user: discord.User, cal_info: dict):
        super().__init__(timeout=600)
        self.bot_instance = bot_instance
        self.user = user
        if not cal_info or "year" not in cal_info:
            uid = user.id if user else 0
            uname = getattr(user, "display_name", "유저")
            cal_info = core.build_monthly_attendance_calendar(0, "현재 서버", uid, uname)
        self.cal_info = cal_info
        self.check_now_btn.disabled = bool(cal_info.get("checked_today", False))
        if self.check_now_btn.disabled:
            self.check_now_btn.label = "✅ 오늘 출석 완료됨"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                content="❌ 본인의 출석 캘린더만 조작할 수 있습니다.",
                ephemeral=True
            )
            return False
        return True

    def build_embed(self):
        if not self.cal_info or "year" not in self.cal_info:
            uid = self.user.id if self.user else 0
            uname = getattr(self.user, "display_name", "유저")
            self.cal_info = core.build_monthly_attendance_calendar(0, "현재 서버", uid, uname)
        c = self.cal_info
        guild_stats = c.get("guild_stats", {})
        ms_lines = []
        for m in c.get("milestones", []):
            if m["achieved"]:
                ms_lines.append(
                    f"{m['emoji']} **{m['days']}일 개근 ({m['title']})** ➔ 💎 **`+{m['reward']:,} 크리스탈`** ✅ **[달성 완료!]**"
                )
            else:
                ms_lines.append(
                    f"{m['emoji']} **{m['days']}일 개근 ({m['title']})** ➔ 💎 **`+{m['reward']:,} 크리스탈`** *(달성까지 `{m['remaining_days']}일` 남음)*"
                )

        embed = discord.Embed(
            title=f"🗓️ {self.user.display_name}님의 {c['year']}년 {c['month']}월 출석 캘린더 & 개근 마일스톤",
            description=(
                f"• **기준 서버:** `{c.get('guild_name', '현재 서버')}` (서버별 1일 1회 독립 출석)\n"
                f"• **이번 달 출석 달성률:** **`{c['month_count']}일 / {c['days_in_month']}일`** (연속 `{guild_stats.get('streak', 0)}일 🔥` · 누적 `{guild_stats.get('total_days', 0)}일`)\n"
                f"└ {c['month_bar']}\n"
                f"• **💎 현재 보유 크리스탈:** **`{c.get('crystals', 0):,}개`**"
            ),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_thumbnail(url=self.user.display_avatar.url)
        embed.add_field(
            name=f"📅 {c['month']}월 출석 도장 달력 (🌟:오늘출석 · ✅:출석완료 · 📍:오늘미출석 · ·:미출석)",
            value=f"```text\n{c['calendar_text']}\n```",
            inline=False
        )
        embed.add_field(
            name="🎁 월간 개근 보상 마일스톤 (출석 달성 시 자동 지급)",
            value="\n".join(ms_lines),
            inline=False
        )
        embed.set_footer(text="매일 출석하여 이번 달 7일 / 14일 / 21일 / 28일 개근 보너스 크리스탈(최대 +3,800💎)을 모두 받아보세요!")
        return embed

    @discord.ui.button(label="📅 오늘 출석체크 하기", style=discord.ButtonStyle.primary, row=0)
    async def check_now_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        embed, file, view = await execute_and_build_attendance_response(interaction, self.bot_instance)
        guild_id = interaction.guild_id or 0
        guild_name = interaction.guild.name if interaction.guild else "개인 메시지(DM)"
        self.cal_info = await asyncio.to_thread(
            core.build_monthly_attendance_calendar,
            guild_id,
            guild_name,
            interaction.user.id,
            interaction.user.display_name
        )
        self.check_now_btn.disabled = True
        self.check_now_btn.label = "✅ 오늘 출석 완료됨"
        try:
            await interaction.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass
        if file:
            await interaction.followup.send(embed=embed, file=file, view=view, wait=True)
        else:
            await interaction.followup.send(embed=embed, view=view, wait=True)

    @discord.ui.button(label="🏆 서버 출석랭킹", style=discord.ButtonStyle.secondary, row=0)
    async def rank_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        init_scope = "guild" if interaction.guild else "global"
        view = AttendanceRankingView(interaction, data, initial_scope=init_scope, initial_sort="total")
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @discord.ui.button(label="📖 전체 카드도감", style=discord.ButtonStyle.success, row=0)
    async def pokedex_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        stats = await asyncio.to_thread(core.get_card_pokedex_stats, guild_id, interaction.user.id)
        view = CardPokedexView(interaction.user, stats, guild_id=guild_id)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=0)
    async def refresh_cal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        guild_name = interaction.guild.name if interaction.guild else "개인 메시지(DM)"
        self.cal_info = await asyncio.to_thread(
            core.build_monthly_attendance_calendar,
            guild_id,
            guild_name,
            self.user.id,
            self.user.display_name,
        )
        self.check_now_btn.disabled = bool(self.cal_info.get("checked_today", False))
        self.check_now_btn.label = "✅ 오늘 출석 완료됨" if self.check_now_btn.disabled else "📅 오늘 출석체크 하기"
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


class AttendanceQuickActionView(core.SafeView):
    """출석체크 결과 하단에서 바로 월간 캘린더, 출석 랭킹, 오늘목표, 카드도감, 빠른 메뉴로 이동하는 버튼 뷰"""
    def __init__(self, bot_instance, user: discord.User):
        super().__init__(timeout=600)
        self.bot_instance = bot_instance
        self.user = user

    @discord.ui.button(label="🗓️ 출석 캘린더 & 개근보상", style=discord.ButtonStyle.primary, row=0)
    async def open_calendar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        guild_name = interaction.guild.name if interaction.guild else "개인 메시지(DM)"
        cal_info = await asyncio.to_thread(
            core.build_monthly_attendance_calendar,
            guild_id,
            guild_name,
            interaction.user.id,
            interaction.user.display_name
        )
        view = AttendanceCalendarView(self.bot_instance, interaction.user, cal_info)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @discord.ui.button(label="🏆 서버 출석랭킹", style=discord.ButtonStyle.secondary, row=0)
    async def open_guild_rank(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        init_scope = "guild" if interaction.guild else "global"
        view = AttendanceRankingView(interaction, data, initial_scope=init_scope, initial_sort="total")
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @discord.ui.button(label="🌱 오늘목표 잔디", style=discord.ButtonStyle.success, row=0)
    async def open_todo_grass(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        profile = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
        core.ensure_user_todo_today(profile)
        await asyncio.to_thread(core.save_data, data)
        view = TodoTrackerView(interaction.user, profile)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @discord.ui.button(label="📖 전체 카드도감", style=discord.ButtonStyle.secondary, row=0)
    async def open_pokedex(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        stats = await asyncio.to_thread(core.get_card_pokedex_stats, guild_id, interaction.user.id)
        view = CardPokedexView(interaction.user, stats, guild_id=guild_id)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @discord.ui.button(label="⚙️ 통합 설정 (/설정)", style=discord.ButtonStyle.secondary, row=0)
    async def open_quick_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        menu_view = QuickMenuHubView(self.bot_instance, interaction.user, interaction.guild, data)
        msg = await interaction.followup.send(embed=menu_view.build_embed(), view=menu_view, wait=True)
        menu_view.message = msg


# ==========================================
# 올인원 빠른 실행 메뉴 (/메뉴) 슈퍼 리모컨 뷰 & 드롭다운
# ==========================================
class CommandRemoteSelect(discord.ui.Select):
    """55개 슬래시 커맨드를 1초 만에 바로 실행하는 리모컨 검색/선택 드롭다운"""
    def __init__(self, bot_instance, user: discord.User):
        self.bot_instance = bot_instance
        self.user = user
        options = [
            discord.SelectOption(label="📅 일일 출석체크 & 달력", value="attendance", description="자정 기준 하루 1회 출석하고 +100💎 및 월간 마일스톤 받기"),
            discord.SelectOption(label="🌱 오늘의 목표 & 잔디", value="todo", description="오늘의 To-Do 체크 및 7일 은하수 잔디 심기"),
            discord.SelectOption(label="🎰 프로세카 뽑기 (10회)", value="pull_10", description="프로세카 10회 연속 뽑기 (★3 이상 확정 / 시각별 유닛 픽업)"),
            discord.SelectOption(label="🌠 /원신기원 (10회)", value="genshin_10", description="원신 10회 기원 (캐릭터·신의 주조 무기·성유물 시각별 로테이션)"),
            discord.SelectOption(label="🚆 /스타레일워프 (10회)", value="hsr_10", description="붕괴: 스타레일 10회 워프 (캐릭터·광추·유물 시각별 로테이션)"),
            discord.SelectOption(label="🎣 세카이 낚시 출조 (호수·강·바다)", value="fishing_cast", description="글로벌 실제 어종 36,700종 낚시·세부 수역 탐사·수족관·최대어 랭킹"),
            discord.SelectOption(label="🏆 낚시 랭킹 (대물 보드)", value="fishing_rank", description="서버 내 물고기 최대 크기(cm)·무게(kg) 순위 & 랭커 정보"),
            discord.SelectOption(label="📅 /미래시", value="forecast", description="프로세카 한섭 이벤트 미래시 달력 & 일섭 비교 상세 타임라인"),
            discord.SelectOption(label="🎶 /이벤트", value="event_info", description="한섭/일섭 실시간 이벤트 및 가챠 배너 정보"),
            discord.SelectOption(label="🎒 프로세카 카드 보관함", value="my_chars", description="뽑은 캐릭터 보관함 & 잠금(🔒) 관리"),
            discord.SelectOption(label="👗 캐릭터 3D 의상실", value="wardrobe", description="캐릭터 3D 의상 착용·어나더 컬러 및 타 캐릭터 의상 제작"),
            discord.SelectOption(label="⚔️ 세카이 라이브", value="sekai_live", description="5인 유닛 덱 & 3D 의상 시너지 세카이 라이브 + 스탬프 랠리"),
            discord.SelectOption(label="📖 프로세카 카드 도감", value="pokedex", description="캐릭터별 수집률(%) 및 미보유 카드 조회"),
            discord.SelectOption(label="🌟 내 통합 프로필", value="profile", description="오시 일러, 덱, 출석, 가챠 통계 프로필 카드"),
            discord.SelectOption(label="🏆 프로세카 가챠 랭킹", value="gacha_rank", description="도감 수집률 & ★4/생일 카드 최다 보유 랭킹"),
            discord.SelectOption(label="🎧 음악 지금 1곡 추천", value="music_now", description="현재 설정 조건으로 세카이 감성 음악 선곡"),
            discord.SelectOption(label="💿 플레이리스트 스튜디오", value="playlist", description="유튜브·스포티파이·사클 나만의 음악 플리 제작 및 공유"),
            discord.SelectOption(label="📋 D-Day 잔디 전광판", value="dday_list", description="등록된 모든 D-Day 전광판 진행 상황 확인"),
            discord.SelectOption(label="💑 파트너 스튜디오", value="partner", description="연인·친구 파트너 맺기 및 공동 D-Day 관리"),
            discord.SelectOption(label="🎂 멤버 생일 전광판 & 등록", value="birthday", description="멤버 생일 전광판 조회 및 내 생일 등록 (+500💎 축하)"),
            discord.SelectOption(label="⏰ 스마트 개인 알림 예약", value="reminder", description="잊지 않게 챙겨주는 스마트 개인 알리미 예약/관리"),
            discord.SelectOption(label="🎮 /모집", value="recruit", description="프로세카·원신·스타레일 등 모든 게임 파티/팀원 자유 모집"),
            discord.SelectOption(label="🌤️ 실시간 기상청 날씨", value="weather", description="기상청/ECMWF 초정밀 실시간 날씨·미세먼지·강수확률"),
            discord.SelectOption(label="🔤 실시간 끝말잇기", value="word_chain", description="표준 두음법칙 적용 실시간 끝말잇기 대결 (+150💎)"),
            discord.SelectOption(label="❓ /도움말", value="help", description="norosi 봇 전체 명령어 카테고리별 상세 도움말"),
        ][:25]
        super().__init__(
            placeholder="🔍 올인원 원클릭 리모컨 (기능 선택)...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
            custom_id="norosi:QuickMenuHubView:command_remote_select",
        )

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        if val == "recruit":
            if not interaction.guild:
                await core.safe_send_response(interaction, "❌ `/모집` 기능은 디스코드 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
                return
            await interaction.response.send_modal(RecruitModal())
            return

        if val == "attendance":
            await core.safe_defer(interaction)
            embed, file, view = await execute_and_build_attendance_response(interaction, self.bot_instance)
            if file:
                await interaction.followup.send(embed=embed, file=file, view=view, wait=True)
            else:
                await interaction.followup.send(embed=embed, view=view, wait=True)
        elif val == "att_calendar":
            await core.safe_defer(interaction)
            guild_id = interaction.guild_id or 0
            guild_name = interaction.guild.name if interaction.guild else "개인 메시지(DM)"
            cal_info = await asyncio.to_thread(
                core.build_monthly_attendance_calendar,
                guild_id,
                guild_name,
                interaction.user.id,
                interaction.user.display_name
            )
            view = AttendanceCalendarView(self.bot_instance, interaction.user, cal_info)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        elif val == "att_rank":
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            init_scope = "guild" if interaction.guild else "global"
            view = AttendanceRankingView(interaction, data, initial_scope=init_scope, initial_sort="total")
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        elif val == "todo":
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            profile = core.ensure_user_profile(data, interaction.user.id, interaction.user.display_name)
            core.ensure_user_todo_today(profile)
            await asyncio.to_thread(core.save_data, data)
            view = TodoTrackerView(interaction.user, profile)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        elif val == "forecast":
            await core.safe_defer(interaction)
            now = datetime.datetime.now(core.KST)
            view = EventForecastView(interaction.user, now.year, now.month)
            embed = await asyncio.to_thread(view.build_embed)
            await interaction.followup.send(embed=embed, view=view, wait=True)
        elif val in ("genshin_10", "genshin_wish"):
            import cogs.genshin as genshin_mod
            pv = genshin_mod.GenshinPullAgainView(interaction.user, banner_key="char1", skip_anim=False, practice=False, last_count=10)
            await pv._run_repull_with_cooldown(interaction, 10)
        elif val in ("hsr_10", "hsr_warp"):
            import cogs.hsr as hsr_mod
            wv = hsr_mod.HSRWarpAgainView(interaction.user, banner_key="char1", skip_anim=False, practice=False, last_count=10)
            await wv._run_rewarp_with_cooldown(interaction, 10)
        elif val == "event_info":
            await core.safe_defer(interaction)
            info = await asyncio.to_thread(core.fetch_live_event_and_gacha_info, "kr")
            ev = info.get("event")
            gachas = info.get("gachas", [])
            embed = discord.Embed(
                title=f"🎶 프로세카 {info['server_label']} 실시간 이벤트 & 가챠 알리미",
                color=discord.Color.from_rgb(0, 204, 221),
                timestamp=datetime.datetime.now(core.KST)
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
                    name=f"🏆 [{info['event_status']}] {ev_name}",
                    value=f"• **종류:** {ev_type} (ID: `{ev.get('id')}`)\n• **기간:** `{start_dt}` ~ `{end_dt}` (KST)\n└ {galaxy_bar}",
                    inline=False
                )
            if gachas:
                g_lines = []
                for g in gachas[:5]:
                    g_name = g.get("name", "가챠")
                    g_end_ms = g.get("endAt", 0)
                    g_end_dt = datetime.datetime.fromtimestamp(g_end_ms / 1000, tz=core.KST).strftime("%m/%d %H:%M") if g_end_ms else "-"
                    g_lines.append(f"• **{g_name}** (종료: `{g_end_dt}`)")
                embed.add_field(name=f"🎰 현재 진행 중인 가챠 배너 ({len(gachas)}개)", value="\n".join(g_lines), inline=False)
            action_view = EventInfoView(self.bot_instance, interaction.user)
            await interaction.followup.send(embed=embed, view=action_view, wait=True)
        elif val in ("pull_1", "pull_10"):
            count = 1 if val == "pull_1" else 10
            repull_view = GachaPullAgainView(interaction.user)
            await repull_view._handle_repull(interaction, count)
        elif val == "fishing_cast":
            fishing_cog = self.bot_instance.get_cog("FishingCog")
            if fishing_cog:
                await fishing_cog._open_cast_hub(interaction)
            else:
                await core.safe_send_response(interaction, "❌ 낚시 모듈이 로드되지 않았습니다.", ephemeral=True)
        elif val == "fishing_rank":
            await core.safe_defer(interaction)
            from cogs.fishing import FishingRankingView
            view = FishingRankingView(interaction.user, guild_id=interaction.guild_id or 0)
            msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
            view.message = msg
        elif val == "my_chars":
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            g_key = str(interaction.guild_id or 0)
            u_key = str(interaction.user.id)
            user_cards_dict = core.safe_get_dict(data, "gacha_users", g_key, u_key, "cards")
            view = MyInventoryView(interaction.user, list(user_cards_dict.values()), items_per_page=10, guild_id=interaction.guild_id or 0)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        elif val == "pokedex":
            await core.safe_defer(interaction)
            guild_id = interaction.guild_id or 0
            stats = await asyncio.to_thread(core.get_card_pokedex_stats, guild_id, interaction.user.id)
            view = CardPokedexView(interaction.user, stats, guild_id=guild_id)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        elif val == "dup_convert":
            guild_id = interaction.guild_id or 0
            preview = await asyncio.to_thread(core.preview_duplicate_cards, guild_id, interaction.user.id)
            view = DuplicateConvertConfirmView(guild_id, interaction.user, preview)
            await core.safe_send_response(interaction, embed=view.build_preview_embed(), view=view, ephemeral=True)
        elif val == "wardrobe":
            await core.safe_defer(interaction)
            view = CharacterCostumeWardrobeView(interaction.user, guild_id=interaction.guild_id or 0)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        elif val == "master_rank":
            await core.safe_defer(interaction)
            view = MasterRankView(interaction.user, guild_id=interaction.guild_id or 0)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        elif val == "sekai_live":
            await core.safe_defer(interaction)
            view = SekaiLiveView(interaction.user, guild_id=interaction.guild_id or 0)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        elif val == "profile":
            gacha_cog = self.bot_instance.get_cog("GachaCog")
            if gacha_cog:
                await gacha_cog.my_profile_cmd.callback(gacha_cog, interaction, None)
        elif val == "gacha_rank":
            gacha_cog = self.bot_instance.get_cog("GachaCog")
            if gacha_cog:
                await gacha_cog.gacha_ranking_cmd.callback(gacha_cog, interaction)
        elif val == "server_log":
            logger_cog = self.bot_instance.get_cog("LoggerCog")
            if logger_cog:
                await logger_cog.set_server_log_channel_cmd.callback(logger_cog, interaction, None, None)
        elif val == "music_now":
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            prefs = core.as_dict(data.get("music_prefs")) or core.DEFAULT_CONFIG["music_prefs"]
            track_info, error = await core.get_recommended_music(prefs)
            if error or not track_info:
                await interaction.followup.send(f"❌ **음악 추천 실패:** {error}", ephemeral=True)
                return
            embed, view = self.bot_instance.build_music_embed_and_view(track_info, prefs, is_morning=False)
            await interaction.followup.send(embed=embed, view=view, wait=True)
        elif val == "music_vault":
            music_cog = self.bot_instance.get_cog("MusicCog")
            if music_cog:
                await music_cog.my_music_library_cmd.callback(music_cog, interaction)
        elif val == "playlist":
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            studio = PlaylistStudioView(interaction.user, interaction.user, data)
            await interaction.followup.send(embed=studio.build_embed(), view=studio, wait=True)
        elif val == "dday_list":
            dday_cog = self.bot_instance.get_cog("DDayCog")
            if dday_cog:
                await dday_cog.list_dday.callback(dday_cog, interaction)
        elif val == "dday_past":
            dday_cog = self.bot_instance.get_cog("DDayCog")
            if dday_cog:
                await dday_cog.past_dday_cmd.callback(dday_cog, interaction)
        elif val == "birthday":
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            view = BirthdayBoardView(interaction.user, interaction.guild, data)
            await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        elif val == "reminder":
            await core.safe_defer(interaction, ephemeral=True)
            data = await asyncio.to_thread(core.load_data)
            view = ReminderHubView(interaction.user, interaction.channel_id, interaction.guild_id, data)
            await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        elif val == "weather":
            stats_cog = self.bot_instance.get_cog("StatsCog")
            if stats_cog:
                await stats_cog.accurate_weather_cmd.callback(stats_cog, interaction, "서울")
        elif val == "word_chain":
            stats_cog = self.bot_instance.get_cog("StatsCog")
            if stats_cog:
                await stats_cog.word_chain_game_cmd.callback(stats_cog, interaction, None, None)
        elif val == "roulette":
            stats_cog = self.bot_instance.get_cog("StatsCog")
            if stats_cog:
                await stats_cog.russian_roulette_cmd.callback(stats_cog, interaction, 1, 50)
        elif val == "user_info":
            stats_cog = self.bot_instance.get_cog("StatsCog")
            if stats_cog:
                await stats_cog.user_profile_info_cmd.callback(stats_cog, interaction, None)
        elif val == "server_stats":
            stats_cog = self.bot_instance.get_cog("StatsCog")
            if stats_cog:
                await stats_cog.server_stats_cmd.callback(stats_cog, interaction, None, None)
        elif val == "dday_secret":
            await core.safe_defer(interaction, ephemeral=True)
            data = await asyncio.to_thread(core.load_data)
            u_key = str(interaction.user.id)
            prof = core.ensure_user_profile(data, u_key, interaction.user.display_name)
            view = SecretDDayHubView(interaction.user, core.as_dict(prof.get("secret_ddays")))
            await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        elif val == "partner":
            dday_cog = self.bot_instance.get_cog("DDayCog")
            if dday_cog:
                await dday_cog.partner_cmd.callback(dday_cog, interaction, None, None, None, None)
        elif val == "suggest":
            sugg_view = SuggestionTypeSelectView(self.bot_instance)
            await core.safe_send_response(interaction, embed=sugg_view.build_overview_embed(), view=sugg_view, ephemeral=True)
        elif val == "help":
            embed = build_help_embed("all")
            await core.safe_send_response(interaction, embed=embed, view=HelpCategoryView(bot_instance=self.bot_instance, author=interaction.user), ephemeral=True)
        else:
            await core.safe_send_response(interaction, content=f"💡 선택하신 기능(`/{val}`)은 채팅창에 직접 명령어를 입력하여 실행할 수 있습니다.", ephemeral=True)


class QuickMenuHubView(core.SafeView):
    """이전 빠른 메뉴 호환 래퍼 — 통합 설정 허브(/설정, MasterDashboardView)로 즉시 연결"""
    def __new__(cls, bot_instance=None, user: discord.User | discord.Member | None = None, guild: discord.Guild | None = None, data: dict | None = None, **kwargs):
        from cogs.dashboard import MasterDashboardView
        bot_obj = bot_instance or kwargs.get("bot")
        return MasterDashboardView(bot=bot_obj, user=user, guild=guild, data=data)


# ==========================================
# 은하수 잔디 심기 (To-Do 트래커) Modal & View 클래스
# ==========================================
class TodoAddModal(core.SafeModal, title="🌱 오늘의 새 목표 추가"):
    task_title = discord.ui.TextInput(
        label="오늘 달성할 목표를 입력하세요",
        placeholder="예: 정처기 실기 기출 1회분 풀기, 알고리즘 2문제",
        required=True,
        max_length=80
    )

    def __init__(self, tracker_view):
        super().__init__()
        self.tracker_view = tracker_view

    async def on_submit(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(self.tracker_view.user.id)
        profile = core.ensure_user_profile(data, u_key, self.tracker_view.user.display_name)
        todo = core.ensure_user_todo_today(profile)
        if len(todo["tasks"]) >= 15:
            await interaction.followup.send("❌ 하루 목표는 최대 15개까지 등록할 수 있습니다.", ephemeral=True)
            return

        todo["tasks"].append({"title": self.task_title.value.strip(), "done": False})
        core.sync_todo_history_today(todo)
        await asyncio.to_thread(core.save_data, data)

        self.tracker_view.profile = profile
        self.tracker_view.update_select_options()
        await interaction.edit_original_response(embed=self.tracker_view.build_embed(), view=self.tracker_view)


class TodoTrackerView(core.SafeView):
    """오늘의 목표 체크박스 전환 및 7일간의 은하수 잔디 시각화 뷰"""
    def __init__(self, user: discord.User, profile: dict):
        super().__init__(timeout=600)
        self.user = user
        self.profile = profile
        self.update_select_options()

    def update_select_options(self):
        todo = core.ensure_user_todo_today(self.profile)
        tasks_list = [t for t in (todo.get("tasks") or []) if isinstance(t, dict)]
        if not tasks_list:
            self.toggle_select.options = [discord.SelectOption(label="등록된 목표가 없습니다", value="NONE")]
            self.toggle_select.disabled = True
        else:
            opts = []
            for idx, t in enumerate(tasks_list):
                status_icon = "✅" if t.get("done") else "⬜"
                label = f"{idx + 1}. {t.get('title', '목표')}"[:95]
                desc = "클릭하여 미완료로 변경" if t.get("done") else "클릭하여 완료(🌌) 체크!"
                opts.append(discord.SelectOption(label=label, value=str(idx), emoji=status_icon, description=desc))
            self.toggle_select.options = opts
            self.toggle_select.disabled = False

    def build_embed(self):
        todo = core.ensure_user_todo_today(self.profile)
        tasks_list = [t for t in (todo.get("tasks") or []) if isinstance(t, dict)]
        done_cnt = sum(1 for t in tasks_list if t.get("done"))
        tot_cnt = len(tasks_list)

        grass_bar, grass_details = core.get_todo_galaxy_grass(self.profile)

        if tot_cnt == 0:
            prog_bar = "🌠" + ("🌑" * 9) + " **0%** (목표를 추가해 보세요!)"
        elif done_cnt >= tot_cnt:
            prog_bar = "✨" * 10 + " **100% (오늘의 은하수 잔디 완성!)**"
        else:
            pct = int((done_cnt / tot_cnt) * 100)
            filled = min(9, pct // 10)
            prog_bar = ("🌌" * filled) + "🌠" + ("🌑" * max(0, 9 - filled)) + f" **{pct}%** (`{done_cnt}/{tot_cnt}` 완료)"

        embed = discord.Embed(
            title=f"🌱 {self.user.display_name}님의 은하수 잔디 & 오늘목표 트래커",
            description=f"• **기준 날짜:** `{core.get_today_str()}`\n└ {prog_bar}",
            color=discord.Color.from_rgb(0, 204, 221) if done_cnt < tot_cnt else discord.Color.from_rgb(255, 105, 180),
            timestamp=datetime.datetime.now(core.KST)
        )

        if not tasks_list:
            embed.add_field(
                name="📋 오늘의 목표 목록",
                value="아직 등록된 목표가 없습니다. 아래 **`[➕ 새 목표 추가]`** 버튼을 눌러 할 일을 등록해 보세요!",
                inline=False
            )
        else:
            lines = []
            for idx, t in enumerate(tasks_list, start=1):
                if t.get("done"):
                    lines.append(f"✅ ~~**{idx}. {t.get('title')}**~~ *(완료!)*")
                else:
                    lines.append(f"⬜ **{idx}. {t.get('title')}**")
            embed.add_field(name=f"📋 오늘의 목표 ({done_cnt}/{tot_cnt})", value="\n".join(lines), inline=False)

        embed.add_field(
            name="🌌 최근 7일 은하수 잔디 기록 (🟪: 하드코어 완주 · 🌌: 100% · 🌠: 진행중 · 🌑: 미달성)",
            value=f"{grass_bar}\n\n{grass_details}",
            inline=False
        )
        embed.set_footer(text="아래 메뉴에서 목표를 선택하면 완료(✅)/미완료(⬜) 상태가 즉시 전환됩니다.")
        return embed

    @discord.ui.select(
        placeholder="☑️ 완료/취소할 오늘의 목표를 선택하세요...",
        row=0,
        options=[discord.SelectOption(label="목표 선택", value="NONE")]
    )
    async def toggle_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 목표 보드만 조작할 수 있습니다.", ephemeral=True)
            return

        val = select.values[0]
        if val == "NONE":
            await core.safe_defer(interaction)
            return

        await core.safe_defer(interaction)
        idx = int(val)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(self.user.id)
        profile = core.ensure_user_profile(data, u_key, self.user.display_name)
        todo = core.ensure_user_todo_today(profile)
        if 0 <= idx < len(todo["tasks"]):
            todo["tasks"][idx]["done"] = not todo["tasks"][idx].get("done", False)
            core.sync_todo_history_today(todo)
            await asyncio.to_thread(core.save_data, data)

        self.profile = profile
        self.update_select_options()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="➕ 새 목표 추가", style=discord.ButtonStyle.primary, row=1)
    async def add_task_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 목표 보드만 조작할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(TodoAddModal(self))

    @discord.ui.button(label="🧹 완료된 목표 비우기", style=discord.ButtonStyle.secondary, row=1)
    async def clear_done_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 목표 보드만 조작할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(self.user.id)
        profile = core.ensure_user_profile(data, u_key, self.user.display_name)
        todo = core.ensure_user_todo_today(profile)

        todo["tasks"] = [t for t in todo.get("tasks", []) if not t.get("done")]
        core.sync_todo_history_today(todo)
        await asyncio.to_thread(core.save_data, data)

        self.profile = profile
        self.update_select_options()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="✅ 전체 완료", style=discord.ButtonStyle.success, row=1)
    async def complete_all_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 목표 보드만 조작할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(self.user.id)
        profile = core.ensure_user_profile(data, u_key, self.user.display_name)
        todo = core.ensure_user_todo_today(profile)

        tasks_list = [t for t in todo.get("tasks", []) if isinstance(t, dict)]
        if not tasks_list:
            await interaction.followup.send("📭 완료 처리할 목표가 없습니다. 먼저 새 목표를 추가해 보세요!", ephemeral=True)
            return

        for t in tasks_list:
            t["done"] = True
        core.sync_todo_history_today(todo)
        await asyncio.to_thread(core.save_data, data)

        self.profile = profile
        self.update_select_options()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_todo_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(self.user.id)
        self.profile = core.ensure_user_profile(data, u_key, self.user.display_name)
        self.update_select_options()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)


# ==========================================
# 출석 랭킹 (서버별 독립 랭킹 / 전체 서버 통합 랭킹 실시간 전환) UI 클래스
# ==========================================
class AttendanceRankingView(core.SafeView):
    """현재 서버 독립 출석 랭킹 & 전체 서버 통합 출석 랭킹 실시간 전환 및 페이징 뷰"""
    def __init__(self, interaction: discord.Interaction, data: dict, initial_scope: str = "guild", initial_sort: str = "total"):
        super().__init__(timeout=600)
        self.guild = interaction.guild
        self.caller = interaction.user
        self.data = data
        self.scope = initial_scope if self.guild else "global"
        self.sort_by = initial_sort
        self.current_page = 0
        self.items_per_page = 10
        self.entries = []
        self.refresh_entries()

    def refresh_entries(self):
        today_str = core.get_today_str()
        yesterday_str = core.get_yesterday_str()
        raw_list = []
        if self.scope == "guild" and self.guild:
            g_map = core.safe_get_dict(self.data, "guild_attendance", str(self.guild.id))
            for uid_str, info in g_map.items():
                if not isinstance(info, dict):
                    continue
                total_d = info.get("total_days", 0)
                last_d = info.get("last_date", "")
                # 오늘/어제 출석하지 않은 유저는 활성 연속 출석 0일로 처리 (최고 기록은 보존)
                eff_streak = info.get("streak", 0) if last_d in (today_str, yesterday_str) else 0
                max_s = max(info.get("max_streak", 0), eff_streak)
                if total_d > 0:
                    prof = core.safe_get_dict(self.data, "user_profiles", uid_str)
                    oshi_val = prof.get("oshi")
                    u_name = info.get("user_name") or core.as_dict(prof.get("attendance")).get("user_name") or f"User({uid_str[:4]})"
                    raw_list.append({
                        "uid": uid_str,
                        "name": u_name,
                        "total": total_d,
                        "streak": eff_streak,
                        "max_streak": max_s,
                        "last_date": last_d,
                        "oshi": oshi_val
                    })
        else:
            for uid_str, p_info in core.safe_get_dict(self.data, "user_profiles").items():
                if not isinstance(p_info, dict):
                    continue
                att = core.as_dict(p_info.get("attendance"))
                total_d = att.get("total_days", 0)
                last_d = att.get("last_date", "")
                eff_streak = att.get("streak", 0) if last_d in (today_str, yesterday_str) else 0
                max_s = max(att.get("max_streak", 0), eff_streak)
                if total_d > 0:
                    raw_list.append({
                        "uid": uid_str,
                        "name": att.get("user_name") or f"User({uid_str[:4]})",
                        "total": total_d,
                        "streak": eff_streak,
                        "max_streak": max_s,
                        "last_date": last_d,
                        "oshi": p_info.get("oshi")
                    })

        if self.sort_by == "streak":
            raw_list.sort(key=lambda x: (-x["streak"], -x["max_streak"], -x["total"]))
        else:
            raw_list.sort(key=lambda x: (-x["total"], -x["streak"], -x["max_streak"]))

        self.entries = raw_list
        self.update_buttons()

    @property
    def max_page(self):
        if not self.entries:
            return 0
        return (len(self.entries) - 1) // self.items_per_page

    def update_buttons(self):
        self.guild_scope_btn.disabled = (self.guild is None)
        self.guild_scope_btn.style = discord.ButtonStyle.primary if self.scope == "guild" else discord.ButtonStyle.secondary
        self.global_scope_btn.style = discord.ButtonStyle.primary if self.scope == "global" else discord.ButtonStyle.secondary
        self.sort_total_btn.style = discord.ButtonStyle.success if self.sort_by == "total" else discord.ButtonStyle.secondary
        self.sort_streak_btn.style = discord.ButtonStyle.success if self.sort_by == "streak" else discord.ButtonStyle.secondary
        self.prev_page_btn.disabled = (self.current_page <= 0)
        self.page_indicator_btn.label = f"📄 {self.current_page + 1} / {self.max_page + 1}"
        self.next_page_btn.disabled = (self.current_page >= self.max_page)
        core.sync_page_number_buttons(
            self,
            current_page=self.current_page,
            total_pages=self.max_page + 1,
            row=2,
            on_select=self._on_page_num_selected,
            zero_indexed=True,
            max_buttons=5,
            active_style=discord.ButtonStyle.primary,
            custom_id_prefix="norosi:AttRank:p",
        )

    async def _on_page_num_selected(self, interaction: discord.Interaction, target_page: int):
        self.current_page = target_page
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def build_embed(self):
        self.update_buttons()
        scope_title = f"🏠 {self.guild.name} 서버 출석 랭킹" if (self.scope == "guild" and self.guild) else "🌍 전체 서버 통합 출석 랭킹"
        sort_label = "📅 누적 출석일순" if self.sort_by == "total" else "🔥 연속 출석일순"

        embed = discord.Embed(
            title=f"🏆 {scope_title}",
            description=(
                f"• **정렬 기준:** `{sort_label}` (참여 유저: **{len(self.entries):,}명**)\n"
                f"• **출석 방식:** 각 서버별 1일 1회 독립 출석 (매일 자정 `00:00 KST` 초기화)"
            ),
            color=discord.Color.gold() if self.scope == "global" else discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )

        start_idx = self.current_page * self.items_per_page
        page_items = self.entries[start_idx:start_idx + self.items_per_page]

        if not page_items:
            embed.add_field(
                name="📭 아직 출석 기록이 없습니다",
                value="`/설정` (`📅 일일 출석체크`)으로 첫 출석의 주인공이 되어보세요!",
                inline=False
            )
        else:
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            lines = []
            for rank_idx, item in enumerate(page_items, start=start_idx + 1):
                rank_badge = medals.get(rank_idx, f"**{rank_idx}위.**")
                oshi_tag = f" · 💖 {item['oshi']}" if item.get("oshi") else ""
                user_display = f"<@{item['uid']}> (`{item['name']}`)" if self.scope == "global" else f"<@{item['uid']}>"
                lines.append(
                    f"{rank_badge} {user_display}{oshi_tag}\n"
                    f"   └ 📅 누적: **`{item['total']:,}일`** · 🔥 연속: **`{item['streak']:,}일`** (최고 `{item['max_streak']:,}일`)"
                )
            embed.add_field(
                name=f"📊 순위표 (페이지 {self.current_page + 1} / {self.max_page + 1})",
                value="\n\n".join(lines),
                inline=False
            )

        caller_uid = str(self.caller.id)
        my_rank = next((i + 1 for i, e in enumerate(self.entries) if e["uid"] == caller_uid), None)
        if my_rank:
            my_info = self.entries[my_rank - 1]
            embed.set_footer(
                text=f"나의 순위: {my_rank}위 / {len(self.entries)}명 (누적 {my_info['total']}일 • 연속 {my_info['streak']}일)"
            )
        else:
            embed.set_footer(text="나의 순위: 미등록 (/설정 ➔ 일일 출석체크로 출석을 시작해 보세요!)")

        return embed

    @discord.ui.button(label="🏠 현재 서버 랭킹", style=discord.ButtonStyle.primary, row=0)
    async def guild_scope_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.data = core.get_cached_data()
        self.scope = "guild"
        self.current_page = 0
        self.refresh_entries()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🌍 전체 서버 랭킹", style=discord.ButtonStyle.secondary, row=0)
    async def global_scope_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.data = core.get_cached_data()
        self.scope = "global"
        self.current_page = 0
        self.refresh_entries()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="📅 누적 출석순", style=discord.ButtonStyle.success, row=0)
    async def sort_total_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.data = core.get_cached_data()
        self.sort_by = "total"
        self.current_page = 0
        self.refresh_entries()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔥 연속 출석순", style=discord.ButtonStyle.secondary, row=0)
    async def sort_streak_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.data = core.get_cached_data()
        self.sort_by = "streak"
        self.current_page = 0
        self.refresh_entries()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="📄 1 / 1", style=discord.ButtonStyle.secondary, disabled=True, row=1)
    async def page_indicator_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = min(self.max_page, self.current_page + 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


def _has_dday_manage_perm(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return True
    if core.BOT_OWNER_ID and interaction.user.id == core.BOT_OWNER_ID:
        return True
    if isinstance(interaction.user, discord.Member):
        perms = interaction.user.guild_permissions
        return perms.administrator or perms.manage_guild or perms.manage_channels
    return False


# ==========================================
# D-Day 은하수 잔디 막대 그래프 대시보드 (/디데이목록) Modal & View
# ==========================================
class DDayQuickAddModal(core.SafeModal, title="📅 새 D-Day 일정 빠른 등록"):
    d_name = discord.ui.TextInput(
        label="D-Day 일정 이름",
        placeholder="예: 기말고사, 프로세카 애니버서리, 프로젝트 마감",
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
        label="진행률 시작 날짜 (YYYY-MM-DD, 비워두면 오늘)",
        placeholder="예: 2026-11-01 (은하수 잔디 진행률 0% 기준일)",
        required=False,
        max_length=10
    )
    d_emoji = discord.ui.TextInput(
        label="대표 이모지 (기본: 🌠)",
        placeholder="예: 🌠, 🔥, 🎶, 🎯",
        required=False,
        default="🌠",
        max_length=5
    )
    d_plus_one = discord.ui.TextInput(
        label="지나간 날짜 +1일 계산 (날짜가 지난 경우 전용)",
        placeholder="이미 지난 날짜에 +1일 적용 시 '+1' 또는 '예' 입력 (미입력 시 미적용)",
        required=False,
        max_length=10
    )

    def __init__(self, board_view):
        super().__init__()
        self.board_view = board_view

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
            today_str = core.get_today_str()
            start_val = min(today_str, target_val)

        plus_one_val = core.parse_dday_plus_one_flag(self.d_plus_one.value)

        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        name_val = self.d_name.value.strip()
        emoji_val = (self.d_emoji.value.strip() or "🌠")
        ddays_map = core.ensure_dict_path(data, "ddays")
        existing = core.as_dict(ddays_map.get(name_val))
        ddays_map[name_val] = {
            "date": target_val,
            "repeat": existing.get("repeat", False),
            "plus_one": plus_one_val,
            "start_date": start_val,
            "emoji": emoji_val,
            "channel_id": existing.get("channel_id"),
            "category_id": existing.get("category_id"),
            "guild_id": interaction.guild_id or existing.get("guild_id"),
        }
        await asyncio.to_thread(core.save_data, data)
        if hasattr(self.board_view.bot_instance, "update_all_dday_channels"):
            try:
                await self.board_view.bot_instance.update_all_dday_channels()
            except Exception:
                pass
        self.board_view.data = data
        await interaction.edit_original_response(embed=self.board_view.build_embed(), view=self.board_view)


class DDayListBoardView(core.SafeView):
    """
    등록된 모든 D-Day 일정의 진행 상황을 남은 기간(diff)에 따라 색상이 동적으로 변하는
    '은하수 잔디 막대 그래프'로 시각화하는 인터랙티브 대시보드 뷰 (/디데이목록)
    """
    def __init__(self, bot_instance, user: discord.User, data: dict):
        super().__init__(timeout=600)
        self.bot_instance = bot_instance
        self.user = user
        self.data = data
        self.sort_mode = "diff"      # "diff" (남은 기간 임박순) | "percent" (진행률 높은순)
        self.filter_mode = "all"     # "all" (전체) | "urgent" (7일 이내 임박/주의만)

    def build_embed(self):
        ddays = core.as_dict(self.data.get("ddays"))
        summary = core.build_dday_grass_board_summary(ddays)
        all_items = summary["items"]
        counts = summary["counts"]

        upcoming = [it for it in all_items if it["diff"] >= 0]
        recent_past = [it for it in all_items if -7 <= it["diff"] < 0]
        archived_count = sum(1 for it in all_items if it["diff"] < -7)

        if self.filter_mode == "urgent":
            filtered_upcoming = [it for it in upcoming if it["diff"] <= 7]
        else:
            filtered_upcoming = list(upcoming)

        if self.sort_mode == "percent":
            filtered_upcoming.sort(key=lambda x: (-x["percent"], x["diff"]))
        else:
            filtered_upcoming.sort(key=lambda x: (x["diff"], -x["percent"]))

        min_diff = min((it["diff"] for it in upcoming), default=-1)
        theme_rgb = core.get_dday_color_theme(min_diff)["rgb"] if upcoming else (0, 204, 221)

        embed = discord.Embed(
            title="🌌 등록된 은하수 잔디 D-Day 막대 그래프 보드",
            description=(
                "남은 기간에 따라 **은하수 잔디 막대 그래프의 색상**이 자동으로 변화합니다!\n"
                "• **색상 범례:** `🟨 D-Day(당일)` · `🟥 임박(D-1~3)` · `🟧 주의(D-4~7)` · `🟦 순항(D-8~30)` · `🟩 여유(D-31+)`\n"
                f"• **일정 분포:** 당일 `{counts['dday']}개` · 임박 `{counts['urgent']}개` · 주의 `{counts['soon']}개` · 순항 `{counts['normal']}개` · 여유 `{counts['relaxed']}개`"
            ),
            color=discord.Color.from_rgb(*theme_rgb),
            timestamp=datetime.datetime.now(core.KST)
        )

        # 1) 상단 전체 일정 은하수 잔디 비교 막대 그래프 (한눈에 보는 멀티 바 차트)
        if filtered_upcoming:
            chart_lines = []
            for it in filtered_upcoming[:10]:
                short_name = it["name"][:10].ljust(10)
                d_label = it["dday_text"].rjust(6)
                pct_label = f"{it['percent']}%".rjust(4)
                chart_lines.append(f"{it['fill_block']} [{d_label}] {short_name} │ {it['grass_bar']} {pct_label}")
            embed.add_field(
                name=f"📊 전체 일정 은하수 잔디 막대 그래프 비교 ({'7일 이내 임박 필터' if self.filter_mode == 'urgent' else '전체 진행 일정'})",
                value="```text\n" + "\n".join(chart_lines) + "\n```",
                inline=False
            )

        # 2) 일정별 상세 은하수 잔디 카드 리스트
        detail_lines = []
        for it in filtered_upcoming:
            rep_tag = " 🔄" if it["repeat"] else ""
            ch_tag = " 🔊" if it["channel_id"] else ""
            detail_lines.append(
                f"• {it['emoji']} **{it['name']}**{rep_tag}{ch_tag} (`{it['start_date']}` → `{it['date']}`) — **`{it['dday_text']}`** · {it['badge']}\n"
                f"  └ {it['grass_bar']} **`{it['percent']}%`** *(경과 {it['passed_days']}일 / 총 {it['total_days']}일)*"
            )

        core.add_chunked_embed_fields(
            embed,
            base_name=f"🌠 진행 중인 D-Day 상세 ({len(filtered_upcoming)}개)",
            lines=detail_lines,
            empty_text="조건에 해당하는 예정된 D-Day 일정이 없습니다. 아래 `[➕ 새 디데이 등록]` 버튼을 눌러 추가해 보세요!",
            separator="\n\n"
        )

        if recent_past and self.filter_mode == "all":
            past_lines = [
                f"• ~~{it['emoji']} {it['name']} ({it['date']})~~ — `{it['dday_text']}` 경과"
                f"{' `(+1일 계산)`' if it.get('plus_one') else ''}\n  └ {it['grass_bar']} `100% 완료`"
                for it in recent_past
            ]
            core.add_chunked_embed_fields(
                embed,
                base_name="🕒 최근 지난 일정 (7일 이내)",
                lines=past_lines,
                separator="\n"
            )

        footer_parts = [
            f"정렬: {'남은 기간 임박순' if self.sort_mode == 'diff' else '진행률 높은순'}",
            f"필터: {'7일 이내 임박만' if self.filter_mode == 'urgent' else '전체 일정'}"
        ]
        if archived_count > 0:
            footer_parts.append(f"7일 이상 지난 일정 {archived_count}개는 /설정 (지나간 D-Day 보관소)에서 확인 가능")
        embed.set_footer(text=" • ".join(footer_parts))
        return embed

    def _sync_sort_styles(self):
        self.sort_diff_btn.style = discord.ButtonStyle.primary if self.sort_mode == "diff" else discord.ButtonStyle.secondary
        self.sort_pct_btn.style = discord.ButtonStyle.primary if self.sort_mode == "percent" else discord.ButtonStyle.secondary

    @discord.ui.button(label="📅 남은기간 임박순", style=discord.ButtonStyle.primary, row=0)
    async def sort_diff_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.data = await asyncio.to_thread(core.load_data)
        self.sort_mode = "diff"
        self._sync_sort_styles()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="📊 진행률 높은순", style=discord.ButtonStyle.secondary, row=0)
    async def sort_pct_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.data = await asyncio.to_thread(core.load_data)
        self.sort_mode = "percent"
        self._sync_sort_styles()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔥 7일 이내 임박만 보기", style=discord.ButtonStyle.danger, row=0)
    async def toggle_urgent_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.data = await asyncio.to_thread(core.load_data)
        self.filter_mode = "all" if self.filter_mode == "urgent" else "urgent"
        button.label = "🌈 전체 일정 보기" if self.filter_mode == "urgent" else "🔥 7일 이내 임박만 보기"
        self._sync_sort_styles()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=0)
    async def refresh_dday_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.data = await asyncio.to_thread(core.load_data)
        self._sync_sort_styles()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="➕ 새 디데이 등록", style=discord.ButtonStyle.success, row=1)
    async def quick_add_dday_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DDayQuickAddModal(self))

    @discord.ui.button(label="🗑️ 디데이 삭제 (관리자)", style=discord.ButtonStyle.danger, row=1)
    async def delete_dday_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild and isinstance(interaction.user, discord.Member) and not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, "❌ 디데이 일정 삭제는 **서버 관리자**만 실행할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        ddays = core.as_dict(data.get("ddays"))
        if not ddays:
            await interaction.followup.send("📭 현재 등록된 D-Day 일정이 없습니다.", ephemeral=True)
            return
        del_view = DDayDeleteView(ddays, self.bot_instance)
        await interaction.followup.send("🗑️ 삭제할 D-Day 일정을 아래 메뉴에서 선택하세요 (연결된 전광판 채널도 함께 정리됩니다):", view=del_view, ephemeral=True, wait=True)

    @discord.ui.button(label="⚙️ 통합 설정 (/설정)", style=discord.ButtonStyle.secondary, row=1)
    async def open_menu_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        view = QuickMenuHubView(self.bot_instance, interaction.user, interaction.guild, data)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg


# ==========================================
# 비밀 디데이 & 파트너 인터랙티브 모달/허브 뷰
# ==========================================
class SecretDDayAddModal(core.SafeModal, title="🔒 비밀 디데이 & 타임캡슐 등록"):
    s_name = discord.ui.TextInput(label="비밀 디데이 이름", placeholder="예: 자격증 합격 발표, 나만의 목표일", required=True, max_length=50)
    s_date = discord.ui.TextInput(label="목표 날짜 (YYYY-MM-DD)", placeholder="예: 2026-12-25", required=True, max_length=10)
    s_memo = discord.ui.TextInput(
        label="타임캡슐 메시지 (당일 오전 9시 DM 발송)",
        style=discord.TextStyle.paragraph,
        placeholder="목표일 아침의 나에게 보낼 응원이나 다짐을 적어보세요!",
        required=False,
        max_length=300
    )
    s_plus_one = discord.ui.TextInput(
        label="지나간 날짜 +1일 계산 (날짜가 지난 경우 전용)",
        placeholder="이미 지난 날짜에 +1일 적용 시 '+1' 또는 '예' 입력 (미입력 시 미적용)",
        required=False,
        max_length=10
    )

    def __init__(self, hub_view):
        super().__init__()
        self.hub_view = hub_view

    async def on_submit(self, interaction: discord.Interaction):
        d_val = self.s_date.value.strip()
        try:
            datetime.datetime.strptime(d_val, "%Y-%m-%d")
        except ValueError:
            await core.safe_send_response(interaction, "❌ 날짜 형식은 `YYYY-MM-DD`로 입력해 주세요.", ephemeral=True)
            return

        plus_one_val = core.parse_dday_plus_one_flag(self.s_plus_one.value)

        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(self.hub_view.user.id)
        profile = core.ensure_user_profile(data, u_key, self.hub_view.user.display_name)
        s_ddays = core.ensure_dict_path(profile, "secret_ddays")
        today_str = core.get_today_str()

        s_ddays[self.s_name.value.strip()] = {
            "date": d_val,
            "memo": self.s_memo.value.strip() if self.s_memo.value else "",
            "start_date": today_str,
            "plus_one": plus_one_val,
            "notified_date": ""
        }
        await asyncio.to_thread(core.save_data, data)

        self.hub_view.s_ddays = {k: v for k, v in s_ddays.items() if isinstance(v, dict)}
        self.hub_view.update_delete_select()
        await interaction.edit_original_response(embed=self.hub_view.build_embed(), view=self.hub_view)


class SecretDDayHubView(core.SafeView):
    """/비밀디데이 명령어를 옵션 없이 쳐도 버튼과 모달로 추가/삭제할 수 있는 뷰"""
    def __init__(self, user: discord.User, s_ddays: dict):
        super().__init__(timeout=600)
        self.user = user
        self.s_ddays = {k: v for k, v in core.as_dict(s_ddays).items() if isinstance(v, dict)}
        self.update_delete_select()

    def update_delete_select(self):
        if not self.s_ddays:
            self.del_select.options = [discord.SelectOption(label="등록된 비밀 디데이가 없습니다", value="NONE")]
            self.del_select.disabled = True
        else:
            opts = []
            seen_vals = set()
            for s_name, s_info in sorted(self.s_ddays.items(), key=lambda x: x[1].get("date", "")):
                val = str(s_name)[:100]
                if not val or val in seen_vals:
                    continue
                seen_vals.add(val)
                opts.append(discord.SelectOption(
                    label=str(s_name)[:95],
                    value=val,
                    description=f"목표일: {s_info.get('date', '-')} | 선택 시 즉시 삭제",
                    emoji="🗑️"
                ))
                if len(opts) >= 25:
                    break
            if not opts:
                self.del_select.options = [discord.SelectOption(label="등록된 비밀 디데이가 없습니다", value="NONE")]
                self.del_select.disabled = True
            else:
                self.del_select.options = opts
                self.del_select.disabled = False

    def build_embed(self):
        embed = discord.Embed(
            title=f"🔒 {self.user.display_name}님의 비밀 디데이 & 타임캡슐 보드",
            color=discord.Color.from_rgb(255, 105, 180),
            timestamp=datetime.datetime.now(core.KST)
        )
        if not self.s_ddays:
            embed.description = (
                "📭 등록된 비밀 디데이가 없습니다.\n"
                "아래 **`[➕ 비밀 디데이 추가]`** 버튼을 눌러 나만 볼 수 있는 일정과 타임캡슐 메시지를 등록해 보세요!"
            )
        else:
            lines = []
            for s_name, s_info in sorted(self.s_ddays.items(), key=lambda x: x[1].get("date", "")):
                d_str = s_info.get("date", core.get_today_str())
                plus_one = bool(s_info.get("plus_one", False))
                diff, text = core.get_dday_info(d_str, plus_one=plus_one)
                plus_tag = " `(+1일)`" if (diff < 0 and plus_one) else ""
                bar_str = core.get_galaxy_progress_bar(s_info.get("start_date", core.get_today_str()), d_str)
                memo_preview = f"\n  └ 💌 타임캡슐: `{s_info['memo']}`" if s_info.get("memo") else ""
                lines.append(f"• **{s_name}** (`{d_str}`) — **`{text}`**{plus_tag}\n  └ {bar_str}{memo_preview}")
            embed.description = "\n\n".join(lines)[:4000]
        embed.set_footer(text="이 메시지는 본인에게만 보입니다 • 목표일 오전 9시 개인 DM으로 타임캡슐이 발송됩니다.")
        return embed

    @discord.ui.button(label="➕ 비밀 디데이 & 타임캡슐 추가", style=discord.ButtonStyle.primary, row=0)
    async def add_secret_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 비밀 디데이 보드만 조작할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(SecretDDayAddModal(self))

    @discord.ui.select(placeholder="🗑️ 삭제할 비밀 디데이를 선택하세요...", row=1, options=[discord.SelectOption(label="선택", value="NONE")])
    async def del_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 비밀 디데이 보드만 조작할 수 있습니다.", ephemeral=True)
            return
        val = select.values[0]
        if val == "NONE":
            await core.safe_defer(interaction)
            return
        await core.safe_defer(interaction)
        u_key = str(self.user.id)

        def _do_del_secret():
            with core._DATA_LOCK:
                data = core.load_data()
                profile = core.ensure_user_profile(data, u_key, self.user.display_name)
                s_ddays = core.ensure_dict_path(profile, "secret_ddays")
                target_k = val if val in s_ddays else next((k for k in s_ddays if str(k)[:100] == val), None)
                if target_k is not None and target_k in s_ddays:
                    del s_ddays[target_k]
                    core.save_data(data)
                return {k: dict(v) for k, v in s_ddays.items() if isinstance(v, dict)}

        self.s_ddays = await asyncio.to_thread(_do_del_secret)
        self.update_delete_select()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)


class PartnerDDayAddModal(core.SafeModal, title="💖 파트너 공동 D-Day 추가"):
    p_name = discord.ui.TextInput(label="공동 D-Day 일정 이름", placeholder="예: 100일 기념일, 함께 여행 가는 날", required=True, max_length=50)
    p_date = discord.ui.TextInput(label="목표 날짜 (YYYY-MM-DD)", placeholder="예: 2026-12-25", required=True, max_length=10)
    p_plus_one = discord.ui.TextInput(
        label="지나간 날짜 +1일 계산 (날짜가 지난 경우 전용)",
        placeholder="이미 지난 날짜에 +1일 적용 시 '+1' 또는 '예' 입력 (미입력 시 미적용)",
        required=False,
        max_length=10
    )

    def __init__(self, hub_view):
        super().__init__()
        self.hub_view = hub_view

    async def on_submit(self, interaction: discord.Interaction):
        d_val = self.p_date.value.strip()
        try:
            datetime.datetime.strptime(d_val, "%Y-%m-%d")
        except ValueError:
            await core.safe_send_response(interaction, "❌ 날짜 형식은 `YYYY-MM-DD`로 입력해 주세요.", ephemeral=True)
            return

        plus_one_val = core.parse_dday_plus_one_flag(self.p_plus_one.value)

        await core.safe_defer(interaction)
        pair_key = core.get_partner_pair_key(self.hub_view.user.id, self.hub_view.partner_id)
        today_str = core.get_today_str()
        p_name_clean = self.p_name.value.strip()

        def _do_add_partner_dday():
            with core._DATA_LOCK:
                data = core.load_data()
                partners_map = core.ensure_dict_path(data, "partners")
                pair_obj = core.ensure_dict_path(partners_map, pair_key)
                if "since" not in pair_obj:
                    pair_obj["since"] = today_str
                p_ddays_map = core.ensure_dict_path(pair_obj, "ddays")
                p_ddays_map[p_name_clean] = {
                    "date": d_val,
                    "start_date": today_str,
                    "plus_one": plus_one_val,
                    "notified_date": ""
                }
                core.save_data(data)
                return data

        self.hub_view.data = await asyncio.to_thread(_do_add_partner_dday)
        self.hub_view.update_components()
        await interaction.edit_original_response(embed=self.hub_view.build_embed(), view=self.hub_view)


class PartnerHubView(core.SafeView):
    """파트너 정보 확인, 공동 디데이 모달 추가/삭제, 공유 음악 보관함 열기를 한 곳에서 조작하는 뷰"""
    def __init__(self, user: discord.User, partner_id: str, data: dict):
        super().__init__(timeout=600)
        self.user = user
        self.partner_id = str(partner_id)
        self.data = data
        self.update_components()

    def update_components(self):
        pair_key = core.get_partner_pair_key(self.user.id, self.partner_id)
        p_ddays = {k: v for k, v in core.safe_get_dict(self.data, "partners", pair_key, "ddays").items() if isinstance(v, dict)}
        if not p_ddays:
            self.del_dday_select.options = [discord.SelectOption(label="등록된 공동 D-Day가 없습니다", value="NONE")]
            self.del_dday_select.disabled = True
        else:
            opts = []
            seen_vals = set()
            for d_name, d_info in sorted(p_ddays.items(), key=lambda x: x[1].get("date", "")):
                val = str(d_name)[:100]
                if not val or val in seen_vals:
                    continue
                seen_vals.add(val)
                opts.append(discord.SelectOption(
                    label=str(d_name)[:95],
                    value=val,
                    description=f"목표일: {d_info.get('date', '-')} | 선택 시 삭제",
                    emoji="🗑️"
                ))
                if len(opts) >= 25:
                    break
            if not opts:
                self.del_dday_select.options = [discord.SelectOption(label="등록된 공동 D-Day가 없습니다", value="NONE")]
                self.del_dday_select.disabled = True
            else:
                self.del_dday_select.options = opts
                self.del_dday_select.disabled = False

    def build_embed(self):
        u_key = str(self.user.id)
        pair_key = core.get_partner_pair_key(u_key, self.partner_id)
        pair_info = core.safe_get_dict(self.data, "partners", pair_key) or {"ddays": {}, "since": core.get_today_str()}
        p_ddays = {k: v for k, v in core.as_dict(pair_info.get("ddays")).items() if isinstance(v, dict)}

        my_music_raw = core.safe_get_dict(self.data, "user_profiles", u_key).get("liked_music")
        partner_music_raw = core.safe_get_dict(self.data, "user_profiles", self.partner_id).get("liked_music")
        my_music = [m for m in (my_music_raw or []) if isinstance(m, dict)] if isinstance(my_music_raw, list) else []
        partner_music = [m for m in (partner_music_raw or []) if isinstance(m, dict)] if isinstance(partner_music_raw, list) else []
        combined_urls = {m.get("url") for m in (my_music + partner_music) if m.get("url")}

        embed = discord.Embed(
            title="💑 우리의 파트너 스페이스",
            description=(
                f"• **나의 파트너:** <@{self.partner_id}> (연결일: `{pair_info.get('since', '-')}`)\n"
                f"• **공유 음악 보관함 곡 수:** `{len(combined_urls):,}곡` (`[🎵 공유 음악 보관함]` 버튼으로 열기)"
            ),
            color=discord.Color.from_rgb(255, 105, 180),
            timestamp=datetime.datetime.now(core.KST)
        )

        lines = []
        for d_name, d_info in sorted(p_ddays.items(), key=lambda x: x[1].get("date", "")):
            d_str = d_info.get("date", core.get_today_str())
            plus_one = bool(d_info.get("plus_one", False))
            diff, d_text = core.get_dday_info(d_str, plus_one=plus_one)
            plus_tag = " `(+1일)`" if (diff < 0 and plus_one) else ""
            bar_str = core.get_galaxy_progress_bar(d_info.get("start_date", core.get_today_str()), d_str)
            lines.append(f"• **{d_name}** (`{d_str}`) — **`{d_text}`**{plus_tag}\n  └ {bar_str}")

        core.add_chunked_embed_fields(
            embed,
            base_name="📅 우리 둘만의 공동 D-Day",
            lines=lines,
            empty_text="등록된 공동 D-Day가 없습니다. 아래 **`[➕ 공동 D-Day 추가]`** 버튼을 눌러보세요!",
            separator="\n\n"
        )

        embed.set_footer(text="목표일 당일 오전 9시에 두 사람 모두에게 축하 DM이 발송됩니다.")
        return embed

    @discord.ui.button(label="➕ 공동 D-Day 추가", style=discord.ButtonStyle.primary, row=0)
    async def add_partner_dday_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) not in (str(self.user.id), str(self.partner_id)):
            await core.safe_send_response(interaction, "❌ 파트너 당사자만 공동 D-Day를 추가할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(PartnerDDayAddModal(self))

    @discord.ui.button(label="🎵 공유 음악 보관함 열기", style=discord.ButtonStyle.success, row=0)
    async def open_shared_music_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.data = await asyncio.to_thread(core.load_data)
        u_key = str(self.user.id)
        my_music_raw = core.safe_get_dict(self.data, "user_profiles", u_key).get("liked_music")
        partner_music_raw = core.safe_get_dict(self.data, "user_profiles", self.partner_id).get("liked_music")
        my_music = [m for m in (my_music_raw or []) if isinstance(m, dict)] if isinstance(my_music_raw, list) else []
        partner_music = [m for m in (partner_music_raw or []) if isinstance(m, dict)] if isinstance(partner_music_raw, list) else []

        seen_urls = set()
        shared_list = []
        for m in (my_music + partner_music):
            u = m.get("url")
            if u and u not in seen_urls:
                seen_urls.add(u)
                shared_list.append(m)

        view = MusicLibraryPaginationView("💑 우리만의 공유 음악 보관함", shared_list, items_per_page=5)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @discord.ui.select(placeholder="🗑️ 삭제할 공동 D-Day 일정을 선택하세요...", row=1, options=[discord.SelectOption(label="선택", value="NONE")])
    async def del_dday_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if str(interaction.user.id) not in (str(self.user.id), str(self.partner_id)):
            await core.safe_send_response(interaction, "❌ 파트너 당사자만 공동 D-Day를 삭제할 수 있습니다.", ephemeral=True)
            return
        val = select.values[0]
        if val == "NONE":
            await core.safe_defer(interaction)
            return
        await core.safe_defer(interaction)
        pair_key = core.get_partner_pair_key(self.user.id, self.partner_id)

        def _do_del_partner_dday():
            with core._DATA_LOCK:
                data = core.load_data()
                p_ddays = core.safe_get_dict(data, "partners", pair_key, "ddays")
                target_k = val if val in p_ddays else next((k for k in p_ddays if str(k)[:100] == val), None)
                if target_k is not None and target_k in p_ddays:
                    del p_ddays[target_k]
                    core.save_data(data)
                return data

        self.data = await asyncio.to_thread(_do_del_partner_dday)
        self.update_components()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)


# ==========================================
# 파트너 수락 / 도움말 / 디데이 삭제 / 초기화 UI 클래스
# ==========================================
class PartnerAcceptView(core.SafeView):
    """짝꿍(파트너) 신청 수락/거절 인터랙티브 뷰"""
    def __init__(self, requester: discord.User, target: discord.User):
        super().__init__(timeout=300)
        self.requester = requester
        self.target = target

    def _restore_from_message(self, interaction: discord.Interaction):
        msg = getattr(interaction, "message", None)
        if not msg:
            return
        orig_inter = getattr(msg, "interaction_metadata", None) or getattr(msg, "interaction", None)
        orig_user = getattr(orig_inter, "user", None)
        if orig_user:
            self.requester = orig_user
        if msg.mentions:
            for m in msg.mentions:
                if not orig_user or m.id != orig_user.id:
                    self.target = m
                    break

    @discord.ui.button(label="💖 파트너 수락하기", style=discord.ButtonStyle.success)
    async def accept_partner(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.requester or not self.target:
            self._restore_from_message(interaction)
        if not self.target or interaction.user.id != self.target.id:
            await core.safe_send_response(interaction, "❌ 파트너 신청을 받은 당사자만 수락할 수 있습니다.", ephemeral=True)
            return

        if self.requester and self.requester.id == self.target.id:
            await core.safe_send_response(interaction, "❌ 본인에게는 파트너 수락을 할 수 없습니다.", ephemeral=True)
            return

        if not self.requester:
            await core.safe_send_response(interaction, "❌ 신청자 정보를 확인할 수 없습니다. 다시 신청해 주세요.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        u1 = str(self.requester.id)
        u2 = str(self.target.id)
        r_name = self.requester.display_name
        t_name = self.target.display_name

        def _do_accept_partner():
            with core._DATA_LOCK:
                data = core.load_data()
                p1 = core.ensure_user_profile(data, u1, r_name)
                p2 = core.ensure_user_profile(data, u2, t_name)
                if p1.get("partner_id") and str(p1.get("partner_id")) != u2:
                    return False, "❌ 신청자가 이미 다른 유저와 파트너 상태입니다."
                if p2.get("partner_id") and str(p2.get("partner_id")) != u1:
                    return False, "❌ 이미 다른 유저와 파트너 상태입니다."
                p1["partner_id"] = u2
                p2["partner_id"] = u1
                pair_key = core.get_partner_pair_key(u1, u2)
                partners_map = core.ensure_dict_path(data, "partners")
                if pair_key not in partners_map or not isinstance(partners_map.get(pair_key), dict):
                    partners_map[pair_key] = {"ddays": {}, "since": core.get_today_str()}
                core.save_data(data)
                return True, ""

        ok, err_msg = await asyncio.to_thread(_do_accept_partner)
        if not ok:
            await interaction.followup.send(err_msg, ephemeral=True)
            return

        embed = discord.Embed(
            title="💑 새로운 파트너 탄생!",
            description=(
                f"🎉 {self.requester.mention}님과 {self.target.mention}님이 **파트너**가 되었습니다!\n\n"
                "• `/설정` (`👤 개인` ➔ `💑 파트너 스튜디오`)에서 두 사람만의 공동 D-Day와 공유 음악 보관함을 바로 열어보세요.\n"
                "• `/카드선물`로 파트너에게 보유 카드를 선물(50 크리스탈)할 수 있습니다."
            ),
            color=discord.Color.from_rgb(255, 105, 180),
            timestamp=datetime.datetime.now(core.KST)
        )
        await interaction.edit_original_response(content=None, embed=embed, view=None)

    @discord.ui.button(label="거절", style=discord.ButtonStyle.secondary)
    async def decline_partner(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.requester or not self.target:
            self._restore_from_message(interaction)
        allowed_ids = {u.id for u in (self.target, self.requester) if u is not None}
        if allowed_ids and interaction.user.id not in allowed_ids:
            await core.safe_send_response(interaction, "❌ 당사자만 누를 수 있습니다.", ephemeral=True)
            return
        embed = discord.Embed(
            title="💔 파트너 신청 취소/거절됨",
            description="파트너 연결이 취소되었습니다.",
            color=discord.Color.dark_grey()
        )
        await interaction.response.edit_message(content=None, embed=embed, view=None)


class DDayDeleteSelect(discord.ui.Select):
    def __init__(self, ddays, bot_instance):
        self.bot_instance = bot_instance
        options = []
        seen_vals = set()
        sorted_ddays = sorted({k: v for k, v in core.as_dict(ddays).items() if isinstance(v, dict)}.items(), key=lambda x: x[1].get("date", "9999-12-31"))
        for name, info in sorted_ddays:
            val = str(name)[:100]
            if not val or val in seen_vals:
                continue
            seen_vals.add(val)
            date_str = info.get("date", "")
            repeat_icon = "🔄 " if info.get("repeat") else ""
            ch_icon = "🔊채널있음 | " if info.get("channel_id") else ""
            options.append(discord.SelectOption(
                label=str(name)[:100],
                value=val,
                description=(f"{ch_icon}{repeat_icon}목표일: {date_str}" if date_str else "목표일 미지정")[:100]
            ))
            if len(options) >= 25:
                break
        if not options:
            options.append(discord.SelectOption(label="삭제할 일정이 없습니다", value="NONE"))
        super().__init__(
            placeholder="🗑️ 삭제할 일정을 선택하세요 (연결된 채널도 함께 삭제됩니다)...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="norosi:DDayDeleteView:dday_delete_select",
        )

    async def callback(self, interaction: discord.Interaction):
        selected_name = self.values[0]
        if selected_name == "NONE":
            await core.safe_defer(interaction, ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)

        ddays_map = core.ensure_dict_path(data, "ddays")
        if selected_name not in ddays_map:
            matched_key = next((k for k in ddays_map if str(k)[:100] == selected_name), None)
            if matched_key is not None:
                selected_name = matched_key
        if selected_name in ddays_map:
            dday_info = core.as_dict(ddays_map.get(selected_name))
            ch_id = dday_info.get("channel_id")
            channel_deleted_msg = ""

            if ch_id:
                ch = self.bot_instance.get_channel(int(ch_id))
                if not ch and interaction.guild:
                    try:
                        ch = await interaction.guild.fetch_channel(int(ch_id))
                    except Exception:
                        ch = None
                if ch and (not interaction.guild or getattr(ch, "guild", None) == interaction.guild):
                    try:
                        await ch.delete(reason=f"디데이 '{selected_name}' 삭제에 따른 자동 채널 삭제")
                        channel_deleted_msg = "\n• 연결된 디데이 전광판 채널도 함께 삭제되었습니다."
                    except discord.Forbidden:
                        channel_deleted_msg = "\n⚠️ 봇에게 '채널 관리' 권한이 없어 채널은 삭제하지 못했습니다."
                    except Exception:
                        pass

            def _do_remove_dday():
                with core._DATA_LOCK:
                    latest = core.load_data()
                    dmap = core.ensure_dict_path(latest, "ddays")
                    if selected_name in dmap:
                        del dmap[selected_name]
                        core.save_data(latest)

            await asyncio.to_thread(_do_remove_dday)

            embed = discord.Embed(
                title="🗑️ 디데이 및 채널 삭제 완료",
                description=f"**{selected_name}** 일정이 데이터베이스에서 제거되었습니다.{channel_deleted_msg}",
                color=discord.Color.blue()
            )
            await interaction.edit_original_response(content=None, embed=embed, view=None)
        else:
            await interaction.edit_original_response(content="❌ 이미 삭제되었거나 찾을 수 없는 일정입니다.", embed=None, view=None)


class DDayDeleteView(core.SafeView):
    def __init__(self, ddays, bot_instance):
        super().__init__(timeout=120)
        self.add_item(DDayDeleteSelect(ddays, bot_instance))


class ResetConfirmView(core.SafeView):
    def __init__(self, bot_instance):
        super().__init__(timeout=60)
        self.bot_instance = bot_instance

    @discord.ui.button(label="⚠️ 모든 데이터 및 디데이 채널 초기화 실행", style=discord.ButtonStyle.danger)
    async def confirm_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, "❌ 서버 관리자만 실행할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)

        old_data = await asyncio.to_thread(core.load_data)
        deleted_ch_count = 0
        guild_id = interaction.guild_id

        ddays = core.as_dict(old_data.get("ddays"))
        remaining_ddays = {}
        for name, info in ddays.items():
            if not isinstance(info, dict):
                continue
            d_guild_id = info.get("guild_id")
            ch_id = info.get("channel_id")
            is_this_guild = False
            if d_guild_id and guild_id and d_guild_id == guild_id:
                is_this_guild = True
            elif ch_id and interaction.guild:
                ch = interaction.guild.get_channel(int(ch_id))
                if ch:
                    is_this_guild = True
            elif not d_guild_id and not guild_id:
                is_this_guild = True

            if is_this_guild:
                if ch_id:
                    ch = self.bot_instance.get_channel(int(ch_id))
                    if ch:
                        try:
                            await ch.delete(reason="관리자 데이터 초기화 실행")
                            deleted_ch_count += 1
                        except Exception:
                            pass
            else:
                remaining_ddays[name] = info

        old_data["ddays"] = remaining_ddays
        if guild_id:
            if isinstance(old_data.get("guild_music_prefs"), dict):
                old_data["guild_music_prefs"].pop(str(guild_id), None)
            if isinstance(old_data.get("guild_settings"), dict):
                old_data["guild_settings"].pop(str(guild_id), None)
        else:
            old_data["music_prefs"] = copy.deepcopy(core.DEFAULT_CONFIG["music_prefs"])
            old_data["music_schedules"] = []

        await asyncio.to_thread(core.save_data, old_data)
        embed = discord.Embed(
            title="🔄 D-Day 및 음악 설정 초기화 완료",
            description=(
                "현재 서버의 모든 **D-Day 일정**과 **알림/음악 설정**이 안전하게 초기화되었습니다.\n"
                f"• 함께 삭제된 디데이 채널 수: `{deleted_ch_count}개`\n"
                "• 🛡️ **안전 보호됨:** 타 서버의 D-Day 및 모든 유저의 **출석 기록, 크리스탈, 보유 캐릭터, 파트너 정보**는 안전하게 보존되었습니다."
            ),
            color=discord.Color.red()
        )
        await interaction.edit_original_response(content=None, embed=embed, view=None)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def cancel_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="✅ 초기화 취소됨",
            description="데이터 초기화가 취소되어 기존 데이터가 안전하게 유지됩니다.",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(content=None, embed=embed, view=None)


# ==========================================
# D-Day / 빠른 메뉴 / 서버별 출석 / 은하수 잔디 / 파트너 / 집중모드 / 도움말 Cog
# ==========================================
class DDayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _create_or_update_dday(
        self,
        interaction: discord.Interaction,
        이름: str,
        날짜: str,
        카테고리: discord.CategoryChannel = None,
        이모지: str = "🌠",
        시작일: str = None,
        매년반복: bool | None = False,
        채널생성: bool = True,
        플러스1: bool = False,
    ):
        try:
            target_dt = datetime.datetime.strptime(날짜, "%Y-%m-%d").date()
            if 시작일:
                datetime.datetime.strptime(시작일, "%Y-%m-%d")
        except ValueError:
            await core.safe_send_response(interaction, "❌ 날짜 형식은 `YYYY-MM-DD`로 입력해 주세요.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)

        ddays_map = core.ensure_dict_path(data, "ddays")
        settings_map = core.ensure_dict_path(data, "settings")
        existing_info = core.as_dict(ddays_map.get(이름))
        existing_ch_id = existing_info.get("channel_id")
        plus_one_val = bool(플러스1)
        repeat_val = bool(existing_info.get("repeat", False)) if 매년반복 is None else bool(매년반복)

        if 시작일:
            actual_start = 시작일
        elif existing_info.get("start_date"):
            actual_start = str(existing_info["start_date"])
        else:
            actual_start = core.get_today_str()

        try:
            start_dt = datetime.datetime.strptime(actual_start, "%Y-%m-%d").date()
            if start_dt > target_dt:
                actual_start = min(core.get_today_str(), 날짜)
        except ValueError:
            actual_start = min(core.get_today_str(), 날짜)

        target_category = 카테고리
        if not target_category and settings_map.get("default_category_id") and interaction.guild:
            target_category = interaction.guild.get_channel(int(settings_map["default_category_id"]))

        created_channel = None
        channel_status_msg = "생성 안 함 (`채널생성: False`)"

        if 채널생성 and interaction.guild:
            new_ch_name = core.format_dday_channel_name(이름, 날짜, 이모지, plus_one=plus_one_val)

            if existing_ch_id:
                created_channel = interaction.guild.get_channel(int(existing_ch_id))
                if created_channel:
                    try:
                        await created_channel.edit(name=new_ch_name, category=target_category or created_channel.category)
                        channel_status_msg = f"🔊 `{created_channel.name}` (기존 채널 갱신됨)"
                    except Exception as e:
                        channel_status_msg = f"⚠️ 기존 채널 수정 실패: {e}"

            if not created_channel:
                try:
                    overwrites = {
                        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=False),
                        interaction.guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True)
                    }
                    created_channel = await interaction.guild.create_voice_channel(
                        name=new_ch_name,
                        category=target_category,
                        overwrites=overwrites,
                        reason=f"디데이 '{이름}' 전광판 채널 자동 생성"
                    )
                    cat_label = f" (카테고리: `{target_category.name}`)" if target_category else ""
                    channel_status_msg = f"🔊 `{created_channel.name}` 생성 완료{cat_label}"
                except discord.Forbidden:
                    channel_status_msg = "🚨 권한 부족: 봇에게 서버의 **'채널 관리'** 권한을 부여해 주세요."
                except Exception as e:
                    channel_status_msg = f"⚠️ 채널 생성 실패: {e}"

        ddays_map[이름] = {
            "date": 날짜,
            "repeat": repeat_val,
            "plus_one": plus_one_val,
            "start_date": actual_start,
            "emoji": 이모지,
            "channel_id": created_channel.id if created_channel else existing_ch_id,
            "category_id": target_category.id if target_category else existing_info.get("category_id"),
            "guild_id": interaction.guild_id or existing_info.get("guild_id"),
        }
        await asyncio.to_thread(core.save_data, data)

        diff, dday_text = core.get_dday_info(날짜, plus_one=plus_one_val)
        repeat_str = " (매년 반복 🔄)" if repeat_val else ""
        plus_one_line = ""
        if plus_one_val:
            if diff < 0:
                plus_one_line = f"\n• **지나간 날짜 +1일 계산:** ✅ 적용됨 (`D+{abs(diff)}` → **`{dday_text}`**)"
            else:
                plus_one_line = "\n• **지나간 날짜 +1일 계산:** ⏳ 예약됨 *(미래·당일 날짜에는 미적용, 날짜가 지난 후부터 +1 적용)*"
        bar_str = core.get_galaxy_progress_bar(actual_start, 날짜)

        embed = discord.Embed(
            title="✅ 디데이 일정 및 채널 설정 완료",
            description=(
                f"**{이름}**{repeat_str} 일정이 등록되었습니다!\n"
                f"• **기간:** `{actual_start}` → `{날짜}` (**`{dday_text}`**){plus_one_line}\n"
                f"• **전광판 채널:** {channel_status_msg}\n"
                f"└ {bar_str}"
            ),
            color=core.get_embed_color(diff)
        )
        await interaction.followup.send(embed=embed)


    @app_commands.command(name="출석체크", description="자정(00:00) 기준 각 서버별로 하루 1회 출석체크를 진행하고 출석 달력 및 개근 보상(100~2000💎)을 받습니다.")
    async def attendance_check_cmd(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        embed, file, view = await execute_and_build_attendance_response(interaction, self.bot)
        if file:
            await interaction.followup.send(embed=embed, file=file, view=view, wait=True)
        else:
            await interaction.followup.send(embed=embed, view=view, wait=True)

    @app_commands.command(name="출석달력", description="이번 달 출석한 날짜를 시각적 캘린더로 확인하고 개근 보상 마일스톤(7/14/21/28일) 현황을 조회합니다.")
    @app_commands.describe(유저="(선택) 다른 유저의 이번 달 서버 출석 캘린더를 확인합니다.")
    async def attendance_calendar_cmd(self, interaction: discord.Interaction, 유저: discord.User = None):
        await core.safe_defer(interaction)
        target_user = 유저 or interaction.user
        guild_id = interaction.guild_id or 0
        guild_name = interaction.guild.name if interaction.guild else "개인 메시지(DM)"
        cal_info = await asyncio.to_thread(
            core.build_monthly_attendance_calendar,
            guild_id,
            guild_name,
            target_user.id,
            target_user.display_name
        )
        view = AttendanceCalendarView(self.bot, target_user, cal_info)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @app_commands.command(name="출석랭킹", description="현재 서버 또는 전체 서버의 출석체크 순위(누적 출석일 / 연속 출석일)를 확인합니다.")
    @app_commands.describe(
        범위="조회할 랭킹 범위를 선택하세요 (기본: 현재 서버 랭킹)",
        기준="정렬할 기준을 선택하세요 (기본: 누적 출석일순)"
    )
    @app_commands.choices(
        범위=[
            app_commands.Choice(name="🏠 현재 서버 출석 랭킹", value="guild"),
            app_commands.Choice(name="🌍 전체 서버 통합 출석 랭킹", value="global")
        ],
        기준=[
            app_commands.Choice(name="📅 누적 출석일 많은순", value="total"),
            app_commands.Choice(name="🔥 현재 연속 출석일 높은순", value="streak")
        ]
    )
    async def attendance_ranking_cmd(
        self,
        interaction: discord.Interaction,
        범위: app_commands.Choice[str] = None,
        기준: app_commands.Choice[str] = None
    ):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        init_scope = 범위.value if 범위 else ("guild" if interaction.guild else "global")
        init_sort = 기준.value if 기준 else "total"

        view = AttendanceRankingView(interaction, data, initial_scope=init_scope, initial_sort=init_sort)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @app_commands.command(name="오늘목표", description="오늘의 할 일(To-Do)을 체크하고 최근 7일간의 은하수 잔디(🌌🌠🌑)를 심습니다.")
    @app_commands.describe(
        새목표="(선택) 바로 추가할 오늘의 목표 내용 (미입력 시 내 목표 보드와 잔디를 엽니다)"
    )
    async def todo_grass_cmd(self, interaction: discord.Interaction, 새목표: str = None):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(interaction.user.id)
        profile = core.ensure_user_profile(data, u_key, interaction.user.display_name)
        todo = core.ensure_user_todo_today(profile)

        if 새목표 and 새목표.strip():
            if len(todo["tasks"]) < 15:
                todo["tasks"].append({"title": 새목표.strip(), "done": False})
                core.sync_todo_history_today(todo)

        await asyncio.to_thread(core.save_data, data)
        view = TodoTrackerView(interaction.user, profile)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)


    @app_commands.command(name="알림설정", description="오전 9시 D-Day 알림을 받을 텍스트 채널과 디데이 채널이 생성될 기본 카테고리를 설정합니다.")
    @app_commands.describe(
        알림채널="매일 오전 9시 D-Day 현황 알림을 받을 텍스트 채널을 선택하세요.",
        기본카테고리="(선택) 디데이 추가 시 전광판 채널이 만들어질 기본 카테고리를 선택하세요."
    )
    async def set_dday_alert_cmd(
        self,
        interaction: discord.Interaction,
        알림채널: discord.TextChannel,
        기본카테고리: discord.CategoryChannel = None
    ):
        if not _has_dday_manage_perm(interaction):
            await core.safe_send_response(
                interaction,
                "❌ 알림 채널 및 카테고리 설정은 **서버 관리자** 또는 **채널/서버 관리 권한**이 있는 멤버만 가능합니다.",
                ephemeral=True,
            )
            return
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        settings_map = core.ensure_dict_path(data, "settings")
        settings_map["dday_alert_channel_id"] = 알림채널.id
        if 기본카테고리:
            settings_map["default_category_id"] = 기본카테고리.id
        await asyncio.to_thread(core.save_data, data)

        cat_id = settings_map.get("default_category_id")
        cat_obj = interaction.guild.get_channel(int(cat_id)) if (cat_id and interaction.guild) else None
        cat_name = f"📁 `{cat_obj.name}`" if cat_obj else "미지정 (디데이 추가 시 개별 선택 가능)"

        embed = discord.Embed(
            title="🔔 D-Day 알림 및 기본 카테고리 설정 완료",
            description=(
                f"• **오전 9시 D-Day 알림 채널:** {알림채널.mention}\n"
                f"• **디데이 채널 기본 생성 카테고리:** {cat_name}"
            ),
            color=discord.Color.from_rgb(0, 204, 221)
        )
        await core.safe_send_response(interaction, embed=embed)

    @app_commands.command(name="디데이추가", description="새 D-Day 일정을 추가하고 선택한 카테고리에 디데이 전광판 채널을 생성합니다.")
    @app_commands.autocomplete(날짜=core.date_autocomplete, 시작일=core.date_autocomplete)
    @app_commands.describe(
        이름="일정 이름 (예: 시험, 여행, 기념일)",
        날짜="목표 날짜 (YYYY-MM-DD)",
        카테고리="(선택) 디데이 전광판 음성 채널을 생성할 카테고리를 선택하세요 (미선택 시 기본 카테고리 사용)",
        이모지="(선택) 채널 이름 맨 앞에 붙일 이모지 (기본값: 🌠)",
        시작일="(선택) 은하수 진행률 계산 시작일 (미입력 시 오늘부터 계산)",
        매년반복="(선택) 생일/기념일처럼 매년 반복되는 일정인가요? (기본값: False)",
        채널생성="(선택) 상단 전광판 음성 채널을 함께 생성할까요? (기본값: True)",
        플러스1="(선택) 날짜가 이미 지나간 경우 전용: +1일 계산 적용 (예: 시작 당일을 1일차로 계산, 기본값: False)"
    )
    async def add_dday(
        self,
        interaction: discord.Interaction,
        이름: str,
        날짜: str,
        카테고리: discord.CategoryChannel = None,
        이모지: str = "🌠",
        시작일: str = None,
        매년반복: bool = False,
        채널생성: bool = True,
        플러스1: bool = False,
    ):
        await self._create_or_update_dday(
            interaction,
            이름=이름,
            날짜=날짜,
            카테고리=카테고리,
            이모지=이모지,
            시작일=시작일,
            매년반복=매년반복,
            채널생성=채널생성,
            플러스1=플러스1,
        )

    @app_commands.command(name="전광판설정", description="특정 D-Day의 전광판 채널 이모지, 날짜, 카테고리를 변경하고 즉시 반영합니다.")
    @app_commands.autocomplete(날짜=core.date_autocomplete)
    @app_commands.describe(
        이름="전광판에 표시할 일정 이름",
        날짜="목표 날짜 (YYYY-MM-DD 형식)",
        카테고리="(선택) 전광판 채널을 이동시키거나 새로 만들 카테고리",
        이모지="맨 앞에 붙일 이모지 (기본값: 🌠)",
        플러스1="(선택) 날짜가 이미 지나간 경우 전용: +1일 계산 적용 (기본값: False)"
    )
    async def set_banner(
        self,
        interaction: discord.Interaction,
        이름: str,
        날짜: str,
        카테고리: discord.CategoryChannel = None,
        이모지: str = "🌠",
        플러스1: bool = False,
    ):
        await self._create_or_update_dday(
            interaction,
            이름=이름,
            날짜=날짜,
            카테고리=카테고리,
            이모지=이모지,
            시작일=None,
            매년반복=None,
            채널생성=True,
            플러스1=플러스1,
        )

    @app_commands.command(name="디데이목록", description="등록된 모든 D-Day 일정의 진행 상황을 남은 기간별 색상이 변하는 '은하수 잔디 막대 그래프'로 확인합니다.")
    async def list_dday(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await core.safe_defer(interaction)

        data = await asyncio.to_thread(core.load_data)
        view = DDayListBoardView(self.bot, interaction.user, data)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @app_commands.command(name="지나간디데이", description="목표일이 지나 추억 보관소로 이동된 지난 D-Day 일정들을 모아봅니다.")
    async def past_dday_cmd(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await core.safe_defer(interaction)

        data = await asyncio.to_thread(core.load_data)
        ddays = {k: v for k, v in core.as_dict(data.get("ddays")).items() if isinstance(v, dict)}
        past_lines = []

        for name, info in sorted(ddays.items(), key=lambda x: x[1].get("date", "9999-12-31"), reverse=True):
            date_str = info.get("date")
            if not date_str:
                continue
            plus_one = bool(info.get("plus_one", False))
            try:
                diff, text = core.get_dday_info(date_str, plus_one=plus_one)
            except Exception:
                continue
            if diff < 0:
                plus_badge = " `(+1일 계산)`" if plus_one else ""
                past_lines.append(f"• **{name}** (`{date_str}`) — `{text}` 경과{plus_badge}")

        embed = discord.Embed(
            title="📦 추억 보관소 (지나간 D-Day 목록)",
            description=("\n".join(past_lines)[:4000] if past_lines else "아직 지나간 디데이 일정이 없습니다."),
            color=discord.Color.dark_grey(),
            timestamp=datetime.datetime.now(core.KST)
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="비밀디데이", description="나만 볼 수 있는 비밀 디데이와 타임캡슐(목표일 오전 9시 DM 발송)을 관리합니다.")
    @app_commands.autocomplete(이름=core.secret_dday_name_autocomplete, 날짜=core.date_autocomplete)
    @app_commands.describe(
        동작="(선택) 미선택 시 버튼과 모달로 조작 가능한 비밀 디데이 보드를 엽니다.",
        이름="(추가/삭제 시) 비밀 디데이 일정 이름",
        날짜="(추가 시) 목표 날짜 (YYYY-MM-DD 형식)",
        타임캡슐메시지="(추가 시) D-Day 당일 오전 9시 개인 DM으로 함께 받을 나만의 메시지",
        플러스1="(추가 시·선택) 날짜가 이미 지나간 경우 전용: +1일 계산 적용 (기본값: False)"
    )
    @app_commands.choices(동작=[
        app_commands.Choice(name="🧭 비밀 디데이 인터랙티브 보드 열기", value="hub"),
        app_commands.Choice(name="➕ 비밀 디데이 & 타임캡슐 추가/수정", value="add"),
        app_commands.Choice(name="📋 내 비밀 디데이 목록 확인", value="list"),
        app_commands.Choice(name="🗑️ 내 비밀 디데이 삭제", value="delete")
    ])
    async def secret_dday_cmd(
        self,
        interaction: discord.Interaction,
        동작: app_commands.Choice[str] = None,
        이름: str = None,
        날짜: str = None,
        타임캡슐메시지: str = None,
        플러스1: bool = False,
    ):
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(interaction.user.id)
        profile = core.ensure_user_profile(data, u_key, interaction.user.display_name)
        s_ddays = core.ensure_dict_path(profile, "secret_ddays")

        mode = 동작.value if 동작 else ("add" if (이름 and 날짜) else "hub")
        if mode in ("hub", "list"):
            hub_view = SecretDDayHubView(interaction.user, s_ddays)
            await interaction.followup.send(embed=hub_view.build_embed(), view=hub_view, ephemeral=True, wait=True)
            return

        if mode == "add":
            if not 이름 or not 날짜:
                hub_view = SecretDDayHubView(interaction.user, s_ddays)
                await interaction.followup.send(
                    "ℹ️ 아래 **`[➕ 비밀 디데이 & 타임캡슐 추가]`** 버튼을 눌러 간편하게 등록해 보세요!",
                    embed=hub_view.build_embed(),
                    view=hub_view,
                    ephemeral=True, wait=True
                )
                return
            try:
                datetime.datetime.strptime(날짜, "%Y-%m-%d")
            except ValueError:
                await interaction.followup.send("❌ 날짜 형식은 `YYYY-MM-DD`로 입력해 주세요.", ephemeral=True)
                return

            today_str = core.get_today_str()
            s_ddays[이름] = {
                "date": 날짜,
                "memo": 타임캡슐메시지 or "",
                "start_date": today_str,
                "plus_one": bool(플러스1),
                "notified_date": ""
            }
            await asyncio.to_thread(core.save_data, data)
            hub_view = SecretDDayHubView(interaction.user, s_ddays)
            await interaction.followup.send(embed=hub_view.build_embed(), view=hub_view, ephemeral=True, wait=True)

        elif mode == "delete":
            if not 이름 or 이름 not in s_ddays:
                hub_view = SecretDDayHubView(interaction.user, s_ddays)
                await interaction.followup.send("ℹ️ 아래 드롭다운에서 삭제할 비밀 디데이를 선택해 주세요.", embed=hub_view.build_embed(), view=hub_view, ephemeral=True, wait=True)
                return
            del s_ddays[이름]
            await asyncio.to_thread(core.save_data, data)
            hub_view = SecretDDayHubView(interaction.user, s_ddays)
            await interaction.followup.send(f"🗑️ 비밀 디데이 **`{이름}`** 일정이 삭제되었습니다.", embed=hub_view.build_embed(), view=hub_view, ephemeral=True, wait=True)

    @app_commands.command(name="디데이삭제", description="드롭다운 메뉴에서 일정을 선택해 삭제합니다. (생성된 디데이 채널도 함께 삭제됩니다)")
    async def delete_dday(self, interaction: discord.Interaction):
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        ddays = {k: v for k, v in core.as_dict(data.get("ddays")).items() if isinstance(v, dict)}
        if not ddays:
            await core.safe_send_response(interaction, content="📭 삭제할 일정이 없습니다.", ephemeral=True)
            return
        view = DDayDeleteView(ddays, self.bot)
        await core.safe_send_response(interaction, content="아래 메뉴에서 삭제할 일정을 선택해 주세요. (연결된 전광판 채널도 자동으로 삭제됩니다)", view=view, ephemeral=True)

    @app_commands.command(name="파트너", description="연인·친구와 파트너를 맺어 공동 D-Day와 우리만의 공유 음악 보관함을 함께 사용합니다.")
    @app_commands.autocomplete(날짜=core.date_autocomplete)
    @app_commands.describe(
        동작="(선택) 미선택 시 파트너 스페이스 보드(또는 파트너 신청 안내)를 엽니다.",
        유저="(파트너 신청 시) 파트너를 맺을 디스코드 유저를 선택하세요.",
        이름="(공동 디데이 추가/삭제 시) 공동 D-Day 일정 이름",
        날짜="(공동 디데이 추가 시) 목표 날짜 (YYYY-MM-DD 형식)",
        플러스1="(공동 디데이 추가 시·선택) 날짜가 이미 지나간 경우 전용: +1일 계산 적용 (기본값: False)"
    )
    @app_commands.choices(동작=[
        app_commands.Choice(name="💑 파트너 스페이스 보드 열기", value="info"),
        app_commands.Choice(name="💌 파트너 신청하기", value="request"),
        app_commands.Choice(name="➕ 파트너 공동 D-Day 추가", value="add_dday"),
        app_commands.Choice(name="🗑️ 파트너 공동 D-Day 삭제", value="del_dday"),
        app_commands.Choice(name="🎵 우리만의 공유 음악 보관함 열기", value="music"),
        app_commands.Choice(name="💔 파트너 해제하기", value="break")
    ])
    async def partner_cmd(
        self,
        interaction: discord.Interaction,
        동작: app_commands.Choice[str] = None,
        유저: discord.User = None,
        이름: str = None,
        날짜: str = None,
        플러스1: bool = False,
    ):
        if not interaction.response.is_done():
            is_public_mode = (동작 and 동작.value in ("request", "music")) or (not 동작 and 유저 is not None)
            await core.safe_defer(interaction, ephemeral=not is_public_mode)

        u_key = str(interaction.user.id)
        data = await asyncio.to_thread(core.load_data)
        profile = core.ensure_user_profile(data, u_key, interaction.user.display_name)
        current_partner_id = profile.get("partner_id")

        if 동작:
            mode = 동작.value
        elif 유저 and not current_partner_id:
            mode = "request"
        elif 이름 and 날짜 and current_partner_id:
            mode = "add_dday"
        else:
            mode = "info"

        if mode == "request":
            if not 유저 or 유저.bot or 유저.id == interaction.user.id:
                await core.safe_send_response(interaction, content="❌ 파트너를 신청할 올바른 유저를 `유저` 옵션에 지정해 주세요.", ephemeral=True)
                return
            if current_partner_id:
                await core.safe_send_response(interaction, content=f"❌ 이미 <@{current_partner_id}>님과 파트너 상태입니다. 먼저 해제 후 신청해 주세요.", ephemeral=True)
                return

            target_partner_id = core.safe_get_dict(data, "user_profiles", str(유저.id)).get("partner_id")
            if target_partner_id:
                await core.safe_send_response(interaction, content="❌ 상대방이 이미 다른 유저와 파트너 상태입니다.", ephemeral=True)
                return

            embed = discord.Embed(
                title="💌 파트너(짝꿍) 신청 도착!",
                description=(
                    f"{유저.mention}님! {interaction.user.mention}님이 **파트너**를 신청했습니다.\n"
                    "수락하시면 두 분만의 **비공개 공동 D-Day**, **공유 음악 보관함**, **파트너 카드 선물(50 크리스탈)** 기능을 사용할 수 있습니다!"
                ),
                color=discord.Color.from_rgb(255, 105, 180)
            )
            await core.safe_send_response(interaction, content=유저.mention, embed=embed, view=PartnerAcceptView(interaction.user, 유저))

        elif mode == "info":
            if not current_partner_id:
                await core.safe_send_response(
                    interaction,
                    content="📭 현재 맺어진 파트너가 없습니다.\n`/설정` (`👤 개인` ➔ `💑 파트너 스튜디오`)에서 파트너를 맺어보세요!",
                    ephemeral=True
                )
                return
            hub_view = PartnerHubView(interaction.user, current_partner_id, data)
            await core.safe_send_response(interaction, embed=hub_view.build_embed(), view=hub_view, ephemeral=True)

        elif mode == "add_dday":
            if not current_partner_id:
                await core.safe_send_response(interaction, content="❌ 먼저 파트너를 맺어야 공동 D-Day를 등록할 수 있습니다.", ephemeral=True)
                return
            if not 이름 or not 날짜:
                hub_view = PartnerHubView(interaction.user, current_partner_id, data)
                await core.safe_send_response(
                    interaction,
                    content="ℹ️ 아래 **`[➕ 공동 D-Day 추가]`** 버튼을 눌러 간편하게 등록해 보세요!",
                    embed=hub_view.build_embed(),
                    view=hub_view,
                    ephemeral=True
                )
                return
            try:
                datetime.datetime.strptime(날짜, "%Y-%m-%d")
            except ValueError:
                await core.safe_send_response(interaction, content="❌ 날짜 형식은 `YYYY-MM-DD`로 입력해 주세요.", ephemeral=True)
                return

            pair_key = core.get_partner_pair_key(u_key, current_partner_id)
            partners_map = core.ensure_dict_path(data, "partners")
            pair_obj = core.ensure_dict_path(partners_map, pair_key)
            if "since" not in pair_obj:
                pair_obj["since"] = core.get_today_str()
            p_ddays_map = core.ensure_dict_path(pair_obj, "ddays")

            today_str = core.get_today_str()
            p_ddays_map[이름] = {
                "date": 날짜,
                "start_date": today_str,
                "plus_one": bool(플러스1),
                "notified_date": ""
            }
            await asyncio.to_thread(core.save_data, data)
            hub_view = PartnerHubView(interaction.user, current_partner_id, data)
            await core.safe_send_response(interaction, embed=hub_view.build_embed(), view=hub_view, ephemeral=True)

        elif mode == "del_dday":
            if not current_partner_id:
                await core.safe_send_response(interaction, content="❌ 연결된 파트너가 없습니다.", ephemeral=True)
                return
            pair_key = core.get_partner_pair_key(u_key, current_partner_id)
            p_ddays = core.safe_get_dict(data, "partners", pair_key, "ddays")
            if not 이름 or 이름 not in p_ddays:
                hub_view = PartnerHubView(interaction.user, current_partner_id, data)
                await core.safe_send_response(interaction, content="ℹ️ 아래 드롭다운에서 삭제할 공동 D-Day를 선택해 주세요.", embed=hub_view.build_embed(), view=hub_view, ephemeral=True)
                return
            del p_ddays[이름]
            await asyncio.to_thread(core.save_data, data)
            hub_view = PartnerHubView(interaction.user, current_partner_id, data)
            await core.safe_send_response(interaction, content=f"🗑️ 공동 D-Day **`{이름}`** 일정이 삭제되었습니다.", embed=hub_view.build_embed(), view=hub_view, ephemeral=True)

        elif mode == "music":
            if not current_partner_id:
                await core.safe_send_response(interaction, content="❌ 먼저 파트너를 맺어야 공유 음악 보관함을 열 수 있습니다.", ephemeral=True)
                return

            my_music_raw = core.safe_get_dict(data, "user_profiles", u_key).get("liked_music")
            partner_music_raw = core.safe_get_dict(data, "user_profiles", str(current_partner_id)).get("liked_music")
            my_music = [m for m in (my_music_raw or []) if isinstance(m, dict)] if isinstance(my_music_raw, list) else []
            partner_music = [m for m in (partner_music_raw or []) if isinstance(m, dict)] if isinstance(partner_music_raw, list) else []

            seen_urls = set()
            shared_list = []
            for m in (my_music + partner_music):
                u = m.get("url")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    shared_list.append(m)

            view = MusicLibraryPaginationView("💑 우리만의 공유 음악 보관함", shared_list, items_per_page=5)
            await core.safe_send_response(interaction, embed=view.build_embed(), view=view)

        elif mode == "break":
            if not current_partner_id:
                await core.safe_send_response(interaction, content="❌ 현재 연결된 파트너가 없습니다.", ephemeral=True)
                return
            u_profiles = core.ensure_dict_path(data, "user_profiles")
            core.ensure_dict_path(u_profiles, u_key)["partner_id"] = None
            if isinstance(u_profiles.get(str(current_partner_id)), dict):
                u_profiles[str(current_partner_id)]["partner_id"] = None
            await asyncio.to_thread(core.save_data, data)
            await core.safe_send_response(interaction, content=f"💔 <@{current_partner_id}>님과의 파트너 관계가 해제되었습니다.", ephemeral=True)

    @app_commands.command(name="집중모드", description="뽀모도로 스터디 타이머(집중 시 음성채널 자동 음소거, 휴식 시 해제 및 힐링 곡 추천)를 실행합니다.")
    @app_commands.describe(
        동작="집중모드 타이머 시작 또는 중지를 선택하세요.",
        집중시간="(선택) 집중할 시간(분 단위, 기본값: 25분)",
        휴식시간="(선택) 휴식할 시간(분 단위, 기본값: 5분)",
        세트수="(선택) 반복할 세트 횟수 (기본값: 1세트)",
        음성채널="(선택) 자동 음소거를 적용할 음성 채널 (미선택 시 현재 접속 중인 음성 채널 자동 인식)"
    )
    @app_commands.choices(동작=[
        app_commands.Choice(name="🔥 집중모드 시작", value="start"),
        app_commands.Choice(name="⏹️ 집중모드 중지 (음소거 즉시 해제)", value="stop")
    ])
    async def pomodoro_cmd(
        self,
        interaction: discord.Interaction,
        동작: app_commands.Choice[str],
        집중시간: int = 25,
        휴식시간: int = 5,
        세트수: int = 1,
        음성채널: discord.VoiceChannel = None
    ):
        key = (interaction.guild_id or 0, interaction.user.id)

        if 동작.value == "stop":
            task_info = core.ACTIVE_POMODORO_TASKS.pop(key, None)
            if not task_info:
                await core.safe_send_response(interaction, "ℹ️ 현재 실행 중인 집중모드 타이머가 없습니다.", ephemeral=True)
                return
            task_info["task"].cancel()
            muted_ids = task_info.get("muted_member_ids", set())
            guild = interaction.guild
            if guild:
                for m_id in muted_ids:
                    member = guild.get_member(m_id)
                    if member:
                        try:
                            await member.edit(mute=False, reason="집중모드 수동 중지")
                        except Exception:
                            pass
            v_ch = task_info.get("voice_channel")
            if v_ch:
                for member in v_ch.members:
                    if not member.bot:
                        try:
                            await member.edit(mute=False, reason="집중모드 수동 중지")
                        except Exception:
                            pass
            await core.safe_send_response(interaction, "⏹️ **집중모드 타이머가 중지되었으며 음성 채널 음소거가 해제되었습니다!**")
            return

        if key in core.ACTIVE_POMODORO_TASKS:
            await core.safe_send_response(interaction, "⚠️ 이미 실행 중인 집중모드가 있습니다. 먼저 `중지`를 선택해 종료해 주세요.", ephemeral=True)
            return

        집중시간 = max(1, min(180, 집중시간))
        휴식시간 = max(1, min(60, 휴식시간))
        세트수 = max(1, min(10, 세트수))

        target_vc = 음성채널
        if not target_vc and isinstance(interaction.user, discord.Member) and interaction.user.voice:
            target_vc = interaction.user.voice.channel

        vc_label = f"🔊 `{target_vc.name}` (집중 시간 자동 음소거 적용)" if target_vc else "미지정 (텍스트 알림 및 휴식 음악 추천만 진행)"

        embed = discord.Embed(
            title="🍅 뽀모도로 집중모드 스터디 타이머 시작!",
            description=(
                f"• **신청자:** {interaction.user.mention}\n"
                f"• **구성:** 집중 `{집중시간}분` / 휴식 `{휴식시간}분` (총 `{세트수}세트`)\n"
                f"• **연동 음성 채널:** {vc_label}\n"
                f"└ 🌠🌑🌑🌑🌑🌑🌑🌑🌑🌑 **0% (집중 시작!)**"
            ),
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(core.KST)
        )
        await core.safe_send_response(interaction, embed=embed)

        muted_member_ids: set[int] = set()
        can_mute_others = bool(
            isinstance(interaction.user, discord.Member)
            and (interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.mute_members)
        )

        async def run_pomodoro_cycle():
            try:
                for cycle in range(1, 세트수 + 1):
                    muted_count = 0
                    if target_vc:
                        for member in target_vc.members:
                            if not member.bot and (can_mute_others or member.id == interaction.user.id):
                                try:
                                    await member.edit(mute=True, reason=f"뽀모도로 집중모드 {cycle}세트 시작")
                                    muted_member_ids.add(member.id)
                                    muted_count += 1
                                except Exception:
                                    pass

                    if cycle > 1 and interaction.channel:
                        start_embed = discord.Embed(
                            title=f"🔥 집중모드 {cycle}/{세트수}세트 시작! ({집중시간}분)",
                            description=(
                                f"{interaction.user.mention}님, 다시 집중할 시간입니다!\n"
                                f"• **음성 채널 자동 음소거:** `{muted_count}명 적용됨`\n"
                                f"└ 🌠🌑🌑🌑🌑🌑🌑🌑🌑🌑 **0%**"
                            ),
                            color=discord.Color.red(),
                            timestamp=datetime.datetime.now(core.KST)
                        )
                        try:
                            await interaction.channel.send(embed=start_embed)
                        except Exception:
                            pass

                    await asyncio.sleep(집중시간 * 60)

                    guild = interaction.guild
                    if guild:
                        for m_id in list(muted_member_ids):
                            member = guild.get_member(m_id)
                            if member:
                                try:
                                    await member.edit(mute=False, reason=f"뽀모도로 휴식 시간 ({cycle}세트 완료)")
                                except Exception:
                                    pass
                    muted_member_ids.clear()

                    break_prefs = {"platform": "all", "genre": "lofi chill piano", "artist": None, "playlist_url": None}
                    track_info, _ = await core.get_recommended_music(break_prefs)

                    break_msg = (
                        f"🔔 **딩동댕! {interaction.user.mention}님, {cycle}/{세트수}세트 집중 시간({집중시간}분)이 끝났습니다!**\n"
                        f"✨✨✨✨✨✨✨✨✨✨ **100% 완료!** 이제 `{휴식시간}분` 동안 편하게 휴식하세요. (음성 채널 음소거 해제 완료)"
                    )

                    if interaction.channel:
                        try:
                            if track_info:
                                m_embed, m_view = self.bot.build_music_embed_and_view(
                                    track_info,
                                    break_prefs,
                                    custom_title=f"휴식 시간 힐링 추천 음악 ({cycle}세트 완료)"
                                )
                                await interaction.channel.send(content=break_msg, embed=m_embed, view=m_view)
                            else:
                                await interaction.channel.send(content=break_msg)
                        except Exception:
                            pass

                    if cycle < 세트수:
                        await asyncio.sleep(휴식시간 * 60)

                if interaction.channel:
                    finish_embed = discord.Embed(
                        title="🎉 뽀모도로 집중모드 전 세트 완주 성공!",
                        description=f"{interaction.user.mention}님, 목표하신 **`{세트수}세트`** 집중 스터디를 모두 마쳤습니다! 수고 많으셨어요! 👏",
                        color=discord.Color.from_rgb(0, 204, 221),
                        timestamp=datetime.datetime.now(core.KST)
                    )
                    try:
                        await interaction.channel.send(embed=finish_embed)
                    except Exception:
                        pass
            except asyncio.CancelledError:
                pass
            finally:
                core.ACTIVE_POMODORO_TASKS.pop(key, None)
                guild = interaction.guild
                if guild and muted_member_ids:
                    for m_id in list(muted_member_ids):
                        member = guild.get_member(m_id)
                        if member:
                            try:
                                await member.edit(mute=False, reason="뽀모도로 종료")
                            except Exception:
                                pass
                    muted_member_ids.clear()

        task = asyncio.create_task(run_pomodoro_cycle())
        core.ACTIVE_POMODORO_TASKS[key] = {"task": task, "voice_channel": target_vc, "muted_member_ids": muted_member_ids}

    @app_commands.command(
        name="하드코어스터디",
        description="자격증 시험/AI 코딩 전용: 50분 집중/10분 휴식 음성 안내 사이클 및 은하수 보라잔디(🟪)와 대량 크리스탈 획득"
    )
    @app_commands.describe(
        동작="하드코어 스터디 타이머 시작, 중지, 또는 현재 진행 현황을 선택하세요.",
        목표="(선택) 공부할 자격증 시험 과목이나 코딩 작업 내용 (기본값: 정보처리기능사 실기 / AI 코딩)",
        목표시간="(선택) 목표 스터디 시간 (기본값: 100분 / 2세트)",
        음성채널="(선택) 음성 안내를 진행할 음성 채널 (미선택 시 현재 접속 중인 음성 채널 자동 감지)",
        음성안내="(선택) 봇이 음성 채널에 직접 입장하여 음성(TTS)으로 시작/휴식을 안내할지 여부 (기본: 예)",
        자동음소거="(선택) 50분 집중 시간 동안 음성 채널 참가자 마이크를 자동 음소거할지 여부 (기본: 예)"
    )
    @app_commands.choices(동작=[
        app_commands.Choice(name="🔥 하드코어 스터디 시작", value="start"),
        app_commands.Choice(name="⏹️ 스터디 중지 (음소거 즉시 해제)", value="stop"),
        app_commands.Choice(name="📊 나의 하드코어 스터디 현황 및 보라잔디 조회", value="status")
    ])
    @app_commands.choices(목표시간=[
        app_commands.Choice(name="⚡ 50분 (1세트 / 집중 50분 + 휴식 10분) — 보상 💎 500개", value=50),
        app_commands.Choice(name="🔥 100분 (2세트 / 집중 100분 + 휴식 20분) [추천] — 보상 💎 1,000개", value=100),
        app_commands.Choice(name="🚀 150분 (3세트 / 집중 150분 + 휴식 30분) — 보상 💎 1,500개", value=150),
        app_commands.Choice(name="👑 200분 (4세트 / 집중 200분 + 휴식 40분) — 보상 💎 2,000개", value=200),
        app_commands.Choice(name="🏆 250분 (5세트 / 집중 250분 + 휴식 50분) — 보상 💎 2,500개", value=250),
    ])
    async def hardcore_study_cmd(
        self,
        interaction: discord.Interaction,
        동작: app_commands.Choice[str],
        목표: str = "정보처리기능사 실기 / AI 코딩",
        목표시간: int = 100,
        음성채널: discord.VoiceChannel = None,
        음성안내: bool = True,
        자동음소거: bool = True
    ):
        key = (interaction.guild_id or 0, interaction.user.id)

        # 1. 현황 조회
        if 동작.value == "status":
            data = await asyncio.to_thread(core.load_data)
            u_key = str(interaction.user.id)
            profile = core.ensure_user_profile(data, u_key, interaction.user.display_name)
            stats = profile.setdefault("hardcore_study_stats", {"total_mins": 0, "total_sets": 0, "completed_days": 0})
            grass_bar, grass_details = core.get_todo_galaxy_grass(profile)

            task_info = core.ACTIVE_HARDCORE_STUDY_TASKS.get(key)
            status_desc = "현재 실행 중인 하드코어 스터디가 없습니다."
            if task_info:
                st = task_info.get("start_time", datetime.datetime.now(core.KST))
                elapsed_min = int((datetime.datetime.now(core.KST) - st).total_seconds() // 60)
                status_desc = (
                    f"🔥 **현재 스터디 진행 중!**\n"
                    f"• **진행 세트:** `{task_info.get('current_set', 1)}/{task_info.get('num_sets', 2)}세트`\n"
                    f"• **스터디 과목:** `{task_info.get('topic', '스터디')}`\n"
                    f"• **경과 시간:** 약 `{elapsed_min}분 경과`\n"
                    f"• **연동 채널:** `{getattr(task_info.get('voice_channel'), 'name', '미지정')}`"
                )

            embed = discord.Embed(
                title=f"📊 {interaction.user.display_name}님의 하드코어 스터디 & 은하수 보라잔디(🟪) 현황",
                description=status_desc,
                color=discord.Color.purple(),
                timestamp=datetime.datetime.now(core.KST)
            )
            embed.add_field(
                name="👑 하드코어 스터디 누적 완주 업적",
                value=(
                    f"• 🟪 **완주 일수:** 총 **`{stats.get('completed_days', 0):,}일`**\n"
                    f"• ⏱️ **누적 집중 시간:** 총 **`{stats.get('total_mins', 0):,}분`** (`{stats.get('total_sets', 0):,}세트`)\n"
                    f"• 💎 **현재 보유 크리스탈:** **`{profile.get('crystals', 0):,}개`**"
                ),
                inline=False
            )
            embed.add_field(
                name="🌱 최근 7일 은하수 잔디 (🟪: 하드코어 완주 · 🌌: 100% · 🌠: 진행중 · 🌑: 미달성)",
                value=f"{grass_bar}\n\n{grass_details}",
                inline=False
            )
            embed.set_footer(text="50분 집중 / 10분 휴식 완주 시 일일 잔디가 🟪(보라색)으로 기록되며 대량 크리스탈이 지급됩니다!")
            await core.safe_send_response(interaction, embed=embed)
            return

        # 2. 중지
        if 동작.value == "stop":
            task_info = core.ACTIVE_HARDCORE_STUDY_TASKS.pop(key, None)
            if not task_info:
                await core.safe_send_response(interaction, "ℹ️ 현재 실행 중인 하드코어 스터디 타이머가 없습니다.", ephemeral=True)
                return

            task_info["task"].cancel()
            muted_ids = task_info.get("muted_member_ids", set())
            guild = interaction.guild
            if guild:
                for m_id in muted_ids:
                    member = guild.get_member(m_id)
                    if member:
                        try:
                            await member.edit(mute=False, reason="하드코어 스터디 수동 중지")
                        except Exception:
                            pass
            v_ch = task_info.get("voice_channel")
            if v_ch:
                for member in v_ch.members:
                    if not member.bot:
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

            await core.safe_send_response(interaction, "⏹️ **하드코어 스터디가 중지되었으며 음성 채널 음소거가 해제되었습니다.**")
            return

        # 3. 시작
        if key in core.ACTIVE_HARDCORE_STUDY_TASKS or key in core.ACTIVE_POMODORO_TASKS:
            await core.safe_send_response(interaction, "⚠️ 이미 실행 중인 집중/스터디 모드가 있습니다. 먼저 `중지`를 선택해 종료해 주세요.", ephemeral=True)
            return

        target_vc = 음성채널
        if not target_vc and isinstance(interaction.user, discord.Member) and interaction.user.voice:
            target_vc = interaction.user.voice.channel

        num_sets = max(1, min(10, 목표시간 // 50))
        actual_study_mins = num_sets * 50
        reward_crystals = num_sets * 500

        vc_status_str = f"🔊 `{target_vc.name}` (음성 안내 On · 자동 음소거 적용)" if target_vc else "미지정 (텍스트 알림 및 힐링 음악 안내)"

        embed = discord.Embed(
            title="🔥 [하드코어 스터디] 50분 집중 / 10분 휴식 사이클 시작!",
            description=(
                f"• 👤 **도전자:** {interaction.user.mention}\n"
                f"• 🎯 **스터디 목표:** `{목표}`\n"
                f"• ⏱️ **목표 시간:** 총 `{actual_study_mins}분` (`{num_sets}세트`)\n"
                f"• 🔊 **연동 음성 채널:** {vc_status_str}\n"
                f"• 🎁 **완주 보상:** 일일 은하수 **`🟪 보라색 잔디`** 심기 + 크리스탈 **`💎 +{reward_crystals:,}개`**\n\n"
                f"└ 🟪🌑🌑🌑🌑🌑🌑🌑🌑🌑 **0% (1세트 50분 집중 시작!)**"
            ),
            color=discord.Color.purple(),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text="중도 포기 없이 완주 시 은하수 보라잔디와 대량 크리스탈이 즉시 지급됩니다! 화이팅! 💪")
        await core.safe_send_response(interaction, embed=embed)

        # 음성 연결 준비 (음악 재생 중인 세션 하이재킹 방지)
        voice_client = None
        if 음성안내 and target_vc and interaction.guild:
            try:
                vc_existing = interaction.guild.voice_client
                if vc_existing and vc_existing.is_connected():
                    if vc_existing.is_playing() or vc_existing.is_paused():
                        voice_client = None
                    else:
                        if vc_existing.channel != target_vc:
                            await vc_existing.move_to(target_vc)
                        voice_client = vc_existing
                else:
                    voice_client = await target_vc.connect(timeout=10.0, self_deaf=False, self_mute=False)
            except Exception as vc_err:
                print(f"⚠️ [하드코어 스터디 음성 연결 예외] {vc_err}", flush=True)

        muted_member_ids: set[int] = set()
        can_mute_others = bool(
            isinstance(interaction.user, discord.Member)
            and (interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.mute_members)
        )

        info_dict = {
            "voice_channel": target_vc,
            "voice_client": voice_client,
            "start_time": datetime.datetime.now(core.KST),
            "num_sets": num_sets,
            "current_set": 1,
            "topic": 목표,
            "reward_crystals": reward_crystals,
            "muted_member_ids": muted_member_ids
        }

        async def run_hardcore_cycle():
            try:
                for cycle in range(1, num_sets + 1):
                    info_dict["current_set"] = cycle
                    muted_count = 0
                    if target_vc and 자동음소거:
                        for member in target_vc.members:
                            if not member.bot and (can_mute_others or member.id == interaction.user.id):
                                try:
                                    await member.edit(mute=True, reason=f"하드코어 스터디 {cycle}세트 집중 시작")
                                    muted_member_ids.add(member.id)
                                    muted_count += 1
                                except Exception:
                                    pass

                    # 1) 집중 시작 음성 안내 및 메시지
                    if voice_client and voice_client.is_connected() and 음성안내:
                        tts_text = f"하드코어 스터디 {cycle}세트 집중 시간을 시작합니다. 목표는 {목표}입니다. 50분 동안 집중해 주세요."
                        await core.play_tts_voice_alert(voice_client, tts_text)

                    if cycle > 1 and interaction.channel:
                        cycle_embed = discord.Embed(
                            title=f"🔥 [하드코어 스터디] {cycle}/{num_sets}세트 집중 시작! (50분)",
                            description=(
                                f"{interaction.user.mention}님, 다시 집중할 시간입니다!\n"
                                f"• 🎯 **목표:** `{목표}`\n"
                                f"• 🔇 **음성 자동 음소거:** `{muted_count}명 적용`\n"
                                f"└ 🟪🌑🌑🌑🌑🌑🌑🌑🌑🌑 **0%**"
                            ),
                            color=discord.Color.purple(),
                            timestamp=datetime.datetime.now(core.KST)
                        )
                        try:
                            await interaction.channel.send(embed=cycle_embed)
                        except Exception:
                            pass

                    # 50분 집중 대기 (50 * 60초)
                    await asyncio.sleep(50 * 60)

                    # 2) 50분 집중 완료 및 10분 휴식 시작
                    unmuted_count = 0
                    if target_vc and 자동음소거:
                        guild = interaction.guild
                        if guild:
                            for m_id in list(muted_member_ids):
                                member = guild.get_member(m_id)
                                if member:
                                    try:
                                        await member.edit(mute=False, reason=f"하드코어 스터디 {cycle}세트 완료 휴식")
                                        unmuted_count += 1
                                    except Exception:
                                        pass
                        muted_member_ids.clear()

                    if voice_client and voice_client.is_connected() and 음성안내:
                        tts_break_text = f"딩동댕! 50분 집중 시간이 끝났습니다. 음소거가 해제되었으니 10분간 편안하게 휴식을 취하세요."
                        await core.play_tts_voice_alert(voice_client, tts_break_text)

                    break_prefs = {"platform": "all", "genre": "lofi chill piano study", "artist": None, "playlist_url": None}
                    track_info, _ = await core.get_recommended_music(break_prefs)

                    break_content = (
                        f"🔔 **딩동댕! {interaction.user.mention}님, {cycle}/{num_sets}세트 50분 집중이 끝났습니다!**\n"
                        f"✨✨✨✨✨✨✨✨✨✨ **100% 완료!** 이제 `10분` 동안 편안히 휴식하세요. (음성 채널 음소거 해제 완료 ☕)"
                    )

                    if interaction.channel:
                        try:
                            if track_info and hasattr(self.bot, "build_music_embed_and_view"):
                                m_embed, m_view = self.bot.build_music_embed_and_view(
                                    track_info,
                                    break_prefs,
                                    custom_title=f"하드코어 스터디 휴식 힐링 음악 ({cycle}세트 완료)"
                                )
                                await interaction.channel.send(content=break_content, embed=m_embed, view=m_view)
                            else:
                                await interaction.channel.send(content=break_content)
                        except Exception:
                            pass

                    # 휴식 10분 대기 (마지막 세트 제외)
                    if cycle < num_sets:
                        await asyncio.sleep(10 * 60)

                # 3) 전 세트 완주 성공 처리!
                if voice_client and voice_client.is_connected() and 음성안내:
                    tts_done_text = f"축하합니다! 목표하신 하드코어 스터디를 전 세트 완주하셨습니다! 일일 은하수 잔디에 보라색 스터디 잔디가 심어졌고, {reward_crystals} 크리스탈이 지급되었습니다. 정말 수고 많으셨습니다!"
                    await core.play_tts_voice_alert(voice_client, tts_done_text)
                    await asyncio.sleep(2.0)
                    try:
                        await voice_client.disconnect()
                    except Exception:
                        pass

                # 데이터베이스 업데이트: 은하수 보라잔디(🟪) 기록 + 대량 크리스탈 지급
                data = await asyncio.to_thread(core.load_data)
                u_key = str(interaction.user.id)
                profile = core.ensure_user_profile(data, u_key, interaction.user.display_name)
                todo = core.ensure_user_todo_today(profile)
                history = core.ensure_dict_path(todo, "history")
                today_str = core.get_today_str()

                today_rec = core.ensure_dict_path(history, today_str)
                today_rec.setdefault("done", 0)
                today_rec.setdefault("total", 0)
                today_rec["hardcore_completed"] = True
                today_rec["hardcore_mins"] = today_rec.get("hardcore_mins", 0) + actual_study_mins
                today_rec["hardcore_topic"] = 목표

                profile["crystals"] = profile.get("crystals", 0) + reward_crystals
                stats = core.ensure_dict_path(profile, "hardcore_study_stats")
                stats["total_mins"] = stats.get("total_mins", 0) + actual_study_mins
                stats["total_sets"] = stats.get("total_sets", 0) + num_sets
                stats["completed_days"] = stats.get("completed_days", 0) + 1

                await asyncio.to_thread(core.save_data, data)

                grass_bar, _ = core.get_todo_galaxy_grass(profile)

                finish_embed = discord.Embed(
                    title="👑 [하드코어 스터디] 전 세트 완주 성공! 은하수 보라잔디(🟪) 심기 완료",
                    description=(
                        f"🎉 {interaction.user.mention}님, 목표하신 **`{actual_study_mins}분`** (`{num_sets}세트`) 고강도 스터디를 완주하셨습니다!\n\n"
                        f"• 🎯 **완주 과목:** `{목표}`\n"
                        f"• 🟪 **일일 은하수 잔디:** 특별 **`🟪 보라색 잔디`** 등록 완료!\n"
                        f"• 💎 **완주 보상:** 크리스탈 **`+{reward_crystals:,}개`** 지급 완료! (현재 보유: `{profile['crystals']:,}개`)\n"
                        f"• 🌱 **최근 7일 잔디:** {grass_bar}"
                    ),
                    color=discord.Color.from_rgb(155, 89, 182),
                    timestamp=datetime.datetime.now(core.KST)
                )
                finish_embed.set_footer(text="자격증 합격과 AI 코딩 정복을 응원합니다! 훌륭한 집중력이었습니다! ✨")

                if interaction.channel:
                    try:
                        view = TodoTrackerView(interaction.user, profile)
                        await interaction.channel.send(embed=finish_embed, view=view)
                    except Exception:
                        try:
                            await interaction.channel.send(embed=finish_embed)
                        except Exception:
                            pass

            except asyncio.CancelledError:
                pass
            finally:
                core.ACTIVE_HARDCORE_STUDY_TASKS.pop(key, None)
                guild = interaction.guild
                if guild and muted_member_ids:
                    for m_id in list(muted_member_ids):
                        member = guild.get_member(m_id)
                        if member:
                            try:
                                await member.edit(mute=False, reason="하드코어 스터디 종료")
                            except Exception:
                                pass
                    muted_member_ids.clear()

        task = asyncio.create_task(run_hardcore_cycle())
        info_dict["task"] = task
        core.ACTIVE_HARDCORE_STUDY_TASKS[key] = info_dict

    @app_commands.command(name="데이터초기화", description="[관리자 전용] 데이터베이스에 저장된 모든 D-Day(채널 포함) 및 음악 설정을 초기화합니다.")
    @app_commands.default_permissions(administrator=True)
    async def reset_database_cmd(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, "❌ 이 명령어는 **서버 관리자**만 사용할 수 있습니다.", ephemeral=True)
            return

        view = ResetConfirmView(self.bot)
        await core.safe_send_response(
            interaction,
            "⚠️ **경고:** 정말로 모든 D-Day 목록(생성된 디데이 채널 포함)과 알림/음악 설정 데이터를 완전히 초기화하시겠습니까?\n"
            "*(이 작업은 되돌릴 수 없으며, 아래 빨간 버튼을 누르면 즉시 삭제 및 초기화됩니다.)*",
            view=view,
            ephemeral=True
        )

    # ==========================================
    # 카테고리 2 - 1: /생일등록 & 멤버 생일 전광판
    # ==========================================
    @app_commands.command(name="생일등록", description="내 생일을 등록해 당일 자정 축하 알림과 +500💎 보너스를 받고, 서버 멤버들의 다가오는 생일 전광판을 확인합니다.")
    @app_commands.describe(
        동작="(선택) 생일 등록/수정, 전광판 조회, 생일 삭제 선택",
        월="(선택) 생일 월 (1~12월)",
        일="(선택) 생일 일 (1~31일)",
        메모="(선택) 생일 한줄 소원이나 축하받고 싶은 한마디"
    )
    @app_commands.choices(동작=[
        app_commands.Choice(name="🎂 내 생일 등록/수정", value="register"),
        app_commands.Choice(name="📋 서버 생일 전광판 보기", value="list"),
        app_commands.Choice(name="🗑️ 내 생일 정보 삭제", value="delete")
    ])
    async def birthday_manage_cmd(
        self,
        interaction: discord.Interaction,
        동작: app_commands.Choice[str] = None,
        월: app_commands.Range[int, 1, 12] = None,
        일: app_commands.Range[int, 1, 31] = None,
        메모: str = None
    ):
        await core.safe_defer(interaction, ephemeral=False)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(interaction.user.id)
        b_map = core.ensure_dict_path(data, "birthdays")
        action_val = 동작.value if 동작 else ("register" if (월 and 일) else "list")

        if action_val == "delete":
            if u_key in b_map:
                del b_map[u_key]
                await asyncio.to_thread(core.save_data, data)
                await interaction.followup.send("🗑️ 등록된 생일 정보가 삭제되었습니다.", ephemeral=True)
            else:
                await interaction.followup.send("ℹ️ 아직 등록된 생일 정보가 없습니다.", ephemeral=True)
            return

        if action_val == "register" and 월 is not None and 일 is not None:
            # 날짜 유효성 검증 (윤년 고려 2024년 기준)
            try:
                datetime.date(2024, 월, 일)
            except ValueError:
                await interaction.followup.send(f"❌ `{월}월 {일}일`은 존재하지 않는 날짜입니다. 올바른 날짜를 입력해 주세요!", ephemeral=True)
                return

            b_map[u_key] = {
                "user_id": interaction.user.id,
                "user_name": interaction.user.display_name,
                "guild_id": interaction.guild_id or 0,
                "month": 월,
                "day": 일,
                "memo": (메모 or "").strip()[:60],
                "last_celebrated_year": 0
            }
            await asyncio.to_thread(core.save_data, data)

        view = BirthdayBoardView(interaction.user, interaction.guild, data)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    # ==========================================
    # 카테고리 4 - 1: /알림예약 (개인 맞춤형 스마트 알리미)
    # ==========================================
    @app_commands.command(name="알림예약", description="'30분 뒤', '1시간 후', '15:30' 등 원하는 시각에 잊지 않도록 DM 및 채널 멘션으로 개인 알림을 보내드립니다.")
    @app_commands.describe(
        시간="(선택) 알림 받을 시간 (예: 30분 뒤, 1시간 20분 후, 15:30, 오후 8시, 미입력 시 예약 관리창 열기)",
        내용="(선택) 알림 받을 메모 내용 (예: 라면 불 끄기, 프로세카 협라 접속, 회의 참석)",
        방식="(선택) 알림 수신 방식 (DM+채널멘션 / 채널멘션만 / 개인DM만)"
    )
    @app_commands.choices(방식=[
        app_commands.Choice(name="📩 개인 DM + 현재 채널 멘션 (기본)", value="both"),
        app_commands.Choice(name="📢 현재 채널 멘션으로만 받기", value="channel"),
        app_commands.Choice(name="🔒 개인 DM으로만 조용히 받기", value="dm")
    ])
    async def reminder_schedule_cmd(
        self,
        interaction: discord.Interaction,
        시간: str = None,
        내용: str = None,
        방식: app_commands.Choice[str] = None
    ):
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)

        if 시간 and 내용:
            target_dt, err = core.parse_natural_reminder_time(시간)
            if err or not target_dt:
                await interaction.followup.send(f"❌ **시간 설정 오류:** {err}", ephemeral=True)
                return

            reminders = data.get("reminders")
            if not isinstance(reminders, list):
                reminders = []
                data["reminders"] = reminders
            rem_id = f"rem_{int(time.time())}_{interaction.user.id % 1000}"
            mode_val = 방식.value if 방식 else "both"

            reminders.append({
                "id": rem_id,
                "user_id": interaction.user.id,
                "user_name": interaction.user.display_name,
                "channel_id": interaction.channel_id or 0,
                "guild_id": interaction.guild_id or 0,
                "content": 내용.strip()[:200],
                "trigger_ts": target_dt.timestamp(),
                "trigger_str": target_dt.strftime("%Y-%m-%d %H:%M:%S KST"),
                "mode": mode_val,
                "created_at": core.get_now_datetime_str()
            })
            await asyncio.to_thread(core.save_data, data)

        view = ReminderHubView(interaction.user, interaction.channel_id, interaction.guild_id, data)
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)


# ==========================================
# 생일 등록 모달 & 전광판 뷰 (/생일등록)
# ==========================================
class BirthdayRegisterModal(core.SafeModal, title="🎂 내 생일 등록 및 수정"):
    mm_dd_input = discord.ui.TextInput(
        label="생일 월-일 입력 (MM-DD 형식)",
        placeholder="예: 02-10, 08-31, 12-25",
        required=True,
        max_length=5
    )
    memo_input = discord.ui.TextInput(
        label="생일 한줄 소원 / 메모 (선택)",
        placeholder="예: 당일 자정에 축하해 주세요! 🎉",
        required=False,
        max_length=60
    )

    def __init__(self, board_view: "BirthdayBoardView"):
        super().__init__()
        self.board_view = board_view

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.mm_dd_input.value.strip().replace("/", "-").replace(".", "-").replace(" ", "-")
        m = re.match(r"^(\d{1,2})-(\d{1,2})$", raw)
        if not m:
            await core.safe_send_response(interaction, "❌ 생일은 `MM-DD` 형식(예: `02-10`, `08-31`)으로 입력해 주세요!", ephemeral=True)
            return

        month, day = int(m.group(1)), int(m.group(2))
        try:
            datetime.date(2024, month, day)
        except ValueError:
            await core.safe_send_response(interaction, f"❌ `{month}월 {day}일`은 유효하지 않은 날짜입니다!", ephemeral=True)
            return

        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(interaction.user.id)
        core.ensure_dict_path(data, "birthdays")[u_key] = {
            "user_id": interaction.user.id,
            "user_name": interaction.user.display_name,
            "guild_id": interaction.guild_id or 0,
            "month": month,
            "day": day,
            "memo": (self.memo_input.value or "").strip(),
            "last_celebrated_year": 0
        }
        await asyncio.to_thread(core.save_data, data)
        self.board_view.data = data
        self.board_view.user = interaction.user
        try:
            await interaction.edit_original_response(embed=self.board_view.build_embed(), view=self.board_view)
        except Exception:
            if interaction.message:
                try:
                    await interaction.message.edit(embed=self.board_view.build_embed(), view=self.board_view)
                except Exception:
                    pass
        try:
            await interaction.followup.send(
                f"✅ **{interaction.user.display_name}** ({interaction.user.mention}) 님의 생일(`{month:02d}월 {day:02d}일`)이 등록되었습니다!",
                ephemeral=True,
            )
        except Exception:
            pass


class BirthdayBoardView(core.SafeView):
    def __init__(self, user: discord.User, guild: discord.Guild | None, data: dict):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.data = data

    def _days_until_birthday(self, month: int, day: int, today: datetime.date) -> int:
        try:
            this_year_bday = datetime.date(today.year, month, day)
        except ValueError:
            this_year_bday = datetime.date(today.year, 2, 28)
        if this_year_bday < today:
            try:
                next_bday = datetime.date(today.year + 1, month, day)
            except ValueError:
                next_bday = datetime.date(today.year + 1, 2, 28)
            return (next_bday - today).days
        return (this_year_bday - today).days

    def build_embed(self) -> discord.Embed:
        today = datetime.datetime.now(core.KST).date()
        b_map = core.as_dict(self.data.get("birthdays"))
        g_name = self.guild.name if self.guild else "세카이 통합"

        entries = []
        for u_key, info in b_map.items():
            if not isinstance(info, dict) or "month" not in info or "day" not in info:
                continue
            if self.guild and int(u_key) != self.user.id and not self.guild.get_member(int(u_key)):
                continue
            rem_days = self._days_until_birthday(info["month"], info["day"], today)
            entries.append((rem_days, info))

        entries.sort(key=lambda x: x[0])

        who_display = f"{self.user.mention} (`{self.user.display_name}`)"
        my_bday = b_map.get(str(self.user.id))
        if my_bday:
            my_rem = self._days_until_birthday(my_bday["month"], my_bday["day"], today)
            my_dday_str = "🎉 **오늘이 바로 생일입니다!**" if my_rem == 0 else f"`D-{my_rem}일`"
            my_status = f"✅ **`{my_bday['month']:02d}월 {my_bday['day']:02d}일`** ({my_dday_str})"
        else:
            my_status = "*(미등록 — 하단 버튼으로 내 생일을 등록해 보세요!)*"

        lines = []
        for idx, (rem_days, info) in enumerate(entries[:12], start=1):
            badge = "🎉 **[TODAY! 오늘 생일!]**" if rem_days == 0 else (f"🔥 **`D-{rem_days}`**" if rem_days <= 14 else f"`D-{rem_days}`")
            memo_part = f" — 💬 *\"{info['memo']}\"*" if info.get("memo") else ""
            lines.append(
                f"**{idx}.** 🎂 **`{info['month']:02d}월 {info['day']:02d}일`** — <@{info['user_id']}> (`{info.get('user_name', '멤버')}`) · {badge}{memo_part}"
            )

        list_str = "\n".join(lines) if lines else "아직 등록된 생일이 없습니다. 첫 번째로 생일을 등록해 보세요! 🎈"

        embed = discord.Embed(
            title=f"🎂 [{g_name}] 멤버 생일 D-Day 전광판 & 자동 축하 보드",
            description=(
                f"👤 **등록자 · 내 생일 ({who_display}):** {my_status}\n"
                f"🎁 **생일 당일 혜택:** 자정(00:00 KST) 자동 축하 메시지 & 보너스 **`+500 💎 크리스탈`** 즉시 지급!\n"
                "──────────────────────\n"
                f"### 🎈 다가오는 생일 멤버 목록 (가까운 순)\n{list_str}"
            ),
            color=discord.Color.from_rgb(255, 105, 180),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text="하단 [🎂 내 생일 등록/수정] 버튼으로 1초 만에 생일을 등록할 수 있습니다.")
        return embed

    @discord.ui.button(label="🎂 내 생일 등록/수정", style=discord.ButtonStyle.primary)
    async def register_bday_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BirthdayRegisterModal(self))

    @discord.ui.button(label="🗑️ 내 생일 삭제", style=discord.ButtonStyle.danger)
    async def delete_bday_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(interaction.user.id)
        b_map = core.ensure_dict_path(data, "birthdays")
        self.user = interaction.user
        if u_key in b_map:
            del b_map[u_key]
            await asyncio.to_thread(core.save_data, data)
            self.data = data
            if interaction.message:
                try:
                    await interaction.message.edit(embed=self.build_embed(), view=self)
                except Exception:
                    pass
            await interaction.followup.send(
                f"🗑️ **{interaction.user.display_name}** ({interaction.user.mention}) 님의 생일 정보가 삭제되었습니다.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"ℹ️ **{interaction.user.display_name}**님의 등록된 생일 정보가 없습니다.",
                ephemeral=True,
            )


# ==========================================
# 개인 스마트 알리미 모달 & 허브 뷰 (/알림예약)
# ==========================================
class ReminderAddModal(core.SafeModal, title="⏰ 새 스마트 알림 예약"):
    time_input = discord.ui.TextInput(
        label="알림 받을 시간 (자연어 또는 시각)",
        placeholder="예: 30분 뒤, 1시간 20분 후, 15:30, 오후 8시",
        required=True,
        max_length=30
    )
    content_input = discord.ui.TextInput(
        label="알림 내용 메모",
        placeholder="예: 라면 불 끄기, 프로세카 협력 라이브, 약 챙겨 먹기",
        required=True,
        max_length=150
    )

    def __init__(self, hub_view: "ReminderHubView"):
        super().__init__()
        self.hub_view = hub_view

    async def on_submit(self, interaction: discord.Interaction):
        target_dt, err = core.parse_natural_reminder_time(self.time_input.value)
        if err or not target_dt:
            await core.safe_send_response(interaction, f"❌ **시간 입력 오류:** {err}", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        reminders = data.get("reminders")
        if not isinstance(reminders, list):
            reminders = []
            data["reminders"] = reminders
        rem_id = f"rem_{int(time.time())}_{interaction.user.id % 1000}"

        reminders.append({
            "id": rem_id,
            "user_id": interaction.user.id,
            "user_name": interaction.user.display_name,
            "channel_id": interaction.channel_id or self.hub_view.channel_id or 0,
            "guild_id": interaction.guild_id or self.hub_view.guild_id or 0,
            "content": self.content_input.value.strip()[:200],
            "trigger_ts": target_dt.timestamp(),
            "trigger_str": target_dt.strftime("%Y-%m-%d %H:%M:%S KST"),
            "mode": "both",
            "created_at": core.get_now_datetime_str()
        })
        await asyncio.to_thread(core.save_data, data)
        self.hub_view.data = data
        self.hub_view.update_select()
        await interaction.edit_original_response(embed=self.hub_view.build_embed(), view=self.hub_view)


class ReminderHubView(core.SafeView):
    def __init__(self, user: discord.User, channel_id: int | None, guild_id: int | None, data: dict):
        super().__init__(timeout=300)
        self.user = user
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.data = data
        self.update_select()

    def _get_user_reminders(self) -> list[dict]:
        all_rems = self.data.get("reminders", [])
        if not isinstance(all_rems, list):
            all_rems = []
        my_rems = [r for r in all_rems if isinstance(r, dict) and r.get("user_id") == self.user.id]
        my_rems.sort(key=lambda x: x.get("trigger_ts", 0))
        return my_rems

    def update_select(self):
        my_rems = self._get_user_reminders()
        if not my_rems:
            self.cancel_select.options = [discord.SelectOption(label="대기 중인 예약 알림이 없습니다", value="NONE")]
            self.cancel_select.disabled = True
        else:
            opts = []
            for r in my_rems[:25]:
                label = f"[{r.get('trigger_str', '')[:16]}] {r.get('content', '')}"[:95]
                opts.append(discord.SelectOption(label=label, value=r.get("id", "NONE"), emoji="⏰"))
            self.cancel_select.options = opts
            self.cancel_select.disabled = False

    def build_embed(self) -> discord.Embed:
        my_rems = self._get_user_reminders()
        now_ts = time.time()

        lines = []
        for idx, r in enumerate(my_rems[:10], start=1):
            rem_sec = max(0, int(r.get("trigger_ts", now_ts) - now_ts))
            h, rem = divmod(rem_sec, 3600)
            m, s = divmod(rem, 60)
            left_str = f"{h}시간 {m}분 후" if h > 0 else (f"{m}분 {s}초 후" if m > 0 else f"{s}초 후")
            lines.append(
                f"**{idx}.** ⏰ **`{r.get('trigger_str', '-')}`** (`{left_str}`)\n"
                f"   └ 📝 내용: **{r.get('content', '')}**"
            )

        list_str = "\n\n".join(lines) if lines else "현재 예약된 개인 알림이 없습니다.\n아래 **[➕ 새 알림 예약하기]** 버튼을 눌러 간편하게 등록해 보세요!"

        embed = discord.Embed(
            title=f"⏰ {self.user.display_name}님의 스마트 개인 알리미 관리 보드",
            description=(
                "원하는 상대 시간(`30분 뒤`, `2시간 후`)이나 지정 시각(`15:30`, `오후 8시`)을 입력하면\n"
                "정확한 시각에 **개인 DM 및 채널 멘션**으로 잊지 않게 챙겨드립니다!\n"
                "──────────────────────\n"
                f"### 📋 대기 중인 내 예약 알림 ({len(my_rems)}개)\n{list_str}"
            ),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text="하단 버튼으로 새 알림을 추가하거나 드롭다운에서 기존 예약을 취소할 수 있습니다.")
        return embed

    @discord.ui.select(
        placeholder="🗑️ 취소(삭제)할 예약 알림을 선택하세요...",
        min_values=1,
        max_values=1,
        options=[discord.SelectOption(label="알림 없음", value="NONE")],
        row=0,
    )
    async def cancel_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        target_id = select.values[0]
        if target_id == "NONE":
            await core.safe_defer(interaction)
            return
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        before_list = data.get("reminders", [])
        if not isinstance(before_list, list):
            before_list = []
        data["reminders"] = [r for r in before_list if isinstance(r, dict) and r.get("id") != target_id]
        await asyncio.to_thread(core.save_data, data)
        self.data = data
        self.update_select()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="➕ 새 알림 예약하기", style=discord.ButtonStyle.primary, row=1)
    async def add_reminder_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReminderAddModal(self))


async def setup(bot):
    await bot.add_cog(DDayCog(bot))
