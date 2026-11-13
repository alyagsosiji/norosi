import os
import re
import sys
import time
import io
import copy
import json
import shutil
import random
import platform
try:
    import resource
except ImportError:
    resource = None
import datetime
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, List
import core


def build_server_stats_embed(guild: discord.Guild, data: dict, timeframe: str = "daily", mode: str = "summary") -> discord.Embed:
    """디스코드 길드의 실제 데이터(실시간 멤버, 음성 채널, 출석 현황, 봇 서비스 사용량, 채널별 메시지)를 기반으로 사실 그대로 통계를 생성합니다."""
    if not guild:
        embed = discord.Embed(
            title="📊 서버 활성도 통계 안내",
            description="❌ `/서버통계` 명령어는 디스코드 서버(길드) 채널 내에서만 사용할 수 있습니다.",
            color=discord.Color.red()
        )
        return embed

    g_key = str(guild.id)
    g_name = guild.name
    now_kst = datetime.datetime.now(core.KST)
    today_str = core.get_today_str()

    # 1. 실제 서버 기본 제원
    member_count = guild.member_count or len(guild.members) or 1
    if guild.members:
        bots_count = sum(1 for m in guild.members if m.bot)
        humans_count = max(0, member_count - bots_count)
        members_desc = f"`{member_count:,}명` (유저 `{humans_count:,}명` · 봇 `{bots_count:,}개`)"
    else:
        bots_count = 0
        humans_count = member_count
        members_desc = f"`{member_count:,}명`"

    text_chs = guild.text_channels
    voice_chs = guild.voice_channels
    roles_cnt = max(0, len(guild.roles) - 1)
    boost_cnt = getattr(guild, "premium_subscription_count", 0) or 0
    boost_lvl = getattr(guild, "premium_tier", 0) or 0
    created_str = guild.created_at.astimezone(core.KST).strftime("%Y-%m-%d") if guild.created_at else "-"

    # 2. 실시간 음성 채널 접속 인원 (100% 실시간 사실)
    active_voice_chs = [vc for vc in voice_chs if hasattr(vc, "members") and len(vc.members) > 0]
    active_voice_users = sum(len(vc.members) for vc in active_voice_chs)
    if active_voice_chs:
        vc_active_str = f"🔊 현재 `{len(active_voice_chs)}개` 채널에서 총 `{active_voice_users:,}명` 실시간 통화 중"
        vc_ch_names = ", ".join([f"`#{vc.name}` ({len(vc.members)}명)" for vc in active_voice_chs[:3]])
    else:
        vc_active_str = "🔇 현재 음성 채널 통화 멤버 없음 (`0명`)"
        vc_ch_names = "통화 중인 채널 없음"

    # 3. 실제 서버 출석체크 참여 현황 (data['guild_attendance'][g_key])
    guild_att = data.get("guild_attendance", {}).get(g_key, {})
    total_att_registered = len(guild_att)
    today_att_count = sum(1 for u in guild_att.values() if isinstance(u, dict) and u.get("last_date") == today_str)
    att_rate = round((today_att_count / max(1, member_count)) * 100, 1)
    streak_7_count = sum(1 for u in guild_att.values() if isinstance(u, dict) and u.get("streak", 0) >= 7)

    # 서버 출석 연속 1위 유저
    streak_leader_str = "기록 대기 중"
    if guild_att:
        top_u = max(guild_att.values(), key=lambda x: x.get("streak", 0) if isinstance(x, dict) else 0, default=None)
        if top_u and top_u.get("streak", 0) > 0:
            streak_leader_str = f"`{top_u.get('user_name', '유저')}` (연속 `{top_u.get('streak', 0)}일` 🔥)"

    # 4. 실제 norosi 봇 서비스 활용 지표 (D-Day, 프로세카 가챠 수집)
    ddays_cnt = sum(1 for d in data.get("ddays", {}).values() if isinstance(d, dict) and (d.get("guild_id") == guild.id or not d.get("guild_id")))
    gacha_users_cnt = len(data.get("gacha_users", {}).get(g_key, {}))
    total_cards_cnt = sum(len(u.get("cards", {})) for u in data.get("gacha_users", {}).get(g_key, {}).values() if isinstance(u, dict))

    # 5. 실제 메시지 수량 및 채널별 집계 (data['server_stats'][g_key])
    s_stats = data.get("server_stats", {}).get(g_key, {})
    is_daily = (timeframe == "daily")
    title_time = "일간 (오늘 00:00~현재)" if is_daily else "주간 (최근 7일 누적)"

    today_msgs = s_stats.get("today_msgs", 0)
    weekly_msgs = s_stats.get("weekly_msgs", 0)
    total_msgs = s_stats.get("total_msgs", 0)
    tot_msgs = today_msgs if is_daily else weekly_msgs

    channel_msgs = s_stats.get("channel_msgs", {})
    sorted_channels = sorted(
        [c for c in channel_msgs.values() if isinstance(c, dict) and c.get("count", 0) > 0],
        key=lambda x: x.get("count", 0),
        reverse=True
    )

    if sorted_channels:
        tot_denom = max(1, tot_msgs)
        display_channels = []
        for c in sorted_channels[:3]:
            c_cnt = c.get("count", 0)
            pct = round((c_cnt / tot_denom) * 100, 1) if tot_msgs > 0 else 0.0
            display_channels.append({"name": c.get("name", "#채널"), "count": c_cnt, "percent": pct})
    else:
        # 메시지 수집 전이면 실제 길드의 텍스트 채널 목록을 안전하게 노출
        display_channels = []
        for ch in text_chs[:3]:
            display_channels.append({"name": f"#{ch.name}", "count": 0, "percent": 0.0})
        if not display_channels:
            display_channels.append({"name": "#채널없음", "count": 0, "percent": 0.0})

    # 6. 시간대별 활동 분포 (실제 수집 데이터)
    hourly_msgs = s_stats.get("hourly_msgs", {})
    h_0_6 = sum(hourly_msgs.get(str(h), 0) for h in range(0, 6))
    h_6_12 = sum(hourly_msgs.get(str(h), 0) for h in range(6, 12))
    h_12_18 = sum(hourly_msgs.get(str(h), 0) for h in range(12, 18))
    h_18_24 = sum(hourly_msgs.get(str(h), 0) for h in range(18, 24))
    h_total = h_0_6 + h_6_12 + h_12_18 + h_18_24

    def make_bar(pct: float, length: int = 10) -> str:
        filled = min(length, max(0, int(round((pct / 100) * length))))
        return "█" * filled + "░" * (length - filled)

    if h_total > 0:
        p_0_6 = round((h_0_6 / h_total) * 100, 1)
        p_6_12 = round((h_6_12 / h_total) * 100, 1)
        p_12_18 = round((h_12_18 / h_total) * 100, 1)
        p_18_24 = round((h_18_24 / h_total) * 100, 1)
        periods = [
            ("00시 ~ 06시 (심야)", p_0_6, h_0_6),
            ("06시 ~ 12시 (오전)", p_6_12, h_6_12),
            ("12시 ~ 18시 (오후)", p_12_18, h_12_18),
            ("18시 ~ 24시 (저녁/야간)", p_18_24, h_18_24)
        ]
        peak_period = max(periods, key=lambda x: x[1])
        peak_str = f"`{peak_period[0]}` (`[{make_bar(peak_period[1])}] {peak_period[1]}%` Peak · `{peak_period[2]:,}개`)"
    else:
        p_0_6 = p_6_12 = p_12_18 = p_18_24 = 0.0
        peak_str = "`실시간 메시지 수집 대기 중`"

    # 메시지 표시 문자열
    if tot_msgs > 0:
        msg_val_str = f"`{tot_msgs:,}개` (전체 누적 `{total_msgs:,}개`)"
    else:
        msg_val_str = "`0개` *(실시간 채팅 수집 대기 중)*"

    if mode == "summary":
        top_ch_desc = (
            f"`{display_channels[0]['name']}` (`{display_channels[0]['count']:,}개` / `{display_channels[0]['percent']}%`)"
            if sorted_channels else f"`{display_channels[0]['name']}` *(메시지 대기 중)*"
        )

        embed = discord.Embed(
            title=f"📊 [{g_name}] {title_time} 서버 실제 활성도 요약 보드",
            description=(
                f"🏠 **서버 멤버:** {members_desc}\n"
                f"📢 **채널 현황:** 텍스트 `{len(text_chs)}개` · 음성 `{len(voice_chs)}개` · 역할 `{roles_cnt}개` (부스트 `Lv.{boost_lvl} / {boost_cnt}개`)\n"
                f"📅 **기준 일시:** `{now_kst.strftime('%Y-%m-%d %H:%M KST')}`\n"
                "───────────────────────────────────────\n"
                f"💬 **채팅 메시지량:** {msg_val_str}\n"
                f"🔊 **음성채널 실시간 현황:** {vc_active_str}\n"
                f"📅 **오늘 출석 참여율:** `{att_rate}%` (`{today_att_count:,}` / `{member_count:,}명` 완료 · 누적 등록 `{total_att_registered:,}명`)\n\n"
                f"🏆 **최다 활성 채널 1위:** {top_ch_desc}\n"
                f"🔥 **최고 활성 시간대:** {peak_str}\n\n"
                f"🤖 **서버 내 봇 기능 활용:** D-Day `{ddays_cnt}개` · 가챠 수집가 `{gacha_users_cnt}명` (카드 `{total_cards_cnt:,}장` 보유)"
            ),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=now_kst
        )
        embed.set_footer(text="하단 버튼으로 [📜 상세 리포트] 또는 [📅 주간/일간 모드]로 전환할 수 있습니다.")
        return embed
    else:
        # Detailed Mode Embed
        ch_lines = []
        for idx, ch in enumerate(display_channels, start=1):
            if sorted_channels:
                ch_lines.append(f"**{idx}위.** `{ch['name']}` — `{ch['count']:,}개` (`{ch['percent']}%`)")
            else:
                ch_lines.append(f"• `{ch['name']}` — `대기 중`")

        graph_lines = [
            f"00시 ~ 06시: [{make_bar(p_0_6)}] {p_0_6:4.1f}% ({h_0_6:,}개) (새벽 심야)",
            f"06시 ~ 12시: [{make_bar(p_6_12)}] {p_6_12:4.1f}% ({h_6_12:,}개) (오전 등교/출근)",
            f"12시 ~ 18시: [{make_bar(p_12_18)}] {p_12_18:4.1f}% ({h_12_18:,}개) (오후 활동)",
            f"18시 ~ 24시: [{make_bar(p_18_24)}] {p_18_24:4.1f}% ({h_18_24:,}개) (저녁/야간 핫타임)"
        ]

        embed = discord.Embed(
            title=f"📜 [{g_name}] {title_time} 서버 심층 활성도 상세 리포트",
            description=(
                f"🏠 **서버 총원:** {members_desc} · **개설일:** `{created_str}`\n"
                f"📢 **채널 구성:** 텍스트 `{len(text_chs)}개` · 음성 `{len(voice_chs)}개` · 역할 `{roles_cnt}개`\n"
                f"💎 **서버 부스트:** `레벨 {boost_lvl}` (`{boost_cnt}개` 부스트 활성)\n\n"
                f"💬 **1. 채널별 실제 메시지 점유율:**\n" + "\n".join(ch_lines) + "\n\n"
                f"🔊 **2. 음성 세션 실시간 데이터:**\n"
                f"• 실시간 통화 인원: `{active_voice_users:,}명`\n"
                f"• 통화 진행 채널: {vc_ch_names}\n\n"
                f"📅 **3. 출석 마일스톤 참여 현황:**\n"
                f"• 오늘 출석률: `{att_rate}%` (`{today_att_count:,}`명 출석 완료)\n"
                f"• 연속 출석 7일 이상 보유 유저: `{streak_7_count:,}명`\n"
                f"• 서버 최장 연속 출석자: {streak_leader_str}\n\n"
                f"🔥 **4. 24시간대별 실제 채팅 분포 타임라인:**\n" + "\n".join([f"`{g}`" for g in graph_lines]) + "\n\n"
                f"🤖 **5. norosi 서비스 연동 현황:**\n"
                f"• 서버 전용 D-Day 일정: `{ddays_cnt}개`\n"
                f"• 프로세카 가챠 이용 유저: `{gacha_users_cnt}명` (총 `{total_cards_cnt:,}장` 보유)"
            ),
            color=discord.Color.gold(),
            timestamp=now_kst
        )
        embed.set_footer(text="하단 버튼으로 요약 보드로 되돌아가거나 데이터를 즉시 새로고침할 수 있습니다.")
        return embed


