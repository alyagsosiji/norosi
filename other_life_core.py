"""
norosi Bot - 「타인의인생」 코어 스토리 시뮬레이션 엔진 (other_life_core.py)
- 0세 탄생부터 노년/결말까지 한 타인의 일생을 인과관계·개연성 기반으로 살아가는 텍스트 RPG
- 균형 잡힌 실시간 시간 배율(60초=1년 표준 / 30초=1년 쾌속 / 3분=1년 슬로우 / 턴제 즉시) + 능동 분기 진행 지원
- 6대 출신 · 7대 진로 × 20개 세부 전공 · 동반자/스승 떡밥 회수 · 1,000종 멀티 엔딩 · 전기 도감
"""

from __future__ import annotations

import copy
import datetime
import random
import threading
from typing import Any, Dict, List, Optional, Tuple

import core
import other_life_endings as ol_endings
import other_life_narratives as ol_narratives
from other_life_endings import (
    ARCHETYPE_META,
    ENDINGS,
    LEGACY_ENDING_MAP,
    migrate_legacy_ending_id,
    resolve_ending,
)
from other_life_narratives import (
    BEAT_AGE_WINDOWS,
    CAREER_SPECIALTIES,
    EMPIRE_ELIGIBLE_SPECIALTIES,
    HOMETOWN_META,
    SPECIALTY_CATALOG,
    get_role_context,
)

_OTHER_LIFE_LOCK = threading.RLock()

DAILY_CRYSTAL_REWARD_LIMIT = 3
MIN_BEATS_FOR_REWARD = 10
MAX_IDLE_YEARS_PER_BEAT = 2
MAX_IDLE_STAT_TICKS_PER_LIFE = 16

# ==========================================
# 1. 시간 배율 프리셋 (실시간 흐름 + 능동 분기 진행 공존)
# ==========================================
TIME_SCALES: Dict[str, Dict[str, Any]] = {
    "balanced": {
        "id": "balanced",
        "name": "⚖️ 표준 세월 배율 (추천)",
        "emoji": "⚖️",
        "sec_per_year": 60,
        "desc": "실시간 60초마다 1년씩 일상이 흐르며(챕터당 최대 2년 · 생애 숙성 상한 16회), 선택지 클릭 시 즉시 다음 분기로 이어집니다.",
        "short_desc": "60초=1년 실시간 일상숙성 + 클릭 즉시 분기 진행",
    },
    "brisk": {
        "id": "brisk",
        "name": "⚡ 쾌속 세월 배율",
        "emoji": "⚡",
        "sec_per_year": 30,
        "desc": "실시간 30초마다 1년씩 빠르게 일상 경험이 쌓이며(챕터당 최대 2년), 원할 때마다 바로 분기를 넘길 수 있습니다.",
        "short_desc": "30초=1년 빠른 일상숙성 + 클릭 즉시 분기 진행",
    },
    "slow": {
        "id": "slow",
        "name": "🕰️ 슬로우 라이프",
        "emoji": "🕰️",
        "sec_per_year": 180,
        "desc": "실시간 3분마다 1년이 흐르며 하루 동안 느긋하게 한 사람의 인생을 동행합니다 (조기 진행 가능).",
        "short_desc": "3분=1년 느긋한 감성 배율 + 클릭 즉시 분기 진행",
    },
    "turn": {
        "id": "turn",
        "name": "📖 턴제 정주행",
        "emoji": "📖",
        "sec_per_year": 0,
        "desc": "실시간 대기 없이 오직 이야기 선택만으로 0세부터 엔딩까지 한 편의 소설처럼 정주행합니다.",
        "short_desc": "대기 없음 · 선택지 클릭만으로 빠르게 엔딩 감상",
    },
}

DEFAULT_TIME_SCALE = "balanced"

# ==========================================
# 2. 인물 시드 / 출신 배경 / 진로 / 5대 시기
# ==========================================
FIRST_NAMES = [
    "서율", "도현", "지안", "시우", "은채", "태오", "하린", "유건",
    "다온", "세훈", "서아", "민준", "수빈", "재원", "연우", "주원",
    "하율", "예린", "건우", "채원", "이안", "가온", "시현", "윤서",
]
SURNAMES = ["강", "윤", "한", "박", "최", "임", "송", "정", "백", "오", "진", "서", "조", "류"]
COMPANION_POOL = ["지우", "민재", "하은", "유진", "도윤", "수아", "현우", "소연", "준서", "채영"]
ADULT_PARTNER_POOL = ["서연", "태현", "해인", "지호", "나연", "우진", "예진", "승민"]
MENTOR_SURNAMES = ["백", "강", "문", "선우", "남", "차", "허", "유"]

HOMETOWNS = [
    "부산 영도의 바닷바람 부는 골목",
    "서울 북촌의 비탈진 기와집 옆",
    "강릉 주문진의 작은 포구",
    "전주 한옥마을 끝자락",
    "인천 차이나타운 너머 낡은 부두",
    "춘천 소양강 안개 낀 언덕",
    "여수 돌산의 붉은 등대 아래",
    "경주 황리단의 오래된 느티나무 곁",
]

