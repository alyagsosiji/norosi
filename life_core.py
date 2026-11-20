"""
life_core.py - 방치형 · 생활 컨텐츠 확장 엔진 (개인 농장 · 서버 공동 농장 · 펫 육성 · 생선 요리 & 버프)
낚시 시스템(fishing_core) 및 일일 출석체크(core.process_user_attendance)와 실시간으로 연동됩니다.
"""

from __future__ import annotations

import copy
import random
import time
from typing import Any, Dict, List, Optional, Tuple

import core

_LIFE_LOCK = core._DATA_LOCK


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        if val is None or isinstance(val, bool):
            return int(val) if isinstance(val, bool) else default
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
# 카탈로그: 농작물 씨앗 · 펫 · 생선 요리 레시피
# ==========================================
SEEDS: Dict[str, Dict[str, Any]] = {
    "clover": {
        "id": "clover",
        "name": "네잎클로버",
        "emoji": "🍀",
        "growth_min": 5,
        "price_gold": 120,
        "price_crystal": 20,
        "yield_min": 2,
        "yield_max": 3,
        "sell_gold": 95,
        "sell_crystal": 0,
        "exp": 12,
        "desc": "5분 만에 자라는 행운의 허브 · 빠른 농장 경험치와 파르페 재료",
    },
    "herb": {
        "id": "herb",
        "name": "바다 허브",
        "emoji": "🌿",
        "growth_min": 10,
        "price_gold": 220,
        "price_crystal": 35,
        "yield_min": 2,
        "yield_max": 3,
        "sell_gold": 165,
        "sell_crystal": 0,
        "exp": 20,
        "desc": "10분 성장 · 모둠회 요리에 상쾌한 풍미를 더해주는 약초",
    },
    "rice": {
        "id": "rice",
        "name": "황금 벼",
        "emoji": "🌾",
        "growth_min": 15,
        "price_gold": 320,
        "price_crystal": 50,
        "yield_min": 2,
        "yield_max": 3,
        "sell_gold": 240,
        "sell_crystal": 0,
        "exp": 28,
        "desc": "15분 성장 · 황금빛 셰프 초밥의 필수 식재료",
    },
    "strawberry": {
        "id": "strawberry",
        "name": "세카이 딸기",
        "emoji": "🍓",
        "growth_min": 25,
        "price_gold": 500,
        "price_crystal": 75,
        "yield_min": 2,
        "yield_max": 3,
        "sell_gold": 380,
        "sell_crystal": 0,
        "exp": 42,
        "desc": "25분 성장 · 달콤한 디저트 파르페(출석 보너스)의 주재료",
    },
    "truffle": {
        "id": "truffle",
        "name": "심해 송로버섯",
        "emoji": "🍄",
        "growth_min": 40,
        "price_gold": 850,
        "price_crystal": 120,
        "yield_min": 1,
        "yield_max": 2,
        "sell_gold": 780,
        "sell_crystal": 5,
        "exp": 68,
        "desc": "40분 성장 · 최고급 요리 트러플 정식 재료 및 크리스탈 부산물",
    },
    "crystal_berry": {
        "id": "crystal_berry",
        "name": "크리스탈 열매",
        "emoji": "💠",
        "growth_min": 60,
        "price_gold": 0,
        "price_crystal": 140,
        "yield_min": 1,
        "yield_max": 2,
        "sell_gold": 300,
        "sell_crystal": 115,
        "exp": 95,
        "desc": "60분 성장 · 수확 후 판매 시 크리스탈 수익을 안겨주는 신비한 열매",
    },
}

PETS: Dict[str, Dict[str, Any]] = {
    "cat_neko": {
        "id": "cat_neko",
        "name": "고등어 냥이",
        "emoji": "🐱",
        "currency": "gold",
        "price": 600,
        "rarity": "일반",
        "specialty": "생선 냄새를 기가 막히게 맡는 애교쟁이 고양이",
        "base_rare": 0.05,
        "rare_per_lvl": 0.008,
        "base_gold": 0.06,
        "gold_per_lvl": 0.01,
        "base_size": 0.02,
        "size_per_lvl": 0.004,
        "base_trophy": 0.02,
        "trophy_per_lvl": 0.004,
        "base_cd": 0.1,
        "cd_per_lvl": 0.02,
        "base_att_cry": 8,
        "att_per_lvl": 2,
    },
    "duck_pipi": {
        "id": "duck_pipi",
        "name": "농장 오리 삐삐",
        "emoji": "🐥",
        "currency": "gold",
        "price": 900,
        "rarity": "고급",
        "specialty": "출석 체크와 수확을 응원하는 행운의 농장 마스코트",
        "base_rare": 0.03,
        "rare_per_lvl": 0.005,
        "base_gold": 0.05,
        "gold_per_lvl": 0.008,
        "base_size": 0.02,
        "size_per_lvl": 0.004,
        "base_trophy": 0.02,
        "trophy_per_lvl": 0.004,
        "base_cd": 0.15,
        "cd_per_lvl": 0.02,
        "base_att_cry": 18,
        "att_per_lvl": 4,
    },
    "otter_poko": {
        "id": "otter_poko",
        "name": "해달 포코",
        "emoji": "🦦",
        "currency": "gold",
        "price": 1500,
        "rarity": "희귀",
        "specialty": "월척과 고등급 물고기를 찾아내는 바다 사냥꾼",
        "base_rare": 0.10,
        "rare_per_lvl": 0.012,
        "base_gold": 0.07,
        "gold_per_lvl": 0.01,
        "base_size": 0.06,
        "size_per_lvl": 0.008,
        "base_trophy": 0.08,
        "trophy_per_lvl": 0.01,
        "base_cd": 0.1,
        "cd_per_lvl": 0.02,
        "base_att_cry": 12,
        "att_per_lvl": 2,
    },
    "penguin_lulu": {
        "id": "penguin_lulu",
        "name": "아기 펭귄 루루",
        "emoji": "🐧",
        "currency": "crystal",
        "price": 320,
        "rarity": "희귀",
        "specialty": "입질 대기·출조 쿨타임을 크게 단축해주는 스피드 파트너",
        "base_rare": 0.07,
        "rare_per_lvl": 0.01,
        "base_gold": 0.06,
        "gold_per_lvl": 0.008,
        "base_size": 0.05,
        "size_per_lvl": 0.008,
        "base_trophy": 0.05,
        "trophy_per_lvl": 0.007,
        "base_cd": 0.45,
        "cd_per_lvl": 0.045,
        "base_att_cry": 15,
        "att_per_lvl": 3,
    },
    "fox_kumi": {
        "id": "fox_kumi",
        "name": "은하수 여우 쿠미",
        "emoji": "🦊",
        "currency": "crystal",
        "price": 650,
        "rarity": "전설",
        "specialty": "별빛 가호로 출석 크리스탈과 낚시 판매 골드를 대폭 증폭",
        "base_rare": 0.12,
        "rare_per_lvl": 0.014,
        "base_gold": 0.14,
        "gold_per_lvl": 0.015,
        "base_size": 0.07,
        "size_per_lvl": 0.009,
        "base_trophy": 0.07,
        "trophy_per_lvl": 0.009,
        "base_cd": 0.30,
        "cd_per_lvl": 0.035,
        "base_att_cry": 30,
        "att_per_lvl": 5,
    },
    "whale_mori": {
        "id": "whale_mori",
        "name": "미니 고래 모리",
        "emoji": "🐳",
        "currency": "crystal",
        "price": 1100,
        "rarity": "신화",
        "specialty": "심해의 축복 — 대물 확률·희귀도·월척·판매가 최상급 버프",
        "base_rare": 0.18,
        "rare_per_lvl": 0.016,
        "base_gold": 0.16,
        "gold_per_lvl": 0.016,
        "base_size": 0.12,
        "size_per_lvl": 0.012,
        "base_trophy": 0.14,
        "trophy_per_lvl": 0.014,
        "base_cd": 0.40,
        "cd_per_lvl": 0.04,
        "base_att_cry": 28,
        "att_per_lvl": 4,
    },
}

