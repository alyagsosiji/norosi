"""
norosi Bot - 「타인의인생」 1,000종 멀티 엔딩 카탈로그 · 인과 판정 · 전기 에필로그 엔진 (other_life_endings.py)
- Group A (276종): 6대 출신 × 7대 진로/변주 통합 서사 아키타입 (별을 건너다·불꽃 같은 서른아홉·오래된 약속 등)
- Group B (720종): 6대 출신 × 20개 세부 전공 × 특화 아키타입 (120종/출신)
- Group C (4종)  : 출신 초월 신화 엔딩 (쌍성의 약속·불꽃에서 돌아온 전설·같은 하늘을 겨눈 두 별·백 년의 완전한 서사)
- 총합 정확히 1,000종 + 구 16종 세이브 데이터 무손실 마이그레이션
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import other_life_narratives as ol_narratives
from other_life_narratives import EMPIRE_ELIGIBLE_SPECIALTIES, SPECIALTY_CATALOG

# ==========================================
# 1. 24종 엔딩 아키타입 & 희귀도·배지 메타 (Group A/B 20종 + Group C 신화 4종)
# ==========================================
ARCHETYPE_META: Dict[str, Dict[str, Any]] = {
    "hidden_star": {
        "name": "별을 건너다",
        "emoji": "🌌",
        "rarity": "히든",
        "color": 0xA855F7,
        "base_crystal": 180,
        "hint": "유년(b1_curious)·학창(b4_study/b6_solo_star)·중년(b14_star)에 별의 씨앗을 품고 지성 58+·공감 54+ 상태로 70세 귀향에서 깨달음(b17_cosmos)→78세 별길(b18_star_walk)을 선택하세요.",
    },
    "flame_39": {
        "name": "불꽃 같은 서른아홉",
        "emoji": "🔥",
        "rarity": "전설",
        "color": 0xEF4444,
        "base_crystal": 135,
        "hint": "34~37세까지 무리(과로 플래그)하거나 근성을 38 이하(또는 24 이하)로 소진한 상태에서 39세 대위기(b12_heroic_risk)에 온몸을 던지세요.",
    },
    "old_promise": {
        "name": "오래된 약속의 완성",
        "emoji": "🧑‍🤝‍🧑",
        "rarity": "전설",
        "color": 0xF472B6,
        "base_crystal": 140,
        "hint": "9세에 소꿉친구와 가까워져(b2_close/b2_rival) 18세 약속(b6_comp_promise)을 맺고, 26세 혹은 44세 재회에서 끝내 서로의 손을 지켜내세요(그림자·타락 제외).",
    },
    "redeemed_spring": {
        "name": "회개와 두 번째 봄",
        "emoji": "🕯️",
        "rarity": "전설",
        "color": 0xFBBF24,
        "base_crystal": 135,
        "hint": "16·22·30세에 편법·타협(또는 그림자)에 발을 들였더라도 50세 심판(b14_reckoning) 앞에서 자진 참회(b14_redeem)를 선택하세요.",
    },
    "broken_crown": {
        "name": "부서진 왕관",
        "emoji": "💔",
        "rarity": "희귀",
        "color": 0x64748B,
        "base_crystal": 95,
        "hint": "편법과 타협(corrupted)을 거듭하거나 그림자 정점 다툼(b14_greed_clash)을 택하고 끝내 뉘우치지 않아 보세요.",
    },
    "lonely_summit": {
        "name": "고독한 정상",
        "emoji": "🏔️",
        "rarity": "희귀",
        "color": 0x4F46E5,
        "base_crystal": 125,
        "hint": "동반자 없이 홀로 걸으며(b6_comp_cold 또는 b9_stay_solo) 정직히 정상을 지킨 뒤 78세에 [홀로 선 정상(b18_lone_peak)]을 고르세요.",
    },
    "horizon_writer": {
        "name": "끝없는 지평선",
        "emoji": "🧭",
        "rarity": "희귀",
        "color": 0x06B6D4,
        "base_crystal": 120,
        "hint": "방랑·기록가의 길을 걷거나 50세(b14_explore)·63세(b16_journey)에 늦깎이 세계 여행을 떠나 보세요.",
    },
    "master_craft": {
        "name": "시대의 거장",
        "emoji": "🏆",
        "rarity": "전설",
        "color": 0xF59E0B,
        "base_crystal": 145,
        "hint": "전공 분야에서 정통·심화 선택(masterwork_kept/peak_craft_vow)을 밟고 주력 역량(지성/열정/근성 중 최고 62+)을 극한까지 벼리세요.",
    },
    "unheard_genius": {
        "name": "미완의 걸작",
        "emoji": "📜",
        "rarity": "희귀",
        "color": 0x6366F1,
        "base_crystal": 120,
        "hint": "화려한 부(자산 44 이하) 대신 순수 열정(46+)과 작품·연구에 매진해 78세 마지막 순간까지 혼신(b18_final_work)을 다하세요.",
    },
    "healer_hands": {
        "name": "생명을 잇는 손",
        "emoji": "🩺",
        "rarity": "희귀",
        "color": 0x10B981,
        "base_crystal": 125,
        "hint": "의학·약초다원·국경구호 전공에서 출세 대신 아픈 이를 구하는 맹세(healer_oath)와 공감(44+)을 끝까지 지키세요.",
    },
    "truth_keeper": {
        "name": "진실을 남긴 이름",
        "emoji": "⚖️",
        "rarity": "전설",
        "color": 0x3B82F6,
        "base_crystal": 140,
        "hint": "사료·언론·수사·변호·다큐 전공에서 고발 사명(whistleblower)을 품고 50세 법정/증언대(b14_truth_final)에서 진실을 세우세요.",
    },
    "noodle_universe": {
        "name": "국수 한 그릇의 우주",
        "emoji": "🍜",
        "rarity": "희귀",
        "color": 0xFB923C,
        "base_crystal": 130,
        "hint": "손멸치국수 장인으로서 골목의 온기(d_artn_local)를 지키거나 시장국수집 출신이 30세에 고향 국수집으로 귀환(b10_noodle_pivot)하세요.",
    },
    "teacher_bridge": {
        "name": "세대를 잇는 스승",
        "emoji": "🌟",
        "rarity": "희귀",
        "color": 0x38BDF8,
        "base_crystal": 120,
        "hint": "공감 46+을 유지하며 44세(b13_heir)·50세(b14_teach/b14_teach_law)·56세(b15_pass_torch)에서 후배를 기르는 길을 택하세요.",
    },
    "village_lantern": {
        "name": "작은 마을의 등불",
        "emoji": "🕊️",
        "rarity": "일반",
        "color": 0x22C55E,
        "base_crystal": 100,
        "hint": "공감 46+과 함께 지역·이웃 나눔(b8/b11/b14_share/b16_community)으로 조용하고 따스한 공동체의 불을 밝히세요.",
    },
    "empire_builder": {
        "name": "제국의 설계자",
        "emoji": "👑",
        "rarity": "희귀",
        "color": 0xEAB308,
        "base_crystal": 125,
        "hint": "사업·상업 확장 적성 전공에서 50세까지 자산을 32+로 키운 뒤 [더 큰 제국(b14_expand)]을 선택해 부를 완성하세요.",
    },
    "family_hearth": {
        "name": "가정의 온기",
        "emoji": "💐",
        "rarity": "일반",
        "color": 0xF97316,
        "base_crystal": 105,
        "hint": "26세에 일터의 인연(b9_commit_new)과 가정을 이루고 34~44세 가정의 온기를 지켜(b11_fam_warm/b13_heal_fam) 화목한 노년을 맞으세요.",
    },
    "quiet_miracle": {
        "name": "일상의 고요한 기적",
        "emoji": "🏡",
        "rarity": "일반",
        "color": 0x14B8A6,
        "base_crystal": 100,
        "hint": "극적인 파국이나 특정 전문 분기에 치우치지 않고 성실히 본업과 일상을 지켜 평온한 마침표를 찍으세요.",
    },
    "masked_shadow": {
        "name": "가면 뒤의 그림자",
        "emoji": "🎭",
        "rarity": "희귀",
        "color": 0x475569,
        "base_crystal": 115,
        "hint": "그림자 브로커·세탁 설계자 루트에서 50세까지 본명과 정체를 끝내 숨긴 채 어둠 속으로 잠적(b14_hide)하세요.",
    },
    "shadow_whistle": {
        "name": "어둠을 깨운 내부고발",
        "emoji": "📂",
        "rarity": "전설",
        "color": 0x0EA5E9,
        "base_crystal": 145,
        "hint": "그림자 루트에서 최소한의 자비(d_shd_leak)나 이탈 결심(b10_stand)을 남긴 뒤 50세에 조직 장부를 폭로(b14_shadow_whistle)하세요.",
    },
    "shadow_phantom": {
        "name": "이름 없는 밤의 후원자",
        "emoji": "🦇",
        "rarity": "전설",
        "color": 0x10B981,
        "base_crystal": 140,
        "hint": "그림자 루트에서 양심의 틈(d_shd_leak/b10_stand)을 남긴 뒤 50세에 검은 돈을 약자들에게 돌리는(b14_shadow_robin) 길을 고르세요.",
    },
    # Group C (Mythic)
    "myth_cosmos_promise": {
        "name": "쌍성의 약속",
        "emoji": "🌠",
        "rarity": "신화",
        "color": 0xC084FC,
        "base_crystal": 240,
        "hint": "[신화] 소꿉친구와 18세 약속을 지켜 평생 동반자(화목 유지)가 되는 동시에 별의 씨앗·지성 56+·공감 56+으로 별을 건너세요.",
    },
    "myth_phoenix_legend": {
        "name": "불꽃에서 돌아온 전설",
        "emoji": "🦅",
        "rarity": "신화",
        "color": 0xF43F5E,
        "base_crystal": 240,
        "hint": "[신화] 39세 화염 속으로 뛰어들어(b12_heroic_risk) 생존한 뒤 50세 거장/참회를 거쳐 80세+ & 근성 45+으로 전설을 완성하세요.",
    },
    "myth_rival_crown": {
        "name": "같은 하늘의 두 별",
        "emoji": "⚔️",
        "rarity": "신화",
        "color": 0xFB7185,
        "base_crystal": 240,
        "hint": "[신화] 9세 라이벌(b2_rival)과 18·44세 재회에서 화해 혹은 약속을 완성하고, 단일 역량(지성·열정·근성·자산 중 하나) 68+ 정점에 오르세요.",
    },
    "myth_complete_archive": {
        "name": "백 년의 완전한 서사",
        "emoji": "📖",
        "rarity": "신화",
        "color": 0x38BDF8,
        "base_crystal": 240,
        "hint": "[신화] 정직한 길(honest_path)로 지성·열정·공감·근성 모두 42+를 유지하며 회고록(b16_memoir)·화해(b17_forgive)·마침표(b18_final_work)를 모두 이루세요.",
    },
}


# ==========================================
# 2. 문학적 출신·진로·세부전공 모티프 (중복 없는 1,000종 제목·서사 조합)
# ==========================================
ORIGIN_MOTIFS: Dict[str, Dict[str, str]] = {
    "orphanage": {
        "label": "해송원",
        "place": "바닷가 보육원 '해송원'",
        "ep1": "해송원의 푸른 유리조각이 비춘",
        "ep2": "바닷가 다락에서 피어난",
        "ep3": "파도 소리 아래 첫 울음을 기억하는",
        "ep4": "갯바람과 갈매기가 지켜본",
        "ep5": "수평선 너머 유리빛을 품은",
        "ep6": "해송원 모래톱 발자국에서 시작된",
        "ep7": "바닷빛 유리 조각에서 첫발을 떼어",
        "scene": "초록빛 유리 조각과 파도 소리 어린 다락",
    },
    "noodle_shop": {
        "label": "시장국수집",
        "place": "시장통 24시 멸치국수집",
        "ep1": "새벽 네 시 멸치 육수 김 서린",
        "ep2": "노포 무쇠 국자의 뜨거운 온기를 품은",
        "ep3": "장터 첫차 불빛 속에서 싹튼",
        "ep4": "어머니의 펄펄 끓는 가마솥 곁에서 온",
        "ep5": "시장통 새벽 안개를 뚫고 걸어온",
        "ep6": "따뜻한 국물 한 그릇의 기억이 살아있는",
        "ep7": "김 서린 장터 채반 곁에서 자라나",
        "scene": "새벽 네 시 시장통 가마솥과 무쇠 국자",
    },
    "scholar_home": {
        "label": "한옥서재",
        "place": "오래된 한옥 서재 집안",
        "ep1": "한옥 서재의 먹 냄새가 밴",
        "ep2": "오래된 기와 처마와 만년필이 빚은",
        "ep3": "대들보 사이 별자리 노트를 품었던",
        "ep4": "고서 갈피마다 세월이 머문",
        "ep5": "묵묵한 서가의 그림자 속에서 자란",
        "ep6": "책장 달빛과 잉크 내음을 벗 삼던",
        "ep7": "엄격한 한옥 마루 끝에서 뻗어나간",
        "scene": "먹물 냄새 배인 한옥 서재와 천문학 노트",
    },
    "fallen_house": {
        "label": "붉은저택",
        "place": "빛바랜 붉은 벽돌 저택",
        "ep1": "붉은 벽돌 옛 저택에서 홀로 선",
        "ep2": "녹슨 가문 문장 열쇠를 움켜쥔",
        "ep3": "꺼진 샹들리에 폐허에서 피어난",
        "ep4": "무너진 돌담 아래서 이를 악물었던",
        "ep5": "차압 딱지 마루를 딛고 일어선",
        "ep6": "옛 저택 화단의 덩굴처럼 질긴",
        "ep7": "빛바랜 저택 정문 열쇠를 간직한",
        "scene": "무너진 붉은 벽돌 저택과 녹슨 가문 열쇠",
    },
    "artisan_shop": {
        "label": "시계공방",
        "place": "오래된 시계·목공 수리점",
        "ep1": "골목 시계방 초침 박자 속에서 자란",
        "ep2": "아버지의 황동 루페 너머를 보던",
        "ep3": "대패질 나무 향과 태엽이 어우러진",
        "ep4": "백열등 아래 톱니를 맞추던 마음으로",
        "ep5": "멈춘 시계에 다시 맥박을 넣던",
        "ep6": "놋쇠 시계추처럼 단단하게 걸어온",
        "ep7": "오래된 수리점 작업대 위에서 벼려진",
        "scene": "황동 돋보기 루페와 초침 소리 가득한 수리점",
    },
    "mountain_clinic": {
        "label": "산골약초방",
        "place": "안개 낀 산골 약초방",
        "ep1": "산골 약초방 첫 안개 속에서 피어난",
        "ep2": "쇠절구 약향과 은하수를 품은",
        "ep3": "할아버지의 낡은 처방전을 이어받은",
        "ep4": "골짜기 솔바람이 숨결을 보탠",
        "ep5": "다친 산새를 감싸 안고 자라난",
        "ep6": "짙은 숲 안개 사이 풀내음을 머금고 자란",
        "ep7": "산마을 아픈 이들의 맥을 짚던",
        "scene": "산안개 낀 약초방과 별자리·약초 수첩",
    },
}

ORIGIN_ORDER = [
    "orphanage",
    "noodle_shop",
    "scholar_home",
    "fallen_house",
    "artisan_shop",
    "mountain_clinic",
]

NON_SHADOW_CAREERS = ["artist", "scholar", "entrepreneur", "artisan", "guardian", "wanderer"]
ALL_CAREERS = NON_SHADOW_CAREERS + ["shadow"]

CAREER_LITERARY: Dict[str, Dict[str, str]] = {
    "artist": {
        "name": "예술·창작가",
        "actor": "예술가",
        "cosmos": "색채와 선율로 은하를 짠 예술가",
        "flame": "전시장 불길 속으로 붓과 심장을 던진 서른아홉",
        "promise": "어린 날 화폭을 안고 돌아온 동행",
        "redeem": "가난한 캔버스 앞에서 다시 붓을 잡은 두 번째 봄",
        "broken": "박수와 표절의 재 위에 흩어진 예술의 왕관",
        "summit": "누구의 평가도 받지 않은 고고한 미학의 정상",
        "horizon": "세상의 지평선을 스케치북에 담은 노년의 여행자",
    },
    "scholar": {
        "name": "학자·연구자",
        "actor": "연구자",
        "cosmos": "우주의 눈금과 인간애를 하나로 이은 성좌의 학자",
        "flame": "폭설 속 유독 연기를 뚫고 환자와 제자를 살린 서른아홉",
        "promise": "백 년 관측 기록을 나란히 펴든 약속의 백발",
        "redeem": "숫자의 오만을 내려놓고 진실 앞에 무릎 꿇은 두 번째 봄",
        "broken": "조작된 데이터 서류더미에 파묻힌 학자의 부서진 왕관",
        "summit": "논문 한 줄 없이 홀로 별빛을 관측한 고독한 정상",
        "horizon": "서재를 박차고 낯선 세계의 살아 있는 답을 걸어간 노년",
    },
    "entrepreneur": {
        "name": "사업·개척가",
        "actor": "개척가",
        "cosmos": "시장의 소란 너머 별의 질서를 읽은 사업가",
        "flame": "무너지는 철골 창고에서 직원을 끌어안은 서른아홉의 불꽃",
        "promise": "험한 풍파를 돌아 약속의 집을 세운 백 년 동반자",
        "redeem": "욕망의 회계를 태우고 소박한 골목으로 돌아온 두 번째 봄",
        "broken": "금고만 채운 채 모두를 잃은 차가운 마천루의 왕관",
        "summit": "아무도 믿지 않는 시장 홀로 정상에 오른 개척가의 고독",
        "horizon": "대표 명함을 접고 낡은 운동화로 세계를 밟은 제2의 청춘",
    },
    "artisan": {
        "name": "장인·생활인",
        "actor": "장인",
        "cosmos": "삶의 정직한 손끝으로 시간의 빛을 깎아낸 별의 장인",
        "flame": "폭우 밤 무너지는 골목 상가에서 이웃 아이를 건진 불꽃",
        "promise": "손마디 굵은 두 손이 맞잡은 오래된 골목 약속",
        "redeem": "초심을 팔았던 공방을 씻고 첫 땀방울을 되찾은 두 번째 봄",
        "broken": "싼 부품과 요령에 깎여나간 장인의 무너진 자부심",
        "summit": "묵묵히 혼자 작업대를 지켜온 세월의 고독한 정상",
        "horizon": "평생 쥐던 앞치마를 풀고 바깥세상의 바람을 마주한 기록자",
    },
    "guardian": {
        "name": "수호·언론인",
        "actor": "수호자",
        "cosmos": "사라진 진실과 인간성을 별빛처럼 복원한 파수꾼",
        "flame": "방화 테러 속 증거 상자와 제보자를 몸으로 감싼 서른아홉",
        "promise": "거친 세상 맞서던 두 손이 노을 앞에서 맞잡은 약속",
        "redeem": "침묵의 대가를 반납하고 피해자 앞에서 뉘우친 두 번째 봄",
        "broken": "권력의 입맞춤에 펜과 배지를 팔아넘긴 부서진 왕관",
        "summit": "동료 없이 끝까지 홀로 기록을 지켜낸 외로운 파수꾼",
        "horizon": "무거운 사건 수첩 대신 맑은 지평선을 담은 노년의 자유",
    },
    "wanderer": {
        "name": "방랑·기록가",
        "actor": "기록가",
        "cosmos": "지구 끝 밤하늘 아래서 시간의 경계를 건넌 별의 방랑자",
        "flame": "산사태 무너진 국경 천막에서 아이들을 안고 멈춘 서른아홉",
        "promise": "세상 끝을 떠돌다 결국 옛 약속의 포구로 돌아온 닻",
        "redeem": "방황과 과오를 털고 이름 없는 거리를 돕는 두 번째 봄",
        "broken": "어둠의 밀수와 탐욕에 발목이 꺾인 방랑자의 추락",
        "summit": "어디에도 정박하지 않은 채 바람과 동행한 고독한 정상",
        "horizon": "평생 미지 너머를 걸어 마침내 바람이 된 지평선의 기록자",
    },
    "shadow": {
        "name": "그림자 브로커",
        "actor": "그림자",
        "cosmos": "빛을 쫓는 별의 길",
        "flame": "암살자의 화염 속 소년을 구하고 사라진 뒷세계의 마지막 불꽃",
        "promise": "어둠 너머의 약속",
        "redeem": "암호 장부를 태우고 백지 신분으로 다시 태어난 두 번째 봄",
        "broken": "카르텔의 혈투 끝에 피투성이로 무너진 밤의 왕관",
        "summit": "그림자의 정상",
        "horizon": "바깥의 길",
    },
}

WANDERER_HORIZON_SPECS = {
    "wnd_photo": "필름 카메라 두 대와 수평선의 기억을 담은 다큐멘터리 작가",
    "wnd_relief": "국경 천막과 사막의 바람 너머를 기록한 구호의 방랑자",
}

# ==========================================
# 3. 20대 세부 전공 × 아키타입 문학적 제목 조각 (720종 100% 고유·자연스러움 보장)
# ==========================================
SPEC_ARCHETYPES: Dict[str, List[str]] = {
    "artist_paint": ["master_craft", "unheard_genius", "teacher_bridge", "village_lantern", "empire_builder", "family_hearth", "quiet_miracle"],
    "artist_music": ["master_craft", "unheard_genius", "teacher_bridge", "village_lantern", "empire_builder", "family_hearth", "quiet_miracle"],
    "artist_write": ["master_craft", "unheard_genius", "teacher_bridge", "village_lantern", "empire_builder", "family_hearth", "quiet_miracle"],
    "scholar_healer": ["healer_hands", "master_craft", "teacher_bridge", "village_lantern", "empire_builder", "family_hearth", "quiet_miracle"],
    "scholar_cosmos": ["master_craft", "unheard_genius", "teacher_bridge", "village_lantern", "family_hearth", "quiet_miracle"],
    "scholar_archive": ["truth_keeper", "master_craft", "unheard_genius", "teacher_bridge", "village_lantern", "family_hearth", "quiet_miracle"],
    "ent_food": ["empire_builder", "master_craft", "teacher_bridge", "village_lantern", "family_hearth", "quiet_miracle"],
    "ent_tech": ["empire_builder", "teacher_bridge", "village_lantern", "family_hearth", "quiet_miracle"],
    "ent_trade": ["empire_builder", "teacher_bridge", "village_lantern", "family_hearth", "quiet_miracle"],
    "artn_noodle": ["noodle_universe", "master_craft", "teacher_bridge", "village_lantern", "family_hearth", "quiet_miracle"],
    "artn_clock": ["master_craft", "unheard_genius", "teacher_bridge", "village_lantern", "empire_builder", "family_hearth", "quiet_miracle"],
    "artn_tea": ["healer_hands", "master_craft", "teacher_bridge", "village_lantern", "empire_builder", "family_hearth", "quiet_miracle"],
    "artn_craft": ["master_craft", "teacher_bridge", "village_lantern", "empire_builder", "family_hearth", "quiet_miracle"],
    "grd_press": ["truth_keeper", "master_craft", "teacher_bridge", "village_lantern", "family_hearth", "quiet_miracle"],
    "grd_detective": ["truth_keeper", "master_craft", "teacher_bridge", "village_lantern", "family_hearth", "quiet_miracle"],
    "grd_advocate": ["truth_keeper", "master_craft", "teacher_bridge", "village_lantern", "empire_builder", "family_hearth", "quiet_miracle"],
    "wnd_photo": ["unheard_genius", "truth_keeper", "teacher_bridge", "village_lantern", "family_hearth", "quiet_miracle"],
    "wnd_relief": ["healer_hands", "master_craft", "teacher_bridge", "village_lantern", "family_hearth", "quiet_miracle"],
    "shd_broker": ["masked_shadow", "shadow_whistle", "shadow_phantom"],
    "shd_launder": ["masked_shadow", "shadow_whistle", "shadow_phantom"],
}

SPEC_PHRASES: Dict[str, Dict[str, Tuple[str, str]]] = {
    "artist_paint": {
        "master_craft": ("수채화 거장의 영원한 화폭", "평생 한 획도 타협하지 않은 수채화 빛깔로 한 시대의 화단을 완성했습니다."),
        "unheard_genius": ("빛바랜 이젤 앞 뒤늦은 천재 화가", "생전엔 팔리지 않던 습작들이 사후 반세기 만에 세계를 울린 무명의 거장이 되었습니다."),
        "teacher_bridge": ("물감 쥔 어린 손을 이끈 미술 스승", "다락 아틀리에를 열어 제자들에게 빛과 색을 보는 눈을 물려주었습니다."),
        "village_lantern": ("골목 담장에 봄을 그린 동네 화가", "이웃들의 얼굴과 낡은 골목 풍경을 따뜻한 수채로 남긴 마을의 화가였습니다."),
        "empire_builder": ("아트 하우스와 미술관을 세운 거장", "홀로 그리던 화풍을 거대한 미술 재단과 전시 제국으로 일으켜 세웠습니다."),
        "family_hearth": ("아틀리에 식탁을 밝힌 화가의 반려", "팔레트 옆 작은 식탁에서 사랑하는 이의 미소를 평생 화폭에 담아내었습니다."),
        "quiet_miracle": ("묵묵히 계절을 그린 소박한 화가", "거창한 명예 없이도 매일 창가 햇살을 캔버스에 옮기며 온전한 일생을 채웠습니다."),
    },
    "artist_music": {
        "master_craft": ("여섯 줄 울림으로 시대를 연 악장", "닳아 없어진 기타 지판 위에서 세월이 흘러도 바래지 않을 선율을 완성했습니다."),
        "unheard_genius": ("지하 녹음실의 빛나는 미완의 악보", "생전엔 여섯 명의 청중 앞에 섰으나 사후 전 세계가 부르게 된 전설의 작곡가입니다."),
        "teacher_bridge": ("기타 조율을 건넨 지하방의 음악 스승", "길 잃은 젊은 음악가들에게 첫 코드와 버틸 용기를 나누어 준 스승이 되었습니다."),
        "village_lantern": ("동네 공원을 적신 저녁의 버스커", "해 질 녘 골목 어귀에서 이웃들의 고단한 하루를 어루만진 선율의 등불이었습니다."),
        "empire_builder": ("음악 레이블과 공연장을 세운 기획의 대가", "지하 작업실의 열정을 수많은 아티스트가 숨 쉬는 거대한 음악 제국으로 키웠습니다."),
        "family_hearth": ("사랑하는 이의 잠결을 닮은 자장가", "세상의 박수보다 집에 돌아와 한 사람만을 위해 뜯는 여섯 줄의 온기를 택했습니다."),
        "quiet_miracle": ("낮은 현을 퉁기며 보낸 고요한 악사", "유행에 휘둘리지 않고 하루 한 곡씩 자신의 마음을 조율하며 평화롭게 늙어갔습니다."),
    },
    "artist_write": {
        "master_craft": ("만년필 끝에 백 년을 새긴 문호", "원고지를 적신 평생의 진심이 한 시대의 고전으로 남아 독자들의 심장을 두드렸습니다."),
        "unheard_genius": ("옥탑 원고 상자 속에 잠든 천재 작가", "생전엔 초판조차 절판되었으나 20년 뒤 세상 사람들이 밤새 읽어낸 불후의 필체입니다."),
        "teacher_bridge": ("서툰 첫 문장에 붉은 펜을 건넨 글 스승", "무명 작가들의 습작마다 다정한 비평을 남기며 문학의 숲을 넓혀 준 스승입니다."),
        "village_lantern": ("이웃의 평범한 구술을 책으로 엮은 작가", "시장 상인과 골목 노인들의 삶을 아름다운 활자로 지켜낸 동네의 기록자였습니다."),
        "empire_builder": ("문예 출판 제국과 서사를 세운 설계자", "옥탑방 만년필에서 시작한 이야기를 거대한 출판·공연 왕국으로 피워 올렸습니다."),
        "family_hearth": ("서재 불빛 아래 마주 앉은 문장의 동반자", "평생의 문장 첫 번째 독자이자 곁을 지켜준 사람과 나란히 황혼을 맞았습니다."),
        "quiet_miracle": ("한 줄의 진실로 하루를 마친 소박한 작가", "베스트셀러 순위 대신 날마다 다정한 일기와 편지를 남기며 행복을 일구었습니다."),
    },
    "scholar_healer": {
        "master_craft": ("희귀 병마를 꺾은 백의의 대가", "현장의 맥박과 끝없는 임상 탐구로 인류의 의학 지평을 한 걸음 넓힌 거장입니다."),
        "healer_hands": ("아픈 이들의 밤을 지킨 생명의 손", "높은 직함과 안락을 거절하고 가장 약한 환자들의 머리맡에서 평생을 바쳤습니다."),
        "teacher_bridge": ("청진기를 물려준 응급실의 스승", "제자들에게 의술보다 먼저 환자의 두 눈을 바라보는 마음을 새겨준 스승입니다."),
        "village_lantern": ("문턱 없는 마을 무료 진료소의 등불", "형편이 어려운 이웃 누구에게나 밤중에도 문을 열어주던 골목의 어른이었습니다."),
        "empire_builder": ("생명 공학과 공공 의료망을 세운 설계자", "작은 진료실의 경험을 전국의 환자를 살리는 거대한 의료·제약 제국으로 키웠습니다."),
        "family_hearth": ("당직의 피로를 녹여준 가정의 온기", "수많은 생명을 살리던 바쁜 손이 집에 돌아오면 다정한 반려의 손을 놓지 않았습니다."),
        "quiet_miracle": ("묵묵히 이웃의 안부를 지킨 성실한 의사", "큰 스포트라이트 없이도 평생 단골 환자들의 안부를 지키며 고요한 삶을 완주했습니다."),
    },
    "scholar_cosmos": {
        "master_craft": ("별빛의 방정식을 증명한 천체의 거장", "수십 년 관측 기록 끝에 우주의 숨은 대칭을 풀어내며 과학사의 이름을 세웠습니다."),
        "unheard_genius": ("외딴 천문대의 시대를 앞선 별의 천재", "살아생전 이단 취급을 받았으나 반세기 뒤 인류가 그 노트를 통해 우주를 새로 읽었습니다."),
        "teacher_bridge": ("작은 망원경을 함께 들여다본 스승", "밤을 새워 별을 묻는 젊은 연구자들의 손에 가장 먼저 관측 일지를 쥐여주었습니다."),
        "village_lantern": ("동네 옥상에서 별자리를 들려준 선생님", "이웃과 아이들에게 밤하늘이 주는 위로를 전하며 작은 동네의 별빛 등대가 되었습니다."),
        "family_hearth": ("긴 관측의 밤 끝을 지켜준 따뜻한 불빛", "차갑고 머나먼 우주 계산 뒤에는 언제나 곁에서 차를 내어주던 소중한 사람이 있었습니다."),
        "quiet_miracle": ("고요한 밤하늘과 나란히 늙은 관측자", "거창한 명성 대신 매일 밤 익숙한 별자리를 확인하는 평화로운 생애를 보냈습니다."),
    },
    "scholar_archive": {
        "master_craft": ("지워진 역사의 백 년을 복원한 거장", "수천 장의 고문서와 먼지 낀 증언을 되살려 시대의 학문적 기준을 새로 세웠습니다."),
        "unheard_genius": ("지하 서고에서 홀로 진실을 짠 고독한 사학자", "당대의 무관심 속에서 써 내려간 연구노트가 훗날 역사를 다시 쓴 걸작이 되었습니다."),
        "truth_keeper": ("은폐된 이름들을 세상에 되돌린 기록의 파수꾼", "권력이 불태우려던 피해자들의 진실을 끝내 법정과 역사책 위에 남겼습니다."),
        "teacher_bridge": ("사료의 무게를 다음 세대에 건넨 스승", "숫자와 권위보다 한 줄의 진실된 증언을 대하는 태도를 제자들에게 물려주었습니다."),
        "village_lantern": ("고향 사람들의 백 년 삶을 지켜낸 지역 기록가", "화려한 국사 너머 이름 없는 이웃들의 사진과 구술을 소중히 모은 마을의 기억 창고입니다."),
        "family_hearth": ("오래된 책 냄새와 함께 나눈 다정한 세월", "서재 구석의 고요함 속에서 반려와 나눈 소박한 대화들이 백 년을 따뜻하게 채웠습니다."),
        "quiet_miracle": ("먼지 낀 사료 한 장씩을 닦아낸 성실한 학자", "조용히 사실을 정리하며 시대에 묵묵한 진실의 주석을 남긴 채 눈을 감았습니다."),
    },
    "ent_food": {
        "empire_builder": ("정직한 먹거리로 전국을 잇는 로컬 제국", "작은 공단 창고에서 시작해 건강한 식탁을 세우는 거대한 식품 왕국을 설계했습니다."),
        "master_craft": ("맛과 원가의 양심을 끝내 지킨 식품 장인 대표", "이윤에 타협하지 않고 백 년 가는 정직한 제품 기준을 세워 업계의 존경을 받았습니다."),
        "teacher_bridge": ("지역 청년 상인들의 기둥이 된 멘토 대표", "실패를 딛고 일어난 경험을 아낌없이 나누며 수많은 로컬 창업을 이끌어 주었습니다."),
        "village_lantern": ("이웃의 굶주림에 가장 먼저 상자를 연 후원자", "매일 남은 정성과 수익을 지역 보육원과 어르신 쉼터에 돌린 따뜻한 사업가였습니다."),
        "family_hearth": ("일터의 분주함을 껴안아 준 가족의 저녁 식탁", "전국을 누비는 바쁨 속에서도 집의 저녁 밥상만큼은 끝내 소중히 지켜내었습니다."),
        "quiet_miracle": ("한 그릇 정성으로 동네를 먹인 정직한 대표", "무모한 팽창을 접고 정든 거래처와 함께 성실한 하루들을 쌓아 올렸습니다."),
    },
    "ent_tech": {
        "empire_builder": ("정밀 부품에서 세계 표준을 세운 기술 제국", "납땜기 하나에서 출발해 시대의 산업 지도를 바꾸는 거대한 기술 제국을 완성했습니다."),
        "teacher_bridge": ("실패한 청년 공학도들의 버팀목", "수백 번 고장 나던 경험을 나누며 다음 세대 기술자들이 꺾이지 않게 손잡아 주었습니다."),
        "village_lantern": ("지역 공단과 이웃의 불편을 고쳐주던 발명가", "거창한 특허보다 동네 어르신과 작은 공장들이 바로 쓸 수 있는 기술을 묵묵히 나누었습니다."),
        "family_hearth": ("밤샘 도면 옆에서 식지 않은 차 한 잔의 사랑", "험난한 창업 전쟁터 뒤에서 늘 기다려 준 반려와 함께 온화한 노년을 맞이했습니다."),
        "quiet_miracle": ("정직한 도면으로 한 평생 현장을 지킨 기술인", "유행을 쫓기보다 손에 쥔 정밀 기계와 동료들을 지키며 떳떳하게 마침표를 찍었습니다."),
    },
    "ent_trade": {
        "empire_builder": ("바다 건너 항로를 개척한 해운 무역 거물", "원양 선적 서류 한 장에서 시작해 대륙을 잇는 거대한 물류·무역 제국을 세웠습니다."),
        "teacher_bridge": ("먼 항로를 후배들에게 열어준 상사의 어른", "거친 협상에서 얻은 눈과 신용의 원칙을 젊은 개척자들에게 아낌없이 전해주었습니다."),
        "village_lantern": ("고향 부두와 어민들을 먼저 돌본 항구의 버팀목", "바다에서 번 재산을 늘 고향 항구와 선원 가족들의 안전을 위해 먼저 흘려보냈습니다."),
        "family_hearth": ("먼 출항 끝마다 닻을 내렸던 다정한 항구", "거친 파도 너머로 돌아올 따뜻한 집 한 채를 지켜내며 평생의 사랑을 완주했습니다."),
        "quiet_miracle": ("약속을 어기지 않은 항구 앞 정직한 무역인", "크게 욕심내지 않고 신뢰할 수 있는 거래처들과 묵묵히 바다의 세월을 건넜습니다."),
    },
    "artn_noodle": {
        "noodle_universe": ("밤낮없이 정성껏 말아 낸 국수 한 그릇의 우주", "반세기가 넘도록 지친 이들에게 따뜻한 국수 한 그릇의 기적을 건넨 골목의 전설입니다."),
        "master_craft": ("사십 년 씨육수 한 솥을 완성한 국수 명장", "값싼 조미료를 끝내 거부하고 오직 정직한 불과 손맛으로 시대의 미각을 세웠습니다."),
        "teacher_bridge": ("국자 무게와 새벽 정성을 전한 국수집 스승", "갈 곳 없던 젊은이들에게 국수 뽑는 기술과 살아갈 넉넉한 품을 물려주었습니다."),
        "village_lantern": ("시장통 누구나 기대어 쉴 수 있는 24시 등불", "주머니 빈 학생과 늦은 노동자들의 외상 장부를 조용히 지워주던 동네의 어머니·아버지였습니다."),
        "family_hearth": ("국물 냄새와 웃음이 잦아들지 않던 부엌의 행복", "서로의 시린 손을 잡아주며 평생 함께 육수 솥 불을 지킨 두 사람의 따뜻한 집입니다."),
        "quiet_miracle": ("한 그릇 정성으로 백 년의 하루를 빚은 삶", "유명세나 프랜차이즈 대신 매일 똑같은 시간 문을 여는 성실함으로 세상을 적셨습니다."),
    },
    "artn_clock": {
        "master_craft": ("멈춘 백 년의 태엽을 살려낸 시간의 명장", "0.1밀리미터 오차도 허용하지 않는 루페의 눈길로 한 시대의 정밀 공예를 대표했습니다."),
        "unheard_genius": ("골목 끝에서 시간에 얽힌 비밀을 깎은 천재", "평생 홀로 만든 걸작 기계시계가 사후 세계 박물관의 심장에 놓이게 되었습니다."),
        "teacher_bridge": ("작은 핀셋으로 인내를 가르친 공방의 스승", "서두르는 제자들의 손을 붙들며 부품 하나에 깃든 시간의 예의를 전해주었습니다."),
        "village_lantern": ("이웃의 추억 깃든 고장 난 시계를 고쳐준 어른", "수리비 대신 오래된 가족 사연을 들으며 동네 사람들의 잃어버린 시간을 되찾아 주었습니다."),
        "empire_builder": ("정밀 타임피스 하우스를 세운 장인의 설계자", "골목 수리점의 섬세한 기술을 세계가 경외하는 독자 시계 브랜드 제국으로 일구었습니다."),
        "family_hearth": ("똑딱거리는 초침 곁에서 느리게 익어간 사랑", "두 사람의 나란한 호흡이 어떤 명품 시계보다 정확하고 따뜻하게 세월을 기록했습니다."),
        "quiet_miracle": ("째깍거리는 골목 공방을 끝까지 지킨 시계공", "수많은 이들의 손목 위 시간을 돌보며 자기 인생의 시계도 가장 고요히 매듭지었습니다."),
    },
    "artn_tea": {
        "master_craft": ("백 년 숙성 씨앗차를 완성한 다원의 거장", "장마와 병충해를 이겨낸 천 번의 덖음 끝에 한 시대가 경탄하는 명차를 빚어내었습니다."),
        "healer_hands": ("한 잔 달인 차로 상처를 씻어낸 치유의 다원", "몸과 마음이 곪아 쓰러진 이들에게 돈 대신 따뜻한 약차를 내어주며 수많은 이들을 일으켰습니다."),
        "teacher_bridge": ("산의 바람과 불 다루는 법을 건넨 다원 스승", "제자들에게 잎을 덖는 기술보다 기다림의 마음을 먼저 물려주었습니다."),
        "village_lantern": ("비 피하는 누구나 맞아주던 산자락의 등불", "산골 이웃과 나그네들이 땀 식히고 갈 수 있도록 솥에 언제나 차를 끓여두던 어른입니다."),
        "empire_builder": ("전통 발효·약초 차 문화를 세계에 세운 개척가", "무쇠 솥의 전통을 현대 건강·차 문화 산업 제국으로 일으켜 세웠습니다."),
        "family_hearth": ("솔바람 깃든 다실 창가에서 함께 늙어간 반려", "차 향기 은은히 피어오르는 저녁마다 곁을 지켜준 사람과 잔을 맞대며 웃었습니다."),
        "quiet_miracle": ("계절마다 새순을 덖으며 보낸 고요한 다인", "거친 세상과 떨어져 손끝의 흙과 찻잎을 사랑하며 자연처럼 편안히 눈을 감았습니다."),
    },
    "artn_craft": {
        "master_craft": ("빵과 가죽 결에 정성을 새긴 수제 공예 명장", "속임수 없는 천연 재료와 단단한 바느질로 시대가 믿고 찾는 장인의 정점에 올랐습니다."),
        "teacher_bridge": ("새벽 오븐과 재단 칼을 물려준 공방의 스승", "청년 장인들이 자기 이름으로 떳떳이 설 수 있도록 공방 한켠을 아낌없이 내어주었습니다."),
        "village_lantern": ("골목 아침을 여는 따뜻한 냄새의 수호자", "빵 한 조각과 가방 수선 하나로 동네 단골들의 하루를 묵묵히 응원해 준 이웃이었습니다."),
        "empire_builder": ("장인의 정성을 품은 수제 아틀리에 브랜드 제국", "오직 정성으로 시작한 공방 이름을 수많은 사람들이 신뢰하는 거대한 브랜드로 키워냈습니다."),
        "family_hearth": ("밀가루 묻은 앞치마를 껴안아 준 가족의 밤", "함께 반죽하고 닦으며 살아온 날들이 세월의 가장 달콤한 기념일이 되었습니다."),
        "quiet_miracle": ("단골 이름을 하나씩 기억하며 늙은 골목 장인", "크게 번창하지 않아도 매일 정직한 결과물로 보답한 백 년의 하루를 완주했습니다."),
    },
    "grd_press": {
        "truth_keeper": ("거짓 권력을 꺾고 시대의 상식을 세운 탐사기자", "수만 번의 협박과 회유 앞에서도 녹음기를 끄지 않아 세상의 양심을 지켜내었습니다."),
        "master_craft": ("한국 탐사 저널리즘의 살아있는 교과서", "끝없는 크로스체크와 타협 없는 문장으로 언론의 사명이 무엇인지 시대에 증명했습니다."),
        "teacher_bridge": ("어린 기자들의 수첩에 원칙을 심어준 보도국 스승", "진실 앞에 작아지려던 후배들 뒤에서 방패가 되어 펜을 지켜주었습니다."),
        "village_lantern": ("목소리 없는 시민들의 억울함을 실어준 골목 기자", "큰 특종보다 가장 힘없는 이웃의 작은 탄원서에 먼저 지면을 내어주었습니다."),
        "family_hearth": ("험한 취재 끝에도 집 문을 열어주던 믿음직한 짝", "위태로운 밤마다 흔들리지 않게 붙들어 준 동반자의 손 덕분에 끝내 무너지지 않았습니다."),
        "quiet_miracle": ("한 줄의 사실도 틀리지 않으려 애쓴 묵직한 언론인", "요란한 이름 대신 늘 정직한 기록 한 편으로 하루를 마감하며 평온히 은퇴했습니다."),
    },
    "grd_detective": {
        "truth_keeper": ("끝까지 미제 사건을 풀어내 원혼을 달랜 수사관", "모두가 잊자고 손사래 치던 사건 파일을 반평생 품어 마침내 진범의 이름을 밝혀내었습니다."),
        "master_craft": ("사건 현장과 닳은 손전등이 증명한 전설의 형사", "권력의 외압보다 피 묻은 골목의 단서를 먼저 믿었던 백전노장의 수호자입니다."),
        "teacher_bridge": ("잠복 밤샘 끝에 후배에게 눈을 물려준 반장", "후배 수사관들에게 요령 대신 끝까지 피해자 가족 눈물을 잊지 않는 기개를 남겼습니다."),
        "village_lantern": ("동네 밤길을 평생 묵묵히 순찰한 골목의 파수꾼", "거대한 훈장보다 아이들과 상인이 안심하고 밤길을 걷는 풍경을 가장 사랑했습니다."),
        "family_hearth": ("위태로운 야근 뒤 따뜻한 국밥으로 맞이하던 가정", "험한 사건 현장을 견딜 수 있었던 건 집에 돌아와 안을 수 있는 사랑이 있었기 때문입니다."),
        "quiet_miracle": ("퇴직 날까지 한결같이 골목을 지킨 성실한 형사", "큰 공을 자랑하지 않고 무탈한 오늘 하루들을 보물로 여기며 조용히 물러났습니다."),
    },
    "grd_advocate": {
        "truth_keeper": ("약자들의 눈물로 시대의 법전을 고쳐 쓴 공익변호인", "승산 없는 싸움 앞에서도 끝내 물러서지 않아 수천 명 노동자와 시민의 권리를 되찾아 주었습니다."),
        "master_craft": ("법정 논리와 인간애를 완성한 인권 변론의 대가", "무너진 법의 저울을 수십 년간의 변론과 저작으로 다시 바로 세운 거장입니다."),
        "teacher_bridge": ("무료 변론의 깃발을 후배 법조인에게 건넨 스승", "돈 대신 사람의 존엄을 변호하는 청년 법률가들의 큰 어른이자 버팀목이 되었습니다."),
        "village_lantern": ("채소 바구니 하나도 정성껏 받아안던 골목 법률방", "글 모르는 어르신과 쫓겨난 이들의 탄원서를 밤새 고쳐 써주며 동네를 지켰습니다."),
        "empire_builder": ("공익과 정의의 틀을 세운 초대형 로펌의 설계자", "낡은 사무실의 투지를 거대한 사회적 법률·인권 재단과 로펌 시스템으로 키워냈습니다."),
        "family_hearth": ("고된 법정 싸움 끝에서 서로를 지켜준 튼튼한 사랑", "돈 적고 바쁜 공익 변호사의 곁을 끝까지 믿어준 반려와 평생 손을 놓지 않았습니다."),
        "quiet_miracle": ("작은 탄원서 하나에도 밤새 밑줄을 그은 변호사", "화려한 재계 사건 대신 평범한 이웃의 일상 권리를 지키며 보람된 백 년을 마쳤습니다."),
    },
    "wnd_photo": {
        "unheard_genius": ("변방의 얼굴을 찍어 반세기 뒤 세계를 울린 사진가", "생전엔 무명의 다큐 작가로 남았으나 훗날 그 필름 통들은 인류가 간직할 위대한 유산이 되었습니다."),
        "truth_keeper": ("금지된 현장의 비극을 필름에 봉인해 고발한 기록자", "검열과 위협을 뚫고 지워질 뻔했던 사람들을 사진 한 장에 영원히 살려내었습니다."),
        "teacher_bridge": ("어린 사진가들에게 뷰파인더 너머의 마음을 가르친 스승", "장비의 가격보다 피사체를 향한 예의가 먼저임을 후배들에게 새겨주었습니다."),
        "village_lantern": ("낯선 마을마다 웃음을 사진으로 돌려준 방랑 사진사", "오래된 사진 한 장 없던 외진 고을 사람들에게 평생 간직할 영정과 가족사진을 남겼습니다."),
        "family_hearth": ("지구 반 바퀴를 돌아 함께 닻을 내린 길 위의 반려", "거친 여행길에서도 늘 같은 지도를 펼쳐 보던 동반자와 포근한 집에서 노년을 맞았습니다."),
        "quiet_miracle": ("인생의 소소한 순간들을 필름에 고이 담은 여행자", "화려한 수상 대신 가방 가득 따뜻한 사람 냄새 나는 사진첩을 안고 고요히 잠들었습니다."),
    },
    "wnd_relief": {
        "healer_hands": ("전쟁과 재난 천막을 지킨 국경 밖 생명의 손", "무너진 마을마다 가장 먼저 천막을 치고 아이들을 품어 안아 수많은 목숨을 이어 주었습니다."),
        "master_craft": ("세계 오지 구호 현장의 기준을 세운 현장 지휘자", "절망뿐인 재난 현장에서도 사람을 살리는 시스템과 용기를 끝없이 갈고닦은 대가입니다."),
        "teacher_bridge": ("오지의 먼지를 견뎌내는 구호 정신을 물려준 선배", "두려움에 떨던 젊은 봉사자들의 손을 잡고 현장 속 희망의 법칙을 일러주었습니다."),
        "village_lantern": ("국경 너머 작은 마을들이 영원히 기억한 이방인 친구", "이름도 낯선 외진 땅에서 아이들에게 글과 웃음과 우물을 선물한 고마운 어른이었습니다."),
        "family_hearth": ("거친 천막 바람을 함께 버텨낸 전우 같은 사랑", "말보다 행동으로 아픔을 나누던 반려와 함께 세월의 끝에서 따뜻한 쉼표를 찍었습니다."),
        "quiet_miracle": ("한 생명을 살리는 하루하루를 감사히 여긴 기록가", "세상을 전부 바꾸지 못해도 눈앞의 한 아이 손을 잡아준 기적만으로 충분했던 삶입니다."),
    },
    "shd_broker": {
        "masked_shadow": ("마지막까지 본명을 지운 익명의 정보 브로커", "수백 개의 가명과 암막 뒤에서 거대한 판을 쥐락펴락하다 안개처럼 조용히 사라졌습니다."),
        "shadow_whistle": ("암흑 카르텔의 심장에 원본 장부를 꽂은 고발자", "스스로가 속했던 어둠의 제국 전체를 세상에 폭로하고 어두운 시대의 막을 내렸습니다."),
        "shadow_phantom": ("검은돈으로 골목의 병원을 지킨 이름 없는 밤의 후원자", "정체를 끝내 숨긴 채 어둠의 재산을 가난한 이들에게 돌리며 조용히 죄를 씻었습니다."),
    },
    "shd_launder": {
        "masked_shadow": ("백지 장부 하나 남기지 않고 사라진 지하 금융의 유령", "거대한 지하 자금망을 끝까지 관리하다 어느 비 오는 새벽 아무 흔적도 없이 자취를 감췄습니다."),
        "shadow_whistle": ("지하 금고 마스터 디스크로 어둠을 무너뜨린 배신자이자 양심", "마지막 순간 모든 차명 계좌와 범죄의 근거를 세상에 넘겨 억울한 이들의 한을 풀었습니다."),
        "shadow_phantom": ("어둠의 숫자를 돌려 가난한 골목을 살린 비밀의 수호자", "세상이 모르는 사이 검은 자금의 물줄기를 장학금과 무료 급식소로 바꾼 밤의 해결사입니다."),
    },
}

# ==========================================
# 4. 1,000종 엔딩 카탈로그 조립 (100% 고유 ID & 100% 고유 문학적 제목)
# ==========================================
ARCH_GROUP_A_MOD = {
    "hidden_star": "별을 건너다",
    "flame_39": "불꽃 같은 서른아홉",
    "old_promise": "오래된 약속의 완성",
    "redeemed_spring": "회개와 두 번째 봄",
    "broken_crown": "부서진 왕관",
    "lonely_summit": "고독한 정상",
    "horizon_writer": "끝없는 지평선",
}


def _build_all_endings() -> Dict[str, Dict[str, Any]]:
    catalog: Dict[str, Dict[str, Any]] = {}
    seen_titles = set()

    def _register(entry: Dict[str, Any]) -> None:
        eid = entry["id"]
        title = entry["title"]
        if eid in catalog:
            raise ValueError(f"Duplicate ending ID: {eid}")
        if title in seen_titles:
            raise ValueError(f"Duplicate ending title: {title} ({eid})")
        seen_titles.add(title)
        catalog[eid] = entry

    # ── Group A : 276종 ──
    for oid in ORIGIN_ORDER:
        om = ORIGIN_MOTIFS[oid]
        # 1) hidden_star (6 × 6 = 36)
        for cid in NON_SHADOW_CAREERS:
            cm = CAREER_LITERARY[cid]
            am = ARCHETYPE_META["hidden_star"]
            _register({
                "id": f"grp_a__{oid}__{cid}__hidden_star",
                "title": f"{om['ep1']} {cm['cosmos']} — 별을 건너다",
                "emoji": am["emoji"],
                "rarity": am["rarity"],
                "color": am["color"],
                "base_crystal": am["base_crystal"],
                "summary": f"{om['place']}에서 품은 첫 질문이 {cm['name']}의 평생을 건너 은하수의 깨달음으로 완성된 히든 생애",
                "hint": am["hint"],
                "origin_id": oid,
                "career": cid,
                "specialty_id": "",
                "archetype": "hidden_star",
                "group": "A",
            })

        # 2) flame_39 (6 × 7 = 42)
        for cid in ALL_CAREERS:
            cm = CAREER_LITERARY[cid]
            am = ARCHETYPE_META["flame_39"]
            _register({
                "id": f"grp_a__{oid}__{cid}__flame_39",
                "title": f"{om['ep2']} {cm['flame']}",
                "emoji": am["emoji"],
                "rarity": am["rarity"],
                "color": am["color"],
                "base_crystal": am["base_crystal"],
                "summary": f"{om['place']} 출신 {ol_narratives.j_i(cm['actor'])} 한계 체력을 소진한 39세의 밤 타인을 구하려 온몸을 던진 짧은 영원의 생애",
                "hint": am["hint"],
                "origin_id": oid,
                "career": cid,
                "specialty_id": "",
                "archetype": "flame_39",
                "group": "A",
            })

        # 3) old_promise (6 × 6 = 36)
        for cid in NON_SHADOW_CAREERS:
            cm = CAREER_LITERARY[cid]
            am = ARCHETYPE_META["old_promise"]
            _register({
                "id": f"grp_a__{oid}__{cid}__old_promise",
                "title": f"{om['ep3']} {cm['promise']} — {cm['name']}",
                "emoji": am["emoji"],
                "rarity": am["rarity"],
                "color": am["color"],
                "base_crystal": am["base_crystal"],
                "summary": f"{om['place']} 시절 나눈 어린 약속을 {cm['name']}의 험한 세월 너머에서 끝내 지켜낸 두 사람의 백 년",
                "hint": am["hint"],
                "origin_id": oid,
                "career": cid,
                "specialty_id": "",
                "archetype": "old_promise",
                "group": "A",
            })

        # 4) redeemed_spring (6 × 7 = 42)
        for cid in ALL_CAREERS:
            cm = CAREER_LITERARY[cid]
            am = ARCHETYPE_META["redeemed_spring"]
            _register({
                "id": f"grp_a__{oid}__{cid}__redeemed_spring",
                "title": f"{om['ep4']} {cm['redeem']}",
                "emoji": am["emoji"],
                "rarity": am["rarity"],
                "color": am["color"],
                "base_crystal": am["base_crystal"],
                "summary": f"어린 시절의 {om['label']} 기억을 딛고 과거의 과오를 뉘우쳐 다시 살아난 {cm['actor']}의 두 번째 봄",
                "hint": am["hint"],
                "origin_id": oid,
                "career": cid,
                "specialty_id": "",
                "archetype": "redeemed_spring",
                "group": "A",
            })

        # 5) broken_crown (6 × 7 = 42)
        for cid in ALL_CAREERS:
            cm = CAREER_LITERARY[cid]
            am = ARCHETYPE_META["broken_crown"]
            _register({
                "id": f"grp_a__{oid}__{cid}__broken_crown",
                "title": f"{om['ep5']} {cm['broken']}",
                "emoji": am["emoji"],
                "rarity": am["rarity"],
                "color": am["color"],
                "base_crystal": am["base_crystal"],
                "summary": f"타협과 탐욕을 좇은 {om['label']} 출신 {ol_narratives.j_i(cm['actor'])} 신의를 잃고 빈 방에서 회한을 마주한 씁쓸한 결말",
                "hint": am["hint"],
                "origin_id": oid,
                "career": cid,
                "specialty_id": "",
                "archetype": "broken_crown",
                "group": "A",
            })

        # 6) lonely_summit (6 × 6 = 36)
        for cid in NON_SHADOW_CAREERS:
            cm = CAREER_LITERARY[cid]
            am = ARCHETYPE_META["lonely_summit"]
            _register({
                "id": f"grp_a__{oid}__{cid}__lonely_summit",
                "title": f"{om['ep6']} {cm['summit']}",
                "emoji": am["emoji"],
                "rarity": am["rarity"],
                "color": am["color"],
                "base_crystal": am["base_crystal"],
                "summary": f"누구에게도 기대지 않고 홀로 버텨온 {cm['name']}의 길을 흔들림 없이 마침표 찍은 외롭고 당당한 정상",
                "hint": am["hint"],
                "origin_id": oid,
                "career": cid,
                "specialty_id": "",
                "archetype": "lonely_summit",
                "group": "A",
            })

        # 7) horizon_writer: 5 non-wanderer non-shadow careers (30) + 2 wanderer specialties (12) = 42
        for cid in ["artist", "scholar", "entrepreneur", "artisan", "guardian"]:
            cm = CAREER_LITERARY[cid]
            am = ARCHETYPE_META["horizon_writer"]
            _register({
                "id": f"grp_a__{oid}__{cid}__horizon_writer",
                "title": f"{om['ep7']} {cm['horizon']}",
                "emoji": am["emoji"],
                "rarity": am["rarity"],
                "color": am["color"],
                "base_crystal": am["base_crystal"],
                "summary": f"{cm['name']}의 자리에 안주하지 않고 인생 후반부 낡은 배낭을 메어 지평선을 건넌 자유인의 생애",
                "hint": am["hint"],
                "origin_id": oid,
                "career": cid,
                "specialty_id": "",
                "archetype": "horizon_writer",
                "group": "A",
            })

        for wsid, wdesc in WANDERER_HORIZON_SPECS.items():
            am = ARCHETYPE_META["horizon_writer"]
            tag = "사진" if wsid == "wnd_photo" else "구호"
            _register({
                "id": f"grp_a__{oid}__{wsid}__horizon_writer",
                "title": f"{om['ep7']} {wdesc} ({tag} 기록자)",
                "emoji": am["emoji"],
                "rarity": am["rarity"],
                "color": am["color"],
                "base_crystal": am["base_crystal"],
                "summary": f"{ol_narratives.j_eul(om['place'])} 떠나 {ol_narratives.j_ro(SPECIALTY_CATALOG[wsid]['title'])} 세계의 바람을 쫓으며 지평선 너머로 걸어간 노년",
                "hint": am["hint"],
                "origin_id": oid,
                "career": "wanderer",
                "specialty_id": wsid,
                "archetype": "horizon_writer",
                "group": "A",
            })

    # ── Group B : 720종 (120종/출신 × 6출신) ──
    origin_spec_prefixes = [
        "ep1", "ep2", "ep3", "ep4", "ep5", "ep6", "ep7"
    ]
    for oid in ORIGIN_ORDER:
        om = ORIGIN_MOTIFS[oid]
        for sid, arch_list in SPEC_ARCHETYPES.items():
            smeta = SPECIALTY_CATALOG[sid]
            sp_phrases = SPEC_PHRASES[sid]
            for a_idx, arch in enumerate(arch_list):
                am = ARCHETYPE_META[arch]
                core_title, core_sum = sp_phrases[arch]
                pref_key = origin_spec_prefixes[a_idx % len(origin_spec_prefixes)]
                title = f"{om[pref_key]} {core_title}"
                _register({
                    "id": f"spec__{oid}__{sid}__{arch}",
                    "title": title,
                    "emoji": am["emoji"],
                    "rarity": am["rarity"],
                    "color": am["color"],
                    "base_crystal": am["base_crystal"],
                    "summary": f"[{om['label']} · {smeta['title']}] {core_sum}",
                    "hint": f"{om['place']} 출신으로 [{smeta['title']}] 세부 전공을 밟아 — {am['hint']}",
                    "origin_id": oid,
                    "career": smeta["career"],
                    "specialty_id": sid,
                    "archetype": arch,
                    "group": "B",
                })

    # ── Group C : 4종 (출신 초월 신화 엔딩) ──
    mythics = [
        {
            "id": "myth_cosmos_promise",
            "title": "🌠 쌍성의 약속 — 시간의 강 너머 두 이름이 나란히 빛나다",
            "archetype": "myth_cosmos_promise",
            "summary": "어린 날 맺은 두 사람의 백 년 약속과 우주의 이치를 향한 호기심이 하나가 되어 시간 너머 영원히 겹쳐진 신화",
        },
        {
            "id": "myth_phoenix_legend",
            "title": "🦅 불꽃에서 돌아온 전설 — 잿더미를 딛고 여든의 봉우리가 되다",
            "archetype": "myth_phoenix_legend",
            "summary": "서른아홉의 참혹한 화염 속에 몸을 던져 타인을 살린 영웅이 백발 여든의 세월을 이겨내며 살아있는 전설로 완성된 신화",
        },
        {
            "id": "myth_rival_crown",
            "title": "⚔️ 같은 하늘을 겨눈 두 별 — 경쟁을 넘어선 백 년의 완주",
            "archetype": "myth_rival_crown",
            "summary": "아홉 살 비 오는 날 처음 맞섰던 라이벌과 시대의 정점에서 다시 만나 서로의 삶을 완성해 준 뜨거운 쌍벽의 신화",
        },
        {
            "id": "myth_complete_archive",
            "title": "📖 백 년의 완전한 서사 — 한 점 후회 없는 인간성의 도서관",
            "archetype": "myth_complete_archive",
            "summary": "지성과 열정·공감과 근성을 모두 고르게 벼리며 회고록과 용서, 마지막 한 획까지 흐트러짐 없이 닫아낸 백 년의 걸작",
        },
    ]
    for mc in mythics:
        am = ARCHETYPE_META[mc["archetype"]]
        _register({
            "id": mc["id"],
            "title": mc["title"],
            "emoji": am["emoji"],
            "rarity": am["rarity"],
            "color": am["color"],
            "base_crystal": am["base_crystal"],
            "summary": mc["summary"],
            "hint": am["hint"],
            "origin_id": "myth",
            "career": "myth",
            "specialty_id": "",
            "archetype": mc["archetype"],
            "group": "C",
        })

    return catalog


ENDINGS: Dict[str, Dict[str, Any]] = _build_all_endings()


# ==========================================
# 5. 구 16종 세이브 데이터 무손실 마이그레이션
# ==========================================
LEGACY_ENDING_MAP: Dict[str, str] = {
    "hidden_star": "grp_a__scholar_home__scholar__hidden_star",
    "flame_39": "grp_a__orphanage__guardian__flame_39",
    "old_promise": "grp_a__orphanage__artist__old_promise",
    "redeemed_spring": "grp_a__fallen_house__artisan__redeemed_spring",
    "broken_crown": "grp_a__fallen_house__entrepreneur__broken_crown",
    "truth_keeper": "spec__scholar_home__grd_press__truth_keeper",
    "master_craft": "spec__artisan_shop__artn_clock__master_craft",
    "unheard_genius": "spec__orphanage__artist_paint__unheard_genius",
    "healer_hands": "spec__mountain_clinic__scholar_healer__healer_hands",
    "masked_shadow": "spec__fallen_house__shd_broker__masked_shadow",
    "empire_builder": "spec__fallen_house__ent_trade__empire_builder",
    "horizon_writer": "grp_a__orphanage__wnd_photo__horizon_writer",
    "noodle_universe": "spec__noodle_shop__artn_noodle__noodle_universe",
    "teacher_bridge": "spec__scholar_home__scholar_archive__teacher_bridge",
    "village_lantern": "spec__noodle_shop__artn_craft__village_lantern",
    "quiet_miracle": "spec__artisan_shop__artn_craft__quiet_miracle",
}


def migrate_legacy_ending_id(
    old_eid: str,
    history_items: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    eid = str(old_eid or "").strip()
    if not eid:
        return None
    if eid in ENDINGS:
        return eid
    if eid not in LEGACY_ENDING_MAP:
        return None

    # 최근 전기 기록에 남아있는 origin_id / career / specialty 정보로 가장 정확한 새 ID 추론
    if isinstance(history_items, list):
        for h in history_items:
            if not isinstance(h, dict) or str(h.get("ending_id") or "") != eid:
                continue
            oid = str(h.get("origin_id") or "orphanage")
            if oid not in ORIGIN_MOTIFS:
                oid = "orphanage"
            cid = str(h.get("career") or "artisan")
            if cid not in ALL_CAREERS:
                cid = "artisan"

            if eid in ("hidden_star", "flame_39", "old_promise", "redeemed_spring", "broken_crown"):
                target_cid = cid if (eid in ("flame_39", "redeemed_spring", "broken_crown") or cid != "shadow") else "artisan"
                cand = f"grp_a__{oid}__{target_cid}__{eid}"
                if cand in ENDINGS:
                    return cand

            if eid == "horizon_writer":
                if cid == "wanderer":
                    cand = f"grp_a__{oid}__wnd_photo__horizon_writer"
                elif cid != "shadow":
                    cand = f"grp_a__{oid}__{cid}__horizon_writer"
                else:
                    cand = f"grp_a__{oid}__wnd_photo__horizon_writer"
                if cand in ENDINGS:
                    return cand

            # Group B 전문직 매칭
            spec_lbl = str(h.get("specialty_label") or "")
            matched_sid = ""
            for s_id, s_meta in SPECIALTY_CATALOG.items():
                if s_meta["title"] == spec_lbl:
                    matched_sid = s_id
                    break
            if not matched_sid:
                matched_sid = ol_narratives.resolve_specialty_id({"origin_id": oid, "career": cid, "flags": []})
            cand_b = f"spec__{oid}__{matched_sid}__{eid}"
            if cand_b in ENDINGS:
                return cand_b

    return LEGACY_ENDING_MAP[eid]


# ==========================================
# 6. 1,000종 엔딩 인과 판정기 (100% 도달 가능 · 우선순위 검증 완료)
# ==========================================
UNHEARD_SPECS = {"artist_paint", "artist_music", "artist_write", "scholar_cosmos", "scholar_archive", "artn_clock", "wnd_photo"}
HEALER_SPECS = {"scholar_healer", "artn_tea", "wnd_relief"}
TRUTH_SPECS = {"scholar_archive", "grd_press", "grd_detective", "grd_advocate", "wnd_photo"}
MASTER_EXCLUDED = {"ent_tech", "ent_trade", "wnd_photo"}


def _si(v: Any, d: int = 0) -> int:
    try:
        return int(float(v)) if v is not None and not isinstance(v, bool) else d
    except Exception:
        return d


def resolve_ending(life: Dict[str, Any], forced_flame: bool = False) -> Tuple[str, Dict[str, Any]]:
    flags = set(life.get("flags") or [])
    stats = life.get("stats") or {}
    origin_id = str(life.get("origin_id") or "orphanage")
    if origin_id not in ORIGIN_MOTIFS:
        origin_id = "orphanage"

    career = str(life.get("career") or "artisan")
    if career not in ALL_CAREERS:
        career = "artisan"

    sid = ol_narratives.resolve_specialty_id(life, career)
    age = _si(life.get("age"), 78)

    intel = _si(stats.get("intellect"), 0)
    passion = _si(stats.get("passion"), 0)
    empathy = _si(stats.get("empathy"), 0)
    grit = _si(stats.get("grit"), 0)
    wealth = _si(stats.get("wealth"), 0)

    partner = life.get("partner_name")
    comp = life.get("companion_name")
    comp_promise_alive = (
        career != "shadow"
        and "corrupted" not in flags
        and "partner_strained" not in flags
        and (
            "old_promise_kept" in flags
            or ("comp_promised" in flags and partner and partner == comp)
        )
    )

    eid: str = ""

    # ── 1) 최우선: 39세 강제 불꽃 희생 (Group A flame_39) ──
    if forced_flame:
        eid = f"grp_a__{origin_id}__{career}__flame_39"

    # ── 2) Group C : 4대 신화 엔딩 ──
    elif (
        career != "shadow"
        and "corrupted" not in flags
        and "cosmos_finale" in flags
        and "time_transcended" in flags
        and intel >= 56
        and empathy >= 56
        and comp_promise_alive
        and ("family_warm" in flags or "family_reconciled" in flags or empathy >= 64)
    ):
        eid = "myth_cosmos_promise"

    elif (
        not forced_flame
        and "corrupted" not in flags
        and "scarred_hero" in flags
        and ("redeemed" in flags or "masterwork_kept" in flags)
        and age >= 80
        and grit >= 45
    ):
        eid = "myth_phoenix_legend"

    elif (
        career != "shadow"
        and "corrupted" not in flags
        and "comp_rival" in flags
        and "partner_strained" not in flags
        and max(intel, passion, grit, wealth) >= 68
        and (
            "old_promise_kept" in flags
            or "peaceful_closure" in flags
            or ("comp_promised" in flags and partner and partner == comp)
        )
    ):
        eid = "myth_rival_crown"

    elif (
        career != "shadow"
        and "corrupted" not in flags
        and "redeemed" not in flags
        and "honest_path" in flags
        and "memoir_written" in flags
        and "reconciled_self" in flags
        and "final_work_done" in flags
        and min(intel, passion, empathy, grit) >= 42
    ):
        eid = "myth_complete_archive"

    # ── 3) Group A 코어 아키타입 (히든 별·오래된 약속·회개·타락·고독정상) ──
    elif (
        career != "shadow"
        and "corrupted" not in flags
        and "cosmos_finale" in flags
        and "time_transcended" in flags
        and intel >= 56
        and empathy >= 50
    ):
        eid = f"grp_a__{origin_id}__{career}__hidden_star"

    elif comp_promise_alive:
        eid = f"grp_a__{origin_id}__{career}__old_promise"

    elif "redeemed" in flags:
        eid = f"grp_a__{origin_id}__{career}__redeemed_spring"

    elif (
        ("corrupted" in flags and "redeemed" not in flags and "shadow_masked" not in flags)
        or "shadow_fall" in flags
    ):
        # 단, shadow가 정체 숨기기(b14_hide -> shadow_masked)를 택한 경우 masked_shadow로 감
        eid = f"grp_a__{origin_id}__{career}__broken_crown"

    # ── 4) 그림자(Shadow) 3종 특화 엔딩 (Group B) ──
    elif career == "shadow":
        shd_sid = sid if sid in ("shd_broker", "shd_launder") else "shd_broker"
        if "shadow_whistler" in flags:
            eid = f"spec__{origin_id}__{shd_sid}__shadow_whistle"
        elif "shadow_benefactor" in flags:
            eid = f"spec__{origin_id}__{shd_sid}__shadow_phantom"
        elif "shadow_masked" in flags or "corrupted" in flags or "former_shadow" not in flags:
            eid = f"spec__{origin_id}__{shd_sid}__masked_shadow"
        else:
            # former_shadow로서 b14_hide/b14_greed_clash/b14_redeem을 거치지 않고 나온 예외 케이스 방지
            eid = f"spec__{origin_id}__{shd_sid}__masked_shadow"

    elif (
        "has_partner" not in flags
        and "lone_summit_vow" in flags
    ):
        eid = f"grp_a__{origin_id}__{career}__lonely_summit"

    # ── 5) 늦깎이/방랑 지평선 (Group A horizon_writer) ──
    elif "late_explorer" in flags:
        if career == "wanderer":
            wsid = sid if sid in ("wnd_photo", "wnd_relief") else "wnd_photo"
            eid = f"grp_a__{origin_id}__{wsid}__horizon_writer"
        else:
            eid = f"grp_a__{origin_id}__{career}__horizon_writer"

    # ── 6) Group B 18개 비그림자 전공별 특화 아키타입 판정 ──
    else:
        arch = "quiet_miracle"
        want_unheard = (
            sid in UNHEARD_SPECS
            and passion >= 40
            and max(passion, intel) >= 48
            and wealth <= 44
            and "empire_ambition" not in flags
            and "teacher_path" not in flags
            and "protect_local" not in flags
            and "truth_confirmed" not in flags
            and ("final_work_done" in flags or ("pure_art" in flags and "peak_craft_vow" not in flags))
        )
        want_master = (
            sid not in MASTER_EXCLUDED
            and "masterwork_kept" in flags
            and max(intel, passion, grit) >= 62
            and not want_unheard
            and not ("empire_ambition" in flags and sid in EMPIRE_ELIGIBLE_SPECIALTIES and wealth >= 46)
        )

        if sid == "artn_noodle" and "noodle_revival" in flags and empathy >= 42 and "teacher_path" not in flags and "masterwork_kept" not in flags:
            arch = "noodle_universe"
        elif sid in HEALER_SPECS and "healer_oath" in flags and empathy >= 44 and "teacher_path" not in flags and not want_master and "empire_ambition" not in flags:
            arch = "healer_hands"
        elif sid in TRUTH_SPECS and (
            "truth_confirmed" in flags
            or (
                "whistleblower" in flags
                and "teacher_path" not in flags
                and "masterwork_kept" not in flags
                and "protect_local" not in flags
                and "empire_ambition" not in flags
                and not want_unheard
            )
            or (
                career == "guardian"
                and "honest_path" in flags
                and empathy >= 46
                and "patient_strategy" not in flags
                and "teacher_path" not in flags
                and "masterwork_kept" not in flags
                and "protect_local" not in flags
                and "empire_ambition" not in flags
                and "has_partner" not in flags
            )
        ):
            arch = "truth_keeper"
        elif want_unheard:
            arch = "unheard_genius"
        elif want_master:
            arch = "master_craft"
        elif (
            sid in EMPIRE_ELIGIBLE_SPECIALTIES
            and (
                ("empire_ambition" in flags and wealth >= 46)
                or (
                    career == "entrepreneur"
                    and wealth >= 56
                    and "philanthropy" not in flags
                    and "protect_local" not in flags
                    and "masterwork_kept" not in flags
                    and "teacher_path" not in flags
                )
                or (
                    wealth >= 68
                    and "philanthropy" not in flags
                    and "protect_local" not in flags
                    and "masterwork_kept" not in flags
                    and "teacher_path" not in flags
                )
            )
        ):
            arch = "empire_builder"
        elif ("mentor_heir" in flags or "teacher_path" in flags) and empathy >= 46 and "empire_ambition" not in flags:
            arch = "teacher_bridge"
        elif ("protect_local" in flags or "philanthropy" in flags or "community_care" in flags) and empathy >= 46 and "empire_ambition" not in flags:
            arch = "village_lantern"
        elif (
            "has_partner" in flags
            and "partner_strained" not in flags
            and ("family_warm" in flags or "family_reconciled" in flags or empathy >= 46)
        ):
            arch = "family_hearth"
        else:
            arch = "quiet_miracle"

        # 안전 가드: 해당 specialty가 지원하는 아키타입인지 검증
        supported = SPEC_ARCHETYPES.get(sid, [])
        if arch not in supported:
            arch = "quiet_miracle" if "quiet_miracle" in supported else (supported[0] if supported else "quiet_miracle")

        cand_id = f"spec__{origin_id}__{sid}__{arch}"
        if cand_id in ENDINGS:
            eid = cand_id
        else:
            eid = f"spec__{origin_id}__{sid}__quiet_miracle"

    emeta = ENDINGS[eid]
    v = ol_narratives.fmt_life_vars(life)
    epilogue = build_rich_ending_epilogue(life, eid, emeta, v)

    rarity = emeta["rarity"]
    rarity_bonus = (
        320 if rarity == "신화"
        else 250 if rarity == "히든"
        else 150 if rarity == "전설"
        else 80 if rarity == "희귀"
        else 40
    )
    score = int((intel + passion + empathy + grit + wealth) * 4 + age * 8 + rarity_bonus)
    return eid, {"meta": emeta, "epilogue": epilogue, "score": score}


# ==========================================
# 7. 맞춤형 다문단 엔딩 전기 생성기 (인과·출신·전공·인연 완벽 반영)
# ==========================================
def build_rich_ending_epilogue(
    life: Dict[str, Any],
    eid: str,
    emeta: Dict[str, Any],
    v: Dict[str, Any],
) -> str:
    flags = set(life.get("flags") or [])
    career = str(life.get("career") or "artisan")
    oid = str(life.get("origin_id") or "orphanage")
    sid = v.get("specialty_id") or "artn_craft"
    arch = str(emeta.get("archetype") or "quiet_miracle")
    comp_rel = str(life.get("companion_rel") or "stranger")
    mentor_rel = str(life.get("mentor_rel") or "unknown")
    stayed_or_returned_home = (
        ("returned_home" in flags)
        or (
            "career_pivoted" not in flags
            and (
                (oid == "noodle_shop" and sid == "artn_noodle")
                or (oid == "mountain_clinic" and sid == "scholar_healer")
                or (oid == "artisan_shop" and sid == "artn_clock")
            )
        )
    )

    # 문단 1: 출신과 엔딩 핵심 서사
    if arch == "flame_39":
        p1 = (
            f"서른아홉 해, 너무나도 눈부셨기에 일찍 꺼져버린 불꽃. {v['name_eun']} 마지막 순간조차 피하지 않고 타오르는 불길과 잔해 속으로 손을 내밀었습니다. "
            f"{v['city']}의 **{v['origin_place']}**에서 보낸 여섯 살의 첫 기억과 **{v['item_short']}**{v['item_eul_s']} 품었던 작은 아이는, 마침내 생명을 건져낸 가장 뜨거운 이름으로 세상에 남았습니다."
        )
    elif arch == "hidden_star":
        p1 = (
            f"{v['age_sal']}의 맑은 새벽 은하수 아래, {v['name_eun']} 여섯 살 **{v['origin_place']}**에서 처음 올려다보았던 별빛을 손끝에 다시 안았습니다. "
            f"[{v['specialty']}]로서 걸어온 {v['years_since_19']}여 년의 탐구와 인간애는 시간의 경계를 넘어 후대 사람들의 어두운 밤길을 비추는 별이 되었습니다."
        )
    elif arch == "myth_cosmos_promise":
        p1 = (
            f"어린 시절 **{v['city']}**의 밤하늘 아래서 싹튼 우주에 대한 경이와, 열여덟 **{v['night_spot']}**에서 맺은 평생의 약속이 **{v['age_sal']}**의 새벽에 한 줄기 쌍성처럼 겹쳐졌습니다. "
            f"[{v['specialty']}]로서 걸어온 {v['name']}의 생애는 사랑과 통찰을 모두 품어낸 한 편의 신화가 되어 별들 사이로 걸어 나갔습니다."
        )
    elif arch == "myth_phoenix_legend":
        p1 = (
            f"서른아홉의 참혹한 불길 속에서 사람을 구하고 남은 깊은 상처를 안고도, {v['name_eun']} 무너지지 않고 **{v['age_sal']}**의 세월을 끝까지 걸어냈습니다. "
            f"잿더미에서 일어나 다시 [{v['specialty']}]의 길을 증명한 그의 이름은 시대가 꺾여도 다시 살아나는 살아있는 전설로 남았습니다."
        )
    elif arch == "myth_rival_crown":
        p1 = (
            f"아홉 살 **{v['hangout']}**에서 처음 승부를 겨루던 라이벌 **{v['comp']}**{ol_narratives.p_wa(v['comp'])}, 정상의 자리에서 마주한 **{v['age_sal']}**의 미소. "
            f"서로를 꺾기 위해서가 아니라 더 멀리 내달리기 위해 서로를 지켜보았던 두 사람의 세월은 시대의 쌍벽으로 길이 기억되었습니다."
        )
    elif arch == "myth_complete_archive":
        p1 = (
            f"여섯 살 **{v['origin_place']}**에서 시작된 한 사람의 백 년이 지성·열정·공감·근성 어느 하나 어그러짐 없이 가장 맑은 균형으로 닫혔습니다. "
            f"회고록의 마침표와 젊은 날을 향한 용서가 하나로 이어진 [{v['specialty']}] {v['name']}의 기록은 인간다움의 교과서가 되었습니다."
        )
    elif arch == "old_promise":
        p1 = (
            f"먼 우회와 거친 계절을 건너 마침내 나란히 노년을 맞은 **{v['name']}**{ol_narratives.p_wa(v['name'])} **{v['partner']}**. "
            f"열여덟 **{v['night_spot']}**의 차가운 바람 속에서 걸었던 약속은 백발이 성성한 **{v['age_sal']}**의 창가에서 가장 따스한 기적의 꽃을 피워 올렸습니다."
        )
    elif arch == "redeemed_spring":
        p1 = (
            f"젊은 날의 오만과 어두운 과거를 감추지 않고 쉰 살의 심판 앞에서 스스로 모든 것을 내려놓았던 날, {v['name']}의 인생에 진정한 두 번째 봄이 찾아왔습니다. "
            f"낮은 자리에서 이웃을 닦아주며 보낸 말년의 나날은 과거 어떤 화려한 성취보다도 눈부신 빛을 발했습니다."
        )
    elif arch == "broken_crown":
        p1 = (
            f"거짓으로 쌓아 올렸던 성벽은 세월의 바람 앞에 모래처럼 부서져 내렸습니다. "
            f"텅 빈 방 창가에서 어릴 적 간직했던 **{v['item_short']}**{v['item_eul_s']} 만지작거리던 **{v['age_sal']}**의 {v['name_eun']} 너무 늦어서야 지켜야 할 이름을 떠올렸습니다."
        )
    elif arch == "lonely_summit":
        p1 = (
            f"누구의 어깨에도 기대지 않고 홀로 버텨낸 **{v['age_sal']}**의 시간. **{v['workplace']}**에서 묵묵히 홀로 쌓아 올린 정상의 풍경은 서늘하지만 티끌 없이 투명했습니다. "
            f"스스로 선택한 고독 속에서 {v['name_eun']} 누구에게도 부끄럽지 않은 자신만의 산맥을 완성했습니다."
        )
    elif arch in ("masked_shadow", "shadow_whistle", "shadow_phantom"):
        name_rano = "이라는" if ol_narratives._jongseong_idx(v["name"]) != 0 else "라는"
        if arch == "shadow_whistle":
            p1 = (
                f"어둠의 심장부에서 스스로 조직의 원본 장부를 세상에 던졌던 밤, {v['name_eun']} 가면을 벗고 거짓의 판 자체를 무너뜨렸습니다. "
                f"비록 본명은 역사 한쪽에 작게 남았을지언정, 그 용기 덕분에 수많은 무고한 가족이 내일을 되찾았습니다."
            )
        elif arch == "shadow_phantom":
            p1 = (
                f"정체를 끝내 감춘 채 검은 자금의 물줄기를 골목 학교와 병원으로 돌려놓은 **{v['name']}**. "
                f"세상은 그의 진짜 이름을 알지 못했지만, 도움을 받은 골목 사람들의 감사한 마음만은 긴 세월을 건너 따뜻하게 살아 숨 쉬었습니다."
            )
        else:
            p1 = (
                f"수만 건의 거래와 가명을 쥐고도 정작 **{v['name']}**{name_rano} 본명을 불러줄 단 한 사람도 남기지 못한 삶. "
                f"도시의 어두운 유리창 뒤편에서 조용히 자취를 감춘 뒤에는 오직 전설처럼 떠도는 소문만이 남았습니다."
            )
    else:
        spec_phrase = SPEC_PHRASES.get(sid, SPEC_PHRASES["artn_craft"]).get(arch, ("삶의 완주", emeta["summary"]))[1]
        p1 = (
            f"{v['city']}의 **{v['origin_place']}**에서 {v['item_wa']} 함께 첫 발을 뗀 작은 아이는 어느덧 **{v['age_sal']}**의 노년을 맞은 **[{v['specialty']}]**{ol_narratives.p_i(v['specialty'])} 되었습니다. "
            f"{spec_phrase}"
        )

    # 문단 2: 일터·전공 여정 & 핵심 플래그 반영
    p2_bits: List[str] = []
    if stayed_or_returned_home:
        p2_bits.append(f"돌고 돌아 지켜낸 고향 **{v['city']}**의 **{v['workplace']}**에는 여전히 정든 **{v['tool']}**{ol_narratives.p_wa(v['tool'])} 첫날의 온기가 살아 있습니다.")
    elif arch != "flame_39" and career != "shadow":
        p2_bits.append(f"수십 해를 동고동락한 **{v['workplace']}**의 **{v['tool']}** 위에는 헛되지 않았던 땀방울이 고스란히 배어 있었습니다.")

    if "scarred_hero" in flags and arch not in ("flame_39", "myth_phoenix_legend"):
        p2_bits.append("서른아홉의 화염에서 타인을 살리고 손등에 새긴 화상 흉터는 평생 무엇을 소중히 여겼는지 증명해 주는 훈장이 되었습니다.")
    if "former_shadow" in flags and career == "shadow" and arch == "redeemed_spring":
        p2_bits.append("서른 살 어둠에서 발을 뺀 이후 기나긴 시련 끝에서도 끝내 인간적인 촛불을 꺼뜨리지 않았습니다.")
    if "reconciled_self" in flags:
        p2_bits.append("칠순의 문턱에서 서툴고 외로웠던 어린 날의 자신마저 껴안고 난 뒤, 마음속 모든 멍에가 가벼이 풀려나갔습니다.")
    elif "grateful_elder" in flags:
        p2_bits.append("아프고 흔들렸던 시절마저 나를 빚어낸 선물이었다며 웃던 황혼의 표정은 맑은 하늘처럼 평온했습니다.")

    p2 = " ".join(p2_bits)

    # 문단 3: 동반자 / 스승 인연 회수
    p3_bits: List[str] = []
    if arch == "old_promise" or arch == "myth_cosmos_promise":
        pass  # 이미 p1에서 중심 서사로 풀림
    elif "has_partner" in flags and life.get("partner_name"):
        if "partner_strained" in flags and arch == "broken_crown":
            p3_bits.append(f"끝내 돌보지 못했던 **{v['partner']}**{v['partner_wa_s']}의 차가운 식탁과 침묵이 공허한 방 안에 무겁게 가라앉았습니다.")
        else:
            p3_bits.append(f"거친 세월의 폭풍 속에서도 한결같이 곁의 등불을 켜준 동반자 **{v['partner']}**의 온기가 마지막 날까지 손을 감싸 주었습니다.")
    elif comp_rel in ("reunited", "parted_warm") or "peaceful_closure" in flags:
        p3_bits.append(f"각자의 길로 걸어가면서도 어린 날 **{v['hangout']}**에서 빗속을 뛰던 **{v['comp']}**의 웃음소리는 마음 한구석 다정한 볕으로 남았습니다.")

    if "mentor_heir" in flags:
        p3_bits.append(f"스승 **{v['mentor']}**에게서 물려받은 나무 상자와 가르침은 이제 젊은 제자들의 손에서 새 숨을 얻었습니다.")
    elif mentor_rel in ("loyal", "rebel") and "mentor_passed" not in flags and career != "shadow":
        p3_bits.append(f"열여섯의 **{v['mentor_place']}**에서 **{v['mentor']}**{v['mentor_i_s']} 건네주었던 한 마디가 평생을 바로 세우는 나침반이 되어 주었습니다.")

    p3 = " ".join(p3_bits)

    # 문단 4: 결정적 전환점 요약 & 여운
    tps = [str(t) for t in (life.get("turning_points") or []) if t]
    name_rano = "이라는" if ol_narratives._jongseong_idx(v["name"]) != 0 else "라는"
    if len(tps) >= 3:
        last_tp = tps[-1].split(":", 1)[-1].strip().rstrip(".")
        p4 = (
            f"긴 세월의 갈피마다 남은 기억 가운데서도 **「{last_tp}」**{ol_narratives.p_ro(last_tp)} 새겨진 대목은, "
            f"{v['name']}{name_rano} 한 권의 책을 가장 선명히 빛내며 고요히 다음 세대의 이야기 속으로 이어졌습니다."
        )
    else:
        p4 = f"{v['age_sal']}의 마침표 앞에서도 지나온 모든 걸음이 헛되지 않았다는 고요한 믿음이 {v['city']}의 바람결처럼 잔잔히 퍼져 나갔습니다."

    paras = [p for p in (p1, p2, p3, p4) if p.strip()]
    return "\n\n".join(paras)
