import io
import copy
import time
import asyncio
import datetime
import discord
from typing import Optional
from discord import app_commands
from discord.ext import commands
import core


# ==========================================
# 프로세카 UI 클래스 (연속 뽑기 / 카드 잠금 / 중복 변환 / 각성 전환 / 확률표 / 보관함 / 교환)
# ==========================================
def build_gacha_pull_embed(drawn: list, pickup_cfg: dict, pull_count: int, user: discord.User = None):
    has_4star = any(c["star_num"] >= 4 for c in drawn)
    embed_color = discord.Color.from_rgb(255, 105, 180) if has_4star else discord.Color.from_rgb(0, 204, 221)

    p_unit = pickup_cfg.get("unit") or "없음"
    p_char = pickup_cfg.get("character") or "없음"

    lines = []
    for idx, c in enumerate(drawn, start=1):
        p_mark = "🎯**[픽업!]** " if c.get("is_pickup") else ""
        new_mark = "✨**[NEW!]** " if c.get("is_new") else ""
        
        # 성급별 시각적 이모지
        s_num = c.get("star_num", 2)
        r_type = c.get("rarity_type", "")
        if r_type == "rarity_birthday":
            rarity_badge = "🎂 [Birthday]"
        elif s_num >= 4:
            rarity_badge = "🌟 ★★★★"
        elif s_num == 3:
            rarity_badge = "💫 ★★★"
        elif s_num == 2:
            rarity_badge = "⭐ ★★"
        else:
            rarity_badge = "🔹 ★"

        unit_str = f"{c['unit']}" + (f" ({c['support_unit']})" if c.get("support_unit") else "")
        limit_badge = f"`[{c['limit_label']}]` " if c.get("limit_label") else ""
        
        cos = core.get_costume_for_card(c.get("id"))
        cos_badge = f" · 👗`[{cos['name']}]`" if cos else ""
        card_title = f"{p_mark}{new_mark}{limit_badge}**{rarity_badge} [{c['prefix']}] {c['char_name']}**"
        card_sub = f"   └ 🏷️ `{unit_str}` · `{c['attr']}` · 확률 `{c['prob']:.4f}%`{cos_badge}"
        lines.append(f"**{idx:02d}.** {card_title}\n{card_sub}")

    r4_cnt = sum(1 for c in drawn if c["rarity_type"] == "rarity_4")
    rb_cnt = sum(1 for c in drawn if c["rarity_type"] == "rarity_birthday")
    r3_cnt = sum(1 for c in drawn if c["rarity_type"] == "rarity_3")
    r2_cnt = sum(1 for c in drawn if c["rarity_type"] == "rarity_2")
    r1_cnt = sum(1 for c in drawn if c["rarity_type"] == "rarity_1")
    new_cnt = sum(1 for c in drawn if c.get("is_new"))

    summary_parts = []
    if r4_cnt > 0:
        summary_parts.append(f"🌟 ★4 `{r4_cnt}장`")
    if rb_cnt > 0:
        summary_parts.append(f"🎂 생일 `{rb_cnt}장`")
    if r3_cnt > 0:
        summary_parts.append(f"💫 ★3 `{r3_cnt}장`")
    if r2_cnt > 0:
        summary_parts.append(f"⭐ ★2 `{r2_cnt}장`")
    if r1_cnt > 0:
        summary_parts.append(f"🔹 ★1 `{r1_cnt}장`")
    if new_cnt > 0:
        summary_parts.append(f"✨ 신규 획득 `{new_cnt}장`")

    summary_line = f"📊 **뽑기 통계:** {' · '.join(summary_parts)}"

    title_str = "🌈 프로세카 10회 뽑기 (10연차) 결과!" if pull_count == 10 else "🎵 프로세카 1회 뽑기 (단차) 결과!"
    if has_4star:
        title_str = "🎉✨ " + title_str + " (최고 등급 카드 등장!)"

    embed = discord.Embed(
        title=title_str,
        description="\n\n".join(lines) + f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n{summary_line}",
        color=embed_color,
        timestamp=datetime.datetime.now(core.KST)
    )

    if user:
        author_icon = user.display_avatar.url if hasattr(user, "display_avatar") else None
        embed.set_author(name=f"{user.display_name}님의 가챠 결과", icon_url=author_icon)

    embed.set_footer(text=f"적용 픽업: 유닛({p_unit}) / 캐릭터({p_char}) • 하단 버튼으로 즉시 재뽑기 및 보관함 관리")
    return embed, has_4star


async def send_gacha_pull_result(interaction: discord.Interaction, drawn: list, pickup_cfg: dict, pull_count: int, view: discord.ui.View):
    """뽑기 결과 전송: ★4(또는 생일) 카드가 1장 이상 등장하면 모든 고성급 카드의 공식 일러스트와 카드 정보를 개별 임베드로 첨부하여 전송합니다."""
    embed, has_4star = build_gacha_pull_embed(drawn, pickup_cfg, pull_count, user=interaction.user)
    if not has_4star:
        await interaction.followup.send(embed=embed, view=view)
        return

    high_cards = [c for c in drawn if c.get("star_num", 0) >= 4]
    total_high = len(high_cards)
    # 디스코드 메시지당 임베드는 최대 10개 (결과 요약 1개 + 카드 일러스트 최대 9개)
    results = await asyncio.gather(*(
        asyncio.to_thread(core.fetch_proseka_card_image_bytes, c, "auto")
        for c in high_cards[:9]
    ))

    embeds = [embed]
    files = []
    for idx, (c, (img_bytes, filename)) in enumerate(zip(high_cards[:9], results), start=1):
        card_badge = "🎂 [Birthday]" if c.get("rarity_type") == "rarity_birthday" else "🌟 ★4"
        pickup_txt = "🎯 **[픽업!]** " if c.get("is_pickup") else ""
        new_txt = "✨ **[NEW!]** " if c.get("is_new") else ""
        limit_txt = f"`[{c.get('limit_label', '통상')}]` " if c.get("limit_label") else ""
        order_txt = f"({idx}/{total_high}) " if total_high > 1 else ""
        unit_str = f"{c.get('unit', '')}" + (f" ({c.get('support_unit')})" if c.get("support_unit") else "")

        card_title = f"{pickup_txt}{new_txt}{card_badge} {order_txt}{limit_txt}[{c.get('prefix', '')}] {c.get('char_name', '')}"
        desc_lines = [
            f"• 🏷️ **유닛:** `{unit_str}`  ·  ✨ **속성:** {c.get('attr', '✨')}  ·  📊 **확률:** `{c.get('prob', 0):.4f}%`"
        ]
        if c.get("skill_name"):
            desc_lines.append(f"• ⚡ **스킬:** `{c.get('skill_name')}`")
        cos = core.get_costume_for_card(c.get("id"))
        if cos:
            desc_lines.append(f"• 👗 **3D 의상 획득:** `[{cos['name']}]` (의상실에서 캐릭터 착용 가능!)")

        card_embed = discord.Embed(
            title=card_title[:256],
            description="\n".join(desc_lines),
            color=discord.Color.from_rgb(255, 105, 180) if c.get("rarity_type") == "rarity_birthday" else discord.Color.from_rgb(255, 215, 0),
            timestamp=datetime.datetime.now(core.KST)
        )
        card_embed.set_footer(text=f"프로세카 ★4 공식 일러스트  •  {c.get('char_name', '')} [{c.get('prefix', '')}]")

        if img_bytes and filename:
            safe_fn = f"pull_{idx}_{filename}"
            files.append(discord.File(io.BytesIO(img_bytes), filename=safe_fn))
            card_embed.set_image(url=f"attachment://{safe_fn}")
        else:
            fallback_url = core.get_proseka_card_image_url(c, "auto")
            card_embed.set_image(url=fallback_url)
        embeds.append(card_embed)

    if files:
        await interaction.followup.send(embeds=embeds, files=files, view=view)
    else:
        await interaction.followup.send(embeds=embeds, view=view)


class DuplicateConvertConfirmView(core.SafeView):
    """2장 이상 중복 보유한 카드(잠금 제외)를 크리스탈로 일괄 변환하는 확인 뷰"""
    def __init__(
        self,
        guild_id: int,
        user: discord.User,
        preview_info: dict,
        parent_inventory_view=None,
        parent_inventory_message=None,
        parent_menu_view=None,
        parent_menu_message=None
    ):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.user = user
        self.preview_info = preview_info
        self.parent_inventory_view = parent_inventory_view
        self.parent_inventory_message = parent_inventory_message
        self.parent_menu_view = parent_menu_view
        self.parent_menu_message = parent_menu_message
        self.convert_btn.disabled = (preview_info.get("total_excess_cards", 0) <= 0)

    def build_preview_embed(self):
        tot_excess = self.preview_info.get("total_excess_cards", 0)
        tot_crystals = self.preview_info.get("total_crystals", 0)
        locked_skip = self.preview_info.get("locked_skipped", 0)

        embed = discord.Embed(
            title=f"💎 {self.user.display_name}님의 중복 카드 크리스탈 변환소",
            color=discord.Color.from_rgb(0, 204, 221) if tot_excess > 0 else discord.Color.dark_grey(),
            timestamp=datetime.datetime.now(core.KST)
        )

        if tot_excess <= 0:
            skip_note = f"\n*(🔒 잠금 보호된 중복 카드 `{locked_skip}장`은 변환 대상에서 제외되었습니다)*" if locked_skip > 0 else ""
            embed.description = (
                "📭 현재 변환 가능한 **중복 카드(2장 이상 보유)**가 없습니다!\n"
                "모든 카드의 원본 1장은 도감 수집률과 덱 유지를 위해 안전하게 보존됩니다."
                f"{skip_note}"
            )
            return embed

        r_lines = []
        for r_key in ("rarity_4", "rarity_birthday", "rarity_3", "rarity_2", "rarity_1"):
            r_data = self.preview_info["by_rarity"].get(r_key, {})
            if r_data.get("count", 0) > 0:
                r_lines.append(f"• **{r_data['label']}** : 초과분 `{r_data['count']:,}장` ➔ **`+{r_data['crystals']:,} 💎`**")

        lock_line = f"\n🔒 **잠금 보호됨:** 잠긴 카드 초과분 `{locked_skip:,}장`은 변환되지 않고 안전하게 유지됩니다." if locked_skip > 0 else ""
        embed.description = (
            "보유 수량이 `2장 이상`인 카드에서 **원본 1장은 남기고** 초과 중복분만 크리스탈로 변환합니다.\n"
            "*(도감 수집률과 5인 유닛 덱 편성은 절대 줄어들지 않습니다!)*\n\n"
            + "\n".join(r_lines)
            + f"\n\n✨ **총 변환 대상:** 중복 카드 **`{tot_excess:,}장`** ➔ 예상 획득 **`+{tot_crystals:,} 크리스탈`**"
            + lock_line
        )
        embed.set_footer(text="아래 [💎 중복 카드 일괄 변환 확정] 버튼을 누르면 즉시 크리스탈이 지급됩니다.")
        return embed

    @discord.ui.button(label="💎 중복 카드 일괄 변환 확정", style=discord.ButtonStyle.success)
    async def convert_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인만 변환을 실행할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        res = await asyncio.to_thread(core.execute_duplicate_card_conversion, self.guild_id, self.user.id)
        if res["converted_count"] <= 0:
            await interaction.edit_original_response(
                embed=discord.Embed(title="ℹ️ 변환할 중복 카드가 없습니다.", color=discord.Color.dark_grey()),
                view=None
            )
            return

        # 열려 있는 /내캐릭터 보관함 뷰가 있다면 실시간으로 수량을 1장으로 갱신하고 원본 메시지 업데이트
        if self.parent_inventory_view:
            for c in self.parent_inventory_view.cards:
                if not c.get("locked", False) and c.get("count", 1) > 1:
                    c["count"] = 1
            if self.parent_inventory_message:
                try:
                    await self.parent_inventory_message.edit(
                        embed=self.parent_inventory_view.build_embed(),
                        view=self.parent_inventory_view
                    )
                except Exception:
                    pass

        # 열려 있는 /메뉴 올인원 리모컨 뷰가 있다면 최신 데이터로 갱신
        if self.parent_menu_view:
            self.parent_menu_view.data = await asyncio.to_thread(core.load_data)
            if self.parent_menu_message:
                try:
                    await self.parent_menu_message.edit(
                        embed=self.parent_menu_view.build_embed(),
                        view=self.parent_menu_view
                    )
                except Exception:
                    pass

        detail_preview = "\n".join(res["details"][:8])
        if len(res["details"]) > 8:
            detail_preview += f"\n*...외 {len(res['details']) - 8}종 변환 완료*"

        done_embed = discord.Embed(
            title="✨ 중복 카드 크리스탈 변환 완료!",
            description=(
                f"🎉 총 **`{res['converted_count']:,}장`**의 초과 중복 카드를 크리스탈로 변환했습니다!\n"
                "*(모든 종류의 원본 카드 1장과 🔒잠금 카드는 안전하게 유지되었습니다)*\n\n"
                f"💎 **획득 크리스탈:** **`+{res['gained_crystals']:,}개`** (현재 총 보유: **`{res['current_crystals']:,}개`**)\n\n"
                f"📋 **변환 내역 요약**\n{detail_preview}"
            ),
            color=discord.Color.from_rgb(255, 105, 180),
            timestamp=datetime.datetime.now(core.KST)
        )
        await interaction.edit_original_response(embed=done_embed, view=None)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인만 취소할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=discord.Embed(title="✅ 중복 카드 변환이 취소되었습니다.", color=discord.Color.blue()),
            view=None
        )


# 모든 뽑기 경로(슬래시 명령어, 단차/10연차 버튼, 재뽑기 버튼)에서 예외 없이 공유되는 엄격한 5초 쿨타임
GACHA_GLOBAL_COOLDOWN: dict[int, float] = {}
GACHA_COOLDOWN_SECONDS: float = 5.0


def check_and_update_gacha_cooldown(user_id: int) -> tuple[bool, float]:
    """모든 뽑기 경로에서 예외 없이 5초 쿨타임을 강제 검사하고 갱신합니다."""
    now = time.time()
    last_t = GACHA_GLOBAL_COOLDOWN.get(user_id, 0.0)
    elapsed = now - last_t
    if elapsed < GACHA_COOLDOWN_SECONDS:
        rem = GACHA_COOLDOWN_SECONDS - elapsed
        return False, rem
    GACHA_GLOBAL_COOLDOWN[user_id] = now
    return True, 0.0