RECIPES: Dict[str, Dict[str, Any]] = {
    "grilled_fish": {
        "id": "grilled_fish",
        "name": "바삭 생선구이",
        "emoji": "🐟",
        "fish_reqs": [(1, 1)],  # (최소~2 이하 성급: (max_rarity=2, min_rarity=1, count=1)) - 간편 표기
        "need_fish_r1": 1,
        "need_fish_r2": 0,
        "crop_reqs": {},
        "duration_min": 20,
        "buffs": {
            "cooldown_reduce": 0.8,
            "gold_bonus": 0.15,
            "rare_bonus": 0.05,
            "size_bonus": 0.0,
            "trophy_bonus": 0.0,
            "attendance_bonus": 0,
        },
        "desc": "★1~★2 미잠금 물고기 1마리 | 20분간 쿨타임 -0.8초 · 판매골드 +15% · 희귀 +5%",
    },
    "spicy_stew": {
        "id": "spicy_stew",
        "name": "특제 얼큰 매운탕",
        "emoji": "🍲",
        "need_fish_r1": 1,
        "need_fish_r2": 1,
        "crop_reqs": {},
        "duration_min": 30,
        "buffs": {
            "cooldown_reduce": 1.1,
            "gold_bonus": 0.22,
            "rare_bonus": 0.12,
            "size_bonus": 0.08,
            "trophy_bonus": 0.12,
            "attendance_bonus": 0,
        },
        "desc": "★2 물고기 1 + ★1~2 물고기 1 | 30분간 쿨타임 -1.1초 · 월척 +12% · 골드 +22%",
    },
    "herbal_sashimi": {
        "id": "herbal_sashimi",
        "name": "허브 숙성 모둠회",
        "emoji": "🍣",
        "need_fish_r1": 1,
        "need_fish_r2": 0,
        "crop_reqs": {"herb": 1},
        "duration_min": 30,
        "buffs": {
            "cooldown_reduce": 0.5,
            "gold_bonus": 0.15,
            "rare_bonus": 0.22,
            "size_bonus": 0.14,
            "trophy_bonus": 0.08,
            "attendance_bonus": 0,
        },
        "desc": "★1~2 물고기 1 + 바다 허브 1 | 30분간 희귀 +22% · 크기 +14% · 월척 +8%",
    },
    "golden_sushi": {
        "id": "golden_sushi",
        "name": "황금 셰프 초밥",
        "emoji": "🍱",
        "need_fish_r1": 0,
        "need_fish_r2": 1,
        "crop_reqs": {"rice": 1},
        "duration_min": 40,
        "buffs": {
            "cooldown_reduce": 0.8,
            "gold_bonus": 0.30,
            "rare_bonus": 0.28,
            "size_bonus": 0.15,
            "trophy_bonus": 0.10,
            "attendance_bonus": 0,
        },
        "desc": "★2 물고기 1 + 황금 벼 1 | 40분간 희귀 +28% · 판매골드 +30% · 크기 +15%",
    },
    "strawberry_parfait": {
        "id": "strawberry_parfait",
        "name": "세카이 스위트 파르페",
        "emoji": "🍨",
        "need_fish_r1": 0,
        "need_fish_r2": 0,
        "crop_reqs": {"strawberry": 1, "clover": 1},
        "duration_min": 1440,
        "buffs": {
            "cooldown_reduce": 0.0,
            "gold_bonus": 0.0,
            "rare_bonus": 0.15,
            "size_bonus": 0.0,
            "trophy_bonus": 0.0,
            "attendance_bonus": 80,
        },
        "desc": "세카이 딸기 1 + 네잎클로버 1 | 다음 출석체크 +80💎 보너스 & 희귀 +15%",
    },
    "truffle_feast": {
        "id": "truffle_feast",
        "name": "심해 트러플 황제 정식",
        "emoji": "👑",
        "need_fish_r1": 0,
        "need_fish_r2": 2,
        "crop_reqs": {"truffle": 1},
        "duration_min": 45,
        "buffs": {
            "cooldown_reduce": 1.4,
            "gold_bonus": 0.38,
            "rare_bonus": 0.42,
            "size_bonus": 0.24,
            "trophy_bonus": 0.22,
            "attendance_bonus": 0,
        },
        "desc": "★2 물고기 2 + 심해 송로버섯 1 | 45분간 희귀 +42% · 크기 +24% · 월척 +22% · 골드 +38%",
    },
}


# ==========================================
# 레벨/시간/데이터 보장 유틸
# ==========================================
def _calc_farm_level(exp: int) -> Tuple[int, int, int]:
    lvl = 1
    rem = max(0, int(exp))
    while True:
        need = 80 + (lvl - 1) * 40
        if rem < need or lvl >= 99:
            return lvl, rem, need
        rem -= need
        lvl += 1


def _calc_pet_level(exp: int) -> Tuple[int, int, int]:
    lvl = 1
    rem = max(0, int(exp))
    while True:
        need = 60 + (lvl - 1) * 35
        if rem < need or lvl >= 20:
            return lvl, rem, need
        rem -= need
        lvl += 1


def _calc_guild_farm_level(exp: int) -> Tuple[int, int, int]:
    lvl = 1
    rem = max(0, int(exp))
    while True:
        need = 200 + (lvl - 1) * 150
        if rem < need or lvl >= 10:
            return lvl, rem, need
        rem -= need
        lvl += 1


def _get_guild_gold(data: dict, guild_id: int | str, user_id: int | str, user_name: str = "") -> int:
    f_g_map = core.ensure_dict_path(data, "fishing_users", str(guild_id or 0))
    fu = f_g_map.get(str(user_id))
    if not isinstance(fu, dict):
        fu = {"name": user_name or f"낚시꾼({str(user_id)[:4]})", "gold": 300}
        f_g_map[str(user_id)] = fu
    fu.setdefault("gold", 300)
    return max(0, _safe_int(fu.get("gold"), 0))


def _add_guild_gold(data: dict, guild_id: int | str, user_id: int | str, delta: int, user_name: str = "") -> int:
    f_g_map = core.ensure_dict_path(data, "fishing_users", str(guild_id or 0))
    fu = f_g_map.get(str(user_id))
    if not isinstance(fu, dict):
        fu = {"name": user_name or f"낚시꾼({str(user_id)[:4]})", "gold": 300}
        f_g_map[str(user_id)] = fu
    cur = max(0, _safe_int(fu.get("gold"), 300))
    nxt = max(0, cur + int(delta))
    fu["gold"] = nxt
    return nxt


