"""붕괴: 스타레일 (Honkai: Star Rail) 워프 · 유물 감정 · 보관함 · 도감 · 별빛/헤르타 상점 · 편대 시너지 Cog

- 그룹 커맨드 `/스타레일` (11개 서브커맨드 + `!스타레일워프` 등 프리픽스 단축어)
- 은하열차 코스믹 보라-골드-홀로그램 테마 · 승차권 3.5초 승격 연출 · 공유 가챠 쿨타임 (일반 3.5초 / 스킵 5.0초)
- 시각별 KST 2시간 자동 로테이션 (캐릭터 · 전용 광추 · 침식된 터널/차원 장신구 유물 동시 회전)
- 봇 주인 전용 `/스타레일 픽업설정` + 상시 300회 5성 선택권 + 별빛/헤르타/잔재 상점 + 4인 편대 시너지
"""
from __future__ import annotations

import asyncio
import datetime
import io
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import core
import hsr_core

_MAX_FILES = 10
_MAX_TOTAL_BYTES = 7_800_000


def _build_hsr_intro_embed(result: dict) -> discord.Embed:
    drawn = result["drawn"]
    b_cfg = hsr_core.HSR_BANNER_CONFIGS.get(result["banner_key"], hsr_core.HSR_BANNER_CONFIGS["char1"])
    r5 = [it for it in drawn if it["rank"] == 5]
    r4 = [it for it in drawn if it["rank"] == 4]

    quote_block = "\n\n🚄 *은하열차가 별빛 사이를 도약하며 운명의 좌표를 수신하고 있습니다...*"
    if r5:
        top = sorted(r5, key=lambda x: not x.get("is_pickup"))[0]
        if result["banner_key"] == "relic":
            orb = "🏺 침식된 터널 · 시뮬레이션 우주 ➔ 🌟 **황금빛 5성 유물 출현!!**"
            color = discord.Color.from_rgb(118, 232, 196)
        else:
            orb = "🎫 은하열차 승차권 ➔ 🌈 **무지개 홀로그램 폭주!! 폼폼 5성 황금빛 도약!!**"
            color = discord.Color.from_rgb(255, 198, 86)
        tier_txt = "🌌 **★★★★★ 최고 등급 워프 확정!!**"
        det = hsr_core.fetch_hsr_detail_kr(top["id"], top["kind"])
        if top["kind"] == "char":
            fac = det.get("faction") or f"{top.get('path_name', '')}의 길"
            desc = (det.get("description") or "").strip().replace("\n", " ")
            snippet = (desc[:95] + "…") if len(desc) > 95 else desc
            quote_block = f"\n\n✨ *소속: {fac}*" + (f"\n💬 \"{snippet}\"" if snippet else "")
        elif top["kind"] == "relic":
            b2 = top.get("bonus_2p") or det.get("bonus_2p") or ""
            slot_txt = top.get("slot_name", "유물")
            main_txt = top.get("main_stat", "")
            quote_block = f"\n\n🏺 *{top['name']} ({slot_txt} · {main_txt})*" + (f"\n✨ 2세트: \"{b2[:90]}\"" if b2 else "")
        else:
            desc = (det.get("description") or "").strip().replace("\n", " ")
            snippet = (desc[:95] + "…") if len(desc) > 95 else desc
            quote_block = "\n\n🪩 *기억의 광추가 별빛 속에 형상화됩니다...*" + (f"\n📜 \"{snippet}\"" if snippet else "")
    elif r4:
        orb = "🎫 은하열차 승차권 ➔ 💜 **자색 홀로그램 공명!!**"
        tier_txt = "⚡ **★★★★ 등급 이상 워프 도달!**"
        color = discord.Color.from_rgb(186, 114, 255)
        top = sorted(r4, key=lambda x: (x["kind"] != "char", not x.get("is_pickup")))[0]
        det = hsr_core.fetch_hsr_detail_kr(top["id"], top["kind"])
        if top["kind"] == "char" and det.get("faction"):
            quote_block = f"\n\n🚄 *진영 「{det['faction']}」의 합류 신호가 포착되었습니다!*"
        elif top["kind"] == "relic":
            quote_block = f"\n\n🏺 *{top['name']} ({top.get('slot_name', '')})* 유물이 발굴되었습니다!"
    else:
        orb = "🎫 **푸른 별빛 승차권이 선로를 따라 미끄러집니다...**"
        tier_txt = "🪩 **은하열차 워프 스캔 중...**"
        color = discord.Color.from_rgb(92, 186, 255)

    emb = discord.Embed(
        title=f"🚆 {b_cfg['name']} ({len(drawn)}회)",
        description=f"{orb}\n{tier_txt}{quote_block}",
        color=color,
        timestamp=datetime.datetime.now(core.KST),
    )
    emb.set_footer(text="3.5초 후 워프 결과판과 일러스트가 공개됩니다!")
    return emb


def _build_hsr_result_embed(result: dict, user: discord.abc.User | None) -> tuple[discord.Embed, list[dict]]:
    drawn = result["drawn"]
    banner_key = result["banner_key"]
    eff = result["eff_pickup"]
    u_state = result["user_state"]
    practice = result["practice"]

    b_cfg = hsr_core.HSR_BANNER_CONFIGS.get(banner_key, hsr_core.HSR_BANNER_CONFIGS["char1"])
    r5 = [it for it in drawn if it["rank"] == 5]
    r4 = [it for it in drawn if it["rank"] == 4]
    r3 = [it for it in drawn if it["rank"] == 3]

    if r5:
        color = discord.Color.from_rgb(255, 200, 82)
    elif r4:
        color = discord.Color.from_rgb(176, 114, 255)
    else:
        color = discord.Color.from_rgb(*b_cfg["color"])

    lines = []
    for idx, it in enumerate(drawn, start=1):
        p_mark = "🎯**[픽업]** " if it.get("is_pickup") else ""
        new_mark = "✨**[NEW]** " if it.get("is_new") else ""
        if it["kind"] == "char":
            dup_txt = f"E{it.get('new_eidolon', 0)}"
            tag = f"{it.get('element_emoji', '')}{it.get('element_name', '')} · {it.get('path_emoji', '')}{it.get('path_name', '')}"
        elif it["kind"] == "relic":
            dup_txt = f"+{it.get('new_level', 3)}"
            subs = ", ".join((it.get("sub_stats") or [])[:2])
            tag = f"{it.get('slot_name', '🏺유물')} · 주옵: {it.get('main_stat', '-')}" + (f" ({subs})" if subs else "")
        else:
            dup_txt = f"S{it.get('new_super', 1)}"
            tag = f"{it.get('path_emoji', '')}{it.get('path_name', '')} 광추"
        pity_txt = f" · `{it['pity_used']}스택`" if it.get("pity_used") else ""
        rew = []
        if it.get("gained_starlight"):
            rew.append(f"+{it['gained_starlight']}🌟별빛")
        if it.get("gained_embers"):
            rew.append(f"+{it['gained_embers']}🫧잔재")
        rew_txt = f" ({', '.join(rew)})" if rew else ""
        lines.append(
            f"**{idx:02d}.** {p_mark}{new_mark}**{it['rarity_label']} {it['name']}** `{dup_txt}`{pity_txt}\n"
            f"└ `{tag}`{rew_txt}"
        )

    if banner_key in ("char1", "char2"):
        p_txt = f"`{u_state.get('pity_char', 0)}/90`"
        g_txt = "🔒 **확정**" if u_state.get("guaranteed_char") else "🎲 **반천장 (50/50)**"
        pity_line = f"• **캐릭터 워프 스택:** {p_txt} ({g_txt})"
    elif banner_key == "lc":
        p_txt = f"`{u_state.get('pity_lc', 0)}/80`"
        g_txt = "🔒 **확정**" if u_state.get("guaranteed_lc") else "🎲 **75/25**"
        pity_line = f"• **광추 워프 스택:** {p_txt} ({g_txt})"
    elif banner_key == "relic":
        p_txt = f"`{u_state.get('pity_relic', 0)}/50`"
        g_txt = "🔒 **픽업세트확정**" if u_state.get("guaranteed_relic") else "🎲 **80/20 픽업우대**"
        pity_line = f"• **유물 감정 스택:** {p_txt} ({g_txt} · 35스택 소프트 천장)"
    else:
        std_tot = int(u_state.get("standard_total_pulls", 0))
        sel_mark = " ✅선택가능!" if (std_tot >= 300 and not u_state.get("standard_300_claimed")) else ""
        pity_line = f"• **상시 워프 스택:** `{u_state.get('pity_standard', 0)}/90` · 🎁 **300회 보상:** `{min(300, std_tot)}/300`{sel_mark}"

    if banner_key == "char1":
        feat_str = f"★★★★★ {eff['char1']['name']}" if eff.get("char1") else "픽업 없음"
    elif banner_key == "char2":
        feat_str = f"★★★★★ {eff['char2']['name']}" if eff.get("char2") else "픽업 없음"
    elif banner_key == "lc":
        lc_names = [l["name"] for l in (eff.get("lc_1"), eff.get("lc_2")) if l]
        feat_str = " / ".join(lc_names) if lc_names else "픽업 광추"
    elif banner_key == "relic":
        r_names = [r["name"] for r in (eff.get("relic_1"), eff.get("relic_2")) if r]
        feat_str = " / ".join(r_names) if r_names else "침식된 터널 유물"
    else:
        feat_str = "상시 5성 캐릭터 & 광추 (300회 시 선택 1명)"

    rot_win = eff.get("time_window") or ""
    rot_tag = f" · ⏰ `{rot_win}`" if rot_win else ""
    mode_banner = "🧪 **[리세마라 연습 모드 — 미저장/천장 미반영]**\n" if practice else ""
    bond_str = f" / `+{result['gained_bonds']} 헤르타채권`" if result.get("gained_bonds") else ""
    rew_sum = (
        f" · 🌟 **보상:** `+{result['total_starlight']} 별빛` / `+{result['total_embers']} 잔재`{bond_str}"
        if not practice else ""
    )
    stat_bar = f"★★★★★ `{len(r5)}` · ★★★★ `{len(r4)}` · ★★★ `{len(r3)}`{rew_sum}"

    header = f"{mode_banner}🚄 **워프:** `{b_cfg['name']}`{rot_tag}\n🎯 **현재 픽업:** `{feat_str}`\n\n"
    footer_block = f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n{stat_bar}\n{pity_line}"
    body = "\n".join(lines)
    max_b = max(200, 4040 - len(header) - len(footer_block))
    if len(body) > max_b:
        body = body[:max_b - 14].rstrip() + "\n...*(생략)*"

    emb = discord.Embed(
        title=f"🌌 스타레일 {len(drawn)}회 워프 결과 ({b_cfg['short_name']})" + (" 🎊 ★5 도약!" if r5 else ""),
        description=(header + body + footer_block)[:4090],
        color=color,
        timestamp=datetime.datetime.now(core.KST),
    )
    if user:
        emb.set_author(name=f"{user.display_name}님의 은하열차 워프", icon_url=user.display_avatar.url)
    emb.set_footer(text=f"보유 별빛 {u_state.get('starlight', 0):,} · 잔재 {u_state.get('embers', 0):,} · 헤르타채권 {u_state.get('herta_bond', 0):,} | 하단에서 캐릭터·광추·유물 배너 전환")

    high_items = [it for it in drawn if it["rank"] >= 5]
    if not high_items and len(drawn) == 1:
        high_items = [drawn[0]]
    elif not high_items and r4:
        high_items = sorted(r4, key=lambda x: (x["kind"] != "char", not x.get("is_pickup")))[:2]
    return emb, high_items


