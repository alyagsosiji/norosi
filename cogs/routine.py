"""
cogs/routine.py — 통합 일일 루틴 · 주간 미션 · 크리스탈⇄골드 환전소 ·
파트너 농장 시너지 · 통합 수집품 쇼케이스 · 즉석 미니 대전(주사위/초성퀴즈) UI Cog
"""

from __future__ import annotations

import asyncio
import datetime
import random
from typing import Any, Dict, Optional, Tuple

import discord
from discord.ext import commands

import core
import economy_core
import fishing_core
import life_core
import routine_core


def _progress_bar(done: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "⬜" * width + " 0%"
    ratio = max(0.0, min(1.0, done / total))
    filled = int(round(ratio * width))
    pct = int(round(ratio * 100))
    return ("🟩" * filled) + ("⬜" * (width - filled)) + f" **{pct}%**"


# ==========================================
# 1. ☀️ 오늘의 일일 루틴 통합 허브
# ==========================================
class DailyRoutineHubView(core.SafeView):
    def __init__(
        self,
        bot: Optional[commands.Bot] = None,
        user: Optional[discord.abc.User] = None,
        guild_id: int = 0,
        status: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(timeout=300)
        self.bot = bot
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.status_msg = ""
        self.status = status or routine_core.get_daily_routine_status(
            self.guild_id,
            user.id if user else 0,
            user.display_name if user else "유저",
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 일일 루틴 보드만 조작할 수 있습니다.", ephemeral=True)
            return False
        if not self.user:
            self.user = interaction.user
        return True

    async def reload(self):
        uid = self.user.id if self.user else 0
        uname = self.user.display_name if self.user else "유저"
        self.status = await asyncio.to_thread(routine_core.get_daily_routine_status, self.guild_id, uid, uname)

    def build_embed(self) -> discord.Embed:
        st = self.status
        done_cnt = st["completed_cnt"]
        tot_cnt = st["total_cnt"]
        bar = _progress_bar(done_cnt, tot_cnt, 10)

        lines = []
        for it in st["items"]:
            icon = "✅" if it["done"] else ("🎁" if it.get("claimable") else "⬜")
            lines.append(f"{icon} {it['emoji']} **{it['name']}**\n└ {it['detail']}")

        if st["bonus_claimed"]:
            bonus_line = f"🏆 **일일 완주 보너스 (`{routine_core.DAILY_ROUTINE_MIN_COMPLETE}개+`):** ✅ 오늘 수령 완료!"
        elif st["bonus_eligible"]:
            bonus_line = (
                f"🎁 **일일 완주 보너스 수령 가능!** "
                f"(`+{routine_core.DAILY_ROUTINE_BONUS_CRYSTALS}💎` · `+{routine_core.DAILY_ROUTINE_BONUS_GOLD}🪙` — 아래 일괄 수령 클릭!)"
            )
        else:
            rem = max(0, routine_core.DAILY_ROUTINE_MIN_COMPLETE - done_cnt)
            bonus_line = (
                f"⏳ **일일 완주 보너스:** `{rem}개` 더 완료 시 "
                f"`+{routine_core.DAILY_ROUTINE_BONUS_CRYSTALS}💎` + `+{routine_core.DAILY_ROUTINE_BONUS_GOLD}🪙`"
            )

        banner = f"\n> {self.status_msg}\n" if self.status_msg else ""

        embed = discord.Embed(
            title=f"☀️ {st['user_name']}님의 오늘의 일일 루틴 ({st['today']})",
            description=(
                f"• **보유 재화:** 💎 **`{st['crystals']:,}💎`**  ·  🪙 **`{st['gold']:,}🪙`**\n"
                f"• **오늘 진행률:** `{done_cnt}/{tot_cnt}`  {bar}\n"
                f"• {bonus_line}"
                f"{banner}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                + "\n".join(lines)
            )[:4096],
            color=0xF59E0B if done_cnt < routine_core.DAILY_ROUTINE_MIN_COMPLETE else 0x10B981,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="🎁 [가능 보상 일괄 수령]으로 낚시 의뢰·농장·공동농장·완주 보너스를 한 번에 처리하세요!")
        return embed

    @discord.ui.button(label="🎁 일괄 수령", style=discord.ButtonStyle.success, row=0)
    async def btn_bulk_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, logs = await asyncio.to_thread(
            routine_core.bulk_claim_daily_rewards,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        self.status_msg = " / ".join(logs[:2]) if ok else logs[0]
        await self.reload()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        await interaction.followup.send("\n".join(logs), ephemeral=True)

    @discord.ui.button(label="📅 출석체크", style=discord.ButtonStyle.primary, row=0)
    async def btn_attend(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        from cogs import dday
        embed, file, view = await dday.execute_and_build_attendance_response(interaction, self.bot or interaction.client)
        await self.reload()
        try:
            if interaction.message:
                await interaction.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass
        if file:
            await interaction.followup.send(embed=embed, file=file, view=view, wait=True)
        else:
            await interaction.followup.send(embed=embed, view=view, wait=True)

    @discord.ui.button(label="🌾 개인 농장", style=discord.ButtonStyle.secondary, row=0)
    async def btn_farm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        from cogs import life
        ov = await asyncio.to_thread(life_core.get_life_overview, self.guild_id, interaction.user.id, interaction.user.display_name)
        v = life.FarmView(interaction.user, self.guild_id, overview=ov)
        msg = await interaction.followup.send(embed=v.build_embed(), view=v, wait=True)
        v.message = msg

    @discord.ui.button(label="🎣 낚시 의뢰", style=discord.ButtonStyle.secondary, row=1)
    async def btn_quest(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        from cogs import fishing
        summary = await asyncio.to_thread(fishing_core.get_user_fishing_summary, self.guild_id, interaction.user.id, interaction.user.display_name)
        v = fishing.FishingQuestView(interaction.user, self.guild_id, summary=summary)
        await interaction.followup.send(embed=v.build_embed(), view=v, wait=True)

    @discord.ui.button(label="🎯 주간 미션", style=discord.ButtonStyle.primary, row=1)
    async def btn_weekly(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        v = WeeklyMissionView(interaction.user, self.guild_id)
        await interaction.followup.send(embed=v.build_embed(), view=v, wait=True)

    @discord.ui.button(label="💱 환전소", style=discord.ButtonStyle.primary, row=1)
    async def btn_exchange(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        v = CurrencyExchangeView(interaction.user, self.guild_id)
        await interaction.followup.send(embed=v.build_embed(), view=v, wait=True)

    @discord.ui.button(label="💑 파트너 물주기", style=discord.ButtonStyle.secondary, row=2)
    async def btn_partner_water(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(
            routine_core.water_partner_farm, self.guild_id, interaction.user.id, interaction.user.display_name
        )
        self.status_msg = "💑 파트너 농장 물주기 완료!" if ok else msg
        await self.reload()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        await interaction.followup.send(msg, ephemeral=not ok)

    @discord.ui.button(label="🏆 쇼케이스", style=discord.ButtonStyle.secondary, row=2)
    async def btn_showcase(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        v = ShowcaseView(interaction.user, self.guild_id)
        await interaction.followup.send(embed=v.build_embed(), view=v, wait=True)

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=2)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.status_msg = "🔄 일일 루틴 현황을 최신으로 갱신했습니다."
        await self.reload()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


# ==========================================
# 2. 💱 크리스탈 ⇄ 낚시 골드 환전소
# ==========================================
class CurrencyExchangeView(core.SafeView):
    def __init__(self, user: Optional[discord.abc.User] = None, guild_id: int = 0):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.status_msg = ""
        self.state = routine_core.get_exchange_state(
            self.guild_id, user.id if user else 0, user.display_name if user else "유저"
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 환전소 창만 조작할 수 있습니다.", ephemeral=True)
            return False
        if not self.user:
            self.user = interaction.user
        return True

    async def reload(self):
        uid = self.user.id if self.user else 0
        uname = self.user.display_name if self.user else "유저"
        self.state = await asyncio.to_thread(routine_core.get_exchange_state, self.guild_id, uid, uname)

    def build_embed(self) -> discord.Embed:
        st = self.state
        banner = f"\n> {self.status_msg}\n" if self.status_msg else ""
        embed = discord.Embed(
            title="💱 크리스탈 ⇄ 낚시 골드 일일 환전소",
            description=(
                f"• **현재 보유:** 💎 **`{st['crystals']:,}💎`**  ·  🪙 **`{st['gold']:,}🪙`**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"1️⃣ **골드 ➔ 크리스탈:** `{routine_core.EXCHANGE_GOLD_TO_CRYSTAL_COST:,}🪙` ➔ **`+{routine_core.EXCHANGE_GOLD_TO_CRYSTAL_GAIN:,}💎`**\n"
                f"   └ 오늘 사용: `{st['g2c_used']} / {st['limit']}회`\n"
                f"2️⃣ **크리스탈 ➔ 골드:** `{routine_core.EXCHANGE_CRYSTAL_TO_GOLD_COST:,}💎` ➔ **`+{routine_core.EXCHANGE_CRYSTAL_TO_GOLD_GAIN:,}🪙`**\n"
                f"   └ 오늘 사용: `{st['c2g_used']} / {st['limit']}회`"
                f"{banner}"
            ),
            color=0x38BDF8,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text=f"기준일: {st['today']} (KST 자정 초기화)  ·  경제 밸런스를 위해 방향별 일일 {st['limit']}회 제한")
        return embed

    @discord.ui.button(label="🪙 500골드 ➔ 💎 100", style=discord.ButtonStyle.success, row=0)
    async def btn_g2c(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(
            routine_core.exchange_currency, self.guild_id, interaction.user.id, "gold_to_crystal", interaction.user.display_name
        )
        self.status_msg = msg
        await self.reload()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="💎 100 ➔ 🪙 450골드", style=discord.ButtonStyle.primary, row=0)
    async def btn_c2g(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(
            routine_core.exchange_currency, self.guild_id, interaction.user.id, "crystal_to_gold", interaction.user.display_name
        )
        self.status_msg = msg
        await self.reload()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.status_msg = ""
        await self.reload()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


# ==========================================
# 3. 🎯 통합 주간 미션 뷰
# ==========================================
class WeeklyMissionView(core.SafeView):
    def __init__(self, user: Optional[discord.abc.User] = None, guild_id: int = 0):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.status_msg = ""
        self.state = routine_core.get_weekly_mission_status(
            self.guild_id, user.id if user else 0, user.display_name if user else "유저"
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 주간 미션 보드만 조작할 수 있습니다.", ephemeral=True)
            return False
        if not self.user:
            self.user = interaction.user
        return True

    async def reload(self):
        uid = self.user.id if self.user else 0
        uname = self.user.display_name if self.user else "유저"
        self.state = await asyncio.to_thread(routine_core.get_weekly_mission_status, self.guild_id, uid, uname)

    def build_embed(self) -> discord.Embed:
        st = self.state
        lines = []
        for m in st["missions"]:
            if m["claimed"]:
                badge = "✅ 수령 완료"
            elif m["claimable"]:
                badge = "🎁 **완료! 수령 가능**"
            else:
                badge = f"`{m['current']}/{m['target']}`"
            r_parts = []
            if m["crystals"]:
                r_parts.append(f"`+{m['crystals']:,}💎`")
            if m["gold"]:
                r_parts.append(f"`+{m['gold']:,}🪙`")
            lines.append(f"{m['emoji']} **{m['title']}** — {badge}\n└ 보상: {' · '.join(r_parts)}")

        banner = f"\n> {self.status_msg}\n" if self.status_msg else ""
        embed = discord.Embed(
            title=f"🎯 {st['user_name']}님의 통합 주간 미션 ({st['week_key']})",
            description=(
                f"• **보유 재화:** 💎 **`{st['crystals']:,}💎`**  ·  🪙 **`{st['gold']:,}🪙`**\n"
                f"• **달성 현황:** `{st['done_cnt']}/{len(st['missions'])}`  {_progress_bar(st['done_cnt'], len(st['missions']), 10)}"
                f"{banner}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                + "\n".join(lines)
            )[:4096],
            color=0x8B5CF6,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="매주 월요일 00:00 (KST) 자동 초기화  ·  완료 미션은 일괄 수령 버튼으로 즉시 획득!")
        return embed

    @discord.ui.button(label="🎁 완료 미션 일괄 수령", style=discord.ButtonStyle.success, row=0)
    async def btn_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(
            routine_core.claim_weekly_missions, self.guild_id, interaction.user.id, interaction.user.display_name
        )
        self.status_msg = "🎉 주간 미션 보상을 수령했습니다!" if ok else msg
        await self.reload()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        await interaction.followup.send(msg, ephemeral=not ok)

    @discord.ui.button(label="☀️ 일일 루틴으로", style=discord.ButtonStyle.primary, row=0)
    async def btn_daily(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        v = DailyRoutineHubView(interaction.client, interaction.user, self.guild_id)
        await interaction.followup.send(embed=v.build_embed(), view=v, wait=True)

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.status_msg = ""
        await self.reload()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


# ==========================================
# 4. 🏆 통합 수집품 쇼케이스 뷰
# ==========================================
class ShowcaseView(core.SafeView):
    def __init__(self, user: Optional[discord.abc.User] = None, guild_id: int = 0, tab: str = "summary"):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.tab = tab
        uid = user.id if user else 0
        uname = user.display_name if user else "유저"
        self.sc = routine_core.build_showcase_data(self.guild_id, uid, uname)
        self.ach = economy_core.evaluate_user_achievements(core.load_data(), self.guild_id, uid, uname)
        self._sync_tab_styles()

    def _sync_tab_styles(self):
        self.btn_summary.style = discord.ButtonStyle.primary if self.tab == "summary" else discord.ButtonStyle.secondary
        self.btn_sekai.style = discord.ButtonStyle.primary if self.tab == "sekai" else discord.ButtonStyle.secondary
        self.btn_hoyoverse.style = discord.ButtonStyle.primary if self.tab == "hoyoverse" else discord.ButtonStyle.secondary
        self.btn_life.style = discord.ButtonStyle.primary if self.tab == "life" else discord.ButtonStyle.secondary
        self.btn_badges.style = discord.ButtonStyle.primary if self.tab == "badges" else discord.ButtonStyle.secondary

    async def reload(self):
        uid = self.user.id if self.user else 0
        uname = self.user.display_name if self.user else "유저"

        def _load_all():
            sc = routine_core.build_showcase_data(self.guild_id, uid, uname)
            ach = economy_core.evaluate_user_achievements(core.load_data(), self.guild_id, uid, uname)
            return sc, ach

        self.sc, self.ach = await asyncio.to_thread(_load_all)

    def build_embed(self) -> discord.Embed:
        self._sync_tab_styles()
        sc = self.sc
        ach = self.ach
        embed = discord.Embed(
            title=f"🏆 {sc['user_name']}님의 통합 수집품 & 업적 쇼케이스",
            color=0xEC4899,
            timestamp=datetime.datetime.now(core.KST),
        )
        if self.user and hasattr(self.user, "display_avatar"):
            embed.set_thumbnail(url=self.user.display_avatar.url)

        if self.tab == "badges":
            unlocked = ach.get("unlocked") or []
            locked = ach.get("locked") or []
            pct = ach.get("completion_pct", 0.0)
            filled = min(10, max(0, int(round(pct / 10))))
            bar = "█" * filled + "░" * (10 - filled)
            u_lines = [
                f"• {b['emoji']} **{b['name']}** — *{b['desc']}*"
                for b in unlocked
            ] or ["*(아직 해금된 업적 뱃지가 없습니다 — 출석·뽑기·낚시로 첫 뱃지를 열어보세요!)*"]
            l_lines = [
                f"• 🔒 **{b['name']}** (`{b['current']:,}/{b['target']:,}`) — *{b['desc']}*"
                for b in locked[:8]
            ] or ["🎉 **모든 크로스 기능 업적 뱃지를 100% 달성했습니다!**"]
            embed.description = (
                f"🏅 **업적 달성도:** `{ach['unlocked_count']}/{ach['total_count']}` (`{pct}%`)  `[{bar}]`\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "**✨ 해금 완료 뱃지**\n" + "\n".join(u_lines) + "\n\n"
                "**🎯 도전 중인 업적**\n" + "\n".join(l_lines)
            )[:4096]
        elif self.tab == "sekai":
            deck_lines = [
                f"`{i}.` **{c.get('rarity_label', '★')} [{c.get('prefix', '-')}] {c.get('char_name', '-')}** "
                f"(`Lv.{c.get('level', 1)}` · `✦MR.{c.get('master_rank', 0)}` · `⚔️{core.get_card_power(c):,}`)"
                for i, c in enumerate(sc["sekai_deck"], 1)
            ] or ["*(편성된 5인 덱이 없습니다)*"]
            top_lines = [
                f"• **{c.get('rarity_label', '★')} [{c.get('prefix', '-')}] {c.get('char_name', '-')}** (`⚔️{core.get_card_power(c):,}`)"
                for c in sc["sekai_top3"]
            ] or ["*(보유 카드 없음)*"]
            embed.description = (
                f"💖 **대표 오시:** `{sc['oshi']}`  ·  📚 **보유 카드:** `{sc['sekai_total']:,}종`\n"
                f"⚔️ **5인 덱 종합력:** **`{sc['sekai_deck_power']:,}`**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "**🎴 편성된 5인 유닛 덱**\n" + "\n".join(deck_lines) + "\n\n"
                "**🌟 내 최강 카드 TOP 3**\n" + "\n".join(top_lines)
            )[:4096]
        elif self.tab == "hoyoverse":
            gi_lines = [
                f"`{i}.` `★{c.get('rank', 5)}` **{c.get('name', '-')}** (`Lv.{c.get('level', 1)}` · `{c.get('constellation', 0)}돌`)"
                for i, c in enumerate(sc["gi_party"], 1)
            ] or ["*(편성된 원신 파티 없음)*"]
            hsr_lines = [
                f"`{i}.` `★{c.get('rank', 5)}` **{c.get('name', '-')}** (`Lv.{c.get('level', 1)}` · `성혼 {c.get('eidolon', 0)}`)"
                for i, c in enumerate(sc["hsr_party"], 1)
            ] or ["*(편성된 스타레일 편대 없음)*"]
            embed.description = (
                f"🌠 **원신:** 총 `{sc['gi_total']}종` (★5 `{sc['gi_r5']}종`)\n" + "\n".join(gi_lines) + "\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🚄 **스타레일:** 총 `{sc['hsr_total']}종` (★5 `{sc['hsr_r5']}종`)\n" + "\n".join(hsr_lines)
            )[:4096]
        elif self.tab == "life":
            tank_lines = [
                f"`{i}.` {f.get('emoji', '🐟')} **★{f.get('rarity', 1)} {f.get('name', '어종')}** — `{float(f.get('length_cm', 0) or 0):.1f}cm`"
                for i, f in enumerate(sc["tank_top3"], 1)
            ] or ["*(전시 중인 대물이 없습니다)*"]
            embed.description = (
                f"🐠 **수족관 대표 대물 TOP 3** *(시간당 `+{sc['tank_hourly']:,}🪙`)*\n" + "\n".join(tank_lines) + "\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📖 **낚시 어류 도감:** `{sc['fish_dex']:,}종`\n"
                f"👶 **타인의 삶:** 해금 엔딩 `{sc['ol_endings']:,}종` · 최고 점수 **`{sc['ol_best']:,}점`**"
            )[:4096]
        else:
            badge_strip = ach.get("badge_strip") or "없음"
            embed.description = (
                f"💖 **대표 오시:** `{sc['oshi']}`  ·  💎 **`{sc['crystals']:,}💎`**  ·  🪙 **`{sc['gold']:,}🪙`**\n"
                f"🏅 **업적 뱃지 ({ach['unlocked_count']}/{ach['total_count']}):** {badge_strip}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• 🎤 **프로세카:** 보유 `{sc['sekai_total']:,}종` · 5인 덱 종합력 **`{sc['sekai_deck_power']:,}`**\n"
                f"• 🌠 **원신:** 보유 `{sc['gi_total']:,}종` (★5 `{sc['gi_r5']}종`) · 파티 `{len(sc['gi_party'])}/4`\n"
                f"• 🚄 **스타레일:** 보유 `{sc['hsr_total']:,}종` (★5 `{sc['hsr_r5']}종`) · 편대 `{len(sc['hsr_party'])}/4`\n"
                f"• 🐠 **낚시 & 수족관:** 도감 `{sc['fish_dex']:,}종` · 수족관 수익 `+{sc['tank_hourly']:,}🪙/h`\n"
                f"• 👶 **타인의 삶:** 엔딩 `{sc['ol_endings']:,}종` · 최고 점수 `{sc['ol_best']:,}점`"
            )[:4096]

        embed.set_footer(text="하단 탭 버튼으로 세부 쇼케이스 및 업적·뱃지 현황을 전환할 수 있습니다.")
        return embed

    @discord.ui.button(label="🌟 종합", style=discord.ButtonStyle.primary, row=0)
    async def btn_summary(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.tab = "summary"
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🎤 프세카 덱", style=discord.ButtonStyle.secondary, row=0)
    async def btn_sekai(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.tab = "sekai"
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🌠 원신·스타", style=discord.ButtonStyle.secondary, row=0)
    async def btn_hoyoverse(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.tab = "hoyoverse"
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🐠 수족관·인생", style=discord.ButtonStyle.secondary, row=1)
    async def btn_life(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.tab = "life"
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🏅 업적·뱃지", style=discord.ButtonStyle.secondary, row=1)
    async def btn_badges(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.tab = "badges"
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=1)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        await self.reload()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


# ==========================================
# 5. 🎲 채널 즉석 미니 대전 (주사위 대결 & 초성 퀴즈)
# ==========================================
class DiceDuelView(core.SafeView):
    def __init__(self, host: Optional[discord.abc.User] = None, bet: int = 0):
        super().__init__(timeout=120 if bet > 0 else 300)
        self.host = host
        self.bet = max(0, int(bet))
        self.rolls: Dict[int, Tuple[str, int, int]] = {}
        self.escrowed: Dict[int, Tuple[str, int]] = {}
        self.finished = False
        self.result_summary = ""
        self._lock = asyncio.Lock()

    def build_embed(self) -> discord.Embed:
        mode_txt = f"💎 `{self.bet:,}💎` 친선 내기" if self.bet > 0 else "🎉 무료 친선전"
        host_name = self.host.display_name if self.host else "방장"
        if self.rolls:
            if self.bet > 0 and not self.finished:
                lines = [
                    f"• **{name}** — 🎲 `[ 굴림 완료 · 정산 시 공개 ({self.bet:,}💎 예치됨) ]`"
                    for _, (name, _, _) in self.rolls.items()
                ]
            else:
                sorted_r = sorted(self.rolls.items(), key=lambda kv: -(kv[1][1] + kv[1][2]))
                lines = [
                    f"• **{name}** — 🎲 `{d1}` + `{d2}` = **`{d1 + d2}점`**"
                    for _, (name, d1, d2) in sorted_r
                ]
            body = "\n".join(lines)
        else:
            body = "*(아직 참가자가 없습니다! 아래 `[🎲 참가 & 주사위 굴리기]` 버튼을 눌러주세요)*"

        res_block = f"\n━━━━━━━━━━━━━━━━━━━━━━\n{self.result_summary}" if self.result_summary else ""
        embed = discord.Embed(
            title=f"🎲 하이로우 주사위 대결 ({mode_txt})",
            description=(
                f"• **개설자:** `{host_name}`  ·  **참가 인원:** `{len(self.rolls)}/6명`\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{body}{res_block}"
            )[:4096],
            color=0x22C55E if self.finished else 0x6366F1,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="2개 주사위(2d6) 합계가 가장 높은 사람이 승리합니다! (최대 6명 · 유료 내기는 정산 시 눈금 공개)")
        return embed

    async def on_timeout(self):
        async with self._lock:
            if not self.finished and self.escrowed:
                to_refund = dict(self.escrowed)
                self.escrowed.clear()
                self.finished = True
                self.result_summary = "⌛ 시간 만료로 대결이 종료되어 참가비 크리스탈이 전액 환불되었습니다."
                await asyncio.to_thread(routine_core.refund_dice_bets, to_refund)
        await super().on_timeout()

    @discord.ui.button(label="🎲 참가 & 주사위 굴리기", style=discord.ButtonStyle.success, row=0)
    async def btn_roll(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        async with self._lock:
            if self.finished:
                await interaction.followup.send("🏁 이미 종료된 대결입니다.", ephemeral=True)
                return
            if interaction.user.id in self.rolls:
                await interaction.followup.send("🎲 이미 주사위를 굴렸습니다! 다른 참가자를 기다려주세요.", ephemeral=True)
                return
            if len(self.rolls) >= 6:
                await interaction.followup.send("⚠️ 최대 6명까지 참가할 수 있습니다.", ephemeral=True)
                return

            if self.bet > 0:
                ok, err = await asyncio.to_thread(
                    routine_core.escrow_dice_bet,
                    interaction.user.id,
                    interaction.user.display_name,
                    self.bet,
                )
                if not ok:
                    await interaction.followup.send(err, ephemeral=True)
                    return
                self.escrowed[interaction.user.id] = (interaction.user.display_name, self.bet)

            d1, d2 = random.randint(1, 6), random.randint(1, 6)
            self.rolls[interaction.user.id] = (interaction.user.display_name, d1, d2)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🏁 결과 정산", style=discord.ButtonStyle.primary, row=0)
    async def btn_settle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.host and interaction.user.id != self.host.id:
            await core.safe_send_response(interaction, "❌ 결과 정산은 방장만 실행할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        async with self._lock:
            if self.finished:
                await interaction.followup.send("🏁 이미 정산 완료된 대결입니다.", ephemeral=True)
                return
            if len(self.rolls) < 2:
                await interaction.followup.send("⚠️ 최소 2명 이상 참가해야 정산할 수 있습니다!", ephemeral=True)
                return

            had_escrow = bool(self.escrowed)
            self.escrowed.clear()
            res = await asyncio.to_thread(routine_core.settle_dice_duel, self.rolls, self.bet, had_escrow)
            self.finished = True
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True

            winners = res.get("winners") or []
            win_names = ", ".join(f"**{w[1]}** (`{w[4]}점`)" for w in winners)
            if self.bet > 0 and res.get("pot", 0) > 0:
                self.result_summary = f"🏆 **승자:** {win_names}\n💰 총 상금 `{res['pot']:,}💎` 중 인당 **`+{res['payout_each']:,}💎`** 지급 완료!"
            else:
                self.result_summary = f"🏆 **승자:** {win_names} — 축하합니다!"
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="❌ 대결 취소", style=discord.ButtonStyle.danger, row=0)
    async def btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.host and interaction.user.id != self.host.id:
            await core.safe_send_response(interaction, "❌ 대결 취소는 방장만 할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        async with self._lock:
            if self.finished:
                await interaction.followup.send("🏁 이미 종료된 대결입니다.", ephemeral=True)
                return
            self.finished = True
            to_refund = dict(self.escrowed)
            self.escrowed.clear()
            if to_refund:
                await asyncio.to_thread(routine_core.refund_dice_bets, to_refund)
                self.result_summary = "🛑 방장이 대결을 취소하여 참가비 크리스탈이 전액 환불되었습니다."
            else:
                self.result_summary = "🛑 방장이 대결을 취소했습니다."
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


class ChosungAnswerModal(core.SafeModal, title="🔤 초성 퀴즈 정답 제출"):
    answer_input = discord.ui.TextInput(
        label="정답 단어를 입력하세요 (띄어쓰기 무관)",
        placeholder="예: 하츠네 미쿠",
        max_length=40,
        required=True,
    )

    def __init__(self, parent_view: "ChosungQuizView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        await self.parent_view.handle_guess(interaction, str(self.answer_input.value or "").strip())


class ChosungQuizView(core.SafeView):
    def __init__(self, host: Optional[discord.abc.User] = None):
        super().__init__(timeout=300)
        self.host = host
        self.used_answers: set = set()
        self.question = routine_core.pick_chosung_question(self.used_answers)
        self.used_answers.add(self.question["answer"])
        self.hint_level = 0
        self.solved = False
        self.last_log = ""
        self.round_num = 1
        self._lock = asyncio.Lock()

    def _is_host_or_admin(self, interaction: discord.Interaction) -> bool:
        if not self.host or interaction.user.id == self.host.id:
            return True
        if isinstance(interaction.user, discord.Member):
            perms = interaction.user.guild_permissions
            if perms.administrator or perms.manage_guild or perms.manage_messages:
                return True
        return False

    def build_embed(self) -> discord.Embed:
        q = self.question
        hints = [f"• **카테고리:** `{q['category']}` · **글자 수:** `{q['length']}글자`"]
        if self.hint_level >= 1:
            ans = q["answer"]
            hints.append(f"• **💡 힌트:** 첫 글자 **`{ans[0]}`**" + (f" · 마지막 글자 **`{ans[-1]}`**" if self.hint_level >= 2 and len(ans) > 1 else ""))

        log_block = f"\n━━━━━━━━━━━━━━━━━━━━━━\n{self.last_log}" if self.last_log else ""
        embed = discord.Embed(
            title=f"🔤 실시간 초성 퀴즈 — #{self.round_num}번 문제",
            description=(
                f"## `{q['chosung']}`\n"
                + "\n".join(hints)
                + f"{log_block}"
            ),
            color=0x10B981 if self.solved else 0x0EA5E9,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text=f"정답 시 +{routine_core.CHOSUNG_REWARD_CRYSTALS}💎 (일일 최대 {routine_core.CHOSUNG_DAILY_REWARD_CAP}회 보상) · 누구나 참여 가능!")
        return embed

    async def handle_guess(self, interaction: discord.Interaction, guess: str):
        if self.solved:
            await core.safe_send_response(interaction, "✅ 이미 정답이 나온 문제입니다! `[⏭️ 다음 문제]`를 눌러주세요.", ephemeral=True)
            return

        norm_guess = guess.replace(" ", "").lower()
        norm_ans = self.question["answer"].replace(" ", "").lower()
        if norm_guess != norm_ans:
            await core.safe_send_response(interaction, f"❌ **`{guess}`** — 오답입니다! 다시 도전해 보세요.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        async with self._lock:
            if self.solved:
                await interaction.followup.send("✅ 간발의 차로 이미 다른 분이 정답을 맞혔습니다!", ephemeral=True)
                return
            if guess.replace(" ", "").lower() != self.question["answer"].replace(" ", "").lower():
                await interaction.followup.send(f"❌ **`{guess}`** — 오답입니다!", ephemeral=True)
                return
            self.solved = True
            paid, amt, today_cnt = await asyncio.to_thread(
                routine_core.grant_chosung_reward, interaction.user.id, interaction.user.display_name
            )
            reward_txt = f" (`+{amt}💎`, 오늘 `{today_cnt}/{routine_core.CHOSUNG_DAILY_REWARD_CAP}회`)" if paid else " *(오늘 보상 한도 도달 — 명예 정답!)*"
            self.last_log = f"🎉 **{interaction.user.display_name}**님 정답! ➔ **`{self.question['answer']}`**{reward_txt}"
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="✏️ 정답 입력", style=discord.ButtonStyle.success, row=0)
    async def btn_answer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.solved:
            await core.safe_send_response(interaction, "✅ 이미 맞힌 문제입니다. `[⏭️ 다음 문제]`를 눌러주세요!", ephemeral=True)
            return
        await interaction.response.send_modal(ChosungAnswerModal(self))

    @discord.ui.button(label="💡 힌트 보기", style=discord.ButtonStyle.primary, row=0)
    async def btn_hint(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.hint_level = min(2, self.hint_level + 1)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="⏭️ 다음 문제", style=discord.ButtonStyle.secondary, row=0)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.solved and not self._is_host_or_admin(interaction):
            await core.safe_send_response(
                interaction,
                "❌ 아직 풀리지 않은 문제 넘기기는 **개설자** 또는 **서버 관리자**만 가능합니다!",
                ephemeral=True,
            )
            return
        await core.safe_defer(interaction)
        async with self._lock:
            prev_ans = self.question["answer"]
            was_solved = self.solved
            self.round_num += 1
            self.question = routine_core.pick_chosung_question(self.used_answers)
            self.used_answers.add(self.question["answer"])
            self.hint_level = 0
            self.solved = False
            self.last_log = "" if was_solved else f"ℹ️ 이전 문제 정답: **`{prev_ans}`**"
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🛑 퀴즈 종료", style=discord.ButtonStyle.danger, row=0)
    async def btn_stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_host_or_admin(interaction):
            await core.safe_send_response(
                interaction,
                "❌ 퀴즈 종료는 **개설자** 또는 **서버 관리자**만 실행할 수 있습니다!",
                ephemeral=True,
            )
            return
        await core.safe_defer(interaction)
        async with self._lock:
            self.solved = True
            self.last_log = f"🛑 초성 퀴즈가 종료되었습니다. *(마지막 정답: **`{self.question['answer']}`**)*"
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


class MiniBattleHubView(core.SafeView):
    def __init__(self, user: Optional[discord.abc.User] = None):
        super().__init__(timeout=300)
        self.user = user

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🎲 채널 즉석 미니 대전 허브",
            description=(
                "채널 멤버들과 버튼 클릭만으로 가볍게 즐기는 즉석 미니게임입니다!\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "• **🎲 하이로우 주사위 대결 (무료 / 50💎 내기):** 2~6명이 2d6 주사위를 굴려 최고 점수 승자 결정\n"
                "• **🔤 실시간 초성 퀴즈:** 프로세카·원신·스타레일·음식·상식 72종 초성 맞히기 (`+30💎`/문제)"
            ),
            color=0x6366F1,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="아래 버튼을 누르면 현재 채널에 바로 대결/퀴즈 방이 열립니다!")
        return embed

    @discord.ui.button(label="🎲 주사위 대결 (무료)", style=discord.ButtonStyle.success, row=0)
    async def btn_dice_free(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        v = DiceDuelView(interaction.user, bet=0)
        await interaction.followup.send(embed=v.build_embed(), view=v, wait=True)

    @discord.ui.button(label="💎 주사위 대결 (50💎)", style=discord.ButtonStyle.primary, row=0)
    async def btn_dice_bet(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        v = DiceDuelView(interaction.user, bet=50)
        await interaction.followup.send(embed=v.build_embed(), view=v, wait=True)

    @discord.ui.button(label="🔤 초성 퀴즈 시작", style=discord.ButtonStyle.primary, row=0)
    async def btn_chosung(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        v = ChosungQuizView(interaction.user)
        await interaction.followup.send(embed=v.build_embed(), view=v, wait=True)


# ==========================================
# Cog 등록 & 채팅창 빠른 실행 단축어
# ==========================================
class RoutineCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="일일루틴")
    async def prefix_daily_routine(self, ctx: commands.Context):
        gid = ctx.guild.id if ctx.guild else 0
        st = await asyncio.to_thread(
            routine_core.get_daily_routine_status, gid, ctx.author.id, ctx.author.display_name
        )
        view = DailyRoutineHubView(self.bot, ctx.author, gid, status=st)
        await ctx.send(embed=view.build_embed(), view=view)

    @commands.command(name="주간미션")
    async def prefix_weekly_missions(self, ctx: commands.Context):
        gid = ctx.guild.id if ctx.guild else 0
        view = WeeklyMissionView(ctx.author, gid)
        await ctx.send(embed=view.build_embed(), view=view)

    @commands.command(name="환전")
    async def prefix_currency_exchange(self, ctx: commands.Context):
        gid = ctx.guild.id if ctx.guild else 0
        view = CurrencyExchangeView(ctx.author, gid)
        await ctx.send(embed=view.build_embed(), view=view)

    @commands.command(name="쇼케이스")
    async def prefix_showcase(self, ctx: commands.Context, 유저: Optional[discord.Member] = None):
        target = 유저 or ctx.author
        gid = ctx.guild.id if ctx.guild else 0
        view = ShowcaseView(target, gid)
        await ctx.send(embed=view.build_embed(), view=view)

    @commands.command(name="초성퀴즈")
    async def prefix_mini_battle(self, ctx: commands.Context):
        view = MiniBattleHubView(ctx.author)
        await ctx.send(embed=view.build_embed(), view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(RoutineCog(bot))