def ensure_life_user(data: dict, guild_id: int | str, user_id: int | str, user_name: str = "") -> Dict[str, Any]:
    g_key = str(guild_id or 0)
    u_key = str(user_id)
    g_map = core.ensure_dict_path(data, "life_users", g_key)
    lu = g_map.get(u_key)
    if not isinstance(lu, dict):
        lu = {}
        g_map[u_key] = lu

    if user_name:
        lu["name"] = user_name
    elif not lu.get("name"):
        lu["name"] = f"주민({u_key[:4]})"

    lu["farm_exp"] = max(0, _safe_int(lu.get("farm_exp"), 0))
    f_lvl, _, _ = _calc_farm_level(lu["farm_exp"])
    lu["farm_level"] = f_lvl
    lu["plot_slots"] = max(4, min(6, _safe_int(lu.get("plot_slots"), 4)))

    raw_plots = core.coerce_list_like(lu.get("plots"))
    plots: List[Dict[str, Any]] = []
    for idx in range(lu["plot_slots"]):
        item = raw_plots[idx] if idx < len(raw_plots) and isinstance(raw_plots[idx], dict) else {}
        plots.append({
            "seed_id": item.get("seed_id") if item.get("seed_id") in SEEDS else None,
            "planted_at": _safe_float(item.get("planted_at"), 0.0),
            "ready_at": _safe_float(item.get("ready_at"), 0.0),
            "watered": bool(item.get("watered", False)),
            "fertilized": bool(item.get("fertilized", False)),
            "bonus_yield": max(0, _safe_int(item.get("bonus_yield"), 0)),
        })
    lu["plots"] = plots

    seeds_map = core.coerce_dict_like(lu.get("seeds"))
    lu["seeds"] = {str(k): max(0, _safe_int(v, 0)) for k, v in seeds_map.items() if k in SEEDS and _safe_int(v, 0) > 0}
    if not lu.get("starter_seeded"):
        lu["starter_seeded"] = True
        lu["seeds"]["clover"] = lu["seeds"].get("clover", 0) + 2

    crops_map = core.coerce_dict_like(lu.get("crops"))
    lu["crops"] = {str(k): max(0, _safe_int(v, 0)) for k, v in crops_map.items() if k in SEEDS and _safe_int(v, 0) > 0}

    lu["pet_food"] = max(0, _safe_int(lu.get("pet_food"), 3 if "pet_food" not in lu else 0))
    pets_map = core.coerce_dict_like(lu.get("pets"))
    clean_pets: Dict[str, Dict[str, Any]] = {}
    for pid, p_obj in pets_map.items():
        if pid in PETS and isinstance(p_obj, dict):
            p_exp = max(0, _safe_int(p_obj.get("exp"), 0))
            plvl, _, _ = _calc_pet_level(p_exp)
            clean_pets[pid] = {
                "exp": p_exp,
                "level": plvl,
                "intimacy": max(0, _safe_int(p_obj.get("intimacy"), 10)),
                "play_date": str(p_obj.get("play_date") or ""),
                "play_count": max(0, _safe_int(p_obj.get("play_count"), 0)),
                "adopted_at": str(p_obj.get("adopted_at") or core.get_today_str()),
            }
    lu["pets"] = clean_pets
    if lu.get("equipped_pet") not in clean_pets:
        lu["equipped_pet"] = next(iter(clean_pets.keys()), None)

    dishes_map = core.coerce_dict_like(lu.get("dishes"))
    lu["dishes"] = {str(k): max(0, _safe_int(v, 0)) for k, v in dishes_map.items() if k in RECIPES and _safe_int(v, 0) > 0}

    now_ts = time.time()
    raw_buffs = core.coerce_list_like(lu.get("active_buffs"))
    clean_buffs: List[Dict[str, Any]] = []
    for b in raw_buffs:
        if not isinstance(b, dict):
            continue
        if _safe_float(b.get("expires_at"), 0.0) > now_ts:
            clean_buffs.append(b)
    lu["active_buffs"] = clean_buffs[:3]
    lu["total_cooked"] = max(0, _safe_int(lu.get("total_cooked"), 0))
    lu["total_harvested"] = max(0, _safe_int(lu.get("total_harvested"), 0))
    return lu


def ensure_guild_farm(data: dict, guild_id: int | str) -> Dict[str, Any]:
    g_key = str(guild_id or 0)
    gf_map = core.ensure_dict_path(data, "guild_farms")
    gf = gf_map.get(g_key)
    if not isinstance(gf, dict):
        gf = {}
        gf_map[g_key] = gf
    gf["exp"] = max(0, _safe_int(gf.get("exp"), 0))
    glvl, rem_exp, need_exp = _calc_guild_farm_level(gf["exp"])
    gf["level"] = glvl
    gf["rem_exp"] = rem_exp
    gf["need_exp"] = need_exp
    gf["water_log"] = core.coerce_dict_like(gf.get("water_log"))
    gf["daily_claimed"] = core.coerce_dict_like(gf.get("daily_claimed"))
    gf["contributors"] = core.coerce_dict_like(gf.get("contributors"))
    gf["total_actions"] = max(0, _safe_int(gf.get("total_actions"), 0))
    return gf