STAGES: List[Tuple[str, str, str, int, int]] = [
    ("childhood", "🌱 유년기", "세상의 첫 질감을 배우는 시절", 0, 13),
    ("teen", "🎒 청소년기", "꿈과 인연, 방황이 싹트는 시절", 14, 18),
    ("youth", "🔥 청년기", "스스로 선택한 길 위에서 부딪히는 시절", 19, 36),
    ("midlife", "🏛️ 장년기", "선택의 무게와 과거가 되돌아오는 시절", 37, 61),
    ("elder", "🍂 노년기", "지나온 세월을 껴안고 마침표를 찍는 시절", 62, 100),
]

CAREER_META: Dict[str, Dict[str, str]] = {
    "none": {"name": "미정 (성장 중)", "emoji": "🌱"},
    "artist": {"name": "예술·창작가", "emoji": "🎨"},
    "scholar": {"name": "학자·연구자", "emoji": "🔬"},
    "entrepreneur": {"name": "사업·개척가", "emoji": "💼"},
    "artisan": {"name": "장인·생활인", "emoji": "🌿"},
    "guardian": {"name": "수호·언론인", "emoji": "⚖️"},
    "wanderer": {"name": "방랑·기록가", "emoji": "🧭"},
    "shadow": {"name": "그림자 브로커", "emoji": "🎭"},
}

ORIGINS: Dict[str, Dict[str, Any]] = {
    "orphanage": {
        "id": "orphanage",
        "name": "🌊 바닷가 보육원 '해송원'",
        "place": "바닷가 보육원 '해송원'",
        "item": "파도에 닳은 유리조각과 스케치북",
        "hook": "가진 것은 적었으나 파도 소리를 들으며 누구보다 단단히 자랐다.",
        "stats": {"intellect": 22, "passion": 26, "empathy": 26, "grit": 28, "wealth": 10},
    },
    "noodle_shop": {
        "id": "noodle_shop",
        "name": "🍜 시장통 24시 멸치국수집",
        "place": "시장통 멸치국수집",
        "item": "어머니의 무쇠 육수 국자",
        "hook": "새벽 4시 멸치 육수 향기와 시끌벅적한 시장 상인들의 웃음 속에서 컸다.",
        "stats": {"intellect": 20, "passion": 24, "empathy": 30, "grit": 26, "wealth": 16},
    },
    "scholar_home": {
        "id": "scholar_home",
        "name": "📚 오래된 한옥 서재 집안",
        "place": "한옥 서재 집안",
        "item": "먹 냄새 배인 만년필과 천문학 노트",
        "hook": "천장까지 쌓인 책들 사이에서 높은 기대를 짊어지고 첫 숨을 쉬었다.",
        "stats": {"intellect": 32, "passion": 22, "empathy": 20, "grit": 20, "wealth": 22},
    },
    "fallen_house": {
        "id": "fallen_house",
        "name": "🏚️ 몰락한 옛 저택의 막내",
        "place": "빛바랜 붉은 벽돌 저택",
        "item": "녹슨 가문 문장 열쇠",
        "hook": "한때의 영광과 빚쟁이들의 그림자 사이에서 일찍 어른의 눈빛을 배웠다.",
        "stats": {"intellect": 26, "passion": 28, "empathy": 18, "grit": 26, "wealth": 14},
    },
    "artisan_shop": {
        "id": "artisan_shop",
        "name": "🕰️ 골목 끝 시계·목공방",
        "place": "오래된 시계·목공 수리점",
        "item": "아버지의 황동 돋보기 루페",
        "hook": "째깍거리는 초침 소리와 대패질 소리 사이에서 묵묵히 손끝의 감각을 익혔다.",
        "stats": {"intellect": 24, "passion": 24, "empathy": 24, "grit": 28, "wealth": 18},
    },
    "mountain_clinic": {
        "id": "mountain_clinic",
        "name": "⛰️ 안개 낀 산골 약초방",
        "place": "안개 낀 산골 약초방",
        "item": "별자리와 약초가 그려진 낡은 수첩",
        "hook": "약초 달이는 향기와 밤하늘 은하수 아래에서 생명의 온도를 먼저 배웠다.",
        "stats": {"intellect": 26, "passion": 20, "empathy": 30, "grit": 26, "wealth": 12},
    },
}

# ==========================================
# 3. 1,000종 멀티 엔딩 카탈로그 (other_life_endings 모듈에서 로드)
# ==========================================
# ENDINGS, ARCHETYPE_META, LEGACY_ENDING_MAP 등은 상단 import로 제공됩니다.


# ==========================================
# 4. 보조 유틸리티
# ==========================================
def _safe_int(val: Any, default: int = 0) -> int:
    try:
        if val is None or isinstance(val, bool):
            return default
        return int(float(val))
    except Exception:
        return default


def _clamp_stat(v: int) -> int:
    return max(0, min(100, int(v)))


def get_stage_for_age(age: int) -> Tuple[str, str, str]:
    for sid, label, desc, mn, mx in STAGES:
        if mn <= age <= mx:
            return sid, label, desc
    return STAGES[-1][0], STAGES[-1][1], STAGES[-1][2]


