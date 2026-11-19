"""
cogs/life.py - 방치형 · 생활 컨텐츠 확장 Cog (#6)
- 개인 농장 (/생활 농장, !농장): 4~6칸 밭 · 6종 씨앗 · 물주기 · 비료 · 수확 · 판매
- 서버 공동 농장 (/생활 공동농장, !공동농장): 길드 협동 Lv.1~10 · 무료 물주기 · 기부 · 일일 배당 · 공용 버프
- 펫 키우기 (/생활 펫, !펫): 6종 펫 입양 · 장착 · 간식/★1~2 생선 먹이기 · 놀아주기 · 패시브 버프
- 생선 요리 & 버프 (/생활 요리, /생활 버프, !요리, !버프): ★1~2 미잠금 생선 + 농작물 조리 · 낚시/출석 버프
"""

from __future__ import annotations

import asyncio
import datetime
import time
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

import core
import life_core


def _fmt_countdown(ready_at: float, now_ts: float) -> str:
    rem = int(ready_at - now_ts)
    if rem <= 0:
        return "✅ **수확 가능!**"
    mins, secs = divmod(rem, 60)
    if mins >= 60:
        hrs, m2 = divmod(mins, 60)
        return f"⏳ `{hrs}시간 {m2}분` 남음"
    return f"⏳ `{mins}분 {secs:02d}초` 남음"


# ==========================================
# 1. 개인 농장 View
# ==========================================
class FarmSeedBuySelect(discord.ui.Select):
    def __init__(self, parent_view: "FarmView"):
        self.parent_view = parent_view
        opts: List[discord.SelectOption] = []
        for sid, sp in life_core.SEEDS.items():
            price_s = f"{sp['price_gold']:,}🪙" if sp["price_gold"] > 0 else f"{sp['price_crystal']:,}💎"
            opts.append(discord.SelectOption(
                label=f"{sp['name']} 씨앗 구매 ({price_s})"[:95],
                value=sid,
                description=f"{sp['growth_min']}분 성장 · 판매 {sp['sell_gold']:,}🪙"[:95],
                emoji=sp["emoji"],
            ))
        super().__init__(
            placeholder="🛒 구매할 씨앗 선택 (1개 구매)",
            min_values=1,
            max_values=1,
            options=opts,
            row=0,
            custom_id="norosi:FarmView:seed_buy_select",
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        await core.safe_defer(interaction)
        sid = self.values[0]
        cur = "crystal" if life_core.SEEDS[sid]["price_gold"] <= 0 else "gold"
        ok, msg = await asyncio.to_thread(
            life_core.buy_seed, pv.guild_id, interaction.user.id, sid, 1, cur, interaction.user.display_name
        )
        pv.status_msg = msg
        await pv.refresh()
        await core.safe_edit_response(interaction, embed=pv.build_embed(), view=pv)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)


class FarmPlantSelect(discord.ui.Select):
    def __init__(self, parent_view: "FarmView", seeds_owned: Dict[str, int]):
        self.parent_view = parent_view
        opts: List[discord.SelectOption] = []
        for sid, sp in life_core.SEEDS.items():
            cnt = int(seeds_owned.get(sid, 0) or 0)
            if cnt > 0:
                opts.append(discord.SelectOption(
                    label=f"🪴 {sp['name']} 심기 (보유 {cnt}개)"[:95],
                    value=sid,
                    description=f"빈 밭에 심기 · 성장 {sp['growth_min']}분"[:95],
                    emoji=sp["emoji"],
                ))
        if not opts:
            opts.append(discord.SelectOption(
                label="보유 중인 씨앗이 없습니다 (위에서 구매해 주세요)",
                value="__none__",
                description="상단 드롭다운에서 씨앗을 먼저 구매해 주세요",
                emoji="🌱",
            ))
        super().__init__(
            placeholder="🪴 빈 밭에 심을 보유 씨앗 선택...",
            min_values=1,
            max_values=1,
            options=opts[:25],
            row=1,
            custom_id="norosi:FarmView:seed_plant_select",
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        sid = self.values[0]
        if sid == "__none__":
            await core.safe_send_response(interaction, "🌱 상단 `씨앗 구매` 드롭다운에서 먼저 씨앗을 구매해 주세요!", ephemeral=True)
            return
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(
            life_core.plant_crop, pv.guild_id, interaction.user.id, sid, None, interaction.user.display_name
        )
        pv.status_msg = msg
        await pv.refresh()
        await core.safe_edit_response(interaction, embed=pv.build_embed(), view=pv)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)