class GachaPullAgainView(core.SafeView):
    """가챠 결과 화면에서 명령어 재입력 없이 바로 1회/10회 더 뽑기를 하거나 보관함을 여는 뷰"""

    def __init__(self, user: discord.User):
        super().__init__(timeout=600)
        self.user = user

    async def _handle_repull(self, interaction: discord.Interaction, pull_count: int):
        can_pull, rem = check_and_update_gacha_cooldown(interaction.user.id)
        if not can_pull:
            await core.safe_send_response(
                interaction,
                content=f"⏳ **봇의 원활한 서비스를 위해, 뽑기 쿨타임입니다!** `{rem:.1f}초` 후에 다시 눌러주세요.",
                ephemeral=True
            )
            return

        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        pickup_cfg = data.get("gacha_pickup", core.DEFAULT_CONFIG["gacha_pickup"])
        drawn = core.draw_proseka_cards(pickup_cfg, count=pull_count)
        if not drawn:
            await interaction.followup.send("❌ 한국 서버 캐릭터 DB를 불러오지 못했습니다.", ephemeral=True)
            return

        guild_id = interaction.guild_id or 0
        await asyncio.to_thread(core.save_pulled_cards_to_user, guild_id, interaction.user.id, drawn)
        new_view = GachaPullAgainView(interaction.user)
        await send_gacha_pull_result(interaction, drawn, pickup_cfg, pull_count, new_view)

    @discord.ui.button(label="🎵 1회 더 뽑기", style=discord.ButtonStyle.primary, row=0)
    async def pull_one_more(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_repull(interaction, 1)

    @discord.ui.button(label="🌈 10회 더 뽑기", style=discord.ButtonStyle.success, row=0)
    async def pull_ten_more(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_repull(interaction, 10)

    @discord.ui.button(label="🎒 내 보관함", style=discord.ButtonStyle.secondary, row=1)
    async def open_inventory(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id or 0)
        u_key = str(interaction.user.id)
        user_cards_dict = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})
        view = MyInventoryView(interaction.user, list(user_cards_dict.values()), items_per_page=10, guild_id=interaction.guild_id or 0)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    @discord.ui.button(label="💎 중복 변환", style=discord.ButtonStyle.secondary, row=1)
    async def open_duplicate_converter(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild_id or 0
        preview = await asyncio.to_thread(core.preview_duplicate_cards, guild_id, interaction.user.id)
        view = DuplicateConvertConfirmView(guild_id, interaction.user, preview)
        await core.safe_send_response(interaction, embed=view.build_preview_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="📖 카드 도감", style=discord.ButtonStyle.secondary, row=1)
    async def open_pokedex(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        stats = await asyncio.to_thread(core.get_card_pokedex_stats, guild_id, interaction.user.id)
        view = CardPokedexView(interaction.user, stats, guild_id=guild_id)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    @discord.ui.button(label="👗 의상실", style=discord.ButtonStyle.secondary, row=1)
    async def open_wardrobe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        view = CharacterCostumeWardrobeView(interaction.user, guild_id=interaction.guild_id or 0)
        await interaction.followup.send(embed=view.build_embed(), view=view)


class CardTradeAcceptView(core.SafeView):
    """유저 간 1:1 카드 교환 상대방 수락/거절 및 양측 일러스트 미리보기 인터랙티브 뷰 (수락 시 신청자 크리스탈 100 소모)"""
    def __init__(self, guild_id: int, requester: discord.User, target: discord.User, req_card: dict, tgt_card: dict):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.requester = requester
        self.target = target
        self.req_card = req_card
        self.tgt_card = tgt_card

    @discord.ui.button(label="🤝 교환 수락하기", style=discord.ButtonStyle.success, row=0)
    async def accept_trade(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await core.safe_send_response(interaction, "❌ 교환 신청을 받은 당사자만 수락할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        ok, msg, given_c, received_c, rem_crystals = await asyncio.to_thread(
            core.execute_card_trade,
            self.guild_id,
            self.requester.id,
            self.target.id,
            str(self.req_card["id"]),
            str(self.tgt_card["id"])
        )

        if not ok:
            err_embed = discord.Embed(
                title="❌ 카드 교환 실패",
                description=msg,
                color=discord.Color.red()
            )
            await interaction.edit_original_response(content=None, embed=err_embed, view=None)
            return

        given_pwr = core.get_card_power(given_c)
        recv_pwr = core.get_card_power(received_c)
        embed = discord.Embed(
            title="🔄 프로세카 1:1 카드 교환 성사!",
            description=(
                f"🎉 {self.requester.mention}님과 {self.target.mention}님의 카드 교환이 완료되었습니다!\n\n"
                f"• **📤 {self.requester.display_name} ➔ {self.target.display_name}:**\n"
                f"  └ `[{given_c.get('limit_label', '통상')}]` **{given_c['rarity_label']} [{given_c['prefix']}] {given_c['char_name']}** (`Lv.{given_c.get('level', 1)}` · `⚔️{given_pwr:,}`)\n"
                f"• **📥 {self.target.display_name} ➔ {self.requester.display_name}:**\n"
                f"  └ `[{received_c.get('limit_label', '통상')}]` **{received_c['rarity_label']} [{received_c['prefix']}] {received_c['char_name']}** (`Lv.{received_c.get('level', 1)}` · `⚔️{recv_pwr:,}`)\n\n"
                f"💎 **소모 재화:** {self.requester.display_name}님의 크리스탈 `100개` 차감 (잔여: `{rem_crystals:,}개`)"
            ),
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_thumbnail(url=core.get_proseka_card_image_url(received_c, "auto"))
        await interaction.edit_original_response(content=None, embed=embed, view=None)

    @discord.ui.button(label="🖼️ 제공 카드 일러스트", style=discord.ButtonStyle.secondary, row=0)
    async def preview_req_card(self, interaction: discord.Interaction, button: discord.ui.Button):
        c = self.req_card
        p_embed = discord.Embed(
            title=f"📤 [{self.requester.display_name} 제공] {c['rarity_label']} [{c['prefix']}] {c['char_name']}",
            description=f"• **분류:** `{c.get('limit_label', '통상')}` · **유닛:** `{c.get('unit', '-')}` · **종합력:** `⚔️ {core.get_card_power(c):,}`",
            color=discord.Color.from_rgb(0, 204, 221)
        )
        p_embed.set_image(url=core.get_proseka_card_image_url(c, "auto"))
        await core.safe_send_response(interaction, embed=p_embed, ephemeral=True)

    @discord.ui.button(label="🖼️ 대상 카드 일러스트", style=discord.ButtonStyle.secondary, row=0)
    async def preview_tgt_card(self, interaction: discord.Interaction, button: discord.ui.Button):
        c = self.tgt_card
        p_embed = discord.Embed(
            title=f"📥 [{self.target.display_name} 보유] {c['rarity_label']} [{c['prefix']}] {c['char_name']}",
            description=f"• **분류:** `{c.get('limit_label', '통상')}` · **유닛:** `{c.get('unit', '-')}` · **종합력:** `⚔️ {core.get_card_power(c):,}`",
            color=discord.Color.from_rgb(255, 105, 180)
        )
        p_embed.set_image(url=core.get_proseka_card_image_url(c, "auto"))
        await core.safe_send_response(interaction, embed=p_embed, ephemeral=True)

    @discord.ui.button(label="거절 / 취소", style=discord.ButtonStyle.danger, row=0)
    async def cancel_trade(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in (self.target.id, self.requester.id):
            await core.safe_send_response(interaction, "❌ 교환 당사자만 취소하거나 거절할 수 있습니다.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🚫 카드 교환 취소/거절됨",
            description="카드 교환이 취소되어 크리스탈과 카드가 차감되지 않았습니다.",
            color=discord.Color.dark_grey()
        )
        await interaction.response.edit_message(content=None, embed=embed, view=None)


class InteractiveCardTradeStudioView(core.SafeView):
    """카드 ID를 직접 입력하지 않아도 드롭다운으로 내 카드와 상대 카드를 골라 교환 신청서를 발송하는 인터랙티브 장터 뷰"""
    def __init__(self, guild_id: int, requester: discord.User, target: discord.User, req_cards: dict, tgt_cards: dict, my_crystals: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.requester = requester
        self.target = target
        self.req_cards = req_cards
        self.tgt_cards = tgt_cards
        self.my_crystals = my_crystals
        self.selected_my_cid = None
        self.selected_tgt_cid = None
        self._populate_selects()

    def _populate_selects(self):
        my_unlocked = [c for c in self.req_cards.values() if not c.get("locked", False) and c.get("count", 0) >= 1]
        my_unlocked.sort(key=lambda x: (-x.get("count", 1), -x.get("star_num", 1), -int(x.get("is_limited", False))))
        if my_unlocked:
            opts1 = []
            for c in my_unlocked[:25]:
                cid_s = str(c["id"])
                dup_tag = f"중복 {c.get('count', 1)}장" if c.get("count", 1) > 1 else "1장 보유"
                label = f"{c['rarity_label']} [{c['prefix']}] {c['char_name']}"[:95]
                desc = f"{dup_tag} · {c.get('limit_label', '통상')} · Lv.{c.get('level', 1)} (ID:{cid_s})"[:95]
                opts1.append(discord.SelectOption(label=label, value=cid_s, description=desc, default=(cid_s == self.selected_my_cid)))
            self.my_card_select.options = opts1
            self.my_card_select.disabled = False
        else:
            self.my_card_select.options = [discord.SelectOption(label="교환 가능한(잠금 해제된) 내 카드가 없습니다", value="NONE")]
            self.my_card_select.disabled = True

        tgt_unlocked = [c for c in self.tgt_cards.values() if not c.get("locked", False) and c.get("count", 0) >= 1]
        tgt_unlocked.sort(key=lambda x: (-x.get("count", 1), -x.get("star_num", 1), -int(x.get("is_limited", False))))
        if tgt_unlocked:
            opts2 = []
            for c in tgt_unlocked[:25]:
                cid_s = str(c["id"])
                dup_tag = f"중복 {c.get('count', 1)}장" if c.get("count", 1) > 1 else "1장 보유"
                label = f"{c['rarity_label']} [{c['prefix']}] {c['char_name']}"[:95]
                desc = f"{dup_tag} · {c.get('limit_label', '통상')} · Lv.{c.get('level', 1)} (ID:{cid_s})"[:95]
                opts2.append(discord.SelectOption(label=label, value=cid_s, description=desc, default=(cid_s == self.selected_tgt_cid)))
            self.tgt_card_select.options = opts2
            self.tgt_card_select.disabled = False
        else:
            self.tgt_card_select.options = [discord.SelectOption(label="상대방에게 교환 가능한 카드가 없습니다", value="NONE")]
            self.tgt_card_select.disabled = True

        self.send_offer_btn.disabled = not (self.selected_my_cid and self.selected_tgt_cid and self.selected_my_cid != self.selected_tgt_cid)

    def build_embed(self) -> discord.Embed:
        self._populate_selects()
        my_c = self.req_cards.get(self.selected_my_cid) if self.selected_my_cid else None
        tgt_c = self.tgt_cards.get(self.selected_tgt_cid) if self.selected_tgt_cid else None

        my_line = (
            f"**`[{my_c.get('limit_label', '통상')}]` {my_c['rarity_label']} [{my_c['prefix']}] {my_c['char_name']}** "
            f"(보유 `{my_c.get('count', 1)}장` · `⚔️{core.get_card_power(my_c):,}`)"
            if my_c else "*아래 첫 번째 드롭다운에서 보낼 카드를 선택하세요*"
        )
        tgt_line = (
            f"**`[{tgt_c.get('limit_label', '통상')}]` {tgt_c['rarity_label']} [{tgt_c['prefix']}] {tgt_c['char_name']}** "
            f"(보유 `{tgt_c.get('count', 1)}장` · `⚔️{core.get_card_power(tgt_c):,}`)"
            if tgt_c else "*아래 두 번째 드롭다운에서 받을 카드를 선택하세요*"
        )

        embed = discord.Embed(
            title=f"🤝 프로세카 1:1 카드 교환 스튜디오 ({self.requester.display_name} ⇄ {self.target.display_name})",
            description=(
                "중복 보유 카드를 우선 정렬하여 보여드립니다. (`🔒 잠금` 카드는 자동 보호됨)\n"
                "양쪽 카드를 선택한 뒤 **`[📨 교환 신청서 발송하기]`** 버튼을 눌러주세요!\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📤 **내가 제공할 카드:**\n└ {my_line}\n\n"
                f"📥 **{self.target.display_name}님에게 받을 카드:**\n└ {tgt_line}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💎 **교환 수수료:** `100 💎` (상대방 수락 시에만 차감 · 내 보유: `{self.my_crystals:,} 💎`)"
            ),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        if tgt_c:
            embed.set_thumbnail(url=core.get_proseka_card_image_url(tgt_c, "auto"))
        elif my_c:
            embed.set_thumbnail(url=core.get_proseka_card_image_url(my_c, "auto"))
        embed.set_footer(text="동일한 카드끼리는 교환할 수 없습니다 • 드롭다운에서 카드를 선택해 보세요!")
        return embed

    @discord.ui.select(placeholder="📤 1단계: 내가 상대방에게 보낼 카드를 선택하세요...", row=0)
    async def my_card_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.requester.id:
            await core.safe_send_response(interaction, "❌ 교환 스튜디오를 연 본인만 조작할 수 있습니다.", ephemeral=True)
            return
        val = select.values[0]
        if val == "NONE":
            await core.safe_defer(interaction)
            return
        self.selected_my_cid = val
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.select(placeholder="📥 2단계: 상대방으로부터 받을 카드를 선택하세요...", row=1)
    async def tgt_card_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.requester.id:
            await core.safe_send_response(interaction, "❌ 교환 스튜디오를 연 본인만 조작할 수 있습니다.", ephemeral=True)
            return
        val = select.values[0]
        if val == "NONE":
            await core.safe_defer(interaction)
            return
        self.selected_tgt_cid = val
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="📨 교환 신청서 발송하기 (100💎)", style=discord.ButtonStyle.success, row=2, disabled=True)
    async def send_offer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.requester.id:
            await core.safe_send_response(interaction, "❌ 교환 스튜디오를 연 본인만 발송할 수 있습니다.", ephemeral=True)
            return
        if not self.selected_my_cid or not self.selected_tgt_cid or self.selected_my_cid == self.selected_tgt_cid:
            await core.safe_send_response(interaction, "❌ 서로 다른 두 카드를 먼저 선택해 주세요.", ephemeral=True)
            return

        my_c = self.req_cards.get(self.selected_my_cid)
        tgt_c = self.tgt_cards.get(self.selected_tgt_cid)
        if not my_c or not tgt_c:
            await core.safe_send_response(interaction, "❌ 카드 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        offer_embed = discord.Embed(
            title="🔄 프로세카 1:1 카드 교환 신청 도착!",
            description=(
                f"{self.target.mention}님! {self.requester.mention}님이 **1:1 카드 교환**을 요청했습니다.\n"
                "아래 내역과 일러스트를 확인하시고 동의하시면 **`[🤝 교환 수락하기]`** 버튼을 눌러주세요.\n\n"
                f"📤 **{self.requester.display_name}님이 제공하는 카드:**\n"
                f"└ `[{my_c.get('limit_label', '통상')}]` **{my_c['rarity_label']} [{my_c['prefix']}] {my_c['char_name']}** (`Lv.{my_c.get('level', 1)}` · 보유 `{my_c.get('count', 1)}장`)\n\n"
                f"📥 **{self.target.display_name}님이 제공하는 카드:**\n"
                f"└ `[{tgt_c.get('limit_label', '통상')}]` **{tgt_c['rarity_label']} [{tgt_c['prefix']}] {tgt_c['char_name']}** (`Lv.{tgt_c.get('level', 1)}` · 보유 `{tgt_c.get('count', 1)}장`)\n\n"
                f"💎 **교환 비용:** 신청자({self.requester.display_name})의 크리스탈 `100개` (수락 시 차감)"
            ),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        offer_embed.set_thumbnail(url=core.get_proseka_card_image_url(my_c, "auto"))
        accept_view = CardTradeAcceptView(self.guild_id, self.requester, self.target, my_c, tgt_c)
        await interaction.edit_original_response(content="✅ 채널에 1:1 카드 교환 신청서를 발송했습니다!", embed=None, view=None)
        await interaction.channel.send(content=self.target.mention, embed=offer_embed, view=accept_view)


class CardIllustToggleView(core.SafeView):
    """보유 카드 일러스트 감상, 각성 전(Normal)/각성 후(After Training) 전환 및 카드 잠금(🔒) 토글 뷰"""
    def __init__(
        self,
        card: dict,
        initial_mode: str = "after_training",
        guild_id: int = 0,
        owner_id: int = 0,
        parent_inventory_view=None,
        parent_inventory_message=None
    ):
        super().__init__(timeout=600)
        self.card = dict(card)
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.parent_inventory_view = parent_inventory_view
        self.parent_inventory_message = parent_inventory_message
        self.has_awakening = core.can_card_awaken(card)
        self.current_mode = initial_mode if self.has_awakening else "normal"
        self.update_buttons()

    def update_buttons(self):
        self.normal_btn.disabled = (self.current_mode == "normal")
        if not self.has_awakening:
            self.awakened_btn.disabled = True
            self.awakened_btn.label = "✨ 각성 후 (★3·★4 전용)"
        else:
            self.awakened_btn.disabled = (self.current_mode == "after_training")
            self.awakened_btn.label = "✨ 각성 후 (After Training)"

        is_locked = bool(self.card.get("locked", False))
        if is_locked:
            self.lock_toggle_btn.label = "🔒 잠금됨 (클릭 시 해제)"
            self.lock_toggle_btn.style = discord.ButtonStyle.danger
        else:
            self.lock_toggle_btn.label = "🔓 카드 잠금하기"
            self.lock_toggle_btn.style = discord.ButtonStyle.success

    def build_embed(self):
        mode_text = "✨ 각성 후 (After Training)" if self.current_mode == "after_training" else "🌸 각성 전 (Normal)"
        lock_status = "🔒 잠금 보호 중 (교환·선물·중복변환 제외)" if self.card.get("locked", False) else "🔓 잠금 해제됨"
        unit_str = f"{self.card['unit']}" + (f" ({self.card['support_unit']})" if self.card.get("support_unit") else "")
        desc_lines = [
            f"• **소속 유닛:** `{unit_str}`",
            f"• **속성:** {self.card.get('attr', '✨')} · **보유 수량:** `{self.card.get('count', 1)}장` (ID: `{self.card.get('id')}`)",
            f"• **일러스트 상태:** `{mode_text}`",
            f"• **보호 상태:** `{lock_status}`"
        ]
        cos = core.get_costume_for_card(self.card.get("id"))
        if cos:
            desc_lines.append(f"• **부속 3D 의상:** 👗 **`[{cos['name']}]`** (`{'/'.join(cos.get('parts', ['body']))}`)")

        embed = discord.Embed(
            title=f"🖼️ [{self.card.get('limit_label', '통상')}] {self.card['rarity_label']} [{self.card['prefix']}] {self.card['char_name']}",
            description="\n".join(desc_lines),
            color=discord.Color.from_rgb(255, 105, 180) if self.card.get("star_num", 1) >= 4 else discord.Color.from_rgb(0, 204, 221)
        )
        return embed

    async def switch_mode(self, interaction: discord.Interaction, target_mode: str):
        await core.safe_defer(interaction)
        self.current_mode = target_mode
        self.update_buttons()
        embed = self.build_embed()
        img_bytes, filename = await asyncio.to_thread(core.fetch_proseka_card_image_bytes, self.card, self.current_mode)
        if img_bytes and filename:
            file = discord.File(io.BytesIO(img_bytes), filename=filename)
            embed.set_image(url=f"attachment://{filename}")
            await interaction.edit_original_response(embed=embed, attachments=[file], view=self)
        else:
            embed.set_image(url=core.get_proseka_card_image_url(self.card, self.current_mode))
            await interaction.edit_original_response(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="🌸 각성 전 (Normal)", style=discord.ButtonStyle.secondary, row=0)
    async def normal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.switch_mode(interaction, "normal")

    @discord.ui.button(label="✨ 각성 후 (After Training)", style=discord.ButtonStyle.primary, row=0)
    async def awakened_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.switch_mode(interaction, "after_training")

    @discord.ui.button(label="🔓 카드 잠금하기", style=discord.ButtonStyle.success, row=0)
    async def lock_toggle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.owner_id and interaction.user.id != self.owner_id:
            await core.safe_send_response(interaction, "❌ 카드 소유자 본인만 잠금 상태를 변경할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        ok, new_locked, updated_card = await asyncio.to_thread(
            core.toggle_user_card_lock,
            self.guild_id or (interaction.guild_id or 0),
            interaction.user.id,
            str(self.card.get("id"))
        )
        if not ok or not updated_card:
            await interaction.followup.send("❌ 카드 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        self.card["locked"] = new_locked
        if self.parent_inventory_view:
            for c in self.parent_inventory_view.cards:
                if str(c.get("id")) == str(self.card.get("id")):
                    c["locked"] = new_locked
            self.parent_inventory_view.update_illust_select()
            if self.parent_inventory_message:
                try:
                    await self.parent_inventory_message.edit(
                        embed=self.parent_inventory_view.build_embed(),
                        view=self.parent_inventory_view
                    )
                except Exception:
                    pass

        self.update_buttons()
        embed = self.build_embed()
        img_bytes, filename = await asyncio.to_thread(core.fetch_proseka_card_image_bytes, self.card, self.current_mode)
        if img_bytes and filename:
            file = discord.File(io.BytesIO(img_bytes), filename=filename)
            embed.set_image(url=f"attachment://{filename}")
            await interaction.edit_original_response(embed=embed, attachments=[file], view=self)
        else:
            embed.set_image(url=core.get_proseka_card_image_url(self.card, self.current_mode))
            await interaction.edit_original_response(embed=embed, view=self)


class CharacterCostumeWardrobeView(core.SafeView):
    """캐릭터별 3D 의상 착용 및 다른 캐릭터 의상 제작/구매(300 💎) 뷰"""
    def __init__(self, user: discord.User, guild_id: int = 0, initial_char_id: int = 1):
        super().__init__(timeout=600)
        self.user = user
        self.guild_id = guild_id
        self.current_char_id = initial_char_id
        char_info = core.CHARACTER_MAP.get(self.current_char_id, core.CHARACTER_MAP[1])
        self.current_unit = char_info["unit"]
        self.update_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await super().interaction_check(interaction)
        if interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 의상실은 **{self.user.display_name}**님의 개인 의상실입니다. `/의상` 명령어로 본인의 의상실을 열어보세요!",
                ephemeral=True
            )
            return False
        return True

    def update_components(self):
        # 1. Unit select (Row 0)
        unit_opts = []
        for u in core.UNIT_ORDER:
            unit_opts.append(discord.SelectOption(
                label=u,
                value=u,
                default=(u == self.current_unit),
                emoji="🎵" if u != "버츄얼 싱어" else "✨"
            ))
        self.unit_select.options = unit_opts

        # 2. Character select for current unit (Row 1)
        chars_in_unit = [
            (cid, info) for cid, info in core.CHARACTER_MAP.items()
            if info["unit"] == self.current_unit
        ]
        if not any(cid == self.current_char_id for cid, _ in chars_in_unit):
            self.current_char_id = chars_in_unit[0][0]

        char_opts = []
        for cid, info in chars_in_unit:
            char_opts.append(discord.SelectOption(
                label=f"{info['name']}",
                value=str(cid),
                description=f"{info['unit']} 소속",
                default=(cid == self.current_char_id)
            ))
        self.char_select.options = char_opts

        # 3. Equip costume select (Row 2)
        unlocked = core.get_user_unlocked_costumes_for_char(self.guild_id, self.user.id, self.current_char_id)
        equipped = core.get_user_equipped_costume(self.guild_id, self.user.id, self.current_char_id)
        eq_id = equipped.get("costume_id")

        equip_opts = []
        for c in unlocked[:25]:
            is_active = (c["costume_id"] == eq_id)
            tag = "[착용 중] " if is_active else ""
            label = f"{tag}{c['name']}"[:100]
            desc = f"{c.get('obtained_how', '기본')} | 구성:{'/'.join(c.get('parts', ['body']))}"[:100]
            equip_opts.append(discord.SelectOption(
                label=label,
                value=c["costume_id"],
                description=desc,
                default=is_active
            ))
        self.equip_select.options = equip_opts
        self.equip_select.disabled = False

        # 4. Shop / purchase select (Row 3)
        purchasable = core.get_purchasable_costumes_for_char(self.guild_id, self.user.id, self.current_char_id)
        if not purchasable:
            self.shop_select.options = [
                discord.SelectOption(
                    label="제작 가능한 새 의상이 없습니다",
                    value="NONE",
                    description="가챠에서 ★4 카드를 뽑으면 해당 의상을 300💎로 제작할 수 있습니다."
                )
            ]
            self.shop_select.disabled = True
        else:
            shop_opts = []
            for c in purchasable[:25]:
                label = f"💎 [300💎] {c['name']}"[:100]
                desc = f"★4 [{c.get('card_prefix')}] 기반 | 원래:{c.get('char_name')}"[:100]
                shop_opts.append(discord.SelectOption(
                    label=label,
                    value=c["costume_id"],
                    description=desc
                ))
            self.shop_select.options = shop_opts
            self.shop_select.disabled = False

    def build_embed(self):
        self.update_components()
        char_info = core.CHARACTER_MAP.get(self.current_char_id, core.CHARACTER_MAP[1])
        gender_kr = "남성 모델 (Men)" if self.current_char_id in core.MALE_CHAR_IDS else "여성 모델 (Ladies)"
        equipped = core.get_user_equipped_costume(self.guild_id, self.user.id, self.current_char_id)
        unlocked = core.get_user_unlocked_costumes_for_char(self.guild_id, self.user.id, self.current_char_id)
        purchasable = core.get_purchasable_costumes_for_char(self.guild_id, self.user.id, self.current_char_id)

        data = core.load_data()
        prof = core.ensure_user_profile(data, self.user.id, self.user.display_name)
        crystals = prof.get("crystals", 0)

        parts_str = " / ".join(equipped.get("parts", ["body", "head"]))
        source_str = equipped.get("obtained_how", "기본 지급 의상")
        if equipped.get("card_prefix") and equipped.get("card_prefix") != "기본":
            source_str = f"★4 [{equipped.get('card_prefix')}] {equipped.get('char_name')} 뽑기 획득"

        embed = discord.Embed(
            title=f"👗 {char_info['name']}의 세카이 3D 의상실",
            description=(
                f"• **소속 유닛:** `{char_info['unit']}`  ·  **체형:** `{gender_kr}`\n"
                f"• **현재 착용 의상:** 👗 **`[{equipped['name']}]`**\n"
                f"   └ 획득 경로: `{source_str}`\n"
                f"   └ 의상 구성 파츠: `{parts_str}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• 💎 **보유 크리스탈:** **`{crystals:,} 💎`**\n"
                f"• 👕 **착용 가능한 보유 의상:** `{len(unlocked)}벌`  ·  🛍️ **새로 제작 가능한 의상:** `{len(purchasable)}벌`\n\n"
                f"*💡 가챠에서 뽑은 카드의 3D 의상을 `{core.COSTUME_PURCHASE_PRICE} 💎`로 제작하여 다른 동일 체형 캐릭터에게 자유롭게 입힐 수 있습니다.*"
            ),
            color=discord.Color.from_rgb(255, 105, 180) if gender_kr.startswith("여성") else discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )

        card_id = equipped.get("card_id")
        if card_id and card_id > 0:
            embed.set_image(url=core.get_proseka_card_image_url({"id": card_id, "assetbundleName": equipped.get("assetbundleName")}, "auto"))
        else:
            rep_card = next((c for c in core.PROSEKA_KR_CARDS if c.get("char_id") == self.current_char_id), None)
            if rep_card:
                embed.set_image(url=core.get_proseka_card_image_url(rep_card, "normal"))

        embed.set_footer(text=f"요청자: {self.user.display_name} • 하단 메뉴에서 유닛·캐릭터를 전환하거나 의상을 착용/제작하세요.")
        return embed

    @discord.ui.select(placeholder="🏷️ 1단계: 유닛(그룹)을 선택하세요...", row=0)
    async def unit_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.current_unit = select.values[0]
        for cid, info in core.CHARACTER_MAP.items():
            if info["unit"] == self.current_unit:
                self.current_char_id = cid
                break
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.select(placeholder="👤 2단계: 캐릭터를 선택하세요...", row=1)
    async def char_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.current_char_id = int(select.values[0])
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.select(placeholder="👗 3단계: 착용할 보유 의상을 선택하세요...", row=2)
    async def equip_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        cos_id = select.values[0]
        ok, msg, cos = await asyncio.to_thread(core.equip_user_costume, self.guild_id, interaction.user.id, self.current_char_id, cos_id)
        if ok:
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
            await core.safe_send_response(interaction, msg, ephemeral=True)
        else:
            await core.safe_send_response(interaction, f"❌ {msg}", ephemeral=True)

    @discord.ui.select(placeholder="🛍️ 4단계: 다른 캐릭터 의상 제작/구매 (300 💎)...", row=3)
    async def shop_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        cos_id = select.values[0]
        if cos_id == "NONE":
            await core.safe_defer(interaction)
            return
        ok, msg, cos, rem = await asyncio.to_thread(core.purchase_and_equip_costume, self.guild_id, interaction.user.id, self.current_char_id, cos_id)
        if ok:
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
            await core.safe_send_response(interaction, f"🎉 {msg} (남은 크리스탈: `{rem:,} 💎`)", ephemeral=True)
        else:
            await core.safe_send_response(interaction, f"❌ {msg}", ephemeral=True)

    @discord.ui.button(label="ℹ️ 의상 시스템 안내", style=discord.ButtonStyle.secondary, row=4)
    async def btn_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        info_text = (
            "👗 **세카이 3D 의상 시스템 안내**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "• **의상 획득 (가챠 연동):**\n"
            "  - `/프로세카뽑기`에서 3D 의상이 포함된 ★4 카드를 뽑으면, 해당 원본 캐릭터에게 의상이 **자동 무료 해금**됩니다.\n\n"
            "• **다른 캐릭터에게 의상 제작/입히기:**\n"
            "  - 뽑기로 보유 중인 카드의 의상은 **동일 체형(여성/남성)의 다른 캐릭터**에게 `300 💎(크리스탈)`로 제작하여 입혀줄 수 있습니다.\n"
            "  - 한 번 제작한 의상은 해당 캐릭터의 영구 보유 목록에 추가되어 언제든 갈아입을 수 있습니다.\n\n"
            "• **크리스탈 획득처:**\n"
            "  - `/출석체크` (매일 출석 및 주간/월간 마일스톤 보너스)\n"
            "  - `/중복카드변환` (가챠 중복 카드 크리스탈 환급)\n"
            "  - `/하드코어스터디` (50분/10분 집중 완료 보상)"
        )
        await core.safe_send_response(interaction, info_text, ephemeral=True)


class ProsekaRatePaginationView(core.SafeView):
    def __init__(self, all_prob_cards, pickup_cfg, items_per_page=5):
        super().__init__(timeout=600)
        self.all_prob_cards = all_prob_cards
        self.filtered_cards = list(all_prob_cards)
        self.pickup_cfg = pickup_cfg
        self.items_per_page = items_per_page
        self.current_page = 0
        self.current_filter = "전체"
        self.update_buttons()

    @property
    def max_page(self):
        if not self.filtered_cards:
            return 0
        return (len(self.filtered_cards) - 1) // self.items_per_page

    def update_buttons(self):
        is_first = (self.current_page <= 0)
        is_last = (self.current_page >= self.max_page)
        self.back_5.disabled = is_first
        self.prev_page.disabled = is_first
        self.page_indicator.label = f"📄 {self.current_page + 1} / {self.max_page + 1}"
        self.next_page.disabled = is_last
        self.forward_5.disabled = is_last

    def build_embed(self):
        self.update_buttons()
        total_cards = len(self.filtered_cards)
        start_idx = self.current_page * self.items_per_page
        page_items = self.filtered_cards[start_idx:start_idx + self.items_per_page]

        p_unit = self.pickup_cfg.get("unit") or "미지정"
        p_char = self.pickup_cfg.get("character") or "미지정"
        inc_lim = "포함 (통상+한정+페스+생일)" if self.pickup_cfg.get("include_limited", True) else "제외 (통상만)"

        embed = discord.Embed(
            title="🎶 프로세카 한국 서버 전체 캐릭터 & 확률 목록",
            description=(
                f"• **기준 DB:** 프로세카 한국 서버 (총 **{len(self.all_prob_cards):,}장**)\n"
                f"• **현재 필터:** `{self.current_filter}` (검색 결과: **{total_cards:,}장**)\n"
                f"• **등급 합산 확률:** `★4 / 🎀생일: 3.0%` · `★3: 8.5%` · `★2 / ★1: 88.5%`\n"
                f"• **현재 픽업 설정:** 유닛 `{p_unit}` · 캐릭터 `{p_char}` · 한정 `{inc_lim}`"
            ),
            color=discord.Color.from_rgb(0, 204, 221)
        )

        if not page_items:
            embed.add_field(name="검색 결과 없음", value="해당 조건에 맞는 캐릭터 카드가 없습니다.", inline=False)
        else:
            lines = []
            for idx, c in enumerate(page_items, start=start_idx + 1):
                pickup_badge = "🎯**[픽업]** " if c.get("is_pickup") else ""
                unit_str = f"{c['unit']}" + (f" ({c['support_unit']})" if c.get("support_unit") else "")
                lines.append(
                    f"**{idx}.** {pickup_badge}`[{c['limit_label']}]` **{c['rarity_label']} [{c['prefix']}] {c['char_name']}**\n"
                    f"   └ 🏷️ {unit_str} · {c['attr']} · 🎲 개별 확률: **`{c['prob']:.4f}%`** (ID: `{c['id']}`)"
                )
            embed.add_field(
                name=f"📖 캐릭터 목록 (페이지 {self.current_page + 1} / {self.max_page + 1})",
                value="\n\n".join(lines),
                inline=False
            )

        embed.set_footer(text="아래 버튼으로 페이지를 이동하거나 드롭다운에서 성급/유닛 필터를 변경할 수 있습니다.")
        return embed

    @discord.ui.button(label="⏪ -5", style=discord.ButtonStyle.secondary, row=0)
    async def back_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 5)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.primary, row=0)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="📄 1 / 1", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = min(self.max_page, self.current_page + 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="+5 ⏩", style=discord.ButtonStyle.secondary, row=0)
    async def forward_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = min(self.max_page, self.current_page + 5)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="🔍 성급 / 한정 / 유닛별 필터 선택...",
        row=1,
        options=[
            discord.SelectOption(label="전체 보기", value="ALL", description="모든 한국 서버 캐릭터 카드 표시"),
            discord.SelectOption(label="🎯 현재 픽업 대상만", value="PICKUP", description="봇주인이 지정한 픽업 대상 카드만 표시"),
            discord.SelectOption(label="✨ 한정/페스/생일 카드만", value="LIMITED", description="통상을 제외한 모든 한정 카드만 표시"),
            discord.SelectOption(label="★★★★ (4성)만", value="R4", description="4성 카드만 모아보기"),
            discord.SelectOption(label="🎀 생일 한정만", value="RB", description="생일 기념 레어 카드만 모아보기"),
            discord.SelectOption(label="★★★ (3성)만", value="R3", description="3성 카드만 모아보기"),
            discord.SelectOption(label="Leo/need", value="U_Leo/need"),
            discord.SelectOption(label="MORE MORE JUMP!", value="U_MORE MORE JUMP!"),
            discord.SelectOption(label="Vivid BAD SQUAD", value="U_Vivid BAD SQUAD"),
            discord.SelectOption(label="원더랜즈×쇼타임", value="U_원더랜즈×쇼타임"),
            discord.SelectOption(label="25시, 나이트 코드에서.", value="U_25시, 나이트 코드에서."),
            discord.SelectOption(label="버츄얼 싱어", value="U_버츄얼 싱어")
        ]
    )
    async def filter_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        if val == "ALL":
            self.filtered_cards = list(self.all_prob_cards)
            self.current_filter = "전체"
        elif val == "PICKUP":
            self.filtered_cards = [c for c in self.all_prob_cards if c.get("is_pickup")]
            self.current_filter = "픽업 대상만"
        elif val == "LIMITED":
            self.filtered_cards = [c for c in self.all_prob_cards if c.get("is_limited")]
            self.current_filter = "한정/페스/생일만"
        elif val == "R4":
            self.filtered_cards = [c for c in self.all_prob_cards if c["rarity_type"] == "rarity_4"]
            self.current_filter = "★★★★ (4성)"
        elif val == "RB":
            self.filtered_cards = [c for c in self.all_prob_cards if c["rarity_type"] == "rarity_birthday"]
            self.current_filter = "🎀 생일 한정"
        elif val == "R3":
            self.filtered_cards = [c for c in self.all_prob_cards if c["rarity_type"] == "rarity_3"]
            self.current_filter = "★★★ (3성)"
        elif val.startswith("U_"):
            u_name = val[2:]
            self.filtered_cards = [
                c for c in self.all_prob_cards
                if c["unit"] == u_name or c.get("support_unit") == u_name
            ]
            self.current_filter = f"유닛: {u_name}"

        self.current_page = 0
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class MyInventoryView(core.SafeView):
    """내 캐릭터 보관함 (검색어 필터 + 정렬 + 잠금 표시 + 중복 카드 크리스탈 변환 + 일러스트 & 각성 전환)"""
    def __init__(self, user: discord.User, card_list: list, items_per_page=10, search_keyword: str = None, guild_id: int = 0):
        super().__init__(timeout=600)
        self.user = user
        self.cards = list(card_list)
        self.items_per_page = items_per_page
        self.search_keyword = search_keyword
        self.guild_id = guild_id
        self.current_page = 0
        self.sort_mode_label = "획득일 최신순"
        self.apply_sort("obtained_desc")
        self.update_illust_select()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await super().interaction_check(interaction)
        if interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 보관함은 **{self.user.display_name}**님의 개인 보관함입니다. `/내캐릭터` 명령어로 본인의 보관함을 열어보세요!",
                ephemeral=True
            )
            return False
        return True

    @property
    def max_page(self):
        if not self.cards:
            return 0
        return (len(self.cards) - 1) // self.items_per_page

    def get_current_page_items(self):
        start_idx = self.current_page * self.items_per_page
        return self.cards[start_idx:start_idx + self.items_per_page]

    def update_illust_select(self):
        is_first = (self.current_page <= 0)
        is_last = (self.current_page >= self.max_page)
        self.back_5.disabled = is_first
        self.prev_page.disabled = is_first
        self.next_page.disabled = is_last
        self.forward_5.disabled = is_last

        page_items = self.get_current_page_items()
        if not page_items:
            self.illust_select.options = [
                discord.SelectOption(label="표시할 카드가 없습니다", value="NONE")
            ]
            self.illust_select.disabled = True
        else:
            opts = []
            start_idx = self.current_page * self.items_per_page
            for idx, c in enumerate(page_items, start=start_idx + 1):
                lock_icon = "🔒 " if c.get("locked", False) else ""
                label = f"{idx}. {lock_icon}{c['rarity_label']} [{c['prefix']}] {c['char_name']}"[:100]
                desc = f"[{c.get('limit_label', '통상')}] 보유:{c.get('count', 1)}장 | 일러스트·각성·잠금 설정"[:100]
                opts.append(discord.SelectOption(label=label, value=str(c["id"]), description=desc))
            self.illust_select.options = opts
            self.illust_select.disabled = False

    def apply_sort(self, mode: str):
        if mode == "obtained_desc":
            self.cards.sort(key=lambda x: x.get("last_obtained_at", ""), reverse=True)
            self.sort_mode_label = "획득일 최신순"
        elif mode == "obtained_asc":
            self.cards.sort(key=lambda x: x.get("obtained_at", ""))
            self.sort_mode_label = "획득일 오래된순"
        elif mode == "star_desc":
            self.cards.sort(key=lambda x: (-x.get("star_num", 1), -int(x.get("is_limited", False)), x.get("char_id", 99)))
            self.sort_mode_label = "성(레어도) 높은순"
        elif mode == "star_asc":
            self.cards.sort(key=lambda x: (x.get("star_num", 1), x.get("char_id", 99)))
            self.sort_mode_label = "성(레어도) 낮은순"
        elif mode == "unit":
            self.cards.sort(key=lambda x: (
                core.UNIT_ORDER.index(x["unit"]) if x.get("unit") in core.UNIT_ORDER else 99,
                x.get("char_id", 99),
                -x.get("star_num", 1)
            ))
            self.sort_mode_label = "유닛 기준"
        elif mode == "char_name":
            self.cards.sort(key=lambda x: (x.get("char_name", ""), -x.get("star_num", 1)))
            self.sort_mode_label = "캐릭터 이름순"
        elif mode == "count_desc":
            self.cards.sort(key=lambda x: (-x.get("count", 1), -x.get("star_num", 1)))
            self.sort_mode_label = "중복 보유 많은순"
        elif mode == "locked_only":
            self.cards.sort(key=lambda x: (not bool(x.get("locked", False)), -x.get("star_num", 1)))
            self.sort_mode_label = "🔒 잠금 카드 우선"

    def build_embed(self):
        self.update_illust_select()
        total_unique = len(self.cards)
        total_pulls = sum(c.get("count", 1) for c in self.cards)
        locked_cnt = sum(1 for c in self.cards if c.get("locked", False))
        dup_cnt = sum(max(0, c.get("count", 1) - 1) for c in self.cards if not c.get("locked", False))
        start_idx = self.current_page * self.items_per_page
        page_items = self.get_current_page_items()

        search_line = f"• **검색어 필터:** `{self.search_keyword}`\n" if self.search_keyword else ""
        embed = discord.Embed(
            title=f"🎒 {self.user.display_name}님의 프로세카 캐릭터 보관함",
            description=(
                f"{search_line}"
                f"• **보유 종류:** `{total_unique:,}종` (총 누적: `{total_pulls:,}장` · 🔒잠금: `{locked_cnt}종` · 💎변환가능 중복: `{dup_cnt}장`)\n"
                f"• **현재 정렬 기준:** `{self.sort_mode_label}`"
            ),
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(core.KST)
        )

        if not page_items:
            empty_msg = f"`{self.search_keyword}` 검색 조건에 맞는 보유 카드가 없습니다." if self.search_keyword else "`/프로세카뽑기` 명령어로 캐릭터를 뽑아보세요!"
            embed.add_field(name="조회된 카드가 없습니다", value=empty_msg, inline=False)
        else:
            lines = []
            for idx, c in enumerate(page_items, start=start_idx + 1):
                unit_str = f"{c['unit']}" + (f" ({c['support_unit']})" if c.get("support_unit") else "")
                lock_badge = "🔒 " if c.get("locked", False) else ""
                cur_lvl = c.get("level", 1)
                max_lvl = core.get_card_max_level(c)
                power_val = core.get_card_power(c)
                cos = core.get_costume_for_card(c.get("id"))
                cos_tag = f" · 👗`[{cos['name']}]`" if cos else ""
                lines.append(
                    f"**{idx}.** {lock_badge}`[{c.get('limit_label', '통상')}]` **{c['rarity_label']} [{c['prefix']}] {c['char_name']}** (보유: `{c.get('count', 1)}장`)\n"
                    f"   └ 🏷️ {unit_str} · {c.get('attr', '✨')}{cos_tag} · 📈 `Lv.{cur_lvl}/{max_lvl}` (`⚔️ {power_val:,}`) · 🕒 `{c.get('last_obtained_at', '-')[:10]}`"
                )
            full_text = "\n".join(lines)
            if len(full_text) <= 1000:
                embed.add_field(
                    name=f"📖 내 캐릭터 목록 (페이지 {self.current_page + 1} / {self.max_page + 1})",
                    value=full_text,
                    inline=False
                )
            else:
                mid = (len(lines) + 1) // 2
                embed.add_field(
                    name=f"📖 내 캐릭터 목록 (페이지 {self.current_page + 1} / {self.max_page + 1}) - 1",
                    value="\n".join(lines[:mid]),
                    inline=False
                )
                embed.add_field(
                    name=f"📖 내 캐릭터 목록 (페이지 {self.current_page + 1} / {self.max_page + 1}) - 2",
                    value="\n".join(lines[mid:]),
                    inline=False
                )

        embed.set_footer(text="하단에서 카드를 선택해 일러스트 감상·각성 전환·잠금(🔒)을 설정하거나, 💎 버튼으로 중복 카드를 크리스탈로 변환하세요.")
        return embed

    @discord.ui.button(label="⏪ -5", style=discord.ButtonStyle.secondary, row=0)
    async def back_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 5)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.primary, row=0)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = min(self.max_page, self.current_page + 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="+5 ⏩", style=discord.ButtonStyle.secondary, row=0)
    async def forward_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = min(self.max_page, self.current_page + 5)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="💎 중복 카드 크리스탈 변환", style=discord.ButtonStyle.success, row=0)
    async def dup_convert_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 보관함에서만 중복 카드를 변환할 수 있습니다.", ephemeral=True)
            return
        gid = self.guild_id or (interaction.guild_id or 0)
        preview = await asyncio.to_thread(core.preview_duplicate_cards, gid, self.user.id)
        view = DuplicateConvertConfirmView(
            gid,
            self.user,
            preview,
            parent_inventory_view=self,
            parent_inventory_message=interaction.message
        )
        await core.safe_send_response(interaction, embed=view.build_preview_embed(), view=view, ephemeral=True)

    @discord.ui.select(
        placeholder="📊 정렬 기준 선택 (획득일 / 성 기준 / 잠금 우선 / 유닛 기준 등)...",
        row=1,
        options=[
            discord.SelectOption(label="🕒 획득일 최신순", value="obtained_desc", description="가장 최근에 뽑은 캐릭터부터 정렬"),
            discord.SelectOption(label="🕰️ 획득일 오래된순", value="obtained_asc", description="가장 처음 뽑은 캐릭터부터 정렬"),
            discord.SelectOption(label="⭐ 성(레어도) 높은순", value="star_desc", description="★4 → 🎀생일 → ★3 → ★2 → ★1 순서로 정렬"),
            discord.SelectOption(label="☆ 성(레어도) 낮은순", value="star_asc", description="★1 → ★2 → ★3 → 🎀생일 → ★4 순서로 정렬"),
            discord.SelectOption(label="🔒 잠금 보호 카드 우선", value="locked_only", description="잠금(🔒) 설정한 소중한 카드를 맨 위로 정렬"),
            discord.SelectOption(label="🏷️ 유닛 기준 정렬", value="unit", description="Leo/need, 모모점, 비배스, 원더쇼, 니고, 버싱 순서"),
            discord.SelectOption(label="🔤 캐릭터 이름순", value="char_name", description="캐릭터 이름 가나다순 정렬"),
            discord.SelectOption(label="🔢 중복 보유 많은순", value="count_desc", description="가장 많이 중복 획득한 카드부터 정렬")
        ]
    )
    async def sort_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.apply_sort(select.values[0])
        self.current_page = 0
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="🖼️ 현재 페이지에서 일러스트 감상 및 잠금(🔒) 설정할 카드를 선택하세요...",
        row=2,
        options=[discord.SelectOption(label="카드 선택", value="NONE")]
    )
    async def illust_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        cid_val = select.values[0]
        if cid_val == "NONE":
            await core.safe_defer(interaction)
            return
        selected_card = next((c for c in self.cards if str(c.get("id")) == cid_val), None)
        if not selected_card:
            await core.safe_send_response(interaction, "❌ 선택한 카드 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        init_mode = "after_training" if core.can_card_awaken(selected_card) else "normal"
        toggle_view = CardIllustToggleView(
            selected_card,
            initial_mode=init_mode,
            guild_id=self.guild_id or (interaction.guild_id or 0),
            owner_id=self.user.id,
            parent_inventory_view=self,
            parent_inventory_message=interaction.message
        )
        embed = toggle_view.build_embed()

        img_bytes, filename = await asyncio.to_thread(core.fetch_proseka_card_image_bytes, selected_card, init_mode)
        if img_bytes and filename:
            file = discord.File(io.BytesIO(img_bytes), filename=filename)
            embed.set_image(url=f"attachment://{filename}")
            await interaction.followup.send(embed=embed, file=file, view=toggle_view)
        else:
            embed.set_image(url=core.get_proseka_card_image_url(selected_card, init_mode))
            await interaction.followup.send(embed=embed, view=toggle_view)


class CardPokedexView(core.SafeView):
    """
    전체 카드 도감 뷰 (/카드도감)
    - 탭 1: 📊 캐릭터별 수집률 (%) (유닛/캐릭터별 보유율 게이지 및 상세 체크리스트)
    - 탭 2: 🔒 미획득 카드 (아직 획득하지 못한 카드만 별도 필터링 및 일러스트 미리보기)
    - 탭 3: ✨ 보유 완료 카드 (수집 완료한 도감 카드 목록)
    """
    def __init__(self, user: discord.User, stats: dict, guild_id: int = 0, initial_tab: str = "char_rates"):
        super().__init__(timeout=600)
        self.user = user
        self.stats = stats
        self.guild_id = guild_id
        self.active_tab = initial_tab  # "char_rates" | "unowned" | "owned"
        self.filter_val = "ALL"
        self.filter_label = "전체 (26명)"
        self.current_page = 0
        self.update_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await super().interaction_check(interaction)
        if interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 도감은 **{self.user.display_name}**님의 개인 도감입니다. `/카드도감` 명령어로 본인의 도감을 열어보세요!",
                ephemeral=True
            )
            return False
        return True

    def get_filtered_items(self):
        if self.active_tab == "char_rates":
            chars = list(self.stats.get("by_character", []))
            if self.filter_val.startswith("U_"):
                u_name = self.filter_val[2:]
                chars = [c for c in chars if c["unit"] == u_name]
            elif self.filter_val == "INCOMPLETE":
                chars = [c for c in chars if c["owned_count"] < c["total_count"]]
            elif self.filter_val == "HIGH_RATE":
                chars.sort(key=lambda x: (-x["rate"], -x["owned_count"], x["char_id"]))
            return chars

        source_list = (
            self.stats.get("unowned_cards", [])
            if self.active_tab == "unowned"
            else self.stats.get("owned_cards", [])
        )
        cards = list(source_list)
        if self.filter_val == "R4":
            cards = [c for c in cards if c.get("rarity_type") == "rarity_4"]
        elif self.filter_val == "RB":
            cards = [c for c in cards if c.get("rarity_type") == "rarity_birthday"]
        elif self.filter_val == "R3":
            cards = [c for c in cards if c.get("rarity_type") == "rarity_3"]
        elif self.filter_val == "LIMITED":
            cards = [c for c in cards if c.get("is_limited")]
        elif self.filter_val.startswith("U_"):
            u_name = self.filter_val[2:]
            cards = [c for c in cards if c.get("unit") == u_name or c.get("support_unit") == u_name]
        return cards

    @property
    def items_per_page(self):
        return 10

    @property
    def max_page(self):
        items = self.get_filtered_items()
        if not items:
            return 0
        return (len(items) - 1) // self.items_per_page

    def update_components(self):
        self.tab_char_btn.style = (
            discord.ButtonStyle.primary if self.active_tab == "char_rates" else discord.ButtonStyle.secondary
        )
        self.tab_unowned_btn.style = (
            discord.ButtonStyle.danger if self.active_tab == "unowned" else discord.ButtonStyle.secondary
        )
        self.tab_owned_btn.style = (
            discord.ButtonStyle.success if self.active_tab == "owned" else discord.ButtonStyle.secondary
        )

        self.prev_btn.disabled = (self.current_page <= 0)
        self.next_btn.disabled = (self.current_page >= self.max_page)

        items = self.get_filtered_items()
        start_idx = self.current_page * self.items_per_page
        page_items = items[start_idx:start_idx + self.items_per_page]

        if self.active_tab == "char_rates" or not page_items:
            self.preview_select.options = [
                discord.SelectOption(
                    label="🔒 미획득 / ✨ 보유 탭에서 카드 일러스트를 미리 볼 수 있습니다",
                    value="NONE"
                )
            ]
            self.preview_select.disabled = True
        else:
            opts = []
            for idx, c in enumerate(page_items, start=start_idx + 1):
                status_tag = "🔒미획득" if self.active_tab == "unowned" else f"✨보유({c.get('count', 1)}장)"
                label = f"{idx}. [{status_tag}] {c['rarity_label']} [{c['prefix']}] {c['char_name']}"[:100]
                desc = f"[{c.get('limit_label', '통상')}] {c.get('unit', '')} · 클릭하여 카드 일러스트 확인"[:100]
                opts.append(discord.SelectOption(label=label, value=str(c["id"]), description=desc))
            self.preview_select.options = opts
            self.preview_select.disabled = False

    def build_embed(self):
        self.update_components()
        tot_master = self.stats.get("total_master", 0)
        tot_owned = self.stats.get("total_owned", 0)
        tot_unowned = self.stats.get("total_unowned", 0)
        overall_bar = self.stats.get("overall_bar", "")
        r_stats = self.stats.get("by_rarity", {})

        r4 = r_stats.get("rarity_4", {"owned": 0, "total": 0})
        rb = r_stats.get("rarity_birthday", {"owned": 0, "total": 0})
        r3 = r_stats.get("rarity_3", {"owned": 0, "total": 0})
        r2 = r_stats.get("rarity_2", {"owned": 0, "total": 0})

        tab_titles = {
            "char_rates": "📊 캐릭터별 도감 수집률 (%)",
            "unowned": f"🔒 아직 획득하지 못한 미보유 카드 ({tot_unowned:,}종)",
            "owned": f"✨ 수집 완료한 보유 도감 카드 ({tot_owned:,}종)"
        }
        embed_color = (
            discord.Color.from_rgb(0, 204, 221)
            if self.active_tab == "char_rates"
            else (discord.Color.from_rgb(255, 105, 180) if self.active_tab == "unowned" else discord.Color.gold())
        )

        embed = discord.Embed(
            title=f"📖 {self.user.display_name}님의 프로세카 전체 카드 도감 — {tab_titles.get(self.active_tab)}",
            description=(
                f"• **전체 도감 달성률:** **`{tot_owned:,} / {tot_master:,}종`** (미획득 `{tot_unowned:,}종`)\n"
                f"└ {overall_bar}\n"
                f"• **성급별 수집:** `★4 {r4['owned']}/{r4['total']}` · `🎀생일 {rb['owned']}/{rb['total']}` · "
                f"`★3 {r3['owned']}/{r3['total']}` · `★2 {r2['owned']}/{r2['total']}`\n"
                f"• **현재 필터:** `{self.filter_label}`"
            ),
            color=embed_color,
            timestamp=datetime.datetime.now(core.KST)
        )

        items = self.get_filtered_items()
        start_idx = self.current_page * self.items_per_page
        page_items = items[start_idx:start_idx + self.items_per_page]

        if self.active_tab == "char_rates":
            if not page_items:
                embed.add_field(name="조회 결과 없음", value="선택한 조건에 해당하는 캐릭터가 없습니다.", inline=False)
            else:
                lines = []
                for c_stat in page_items:
                    unowned_c = c_stat["total_count"] - c_stat["owned_count"]
                    badge = "👑 **[컴플리트!]**" if unowned_c == 0 and c_stat["total_count"] > 0 else f"*(미획득 `{unowned_c}종`)*"
                    lines.append(
                        f"• **{c_stat['char_name']}** (`{c_stat['unit']}`)\n"
                        f"  └ {c_stat['bar']} **`{c_stat['rate']:.1f}%`** (`{c_stat['owned_count']}/{c_stat['total_count']}종`) {badge}"
                    )
                full_text = "\n".join(lines)
                if len(full_text) <= 1000:
                    embed.add_field(
                        name=f"📊 캐릭터별 수집률 현황 (페이지 {self.current_page + 1} / {self.max_page + 1})",
                        value=full_text,
                        inline=False
                    )
                else:
                    mid = (len(lines) + 1) // 2
                    embed.add_field(
                        name=f"📊 캐릭터별 수집률 현황 (페이지 {self.current_page + 1} / {self.max_page + 1}) - 1",
                        value="\n".join(lines[:mid]),
                        inline=False
                    )
                    embed.add_field(
                        name=f"📊 캐릭터별 수집률 현황 (페이지 {self.current_page + 1} / {self.max_page + 1}) - 2",
                        value="\n".join(lines[mid:]),
                        inline=False
                    )
        elif self.active_tab == "unowned":
            if not page_items:
                embed.add_field(
                    name="🎉 미획득 카드가 없습니다!",
                    value="해당 필터 조건의 모든 카드를 100% 수집 완료했습니다!",
                    inline=False
                )
            else:
                lines = []
                for idx, c in enumerate(page_items, start=start_idx + 1):
                    unit_str = f"{c['unit']}" + (f" ({c['support_unit']})" if c.get("support_unit") else "")
                    lines.append(
                        f"**{idx}.** 🔒 `[{c.get('limit_label', '통상')}]` **{c['rarity_label']} [{c['prefix']}] {c['char_name']}**\n"
                        f"   └ 🏷️ {unit_str} · {c.get('attr', '✨')} · 도감 ID: `{c['id']}` *(미보유)*"
                    )
                full_text = "\n".join(lines)
                if len(full_text) <= 1000:
                    embed.add_field(
                        name=f"🔒 아직 획득하지 못한 카드 목록 (페이지 {self.current_page + 1} / {self.max_page + 1})",
                        value=full_text,
                        inline=False
                    )
                else:
                    mid = (len(lines) + 1) // 2
                    embed.add_field(
                        name=f"🔒 아직 획득하지 못한 카드 목록 (페이지 {self.current_page + 1} / {self.max_page + 1}) - 1",
                        value="\n".join(lines[:mid]),
                        inline=False
                    )
                    embed.add_field(
                        name=f"🔒 아직 획득하지 못한 카드 목록 (페이지 {self.current_page + 1} / {self.max_page + 1}) - 2",
                        value="\n".join(lines[mid:]),
                        inline=False
                    )
        else:
            if not page_items:
                embed.add_field(
                    name="📭 보유한 카드가 없습니다",
                    value="`/프로세카뽑기` 명령어로 첫 카드를 수집해 보세요!",
                    inline=False
                )
            else:
                lines = []
                for idx, c in enumerate(page_items, start=start_idx + 1):
                    lock_icon = "🔒 " if c.get("locked") else ""
                    lines.append(
                        f"**{idx}.** ✨ {lock_icon}`[{c.get('limit_label', '통상')}]` **{c['rarity_label']} [{c['prefix']}] {c['char_name']}** (`x{c.get('count', 1)}장`)\n"
                        f"   └ 🏷️ {c.get('unit', '')} · {c.get('attr', '✨')} · 도감 ID: `{c['id']}`"
                    )
                full_text = "\n".join(lines)
                if len(full_text) <= 1000:
                    embed.add_field(
                        name=f"✨ 보유 완료 도감 목록 (페이지 {self.current_page + 1} / {self.max_page + 1})",
                        value=full_text,
                        inline=False
                    )
                else:
                    mid = (len(lines) + 1) // 2
                    embed.add_field(
                        name=f"✨ 보유 완료 도감 목록 (페이지 {self.current_page + 1} / {self.max_page + 1}) - 1",
                        value="\n".join(lines[:mid]),
                        inline=False
                    )
                    embed.add_field(
                        name=f"✨ 보유 완료 도감 목록 (페이지 {self.current_page + 1} / {self.max_page + 1}) - 2",
                        value="\n".join(lines[mid:]),
                        inline=False
                    )

        embed.set_footer(text="상단 버튼으로 [캐릭터별 수집률 %] / [🔒 미획득 카드] / [✨ 보유 카드] 탭을 자유롭게 전환하세요!")
        return embed

    @discord.ui.button(label="📊 캐릭터별 수집률(%)", style=discord.ButtonStyle.primary, row=0)
    async def tab_char_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.stats = await asyncio.to_thread(core.get_card_pokedex_stats, self.guild_id, self.user.id)
        self.active_tab = "char_rates"
        if self.filter_val in ("R4", "RB", "R3", "LIMITED"):
            self.filter_val = "ALL"
            self.filter_label = "전체 (26명)"
        self.current_page = 0
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔒 미획득 카드", style=discord.ButtonStyle.secondary, row=0)
    async def tab_unowned_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.stats = await asyncio.to_thread(core.get_card_pokedex_stats, self.guild_id, self.user.id)
        self.active_tab = "unowned"
        if self.filter_val in ("HIGH_RATE", "INCOMPLETE"):
            self.filter_val = "ALL"
            self.filter_label = "전체 카드"
        self.current_page = 0
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="✨ 보유 카드", style=discord.ButtonStyle.secondary, row=0)
    async def tab_owned_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.stats = await asyncio.to_thread(core.get_card_pokedex_stats, self.guild_id, self.user.id)
        self.active_tab = "owned"
        if self.filter_val in ("HIGH_RATE", "INCOMPLETE"):
            self.filter_val = "ALL"
            self.filter_label = "전체 카드"
        self.current_page = 0
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = min(self.max_page, self.current_page + 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="🔍 유닛 / 성급 / 수집률 정렬 필터 선택...",
        row=1,
        options=[
            discord.SelectOption(label="전체 보기", value="ALL", description="모든 유닛 및 성급 표시"),
            discord.SelectOption(label="🏆 수집률 높은 캐릭터순 (수집률 탭)", value="HIGH_RATE", description="수집률(%)이 높은 캐릭터부터 정렬"),
            discord.SelectOption(label="🎯 미완성 캐릭터만 보기 (수집률 탭)", value="INCOMPLETE", description="아직 100%를 채우지 못한 캐릭터만 표시"),
            discord.SelectOption(label="★★★★ (4성 카드만)", value="R4", description="4성 카드만 필터링"),
            discord.SelectOption(label="🎀 생일 한정만", value="RB", description="생일 한정 카드만 필터링"),
            discord.SelectOption(label="★★★ (3성 카드만)", value="R3", description="3성 카드만 필터링"),
            discord.SelectOption(label="✨ 한정/페스/생일만", value="LIMITED", description="통상 제외 모든 한정 카드만 표시"),
            discord.SelectOption(label="Leo/need", value="U_Leo/need"),
            discord.SelectOption(label="MORE MORE JUMP!", value="U_MORE MORE JUMP!"),
            discord.SelectOption(label="Vivid BAD SQUAD", value="U_Vivid BAD SQUAD"),
            discord.SelectOption(label="원더랜즈×쇼타임", value="U_원더랜즈×쇼타임"),
            discord.SelectOption(label="25시, 나이트 코드에서.", value="U_25시, 나이트 코드에서."),
            discord.SelectOption(label="버츄얼 싱어", value="U_버츄얼 싱어")
        ]
    )
    async def filter_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        self.filter_val = val
        label_map = {
            "ALL": "전체",
            "HIGH_RATE": "수집률 높은순",
            "INCOMPLETE": "미완성 캐릭터만",
            "R4": "★★★★ (4성)",
            "RB": "🎀 생일 한정",
            "R3": "★★★ (3성)",
            "LIMITED": "한정/페스/생일만"
        }
        self.filter_label = label_map.get(val, val.replace("U_", "유닛: "))
        self.current_page = 0
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="🖼️ 현재 페이지 카드 일러스트 미리보기...",
        row=2,
        options=[discord.SelectOption(label="카드 선택", value="NONE")]
    )
    async def preview_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        cid_val = select.values[0]
        if cid_val == "NONE":
            await core.safe_defer(interaction)
            return
        pool = self.get_filtered_items()
        target_card = next((c for c in pool if str(c.get("id")) == cid_val), None)
        if not target_card:
            await core.safe_send_response(interaction, "❌ 선택한 카드를 찾을 수 없습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        init_mode = "after_training" if core.can_card_awaken(target_card) else "normal"
        status_txt = "✨ 보유 완료" if target_card.get("count", 0) > 0 else "🔒 미획득 (위시리스트 대상)"
        p_embed = discord.Embed(
            title=f"📖 도감 일러스트 미리보기 — [{target_card.get('limit_label', '통상')}] {target_card['rarity_label']} [{target_card['prefix']}] {target_card['char_name']}",
            description=(
                f"• **도감 상태:** **{status_txt}**\n"
                f"• **소속 유닛:** `{target_card.get('unit', '-')}` · **속성:** {target_card.get('attr', '✨')} (도감 ID: `{target_card.get('id')}`)"
            ),
            color=discord.Color.from_rgb(255, 105, 180)
        )
        img_bytes, filename = await asyncio.to_thread(core.fetch_proseka_card_image_bytes, target_card, init_mode)
        if img_bytes and filename:
            file = discord.File(io.BytesIO(img_bytes), filename=filename)
            p_embed.set_image(url=f"attachment://{filename}")
            await interaction.followup.send(embed=p_embed, file=file, ephemeral=True)
        else:
            p_embed.set_image(url=core.get_proseka_card_image_url(target_card, init_mode))
            await interaction.followup.send(embed=p_embed, ephemeral=True)


class GuildGachaResetConfirmView(core.SafeView):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=60)
        self.guild = guild

    @discord.ui.button(label="⚠️ 이 서버 캐릭터 데이터 초기화 실행", style=discord.ButtonStyle.danger)
    async def confirm_guild_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, "❌ 서버 관리자만 실행할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        g_key = str(self.guild.id)
        if g_key in data.get("gacha_users", {}):
            del data["gacha_users"][g_key]
            await asyncio.to_thread(core.save_data, data)

        embed = discord.Embed(
            title="🔄 서버 캐릭터 데이터 초기화 완료",
            description=f"**{self.guild.name}** 서버의 모든 유저 프로세카 캐릭터 보관함이 초기화되었습니다.",
            color=discord.Color.red()
        )
        await interaction.edit_original_response(content=None, embed=embed, view=None)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def cancel_guild_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="✅ 초기화 취소됨", description="서버 캐릭터 데이터가 안전하게 유지됩니다.", color=discord.Color.blue())
        await interaction.response.edit_message(content=None, embed=embed, view=None)


