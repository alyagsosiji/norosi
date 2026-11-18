"""
economy_core.py - 통합 경제 & 커스터마이징 엔진
1. 칭호(Titles) 상점 & 업적 기반 배지(Badges) 자동 해금/평가
2. 크리스탈 송금 & 세금(5%, 일일 상한 5,000💎) 원자적 처리
3. 주간 로또 복권(1~20 중 4개 추첨, 이월 잭팟, 자동 정산/지급)
4. 4대 게임 통합 고화질 프로필 카드 PNG 생성기 (프로세카·원신·스타레일·낚시/생활)
5. 서버/전역 통합 자산 랭킹 집계
"""

from __future__ import annotations

import copy
import datetime
import io
import random
import uuid
from typing import Any, Dict, List, Optional, Tuple

try:
    import aiohttp
except Exception:
    aiohttp = None

import core
import fishing_core
import genshin_core
import hsr_core
import life_core

try:
    from PIL import Image, ImageDraw
except Exception:
    Image = None
    ImageDraw = None


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        if val is None or isinstance(val, bool):
            return default
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or isinstance(val, bool):
            return float(default)
        return float(val)
    except (TypeError, ValueError):
        return default


# ==========================================
# 1. 칭호(Titles) & 배지(Badges) 카탈로그
# ==========================================
TITLES: Dict[str, Dict[str, Any]] = {
    "newbie": {
        "id": "newbie",
        "name": "새싹 여행자",
        "tag": "[새싹 여행자]",
        "emoji": "🌱",
        "price": 0,
        "unlock_hint": "기본 지급 칭호",
        "rgb": (110, 231, 183),
    },
    "collector_sekai": {
        "id": "collector_sekai",
        "name": "세카이 연주자",
        "tag": "[세카이 연주자]",
        "emoji": "🎶",
        "price": 400,
        "unlock_hint": "프로세카 카드 15종 수집 또는 400💎 구매",
        "rgb": (56, 189, 248),
    },
    "traveler_teyvat": {
        "id": "traveler_teyvat",
        "name": "티바트의 별",
        "tag": "[티바트의 별]",
        "emoji": "🌠",
        "price": 500,
        "unlock_hint": "원신 기원 40회 이상 또는 500💎 구매",
        "rgb": (250, 204, 21),
    },
    "trailblazer": {
        "id": "trailblazer",
        "name": "은하열차 개척자",
        "tag": "[은하열차 개척자]",
        "emoji": "🚄",
        "price": 500,
        "unlock_hint": "스타레일 워프 40회 이상 또는 500💎 구매",
        "rgb": (167, 139, 250),
    },
    "fisher_king": {
        "id": "fisher_king",
        "name": "대해의 낚시왕",
        "tag": "[대해의 낚시왕]",
        "emoji": "🎣",
        "price": 600,
        "unlock_hint": "낚시 Lv.5 또는 도감 20종 달성 또는 600💎 구매",
        "rgb": (34, 211, 238),
    },
    "farmer_master": {
        "id": "farmer_master",
        "name": "만능 자급자족 달인",
        "tag": "[자급자족 달인]",
        "emoji": "🌾",
        "price": 450,
        "unlock_hint": "생활 농장 Lv.3 또는 펫 Lv.4 달성 또는 450💎 구매",
        "rgb": (132, 204, 22),
    },
    "attendance_guard": {
        "id": "attendance_guard",
        "name": "성실한 개근왕",
        "tag": "[성실한 개근왕]",
        "emoji": "📅",
        "price": 500,
        "unlock_hint": "누적 출석 14일 달성 또는 500💎 구매",
        "rgb": (45, 212, 191),
    },
    "jackpot_dreamer": {
        "id": "jackpot_dreamer",
        "name": "행운의 복권왕",
        "tag": "[행운의 복권왕]",
        "emoji": "🎟️",
        "price": 800,
        "unlock_hint": "주간 복권 상위 당첨 또는 800💎 구매",
        "rgb": (251, 146, 60),
    },
    "wealth_tycoon": {
        "id": "wealth_tycoon",
        "name": "세카이의 거부",
        "tag": "[세카이의 거부]",
        "emoji": "💎",
        "price": 1500,
        "unlock_hint": "보유 크리스탈 10,000💎 이상 또는 1,500💎 구매",
        "rgb": (244, 114, 182),
    },
    "nightcord_vip": {
        "id": "nightcord_vip",
        "name": "밤 25시의 별빛",
        "tag": "[밤 25시의 별빛]",
        "emoji": "🌙",
        "price": 2500,
        "unlock_hint": "상점 전용 프리미엄 칭호 (2,500💎)",
        "rgb": (192, 132, 252),
    },
}

BADGE_CATALOG: List[Dict[str, str]] = [
    {"id": "att_7", "emoji": "🔥", "name": "출석 개근(7일+)"},
    {"id": "sekai_star4", "emoji": "⭐", "name": "세카이 ★4 컬렉터"},
    {"id": "genshin_5star", "emoji": "🌠", "name": "티바트 ★5 인연"},
    {"id": "hsr_5star", "emoji": "🚄", "name": "은하 ★5 개척"},
    {"id": "fisher_dex", "emoji": "🐠", "name": "어종 탐색가(15종+)"},
    {"id": "life_pet", "emoji": "🐾", "name": "펫 & 셰프"},
    {"id": "rich_vip", "emoji": "💎", "name": "크리스탈 부호(5,000+)"},
]


def get_equipped_title_info(profile: dict) -> Dict[str, Any]:
    tid = str(profile.get("equipped_title") or "newbie")
    return TITLES.get(tid, TITLES["newbie"])