class ServerStatsDashboardView(core.SafeView):
    def __init__(self, guild: discord.Guild, data: dict, timeframe: str = "daily", mode: str = "summary", user: Optional[discord.User] = None):
        super().__init__(timeout=180)
        self.guild = guild
        self.data = data
        self.timeframe = timeframe
        self.mode = mode
        self.user = user
        self._update_button_styles()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await super().interaction_check(interaction)
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 대시보드를 연 당사자만 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    def _update_button_styles(self):
        self.toggle_mode_btn.label = "📊 요약 보기" if self.mode == "detailed" else "📜 상세 리포트"
        self.toggle_time_btn.label = "📅 주간 통계" if self.timeframe == "daily" else "📅 일간 통계"

    @discord.ui.button(label="📜 상세 리포트", style=discord.ButtonStyle.primary, custom_id="btn_toggle_mode")
    async def toggle_mode_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "summary" if self.mode == "detailed" else "detailed"
        self._update_button_styles()
        embed = build_server_stats_embed(self.guild, self.data, self.timeframe, self.mode)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="📅 주간 통계", style=discord.ButtonStyle.secondary, custom_id="btn_toggle_time")
    async def toggle_time_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.timeframe = "weekly" if self.timeframe == "daily" else "daily"
        self._update_button_styles()
        embed = build_server_stats_embed(self.guild, self.data, self.timeframe, self.mode)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🔄 데이터 새로고침", style=discord.ButtonStyle.success, custom_id="btn_refresh_stats")
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.data = await asyncio.to_thread(core.load_data)
        embed = build_server_stats_embed(self.guild, self.data, self.timeframe, self.mode)
        await interaction.edit_original_response(embed=embed, view=self)


# ==========================================
# /모집 게임별 스타일 맵핑
# ==========================================
GAME_EMOJIS = {
    "프로세카": ("🎵", discord.Color.from_rgb(0, 204, 221)),
    "리그 오브 레전드": ("⚔️", discord.Color.from_rgb(10, 50, 90)),
    "롤": ("⚔️", discord.Color.from_rgb(10, 50, 90)),
    "발로란트": ("🎯", discord.Color.from_rgb(253, 69, 86)),
    "오버워치": ("🛡️", discord.Color.from_rgb(249, 158, 26)),
    "배틀그라운드": ("🪂", discord.Color.from_rgb(242, 169, 0)),
    "배그": ("🪂", discord.Color.from_rgb(242, 169, 0)),
    "전략적 팀 전투": ("♟️", discord.Color.from_rgb(33, 150, 243)),
    "tft": ("♟️", discord.Color.from_rgb(33, 150, 243)),
    "롤토체스": ("♟️", discord.Color.from_rgb(33, 150, 243)),
    "원신": ("✨", discord.Color.from_rgb(238, 119, 34)),
    "스타레일": ("🌠", discord.Color.from_rgb(120, 80, 220)),
    "스팀": ("🎮", discord.Color.from_rgb(27, 40, 56)),
    "마인크래프트": ("⛏️", discord.Color.from_rgb(90, 150, 60)),
    "수다": ("☕", discord.Color.from_rgb(180, 140, 100)),
    "화공": ("📺", discord.Color.from_rgb(150, 100, 200)),
}


class RecruitEditModal(core.SafeModal, title="✏️ 파티 모집 정보 수정"):
    game_input = discord.ui.TextInput(
        label="게임 종목",
        placeholder="예: 프로세카, 롤, 발로란트, 스팀 협동 등",
        min_length=1,
        max_length=40,
        required=True
    )
    capacity_input = discord.ui.TextInput(
        label="모집 총 인원수 (방장 포함 2~20명)",
        placeholder="숫자 입력 (예: 5 또는 5명)",
        min_length=1,
        max_length=10,
        required=True
    )
    goal_input = discord.ui.TextInput(
        label="파티 목표 / 모드",
        placeholder="예: 즐겜/친목, 랭크 승급, 협력 라이브 S랭크 등",
        min_length=1,
        max_length=60,
        required=True
    )
    departure_input = discord.ui.TextInput(
        label="출발 예정 시간 (선택)",
        placeholder="예: 지금 바로 출발 / 10분 뒤 / 22:00",
        required=False,
        max_length=50
    )
    memo_input = discord.ui.TextInput(
        label="방 번호 / 룸 코드 및 안내 메모 (선택)",
        placeholder="예: 룸코드 12345 / 디코 마이크 필수",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=300
    )

    def __init__(self, lobby_view: "RecruitLobbyView"):
        super().__init__()
        self.lobby_view = lobby_view
        self.game_input.default = lobby_view.game
        self.capacity_input.default = str(lobby_view.capacity)
        self.goal_input.default = lobby_view.goal
        self.departure_input.default = lobby_view.departure_time or ""
        self.memo_input.default = (
            f"방코드: {lobby_view.room_code}\n{lobby_view.memo or ''}".strip()
            if lobby_view.room_code else (lobby_view.memo or "")
        )

    async def on_submit(self, interaction: discord.Interaction):
        lv = self.lobby_view
        m_num = re.search(r"\d+", self.capacity_input.value or "")
        raw_cap = int(m_num.group(0)) if m_num else lv.capacity
        new_cap = max(len(lv.members), max(2, min(20, raw_cap)))

        lv.game = self.game_input.value.strip() or lv.game
        lv.capacity = new_cap
        lv.goal = self.goal_input.value.strip() or lv.goal
        lv.departure_time = self.departure_input.value.strip() if self.departure_input.value and self.departure_input.value.strip() else None
        lv.memo = self.memo_input.value.strip() if self.memo_input.value and self.memo_input.value.strip() else None

        if lv.status not in ("departed", "cancelled"):
            lv.status = "ready" if len(lv.members) >= lv.capacity else "recruiting"
        lv._sync_buttons()
        await interaction.response.edit_message(embed=lv.build_embed(), view=lv)


class RecruitLobbyView(core.SafeView):
    def __init__(
        self,
        host: discord.Member,
        game: str,
        capacity: int,
        goal: str,
        room_code: Optional[str] = None,
        departure_time: Optional[str] = None,
        memo: Optional[str] = None
    ):
        super().__init__(timeout=7200)
        self.host = host
        self.game = game
        self.capacity = max(2, min(20, capacity))
        self.goal = goal
        self.room_code = room_code
        self.departure_time = departure_time
        self.memo = memo
        self.members: List[discord.Member] = [host]
        self.status = "recruiting"
        self.message: Optional[discord.Message] = None
        self._sync_buttons()

    def _sync_buttons(self):
        if self.status in ("departed", "cancelled"):
            for item in self.children:
                item.disabled = True
            return

        is_full = len(self.members) >= self.capacity
        self.join_btn.disabled = is_full
        self.join_btn.label = "✅ 정원 마감" if is_full else "🖐️ 파티 참가"
        self.join_btn.style = discord.ButtonStyle.secondary if is_full else discord.ButtonStyle.success
        self.leave_btn.disabled = False
        self.edit_btn.disabled = False
        self.depart_btn.disabled = False
        self.cancel_btn.disabled = False

    def _get_game_style(self):
        clean_g = self.game.lower()
        for k, v in GAME_EMOJIS.items():
            if k.lower() in clean_g:
                return v
        return ("🎮", discord.Color.from_rgb(88, 101, 242))

    def build_embed(self) -> discord.Embed:
        emoji, color = self._get_game_style()
        curr_cnt = len(self.members)
        is_full = (curr_cnt >= self.capacity)
        now_kst = datetime.datetime.now(core.KST)

        if self.status == "departed":
            status_badge = "🚀 **[출발 완료]** 게임이 시작되었습니다!"
            title_text = f"{emoji} [{self.game}] 파티가 출발했습니다!"
            embed_color = discord.Color.dark_gray()
            bottom_guide = "🚀 **파티가 출발했습니다! 참가 멤버분들 모두 즐거운 플레이 되세요!**"
        elif self.status == "cancelled":
            status_badge = "🛑 **[모집 취소]** 모집이 중단되었습니다."
            title_text = f"✖️ [{self.game}] 파티 모집이 취소되었습니다."
            embed_color = discord.Color.red()
            bottom_guide = "🛑 **방장 또는 관리자에 의해 종료된 파티 모집입니다.**"
        elif is_full or self.status == "ready":
            status_badge = "🎉 **[모집 완료]** 모든 파티원이 모였습니다! 출발 준비 완료!"
            title_text = f"🎉 [{self.game}] 모집 완료! ({curr_cnt}/{self.capacity}명)"
            embed_color = discord.Color.green()
            bottom_guide = "👑 **정원이 모두 찼습니다! 방장님은 `[🚀 지금 출발]` 버튼을 눌러 출발해 주세요.**"
        else:
            status_badge = f"🔥 **[모집 진행 중]** 참가자를 기다리고 있습니다! (`{self.capacity - curr_cnt}명` 남음)"
            title_text = f"{emoji} [{self.game}] 파티원 모집 중! ({curr_cnt}/{self.capacity}명)"
            embed_color = color
            bottom_guide = "👇 **참가를 원하시면 아래 `[🖐️ 파티 참가]` 버튼을 눌러주세요!**"

        filled_blocks = min(10, max(0, int((curr_cnt / self.capacity) * 10)))
        gauge_str = ("🟩" * filled_blocks) + ("⬜" * (10 - filled_blocks))
        pct = int((curr_cnt / self.capacity) * 100)

        slot_lines = []
        for i in range(self.capacity):
            slot_num = i + 1
            if i < len(self.members):
                mem = self.members[i]
                if i == 0:
                    slot_lines.append(f"`슬롯 {slot_num:02d}` 👑 {mem.mention} `({mem.display_name})` **[방장]**")
                else:
                    slot_lines.append(f"`슬롯 {slot_num:02d}` 👤 {mem.mention} `({mem.display_name})`")
            else:
                slot_lines.append(f"`슬롯 {slot_num:02d}` 🔲 *( 빈자리 대기 중... )*")
        slots_str = "\n".join(slot_lines)

        info_lines = [
            f"• 🎯 **파티 목표:** `{self.goal}`",
            f"• ⏰ **출발 예정:** `{self.departure_time or '인원 충원 즉시 출발'}`",
        ]
        if self.room_code:
            info_lines.append(f"• 🔑 **방 번호 / 룸 코드:** `{self.room_code}` *(터치하여 복사)*")
        if self.memo:
            info_lines.append(f"• 📝 **안내 / 메모:** {self.memo}")

        info_str = "\n".join(info_lines)

        desc = (
            f"{status_badge}\n\n"
            f"📊 **모집 현황:** `{gauge_str}` **{pct}%** (`{curr_cnt}/{self.capacity}명`)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 **파티 상세 정보:**\n"
            f"{info_str}\n\n"
            f"👥 **참가 파티원 명단:**\n"
            f"{slots_str}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{bottom_guide}"
        )

        embed = discord.Embed(
            title=title_text,
            description=desc,
            color=embed_color,
            timestamp=now_kst
        )

        embed.set_author(
            name=f"{self.host.display_name} 님의 파티 모집",
            icon_url=self.host.display_avatar.url if hasattr(self.host, "display_avatar") else None
        )

        if self.host.guild and self.host.guild.icon:
            embed.set_thumbnail(url=self.host.guild.icon.url)

        embed.set_footer(
            text=f"norosi Party Matcher  ·  모집장: {self.host.display_name}",
            icon_url=self.host.display_avatar.url if hasattr(self.host, "display_avatar") else None
        )
        return embed

    @discord.ui.button(label="🖐️ 파티 참가", style=discord.ButtonStyle.success, row=0)
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.status in ("departed", "cancelled"):
            await core.safe_send_response(interaction, content="❌ 이미 종료되거나 취소된 모집입니다.", ephemeral=True)
            return

        if any(m.id == interaction.user.id for m in self.members):
            await core.safe_send_response(interaction, content="❌ 이미 파티에 참가 중입니다!", ephemeral=True)
            return

        if len(self.members) >= self.capacity:
            await core.safe_send_response(interaction, content="❌ 이미 파티 정원이 가득 찼습니다!", ephemeral=True)
            return

        self.members.append(interaction.user)
        is_full = (len(self.members) >= self.capacity)
        if is_full:
            self.status = "ready"

        self._sync_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

        if is_full:
            mention_str = " ".join(m.mention for m in self.members)
            pings_msg = (
                f"🎉 **[{self.game}] 파티 모집 완료!** {mention_str}\n"
                f"👉 총 `{self.capacity}명`의 파티원이 모두 모였습니다! 게임에 입장하여 즐겨주세요!"
            )
            if self.room_code:
                pings_msg += f"\n🔑 **방 번호:** `{self.room_code}`"
            await interaction.followup.send(pings_msg)

    @discord.ui.button(label="🚀 지금 출발", style=discord.ButtonStyle.primary, row=0)
    async def depart_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id:
            await core.safe_send_response(interaction, content="❌ 방장만 출발시킬 수 있습니다.", ephemeral=True)
            return

        self.status = "departed"
        self._sync_buttons()

        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

        mention_str = " ".join(m.mention for m in self.members)
        depart_msg = (
            f"🚀 **[{self.game}] 파티가 출발했습니다!** {mention_str}\n"
            f"👉 목표: `{self.goal}` · 모두 즐거운 플레이 되세요!"
        )
        if self.room_code:
            depart_msg += f"\n🔑 **방 번호:** `{self.room_code}`"
        await interaction.followup.send(depart_msg)

    @discord.ui.button(label="🏃 나가기", style=discord.ButtonStyle.secondary, row=1)
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.status in ("departed", "cancelled"):
            await core.safe_send_response(interaction, content="❌ 이미 종료되거나 취소된 모집입니다.", ephemeral=True)
            return

        if interaction.user.id == self.host.id:
            await core.safe_send_response(interaction, content="❌ 방장은 파티를 나갈 수 없습니다. 모집을 중단하려면 `[모집 취소]`를 눌러주세요.", ephemeral=True)
            return

        if not any(m.id == interaction.user.id for m in self.members):
            await core.safe_send_response(interaction, content="❌ 현재 파티에 참가하고 있지 않습니다.", ephemeral=True)
            return

        self.members = [m for m in self.members if m.id != interaction.user.id]
        if self.status == "ready":
            self.status = "recruiting"

        self._sync_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="✏️ 모집 수정", style=discord.ButtonStyle.secondary, row=1)
    async def edit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.status in ("departed", "cancelled"):
            await core.safe_send_response(interaction, content="❌ 이미 종료되거나 취소된 모집입니다.", ephemeral=True)
            return

        is_admin = interaction.user.guild_permissions.administrator if interaction.guild else False
        if interaction.user.id != self.host.id and not is_admin:
            await core.safe_send_response(interaction, content="❌ 방장 또는 서버 관리자만 모집 정보를 수정할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.send_modal(RecruitEditModal(self))

    @discord.ui.button(label="✖️ 모집 취소", style=discord.ButtonStyle.danger, row=1)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_admin = interaction.user.guild_permissions.administrator if interaction.guild else False
        if interaction.user.id != self.host.id and not is_admin:
            await core.safe_send_response(interaction, content="❌ 방장 또는 서버 관리자만 취소할 수 있습니다.", ephemeral=True)
            return

        self.status = "cancelled"
        self._sync_buttons()

        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)