async def send_hsr_warp_result(
    interaction: discord.Interaction,
    result: dict,
    view: discord.ui.View,
    skip_anim: bool = False,
):
    drawn = result["drawn"]
    banner_key = result["banner_key"]
    main_embed, high_items = _build_hsr_result_embed(result, interaction.user)
    want_grid = len(drawn) >= 2
    splash_targets = high_items[:9]

    async def _empty_grid():
        return None

    async def _empty_list():
        return []

    img_coro = (
        asyncio.gather(*(asyncio.to_thread(hsr_core.fetch_hsr_item_image_bytes, it, True) for it in splash_targets))
        if splash_targets else _empty_list()
    )
    det_coro = (
        asyncio.gather(*(asyncio.to_thread(hsr_core.fetch_hsr_detail_kr, it["id"], it["kind"]) for it in splash_targets))
        if splash_targets else _empty_list()
    )
    tag = "연습 모드" if result["practice"] else f"{result['user_state'].get('total_pulls', 0)}회 누적"
    grid_coro = (
        asyncio.to_thread(hsr_core.build_hsr_10pull_grid_bytes, drawn, banner_key, tag)
        if want_grid else _empty_grid()
    )

    intro_msg = None
    if not skip_anim:
        intro_embed = await asyncio.to_thread(_build_hsr_intro_embed, result)
        try:
            intro_msg = await interaction.followup.send(embed=intro_embed, wait=True)
        except Exception:
            intro_msg = None
        img_results, det_results, grid_buf, _ = await asyncio.gather(img_coro, det_coro, grid_coro, asyncio.sleep(3.5))
    else:
        img_results, det_results, grid_buf = await asyncio.gather(img_coro, det_coro, grid_coro)

    file_specs: list[tuple[bytes, str]] = []
    total_bytes = 0
    if grid_buf is not None:
        g_bytes = grid_buf.getvalue()
        if g_bytes and len(g_bytes) <= _MAX_TOTAL_BYTES:
            file_specs.append((g_bytes, "hsr_grid.png"))
            total_bytes += len(g_bytes)
            main_embed.set_image(url="attachment://hsr_grid.png")

    embeds = [main_embed]
    splash_pairs: list[tuple[discord.Embed, dict]] = []
    if not want_grid and splash_targets and img_results:
        sb, sfn = img_results[0]
        if sb and len(file_specs) < _MAX_FILES and total_bytes + len(sb) <= _MAX_TOTAL_BYTES:
            safe_fn = f"hsr_1_{sfn}"
            file_specs.append((sb, safe_fn))
            total_bytes += len(sb)
            main_embed.set_image(url=f"attachment://{safe_fn}")
        else:
            main_embed.set_image(url=hsr_core.get_hsr_primary_image_url(splash_targets[0], True))
    else:
        for idx, (it, (sb, sfn), det) in enumerate(zip(splash_targets, img_results, det_results), start=1):
            if len(embeds) >= 10:
                break
            p_tag = "🎯 [픽업!] " if it.get("is_pickup") else ""
            n_tag = "✨ [NEW] " if it.get("is_new") else ""
            c_title = f"{p_tag}{n_tag}{it['rarity_label']} {it['name']}"
            if it["kind"] == "char":
                el_t = f"{it.get('element_emoji', '')} {it.get('element_name', '')}"
                pt_t = f"{it.get('path_emoji', '')} {it.get('path_name', '')}"
                extra = [f"• **속성/운명의 길:** {el_t} · {pt_t} (`{it.get('path_role', '')}`)"]
                if det.get("faction"):
                    extra.append(f"• **진영:** `{det['faction']}`")
                if det.get("cv_kr"):
                    extra.append(f"• **한국어 성우:** `CV. {det['cv_kr']}`")
                if det.get("description"):
                    d_txt = det["description"].replace("\n", " ")
                    extra.append(f"• 💬 *\"{d_txt[:140]}{'…' if len(d_txt) > 140 else ''}\"*")
            elif it["kind"] == "relic":
                extra = [
                    f"• **유물 분류/부위:** {it.get('path_emoji', '🏺')}{it.get('path_name', '터널 유물')} · {it.get('slot_name', '')} (**`{it.get('main_stat', '-')}`**)",
                    f"• **부옵션 감정:** `{', '.join(it.get('sub_stats') or ['-'])}`",
                ]
                b2 = it.get("bonus_2p") or det.get("bonus_2p")
                b4 = it.get("bonus_4p") or det.get("bonus_4p")
                if b2:
                    extra.append(f"• **2세트 효과:** {b2}")
                if b4:
                    extra.append(f"• **4세트 효과:** {b4[:120]}{'…' if len(b4) > 120 else ''}")
            else:
                extra = [f"• **광추 운명의 길:** {it.get('path_emoji', '')} {it.get('path_name', '')}"]
                if det.get("skill_name"):
                    extra.append(f"• **스킬명:** `{det['skill_name']}`")
                if det.get("description"):
                    d_txt = det["description"].replace("\n", " ")
                    extra.append(f"• 📜 *\"{d_txt[:140]}{'…' if len(d_txt) > 140 else ''}\"*")

            sp_emb = discord.Embed(
                title=c_title[:256],
                description="\n".join(extra),
                color=discord.Color.from_rgb(255, 200, 82) if it["rank"] == 5 else discord.Color.from_rgb(174, 114, 255),
            )
            if sb and len(file_specs) < _MAX_FILES and total_bytes + len(sb) <= _MAX_TOTAL_BYTES:
                safe_fn = f"hsr_{idx}_{sfn}"
                file_specs.append((sb, safe_fn))
                total_bytes += len(sb)
                sp_emb.set_image(url=f"attachment://{safe_fn}")
            else:
                sp_emb.set_image(url=hsr_core.get_hsr_primary_image_url(it, True))
            embeds.append(sp_emb)
            splash_pairs.append((sp_emb, it))

    files = [discord.File(io.BytesIO(b), filename=fn) for b, fn in file_specs]
    if intro_msg is not None:
        try:
            await intro_msg.edit(embeds=embeds, attachments=files, view=view)
            return
        except Exception:
            try:
                await intro_msg.delete()
            except Exception:
                pass

    try:
        if files:
            await interaction.followup.send(embeds=embeds, files=files, view=view)
        else:
            await interaction.followup.send(embeds=embeds, view=view)
    except discord.HTTPException:
        main_embed.set_image(url=None)
        for sp_e, sp_it in splash_pairs:
            sp_e.set_image(url=hsr_core.get_hsr_primary_image_url(sp_it, True))
        await interaction.followup.send(embeds=embeds, view=view)


