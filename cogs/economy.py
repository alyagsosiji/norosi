"""
cogs/economy.py - 통합 경제 & 커스터마이징 Cog (#2)
- 통합 프로필 카드 PNG (/프로필카드, /경제 프로필카드, !프로필카드)
- 칭호 상점 & 업적 배지 (/경제 칭호)
- 크리스탈 송금 & 세금 (/경제 송금)
- 주간 로또 복권 (/경제 복권)
- 통합 자산 랭킹 (/경제 랭킹)
"""

from __future__ import annotations

import asyncio
import datetime
import re
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

import core
import economy_core


async def _send_profile_card(
    target_send,
    target_user: Any,
    guild_id: int,
    *,
    is_interaction: bool = True,
):
    stats, png_buf = await economy_core.build_unified_profile_card_bytes(target_user, guild_id=guild_id)
    title_info = stats["title"]
    badges = stats.get("badges") or []
    badge_str = " ".join(f"{b['emoji']} `{b['name']}`" for b in badges) if badges else "*(아직 획득한 업적 배지가 없습니다)*"

    sek = stats["sekai"]
    gen = stats["genshin"]
    hsr = stats["hsr"]
    fl = stats["fishing_life"]

    art_txt = (
        f"`{gen['best_art']['name']}` ({gen['best_art']['grade']}, CV `{gen['best_art']['cv']}`)"
        if gen.get("best_art") else "미보유"
    )
    rel_txt = (
        f"`{hsr['best_relic']['name']}` ({hsr['best_relic']['grade']}, RV `{hsr['best_relic']['rv']}`)"
        if hsr.get("best_relic") else "미보유"
    )
    best_fish_txt = (
        f"`{fl['best_fish_name']}` (`{fl['best_fish_cm']:.1f}cm`)"
        if fl.get("best_fish_cm", 0) > 0 else "기록 없음"
    )

    embed = discord.Embed(
        title=f"{title_info['emoji']} {title_info['tag']} {stats['user_name']}님의 통합 프로필 카드",
        description=(
            f"• **💎 보유 크리스탈:** **`{stats['crystals']:,}💎`**  ·  **🪙 낚시/생활 골드:** **`{stats['fish_gold']:,}🪙`**\n"
            f"• **📅 출석 기록:** 누적 **`{stats['att_total']:,}일`** · 연속 **`{stats['att_streak']:,}일 🔥`** (최고 `{stats['att_max_streak']:,}일`)\n"
            f"• **🏅 보유 배지 ({len(badges)}/{len(economy_core.BADGE_CATALOG)}):** {badge_str}"
        ),
        color=discord.Color.from_rgb(*title_info.get("rgb", (56, 189, 248))),
        timestamp=datetime.datetime.now(core.KST),
    )
    embed.add_field(
        name="🎶 프로세카 / 🌠 원신 / 🚄 스타레일",
        value=(
            f"• **프로세카:** 오시 `{sek['oshi']}` · `{sek['unique_cards']}종` (★4 `{sek['star4_count']}장`) · 덱 `{sek['deck_power']:,}`\n"
            f"• **원신:** 기원 `{gen['total_pulls']:,}회` · ★5 `{gen['star5_count']}종` · 성유물 {art_txt}\n"
            f"• **스타레일:** 워프 `{hsr['total_pulls']:,}회` · ★5 `{hsr['star5_count']}종` · 유물 {rel_txt}"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎣 낚시 & 🌾 생활 라이프",
        value=(
            f"• **낚시 Lv.{fl['level']}** (`{fl['catches']:,}마리` · 도감 `{fl['dex_owned']}/{fl['dex_total']}` · 최장 {best_fish_txt})\n"
            f"• **장비:** `{fl['rod_name']}` · 그물 `{fl['net_name']}`\n"
            f"• **생활:** 동반 펫 `{fl['pet_label']}` · 개인 농장 `Lv.{fl['farm_level']}` · 공동 농장 `Lv.{fl['guild_farm_level']}`"
        ),
        inline=False,
    )
    if stats.get("newly_unlocked_titles"):
        un_txt = ", ".join(f"{economy_core.TITLES[t]['emoji']} {economy_core.TITLES[t]['name']}" for t in stats["newly_unlocked_titles"] if t in economy_core.TITLES)
        if un_txt:
            embed.add_field(name="🎉 새 업적 칭호 자동 해금!", value=un_txt, inline=False)

    embed.set_footer(text="칭호 변경 및 꾸미기는 /경제 칭호 · 자산 송금은 /경제 송금")

    if png_buf is not None:
        file = discord.File(fp=png_buf, filename="profile_card.png")
        embed.set_image(url="attachment://profile_card.png")
        await target_send(embed=embed, file=file)
    else:
        if hasattr(target_user, "display_avatar"):
            embed.set_thumbnail(url=target_user.display_avatar.url)
        await target_send(embed=embed)


def build_lottery_draw_embed(draw_res: Dict[str, Any], guild_name: str = "전체 서버") -> discord.Embed:
    nums_txt = "  ".join(f"**`[{n:02d}]`**" for n in draw_res.get("winning_numbers", []))
    winners = draw_res.get("winners") or []
    if winners:
        win_lines = [
            f"• `{w['best_rank']}등` **{w['user_name']}** — **`+{w['total_prize']:,}💎`**"
            for w in winners[:8]
        ]
        win_val = "\n".join(win_lines)
    else:
        win_val = "*(이번 회차는 1~3등 당첨자가 없어 잭팟이 다음 회차로 이월되었습니다!)*"

    roll_note = (
        f"🔥 **1등 미당첨으로 다음 회차 잭팟이 `{draw_res.get('next_jackpot', 1000):,}💎`으로 이월되었습니다!**"
        if draw_res.get("rolled_over")
        else f"🎊 **1등 당첨자 탄생! 다음 회차 기본 잭팟은 `{draw_res.get('next_jackpot', 1000):,}💎`으로 시작합니다.**"
    )

    embed = discord.Embed(
        title=f"🎟️ 제 {draw_res.get('round', 1)}회차 norosi 주간 로또 추첨 결과!",
        description=(
            f"📅 **추첨 시각:** `{draw_res.get('drawn_at', '-')}` ({guild_name})\n"
            f"🎱 **당첨 번호 (1~20):** {nums_txt}\n\n"
            f"• **총 응모 복권:** `{draw_res.get('ticket_count', 0):,}장`  ·  **총 상금 풀:** **`{draw_res.get('total_pot', 0):,}💎`**\n"
            f"• **🥇 1등 (4개 일치):** `{draw_res.get('rank1_count', 0)}명` (`각 {draw_res.get('rank1_each', 0):,}💎`)\n"
            f"• **🥈 2등 (3개 일치):** `{draw_res.get('rank2_count', 0)}명` (`각 {draw_res.get('rank2_each', 500):,}💎`)\n"
            f"• **🥉 3등 (2개 일치):** `{draw_res.get('rank3_count', 0)}명` (`각 {draw_res.get('rank3_each', 120):,}💎`)\n\n"
            f"{roll_note}"
        ),
        color=0xF59E0B,
        timestamp=datetime.datetime.now(core.KST),
    )
    embed.add_field(name="🏆 주요 당첨자 및 즉시 지급 내역", value=win_val, inline=False)
    embed.set_footer(text="매주 일요일 21:00 KST 자동 추첨 · /경제 복권 으로 새 회차 응모!")
    return embed


# ==========================================
# 1. 칭호 & 배지 상점 뷰
# ==========================================
class TitleShopSelect(discord.ui.Select):
    def __init__(self, parent_view: "TitleStudioView", stats: Dict[str, Any]):
        self.parent_view = parent_view
        owned = set(stats.get("owned_titles") or ["newbie"])
        equipped_id = stats.get("title", {}).get("id", "newbie")
        opts: List[discord.SelectOption] = []
        for tid, tm in economy_core.TITLES.items():
            if tid == equipped_id:
                status = "✅ 장착중"
            elif tid in owned:
                status = "📦 보유(장착하기)"
            else:
                status = f"🛒 {tm['price']:,}💎"
            opts.append(discord.SelectOption(
                label=f"{tm['name']} ({status})"[:95],
                value=tid,
                description=tm["unlock_hint"][:95],
                emoji=tm["emoji"],
                default=(tid == equipped_id),
            ))
        super().__init__(
            placeholder="🏷️ 구매하거나 장착할 칭호를 선택하세요...",
            min_values=1,
            max_values=1,
            options=opts[:25],
            row=0,
            custom_id="norosi:TitleStudioView:title_select",
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        if interaction.user.id != (pv.user.id if pv.user else interaction.user.id):
            await core.safe_send_response(interaction, "❌ 본인만 칭호를 변경/구매할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        tid = self.values[0]
        ok, msg = await asyncio.to_thread(
            economy_core.buy_or_equip_title,
            pv.guild_id,
            interaction.user.id,
            tid,
            interaction.user.display_name,
        )
        pv.status_msg = msg
        await pv.refresh()
        await core.safe_edit_response(interaction, embed=pv.build_embed(), view=pv)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)


class TitleStudioView(core.SafeView):
    def __init__(self, user: Optional[discord.abc.User] = None, guild_id: int = 0):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.status_msg = ""
        self.stats: Dict[str, Any] = economy_core.get_title_shop_state(
            self.guild_id,
            user.id if user else 0,
            user.display_name if user else "유저",
        )
        self._rebuild()

    async def refresh(self):
        uid = self.user.id if self.user else 0
        uname = self.user.display_name if self.user else "유저"
        self.stats = await asyncio.to_thread(economy_core.get_title_shop_state, self.guild_id, uid, uname)
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        self.add_item(TitleShopSelect(self, self.stats))

    def build_embed(self) -> discord.Embed:
        st = self.stats
        cur = st["title"]
        owned = set(st.get("owned_titles") or ["newbie"])
        lines = []
        for tid, tm in economy_core.TITLES.items():
            if tid == cur["id"]:
                badge = "✅ **[장착중]**"
            elif tid in owned:
                badge = "🔓 **보유중**"
            else:
                badge = f"🔒 `{tm['price']:,}💎`"
            lines.append(f"• {tm['emoji']} **`{tm['tag']}`** — {badge}\n  └ *{tm['unlock_hint']}*")

        badges = st.get("badges") or []
        badge_line = "  ".join(f"{b['emoji']} `{b['name']}`" for b in badges) if badges else "*(아직 해금된 배지 없음)*"
        banner = f"\n\n> {self.status_msg}" if self.status_msg else ""

        embed = discord.Embed(
            title=f"🏷️ {st['user_name']}님의 칭호 상점 & 배지 쇼케이스",
            description=(
                f"• **현재 장착 칭호:** {cur['emoji']} **`{cur['tag']}`**  ·  **보유 크리스탈:** **`{st['crystals']:,}💎`**\n"
                f"• **보유 배지 ({len(badges)}/{len(economy_core.BADGE_CATALOG)}):** {badge_line}"
                f"{banner}\n\n"
                + "\n".join(lines)
            )[:4096],
            color=discord.Color.from_rgb(*cur.get("rgb", (56, 189, 248))),
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="아래 드롭다운에서 보유 칭호를 즉시 장착하거나 새 칭호를 구매할 수 있습니다 (/프로필카드 반영)")
        return embed


# ==========================================
# 2. 주간 로또 복권 스튜디오 뷰 & 모달
# ==========================================
class LotteryPickModal(core.SafeModal, title="🎟️ 로또 번호 직접 선택 (1~20 중 4개)"):
    numbers_input = discord.ui.TextInput(
        label="번호 4개 입력 (공백 또는 쉼표로 구분)",
        placeholder="예: 3 7 12 19  (1~20 사이 중복 없는 4개 숫자 · 100💎)",
        required=True,
        max_length=40,
    )

    def __init__(self, parent_view: "LotteryStudioView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.numbers_input.value.strip()
        tokens = [t for t in re.split(r"[\s,./]+", raw) if t]
        picks: List[int] = []
        for t in tokens:
            if not t.isdigit():
                await core.safe_send_response(interaction, "❌ 숫자 4개만 입력해 주세요! (예: `3 7 12 19`)", ephemeral=True)
                return
            picks.append(int(t))

        await core.safe_defer(interaction, ephemeral=True)
        ok, msg, _ = await asyncio.to_thread(
            economy_core.buy_lottery_tickets,
            interaction.user.id,
            interaction.user.display_name,
            1,
            picks,
        )
        if self.parent_view:
            self.parent_view.status_msg = msg
            await self.parent_view.refresh()
            if getattr(self.parent_view, "message", None):
                try:
                    await self.parent_view.message.edit(embed=self.parent_view.build_embed(), view=self.parent_view)
                except Exception:
                    pass
        await interaction.followup.send(msg, ephemeral=True)


class LotteryStudioView(core.SafeView):
    def __init__(self, user: Optional[discord.abc.User] = None, guild: Optional[discord.Guild] = None):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.guild_id = guild.id if guild else 0
        self.status_msg = ""
        uid = user.id if user else 0
        self.overview: Dict[str, Any] = economy_core.get_lottery_overview(uid)

    async def refresh(self):
        uid = self.user.id if self.user else 0
        self.overview = await asyncio.to_thread(economy_core.get_lottery_overview, uid)

    def build_embed(self) -> discord.Embed:
        ov = self.overview
        total_pot = ov["jackpot"] + ov["pool"]
        my_t = ov.get("my_tickets") or []
        if my_t:
            my_lines = [
                f"• `#{t['ticket_id']}` ➔ **`{', '.join(str(n) for n in t['numbers'])}`**"
                for t in my_t[:10]
            ]
            my_txt = "\n".join(my_lines)
        else:
            my_txt = "*(이번 회차에 구매한 복권이 아직 없습니다. `100💎`/장으로 도전해보세요!)*"

        last = ov.get("last_draw")
        if isinstance(last, dict):
            w_nums = ", ".join(str(n) for n in last.get("winning_numbers", []))
            last_txt = (
                f"제 {last.get('round', 1)}회 (`{last.get('drawn_at', '-')}`) | 당첨번호: **`[{w_nums}]`**\n"
                f"└ 1등 `{last.get('rank1_count', 0)}명` · 2등 `{last.get('rank2_count', 0)}명` · 3등 `{last.get('rank3_count', 0)}명`"
            )
        else:
            last_txt = "*(아직 진행된 추첨 회차가 없습니다.)*"

        banner = f"\n> {self.status_msg}\n" if self.status_msg else ""

        embed = discord.Embed(
            title=f"🎟️ norosi 주간 로또 복권 (제 {ov['round']}회차)",
            description=(
                f"`1~20` 숫자 중 `4개`를 선택해 매주 **일요일 21:00 KST** 자동 추첨에 도전하세요!\n"
                f"*(크리스탈 송금 세금의 30% + 티켓 판매금 85%가 실시간 누적 · 1등 미당첨 시 이월)*\n"
                f"{banner}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **💰 현재 예상 총 상금:** **`{total_pot:,}💎`** *(기본/이월 `{ov['jackpot']:,}💎` + 누적 풀 `{ov['pool']:,}💎`)*\n"
                f"• **🎫 전체 응모 수:** `{ov['total_tickets']:,}장`  ·  **내 보유 크리스탈:** **`{ov['crystals']:,}💎`**\n"
                f"• **🏆 당첨 보상:** 🥇4개 일치(상금 70%, 최소 `1,000💎`) · 🥈3개(`500💎`) · 🥉2개(`120💎`)\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=0xF59E0B,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.add_field(
            name=f"🧾 내 이번 회차 복권 ({len(my_t)}/{economy_core.LOTTERY_MAX_TICKETS_PER_ROUND}장)",
            value=my_txt,
            inline=False,
        )
        embed.add_field(name="📜 직전 회차 결과", value=last_txt, inline=False)
        embed.set_footer(text="1장당 100💎 (회차당 최대 10장) · 관리자 전용 버튼으로 알림 채널 설정 및 수동 추첨 가능")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 복권 창은 **{self.user.display_name}**님의 창입니다. `/경제 복권`으로 열어주세요!",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="🎟️ 자동 1장 (100💎)", style=discord.ButtonStyle.success, row=0)
    async def btn_buy_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg, _ = await asyncio.to_thread(
            economy_core.buy_lottery_tickets, interaction.user.id, interaction.user.display_name, 1, None
        )
        self.status_msg = msg
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🎫 자동 5장 (500💎)", style=discord.ButtonStyle.primary, row=0)
    async def btn_buy_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg, _ = await asyncio.to_thread(
            economy_core.buy_lottery_tickets, interaction.user.id, interaction.user.display_name, 5, None
        )
        self.status_msg = msg
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="✏️ 번호 직접 선택", style=discord.ButtonStyle.secondary, row=0)
    async def btn_manual_pick(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LotteryPickModal(self))

    @discord.ui.button(label="📢 이 채널 결과알림 [관리자]", style=discord.ButtonStyle.secondary, row=1)
    async def btn_set_announce(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 설정할 수 있습니다.", ephemeral=True)
            return
        bot_ref = interaction.client
        is_owner = await bot_ref.is_bot_owner_user(interaction.user) if hasattr(bot_ref, "is_bot_owner_user") else False
        if not (is_owner or interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild):
            await core.safe_send_response(interaction, "❌ 서버 관리자 권한이 필요합니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        await asyncio.to_thread(economy_core.set_lottery_announce_channel, interaction.guild_id, interaction.channel_id)
        await interaction.followup.send(
            f"✅ 매주 일요일 21:00 KST 주간 로또 추첨 결과가 <#{interaction.channel_id}> 채널에 자동 공지됩니다!",
            ephemeral=True,
        )

    @discord.ui.button(label="🎲 수동 추첨 실행 [관리자]", style=discord.ButtonStyle.danger, row=1)
    async def btn_manual_draw(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot_ref = interaction.client
        is_owner = await bot_ref.is_bot_owner_user(interaction.user) if hasattr(bot_ref, "is_bot_owner_user") else False
        is_admin = bool(
            interaction.guild and isinstance(interaction.user, discord.Member)
            and (interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild)
        )
        if not (is_owner or is_admin):
            await core.safe_send_response(interaction, "❌ 관리자 또는 봇 소유자만 추첨을 실행할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        draw_res = await asyncio.to_thread(economy_core.execute_lottery_draw, f"admin:{interaction.user.display_name}")
        await self.refresh()
        self.status_msg = f"🎉 제 {draw_res['round']}회 추첨 완료! 당첨번호: `{draw_res['winning_numbers']}`"
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        draw_embed = build_lottery_draw_embed(draw_res, interaction.guild.name if interaction.guild else "서버")
        await interaction.followup.send(embed=draw_embed)


# ==========================================
# 3. 통합 자산 랭킹 뷰
# ==========================================
class EconomyLeaderboardView(core.SafeView):
    def __init__(self, user: Optional[discord.abc.User] = None, guild_id: int = 0, mode: str = "net_worth"):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.mode = mode
        self.lb = economy_core.get_economy_leaderboard(self.guild_id)

    def build_embed(self) -> discord.Embed:
        medals = ["🥇", "🥈", "🥉"]
        if self.mode == "crystal":
            title = "💎 통합 크리스탈 랭킹 TOP 15"
            rows = self.lb["by_crystal"]
        elif self.mode == "gold":
            title = "🪙 서버 낚시·생활 골드 랭킹 TOP 15"
            rows = self.lb["by_gold"]
        else:
            title = "🏦 서버 통합 순자산 랭킹 TOP 15 (💎 + 🪙×0.25)"
            rows = self.lb["by_total"]

        lines = []
        for idx, r in enumerate(rows[:15]):
            m = medals[idx] if idx < 3 else f"`{idx + 1:2d}.`"
            lines.append(
                f"{m} {r['title_emoji']} **`{r['title_tag']}` {r['user_name']}** — "
                f"💎 `{r['crystals']:,}` · 🪙 `{r['fish_gold']:,}` *(총 `{r['net_worth']:,}` · 출석 `{r['att_days']}일`)*"
            )
        desc = "\n".join(lines) if lines else "*(아직 집계된 자산 데이터가 없습니다.)*"
        embed = discord.Embed(
            title=title,
            description=desc[:4096],
            color=0x38BDF8,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="하단 버튼으로 순자산 · 크리스탈 · 낚시 골드 기준을 전환할 수 있습니다.")
        return embed

    @discord.ui.button(label="🏦 통합 순자산순", style=discord.ButtonStyle.primary, row=0)
    async def btn_net(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "net_worth"
        self.lb = await asyncio.to_thread(economy_core.get_economy_leaderboard, self.guild_id)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="💎 크리스탈순", style=discord.ButtonStyle.secondary, row=0)
    async def btn_cry(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "crystal"
        self.lb = await asyncio.to_thread(economy_core.get_economy_leaderboard, self.guild_id)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🪙 낚시골드순", style=discord.ButtonStyle.secondary, row=0)
    async def btn_gold(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "gold"
        self.lb = await asyncio.to_thread(economy_core.get_economy_leaderboard, self.guild_id)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


# ==========================================
# 4. Cog 등록 (/프로필카드 & /경제 그룹)
# ==========================================
class ProfileCardStandaloneCog(commands.Cog):
    """단독 슬래시 /프로필카드 및 접두사 !프로필카드 · !복권 단축어 Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="프로필카드", description="🪪 프로세카·원신·스타레일·낚시·생활·칭호·배지 통합 고화질 PNG 프로필 카드를 생성합니다.")
    @app_commands.describe(유저="조회할 서버 멤버 (미입력 시 본인)")
    async def profile_card_slash(self, interaction: discord.Interaction, 유저: Optional[discord.Member] = None):
        await core.safe_defer(interaction)
        target = 유저 or interaction.user
        guild_id = interaction.guild_id or 0
        await _send_profile_card(interaction.followup.send, target, guild_id)

    @commands.command(name="프로필카드", aliases=["통합프로필", "profilecard"])
    async def prefix_profile_card(self, ctx: commands.Context, 유저: Optional[discord.Member] = None):
        target = 유저 or ctx.author
        guild_id = ctx.guild.id if ctx.guild else 0
        await _send_profile_card(ctx.send, target, guild_id, is_interaction=False)

    @commands.command(name="복권", aliases=["로또", "lottery"])
    async def prefix_lottery(self, ctx: commands.Context):
        view = LotteryStudioView(ctx.author, ctx.guild)
        msg = await ctx.send(embed=view.build_embed(), view=view)
        view.message = msg


class EconomyGroupCog(commands.GroupCog, name="경제", description="💳 통합 프로필 카드 · 크리스탈 송금 · 칭호 상점 · 주간 로또 복권 · 통합 랭킹"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="프로필카드", description="🪪 4대 게임·출석·칭호·배지 통합 고화질 PNG 프로필 카드를 발급합니다.")
    @app_commands.describe(유저="조회할 서버 멤버 (미입력 시 본인)")
    async def eco_profile_card(self, interaction: discord.Interaction, 유저: Optional[discord.Member] = None):
        await core.safe_defer(interaction)
        target = 유저 or interaction.user
        await _send_profile_card(interaction.followup.send, target, interaction.guild_id or 0)

    @app_commands.command(name="송금", description="💸 다른 멤버에게 크리스탈을 송금합니다 (5% 세금 · 일일 최대 5,000💎 · 세금 일부 복권 적립).")
    @app_commands.describe(상대="크리스탈을 받을 서버 멤버", 금액="송금할 크리스탈 금액 (10 ~ 5,000)")
    async def eco_transfer(
        self,
        interaction: discord.Interaction,
        상대: discord.Member,
        금액: app_commands.Range[int, 10, 5000],
    ):
        await core.safe_defer(interaction)
        ok, msg, details = await asyncio.to_thread(
            economy_core.transfer_crystals,
            interaction.user.id,
            interaction.user.display_name,
            상대.id,
            상대.display_name,
            int(금액),
            bool(상대.bot),
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
        embed.set_footer(text="세금 5% 중 30%는 매주 일요일 21:00 주간 로또 상금 풀에 자동 적립됩니다.")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="칭호", description="🏷️ 칭호 상점 및 업적 자동 해금 배지 쇼케이스를 엽니다.")
    async def eco_titles(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        view = await asyncio.to_thread(TitleStudioView, interaction.user, interaction.guild_id or 0)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="복권", description="🎟️ 매주 일요일 21:00 추첨 주간 로또 복권 구매 및 상금 풀 확인")
    async def eco_lottery(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        view = await asyncio.to_thread(LotteryStudioView, interaction.user, interaction.guild)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="랭킹", description="🏦 서버 크리스탈 · 낚시 골드 · 통합 순자산 랭킹을 확인합니다.")
    async def eco_ranking(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        view = await asyncio.to_thread(EconomyLeaderboardView, interaction.user, interaction.guild_id or 0, "net_worth")
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg


async def setup(bot: commands.Bot):
    await bot.add_cog(ProfileCardStandaloneCog(bot))
    await bot.add_cog(EconomyGroupCog(bot))