# ==========================================
# /모집 직접 작성 팝업 모달 (선택 목록 없이 자유 작성)
# ==========================================
class RecruitModal(core.SafeModal, title="🎮 파티 / 팀원 모집 작성"):
    game_input = discord.ui.TextInput(
        label="게임 종목",
        placeholder="예: 프로세카, 롤, 발로란트, 스팀 협동, 마인크래프트 등",
        min_length=1,
        max_length=40,
        required=True
    )
    capacity_input = discord.ui.TextInput(
        label="모집 총 인원수 (방장 포함 2~20명)",
        placeholder="숫자 입력 (예: 5 또는 5명, 기본값: 5)",
        default="5",
        min_length=1,
        max_length=10,
        required=True
    )
    goal_input = discord.ui.TextInput(
        label="파티 목표 / 모드",
        placeholder="예: 즐겜/친목, 랭크 티어 승급, 협력 라이브 S랭크, 풀콤작 등",
        default="즐겜 / 친목",
        min_length=1,
        max_length=60,
        required=True
    )
    departure_input = discord.ui.TextInput(
        label="출발 예정 시간 (선택)",
        placeholder="예: 지금 바로 출발 / 10분 뒤 / 22:00 (기본: 충원 즉시 출발)",
        required=False,
        max_length=50
    )
    memo_input = discord.ui.TextInput(
        label="방 번호 / 룸 코드 및 안내 메모 (선택)",
        placeholder="예: 룸코드 12345 / 디코 마이크 필수 / 편하게 오세요",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=300
    )

    async def on_submit(self, interaction: discord.Interaction):
        m_num = re.search(r"\d+", self.capacity_input.value or "")
        if m_num:
            capacity = max(2, min(20, int(m_num.group(0))))
        else:
            capacity = 5

        game_val = self.game_input.value.strip() or "게임"
        goal_val = self.goal_input.value.strip() or "즐겜 / 친목"
        departure_val = self.departure_input.value.strip() if self.departure_input.value and self.departure_input.value.strip() else None
        memo_val = self.memo_input.value.strip() if self.memo_input.value and self.memo_input.value.strip() else None

        view = RecruitLobbyView(
            host=interaction.user,
            game=game_val,
            capacity=capacity,
            goal=goal_val,
            room_code=None,
            departure_time=departure_val,
            memo=memo_val
        )
        msg_obj = await core.safe_send_response(interaction, embed=view.build_embed(), view=view)
        try:
            view.message = msg_obj or await interaction.original_response()
        except Exception:
            pass


