"""
norosi Bot - 「타인의인생」 고밀도 서사·개연성 스토리 엔진 (other_life_narratives.py)
- 8개 고향 로어 · 6대 출신 서사 · 7대 진로 × 20개 세부 전공/일터 · 스승/동반자/과거 선택의 인과 연결
- 18개 챕터 × 다중 분기(출신·직업·플래그·직전 선택 브릿지) + 한국어 조사 자동 보정 + 여파(Outcome) 서사
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple


# ==========================================
# 1. 한국어 조사 자동 보정 & 포맷 유틸
# ==========================================
def _last_syllable_code(word: str) -> Optional[int]:
    s = str(word or "").strip().rstrip("`'\"”’)]>.,!?~ ")
    for ch in reversed(s):
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            return code
        if ch.isalnum():
            # 영문/숫자 간이 판별
            if ch in "013678lmnrLMNR":
                return 0xAC00 + 8  # ㄹ 받침 취급 (로, 이, 은, 을...)
            if ch in "2459":
                return 0xAC00
            return 0xAC01
    return None


def _jongseong_idx(word: str) -> int:
    code = _last_syllable_code(word)
    if code is None:
        return 0
    return (code - 0xAC00) % 28


def j_eun(word: str) -> str:
    return f"{word}{'은' if _jongseong_idx(word) != 0 else '는'}"


def j_i(word: str) -> str:
    return f"{word}{'이' if _jongseong_idx(word) != 0 else '가'}"


def j_eul(word: str) -> str:
    return f"{word}{'을' if _jongseong_idx(word) != 0 else '를'}"


def j_wa(word: str) -> str:
    return f"{word}{'과' if _jongseong_idx(word) != 0 else '와'}"


def j_ya(word: str) -> str:
    return f"{word}{'아' if _jongseong_idx(word) != 0 else '야'}"


def j_ro(word: str) -> str:
    idx = _jongseong_idx(word)
    # 무받침(0) 또는 ㄹ받침(8)은 '로', 그 외 받침은 '으로'
    return f"{word}{'로' if idx in (0, 8) else '으로'}"


def j_ida(word: str) -> str:
    return f"{word}{'이라' if _jongseong_idx(word) != 0 else '라'}"


def p_eun(word: str) -> str:
    return "은" if _jongseong_idx(word) != 0 else "는"


def p_i(word: str) -> str:
    return "이" if _jongseong_idx(word) != 0 else "가"


def p_eul(word: str) -> str:
    return "을" if _jongseong_idx(word) != 0 else "를"


def p_wa(word: str) -> str:
    return "과" if _jongseong_idx(word) != 0 else "와"


def p_ro(word: str) -> str:
    return "로" if _jongseong_idx(word) in (0, 8) else "으로"


def aff_eun(word: str) -> str:
    return f"{word}{'이는' if _jongseong_idx(word) != 0 else '는'}"


# ==========================================
# 2. 고향 로어 메타데이터 (8개 지역 완전 맞춤형 무대)
# ==========================================
HOMETOWN_META: Dict[str, Dict[str, str]] = {
    "부산 영도의 바닷바람 부는 골목": {
        "full": "부산 영도의 바닷바람 부는 골목",
        "city": "부산 영도",
        "hangout": "녹슨 등대 아래 방파제 계단",
        "night_spot": "파도 부서지는 흰여울 방파제 끝자락",
        "station": "부산역 붉은 벽돌 광장 앞 횡단보도",
        "sensory": "짭조름한 갯내음과 영도대교 너머 밤배의 기적 소리",
    },
    "서울 북촌의 비탈진 기와집 옆": {
        "full": "서울 북촌의 비탈진 기와집 옆",
        "city": "서울 북촌",
        "hangout": "감고당길 돌담 모퉁이 문방구 앞",
        "night_spot": "남산 불빛이 한눈에 내려다보이는 비탈 옥상",
        "station": "종로 세운상가 앞 오래된 횡단보도",
        "sensory": "비 젖은 기와 냄새와 골목 끝을 울리는 저녁 종소리",
    },
    "강릉 주문진의 작은 포구": {
        "full": "강릉 주문진의 작은 포구",
        "city": "강릉 주문진",
        "hangout": "오징어 건조대가 늘어선 포구 빨간 등대 앞",
        "night_spot": "고깃배 불빛이 수평선처럼 번지는 방파제 끝",
        "station": "강릉 시외버스터미널 앞 낡은 찻집",
        "sensory": "새벽 어판장의 소금기 어린 바람과 갈매기 울음소리",
    },
    "전주 한옥마을 끝자락": {
        "full": "전주 한옥마을 끝자락",
        "city": "전주",
        "hangout": "천변 버드나무 아래 낡은 헌책방 처마",
        "night_spot": "처마 끝 풍경이 바람에 우는 오목대 언덕 난간",
        "station": "전주역 한옥 지붕 아래 대합실 벤치",
        "sensory": "촉촉한 한지·먹 냄새와 천변을 스치는 풀벌레 소리",
    },
    "인천 차이나타운 너머 낡은 부두": {
        "full": "인천 차이나타운 너머 낡은 부두",
        "city": "인천 개항장",
        "hangout": "붉은 등롱 골목 끝 돌계단 쉼터",
        "night_spot": "안개 낀 월미도 너머 화물선 불빛이 스치는 부두 난간",
        "station": "인천역 앞 오래된 개항장 시계탑 아래",
        "sensory": "짜장·만두 찌는 김 냄새와 먼 바다에서 밀려오는 안개 바람",
    },
    "춘천 소양강 안개 낀 언덕": {
        "full": "춘천 소양강 안개 낀 언덕",
        "city": "춘천",
        "hangout": "소양강 처녀상 옆 자갈밭 나루터 매점",
        "night_spot": "물안개 위로 강물 불빛이 흔들리는 소양2교 언덕",
        "station": "남춘천역 플라타너스 가로수길",
        "sensory": "새벽마다 강물에서 피어오르는 서늘한 물안개와 기차 레일 소리",
    },
    "여수 돌산의 붉은 등대 아래": {
        "full": "여수 돌산의 붉은 등대 아래",
        "city": "여수 돌산",
        "hangout": "동백꽃 떨어지는 포구 앞 구멍가게 평상",
        "night_spot": "밤바다에 붉은빛을 길게 눕히는 돌산 등대 방파제",
        "station": "여수엑스포역 해풍 부는 바닷가 산책로",
        "sensory": "돌산 갓김치 익는 냄새와 밤바다를 건너오는 통통배 엔진 소리",
    },
    "경주 황리단의 오래된 느티나무 곁": {
        "full": "경주 황리단의 오래된 느티나무 곁",
        "city": "경주",
        "hangout": "천년 고분 옆 흙담장 문방구 처마",
        "night_spot": "신라 고분 너머 은하수가 쏟아지는 반월성 잔디 언덕",
        "station": "경주 시내 오래된 플라타너스 서점 앞",
        "sensory": "천년 느티나무 잎사귀 부딪치는 소리와 마른 흙냄새",
    },
}


def get_hometown_meta(hometown: str) -> Dict[str, str]:
    ht = str(hometown or "").strip()
    if ht in HOMETOWN_META:
        return HOMETOWN_META[ht]
    for k, meta in HOMETOWN_META.items():
        if k in ht or meta["city"] in ht:
            return meta
    return {
        "full": ht or "오래된 작은 마을",
        "city": (ht.split()[0] if ht else "고향"),
        "hangout": "오래된 문방구 처마 아래 평상",
        "night_spot": "마을 불빛이 내려다보이는 뒷산 쉼터",
        "station": "낡은 시외버스터미널 앞 횡단보도",
        "sensory": "익숙한 바람 냄새와 골목 어귀의 저녁 노을빛",
    }


# ==========================================
# 3. 6대 출신 로어 (유품·보호자·환경 디테일)
# ==========================================
ORIGIN_LORE: Dict[str, Dict[str, str]] = {
    "orphanage": {
        "place": "바닷가 보육원 '해송원'",
        "guardian": "원장 수녀님",
        "item_short": "파도에 깎인 유리 조각",
        "item_full": "파도에 닳은 유리조각과 스케치북",
        "memory_anchor": "창고 다락에서 처음 찾아낸 초록빛 유리 조각과 물 빠진 색연필",
    },
    "noodle_shop": {
        "place": "시장통 24시 멸치국수집",
        "guardian": "새벽 불을 지피시던 어머니",
        "item_short": "무쇠 육수 국자",
        "item_full": "어머니의 무쇠 육수 국자",
        "memory_anchor": "새벽 네 시 펄펄 끓는 멸치 육수 위로 손때가 반질반질하게 닦인 무쇠 국자",
    },
    "scholar_home": {
        "place": "오래된 한옥 서재 집안",
        "guardian": "서재를 지키던 엄격한 아버지",
        "item_short": "잉크 냄새 밴 만년필",
        "item_full": "먹 냄새 배인 만년필과 천문학 노트",
        "memory_anchor": "서재 천장의 별자리를 몰래 옮겨 적던 먹물 냄새 밴 노트와 만년필",
    },
    "fallen_house": {
        "place": "빛바랜 붉은 벽돌 저택",
        "guardian": "마지막 자존심을 삼키던 어머니",
        "item_short": "녹슨 가문 문장 열쇠",
        "item_full": "녹슨 가문 문장 열쇠",
        "memory_anchor": "경매 딱지가 붙던 날 마루 틈에서 줍고 꽉 쥔 녹슨 저택 정문 열쇠",
    },
    "artisan_shop": {
        "place": "오래된 시계·목공 수리점",
        "guardian": "손마디가 굵었던 아버지",
        "item_short": "황동 돋보기 루페",
        "item_full": "아버지의 황동 돋보기 루페",
        "memory_anchor": "수백 개의 시계 초침 소리 사이로 아버지가 내어주신 낡은 황동 돋보기 루페",
    },
    "mountain_clinic": {
        "place": "안개 낀 산골 약초방",
        "guardian": "촌사람들의 맥을 짚던 할아버지",
        "item_short": "별자리·약초 수첩",
        "item_full": "별자리와 약초가 그려진 낡은 수첩",
        "memory_anchor": "약초 달이는 향기와 밤하늘 별빛 아래 할아버지가 남겨주신 낡은 처방 수첩",
    },
}


def get_origin_lore(origin_id: Any) -> Dict[str, str]:
    oid = str(origin_id or "orphanage").strip()
    return ORIGIN_LORE.get(oid, ORIGIN_LORE["orphanage"])


# ==========================================
# 4. 7대 진로 × 20개 세부 전공·일터·도구 카탈로그
# ==========================================
SPECIALTY_CATALOG: Dict[str, Dict[str, str]] = {
    # artist
    "artist_paint": {
        "career": "artist",
        "title": "수채화·삽화가",
        "workplace": "북향 빛만 드는 다락 아틀리에",
        "tool": "물감 찌든 팔레트와 세필 붓",
        "work_obj": "물감이 아직 마르지 않은 대형 캔버스",
        "patron": "갤러리 관장",
    },
    "artist_music": {
        "career": "artist",
        "title": "어쿠스틱 작곡·음악가",
        "workplace": "방음 스펀지가 빛바랜 지하 녹음 작업실",
        "tool": "지판이 닳은 통기타와 오선지",
        "work_obj": "밤새 녹음한 미공개 마스터 테이프",
        "patron": "대형 음반 기획사 대표",
    },
    "artist_write": {
        "career": "artist",
        "title": "장편 소설·희곡 작가",
        "workplace": "원고지가 천장까지 쌓인 옥탑 책상",
        "tool": "펜촉이 닳은 만년필과 붉은 교정펜",
        "work_obj": "5년간 고쳐 쓴 장편 원고 상자",
        "patron": "유명 출판사 주간",
    },
    # scholar
    "scholar_healer": {
        "career": "scholar",
        "title": "공공·임상 의학자",
        "workplace": "새벽 응급차 사이렌이 울리는 지역 진료실",
        "tool": "차가운 청진기와 환자 차트철",
        "work_obj": "희귀 질환 치료제 임상 보고서",
        "patron": "대형 제약 연구소 이사",
    },
    "scholar_cosmos": {
        "career": "scholar",
        "title": "천체·기초물리 연구자",
        "workplace": "밤새 관측 로그가 찍히는 외곽 천문 연구동",
        "tool": "분광 기록지와 만년필 관측 일지",
        "work_obj": "수십 년 치 외계 항성 스펙트럼 원본 자료",
        "patron": "국책 연구단 심의위원장",
    },
    "scholar_archive": {
        "career": "scholar",
        "title": "근현대사·사회학 연구자",
        "workplace": "먼지 낀 고문헌이 들어찬 지하 서고 연구실",
        "tool": "사료 색인 카드와 돋보기",
        "work_obj": "은폐된 지역 사건들의 복원 사료철",
        "patron": "유력 학술재단 이사",
    },
    # entrepreneur
    "ent_food": {
        "career": "entrepreneur",
        "title": "생활 식품·로컬 브랜드 대표",
        "workplace": "냉동 창고 냄새가 배인 공단 모퉁이 사무실",
        "tool": "원가 계산서와 거래처 수첩",
        "work_obj": "전국 직납 유통망 계약 원장",
        "patron": "사모펀드 인수 담당자",
    },
    "ent_tech": {
        "career": "entrepreneur",
        "title": "정밀 부품·기술 벤처 대표",
        "workplace": "시제품 기판이 널린 구로 골목 3층 연구실",
        "tool": "회로 도면과 낡은 납땜기",
        "work_obj": "국산 정밀 제어 모듈 설계 원본",
        "patron": "거대 투자사 수석 파트너",
    },
    "ent_trade": {
        "career": "entrepreneur",
        "title": "독립 무역·해운 상사 개척가",
        "workplace": "부두 크레인이 보이는 항구 앞 작은 무역 사무소",
        "tool": "선적 서류 뭉치와 환율 메모장",
        "work_obj": "전 재산을 담보로 잡은 원양 화물 계약서",
        "patron": "동업자이자 투자 브로커",
    },
    # artisan
    "artn_noodle": {
        "career": "artisan",
        "title": "골목 손멸치국수 장인",
        "workplace": "새벽 네 시부터 김이 솟는 시장통 국수집 주방",
        "tool": "손때 낀 채반과 어머니의 무쇠 국자",
        "work_obj": "사십 년 묵은 씨육수 솥과 손님 외상 장부",
        "patron": "대형 외식 프랜차이즈 개발팀",
    },
    "artn_clock": {
        "career": "artisan",
        "title": "기계식 시계·정밀 목공 명장",
        "workplace": "수십 개 시계 초침이 숨 쉬는 골목 끝 공방",
        "tool": "황동 돋보기 루페와 미세 핀셋",
        "work_obj": "100년 된 괘종시계 무브먼트와 설계 도면",
        "patron": "명품 복제 납품 브로커",
    },
    "artn_tea": {
        "career": "artisan",
        "title": "전통 약초·발효 다원 마스터",
        "workplace": "솔향과 약초 덖는 냄새가 밴 산자락 다실",
        "tool": "무쇠 덖음솥과 발효 항아리",
        "work_obj": "할아버지 대부터 내려온 백년 씨앗 차 항아리",
        "patron": "유통 대기업 건강식품 사업부",
    },
    "artn_craft": {
        "career": "artisan",
        "title": "수제 제과·가죽 공예 장인",
        "workplace": "새벽 오븐 열기와 가죽 냄새가 섞인 붉은 벽돌 공방",
        "tool": "천연 효모종 단지와 닳은 재단 칼",
        "work_obj": "단골들의 이름이 적힌 맞춤 공방 주문서",
        "patron": "백화점 명품관 입점 에이전트",
    },
    # guardian
    "grd_press": {
        "career": "guardian",
        "title": "탐사 보도 기자",
        "workplace": "타자 소리와 식은 커피 냄새가 가시지 않는 탐사 보도국",
        "tool": "구형 보이스레코더와 취재 수첩",
        "work_obj": "유력 권력 비리를 담은 원본 취재 녹취 테이프",
        "patron": "방송국 보도국 윗선",
    },
    "grd_detective": {
        "career": "guardian",
        "title": "강력·미제 사건 수사관",
        "workplace": "야근 라면 냄새가 배어 있는 철야 당직 조사실",
        "tool": "사건 파일철과 닳아버린 방수 손전등",
        "work_obj": "재수사 끝판왕 미제 사건 원본 증거 상자",
        "patron": "사건 무마를 압박하는 상부 라인",
    },
    "grd_advocate": {
        "career": "guardian",
        "title": "공익·인권 조사 변호인",
        "workplace": "법전과 탄원서가 발목까지 쌓인 낡은 공익 법률 사무소",
        "tool": "탄원서 뭉치와 붉은 형광펜",
        "work_obj": "산업재해 피해자 집단소송 핵심 기밀 문건",
        "patron": "대형 로펌 영입 임원",
    },
    # wanderer
    "wnd_photo": {
        "career": "wanderer",
        "title": "다큐멘터리 사진·기행 작가",
        "workplace": "어느 항구의 방파제와 낡은 기차역 사이의 쪽방 여관",
        "tool": "필름 카메라 두 대와 해진 방수 수첩",
        "work_obj": "분쟁과 변방의 얼굴을 담은 필름 통 수백 개",
        "patron": "대형 출판사 베스트셀러 기획팀",
    },
    "wnd_relief": {
        "career": "wanderer",
        "title": "국경·오지 구호 기록가",
        "workplace": "천막 지붕 위로 모래바람과 비가 두드리는 구호소",
        "tool": "구급 배낭과 방수 기록 수첩",
        "work_obj": "고립된 마을 아이들의 신원과 진료 기록부",
        "patron": "안전한 본부 홍보국 임원",
    },
    # shadow
    "shd_broker": {
        "career": "shadow",
        "title": "상류층 비밀 해결사·정보 브로커",
        "workplace": "암막 커튼을 친 뒷골목 무명 오피스텔",
        "tool": "대포폰 두 대와 암호 난수표",
        "work_obj": "고위층 비밀 거래 내역이 담긴 이중 장부",
        "patron": "정재계 검은 손 실세",
    },
    "shd_launder": {
        "career": "shadow",
        "title": "암호 장부·자금 세탁 설계자",
        "workplace": "창문 하나 없는 지하 기계실 안쪽 비밀 사무소",
        "tool": "차명 인감 상자와 파쇄기",
        "work_obj": "수십억 검은돈의 출처가 적힌 마스터 디스크",
        "patron": "지하 금융 카르텔 총책",
    },
}


def resolve_specialty_id(life: Dict[str, Any], career_override: Optional[str] = None) -> str:
    career = career_override or str(life.get("career") or "none")
    origin_id = str(life.get("origin_id") or "orphanage")
    flags = set(life.get("flags") or [])
    saved = str(life.get("specialty") or "")
    if saved in SPECIALTY_CATALOG and SPECIALTY_CATALOG[saved]["career"] == career:
        # 만약 국수집 복귀 플래그가 뒤늦게 찍혔으면 artn_noodle 우선
        if career == "artisan" and "noodle_revival" in flags:
            return "artn_noodle"
        return saved

    if career == "artist":
        if "art_spark" in flags or origin_id in ("orphanage", "fallen_house"):
            return "artist_paint"
        if "promise_express" in flags or origin_id in ("noodle_shop", "artisan_shop"):
            return "artist_music"
        return "artist_write"
    if career == "scholar":
        if "healer_oath" in flags or origin_id == "mountain_clinic":
            return "scholar_healer"
        if "star_seed" in flags or "curious_mind" in flags or origin_id == "scholar_home":
            return "scholar_cosmos"
        return "scholar_archive"
    if career == "entrepreneur":
        if origin_id in ("noodle_shop", "mountain_clinic"):
            return "ent_food"
        if origin_id in ("artisan_shop", "scholar_home"):
            return "ent_tech"
        return "ent_trade"
    if career == "artisan":
        if "noodle_revival" in flags or origin_id == "noodle_shop":
            return "artn_noodle"
        if origin_id == "artisan_shop":
            return "artn_clock"
        if origin_id == "mountain_clinic":
            return "artn_tea"
        return "artn_craft"
    if career == "guardian":
        if "promise_express" in flags or "apt_art" in flags or origin_id == "scholar_home":
            return "grd_press"
        if "promise_protect" in flags or origin_id in ("orphanage", "fallen_house"):
            return "grd_detective"
        return "grd_advocate"
    if career == "wanderer":
        if origin_id == "mountain_clinic" or "healer_oath" in flags:
            return "wnd_relief"
        return "wnd_photo"
    if career == "shadow":
        if origin_id in ("artisan_shop", "scholar_home"):
            return "shd_launder"
        return "shd_broker"
    return "artn_craft"


def get_role_context(life: Dict[str, Any]) -> Dict[str, str]:
    career = str(life.get("career") or "none")
    if career == "none":
        return {
            "career": "none",
            "specialty_id": "none",
            "title": "성장 중 (진로 탐색)",
            "workplace": get_hometown_meta(life.get("hometown", ""))["hangout"],
            "tool": ORIGIN_LORE.get(str(life.get("origin_id") or "orphanage"), ORIGIN_LORE["orphanage"])["item_short"],
            "work_obj": "낡은 공책과 작은 소망들",
            "patron": "세상의 거친 파도",
        }
    sid = resolve_specialty_id(life, career)
    ctx = dict(SPECIALTY_CATALOG[sid])
    ctx["specialty_id"] = sid
    return ctx


def _resolve_mentor_ctx(life: Dict[str, Any]) -> Dict[str, str]:
    flags = set(life.get("flags") or [])
    origin_id = str(life.get("origin_id") or "orphanage")
    mentor = str(life.get("mentor_name") or "백 선생")

    if "apt_art" in flags:
        return {
            "name": mentor,
            "role": "반지하에서 홀로 그림과 음표를 깎아온 괴짜 예술가",
            "place": "물감과 낡은 악보가 뒤엉킨 반지하 작업실",
            "temptation": "부잣집 동급생 부모가 '미대 수시 포트폴리오를 대신 그려주고 이름만 내줘라, 두 달 알바비를 현금으로 주겠다'며 검은 봉투를 내민다",
            "lesson": "기술을 남의 이름에 팔기 시작하면, 네 손끝이 빚는 선이 가장 먼저 너를 외면할 거다.",
        }
    if "apt_study" in flags:
        return {
            "name": mentor,
            "role": "젊은 날 진실을 굽히지 않아 강단에서 내려온 은퇴 연구자",
            "place": "백열등 하나가 서가를 비추는 낡은 실험·서재방",
            "temptation": "팀 선배가 '전국 탐구대회 장학금 걸린 거 알지? 어긋난 관측값 세 줄만 지우고 평균 내자. 아무도 몰라'라며 빨간 펜을 들이민다",
            "lesson": "눈금을 한 번 속여서 얻은 답은, 평생 네가 세울 모든 가설의 발목을 잡는 모래밭이 된다.",
        }
    if "apt_justice" in flags:
        return {
            "name": mentor,
            "role": "거대 비리를 끝까지 물고 늘어졌던 해직 탐사기자",
            "place": "오래된 신문 스크랩이 벽을 채운 골목 북카페 구석",
            "temptation": "학생회 실세가 '급식 납품 비리 기사만 빼면 내년 교지 예산이랑 추천서 전부 챙겨줄게'라며 두꺼운 문화상품권 봉투를 슬쩍 밀어 넣는다",
            "lesson": "기자가 펜을 꺾는 순간은 위협을 받을 때가 아니라, 조용한 편의를 대가로 침묵을 거래할 때다.",
        }
    if "apt_craft" in flags or origin_id in ("noodle_shop", "artisan_shop", "mountain_clinic"):
        if origin_id == "noodle_shop":
            return {
                "name": mentor,
                "role": "40년간 시장 골목 육수 맛을 감별해 온 까다로운 노포 명장",
                "place": "새벽 장이 서기 전 가장 먼저 연기가 오르는 노포 뒤편",
                "temptation": "식자재 도매상이 '요즘 누가 일일이 멸치 내장을 따고 다시마를 우리냐? 값싼 분말 한 숟가락만 타면 마진이 세 배야'라며 조미료 포대를 던진다",
                "lesson": "손님은 혀가 아니라 새벽 공기로 국물을 기억한다. 주인이 요령을 부리면 국자 무게가 제일 먼저 가벼워지는 법이야.",
            }
        return {
            "name": mentor,
            "role": "손끝의 정직함 하나로 평생을 버텨온 30년 경력의 베테랑 장인",
            "place": "나무 깎는 향기와 쇳가루가 내려앉은 골목 끝 수리방",
            "temptation": "하청 업자가 '겉만 번지르르한 저가 부품을 끼워 넣고 장인 공방 도장을 찍자'며 두툼한 현금 뭉치를 작업대에 올려놓는다",
            "lesson": "물건은 주인의 손을 닮는다. 겉만 그럴싸하게 속인 물건은 반드시 가장 결정적인 날 부서져 사람을 다치게 해.",
        }
    return {
        "name": mentor,
        "role": "거친 세상 속에서 자기 방식의 규칙을 세운 동네 어른",
        "place": "기차 소리 멀리 들리는 역전 뒤편 조용한 찻집",
        "temptation": "동네 선배가 '내용물도 묻지 말고 역 앞 코인라커에서 봉투만 옮겨주면 한 번에 반년 용돈을 준다'며 열쇠를 흔든다",
        "lesson": "공짜처럼 보이는 대가에는 반드시 네 이름과 자존심이 담보로 잡혀 있다.",
    }


# ==========================================
# 5. 포맷 변수 빌더 (한국어 조사·고향·전공·인연 완벽 통합)
# ==========================================
def fmt_life_vars(life: Dict[str, Any]) -> Dict[str, Any]:
    origin_id = str(life.get("origin_id") or "orphanage")
    lore = ORIGIN_LORE.get(origin_id, ORIGIN_LORE["orphanage"])
    ht = get_hometown_meta(str(life.get("hometown") or ""))
    role = get_role_context(life)
    mentor_ctx = _resolve_mentor_ctx(life)

    name = str(life.get("name") or "이안")
    comp = str(life.get("companion_name") or "지우")
    adult_p = str(life.get("adult_partner_name") or "서연")
    partner = str(life.get("partner_name") or adult_p)
    mentor = str(life.get("mentor_name") or "백 선생")
    item_s = lore["item_short"]

    tps = [str(t) for t in (life.get("turning_points") or []) if t]

    return {
        "name": name,
        "name_eun": j_eun(name),
        "name_i": j_i(name),
        "name_eul": j_eul(name),
        "name_wa": j_wa(name),
        "name_ya": j_ya(name),
        "name_aff_eun": aff_eun(name),
        "name_eul_s": p_eul(name),
        "name_i_s": p_i(name),
        "comp": comp,
        "companion": comp,
        "comp_eun": j_eun(comp),
        "comp_i": j_i(comp),
        "comp_eul": j_eul(comp),
        "comp_wa": j_wa(comp),
        "comp_ya": j_ya(comp),
        "adult_partner": adult_p,
        "adult_wa": j_wa(adult_p),
        "adult_i": j_i(adult_p),
        "adult_eul": j_eul(adult_p),
        "partner": partner,
        "partner_eun": j_eun(partner),
        "partner_i": j_i(partner),
        "partner_eul": j_eul(partner),
        "partner_wa": j_wa(partner),
        "partner_i_s": p_i(partner),
        "partner_wa_s": p_wa(partner),
        "mentor": mentor,
        "mentor_i": j_i(mentor),
        "mentor_eun": j_eun(mentor),
        "mentor_wa": j_wa(mentor),
        "mentor_i_s": p_i(mentor),
        "mentor_wa_s": p_wa(mentor),
        "mentor_role": mentor_ctx["role"],
        "mentor_place": mentor_ctx["place"],
        "mentor_tempt": mentor_ctx["temptation"],
        "mentor_lesson": mentor_ctx["lesson"],
        "origin_id": origin_id,
        "origin_place": lore["place"],
        "origin_guardian": lore["guardian"],
        "guardian_i_s": p_i(lore["guardian"]),
        "guardian_eun_s": p_eun(lore["guardian"]),
        "origin_item": lore["item_full"],
        "item_short": item_s,
        "item_eun": j_eun(item_s),
        "item_eul": j_eul(item_s),
        "item_ro": j_ro(item_s),
        "item_i": j_i(item_s),
        "item_i_s": p_i(item_s),
        "item_eul_s": p_eul(item_s),
        "memory_anchor": lore["memory_anchor"],
        "hometown": ht["full"],
        "city": ht["city"],
        "city_eul": j_eul(ht["city"]),
        "city_wa": j_wa(ht["city"]),
        "hangout": ht["hangout"],
        "night_spot": ht["night_spot"],
        "station": ht["station"],
        "sensory": ht["sensory"],
        "sensory_i": j_i(ht["sensory"]),
        "career": role["career"],
        "career_label": role["title"],
        "specialty": role["title"],
        "specialty_ro_s": p_ro(role["title"]),
        "specialty_id": role["specialty_id"],
        "workplace": role["workplace"],
        "tool": role["tool"],
        "tool_eul": j_eul(role["tool"]),
        "tool_eul_s": p_eul(role["tool"]),
        "work_obj": role["work_obj"],
        "work_obj_i_s": p_i(role["work_obj"]),
        "work_obj_eul_s": p_eul(role["work_obj"]),
        "work_obj_eun_s": p_eun(role["work_obj"]),
        "work_obj_eul": j_eul(role["work_obj"]),
        "patron": role["patron"],
        "patron_eun_s": p_eun(role["patron"]),
        "patron_i_s": p_i(role["patron"]),
        "age": int(life.get("age") or 6),
        "turning_points": tps,
    }


def _make_node(
    node_id: str,
    title: str,
    body: str,
    years_advance: int,
    choices: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "id": node_id,
        "title": title,
        "body": body,
        "years_advance": years_advance,
        "choices": choices,
    }


def _prev_bridge(life: Dict[str, Any], v: Dict[str, Any]) -> str:
    """직전 선택의 인과를 현재 챕터 도입부에 자연스럽게 잇는 1문장 브릿지"""
    pc = str(life.get("prev_choice_id") or "")
    flags = set(life.get("flags") or [])
    if not pc:
        return ""
    if pc == "b1_curious":
        return f"그날 다락에서부터 무엇이든 까닭을 파고들던 버릇이 배어, {v['name_eun']} 주머니마다 메모지를 꽂고 다니는 아이가 되었습니다."
    if pc == "b1_feel":
        return f"그날의 색과 소리를 서툴게 그려내던 손길 이후, {v['name_eun']} 혼자만의 공책에 본 것들을 옮겨 적으며 크고 있었습니다."
    if pc == "b1_work":
        return f"그날 작은 두 손으로 직접 부딪혀 본 이후, {v['name_eun']} 말보다 몸이 먼저 움직이는 단단한 아이로 자랐습니다."
    if pc == "b2_close":
        return f"비 오던 {v['hangout']} 이후로 {v['comp_wa']} 나눈 우정은 금세 동네에서 소문난 단짝 사이로 깊어졌습니다."
    if pc == "b2_rival":
        return f"그날 빗속에서 자존심을 걸고 달린 뒤, {v['comp_wa']} 마주칠 때마다 눈빛으로 불꽃을 튀기는 경쟁이 일상이 되었습니다."
    if pc == "b2_solo":
        return f"우산을 내어주고 혼자 남았던 그 오후처럼, {v['name_eun']} 왁자지껄한 무리보다 한 걸음 뒤에서 세상을 관찰하곤 했습니다."
    if pc == "b3_protect":
        return f"열두 살 겨울, 남보다 먼저 어깨를 들이밀며 버텼던 기억은 어느새 {v['name']}의 걸음걸이까지 묵직하게 바꾸어 놓았습니다."
    if pc == "b3_truth":
        return f"감정보다 원인을 짚어 돌파구를 찾았던 그날의 기억 덕분에, {v['name_eun']} 복잡한 세상 앞에서도 좀처럼 당황하지 않았습니다."
    if pc == "b3_express":
        return f"무너지는 밤을 낡은 공책과 선율로 견뎌낸 열두 살 이후, {v['name']}에게 표현한다는 것은 살아남는 방식 그 자체가 되었습니다."
    if pc == "b5_honest":
        return f"부당한 지름길을 거절하고 {v['mentor']} 곁에서 늦은 밤까지 기본기를 깎았던 땀방울이 손바닥에 굳은살로 남았습니다."
    if pc == "b5_shortcut":
        return f"주머니 속에 찔러 넣었던 첫 편법의 대가는 생각보다 가볍지 않아, {v['name_eun']} 잘 웃다가도 문득 뒤를 돌아보곤 했습니다."
    if pc == "b5_rebel":
        return f"{v['mentor']}의 틀마저 깨고 나온 뒤, {v['name_eun']} 아무도 걷지 않은 길 위에서 넘어지며 자기만의 감각을 시험했습니다."
    if pc == "b6_comp_promise":
        return f"열여덟 마지막 밤, {v['night_spot']}에서 {v['comp_wa']} 손가락을 걸던 따스한 온기는 먼 타지에서도 좀처럼 식지 않았습니다."
    if pc == "b6_comp_cold":
        return f"스스로 마음을 얼리고 떠났던 그 겨울 밤 이후, {v['name_eun']} 누군가 가까이 다가올 때마다 한 걸음씩 물러서는 버릇이 생겼습니다."
    if pc == "d_wnd_smug":
        return f"항구의 어두운 창고에서 손을 더럽혔던 그 밤 이후, {v['name']}의 이름표 앞에는 정식 직함 대신 은밀한 암호명이 붙기 시작했습니다."
    if pc == "b10_noodle_pivot":
        return f"화려한 바깥세상의 계급장을 내려놓고 다시 {v['city']} 골목으로 돌아온 {v['name']} 앞에는 오래된 육수 가마솥의 김이 피어오르고 있었습니다."
    if pc == "b10_compromise":
        return f"서른의 문턱에서 양심 대신 현실의 조건을 택했던 그날의 도장은, 높은 천장과 두꺼운 통장을 안겨준 대신 잠자리를 서늘하게 식혀 갔습니다."
    if pc == "b10_stand":
        return f"손해를 각오하고 거대 조건을 걷어찼던 서른 살의 선택 이후, 손에 쥔 돈은 줄었을지언정 {v['name']}의 눈빛만은 누구 앞에서도 흔들리지 않았습니다."
    if pc == "b11_fam_work" and "partner_strained" in flags:
        return f"집을 위한다는 핑계로 새벽마다 현관문만 닫고 나섰던 서른넷 이후, 식탁 위에는 식은 반찬과 두 사람의 짧은 한숨만 늘어 갔습니다."
    if pc == "b11_solo_burn" and "overworked" in flags:
        return f"잠을 깎아가며 몸을 몰아붙였던 서른넷 이후, 계단 몇 칸만 올라가도 가슴 한구석이 욱신거리는 신호가 잦아졌습니다."
    if pc == "b12_heroic_risk" and "wise_survivor" not in flags:
        return f"서른아홉의 참혹한 밤, 목숨을 내던져 사람을 건져낸 뒤 손등과 어깨에 남은 짙은 화상 자국은 {v['name_i']} 무엇을 지키며 살았는지 말없이 증명했습니다."
    if pc == "b14_redeem":
        return f"쉰 살의 문턱에서 스스로 고개를 숙이고 가진 것을 전부 내려놓았던 날, {v['name_eun']} 평생 처음으로 숨이 턱까지 차지 않는 밤을 잤습니다."
    return ""


# ==========================================
# 6. BEAT 1~3 : 유년기 (6세 · 9세 · 12세)
# ==========================================
def _build_childhood_node(beat: int, life: Dict[str, Any], v: Dict[str, Any]) -> Dict[str, Any]:
    age = v["age"]
    oid = v["origin_id"]
    flags = set(life.get("flags") or [])
    bridge = _prev_bridge(life, v)
    bline = f"{bridge}\n\n" if bridge else ""

    # ── BEAT 1 (6세: 첫 기억) ──
    if beat == 1:
        origin_bodies = {
            "orphanage": (
                f"{v['sensory_i']} 스며드는 {v['city']}의 낡은 **바닷가 보육원 '해송원'**. "
                f"비바람이 창틀을 흔들던 어느 오후, 여섯 살 {v['name_eun']} 원장 수녀님이 아껴두시던 삐걱이는 다락 창고로 몰래 올라갔습니다.\n\n"
                f"거미줄을 걷어내고 연 낡은 나무 상자 안에는 표지가 젖은 바닷새 백과사전과 물 빠진 색연필 한 줌, "
                f"그리고 햇빛이 스칠 때마다 푸른빛을 뿜는 **{v['item_short']}** 하나가 곱게 싸여 있었습니다. "
                f"세상에서 처음 온전히 '내 것'이라 부를 만한 비밀이 두 손 안에 들어온 순간입니다."
            ),
            "noodle_shop": (
                f"아직 가로등도 꺼지지 않은 새벽 네 시, {v['sensory']} 속에서 **시장통 멸치국수집**의 가마솥이 가장 먼저 눈을 뜹니다. "
                f"뜨거운 수증기가 천장까지 차오르는 주방 한켠, 여섯 살 {v['name_eun']} 작은 나무 의자 위에 올라앉아 멸치 머리를 따고 계신 어머니의 거친 손을 가만히 바라봅니다.\n\n"
                f"\"우리 {v['name_aff_eun']} 이 새벽 냄새가 싫지 않니?\" 어머니가 건네신 맑은 멸치 육수 한 모금과 무겁고 까만 **{v['item_short']}**. "
                f"허름한 비닐 천막 밖으로 새벽 시장 첫 버스가 불을 켜고 지나갑니다."
            ),
            "scholar_home": (
                f"오래된 먹 냄새와 누렇게 바랜 종이 냄새가 집 안 구석구석에 배어 있는 {v['city']}의 **한옥 서재 집안**. "
                f"아버지의 서재에는 천장까지 책이 빽빽했고, 여섯 살 {v['name_eun']} 어른들의 기대 속에서 '실수하지 않는 법'부터 먼저 배웠습니다.\n\n"
                f"하지만 책장이 삐걱이는 고요한 밤이면, {v['name']}의 시선은 늘 높은 대들보 사이 작은 창으로 쏟아지는 밤별과 "
                f"책상 귀퉁이에 놓인 아버지의 낡은 **{v['item_short']}** 위에 오래 머물렀습니다."
            ),
            "fallen_house": (
                f"비싸 보이던 샹들리에 아래 붉은 압류 딱지가 하나둘 붙기 시작한 {v['city']}의 **붉은 벽돌 저택**. "
                f"어른들이 안방에서 낮은 목소리로 다투며 한숨을 내쉴 때마다, 여섯 살 {v['name_eun']} 텅 빈 거실 마루 끝에 쪼그려 앉아 차가운 대리석 무늬를 세곤 했습니다.\n\n"
                f"그날 저녁, 문밖으로 쫓기듯 나가는 빚쟁이들의 구두 소리 뒤편에서 {v['name_eun']} 화단 틈에 떨어진 무거운 **{v['item_short']}** 하나를 주워 들었습니다. "
                f"이 커다란 집에서 기댈 곳은 결국 제 두 손뿐이라는 사실이 어린 마음에도 또렷이 새겨집니다."
            ),
            "artisan_shop": (
                f"크고 작은 괘종시계와 손목시계 수십 개가 저마다 다른 박자로 째깍거리는 {v['city']} 골목 끝의 **시계·목공 수리점**. "
                f"아버지가 손님 배웅을 하러 나간 짧은 틈, 여섯 살 {v['name_eun']} 대패질 냄새가 풍기는 작업대 위로 턱을 괴었습니다.\n\n"
                f"초록색 고무 매트 위에는 뚜껑이 열린 낡은 회중시계 하나와 구리빛으로 반짝이는 **{v['item_short']}**{v['item_i_s']} 나란히 놓여 있습니다. "
                f"멈춰 선 작은 톱니바퀴 하나가 아이의 시선을 통째로 붙잡았습니다."
            ),
            "mountain_clinic": (
                f"새벽마다 지리산 골짜기처럼 서늘한 안개가 마당을 덮는 {v['city']} 언덕 위의 **산골 약초방**. "
                f"할아버지가 쇠절구로 약재를 빻는 규칙적인 소리를 들으며 뒤뜰로 나온 여섯 살 {v['name_eun']}, 처마 밑 마른 잎 사이에서 작게 떠는 산새 한 마리를 발견했습니다.\n\n"
                f"할아버지의 품에서 꺼낸 **{v['item_short']}** 위로 햇살이 쏟아지고, 날개 끝이 꺾인 작은 생명 하나가 여섯 살 아이의 손바닥 안에서 가녀리게 숨을 쉽니다."
            ),
        }
        return _make_node(
            "b1_origin",
            f"🌅 {age}세의 첫 기억 — {v['city']}의 {v['origin_place']}",
            origin_bodies.get(oid, origin_bodies["orphanage"]),
            3,
            [
                {
                    "id": "b1_curious",
                    "label": "🔍 원리와 이유를 끝까지 묻고 관찰한다",
                    "hint": "지성 +6 · 공감 +1 · 사물의 이치와 별을 쫓는 씨앗",
                    "delta": {"intellect": 6, "empathy": 1},
                    "add_flags": ["curious_mind", "star_seed"],
                    "log": f"{v['origin_place']}에서 {v['item_eul']} 손에 쥐고 세상의 원리와 별의 까닭을 묻기 시작했다.",
                    "tp": f"6세: {v['origin_place']}에서 '왜 그럴까?'라는 첫 질문을 가슴에 품다.",
                    "outcome": (
                        f"{v['name_eun']} 몇 시간이고 꼼짝하지 않은 채 {v['item_eul']} 이리저리 비추어 보았습니다. "
                        f"\"왜 그림자가 길어져요? 저기 별은 어디서 와요?\" 멈추지 않는 질문 앞에서 {v['origin_guardian']}도 결국 빙그레 웃으며 낡은 공책 한 권을 내어주었습니다."
                    ),
                },
                {
                    "id": "b1_feel",
                    "label": "🎨 떠오른 색깔과 감정을 손과 목소리로 표현한다",
                    "hint": "열정 +6 · 공감 +2 · 예술과 서정의 씨앗",
                    "delta": {"passion": 6, "empathy": 2},
                    "add_flags": ["art_spark"],
                    "log": f"그날 본 {v['city']}의 빛깔과 감정을 서툰 그림과 흥얼거림으로 옮겼다.",
                    "tp": f"6세: 말로 다 담기지 않는 감정을 선과 소리로 빚어내는 즐거움을 알다.",
                    "outcome": (
                        f"종이 모서리가 닳도록 크레파스를 문지르고 작은 콧노래를 흥얼거리는 동안, "
                        f"어수선하던 {v['origin_place']}의 공기가 신기할 만큼 따뜻하게 누그러졌습니다. "
                        f"그날 아이가 그린 서툰 선 하나는 훗날까지도 지워지지 않을 감각의 첫 획이 됩니다."
                    ),
                },
                {
                    "id": "b1_work",
                    "label": "🛡️ 망설이지 않고 두 손을 움직여 직접 돌보고 고친다",
                    "hint": "근성 +6 · 자산 +2 · 현실을 감당하는 단단한 손끝",
                    "delta": {"grit": 6, "wealth": 2},
                    "add_flags": ["craft_hands"],
                    "log": f"여섯 살의 작은 손으로 직접 눈앞의 일을 보살피며 현실의 감각을 익혔다.",
                    "tp": f"6세: 말보다 먼저 손을 뻗어 작은 것들을 지키고 고치는 법을 배우다.",
                    "outcome": (
                        f"{v['name_eun']} 작은 헝겊을 적셔 얼룩을 닦고 삐뚤어진 자리를 조심스레 맞췄습니다. "
                        f"\"아이고, 우리 {v['name_i']} 손끝이 벌써 야무지네.\" {v['origin_guardian']}의 따뜻한 칭찬이 어린 손등에 오랫동안 남았습니다."
                    ),
                },
            ],
        )

    # ── BEAT 2 (9세: 고향 놀이터에서 만난 소꿉친구 {companion}) ──
    if beat == 2:
        meet_map = {
            "orphanage": (
                f"소나기가 몰아치고 난 뒤 붉은 노을이 깔린 **{v['hangout']}**.\n"
                f"보육원 아이들 몰래 혼자 파도 틈에서 예쁜 조개껍데기를 줍던 {v['name']} 귀에 다급한 외침이 들립니다. "
                f"물 빠진 바위 틈에 구두 한 짝이 낀 채 울상을 짓고 있는 동갑내기 **{v['comp']}**입니다. 무릎엔 붉은 찰과상, 손에는 눅눅해진 종이배 두 척이 들려 있습니다."
            ),
            "noodle_shop": (
                f"장대비가 쏟아지는 시장 골목, 천막 끝에서 빗물이 폭포처럼 흘러내리는 **{v['hangout']}** 옆.\n"
                f"빈 그릇을 정리하던 {v['name_eun']} 가게 비닐 가림막 틈새로 따뜻한 멸치 육수 김을 하염없이 바라보던 동갑내기 **{v['comp_eul']}** 발견했습니다. "
                f"교복 대신 물 빠진 체육복을 입은 아이의 손에는 꼬깃꼬깃 젖은 오백 원짜리 동전 한 개와 반쪽짜리 우산이 들려 있습니다."
            ),
            "scholar_home": (
                f"개학식 날, 무거운 책가방을 메고 들른 **{v['hangout']}**의 낮은 돌담 아래.\n"
                f"담장 너머로 떨어진 파란 비행기 모형을 찾으려 까치발을 들던 {v['name']} 머리 위로, 흙투성이 운동화를 신은 동갑내기 **{v['comp_i']}** 훌쩍 담을 뛰어내립니다. "
                f"\"야, 이거 네 거지?\" 씨익 웃는 아이의 팔꿈치엔 방금 넘어졌는지 흙먼지가 잔뜩 묻어 있습니다."
            ),
            "fallen_house": (
                f"주인이 떠나버린 집 뒤편, 깨진 유리창 사이로 덩굴이 자란 **{v['hangout']}** 모퉁이.\n"
                f"어른들 몰래 혼자 낡은 열쇠를 만지작거리던 {v['name_eun']} 안쪽 구석에서 작은 강아지에게 호빵을 쪼개 나눠주는 **{v['comp_wa']}** 눈이 마주쳤습니다. "
                f"\"어, 여긴 비밀 기지인데! 너도 비 피하러 온 거야?\""
            ),
            "artisan_shop": (
                f"하굣길 빗줄기가 세차게 유리창을 두드리던 **{v['hangout']}** 앞.\n"
                f"수리점 진열장 앞에서 부서진 장난감 태엽을 쥔 채 입술을 꾹 깨물고 서 있던 동갑내기 **{v['comp']}**. "
                f"안에서 시계 톱니를 닦던 {v['name_i']} 문을 빼꼼 열자, 아이는 머쓱한 듯 젖은 손으로 목덜미를 긁적입니다."
            ),
            "mountain_clinic": (
                f"안개가 허리춤까지 내려앉아 앞이 잘 보이지 않던 **{v['hangout']}** 샛길.\n"
                f"약초 바구니를 메고 내려오던 {v['name_eun']} 나무뿌리에 발목이 꺾인 채 씩씩거리며 주저앉아 있는 동갑내기 **{v['comp_eul']}** 만났습니다. "
                f"\"괜찮아, 나 안 울었어! 그냥 돌부리가 나빠서 그래!\" 고집 센 눈동자가 안개 너머로 맑게 빛납니다."
            ),
        }
        return _make_node(
            "b2_companion",
            f"☔ {age}세 — {v['city']}에서 만난 동갑내기 '{v['comp']}'",
            bline + meet_map.get(oid, meet_map["orphanage"]),
            3,
            [
                {
                    "id": "b2_close",
                    "label": f"☂️ 망설임 없이 다가가 {v['comp']}의 젖은 어깨를 감싸며 친구가 된다",
                    "hint": "공감 +7 · 근성 +1 · 평생 마음을 나눌 소꿉친구 인연",
                    "delta": {"empathy": 7, "grit": 1},
                    "add_flags": ["comp_close"],
                    "set_comp_rel": "close",
                    "log": f"{v['hangout']}에서 {v['comp_wa']} 온기를 나누며 둘도 없는 소꿉친구가 되었다.",
                    "tp": f"9세: {v['comp_wa']} 처음 손을 맞잡으며 혼자가 아니라는 기쁨을 알다.",
                    "outcome": (
                        f"\"이거 반 나눌래?\" {v['name_i']} 조심스레 내민 손에 {v['comp_eun']} 잠시 놀라더니 금세 환하게 웃었습니다. "
                        f"그날 해가 질 때까지 두 아이는 {v['hangout']}에 나란히 앉아 자기 집 비밀번호보다 더 은밀한 어린 시절의 꿈을 털어놓았습니다."
                    ),
                },
                {
                    "id": "b2_rival",
                    "label": f"🏃 \"울보처럼 굴지 말고 나랑 누가 먼저 저기까지 가나 내기하자!\"",
                    "hint": "열정 +6 · 근성 +3 · 서로를 끌어올리는 라이벌 인연",
                    "delta": {"passion": 6, "grit": 3},
                    "add_flags": ["comp_rival"],
                    "set_comp_rel": "rival",
                    "log": f"{v['comp_wa']} 자존심을 건 달리기를 하며 평생 지지 않으려는 유쾌한 라이벌이 되었다.",
                    "tp": f"9세: {v['comp_eul']} 만나 지고 싶지 않은 마음에서 나오는 뜨거운 승부욕을 배우다.",
                    "outcome": (
                        f"\"뭐야, 너 꽤 빠르네?\" 빗물 웅덩이를 첨벙거리며 뛰어간 끝에 두 아이는 누가 먼저랄 것도 없이 땅바닥에 뻗어 거친 숨을 몰아쉬었습니다. "
                        f"\"다음엔 내가 꼭 이길 거야!\" 서로를 노려보며 터진 웃음소리가 {v['city']} 골목에 오래 울려 퍼졌습니다."
                    ),
                },
                {
                    "id": "b2_solo",
                    "label": "📓 필요한 도움만 건네고 한 걸음 물러나 내 공책으로 돌아간다",
                    "hint": "지성 +6 · 자산 +2 · 누구에게도 휩쓸리지 않는 고독한 관찰자",
                    "delta": {"intellect": 6, "wealth": 2},
                    "add_flags": ["comp_solo"],
                    "set_comp_rel": "solo",
                    "log": f"{v['comp']}에게 필요한 도움만 건넨 뒤 다시 나만의 사색과 기록으로 돌아갔다.",
                    "tp": f"9세: 다정함 대신 거리를 두며 혼자 서서 세상을 기록하는 법을 익히다.",
                    "outcome": (
                        f"{v['comp_i']} 돌아서며 \"고마워, 이름은 뭐야?\" 하고 불렀지만, {v['name_eun']} 작게 손만 들어 보이고는 조용히 발걸음을 돌렸습니다. "
                        f"누군가와 부대끼는 온기 대신, 그날 밤 공책에 꾹꾹 눌러쓴 또렷한 문장들이 {v['name']}의 든든한 방패가 되어주었습니다."
                    ),
                },
            ],
        )

    # ── BEAT 3 (12세: 환경의 첫 현실 시련 + 동반자/유품 콜백) ──
    if beat == 3:
        trial_desc = {
            "orphanage": (
                f"겨울 문턱의 차가운 밤, {v['origin_place']}에 큰일이 닥쳤습니다. 평생 아이들을 먹여 살리던 **{v['origin_guardian']}**{v['guardian_i_s']} 결국 과로로 쓰러지고, "
                f"원생들을 흩어 보낼 수도 있다는 소문이 동네에 돌기 시작합니다. 열두 살 {v['name']} 앞에는 낡은 장부와 아직 철없는 동생들의 겁먹은 눈빛이 놓여 있습니다."
            ),
            "noodle_shop": (
                f"골목 어귀에 번쩍이는 대형 마트와 프랜차이즈 음식점이 들어서면서, 손님이 북적이던 **시장통 국수집**에 파리만 날리기 시작했습니다. "
                f"밤 열두 시 불 꺼진 주방에서 계산기를 두드리며 조용히 눈물을 훔치는 **{v['origin_guardian']}**의 어깨가 그날 유독 뼈가 드러날 만큼 작아 보입니다."
            ),
            "scholar_home": (
                f"집안의 모든 기대를 짊어지고 본 큰 시험에서 딱 두 문제 차이로 수석을 놓친 밤. "
                f"**{v['origin_guardian']}**{v['guardian_eun_s']} 한마디 꾸짖음도 없이 차갑게 방문을 닫았고, 서재의 싸늘한 침묵이 열두 살 {v['name']}의 목을 묵직하게 조여 옵니다."
            ),
            "fallen_house": (
                f"유예 기간이 끝난 아침, **{v['origin_place']}** 정문에 차가운 경매 안내장이 붙고 낯선 사람들이 마당으로 들어왔습니다. "
                f"단칸방으로 옮길 트럭 짐칸 위에서 억지로 웃어 보이는 **{v['origin_guardian']}**의 손이 덜덜 떨리고 있습니다."
            ),
            "artisan_shop": (
                f"수십 년간 작은 부품 하나 놓치지 않던 **{v['origin_guardian']}**의 손가락 관절이 퉁퉁 부어 핀셋조차 쥐지 못하게 된 어느 날. "
                f"고급 시계 수리 의뢰가 모두 끊기고, 문틈으로 꽂힌 월세 독촉장이 차가운 공방 바닥 위에 떨어졌습니다."
            ),
            "mountain_clinic": (
                f"사흘간 멈추지 않은 폭우로 아랫마을 다리가 끊겨버린 한밤중. "
                f"고열로 의식을 잃어가는 독거 어르신을 앞에 두고 연로한 **{v['origin_guardian']}**의 약재 가방마저 비어가며 긴박한 밤이 찾아왔습니다."
            ),
        }
        if "comp_close" in flags:
            comp_scene = f"\n\n그 막막한 문턱에 쪼그려 앉아 있을 때, 골목 저편에서 **{v['comp_i']}** 호빵 봉지를 품에 안고 숨을 헐떡이며 달려왔습니다. \"야, 혼자 앓지 마. 내가 뭐 도울 거 없어?\""
        elif "comp_rival" in flags:
            comp_scene = f"\n\n입술을 깨물고 주저앉으려던 찰나, **{v['comp_i']}** 툭툭 어깨를 치고 지나가며 말했습니다. \"네가 여기서 기 죽으면 다음번 내기도 재미없잖아. 정신 차려!\""
        else:
            comp_scene = f"\n\n아무도 찾아오지 않는 적막한 밤, 주머니 속에서 꽉 쥔 **{v['item_short']}**의 차가운 감촉만이 열두 살 {v['name_eul']} 깨어 있게 했습니다."

        return _make_node(
            "b3_trial",
            f"🌩️ {age}세 — 어린 어깨를 내리누른 첫 현실의 벽",
            bline + trial_desc.get(oid, trial_desc["orphanage"]) + comp_scene,
            2,
            [
                {
                    "id": "b3_protect",
                    "label": "💪 내가 먼저 팔을 걷어붙여 곁의 사람들과 집안을 돕는다",
                    "hint": "근성 +7 · 자산 +4 · 끝까지 버텨내는 생활의 책임감",
                    "delta": {"grit": 7, "wealth": 4},
                    "add_flags": ["promise_protect"],
                    "log": "열두 살의 가혹한 현실 앞에서 주저앉지 않고 두 손으로 곁의 사람들을 받치기 시작했다.",
                    "tp": f"12세: 무너져가는 현실 앞에서 피하지 않고 '내 힘으로 곁을 지키겠다'고 맹세하다.",
                    "outcome": (
                        f"새벽 신문 배달이든 막일 심부름이든 열두 살이 할 수 있는 모든 일을 닥치는 대로 해냈습니다. "
                        f"손마디가 터져 쓰라린 밤에도 {v['origin_guardian']}의 얼굴에 잠깐 스치는 안도의 빛을 보며 {v['name_eun']} 어른이 될 결심을 굳혔습니다."
                    ),
                },
                {
                    "id": "b3_truth",
                    "label": "🧠 감정 대신 문제의 구조를 차분히 파고들어 해결책을 찾는다",
                    "hint": "지성 +7 · 공감 +2 · 본질과 원리를 꿰뚫는 냉철함",
                    "delta": {"intellect": 7, "empathy": 2},
                    "add_flags": ["promise_truth"],
                    "log": "막막한 위기 속에서도 원인과 구조를 차분히 기록하며 돌파구의 실마리를 찾았다.",
                    "tp": f"12세: 절망에 휩쓸리지 않고 문제의 뿌리를 추적하는 냉철한 시선을 얻다.",
                    "outcome": (
                        f"{v['name_eun']} 밤새 낡은 계약서와 가계부, 관공서 안내문과 도서관 책을 뒤지며 무엇이 잘못되었는지 조목조목 짚어냈습니다. "
                        f"\"어린애 눈빛이 어떻게 저렇게 형형할까.\" 어른들마저 감탄할 만큼 단단한 논리가 그날 밤 완성되었습니다."
                    ),
                },
                {
                    "id": "b3_express",
                    "label": "🎵 흔들리는 마음과 슬픔을 노트에 글·그림·선율로 새기며 버틴다",
                    "hint": "열정 +7 · 공감 +3 · 아픔을 예술적 언어로 승화시키는 힘",
                    "delta": {"passion": 7, "empathy": 3},
                    "add_flags": ["promise_express"],
                    "log": "버거운 슬픔을 낡은 공책 한 권의 문장과 선율로 옮기며 마음을 단단히 붙들었다.",
                    "tp": f"12세: 캄캄한 겨울밤의 고통을 아름다운 표현과 이야기로 번역하는 법을 깨닫다.",
                    "outcome": (
                        f"불 꺼진 구석에서 닳아가는 연필로 밤새 그날의 풍경과 울음을 공책 가득 채웠습니다. "
                        f"종이 위에 마음을 다 쏟아내고 나자 신기하게도 내일을 버틸 숨결이 다시 돌아왔고, 그 공책은 첫 번째 보물이 되었습니다."
                    ),
                },
            ],
        )


# ==========================================
# 7. BEAT 4~6 : 청소년기 (14세 · 16세 · 18세)
# ==========================================
def _build_teen_node(beat: int, life: Dict[str, Any], v: Dict[str, Any]) -> Dict[str, Any]:
    age = v["age"]
    oid = v["origin_id"]
    flags = set(life.get("flags") or [])
    bridge = _prev_bridge(life, v)
    bline = f"{bridge}\n\n" if bridge else ""

    # ── BEAT 4 (14세: 중학교 동아리와 정체성) ──
    if beat == 4:
        comp_peek = (
            f"복도 창가에서는 **{v['comp_i']}** 자기 반 교실 쪽에서 손을 흔들며 이쪽 포스터 게시판을 넘겨다보고 있고, "
            if "comp_close" in flags
            else (
                f"전교 석차표 앞에서 매번 나란히 이름을 견주던 **{v['comp_eun']}** 이미 벌써 다른 동아리 방으로 들어간 모양이고, "
                if "comp_rival" in flags
                else f"시끌벅적한 새 학기 복도 틈에서도 늘 그렇듯 한 걸음 떨어져 선 {v['name_eun']} 홀로 게시판을 응시합니다. "
            )
        )
        origin_tension = {
            "scholar_home": "집안 어른들이 바라는 이른바 '안정된 명문 진학 코어'를 따를지 가슴 한구석이 묵직하지만, ",
            "fallen_house": "당장 교복 소매가 해져도 스스로 앞길을 뚫어야 한다는 조급함이 앞서지만, ",
            "noodle_shop": "방과 후에는 멸치국수집 배달과 설거지를 도와야 하는 형편이지만, ",
        }.get(oid, "")

        return _make_node(
            "b4_aptitude",
            f"🏫 {age}세 — 사춘기의 오후, 가슴이 먼저 반응한 네 장의 포스터",
            (
                f"{bline}교복 깃이 조금씩 몸에 익어가는 중학교 2학년 봄날의 방과 후. "
                f"{origin_tension}{comp_peek}햇살이 비스듬히 내리꽂히는 중앙 복도 게시판 앞에 선 {v['name']}의 눈이 네 갈래 모집 공고 위를 오갑니다.\n\n"
                f"이 시간 이후 매일 저녁 어디서 무엇을 붙들고 땀을 흘릴지가 곧 열아홉 살 스무 살의 얼굴을 결정지을 것입니다."
            ),
            2,
            [
                {
                    "id": "b4_art",
                    "label": "🎨 문예·미술·음악창작반 — 내 안의 세계를 빛과 소리로 빚는다",
                    "hint": "열정 +7 · 공감 +2 · 예술·창작 루트 핵심 적성",
                    "delta": {"passion": 7, "empathy": 2},
                    "add_flags": ["apt_art"],
                    "log": "방과 후 낡은 예술실 창가에서 그림·선율·문장으로 세상을 번역하기 시작했다.",
                    "tp": f"14세: 정해진 정답보다 나만의 색깔을 표현하는 예술창작반에 가슴을 걸다.",
                    "outcome": (
                        f"물감 냄새와 낡은 피아노 건반 소리, 구겨진 원고지 더미 속에 발을 들인 첫날부터 {v['name_eun']} 시간 가는 줄을 몰랐습니다. "
                        f"누가 시키지 않아도 해 질 녘 교실에 홀로 남아 습작을 반복하는 사이, 두 눈에는 이상한 불꽃이 깃들었습니다."
                    ),
                },
                {
                    "id": "b4_study",
                    "label": "🔬 과학·천문·독서탐구반 — 세상의 법칙과 인간의 구조를 파고든다",
                    "hint": "지성 +8 · 학문·의학·천문 루트 핵심 적성 · [별의 씨앗+]",
                    "delta": {"intellect": 8},
                    "add_flags": ["apt_study", "star_seed"],
                    "log": "과학실과 도서관 구석을 누비며 별자리와 인체·역사의 구조를 탐구했다.",
                    "tp": f"14세: 밤늦은 도서관에서 우주의 원리와 세상의 법칙을 탐구하는 기쁨에 눈뜨다.",
                    "outcome": (
                        f"옥상 망원경에 맺힌 목성의 줄무늬와 두꺼운 백과사전의 도표들을 옮겨 적으며 {v['name_eun']} 전율을 느꼈습니다. "
                        f"거대하고 무질서해 보이던 세상에도 분명 숨겨진 아름다운 규칙이 있다는 믿음이 머릿속에 깊이 뿌리내렸습니다."
                    ),
                },
                {
                    "id": "b4_justice",
                    "label": "📰 교지편집·탐사·봉사반 — 가려진 진실과 약자의 목소리를 적는다",
                    "hint": "공감 +6 · 근성 +3 · 수호·언론·기록 루트 핵심 적성",
                    "delta": {"empathy": 6, "grit": 3},
                    "add_flags": ["apt_justice"],
                    "log": "학교와 골목 안팎의 부당한 일을 기록하고 묵묵히 목소리를 내기 시작했다.",
                    "tp": f"14세: 남들이 외면하고 지나치는 작은 억울함을 기록하는 펜을 들다.",
                    "outcome": (
                        f"낡은 카메라와 수첩을 들고 급식실 뒤편 납품 차량과 학교 밖 철거 골목을 취재하던 첫 주, 한 선배가 경고했지만 {v['name_eun']} 물러서지 않았습니다. "
                        f"활자 몇 줄이 거짓을 부끄럽게 만든다는 짜릿한 실감을 처음 맛보았습니다."
                    ),
                },
                {
                    "id": "b4_craft",
                    "label": "🔧 실전 기술·장사·공방 실습 — 책상 밖 진짜 삶의 기술을 배운다",
                    "hint": "자산 +6 · 근성 +5 · 장인·사업·생활인 루트 핵심 적성",
                    "delta": {"wealth": 6, "grit": 5},
                    "add_flags": ["apt_craft"],
                    "log": "책상 앞의 이론보다 현장 장사와 손기술 속에서 살아 움직이는 배움을 택했다.",
                    "tp": f"14세: 공구와 장부를 손에 쥐며 내 노동으로 가치를 만드는 감각을 익히다.",
                    "outcome": (
                        f"수업 종이 울리자마자 앞치마와 공구 벨트를 두른 {v['name_eun']} 물건이 어떻게 팔리고 수리되는지 온몸으로 배웠습니다. "
                        f"처음 제 힘으로 만 원짜리 몇 장을 벌어 {v['origin_guardian']} 손에 쥐여 드리던 날, 어른이 되는 문턱이 손에 잡히는 듯했습니다."
                    ),
                },
            ],
        )

    # ── BEAT 5 (16세: 스승 {mentor}와 첫 번째 구체적 유혹) ──
    if beat == 5:
        return _make_node(
            "b5_mentor",
            f"🕯️ {age}세 — 스승 '{v['mentor']}'{v['mentor_wa_s']} 첫 번째 지름길의 유혹",
            (
                f"{bline}고등학생이 된 {v['name_eun']} {v['city']}의 외진 모퉁이 **{v['mentor_place']}**에서 "
                f"{v['mentor_role']} **{v['mentor']}**의 눈에 띄어 밤늦은 특별 사사를 받기 시작했습니다.\n\n"
                f"하지만 남들이 쉬는 시간에도 똑같은 기본기만 수백 번씩 반복하는 나날은 지치고 가난했습니다. "
                f"바로 그 지친 틈새를 노린 듯, 어느 저녁 **{v['mentor_tempt']}**.\n"
                f"> *{v['mentor']}: \"{v['mentor_lesson']}\"*"
            ),
            2,
            [
                {
                    "id": "b5_honest",
                    "label": f"🧭 유혹을 거절하고 {v['mentor']}의 고된 기본기를 끝까지 파고든다",
                    "hint": "근성 +6 · 지성 +4 · 정직한 실력의 뿌리 & 스승의 두터운 신임",
                    "delta": {"grit": 6, "intellect": 4},
                    "add_flags": ["honest_path", "mentor_loyal"],
                    "set_mentor_rel": "loyal",
                    "log": f"은밀한 편법 제안을 뿌리치고 {v['mentor']} 밑에서 고된 기본기를 견뎌내며 정직한 실력을 쌓았다.",
                    "tp": f"16세: 달콤한 지름길의 봉투를 돌려보내고 {v['mentor']} 곁에서 느리지만 정직한 뿌리를 내리다.",
                    "outcome": (
                        f"\"죄송하지만 그건 못 하겠습니다.\" 제안을 돌려보낸 밤, 주머니는 가벼웠지만 {v['mentor_place']}로 돌아온 {v['name']}에게 "
                        f"{v['mentor_i']} 아무 말 없이 따뜻한 찻잔과 가장 아끼던 비법 노트를 슬며시 건넸습니다."
                    ),
                },
                {
                    "id": "b5_shortcut",
                    "label": "🪙 현실의 벽을 넘기 위해 은밀한 제안을 받아들이고 큰돈과 성과를 챙긴다",
                    "hint": "자산 +9 · 열정 +4 · 공감 -5 · 편법의 첫 맛 (뒷세계 루트 개방 조건)",
                    "delta": {"wealth": 9, "passion": 4, "empathy": -5},
                    "add_flags": ["shortcut_tempted", "corrupted"],
                    "set_mentor_rel": "distant",
                    "log": "느린 정석 대신 빠른 대가를 택하며 처음으로 양심보다 요령에 손을 대고 말았다.",
                    "tp": f"16세: 당장의 돈과 환호를 위해 원칙과 눈을 맞바꾸는 첫 타협을 저지르다.",
                    "outcome": (
                        f"두툼한 현금 봉투와 환호성이 손안에 들어오는 데는 단 하룻밤이면 충분했습니다. "
                        f"하지만 며칠 뒤 작업실 구석에서 마주친 {v['mentor']}의 쓸쓸하고 조용한 눈빛을, {v['name_eun']} 끝내 정면으로 마주 보지 못했습니다."
                    ),
                },
                {
                    "id": "b5_rebel",
                    "label": f"🕊️ 정석도 편법도 내 길이 아니다 — {v['mentor']}께 인사하고 독자적 실험을 떠난다",
                    "hint": "열정 +7 · 지성 +4 · 기존 틀을 부수는 대담한 개척 정신",
                    "delta": {"passion": 7, "intellect": 4},
                    "add_flags": ["rebel_spirit"],
                    "set_mentor_rel": "rebel",
                    "log": f"{v['mentor']}의 낡은 틀마저 넘어 스스로 깨지고 부딪히며 독자적인 방식을 찾기 시작했다.",
                    "tp": f"16세: 스승의 가르침을 품은 채 낡은 울타리를 뛰어넘는 나만의 실험을 시작하다.",
                    "outcome": (
                        f"\"선생님 방식대로는 이 답답한 세상에 틈을 못 낼 것 같습니다.\" {v['name_eun']} 깊게 절을 올린 뒤 스스로의 거친 방식을 시험하러 거리로 나섰습니다. "
                        f"{v['mentor_eun']} 혀를 찼지만, 문이 닫힌 뒤 오래도록 제자의 뒷모습을 보며 미소 지었습니다."
                    ),
                },
            ],
        )

    # ── BEAT 6 (18세: 고향 밤 명소에서의 졸업 전야) ──
    if beat == 6:
        if "comp_close" in flags or "comp_rival" in flags:
            if "comp_close" in flags:
                mood_intro = (
                    f"{bline}졸업식을 하루 앞둔 열여덟의 매서운 겨울밤. {v['name_eun']} 가장 소중한 소꿉친구 **{v['comp_wa']}** 나란히 "
                    f"**{v['night_spot']}** 난간에 섰습니다.\n\n"
                    f"하얀 입김이 어둠 속으로 흩어지고, 9년 전 처음 만났던 {v['hangout']} 시절이 어제 일처럼 스쳐 지나갑니다. "
                    f"\"우리 이제 진짜 어른이네.\" **{v['comp_i']}** 호주머니에서 9년 전 그날과 닮은 작은 사탕 두 알을 꺼내 한쪽을 건네며 조용히 묻습니다.\n"
                    f"> *\"스무 살이 되어 이 {v['city_eul']} 떠나더라도… 우리 나중에 어떻게 다시 만나게 될까?\"*"
                )
            else:
                mood_intro = (
                    f"{bline}열아홉을 코앞에 둔 겨울밤. 지기 싫어하며 수십 번을 겨루었던 라이벌 **{v['comp_wa']}** 숨을 몰아쉬며 "
                    f"**{v['night_spot']}** 언덕 끝까지 마지막 경주처럼 뛰어올랐습니다.\n\n"
                    f"차가운 밤바람에 빨개진 귀를 문지르며 **{v['comp_i']}** 불빛 아래 선 {v['name_eul']} 바라봅니다. "
                    f"어릴 적부터 경쟁하던 얼굴 위에 어느새 진심 어린 온기가 배어 있습니다.\n"
                    f"> *\"야, {v['name_ya']}. 더 넓은 세상에 나가서도 나보다 먼저 무너지면 안 된다?\"*"
                )

            return _make_node(
                "b6_promise_comp",
                f"🌙 {age}세 — 졸업 전날 밤, {v['night_spot']}에서의 고백",
                mood_intro,
                1,
                [
                    {
                        "id": "b6_comp_promise",
                        "label": f"🤝 \"어디서 무슨 일을 하든 스무 살 넘겨서 꼭 다시 찾자\"고 약속한다",
                        "hint": "공감 +6 · 열정 +2 · 운명적 재회와 [오래된 약속의 완성] 초석",
                        "delta": {"empathy": 6, "passion": 2},
                        "add_flags": ["comp_promised"],
                        "set_comp_rel": "promised",
                        "log": f"{v['night_spot']}에서 {v['comp_wa']} 미래에도 서로를 찾겠다는 깊은 약속을 맺었다.",
                        "tp": f"18세: {v['night_spot']}의 밤바람 아래 {v['comp_wa']} 훗날 다시 만날 굳은 약속을 나누다.",
                        "outcome": (
                            f"\"약속했다. 연락 끊기면 내가 세상 끝까지라도 찾아갈 거니까.\" {v['comp_i']} 걸어온 새끼손가락이 추운 밤 공기 속에서 유난히 뜨거웠습니다. "
                            f"그 밤 두 사람 사이에 놓인 약속은 훗날 험난한 청춘을 건너는 보이지 않는 닻이 되었습니다."
                        ),
                    },
                    {
                        "id": "b6_comp_warm",
                        "label": "✨ \"각자 꿈을 이룬 다음 웃으면서 멋지게 다시 보자\"며 힘껏 안아준다",
                        "hint": "열정 +5 · 공감 +3 · 서로의 날개를 축복하는 아련한 출발",
                        "delta": {"passion": 5, "empathy": 3},
                        "add_flags": ["comp_parted_warm"],
                        "set_comp_rel": "parted_warm",
                        "log": f"{v['comp_wa']} 서로의 앞날을 응원하며 아련하지만 힘찬 작별을 나누었다.",
                        "tp": f"18세: 서로의 꿈을 지켜주기 위해 눈물 대신 웃음으로 {v['comp_eul']} 배웅하다.",
                        "outcome": (
                            f"어색하게 부딪친 어깨 너머로 짭조름하고 따뜻한 밤공기가 흘렀습니다. "
                            f"두 사람은 약속의 반지 대신 '반드시 잘 살아서 다시 마주치자'는 무언의 다짐만 남긴 채 각자의 새벽 열차를 기다렸습니다."
                        ),
                    },
                    {
                        "id": "b6_comp_cold",
                        "label": "❄️ 감정이 앞길을 붙잡을까 두려워 일부러 차갑게 거리를 두고 돌아선다",
                        "hint": "지성 +5 · 근성 +5 · 공감 -4 · 목표만을 향한 고독한 각성",
                        "delta": {"intellect": 5, "grit": 5, "empathy": -4},
                        "add_flags": ["solo_focus"],
                        "set_comp_rel": "estranged",
                        "log": "성공을 위해 감정을 접고 차갑게 혼자만의 길을 걸어가기로 결심했다.",
                        "tp": f"18세: 정을 잘라내듯 냉정하게 돌아서서 홀로 세상에 맞설 갑옷을 입다.",
                        "outcome": (
                            f"\"지금 한가하게 약속이나 할 때가 아니야.\" 일부러 차갑게 내뱉은 말에 {v['comp']}의 표정이 천천히 굳었습니다. "
                            f"뒤돌아 내려오는 계단마다 시린 바람이 가슴을 찔렀지만, {v['name_eun']} 다시 고개를 돌리지 않았습니다."
                        ),
                    },
                ],
            )

        # Solo path Beat 6
        if "shortcut_tempted" in flags:
            solo_body = (
                f"{bline}졸업 전날 밤, {v['name_eun']} 홀로 **{v['night_spot']}** 끝에 서서 아래에 펼쳐진 {v['city']}의 불빛을 내려다봅니다.\n\n"
                f"두툼한 외투 안주머니에는 열여섯에 손댔던 편법의 대가로 얻은 빳빳한 지폐가 구겨져 있고, "
                f"다른 쪽 주머니에는 여섯 살 때부터 지녀온 **{v['item_short']}**{v['item_i_s']} 차갑게 만져집니다. "
                f"맞은편 {v['mentor_place']}의 불빛이 막 꺼지는 것을 보며, 다가올 스무 살을 어떤 얼굴로 맞을지 스스로에게 묻습니다."
            )
        else:
            solo_body = (
                f"{bline}졸업을 하루 앞둔 겨울밤, {v['name_eun']} 동행 없이 홀로 **{v['night_spot']}**에 올라 은하수가 비치는 하늘을 바라봅니다.\n\n"
                f"어린 시절 **{v['origin_place']}**에서부터 손때 묻혀 간직해 온 **{v['item_short']}**{v['item_eul_s']} 손바닥에 올려두니, 지난 열여덟 해의 울음과 배움이 바람결처럼 스쳐 지나갑니다. "
                f"이제 누구의 보호막도 없는 거친 세상 앞에 내 이름 석 자만 들고 나아갈 시간입니다."
            )

        return _make_node(
            "b6_promise_solo",
            f"🌠 {age}세 — 홀로 선 {v['night_spot']}의 열여덟 겨울 하늘",
            solo_body,
            1,
            [
                {
                    "id": "b6_solo_fame",
                    "label": "🔥 언젠가 이 좁은 고향을 벗어나 온 세상이 내 이름을 기억하게 만들겠다",
                    "hint": "열정 +6 · 지성 +4 · 거침없는 성취와 야망",
                    "delta": {"passion": 6, "intellect": 4},
                    "add_flags": ["dream_fame"],
                    "log": "고독을 연료 삼아 언젠가 세상에 뚜렷한 이름을 남기겠다고 다짐했다.",
                    "tp": f"18세: {v['night_spot']} 아래서 반드시 세상을 놀라게 하겠다는 뜨거운 맹세를 세우다.",
                    "outcome": (
                        f"차가운 바람을 폐부 깊이 들이마신 {v['name_eun']} 밤하늘 아래서 두 주먹을 꽉 쥐었습니다. "
                        f"누구의 도움도 없이 바닥에서 솟아오르겠다는 지독한 오기가 등줄기를 뜨겁게 덥혔습니다."
                    ),
                },
                {
                    "id": "b6_solo_star",
                    "label": "🌌 화려한 이름 대신, 시간과 사람의 마음을 잇는 진짜 의미를 찾고 싶다",
                    "hint": "지성 +7 · 공감 +5 · 깊은 사유의 길 ([별의 씨앗] 결정적 단서)",
                    "delta": {"intellect": 7, "empathy": 5},
                    "add_flags": ["star_seed"],
                    "remove_flags": ["corrupted"] if "shortcut_tempted" in flags else [],
                    "log": "눈에 보이는 성공 너머 인간과 시간이 이어지는 깊은 질문에 답을 찾기로 했다.",
                    "tp": f"18세: {v['night_spot']} 밤하늘 아래서 시간 너머의 빛을 쫓는 질문을 가슴에 새기다.",
                    "outcome": (
                        f"주머니 속 {v['item_eul']} 하늘을 향해 비추던 {v['name']}의 마음에 잔잔한 물결이 번졌습니다. "
                        f"잠시의 욕심을 씻어내고, 세상이 재는 성공이 아니라 나만의 질문 끝까지 걸어가 보겠다는 조용한 맹세가 싹텄습니다."
                    ),
                },
                {
                    "id": "b6_solo_grit",
                    "label": "💰 누구에게도 흔들리거나 무시당하지 않을 현실의 힘과 기반을 세우겠다",
                    "hint": "근성 +6 · 자산 +6 · 냉철한 자수성가의 길",
                    "delta": {"grit": 6, "wealth": 6},
                    "add_flags": ["self_made"],
                    "log": "냉정한 세상에서 살아남아 스스로와 소중한 이를 지킬 현실적 힘을 쌓기로 했다.",
                    "tp": f"18세: 어떤 풍파 앞에서도 다시 빚쟁이들에게 집을 뺏기지 않겠다고 다짐하다.",
                    "outcome": (
                        f"{v['name_eun']} 차가운 난간을 짚고 일어나 털고 걸어 내려왔습니다. "
                        f"어린 날 보았던 어른들의 눈물과 가난의 냄새를 다시는 되풀이하지 않겠다는 다짐이 발걸음마다 단단하게 박혔습니다."
                    ),
                },
            ],
        )


# ==========================================
# 8. BEAT 7~11 : 청년기 (19세 · 22세 · 26세 · 30세 · 34세)
# ==========================================
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


def _build_youth_node(beat: int, life: Dict[str, Any], v: Dict[str, Any]) -> Dict[str, Any]:
    age = v["age"]
    oid = v["origin_id"]
    career = v["career"]
    flags = set(life.get("flags") or [])
    stats = life.get("stats") or {}
    bridge = _prev_bridge(life, v)
    bline = f"{bridge}\n\n" if bridge else ""

    # ── BEAT 7 (19세: 스무 살 진로 결정 — 출신·적성 기반 세부 전공 미리보기 포함!) ──
    if beat == 7:
        top2 = _pick_top_careers(stats, flags)
        def _tag(cid: str) -> str:
            return " [추천]" if cid in top2 else ""

        def _preview(cid: str) -> str:
            sid = resolve_specialty_id(life, cid)
            return SPECIALTY_CATALOG[sid]["title"]

        choices = [
            {
                "id": "c_artist",
                "label": f"🎨 예술·창작가의 길 — {_preview('artist')}{_tag('artist')}",
                "hint": f"열정 +6 · 자산 -2 · [{_preview('artist')}] 세부 전공 개방",
                "delta": {"passion": 6, "wealth": -2},
                "set_career": "artist",
                "log": f"불확실한 생계를 각오하고 [{_preview('artist')}]의 길에 첫 발을 내디뎠다.",
                "tp": f"19세: 고향 {v['city_eul']} 떠나 [{_preview('artist')}]라는 험난한 창작의 길을 택하다.",
                "outcome": f"낡은 여행 가방에 {v['item_eul']} 챙긴 {v['name_eun']} 기차 창밖으로 멀어지는 {v['city_eul']} 보며 가슴 벅찬 붓·음표의 꿈을 되뇌었습니다.",
            },
            {
                "id": "c_scholar",
                "label": f"🔬 학자·의학·연구의 길 — {_preview('scholar')}{_tag('scholar')}",
                "hint": f"지성 +6 · 근성 +1 · [{_preview('scholar')}] 세부 전공 개방",
                "delta": {"intellect": 6, "grit": 1},
                "set_career": "scholar",
                "log": f"두꺼운 전공서와 노트를 안고 [{_preview('scholar')}]의 세계로 들어섰다.",
                "tp": f"19세: 진리와 생명을 향한 질문을 안고 [{_preview('scholar')}]의 궤도에 오르다.",
                "outcome": f"첫차에서 내린 대학가와 연구동 냄새는 낯설고 차가웠지만, {v['name']}의 손에는 이제 밤새 붙들고 늘어질 진짜 문제들이 쥐어졌습니다.",
            },
            {
                "id": "c_entrepreneur",
                "label": f"💼 사업·청년 창업의 길 — {_preview('entrepreneur')}{_tag('entrepreneur')}",
                "hint": f"자산 +6 · 열정 +2 · [{_preview('entrepreneur')}] 세부 전공 개방",
                "delta": {"wealth": 6, "passion": 2},
                "set_career": "entrepreneur",
                "log": f"작은 종잣돈과 배짱 하나로 [{_preview('entrepreneur')}]의 치열한 판에 뛰어들었다.",
                "tp": f"19세: 남 밑에서 일하기보다 직접 판을 설계하는 [{_preview('entrepreneur')}]로 출발하다.",
                "outcome": f"구두 뒷굽이 닳도록 발품을 팔며 작은 보증금을 마련한 {v['name_eun']} 간판도 없는 사무실 책상 위에서 첫 사업 계획서를 열었습니다.",
            },
            {
                "id": "c_artisan",
                "label": f"🌿 장인·공방·요리의 길 — {_preview('artisan')}{_tag('artisan')}",
                "hint": f"근성 +5 · 공감 +3 · [{_preview('artisan')}] 세부 전공 개방",
                "delta": {"grit": 5, "empathy": 3},
                "set_career": "artisan",
                "log": f"화려한 간판 대신 땀과 손끝으로 빚어내는 [{_preview('artisan')}]의 길을 택했다.",
                "tp": f"19세: 정직한 노동과 손끝의 온기를 믿고 [{_preview('artisan')}]의 문을 두드리다.",
                "outcome": f"새벽 공기 속에서 작업복 앞치마를 고쳐 맨 순간, {v['origin_place']}에서부터 몸에 배어 있던 손끝의 감각이 살아나는 듯했습니다.",
            },
            {
                "id": "c_guardian",
                "label": f"⚖️ 수호·탐사·정의의 길 — {_preview('guardian')}{_tag('guardian')}",
                "hint": f"공감 +5 · 근성 +3 · [{_preview('guardian')}] 세부 전공 개방",
                "delta": {"empathy": 5, "grit": 3},
                "set_career": "guardian",
                "log": f"세상의 어두운 구석을 외면하지 않기 위해 [{_preview('guardian')}]의 길에 들어섰다.",
                "tp": f"19세: 힘없는 사람들의 편에 서기 위해 [{_preview('guardian')}]의 길을 결심하다.",
                "outcome": f"수첩 앞장에 '외면하지 않을 것' 세 글자를 적어 넣은 {v['name_eun']} 차가운 아스팔트 위로 묵직한 첫 걸음을 내디뎠습니다.",
            },
        ]
        can_shadow = ("shortcut_tempted" in flags and int(stats.get("empathy", 20) or 20) <= 28) or (oid == "fallen_house" and "shortcut_tempted" in flags)
        if can_shadow:
            choices.append({
                "id": "c_shadow",
                "label": f"🎭 뒷세계 브로커의 길 — {_preview('shadow')}",
                "hint": f"자산 +10 · 공감 -5 · 이름 없이 어둠의 거래를 설계하는 위험한 길",
                "delta": {"wealth": 10, "empathy": -5},
                "set_career": "shadow",
                "add_flags": ["corrupted"],
                "log": f"양지의 규칙에 등을 돌리고 도시의 뒷면에서 [{_preview('shadow')}]로 발을 들였다.",
                "tp": f"19세: 돈이 지배하는 뒷골목 규칙을 깨닫고 [{_preview('shadow')}]의 가면을 쓰다.",
                "outcome": f"열여섯의 그 첫 봉투 이후, {v['name']}에게 합법의 줄은 이미 의미가 없었습니다. 낯선 인물이 건넨 첫 암호 번호가 모든 시작이었습니다.",
            })
        else:
            choices.append({
                "id": "c_wanderer",
                "label": f"🧭 방랑·세계 기록가의 길 — {_preview('wanderer')}{_tag('wanderer')}",
                "hint": f"열정 +4 · 지성 +4 · [{_preview('wanderer')}] 세부 전공 개방",
                "delta": {"passion": 4, "intellect": 4},
                "set_career": "wanderer",
                "log": f"남들이 정한 궤도를 거부하고 [{_preview('wanderer')}]로서 넓은 세상으로 떠났다.",
                "tp": f"19세: 한곳에 뿌리내리기보다 세상 전체를 두 발로 읽는 [{_preview('wanderer')}]로 떠나다.",
                "outcome": f"무거운 캐리어 대신 해진 배낭 하나와 {v['item_eul']} 챙긴 채 항구 여객선 갑판에 오른 순간, 짠 바닷바람이 청춘의 닻을 올렸습니다.",
            })

        return _make_node(
            "b7_career",
            f"🚪 {age}세 — 스무 살의 문턱, 어떤 삶으로 걸어갈 것인가",
            (
                f"{bline}{v['city']}의 **{v['origin_place']}**에서 울고 웃던 아이는 어느덧 성인의 문턱에 섰습니다. "
                f"스무 살의 {v['name']} 손에는 어릴 적 지니고 온 **{v['item_short']}**, 그동안 길러온 재능과 상처, 그리고 세상에 품은 질문이 들려 있습니다.\n\n"
                f"어떤 직업을 택하느냐에 따라 앞으로 서게 될 **일터**와 **만나게 될 인연**, 그리고 **인생의 마지막 페이지**가 전혀 다른 갈래로 열립니다."
            ),
            3,
            choices,
        )

    # ── BEAT 8 (22세: 세부 전공별 첫 데뷔와 혹독한 신고식) ──
    if beat == 8:
        sid = v["specialty_id"]
        if career == "artist":
            scene_desc = (
                f"{bline}스물둘의 {v['name_eun']} **{v['workplace']}**에서 반년간 매달린 첫 결과물을 들고 마침내 세상의 문 앞에 섰습니다. "
                f"하지만 {v['tool_eul']} 내려놓은 첫 밤, **{v['patron']}**{v['patron_eun_s']} 눈도 마주치지 않은 채 서늘하게 말했습니다.\n"
                f"> *\"독특하긴 한데 요즘 시장엔 너무 낡고 무거워. 팔릴 만한 껍데기를 입히든가, 아니면 그냥 배 곯고 살든가.\"*"
            )
            chs = [
                {
                    "id": "d_art_pure",
                    "label": "🔥 배고프더라도 내 색깔과 진정성만큼은 단 한 줄도 고치지 않는다",
                    "hint": "열정 +7 · 근성 +3 · 순수 창작의 자존심 (걸작·무명천재 루트)",
                    "delta": {"passion": 7, "grit": 3},
                    "add_flags": ["pure_art", "masterwork_kept"],
                    "log": f"혹평과 가난을 감수하고 [{v['specialty']}]만의 타협 없는 언어를 밀어붙였다.",
                    "tp": f"22세: 모욕적인 평가 앞에서도 '내 작업만큼은 팔지 않겠다'며 순수함을 지키다.",
                    "outcome": f"거절당한 {v['work_obj_eul']} 안고 찬 비를 맞으며 작업실로 돌아온 {v['name_eun']} 밤새 이를 악물며 다음 작품을 새로 시작했습니다.",
                },
                {
                    "id": "d_art_pop",
                    "label": "💰 상업 외주 작업으로 생활비를 벌며 그 안에서 내 색깔을 지킨다",
                    "hint": "자산 +7 · 공감 +2 · 현실과 이상 사이의 유연한 균형",
                    "delta": {"wealth": 7, "empathy": 2},
                    "add_flags": ["commercial_skill"],
                    "log": "낮에는 상업 외주 작업으로 생계를 잇고 밤마다 나만의 창작을 이어갔다.",
                    "outcome": f"타인의 주문에 맞춰 작업을 하면서도, 아무도 보지 않는 자정 이후 두 시간만큼은 꼬박 {v['work_obj']}에 모든 영혼을 부었습니다.",
                },
                {
                    "id": "d_art_copy",
                    "label": "⚠️ 요즘 뜨는 유명 선배의 구도와 아이디어를 교묘히 차용해 빠르게 데뷔한다",
                    "hint": "자산 +9 · 열정 -4 · 공감 -5 · 이름과 맞바꾼 양심의 균열",
                    "delta": {"wealth": 9, "passion": -4, "empathy": -5},
                    "add_flags": ["corrupted"],
                    "log": "조급함 끝에 타인의 감각을 차용해 빠른 스포트라이트를 얻었으나 양심이 무뎌졌다.",
                    "tp": f"22세: 인정받고 싶다는 초조함에 창작자 최대의 금기인 모방에 손을 대다.",
                    "outcome": f"화려한 박수와 첫 원고료가 쏟아졌지만, 축하 인사 속에서도 정작 {v['name']} 자신은 그 작품을 똑바로 바라보지 못했습니다.",
                },
            ]
        elif career == "scholar":
            scene_desc = (
                f"{bline}스물둘의 연구자 {v['name_eun']} 새벽 두 시까지 불이 꺼지지 않는 **{v['workplace']}**에서 코피를 닦아내며 매달리고 있습니다. "
                f"책상 위에는 수백 장의 기록과 함께 **{v['work_obj']}** 초안이 놓여 있고, **{v['patron']}**{v['patron_eun_s']} 빠른 성과와 깔끔한 수치를 은근히 압박해 옵니다."
            )
            chs = [
                {
                    "id": "d_sch_heal",
                    "label": "🩺 출세와 속도를 버리고 당장 아픈 이·고립된 현장을 살리는 데 집중한다",
                    "hint": "공감 +7 · 지성 +3 · [생명을 잇는 손] 치유자의 맹세",
                    "delta": {"empathy": 7, "intellect": 3},
                    "add_flags": ["healer_oath", "honest_path"],
                    "log": f"[{v['specialty']}]로서 논문 점수보다 현장의 생명과 사람을 살리는 길을 택했다.",
                    "tp": f"22세: 스펙과 출세 대신 가장 약하고 아픈 이들 곁을 지키는 치유자의 길을 맹세하다.",
                    "outcome": f"환자와 주민들의 손을 잡아주는 밤샘 당직이 이어졌지만, 막혀 있던 가설 하나가 현장의 울음 속에서 거짓말처럼 풀렸습니다.",
                },
                {
                    "id": "d_sch_deep",
                    "label": "📚 남들이 돈 안 된다며 피하는 기초 난제를 10년이고 끝까지 파고든다",
                    "hint": "지성 +8 · 근성 +3 · [시대의 거장 / 별의 씨앗] 정통 연구 외길",
                    "delta": {"intellect": 8, "grit": 3},
                    "add_flags": ["masterwork_kept", "star_seed"],
                    "log": "수익성 없는 기초 난제를 끝까지 파고드는 고독한 학자의 길에 들어섰다.",
                    "tp": f"22세: 시류가 외면하는 거대한 기초 난제 앞에 자신의 청춘을 통째로 던지다.",
                    "outcome": f"먼지 낀 자료 더미와 밤샘 계산 끝에 작은 단서 한 줄을 찾아낸 새벽, {v['name_eun']} 평생 학자의 길을 후회하지 않으리라 확신했습니다.",
                },
                {
                    "id": "d_sch_stat",
                    "label": "⚠️ 연구비와 조기 임용을 위해 어긋난 표본 수치 일부를 살짝 다듬는다",
                    "hint": "자산 +7 · 지성 -3 · 공감 -5 · 학자의 금기를 어긴 대가",
                    "delta": {"wealth": 7, "intellect": -3, "empathy": -5},
                    "add_flags": ["corrupted"],
                    "log": "연구 지원금을 따내기 위해 불편한 실험 데이터를 눈감고 삭제하고 말았다.",
                    "tp": f"22세: 빠른 명예와 연구비 앞에서 진실의 숫자를 깎아내는 잘못을 저지르다.",
                    "outcome": f"학술지 게재와 장학금은 일사천리로 통과되었지만, 파일 깊숙이 감춰둔 원본 데이터 폴더를 볼 때마다 등골이 서늘해졌습니다.",
                },
            ]
        elif career == "entrepreneur":
            scene_desc = (
                f"{bline}부푼 꿈을 안고 연 **{v['workplace']}**. 하지만 첫 계약 납품 기한을 일주일 앞둔 밤, 핵심 거래처가 일방적으로 대금을 미루며 보증금까지 압류당할 위기에 처했습니다.\n\n"
                f"텅 빈 사무실 형광등 아래 낡은 **{v['tool']}**만 나뒹굴고, 전화기 너머 **{v['patron']}**{v['patron_eun_s']} 싸늘하게 조건을 들이밉니다."
            )
            chs = [
                {
                    "id": "d_ent_grit",
                    "label": "🛡️ 거래처마다 직접 발품을 팔고 솔직히 사정을 설명해 신뢰로 돌파한다",
                    "hint": "근성 +7 · 자산 +5 · 단단한 정공법 사업가의 초석",
                    "delta": {"grit": 7, "wealth": 5},
                    "add_flags": ["honest_path"],
                    "log": "비굴하지 않은 정공법으로 거래처를 일일이 설득해 첫 도산 위기를 넘겼다.",
                    "tp": f"22세: 첫 부도 위기 앞에서도 눈속임 대신 맨발로 신뢰를 사서 기적처럼 일어서다.",
                    "outcome": f"밤새 쉰 목소리로 사정과 품질 약속을 증명하자, 거래처 사장 한 명이 \"젊은이 눈빛이 진짜네\"라며 현장에서 물량을 떠안아 주었습니다.",
                },
                {
                    "id": "d_ent_bold",
                    "label": "🚀 남은 전 재산을 신제품·신규 라인에 올인해 승부수로 판을 뒤집는다",
                    "hint": "열정 +6 · 자산 +8 · 근성 -3 · 멈출 줄 모르는 승부사",
                    "delta": {"passion": 6, "wealth": 8, "grit": -3},
                    "add_flags": ["high_roller"],
                    "log": "퇴로를 스스로 불태우는 승부수를 던져 첫 대형 거래를 따냈다.",
                    "outcome": f"사흘 밤낮 잠 한숨 자지 못한 채 밀어붙인 승부수가 시장에서 적중하며, 반지하 월세방 신세를 단숨에 벗어났습니다.",
                },
                {
                    "id": "d_ent_scam",
                    "label": "⚠️ 하청 단가를 일방적으로 후려치고 원산지·스펙을 부풀려 흑자를 만든다",
                    "hint": "자산 +11 · 공감 -7 · 타인의 피눈물로 쌓은 첫 수익",
                    "delta": {"wealth": 11, "empathy": -7},
                    "add_flags": ["corrupted"],
                    "log": "약소한 하청업자들의 대금을 깎고 서류를 꾸며 당장의 큰 이득을 챙겼다.",
                    "tp": f"22세: 살아남는다는 구실 아래 가장 약한 거래처의 등을 치는 비정함을 배우다.",
                    "outcome": f"장부 위 숫자는 화려한 흑자로 뒤집혔지만, 사무실 문밖에서 울며 돌아서던 영세 하청 사장의 뒷모습이 오래 남아 지워지지 않았습니다.",
                },
            ]
        elif career == "artisan":
            scene_desc = (
                f"{bline}남들이 잠든 새벽마다 불을 켜고 **{v['workplace']}**에서 하루 열두 시간씩 손가락이 부르트도록 일한 3년. "
                f"마침내 {v['name_eun']} 온전히 자기 이름을 내걸고 첫 손님과 첫 주문을 마주합니다.\n\n"
                f"작업대 위엔 손때 묻은 **{v['tool']}**, 그러나 당장 재료비조차 버거운 통장 위로 **{v['patron']}**의 솔깃한 제의가 날아듭니다."
            )
            chs = [
                {
                    "id": "d_artn_craft",
                    "label": "🔨 적자가 나더라도 최상급 재료와 백 년 가는 손기술 원칙만은 굽히지 않는다",
                    "hint": "근성 +6 · 공감 +4 · [시대의 거장] 장인의 고집",
                    "delta": {"grit": 6, "empathy": 4},
                    "add_flags": ["masterwork_kept", "honest_path"],
                    "log": f"[{v['specialty']}]로서 어떤 타협도 없이 최상의 재료와 정성만 지키겠다고 맹세했다.",
                    "tp": f"22세: 돈을 적게 남기더라도 내 손이 부끄러운 물건·음식은 내놓지 않기로 맹세하다.",
                    "outcome": f"첫 달엔 손에 쥔 돈보다 허리 통증이 더 컸지만, 한 번 맛보거나 써 본 손님들이 말없이 지인을 데리고 다시 문을 열기 시작했습니다.",
                },
                {
                    "id": "d_artn_local",
                    "label": "🏘️ 동네 어르신과 지친 이웃들이 언제든 기대어 쉬어가는 따뜻한 사랑방으로 만든다",
                    "hint": "공감 +7 · 자산 +4 · [국수 한 그릇의 우주 / 마을 등불] 초석",
                    "delta": {"empathy": 7, "wealth": 4},
                    "add_flags": ["protect_local", "noodle_revival"] if sid == "artn_noodle" else ["protect_local"],
                    "log": "이윤보다 이웃들의 배고픔과 외로움을 채워주는 동네 사랑방을 일구었다.",
                    "tp": f"22세: 내 일터를 혼자 돈 버는 가게가 아니라 이웃이 숨 돌리는 동네 등불로 만들다.",
                    "outcome": f"주머니 사정이 뻔해 보이는 학생에겐 한 그릇 더 얹어주고 비 오는 날엔 우산을 빌려주자, 어느새 가게는 골목에서 가장 따뜻한 불빛이 되었습니다.",
                },
                {
                    "id": "d_artn_eff",
                    "label": "⚙️ 단골 감성에 얽매이지 않고 자동화 공정·납품을 도입해 매출을 키운다",
                    "hint": "자산 +8 · 열정 -2 · 실리와 확장에 집중한 생활 사업",
                    "delta": {"wealth": 8, "passion": -2},
                    "add_flags": ["scaled_shop"],
                    "log": "손맛과 감성 대신 표준 공정과 대량 납품을 도입해 규모를 불려 나갔다.",
                    "outcome": f"직원을 두 명 더 두고 장부 규모를 세 배로 늘렸지만, 어릴 적 작업실에서 느껴지던 설렘은 조금씩 숫자로 바뀌어 갔습니다.",
                },
            ]
        elif career == "guardian":
            scene_desc = (
                f"{bline}수습 딱지를 갓 뗀 스물둘, **{v['workplace']}**의 차가운 야근 등 아래로 지역 유력 인사의 아들이 연루된 수상한 사고 기록이 떨어집니다.\n\n"
                f"**{v['patron']}**{v['patron_eun_s']} 서류를 서랍 깊숙이 넣으라 눈짓하고, 복도 유리문 밖에서는 가난한 피해자 가족이 {v['name']}의 이름만 부르며 떨고 있습니다."
            )
            chs = [
                {
                    "id": "d_grd_truth",
                    "label": "⚖️ 상부의 압력과 보복을 감수하고 밤새 현장 진짜 증거를 파헤친다",
                    "hint": "공감 +6 · 근성 +5 · 자산 -2 · [진실을 남긴 이름] 불굴의 수호자",
                    "delta": {"empathy": 6, "grit": 5, "wealth": -2},
                    "add_flags": ["whistleblower", "honest_path"],
                    "log": "윗선의 회유를 정면으로 거부하고 피해자의 억울함을 밝혀내는 외로운 싸움을 시작했다.",
                    "tp": f"22세: 첫 현장에서 권력의 압력을 걷어차고 피해자 편에 서는 강골로 이름을 날리다.",
                    "outcome": f"사흘 밤을 새워 쥐어 짠 CCTV 원본과 증언으로 사건이 뒤집히던 아침, 동료들은 피했지만 피해자 어머니의 울음 섞인 악수가 가슴에 박혔습니다.",
                },
                {
                    "id": "d_grd_smart",
                    "label": "🧠 무모하게 부딪히기보다 사본 증거를 안전한 곳에 빼돌린 뒤 결정적 때를 기다린다",
                    "hint": "지성 +7 · 근성 +3 · 치밀하게 판을 짜는 지략가",
                    "delta": {"intellect": 7, "grit": 3},
                    "add_flags": ["patient_strategy"],
                    "log": "겉으로 순응하는 척하며 모든 핵심 자료의 사본을 은밀히 모으기 시작했다.",
                    "tp": f"22세: 성급히 부러지기보다 더 큰 싸움을 이기기 위해 냉철하게 증거를 모으다.",
                    "outcome": f"겉으론 고개를 숙였지만 구두 밑창과 개인 금고 속엔 그날의 모든 파일 사본이 고스란히 복제되었습니다.",
                },
                {
                    "id": "d_grd_obey",
                    "label": "😶 아직 힘없는 신참이 무슨 수로 이기나 싶어 눈을 감고 처분에 따른다",
                    "hint": "자산 +7 · 공감 -6 · 첫 양심의 균열",
                    "delta": {"wealth": 7, "empathy": -6},
                    "add_flags": ["corrupted"],
                    "log": "보복과 좌천이 두려워 정의 대신 침묵을 선택한 그날 밤 잠을 이루지 못했다.",
                    "tp": f"22세: '어쩔 수 없었다'는 변명 뒤에 숨어 처음 양심을 접고 말다.",
                    "outcome": f"특진 포상금과 칭찬이 따라왔지만, 복도를 빠져나가던 유가족의 절망 어린 눈빛이 며칠이고 {v['workplace']} 불빛마다 어른거렸습니다.",
                },
            ]
        elif career == "wanderer":
            scene_desc = (
                f"{bline}낯선 땅과 바람을 쫓아 국경과 바다를 건너온 스물둘의 {v['name']}. 폭우가 쏟아지던 어느 밤, "
                f"**{v['workplace']}** 지붕 너머로 빗물이 새고 여권과 노잣돈까지 젖어 버린 채 낯선 도시 한복판에 고립되었습니다. "
                f"배낭 안에 남은 건 **{v['tool']}**{p_wa(v['tool'])} 어린 날부터 지닌 **{v['item_short']}**뿐입니다."
            )
            chs = [
                {
                    "id": "d_wnd_write",
                    "label": "✍️ 길 위에서 만난 이름 없는 이웃들의 삶을 도와주고 그들의 이야기를 기록한다",
                    "hint": "공감 +7 · 열정 +5 · 인간에 대한 깊은 통찰 ([별의 씨앗+])",
                    "delta": {"empathy": 7, "passion": 5},
                    "add_flags": ["star_seed", "honest_path"],
                    "log": "낯선 이방인들의 따뜻한 밥 한 공기에 빚지며 그들의 이름 없는 역사를 수첩에 담았다.",
                    "tp": f"22세: 무일푼 이방인으로 국경을 떠돌며 세상의 가장 낮은 사람들의 이야기를 기록하다.",
                    "outcome": f"말도 통하지 않는 노파가 내민 찐 감자 두 알을 받아 들던 밤, {v['name_eun']} 세상 어디를 가도 사람 사는 온기는 같다는 사실을 뼈저리게 적었습니다.",
                },
                {
                    "id": "d_wnd_grit",
                    "label": "⚓ 항구 부두 막노동과 임시 수리공 일을 뛰며 스스로 노잣돈을 벌어낸다",
                    "hint": "근성 +8 · 자산 +4 · 세상 어디서도 굶지 않을 생존력",
                    "delta": {"grit": 8, "wealth": 4},
                    "add_flags": ["tough_survivor"],
                    "log": "거친 바다와 막노동 현장에서 몸소 생존하는 강인한 배짱을 길렀다.",
                    "outcome": f"물집이 터진 손으로 그물을 꿴 두 달 만에 넉넉한 여비와 새 카메라 필름을 쥔 {v['name_eun']} 다시 지평선 너머로 걸어 나갔습니다.",
                },
                {
                    "id": "d_wnd_smug",
                    "label": "🎭 항구 뒷골목에서 큰돈을 준다는 밀수 운반 의뢰에 손을 대고 만다",
                    "hint": "자산 +10 · 공감 -5 · [그림자 브로커]로 어두운 전직",
                    "delta": {"wealth": 10, "empathy": -5},
                    "set_career": "shadow",
                    "add_flags": ["corrupted"],
                    "log": "궁핍함 끝에 손댄 밀수 심부름을 계기로 도시 그림자 세계의 브로커가 되었다.",
                    "tp": f"22세: 배고픔 앞에서 넘어선 안 될 선을 넘으며 방랑자에서 그림자 브로커로 추락하다.",
                    "outcome": f"자정을 넘어 불 꺼진 세관을 빠져나온 상자 안에서 엄청난 지폐 다발을 쥔 순간, 순수했던 여행자의 수첩은 어두운 수첩으로 바뀌었습니다.",
                },
            ]
        else:  # shadow
            scene_desc = (
                f"{bline}밤이 되어야 진짜 업무가 시작되는 **{v['workplace']}**. 차명 계좌와 암호화된 호출기로 첫 큰돈을 손에 쥔 스물둘의 {v['name']}.\n\n"
                f"그러나 오늘 밤 **{v['patron']}**{v['patron_i_s']} 넘긴 서류철을 풀어보니, 거래가 실행되면 아무 죄 없는 평범한 상인 가족의 전 재산이 내일 아침 공중분해될 정황이 드러납니다."
            )
            chs = [
                {
                    "id": "d_shd_cold",
                    "label": "🧊 감정은 이 세계에서 가장 위험한 약점이다. 의뢰만 정확히 끝낸다",
                    "hint": "자산 +10 · 지성 +3 · 공감 -6 · 냉혹한 그림자의 프로",
                    "delta": {"wealth": 10, "intellect": 3, "empathy": -6},
                    "add_flags": ["corrupted"],
                    "log": "죄책감을 도려내며 암흑 시장에서 가장 빈틈없는 브로커로 입지를 굳혔다.",
                    "tp": f"22세: 무고한 사람의 눈물 앞에서 마음을 닫고 완벽한 그림자 브로커가 되다.",
                    "outcome": f"다음 날 새벽 뉴스 한 귀퉁이에 그 집안의 부도 소식이 스쳐 지나갔을 때조차, {v['name_eun']} 아무렇지 않게 두 번째 커피를 내렸습니다.",
                },
                {
                    "id": "d_shd_leak",
                    "label": "🕳️ 일은 진행하되 피해자에게 익명으로 경고 메모를 몰래 보내 피할 틈을 준다",
                    "hint": "공감 +5 · 지성 +4 · 근성 -2 · 어둠 속에 남은 한 줄기 양심",
                    "delta": {"empathy": 5, "intellect": 4, "grit": -2},
                    "add_flags": ["secret_mercy"],
                    "log": "어둠의 거래를 이어가면서도 최소한의 선만은 넘지 않으려 몰래 피해자를 살렸다.",
                    "tp": f"22세: 그림자 세계 한가운데서도 마지막 양심의 숨구멍 하나는 뚫어두다.",
                    "outcome": f"우체통에 익명 편지를 넣고 돌아서던 새벽, 들킬지 모른다는 식은땀 속에서도 이상하리만치 숨통이 트이는 기분이 들었습니다.",
                },
            ]
        return _make_node(f"b8_{career}", f"{'🎨🔬💼🌿⚖️🧭🎭'[list(('artist','scholar','entrepreneur','artisan','guardian','wanderer','shadow')).index(career) if career in ('artist','scholar','entrepreneur','artisan','guardian','wanderer','shadow') else 3]} {age}세 — [{v['specialty']}]로서의 첫 무대와 시련", scene_desc, 4, chs)

    # ── BEAT 9 (26세: 약속의 재회 OR 일터·현장 속의 새로운 사랑) ──
    if beat == 9:
        if "comp_promised" in flags:
            dark_note = (
                f"\n\n문득 책상 위 급히 덮어둔 어두운 서류철과 내 손에 묻은 씁쓸한 흔적이 떠올라, "
                f"{v['name_eun']} 자기도 모르게 **{v['comp']}**의 맑은 눈을 마주 보기가 겁이 납니다."
                if "corrupted" in flags
                else ""
            )
            return _make_node(
                "b9_reunion_comp",
                f"💐 {age}세 — 약속처럼 {v['workplace']} 앞에 찾아온 '{v['comp']}'",
                (
                    f"{bline}봄비가 가늘게 내리던 스물여섯의 퇴근길. 지친 눈을 비비며 **{v['workplace']}** 문을 나서던 {v['name']} 앞, "
                    f"빗물 맺힌 우산 하나를 들고 누군가 조용히 웃으며 서 있습니다.\n\n"
                    f"어릴 적 {v['hangout']}에서, 그리고 열여덟 겨울 **{v['night_spot']}**에서 손을 걸었던 **{v['comp']}**입니다. "
                    f"\"오랜만이야, {v['name_ya']}. 나 그날 한 약속… 진짜 기억하고 있었어.\"{dark_note}"
                ),
                4,
                [
                    {
                        "id": "b9_commit_comp",
                        "label": f"💍 멈추지 않고 달려온 걸음을 세우고, 이제 {v['comp_wa']} 함께 걸어가기로 한다",
                        "hint": "공감 +8 · 열정 +3 · 소꿉친구 동반자 확정 ([오래된 약속의 완성] 정통 루트)",
                        "delta": {"empathy": 8, "passion": 3},
                        "set_partner": v["comp"],
                        "set_comp_rel": "partner",
                        "add_flags": ["has_partner", "partner_committed"],
                        "log": f"{v['workplace']} 앞에서 다시 만난 {v['comp_wa']} 평생을 함께하는 동반자가 되었다.",
                        "tp": f"26세: 8년 전의 약속대로 돌아온 {v['comp']}의 손을 맞잡고 한 삶이 되다.",
                        "outcome": f"우산 아래 두 어깨가 닿자 지난 타지 생활의 춥고 서러운 날들이 한꺼번에 녹아내렸습니다. 그날 밤 두 사람은 9살 때처럼 밤새도록 미래를 그렸습니다.",
                    },
                    {
                        "id": "b9_miss_comp",
                        "label": "💔 지금 내 삶과 일이 너무 위태로워서, 미안하다는 말만 남긴 채 돌려보낸다",
                        "hint": "근성 +4 · 열정 +3 · 공감 -3 · 44세 기적 같은 재회 혹은 고독의 길",
                        "delta": {"grit": 4, "passion": 3, "empathy": -3},
                        "set_comp_rel": "missed",
                        "add_flags": ["comp_missed", "solo_path"],
                        "log": f"스물여섯의 현실과 짐 때문에 끝내 {v['comp_eul']} 잡지 못한 채 홀로 일에 매달렸다.",
                        "tp": f"26세: 다시 찾아온 {v['comp_eul']} 내 처지가 부끄럽고 벅차 눈물로 돌려보내다.",
                        "outcome": f"\"지금 내 곁에 있으면 너까지 힘들어져.\" 진심이 아닌 차가운 거짓말 뒤에서 빗속으로 멀어지는 {v['comp']}의 뒷모습을 보고 {v['name_eun']} 밤새 울었습니다.",
                    },
                ],
            )

        meet_by_spec = {
            "artist_paint": f"비가 쏟아지던 소규모 전시 마지막 날, 남들 다 빠져나간 전시장에서 그림 앞을 떠나지 못한 채 조용히 숨을 고르던 **{v['adult_partner']}**",
            "artist_music": f"관객 여섯 명뿐이던 홍대 뒤편 소극장 무대 끝, 낡은 녹음 테이프를 사주며 \"이 선율 오래 기억할 것 같아요\"라고 말한 **{v['adult_partner']}**",
            "artist_write": f"낡은 독립 서점 구석에서 내 첫 무명 책 귀퉁이를 접어가며 밑줄을 긋고 있던 다정한 눈빛의 **{v['adult_partner']}**",
            "scholar_healer": f"새벽 응급 병동 복도에서 72시간 당직으로 비틀거리던 {v['name']}에게 조용히 따뜻한 유자차를 건넨 **{v['adult_partner']}**",
            "scholar_cosmos": f"산 정상 천문 연구동으로 가는 마지막 셔틀이 끊긴 밤, 함께 밤하늘을 걸어 내려오며 별 이름을 묻던 **{v['adult_partner']}**",
            "scholar_archive": f"지하 서고 열람실 마감 종이 울릴 때마다 매번 같은 창가에서 조용히 미소 짓던 **{v['adult_partner']}**",
            "ent_food": f"지방 납품 길을 돌다 폭설에 갇힌 국도 휴게소에서 함께 컵라면을 나눠 먹으며 사업 고민을 들어준 **{v['adult_partner']}**",
            "ent_tech": f"거절만 당하고 돌아오던 밤 지하철역 벤치에서 내 낡은 도면 서류를 주워주며 끝까지 이야기를 들어준 **{v['adult_partner']}**",
            "ent_trade": f"안개 낀 항구 세관 앞에서 수출 서류와 씨름하던 {v['name']} 곁에 우산 하나를 조용히 씌워준 당찬 **{v['adult_partner']}**",
            "artn_noodle": f"새벽 첫차를 놓치고 추위에 떨며 국수 한 그릇을 다 비운 뒤 \"세상에서 제일 따뜻한 밤이었어요\"라던 **{v['adult_partner']}**",
            "artn_clock": f"어머니의 낡은 손목시계 수리를 맡기러 공방에 들른 뒤, 초침 소리를 좋아한다며 매주 차를 사 들고 온 **{v['adult_partner']}**",
            "artn_tea": f"산비에 젖어 다실로 뛰어든 뒤 따뜻한 덖음차 한 잔에 긴 이야기를 털어놓았던 **{v['adult_partner']}**",
            "artn_craft": f"빵 굽는 냄새가 골목을 감싸던 퇴근길마다 늘 마지막 남은 빵을 사 가며 미소 짓던 **{v['adult_partner']}**",
            "grd_press": f"온갖 협박 문자에 시달리던 저녁, 보도국 뒷골목에서 묵묵히 함께 걸어주며 방패가 되어준 **{v['adult_partner']}**",
            "grd_detective": f"잠복 근무 끝에 탈진해 쓰러진 새벽, 아무것도 묻지 않고 따뜻한 국밥과 편지를 놓고 간 **{v['adult_partner']}**",
            "grd_advocate": f"패소 위기에 꺾여 있던 재판 뒤풀이에서 \"그래도 누군가는 끝까지 싸워줘야죠\"라며 내 손을 잡은 **{v['adult_partner']}**",
            "wnd_photo": f"국경 산악 열차의 딱딱한 나무 좌석에서 같은 지도를 펼쳐 들고 밤새 여행 이야기를 나눈 **{v['adult_partner']}**",
            "wnd_relief": f"구호 천막 밖 먼지 바람 속에서 지친 아이들을 함께 돌보며 말이 통하지 않아도 마음으로 통한 **{v['adult_partner']}**",
            "shd_broker": f"이름도 직업도 밝히지 못한 상처를 아무것도 캐묻지 않은 채 묵묵히 약을 발라준 유일한 사람 **{v['adult_partner']}**",
            "shd_launder": f"빗속 지하실에서 나와 젖은 어깨를 털어줄 때 가짜 이름 대신 진짜 내 눈빛을 알아본 **{v['adult_partner']}**",
        }
        m_txt = meet_by_spec.get(v["specialty_id"], meet_by_spec["artn_craft"])
        return _make_node(
            "b9_new_love",
            f"💞 {age}세 — 치열한 청춘 한가운데 스며든 사람 '{v['adult_partner']}'",
            (
                f"{bline}잠과 밥을 줄여가며 오직 **[ {v['specialty']} ]** 외길만 내달리던 스물여섯의 {v['name']}. "
                f"차갑던 **{v['workplace']}** 주변의 공기 속에 예상치 못한 다정한 계절이 찾아왔습니다.\n\n"
                f"{m_txt}. 어느덧 두 사람은 거친 하루 끝마다 가장 먼저 안부가 떠오르는 사이가 되었습니다."
            ),
            4,
            [
                {
                    "id": "b9_commit_new",
                    "label": f"💍 방어적인 마음을 열고 {v['adult_partner']}에게 평생의 곁을 내어준다",
                    "hint": "공감 +8 · 근성 +2 · 가정을 이루고 함께 버티는 삶",
                    "delta": {"empathy": 8, "grit": 2},
                    "set_partner": v["adult_partner"],
                    "add_flags": ["has_partner", "partner_committed"],
                    "log": f"{v['adult_wa']} 깊은 신뢰를 약속하며 한 지붕 아래 살아갈 둥지를 꾸렸다.",
                    "tp": f"26세: 치열한 세상 한가운데서 나를 이해해 준 {v['adult_wa']} 평생의 짝이 되다.",
                    "outcome": f"작은 반지하방이든 좁은 전셋집이든 두 사람이 함께 저녁상을 펴고 앉자 세상의 무게가 절반으로 줄어드는 기적이 일어났습니다.",
                },
                {
                    "id": "b9_stay_solo",
                    "label": "🕊️ 따뜻한 마음에 감사하면서도, 아직은 내 길에 온전히 집중하겠다며 선을 긋는다",
                    "hint": "지성 +4 · 열정 +5 · 독립적 행보 (홀로 정점을 향해)",
                    "delta": {"intellect": 4, "passion": 5},
                    "add_flags": ["solo_path"],
                    "log": "누군가에게 얽매여 속도를 늦추기보다 나만의 길을 끝까지 가보기로 정했다.",
                    "tp": f"26세: 다정한 인연 앞에서조차 내 일과 소명을 위해 고독한 길을 택하다.",
                    "outcome": f"\"{v['name']} 씨는 늘 멀리 보고 있는 사람 같았어요.\" 조용히 물러선 {v['adult_partner']}의 배려 뒤로, 더욱 고요하고 집요한 나날이 시작되었습니다.",
                },
            ],
        )

    # ── BEAT 10 (30세: 서른 살의 폭풍 — 과거 편법 업보 분기 vs 정통 직업 갈림길 vs 고향 회귀) ──
    if beat == 10:
        if "corrupted" in flags and career != "shadow":
            st_title = f"⛈️ {age}세 — 서른 살의 청구서, 과거의 거짓이 문 두드리다"
            st_body = (
                f"{bline}서른 살을 맞아 승승장구하던 {v['name']}의 **{v['workplace']}** 앞으로 날카로운 등기 우편 한 통과 낯선 방문객이 찾아옵니다.\n\n"
                f"스물둘에 손을 댔던 잘못된 타협과 조작된 흔적, 바로 그 뒷면에서 피해를 보았던 사람의 가족(또는 감사팀)이 **{v['work_obj']}** 사본을 들이밀며 "
                f"진실을 묻기 시작한 것입니다. 옆방에서는 브로커가 '돈으로 입을 막고 더 높이 올라가자'고 속삭입니다."
            )
            choices = [
                {
                    "id": "b10_stand",
                    "label": "⚖️ 지금이라도 모든 이권을 포기하고 잘못을 인정한 뒤 원칙으로 돌아간다",
                    "hint": "공감 +8 · 지성 +4 · 자산 -7 · 과거의 굴레 청산 ([정직한 길] 복귀)",
                    "delta": {"empathy": 8, "intellect": 4, "wealth": -7},
                    "add_flags": ["honest_path"],
                    "remove_flags": ["corrupted"],
                    "log": "서른 살에 찾아온 과거의 청구서 앞에서 회피 대신 정직한 배상과 책임을 택했다.",
                    "tp": f"30세: 거짓된 성공을 스스로 무너뜨리고 원칙의 길로 어렵게 돌아서다.",
                    "outcome": f"모아둔 재산 상당수가 배상으로 날아가고 언론·업계의 조롱이 쏟아졌지만, 그날 밤 {v['name_eun']} 수년 만에 다리를 뻗고 깊은 잠에 들었습니다.",
                },
                {
                    "id": "b10_compromise",
                    "label": "💰 이미 늦었다. 돈과 권력을 총동원해 제보자의 입을 막고 더 거대하게 덮는다",
                    "hint": "자산 +14 · 공감 -8 · 지성 -2 · 되돌리기 힘든 어둠의 정점",
                    "delta": {"wealth": 14, "empathy": -8, "intellect": -2},
                    "add_flags": ["corrupted"],
                    "log": "진실이 드러날 위기마저 돈과 위력으로 틀어막으며 어두운 권력의 길로 깊숙이 들어섰다.",
                    "tp": f"30세: 반성 대신 더 두꺼운 장막과 돈으로 진실을 입막음하는 비정함을 택하다.",
                    "outcome": f"위기는 며칠 만에 감쪽같이 지워지고 통장 잔고는 더 크게 불어났지만, 거울 속 자신의 눈빛마저 점점 낯선 괴물을 닮아갔습니다.",
                },
            ]
        else:
            storm_map = {
                "artist": (
                    f"⛈️ {age}세 — 대형 자본의 천문학적 계약 vs 훼손되는 내 원작",
                    f"{bline}서른 살을 맞은 [{v['specialty']}] {v['name']}의 **{v['workplace']}**{p_ro(v['workplace'])} 거대 기획사·출판사의 대표가 직접 찾아왔습니다.\n\n"
                    f"책상 위에 놓인 것은 빚을 다 갚고도 남을 천문학적 계약금. 하지만 조건은 **\"{v['work_obj']}의 핵심 줄기와 아픔은 전부 걷어내고 대중 취향대로 껍데기만 남기라\"**는 것입니다.",
                ),
                "scholar": (
                    f"⛈️ {age}세 — 거액 스폰서 제의와 은폐해야 하는 치명적 오류",
                    f"{bline}서른이 된 [{v['specialty']}] {v['name_eun']} 핵심 자료를 검토하던 새벽, 대형 프로젝트 전체를 뒤집을 중대한 결함과 위험 단서를 찾아냅니다.\n\n"
                    f"**{v['patron']}**{v['patron_eun_s']} \"발표하면 연구단도 네 앞길도 오늘로 끝이야. 묻고 가면 평생 지원금을 보장하지\"라며 문을 잠급니다.",
                ),
                "entrepreneur": (
                    f"⛈️ {age}세 — 상장(IPO) 직전의 회계 분식 유혹과 동업자의 배신",
                    f"{bline}서른의 문턱, 연 매출이 수십억으로 치솟은 {v['name']}의 회사에 동업자가 다가와 **\"투자자들 비위 맞추려면 장부랑 세금 서류 좀 건드려야 한다\"**며 법인 인감을 내밉니다.\n\n"
                    f"거절하면 자금줄이 말라 당장 직원들 월급부터 막힐 절벽 끝입니다.",
                ),
                "artisan": (
                    f"⛈️ {age}세 — 재개발 철거 통보와 대기업 브랜드 매각 제의",
                    f"{bline}골목의 든든한 버팀목이 되어가던 {v['name']}의 **{v['workplace']}** 유리창에 붉은 재개발 공고문이 붙던 아침, **{v['patron']}**{v['patron_i_s']} 검은 양복 차림으로 들어섭니다.\n\n"
                    f"\"이 낡은 골목 끝났어요. 브랜드 이름과 레시피·설계도만 넘기시면 평생 놀고먹을 권리금을 드리죠.\"",
                ),
                "guardian": (
                    f"⛈️ {age}세 — 거물 비리 원본 파일, 그리고 곁을 겨눈 협박 전화",
                    f"{bline}서른의 [{v['specialty']}] {v['name']} 금고 안엔 정재계 윗선 전체를 흔들 결정적 원본 파일이 들어왔습니다.\n\n"
                    f"하지만 자정이 넘은 시간, 발신 번호 없는 전화기 너머로 차가운 목소리가 속삭입니다. \"네 가족과 {v['city']}에 있는 집 주소까지 다 알고 있다. 덮으면 자리 하나 주지.\"",
                ),
                "wanderer": (
                    f"⛈️ {age}세 — 위험한 분쟁·재난지 취재 vs 안락한 베스트셀러 계약",
                    f"{bline}세상의 변방을 기록해 온 서른 살의 {v['name']}에게 두 통의 편지가 동시에 도착합니다.\n\n"
                    f"한 통은 굶주림과 폭격이 멈추지 않는 변방 마을의 간절한 구조 기록 요청이고, 다른 한 통은 적당히 예쁜 여행기만 써 달라는 대형 출판사의 거액 계약서입니다.",
                ),
                "shadow": (
                    f"⛈️ {age}세 — 돌이킬 수 없는 선, 조직의 최종 의뢰와 도망의 틈",
                    f"{bline}그림자 세계의 실세 반열에 오른 서른 살. **{v['patron']}**{v['patron_eun_s']} 이제 단순 중개를 넘어 한 무고한 인물의 인생을 완전히 매장시키는 범죄 공범을 요구합니다.\n\n"
                    f"지금 이 명령을 받으면 두 번 다시 햇빛 아래 이름으로 돌아가지 못할 마지막 기로입니다.",
                ),
            }
            st_title, st_body = storm_map.get(career, storm_map["artisan"])
            choices = [
                {
                    "id": "b10_stand",
                    "label": "⚖️ 당장 손해를 입고 밀려나더라도 내 신념과 진실만큼은 절대 팔지 않는다",
                    "hint": "공감 +6 · 지성 +4 · 자산 -5 · 올곧은 지조 ([진실/거장] 루트)",
                    "delta": {"empathy": 6, "intellect": 4, "wealth": -5},
                    "add_flags": ["honest_path", "whistleblower"] if career == "guardian" else ["honest_path"],
                    "remove_flags": ["corrupted"],
                    "log": "서른 살의 거대한 유혹 앞에서 금전적 손해를 감수하고 스스로의 원칙을 지켜냈다.",
                    "tp": f"30세: 천문학적인 조건과 협박 앞에서도 결국 양심과 진짜 가치를 꺾지 않다.",
                    "outcome": f"계약은 찢어지고 통장은 텅 비었지만, 찬 바람 부는 문밖을 나서며 {v['name_eun']} 평생 처음으로 자기 이름이 부끄럽지 않다고 느꼈습니다.",
                },
                {
                    "id": "b10_compromise",
                    "label": "💰 이상만으로는 못 버틴다. 눈을 질끈 감고 세상의 조건을 받아들인다",
                    "hint": "자산 +14 · 공감 -8 · 지성 -2 · 거대한 부와 어두운 그림자",
                    "delta": {"wealth": 14, "empathy": -8, "intellect": -2},
                    "add_flags": ["corrupted"],
                    "log": "부와 명성을 얻는 대신 오랫동안 지켜온 신념을 세상의 조건과 맞바꾸었다.",
                    "tp": f"30세: 이상을 접고 부와 현실적 권력을 택하며 차가운 타협의 길로 들어서다.",
                    "outcome": f"곧바로 더 넓은 사무실과 화려한 대우가 따라왔지만, 서랍 깊숙이 밀어 넣은 {v['item_eul']} 꺼낼 엄두조차 나지 않게 되었습니다.",
                },
            ]

        # Origin home-call pivot or Wanderer freedom pivot
        if oid == "noodle_shop" and v["specialty_id"] != "artn_noodle":
            choices.append({
                "id": "b10_noodle_pivot",
                "label": f"🍜 지친 타지 경쟁을 접고 {v['city']} 어머니의 작은 국수집을 살리러 돌아간다",
                "hint": "공감 +8 · 근성 +5 · [골목 손멸치국수 장인] 전직 ([국수 한 그릇의 우주] 개방)",
                "delta": {"empathy": 8, "grit": 5},
                "set_career": "artisan",
                "set_specialty": "artn_noodle",
                "add_flags": ["noodle_revival", "honest_path", "protect_local"],
                "remove_flags": ["corrupted"],
                "log": f"화려한 바깥의 욕심을 내려놓고 {v['city']} 시장통 낡은 국수집의 불을 다시 지폈다.",
                "tp": f"30세: 모든 걸 접고 어머니의 무너져가는 {v['city']} 국수집을 되살리려 고향으로 돌아가다.",
                "outcome": f"무릎이 다 닳아 누워 계신 어머니 대신 새벽 4시 불을 켠 {v['name']} 손에 다시 {v['item_i']} 쥐여지자, 시장 이웃들이 하나둘 울먹이며 아침 첫 손님으로 찾아왔습니다.",
            })
        elif oid == "mountain_clinic" and v["specialty_id"] != "scholar_healer":
            choices.append({
                "id": "b10_clinic_pivot",
                "label": f"🩺 도시의 허영을 버리고 할아버지의 {v['city']} 산골 약초방·진료소를 물려받는다",
                "hint": "공감 +8 · 지성 +4 · [공공·임상 의학자] 전직 ([생명을 잇는 손] 개방)",
                "delta": {"empathy": 8, "intellect": 4},
                "set_career": "scholar",
                "set_specialty": "scholar_healer",
                "add_flags": ["healer_oath", "honest_path", "protect_local"],
                "remove_flags": ["corrupted"],
                "log": f"연로한 할아버지의 부름을 받고 {v['city']} 산골 마을 사람들의 생명을 지키는 길을 택했다.",
                "tp": f"30세: 도시의 출세 길을 접고 할아버지의 산골 진료소를 이어받아 사람들을 살리다.",
                "outcome": f"안개 낀 고향 약초방 문을 다시 열자 산너머 어르신들이 \"우리 손주 왔다!\"며 지팡이를 짚고 마당으로 달려 나왔습니다.",
            })
        else:
            choices.append({
                "id": "b10_pivot_freedom",
                "label": "🧭 썩어버린 판 자체에 환멸을 느끼고 가방을 싸 세상 끝으로 떠난다",
                "hint": "열정 +6 · 지성 +4 · [방랑·세계 기록가] 전직 ([끝없는 지평선] 루트)",
                "delta": {"passion": 6, "intellect": 4},
                "set_career": "wanderer",
                "add_flags": ["honest_path"],
                "remove_flags": ["corrupted"],
                "log": "기존의 자리와 유혹을 미련 없이 털어내고 길 위에서 세상을 기록하는 방랑자가 되었다.",
                "tp": f"30세: 거짓된 성공의 판을 걷어차고 낡은 배낭과 함께 자유로운 길 위로 떠나다.",
                "outcome": f"사직서와 열쇠를 책상에 올려두고 공항·항구 버스에 오른 오후, 삼십 년 인생 처음으로 폐가 부서질 듯 상쾌한 바람이 불어왔습니다.",
            })

        return _make_node("b10_storm", st_title, st_body, 4, choices)

    # ── BEAT 11 (34세: 서른넷의 생활 — 가정의 온기/균열 OR 일터의 고독과 과로) ──
    if beat == 11:
        if "has_partner" in flags:
            corrupted_strain = (
                f"더욱이 최근 {v['name']}에게 걸려오는 수상한 밤 전화와 서늘해진 눈빛을 보며 {v['partner_eun']} 아무 말 못 한 채 조용히 속을 앓고 있습니다.\n\n"
                if "corrupted" in flags
                else ""
            )
            return _make_node(
                "b11_family",
                f"🏡 {age}세 — '{v['partner']}'{v['partner_wa_s']} 마주 앉은 서른넷의 식탁",
                (
                    f"{bline}{v['partner_wa']} 한 지붕 아래에서 풍파를 견디며 살아온 지도 어느덧 여덟 해. "
                    f"생활비와 **[ {v['specialty']} ]** 일터의 중압감에 치여, 두 사람이 서로 눈을 맞추고 밥 한 끼 먹은 날이 손에 꼽을 만큼 줄었습니다.\n\n"
                    f"{corrupted_strain}오늘 밤 늦게 들어온 {v['name']} 앞에 {v['partner_i']} 식지 않게 데워둔 국그릇 두 개를 놓고 조용히 말을 꺼냅니다.\n"
                    f"> *\"우리… 요새 무슨 생각 하면서 사는지 얘기 좀 해. 나 요즘 자꾸 당신이 멀게 느껴져.\"*"
                ),
                5,
                [
                    {
                        "id": "b11_fam_warm",
                        "label": f"🫂 일을 조금 줄이고 수익이 덜하더라도 {v['partner']}의 손을 잡고 속마음을 나눈다",
                        "hint": "공감 +8 · 근성 +3 · 가정의 온기 회복 (오래된 약속 유지 필수)",
                        "delta": {"empathy": 8, "grit": 3},
                        "add_flags": ["family_warm"],
                        "remove_flags": ["partner_strained"],
                        "log": f"{v['partner']}의 눈을 마주 보며 바쁜 세월 속 잃어가던 가정의 온기를 지켜냈다.",
                        "tp": f"34세: 성공보다 소중한 것은 지금 내 앞의 사람임을 깨닫고 {v['partner_wa']} 화해하다.",
                        "outcome": f"그날 밤 식은 국그릇을 두고 새벽 두 시까지 나눈 서러운 고백 끝에 두 사람은 스물여섯의 그날처럼 다시 웃을 수 있었습니다.",
                    },
                    {
                        "id": "b11_fam_work",
                        "label": "💼 \"다 우리 가족 잘 살자고 뛰는 거잖아!\"라며 더 늦게까지 일터로만 파고든다",
                        "hint": "자산 +8 · 열정 +4 · 공감 -6 · 관계의 깊은 균열 위험",
                        "delta": {"wealth": 8, "passion": 4, "empathy": -6},
                        "add_flags": ["partner_strained"],
                        "log": "가족을 위한다는 핑계로 일에만 매몰되어 집 안의 대화가 차갑게 얼어붙기 시작했다.",
                        "tp": f"34세: 일에 미쳐 사랑하는 {v['partner']}의 외로움을 외면하고 거리를 벌려놓다.",
                        "outcome": f"\"그만 얘기하자.\" {v['partner_i']} 조용히 수저를 내려놓고 방문을 닫는 소리가 다음 날 새벽 출근길까지 귓가를 떠나지 않았습니다.",
                    },
                ],
            )

        return _make_node(
            "b11_solo_mature",
            f"🌆 {age}세 — 불 꺼진 {v['workplace']}, 서른넷의 고독한 등불",
            (
                f"{bline}자정이 훌쩍 넘은 시간. **{v['workplace']}** 바닥에 홀로 앉은 서른넷의 {v['name_eun']} 신발을 벗은 채 천장을 바라봅니다.\n\n"
                f"옛 동창들은 청첩장과 돌잔치 소식을 보내오지만, 당신의 책상 위에는 손때가 벗겨진 **{v['tool']}**, 어린 날 챙겨온 **{v['item_short']}**, "
                f"그리고 아무도 대신 걸어줄 수 없는 외로운 세월만이 놓여 있습니다. 최근 들어 무리한 날이면 심장이 뻐근하게 조여 옵니다."
            ),
            5,
            [
                {
                    "id": "b11_solo_health",
                    "label": "🍵 무리한 욕심을 조금 내려놓고 몸과 마음을 돌보며 깊이를 다진다",
                    "hint": "근성 +8 · 지성 +3 · 건강한 성숙과 안정",
                    "delta": {"grit": 8, "intellect": 3},
                    "remove_flags": ["overworked"],
                    "log": "조급함을 버리고 규칙적인 수면과 사색으로 서른넷의 고독을 단단히 다듬었다.",
                    "outcome": f"오래 앓던 불면이 조금씩 가시고, 맑아진 정신 덕분에 {v['work_obj_eul']} 바라보는 시선도 한층 깊고 여유로워졌습니다.",
                },
                {
                    "id": "b11_solo_burn",
                    "label": "🔥 잠과 밥까지 깎아가며 오직 내 일의 한계를 넘기 위해 몸을 불태운다",
                    "hint": "열정 +9 · 지성 +5 · 근성 -10 · [⚠️ 극심한 건강 고갈 → 39세 희생 엔딩 근접]",
                    "delta": {"passion": 9, "intellect": 5, "grit": -10},
                    "add_flags": ["overworked"],
                    "log": "몸이 보내는 경고를 무시하고 밤낮없이 목표에 모든 체력을 쏟아부었다.",
                    "tp": f"34세: 건강을 돌보지 않고 오직 한 길만을 향해 온몸을 깎아내듯 몰아붙이다.",
                    "outcome": f"경이로운 결과물들이 쏟아져 나왔지만, 기침을 할 때마다 가슴 한쪽이 칼로 베이는 듯 시리고 손끝이 미세하게 떨리기 시작했습니다.",
                },
                {
                    "id": "b11_solo_share",
                    "label": "🤝 내 외로움 대신 갈 곳 없는 후배들과 동네 이웃들에게 먼저 손을 내민다",
                    "hint": "공감 +8 · 열정 +2 · 연대와 스승의 마음 싹틈",
                    "delta": {"empathy": 8, "passion": 2},
                    "add_flags": ["community_care", "protect_local"],
                    "log": "혼자라는 이유로 문을 닫기보다 후배들과 동네 이웃들에게 온기를 나누기 시작했다.",
                    "tp": f"34세: 고독에 갇히지 않고 어두운 골목과 젊은 후배들의 버팀목이 되어주다.",
                    "outcome": f"밤마다 들르는 단골 후배와 동네 아이들 웃음소리가 차갑던 {v['workplace']}에 다시 사람 냄새를 채워 주었습니다.",
                },
            ],
        )


# ==========================================
# 9. BEAT 12~15 : 장년기 (39세 · 44세 · 50세 · 56세)
# ==========================================
def _build_midlife_node(beat: int, life: Dict[str, Any], v: Dict[str, Any]) -> Dict[str, Any]:
    age = v["age"]
    career = v["career"]
    flags = set(life.get("flags") or [])
    stats = life.get("stats") or {}
    bridge = _prev_bridge(life, v)
    bline = f"{bridge}\n\n" if bridge else ""

    # ── BEAT 12 (39세: 7대 직업별 전용 서른아홉 대위기!) ──
    if beat == 12:
        cur_grit = int(stats.get("grit", 25) or 25)
        will_burn = (cur_grit <= 22) or (cur_grit <= 28 and "overworked" in flags)
        grit_warn = (
            f"\n\n> ⚠️ **경고 — 한계 체력 (현재 근성 `{cur_grit}`):** 서른넷 이후 누적된 피로와 상처 때문에 심장이 턱끝까지 차오릅니다. "
            f"지금 불길과 잔해 속으로 온몸을 던지면 살아서 나오지 못하고 **[🔥 불꽃 같은 서른아홉] 엔딩**으로 직행할 수 있습니다!"
            if will_burn
            else f"\n\n*(현재 근성 `{cur_grit}` — 위기를 감수하고 뛰어들거나 냉철히 우회로를 찾을 체력이 남아 있습니다.)*"
        )

        crisis_by_career = {
            "artist": (
                f"🔥 {age}세 — 겨울밤 전시장·{v['workplace']} 대형 누전 화재",
                f"{bline}서른아홉의 한겨울 밤, 평생 땀을 쏟은 전시 회고전 전날 밤에 오래된 전시장 전기 배선에서 시뻘건 불기둥이 솟구쳤습니다.\n\n"
                f"유독 가스가 차오르는 복도 안쪽에는 아르바이트하던 어린 후배가 발목을 다쳐 쓰러져 있고, 바로 옆 방엔 20년 치 **{v['work_obj']}**{v['work_obj_i_s']} 불길에 휩싸여 있습니다.",
            ),
            "scholar": (
                f"🔥 {age}세 — 폭설로 고립된 {v['workplace']} 유독 가스 누출 및 고립",
                f"{bline}폭설로 도로가 끊긴 서른아홉의 새벽, **{v['workplace']}** 지하 보일러실과 시약·산소 배관이 동시에 파열되며 독한 연기가 병동과 연구층을 집어삼킵니다.\n\n"
                f"대피 경보가 울리는 가운데, 격리실 안에는 혼자 움직이지 못하는 환자와 연구실 후배가 쓰러져 있고 방화 셔터가 서서히 내려오기 시작합니다.",
            ),
            "entrepreneur": (
                f"🔥 {age}세 — 야간 창고 연쇄 폭발과 회사를 덮친 최악의 밤",
                f"{bline}서른아홉의 한여름 밤, 빗속 낙뢰와 누전이 겹치며 회사의 모든 핵심 물류가 쌓인 창고에서 거대한 화염이 터졌습니다.\n\n"
                f"무너져 내리는 철골 아래에는 경비를 서던 나이 든 아저씨가 깔려 신음하고, 바로 옆 방화 금고 안엔 회사와 수십 명 직원들의 운명이 달린 **{v['work_obj']}**{v['work_obj_i_s']} 타고 있습니다.",
            ),
            "artisan": (
                f"🔥 {age}세 — 폭우 밤 노후 골목 상가 가스 폭발과 천장 붕괴",
                f"{bline}태풍이 몰아치던 서른아홉의 밤, 오랜 세월 함께해 온 골목 옆집 주방에서 요란한 가스 폭발음이 터지고 천장 대들보가 주저앉았습니다.\n\n"
                f"연기 자욱한 옆 가게 밑에서 어린아이의 울음소리가 들려오고, 불길은 수십 년 피땀이 어린 **{v['workplace']}** 앞까지 번져 옵니다.",
            ),
            "guardian": (
                f"🔥 {age}세 — 비리 세력의 보복 방화 테러, 불타는 증거 보관소",
                f"{bline}서른아홉의 밤, 결정적 진실을 세상에 내놓기 직전 누군가 **{v['workplace']}** 계단에 시너를 붓고 불을 질렀습니다.\n\n"
                f"출입구가 막힌 안쪽 자료실에는 용기를 내어 나온 공익 제보자가 떨고 있고, 손에 들린 **{v['work_obj']}**{v['work_obj_i_s']} 아니면 수백 명의 억울함이 영원히 묻힐 판입니다.",
            ),
            "wanderer": (
                f"🔥 {age}세 — 산사태와 여진이 덮친 국경 마을 임시 대피소 붕괴",
                f"{bline}서른아홉의 이방 땅 한가운데서 밤새 폭우와 진도 6의 지진이 덮치며, 아이들과 주민들이 머물던 낡은 대피소 지붕이 순식간에 무너졌습니다.\n\n"
                f"추가 여진이 건물을 흔드는 절망 속에서 콘크리트 틈새 너머로 아이들의 희미한 구조 목소리가 들려옵니다.",
            ),
            "shadow": (
                f"🔥 {age}세 — 조직 배신자들의 매복 암살과 불타는 안전가옥",
                f"{bline}서른아홉의 비 오는 밤, 너무 많은 비밀을 쥔 {v['name_eul']} 제거하기 위해 옛 동업자들이 안전가옥에 불을 지르고 문을 밖에서 걸어 잠갔습니다.\n\n"
                f"타오르는 방 한켠에는 아무것도 모른 채 심부름 온 어린 소년 한 명이 묶여 있고, 출구 쪽 창문은 이미 쇠창살로 막혀 있습니다.",
            ),
        }
        c_title, c_body = crisis_by_career.get(career, crisis_by_career["artisan"])
        return _make_node(
            "b12_crisis39",
            c_title,
            c_body + grit_warn,
            5,
            [
                {
                    "id": "b12_heroic_risk",
                    "label": "🔥 내 몸과 전부를 내던져서라도 끝까지 안쪽으로 뛰어들어 생명을 구한다",
                    "hint": "공감 +10 · 열정 +8 · 근성 -18 · (체력/근성이 낮으면 🔥 [불꽃 같은 서른아홉] 엔딩 직행)",
                    "delta": {"empathy": 10, "passion": 8, "grit": -18},
                    "add_flags": ["reckless_hero"],
                    "trigger_flame_if_low_grit": True,
                    "log": f"서른아홉의 대위기 속에서 망설임 없이 몸을 던져 안에 갇힌 생명과 진실을 끌어안았다.",
                    "tp": f"39세: 타오르는 아수라장 속으로 기꺼이 뛰어들어 소중한 생명을 몸으로 막아내다.",
                    "outcome": (
                        f"뜨거운 열기와 시커먼 연기가 목을 태웠지만 {v['name_eun']} 쓰러진 이의 어깨를 들쳐 메고 끝내 문밖 아스팔트 위로 굴러 나왔습니다. "
                        f"응급차 들것 위에서 천장을 바라보며 남긴 깊은 화상 흉터는 평생 지워지지 않을 훈장이 되었습니다."
                    ),
                },
                {
                    "id": "b12_rescue_smart",
                    "label": "🛡️ 주변의 소화 장비·비상 도구를 침착히 지휘해 우회로를 뚫어 함께 탈출한다",
                    "hint": "지성 +5 · 공감 +5 · 근성 +3 · 살아남아 내일을 여는 냉철한 지혜",
                    "delta": {"intellect": 5, "empathy": 5, "grit": 3},
                    "add_flags": ["wise_survivor"],
                    "log": "위기의 순간에도 냉정을 잃지 않고 우회로와 주변 사람들의 협력을 끌어내 모두를 살렸다.",
                    "tp": f"39세: 대혼란 속에서도 무모함 대신 지혜로운 연대로 사람들을 안전히 이끌어내다.",
                    "outcome": f"젖은 외투를 벗어 입을 막고 뒤편 환기구와 철문을 지렛대로 뜯어낸 10분은 평생 가장 긴박하고 기적 같은 시간으로 기억되었습니다.",
                },
                {
                    "id": "b12_flee",
                    "label": "💨 무모한 희생보다 살아남아야 뒷일을 도모할 수 있다며 한 발 물러선다",
                    "hint": "근성 +6 · 자산 +4 · 공감 -3 · 냉혹한 생존 본능",
                    "delta": {"grit": 6, "wealth": 4, "empathy": -3},
                    "log": "위험 앞에서도 철저히 자신의 생존과 남은 가족·기반을 우선하며 물러섰다.",
                    "tp": f"39세: 감상적인 영웅심을 거부하고 살아남는 쪽을 택하며 마흔의 문턱을 넘다.",
                    "outcome": f"119 사이렌이 울리는 골목 끝에서 묵묵히 몸을 피한 {v['name_eun']} 살아남았지만, 타오르던 잔해 냄새는 오래도록 옷깃에 배어 있었습니다.",
                },
            ],
        )

    # ── BEAT 13 (44세: 중년의 떡밥 회수 — 26년 만의 소꿉친구 재회 / 부부 파도 / 스승의 나무 상자) ──
    if beat == 13:
        if ("has_partner" not in flags) and ("comp_missed" in flags or "comp_parted_warm" in flags or "comp_rival" in flags):
            if "comp_rival" in flags and "comp_missed" not in flags:
                greet_txt = (
                    f"가을비가 갠 **{v['station']}** 앞. 서류를 안고 바삐 걷던 {v['name_eun']} 맞은편에서 낯익은 날카로운 미소와 마주칩니다.\n\n"
                    f"어느새 눈가에 잔주름이 진 옛 라이벌 **{v['comp']}**입니다. \"야, 여전히 걸음걸이가 급하네. 우리 그 마지막 내기, 아직 결론 안 난 거 알지?\""
                )
            else:
                greet_txt = (
                    f"낙엽이 발목에 감기던 마흔넷의 가을 오후. **{v['station']}** 앞 오래된 서점 처마 밑에서, {v['name_eun']} 익숙한 이름을 부르는 낮은 목소리에 걸음을 멈췄습니다.\n\n"
                    f"흰머리가 성성하게 섞여 버린 **{v['comp_i']}** 26년 전과 똑같은 다정한 눈빛으로 서 있습니다. "
                    f"\"오래 걸렸네, {v['name_ya']}. 나 그사이 꽤 먼 길을 돌아왔어.\""
                )
            return _make_node(
                "b13_comp_mid_reunion",
                f"🍂 {age}세 — 26년 만에 {v['station']}에서 다시 만난 '{v['comp']}'",
                f"{bline}{greet_txt}",
                6,
                [
                    {
                        "id": "b13_old_promise",
                        "label": f"💞 \"이번엔 절대 놓치지 않을게.\" 이제라도 {v['comp_wa']} 남은 세월을 함께 걷는다",
                        "hint": "공감 +10 · 열정 +4 · [오래된 약속의 완성] 엔딩 직결",
                        "delta": {"empathy": 10, "passion": 4},
                        "set_partner": v["comp"],
                        "set_comp_rel": "reunited",
                        "add_flags": ["has_partner", "old_promise_kept"],
                        "remove_flags": ["partner_strained", "comp_missed"],
                        "log": f"수십 년의 우회 끝에 마흔넷에 {v['comp_wa']} 다시 손을 잡고 늦깎이 동반자가 되었다.",
                        "tp": f"44세: 26년의 엇갈림을 뚫고 다시 만난 {v['comp_wa']} 남은 생을 함께하기로 맹세하다.",
                        "outcome": f"\"이제 우리 둘 다 너무 늙어서 더 도망갈 데도 없겠다.\" 웃음 섞인 눈물을 닦아주는 두 손 위에, 열여덟 {v['night_spot']}의 밤바람이 따스하게 내려앉았습니다.",
                    },
                    {
                        "id": "b13_warm_tea",
                        "label": "☕ 따뜻한 차 한 잔에 지난 시절을 추억한 뒤 서로의 현재를 축복하며 배웅한다",
                        "hint": "공감 +5 · 지성 +4 · 담백하고 아름다운 중년의 우정",
                        "delta": {"empathy": 5, "intellect": 4},
                        "add_flags": ["peaceful_closure"],
                        "log": f"{v['comp_wa']} 긴 세월의 안부를 나눈 뒤 서로의 삶을 축복하며 아름답게 돌아섰다.",
                        "tp": f"44세: 오랜 빚처럼 남아있던 {v['comp_wa']}의 추억을 따뜻한 차 한 잔으로 화해시키다.",
                        "outcome": f"두 시간 넘게 웃고 울며 차가 식도록 이야기를 나눈 두 사람은 역 앞 횡단보도에서 환하게 손을 흔들었습니다. 마음에 맺혔던 오랜 매듭이 비로소 풀렸습니다.",
                    },
                ],
            )

        if "has_partner" in flags:
            if "corrupted" in flags:
                tone = (
                    f"최근 들어 서랍 깊숙이 숨겨둔 비밀 장부와 수상한 거래 흔적을 우연히 알게 된 {v['partner_i']} "
                    f"하얗게 질린 얼굴로 거실 식탁에 그것을 올려놓았고,"
                )
            elif "partner_strained" in flags:
                tone = f"일 중독으로 멀어진 채 침묵만 흐르던 {v['partner_wa']}의 거리가 어느덧 냉랭한 벽이 된 가운데,"
            else:
                tone = f"십수 년을 함께 버텨온 {v['partner_wa']}의 가정에 예상치 못한 중병과 큰 경제적 한파가 한꺼번에 들이닥쳐,"

            return _make_node(
                "b13_mid_partner",
                f"🏠 {age}세 — 마흔넷의 거센 바람, '{v['partner']}'의 눈물",
                (
                    f"{bline}마흔넷의 시린 밤. {tone} 두 사람의 지난 18년이 통째로 시험대에 올랐습니다.\n\n"
                    f"\"더는 이렇게 못 버티겠어요. 당신 옆에 내가 정말 필요한 사람 맞아요?\" {v['partner']}의 떨리는 목소리가 방 안을 가득 메웁니다."
                ),
                6,
                [
                    {
                        "id": "b13_heal_fam",
                        "label": f"💐 자존심과 욕심을 모두 내려놓고 {v['partner']} 앞에 진심으로 사과하며 손을 잡는다",
                        "hint": "공감 +9 · 근성 +3 · 관계의 완전한 치유",
                        "delta": {"empathy": 9, "grit": 3},
                        "remove_flags": ["partner_strained"],
                        "add_flags": ["family_reconciled"],
                        "log": f"{v['partner']}에게 진심을 전해 삐걱거리던 가정을 눈물 속에 다시 품어 안았다.",
                        "tp": f"44세: 무너지기 직전의 가정 앞에서 진심 어린 눈물로 {v['partner']}의 손을 되찾다.",
                        "outcome": f"서툴게 먼저 내민 두 손을 맞잡은 채 밤을 지새우고 나니, 다음 날 아침 커튼 틈으로 든 빛이 신혼 첫날처럼 맑았습니다.",
                    },
                    {
                        "id": "b13_drift",
                        "label": "📄 더는 서로에게 짐이 되지 말자며 각자의 평온을 위해 이별에 합의한다",
                        "hint": "자산 -4 · 근성 +3 · 공감 -4 · 홀로 남은 쓸쓸한 중년",
                        "delta": {"wealth": -4, "grit": 3, "empathy": -4},
                        "clear_partner": True,
                        "remove_flags": ["has_partner", "partner_committed"],
                        "log": f"{v['partner_wa']} 긴 침묵과 합의 끝에 서로의 길을 놓아주는 정중한 이별을 택했다.",
                        "tp": f"44세: 끝내 넘지 못한 세월의 골 앞에서 {v['partner_wa']} 각자의 길로 갈라서다.",
                        "outcome": f"이사 트럭이 떠난 텅 빈 거실에서 오래된 찻잔 두 개 중 하나를 치우고 나자, 마흔넷의 저녁 노을이 유난히 적막하게 기울었습니다.",
                    },
                ],
            )

        # Solo Mentor Wooden Box Beat 13
        m_rel = str(life.get("mentor_rel") or "loyal")
        if m_rel == "distant":
            letter_q = "> *\"네가 지름길을 고른 날 내 가슴이 아팠던 건 네가 미워서가 아니었다. 언젠가 멈춰 서고 싶어질 때 이 노트를 펼쳐보거라.\"*"
        elif m_rel == "rebel":
            letter_q = "> *\"내 틀을 깨고 나간 괴짜 제자야. 네가 가는 거친 길 끝에서 내 낡은 메모 몇 줄이 작은 촛불이 된다면 그걸로 족하다.\"*"
        else:
            letter_q = "> *\"끝까지 내 고집을 믿고 기본기를 지켰던 자네라면, 이제 뒤에 따라오는 외로운 아이들에게 길을 내어줄 수 있을 걸세.\"*"

        return _make_node(
            "b13_mentor_legacy",
            f"📦 {age}세 — 고향 {v['city']}에서 날아온 스승 '{v['mentor']}'의 나무 상자",
            (
                f"{bline}홀로 묵묵히 마흔넷을 건너던 어느 비 오는 저녁, {v['workplace']} 문 앞에 **{v['city']}** 소인이 찍힌 낡은 나무 상자 하나가 배달됩니다.\n\n"
                f"옛 스승 **{v['mentor']}**의 부고와 함께 도착한 상자 안에는 수십 년간 스승이 직접 손으로 눌러쓴 미완의 연구·작업 노트와 "
                f"낡은 편지 한 장이 곱게 접혀 있었습니다.\n{letter_q}"
            ),
            6,
            [
                {
                    "id": "b13_heir",
                    "label": f"🌟 {v['mentor']}의 뜻을 이어 방황하는 후배와 제자를 키우기로 결심한다",
                    "hint": "공감 +8 · 지성 +5 · [세대를 잇는 스승] 계보 확립",
                    "delta": {"empathy": 8, "intellect": 5},
                    "add_flags": ["mentor_heir", "teacher_path", "mentor_passed"],
                    "set_mentor_rel": "heir",
                    "log": f"{v['mentor']}의 유지를 받들어 젊은 후배들에게 아낌없이 배움과 자리를 나누기 시작했다.",
                    "tp": f"44세: 스승 {v['mentor']}의 마지막 상자를 안고 다음 세대를 기르는 어른이 되기로 다짐하다.",
                    "outcome": f"스승의 노트를 작업대 가장 밝은 곳에 펼쳐 둔 그 주부터, {v['workplace']} 문 앞에는 배우고자 찾아오는 젊은이들의 발걸음이 이어졌습니다.",
                },
                {
                    "id": "b13_solo_peak",
                    "label": "🔬 스승의 기록을 발판 삼아 내 개인의 생애 최고 걸작·연구에 도전한다",
                    "hint": "열정 +6 · 지성 +6 · [시대의 거장 / 미완의 걸작] 심화",
                    "delta": {"passion": 6, "intellect": 6},
                    "add_flags": ["masterwork_kept", "mentor_passed"],
                    "log": f"{v['mentor']}의 유품에서 결정적 영감을 얻어 일생일대의 작품·연구에 착수했다.",
                    "tp": f"44세: 스승의 노트를 이어받아 평생을 증명할 필생의 역작에 목숨을 걸다.",
                    "outcome": f"스승이 평생 풀지 못해 여백으로 남긴 마지막 장 앞에서, {v['name']}의 눈이 소년 시절처럼 다시 빛나기 시작했습니다.",
                },
            ],
        )

    # ── BEAT 14 (50세: 지천명 — 죄업과 심판 / 제국의 기로 / 정의의 판결 / 중년의 깊은 무늬) ──
    if beat == 14:
        if "corrupted" in flags or career == "shadow":
            confront_who = (
                f"함께 살아온 **{v['partner']}**의 침묵 어린 눈빛과 책상 위 그 증거 서류"
                if "has_partner" in flags
                else f"과거 자신이 버렸던 **양심의 기록철**을 들이민 패기 넘치는 젊은 기자"
            )
            return _make_node(
                "b14_reckoning",
                f"⚖️ {age}세 — 지천명(知天命), 숨겨왔던 과거가 문 앞까지 들이닥치다",
                (
                    f"{bline}쉰 살을 넘긴 깊은 밤, 화려한 불빛 아래 덮어 두었던 편법과 그림자의 장부들이 내부 고발과 특별 감사로 한꺼번에 수면 위로 떠오르기 시작합니다.\n\n"
                    f"책상 위에는 도망칠 차명 자금 루트가 열려 있고, 맞은편에는 {confront_who} 그리고 오래전 고향에서 챙겨온 **{v['item_short']}**{v['item_i_s']} 나란히 놓여 있습니다."
                ),
                6,
                [
                    {
                        "id": "b14_redeem",
                        "label": "🕯️ 모든 직함과 재산을 내려놓고 자진 고백·배상하며 두 번째 봄을 산다",
                        "hint": "공감 +12 · 근성 +6 · 자산 -18 · [🕯️ 회개와 두 번째 봄] 엔딩 루트",
                        "delta": {"empathy": 12, "grit": 6, "wealth": -18},
                        "add_flags": ["redeemed", "honest_path"],
                        "remove_flags": ["corrupted"],
                        "set_career": "artisan" if career == "shadow" else career,
                        "log": "쉰 살의 문턱에서 과거의 죄를 스스로 고백하고 전 재산으로 배상하며 새사람으로 거듭났다.",
                        "tp": f"50세: 쉰 살의 심판 앞에서 변명 없이 무릎 꿇고 참회하여 '두 번째 봄'을 택하다.",
                        "outcome": f"수갑과 몰수의 시간을 지나 작은 단칸방과 낡은 공방 앞치마만 남았을 때, 수십 년 만에 처음으로 마주친 거리의 아이들 앞에서 당당히 고개를 들 수 있었습니다.",
                    },
                    {
                        "id": "b14_hide",
                        "label": "🎭 더 두꺼운 돈과 비밀의 장막 뒤로 끝까지 모습을 감춘다",
                        "hint": "자산 +10 · 공감 -8 · [🎭 그림자 / 💔 부서진 왕관] 결말 확정",
                        "delta": {"wealth": 10, "empathy": -8},
                        "add_flags": ["corrupted"],
                        "log": "진실을 덮기 위해 더 큰 거짓과 돈을 쏟아부으며 누구도 믿지 못하는 어둠을 택했다.",
                        "tp": f"50세: 마지막 참회의 기회마저 걷어차고 거짓의 성벽 안으로 더 깊이 잠적하다.",
                        "outcome": f"사건은 또다시 덮였지만, 밤마다 자명종 소리가 날 때마다 수사관의 발소리 같아 커튼 틈새를 살피는 불면이 시작되었습니다.",
                    },
                ],
            )

        if career == "guardian" or "whistleblower" in flags:
            return _make_node(
                "b14_verdict",
                f"⚖️ {age}세 — 28년을 추적해 온 거악, 최후의 법정과 기록",
                (
                    f"{bline}반백이 성성해진 쉰 살의 [{v['specialty']}] {v['name']}. 젊은 날 스물둘에 처음 쥐었던 그 사건이 마침내 거대한 뿌리까지 연결되어 최후의 공개 검증대 앞에 섰습니다.\n\n"
                    f"상대 측은 노후 보장·거대 재단 자리를 내밀며 마지막 타협을 청해오고, 법정 앞에서는 30년을 기다린 피해자 유족들이 {v['name']}의 입만 바라보고 있습니다."
                ),
                6,
                [
                    {
                        "id": "b14_truth_final",
                        "label": "⚖️ 마지막 한 줄까지 타협 없이 전부 공개해 시대의 상식을 세운다",
                        "hint": "공감 +9 · 지성 +5 · [⚖️ 진실을 남긴 이름] 핵심 조건",
                        "delta": {"empathy": 9, "intellect": 5},
                        "add_flags": ["honest_path", "whistleblower"],
                        "log": "쉰 살의 최후 법정에서 모든 압력을 뚫고 시대의 진실을 끝내 세상에 남겼다.",
                        "tp": f"50세: 반생의 집념 끝에 거대한 진실을 세상에 공개하고 약자들의 한을 풀다.",
                        "outcome": f"판결문이 낭독되던 오후, 수십 년간 가슴을 누르던 돌덩이가 녹아내리며 법원 계단 밖에서 수많은 시민들이 {v['name']}의 이름을 연호했습니다.",
                    },
                    {
                        "id": "b14_teach_law",
                        "label": "🌟 사건 마무리를 후배들에게 물려주고 정의를 기록하는 교육자로 돌아선다",
                        "hint": "공감 +8 · 지성 +5 · [🌟 세대를 잇는 스승] 계보",
                        "delta": {"empathy": 8, "intellect": 5},
                        "add_flags": ["teacher_path", "honest_path"],
                        "log": "현장의 바통을 젊은 후배들에게 물려주고 기록과 교육의 길에 섰다.",
                        "outcome": f"스무 살 무렵 {v['mentor']}에게서 받았던 노트를 이제 젊은 기자와 조사관들에게 건네며 진실의 불씨를 이어 주었습니다.",
                    },
                ],
            )

        if int(stats.get("wealth", 0) or 0) >= 60 or career == "entrepreneur":
            return _make_node(
                "b14_empire_choice",
                f"🏛️ {age}세 — 손에 쥔 큰 부와 영향력, 어디에 쓸 것인가",
                (
                    f"{bline}열아홉 살 맨손으로 {v['city']}의 **{v['origin_place']}**{p_eul(v['origin_place'])} 떠났던 {v['name_eun']} 어느새 업계에서 이름만 대면 모두가 아는 큰 부와 자리를 거머쥐었습니다.\n\n"
                    f"지천명의 문턱에 선 오늘 밤, 두꺼운 자산 보고서를 덮은 {v['name_eun']} 이 거대한 힘을 어디로 흘려보낼지 결정해야 합니다."
                ),
                6,
                [
                    {
                        "id": "b14_share",
                        "label": f"🕊️ {v['city']} 고향과 어려운 후배들을 위해 장학재단·무료 공방을 열어 환원한다",
                        "hint": "공감 +10 · 자산 -6 · [🕊️ 작은 마을의 등불] 존경받는 어른",
                        "delta": {"empathy": 10, "wealth": -6},
                        "add_flags": ["philanthropy", "protect_local"],
                        "log": f"모아온 재산 상당 부분을 고향 {v['city']}의 가난한 청춘과 이웃들에게 환원했다.",
                        "tp": f"50세: 내 손에 쥔 부를 쌓아두는 대신 고향과 젊은이들을 살리는 등불로 내어놓다.",
                        "outcome": f"어린 시절 자신이 뛰놀던 {v['hangout']} 인근에 무료 공부방과 국수 쉼터 간판이 걸리던 날, {v['name_eun']} 어떤 계약 성사 때보다 크게 울었습니다.",
                    },
                    {
                        "id": "b14_expand",
                        "label": "👑 쉰의 나이에도 안주하지 않고 더 거대한 제국과 업계의 정상을 향해 질주한다",
                        "hint": "자산 +12 · 열정 +5 · 공감 -4 · [👑 제국의 설계자] 직행",
                        "delta": {"wealth": 12, "passion": 5, "empathy": -4},
                        "add_flags": ["empire_ambition"],
                        "log": "쉰 살의 나이에도 멈추지 않고 더욱 거대한 사업 제국을 완성해 나갔다.",
                        "tp": f"50세: 은퇴 대신 시대의 스카이라인을 바꾸는 거대한 제국 확장을 선택하다.",
                        "outcome": f"마천루 꼭대기 유리창 너머로 도시의 불빛을 내려다보는 자리까지 올랐지만, 불빛 아래 홀로 남는 밤은 더욱 깊어졌습니다.",
                    },
                    {
                        "id": "b14_explore",
                        "label": "🧭 경영권을 믿을 후배들에게 넘기고 평생 미뤄둔 세계 여행길에 오른다",
                        "hint": "열정 +8 · 지성 +5 · [🧭 끝없는 지평선의 기록자] 늦깎이 모험",
                        "delta": {"passion": 8, "intellect": 5},
                        "add_flags": ["late_explorer"],
                        "log": "화려한 대표 직함을 내려놓고 뒤늦은 배낭을 꾸려 넓은 세상으로 떠났다.",
                        "tp": f"50세: 거머쥔 직함과 성을 내려놓고 자유로운 바람 속으로 늦은 여행을 떠나다.",
                        "outcome": f"사내 송별회 다음 날 아침, 정장을 모두 정리하고 새 운동화를 신은 채 공항으로 향하는 발걸음이 스무 살처럼 가벼웠습니다.",
                    },
                ],
            )

        return _make_node(
            "b14_midlife_depth",
            f"🌿 {age}세 — 쉰 살의 오후, 내 인생의 진짜 무늬가 보이다",
            (
                f"{bline}인생의 반환점을 돌아온 쉰 살의 [{v['specialty']}] {v['name']}. "
                f"거대한 부나 권력은 손에 쥐지 않았을지라도, 지난 반세기 동안 **{v['workplace']}**에서 견디고 깎아온 세월이 주름과 손마디마다 깊게 새겨져 있습니다.\n\n"
                f"창밖으로 기울어가는 햇살 아래 **{v['work_obj']}**{v['work_obj_eul_s']} 매만지며, 남은 삶의 황금기를 어디에 쏟을지 마음속 저울을 들어 봅니다."
            ),
            6,
            [
                {
                    "id": "b14_teach",
                    "label": "🌟 방황하는 젊은 후배들에게 내가 평생 겪은 기술과 시행착오를 전부 알려준다",
                    "hint": "공감 +9 · 지성 +4 · [🌟 세대를 잇는 스승] 계보",
                    "delta": {"empathy": 9, "intellect": 4},
                    "add_flags": ["teacher_path"],
                    "log": "자신이 겪었던 숱한 실패를 거름 삼아 후배들을 길러내는 스승이 되었다.",
                    "tp": f"50세: 내 이름 하나를 더 세우기보다 젊은이들의 발판이 되는 스승의 길을 택하다.",
                    "outcome": f"작은 작업대 옆자리를 내주자 어리숙하지만 눈빛만은 반짝이는 제자들이 하나둘 모여들며 {v['workplace']}에 봄바람이 불었습니다.",
                },
                {
                    "id": "b14_craft_deep",
                    "label": "🏆 남들이 쉴 나이에 오히려 평생을 증명할 필생의 역작에 목숨을 건다",
                    "hint": "열정 +7 · 지성 +5 · [🏆 시대의 거장 / 📜 미완의 걸작] 정점",
                    "delta": {"passion": 7, "intellect": 5},
                    "add_flags": ["masterwork_kept"],
                    "log": "세월의 무게를 핑계 대지 않고 생애 가장 깊이 있는 작업에 몰입했다.",
                    "tp": f"50세: 쉰 살의 문턱에서 생애 모든 세월을 집약한 마지막 필생작에 돌입하다.",
                    "outcome": f"젊은 시절의 패기 대신 세월에서 우러난 묵직함이 손끝에 실리며, 지금껏 한 번도 닿지 못했던 경지가 보이기 시작했습니다.",
                },
                {
                    "id": "b14_star",
                    "label": "🌌 저녁마다 작은 망원경과 노트를 펴고 별빛과 인간의 시간이 잇는 뜻을 적는다",
                    "hint": "지성 +8 · 공감 +5 · 내면의 완성 ([🌌 별을 건너다] 핵심 씨앗)",
                    "delta": {"intellect": 8, "empathy": 5},
                    "add_flags": ["star_seed"],
                    "log": "삶의 속도를 늦추고 밤하늘 별빛과 인간의 시간이 만나는 깊은 사색을 남겼다.",
                    "tp": f"50세: 성취의 속도를 늦추고 밤하늘과 {v['item_short']} 너머 시간의 의미를 깨닫다.",
                    "outcome": f"여섯 살 다락 창고에서 보았던 별빛과 쉰 살 밤의 은하수가 한 줄기 빛으로 이어지던 날, 두려움 없는 고요가 가슴을 채웠습니다.",
                },
            ],
        )

    # ── BEAT 15 (56세: 세대 교체 + {mentor} 마지막 에코) ──
    if beat == 15:
        if "mentor_passed" in flags:
            mentor_echo = f" 문득 십여 해 전 스승 **{v['mentor']}**{v['mentor_i_s']} 남긴 낡은 나무 상자가 작업대 한편에서 조용히 빛납니다."
        elif "mentor_heir" in flags or life.get("mentor_rel") == "heir":
            mentor_echo = ""
        else:
            mentor_echo = f" 마침 이번 주 고향 {v['city']}에서 들려온 소식에 따르면, 옛 스승 **{v['mentor']}**도 고령으로 자리에서 물러나 조용히 제자들을 기억하고 계신다고 합니다."
        return _make_node(
            "b15_generation",
            f"🌅 {age}세 — 쉰여섯, 스무 살의 나를 꼭 닮은 손님이 문을 두드리다",
            (
                f"{bline}머리카락에 흰 서리가 내려앉은 쉰여섯의 황혼. 빗소리 잔잔한 저녁에 **{v['workplace']}** 문을 조심스럽게 두드리는 이가 있습니다.\n\n"
                f"비에 젖은 낡은 신발을 신은 스무 살 남짓한 후배 — 눈빛 속 간절함과 두려움이 꼭 서른일곱 해 전 {v['city_eul']} 떠나던 {v['name']} 자신과 소름 끼치도록 닮아 있습니다.{mentor_echo}"
            ),
            7,
            [
                {
                    "id": "b15_pass_torch",
                    "label": f"🤝 {v['mentor']}에게 배웠던 것처럼, 내 비법과 자리를 아낌없이 열어 물려준다",
                    "hint": "공감 +8 · 근성 +3 · 세대를 잇는 든든한 버팀목",
                    "delta": {"empathy": 8, "grit": 3},
                    "add_flags": ["teacher_path"],
                    "log": "과거의 나처럼 방황하는 젊은이에게 스승처럼 묵묵히 길을 내어주는 어른이 되었다.",
                    "tp": f"56세: 젊은 날의 나를 닮은 후배에게 아낌없이 문을 열어 세대를 잇다.",
                    "outcome": f"젖은 어깨에 수건을 덮어주고 작업대 앞자리를 내어주며 건넨 첫 한마디에, 젊은 후배는 참았던 울음을 터뜨리고 말았습니다.",
                },
                {
                    "id": "b15_protect_own",
                    "label": "🛡️ 아직 내가 마저 끝낼 일이 남았다며 끝까지 최전선 현역 자리를 지킨다",
                    "hint": "열정 +6 · 자산 +5 · 꺾이지 않는 현역의 자부심",
                    "delta": {"passion": 6, "wealth": 5},
                    "log": "나이에 굴하지 않고 쉰여섯에도 최전선 현장에서 누구보다 치열하게 현역을 지켰다.",
                    "outcome": f"후배에게 조언 몇 마디와 여비만 쥐여 보낸 뒤, {v['name_eun']} 다시 {v['tool_eul']} 고쳐 쥐며 마지막 불꽃 같은 현역을 이어갔습니다.",
                },
                {
                    "id": "b15_heal_body",
                    "label": "🌿 이제는 무리했던 몸을 추스르고 가까운 사람들과의 시간을 조용히 늘려간다",
                    "hint": "근성 +9 · 공감 +4 · 평온한 노년을 향한 건강 회복",
                    "delta": {"grit": 9, "empathy": 4},
                    "log": "고장 나던 몸을 돌보며 소중한 사람들의 이름을 한 번 더 불러주는 시간을 택했다.",
                    "outcome": f"규칙적인 산책과 따뜻한 저녁 밥상 속에서 닳아 있던 몸과 마음이 서서히 제 온기를 되찾아 갔습니다.",
                },
            ],
        )


# ==========================================
# 10. BEAT 16~18 : 노년기 (63세 · 70세 · 78세)
# ==========================================
def _build_elder_node(beat: int, life: Dict[str, Any], v: Dict[str, Any]) -> Dict[str, Any]:
    age = v["age"]
    career = v["career"]
    flags = set(life.get("flags") or [])
    stats = life.get("stats") or {}
    bridge = _prev_bridge(life, v)
    bline = f"{bridge}\n\n" if bridge else ""

    # ── BEAT 16 (63세: 은퇴의 아침) ──
    if beat == 16:
        partner_scene = (
            f"식탁 맞은편에 앉은 **{v['partner']}**의 흰머리 위로 따스한 아침 햇살이 내려앉는 가운데, "
            if "has_partner" in flags
            else f"창가 화분에 맺힌 이슬을 닦아내며 고요히 끓인 찻잔을 든 가운데, "
        )
        retire_action = {
            "artist": f"평생을 부둥켜안고 싸워온 {v['tool_eul']} 깨끗이 닦아 천에 감싸 두고,",
            "scholar": f"수십 년 치 연구 파일과 관측 노트를 서가에 가지런히 꽂아 넣으며,",
            "entrepreneur": f"회사 현관에 마지막으로 들러 젊은 후배들의 어깨를 두드려 주고 명함을 반납하며,",
            "artisan": f"수십 년간 손님을 맞아 온 {v['workplace']} 앞치마와 간판에 묻은 먼지를 천천히 털어내며,",
            "guardian": f"수만 페이지의 기록과 낡은 사원증을 작은 상자 속에 정중히 내려놓으며,",
            "wanderer": f"지구 반 바퀴를 함께 걸은 해진 배낭과 여권들을 책상 위에 펼쳐 두고,",
            "shadow": f"가짜 신분증과 암호 장부들을 난로 불꽃 속으로 하나씩 던져 재로 지워내며,",
        }.get(career, f"오랜 세월 붙잡아 온 {v['tool_eul']} 내려놓으며,")

        return _make_node(
            "b16_retire",
            f"🍁 {age}세 — 예순셋의 아침, 손에서 내려놓은 세월의 이름표",
            (
                f"{bline}{partner_scene}서른 해가 넘도록 치열하게 살아온 **[{v['specialty']}]**의 자리가 이제 서서히 뒷모습으로 물러날 때가 왔습니다.\n\n"
                f"{v['name_eun']} {retire_action} 텅 비어가는 오후의 여백을 어떤 마지막 색으로 채울지 가만히 미소 짓습니다."
            ),
            7,
            [
                {
                    "id": "b16_community",
                    "label": "🕊️ 거창한 이름 대신 동네 도서관·골목 쉼터·무료 나눔 자리로 이웃 곁에 남는다",
                    "hint": "공감 +8 · 근성 +4 · [🕊️ 마을의 등불 / 🍜 국수 우주] 따뜻한 노년",
                    "delta": {"empathy": 8, "grit": 4},
                    "add_flags": ["protect_local"],
                    "log": "은퇴 후에도 작지만 동네 이웃들이 마음 편히 들르는 따뜻한 쉼터의 등불이 되었다.",
                    "tp": f"63세: 현역에서 물러난 뒤 이웃들의 곁을 밝히는 동네의 작은 쉼터를 열다.",
                    "outcome": f"큰돈이 오가는 자리는 아니었지만, 방과 후 아이들과 늙은 이웃들이 편히 차 한 잔 마시고 가는 소란스러움이 황혼기를 넉넉히 채워주었습니다.",
                },
                {
                    "id": "b16_memoir",
                    "label": "📜 평생 부딪히며 깨달은 진실과 실패의 기록을 한 권의 회고록·유작으로 남긴다",
                    "hint": "지성 +7 · 열정 +5 · [🏆 거장 / 📜 미완의 걸작 / ⚖️ 진실] 기록 완성",
                    "delta": {"intellect": 7, "passion": 5},
                    "add_flags": ["memoir_written"],
                    "log": "평생 겪은 기쁨과 실패를 가감 없이 한 권의 기록과 유작에 담아 세상에 남겼다.",
                    "tp": f"63세: 살아온 백 년 가까운 진실을 꾸밈없이 담은 회고록을 남기기 시작하다.",
                    "outcome": f"잘난 척도 후회도 꾸미지 않은 담백한 문장들 위에, 잊혔던 이름들과 젊은 날의 땀방울이 하나씩 선명하게 되살아났습니다.",
                },
                {
                    "id": "b16_journey",
                    "label": "🧭 평생 가보려다 미뤄두기만 했던 먼 바다와 산을 향해 늦은 배낭여행을 떠난다",
                    "hint": "열정 +7 · 근성 +3 · [🧭 끝없는 지평선의 기록자] 자유로운 황혼",
                    "delta": {"passion": 7, "grit": 3},
                    "add_flags": ["late_explorer"],
                    "log": "미뤄왔던 여행 가방을 꾸려 예순셋의 늦가을, 아직 보지 못한 먼 세상으로 떠났다.",
                    "tp": f"63세: 모든 짐을 내려놓고 아직 밟지 못한 지평선을 향해 늦깎이 여행을 떠나다.",
                    "outcome": f"느린 완행열차 창밖으로 스치는 낯선 바다와 들판 앞에서 {v['name_eun']} 비로소 세월이라는 무게를 벗고 스무 살처럼 웃었습니다.",
                },
            ],
        )

    # ── BEAT 17 (70세: 고향 {city}의 {origin_place} 귀향 — 전 생애 떡밥 완벽 회수) ──
    if beat == 17:
        intel = int(stats.get("intellect", 0) or 0)
        empathy = int(stats.get("empathy", 0) or 0)
        has_star = ("star_seed" in flags) and intel >= 50 and empathy >= 46

        tps = v.get("turning_points") or []
        recall_list = tps[:2] + (tps[-1:] if len(tps) > 2 else [])
        tp_recall_txt = (
            "\n\n눈을 감자 주마등처럼 지나가는 이름과 장면들 —\n" + "\n".join(f"> • *{t}*" for t in recall_list)
            if recall_list
            else ""
        )

        star_tease = (
            "\n\n별빛 아래 **{item_short}**{item_i_s} 이상하리만치 투명하게 반짝이며, 평생 묻고 또 물었던 시간의 비밀이 코앞에 다가온 듯 숨이 멎을 것 같습니다.".format(**v)
            if has_star
            else (
                "\n\n밤하늘 별빛을 올려다보며 평생 간직한 호기심이 아련히 맴돌지만, 문득 조금 다른 길로 걸어왔더라면 저 별 너머의 답까지 닿았을까 미소 짓습니다."
                if "star_seed" in flags
                else ""
            )
        )

        choices = [
            {
                "id": "b17_forgive",
                "label": f"💧 주머니 속 오래된 {v['item_eul']} 가슴에 안고 지나온 모든 나와 화해한다",
                "hint": "공감 +8 · 지성 +4 · 상처마저 껴안는 온전한 삶의 화해",
                "delta": {"empathy": 8, "intellect": 4},
                "add_flags": ["reconciled_self"],
                "log": f"칠십이 넘어 처음 출발했던 {v['city']} {v['origin_place']} 앞에서 젊은 날의 자신을 안아주었다.",
                "tp": f"70세: {v['city']}의 바람 앞에서 상처투성이였던 젊은 날의 나를 용서하고 화해하다.",
                "outcome": f"그때 그렇게 서툴고 모자랄 수밖에 없었던 여섯 살과 서른 살의 나를 떠올리며, 늙은 두 손으로 조용히 자기 어깨를 토닥여 주었습니다.",
            },
            {
                "id": "b17_smile",
                "label": "🏡 세월이 바꿔놓은 풍경 속에서 아프고 눈부셨던 모든 날에 진심으로 감사한다",
                "hint": "근성 +6 · 공감 +6 · 후회 없는 백 년의 평온",
                "delta": {"grit": 6, "empathy": 6},
                "add_flags": ["grateful_elder"],
                "log": "아프고 어긋났던 날들까지 지금의 나를 만든 선물이었다며 환하게 미소 지었다.",
                "outcome": f"옛 {v['hangout']} 자리에 들어선 작은 나무 벤치에 앉아 아이들이 뛰어노는 모습을 바라보며, 이 세상이 여전히 따뜻하다고 믿게 되었습니다.",
            },
        ]
        if has_star:
            choices.append({
                "id": "b17_cosmos",
                "label": "🌌 쏟아지는 밤하늘 별빛 속에서 시간과 세월이 하나로 이어지는 깊은 깨달음을 얻는다",
                "hint": "지성 +8 · 공감 +8 · [🌌 히든 엔딩: 별을 건너다] 해금 조건!",
                "delta": {"intellect": 8, "empathy": 8},
                "add_flags": ["time_transcended"],
                "log": "칠십의 은하수 아래서 시간은 흐르는 것이 아니라 마음속 빛으로 겹쳐지는 것임을 깨달았다.",
                "tp": f"70세: {v['city']} 밤하늘 아래서 시간의 경계를 건너는 경이로운 깨달음을 얻다.",
                "outcome": f"64년 전 {v['origin_place']}에서 올려다보았던 그 별빛이 지금 내 눈동자 안에 고스란히 살아 숨 쉬고 있음을 깨달은 밤, 세상의 모든 슬픔이 빛으로 바뀌었습니다.",
            })

        return _make_node(
            "b17_homecoming",
            f"🏡 {age}세 — 64년 만에 돌아온 고향 {v['city']}, 그날의 {v['origin_place']}",
            (
                f"{bline}칠순을 넘긴 {v['name']}의 느린 발걸음이 자신도 모르게 인생의 첫 장면이 열렸던 **{v['city']}**, **{v['origin_place']}** 터 앞에 멈춰 섭니다.\n\n"
                f"옛 건물은 높은 아파트와 새 간판으로 바뀌었지만, 골목을 스치는 **{v['sensory']}**만은 육십사 해 전 여섯 살 그날 그대로입니다. "
                f"외투 주머니 깊숙이 간직해 온 낡은 **{v['item_short']}**{v['item_i_s']} 주름진 손끝에 닿습니다.{tp_recall_txt}{star_tease}"
            ),
            8,
            choices,
        )

    # ── BEAT 18 (78세+: 인생이라는 책의 마지막 페이지) ──
    last_partner_msg = (
        f"침대 곁에서 조용히 손을 잡아주는 **{v['partner']}**의 주름진 온기를 느끼며, "
        if "has_partner" in flags
        else f"평생 걸어온 길 위에서 스쳐 간 **{v['comp']}**, **{v['mentor']}**, 그리고 이름 모를 수많은 얼굴들을 떠올리며, "
    )
    choices_18 = [
        {
            "id": "b18_peace",
            "label": "🌅 사랑하고 미워했던 모든 이들의 이름을 불러본 뒤 고요히 눈을 감는다",
            "hint": "인생의 다정하고 온전한 마침표",
            "delta": {"empathy": 4, "grit": 2},
            "add_flags": ["peaceful_end"],
            "log": "지나온 인연과 세월에게 마지막 감사를 건넨 뒤 평온히 눈을 감았다.",
            "outcome": f"창밖으로 붉은 노을빛이 천천히 사그라지던 저녁, 평생 손에 쥐었던 {v['item_eul']} 가슴 위에 올려둔 채 가장 고요한 미소로 마지막 숨을 내쉬었습니다.",
        },
        {
            "id": "b18_final_work",
            "label": "✍️ 마지막 기운까지 모아 세상에 남길 한 줄의 기록·작품에 마침표를 찍는다",
            "hint": "열정 +5 · 지성 +3 · 끝까지 빛난 혼신의 마무리 ([📜 미완의 걸작/🏆 거장])",
            "delta": {"passion": 5, "intellect": 3},
            "add_flags": ["final_work_done"],
            "log": "숨이 닿는 마지막 순간까지 평생 사랑한 일의 마침표를 스스로 찍었다.",
            "outcome": f"떨리는 손으로 마지막 문장과 손길을 남기고 책상 위에 고개를 기대었을 때, 창문 너머로 {v['city']}의 첫 새벽종 소리가 은은히 울려 퍼졌습니다.",
        },
    ]
    if "time_transcended" in flags:
        choices_18.append({
            "id": "b18_star_walk",
            "label": "🌌 은하수가 창가를 비추는 새벽, 시간의 저편으로 조용히 걸어 나간다",
            "hint": "[🌌 히든 엔딩: 별을 건너다] 전용 최종 선택",
            "delta": {"intellect": 4, "empathy": 4},
            "add_flags": ["cosmos_finale"],
            "log": "별빛이 방 안을 채운 새벽, 세월의 경계를 조용히 건너 영원한 이야기가 되었다.",
            "outcome": f"은하수의 잔광 속에서 여섯 살의 {v['name_wa']} 칠십여 세의 {v['name_i']} 마주 보고 웃던 그 순간, 한 사람의 삶은 우주의 오래된 시가 되었습니다.",
        })
    return _make_node(
        "b18_finale",
        f"📖 {age}세 — 인생이라는 두꺼운 책의 마지막 페이지",
        (
            f"{bline}길고도 찰나 같았던 한 사람의 세월. {v['city']}의 **{v['origin_place']}**에서 시작해 **[{v['specialty']}]**{v['specialty_ro_s']} 살아낸 삶이 이제 마지막 장 앞에 놓여 있습니다.\n\n"
            f"{last_partner_msg}{v['name_eun']} 창밖을 물들이는 따스한 노을을 바라봅니다. "
            f"서툴렀던 실수도, 눈물 젖은 회한도, 남몰래 건넸던 다정도 모두 한 권의 빛나는 책이 되어 마지막 문장을 기다리고 있습니다."
        ),
        0,
        choices_18,
    )


def build_story_node(life: Dict[str, Any]) -> Dict[str, Any]:
    beat = max(1, min(18, int(life.get("beat") or 1)))
    v = fmt_life_vars(life)
    if beat <= 3:
        return _build_childhood_node(beat, life, v)
    if beat <= 6:
        return _build_teen_node(beat, life, v)
    if beat <= 11:
        return _build_youth_node(beat, life, v)
    if beat <= 15:
        return _build_midlife_node(beat, life, v)
    return _build_elder_node(beat, life, v)


# ==========================================
# 11. 다채로운 상황 맞춤형 일상 일기장 (세월 숙성 + 조용한 1년)
# ==========================================
def build_idle_diary_line(life: Dict[str, Any], age_at_year: int) -> Tuple[str, Dict[str, int]]:
    v = fmt_life_vars(life)
    flags = set(life.get("flags") or [])
    career = v["career"]
    sid = v["specialty_id"]
    delta: Dict[str, int] = {}

    if age_at_year < 14:
        lines = [
            f"{v['city']}의 {v['hangout']} 근처에서 사계절이 바뀌는 풍경을 눈에 담았다.",
            f"주머니 속 {v['item_eul']} 만지작거리며 서툴지만 단단하게 한 뼘 더 자랐다.",
            f"{v['origin_place']}의 낡은 골목 끝을 돌며 동네 사람들의 삶과 냄새를 배웠다.",
        ]
        if "comp_close" in flags:
            lines.append(f"{v['comp_wa']} 하굣길 떡볶이 컵을 나눠 들며 비밀 지도를 그렸다.")
        elif "comp_rival" in flags:
            lines.append(f"{v['comp_wa']} 줄넘기와 달리기 기록을 두고 하루 종일 투닥거렸다.")
        delta = {"grit": 1, "empathy": 1}
    elif age_at_year < 19:
        lines = [
            f"밤늦도록 스탠드 불빛 아래서 {v['city']} 너머에 펼쳐질 스무 살의 내일을 그렸다.",
            f"{v['mentor_place']}로 오가는 길목에서 스승 {v['mentor']}의 말씀을 공책에 옮겨 적었다.",
            f"사춘기의 흔들리는 밤마다 {v['item_eul']} 책상 위에 두고 조용히 마음을 다잡았다.",
        ]
        if "shortcut_tempted" in flags:
            lines.append("빠른 요령으로 얻은 성과 뒤에서 왠지 모를 씁쓸한 공허함을 삼켰다.")
        delta = {"intellect": 1, "passion": 1}
    else:
        spec_lines = {
            "artist_paint": [
                f"{v['workplace']}에서 동이 틀 때까지 붓을 씻고 색의 온도를 시험했다.",
                "아무도 찾지 않는 갤러리 모퉁이에서 묵묵히 스케치북 다섯 권을 채웠다.",
            ],
            "artist_music": [
                f"{v['workplace']}에서 지판이 패이도록 기타를 뜯으며 새벽 멜로디를 흥얼거렸다.",
                "비 오는 날 창문을 열어두고 빗소리에 맞춰 오래된 악보를 고쳐 썼다.",
            ],
            "artist_write": [
                f"{v['workplace']}에서 잉크가 마를 때마다 원고지 수백 장을 찢고 다시 썼다.",
                "지하철 창밖 사람들의 표정을 작은 수첩에 문장으로 옮기며 하루를 채웠다.",
            ],
            "scholar_healer": [
                f"{v['workplace']}의 밤샘 당직 속에서 아픈 이들의 호흡과 차트를 꼼꼼히 챙겼다.",
                "시골 노인들이 쥐여준 귤 몇 개에 힘을 얻어 낡은 의학 저널을 밤새 읽었다.",
            ],
            "scholar_cosmos": [
                f"{v['workplace']}에서 차가운 밤공기를 마시며 망원경 시계열 오차를 계산했다.",
                "수십 년 전 스승이 남긴 여백 메모 옆에 작은 가설 한 줄을 보탰다.",
            ],
            "scholar_archive": [
                f"{v['workplace']}의 먼지 낀 사료 상자를 풀며 잊혀진 이름들을 다시 기록했다.",
                "오래된 신문 마이크로필름을 돌리다가 반세기 전 진실의 꼬리를 밟았다.",
            ],
            "ent_food": [
                f"{v['workplace']}에서 산지 농가와 거래처를 오가며 원가와 맛의 균형을 잡았다.",
                "매장 재고가 남는 날이면 동네 보육원과 쉼터에 조용히 박스를 보냈다.",
            ],
            "ent_tech": [
                f"{v['workplace']}에서 납땜 연기를 마시며 고장 난 시제품을 백 번째 다시 조립했다.",
                "까다로운 투자사 앞에서 밤새 만든 설계 도면으로 신뢰를 얻어냈다.",
            ],
            "ent_trade": [
                f"{v['workplace']} 창밖으로 부두 크레인이 움직이는 새벽마다 선적 장부를 점검했다.",
                "거친 무역 협상 테이블에서도 계약의 선만은 끝내 지키는 방식으로 거래를 넓혔다.",
            ],
            "artn_noodle": [
                f"{v['workplace']}에서 새벽 네 시마다 멸치 내장을 따고 진한 육수 불을 조절했다.",
                "단골 학생과 야근 직장인들이 국수 한 그릇 비우고 웃을 때마다 손끝에 힘이 돌았다.",
            ],
            "artn_clock": [
                f"{v['workplace']}에서 황동 루페를 눈에 끼고 0.1밀리미터 톱니 하나를 밤새 다듬었다.",
                "할아버지 유품 시계를 들고 온 손님의 사연을 들으며 묵묵히 태엽을 되살렸다.",
            ],
            "artn_tea": [
                f"{v['workplace']}의 무쇠 솥 앞에서 손바닥이 데도록 어린 찻잎을 덖어냈다.",
                "장마철 곰팡이 하나 피지 않게 항아리 덮개를 하루 세 번씩 살폈다.",
            ],
            "artn_craft": [
                f"{v['workplace']}에서 반죽과 가죽 결을 만지며 정직한 땀방울의 하루를 쌓았다.",
                "이윤이 적더라도 부끄러운 재료는 쓰지 않는다는 소신으로 단골을 지켰다.",
            ],
            "grd_press": [
                f"{v['workplace']}에서 밤새 녹취록을 돌려 들으며 팩트 하나라도 틀리지 않으려 검수했다.",
                "협박 전화가 울린 밤에도 취재 수첩 첫 장의 다짐을 읽으며 마음을 고쳐먹었다.",
            ],
            "grd_detective": [
                f"{v['workplace']}의 낡은 미제 사건 캐비닛을 훑으며 사라진 목격자의 행방을 쫓았다.",
                "잠복 근무 새벽, 차가운 편의점 커피로 졸음을 쫓으며 골목을 지켰다.",
            ],
            "grd_advocate": [
                f"{v['workplace']}에서 억울한 산재 피해자의 탄원서 한 줄을 밤새워 다듬었다.",
                "수임료 대신 건네받은 직접 기른 채소 바구니에 목이 메는 저녁을 보냈다.",
            ],
            "wnd_photo": [
                "낯선 항구와 기차역 벤치에서 스쳐 간 사람들의 웃음과 눈물을 필름에 담았다.",
                "신발 밑창이 닳도록 걸으며 지도에도 잘 나오지 않는 작은 마을의 이름을 적었다.",
            ],
            "wnd_relief": [
                "먼지바람 부는 천막 진료소에서 밤새 열이 오르는 아이의 이마를 닦아 주었다.",
                "물자가 끊긴 고립 지역에서 주민들과 함께 임시 우물을 파며 하루를 버텼다.",
            ],
            "shd_broker": [
                f"{v['workplace']}에서 암호화된 호출을 정리하며 누구에게도 진짜 표정을 보이지 않았다.",
                "돈은 무섭게 불어났지만 문밖 사람들의 웃음소리가 멀고 낯설게만 들렸다.",
            ],
            "shd_launder": [
                f"{v['workplace']} 지하실 파쇄기 소리 속에서 검은 장부의 숫자를 매끄럽게 세탁했다.",
                "두꺼운 차명 통장 위로 쌓이는 숫자만큼이나 잠 못 드는 새벽이 길어졌다.",
            ],
        }
        lines = list(spec_lines.get(sid, [f"{v['workplace']}에서 묵묵히 하루의 몫을 다하며 계절을 건넜다."]))
        if "corrupted" in flags:
            lines.append("화려한 통장 뒤편으로 과거의 타협이 언제 들통날지 몰라 밤마다 뒤를 돌아보았다.")
        if "redeemed" in flags:
            lines.append("과거를 속죄하듯 소박한 하루를 살며 작은 봉사로 마음의 빛을 갚아 나갔다.")
        if "overworked" in flags:
            lines.append("잠을 아껴 일에만 매달리다 문득 가슴을 짚으며 가쁜 숨을 고르곤 했다.")
        if "star_seed" in flags:
            lines.append("고단한 일과 끝에도 밤하늘 별자리를 올려다보며 작은 수첩에 사색을 남겼다.")
        if "has_partner" in flags or life.get("partner_name"):
            if "partner_strained" in flags:
                lines.append(f"{v['partner_wa']} 한 지붕 아래 살면서도 대화 한마디 없이 잠드는 밤이 잦았다.")
            else:
                lines.append(f"{v['partner_wa']} 나눈 소박한 저녁 밥상 덕분에 고단한 한 해를 버텨낼 힘을 얻었다.")

        if career == "artist":
            delta = {"passion": 2, "empathy": 1}
        elif career == "scholar":
            delta = {"intellect": 2, "grit": 1}
        elif career == "entrepreneur":
            delta = {"wealth": 2, "passion": 1}
        elif career == "artisan":
            delta = {"grit": 2, "wealth": 1}
        elif career == "guardian":
            delta = {"empathy": 2, "grit": 1}
        elif career == "wanderer":
            delta = {"passion": 1, "intellect": 1, "empathy": 1}
        elif career == "shadow":
            delta = {"wealth": 2, "intellect": 1}
        else:
            delta = {"grit": 1}

    return random.choice(lines), delta


# ==========================================
# 12. 16종 맞춤형 다문단 엔딩 전기 생성기
# ==========================================
def build_rich_ending_epilogue(life: Dict[str, Any], eid: str, emeta: Dict[str, Any], v: Dict[str, Any]) -> str:
    flags = set(life.get("flags") or [])
    stats = life.get("stats") or {}
    empathy = int(stats.get("empathy", 0) or 0)
    age = v["age"]
    tps = v.get("turning_points") or []

    # 맞춤형 엔딩 핵심 단락들
    if eid == "hidden_star":
        core = (
            f"{age}세의 맑은 새벽, {v['name_eun']} 창밖으로 쏟아지는 은하수를 올려다보며 여섯 살 **{v['origin_place']}** 다락에서 품었던 첫 질문을 떠올렸습니다.\n\n"
            f"[{v['specialty']}]로서 평생 쌓은 통찰과 사람에 대한 따뜻한 연민은 세월의 벽을 건너 후대의 기록 속에 별빛처럼 남았습니다. "
            f"{v['item_eul']} 품에 안고 눈을 감은 밤, 한 사람의 생애는 시간이 흘러도 꺼지지 않는 별자리가 되어 수많은 이의 밤길을 밝혀주었습니다."
        )
    elif eid == "flame_39":
        core = (
            f"서른아홉, 가장 치열하게 불타오르던 한여름 혹은 한겨울의 밤에 멈춰 선 시계. "
            f"[{v['specialty']}]의 현장이 화염과 붕괴로 무너지던 그 절체절명의 순간, {v['name_eun']} 제 목숨 대신 안에 갇힌 생명과 가치를 먼저 품어 안았습니다.\n\n"
            f"비록 {v['city']}의 고향 땅으로 돌아갈 노년은 허락되지 않았으나, "
            f"그가 온몸을 내던져 살려낸 이들의 맥박과 기억 속에서 서른아홉의 이름은 결코 식지 않는 불꽃이 되어 영원히 타오릅니다."
        )
    elif eid == "old_promise":
        core = (
            f"아홉 살 **{v['hangout']}**에서 처음 마주 잡고, 열여덟 **{v['night_spot']}**에서 밤바람을 맞으며 걸었던 약속.\n\n"
            f"서툴고 아픈 긴 우회를 돌아 마침내 한 지붕 아래에서 나란히 백발을 맞은 **{v['name_wa']} {v['partner']}**. "
            f"[{v['specialty']}]{v['specialty_ro_s']} 살아온 고단한 세월 끝, 두 사람이 창가에서 낡은 추억과 **{v['item_short']}**{v['item_eul_s']} 꺼내 웃던 그 오후, 시간은 세상에서 가장 다정한 선물이 되었습니다."
        )
    elif eid == "redeemed_spring":
        core = (
            f"젊은 날의 오만과 어두운 그림자 속으로 추락했던 과거. 그러나 지천명의 심판 앞에서 변명 대신 스스로 무릎 꿇고 가진 것을 전부 내려놓았던 쉰 살의 선택.\n\n"
            f"가장 낮은 바닥에서 다시 두 팔을 걷어붙인 {v['name_eun']} 남은 백 년 가까운 세월을 묵묵히 타인의 상처를 닦고 갚는 데 바쳤습니다. "
            f"{age}세의 고요한 봄날, 사람들은 그의 허물이 아닌 끝내 다시 피워낸 가장 눈부신 두 번째 봄을 기억했습니다."
        )
    elif eid == "masked_shadow":
        core = (
            f"수천억 원의 검은 돈과 정재계의 가장 은밀한 비밀들이 [{v['specialty']}]의 손끝을 스쳐 갔지만, 정작 세상 어디에도 **{v['name']}**의 진짜 이름을 아는 이는 남지 않았습니다.\n\n"
            f"{v['city']}의 기억마저 지운 채 수많은 가명 속에 살았던 세월. 안개 낀 부두 혹은 뒷골목 어둠 속으로 홀연히 자취를 감춘 뒤, 그에 대해서는 빗소리처럼 떠도는 전설 같은 소문만 남았습니다."
        )
    elif eid == "broken_crown":
        core = (
            f"한때 돈과 지위로 세상의 모든 문을 열 수 있다고 믿었던 날들이 있었습니다. 그러나 양심을 깎아 쌓아 올린 모래성은 세월의 바람 한 줄기에 형체도 없이 무너져 내렸습니다.\n\n"
            f"차가운 빈방에 홀로 남아 젊은 날부터 지니고 온 **{v['item_eul']}** 멍하니 만지작거리던 {age}세의 **{v['name']}**. "
            f"너무 늦게야 떠오른 {v['origin_place']}의 소박한 웃음소리 앞에서, 부서진 왕관은 조용히 바닥을 굴렀습니다."
        )
    elif eid == "noodle_universe":
        core = (
            f"화려한 성공과 거대한 간판 대신 새벽 네 시 김 서린 가마솥 불빛을 지켜낸 **{v['name']}**. "
            f"어머니의 **{v['item_eul']}** 이어받아 {v['city']} 골목에 다시 띄운 멸치 육수 향기는 반세기가 넘도록 동네를 감쌌습니다.\n\n"
            f"주머니 빈 청춘에겐 넉넉한 한 그릇을, 지친 늙은 이웃에겐 말없는 위로를 건네며 살아낸 {age}년. 작은 국수 한 그릇은 온 세상을 품는 따스한 우주가 되었습니다."
        )
    elif eid == "truth_keeper":
        core = (
            f"수십 번의 협박과 회유, 가족과 자리를 겨눈 위협 속에서도 끝내 진실의 펜과 기록을 꺾지 않았던 [{v['specialty']}] **{v['name']}**.\n\n"
            f"{age}세에 조용히 자리를 물러났을 때 통장엔 남은 것이 적었지만, 그가 목숨처럼 지켜낸 기록 한 줄과 증거들은 수만 명의 억울한 삶을 구하는 시대의 법과 상식이 되었습니다."
        )
    elif eid == "healer_hands":
        core = (
            f"화려한 도심 대형 병원과 돈 되는 명예 대신, 안개 낀 {v['city']} 산골과 아픈 이웃의 머리맡을 끝까지 지킨 [{v['specialty']}] **{v['name']}**.\n\n"
            f"어린 시절 산새를 품던 그 손으로 수십 년간 수많은 생명을 다시 일으켜 세운 {age}세의 마지막 날, 장례식장 골목 밖까지 그가 살려낸 이웃들이 국화 한 송이씩을 들고 끝없이 줄을 섰습니다."
        )
    elif eid == "unheard_genius":
        core = (
            f"시대를 너무 앞서갔던 탓인지, 살아생전 **{v['name']}**의 **{v['workplace']}**에는 화려한 박수보다 가난과 고독이 더 오래 머물렀습니다.\n\n"
            f"하지만 낡은 **{v['tool']}**{v['tool_eul_s']} 손에 쥔 채 마지막 마침표를 찍고 떠난 지 20년 뒤, 먼지 쌓인 상자 속에서 **{v['work_obj']}**{v['work_obj_i_s']} 발굴되자 온 세상은 비로소 타협 없던 천재의 혼 앞에 깊은 경의를 바쳤습니다."
        )
    elif eid == "master_craft":
        core = (
            f"{v['city']}의 **{v['origin_place']}**에서 시작된 서툰 손짓은 70년 세월의 모진 바람과 땀을 견디며 마침내 한 시대의 기준이 되었습니다.\n\n"
            f"어떠한 요령도 편법도 들이지 않은 채 [{v['specialty']}]의 외길을 파고든 **{v['name']}**. {age}세까지 정직한 땀을 멈추지 않은 그의 이름과 **{v['work_obj']}**{v['work_obj_eun_s']} 시대를 대표하는 살아있는 전설로 남았습니다."
        )
    elif eid == "teacher_bridge":
        core = (
            f"스승 **{v['mentor']}**에게서 물려받은 묵직한 가르침을 헛되이 하지 않고, 스스로 빛나는 왕관 대신 다음 세대의 발판이 되어준 **{v['name']}**.\n\n"
            f"{age}세가 된 그의 오래된 공방과 교정에는 그가 기꺼이 자리를 내어주며 키워낸 제자들의 밝은 웃음소리가 봄바람처럼 끊이지 않았습니다."
        )
    elif eid == "village_lantern":
        core = (
            f"위인전이나 뉴스 첫 페이지에는 실리지 않았지만, 함께 살아간 {v['city_wa']} 동네 이웃 그 누구도 그의 따뜻한 이름을 잊지 못했습니다.\n\n"
            f"어려운 청춘이 굶지 않게 돕고, 늙고 외로운 이웃 곁을 말없이 지켰던 **{v['name']}**. {age}세에 평온히 눈을 감던 날 밤, 온 동네 골목 처마마다 그의 마지막 길을 밝히는 등불이 환하게 켜졌습니다."
        )
    elif eid == "empire_builder":
        sub = (
            f"수많은 직원들과 사랑하는 **{v['partner']}**의 축복 속에 일군 사업과 나눔의 가치를 따스하게 물려주며 진정한 큰 어른으로 기억되었습니다."
            if ("has_partner" in flags and empathy >= 45)
            else f"화려한 스카이라인을 내려다보는 높은 펜트하우스 창문 너머로, 문득 어릴 적 {v['origin_place']}의 소박한 냄새가 그리워지곤 했습니다."
        )
        core = (
            f"맨손과 작은 빚더미에서 출발해 시대의 흐름을 읽고 거대한 사업과 부를 일구어낸 [{v['specialty']}] **{v['name']}**.\n\n{sub}"
        )
    elif eid == "horizon_writer":
        core = (
            f"일흔이 넘어서도 빛바랜 배낭과 방수 수첩을 놓지 않았던 자유로운 영혼 **{v['name']}**.\n\n"
            f"바다 건너 낯선 항구 마을의 작은 우체국에서 고향 {v['city_eul']} 떠올리며 마지막 엽서를 부친 뒤, 그는 평생 사랑했던 끝없는 지평선 너머로 자유롭게 바람처럼 여행을 떠났습니다."
        )
    else:  # quiet_miracle
        sub = (
            f"마지막 순간까지 주름진 손을 놓지 않은 **{v['partner']}**{v['partner_wa_s']} 동네 이웃들의 따스한 웃음소리 속에서, 아무런 후회 없는 백 년의 미소를 남겼습니다."
            if "has_partner" in flags
            else f"좋아하던 차 한 잔의 향기와 창밖으로 바뀌어 가는 사계절의 빛깔을 사랑하며, 조용하지만 누구보다 충만한 한 생애를 마쳤습니다."
        )
        core = (
            f"화려한 전설도, 요란한 비극도 없었지만 그 누구보다 성실하고 다정하게 하루하루를 채워 올린 **{v['name']}**의 {age}년.\n\n{sub}"
        )

    highlights = tps[-4:] if len(tps) > 4 else tps
    tp_block = (
        "\n\n📌 **평생의 궤적을 만든 결정적 순간들**\n" + "\n".join(f"> • {t}" for t in highlights)
        if highlights
        else ""
    )
    return core + tp_block