# ==========================================
# 유저 통합 통계 수집 & 칭호/배지 동기화
# ==========================================
def collect_user_unified_stats(
    data: dict,
    guild_id: int | str,
    user_id: int | str,
    user_name: str = "",
) -> Dict[str, Any]:
    g_key = str(guild_id or 0)
    u_key = str(user_id)
    prof = core.ensure_user_profile(data, u_key, user_name)

    crystals = max(0, _safe_int(prof.get("crystals"), 0))
    att = core.as_dict(prof.get("attendance"))
    att_total = _safe_int(att.get("total_days"), 0)
    att_streak = _safe_int(att.get("streak"), 0)
    att_max_streak = _safe_int(att.get("max_streak"), 0)

    # 1. 프로세카 (카드/덱/오시)
    g_user = core.safe_get_dict(data, "gacha_users", g_key, u_key)
    cards_map = core.as_dict(g_user.get("cards"))
    sekai_unique = len(cards_map)
    sekai_star4 = 0
    for c_obj in cards_map.values():
        if isinstance(c_obj, dict) and _safe_int(c_obj.get("star_num"), 0) >= 4:
            sekai_star4 += 1
    deck_ids = [str(cid) for cid in (prof.get("deck") or []) if cid is not None]
    deck_power = 0
    for cid in deck_ids[:5]:
        c_obj = cards_map.get(cid)
        if isinstance(c_obj, dict):
            deck_power += core.get_card_power(c_obj)
    oshi = prof.get("oshi") or "미설정"

    # 2. 원신 (기원/★5/최고 성유물)
    gen_user = core.safe_get_dict(data, "genshin_users", g_key, u_key)
    gen_pulls = _safe_int(gen_user.get("total_pulls"), 0)
    gen_items = core.as_dict(gen_user.get("items"))
    gen_5star = sum(1 for it in gen_items.values() if isinstance(it, dict) and _safe_int(it.get("rarity", it.get("rank")), 0) >= 5)
    gen_arts = [a for a in core.coerce_list_like(gen_user.get("artifacts")) if isinstance(a, dict)]
    gen_arts.extend(it for it in gen_items.values() if isinstance(it, dict) and it.get("kind") == "artifact")
    gen_best_art = None
    best_art_tuple = (-1.0, -1.0, "-")
    for art in gen_arts:
        cv, rv, grade = genshin_core.compute_genshin_artifact_score(art)
        if (rv, cv) > (best_art_tuple[1], best_art_tuple[0]):
            best_art_tuple = (cv, rv, grade)
            gen_best_art = {
                "name": art.get("name") or art.get("set_name") or "성유물",
                "cv": round(cv, 1),
                "rv": round(rv, 1),
                "grade": str(grade).split(" ")[0],
            }

    # 3. 스타레일 (워프/★5/최고 유물)
    hsr_user = core.safe_get_dict(data, "hsr_users", g_key, u_key)
    hsr_pulls = _safe_int(hsr_user.get("total_pulls"), 0)
    hsr_items = core.as_dict(hsr_user.get("items"))
    hsr_5star = sum(1 for it in hsr_items.values() if isinstance(it, dict) and _safe_int(it.get("rarity", it.get("rank")), 0) >= 5)
    hsr_rels = [r for r in core.coerce_list_like(hsr_user.get("relics")) if isinstance(r, dict)]
    hsr_rels.extend(it for it in hsr_items.values() if isinstance(it, dict) and it.get("kind") == "relic")
    hsr_best_rel = None
    best_rel_tuple = (-1.0, -1.0, "-")
    for rel in hsr_rels:
        cv, rv, grade = hsr_core.compute_hsr_relic_score(rel)
        if (rv, cv) > (best_rel_tuple[1], best_rel_tuple[0]):
            best_rel_tuple = (cv, rv, grade)
            hsr_best_rel = {
                "name": rel.get("name") or rel.get("set_name") or "유물",
                "cv": round(cv, 1),
                "rv": round(rv, 1),
                "grade": str(grade).split(" ")[0],
            }

    # 4. 낚시 & 생활 라이프
    fish_user = core.safe_get_dict(data, "fishing_users", g_key, u_key)
    fish_gold = _safe_int(fish_user.get("gold"), 0)
    fish_lvl = max(1, _safe_int(fish_user.get("level"), 1))
    fish_catches = _safe_int(fish_user.get("total_catches"), 0)
    fish_pd = core.as_dict(fish_user.get("pokedex"))
    fish_dex_cnt = len(fish_pd)
    best_fish_name = "기록 없음"
    best_fish_cm = 0.0
    for fid, pd_rec in fish_pd.items():
        if isinstance(pd_rec, dict):
            mcm = _safe_float(pd_rec.get("max_cm"), 0.0)
            if mcm > best_fish_cm:
                best_fish_cm = mcm
                sp = fishing_core.FISH_BY_ID.get(fid)
                best_fish_name = sp["name"] if sp else fid
    rod = fishing_core.RODS.get(fish_user.get("rod_id", "bamboo"), fishing_core.RODS["bamboo"])
    net = fishing_core.NETS.get(fish_user.get("net_id"))

    life_user = core.safe_get_dict(data, "life_users", g_key, u_key)
    farm_lvl = max(1, _safe_int(life_user.get("farm_level"), 1))
    pets_map = core.as_dict(life_user.get("pets"))
    eq_pet_id = life_user.get("equipped_pet")
    pet_label = "미보유"
    pet_max_lvl = 0
    for pid, p_obj in pets_map.items():
        if isinstance(p_obj, dict):
            pet_max_lvl = max(pet_max_lvl, _safe_int(p_obj.get("level"), 1))
    if eq_pet_id and eq_pet_id in life_core.PETS and isinstance(pets_map.get(eq_pet_id), dict):
        pm = life_core.PETS[eq_pet_id]
        pet_label = f"{pm['name']} Lv.{pets_map[eq_pet_id].get('level', 1)}"
    gf = core.safe_get_dict(data, "guild_farms", g_key)
    gf_lvl = _safe_int(gf.get("level"), 1) if gf else 0

    # 업적 칭호 자동 해금 검사
    owned_titles = prof.setdefault("owned_titles", ["newbie"])
    auto_unlock_checks = {
        "collector_sekai": sekai_unique >= 15,
        "traveler_teyvat": gen_pulls >= 40,
        "trailblazer": hsr_pulls >= 40,
        "fisher_king": fish_lvl >= 5 or fish_dex_cnt >= 20,
        "farmer_master": farm_lvl >= 3 or pet_max_lvl >= 4,
        "attendance_guard": att_total >= 14 or att_max_streak >= 14,
        "wealth_tycoon": crystals >= 10000,
    }
    newly_unlocked_titles: List[str] = []
    for tid, cond in auto_unlock_checks.items():
        if cond and tid not in owned_titles:
            owned_titles.append(tid)
            newly_unlocked_titles.append(tid)

    # 배지 평가
    badges: List[Dict[str, str]] = []
    if att_total >= 7 or att_max_streak >= 7:
        badges.append(BADGE_CATALOG[0])
    if sekai_star4 >= 1:
        badges.append(BADGE_CATALOG[1])
    if gen_5star >= 1:
        badges.append(BADGE_CATALOG[2])
    if hsr_5star >= 1:
        badges.append(BADGE_CATALOG[3])
    if fish_dex_cnt >= 15:
        badges.append(BADGE_CATALOG[4])
    if len(pets_map) >= 1 or _safe_int(life_user.get("total_cooked"), 0) >= 1:
        badges.append(BADGE_CATALOG[5])
    if crystals >= 5000:
        badges.append(BADGE_CATALOG[6])

    title_meta = get_equipped_title_info(prof)
    return {
        "user_id": u_key,
        "user_name": user_name or prof.get("attendance", {}).get("user_name") or f"User({u_key[:4]})",
        "crystals": crystals,
        "fish_gold": fish_gold,
        "title": title_meta,
        "owned_titles": list(owned_titles),
        "newly_unlocked_titles": newly_unlocked_titles,
        "badges": badges,
        "att_total": att_total,
        "att_streak": att_streak,
        "att_max_streak": att_max_streak,
        "sekai": {
            "oshi": oshi,
            "unique_cards": sekai_unique,
            "star4_count": sekai_star4,
            "deck_power": deck_power,
        },
        "genshin": {
            "total_pulls": gen_pulls,
            "star5_count": gen_5star,
            "best_art": gen_best_art,
        },
        "hsr": {
            "total_pulls": hsr_pulls,
            "star5_count": hsr_5star,
            "best_relic": hsr_best_rel,
        },
        "fishing_life": {
            "level": fish_lvl,
            "catches": fish_catches,
            "dex_owned": fish_dex_cnt,
            "dex_total": len(fishing_core.FISH_SPECIES_DB),
            "best_fish_name": best_fish_name,
            "best_fish_cm": best_fish_cm,
            "rod_name": rod["name"],
            "net_name": net["name"] if net else "미장착",
            "farm_level": farm_lvl,
            "pet_label": pet_label,
            "guild_farm_level": gf_lvl,
        },
    }