class StatsCog(commands.Cog):
    """서버 활성도 및 채널/음성/출석 통계 요약 및 상세 대시보드 Cog"""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """실제 서버 채팅 활동량을 백그라운드에서 실시간 집계하여 누적"""
        if not message.guild or message.author.bot:
            return

        g_key = str(message.guild.id)
        ch_id = str(message.channel.id)
        ch_name = f"#{message.channel.name}" if hasattr(message.channel, "name") else "#채널"
        now_kst = datetime.datetime.now(core.KST)
        today_str = now_kst.strftime("%Y-%m-%d")
        hour_str = str(now_kst.hour)

        data = await asyncio.to_thread(core.load_data)
        s_stats = data.setdefault("server_stats", {})
        g_stat = s_stats.setdefault(g_key, {
            "today_date": today_str,
            "today_msgs": 0,
            "weekly_msgs": 0,
            "total_msgs": 0,
            "channel_msgs": {},
            "hourly_msgs": {},
            "active_users": {}
        })

        # 자정이 지난 경우 오늘 일간 카운트 갱신 (일간 채널 점유율 100% 초과 방지)
        if g_stat.get("today_date") != today_str:
            g_stat["today_date"] = today_str
            g_stat["today_msgs"] = 0
            g_stat["channel_msgs"] = {}
            g_stat["hourly_msgs"] = {}

        g_stat["today_msgs"] = g_stat.get("today_msgs", 0) + 1
        g_stat["weekly_msgs"] = g_stat.get("weekly_msgs", 0) + 1
        g_stat["total_msgs"] = g_stat.get("total_msgs", 0) + 1

        ch_map = g_stat.setdefault("channel_msgs", {})
        ch_entry = ch_map.setdefault(ch_id, {"name": ch_name, "count": 0})
        ch_entry["name"] = ch_name
        ch_entry["count"] = ch_entry.get("count", 0) + 1

        h_map = g_stat.setdefault("hourly_msgs", {})
        h_map[hour_str] = h_map.get(hour_str, 0) + 1

        u_id = str(message.author.id)
        u_map = g_stat.setdefault("active_users", {})
        u_map[u_id] = u_map.get(u_id, 0) + 1

        # 채팅마다 동기식 I/O를 배제하고 25메시지마다 배치 저장하여 디스크/네트워크 병목 방지
        self._msg_save_counter = getattr(self, "_msg_save_counter", 0) + 1
        if self._msg_save_counter >= 25:
            self._msg_save_counter = 0
            await asyncio.to_thread(core.save_data, data)

    @app_commands.command(name="서버통계", description="서버의 실제 일일/주간 채팅량, 채널별 점유율, 음성 실시간 현황, 출석율을 분석한 대시보드를 출력합니다.")
    @app_commands.describe(
        기간="(선택) 분석할 기간 범위 (일간/주간)",
        상세보기="(선택) 리포트 출력 모드 (요약 보드/상세 리포트)"
    )
    @app_commands.choices(
        기간=[
            app_commands.Choice(name="📅 일간 (오늘 00:00~현재)", value="daily"),
            app_commands.Choice(name="📅 주간 (최근 7일 누적)", value="weekly")
        ],
        상세보기=[
            app_commands.Choice(name="📊 한눈에 보는 요약 보드", value="summary"),
            app_commands.Choice(name="📜 심층 분석 상세 리포트", value="detailed")
        ]
    )
    async def server_stats_cmd(
        self,
        interaction: discord.Interaction,
        기간: app_commands.Choice[str] = None,
        상세보기: app_commands.Choice[str] = None
    ):
        await core.safe_defer(interaction, ephemeral=False)
        data = await asyncio.to_thread(core.load_data)

        tf = 기간.value if 기간 else "daily"
        mode = 상세보기.value if 상세보기 else "summary"

        embed = build_server_stats_embed(interaction.guild, data, tf, mode)
        view = ServerStatsDashboardView(interaction.guild, data, tf, mode, user=interaction.user)
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="봇상태", description="[서버 관리자 전용] norosi 봇의 호스트 시스템 리소스(RAM, CPU, 디스크, 핑, 업타임) 상태를 확인합니다.")
    @app_commands.default_permissions(manage_guild=True)
    async def host_system_stats_cmd(self, interaction: discord.Interaction):
        # 관리자 권한 안전 검증
        is_owner = await self.bot.is_bot_owner_user(interaction.user)
        is_admin = False
        if interaction.guild and isinstance(interaction.user, discord.Member):
            is_admin = interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild

        if not (is_owner or is_admin):
            await core.safe_send_response(
                interaction,
                content="🚨 **권한 부족:** `/봇상태` 명령어는 **디스코드 서버 관리자(서버 관리/관리자 권한)** 또는 **봇 소유자**만 실행할 수 있습니다.",
                ephemeral=True
            )
            return

        await core.safe_defer(interaction, ephemeral=True)

        # 시스템 리소스 및 프로세스 지표 측정
        start_ping = time.perf_counter()
        data = await asyncio.to_thread(core.load_data)
        data_disk_ms = round((time.perf_counter() - start_ping) * 1000, 2)

        # 메모리 사용량 (RSS - OS별 단위 보정: Linux KB / Darwin Byte / Windows fallback)
        try:
            if resource:
                mem_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                if sys.platform == "darwin":
                    mem_mb = round(mem_kb / (1024 * 1024), 2)
                else:
                    mem_mb = round(mem_kb / 1024, 2)
            else:
                mem_mb = 0.0
        except Exception:
            mem_mb = 0.0

        # 디스크 용량 (GB)
        try:
            disk = shutil.disk_usage(".")
            disk_total_gb = round(disk.total / (1024 ** 3), 1)
            disk_used_gb = round(disk.used / (1024 ** 3), 2)
            disk_free_gb = round(disk.free / (1024 ** 3), 1)
            disk_pct = round((disk.used / disk.total) * 100, 1)
        except Exception:
            disk_total_gb = disk_used_gb = disk_free_gb = disk_pct = 0

        # CPU 로드 및 OS 정보
        try:
            load_avg = os.getloadavg()
            load_str = f"{load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f}"
        except Exception:
            load_str = "지원 안 됨"

        # 업타임 계산
        bot_start = getattr(self.bot, "start_time", None)
        if bot_start:
            uptime_td = datetime.datetime.now(core.KST) - bot_start
            up_days = uptime_td.days
            up_hours, rem_s = divmod(uptime_td.seconds, 3600)
            up_mins, up_secs = divmod(rem_s, 60)
            uptime_str = f"{up_days}일 {up_hours}시간 {up_mins}분 {up_secs}초"
            start_str = bot_start.strftime("%Y-%m-%d %H:%M:%S KST")
        else:
            uptime_str = "측정 중"
            start_str = "-"

        # 핑 및 게이트웨이 상태
        ws_latency = round(self.bot.latency * 1000, 1)
        guilds_cnt = len(self.bot.guilds)
        users_cnt = sum(g.member_count or 0 for g in self.bot.guilds)
        cogs_cnt = len(self.bot.cogs)
        exts_cnt = len(self.bot.extensions)

        # 게이지 바 시각화 헬퍼
        def make_bar(pct: float, length: int = 10) -> str:
            filled = min(length, max(0, int(round((pct / 100) * length))))
            return "█" * filled + "░" * (length - filled)

        disk_bar = make_bar(disk_pct)

        embed = discord.Embed(
            title="🖥️ norosi 봇 호스트 서버 실시간 시스템 상태",
            description=(
                "**[서버 관리자 전용]** 봇 인스턴스의 하드웨어 자원, 네트워크 레이턴시 및 런타임 현황입니다.\n"
                "───────────────────────────────────────"
            ),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )

        embed.add_field(
            name="📡 네트워크 & 게이트웨이",
            value=(
                f"• **WebSocket 핑:** `{ws_latency}ms` (정상)\n"
                f"• **데이터 I/O 지연:** `{data_disk_ms}ms`\n"
                f"• **참여 서버 수:** `{guilds_cnt:,}개 길드`\n"
                f"• **서비스 유저 수:** `{users_cnt:,}명`"
            ),
            inline=True
        )

        embed.add_field(
            name="⚙️ 시스템 리소스 & 메모리",
            value=(
                f"• **RAM 점유(RSS):** `{mem_mb} MB`\n"
                f"• **CPU 로드:** `{load_str}`\n"
                f"• **디스크:** `{disk_used_gb}GB` / `{disk_total_gb}GB` (`{disk_pct}%`)\n"
                f"└ `[{disk_bar}]`"
            ),
            inline=True
        )

        embed.add_field(
            name="⏱️ 프로세스 런타임 & 업타임",
            value=(
                f"• **가동 시작일:** `{start_str}`\n"
                f"• **연속 가동 시간:** `{uptime_str}`\n"
                f"• **활성 확장 Cogs:** `{cogs_cnt}개 모듈` (`{exts_cnt}개 로드됨`)\n"
                f"• **Python 버전:** `{platform.python_version()}` (`{platform.system()} {platform.release()[:10]}`)"
            ),
            inline=False
        )

        embed.set_footer(text=f"요청자: {interaction.user.display_name} • 24/7 백그라운드 헬스체크 정상 가동 중")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ==========================================
    # 카테고리 5 - 4: /유저정보 (멤버 상세 프로필 조회기)
    # ==========================================
    @app_commands.command(name="유저정보", description="멤버의 디스코드 가입일, 서버 입장 순번, 보유 역할, 출석/크리스탈/채팅 활동량을 종합 조회합니다.")
    @app_commands.describe(유저="(선택) 상세 정보를 조회할 서버 멤버 (미지정 시 본인 조회)")
    async def user_profile_info_cmd(
        self,
        interaction: discord.Interaction,
        유저: discord.Member = None
    ):
        await core.safe_defer(interaction, ephemeral=False)
        target = 유저 or interaction.user
        data = await asyncio.to_thread(core.load_data)

        now_kst = datetime.datetime.now(core.KST)
        created_kst = target.created_at.astimezone(core.KST) if getattr(target, "created_at", None) else now_kst
        created_days = max(0, (now_kst.date() - created_kst.date()).days)
        created_str = f"`{created_kst.strftime('%Y-%m-%d %H:%M')}` (`D+{created_days:,}일`)"

        joined_str = "정보 없음 (DM)"
        join_rank_str = "-"
        roles_str = "역할 없음"
        top_role_str = "없음"
        boost_str = "미사용"
        perm_badges = []

        if interaction.guild and isinstance(target, discord.Member):
            if target.joined_at:
                joined_kst = target.joined_at.astimezone(core.KST)
                joined_days = max(0, (now_kst.date() - joined_kst.date()).days)
                joined_str = f"`{joined_kst.strftime('%Y-%m-%d %H:%M')}` (`D+{joined_days:,}일`)"

                # 서버 입장 순번 계산
                sorted_members = sorted(
                    [m for m in interaction.guild.members if m.joined_at is not None],
                    key=lambda m: m.joined_at
                )
                try:
                    rank_idx = sorted_members.index(target) + 1
                    join_rank_str = f"**`#{rank_idx:,}번째`** / 총 `{interaction.guild.member_count or len(sorted_members):,}명`"
                except ValueError:
                    join_rank_str = f"총 `{interaction.guild.member_count or 1:,}명` 중"

            # 역할 목록 (@everyone 제외)
            member_roles = [r for r in reversed(target.roles) if r.name != "@everyone"]
            if member_roles:
                top_role_str = member_roles[0].mention
                shown_roles = [r.mention for r in member_roles[:12]]
                rem_cnt = len(member_roles) - len(shown_roles)
                roles_str = " ".join(shown_roles) + (f" 외 `{rem_cnt}개`" if rem_cnt > 0 else "")

            if target.premium_since:
                b_kst = target.premium_since.astimezone(core.KST)
                boost_str = f"💎 부스트 중 (`{b_kst.strftime('%Y-%m-%d')}~`)"

            perms = target.guild_permissions
            if interaction.guild.owner_id == target.id:
                perm_badges.append("👑 서버 소유자")
            elif perms.administrator:
                perm_badges.append("🛡️ 서버 관리자")
            else:
                if perms.manage_guild:
                    perm_badges.append("⚙️ 서버 관리")
                if perms.manage_channels:
                    perm_badges.append("📢 채널 관리")
                if perms.manage_messages:
                    perm_badges.append("🧹 메시지 관리")
                if perms.ban_members or perms.kick_members:
                    perm_badges.append("🔨 멤버 추방/차단")

        perm_summary = ", ".join(perm_badges) if perm_badges else "일반 멤버"

        # norosi 봇 내부 활동 데이터 연동
        u_key = str(target.id)
        g_key = str(interaction.guild_id or 0)
        profile = core.ensure_user_profile(data, u_key, target.display_name)
        crystals = profile.get("crystals", 0)
        oshi_name = profile.get("oshi") or "미설정"
        partner_id = profile.get("partner_id")
        partner_str = f"<@{partner_id}>" if partner_id else "없음"

        guild_att = data.get("guild_attendance", {}).get(g_key, {}).get(u_key, {})
        att_total = guild_att.get("total_days", 0)
        att_streak = guild_att.get("streak", 0)

        gacha_cards = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})
        unique_cards = len(gacha_cards)
        star4_cards = sum(1 for c in gacha_cards.values() if isinstance(c, dict) and c.get("star_num", 1) >= 4)

        msg_count = data.get("server_stats", {}).get(g_key, {}).get("active_users", {}).get(u_key, 0)
        bday_info = data.get("birthdays", {}).get(u_key)
        bday_str = f"`{bday_info['month']:02d}월 {bday_info['day']:02d}일` 🎂" if isinstance(bday_info, dict) and "month" in bday_info else "미등록 (`/생일등록`)"

        embed_color = target.color if isinstance(target, discord.Member) and target.color != discord.Color.default() else discord.Color.from_rgb(0, 204, 221)
        bot_badge = " 🤖 `[BOT]`" if target.bot else ""

        embed = discord.Embed(
            title=f"🪪 {target.display_name}{bot_badge}님의 상세 멤버 프로필",
            description=(
                f"👤 **유저 멘션:** {target.mention} (`{target.name}`)\n"
                f"🆔 **고유 ID:** `{target.id}` · **권한 등급:** `{perm_summary}`\n"
                "───────────────────────────────────────"
            ),
            color=embed_color,
            timestamp=now_kst
        )
        if hasattr(target, "display_avatar") and target.display_avatar:
            embed.set_thumbnail(url=target.display_avatar.url)

        embed.add_field(
            name="📅 계정 및 서버 가입 이력",
            value=(
                f"• **디스코드 가입일:** {created_str}\n"
                f"• **현재 서버 입장일:** {joined_str}\n"
                f"• **서버 입장 순번:** {join_rank_str}\n"
                f"• **서버 부스트:** {boost_str}"
            ),
            inline=False
        )

        embed.add_field(
            name=f"🛡️ 보유 역할 정보 (대표: {top_role_str})",
            value=roles_str,
            inline=False
        )

        embed.add_field(
            name="🌟 세카이 & 서버 활동 지표",
            value=(
                f"• **서버 출석:** 누적 `{att_total:,}일` (연속 `{att_streak:,}일 🔥`)\n"
                f"• **보유 크리스탈:** `💎 {crystals:,}개` · **채팅 활동:** `{msg_count:,}회`\n"
                f"• **수집 캐릭터:** 총 `{unique_cards:,}종` (★4·생일 `{star4_cards:,}종`)\n"
                f"• **내 오시:** `{oshi_name}` · **파트너:** {partner_str} · **생일:** {bday_str}"
            ),
            inline=False
        )

        embed.set_footer(text=f"요청자: {interaction.user.display_name} • 실시간 멤버 분석 완료")
        await interaction.followup.send(embed=embed)

    # ==========================================
    # 카테고리 4 - 2: /날씨 (초정밀 실시간 기상 & 미세먼지 & 시간별 강수 예보)
    # ==========================================
    @app_commands.command(name="날씨", description="기상청/ECMWF 실시간 관측 데이터로 지역별 기온, 체감온도, 미세먼지, 시간별 강수확률 및 우산 가이드를 조회합니다.")
    @app_commands.describe(지역="조회할 도시·시·군·구·동 이름 (예: 서울, 강남, 부산, 수원, 대전, 제주, 도쿄)")
    async def accurate_weather_cmd(
        self,
        interaction: discord.Interaction,
        지역: str = "서울"
    ):
        await core.safe_defer(interaction, ephemeral=False)
        w_info, err = await asyncio.to_thread(core.fetch_accurate_weather_sync, 지역)
        if err or not w_info:
            await interaction.followup.send(f"❌ **날씨 조회 실패:** {err}", ephemeral=True)
            return

        view = WeatherRefreshView(지역, w_info, user=interaction.user)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    # ==========================================
    # 카테고리 1 - 2: /끝말잇기 (실시간 끝말잇기 배틀 — 두음법칙 완벽 적용)
    # ==========================================
    @app_commands.command(name="끝말잇기", description="표준 두음법칙이 적용되는 실시간 끝말잇기 대결! (봇 1:1 대결 또는 서버 멤버와 턴제 배틀)")
    @app_commands.describe(
        상대유저="(선택) 함께 대결할 서버 멤버 (비워두면 세카이 AI 봇과 1:1 대결!)",
        시작단어="(선택) 첫 시작 단어 (2글자 이상 한글 명사, 미지정 시 랜덤 제시)"
    )
    async def word_chain_game_cmd(
        self,
        interaction: discord.Interaction,
        상대유저: discord.Member = None,
        시작단어: str = None
    ):
        if 상대유저 and (상대유저.bot or 상대유저.id == interaction.user.id):
            await core.safe_send_response(
                interaction,
                content="ℹ️ 봇과 대결하려면 `상대유저` 옵션을 비워두시고, 유저와 대결하려면 본인이 아닌 다른 멤버를 지정해 주세요!",
                ephemeral=True
            )
            return

        await core.safe_defer(interaction, ephemeral=False)
        first_word = (시작단어 or "").strip()
        if not first_word or not (2 <= len(first_word) <= 10) or not all("가" <= ch <= "힣" for ch in first_word):
            import random
            first_word = random.choice(["세카이", "음악", "별자리", "피아노", "출석", "콘서트", "하늘", "무지개", "기차", "바다"])

        view = WordChainGameView(interaction.user, 상대유저, first_word)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    # ==========================================
    # 카테고리 1 - 3: /러시안룰렛 (스릴 만점 6연발 리볼버 생존 게임)
    # ==========================================
    @app_commands.command(name="러시안룰렛", description="6연발 리볼버에 실탄을 장전하고 방아쇠를 당겨 생존 보너스 크리스탈(💎)을 획득하는 스릴 생존 게임!")
    @app_commands.describe(
        실탄수="(선택) 6연발 실린더에 넣을 실탄 개수 (1~5발, 기본: 1발)",
        참가비="(선택) 기본 판돈 크리스탈 (0~500💎, 기본: 50💎)"
    )
    async def russian_roulette_cmd(
        self,
        interaction: discord.Interaction,
        실탄수: app_commands.Range[int, 1, 5] = 1,
        참가비: app_commands.Range[int, 0, 500] = 50
    ):
        await core.safe_defer(interaction, ephemeral=False)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(interaction.user.id)
        prof = core.ensure_user_profile(data, u_key, interaction.user.display_name)

        if 참가비 > 0:
            if prof.get("crystals", 0) < 참가비:
                await interaction.followup.send(
                    f"❌ 보유 크리스탈이 부족합니다! (현재 보유: `{prof.get('crystals', 0):,}💎` / 필요 참가비: `{참가비:,}💎`)\n"
                    "💡 `/출석체크`로 크리스탈을 모으거나 `참가비: 0`으로 무료 모드를 즐겨보세요!",
                    ephemeral=True
                )
                return
            prof["crystals"] -= 참가비
            await asyncio.to_thread(core.save_data, data)

        view = RussianRouletteView(interaction.user, bullets=실탄수, bet_crystals=참가비)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    # ==========================================
    # 카테고리 1 - 1: /건의 (익명/계정공개 선택 + 미디어 첨부 + 약관 안내)
    # ==========================================
    @app_commands.command(name="건의", description="봇 개발진 및 운영진에게 익명 또는 계정 공개로 건의사항이나 피드백을 전달합니다 (이미지/미디어 첨부 지원).")
    @app_commands.describe(
        유형="건의 접수 방식 선택 (🔒 익명 건의: 정보 비공개 / 📢 계정 공개: 닉네임·ID 포함)",
        제목="(선택) 건의 한줄 요약 제목 (미입력 시 상세 작성 모달 창 열기)",
        내용="(선택) 상세 건의 내용",
        첨부파일="(선택) 버그 스크린샷, 오류 화면 또는 참고 이미지/미디어 파일"
    )
    @app_commands.choices(유형=[
        app_commands.Choice(name="🔒 익명 건의 (내 계정/ID 비공개, 순수 내용만 접수)", value="anonymous"),
        app_commands.Choice(name="📢 계정 공개 건의 (닉네임·ID 포함, 답변/피드백 수신 가능)", value="public")
    ])
    async def suggestion_cmd(
        self,
        interaction: discord.Interaction,
        유형: app_commands.Choice[str] = None,
        제목: str = None,
        내용: str = None,
        첨부파일: discord.Attachment = None
    ):
        attach_url = 첨부파일.url if 첨부파일 else None
        attach_name = 첨부파일.filename if 첨부파일 else None

        # 1. 제목과 내용이 모두 제공된 경우 즉시 접수 처리
        if 제목 and 내용:
            await core.safe_defer(interaction, ephemeral=True)
            is_anon = (유형.value == "anonymous") if 유형 else True
            entry = await save_and_notify_suggestion(
                self.bot,
                interaction.user,
                interaction.guild,
                제목,
                내용,
                is_anon,
                attachment_url=attach_url,
                attachment_name=attach_name
            )
            embed = build_suggestion_result_embed(entry)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # 2. 유형이 이미 지정된 경우 모달 창을 바로 전송 (첨부파일 전달 보존)
        if 유형:
            is_anon = (유형.value == "anonymous")
            await interaction.response.send_modal(
                SuggestionSubmitModal(
                    self.bot,
                    is_anonymous=is_anon,
                    initial_title=제목 or "",
                    attachment_url=attach_url,
                    attachment_name=attach_name
                )
            )
            return

        # 3. 옵션이 비어있는 경우 이용약관 안내와 함께 [익명 건의] / [계정 공개 건의] 선택 버튼 패널 표시
        view = SuggestionTypeSelectView(self.bot, attachment_url=attach_url, attachment_name=attach_name)
        embed = view.build_overview_embed()
        await core.safe_send_response(interaction, embed=embed, view=view, ephemeral=True)

    # ==========================================
    # 카테고리 5 - 4: /서버백업 [봇주인 전용]
    # ==========================================
    @app_commands.command(name="서버백업", description="[봇주인 전용] 현재 디스코드 서버의 채널/역할/카테고리 구조 또는 봇 DB 전체를 JSON 파일로 백업합니다.")
    @app_commands.describe(모드="백업 대상 선택 (현재 서버 구조 백업 / 봇 전체 DB 데이터 백업)")
    @app_commands.choices(모드=[
        app_commands.Choice(name="🏰 현재 서버 구조 백업 (채널/역할/카테고리 JSON)", value="guild"),
        app_commands.Choice(name="💾 전체 봇 DB 백업 (ddays_data.json)", value="db")
    ])
    async def server_backup_cmd(
        self,
        interaction: discord.Interaction,
        모드: app_commands.Choice[str] = None
    ):
        await core.safe_defer(interaction, ephemeral=True)
        is_owner = (interaction.user.id == core.BOT_OWNER_ID) or (await self.bot.is_bot_owner_user(interaction.user) if hasattr(self.bot, 'is_bot_owner_user') else False)
        if not is_owner:
            await interaction.followup.send(
                "❌ **권한 부족:** `/서버백업` 명령어는 봇 소유자(Bot Owner)만 실행할 수 있습니다.",
                ephemeral=True
            )
            return

        choice_mode = 모드.value if 모드 else "guild"
        now_kst = datetime.datetime.now(core.KST)
        ts_str = now_kst.strftime("%Y%m%d_%H%M%S")

        if choice_mode == "guild":
            if not interaction.guild:
                await interaction.followup.send("❌ 이 명령어는 디스코드 서버(길드) 채널 내에서만 실행할 수 있습니다.", ephemeral=True)
                return

            guild = interaction.guild
            backup_data = {
                "backup_version": "1.0",
                "backup_type": "guild_structure",
                "timestamp": now_kst.strftime("%Y-%m-%d %H:%M:%S KST"),
                "server": {
                    "id": guild.id,
                    "name": guild.name,
                    "owner_id": guild.owner_id,
                    "created_at": guild.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "member_count": guild.member_count,
                    "premium_tier": getattr(guild, "premium_tier", 0),
                    "premium_subscription_count": getattr(guild, "premium_subscription_count", 0),
                    "preferred_locale": str(guild.preferred_locale),
                    "icon_url": str(guild.icon.url) if guild.icon else None
                },
                "roles": [],
                "categories": [],
                "channels": [],
                "emojis": [
                    {"id": e.id, "name": e.name, "animated": e.animated, "url": str(e.url)}
                    for e in guild.emojis
                ]
            }

            for r in guild.roles:
                if r.is_default():
                    continue
                backup_data["roles"].append({
                    "id": r.id,
                    "name": r.name,
                    "color": str(r.color),
                    "hoist": r.hoist,
                    "position": r.position,
                    "permissions": [perm for perm, val in r.permissions if val],
                    "mentionable": r.mentionable
                })

            for cat in guild.categories:
                backup_data["categories"].append({
                    "id": cat.id,
                    "name": cat.name,
                    "position": cat.position
                })

            for ch in guild.channels:
                if isinstance(ch, discord.CategoryChannel):
                    continue
                ch_info = {
                    "id": ch.id,
                    "name": ch.name,
                    "type": str(ch.type),
                    "position": ch.position,
                    "category": ch.category.name if ch.category else None,
                    "category_id": ch.category.id if ch.category else None
                }
                if hasattr(ch, "topic"):
                    ch_info["topic"] = ch.topic
                if hasattr(ch, "slowmode_delay"):
                    ch_info["slowmode_delay"] = ch.slowmode_delay
                if hasattr(ch, "bitrate"):
                    ch_info["bitrate"] = ch.bitrate
                if hasattr(ch, "user_limit"):
                    ch_info["user_limit"] = ch.user_limit
                backup_data["channels"].append(ch_info)

            json_bytes = json.dumps(backup_data, ensure_ascii=False, indent=2).encode("utf-8")
            fp = io.BytesIO(json_bytes)
            filename = f"guild_backup_{guild.id}_{ts_str}.json"
            file = discord.File(fp, filename=filename)

            embed = discord.Embed(
                title=f"🏰 [{guild.name}] 서버 구조 안전 백업 완료",
                description=(
                    f"서버의 전체 역할, 카테고리, 채널 및 기본 설정 데이터를 JSON 파일로 정상 추출했습니다.\n\n"
                    f"• **백업 생성 시각:** `{backup_data['timestamp']}`\n"
                    f"• **역할(Roles) 수:** `{len(backup_data['roles'])}개`\n"
                    f"• **카테고리 수:** `{len(backup_data['categories'])}개`\n"
                    f"• **채널 수:** `{len(backup_data['channels'])}개` (텍스트/음성/포럼 등)\n"
                    f"• **커스텀 이모지 수:** `{len(backup_data['emojis'])}개`\n"
                    f"• **백업 파일 크기:** `{len(json_bytes) / 1024:.2f} KB`\n\n"
                    "🔒 *첨부된 JSON 백업 파일은 서버 복구 및 템플릿 마이그레이션에 안전하게 사용하실 수 있습니다.*"
                ),
                color=discord.Color.from_rgb(0, 204, 221),
                timestamp=now_kst
            )
            embed.set_footer(text="[봇주인 전용] norosi Safety Guard")
            await interaction.followup.send(embed=embed, file=file, ephemeral=True)

        else:
            # 봇 DB 전체 백업
            data = await asyncio.to_thread(core.load_data)
            clean_db = copy.deepcopy(data)
            json_bytes = json.dumps(clean_db, ensure_ascii=False, indent=2).encode("utf-8")
            fp = io.BytesIO(json_bytes)
            filename = f"norosi_db_backup_{ts_str}.json"
            file = discord.File(fp, filename=filename)

            embed = discord.Embed(
                title="💾 [norosi DB] 전체 데이터베이스 안전 백업 완료",
                description=(
                    "봇의 모든 D-Day, 출석, 크리스탈, 보유 카드, 랭킹 및 통계 데이터를 JSON 백업 파일로 생성했습니다.\n\n"
                    f"• **백업 생성 시각:** `{now_kst.strftime('%Y-%m-%d %H:%M:%S KST')}`\n"
                    f"• **유저 프로필 수:** `{len(clean_db.get('user_profiles', {}))}개`\n"
                    f"• **D-Day 일정 수:** `{len(clean_db.get('ddays', {}))}개`\n"
                    f"• **가챠 보유 유저:** `{sum(len(u) for u in clean_db.get('gacha_users', {}).values())}명`\n"
                    f"• **접수된 건의 수:** `{len(clean_db.get('suggestions', []))}건`\n"
                    f"• **백업 파일 크기:** `{len(json_bytes) / 1024:.2f} KB`"
                ),
                color=discord.Color.green(),
                timestamp=now_kst
            )
            embed.set_footer(text="[봇주인 전용] norosi Cloud Backup")
            await interaction.followup.send(embed=embed, file=file, ephemeral=True)

    # ==========================================
    # /모집: 프로세카 및 모든 게임 올인원 파티 모집 (직접 작성 모달 & 자유 입력)
    # ==========================================
    @app_commands.command(name="모집", description="프로세카 협력 라이브뿐 아니라 롤, 발로란트, 스팀 등 모든 게임의 파티/팀원을 모집합니다.")
    @app_commands.describe(
        게임="(선택) 모집할 게임 이름 (입력하지 않으면 직접 작성할 수 있는 모달 창이 열립니다)",
        인원수="(선택) 모집할 총 인원수 (방장 포함 2~20명, 기본: 5명)",
        목표="(선택) 파티 목표 (예: 즐겜, 랭크 승급, 이벤트 파밍 등 자유 작성)",
        방번호="(선택) 게임 룸 코드, 비밀번호, 또는 음성 채널 링크",
        시간="(선택) 출발 예정 시간 (예: 지금 바로, 10분 뒤, 22:00)",
        메모="(선택) 파티 조건이나 전할 말"
    )
    async def recruit_cmd(
        self,
        interaction: discord.Interaction,
        게임: Optional[str] = None,
        인원수: Optional[app_commands.Range[int, 2, 20]] = None,
        목표: Optional[str] = None,
        방번호: Optional[str] = None,
        시간: Optional[str] = None,
        메모: Optional[str] = None
    ):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 이 명령어는 디스코드 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return

        # 옵션 없이 /모집 만 실행한 경우 -> 직접 작성할 수 있는 팝업 창(Modal) 띄우기
        if not 게임:
            await interaction.response.send_modal(RecruitModal())
            return

        # 슬래시 옵션에 직접 텍스트로 작성하여 실행한 경우
        cap = 인원수 if 인원수 is not None else 5
        g_goal = 목표.strip() if 목표 else "즐겜 / 친목"
        view = RecruitLobbyView(
            host=interaction.user,
            game=게임.strip(),
            capacity=cap,
            goal=g_goal,
            room_code=방번호.strip() if 방번호 else None,
            departure_time=시간.strip() if 시간 else None,
            memo=메모.strip() if 메모 else None
        )
        msg_obj = await core.safe_send_response(interaction, embed=view.build_embed(), view=view)
        try:
            view.message = msg_obj or await interaction.original_response()
        except Exception:
            pass