class FarmView(core.SafeView):
    def __init__(self, user: Optional[discord.abc.User] = None, guild_id: int = 0, overview: Optional[Dict[str, Any]] = None):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.status_msg = ""
        self.overview: Dict[str, Any] = overview if overview is not None else life_core.get_life_overview(
            self.guild_id, user.id if user else 0, user.display_name if user else "주민"
        )
        self._rebuild()

    async def refresh(self):
        uid = self.user.id if self.user else 0
        uname = self.user.display_name if self.user else "주민"
        self.overview = await asyncio.to_thread(life_core.get_life_overview, self.guild_id, uid, uname)
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        lu = self.overview["user"]
        self.add_item(FarmSeedBuySelect(self))
        self.add_item(FarmPlantSelect(self, lu.get("seeds") or {}))

        actions = [
            ("⚡ 일괄(수확+물)", discord.ButtonStyle.success, 2, "quick_manage", self._on_quick_manage),
            ("💧 전체 물주기", discord.ButtonStyle.primary, 2, "water_all", self._on_water),
            ("✨ 전체 비료 (120🪙/칸)", discord.ButtonStyle.secondary, 2, "fert_all", self._on_fertilize),
            ("🧺 전체 수확", discord.ButtonStyle.success, 2, "harvest_all", self._on_harvest),
            ("💰 작물 일괄 판매", discord.ButtonStyle.primary, 3, "sell_all", self._on_sell),
            ("🚜 밭 확장", discord.ButtonStyle.secondary, 3, "expand", self._on_expand),
            ("🔄 새로고침", discord.ButtonStyle.secondary, 3, "refresh", self._on_refresh),
        ]
        for lbl, st, row, cid_sfx, cb in actions:
            btn = discord.ui.Button(label=lbl, style=st, row=row, custom_id=f"norosi:FarmView:{cid_sfx}")
            btn.callback = cb
            self.add_item(btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction, f"❌ 이 농장은 **{self.user.display_name}**님의 농장입니다. `/설정` (`🎮 미니게임` ➔ `🌾 세카이 라이프(농장/펫/요리)`)에서 열어주세요!", ephemeral=True
            )
            return False
        return True

    def build_embed(self) -> discord.Embed:
        ov = self.overview
        lu = ov["user"]
        now_ts = time.time()

        plot_lines = []
        ready_cnt = 0
        growing_cnt = 0
        empty_cnt = 0
        for idx, p in enumerate(lu.get("plots") or [], 1):
            sid = p.get("seed_id")
            if not sid or sid not in life_core.SEEDS:
                empty_cnt += 1
                plot_lines.append(f"`{idx}번 밭` 🟫 **비어 있음** *(아래 드롭다운에서 씨앗 심기)*")
            else:
                sp = life_core.SEEDS[sid]
                if float(p.get("ready_at", 0) or 0) <= now_ts:
                    ready_cnt += 1
                else:
                    growing_cnt += 1
                tags = []
                if p.get("watered"):
                    tags.append("💧물줌")
                if p.get("fertilized"):
                    tags.append("✨비료(+1)")
                tag_s = f" [{', '.join(tags)}]" if tags else ""
                plot_lines.append(f"`{idx}번 밭` {sp['emoji']} **{sp['name']}** — {_fmt_countdown(p['ready_at'], now_ts)}{tag_s}")

        seeds_owned = lu.get("seeds") or {}
        seed_txt = ", ".join(f"{life_core.SEEDS[k]['emoji']}{life_core.SEEDS[k]['name']}×{v}" for k, v in seeds_owned.items()) or "없음"
        crops_owned = lu.get("crops") or {}
        crop_txt = ", ".join(f"{life_core.SEEDS[k]['emoji']}{life_core.SEEDS[k]['name']}×{v}" for k, v in crops_owned.items()) or "없음"
        banner = f"\n> {self.status_msg}\n" if self.status_msg else ""

        embed = discord.Embed(
            title=f"🌾 {lu['name']}님의 개인 농장 (농장 Lv.{lu['farm_level']})",
            description=(
                f"• **🪙 낚시 골드:** **`{ov['gold']:,}🪙`**  ·  **💎 크리스탈:** **`{ov['crystals']:,}💎`**  ·  **밭 크기:** `{lu['plot_slots']}/6칸`\n"
                f"• **📊 밭 현황:** 🌾 수확 가능 `{ready_cnt}` · 🌱 성장 중 `{growing_cnt}` · 🟫 빈 밭 `{empty_cnt}`\n"
                f"• **🌱 보유 씨앗:** {seed_txt}\n"
                f"• **🧺 수확 작물(요리 재료/판매):** {crop_txt}"
                f"{banner}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                + "\n".join(plot_lines)
            )[:4096],
            color=0x84CC16,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="수확 작물은 즉시 판매하거나 /설정 ➔ 🎮 미니게임(세카이 라이프 요리)에서 버프 재료로 활용할 수 있습니다.")
        return embed

    async def _on_quick_manage(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        h_ok, h_msg, _ = await asyncio.to_thread(life_core.harvest_plots, self.guild_id, interaction.user.id, interaction.user.display_name)
        w_ok, w_msg = await asyncio.to_thread(life_core.water_farm_plot, self.guild_id, interaction.user.id, None, interaction.user.display_name)
        parts = []
        if h_ok:
            parts.append(h_msg)
        if w_ok:
            parts.append(w_msg)
        self.status_msg = " / ".join(parts) if parts else "ℹ️ 수확하거나 물을 줄 작물이 아직 없습니다."
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_water(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(life_core.water_farm_plot, self.guild_id, interaction.user.id, None, interaction.user.display_name)
        self.status_msg = msg
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    async def _on_fertilize(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(life_core.fertilize_plot, self.guild_id, interaction.user.id, None, interaction.user.display_name)
        self.status_msg = msg
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    async def _on_harvest(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        ok, msg, _ = await asyncio.to_thread(life_core.harvest_plots, self.guild_id, interaction.user.id, interaction.user.display_name)
        self.status_msg = msg
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    async def _on_sell(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(life_core.sell_crops, self.guild_id, interaction.user.id, "all", interaction.user.display_name)
        self.status_msg = msg
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    async def _on_expand(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(life_core.expand_farm_plots, self.guild_id, interaction.user.id, interaction.user.display_name)
        self.status_msg = msg
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    async def _on_refresh(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        self.status_msg = "🔄 농장 성장 상태를 최신으로 갱신했습니다."
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


# ==========================================
# 2. 서버 공동 농장 View
# ==========================================
class CommunityFarmView(core.SafeView):
    def __init__(
        self,
        user: Optional[discord.abc.User] = None,
        guild: Optional[discord.Guild] = None,
        overview: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.guild_id = guild.id if guild else 0
        self.status_msg = ""
        self.overview: Dict[str, Any] = overview if overview is not None else life_core.get_life_overview(
            self.guild_id, user.id if user else 0, user.display_name if user else "주민"
        )

    async def refresh(self):
        uid = self.user.id if self.user else 0
        uname = self.user.display_name if self.user else "주민"
        self.overview = await asyncio.to_thread(life_core.get_life_overview, self.guild_id, uid, uname)

    def build_embed(self) -> discord.Embed:
        gf = self.overview["guild_farm"]
        lvl = gf["level"]
        rem = gf["rem_exp"]
        need = gf["need_exp"]
        pct = min(100, int((rem / max(1, need)) * 100))
        filled = round(pct / 10)
        bar = "🟩" * filled + "⬜" * (10 - filled)

        rare_b = (lvl - 1) * 2
        gold_b = (lvl - 1) * 3
        att_b = lvl * 5 if gf.get("exp", 0) > 0 else 0

        today = core.get_today_str()
        u_key = str(self.user.id if self.user else 0)
        water_today = int((gf.get("water_log", {}).get(today) or {}).get(u_key, 0) or 0)
        claimed_today = bool((gf.get("daily_claimed", {}).get(today) or {}).get(u_key, False))

        contribs = sorted(
            [c for c in (gf.get("contributors") or {}).values() if isinstance(c, dict)],
            key=lambda x: -int(x.get("points", 0) or 0),
        )[:5]
        c_lines = [f"`{i}.` **{c.get('name', '주민')}** — `{c.get('points', 0):,} 기여 EXP`" for i, c in enumerate(contribs, 1)]
        c_val = "\n".join(c_lines) if c_lines else "*(아직 첫 물주기를 기다리고 있습니다!)*"

        gname = self.guild.name if self.guild else "서버"
        banner = f"\n> {self.status_msg}\n" if self.status_msg else ""

        embed = discord.Embed(
            title=f"🌾 {gname} 서버 공동 농장 (Lv.{lvl}/10)",
            description=(
                f"서버 멤버 모두가 함께 가꾸는 협동 농장! 성장할수록 **서버 전체 멤버에게 낚시·출석 버프**가 적용됩니다.\n"
                f"{banner}\n"
                f"• **성장도:** {bar} (`{rem}/{need} EXP` · 총 `{gf['exp']:,}`)\n"
                f"• **✨ 서버 공용 패시브 버프:** 낚시 희귀 `+{rare_b}%` · 판매골드 `+{gold_b}%` · 출석 `+{att_b}💎/일`\n"
                f"• **내 오늘 상태:** 무료 물주기 `{water_today}/3회` · 일일 수확 배당 `{'✅ 수령 완료' if claimed_today else '🎁 수령 가능'}`\n"
                f"• **내 보유 재화:** 🪙 `{self.overview['gold']:,}🪙` · 💎 `{self.overview['crystals']:,}💎`"
            )[:4096],
            color=0x22C55E,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.add_field(name="🏆 공동 농장 기여도 TOP 5", value=c_val, inline=False)
        embed.set_footer(text="물주기(1일 3회 무료 보상 +25🪙/+5💎) · 골드/크리스탈 기부 시 펫 간식 답례!")
        return embed

    @discord.ui.button(label="💧 물주기 (+25🪙·+5💎)", style=discord.ButtonStyle.success, row=0)
    async def btn_water(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(
            life_core.contribute_community_farm, self.guild_id, interaction.user.id, "water", interaction.user.display_name
        )
        self.status_msg = msg
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🪙 500골드 기부 (+🦴1)", style=discord.ButtonStyle.primary, row=0)
    async def btn_gold(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(
            life_core.contribute_community_farm, self.guild_id, interaction.user.id, "gold_donate", interaction.user.display_name
        )
        self.status_msg = msg
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="💎 50크리스탈 기부 (+🦴2)", style=discord.ButtonStyle.primary, row=0)
    async def btn_crystal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(
            life_core.contribute_community_farm, self.guild_id, interaction.user.id, "crystal_donate", interaction.user.display_name
        )
        self.status_msg = msg
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🎁 일일 수확 배당금 수령", style=discord.ButtonStyle.secondary, row=1)
    async def btn_daily(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(
            life_core.claim_community_farm_daily, self.guild_id, interaction.user.id, interaction.user.display_name
        )
        self.status_msg = msg
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=1)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.status_msg = "🔄 공동 농장 현황을 최신으로 갱신했습니다."
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


# ==========================================
# 3. 펫 키우기 View
# ==========================================
class PetSelect(discord.ui.Select):
    def __init__(self, parent_view: "PetCareView", lu: Dict[str, Any]):
        self.parent_view = parent_view
        owned = lu.get("pets") or {}
        eq = lu.get("equipped_pet")
        opts: List[discord.SelectOption] = []
        for pid, pm in life_core.PETS.items():
            if pid == eq:
                st = f"✅ 동반중 Lv.{owned[pid]['level']}"
            elif pid in owned:
                st = f"📦 보유 Lv.{owned[pid]['level']} (장착)"
            else:
                unit = "💎" if pm["currency"] == "crystal" else "🪙"
                st = f"🛒 {pm['price']:,}{unit} 입양"
            opts.append(discord.SelectOption(
                label=f"{pm['name']} [{pm['rarity']}] ({st})"[:95],
                value=pid,
                description=pm["specialty"][:95],
                emoji=pm["emoji"],
                default=(pid == eq),
            ))
        super().__init__(
            placeholder="🐾 입양하거나 동반 장착할 펫 선택...",
            min_values=1,
            max_values=1,
            options=opts[:25],
            row=0,
            custom_id="norosi:PetCareView:pet_select",
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        await core.safe_defer(interaction)
        pid = self.values[0]
        ok, msg = await asyncio.to_thread(
            life_core.adopt_pet, pv.guild_id, interaction.user.id, pid, interaction.user.display_name
        )
        pv.status_msg = msg
        await pv.refresh()
        await core.safe_edit_response(interaction, embed=pv.build_embed(), view=pv)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)


class PetCareView(core.SafeView):
    def __init__(
        self,
        user: Optional[discord.abc.User] = None,
        guild_id: int = 0,
        overview: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.status_msg = ""
        self.overview: Dict[str, Any] = overview if overview is not None else life_core.get_life_overview(
            self.guild_id, user.id if user else 0, user.display_name if user else "주민"
        )
        self._rebuild()

    async def refresh(self):
        uid = self.user.id if self.user else 0
        uname = self.user.display_name if self.user else "주민"
        self.overview = await asyncio.to_thread(life_core.get_life_overview, self.guild_id, uid, uname)
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        lu = self.overview["user"]
        self.add_item(PetSelect(self, lu))

        btns = [
            ("🦴 간식 먹이기 (+35 EXP)", discord.ButtonStyle.success, 1, "feed_food", self._on_feed_food),
            ("🐟 생선 먹이기 (★1~2)", discord.ButtonStyle.primary, 1, "feed_fish", self._on_feed_fish),
            ("🎾 놀아주기 (일일 5회)", discord.ButtonStyle.success, 1, "play", self._on_play),
            ("🛒 간식 5개 구매 (225🪙)", discord.ButtonStyle.secondary, 2, "buy_food", self._on_buy_food),
            ("🔄 새로고침", discord.ButtonStyle.secondary, 2, "refresh", self._on_refresh),
        ]
        for lbl, st, r, cid_s, cb in btns:
            b = discord.ui.Button(label=lbl, style=st, row=r, custom_id=f"norosi:PetCareView:{cid_s}")
            b.callback = cb
            self.add_item(b)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인 펫만 관리할 수 있습니다. `/설정` (`👤 개인` ➔ `🌾 내 농장·펫·요리·버프`)에서 열어주세요!", ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        ov = self.overview
        lu = ov["user"]
        buffs = ov["buffs"]
        eq_pet = buffs.get("pet")
        cookable = ov.get("cookable_r1", 0) + ov.get("cookable_r2", 0)

        if eq_pet:
            eq_txt = (
                f"{eq_pet['emoji']} **{eq_pet['name']}** (`{eq_pet['rarity']}` · **Lv.{eq_pet['level']}/20** · 친밀도 `{eq_pet['intimacy']}`)\n"
                f"└ 패시브: 쿨타임 `-{eq_pet['cd_reduce']:.2f}초` · 희귀 `+{int(eq_pet['rare_bonus']*100)}%` · "
                f"골드 `+{int(eq_pet['gold_bonus']*100)}%` · 월척 `+{int(eq_pet['trophy_bonus']*100)}%` · 출석 `+{eq_pet['att_bonus']}💎`"
            )
        else:
            eq_txt = "*(동반 중인 펫이 없습니다! 위 드롭다운에서 600🪙 고등어 냥이부터 입양해 보세요!)*"

        owned_lines = []
        for pid, pu in (lu.get("pets") or {}).items():
            pm = life_core.PETS.get(pid)
            if pm:
                mark = " ✅" if pid == lu.get("equipped_pet") else ""
                owned_lines.append(f"{pm['emoji']} **{pm['name']}** Lv.{pu['level']}{mark}")
        owned_str = " · ".join(owned_lines) if owned_lines else "없음"
        banner = f"\n> {self.status_msg}\n" if self.status_msg else ""

        embed = discord.Embed(
            title=f"🐾 {lu['name']}님의 펫 하우스 & 동반자 버프",
            description=(
                f"• **🪙 낚시 골드:** `{ov['gold']:,}🪙`  ·  **💎 크리스탈:** `{ov['crystals']:,}💎`\n"
                f"• **🦴 펫 간식:** `{lu['pet_food']:,}개`  ·  **🐟 먹이 가능 생선(★1~2 미잠금):** `{cookable:,}마리`\n"
                f"{banner}\n"
                f"**🌟 현재 동반 중인 펫**\n{eq_txt}\n\n"
                f"**📦 보유 펫 ({len(lu.get('pets') or {})}/{len(life_core.PETS)})**\n{owned_str}"
            )[:4096],
            color=0xEC4899,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="동반 펫은 낚시 출조 쿨타임·희귀 확률·판매가와 매일 출석 보너스에 실시간 적용됩니다!")
        return embed

    async def _on_feed_food(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(life_core.feed_pet, self.guild_id, interaction.user.id, None, "pet_food", interaction.user.display_name)
        self.status_msg = msg
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    async def _on_feed_fish(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(life_core.feed_pet, self.guild_id, interaction.user.id, None, "fish", interaction.user.display_name)
        self.status_msg = msg
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    async def _on_play(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(life_core.play_pet, self.guild_id, interaction.user.id, None, interaction.user.display_name)
        self.status_msg = msg
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    async def _on_buy_food(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(life_core.buy_pet_food, self.guild_id, interaction.user.id, 5, interaction.user.display_name)
        self.status_msg = msg
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    async def _on_refresh(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        self.status_msg = "🔄 펫 정보를 갱신했습니다."
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


# ==========================================
# 4. 생선 요리 & 버프 View
# ==========================================
class CookRecipeSelect(discord.ui.Select):
    def __init__(self, parent_view: "CookingView"):
        self.parent_view = parent_view
        opts: List[discord.SelectOption] = []
        for rid, rec in life_core.RECIPES.items():
            opts.append(discord.SelectOption(
                label=f"🍳 {rec['name']} 조리하기"[:95],
                value=rid,
                description=rec["desc"][:95],
                emoji=rec["emoji"],
            ))
        super().__init__(
            placeholder="🍳 조리할 생선 요리/디저트 레시피 선택...",
            min_values=1,
            max_values=1,
            options=opts[:25],
            row=0,
            custom_id="norosi:CookingView:cook_select",
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        await core.safe_defer(interaction)
        rid = self.values[0]
        ok, msg = await asyncio.to_thread(life_core.cook_recipe, pv.guild_id, interaction.user.id, rid, 1, interaction.user.display_name)
        pv.status_msg = msg
        await pv.refresh()
        await core.safe_edit_response(interaction, embed=pv.build_embed(), view=pv)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)


class EatDishSelect(discord.ui.Select):
    def __init__(self, parent_view: "CookingView", dishes: Dict[str, int]):
        self.parent_view = parent_view
        opts: List[discord.SelectOption] = []
        for rid, cnt in dishes.items():
            rec = life_core.RECIPES.get(rid)
            if rec and cnt > 0:
                opts.append(discord.SelectOption(
                    label=f"🍽️ {rec['name']} 먹기 (보유 {cnt}개)"[:95],
                    value=rid,
                    description=rec["desc"][:95],
                    emoji=rec["emoji"],
                ))
        if not opts:
            opts.append(discord.SelectOption(
                label="보유 중인 완성 요리가 없습니다 (위에서 먼저 조리하세요)",
                value="__none__",
                description="조리 완료 후 여기서 먹으면 즉시 버프가 적용됩니다",
                emoji="🍽️",
            ))
        super().__init__(
            placeholder="🍽️ 먹어서 버프를 활성화할 완성 요리 선택...",
            min_values=1,
            max_values=1,
            options=opts[:25],
            row=1,
            custom_id="norosi:CookingView:eat_select",
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        rid = self.values[0]
        if rid == "__none__":
            await core.safe_send_response(interaction, "🍳 먼저 상단 레시피에서 요리를 조리해 주세요!", ephemeral=True)
            return
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(life_core.consume_dish, pv.guild_id, interaction.user.id, rid, interaction.user.display_name)
        pv.status_msg = msg
        await pv.refresh()
        await core.safe_edit_response(interaction, embed=pv.build_embed(), view=pv)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)


class CookingView(core.SafeView):
    def __init__(
        self,
        user: Optional[discord.abc.User] = None,
        guild_id: int = 0,
        overview: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.status_msg = ""
        self.overview: Dict[str, Any] = overview if overview is not None else life_core.get_life_overview(
            self.guild_id, user.id if user else 0, user.display_name if user else "주민"
        )
        self._rebuild()

    async def refresh(self):
        uid = self.user.id if self.user else 0
        uname = self.user.display_name if self.user else "주민"
        self.overview = await asyncio.to_thread(life_core.get_life_overview, self.guild_id, uid, uname)
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        lu = self.overview["user"]
        self.add_item(CookRecipeSelect(self))
        self.add_item(EatDishSelect(self, lu.get("dishes") or {}))
        btn_ref = discord.ui.Button(label="🔄 버프·재료 새로고침", style=discord.ButtonStyle.secondary, row=2, custom_id="norosi:CookingView:refresh")
        btn_ref.callback = self._on_refresh
        self.add_item(btn_ref)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인 주방만 이용할 수 있습니다. `/설정` (`👤 개인` ➔ `🌾 내 농장·펫·요리·버프`)에서 열어주세요!", ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        ov = self.overview
        lu = ov["user"]
        buffs = ov["buffs"]
        r1, r2 = ov.get("cookable_r1", 0), ov.get("cookable_r2", 0)
        crops_owned = lu.get("crops") or {}
        crop_txt = ", ".join(f"{life_core.SEEDS[k]['emoji']}{life_core.SEEDS[k]['name']}×{v}" for k, v in crops_owned.items()) or "없음"
        dishes_owned = lu.get("dishes") or {}
        dish_txt = ", ".join(f"{life_core.RECIPES[k]['emoji']}{life_core.RECIPES[k]['name']}×{v}" for k, v in dishes_owned.items()) or "없음"

        recipe_lines = [f"• {r['emoji']} **{r['name']}** — {r['desc']}" for r in life_core.RECIPES.values()]
        active_lines = buffs.get("summary_lines") or ["*(현재 적용 중인 생활·요리 버프가 없습니다)*"]
        banner = f"\n> {self.status_msg}\n" if self.status_msg else ""

        embed = discord.Embed(
            title=f"🍳 {lu['name']}님의 세카이 주방 & 통합 생활 버프",
            description=(
                f"낚시 가방 속 **미잠금 ★1~★2 물고기**와 **수확 농작물**을 요리해 낚시·출석 버프를 획득하세요!\n"
                f"• **🐟 요리 가능 물고기(미잠금):** ★1 `{r1}마리` · ★2 `{r2}마리` *(★3~★5·잠금 어종은 보호됨)*\n"
                f"• **🌾 보유 농작물:** {crop_txt}\n"
                f"• **🍱 보관 중인 요리:** {dish_txt}"
                f"{banner}\n"
                "**📜 레시피 카탈로그**\n" + "\n".join(recipe_lines)
            )[:4096],
            color=0xF97316,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.add_field(
            name="⚡ 현재 활성 통합 버프 (요리 + 펫 + 서버 공동 농장)",
            value="\n".join(f"• {ln}" for ln in active_lines)
            + f"\n└ **합산:** 쿨타임 `-{buffs['cooldown_reduce']:.2f}초` · 희귀 `+{int(buffs['rare_bonus']*100)}%` · "
            f"크기 `+{int(buffs['size_bonus']*100)}%` · 월척 `+{int(buffs['trophy_bonus']*100)}%` · "
            f"골드 `+{int(buffs['gold_bonus']*100)}%` · 출석 `+{buffs['attendance_total_bonus']}💎`",
            inline=False,
        )
        embed.set_footer(text="요리는 최대 3종까지 동시 버프 가능 · 파르페 먹으면 다음 출석체크 시 +80💎 자동 지급!")
        return embed

    async def _on_refresh(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        self.status_msg = "🔄 요리·재료·버프 현황을 갱신했습니다."
        await self.refresh()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


# ==========================================
# 5. 생활 통합 대시보드 View
# ==========================================
class LifeDashboardView(core.SafeView):
    def __init__(
        self,
        user: Optional[discord.abc.User] = None,
        guild: Optional[discord.Guild] = None,
        overview: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.guild_id = guild.id if guild else 0
        self.overview: Dict[str, Any] = overview if overview is not None else life_core.get_life_overview(
            self.guild_id, user.id if user else 0, user.display_name if user else "주민"
        )

    def build_embed(self) -> discord.Embed:
        ov = self.overview
        lu = ov["user"]
        gf = ov["guild_farm"]
        buffs = ov["buffs"]
        now_ts = time.time()

        ready_cnt = sum(1 for p in (lu.get("plots") or []) if p.get("seed_id") and p.get("ready_at", 0) <= now_ts)
        growing_cnt = sum(1 for p in (lu.get("plots") or []) if p.get("seed_id") and p.get("ready_at", 0) > now_ts)
        pet = buffs.get("pet")
        pet_str = f"{pet['emoji']} **{pet['name']} Lv.{pet['level']}**" if pet else "미장착 (`/설정` ➔ `🐾 내 펫 돌보기`)"

        embed = discord.Embed(
            title=f"🌿 {lu['name']}님의 생활 컨텐츠 종합 허브",
            description=(
                "개인 농장, 서버 공동 농장, 동반 펫, 생선 요리로 낚시와 일일 출석 보상을 극대화하세요!\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **💰 보유 재화:** 🪙 `{ov['gold']:,}🪙` · 💎 `{ov['crystals']:,}💎`\n"
                f"• **🌾 개인 농장 (Lv.{lu['farm_level']}):** 밭 `{lu['plot_slots']}칸` (수확 가능 `{ready_cnt}` · 성장중 `{growing_cnt}`)\n"
                f"• **🤝 서버 공동 농장 (Lv.{gf['level']}/10):** 공용 희귀 `+{(gf['level']-1)*2}%` · 골드 `+{(gf['level']-1)*3}%` · 출석 `+{gf['level']*5 if gf['exp']>0 else 0}💎`\n"
                f"• **🐾 동반 펫:** {pet_str} · 간식 `{lu['pet_food']}개`\n"
                f"• **🍳 요리 & 활성 버프:** 요리 `{sum((lu.get('dishes') or {}).values())}개` · 활성 버프 `{len(buffs.get('active_dishes') or [])}/3종`\n"
                f"• **⚡ 현재 통합 보정:** 쿨타임 `-{buffs['cooldown_reduce']:.2f}초` · 희귀 `+{int(buffs['rare_bonus']*100)}%` · 골드 `+{int(buffs['gold_bonus']*100)}%` · 출석 `+{buffs['attendance_total_bonus']}💎`\n"
                "━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=0x10B981,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="아래 버튼으로 개인 농장 · 공동 농장 · 펫 하우스 · 생선 요리를 즉시 열어보세요!")
        return embed

    @discord.ui.button(label="🌾 개인 농장", style=discord.ButtonStyle.success, row=0)
    async def btn_farm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ov = await asyncio.to_thread(
            life_core.get_life_overview, self.guild_id, interaction.user.id, interaction.user.display_name
        )
        v = FarmView(interaction.user, self.guild_id, overview=ov)
        msg = await interaction.followup.send(embed=v.build_embed(), view=v, wait=True)
        v.message = msg

    @discord.ui.button(label="🤝 서버 공동농장", style=discord.ButtonStyle.primary, row=0)
    async def btn_gfarm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        gid = interaction.guild.id if interaction.guild else self.guild_id
        ov = await asyncio.to_thread(
            life_core.get_life_overview, gid, interaction.user.id, interaction.user.display_name
        )
        v = CommunityFarmView(interaction.user, interaction.guild, overview=ov)
        msg = await interaction.followup.send(embed=v.build_embed(), view=v, wait=True)
        v.message = msg

    @discord.ui.button(label="🐾 펫 키우기", style=discord.ButtonStyle.primary, row=0)
    async def btn_pet(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ov = await asyncio.to_thread(
            life_core.get_life_overview, self.guild_id, interaction.user.id, interaction.user.display_name
        )
        v = PetCareView(interaction.user, self.guild_id, overview=ov)
        msg = await interaction.followup.send(embed=v.build_embed(), view=v, wait=True)
        v.message = msg

    @discord.ui.button(label="🍳 생선 요리 & 버프", style=discord.ButtonStyle.secondary, row=0)
    async def btn_cook(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ov = await asyncio.to_thread(
            life_core.get_life_overview, self.guild_id, interaction.user.id, interaction.user.display_name
        )
        v = CookingView(interaction.user, self.guild_id, overview=ov)
        msg = await interaction.followup.send(embed=v.build_embed(), view=v, wait=True)
        v.message = msg

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        target = self.user or interaction.user
        self.overview = await asyncio.to_thread(
            life_core.get_life_overview, self.guild_id, target.id, target.display_name
        )
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


# ==========================================
# 6. Cog 등록 (/생활 그룹 + !단축어)
# ==========================================
class LifeGroupCog(commands.GroupCog, name="생활", description="🌾 개인 농장 · 서버 공동 농장 · 펫 키우기 · 생선 요리 & 낚시/출석 버프"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="대시보드", description="🌿 농장 · 공동농장 · 펫 · 요리 통합 생활 현황판을 엽니다.")
    async def life_dashboard(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        ov = await asyncio.to_thread(
            life_core.get_life_overview, interaction.guild_id or 0, interaction.user.id, interaction.user.display_name
        )
        view = LifeDashboardView(interaction.user, interaction.guild, overview=ov)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="농장", description="🌾 나만의 개인 밭에 씨앗을 심고 물주기·비료·수확·판매를 진행합니다.")
    async def life_farm(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        gid = interaction.guild_id or 0
        ov = await asyncio.to_thread(
            life_core.get_life_overview, gid, interaction.user.id, interaction.user.display_name
        )
        view = FarmView(interaction.user, gid, overview=ov)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="공동농장", description="🤝 서버 전체 유저와 함께 가꾸는 서버 공동 농장(Lv.1~10 · 일일 배당 · 공용 버프)을 엽니다.")
    async def life_guild_farm(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        ov = await asyncio.to_thread(
            life_core.get_life_overview, interaction.guild_id or 0, interaction.user.id, interaction.user.display_name
        )
        view = CommunityFarmView(interaction.user, interaction.guild, overview=ov)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="펫", description="🐾 6종의 귀여운 펫을 입양·육성하고 낚시 및 출석체크 패시브 버프를 받습니다.")
    async def life_pet(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        gid = interaction.guild_id or 0
        ov = await asyncio.to_thread(
            life_core.get_life_overview, gid, interaction.user.id, interaction.user.display_name
        )
        view = PetCareView(interaction.user, gid, overview=ov)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="요리", description="🍳 미잠금 ★1~2 물고기와 농작물로 요리를 만들어 낚시/출석 버프를 얻습니다.")
    async def life_cook(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        gid = interaction.guild_id or 0
        ov = await asyncio.to_thread(
            life_core.get_life_overview, gid, interaction.user.id, interaction.user.display_name
        )
        view = CookingView(interaction.user, gid, overview=ov)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="버프", description="⚡ 현재 나에게 적용 중인 펫 · 공동 농장 · 요리 통합 버프를 확인합니다.")
    async def life_buffs(self, interaction: discord.Interaction):
        await core.safe_defer(interaction, ephemeral=True)
        ov = await asyncio.to_thread(
            life_core.get_life_overview, interaction.guild_id or 0, interaction.user.id, interaction.user.display_name
        )
        buffs = ov["buffs"]
        lines = buffs.get("summary_lines") or ["*(현재 활성화된 생활 버프가 없습니다. 펫을 입양하거나 요리를 먹어보세요!)*"]
        embed = discord.Embed(
            title=f"⚡ {interaction.user.display_name}님의 실시간 생활 통합 버프",
            description="\n".join(f"• {ln}" for ln in lines)
            + f"\n\n**📊 합산 효과**\n"
            f"• 낚시 출조 쿨타임: **`-{buffs['cooldown_reduce']:.2f}초`**\n"
            f"• 희귀 어종 확률: **`+{int(buffs['rare_bonus']*100)}%`**  ·  체장/무게: **`+{int(buffs['size_bonus']*100)}%`**\n"
            f"• 월척 확률: **`+{int(buffs['trophy_bonus']*100)}%`**  ·  판매 골드: **`+{int(buffs['gold_bonus']*100)}%`**\n"
            f"• 출석체크 보너스: **`+{buffs['attendance_total_bonus']:,}💎`** *(펫+공동농장 `{buffs['attendance_passive_bonus']}💎` + 요리 `{buffs['attendance_dish_bonus']}💎`)*",
            color=0xF59E0B,
            timestamp=datetime.datetime.now(core.KST),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


class LifeStandaloneCog(commands.Cog):
    """!농장 · !공동농장 · !펫 · !요리 · !버프 접두사 단축어 Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="농장", aliases=["farm"])
    async def prefix_farm(self, ctx: commands.Context):
        gid = ctx.guild.id if ctx.guild else 0
        ov = await asyncio.to_thread(life_core.get_life_overview, gid, ctx.author.id, ctx.author.display_name)
        v = FarmView(ctx.author, gid, overview=ov)
        msg = await ctx.send(embed=v.build_embed(), view=v)
        v.message = msg

    @commands.command(name="공동농장", aliases=["길드농장", "communityfarm"])
    async def prefix_community_farm(self, ctx: commands.Context):
        gid = ctx.guild.id if ctx.guild else 0
        ov = await asyncio.to_thread(life_core.get_life_overview, gid, ctx.author.id, ctx.author.display_name)
        v = CommunityFarmView(ctx.author, ctx.guild, overview=ov)
        msg = await ctx.send(embed=v.build_embed(), view=v)
        v.message = msg

    @commands.command(name="펫", aliases=["pet"])
    async def prefix_pet(self, ctx: commands.Context):
        gid = ctx.guild.id if ctx.guild else 0
        ov = await asyncio.to_thread(life_core.get_life_overview, gid, ctx.author.id, ctx.author.display_name)
        v = PetCareView(ctx.author, gid, overview=ov)
        msg = await ctx.send(embed=v.build_embed(), view=v)
        v.message = msg

    @commands.command(name="요리", aliases=["cook", "버프"])
    async def prefix_cook(self, ctx: commands.Context):
        gid = ctx.guild.id if ctx.guild else 0
        ov = await asyncio.to_thread(life_core.get_life_overview, gid, ctx.author.id, ctx.author.display_name)
        v = CookingView(ctx.author, gid, overview=ov)
        msg = await ctx.send(embed=v.build_embed(), view=v)
        v.message = msg


async def setup(bot: commands.Bot):
    await bot.add_cog(LifeGroupCog(bot))
    await bot.add_cog(LifeStandaloneCog(bot))
