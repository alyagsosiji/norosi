"""원신 (Genshin Impact) 기원 · 성유물 감정 · 보관함 · 도감 · 페이몬의 상점 · 파티 원소 공명 Cog

- 그룹 커맨드 `/원신` (11개 서브커맨드 + `!원신기원` 등 프리픽스 단축어)
- 티바트 성좌 네이비-골드 스타일 UI · 유성 승격 3.5초 연출 · 공유 가챠 쿨타임 (일반 3.5초 / 스킵 5.0초)
- 시각별 KST 2시간 자동 로테이션 (캐릭터 · 전용 무기 · 비경 성유물 동시 회전)
- 봇 주인 전용 `/원신 픽업설정` + 운명의 궤도(1/1) + 포착된 광휘 + 페이몬의 상점 + 4인 원소 공명 파티
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
import genshin_core

_MAX_FILES = 10
_MAX_TOTAL_BYTES = 7_800_000


def _build_genshin_intro_embed(result: dict) -> discord.Embed:
    drawn = result["drawn"]
    b_cfg = genshin_core.GENSHIN_BANNER_CONFIGS.get(result["banner_key"], genshin_core.GENSHIN_BANNER_CONFIGS["char1"])
    r5 = [it for it in drawn if it["rank"] == 5]
    r4 = [it for it in drawn if it["rank"] == 4]

    quote_block = "\n\n✨ *밤하늘을 가르는 운명의 별빛이 모이고 있습니다...*"
    if r5:
        top = sorted(r5, key=lambda x: not x.get("is_pickup"))[0]
        is_rad = any(x.get("is_radiance") for x in r5)
        if is_rad:
            orb = "🟣 분홍빛 궤적 ➔ 🌟 **포착된 광휘!! 금빛 유성으로 승격!!**"
            color = discord.Color.from_rgb(255, 130, 210)
        elif result["banner_key"] == "artifact":
            orb = "🌳 고목의 비경 ➔ 🌟 **찬란한 금빛 성유물 출현!!**"
            color = discord.Color.from_rgb(88, 224, 186)
        else:
            orb = "🔵 파란 유성 ➔ 🟣 보라 유성 ➔ 🌟 **찬란한 금빛 유성 강림!!**"
            color = discord.Color.from_rgb(255, 206, 84)
        det = genshin_core.fetch_genshin_detail_kr(top["id"], top["kind"])
        if top["kind"] == "char":
            c_title = det.get("title") or top.get("region_name", "티바트")
            c_const = det.get("constellation") or ""
            c_det = (det.get("detail") or "").strip()
            snippet = (c_det[:95] + "…") if len(c_det) > 95 else c_det
            meta = f"*{c_title}" + (f" · {c_const}*" if c_const else "*")
            quote_block = f"\n\n🌠 {meta}" + (f"\n💬 \"{snippet}\"" if snippet else "")
        elif top["kind"] == "artifact":
            b2 = top.get("bonus_2p") or det.get("bonus_2p") or ""
            slot_txt = top.get("slot_name", "성유물")
            main_txt = top.get("main_stat", "")
            quote_block = f"\n\n🏺 *{top['name']} ({slot_txt} · {main_txt})*" + (f"\n✨ 2세트: \"{b2[:90]}\"" if b2 else "")
        else:
            w_desc = (det.get("description") or "").strip()
            snippet = (w_desc[:95] + "…") if len(w_desc) > 95 else w_desc
            quote_block = f"\n\n⚔️ *전설의 무기가 공명합니다...*" + (f"\n💬 \"{snippet}\"" if snippet else "")
        tier_txt = "🌠 **★★★★★ 최고 등급 출현 확정!!**"
    elif r4:
        orb = "🔵 파란 유성 ➔ 🟣 **보라빛 유성 강림!!**"
        tier_txt = "⚡ **★★★★ 등급 이상 출현!**"
        color = discord.Color.from_rgb(174, 118, 255)
        top = sorted(r4, key=lambda x: (x["kind"] != "char", not x.get("is_pickup")))[0]
        det = genshin_core.fetch_genshin_detail_kr(top["id"], top["kind"])
        if top["kind"] == "char" and det.get("title"):
            quote_block = f"\n\n✨ *{det['title']}*의 별빛이 반짝입니다..."
        elif top["kind"] == "artifact":
            quote_block = f"\n\n🏺 *{top['name']} ({top.get('slot_name', '')})*의 유산이 공명합니다..."
    else:
        orb = "🔵 **푸른 유성이 밤하늘을 스쳐 지나갑니다...**"
        tier_txt = "🗡️ **기원이 진행 중입니다...**"
        color = discord.Color.from_rgb(84, 168, 255)

    embed = discord.Embed(
        title=f"🌠 {b_cfg['name']} ({len(drawn)}회)",
        description=f"{orb}\n{tier_txt}{quote_block}",
        color=color,
        timestamp=datetime.datetime.now(core.KST),
    )
    embed.set_footer(text="3.5초 후 기원 결과판과 일러스트가 공개됩니다!")
    return embed


def _build_genshin_result_embed(result: dict, user: discord.abc.User | None) -> tuple[discord.Embed, list[dict]]:
    drawn = result["drawn"]
    banner_key = result["banner_key"]
    eff = result["eff_pickup"]
    u_state = result["user_state"]
    practice = result["practice"]

    b_cfg = genshin_core.GENSHIN_BANNER_CONFIGS.get(banner_key, genshin_core.GENSHIN_BANNER_CONFIGS["char1"])
    r5 = [it for it in drawn if it["rank"] == 5]
    r4 = [it for it in drawn if it["rank"] == 4]
    r3 = [it for it in drawn if it["rank"] == 3]

    if r5:
        color = discord.Color.from_rgb(255, 204, 82)
    elif r4:
        color = discord.Color.from_rgb(172, 118, 255)
    else:
        color = discord.Color.from_rgb(*b_cfg["color"])

    lines = []
    for idx, it in enumerate(drawn, start=1):
        p_mark = "🎯**[픽업]** " if it.get("is_pickup") else ""
        rad_mark = "🌈**[포착된광휘!]** " if it.get("is_radiance") else ""
        fate_mark = "🧭**[궤도확정!]** " if it.get("is_fate_guaranteed") else ""
        new_mark = "✨**[NEW]** " if it.get("is_new") else ""

        if it["kind"] == "char":
            dup_txt = f"C{it.get('new_constellation', 0)}"
            tag = f"{it.get('element_emoji', '')}{it.get('element_name', '')} · {it.get('weapon_type_emoji', '')}{it.get('weapon_type_name', '')}"
        elif it["kind"] == "artifact":
            dup_txt = f"+{it.get('new_level', 4)}"
            subs = ", ".join((it.get("sub_stats") or [])[:2])
            tag = f"{it.get('slot_name', '🏺성유물')} · 주옵: {it.get('main_stat', '-')}" + (f" ({subs})" if subs else "")
        else:
            dup_txt = f"R{it.get('new_refinement', 1)}"
            tag = f"{it.get('weapon_type_emoji', '')}{it.get('weapon_type_name', '')}"

        pity_txt = f" · `{it['pity_used']}스택`" if it.get("pity_used") else ""
        rew = []
        if it.get("gained_starglitter"):
            rew.append(f"+{it['gained_starglitter']}✨스타라이트")
        if it.get("gained_stardust"):
            rew.append(f"+{it['gained_stardust']}💠더스트")
        rew_txt = f" ({', '.join(rew)})" if rew else ""

        lines.append(
            f"**{idx:02d}.** {rad_mark}{fate_mark}{p_mark}{new_mark}**{it['rarity_label']} {it['name']}** `{dup_txt}`{pity_txt}\n"
            f"└ `{tag}`{rew_txt}"
        )

    # 현재 천장 요약
    if banner_key in ("char1", "char2"):
        p_txt = f"`{u_state.get('pity_char', 0)}/90`"
        g_txt = "🔒 **확정**" if u_state.get("guaranteed_char") else "🎲 **반천장 (50/50)**"
        loss_s = int(u_state.get("loss_streak", 0))
        extra_p = f" · 광휘스택 `{loss_s}`" if loss_s > 0 else ""
        pity_line = f"• **캐릭터 기원 스택:** {p_txt} ({g_txt}{extra_p})"
    elif banner_key == "weapon":
        p_txt = f"`{u_state.get('pity_weapon', 0)}/80`"
        g_txt = "🔒 **75%픽업확정**" if u_state.get("guaranteed_weapon") else "🎲 **75/25**"
        fp = int(u_state.get("fate_point", 0))
        ft = u_state.get("fate_target_id")
        w_obj = next((w for w in (eff.get("weapon_1"), eff.get("weapon_2")) if w and w["id"] == ft), None)
        ft_name = w_obj["name"] if w_obj else "미설정"
        pity_line = f"• **무기 기원 스택:** {p_txt} ({g_txt}) · 🧭 궤도: `{ft_name}` (`{fp}/1`)"
    elif banner_key == "artifact":
        p_txt = f"`{u_state.get('pity_artifact', 0)}/50`"
        g_txt = "🔒 **픽업세트확정**" if u_state.get("guaranteed_artifact") else "🎲 **80/20 픽업우대**"
        pity_line = f"• **성유물 축복 스택:** {p_txt} ({g_txt} · 35스택 소프트 천장)"
    else:
        pity_line = f"• **상시 기원 스택:** `{u_state.get('pity_standard', 0)}/90`"

    if banner_key == "char1":
        feat_str = f"★★★★★ {eff['char1']['name']}" if eff.get("char1") else "픽업 없음"
    elif banner_key == "char2":
        feat_str = f"★★★★★ {eff['char2']['name']}" if eff.get("char2") else "픽업 없음"
    elif banner_key == "weapon":
        w_names = [w["name"] for w in (eff.get("weapon_1"), eff.get("weapon_2")) if w]
        feat_str = " / ".join(w_names) if w_names else "상시 무기"
    elif banner_key == "artifact":
        a_names = [a["name"] for a in (eff.get("artifact_1"), eff.get("artifact_2")) if a]
        feat_str = " / ".join(a_names) if a_names else "비경 성유물 세트"
    else:
        feat_str = "상시 5성 캐릭터 & 무기"

    rot_win = eff.get("time_window") or ""
    rot_tag = f" · ⏰ `{rot_win}`" if rot_win else ""
    mode_banner = "🧪 **[리세마라 연습 모드 — 미저장/천장 미반영]**\n" if practice else ""
    rew_sum = (
        f" · 💫 **보상:** `+{result['total_glitter']} 스타라이트` / `+{result['total_dust']} 스타더스트`"
        if not practice else ""
    )
    stat_bar = f"★★★★★ `{len(r5)}` · ★★★★ `{len(r4)}` · ★★★ `{len(r3)}`{rew_sum}"

    header = f"{mode_banner}🎰 **기원:** `{b_cfg['name']}`{rot_tag}\n🎯 **현재 픽업:** `{feat_str}`\n\n"
    footer_block = f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n{stat_bar}\n{pity_line}"
    body = "\n".join(lines)
    max_b = max(200, 4040 - len(header) - len(footer_block))
    if len(body) > max_b:
        body = body[:max_b - 14].rstrip() + "\n...*(생략)*"

    embed = discord.Embed(
        title=f"🌠 원신 {len(drawn)}회 기원 결과 ({b_cfg['short_name']})" + (" 🎊 ★5 등장!" if r5 else ""),
        description=(header + body + footer_block)[:4090],
        color=color,
        timestamp=datetime.datetime.now(core.KST),
    )
    if user:
        embed.set_author(name=f"{user.display_name}님의 티바트 기원", icon_url=user.display_avatar.url)
    embed.set_footer(text=f"보유 스타라이트 {u_state.get('starglitter', 0):,} · 스타더스트 {u_state.get('stardust', 0):,} | 하단에서 캐릭터·무기·성유물 배너 전환")

    high_items = [it for it in drawn if it["rank"] >= 5]
    if not high_items and len(drawn) == 1:
        high_items = [drawn[0]]
    elif not high_items and r4:
        high_items = sorted(r4, key=lambda x: (x["kind"] != "char", not x.get("is_pickup")))[:2]
    return embed, high_items


async def send_genshin_pull_result(
    interaction: discord.Interaction,
    result: dict,
    view: discord.ui.View,
    skip_anim: bool = False,
):
    drawn = result["drawn"]
    banner_key = result["banner_key"]
    main_embed, high_items = _build_genshin_result_embed(result, interaction.user)
    want_grid = len(drawn) >= 2
    splash_targets = high_items[:9]

    async def _empty_grid():
        return None, None

    async def _empty_list():
        return []

    img_coro = (
        asyncio.gather(*(asyncio.to_thread(genshin_core.fetch_genshin_item_image_bytes, it, True) for it in splash_targets))
        if splash_targets else _empty_list()
    )
    det_coro = (
        asyncio.gather(*(asyncio.to_thread(genshin_core.fetch_genshin_detail_kr, it["id"], it["kind"]) for it in splash_targets))
        if splash_targets else _empty_list()
    )
    tag = "연습 모드" if result["practice"] else f"{result['user_state'].get('total_pulls', 0)}회 누적"
    grid_coro = (
        asyncio.to_thread(genshin_core.build_genshin_10pull_grid_bytes, drawn, banner_key, tag)
        if want_grid else _empty_grid()
    )

    intro_msg = None
    if not skip_anim:
        intro_embed = await asyncio.to_thread(_build_genshin_intro_embed, result)
        try:
            intro_msg = await interaction.followup.send(embed=intro_embed, wait=True)
        except Exception:
            intro_msg = None
        img_results, det_results, grid_res, _ = await asyncio.gather(img_coro, det_coro, grid_coro, asyncio.sleep(3.5))
    else:
        img_results, det_results, grid_res = await asyncio.gather(img_coro, det_coro, grid_coro)

    file_specs: list[tuple[bytes, str]] = []
    total_bytes = 0
    if grid_res is not None:
        if isinstance(grid_res, tuple):
            g_bytes, g_fn = grid_res
        else:
            g_bytes, g_fn = grid_res.getvalue(), "genshin_grid.png"
        if g_bytes and len(g_bytes) <= _MAX_TOTAL_BYTES:
            safe_g_fn = g_fn or "genshin_grid.png"
            file_specs.append((g_bytes, safe_g_fn))
            total_bytes += len(g_bytes)
            main_embed.set_image(url=f"attachment://{safe_g_fn}")

    embeds = [main_embed]
    splash_pairs: list[tuple[discord.Embed, dict]] = []
    if not want_grid and splash_targets and img_results:
        sb, sfn = img_results[0]
        if sb and len(file_specs) < _MAX_FILES and total_bytes + len(sb) <= _MAX_TOTAL_BYTES:
            safe_fn = f"gi_1_{sfn}"
            file_specs.append((sb, safe_fn))
            total_bytes += len(sb)
            main_embed.set_image(url=f"attachment://{safe_fn}")
        else:
            main_embed.set_image(url=genshin_core.get_genshin_primary_image_url(splash_targets[0], True))
    else:
        for idx, (it, (sb, sfn), det) in enumerate(zip(splash_targets, img_results, det_results), start=1):
            if len(embeds) >= 10:
                break
            p_tag = "🎯 [픽업!] " if it.get("is_pickup") else ""
            n_tag = "✨ [NEW] " if it.get("is_new") else ""
            c_title = f"{p_tag}{n_tag}{it['rarity_label']} {it['name']}"
            if it["kind"] == "char":
                el_t = f"{it.get('element_emoji', '')} {it.get('element_name', '')}"
                wt_t = f"{it.get('weapon_type_emoji', '')} {it.get('weapon_type_name', '')}"
                extra_lines = [f"• **원소/무기:** {el_t} · {wt_t} · 📍 `{it.get('region_name', '티바트')}`"]
                if det.get("title"):
                    extra_lines.append(f"• **이명/별자리:** `{det['title']}`" + (f" ({det['constellation']})" if det.get("constellation") else ""))
                if det.get("cv_kr"):
                    extra_lines.append(f"• **한국어 성우:** `CV. {det['cv_kr']}`")
                if det.get("detail"):
                    d_txt = det["detail"]
                    extra_lines.append(f"• 💬 *\"{d_txt[:140]}{'…' if len(d_txt) > 140 else ''}\"*")
            elif it["kind"] == "artifact":
                extra_lines = [
                    f"• **감정 부위/주옵션:** {it.get('slot_name', '🏺성유물')} · **`{it.get('main_stat', '-')}`**",
                    f"• **부옵션 감정:** `{', '.join(it.get('sub_stats') or ['-'])}`",
                ]
                b2 = it.get("bonus_2p") or det.get("bonus_2p")
                b4 = it.get("bonus_4p") or det.get("bonus_4p")
                if b2:
                    extra_lines.append(f"• **2세트 효과:** {b2}")
                if b4:
                    extra_lines.append(f"• **4세트 효과:** {b4[:120]}{'…' if len(b4) > 120 else ''}")
            else:
                extra_lines = [
                    f"• **무기군:** {it.get('weapon_type_emoji', '')} {it.get('weapon_type_name', '')} · **부옵션:** `{it.get('special_prop_name', '-')}`"
                ]
                if det.get("description"):
                    d_txt = det["description"]
                    extra_lines.append(f"• 📜 *\"{d_txt[:140]}{'…' if len(d_txt) > 140 else ''}\"*")

            sp_embed = discord.Embed(
                title=c_title[:256],
                description="\n".join(extra_lines),
                color=discord.Color.from_rgb(255, 206, 86) if it["rank"] == 5 else discord.Color.from_rgb(176, 118, 255),
            )
            if sb and len(file_specs) < _MAX_FILES and total_bytes + len(sb) <= _MAX_TOTAL_BYTES:
                safe_fn = f"gi_{idx}_{sfn}"
                file_specs.append((sb, safe_fn))
                total_bytes += len(sb)
                sp_embed.set_image(url=f"attachment://{safe_fn}")
            else:
                sp_embed.set_image(url=genshin_core.get_genshin_primary_image_url(it, True))
            embeds.append(sp_embed)
            splash_pairs.append((sp_embed, it))

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
            sp_e.set_image(url=genshin_core.get_genshin_primary_image_url(sp_it, True))
        await interaction.followup.send(embeds=embeds, view=view)


# ==========================================
# 인터랙티브 SafeView 클래스들 (봇 재시작 복구 대응 기본값 완비)
# ==========================================
class _GenshinBannerSelect(discord.ui.Select):
    def __init__(self, current_banner: str = "char1", eff_pickup: dict | None = None):
        eff = eff_pickup or genshin_core.resolve_effective_genshin_pickup(None)
        c1_name = eff["char1"]["name"] if eff.get("char1") else "픽업 캐릭터 ①"
        c2_name = eff["char2"]["name"] if eff.get("char2") else "픽업 캐릭터 ②"
        w_names = " / ".join(w["name"] for w in (eff.get("weapon_1"), eff.get("weapon_2")) if w) or "픽업 무기"
        a_names = " / ".join(a["name"] for a in (eff.get("artifact_1"), eff.get("artifact_2")) if a) or "비경 성유물"
        options = [
            discord.SelectOption(label="🌠 캐릭터 이벤트 기원 ①", value="char1", description=f"픽업: {c1_name}"[:95], default=(current_banner == "char1")),
            discord.SelectOption(label="🌙 캐릭터 이벤트 기원 ②", value="char2", description=f"픽업: {c2_name}"[:95], default=(current_banner == "char2")),
            discord.SelectOption(label="⚔️ 신의 주조 (무기 기원)", value="weapon", description=f"픽업: {w_names}"[:95], default=(current_banner == "weapon")),
            discord.SelectOption(label="🏺 비경 성유물 축복 (성유물 감정)", value="artifact", description=f"픽업 세트: {a_names}"[:95], default=(current_banner == "artifact")),
            discord.SelectOption(label="🌌 세상 여행 (상시 기원)", value="standard", description="상시 5성 캐릭터·무기 · 초기 4성 포함", default=(current_banner == "standard")),
        ]
        super().__init__(placeholder="🎰 기원 배너 전환 (캐릭터·무기·성유물·상시)...", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        view: GenshinPullAgainView = self.view
        if not await view._check_owner(interaction):
            return
        view.banner_key = self.values[0]
        await view._run_repull_with_cooldown(interaction, view.last_count)


class GenshinPullAgainView(core.SafeView):
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
        eff = genshin_core.resolve_effective_genshin_pickup(data.get("genshin_pickup"))
        self.add_item(_GenshinBannerSelect(self.banner_key, eff))

        b10 = discord.ui.Button(label="🌠 10회 기원", style=discord.ButtonStyle.primary, row=1)
        b10.callback = self._on_10
        self.add_item(b10)

        b1 = discord.ui.Button(label="✨ 1회 기원", style=discord.ButtonStyle.secondary, row=1)
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
            bprac = discord.ui.Button(label="🧪 연습 모드 전환", style=discord.ButtonStyle.secondary, row=1)
            bprac.callback = self._on_toggle_practice
            self.add_item(bprac)
        else:
            breal = discord.ui.Button(label="⭐ 실전 모드 전환", style=discord.ButtonStyle.success, row=1)
            breal.callback = self._on_toggle_practice
            self.add_item(breal)

        if self.banner_key == "weapon":
            bfate = discord.ui.Button(label="🧭 운명의 궤도 변경", style=discord.ButtonStyle.secondary, row=2)
            bfate.callback = self._on_fate_btn
            self.add_item(bfate)

        binv = discord.ui.Button(label="🎒 보관함", style=discord.ButtonStyle.secondary, row=2)
        binv.callback = self._on_inv
        self.add_item(binv)

        bshop = discord.ui.Button(label="🛍️ 페이몬 상점", style=discord.ButtonStyle.secondary, row=2)
        bshop.callback = self._on_shop
        self.add_item(bshop)

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 기원 화면에서만 조작할 수 있습니다!", ephemeral=True)
            return False
        if self.user is None:
            self.user = interaction.user
        return True

    async def _run_repull_with_cooldown(self, interaction: discord.Interaction, count: int):
        async with self._lock:
            if not self.practice:
                ok, rem = core.check_and_update_gacha_cooldown(interaction.user.id, skip_anim=self.skip_anim)
                if not ok:
                    return await core.safe_send_response(
                        interaction,
                        f"⏳ 가챠 쿨타임 중입니다! **`{rem:.1f}초`** 후 다시 기원해 주세요. ({'스킵 5.0초' if self.skip_anim else '기본 3.5초'})",
                        ephemeral=True,
                    )
            await core.safe_defer(interaction)
            self.last_count = count
            self._build_items()
            res = await asyncio.to_thread(
                genshin_core.execute_genshin_pull,
                interaction.guild_id or 0,
                interaction.user.id,
                self.banner_key,
                count,
                self.practice,
            )
            await send_genshin_pull_result(interaction, res, view=self, skip_anim=self.skip_anim)

    async def _on_10(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return
        await self._run_repull_with_cooldown(interaction, 10)

    async def _on_1(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return
        await self._run_repull_with_cooldown(interaction, 1)

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

    async def _on_fate_btn(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return
        v = GenshinFatePathView(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v, ephemeral=True)

    async def _on_inv(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return
        v = GenshinInventoryView(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v, ephemeral=True)

    async def _on_shop(self, interaction: discord.Interaction):
        if not await self._check_owner(interaction):
            return
        v = GenshinShopView(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v, ephemeral=True)


class GenshinFatePathView(core.SafeView):
    def __init__(self, guild_id: int = 0, user: discord.User | None = None):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.user = user
        self._build()

    def _build(self):
        self.clear_items()
        data = core.load_data()
        eff = genshin_core.resolve_effective_genshin_pickup(data.get("genshin_pickup"))
        u_data = genshin_core.ensure_genshin_user(data, self.guild_id, self.user.id if self.user else 0)
        cur_id = u_data.get("fate_target_id")

        for w in (eff.get("weapon_1"), eff.get("weapon_2")):
            if not w:
                continue
            is_sel = (cur_id == w["id"])
            btn = discord.ui.Button(
                label=f"🧭 {w['name']}"[:80],
                style=discord.ButtonStyle.success if is_sel else discord.ButtonStyle.primary,
                row=0,
            )
            wid = w["id"]

            async def _cb(interaction: discord.Interaction, target_id=wid):
                await self._select(interaction, target_id)

            btn.callback = _cb
            self.add_item(btn)

        b_clear = discord.ui.Button(label="❌ 궤도 해제", style=discord.ButtonStyle.danger, row=0)

        async def _cb_clr(interaction: discord.Interaction):
            await self._select(interaction, "NONE")

        b_clear.callback = _cb_clr
        self.add_item(b_clear)

    async def _select(self, interaction: discord.Interaction, target_id: str):
        if self.user and interaction.user.id != self.user.id:
            return await core.safe_send_response(interaction, "❌ 본인만 궤도를 설정할 수 있습니다.", ephemeral=True)
        if self.user is None:
            self.user = interaction.user
        gid = self.guild_id or (interaction.guild_id or 0)
        self.guild_id = gid
        ok, msg, _ = await asyncio.to_thread(genshin_core.set_genshin_fate_path, gid, interaction.user.id, target_id)
        self._build()
        await core.safe_edit_response(interaction, content=msg, embed=self.build_embed(), view=self)

    def build_embed(self) -> discord.Embed:
        data = core.load_data()
        eff = genshin_core.resolve_effective_genshin_pickup(data.get("genshin_pickup"))
        u_data = genshin_core.ensure_genshin_user(data, self.guild_id, self.user.id if self.user else 0)
        ft = u_data.get("fate_target_id")
        fp = int(u_data.get("fate_point", 0))
        w1, w2 = eff.get("weapon_1"), eff.get("weapon_2")
        cur_obj = next((w for w in (w1, w2) if w and w["id"] == ft), None)
        cur_txt = f"`★★★★★ {cur_obj['name']}` (`명정 포인트 {fp}/1`)" if cur_obj else "미설정 (`0/1`)"
        return discord.Embed(
            title="🧭 신의 주조 — 운명의 궤도 정하기",
            description=(
                "원하는 픽업 5성 무기를 1종 선택하면, 다른 5성 무기가 나왔을 때 **명정 포인트 1**이 쌓이고\n"
                "다음 5성 무기는 **100% 정해진 무기**로 확정 획득됩니다! *(궤도 변경 시 명정 포인트는 초기화)*\n\n"
                f"• **현재 정해진 무기:** {cur_txt}\n"
                f"• **픽업 ①:** `★★★★★ {w1['name'] if w1 else '-'}`\n"
                f"• **픽업 ②:** `★★★★★ {w2['name'] if w2 else '-'}`"
            ),
            color=discord.Color.from_rgb(255, 165, 76),
        )


class GenshinInventoryView(core.SafeView):
    def __init__(
        self,
        guild_id: int = 0,
        user: discord.User | None = None,
        filter_mode: str = "all",
        page: int = 0,
    ):
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
        u_data = genshin_core.ensure_genshin_user(data, self.guild_id, uid)
        items = list(u_data.get("items", {}).values())
        if self.filter_mode == "char":
            items = [it for it in items if it.get("kind") == "char"]
        elif self.filter_mode == "weapon":
            items = [it for it in items if it.get("kind") == "weapon"]
        elif self.filter_mode == "artifact":
            items = [it for it in items if it.get("kind") == "artifact"]
        elif self.filter_mode == "r5":
            items = [it for it in items if it.get("rank") == 5]
        elif self.filter_mode == "r4":
            items = [it for it in items if it.get("rank") == 4]
        elif self.filter_mode == "locked":
            items = [it for it in items if it.get("locked")]
        kind_ord = {"char": 0, "weapon": 1, "artifact": 2}
        items.sort(key=lambda x: (-int(x.get("rank", 3)), kind_ord.get(x.get("kind"), 9), -int(x.get("level", 1)), -int(x.get("count", 1)), x.get("name", "")))
        return u_data, items

    def _build(self):
        self.clear_items()
        _, items = self._get_filtered_items()
        max_page = max(0, (len(items) - 1) // self._per_page)
        self.page = max(0, min(self.page, max_page))
        slice_items = items[self.page * self._per_page:(self.page + 1) * self._per_page]

        f_opts = [
            discord.SelectOption(label="📋 전체 보유 목록", value="all", default=(self.filter_mode == "all")),
            discord.SelectOption(label="🧍 캐릭터만 보기", value="char", default=(self.filter_mode == "char")),
            discord.SelectOption(label="⚔️ 무기만 보기", value="weapon", default=(self.filter_mode == "weapon")),
            discord.SelectOption(label="🏺 성유물만 보기", value="artifact", default=(self.filter_mode == "artifact")),
            discord.SelectOption(label="🌟 5성만 보기", value="r5", default=(self.filter_mode == "r5")),
            discord.SelectOption(label="💜 4성만 보기", value="r4", default=(self.filter_mode == "r4")),
            discord.SelectOption(label="🔒 잠금 항목만", value="locked", default=(self.filter_mode == "locked")),
        ]
        sel_f = discord.ui.Select(placeholder="🔍 보관함 필터 선택...", options=f_opts, row=0)
        sel_f.callback = self._on_filter
        self.add_item(sel_f)

        if slice_items:
            d_opts = []
            for it in slice_items:
                if it["kind"] == "char":
                    tag = f"C{it.get('constellation', 0)}"
                elif it["kind"] == "artifact":
                    tag = f"+{it.get('level', 4)}"
                else:
                    tag = f"R{it.get('refinement', 1)}"
                lock_icon = "🔒 " if it.get("locked") else ""
                d_opts.append(discord.SelectOption(
                    label=f"{lock_icon}{it['rarity_label']} {it['name']} ({tag})"[:95],
                    value=it["item_key"],
                    description=f"Lv.{it.get('level', 1)} · 보유 {it.get('count', 1)}회 · 클릭해 스플래시/잠금/레벨업"[:95],
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
        v = GenshinItemDetailView(self.guild_id, interaction.user, ikey)
        emb, f = await v.build_embed_and_file()
        if f:
            await interaction.followup.send(embed=emb, file=f, view=v, ephemeral=True)
        else:
            await interaction.followup.send(embed=emb, view=v, ephemeral=True)

    def build_embed(self) -> discord.Embed:
        u_data, items = self._get_filtered_items()
        max_page = max(1, (len(items) + self._per_page - 1) // self._per_page)
        slice_items = items[self.page * self._per_page:(self.page + 1) * self._per_page]
        lines = []
        for idx, it in enumerate(slice_items, start=self.page * self._per_page + 1):
            lk = "🔒" if it.get("locked") else "🔓"
            if it["kind"] == "char":
                lines.append(
                    f"**{idx:02d}.** {lk} **{it['rarity_label']} {it['name']}** `C{it.get('constellation', 0)}` · `Lv.{it.get('level', 1)}`\n"
                    f"└ {it.get('element_emoji', '')}{it.get('element_name', '')} · {it.get('weapon_type_emoji', '')}{it.get('weapon_type_name', '')} · 누적 `{it.get('count', 1)}회`"
                )
            elif it["kind"] == "artifact":
                lines.append(
                    f"**{idx:02d}.** {lk} **{it['rarity_label']} {it['name']}** `+{it.get('level', 4)}` · 누적 `{it.get('count', 1)}회`\n"
                    f"└ {it.get('slot_name', '🏺성유물')} · 주옵: `{it.get('main_stat', '-')}` · {it.get('bonus_2p', '')[:36]}"
                )
            else:
                lines.append(
                    f"**{idx:02d}.** {lk} **{it['rarity_label']} {it['name']}** `R{it.get('refinement', 1)}` · 누적 `{it.get('count', 1)}회`\n"
                    f"└ {it.get('weapon_type_emoji', '')}{it.get('weapon_type_name', '')} · {it.get('special_prop_name', '-')}"
                )
        body = "\n".join(lines) if lines else "*(해당 조건에 보유한 캐릭터·무기·성유물이 없습니다)*"
        owner_name = self.user.display_name if self.user else "여행자"
        return discord.Embed(
            title=f"🎒 {owner_name}님의 원신 보관함 ({len(items)}종)",
            description=(
                f"✨ 스타라이트 `{u_data.get('starglitter', 0):,}` · 💠 스타더스트 `{u_data.get('stardust', 0):,}` · 📘 영웅의 경험 `{u_data.get('hero_wit', 0):,}권`\n"
                f"• 캐릭터 `{u_data.get('pity_char', 0)}/90` · 무기 `{u_data.get('pity_weapon', 0)}/80` · 성유물 `{u_data.get('pity_artifact', 0)}/50` · 상시 `{u_data.get('pity_standard', 0)}/90`\n\n"
                f"{body}"
            )[:4050],
            color=discord.Color.from_rgb(40, 74, 150),
            timestamp=datetime.datetime.now(core.KST),
        ).set_footer(text=f"페이지 {self.page + 1}/{max_page} • 아래에서 항목을 고르면 스플래시 아트/잠금/레벨업 가능")


class GenshinItemDetailView(core.SafeView):
    def __init__(self, guild_id: int = 0, user: discord.User | None = None, item_key: str = ""):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.user = user
        self.item_key = item_key
        self._build()

    def _build(self):
        self.clear_items()
        data = core.load_data()
        u_data = genshin_core.ensure_genshin_user(data, self.guild_id, self.user.id if self.user else 0)
        it = u_data.get("items", {}).get(self.item_key)
        locked = bool(it.get("locked")) if it else False

        b_lock = discord.ui.Button(
            label="🔓 잠금 해제" if locked else "🔒 잠금 설정",
            style=discord.ButtonStyle.secondary if locked else discord.ButtonStyle.primary,
            row=0,
        )
        b_lock.callback = self._on_lock
        self.add_item(b_lock)

        if it and it.get("kind") == "char":
            b_lv = discord.ui.Button(
                label=f"⬆️ 레벨업 (+10Lv · 영웅의경험 2권)" if int(it.get("level", 1)) < 90 else "✅ Lv.90 MAX",
                style=discord.ButtonStyle.success,
                disabled=(int(it.get("level", 1)) >= 90),
                row=0,
            )
            b_lv.callback = self._on_lvup
            self.add_item(b_lv)

    async def build_embed_and_file(self) -> tuple[discord.Embed, discord.File | None]:
        genshin_core.load_genshin_kr_db()
        data = core.load_data()
        u_data = genshin_core.ensure_genshin_user(data, self.guild_id, self.user.id if self.user else 0)
        owned = u_data.get("items", {}).get(self.item_key)
        master = genshin_core.GENSHIN_ALL_ITEMS.get(self.item_key) or owned or {"id": "", "kind": "char", "name": "정보 없음", "rank": 4, "rarity_label": "★★★★"}
        it = {**master, **(owned or {})}
        det = await asyncio.to_thread(genshin_core.fetch_genshin_detail_kr, it["id"], it["kind"])
        img_bytes, fn = await asyncio.to_thread(genshin_core.fetch_genshin_item_image_bytes, it, True)

        lines = []
        if it["kind"] == "char":
            lines.append(f"• **원소/무기:** {it.get('element_emoji', '')}{it.get('element_name', '')} · {it.get('weapon_type_emoji', '')}{it.get('weapon_type_name', '')} (`{it.get('region_name', '티바트')}`)")
            lines.append(f"• **성장/돌파:** `Lv.{it.get('level', 1)}/90` · **운명의 자리 `C{it.get('constellation', 0)}/6`** · 전투력 `{genshin_core.compute_genshin_char_power(it):,}`")
            if det.get("title"):
                lines.append(f"• **이명/운명의 자리명:** `{det['title']}` · `{det.get('constellation', '-')}`")
            if det.get("cv_kr"):
                lines.append(f"• **한국어 성우:** `{det['cv_kr']}`")
            if det.get("detail"):
                lines.append(f"\n> {det['detail'][:300]}")
        elif it["kind"] == "artifact":
            lines.append(f"• **성유물 부위/강화:** {it.get('slot_name', '🏺성유물')} · **`+{it.get('level', 4)}/20`** · 누적 `{it.get('count', 1)}회`")
            lines.append(f"• **주옵션:** `{it.get('main_stat', '-')}` · **부옵션:** `{', '.join(it.get('sub_stats') or ['-'])}`")
            if it.get("bonus_2p"):
                lines.append(f"• **2세트 효과:** {it['bonus_2p']}")
            if it.get("bonus_4p"):
                lines.append(f"• **4세트 효과:** {it['bonus_4p'][:250]}")
        else:
            lines.append(f"• **무기군/부옵션:** {it.get('weapon_type_emoji', '')}{it.get('weapon_type_name', '')} · `{it.get('special_prop_name', '-')}`")
            lines.append(f"• **재련 단계:** **`R{it.get('refinement', 1)}/5`** · 누적 `{it.get('count', 1)}회`")
            if det.get("description"):
                lines.append(f"\n> {det['description'][:300]}")

        emb = discord.Embed(
            title=f"{'🔒 ' if it.get('locked') else ''}{it.get('rarity_label', '')} {it.get('name', '')}",
            description="\n".join(lines),
            color=discord.Color.from_rgb(255, 204, 82) if it.get("rank") == 5 else discord.Color.from_rgb(174, 118, 255),
        )
        file_obj = None
        if img_bytes:
            file_obj = discord.File(io.BytesIO(img_bytes), filename=fn)
            emb.set_image(url=f"attachment://{fn}")
        else:
            emb.set_image(url=genshin_core.get_genshin_primary_image_url(it, True))
        return emb, file_obj

    async def _on_lock(self, interaction: discord.Interaction):
        if self.user and interaction.user.id != self.user.id:
            return await core.safe_send_response(interaction, "❌ 본인 아이템만 잠금할 수 있습니다.", ephemeral=True)
        self.user = self.user or interaction.user
        gid = self.guild_id or (interaction.guild_id or 0)
        self.guild_id = gid
        await asyncio.to_thread(genshin_core.toggle_genshin_item_lock, gid, interaction.user.id, self.item_key)
        self._build()
        emb, _ = await self.build_embed_and_file()
        await core.safe_edit_response(interaction, embed=emb, view=self)

    async def _on_lvup(self, interaction: discord.Interaction):
        if self.user and interaction.user.id != self.user.id:
            return await core.safe_send_response(interaction, "❌ 본인 캐릭터만 레벨업할 수 있습니다.", ephemeral=True)
        self.user = self.user or interaction.user
        gid = self.guild_id or (interaction.guild_id or 0)
        self.guild_id = gid
        ok, msg, _ = await asyncio.to_thread(genshin_core.levelup_genshin_char, gid, interaction.user.id, self.item_key)
        if not ok:
            return await core.safe_send_response(interaction, msg, ephemeral=True)
        self._build()
        emb, _ = await self.build_embed_and_file()
        await core.safe_edit_response(interaction, content=msg, embed=emb, view=self)


class GenshinPokedexView(core.SafeView):
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
        stats = genshin_core.get_genshin_pokedex_stats(self.guild_id, uid)
        raw = stats["owned_items"] if self.tab == "owned" else (stats["unowned_items"] if self.tab == "unowned" else (stats["owned_items"] + stats["unowned_items"]))
        if self.kind_filter == "char":
            raw = [it for it in raw if it["kind"] == "char"]
        elif self.kind_filter == "weapon":
            raw = [it for it in raw if it["kind"] == "weapon"]
        elif self.kind_filter == "artifact":
            raw = [it for it in raw if it["kind"] == "artifact"]
        kind_ord = {"char": 0, "weapon": 1, "artifact": 2}
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

        for lbl, kf in [("전체종류", "all"), ("캐릭터만", "char"), ("무기만", "weapon"), ("성유물만", "artifact")]:
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
                c_txt = f" `C{it['constellation']}`" if "constellation" in it else ""
                lines.append(f"• {it['rarity_label']} **{it['name']}**{c_txt} ({it.get('element_emoji', '')}{it.get('element_name', '')} · `{it.get('pool_type', '')}`)")
            elif it["kind"] == "artifact":
                l_txt = f" `+{it['level']}`" if "level" in it else ""
                lines.append(f"• 🏺 **{it['name']}**{l_txt} ({it.get('bonus_2p', '비경 성유물')[:38]})")
            else:
                r_txt = f" `R{it['refinement']}`" if "refinement" in it else ""
                lines.append(f"• {it['rarity_label']} **{it['name']}**{r_txt} ({it.get('weapon_type_emoji', '')}{it.get('weapon_type_name', '')} · `{it.get('pool_type', '')}`)")
        list_body = "\n".join(lines) if lines else "*(표시할 항목이 없습니다)*"
        owner_n = self.user.display_name if self.user else "여행자"
        a5_own, a5_tot = stats.get("a5", (0, 0))
        return discord.Embed(
            title=f"📖 {owner_n}님의 원신 티바트 도감",
            description=(
                f"• **기원 도감 수집률:** `{stats['wishable_owned']}/{stats['wishable_total']}` (**`{stats['rate']:.1f}%`**)\n"
                f"  {stats['bar']}\n"
                f"• **캐릭터:** ★5 `{stats['c5'][0]}/{stats['c5'][1]}` · ★4 `{stats['c4'][0]}/{stats['c4'][1]}`\n"
                f"• **무기 & 성유물:** 무기 ★5 `{stats['w5'][0]}/{stats['w5'][1]}` · ★4 `{stats['w4'][0]}/{stats['w4'][1]}` · 성유물 세트 `{a5_own}/{a5_tot}`\n\n"
                f"{list_body}"
            )[:4050],
            color=discord.Color.from_rgb(244, 198, 92),
        ).set_footer(text=f"페이지 {self.page + 1}/{max_page} • 전체 DB {stats['total_all']}종 실시간 동기화")


class GenshinShopView(core.SafeView):
    def __init__(self, guild_id: int = 0, user: discord.User | None = None):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.user = user
        self._build()

    def _build(self):
        self.clear_items()
        cat = genshin_core.get_genshin_shop_catalog()
        opts = []
        for c in cat["chars"]:
            opts.append(discord.SelectOption(
                label=f"✨ [34 스타라이트] ★★★★ {c['name']}",
                value=f"buy_char:{c['id']}",
                description=f"{c['element_name']} · {c['weapon_type_name']} (월 1회 영입/운명의자리 +1)",
            ))
        for w in cat["weapons"]:
            opts.append(discord.SelectOption(
                label=f"⚔️ [24 스타라이트] ★★★★ {w['name']}",
                value=f"buy_wp:{w['id']}",
                description=f"{w['weapon_type_name']} · {w['special_prop_name']} (재련용 중복 구매 가능)",
            ))
        opts.extend([
            discord.SelectOption(label="🌠 [5 스타라이트] 뒤얽힌 인연 ×1", value="glitter_intertwined", description="한도 없음"),
            discord.SelectOption(label="🌌 [5 스타라이트] 만남의 인연 ×1", value="glitter_acquaint", description="한도 없음"),
            discord.SelectOption(label="🌠 [75 스타더스트] 뒤얽힌 인연 ×1", value="dust_intertwined", description="월 5회 제한"),
            discord.SelectOption(label="🌌 [75 스타더스트] 만남의 인연 ×1", value="dust_acquaint", description="월 5회 제한"),
            discord.SelectOption(label="📘 [40 스타더스트] 영웅의 경험 ×5", value="dust_hero_wit", description="보유 캐릭터 Lv.1~90 육성 재료"),
        ])
        sel = discord.ui.Select(placeholder="🛒 페이몬의 상점에서 교환할 상품 선택...", options=opts[:25], row=0)
        sel.callback = self._on_buy
        self.add_item(sel)

    async def _on_buy(self, interaction: discord.Interaction):
        if self.user and interaction.user.id != self.user.id:
            return await core.safe_send_response(interaction, "❌ 본인의 페이몬 상점 화면만 사용할 수 있습니다.", ephemeral=True)
        self.user = self.user or interaction.user
        gid = self.guild_id or (interaction.guild_id or 0)
        self.guild_id = gid
        offer = interaction.data["values"][0]
        ok, msg, _ = await asyncio.to_thread(genshin_core.purchase_genshin_shop_item, gid, interaction.user.id, offer)
        self._build()
        if ok:
            await core.safe_edit_response(interaction, content=msg, embed=self.build_embed(), view=self)
        else:
            await core.safe_send_response(interaction, f"⚠️ {msg}", ephemeral=True)

    def build_embed(self) -> discord.Embed:
        cat = genshin_core.get_genshin_shop_catalog()
        data = core.load_data()
        u_data = genshin_core.ensure_genshin_user(data, self.guild_id, self.user.id if self.user else 0)
        monthly = u_data.get("shop_monthly", {})
        if monthly.get("month_key") != cat["month_key"]:
            di = da = 0
        else:
            di = int(monthly.get("dust_intertwined", 0))
            da = int(monthly.get("dust_acquaint", 0))

        chars_str = ", ".join(f"**{c['name']}**({c['element_emoji']})" for c in cat["chars"]) or "로테이션 로딩 중"
        wps_str = ", ".join(w["name"] for w in cat["weapons"]) or "-"
        return discord.Embed(
            title=f"🧚 페이몬의 상점 ({cat['month']}월 로테이션)",
            description=(
                f"• **내 보유 재화:** ✨ 스타라이트 **`{u_data.get('starglitter', 0):,}`** · 💠 스타더스트 **`{u_data.get('stardust', 0):,}`**\n"
                f"• **인연 티켓:** 🌠 뒤얽힌 `{u_data.get('intertwined_fate', 0):,}` · 🌌 만남 `{u_data.get('acquaint_fate', 0):,}` · 📘 영웅의 경험 `{u_data.get('hero_wit', 0):,}권`\n\n"
                f"### ✨ 스타라이트 교환\n"
                f"• **이달의 4성 캐릭터 (34개 / 월1회):** {chars_str}\n"
                f"• **이달의 4성 무기 — {cat['weapon_series_name']} (24개):** {wps_str}\n"
                f"• **뒤얽힌/만남의 인연 (5개):** 무제한 교환\n\n"
                f"### 💠 스타더스트 교환\n"
                f"• **뒤얽힌 인연 (75개):** 이달 `{di}/5회`\n"
                f"• **만남의 인연 (75개):** 이달 `{da}/5회`\n"
                f"• **영웅의 경험 ×5권 (40개):** 캐릭터 레벨업(Lv.1~90)용"
            ),
            color=discord.Color.from_rgb(245, 198, 92),
        )


class GenshinPartyView(core.SafeView):
    def __init__(self, guild_id: int = 0, user: discord.User | None = None):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.user = user
        self._build()

    def _build(self):
        self.clear_items()
        data = core.load_data()
        u_data = genshin_core.ensure_genshin_user(data, self.guild_id, self.user.id if self.user else 0)
        owned_chars = [v for v in u_data.get("items", {}).values() if isinstance(v, dict) and v.get("kind") == "char"]
        owned_chars.sort(key=lambda c: (-int(c.get("rank", 4)), -int(c.get("level", 1)), -int(c.get("constellation", 0)), c.get("name", "")))

        if owned_chars:
            opts = [
                discord.SelectOption(
                    label=f"{c['rarity_label']} {c['name']} (C{c.get('constellation', 0)} · Lv.{c.get('level', 1)})"[:95],
                    value=c["item_key"],
                    description=f"{c.get('element_emoji', '')}{c.get('element_name', '')} · 전투력 {genshin_core.compute_genshin_char_power(c):,}"[:95],
                )
                for c in owned_chars[:25]
            ]
            sel = discord.ui.Select(
                placeholder="⚔️ 파티에 배치할 캐릭터 최대 4명 선택...",
                options=opts,
                min_values=1,
                max_values=min(4, len(opts)),
                row=0,
            )
            sel.callback = self._on_pick_party
            self.add_item(sel)

        b_auto = discord.ui.Button(label="✨ 최강 전투력 자동 편성", style=discord.ButtonStyle.primary, row=1)
        b_auto.callback = self._on_auto
        self.add_item(b_auto)

        b_clr = discord.ui.Button(label="🧹 파티 비우기", style=discord.ButtonStyle.danger, row=1)
        b_clr.callback = self._on_clear
        self.add_item(b_clr)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인 파티만 편성할 수 있습니다.", ephemeral=True)
            return False
        if self.user is None:
            self.user = interaction.user
            self.guild_id = interaction.guild_id or self.guild_id
        return True

    async def _on_pick_party(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return
        picked = list(interaction.data["values"])[:4]
        data = core.load_data()
        u_data = genshin_core.ensure_genshin_user(data, self.guild_id, interaction.user.id)
        u_data["party"] = picked
        core.save_data(data)
        self._build()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_auto(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return
        data = core.load_data()
        u_data = genshin_core.ensure_genshin_user(data, self.guild_id, interaction.user.id)
        chars = [v for v in u_data.get("items", {}).values() if isinstance(v, dict) and v.get("kind") == "char"]
        chars.sort(key=lambda c: -genshin_core.compute_genshin_char_power(c))
        u_data["party"] = [c["item_key"] for c in chars[:4]]
        core.save_data(data)
        self._build()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_clear(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return
        data = core.load_data()
        u_data = genshin_core.ensure_genshin_user(data, self.guild_id, interaction.user.id)
        u_data["party"] = []
        core.save_data(data)
        self._build()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    def build_embed(self) -> discord.Embed:
        data = core.load_data()
        u_data = genshin_core.ensure_genshin_user(data, self.guild_id, self.user.id if self.user else 0)
        items = u_data.get("items", {})
        party_keys = [k for k in (u_data.get("party") or []) if k in items][:4]
        party_objs = [items[k] for k in party_keys]
        analysis = genshin_core.analyze_genshin_party(party_objs)

        slot_lines = []
        for idx in range(4):
            if idx < len(party_objs):
                c = party_objs[idx]
                pwr = genshin_core.compute_genshin_char_power(c)
                slot_lines.append(
                    f"**슬롯 {idx + 1}:** {c['rarity_label']} **{c['name']}** ({c.get('element_emoji', '')}{c.get('element_name', '')} · `C{c.get('constellation', 0)}` · `Lv.{c.get('level', 1)}` · `{pwr:,}`)"
                )
            else:
                slot_lines.append(f"**슬롯 {idx + 1}:** *(비어 있음)*")

        res_lines = [f"• {r['emoji']} **{r['name']}**: {r['desc']}" for r in analysis["resonances"]]
        res_txt = "\n".join(res_lines) if res_lines else "*(동일 원소 2명 이상 또는 서로 다른 4원소 배치 시 원소 공명 발동!)*"
        owner_n = self.user.display_name if self.user else "여행자"
        return discord.Embed(
            title=f"⚔️ {owner_n}님의 원신 4인 파티 & 원소 공명",
            description=(
                f"### 🛡️ 현재 파티 멤버 ({len(party_objs)}/4)\n"
                + "\n".join(slot_lines)
                + f"\n\n### ✨ 원소 공명 ({len(analysis['resonances'])}개 발동 · 시너지 `+{analysis['bonus_pct']}%`)\n"
                + res_txt
                + f"\n\n🔥 **총 파티 전투력:** **`{analysis['total_power']:,}`**"
            ),
            color=discord.Color.from_rgb(56, 174, 248),
        ).set_footer(text="/원신 파티편성 또는 하단 드롭다운으로 최대 4명까지 편성할 수 있습니다.")


class GenshinRankingView(core.SafeView):
    def __init__(self, guild_id: int = 0, mode: str = "ranking"):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.mode = mode
        self._build()

    def _build(self):
        self.clear_items()
        for lbl, m in [("🏆 서버 컬렉션 랭킹", "ranking"), ("🌟 10연 명예의 전당", "hof"), ("⚡ 최근 ★5 속보", "recent")]:
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
        g_users = data.get("genshin_users", {}).get(g_key, {})

        if self.mode == "hof":
            hof = genshin_core.get_genshin_hall_of_fame(data, self.guild_id)
            recs = hof["top_records"]
            lines = []
            for idx, r in enumerate(recs[:10], start=1):
                uid_i = int(r["uid"])
                mem = guild.get_member(uid_i) if guild else None
                uname = mem.display_name if mem else f"여행자({uid_i})"
                lines.append(f"**#{idx}** **{uname}** — ★5 **`{r['r5_count']}회`** (픽업 {r['pickup_count']} · 최소 {r['min_pity']}스택)\n└ {' / '.join(r['items'][:4])}")
            desc = "\n".join(lines) if lines else "*(아직 10연 기원에서 ★5 명예의 전당 기록이 없습니다)*"
            return discord.Embed(title="🌟 원신 10연 기원 명예의 전당", description=desc, color=discord.Color.gold())

        if self.mode == "recent":
            hof = genshin_core.get_genshin_hall_of_fame(data, self.guild_id)
            logs = hof["recent_5_logs"]
            lines = []
            for r in logs[:15]:
                uid_i = int(r["uid"])
                mem = guild.get_member(uid_i) if guild else None
                uname = mem.display_name if mem else f"여행자({uid_i})"
                rad = "🌈광휘 " if r.get("is_radiance") else ("🎯픽업 " if r.get("is_pickup") else "")
                lines.append(f"• **{uname}**: {rad}**★★★★★ {r['name']}** (`{r.get('pity', '?')}스택` · {r.get('banner', '')})")
            desc = "\n".join(lines) if lines else "*(최근 ★5 출현 로그가 없습니다)*"
            return discord.Embed(title="⚡ 원신 서버 ★5 최근 획득 속보", description=desc, color=discord.Color.from_rgb(255, 198, 84))

        rows = []
        for uid_s, u_data in g_users.items():
            if not isinstance(u_data, dict):
                continue
            items = u_data.get("items", {})
            if not items and not u_data.get("total_pulls"):
                continue
            r5_cnt = sum(1 for v in items.values() if v.get("rank") == 5)
            c6_cnt = sum(1 for v in items.values() if v.get("kind") == "char" and int(v.get("constellation", 0)) >= 6)
            uniq_cnt = len(items)
            pulls = int(u_data.get("total_pulls", 0))
            rows.append((r5_cnt, c6_cnt, uniq_cnt, pulls, uid_s))
        rows.sort(key=lambda x: (-x[0], -x[1], -x[2], -x[3]))
        lines = []
        for idx, (r5, c6, uq, pl, uid_s) in enumerate(rows[:15], start=1):
            mem = guild.get_member(int(uid_s)) if guild else None
            uname = mem.display_name if mem else f"여행자({uid_s})"
            medal = ["🥇", "🥈", "🥉"][idx - 1] if idx <= 3 else f"**#{idx}**"
            lines.append(f"{medal} **{uname}** — ★5 `{r5}종` (완전돌파 `{c6}`) · 도감 `{uq}종` · 기원 `{pl:,}회`")
        desc = "\n".join(lines) if lines else "*(아직 이 서버에 원신 기원 기록이 있는 유저가 없습니다)*"
        return discord.Embed(title="🏆 원신 서버 컬렉션 랭킹 TOP 15", description=desc, color=discord.Color.from_rgb(68, 152, 255))


class GenshinRateView(core.SafeView):
    def __init__(self, banner_key: str = "char1"):
        super().__init__(timeout=180)
        self.banner_key = banner_key
        self._build()

    def _build(self):
        self.clear_items()
        for k, cfg in genshin_core.GENSHIN_BANNER_CONFIGS.items():
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
        eff = genshin_core.resolve_effective_genshin_pickup(data.get("genshin_pickup"))
        cfg = genshin_core.GENSHIN_BANNER_CONFIGS.get(self.banner_key, genshin_core.GENSHIN_BANNER_CONFIGS["char1"])
        c4_txt = ", ".join(c["name"] for c in eff["char_4"]) or "-"
        w4_txt = ", ".join(w["name"] for w in eff["weapon_4"]) or "-"
        rot_win = eff.get("time_window") or "실시간"

        if self.banner_key in ("char1", "char2"):
            feat = eff["char1"] if self.banner_key == "char1" else eff["char2"]
            body = (
                f"• **시각별 로테이션:** `⏰ {rot_win}` ({eff.get('banner_name', '')})\n"
                f"• **픽업 ★★★★★ 캐릭터:** **`{feat['name'] if feat else '-'}`** ({feat['element_emoji'] if feat else ''}{feat['element_name'] if feat else '-'} · {feat['weapon_type_name'] if feat else '-'})\n"
                f"• **픽업 ★★★★ 캐릭터 (50% 확률업):** `{c4_txt}`\n"
                f"• **기본 5성 확률:** `0.6%` (`74스택`부터 매회 +6% 소프트 천장 · `90스택` 확정)\n"
                f"• **픽뚫 보정:** 50/50 실패 시 다음 ★5 확정! **포착된 광휘** 시스템 자동 적용 (연속 픽뚫 방지)\n"
                f"• **공유 규칙:** 캐릭터 이벤트 기원 ①과 ②는 5성 천장·확정·광휘 스택을 공유합니다."
            )
        elif self.banner_key == "weapon":
            w1, w2 = eff.get("weapon_1"), eff.get("weapon_2")
            body = (
                f"• **시각별 전용 무기 연동:** `⏰ {rot_win}`\n"
                f"• **픽업 ★★★★★ 무기 ①:** **`{w1['name'] if w1 else '-'}`** ({w1['weapon_type_name'] if w1 else '-'})\n"
                f"• **픽업 ★★★★★ 무기 ②:** **`{w2['name'] if w2 else '-'}`** ({w2['weapon_type_name'] if w2 else '-'})\n"
                f"• **픽업 ★★★★ 무기 (75% 확률업):** `{w4_txt}`\n"
                f"• **기본 5성 확률:** `0.7%` (`63스택`부터 매회 +7% 소프트 천장 · `80스택` 확정)\n"
                f"• **운명의 궤도 (`0/1 ➔ 1/1`):** 원하는 무기 미획득 시 명정 포인트 1 적립, 다음 ★5는 **100% 목표 무기 확정!** (`/원신 운명의궤도`)"
            )
        elif self.banner_key == "artifact":
            a1, a2 = eff.get("artifact_1"), eff.get("artifact_2")
            body = (
                f"• **시각별 비경 로테이션:** `⏰ {rot_win}`\n"
                f"• **픽업 ★★★★★ 성유물 세트 ①:** **`{a1['name'] if a1 else '-'}`** ({a1.get('bonus_2p', '-') if a1 else '-'})\n"
                f"• **픽업 ★★★★★ 성유물 세트 ②:** **`{a2['name'] if a2 else '-'}`** ({a2.get('bonus_2p', '-') if a2 else '-'})\n"
                f"• **드랍 및 감정 규칙:** 5부위(🌸생명의 꽃 · 🪶죽음의 깃털 · ⏳시간의 모래 · 🏆공간의 성배 · 👑이성의 왕관) 및 주옵션·부옵션 4줄 실시간 감정!\n"
                f"• **기본 5성 확률:** `2.5%` (`35스택` 소프트 · `50스택` 확정 · 픽업 세트 80% 우대)"
            )
        else:
            body = (
                "• **상시 ★★★★★ 캐릭터(8인):** 진, 다이루크, 치치, 모나, 각청, 타이나리, 데히야, 유메미즈키 미즈키\n"
                "• **상시 ★★★★★ 무기(10종):** 매의 검, 천공의 검/긍지/마루/두루마리/날개, 늑대의 말로, 화박연, 사풍 원서, 아모스의 활\n"
                "• **상시 전용 4성 포함:** 엠버 · 케이아 · 리사 획득 가능\n"
                "• **확률:** `0.6%` (`74스택` 소프트 · `90스택` 확정 · 캐릭터/무기 50:50)"
            )
        return discord.Embed(
            title=f"📊 {cfg['name']} — 상세 확률표",
            description=body,
            color=discord.Color.from_rgb(*cfg["color"]),
        )


class GenshinGuildResetConfirmView(core.SafeView):
    def __init__(self, guild_id: int = 0, caller: discord.User | None = None):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.caller = caller

    @discord.ui.button(label="⚠️ 예, 이 서버 원신 데이터 초기화", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.caller and interaction.user.id != self.caller.id:
            return await core.safe_send_response(interaction, "❌ 요청한 관리자만 확정할 수 있습니다.", ephemeral=True)
        data = core.load_data()
        g_key = str(self.guild_id or interaction.guild_id or 0)
        data.get("genshin_users", {}).pop(g_key, None)
        data.get("genshin_hall_of_fame", {}).pop(g_key, None)
        core.save_data(data)
        await core.safe_edit_response(interaction, content="🧹 이 서버의 모든 원신 기원 데이터가 깔끔하게 초기화되었습니다.", embed=None, view=None)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_edit_response(interaction, content="취소되었습니다.", embed=None, view=None)


# ==========================================
# /원신 GroupCog (11 Subcommands + Prefix Shortcuts)
# ==========================================
class GenshinCog(commands.GroupCog, group_name="원신", group_description="🌠 원신 (Genshin Impact) 기원 · 성유물 감정 · 도감 · 페이몬 상점 · 파티 공명"):
    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    @app_commands.command(name="기원", description="🌠 원신 기원 (캐릭터·무기·성유물·상시 · 시각별 로테이션 · 3.5초 연출)")
    @app_commands.describe(
        배너="기원을 진행할 배너 종류를 선택하세요 (캐릭터/무기/성유물/상시)",
        횟수="10회 또는 1회 기원",
        연습모드="True 선택 시 쿨타임 없이 가상 뽑기만 테스트합니다 (보관함/천장 미저장)",
        연출스킵="True 선택 시 3.5초 연출을 건너뛰고 바로 결과판을 출력합니다 (쿨타임 5.0초)",
    )
    @app_commands.choices(
        배너=[
            app_commands.Choice(name="🌠 캐릭터 이벤트 기원 ①", value="char1"),
            app_commands.Choice(name="🌙 캐릭터 이벤트 기원 ②", value="char2"),
            app_commands.Choice(name="⚔️ 신의 주조 (무기 기원)", value="weapon"),
            app_commands.Choice(name="🏺 비경 성유물 축복 (성유물 감정)", value="artifact"),
            app_commands.Choice(name="🌌 세상 여행 (상시 기원)", value="standard"),
        ],
        횟수=[
            app_commands.Choice(name="10회 기원", value=10),
            app_commands.Choice(name="1회 기원", value=1),
        ],
    )
    async def wish_cmd(
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
                    f"⏳ 가챠 쿨타임 중입니다! **`{rem:.1f}초`** 후 다시 기원해 주세요. ({'스킵 5.0초' if 연출스킵 else '기본 3.5초'})",
                    ephemeral=True,
                )
        await core.safe_defer(interaction)
        res = await asyncio.to_thread(genshin_core.execute_genshin_pull, interaction.guild_id or 0, interaction.user.id, 배너, 횟수, 연습모드)
        v = GenshinPullAgainView(interaction.user, banner_key=배너, skip_anim=연출스킵, practice=연습모드, last_count=횟수)
        await send_genshin_pull_result(interaction, res, view=v, skip_anim=연출스킵)

    @app_commands.command(name="운명의궤도", description="🧭 신의 주조(무기 이벤트 기원) 운명의 궤도 목표 무기를 선택/해제합니다")
    async def fate_path_cmd(self, interaction: discord.Interaction):
        v = GenshinFatePathView(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v, ephemeral=True)

    @app_commands.command(name="확률", description="📊 현재 원신 시각별 픽업 정보와 캐릭터·무기·성유물 천장 확률표를 확인합니다")
    @app_commands.choices(배너=[
        app_commands.Choice(name="🌠 캐릭터 기원 ①", value="char1"),
        app_commands.Choice(name="🌙 캐릭터 기원 ②", value="char2"),
        app_commands.Choice(name="⚔️ 신의 주조 (무기)", value="weapon"),
        app_commands.Choice(name="🏺 비경 성유물 축복", value="artifact"),
        app_commands.Choice(name="🌌 세상 여행 (상시)", value="standard"),
    ])
    async def rate_cmd(self, interaction: discord.Interaction, 배너: str = "char1"):
        v = GenshinRateView(배너)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v)

    @app_commands.command(name="보관함", description="🎒 보유 중인 원신 캐릭터(운명의 자리) · 무기(재련) · 성유물(+20) · 잠금 관리")
    @app_commands.choices(필터=[
        app_commands.Choice(name="전체", value="all"),
        app_commands.Choice(name="캐릭터만", value="char"),
        app_commands.Choice(name="무기만", value="weapon"),
        app_commands.Choice(name="성유물만", value="artifact"),
        app_commands.Choice(name="★5만", value="r5"),
        app_commands.Choice(name="★4만", value="r4"),
        app_commands.Choice(name="잠금🔒만", value="locked"),
    ])
    async def inventory_cmd(self, interaction: discord.Interaction, 필터: str = "all"):
        v = GenshinInventoryView(interaction.guild_id or 0, interaction.user, filter_mode=필터)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v)

    @app_commands.command(name="도감", description="📖 원신 전체 캐릭터·무기·성유물 실시간 DB 도감과 수집 달성률을 확인합니다")
    @app_commands.choices(탭=[
        app_commands.Choice(name="보유 목록", value="owned"),
        app_commands.Choice(name="미보유", value="unowned"),
        app_commands.Choice(name="전체 도감", value="all"),
    ])
    async def pokedex_cmd(self, interaction: discord.Interaction, 탭: str = "owned"):
        v = GenshinPokedexView(interaction.guild_id or 0, interaction.user, tab=탭)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v)

    @app_commands.command(name="상점", description="🧚 페이몬의 상점 (스타라이트 월간 4성 캐릭터·흑암/왕실 무기 & 인연 · 영웅의 경험)")
    async def shop_cmd(self, interaction: discord.Interaction):
        v = GenshinShopView(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v)

    @app_commands.command(name="파티편성", description="⚔️ 보유 원신 캐릭터 4명으로 파티를 편성하고 원소 공명 & 전투력을 계산합니다")
    @app_commands.autocomplete(
        슬롯1=genshin_core.genshin_owned_char_autocomplete,
        슬롯2=genshin_core.genshin_owned_char_autocomplete,
        슬롯3=genshin_core.genshin_owned_char_autocomplete,
        슬롯4=genshin_core.genshin_owned_char_autocomplete,
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
            u_data = genshin_core.ensure_genshin_user(data, interaction.guild_id or 0, interaction.user.id)
            u_items = u_data.get("items", {})
            valid = [k for k in dedup if k in u_items and u_items[k].get("kind") == "char"][:4]
            u_data["party"] = valid
            core.save_data(data)
        v = GenshinPartyView(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(interaction, embed=v.build_embed(), view=v)

    @app_commands.command(name="프로필", description="🪪 나 또는 다른 여행자의 원신 쇼케이스 카드(천장 · 대표캐릭터 · 파티)를 봅니다")
    @app_commands.autocomplete(대표캐릭터=genshin_core.genshin_owned_char_autocomplete)
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
        u_data = genshin_core.ensure_genshin_user(data, interaction.guild_id or 0, target.id)
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
        chars.sort(key=lambda c: (-int(c.get("rank", 4)), -int(c.get("constellation", 0)), -int(c.get("level", 1))))
        p_key = u_data.get("profile_char")
        rep_char = items.get(p_key) if p_key and p_key in items and items[p_key].get("kind") == "char" else (chars[0] if chars else None)

        party_objs = [items[k] for k in (u_data.get("party") or []) if k in items][:4]
        party_ana = genshin_core.analyze_genshin_party(party_objs)
        top3 = ", ".join(f"{c['name']}(C{c.get('constellation', 0)})" for c in chars[:3]) or "없음"
        note_str = u_data.get("profile_note") or "티바트 모험 중!"
        rep_str = (
            f"{rep_char['rarity_label']} **{rep_char['name']}** (`C{rep_char.get('constellation', 0)}` · `Lv.{rep_char.get('level', 1)}`)"
            if rep_char else "미설정"
        )

        emb = discord.Embed(
            title=f"🪪 {target.display_name}님의 원신 여행자 프로필",
            description=(
                f"💬 *\"{note_str}\"*\n\n"
                f"• **대표 캐릭터:** {rep_str}\n"
                f"• **기원 통계:** 누적 `{u_data.get('total_pulls', 0):,}회` · 고유 수집 `{len(items)}종`\n"
                f"• **현재 천장:** 캐릭터 `{u_data.get('pity_char', 0)}/90` ({'확정' if u_data.get('guaranteed_char') else '반천'}) · 무기 `{u_data.get('pity_weapon', 0)}/80` · 성유물 `{u_data.get('pity_artifact', 0)}/50` · 상시 `{u_data.get('pity_standard', 0)}/90`\n"
                f"• **재화:** ✨ 스타라이트 `{u_data.get('starglitter', 0):,}` · 💠 스타더스트 `{u_data.get('stardust', 0):,}`\n"
                f"• **주력 캐릭터:** {top3}\n"
                f"• **파티 전투력:** `{party_ana['total_power']:,}` (공명 {len(party_ana['resonances'])}개)"
            ),
            color=discord.Color.from_rgb(56, 152, 236),
            timestamp=datetime.datetime.now(core.KST),
        )
        if rep_char:
            emb.set_thumbnail(url=genshin_core.get_genshin_primary_image_url(rep_char, splash=False))
        else:
            emb.set_thumbnail(url=target.display_avatar.url)
        await core.safe_send_response(interaction, embed=emb)

    @app_commands.command(name="랭킹", description="🏆 서버 원신 수집 랭킹 · 10연 명예의 전당 · 최근 ★5 속보를 확인합니다")
    async def ranking_cmd(self, interaction: discord.Interaction):
        v = GenshinRankingView(interaction.guild_id or 0, mode="ranking")
        await core.safe_send_response(interaction, embed=v.build_embed(interaction.guild), view=v)

    @app_commands.command(name="픽업설정", description="🔒 [봇 주인 전용] 원신 기원 픽업(5성/4성/무기/성유물/시각 로테이션)을 변경합니다")
    @app_commands.choices(프리셋=[
        app_commands.Choice(name="⏰ KST 시각 연동 2시간 자동 로테이션 (권장)", value="time_rotation"),
        app_commands.Choice(name="🌟 최신 캐릭터 (로엔 / 린네아)", value="latest"),
        app_commands.Choice(name="❄️ 스네즈나야 (콜롬비나 / 스커크)", value="snezhnaya_star"),
        app_commands.Choice(name="🌙 노드크라이 (바르카 / 플린스)", value="nodkrai_moon"),
        app_commands.Choice(name="💧 폰타인 (푸리나 / 느비예트)", value="fontaine_archon"),
        app_commands.Choice(name="🔥 나타 (마비카 / 시틀라리)", value="natlan_archon"),
        app_commands.Choice(name="⚡ 이나즈마 (라이덴 쇼군 / 아를레키노)", value="inazuma_thunder"),
        app_commands.Choice(name="🌿 수메르 (나히다 / 방랑자)", value="sumeru_dendro"),
        app_commands.Choice(name="🧹 기본값 초기화", value="reset"),
    ])
    @app_commands.autocomplete(
        캐릭터1=genshin_core.genshin_5star_char_autocomplete,
        캐릭터2=genshin_core.genshin_5star_char_autocomplete,
        사성1=genshin_core.genshin_4star_char_autocomplete,
        사성2=genshin_core.genshin_4star_char_autocomplete,
        사성3=genshin_core.genshin_4star_char_autocomplete,
        무기1=genshin_core.genshin_5star_weapon_autocomplete,
        무기2=genshin_core.genshin_5star_weapon_autocomplete,
        성유물1=genshin_core.genshin_artifact_autocomplete,
        성유물2=genshin_core.genshin_artifact_autocomplete,
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
        무기1: Optional[str] = None,
        무기2: Optional[str] = None,
        성유물1: Optional[str] = None,
        성유물2: Optional[str] = None,
        배너이름: Optional[str] = None,
    ):
        if not await self.bot.is_bot_owner_user(interaction.user):
            return await core.safe_send_response(
                interaction,
                "⛔ **권한 부족:** `/원신 픽업설정`은 **봇 주인(소유자) 전용** 명령어입니다!",
                ephemeral=True,
            )

        await core.safe_defer(interaction, ephemeral=True)
        if 프리셋 and not any([캐릭터1, 캐릭터2, 사성1, 사성2, 사성3, 무기1, 무기2, 성유물1, 성유물2, 배너이름]):
            ok, msg, eff = await asyncio.to_thread(genshin_core.apply_genshin_pickup_preset, 프리셋)
        else:
            chars, weapons = genshin_core.load_genshin_kr_db()
            by_c = {c["id"]: c for c in chars}
            by_w = {w["id"]: w for w in weapons}
            by_a = {a["id"]: a for a in genshin_core.GENSHIN_ARTIFACTS}
            data = core.load_data()
            cfg = dict(data.get("genshin_pickup") or {})
            if 프리셋 and 프리셋 not in ("reset", "time_rotation"):
                pr = genshin_core.GENSHIN_BANNER_PRESETS.get(프리셋, {})
                cfg.update({k: pr[k] for k in ("char1", "char2", "char_4_ids", "weapon_1", "weapon_2", "artifact_1", "artifact_2", "banner_name") if k in pr})
            if 캐릭터1 and 캐릭터1 in by_c:
                cfg["char1"] = 캐릭터1
            if 캐릭터2 and 캐릭터2 in by_c:
                cfg["char2"] = 캐릭터2
            custom_4s = [x for x in (사성1, 사성2, 사성3) if x and x in by_c]
            if custom_4s:
                cfg["char_4_ids"] = custom_4s
            if 무기1 and 무기1 in by_w:
                cfg["weapon_1"] = 무기1
            if 무기2 and 무기2 in by_w:
                cfg["weapon_2"] = 무기2
            if 성유물1 and 성유물1 in by_a:
                cfg["artifact_1"] = 성유물1
            if 성유물2 and 성유물2 in by_a:
                cfg["artifact_2"] = 성유물2
            if 배너이름:
                cfg["banner_name"] = 배너이름.strip()[:60]
            cfg["updated_at"] = datetime.datetime.now(core.KST).isoformat()
            data["genshin_pickup"] = cfg
            core.save_data(data)
            eff = genshin_core.resolve_effective_genshin_pickup(cfg)
            msg = "✅ **원신 커스텀 픽업 설정이 적용되었습니다!**"

        emb = discord.Embed(
            title="🎯 원신 이벤트 기원 픽업 적용 완료",
            description=(
                f"{msg}\n\n"
                f"• **캐릭터 ① / ②:** `★★★★★ {eff['char1']['name'] if eff.get('char1') else '-'}` / `★★★★★ {eff['char2']['name'] if eff.get('char2') else '-'}`\n"
                f"• **픽업 ★★★★:** {', '.join(c['name'] for c in eff['char_4'])}\n"
                f"• **무기 ① / ②:** `{eff['weapon_1']['name'] if eff.get('weapon_1') else '-'}` / `{eff['weapon_2']['name'] if eff.get('weapon_2') else '-'}`\n"
                f"• **성유물 ① / ②:** `{eff['artifact_1']['name'] if eff.get('artifact_1') else '-'}` / `{eff['artifact_2']['name'] if eff.get('artifact_2') else '-'}`"
            ),
            color=discord.Color.gold(),
        )
        await interaction.followup.send(embed=emb, ephemeral=True)

    @app_commands.command(name="서버초기화", description="🧹 [서버 관리자 전용] 이 서버의 모든 원신 기원/보관함 데이터를 초기화합니다")
    async def reset_guild_cmd(self, interaction: discord.Interaction):
        is_owner = await self.bot.is_bot_owner_user(interaction.user)
        perms = getattr(interaction.user, "guild_permissions", None)
        if not (is_owner or (perms and (perms.administrator or perms.manage_guild))):
            return await core.safe_send_response(interaction, "⛔ 서버 관리자 또는 봇 주인만 실행할 수 있습니다.", ephemeral=True)
        v = GenshinGuildResetConfirmView(interaction.guild_id or 0, interaction.user)
        await core.safe_send_response(
            interaction,
            "⚠️ 정말로 **이 서버의 모든 유저 원신 기원 데이터**를 초기화하시겠습니까? (복구 불가)",
            view=v,
            ephemeral=True,
        )

    # 프리픽스 단축어 (!원신기원 / !원신뽑기 / !원신도감)
    @commands.command(name="원신기원", aliases=["원신뽑기"])
    async def prefix_wish(self, ctx: commands.Context, banner: str = "char1", count: int = 10):
        banner_map = {"1": "char1", "2": "char2", "무기": "weapon", "성유물": "artifact", "상시": "standard"}
        bk = banner_map.get(banner, banner if banner in genshin_core.GENSHIN_BANNER_CONFIGS else "char1")
        cnt = 10 if count >= 10 else 1
        ok, rem = core.check_and_update_gacha_cooldown(ctx.author.id, skip_anim=False)
        if not ok:
            return await ctx.reply(f"⏳ 가챠 쿨타임 중입니다! **`{rem:.1f}초`** 후 다시 시도해 주세요.")
        res = await asyncio.to_thread(genshin_core.execute_genshin_pull, ctx.guild.id if ctx.guild else 0, ctx.author.id, bk, cnt, False)
        emb, high_items = _build_genshin_result_embed(res, ctx.author)
        grid_res = await asyncio.to_thread(genshin_core.build_genshin_10pull_grid_bytes, res["drawn"], bk, f"{res['user_state'].get('total_pulls', 0)}회") if cnt >= 2 else (None, None)
        files = []
        g_bytes, g_fn = grid_res if isinstance(grid_res, tuple) else (grid_res.getvalue() if grid_res else None, "genshin_grid.png")
        if g_bytes:
            safe_g_fn = g_fn or "genshin_grid.png"
            files.append(discord.File(io.BytesIO(g_bytes), filename=safe_g_fn))
            emb.set_image(url=f"attachment://{safe_g_fn}")
        elif high_items:
            sb, sfn = await asyncio.to_thread(genshin_core.fetch_genshin_item_image_bytes, high_items[0], True)
            if sb:
                files.append(discord.File(io.BytesIO(sb), filename=sfn))
                emb.set_image(url=f"attachment://{sfn}")
        v = GenshinPullAgainView(ctx.author, banner_key=bk, last_count=cnt)
        await ctx.reply(embed=emb, files=files, view=v)

    @commands.command(name="원신도감")
    async def prefix_pokedex(self, ctx: commands.Context):
        v = GenshinPokedexView(ctx.guild.id if ctx.guild else 0, ctx.author, tab="owned")
        await ctx.reply(embed=v.build_embed(), view=v)


async def setup(bot: commands.Bot):
    await bot.add_cog(GenshinCog(bot))