# ==========================================
# 실시간 날씨 새로고침 뷰
# ==========================================
class WeatherRefreshView(core.SafeView):
    def __init__(self, query: str, weather_info: dict, user: Optional[discord.User] = None):
        super().__init__(timeout=300)
        self.query = query
        self.w = weather_info
        self.user = user

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await super().interaction_check(interaction)
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 날씨를 조회한 당사자만 새로고침할 수 있습니다.", ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        w = self.w
        now_kst = datetime.datetime.now(core.KST)

        hourly_lines = []
        for h in w.get("hourly", []):
            hourly_lines.append(f"`{h['time']}` {h['emoji']} **{h['temp']:.1f}°C** (강수 `{h['pop']}%`)")
        hourly_str = "  |  ".join(hourly_lines) if hourly_lines else "예보 데이터 갱신 중"

        embed = discord.Embed(
            title=f"{w['weather_emoji']} [{w['location']}] 초정밀 실시간 기상 & 대기질 리포트",
            description=(
                f"📍 **관측 좌표:** `위도 {w['lat']}, 경도 {w['lon']}` · 🕒 **기준:** `{now_kst.strftime('%Y-%m-%d %H:%M KST')}`\n"
                "───────────────────────────────────────\n"
                f"### 🌡️ 현재 기온: **`{w['temp']:.1f}°C`** ({w['weather_desc']})\n"
                f"• **체감 온도:** **`{w['feels_like']:.1f}°C`**  |  **오늘 최저/최고:** `{w['min_temp']:.1f}°C` / `{w['max_temp']:.1f}°C`\n"
                f"• **상대 습도:** `{w['humidity']}%`  |  **풍속:** `{w['wind']} km/h`  |  **기압:** `{w['pressure']:.0f} hPa`"
            ),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=now_kst
        )

        embed.add_field(
            name="☔ 강수 확률 & 자외선 & 일출/일몰",
            value=(
                f"• **오늘 최대 강수확률:** **`{w['pop_max']}%`** (현재 강수량 `{w['precip']}mm`)\n"
                f"• **자외선 지수(UV):** `{w['uv_max']:.1f}`  |  🌅 **일출/일몰:** `{w['sunrise']}` / `{w['sunset']}`"
            ),
            inline=False
        )

        embed.add_field(
            name="😷 실시간 미세먼지 & 대기질 (환경부 기준)",
            value=(
                f"• **미세먼지 (PM10):** {w['pm10_grade']}\n"
                f"• **초미세먼지 (PM2.5):** {w['pm25_grade']}"
            ),
            inline=False
        )

        embed.add_field(
            name="⏱️ 향후 시간대별 기온 & 강수 예보",
            value=hourly_str,
            inline=False
        )

        embed.add_field(
            name="📅 내일 날씨 미리보기 & 생활 가이드",
            value=(
                f"• **내일 예보:** {w['tmr_desc']} (`{w['tmr_min']:.1f}°C ~ {w['tmr_max']:.1f}°C` · 강수확률 `{w['tmr_pop']}%`)\n"
                f"• {w['umbrella_tip']}\n"
                f"• **추천 옷차림:** {w['outfit_tip']}"
            ),
            inline=False
        )

        embed.set_footer(text="기상청(KMA) & ECMWF 글로벌 통합 기상 모델 실시간 연동 • 하단 버튼으로 최신 관측치 새로고침")
        return embed

    @discord.ui.button(label="🔄 실시간 날씨 새로고침", style=discord.ButtonStyle.primary)
    async def refresh_weather_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        new_w, err = await asyncio.to_thread(core.fetch_accurate_weather_sync, self.query)
        if not err and new_w:
            self.w = new_w
        await interaction.edit_original_response(embed=self.build_embed(), view=self)