def _pick_top_careers(stats: Dict[str, int], flags: set) -> List[str]:
    scores = {
        "artist": stats.get("passion", 0) * 1.15 + stats.get("empathy", 0) * 0.6 + (15 if "apt_art" in flags else 0) + (10 if "promise_express" in flags else 0),
        "scholar": stats.get("intellect", 0) * 1.2 + (18 if "apt_study" in flags else 0) + (10 if "promise_truth" in flags else 0),
        "entrepreneur": stats.get("wealth", 0) * 1.1 + stats.get("passion", 0) * 0.5 + (15 if "shortcut_tempted" in flags else 0),
        "artisan": stats.get("grit", 0) * 1.0 + stats.get("empathy", 0) * 0.5 + (18 if "apt_craft" in flags else 0),
        "guardian": stats.get("empathy", 0) * 0.9 + stats.get("grit", 0) * 0.8 + (18 if "apt_justice" in flags else 0) + (10 if "honest_path" in flags else 0),
        "wanderer": stats.get("passion", 0) * 0.6 + stats.get("intellect", 0) * 0.5 + (18 if "rebel_spirit" in flags else 0),
    }
    ordered = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
    return ordered[:2]


# ==========================================
# 5. 유저 상태 초기화 & 시간 배율 진행 엔진
# ==========================================
def ensure_other_life_user(data: Dict[str, Any], guild_id: int | str, user_id: int | str, user_name: str = "") -> Dict[str, Any]:
    root = core.ensure_dict_path(data, "other_life_users", str(guild_id or 0))
    u_key = str(user_id)
    u = root.get(u_key)
    if not isinstance(u, dict):
        u = {}
        root[u_key] = u

    if user_name:
        u["user_name"] = user_name
    elif not u.get("user_name"):
        u["user_name"] = f"유저#{u_key[-4:]}"

    ts = str(u.get("preferred_scale") or DEFAULT_TIME_SCALE)
    u["preferred_scale"] = ts if ts in TIME_SCALES else DEFAULT_TIME_SCALE
    u["lives_completed"] = max(0, _safe_int(u.get("lives_completed"), 0))
    u["best_score"] = max(0, _safe_int(u.get("best_score"), 0))
    u["longest_age"] = max(0, _safe_int(u.get("longest_age"), 0))

    history_list = [
        copy.deepcopy(h) for h in core.coerce_list_like(u.get("history"))
        if isinstance(h, dict) and h.get("name") and h.get("ending_id")
    ]
    raw_endings = u.get("unlocked_endings")
    migrated_endings: Dict[str, int] = {}
    if isinstance(raw_endings, list):
        for raw_e in raw_endings:
            e_str = str(raw_e or "").strip()
            new_eid = e_str if e_str in ENDINGS else migrate_legacy_ending_id(e_str, history_list)
            if new_eid and new_eid in ENDINGS:
                migrated_endings[new_eid] = migrated_endings.get(new_eid, 0) + 1
    elif isinstance(raw_endings, dict):
        for raw_k, raw_v in raw_endings.items():
            k_str = str(raw_k or "").strip()
            cnt = max(1, _safe_int(raw_v, 1))
            new_eid = k_str if k_str in ENDINGS else migrate_legacy_ending_id(k_str, history_list)
            if new_eid and new_eid in ENDINGS:
                migrated_endings[new_eid] = migrated_endings.get(new_eid, 0) + cnt
    u["unlocked_endings"] = migrated_endings

    for h in history_list:
        old_heid = str(h.get("ending_id") or "").strip()
        if old_heid and old_heid not in ENDINGS:
            new_heid = migrate_legacy_ending_id(old_heid, [h])
            if new_heid and new_heid in ENDINGS:
                em = ENDINGS[new_heid]
                h["ending_id"] = new_heid
                h["ending_title"] = em["title"]
                h["ending_emoji"] = em["emoji"]
                h["ending_rarity"] = em["rarity"]
    u["history"] = history_list[:50]

    today_str = core.get_today_str()
    if u.get("reward_date") != today_str:
        u["reward_date"] = today_str
        u["daily_rewards"] = 0
    else:
        u["daily_rewards"] = max(0, _safe_int(u.get("daily_rewards"), 0))

    active = u.get("active_life")
    if active is not None and not isinstance(active, dict):
        u["active_life"] = None
    elif isinstance(active, dict):
        if active.get("time_scale") not in TIME_SCALES:
            active["time_scale"] = u["preferred_scale"]
        if not isinstance(active.get("stats"), dict):
            active["stats"] = {"intellect": 25, "passion": 25, "empathy": 25, "grit": 25, "wealth": 15}
        active["flags"] = [str(f) for f in core.coerce_list_like(active.get("flags")) if f]
        active["chronicle"] = [str(c) for c in core.coerce_list_like(active.get("chronicle")) if c][-120:]
        active["turning_points"] = [str(t) for t in core.coerce_list_like(active.get("turning_points")) if t][-30:]
        active["beat"] = max(1, min(18, _safe_int(active.get("beat"), 1)))
        active["age"] = max(0, min(105, _safe_int(active.get("age"), 6)))
        active["quiet_in_stage"] = max(0, _safe_int(active.get("quiet_in_stage"), 0))
        active["idle_years_beat"] = max(0, _safe_int(active.get("idle_years_beat"), 0))
        active["idle_stat_ticks"] = max(0, _safe_int(active.get("idle_stat_ticks"), 0))
        if active.get("career") and active.get("career") != "none" and not active.get("specialty"):
            active["specialty"] = ol_narratives.resolve_specialty_id(active)
        if active.get("finished") and active.get("ending_id") and str(active.get("ending_id")) not in ENDINGS:
            old_active_eid = str(active.get("ending_id"))
            fake_h = [{
                "ending_id": old_active_eid,
                "origin_id": active.get("origin_id"),
                "career": active.get("career"),
                "specialty_label": SPECIALTY_CATALOG.get(str(active.get("specialty") or ""), {}).get("title", ""),
            }]
            new_aeid = migrate_legacy_ending_id(old_active_eid, fake_h)
            if new_aeid and new_aeid in ENDINGS:
                active["ending_id"] = new_aeid
    return u