def get_title_shop_state(guild_id: int | str, user_id: int | str, user_name: str = "") -> Dict[str, Any]:
    with core._DATA_LOCK:
        data = core.load_data()
        stats = collect_user_unified_stats(data, guild_id, user_id, user_name)
        if stats["newly_unlocked_titles"]:
            core.save_data(data)
        return stats


def buy_or_equip_title(
    guild_id: int | str,
    user_id: int | str,
    title_id: str,
    user_name: str = "",
) -> Tuple[bool, str]:
    tmeta = TITLES.get(title_id)
    if not tmeta:
        return False, "❌ 존재하지 않는 칭호입니다."

    with core._DATA_LOCK:
        data = core.load_data()
        prof = core.ensure_user_profile(data, str(user_id), user_name)
        collect_user_unified_stats(data, guild_id, user_id, user_name)
        owned = prof.setdefault("owned_titles", ["newbie"])

        if title_id in owned:
            prof["equipped_title"] = title_id
            core.save_data(data)
            return True, f"🏷️ {tmeta['emoji']} **`{tmeta['tag']}`** 칭호를 장착했습니다!"

        price = int(tmeta["price"])
        have = max(0, _safe_int(prof.get("crystals"), 0))
        if have < price:
            return False, f"❌ 크리스탈이 부족합니다! (필요: `{price:,}💎` / 보유: `{have:,}💎` · 해금 조건: *{tmeta['unlock_hint']}*)"

        prof["crystals"] = have - price
        owned.append(title_id)
        prof["equipped_title"] = title_id
        core.save_data(data)
        return True, f"🎉 {tmeta['emoji']} **`{tmeta['tag']}`** 칭호 구매 및 장착 완료! (`-{price:,}💎` · 남은 크리스탈: `{prof['crystals']:,}💎`)"


# ==========================================
# 2. 크리스탈 송금 & 세금 (5% 세율, 일일 한도 5,000💎)
# ==========================================
TRANSFER_TAX_RATE: float = 0.05
TRANSFER_MIN_AMOUNT: int = 10
TRANSFER_DAILY_LIMIT: int = 5000