class AllGachaResetConfirmView(core.SafeView):
    def __init__(self, bot_instance):
        super().__init__(timeout=60)
        self.bot_instance = bot_instance

    @discord.ui.button(label="🚨 전체 서버 캐릭터 데이터 초기화 실행", style=discord.ButtonStyle.danger)
    async def confirm_all_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.bot_instance.is_bot_owner_user(interaction.user):
            await core.safe_send_response(interaction, "❌ 봇주인(Bot Owner)만 실행할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        data["gacha_users"] = {}
        data["gacha_pickup"] = copy.deepcopy(core.DEFAULT_CONFIG["gacha_pickup"])
        await asyncio.to_thread(core.save_data, data)

        embed = discord.Embed(
            title="🚨 전체 서버 캐릭터 데이터 초기화 완료",
            description="봇이 소속된 **모든 서버의 프로세카 캐릭터 보관함 데이터 및 픽업 설정**이 완전히 초기화되었습니다.",
            color=discord.Color.red()
        )
        await interaction.edit_original_response(content=None, embed=embed, view=None)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def cancel_all_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="✅ 초기화 취소됨", description="전체 캐릭터 데이터가 안전하게 유지됩니다.", color=discord.Color.blue())
        await interaction.response.edit_message(content=None, embed=embed, view=None)