# ==========================================
# 실시간 버프 통합 집계 (낚시 + 출석체크 연동 핵심 엔진)
# ==========================================
def get_active_life_buffs(guild_id: int | str, user_id: int | str, data: Optional[dict] = None) -> Dict[str, Any]:
    """
    현재 활성화된 [생선 요리 버프 + 장착 중인 펫 + 서버 공동 농장] 통합 효과 계산.
    read-only/사이드이펙트 안전하게 동작 (data가 전달되면 그대로 참조).
    """
    if data is None:
        data = core.get_cached_data()

    g_key = str(guild_id or 0)
    u_key = str(user_id)
    now_ts = time.time()

    lu = core.safe_get_dict(data, "life_users", g_key, u_key)
    gf = core.safe_get_dict(data, "guild_farms", g_key)

    cd_reduce = 0.0
    rare_bonus = 0.0
    size_bonus = 0.0
    trophy_bonus = 0.0
    gold_bonus = 0.0
    att_pet_farm_bonus = 0
    att_dish_bonus = 0

    active_dishes: List[Dict[str, Any]] = []
    for b in core.coerce_list_like(lu.get("active_buffs")):
        if not isinstance(b, dict):
            continue
        exp_at = _safe_float(b.get("expires_at"), 0.0)
        if exp_at <= now_ts:
            continue
        rem_min = max(1, int((exp_at - now_ts) // 60) + 1)
        b_copy = copy.deepcopy(b)
        b_copy["remain_min"] = rem_min
        active_dishes.append(b_copy)

        cd_reduce += _safe_float(b.get("cooldown_reduce"), 0.0)
        rare_bonus += _safe_float(b.get("rare_bonus"), 0.0)
        size_bonus += _safe_float(b.get("size_bonus"), 0.0)
        trophy_bonus += _safe_float(b.get("trophy_bonus"), 0.0)
        gold_bonus += _safe_float(b.get("gold_bonus"), 0.0)
        att_dish_bonus += max(0, _safe_int(b.get("attendance_bonus"), 0))

    pet_summary = None
    eq_pid = lu.get("equipped_pet")
    pets_map = core.as_dict(lu.get("pets"))
    if eq_pid and eq_pid in PETS and isinstance(pets_map.get(eq_pid), dict):
        pm = PETS[eq_pid]
        pu = pets_map[eq_pid]
        plvl = max(1, _safe_int(pu.get("level"), 1))
        step = plvl - 1
        p_cd = round(pm["base_cd"] + pm["cd_per_lvl"] * step, 2)
        p_rare = round(pm["base_rare"] + pm["rare_per_lvl"] * step, 4)
        p_size = round(pm["base_size"] + pm["size_per_lvl"] * step, 4)
        p_trophy = round(pm["base_trophy"] + pm["trophy_per_lvl"] * step, 4)
        p_gold = round(pm["base_gold"] + pm["gold_per_lvl"] * step, 4)
        p_att = int(pm["base_att_cry"] + pm["att_per_lvl"] * step)

        cd_reduce += p_cd
        rare_bonus += p_rare
        size_bonus += p_size
        trophy_bonus += p_trophy
        gold_bonus += p_gold
        att_pet_farm_bonus += p_att
        pet_summary = {
            "id": eq_pid,
            "name": pm["name"],
            "emoji": pm["emoji"],
            "level": plvl,
            "rarity": pm["rarity"],
            "intimacy": max(0, _safe_int(pu.get("intimacy"), 10)),
            "cd_reduce": p_cd,
            "rare_bonus": p_rare,
            "size_bonus": p_size,
            "trophy_bonus": p_trophy,
            "gold_bonus": p_gold,
            "att_bonus": p_att,
        }

    gf_exp = max(0, _safe_int(gf.get("exp"), 0))
    gf_lvl, _, _ = _calc_guild_farm_level(gf_exp) if gf else (1, 0, 200)
    has_guild_farm = bool(gf and gf_exp > 0)
    gf_rare = round((gf_lvl - 1) * 0.02, 4) if gf_lvl > 1 else 0.0
    gf_gold = round((gf_lvl - 1) * 0.03, 4) if gf_lvl > 1 else 0.0
    gf_att = gf_lvl * 5 if has_guild_farm else 0
    rare_bonus += gf_rare
    gold_bonus += gf_gold
    att_pet_farm_bonus += gf_att

    cd_reduce = min(2.3, round(cd_reduce, 2))
    summary_lines: List[str] = []
    if pet_summary:
        summary_lines.append(
            f"{pet_summary['emoji']} **{pet_summary['name']} Lv.{pet_summary['level']}** "
            f"(희귀 `+{int(pet_summary['rare_bonus']*100)}%`, 골드 `+{int(pet_summary['gold_bonus']*100)}%`, 출석 `+{pet_summary['att_bonus']}💎`)"
        )
    if has_guild_farm:
        summary_lines.append(
            f"🌾 **서버 공동 농장 Lv.{gf_lvl}** "
            f"(희귀 `+{int(gf_rare*100)}%`, 골드 `+{int(gf_gold*100)}%`, 출석 `+{gf_att}💎`)"
        )
    for d in active_dishes:
        summary_lines.append(f"{d.get('emoji', '🍽️')} **{d.get('name')}** (`{d['remain_min']}분 남음`)")

    return {
        "cooldown_reduce": cd_reduce,
        "rare_bonus": round(rare_bonus, 4),
        "size_bonus": round(size_bonus, 4),
        "trophy_bonus": round(trophy_bonus, 4),
        "gold_bonus": round(gold_bonus, 4),
        "attendance_passive_bonus": att_pet_farm_bonus,
        "attendance_dish_bonus": att_dish_bonus,
        "attendance_total_bonus": att_pet_farm_bonus + att_dish_bonus,
        "active_dishes": active_dishes,
        "pet": pet_summary,
        "guild_farm_level": gf_lvl if has_guild_farm else 0,
        "summary_lines": summary_lines,
    }


def consume_attendance_life_bonus(data: dict, guild_id: int | str, user_id: int | str, user_name: str = "") -> Tuple[int, List[str]]:
    """
    core.process_user_attendance 내부(_DATA_LOCK 보유 상태)에서 호출되어
    1) 장착 펫 출석 보너스 + 서버 공동 농장 보너스 계산
    2) 일회성 출석 요리 버프(세카이 스위트 파르페 등) 소모
    를 data 딕셔너리 위에서 원자적으로 수행합니다.
    """
    g_key = str(guild_id or 0)
    u_key = str(user_id)
    now_ts = time.time()

    lu = core.safe_get_dict(data, "life_users", g_key, u_key)
    gf = core.safe_get_dict(data, "guild_farms", g_key)

    total_bonus = 0
    reasons: List[str] = []

    # 1. 장착 펫 보너스
    eq_pid = lu.get("equipped_pet") if isinstance(lu, dict) else None
    pets_map = core.as_dict(lu.get("pets")) if isinstance(lu, dict) else {}
    if eq_pid and eq_pid in PETS and isinstance(pets_map.get(eq_pid), dict):
        pm = PETS[eq_pid]
        plvl = max(1, _safe_int(pets_map[eq_pid].get("level"), 1))
        p_att = int(pm["base_att_cry"] + pm["att_per_lvl"] * (plvl - 1))
        if p_att > 0:
            total_bonus += p_att
            reasons.append(f"{pm['emoji']} {pm['name']} Lv.{plvl}(+{p_att}💎)")

    # 2. 서버 공동 농장 보너스 (공동 농장 경험치가 1 이상 기록된 경우 활성화)
    if isinstance(gf, dict) and _safe_int(gf.get("exp"), 0) > 0:
        gf_lvl, _, _ = _calc_guild_farm_level(_safe_int(gf.get("exp"), 0))
        gf_att = gf_lvl * 5
        total_bonus += gf_att
        reasons.append(f"🌾 공동농장 Lv.{gf_lvl}(+{gf_att}💎)")

    # 3. 일회성 출석 요리 버프 소모
    if isinstance(lu, dict) and isinstance(lu.get("active_buffs"), list):
        kept_buffs = []
        for b in lu["active_buffs"]:
            if not isinstance(b, dict):
                continue
            if _safe_float(b.get("expires_at"), 0.0) <= now_ts:
                continue
            att_b = max(0, _safe_int(b.get("attendance_bonus"), 0))
            if att_b > 0:
                total_bonus += att_b
                reasons.append(f"{b.get('emoji', '🍨')} {b.get('name', '요리 버프')}(+{att_b}💎)")
                # 출석 보너스 소모 후 다른 지속 버프가 남으면 attendance_bonus만 0으로, 아니면 제거
                if _safe_float(b.get("rare_bonus"), 0.0) > 0:
                    b["attendance_bonus"] = 0
                    kept_buffs.append(b)
            else:
                kept_buffs.append(b)
        lu["active_buffs"] = kept_buffs

    return total_bonus, reasons


# ==========================================
# 개인 농장 액션 (씨앗 구매 · 파종 · 물주기 · 비료 · 수확 · 판매 · 확장)
# ==========================================
def get_life_overview(guild_id: int | str, user_id: int | str, user_name: str = "") -> Dict[str, Any]:
    with _LIFE_LOCK:
        data = core.load_data()
        g_key = str(guild_id or 0)
        u_key = str(user_id)
        before_state = (
            copy.deepcopy(core.safe_get_dict(data, "life_users", g_key, u_key)),
            copy.deepcopy(core.safe_get_dict(data, "guild_farms", g_key)),
            copy.deepcopy(core.safe_get_dict(data, "user_profiles", u_key)),
        )
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        gf = ensure_guild_farm(data, guild_id)
        prof = core.ensure_user_profile(data, user_id, user_name)
        gold = _get_guild_gold(data, guild_id, user_id, user_name)
        crystals = max(0, _safe_int(prof.get("crystals"), 0))
        buffs = get_active_life_buffs(guild_id, user_id, data=data)

        # 가방 내 요리 가능(미잠금 ★1~★2) 물고기 집계
        bag = core.coerce_list_like(core.safe_get_dict(data, "fishing_users", g_key, u_key).get("bag"))
        cookable_r1 = sum(1 for it in bag if isinstance(it, dict) and not it.get("locked", False) and _safe_int(it.get("rarity"), 1) == 1)
        cookable_r2 = sum(1 for it in bag if isinstance(it, dict) and not it.get("locked", False) and _safe_int(it.get("rarity"), 1) == 2)

        if (lu, gf, prof) != before_state:
            core.save_data(data)
        return {
            "user": copy.deepcopy(lu),
            "guild_farm": copy.deepcopy(gf),
            "gold": gold,
            "crystals": crystals,
            "buffs": buffs,
            "cookable_r1": cookable_r1,
            "cookable_r2": cookable_r2,
            "now_ts": time.time(),
        }


def buy_seed(
    guild_id: int | str,
    user_id: int | str,
    seed_id: str,
    qty: int = 1,
    currency: str = "gold",
    user_name: str = "",
) -> Tuple[bool, str]:
    seed = SEEDS.get(seed_id)
    if not seed:
        return False, "❌ 존재하지 않는 씨앗입니다."
    qty = max(1, min(20, int(qty)))

    with _LIFE_LOCK:
        data = core.load_data()
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        prof = core.ensure_user_profile(data, user_id, user_name)

        use_cur = currency if currency in ("gold", "crystal") else "gold"
        if use_cur == "gold" and seed["price_gold"] <= 0:
            use_cur = "crystal"

        if use_cur == "crystal":
            cost = seed["price_crystal"] * qty
            have = max(0, _safe_int(prof.get("crystals"), 0))
            if have < cost:
                return False, f"❌ 크리스탈이 부족합니다! (필요: `{cost:,}💎` / 보유: `{have:,}💎`)"
            prof["crystals"] = have - cost
            cost_txt = f"`-{cost:,}💎`"
        else:
            cost = seed["price_gold"] * qty
            have = _get_guild_gold(data, guild_id, user_id, user_name)
            if have < cost:
                return False, f"❌ 낚시 골드가 부족합니다! (필요: `{cost:,}🪙` / 보유: `{have:,}🪙`)"
            _add_guild_gold(data, guild_id, user_id, -cost, user_name)
            cost_txt = f"`-{cost:,}🪙`"

        lu["seeds"][seed_id] = lu["seeds"].get(seed_id, 0) + qty
        core.save_data(data)
        return True, f"🌱 {seed['emoji']} **{seed['name']} 씨앗 ×{qty}개** 구매 완료! ({cost_txt} · 보유 `{lu['seeds'][seed_id]}개`)"


def plant_crop(
    guild_id: int | str,
    user_id: int | str,
    seed_id: str,
    plot_idx: Optional[int] = None,
    user_name: str = "",
) -> Tuple[bool, str]:
    seed = SEEDS.get(seed_id)
    if not seed:
        return False, "❌ 알 수 없는 작물입니다."

    with _LIFE_LOCK:
        data = core.load_data()
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        have_seed = lu["seeds"].get(seed_id, 0)
        if have_seed <= 0:
            return False, f"❌ **{seed['name']} 씨앗**을 보유하고 있지 않습니다! 먼저 씨앗을 구매해 주세요."

        plots = lu["plots"]
        target_idx = None
        if plot_idx is not None and 0 <= plot_idx < len(plots):
            if plots[plot_idx].get("seed_id") is None:
                target_idx = plot_idx
            else:
                return False, f"⚠️ {plot_idx + 1}번 밭에는 이미 작물이 자라고 있습니다."
        else:
            for idx, p in enumerate(plots):
                if p.get("seed_id") is None:
                    target_idx = idx
                    break

        if target_idx is None:
            return False, "⚠️ 비어 있는 밭 슬롯이 없습니다! 다 자란 작물을 수확하거나 밭을 확장해 주세요."

        now_ts = time.time()
        growth_sec = seed["growth_min"] * 60.0
        # 펫/농장 레벨에 따른 미세 성장 단축 (최대 20%)
        farm_lvl = max(1, _safe_int(lu.get("farm_level"), 1))
        speed_mult = max(0.80, 1.0 - (farm_lvl - 1) * 0.015)
        dur = growth_sec * speed_mult

        lu["seeds"][seed_id] = have_seed - 1
        if lu["seeds"][seed_id] <= 0:
            lu["seeds"].pop(seed_id, None)

        plots[target_idx] = {
            "seed_id": seed_id,
            "planted_at": now_ts,
            "ready_at": now_ts + dur,
            "watered": False,
            "fertilized": False,
            "bonus_yield": 0,
        }
        core.save_data(data)
        mins = max(1, int(round(dur / 60.0)))
        return True, f"🪴 **{target_idx + 1}번 밭**에 {seed['emoji']} **{seed['name']}**을(를) 심었습니다! (수확까지 약 `{mins}분`)"


def water_farm_plot(
    guild_id: int | str,
    user_id: int | str,
    plot_idx: Optional[int] = None,
    user_name: str = "",
) -> Tuple[bool, str]:
    with _LIFE_LOCK:
        data = core.load_data()
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        now_ts = time.time()
        watered_cnt = 0

        targets = [plot_idx] if plot_idx is not None else list(range(len(lu["plots"])))
        for idx in targets:
            if idx is None or not (0 <= idx < len(lu["plots"])):
                continue
            p = lu["plots"][idx]
            if not p.get("seed_id") or p.get("watered"):
                continue
            rem = _safe_float(p.get("ready_at"), 0.0) - now_ts
            if rem <= 0:
                continue
            p["watered"] = True
            p["ready_at"] = now_ts + rem * 0.65  # 남은 성장 시간 35% 단축
            watered_cnt += 1

        if watered_cnt == 0:
            return False, "ℹ️ 지금 물을 줄 수 있는 성장 중인 작물이 없습니다."

        core.save_data(data)
        return True, f"💧 작물 `{watered_cnt}칸`에 시원한 물을 주었습니다! (남은 성장 시간 `35% 단축`)"


def fertilize_plot(
    guild_id: int | str,
    user_id: int | str,
    plot_idx: Optional[int] = None,
    user_name: str = "",
) -> Tuple[bool, str]:
    cost_per_plot = 120
    with _LIFE_LOCK:
        data = core.load_data()
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        now_ts = time.time()
        gold = _get_guild_gold(data, guild_id, user_id, user_name)

        targets = [plot_idx] if plot_idx is not None else list(range(len(lu["plots"])))
        eligible = []
        for idx in targets:
            if idx is not None and 0 <= idx < len(lu["plots"]):
                p = lu["plots"][idx]
                if p.get("seed_id") and not p.get("fertilized") and _safe_float(p.get("ready_at"), 0.0) > now_ts:
                    eligible.append(idx)

        if not eligible:
            return False, "ℹ️ 비료를 줄 수 있는 성장 중인 작물이 없습니다."

        total_cost = len(eligible) * cost_per_plot
        if gold < total_cost:
            return False, f"❌ 고급 비료 비용이 부족합니다! (필요: `{total_cost:,}🪙` / 보유: `{gold:,}🪙`)"

        _add_guild_gold(data, guild_id, user_id, -total_cost, user_name)
        for idx in eligible:
            p = lu["plots"][idx]
            p["fertilized"] = True
            p["ready_at"] = now_ts  # 즉시 성장 완료!
            p["bonus_yield"] = _safe_int(p.get("bonus_yield"), 0) + 1

        core.save_data(data)
        return True, f"✨ **{len(eligible)}칸**에 마력 비료를 뿌려 **즉시 수확 가능(수확량 +1)** 상태가 되었습니다! (`-{total_cost:,}🪙`)"


def harvest_plots(guild_id: int | str, user_id: int | str, user_name: str = "") -> Tuple[bool, str, Dict[str, Any]]:
    with _LIFE_LOCK:
        data = core.load_data()
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        now_ts = time.time()

        harvested: Dict[str, int] = {}
        gain_exp = 0
        pet_food_found = 0
        harvested_slots = 0

        for idx, p in enumerate(lu["plots"]):
            sid = p.get("seed_id")
            if not sid or sid not in SEEDS:
                continue
            if _safe_float(p.get("ready_at"), 0.0) > now_ts:
                continue
            sp = SEEDS[sid]
            qty = random.randint(sp["yield_min"], sp["yield_max"]) + _safe_int(p.get("bonus_yield"), 0)
            lu["crops"][sid] = lu["crops"].get(sid, 0) + qty
            harvested[sid] = harvested.get(sid, 0) + qty
            gain_exp += sp["exp"]
            harvested_slots += 1
            if random.random() < 0.45:
                pet_food_found += 1

            lu["plots"][idx] = {
                "seed_id": None,
                "planted_at": 0.0,
                "ready_at": 0.0,
                "watered": False,
                "fertilized": False,
                "bonus_yield": 0,
            }

        if harvested_slots == 0:
            return False, "⏳ 아직 수확 가능한 작물이 없습니다!", {}

        lu["farm_exp"] = lu.get("farm_exp", 0) + gain_exp
        old_lvl = lu.get("farm_level", 1)
        new_lvl, _, _ = _calc_farm_level(lu["farm_exp"])
        lu["farm_level"] = new_lvl
        lu["total_harvested"] = lu.get("total_harvested", 0) + harvested_slots
        if pet_food_found > 0:
            lu["pet_food"] = lu.get("pet_food", 0) + pet_food_found

        core.save_data(data)
        summary_items = ", ".join(f"{SEEDS[k]['emoji']} {SEEDS[k]['name']} ×{v}" for k, v in harvested.items())
        extra = f" · 🦴 펫 간식 `+{pet_food_found}`" if pet_food_found > 0 else ""
        lvl_msg = f" 🎉 **농장 Lv.{new_lvl} 달성!**" if new_lvl > old_lvl else ""
        return (
            True,
            f"🧺 **{harvested_slots}칸 수확 완료!** ({summary_items} · `+{gain_exp} EXP`{extra}){lvl_msg}",
            {"harvested": harvested, "exp": gain_exp, "pet_food": pet_food_found, "leveled_up": new_lvl > old_lvl},
        )


def sell_crops(guild_id: int | str, user_id: int | str, crop_id: str = "all", user_name: str = "") -> Tuple[bool, str]:
    with _LIFE_LOCK:
        data = core.load_data()
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        prof = core.ensure_user_profile(data, user_id, user_name)

        crops = lu["crops"]
        if not crops:
            return False, "ℹ️ 판매할 수확 작물이 없습니다."

        target_ids = list(crops.keys()) if crop_id == "all" else ([crop_id] if crop_id in crops else [])
        if not target_ids:
            return False, "ℹ️ 선택한 작물을 보유하고 있지 않습니다."

        gain_gold = 0
        gain_cry = 0
        sold_cnt = 0
        for cid in target_ids:
            qty = max(0, _safe_int(crops.get(cid), 0))
            if qty <= 0 or cid not in SEEDS:
                continue
            sp = SEEDS[cid]
            gain_gold += sp["sell_gold"] * qty
            gain_cry += sp["sell_crystal"] * qty
            sold_cnt += qty
            crops.pop(cid, None)

        if sold_cnt == 0:
            return False, "ℹ️ 판매할 작물이 없습니다."

        if gain_gold > 0:
            _add_guild_gold(data, guild_id, user_id, gain_gold, user_name)
        if gain_cry > 0:
            prof["crystals"] = max(0, _safe_int(prof.get("crystals"), 0)) + gain_cry

        core.save_data(data)
        parts = []
        if gain_gold > 0:
            parts.append(f"`+{gain_gold:,}🪙`")
        if gain_cry > 0:
            parts.append(f"`+{gain_cry:,}💎`")
        return True, f"💰 수확 작물 `{sold_cnt}개`를 시장에 판매했습니다! ({' · '.join(parts)})"


def expand_farm_plots(guild_id: int | str, user_id: int | str, user_name: str = "") -> Tuple[bool, str]:
    with _LIFE_LOCK:
        data = core.load_data()
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        cur = lu["plot_slots"]
        if cur >= 6:
            return False, "🏆 이미 농장 밭이 최대 크기(6칸)까지 확장되었습니다!"
        cost_gold = 1200 if cur == 4 else 2400
        have = _get_guild_gold(data, guild_id, user_id, user_name)
        if have < cost_gold:
            return False, f"❌ 밭 확장 비용이 부족합니다! (필요: `{cost_gold:,}🪙` / 보유: `{have:,}🪙`)"
        _add_guild_gold(data, guild_id, user_id, -cost_gold, user_name)
        lu["plot_slots"] = cur + 1
        ensure_life_user(data, guild_id, user_id, user_name)
        core.save_data(data)
        return True, f"🚜 개인 농장 밭이 `{cur}칸 → {cur + 1}칸`으로 확장되었습니다! (`-{cost_gold:,}🪙`)"


# ==========================================
# 서버 공동 농장 (길드 전체 협동 버프 & 일일 배당)
# ==========================================
def contribute_community_farm(
    guild_id: int | str,
    user_id: int | str,
    mode: str = "water",
    user_name: str = "",
) -> Tuple[bool, str]:
    today = core.get_today_str()
    u_key = str(user_id)

    with _LIFE_LOCK:
        data = core.load_data()
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        gf = ensure_guild_farm(data, guild_id)
        prof = core.ensure_user_profile(data, user_id, user_name)

        old_lvl = gf["level"]
        gain_gf_exp = 0
        reward_msg = ""

        if mode == "water":
            today_map = gf["water_log"].setdefault(today, {})
            if not isinstance(today_map, dict):
                today_map = {}
                gf["water_log"][today] = today_map
            used = _safe_int(today_map.get(u_key), 0)
            if used >= 3:
                return False, "💧 오늘 서버 공동 농장 무료 물주기는 최대 **3회**까지 가능합니다!"
            today_map[u_key] = used + 1
            gain_gf_exp = 25
            _add_guild_gold(data, guild_id, user_id, 25, user_name)
            prof["crystals"] = max(0, _safe_int(prof.get("crystals"), 0)) + 5
            reward_msg = f"보상: `+25🪙 · +5💎` · 오늘 무료 물주기 `{used + 1}/3회`"
        elif mode == "gold_donate":
            gold = _get_guild_gold(data, guild_id, user_id, user_name)
            if gold < 500:
                return False, f"❌ 공동 농장 기부에 필요한 낚시 골드가 부족합니다! (필요: `500🪙` / 보유: `{gold:,}🪙`)"
            _add_guild_gold(data, guild_id, user_id, -500, user_name)
            gain_gf_exp = 70
            lu["pet_food"] = lu.get("pet_food", 0) + 1
            reward_msg = "기부: `-500🪙` · 답례: `🦴 펫 간식 +1`"
        elif mode == "crystal_donate":
            have_c = max(0, _safe_int(prof.get("crystals"), 0))
            if have_c < 50:
                return False, f"❌ 공동 농장 기부에 필요한 크리스탈이 부족합니다! (필요: `50💎` / 보유: `{have_c:,}💎`)"
            prof["crystals"] = have_c - 50
            gain_gf_exp = 100
            lu["pet_food"] = lu.get("pet_food", 0) + 2
            reward_msg = "기부: `-50💎` · 답례: `🦴 펫 간식 +2`"
        else:
            return False, "❌ 알 수 없는 공동 농장 기여 방식입니다."

        gf["exp"] += gain_gf_exp
        gf["total_actions"] = _safe_int(gf.get("total_actions"), 0) + 1
        c_rec = gf["contributors"].get(u_key)
        if not isinstance(c_rec, dict):
            c_rec = {"name": user_name or u_key, "points": 0}
        if user_name:
            c_rec["name"] = user_name
        c_rec["points"] = _safe_int(c_rec.get("points"), 0) + gain_gf_exp
        gf["contributors"][u_key] = c_rec

        new_lvl, rem_e, need_e = _calc_guild_farm_level(gf["exp"])
        gf["level"] = new_lvl
        gf["rem_exp"] = rem_e
        gf["need_exp"] = need_e

        # 오래된 일일 로그 정리 (최근 7일분만 유지)
        if len(gf["water_log"]) > 7:
            for old_d in sorted(gf["water_log"].keys())[:-7]:
                gf["water_log"].pop(old_d, None)

        core.save_data(data)
        lvl_txt = f" 🎊 **서버 공동 농장 Lv.{new_lvl} 레벨업!**" if new_lvl > old_lvl else ""
        return True, f"🌾 **공동 농장 성장 `+{gain_gf_exp} EXP`**! ({reward_msg}){lvl_txt}"


def claim_community_farm_daily(guild_id: int | str, user_id: int | str, user_name: str = "") -> Tuple[bool, str]:
    today = core.get_today_str()
    u_key = str(user_id)

    with _LIFE_LOCK:
        data = core.load_data()
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        gf = ensure_guild_farm(data, guild_id)
        prof = core.ensure_user_profile(data, user_id, user_name)

        claimed_today = gf["daily_claimed"].setdefault(today, {})
        if not isinstance(claimed_today, dict):
            claimed_today = {}
            gf["daily_claimed"][today] = claimed_today

        if claimed_today.get(u_key):
            return False, "ℹ️ 오늘의 공동 농장 수확 배당금을 이미 수령했습니다! 내일(00:00 KST) 다시 수령할 수 있습니다."

        if _safe_int(gf.get("level"), 1) <= 1 and _safe_int(gf.get("exp"), 0) <= 0 and not gf.get("water_log"):
            return False, "🌱 먼저 서버 공동 농장에 물주기 또는 수확 기여를 1회 이상 진행해 주세요!"

        lvl = gf["level"]
        gold_div = 150 + lvl * 80
        cry_div = 10 + lvl * 5
        claimed_today[u_key] = True
        _add_guild_gold(data, guild_id, user_id, gold_div, user_name)
        prof["crystals"] = max(0, _safe_int(prof.get("crystals"), 0)) + cry_div
        lu["pet_food"] = lu.get("pet_food", 0) + 1

        if len(gf["daily_claimed"]) > 7:
            for old_d in sorted(gf["daily_claimed"].keys())[:-7]:
                gf["daily_claimed"].pop(old_d, None)

        core.save_data(data)
        return True, f"🎁 **서버 공동 농장(Lv.{lvl}) 일일 수확 배당 수령!** (`+{gold_div:,}🪙` · `+{cry_div:,}💎` · `🦴 펫 간식 +1`)"


# ==========================================
# 펫 입양 · 장착 · 먹이 · 놀아주기
# ==========================================
def adopt_pet(guild_id: int | str, user_id: int | str, pet_id: str, user_name: str = "") -> Tuple[bool, str]:
    pm = PETS.get(pet_id)
    if not pm:
        return False, "❌ 존재하지 않는 펫입니다."

    with _LIFE_LOCK:
        data = core.load_data()
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        prof = core.ensure_user_profile(data, user_id, user_name)

        if pet_id in lu["pets"]:
            lu["equipped_pet"] = pet_id
            core.save_data(data)
            return True, f"{pm['emoji']} 이미 보유 중인 **{pm['name']}**을(를) 동반 펫으로 장착했습니다!"

        price = pm["price"]
        if pm["currency"] == "crystal":
            have = max(0, _safe_int(prof.get("crystals"), 0))
            if have < price:
                return False, f"❌ 크리스탈이 부족합니다! (필요: `{price:,}💎` / 보유: `{have:,}💎`)"
            prof["crystals"] = have - price
            cost_s = f"`-{price:,}💎`"
        else:
            have = _get_guild_gold(data, guild_id, user_id, user_name)
            if have < price:
                return False, f"❌ 낚시 골드가 부족합니다! (필요: `{price:,}🪙` / 보유: `{have:,}🪙`)"
            _add_guild_gold(data, guild_id, user_id, -price, user_name)
            cost_s = f"`-{price:,}🪙`"

        lu["pets"][pet_id] = {
            "exp": 0,
            "level": 1,
            "intimacy": 10,
            "play_date": "",
            "play_count": 0,
            "adopted_at": core.get_today_str(),
        }
        lu["equipped_pet"] = pet_id
        core.save_data(data)
        return True, f"🎉 {pm['emoji']} **{pm['name']}**을(를) 입양하고 동반 펫으로 장착했습니다! ({cost_s})"


def equip_pet(guild_id: int | str, user_id: int | str, pet_id: str, user_name: str = "") -> Tuple[bool, str]:
    with _LIFE_LOCK:
        data = core.load_data()
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        if pet_id not in lu["pets"] or pet_id not in PETS:
            return False, "❌ 보유하지 않은 펫입니다."
        lu["equipped_pet"] = pet_id
        core.save_data(data)
        pm = PETS[pet_id]
        lvl = lu["pets"][pet_id]["level"]
        return True, f"{pm['emoji']} **{pm['name']}** (Lv.{lvl})이(가) 출조 & 출석에 동행합니다!"


def buy_pet_food(guild_id: int | str, user_id: int | str, qty: int = 5, user_name: str = "") -> Tuple[bool, str]:
    qty = max(1, min(50, int(qty)))
    cost = qty * 45
    with _LIFE_LOCK:
        data = core.load_data()
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        gold = _get_guild_gold(data, guild_id, user_id, user_name)
        if gold < cost:
            return False, f"❌ 낚시 골드가 부족합니다! (필요: `{cost:,}🪙` / 보유: `{gold:,}🪙`)"
        _add_guild_gold(data, guild_id, user_id, -cost, user_name)
        lu["pet_food"] = lu.get("pet_food", 0) + qty
        core.save_data(data)
        return True, f"🦴 프리미엄 펫 간식 **`×{qty}개`** 구매! (`-{cost:,}🪙` · 보유 `{lu['pet_food']}개`)"


def feed_pet(
    guild_id: int | str,
    user_id: int | str,
    pet_id: Optional[str] = None,
    feed_source: str = "pet_food",
    user_name: str = "",
) -> Tuple[bool, str]:
    with _LIFE_LOCK:
        data = core.load_data()
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        target_id = pet_id or lu.get("equipped_pet")
        if not target_id or target_id not in lu["pets"]:
            return False, "❌ 먹이를 줄 펫이 없습니다. 먼저 펫을 입양해 주세요!"

        pu = lu["pets"][target_id]
        pm = PETS[target_id]
        consumed_label = ""
        gain_exp = 0
        gain_int = 0

        if feed_source == "fish":
            bag = core.safe_get_dict(data, "fishing_users", str(guild_id or 0), str(user_id)).get("bag")
            if not isinstance(bag, list):
                return False, "❌ 낚시 가방에 먹이로 줄 미잠금 ★1~★2 물고기가 없습니다!"
            picked_idx = None
            for idx, item in enumerate(bag):
                if isinstance(item, dict) and not item.get("locked", False) and _safe_int(item.get("rarity"), 1) <= 2:
                    picked_idx = idx
                    break
            if picked_idx is None:
                return False, "❌ 먹이로 줄 수 있는 **미잠금 ★1~★2 물고기**가 없습니다! (전설·잠금 어종은 보호됨)"
            fish_item = bag.pop(picked_idx)
            consumed_label = f"🐟 {fish_item.get('name', '생선')}"
            gain_exp = 32 if _safe_int(fish_item.get("rarity"), 1) == 1 else 52
            gain_int = 5
        else:
            if lu.get("pet_food", 0) <= 0:
                return False, "❌ 보유한 펫 간식이 없습니다! (`🦴 간식 구매` 또는 `🐟 생선 먹이기`를 이용해 주세요.)"
            lu["pet_food"] -= 1
            consumed_label = "🦴 펫 간식"
            gain_exp = 35
            gain_int = 6

        old_lvl = pu["level"]
        pu["exp"] += gain_exp
        pu["intimacy"] = pu.get("intimacy", 0) + gain_int
        new_lvl, _, _ = _calc_pet_level(pu["exp"])
        pu["level"] = new_lvl
        core.save_data(data)

        lvl_txt = f" 🎊 **Lv.{new_lvl} 성장!**" if new_lvl > old_lvl else ""
        return True, f"{pm['emoji']} **{pm['name']}**에게 `{consumed_label}`을(를) 주었습니다! (`+{gain_exp} EXP` · 친밀도 `+{gain_int}`){lvl_txt}"


def play_pet(
    guild_id: int | str,
    user_id: int | str,
    pet_id: Optional[str] = None,
    user_name: str = "",
) -> Tuple[bool, str]:
    today = core.get_today_str()
    with _LIFE_LOCK:
        data = core.load_data()
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        target_id = pet_id or lu.get("equipped_pet")
        if not target_id or target_id not in lu["pets"]:
            return False, "❌ 놀아줄 펫이 없습니다. 먼저 펫을 입양해 주세요!"

        pu = lu["pets"][target_id]
        pm = PETS[target_id]
        if pu.get("play_date") != today:
            pu["play_date"] = today
            pu["play_count"] = 0
        if pu.get("play_count", 0) >= 5:
            return False, f"😴 **{pm['name']}**이(가) 오늘 너무 신나게 놀아서 쉬고 있어요! (일일 5회 완료)"

        pu["play_count"] += 1
        old_lvl = pu["level"]
        pu["exp"] += 22
        pu["intimacy"] = pu.get("intimacy", 0) + 8
        new_lvl, _, _ = _calc_pet_level(pu["exp"])
        pu["level"] = new_lvl

        prof = core.ensure_user_profile(data, user_id, user_name)
        bonus_gold = 35 + new_lvl * 5
        bonus_cry = 5 if pu["play_count"] == 1 else 0
        _add_guild_gold(data, guild_id, user_id, bonus_gold, user_name)
        if bonus_cry > 0:
            prof["crystals"] = max(0, _safe_int(prof.get("crystals"), 0)) + bonus_cry

        core.save_data(data)
        extra = f" · `+{bonus_cry}💎`" if bonus_cry > 0 else ""
        lvl_txt = f" 🎊 **Lv.{new_lvl} 성장!**" if new_lvl > old_lvl else ""
        return (
            True,
            f"🎾 **{pm['name']}**와(과) 즐겁게 놀아주었습니다! (`{pu['play_count']}/5회` · `+22 EXP` · `+{bonus_gold}🪙`{extra}){lvl_txt}",
        )


# ==========================================
# 생선 요리 & 버프 활성화
# ==========================================
def cook_recipe(
    guild_id: int | str,
    user_id: int | str,
    recipe_id: str,
    qty: int = 1,
    user_name: str = "",
) -> Tuple[bool, str]:
    rec = RECIPES.get(recipe_id)
    if not rec:
        return False, "❌ 존재하지 않는 요리 레시피입니다."
    qty = max(1, min(10, int(qty)))

    with _LIFE_LOCK:
        data = core.load_data()
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        f_g_map = core.ensure_dict_path(data, "fishing_users", str(guild_id or 0))
        fu = f_g_map.get(str(user_id))
        bag = fu.get("bag") if isinstance(fu, dict) and isinstance(fu.get("bag"), list) else []

        # 농작물 재료 검증
        for cid, need_c in rec["crop_reqs"].items():
            have_c = lu["crops"].get(cid, 0)
            if have_c < need_c * qty:
                return False, f"❌ 농작물 재료 부족: **{SEEDS[cid]['emoji']} {SEEDS[cid]['name']}** (필요 `{need_c * qty}개` / 보유 `{have_c}개`)"

        need_r2 = rec["need_fish_r2"] * qty
        need_r1 = rec["need_fish_r1"] * qty

        # 미잠금 ★2 후보, 미잠금 ★1~2 후보 분리 선별 (가장 저렴한 물고기부터 소모)
        unlocked_r2 = sorted(
            [(idx, it) for idx, it in enumerate(bag) if isinstance(it, dict) and not it.get("locked", False) and _safe_int(it.get("rarity"), 1) == 2],
            key=lambda x: _safe_int(x[1].get("gold"), 0),
        )
        if len(unlocked_r2) < need_r2:
            return False, f"❌ 미잠금 **★2 물고기**가 부족합니다! (필요 `{need_r2}마리` / 보유 `{len(unlocked_r2)}마리`)"

        chosen_indices = {idx for idx, _ in unlocked_r2[:need_r2]}
        unlocked_r1_or_2 = sorted(
            [
                (idx, it)
                for idx, it in enumerate(bag)
                if isinstance(it, dict)
                and not it.get("locked", False)
                and _safe_int(it.get("rarity"), 1) in (1, 2)
                and idx not in chosen_indices
            ],
            key=lambda x: (_safe_int(x[1].get("rarity"), 1), _safe_int(x[1].get("gold"), 0)),
        )
        if len(unlocked_r1_or_2) < need_r1:
            return False, f"❌ 미잠금 **★1~★2 물고기**가 부족합니다! (필요 `{need_r1}마리` / 남은 보유 `{len(unlocked_r1_or_2)}마리`)"

        for idx, _ in unlocked_r1_or_2[:need_r1]:
            chosen_indices.add(idx)

        consumed_fish_names: List[str] = []
        if chosen_indices and isinstance(fu, dict):
            new_bag = []
            for idx, it in enumerate(bag):
                if idx in chosen_indices:
                    consumed_fish_names.append(it.get("name", "물고기"))
                else:
                    new_bag.append(it)
            fu["bag"] = new_bag

        for cid, need_c in rec["crop_reqs"].items():
            lu["crops"][cid] = lu["crops"].get(cid, 0) - need_c * qty
            if lu["crops"][cid] <= 0:
                lu["crops"].pop(cid, None)

        lu["dishes"][recipe_id] = lu["dishes"].get(recipe_id, 0) + qty
        lu["total_cooked"] = lu.get("total_cooked", 0) + qty
        core.save_data(data)

        fish_note = f" (재료 생선: {', '.join(consumed_fish_names[:3])})" if consumed_fish_names else ""
        return True, f"🍳 {rec['emoji']} **{rec['name']} ×{qty}개** 조리 완료!{fish_note} (보유 `{lu['dishes'][recipe_id]}개`)"


def consume_dish(
    guild_id: int | str,
    user_id: int | str,
    recipe_id: str,
    user_name: str = "",
) -> Tuple[bool, str]:
    rec = RECIPES.get(recipe_id)
    if not rec:
        return False, "❌ 알 수 없는 요리입니다."

    with _LIFE_LOCK:
        data = core.load_data()
        lu = ensure_life_user(data, guild_id, user_id, user_name)
        have = lu["dishes"].get(recipe_id, 0)
        if have <= 0:
            return False, f"❌ 보유한 **{rec['name']}** 요리가 없습니다! 먼저 조리해 주세요."

        lu["dishes"][recipe_id] = have - 1
        if lu["dishes"][recipe_id] <= 0:
            lu["dishes"].pop(recipe_id, None)

        now_ts = time.time()
        dur_sec = rec["duration_min"] * 60.0
        buff_entry = {
            "recipe_id": recipe_id,
            "name": rec["name"],
            "emoji": rec["emoji"],
            "expires_at": now_ts + dur_sec,
            **rec["buffs"],
        }

        existing = [b for b in lu["active_buffs"] if isinstance(b, dict) and b.get("recipe_id") != recipe_id and _safe_float(b.get("expires_at"), 0.0) > now_ts]
        existing.append(buff_entry)
        lu["active_buffs"] = existing[-3:]  # 최대 3종 동시 버프 유지
        core.save_data(data)

        return True, f"🍽️ {rec['emoji']} **{rec['name']}**을(를) 맛있게 먹었습니다! (`{rec['desc']}`)"
