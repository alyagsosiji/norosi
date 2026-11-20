"""
routine_core.py — 통합 일일 루틴 · 주간 미션 · 크리스탈⇄골드 환전소 ·
파트너 농장 시너지 · 통합 수집품 쇼케이스 · 즉석 미니 대전(주사위/초성퀴즈) 코어 엔진
"""

from __future__ import annotations

import datetime
import random
import time
from typing import Any, Dict, List, Optional, Tuple

import core
import fishing_core
import life_core

# ==========================================
# 상수 & 밸런스 설정
# ==========================================
DAILY_ROUTINE_MIN_COMPLETE = 3
DAILY_ROUTINE_BONUS_CRYSTALS = 150
DAILY_ROUTINE_BONUS_GOLD = 300

EXCHANGE_DAILY_LIMIT = 3
EXCHANGE_GOLD_TO_CRYSTAL_COST = 500
EXCHANGE_GOLD_TO_CRYSTAL_GAIN = 100
EXCHANGE_CRYSTAL_TO_GOLD_COST = 100
EXCHANGE_CRYSTAL_TO_GOLD_GAIN = 450

PARTNER_WATER_BONUS_CRYSTALS = 50
PARTNER_WATER_BONUS_GOLD = 100

CHOSUNG_DAILY_REWARD_CAP = 10
CHOSUNG_REWARD_CRYSTALS = 30

# ==========================================
# 초성 퀴즈 단어 DB (카테고리별 72종)
# ==========================================
CHOSUNG_WORDS: List[Tuple[str, str]] = [
    # 게임 / 서브컬처
    ("프로세카", "하츠네 미쿠"), ("프로세카", "원더랜즈 쇼타임"), ("프로세카", "나이트코드"),
    ("프로세카", "비비드 배드 스쿼드"), ("프로세카", "모어 모어 점프"), ("프로세카", "레오니드"),
    ("프로세카", "마스터 랭크"), ("프로세카", "버츄얼 싱어"), ("프로세카", "컬러풀 페스"),
    ("원신", "몬드성"), ("원신", "리월항"), ("원신", "이나즈마"), ("원신", "수메르"),
    ("원신", "폰타인"), ("원신", "나타"), ("원신", "운명의 궤도"), ("원신", "성유물"),
    ("스타레일", "은하열차"), ("스타레일", "야릴로"), ("스타레일", "선주 나부"),
    ("스타레일", "페나코니"), ("스타레일", "개척자"), ("스타레일", "시뮬레이션 우주"),
    # 음식
    ("음식", "김치찌개"), ("음식", "떡볶이"), ("음식", "삼겹살"), ("음식", "치킨무"),
    ("음식", "불고기"), ("음식", "된장찌개"), ("음식", "비빔밥"), ("음식", "짜장면"),
    ("음식", "탕수육"), ("음식", "돈까스"), ("음식", "아메리카노"), ("음식", "마라탕"),
    ("음식", "크루아상"), ("음식", "타코야키"), ("음식", "오므라이스"), ("음식", "김밥천국"),
    # 일상 / 사물
    ("일상", "스마트폰"), ("일상", "무선이어폰"), ("일상", "보조배터리"), ("일상", "기계식키보드"),
    ("일상", "아이스팩"), ("일상", "알람시계"), ("일상", "텀블러"), ("일상", "지하철역"),
    ("일상", "편의점"), ("일상", "도서관"), ("일상", "우산꽂이"), ("일상", "노트북"),
    # 자연 / 동물
    ("자연·동물", "고래상어"), ("자연·동물", "북극곰"), ("자연·동물", "레서판다"),
    ("자연·동물", "해바라기"), ("자연·동물", "은하수"), ("자연·동물", "오로라"),
    ("자연·동물", "사막여우"), ("자연·동물", "황제펭귄"), ("자연·동물", "무지개"),
    # 취미 / 문화
    ("문화·취미", "플레이리스트"), ("문화·취미", "콘서트홀"), ("문화·취미", "사진작가"),
    ("문화·취미", "보드게임"), ("문화·취미", "타임캡슐"), ("문화·취미", "마라톤"),
    ("문화·취미", "웹소설"), ("문화·취미", "애니메이션"), ("문화·취미", "미니게임"),
    ("문화·취미", "수족관"), ("문화·취미", "낚시터"), ("문화·취미", "공동농장"),
]

_CHOSUNG_LIST = [
    "ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ", "ㅅ",
    "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
]