def _make_idle_diary_line(life: Dict[str, Any], age_at_year: int) -> Tuple[str, Dict[str, int]]:
    return ol_narratives.build_idle_diary_line(life, age_at_year)


def _stage_age_ceiling(beat: int, current_age: int = 6) -> int:
    """실시간 시간 경과가 현재 스토리 챕터의 나이 맥락을 망가뜨리지 않도록 상한 부여"""
    b = max(1, min(18, _safe_int(beat, 1)))
    _, _, max_a = BEAT_AGE_WINDOWS.get(b, (_safe_int(current_age, 6), _safe_int(current_age, 6), 95))
    return max(_safe_int(current_age, 6), int(max_a))


def _apply_stat_delta(stats: Dict[str, int], delta: Dict[str, int]) -> None:
    for k in ("intellect", "passion", "empathy", "grit", "wealth"):
        if k in delta:
            stats[k] = _clamp_stat(_safe_int(stats.get(k), 20) + int(delta[k]))


def sync_life_time(life: Dict[str, Any], now_ts: Optional[float] = None) -> Tuple[int, List[str]]:
    """
    선택된 시간 배율(TIME_SCALES)에 따라 마지막 활동 이후 흐른 실제 시간만큼
    캐릭터의 일상 숙성(챕터당 최대 2년 · 생애 스탯 숙성 상한 16회)과 일기장 기록을 자연스럽게 반영합니다.
    (스토리 분기점 자체를 임의로 건너뛰지는 않으므로 스토리 개연성이 100% 유지됩니다.)
    """
    if not isinstance(life, dict) or life.get("finished"):
        return 0, []
    scale_id = str(life.get("time_scale") or DEFAULT_TIME_SCALE)
    scale = TIME_SCALES.get(scale_id, TIME_SCALES[DEFAULT_TIME_SCALE])
    sec_per_year = int(scale.get("sec_per_year", 0))
    now_f = float(now_ts if now_ts is not None else datetime.datetime.now(core.KST).timestamp())
    last_f = float(life.get("last_tick_at") or now_f)
    if sec_per_year <= 0:
        life["last_tick_at"] = now_f
        return 0, []

    elapsed = max(0.0, now_f - last_f)
    years_ready = int(elapsed // sec_per_year)
    if years_ready <= 0:
        return 0, []

    cur_beat = _safe_int(life.get("beat"), 1)
    cur_age = _safe_int(life.get("age"), 6)
    ceiling = _stage_age_ceiling(cur_beat, cur_age)
    idle_used_beat = max(0, _safe_int(life.get("idle_years_beat"), 0))
    room_age = max(0, ceiling - cur_age)
    room_beat = max(0, MAX_IDLE_YEARS_PER_BEAT - idle_used_beat)
    room = min(room_age, room_beat)
    if room <= 0:
        life["last_tick_at"] = now_f
        return 0, []

    years_to_add = min(MAX_IDLE_YEARS_PER_BEAT, years_ready, room)
    if years_ready > years_to_add:
        rem_sec = elapsed % sec_per_year
        life["last_tick_at"] = now_f - rem_sec
    else:
        life["last_tick_at"] = min(now_f, last_f + years_to_add * sec_per_year)
    if years_to_add <= 0:
        return 0, []

    added_logs: List[str] = []
    stats = life.setdefault("stats", {})
    chronicle = life.setdefault("chronicle", [])
    idle_stat_ticks = max(0, _safe_int(life.get("idle_stat_ticks"), 0))
    for step in range(years_to_add):
        y_age = cur_age + step + 1
        line, delta = _make_idle_diary_line(life, y_age)
        if idle_stat_ticks < MAX_IDLE_STAT_TICKS_PER_LIFE:
            _apply_stat_delta(stats, delta)
            idle_stat_ticks += 1
        entry = f"⏳ {y_age}세 (세월의 흐름) — {line}"
        chronicle.append(entry)
        added_logs.append(entry)
    life["age"] = cur_age + years_to_add
    life["idle_years_beat"] = idle_used_beat + years_to_add
    life["idle_stat_ticks"] = idle_stat_ticks
    if len(chronicle) > 120:
        del chronicle[:-120]
    return years_to_add, added_logs


# ==========================================
# 6. 스토리 노드 빌더 (other_life_narratives 위임)
# ==========================================
def _fmt_vars(life: Dict[str, Any]) -> Dict[str, Any]:
    return ol_narratives.fmt_life_vars(life)


def build_current_node(life: Dict[str, Any]) -> Dict[str, Any]:
    """현재 캐릭터의 beat, origin, career, specialty, flags, 관계에 정확히 부합하는 스토리 장면을 생성합니다."""
    return ol_narratives.build_story_node(life)


# ==========================================
# 7. 엔딩 판정기 (other_life_endings 위임 — 1,000종 인과 판정)
# ==========================================
def _resolve_ending(life: Dict[str, Any], forced_flame: bool = False) -> Tuple[str, Dict[str, Any]]:
    return resolve_ending(life, forced_flame=forced_flame)


# ==========================================
# 8. 공개 API (시작 / 선택 / 조용한 1년 / 시간 동기화 / 도감 / 랭킹)
# ==========================================
def start_new_life(
    guild_id: int | str,
    user_id: int | str,
    user_name: str = "",
    time_scale: Optional[str] = None,
    origin_id: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    with _OTHER_LIFE_LOCK:
        data = core.load_data()
        u = ensure_other_life_user(data, guild_id, user_id, user_name)

        scale_id = time_scale if time_scale in TIME_SCALES else u["preferred_scale"]
        u["preferred_scale"] = scale_id

        chosen_origin = origin_id if origin_id in ORIGINS else random.choice(list(ORIGINS.keys()))
        orig = ORIGINS[chosen_origin]

        full_name = random.choice(SURNAMES) + random.choice(FIRST_NAMES)
        comp_choices = [c for c in COMPANION_POOL if not full_name.endswith(c)]
        companion = random.choice(comp_choices)
        adult_choices = [a for a in ADULT_PARTNER_POOL if a != companion and not full_name.endswith(a)]
        adult_partner = random.choice(adult_choices)
        mentor = f"{random.choice(MENTOR_SURNAMES)} 선생"
        hometown = random.choice(HOMETOWNS)
        ht = ol_narratives.get_hometown_meta(hometown)
        ro_sfx = ol_narratives.p_ro(full_name)

        now_f = datetime.datetime.now(core.KST).timestamp()
        life = {
            "life_uid": f"{int(now_f)}_{random.randint(100, 999)}",
            "name": full_name,
            "hometown": hometown,
            "origin_id": chosen_origin,
            "companion_name": companion,
            "adult_partner_name": adult_partner,
            "mentor_name": mentor,
            "partner_name": None,
            "career": "none",
            "specialty": "none",
            "companion_rel": "stranger",
            "mentor_rel": "unknown",
            "prev_choice_id": "",
            "age": 6,
            "beat": 1,
            "quiet_in_stage": 0,
            "idle_years_beat": 0,
            "idle_stat_ticks": 0,
            "time_scale": scale_id,
            "last_tick_at": now_f,
            "started_at": datetime.datetime.now(core.KST).isoformat(),
            "stats": copy.deepcopy(orig["stats"]),
            "flags": [],
            "turning_points": [
                f"0세: {ht['city']}의 {orig['place']}에서 '{full_name}'{ro_sfx} 태어나다."
            ],
            "last_outcome": (
                f"{ol_narratives.j_i(ht['sensory'])} 스며드는 **{ht['city']}**의 **{orig['place']}**에서 작은 울음소리와 함께 세상에 눈을 떴습니다. "
                f"어린 손에 처음 쥔 유품은 **{orig['item']}**. {orig['hook']}"
            ),
            "chronicle": [
                f"👶 0세 — {ht['city']}의 {orig['place']}에서 '{full_name}'{ro_sfx} 태어났다. ({orig['hook']})"
            ],
            "finished": False,
            "ending_id": None,
            "ending_epilogue": None,
            "score": 0,
            "crystal_awarded": 0,
        }
        u["active_life"] = life
        core.save_data(data)
        return True, f"📖 새로운 타인의 인생 **'{full_name}'**의 이야기가 시작되었습니다!", copy.deepcopy(u)


def get_other_life_state(
    guild_id: int | str,
    user_id: int | str,
    user_name: str = "",
) -> Tuple[Dict[str, Any], int, List[str]]:
    with _OTHER_LIFE_LOCK:
        data = core.load_data()
        before = copy.deepcopy(core.safe_get_dict(data, "other_life_users", str(guild_id or 0), str(user_id)))
        u = ensure_other_life_user(data, guild_id, user_id, user_name)
        years_added = 0
        idle_logs: List[str] = []
        if isinstance(u.get("active_life"), dict) and not u["active_life"].get("finished"):
            years_added, idle_logs = sync_life_time(u["active_life"])
        if years_added > 0 or u != before:
            core.save_data(data)
        return copy.deepcopy(u), years_added, idle_logs


def set_life_time_scale(
    guild_id: int | str,
    user_id: int | str,
    scale_id: str,
    user_name: str = "",
) -> Tuple[bool, str, Dict[str, Any]]:
    if scale_id not in TIME_SCALES:
        return False, "❌ 알 수 없는 시간 배율입니다.", {}
    with _OTHER_LIFE_LOCK:
        data = core.load_data()
        u = ensure_other_life_user(data, guild_id, user_id, user_name)
        u["preferred_scale"] = scale_id
        if isinstance(u.get("active_life"), dict) and not u["active_life"].get("finished"):
            sync_life_time(u["active_life"])
            u["active_life"]["time_scale"] = scale_id
            u["active_life"]["last_tick_at"] = datetime.datetime.now(core.KST).timestamp()
        core.save_data(data)
        sc = TIME_SCALES[scale_id]
        return True, f"⏱️ 시간 배율을 **{sc['name']}**(`{sc['short_desc']}`)로 변경했습니다!", copy.deepcopy(u)


def set_life_specialty(
    guild_id: int | str,
    user_id: int | str,
    specialty_id: str,
    user_name: str = "",
) -> Tuple[bool, str, Dict[str, Any]]:
    spec_id = str(specialty_id or "").strip()
    if spec_id not in SPECIALTY_CATALOG:
        return False, "❌ 알 수 없는 세부 전공입니다.", {}
    with _OTHER_LIFE_LOCK:
        data = core.load_data()
        u = ensure_other_life_user(data, guild_id, user_id, user_name)
        life = u.get("active_life")
        if not isinstance(life, dict) or life.get("finished"):
            return False, "ℹ️ 현재 진행 중인 인생이 없습니다.", copy.deepcopy(u)
        career = str(life.get("career") or "none")
        allowed = CAREER_SPECIALTIES.get(career, [])
        if spec_id not in allowed:
            return False, "❌ 현재 진로에서는 선택할 수 없는 세부 전공입니다.", copy.deepcopy(u)
        if _safe_int(life.get("beat"), 1) != 8:
            return False, "ℹ️ 세부 전공 변경은 22세 첫 무대(Chapter 8)에서만 가능합니다.", copy.deepcopy(u)
        life["specialty"] = spec_id
        smeta = SPECIALTY_CATALOG[spec_id]
        life["last_action_summary"] = f"세부 전공 선택: {smeta['title']}"
        core.save_data(data)
        return True, f"🎯 세부 전공을 **{smeta['emoji']} {smeta['title']}**(으)로 선택했습니다!", copy.deepcopy(u)


def spend_quiet_year(
    guild_id: int | str,
    user_id: int | str,
    user_name: str = "",
) -> Tuple[bool, str, Dict[str, Any]]:
    with _OTHER_LIFE_LOCK:
        data = core.load_data()
        u = ensure_other_life_user(data, guild_id, user_id, user_name)
        life = u.get("active_life")
        if not isinstance(life, dict) or life.get("finished"):
            return False, "ℹ️ 현재 진행 중인 인생이 없습니다.", copy.deepcopy(u)

        sync_life_time(life)
        cur_beat = _safe_int(life.get("beat"), 1)
        max_q = 3 if cur_beat == 18 else 2
        if _safe_int(life.get("quiet_in_stage"), 0) >= max_q:
            return False, f"⏳ 이번 시기의 조용한 수련(최대 {max_q}년)을 모두 보냈습니다. 이제 인생의 선택지를 골라 주세요!", copy.deepcopy(u)

        cur_age = _safe_int(life.get("age"), 6)
        ceiling = _stage_age_ceiling(cur_beat, cur_age)
        if cur_age >= ceiling or cur_age >= 95:
            return False, "⏳ 다음 분기점의 문턱에 도달했습니다! 아래 선택지 중 하나를 선택해 주세요.", copy.deepcopy(u)

        new_age = cur_age + 1
        line, delta = _make_idle_diary_line(life, new_age)
        # Boost slightly for active quiet year (pure_art/overworked 제약 보존)
        for k in list(delta.keys()):
            delta[k] = delta[k] + 1
        _apply_stat_delta(life["stats"], delta)
        life["age"] = new_age
        life["quiet_in_stage"] = _safe_int(life.get("quiet_in_stage"), 0) + 1
        life["last_tick_at"] = datetime.datetime.now(core.KST).timestamp()
        life["last_outcome"] = f"**{new_age}세**의 조용한 한 해 — {line}"
        entry = f"🕰️ {new_age}세 (조용한 한 해) — {line}"
        chronicle = life.setdefault("chronicle", [])
        chronicle.append(entry)
        if len(chronicle) > 120:
            del chronicle[:-120]
        core.save_data(data)
        return True, f"🕰️ **{new_age}세**의 조용한 한 해를 보내며 차분히 내면을 다졌습니다.", copy.deepcopy(u)


def _finalize_ending(data: Dict[str, Any], u: Dict[str, Any], user_id: int | str, user_name: str, forced_flame: bool = False) -> None:
    life = u["active_life"]
    eid, res = _resolve_ending(life, forced_flame=forced_flame)
    meta = res["meta"]
    score = res["score"]

    life["finished"] = True
    life["ending_id"] = eid
    life["ending_epilogue"] = res["epilogue"]
    life["score"] = score
    chronicle = life.setdefault("chronicle", [])
    chronicle.append(f"📖 {life['age']}세 — [엔딩: {meta['emoji']} {meta['title']}]")
    if len(chronicle) > 120:
        del chronicle[:-120]

    u["lives_completed"] = _safe_int(u.get("lives_completed"), 0) + 1
    u["best_score"] = max(_safe_int(u.get("best_score"), 0), score)
    u["longest_age"] = max(_safe_int(u.get("longest_age"), 0), _safe_int(life.get("age"), 0))

    unlocked = u.setdefault("unlocked_endings", {})
    is_first_unlock = eid not in unlocked
    unlocked[eid] = _safe_int(unlocked.get(eid), 0) + 1

    # 일일 보상 상한 & 최소 진행 챕터 검증으로 어뷰징 방지
    today_str = core.get_today_str()
    if u.get("reward_date") != today_str:
        u["reward_date"] = today_str
        u["daily_rewards"] = 0

    beats_played = _safe_int(life.get("beat"), 1)
    crystal_gain = 0
    reward_note = ""
    if beats_played >= MIN_BEATS_FOR_REWARD:
        if u["daily_rewards"] < DAILY_CRYSTAL_REWARD_LIMIT:
            crystal_gain = int(meta["base_crystal"]) + (120 if is_first_unlock else 0)
            u["daily_rewards"] += 1
            prof = core.ensure_user_profile(data, str(user_id), user_name or u.get("user_name", ""))
            prof["crystals"] = _safe_int(prof.get("crystals"), 0) + crystal_gain
            first_tag = " (🆕 신규 엔딩 초회 보너스 +120💎 포함!)" if is_first_unlock else ""
            reward_note = f"+{crystal_gain:,}💎 지급 완료{first_tag}"
        else:
            reward_note = f"오늘 💎 보상 한도({DAILY_CRYSTAL_REWARD_LIMIT}회/일) 도달 — 도감·기록은 정상 등록!"
    else:
        reward_note = "최소 진행 기준 미달 (도감 등록 완료)"

    life["crystal_awarded"] = crystal_gain
    life["reward_note"] = reward_note
    life["is_first_unlock"] = is_first_unlock

    career_meta = CAREER_META.get(str(life.get("career") or "none"), CAREER_META["none"])
    role_ctx = get_role_context(life)
    u.setdefault("history", []).insert(0, {
        "life_uid": life.get("life_uid"),
        "name": life.get("name"),
        "origin_id": life.get("origin_id"),
        "career": life.get("career"),
        "career_label": career_meta["name"],
        "specialty": role_ctx.get("specialty_id") or "",
        "specialty_label": role_ctx["title"] if role_ctx["career"] != "none" else career_meta["name"],
        "age": life.get("age"),
        "ending_id": eid,
        "ending_title": meta["title"],
        "ending_emoji": meta["emoji"],
        "ending_rarity": meta["rarity"],
        "score": score,
        "finished_at": datetime.datetime.now(core.KST).strftime("%Y-%m-%d %H:%M"),
        "chronicle_tail": list(life.get("chronicle") or [])[-8:],
    })
    if len(u["history"]) > 50:
        del u["history"][50:]


def apply_life_choice(
    guild_id: int | str,
    user_id: int | str,
    choice_id: str,
    user_name: str = "",
) -> Tuple[bool, str, Dict[str, Any], Optional[Dict[str, Any]]]:
    with _OTHER_LIFE_LOCK:
        data = core.load_data()
        u = ensure_other_life_user(data, guild_id, user_id, user_name)
        life = u.get("active_life")
        if not isinstance(life, dict) or life.get("finished"):
            return False, "ℹ️ 이미 마무리되었거나 진행 중인 인생이 없습니다.", copy.deepcopy(u), None

        sync_life_time(life)
        node = build_current_node(life)
        chosen = next((c for c in node["choices"] if c["id"] == choice_id), None)
        if not chosen:
            return False, "⚠️ 이미 지난 분기이거나 유효하지 않은 선택지입니다.", copy.deepcopy(u), None

        cur_age = _safe_int(life.get("age"), 6)
        stats = life.setdefault("stats", {})
        pre_grit = _safe_int(stats.get("grit"), 25)
        pre_flags = set(life.get("flags") or [])

        _apply_stat_delta(stats, chosen.get("delta") or {})

        flag_set = set(life.get("flags") or [])
        for f in chosen.get("add_flags") or []:
            flag_set.add(str(f))
        for f in chosen.get("remove_flags") or []:
            flag_set.discard(str(f))
        life["flags"] = sorted(flag_set)

        if chosen.get("set_career"):
            new_career = str(chosen["set_career"])
            if new_career != life.get("career"):
                life["specialty"] = ""
            life["career"] = new_career
        if chosen.get("set_specialty"):
            life["specialty"] = str(chosen["set_specialty"])
        elif life.get("career") and life.get("career") != "none":
            life["specialty"] = ol_narratives.resolve_specialty_id(life)

        if chosen.get("set_partner"):
            life["partner_name"] = str(chosen["set_partner"])
        if chosen.get("clear_partner"):
            life["partner_name"] = None
        if chosen.get("set_comp_rel"):
            life["companion_rel"] = str(chosen["set_comp_rel"])
        if chosen.get("set_mentor_rel"):
            life["mentor_rel"] = str(chosen["set_mentor_rel"])

        life["prev_choice_id"] = str(choice_id)

        log_text = str(chosen.get("log") or chosen.get("label") or "").strip()
        outcome_text = str(chosen.get("outcome") or "").strip()
        life["last_outcome"] = outcome_text or f"{cur_age}세의 선택 — {log_text}"
        life.setdefault("chronicle", []).append(f"• {cur_age}세 — {log_text}")
        if len(life["chronicle"]) > 120:
            del life["chronicle"][:-120]

        if chosen.get("tp"):
            tps = life.setdefault("turning_points", [])
            tp_str = str(chosen["tp"]).strip()
            if tp_str and (not tps or tps[-1] != tp_str):
                tps.append(tp_str)
            if len(tps) > 30:
                del tps[:-30]

        life["last_action_summary"] = f"{cur_age}세의 선택: {log_text}"
        life["last_tick_at"] = datetime.datetime.now(core.KST).timestamp()

        # 조기 영웅적 희생 / 건강 고갈 체크 (Beat 12 — 경고 조건과 100% 동기화)
        will_flame = (pre_grit <= 24) or (pre_grit <= 38 and "overworked" in pre_flags)
        if chosen.get("trigger_flame_if_low_grit") and will_flame:
            _finalize_ending(data, u, user_id, user_name, forced_flame=True)
            core.save_data(data)
            return True, f"🔥 **{life['name']}**의 불꽃 같은 생애가 엔딩에 도달했습니다!", copy.deepcopy(u), copy.deepcopy(chosen)

        cur_beat = _safe_int(life.get("beat"), 1)
        if cur_beat >= 18:
            _finalize_ending(data, u, user_id, user_name, forced_flame=False)
            core.save_data(data)
            return True, f"📖 **{life['name']}**의 인생 이야기가 완결되었습니다!", copy.deepcopy(u), copy.deepcopy(chosen)

        prev_stage = get_stage_for_age(cur_age)[0]
        next_beat = cur_beat + 1
        min_a, canon_a, max_a = BEAT_AGE_WINDOWS.get(next_beat, (cur_age + 1, cur_age + 1, 95))
        raw_next = cur_age + max(1, _safe_int(node.get("years_advance"), 3))
        if cur_age >= min_a:
            next_age = min(95, max(cur_age + 1, canon_a))
        else:
            next_age = max(min_a, min(max_a, max(canon_a, raw_next)))

        next_stage = get_stage_for_age(next_age)[0]
        life["age"] = next_age
        life["beat"] = next_beat
        life["idle_years_beat"] = 0
        if next_stage != prev_stage or next_beat == 18:
            life["quiet_in_stage"] = 0

        core.save_data(data)
        return True, f"📖 {next_age}세의 이야기로 이어집니다.", copy.deepcopy(u), copy.deepcopy(chosen)


def get_other_life_ranking(guild_id: int | str, limit: int = 10) -> List[Dict[str, Any]]:
    data = core.load_data()
    g_map = core.safe_get_dict(data, "other_life_users", str(guild_id or 0))
    rows: List[Dict[str, Any]] = []
    for u_key, raw in g_map.items():
        if not isinstance(raw, dict):
            continue
        unlocked = raw.get("unlocked_endings") or {}
        hist_raw = raw.get("history") if isinstance(raw.get("history"), list) else None
        raw_keys = unlocked.keys() if isinstance(unlocked, dict) else (unlocked if isinstance(unlocked, list) else [])
        resolved_keys = set()
        for k in raw_keys:
            ks = str(k or "").strip()
            if ks in ENDINGS:
                resolved_keys.add(ks)
            else:
                mk = migrate_legacy_ending_id(ks, hist_raw)
                if mk and mk in ENDINGS:
                    resolved_keys.add(mk)
        endings_cnt = len(resolved_keys)
        lives = max(0, _safe_int(raw.get("lives_completed"), 0))
        best_score = max(0, _safe_int(raw.get("best_score"), 0))
        if lives <= 0 and endings_cnt <= 0:
            continue
        rows.append({
            "user_id": str(u_key),
            "user_name": raw.get("user_name") or f"유저#{str(u_key)[-4:]}",
            "endings_cnt": endings_cnt,
            "lives_completed": lives,
            "best_score": best_score,
            "longest_age": max(0, _safe_int(raw.get("longest_age"), 0)),
        })
    rows.sort(key=lambda r: (r["endings_cnt"], r["best_score"], r["lives_completed"]), reverse=True)
    return rows[:limit]