def transfer_crystals(
    sender_id: int | str,
    sender_name: str,
    receiver_id: int | str,
    receiver_name: str,
    amount: int,
    receiver_is_bot: bool = False,
) -> Tuple[bool, str, Dict[str, Any]]:
    if receiver_is_bot:
        return False, "❌ 봇 계정에게는 크리스탈을 송금할 수 없습니다.", {}
    s_key = str(sender_id)
    r_key = str(receiver_id)
    if s_key == r_key:
        return False, "❌ 자기 자신에게는 크리스탈을 송금할 수 없습니다.", {}
    try:
        amt = int(amount)
    except (TypeError, ValueError):
        return False, "❌ 송금 금액은 정수로 입력해 주세요.", {}
    if amt < TRANSFER_MIN_AMOUNT:
        return False, f"❌ 최소 송금 금액은 **`{TRANSFER_MIN_AMOUNT:,}💎`** 이상입니다.", {}
    if amt > TRANSFER_DAILY_LIMIT:
        return False, f"❌ 1회 및 1일 최대 송금 한도는 **`{TRANSFER_DAILY_LIMIT:,}💎`**입니다.", {}

    today = core.get_today_str()
    with core._DATA_LOCK:
        data = core.load_data()
        s_prof = core.ensure_user_profile(data, s_key, sender_name)
        r_prof = core.ensure_user_profile(data, r_key, receiver_name)

        s_log = s_prof.setdefault("transfer_log", {"date": today, "sent_today": 0, "received_today": 0})
        if s_log.get("date") != today:
            s_log["date"] = today
            s_log["sent_today"] = 0
            s_log["received_today"] = 0

        r_log = r_prof.setdefault("transfer_log", {"date": today, "sent_today": 0, "received_today": 0})
        if r_log.get("date") != today:
            r_log["date"] = today
            r_log["sent_today"] = 0
            r_log["received_today"] = 0

        sent_today = _safe_int(s_log.get("sent_today"), 0)
        if sent_today + amt > TRANSFER_DAILY_LIMIT:
            rem_limit = max(0, TRANSFER_DAILY_LIMIT - sent_today)
            return False, f"❌ 일일 송금 한도(`{TRANSFER_DAILY_LIMIT:,}💎`)를 초과합니다! (오늘 남은 한도: `{rem_limit:,}💎`)", {}

        have = max(0, _safe_int(s_prof.get("crystals"), 0))
        if have < amt:
            return False, f"❌ 보유 크리스탈이 부족합니다! (보유: `{have:,}💎` / 요청: `{amt:,}💎`)", {}

        tax = max(1, int(round(amt * TRANSFER_TAX_RATE)))
        net_amount = amt - tax
        if net_amount <= 0:
            return False, "❌ 세금 차감 후 수령액이 0 이하이므로 송금할 수 없습니다.", {}

        s_prof["crystals"] = have - amt
        r_prof["crystals"] = max(0, _safe_int(r_prof.get("crystals"), 0)) + net_amount
        s_log["sent_today"] = sent_today + amt
        r_log["received_today"] = _safe_int(r_log.get("received_today"), 0) + net_amount

        # 세금의 30%는 주간 로또 상금 풀로 적립
        lot_contrib = max(1, int(tax * 0.30))
        lot_state = _ensure_lottery_state(data)
        lot_state["pool"] = max(0, _safe_int(lot_state.get("pool"), 0)) + lot_contrib

        core.save_data(data)
        return (
            True,
            (
                f"💸 **{sender_name}**님이 **{receiver_name}**님께 **`{amt:,}💎`**를 송금했습니다!\n"
                f"• **실제 수령액:** **`+{net_amount:,}💎`** (세금 5%: `{tax:,}💎` · `{lot_contrib:,}💎` 로또 풀 적립)\n"
                f"• **남은 보유량:** `{s_prof['crystals']:,}💎` (오늘 송금: `{s_log['sent_today']:,} / {TRANSFER_DAILY_LIMIT:,}💎`)"
            ),
            {
                "amount": amt,
                "tax": tax,
                "net_amount": net_amount,
                "sender_crystals": s_prof["crystals"],
                "receiver_crystals": r_prof["crystals"],
                "sent_today": s_log["sent_today"],
            },
        )


# ==========================================
# 3. 주간 복권(로또: 1~20 중 4개 추첨)
# ==========================================
LOTTERY_TICKET_PRICE: int = 100
LOTTERY_MAX_TICKETS_PER_ROUND: int = 10
LOTTERY_POOL_MAX_NUM: int = 20
LOTTERY_PICK_COUNT: int = 4

DEFAULT_LOTTERY_STATE: Dict[str, Any] = {
    "round": 1,
    "jackpot": 1000,
    "pool": 0,
    "tickets": [],
    "announce_channels": {},
    "last_draw": None,
    "history": [],
}


def _ensure_lottery_state(data: dict) -> dict:
    lot = data.get("lottery_state")
    if not isinstance(lot, dict):
        lot = copy.deepcopy(core.DEFAULT_CONFIG.get("lottery_state", DEFAULT_LOTTERY_STATE))
        data["lottery_state"] = lot
    else:
        for k, v in DEFAULT_LOTTERY_STATE.items():
            if k not in lot:
                lot[k] = copy.deepcopy(v) if isinstance(v, (dict, list)) else v
    return lot


def _validate_lottery_picks(picks: List[int]) -> Optional[List[int]]:
    if not isinstance(picks, (list, tuple)) or len(picks) != LOTTERY_PICK_COUNT:
        return None
    cleaned = []
    for n in picks:
        try:
            v = int(n)
        except (TypeError, ValueError):
            return None
        if not (1 <= v <= LOTTERY_POOL_MAX_NUM) or v in cleaned:
            return None
        cleaned.append(v)
    return sorted(cleaned)


def get_lottery_overview(user_id: int | str) -> Dict[str, Any]:
    data = core.get_cached_data_ro()
    lot = core.as_dict(data.get("lottery_state"))
    u_key = str(user_id)
    prof = core.safe_get_dict(data, "user_profiles", u_key)
    all_tickets = [t for t in (lot.get("tickets") or []) if isinstance(t, dict)]
    my_tickets = [t for t in all_tickets if str(t.get("user_id")) == u_key]
    return {
        "round": max(1, _safe_int(lot.get("round"), 1)),
        "jackpot": max(0, _safe_int(lot.get("jackpot"), 1000)),
        "pool": max(0, _safe_int(lot.get("pool"), 0)),
        "total_tickets": len(all_tickets),
        "my_tickets": copy.deepcopy(my_tickets),
        "last_draw": copy.deepcopy(lot.get("last_draw")),
        "history": copy.deepcopy(lot.get("history") or []),
        "crystals": max(0, _safe_int(prof.get("crystals"), 0)),
    }