# ==========================================
# 프로세카 한섭 이벤트 미래시 달력 & 상세 타임라인 View
# ==========================================
class EventForecastSelect(discord.ui.Select):
    """월별 미래시 이벤트 중 상세 카드를 확인할 이벤트를 선택하는 드롭다운"""
    def __init__(self, events_list: list, selected_id: int | None = None):
        options = []
        for ev in events_list[:25]:
            is_sel = (selected_id == ev["id"])
            tag = "🌟페스" if ev.get("is_fes") else ("🎀한정" if ev.get("is_limited") else "🎵통상")
            label = f"[{ev['id']}] {ev['name']}"[:95]
            desc = f"{ev['kr_estimated_start']}~{ev['kr_estimated_end']} · {tag} · {ev.get('unit', '')}"[:98]
            options.append(discord.SelectOption(
                label=label,
                value=str(ev["id"]),
                description=desc,
                default=is_sel
            ))
        if not options:
            options = [discord.SelectOption(label="예정된 이벤트가 없습니다", value="NONE")]
        super().__init__(
            placeholder="🔍 상세 카드와 가챠 정보를 확인할 이벤트를 선택하세요...",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        if val == "NONE":
            await core.safe_defer(interaction)
            return
        self.view.selected_event_id = int(val)
        self.view.update_components()
        await interaction.response.edit_message(embed=self.view.build_embed(), view=self.view)


class EventForecastView(core.SafeView):
    """프로세카 한섭 이벤트 미래시 달력 (월별 아스키 그리드 + 상세 타임라인 카드 + 일섭 비교)"""
    def __init__(self, user: discord.User, year: int, month: int, selected_event_id: int | None = None):
        super().__init__(timeout=600)
        self.user = user
        self.year = year
        self.month = month
        self.selected_event_id = selected_event_id
        self.update_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await super().interaction_check(interaction)
        if interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 미래시 달력은 **{self.user.display_name}**님이 조회한 창입니다. `/미래시` 명령어로 직접 조회해 보세요!",
                ephemeral=True
            )
            return False
        return True

    def update_components(self):
        self.clear_items()
        cal_data = core.build_monthly_event_forecast_calendar(self.year, self.month)
        events_in_month = cal_data["events_in_month"]
        all_events = core.get_event_forecast_list()

        target_list = events_in_month if events_in_month else all_events
        if not self.selected_event_id and events_in_month:
            self.selected_event_id = events_in_month[0]["id"]
        elif not self.selected_event_id and all_events:
            self.selected_event_id = all_events[0]["id"]

        self.add_item(EventForecastSelect(target_list, self.selected_event_id))

        # 네비게이션 버튼 (Row 1)
        prev_btn = discord.ui.Button(label="◀ 이전달", style=discord.ButtonStyle.secondary, row=1)
        prev_btn.callback = self.on_prev_month
        self.add_item(prev_btn)

        cur_btn = discord.ui.Button(label="📅 이번달", style=discord.ButtonStyle.primary, row=1)
        cur_btn.callback = self.on_current_month
        self.add_item(cur_btn)

        next_btn = discord.ui.Button(label="다음달 ▶", style=discord.ButtonStyle.secondary, row=1)
        next_btn.callback = self.on_next_month
        self.add_item(next_btn)

        all_list_btn = discord.ui.Button(label="📜 전체 미래시 목록", style=discord.ButtonStyle.success, row=1)
        all_list_btn.callback = self.on_show_all_list
        self.add_item(all_list_btn)

    def build_embed(self) -> discord.Embed:
        cal_data = core.build_monthly_event_forecast_calendar(self.year, self.month)
        events_in_month = cal_data["events_in_month"]
        all_events = core.get_event_forecast_list()

        selected_ev = None
        if self.selected_event_id:
            selected_ev = next((e for e in all_events if e["id"] == self.selected_event_id), None)
        if not selected_ev and events_in_month:
            selected_ev = events_in_month[0]

        embed = discord.Embed(
            title=f"📅 프로세카 한섭 이벤트 미래시 달력 ({cal_data['month_label']})",
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )

        cal_box = (
            f"```text\n"
            f"{cal_data['calendar_ascii']}\n"
            f"```\n"
            f"📌 **범례:** `🚩 시작일` · `🟢 진행 중` · `🏁 종료일` · `· 평일`"
        )
        embed.add_field(name=f"🗓️ {self.year}년 {self.month:02d}월 한섭 예상 일정표", value=cal_box, inline=False)

        if selected_ev:
            ev_type_label = core.EVENT_TYPE_MAP.get(selected_ev.get("eventType", ""), selected_ev.get("eventType", "이벤트"))
            tag = "🌟 컬러풀 페스티벌 (컬페한정)" if selected_ev.get("is_fes") else ("🎀 기간 한정 가챠" if selected_ev.get("is_limited") else "🎵 통상 가챠")
            
            cards_lines = []
            for c in selected_ev.get("featured_cards", []):
                cards_lines.append(f"  • {c}")
            cards_str = "\n".join(cards_lines) if cards_lines else "  • 정보 확인 중"

            detail_val = (
                f"• **이벤트 명:** `{selected_ev['name']}`\n"
                f"  └ *일섭 원제: {selected_ev.get('jp_name', '-') }*\n"
                f"• **이벤트 유형:** `{ev_type_label}` · **유닛:** `{selected_ev.get('unit', '-')}` · **속성:** {selected_ev.get('attribute', '-')}\n"
                f"• **🇰🇷 한섭 예상 기간:** `{selected_ev['kr_estimated_start']}` ~ `{selected_ev['kr_estimated_end']}`\n"
                f"• **🇯🇵 일섭 원본 기간:** `{selected_ev['jp_start']}` ~ `{selected_ev['jp_end']}` *(약 1년 선행)*\n"
                f"• **🎰 연계 가챠 배너:** `{selected_ev.get('gacha_name', '-')}` (`{tag}`)\n"
                f"• **🌟 주요 픽업 카드:**\n{cards_str}\n"
                f"• **🎵 이벤트 테마곡:** `{selected_ev.get('theme_song', '-')}`"
            )
            embed.add_field(name=f"🏆 [이벤트 상세] {selected_ev['name']}", value=detail_val, inline=False)
        else:
            embed.add_field(name="🏆 이벤트 상세", value="이번 달에는 예정된 이벤트가 없거나 일정을 산출 중입니다.", inline=False)

        if events_in_month:
            summary_lines = []
            for ev in events_in_month:
                tag = "🌟컬페" if ev.get("is_fes") else ("🎀한정" if ev.get("is_limited") else "🎵통상")
                summary_lines.append(f"• `[{ev['kr_estimated_start'][5:]} ~ {ev['kr_estimated_end'][5:]}]` **{ev['name']}** ({ev['unit']} · `{tag}`)")
            embed.add_field(name=f"📋 이번 달 예정 이벤트 ({len(events_in_month)}개)", value="\n".join(summary_lines), inline=False)

        embed.set_footer(text=cal_data["disclaimer"])
        return embed

    async def on_prev_month(self, interaction: discord.Interaction):
        if self.month == 1:
            self.year -= 1
            self.month = 12
        else:
            self.month -= 1
        self.selected_event_id = None
        self.update_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_next_month(self, interaction: discord.Interaction):
        if self.month == 12:
            self.year += 1
            self.month = 1
        else:
            self.month += 1
        self.selected_event_id = None
        self.update_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_current_month(self, interaction: discord.Interaction):
        now = datetime.datetime.now(core.KST)
        self.year = now.year
        self.month = now.month
        self.selected_event_id = None
        self.update_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_show_all_list(self, interaction: discord.Interaction):
        all_events = core.get_event_forecast_list()
        embed = discord.Embed(
            title="📜 프로세카 한섭 다가오는 이벤트 미래시 전체 목록",
            description="일본 서버(JP) 순서를 기반으로 한 다가오는 한국 서버(KR) 예상 일정입니다.",
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        for ev in all_events:
            tag = "🌟컬페한정" if ev.get("is_fes") else ("🎀한정" if ev.get("is_limited") else "🎵통상")
            val = (
                f"• **예상 기간:** `{ev['kr_estimated_start']}` ~ `{ev['kr_estimated_end']}`\n"
                f"• **일섭 원본:** `{ev['jp_start']}` ~ `{ev['jp_end']}`\n"
                f"• **유닛/가챠:** {ev['unit']} · `{ev['gacha_name']}` ({tag})\n"
                f"• **대표 픽업:** {', '.join(ev.get('featured_cards', [])[:2])}"
            )
            embed.add_field(name=f"🏆 [{ev['id']}] {ev['name']}", value=val, inline=False)
        embed.set_footer(text=core.FORECAST_DISCLAIMER)
        await core.safe_send_response(interaction, embed=embed, ephemeral=True)


class EventInfoView(core.SafeView):
    """실시간 이벤트 조회 시 미래시 달력으로 바로 연결하는 뷰"""
    def __init__(self, bot_instance, user: discord.User):
        super().__init__(timeout=300)
        self.bot_instance = bot_instance
        self.user = user

    @discord.ui.button(label="📅 한섭 이벤트 미래시 달력 보기", style=discord.ButtonStyle.primary, emoji="📅")
    async def open_forecast(self, interaction: discord.Interaction, button: discord.ui.Button):
        now = datetime.datetime.now(core.KST)
        view = EventForecastView(interaction.user, now.year, now.month)
        await core.safe_send_response(interaction, embed=view.build_embed(), view=view, ephemeral=True)


# ==========================================
# 프로세카 Cog 명령어 등록
# ==========================================
class GachaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="프로세카뽑기", description="프로세카 한국 서버 캐릭터를 뽑고 내 캐릭터 보관함에 저장합니다.")
    @app_commands.describe(횟수="1회 뽑기(단차) 또는 10회 뽑기(10연차 - ★3 이상 확정)를 선택하세요.")
    @app_commands.choices(횟수=[
        app_commands.Choice(name="🎵 1회 뽑기 (단차)", value=1),
        app_commands.Choice(name="🌈 10회 뽑기 (10연차 - ★3 이상 확정!)", value=10)
    ])
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
    async def proseka_pull_cmd(self, interaction: discord.Interaction, 횟수: app_commands.Choice[int] = None):
        can_pull, rem = check_and_update_gacha_cooldown(interaction.user.id)
        if not can_pull:
            await core.safe_send_response(
                interaction,
                content=f"⏳ **봇의 원활한 서비스를 위해, 뽑기 쿨타임입니다!** `{rem:.1f}초` 후에 다시 눌러주세요.",
                ephemeral=True
            )
            return

        await core.safe_defer(interaction)
        pull_count = 횟수.value if 횟수 else 1

        data = await asyncio.to_thread(core.load_data)
        pickup_cfg = data.get("gacha_pickup", core.DEFAULT_CONFIG["gacha_pickup"])
        drawn = core.draw_proseka_cards(pickup_cfg, count=pull_count)

        if not drawn:
            await interaction.followup.send("❌ 한국 서버 캐릭터 DB를 불러오지 못했습니다.")
            return

        guild_id = interaction.guild_id or 0
        await asyncio.to_thread(core.save_pulled_cards_to_user, guild_id, interaction.user.id, drawn)

        repull_view = GachaPullAgainView(interaction.user)
        await send_gacha_pull_result(interaction, drawn, pickup_cfg, pull_count, repull_view)

    @proseka_pull_cmd.error
    async def proseka_pull_cmd_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            rem = error.retry_after
            msg = f"⏳ **봇의 원활한 서비스를 위해, 뽑기 쿨타임입니다!** `{rem:.1f}초` 후에 다시 눌러주세요."
            await core.safe_send_response(interaction, content=msg, ephemeral=True)
        else:
            err_msg = f"❌ 뽑기 처리 중 오류가 발생했습니다: `{error}`"
            await core.safe_send_response(interaction, err_msg, ephemeral=True)

    @app_commands.command(name="중복카드변환", description="2장 이상 중복 보유한 카드(원본 1장 및 🔒잠금 카드 제외)를 성급별 크리스탈로 일괄 변환합니다.")
    async def convert_duplicates_cmd(self, interaction: discord.Interaction):
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild_id or 0
        preview = await asyncio.to_thread(core.preview_duplicate_cards, guild_id, interaction.user.id)
        view = DuplicateConvertConfirmView(guild_id, interaction.user, preview)
        await core.safe_send_response(interaction, embed=view.build_preview_embed(), view=view, ephemeral=True)

    @app_commands.command(name="프로세카확률목록", description="한국 서버 모든 캐릭터(한정 포함) 텍스트 및 확률 목록을 5개씩 페이지로 확인합니다.")
    async def proseka_rate_list_cmd(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        pickup_cfg = data.get("gacha_pickup", core.DEFAULT_CONFIG["gacha_pickup"])
        prob_cards = core.calculate_card_probabilities(pickup_cfg)

        view = ProsekaRatePaginationView(prob_cards, pickup_cfg, items_per_page=5)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    @app_commands.command(name="내캐릭터", description="내가 뽑은 프로세카 캐릭터를 검색/정렬하고 일러스트(각성 전·후), 잠금(🔒), 중복 변환을 관리합니다.")
    @app_commands.describe(
        유저="(선택) 다른 유저의 캐릭터 보관함을 구경할 수 있습니다.",
        검색어="(선택) 캐릭터 이름, 카드명, 유닛, 한정 여부 등으로 보유 카드를 검색합니다 (예: 카나데, 한정)"
    )
    async def my_characters_cmd(self, interaction: discord.Interaction, 유저: discord.User = None, 검색어: str = None):
        await core.safe_defer(interaction)
        target_user = 유저 or interaction.user
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id or 0)
        u_key = str(target_user.id)

        user_cards_dict = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})
        card_list = list(user_cards_dict.values())

        clean_kw = 검색어.strip() if 검색어 and 검색어.strip() else None
        if clean_kw:
            kw_lower = clean_kw.lower()
            card_list = [
                c for c in card_list
                if kw_lower in c.get("char_name", "").lower()
                or kw_lower in c.get("prefix", "").lower()
                or kw_lower in c.get("unit", "").lower()
                or kw_lower in (c.get("support_unit") or "").lower()
                or kw_lower in c.get("limit_label", "").lower()
                or kw_lower in c.get("attr", "").lower()
                or kw_lower in c.get("rarity_label", "").lower()
            ]

        view = MyInventoryView(target_user, card_list, items_per_page=10, search_keyword=clean_kw, guild_id=interaction.guild_id or 0)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    @app_commands.command(name="카드도감", description="캐릭터별 수집률(%)과 아직 획득하지 못한 미보유 카드를 별도 탭으로 확인하는 전체 카드 도감을 엽니다.")
    @app_commands.describe(
        유저="(선택) 다른 유저의 카드 도감 수집률과 미획득 카드를 확인합니다.",
        초기탭="(선택) 처음 열릴 도감 탭을 선택합니다 (기본: 캐릭터별 수집률 %)"
    )
    @app_commands.choices(초기탭=[
        app_commands.Choice(name="📊 캐릭터별 도감 수집률 (%)", value="char_rates"),
        app_commands.Choice(name="🔒 아직 획득하지 못한 미보유 카드", value="unowned"),
        app_commands.Choice(name="✨ 보유 완료 도감 카드", value="owned")
    ])
    async def card_pokedex_cmd(
        self,
        interaction: discord.Interaction,
        유저: discord.User = None,
        초기탭: app_commands.Choice[str] = None
    ):
        await core.safe_defer(interaction)
        target_user = 유저 or interaction.user
        guild_id = interaction.guild_id or 0
        tab_key = 초기탭.value if 초기탭 else "char_rates"

        stats = await asyncio.to_thread(core.get_card_pokedex_stats, guild_id, target_user.id)
        view = CardPokedexView(target_user, stats, guild_id=guild_id, initial_tab=tab_key)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    @app_commands.command(name="카드교환", description="크리스탈 100개를 사용하여 다른 유저와 보유 카드를 1:1로 교환합니다 (미입력 시 교환 장터 스튜디오 실행).")
    @app_commands.autocomplete(
        내카드=core.owned_card_autocomplete,
        상대카드=core.target_user_card_autocomplete
    )
    @app_commands.describe(
        상대유저="카드를 교환할 대상 유저를 선택하세요.",
        내카드="(선택) 상대방에게 건네줄 나의 보유 카드 (비워두면 드롭다운 교환 스튜디오 실행)",
        상대카드="(선택) 상대방으로부터 받을 카드 (비워두면 드롭다운 교환 스튜디오 실행)"
    )
    async def card_trade_cmd(
        self,
        interaction: discord.Interaction,
        상대유저: discord.User,
        내카드: Optional[str] = None,
        상대카드: Optional[str] = None
    ):
        if 상대유저.bot or 상대유저.id == interaction.user.id:
            await core.safe_send_response(interaction, "❌ 본인이나 봇과는 카드를 교환할 수 없습니다.", ephemeral=True)
            return

        if not 내카드 or not 상대카드 or 내카드 == "NONE" or 상대카드 == "NONE":
            await core.safe_defer(interaction, ephemeral=True)
            data = await asyncio.to_thread(core.load_data)
            g_key = str(interaction.guild_id or 0)
            r_key = str(interaction.user.id)
            t_key = str(상대유저.id)
            req_prof = core.ensure_user_profile(data, r_key, interaction.user.display_name)
            my_crystals = req_prof.get("crystals", 0)
            if my_crystals < 100:
                await interaction.followup.send(
                    f"❌ **카드 교환에는 크리스탈 `100개`가 필요합니다!**\n"
                    f"• 현재 보유 크리스탈: `{my_crystals:,}개` (`/출석체크` 또는 `/중복카드변환`으로 획득 가능)",
                    ephemeral=True
                )
                return
            req_cards = data.get("gacha_users", {}).get(g_key, {}).get(r_key, {}).get("cards", {})
            tgt_cards = data.get("gacha_users", {}).get(g_key, {}).get(t_key, {}).get("cards", {})
            if not req_cards:
                await interaction.followup.send("❌ 보유한 카드가 없습니다. `/프로세카뽑기`로 먼저 캐릭터를 뽑아주세요!", ephemeral=True)
                return
            if not tgt_cards:
                await interaction.followup.send(f"❌ **{상대유저.display_name}**님이 아직 이 서버에서 보유한 카드가 없습니다.", ephemeral=True)
                return
            studio_view = InteractiveCardTradeStudioView(interaction.guild_id or 0, interaction.user, 상대유저, req_cards, tgt_cards, my_crystals)
            if 내카드 and 내카드 in req_cards and not req_cards[내카드].get("locked", False):
                studio_view.selected_my_cid = 내카드
            if 상대카드 and 상대카드 in tgt_cards and not tgt_cards[상대카드].get("locked", False):
                studio_view.selected_tgt_cid = 상대카드
            await interaction.followup.send(embed=studio_view.build_embed(), view=studio_view, ephemeral=True)
            return

        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id or 0)
        r_key = str(interaction.user.id)
        t_key = str(상대유저.id)

        my_crystals = data.get("user_profiles", {}).get(r_key, {}).get("crystals", 0)
        if my_crystals < 100:
            await interaction.followup.send(
                f"❌ **카드 교환에는 크리스탈 `100개`가 필요합니다!**\n"
                f"• 현재 보유 크리스탈: `{my_crystals:,}개` (`/출석체크` 또는 `/중복카드변환`으로 획득 가능)",
                ephemeral=True
            )
            return

        req_cards = data.get("gacha_users", {}).get(g_key, {}).get(r_key, {}).get("cards", {})
        tgt_cards = data.get("gacha_users", {}).get(g_key, {}).get(t_key, {}).get("cards", {})

        if 내카드 not in req_cards or req_cards[내카드].get("count", 0) < 1:
            await interaction.followup.send("❌ 선택한 `내카드`를 보유하고 있지 않습니다.", ephemeral=True)
            return
        if 상대카드 not in tgt_cards or tgt_cards[상대카드].get("count", 0) < 1:
            await interaction.followup.send(f"❌ {상대유저.display_name}님이 선택한 `상대카드`를 보유하고 있지 않습니다.", ephemeral=True)
            return
        if 내카드 == 상대카드:
            await interaction.followup.send("❌ 동일한 카드는 서로 교환할 수 없습니다.", ephemeral=True)
            return
        if req_cards[내카드].get("locked", False):
            await interaction.followup.send("🔒 선택한 `내카드`가 **잠금 보호** 상태입니다! 교환하려면 `/내캐릭터`에서 잠금을 먼저 해제해 주세요.", ephemeral=True)
            return
        if tgt_cards[상대카드].get("locked", False):
            await interaction.followup.send(f"🔒 {상대유저.display_name}님의 해당 카드는 **잠금 보호** 상태여서 교환을 요청할 수 없습니다.", ephemeral=True)
            return

        my_c = req_cards[내카드]
        tgt_c = tgt_cards[상대카드]

        embed = discord.Embed(
            title="🔄 프로세카 1:1 카드 교환 신청 도착!",
            description=(
                f"{상대유저.mention}님! {interaction.user.mention}님이 **1:1 카드 교환**을 요청했습니다.\n"
                "아래 내역과 일러스트를 확인하시고 동의하시면 **`[🤝 교환 수락하기]`** 버튼을 눌러주세요.\n\n"
                f"📤 **{interaction.user.display_name}님이 제공하는 카드:**\n"
                f"└ `[{my_c.get('limit_label', '통상')}]` **{my_c['rarity_label']} [{my_c['prefix']}] {my_c['char_name']}** (`Lv.{my_c.get('level', 1)}` · 보유: `{my_c.get('count', 1)}장`)\n\n"
                f"📥 **{상대유저.display_name}님이 제공하는 카드:**\n"
                f"└ `[{tgt_c.get('limit_label', '통상')}]` **{tgt_c['rarity_label']} [{tgt_c['prefix']}] {tgt_c['char_name']}** (`Lv.{tgt_c.get('level', 1)}` · 보유: `{tgt_c.get('count', 1)}장`)\n\n"
                f"💎 **교환 비용:** 신청자({interaction.user.display_name})의 크리스탈 `100개` (수락 시 차감)"
            ),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_thumbnail(url=core.get_proseka_card_image_url(my_c, "auto"))
        view = CardTradeAcceptView(interaction.guild_id or 0, interaction.user, 상대유저, my_c, tgt_c)
        await interaction.followup.send(content=상대유저.mention, embed=embed, view=view)

    @app_commands.command(name="카드선물", description="크리스탈 50개를 사용하여 나의 파트너(짝꿍)에게 보유 카드를 선물합니다.")
    @app_commands.autocomplete(내카드=core.owned_card_autocomplete)
    @app_commands.describe(
        내카드="파트너에게 선물할 나의 보유 카드를 선택하세요.",
        메시지="(선택) 파트너에게 함께 전할 짧은 선물 메시지"
    )
    async def card_gift_cmd(
        self,
        interaction: discord.Interaction,
        내카드: str,
        메시지: str = None
    ):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(interaction.user.id)
        partner_id = data.get("user_profiles", {}).get(u_key, {}).get("partner_id")

        if not partner_id:
            await interaction.followup.send(
                "❌ **파트너(짝꿍)가 등록되어 있지 않습니다!**\n"
                "`/파트너` 명령어로 파트너를 먼저 맺은 뒤 카드를 선물할 수 있습니다.",
                ephemeral=True
            )
            return

        ok, msg, gifted_c, rem_crystals = await asyncio.to_thread(
            core.execute_partner_gift,
            interaction.guild_id or 0,
            interaction.user.id,
            int(partner_id),
            내카드
        )

        if not ok:
            await interaction.followup.send(f"❌ **카드 선물 실패:** {msg}", ephemeral=True)
            return

        memo_line = f"\n💌 **선물 메시지:** `\"{메시지}\"`" if 메시지 else ""
        embed = discord.Embed(
            title="🎁 파트너 카드 선물 완료!",
            description=(
                f"💖 {interaction.user.mention}님이 파트너 <@{partner_id}>님에게 카드를 선물했습니다!\n\n"
                f"🎀 **선물한 카드:**\n"
                f"└ `[{gifted_c.get('limit_label', '통상')}]` **{gifted_c['rarity_label']} [{gifted_c['prefix']}] {gifted_c['char_name']}**"
                f"{memo_line}\n\n"
                f"💎 **소모 재화:** 크리스탈 `50개` 차감 (잔여: `{rem_crystals:,}개`)"
            ),
            color=discord.Color.from_rgb(255, 105, 180),
            timestamp=datetime.datetime.now(core.KST)
        )

        img_bytes, filename = await asyncio.to_thread(core.fetch_proseka_card_image_bytes, gifted_c, "auto")
        if img_bytes and filename:
            file = discord.File(io.BytesIO(img_bytes), filename=filename)
            embed.set_image(url=f"attachment://{filename}")
            await interaction.followup.send(content=f"<@{partner_id}>", embed=embed, file=file)
        else:
            embed.set_image(url=core.get_proseka_card_image_url(gifted_c, "auto"))
            await interaction.followup.send(content=f"<@{partner_id}>", embed=embed)

    @app_commands.command(name="이벤트", description="프로세카 한국 서버(KR) 또는 일본 서버(JP)의 실시간 이벤트 및 가챠 배너 정보를 확인합니다.")
    @app_commands.describe(서버="조회할 프로세카 서버를 선택하세요 (기본: 한국 서버)")
    @app_commands.choices(서버=[
        app_commands.Choice(name="🇰🇷 한국 서버 (KR)", value="kr"),
        app_commands.Choice(name="🇯🇵 일본 서버 (JP)", value="jp")
    ])
    async def proseka_event_cmd(self, interaction: discord.Interaction, 서버: app_commands.Choice[str] = None):
        await core.safe_defer(interaction)
        server_key = 서버.value if 서버 else "kr"

        info = await asyncio.to_thread(core.fetch_live_event_and_gacha_info, server_key)
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
                value=(
                    f"• **종류:** {ev_type} (ID: `{ev.get('id')}`)\n"
                    f"• **기간:** `{start_dt}` ~ `{end_dt}` (KST)\n"
                    f"└ {galaxy_bar}"
                ),
                inline=False
            )
        else:
            embed.add_field(name="🏆 이벤트 정보", value="현재 이벤트 데이터를 불러올 수 없습니다.", inline=False)

        if gachas:
            g_lines = []
            for g in gachas[:5]:
                g_name = g.get("name", "가챠")
                g_end_ms = g.get("endAt", 0)
                g_end_dt = datetime.datetime.fromtimestamp(g_end_ms / 1000, tz=core.KST).strftime("%m/%d %H:%M") if g_end_ms else "-"
                g_lines.append(f"• **{g_name}** (종료: `{g_end_dt}`)")
            if len(gachas) > 5:
                g_lines.append(f"*...외 {len(gachas) - 5}개 배너 진행 중*")
            embed.add_field(name=f"🎰 현재 진행 중인 가챠 배너 ({len(gachas)}개)", value="\n".join(g_lines), inline=False)
        else:
            embed.add_field(name="🎰 현재 진행 중인 가챠 배너", value="현재 진행 중인 가챠 배너가 없습니다.", inline=False)

        action_view = EventInfoView(self.bot, interaction.user)
        if info.get("banner_bytes") and info.get("banner_filename"):
            file = discord.File(io.BytesIO(info["banner_bytes"]), filename=info["banner_filename"])
            embed.set_image(url=f"attachment://{info['banner_filename']}")
            await interaction.followup.send(embed=embed, file=file, view=action_view)
        else:
            await interaction.followup.send(embed=embed, view=action_view)

    @app_commands.command(name="미래시", description="프로세카 한국 서버의 다가오는 이벤트 미래시 일정을 월별 달력과 상세 타임라인 카드로 확인합니다.")
    @app_commands.describe(
        년도="(선택) 조회할 년도 (기본: 현재 년도)",
        월="(선택) 조회할 월 (1~12월, 기본: 현재 월)"
    )
    async def event_forecast_cmd(
        self,
        interaction: discord.Interaction,
        년도: int = None,
        월: int = None
    ):
        now = datetime.datetime.now(core.KST)
        target_year = 년도 if (년도 and 2020 <= 년도 <= 2035) else now.year
        target_month = 월 if (월 and 1 <= 월 <= 12) else now.month

        view = EventForecastView(interaction.user, target_year, target_month)
        await core.safe_send_response(interaction, embed=view.build_embed(), view=view)

    @app_commands.command(name="덱편성", description="보유한 카드 중 최대 5장을 골라 리더와 멤버로 나만의 5인 유닛 덱을 편성합니다.")
    @app_commands.autocomplete(
        리더=core.owned_card_autocomplete,
        멤버2=core.owned_card_autocomplete,
        멤버3=core.owned_card_autocomplete,
        멤버4=core.owned_card_autocomplete,
        멤버5=core.owned_card_autocomplete
    )
    @app_commands.describe(
        리더="덱의 중심이 될 리더 카드를 선택하세요 (보유 카드 자동완성)",
        멤버2="(선택) 2번 슬롯에 배치할 카드",
        멤버3="(선택) 3번 슬롯에 배치할 카드",
        멤버4="(선택) 4번 슬롯에 배치할 카드",
        멤버5="(선택) 5번 슬롯에 배치할 카드"
    )
    async def set_deck_cmd(
        self,
        interaction: discord.Interaction,
        리더: str,
        멤버2: str = None,
        멤버3: str = None,
        멤버4: str = None,
        멤버5: str = None
    ):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id or 0)
        u_key = str(interaction.user.id)

        user_cards_dict = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})
        if not user_cards_dict:
            await interaction.followup.send("❌ 보유한 카드가 없습니다. `/프로세카뽑기`로 먼저 캐릭터를 뽑아주세요!", ephemeral=True)
            return

        raw_slots = [리더, 멤버2, 멤버3, 멤버4, 멤버5]
        chosen_ids = []
        chosen_chars = set()
        for cid in raw_slots:
            if not cid or cid not in user_cards_dict or cid in chosen_ids:
                continue
            c = user_cards_dict[cid]
            char_ident = c.get("char_id") or c.get("char_name")
            if char_ident in chosen_chars:
                await interaction.followup.send(
                    f"❌ **동일 캐릭터 중복 편성 불가:** `{c.get('char_name')}` 카드가 덱에 2장 이상 포함되어 있습니다. 프로세카 덱은 서로 다른 5명의 캐릭터로만 구성할 수 있습니다!",
                    ephemeral=True
                )
                return
            chosen_chars.add(char_ident)
            chosen_ids.append(cid)

        if not chosen_ids:
            await interaction.followup.send("❌ 보유 중인 올바른 카드를 목록에서 선택해 주세요.", ephemeral=True)
            return

        profile = core.ensure_user_profile(data, u_key, interaction.user.display_name)
        profile["deck"] = chosen_ids
        await asyncio.to_thread(core.save_data, data)

        deck_lines = []
        total_deck_power = 0
        for idx, cid in enumerate(chosen_ids, start=1):
            c = user_cards_dict[cid]
            p_val = core.get_card_power(c)
            total_deck_power += p_val
            cur_lvl = c.get("level", 1)
            role_badge = "👑 **[리더]**" if idx == 1 else f"🎸 **[멤버 {idx}]**"
            deck_lines.append(f"{role_badge} `[{c.get('limit_label', '통상')}]` **{c['rarity_label']} [{c['prefix']}] {c['char_name']}** (`Lv.{cur_lvl}` · `⚔️ {p_val:,}`)")

        embed = discord.Embed(
            title=f"🎸 {interaction.user.display_name}님의 5인 유닛 덱 편성 완료! (총 종합력: ⚔️ {total_deck_power:,})",
            description="\n".join(deck_lines) + "\n\n*편성된 덱은 `/내프로필` 및 `/메뉴`에서 언제든 함께 확인할 수 있습니다. (`/카드강화`로 종합력 상승 가능!)*",
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )

        leader_card = user_cards_dict[chosen_ids[0]]
        img_bytes, filename = await asyncio.to_thread(core.fetch_proseka_card_image_bytes, leader_card, "auto")
        if img_bytes and filename:
            file = discord.File(io.BytesIO(img_bytes), filename=filename)
            embed.set_image(url=f"attachment://{filename}")
            await interaction.followup.send(embed=embed, file=file)
        else:
            embed.set_image(url=core.get_proseka_card_image_url(leader_card, "auto"))
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="오시설정", description="내 프로필 카드에 표시할 최애(오시) 캐릭터를 설정합니다.")
    @app_commands.autocomplete(캐릭터=core.oshi_char_autocomplete)
    @app_commands.describe(캐릭터="나의 최애(오시) 프로세카 캐릭터를 선택하세요.")
    async def set_oshi_cmd(self, interaction: discord.Interaction, 캐릭터: str):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(interaction.user.id)
        profile = core.ensure_user_profile(data, u_key, interaction.user.display_name)
        profile["oshi"] = 캐릭터
        await asyncio.to_thread(core.save_data, data)

        embed = discord.Embed(
            title="💖 오시(최애) 캐릭터 설정 완료",
            description=(
                f"**{interaction.user.display_name}**님의 오시 캐릭터가 **`{캐릭터}`**(으)로 설정되었습니다!\n"
                "• `/내프로필` 실행 시 보유한 오시 카드 중 **가장 높은 등급의 일러스트**가 자동 표시됩니다.\n"
                "• `/출석체크` 시 오시 캐릭터의 세카이 대사가 우선 매칭됩니다."
            ),
            color=discord.Color.from_rgb(255, 105, 180)
        )
        await core.safe_send_response(interaction, embed=embed)

    @app_commands.command(name="내프로필", description="오시 대표 일러스트, 5인 덱, 서버/통합 출석, 보유 크리스탈, 은하수 잔디, 가챠 통계를 확인합니다.")
    @app_commands.describe(유저="(선택) 다른 유저의 프로필 카드를 확인합니다.")
    async def my_profile_cmd(self, interaction: discord.Interaction, 유저: discord.User = None):
        await core.safe_defer(interaction)
        target_user = 유저 or interaction.user
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id or 0)
        u_key = str(target_user.id)

        profile = core.ensure_user_profile(data, u_key, target_user.display_name)
        oshi_raw = profile.get("oshi")
        oshi_name = oshi_raw or "미설정 (`/오시설정`)"
        liked_music_count = len(profile.get("liked_music", []))
        deck_ids = profile.get("deck", [])
        partner_id = profile.get("partner_id")
        crystals = profile.get("crystals", 0)

        global_att = profile.get("attendance", {})
        guild_att = data.get("guild_attendance", {}).get(g_key, {}).get(u_key, {})

        g_total = guild_att.get("total_days", 0)
        g_streak = guild_att.get("streak", 0)
        all_total = global_att.get("total_days", 0)
        all_max = max(global_att.get("max_streak", 0), guild_att.get("max_streak", 0))

        grass_bar, _ = core.get_todo_galaxy_grass(profile)

        user_cards_dict = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})
        cards = list(user_cards_dict.values())

        total_pulls = sum(c.get("count", 1) for c in cards)
        total_unique = len(cards)
        total_db_cards = len(core.PROSEKA_KR_CARDS)
        collect_rate = (total_unique / total_db_cards * 100) if total_db_cards > 0 else 0.0

        star4_count = sum(c.get("count", 1) for c in cards if c.get("rarity_type") == "rarity_4")
        bday_count = sum(c.get("count", 1) for c in cards if c.get("rarity_type") == "rarity_birthday")
        oshi_cards = [c for c in cards if oshi_raw and c.get("char_name") == oshi_raw]
        oshi_card_count = sum(c.get("count", 1) for c in oshi_cards)
        oshi_char_id = next((cid for cid, info in core.CHARACTER_MAP.items() if info["name"] == oshi_raw), None)
        oshi_cos_str = ""
        if oshi_char_id:
            oshi_cos = core.get_user_equipped_costume(interaction.guild_id or 0, target_user.id, oshi_char_id)
            oshi_cos_str = f" · 👗`[{oshi_cos['name']}]`"

        embed = discord.Embed(
            title=f"🌟 {target_user.display_name}님의 norosi 프로필",
            color=discord.Color.from_rgb(255, 182, 193),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)
        embed.add_field(name="👑 나의 오시 (최애)", value=f"**{oshi_name}** (`{oshi_card_count}장`){oshi_cos_str}", inline=True)
        embed.add_field(name="💑 파트너 (짝꿍)", value=f"<@{partner_id}>" if partner_id else "미등록 (`/파트너`)", inline=True)
        embed.add_field(name="💎 보유 크리스탈", value=f"**`{crystals:,}개`**", inline=True)
        embed.add_field(name="🎰 누적 뽑기", value=f"`{total_pulls:,}회`", inline=True)
        embed.add_field(name="★★★★ / 🎀생일", value=f"`★4 {star4_count}장` · `🎀 {bday_count}장`", inline=True)
        embed.add_field(name="📚 도감 수집률", value=f"`{total_unique:,} / {total_db_cards:,}종 ({collect_rate:.1f}%)`", inline=True)

        ms = core.ensure_my_sekai(profile)
        ms_theme_name = core.MY_SEKAI_THEMES.get(ms.get("theme", "default"), {}).get("name", "🌌 기본 빈 세카이")
        ms_bonus = core.get_my_sekai_daily_bonus(profile)
        furn_cnt = len(ms.get("furniture", []))
        embed.add_field(
            name="🏠 마이세카이 미니 룸 (/마이세카이)",
            value=f"테마: **{ms_theme_name}** · 가구 `{furn_cnt}/{len(core.MY_SEKAI_FURNITURE)}개` · 출석 이자 **`+{ms_bonus}💎/일`**",
            inline=False
        )
        embed.add_field(
            name="📅 출석 기록 (서버 / 통합) & ❤️ 음악 보관함",
            value=(
                f"🏠 **현재 서버:** 누적 `{g_total:,}일` (`{g_streak:,}일 연속 🔥`)\n"
                f"🌍 **전체 통합:** 누적 `{all_total:,}일` (최고 `{all_max:,}일`) · ❤️ 음악 `{liked_music_count:,}곡`"
            ),
            inline=False
        )
        embed.add_field(
            name="🌱 최근 7일 은하수 잔디 (/오늘목표)",
            value=f"└ {grass_bar}",
            inline=False
        )

        valid_deck_cards = [user_cards_dict[cid] for cid in deck_ids if cid in user_cards_dict]
        if valid_deck_cards:
            deck_lines = []
            total_deck_power = 0
            for idx, c in enumerate(valid_deck_cards, start=1):
                badge = "👑" if idx == 1 else f"**{idx}.**"
                lock_tag = " 🔒" if c.get("locked") else ""
                p_val = core.get_card_power(c)
                total_deck_power += p_val
                cur_lvl = c.get("level", 1)
                deck_lines.append(f"{badge} `{c['rarity_label']}` [{c['prefix']}] **{c['char_name']}** (`Lv.{cur_lvl}` · `⚔️{p_val:,}`){lock_tag}")
            embed.add_field(name=f"🎸 나만의 5인 유닛 덱 (총 종합력: ⚔️ {total_deck_power:,})", value="\n".join(deck_lines), inline=False)
        else:
            embed.add_field(name="🎸 나만의 5인 유닛 덱", value="미편성 (`/덱편성` 명령어로 5인 유닛을 꾸며보세요!)", inline=False)

        rep_card = None
        if oshi_cards:
            oshi_cards.sort(key=lambda x: (-x.get("star_num", 1), -int(x.get("is_limited", False)), -x.get("count", 1), -x.get("id", 0)))
            rep_card = oshi_cards[0]
            embed.set_footer(text=f"대표 일러스트: [{rep_card.get('limit_label', '통상')}] {rep_card['rarity_label']} [{rep_card['prefix']}] {rep_card['char_name']}")
        elif valid_deck_cards:
            rep_card = valid_deck_cards[0]
            embed.set_footer(text=f"대표 일러스트 (덱 리더): [{rep_card.get('limit_label', '통상')}] {rep_card['rarity_label']} [{rep_card['prefix']}] {rep_card['char_name']}")

        if rep_card:
            img_bytes, filename = await asyncio.to_thread(core.fetch_proseka_card_image_bytes, rep_card, "auto")
            if img_bytes and filename:
                file = discord.File(io.BytesIO(img_bytes), filename=filename)
                embed.set_image(url=f"attachment://{filename}")
                await interaction.followup.send(embed=embed, file=file)
                return
            else:
                embed.set_image(url=core.get_proseka_card_image_url(rep_card, "auto"))
                await interaction.followup.send(embed=embed)
                return

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="가챠랭킹", description="현재 서버의 도감 수집률, ★4·생일 최다 보유자, 최다 뽑기 유저 순위를 확인합니다.")
    async def gacha_ranking_cmd(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id or 0)
        guild_users = data.get("gacha_users", {}).get(g_key, {})

        if not guild_users:
            await interaction.followup.send("📭 아직 이 서버에서 가챠를 진행한 유저가 없습니다. `/프로세카뽑기`로 첫 주인공이 되어보세요!")
            return

        total_db_cards = max(1, len(core.PROSEKA_KR_CARDS))
        stats_list = []

        for uid_str, u_data in guild_users.items():
            u_cards = list(u_data.get("cards", {}).values())
            if not u_cards:
                continue
            unique_cnt = len(u_cards)
            high_cnt = sum(c.get("count", 1) for c in u_cards if c.get("star_num", 1) >= 4)
            star4_cnt = sum(c.get("count", 1) for c in u_cards if c.get("rarity_type") == "rarity_4")
            bday_cnt = sum(c.get("count", 1) for c in u_cards if c.get("rarity_type") == "rarity_birthday")
            pull_cnt = sum(c.get("count", 1) for c in u_cards)
            stats_list.append({
                "uid": uid_str,
                "unique": unique_cnt,
                "rate": (unique_cnt / total_db_cards) * 100,
                "high": high_cnt,
                "star4": star4_cnt,
                "bday": bday_cnt,
                "pulls": pull_cnt
            })

        if not stats_list:
            await interaction.followup.send("📭 아직 집계된 가챠 데이터가 없습니다.")
            return

        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]

        by_collect = sorted(stats_list, key=lambda x: (-x["unique"], -x["high"], -x["pulls"]))[:5]
        collect_lines = [
            f"{medals[i]} <@{s['uid']}> — **`{s['unique']:,}종`** (`{s['rate']:.1f}%`)"
            for i, s in enumerate(by_collect)
        ]

        by_high = sorted(stats_list, key=lambda x: (-x["high"], -x["star4"], -x["unique"]))[:5]
        high_lines = [
            f"{medals[i]} <@{s['uid']}> — 합계 **`{s['high']:,}장`** (`★4 {s['star4']}` · `🎀 {s['bday']}`)"
            for i, s in enumerate(by_high)
        ]

        by_pulls = sorted(stats_list, key=lambda x: (-x["pulls"], -x["unique"]))[:5]
        pull_lines = [
            f"{medals[i]} <@{s['uid']}> — 누적 **`{s['pulls']:,}회`** 뽑기"
            for i, s in enumerate(by_pulls)
        ]

        guild_name = interaction.guild.name if interaction.guild else "서버"
        embed = discord.Embed(
            title=f"🏆 {guild_name} 프로세카 가챠 랭킹 보드",
            description=f"한국 서버 전체 도감(`{total_db_cards:,}종`) 기준 실시간 순위입니다.",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.add_field(name="📚 도감 수집률 TOP 5", value="\n".join(collect_lines), inline=False)
        embed.add_field(name="✨ ★4 & 🎀생일 최다 보유 TOP 5", value="\n".join(high_lines), inline=False)
        embed.add_field(name="🎰 누적 뽑기 횟수 TOP 5", value="\n".join(pull_lines), inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="픽업설정", description="[봇주인 전용] 프로세카 뽑기의 픽업 유닛, 픽업 캐릭터, 한정 포함 여부를 설정합니다.")
    @app_commands.autocomplete(캐릭터=core.proseka_char_autocomplete)
    @app_commands.describe(
        유닛="픽업 확률을 높일 유닛 선택 ('해제' 선택 시 유닛 픽업 해제)",
        캐릭터="픽업 확률을 높일 캐릭터 선택 ('해제' 선택 시 캐릭터 픽업 해제)",
        한정포함="기간한정/페스한정/생일한정 카드를 뽑기 풀에 포함할지 여부 (기본: True)"
    )
    @app_commands.choices(유닛=[
        app_commands.Choice(name="해제 (유닛 픽업 안 함)", value="NONE"),
        app_commands.Choice(name="Leo/need", value="Leo/need"),
        app_commands.Choice(name="MORE MORE JUMP!", value="MORE MORE JUMP!"),
        app_commands.Choice(name="Vivid BAD SQUAD", value="Vivid BAD SQUAD"),
        app_commands.Choice(name="원더랜즈×쇼타임", value="원더랜즈×쇼타임"),
        app_commands.Choice(name="25시, 나이트 코드에서.", value="25시, 나이트 코드에서."),
        app_commands.Choice(name="버츄얼 싱어", value="버츄얼 싱어")
    ])
    async def set_pickup_cmd(
        self,
        interaction: discord.Interaction,
        유닛: app_commands.Choice[str] = None,
        캐릭터: str = None,
        한정포함: bool = True
    ):
        if not await self.bot.is_bot_owner_user(interaction.user):
            await core.safe_send_response(interaction, content="❌ 이 명령어는 **봇주인(Bot Owner)**만 사용할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        selected_unit = None if (not 유닛 or 유닛.value == "NONE") else 유닛.value
        selected_char = None if (not 캐릭터 or 캐릭터 == "NONE") else 캐릭터

        data["gacha_pickup"] = {
            "unit": selected_unit,
            "character": selected_char,
            "include_limited": 한정포함
        }
        await asyncio.to_thread(core.save_data, data)

        embed = discord.Embed(
            title="🎯 [봇주인 전용] 프로세카 픽업 설정 완료",
            description=(
                f"• **픽업 유닛:** `{selected_unit or '미지정 (전체 동일)'}`\n"
                f"• **픽업 캐릭터:** `{selected_char or '미지정 (전체 동일)'}`\n"
                f"• **한정/페스/생일 카드 포함:** `{'포함됨' if 한정포함 else '제외됨 (통상만 등장)'}`\n\n"
                "이제 `/프로세카뽑기` 및 `/프로세카확률목록`에 픽업 확률(등급 내 50% 집중 배분)이 즉시 반영됩니다!"
            ),
            color=discord.Color.from_rgb(0, 204, 221)
        )
        await core.safe_send_response(interaction, embed=embed)

    @app_commands.command(name="서버캐릭터초기화", description="[서버 관리자 전용] 현재 디스코드 서버 유저들의 프로세카 캐릭터 보관함을 초기화합니다.")
    @app_commands.default_permissions(administrator=True)
    async def reset_guild_gacha_cmd(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, "❌ 이 명령어는 **서버 관리자**만 사용할 수 있습니다.", ephemeral=True)
            return

        view = GuildGachaResetConfirmView(interaction.guild)
        await core.safe_send_response(
            interaction,
            f"⚠️ **경고:** 정말로 **{interaction.guild.name}** 서버의 모든 유저 캐릭터 보관함 데이터를 초기화하시겠습니까?\n"
            "*(다른 서버의 데이터나 D-Day 일정은 건드리지 않습니다.)*",
            view=view,
            ephemeral=True
        )

    @app_commands.command(name="카드강화", description="[프로세카] 크리스탈을 소모하여 보유 카드의 레벨과 종합력을 상승시킵니다.")
    @app_commands.autocomplete(카드선택=core.owned_card_autocomplete)
    @app_commands.describe(
        카드선택="강화할 보유 카드를 선택하거나 카드 이름/ID를 입력하세요.",
        강화단계="강화 방식 (1단계 상승 / 10단계 상승 / MAX 레벨 직행)"
    )
    @app_commands.choices(강화단계=[
        app_commands.Choice(name="⚡ +1 레벨업", value="1"),
        app_commands.Choice(name="⚡ +10 레벨업", value="10"),
        app_commands.Choice(name="🚀 MAX 레벨 직행 강화", value="MAX")
    ])
    async def enhance_card_cmd(
        self,
        interaction: discord.Interaction,
        카드선택: str,
        강화단계: app_commands.Choice[str]
    ):
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id or 0)
        u_key = str(interaction.user.id)

        profile = core.ensure_user_profile(data, u_key, interaction.user.display_name)
        user_crystals = profile.get("crystals", 0)
        user_cards_dict = data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})

        if not user_cards_dict:
            await interaction.followup.send("❌ 보유한 카드가 없습니다. `/프로세카뽑기`로 먼저 캐릭터를 뽑아주세요!", ephemeral=True)
            return

        target = None
        query = 카드선택.strip().lower()
        if query in user_cards_dict:
            target = user_cards_dict[query]
        else:
            for c in user_cards_dict.values():
                if str(c.get("id")) == query or query in c.get("char_name", "").lower() or query in c.get("prefix", "").lower():
                    target = c
                    break

        if not target:
            await interaction.followup.send(f"❌ 검색어 `{카드선택}`에 해당하는 보유 카드를 찾지 못했습니다. `/내캐릭터`에서 보유 카드 목록과 ID를 확인해 주세요.", ephemeral=True)
            return

        star_num = target.get("star_num", 3)
        max_lvl = core.get_card_max_level(target)
        cur_lvl = max(1, int(target.get("level", 1)))

        if cur_lvl >= max_lvl:
            await interaction.followup.send(f"ℹ️ **[{target.get('prefix')}] {target.get('char_name')}** 카드는 이미 **MAX 레벨(Lv.{max_lvl})**에 도달했습니다!", ephemeral=True)
            return

        mode = 강화단계.value
        target_lvl = max_lvl if mode == "MAX" else min(max_lvl, cur_lvl + int(mode))

        total_cost = 0
        for l in range(cur_lvl, target_lvl):
            if star_num <= 1:
                cost = min(120, 15 + l * 5)
            elif star_num == 2:
                cost = min(350, 30 + l * 10)
            elif star_num == 3:
                cost = min(850, 60 + l * 20)
            else:
                cost = min(1850, 100 + l * 35)
            total_cost += cost

        if user_crystals < total_cost:
            await interaction.followup.send(
                f"❌ 크리스탈이 부족합니다! (필요: `{total_cost:,}💎` / 보유: `{user_crystals:,}💎`)\n"
                f"출석체크(`/출석체크`)나 중복카드 변환(`/중복카드변환`)으로 크리스탈을 추가 획득해 보세요.",
                ephemeral=True
            )
            return

        old_power = core.get_card_power(target)
        is_max = (target_lvl == max_lvl)
        max_bonus = (50 if star_num <= 1 else 100 if star_num == 2 else 200 if star_num == 3 else 500) if (is_max and cur_lvl < max_lvl) else 0
        was_awakened = bool(target.get("awakened"))
        if is_max and core.can_card_awaken(target):
            target["awakened"] = True
        new_crystals = user_crystals - total_cost + max_bonus
        profile["crystals"] = new_crystals
        target["level"] = target_lvl
        target["max_level"] = max_lvl
        new_power = core.get_card_power(target)
        diff_power = new_power - old_power
        await asyncio.to_thread(core.save_data, data)

        awaken_notice = "\n✨ **특훈(각성) 달성!** MAX 레벨 달성으로 각성 보너스(`+3,000⚔️`)가 활성화되었습니다!" if (target.get("awakened") and not was_awakened) else ""
        embed = discord.Embed(
            title="⚡ 프로세카 카드 레벨업 (강화) 완료!",
            description=(
                f"🖼️ `[{target.get('limit_label', '통상')}]` **{target.get('rarity_label')} [{target.get('prefix')}] {target.get('char_name')}**\n\n"
                f"• **레벨 변화:** `Lv.{cur_lvl}` ➡️ **`Lv.{target_lvl} / {max_lvl}`**\n"
                f"• **종합력 스탯:** `{old_power:,}` ➡️ **`⚔️ {new_power:,}` (+{diff_power:,})**\n"
                f"• **크리스탈 소모:** `- {total_cost:,}💎` (남은 크리스탈: `{new_crystals:,}💎`)"
                + (f"\n🎉 **MAX 레벨 달성 보너스:** `+ {max_bonus}💎` 환급 지급!" if max_bonus > 0 else "")
                + awaken_notice
            ),
            color=discord.Color.gold() if is_max else discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_thumbnail(url=core.get_proseka_card_image_url(target, "auto"))
        embed.set_footer(text=f"요청자: {interaction.user.display_name} • `/내캐릭터` 및 `/내프로필`에서 강화된 스탯을 확인할 수 있습니다.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="마이세카이", description="나만의 미니 룸 테마와 세카이 가구를 꾸미고 매일 출석체크 추가 크리스탈 이자(패시브 보너스)를 받습니다.")
    @app_commands.describe(유저="(선택) 다른 유저가 꾸민 마이세카이 미니 룸을 구경합니다.")
    async def my_sekai_cmd(self, interaction: discord.Interaction, 유저: Optional[discord.User] = None):
        await core.safe_defer(interaction)
        target_user = 유저 or interaction.user
        data = await asyncio.to_thread(core.load_data)
        view = MySekaiHubView(interaction.user, target_user, interaction.guild_id or 0, data)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    @app_commands.command(name="의상", description="캐릭터별 3D 의상을 착용하거나 뽑은 카드의 의상을 300 크리스탈로 제작하여 다른 캐릭터에게 입힙니다.")
    @app_commands.describe(캐릭터="(선택) 의상실을 열 캐릭터를 선택합니다.")
    @app_commands.autocomplete(캐릭터=core.oshi_char_autocomplete)
    async def costume_wardrobe_cmd(self, interaction: discord.Interaction, 캐릭터: Optional[str] = None):
        await core.safe_defer(interaction)
        initial_cid = 1
        if 캐릭터:
            matched_cid = next((cid for cid, info in core.CHARACTER_MAP.items() if info["name"] == 캐릭터 or 캐릭터 in info["name"]), None)
            if matched_cid:
                initial_cid = matched_cid

        view = CharacterCostumeWardrobeView(interaction.user, guild_id=interaction.guild_id or 0, initial_char_id=initial_cid)
        await interaction.followup.send(embed=view.build_embed(), view=view)


class MySekaiGreetingModal(core.SafeModal, title="🪧 마이세카이 방 한줄 소개글 변경"):
    greeting_input = discord.ui.TextInput(
        label="방문객에게 보여줄 한줄 환영 인사",
        placeholder="예: 25시 작곡 작업실입니다 🍜 카나데 오시 환영해요!",
        required=True,
        max_length=80
    )

    def __init__(self, hub_view: "MySekaiHubView"):
        super().__init__()
        self.hub_view = hub_view

    async def on_submit(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        profile = core.ensure_user_profile(data, self.hub_view.owner.id, self.hub_view.owner.display_name)
        ms = core.ensure_my_sekai(profile)
        ms["greeting"] = self.greeting_input.value.strip() or "나만의 아늑한 마이세카이에 오신 것을 환영합니다! ✨"
        await asyncio.to_thread(core.save_data, data)
        self.hub_view.data = data
        await interaction.edit_original_response(embed=self.hub_view.build_embed(), view=self.hub_view)


class MySekaiHubView(core.SafeView):
    """크리스탈로 세카이 배경 테마와 가구·소품을 구매/배치하고 일일 출석 패시브 보너스를 받는 하우징 뷰"""
    def __init__(self, caller: discord.User, owner: discord.User, guild_id: int, data: dict):
        super().__init__(timeout=600)
        self.caller = caller
        self.owner = owner
        self.guild_id = guild_id
        self.data = data
        self.status_notice = ""
        self._refresh_components()

    def _refresh_components(self):
        is_owner = (self.caller.id == self.owner.id)
        profile = core.ensure_user_profile(self.data, self.owner.id, self.owner.display_name)
        ms = core.ensure_my_sekai(profile)
        cur_theme = ms.get("theme", "default")
        owned_themes = set(ms.get("owned_themes", ["default"]))
        owned_furn = set(ms.get("furniture", []))

        t_opts = []
        for t_key, t_info in core.MY_SEKAI_THEMES.items():
            if t_key == cur_theme:
                status = "🌟 현재 적용 중"
            elif t_key in owned_themes:
                status = "✅ 보유 중 (클릭 시 무료 변경)"
            else:
                status = f"💎 {t_info['cost']:,} 크리스탈 구매·적용"
            label = f"{t_info['name']}"[:95]
            desc = f"[{status}] 출석 +{t_info['bonus']}💎/일 | {t_info['desc']}"[:95]
            t_opts.append(discord.SelectOption(label=label, value=t_key, description=desc, default=(t_key == cur_theme)))
        self.theme_select.options = t_opts
        self.theme_select.disabled = not is_owner

        f_opts = []
        for f_key, f_info in core.MY_SEKAI_FURNITURE.items():
            has_it = (f_key in owned_furn)
            status = "✅ 배치 완료" if has_it else f"🛒 {f_info['cost']:,}💎 구매"
            label = f"{f_info['name']} ({status})"[:95]
            desc = f"출석 보너스 +{f_info['bonus']}💎/일 · {f_info['desc']}"[:95]
            f_opts.append(discord.SelectOption(label=label, value=f_key, description=desc, emoji=f_info["emoji"]))
        self.furniture_select.options = f_opts
        self.furniture_select.disabled = not is_owner
        self.edit_greeting_btn.disabled = not is_owner

    def build_embed(self) -> discord.Embed:
        self._refresh_components()
        u_key = str(self.owner.id)
        g_key = str(self.guild_id or 0)
        profile = core.ensure_user_profile(self.data, u_key, self.owner.display_name)
        ms = core.ensure_my_sekai(profile)

        crystals = profile.get("crystals", 0)
        oshi_name = profile.get("oshi") or "미설정 (`/오시설정`)"
        cur_theme_key = ms.get("theme", "default")
        theme_info = core.MY_SEKAI_THEMES.get(cur_theme_key, core.MY_SEKAI_THEMES["default"])
        owned_furn = ms.get("furniture", [])
        daily_bonus = core.get_my_sekai_daily_bonus(profile)

        # 미니 룸 쇼케이스 시각화
        if owned_furn:
            room_icons = "  ".join(core.MY_SEKAI_FURNITURE[f]["emoji"] for f in owned_furn if f in core.MY_SEKAI_FURNITURE)
            furn_lines = [
                f"• {core.MY_SEKAI_FURNITURE[f]['name']} (**`+{core.MY_SEKAI_FURNITURE[f]['bonus']}💎/일`**)"
                for f in owned_furn if f in core.MY_SEKAI_FURNITURE
            ]
            furn_list_str = "\n".join(furn_lines)
        else:
            room_icons = "▫️  (아직 배치된 가구가 없습니다 — 아래 드롭다운에서 첫 가구를 들여놓아 보세요!)"
            furn_list_str = "*배치된 가구 없음*"

        total_furn = len(core.MY_SEKAI_FURNITURE)
        cnt_furn = len(owned_furn)
        filled_bars = int(round((cnt_furn / max(1, total_furn)) * 10))
        progress_bar = "🟦" * filled_bars + "⬜" * (10 - filled_bars)

        notice_block = f"\n📢 **알림:** {self.status_notice}\n" if self.status_notice else ""

        embed = discord.Embed(
            title=f"🏠 {self.owner.display_name}님의 마이세카이 미니 룸",
            description=(
                f"> 💬 **\"{ms.get('greeting', '환영합니다!')}\"**\n"
                f"{notice_block}"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎨 **적용 배경 테마:** **{theme_info['name']}** (`+{theme_info['bonus']}💎/일`)\n"
                f"└ *{theme_info['desc']}*\n\n"
                f"🛋️ **미니 룸 가구 진열장 (`{cnt_furn}/{total_furn}`):**\n"
                f"### 🪟 【  {room_icons}  】 🪟\n"
                f"└ 수집도: `{progress_bar}` (**{int(cnt_furn / max(1, total_furn) * 100)}%**)\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_thumbnail(url=self.owner.display_avatar.url)
        embed.add_field(
            name="💰 마이세카이 출석 이자 (패시브 보상)",
            value=(
                f"• 기본 출석 보상: `100 💎`\n"
                f"• **마이세카이 보너스:** **`+{daily_bonus} 💎 / 매일`**\n"
                f"👉 `/출석체크` 시 매일 **`{100 + daily_bonus:,} 💎`** 즉시 수령!"
            ),
            inline=True
        )
        embed.add_field(
            name="💎 보유 자산 & 오시",
            value=(
                f"• **보유 크리스탈:** **`{crystals:,} 💎`**\n"
                f"• **초대된 오시:** 💖 **{oshi_name}**\n"
                f"• **보유 테마:** `{len(ms.get('owned_themes', ['default']))}/{len(core.MY_SEKAI_THEMES)}종`"
            ),
            inline=True
        )
        embed.add_field(
            name=f"📦 배치된 세카이 가구 & 오브제 ({cnt_furn}개)",
            value=furn_list_str,
            inline=False
        )

        # 오시 카드가 있다면 룸 대표 액자로 썸네일/이미지 연동
        user_cards_dict = self.data.get("gacha_users", {}).get(g_key, {}).get(u_key, {}).get("cards", {})
        oshi_raw = profile.get("oshi")
        if oshi_raw and user_cards_dict:
            oshi_cards = [c for c in user_cards_dict.values() if c.get("char_name") == oshi_raw]
            if oshi_cards:
                oshi_cards.sort(key=lambda x: (-x.get("star_num", 1), -int(x.get("is_limited", False))))
                embed.set_image(url=core.get_proseka_card_image_url(oshi_cards[0], "auto"))

        embed.set_footer(text="테마와 가구를 수집할수록 매일 /출석체크 시 지급되는 크리스탈 이자가 영구적으로 증가합니다!")
        return embed

    @discord.ui.select(placeholder="🎨 배경 테마 변경 또는 신규 테마 구매...", row=0)
    async def theme_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.owner.id:
            await core.safe_send_response(interaction, "❌ 본인의 마이세카이만 꾸밀 수 있습니다. `/마이세카이`를 입력해 보세요!", ephemeral=True)
            return

        t_key = select.values[0]
        t_info = core.MY_SEKAI_THEMES.get(t_key)
        if not t_info:
            await core.safe_defer(interaction)
            return

        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        profile = core.ensure_user_profile(data, self.owner.id, self.owner.display_name)
        ms = core.ensure_my_sekai(profile)
        owned_themes = ms.setdefault("owned_themes", ["default"])

        if t_key in owned_themes:
            ms["theme"] = t_key
            await asyncio.to_thread(core.save_data, data)
            self.data = data
            self.status_notice = f"✅ 배경 테마를 **{t_info['name']}**(으)로 변경했습니다!"
            await interaction.edit_original_response(embed=self.build_embed(), view=self)
            return

        cost = t_info["cost"]
        cur_crystals = profile.get("crystals", 0)
        if cur_crystals < cost:
            await interaction.followup.send(
                f"❌ **{t_info['name']}** 테마 구매에 필요한 크리스탈이 부족합니다! (필요: `{cost:,}💎` / 보유: `{cur_crystals:,}💎`)",
                ephemeral=True
            )
            return

        profile["crystals"] = cur_crystals - cost
        owned_themes.append(t_key)
        ms["theme"] = t_key
        await asyncio.to_thread(core.save_data, data)
        self.data = data
        self.status_notice = f"🎉 **{t_info['name']}** 테마를 구매하고 즉시 적용했습니다! (`-{cost:,}💎` · 출석 보너스 `+{t_info['bonus']}💎/일`)"
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.select(placeholder="🛋️ 세카이 가구·소품 구매 및 배치하기...", row=1)
    async def furniture_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.owner.id:
            await core.safe_send_response(interaction, "❌ 본인의 마이세카이만 꾸밀 수 있습니다. `/마이세카이`를 입력해 보세요!", ephemeral=True)
            return

        f_key = select.values[0]
        f_info = core.MY_SEKAI_FURNITURE.get(f_key)
        if not f_info:
            await core.safe_defer(interaction)
            return

        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        profile = core.ensure_user_profile(data, self.owner.id, self.owner.display_name)
        ms = core.ensure_my_sekai(profile)
        furn_list = ms.setdefault("furniture", [])

        if f_key in furn_list:
            await interaction.followup.send(
                f"ℹ️ **{f_info['name']}** 가구는 이미 마이세카이에 배치되어 출석 보너스(`+{f_info['bonus']}💎/일`)를 제공하고 있습니다!",
                ephemeral=True
            )
            return

        cost = f_info["cost"]
        cur_crystals = profile.get("crystals", 0)
        if cur_crystals < cost:
            await interaction.followup.send(
                f"❌ **{f_info['name']}** 구매에 필요한 크리스탈이 부족합니다! (필요: `{cost:,}💎` / 보유: `{cur_crystals:,}💎`)",
                ephemeral=True
            )
            return

        profile["crystals"] = cur_crystals - cost
        furn_list.append(f_key)
        await asyncio.to_thread(core.save_data, data)
        self.data = data
        total_bonus = core.get_my_sekai_daily_bonus(profile)
        self.status_notice = (
            f"🎊 **{f_info['name']}** 가구를 배치했습니다! "
            f"(`-{cost:,}💎` · 일일 출석 이자 총 **`+{total_bonus}💎/일`**)"
        )
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🪧 방 한줄 소개글 변경", style=discord.ButtonStyle.primary, row=2)
    async def edit_greeting_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner.id:
            await core.safe_send_response(interaction, "❌ 본인의 마이세카이 소개글만 수정할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(MySekaiGreetingModal(self))

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=2)
    async def refresh_room_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.data = await asyncio.to_thread(core.load_data)
        self.status_notice = ""
        await interaction.edit_original_response(embed=self.build_embed(), view=self)


async def setup(bot):
    await bot.add_cog(GachaCog(bot))