# ==========================================
# 끝말잇기 모달 & 게임 뷰 (두음법칙 완벽 지원)
# ==========================================
class WordChainInputModal(core.SafeModal, title="✏️ 끝말잇기 단어 입력"):
    word_input = discord.ui.TextInput(
        label="이어갈 한글 단어를 입력하세요 (2글자 이상)",
        placeholder="두음법칙 자동 적용! (예: 사과 -> 과일)",
        required=True,
        min_length=2,
        max_length=15
    )

    def __init__(self, game_view: "WordChainGameView"):
        super().__init__()
        self.game_view = game_view
        valid_chars = core.get_dueum_chars(game_view.current_word[-1])
        char_hint = " 또는 ".join([f"'{c}'" for c in valid_chars])
        self.word_input.label = f"{char_hint}(으)로 시작하는 단어 입력"

    async def on_submit(self, interaction: discord.Interaction):
        await self.game_view.process_turn(interaction, self.word_input.value.strip())


class WordChainGameView(core.SafeView):
    def __init__(self, host_user: discord.User, opponent: discord.Member | None, start_word: str):
        super().__init__(timeout=300)
        self.host_user = host_user
        self.opponent = opponent  # None이면 세카이 AI 봇과 1:1 대결
        self.current_word = start_word
        self.used_words = {start_word}
        self.chain_history = [f"🏁 `{start_word}`"]
        self.turn_user = host_user
        self.rally_count = 0
        self.finished = False
        self.status_notice = "아래 **[✏️ 단어 입력하기]** 버튼을 눌러 끝말잇기를 이어가세요!"

    def build_embed(self) -> discord.Embed:
        last_char = self.current_word[-1]
        valid_starts = core.get_dueum_chars(last_char)
        dueum_str = " 또는 ".join([f"**`{c}`**" for c in valid_starts])

        mode_str = f"⚔️ **{self.host_user.display_name}** vs **{self.opponent.display_name}**" if self.opponent else f"🤖 **{self.host_user.display_name}** vs **노로시 봇 (7랠리 돌파 시 +150💎)**"
        recent_chain = " ➔ ".join(self.chain_history[-8:])

        embed = discord.Embed(
            title="🔤 실시간 스피드 끝말잇기 배틀 (표준 두음법칙 적용)",
            description=(
                f"🎮 **대결 모드:** {mode_str}\n"
                f"🔥 **현재 랠리:** `{self.rally_count}회` 연속 성공\n"
                "───────────────────────────────────────\n"
                f"### 🎯 현재 제시어: **`{self.current_word}`**\n"
                f"👉 이어갈 첫 글자: {dueum_str}(으)로 시작하는 2글자 이상 단어\n\n"
                f"📜 **단어 체인 기록:**\n{recent_chain}\n\n"
                f"💡 **진행 안내:** {self.status_notice}"
            ),
            color=discord.Color.gold() if self.finished else discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        turn_label = "게임 종료" if self.finished else f"현재 차례: {self.turn_user.display_name}"
        embed.set_footer(text=f"{turn_label} • 이미 사용한 단어는 재사용할 수 없습니다.")
        return embed

    async def process_turn(self, interaction: discord.Interaction, word: str):
        if self.finished:
            await core.safe_send_response(interaction, content="ℹ️ 이미 종료된 게임입니다.", ephemeral=True)
            return

        if interaction.user.id != self.turn_user.id:
            await core.safe_send_response(interaction, content=f"⏳ 지금은 **{self.turn_user.display_name}**님의 차례입니다!", ephemeral=True)
            return

        clean_w = word.strip()
        if len(clean_w) < 2 or not all("가" <= ch <= "힣" for ch in clean_w):
            await core.safe_send_response(interaction, content="❌ **2글자 이상의 순수 한글 단어**만 입력할 수 있습니다!", ephemeral=True)
            return

        if not core.is_valid_word_chain_word(clean_w):
            await core.safe_send_response(
                interaction,
                content=f"❌ **`{clean_w}`** 단어는 사전에 등재되지 않은 단어입니다! (실제 표준 명사를 입력해 주세요)",
                ephemeral=True
            )
            return

        valid_starts = core.get_dueum_chars(self.current_word[-1])
        if clean_w[0] not in valid_starts:
            dueum_hint = " 또는 ".join([f"'{c}'" for c in valid_starts])
            await core.safe_send_response(
                interaction,
                content=f"❌ `{self.current_word}`의 끝 글자를 이어 **{dueum_hint}**(으)로 시작하는 단어를 입력해야 합니다!",
                ephemeral=True
            )
            return

        if clean_w in self.used_words:
            await core.safe_send_response(interaction, content=f"❌ **`{clean_w}`** 단어는 이번 게임에서 이미 사용된 단어입니다!", ephemeral=True)
            return

        await core.safe_defer(interaction)
        self.used_words.add(clean_w)
        self.current_word = clean_w
        self.rally_count += 1
        self.chain_history.append(f"👤 `{clean_w}`")

        # 1) 봇과의 1:1 대결 모드
        if self.opponent is None:
            if self.rally_count >= 7:
                self.finished = True
                self.input_btn.disabled = True
                self.surrender_btn.disabled = True
                data = await asyncio.to_thread(core.load_data)
                prof = core.ensure_user_profile(data, str(self.host_user.id), self.host_user.display_name)
                prof["crystals"] = prof.get("crystals", 0) + 150
                await asyncio.to_thread(core.save_data, data)
                self.status_notice = f"🎊 **축하합니다!** 7랠리를 모두 돌파하여 **{self.host_user.display_name}**님이 승리했습니다! (**`+150 💎`** 지급 완료, 보유: `{prof['crystals']:,}💎`)"
                await interaction.edit_original_response(embed=self.build_embed(), view=self)
                return

            bot_word = core.pick_bot_word(clean_w[-1], self.used_words)
            if not bot_word:
                self.finished = True
                self.input_btn.disabled = True
                self.surrender_btn.disabled = True
                data = await asyncio.to_thread(core.load_data)
                prof = core.ensure_user_profile(data, str(self.host_user.id), self.host_user.display_name)
                prof["crystals"] = prof.get("crystals", 0) + 150
                await asyncio.to_thread(core.save_data, data)
                self.status_notice = f"🏆 봇이 `{clean_w[-1]}`(으)로 시작하는 단어를 찾지 못해 기권했습니다! **{self.host_user.display_name}**님 완벽 승리! (**`+150 💎`** 지급 완료)"
                await interaction.edit_original_response(embed=self.build_embed(), view=self)
                return

            self.used_words.add(bot_word)
            self.current_word = bot_word
            self.chain_history.append(f"🤖 `{bot_word}`")
            self.status_notice = f"🤖 노로시 봇이 **`{bot_word}`**(으)로 받아쳤습니다! ({7 - self.rally_count}번 더 성공하면 승리 보너스 `+150💎`!)"
            await interaction.edit_original_response(embed=self.build_embed(), view=self)
        else:
            # 2) 유저 간 1:1 턴제 대결 모드
            self.turn_user = self.opponent if self.turn_user.id == self.host_user.id else self.host_user
            self.status_notice = f"✅ `{clean_w}` 통과! 이제 {self.turn_user.mention}님이 이어갈 차례입니다!"
            await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="✏️ 단어 입력하기", style=discord.ButtonStyle.primary)
    async def input_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.finished:
            await core.safe_send_response(interaction, content="ℹ️ 이미 종료된 게임입니다.", ephemeral=True)
            return
        if interaction.user.id != self.turn_user.id:
            await core.safe_send_response(interaction, content=f"⏳ 지금은 **{self.turn_user.display_name}**님의 차례입니다!", ephemeral=True)
            return
        await interaction.response.send_modal(WordChainInputModal(self))

    @discord.ui.button(label="🏳️ 기권하기", style=discord.ButtonStyle.danger)
    async def surrender_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.finished:
            return
        allowed_ids = {self.host_user.id}
        if self.opponent:
            allowed_ids.add(self.opponent.id)
        if interaction.user.id not in allowed_ids:
            await core.safe_send_response(interaction, content="❌ 대결 참가자만 기권할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        self.finished = True
        self.input_btn.disabled = True
        self.surrender_btn.disabled = True

        if self.opponent:
            winner = self.opponent if interaction.user.id == self.host_user.id else self.host_user
            data = await asyncio.to_thread(core.load_data)
            prof = core.ensure_user_profile(data, str(winner.id), winner.display_name)
            prof["crystals"] = prof.get("crystals", 0) + 100
            await asyncio.to_thread(core.save_data, data)
            self.status_notice = f"🏳️ **{interaction.user.display_name}**님이 기권하여 **{winner.display_name}**님이 승리했습니다! (승리 보상 **`+100 💎`** 지급)"
        else:
            self.status_notice = f"🏳️ **{interaction.user.display_name}**님이 아쉽게 기권하셨습니다. (총 `{self.rally_count}`랠리 달성)"

        await interaction.edit_original_response(embed=self.build_embed(), view=self)


# ==========================================
# 러시안룰렛 6연발 생존 게임 뷰
# ==========================================
ROULETTE_PENALTIES = [
    "🎭 다음 채팅 3줄을 오시 캐릭터 말투로 작성하기!",
    "🍜 오늘 가장 먼저 인사하는 서버원에게 따뜻한 칭찬 한마디 건네기!",
    "🎵 지금 듣고 있는 노래나 최애곡 하나를 채팅방에 공유하기!",
    "🌟 디데이 전광판이나 오늘 목표 1개 달성 인증하기!",
    "💬 프로필 상태메시지를 10분 동안 '러시안룰렛 당첨자💥'로 바꾸기!"
]


class RussianRouletteView(core.SafeView):
    def __init__(self, host_user: discord.User, bullets: int = 1, bet_crystals: int = 50):
        super().__init__(timeout=300)
        import random
        self.host_user = host_user
        self.bullets = bullets
        self.bet_crystals = bet_crystals
        self.chambers = [True] * bullets + [False] * (6 - bullets)
        random.shuffle(self.chambers)
        self.current_idx = 0
        self.survivor_streak = 0
        self.last_survivor_user: Optional[discord.User] = None
        self.pot_crystals = bet_crystals
        self.participants = []
        self.finished = False
        self.last_log = "🔫 6연발 리볼버 실린더가 회전하며 장전되었습니다. 용기 있는 분이 방아쇠를 당겨주세요!"

    def _cylinder_visual(self) -> str:
        icons = []
        for i in range(6):
            if i < self.current_idx:
                icons.append("💨")
            elif i == self.current_idx and self.finished and self.chambers[i]:
                icons.append("💥")
            else:
                icons.append("⚪")
        return " [ " + " · ".join(icons) + " ] "

    def build_embed(self) -> discord.Embed:
        rem_slots = 6 - self.current_idx
        danger_pct = round((self.bullets / max(1, rem_slots)) * 100, 1) if not self.finished else 0.0

        embed = discord.Embed(
            title="🔫 스릴 만점 세카이 러시안룰렛 (6연발 리볼버)",
            description=(
                f"🎯 **장전 실탄:** `6발 중 {self.bullets}발` (현재 격발 확률: **`{danger_pct}%`**)\n"
                f"💎 **누적 생존 상금:** **`{self.pot_crystals:,} 💎`** (생존 콤보: `{self.survivor_streak}연속`)\n"
                "───────────────────────────────────────\n"
                f"### 🔄 실린더 상태: `{self._cylinder_visual()}`\n\n"
                f"📢 **상황 중계:**\n> {self.last_log}"
            ),
            color=discord.Color.red() if self.finished else discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text=f"개설자: {self.host_user.display_name} • [방아쇠 당기기]로 스릴을 즐기거나 [생존 스톱]으로 상금을 챙기세요!")
        return embed

    @discord.ui.button(label="🔫 방아쇠 당기기 (격발)", style=discord.ButtonStyle.danger)
    async def pull_trigger_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.finished:
            await core.safe_send_response(interaction, content="ℹ️ 이미 종료된 게임입니다.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        import random
        is_bullet = self.chambers[self.current_idx]

        if is_bullet:
            self.finished = True
            self.last_survivor_user = None
            self.pull_trigger_btn.disabled = True
            self.cashout_btn.disabled = True
            self.spin_btn.disabled = True
            penalty = random.choice(ROULETTE_PENALTIES)
            self.last_log = (
                f"💥 **빵야!! ({self.current_idx + 1}번째 약실 실탄 격발!)**\n"
                f"> 😱 당첨자: {interaction.user.mention}님이 실탄에 맞았습니다!\n"
                f"> 🎲 **오늘의 미니 벌칙:** `{penalty}`"
            )
            await interaction.edit_original_response(embed=self.build_embed(), view=self)
        else:
            self.current_idx += 1
            self.survivor_streak += 1
            self.last_survivor_user = interaction.user
            bonus = 30 * self.bullets + (self.survivor_streak * 20)
            self.pot_crystals += bonus
            if interaction.user.display_name not in self.participants:
                self.participants.append(interaction.user.display_name)

            # 남은 약실이 모두 실탄인 경우 자동 생존 올클리어 승리!
            rem_slots = 6 - self.current_idx
            if rem_slots <= self.bullets:
                self.finished = True
                self.pull_trigger_btn.disabled = True
                self.cashout_btn.disabled = True
                self.spin_btn.disabled = True
                data = await asyncio.to_thread(core.load_data)
                prof = core.ensure_user_profile(data, str(interaction.user.id), interaction.user.display_name)
                prof["crystals"] = prof.get("crystals", 0) + self.pot_crystals
                await asyncio.to_thread(core.save_data, data)
                self.last_log = (
                    f"💨 **찰칵! ({self.current_idx}번째 약실 생존!)**\n"
                    f"🎊 **퍼펙트 서바이벌!** 빈 약실을 모두 찾아내어 {interaction.user.mention}님이 최종 상금 **`+{self.pot_crystals:,} 💎`**를 획득했습니다!"
                )
            else:
                self.last_log = (
                    f"💨 **찰칵! ({self.current_idx}번째 약실은 빈 약실이었습니다!)**\n"
                    f"> 😮‍💨 {interaction.user.mention}님 생존 성공! 상금이 **`{self.pot_crystals:,} 💎`**(`+{bonus}💎`)로 상승했습니다!"
                )
            await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="💰 생존 스톱 & 상금 수령", style=discord.ButtonStyle.success)
    async def cashout_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.finished:
            return
        if self.survivor_streak < 1 or not self.last_survivor_user:
            await core.safe_send_response(interaction, content="⚠️ 최소 1번 이상 방아쇠를 당겨 생존한 후에만 상금을 수령할 수 있습니다!", ephemeral=True)
            return
        if interaction.user.id != self.last_survivor_user.id:
            await core.safe_send_response(
                interaction,
                content=f"❌ 직전에 방아쇠를 당겨 생존한 **{self.last_survivor_user.display_name}**님만 상금을 수령(생존 스톱)할 수 있습니다!",
                ephemeral=True
            )
            return

        await core.safe_defer(interaction)
        self.finished = True
        self.pull_trigger_btn.disabled = True
        self.cashout_btn.disabled = True
        self.spin_btn.disabled = True

        data = await asyncio.to_thread(core.load_data)
        prof = core.ensure_user_profile(data, str(interaction.user.id), interaction.user.display_name)
        prof["crystals"] = prof.get("crystals", 0) + self.pot_crystals
        await asyncio.to_thread(core.save_data, data)

        self.last_log = (
            f"💰 **생존 스톱 성공!** {interaction.user.mention}님이 `{self.survivor_streak}연속` 생존 후 멈추어 "
            f"누적 상금 **`+{self.pot_crystals:,} 💎`**를 안전하게 수령했습니다! (보유: `{prof['crystals']:,}💎`)"
        )
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔄 실린더 다시 돌리기 (1회)", style=discord.ButtonStyle.secondary)
    async def spin_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.finished:
            return
        await core.safe_defer(interaction)
        import random
        random.shuffle(self.chambers)
        self.current_idx = 0
        self.survivor_streak = 0
        self.last_survivor_user = None
        self.spin_btn.disabled = True
        self.last_log = f"🔄 {interaction.user.mention}님이 리볼버 실린더를 힘껏 돌려 약실 위치를 다시 섞었습니다! (생존 콤보가 초기화되었습니다)"
        await interaction.edit_original_response(embed=self.build_embed(), view=self)


# ==========================================
# /건의 관련 약관 및 모달 & 뷰
# ==========================================
SUGGESTION_TERMS_SUMMARY = (
    "📜 **[norosi 건의 및 피드백 처리 이용약관]**\n"
    "1. **수집 및 이용 목적**: 서비스 품질 향상, 시스템 버그 해결 및 유저 제안 신규 기능 검토\n"
    "2. **수집 항목**:\n"
    "   • **익명 건의**: 건의 접수 번호, 제목, 상세 내용, 접수 일시 (*디스코드 유저 ID 및 닉네임 일체 미수집*)\n"
    "   • **계정 공개**: 건의 접수 번호, 제목, 상세 내용, 접수 일시, 디스코드 유저 ID 및 닉네임\n"
    "3. **금지 행위**: 타인에 대한 모욕·비방, 욕설, 허위 사실 유포, 음란물, 개인정보 노출, 스팸성 반복 전송 시 봇 이용이 제한될 수 있습니다.\n"
    "4. **보관 기간**: 처리 완료 및 통계 목적으로 접수일로부터 6개월간 안전하게 보관된 후 파기됩니다."
)


async def save_and_notify_suggestion(
    bot,
    user: discord.User | discord.Member,
    guild: discord.Guild,
    title: str,
    content: str,
    is_anonymous: bool,
    attachment_url: str = None,
    attachment_name: str = None
) -> dict:
    data = await asyncio.to_thread(core.load_data)
    suggestions = data.setdefault("suggestions", [])
    now_kst = datetime.datetime.now(core.KST)
    sugg_id = f"SUGG-{now_kst.strftime('%Y%m%d')}-{len(suggestions) + 1:04d}"

    entry = {
        "id": sugg_id,
        "is_anonymous": is_anonymous,
        "user_id": 0 if is_anonymous else user.id,
        "user_name": "익명의 세카이 멤버" if is_anonymous else user.display_name,
        "guild_id": guild.id if guild else 0,
        "guild_name": guild.name if guild else "개인 DM",
        "title": title.strip()[:100],
        "content": content.strip()[:1500],
        "attachment_url": (attachment_url or "").strip() or None,
        "attachment_name": (attachment_name or "첨부 파일").strip(),
        "created_at": now_kst.strftime("%Y-%m-%d %H:%M:%S KST"),
        "status": "접수 완료"
    }
    suggestions.append(entry)
    await asyncio.to_thread(core.save_data, data)

    # 봇 개발자(BOT_OWNER_ID)에게 DM 알림 전송 시도
    if core.BOT_OWNER_ID:
        try:
            owner = bot.get_user(core.BOT_OWNER_ID)
            if not owner:
                owner = await bot.fetch_user(core.BOT_OWNER_ID)
            if owner:
                owner_embed = discord.Embed(
                    title=f"📬 [새로운 건의사항 도착] {sugg_id}",
                    description=f"**제목:** {entry['title']}\n\n**내용:**\n```{entry['content']}```",
                    color=discord.Color.from_rgb(0, 204, 221),
                    timestamp=now_kst
                )
                owner_embed.add_field(
                    name="보낸 사람",
                    value="🔒 익명 (비공개 보호)" if is_anonymous else f"👤 {user.mention} (`{user.id}`)",
                    inline=True
                )
                owner_embed.add_field(name="접수 서버", value=f"🏰 {entry['guild_name']}", inline=True)
                owner_embed.add_field(name="접수 일시", value=f"🕒 `{entry['created_at']}`", inline=True)

                if entry.get("attachment_url"):
                    owner_embed.add_field(
                        name="📎 첨부 미디어 파일",
                        value=f"[{entry['attachment_name']}]({entry['attachment_url']})",
                        inline=False
                    )
                    url_lower = entry["attachment_url"].lower()
                    if any(ext in url_lower for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
                        owner_embed.set_image(url=entry["attachment_url"])

                await owner.send(embed=owner_embed)
        except Exception as e:
            print(f"ℹ️ 봇 소유자 건의 알림 DM 전송 생략: {e}", flush=True)

    return entry


def build_suggestion_result_embed(entry: dict) -> discord.Embed:
    is_anon = entry["is_anonymous"]
    embed = discord.Embed(
        title=f"✅ 건의사항이 성공적으로 접수되었습니다! ({entry['id']})",
        description=(
            "보내주신 소중한 의견은 norosi 봇 개발 및 서비스 개선에 적극 반영됩니다.\n\n"
            f"📌 **건의 제목:** `{entry['title']}`\n"
            f"🔒 **공개 유형:** {'🔒 익명 건의 (내 계정 정보 비공개)' if is_anon else '📢 계정 공개 건의 (답변 및 피드백 가능)'}\n"
            f"🕒 **접수 시각:** `{entry['created_at']}`\n\n"
            f"**접수된 내용 요약:**\n> {entry['content'][:250]}{'...' if len(entry['content']) > 250 else ''}\n\n"
            "───────────────────────────────────────\n"
            f"{SUGGESTION_TERMS_SUMMARY}"
        ),
        color=discord.Color.green(),
        timestamp=datetime.datetime.now(core.KST)
    )

    if entry.get("attachment_url"):
        embed.add_field(
            name="📎 첨부 미디어",
            value=f"[{entry['attachment_name']}]({entry['attachment_url']})",
            inline=False
        )
        url_lower = entry["attachment_url"].lower()
        if any(ext in url_lower for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
            embed.set_image(url=entry["attachment_url"])

    embed.set_footer(text="이용약관 및 개인정보 처리방침에 따라 안전하게 보호·처리됩니다.")
    return embed


class SuggestionSubmitModal(core.SafeModal):
    def __init__(
        self,
        bot,
        is_anonymous: bool = True,
        initial_title: str = "",
        attachment_url: str = None,
        attachment_name: str = None
    ):
        mode_str = "익명 건의" if is_anonymous else "계정 공개 건의"
        super().__init__(title=f"📝 norosi {mode_str} 작성")
        self.bot = bot
        self.is_anonymous = is_anonymous
        self.attachment_url = attachment_url
        self.attachment_name = attachment_name

        self.sugg_title = discord.ui.TextInput(
            label="건의 제목 (한줄 요약)",
            placeholder="예: 음악 추천 기능에 J-POP / 보컬로이드 태그 추가해 주세요",
            default=initial_title,
            min_length=2,
            max_length=80,
            required=True
        )
        self.sugg_content = discord.ui.TextInput(
            label="상세 건의 내용 (약관 준수)",
            style=discord.TextStyle.paragraph,
            placeholder="건의 사항이나 버그 내용, 제안 아이디어를 자유롭게 적어주세요. (욕설/비방 금지)",
            min_length=5,
            max_length=1500,
            required=True
        )
        self.sugg_media_url = discord.ui.TextInput(
            label="추가 이미지/스크린샷 링크 (선택)",
            placeholder="예: https://cdn.discordapp.com/... 또는 Imgur 링크 (미입력 가능)",
            default=attachment_url or "",
            required=False,
            max_length=500
        )
        self.add_item(self.sugg_title)
        self.add_item(self.sugg_content)
        self.add_item(self.sugg_media_url)

    async def on_submit(self, interaction: discord.Interaction):
        await core.safe_defer(interaction, ephemeral=True)
        final_media_url = self.attachment_url or (self.sugg_media_url.value.strip() if self.sugg_media_url.value else None)
        final_media_name = self.attachment_name or ("첨부 이미지" if final_media_url else None)

        entry = await save_and_notify_suggestion(
            self.bot,
            interaction.user,
            interaction.guild,
            self.sugg_title.value,
            self.sugg_content.value,
            self.is_anonymous,
            attachment_url=final_media_url,
            attachment_name=final_media_name
        )
        embed = build_suggestion_result_embed(entry)
        await interaction.followup.send(embed=embed, ephemeral=True)


class SuggestionTypeSelectView(core.SafeView):
    def __init__(self, bot, attachment_url: str = None, attachment_name: str = None):
        super().__init__(timeout=180)
        self.bot = bot
        self.attachment_url = attachment_url
        self.attachment_name = attachment_name

        # 이용약관 공식 노션 링크 버튼 추가
        self.add_item(discord.ui.Button(
            label="📜 이용약관 전문 보기",
            style=discord.ButtonStyle.link,
            url="https://app.notion.com/p/40f0518d0603809ea4bde601d93fbffb?source=copy_link"
        ))

    def build_overview_embed(self) -> discord.Embed:
        desc_lines = [
            "norosi 봇을 이용해 주셔서 감사합니다! 원하시는 건의 방식을 아래 버튼에서 선택해 주세요.",
            ""
        ]
        if self.attachment_name:
            desc_lines.extend([
                f"📎 **미리 첨부된 미디어:** `{self.attachment_name}` (건의 작성 시 함께 전송됩니다)",
                ""
            ])
        desc_lines.extend([
            "### 🔒 익명 건의",
            "• 사용자의 디스코드 프로필, 유저 ID, 아바타 정보를 일체 수집하지 않습니다.",
            "• 편안하고 자유롭게 의견이나 개선점을 남기실 수 있습니다.",
            "",
            "### 📢 계정 공개 건의",
            "• 닉네임과 디스코드 ID가 포함되어 접수됩니다.",
            "• 개발진이 필요시 추가 확인이나 답변, 보상 크리스탈(💎)을 드릴 수 있습니다.",
            "",
            "───────────────────────────────────────",
            SUGGESTION_TERMS_SUMMARY
        ])

        embed = discord.Embed(
            title="📝 norosi 봇 건의 및 피드백 센터",
            description="\n".join(desc_lines),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        if self.attachment_url and any(ext in self.attachment_url.lower() for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
            embed.set_thumbnail(url=self.attachment_url)
        embed.set_footer(text="버튼을 누르면 건의 작성 모달 창이 열립니다.")
        return embed

    @discord.ui.button(label="🔒 익명으로 건의 작성", style=discord.ButtonStyle.secondary, emoji="🔒")
    async def anon_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            SuggestionSubmitModal(
                self.bot,
                is_anonymous=True,
                attachment_url=self.attachment_url,
                attachment_name=self.attachment_name
            )
        )

    @discord.ui.button(label="📢 계정 공개로 건의 작성", style=discord.ButtonStyle.primary, emoji="📢")
    async def public_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            SuggestionSubmitModal(
                self.bot,
                is_anonymous=False,
                attachment_url=self.attachment_url,
                attachment_name=self.attachment_name
            )
        )


async def setup(bot):
    await bot.add_cog(StatsCog(bot))