# ==========================================
# 인터랙티브 SafeView 클래스들 (봇 재시작 복구 대응 기본값 완비)
# ==========================================
class _HSRBannerSelect(discord.ui.Select):
    def __init__(self, current_banner: str = "char1", eff_pickup: dict | None = None):
        eff = eff_pickup or hsr_core.resolve_effective_hsr_pickup(None)
        c1 = eff["char1"]["name"] if eff.get("char1") else "픽업 캐릭터 ①"
        c2 = eff["char2"]["name"] if eff.get("char2") else "픽업 캐릭터 ②"
        lc_names = " / ".join(l["name"] for l in (eff.get("lc_1"), eff.get("lc_2")) if l) or "픽업 광추"
        r_names = " / ".join(r["name"] for r in (eff.get("relic_1"), eff.get("relic_2")) if r) or "터널 유물/장신구"
        options = [
            discord.SelectOption(label="🚆 캐릭터 이벤트 워프 ①", value="char1", description=f"픽업: {c1}"[:95], default=(current_banner == "char1")),
            discord.SelectOption(label="🌠 캐릭터 이벤트 워프 ②", value="char2", description=f"픽업: {c2}"[:95], default=(current_banner == "char2")),
            discord.SelectOption(label="🪩 빛의 자취 (광추 워프)", value="lc", description=f"픽업: {lc_names}"[:95], default=(current_banner == "lc")),
            discord.SelectOption(label="🏺 침식된 터널 · 장신구 (유물 워프)", value="relic", description=f"픽업 세트: {r_names}"[:95], default=(current_banner == "relic")),
            discord.SelectOption(label="🌌 뭇별의 워프 (상시)", value="standard", description="상시 5성 · 300회 시 선택 1명", default=(current_banner == "standard")),
        ]
        super().__init__(placeholder="🚄 워프 배너 전환 (캐릭터·광추·유물·상시)...", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        view: HSRWarpAgainView = self.view
        if not await view._check_owner(interaction):
            return
        view.banner_key = self.values[0]
        await view._run_rewarp_with_cooldown(interaction, view.last_count)


class HSRWarpAgainView(core.SafeView):
    def __init__(
        self,
        user: discord.User | None = None,
        banner_key: str = "char1",
        skip_anim: bool = False,
        practice: bool = False,
        last_count: int = 10,
    ):
        super().__init__(timeout=300)
        self.user = user
        self.banner_key = banner_key
        self.skip_anim = skip_anim
        self.practice = practice
        self.last_count = last_count
        self._lock = asyncio.Lock()
        self._build_items()

    def _build_items(self):
        self.clear_items()
        data = core.get_cached_data()
        eff = hsr_core.resolve_effective_hsr_pickup(data.get("hsr_pickup"))
        self.add_item(_HSRBannerSelect(self.banner_key, eff))

        b10 = discord.ui.Button(label="🚆 10회 워프", style=discord.ButtonStyle.primary, row=1)
        b10.callback = self._on_10
        self.add_item(b10)

        b1 = discord.ui.Button(label="🎫 1회 워프", style=discord.ButtonStyle.secondary, row=1)
        b1.callback = self._on_1
        self.add_item(b1)

        bskip = discord.ui.Button(
            label="⏩ 연출 스킵 ON" if self.skip_anim else "🎬 연출 보기 (3.5초)",
            style=discord.ButtonStyle.success if self.skip_anim else discord.ButtonStyle.secondary,
            row=1,
        )
        bskip.callback = self._on_toggle_skip
        self.add_item(bskip)

        if not self.practice:
            bp = discord.ui.Button(label="🧪 연습 모드 전환", style=discord.ButtonStyle.secondary, row=1)
        else:
            bp = discord.ui.Button(label="⭐ 실전 모드 전환", style=discord.ButtonStyle.success, row=1)
        bp.callback = self._on_toggle_practice
        self.add_item(bp)

        binv = discord.ui.Button(label="🎒 보관함", style=discord.ButtonStyle.secondary, row=2)
        binv.callback = self._on_inv
        self.add_item(binv)

        bshop = discord.ui.Button(label="🛍️ 별빛·헤르타 상점", style=discord.ButtonStyle.secondary, row=2)
        bshop.callback = self._on_shop
        self.add_item(bshop)

        if self.banner_key == "standard":
            b300 = discord.ui.Button(label="🎁 상시 300 선택", style=discord.ButtonStyle.success, row=2)
            b300.callback = self._on_300
            self.add_item(b300)

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 워프 화면에서만 조작할 수 있습니다!", ephemeral=True)
            return False
        if self.user is None:
            self.user = interaction.user
        return True

    async def _run_rewarp_with_cooldown(self, interaction: discord.Interaction, count: int):
        async with self._lock:
            if not self.practice:
                ok, rem = core.check_and_update_gacha_cooldown(interaction.user.id, skip_anim=self.skip_anim)
                if not ok:
                    return await core.safe_send_response(
                        interaction,
                        f"⏳ 가챠 쿨타임 중입니다! **`{rem:.1f}초`** 후 다시 워프해 주세요. ({'스킵 5.0초' if self.skip_anim else '기본 3.5초'})",
                        ephemeral=True,
                    )
            await core.safe_defer(interaction)
            self.last_count = count
            self._build_items()
            res = await asyncio.to_thread(
                hsr_core.execute_hsr_warp,
                interaction.guild_id or 0,
                interaction.user.id,
                self.banner_key,
                count,
                self.practice,
            )
            await send_hsr_warp_result(interaction, res, view=self, skip_anim=self.skip_anim)

    async def _on_10(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return
        await self._run_rewarp_with_cooldown(interaction, 10)

    async def _on_1(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return
        await self._run_rewarp_with_cooldown(interaction, 1)

    async def _on_toggle_skip(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return
        self.skip_anim = not self.skip_anim
        self._build_items()
        await core.safe_edit_response(interaction, view=self)

    async def _on_toggle_practice(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return
        self.practice = not self.practice
        self._build_items()
        await core.safe_edit_response(interaction, view=self)

    async def _on_inv(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return
        v = HSRInventoryView(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v, ephemeral=True)

    async def _on_shop(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return
        v = HSRShopView(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v, ephemeral=True)

    async def _on_300(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return
        v = HSRStandard300View(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v, ephemeral=True)


class HSRStandard300View(core.SafeView):
    def __init__(self, guild_id: int = 0, user: discord.User | None = None):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.user = user
        self._build()

    def _build(self):
        self.clear_items()
        hsr_core.load_hsr_kr_db()
        data = core.load_data()
        u_data = hsr_core.ensure_hsr_user(data, self.guild_id, self.user.id if self.user else 0)
        eligible = (int(u_data.get("standard_total_pulls", 0)) >= 300) and (not u_data.get("standard_300_claimed"))

        opts = []
        for cid in sorted(hsr_core.HSR_STD_5_CHARS):
            c = hsr_core.HSR_ALL_ITEMS.get(f"char:{cid}")
            if c:
                opts.append(discord.SelectOption(
                    label=f"★★★★★ {c['name']} ({c['element_name']} · {c['path_name']})",
                    value=cid,
                    description=f"상시 5성 {c['path_role']}",
                ))
        sel = discord.ui.Select(
            placeholder="🎁 뭇별의 워프 300회 보상 5성 선택..." if eligible else "🔒 상시 워프 300회 달성 시 해금됩니다",
            options=opts,
            disabled=not eligible,
            row=0,
        )
        sel.callback = self._on_pick
        self.add_item(sel)

    async def _on_pick(self, interaction: discord.Interaction):
        if self.user and interaction.user.id != self.user.id:
            return await core.safe_send_response(interaction, "❌ 본인만 선택할 수 있습니다.", ephemeral=True)
        if self.user is None:
            self.user = interaction.user
        gid = self.guild_id or (interaction.guild_id or 0)
        self.guild_id = gid
        cid = interaction.data["values"][0]
        ok, msg, _ = await asyncio.to_thread(hsr_core.claim_hsr_standard_300, gid, interaction.user.id, cid)
        self._build()
        if ok:
            await core.safe_edit_response(interaction, content=msg, embed=self.build_embed(), view=self)
        else:
            await core.safe_send_response(interaction, f"⚠️ {msg}", ephemeral=True)

    def build_embed(self) -> discord.Embed:
        data = core.load_data()
        u_data = hsr_core.ensure_hsr_user(data, self.guild_id, self.user.id if self.user else 0)
        std_tot = int(u_data.get("standard_total_pulls", 0))
        claimed = bool(u_data.get("standard_300_claimed"))
        status = "✅ **이미 수령 완료!**" if claimed else ("🎊 **지금 선택 가능!**" if std_tot >= 300 else f"⏳ 진행 중 (`{std_tot}/300회`)")
        pct = min(100.0, (std_tot / 300.0) * 100.0)
        bar = "🟨" * int(round(pct / 10)) + "⬛" * max(0, 10 - int(round(pct / 10)))
        return discord.Embed(
            title="🎁 뭇별의 워프 — 누적 300회 5성 특별 초대",
            description=(
                f"상시 워프 누적 **300회**를 달성하면 상시 5성 캐릭터 7인 중 1명을 직접 영입할 수 있습니다!\n\n"
                f"• **현재 진행률:** `{min(300, std_tot)}/300회` (`{pct:.1f}%`) — {status}\n"
                f"  {bar}\n"
                f"• **선택 대상:** 히메코 · 웰트 · 브로냐 · 게파드 · 클라라 · 연경 · 백로"
            ),
            color=discord.Color.from_rgb(138, 128, 255),
        )


class HSRInventoryView(core.SafeView):
    def __init__(self, guild_id: int = 0, user: discord.User | None = None, filter_mode: str = "all", page: int = 0):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.user = user
        self.filter_mode = filter_mode
        self.page = page
        self._per_page = 10
        self._build()

    def _get_filtered_items(self) -> tuple[dict, list[dict]]:
        data = core.load_data()
        uid = self.user.id if self.user else 0
        u_data = hsr_core.ensure_hsr_user(data, self.guild_id, uid)
        items = list(u_data.get("items", {}).values())
        if self.filter_mode == "char":
            items = [it for it in items if it.get("kind") == "char"]
        elif self.filter_mode == "lc":
            items = [it for it in items if it.get("kind") == "lc"]
        elif self.filter_mode == "relic":
            items = [it for it in items if it.get("kind") == "relic"]
        elif self.filter_mode == "r5":
            items = [it for it in items if it.get("rank") == 5]
        elif self.filter_mode == "r4":
            items = [it for it in items if it.get("rank") == 4]
        elif self.filter_mode == "locked":
            items = [it for it in items if it.get("locked")]
        kind_ord = {"char": 0, "lc": 1, "relic": 2}
        items.sort(key=lambda x: (-int(x.get("rank", 3)), kind_ord.get(x.get("kind"), 9), -int(x.get("level", 1)), -int(x.get("count", 1)), x.get("name", "")))
        return u_data, items

    def _build(self):
        self.clear_items()
        _, items = self._get_filtered_items()
        max_page = max(0, (len(items) - 1) // self._per_page)
        self.page = max(0, min(self.page, max_page))
        sl = items[self.page * self._per_page:(self.page + 1) * self._per_page]

        f_opts = [
            discord.SelectOption(label="📋 전체 보유 목록", value="all", default=(self.filter_mode == "all")),
            discord.SelectOption(label="🧍 캐릭터만 보기", value="char", default=(self.filter_mode == "char")),
            discord.SelectOption(label="🪩 광추만 보기", value="lc", default=(self.filter_mode == "lc")),
            discord.SelectOption(label="🏺 유물만 보기", value="relic", default=(self.filter_mode == "relic")),
            discord.SelectOption(label="🌟 5성만 보기", value="r5", default=(self.filter_mode == "r5")),
            discord.SelectOption(label="💜 4성만 보기", value="r4", default=(self.filter_mode == "r4")),
            discord.SelectOption(label="🔒 잠금 항목만", value="locked", default=(self.filter_mode == "locked")),
        ]
        sel_f = discord.ui.Select(placeholder="🔍 보관함 필터 선택...", options=f_opts, row=0)
        sel_f.callback = self._on_filter
        self.add_item(sel_f)

        if sl:
            d_opts = []
            for it in sl:
                if it["kind"] == "char":
                    tag = f"E{it.get('eidolon', 0)}"
                elif it["kind"] == "relic":
                    tag = f"+{it.get('level', 3)}"
                else:
                    tag = f"S{it.get('superimposition', 1)}"
                lk = "🔒 " if it.get("locked") else ""
                d_opts.append(discord.SelectOption(
                    label=f"{lk}{it['rarity_label']} {it['name']} ({tag})"[:95],
                    value=it["item_key"],
                    description=f"Lv.{it.get('level', 1)} · 누적 {it.get('count', 1)}회 · 상세 일러스트/잠금/레벨업"[:95],
                ))
            sel_it = discord.ui.Select(placeholder="🖼️ 상세 일러스트 · 🔒잠금 · ⬆️레벨업 선택...", options=d_opts, row=1)
            sel_it.callback = self._on_select_item
            self.add_item(sel_it)

        b_prev = discord.ui.Button(label="◀ 이전", style=discord.ButtonStyle.secondary, disabled=(self.page <= 0), row=2)
        b_prev.callback = self._on_prev
        self.add_item(b_prev)

        b_next = discord.ui.Button(label="다음 ▶", style=discord.ButtonStyle.secondary, disabled=(self.page >= max_page), row=2)
        b_next.callback = self._on_next
        self.add_item(b_next)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인 보관함만 조작할 수 있습니다.", ephemeral=True)
            return False
        if self.user is None:
            self.user = interaction.user
            self.guild_id = interaction.guild_id or self.guild_id
        return True

    async def _on_filter(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return
        self.filter_mode = interaction.data["values"][0]
        self.page = 0
        self._build()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_prev(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return
        self.page = max(0, self.page - 1)
        self._build()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_next(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return
        self.page += 1
        self._build()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_select_item(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return
        ikey = interaction.data["values"][0]
        await core.safe_defer(interaction, ephemeral=True)
        gid = self.guild_id or interaction.guild_id or 0
        v = HSRItemDetailView(gid, interaction.user, ikey)
        emb, f = await v.build_embed_and_file()
        if f:
            await interaction.followup.send(embed=emb, file=f, view=v, ephemeral=True)
        else:
            await interaction.followup.send(embed=emb, view=v, ephemeral=True)

    def build_embed(self) -> discord.Embed:
        u_data, items = self._get_filtered_items()
        max_page = max(1, (len(items) + self._per_page - 1) // self._per_page)
        sl = items[self.page * self._per_page:(self.page + 1) * self._per_page]
        lines = []
        for idx, it in enumerate(sl, start=self.page * self._per_page + 1):
            lk = "🔒" if it.get("locked") else "🔓"
            if it["kind"] == "char":
                lines.append(
                    f"**{idx:02d}.** {lk} **{it['rarity_label']} {it['name']}** `E{it.get('eidolon', 0)}` · `Lv.{it.get('level', 1)}`\n"
                    f"└ {it.get('element_emoji', '')}{it.get('element_name', '')} · {it.get('path_emoji', '')}{it.get('path_name', '')} · 누적 `{it.get('count', 1)}회`"
                )
            elif it["kind"] == "relic":
                lines.append(
                    f"**{idx:02d}.** {lk} **{it['rarity_label']} {it['name']}** `+{it.get('level', 3)}` · 누적 `{it.get('count', 1)}회`\n"
                    f"└ {it.get('slot_name', '🏺유물')} · 주옵: `{it.get('main_stat', '-')}` · {it.get('bonus_2p', '')[:36]}"
                )
            else:
                lines.append(
                    f"**{idx:02d}.** {lk} **{it['rarity_label']} {it['name']}** `S{it.get('superimposition', 1)}` · 누적 `{it.get('count', 1)}회`\n"
                    f"└ {it.get('path_emoji', '')}{it.get('path_name', '')} 광추 · `{it.get('pool_type', '')}`"
                )
        body = "\n".join(lines) if lines else "*(해당 조건에 보유한 캐릭터·광추·유물이 없습니다)*"
        owner_n = self.user.display_name if self.user else "개척자"
        return discord.Embed(
            title=f"🎒 {owner_n}님의 스타레일 보관함 ({len(items)}종)",
            description=(
                f"🌟 별빛 `{u_data.get('starlight', 0):,}` · 🫧 잔재 `{u_data.get('embers', 0):,}` · 🧪 헤르타채권 `{u_data.get('herta_bond', 0):,}` · 📘 가이드 `{u_data.get('traveler_guide', 0):,}권`\n"
                f"• 캐릭터 `{u_data.get('pity_char', 0)}/90` · 광추 `{u_data.get('pity_lc', 0)}/80` · 유물 `{u_data.get('pity_relic', 0)}/50` · 상시 `{u_data.get('pity_standard', 0)}/90`\n\n"
                f"{body}"
            )[:4050],
            color=discord.Color.from_rgb(122, 74, 214),
            timestamp=datetime.datetime.now(core.KST),
        ).set_footer(text=f"페이지 {self.page + 1}/{max_page} • 아래에서 항목 선택 시 일러스트/잠금/레벨업 가능")


class HSRItemDetailView(core.SafeView):
    def __init__(self, guild_id: int = 0, user: discord.User | None = None, item_key: str = ""):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.user = user
        self.item_key = item_key
        self._build()

    def _build(self):
        self.clear_items()
        data = core.load_data()
        u_data = hsr_core.ensure_hsr_user(data, self.guild_id, self.user.id if self.user else 0)
        it = u_data.get("items", {}).get(self.item_key)
        locked = bool(it.get("locked")) if it else False

        b_lk = discord.ui.Button(label="🔓 잠금 해제" if locked else "🔒 잠금 설정", style=discord.ButtonStyle.secondary if locked else discord.ButtonStyle.primary, row=0)
        b_lk.callback = self._on_lock
        self.add_item(b_lk)

        if it and it.get("kind") == "char":
            b_lv = discord.ui.Button(
                label="⬆️ 레벨업 (+10Lv · 여행가이드 2권)" if int(it.get("level", 1)) < 80 else "✅ Lv.80 MAX",
                style=discord.ButtonStyle.success,
                disabled=(int(it.get("level", 1)) >= 80),
                row=0,
            )
            b_lv.callback = self._on_lvup
            self.add_item(b_lv)

    async def build_embed_and_file(self) -> tuple[discord.Embed, discord.File | None]:
        hsr_core.load_hsr_kr_db()
        data = core.load_data()
        u_data = hsr_core.ensure_hsr_user(data, self.guild_id, self.user.id if self.user else 0)
        owned = u_data.get("items", {}).get(self.item_key)
        master = hsr_core.HSR_ALL_ITEMS.get(self.item_key) or owned or {"id": "", "kind": "char", "name": "정보 없음", "rank": 4, "rarity_label": "★★★★"}
        it = {**master, **(owned or {})}
        det = await asyncio.to_thread(hsr_core.fetch_hsr_detail_kr, it["id"], it["kind"])
        img_bytes, fn = await asyncio.to_thread(hsr_core.fetch_hsr_item_image_bytes, it, True)

        lines = []
        if it["kind"] == "char":
            lines.append(f"• **속성/운명의 길:** {it.get('element_emoji', '')}{it.get('element_name', '')} · {it.get('path_emoji', '')}{it.get('path_name', '')} (`{it.get('path_role', '')}`)")
            lines.append(f"• **성장/성혼:** `Lv.{it.get('level', 1)}/80` · **성혼 `E{it.get('eidolon', 0)}/6`** · 전투력 `{hsr_core.compute_hsr_char_power(it):,}`")
            if det.get("faction"):
                lines.append(f"• **진영/소속:** `{det['faction']}`")
            if det.get("cv_kr"):
                lines.append(f"• **한국어 성우:** `{det['cv_kr']}`")
            if det.get("description"):
                lines.append(f"\n> {det['description'][:300]}")
        elif it["kind"] == "relic":
            lines.append(f"• **유물 분류/강화:** {it.get('path_emoji', '🏺')}{it.get('path_name', '터널 유물')} · {it.get('slot_name', '')} (**`+{it.get('level', 3)}/15`**)")
            lines.append(f"• **주옵션:** `{it.get('main_stat', '-')}` · **부옵션:** `{', '.join(it.get('sub_stats') or ['-'])}`")
            if it.get("bonus_2p"):
                lines.append(f"• **2세트 효과:** {it['bonus_2p']}")
            if it.get("bonus_4p"):
                lines.append(f"• **4세트 효과:** {it['bonus_4p'][:250]}")
        else:
            lines.append(f"• **운명의 길/출처:** {it.get('path_emoji', '')}{it.get('path_name', '')} · `{it.get('pool_type', '')}`")
            lines.append(f"• **중첩 단계:** **`S{it.get('superimposition', 1)}/5`** · 누적 `{it.get('count', 1)}회`")
            if det.get("skill_name"):
                lines.append(f"• **광추 스킬:** `{det['skill_name']}`")
            if det.get("description"):
                lines.append(f"\n> {det['description'][:300]}")

        emb = discord.Embed(
            title=f"{'🔒 ' if it.get('locked') else ''}{it.get('rarity_label', '')} {it.get('name', '')}",
            description="\n".join(lines),
            color=discord.Color.from_rgb(255, 200, 82) if it.get("rank") == 5 else discord.Color.from_rgb(174, 114, 255),
        )
        file_obj = None
        if img_bytes:
            file_obj = discord.File(io.BytesIO(img_bytes), filename=fn)
            emb.set_image(url=f"attachment://{fn}")
        else:
            emb.set_image(url=hsr_core.get_hsr_primary_image_url(it, True))
        return emb, file_obj

    async def _on_lock(self, interaction: discord.Interaction):
        if self.user and interaction.user.id != self.user.id:
            return await core.safe_send_response(interaction, "❌ 본인 항목만 잠금할 수 있습니다.", ephemeral=True)
        self.user = self.user or interaction.user
        gid = self.guild_id or (interaction.guild_id or 0)
        self.guild_id = gid
        await asyncio.to_thread(hsr_core.toggle_hsr_item_lock, gid, interaction.user.id, self.item_key)
        self._build()
        emb, _ = await self.build_embed_and_file()
        await core.safe_edit_response(interaction, embed=emb, view=self)

    async def _on_lvup(self, interaction: discord.Interaction):
        if self.user and interaction.user.id != self.user.id:
            return await core.safe_send_response(interaction, "❌ 본인 캐릭터만 레벨업할 수 있습니다.", ephemeral=True)
        self.user = self.user or interaction.user
        gid = self.guild_id or (interaction.guild_id or 0)
        self.guild_id = gid
        ok, msg, _ = await asyncio.to_thread(hsr_core.levelup_hsr_char, gid, interaction.user.id, self.item_key)
        if not ok:
            return await core.safe_send_response(interaction, msg, ephemeral=True)
        self._build()
        emb, _ = await self.build_embed_and_file()
        await core.safe_edit_response(interaction, content=msg, embed=emb, view=self)


class HSRPokedexView(core.SafeView):
    def __init__(self, guild_id: int = 0, user: discord.User | None = None, tab: str = "owned", kind_filter: str = "all", page: int = 0):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.user = user
        self.tab = tab
        self.kind_filter = kind_filter
        self.page = page
        self._per_page = 12
        self._build()

    def _get_list(self) -> tuple[dict, list[dict]]:
        uid = self.user.id if self.user else 0
        stats = hsr_core.get_hsr_pokedex_stats(self.guild_id, uid)
        raw = stats["owned_items"] if self.tab == "owned" else (stats["unowned_items"] if self.tab == "unowned" else (stats["owned_items"] + stats["unowned_items"]))
        if self.kind_filter == "char":
            raw = [it for it in raw if it["kind"] == "char"]
        elif self.kind_filter == "lc":
            raw = [it for it in raw if it["kind"] == "lc"]
        elif self.kind_filter == "relic":
            raw = [it for it in raw if it["kind"] == "relic"]
        kind_ord = {"char": 0, "lc": 1, "relic": 2}
        raw.sort(key=lambda x: (-int(x.get("rank", 3)), kind_ord.get(x.get("kind"), 9), x.get("name", "")))
        return stats, raw

    def _build(self):
        self.clear_items()
        _, items = self._get_list()
        max_page = max(0, (len(items) - 1) // self._per_page)
        self.page = max(0, min(self.page, max_page))

        for lbl, key in [("✨ 보유 목록", "owned"), ("❔ 미보유", "unowned"), ("📖 전체 도감", "all")]:
            b = discord.ui.Button(label=lbl, style=discord.ButtonStyle.primary if self.tab == key else discord.ButtonStyle.secondary, row=0)

            async def _cb(interaction: discord.Interaction, t=key):
                if self.user and interaction.user.id != self.user.id:
                    return await core.safe_send_response(interaction, "❌ 본인 도감 화면에서만 전환 가능합니다.", ephemeral=True)
                self.user = self.user or interaction.user
                self.guild_id = self.guild_id or (interaction.guild_id or 0)
                self.tab = t
                self.page = 0
                self._build()
                await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

            b.callback = _cb
            self.add_item(b)

        for lbl, kf in [("전체종류", "all"), ("캐릭터만", "char"), ("광추만", "lc"), ("유물만", "relic")]:
            b = discord.ui.Button(label=lbl, style=discord.ButtonStyle.success if self.kind_filter == kf else discord.ButtonStyle.secondary, row=1)

            async def _cb_k(interaction: discord.Interaction, k=kf):
                if self.user and interaction.user.id != self.user.id:
                    return await core.safe_send_response(interaction, "❌ 본인 도감 화면에서만 전환 가능합니다.", ephemeral=True)
                self.user = self.user or interaction.user
                self.guild_id = self.guild_id or (interaction.guild_id or 0)
                self.kind_filter = k
                self.page = 0
                self._build()
                await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

            b.callback = _cb_k
            self.add_item(b)

        b_prev = discord.ui.Button(label="◀ 이전", style=discord.ButtonStyle.secondary, disabled=(self.page <= 0), row=2)
        b_next = discord.ui.Button(label="다음 ▶", style=discord.ButtonStyle.secondary, disabled=(self.page >= max_page), row=2)

        async def _prev(interaction: discord.Interaction):
            if self.user and interaction.user.id != self.user.id:
                return await core.safe_send_response(interaction, "❌ 본인 도감 화면만 조작 가능합니다.", ephemeral=True)
            self.user = self.user or interaction.user
            self.guild_id = self.guild_id or (interaction.guild_id or 0)
            self.page = max(0, self.page - 1)
            self._build()
            await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

        async def _next(interaction: discord.Interaction):
            if self.user and interaction.user.id != self.user.id:
                return await core.safe_send_response(interaction, "❌ 본인 도감 화면만 조작 가능합니다.", ephemeral=True)
            self.user = self.user or interaction.user
            self.guild_id = self.guild_id or (interaction.guild_id or 0)
            self.page += 1
            self._build()
            await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

        b_prev.callback = _prev
        b_next.callback = _next
        self.add_item(b_prev)
        self.add_item(b_next)

    def build_embed(self) -> discord.Embed:
        stats, items = self._get_list()
        max_page = max(1, (len(items) + self._per_page - 1) // self._per_page)
        sl = items[self.page * self._per_page:(self.page + 1) * self._per_page]
        lines = []
        for it in sl:
            if it["kind"] == "char":
                e_txt = f" `E{it['eidolon']}`" if "eidolon" in it else ""
                lines.append(f"• {it['rarity_label']} **{it['name']}**{e_txt} ({it.get('element_emoji', '')}{it.get('path_name', '')} · `{it.get('pool_type', '')}`)")
            elif it["kind"] == "relic":
                l_txt = f" `+{it['level']}`" if "level" in it else ""
                lines.append(f"• {it.get('path_emoji', '🏺')} **{it['name']}**{l_txt} ({it.get('path_name', '터널 유물')} · {it.get('bonus_2p', '')[:34]})")
            else:
                s_txt = f" `S{it['superimposition']}`" if "superimposition" in it else ""
                lines.append(f"• {it['rarity_label']} **{it['name']}**{s_txt} ({it.get('path_emoji', '')}{it.get('path_name', '')} · `{it.get('pool_type', '')}`)")
        list_body = "\n".join(lines) if lines else "*(표시할 항목이 없습니다)*"
        owner_n = self.user.display_name if self.user else "개척자"
        r_own, r_tot = stats.get("r5", (0, 0))
        return discord.Embed(
            title=f"📖 {owner_n}님의 스타레일 은하 아카이브",
            description=(
                f"• **워프 도감 수집률:** `{stats['warpable_owned']}/{stats['warpable_total']}` (**`{stats['rate']:.1f}%`**)\n"
                f"  {stats['bar']}\n"
                f"• **캐릭터:** ★5 `{stats['c5'][0]}/{stats['c5'][1]}` · ★4 `{stats['c4'][0]}/{stats['c4'][1]}`\n"
                f"• **광추 & 유물:** 광추 ★5 `{stats['l5'][0]}/{stats['l5'][1]}` · ★4 `{stats['l4'][0]}/{stats['l4'][1]}` · 유물 세트 `{r_own}/{r_tot}`\n\n"
                f"{list_body}"
            )[:4050],
            color=discord.Color.from_rgb(174, 114, 255),
        ).set_footer(text=f"페이지 {self.page + 1}/{max_page} • 전체 DB {stats['total_all']}종 실시간 동기화")


class HSRShopView(core.SafeView):
    def __init__(self, guild_id: int = 0, user: discord.User | None = None, shop_tab: str = "starlight"):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.user = user
        self.shop_tab = shop_tab
        self._build()

    def _build(self):
        self.clear_items()
        cat = hsr_core.get_hsr_shop_catalog()

        for lbl, t in [("🌟 별빛·티켓 교환", "starlight"), ("🧪 헤르타 상점", "herta"), ("🫧 불멸의 잔재·광추", "embers")]:
            b = discord.ui.Button(label=lbl, style=discord.ButtonStyle.primary if self.shop_tab == t else discord.ButtonStyle.secondary, row=0)

            async def _cb(interaction: discord.Interaction, target_t=t):
                if self.user and interaction.user.id != self.user.id:
                    return await core.safe_send_response(interaction, "❌ 본인 상점만 전환 가능합니다.", ephemeral=True)
                self.user = self.user or interaction.user
                self.guild_id = self.guild_id or (interaction.guild_id or 0)
                self.shop_tab = target_t
                self._build()
                await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

            b.callback = _cb
            self.add_item(b)

        opts = []
        if self.shop_tab == "starlight":
            for c in cat["chars"]:
                opts.append(discord.SelectOption(
                    label=f"✨ [140 별빛] ★★★★ {c['name']}",
                    value=f"buy_char:{c['id']}",
                    description=f"{c['element_name']} · {c['path_name']} (월 1회 영입/성혼 +1)",
                ))
            for l in cat["std_5_lcs"]:
                opts.append(discord.SelectOption(
                    label=f"🪩 [600 별빛] ★★★★★ {l['name']}",
                    value=f"buy_5lc:{l['id']}",
                    description=f"{l['path_name']} 상시 5성 광추",
                ))
            opts.extend([
                discord.SelectOption(label="🎫 [20 별빛] 별의 궤도 전용티켓 ×1", value="sl_special_pass", description="한도 없음"),
                discord.SelectOption(label="🎟️ [20 별빛] 별의 궤도 티켓 ×1", value="sl_standard_pass", description="한도 없음"),
            ])
        elif self.shop_tab == "herta":
            for l in cat["herta_lcs"]:
                opts.append(discord.SelectOption(
                    label=f"🧪 [8 채권] ★★★★★ {l['name']}",
                    value=f"herta_lc:{l['id']}",
                    description=f"헤르타 상점 전용 {l['path_name']} 5성 광추",
                ))
            opts.append(discord.SelectOption(
                label="🔧 [2 채권] 중첩기 (특제) — 보유 헤르타 5★ 광추 S+1",
                value="herta_superimposer",
                description="S5 미만 헤르타 5성 광추 1단계 즉시 중첩!",
            ))
        else:
            opts.extend([
                discord.SelectOption(label="🎫 [90 잔재] 별의 궤도 전용티켓 ×1", value="embers_special_pass", description="월 5회 제한"),
                discord.SelectOption(label="🎟️ [90 잔재] 별의 궤도 티켓 ×1", value="embers_standard_pass", description="월 5회 제한"),
                discord.SelectOption(label="📘 [60 잔재] 여행 가이드 ×5", value="embers_traveler_guide", description="캐릭터 Lv.1~80 육성 재료"),
            ])
            for l in cat["special_4_lcs"][:20]:
                opts.append(discord.SelectOption(
                    label=f"🪩 [160 잔재] ★★★★ {l['name']}",
                    value=f"manifest_lc:{l['id']}",
                    description=f"{l['path_name']} · {l['pool_type']}",
                ))

        if opts:
            sel = discord.ui.Select(placeholder="🛒 교환할 상품 선택...", options=opts[:25], row=1)
            sel.callback = self._on_buy
            self.add_item(sel)

    async def _on_buy(self, interaction: discord.Interaction):
        if self.user and interaction.user.id != self.user.id:
            return await core.safe_send_response(interaction, "❌ 본인 상점만 이용할 수 있습니다.", ephemeral=True)
        self.user = self.user or interaction.user
        gid = self.guild_id or (interaction.guild_id or 0)
        self.guild_id = gid
        offer = interaction.data["values"][0]
        ok, msg, _ = await asyncio.to_thread(hsr_core.purchase_hsr_shop_item, gid, interaction.user.id, offer)
        self._build()
        if ok:
            await core.safe_edit_response(interaction, content=msg, embed=self.build_embed(), view=self)
        else:
            await core.safe_send_response(interaction, f"⚠️ {msg}", ephemeral=True)

    def build_embed(self) -> discord.Embed:
        cat = hsr_core.get_hsr_shop_catalog()
        data = core.load_data()
        u_data = hsr_core.ensure_hsr_user(data, self.guild_id, self.user.id if self.user else 0)
        monthly = u_data.get("shop_monthly", {})
        if monthly.get("month_key") != cat["month_key"]:
            es = et = 0
        else:
            es = int(monthly.get("embers_special_pass", 0))
            et = int(monthly.get("embers_standard_pass", 0))

        chars_str = ", ".join(f"**{c['name']}**({c['element_emoji']})" for c in cat["chars"]) or "-"
        return discord.Embed(
            title=f"🛍️ 은하열차 별빛 & 헤르타 상점 ({cat['month']}월)",
            description=(
                f"• **보유 재화:** 🌟 별빛 **`{u_data.get('starlight', 0):,}`** · 🫧 잔재 **`{u_data.get('embers', 0):,}`** · 🧪 헤르타 채권 **`{u_data.get('herta_bond', 0):,}`**\n"
                f"• **티켓/경험치:** 🎫 전용 `{u_data.get('special_pass', 0):,}` · 🎟️ 티켓 `{u_data.get('standard_pass', 0):,}` · 📘 여행 가이드 `{u_data.get('traveler_guide', 0):,}권`\n\n"
                f"### 🌟 별빛 교환\n"
                f"• **이달의 4성 캐릭터 (140 별빛):** {chars_str}\n"
                f"• **상시 5성 광추 7종 (600 별빛):** 은하철도의 밤 · 아직 전투는 끝나지 않았다 등\n"
                f"• **별의 궤도 티켓 (20 별빛):** 무제한 교환\n\n"
                f"### 🧪 헤르타 상점 & 🫧 불멸의 잔재\n"
                f"• **헤르타 5성 광추 7종 (8 채권) & 특제 중첩기 (2 채권)** *(10연 워프마다 +1 채권!)*\n"
                f"• **불멸의 잔재 티켓 (90 잔재):** 전용 `{es}/5회` · 상시 `{et}/5회`\n"
                f"• **이벤트·망각의정원 ★4 광추 (160 잔재)** · **여행 가이드 ×5 (60 잔재)**"
            ),
            color=discord.Color.from_rgb(174, 114, 255),
        )


class HSRPartyView(core.SafeView):
    def __init__(self, guild_id: int = 0, user: discord.User | None = None):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.user = user
        self._build()

    def _build(self):
        self.clear_items()
        data = core.load_data()
        u_data = hsr_core.ensure_hsr_user(data, self.guild_id, self.user.id if self.user else 0)
        owned_chars = [v for v in u_data.get("items", {}).values() if isinstance(v, dict) and v.get("kind") == "char"]
        owned_chars.sort(key=lambda c: (-int(c.get("rank", 4)), -int(c.get("level", 1)), -int(c.get("eidolon", 0)), c.get("name", "")))

        if owned_chars:
            opts = [
                discord.SelectOption(
                    label=f"{c['rarity_label']} {c['name']} (E{c.get('eidolon', 0)} · Lv.{c.get('level', 1)})"[:95],
                    value=c["item_key"],
                    description=f"{c.get('element_emoji', '')}{c.get('element_name', '')} · {c.get('path_name', '')} · 전투력 {hsr_core.compute_hsr_char_power(c):,}"[:95],
                )
                for c in owned_chars[:25]
            ]
            sel = discord.ui.Select(
                placeholder="🚄 편대에 합류시킬 동료 최대 4명 선택...",
                options=opts,
                min_values=1,
                max_values=min(4, len(opts)),
                row=0,
            )
            sel.callback = self._on_pick
            self.add_item(sel)

        b_auto = discord.ui.Button(label="✨ 최강 시너지 자동 편성", style=discord.ButtonStyle.primary, row=1)
        b_auto.callback = self._on_auto
        self.add_item(b_auto)

        b_clr = discord.ui.Button(label="🧹 편대 비우기", style=discord.ButtonStyle.danger, row=1)
        b_clr.callback = self._on_clear
        self.add_item(b_clr)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인 편대만 수정할 수 있습니다.", ephemeral=True)
            return False
        if self.user is None:
            self.user = interaction.user
            self.guild_id = interaction.guild_id or self.guild_id
        return True

    async def _on_pick(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return
        gid = self.guild_id or interaction.guild_id or 0
        data = core.load_data()
        u_data = hsr_core.ensure_hsr_user(data, gid, interaction.user.id)
        u_data["party"] = list(interaction.data["values"])[:4]
        core.save_data(data)
        self._build()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_auto(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return
        gid = self.guild_id or interaction.guild_id or 0
        data = core.load_data()
        u_data = hsr_core.ensure_hsr_user(data, gid, interaction.user.id)
        chars = [v for v in u_data.get("items", {}).values() if isinstance(v, dict) and v.get("kind") == "char"]
        chars.sort(key=lambda c: -hsr_core.compute_hsr_char_power(c))
        chosen = []
        for tag in ("dps", "sup", "sus"):
            cand = next((c for c in chars if (c.get("role_tag") == tag) and c["item_key"] not in chosen), None)
            if cand:
                chosen.append(cand["item_key"])
        for c in chars:
            if len(chosen) >= 4:
                break
            if c["item_key"] not in chosen:
                chosen.append(c["item_key"])
        u_data["party"] = chosen[:4]
        core.save_data(data)
        self._build()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_clear(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return
        gid = self.guild_id or interaction.guild_id or 0
        data = core.load_data()
        u_data = hsr_core.ensure_hsr_user(data, gid, interaction.user.id)
        u_data["party"] = []
        core.save_data(data)
        self._build()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    def build_embed(self) -> discord.Embed:
        data = core.load_data()
        u_data = hsr_core.ensure_hsr_user(data, self.guild_id, self.user.id if self.user else 0)
        items = u_data.get("items", {})
        party_keys = [k for k in (u_data.get("party") or []) if k in items][:4]
        party_objs = [items[k] for k in party_keys]
        ana = hsr_core.analyze_hsr_party(party_objs)

        slot_lines = []
        for idx in range(4):
            if idx < len(party_objs):
                c = party_objs[idx]
                pwr = hsr_core.compute_hsr_char_power(c)
                slot_lines.append(
                    f"**편성 {idx + 1}:** {c['rarity_label']} **{c['name']}** ({c.get('element_emoji', '')}{c.get('path_emoji', '')}{c.get('path_name', '')} · `E{c.get('eidolon', 0)}` · `Lv.{c.get('level', 1)}` · `{pwr:,}`)"
                )
            else:
                slot_lines.append(f"**편성 {idx + 1}:** *(비어 있음)*")

        syn_txt = "\n".join(f"• {s}" for s in ana["synergies"]) if ana["synergies"] else "*(딜러·서포터·생존 조합 및 다속성 배치 시 시너지가 발동됩니다!)*"
        owner_n = self.user.display_name if self.user else "개척자"
        return discord.Embed(
            title=f"🚄 {owner_n}님의 스타레일 4인 개척 편대",
            description=(
                f"### ⚔️ 편대 배치 ({len(party_objs)}/4)\n"
                + "\n".join(slot_lines)
                + f"\n\n### 🪩 운명의 길 & 약점 격파 시너지 (`+{ana['bonus_pct']}%` · `{ana['elem_count']}속성`)\n"
                + syn_txt
                + f"\n\n🔥 **총 편대 전투력:** **`{ana['total_power']:,}`**"
            ),
            color=discord.Color.from_rgb(174, 114, 255),
        )


class HSRRankingView(core.SafeView):
    def __init__(self, guild_id: int = 0, mode: str = "ranking"):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.mode = mode
        self._build()

    def _build(self):
        self.clear_items()
        for lbl, m in [("🏆 서버 컬렉션 랭킹", "ranking"), ("🌟 10연 워프 명예의 전당", "hof"), ("⚡ 최근 ★5 속보", "recent")]:
            b = discord.ui.Button(label=lbl, style=discord.ButtonStyle.primary if self.mode == m else discord.ButtonStyle.secondary, row=0)

            async def _cb(interaction: discord.Interaction, target_m=m):
                self.guild_id = self.guild_id or (interaction.guild_id or 0)
                self.mode = target_m
                self._build()
                await core.safe_edit_response(interaction, embed=self.build_embed(interaction.guild), view=self)

            b.callback = _cb
            self.add_item(b)

    def build_embed(self, guild: discord.Guild | None = None) -> discord.Embed:
        data = core.load_data()
        g_key = str(self.guild_id or 0)
        g_users = data.get("hsr_users", {}).get(g_key, {})

        if self.mode == "hof":
            hof = hsr_core.get_hsr_hall_of_fame(data, self.guild_id)
            recs = hof["top_records"]
            lines = []
            for idx, r in enumerate(recs[:10], start=1):
                uid_i = int(r["uid"])
                mem = guild.get_member(uid_i) if guild else None
                uname = mem.display_name if mem else f"개척자({uid_i})"
                lines.append(f"**#{idx}** **{uname}** — ★5 **`{r['r5_count']}회`** (픽업 {r['pickup_count']} · 최소 {r['min_pity']}스택)\n└ {' / '.join(r['items'][:4])}")
            desc = "\n".join(lines) if lines else "*(아직 10연 워프 ★5 명예의 전당 기록이 없습니다)*"
            return discord.Embed(title="🌟 스타레일 10연 워프 명예의 전당", description=desc, color=discord.Color.gold())

        if self.mode == "recent":
            hof = hsr_core.get_hsr_hall_of_fame(data, self.guild_id)
            logs = hof["recent_5_logs"]
            lines = []
            for r in logs[:15]:
                uid_i = int(r["uid"])
                mem = guild.get_member(uid_i) if guild else None
                uname = mem.display_name if mem else f"개척자({uid_i})"
                pk = "🎯픽업 " if r.get("is_pickup") else ""
                lines.append(f"• **{uname}**: {pk}**★★★★★ {r['name']}** (`{r.get('pity', '?')}스택` · {r.get('banner', '')})")
            desc = "\n".join(lines) if lines else "*(최근 ★5 도약 로그가 없습니다)*"
            return discord.Embed(title="⚡ 스타레일 서버 ★5 최근 획득 속보", description=desc, color=discord.Color.from_rgb(255, 198, 86))

        rows = []
        for uid_s, u_data in g_users.items():
            if not isinstance(u_data, dict):
                continue
            items = u_data.get("items", {})
            if not items and not u_data.get("total_pulls"):
                continue
            r5_cnt = sum(1 for v in items.values() if v.get("rank") == 5)
            e6_cnt = sum(1 for v in items.values() if v.get("kind") == "char" and int(v.get("eidolon", 0)) >= 6)
            uniq_cnt = len(items)
            pulls = int(u_data.get("total_pulls", 0))
            rows.append((r5_cnt, e6_cnt, uniq_cnt, pulls, uid_s))
        rows.sort(key=lambda x: (-x[0], -x[1], -x[2], -x[3]))
        lines = []
        for idx, (r5, e6, uq, pl, uid_s) in enumerate(rows[:15], start=1):
            mem = guild.get_member(int(uid_s)) if guild else None
            uname = mem.display_name if mem else f"개척자({uid_s})"
            medal = ["🥇", "🥈", "🥉"][idx - 1] if idx <= 3 else f"**#{idx}**"
            lines.append(f"{medal} **{uname}** — ★5 `{r5}종` (성혼6 `{e6}`) · 도감 `{uq}종` · 워프 `{pl:,}회`")
        desc = "\n".join(lines) if lines else "*(아직 이 서버에 스타레일 워프 기록이 있는 유저가 없습니다)*"
        return discord.Embed(title="🏆 스타레일 서버 컬렉션 랭킹 TOP 15", description=desc, color=discord.Color.from_rgb(174, 114, 255))


class HSRRateView(core.SafeView):
    def __init__(self, banner_key: str = "char1"):
        super().__init__(timeout=180)
        self.banner_key = banner_key
        self._build()

    def _build(self):
        self.clear_items()
        for k, cfg in hsr_core.HSR_BANNER_CONFIGS.items():
            b = discord.ui.Button(
                label=cfg["short_name"],
                style=discord.ButtonStyle.primary if self.banner_key == k else discord.ButtonStyle.secondary,
                row=0,
            )

            async def _cb(interaction: discord.Interaction, bk=k):
                self.banner_key = bk
                self._build()
                await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

            b.callback = _cb
            self.add_item(b)

    def build_embed(self) -> discord.Embed:
        data = core.get_cached_data()
        eff = hsr_core.resolve_effective_hsr_pickup(data.get("hsr_pickup"))
        cfg = hsr_core.HSR_BANNER_CONFIGS.get(self.banner_key, hsr_core.HSR_BANNER_CONFIGS["char1"])
        c4_txt = ", ".join(c["name"] for c in eff["char_4"]) or "-"
        l4_txt = ", ".join(l["name"] for l in eff["lc_4"]) or "-"
        rot_win = eff.get("time_window") or "실시간"

        if self.banner_key in ("char1", "char2"):
            feat = eff["char1"] if self.banner_key == "char1" else eff["char2"]
            feat_name = feat["name"] if feat else "-"
            feat_meta = f"{feat['element_emoji']}{feat['element_name']} · {feat['path_emoji']}{feat['path_name']}" if feat else "-"
            body = (
                f"• **시각별 로테이션:** `⏰ {rot_win}` ({eff.get('banner_name', '')})\n"
                f"• **픽업 ★★★★★ 캐릭터:** **`{feat_name}`** ({feat_meta})\n"
                f"• **픽업 ★★★★ 캐릭터 (50% 확률업):** `{c4_txt}`\n"
                f"• **기본 5성 확률:** `0.6%` (`74스택` 소프트 +6% · `90스택` 확정 · 50/50 실패 시 다음 확정)\n"
                f"• **공유 규칙:** 캐릭터 워프 ①과 ②는 5성 천장 및 확정 상태를 공유합니다.\n"
                f"• **추가 보너스:** 워프 10회마다 `헤르타 채권 ×1` 자동 적립!"
            )
        elif self.banner_key == "lc":
            l1, l2 = eff.get("lc_1"), eff.get("lc_2")
            l1_txt = f"{l1['name']} ({l1['path_emoji']}{l1['path_name']})" if l1 else "-"
            l2_txt = f"{l2['name']} ({l2['path_emoji']}{l2['path_name']})" if l2 else "-"
            body = (
                f"• **시각별 전용 광추 연동:** `⏰ {rot_win}`\n"
                f"• **픽업 ★★★★★ 광추 ①:** **`{l1_txt}`**\n"
                f"• **픽업 ★★★★★ 광추 ②:** **`{l2_txt}`**\n"
                f"• **픽업 ★★★★ 광추 (75% 확률업):** `{l4_txt}`\n"
                f"• **기본 5성 확률:** `0.8%` (`66스택` 소프트 +7% · `80스택` 확정 · **75/25**)\n"
                f"• **픽뚫 보정:** 75/25 실패 시 다음 ★5 광추는 100% 픽업 광추 확정!"
            )
        elif self.banner_key == "relic":
            r1, r2 = eff.get("relic_1"), eff.get("relic_2")
            body = (
                f"• **시각별 터널/장신구 로테이션:** `⏰ {rot_win}`\n"
                f"• **픽업 ★★★★★ 유물 세트 ①:** **`{r1['name'] if r1 else '-'}`** ({r1.get('bonus_2p', '-') if r1 else '-'})\n"
                f"• **픽업 ★★★★★ 장신구 세트 ②:** **`{r2['name'] if r2 else '-'}`** ({r2.get('bonus_2p', '-') if r2 else '-'})\n"
                f"• **드랍 및 감정 규칙:** 터널 유물 4부위(🪖머리·🧤핸드·🧥바디·🥾풋) 및 차원 장신구 2부위(🌐차원구체·🪢연결매듭) + 주옵션·부옵션 4줄 실시간 감정!\n"
                f"• **기본 5성 확률:** `2.5%` (`35스택` 소프트 · `50스택` 확정 · 픽업 세트 80% 우대)"
            )
        else:
            body = (
                "• **상시 ★★★★★ 캐릭터(7인):** 히메코 · 웰트 · 브로냐 · 게파드 · 클라라 · 연경 · 백로\n"
                "• **상시 ★★★★★ 광추(7종):** 은하철도의 밤, 대체할 수 없는 것, 아직 전투는 끝나지 않았다 등\n"
                "• **300회 특별 초대:** 상시 워프 누적 300회 달성 시 `/스타레일 상시300선택`으로 원하는 ★5 직접 영입!\n"
                "• **확률:** `0.6%` (`74스택` 소프트 · `90스택` 확정 · 캐릭터/광추 50:50)"
            )
        return discord.Embed(
            title=f"📊 {cfg['name']} — 상세 확률표",
            description=body,
            color=discord.Color.from_rgb(*cfg["color"]),
        )


class HSRGuildResetConfirmView(core.SafeView):
    def __init__(self, guild_id: int = 0, caller: discord.User | None = None):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.caller = caller

    @discord.ui.button(label="⚠️ 예, 이 서버 스타레일 데이터 초기화", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.caller and interaction.user.id != self.caller.id:
            return await core.safe_send_response(interaction, "❌ 요청한 관리자만 확정할 수 있습니다.", ephemeral=True)
        data = core.load_data()
        g_key = str(self.guild_id or interaction.guild_id or 0)
        data.get("hsr_users", {}).pop(g_key, None)
        data.get("hsr_hall_of_fame", {}).pop(g_key, None)
        core.save_data(data)
        await core.safe_edit_response(interaction, content="🧹 이 서버의 모든 스타레일 워프 데이터가 깔끔하게 초기화되었습니다.", embed=None, view=None)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_edit_response(interaction, content="취소되었습니다.", embed=None, view=None)


# ==========================================
# /스타레일 GroupCog (11 Subcommands + Prefix Shortcuts)
# ==========================================
class HSRCog(commands.GroupCog, group_name="스타레일", group_description="🚄 붕괴: 스타레일 워프 · 유물 감정 · 아카이브 도감 · 별빛/헤르타 상점 · 편대 시너지"):
    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    @app_commands.command(name="워프", description="🚄 스타레일 워프 (캐릭터·광추·유물·상시 · 시각별 로테이션 · 3.5초 승차권 연출)")
    @app_commands.describe(
        배너="워프를 진행할 배너 종류를 선택하세요 (캐릭터/광추/유물/상시)",
        횟수="10회 또는 1회 워프",
        연습모드="True 선택 시 쿨타임 없이 가상 워프만 테스트합니다 (보관함/천장 미저장)",
        연출스킵="True 선택 시 3.5초 연출을 건너뛰고 바로 결과판을 출력합니다 (쿨타임 5.0초)",
    )
    @app_commands.choices(
        배너=[
            app_commands.Choice(name="🚆 캐릭터 이벤트 워프 ①", value="char1"),
            app_commands.Choice(name="🌠 캐릭터 이벤트 워프 ②", value="char2"),
            app_commands.Choice(name="🪩 빛의 자취 (광추 워프)", value="lc"),
            app_commands.Choice(name="🏺 침식된 터널 · 장신구 (유물 워프)", value="relic"),
            app_commands.Choice(name="🌌 뭇별의 워프 (상시)", value="standard"),
        ],
        횟수=[
            app_commands.Choice(name="10회 워프", value=10),
            app_commands.Choice(name="1회 워프", value=1),
        ],
    )
    async def warp_cmd(
        self,
        interaction: discord.Interaction,
        배너: str = "char1",
        횟수: int = 10,
        연습모드: bool = False,
        연출스킵: bool = False,
    ):
        if not 연습모드:
            ok, rem = core.check_and_update_gacha_cooldown(interaction.user.id, skip_anim=연출스킵)
            if not ok:
                return await core.safe_send_response(
                    interaction,
                    f"⏳ 가챠 쿨타임 중입니다! **`{rem:.1f}초`** 후 다시 워프해 주세요. ({'스킵 5.0초' if 연출스킵 else '기본 3.5초'})",
                    ephemeral=True,
                )
        await core.safe_defer(interaction)
        res = await asyncio.to_thread(hsr_core.execute_hsr_warp, interaction.guild_id or 0, interaction.user.id, 배너, 횟수, 연습모드)
        v = HSRWarpAgainView(interaction.user, banner_key=배너, skip_anim=연출스킵, practice=연습모드, last_count=횟수)
        await send_hsr_warp_result(interaction, res, view=v, skip_anim=연출스킵)

    @app_commands.command(name="상시300선택", description="🎁 뭇별의 워프 300회 달성 시 상시 5성 캐릭터 1명을 직접 선택 영입합니다")
    async def standard_300_cmd(self, interaction: discord.Interaction):
        v = HSRStandard300View(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v, ephemeral=True)

    @app_commands.command(name="확률", description="📊 현재 스타레일 시각별 픽업 배너와 캐릭터·광추·유물 천장 확률을 확인합니다")
    @app_commands.choices(배너=[
        app_commands.Choice(name="🚆 캐릭터 워프 ①", value="char1"),
        app_commands.Choice(name="🌠 캐릭터 워프 ②", value="char2"),
        app_commands.Choice(name="🪩 빛의 자취 (광추)", value="lc"),
        app_commands.Choice(name="🏺 침식된 터널 · 장신구 (유물)", value="relic"),
        app_commands.Choice(name="🌌 뭇별의 워프 (상시)", value="standard"),
    ])
    async def rate_cmd(self, interaction: discord.Interaction, 배너: str = "char1"):
        v = HSRRateView(배너)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v)

    @app_commands.command(name="보관함", description="🎒 보유 중인 스타레일 캐릭터(성혼 E0~E6) · 광추(중첩 S1~S5) · 유물(+15) · 잠금 관리")
    @app_commands.choices(필터=[
        app_commands.Choice(name="전체", value="all"),
        app_commands.Choice(name="캐릭터만", value="char"),
        app_commands.Choice(name="광추만", value="lc"),
        app_commands.Choice(name="유물만", value="relic"),
        app_commands.Choice(name="★5만", value="r5"),
        app_commands.Choice(name="★4만", value="r4"),
        app_commands.Choice(name="잠금🔒만", value="locked"),
    ])
    async def inventory_cmd(self, interaction: discord.Interaction, 필터: str = "all"):
        v = HSRInventoryView(interaction.guild_id or 0, interaction.user, filter_mode=필터)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v)

    @app_commands.command(name="도감", description="📖 붕괴: 스타레일 전체 캐릭터·광추·유물 실시간 DB 아카이브 도감을 확인합니다")
    @app_commands.choices(탭=[
        app_commands.Choice(name="보유 목록", value="owned"),
        app_commands.Choice(name="미보유", value="unowned"),
        app_commands.Choice(name="전체 도감", value="all"),
    ])
    async def pokedex_cmd(self, interaction: discord.Interaction, 탭: str = "owned"):
        v = HSRPokedexView(interaction.guild_id or 0, interaction.user, tab=탭)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v)

    @app_commands.command(name="상점", description="🛍️ 스타레일 별빛 교환 (600 별빛 5★ 광추) · 헤르타 상점 (채권) · 불멸의 잔재")
    async def shop_cmd(self, interaction: discord.Interaction):
        v = HSRShopView(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v)

    @app_commands.command(name="파티편성", description="⚔️ 보유 스타레일 동료 4명 편대 구성 및 운명의 길·약점 격파 시너지 계산")
    @app_commands.autocomplete(
        슬롯1=hsr_core.hsr_owned_char_autocomplete,
        슬롯2=hsr_core.hsr_owned_char_autocomplete,
        슬롯3=hsr_core.hsr_owned_char_autocomplete,
        슬롯4=hsr_core.hsr_owned_char_autocomplete,
    )
    async def party_cmd(
        self,
        interaction: discord.Interaction,
        슬롯1: Optional[str] = None,
        슬롯2: Optional[str] = None,
        슬롯3: Optional[str] = None,
        슬롯4: Optional[str] = None,
    ):
        chosen = [s for s in (슬롯1, 슬롯2, 슬롯3, 슬롯4) if s]
        if chosen:
            dedup = []
            for k in chosen:
                if k not in dedup:
                    dedup.append(k)
            data = core.load_data()
            u_data = hsr_core.ensure_hsr_user(data, interaction.guild_id or 0, interaction.user.id)
            u_items = u_data.get("items", {})
            u_data["party"] = [k for k in dedup if k in u_items and u_items[k].get("kind") == "char"][:4]
            core.save_data(data)
        v = HSRPartyView(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v)

    @app_commands.command(name="프로필", description="🪪 나 또는 다른 개척자의 스타레일 쇼케이스 카드(천장 · 대표캐릭터 · 편대)를 봅니다")
    @app_commands.autocomplete(대표캐릭터=hsr_core.hsr_owned_char_autocomplete)
    async def profile_cmd(
        self,
        interaction: discord.Interaction,
        대상: Optional[discord.Member] = None,
        대표캐릭터: Optional[str] = None,
        상태문구: Optional[str] = None,
    ):
        target = 대상 or interaction.user
        if (대표캐릭터 or 상태문구 is not None) and target.id != interaction.user.id:
            return await core.safe_send_response(interaction, "❌ 대표 캐릭터와 상태 문구는 본인 프로필에서만 수정 가능합니다.", ephemeral=True)

        data = core.load_data()
        u_data = hsr_core.ensure_hsr_user(data, interaction.guild_id or 0, target.id)
        if target.id == interaction.user.id:
            changed = False
            u_items = u_data.get("items", {})
            if 대표캐릭터 and 대표캐릭터 in u_items and u_items[대표캐릭터].get("kind") == "char":
                u_data["profile_char"] = 대표캐릭터
                changed = True
            if 상태문구 is not None:
                u_data["profile_note"] = 상태문구.strip()[:80]
                changed = True
            if changed:
                core.save_data(data)

        items = u_data.get("items", {})
        chars = [v for v in items.values() if v.get("kind") == "char"]
        chars.sort(key=lambda c: (-int(c.get("rank", 4)), -int(c.get("eidolon", 0)), -int(c.get("level", 1))))
        p_key = u_data.get("profile_char")
        rep_char = items.get(p_key) if p_key and p_key in items and items[p_key].get("kind") == "char" else (chars[0] if chars else None)

        party_objs = [items[k] for k in (u_data.get("party") or []) if k in items][:4]
        party_ana = hsr_core.analyze_hsr_party(party_objs)
        top3 = ", ".join(f"{c['name']}(E{c.get('eidolon', 0)})" for c in chars[:3]) or "없음"
        note_str = u_data.get("profile_note") or "은하의 끝까지 개척!"
        rep_str = (
            f"{rep_char['rarity_label']} **{rep_char['name']}** (`E{rep_char.get('eidolon', 0)}` · `Lv.{rep_char.get('level', 1)}`)"
            if rep_char else "미설정"
        )

        emb = discord.Embed(
            title=f"🪪 {target.display_name}님의 스타레일 개척자 프로필",
            description=(
                f"💬 *\"{note_str}\"*\n\n"
                f"• **대표 캐릭터:** {rep_str}\n"
                f"• **워프 통계:** 누적 `{u_data.get('total_pulls', 0):,}회` · 고유 수집 `{len(items)}종` · 상시 `{u_data.get('standard_total_pulls', 0)}/300`\n"
                f"• **현재 천장:** 캐릭터 `{u_data.get('pity_char', 0)}/90` ({'확정' if u_data.get('guaranteed_char') else '반천'}) · 광추 `{u_data.get('pity_lc', 0)}/80` · 유물 `{u_data.get('pity_relic', 0)}/50` · 상시 `{u_data.get('pity_standard', 0)}/90`\n"
                f"• **재화:** 🌟 별빛 `{u_data.get('starlight', 0):,}` · 🫧 잔재 `{u_data.get('embers', 0):,}` · 🧪 채권 `{u_data.get('herta_bond', 0):,}`\n"
                f"• **주력 동료:** {top3}\n"
                f"• **편대 전투력:** `{party_ana['total_power']:,}` (시너지 {len(party_ana['synergies'])}개 · `+{party_ana['bonus_pct']}%`)"
            ),
            color=discord.Color.from_rgb(174, 114, 255),
            timestamp=datetime.datetime.now(core.KST),
        )
        if rep_char:
            emb.set_thumbnail(url=hsr_core.get_hsr_primary_image_url(rep_char, splash=False))
        else:
            emb.set_thumbnail(url=target.display_avatar.url)
        await core.safe_send_response(interaction, embed=emb)

    @app_commands.command(name="랭킹", description="🏆 서버 스타레일 수집 랭킹 · 10연 명예의 전당 · 최근 ★5 속보를 확인합니다")
    async def ranking_cmd(self, interaction: discord.Interaction):
        v = HSRRankingView(interaction.guild_id or 0, mode="ranking")
        await core.safe_send_response(interaction, embed=v.build_embed(interaction.guild), view=v)

    @app_commands.command(name="픽업설정", description="🔒 [봇 주인 전용] 스타레일 이벤트 워프 픽업(5성/4성/광추/유물/시각 로테이션)을 변경합니다")
    @app_commands.choices(프리셋=[
        app_commands.Choice(name="⏰ KST 시각 연동 2시간 자동 로테이션 (권장)", value="time_rotation"),
        app_commands.Choice(name="✨ 최신 개척 캐릭터 (펄 / 스파키)", value="latest"),
        app_commands.Choice(name="🎭 환락의 축복 스테이지 (어벤츄린•웨이브 / 로빈•서머레토)", value="elation_stage"),
        app_commands.Choice(name="👑 Fate/stay night 콜라보 (세이버 / 길가메시)", value="fate_collab"),
        app_commands.Choice(name="☀️ 앰포리어스 (파이논 / 카스토리스)", value="amphoreus_dawn"),
        app_commands.Choice(name="❄️ 영원의 기억 (키레네 / 더 헤르타)", value="amphoreus_memory"),
        app_commands.Choice(name="🌌 페나코니 (아케론 / 반디)", value="penacony_dream"),
        app_commands.Choice(name="🎵 은하 화합 (로빈 / 선데이)", value="ipc_harmony"),
        app_commands.Choice(name="🧹 기본값 초기화", value="reset"),
    ])
    @app_commands.autocomplete(
        캐릭터1=hsr_core.hsr_5star_char_autocomplete,
        캐릭터2=hsr_core.hsr_5star_char_autocomplete,
        사성1=hsr_core.hsr_4star_char_autocomplete,
        사성2=hsr_core.hsr_4star_char_autocomplete,
        사성3=hsr_core.hsr_4star_char_autocomplete,
        광추1=hsr_core.hsr_5star_lc_autocomplete,
        광추2=hsr_core.hsr_5star_lc_autocomplete,
        유물1=hsr_core.hsr_relic_autocomplete,
        유물2=hsr_core.hsr_relic_autocomplete,
    )
    async def setup_pickup_cmd(
        self,
        interaction: discord.Interaction,
        프리셋: Optional[str] = None,
        캐릭터1: Optional[str] = None,
        캐릭터2: Optional[str] = None,
        사성1: Optional[str] = None,
        사성2: Optional[str] = None,
        사성3: Optional[str] = None,
        광추1: Optional[str] = None,
        광추2: Optional[str] = None,
        유물1: Optional[str] = None,
        유물2: Optional[str] = None,
        배너이름: Optional[str] = None,
    ):
        if not await self.bot.is_bot_owner_user(interaction.user):
            return await core.safe_send_response(
                interaction,
                "⛔ **권한 부족:** `/스타레일 픽업설정`은 **봇 주인(소유자) 전용** 명령어입니다!",
                ephemeral=True,
            )

        await core.safe_defer(interaction, ephemeral=True)
        if 프리셋 and not any([캐릭터1, 캐릭터2, 사성1, 사성2, 사성3, 광추1, 광추2, 유물1, 유물2, 배너이름]):
            ok, msg, eff = await asyncio.to_thread(hsr_core.apply_hsr_pickup_preset, 프리셋)
        else:
            chars, lcs = hsr_core.load_hsr_kr_db()
            by_c = {c["id"]: c for c in chars}
            by_l = {l["id"]: l for l in lcs}
            by_r = {r["id"]: r for r in hsr_core.HSR_RELICS}
            data = core.load_data()
            cfg = dict(data.get("hsr_pickup") or {})
            if 프리셋 and 프리셋 not in ("reset", "time_rotation"):
                pr = hsr_core.HSR_BANNER_PRESETS.get(프리셋, {})
                cfg.update({k: pr[k] for k in ("char1", "char2", "char_4_ids", "lc_1", "lc_2", "relic_1", "relic_2", "banner_name") if k in pr})
            if 캐릭터1 and 캐릭터1 in by_c:
                cfg["char1"] = 캐릭터1
            if 캐릭터2 and 캐릭터2 in by_c:
                cfg["char2"] = 캐릭터2
            custom_4s = [x for x in (사성1, 사성2, 사성3) if x and x in by_c]
            if custom_4s:
                cfg["char_4_ids"] = custom_4s
            if 광추1 and 광추1 in by_l:
                cfg["lc_1"] = 광추1
            if 광추2 and 광추2 in by_l:
                cfg["lc_2"] = 광추2
            if 유물1 and 유물1 in by_r:
                cfg["relic_1"] = 유물1
            if 유물2 and 유물2 in by_r:
                cfg["relic_2"] = 유물2
            if 배너이름:
                cfg["banner_name"] = 배너이름.strip()[:60]
            cfg["updated_at"] = datetime.datetime.now(core.KST).isoformat()
            data["hsr_pickup"] = cfg
            core.save_data(data)
            eff = hsr_core.resolve_effective_hsr_pickup(cfg)
            msg = "✅ **스타레일 커스텀 워프 픽업이 적용되었습니다!**"

        emb = discord.Embed(
            title="🎯 스타레일 이벤트 워프 픽업 적용 완료",
            description=(
                f"{msg}\n\n"
                f"• **캐릭터 ① / ②:** `★★★★★ {eff['char1']['name'] if eff.get('char1') else '-'}` / `★★★★★ {eff['char2']['name'] if eff.get('char2') else '-'}`\n"
                f"• **픽업 ★★★★:** {', '.join(c['name'] for c in eff['char_4'])}\n"
                f"• **광추 ① / ②:** `{eff['lc_1']['name'] if eff.get('lc_1') else '-'}` / `{eff['lc_2']['name'] if eff.get('lc_2') else '-'}`\n"
                f"• **유물 ① / ②:** `{eff['relic_1']['name'] if eff.get('relic_1') else '-'}` / `{eff['relic_2']['name'] if eff.get('relic_2') else '-'}`"
            ),
            color=discord.Color.from_rgb(174, 114, 255),
        )
        await interaction.followup.send(embed=emb, ephemeral=True)

    @app_commands.command(name="서버초기화", description="🧹 [서버 관리자 전용] 이 서버의 모든 스타레일 워프/보관함 데이터를 초기화합니다")
    async def reset_guild_cmd(self, interaction: discord.Interaction):
        is_owner = await self.bot.is_bot_owner_user(interaction.user)
        perms = getattr(interaction.user, "guild_permissions", None)
        if not (is_owner or (perms and (perms.administrator or perms.manage_guild))):
            return await core.safe_send_response(interaction, "⛔ 서버 관리자 또는 봇 주인만 실행할 수 있습니다.", ephemeral=True)
        v = HSRGuildResetConfirmView(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(
            interaction,
            "⚠️ 정말로 **이 서버의 모든 유저 스타레일 워프 데이터**를 초기화하시겠습니까? (복구 불가)",
            view=v,
            ephemeral=True,
        )

    # 프리픽스 단축어 (!스타레일워프 / !스타레일뽑기 / !스타레일도감)
    @commands.command(name="스타레일워프", aliases=["스타레일뽑기"])
    async def prefix_warp(self, ctx: commands.Context, banner: str = "char1", count: int = 10):
        bmap = {"1": "char1", "2": "char2", "광추": "lc", "유물": "relic", "상시": "standard"}
        bk = bmap.get(banner, banner if banner in hsr_core.HSR_BANNER_CONFIGS else "char1")
        cnt = 10 if count >= 10 else 1
        ok, rem = core.check_and_update_gacha_cooldown(ctx.author.id, skip_anim=False)
        if not ok:
            return await ctx.reply(f"⏳ 가챠 쿨타임 중입니다! **`{rem:.1f}초`** 후 다시 시도해 주세요.")
        res = await asyncio.to_thread(hsr_core.execute_hsr_warp, ctx.guild.id if ctx.guild else 0, ctx.author.id, bk, cnt, False)
        emb, high_items = _build_hsr_result_embed(res, ctx.author)
        grid_buf = await asyncio.to_thread(hsr_core.build_hsr_10pull_grid_bytes, res["drawn"], bk, f"{res['user_state'].get('total_pulls', 0)}회") if cnt >= 2 else None
        files = []
        if grid_buf and grid_buf.getbuffer().nbytes > 0:
            files.append(discord.File(grid_buf, filename="hsr_grid.png"))
            emb.set_image(url="attachment://hsr_grid.png")
        elif high_items:
            sb, sfn = await asyncio.to_thread(hsr_core.fetch_hsr_item_image_bytes, high_items[0], True)
            if sb:
                files.append(discord.File(io.BytesIO(sb), filename=sfn))
                emb.set_image(url=f"attachment://{sfn}")
        v = HSRWarpAgainView(ctx.author, banner_key=bk, last_count=cnt)
        await ctx.reply(embed=emb, files=files, view=v)

    @commands.command(name="스타레일도감")
    async def prefix_pokedex(self, ctx: commands.Context):
        v = HSRPokedexView(ctx.guild.id if ctx.guild else 0, ctx.author, tab="owned")
        await ctx.reply(embed=v.build_embed(), view=v)


async def setup(bot: commands.Bot):
    await bot.add_cog(HSRCog(bot))
