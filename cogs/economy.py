"""
cogs/economy.py - 통합 경제 & 커스터마이징 Cog (#2)
- 통합 프로필 카드 PNG (/프로필카드, /경제 프로필카드)
- 칭호 상점 & 업적 배지 (/경제 칭호)
- 크리스탈 송금 & 세금 (/경제 송금)
- 통합 자산 랭킹 (/경제 랭킹)
"""

from __future__ import annotations

import asyncio
import datetime
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
            f"• **프로세카:** 뽑기 `{sek.get('total_pulls', 0):,}회` · `{sek['unique_cards']}종` (★4 `{sek['star4_count']}장`) · 오시 `{sek['oshi']}` · 덱 `{sek['deck_power']:,}`\n"
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

    embed.set_footer(text="칭호 꾸미기·자산 송금은 /설정 ➔ 👤 개인에서 이용할 수 있습니다.")

    if png_buf is not None:
        file = discord.File(fp=png_buf, filename="profile_card.png")
        embed.set_image(url="attachment://profile_card.png")
        await target_send(embed=embed, file=file)
    else:
        if hasattr(target_user, "display_avatar"):
            embed.set_thumbnail(url=target_user.display_avatar.url)
        await target_send(embed=embed)


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
        if pv.user and interaction.user.id != pv.user.id:
            await core.safe_send_response(interaction, "❌ 본인만 칭호를 변경/구매할 수 있습니다.", ephemeral=True)
            return
        if pv.user is None:
            pv.user = interaction.user
        pv.guild_id = pv.guild_id or (interaction.guild_id or 0)
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
    def __init__(self, user: Optional[discord.abc.User] = None, guild_id: int = 0, stats: Optional[Dict[str, Any]] = None):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.status_msg = ""
        if stats and "title" in stats:
            self.stats: Dict[str, Any] = stats
        else:
            self.stats = economy_core.get_title_shop_state(
                self.guild_id,
                user.id if user else 0,
                user.display_name if user else "유저",
            )
        self._rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                "❌ 본인이 연 칭호·배지 스튜디오만 조작할 수 있습니다.",
                ephemeral=True,
            )
            return False
        return True

    async def refresh(self):
        uid = self.user.id if self.user else 0
        uname = self.user.display_name if self.user else "유저"
        self.stats = await asyncio.to_thread(economy_core.get_title_shop_state, self.guild_id, uid, uname)
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        self.add_item(TitleShopSelect(self, self.stats))
        btn_card = discord.ui.Button(
            label="🪪 프로필카드 미리보기",
            style=discord.ButtonStyle.primary,
            row=1,
            custom_id="norosi:TitleStudioView:preview_card",
        )
        btn_card.callback = self._on_preview_card
        self.add_item(btn_card)

        btn_lotto = discord.ui.Button(
            label="🎟️ 주간 복권",
            style=discord.ButtonStyle.success,
            row=1,
            custom_id="norosi:TitleStudioView:open_lottery",
        )
        btn_lotto.callback = self._on_open_lottery
        self.add_item(btn_lotto)

        btn_ref = discord.ui.Button(
            label="🔄 새로고침",
            style=discord.ButtonStyle.secondary,
            row=1,
            custom_id="norosi:TitleStudioView:refresh",
        )
        btn_ref.callback = self._on_refresh
        self.add_item(btn_ref)

    async def _on_preview_card(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        target = self.user or interaction.user
        gid = self.guild_id or (interaction.guild_id or 0)
        await _send_profile_card(interaction.followup.send, target, gid, is_interaction=True)

    async def _on_open_lottery(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        target = self.user or interaction.user
        gid = self.guild_id or (interaction.guild_id or 0)
        ov = await asyncio.to_thread(economy_core.get_lottery_overview, target.id)
        lot_view = LotteryStudioView(target, gid, overview=ov)
        msg = await interaction.followup.send(embed=lot_view.build_embed(), view=lot_view, wait=True)
        lot_view.message = msg

    async def _on_refresh(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        self.status_msg = "🔄 칭호 및 배지 보유 상태를 최신으로 갱신했습니다."
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    def build_embed(self) -> discord.Embed:
        if not self.stats or "title" not in self.stats:
            self.stats = economy_core.get_title_shop_state(
                self.guild_id,
                self.user.id if self.user else 0,
                self.user.display_name if self.user else "유저",
            )
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
        embed.set_footer(text="아래 드롭다운에서 보유 칭호를 즉시 장착하거나 새 칭호를 구매할 수 있습니다 (/설정 ➔ 👤 개인 프로필카드 반영)")
        return embed


# ==========================================
# 2-A. 주간 크리스탈 복권 스튜디오 뷰
# ==========================================
class LotteryManualPickModal(core.SafeModal, title="🔢 주간 복권 수동 번호 선택 (1~20 중 4개)"):
    nums_input = discord.ui.TextInput(
        label="1~20 사이의 중복 없는 숫자 4개 입력",
        placeholder="예: 3 7 12 19 (공백 또는 쉼표로 구분)",
        required=True,
        max_length=25,
    )

    def __init__(self, studio_view: "LotteryStudioView"):
        super().__init__()
        self.studio_view = studio_view

    async def on_submit(self, interaction: discord.Interaction):
        import re
        raw_parts = [p for p in re.split(r"[\s,]+", (self.nums_input.value or "").strip()) if p]
        try:
            picks = [int(x) for x in raw_parts]
        except ValueError:
            await core.safe_send_response(
                interaction,
                "❌ 숫자만 입력해 주세요! (예: `3 7 12 19`)",
                ephemeral=True,
            )
            return

        await core.safe_defer(interaction)
        ok, msg, _ = await asyncio.to_thread(
            economy_core.buy_lottery_tickets,
            interaction.user.id,
            interaction.user.display_name,
            1,
            picks,
        )
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)
            return
        self.studio_view.status_msg = msg
        self.studio_view.overview = await asyncio.to_thread(economy_core.get_lottery_overview, interaction.user.id)
        await core.safe_edit_response(interaction, embed=self.studio_view.build_embed(), view=self.studio_view)


class LotteryStudioView(core.SafeView):
    def __init__(
        self,
        user: Optional[discord.abc.User] = None,
        guild_id: int = 0,
        overview: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.overview = overview or economy_core.get_lottery_overview(user.id if user else 0)
        self.status_msg = ""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 복권 창구만 조작할 수 있습니다! (`/설정`에서 직접 열어주세요)", ephemeral=True)
            return False
        if self.user is None:
            self.user = interaction.user
        return True

    def build_embed(self) -> discord.Embed:
        ov = self.overview or economy_core.get_lottery_overview(self.user.id if self.user else 0)
        my_tickets = ov.get("my_tickets") or []
        total_pot = int(ov.get("jackpot", 1000)) + int(ov.get("pool", 0))
        uname = self.user.display_name if self.user else "유저"

        my_lines = [
            f"• `#{t['ticket_id']}` — **`[ {', '.join(str(n) for n in (t.get('numbers') or []))} ]`**"
            for t in my_tickets[:10]
        ] or ["*(이번 회차 구매한 복권이 없습니다 — 아래 버튼으로 행운에 도전해 보세요!)*"]

        last_draw = ov.get("last_draw")
        if isinstance(last_draw, dict) and last_draw.get("winning_numbers"):
            w_str = ", ".join(str(n) for n in last_draw["winning_numbers"])
            last_txt = (
                f"제 `{last_draw.get('round', '-')}`회차 당첨번호 **`[ {w_str} ]`** "
                f"(1등 `{last_draw.get('rank1_count', 0)}명` · 2등 `{last_draw.get('rank2_count', 0)}명` · 3등 `{last_draw.get('rank3_count', 0)}명`)"
            )
        else:
            last_txt = "*(아직 추첨 기록이 없습니다 — 매주 월요일 자정 00:00 KST 자동 추첨!)*"

        notice = f"\n\n{self.status_msg}" if self.status_msg else ""
        embed = discord.Embed(
            title=f"🎟️ 제 {ov.get('round', 1)}회차 세카이 주간 크리스탈 복권",
            description=(
                f"• **💰 현재 총 상금 풀:** **`{total_pot:,}💎`** *(기본·이월 `{ov.get('jackpot', 1000):,}💎` + 누적 판매·세금 풀 `{ov.get('pool', 0):,}💎`)*\n"
                f"• **🎟️ 전체 판매 티켓:** `{ov.get('total_tickets', 0):,}장`  ·  **내 보유 크리스탈:** **`{ov.get('crystals', 0):,}💎`**\n"
                f"• **🏆 당첨 기준 (1~{economy_core.LOTTERY_POOL_MAX_NUM} 중 {economy_core.LOTTERY_PICK_COUNT}개 일치):** "
                "4개 일치 **1등(상금풀 70%+칭호)** · 3개 **2등(+500💎+칭호)** · 2개 **3등(+120💎)**"
                f"{notice}"
            )[:4096],
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.add_field(
            name=f"🎫 {uname}님의 이번 회차 복권 ({len(my_tickets)}/{economy_core.LOTTERY_MAX_TICKETS_PER_ROUND}장)",
            value="\n".join(my_lines)[:1024],
            inline=False,
        )
        embed.add_field(name="📜 직전 회차 추첨 결과", value=last_txt[:1024], inline=False)
        embed.set_footer(text=f"1장당 {economy_core.LOTTERY_TICKET_PRICE}💎 • 회차당 최대 {economy_core.LOTTERY_MAX_TICKETS_PER_ROUND}장 • 매주 월요일 00:00 KST 자동 추첨")
        return embed

    @discord.ui.button(label="🎲 자동 1장 (100💎)", style=discord.ButtonStyle.success, row=0)
    async def btn_auto_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg, _ = await asyncio.to_thread(
            economy_core.buy_lottery_tickets, interaction.user.id, interaction.user.display_name, 1, None
        )
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)
            return
        self.status_msg = msg
        self.overview = await asyncio.to_thread(economy_core.get_lottery_overview, interaction.user.id)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🎲 자동 5장 (500💎)", style=discord.ButtonStyle.primary, row=0)
    async def btn_auto_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg, _ = await asyncio.to_thread(
            economy_core.buy_lottery_tickets, interaction.user.id, interaction.user.display_name, 5, None
        )
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)
            return
        self.status_msg = msg
        self.overview = await asyncio.to_thread(economy_core.get_lottery_overview, interaction.user.id)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔢 수동 번호 선택", style=discord.ButtonStyle.secondary, row=0)
    async def btn_manual(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LotteryManualPickModal(self))

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=1)
    async def btn_refresh_lotto(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.status_msg = ""
        self.overview = await asyncio.to_thread(economy_core.get_lottery_overview, interaction.user.id)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="📢 이 채널에 발표 설정", style=discord.ButtonStyle.secondary, row=1)
    async def btn_set_announce_ch(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not (
            interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild
        ):
            await core.safe_send_response(interaction, "❌ 추첨 발표 채널 지정은 **서버 관리자**만 설정할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        await asyncio.to_thread(economy_core.set_lottery_announce_channel, interaction.guild.id, interaction.channel_id)
        await interaction.followup.send(
            f"✅ 매주 월요일 자정 복권 추첨 결과 발표 채널이 <#{interaction.channel_id}>로 설정되었습니다!",
            ephemeral=True,
        )


# ==========================================
# 2. 통합 자산 랭킹 뷰
# ==========================================
class EconomyLeaderboardView(core.SafeView):
    def __init__(self, user: Optional[discord.abc.User] = None, guild_id: int = 0, mode: str = "net_worth", lb: Optional[Dict[str, Any]] = None):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.mode = mode
        self.lb = lb if lb is not None else economy_core.get_economy_leaderboard(self.guild_id)
        self._sync_tab_styles()

    def _sync_tab_styles(self):
        self.btn_net.style = discord.ButtonStyle.primary if self.mode == "net_worth" else discord.ButtonStyle.secondary
        self.btn_cry.style = discord.ButtonStyle.primary if self.mode == "crystal" else discord.ButtonStyle.secondary
        self.btn_gold.style = discord.ButtonStyle.primary if self.mode == "gold" else discord.ButtonStyle.secondary

    def build_embed(self) -> discord.Embed:
        self._sync_tab_styles()
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

        my_uid = str(self.user.id) if self.user else ""
        my_rank = None
        for idx, r in enumerate(rows, 1):
            if my_uid and str(r.get("user_id", "")) == my_uid:
                my_rank = idx
                break

        lines = []
        for idx, r in enumerate(rows[:15]):
            m = medals[idx] if idx < 3 else f"`{idx + 1:2d}.`"
            me_tag = " 👈" if (my_uid and str(r.get("user_id", "")) == my_uid) else ""
            lines.append(
                f"{m} {r['title_emoji']} **`{r['title_tag']}` {r['user_name']}**{me_tag} — "
                f"💎 `{r['crystals']:,}` · 🪙 `{r['fish_gold']:,}` *(총 `{r['net_worth']:,}` · 출석 `{r['att_days']}일`)*"
            )
        desc = "\n".join(lines) if lines else "*(아직 집계된 자산 데이터가 없습니다.)*"
        embed = discord.Embed(
            title=title,
            description=desc[:4096],
            color=0x38BDF8,
            timestamp=datetime.datetime.now(core.KST),
        )
        rank_hint = f"📍 내 순위: #{my_rank}위  ·  " if my_rank else ""
        if rank_hint.strip():
            embed.set_footer(text=rank_hint.strip(" •·"))
        return embed

    @discord.ui.button(label="🏦 통합 순자산순", style=discord.ButtonStyle.primary, row=0)
    async def btn_net(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.guild_id = self.guild_id or (interaction.guild_id or 0)
        self.mode = "net_worth"
        self.lb = await asyncio.to_thread(economy_core.get_economy_leaderboard, self.guild_id)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="💎 크리스탈순", style=discord.ButtonStyle.secondary, row=0)
    async def btn_cry(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.guild_id = self.guild_id or (interaction.guild_id or 0)
        self.mode = "crystal"
        self.lb = await asyncio.to_thread(economy_core.get_economy_leaderboard, self.guild_id)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🪙 낚시골드순", style=discord.ButtonStyle.secondary, row=0)
    async def btn_gold(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.guild_id = self.guild_id or (interaction.guild_id or 0)
        self.mode = "gold"
        self.lb = await asyncio.to_thread(economy_core.get_economy_leaderboard, self.guild_id)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.guild_id = self.guild_id or (interaction.guild_id or 0)
        self.lb = await asyncio.to_thread(economy_core.get_economy_leaderboard, self.guild_id)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


# ==========================================
# 3. Cog 등록 (/프로필카드 & /경제 그룹)
# ==========================================
class ProfileCardStandaloneCog(commands.Cog):
    """단독 슬래시 /프로필카드 Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="프로필카드", description="🪪 프로세카·원신·스타레일·낚시·생활·칭호·배지 통합 고화질 PNG 프로필 카드를 생성합니다.")
    @app_commands.describe(유저="조회할 서버 멤버 (미입력 시 본인)")
    async def profile_card_slash(self, interaction: discord.Interaction, 유저: Optional[discord.Member] = None):
        await core.safe_defer(interaction)
        target = 유저 or interaction.user
        guild_id = interaction.guild_id or 0
        await _send_profile_card(interaction.followup.send, target, guild_id)

class EconomyGroupCog(commands.GroupCog, name="경제", description="💳 통합 프로필 카드 · 크리스탈 송금 · 칭호 상점 · 주간 복권 · 통합 자산 랭킹"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="프로필카드", description="🪪 4대 게임·출석·칭호·배지 통합 고화질 PNG 프로필 카드를 발급합니다.")
    @app_commands.describe(유저="조회할 서버 멤버 (미입력 시 본인)")
    async def eco_profile_card(self, interaction: discord.Interaction, 유저: Optional[discord.Member] = None):
        await core.safe_defer(interaction)
        target = 유저 or interaction.user
        await _send_profile_card(interaction.followup.send, target, interaction.guild_id or 0)

    @app_commands.command(name="송금", description="💸 다른 멤버에게 크리스탈을 송금합니다 (5% 세금 차감 · 일일 최대 5,000💎).")
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
        embed.set_footer(text="송금 수수료 5%가 자동 차감되며, 일일 최대 송금 한도는 5,000💎입니다.")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="칭호", description="🏷️ 칭호 상점 및 업적 자동 해금 배지 쇼케이스를 엽니다.")
    async def eco_titles(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        stats = await asyncio.to_thread(
            economy_core.get_title_shop_state,
            interaction.guild_id or 0,
            interaction.user.id,
            interaction.user.display_name,
        )
        view = TitleStudioView(interaction.user, interaction.guild_id or 0, stats=stats)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="복권", description="🎟️ 매주 월요일 추첨되는 주간 크리스탈 로또 복권을 구매·확인합니다.")
    async def eco_lottery(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        ov = await asyncio.to_thread(economy_core.get_lottery_overview, interaction.user.id)
        view = LotteryStudioView(interaction.user, interaction.guild_id or 0, overview=ov)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="랭킹", description="🏦 서버 크리스탈 · 낚시 골드 · 통합 순자산 랭킹을 확인합니다.")
    async def eco_ranking(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        lb = await asyncio.to_thread(economy_core.get_economy_leaderboard, guild_id)
        view = EconomyLeaderboardView(interaction.user, guild_id, "net_worth", lb=lb)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg


async def setup(bot: commands.Bot):
    await bot.add_cog(ProfileCardStandaloneCog(bot))
    await bot.add_cog(EconomyGroupCog(bot))
