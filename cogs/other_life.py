"""
cogs/other_life.py - 「타인의인생」 0세~노년 풀 스토리 인생 시뮬레이션 Cog
- /타인의인생 플레이 [출신] [시간배율] : 실시간 시간 배율(45초=1년 표준 / 15초 쾌속 / 3분 슬로우 / 턴제) + 능동 분기 선택
- /타인의인생 도감 : 16종 멀티 엔딩 도감 & 내 과거 인생 전기 아카이브 열람
- /타인의인생 랭킹 : 서버 엔딩 수집 · 최고 점수 · 최장 수명 랭킹 보드
- !타인의인생 / !인생게임 / !타인 : 빠른 접두사 단축어 지원
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

import core
import other_life_core


def _stat_bar(val: int) -> str:
    clamped = max(0, min(100, int(val or 0)))
    filled = round(clamped / 20)
    return ("▓" * filled + "░" * (5 - filled)) + f" `{clamped:02d}`"


def _format_stats_block(stats: Dict[str, Any]) -> str:
    return (
        f"🧠 지성 {_stat_bar(stats.get('intellect', 0))}  ·  "
        f"🔥 열정 {_stat_bar(stats.get('passion', 0))}  ·  "
        f"💗 공감 {_stat_bar(stats.get('empathy', 0))}\n"
        f"🛡️ 근성 {_stat_bar(stats.get('grit', 0))}  ·  "
        f"🪙 자산 {_stat_bar(stats.get('wealth', 0))}"
    )


def _next_tick_text(life: Dict[str, Any]) -> str:
    if life.get("finished"):
        return "인생 완결"
    scale_id = str(life.get("time_scale") or other_life_core.DEFAULT_TIME_SCALE)
    scale = other_life_core.TIME_SCALES.get(scale_id, other_life_core.TIME_SCALES[other_life_core.DEFAULT_TIME_SCALE])
    sec_per_year = int(scale.get("sec_per_year", 0))
    if sec_per_year <= 0:
        return "📖 턴제 정주행 (대기 없음)"

    cur_age = int(life.get("age", 6) or 6)
    ceiling = other_life_core._stage_age_ceiling(int(life.get("beat", 1) or 1), cur_age)
    if cur_age >= ceiling:
        return f"⏸️ {cur_age}세 분기점 도달 (선택지 클릭 시 다음 챕터로)"

    now_f = datetime.datetime.now(core.KST).timestamp()
    last_f = float(life.get("last_tick_at") or now_f)
    rem = max(0, int(sec_per_year - max(0.0, now_f - last_f)))
    if rem == 0:
        return f"⏳ 다음 일상(+1세) 반영 대기 중 (`🔄 세월 확인` 클릭)"
    if rem >= 60:
        m, s = divmod(rem, 60)
        return f"⏳ 다음 +1세까지 `{m}분 {s:02d}초` *(상한 {ceiling}세 · 즉시 진행 가능)*"
    return f"⏳ 다음 +1세까지 `{rem}초` *(상한 {ceiling}세 · 즉시 진행 가능)*"


_UNLOCK_HINTS: Dict[str, str] = {
    "hidden_star": "유년·학창·중년에 별과 이치의 씨앗을 품고 높은 지성·공감을 유지해 70세 귀향에서 별빛을 마주하세요.",
    "flame_39": "체력/건강(근성)을 소진할 만큼 치열하게 살다가 39세 화재의 밤에 온몸을 던져 보세요.",
    "old_promise": "어린 소꿉친구와 18세의 약속을 맺고, 26세 혹은 44세 재회에서 끝내 서로의 손을 잡으세요.",
    "truth_keeper": "수호·언론인의 길이나 내부고발에서 양심을 꺾지 않고 높은 공감을 지켜내세요.",
    "master_craft": "예술·학문·장인의 외길을 편법 없이 파고들어 최고 수준의 역량(65+)에 도달하세요.",
    "unheard_genius": "예술가·학자로서 자산은 적지만 흔들리지 않는 열정과 순수한 작품으로 마지막까지 걸어가세요.",
    "healer_hands": "산골 약초방 출신이나 의학·연구의 길에서 생명을 살리는 맹세를 지켜내세요.",
    "broken_crown": "유혹과 편법의 길로 접어든 뒤 끝내 참회하지 않고 욕망의 끝까지 달려가 보세요.",
    "redeemed_spring": "젊은 날의 오만이나 그림자의 과거가 있더라도 50세의 심판 앞에서 진심으로 뉘우쳐 보세요.",
    "masked_shadow": "뒷세계 그림자 브로커로 살아가며 끝까지 가면을 벗지 않아 보세요.",
    "empire_builder": "사업가의 길이나 막대한 자산(72+)을 일구어 시대의 거물로 우뚝 서 보세요.",
    "horizon_writer": "방랑·기록가의 길을 걷거나 노년에 늦깎이 세계 여행을 떠나 보세요.",
    "noodle_universe": "시장통 국수집 출신으로 장인의 길을 걷거나 30세의 폭풍에서 어머니의 국수집으로 돌아가 보세요.",
    "teacher_bridge": "스승의 유지를 잇거나 50~56세에 다음 세대를 기르는 어른이 되어 보세요.",
    "village_lantern": "이웃과 지역 사회를 따뜻하게 돌보며 높은 공감의 발자취를 남기세요.",
    "quiet_miracle": "극단으로 치우치지 않고 소박하고 성실하게 백 년의 일상을 채워 보세요.",
}


# ==========================================
# 1. Setup Selects (출신 & 시간 배율)
# ==========================================
class OtherLifeOriginSelect(discord.ui.Select):
    def __init__(self, parent_view: "OtherLifeGameView", selected_origin: str):
        self.parent_view = parent_view
        opts = [
            discord.SelectOption(
                label="🎲 운명에 맡기기 (무작위 출신)",
                value="random",
                description="6가지 출신 배경 중 하나가 랜덤하게 배정됩니다",
                emoji="🎲",
                default=(selected_origin == "random"),
            )
        ]
        for oid, orig in other_life_core.ORIGINS.items():
            opts.append(discord.SelectOption(
                label=orig["name"][:95],
                value=oid,
                description=orig["hook"][:95],
                default=(selected_origin == oid),
            ))
        super().__init__(
            placeholder="🧬 태어날 출신 환경 선택...",
            min_values=1,
            max_values=1,
            options=opts[:25],
            row=0,
            custom_id="norosi:OtherLifeGameView:origin_select",
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        pv.selected_origin = self.values[0]
        pv.status_msg = (
            "🎲 무작위 출신을 선택했습니다."
            if pv.selected_origin == "random"
            else f"🧬 출신지를 **{other_life_core.ORIGINS[pv.selected_origin]['name']}**(으)로 예약했습니다."
        )
        pv._rebuild()
        await core.safe_edit_response(interaction, embed=pv.build_embed(), view=pv)


class OtherLifeScaleSelect(discord.ui.Select):
    def __init__(self, parent_view: "OtherLifeGameView", current_scale: str, row: int = 1):
        self.parent_view = parent_view
        opts = []
        for sid, sc in other_life_core.TIME_SCALES.items():
            opts.append(discord.SelectOption(
                label=sc["name"][:95],
                value=sid,
                description=sc["short_desc"][:95],
                emoji=sc["emoji"],
                default=(sid == current_scale),
            ))
        super().__init__(
            placeholder="⏱️ 세월 시간 배율 변경...",
            min_values=1,
            max_values=1,
            options=opts[:25],
            row=row,
            custom_id="norosi:OtherLifeGameView:scale_select",
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        await core.safe_defer(interaction)
        new_scale = self.values[0]
        pv.selected_scale = new_scale
        ok, msg, updated_u = await asyncio.to_thread(
            other_life_core.set_life_time_scale,
            pv.guild_id,
            interaction.user.id,
            new_scale,
            interaction.user.display_name,
        )
        pv.user_state = updated_u
        pv.status_msg = msg
        pv._rebuild()
        await core.safe_edit_response(interaction, embed=pv.build_embed(), view=pv)


# ==========================================
# 2. 새 인생 시작 확인 View (진행 중 덮어쓰기 방지)
# ==========================================
class OtherLifeConfirmResetView(core.SafeView):
    def __init__(
        self,
        parent_view: Optional["OtherLifeGameView"] = None,
        user: Optional[discord.abc.User] = None,
        guild_id: int = 0,
    ):
        super().__init__(timeout=60)
        self.parent_view = parent_view
        self.user = user or (parent_view.user if parent_view else None)
        self.guild_id = int(guild_id or (parent_view.guild_id if parent_view else 0))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인만 선택할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🧬 출신·배율 골라서 새로 시작", style=discord.ButtonStyle.danger, row=0)
    async def btn_confirm_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        u_state, _, _ = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        gv = self.parent_view or OtherLifeGameView(interaction.user, self.guild_id, user_state=u_state)
        gv.user_state = u_state
        gv.mode = "setup"
        gv.status_msg = "🧬 새로운 타인의 인생을 시작하기 위해 출신과 배율을 선택해 주세요."
        gv._rebuild()
        await core.safe_edit_response(interaction, embed=gv.build_embed(), view=gv)

    @discord.ui.button(label="🌱 랜덤으로 즉시 시작", style=discord.ButtonStyle.success, row=0)
    async def btn_confirm_quick(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg, u_state = await asyncio.to_thread(
            other_life_core.start_new_life,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        gv = self.parent_view or OtherLifeGameView(interaction.user, self.guild_id, user_state=u_state)
        gv.user_state = u_state
        gv.mode = "play"
        gv.status_msg = msg
        gv._rebuild()
        await core.safe_edit_response(interaction, embed=gv.build_embed(), view=gv)

    @discord.ui.button(label="◀ 지금 인생 계속하기", style=discord.ButtonStyle.secondary, row=0)
    async def btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        u_state, yrs, logs = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        gv = self.parent_view or OtherLifeGameView(interaction.user, self.guild_id, user_state=u_state)
        gv.user_state = u_state
        gv.mode = "play"
        gv.idle_logs = logs
        gv.status_msg = "📖 현재 살아가던 인생으로 돌아왔습니다."
        gv._rebuild()
        await core.safe_edit_response(interaction, embed=gv.build_embed(), view=gv)


# ==========================================
# 3. 도감 & 연대기 View (16종 멀티 엔딩 + 과거 기록)
# ==========================================
class OtherLifeCollectionView(core.SafeView):
    def __init__(
        self,
        user: Optional[discord.abc.User] = None,
        guild_id: int = 0,
        user_state: Optional[Dict[str, Any]] = None,
        tab: str = "endings",
    ):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        if user_state is None:
            uid = user.id if user else 0
            uname = user.display_name if user else "여행자"
            u_state, _, _ = other_life_core.get_other_life_state(self.guild_id, uid, uname)
            self.user_state = u_state
        else:
            self.user_state = user_state
        self.tab = tab  # "endings" or "history"
        self.page = 0
        self._rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 도감은 **{self.user.display_name}**님의 기록입니다. `/타인의인생 도감`으로 열어주세요!",
                ephemeral=True,
            )
            return False
        return True

    def _rebuild(self):
        self.clear_items()
        btn_endings = discord.ui.Button(
            label="📚 엔딩 도감 (16종)",
            style=discord.ButtonStyle.primary if self.tab == "endings" else discord.ButtonStyle.secondary,
            row=0,
            custom_id="norosi:OtherLifeCollectionView:tab_endings",
        )
        btn_endings.callback = self._on_tab_endings
        self.add_item(btn_endings)

        btn_history = discord.ui.Button(
            label="📖 최근 전기·연대기",
            style=discord.ButtonStyle.primary if self.tab == "history" else discord.ButtonStyle.secondary,
            row=0,
            custom_id="norosi:OtherLifeCollectionView:tab_history",
        )
        btn_history.callback = self._on_tab_history
        self.add_item(btn_history)

        max_p = self._max_page()
        btn_prev = discord.ui.Button(
            label="◀ 이전",
            style=discord.ButtonStyle.secondary,
            disabled=(self.page <= 0),
            row=0,
            custom_id="norosi:OtherLifeCollectionView:prev",
        )
        btn_prev.callback = self._on_prev
        self.add_item(btn_prev)

        btn_next = discord.ui.Button(
            label="다음 ▶",
            style=discord.ButtonStyle.secondary,
            disabled=(self.page >= max_p),
            row=0,
            custom_id="norosi:OtherLifeCollectionView:next",
        )
        btn_next.callback = self._on_next
        self.add_item(btn_next)

        btn_play = discord.ui.Button(
            label="🎮 인생 플레이로 이동",
            style=discord.ButtonStyle.success,
            row=0,
            custom_id="norosi:OtherLifeCollectionView:open_play",
        )
        btn_play.callback = self._on_open_play
        self.add_item(btn_play)

    def _max_page(self) -> int:
        if self.tab == "endings":
            return 1  # 16 endings / 8 per page = 2 pages (0, 1)
        hist = self.user_state.get("history") or []
        if not hist:
            return 0
        return max(0, (len(hist) - 1) // 5)

    def build_embed(self) -> discord.Embed:
        u = self.user_state
        uname = self.user.display_name if self.user else u.get("user_name", "플레이어")
        unlocked = u.get("unlocked_endings") or {}
        unlocked_cnt = len([k for k in unlocked if k in other_life_core.ENDINGS])
        total_endings = len(other_life_core.ENDINGS)

        if self.tab == "endings":
            all_ids = list(other_life_core.ENDINGS.keys())
            per = 8
            self.page = max(0, min(self.page, 1))
            slice_ids = all_ids[self.page * per:(self.page + 1) * per]
            lines = []
            for eid in slice_ids:
                em = other_life_core.ENDINGS[eid]
                cnt = unlocked.get(eid, 0)
                if cnt > 0:
                    lines.append(
                        f"{em['emoji']} **{em['title']}** `[{em['rarity']} · {cnt}회 달성]` (+{em['base_crystal']}💎)\n"
                        f"> {em['summary']}"
                    )
                else:
                    hint = _UNLOCK_HINTS.get(eid, "다양한 출신과 선택을 시도해 보세요.")
                    lines.append(
                        f"🔒 **???** `[{em['rarity']}]` *(미해금 · 초회 +120💎 보너스)*\n"
                        f"> 💡 힌트: {hint}"
                    )
            embed = discord.Embed(
                title=f"📚 {uname}님의 타인의 인생 엔딩 도감 ({unlocked_cnt}/{total_endings})",
                description=(
                    f"누적 완결 생애 **`{u.get('lives_completed', 0)}회`** · "
                    f"최고 점수 **`{u.get('best_score', 0):,}점`** · "
                    f"최장 수명 **`{u.get('longest_age', 0)}세`**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    + "\n\n".join(lines)
                )[:4000],
                color=0x8B5CF6,
                timestamp=datetime.datetime.now(core.KST),
            )
            embed.set_footer(text=f"엔딩 도감 {self.page + 1} / 2 페이지  •  엔딩당 초회 해금 시 +120💎 보너스")
            return embed

        # History / Chronicle tab
        hist = u.get("history") or []
        active = u.get("active_life")
        blocks: List[str] = []
        if isinstance(active, dict) and not active.get("finished") and self.page == 0:
            tail = (active.get("chronicle") or [])[-5:]
            blocks.append(
                f"🌱 **현재 진행 중: {active.get('name')} ({active.get('age')}세 · {active.get('beat')}/18장)**\n"
                + "\n".join(f"> {c}" for c in tail)
            )

        if not hist:
            if not blocks:
                blocks.append("*(아직 완결된 타인의 인생 전기가 없습니다. 첫 생애를 끝까지 살아보세요!)*")
        else:
            per = 5
            start = self.page * per
            for idx, h in enumerate(hist[start:start + per], start + 1):
                orig_name = other_life_core.ORIGINS.get(str(h.get("origin_id")), {}).get("place", "알 수 없는 곳")
                tail_s = "\n".join(f"  {t}" for t in (h.get("chronicle_tail") or [])[-3:])
                blocks.append(
                    f"`#{idx}` {h.get('ending_emoji', '📖')} **{h.get('name')}** "
                    f"({h.get('age', 0)}세 · {h.get('career_label', '방랑')}) — **{h.get('ending_title')}** `[{h.get('score', 0):,}점]`\n"
                    f"출신: {orig_name} · {h.get('finished_at', '')}\n{tail_s}"
                )

        embed = discord.Embed(
            title=f"📖 {uname}님의 타인의 인생 전기 아카이브",
            description="\n\n".join(blocks)[:4000],
            color=0x0EA5E9,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text=f"전기 아카이브 {self.page + 1} / {self._max_page() + 1} 페이지 (최근 30생애 보존)")
        return embed

    async def _on_tab_endings(self, interaction: discord.Interaction):
        self.tab = "endings"
        self.page = 0
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_tab_history(self, interaction: discord.Interaction):
        self.tab = "history"
        self.page = 0
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_prev(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_next(self, interaction: discord.Interaction):
        self.page = min(self._max_page(), self.page + 1)
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_open_play(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        u_state, _, idle_logs = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        gv = OtherLifeGameView(interaction.user, self.guild_id, user_state=u_state, idle_logs=idle_logs)
        await core.safe_edit_response(interaction, embed=gv.build_embed(), view=gv)


# ==========================================
# 4. 서버 랭킹 View
# ==========================================
class OtherLifeRankingView(core.SafeView):
    def __init__(self, user: Optional[discord.abc.User] = None, guild_id: int = 0):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.rows = other_life_core.get_other_life_ranking(self.guild_id, limit=10)

    def build_embed(self) -> discord.Embed:
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        total_endings = len(other_life_core.ENDINGS)
        for idx, r in enumerate(self.rows, 1):
            badge = medals[idx - 1] if idx <= 3 else f"`{idx}위`"
            lines.append(
                f"{badge} **{r['user_name']}** — 엔딩 **`{r['endings_cnt']}/{total_endings}종`** · "
                f"최고 **`{r['best_score']:,}점`** · 완결 `{r['lives_completed']}회` *(최장 {r['longest_age']}세)*"
            )
        body = "\n".join(lines) if lines else "*(아직 이 서버에 완결된 타인의 인생 기록이 없습니다. 첫 엔딩의 주인공이 되어보세요!)*"
        embed = discord.Embed(
            title="🏆 타인의 인생 — 서버 랭킹 TOP 10",
            description=(
                "수집한 고유 엔딩 수와 최고 인생 점수 기준으로 집계됩니다.\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                + body
            ),
            color=0xF59E0B,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="`/타인의인생 플레이` 또는 `!타인의인생`으로 새로운 생애를 살아보세요!")
        return embed

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.rows = await asyncio.to_thread(other_life_core.get_other_life_ranking, self.guild_id, 10)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🎮 내 인생 플레이하기", style=discord.ButtonStyle.success, row=0)
    async def btn_play(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        u_state, _, idle_logs = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        gv = OtherLifeGameView(interaction.user, self.guild_id, user_state=u_state, idle_logs=idle_logs)
        await core.safe_edit_response(interaction, embed=gv.build_embed(), view=gv)


# ==========================================
# 5. 메인 인터랙티브 플레이 View
# ==========================================
class OtherLifeGameView(core.SafeView):
    def __init__(
        self,
        user: Optional[discord.abc.User] = None,
        guild_id: int = 0,
        user_state: Optional[Dict[str, Any]] = None,
        idle_logs: Optional[List[str]] = None,
        force_setup: bool = False,
    ):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        if user_state is None:
            uid = user.id if user else 0
            uname = user.display_name if user else "여행자"
            u_state, _, logs = other_life_core.get_other_life_state(self.guild_id, uid, uname)
            self.user_state = u_state
            self.idle_logs = idle_logs if idle_logs is not None else logs
        else:
            self.user_state = user_state
            self.idle_logs = idle_logs or []

        self.selected_origin = "random"
        self.selected_scale = str(self.user_state.get("preferred_scale") or other_life_core.DEFAULT_TIME_SCALE)
        self.status_msg = ""

        active = self.user_state.get("active_life")
        if force_setup or not isinstance(active, dict):
            self.mode = "setup"
        else:
            self.mode = "play"
        self._rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 인생 이야기는 **{self.user.display_name}**님이 진행 중입니다. `/타인의인생 플레이`로 본인만의 인생을 시작해 보세요!",
                ephemeral=True,
            )
            return False
        return True

    def _rebuild(self):
        self.clear_items()
        u = self.user_state
        unlocked_cnt = len([k for k in (u.get("unlocked_endings") or {}) if k in other_life_core.ENDINGS])
        total_endings = len(other_life_core.ENDINGS)
        active = u.get("active_life")

        # ── Setup Mode (새 인생 준비 화면) ──
        if self.mode == "setup" or not isinstance(active, dict):
            self.add_item(OtherLifeOriginSelect(self, self.selected_origin))
            self.add_item(OtherLifeScaleSelect(self, self.selected_scale, row=1))

            btn_start = discord.ui.Button(
                label="🌱 이 설정으로 인생 시작!",
                style=discord.ButtonStyle.success,
                row=2,
                custom_id="norosi:OtherLifeGameView:start_life",
            )
            btn_start.callback = self._on_start_life
            self.add_item(btn_start)

            if isinstance(active, dict) and not active.get("finished"):
                btn_resume = discord.ui.Button(
                    label="📖 진행 중 인생 이어하기",
                    style=discord.ButtonStyle.primary,
                    row=2,
                    custom_id="norosi:OtherLifeGameView:resume_life",
                )
                btn_resume.callback = self._on_resume_life
                self.add_item(btn_resume)

            btn_col = discord.ui.Button(
                label=f"📜 엔딩 도감 ({unlocked_cnt}/{total_endings})",
                style=discord.ButtonStyle.secondary,
                row=2,
                custom_id="norosi:OtherLifeGameView:open_collection",
            )
            btn_col.callback = self._on_open_collection
            self.add_item(btn_col)

            btn_rank = discord.ui.Button(
                label="🏆 서버 랭킹",
                style=discord.ButtonStyle.secondary,
                row=2,
                custom_id="norosi:OtherLifeGameView:open_ranking",
            )
            btn_rank.callback = self._on_open_ranking
            self.add_item(btn_rank)
            return

        # ── Finished Mode (엔딩 도달 화면) ──
        if active.get("finished"):
            btn_quick = discord.ui.Button(
                label="🌱 새 타인의 인생 시작",
                style=discord.ButtonStyle.success,
                row=0,
                custom_id="norosi:OtherLifeGameView:quick_new_life",
            )
            btn_quick.callback = self._on_quick_new_life
            self.add_item(btn_quick)

            btn_setup = discord.ui.Button(
                label="🧬 출신·배율 고르기",
                style=discord.ButtonStyle.primary,
                row=0,
                custom_id="norosi:OtherLifeGameView:goto_setup",
            )
            btn_setup.callback = self._on_goto_setup
            self.add_item(btn_setup)

            btn_col = discord.ui.Button(
                label=f"📜 엔딩 도감 ({unlocked_cnt}/{total_endings})",
                style=discord.ButtonStyle.secondary,
                row=0,
                custom_id="norosi:OtherLifeGameView:open_collection",
            )
            btn_col.callback = self._on_open_collection
            self.add_item(btn_col)

            btn_rank = discord.ui.Button(
                label="🏆 서버 랭킹",
                style=discord.ButtonStyle.secondary,
                row=0,
                custom_id="norosi:OtherLifeGameView:open_ranking",
            )
            btn_rank.callback = self._on_open_ranking
            self.add_item(btn_rank)

            self.add_item(OtherLifeScaleSelect(self, str(u.get("preferred_scale") or self.selected_scale), row=1))
            return

        # ── Active Play Mode (18개 분기점 플레이) ──
        node = other_life_core.build_current_node(active)
        choices = node["choices"]
        num_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"]
        split_at = 3 if len(choices) > 4 else 4

        for idx, ch in enumerate(choices):
            row = 0 if idx < split_at else 1
            raw_lbl = str(ch["label"]).strip()
            short_lbl = f"{num_emojis[idx]} {raw_lbl}"
            if len(short_lbl) > 38:
                short_lbl = short_lbl[:37] + "…"
            btn = discord.ui.Button(
                label=short_lbl,
                style=discord.ButtonStyle.primary if idx == 0 else discord.ButtonStyle.secondary,
                row=row,
                custom_id=f"norosi:OtherLifeGameView:choice:{ch['id']}",
            )
            btn.callback = self._make_choice_cb(ch["id"])
            self.add_item(btn)

        # Row 2: Utility actions (5 buttons max)
        cur_age = int(active.get("age", 6) or 6)
        ceiling = other_life_core._stage_age_ceiling(int(active.get("beat", 1) or 1), cur_age)
        quiet_disabled = (int(active.get("quiet_in_stage", 0) or 0) >= 2) or (cur_age >= ceiling) or (cur_age >= 95)

        btn_quiet = discord.ui.Button(
            label="⏳ 1년 조용히",
            style=discord.ButtonStyle.secondary,
            disabled=quiet_disabled,
            row=2,
            custom_id="norosi:OtherLifeGameView:quiet_year",
        )
        btn_quiet.callback = self._on_quiet_year
        self.add_item(btn_quiet)

        btn_tick = discord.ui.Button(
            label="🔄 세월 확인",
            style=discord.ButtonStyle.secondary,
            row=2,
            custom_id="norosi:OtherLifeGameView:refresh_time",
        )
        btn_tick.callback = self._on_refresh_time
        self.add_item(btn_tick)

        btn_col = discord.ui.Button(
            label=f"📜 도감 ({unlocked_cnt}/{total_endings})",
            style=discord.ButtonStyle.secondary,
            row=2,
            custom_id="norosi:OtherLifeGameView:open_collection",
        )
        btn_col.callback = self._on_open_collection
        self.add_item(btn_col)

        btn_rank = discord.ui.Button(
            label="🏆 랭킹",
            style=discord.ButtonStyle.secondary,
            row=2,
            custom_id="norosi:OtherLifeGameView:open_ranking",
        )
        btn_rank.callback = self._on_open_ranking
        self.add_item(btn_rank)

        btn_reset = discord.ui.Button(
            label="🔁 새 인생",
            style=discord.ButtonStyle.danger,
            row=2,
            custom_id="norosi:OtherLifeGameView:request_reset",
        )
        btn_reset.callback = self._on_request_reset
        self.add_item(btn_reset)

        # Row 3: Live Time Scale Selector
        self.add_item(
            OtherLifeScaleSelect(
                self,
                str(active.get("time_scale") or self.selected_scale),
                row=3,
            )
        )

    def _make_choice_cb(self, choice_id: str):
        async def _cb(interaction: discord.Interaction):
            await core.safe_defer(interaction)
            ok, msg, updated_u, _ = await asyncio.to_thread(
                other_life_core.apply_life_choice,
                self.guild_id,
                interaction.user.id,
                choice_id,
                interaction.user.display_name,
            )
            self.user_state = updated_u
            self.idle_logs = []
            self.status_msg = msg
            self._rebuild()
            await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
            if not ok:
                await interaction.followup.send(msg, ephemeral=True)
        return _cb

    def build_embed(self) -> discord.Embed:
        u = self.user_state
        uname = self.user.display_name if self.user else u.get("user_name", "플레이어")
        unlocked_cnt = len([k for k in (u.get("unlocked_endings") or {}) if k in other_life_core.ENDINGS])
        total_endings = len(other_life_core.ENDINGS)
        active = u.get("active_life")

        # ── Setup Embed ──
        if self.mode == "setup" or not isinstance(active, dict):
            scale_meta = other_life_core.TIME_SCALES.get(
                self.selected_scale,
                other_life_core.TIME_SCALES[other_life_core.DEFAULT_TIME_SCALE],
            )
            if self.selected_origin == "random":
                origin_preview = "🎲 **무작위 출신** *(바닷가 보육원·시장통 국수집·한옥 서재 등 6가지 운명 중 랜덤 시작)*"
            else:
                orig = other_life_core.ORIGINS[self.selected_origin]
                origin_preview = f"{orig['name']} — *{orig['hook']}*\n> 유품: `{orig['item']}`"

            status_banner = f"\n🔔 {self.status_msg}\n" if self.status_msg else ""
            embed = discord.Embed(
                title="📖 타인의 인생 — 새로운 일생의 첫 페이지",
                description=(
                    f"**{uname}**님, 이름도 배경도 낯선 어느 타인의 0세부터 노년까지를 대신 살아보세요.\n"
                    f"유년기의 작은 약속, 청소년기의 스승, 서른의 유혹이 노년과 **16종 엔딩**으로 인과를 맺습니다.\n"
                    f"{status_banner}\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🧬 **선택된 출신 배경**\n{origin_preview}\n\n"
                    f"⏱️ **선택된 시간 배율:** **{scale_meta['name']}**\n"
                    f"> {scale_meta['desc']}\n\n"
                    f"📚 **내 수집 기록:** 해금 엔딩 **`{unlocked_cnt}/{total_endings}종`** · "
                    f"완결 생애 `{u.get('lives_completed', 0)}회` · 최고 `{u.get('best_score', 0):,}점`\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "👇 아래 드롭다운으로 출신과 시간 배율을 고른 뒤 **`🌱 이 설정으로 인생 시작!`**을 눌러주세요!"
                ),
                color=0x38BDF8,
                timestamp=datetime.datetime.now(core.KST),
            )
            embed.set_footer(text="하루 3회 완결 💎 보상 (초회 엔딩 해금 시 +120💎 보너스!) · /타인의인생 도감")
            return embed

        # ── Finished Ending Embed ──
        if active.get("finished"):
            eid = str(active.get("ending_id") or "quiet_miracle")
            emeta = other_life_core.ENDINGS.get(eid, other_life_core.ENDINGS["quiet_miracle"])
            c_meta = other_life_core.CAREER_META.get(str(active.get("career") or "none"), other_life_core.CAREER_META["none"])
            orig = other_life_core.ORIGINS.get(str(active.get("origin_id") or "orphanage"), other_life_core.ORIGINS["orphanage"])
            tail_chronicle = (active.get("chronicle") or [])[-6:]
            chronicle_txt = "\n".join(f"> {line}" for line in tail_chronicle) if tail_chronicle else "> (기록 없음)"

            reward_line = active.get("reward_note") or "도감 등록 완료"
            partner_line = f" · 동반자 `{active['partner_name']}`" if active.get("partner_name") else ""

            embed = discord.Embed(
                title=f"🎬 [인생 완결] {active.get('name')} ({active.get('age')}세) — {emeta['emoji']} {emeta['title']}"[:250],
                description=(
                    f"**등급:** `[{emeta['rarity']}]` · **주제:** *{emeta['summary']}*\n"
                    f"**배경:** {orig['name']} · **길:** {c_meta['emoji']} {c_meta['name']}{partner_line}\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📜 **생애의 마침표**\n{active.get('ending_epilogue', '')}\n\n"
                    f"📊 **최종 삶의 결** *(인생 점수 **`{active.get('score', 0):,}점`**)*\n"
                    f"{_format_stats_block(active.get('stats') or {})}\n\n"
                    f"💎 **보상 & 도감:** {reward_line} · 해금 **`{unlocked_cnt}/{total_endings}종`**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🕰️ **인생 주요 발자취 (최근 기록)**\n{chronicle_txt}"
                )[:4000],
                color=emeta["color"],
                timestamp=datetime.datetime.now(core.KST),
            )
            embed.set_footer(text=f"{uname}님의 타인의 인생 기록 · '새 타인의 인생 시작'으로 다른 운명을 체험해 보세요!")
            return embed

        # ── Active Play Embed ──
        cur_age = int(active.get("age", 6) or 6)
        cur_beat = int(active.get("beat", 1) or 1)
        stage_id, stage_label, stage_desc = other_life_core.get_stage_for_age(cur_age)
        node = other_life_core.build_current_node(active)
        orig = other_life_core.ORIGINS.get(str(active.get("origin_id") or "orphanage"), other_life_core.ORIGINS["orphanage"])
        c_meta = other_life_core.CAREER_META.get(str(active.get("career") or "none"), other_life_core.CAREER_META["none"])
        scale_id = str(active.get("time_scale") or other_life_core.DEFAULT_TIME_SCALE)
        scale_meta = other_life_core.TIME_SCALES.get(scale_id, other_life_core.TIME_SCALES[other_life_core.DEFAULT_TIME_SCALE])

        rel_bits = [f"고향 `{active.get('hometown', '어느 골목')}`", f"소꿉친구 `{active.get('companion_name', '지우')}`", f"스승 `{active.get('mentor_name', '백 선생')}`"]
        if active.get("partner_name"):
            rel_bits.append(f"💍 동반자 `{active['partner_name']}`")

        chron_lines = (active.get("chronicle") or [])[-3:]
        chron_block = "\n".join(f"> {c}" for c in chron_lines)

        num_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"]
        choice_lines = []
        for idx, ch in enumerate(node["choices"]):
            choice_lines.append(f"{num_emojis[idx]} **{ch['label']}**\n> `{ch['hint']}`")

        banner_parts = []
        if self.idle_logs:
            banner_parts.append(f"⏳ **방금 흐른 세월 ({len(self.idle_logs)}년):** {self.idle_logs[-1]}")
        if self.status_msg:
            banner_parts.append(f"💬 {self.status_msg}")
        banner_txt = ("\n".join(banner_parts) + "\n\n") if banner_parts else ""

        stage_colors = {
            "childhood": 0x4ADE80,
            "teen": 0x38BDF8,
            "youth": 0xF97316,
            "midlife": 0xA855F7,
            "elder": 0xEAB308,
        }

        embed = discord.Embed(
            title=f"{node['title']}"[:250],
            description=(
                f"{banner_txt}"
                f"**👤 {active.get('name')}** (`{cur_age}세` · {stage_label} · **Chapter `{cur_beat}/18`**)\n"
                f"🧬 {orig['name']} · {c_meta['emoji']} {c_meta['name']}\n"
                f"⏱️ {scale_meta['name']} · {_next_tick_text(active)}\n"
                f"🤝 {' · '.join(rel_bits)}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{_format_stats_block(active.get('stats') or {})}\n\n"
                f"🕰️ **최근 연대기**\n{chron_block}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📖 **지금 마주한 순간**\n{node['body']}\n\n"
                f"🎯 **당신의 선택**\n" + "\n".join(choice_lines)
            )[:4000],
            color=stage_colors.get(stage_id, 0x38BDF8),
            timestamp=datetime.datetime.now(core.KST),
        )
        quiet_rem = max(0, 2 - int(active.get("quiet_in_stage", 0) or 0))
        embed.set_footer(
            text=f"{uname}님의 타인의 인생 · 현재 시기 조용한 1년 {quiet_rem}회 남음 · 아래 드롭다운으로 배율 즉시 변경 가능"
        )
        return embed

    # ── Button Callbacks ──
    async def _on_start_life(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        orig_arg = None if self.selected_origin == "random" else self.selected_origin
        ok, msg, updated_u = await asyncio.to_thread(
            other_life_core.start_new_life,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
            self.selected_scale,
            orig_arg,
        )
        self.user_state = updated_u
        self.idle_logs = []
        self.mode = "play"
        self.status_msg = msg
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_resume_life(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        u_state, _, logs = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        self.user_state = u_state
        self.idle_logs = logs
        self.mode = "play"
        self.status_msg = "📖 진행 중이던 인생을 다시 펼쳤습니다."
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_quick_new_life(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        ok, msg, updated_u = await asyncio.to_thread(
            other_life_core.start_new_life,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        self.user_state = updated_u
        self.idle_logs = []
        self.mode = "play"
        self.status_msg = msg
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_goto_setup(self, interaction: discord.Interaction):
        self.mode = "setup"
        self.status_msg = "🧬 새로운 출신과 시간 배율을 선택해 주세요."
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_quiet_year(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        ok, msg, updated_u = await asyncio.to_thread(
            other_life_core.spend_quiet_year,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        self.user_state = updated_u
        self.idle_logs = []
        self.status_msg = msg
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    async def _on_refresh_time(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        u_state, yrs, logs = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        self.user_state = u_state
        self.idle_logs = logs
        self.status_msg = (
            f"⏳ {yrs}년의 일상이 자연스럽게 흘러 일기장에 기록되었습니다!"
            if yrs > 0
            else "🔄 현재 시점까지 세월 상태를 확인했습니다."
        )
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_open_collection(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        u_state, _, _ = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        cv = OtherLifeCollectionView(interaction.user, self.guild_id, user_state=u_state)
        await core.safe_edit_response(interaction, embed=cv.build_embed(), view=cv)

    async def _on_open_ranking(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        rv = OtherLifeRankingView(interaction.user, self.guild_id)
        await core.safe_edit_response(interaction, embed=rv.build_embed(), view=rv)

    async def _on_request_reset(self, interaction: discord.Interaction):
        active = self.user_state.get("active_life") or {}
        if int(active.get("beat", 1) or 1) <= 1 and not active.get("chronicle"):
            self.mode = "setup"
            self._rebuild()
            await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
            return

        cv = OtherLifeConfirmResetView(self, interaction.user, self.guild_id)
        embed = discord.Embed(
            title="🔁 진행 중인 인생을 새로 시작할까요?",
            description=(
                f"현재 **{active.get('name')} ({active.get('age')}세 · {active.get('beat')}/18장)**의 이야기가 진행 중입니다.\n"
                "지금 새로 시작하면 현재 생애는 완결 기록(도감)에 저장되지 않고 덮어써집니다.\n\n"
                "어떻게 하시겠어요?"
            ),
            color=0xEF4444,
        )
        await core.safe_edit_response(interaction, embed=embed, view=cv)


# ==========================================
# 6. Cog 등록 (/타인의인생 그룹 + !타인의인생 단축어)
# ==========================================
class OtherLifeCog(
    commands.GroupCog,
    name="타인의인생",
    description="📖 0세부터 노년까지 타인의 일생을 살아가는 스토리 시뮬레이션 (시간 배율 · 16종 멀티 엔딩)",
):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="플레이", description="📖 타인의 인생을 시작하거나 진행 중이던 생애를 이어갑니다.")
    @app_commands.describe(
        출신="새 인생 시작 시 고를 출신 환경 (미선택 시 이어하기/랜덤 선택창 표시)",
        시간배율="인생 세월이 흐르는 시간 배율 (표준 45초=1년 추천 / 쾌속 / 슬로우 / 턴제)",
    )
    @app_commands.choices(
        출신=[
            app_commands.Choice(name="🎲 랜덤 출신 (운명에 맡기기)", value="random"),
            app_commands.Choice(name="🌊 바닷가 보육원 '해송원'", value="orphanage"),
            app_commands.Choice(name="🍜 시장통 24시 멸치국수집", value="noodle_shop"),
            app_commands.Choice(name="📚 오래된 한옥 서재 집안", value="scholar_home"),
            app_commands.Choice(name="🏚️ 몰락한 옛 저택의 막내", value="fallen_house"),
            app_commands.Choice(name="🕰️ 골목 끝 시계·목공방", value="artisan_shop"),
            app_commands.Choice(name="⛰️ 안개 낀 산골 약초방", value="mountain_clinic"),
        ],
        시간배율=[
            app_commands.Choice(name="⚖️ 표준 세월 배율 (45초=1년 · 추천)", value="balanced"),
            app_commands.Choice(name="⚡ 쾌속 세월 배율 (15초=1년)", value="brisk"),
            app_commands.Choice(name="🕰️ 슬로우 라이프 (3분=1년)", value="slow"),
            app_commands.Choice(name="📖 턴제 정주행 (대기 없음)", value="turn"),
        ],
    )
    async def play_cmd(
        self,
        interaction: discord.Interaction,
        출신: Optional[app_commands.Choice[str]] = None,
        시간배율: Optional[app_commands.Choice[str]] = None,
    ):
        await core.safe_defer(interaction)
        gid = interaction.guild_id or 0
        uid = interaction.user.id
        uname = interaction.user.display_name

        u_state, yrs, idle_logs = await asyncio.to_thread(other_life_core.get_other_life_state, gid, uid, uname)
        scale_val = 시간배율.value if 시간배율 else None
        origin_val = 출신.value if 출신 else None

        active = u_state.get("active_life")
        has_unfinished = isinstance(active, dict) and not active.get("finished")

        status_msg = ""
        if scale_val and (has_unfinished or not origin_val):
            _, s_msg, u_state = await asyncio.to_thread(
                other_life_core.set_life_time_scale, gid, uid, scale_val, uname
            )
            status_msg = s_msg

        if origin_val and not has_unfinished:
            orig_arg = None if origin_val == "random" else origin_val
            _, start_msg, u_state = await asyncio.to_thread(
                other_life_core.start_new_life,
                gid,
                uid,
                uname,
                scale_val or u_state.get("preferred_scale"),
                orig_arg,
            )
            idle_logs = []
            status_msg = start_msg

        view = OtherLifeGameView(interaction.user, gid, user_state=u_state, idle_logs=idle_logs)
        if scale_val:
            view.selected_scale = scale_val
        if origin_val and has_unfinished:
            view.selected_origin = origin_val
            status_msg = "ℹ️ 이미 진행 중인 인생을 불러왔습니다. 새로 시작하려면 `🔁 새 인생` 버튼을 눌러주세요."
        if status_msg:
            view.status_msg = status_msg
        view._rebuild()

        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="도감", description="📜 해금한 16종 멀티 엔딩 도감과 내가 살아온 인생 전기 아카이브를 봅니다.")
    async def collection_cmd(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        gid = interaction.guild_id or 0
        u_state, _, _ = await asyncio.to_thread(
            other_life_core.get_other_life_state, gid, interaction.user.id, interaction.user.display_name
        )
        view = OtherLifeCollectionView(interaction.user, gid, user_state=u_state)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="랭킹", description="🏆 서버 유저들의 타인의 인생 엔딩 수집 · 최고 점수 랭킹을 봅니다.")
    async def ranking_cmd(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        gid = interaction.guild_id or 0
        view = OtherLifeRankingView(interaction.user, gid)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg


class OtherLifeStandaloneCog(commands.Cog):
    """!타인의인생 · !인생게임 · !타인 접두사 단축어 Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="타인의인생", aliases=["인생게임", "타인"])
    async def prefix_other_life(self, ctx: commands.Context):
        gid = ctx.guild.id if ctx.guild else 0
        u_state, _, idle_logs = await asyncio.to_thread(
            other_life_core.get_other_life_state, gid, ctx.author.id, ctx.author.display_name
        )
        view = OtherLifeGameView(ctx.author, gid, user_state=u_state, idle_logs=idle_logs)
        msg = await ctx.send(embed=view.build_embed(), view=view)
        view.message = msg


async def setup(bot: commands.Bot):
    await bot.add_cog(OtherLifeCog(bot))
    await bot.add_cog(OtherLifeStandaloneCog(bot))