def extract_chosung(text: str) -> str:
    """한글 문자열에서 초성을 추출합니다 (공백 유지)."""
    out: List[str] = []
    for ch in text:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            idx = (code - 0xAC00) // 588
            out.append(_CHOSUNG_LIST[idx])
        elif ch == " ":
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def pick_chosung_question(exclude: Optional[set] = None) -> Dict[str, str]:
    pool = [item for item in CHOSUNG_WORDS if not exclude or item[1] not in exclude]
    if not pool:
        pool = CHOSUNG_WORDS
    cat, answer = random.choice(pool)
    return {
        "category": cat,
        "answer": answer,
        "chosung": extract_chosung(answer),
        "length": str(len(answer.replace(" ", ""))),
    }


def get_kst_week_key(now: Optional[datetime.datetime] = None) -> str:
    dt = now or datetime.datetime.now(core.KST)
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _get_kst_week_dates(now: Optional[datetime.datetime] = None) -> List[str]:
    dt = now or datetime.datetime.now(core.KST)
    monday = dt - datetime.timedelta(days=dt.weekday())
    return [(monday + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def _ensure_routine_bucket(profile: dict) -> dict:
    rb = profile.get("routine_state")
    if not isinstance(rb, dict):
        rb = {}
        profile["routine_state"] = rb
    return rb


def record_weekly_activity(data: dict, user_id: int, user_name: str, key: str, delta: int = 1) -> None:
    """주간 미션 활동 카운터를 누적합니다 (이미 로드된 data 딕셔너리 내부 갱신)."""
    prof = core.ensure_user_profile(data, user_id, user_name)
    rb = _ensure_routine_bucket(prof)
    wk = get_kst_week_key()
    wmap = rb.setdefault("weekly", {})
    wcur = wmap.setdefault(wk, {"claimed": [], "counts": {}})
    counts = wcur.setdefault("counts", {})
    counts[key] = int(counts.get(key, 0) or 0) + int(delta)


# ==========================================
# 1. 오늘의 일일 루틴 통합 상태 & 일괄 수령
# ==========================================
def get_daily_routine_status(guild_id: int, user_id: int, user_name: str = "유저") -> Dict[str, Any]:
    data = core.load_data()
    today = core.get_today_str()
    g_key = str(guild_id or 0)
    u_key = str(user_id)
    now_ts = time.time()

    prof = core.ensure_user_profile(data, user_id, user_name)
    rb = _ensure_routine_bucket(prof)

    # 1) 출석체크
    g_att = core.safe_get_dict(data, "guild_attendance", g_key, u_key) if guild_id else core.as_dict(prof.get("attendance"))
    att_done = (g_att.get("last_date") == today)
    att_streak = int(g_att.get("streak", 0) or 0)

    # 2) 낚시 일일 의뢰
    fu = fishing_core.ensure_fishing_user(data, guild_id, user_id, user_name)
    dq = core.as_dict(fu.get("daily_quests"))
    q_items = [q for q in (dq.get("items") or []) if isinstance(q, dict)]
    q_claimed = sum(1 for q in q_items if q.get("claimed"))
    q_claimable = sum(1 for q in q_items if not q.get("claimed") and int(q.get("progress", 0) or 0) >= int(q.get("target", 1) or 1))
    q_done = (len(q_items) > 0 and (q_claimed + q_claimable) >= len(q_items))

    # 3) 개인 농장
    lu = life_core.ensure_life_user(data, guild_id, user_id, user_name)
    plots = [p for p in (lu.get("plots") or []) if isinstance(p, dict)]
    farm_ready = sum(1 for p in plots if p.get("seed_id") and float(p.get("ready_at", 0) or 0) <= now_ts)
    farm_growing = sum(1 for p in plots if p.get("seed_id") and float(p.get("ready_at", 0) or 0) > now_ts)
    farm_need_water = sum(1 for p in plots if p.get("seed_id") and float(p.get("ready_at", 0) or 0) > now_ts and not p.get("watered"))
    farm_done = (farm_growing > 0 and farm_ready == 0 and farm_need_water == 0)

    # 4) 서버 공동농장 일일 배당금
    gf = life_core.ensure_guild_farm(data, guild_id)
    gf_claimed = (lu.get("last_guild_farm_claim") == today)
    gf_can_claim = (not gf_claimed) and (int(gf.get("exp", 0) or 0) > 0 or int(gf.get("level", 1) or 1) > 1)

    # 5) 프로세카 일일 운명 다시뽑기
    ug = core.safe_get_dict(data, "gacha_users", g_key, u_key)
    destiny_done = (ug.get("last_destiny_date") == today or ug.get("destiny_reroll_date") == today)

    # 6) 오늘의 목표 잔디
    todo = core.ensure_user_todo_today(prof)
    t_list = [t for t in (todo.get("tasks") or []) if isinstance(t, dict)]
    t_done_cnt = sum(1 for t in t_list if t.get("done"))
    t_done = (len(t_list) > 0 and t_done_cnt >= len(t_list))

    # 7) 파트너 농장 물주기 여부
    partner_id = prof.get("partner_id")
    partner_watered = (rb.get("last_partner_water_date") == today)

    items = [
        {
            "key": "attendance",
            "emoji": "📅",
            "name": "일일 출석체크",
            "done": att_done,
            "detail": f"완료 (연속 {att_streak}일 🔥)" if att_done else "미완료 — 지금 출석하고 크리스탈 받기!",
            "claimable": False,
        },
        {
            "key": "fishing_quest",
            "emoji": "🎣",
            "name": "낚시 일일 의뢰 (3종)",
            "done": q_done,
            "detail": (
                f"🎁 수령 가능 {q_claimable}건!" if q_claimable > 0
                else (f"전체 완료 ({q_claimed}/{len(q_items)})" if q_done else f"진행 중 ({q_claimed}/{len(q_items)} 수령)")
            ),
            "claimable": q_claimable > 0,
        },
        {
            "key": "personal_farm",
            "emoji": "🌾",
            "name": "개인 농장 관리",
            "done": farm_done,
            "detail": (
                f"🧺 수확 가능 {farm_ready}칸" + (f" · 💧물 필요 {farm_need_water}칸" if farm_need_water else "")
                if farm_ready > 0
                else (f"💧 물주기 필요 {farm_need_water}칸" if farm_need_water > 0 else (f"🌱 성장 중 {farm_growing}칸 (관리 완료)" if farm_growing > 0 else "🟫 빈 밭 — 씨앗을 심어보세요"))
            ),
            "claimable": farm_ready > 0 or farm_need_water > 0,
        },
        {
            "key": "guild_farm",
            "emoji": "🏡",
            "name": "서버 공동농장 배당금",
            "done": gf_claimed,
            "detail": "오늘 배당금 수령 완료" if gf_claimed else ("🎁 오늘 배당금 수령 가능!" if gf_can_claim else "공동농장에 물주기로 첫 기여 필요"),
            "claimable": gf_can_claim,
        },
        {
            "key": "sekai_destiny",
            "emoji": "🔮",
            "name": "프로세카 일일 운명 뽑기",
            "done": destiny_done,
            "detail": "오늘 1회 사용 완료" if destiny_done else "미사용 (1일 1회 · 3세트 중 택1)",
            "claimable": False,
        },
        {
            "key": "todo",
            "emoji": "🌱",
            "name": "오늘의 목표 & 잔디",
            "done": t_done,
            "detail": f"목표 완료 ({t_done_cnt}/{len(t_list)})" if t_list else "등록된 목표 없음",
            "claimable": False,
        },
    ]

    completed_cnt = sum(1 for it in items if it["done"])
    bonus_claimed = (rb.get("last_daily_bonus_date") == today)
    bonus_eligible = (completed_cnt >= DAILY_ROUTINE_MIN_COMPLETE) and (not bonus_claimed)

    return {
        "today": today,
        "user_name": user_name,
        "crystals": int(prof.get("crystals", 0) or 0),
        "gold": int(fu.get("gold", 0) or 0),
        "items": items,
        "completed_cnt": completed_cnt,
        "total_cnt": len(items),
        "bonus_claimed": bonus_claimed,
        "bonus_eligible": bonus_eligible,
        "partner_id": partner_id,
        "partner_watered": partner_watered,
    }


def bulk_claim_daily_rewards(guild_id: int, user_id: int, user_name: str = "유저") -> Tuple[bool, List[str]]:
    """현재 즉시 수령 가능한 보상(낚시 의뢰 + 농장 수확/물주기 + 공동농장 배당금 + 일일 루틴 완주 보너스)을 한 번에 처리합니다."""
    logs: List[str] = []

    # 1) 낚시 완료 의뢰 일괄 수령
    q_ok, q_msg, q_gold, q_cry = fishing_core.claim_all_completed_quests(guild_id, user_id, user_name)
    if q_ok:
        logs.append(f"🎣 낚시 의뢰 보상: `+{q_gold:,}🪙` `+{q_cry:,}💎`")

    # 2) 개인 농장 수확 + 물주기
    h_ok, h_msg, _ = life_core.harvest_plots(guild_id, user_id, user_name)
    if h_ok:
        logs.append(f"🌾 개인 농장: {h_msg}")
    w_ok, w_msg = life_core.water_farm_plot(guild_id, user_id, None, user_name)
    if w_ok:
        logs.append(f"💧 개인 농장: {w_msg}")

    # 3) 서버 공동농장 배당금 수령
    gf_ok, gf_msg = life_core.claim_community_farm_daily(guild_id, user_id, user_name)
    if gf_ok:
        logs.append(f"🏡 공동농장: {gf_msg}")

    # 4) 일일 루틴 완주 보너스 (3개 이상 완료 시 1일 1회)
    st = get_daily_routine_status(guild_id, user_id, user_name)
    if st["bonus_eligible"]:
        data = core.load_data()
        prof = core.ensure_user_profile(data, user_id, user_name)
        fu = fishing_core.ensure_fishing_user(data, guild_id, user_id, user_name)
        rb = _ensure_routine_bucket(prof)
        today = core.get_today_str()
        if rb.get("last_daily_bonus_date") != today:
            rb["last_daily_bonus_date"] = today
            prof["crystals"] = int(prof.get("crystals", 0) or 0) + DAILY_ROUTINE_BONUS_CRYSTALS
            fu["gold"] = int(fu.get("gold", 0) or 0) + DAILY_ROUTINE_BONUS_GOLD
            record_weekly_activity(data, user_id, user_name, "daily_bonus", 1)
            core.save_data(data)
            logs.append(
                f"☀️ **일일 루틴 완주 보너스({st['completed_cnt']}/{st['total_cnt']}):** "
                f"`+{DAILY_ROUTINE_BONUS_CRYSTALS:,}💎` `+{DAILY_ROUTINE_BONUS_GOLD:,}🪙`"
            )

    if not logs:
        return False, ["ℹ️ 현재 즉시 수령하거나 처리할 일일 보상이 없습니다. (출석·낚시·농장 활동 후 다시 눌러주세요!)"]
    return True, logs


# ==========================================
# 2. 크리스탈 ⇄ 낚시 골드 환전소 (일일 한도)
# ==========================================
def get_exchange_state(guild_id: int, user_id: int, user_name: str = "유저") -> Dict[str, Any]:
    data = core.load_data()
    today = core.get_today_str()
    prof = core.ensure_user_profile(data, user_id, user_name)
    fu = fishing_core.ensure_fishing_user(data, guild_id, user_id, user_name)
    rb = _ensure_routine_bucket(prof)
    ex = rb.get("exchange")
    if not isinstance(ex, dict) or ex.get("date") != today:
        ex = {"date": today, "g2c": 0, "c2g": 0}
    return {
        "today": today,
        "crystals": int(prof.get("crystals", 0) or 0),
        "gold": int(fu.get("gold", 0) or 0),
        "g2c_used": int(ex.get("g2c", 0) or 0),
        "c2g_used": int(ex.get("c2g", 0) or 0),
        "limit": EXCHANGE_DAILY_LIMIT,
    }


def exchange_currency(guild_id: int, user_id: int, direction: str, user_name: str = "유저") -> Tuple[bool, str]:
    """direction: 'gold_to_crystal' | 'crystal_to_gold'"""
    data = core.load_data()
    today = core.get_today_str()
    prof = core.ensure_user_profile(data, user_id, user_name)
    fu = fishing_core.ensure_fishing_user(data, guild_id, user_id, user_name)
    rb = _ensure_routine_bucket(prof)
    ex = rb.get("exchange")
    if not isinstance(ex, dict) or ex.get("date") != today:
        ex = {"date": today, "g2c": 0, "c2g": 0}
        rb["exchange"] = ex

    crystals = int(prof.get("crystals", 0) or 0)
    gold = int(fu.get("gold", 0) or 0)

    if direction == "gold_to_crystal":
        if int(ex.get("g2c", 0) or 0) >= EXCHANGE_DAILY_LIMIT:
            return False, f"⏳ 오늘 **골드 ➔ 크리스탈** 환전 한도(`{EXCHANGE_DAILY_LIMIT}회`)를 모두 사용했습니다. 내일 자정(KST)에 초기화됩니다."
        if gold < EXCHANGE_GOLD_TO_CRYSTAL_COST:
            return False, f"❌ 낚시 골드가 부족합니다. (필요 `{EXCHANGE_GOLD_TO_CRYSTAL_COST:,}🪙` · 보유 `{gold:,}🪙`)"
        fu["gold"] = gold - EXCHANGE_GOLD_TO_CRYSTAL_COST
        prof["crystals"] = crystals + EXCHANGE_GOLD_TO_CRYSTAL_GAIN
        ex["g2c"] = int(ex.get("g2c", 0) or 0) + 1
        record_weekly_activity(data, user_id, user_name, "exchange", 1)
        core.save_data(data)
        return True, (
            f"✅ 환전 완료! **`{EXCHANGE_GOLD_TO_CRYSTAL_COST:,}🪙`** ➔ **`+{EXCHANGE_GOLD_TO_CRYSTAL_GAIN:,}💎`** "
            f"(잔액: `{fu['gold']:,}🪙` · `{prof['crystals']:,}💎` · 오늘 `{ex['g2c']}/{EXCHANGE_DAILY_LIMIT}회`)"
        )

    if direction == "crystal_to_gold":
        if int(ex.get("c2g", 0) or 0) >= EXCHANGE_DAILY_LIMIT:
            return False, f"⏳ 오늘 **크리스탈 ➔ 골드** 환전 한도(`{EXCHANGE_DAILY_LIMIT}회`)를 모두 사용했습니다. 내일 자정(KST)에 초기화됩니다."
        if crystals < EXCHANGE_CRYSTAL_TO_GOLD_COST:
            return False, f"❌ 크리스탈이 부족합니다. (필요 `{EXCHANGE_CRYSTAL_TO_GOLD_COST:,}💎` · 보유 `{crystals:,}💎`)"
        prof["crystals"] = crystals - EXCHANGE_CRYSTAL_TO_GOLD_COST
        fu["gold"] = gold + EXCHANGE_CRYSTAL_TO_GOLD_GAIN
        ex["c2g"] = int(ex.get("c2g", 0) or 0) + 1
        record_weekly_activity(data, user_id, user_name, "exchange", 1)
        core.save_data(data)
        return True, (
            f"✅ 환전 완료! **`{EXCHANGE_CRYSTAL_TO_GOLD_COST:,}💎`** ➔ **`+{EXCHANGE_CRYSTAL_TO_GOLD_GAIN:,}🪙`** "
            f"(잔액: `{prof['crystals']:,}💎` · `{fu['gold']:,}🪙` · 오늘 `{ex['c2g']}/{EXCHANGE_DAILY_LIMIT}회`)"
        )

    return False, "❌ 알 수 없는 환전 방향입니다."


# ==========================================
# 3. 통합 주간 미션 (ISO 주간 KST 자동 리셋)
# ==========================================
WEEKLY_MISSION_DEFS = [
    {"id": "w_att", "emoji": "📅", "title": "이번 주 출석 3일 달성", "target": 3, "crystals": 250, "gold": 0},
    {"id": "w_fish", "emoji": "🎣", "title": "낚시 누적 포획 10마리 이상", "target": 10, "crystals": 150, "gold": 400},
    {"id": "w_farm", "emoji": "🌾", "title": "농장 수확·생활 활동 달성", "target": 3, "crystals": 150, "gold": 350},
    {"id": "w_collect", "emoji": "✨", "title": "3대 가챠 도감 15종 이상 보유", "target": 15, "crystals": 200, "gold": 0},
    {"id": "w_all", "emoji": "🏆", "title": "주간 미션 3개 이상 달성 (올클리어)", "target": 3, "crystals": 300, "gold": 500},
]


def _compute_weekly_progress(data: dict, guild_id: int, user_id: int, user_name: str) -> Dict[str, Any]:
    wk = get_kst_week_key()
    week_dates = set(_get_kst_week_dates())
    g_key = str(guild_id or 0)
    u_key = str(user_id)

    prof = core.ensure_user_profile(data, user_id, user_name)
    rb = _ensure_routine_bucket(prof)
    wmap = rb.setdefault("weekly", {})
    wcur = wmap.setdefault(wk, {"claimed": [], "counts": {}})
    claimed = set(wcur.get("claimed") or [])

    # 1) 이번 주 출석 일수
    g_att = core.safe_get_dict(data, "guild_attendance", g_key, u_key) if guild_id else core.as_dict(prof.get("attendance"))
    att_dates = set(g_att.get("dates") or [])
    if g_att.get("last_date"):
        att_dates.add(g_att["last_date"])
    w_att_cnt = len(att_dates & week_dates)

    # 2) 낚시 포획 수 (누적 + 주간 스냅샷 대비 또는 누적 기준)
    fu = fishing_core.ensure_fishing_user(data, guild_id, user_id, user_name)
    total_catches = int(fu.get("total_catches", 0) or 0)
    base_catches = wcur.get("base_catches")
    if base_catches is None:
        # 첫 주간 진입 시 기존 유저는 현재 누적의 일부를 즉시 반영하되, 신규 기준점 기록
        base_catches = max(0, total_catches - min(total_catches, 10))
        wcur["base_catches"] = base_catches
    w_fish_cnt = max(0, total_catches - int(base_catches))

    # 3) 농장/생활 활동 (농장 레벨/수확/물주기/일일 보너스/파트너 물주기 종합)
    lu = life_core.ensure_life_user(data, guild_id, user_id, user_name)
    farm_harvests = int(lu.get("total_harvests", 0) or 0)
    base_harvests = wcur.get("base_harvests")
    if base_harvests is None:
        base_harvests = max(0, farm_harvests - min(farm_harvests, 3))
        wcur["base_harvests"] = base_harvests
    counts = wcur.get("counts") or {}
    w_farm_cnt = max(0, farm_harvests - int(base_harvests)) + int(counts.get("partner_water", 0) or 0) + int(counts.get("daily_bonus", 0) or 0)

    # 4) 3대 가챠 통합 도감 수집 수
    sekai_cnt = len(core.safe_get_dict(data, "gacha_users", g_key, u_key, "cards"))
    gi_cnt = len(core.as_dict(core.safe_get_dict(data, "genshin_users", g_key, u_key).get("items")))
    hsr_cnt = len(core.as_dict(core.safe_get_dict(data, "hsr_users", g_key, u_key).get("items")))
    total_collect = sekai_cnt + gi_cnt + hsr_cnt

    prog_map = {
        "w_att": w_att_cnt,
        "w_fish": w_fish_cnt,
        "w_farm": w_farm_cnt,
        "w_collect": total_collect,
    }
    done_base = sum(1 for m in WEEKLY_MISSION_DEFS[:4] if prog_map[m["id"]] >= m["target"])
    prog_map["w_all"] = done_base

    missions = []
    for m in WEEKLY_MISSION_DEFS:
        cur = min(m["target"], int(prog_map[m["id"]]))
        is_done = cur >= m["target"]
        is_claimed = m["id"] in claimed
        missions.append({
            **m,
            "current": cur,
            "done": is_done,
            "claimed": is_claimed,
            "claimable": is_done and not is_claimed,
        })

    return {
        "week_key": wk,
        "user_name": user_name,
        "crystals": int(prof.get("crystals", 0) or 0),
        "gold": int(fu.get("gold", 0) or 0),
        "missions": missions,
        "claimable_cnt": sum(1 for m in missions if m["claimable"]),
        "done_cnt": sum(1 for m in missions if m["done"]),
    }


def get_weekly_mission_status(guild_id: int, user_id: int, user_name: str = "유저") -> Dict[str, Any]:
    data = core.load_data()
    return _compute_weekly_progress(data, guild_id, user_id, user_name)


def claim_weekly_missions(guild_id: int, user_id: int, user_name: str = "유저") -> Tuple[bool, str]:
    data = core.load_data()
    st = _compute_weekly_progress(data, guild_id, user_id, user_name)
    claimables = [m for m in st["missions"] if m["claimable"]]
    if not claimables:
        return False, "ℹ️ 현재 수령 가능한 완료 주간 미션이 없습니다."

    prof = core.ensure_user_profile(data, user_id, user_name)
    fu = fishing_core.ensure_fishing_user(data, guild_id, user_id, user_name)
    rb = _ensure_routine_bucket(prof)
    wk = st["week_key"]
    wcur = rb.setdefault("weekly", {}).setdefault(wk, {"claimed": [], "counts": {}})
    claimed_list = list(wcur.get("claimed") or [])

    tot_c = 0
    tot_g = 0
    names = []
    for m in claimables:
        if m["id"] not in claimed_list:
            claimed_list.append(m["id"])
            tot_c += int(m["crystals"])
            tot_g += int(m["gold"])
            names.append(f"{m['emoji']} {m['title']}")

    wcur["claimed"] = claimed_list
    prof["crystals"] = int(prof.get("crystals", 0) or 0) + tot_c
    fu["gold"] = int(fu.get("gold", 0) or 0) + tot_g
    core.save_data(data)

    reward_parts = []
    if tot_c:
        reward_parts.append(f"**`+{tot_c:,}💎`**")
    if tot_g:
        reward_parts.append(f"**`+{tot_g:,}🪙`**")
    return True, f"🎉 주간 미션 `{len(names)}종` 보상 수령 완료! ({' · '.join(reward_parts)})\n" + "\n".join(f"• {n}" for n in names)


# ==========================================
# 4. 파트너 시너지 — 파트너 농장 대신 물주기
# ==========================================
def water_partner_farm(guild_id: int, user_id: int, user_name: str = "유저") -> Tuple[bool, str]:
    data = core.load_data()
    today = core.get_today_str()
    prof = core.ensure_user_profile(data, user_id, user_name)
    partner_id = prof.get("partner_id")
    if not partner_id:
        return False, "💔 등록된 파트너가 없습니다. `/설정` (`👤 개인` ➔ `💑 내 생일 & 파트너`)에서 파트너를 먼저 맺어보세요!"

    rb = _ensure_routine_bucket(prof)
    if rb.get("last_partner_water_date") == today:
        return False, "💧 오늘은 이미 파트너의 농장에 물을 주었습니다! 내일 다시 도와줄 수 있어요."

    p_uid = int(partner_id)
    p_prof = core.ensure_user_profile(data, p_uid, f"파트너({p_uid})")
    p_name = p_prof.get("name") or f"<@{p_uid}>"

    # 파트너 농장에 물주기 적용
    w_ok, w_msg = life_core.water_farm_plot(guild_id, p_uid, None, p_name)

    # 우정 보너스 지급 (양쪽 모두!)
    data = core.load_data()
    prof = core.ensure_user_profile(data, user_id, user_name)
    p_prof = core.ensure_user_profile(data, p_uid, p_name)
    fu_me = fishing_core.ensure_fishing_user(data, guild_id, user_id, user_name)
    fu_pt = fishing_core.ensure_fishing_user(data, guild_id, p_uid, p_name)

    rb = _ensure_routine_bucket(prof)
    rb["last_partner_water_date"] = today

    prof["crystals"] = int(prof.get("crystals", 0) or 0) + PARTNER_WATER_BONUS_CRYSTALS
    fu_me["gold"] = int(fu_me.get("gold", 0) or 0) + PARTNER_WATER_BONUS_GOLD
    p_prof["crystals"] = int(p_prof.get("crystals", 0) or 0) + PARTNER_WATER_BONUS_CRYSTALS
    fu_pt["gold"] = int(fu_pt.get("gold", 0) or 0) + PARTNER_WATER_BONUS_GOLD

    record_weekly_activity(data, user_id, user_name, "partner_water", 1)
    core.save_data(data)

    water_note = "파트너의 성장 중인 밭에 물을 주었습니다!" if w_ok else "파트너의 농장을 응원 방문했습니다! *(현재 물이 필요한 작물은 없었지만 우정 보너스가 지급됩니다)*"
    return True, (
        f"💑 **{water_note}**\n"
        f"• 나 & <@{p_uid}> 모두 우정 보너스 **`+{PARTNER_WATER_BONUS_CRYSTALS}💎` · `+{PARTNER_WATER_BONUS_GOLD}🪙`** 획득!"
    )


# ==========================================
# 5. 통합 수집품 쇼케이스 요약 빌더
# ==========================================
def build_showcase_data(guild_id: int, user_id: int, user_name: str = "유저") -> Dict[str, Any]:
    data = core.load_data()
    g_key = str(guild_id or 0)
    u_key = str(user_id)
    prof = core.ensure_user_profile(data, user_id, user_name)

    # 1) 프로세카 5인 덱 & 최강 카드
    ug = core.safe_get_dict(data, "gacha_users", g_key, u_key)
    cards_dict = core.as_dict(ug.get("cards"))
    deck_ids = [str(x) for x in (prof.get("deck") or [])]
    deck_cards = [cards_dict[cid] for cid in deck_ids if cid in cards_dict and isinstance(cards_dict[cid], dict)]
    all_cards = [c for c in cards_dict.values() if isinstance(c, dict)]
    all_cards.sort(key=lambda c: -core.get_card_power(c))
    deck_power = sum(core.get_card_power(c) for c in deck_cards)

    # 2) 원신 4인 파티 & 보유 요약
    gi_u = core.safe_get_dict(data, "genshin_users", g_key, u_key)
    gi_items = core.as_dict(gi_u.get("items"))
    gi_party_keys = [str(x) for x in (gi_u.get("party") or [])]
    gi_party = [gi_items[k] for k in gi_party_keys if k in gi_items and isinstance(gi_items[k], dict)]
    gi_r5 = sum(1 for v in gi_items.values() if isinstance(v, dict) and int(v.get("rank", 0) or 0) == 5)

    # 3) 스타레일 4인 편대 & 보유 요약
    hsr_u = core.safe_get_dict(data, "hsr_users", g_key, u_key)
    hsr_items = core.as_dict(hsr_u.get("items"))
    hsr_party_keys = [str(x) for x in (hsr_u.get("party") or [])]
    hsr_party = [hsr_items[k] for k in hsr_party_keys if k in hsr_items and isinstance(hsr_items[k], dict)]
    hsr_r5 = sum(1 for v in hsr_items.values() if isinstance(v, dict) and int(v.get("rank", 0) or 0) == 5)

    # 4) 낚시 수족관 대표 대물
    f_sum = fishing_core.get_user_fishing_summary(guild_id, user_id, user_name)
    fu = f_sum["user"]
    tank = [it for it in (fu.get("tank") or []) if isinstance(it, dict)]
    tank_sorted = sorted(tank, key=lambda it: (-int(it.get("rarity", 1) or 1), -float(it.get("length_cm", 0) or 0)))

    # 5) 타인의 삶 요약
    ol_u = core.safe_get_dict(data, "other_life_users", g_key, u_key)
    ol_endings = len([k for k, v in core.as_dict(ol_u.get("unlocked_endings")).items() if v])
    ol_best = int(ol_u.get("best_score", 0) or 0)

    return {
        "user_name": user_name,
        "oshi": prof.get("oshi") or "미설정",
        "crystals": int(prof.get("crystals", 0) or 0),
        "gold": int(fu.get("gold", 0) or 0),
        "sekai_total": len(all_cards),
        "sekai_deck": deck_cards,
        "sekai_deck_power": deck_power,
        "sekai_top3": all_cards[:3],
        "gi_total": len(gi_items),
        "gi_r5": gi_r5,
        "gi_party": gi_party,
        "hsr_total": len(hsr_items),
        "hsr_r5": hsr_r5,
        "hsr_party": hsr_party,
        "tank_top3": tank_sorted[:3],
        "tank_hourly": int(f_sum.get("tank_hourly", 0) or 0),
        "fish_dex": len(core.as_dict(fu.get("pokedex"))),
        "ol_endings": ol_endings,
        "ol_best": ol_best,
    }


# ==========================================
# 6. 초성 퀴즈 & 주사위 대결 보상 처리
# ==========================================
def grant_chosung_reward(user_id: int, user_name: str = "유저") -> Tuple[bool, int, int]:
    """초성 퀴즈 정답 시 일일 한도 내 크리스탈 보상 지급. 반환: (보상지급여부, 지급액, 오늘횟수)"""
    data = core.load_data()
    today = core.get_today_str()
    prof = core.ensure_user_profile(data, user_id, user_name)
    rb = _ensure_routine_bucket(prof)
    ch = rb.get("chosung")
    if not isinstance(ch, dict) or ch.get("date") != today:
        ch = {"date": today, "count": 0}
        rb["chosung"] = ch

    cnt = int(ch.get("count", 0) or 0)
    if cnt >= CHOSUNG_DAILY_REWARD_CAP:
        return False, 0, cnt

    ch["count"] = cnt + 1
    prof["crystals"] = int(prof.get("crystals", 0) or 0) + CHOSUNG_REWARD_CRYSTALS
    core.save_data(data)
    return True, CHOSUNG_REWARD_CRYSTALS, ch["count"]


def settle_dice_duel(rolls: Dict[int, Tuple[str, int, int]], bet: int = 0) -> Dict[str, Any]:
    """
    주사위 대결 결과 정산.
    rolls: {user_id: (display_name, d1, d2)}
    bet: 0 (무료 친선전) 또는 >0 (크리스탈 내기 — 승자에게 상금 지급, 무승부 시 환불)
    """
    if not rolls:
        return {"ok": False, "msg": "참가자가 없습니다."}

    scored = sorted(
        [(uid, name, d1, d2, d1 + d2) for uid, (name, d1, d2) in rolls.items()],
        key=lambda x: (-x[4], -max(x[2], x[3])),
    )
    top_sum = scored[0][4]
    winners = [row for row in scored if row[4] == top_sum]

    if bet <= 0 or len(scored) < 2:
        return {
            "ok": True,
            "scored": scored,
            "winners": winners,
            "pot": 0,
            "payout_each": 0,
            "is_tie": len(winners) > 1,
        }

    # 내기 정산: 참가자 중 잔액이 충분한 사람 기준으로 안전 정산
    data = core.load_data()
    pot = 0
    paid_uids = []
    for uid, name, _, _, _ in scored:
        prof = core.ensure_user_profile(data, uid, name)
        cur = int(prof.get("crystals", 0) or 0)
        deduct = min(cur, bet)
        prof["crystals"] = cur - deduct
        pot += deduct
        paid_uids.append((uid, name, deduct))

    payout_each = pot // len(winners) if winners else 0
    rem = pot - payout_each * len(winners)
    for idx, (uid, name, _, _, _) in enumerate(winners):
        prof = core.ensure_user_profile(data, uid, name)
        prof["crystals"] = int(prof.get("crystals", 0) or 0) + payout_each + (rem if idx == 0 else 0)

    core.save_data(data)
    return {
        "ok": True,
        "scored": scored,
        "winners": winners,
        "pot": pot,
        "payout_each": payout_each,
        "is_tie": len(winners) > 1,
    }