def buy_lottery_tickets(
    user_id: int | str,
    user_name: str,
    count: int = 1,
    manual_picks: Optional[List[int]] = None,
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    u_key = str(user_id)
    if manual_picks is not None:
        validated = _validate_lottery_picks(manual_picks)
        if not validated:
            return False, f"❌ 번호는 `1~{LOTTERY_POOL_MAX_NUM}` 사이의 **중복 없는 {LOTTERY_PICK_COUNT}개 숫자**여야 합니다. (예: `3 7 12 19`)", []
        qty = 1
    else:
        qty = max(1, min(LOTTERY_MAX_TICKETS_PER_ROUND, int(count)))
        validated = None

    with core._DATA_LOCK:
        data = core.load_data()
        prof = core.ensure_user_profile(data, u_key, user_name)
        lot = _ensure_lottery_state(data)
        tickets = lot.setdefault("tickets", [])
        cur_user_cnt = sum(1 for t in tickets if isinstance(t, dict) and str(t.get("user_id")) == u_key)

        if cur_user_cnt + qty > LOTTERY_MAX_TICKETS_PER_ROUND:
            rem = max(0, LOTTERY_MAX_TICKETS_PER_ROUND - cur_user_cnt)
            return False, f"⚠️ 한 회차당 최대 **`{LOTTERY_MAX_TICKETS_PER_ROUND}장`**까지 구매할 수 있습니다! (이번 회차 남은 한도: `{rem}장`)", []

        cost = qty * LOTTERY_TICKET_PRICE
        have = max(0, _safe_int(prof.get("crystals"), 0))
        if have < cost:
            return False, f"❌ 크리스탈이 부족합니다! (필요: `{cost:,}💎` / 보유: `{have:,}💎`)", []

        prof["crystals"] = have - cost
        lot["pool"] = max(0, _safe_int(lot.get("pool"), 0)) + int(cost * 0.85)
        now_s = datetime.datetime.now(core.KST).strftime("%Y-%m-%d %H:%M")

        issued: List[Dict[str, Any]] = []
        for _ in range(qty):
            nums = validated if validated is not None else sorted(random.sample(range(1, LOTTERY_POOL_MAX_NUM + 1), LOTTERY_PICK_COUNT))
            entry = {
                "ticket_id": uuid.uuid4().hex[:8],
                "user_id": u_key,
                "user_name": user_name,
                "numbers": nums,
                "bought_at": now_s,
            }
            tickets.append(entry)
            issued.append(entry)

        core.save_data(data)
        num_lines = "\n".join(f"• `#{t['ticket_id']}` ➔ **`{', '.join(str(x) for x in t['numbers'])}`**" for t in issued[:5])
        if len(issued) > 5:
            num_lines += f"\n*(외 {len(issued) - 5}장 더 발급됨)*"
        return (
            True,
            (
                f"🎟️ **제 {lot['round']}회차 주간 로또 복권 {len(issued)}장 구매 완료!** (`-{cost:,}💎`)\n"
                f"{num_lines}\n"
                f"• **현재 총 상금(이월+풀):** **`{lot['jackpot'] + lot['pool']:,}💎`** · 남은 크리스탈: `{prof['crystals']:,}💎`"
            ),
            issued,
        )


def set_lottery_announce_channel(guild_id: int | str, channel_id: Optional[int]) -> None:
    with core._DATA_LOCK:
        data = core.load_data()
        lot = _ensure_lottery_state(data)
        ch_map = core.ensure_dict_path(lot, "announce_channels")
        g_key = str(guild_id or 0)
        if channel_id:
            ch_map[g_key] = int(channel_id)
        else:
            ch_map.pop(g_key, None)
        core.save_data(data)


def execute_lottery_draw(triggered_by: str = "auto", winning_override: Optional[List[int]] = None) -> Dict[str, Any]:
    """
    주간 로또 추첨을 실행하고 당첨자에게 크리스탈을 즉시 지급합니다.
    1등 당첨자가 없으면 잭팟을 다음 회차로 이월합니다.
    """
    with core._DATA_LOCK:
        data = core.load_data()
        lot = _ensure_lottery_state(data)
        round_no = max(1, _safe_int(lot.get("round"), 1))
        jackpot = max(0, _safe_int(lot.get("jackpot"), 1000))
        pool = max(0, _safe_int(lot.get("pool"), 0))
        tickets = [t for t in (lot.get("tickets") or []) if isinstance(t, dict)]

        winning = _validate_lottery_picks(winning_override) if winning_override else None
        if winning is None:
            winning = sorted(random.sample(range(1, LOTTERY_POOL_MAX_NUM + 1), LOTTERY_PICK_COUNT))
        win_set = set(winning)

        rank1: List[Dict[str, Any]] = []
        rank2: List[Dict[str, Any]] = []
        rank3: List[Dict[str, Any]] = []
        for t in tickets:
            nums = set(int(x) for x in (t.get("numbers") or []) if str(x).isdigit())
            matched = len(nums & win_set)
            if matched == 4:
                rank1.append(t)
            elif matched == 3:
                rank2.append(t)
            elif matched == 2:
                rank3.append(t)

        total_prize_pot = jackpot + pool
        r1_each = (max(1000, int(total_prize_pot * 0.70)) // len(rank1)) if rank1 else 0
        r2_each = 500
        r3_each = 120

        payouts: Dict[str, Dict[str, Any]] = {}

        def _credit_winner(t: dict, rank: int, prize: int):
            uid = str(t.get("user_id") or "")
            if not uid or prize <= 0:
                return
            prof = core.ensure_user_profile(data, uid, str(t.get("user_name") or ""))
            prof["crystals"] = max(0, _safe_int(prof.get("crystals"), 0)) + prize
            if rank in (1, 2):
                owned = prof.setdefault("owned_titles", ["newbie"])
                if "jackpot_dreamer" not in owned:
                    owned.append("jackpot_dreamer")
            rec = payouts.setdefault(uid, {
                "user_id": uid,
                "user_name": str(t.get("user_name") or uid),
                "total_prize": 0,
                "best_rank": rank,
            })
            rec["total_prize"] += prize
            rec["best_rank"] = min(rec["best_rank"], rank)

        for t in rank1:
            _credit_winner(t, 1, r1_each)
        for t in rank2:
            _credit_winner(t, 2, r2_each)
        for t in rank3:
            _credit_winner(t, 3, r3_each)

        # 다음 회차 이월 잭팟 계산
        if rank1:
            next_jackpot = 1000
            rolled_over = False
        else:
            next_jackpot = max(1000, jackpot + int(pool * 0.55))
            rolled_over = True

        now_dt = datetime.datetime.now(core.KST)
        draw_record = {
            "round": round_no,
            "drawn_at": now_dt.strftime("%Y-%m-%d %H:%M"),
            "week_key": now_dt.strftime("%Y-W%W"),
            "winning_numbers": winning,
            "ticket_count": len(tickets),
            "total_pot": total_prize_pot,
            "rank1_count": len(rank1),
            "rank1_each": r1_each,
            "rank2_count": len(rank2),
            "rank2_each": r2_each,
            "rank3_count": len(rank3),
            "rank3_each": r3_each,
            "rolled_over": rolled_over,
            "next_jackpot": next_jackpot,
            "winners": sorted(payouts.values(), key=lambda x: -x["total_prize"])[:10],
            "triggered_by": triggered_by,
        }

        lot["round"] = round_no + 1
        lot["jackpot"] = next_jackpot
        lot["pool"] = 0
        lot["tickets"] = []
        lot["last_draw"] = draw_record
        hist = lot.setdefault("history", [])
        hist.insert(0, draw_record)
        lot["history"] = hist[:10]
        announce_channels = copy.deepcopy(lot.get("announce_channels") or {})

        core.save_data(data)
        draw_record["announce_channels"] = announce_channels
        return draw_record


# ==========================================
# 4. 통합 자산/컬렉션 랭킹 집계
# ==========================================
def get_economy_leaderboard(guild_id: int | str) -> Dict[str, Any]:
    data = core.get_cached_data_ro()
    g_key = str(guild_id or 0)
    profiles = core.as_dict(data.get("user_profiles"))
    f_users = core.safe_get_dict(data, "fishing_users", g_key)

    rows: List[Dict[str, Any]] = []
    for uid_s, prof in profiles.items():
        if not isinstance(prof, dict):
            continue
        crystals = max(0, _safe_int(prof.get("crystals"), 0))
        fu = core.as_dict(f_users.get(uid_s))
        fgold = max(0, _safe_int(fu.get("gold"), 0))
        att_days = _safe_int(core.as_dict(prof.get("attendance")).get("total_days"), 0)
        if crystals == 0 and fgold == 0 and att_days == 0:
            continue
        tmeta = get_equipped_title_info(prof)
        uname = core.as_dict(prof.get("attendance")).get("user_name") or fu.get("name") or f"User({uid_s[:4]})"
        net_worth = crystals + int(fgold * 0.25)
        rows.append({
            "user_id": uid_s,
            "user_name": uname,
            "title_tag": tmeta["tag"],
            "title_emoji": tmeta["emoji"],
            "crystals": crystals,
            "fish_gold": fgold,
            "att_days": att_days,
            "net_worth": net_worth,
        })

    by_crystal = sorted(rows, key=lambda x: (-x["crystals"], -x["fish_gold"]))
    by_gold = sorted(rows, key=lambda x: (-x["fish_gold"], -x["crystals"]))
    by_total = sorted(rows, key=lambda x: (-x["net_worth"], -x["crystals"]))
    return {
        "by_crystal": by_crystal,
        "by_gold": by_gold,
        "by_total": by_total,
    }


# ==========================================
# 5. 통합 프로필 카드 고화질 PNG 렌더러
# ==========================================
_PROFILE_BG_CACHE: Dict[Tuple[int, int, int], Any] = {}


def _get_profile_base_canvas(w: int, h: int, t_rgb: Tuple[int, int, int]):
    tr, tg, tb = int(t_rgb[0]), int(t_rgb[1]), int(t_rgb[2])
    key = (tr, tg, tb)
    base = _PROFILE_BG_CACHE.get(key)
    if base is not None:
        return base.copy()
    img = Image.new("RGBA", (w, h), (12, 16, 30, 255))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        ratio = y / h
        r = int(12 + tr * 0.10 * (1.0 - ratio) + 18 * ratio)
        g = int(16 + tg * 0.11 * (1.0 - ratio) + 12 * ratio)
        b = int(32 + tb * 0.18 * (1.0 - ratio) + 34 * ratio)
        draw.line([(0, y), (w, y)], fill=(min(255, r), min(255, g), min(255, b), 255))
    draw.rounded_rectangle([14, 14, w - 14, h - 14], radius=24, outline=(tr, tg, tb, 210), width=4)
    draw.rounded_rectangle([24, 24, w - 24, h - 24], radius=18, outline=(255, 255, 255, 35), width=1)
    draw.rounded_rectangle([38, 36, w - 38, 212], radius=18, fill=(20, 27, 48, 230), outline=(tr, tg, tb, 140), width=2)
    _PROFILE_BG_CACHE[key] = img
    return img.copy()


def render_unified_profile_card_png(
    stats: Dict[str, Any],
    avatar_bytes: Optional[bytes] = None,
) -> Optional[io.BytesIO]:
    """4대 게임·출석·칭호·배지를 한 장에 시각화하는 1080×720 PNG 프로필 카드 생성."""
    if Image is None or ImageDraw is None:
        return None
    img = None
    try:
        w, h = 1080, 720
        t_rgb = stats.get("title", {}).get("rgb", (56, 189, 248))
        tr, tg, tb = t_rgb
        img = _get_profile_base_canvas(w, h, (tr, tg, tb))
        draw = ImageDraw.Draw(img)

        f_name = core._get_grid_font(34, bold=True)
        f_sub = core._get_grid_font(20, bold=True)
        f_card_title = core._get_grid_font(22, bold=True)
        f_body = core._get_grid_font(18, bold=False)
        f_sm = core._get_grid_font(15, bold=False)

        # 아바타 원형 크롭 또는 이니셜 벡터 아바타
        ax, ay, ar = 122, 124, 62
        draw.ellipse([ax - ar - 5, ay - ar - 5, ax + ar + 5, ay + ar + 5], fill=(tr, tg, tb, 220))
        avatar_loaded = False
        if avatar_bytes:
            try:
                with Image.open(io.BytesIO(avatar_bytes)) as raw_av:
                    av_img = raw_av.convert("RGBA").resize((ar * 2, ar * 2), Image.Resampling.LANCZOS)
                mask = Image.new("L", (ar * 2, ar * 2), 0)
                ImageDraw.Draw(mask).ellipse([0, 0, ar * 2, ar * 2], fill=255)
                img.paste(av_img, (ax - ar, ay - ar), mask)
                av_img.close()
                mask.close()
                avatar_loaded = True
            except Exception:
                avatar_loaded = False

        if not avatar_loaded:
            draw.ellipse([ax - ar, ay - ar, ax + ar, ay + ar], fill=(28, 38, 68, 255))
            init_ch = core._sanitize_grid_text(str(stats.get("user_name") or "U")[:1]).upper() or "N"
            if f_name:
                ib = draw.textbbox((0, 0), init_ch, font=f_name)
                iw, ih = ib[2] - ib[0], ib[3] - ib[1]
                draw.text((ax - iw // 2, ay - ih // 2 - 4), init_ch, font=f_name, fill=(255, 255, 255, 255))

        # 유저명 & 칭호 배지
        hx = 212
        title_tag = core._sanitize_grid_text(stats.get("title", {}).get("tag", "[새싹 여행자]"))
        tb_box = draw.textbbox((0, 0), title_tag, font=f_sm) if f_sm else (0, 0, 120, 20)
        pill_w = (tb_box[2] - tb_box[0]) + 24
        draw.rounded_rectangle([hx, 52, hx + pill_w, 82], radius=12, fill=(tr, tg, tb, 235))
        draw.text((hx + 12, 57), title_tag, font=f_sm, fill=(14, 18, 32, 255))

        uname_clean = core._sanitize_grid_text(stats.get("user_name", "유저"))
        if f_name and uname_clean:
            raw_un = uname_clean
            cut_n = len(raw_un)
            while cut_n > 5 and draw.textbbox((0, 0), uname_clean, font=f_name)[2] > 420:
                cut_n -= 1
                uname_clean = raw_un[:cut_n].rstrip() + "..."
        draw.text((hx, 92), uname_clean, font=f_name, fill=(255, 255, 255, 255))

        # 배지 요약 행
        badge_names = [core._sanitize_grid_text(b["name"]) for b in (stats.get("badges") or [])[:4]]
        badge_line = "  ·  ".join(badge_names) if badge_names else "획득한 업적 배지 없음 (활동 시 자동 해금)"
        draw.text((hx, 144), core._sanitize_grid_text(f"배지: {badge_line}"), font=f_sm, fill=(195, 215, 245, 230))
        draw.text(
            (hx, 172),
            core._sanitize_grid_text(
                f"출석: 누적 {stats['att_total']:,}일  |  연속 {stats['att_streak']:,}일 (최고 {stats['att_max_streak']:,}일)"
            ),
            font=f_sm,
            fill=(134, 239, 172, 240),
        )

        # 우측 자산 요약 박스 2개 (크리스탈 / 낚시골드)
        rx_box = 730
        draw.rounded_rectangle([rx_box, 54, w - 58, 120], radius=14, fill=(15, 23, 42, 235), outline=(56, 189, 248, 160), width=1)
        draw.text((rx_box + 16, 62), core._sanitize_grid_text("보유 크리스탈 (Crystal)"), font=f_sm, fill=(147, 197, 253, 225))
        draw.text((rx_box + 16, 84), core._sanitize_grid_text(f"{stats['crystals']:,} 💎"), font=f_sub, fill=(125, 211, 252, 255))

        draw.rounded_rectangle([rx_box, 130, w - 58, 196], radius=14, fill=(15, 23, 42, 235), outline=(250, 204, 21, 160), width=1)
        draw.text((rx_box + 16, 138), core._sanitize_grid_text("낚시 & 생활 골드 (Gold)"), font=f_sm, fill=(253, 230, 138, 225))
        draw.text((rx_box + 16, 160), core._sanitize_grid_text(f"{stats['fish_gold']:,} G"), font=f_sub, fill=(250, 204, 21, 255))

        # 2×2 게임 패널
        sek = stats["sekai"]
        gen = stats["genshin"]
        hsr = stats["hsr"]
        fl = stats["fishing_life"]

        art_line = (
            f"최고 성유물: {gen['best_art']['name']} ({gen['best_art']['grade']}, CV {gen['best_art']['cv']})"
            if gen.get("best_art")
            else "최고 성유물: 미보유 (/원신 성유물)"
        )
        rel_line = (
            f"최고 유물: {hsr['best_relic']['name']} ({hsr['best_relic']['grade']}, RV {hsr['best_relic']['rv']})"
            if hsr.get("best_relic")
            else "최고 유물: 미보유 (/스타레일 유물)"
        )
        best_fish_line = (
            f"최장 기록: {fl['best_fish_name']} ({fl['best_fish_cm']:.1f} cm)"
            if fl.get("best_fish_cm", 0) > 0
            else "최장 기록: 출조 대기 중 (/낚시 출조)"
        )

        panels = [
            {
                "title": "프로세카 (Project SEKAI)",
                "color": (56, 189, 248),
                "lines": [
                    f"최애(오시): {sek['oshi']}",
                    f"보유 카드: {sek['unique_cards']:,}종  |  ★4 카드: {sek['star4_count']:,}장",
                    f"5인 덱 종합력: {sek['deck_power']:,}",
                    "세카이 라이브 & 의상 스튜디오 연동 중",
                ],
            },
            {
                "title": "원신 (Genshin Impact)",
                "color": (250, 204, 21),
                "lines": [
                    f"누적 기원 횟수: {gen['total_pulls']:,}회",
                    f"★5 캐릭터·무기 보유: {gen['star5_count']:,}종",
                    art_line,
                    "운명의 궤도 & 축성의 엘릭서 연동",
                ],
            },
            {
                "title": "스타레일 (Honkai: Star Rail)",
                "color": (167, 139, 250),
                "lines": [
                    f"누적 워프 횟수: {hsr['total_pulls']:,}회",
                    f"★5 캐릭터·광추 보유: {hsr['star5_count']:,}종",
                    rel_line,
                    "상시 300선택 & 자가조형 레진 연동",
                ],
            },
            {
                "title": "낚시 & 생활 라이프",
                "color": (52, 211, 153),
                "lines": [
                    f"낚시 Lv.{fl['level']} ({fl['catches']:,}마리)  |  도감 {fl['dex_owned']}/{fl['dex_total']}종",
                    best_fish_line,
                    f"장비: {fl['rod_name']} / 그물: {fl['net_name']}",
                    f"동반 펫: {fl['pet_label']}  |  농장 Lv.{fl['farm_level']} (공동 Lv.{fl['guild_farm_level']})",
                ],
            },
        ]

        pw, ph = 492, 206
        positions = [(38, 232), (550, 232), (38, 456), (550, 456)]
        for idx, p_info in enumerate(panels):
            px, py = positions[idx]
            cr, cg, cb = p_info["color"]
            draw.rounded_rectangle([px, py, px + pw, py + ph], radius=18, fill=(18, 25, 44, 230), outline=(cr, cg, cb, 165), width=2)
            draw.rounded_rectangle([px + 14, py + 14, px + 22, py + 44], radius=4, fill=(cr, cg, cb, 255))
            draw.text((px + 34, py + 16), core._sanitize_grid_text(p_info["title"]), font=f_card_title, fill=(255, 255, 255, 255))
            draw.line([(px + 18, py + 54), (px + pw - 18, py + 54)], fill=(255, 255, 255, 32), width=1)

            for l_idx, raw_line in enumerate(p_info["lines"]):
                ly = py + 68 + l_idx * 32
                line_clean = core._sanitize_grid_text(raw_line)
                if f_body and line_clean:
                    base_l = line_clean
                    cut = len(base_l)
                    while cut > 8 and draw.textbbox((0, 0), line_clean, font=f_body)[2] > (pw - 36):
                        cut -= 1
                        line_clean = base_l[:cut].rstrip() + "..."
                draw.text((px + 18, ly), line_clean, font=f_body, fill=(226, 232, 240, 240))

        # 하단 푸터
        now_str = datetime.datetime.now(core.KST).strftime("%Y-%m-%d %H:%M KST")
        draw.text((44, h - 42), core._sanitize_grid_text(f"norosi Unified Profile Card  ·  Issued at {now_str}"), font=f_sm, fill=(148, 163, 184, 220))

        buf = io.BytesIO()
        img.save(buf, format="PNG", compress_level=1)
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"⚠️ [economy_core] 프로필 카드 PNG 렌더링 예외: {e}", flush=True)
        return None
    finally:
        if img is not None:
            try:
                img.close()
            except Exception:
                pass


async def build_unified_profile_card_bytes(
    user: Any,
    guild_id: int | str = 0,
    avatar_bytes: Optional[bytes] = None,
) -> Tuple[Dict[str, Any], Optional[io.BytesIO]]:
    """아바타 이미지 비동기 다운로드 후 통합 프로필 통계 + PNG 버퍼 반환."""
    import asyncio

    uid = getattr(user, "id", 0)
    uname = getattr(user, "display_name", None) or getattr(user, "name", "유저")

    def _collect():
        with core._DATA_LOCK:
            data = core.load_data()
            st = collect_user_unified_stats(data, guild_id, uid, uname)
            if st["newly_unlocked_titles"]:
                core.save_data(data)
            return st

    stats = await asyncio.to_thread(_collect)

    if avatar_bytes is None:
        disp_av = getattr(user, "display_avatar", None)
        if disp_av is not None and hasattr(disp_av, "read"):
            try:
                avatar_bytes = await asyncio.wait_for(disp_av.read(), timeout=2.5)
            except Exception:
                avatar_bytes = None
        if avatar_bytes is None:
            av_url = str(getattr(disp_av, "url", "") or "")
            if aiohttp is not None and av_url.startswith(("http://", "https://")) and "example.com" not in av_url:
                try:
                    timeout = aiohttp.ClientTimeout(total=2.5)
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.get(av_url) as resp:
                            if resp.status == 200:
                                avatar_bytes = await resp.read()
                except Exception:
                    avatar_bytes = None

    png_buf = await asyncio.to_thread(render_unified_profile_card_png, stats, avatar_bytes)
    return stats, png_buf
