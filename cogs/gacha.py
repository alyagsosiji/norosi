import io
import copy
import random
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
async def _is_interaction_bot_owner(interaction: discord.Interaction, bot_instance=None) -> bool:
    user = getattr(interaction, "user", None)
    if not user:
        return False
    bot_ref = bot_instance or getattr(interaction, "client", None)
    if bot_ref and hasattr(bot_ref, "is_bot_owner_user"):
        try:
            return bool(await bot_ref.is_bot_owner_user(user))
        except Exception:
            pass
    if core.BOT_OWNER_ID and getattr(user, "id", None) == core.BOT_OWNER_ID:
        return True
    return False


def _pick_spotlight_card(drawn: list) -> dict | None:
    """대사 선공개 연출에 사용할 가장 돋보이는 카드 1장을 선택합니다."""
    if not drawn:
        return None
    high_cards = [c for c in drawn if c.get("star_num", 0) >= 4]
    pool = high_cards if high_cards else [c for c in drawn if c.get("star_num", 0) == 3]
    if not pool:
        return drawn[-1]

    def _score(c: dict):
        trig = c.get("bonus_trigger")
        trig_rank = 3 if trig == "select_list" else (2 if trig == "100pt" else (1 if trig == "50pt" else 0))
        return (
            trig_rank,
            int(bool(c.get("is_pickup"))),
            int(bool(c.get("is_new"))),
            int(c.get("star_num", 0)),
        )

    return max(pool, key=_score)


def _get_card_preview_quote(card: dict) -> str:
    """카드의 공식 가챠 대사(gachaPhrase) 또는 캐릭터 대표 대사를 반환합니다."""
    raw_quote = (card.get("gachaPhrase") or "").strip()
    if raw_quote and raw_quote != "-":
        return raw_quote
    char_id = int(card.get("char_id") or 1)
    return core.DEFAULT_CHARACTER_QUOTES.get(char_id, "세카이의 새로운 소리가 울려 퍼집니다!")


def build_gacha_intro_embed(drawn: list, banner_type: str = "normal", pull_count: int = 1) -> discord.Embed:
    """뽑기 결과 공개 직전 오브 승격 연출 및 ★4·생일 대사(gachaPhrase) 선공개 임베드 (단일 프레임 호환용)"""
    b_cfg = core.get_banner_meta(banner_type)
    high_cards = [c for c in drawn if c.get("star_num", 0) >= 4]
    has_4star = len(high_cards) > 0
    has_3star = any(c.get("star_num", 0) == 3 for c in drawn)

    if has_4star:
        orb_line = "🔵 파란 빛 ➔ 🟡 황금 빛\n🌈 **무지개 빛으로 승격!!**"
        tier_msg = "✨ 최고 등급(**★★★★ / 🎂 생일**) 카드 출현 확정"
        color = discord.Color.from_rgb(255, 105, 180)
        top_card = _pick_spotlight_card(drawn) or high_cards[0]
        raw_quote = _get_card_preview_quote(top_card)
        quote_block = f"\n\n> 💬 *\"{raw_quote}\"*\n└ — **???** *(어디선가 익숙한 목소리가 들려옵니다…)*"
    elif has_3star:
        orb_line = "🔵 파란 빛 ➔ 🟡 **황금 빛 반짝임!**"
        tier_msg = "💫 **★★★ 이상 카드 등장**"
        color = discord.Color.gold()
        quote_block = "\n\n✨ *세카이의 문이 천천히 열리고 있습니다…*"
    else:
        orb_line = "🔵 **잔잔한 푸른 빛이 감돕니다…**"
        tier_msg = "🎵 프로세카 스카우트 진행 중"
        color = discord.Color.from_rgb(0, 204, 221)
        quote_block = "\n\n✨ *카드가 도착하고 있습니다…*"

    title = f"🎰 {b_cfg['short_name']} ({pull_count}회 뽑기)"
    embed = discord.Embed(
        title=title,
        description=f"{orb_line}\n{tier_msg}{quote_block}",
        color=color,
        timestamp=datetime.datetime.now(core.KST)
    )
    embed.set_footer(text="잠시 후 전체 카드 결과와 일러스트가 공개됩니다")
    return embed


def build_gacha_animation_stages(
    drawn: list,
    banner_type: str = "normal",
    pull_count: int = 1,
    pity_info: dict | None = None,
) -> list[tuple[discord.Embed, float]]:
    """
    다단계 리얼타임 가챠 연출 시퀀스를 생성합니다:
    1) 오브 등장 (★4 시 약 48% 확률로 황금/파란 오브 페이크 시작!)
    2) 승격 반전 연출 (🟡/🔵 ➔ 💥 🌈 무지개 빛으로 대폭발 승격!)
    3) ★4/🎂생일 대사 선공개 스포트라이트 컷신 (실루엣 `???` + 유닛/속성/NEW·픽업 힌트!)
    """
    b_cfg = core.get_banner_meta(banner_type)
    high_cards = [c for c in drawn if c.get("star_num", 0) >= 4]
    has_4star = len(high_cards) > 0
    has_3star = any(c.get("star_num", 0) == 3 for c in drawn)
    base_title = f"🎰 {b_cfg['short_name']} ({pull_count}회 뽑기)"
    now_ts = datetime.datetime.now(core.KST)
    stages: list[tuple[discord.Embed, float]] = []

    if has_4star:
        pity = pity_info or {}
        top_card = _pick_spotlight_card(drawn) or high_cards[0]
        do_promotion = (random.random() < 0.48)

        bonus_callout = ""
        if banner_type == "select_list":
            bonus_callout = "\n> 🎟️ **셀렉트 리스트 확정 슬롯 발동!**"
        elif pity.get("hit_100"):
            bonus_callout = "\n> 🔥 **100pt 가챠 보너스 발동 · 픽업 최고 등급 확정!**"
        elif pity.get("hit_50"):
            bonus_callout = "\n> ⚡ **50pt 가챠 보너스 발동 · ★4 확정!**"

        # 높은 성 카드 다수 출현 시: 나온 캐릭터 수 × 0.3초를 앞 연출(오브/승격)에 균등 분배
        n_high = len(high_cards)
        multi_extra = 0.3 * n_high if n_high > 1 else 0.0

        if do_promotion:
            super_fake = (random.random() < 0.25)
            if super_fake:
                s1 = discord.Embed(
                    title=base_title,
                    description=(
                        "🔵 **잔잔한 푸른 빛의 오브가 내려옵니다…**\n"
                        "🎵 *세카이의 문이 열리고 있습니다…*\n\n"
                        "> ⚡ *…어라? 푸른 오브가 미세하게 진동하기 시작했습니다?!*"
                    ),
                    color=discord.Color.from_rgb(0, 188, 224),
                    timestamp=now_ts,
                )
            else:
                s1 = discord.Embed(
                    title=base_title,
                    description=(
                        "🔵 파란 빛 ➔ 🟡 **황금 빛 오브 출현!**\n"
                        "💫 ★★★ 이상 카드 등장…?\n\n"
                        "> ⚡ *…잠깐?! 황금 오브 표면에 눈부신 균열이 생기고 있습니다!!*"
                    ),
                    color=discord.Color.gold(),
                    timestamp=now_ts,
                )
            s1.set_footer(text="✨ 세카이의 빛을 확인하는 중…")
            stages.append((s1, 1.4 + multi_extra / 2))

            promo_arrow = (
                "🔵 파란 오브 ➔ ⚡ 🟡 황금 오브\n💥 🌈 **무지개 빛으로 2단 대역전 승격!!**"
                if super_fake
                else "🟡 황금 오브 ➔ ⚡ 균열 돌파!\n💥 🌈 **무지개 빛으로 역전 승격!!**"
            )
            s2 = discord.Embed(
                title="⚡ 승격 연출 발동! (PROMOTION)",
                description=(
                    f"{promo_arrow}\n"
                    f"✨ 최고 등급(**★★★★ / 🎂 생일**) 카드 출현 확정!{bonus_callout}\n\n"
                    "🌟 *눈부신 레인보우 섬광 너머로 누군가의 목소리가 들려옵니다…*"
                ),
                color=discord.Color.from_rgb(255, 64, 168),
                timestamp=now_ts,
            )
            s2.set_footer(text="🌈 역전 승격 성공 · 곧 캐릭터 대사가 선공개됩니다")
            stages.append((s2, 1.4 + multi_extra / 2))
        else:
            s1 = discord.Embed(
                title=f"🌈 {b_cfg['short_name']} — 무지개 오브 출현!",
                description=(
                    "🔵 파란 빛 ➔ 🟡 황금 빛\n🌈 **찬란한 무지개 빛 폭발!!**\n"
                    f"✨ 최고 등급(**★★★★ / 🎂 생일**) 카드 출현 확정!{bonus_callout}\n\n"
                    "🌟 *세카이의 문 너머에서 특별한 목소리가 울려 퍼집니다…*"
                ),
                color=discord.Color.from_rgb(255, 105, 180),
                timestamp=now_ts,
            )
            s1.set_footer(text="🌈 최고 등급 확정 · 곧 캐릭터 대사가 선공개됩니다")
            stages.append((s1, 1.85 + multi_extra))

        # 대사 선공개 스포트라이트: 높은 성 카드가 여러 장이면 나온 순서대로 한 명씩 대사가 지나갑니다
        quote_cards = high_cards if n_high > 1 else [top_card]
        quote_wait = 1.75 if n_high <= 1 else 1.5
        for q_idx, q_card in enumerate(quote_cards, start=1):
            raw_quote = _get_card_preview_quote(q_card)
            unit_name = q_card.get("unit") or "세카이"
            unit_emoji = core.UNIT_EMOJIS.get(unit_name, "🎵")
            attr_txt = q_card.get("attr") or "✨"
            hint_badges = []
            if q_card.get("rarity_type") == "rarity_birthday":
                hint_badges.append("🎂 `생일 한정`")
            elif q_card.get("bonus_trigger") == "select_list":
                hint_badges.append("🎟️ `셀렉트 확정`")
            elif q_card.get("bonus_trigger") == "100pt":
                hint_badges.append("🔥 `100pt 픽업확정`")
            elif q_card.get("bonus_trigger") == "50pt":
                hint_badges.append("⚡ `50pt 보너스`")
            elif q_card.get("is_pickup"):
                hint_badges.append("🎯 `픽업 예감!`")
            if q_card.get("is_new"):
                hint_badges.append("✨ `NEW! 처음 만나는 목소리`")

            badge_line = f"\n└ {' · '.join(hint_badges)}" if hint_badges else ""
            remain = len(quote_cards) - q_idx
            extra_line = f"\n\n🌈 다음 목소리 **{remain}명** 대기 중…" if remain > 0 else ""
            seq_tag = f" {q_idx}/{len(quote_cards)}" if len(quote_cards) > 1 else ""
            u_rgb = core.UNIT_THEME_COLORS.get(unit_name, (255, 105, 180))
            s_quote = discord.Embed(
                title=f"💬 대사 선공개{seq_tag} (VOICE PREVIEW)",
                description=(
                    f"> ### *\"{raw_quote}\"*\n\n"
                    f"— **???**\n"
                    f"└ {unit_emoji} `{unit_name}` · {attr_txt}"
                    f"{badge_line}"
                    f"{extra_line}"
                ),
                color=discord.Color.from_rgb(*u_rgb),
                timestamp=now_ts,
            )
            s_quote.set_footer(
                text="다음 목소리가 이어집니다…" if remain > 0 else "잠시 후 전체 카드 결과와 고화질 일러스트가 공개됩니다"
            )
            stages.append((s_quote, quote_wait))
        return stages

    if has_3star:
        s1 = discord.Embed(
            title=base_title,
            description="🔵 **푸른 오브가 천천히 빛나고 있습니다…**\n🎵 *세카이의 문이 열리는 중…*",
            color=discord.Color.from_rgb(0, 188, 224),
            timestamp=now_ts,
        )
        s1.set_footer(text="✨ 세카이의 빛을 확인하는 중…")
        stages.append((s1, 1.2))

        top3 = _pick_spotlight_card(drawn)
        q3 = _get_card_preview_quote(top3) if top3 else ""
        q3_block = f"\n\n> 💬 *\"{q3}\"*\n└ — **???** · `{top3.get('unit', '')}`" if q3 else ""
        s2 = discord.Embed(
            title=f"🟡 {b_cfg['short_name']} — 황금 빛 승격!",
            description=f"🔵 파란 빛 ➔ 🟡 **황금 빛 반짝임!**\n💫 **★★★ 이상 카드 등장!**{q3_block}",
            color=discord.Color.gold(),
            timestamp=now_ts,
        )
        s2.set_footer(text="잠시 후 전체 카드 결과가 공개됩니다")
        stages.append((s2, 1.5))
        return stages

    s1 = discord.Embed(
        title=base_title,
        description="🔵 **잔잔한 푸른 빛이 감돕니다…**\n🎵 프로세카 스카우트 진행 중\n\n✨ *카드가 도착하고 있습니다…*",
        color=discord.Color.from_rgb(0, 204, 221),
        timestamp=now_ts,
    )
    s1.set_footer(text="잠시 후 결과가 공개됩니다")
    stages.append((s1, 1.75))
    return stages


def build_gacha_pull_embed(
    drawn: list,
    pickup_cfg: dict,
    pull_count: int,
    user: discord.User = None,
    banner_type: str = "normal",
    mode_note: str | None = None,
    pity_info: dict | None = None,
):
    has_4star = any(c["star_num"] >= 4 for c in drawn)
    b_cfg = core.get_banner_meta(banner_type)
    default_rgb = b_cfg.get("color", (0, 204, 221))
    # 테두리 색: ★4/생일 = 분홍, 최고 ★3 = 노랑, 그 외 = 배너 기본색
    if has_4star:
        embed_color = discord.Color.from_rgb(255, 105, 180)
    elif any(c.get("star_num", 0) == 3 for c in drawn):
        embed_color = discord.Color.from_rgb(242, 184, 48)
    else:
        embed_color = discord.Color.from_rgb(*default_rgb)

    pickup_summary = "직접 선택한 ★4 10장 확정" if banner_type == "select_list" else core.format_pickup_summary(pickup_cfg)
    is_single = len(drawn) == 1

    lines = []
    for idx, c in enumerate(drawn, start=1):
        trig = c.get("bonus_trigger")
        tag_chips = []
        if trig == "select_list":
            tag_chips.append("🎟️`셀렉트확정`")
        elif trig == "100pt":
            tag_chips.append("🔥`100pt확정`")
        elif trig == "50pt":
            tag_chips.append("⚡`50pt보너스`")
        elif c.get("is_pickup"):
            tag_chips.append("🎯`픽업`")
        if c.get("is_new"):
            tag_chips.append("✨`NEW`")

        s_num = c.get("star_num", 2)
        r_type = c.get("rarity_type", "")
        if r_type == "rarity_birthday":
            rarity_badge = "🎂 `생일`"
        elif s_num >= 4:
            rarity_badge = "🌟 `★4`"
        elif s_num == 3:
            rarity_badge = "💫 `★3`"
        elif s_num == 2:
            rarity_badge = "⭐ `★2`"
        else:
            rarity_badge = "🔹 `★1`"

        unit_str = f"{c['unit']}" + (f" ({c['support_unit']})" if c.get("support_unit") else "")
        limit_lbl = c.get("limit_label") or ""
        chips_str = (" " + " ".join(tag_chips)) if tag_chips else ""

        if s_num >= 4 or is_single:
            cos = core.get_costume_for_card(c.get("id"))
            cos_part = f" · 👗 `{cos['name']}`" if cos else ""
            lim_part = f"`{limit_lbl}` · " if limit_lbl else ""
            row = (
                f"`{idx:02d}.` {rarity_badge} **{c['char_name']}** [{c['prefix']}]{chips_str}\n"
                f"└ {lim_part}`{unit_str}` · {c['attr']}{cos_part} · `{c.get('prob', 0.0):.4f}%`"
            )
            lines.append(row)
        elif s_num == 3:
            lines.append(
                f"`{idx:02d}.` {rarity_badge} **{c['char_name']}** [{c['prefix']}]{chips_str} · `{c['unit']}` · {c['attr']}"
            )
        else:
            lines.append(
                f"`{idx:02d}.` {rarity_badge} {c['char_name']} [{c['prefix']}]{chips_str} · `{c['unit']}` · {c['attr']}"
            )

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
        summary_parts.append(f"✨ NEW `{new_cnt}장`")

    summary_val = " · ".join(summary_parts) if summary_parts else "결과 없음"

    pull_lbl = "10연차" if pull_count == 10 else f"{pull_count}회 단차"
    if banner_type == "select_list":
        title_str = "🎟️ 셀렉트 리스트 10연차 확정 결과"
    elif banner_type == "fes":
        title_str = f"🎊 페스티벌 ★4 2배 {pull_lbl} 결과" + (" — 최고 등급 등장!" if has_4star else "")
    elif banner_type == "birthday":
        title_str = f"🎂 생일 스페셜 {pull_lbl} 결과" + (" — 생일 카드 등장!" if has_4star else "")
    elif has_4star:
        title_str = f"🌈 프로세카 {pull_lbl} 결과 — 최고 등급 등장!"
    else:
        title_str = f"🎵 프로세카 {pull_lbl} 결과"

    header_lines = [f"🎰 **배너:** `{b_cfg['name']}`"]
    if mode_note:
        header_lines.append(f"> {mode_note}")
    if pity_info:
        if pity_info.get("hit_100"):
            p_txt = "픽업 ★4 확정 출현!" if pity_info.get("had_pickup_pool") else "★4 확정 출현!"
            header_lines.append(f"> 🔥 **100pt 가챠 보너스 발동** — 🎯 {p_txt} *(게이지 리셋)*")
        elif pity_info.get("hit_50"):
            header_lines.append("> ⚡ **50pt 가챠 보너스 발동** — 🌟 ★4 최고 등급 1장 확정 출현!")
    today_bdays = core.get_today_birthday_characters()
    if today_bdays:
        bday_names = ", ".join(b["char_name"] for b in today_bdays)
        header_lines.append(f"🎂 **오늘의 생일:** `{bday_names}` *(하단 무료 단차 지원)*")

    banner_line = "\n".join(header_lines) + "\n\n"
    body_text = "\n".join(lines)
    max_body = max(200, 4040 - len(banner_line))
    if len(body_text) > max_body:
        body_text = body_text[:max_body - 12].rstrip() + "\n…*(생략)*"
    full_desc = (banner_line + body_text)[:4090]
    embed = discord.Embed(
        title=title_str[:256],
        description=full_desc,
        color=embed_color,
        timestamp=datetime.datetime.now(core.KST)
    )

    embed.add_field(name="📊 뽑기 요약", value=summary_val, inline=False)

    if pity_info:
        gauge_text, badge_text = core.format_gacha_pity_display(pity_info)
        embed.add_field(
            name="⚡ 가챠 보너스 게이지 (50pt ★4 · 100pt 픽업 ★4)",
            value=gauge_text,
            inline=False,
        )
        embed.add_field(
            name=f"🏅 가챠 배지 천장 ({int(pity_info.get('ceiling_cost', core.GACHA_CEILING_BADGE_COST))}개)",
            value=badge_text,
            inline=False,
        )

    embed.add_field(name="🎯 현재 픽업", value=core.truncate_text(pickup_summary, 1000) or "-", inline=False)

    if user:
        author_icon = user.display_avatar.url if hasattr(user, "display_avatar") else None
        embed.set_author(name=f"{user.display_name}님의 가챠 결과", icon_url=author_icon)

    embed.set_footer(text=f"{b_cfg['short_name']} • {pull_lbl}")
    return embed, has_4star


async def _build_gacha_result_payload(
    drawn: list,
    pickup_cfg: dict,
    pull_count: int,
    user: discord.abc.User | None,
    banner_type: str = "normal",
    mode_note: str | None = None,
    grid_tag: str = "",
    pity_info: dict | None = None,
    illust_mode: str = "normal",
    prebuilt_grid: tuple[bytes | None, str | None] = (None, None),
) -> tuple[list[discord.Embed], list[tuple[bytes, str]], list[tuple[discord.Embed, dict, str]], tuple[bytes | None, str | None]]:
    embed, has_4star = build_gacha_pull_embed(
        drawn,
        pickup_cfg,
        pull_count,
        user=user,
        banner_type=banner_type,
        mode_note=mode_note,
        pity_info=pity_info,
    )
    high_cards = [c for c in drawn if c.get("star_num", 0) >= 4] if has_4star else []
    total_high = len(high_cards)
    display_high = high_cards[:9]
    want_grid = len(drawn) >= 2
    want_single_img = (not has_4star) and (not want_grid) and len(drawn) == 1
    eff_mode = "after_training" if illust_mode == "after_training" else "normal"

    async def _fetch_one(card_obj: dict):
        c_mode = eff_mode if core.can_card_awaken(card_obj) else "normal"
        pair = await asyncio.to_thread(core.fetch_proseka_card_image_bytes, card_obj, c_mode)
        return c_mode, pair

    async def _fetch_images():
        if display_high:
            return await asyncio.gather(*(_fetch_one(c) for c in display_high))
        if want_single_img:
            return [await _fetch_one(drawn[0])]
        return []

    async def _fetch_grid():
        if want_grid:
            if prebuilt_grid[0] and prebuilt_grid[1]:
                return prebuilt_grid
            return await asyncio.to_thread(core.build_10pull_grid_image_bytes, drawn, banner_type, grid_tag)
        return None, None

    results, (grid_bytes, grid_fn) = await asyncio.gather(_fetch_images(), _fetch_grid())

    MAX_FILES = 10
    MAX_TOTAL_BYTES = 7_800_000
    file_specs: list[tuple[bytes, str]] = []
    total_bytes = 0

    if grid_bytes and grid_fn and len(grid_bytes) <= MAX_TOTAL_BYTES:
        file_specs.append((grid_bytes, grid_fn))
        total_bytes += len(grid_bytes)
        embed.set_image(url=f"attachment://{grid_fn}")

    if not has_4star:
        single_pairs: list[tuple[discord.Embed, dict, str]] = []
        if want_single_img and results:
            c0 = drawn[0]
            c0_mode, (img_bytes, img_fn) = results[0]
            if core.can_card_awaken(c0):
                stage_lbl = (
                    "✨ 특훈 후 일러스트"
                    if c0_mode == "after_training"
                    else "🌸 특훈 전 일러스트 • 하단 버튼으로 특훈 전·후 전환"
                )
                embed.set_footer(text=f"{embed.footer.text or ''} • {stage_lbl}".strip(" •"))
            if img_bytes and img_fn and len(file_specs) < MAX_FILES and (total_bytes + len(img_bytes) <= MAX_TOTAL_BYTES):
                safe_fn = f"pull_1_{c0_mode}_{img_fn}"
                file_specs.append((img_bytes, safe_fn))
                total_bytes += len(img_bytes)
                embed.set_image(url=f"attachment://{safe_fn}")
            else:
                embed.set_image(url=core.get_proseka_card_image_url(c0, c0_mode))
            single_pairs.append((embed, c0, c0_mode))
        return [embed], file_specs, single_pairs, (grid_bytes, grid_fn)

    embeds = [embed]
    card_embed_pairs: list[tuple[discord.Embed, dict, str]] = []
    if total_high > 9:
        rest = ", ".join(f"[{c.get('prefix', '')}] {c.get('char_name', '')}" for c in high_cards[9:])
        embed.add_field(
            name=f"🖼️ 일러스트 미표시 {total_high - 9}장 (디스코드 10개 제한)",
            value=core.truncate_text(rest, 1000) + "\n└ 내 카드 보관함에서 특훈 전·후 일러스트를 모두 확인할 수 있어요",
            inline=False,
        )

    for idx, (c, (c_mode, (img_bytes, img_fn))) in enumerate(zip(display_high, results), start=1):
        is_bday_card = (c.get("rarity_type") == "rarity_birthday")
        card_badge = "🎂 생일" if is_bday_card else "🌟 ★4"
        trig = c.get("bonus_trigger")
        title_tags = []
        if trig == "select_list":
            title_tags.append("🎟️ 셀렉트확정")
        elif trig == "100pt":
            title_tags.append("🔥 100pt확정")
        elif trig == "50pt":
            title_tags.append("⚡ 50pt보너스")
        elif c.get("is_pickup"):
            title_tags.append("🎯 픽업")
        if c.get("is_new"):
            title_tags.append("✨ NEW")

        limit_lbl = c.get("limit_label") or "통상"
        order_txt = f" ({idx}/{total_high})" if total_high > 1 else ""
        unit_str = f"{c.get('unit', '')}" + (f" ({c.get('support_unit')})" if c.get("support_unit") else "")

        awakenable = core.can_card_awaken(c)
        stage_prefix = ("✨ [특훈 후] " if c_mode == "after_training" else "🌸 [특훈 전] ") if awakenable else ""
        card_title = f"{card_badge} {stage_prefix}[{c.get('prefix', '')}] {c.get('char_name', '')}{order_txt}"
        desc_parts = []
        if title_tags:
            desc_parts.append(" · ".join(f"**{t}**" for t in title_tags) + f" · `{limit_lbl}`")
        else:
            desc_parts.append(f"분류: `{limit_lbl}`")

        raw_phrase = (c.get("gachaPhrase") or "").strip()
        if not raw_phrase or raw_phrase == "-":
            raw_phrase = (_get_card_preview_quote(c) or "").strip()
        if raw_phrase and raw_phrase != "-":
            desc_parts.append(f"> 💬 *\"{raw_phrase}\"*")

        card_embed = discord.Embed(
            title=card_title[:256],
            description="\n\n".join(desc_parts),
            color=discord.Color.from_rgb(255, 105, 180),
            timestamp=datetime.datetime.now(core.KST)
        )
        card_embed.add_field(name="🏷️ 유닛", value=f"`{unit_str}`", inline=True)
        card_embed.add_field(name="✨ 속성", value=f"{c.get('attr', '✨')}", inline=True)
        card_embed.add_field(name="📊 확률", value=f"`{c.get('prob', 0):.4f}%`", inline=True)
        if c.get("skill_name"):
            card_embed.add_field(name="⚡ 스킬", value=f"`{c.get('skill_name')}`", inline=True)
        cos = core.get_costume_for_card(c.get("id"))
        if cos:
            card_embed.add_field(
                name="👗 3D 의상 획득",
                value=f"`{cos['name']}` *(의상실 착용 · ✦MR.2 어나더 컬러)*",
                inline=False,
            )

        if awakenable:
            if c_mode == "after_training":
                card_embed.set_footer(text="프로세카 ★4 특훈 후 (After Training) 공식 일러스트")
            else:
                card_embed.set_footer(text="프로세카 ★4 특훈 전 (Normal) 공식 일러스트 • 하단 버튼으로 특훈 전·후 전환")
        else:
            footer_kind = "🎂 생일 한정" if is_bday_card else "★4"
            card_embed.set_footer(text=f"프로세카 {footer_kind} 공식 일러스트")

        if img_bytes and img_fn and len(file_specs) < MAX_FILES and (total_bytes + len(img_bytes) <= MAX_TOTAL_BYTES):
            safe_fn = f"pull_{idx}_{c_mode}_{img_fn}"
            file_specs.append((img_bytes, safe_fn))
            total_bytes += len(img_bytes)
            card_embed.set_image(url=f"attachment://{safe_fn}")
        else:
            card_embed.set_image(url=core.get_proseka_card_image_url(c, c_mode))
        embeds.append(card_embed)
        card_embed_pairs.append((card_embed, c, c_mode))

    return embeds, file_specs, card_embed_pairs, (grid_bytes, grid_fn)


async def send_gacha_pull_result(
    interaction: discord.Interaction,
    drawn: list,
    pickup_cfg: dict,
    pull_count: int,
    view: discord.ui.View,
    banner_type: str = "normal",
    skip_anim: bool = False,
    mode_note: str | None = None,
    grid_tag: str = "",
    pity_info: dict | None = None,
):
    """뽑기 결과 전송: 기본은 특훈 전(Normal) 일러스트로 표시하며 버튼으로 특훈 전·후를 전환할 수 있습니다."""
    payload_task = asyncio.create_task(
        _build_gacha_result_payload(
            drawn,
            pickup_cfg,
            pull_count,
            interaction.user,
            banner_type=banner_type,
            mode_note=mode_note,
            grid_tag=grid_tag,
            pity_info=pity_info,
            illust_mode="normal",
        )
    )

    intro_msg = None
    try:
        if not skip_anim:
            stages = build_gacha_animation_stages(
                drawn, banner_type=banner_type, pull_count=pull_count, pity_info=pity_info
            )
            core.extend_gacha_cooldown(interaction.user.id, sum(w for _, w in stages) + 0.5)
            for s_idx, (stage_embed, wait_sec) in enumerate(stages):
                if s_idx == 0:
                    try:
                        intro_msg = await interaction.followup.send(embed=stage_embed, wait=True)
                    except Exception:
                        intro_msg = None
                elif intro_msg is not None:
                    try:
                        await intro_msg.edit(embed=stage_embed)
                    except Exception:
                        pass
                await asyncio.sleep(wait_sec)
        embeds, file_specs, card_embed_pairs, grid_pair = await payload_task
    except BaseException:
        if not payload_task.done():
            payload_task.cancel()
        raise

    if hasattr(view, "bind_pull_result"):
        view.bind_pull_result(
            drawn,
            pickup_cfg=pickup_cfg,
            pull_count=pull_count,
            banner_type=banner_type,
            mode_note=mode_note,
            grid_tag=grid_tag,
            pity_info=pity_info,
            grid_pair=grid_pair,
        )

    def _build_files(specs: list[tuple[bytes, str]]) -> list[discord.File]:
        return [discord.File(io.BytesIO(b), filename=fn) for b, fn in specs]

    if intro_msg is not None:
        try:
            await intro_msg.edit(embeds=embeds, attachments=_build_files(file_specs), view=view)
            return
        except Exception:
            try:
                await intro_msg.delete()
            except Exception:
                pass

    try:
        if file_specs:
            await interaction.followup.send(embeds=embeds, files=_build_files(file_specs), view=view, wait=True)
        else:
            await interaction.followup.send(embeds=embeds, view=view, wait=True)
    except discord.HTTPException:
        if embeds:
            embeds[0].set_image(url=None)
        for c_emb, c, f_mode in card_embed_pairs:
            c_emb.set_image(url=core.get_proseka_card_image_url(c, f_mode))
        await interaction.followup.send(embeds=embeds, view=view, wait=True)


class DuplicateConvertConfirmView(core.SafeView):
    """2장 이상 중복 보유한 카드(잠금 제외)를 크리스탈로 일괄 변환하는 확인 뷰"""
    def __init__(
        self,
        guild_id: int = 0,
        user: discord.User | None = None,
        preview_info: dict | None = None,
        parent_inventory_view=None,
        parent_inventory_message=None,
        parent_menu_view=None,
        parent_menu_message=None
    ):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.user = user
        self.preview_info = preview_info or {}
        self.parent_inventory_view = parent_inventory_view
        self.parent_inventory_message = parent_inventory_message
        self.parent_menu_view = parent_menu_view
        self.parent_menu_message = parent_menu_message
        self.convert_btn.disabled = (self.preview_info.get("total_excess_cards", 0) <= 0)

    def build_preview_embed(self):
        tot_excess = self.preview_info.get("total_excess_cards", 0)
        tot_crystals = self.preview_info.get("total_crystals", 0)
        locked_skip = self.preview_info.get("locked_skipped", 0)
        u_name = self.user.display_name if self.user else "유저"

        embed = discord.Embed(
            title=f"💎 {u_name}님의 중복 카드 변환소",
            color=discord.Color.from_rgb(0, 204, 221) if tot_excess > 0 else discord.Color.dark_grey(),
            timestamp=datetime.datetime.now(core.KST)
        )

        if tot_excess <= 0:
            skip_note = f"\n\n> 🔒 잠금 보호된 중복 카드 `{locked_skip:,}장`은 자동 제외되었습니다." if locked_skip > 0 else ""
            embed.description = (
                "📭 현재 변환 가능한 **중복 카드(2장 이상 보유)** 가 없습니다.\n"
                "모든 카드의 원본 1장은 도감·덱 유지를 위해 안전하게 보존됩니다."
                f"{skip_note}"
            )
            return embed

        r_lines = []
        for r_key in ("rarity_4", "rarity_birthday", "rarity_3", "rarity_2", "rarity_1"):
            r_data = self.preview_info.get("by_rarity", {}).get(r_key, {})
            if r_data.get("count", 0) > 0:
                r_lines.append(f"• **{r_data['label']}** — 초과 `{r_data['count']:,}장` ➔ **`+{r_data['crystals']:,} 💎`**")

        embed.description = (
            "보유 수량이 `2장 이상`인 카드에서 **원본 1장을 남기고** 초과분만 변환합니다.\n"
            "*(도감 수집률과 5인 덱 편성은 유지됩니다)*"
        )
        embed.add_field(name="📋 등급별 변환 내역", value="\n".join(r_lines), inline=False)
        embed.add_field(name="🃏 총 변환 카드", value=f"**`{tot_excess:,}장`**", inline=True)
        embed.add_field(name="💎 예상 획득", value=f"**`+{tot_crystals:,} 💎`**", inline=True)
        if locked_skip > 0:
            embed.add_field(
                name="🔒 잠금 보호 제외",
                value=f"잠긴 카드 초과분 `{locked_skip:,}장`은 변환하지 않고 보존됩니다.",
                inline=False,
            )
        embed.set_footer(text="아래 [💎 중복 카드 일괄 변환 확정] 버튼을 누르면 즉시 지급됩니다")
        return embed

    @discord.ui.button(label="💎 중복 카드 일괄 변환 확정", style=discord.ButtonStyle.success, row=0)
    async def convert_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인만 변환을 실행할 수 있습니다.", ephemeral=True)
            return
        if not self.user:
            self.user = interaction.user

        await core.safe_defer(interaction)
        gid = self.guild_id or (interaction.guild_id or 0)
        res = await asyncio.to_thread(core.execute_duplicate_card_conversion, gid, self.user.id)
        if res["converted_count"] <= 0:
            await interaction.edit_original_response(
                embed=discord.Embed(title="ℹ️ 변환할 중복 카드가 없습니다.", color=discord.Color.dark_grey()),
                view=None
            )
            return

        # 열려 있는 /내캐릭터 보관함 뷰가 있다면 실시간으로 수량을 1장으로 갱신하고 원본 메시지 업데이트
        if self.parent_inventory_view:
            target_pool = getattr(self.parent_inventory_view, "all_cards", None) or self.parent_inventory_view.cards
            seen_ids = set()
            for c in target_pool:
                seen_ids.add(id(c))
                if not c.get("locked", False) and c.get("count", 1) > 1:
                    c["count"] = 1
            for c in self.parent_inventory_view.cards:
                if id(c) not in seen_ids and not c.get("locked", False) and c.get("count", 1) > 1:
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

        detail_lines = [f"• {line}" for line in res["details"][:8]]
        if len(res["details"]) > 8:
            detail_lines.append(f"*…외 `{len(res['details']) - 8:,}종` 변환 완료*")

        done_embed = discord.Embed(
            title="✨ 중복 카드 크리스탈 변환 완료!",
            description=(
                f"🎉 초과 중복 카드 **`{res['converted_count']:,}장`** 변환을 마쳤습니다.\n"
                "*(원본 1장과 🔒 잠금 카드는 안전하게 유지되었습니다)*"
            ),
            color=discord.Color.from_rgb(255, 105, 180),
            timestamp=datetime.datetime.now(core.KST)
        )
        done_embed.add_field(name="💎 획득 크리스탈", value=f"**`+{res['gained_crystals']:,} 💎`**", inline=True)
        done_embed.add_field(name="💰 현재 보유", value=f"**`{res['current_crystals']:,} 💎`**", inline=True)
        if detail_lines:
            done_embed.add_field(name="📋 변환 내역 요약", value="\n".join(detail_lines)[:1024], inline=False)
        await interaction.edit_original_response(embed=done_embed, view=None)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary, row=0)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인만 취소할 수 있습니다.", ephemeral=True)
            return
        await core.safe_edit_response(interaction, 
            embed=discord.Embed(title="✅ 중복 카드 변환이 취소되었습니다.", color=discord.Color.blue()),
            view=None
        )


# 모든 뽑기 경로(프로세카/원신/붕괴: 스타레일, 슬래시 명령어, 단차/10연차/재뽑기)에서 예외 없이 공유되는 쿨타임
# 기본 연출 보기: 프로세카 3.0초 (연출 +0.5초만큼 단축, 단 연출 재생 중에는 뽑기 불가) / 연출 스킵 시: 5.0초
GACHA_GLOBAL_COOLDOWN = core.GACHA_GLOBAL_COOLDOWN
GACHA_COOLDOWN_SECONDS = core.GACHA_COOLDOWN_SECONDS - 0.5
GACHA_SKIP_COOLDOWN_SECONDS = core.GACHA_SKIP_COOLDOWN_SECONDS


def check_and_update_gacha_cooldown(user_id: int, skip_anim: bool = False) -> tuple[bool, float]:
    return core.check_and_update_gacha_cooldown(user_id, skip_anim=skip_anim, base_seconds=GACHA_COOLDOWN_SECONDS)


class ProsekaRegisterView(core.SafeView):
    """프로세카 가챠 등록 버튼 (등록 시 ★1 카드 전부 기본 지급)"""

    def __init__(self, user: discord.abc.User, guild_id: int = 0):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = guild_id

    @discord.ui.button(label="📝 프로세카 가챠 등록", style=discord.ButtonStyle.success)
    async def register_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인만 등록 버튼을 누를 수 있습니다.", ephemeral=True)
            return
        ok, msg, _ = await asyncio.to_thread(
            core.register_proseka_gacha_user, interaction.guild_id or self.guild_id or 0, interaction.user.id
        )
        if ok:
            button.disabled = True
            button.label = "✅ 등록 완료"
            try:
                await interaction.response.edit_message(view=self)
            except Exception:
                pass
        await core.safe_send_response(interaction, f"{'🎉' if ok else 'ℹ️'} {msg}", ephemeral=True)


def build_proseka_register_embed() -> discord.Embed:
    return discord.Embed(
        title="📝 프로세카 가챠 등록",
        description=(
            "프로세카 가챠를 이용하려면 먼저 **등록**이 필요합니다.\n"
            "등록하면 ★1 카드 전체가 **내 보관함에 기본 지급**됩니다! 🎁"
        ),
        color=discord.Color.teal(),
    )


async def ensure_proseka_registered(interaction: discord.Interaction, guild_id: int | None = None) -> bool:
    """미등록 유저면 등록 안내를 보내고 False를 반환합니다 (모든 프로세카 뽑기 경로 공용 게이트)."""
    gid = guild_id if guild_id is not None else (interaction.guild_id or 0)
    if core.is_proseka_gacha_registered(gid, interaction.user.id):
        return True
    await core.safe_send_response(
        interaction,
        embed=build_proseka_register_embed(),
        view=ProsekaRegisterView(interaction.user, gid),
        ephemeral=True,
    )
    return False


class GachaPullAgainView(core.SafeView):
    """가챠 결과 화면에서 배너 전환, 연출 스킵, 재뽑기, 천장 교환(200배지), 셀렉트 리스트, 캐랭 깃발, 생일 단차 등을 여는 뷰"""

    def __init__(
        self,
        user: discord.User | None = None,
        banner_type: str | None = None,
        skip_anim: bool = False,
        guild_id: int = 0,
        pity_info: dict | None = None,
    ):
        super().__init__(timeout=600)
        self.user = user
        self.guild_id = guild_id
        self.banner_type = banner_type if banner_type in core.BANNER_CONFIGS else core.get_active_proseka_banner()
        self.skip_anim = bool(skip_anim)
        self.pity_info = pity_info or {}
        self.illust_mode = "normal"
        self._bound = False
        self.drawn_cards: list[dict] = []
        self.result_pickup_cfg: dict = {}
        self.result_pull_count: int = 1
        self.result_banner_type: str = self.banner_type
        self.result_mode_note: str | None = None
        self.result_grid_tag: str = ""
        self._cached_grid_pair: tuple[bytes | None, str | None] = (None, None)
        self._refresh_components()

    def _has_awakenable_result(self) -> bool:
        if not self.drawn_cards:
            return False
        has_4star = any(c.get("star_num", 0) >= 4 for c in self.drawn_cards)
        if has_4star:
            return any(core.can_card_awaken(c) for c in self.drawn_cards if c.get("star_num", 0) >= 4)
        return len(self.drawn_cards) == 1 and core.can_card_awaken(self.drawn_cards[0])

    def bind_pull_result(
        self,
        drawn: list[dict],
        pickup_cfg: dict | None = None,
        pull_count: int = 1,
        banner_type: str = "normal",
        mode_note: str | None = None,
        grid_tag: str = "",
        pity_info: dict | None = None,
        grid_pair: tuple[bytes | None, str | None] = (None, None),
    ):
        self._bound = True
        self.drawn_cards = [dict(c) for c in (drawn or [])]
        self.result_pickup_cfg = dict(pickup_cfg or {})
        self.result_pull_count = pull_count
        self.result_banner_type = banner_type
        self.result_mode_note = mode_note
        self.result_grid_tag = grid_tag
        if pity_info is not None:
            self.pity_info = pity_info
        self._cached_grid_pair = grid_pair
        self.illust_mode = "normal"
        self._refresh_components()

    def _restore_from_message(self, interaction: discord.Interaction):
        msg = getattr(interaction, "message", None)
        embeds = getattr(msg, "embeds", None) or []
        blob = "\n".join(
            f"{getattr(e, 'title', '') or ''}\n{getattr(getattr(e, 'footer', None), 'text', '') or ''}"
            for e in embeds
        )
        if "✨ [특훈 후]" in blob or "✨ 특훈 후 일러스트" in blob or "After Training" in blob:
            self.illust_mode = "after_training"
        else:
            self.illust_mode = "normal"
        self._refresh_components()

    def _refresh_components(self):
        if self.skip_anim:
            self.toggle_skip_anim.label = "⏭️ 스킵: ON"
            self.toggle_skip_anim.style = discord.ButtonStyle.success
        else:
            self.toggle_skip_anim.label = "✨ 스킵: OFF"
            self.toggle_skip_anim.style = discord.ButtonStyle.secondary

        badges = int(self.pity_info.get("badges", 0)) if self.pity_info else None
        ceil_cost = int(self.pity_info.get("ceiling_cost", core.GACHA_CEILING_BADGE_COST))
        if badges is not None:
            self.open_ceiling_exchange.label = f"🏅 천장({badges}/{ceil_cost})"[:80]
            self.open_ceiling_exchange.style = (
                discord.ButtonStyle.success if badges >= ceil_cost else discord.ButtonStyle.secondary
            )
        else:
            self.open_ceiling_exchange.label = "🏅 천장교환(200)"
            self.open_ceiling_exchange.style = discord.ButtonStyle.secondary

        tickets = int(self.pity_info.get("select_tickets", 0)) if self.pity_info else None
        if tickets is not None:
            self.open_select_list.label = f"🎟️ 셀렉트({tickets})"[:80]
            self.open_select_list.style = (
                discord.ButtonStyle.success if tickets > 0 else discord.ButtonStyle.secondary
            )
        else:
            self.open_select_list.label = "🎟️ 셀렉트리스트"
            self.open_select_list.style = discord.ButtonStyle.secondary

        bday_chars = core.get_today_birthday_characters()
        if bday_chars:
            names = ", ".join(b["char_name"].split()[-1] for b in bday_chars)
            self.birthday_free_pull.label = f"🎂 [{names}] 생일 무료 단차!"[:80]
        else:
            if self.birthday_free_pull in self.children:
                self.remove_item(self.birthday_free_pull)

        show_illust_btns = (not self._bound) or self._has_awakenable_result()
        if show_illust_btns:
            if self.normal_illust_btn not in self.children:
                self.add_item(self.normal_illust_btn)
            if self.trained_illust_btn not in self.children:
                self.add_item(self.trained_illust_btn)
            self.normal_illust_btn.disabled = (self.illust_mode == "normal")
            self.trained_illust_btn.disabled = (self.illust_mode == "after_training")
        else:
            if self.normal_illust_btn in self.children:
                self.remove_item(self.normal_illust_btn)
            if self.trained_illust_btn in self.children:
                self.remove_item(self.trained_illust_btn)

        self.banner_select.options = [
            discord.SelectOption(
                label="🌟 일반 / 현재 픽업 가챠 (★4 3.0%)",
                value="normal",
                description=core.BANNER_CONFIGS["normal"]["desc"][:100],
                default=(self.banner_type == "normal"),
            ),
            discord.SelectOption(
                label="🎊 컬러풀 페스티벌 (★4 2배 · 6.0%!)",
                value="fes",
                description=core.BANNER_CONFIGS["fes"]["desc"][:100],
                default=(self.banner_type == "fes"),
            ),
            discord.SelectOption(
                label="🎂 생일 / 기념일 스페셜 가챠 (생일 UP!)",
                value="birthday",
                description=core.BANNER_CONFIGS["birthday"]["desc"][:100],
                default=(self.banner_type == "birthday"),
            ),
        ]

    async def _handle_repull(self, interaction: discord.Interaction, pull_count: int):
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                "❌ 가챠를 실행한 본인만 재뽑기 버튼을 사용할 수 있습니다. `/설정` (`🎮 미니게임` ➔ `🎰 프로세카 뽑기`)에서 직접 뽑아보세요!",
                ephemeral=True,
            )
            return
        if not self.user:
            self.user = interaction.user
        if not await ensure_proseka_registered(interaction, interaction.guild_id or self.guild_id or 0):
            return
        can_pull, rem = check_and_update_gacha_cooldown(interaction.user.id, skip_anim=self.skip_anim)
        if not can_pull:
            await core.safe_send_response(
                interaction,
                content=f"⏳ **봇의 원활한 서비스를 위해, 뽑기 쿨타임입니다!** `{rem:.1f}초` 후에 다시 눌러주세요.",
                ephemeral=True
            )
            return

        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        pickup_cfg = core.as_dict(data.get("gacha_pickup")) or core.DEFAULT_CONFIG["gacha_pickup"]
        active_banner = core.get_active_proseka_banner(pickup_cfg)
        is_owner = await _is_interaction_bot_owner(interaction)
        effective_banner = self.banner_type if is_owner else active_banner
        guild_id = interaction.guild_id or self.guild_id or 0

        drawn, pity_info = await asyncio.to_thread(
            core.execute_real_proseka_pull, guild_id, interaction.user.id, pickup_cfg, pull_count, effective_banner
        )
        if not drawn:
            await interaction.followup.send("❌ 한국 서버 캐릭터 DB를 불러오지 못했습니다.", ephemeral=True)
            return

        new_view = GachaPullAgainView(
            interaction.user,
            banner_type=effective_banner,
            skip_anim=self.skip_anim,
            guild_id=guild_id,
            pity_info=pity_info,
        )
        await send_gacha_pull_result(
            interaction,
            drawn,
            pickup_cfg,
            pull_count,
            new_view,
            banner_type=effective_banner,
            skip_anim=self.skip_anim,
            pity_info=pity_info,
        )

    @discord.ui.button(label="🎵 1회 뽑기", style=discord.ButtonStyle.primary, row=0)
    async def pull_one_more(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_repull(interaction, 1)

    @discord.ui.button(label="🌈 10회 뽑기", style=discord.ButtonStyle.success, row=0)
    async def pull_ten_more(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_repull(interaction, 10)

    @discord.ui.button(label="✨ 스킵: OFF", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_skip_anim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 가챠를 실행한 본인만 연출 설정을 바꿀 수 있습니다.", ephemeral=True)
            return
        if not self.user:
            self.user = interaction.user
        self.skip_anim = not self.skip_anim
        self._refresh_components()
        await core.safe_edit_response(interaction, view=self)
        state_txt = "**ON (결과 즉시 표시)**" if self.skip_anim else "**OFF (다단계 승격 & 대사 선공개 연출 보기)**"
        await core.safe_send_response(interaction, f"⚙️ 뽑기 연출 스킵 설정이 {state_txt}(으)로 변경되었습니다.", ephemeral=True)

    @discord.ui.button(label="🏅 천장교환(200)", style=discord.ButtonStyle.secondary, row=0)
    async def open_ceiling_exchange(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        view = GachaCeilingExchangeView(interaction.user, guild_id=guild_id)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @discord.ui.button(label="🎟️ 셀렉트리스트", style=discord.ButtonStyle.secondary, row=0)
    async def open_select_list(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        view = SelectListGachaView(interaction.user, guild_id=guild_id, skip_anim=self.skip_anim)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @discord.ui.button(label="🎒 보관함", style=discord.ButtonStyle.secondary, row=1)
    async def open_inventory(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id or 0)
        u_key = str(interaction.user.id)
        user_cards_dict = core.safe_get_dict(data, "gacha_users", g_key, u_key, "cards")
        view = MyInventoryView(interaction.user, list(user_cards_dict.values()), items_per_page=10, guild_id=interaction.guild_id or 0)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @discord.ui.button(label="💎 중복변환", style=discord.ButtonStyle.secondary, row=1)
    async def open_duplicate_converter(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild_id or 0
        preview = await asyncio.to_thread(core.preview_duplicate_cards, guild_id, interaction.user.id)
        view = DuplicateConvertConfirmView(guild_id, interaction.user, preview)
        await core.safe_send_response(interaction, embed=view.build_preview_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="📖 도감", style=discord.ButtonStyle.secondary, row=1)
    async def open_pokedex(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        stats = await asyncio.to_thread(core.get_card_pokedex_stats, guild_id, interaction.user.id)
        view = CardPokedexView(interaction.user, stats, guild_id=guild_id)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @discord.ui.button(label="🚩 캐랭·깃발", style=discord.ButtonStyle.secondary, row=1)
    async def open_character_rank(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        view = CharacterRankView(interaction.user, guild_id=guild_id)
        embed, file_obj = await view.build_embed_and_file()
        if file_obj:
            await interaction.followup.send(embed=embed, file=file_obj, view=view, wait=True)
        else:
            await interaction.followup.send(embed=embed, view=view, wait=True)

    @discord.ui.button(label="🏆 MR돌파", style=discord.ButtonStyle.secondary, row=1)
    async def open_master_rank(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        view = MasterRankView(interaction.user, guild_id=interaction.guild_id or 0)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @discord.ui.select(
        placeholder="🔒 [봇주 전용] 재뽑기 배너 변경 (일반 / 컬러풀 페스티벌 / 생일)...",
        row=2,
        options=[discord.SelectOption(label="일반", value="normal")]
    )
    async def banner_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not await _is_interaction_bot_owner(interaction):
            await core.safe_send_response(
                interaction,
                "❌ 프로세카 가챠 배너 변경은 **봇주인(Bot Owner)** 만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 가챠를 실행한 본인만 배너를 바꿀 수 있습니다.", ephemeral=True)
            return
        if not self.user:
            self.user = interaction.user
        await core.safe_defer(interaction)
        self.banner_type = select.values[0]
        self._refresh_components()
        b_cfg = core.BANNER_CONFIGS.get(self.banner_type, core.BANNER_CONFIGS["normal"])
        await core.safe_edit_response(interaction, view=self)
        await core.safe_send_response(
            interaction,
            f"🎰 다음 뽑기 배너가 **`{b_cfg['name']}`**(으)로 변경되었습니다!\n└ *{b_cfg['desc']}*",
            ephemeral=True
        )

    @discord.ui.button(label="⚔️ 라이브", style=discord.ButtonStyle.primary, row=3)
    async def open_sekai_live(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        view = SekaiLiveView(interaction.user, guild_id=interaction.guild_id or 0)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @discord.ui.button(label="👗 의상실", style=discord.ButtonStyle.secondary, row=3)
    async def open_wardrobe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        view = CharacterCostumeWardrobeView(interaction.user, guild_id=interaction.guild_id or 0)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @discord.ui.button(label="🎂 생일 무료 단차!", style=discord.ButtonStyle.danger, row=3)
    async def birthday_free_pull(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_proseka_registered(interaction):
            return
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        ok, msg, bday_chars, drawn = await asyncio.to_thread(
            core.draw_birthday_free_pull, guild_id, interaction.user.id
        )
        if not ok:
            await interaction.followup.send(f"❌ {msg}", ephemeral=True)
            return
        data = await asyncio.to_thread(core.load_data)
        pickup_cfg = core.as_dict(data.get("gacha_pickup")) or core.DEFAULT_CONFIG["gacha_pickup"]
        pity_info = core.get_user_gacha_pity_state(guild_id, interaction.user.id, data=data)
        pity_info["added_badges"] = len(drawn)
        is_owner = await _is_interaction_bot_owner(interaction)
        next_banner = self.banner_type if is_owner else core.get_active_proseka_banner(pickup_cfg)
        new_view = GachaPullAgainView(
            interaction.user,
            banner_type=next_banner,
            skip_anim=self.skip_anim,
            guild_id=guild_id,
            pity_info=pity_info,
        )
        await send_gacha_pull_result(
            interaction,
            drawn,
            pickup_cfg,
            1,
            new_view,
            banner_type="birthday",
            skip_anim=self.skip_anim,
            mode_note=msg,
            pity_info=pity_info,
        )


    async def _switch_result_illust(self, interaction: discord.Interaction, target_mode: str):
        await core.safe_defer(interaction)
        self.illust_mode = "after_training" if target_mode == "after_training" else "normal"
        self._refresh_components()

        if self.drawn_cards:
            embeds, file_specs, card_embed_pairs, grid_pair = await _build_gacha_result_payload(
                self.drawn_cards,
                self.result_pickup_cfg or core.DEFAULT_CONFIG["gacha_pickup"],
                self.result_pull_count or len(self.drawn_cards),
                self.user or interaction.user,
                banner_type=self.result_banner_type or self.banner_type,
                mode_note=self.result_mode_note,
                grid_tag=self.result_grid_tag,
                pity_info=self.pity_info,
                illust_mode=self.illust_mode,
                prebuilt_grid=self._cached_grid_pair,
            )
            self._cached_grid_pair = grid_pair
            files = [discord.File(io.BytesIO(b), filename=fn) for b, fn in file_specs]
            try:
                await interaction.edit_original_response(embeds=embeds, attachments=files, view=self)
            except discord.HTTPException:
                for c_emb, c, f_mode in card_embed_pairs:
                    c_emb.set_image(url=core.get_proseka_card_image_url(c, f_mode))
                await interaction.edit_original_response(embeds=embeds, view=self)
            return

        # 봇 재시작 후 복원된 메시지에서도 임베드 이미지를 즉시 전환
        orig_embeds = list(getattr(interaction.message, "embeds", None) or [])
        if not orig_embeds:
            await core.safe_edit_response(interaction, view=self)
            return
        new_embeds: list[discord.Embed] = []
        target_indices = range(1, len(orig_embeds)) if len(orig_embeds) > 1 else range(0, 1)
        for idx, e in enumerate(orig_embeds):
            cloned = discord.Embed.from_dict(e.to_dict())
            if idx in target_indices:
                matched = _resolve_proseka_card_from_embed(e)
                if matched and core.can_card_awaken(matched):
                    if cloned.title:
                        cloned.title = (
                            cloned.title.replace("🌸 [특훈 전] ", "✨ [특훈 후] ")
                            if self.illust_mode == "after_training"
                            else cloned.title.replace("✨ [특훈 후] ", "🌸 [특훈 전] ")
                        )
                    cloned.set_image(url=core.get_proseka_card_image_url(matched, self.illust_mode))
            new_embeds.append(cloned)
        await interaction.edit_original_response(embeds=new_embeds, view=self)

    @discord.ui.button(label="🌸 특훈 전", style=discord.ButtonStyle.secondary, row=3)
    async def normal_illust_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch_result_illust(interaction, "normal")

    @discord.ui.button(label="✨ 특훈 후", style=discord.ButtonStyle.primary, row=3)
    async def trained_illust_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch_result_illust(interaction, "after_training")


def _resolve_proseka_card_from_embed(emb: discord.Embed | None) -> dict | None:
    """임베드 텍스트(ID 또는 [카드명] 캐릭터명)로부터 프로세카 카드 메타데이터를 복원합니다."""
    if emb is None:
        return None
    import re
    search_blob = "\n".join(
        [emb.title or "", emb.description or "", getattr(emb.footer, "text", "") or ""]
        + [f"{f.name or ''} {f.value or ''}" for f in getattr(emb, "fields", [])]
    )
    m_id = re.search(r"(?:ID[:\s]*`?|도감 ID\s*`?)(\d+)", search_blob)
    if m_id:
        found = core.get_proseka_card_by_id(m_id.group(1))
        if isinstance(found, dict):
            return dict(found)
    for c in core.PROSEKA_KR_CARDS:
        pfx = c.get("prefix")
        cname = c.get("char_name")
        if pfx and cname and f"[{pfx}]" in search_blob and cname in search_blob:
            return dict(c)
    return None


class SimpleCardIllustToggleView(core.SafeView):
    """단일 카드 임베드(도감·천장·교환·선물·덱·프로필 등)에서 기본 특훈 전 표시 후 특훈 전·후를 버튼으로 전환하는 공용 뷰"""

    def __init__(self, card: dict | None = None, initial_mode: str = "normal"):
        super().__init__(timeout=600)
        self.card = dict(card or {})
        self.has_awakening = core.can_card_awaken(self.card) if self.card else True
        self.current_mode = "after_training" if (self.has_awakening and initial_mode == "after_training") else "normal"
        self.update_buttons()

    def _restore_from_message(self, interaction: discord.Interaction):
        msg = getattr(interaction, "message", None)
        embeds = getattr(msg, "embeds", None) or []
        if embeds and (not self.card or "id" not in self.card):
            found = _resolve_proseka_card_from_embed(embeds[0])
            if found:
                self.card = found
                self.has_awakening = core.can_card_awaken(self.card)
        if embeds:
            e0 = embeds[0]
            blob = f"{e0.title or ''}\n{e0.description or ''}\n{getattr(e0.footer, 'text', '') or ''}"
            if "✨ [특훈 후]" in blob or "특훈 후 (After Training)" in blob or "✨ 특훈 후 일러스트" in blob:
                self.current_mode = "after_training"
            else:
                self.current_mode = "normal"
        self.update_buttons()

    def update_buttons(self):
        if not self.has_awakening:
            self.normal_btn.disabled = True
            self.awakened_btn.disabled = True
        else:
            self.normal_btn.disabled = (self.current_mode == "normal")
            self.awakened_btn.disabled = (self.current_mode == "after_training")

    async def _switch_mode(self, interaction: discord.Interaction, target_mode: str):
        if not self.card or "id" not in self.card:
            self._restore_from_message(interaction)
        if not self.card or "id" not in self.card:
            await core.safe_send_response(interaction, "❌ 카드 정보를 찾을 수 없습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        self.has_awakening = core.can_card_awaken(self.card)
        self.current_mode = "after_training" if (self.has_awakening and target_mode == "after_training") else "normal"
        self.update_buttons()

        orig_embeds = list(getattr(interaction.message, "embeds", None) or [])
        if not orig_embeds:
            await core.safe_edit_response(interaction, view=self)
            return

        cloned = discord.Embed.from_dict(orig_embeds[0].to_dict())
        if cloned.title:
            if self.current_mode == "after_training":
                if "🌸 [특훈 전] " in cloned.title:
                    cloned.title = cloned.title.replace("🌸 [특훈 전] ", "✨ [특훈 후] ")
            else:
                if "✨ [특훈 후] " in cloned.title:
                    cloned.title = cloned.title.replace("✨ [특훈 후] ", "🌸 [특훈 전] ")

        old_footer = getattr(cloned.footer, "text", None) or ""
        if "특훈 전" in old_footer or "특훈 후" in old_footer:
            new_footer = (
                old_footer.replace("🌸 특훈 전 (Normal)", "✨ 특훈 후 (After Training)").replace("특훈 전", "특훈 후")
                if self.current_mode == "after_training"
                else old_footer.replace("✨ 특훈 후 (After Training)", "🌸 특훈 전 (Normal)").replace("특훈 후", "특훈 전")
            )
            cloned.set_footer(text=new_footer)

        img_bytes, fn = await asyncio.to_thread(core.fetch_proseka_card_image_bytes, self.card, self.current_mode)
        if img_bytes and fn:
            safe_fn = f"card_toggle_{self.current_mode}_{fn}"
            cloned.set_image(url=f"attachment://{safe_fn}")
            await interaction.edit_original_response(
                embed=cloned,
                attachments=[discord.File(io.BytesIO(img_bytes), filename=safe_fn)],
                view=self,
            )
        else:
            cloned.set_image(url=core.get_proseka_card_image_url(self.card, self.current_mode))
            await interaction.edit_original_response(embed=cloned, attachments=[], view=self)

    @discord.ui.button(label="🌸 특훈 전", style=discord.ButtonStyle.secondary, row=0)
    async def normal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch_mode(interaction, "normal")

    @discord.ui.button(label="✨ 특훈 후", style=discord.ButtonStyle.primary, row=0)
    async def awakened_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch_mode(interaction, "after_training")


class GachaCeilingExchangeView(core.SafeView):
    """가챠 배지 200개로 원하는 ★4 / 🎀생일 카드를 확정 교환하는 천장 교환소 뷰"""

    def __init__(self, user: discord.User | None = None, guild_id: int = 0):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = guild_id
        self.unit_filter = "PICKUP"
        self.unowned_only = False
        self.page = 0
        self.per_page = 15
        self.selected_card_id: str | None = None
        self.status_note: str = ""
        self._lock = asyncio.Lock()

        self.pickup_cfg: dict = {}
        self.banner_type: str = "normal"
        self.pity_state: dict = {}
        self.owned_map: dict = {}
        self.pickup_cards: list[dict] = []
        self.filtered_cards: list[dict] = []

        self._reload_state()
        if not self.pickup_cards:
            self.unit_filter = "ALL"
            self._reload_state()

    def _reload_state(self):
        data = core.load_data()
        self.pickup_cfg = core.as_dict(data.get("gacha_pickup")) or core.DEFAULT_CONFIG["gacha_pickup"]
        self.banner_type = core.get_active_proseka_banner(self.pickup_cfg)
        uid = self.user.id if self.user else 0
        self.pity_state = core.get_user_gacha_pity_state(self.guild_id, uid, data=data)
        self.owned_map = core.safe_get_dict(data, "gacha_users", str(self.guild_id or 0), str(uid), "cards")
        self.pickup_cards, pool = core.get_ceiling_exchange_pool(
            self.pickup_cfg, banner_type=self.banner_type, unit_filter=self.unit_filter
        )
        if self.unowned_only:
            pool = [c for c in pool if str(c.get("id")) not in self.owned_map]
        self.filtered_cards = pool
        total_pages = max(1, (len(self.filtered_cards) + self.per_page - 1) // self.per_page)
        self.page = max(0, min(self.page, total_pages - 1))
        if self.selected_card_id and not any(str(c.get("id")) == self.selected_card_id for c in self.filtered_cards):
            self.selected_card_id = None
        if not self.selected_card_id and self.filtered_cards:
            self.selected_card_id = str(self.filtered_cards[0]["id"])
        self._refresh_components()

    def _refresh_components(self):
        filter_opts = [
            discord.SelectOption(
                label=f"🎯 현재 픽업 ★4/생일 ({len(self.pickup_cards)}종)",
                value="PICKUP",
                default=(self.unit_filter == "PICKUP"),
            ),
            discord.SelectOption(
                label="🌟 전체 ★4/생일 카드",
                value="ALL",
                default=(self.unit_filter == "ALL"),
            ),
        ]
        for u in core.UNIT_ORDER:
            u_em = core.UNIT_EMOJIS.get(u, "🎵")
            filter_opts.append(
                discord.SelectOption(label=f"{u_em} {u}", value=u, default=(self.unit_filter == u))
            )
        self.filter_select.options = filter_opts

        start = self.page * self.per_page
        page_items = self.filtered_cards[start : start + self.per_page]
        if page_items:
            opts = []
            for c in page_items:
                cid_str = str(c["id"])
                owned_c = self.owned_map.get(cid_str)
                own_tag = f"보유 {owned_c.get('count', 1)}장" if isinstance(owned_c, dict) else "✨ 미보유"
                p_tag = "🎯" if c.get("is_pickup") else ("🎂" if c.get("rarity_type") == "rarity_birthday" else "🌟")
                lbl = f"{p_tag} [{c.get('prefix', '')}] {c.get('char_name', '')}"[:95]
                desc = f"{c.get('unit', '')} · {c.get('limit_label', '통상')} · {own_tag}"[:100]
                opts.append(
                    discord.SelectOption(label=lbl, value=cid_str, description=desc, default=(cid_str == self.selected_card_id))
                )
            self.card_select.options = opts
            self.card_select.disabled = False
        else:
            self.card_select.options = [discord.SelectOption(label="조건에 맞는 카드가 없습니다", value="NONE")]
            self.card_select.disabled = True

        total_pages = max(1, (len(self.filtered_cards) + self.per_page - 1) // self.per_page)
        self.prev_btn.disabled = (self.page <= 0)
        self.next_btn.disabled = (self.page >= total_pages - 1)
        self.page_btn.label = f"{self.page + 1} / {total_pages}"
        self.unowned_toggle_btn.label = "✨ 미보유만: ON" if self.unowned_only else "✨ 미보유만: OFF"
        self.unowned_toggle_btn.style = discord.ButtonStyle.success if self.unowned_only else discord.ButtonStyle.secondary

        badges = int(self.pity_state.get("badges", 0))
        cost = int(self.pity_state.get("ceiling_cost", core.GACHA_CEILING_BADGE_COST))
        can_ex = (badges >= cost) and bool(self.selected_card_id) and (self.selected_card_id != "NONE")
        self.exchange_btn.disabled = not can_ex
        if can_ex:
            self.exchange_btn.label = f"🏅 {cost}배지로 선택한 카드 확정 교환!"
            self.exchange_btn.style = discord.ButtonStyle.success
        else:
            rem = max(0, cost - badges)
            self.exchange_btn.label = f"🔒 배지 부족 ({rem}개 더 필요)" if badges < cost else "🏅 교환할 카드를 선택하세요"
            self.exchange_btn.style = discord.ButtonStyle.secondary

    def build_embed(self) -> discord.Embed:
        badges = int(self.pity_state.get("badges", 0))
        cost = int(self.pity_state.get("ceiling_cost", core.GACHA_CEILING_BADGE_COST))
        u_name = self.user.display_name if self.user else "유저"

        selected_card = (
            next((c for c in self.filtered_cards if str(c.get("id")) == self.selected_card_id), None)
            if self.selected_card_id
            else None
        )

        filter_name = (
            "현재 픽업" if self.unit_filter == "PICKUP"
            else ("전체" if self.unit_filter == "ALL" else self.unit_filter)
        )
        if self.unowned_only:
            filter_name += " · 미보유만"

        desc_lines = [
            f"🎯 **필터:** `{filter_name}` (`{len(self.filtered_cards):,}종`) · **누적 교환:** `{self.pity_state.get('ceiling_count', 0):,}회`"
        ]
        if self.status_note:
            desc_lines.append(f"\n> {self.status_note}")

        embed = discord.Embed(
            title=f"🏅 {u_name}님의 천장 교환소 ({cost}배지)",
            description="\n".join(desc_lines),
            color=discord.Color.gold() if badges >= cost else discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST),
        )
        gauge_text, badge_text = core.format_gacha_pity_display(self.pity_state)
        embed.add_field(name=f"🏅 가챠 배지 천장 ({cost}개)", value=badge_text, inline=False)
        embed.add_field(name="⚡ 가챠 보너스 게이지 (50pt ★4 · 100pt 픽업 ★4)", value=gauge_text, inline=False)

        if selected_card:
            cid_str = str(selected_card["id"])
            owned_c = self.owned_map.get(cid_str)
            own_txt = f"보유 중 (`{owned_c.get('count', 1)}장`)" if isinstance(owned_c, dict) else "✨ **미보유 (NEW)**"
            cos = core.get_costume_for_card(selected_card.get("id"))
            cos_line = f"\n👗 3D 의상: `{cos['name']}`" if cos else ""
            raw_q = _get_card_preview_quote(selected_card)
            sel_val = (
                f"**{selected_card.get('char_name')}** [{selected_card.get('prefix')}]\n"
                f"└ `{selected_card.get('rarity_label', '★★★★')}` · `{selected_card.get('limit_label', '통상')}` · {own_txt}\n"
                f"└ 🏷️ `{selected_card.get('unit')}` · {selected_card.get('attr')}{cos_line}\n"
                f"> 💬 *\"{raw_q}\"*"
            )
            embed.add_field(name="🎯 선택된 교환 대상 카드", value=sel_val[:1024], inline=False)
            embed.set_thumbnail(url=core.get_proseka_card_image_url(selected_card, "auto"))
        else:
            embed.add_field(
                name="🎯 선택된 교환 대상 카드",
                value="📭 조건에 맞는 카드가 없습니다. 아래 필터를 변경해 주세요.",
                inline=False,
            )

        embed.set_footer(text=f"1회 뽑기당 배지 +1 · {cost}배지로 원하는 ★4/생일 카드 1장 확정 교환")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await super().interaction_check(interaction)
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 천장 교환소를 연 본인만 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.select(placeholder="🎯 교환 풀 필터 (현재 픽업 / 전체 / 유닛별)...", row=0, options=[discord.SelectOption(label="전체", value="ALL")])
    async def filter_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await core.safe_defer(interaction)
        self.unit_filter = select.values[0]
        self.page = 0
        self.selected_card_id = None
        self.status_note = ""
        await asyncio.to_thread(self._reload_state)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.select(placeholder="🌟 교환할 ★4 / 🎀생일 카드를 선택하세요...", row=1, options=[discord.SelectOption(label="로딩중", value="NONE")])
    async def card_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        if val == "NONE":
            await core.safe_defer(interaction)
            return
        await core.safe_defer(interaction)
        self.selected_card_id = val
        self.status_note = ""
        self._refresh_components()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary, row=2)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        if self.page > 0:
            self.page -= 1
            self._refresh_components()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.secondary, disabled=True, row=2)
    async def page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary, row=2)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        total_pages = max(1, (len(self.filtered_cards) + self.per_page - 1) // self.per_page)
        if self.page < total_pages - 1:
            self.page += 1
            self._refresh_components()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="✨ 미보유만: OFF", style=discord.ButtonStyle.secondary, row=2)
    async def unowned_toggle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.unowned_only = not self.unowned_only
        self.page = 0
        self.selected_card_id = None
        await asyncio.to_thread(self._reload_state)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🏅 200배지로 확정 교환!", style=discord.ButtonStyle.success, row=3)
    async def exchange_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._lock.locked():
            await core.safe_send_response(interaction, "⏳ 교환을 처리 중입니다. 잠시만 기다려 주세요.", ephemeral=True)
            return
        async with self._lock:
            if not self.selected_card_id or self.selected_card_id == "NONE":
                await core.safe_send_response(interaction, "❌ 먼저 교환할 카드를 선택해 주세요!", ephemeral=True)
                return
            if not await ensure_proseka_registered(interaction, self.guild_id):
                return
            await core.safe_defer(interaction)
            ok, msg, info = await asyncio.to_thread(
                core.exchange_gacha_ceiling_badge, self.guild_id, interaction.user.id, self.selected_card_id
            )
            if not ok:
                self.status_note = f"❌ {msg}"
                await asyncio.to_thread(self._reload_state)
                await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
                return

            card = info["card"]
            self.status_note = f"✅ {msg} (남은 배지: `{info['remaining_badges']:,}개`)"
            await asyncio.to_thread(self._reload_state)
            await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

            # 축하 결과 & 고화질 공식 일러스트(특훈 전 · 특훈 후) 별도 출력
            new_badge = " · ✨ **NEW**" if info.get("is_new") else ""
            cos = core.get_costume_for_card(card.get("id"))
            raw_q = _get_card_preview_quote(card)
            can_train = core.can_card_awaken(card)
            stage_tag = "🌸 [특훈 전] " if can_train else ""
            cele_embed = discord.Embed(
                title=f"🏅 천장 교환 완료 — {stage_tag}[{card.get('prefix')}] {card.get('char_name')}"[:256],
                description=(
                    f"🎉 {interaction.user.mention}님이 **가챠 배지** `{core.GACHA_CEILING_BADGE_COST}개`로 확정 영입했습니다!{new_badge}\n\n"
                    f"> 💬 *\"{raw_q}\"*"
                ),
                color=discord.Color.from_rgb(255, 105, 180),
                timestamp=datetime.datetime.now(core.KST),
            )
            cele_embed.add_field(name="🏷️ 유닛", value=f"`{card.get('unit')}`", inline=True)
            cele_embed.add_field(name="✨ 속성 / 분류", value=f"{card.get('attr')} · `{card.get('limit_label', '통상')}`", inline=True)
            cele_embed.add_field(
                name="🏅 남은 배지",
                value=f"**`{info['remaining_badges']:,}개`** *(누적 `{info['ceiling_count']}회`)*",
                inline=True,
            )
            if cos:
                cele_embed.add_field(name="👗 3D 의상 획득", value=f"`{cos['name']}`", inline=False)

            cele_view = SimpleCardIllustToggleView(card, initial_mode="normal") if can_train else None
            if can_train:
                cele_embed.set_footer(text="프로세카 ★4 🌸 특훈 전 (Normal) 공식 일러스트 • 하단 버튼으로 특훈 전·후 전환")
            else:
                cele_embed.set_footer(text="프로세카 🎂 생일 한정 공식 일러스트")

            img_bytes, fn = await asyncio.to_thread(core.fetch_proseka_card_image_bytes, card, "normal")
            cele_file = None
            if img_bytes and fn:
                safe_n_fn = f"ceil_norm_{fn}"
                cele_embed.set_image(url=f"attachment://{safe_n_fn}")
                cele_file = discord.File(io.BytesIO(img_bytes), filename=safe_n_fn)
            else:
                cele_embed.set_image(url=core.get_proseka_card_image_url(card, "normal"))

            send_kw = {"embed": cele_embed}
            if cele_view is not None:
                send_kw["view"] = cele_view
            try:
                if cele_file is not None:
                    await interaction.followup.send(file=cele_file, **send_kw)
                else:
                    await interaction.followup.send(**send_kw)
            except discord.HTTPException:
                cele_embed.set_image(url=core.get_proseka_card_image_url(card, "normal"))
                await interaction.followup.send(**send_kw)


class SelectListGachaView(core.SafeView):
    """봇주가 지급한 특수 티켓 1장으로 원하는 ★4 카드 10장을 직접 골라 확정 10연차를 돌리는 셀렉트 리스트 가챠 뷰"""

    def __init__(self, user: discord.User | None = None, guild_id: int = 0, skip_anim: bool = False):
        super().__init__(timeout=600)
        self.user = user
        self.guild_id = guild_id
        self.skip_anim = bool(skip_anim)
        self.unit_filter = "ALL"
        self.unowned_only = False
        self.page = 0
        self.per_page = 15
        self.selected_ids: list[str] = []
        self.status_note: str = ""
        self._lock = asyncio.Lock()

        self.tickets: int = 0
        self.owned_map: dict = {}
        self.all_star4: list[dict] = []
        self.filtered_cards: list[dict] = []
        self._reload_state()

    def _reload_state(self):
        data = core.load_data()
        uid = self.user.id if self.user else 0
        self.tickets = core.get_user_select_tickets(uid, data=data)
        self.owned_map = core.safe_get_dict(data, "gacha_users", str(self.guild_id or 0), str(uid), "cards")
        self.all_star4 = [c for c in core.PROSEKA_KR_CARDS if c.get("rarity_type") == "rarity_4"]
        pool = list(self.all_star4)
        if self.unit_filter in core.UNIT_ORDER:
            pool = [c for c in pool if c.get("unit") == self.unit_filter]
        if self.unowned_only:
            pool = [c for c in pool if str(c.get("id")) not in self.owned_map]
        pool.sort(key=lambda x: (str(x.get("id")) in self.owned_map, x.get("char_id", 99), -x.get("id", 0)))
        self.filtered_cards = pool
        total_pages = max(1, (len(self.filtered_cards) + self.per_page - 1) // self.per_page)
        self.page = max(0, min(self.page, total_pages - 1))
        self._refresh_components()

    def _refresh_components(self):
        unit_opts = [
            discord.SelectOption(label=f"🌟 전체 ★4 카드 ({len(self.all_star4)}종)", value="ALL", default=(self.unit_filter == "ALL"))
        ]
        for u in core.UNIT_ORDER:
            unit_opts.append(
                discord.SelectOption(label=f"{core.UNIT_EMOJIS.get(u, '🎵')} {u}", value=u, default=(self.unit_filter == u))
            )
        self.unit_select.options = unit_opts

        start = self.page * self.per_page
        page_items = self.filtered_cards[start : start + self.per_page]
        sel_set = set(self.selected_ids)
        if page_items:
            opts = []
            for c in page_items:
                cid_str = str(c["id"])
                is_sel = cid_str in sel_set
                own_tag = "보유" if cid_str in self.owned_map else "✨미보유"
                mark = "✅" if is_sel else "☐"
                lbl = f"{mark} [{c.get('prefix', '')}] {c.get('char_name', '')}"[:95]
                desc = f"{c.get('unit', '')} · {c.get('limit_label', '통상')} · {own_tag}"[:100]
                opts.append(discord.SelectOption(label=lbl, value=cid_str, description=desc))
            self.card_multi_select.options = opts
            self.card_multi_select.min_values = 1
            self.card_multi_select.max_values = min(core.SELECT_LIST_REQUIRED_COUNT, len(opts))
            self.card_multi_select.disabled = False
        else:
            self.card_multi_select.options = [discord.SelectOption(label="조건에 맞는 ★4 카드가 없습니다", value="NONE")]
            self.card_multi_select.min_values = 1
            self.card_multi_select.max_values = 1
            self.card_multi_select.disabled = True

        total_pages = max(1, (len(self.filtered_cards) + self.per_page - 1) // self.per_page)
        self.prev_btn.disabled = (self.page <= 0)
        self.next_btn.disabled = (self.page >= total_pages - 1)
        self.page_btn.label = f"{self.page + 1}/{total_pages}"
        self.unowned_btn.label = "✨ 미보유만: ON" if self.unowned_only else "✨ 미보유만: OFF"
        self.unowned_btn.style = discord.ButtonStyle.success if self.unowned_only else discord.ButtonStyle.secondary

        req = core.SELECT_LIST_REQUIRED_COUNT
        cnt = len(self.selected_ids)
        can_pull = (self.tickets >= 1) and (cnt == req)
        self.pull_btn.disabled = not can_pull
        if self.tickets < 1:
            self.pull_btn.label = f"🔒 특수 티켓 부족 (0장 · {cnt}/{req})"
            self.pull_btn.style = discord.ButtonStyle.secondary
        elif cnt < req:
            self.pull_btn.label = f"🎟️ ★4 카드 선택 중 ({cnt}/{req}장)"
            self.pull_btn.style = discord.ButtonStyle.primary
        else:
            self.pull_btn.label = f"🎟️ 티켓 1장 사용 · 10연차 실행! ({cnt}/{req})"
            self.pull_btn.style = discord.ButtonStyle.success

        self.skip_btn.label = "⏭️ 스킵: ON" if self.skip_anim else "✨ 스킵: OFF"
        self.skip_btn.style = discord.ButtonStyle.success if self.skip_anim else discord.ButtonStyle.secondary

    def build_embed(self) -> discord.Embed:
        req = core.SELECT_LIST_REQUIRED_COUNT
        cnt = len(self.selected_ids)
        u_name = self.user.display_name if self.user else "유저"
        prog_bar = core.format_progress_bar(cnt, req, slots=10)
        filter_lbl = "전체 ★4" if self.unit_filter == "ALL" else self.unit_filter
        if self.unowned_only:
            filter_lbl += " · 미보유만"

        desc_lines = [
            f"직접 고른 **★4 카드 {req}장** 중 **최소 1장 100% 확정 출현!** *(1~9슬롯 픽업 UP · 배지 +10)*",
            f"🎯 **현재 필터:** `{filter_lbl}` (`{len(self.filtered_cards):,}종`)",
        ]
        if self.status_note:
            desc_lines.append(f"\n> {self.status_note}")

        embed = discord.Embed(
            title=f"🎟️ {u_name}님의 셀렉트 리스트 가챠",
            description="\n".join(desc_lines),
            color=discord.Color.from_rgb(255, 205, 86) if self.tickets > 0 else discord.Color.dark_grey(),
            timestamp=datetime.datetime.now(core.KST),
        )
        t_val = (
            f"**`{self.tickets:,}장`** ✨ *(즉시 실행 가능)*"
            if self.tickets > 0
            else "**`0장`** *(🔒 봇주인 지급 필요)*"
        )
        embed.add_field(name="🎟️ 보유 특수 티켓", value=t_val, inline=True)
        embed.add_field(
            name=f"📋 선택 진행도 ({cnt} / {req}장)",
            value=f"{prog_bar} **`{cnt}/{req}`**",
            inline=True,
        )

        if self.selected_ids:
            sel_lines = []
            for idx, cid_str in enumerate(self.selected_ids, start=1):
                c = core.get_proseka_card_by_id(cid_str)
                if not c:
                    continue
                own_tag = "" if cid_str in self.owned_map else " ✨`NEW`"
                sel_lines.append(
                    f"`{idx:02d}.` {core.UNIT_EMOJIS.get(c.get('unit'), '🌟')} **{c.get('char_name')}** [{c.get('prefix')}] · `{c.get('limit_label', '통상')}`{own_tag}"
                )
            embed.add_field(name="🌟 내 셀렉트 리스트 선택 목록", value="\n".join(sel_lines)[:1024], inline=False)
        else:
            embed.add_field(
                name="🌟 내 셀렉트 리스트 선택 목록",
                value="💡 아래 드롭다운에서 ★4를 고르거나 **`🎲 미보유 자동 10장 채우기`** 버튼을 눌러보세요!",
                inline=False,
            )

        embed.set_footer(text="드롭다운에서 여러 장 한꺼번에 추가·해제 가능 • 10장 선택 후 즉시 10연차")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await super().interaction_check(interaction)
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 셀렉트 리스트 가챠를 연 본인만 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.select(placeholder="🏷️ 유닛 필터 (전체 / 유닛별 ★4)...", row=0, options=[discord.SelectOption(label="전체", value="ALL")])
    async def unit_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await core.safe_defer(interaction)
        self.unit_filter = select.values[0]
        self.page = 0
        self.status_note = ""
        await asyncio.to_thread(self._reload_state)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.select(placeholder="🌟 ★4 카드를 골라 리스트에 추가/해제하세요 (다중 선택 가능)...", row=1, options=[discord.SelectOption(label="로딩중", value="NONE")])
    async def card_multi_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await core.safe_defer(interaction)
        req = core.SELECT_LIST_REQUIRED_COUNT
        added = 0
        removed = 0
        overflow = 0
        for val in select.values:
            if val == "NONE":
                continue
            if val in self.selected_ids:
                self.selected_ids.remove(val)
                removed += 1
            else:
                if len(self.selected_ids) < req:
                    self.selected_ids.append(val)
                    added += 1
                else:
                    overflow += 1
        parts = []
        if added:
            parts.append(f"`+{added}장` 추가")
        if removed:
            parts.append(f"`-{removed}장` 해제")
        if overflow:
            parts.append(f"⚠️ 최대 {req}장까지만 담을 수 있어 `{overflow}장` 제외됨")
        self.status_note = " / ".join(parts)
        self._refresh_components()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=2)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        if self.page > 0:
            self.page -= 1
            self._refresh_components()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.secondary, disabled=True, row=2)
    async def page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=2)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        total_pages = max(1, (len(self.filtered_cards) + self.per_page - 1) // self.per_page)
        if self.page < total_pages - 1:
            self.page += 1
            self._refresh_components()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="✨ 미보유만: OFF", style=discord.ButtonStyle.secondary, row=2)
    async def unowned_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.unowned_only = not self.unowned_only
        self.page = 0
        await asyncio.to_thread(self._reload_state)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🎲 미보유 10장 채우기", style=discord.ButtonStyle.primary, row=2)
    async def auto_fill_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        req = core.SELECT_LIST_REQUIRED_COUNT
        need = max(0, req - len(self.selected_ids))
        if need == 0:
            self.status_note = f"✅ 이미 {req}장이 모두 채워져 있습니다! 교체하려면 선택 초기화 후 다시 담아주세요."
        else:
            sel_set = set(self.selected_ids)
            filt_unowned = [str(c["id"]) for c in self.filtered_cards if str(c["id"]) not in sel_set and str(c["id"]) not in self.owned_map]
            filt_owned = [str(c["id"]) for c in self.filtered_cards if str(c["id"]) not in sel_set and str(c["id"]) in self.owned_map]
            random.shuffle(filt_unowned)
            random.shuffle(filt_owned)
            picks = (filt_unowned + filt_owned)[:need]
            if len(picks) < need:
                taken = sel_set | set(picks)
                all_unowned = [str(c["id"]) for c in self.all_star4 if str(c["id"]) not in taken and str(c["id"]) not in self.owned_map]
                all_owned = [str(c["id"]) for c in self.all_star4 if str(c["id"]) not in taken and str(c["id"]) in self.owned_map]
                random.shuffle(all_unowned)
                random.shuffle(all_owned)
                picks.extend((all_unowned + all_owned)[: need - len(picks)])
            self.selected_ids.extend(picks)
            self.status_note = f"🎲 미보유 ★4 우선으로 **{len(picks)}장**을 자동 채웠습니다! (`{len(self.selected_ids)}/{req}`)"
        self._refresh_components()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🎟️ 티켓 1장 사용 · 10연차 실행!", style=discord.ButtonStyle.success, row=3)
    async def pull_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._lock.locked():
            await core.safe_send_response(interaction, "⏳ 셀렉트 리스트 뽑기를 처리 중입니다!", ephemeral=True)
            return
        async with self._lock:
            if not await ensure_proseka_registered(interaction, self.guild_id):
                return
            can_pull, rem = check_and_update_gacha_cooldown(interaction.user.id, skip_anim=self.skip_anim)
            if not can_pull:
                await core.safe_send_response(
                    interaction,
                    f"⏳ **봇의 원활한 서비스를 위해, 뽑기 쿨타임입니다!** `{rem:.1f}초` 후에 다시 눌러주세요.",
                    ephemeral=True,
                )
                return
            await core.safe_defer(interaction)
            ok, msg, drawn, pity_info = await asyncio.to_thread(
                core.execute_select_list_gacha_pull, self.guild_id, interaction.user.id, list(self.selected_ids)
            )
            if not ok:
                self.status_note = f"❌ {msg}"
                await asyncio.to_thread(self._reload_state)
                await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
                return

            self.status_note = f"🎉 셀렉트 리스트 10연차 완료! (남은 특수 티켓: `{pity_info.get('remaining_tickets', 0)}장`)"
            await asyncio.to_thread(self._reload_state)
            await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

            data = await asyncio.to_thread(core.load_data)
            pickup_cfg = core.as_dict(data.get("gacha_pickup")) or core.DEFAULT_CONFIG["gacha_pickup"]
            active_banner = core.get_active_proseka_banner(pickup_cfg)
            repull_view = GachaPullAgainView(
                interaction.user,
                banner_type=active_banner,
                skip_anim=self.skip_anim,
                guild_id=self.guild_id,
                pity_info=pity_info,
            )
            await send_gacha_pull_result(
                interaction,
                drawn,
                pickup_cfg,
                10,
                repull_view,
                banner_type="select_list",
                skip_anim=self.skip_anim,
                mode_note=f"🎟️ **[셀렉트 리스트 가챠!]** 직접 선택한 ★4 10장 중 최소 1장 확정 출현! (남은 티켓: `{pity_info.get('remaining_tickets', 0)}장`)",
                grid_tag="셀렉트 리스트",
                pity_info=pity_info,
            )

    @discord.ui.button(label="🧹 선택 초기화", style=discord.ButtonStyle.danger, row=3)
    async def clear_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.selected_ids = []
        self.status_note = "🧹 선택한 셀렉트 리스트를 초기화했습니다."
        self._refresh_components()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="✨ 스킵: OFF", style=discord.ButtonStyle.secondary, row=3)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.skip_anim = not self.skip_anim
        self._refresh_components()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


class OwnerSelectTicketAmountModal(core.SafeModal, title="🎟️ [봇주 전용] 셀렉트 티켓 수량·사유 입력"):
    amount_input = discord.ui.TextInput(
        label="지급/회수 수량 (예: 1, 3, -1)",
        placeholder="양수 입력 시 지급, 음수 입력 시 회수 (예: 2)",
        required=True,
        max_length=10,
    )
    reason_input = discord.ui.TextInput(
        label="지급/회수 사유 (선택)",
        placeholder="예: 이벤트 우승 보상 / 주년 기념 선물",
        required=False,
        max_length=80,
    )

    def __init__(self, parent_view: "OwnerSelectTicketGrantView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        if not await _is_interaction_bot_owner(interaction):
            await core.safe_send_response(interaction, "❌ 봇주인 전용 기능입니다.", ephemeral=True)
            return
        if not self.parent_view.target_user:
            await core.safe_send_response(interaction, "❌ 먼저 대상 유저를 선택해 주세요.", ephemeral=True)
            return
        raw_val = (self.amount_input.value or "").strip()
        try:
            delta = int(raw_val)
        except ValueError:
            await core.safe_send_response(interaction, "❌ 수량은 정수로 입력해 주세요. (예: `1`, `5`, `-1`)", ephemeral=True)
            return
        if delta == 0 or abs(delta) > 999:
            await core.safe_send_response(interaction, "❌ 수량은 `-999 ~ +999` 사이의 0이 아닌 정수로 입력해 주세요.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True, thinking=True)
        t_user = self.parent_view.target_user
        ok, msg, after_cnt = await asyncio.to_thread(
            core.adjust_user_select_tickets,
            t_user.id,
            delta,
            getattr(t_user, "display_name", ""),
            interaction.user.id,
            self.reason_input.value or "",
        )
        self.parent_view.status_note = f"{'✅' if ok else '❌'} {t_user.mention} ➔ {msg}"
        updated_panel = False
        if self.parent_view._last_interaction is not None:
            try:
                await self.parent_view._last_interaction.edit_original_response(
                    embed=self.parent_view.build_embed(), view=self.parent_view
                )
                updated_panel = True
            except Exception:
                pass
        if not updated_panel and self.parent_view.message is not None:
            try:
                await self.parent_view.message.edit(embed=self.parent_view.build_embed(), view=self.parent_view)
            except Exception:
                pass
        await interaction.followup.send(f"🎟️ **{t_user.display_name}** ({t_user.mention}) — {msg}", ephemeral=True)


class OwnerSelectTicketGrantView(core.SafeView):
    """[봇주인 전용] 셀렉트 리스트 가챠 특수 티켓 지급·회수·보유자 관리 패널"""

    def __init__(self, user: discord.User | None = None):
        super().__init__(timeout=300)
        self.user = user
        self.owner_user = user
        self.target_user: discord.User | discord.Member | None = None
        self.status_note: str = ""
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await super().interaction_check(interaction)
        if not await _is_interaction_bot_owner(interaction):
            await core.safe_send_response(interaction, "❌ 이 제어판은 **봇주인(Bot Owner)** 만 사용할 수 있습니다.", ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        holders = core.list_select_ticket_holders()
        total_tickets = sum(h["tickets"] for h in holders)

        desc_lines = [
            "유저에게 **🎟️ 셀렉트 리스트 가챠 특수 티켓**을 지급·회수합니다.",
        ]
        if self.status_note:
            desc_lines.append(f"\n> {self.status_note}")

        embed = discord.Embed(
            title="🎟️ [봇주인 전용] 셀렉트 티켓 관리 패널",
            description="\n".join(desc_lines),
            color=discord.Color.from_rgb(255, 205, 86),
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.add_field(
            name="📊 전체 유통 현황",
            value=f"보유 유저 **`{len(holders):,}명`** · 총 **`{total_tickets:,}장`**",
            inline=True,
        )
        if self.target_user:
            cur_t = core.get_user_select_tickets(self.target_user.id)
            target_val = f"{self.target_user.mention} — **`{cur_t:,}장`**"
        else:
            target_val = "*아래 드롭다운에서 대상을 선택하세요*"
        embed.add_field(name="👤 선택된 대상", value=target_val, inline=True)

        if holders:
            top_lines = [f"• <@{h['uid']}> — **`{h['tickets']:,}장`**" for h in holders[:8]]
            if len(holders) > 8:
                top_lines.append(f"*…외 `{len(holders) - 8:,}명`*")
            embed.add_field(name="📋 현재 티켓 보유자", value="\n".join(top_lines)[:1024], inline=False)

        embed.set_footer(text="대상 선택 후 +1 / +3 / +5 / 직접입력 / -1 회수 • 사용처: /셀렉트리스트")
        return embed

    async def _quick_adjust(self, interaction: discord.Interaction, delta: int):
        if not self.target_user:
            await core.safe_send_response(interaction, "❌ 먼저 상단 드롭다운에서 대상 유저를 선택해 주세요!", ephemeral=True)
            return
        await core.safe_defer(interaction)
        ok, msg, _ = await asyncio.to_thread(
            core.adjust_user_select_tickets,
            self.target_user.id,
            delta,
            getattr(self.target_user, "display_name", ""),
            interaction.user.id,
            "봇주인 제어판 지급" if delta > 0 else "봇주인 제어판 회수",
        )
        self.status_note = f"{'✅' if ok else '❌'} {self.target_user.mention} ➔ {msg}"
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="👤 특수 티켓을 지급/회수할 유저를 선택하세요...", row=0)
    async def user_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        await core.safe_defer(interaction)
        picked = select.values[0]
        if isinstance(picked, (str, int)):
            uid = int(picked) if str(picked).isdigit() else 0
            resolved = (interaction.guild.get_member(uid) if interaction.guild and uid else None) or (
                interaction.client.get_user(uid) if uid else None
            )
            if resolved is None and uid and hasattr(interaction.client, "fetch_user"):
                try:
                    resolved = await interaction.client.fetch_user(uid)
                except Exception:
                    resolved = None
            picked = resolved or interaction.user
        self.target_user = picked
        self.status_note = f"👤 대상 유저가 {self.target_user.mention}(으)로 선택되었습니다."
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🎟️ +1장 지급", style=discord.ButtonStyle.success, row=1)
    async def give_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._quick_adjust(interaction, 1)

    @discord.ui.button(label="🎟️ +3장 지급", style=discord.ButtonStyle.success, row=1)
    async def give_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._quick_adjust(interaction, 3)

    @discord.ui.button(label="🎟️ +5장 지급", style=discord.ButtonStyle.primary, row=1)
    async def give_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._quick_adjust(interaction, 5)

    @discord.ui.button(label="✏️ 수량·사유 입력", style=discord.ButtonStyle.secondary, row=1)
    async def custom_modal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.target_user:
            await core.safe_send_response(interaction, "❌ 먼저 상단 드롭다운에서 대상 유저를 선택해 주세요!", ephemeral=True)
            return
        self.message = interaction.message
        await interaction.response.send_modal(OwnerSelectTicketAmountModal(self))

    @discord.ui.button(label="➖ 1장 회수", style=discord.ButtonStyle.danger, row=1)
    async def revoke_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._quick_adjust(interaction, -1)


class CharacterRankView(core.SafeView):
    """프로세카 26인 캐릭터 랭크(캐랭) 조회, 랭크업 크리스탈 보상 수령, 칭호 깃발 프로필 장착 뷰"""

    def __init__(self, user: discord.User | None = None, guild_id: int = 0, initial_char_id: int | None = None):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = guild_id
        self.selected_unit: str = "SUMMARY"
        self.selected_char_id: int | None = None
        self.status_note: str = ""
        self._lock = asyncio.Lock()

        self.all_ranks: list[dict] = []
        self.equipped_flags: list[dict] = []
        if initial_char_id and int(initial_char_id) in core.CHARACTER_MAP:
            self.selected_char_id = int(initial_char_id)
            self.selected_unit = core.CHARACTER_MAP[self.selected_char_id]["unit"]
        self._reload_state()

    def _reload_state(self):
        data = core.load_data()
        uid = self.user.id if self.user else 0
        self.all_ranks = core.calculate_all_character_ranks(data, self.guild_id, uid)
        self.equipped_flags = core.get_user_equipped_rank_flags(self.guild_id, uid, data=data)
        self._refresh_components()

    def _get_selected_rank_info(self) -> dict | None:
        if self.selected_char_id is None:
            return None
        return next((r for r in self.all_ranks if r["char_id"] == self.selected_char_id), None)

    def _refresh_components(self):
        unit_opts = [
            discord.SelectOption(
                label="📊 전체 26인 캐랭 요약 & 장착 깃발",
                value="SUMMARY",
                default=(self.selected_unit == "SUMMARY"),
            )
        ]
        for u in core.UNIT_ORDER:
            u_ranks = [r["rank"] for r in self.all_ranks if r["unit"] == u]
            u_max = max(u_ranks) if u_ranks else 1
            unit_opts.append(
                discord.SelectOption(
                    label=f"{core.UNIT_EMOJIS.get(u, '🎵')} {u}",
                    value=u,
                    description=f"최고 Rank {u_max}",
                    default=(self.selected_unit == u),
                )
            )
        self.unit_select.options = unit_opts

        if self.selected_unit in core.UNIT_ORDER:
            char_pool = [r for r in self.all_ranks if r["unit"] == self.selected_unit]
            self.char_select.placeholder = f"👤 {self.selected_unit} 캐릭터를 선택해 깃발 배너를 확인하세요..."
        else:
            char_pool = sorted(self.all_ranks, key=lambda r: (-r["rank"], -r["total_exp"], r["char_id"]))[:25]
            self.char_select.placeholder = "👤 상위 25인 바로 선택 (전체 26인은 위 유닛 필터 사용)..."

        char_opts = []
        for r in char_pool:
            f_em = r["highest_flag"]["emoji"] if r["highest_flag"] else "🔒"
            uncl = f" · 🎁+{r['unclaimed_crystals']}💎" if r["unclaimed_crystals"] > 0 else ""
            oshi_mark = " 💖" if r["is_oshi"] else ""
            lbl = f"{f_em} {r['char_name']}{oshi_mark} (Rank {r['rank']})"[:95]
            desc = f"{r['unit']} · 카드 {r['owned_cards']}종 · MR합 {r['mr_sum']}{uncl}"[:100]
            char_opts.append(
                discord.SelectOption(
                    label=lbl,
                    value=str(r["char_id"]),
                    description=desc,
                    default=(self.selected_char_id == r["char_id"]),
                )
            )
        self.char_select.options = char_opts or [discord.SelectOption(label="캐릭터 없음", value="NONE")]

        sel_info = self._get_selected_rank_info()
        eq_pairs = {(f["char_id"], f["tier_rank"]) for f in self.equipped_flags}
        if sel_info and sel_info["unlocked_flags"]:
            flag_opts = []
            for f in sel_info["unlocked_flags"]:
                is_eq = (f["char_id"], f["tier_rank"]) in eq_pairs
                mark = "✅ [장착중] " if is_eq else ""
                flag_opts.append(
                    discord.SelectOption(
                        label=f"{mark}{f['emoji']} [{f['title']}]"[:95],
                        value=f"{f['char_id']}:{f['tier_rank']}",
                        description=f"Rank {f['tier_rank']} 해금 · {f['grade']} (클릭 시 장착/교체/해제)",
                    )
                )
            self.flag_tier_select.options = flag_opts
            self.flag_tier_select.disabled = False
            self.flag_tier_select.placeholder = f"🚩 {sel_info['char_name']} 해금 칭호 깃발 선택 장착/해제..."
        else:
            lock_txt = (
                f"🔒 {sel_info['char_name']} Rank 5 달성 시 첫 깃발 해금 (현재 Rank {sel_info['rank']})"
                if sel_info
                else "🚩 위에서 캐릭터를 선택하면 해금된 칭호 깃발을 장착할 수 있어요"
            )
            self.flag_tier_select.options = [discord.SelectOption(label=lock_txt[:95], value="NONE")]
            self.flag_tier_select.disabled = True
            self.flag_tier_select.placeholder = "🚩 캐릭터 선택 후 해금된 깃발 장착..."

        if sel_info and sel_info["highest_flag"]:
            hf = sel_info["highest_flag"]
            is_hf_eq = (hf["char_id"], hf["tier_rank"]) in eq_pairs
            self.quick_equip_btn.disabled = False
            self.quick_equip_btn.label = "🏷️ 최고 깃발 해제" if is_hf_eq else f"🚩 [{hf['grade']}] 장착"
            self.quick_equip_btn.style = discord.ButtonStyle.secondary if is_hf_eq else discord.ButtonStyle.primary
        else:
            self.quick_equip_btn.disabled = True
            self.quick_equip_btn.label = "🚩 깃발 장착 (Rank 5+)"
            self.quick_equip_btn.style = discord.ButtonStyle.secondary

        if sel_info and sel_info["unclaimed_crystals"] > 0:
            self.claim_char_btn.disabled = False
            self.claim_char_btn.label = f"🎁 캐릭터 보상 (+{sel_info['unclaimed_crystals']:,}💎)"[:80]
            self.claim_char_btn.style = discord.ButtonStyle.success
        else:
            self.claim_char_btn.disabled = True
            self.claim_char_btn.label = "🎁 캐릭터 보상 없음"
            self.claim_char_btn.style = discord.ButtonStyle.secondary

        total_unclaimed = sum(r["unclaimed_crystals"] for r in self.all_ranks)
        if total_unclaimed > 0:
            self.claim_all_btn.disabled = False
            self.claim_all_btn.label = f"💎 전체 일괄수령 (+{total_unclaimed:,}💎)"[:80]
            self.claim_all_btn.style = discord.ButtonStyle.success
        else:
            self.claim_all_btn.disabled = True
            self.claim_all_btn.label = "💎 전체 보상 수령완료"
            self.claim_all_btn.style = discord.ButtonStyle.secondary

        self.clear_flags_btn.disabled = (len(self.equipped_flags) == 0)

    def _build_equipped_flags_line(self) -> str:
        if not self.equipped_flags:
            return "미장착 *(Rank 5 이상 달성 후 캐릭터를 선택해 최대 3개까지 장착해 보세요!)*"
        return "\n".join(
            f"• {f['emoji']} **`[{f['title']}]`** (`{f['grade']}` · `Rank {f.get('current_rank', f['tier_rank'])}`)"
            for f in self.equipped_flags
        )

    async def build_embed_and_file(self) -> tuple[discord.Embed, discord.File | None]:
        u_name = self.user.display_name if self.user else "유저"
        sel_info = self._get_selected_rank_info()

        if sel_info is None:
            ranked = sorted(self.all_ranks, key=lambda r: (-r["rank"], -r["total_exp"], r["char_id"]))
            total_rank_sum = sum(r["rank"] for r in self.all_ranks)
            unlocked_flag_chars = sum(1 for r in self.all_ranks if r["highest_flag"])
            total_unclaimed = sum(r["unclaimed_crystals"] for r in self.all_ranks)

            top_lines = []
            for idx, r in enumerate(ranked[:12], start=1):
                hf = r["highest_flag"]
                flag_txt = f"{hf['emoji']}`{hf['title']}`" if hf else "🔒`미해금`"
                oshi_t = " 💖" if r["is_oshi"] else ""
                uncl_t = f" · 🎁`+{r['unclaimed_crystals']:,}💎`" if r["unclaimed_crystals"] > 0 else ""
                top_lines.append(
                    f"`{idx:02d}.` {r['unit_emoji']} **{r['char_name']}**{oshi_t} — **`Rank {r['rank']}`** · {flag_txt}{uncl_t}"
                )

            desc = f"> {self.status_note}" if self.status_note else "26인 캐릭터 랭크 현황과 프로필 칭호 깃발을 관리합니다."
            embed = discord.Embed(
                title=f"🚩 {u_name}님의 캐릭터 랭크 & 칭호 깃발",
                description=desc,
                color=discord.Color.from_rgb(0, 204, 221),
                timestamp=datetime.datetime.now(core.KST),
            )
            embed.add_field(name="📊 26인 랭크 합계", value=f"**`{total_rank_sum:,}`**", inline=True)
            embed.add_field(name="🚩 깃발 해금", value=f"**`{unlocked_flag_chars} / 26명`**", inline=True)
            embed.add_field(name="💎 미수령 보상", value=f"**`+{total_unclaimed:,} 💎`**", inline=True)
            embed.add_field(
                name=f"🪪 프로필 장착 깃발 ({len(self.equipped_flags)}/{core.MAX_EQUIPPED_RANK_FLAGS})",
                value=self._build_equipped_flags_line(),
                inline=False,
            )
            embed.add_field(name="🏆 내 캐릭터 랭크 TOP 12", value="\n".join(top_lines)[:1024], inline=False)
            embed.set_footer(text="랭크업 +50💎 · 5단위 +150💎 · 10단위 +300💎 • 아래에서 캐릭터 선택 시 깃발 배너 확인")
            return embed, None

        # 캐릭터 상세 모드 + 프로세카 인게임 스타일 깃발 배너 PNG 생성
        bd = sel_info["breakdown"]
        exp_bar = core.format_progress_bar(sel_info["cur_exp"], max(1, sel_info["need_exp"]), slots=10)
        pct = min(100, int((sel_info["cur_exp"] / max(1, sel_info["need_exp"])) * 100))

        tier_lines = []
        eq_pairs = {(f["char_id"], f["tier_rank"]) for f in self.equipped_flags}
        for t in core.CHARACTER_RANK_FLAG_TIERS:
            fm = core.get_char_rank_flag_meta(sel_info["char_id"], t["rank"])
            if not fm:
                continue
            unlocked = sel_info["rank"] >= t["rank"]
            is_eq = (fm["char_id"], fm["tier_rank"]) in eq_pairs
            st = "✅ 장착중" if is_eq else ("🔓 해금" if unlocked else f"🔒 `R{t['rank']}`")
            tier_lines.append(f"`R{t['rank']:02d}` {fm['emoji']} **{fm['title']}** (`{fm['grade']}`) — {st}")

        u_rgb = sel_info.get("unit_color") or (0, 204, 221)
        desc = f"> {self.status_note}" if self.status_note else f"`{sel_info['unit']}` 소속 · 랭크업 시 크리스탈과 칭호 깃발이 해금됩니다."
        embed = discord.Embed(
            title=f"{sel_info['unit_emoji']} {sel_info['char_name']} — Rank {sel_info['rank']}",
            description=desc,
            color=discord.Color.from_rgb(*u_rgb),
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.add_field(
            name="⭐ 캐릭터 랭크 & EXP",
            value=(
                f"**Rank {sel_info['rank']}** · `{pct}%` *(누적 `{sel_info['total_exp']:,} EXP`)*\n"
                f"{exp_bar}\n"
                f"└ 다음 랭크까지 `{sel_info['cur_exp']:,} / {sel_info['need_exp']:,} EXP`"
            ),
            inline=False,
        )
        embed.add_field(
            name="💎 미수령 랭크업 보상",
            value=f"**`+{sel_info['unclaimed_crystals']:,} 💎`** (`{sel_info['unclaimed_ranks']}랭크`분)",
            inline=True,
        )
        embed.add_field(
            name="📊 EXP 상세 내역",
            value=(
                f"🃏 카드 `{sel_info['owned_cards']}종` (`+{bd['card_exp']}`) · 🏆 MR합 `{sel_info['mr_sum']}` (`+{bd['mr_exp']}`)\n"
                f"🔨 강화 (`+{bd['lvl_exp']}`) · 👗 의상 `{sel_info['costume_count']}벌` (`+{bd['costume_exp']}`)\n"
                f"⚔️ 라이브 `{sel_info['live_plays']}회` (`+{bd['live_exp']}`) · 💖 오시 (`+{bd['oshi_exp']}`)"
            ),
            inline=False,
        )
        embed.add_field(name="🚩 칭호 깃발 티어 (Rank 5 ~ 65)", value="\n".join(tier_lines)[:1024], inline=False)
        embed.add_field(
            name=f"🪪 프로필 장착 깃발 ({len(self.equipped_flags)}/{core.MAX_EQUIPPED_RANK_FLAGS})",
            value=self._build_equipped_flags_line(),
            inline=False,
        )
        embed.set_footer(text="장착한 깃발은 /내프로필 및 통합 PNG 프로필 카드에 자동 반영됩니다")

        img_bytes, fn = await asyncio.to_thread(
            core.build_character_rank_flag_image_bytes, sel_info, self.equipped_flags
        )
        if img_bytes and fn:
            embed.set_image(url=f"attachment://{fn}")
            return embed, discord.File(io.BytesIO(img_bytes), filename=fn)
        return embed, None

    async def _commit_update(self, interaction: discord.Interaction):
        embed, file_obj = await self.build_embed_and_file()
        if file_obj:
            await core.safe_edit_response(interaction, embed=embed, attachments=[file_obj], view=self)
        else:
            await core.safe_edit_response(interaction, embed=embed, attachments=[], view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await super().interaction_check(interaction)
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 캐릭터 랭크 창을 연 본인만 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.select(placeholder="🏷️ 유닛 선택 (전체 26인 요약 / 유닛별)...", row=0, options=[discord.SelectOption(label="요약", value="SUMMARY")])
    async def unit_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await core.safe_defer(interaction)
        val = select.values[0]
        self.selected_unit = val
        self.status_note = ""
        if val == "SUMMARY":
            self.selected_char_id = None
        else:
            unit_chars = [r for r in self.all_ranks if r["unit"] == val]
            self.selected_char_id = unit_chars[0]["char_id"] if unit_chars else None
        await asyncio.to_thread(self._reload_state)
        await self._commit_update(interaction)

    @discord.ui.select(placeholder="👤 캐릭터를 선택해 깃발 배너 & 상세 정보를 확인하세요...", row=1, options=[discord.SelectOption(label="로딩중", value="NONE")])
    async def char_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        if val == "NONE":
            await core.safe_defer(interaction)
            return
        await core.safe_defer(interaction)
        cid = int(val)
        self.selected_char_id = cid
        if cid in core.CHARACTER_MAP:
            self.selected_unit = core.CHARACTER_MAP[cid]["unit"]
        self.status_note = ""
        await asyncio.to_thread(self._reload_state)
        await self._commit_update(interaction)

    @discord.ui.select(placeholder="🚩 해금된 칭호 깃발 선택 장착/해제...", row=2, options=[discord.SelectOption(label="로딩중", value="NONE")])
    async def flag_tier_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        if val == "NONE" or ":" not in val:
            await core.safe_defer(interaction)
            return
        await core.safe_defer(interaction)
        cid_s, tier_s = val.split(":", 1)
        ok, msg, _ = await asyncio.to_thread(
            core.toggle_user_equipped_rank_flag, self.guild_id, interaction.user.id, int(cid_s), int(tier_s)
        )
        self.status_note = msg
        await asyncio.to_thread(self._reload_state)
        await self._commit_update(interaction)

    @discord.ui.button(label="🚩 깃발 장착", style=discord.ButtonStyle.primary, row=3)
    async def quick_equip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selected_char_id is None:
            await core.safe_send_response(interaction, "❌ 먼저 캐릭터를 선택해 주세요.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        ok, msg, _ = await asyncio.to_thread(
            core.toggle_user_equipped_rank_flag, self.guild_id, interaction.user.id, self.selected_char_id, None
        )
        self.status_note = msg
        await asyncio.to_thread(self._reload_state)
        await self._commit_update(interaction)

    @discord.ui.button(label="🎁 캐릭터 보상", style=discord.ButtonStyle.success, row=3)
    async def claim_char_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selected_char_id is None:
            await core.safe_send_response(interaction, "❌ 먼저 캐릭터를 선택해 주세요.", ephemeral=True)
            return
        async with self._lock:
            await core.safe_defer(interaction)
            ok, msg, res = await asyncio.to_thread(
                core.claim_character_rank_rewards,
                self.guild_id,
                interaction.user.id,
                self.selected_char_id,
                interaction.user.display_name,
            )
            self.status_note = f"{msg} (현재 크리스탈: `{res.get('current_crystals', 0):,}💎`)" if ok else f"ℹ️ {msg}"
            await asyncio.to_thread(self._reload_state)
            await self._commit_update(interaction)

    @discord.ui.button(label="💎 전체 일괄수령", style=discord.ButtonStyle.success, row=3)
    async def claim_all_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self._lock:
            await core.safe_defer(interaction)
            ok, msg, res = await asyncio.to_thread(
                core.claim_character_rank_rewards,
                self.guild_id,
                interaction.user.id,
                None,
                interaction.user.display_name,
            )
            self.status_note = f"{msg} (현재 크리스탈: `{res.get('current_crystals', 0):,}💎`)" if ok else f"ℹ️ {msg}"
            await asyncio.to_thread(self._reload_state)
            await self._commit_update(interaction)

    @discord.ui.button(label="🧹 깃발 해제", style=discord.ButtonStyle.secondary, row=3)
    async def clear_flags_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        _, msg = await asyncio.to_thread(core.clear_user_equipped_rank_flags, self.guild_id, interaction.user.id)
        self.status_note = msg
        await asyncio.to_thread(self._reload_state)
        await self._commit_update(interaction)

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=3)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.status_note = "🔄 최신 카드·마스터랭크·의상·라이브 기준으로 캐랭을 다시 계산했습니다."
        await asyncio.to_thread(self._reload_state)
        await self._commit_update(interaction)


class RerollSimulatorView(core.SafeView):
    """보관함/랭킹/쿨타임 영향 없이 10연차와 픽업 저격 확률을 체험하는 리세마라 연습 시뮬레이터 뷰"""

    def __init__(self, user: discord.User | None = None, guild_id: int = 0, pickup_cfg: dict | None = None, banner_type: str | None = None, initial_drawn: list | None = None):
        super().__init__(timeout=600)
        self.user = user
        self.guild_id = guild_id
        self.pickup_cfg = core.as_dict(pickup_cfg) or core.DEFAULT_CONFIG["gacha_pickup"]
        self.banner_type = banner_type if banner_type in core.BANNER_CONFIGS else core.get_active_proseka_banner(self.pickup_cfg)
        self.attempt_count = 1
        self.drawn = initial_drawn or []
        self.total_high = sum(1 for c in self.drawn if c.get("star_num", 0) >= 4)
        self.total_pickup = sum(1 for c in self.drawn if c.get("star_num", 0) >= 4 and c.get("is_pickup"))
        self.last_auto_note: str | None = None
        self._lock = asyncio.Lock()
        self._refresh_select()

    def _refresh_select(self):
        self.sim_banner_select.options = [
            discord.SelectOption(
                label="🌟 일반 / 현재 픽업 가챠 (★4 3.0%)",
                value="normal",
                default=(self.banner_type == "normal"),
            ),
            discord.SelectOption(
                label="🎊 컬러풀 페스티벌 (★4 2배 · 6.0%!)",
                value="fes",
                default=(self.banner_type == "fes"),
            ),
            discord.SelectOption(
                label="🎂 생일 / 기념일 스페셜 가챠",
                value="birthday",
                default=(self.banner_type == "birthday"),
            ),
        ]

    def build_sim_embed(self, grid_filename: str | None = None) -> discord.Embed:
        b_cfg = core.BANNER_CONFIGS.get(self.banner_type, core.BANNER_CONFIGS["normal"])
        lines = []
        for idx, c in enumerate(self.drawn, start=1):
            chips = []
            if c.get("is_pickup"):
                chips.append("🎯`픽업`")
            if c.get("is_new"):
                chips.append("✨`NEW`")
            chips_str = (" " + " ".join(chips)) if chips else ""
            s_num = int(c.get("star_num", 2))
            if c.get("rarity_type") == "rarity_birthday":
                badge = "🎂 `생일`"
            elif s_num >= 4:
                badge = "🌟 `★4`"
            elif s_num == 3:
                badge = "💫 `★3`"
            elif s_num == 2:
                badge = "⭐ `★2`"
            else:
                badge = "🔹 `★1`"
            if s_num >= 4:
                lines.append(
                    f"**{idx:02d}.** {badge} **{c.get('char_name', '')}** [{c.get('prefix', '')}]{chips_str} · `{c.get('prob', 0):.4f}%`"
                )
            elif s_num == 3:
                lines.append(
                    f"**{idx:02d}.** {badge} **{c.get('char_name', '')}** [{c.get('prefix', '')}]{chips_str}"
                )
            else:
                lines.append(
                    f"`{idx:02d}.` {badge} {c.get('char_name', '')} [{c.get('prefix', '')}]{chips_str}"
                )

        cur_high = sum(1 for c in self.drawn if c.get("star_num", 0) >= 4)
        cur_pickup = sum(1 for c in self.drawn if c.get("star_num", 0) >= 4 and c.get("is_pickup"))
        crystal_used = self.attempt_count * 3000

        desc_parts = [f"🎰 **배너:** `{b_cfg['name']}`"]
        if self.last_auto_note:
            desc_parts.append(f"> {self.last_auto_note}")
        desc_parts.append("\n" + "\n".join(lines))

        embed = discord.Embed(
            title=f"🧪 연습 시뮬레이터 — {self.attempt_count}회차",
            description="\n".join(desc_parts),
            color=discord.Color.from_rgb(255, 105, 180) if cur_high > 0 else discord.Color.from_rgb(*b_cfg.get("color", (0, 204, 221))),
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.add_field(
            name="🎯 이번 세트",
            value=f"★4·생일 **`{cur_high}장`** · 🎯 픽업 **`{cur_pickup}장`**",
            inline=True,
        )
        embed.add_field(
            name="📊 누적 기록",
            value=f"`{self.attempt_count:,}회` (`{self.attempt_count * 10:,}연` · `{crystal_used:,}💎`)\n└ ★4·생일 `{self.total_high:,}장` · 픽업 `{self.total_pickup:,}장`",
            inline=True,
        )
        u_name = self.user.display_name if self.user else "유저"
        u_icon = getattr(self.user.display_avatar, "url", None) if self.user else None
        embed.set_author(name=f"{u_name}님의 연습 시뮬레이션", icon_url=u_icon)
        if grid_filename:
            embed.set_image(url=f"attachment://{grid_filename}")
        embed.set_footer(text=f"연습 모드 (보관함·랭킹 미반영) • 픽업: {core.truncate_text(core.format_pickup_summary(self.pickup_cfg), 55)}")
        return embed

    @discord.ui.button(label="🔁 10연차 다시 돌리기", style=discord.ButtonStyle.primary, row=0)
    async def reroll_once(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 연습 시뮬레이션을 시작한 본인만 조작할 수 있습니다.", ephemeral=True)
            return
        if not self.user:
            self.user = interaction.user
        if self._lock.locked():
            await core.safe_send_response(interaction, "⏳ 이전 시뮬레이션을 처리 중입니다. 잠시 후 다시 눌러주세요.", ephemeral=True)
            return
        async with self._lock:
            await core.safe_defer(interaction)
            def _do_roll():
                d = core.load_data()
                p_cfg = core.as_dict(d.get("gacha_pickup")) or core.DEFAULT_CONFIG["gacha_pickup"]
                dr = core.draw_proseka_cards(p_cfg, count=10, banner_type=self.banner_type)
                core.annotate_drawn_is_new(self.guild_id, self.user.id, dr)
                return p_cfg, dr

            self.pickup_cfg, drawn = await asyncio.to_thread(_do_roll)
            self.drawn = drawn
            self.attempt_count += 1
            self.total_high += sum(1 for c in drawn if c.get("star_num", 0) >= 4)
            self.total_pickup += sum(1 for c in drawn if c.get("star_num", 0) >= 4 and c.get("is_pickup"))
            self.last_auto_note = None
            grid_bytes, grid_fn = await asyncio.to_thread(
                core.build_10pull_grid_image_bytes, drawn, self.banner_type, f"연습 {self.attempt_count}회차"
            )
            embed = self.build_sim_embed(grid_fn if grid_bytes else None)
            if grid_bytes and grid_fn:
                await interaction.edit_original_response(
                    embed=embed, attachments=[discord.File(io.BytesIO(grid_bytes), filename=grid_fn)], view=self
                )
            else:
                await interaction.edit_original_response(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="🎯 ★4/픽업까지 돌리기 (50회)", style=discord.ButtonStyle.success, row=0)
    async def auto_reroll_until_hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 연습 시뮬레이션을 시작한 본인만 조작할 수 있습니다.", ephemeral=True)
            return
        if not self.user:
            self.user = interaction.user
        if self._lock.locked():
            await core.safe_send_response(interaction, "⏳ 이전 시뮬레이션을 처리 중입니다. 잠시 후 다시 눌러주세요.", ephemeral=True)
            return
        async with self._lock:
            await core.safe_defer(interaction)

            def _run_batch():
                d = core.load_data()
                p_cfg = core.as_dict(d.get("gacha_pickup")) or core.DEFAULT_CONFIG["gacha_pickup"]
                prob_cards = core.calculate_card_probabilities(p_cfg, banner_type=self.banner_type)
                if not prob_cards:
                    return p_cfg, 0, [], False, 0, 0, False
                has_pickup_target = any(c.get("is_pickup") and c.get("star_num", 0) >= 4 for c in prob_cards)
                weights = [c["prob"] for c in prob_cards]
                high_pool = [c for c in prob_cards if c["star_num"] >= 3]
                high_weights = [c["prob"] for c in high_pool]

                batch_tries = 0
                add_high = 0
                add_pickup = 0
                last_drawn = []
                hit = False
                while batch_tries < 50:
                    batch_tries += 1
                    drawn = [dict(c) for c in random.choices(prob_cards, weights=weights, k=10)]
                    if high_pool and not any(c["star_num"] >= 3 for c in drawn):
                        drawn[-1] = dict(random.choices(high_pool, weights=high_weights, k=1)[0])
                    add_high += sum(1 for c in drawn if c.get("star_num", 0) >= 4)
                    add_pickup += sum(1 for c in drawn if c.get("star_num", 0) >= 4 and c.get("is_pickup"))
                    last_drawn = drawn
                    if has_pickup_target:
                        if any(c.get("is_pickup") and c.get("star_num", 0) >= 4 for c in drawn):
                            hit = True
                            break
                    else:
                        if any(c.get("star_num", 0) >= 4 for c in drawn):
                            hit = True
                            break
                for c in last_drawn:
                    cid_str = str(c.get("id"))
                    if cid_str in core.PROSEKA_KR_COSTUMES:
                        c["costume"] = core.PROSEKA_KR_COSTUMES[cid_str]
                core.annotate_drawn_is_new(self.guild_id, self.user.id, last_drawn)
                return p_cfg, batch_tries, last_drawn, hit, add_high, add_pickup, has_pickup_target

            self.pickup_cfg, batch_tries, last_drawn, hit, add_high, add_pickup, has_pickup_target = await asyncio.to_thread(_run_batch)
            self.attempt_count += batch_tries
            self.total_high += add_high
            self.total_pickup += add_pickup
            self.drawn = last_drawn

            target_label = "목표 픽업 ★4" if has_pickup_target else "★4·생일"
            if hit:
                self.last_auto_note = f"🎉 **자동 시뮬 성공:** 이번 도전 `{batch_tries}회` (`{batch_tries * 10}연차`, 가상 `{batch_tries * 3000:,}💎`) 만에 {target_label} 등장!"
            else:
                self.last_auto_note = f"💦 **자동 시뮬 50회({500}연차) 완료:** 이번 50회에서는 {target_label} 미등장"

            grid_bytes, grid_fn = await asyncio.to_thread(
                core.build_10pull_grid_image_bytes, last_drawn, self.banner_type, f"연습 {self.attempt_count}회차"
            )
            embed = self.build_sim_embed(grid_fn if grid_bytes else None)
            if grid_bytes and grid_fn:
                await interaction.edit_original_response(
                    embed=embed, attachments=[discord.File(io.BytesIO(grid_bytes), filename=grid_fn)], view=self
                )
            else:
                await interaction.edit_original_response(embed=embed, attachments=[], view=self)

    @discord.ui.select(
        placeholder="🔒 [봇주 전용] 연습 배너 선택...",
        row=1,
        options=[discord.SelectOption(label="일반", value="normal")]
    )
    async def sim_banner_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not await _is_interaction_bot_owner(interaction):
            await core.safe_send_response(
                interaction,
                "❌ 프로세카 가챠 배너 변경은 **봇주인(Bot Owner)** 만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 연습 시뮬레이션을 시작한 본인만 배너를 바꿀 수 있습니다.", ephemeral=True)
            return
        if not self.user:
            self.user = interaction.user
        if self._lock.locked():
            await core.safe_send_response(interaction, "⏳ 이전 시뮬레이션을 처리 중입니다. 잠시 후 다시 눌러주세요.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        self.banner_type = select.values[0]
        self._refresh_select()
        b_cfg = core.BANNER_CONFIGS.get(self.banner_type, core.BANNER_CONFIGS["normal"])
        await core.safe_edit_response(interaction, view=self)
        await core.safe_send_response(
            interaction,
            f"🧪 다음 연습 배너가 **`{b_cfg['name']}`**(으)로 변경되었습니다! 상단 버튼을 눌러 10연차를 돌려보세요.",
            ephemeral=True,
        )


class DestinyRerollView(core.SafeView):
    """일일 1회 '운명 다시 뽑기': 최대 3세트의 10연차를 굴려보고 가장 마음에 드는 1세트를 확정 수령하는 뷰"""

    def __init__(self, user: discord.User | None = None, guild_id: int = 0, pickup_cfg: dict | None = None, banner_type: str = "normal", first_set: list[dict] | None = None):
        super().__init__(timeout=600)
        self.user = user
        self.guild_id = guild_id
        self.pickup_cfg = pickup_cfg or core.DEFAULT_CONFIG["gacha_pickup"]
        self.banner_type = banner_type if banner_type in core.BANNER_CONFIGS else "normal"
        self.sets: list[list[dict]] = [first_set] if first_set else []
        self.current_idx: int = 0
        self.confirmed: bool = False if self.sets else True
        self._lock = asyncio.Lock()
        self._refresh_buttons()

    def _refresh_buttons(self):
        rem_rerolls = max(0, 3 - len(self.sets)) if self.sets else 0
        self.reroll_set.label = f"🔁 다시 뽑기 (남은 {rem_rerolls}/2회)"
        self.reroll_set.disabled = self.confirmed or (rem_rerolls == 0)
        self.prev_set.disabled = self.confirmed or (self.current_idx <= 0)
        self.next_set.disabled = self.confirmed or (self.current_idx >= len(self.sets) - 1)
        self.confirm_set.label = f"✅ {self.current_idx + 1}세트 확정 수령!" if not self.confirmed else "✅ 수령 완료!"
        self.confirm_set.disabled = self.confirmed or not self.sets

    def build_destiny_embed(self, grid_filename: str | None = None) -> discord.Embed:
        b_cfg = core.BANNER_CONFIGS.get(self.banner_type, core.BANNER_CONFIGS["normal"])
        cur_cards = self.sets[self.current_idx] if self.sets and 0 <= self.current_idx < len(self.sets) else []
        lines = []
        for idx, c in enumerate(cur_cards, start=1):
            chips = []
            if c.get("is_pickup"):
                chips.append("🎯`픽업`")
            if c.get("is_new"):
                chips.append("✨`NEW`")
            chips_str = (" " + " ".join(chips)) if chips else ""
            s_num = int(c.get("star_num", 2))
            if c.get("rarity_type") == "rarity_birthday":
                badge = "🎂 `생일`"
            elif s_num >= 4:
                badge = "🌟 `★4`"
            elif s_num == 3:
                badge = "💫 `★3`"
            elif s_num == 2:
                badge = "⭐ `★2`"
            else:
                badge = "🔹 `★1`"
            if s_num >= 4:
                lines.append(f"**{idx:02d}.** {badge} **{c.get('char_name', '')}** [{c.get('prefix', '')}]{chips_str}")
            elif s_num == 3:
                lines.append(f"**{idx:02d}.** {badge} **{c.get('char_name', '')}** [{c.get('prefix', '')}]{chips_str}")
            else:
                lines.append(f"`{idx:02d}.` {badge} {c.get('char_name', '')} [{c.get('prefix', '')}]{chips_str}")

        compare_lines = []
        for s_i, s_cards in enumerate(self.sets):
            h_cnt = sum(1 for c in s_cards if c.get("star_num", 0) >= 4)
            p_cnt = sum(1 for c in s_cards if c.get("star_num", 0) >= 4 and c.get("is_pickup"))
            n_cnt = sum(1 for c in s_cards if c.get("is_new"))
            marker = "👉" if s_i == self.current_idx else "•"
            cur_tag = " *(선택 중)*" if s_i == self.current_idx else ""
            compare_lines.append(
                f"{marker} **{s_i + 1}세트** — ★4·생일 `{h_cnt}장` (픽업 `{p_cnt}`) · NEW `{n_cnt}장`{cur_tag}"
            )

        status_txt = (
            "> ✅ **선택 확정 완료!** 보관함에 저장되었습니다."
            if self.confirmed
            else "> 💡 최대 3세트까지 뽑고 비교한 뒤, 원하는 **1세트**를 확정 수령하세요."
        )
        desc = f"🎰 **배너:** `{b_cfg['name']}`\n{status_txt}\n\n" + "\n".join(lines)
        cur_high = sum(1 for c in cur_cards if c.get("star_num", 0) >= 4)
        embed = discord.Embed(
            title=f"🔮 세트 {self.current_idx + 1} / {len(self.sets)} (최대 3세트)",
            description=desc,
            color=discord.Color.from_rgb(255, 105, 180) if cur_high > 0 else discord.Color.purple(),
            timestamp=datetime.datetime.now(core.KST),
        )
        if compare_lines:
            embed.add_field(name="📊 세트별 비교", value="\n".join(compare_lines), inline=False)
        u_name = self.user.display_name if self.user else "유저"
        u_icon = getattr(self.user.display_avatar, "url", None) if self.user else None
        embed.set_author(name=f"{u_name}님의 일일 운명 다시 뽑기", icon_url=u_icon)
        if grid_filename:
            embed.set_image(url=f"attachment://{grid_filename}")
        embed.set_footer(text="확정 수령 버튼을 누르기 전까지 보관함에 저장되지 않습니다")
        return embed

    async def _render_current(self, interaction: discord.Interaction):
        self._refresh_buttons()
        cur_cards = self.sets[self.current_idx]
        grid_bytes, grid_fn = await asyncio.to_thread(
            core.build_10pull_grid_image_bytes, cur_cards, self.banner_type, f"운명 {self.current_idx + 1}세트"
        )
        embed = self.build_destiny_embed(grid_fn if grid_bytes else None)
        if grid_bytes and grid_fn:
            await interaction.edit_original_response(
                embed=embed, attachments=[discord.File(io.BytesIO(grid_bytes), filename=grid_fn)], view=self
            )
        else:
            await interaction.edit_original_response(embed=embed, attachments=[], view=self)

    @discord.ui.button(label="🔁 다시 뽑기 (2/2)", style=discord.ButtonStyle.primary, row=0)
    async def reroll_set(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.user or interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 운명 다시 뽑기를 시작한 본인만 조작할 수 있습니다.", ephemeral=True)
            return
        if self._lock.locked():
            await core.safe_send_response(interaction, "⏳ 이전 작업을 처리 중입니다. 잠시 후 다시 눌러주세요.", ephemeral=True)
            return
        if self.confirmed or len(self.sets) >= 3:
            await core.safe_send_response(interaction, "❌ 더 이상 다시 뽑을 수 없습니다.", ephemeral=True)
            return
        async with self._lock:
            if self.confirmed or len(self.sets) >= 3:
                await core.safe_send_response(interaction, "❌ 더 이상 다시 뽑을 수 없습니다.", ephemeral=True)
                return
            await core.safe_defer(interaction)
            def _draw_new():
                ns = core.draw_proseka_cards(self.pickup_cfg, count=10, banner_type=self.banner_type)
                core.annotate_drawn_is_new(self.guild_id, self.user.id, ns)
                return ns
            new_set = await asyncio.to_thread(_draw_new)
            self.sets.append(new_set)
            self.current_idx = len(self.sets) - 1
            await self._render_current(interaction)

    @discord.ui.button(label="◀ 이전 세트", style=discord.ButtonStyle.secondary, row=0)
    async def prev_set(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.user or interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인만 세트를 전환할 수 있습니다.", ephemeral=True)
            return
        if self._lock.locked():
            await core.safe_send_response(interaction, "⏳ 이전 작업을 처리 중입니다. 잠시 후 다시 눌러주세요.", ephemeral=True)
            return
        async with self._lock:
            if self.current_idx <= 0:
                await core.safe_send_response(interaction, "ℹ️ 이미 첫 번째 세트입니다.", ephemeral=True)
                return
            await core.safe_defer(interaction)
            self.current_idx -= 1
            await self._render_current(interaction)

    @discord.ui.button(label="다음 세트 ▶", style=discord.ButtonStyle.secondary, row=0)
    async def next_set(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.user or interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인만 세트를 전환할 수 있습니다.", ephemeral=True)
            return
        if self._lock.locked():
            await core.safe_send_response(interaction, "⏳ 이전 작업을 처리 중입니다. 잠시 후 다시 눌러주세요.", ephemeral=True)
            return
        async with self._lock:
            if self.current_idx >= len(self.sets) - 1:
                await core.safe_send_response(interaction, "ℹ️ 이미 마지막 세트입니다.", ephemeral=True)
                return
            await core.safe_defer(interaction)
            self.current_idx += 1
            await self._render_current(interaction)

    @discord.ui.button(label="✅ 1세트 확정 수령!", style=discord.ButtonStyle.success, row=1)
    async def confirm_set(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.user or interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인만 세트를 확정 수령할 수 있습니다.", ephemeral=True)
            return
        if self._lock.locked():
            await core.safe_send_response(interaction, "⏳ 이전 작업을 처리 중입니다. 잠시 후 다시 눌러주세요.", ephemeral=True)
            return
        if self.confirmed:
            await core.safe_send_response(interaction, "✅ 이미 확정 수령을 완료했습니다.", ephemeral=True)
            return
        async with self._lock:
            if self.confirmed:
                await core.safe_send_response(interaction, "✅ 이미 확정 수령을 완료했습니다.", ephemeral=True)
                return
            await core.safe_defer(interaction)
            self.confirmed = True
            chosen_idx = self.current_idx
            chosen_cards = self.sets[chosen_idx]
            await asyncio.to_thread(
                core.save_real_pull_and_records, self.guild_id, self.user.id, chosen_cards, self.banner_type
            )
            pity_info = await asyncio.to_thread(core.get_user_gacha_pity_state, self.guild_id, self.user.id)
            pity_info["added_badges"] = len(chosen_cards)
            await self._render_current(interaction)

            repull_view = GachaPullAgainView(
                self.user, banner_type=self.banner_type, skip_anim=True, guild_id=self.guild_id, pity_info=pity_info
            )
            await send_gacha_pull_result(
                interaction,
                chosen_cards,
                self.pickup_cfg,
                10,
                repull_view,
                banner_type=self.banner_type,
                skip_anim=True,
                mode_note=f"🔮 **운명 다시 뽑기 확정 수령** — 총 {len(self.sets)}세트 중 **{chosen_idx + 1}세트** 저장 완료!",
                grid_tag=f"운명 확정 ({chosen_idx + 1}세트)",
                pity_info=pity_info,
            )


class GachaRankingView(core.SafeView):
    """종합 가챠 랭킹 + 최고 비틱 명예의 전당 & 최근 픽업 ★4 로그를 전환하는 2탭 뷰"""

    def __init__(self, user: discord.User | None = None, guild_name: str = "서버", total_db_cards: int = 1, stats_list: list[dict] | None = None, hall_of_fame: dict | None = None):
        super().__init__(timeout=300)
        self.user = user
        self.guild_name = guild_name or "서버"
        self.total_db_cards = max(1, total_db_cards or len(core.PROSEKA_KR_CARDS) or 1)
        self.stats_list = list(stats_list or [])
        self.hall_of_fame = hall_of_fame or {}
        self.current_tab = "overall"  # overall | hof
        self._refresh_buttons()

    def _refresh_buttons(self):
        self.tab_overall.style = discord.ButtonStyle.primary if self.current_tab == "overall" else discord.ButtonStyle.secondary
        self.tab_hof.style = discord.ButtonStyle.primary if self.current_tab == "hof" else discord.ButtonStyle.secondary

    def build_embed(self) -> discord.Embed:
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        if self.current_tab == "overall":
            embed = discord.Embed(
                title=f"🏆 {self.guild_name} 프로세카 가챠 랭킹",
                description=f"한국 서버 전체 도감(`{self.total_db_cards:,}종`) 기준 실시간 순위입니다.",
                color=discord.Color.gold(),
                timestamp=datetime.datetime.now(core.KST),
            )
            if self.stats_list:
                by_collect = sorted(self.stats_list, key=lambda x: (-x["unique"], -x["high"], -x["pulls"]))[:5]
                collect_lines = [
                    f"{medals[i]} <@{s['uid']}> — **`{s['unique']:,}종`** (`{s['rate']:.1f}%`)"
                    for i, s in enumerate(by_collect)
                ]
                by_high = sorted(self.stats_list, key=lambda x: (-x["high"], -x["star4"], -x["unique"]))[:5]
                high_lines = [
                    f"{medals[i]} <@{s['uid']}> — **`{s['high']:,}장`** (`★4 {s['star4']}` · `🎂 {s['bday']}`)"
                    for i, s in enumerate(by_high)
                ]
                by_pulls = sorted(self.stats_list, key=lambda x: (-x["pulls"], -x["unique"]))[:5]
                pull_lines = [
                    f"{medals[i]} <@{s['uid']}> — **`{s['pulls']:,}회`**"
                    for i, s in enumerate(by_pulls)
                ]
                core.add_chunked_embed_fields(embed, "📚 도감 수집률 TOP 5", collect_lines, separator="\n", max_chars=950)
                core.add_chunked_embed_fields(embed, "🌟 ★4 & 🎂 생일 최다 보유 TOP 5", high_lines, separator="\n", max_chars=950)
                core.add_chunked_embed_fields(embed, "🎰 누적 뽑기 TOP 5", pull_lines, separator="\n", max_chars=950)

                if self.user:
                    my_uid = str(self.user.id)
                    ranked = sorted(self.stats_list, key=lambda x: (-x["unique"], -x["high"], -x["pulls"]))
                    for idx, s in enumerate(ranked, 1):
                        if str(s.get("uid")) == my_uid:
                            embed.add_field(
                                name="📍 내 순위",
                                value=f"도감 **`#{idx}위`** (`{s['unique']:,}종` · `{s['rate']:.1f}%`) · ★4·생일 `{s['high']:,}장` · 누적 `{s['pulls']:,}회`",
                                inline=False,
                            )
                            break
            else:
                embed.add_field(name="📭 데이터 없음", value="아직 집계된 보관함 기록이 없습니다.", inline=False)
            embed.set_footer(text="하단 버튼으로 [👑 명예의 전당 & 비틱 로그]를 확인할 수 있습니다")
            return embed

        # 명예의 전당 & 픽업 ★4 로그 탭
        embed = discord.Embed(
            title=f"👑 {self.guild_name} 명예의 전당 & 픽업 로그",
            description="단일 10연차 최다 ★4·생일 신기록과 최근 픽업 획득 현황입니다. *(연습 모드 제외)*",
            color=discord.Color.from_rgb(255, 105, 180),
            timestamp=datetime.datetime.now(core.KST),
        )
        top_records = self.hall_of_fame.get("top_records") or []
        if top_records:
            hof_lines = []
            for i, r in enumerate(top_records[:5]):
                raw_cards = r.get("cards", [])
                cards_preview = ", ".join(raw_cards[:3])
                if len(raw_cards) > 3:
                    cards_preview += f" 외 `+{len(raw_cards) - 3}장`"
                pickup_info = f" · 🎯 픽업 `{r.get('pickup_count', 0)}`" if r.get("pickup_count", 0) > 0 else ""
                hof_lines.append(
                    f"{medals[i]} <@{r['uid']}> — ★4·생일 **`{r.get('high_count', 0)}장`**{pickup_info}\n"
                    f"└ {cards_preview} *(`{r.get('banner', '')}` · {r.get('achieved_at', '')[:10]})*"
                )
            core.add_chunked_embed_fields(embed, "🌟 단일 10연차 최고 비틱 TOP 5", hof_lines, separator="\n\n", max_chars=950)
        else:
            embed.add_field(name="🌟 단일 10연차 최고 비틱 TOP 5", value="아직 기록이 없습니다. 첫 주인공이 되어보세요!", inline=False)

        pickup_logs = self.hall_of_fame.get("recent_pickup_logs") or []
        if pickup_logs:
            p_lines = [
                f"🎯 <@{e['uid']}> · **{e['label']}**\n└ `{e['banner']}` · `{e['obtained_at'][5:16]}`"
                for e in pickup_logs[:6]
            ]
            core.add_chunked_embed_fields(embed, "🎯 최근 픽업 ★4 획득 로그", p_lines, separator="\n", max_chars=950)
        else:
            embed.add_field(name="🎯 최근 픽업 ★4 획득 로그", value="최근 픽업 ★4 획득 기록이 아직 없습니다.", inline=False)

        high_logs = self.hall_of_fame.get("recent_high_logs") or []
        if high_logs:
            h_lines = [
                f"{'🎯' if e.get('is_pickup') else ('🎂' if e.get('rarity_type') == 'rarity_birthday' else '🌟')} <@{e['uid']}> · **{e['label']}** (`{e['obtained_at'][5:16]}`)"
                for e in high_logs[:5]
            ]
            core.add_chunked_embed_fields(embed, "✨ 최근 ★4 · 생일 획득 로그", h_lines, separator="\n", max_chars=950)

        embed.set_footer(text="하단 버튼으로 [🏆 종합 랭킹]과 [👑 명예의 전당]을 전환할 수 있습니다")
        return embed

    @discord.ui.button(label="🏆 종합 랭킹", style=discord.ButtonStyle.primary, row=0)
    async def tab_overall(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_tab = "overall"
        self._refresh_buttons()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="👑 명예의 전당 & 비틱 로그", style=discord.ButtonStyle.secondary, row=0)
    async def tab_hof(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_tab = "hof"
        self._refresh_buttons()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh_rank(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        guild_id = interaction.guild_id or 0
        total_db_cards, new_stats = core.build_proseka_guild_ranking_stats(data, guild_id)
        self.total_db_cards = max(1, total_db_cards or self.total_db_cards)
        self.stats_list = new_stats
        self.hall_of_fame = await asyncio.to_thread(lambda: core.as_dict(core.get_gacha_hall_of_fame(guild_id)))
        self._refresh_buttons()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


class CardTradeAcceptView(core.SafeView):
    """유저 간 1:1 카드 교환 상대방 수락/거절 및 양측 일러스트 미리보기 인터랙티브 뷰 (수락 시 신청자 크리스탈 100 소모)"""
    def __init__(self, guild_id: int = 0, requester: discord.User | None = None, target: discord.User | None = None, req_card: dict | None = None, tgt_card: dict | None = None):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.requester = requester
        self.target = target
        self.req_card = req_card or {}
        self.tgt_card = tgt_card or {}

    @discord.ui.button(label="🤝 교환 수락", style=discord.ButtonStyle.success, row=0)
    async def accept_trade(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.target or not self.requester or not self.req_card or not self.tgt_card or self.requester.id == self.target.id:
            await core.safe_send_response(interaction, "⚠️ 교환 요청 정보가 만료되었습니다. `/설정` (`👤 개인` ➔ `🤝 1:1 카드 교환/선물`)에서 다시 신청해 주세요.", ephemeral=True)
            return
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
            description=f"🎉 {self.requester.mention}님과 {self.target.mention}님의 카드 교환이 완료되었습니다!",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.add_field(
            name=f"📤 {self.requester.display_name} ➔ {self.target.display_name}",
            value=(
                f"**{given_c['rarity_label']} {given_c['char_name']}** [{given_c['prefix']}]\n"
                f"└ `{given_c.get('limit_label', '통상')}` · `Lv.{given_c.get('level', 1)}` · `⚔️ {given_pwr:,}`"
            ),
            inline=False,
        )
        embed.add_field(
            name=f"📥 {self.target.display_name} ➔ {self.requester.display_name}",
            value=(
                f"**{received_c['rarity_label']} {received_c['char_name']}** [{received_c['prefix']}]\n"
                f"└ `{received_c.get('limit_label', '통상')}` · `Lv.{received_c.get('level', 1)}` · `⚔️ {recv_pwr:,}`"
            ),
            inline=False,
        )
        embed.add_field(
            name="💎 소모 재화",
            value=f"{self.requester.display_name}님 크리스탈 `-100 💎` *(잔여 `{rem_crystals:,} 💎`)*",
            inline=False,
        )
        embed.set_thumbnail(url=core.get_proseka_card_image_url(received_c, "auto"))
        await interaction.edit_original_response(content=None, embed=embed, view=None)

    @discord.ui.button(label="🖼️ 제공 카드", style=discord.ButtonStyle.secondary, row=1)
    async def preview_req_card(self, interaction: discord.Interaction, button: discord.ui.Button):
        c = self.req_card
        if not c or "id" not in c:
            await core.safe_send_response(interaction, "⚠️ 카드 정보가 만료되었습니다. `/설정` (`👤 개인` ➔ `🤝 1:1 카드 교환/선물`)에서 다시 확인해 주세요.", ephemeral=True)
            return
        req_name = self.requester.display_name if self.requester else "신청자"
        can_train = core.can_card_awaken(c)
        stage_tag = "🌸 [특훈 전] " if can_train else ""
        p_embed = discord.Embed(
            title=f"📤 {stage_tag}{c['rarity_label']} [{c['prefix']}] {c['char_name']}"[:256],
            description=f"**{req_name}**님 제공 카드 미리보기 *(ID: `{c.get('id')}`)*",
            color=discord.Color.from_rgb(0, 204, 221)
        )
        p_embed.add_field(name="🏷️ 유닛 · 분류", value=f"`{c.get('unit', '-')}` · `{c.get('limit_label', '통상')}`", inline=True)
        p_embed.add_field(name="⚔️ 스탯", value=f"`Lv.{c.get('level', 1)}` · `✦MR.{int(c.get('master_rank', 0))}` · `⚔️ {core.get_card_power(c):,}`", inline=True)
        p_embed.set_image(url=core.get_proseka_card_image_url(c, "normal"))
        t_view = SimpleCardIllustToggleView(c, initial_mode="normal") if can_train else None
        await core.safe_send_response(interaction, embed=p_embed, view=t_view, ephemeral=True)

    @discord.ui.button(label="🖼️ 대상 카드", style=discord.ButtonStyle.secondary, row=1)
    async def preview_tgt_card(self, interaction: discord.Interaction, button: discord.ui.Button):
        c = self.tgt_card
        if not c or "id" not in c:
            await core.safe_send_response(interaction, "⚠️ 카드 정보가 만료되었습니다. `/설정` (`👤 개인` ➔ `🤝 1:1 카드 교환/선물`)에서 다시 확인해 주세요.", ephemeral=True)
            return
        tgt_name = self.target.display_name if self.target else "상대"
        can_train = core.can_card_awaken(c)
        stage_tag = "🌸 [특훈 전] " if can_train else ""
        p_embed = discord.Embed(
            title=f"📥 {stage_tag}{c['rarity_label']} [{c['prefix']}] {c['char_name']}"[:256],
            description=f"**{tgt_name}**님 보유 카드 미리보기 *(ID: `{c.get('id')}`)*",
            color=discord.Color.from_rgb(255, 105, 180)
        )
        p_embed.add_field(name="🏷️ 유닛 · 분류", value=f"`{c.get('unit', '-')}` · `{c.get('limit_label', '통상')}`", inline=True)
        p_embed.add_field(name="⚔️ 스탯", value=f"`Lv.{c.get('level', 1)}` · `✦MR.{int(c.get('master_rank', 0))}` · `⚔️ {core.get_card_power(c):,}`", inline=True)
        p_embed.set_image(url=core.get_proseka_card_image_url(c, "normal"))
        t_view = SimpleCardIllustToggleView(c, initial_mode="normal") if can_train else None
        await core.safe_send_response(interaction, embed=p_embed, view=t_view, ephemeral=True)

    @discord.ui.button(label="거절 / 취소", style=discord.ButtonStyle.danger, row=0)
    async def cancel_trade(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.target and self.requester and interaction.user.id not in (self.target.id, self.requester.id):
            await core.safe_send_response(interaction, "❌ 교환 당사자만 취소하거나 거절할 수 있습니다.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🚫 카드 교환 취소/거절됨",
            description="카드 교환이 취소되어 크리스탈과 카드가 차감되지 않았습니다.",
            color=discord.Color.dark_grey()
        )
        await core.safe_edit_response(interaction, content=None, embed=embed, view=None)


class InteractiveCardTradeStudioView(core.SafeView):
    """카드 ID를 직접 입력하지 않아도 드롭다운으로 내 카드와 상대 카드를 골라 교환 신청서를 발송하는 인터랙티브 장터 뷰"""
    def __init__(self, guild_id: int = 0, requester: discord.User | None = None, target: discord.User | None = None, req_cards: dict | None = None, tgt_cards: dict | None = None, my_crystals: int = 0):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.requester = requester
        self.target = target
        self.req_cards = req_cards or {}
        self.tgt_cards = tgt_cards or {}
        self.my_crystals = my_crystals
        self.selected_my_cid = None
        self.selected_tgt_cid = None
        self._populate_selects()

    def _populate_selects(self):
        my_unlocked = [c for c in self.req_cards.values() if isinstance(c, dict) and not c.get("locked", False) and c.get("count", 0) >= 1 and c.get("id") is not None]
        my_unlocked.sort(key=lambda x: (-x.get("count", 1), -x.get("star_num", 1), -int(x.get("is_limited", False))))
        if my_unlocked:
            opts1 = []
            seen1 = set()
            for c in my_unlocked:
                cid_s = str(c["id"])
                if cid_s in seen1:
                    continue
                seen1.add(cid_s)
                dup_tag = f"중복 {c.get('count', 1)}장" if c.get("count", 1) > 1 else "1장"
                label = f"{c['rarity_label']} [{c['prefix']}] {c['char_name']}"[:65]
                desc = f"{dup_tag} · {c.get('limit_label', '통상')} (ID:{cid_s})"[:45]
                opts1.append(discord.SelectOption(label=label, value=cid_s, description=desc, default=(cid_s == self.selected_my_cid)))
                if len(opts1) >= 10:
                    break
            self.my_card_select.options = opts1
            self.my_card_select.disabled = False
        else:
            self.my_card_select.options = [discord.SelectOption(label="교환 가능한(잠금 해제된) 내 카드가 없습니다", value="NONE")]
            self.my_card_select.disabled = True

        tgt_unlocked = [c for c in self.tgt_cards.values() if isinstance(c, dict) and not c.get("locked", False) and c.get("count", 0) >= 1 and c.get("id") is not None]
        tgt_unlocked.sort(key=lambda x: (-x.get("count", 1), -x.get("star_num", 1), -int(x.get("is_limited", False))))
        if tgt_unlocked:
            opts2 = []
            seen2 = set()
            for c in tgt_unlocked:
                cid_s = str(c["id"])
                if cid_s in seen2:
                    continue
                seen2.add(cid_s)
                dup_tag = f"중복 {c.get('count', 1)}장" if c.get("count", 1) > 1 else "1장"
                label = f"{c['rarity_label']} [{c['prefix']}] {c['char_name']}"[:65]
                desc = f"{dup_tag} · {c.get('limit_label', '통상')} (ID:{cid_s})"[:45]
                opts2.append(discord.SelectOption(label=label, value=cid_s, description=desc, default=(cid_s == self.selected_tgt_cid)))
                if len(opts2) >= 10:
                    break
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
        req_name = self.requester.display_name if self.requester else "신청자"
        tgt_name = self.target.display_name if self.target else "상대방"

        my_val = (
            f"**{my_c['rarity_label']} {my_c['char_name']}** [{my_c['prefix']}]\n"
            f"└ `{my_c.get('limit_label', '통상')}` · 보유 `{my_c.get('count', 1)}장` · `⚔️ {core.get_card_power(my_c):,}`"
            if my_c else "*아래 1단계 드롭다운에서 보낼 카드를 선택하세요*"
        )
        tgt_val = (
            f"**{tgt_c['rarity_label']} {tgt_c['char_name']}** [{tgt_c['prefix']}]\n"
            f"└ `{tgt_c.get('limit_label', '통상')}` · 보유 `{tgt_c.get('count', 1)}장` · `⚔️ {core.get_card_power(tgt_c):,}`"
            if tgt_c else "*아래 2단계 드롭다운에서 받을 카드를 선택하세요*"
        )

        embed = discord.Embed(
            title=f"🤝 1:1 카드 교환 스튜디오 ({req_name} ⇄ {tgt_name})",
            description=(
                "중복 보유 카드를 우선 정렬했습니다. (`🔒 잠금` 카드는 자동 보호)\n"
                "양쪽 카드를 고른 뒤 **`[📨 교환 신청서 발송하기]`** 버튼을 눌러주세요."
            ),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.add_field(name="📤 내가 제공할 카드", value=my_val, inline=False)
        embed.add_field(name=f"📥 {tgt_name}님에게 받을 카드", value=tgt_val, inline=False)
        embed.add_field(
            name="💎 교환 수수료",
            value=f"`100 💎` *(상대 수락 시 차감 · 내 보유 `{self.my_crystals:,} 💎`)*",
            inline=False,
        )
        if tgt_c:
            embed.set_thumbnail(url=core.get_proseka_card_image_url(tgt_c, "auto"))
        elif my_c:
            embed.set_thumbnail(url=core.get_proseka_card_image_url(my_c, "auto"))
        embed.set_footer(text="동일한 카드끼리는 교환할 수 없습니다")
        return embed

    @discord.ui.select(
        placeholder="📤 1단계: 내가 상대방에게 보낼 카드를 선택하세요...",
        row=0,
        options=[discord.SelectOption(label="카드 선택", value="NONE")],
    )
    async def my_card_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not self.requester or not self.req_cards:
            await core.safe_send_response(interaction, "⚠️ 교환 스튜디오 세션이 만료되었습니다. `/설정` (`👤 개인` ➔ `🤝 1:1 카드 교환/선물`)에서 다시 열어주세요.", ephemeral=True)
            return
        if interaction.user.id != self.requester.id:
            await core.safe_send_response(interaction, "❌ 교환 스튜디오를 연 본인만 조작할 수 있습니다.", ephemeral=True)
            return
        val = select.values[0]
        if val == "NONE":
            await core.safe_defer(interaction)
            return
        await core.safe_defer(interaction)
        self.selected_my_cid = val
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="📥 2단계: 상대방으로부터 받을 카드를 선택하세요...",
        row=1,
        options=[discord.SelectOption(label="카드 선택", value="NONE")],
    )
    async def tgt_card_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not self.requester or not self.tgt_cards:
            await core.safe_send_response(interaction, "⚠️ 교환 스튜디오 세션이 만료되었습니다. `/설정` (`👤 개인` ➔ `🤝 1:1 카드 교환/선물`)에서 다시 열어주세요.", ephemeral=True)
            return
        if interaction.user.id != self.requester.id:
            await core.safe_send_response(interaction, "❌ 교환 스튜디오를 연 본인만 조작할 수 있습니다.", ephemeral=True)
            return
        val = select.values[0]
        if val == "NONE":
            await core.safe_defer(interaction)
            return
        await core.safe_defer(interaction)
        self.selected_tgt_cid = val
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="📨 교환 신청서 발송하기 (100💎)", style=discord.ButtonStyle.success, row=2, disabled=True)
    async def send_offer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.requester or not self.target or self.requester.id == self.target.id:
            await core.safe_send_response(interaction, "⚠️ 교환 스튜디오 세션이 만료되었습니다. `/설정` (`👤 개인` ➔ `🤝 1:1 카드 교환/선물`)에서 다시 열어주세요.", ephemeral=True)
            return
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
                f"{self.target.mention}님, {self.requester.mention}님이 **1:1 카드 교환**을 요청했습니다.\n"
                "아래 카드와 하단 미리보기를 확인한 뒤 **`[🤝 교환 수락]`** 버튼을 눌러주세요."
            ),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        offer_embed.add_field(
            name=f"📤 {self.requester.display_name}님 제공",
            value=(
                f"**{my_c['rarity_label']} {my_c['char_name']}** [{my_c['prefix']}]\n"
                f"└ `{my_c.get('limit_label', '통상')}` · `Lv.{my_c.get('level', 1)}` · `⚔️ {core.get_card_power(my_c):,}` · 보유 `{my_c.get('count', 1)}장`"
            ),
            inline=False,
        )
        offer_embed.add_field(
            name=f"📥 {self.target.display_name}님 제공",
            value=(
                f"**{tgt_c['rarity_label']} {tgt_c['char_name']}** [{tgt_c['prefix']}]\n"
                f"└ `{tgt_c.get('limit_label', '통상')}` · `Lv.{tgt_c.get('level', 1)}` · `⚔️ {core.get_card_power(tgt_c):,}` · 보유 `{tgt_c.get('count', 1)}장`"
            ),
            inline=False,
        )
        offer_embed.add_field(
            name="💎 교환 비용",
            value=f"신청자({self.requester.display_name}) 크리스탈 `100 💎` *(수락 시 차감)*",
            inline=False,
        )
        offer_embed.set_thumbnail(url=core.get_proseka_card_image_url(my_c, "auto"))
        offer_embed.set_footer(text="하단 [🖼️ 제공 카드] · [🖼️ 대상 카드] 버튼으로 양쪽 일러스트를 확인할 수 있습니다")
        accept_view = CardTradeAcceptView(self.guild_id, self.requester, self.target, my_c, tgt_c)
        await interaction.edit_original_response(content="✅ 채널에 1:1 카드 교환 신청서를 발송했습니다!", embed=None, view=None)
        await interaction.channel.send(content=self.target.mention, embed=offer_embed, view=accept_view)


class CardIllustToggleView(core.SafeView):
    """보유 카드 일러스트 감상 — ★3·★4 기본 특훈 전(Normal) 표시 및 특훈 전·후 버튼 전환, 잠금(🔒) 토글, 마스터 랭크 바로가기 뷰"""
    def __init__(
        self,
        card: dict | None = None,
        initial_mode: str = "normal",
        guild_id: int = 0,
        owner_id: int = 0,
        parent_inventory_view=None,
        parent_inventory_message=None
    ):
        super().__init__(timeout=600)
        self.card = dict(card or {})
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.parent_inventory_view = parent_inventory_view
        self.parent_inventory_message = parent_inventory_message
        self.has_awakening = core.can_card_awaken(self.card) if self.card else False
        if self.has_awakening and initial_mode == "after_training":
            self.current_mode = "after_training"
        else:
            self.current_mode = "normal"
        self.update_buttons()

    def _card_accent_color(self) -> discord.Color:
        s_num = int(self.card.get("star_num") or 0)
        r_type = str(self.card.get("rarity_type") or "")
        if r_type in ("rarity_4", "rarity_birthday") or s_num >= 4:
            return discord.Color.from_rgb(255, 105, 180)
        if r_type == "rarity_3" or s_num == 3:
            return discord.Color.from_rgb(242, 184, 48)
        return discord.Color.from_rgb(0, 204, 221)

    def _restore_from_message(self, interaction: discord.Interaction):
        msg = getattr(interaction, "message", None)
        if not msg:
            return
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        orig_inter = getattr(msg, "interaction_metadata", None)
        orig_user = getattr(orig_inter, "user", None) or interaction.user
        if not self.owner_id and orig_user and isinstance(getattr(orig_user, "id", None), int):
            self.owner_id = orig_user.id

        if not self.card or "id" not in self.card:
            cid_str = None
            embeds = getattr(msg, "embeds", None) or []
            search_blob = ""
            if embeds:
                import re
                emb0 = embeds[0]
                search_blob = "\n".join(
                    [emb0.description or "", getattr(emb0.footer, "text", "") or ""]
                    + [f.value or "" for f in getattr(emb0, "fields", [])]
                )
                m = re.search(r"\(ID:\s*`?(\d+)`?\)", search_blob)
                if m:
                    cid_str = m.group(1)
            if cid_str:
                data = core.get_cached_data_ro()
                u_cards = core.safe_get_dict(data, "gacha_users", str(self.guild_id or 0), str(self.owner_id or interaction.user.id), "cards")
                found = u_cards.get(cid_str)
                if not isinstance(found, dict):
                    found = next((c for c in u_cards.values() if isinstance(c, dict) and str(c.get("id")) == cid_str), None)
                if not isinstance(found, dict):
                    found = core.get_proseka_card_by_id(cid_str)
                if isinstance(found, dict):
                    self.card = dict(found)
                    self.has_awakening = core.can_card_awaken(self.card)
                    if self.has_awakening and "특훈 후 (After Training)" in search_blob:
                        self.current_mode = "after_training"
                    else:
                        self.current_mode = "normal"
                    self.update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.card or "id" not in self.card:
            self._restore_from_message(interaction)
        return True

    def update_buttons(self):
        if not self.has_awakening:
            self.normal_btn.disabled = True
            self.normal_btn.label = "🖼️ 기본 일러스트"
            self.awakened_btn.disabled = True
            self.awakened_btn.label = "✨ 특훈 후 (★3·★4 전용)"
        else:
            self.normal_btn.disabled = (self.current_mode == "normal")
            self.normal_btn.label = "🌸 특훈 전"
            self.awakened_btn.disabled = (self.current_mode == "after_training")
            self.awakened_btn.label = "✨ 특훈 후"

        is_locked = bool(self.card.get("locked", False))
        if is_locked:
            self.lock_toggle_btn.label = "🔒 잠금됨 (클릭 시 해제)"
            self.lock_toggle_btn.style = discord.ButtonStyle.danger
        else:
            self.lock_toggle_btn.label = "🔓 카드 잠금하기"
            self.lock_toggle_btn.style = discord.ButtonStyle.success

    def build_embed(self):
        if not self.has_awakening:
            mode_text = "🖼️ 기본 일러스트 (Normal)"
        elif self.current_mode == "after_training":
            mode_text = "✨ 특훈 후 (After Training)"
        else:
            mode_text = "🌸 특훈 전 (Normal)"

        lock_status = "🔒 잠금 보호 중" if self.card.get("locked", False) else "🔓 잠금 해제"
        base_unit = self.card.get("unit", "프로세카")
        unit_str = f"{base_unit}" + (f" ({self.card['support_unit']})" if self.card.get("support_unit") else "")
        mr = int(self.card.get("master_rank", 0))
        cur_lvl = self.card.get("level", 1)
        max_lvl = core.get_card_max_level(self.card)
        pwr = core.get_card_power(self.card)
        r_label = core.get_card_rarity_label(self.card)

        embed = discord.Embed(
            title=f"🖼️ {r_label} [{self.card.get('prefix', '카드')}] {self.card.get('char_name', '캐릭터')}"[:256],
            description=f"`{mode_text}` · `{lock_status}` *(ID: `{self.card.get('id', '-')}`)*",
            color=self._card_accent_color(),
        )
        embed.add_field(name="🏷️ 유닛 · 분류", value=f"`{unit_str}`\n└ `{self.card.get('limit_label', '통상')}` · {self.card.get('attr', '✨')}", inline=True)
        embed.add_field(name="⚔️ 성장 스탯", value=f"**`⚔️ {pwr:,}`**\n└ `Lv.{cur_lvl}/{max_lvl}` · `✦MR.{mr}/5`", inline=True)
        embed.add_field(name="📦 보유 수량", value=f"**`{self.card.get('count', 1)}장`**", inline=True)

        cos = core.get_costume_for_card(self.card.get("id"))
        if cos:
            ac_txt = "✅ 어나더 컬러 해금됨" if mr >= 2 else "🔒 ✦MR.2 달성 시 어나더 컬러 해금"
            embed.add_field(
                name="👗 부속 3D 의상",
                value=f"**`{cos['name']}`** (`{'/'.join(cos.get('parts', ['body']))}`)\n└ *{ac_txt}*",
                inline=False,
            )
        embed.set_footer(text="잠금 시 교환·선물·중복변환에서 안전하게 보호됩니다")
        return embed

    async def build_embeds_and_files(self) -> tuple[list[discord.Embed], list[discord.File]]:
        primary_embed = self.build_embed()
        files: list[discord.File] = []
        fetch_mode = "after_training" if (self.has_awakening and self.current_mode == "after_training") else "normal"
        img_bytes, filename = await asyncio.to_thread(core.fetch_proseka_card_image_bytes, self.card, fetch_mode)
        if img_bytes and filename:
            safe_fn = f"inv_{fetch_mode}_{filename}"
            files.append(discord.File(io.BytesIO(img_bytes), filename=safe_fn))
            primary_embed.set_image(url=f"attachment://{safe_fn}")
        else:
            primary_embed.set_image(url=core.get_proseka_card_image_url(self.card, fetch_mode))
        return [primary_embed], files

    async def switch_mode(self, interaction: discord.Interaction, target_mode: str):
        if not self.card or "id" not in self.card:
            await core.safe_send_response(interaction, "❌ 카드 정보를 찾을 수 없습니다. `/설정` (`👤 개인` ➔ `🎒 프로세카 카드 보관함`)에서 다시 선택해 주세요.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        self.current_mode = "after_training" if (self.has_awakening and target_mode == "after_training") else "normal"
        self.update_buttons()
        embeds, files = await self.build_embeds_and_files()
        await interaction.edit_original_response(embeds=embeds, attachments=files, view=self)

    @discord.ui.button(label="🌸 특훈 전", style=discord.ButtonStyle.secondary, row=0)
    async def normal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.switch_mode(interaction, "normal")

    @discord.ui.button(label="✨ 특훈 후", style=discord.ButtonStyle.primary, row=0)
    async def awakened_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.switch_mode(interaction, "after_training")

    @discord.ui.button(label="🔓 카드 잠금", style=discord.ButtonStyle.success, row=1)
    async def lock_toggle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.owner_id and interaction.user.id != self.owner_id:
            await core.safe_send_response(interaction, "❌ 카드 소유자 본인만 잠금 상태를 변경할 수 있습니다.", ephemeral=True)
            return
        if not self.card or "id" not in self.card:
            await core.safe_send_response(interaction, "❌ 카드 정보를 찾을 수 없습니다.", ephemeral=True)
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
            target_pool = getattr(self.parent_inventory_view, "all_cards", None) or self.parent_inventory_view.cards
            for c in target_pool:
                if str(c.get("id")) == str(self.card.get("id")):
                    c["locked"] = new_locked
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
        embeds, files = await self.build_embeds_and_files()
        await interaction.edit_original_response(embeds=embeds, attachments=files, view=self)

    @discord.ui.button(label="🏆 마스터 랭크", style=discord.ButtonStyle.primary, row=1)
    async def master_rank_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.owner_id and interaction.user.id != self.owner_id:
            await core.safe_send_response(interaction, "❌ 카드 소유자 본인만 마스터 랭크를 돌파할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        gid = self.guild_id or (interaction.guild_id or 0)
        cid_str = str(self.card.get("id")) if self.card and self.card.get("id") is not None else None
        mr_view = MasterRankView(interaction.user, guild_id=gid, initial_card_id=cid_str)
        await interaction.followup.send(embed=mr_view.build_embed(), view=mr_view, wait=True)


class CharacterCostumeWardrobeView(core.SafeView):
    """캐릭터별 3D 의상 착용 및 다른 캐릭터 의상 제작/구매(300 💎) 뷰"""
    def __init__(self, user: discord.User | None = None, guild_id: int = 0, initial_char_id: int = 1):
        super().__init__(timeout=600)
        self.user = user
        self.guild_id = guild_id
        self.current_char_id = initial_char_id
        char_info = core.CHARACTER_MAP.get(self.current_char_id, core.CHARACTER_MAP[1])
        self.current_unit = char_info["unit"]
        self.view_mode = "char"
        self.illust_stage = "normal"
        self.update_components()

    def _restore_from_message(self, interaction: discord.Interaction):
        msg = getattr(interaction, "message", None)
        if not msg:
            return
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        restored_unit = None
        restored_cid = None
        for row in getattr(msg, "components", []) or []:
            for comp in getattr(row, "children", []):
                cid = getattr(comp, "custom_id", "") or ""
                if cid.endswith(":unit_select"):
                    for opt in getattr(comp, "options", []):
                        if getattr(opt, "default", False) and getattr(opt, "value", None) in core.UNIT_ORDER:
                            restored_unit = str(opt.value)
                elif cid.endswith(":char_select"):
                    for opt in getattr(comp, "options", []):
                        if getattr(opt, "default", False) and str(getattr(opt, "value", "")).isdigit():
                            restored_cid = int(opt.value)
        if restored_cid is None:
            embeds = getattr(msg, "embeds", None) or []
            if embeds and embeds[0].title:
                for map_cid, info in core.CHARACTER_MAP.items():
                    if info["name"] in embeds[0].title:
                        restored_cid = map_cid
                        break
        if restored_cid in core.CHARACTER_MAP:
            self.current_char_id = restored_cid
            self.current_unit = core.CHARACTER_MAP[restored_cid]["unit"]
        elif restored_unit in core.UNIT_ORDER:
            self.current_unit = restored_unit
            for map_cid, info in core.CHARACTER_MAP.items():
                if info["unit"] == self.current_unit:
                    self.current_char_id = map_cid
                    break
        if self.user:
            self.update_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 의상실은 **{self.user.display_name}**님의 개인 의상실입니다. `/설정` (`👤 개인` ➔ `👗 캐릭터 3D 의상실`)에서 본인의 의상실을 열어보세요!",
                ephemeral=True
            )
            return False
        if not self.user:
            self.user = interaction.user
            self._restore_from_message(interaction)
            self.update_components()
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
        uid = self.user.id if self.user else 0
        unlocked = core.get_user_unlocked_costumes_for_char(self.guild_id, uid, self.current_char_id)
        equipped = core.get_user_equipped_costume(self.guild_id, uid, self.current_char_id)
        eq_id = equipped.get("costume_id")

        equip_opts = []
        seen_eq = set()
        for c in unlocked:
            c_val = str(c.get("costume_id") or "")
            if not c_val or c_val in seen_eq:
                continue
            seen_eq.add(c_val)
            is_active = (c_val == eq_id)
            tag = "[착용] " if is_active else ""
            label = f"{tag}{c['name']}"[:42]
            desc = f"{c.get('obtained_how', '기본')}"[:32]
            equip_opts.append(discord.SelectOption(
                label=label,
                value=c_val[:100],
                description=desc,
                default=is_active
            ))
            if len(equip_opts) >= 8:
                break
        if not equip_opts:
            equip_opts = [discord.SelectOption(label="기본 의상", value=f"default_{self.current_char_id}", default=True)]
        self.equip_select.options = equip_opts
        self.equip_select.disabled = False

        # 4. Shop / purchase select (Row 3)
        purchasable = core.get_purchasable_costumes_for_char(self.guild_id, uid, self.current_char_id)
        shop_opts = []
        seen_shop = set()
        for c in purchasable:
            c_val = str(c.get("costume_id") or "")
            if not c_val or c_val in seen_shop:
                continue
            seen_shop.add(c_val)
            label = f"💎 [300💎] {c['name']}"[:42]
            desc = f"★4 [{c.get('card_prefix')}] ({c.get('char_name')})"[:32]
            shop_opts.append(discord.SelectOption(
                label=label,
                value=c_val[:100],
                description=desc
            ))
            if len(shop_opts) >= 8:
                break
        if not shop_opts:
            self.shop_select.options = [
                discord.SelectOption(
                    label="제작 가능한 새 의상이 없습니다",
                    value="NONE",
                    description="가챠에서 ★4 카드를 뽑으면 해당 의상을 300💎로 제작할 수 있습니다."
                )
            ]
            self.shop_select.disabled = True
        else:
            self.shop_select.options = shop_opts
            self.shop_select.disabled = False

        # 5. Toggle & Another Color button state (Row 4)
        origin_char_id = equipped.get("origin_char_id")
        card_id = equipped.get("card_id")
        is_different_char = bool(origin_char_id is not None and origin_char_id != self.current_char_id and card_id and card_id > 0)
        self.btn_toggle_view.disabled = not is_different_char
        if not is_different_char:
            self.btn_toggle_view.label = "🖼️ 일러스트 일치함"
            self.btn_toggle_view.style = discord.ButtonStyle.secondary
        else:
            if self.view_mode == "char":
                origin_name = equipped.get("char_name", "원작")
                self.btn_toggle_view.label = f"👗 의상 원본 보기 ({origin_name})"
                self.btn_toggle_view.style = discord.ButtonStyle.secondary
            else:
                cur_name = core.CHARACTER_MAP.get(self.current_char_id, {}).get("name", "착용자")
                self.btn_toggle_view.label = f"👤 착용 모델 보기 ({cur_name})"
                self.btn_toggle_view.style = discord.ButtonStyle.primary

        if equipped.get("is_default"):
            self.btn_color_variant.disabled = True
            self.btn_color_variant.label = "🎨 어나더 컬러 (3D 전용)"
            self.btn_color_variant.style = discord.ButtonStyle.secondary
        elif equipped.get("another_color_unlocked"):
            self.btn_color_variant.disabled = False
            v_emoji = equipped.get("color_variant_emoji", "🎨")
            self.btn_color_variant.label = f"{v_emoji} 어나더 컬러 전환"
            self.btn_color_variant.style = (
                discord.ButtonStyle.success if equipped.get("color_variant", "orig") != "orig" else discord.ButtonStyle.primary
            )
        else:
            self.btn_color_variant.disabled = False
            self.btn_color_variant.label = "🔒 어나더 컬러 (MR.2)"
            self.btn_color_variant.style = discord.ButtonStyle.secondary

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
        origin_char_id = equipped.get("origin_char_id")
        card_id = equipped.get("card_id")
        is_different_char = bool(origin_char_id is not None and origin_char_id != self.current_char_id and card_id and card_id > 0)

        if equipped.get("card_prefix") and equipped.get("card_prefix") != "기본":
            if is_different_char:
                source_str = f"★4 [{equipped.get('card_prefix')}] {equipped.get('char_name')} 의상 제작/구매 (300💎)"
            else:
                source_str = f"★4 [{equipped.get('card_prefix')}] {equipped.get('char_name')} 뽑기 획득"

        embed = discord.Embed(
            title=f"👗 {char_info['name']}의 세카이 3D 의상실",
            description=f"🏷️ `{char_info['unit']}` · `{gender_kr}`",
            color=discord.Color.from_rgb(255, 105, 180) if gender_kr.startswith("여성") else discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )

        cos_lines = [
            f"👗 **`{equipped['name']}`**",
            f"└ 획득: {source_str}",
            f"└ 파츠: `{parts_str}` · 컬러: `{equipped.get('color_variant_label', '기본 오리지널 컬러')}`",
        ]
        if equipped.get("hair_unlocked"):
            cos_lines.append("└ 💇 **한정 헤어 해금됨** *(✦MR.2 특전 · 라이브 시너지 `+10%`)*")
        elif not equipped.get("is_default") and not equipped.get("another_color_unlocked"):
            cos_lines.append("└ 🔒 *어나더 컬러 3종: ✦MR.2 달성 시 해금*")
        if is_different_char:
            cos_lines.append(f"└ 💡 착용 모델 `{char_info['name']}` *(의상 원작: `{equipped.get('char_name')}`)*")

        embed.add_field(name="✨ 현재 착용 의상", value="\n".join(cos_lines)[:1024], inline=False)
        embed.add_field(name="💎 보유 크리스탈", value=f"**`{crystals:,} 💎`**", inline=True)
        embed.add_field(name="👕 보유 의상", value=f"**`{len(unlocked)}벌`**", inline=True)
        embed.add_field(name="🛍️ 제작 가능", value=f"**`{len(purchasable)}벌`** (`{core.COSTUME_PURCHASE_PRICE}💎`)", inline=True)

        # 1. 착용 캐릭터(현재 선택한 캐릭터)의 대표 카드 찾기
        g_key = str(self.guild_id or 0)
        u_key = str(self.user.id)
        user_cards_dict = core.safe_get_dict(data, "gacha_users", g_key, u_key, "cards")
        my_char_cards = [
            c for c in user_cards_dict.values()
            if isinstance(c, dict) and MyInventoryView._resolve_card_char_id(c) == self.current_char_id
        ]

        char_card = None
        if my_char_cards:
            my_char_cards.sort(
                key=lambda x: (
                    -core._safe_card_int(x.get("star_num") if x.get("star_num") is not None else x.get("rarity"), 1),
                    -int(bool(x.get("is_limited", False))),
                    -core._safe_card_int(x.get("count"), 1),
                    -core._safe_card_int(x.get("id"), 0),
                )
            )
            char_card = my_char_cards[0]
        else:
            char_card = next((c for c in core.PROSEKA_KR_CARDS if c.get("char_id") == self.current_char_id and c.get("rarity_type") == "rarity_4"), None)
            if not char_card:
                char_card = next((c for c in core.PROSEKA_KR_CARDS if c.get("char_id") == self.current_char_id), None)

        # 2. 의상 원작 카드
        cos_card_obj = core.get_proseka_card_by_id(card_id) if card_id else None

        active_card = None
        if not is_different_char:
            target_card = cos_card_obj or char_card
            active_card = target_card
            if target_card:
                embed.set_image(url=core.get_proseka_card_image_url(target_card, self.illust_stage))
            embed.set_footer(text=f"{self.user.display_name} • 동일 체형 다른 캐릭터에게 {core.COSTUME_PURCHASE_PRICE}💎로 제작 가능")
        else:
            if self.view_mode == "char":
                active_card = char_card
                if char_card:
                    embed.set_image(url=core.get_proseka_card_image_url(char_card, self.illust_stage))
                if cos_card_obj:
                    embed.set_thumbnail(url=core.get_proseka_card_image_url(cos_card_obj, "normal"))
                embed.set_footer(text=f"일러스트: 착용 모델 [{char_info['name']}] • 하단 버튼으로 의상 원본 전환")
            else:
                active_card = cos_card_obj
                if cos_card_obj:
                    embed.set_image(url=core.get_proseka_card_image_url(cos_card_obj, self.illust_stage))
                if char_card:
                    embed.set_thumbnail(url=core.get_proseka_card_image_url(char_card, "normal"))
                embed.set_footer(text=f"일러스트: 의상 원작 [{equipped.get('char_name')}] • 하단 버튼으로 착용 모델 전환")

        can_train_active = bool(active_card and core.can_card_awaken(active_card))
        self.btn_stage_normal.disabled = (not can_train_active) or (self.illust_stage == "normal")
        self.btn_stage_trained.disabled = (not can_train_active) or (self.illust_stage == "after_training")
        return embed

    @discord.ui.select(
        placeholder="🏷️ 1단계: 유닛(그룹)을 선택하세요...",
        options=[discord.SelectOption(label="유닛 불러오는 중...", value="Leo/need")],
        row=0,
    )
    async def unit_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await core.safe_defer(interaction)
        self.current_unit = select.values[0]
        self.view_mode = "char"
        self.illust_stage = "normal"
        for cid, info in core.CHARACTER_MAP.items():
            if info["unit"] == self.current_unit:
                self.current_char_id = cid
                break
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="👤 2단계: 캐릭터를 선택하세요...",
        options=[discord.SelectOption(label="캐릭터 불러오는 중...", value="1")],
        row=1,
    )
    async def char_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await core.safe_defer(interaction)
        try:
            self.current_char_id = int(select.values[0])
        except Exception:
            self.current_char_id = 1
        self.view_mode = "char"
        self.illust_stage = "normal"
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="👗 3단계: 착용할 보유 의상을 선택하세요...",
        options=[discord.SelectOption(label="보유 의상 불러오는 중...", value="DEFAULT")],
        row=2,
    )
    async def equip_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await core.safe_defer(interaction)
        cos_id = select.values[0]
        self.view_mode = "char"
        self.illust_stage = "normal"
        ok, msg, cos = await asyncio.to_thread(core.equip_user_costume, self.guild_id, interaction.user.id, self.current_char_id, cos_id)
        if ok:
            await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
            await core.safe_send_response(interaction, msg, ephemeral=True)
        else:
            await core.safe_send_response(interaction, f"❌ {msg}", ephemeral=True)

    @discord.ui.select(
        placeholder="🛍️ 4단계: 다른 캐릭터 의상 제작/구매 (300 💎)...",
        options=[discord.SelectOption(label="제작 가능 의상 없음", value="NONE")],
        row=3,
    )
    async def shop_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        cos_id = select.values[0]
        if cos_id == "NONE":
            await core.safe_defer(interaction)
            return
        await core.safe_defer(interaction)
        self.view_mode = "char"
        self.illust_stage = "normal"
        ok, msg, cos, rem = await asyncio.to_thread(core.purchase_and_equip_costume, self.guild_id, interaction.user.id, self.current_char_id, cos_id)
        if ok:
            await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
            await core.safe_send_response(interaction, f"🎉 {msg} (남은 크리스탈: `{rem:,} 💎`)", ephemeral=True)
        else:
            await core.safe_send_response(interaction, f"❌ {msg}", ephemeral=True)

    @discord.ui.button(label="🌸 특훈 전", style=discord.ButtonStyle.secondary, row=4)
    async def btn_stage_normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.illust_stage = "normal"
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="✨ 특훈 후", style=discord.ButtonStyle.primary, row=4)
    async def btn_stage_trained(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.illust_stage = "after_training"
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🖼️ 일러스트 전환", style=discord.ButtonStyle.secondary, row=4)
    async def btn_toggle_view(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.view_mode = "costume" if self.view_mode == "char" else "char"
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🎨 어나더 컬러", style=discord.ButtonStyle.secondary, row=4)
    async def btn_color_variant(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg, v_info = await asyncio.to_thread(core.cycle_user_costume_color, self.guild_id, interaction.user.id, self.current_char_id)
        if ok:
            await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
            await core.safe_send_response(interaction, f"{msg}\n*(💡 어나더 컬러 적용 시 `/설정` (`⚔️ 세카이 라이브`) 보너스가 `+10%`로 강화됩니다!)*", ephemeral=True)
        else:
            await core.safe_send_response(interaction, msg, ephemeral=True)

    @discord.ui.button(label="ℹ️ 의상 시스템 안내", style=discord.ButtonStyle.secondary, row=4)
    async def btn_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        info_emb = discord.Embed(
            title="👗 세카이 3D 의상 & 어나더 컬러 안내",
            color=discord.Color.from_rgb(255, 105, 180),
        )
        info_emb.add_field(
            name="🎰 의상 획득 (가챠 연동)",
            value="3D 의상이 포함된 ★4 카드를 뽑으면 해당 원본 캐릭터에게 **자동 무료 해금**됩니다.",
            inline=False,
        )
        info_emb.add_field(
            name="🎨 어나더 컬러 & 한정 헤어 (✦MR.2)",
            value=(
                "원본 카드를 **✦MR.2 이상** 돌파하면 어나더 컬러 3종(파스텔·다크·골드)과 한정 헤어가 해금됩니다.\n"
                "└ 적용 시 세카이 라이브 멤버당 **`+10%` 시너지**가 추가됩니다."
            ),
            inline=False,
        )
        info_emb.add_field(
            name="🛍️ 다른 캐릭터에게 제작/입히기",
            value=f"보유 카드 의상을 **동일 체형(여성/남성)** 의 다른 캐릭터에게 **`{core.COSTUME_PURCHASE_PRICE} 💎`** 로 제작해 입힐 수 있습니다.",
            inline=False,
        )
        await core.safe_send_response(interaction, embed=info_emb, ephemeral=True)


class ProsekaRatePaginationView(core.SafeView):
    def __init__(self, all_prob_cards=None, pickup_cfg=None, items_per_page=5, banner_type: str = "normal"):
        super().__init__(timeout=600)
        self.banner_type = banner_type if banner_type in core.BANNER_CONFIGS else "normal"
        pickup_cfg = core.as_dict(pickup_cfg)
        if not pickup_cfg:
            d = core.get_cached_data()
            pickup_cfg = core.as_dict(d.get("gacha_pickup")) or core.DEFAULT_CONFIG["gacha_pickup"]
        self.pickup_cfg = pickup_cfg
        if not all_prob_cards:
            all_prob_cards = core.calculate_card_probabilities(self.pickup_cfg, banner_type=self.banner_type)
        self.all_prob_cards = list(all_prob_cards or [])
        self.filtered_cards = list(self.all_prob_cards)
        self.items_per_page = items_per_page
        self.current_page = 0
        self.current_filter_val = "ALL"
        self.current_filter = "전체"
        self.update_buttons()

    @property
    def max_page(self):
        if not self.filtered_cards:
            return 0
        return (len(self.filtered_cards) - 1) // self.items_per_page

    def _apply_filter(self, val: str):
        self.current_filter_val = val
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

    def update_buttons(self):
        is_first = (self.current_page <= 0)
        is_last = (self.current_page >= self.max_page)
        self.back_5.disabled = is_first
        self.prev_page.disabled = is_first
        self.page_indicator.label = f"📄 {self.current_page + 1} / {self.max_page + 1}"
        self.next_page.disabled = is_last
        self.forward_5.disabled = is_last

        self.banner_select.options = [
            discord.SelectOption(
                label="🌟 일반 / 현재 픽업 가챠 (★4 3.0%)",
                value="normal",
                default=(self.banner_type == "normal"),
            ),
            discord.SelectOption(
                label="🎊 컬러풀 페스티벌 (★4 2배 · 6.0%!)",
                value="fes",
                default=(self.banner_type == "fes"),
            ),
            discord.SelectOption(
                label="🎂 생일 / 기념일 스페셜 가챠 (★4·생일 3.5%)",
                value="birthday",
                default=(self.banner_type == "birthday"),
            ),
        ]
        core.sync_page_number_buttons(
            self,
            current_page=self.current_page,
            total_pages=self.max_page + 1,
            row=3,
            on_select=self._on_page_num_selected,
            zero_indexed=True,
            max_buttons=5,
            active_style=discord.ButtonStyle.primary,
            custom_id_prefix="norosi:ProsekaRate:p",
        )

    async def _on_page_num_selected(self, interaction: discord.Interaction, target_page: int):
        await core.safe_defer(interaction)
        self.current_page = max(0, min(target_page, self.max_page))
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    def build_embed(self):
        self.update_buttons()
        total_cards = len(self.filtered_cards)
        start_idx = self.current_page * self.items_per_page
        page_items = self.filtered_cards[start_idx:start_idx + self.items_per_page]

        b_cfg = core.BANNER_CONFIGS.get(self.banner_type, core.BANNER_CONFIGS["normal"])
        pickup_summary = core.format_pickup_summary(self.pickup_cfg)
        inc_lim = "포함" if (self.banner_type in ("fes", "birthday") or self.pickup_cfg.get("include_limited", True)) else "제외 (통상만)"

        embed = discord.Embed(
            title=f"🎲 프로세카 확률표 — {b_cfg['short_name']}",
            description=f"🎰 **배너:** `{b_cfg['name']}` · 필터 `{self.current_filter}` (`{total_cards:,} / {len(self.all_prob_cards):,}장`)",
            color=discord.Color.from_rgb(*b_cfg.get("color", (0, 204, 221)))
        )
        embed.add_field(
            name="📊 등급 합산 확률",
            value=f"🌟 ★4·🎂생일 **`{b_cfg['top_rate']:.1f}%`** · 💫 ★3 `{b_cfg['mid_rate']:.1f}%` · ⭐ ★2·★1 `{b_cfg['low_rate']:.1f}%`",
            inline=False,
        )
        embed.add_field(
            name="🎯 현재 픽업 · 한정",
            value=f"`{core.truncate_text(pickup_summary, 70)}` · 한정 `{inc_lim}`",
            inline=False,
        )

        if not page_items:
            embed.add_field(name="📭 검색 결과 없음", value="해당 조건에 맞는 카드가 없습니다.", inline=False)
        else:
            lines = []
            for idx, c in enumerate(page_items, start=start_idx + 1):
                pickup_badge = " 🎯`픽업`" if c.get("is_pickup") else ""
                unit_str = f"{c['unit']}" + (f" ({c['support_unit']})" if c.get("support_unit") else "")
                lines.append(
                    f"`{idx:02d}.` **`{c['prob']:.4f}%`** · **{c['rarity_label']} {c['char_name']}** [{c['prefix']}]{pickup_badge}\n"
                    f"└ `{c['limit_label']}` · `{unit_str}` · {c['attr']} *(ID: `{c['id']}`)*"
                )
            core.add_chunked_embed_fields(
                embed,
                f"📖 카드 목록 (페이지 {self.current_page + 1} / {self.max_page + 1})",
                lines,
                separator="\n\n",
                max_chars=950,
            )

        embed.set_footer(text="하단 드롭다운에서 필터 또는 배너(일반/페스티벌/생일)별 확률을 전환할 수 있습니다")
        return embed

    @discord.ui.button(label="⏪ -5", style=discord.ButtonStyle.secondary, row=0)
    async def back_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.current_page = max(0, self.current_page - 5)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.primary, row=0)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.current_page = max(0, self.current_page - 1)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="📄 1 / 1", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.current_page = min(self.max_page, self.current_page + 1)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="+5 ⏩", style=discord.ButtonStyle.secondary, row=0)
    async def forward_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.current_page = min(self.max_page, self.current_page + 5)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="🔍 성급 / 한정 / 유닛별 필터 선택...",
        row=1,
        options=[
            discord.SelectOption(label="전체 보기", value="ALL", description="모든 한국 서버 캐릭터 카드 표시"),
            discord.SelectOption(label="🎯 현재 픽업 대상만", value="PICKUP", description="배너/봇주인 픽업 대상 카드만 표시"),
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
        await core.safe_defer(interaction)
        self._apply_filter(select.values[0])
        self.current_page = 0
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="🎰 확률표 배너 선택 (일반 / 페스티벌 / 생일)...",
        row=2,
        options=[discord.SelectOption(label="일반", value="normal")]
    )
    async def banner_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await core.safe_defer(interaction)
        self.banner_type = select.values[0]
        self.all_prob_cards = core.calculate_card_probabilities(self.pickup_cfg, banner_type=self.banner_type)
        self._apply_filter(self.current_filter_val)
        self.current_page = 0
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


class MyInventoryView(core.SafeView):
    """내 캐릭터 보관함 (유닛/캐릭터별 필터 + 검색어 필터 + 정렬 + 잠금 표시 + 중복 카드 크리스탈 변환 + 일러스트 & 각성 전환)"""
    def __init__(
        self,
        user: discord.User | None = None,
        card_list: list | None = None,
        items_per_page=10,
        search_keyword: str = None,
        guild_id: int = 0,
        initial_unit: str | None = None,
        initial_char_id: int | None = None,
    ):
        super().__init__(timeout=600)
        self.user = user
        self.guild_id = guild_id
        if card_list:
            self.all_cards = [c for c in card_list if isinstance(c, dict)]
        elif self.user:
            self.all_cards = self._load_user_cards()
        else:
            self.all_cards = []
        self.cards: list = []
        self.items_per_page = items_per_page
        self.search_keyword = search_keyword
        self.current_page = 0
        self.sort_mode = "obtained_desc"
        self.sort_mode_label = "획득일 최신순"
        self.selected_unit = initial_unit if (initial_unit in core.UNIT_ORDER) else "ALL"
        self.selected_char_id = int(initial_char_id) if initial_char_id is not None else None
        self.has_more_chars_notice = False
        self.apply_filters_and_sort()

    def _load_user_cards(self) -> list[dict]:
        if not self.user:
            return []
        d = core.get_cached_data_ro()
        u_cards = core.safe_get_dict(d, "gacha_users", str(self.guild_id or 0), str(self.user.id), "cards")
        out = []
        seen = set()
        for k, c in u_cards.items():
            if not isinstance(c, dict):
                continue
            raw_id = c.get("id") if c.get("id") is not None else k
            cid_s = str(raw_id).strip()
            if not cid_s or cid_s in seen:
                continue
            seen.add(cid_s)
            if c.get("id") is None:
                c = dict(c)
                c["id"] = int(cid_s) if cid_s.isdigit() else cid_s
            out.append(c)
        return out

    def _restore_from_message(self, interaction: discord.Interaction):
        msg = getattr(interaction, "message", None)
        if not msg:
            return
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if self.user and not self.all_cards:
            self.all_cards = self._load_user_cards()
        for row in getattr(msg, "components", []) or []:
            for comp in getattr(row, "children", []):
                cid = getattr(comp, "custom_id", "") or ""
                if cid.endswith(":unit_select"):
                    for opt in getattr(comp, "options", []):
                        if getattr(opt, "default", False) and getattr(opt, "value", None):
                            self.selected_unit = str(opt.value)
                elif cid.endswith(":char_select"):
                    for opt in getattr(comp, "options", []):
                        if getattr(opt, "default", False) and getattr(opt, "value", None):
                            val_s = str(opt.value)
                            self.selected_char_id = int(val_s) if val_s.isdigit() else None
        embeds = getattr(msg, "embeds", None) or []
        if embeds:
            import re
            emb = embeds[0]
            if emb.description:
                sort_map = {
                    "획득일 최신순": "obtained_desc",
                    "획득일 오래된순": "obtained_asc",
                    "성(레어도) 높은순": "star_desc",
                    "성(레어도) 낮은순": "star_asc",
                    "유닛 기준": "unit",
                    "캐릭터 이름순": "char_name",
                    "중복 보유 많은순": "count_desc",
                    "🔒 잠금 카드 우선": "locked_only",
                }
                for lbl, sm in sort_map.items():
                    if f"`{lbl}`" in emb.description:
                        self.sort_mode = sm
                        break
            for f in getattr(emb, "fields", []) or []:
                m = re.search(r"\(페이지\s*(\d+)\s*/\s*(\d+)\)", getattr(f, "name", "") or "")
                if m:
                    self.current_page = max(0, int(m.group(1)) - 1)
                    break
        self.apply_filters_and_sort()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 보관함은 **{self.user.display_name}**님의 개인 보관함입니다. `/설정` (`👤 개인` ➔ `🎒 프로세카 카드 보관함`)에서 본인의 보관함을 열어보세요!",
                ephemeral=True
            )
            return False
        if not self.user:
            self.user = interaction.user
            self._restore_from_message(interaction)
        elif not self.all_cards:
            self.all_cards = self._load_user_cards()
            self.apply_filters_and_sort()
        return True

    @staticmethod
    def _resolve_card_char_id(card: dict) -> int | None:
        if not isinstance(card, dict):
            return None
        cid = card.get("char_id")
        if cid is not None and cid != "":
            try:
                cid_int = int(cid)
                if cid_int in core.CHARACTER_MAP:
                    return cid_int
            except Exception:
                pass
        cname = str(card.get("char_name") or "").strip()
        if cname:
            for map_cid, info in core.CHARACTER_MAP.items():
                if info.get("name") == cname:
                    return map_cid
        raw_id = card.get("id")
        if raw_id is not None:
            raw_str = str(raw_id).strip()
            ref = core.get_proseka_card_by_id(raw_str)
            if ref is not None:
                ref_cid = ref.get("char_id")
                if ref_cid is not None:
                    try:
                        ref_cid_int = int(ref_cid)
                        if ref_cid_int in core.CHARACTER_MAP:
                            return ref_cid_int
                    except Exception:
                        pass
        return None

    @classmethod
    def _card_matches_unit(cls, card: dict, unit_name: str) -> bool:
        if unit_name == "ALL":
            return True
        if card.get("unit") == unit_name or card.get("support_unit") == unit_name:
            return True
        cid = cls._resolve_card_char_id(card)
        if cid in core.CHARACTER_MAP and core.CHARACTER_MAP[cid].get("unit") == unit_name:
            return True
        return False

    def apply_filters_and_sort(self, mode: str | None = None):
        if mode is not None:
            self.sort_mode = mode
        filtered = list(self.all_cards)
        if self.selected_unit != "ALL":
            filtered = [c for c in filtered if self._card_matches_unit(c, self.selected_unit)]
        if self.selected_char_id is not None:
            filtered = [c for c in filtered if self._resolve_card_char_id(c) == self.selected_char_id]
        self.cards = filtered
        self.apply_sort(self.sort_mode)
        if self.current_page > self.max_page:
            self.current_page = self.max_page
        self.update_filter_selects()
        self.update_illust_select()

    def update_filter_selects(self):
        # Row 3: 유닛별 필터
        unit_emojis = {
            "Leo/need": "🎸",
            "MORE MORE JUMP!": "🍀",
            "Vivid BAD SQUAD": "🎧",
            "원더랜즈×쇼타임": "🎪",
            "25시, 나이트 코드에서.": "🌃",
            "버츄얼 싱어": "🎤",
        }
        total_unique_all = len(self.all_cards)
        unit_opts = [
            discord.SelectOption(
                label=f"전체 유닛 ({total_unique_all}종)"[:45],
                value="ALL",
                default=(self.selected_unit == "ALL"),
            )
        ]
        for u_name in core.UNIT_ORDER:
            u_cards = [c for c in self.all_cards if self._card_matches_unit(c, u_name)]
            u_emoji = unit_emojis.get(u_name, "🏷️")
            unit_opts.append(
                discord.SelectOption(
                    label=f"{u_emoji} {u_name} ({len(u_cards)}종)"[:45],
                    value=u_name,
                    default=(self.selected_unit == u_name),
                )
            )
        self.unit_select.options = unit_opts[:25]

        # Row 4: 캐릭터별 필터
        base_pool = (
            self.all_cards
            if self.selected_unit == "ALL"
            else [c for c in self.all_cards if self._card_matches_unit(c, self.selected_unit)]
        )
        char_counts: dict[int, tuple[int, int]] = {}
        for c in base_pool:
            cid = self._resolve_card_char_id(c)
            if cid is None:
                continue
            prev_u, prev_p = char_counts.get(cid, (0, 0))
            char_counts[cid] = (prev_u + 1, prev_p + int(c.get("count", 1)))

        if self.selected_unit == "ALL":
            all_char_label = f"전체 캐릭터 ({len(base_pool)}종)"
            candidate_cids = sorted(cid for cid in char_counts.keys() if cid in core.CHARACTER_MAP)
            if self.selected_char_id is not None and self.selected_char_id in core.CHARACTER_MAP and self.selected_char_id not in candidate_cids:
                candidate_cids.append(self.selected_char_id)
                candidate_cids.sort()
        else:
            all_char_label = f"{self.selected_unit} 전체 ({len(base_pool)}종)"
            unit_member_cids = [cid for cid, info in core.CHARACTER_MAP.items() if info.get("unit") == self.selected_unit]
            extra_cids = [cid for cid in sorted(char_counts.keys()) if cid in core.CHARACTER_MAP and cid not in unit_member_cids]
            candidate_cids = unit_member_cids + extra_cids

        char_opts = [
            discord.SelectOption(
                label=all_char_label[:45],
                value="ALL",
                default=(self.selected_char_id is None),
            )
        ]

        self.has_more_chars_notice = False
        if len(candidate_cids) > 24:
            self.has_more_chars_notice = True
            display_cids = candidate_cids[:24]
            if self.selected_char_id is not None and self.selected_char_id in candidate_cids and self.selected_char_id not in display_cids:
                display_cids = display_cids[:-1] + [self.selected_char_id]
        else:
            display_cids = candidate_cids

        for cid in display_cids:
            c_info = core.CHARACTER_MAP.get(cid, {"name": f"캐릭터 #{cid}", "unit": "-"})
            u_cnt, _ = char_counts.get(cid, (0, 0))
            short_name = c_info["name"].split()[-1] if " " in c_info["name"] else c_info["name"]
            char_opts.append(
                discord.SelectOption(
                    label=f"{short_name} ({u_cnt})"[:32],
                    value=str(cid),
                    default=(self.selected_char_id == cid),
                )
            )
        self.char_select.options = char_opts[:25]

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
            seen_vals = set()
            start_idx = self.current_page * self.items_per_page
            for idx, c in enumerate(page_items[:10], start=start_idx + 1):
                cid_val = str(c.get("id") or idx)
                if cid_val in seen_vals:
                    continue
                seen_vals.add(cid_val)
                lock_icon = "🔒" if c.get("locked", False) else ""
                mr = int(c.get("master_rank", 0))
                mr_desc = f"·MR{mr}" if mr > 0 else ""
                r_short = core.get_card_rarity_short_label(c)
                raw_cn = str(c.get("char_name") or "")
                short_cn = raw_cn.split()[-1] if " " in raw_cn else raw_cn
                label = f"{idx}.{lock_icon}{r_short} {short_cn} [{c['prefix'][:6]}] ({c.get('count', 1)}{mr_desc})"[:36]
                desc = (
                    "🌸특훈 전(기본) · ✨특훈 후 버튼 전환 및 잠금 관리"
                    if core.can_card_awaken(c)
                    else "🖼️ 카드 일러스트 감상 및 잠금 관리"
                )
                opts.append(discord.SelectOption(label=label, value=cid_val[:100], description=desc))
            self.illust_select.options = opts[:25] or [discord.SelectOption(label="표시할 카드가 없습니다", value="NONE")]
            self.illust_select.disabled = not bool(opts)

    def apply_sort(self, mode: str):
        self.sort_mode = mode
        if mode == "obtained_desc":
            self.cards.sort(key=lambda x: x.get("last_obtained_at", ""), reverse=True)
            self.sort_mode_label = "획득일 최신순"
        elif mode == "obtained_asc":
            self.cards.sort(key=lambda x: x.get("obtained_at", ""))
            self.sort_mode_label = "획득일 오래된순"
        elif mode == "star_desc":
            self.cards.sort(key=lambda x: (-x.get("star_num", 1), -int(x.get("is_limited", False)), x.get("char_id", 99)))
            self.sort_mode_label = "성(레어도) 높은순"
        elif mode == "star3_first":
            self.cards.sort(key=lambda x: (0 if (x.get("rarity_type") == "rarity_3" or x.get("star_num") == 3) else 1, -x.get("star_num", 1), x.get("char_id", 99)))
            self.sort_mode_label = "★★★ (3성) 우선"
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
        self.update_filter_selects()
        self.update_illust_select()
        total_unique = len(self.cards)
        total_pulls = sum(c.get("count", 1) for c in self.cards)
        locked_cnt = sum(1 for c in self.cards if c.get("locked", False))
        dup_cnt = sum(max(0, c.get("count", 1) - 1) for c in self.cards if not c.get("locked", False))
        start_idx = self.current_page * self.items_per_page
        page_items = self.get_current_page_items()

        unit_label = "전체 유닛" if self.selected_unit == "ALL" else self.selected_unit
        char_label = (
            core.CHARACTER_MAP.get(self.selected_char_id, {}).get("name", f"캐릭터 #{self.selected_char_id}")
            if self.selected_char_id is not None
            else "전체 캐릭터"
        )
        is_filtered = (self.selected_unit != "ALL" or self.selected_char_id is not None)
        all_scope_note = f" / 전체 `{len(self.all_cards):,}종`" if is_filtered else ""

        desc_parts = [f"🔍 **필터:** `{unit_label}` · `{char_label}` · **정렬:** `{self.sort_mode_label}`"]
        if self.search_keyword:
            desc_parts.append(f"🔎 **검색어:** `{self.search_keyword}`")
        if self.has_more_chars_notice:
            desc_parts.append("> 💡 *25명 이상 보유 시 유닛 필터를 먼저 선택하면 모든 캐릭터가 표시됩니다.*")

        embed = discord.Embed(
            title=f"🎒 {self.user.display_name}님의 카드 보관함",
            description="\n".join(desc_parts),
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.add_field(name="🃏 보유 카드", value=f"**`{total_unique:,}종`** *(누적 `{total_pulls:,}장`{all_scope_note})*", inline=True)
        embed.add_field(name="🔒 잠금 보호", value=f"**`{locked_cnt:,}종`**", inline=True)
        embed.add_field(name="💎 변환 가능 중복", value=f"**`{dup_cnt:,}장`**", inline=True)

        if not page_items:
            if self.selected_char_id is not None or self.selected_unit != "ALL":
                empty_msg = f"`{unit_label}` · `{char_label}` 조건에 해당하는 보유 카드가 없습니다. 하단 드롭다운에서 필터를 변경해 보세요."
            elif self.search_keyword:
                empty_msg = f"`{self.search_keyword}` 검색 조건에 맞는 보유 카드가 없습니다."
            else:
                empty_msg = "`/설정` (`🎮 미니게임` ➔ `🎰 프로세카 뽑기`)에서 첫 카드를 뽑아보세요!"
            embed.add_field(name="📭 조회된 카드 없음", value=empty_msg, inline=False)
        else:
            lines = []
            for idx, c in enumerate(page_items, start=start_idx + 1):
                unit_str = f"{c['unit']}" + (f" ({c['support_unit']})" if c.get("support_unit") else "")
                lock_badge = "🔒 " if c.get("locked", False) else ""
                mr = int(c.get("master_rank", 0))
                mr_tag = f" · `✦MR.{mr}`" if mr > 0 else ""
                cur_lvl = c.get("level", 1)
                max_lvl = core.get_card_max_level(c)
                power_val = core.get_card_power(c)
                cos = core.get_costume_for_card(c.get("id"))
                cos_tag = " · 👗" if cos else ""
                cnt_val = c.get("count", 1)
                cnt_tag = f" `×{cnt_val}`" if cnt_val > 1 else ""
                lines.append(
                    f"`{idx:02d}.` {lock_badge}**{c['rarity_label']} {c['char_name']}** [{c['prefix']}]{cnt_tag}{mr_tag}\n"
                    f"└ `{c.get('limit_label', '통상')}` · `{unit_str}` · {c.get('attr', '✨')}{cos_tag} · `Lv.{cur_lvl}/{max_lvl}` · `⚔️{power_val:,}`"
                )
            core.add_chunked_embed_fields(
                embed,
                f"📖 보유 카드 목록 (페이지 {self.current_page + 1} / {self.max_page + 1})",
                lines,
                separator="\n",
                max_chars=950
            )

        embed.set_footer(text="하단 드롭다운으로 필터링 · ★3·★4 특훈 전·후 일러스트 감상 · 잠금(🔒) 관리가 가능합니다")
        return embed

    @discord.ui.button(label="⏪ -5", style=discord.ButtonStyle.secondary, row=0)
    async def back_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.current_page = max(0, self.current_page - 5)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.primary, row=0)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.current_page = max(0, self.current_page - 1)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.current_page = min(self.max_page, self.current_page + 1)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="+5 ⏩", style=discord.ButtonStyle.secondary, row=0)
    async def forward_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.current_page = min(self.max_page, self.current_page + 5)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="💎 중복변환", style=discord.ButtonStyle.success, row=0)
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
        placeholder="📊 정렬 기준 선택...",
        row=1,
        options=[
            discord.SelectOption(label="획득 최신순", value="obtained_desc"),
            discord.SelectOption(label="획득 오래된순", value="obtained_asc"),
            discord.SelectOption(label="레어도 높은순 (★4·생일 우선)", value="star_desc"),
            discord.SelectOption(label="★★★ (3성) 카드 우선 보기", value="star3_first"),
            discord.SelectOption(label="레어도 낮은순", value="star_asc"),
            discord.SelectOption(label="잠금 카드 우선", value="locked_only"),
            discord.SelectOption(label="유닛 기준", value="unit"),
            discord.SelectOption(label="캐릭터 이름순", value="char_name"),
            discord.SelectOption(label="중복 많은순", value="count_desc")
        ]
    )
    async def sort_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await core.safe_defer(interaction)
        self.apply_sort(select.values[0])
        self.current_page = 0
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="🖼️ 카드 일러스트(★3·★4 특훈 전·후)·잠금 선택...",
        row=2,
        options=[discord.SelectOption(label="카드 선택", value="NONE")]
    )
    async def illust_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        cid_val = select.values[0]
        if cid_val == "NONE":
            await core.safe_send_response(interaction, "ℹ️ 현재 페이지에서 감상할 카드를 선택해주세요.", ephemeral=True)
            return
        selected_card = next((c for c in self.cards if str(c.get("id")) == cid_val), None)
        if not selected_card:
            selected_card = next((c for c in self.all_cards if str(c.get("id")) == cid_val), None)
        if not selected_card:
            gid_s = str(self.guild_id or (interaction.guild_id or 0))
            uid_s = str(self.user.id if self.user else interaction.user.id)
            u_cards = core.safe_get_dict(core.get_cached_data_ro(), "gacha_users", gid_s, uid_s, "cards")
            cand = u_cards.get(cid_val)
            if isinstance(cand, dict):
                selected_card = cand
            else:
                selected_card = next((c for c in u_cards.values() if isinstance(c, dict) and str(c.get("id")) == cid_val), None)
        if not selected_card:
            selected_card = core.get_proseka_card_by_id(cid_val)
        if not selected_card:
            await core.safe_send_response(interaction, "❌ 선택한 카드 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        toggle_view = CardIllustToggleView(
            selected_card,
            initial_mode="normal",
            guild_id=self.guild_id or (interaction.guild_id or 0),
            owner_id=self.user.id if self.user else interaction.user.id,
            parent_inventory_view=self,
            parent_inventory_message=interaction.message
        )
        embeds, files = await toggle_view.build_embeds_and_files()
        if files:
            await interaction.followup.send(embeds=embeds, files=files, view=toggle_view, wait=True)
        else:
            await interaction.followup.send(embeds=embeds, view=toggle_view, wait=True)

    @discord.ui.select(
        placeholder="🏷️ 유닛별 필터...",
        row=3,
        options=[discord.SelectOption(label="🌐 전체 유닛", value="ALL")]
    )
    async def unit_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await core.safe_defer(interaction)
        chosen_unit = select.values[0]
        self.selected_unit = chosen_unit
        if self.selected_char_id is not None and chosen_unit != "ALL":
            char_unit = core.CHARACTER_MAP.get(self.selected_char_id, {}).get("unit")
            has_match = any(
                self._card_matches_unit(c, chosen_unit) and self._resolve_card_char_id(c) == self.selected_char_id
                for c in self.all_cards
            )
            if char_unit != chosen_unit and not has_match:
                self.selected_char_id = None
        self.current_page = 0
        self.apply_filters_and_sort()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="👤 캐릭터별 필터...",
        row=4,
        options=[discord.SelectOption(label="🌐 전체 캐릭터", value="ALL")]
    )
    async def char_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await core.safe_defer(interaction)
        chosen = select.values[0]
        try:
            self.selected_char_id = None if chosen == "ALL" else int(chosen)
        except Exception:
            self.selected_char_id = None
        self.current_page = 0
        self.apply_filters_and_sort()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


class CardPokedexView(core.SafeView):
    """
    전체 카드 도감 뷰 (/카드도감)
    - 탭 1: 📊 캐릭터별 수집률 (%) (유닛/캐릭터별 보유율 게이지 및 상세 체크리스트)
    - 탭 2: 🔒 미획득 카드 (아직 획득하지 못한 카드만 별도 필터링 및 일러스트 미리보기)
    - 탭 3: ✨ 보유 완료 카드 (수집 완료한 도감 카드 목록)
    """
    def __init__(self, user: discord.User | None = None, stats: dict | None = None, guild_id: int = 0, initial_tab: str = "char_rates"):
        super().__init__(timeout=600)
        self.user = user
        self.guild_id = guild_id
        if stats:
            self.stats = stats
        elif self.user:
            self.stats = core.get_card_pokedex_stats(self.guild_id, self.user.id)
        else:
            self.stats = {}
        self.active_tab = initial_tab  # "char_rates" | "unowned" | "owned"
        self.filter_val = "ALL"
        self.filter_label = "전체 (26명)"
        self.current_page = 0
        self.update_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 도감은 **{self.user.display_name}**님의 개인 도감입니다. `/설정` (`🎮 미니게임` ➔ `📚 통합 도감 & 확률 허브`)에서 본인의 도감을 열어보세요!",
                ephemeral=True
            )
            return False
        if not self.user:
            self.user = interaction.user
            if not self.stats:
                self.stats = await asyncio.to_thread(core.get_card_pokedex_stats, self.guild_id, self.user.id)
                self.update_components()
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
        elif self.filter_val == "R2":
            cards = [c for c in cards if c.get("rarity_type") == "rarity_2"]
        elif self.filter_val == "R1":
            cards = [c for c in cards if c.get("rarity_type") == "rarity_1"]
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
        r1 = r_stats.get("rarity_1", {"owned": 0, "total": 0})

        tab_labels = {
            "char_rates": "📊 캐릭터별 수집률",
            "unowned": f"🔒 미획득 카드 ({tot_unowned:,}종)",
            "owned": f"✨ 보유 카드 ({tot_owned:,}종)",
        }
        embed_color = (
            discord.Color.from_rgb(0, 204, 221)
            if self.active_tab == "char_rates"
            else (discord.Color.from_rgb(255, 105, 180) if self.active_tab == "unowned" else discord.Color.gold())
        )

        embed = discord.Embed(
            title=f"📖 {self.user.display_name}님의 카드 도감 — {tab_labels.get(self.active_tab)}",
            description=f"🔍 **필터:** `{self.filter_label}`",
            color=embed_color,
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.add_field(
            name="📊 전체 도감 달성률",
            value=(
                f"**{tot_owned:,} / {tot_master:,}종** *(미획득 `{tot_unowned:,}종`)*\n"
                f"{overall_bar}"
            ),
            inline=False,
        )
        embed.add_field(
            name="🌟 성급별 수집",
            value=(
                f"★4 `{r4['owned']}/{r4['total']}` · 🎂 생일 `{rb['owned']}/{rb['total']}`\n"
                f"★3 `{r3['owned']}/{r3['total']}` · ★2 `{r2['owned']}/{r2['total']}` · ★1 `{r1['owned']}/{r1['total']}`"
            ),
            inline=False,
        )

        items = self.get_filtered_items()
        start_idx = self.current_page * self.items_per_page
        page_items = items[start_idx:start_idx + self.items_per_page]

        if self.active_tab == "char_rates":
            if not page_items:
                embed.add_field(name="📭 조회 결과 없음", value="선택한 조건에 해당하는 캐릭터가 없습니다.", inline=False)
            else:
                lines = []
                for c_stat in page_items:
                    unowned_c = c_stat["total_count"] - c_stat["owned_count"]
                    badge = "👑 **컴플리트!**" if unowned_c == 0 and c_stat["total_count"] > 0 else f"*(미획득 `{unowned_c}`)*"
                    lines.append(
                        f"**{c_stat['char_name']}** · `{c_stat['unit']}`\n"
                        f"└ {c_stat['bar']} **`{c_stat['rate']:.1f}%`** (`{c_stat['owned_count']}/{c_stat['total_count']}`) {badge}"
                    )
                core.add_chunked_embed_fields(
                    embed,
                    f"📊 캐릭터별 수집률 (페이지 {self.current_page + 1} / {self.max_page + 1})",
                    lines,
                    separator="\n",
                    max_chars=950
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
                        f"`{idx:02d}.` 🔒 **{c['rarity_label']} {c['char_name']}** [{c['prefix']}]\n"
                        f"└ `{c.get('limit_label', '통상')}` · `{unit_str}` · {c.get('attr', '✨')} *(ID: `{c['id']}`)*"
                    )
                core.add_chunked_embed_fields(
                    embed,
                    f"🔒 미획득 카드 목록 (페이지 {self.current_page + 1} / {self.max_page + 1})",
                    lines,
                    separator="\n",
                    max_chars=950
                )
        else:
            if not page_items:
                embed.add_field(
                    name="📭 보유한 카드가 없습니다",
                    value="`/설정` (`🎮 미니게임` ➔ `🎰 프로세카 뽑기`)에서 첫 카드를 수집해 보세요!",
                    inline=False
                )
            else:
                lines = []
                for idx, c in enumerate(page_items, start=start_idx + 1):
                    lock_icon = "🔒 " if c.get("locked") else ""
                    cnt_tag = f" `×{c.get('count', 1)}`" if c.get("count", 1) > 1 else ""
                    lines.append(
                        f"`{idx:02d}.` {lock_icon}**{c['rarity_label']} {c['char_name']}** [{c['prefix']}]{cnt_tag}\n"
                        f"└ `{c.get('limit_label', '통상')}` · `{c.get('unit', '')}` · {c.get('attr', '✨')} *(ID: `{c['id']}`)*"
                    )
                core.add_chunked_embed_fields(
                    embed,
                    f"✨ 보유 도감 목록 (페이지 {self.current_page + 1} / {self.max_page + 1})",
                    lines,
                    separator="\n",
                    max_chars=950
                )

        embed.set_footer(text="상단 버튼으로 [수집률] · [미획득] · [보유] 탭을 전환하세요")
        return embed

    @discord.ui.button(label="📊 수집률", style=discord.ButtonStyle.primary, row=0)
    async def tab_char_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.stats = await asyncio.to_thread(core.get_card_pokedex_stats, self.guild_id, self.user.id)
        self.active_tab = "char_rates"
        if self.filter_val in ("R4", "RB", "R3", "R2", "R1", "LIMITED"):
            self.filter_val = "ALL"
            self.filter_label = "전체 (26명)"
        self.current_page = 0
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔒 미획득", style=discord.ButtonStyle.secondary, row=0)
    async def tab_unowned_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.stats = await asyncio.to_thread(core.get_card_pokedex_stats, self.guild_id, self.user.id)
        self.active_tab = "unowned"
        if self.filter_val in ("HIGH_RATE", "INCOMPLETE"):
            self.filter_val = "ALL"
            self.filter_label = "전체 카드"
        self.current_page = 0
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="✨ 보유", style=discord.ButtonStyle.secondary, row=0)
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
        await core.safe_defer(interaction)
        self.current_page = max(0, self.current_page - 1)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.current_page = min(self.max_page, self.current_page + 1)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

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
            discord.SelectOption(label="★★ (2성 카드만)", value="R2", description="2성 카드만 필터링"),
            discord.SelectOption(label="★ (1성 기본 카드만)", value="R1", description="가챠 등록 기본 지급 1성 카드 필터링"),
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
        await core.safe_defer(interaction)
        val = select.values[0]
        self.filter_val = val
        label_map = {
            "ALL": "전체",
            "HIGH_RATE": "수집률 높은순",
            "INCOMPLETE": "미완성 캐릭터만",
            "R4": "★★★★ (4성)",
            "RB": "🎀 생일 한정",
            "R3": "★★★ (3성)",
            "R2": "★★ (2성)",
            "R1": "★ (1성 기본)",
            "LIMITED": "한정/페스/생일만"
        }
        self.filter_label = label_map.get(val, val.replace("U_", "유닛: "))
        self.current_page = 0
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="🖼️ 현재 페이지 카드 일러스트 미리보기...",
        row=2,
        options=[discord.SelectOption(label="카드 선택", value="NONE")]
    )
    async def preview_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        cid_val = select.values[0]
        if cid_val == "NONE":
            await core.safe_send_response(interaction, "ℹ️ 현재 페이지에서 미리볼 카드를 선택해주세요.", ephemeral=True)
            return
        pool = self.get_filtered_items()
        target_card = next((c for c in pool if isinstance(c, dict) and str(c.get("id")) == cid_val), None)
        if not target_card:
            all_stat_cards = list(self.stats.get("owned_cards", [])) + list(self.stats.get("unowned_cards", []))
            target_card = next((c for c in all_stat_cards if isinstance(c, dict) and str(c.get("id")) == cid_val), None)
        if not target_card:
            target_card = core.get_proseka_card_by_id(cid_val)
        if not target_card:
            await core.safe_send_response(interaction, "❌ 선택한 카드를 찾을 수 없습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        can_train = core.can_card_awaken(target_card)
        status_txt = "✨ 보유 완료" if target_card.get("count", 0) > 0 else "🔒 미획득"
        s_num = int(target_card.get("star_num", 3))
        p_color = (
            discord.Color.from_rgb(255, 105, 180)
            if s_num >= 4
            else (discord.Color.from_rgb(242, 184, 48) if s_num == 3 else discord.Color.from_rgb(0, 204, 221))
        )
        stage_tag = "🌸 [특훈 전] " if can_train else ""
        p_embed = discord.Embed(
            title=f"📖 {stage_tag}{target_card['rarity_label']} [{target_card['prefix']}] {target_card['char_name']}"[:256],
            description=f"`{target_card.get('limit_label', '통상')}` · 도감 ID `{target_card.get('id')}`",
            color=p_color,
        )
        p_embed.add_field(name="📌 상태", value=f"**{status_txt}**", inline=True)
        p_embed.add_field(name="🏷️ 유닛 · 속성", value=f"`{target_card.get('unit', '-')}` · {target_card.get('attr', '✨')}", inline=True)

        p_view = SimpleCardIllustToggleView(target_card, initial_mode="normal") if can_train else None
        if can_train:
            p_embed.set_footer(text="🌸 특훈 전 (Normal) 공식 일러스트 • 하단 버튼으로 특훈 전·후 전환")

        img_bytes, filename = await asyncio.to_thread(core.fetch_proseka_card_image_bytes, target_card, "normal")
        p_file = None
        if img_bytes and filename:
            safe_n_fn = f"pdx_norm_{filename}"
            p_embed.set_image(url=f"attachment://{safe_n_fn}")
            p_file = discord.File(io.BytesIO(img_bytes), filename=safe_n_fn)
        else:
            p_embed.set_image(url=core.get_proseka_card_image_url(target_card, "normal"))

        send_kw = {"embed": p_embed, "ephemeral": True}
        if p_view is not None:
            send_kw["view"] = p_view
        if p_file is not None:
            await interaction.followup.send(file=p_file, **send_kw)
        else:
            await interaction.followup.send(**send_kw)


class GuildGachaResetConfirmView(core.SafeView):
    def __init__(self, guild: discord.Guild | None = None):
        super().__init__(timeout=60)
        self.guild = guild

    @discord.ui.button(label="⚠️ 이 서버 캐릭터 데이터 초기화 실행", style=discord.ButtonStyle.danger, row=0)
    async def confirm_guild_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, "❌ 서버 관리자만 실행할 수 있습니다.", ephemeral=True)
            return

        target_guild = self.guild or interaction.guild
        if not target_guild:
            await core.safe_send_response(interaction, "❌ 서버 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        g_key = str(target_guild.id)

        def _do_guild_gacha_reset():
            with core._DATA_LOCK:
                data = core.load_data()
                changed = False
                gacha_users_map = core.ensure_dict_path(data, "gacha_users")
                if g_key in gacha_users_map:
                    del gacha_users_map[g_key]
                    changed = True
                hof_map = core.ensure_dict_path(data, "gacha_hall_of_fame")
                if g_key in hof_map:
                    del hof_map[g_key]
                    changed = True
                if changed:
                    core.save_data(data)

        await asyncio.to_thread(_do_guild_gacha_reset)

        embed = discord.Embed(
            title="🔄 서버 캐릭터 데이터 초기화 완료",
            description=f"**{target_guild.name}** 서버의 모든 유저 프로세카 캐릭터 보관함이 초기화되었습니다.",
            color=discord.Color.red()
        )
        await interaction.edit_original_response(content=None, embed=embed, view=None)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary, row=0)
    async def cancel_guild_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="✅ 초기화 취소됨", description="서버 캐릭터 데이터가 안전하게 유지됩니다.", color=discord.Color.blue())
        await core.safe_edit_response(interaction, content=None, embed=embed, view=None)


class AllGachaResetConfirmView(core.SafeView):
    def __init__(self, bot_instance=None):
        super().__init__(timeout=60)
        self.bot_instance = bot_instance

    @discord.ui.button(label="🚨 전체 서버 캐릭터 데이터 초기화 실행", style=discord.ButtonStyle.danger, row=0)
    async def confirm_all_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot_ref = self.bot_instance or interaction.client
        if not bot_ref or not await bot_ref.is_bot_owner_user(interaction.user):
            await core.safe_send_response(interaction, "❌ 봇주인(Bot Owner)만 실행할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        data["gacha_users"] = {}
        data["gacha_hall_of_fame"] = {}
        data["gacha_pickup"] = copy.deepcopy(core.DEFAULT_CONFIG["gacha_pickup"])
        await asyncio.to_thread(core.save_data, data)

        embed = discord.Embed(
            title="🚨 전체 서버 캐릭터 데이터 초기화 완료",
            description="봇이 소속된 **모든 서버의 프로세카 캐릭터 보관함 데이터 및 픽업 설정**이 완전히 초기화되었습니다.",
            color=discord.Color.red()
        )
        await interaction.edit_original_response(content=None, embed=embed, view=None)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary, row=0)
    async def cancel_all_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="✅ 초기화 취소됨", description="전체 캐릭터 데이터가 안전하게 유지됩니다.", color=discord.Color.blue())
        await core.safe_edit_response(interaction, content=None, embed=embed, view=None)


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
            row=0,
            custom_id="norosi:EventForecastView:event_select",
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if view is None:
            await core.safe_defer(interaction)
            return
        val = self.values[0]
        if val == "NONE":
            await core.safe_defer(interaction)
            return
        try:
            selected_id = int(val)
        except Exception:
            await core.safe_defer(interaction)
            return
        await core.safe_defer(interaction)
        view.selected_event_id = selected_id
        view.update_components()
        await core.safe_edit_response(interaction, embed=view.build_embed(), view=view)


class EventForecastView(core.SafeView):
    """프로세카 한섭 이벤트 미래시 달력 (월별 아스키 그리드 + 상세 타임라인 카드 + 일섭 비교)"""
    def __init__(self, user: discord.User | None = None, year: int | None = None, month: int | None = None, selected_event_id: int | None = None):
        super().__init__(timeout=600)
        now = datetime.datetime.now(core.KST)
        self.user = user
        self.year = year or now.year
        self.month = month or now.month
        self.selected_event_id = selected_event_id
        self.update_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 미래시 달력은 **{self.user.display_name}**님이 조회한 창입니다. `/설정`에서 직접 조회해 보세요!",
                ephemeral=True
            )
            return False
        if not self.user:
            self.user = interaction.user
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
            title=f"📅 한섭 이벤트 미래시 달력 ({cal_data['month_label']})",
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )

        cal_box = (
            f"```text\n"
            f"{cal_data['calendar_ascii']}\n"
            f"```\n"
            f"📌 **범례:** `S` 시작 · `*` 진행 중 · `E` 종료"
        )
        embed.add_field(name=f"🗓️ {self.year}년 {self.month:02d}월 예상 일정표", value=cal_box, inline=False)

        if selected_ev:
            ev_type_label = core.EVENT_TYPE_MAP.get(selected_ev.get("eventType", ""), selected_ev.get("eventType", "이벤트"))
            tag = "🌟 컬러풀 페스티벌" if selected_ev.get("is_fes") else ("🎀 기간 한정" if selected_ev.get("is_limited") else "🎵 통상")

            cards_lines = [f"• {c}" for c in selected_ev.get("featured_cards", [])]
            cards_str = "\n".join(cards_lines) if cards_lines else "• 정보 확인 중"

            embed.add_field(
                name=f"🏆 {selected_ev['name']}",
                value=(
                    f"*일섭 원제: {selected_ev.get('jp_name', '-')}*\n"
                    f"└ `{ev_type_label}` · `{selected_ev.get('unit', '-')}` · {selected_ev.get('attribute', '-')}\n"
                    f"└ 🎵 테마곡: `{selected_ev.get('theme_song', '-')}`"
                ),
                inline=False,
            )
            embed.add_field(
                name="🇰🇷 한섭 예상",
                value=f"`{selected_ev['kr_estimated_start']}`\n~ `{selected_ev['kr_estimated_end']}`",
                inline=True,
            )
            embed.add_field(
                name="🇯🇵 일섭 원본",
                value=f"`{selected_ev['jp_start']}`\n~ `{selected_ev['jp_end']}`",
                inline=True,
            )
            embed.add_field(
                name=f"🎰 연계 가챠 ({tag})",
                value=f"**{selected_ev.get('gacha_name', '-')}**\n{cards_str}"[:1024],
                inline=False,
            )
        else:
            embed.add_field(name="🏆 이벤트 상세", value="이번 달에는 예정된 이벤트가 없거나 일정을 산출 중입니다.", inline=False)

        if events_in_month:
            summary_lines = []
            for ev in events_in_month:
                tag = "🌟컬페" if ev.get("is_fes") else ("🎀한정" if ev.get("is_limited") else "🎵통상")
                summary_lines.append(f"• `{ev['kr_estimated_start'][5:]}~{ev['kr_estimated_end'][5:]}` **{ev['name']}** · `{tag}`")
            embed.add_field(name=f"📋 이번 달 예정 이벤트 ({len(events_in_month)}개)", value="\n".join(summary_lines)[:1024], inline=False)

        embed.set_footer(text=cal_data["disclaimer"])
        return embed

    async def on_prev_month(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        if self.month == 1:
            self.year -= 1
            self.month = 12
        else:
            self.month -= 1
        self.selected_event_id = None
        self.update_components()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def on_next_month(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        if self.month == 12:
            self.year += 1
            self.month = 1
        else:
            self.month += 1
        self.selected_event_id = None
        self.update_components()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def on_current_month(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        now = datetime.datetime.now(core.KST)
        self.year = now.year
        self.month = now.month
        self.selected_event_id = None
        self.update_components()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def on_show_all_list(self, interaction: discord.Interaction):
        all_events = core.get_event_forecast_list()
        embed = discord.Embed(
            title="📜 한섭 다가오는 이벤트 미래시 목록",
            description="일본 서버(JP) 순서를 기반으로 한 한국 서버(KR) 예상 일정입니다.",
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        rows = []
        for ev in all_events[:30]:
            tag = "🌟컬페" if ev.get("is_fes") else ("🎀한정" if ev.get("is_limited") else "🎵통상")
            picks = ", ".join(ev.get("featured_cards", [])[:2]) or "정보 확인 중"
            rows.append(
                f"**{ev['name']}** `{tag}`\n"
                f"└ 🇰🇷 `{ev['kr_estimated_start'][5:]}~{ev['kr_estimated_end'][5:]}` · `{ev['unit']}` · {picks}"
            )
        if rows:
            core.add_chunked_embed_fields(embed, f"🗓️ 예정 이벤트 ({len(rows)}개)", rows, separator="\n", max_chars=950)
        if len(all_events) > 30:
            embed.add_field(
                name=f"➕ 외 {len(all_events) - 30}개 예정 이벤트",
                value="월별 미래시 달력에서 이전/다음 월 버튼으로 확인하실 수 있습니다.",
                inline=False,
            )
        embed.set_footer(text=core.FORECAST_DISCLAIMER)
        await core.safe_send_response(interaction, embed=embed, ephemeral=True)


class EventInfoView(core.SafeView):
    """실시간 이벤트 조회 시 미래시 달력 및 봇주 전용 이벤트 픽업 동기화 바로가기 뷰"""
    def __init__(self, bot_instance=None, user: discord.User | None = None):
        super().__init__(timeout=300)
        self.bot_instance = bot_instance
        self.user = user

    @discord.ui.button(label="📅 한섭 이벤트 미래시 달력 보기", style=discord.ButtonStyle.primary, emoji="📅", row=0)
    async def open_forecast(self, interaction: discord.Interaction, button: discord.ui.Button):
        now = datetime.datetime.now(core.KST)
        view = EventForecastView(interaction.user, now.year, now.month)
        await core.safe_send_response(interaction, embed=view.build_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="🎯 이벤트 픽업 맞추기 (봇주 전용)", style=discord.ButtonStyle.success, row=0)
    async def sync_event_pickup(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot_ref = self.bot_instance or interaction.client
        if not bot_ref or not hasattr(bot_ref, "is_bot_owner_user") or not await bot_ref.is_bot_owner_user(interaction.user):
            await core.safe_send_response(
                interaction,
                content="❌ 이 기능은 **봇주인(Bot Owner)** 만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        await core.safe_defer(interaction, ephemeral=True)
        ok, msg, pickup_obj = await asyncio.to_thread(core.sync_gacha_pickup_to_live_event)
        if not ok:
            await interaction.followup.send(f"❌ {msg}", ephemeral=True)
            return

        labels = pickup_obj.get("pickup_card_labels") or []
        cards_txt = "\n".join(f"• {lbl}" for lbl in labels[:12]) if labels else f"• 유닛 픽업: `{pickup_obj.get('unit') or '전체'}`"
        embed = discord.Embed(
            title="🎯 한섭 이벤트 픽업 자동 연동 완료",
            description=msg,
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.add_field(
            name="🏆 적용 이벤트",
            value=f"**{pickup_obj.get('event_name')}** (`{pickup_obj.get('event_status', '진행 중')}`)",
            inline=False,
        )
        embed.add_field(name=f"🌟 픽업 ★4 카드 ({len(labels)}종)", value=cards_txt[:1024], inline=False)
        embed.set_footer(text="프로세카 뽑기 및 확률표에 즉시 반영됩니다")
        await interaction.followup.send(embed=embed, ephemeral=True)


class MasterRankView(core.SafeView):
    """보유 카드의 마스터 랭크(0~5) 한계 돌파 및 MR.2 어나더 컬러·한정 헤어 해금 뷰"""
    def __init__(self, user: discord.User | None = None, guild_id: int = 0, initial_card_id: str | None = None):
        super().__init__(timeout=600)
        self.user = user
        self.guild_id = guild_id
        self.per_page = 5
        self.card_page = 0
        self.selected_unit: str = "ALL"
        self.selected_char_id: int | None = None
        self.selected_card_id: str | None = str(initial_card_id) if initial_card_id is not None else None
        self.status_notice = ""
        self.has_more_chars_notice = False
        self.illust_stage = "normal"

        data = core.get_cached_data_ro()
        self._refresh(data, sync_page_to_selected=True)

    def _restore_from_message(self, interaction: discord.Interaction):
        """봇 재시작/뷰 복원 시 기존 메시지 컴포넌트 및 임베드에서 필터, 페이지, 선택된 카드 ID를 복구합니다."""
        msg = getattr(interaction, "message", None)
        if not msg:
            return
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        restored_cid = None
        restored_page = None
        restored_unit = None
        restored_char = None
        has_char_select = False
        for row in getattr(msg, "components", []) or []:
            for comp in getattr(row, "children", []):
                cid = getattr(comp, "custom_id", "") or ""
                if cid.endswith(":list_page_btn") or "📄" in (getattr(comp, "label", "") or ""):
                    lbl = getattr(comp, "label", "") or ""
                    parts = lbl.replace("📄", "").strip().split("/")
                    if parts and parts[0].strip().isdigit():
                        restored_page = max(0, int(parts[0].strip()) - 1)
                elif cid.endswith(":unit_select"):
                    for opt in getattr(comp, "options", []):
                        if getattr(opt, "default", False) and getattr(opt, "value", None):
                            restored_unit = str(opt.value)
                elif cid.endswith(":char_select"):
                    has_char_select = True
                    for opt in getattr(comp, "options", []):
                        if getattr(opt, "default", False) and getattr(opt, "value", None):
                            val_s = str(opt.value)
                            restored_char = int(val_s) if val_s.isdigit() else None
                elif cid.endswith(":card_select") or (not cid and getattr(comp, "options", None)):
                    for opt in getattr(comp, "options", []):
                        if getattr(opt, "default", False) and getattr(opt, "value", None) not in (None, "NONE"):
                            restored_cid = str(opt.value)

        if restored_cid is None:
            embeds = getattr(msg, "embeds", None) or []
            if embeds:
                import re
                emb0 = embeds[0]
                blob = "\n".join(
                    [emb0.description or "", getattr(emb0.footer, "text", "") or ""]
                    + [f.value or "" for f in getattr(emb0, "fields", [])]
                )
                m = re.search(r"\(ID:\s*`?([^`\)\s]+)`?\)", blob)
                if m:
                    restored_cid = m.group(1)

        if restored_unit is not None:
            self.selected_unit = restored_unit
        if has_char_select:
            self.selected_char_id = restored_char
        if restored_page is not None:
            self.card_page = restored_page
        if restored_cid is not None:
            self.selected_card_id = restored_cid

        self._refresh(
            core.get_cached_data_ro(),
            sync_page_to_selected=(restored_page is None and restored_cid is not None),
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 마스터 랭크 메뉴는 **{self.user.display_name}**님 전용입니다. `/설정` (`👤 개인` ➔ `🏆 마스터 랭크`)에서 열어보세요!",
                ephemeral=True
            )
            return False
        if not self.user:
            self.user = interaction.user
            self._restore_from_message(interaction)
        if not self.selected_card_id:
            self._restore_from_message(interaction)
            if not self.selected_card_id:
                self._refresh(core.get_cached_data_ro(), sync_page_to_selected=True)
        return True

    @staticmethod
    def _safe_int(val, default: int = 0) -> int:
        if val is None or val == "":
            return default
        try:
            return int(val)
        except Exception:
            return default

    @classmethod
    def _card_star_num(cls, card: dict, default: int = 3) -> int:
        raw = card.get("star_num") if card.get("star_num") is not None else card.get("rarity")
        return cls._safe_int(raw, default)

    def _get_all_owned_cards(self, data: dict) -> list[dict]:
        g_key = str(self.guild_id or 0)
        u_key = str(self.user.id) if self.user else "0"
        u_cards = core.safe_get_dict(data, "gacha_users", g_key, u_key, "cards")
        out = []
        seen = set()
        for cid_key, c in u_cards.items():
            if not isinstance(c, dict):
                continue
            raw_id = c.get("id") if c.get("id") is not None else cid_key
            cid_str = str(raw_id).strip()
            if not cid_str or cid_str in seen:
                continue
            seen.add(cid_str)
            if c.get("id") is None or str(c.get("id")) != cid_str:
                c = dict(c)
                c["id"] = int(cid_str) if cid_str.isdigit() else cid_str
            out.append(c)
        return out

    @classmethod
    def _matches_unit_or_quick_filter(cls, card: dict, filter_val: str) -> bool:
        if filter_val == "ALL":
            return True
        if filter_val == "DUP_ONLY":
            return cls._safe_int(card.get("count", 1), 1) >= 2 and cls._safe_int(card.get("master_rank", 0), 0) < 5
        if filter_val == "STAR4_ONLY":
            return cls._card_star_num(card, 1) >= 4 or card.get("rarity_type") == "rarity_birthday"
        if filter_val == "COSTUME_ONLY":
            return core.get_costume_for_card(card.get("id")) is not None
        return MyInventoryView._card_matches_unit(card, filter_val)

    def _update_filter_selects(self, all_cards: list[dict]):
        unit_emojis = {
            "Leo/need": "🎸",
            "MORE MORE JUMP!": "🍀",
            "Vivid BAD SQUAD": "🎧",
            "원더랜즈×쇼타임": "🎪",
            "25시, 나이트 코드에서.": "🌃",
            "버츄얼 싱어": "🎤",
        }
        total_cnt = len(all_cards)
        dup_cnt = sum(1 for c in all_cards if self._matches_unit_or_quick_filter(c, "DUP_ONLY"))
        s4_cnt = sum(1 for c in all_cards if self._matches_unit_or_quick_filter(c, "STAR4_ONLY"))
        cos_cnt = sum(1 for c in all_cards if self._matches_unit_or_quick_filter(c, "COSTUME_ONLY"))

        unit_opts = [
            discord.SelectOption(
                label=f"🌐 전체 ({total_cnt})"[:30],
                value="ALL",
                default=(self.selected_unit == "ALL"),
            ),
            discord.SelectOption(
                label=f"🃏 중복 ({dup_cnt}·0💎)"[:30],
                value="DUP_ONLY",
                default=(self.selected_unit == "DUP_ONLY"),
            ),
            discord.SelectOption(
                label=f"⭐ ★4·생일 ({s4_cnt})"[:30],
                value="STAR4_ONLY",
                default=(self.selected_unit == "STAR4_ONLY"),
            ),
            discord.SelectOption(
                label=f"👗 3D의상 ({cos_cnt})"[:30],
                value="COSTUME_ONLY",
                default=(self.selected_unit == "COSTUME_ONLY"),
            ),
        ]
        for u_name in core.UNIT_ORDER:
            u_list = [c for c in all_cards if MyInventoryView._card_matches_unit(c, u_name)]
            u_emoji = unit_emojis.get(u_name, "🏷️")
            unit_opts.append(
                discord.SelectOption(
                    label=f"{u_emoji} {u_name} ({len(u_list)})"[:30],
                    value=u_name,
                    default=(self.selected_unit == u_name),
                )
            )
        self.unit_select.options = unit_opts[:25]

        base_pool = [c for c in all_cards if self._matches_unit_or_quick_filter(c, self.selected_unit)]
        char_counts: dict[int, tuple[int, int]] = {}
        for c in base_pool:
            cid = MyInventoryView._resolve_card_char_id(c)
            if cid is None:
                continue
            prev_u, prev_dup = char_counts.get(cid, (0, 0))
            is_dup = 1 if (self._safe_int(c.get("count", 1), 1) >= 2 and self._safe_int(c.get("master_rank", 0), 0) < 5) else 0
            char_counts[cid] = (prev_u + 1, prev_dup + is_dup)

        if self.selected_unit in core.UNIT_ORDER:
            unit_member_cids = [cid for cid, info in core.CHARACTER_MAP.items() if info.get("unit") == self.selected_unit]
            extra_cids = [cid for cid in sorted(char_counts.keys()) if cid in core.CHARACTER_MAP and cid not in unit_member_cids]
            candidate_cids = unit_member_cids + extra_cids
        else:
            candidate_cids = sorted(cid for cid in char_counts.keys() if cid in core.CHARACTER_MAP)
            if self.selected_char_id is not None and self.selected_char_id in core.CHARACTER_MAP and self.selected_char_id not in candidate_cids:
                candidate_cids.append(self.selected_char_id)
                candidate_cids.sort()

        self.has_more_chars_notice = len(candidate_cids) > 24
        if self.has_more_chars_notice:
            display_cids = candidate_cids[:24]
            if self.selected_char_id is not None and self.selected_char_id in candidate_cids and self.selected_char_id not in display_cids:
                display_cids = display_cids[:-1] + [self.selected_char_id]
            self.char_select.placeholder = "👤 캐릭터 (MEIKO·KAITO: 1단계 버츄얼 싱어)"
        else:
            display_cids = candidate_cids
            self.char_select.placeholder = "👤 2단계: 캐릭터 선택..."

        char_opts = [
            discord.SelectOption(
                label=f"🌐 전체 ({len(base_pool)})"[:26],
                value="ALL",
                default=(self.selected_char_id is None),
            )
        ]
        for cid in display_cids:
            c_info = core.CHARACTER_MAP.get(cid, {"name": f"캐릭터 #{cid}", "unit": "-"})
            u_cnt, d_cnt = char_counts.get(cid, (0, 0))
            dup_note = f"·중{d_cnt}" if d_cnt > 0 else ""
            short_name = c_info["name"].split()[-1]
            char_opts.append(
                discord.SelectOption(
                    label=f"{short_name} ({u_cnt}{dup_note})"[:26],
                    value=str(cid),
                    default=(self.selected_char_id == cid),
                )
            )
        self.char_select.options = char_opts[:25]

    def _get_sorted_cards(self, data: dict) -> list[dict]:
        all_cards = self._get_all_owned_cards(data)
        self._update_filter_selects(all_cards)
        cards = [c for c in all_cards if self._matches_unit_or_quick_filter(c, self.selected_unit)]
        if self.selected_char_id is not None:
            cards = [c for c in cards if MyInventoryView._resolve_card_char_id(c) == self.selected_char_id]
        cards.sort(key=lambda c: (
            -int(self._safe_int(c.get("master_rank", 0), 0) < 5),
            -self._card_star_num(c, 1),
            -int(self._safe_int(c.get("count", 1), 1) >= 2),
            -self._safe_int(c.get("master_rank", 0), 0),
            -core.get_card_power(c),
            self._safe_int(c.get("char_id", 99), 99),
            self._safe_int(c.get("id", 0), 0),
        ))
        return cards

    def _refresh(self, data: dict | None = None, sync_page_to_selected: bool = True) -> tuple[dict, list[dict], dict | None]:
        d = data if data is not None else core.load_data()
        cards = self._get_sorted_cards(d)

        if sync_page_to_selected and self.selected_card_id is not None:
            for idx, c in enumerate(cards):
                if str(c.get("id")) == str(self.selected_card_id):
                    self.card_page = idx // self.per_page
                    break

        max_page = max(0, (len(cards) - 1) // self.per_page) if cards else 0
        self.card_page = max(0, min(self.card_page, max_page))
        start = self.card_page * self.per_page
        page_cards = cards[start:start + self.per_page]

        selected = next((c for c in page_cards if str(c.get("id")) == str(self.selected_card_id)), None)
        if not selected and page_cards:
            selected = page_cards[0]
            self.selected_card_id = str(selected.get("id"))
        elif not cards:
            self.selected_card_id = None

        if not page_cards:
            self.card_select.options = [discord.SelectOption(label="조건에 맞는 카드 없음", value="NONE")]
            self.card_select.disabled = True
        else:
            opts = []
            seen_vals = set()
            for c in page_cards:
                cid_val = str(c.get("id"))
                if cid_val in seen_vals:
                    continue
                seen_vals.add(cid_val)
                mr = self._safe_int(c.get("master_rank", 0), 0)
                cnt = self._safe_int(c.get("count", 1), 1)
                dup_txt = f"중{cnt - 1}" if cnt >= 2 else "1"
                cos = core.get_costume_for_card(c.get("id"))
                cos_badge = "👗" if cos else ""
                r_lbl = core.get_card_rarity_label(c)
                prefix = (c.get("prefix") or "카드")[:8]
                cname = (c.get("char_name") or "캐릭터").split()[-1]
                label = f"{cos_badge}[MR{mr}]{r_lbl} {prefix}·{cname}({dup_txt})"[:34]
                opts.append(discord.SelectOption(
                    label=label,
                    value=cid_val[:100],
                    default=(cid_val == str(self.selected_card_id))
                ))
            self.card_select.options = opts or [discord.SelectOption(label="표시할 카드 없음", value="NONE")]
            self.card_select.disabled = not bool(opts)

        self.prev_list_btn.disabled = (self.card_page <= 0)
        self.list_page_btn.label = f"📄 {self.card_page + 1} / {max_page + 1} ({len(cards)}종)"
        self.next_list_btn.disabled = (self.card_page >= max_page)

        if not selected:
            self.btn_upgrade_dup.disabled = True
            self.btn_upgrade_dup.label = "🃏 중복 카드로 돌파 (0💎)"
            self.btn_upgrade_crystal.disabled = True
            self.btn_upgrade_crystal.label = "💎 크리스탈로 돌파"
            self.btn_goto_wardrobe.disabled = True
            self.btn_stage_normal.disabled = True
            self.btn_stage_trained.disabled = True
        else:
            cur_mr = self._safe_int(selected.get("master_rank", 0), 0)
            cnt = self._safe_int(selected.get("count", 1), 1)
            star_num = self._card_star_num(selected, 3)
            self.btn_goto_wardrobe.disabled = False
            can_train_sel = core.can_card_awaken(selected)
            self.btn_stage_normal.disabled = (not can_train_sel) or (self.illust_stage == "normal")
            self.btn_stage_trained.disabled = (not can_train_sel) or (self.illust_stage == "after_training")
            if cur_mr >= 5:
                self.btn_upgrade_dup.disabled = True
                self.btn_upgrade_dup.label = "🏆 MAX 마스터 랭크 달성!"
                self.btn_upgrade_crystal.disabled = True
                self.btn_upgrade_crystal.label = "✨ ✦MR.5/5 완료"
            else:
                cost = core.get_master_rank_crystal_cost(star_num, cur_mr)
                self.btn_upgrade_dup.disabled = (cnt < 2)
                self.btn_upgrade_dup.label = f"🃏 중복 카드로 돌파 (중복 {max(0, cnt - 1)}장 · 0💎)" if cnt >= 2 else "🃏 중복 카드 없음"
                self.btn_upgrade_crystal.disabled = False
                self.btn_upgrade_crystal.label = f"💎 크리스탈로 돌파 ({cost:,}💎)"

        return d, cards, selected

    def build_embed(self, data: dict | None = None, sync_page_to_selected: bool = True) -> discord.Embed:
        d_in = data if data is not None else core.load_data()
        d, cards, selected = self._refresh(d_in, sync_page_to_selected=sync_page_to_selected)
        u_id = self.user.id if self.user else 0
        u_name = self.user.display_name if self.user else "유저"
        prof = core.ensure_user_profile(d, u_id, u_name)
        crystals = self._safe_int(prof.get("crystals", 0), 0)

        filter_names = {
            "ALL": "전체 보유 카드",
            "DUP_ONLY": "중복 보유 카드만 (0💎)",
            "STAR4_ONLY": "★4 · 🎀생일 카드만",
            "COSTUME_ONLY": "3D 의상 카드만",
        }
        u_lbl = filter_names.get(self.selected_unit, self.selected_unit)
        c_lbl = (
            core.CHARACTER_MAP.get(self.selected_char_id, {}).get("name", f"캐릭터 #{self.selected_char_id}")
            if self.selected_char_id is not None
            else "전체 캐릭터"
        )
        notice_block = f"\n🎉 {self.status_notice}\n\n" if self.status_notice else ""
        more_chars_tip = (
            "• 💡 `MEIKO·KAITO`는 1단계 `버츄얼 싱어`에서 선택\n"
            if self.has_more_chars_notice
            else ""
        )

        if not selected:
            return discord.Embed(
                title=f"🏆 {u_name}님의 마스터 랭크 (한계 돌파)",
                description=(
                    f"{notice_block}"
                    f"• **현재 필터:** `{u_lbl}` · `{c_lbl}` · **보유 크리스탈:** **`{crystals:,} 💎`**\n"
                    f"{more_chars_tip}\n"
                    "📭 해당 필터 조건에 맞는 프로세카 카드가 없습니다.\n"
                    "위 드롭다운에서 **`🌐 전체 카드`** 또는 다른 캐릭터를 선택해 보세요!"
                ),
                color=discord.Color.dark_grey(),
                timestamp=datetime.datetime.now(core.KST)
            )

        mr = self._safe_int(selected.get("master_rank", 0), 0)
        mr_bar = core.format_progress_bar(mr, 5, slots=5)
        cur_lvl = self._safe_int(selected.get("level", 1), 1)
        max_lvl = core.get_card_max_level(selected)
        cur_pwr = core.get_card_power(selected)
        cnt = self._safe_int(selected.get("count", 1), 1)
        star_num = self._card_star_num(selected, 3)
        cos = core.get_costume_for_card(selected.get("id"))

        # 다음 MR 예상 종합력 미리보기 & 즉시 돌파 가능 여부 배지
        if mr < 5:
            next_card = dict(selected)
            next_card["master_rank"] = mr + 1
            next_pwr = core.get_card_power(next_card)
            next_cost = core.get_master_rank_crystal_cost(star_num, mr)
            if cnt >= 2:
                ready_badge = f"✅ **무료 돌파 가능** *(중복 `{cnt - 1}장` · `0💎`)*"
            elif crystals >= next_cost:
                ready_badge = f"💎 **크리스탈 돌파 가능** *(잔여 `{crystals - next_cost:,}💎`)*"
            else:
                ready_badge = f"⚠️ **크리스탈 `{next_cost - crystals:,}💎` 부족**"
            next_field_name = f"📈 다음 단계 (✦MR.{mr + 1})"
            next_field_val = (
                f"{ready_badge}\n"
                f"└ 종합력: `⚔️ {cur_pwr:,}` ➔ **`⚔️ {next_pwr:,}`** (`+{next_pwr - cur_pwr:,}`)\n"
                f"└ 재료: 중복 카드 `1장` (`0💎`, 보유 `{cnt}장`) 또는 **`{next_cost:,} 💎`**"
            )
        else:
            next_field_name = "🏆 마스터 랭크 MAX"
            next_field_val = "최고 단계(**`✦MR.5 / 5`**) 도달 완료 · 종합력 **`+40%`** 영구 적용 중"

        perk_lines = []
        if cos:
            ac_state = "✅ 해금 완료" if mr >= 2 else "🔒 ✦MR.2 해금"
            perk_lines.append(f"• 👗 어나더 컬러 3종 (`{cos.get('name', '3D 의상')}`) — {ac_state}")
            if selected.get("is_limited"):
                hair_state = "✅ 해금 완료" if mr >= 2 else "🔒 ✦MR.2 해금"
                perk_lines.append(f"• 💇 한정 헤어스타일 특전 — {hair_state}")
        else:
            perk_lines.append("• 돌파당 **종합력 `+8%`** (최대 `+40%`) 영구 상승")

        r_lbl = core.get_card_rarity_label(selected)
        prefix = selected.get("prefix") or "카드"
        cname = selected.get("char_name") or "알 수 없음"
        cid_disp = selected.get("id", "-")

        desc_lines = [
            f"🔍 **필터:** `{u_lbl}` · `{c_lbl}` (`{len(cards):,}종`)",
            f"🃏 **{r_lbl} {cname}** [{prefix}] · `{selected.get('limit_label', '통상')}` *(ID: `{cid_disp}`)*",
        ]
        if self.has_more_chars_notice:
            desc_lines.append("💡 `MEIKO·KAITO`는 1단계 `버츄얼 싱어`에서 선택")
        if self.status_notice:
            desc_lines.append(f"\n> 🎉 {self.status_notice}")

        embed = discord.Embed(
            title=f"🏆 {u_name}님의 마스터 랭크 돌파",
            description="\n".join(desc_lines),
            color=discord.Color.from_rgb(170, 90, 255) if mr >= 2 else discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.add_field(
            name="⭐ 마스터 랭크",
            value=f"**✦MR.{mr} / 5** *(종합력 `+{mr * 8}%`)*\n{mr_bar}",
            inline=True,
        )
        embed.add_field(
            name="⚔️ 현재 스탯",
            value=f"**`⚔️ {cur_pwr:,}`**\n└ `Lv.{cur_lvl}/{max_lvl}` · 보유 `{cnt}장`",
            inline=True,
        )
        embed.add_field(
            name="💎 보유 크리스탈",
            value=f"**`{crystals:,} 💎`**",
            inline=True,
        )
        embed.add_field(name=next_field_name, value=next_field_val, inline=False)
        embed.add_field(name="✨ 돌파 특전", value="\n".join(perk_lines), inline=False)
        eff_stage = "after_training" if (self.illust_stage == "after_training" and core.can_card_awaken(selected)) else "normal"
        embed.set_image(url=core.get_proseka_card_image_url(selected, eff_stage))
        embed.set_footer(text="✦MR.1당 종합력 +8% (최대 +40%) · 3D 의상 카드는 ✦MR.2에서 어나더 컬러 & 한정 헤어 해금")
        return embed

    async def _commit_ui_update(self, interaction: discord.Interaction, data: dict, sync_page_to_selected: bool = True):
        try:
            await core.safe_edit_response(
                interaction,
                embed=self.build_embed(data=data, sync_page_to_selected=sync_page_to_selected),
                view=self,
                raise_on_error=True,
            )
        except Exception as e:
            print(f"⚠️ [MasterRankView UI 갱신 실패] {e}", flush=True)
            await core.safe_send_response(
                interaction,
                f"⚠️ 마스터 랭크 화면 갱신 실패: `{e}`",
                ephemeral=True,
            )

    @discord.ui.select(
        placeholder="🏷️ 1단계: 유닛 / 돌파 조건 필터 선택...",
        row=0,
        options=[discord.SelectOption(label="🌐 전체 카드", value="ALL")]
    )
    async def unit_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await core.safe_defer(interaction)
        chosen_unit = select.values[0]
        data = await asyncio.to_thread(core.load_data)
        self.selected_unit = chosen_unit
        if self.selected_char_id is not None:
            if chosen_unit in core.UNIT_ORDER:
                char_unit = core.CHARACTER_MAP.get(self.selected_char_id, {}).get("unit")
                if char_unit != chosen_unit:
                    self.selected_char_id = None
            if self.selected_char_id is not None:
                all_cards = self._get_all_owned_cards(data)
                has_char_cards = any(
                    self._matches_unit_or_quick_filter(c, chosen_unit)
                    and MyInventoryView._resolve_card_char_id(c) == self.selected_char_id
                    for c in all_cards
                )
                if not has_char_cards:
                    self.selected_char_id = None
        self.card_page = 0
        self.selected_card_id = None
        self.status_notice = ""
        await self._commit_ui_update(interaction, data=data, sync_page_to_selected=False)

    @discord.ui.select(
        placeholder="👤 2단계: 캐릭터별 필터 선택...",
        row=1,
        options=[discord.SelectOption(label="🌐 전체", value="ALL")]
    )
    async def char_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await core.safe_defer(interaction)
        chosen = select.values[0]
        data = await asyncio.to_thread(core.load_data)
        try:
            self.selected_char_id = None if chosen == "ALL" else int(chosen)
        except Exception:
            self.selected_char_id = None
        self.card_page = 0
        self.selected_card_id = None
        self.status_notice = ""
        await self._commit_ui_update(interaction, data=data, sync_page_to_selected=False)

    @discord.ui.select(
        placeholder="🏆 3단계: 한계 돌파할 보유 카드 선택...",
        row=2,
        options=[discord.SelectOption(label="카드 선택", value="NONE")]
    )
    async def card_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        if val == "NONE":
            await core.safe_send_response(interaction, "ℹ️ 표시된 카드가 없습니다. 위 필터를 변경하거나 `/설정` (`🎰 프로세카 뽑기`)에서 카드를 뽑아주세요.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        self.selected_card_id = str(val)
        self.status_notice = ""
        data = await asyncio.to_thread(core.load_data)
        await self._commit_ui_update(interaction, data=data, sync_page_to_selected=True)

    async def _ensure_selected_card_id(self, interaction: discord.Interaction) -> str | None:
        if not self.selected_card_id:
            self._restore_from_message(interaction)
        if not self.selected_card_id:
            data = await asyncio.to_thread(core.load_data)
            self._refresh(data, sync_page_to_selected=True)
        return self.selected_card_id

    @discord.ui.button(label="🃏 중복 카드로 돌파 (0💎)", style=discord.ButtonStyle.success, row=3)
    async def btn_upgrade_dup(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        target_card_id = await self._ensure_selected_card_id(interaction)
        if not target_card_id:
            await core.safe_send_response(interaction, "❌ 선택된 카드가 없습니다. 위 목록에서 카드를 먼저 선택해 주세요.", ephemeral=True)
            return
        gid = self.guild_id or (interaction.guild_id or 0)
        target_uid = self.user.id if self.user else interaction.user.id
        ok, msg, info = await asyncio.to_thread(
            core.upgrade_card_master_rank, gid, target_uid, target_card_id, True
        )
        if not ok:
            await core.safe_send_response(interaction, f"❌ {msg}", ephemeral=True)
            return
        extra = ""
        if info.get("unlocked_ac_now") and isinstance(info.get("costume"), dict):
            extra += f"\n🎨 **[{info['costume'].get('name', '3D 의상')}] 어나더 컬러 3종 해금!**"
        if info.get("unlocked_hair_now"):
            extra += " 💇 **한정 헤어스타일 해금!**"
        self.status_notice = f"{msg} (`+{info.get('diff_power', 0):,} ⚔️`){extra}"
        data = await asyncio.to_thread(core.load_data)
        await self._commit_ui_update(interaction, data=data, sync_page_to_selected=True)

    @discord.ui.button(label="💎 크리스탈로 돌파", style=discord.ButtonStyle.primary, row=3)
    async def btn_upgrade_crystal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        target_card_id = await self._ensure_selected_card_id(interaction)
        if not target_card_id:
            await core.safe_send_response(interaction, "❌ 선택된 카드가 없습니다. 위 목록에서 카드를 먼저 선택해 주세요.", ephemeral=True)
            return
        gid = self.guild_id or (interaction.guild_id or 0)
        target_uid = self.user.id if self.user else interaction.user.id
        ok, msg, info = await asyncio.to_thread(
            core.upgrade_card_master_rank, gid, target_uid, target_card_id, False
        )
        if not ok:
            await core.safe_send_response(interaction, f"❌ {msg}", ephemeral=True)
            return
        extra = ""
        if info.get("unlocked_ac_now") and isinstance(info.get("costume"), dict):
            extra += f"\n🎨 **[{info['costume'].get('name', '3D 의상')}] 어나더 컬러 3종 해금!**"
        if info.get("unlocked_hair_now"):
            extra += " 💇 **한정 헤어스타일 해금!**"
        self.status_notice = f"{msg} (`-{info.get('cost_crystals', 0):,}💎`, `+{info.get('diff_power', 0):,} ⚔️`){extra}"
        data = await asyncio.to_thread(core.load_data)
        await self._commit_ui_update(interaction, data=data, sync_page_to_selected=True)

    @discord.ui.button(label="👗 의상실 바로가기", style=discord.ButtonStyle.secondary, row=3)
    async def btn_goto_wardrobe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        gid = self.guild_id or (interaction.guild_id or 0)
        g_key = str(gid)
        u_obj = self.user or interaction.user
        u_key = str(u_obj.id)
        u_cards = core.safe_get_dict(data, "gacha_users", g_key, u_key, "cards")
        card = u_cards.get(str(self.selected_card_id))
        if not isinstance(card, dict):
            card = next((c for c in u_cards.values() if isinstance(c, dict) and str(c.get("id")) == str(self.selected_card_id)), None)
        resolved_cid = MyInventoryView._resolve_card_char_id(card) if isinstance(card, dict) else None
        init_cid = resolved_cid if (resolved_cid in core.CHARACTER_MAP) else 1
        view = CharacterCostumeWardrobeView(u_obj, guild_id=gid, initial_char_id=init_cid)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @discord.ui.button(label="🌸 특훈 전", style=discord.ButtonStyle.secondary, row=3)
    async def btn_stage_normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.illust_stage = "normal"
        data = await asyncio.to_thread(core.load_data)
        await self._commit_ui_update(interaction, data=data, sync_page_to_selected=True)

    @discord.ui.button(label="✨ 특훈 후", style=discord.ButtonStyle.primary, row=3)
    async def btn_stage_trained(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.illust_stage = "after_training"
        data = await asyncio.to_thread(core.load_data)
        await self._commit_ui_update(interaction, data=data, sync_page_to_selected=True)

    @discord.ui.button(label="◀ 카드 목록", style=discord.ButtonStyle.secondary, row=4)
    async def prev_list_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.card_page = max(0, self.card_page - 1)
        self.status_notice = ""
        data = await asyncio.to_thread(core.load_data)
        await self._commit_ui_update(interaction, data=data, sync_page_to_selected=False)

    @discord.ui.button(label="📄 1 / 1", style=discord.ButtonStyle.secondary, disabled=True, row=4)
    async def list_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)

    @discord.ui.button(label="카드 목록 ▶", style=discord.ButtonStyle.secondary, row=4)
    async def next_list_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.card_page += 1
        self.status_notice = ""
        data = await asyncio.to_thread(core.load_data)
        await self._commit_ui_update(interaction, data=data, sync_page_to_selected=False)


class SekaiLiveView(core.SafeView):
    """내 5인 유닛 덱 & 3D 의상 시너지로 즐기는 세카이 라이브 & 7일 스탬프 랠리 뷰"""
    def __init__(self, user: discord.User | None = None, guild_id: int = 0, initial_song_id: str | None = None):
        super().__init__(timeout=600)
        self.user = user
        self.guild_id = guild_id
        valid_ids = {s["id"] for s in core.PROSEKA_LIVE_SONGS}
        self.selected_song_id = initial_song_id if initial_song_id in valid_ids else core.PROSEKA_LIVE_SONGS[0]["id"]
        self.last_result: dict | None = None
        self._lock = asyncio.Lock()
        self._refresh_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 세카이 라이브 무대는 **{self.user.display_name}**님 전용입니다. `/설정` (`🎮 미니게임` ➔ `⚔️ 세카이 라이브`)에서 열어보세요!",
                ephemeral=True
            )
            return False
        if not self.user:
            self.user = interaction.user
        return True

    def _refresh_components(self):
        opts = []
        for s in core.PROSEKA_LIVE_SONGS[:25]:
            opts.append(discord.SelectOption(
                label=f"{s['attr']} {s['title']} (Lv.{s['level']})"[:100],
                value=s["id"],
                description=f"{s['unit']} · BPM {s['bpm']}"[:100],
                default=(s["id"] == self.selected_song_id),
            ))
        self.song_select.options = opts

    def build_embed(self) -> discord.Embed:
        self._refresh_components()
        data = core.load_data()
        g_key = str(self.guild_id or 0)
        u_id = self.user.id if self.user else 0
        u_name = self.user.display_name if self.user else "유저"
        u_key = str(u_id)
        prof = core.ensure_user_profile(data, u_key, u_name)
        g_user = core.safe_get_dict(data, "gacha_users", g_key, u_key)
        u_cards = core.as_dict(g_user.get("cards"))

        song = next((s for s in core.PROSEKA_LIVE_SONGS if s["id"] == self.selected_song_id), core.PROSEKA_LIVE_SONGS[0])

        saved_deck_ids = prof.get("deck") or g_user.get("deck") or []
        if not isinstance(saved_deck_ids, list):
            saved_deck_ids = []
        deck_cards = [u_cards[str(cid)] for cid in saved_deck_ids if str(cid) in u_cards and isinstance(u_cards.get(str(cid)), dict)]
        used_auto = False
        if not deck_cards and u_cards:
            used_auto = True
            deck_cards = sorted([c for c in u_cards.values() if isinstance(c, dict)], key=lambda c: (-core.get_card_power(c), -c.get("star_num", 1)))[:5]

        today_str = core.get_today_str()
        live_stats = core.as_dict(prof.get("sekai_live"))
        daily_used = int(live_stats.get("daily_count", 0)) if live_stats.get("last_date") == today_str else 0
        stamps = int(live_stats.get("stamps", 0))
        best_score = int(live_stats.get("best_score", 0))
        rally_clears = int(live_stats.get("rally_clears", 0))
        crystals = int(prof.get("crystals", 0))

        stamp_bar = core.format_progress_bar(stamps, 7, slots=7)
        daily_val = f"**`{daily_used} / 3회`** *(남음 `{max(0, 3 - daily_used)}회`)*" if daily_used < 3 else "**`3 / 3회 완료`** *(🏋️ 연습 무제한)*"

        embed = discord.Embed(
            title=f"⚔️ {self.user.display_name}님의 세카이 라이브",
            description=(
                f"🎵 **{song['title']}**\n"
                f"└ `{song['unit']}` · {song['attr']} · `MASTER Lv.{song['level']}` · `BPM {song['bpm']}`"
            ),
            color=discord.Color.from_rgb(255, 105, 180) if self.last_result and self.last_result.get("rank") in ("SS", "S") else discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.add_field(name="📅 오늘 보상 라이브", value=daily_val, inline=True)
        embed.add_field(name="🏆 개인 최고 스코어", value=f"**`{best_score:,} 점`**", inline=True)
        embed.add_field(name="💎 보유 크리스탈", value=f"**`{crystals:,} 💎`**", inline=True)
        embed.add_field(
            name="🎫 7회 스탬프 랠리 (완주 +300💎)",
            value=f"**{stamps} / 7** *(완주 `{rally_clears}회`)*\n{stamp_bar}",
            inline=False,
        )
        pr = core.get_player_rank_info(g_user.get("player_rank_exp", 0))
        pr_bar = core.format_progress_bar(pr["cur_exp"], max(1, pr["need_exp"]), slots=10) if pr["need_exp"] else "MAX"
        embed.add_field(
            name=f"🎖️ 플레이어 랭크 Rank {pr['rank']}",
            value=f"`{pr['cur_exp']:,} / {pr['need_exp']:,} EXP` *(캐랭·마랭과 별개)*\n{pr_bar}",
            inline=False,
        )

        if self.last_result:
            r = self.last_result
            rs = r["song"]
            combo_txt = "✨ ALL PERFECT!" if r["is_all_perfect"] else ("🔥 FULL COMBO" if r["is_full_combo"] else "🎵 CLEAR")
            new_best_txt = " 🆕 **NEW RECORD!**" if r["is_new_best"] else ""
            if r["is_practice"]:
                reward_txt = "🏋️ *일일 보상(3회) 완료 — 연습 모드로 클리어*"
            else:
                rally_note = f"\n🎊 **스탬프 7회 완주 보너스 `+{r['rally_bonus']} 💎` 추가 달성!**" if r["rally_bonus"] > 0 else ""
                reward_txt = f"💎 획득 **`+{r['gained_crystals']:,} 💎`** *(보유 `{r['current_crystals']:,} 💎`)*{rally_note}"
            if r.get("player_rank_gained_exp"):
                rank_up_txt = (
                    f" 🎉 **랭크 업! Rank {r['player_rank_prev']} ➔ {r['player_rank']}**"
                    if r.get("player_rank_up") else ""
                )
                reward_txt += f"\n🎖️ 플레이어 랭크 EXP `+{r['player_rank_gained_exp']}`{rank_up_txt}"

            embed.add_field(
                name=f"🎉 직전 라이브 결과 — {r['rank_label']} · {combo_txt}",
                value=(
                    f"🎵 `{rs['title']}` ({rs['attr']} · `{rs['unit']}`)\n"
                    f"🏆 스코어: **`{r['score']:,} 점`**{new_best_txt}\n"
                    f"└ 적용 종합력 `⚔️ {r['effective_power']:,}` · 총 시너지 **`+{r['total_bonus_pct']}%`**\n"
                    f"└ 속성 `{r['attr_matches']}명(+{r['attr_bonus_pct']}%)` · 유닛 `{r['unit_matches']}명(+{r['unit_bonus_pct']}%)`\n"
                    f"└ 의상/컬러 `(+{r['costume_bonus_pct']}%)` · 파트너 `(+{r['partner_bonus_pct']}%)`\n"
                    f"{reward_txt}"
                ),
                inline=False
            )

        if not deck_cards:
            embed.add_field(name="🎸 출전 유닛 덱", value="보유한 카드가 없습니다! `/설정` (`🎰 프로세카 뽑기`)에서 카드를 뽑아보세요.", inline=False)
        else:
            deck_lines = []
            base_pwr = 0
            for idx, c in enumerate(deck_cards, start=1):
                pwr = core.get_card_power(c)
                base_pwr += pwr
                mr = core._safe_card_int(c.get("master_rank"), 0)
                mr_tag = f" `✦MR.{mr}`" if mr > 0 else ""
                eq_cos = core.get_user_equipped_costume(self.guild_id, self.user.id, MyInventoryView._resolve_card_char_id(c) or 1)
                cos_txt = ""
                if not eq_cos.get("is_default"):
                    cos_txt = " 🎨" if eq_cos.get("color_variant", "orig") != "orig" else " 👗"
                role = "👑" if idx == 1 else f"`{idx}.`"
                r_lbl = core.get_card_rarity_label(c)
                pref = c.get("prefix") or "카드"
                cname = c.get("char_name") or "캐릭터"
                c_attr = c.get("attr") or "-"
                deck_lines.append(f"{role} `{r_lbl}` **{cname}** [{pref}]{cos_txt}\n└ {c_attr}{mr_tag} · `⚔️ {pwr:,}`")

            deck_mode = "자동 추천 TOP 5" if used_auto else "저장 5인 덱"
            embed.add_field(
                name=f"🎸 출전 덱 ({deck_mode} · 기본 ⚔️ {base_pwr:,})",
                value="\n".join(deck_lines)[:1024],
                inline=False
            )
            embed.set_thumbnail(url=core.get_proseka_card_image_url(deck_cards[0], "auto"))

        embed.set_footer(text="속성(+12%) · 유닛(+8%) · 의상(+5%) · 어나더컬러(+10%) · 파트너(+5%) 반영")
        return embed

    async def _run_live(self, interaction: discord.Interaction, song_id: str | None):
        if self._lock.locked():
            await core.safe_send_response(
                interaction,
                "⏳ 이미 세카이 라이브 무대가 진행 중입니다! 잠시 후 다시 시도해주세요.",
                ephemeral=True
            )
            return
        async with self._lock:
            await core.safe_defer(interaction)
            s_obj = next((s for s in core.PROSEKA_LIVE_SONGS if s["id"] == song_id), None) if song_id else None
            title_preview = s_obj["title"] if s_obj else "랜덤 세카이 명곡"
            fever_embed = discord.Embed(
                title=f"🎶 [{title_preview}] LIVE START!!",
                description=(
                    "✨ **5인 유닛 멤버가 스테이지에 올라섰습니다!**\n"
                    "🎵 리듬 노트 집중... **FEVER CHANCE!! ⚡**"
                ),
                color=discord.Color.gold(),
                timestamp=datetime.datetime.now(core.KST)
            )
            try:
                await interaction.edit_original_response(embed=fever_embed, view=None)
            except Exception:
                pass

            await asyncio.sleep(1.0)
            ok, msg, res = await asyncio.to_thread(
                core.execute_sekai_live, self.guild_id, interaction.user.id, song_id, interaction.user.display_name
            )
            if not ok:
                await interaction.edit_original_response(embed=self.build_embed(), view=self)
                await core.safe_send_response(interaction, f"❌ {msg}", ephemeral=True)
                return

            self.last_result = res
            self.selected_song_id = res["song"]["id"]
            await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="🎵 플레이할 세카이 라이브 곡을 선택하세요...",
        options=[discord.SelectOption(label="곡 목록 불러오는 중...", value="0")],
        row=0,
    )
    async def song_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        await core.safe_defer(interaction)
        self.selected_song_id = select.values[0]
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🎵 세카이 라이브 시작!", style=discord.ButtonStyle.success, row=1)
    async def btn_start_live(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run_live(interaction, self.selected_song_id)

    @discord.ui.button(label="🎲 랜덤 선곡 라이브", style=discord.ButtonStyle.primary, row=1)
    async def btn_random_live(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run_live(interaction, None)

    @discord.ui.button(label="🔄 덱/상태 새로고침", style=discord.ButtonStyle.secondary, row=1)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)


# ==========================================
# 프로세카 Cog 명령어 등록
# ==========================================
class GachaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="프로세카뽑기", description="프로세카 한섭 뽑기 (일반·페스·생일 / 리세마라 연습 / 일일 운명 다시 뽑기 / 생일 무료 단차)")
    @app_commands.describe(
        횟수="1회 뽑기(단차) 또는 10회 뽑기(10연차 - ★3 이상 확정)를 선택하세요.",
        배너="[봇주인 전용] 뽑기 배너를 선택합니다 (일반·페스티벌 ★4 2배·생일 스페셜)",
        연출="(선택) 무지개 승격 & 대사 선공개 연출 표시 여부를 선택하세요.",
        모드="(선택) 일반 뽑기 / 리세마라 연습(무저장·무쿨타임) / 운명 다시 뽑기(1일 1회) / 생일 무료 단차"
    )
    @app_commands.choices(
        횟수=[
            app_commands.Choice(name="🎵 1회 뽑기 (단차)", value=1),
            app_commands.Choice(name="🌈 10회 뽑기 (10연차 - ★3 이상 확정!)", value=10)
        ],
        배너=[
            app_commands.Choice(name="🌟 일반 / 현재 픽업 가챠 (★4 3.0%)", value="normal"),
            app_commands.Choice(name="🎊 컬러풀 페스티벌 (★4 2배 · 6.0%!)", value="fes"),
            app_commands.Choice(name="🎂 생일 / 기념일 스페셜 (생일한정 UP!)", value="birthday"),
        ],
        연출=[
            app_commands.Choice(name="✨ 무지개 승격 & 대사 연출 보기 (기본)", value="anim"),
            app_commands.Choice(name="⏭️ 연출 스킵 (결과 즉시 표시)", value="skip"),
        ],
        모드=[
            app_commands.Choice(name="💎 일반 뽑기 (보관함 저장 · 기본)", value="normal"),
            app_commands.Choice(name="🧪 리세마라 연습 모드 (저장 안 됨 · 무쿨타임)", value="practice"),
            app_commands.Choice(name="🔮 운명 다시 뽑기 (1일 1회 · 3세트 중 택1)", value="destiny"),
            app_commands.Choice(name="🎂 오늘의 생일 무료 단차 (생일 당일 1회)", value="birthday_free"),
        ]
    )
    async def proseka_pull_cmd(
        self,
        interaction: discord.Interaction,
        횟수: app_commands.Choice[int] = None,
        배너: app_commands.Choice[str] = None,
        연출: app_commands.Choice[str] = None,
        모드: app_commands.Choice[str] = None,
    ):
        is_owner = await _is_interaction_bot_owner(interaction, self.bot)
        if 배너 is not None and not is_owner:
            await core.safe_send_response(
                interaction,
                content="❌ 프로세카 가챠 배너 선택은 **봇주인(Bot Owner)** 만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        mode_val = 모드.value if 모드 else "normal"
        skip_anim = (연출 is not None and 연출.value == "skip")
        guild_id = interaction.guild_id or 0
        if not await ensure_proseka_registered(interaction, guild_id):
            return

        if mode_val == "practice":
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            pickup_cfg = core.as_dict(data.get("gacha_pickup")) or core.DEFAULT_CONFIG["gacha_pickup"]
            banner_key = 배너.value if (배너 is not None and is_owner) else core.get_active_proseka_banner(pickup_cfg)
            drawn = await asyncio.to_thread(core.draw_proseka_cards, pickup_cfg, count=10, banner_type=banner_key)
            if not drawn:
                await interaction.followup.send("❌ 한국 서버 캐릭터 DB를 불러오지 못했습니다.", ephemeral=True)
                return
            await asyncio.to_thread(core.annotate_drawn_is_new, guild_id, interaction.user.id, drawn)
            sim_view = RerollSimulatorView(interaction.user, guild_id, pickup_cfg, banner_type=banner_key, initial_drawn=drawn)
            grid_bytes, grid_fn = await asyncio.to_thread(
                core.build_10pull_grid_image_bytes, drawn, banner_key, "연습 1회차"
            )
            embed = sim_view.build_sim_embed(grid_fn if grid_bytes else None)
            if grid_bytes and grid_fn:
                await interaction.followup.send(
                    embed=embed, file=discord.File(io.BytesIO(grid_bytes), filename=grid_fn), view=sim_view, wait=True
                )
            else:
                await interaction.followup.send(embed=embed, view=sim_view, wait=True)
            return

        if mode_val == "birthday_free":
            can_bday, _, b_reason = await asyncio.to_thread(
                core.can_use_daily_birthday_free_pull, guild_id, interaction.user.id
            )
            if not can_bday:
                await core.safe_send_response(interaction, content=f"❌ {b_reason}", ephemeral=True)
                return
            await core.safe_defer(interaction)
            ok, msg, _, drawn = await asyncio.to_thread(core.draw_birthday_free_pull, guild_id, interaction.user.id)
            if not ok:
                await interaction.followup.send(f"❌ {msg}", ephemeral=True)
                return
            data = await asyncio.to_thread(core.load_data)
            pickup_cfg = core.as_dict(data.get("gacha_pickup")) or core.DEFAULT_CONFIG["gacha_pickup"]
            pity_info = core.get_user_gacha_pity_state(guild_id, interaction.user.id, data=data)
            pity_info["added_badges"] = len(drawn)
            next_banner = (배너.value if (배너 is not None and is_owner) else core.get_active_proseka_banner(pickup_cfg))
            repull_view = GachaPullAgainView(
                interaction.user, banner_type=next_banner, skip_anim=skip_anim, guild_id=guild_id, pity_info=pity_info
            )
            await send_gacha_pull_result(
                interaction,
                drawn,
                pickup_cfg,
                1,
                repull_view,
                banner_type="birthday",
                skip_anim=skip_anim,
                mode_note=msg,
                pity_info=pity_info,
            )
            return

        if mode_val == "destiny":
            can_dest, d_reason = await asyncio.to_thread(
                core.can_use_daily_destiny_reroll, guild_id, interaction.user.id
            )
            if not can_dest:
                await core.safe_send_response(interaction, content=f"❌ {d_reason}", ephemeral=True)
                return
            can_pull, rem = check_and_update_gacha_cooldown(interaction.user.id, skip_anim=True)
            if not can_pull:
                await core.safe_send_response(
                    interaction,
                    content=f"⏳ **봇의 원활한 서비스를 위해, 뽑기 쿨타임입니다!** `{rem:.1f}초` 후에 다시 눌러주세요.",
                    ephemeral=True
                )
                return
            await core.safe_defer(interaction)
            data = await asyncio.to_thread(core.load_data)
            pickup_cfg = core.as_dict(data.get("gacha_pickup")) or core.DEFAULT_CONFIG["gacha_pickup"]
            banner_key = 배너.value if (배너 is not None and is_owner) else core.get_active_proseka_banner(pickup_cfg)
            ok, msg, first_set = await asyncio.to_thread(
                core.start_daily_destiny_reroll, guild_id, interaction.user.id, pickup_cfg, banner_key
            )
            if not ok:
                await interaction.followup.send(f"❌ {msg}", ephemeral=True)
                return
            destiny_view = DestinyRerollView(interaction.user, guild_id, pickup_cfg, banner_key, first_set)
            grid_bytes, grid_fn = await asyncio.to_thread(
                core.build_10pull_grid_image_bytes, first_set, banner_key, "운명 1세트"
            )
            embed = destiny_view.build_destiny_embed(grid_fn if grid_bytes else None)
            if grid_bytes and grid_fn:
                await interaction.followup.send(
                    embed=embed, file=discord.File(io.BytesIO(grid_bytes), filename=grid_fn), view=destiny_view, wait=True
                )
            else:
                await interaction.followup.send(embed=embed, view=destiny_view, wait=True)
            return

        can_pull, rem = check_and_update_gacha_cooldown(interaction.user.id, skip_anim=skip_anim)
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
        pickup_cfg = core.as_dict(data.get("gacha_pickup")) or core.DEFAULT_CONFIG["gacha_pickup"]
        banner_key = 배너.value if (배너 is not None and is_owner) else core.get_active_proseka_banner(pickup_cfg)
        drawn, pity_info = await asyncio.to_thread(
            core.execute_real_proseka_pull, guild_id, interaction.user.id, pickup_cfg, pull_count, banner_key
        )

        if not drawn:
            await interaction.followup.send("❌ 한국 서버 캐릭터 DB를 불러오지 못했습니다.", ephemeral=True)
            return

        repull_view = GachaPullAgainView(
            interaction.user, banner_type=banner_key, skip_anim=skip_anim, guild_id=guild_id, pity_info=pity_info
        )
        await send_gacha_pull_result(
            interaction,
            drawn,
            pickup_cfg,
            pull_count,
            repull_view,
            banner_type=banner_key,
            skip_anim=skip_anim,
            pity_info=pity_info,
        )

    @proseka_pull_cmd.error
    async def proseka_pull_cmd_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            rem = error.retry_after
            msg = f"⏳ **봇의 원활한 서비스를 위해, 뽑기 쿨타임입니다!** `{rem:.1f}초` 후에 다시 눌러주세요."
            await core.safe_send_response(interaction, content=msg, ephemeral=True)
        else:
            err_msg = f"❌ 뽑기 처리 중 오류가 발생했습니다: `{error}`"
            await core.safe_send_response(interaction, err_msg, ephemeral=True)

    @app_commands.command(name="프로세카등록", description="프로세카 가챠에 등록하고 ★1 카드 전체를 기본 지급받습니다 (등록 후 뽑기 가능).")
    async def proseka_register_cmd(self, interaction: discord.Interaction):
        ok, msg, _ = await asyncio.to_thread(
            core.register_proseka_gacha_user, interaction.guild_id or 0, interaction.user.id
        )
        await core.safe_send_response(interaction, f"{'🎉' if ok else 'ℹ️'} {msg}", ephemeral=True)

    @app_commands.command(name="중복카드변환", description="2장 이상 중복 보유한 카드(원본 1장 및 🔒잠금 카드 제외)를 성급별 크리스탈로 일괄 변환합니다.")
    async def convert_duplicates_cmd(self, interaction: discord.Interaction):
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild_id or 0
        preview = await asyncio.to_thread(core.preview_duplicate_cards, guild_id, interaction.user.id)
        view = DuplicateConvertConfirmView(guild_id, interaction.user, preview)
        await core.safe_send_response(interaction, embed=view.build_preview_embed(), view=view, ephemeral=True)

    @app_commands.command(name="프로세카확률목록", description="한국 서버 모든 캐릭터(한정 포함) 텍스트 및 배너별 확률 목록을 5개씩 페이지로 확인합니다.")
    @app_commands.describe(배너="(선택) 확인할 가챠 배너 확률표 (일반 / 페스티벌 ★4 2배 / 생일 스페셜)")
    @app_commands.choices(배너=[
        app_commands.Choice(name="🌟 일반 / 현재 픽업 가챠 (★4 3.0%)", value="normal"),
        app_commands.Choice(name="🎊 컬러풀 페스티벌 (★4 2배 · 6.0%)", value="fes"),
        app_commands.Choice(name="🎂 생일 / 기념일 스페셜 (★4·생일 3.5%)", value="birthday"),
    ])
    async def proseka_rate_list_cmd(self, interaction: discord.Interaction, 배너: app_commands.Choice[str] = None):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        pickup_cfg = core.as_dict(data.get("gacha_pickup")) or core.DEFAULT_CONFIG["gacha_pickup"]
        banner_key = 배너.value if 배너 else core.get_active_proseka_banner(pickup_cfg)
        prob_cards = core.calculate_card_probabilities(pickup_cfg, banner_type=banner_key)

        view = ProsekaRatePaginationView(prob_cards, pickup_cfg, items_per_page=5, banner_type=banner_key)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @app_commands.command(name="내캐릭터", description="내가 뽑은 프로세카 캐릭터를 캐릭터별·유닛별로 확인하고 일러스트, 잠금(🔒), 중복 변환을 관리합니다.")
    @app_commands.describe(
        유저="(선택) 다른 유저의 캐릭터 보관함을 구경할 수 있습니다.",
        캐릭터="(선택) 특정 캐릭터의 보유 카드만 바로 필터링하여 봅니다 (예: 요이사키 카나데, 하츠네 미쿠)",
        검색어="(선택) 캐릭터 이름, 카드명, 유닛, 한정 여부 등으로 보유 카드를 검색합니다 (예: 한정, 버츄얼)"
    )
    @app_commands.autocomplete(캐릭터=core.oshi_char_autocomplete)
    async def my_characters_cmd(self, interaction: discord.Interaction, 유저: discord.User = None, 캐릭터: str = None, 검색어: str = None):
        await core.safe_defer(interaction)
        target_user = 유저 or interaction.user
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id or 0)
        u_key = str(target_user.id)

        user_cards_dict = core.safe_get_dict(data, "gacha_users", g_key, u_key, "cards")
        card_list = [c for c in user_cards_dict.values() if isinstance(c, dict)]

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

        initial_char_id = None
        if 캐릭터 and 캐릭터.strip() and 캐릭터.strip() != "NONE":
            c_q = 캐릭터.strip().lower()
            initial_char_id = next(
                (cid for cid, info in core.CHARACTER_MAP.items() if info["name"].lower() == c_q),
                None,
            )
            if initial_char_id is None:
                initial_char_id = next(
                    (cid for cid, info in core.CHARACTER_MAP.items() if c_q in info["name"].lower()),
                    None,
                )

        view = MyInventoryView(
            target_user,
            card_list,
            items_per_page=10,
            search_keyword=clean_kw,
            guild_id=interaction.guild_id or 0,
            initial_char_id=initial_char_id,
        )
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

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
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

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
                    f"• 현재 보유 크리스탈: `{my_crystals:,}개` (`/설정`의 `📅 출석체크` 또는 `💎 중복 카드 변환`으로 획득 가능)",
                    ephemeral=True
                )
                return
            req_cards = core.safe_get_dict(data, "gacha_users", g_key, r_key, "cards")
            tgt_cards = core.safe_get_dict(data, "gacha_users", g_key, t_key, "cards")
            if not req_cards:
                await interaction.followup.send("❌ 보유한 카드가 없습니다. `/설정` (`🎰 프로세카 뽑기`)에서 먼저 캐릭터를 뽑아주세요!", ephemeral=True)
                return
            if not tgt_cards:
                await interaction.followup.send(f"❌ **{상대유저.display_name}**님이 아직 이 서버에서 보유한 카드가 없습니다.", ephemeral=True)
                return
            studio_view = InteractiveCardTradeStudioView(interaction.guild_id or 0, interaction.user, 상대유저, req_cards, tgt_cards, my_crystals)
            if 내카드 and 내카드 in req_cards and not req_cards[내카드].get("locked", False):
                studio_view.selected_my_cid = 내카드
            if 상대카드 and 상대카드 in tgt_cards and not tgt_cards[상대카드].get("locked", False):
                studio_view.selected_tgt_cid = 상대카드
            await interaction.followup.send(embed=studio_view.build_embed(), view=studio_view, ephemeral=True, wait=True)
            return

        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id or 0)
        r_key = str(interaction.user.id)
        t_key = str(상대유저.id)

        my_crystals = core.safe_get_dict(data, "user_profiles", r_key).get("crystals", 0)
        if my_crystals < 100:
            await interaction.followup.send(
                f"❌ **카드 교환에는 크리스탈 `100개`가 필요합니다!**\n"
                f"• 현재 보유 크리스탈: `{my_crystals:,}개` (`/설정`의 `📅 출석체크` 또는 `💎 중복 카드 변환`으로 획득 가능)",
                ephemeral=True
            )
            return

        req_cards = core.safe_get_dict(data, "gacha_users", g_key, r_key, "cards")
        tgt_cards = core.safe_get_dict(data, "gacha_users", g_key, t_key, "cards")

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
            await interaction.followup.send("🔒 선택한 `내카드`가 **잠금 보호** 상태입니다! 교환하려면 `/설정` (`🎒 프로세카 카드 보관함`)에서 잠금을 먼저 해제해 주세요.", ephemeral=True)
            return
        if tgt_cards[상대카드].get("locked", False):
            await interaction.followup.send(f"🔒 {상대유저.display_name}님의 해당 카드는 **잠금 보호** 상태여서 교환을 요청할 수 없습니다.", ephemeral=True)
            return

        my_c = req_cards[내카드]
        tgt_c = tgt_cards[상대카드]

        embed = discord.Embed(
            title="🔄 프로세카 1:1 카드 교환 신청 도착!",
            description=(
                f"{상대유저.mention}님, {interaction.user.mention}님이 **1:1 카드 교환**을 요청했습니다.\n"
                "아래 카드와 하단 미리보기를 확인한 뒤 **`[🤝 교환 수락]`** 버튼을 눌러주세요."
            ),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.add_field(
            name=f"📤 {interaction.user.display_name}님 제공",
            value=(
                f"**{my_c['rarity_label']} {my_c['char_name']}** [{my_c['prefix']}]\n"
                f"└ `{my_c.get('limit_label', '통상')}` · `Lv.{my_c.get('level', 1)}` · `⚔️ {core.get_card_power(my_c):,}` · 보유 `{my_c.get('count', 1)}장`"
            ),
            inline=False,
        )
        embed.add_field(
            name=f"📥 {상대유저.display_name}님 제공",
            value=(
                f"**{tgt_c['rarity_label']} {tgt_c['char_name']}** [{tgt_c['prefix']}]\n"
                f"└ `{tgt_c.get('limit_label', '통상')}` · `Lv.{tgt_c.get('level', 1)}` · `⚔️ {core.get_card_power(tgt_c):,}` · 보유 `{tgt_c.get('count', 1)}장`"
            ),
            inline=False,
        )
        embed.add_field(
            name="💎 교환 비용",
            value=f"신청자({interaction.user.display_name}) 크리스탈 `100 💎` *(수락 시 차감)*",
            inline=False,
        )
        embed.set_thumbnail(url=core.get_proseka_card_image_url(my_c, "auto"))
        embed.set_footer(text="하단 [🖼️ 제공 카드] · [🖼️ 대상 카드] 버튼으로 양쪽 일러스트를 확인할 수 있습니다")
        view = CardTradeAcceptView(interaction.guild_id or 0, interaction.user, 상대유저, my_c, tgt_c)
        await interaction.followup.send(content=상대유저.mention, embed=embed, view=view, wait=True)

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
        partner_id = core.safe_get_dict(data, "user_profiles", u_key).get("partner_id")

        if not partner_id:
            await interaction.followup.send(
                "❌ **파트너(짝꿍)가 등록되어 있지 않습니다!**\n"
                "`/설정` (`👤 개인` ➔ `💑 파트너 스튜디오`)에서 파트너를 먼저 맺은 뒤 카드를 선물할 수 있습니다.",
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

        embed = discord.Embed(
            title="🎁 파트너 카드 선물 완료!",
            description=f"💖 {interaction.user.mention}님이 파트너 <@{partner_id}>님에게 카드를 선물했습니다!",
            color=discord.Color.from_rgb(255, 105, 180),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.add_field(
            name="🎀 선물한 카드",
            value=(
                f"**{gifted_c['rarity_label']} {gifted_c['char_name']}** [{gifted_c['prefix']}]\n"
                f"└ `{gifted_c.get('limit_label', '통상')}` · `{gifted_c.get('unit', '-')}` · `Lv.{gifted_c.get('level', 1)}`"
            ),
            inline=False,
        )
        if 메시지 and 메시지.strip():
            embed.add_field(name="💌 선물 메시지", value=f"> {메시지.strip()[:500]}", inline=False)
        embed.set_footer(text=f"소모: 50 💎 • 잔여 크리스탈: {rem_crystals:,} 💎")

        gift_view = SimpleCardIllustToggleView(gifted_c, initial_mode="normal") if core.can_card_awaken(gifted_c) else None
        img_bytes, filename = await asyncio.to_thread(core.fetch_proseka_card_image_bytes, gifted_c, "normal")
        send_kw = {"content": f"<@{partner_id}>", "embed": embed}
        if gift_view is not None:
            send_kw["view"] = gift_view
        if img_bytes and filename:
            file = discord.File(io.BytesIO(img_bytes), filename=filename)
            embed.set_image(url=f"attachment://{filename}")
            await interaction.followup.send(file=file, **send_kw)
        else:
            embed.set_image(url=core.get_proseka_card_image_url(gifted_c, "normal"))
            await interaction.followup.send(**send_kw)

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
            title=f"🎶 프로세카 {info['server_label']} 실시간 이벤트",
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )

        if ev:
            ev_name = ev.get("name", "제목 없음")
            ev_type = core.EVENT_TYPE_MAP.get(ev.get("eventType", ""), "🎵 이벤트")
            start_ms = ev.get("startAt", 0)
            end_ms = ev.get("aggregateAt") or ev.get("closedAt") or 0

            start_dt = datetime.datetime.fromtimestamp(start_ms / 1000, tz=core.KST).strftime("%m/%d %H:%M") if start_ms else "-"
            end_dt = datetime.datetime.fromtimestamp(end_ms / 1000, tz=core.KST).strftime("%m/%d %H:%M") if end_ms else "-"
            prog_line, rem_line = core.format_event_progress_bar(start_ms, end_ms)

            embed.description = f"🏆 **[{info['event_status']}] {ev_name}**\n└ {ev_type} · 기간 `{start_dt}` ~ `{end_dt}` (KST)"
            embed.add_field(
                name="⏳ 이벤트 진행률",
                value=f"{prog_line}\n{rem_line}",
                inline=False,
            )
        else:
            embed.add_field(name="🏆 이벤트 정보", value="현재 이벤트 데이터를 불러올 수 없습니다.", inline=False)

        if gachas:
            g_lines = []
            for g in gachas[:5]:
                g_name = g.get("name", "가챠")
                g_end_ms = g.get("endAt", 0)
                g_end_dt = datetime.datetime.fromtimestamp(g_end_ms / 1000, tz=core.KST).strftime("%m/%d %H:%M") if g_end_ms else "-"
                g_lines.append(f"• {g_name}\n└ 종료 `{g_end_dt}`")
            if len(gachas) > 5:
                g_lines.append(f"*…외 `{len(gachas) - 5}개` 배너 진행 중*")
            embed.add_field(name=f"🎰 진행 중인 가챠 배너 ({len(gachas)}개)", value="\n".join(g_lines)[:1024], inline=False)
        else:
            embed.add_field(name="🎰 진행 중인 가챠 배너", value="현재 진행 중인 가챠 배너가 없습니다.", inline=False)

        action_view = EventInfoView(self.bot, interaction.user)
        if info.get("banner_bytes") and info.get("banner_filename"):
            file = discord.File(io.BytesIO(info["banner_bytes"]), filename=info["banner_filename"])
            embed.set_image(url=f"attachment://{info['banner_filename']}")
            await interaction.followup.send(embed=embed, file=file, view=action_view, wait=True)
        else:
            await interaction.followup.send(embed=embed, view=action_view, wait=True)

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

        user_cards_dict = core.safe_get_dict(data, "gacha_users", g_key, u_key, "cards")
        if not user_cards_dict:
            await interaction.followup.send("❌ 보유한 카드가 없습니다. `/설정` (`🎰 프로세카 뽑기`)에서 먼저 캐릭터를 뽑아주세요!", ephemeral=True)
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
            mr = int(c.get("master_rank", 0))
            mr_tag = f" · `✦MR.{mr}`" if mr > 0 else ""
            lock_tag = " 🔒" if c.get("locked") else ""
            role = "👑" if idx == 1 else f"`{idx}.`"
            deck_lines.append(
                f"{role} `{c['rarity_label']}` **{c['char_name']}** [{c['prefix']}]{lock_tag}\n"
                f"└ `{c.get('limit_label', '통상')}` · `Lv.{cur_lvl}`{mr_tag} · `⚔️ {p_val:,}`"
            )

        embed = discord.Embed(
            title=f"🎸 {interaction.user.display_name}님의 5인 유닛 덱 편성 완료",
            description=f"⚔️ **총 종합력:** **`{total_deck_power:,}`** (`{len(chosen_ids)}명` 편성)",
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.add_field(name="🌟 편성 멤버", value="\n".join(deck_lines)[:1024], inline=False)
        embed.set_footer(text="편성된 덱은 /내프로필 · 세카이 라이브에 자동 반영됩니다")

        leader_card = user_cards_dict[chosen_ids[0]]
        deck_view = SimpleCardIllustToggleView(leader_card, initial_mode="normal") if core.can_card_awaken(leader_card) else None
        img_bytes, filename = await asyncio.to_thread(core.fetch_proseka_card_image_bytes, leader_card, "normal")
        send_kw = {"embed": embed}
        if deck_view is not None:
            send_kw["view"] = deck_view
        if img_bytes and filename:
            file = discord.File(io.BytesIO(img_bytes), filename=filename)
            embed.set_image(url=f"attachment://{filename}")
            await interaction.followup.send(file=file, **send_kw)
        else:
            embed.set_image(url=core.get_proseka_card_image_url(leader_card, "normal"))
            await interaction.followup.send(**send_kw)

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
            description=f"**{interaction.user.display_name}**님의 최애 캐릭터가 **`{캐릭터}`**(으)로 설정되었습니다!",
            color=discord.Color.from_rgb(255, 105, 180),
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.add_field(
            name="✨ 자동 반영 혜택",
            value=(
                "• **프로필 카드:** 보유한 오시 카드 중 최고 등급 일러스트 자동 표시\n"
                "• **일일 출석:** 오시 캐릭터의 세카이 대사 우선 매칭 · 캐랭 EXP 보너스"
            ),
            inline=False,
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
        liked_music_count = len(profile.get("liked_music", []))
        deck_ids = profile.get("deck", [])
        partner_id = profile.get("partner_id")
        crystals = profile.get("crystals", 0)

        global_att = core.as_dict(profile.get("attendance"))
        guild_att = core.safe_get_dict(data, "guild_attendance", g_key, u_key)

        g_total = guild_att.get("total_days", 0)
        g_streak = guild_att.get("streak", 0)
        all_total = global_att.get("total_days", 0)
        all_max = max(global_att.get("max_streak", 0), guild_att.get("max_streak", 0))

        grass_bar, _ = core.get_todo_galaxy_grass(profile)

        u_gacha = core.safe_get_dict(data, "gacha_users", g_key, u_key)
        user_cards_dict = core.as_dict(u_gacha.get("cards"))
        cards = [c for c in user_cards_dict.values() if isinstance(c, dict)]

        total_pulls = core.get_proseka_user_total_pulls(u_gacha)
        total_unique = len(cards)
        total_db_cards = len(core.PROSEKA_KR_CARDS)
        collect_rate = (total_unique / total_db_cards * 100) if total_db_cards > 0 else 0.0

        star4_count = sum(c.get("count", 1) for c in cards if c.get("rarity_type") == "rarity_4")
        bday_count = sum(c.get("count", 1) for c in cards if c.get("rarity_type") == "rarity_birthday")
        oshi_cards = [c for c in cards if oshi_raw and c.get("char_name") == oshi_raw]
        oshi_card_count = sum(c.get("count", 1) for c in oshi_cards)
        oshi_char_id = next((cid for cid, info in core.CHARACTER_MAP.items() if info["name"] == oshi_raw), None)
        if oshi_char_id:
            oshi_cos = core.get_user_equipped_costume(interaction.guild_id or 0, target_user.id, oshi_char_id)
            oshi_rk = core.calculate_character_rank(data, interaction.guild_id or 0, target_user.id, oshi_char_id)

        equipped_flags = core.get_user_equipped_rank_flags(interaction.guild_id or 0, target_user.id, data=data)
        pity_state = core.get_user_gacha_pity_state(interaction.guild_id or 0, target_user.id, data=data)

        embed = discord.Embed(
            title=f"🌟 {target_user.display_name}님의 norosi 프로필",
            color=discord.Color.from_rgb(255, 182, 193),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)
        if oshi_raw:
            oshi_sub_parts = [f"`{oshi_card_count}장`"]
            if oshi_char_id:
                oshi_sub_parts.append(f"🚩 `Rank {oshi_rk['rank']}`")
            oshi_val = f"**{oshi_raw}**\n└ {' · '.join(oshi_sub_parts)}"
            if oshi_char_id:
                oshi_val += f"\n└ 👗 `{core.truncate_text(oshi_cos['name'], 22)}`"
        else:
            oshi_val = "미설정"
        embed.add_field(name="👑 나의 오시", value=oshi_val, inline=True)
        embed.add_field(name="💑 파트너", value=f"<@{partner_id}>" if partner_id else "미등록", inline=True)
        embed.add_field(name="💎 크리스탈", value=f"**`{crystals:,} 💎`**", inline=True)
        embed.add_field(name="🎰 누적 뽑기", value=f"**`{total_pulls:,}회`**", inline=True)
        embed.add_field(name="🌟 ★4 · 🎂 생일", value=f"★4 `{star4_count}장` · 🎂 `{bday_count}장`", inline=True)
        embed.add_field(name="📚 도감 수집률", value=f"**`{collect_rate:.1f}%`**\n└ `{total_unique:,} / {total_db_cards:,}종`", inline=True)

        if equipped_flags:
            flags_val = "\n".join(
                f"• {f['emoji']} **`[{f['title']}]`** (`Rank {f.get('current_rank', f['tier_rank'])}`)"
                for f in equipped_flags
            )
        else:
            flags_val = "미장착 *(Rank 5+ 달성 시 `/캐릭터랭크`에서 장착 가능)*"
        embed.add_field(name="🚩 장착 중인 캐랭 칭호 깃발", value=flags_val, inline=False)

        gauge_text, badge_text = core.format_gacha_pity_display(pity_state, show_zero_tickets=True)
        embed.add_field(
            name="⚡ 가챠 보너스 게이지 (50pt ★4 · 100pt 픽업 ★4)",
            value=gauge_text,
            inline=False,
        )
        embed.add_field(
            name=f"🏅 가챠 배지 천장 ({pity_state['ceiling_cost']}개)",
            value=badge_text,
            inline=False,
        )

        ms = core.ensure_my_sekai(profile)
        ms_theme_name = core.MY_SEKAI_THEMES.get(ms.get("theme", "default"), {}).get("name", "🌌 기본 빈 세카이")
        ms_bonus = core.get_my_sekai_daily_bonus(profile)
        furn_cnt = len(ms.get("furniture", []))
        embed.add_field(
            name="🏠 마이세카이 미니 룸",
            value=f"**{ms_theme_name}**\n└ 가구 `{furn_cnt}/{len(core.MY_SEKAI_FURNITURE)}개` · 출석 이자 **`+{ms_bonus}💎/일`**",
            inline=False
        )
        embed.add_field(
            name="📅 출석 기록 & ❤️ 음악",
            value=(
                f"🏠 현재 서버: `{g_total:,}일` (`{g_streak:,}일 연속 🔥`)\n"
                f"🌍 전체 통합: `{all_total:,}일` *(최고 `{all_max:,}일`)* · ❤️ 음악 `{liked_music_count:,}곡`"
            ),
            inline=False
        )
        embed.add_field(
            name="🌱 최근 7일 은하수 잔디",
            value=f"{grass_bar}",
            inline=False
        )

        valid_deck_cards = [user_cards_dict[cid] for cid in deck_ids if cid in user_cards_dict]
        if valid_deck_cards:
            deck_lines = []
            total_deck_power = 0
            for idx, c in enumerate(valid_deck_cards, start=1):
                badge = "👑" if idx == 1 else f"`{idx}.`"
                lock_tag = " 🔒" if c.get("locked") else ""
                p_val = core.get_card_power(c)
                total_deck_power += p_val
                cur_lvl = c.get("level", 1)
                mr = int(c.get("master_rank", 0))
                mr_tag = f" `✦MR.{mr}`" if mr > 0 else ""
                deck_lines.append(
                    f"{badge} `{c['rarity_label']}` **{c['char_name']}** [{c['prefix']}]{lock_tag}\n"
                    f"└ `Lv.{cur_lvl}`{mr_tag} · `⚔️ {p_val:,}`"
                )
            embed.add_field(name=f"🎸 5인 유닛 덱 (총 ⚔️ {total_deck_power:,})", value="\n".join(deck_lines)[:1024], inline=False)
        else:
            embed.add_field(name="🎸 5인 유닛 덱", value="미편성 *(`/설정` ➔ 5인 유닛 덱 편성)*", inline=False)

        live_stats = core.as_dict(profile.get("sekai_live"))
        today_str = core.get_today_str()
        live_daily = int(live_stats.get("daily_count", 0)) if live_stats.get("last_date") == today_str else 0
        live_stamps = int(live_stats.get("stamps", 0))
        live_best = int(live_stats.get("best_score", 0))
        live_clears = int(live_stats.get("rally_clears", 0))
        live_total = int(live_stats.get("total_lives", 0))
        pr_info = core.get_player_rank_info(u_gacha.get("player_rank_exp", 0))
        if live_total > 0:
            embed.add_field(
                name=f"⚔️ 세카이 라이브 · 🎖️ Rank {pr_info['rank']}",
                value=(
                    f"최고 **`{live_best:,}점`** · 🎫 스탬프 `{live_stamps}/7` *(완주 `{live_clears}회`)* · 오늘 `{live_daily}/3회`\n"
                    f"└ 전체 플레이어 랭크 **`Rank {pr_info['rank']}`** (`{pr_info['cur_exp']:,} / {pr_info['need_exp']:,} EXP`)"
                ),
                inline=False
            )
        else:
            embed.add_field(
                name=f"⚔️ 세카이 라이브 · 🎖️ Rank {pr_info['rank']}",
                value="미플레이 *(`/설정` ➔ 세카이 라이브)*",
                inline=False
            )

        rep_card = None
        if oshi_cards:
            # 1순위: 오시가 본인의 원래 카드 의상을 착용 중인 경우, 그 착용 의상의 카드 일러스트 우선 연동!
            if oshi_char_id:
                oshi_cos = core.get_user_equipped_costume(interaction.guild_id or 0, target_user.id, oshi_char_id)
                cos_card_id = oshi_cos.get("card_id")
                cos_origin_id = oshi_cos.get("origin_char_id")
                if cos_card_id and cos_card_id > 0 and cos_origin_id == oshi_char_id:
                    matched_cos_card = next((c for c in oshi_cards if c.get("id") == cos_card_id), None)
                    if matched_cos_card:
                        rep_card = matched_cos_card
                        cos_name_tag = f" · 👗착용 의상: [{oshi_cos.get('name', '의상')}]"
                        embed.set_footer(text=f"대표 일러스트: [{rep_card.get('limit_label', '통상')}] {rep_card['rarity_label']} [{rep_card['prefix']}] {rep_card['char_name']}{cos_name_tag}")

            # 2순위: 다른 캐릭터의 의상을 착용했거나 기본 의상인 경우 -> 오시 본인의 최고 등급 카드
            if not rep_card:
                oshi_cards.sort(key=lambda x: (-x.get("star_num", 1), -int(x.get("is_limited", False)), -x.get("count", 1), -x.get("id", 0)))
                rep_card = oshi_cards[0]
                cos_name_tag = ""
                if oshi_char_id:
                    oshi_cos = core.get_user_equipped_costume(interaction.guild_id or 0, target_user.id, oshi_char_id)
                    if oshi_cos.get("card_prefix") and oshi_cos.get("card_prefix") != "기본":
                        origin_name = oshi_cos.get("char_name", "")
                        origin_note = f" (원작: {origin_name})" if oshi_cos.get("origin_char_id") != oshi_char_id else ""
                        cos_name_tag = f" · 👗착용 의상: [{oshi_cos.get('name')}]{origin_note}"
                embed.set_footer(text=f"대표 일러스트: [{rep_card.get('limit_label', '통상')}] {rep_card['rarity_label']} [{rep_card['prefix']}] {rep_card['char_name']}{cos_name_tag}")
        elif valid_deck_cards:
            rep_card = valid_deck_cards[0]
            embed.set_footer(text=f"대표 일러스트 (덱 리더): [{rep_card.get('limit_label', '통상')}] {rep_card['rarity_label']} [{rep_card['prefix']}] {rep_card['char_name']}")

        if rep_card:
            prof_view = SimpleCardIllustToggleView(rep_card, initial_mode="normal") if core.can_card_awaken(rep_card) else None
            img_bytes, filename = await asyncio.to_thread(core.fetch_proseka_card_image_bytes, rep_card, "normal")
            send_kw = {"embed": embed}
            if prof_view is not None:
                send_kw["view"] = prof_view
            if img_bytes and filename:
                file = discord.File(io.BytesIO(img_bytes), filename=filename)
                embed.set_image(url=f"attachment://{filename}")
                await interaction.followup.send(file=file, **send_kw)
                return
            else:
                embed.set_image(url=core.get_proseka_card_image_url(rep_card, "normal"))
                await interaction.followup.send(**send_kw)
                return

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="가챠랭킹", description="서버의 수집률/★4 보유 순위 및 단일 10연차 최고 비틱 명예의 전당·픽업 로그를 확인합니다.")
    async def gacha_ranking_cmd(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        guild_id = interaction.guild_id or 0
        hall_of_fame = core.as_dict(core.get_gacha_hall_of_fame(guild_id))
        total_db_cards, stats_list = core.build_proseka_guild_ranking_stats(data, guild_id)

        has_hof = bool(hall_of_fame.get("top_records") or hall_of_fame.get("recent_pickup_logs") or hall_of_fame.get("recent_high_logs"))
        if not stats_list and not has_hof:
            await interaction.followup.send("📭 아직 이 서버에서 가챠를 진행한 유저가 없습니다. `/설정` (`🎮 미니게임` ➔ `🎰 프로세카 뽑기`)로 첫 주인공이 되어보세요!")
            return

        guild_name = interaction.guild.name if interaction.guild else "서버"
        view = GachaRankingView(interaction.user, guild_name, total_db_cards, stats_list, hall_of_fame)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @app_commands.command(name="픽업설정", description="[봇주인 전용] 현재 한섭 이벤트에 맞춰 픽업을 자동 연동하거나 유닛/캐릭터/배너/한정 여부를 직접 설정합니다.")
    @app_commands.autocomplete(캐릭터=core.proseka_char_autocomplete)
    @app_commands.describe(
        모드="픽업 설정 방식 (현재 한섭 이벤트 자동 맞춤 / 수동 지정 / 픽업 해제)",
        유닛="[수동] 픽업 확률을 높일 유닛 선택 ('해제' 선택 시 유닛 픽업 해제)",
        캐릭터="[수동] 픽업 확률을 높일 캐릭터 선택 ('해제' 선택 시 캐릭터 픽업 해제)",
        한정포함="[수동] 기간한정/페스한정/생일한정 카드를 뽑기 풀에 포함할지 여부 (기본: True)",
        배너="[전역 배너] 전체 유저 기본 프로세카 가챠 배너 변경 (일반 / 페스티벌 ★4 2배 / 생일 스페셜)"
    )
    @app_commands.choices(
        모드=[
            app_commands.Choice(name="🎯 현재 한섭 이벤트에 자동 맞추기 (실시간 DB)", value="event_sync"),
            app_commands.Choice(name="🎛️ 수동 설정 (유닛 / 캐릭터 직접 선택)", value="manual"),
            app_commands.Choice(name="🧹 픽업 초기화 (전체 해제)", value="reset"),
        ],
        유닛=[
            app_commands.Choice(name="해제 (유닛 픽업 안 함)", value="NONE"),
            app_commands.Choice(name="Leo/need", value="Leo/need"),
            app_commands.Choice(name="MORE MORE JUMP!", value="MORE MORE JUMP!"),
            app_commands.Choice(name="Vivid BAD SQUAD", value="Vivid BAD SQUAD"),
            app_commands.Choice(name="원더랜즈×쇼타임", value="원더랜즈×쇼타임"),
            app_commands.Choice(name="25시, 나이트 코드에서.", value="25시, 나이트 코드에서."),
            app_commands.Choice(name="버츄얼 싱어", value="버츄얼 싱어")
        ],
        배너=[
            app_commands.Choice(name="🌟 일반 / 현재 픽업 가챠 (★4 3.0%)", value="normal"),
            app_commands.Choice(name="🎊 컬러풀 페스티벌 (★4 2배 · 6.0%!)", value="fes"),
            app_commands.Choice(name="🎂 생일 / 기념일 스페셜 (생일한정 UP!)", value="birthday"),
        ],
    )
    async def set_pickup_cmd(
        self,
        interaction: discord.Interaction,
        모드: app_commands.Choice[str] = None,
        유닛: app_commands.Choice[str] = None,
        캐릭터: str = None,
        한정포함: bool = True,
        배너: app_commands.Choice[str] = None,
    ):
        if not await self.bot.is_bot_owner_user(interaction.user):
            await core.safe_send_response(interaction, content="❌ 이 명령어는 **봇주인(Bot Owner)** 만 사용할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction)
        mode_val = 모드.value if 모드 else None

        if mode_val == "event_sync":
            ok, msg, pickup_obj = await asyncio.to_thread(core.sync_gacha_pickup_to_live_event)
            if not ok:
                await core.safe_send_response(interaction, content=f"❌ {msg}", ephemeral=True)
                return

            if 배너 is not None:
                def _apply_banner_type():
                    with core._DATA_LOCK:
                        d_sync = core.load_data()
                        gp_sync = core.ensure_dict_path(d_sync, "gacha_pickup")
                        gp_sync["banner_type"] = 배너.value
                        core.save_data(d_sync)
                await asyncio.to_thread(_apply_banner_type)
                pickup_obj["banner_type"] = 배너.value

            b_cfg = core.BANNER_CONFIGS.get(core.get_active_proseka_banner(pickup_obj), core.BANNER_CONFIGS["normal"])
            labels = pickup_obj.get("pickup_card_labels") or []
            cards_txt = "\n".join(f"• {lbl}" for lbl in labels[:12]) if labels else f"• 유닛 픽업: `{pickup_obj.get('unit') or '전체 동일'}`"
            embed = discord.Embed(
                title="🎯 [봇주인] 한섭 이벤트 픽업 자동 연동 완료",
                description=f"🏆 **{pickup_obj.get('event_name')}** (`{pickup_obj.get('event_status', '진행 중')}`)",
                color=discord.Color.from_rgb(0, 204, 221),
                timestamp=datetime.datetime.now(core.KST)
            )
            embed.add_field(name="🎰 적용 배너", value=f"`{b_cfg['name']}`", inline=True)
            embed.add_field(name="✨ 한정/페스/생일", value="`포함됨`", inline=True)
            embed.add_field(name=f"🌟 픽업 대상 ({len(labels)}종)", value=cards_txt[:1024], inline=False)
            embed.set_footer(text="뽑기 및 확률표에 등급 내 50% 픽업 집중 배분이 즉시 반영됩니다")
            await core.safe_send_response(interaction, embed=embed)
            return

        data = await asyncio.to_thread(core.load_data)
        if mode_val == "reset":
            reset_obj = copy.deepcopy(core.DEFAULT_CONFIG["gacha_pickup"])
            if 배너 is not None:
                reset_obj["banner_type"] = 배너.value
            data["gacha_pickup"] = reset_obj
            await asyncio.to_thread(core.save_data, data)
            b_cfg = core.BANNER_CONFIGS.get(core.get_active_proseka_banner(reset_obj), core.BANNER_CONFIGS["normal"])
            embed = discord.Embed(
                title="🧹 [봇주인] 프로세카 픽업 설정 초기화 완료",
                description="모든 이벤트·유닛·캐릭터 픽업이 해제되어 전체 카드 동일 확률로 복원되었습니다.",
                color=discord.Color.from_rgb(0, 204, 221),
                timestamp=datetime.datetime.now(core.KST),
            )
            embed.add_field(name="🎰 적용 배너", value=f"`{b_cfg['name']}`", inline=False)
            await core.safe_send_response(interaction, embed=embed)
            return

        if mode_val is None and 배너 is not None and 유닛 is None and 캐릭터 is None:
            gp = core.ensure_dict_path(data, "gacha_pickup")
            gp["banner_type"] = 배너.value
            await asyncio.to_thread(core.save_data, data)
            b_cfg = core.BANNER_CONFIGS.get(배너.value, core.BANNER_CONFIGS["normal"])
            embed = discord.Embed(
                title="🎰 [봇주인] 프로세카 전역 배너 변경 완료",
                description=b_cfg["desc"],
                color=discord.Color.from_rgb(*b_cfg.get("color", (0, 204, 221))),
                timestamp=datetime.datetime.now(core.KST),
            )
            embed.add_field(name="🎰 적용 배너", value=f"`{b_cfg['name']}`", inline=True)
            embed.add_field(name="🎯 유지 중인 픽업", value=f"`{core.truncate_text(core.format_pickup_summary(gp), 80)}`", inline=True)
            embed.set_footer(text="전체 유저의 기본 프로세카 뽑기 및 확률표에 즉시 적용됩니다")
            await core.safe_send_response(interaction, embed=embed)
            return

        prev_banner = core.get_active_proseka_banner(core.as_dict(data.get("gacha_pickup")))
        active_banner = 배너.value if 배너 is not None else prev_banner
        selected_unit = None if (not 유닛 or 유닛.value == "NONE") else 유닛.value
        selected_char = None if (not 캐릭터 or 캐릭터 == "NONE") else 캐릭터

        data["gacha_pickup"] = {
            "unit": selected_unit,
            "character": selected_char,
            "card_ids": [],
            "event_id": None,
            "event_name": None,
            "pickup_card_labels": [],
            "include_limited": 한정포함,
            "banner_type": active_banner,
        }
        await asyncio.to_thread(core.save_data, data)

        b_cfg = core.BANNER_CONFIGS.get(active_banner, core.BANNER_CONFIGS["normal"])
        embed = discord.Embed(
            title="🎯 [봇주인] 프로세카 픽업 설정 완료",
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.add_field(name="🎰 적용 배너", value=f"`{b_cfg['name']}`", inline=True)
        embed.add_field(name="✨ 한정/페스/생일", value=f"`{'포함됨' if 한정포함 else '제외 (통상만)'}`", inline=True)
        embed.add_field(name="🏷️ 픽업 유닛", value=f"`{selected_unit or '미지정 (전체 동일)'}`", inline=True)
        embed.add_field(name="👤 픽업 캐릭터", value=f"`{selected_char or '미지정 (전체 동일)'}`", inline=True)
        embed.set_footer(text="뽑기 및 확률표에 등급 내 50% 픽업 집중 배분이 즉시 반영됩니다")
        await core.safe_send_response(interaction, embed=embed)

    @app_commands.command(name="서버캐릭터초기화", description="[서버 관리자 전용] 현재 디스코드 서버 유저들의 프로세카 캐릭터 보관함을 초기화합니다.")
    @app_commands.default_permissions(administrator=True)
    async def reset_guild_gacha_cmd(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, "❌ 이 명령어는 **서버 관리자**만 사용할 수 있습니다.", ephemeral=True)
            return

        view = GuildGachaResetConfirmView(interaction.guild)
        warn_embed = discord.Embed(
            title="⚠️ 서버 캐릭터 보관함 초기화 확인",
            description=f"**{interaction.guild.name}** 서버의 모든 유저 프로세카 캐릭터 데이터를 초기화할까요?",
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(core.KST),
        )
        warn_embed.add_field(name="🗑️ 초기화 대상", value="현재 서버 유저들의 프로세카 보관함 · 도감 기록", inline=False)
        warn_embed.add_field(name="🛡️ 보존 대상", value="다른 서버 데이터 · D-Day 일정 · 공통 프로필", inline=False)
        await core.safe_send_response(interaction, embed=warn_embed, view=view, ephemeral=True)

    @staticmethod
    def _find_user_card_by_query(u_cards: dict, query_raw: str) -> tuple[str | None, dict | None]:
        if not u_cards or not query_raw:
            return None, None
        q = query_raw.strip()
        if q in u_cards and isinstance(u_cards[q], dict):
            c = u_cards[q]
            return str(c.get("id") if c.get("id") is not None else q), c
        import re
        m_id = re.search(r"(?:id[:\s]*)(\d+)", q, flags=re.IGNORECASE)
        id_cand = m_id.group(1) if m_id else (q if q.isdigit() else None)
        if id_cand and id_cand in u_cards and isinstance(u_cards[id_cand], dict):
            c = u_cards[id_cand]
            return str(c.get("id") if c.get("id") is not None else id_cand), c

        q_low = q.lower()
        for k, c in u_cards.items():
            if not isinstance(c, dict):
                continue
            cid_s = str(c.get("id") if c.get("id") is not None else k)
            if cid_s == q_low or (id_cand and cid_s == id_cand):
                return cid_s, c
        for k, c in u_cards.items():
            if not isinstance(c, dict):
                continue
            cid_s = str(c.get("id") if c.get("id") is not None else k)
            cname = str(c.get("char_name") or "").lower()
            prefix = str(c.get("prefix") or "").lower()
            full_lbl = f"{c.get('rarity_label', '')} [{c.get('prefix', '')}] {c.get('char_name', '')}".lower()
            if q_low in cname or q_low in prefix or q_low in full_lbl:
                return cid_s, c
        return None, None

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
        g_key = str(interaction.guild_id or 0)
        u_key = str(interaction.user.id)
        u_disp = interaction.user.display_name
        mode = 강화단계.value

        def _do_enhance():
            with core._DATA_LOCK:
                data = core.load_data()
                profile = core.ensure_user_profile(data, u_key, u_disp)
                user_crystals = int(profile.get("crystals", 0))
                user_cards_dict = core.safe_get_dict(data, "gacha_users", g_key, u_key, "cards")
                if not user_cards_dict:
                    return "NO_CARDS", None

                _, target = self._find_user_card_by_query(user_cards_dict, 카드선택)
                if not target:
                    return "NOT_FOUND", None

                star_num = target.get("star_num", 3)
                max_lvl = core.get_card_max_level(target)
                cur_lvl = max(1, int(target.get("level", 1)))
                if cur_lvl >= max_lvl:
                    return "ALREADY_MAX", {"target": copy.deepcopy(target), "max_lvl": max_lvl}

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
                    return "NO_CRYSTALS", {"total_cost": total_cost, "user_crystals": user_crystals}

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
                core.save_data(data)
                return "OK", {
                    "target": copy.deepcopy(target),
                    "cur_lvl": cur_lvl,
                    "target_lvl": target_lvl,
                    "max_lvl": max_lvl,
                    "old_power": old_power,
                    "new_power": new_power,
                    "diff_power": diff_power,
                    "total_cost": total_cost,
                    "new_crystals": new_crystals,
                    "max_bonus": max_bonus,
                    "is_max": is_max,
                    "was_awakened": was_awakened,
                }

        status, res = await asyncio.to_thread(_do_enhance)
        if status == "NO_CARDS":
            await interaction.followup.send("❌ 보유한 카드가 없습니다. `/설정` (`🎰 프로세카 뽑기`)에서 먼저 캐릭터를 뽑아주세요!", ephemeral=True)
            return
        if status == "NOT_FOUND":
            await interaction.followup.send(f"❌ 검색어 `{카드선택}`에 해당하는 보유 카드를 찾지 못했습니다. `/설정` (`👤 개인` ➔ `🎒 프로세카 카드 보관함`)에서 보유 카드 목록과 ID를 확인해 주세요.", ephemeral=True)
            return
        if status == "ALREADY_MAX":
            t_card = res["target"]
            await interaction.followup.send(f"ℹ️ **[{t_card.get('prefix')}] {t_card.get('char_name')}** 카드는 이미 **MAX 레벨(Lv.{res['max_lvl']})** 에 도달했습니다!", ephemeral=True)
            return
        if status == "NO_CRYSTALS":
            await interaction.followup.send(
                f"❌ 크리스탈이 부족합니다! (필요: `{res['total_cost']:,}💎` / 보유: `{res['user_crystals']:,}💎`)\n"
                f"`/설정`의 출석체크(`📅 일일 출석체크`)나 중복카드 변환(`💎 중복 카드 변환`)으로 크리스탈을 추가 획득해 보세요.",
                ephemeral=True
            )
            return

        target = res["target"]
        cur_lvl = res["cur_lvl"]
        target_lvl = res["target_lvl"]
        max_lvl = res["max_lvl"]
        old_power = res["old_power"]
        new_power = res["new_power"]
        diff_power = res["diff_power"]
        total_cost = res["total_cost"]
        new_crystals = res["new_crystals"]
        max_bonus = res["max_bonus"]
        is_max = res["is_max"]
        was_awakened = res["was_awakened"]

        embed = discord.Embed(
            title="⚡ 카드 레벨업 완료!",
            description=f"🖼️ **{target.get('rarity_label')} {target.get('char_name')}** [{target.get('prefix')}] · `{target.get('limit_label', '통상')}`",
            color=discord.Color.gold() if is_max else discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.add_field(
            name="📈 레벨",
            value=f"`Lv.{cur_lvl}` ➔ **`Lv.{target_lvl} / {max_lvl}`**",
            inline=True,
        )
        embed.add_field(
            name="⚔️ 종합력",
            value=f"`{old_power:,}` ➔ **`{new_power:,}`**\n└ `+{diff_power:,}`",
            inline=True,
        )
        embed.add_field(
            name="💎 크리스탈",
            value=f"`-{total_cost:,} 💎`\n└ 잔여 `{new_crystals:,} 💎`",
            inline=True,
        )
        milestones = []
        if max_bonus > 0:
            milestones.append(f"🎉 **MAX 레벨 달성 보너스:** `+{max_bonus:,} 💎` 환급!")
        if target.get("awakened") and not was_awakened:
            milestones.append("✨ **특훈(각성) 달성!** 각성 보너스 `+3,000 ⚔️` 활성화!")
        if milestones:
            embed.add_field(name="🌟 달성 보너스", value="\n".join(milestones), inline=False)
        embed.set_thumbnail(url=core.get_proseka_card_image_url(target, "auto"))
        embed.set_footer(text=f"{interaction.user.display_name} • 보관함 및 프로필 카드에 즉시 반영됩니다")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="마이세카이", description="나만의 미니 룸 테마와 세카이 가구를 꾸미고 매일 출석체크 추가 크리스탈 이자(패시브 보너스)를 받습니다.")
    @app_commands.describe(유저="(선택) 다른 유저가 꾸민 마이세카이 미니 룸을 구경합니다.")
    async def my_sekai_cmd(self, interaction: discord.Interaction, 유저: Optional[discord.User] = None):
        await core.safe_defer(interaction)
        target_user = 유저 or interaction.user
        data = await asyncio.to_thread(core.load_data)
        view = MySekaiHubView(interaction.user, target_user, interaction.guild_id or 0, data)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

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
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @app_commands.command(name="마스터랭크", description="보유 카드의 마스터 랭크(0~5)를 한계 돌파하여 종합력을 올리고 MR.2에서 어나더 컬러·한정 헤어를 해금합니다.")
    @app_commands.describe(카드선택="(선택) 바로 선택할 보유 카드를 지정합니다.")
    @app_commands.autocomplete(카드선택=core.owned_card_autocomplete)
    async def master_rank_cmd(self, interaction: discord.Interaction, 카드선택: Optional[str] = None):
        await core.safe_defer(interaction)
        initial_cid = None
        if 카드선택:
            data = await asyncio.to_thread(core.load_data)
            g_key = str(interaction.guild_id or 0)
            u_key = str(interaction.user.id)
            u_cards = core.safe_get_dict(data, "gacha_users", g_key, u_key, "cards")
            initial_cid, _ = self._find_user_card_by_query(u_cards, 카드선택)
        view = MasterRankView(interaction.user, guild_id=interaction.guild_id or 0, initial_card_id=initial_cid)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @app_commands.command(name="라이브", description="편성한 5인 유닛 덱과 3D 의상 시너지로 세카이 라이브를 플레이하고 7일 스탬프 랠리 보상(💎)을 받습니다.")
    @app_commands.describe(곡="(선택) 플레이할 세카이 라이브 곡을 선택합니다.")
    @app_commands.choices(곡=[
        app_commands.Choice(name=f"{s['attr']} {s['title']} ({s['unit']})"[:100], value=s["id"])
        for s in core.PROSEKA_LIVE_SONGS
    ])
    async def sekai_live_cmd(self, interaction: discord.Interaction, 곡: Optional[app_commands.Choice[str]] = None):
        await core.safe_defer(interaction)
        song_id = 곡.value if 곡 else None
        view = SekaiLiveView(interaction.user, guild_id=interaction.guild_id or 0, initial_song_id=song_id)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @app_commands.command(name="천장교환", description="가챠 배지 200개로 원하는 ★4 / 🎀생일 카드를 확정 교환하고 가챠 보너스 게이지를 확인합니다.")
    async def ceiling_exchange_cmd(self, interaction: discord.Interaction):
        if not await ensure_proseka_registered(interaction):
            return
        await core.safe_defer(interaction)
        view = GachaCeilingExchangeView(interaction.user, guild_id=interaction.guild_id or 0)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @app_commands.command(name="셀렉트리스트", description="봇주 지급 특수 티켓 1장으로 원하는 ★4 카드 10장을 골라 1장 확정 10연차를 실행합니다.")
    async def select_list_gacha_cmd(self, interaction: discord.Interaction):
        if not await ensure_proseka_registered(interaction):
            return
        await core.safe_defer(interaction)
        view = SelectListGachaView(interaction.user, guild_id=interaction.guild_id or 0)
        await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)

    @app_commands.command(name="셀렉트티켓지급", description="[봇주인 전용] 특정 유저에게 셀렉트 리스트 가챠 특수 티켓을 지급·회수하거나 관리 패널을 엽니다.")
    @app_commands.describe(
        유저="(선택) 티켓을 지급하거나 회수할 대상 유저 (미입력 시 봇주 관리 제어판 열기)",
        수량="(선택) 지급할 수량 (양수: 지급 / 음수: 회수 / 0: 보유량 확인, 기본: 1)",
        사유="(선택) 지급/회수 사유 메모"
    )
    async def grant_select_ticket_cmd(
        self,
        interaction: discord.Interaction,
        유저: Optional[discord.User] = None,
        수량: int = 1,
        사유: str = "",
    ):
        if not await _is_interaction_bot_owner(interaction, self.bot):
            await core.safe_send_response(
                interaction,
                content="❌ 셀렉트 리스트 특수 티켓 지급은 **봇주인(Bot Owner)** 만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return
        if 유저 is None:
            await core.safe_defer(interaction, ephemeral=True)
            view = OwnerSelectTicketGrantView(interaction.user)
            msg_obj = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
            view.message = msg_obj
            return
        if abs(수량) > 999:
            await core.safe_send_response(interaction, "❌ 수량은 `-999 ~ +999` 사이로 입력해 주세요.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        ok, msg, after_cnt = await asyncio.to_thread(
            core.adjust_user_select_tickets,
            유저.id,
            수량,
            getattr(유저, "display_name", ""),
            interaction.user.id,
            사유,
        )
        action_lbl = "지급 완료" if (ok and 수량 > 0) else ("회수 완료" if (ok and 수량 < 0) else ("보유량 확인" if ok else "처리 실패"))
        embed = discord.Embed(
            title=f"🎟️ [봇주인] 셀렉트 티켓 {action_lbl}",
            color=discord.Color.from_rgb(255, 205, 86) if ok else discord.Color.red(),
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.add_field(name="👤 대상 유저", value=f"{유저.mention}", inline=True)
        embed.add_field(name="🎟️ 처리 결과", value=msg, inline=True)
        if (사유 or "").strip():
            embed.add_field(name="📝 사유", value=f"> {사유.strip()[:100]}", inline=False)
        embed.set_footer(text="받은 티켓은 /셀렉트리스트 또는 /설정 ➔ 특수뽑기에서 즉시 사용할 수 있습니다")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="캐릭터랭크", description="프로세카 26인 캐릭터 랭크(캐랭)와 칭호 깃발을 확인·장착하고 랭크업 보상(💎)을 수령합니다.")
    @app_commands.autocomplete(캐릭터=core.proseka_char_autocomplete)
    @app_commands.describe(캐릭터="(선택) 바로 확인할 프로세카 캐릭터 이름")
    async def character_rank_cmd(self, interaction: discord.Interaction, 캐릭터: Optional[str] = None):
        await core.safe_defer(interaction)
        init_cid = None
        if 캐릭터:
            q = 캐릭터.strip().lower()
            for cid, cinfo in core.CHARACTER_MAP.items():
                if q in cinfo["name"].lower():
                    init_cid = cid
                    break
        view = CharacterRankView(interaction.user, guild_id=interaction.guild_id or 0, initial_char_id=init_cid)
        embed, file_obj = await view.build_embed_and_file()
        if file_obj:
            await interaction.followup.send(embed=embed, file=file_obj, view=view, wait=True)
        else:
            await interaction.followup.send(embed=embed, view=view, wait=True)


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
    def __init__(self, caller: discord.User | None = None, owner: discord.User | None = None, guild_id: int = 0, data: dict | None = None):
        super().__init__(timeout=600)
        self.caller = caller
        self.owner = owner or caller
        self.guild_id = guild_id
        self.data = data if data else core.get_cached_data()
        self.status_notice = ""
        self.illust_stage = "normal"
        self._refresh_components()

    def _refresh_components(self):
        if self.owner:
            caller_id = self.caller.id if self.caller else self.owner.id
            is_owner = (caller_id == self.owner.id)
            profile = core.ensure_user_profile(self.data, self.owner.id, self.owner.display_name)
        else:
            is_owner = True
            profile = {}
        ms = core.ensure_my_sekai(profile)
        cur_theme = ms.get("theme", "default")
        owned_themes = set(ms.get("owned_themes", ["default"]))
        owned_furn = set(ms.get("furniture", []))

        t_opts = []
        for t_key, t_info in core.MY_SEKAI_THEMES.items():
            if t_key == cur_theme:
                status = "✅ 적용중"
            elif t_key in owned_themes:
                status = "보유중"
            else:
                status = f"{t_info['cost']:,}💎"
            t_opts.append(
                discord.SelectOption(
                    label=t_info["name"][:95],
                    value=t_key,
                    description=f"{status} · 출석 이자 +{t_info['bonus']}💎/일"[:100],
                    default=(t_key == cur_theme),
                )
            )
        self.theme_select.options = t_opts[:25]
        self.theme_select.disabled = not is_owner

        f_opts = []
        for f_key, f_info in core.MY_SEKAI_FURNITURE.items():
            has_it = (f_key in owned_furn)
            status = "✅ 배치됨" if has_it else f"{f_info['cost']:,}💎"
            f_opts.append(
                discord.SelectOption(
                    label=f_info["name"][:95],
                    value=f_key,
                    description=f"{status} · 출석 이자 +{f_info['bonus']}💎/일"[:100],
                )
            )
        self.furniture_select.options = f_opts[:25]
        self.furniture_select.disabled = not is_owner
        self.edit_greeting_btn.disabled = not is_owner

    def build_embed(self) -> discord.Embed:
        self._refresh_components()
        if not self.owner:
            return discord.Embed(title="🏠 마이세카이 미니 룸", description="유저 정보를 불러올 수 없습니다.", color=discord.Color.from_rgb(0, 204, 221))
        u_key = str(self.owner.id)
        g_key = str(self.guild_id or 0)
        profile = core.ensure_user_profile(self.data, u_key, self.owner.display_name)
        ms = core.ensure_my_sekai(profile)

        crystals = profile.get("crystals", 0)
        oshi_name = profile.get("oshi") or "미설정"
        cur_theme_key = ms.get("theme", "default")
        theme_info = core.MY_SEKAI_THEMES.get(cur_theme_key, core.MY_SEKAI_THEMES["default"])
        owned_furn = ms.get("furniture", [])
        daily_bonus = core.get_my_sekai_daily_bonus(profile)

        total_furn = len(core.MY_SEKAI_FURNITURE)
        cnt_furn = len(owned_furn)
        furn_pct = int(cnt_furn / max(1, total_furn) * 100)
        prog_bar = core.format_progress_bar(cnt_furn, max(1, total_furn), slots=10)

        desc_lines = [f"> 💬 *\"{ms.get('greeting', '환영합니다!')}\"*"]
        if self.status_notice:
            desc_lines.append(f"\n📢 {self.status_notice}")

        embed = discord.Embed(
            title=f"🏠 {self.owner.display_name}님의 마이세카이 미니 룸",
            description="\n".join(desc_lines),
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_thumbnail(url=self.owner.display_avatar.url)
        embed.add_field(
            name="🎨 적용 배경 테마",
            value=f"**{theme_info['name']}** (`+{theme_info['bonus']}💎/일`)\n└ *{theme_info['desc']}*",
            inline=False,
        )

        if owned_furn:
            room_icons = " ".join(core.MY_SEKAI_FURNITURE[f]["emoji"] for f in owned_furn if f in core.MY_SEKAI_FURNITURE)
            showcase_val = f"🪟 {room_icons}\n{prog_bar} **`{cnt_furn}/{total_furn}`** (`{furn_pct}%`)"
            furn_lines = [
                f"• {core.MY_SEKAI_FURNITURE[f]['name']} (`+{core.MY_SEKAI_FURNITURE[f]['bonus']}💎/일`)"
                for f in owned_furn if f in core.MY_SEKAI_FURNITURE
            ]
            furn_list_str = "\n".join(furn_lines)
        else:
            showcase_val = f"*아직 배치된 가구가 없습니다 — 아래 드롭다운에서 첫 가구를 들여놓아 보세요!*\n{prog_bar} **`0/{total_furn}`** (`0%`)"
            furn_list_str = "*배치된 가구 없음*"

        embed.add_field(name=f"🛋️ 가구 진열장 ({cnt_furn}/{total_furn})", value=showcase_val, inline=False)
        embed.add_field(
            name="💰 일일 출석 이자",
            value=f"기본 `100 💎` + 보너스 **`+{daily_bonus} 💎`**\n└ 매일 총 **`{100 + daily_bonus:,} 💎`**",
            inline=True
        )
        embed.add_field(
            name="💎 보유 자산 & 오시",
            value=f"보유 **`{crystals:,} 💎`** · 💖 `{oshi_name}`\n└ 테마 `{len(ms.get('owned_themes', ['default']))}/{len(core.MY_SEKAI_THEMES)}종`",
            inline=True
        )
        embed.add_field(
            name=f"📦 배치된 가구 ({cnt_furn}개)",
            value=furn_list_str[:1024],
            inline=False
        )

        # 오시 카드가 있다면 룸 대표 액자로 썸네일/이미지 연동
        user_cards_dict = core.safe_get_dict(self.data, "gacha_users", g_key, u_key, "cards")
        oshi_raw = profile.get("oshi")
        can_train_oshi = False
        if oshi_raw and user_cards_dict:
            oshi_cards = [c for c in user_cards_dict.values() if isinstance(c, dict) and c.get("char_name") == oshi_raw]
            if oshi_cards:
                oshi_cards.sort(key=lambda x: (-x.get("star_num", 1), -int(x.get("is_limited", False))))
                top_oshi = oshi_cards[0]
                can_train_oshi = core.can_card_awaken(top_oshi)
                eff_stage = "after_training" if (self.illust_stage == "after_training" and can_train_oshi) else "normal"
                embed.set_image(url=core.get_proseka_card_image_url(top_oshi, eff_stage))

        self.btn_stage_normal.disabled = (not can_train_oshi) or (self.illust_stage == "normal")
        self.btn_stage_trained.disabled = (not can_train_oshi) or (self.illust_stage == "after_training")
        embed.set_footer(text="테마·가구를 수집할수록 매일 출석체크 크리스탈 이자가 영구 증가합니다")
        return embed

    @discord.ui.select(
        placeholder="🎨 배경 테마 변경 또는 신규 테마 구매...",
        options=[discord.SelectOption(label="테마 불러오는 중...", value="default")],
        row=0,
    )
    async def theme_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not self.owner:
            self.owner = interaction.user
            self.caller = interaction.user
        if interaction.user.id != self.owner.id:
            await core.safe_send_response(interaction, "❌ 본인의 마이세카이만 꾸밀 수 있습니다. `/설정` (`👤 개인` ➔ `🏠 마이세카이 룸`)에서 열어보세요!", ephemeral=True)
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
        owned_themes = ms.get("owned_themes")
        if not isinstance(owned_themes, list):
            owned_themes = ["default"]
            ms["owned_themes"] = owned_themes

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

    @discord.ui.select(
        placeholder="🛋️ 세카이 가구·소품 구매 및 배치하기...",
        options=[discord.SelectOption(label="가구 불러오는 중...", value="NONE")],
        row=1,
    )
    async def furniture_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not self.owner:
            self.owner = interaction.user
            self.caller = interaction.user
        if interaction.user.id != self.owner.id:
            await core.safe_send_response(interaction, "❌ 본인의 마이세카이만 꾸밀 수 있습니다. `/설정` (`👤 개인` ➔ `🏠 마이세카이 룸`)에서 열어보세요!", ephemeral=True)
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
        furn_list = ms.get("furniture")
        if not isinstance(furn_list, list):
            furn_list = []
            ms["furniture"] = furn_list

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

    @discord.ui.button(label="🌸 특훈 전", style=discord.ButtonStyle.secondary, row=2)
    async def btn_stage_normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.illust_stage = "normal"
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="✨ 특훈 후", style=discord.ButtonStyle.primary, row=2)
    async def btn_stage_trained(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.illust_stage = "after_training"
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🪧 방 한줄 소개글 변경", style=discord.ButtonStyle.primary, row=2)
    async def edit_greeting_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.owner:
            self.owner = interaction.user
            self.caller = interaction.user
        if interaction.user.id != self.owner.id:
            await core.safe_send_response(interaction, "❌ 본인의 마이세카이 소개글만 수정할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(MySekaiGreetingModal(self))

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=2)
    async def refresh_room_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.owner:
            self.owner = interaction.user
            self.caller = interaction.user
        await core.safe_defer(interaction)
        self.data = await asyncio.to_thread(core.load_data)
        self.status_notice = ""
        await interaction.edit_original_response(embed=self.build_embed(), view=self)


async def setup(bot):
    await bot.add_cog(GachaCog(bot))
