"""Korean taxonomic labels, family biology metadata, and EN/Latin->KO fish translators."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

BioTuple = Tuple[str, str, Tuple[float, float], Tuple[float, float], int, str, str, str, str, str]

ORDER_BIOLOGY: Dict[int, BioTuple] = {
    49216: ("river", "중류 자갈 여울", (8.0, 26.0), (0.011, 3.01), 1, "day", "clear", "dough", "🐟", "잉어목 어류"),
    49175: ("river", "대하천 본류", (12.0, 48.0), (0.012, 3.02), 2, "night", "rain", "worm", "🐟", "메기목 어류"),
    47388: ("river", "대하천 본류", (5.0, 22.0), (0.014, 3.01), 2, "day", "clear", "dough", "🐠", "카라신목 어류"),
    1303736: ("lake", "열대·아열대 대호", (10.0, 36.0), (0.020, 3.02), 2, "day", "clear", "worm", "🐠", "시클리드목 어류"),
    49333: ("lake", "열대·아열대 대호", (3.5, 9.5), (0.012, 3.00), 2, "day", "rain", "dough", "🐠", "송사리목 어류"),
    47521: ("river", "상류 1급수 계곡", (24.0, 78.0), (0.012, 3.02), 3, "day", "clear", "lure", "🐟", "연어목 어류"),
    49240: ("river", "대하천 본류", (22.0, 75.0), (0.010, 3.00), 3, "night", "fog", "worm", "🐉", "골설어목 어류"),
    49824: ("lake", "깊은 심수층", (70.0, 210.0), (0.008, 3.02), 4, "all", "storm", "shrimp", "🦈", "철갑상어목 어류"),
    1303725: ("sea", "연안 갯바위·내만", (5.5, 18.0), (0.011, 3.00), 1, "all", "clear", "worm", "🐟", "망둑어목 어류"),
    47233: ("sea", "연안 갯바위·내만", (16.0, 48.0), (0.016, 3.02), 2, "day", "clear", "shrimp", "🐟", "농어목 어류"),
    1303727: ("sea", "원양·회유 해역", (24.0, 76.0), (0.014, 3.01), 2, "day", "clear", "lure", "🐟", "전갱이목 어류"),
    1303751: ("sea", "대륙붕·외해", (18.0, 52.0), (0.013, 3.00), 2, "night", "all", "worm", "🐟", "가자미아목 어류"),
    1555654: ("sea", "산호초·열대 해역", (14.0, 46.0), (0.017, 3.01), 2, "day", "clear", "shrimp", "🐠", "놀래기목 어류"),
    47314: ("sea", "연안 갯바위·내만", (34.0, 110.0), (0.0022, 3.01), 3, "night", "fog", "shrimp", "🐍", "뱀장어목 어류"),
    47245: ("sea", "산호초·열대 해역", (10.0, 32.0), (0.005, 2.95), 2, "day", "clear", "dough", "🐠", "실고기목 어류"),
    63741: ("sea", "심해·해구", (26.0, 82.0), (0.009, 3.01), 3, "night", "fog", "glow", "💠", "대구목 어류"),
    47391: ("sea", "심해·해구", (14.0, 48.0), (0.006, 3.00), 3, "night", "fog", "glow", "💠", "첨치목 어류"),
    61542: ("sea", "심해·해구", (14.0, 46.0), (0.022, 2.98), 4, "night", "fog", "glow", "🐡", "아귀목 어류"),
    49409: ("sea", "심해·해구", (18.0, 58.0), (0.008, 3.01), 3, "night", "fog", "glow", "💠", "홍메치목 어류"),
    85530: ("sea", "심해·해구", (6.0, 18.0), (0.011, 3.02), 3, "night", "fog", "glow", "💠", "샛비늘치목 어류"),
    49627: ("sea", "심해·해구", (16.0, 46.0), (0.020, 3.01), 3, "night", "fog", "glow", "🐠", "금눈돔목 어류"),
    47177: ("sea", "산호초·열대 해역", (16.0, 48.0), (0.025, 3.00), 2, "day", "clear", "shrimp", "🐡", "복어목 어류"),
    49235: ("sea", "대륙붕·외해", (12.0, 30.0), (0.010, 3.02), 1, "day", "clear", "dough", "🐟", "청어목 어류"),
    51485: ("sea", "원양·회유 해역", (18.0, 48.0), (0.006, 3.02), 2, "day", "clear", "dough", "🐟", "동갈치목 어류"),
    85506: ("sea", "연안 갯바위·내만", (8.0, 22.0), (0.009, 3.00), 2, "day", "clear", "dough", "🐟", "색줄멸목 어류"),
    85529: ("river", "강·바다 기수역", (22.0, 62.0), (0.014, 3.00), 2, "day", "clear", "dough", "🐟", "숭어목 어류"),
    1303726: ("sea", "산호초·열대 해역", (16.0, 48.0), (0.022, 3.01), 2, "day", "clear", "shrimp", "🐠", "양쥐돔목 어류"),
    1303739: ("sea", "원양·회유 해역", (34.0, 115.0), (0.013, 3.02), 3, "day", "clear", "lure", "🐟", "고등어목 어류"),
    1303737: ("sea", "연안 갯바위·내만", (5.0, 16.0), (0.011, 3.00), 2, "day", "clear", "worm", "🐠", "청베도라치목 어류"),
    1303731: ("sea", "연안 갯바위·내만", (18.0, 52.0), (0.018, 3.02), 2, "day", "clear", "shrimp", "🐟", "검정우럭목 어류"),
    1303732: ("sea", "심해·해구", (16.0, 44.0), (0.016, 3.01), 3, "night", "fog", "glow", "💠", "반딧불게르치목 어류"),
    1303733: ("sea", "심해·해구", (24.0, 72.0), (0.011, 3.00), 4, "night", "fog", "glow", "💠", "민머리치목 어류"),
    551307: ("sea", "원양·회유 해역", (65.0, 190.0), (0.010, 3.02), 4, "night", "storm", "lure", "🦈", "상어상목 어류"),
    448201: ("sea", "대륙붕·외해", (42.0, 125.0), (0.018, 2.93), 3, "all", "all", "shrimp", "🦅", "가오리상목 어류"),
    47273: ("sea", "대륙붕·외해", (55.0, 160.0), (0.012, 3.00), 3, "all", "all", "shrimp", "🦈", "연골어류"),
}

CURATED_MISSING_FAMILIES: Dict[str, BioTuple] = {
    "Acestrorhamphidae": ("river", "대하천 본류", (4.5, 14.0), (0.013, 3.00), 2, "day", "clear", "dough", "🐠", "남미테트라과"),
    "Stevardiidae": ("river", "대하천 본류", (4.0, 11.0), (0.013, 3.00), 2, "day", "clear", "dough", "🐠", "스테바르디아테트라과"),
    "Heptapteridae": ("river", "중류 자갈 여울", (8.0, 28.0), (0.011, 3.01), 2, "night", "rain", "worm", "🐟", "세수염메기과"),
    "Psychrolutidae": ("sea", "심해·해구", (18.0, 56.0), (0.020, 3.00), 3, "night", "fog", "glow", "🐡", "둑중개아과(물수배기과)"),
    "Gobiesocidae": ("sea", "연안 갯바위·내만", (4.0, 13.0), (0.012, 3.00), 2, "day", "clear", "worm", "🐟", "학치과"),
    "Ariidae": ("sea", "강·바다 기수역", (24.0, 74.0), (0.013, 3.02), 2, "night", "rain", "shrimp", "🐟", "바다동자개과"),
    "Gastromyzontidae": ("river", "상류 1급수 계곡", (4.5, 11.0), (0.012, 3.00), 2, "day", "clear", "worm", "🐟", "계류흡반미꾸리과"),
    "Bythitidae": ("sea", "심해·해구", (14.0, 48.0), (0.007, 3.00), 3, "night", "fog", "glow", "💠", "태생브로툴라과"),
    "Auchenipteridae": ("river", "대하천 본류", (10.0, 34.0), (0.014, 3.01), 2, "night", "rain", "worm", "🐟", "유목메기과"),
    "Crenuchidae": ("river", "상류 1급수 계곡", (4.5, 10.5), (0.012, 3.00), 2, "day", "clear", "worm", "🐠", "남미다터테트라과"),
    "Dinematichthyidae": ("sea", "산호초·열대 해역", (5.5, 14.0), (0.008, 3.00), 2, "night", "clear", "shrimp", "🐠", "산호브로툴라과"),
    "Distichodontidae": ("river", "대하천 본류", (8.0, 42.0), (0.014, 3.01), 3, "day", "clear", "worm", "🐠", "디스티코돈과"),
    "Amphiliidae": ("river", "상류 1급수 계곡", (6.0, 18.0), (0.010, 3.00), 2, "night", "clear", "worm", "🐟", "미꾸리메기과"),
    "Alepocephalidae": ("sea", "심해·해구", (26.0, 76.0), (0.010, 3.01), 4, "night", "fog", "glow", "💠", "민머리치과"),
    "Dorosomatidae": ("sea", "연안 갯바위·내만", (13.0, 34.0), (0.011, 3.02), 1, "day", "clear", "dough", "🐟", "전어과"),
    "Myxinidae": ("sea", "심해·해구", (28.0, 78.0), (0.0022, 3.00), 3, "night", "fog", "worm", "🐍", "먹장어(꾀장어)과"),
    "Astroblepidae": ("river", "상류 1급수 계곡", (7.0, 22.0), (0.015, 3.00), 3, "night", "rain", "worm", "🐟", "안데스빨판입메기과"),
    "Procatopodidae": ("river", "대하천 본류", (3.0, 7.0), (0.011, 2.98), 2, "day", "clear", "dough", "🐠", "아프리카램프아이과"),
    "Melamphaidae": ("sea", "심해·해구", (6.0, 18.0), (0.016, 3.00), 3, "night", "fog", "glow", "💠", "큰비늘심해어과"),
    "Lebiasinidae": ("river", "대하천 본류", (3.5, 11.0), (0.012, 3.00), 2, "day", "clear", "dough", "🐠", "연필고기과"),
    "Oneirodidae": ("sea", "심해·해구", (8.0, 26.0), (0.025, 2.98), 4, "night", "storm", "glow", "💠", "초롱심해아귀과"),
    "Paralepididae": ("sea", "심해·해구", (18.0, 56.0), (0.004, 3.00), 3, "night", "fog", "glow", "💠", "꼬치매퉁이과"),
    "Claroteidae": ("river", "대하천 본류", (18.0, 64.0), (0.013, 3.02), 3, "night", "rain", "worm", "🐟", "클라로테스메기과"),
    "Zenarchopteridae": ("river", "강·바다 기수역", (7.0, 19.0), (0.005, 3.00), 2, "day", "clear", "dough", "🐟", "태생학꽁치과"),
    "Sternopygidae": ("river", "대하천 본류", (18.0, 52.0), (0.004, 3.00), 3, "night", "fog", "glow", "⚡", "유리칼고기과"),
    "Pseudopimelodidae": ("river", "중류 자갈 여울", (7.0, 26.0), (0.016, 3.02), 2, "night", "rain", "worm", "🐟", "꿀벌메기과"),
    "Akysidae": ("river", "중류 자갈 여울", (4.0, 12.0), (0.013, 3.00), 2, "night", "rain", "worm", "🐟", "계류메기과"),
    "Butidae": ("river", "강·바다 기수역", (10.0, 32.0), (0.015, 3.02), 2, "night", "all", "worm", "🐟", "남방구굴무치과"),
    "Synaphobranchidae": ("sea", "심해·해구", (32.0, 105.0), (0.0022, 3.01), 4, "night", "fog", "glow", "🐍", "심해긴목장어과"),
    "Ambassidae": ("river", "강·바다 기수역", (5.0, 14.0), (0.015, 3.00), 2, "day", "clear", "dough", "🐠", "유리농어과"),
    "Ehiravidae": ("river", "대하천 본류", (4.0, 11.0), (0.009, 3.00), 1, "day", "clear", "dough", "🐟", "강멸치과"),
    "Plesiopidae": ("sea", "산호초·열대 해역", (6.0, 19.0), (0.017, 3.00), 2, "night", "clear", "shrimp", "🐠", "동글머리치과"),
    "Aspredinidae": ("river", "대하천 본류", (6.0, 24.0), (0.012, 3.00), 2, "night", "rain", "worm", "🐟", "반조메기과"),
    "Epigonidae": ("sea", "심해·해구", (12.0, 38.0), (0.016, 3.01), 3, "night", "fog", "glow", "💠", "심해동갈돔과"),
    "Dactyloscopidae": ("sea", "연안 갯바위·내만", (6.0, 16.0), (0.012, 3.00), 2, "day", "clear", "worm", "🐟", "모래통구멍과"),
    "Harpagiferidae": ("sea", "심해·해구", (9.0, 26.0), (0.016, 3.00), 3, "all", "fog", "lure", "❄️", "남극약탈어과"),
    "Nettastomatidae": ("sea", "심해·해구", (38.0, 108.0), (0.0018, 3.00), 3, "night", "fog", "glow", "🐍", "오리주둥이장어과"),
    "Cepolidae": ("sea", "대륙붕·외해", (18.0, 54.0), (0.005, 3.00), 2, "night", "clear", "worm", "🐠", "붉은띠치과"),
    "Aphaniidae": ("lake", "수초 연안", (3.5, 7.5), (0.013, 3.00), 2, "day", "clear", "dough", "🐠", "아파니우스킬리과"),
    "Cyclopsettidae": ("sea", "대륙붕·외해", (14.0, 38.0), (0.014, 3.00), 2, "night", "all", "worm", "🐟", "모래넙치과"),
    "Cetopsidae": ("river", "대하천 본류", (10.0, 32.0), (0.015, 3.01), 3, "night", "rain", "worm", "🐟", "고래메기과"),
    "Liopropomatidae": ("sea", "산호초·열대 해역", (8.0, 26.0), (0.017, 3.01), 3, "night", "clear", "shrimp", "🐠", "리오프로포마바리과"),
    "Platytroctidae": ("sea", "심해·해구", (14.0, 34.0), (0.011, 3.00), 4, "night", "fog", "glow", "💠", "발광어깨치과"),
    "Pristigasteridae": ("sea", "연안 갯바위·내만", (16.0, 44.0), (0.011, 3.02), 2, "day", "clear", "shrimp", "🐟", "준치과"),
    "Iguanodectidae": ("river", "대하천 본류", (5.0, 14.0), (0.011, 3.00), 2, "day", "clear", "dough", "🐠", "이구아노덱테스과"),
    "Carapidae": ("sea", "산호초·열대 해역", (10.0, 30.0), (0.003, 2.98), 3, "night", "clear", "worm", "🐍", "숨이고기과"),
    "Hypopomidae": ("river", "대하천 본류", (12.0, 36.0), (0.004, 3.00), 3, "night", "fog", "glow", "⚡", "짧은입칼고기과"),
    "Atherinomoridae": ("sea", "연안 갯바위·내만", (6.0, 15.0), (0.009, 3.00), 1, "day", "clear", "dough", "🐟", "열대색줄멸과"),
    "Badidae": ("river", "중류 자갈 여울", (3.5, 8.0), (0.015, 3.00), 2, "day", "clear", "worm", "🐠", "바디스과"),
    "Achiridae": ("river", "강·바다 기수역", (10.0, 28.0), (0.016, 3.00), 2, "night", "all", "worm", "🐟", "아메리카서대과"),
    "Schilbeidae": ("river", "대하천 본류", (14.0, 48.0), (0.011, 3.01), 2, "night", "rain", "worm", "🐟", "유리메기과"),
    "Grammistidae": ("sea", "산호초·열대 해역", (10.0, 32.0), (0.019, 3.01), 3, "night", "clear", "shrimp", "🐠", "비누고기과"),
    "Craterocephalidae": ("lake", "수초 연안", (5.0, 11.0), (0.010, 3.00), 2, "day", "clear", "dough", "🐟", "은줄멸아과"),
    "Hemiodontidae": ("river", "대하천 본류", (12.0, 32.0), (0.012, 3.01), 2, "day", "clear", "dough", "🐟", "반이빨카라신과"),
    "Trachinotidae": ("sea", "원양·회유 해역", (28.0, 82.0), (0.019, 3.02), 3, "day", "clear", "lure", "🐟", "병어전갱이과"),
    "Chaunacidae": ("sea", "심해·해구", (14.0, 36.0), (0.026, 2.98), 4, "night", "fog", "glow", "🐡", "점박이아귀과"),
    "Ipnopidae": ("sea", "심해·해구", (14.0, 36.0), (0.007, 3.00), 4, "night", "fog", "glow", "💠", "심해세발치과"),
    "Kneriidae": ("river", "상류 1급수 계곡", (5.0, 15.0), (0.010, 3.00), 2, "day", "clear", "worm", "🐟", "크네리아과"),
    "Psilorhynchidae": ("river", "상류 1급수 계곡", (5.0, 12.0), (0.011, 3.00), 2, "day", "clear", "worm", "🐟", "산악잉어과"),
    "Latridae": ("sea", "연안 갯바위·내만", (26.0, 74.0), (0.017, 3.02), 3, "day", "clear", "shrimp", "🐟", "나팔돔과"),
    "Parodontidae": ("river", "상류 1급수 계곡", (7.0, 17.0), (0.012, 3.00), 2, "day", "clear", "dough", "🐟", "파로돈카라신과"),
    "Narcinidae": ("sea", "대륙붕·외해", (26.0, 68.0), (0.022, 2.94), 3, "night", "fog", "shrimp", "⚡", "시끈가오리과"),
    "Latilidae": ("sea", "심해·해구", (24.0, 68.0), (0.014, 3.02), 3, "day", "clear", "shrimp", "🐠", "심해옥돔과"),
    "Alosidae": ("sea", "원양·회유 해역", (20.0, 56.0), (0.012, 3.02), 2, "day", "clear", "lure", "🐟", "청어전어과"),
    "Taeniopsettidae": ("sea", "대륙붕·외해", (14.0, 36.0), (0.014, 3.00), 3, "night", "fog", "worm", "🐟", "테니오프세타넙치과"),
    "Lepidarchidae": ("river", "대하천 본류", (3.0, 6.5), (0.012, 3.00), 3, "day", "clear", "dough", "🐠", "레피다르케스카라신과"),
    "Otodontidae": ("sea", "원양·회유 해역", (240.0, 1100.0), (0.014, 3.04), 5, "night", "storm", "golden", "🦈", "오토두스상어과"),
    "Pinguipedidae": ("sea", "연안 갯바위·내만", (14.0, 38.0), (0.014, 3.02), 2, "day", "clear", "worm", "🐟", "양동미리과"),
    "Leiognathidae": ("sea", "연안 갯바위·내만", (9.0, 22.0), (0.019, 3.00), 1, "day", "clear", "worm", "🐟", "주둥치과"),
    "Agonidae": ("sea", "대륙붕·외해", (12.0, 32.0), (0.010, 3.00), 2, "night", "fog", "worm", "🐟", "날개줄고기과"),
    "Plotosidae": ("sea", "연안 갯바위·내만", (20.0, 62.0), (0.010, 3.02), 2, "night", "rain", "worm", "🐍", "쏠종개과"),
    "Urolophidae": ("sea", "대륙붕·외해", (28.0, 74.0), (0.022, 2.93), 3, "night", "all", "shrimp", "🦅", "흰가오리과"),
    "Bathylagidae": ("sea", "심해·해구", (10.0, 24.0), (0.009, 3.00), 3, "night", "fog", "glow", "💠", "심해빙어과"),
    "Microdesmidae": ("sea", "산호초·열대 해역", (6.0, 16.0), (0.006, 3.00), 2, "day", "clear", "worm", "🐠", "화살망둑과"),
    "Nemichthyidae": ("sea", "심해·해구", (45.0, 135.0), (0.0008, 2.98), 4, "night", "fog", "glow", "🐍", "도요새장어과"),
    "Nessorhamphidae": ("sea", "심해·해구", (35.0, 105.0), (0.0018, 3.00), 4, "night", "fog", "glow", "🐍", "오리주둥이뱀장어과"),
    "Derichthyidae": ("sea", "심해·해구", (28.0, 72.0), (0.0020, 3.00), 4, "night", "fog", "glow", "🐍", "긴목심해장어과"),
    "Muraenesocidae": ("sea", "대륙붕·외해", (55.0, 175.0), (0.0022, 3.02), 3, "night", "rain", "shrimp", "🐍", "갯장어과"),
    "Chlopsidae": ("sea", "산호초·열대 해역", (16.0, 42.0), (0.0022, 3.00), 3, "night", "clear", "worm", "🐍", "가짜곰치과"),
    "Aploactinidae": ("sea", "연안 갯바위·내만", (7.0, 20.0), (0.018, 3.00), 3, "night", "all", "shrimp", "🐠", "우단치과"),
    "Tetrarogidae": ("sea", "연안 갯바위·내만", (8.0, 24.0), (0.019, 3.00), 2, "night", "all", "shrimp", "🐠", "미역치과"),
    "Peristediidae": ("sea", "심해·해구", (16.0, 42.0), (0.013, 3.00), 3, "night", "fog", "glow", "🐠", "무장성대과"),
    "Sebastolobidae": ("sea", "심해·해구", (26.0, 68.0), (0.018, 3.02), 3, "night", "fog", "glow", "🐠", "홍살치과"),
    "Mochokidae": ("river", "대하천 본류", (10.0, 36.0), (0.015, 3.02), 2, "night", "clear", "worm", "🐠", "시노돈티스메기과"),
    "Bregmacerotidae": ("sea", "대륙붕·외해", (6.0, 14.0), (0.009, 3.00), 2, "night", "clear", "shrimp", "🐟", "날개대구과"),
    "Macrouridae": ("sea", "심해·해구", (28.0, 92.0), (0.007, 3.00), 4, "night", "fog", "glow", "💠", "민태과"),
    "Macruronidae": ("sea", "심해·해구", (45.0, 115.0), (0.008, 3.02), 3, "night", "fog", "lure", "🐟", "호키민대구과"),
    "Hypnidae": ("sea", "대륙붕·외해", (32.0, 68.0), (0.024, 2.94), 4, "night", "fog", "glow", "⚡", "관전기가오리과"),
    "Caproidae": ("sea", "심해·해구", (12.0, 28.0), (0.025, 3.00), 3, "night", "fog", "shrimp", "🐠", "다홍치과"),
    "Cyttidae": ("sea", "심해·해구", (24.0, 54.0), (0.023, 3.00), 3, "night", "fog", "lure", "🐠", "거울달고기과"),
    "Grammicolepididae": ("sea", "심해·해구", (18.0, 48.0), (0.020, 3.00), 4, "night", "fog", "glow", "💠", "은박달고기과"),
    "Oreosomatidae": ("sea", "심해·해구", (22.0, 56.0), (0.024, 3.00), 4, "night", "fog", "glow", "💠", "오레오달고기과"),
    "Triacanthodidae": ("sea", "심해·해구", (10.0, 26.0), (0.022, 3.00), 3, "night", "fog", "glow", "🐠", "심해은비늘쥐치과"),
    "Triacanthidae": ("sea", "연안 갯바위·내만", (16.0, 36.0), (0.021, 3.00), 2, "day", "clear", "shrimp", "🐟", "은비늘쥐치과"),
    "Nomeidae": ("sea", "원양·회유 해역", (16.0, 48.0), (0.015, 3.01), 2, "day", "clear", "shrimp", "🐟", "노메치과"),
    "Centrolophidae": ("sea", "원양·회유 해역", (28.0, 86.0), (0.016, 3.02), 3, "all", "fog", "lure", "🐟", "해파리병어과"),
    "Ariommatidae": ("sea", "대륙붕·외해", (16.0, 38.0), (0.016, 3.01), 2, "day", "clear", "shrimp", "🐟", "은병어과"),
    "Polymixiidae": ("sea", "심해·해구", (18.0, 46.0), (0.018, 3.01), 3, "night", "fog", "glow", "🐠", "턱수염금눈돔과"),
    "Monocentridae": ("sea", "대륙붕·외해", (10.0, 24.0), (0.028, 2.98), 4, "night", "clear", "glow", "🐠", "철갑둥어과"),
    "Anomalopidae": ("sea", "산호초·열대 해역", (9.0, 22.0), (0.020, 3.00), 4, "night", "clear", "glow", "💠", "발광눈고기과"),
    "Grammatidae": ("sea", "산호초·열대 해역", (5.0, 11.0), (0.016, 3.00), 3, "day", "clear", "shrimp", "🐠", "요정바슬렛과"),
    "Notacanthidae": ("sea", "심해·해구", (32.0, 88.0), (0.003, 3.00), 4, "night", "fog", "glow", "🐍", "가시꼬리심해장어과"),
    "Halosauridae": ("sea", "심해·해구", (34.0, 86.0), (0.003, 3.00), 4, "night", "fog", "glow", "🐍", "할로사우루스장어과"),
    "Chlorophthalmidae": ("sea", "심해·해구", (14.0, 34.0), (0.011, 3.01), 3, "night", "fog", "glow", "💠", "초록눈고기과"),
    "Scopelarchidae": ("sea", "심해·해구", (12.0, 32.0), (0.010, 3.00), 4, "night", "fog", "glow", "💠", "진주눈고기과"),
    "Evermannellidae": ("sea", "심해·해구", (10.0, 22.0), (0.009, 3.00), 4, "night", "storm", "glow", "💠", "검치심해어과"),
    "Giganturidae": ("sea", "심해·해구", (12.0, 26.0), (0.007, 3.00), 5, "night", "fog", "glow", "💠", "망원경눈고기과"),
    "Opisthoproctidae": ("sea", "심해·해구", (8.0, 20.0), (0.013, 3.00), 4, "night", "fog", "glow", "💠", "통안어과"),
    "Phosichthyidae": ("sea", "심해·해구", (8.0, 26.0), (0.008, 3.00), 3, "night", "fog", "glow", "💠", "발광치과"),
    "Melanocetidae": ("sea", "심해·해구", (7.0, 20.0), (0.028, 2.96), 4, "night", "storm", "glow", "💠", "검은악마심해아귀과"),
    "Ceratiidae": ("sea", "심해·해구", (35.0, 110.0), (0.020, 2.98), 5, "night", "storm", "glow", "💠", "바다악마아귀과"),
    "Gigantactinidae": ("sea", "심해·해구", (18.0, 56.0), (0.012, 2.98), 5, "night", "fog", "glow", "💠", "채찍코심해아귀과"),
    "Chilodontidae": ("river", "대하천 본류", (8.0, 20.0), (0.014, 3.00), 2, "day", "clear", "dough", "🐠", "머리서기카라신과"),
    "Citharinidae": ("river", "대하천 본류", (18.0, 56.0), (0.018, 3.02), 3, "day", "clear", "dough", "🐟", "시타리누스과"),
    "Cynolebiidae": ("river", "대하천 본류", (4.0, 12.0), (0.013, 3.00), 3, "day", "rain", "worm", "🐠", "남미계절킬리피시과"),
    "Gadopsidae": ("river", "중류 자갈 여울", (20.0, 54.0), (0.014, 3.02), 3, "night", "clear", "worm", "🐟", "블랙피시과"),
    "Hiodontidae": ("river", "대하천 본류", (22.0, 48.0), (0.012, 3.02), 2, "night", "clear", "lure", "🐟", "문이(금눈청어)과"),
    "Nandidae": ("river", "수초 연안", (6.0, 18.0), (0.018, 3.00), 2, "night", "clear", "worm", "🐠", "나뭇잎고기과"),
    "Polycentridae": ("river", "수초 연안", (4.5, 10.0), (0.019, 3.00), 2, "day", "clear", "worm", "🐠", "아마존나뭇잎고기과"),
    "Malapteruridae": ("river", "대하천 본류", (25.0, 88.0), (0.015, 3.02), 4, "night", "storm", "worm", "⚡", "전기메기과"),
    "Protopteridae": ("river", "대하천 본류", (45.0, 145.0), (0.010, 3.02), 4, "night", "rain", "worm", "🐉", "아프리카폐어과"),
    "Pantodontidae": ("lake", "수초 연안", (7.0, 12.0), (0.015, 3.00), 3, "day", "clear", "worm", "🐠", "민물나비고기과"),
    "Sillaginidae": ("sea", "연안 갯바위·내만", (14.0, 32.0), (0.009, 3.02), 1, "day", "clear", "worm", "🐟", "보리멸과"),
    "Menidae": ("sea", "연안 갯바위·내만", (14.0, 30.0), (0.024, 3.00), 2, "day", "clear", "shrimp", "🐠", "달고기전갱이과"),
    "Trichonotidae": ("sea", "산호초·열대 해역", (8.0, 22.0), (0.005, 3.00), 2, "day", "clear", "worm", "🐠", "모래잠수어과"),
    "Creediidae": ("sea", "산호초·열대 해역", (4.0, 9.0), (0.006, 3.00), 2, "day", "clear", "worm", "🐠", "모래숨기어과"),
    "Champsodontidae": ("sea", "심해·해구", (7.0, 16.0), (0.009, 3.00), 2, "night", "fog", "glow", "🐟", "악어이빨치과"),
    "Pentacerotidae": ("sea", "심해·해구", (25.0, 68.0), (0.022, 3.02), 4, "night", "fog", "lure", "👑", "돗돔류(갑옷머리돔)과"),
    "Arripidae": ("sea", "원양·회유 해역", (35.0, 88.0), (0.013, 3.02), 3, "day", "clear", "lure", "🐟", "호주연어농어과"),
    "Callorhinchidae": ("sea", "대륙붕·외해", (52.0, 118.0), (0.008, 3.00), 4, "night", "fog", "shrimp", "💠", "쟁기코은상어과"),
    "Rhinochimaeridae": ("sea", "심해·해구", (58.0, 135.0), (0.006, 3.00), 4, "night", "fog", "glow", "💠", "긴코은상어과"),
    "Samaridae": ("sea", "대륙붕·외해", (8.0, 22.0), (0.013, 3.00), 2, "night", "all", "worm", "🐟", "뿔가자미과"),
    "Psettodidae": ("sea", "대륙붕·외해", (30.0, 74.0), (0.016, 3.01), 3, "day", "clear", "lure", "🐟", "인도큰넙치과"),
    "Odacidae": ("sea", "연안 갯바위·내만", (14.0, 40.0), (0.012, 3.01), 2, "day", "clear", "dough", "🐠", "해초놀래기과"),
}

EN_HEAD_NOUNS: Dict[str, str] = {
    # Multi-word & compound fish nouns first
    "cutthroat eel": "심해긴목장어", "cutthroat eels": "심해긴목장어",
    "snipe eel": "도요새장어", "snipe eels": "도요새장어",
    "sawtooth eel": "톱니장어", "bobtail snipe eel": "짧은꼬리장어",
    "spaghetti eel": "실장어", "duckbill eel": "오리주둥이장어", "duckbill eels": "오리주둥이장어",
    "worm eel": "지렁이장어", "snake eel": "바다뱀장어",
    "cusk eel": "첨치", "cusk-eel": "첨치", "cusk eels": "첨치", "cusk-eels": "첨치",
    "deepsea cusk-eel": "심해첨치", "pike conger": "갯장어", "pike-conger": "갯장어",
    "pikeconger": "갯장어", "false moray": "가짜곰치", "moray eel": "곰치",
    "conger eel": "붕장어", "mud eel": "진흙뱀장어", "spiny eel": "가시장어",
    "swamp eel": "드렁허리", "electric eel": "전기뱀장어", "snakemoray": "뱀곰치",
    "slope dragonet": "비탈돛양태", "deepsea anglerfish": "심해아귀",
    "whipnose angler": "채찍코심해아귀", "wolftrap angler": "늑대덫심해아귀",
    "dwarf goby": "꼬마망둑", "pygmy goby": "꼬마망둑", "pygmygoby": "꼬마망둑",
    "dwarfgoby": "꼬마망둑", "coral goby": "산호망둑", "coralgoby": "산호망둑",
    "reef goby": "산호초망둑", "reefgoby": "산호초망둑", "shrimp goby": "공생망둑",
    "shrimpgoby": "공생망둑", "barbel goby": "수염망둑", "barbelgoby": "수염망둑",
    "dart goby": "화살망둑", "dartfish": "화살망둑", "wormgoby": "지렁이망둑",
    "worm goby": "지렁이망둑", "mangrove goby": "맹그로브망둑", "mangrovegoby": "맹그로브망둑",
    "atomgoby": "초소형망둑", "eelgoby": "장어망둑", "eel goby": "장어망둑",
    "mudskipper": "말뚝망둥어", "sleeper goby": "구굴무치", "loach goby": "미꾸리망둑",
    "fairy wrasse": "요정놀래기", "razor wrasse": "면도날놀래기", "hogfish": "혹놀래기",
    "tuskfish": "엄니놀래기", "rainbow wrasse": "무지개놀래기", "parrotfish": "파랑비늘돔",
    "fairy basslet": "요정바슬렛", "painted basslet": "채색바슬렛", "painted basslets": "채색바슬렛",
    "pygmy angelfish": "꼬마청줄돔", "freshwater butterflyfish": "민물나비고기",
    "butterflyfish": "나비고기", "butterfly fish": "나비고기", "bannerfish": "깃대나비고기",
    "angelfish": "청줄돔", "surgeonfish": "양쥐돔", "unicornfish": "표문쥐치",
    "rabbitfish": "독가시치", "damselfish": "자리돔", "anemonefish": "흰동가리",
    "clownfish": "흰동가리", "triggerfish": "쥐치복", "filefish": "쥐치",
    "leatherjacket": "말쥐치", "pufferfish": "복어", "toadfish": "두꺼비고기",
    "porcupinefish": "가시복", "burrfish": "가시복", "boxfish": "거북복",
    "cowfish": "뿔복", "frogfish": "씬벵이", "coffinfish": "관심해아귀",
    "handfish": "손지느러미고기", "seabat": "부치", "batfish": "부치",
    "sea toad": "심해두꺼비아귀", "sea toads": "심해두꺼비아귀",
    "stonefish": "스톤피시", "waspfish": "미역치", "scorpionfish": "양볼락",
    "rockfish": "볼락", "thornyhead": "홍살치", "lionfish": "쏠배감펭",
    "turkeyfish": "쏠배감펭", "velvetfish": "우단치", "stingfish": "가시쏠배감펭",
    "duckbill flathead": "오리부리양태", "ghost flathead": "가시양태",
    "deepwater flathead": "심해양태", "flathead": "양태",
    "flying gurnard": "날개달린성대", "armored searobin": "무장성대",
    "sea robin": "성대", "searobin": "성대", "gurnard": "성대",
    "lefteye flounder": "둥글넙치", "righteye flounder": "가자미",
    "sand flounder": "모래넙치", "crested flounder": "관가자미",
    "tongue sole": "참서대", "tonguesole": "참서대", "tonguefish": "혀서대",
    "american sole": "아메리카서대", "american soles": "아메리카서대",
    "sand whiff": "모래납작넙치", "sand whiffs": "모래납작넙치", "sanddab": "모래넙치",
    "round stingray": "둥근가오리", "round ray": "둥근가오리", "butterfly ray": "나비가오리",
    "eagle ray": "매가오리", "manta ray": "만타가오리", "devilray": "만타가오리",
    "cownose ray": "소코가오리", "electric ray": "전기가오리", "sleeper ray": "잠가오리",
    "torpedo ray": "전기가오리", "numbfish": "전기가오리", "numbfishes": "전기가오리",
    "guitarfish": "가래상어", "wedgefish": "가래상어", "banjo ray": "반조가오리",
    "fanray": "부채가오리", "sawfish": "톱가오리", "sawshark": "톱상어",
    "catshark": "두툽상어", "houndshark": "까치상어", "dogfish": "곱상어",
    "lanternshark": "발광상어", "sleeper shark": "잠상어", "gulper shark": "꿀꺽상어",
    "kitefin shark": "연지느러미상어", "bramble shark": "가시상어", "frilled shark": "주름상어",
    "goblin shark": "마귀상어", "megamouth shark": "넓은주둥이상어", "carpet shark": "수염상어",
    "bamboo shark": "대나무상어", "hammerhead": "귀상어", "thresher shark": "환도상어",
    "sand tiger": "모래뱀상어", "tiger shark": "뱀상어", "angelshark": "전자상어",
    "angel shark": "전자상어", "longnose chimaera": "긴코은상어", "plownose chimaera": "쟁기코은상어",
    "ghost shark": "은상어", "rabbit fish": "은상어",
    "hillstream loach": "계류미꾸리", "hillstream loaches": "계류미꾸리",
    "stone loach": "종개", "spined loach": "기름종개", "clown loach": "어릿광대미꾸리",
    "sand loach": "모래미꾸리", "loach catfish": "미꾸리메기", "loach catfishes": "미꾸리메기",
    "glass catfish": "유리메기", "driftwood catfish": "유목메기", "driftwood catfishes": "유목메기",
    "banjo catfish": "반조메기", "banjo catfishes": "반조메기", "upside-down catfish": "거꾸로메기",
    "electric catfish": "전기메기", "bumblebee catfish": "꿀벌메기", "bumblebee catfishes": "꿀벌메기",
    "armored catfish": "갑옷메기", "suckermouth catfish": "빨판입메기", "sucker-mouth catfishes": "빨판입메기",
    "whiptail catfish": "채찍꼬리메기", "sea catfish": "바다동자개", "sea catfishes": "바다동자개",
    "torrent catfish": "급류메기", "stream catfishes": "계류메기", "pencil catfish": "연필메기",
    "parasitic catfish": "연필메기", "talking catfish": "울음메기", "shark catfish": "상어메기",
    "three-barbeled catfishes": "세수염메기", "grunter catfishes": "그런터메기",
    "whale catfishes": "고래메기", "schilbid catfishes": "유리메기",
    "dwarf cichlid": "드워프시클리드", "peacock bass": "피콕배스", "peacock cichlid": "피콕시클리드",
    "pike cichlid": "파이크시클리드", "dwarf pike": "꼬마파이크시클리드", "shell-dweller": "패각시클리드",
    "mouthbrooder": "마우스브루더", "mouth almighty": "마우스올마이티", "eartheater": "어스이터시클리드",
    "diamond tetra": "다이아몬드테트라", "pencilfish": "연필고기", "pencilfishes": "연필고기",
    "headstander": "머리서기고기", "hatchetfish": "도끼고기", "glass knifefish": "유리칼고기",
    "glass knifefishes": "유리칼고기", "sand knifefish": "모래칼고기", "knifefish": "칼고기",
    "pike characin": "창꼬치카라신", "african tetra": "아프리카테트라",
    "south american darter": "남미화살테트라", "south american darters": "남미화살테트라",
    "gizzard shad": "전어", "thread herring": "실청어", "longfin herrings": "준치",
    "round herring": "샛줄멸", "wolf herring": "늑대청어", "river sprats": "강멸치",
    "flyingfish": "날치", "flying fish": "날치", "halfbeak": "학꽁치", "halfbeaks": "학꽁치",
    "needlefish": "동갈치", "saury": "꽁치", "pipefish": "실고기", "ghost pipefish": "유령실고기",
    "seadragon": "해룡", "shrimpfish": "대롱치", "snipefish": "대롱치", "trumpetfish": "대롱치",
    "cornetfish": "홍대치", "seamoth": "바다나방",
    "deepwater cardinalfish": "심해동갈돔", "deepwater cardinalfishes": "심해동갈돔",
    "cardinalfish": "동갈돔", "squirrelfish": "얼게비늘", "soldierfish": "군인돔",
    "lanternfish": "샛비늘치", "lanternfishes": "샛비늘치",
    "dragonfish": "심해용치", "loosejaw": "느슨턱용치", "snaggletooth": "송곳니용치",
    "viperfish": "살무사용치", "lightfish": "발광치", "bristlemouth": "털입발광치",
    "pearlside": "진주발광치", "pearlfish": "진주고기", "pearlfishes": "진주고기",
    "pearleye": "진주눈고기", "barreleye": "통안어", "spookfish": "유령통안어",
    "telescopefish": "망원경고기", "greeneye": "초록눈고기", "deepsea lizardfish": "심해매퉁이",
    "lizardfish": "매퉁이", "cucumber fish": "오이고기", "cucumberfish": "오이고기",
    "flagfin": "깃발지느러미", "barracudina": "꼬치매퉁이", "barracudinas": "꼬치매퉁이",
    "sabertooth": "검치어", "sabretooth": "검치어", "lancetfish": "란셋피시",
    "daggertooth": "단검이빨치", "waryfish": "파란눈심해치", "slickhead": "민머리치",
    "slickheads": "민머리치", "tubeshoulder": "발광어깨치", "tubeshoulders": "발광어깨치",
    "deep-sea smelt": "심해빙어", "deepsea tripod fishes": "심해세발치",
    "tripod fish": "세발치", "spiderfish": "거미세발치", "pencilsmelt": "심해연필빙어",
    "blacksmelt": "검은심해빙어", "deepsea smelt": "심해빙어",
    "crocodile icefish": "악어남극빙어", "icefish": "남극빙어",
    "plunderfish": "약탈어", "plunderfishes": "약탈어", "antarctic dragonfish": "남극용치",
    "snailfish": "꼼치", "lumpsucker": "뚝지", "lumpfish": "뚝지",
    "poacher": "날개줄고기", "poachers": "날개줄고기",
    "fathead sculpin": "물수배기", "fathead sculpins": "물수배기", "sculpin": "둑중개",
    "eelpout": "등가시치", "prickleback": "장갱이", "gunnel": "황줄베도라치",
    "wolffish": "늑대고기", "wrymouth": "비틀입장갱이", "prowfish": "이물고기",
    "quillfish": "깃대장갱이", "graveldiver": "자갈잠수어", "sand diver": "모래잠수어",
    "sanddiver": "모래잠수어", "sandburrower": "모래숨기어", "sandperch": "양동미리",
    "sandperches": "양동미리", "clinid": "비늘베도라치", "klipfish": "바위베도라치",
    "weedfish": "해초베도라치", "triplefin": "먹베도라치", "threefin": "먹베도라치",
    "tube blenny": "대롱베도라치", "fangblenny": "송곳니베도라치", "rockskipper": "바위베도라치",
    "coralblenny": "산호베도라치", "kelpfish": "해초베도라치", "cockscomb": "닭벼슬장갱이",
    "dragonet": "돛양태", "clingfish": "학치", "clingfishes": "학치",
    "sand stargazer": "모래통구멍", "sand stargazers": "모래통구멍", "stargazer": "통구멍",
    "jawfish": "후악치", "dottyback": "도티백", "basslet": "바슬렛", "basslets": "바슬렛",
    "roundhead": "동글머리치", "roundheads": "동글머리치", "longfin": "긴지느러미치",
    "soapfish": "비누고기", "soapfishes": "비누고기", "sweeper": "주걱치", "bullseye": "주걱치",
    "bandfish": "붉은띠치", "bandfishes": "붉은띠치", "hardyhead": "은줄멸",
    "hardyheads": "은줄멸", "silverside": "색줄멸", "silversides": "색줄멸",
    "rainbowfish": "레인보우피시", "blue-eye": "푸른눈송사리", "blue eye": "푸른눈송사리",
    "lampeye": "램프아이송사리", "lampeyes": "램프아이송사리", "toothcarp": "킬리피시",
    "killifish": "킬리피시", "killifishes": "킬리피시", "pupfish": "퍼프피시",
    "livebearer": "난태생송사리", "medaka": "송사리", "ricefish": "송사리",
    "ponyfish": "주둥치", "ponyfishes": "주둥치", "slipmouth": "주둥치",
    "mojarra": "게레치", "silver-biddy": "게레치", "threadfin bream": "실꼬리돔",
    "monocle bream": "실꼬리돔", "threadfin": "날가지숭어", "bigeye": "붉은메기",
    "goatfish": "촉수", "fusilier": "세동가리", "grunt": "하스돔", "sweetlips": "어름돔",
    "emperor": "갈돔", "whiptail": "민태", "grenadier": "민태", "rattail": "민태",
    "codlet": "꼬마대구", "rockling": "바위대구", "morid cod": "돌대구", "eel cod": "장어대구",
    "oilfish": "기름치", "escolar": "에스콜라", "snake mackerel": "갈치꼬치",
    "cutlassfish": "갈치", "hairtail": "갈치", "driftfish": "노메치", "medusafish": "해파리병어",
    "butterfish": "병어", "pomfret": "새다래", "oarfish": "산갈치", "ribbonfish": "투라치",
    "crestfish": "투구산갈치", "boarfish": "다홍치", "boar fish": "다홍치",
    "lookdown dory": "거울달고기", "tinselfish": "은박달고기", "alfonsino": "금눈돔",
    "slimehead": "납작금눈돔", "roughy": "납작금눈돔", "whalefish": "고래고기치",
    "assfish": "심해첨치", "hagfish": "먹장어", "hagfishes": "먹장어", "lamprey": "칠성장어",
    "gudgeon": "모래무지", "gudgeons": "모래무지", "nase": "눈치", "danio": "다니오",
    "rasbora": "라스보라", "snowtrout": "설산송어잉어", "minnow": "피라미", "chub": "황어",
    "dace": "황어", "shiner": "피라미", "bitterling": "납자루", "mahseer": "마시르",
    "labeo": "라베오", "garra": "가라잉어", "barbel": "바벨잉어", "sucker": "서커잉어",
    "mountain carps": "산악잉어", "stardrum": "민어", "kingcroaker": "킹민어", "croaker": "민어",
    "weakfish": "민어", "meagre": "민어", "sea bass": "농어", "seabass": "농어",
    "seaperch": "바다농어", "perchlet": "유리농어", "glassfish": "유리농어", "glassfishes": "유리농어",
    "ocean-bass": "심해농어", "slopefish": "비탈돔", "slope fish": "비탈돔",
    "armorhead": "돗돔류", "lanternbelly": "반딧불게르치", "splitfin": "게르치",
    "hawkfish": "황다래", "trumpeter": "나팔돔", "trumpeters": "나팔돔", "morwong": "다동가리",
    "halfmoon": "초승달돔", "rover": "방랑돔", "chameleonfish": "카멜레온치",
    "chameleonfishes": "카멜레온치", "leaffish": "나뭇잎고기", "climbing perch": "등목어",
    "fighting fish": "베타", "paradise fish": "버들붕어", "lungfish": "폐어",
    "bichir": "폴립테루스", "reedfish": "갈대고기", "elephantfish": "코끼리코고기",
    "mudfish": "진흙고기", "cavefish": "동굴고기", "blindcat": "눈먼메기",
    "flashlightfish": "발광눈고기", "pineapplefish": "철갑둥어", "bearded fish": "수염돔",
    "beardfish": "턱수염금눈돔", "sandlance": "까나리", "sand lance": "까나리",
    "siphonfish": "사이펀동갈돔", "tapirfish": "가시꼬리심해장어", "swallowtail": "제비꼬리돔",
    "portholefish": "반짝심해어", "sawpalate": "톱입천장장어", "duckbill": "오리부리치",
    "frogmouth": "두꺼비입물고기", "banjofish": "반조돔", "seadevil": "바다악마아귀",
    "slimy head": "납작금눈돔", "pike": "강꼬치고기", "pickerel": "꼬마강꼬치",
    "sturgeon": "철갑상어", "paddlefish": "주걱철갑상어", "gar": "가아", "garfish": "동갈치",
    "bowfin": "보우핀", "arowana": "아로와나", "arapaima": "아라파이마",
    "tarpon": "풀잉어", "milkfish": "갯농어", "bonefish": "여을멸", "ronquil": "장갱이",
    "citharine": "시타리누스", "spook": "은상어", "oldwife": "올드와이프", "argentine": "심해은어",
    # Single-word heads
    "anglerfish": "아귀", "angler": "아귀", "spikefish": "삼각가시쥐치",
    "brotula": "브로툴라", "coralbrotula": "산호브로툴라", "grubfish": "동미리",
    "eviota": "꼬마망둑", "cory": "코리도라스", "corydoras": "코리도라스", "corydora": "코리도라스",
    "tandan": "장어메기", "tilapia": "틸라피아", "gaper": "악어이빨치",
    "podge": "포지바리", "cusk": "첨치", "gregory": "자리돔",
    "sawbelly": "톱배금눈돔", "snakelet": "실뱀고기", "pigfish": "돼지하스돔",
    "panchax": "판착스킬리", "goosefish": "아귀", "midshipman": "발광두꺼비고기",
    "lipsucker": "입술빨판고기", "whipnose": "채찍코아귀", "limia": "리미아송사리",
    "hamlet": "햄릿바리", "bleak": "블리크잉어", "pugolovka": "올챙이망둑",
    "whiff": "납작넙치", "coris": "무지개놀래기", "ctenopoma": "등목어",
    "ilisha": "준치", "hoplo": "호플로메기", "wormfish": "실망둑",
    "nothobranch": "노토브란킬리", "dario": "다리오", "mosquitofish": "모기송사리",
    "kneria": "크네리아", "lamprologus": "람프롤로구스", "sillago": "보리멸",
    "platyfish": "플래티", "fangjaw": "송곳니심해어", "oreo": "오레오달고기",
    "darter": "다터", "tilefish": "옥돔", "goby": "망둑어", "gobies": "망둑어",
    "blenny": "베도라치", "blennies": "베도라치", "wrasse": "놀래기", "wrasses": "놀래기",
    "cichlid": "시클리드", "cichlids": "시클리드", "tetra": "테트라", "tetras": "테트라",
    "catfish": "메기", "catfishes": "메기", "loach": "미꾸리", "loaches": "미꾸리",
    "anchovy": "멸치", "anchovies": "멸치", "thryssa": "곤어리",
    "eel": "장어", "eels": "장어", "moray": "곰치", "morays": "곰치", "conger": "붕장어",
    "sole": "서대", "soles": "서대", "flounder": "넙치", "flounders": "넙치",
    "halibut": "가자미", "turbot": "터봇넙치", "chromis": "자리돔", "anthias": "꽃돔",
    "snapper": "퉁돔", "snappers": "퉁돔", "grouper": "바리", "groupers": "바리",
    "rockcod": "바리", "hind": "바리", "seabream": "도미", "bream": "도미", "porgy": "도미",
    "perch": "농어", "perches": "농어", "bass": "농어", "basses": "농어",
    "puffer": "복어", "puffers": "복어", "toby": "복어", "mullet": "숭어",
    "smelt": "빙어", "herring": "청어", "sardine": "정어리", "sardinella": "정어리",
    "sprat": "멸치", "shad": "전어", "whiting": "보리멸", "hake": "민대구",
    "cod": "대구", "ling": "대구", "mackerel": "고등어", "tuna": "다랑어", "bonito": "가다랑어",
    "trevally": "전갱이", "jack": "전갱이", "pompano": "전갱이", "scad": "전갱이",
    "drum": "민어", "kingfish": "민어", "grunter": "벤자리", "carp": "잉어",
    "barb": "바브", "barbs": "바브", "trout": "송어", "salmon": "연어",
    "char": "곤들매기", "charr": "곤들매기", "whitefish": "백어", "cisco": "시스코백어",
    "grayling": "살기", "gourami": "구라미", "betta": "베타", "snakehead": "가물치",
    "piranha": "피라냐", "pacu": "파쿠", "characin": "카라신", "characins": "카라신",
    "dory": "달고기", "stingray": "노랑가오리", "ray": "가오리", "rays": "가오리",
    "skate": "홍어", "skates": "홍어", "shark": "상어", "sharks": "상어",
    "chimaera": "은상어", "seahorse": "해마", "razorfish": "면도날놀래기",
    "damsel": "자리돔", "demoiselle": "자리돔", "sergeant": "자리돔",
    "galaxias": "갈락시아스", "paragalaxias": "파라갈락시아스", "gambusia": "감부시아",
    "molly": "몰리", "platy": "플래티", "swordtail": "소드테일", "rivulus": "리불루스킬리",
    "apisto": "아피스토그라마", "hap": "하플로크로미스", "haplo": "하플로크로미스",
    "astyanax": "아스티아낙스테트라", "brycon": "브리콘", "mogurnda": "모군다",
    "badis": "바디스", "notothen": "남극암치", "dreamer": "초롱심해아귀",
    "swallower": "큰입심해어", "wriggler": "실망둑", "robber": "로버테트라",
    "tatia": "타티아메기", "groppo": "그로포", "toothy": "이빨망둑", "halosaur": "할로사우루스",
    "catlet": "꼬마메기", "happy": "해피시클리드", "mormyrid": "코끼리코고기",
    "banjo": "반조메기", "sandy": "모래치", "dart": "모래화살망둑",
    "goldie": "금빛꽃돔", "floater": "부유치", "squeaker": "시노돈티스메기",
    "gulper": "풍선장어", "payara": "파야라", "himri": "힘리잉어",
    "fanfin": "부채심해아귀", "hemiodus": "헤미오두스", "prettyfin": "프리티핀테트라",
    "piquira": "피퀴라테트라", "acara": "아카라시클리드", "sleeper": "구굴무치",
    "nibbler": "바위도미", "sacura": "사쿠라꽃돔", "comber": "컴버바리",
    "buntingi": "분팅이송사리", "largemouth": "큰입시클리드", "utaka": "우타카시클리드",
    "sicyopus": "시키오푸스망둑", "stiphodon": "스티포돈망둑", "cabillus": "카빌루스망둑",
    "calumia": "칼루미아망둑", "fish": "어", "fishes": "어",
}

EN_MOD_WORDS: Dict[str, str] = {
    "abyssal": "심해", "deepsea": "심해", "deepwater": "심해", "deep-water": "심해", "deep-sea": "심해", "deep": "심해",
    "pelagic": "원양", "oceanic": "원양", "marine": "바다", "coastal": "연안", "shallow": "얕은",
    "reef": "산호초", "coral": "산호", "rock": "바위", "stone": "돌", "sand": "모래", "mud": "갯벌",
    "gravel": "자갈", "pebble": "조약돌", "cave": "동굴", "subterranean": "지하", "blind": "눈먼",
    "freshwater": "민물", "river": "강", "stream": "계류", "creek": "시내", "brook": "개울", "torrent": "급류",
    "mountain": "산악", "highland": "고산", "hillstream": "계류", "lake": "호수", "pond": "연못",
    "swamp": "늪", "marsh": "습지", "lagoon": "석호", "estuary": "하구", "bay": "내만", "gulf": "만",
    "island": "섬", "slope": "비탈", "shelf": "대륙붕", "seamount": "해산", "tidepool": "조수웅덩이",
    "surf": "파도", "mangrove": "맹그로브", "kelp": "다시마숲", "seagrass": "해초밭", "grass": "수초",
    "algae": "조류", "moss": "이끼",
    "black": "검은", "white": "흰", "red": "붉은", "crimson": "진홍", "scarlet": "주홍",
    "pink": "분홍", "rosy": "장미", "rose": "장미", "blue": "푸른", "azure": "청록",
    "yellow": "노랑", "golden": "황금", "gold": "황금", "silver": "은빛", "silvery": "은빛",
    "bronze": "청동", "copper": "구리", "orange": "주황", "green": "초록", "emerald": "에메랄드",
    "olive": "올리브", "brown": "갈색", "dusky": "어두운", "dark": "어두운", "pale": "연한",
    "bright": "빛나는", "brilliant": "찬란한", "luminous": "발광", "glowing": "발광",
    "glass": "유리", "transparent": "투명", "ghost": "유령", "phantom": "유령", "shadow": "그림자",
    "spotted": "점박이", "spot": "점", "spots": "점", "speckled": "잔점", "freckled": "주근깨",
    "dotted": "점무늬", "polkadot": "물방울", "ocellated": "안점", "eyed": "눈무늬",
    "striped": "줄무늬", "stripe": "줄", "banded": "띠무늬", "band": "띠",
    "barred": "가로줄", "bar": "줄", "lined": "세로줄", "line": "줄", "ringed": "고리무늬",
    "checkered": "바둑무늬", "marbled": "대리석", "mottled": "얼룩", "blotched": "큰얼룩",
    "netted": "그물무늬", "bridled": "고삐무늬", "masked": "가면", "saddled": "안장무늬",
    "collared": "목걸이", "crowned": "왕관", "crested": "벼슬", "horned": "뿔",
    "bearded": "수염", "whiskered": "수염", "barbeled": "수염", "barbel": "수염", "bullseye": "과녁눈", "tusked": "엄니",
    "toothed": "이빨", "fanged": "송곳니", "spiny": "가시", "spined": "가시",
    "thorny": "가시", "prickly": "가시", "armored": "갑옷", "scaly": "비늘",
    "smallscale": "작은비늘", "largescale": "큰비늘", "naked": "무비늘", "smooth": "민",
    "rough": "거친", "flat": "납작", "slender": "가는", "elongate": "긴몸", "elongated": "긴몸",
    "narrow": "좁은", "broad": "넓은", "broadfin": "넓은지느러미", "wide": "넓은",
    "stout": "통통한", "fat": "뚱뚱한", "deepbody": "체고높은", "narrowbody": "좁은몸",
    "dwarf": "꼬마", "pygmy": "꼬마", "mini": "꼬마", "miniature": "꼬마",
    "tiny": "작은", "little": "작은", "small": "작은", "lesser": "작은",
    "giant": "대형", "great": "큰", "greater": "큰", "large": "큰", "big": "큰", "bigfoot": "큰발",
    "bigeye": "큰눈", "smalleye": "작은눈", "redeye": "붉은눈", "long": "긴", "short": "짧은",
    "longfin": "긴지느러미", "shortfin": "짧은지느러미", "sailfin": "돛지느러미", "highfin": "높은지느러미",
    "blackfin": "검은지느러미", "yellowfin": "노랑지느러미", "redfin": "붉은지느러미",
    "bluefin": "푸른지느러미", "whitefin": "흰지느러미", "anglefin": "모난지느러미",
    "blacktop": "검은등", "longspine": "긴가시", "darkedge": "검은테두리",
    "longtail": "긴꼬리", "shorttail": "짧은꼬리", "spottail": "점꼬리", "forktail": "갈래꼬리",
    "lyretail": "거문고꼬리", "redtail": "붉은꼬리", "tigertail": "호랑이꼬리", "spotside": "옆점",
    "longnose": "긴코", "longsnout": "긴주둥이", "shortsnout": "짧은주둥이", "short-tailed": "짧은꼬리",
    "bigmouth": "큰입", "smallmouth": "작은입", "silvermouth": "은입", "bluelip": "푸른입술",
    "bluethroat": "푸른목", "acute": "뾰족", "sharp": "날카로운", "blunt": "뭉툭",
    "broadhead": "넓은머리", "narrowhead": "좁은머리", "arrowhead": "화살머리", "flathead": "납작머리",
    "roundhead": "둥근머리", "hardyhead": "은줄", "palespot": "연한점", "granular": "과립무늬",
    "ciliate": "섬모", "obliquebanded": "빗띠무늬", "twospot": "두점", "brokenbar": "끊어진줄",
    "abstract": "무늬", "broken": "끊어진", "false": "가짜", "mimic": "흉내", "true": "참",
    "common": "일반", "ornate": "화려한", "painted": "채색", "elegant": "우아한", "graceful": "우아한",
    "splendid": "화려한", "superb": "찬란한", "exquisite": "고운", "pretty": "고운",
    "beautiful": "아름다운", "handsome": "수려한", "royal": "왕실", "emperor": "황제",
    "king": "왕", "queen": "여왕", "princess": "공주", "fairy": "요정",
    "tiger": "호랑이", "leopard": "표범", "zebra": "얼룩말", "peacock": "공작",
    "bumblebee": "꿀벌", "clown": "어릿광대", "butterfly": "나비", "angel": "천사",
    "devil": "악마", "dragon": "용", "snake": "뱀", "worm": "지렁이", "eel": "장어",
    "rooster": "수탉", "parrot": "앵무", "orchid": "난초", "honey": "꿀빛", "dalmatian": "달마시안",
    "climbing": "나무타기", "walking": "걷는", "flying": "나는", "stargazing": "위보는",
    "electric": "전기", "viviparous": "태생", "rapid": "급류",
    "one": "한", "two": "두", "three": "세", "four": "네", "five": "다섯", "six": "여섯", "seven": "일곱", "eight": "여덟",
    "double": "이중", "triple": "삼중", "half": "반", "monocle": "외눈",
    "finned": "지느러미", "tailed": "꼬리", "headed": "머리", "billed": "주둥이",
    "tipped": "끝무늬", "fringed": "술무늬", "arched": "굽은", "nosed": "코",
    "mouth": "입", "eye": "눈", "nose": "코", "fin": "지느러미", "tail": "꼬리",
    "body": "몸", "belly": "배", "chin": "턱", "jaw": "턱", "nape": "목덜미",
    "nasal": "코", "flap": "돌기", "face": "얼굴", "peninsula": "반도",
    "wonderful": "기이한", "strange": "기이한", "weird": "기이한", "bizarre": "기이한", "curious": "기이한",
    "cryptic": "은밀한", "hidden": "숨은", "secret": "비밀", "shy": "수줍은",
    "bold": "선명한", "vivid": "선명한", "cosmopolitan": "범세계", "warmseas": "온난해", "insular": "섬",
    "northern": "북방", "southern": "남방", "eastern": "동방", "western": "서방",
    "eastcoast": "동해안", "atlantic": "대서양", "pacific": "태평양", "indopacific": "인도태평양",
    "arctic": "북극", "antarctic": "남극", "mediterranean": "지중해", "caribbean": "카리브",
    "redsea": "홍해", "african": "아프리카", "american": "아메리카", "south": "남",
    "asian": "아시아", "european": "유럽", "australian": "호주", "japanese": "일본",
    "korean": "한국", "chinese": "중국", "taiwanese": "대만", "philippine": "필리핀",
    "indonesian": "인도네시아", "vietnamese": "베트남", "thai": "태국", "burmese": "미얀마",
    "indian": "인도", "brazilian": "브라질", "amazon": "아마존", "peruvian": "페루",
    "mexican": "멕시코", "chilean": "칠레", "argentine": "아르헨티나", "hawaiian": "하와이",
    "galapagos": "갈라파고스", "californian": "캘리포니아", "nicaragua": "니카라과",
    "angolan": "앙골라", "ghanean": "가나", "nepalese": "네팔", "madagascar": "마다가스카르",
    "malabar": "말라바르", "bengal": "벵골", "borneo": "보르네오", "sumatra": "수마트라",
    "java": "자바", "sulawesi": "술라웨시", "congo": "콩고", "nile": "나일",
    "malawi": "말라위", "tanganyika": "탕가니카", "victoria": "빅토리아", "baikal": "바이칼",
    "mekong": "메콩", "ganges": "갠지스", "mississippi": "미시시피", "orinoco": "오리노코",
    "bahama": "바하마", "chatham": "채텀", "clipperton": "클리퍼턴", "manyara": "마냐라",
    "kutubu": "쿠투부", "rapanui": "라파누이", "prespa": "프레스파", "oriental": "동양",
    "tropical": "열대", "new": "뉴", "guinea": "기니", "zealand": "질랜드",
    "cape": "케이프", "natal": "나탈", "st": "세인트", "helena": "헬레나",
    "of": "의", "and": "와", "in": "", "with": "", "from": "", "the": "",
    "whole": "온", "entire": "온", "mosaic": "모자이크",
}

GENUS_KR_MAP: Dict[str, str] = {
    "Schistura": "스키스투라종개",
    "Haplochromis": "하플로크로미스",
    "Enteromius": "엔테로미우스바브",
    "Trichomycterus": "트리코믹테루스메기",
    "Garra": "가라잉어",
    "Triplophysa": "고원종개",
    "Careproctus": "심해꼼치",
    "Glyptothorax": "글립토토락스메기",
    "Hypostomus": "플레코",
    "Paraliparis": "심해민꼼치",
    "Hyphessobrycon": "하이페소브리콘테트라",
    "Labeobarbus": "라베오바부스",
    "Aphyosemion": "아피오세미온킬리",
    "Rhinogobius": "밀망둑",
    "Astyanax": "아스티아낙스테트라",
    "Synodontis": "시노돈티스메기",
    "Labeo": "라베오잉어",
    "Creagrutus": "크레아그루투스테트라",
    "Coelorinchus": "꼬리민태",
    "Nothobranchius": "노토브란킬리",
    "Pimelodella": "피멜로델라메기",
    "Cobitis": "기름종개",
    "Sinocyclocheilus": "동굴황금잉어",
    "Ancistrus": "안시스트루스플레코",
    "Rineloricaria": "채찍꼬리플레코",
    "Eustomias": "심해검은용치",
    "Leporinus": "레포리누스",
    "Characidium": "남미다터카라신",
    "Symphurus": "보섭서대",
    "Moenkhausia": "모엔카우시아테트라",
    "Rasbora": "라스보라",
    "Melanorivulus": "멜라노리불루스킬리",
    "Callionymus": "실양태",
    "Chiloglanis": "빨판메기",
    "Ophichthus": "바다뱀장어",
    "Trimma": "꼬마산호망둑",
    "Anablepsoides": "아나블렙소이데스킬리",
    "Cambeva": "캄베바메기",
    "Mastacembelus": "가시장어",
    "Hemibrycon": "헤미브리콘테트라",
    "Lycenchelys": "심해등가시치",
    "Schizothorax": "설산송어잉어",
    "Hypsolebias": "힙솔레비아스킬리",
    "Hoplisoma": "코리도라스",
    "Chaetostoma": "가시코플레코",
    "Cyphocharax": "키포카락스",
    "Epiplatys": "에피플라티스킬리",
    "Hemigrammus": "헤미그람무스테트라",
    "Diaphus": "심해샛비늘치",
    "Neobythites": "심해첨치",
    "Oxynoemacheilus": "서아시아종개",
    "Clarias": "클라리아스메기",
    "Gymnotus": "줄전기뱀장어",
    "Cynoglossus": "개서대",
    "Chrysichthys": "황금수염메기",
    "Coryphaenoides": "민태",
    "Orestias": "안데스킬리",
    "Psalidodon": "프살리도돈테트라",
    "Petrocephalus": "페트로케팔루스",
    "Eviota": "에비오타꼬마망둑",
    "Liparis": "꼼치",
    "Nannocharax": "난노카락스",
    "Parapercis": "눈동미리",
    "Placidochromis": "플라키도크로미스",
    "Tachysurus": "동자개",
    "Knodus": "크노두스테트라",
    "Neolamprologus": "네오람프롤로구스",
    "Nezumia": "쥐꼬리민태",
    "Enneapterygius": "먹베도라치",
    "Aseraggodes": "남방서대",
    "Marcusenius": "마르쿠세니우스",
    "Melanotaenia": "레인보우피시",
    "Oneirodes": "초롱심해아귀",
    "Devario": "데바리오다니오",
    "Melamphaes": "큰비늘심해어",
    "Mystus": "미스투스동자개",
    "Physiculus": "돌대구",
    "Gastromyzon": "계류흡반미꾸리",
    "Nemacheilus": "계류종개",
    "Synchiropus": "알롱양태",
    "Etheostoma": "다터",
    "Gambusia": "감부시아",
    "Poecilia": "몰리",
    "Xiphophorus": "소드테일",
    "Apistogramma": "아피스토그라마",
    "Corydoras": "코리도라스",
    "Osteochilus": "오스테오킬루스",
    "Barbus": "바벨잉어",
    "Puntius": "푼티우스바브",
    "Systomus": "시스토무스바브",
    "Danio": "다니오",
    "Gobio": "모래무지",
    "Rhodeus": "납자루",
    "Acheilognathus": "납줄개",
    "Squalidus": "몰개",
    "Microphysogobio": "모래주사",
    "Pseudorasbora": "참붕어",
    "Gymnothorax": "곰치",
    "Apogon": "동갈돔",
    "Ostorhinchus": "줄동갈돔",
    "Chromis": "자리돔",
    "Pomacentrus": "열대자리돔",
    "Chrysiptera": "파랑자리돔",
    "Chaetodon": "나비고기",
    "Halichoeres": "용치놀래기",
    "Cirrhilabrus": "요정놀래기",
    "Thalassoma": "무지개놀래기",
    "Epinephelus": "바리",
    "Lutjanus": "퉁돔",
    "Sebastes": "볼락",
    "Scorpionfish": "양볼락",
    "Scorpaena": "살살치",
    "Sphyraena": "꼬치고기",
    "Hippocampus": "해마",
    "Syngnathus": "실고기",
    "Gasterosteus": "큰가시고기",
    "Cottus": "둑중개",
    "Salmo": "브라운송어",
    "Oncorhynchus": "연어",
    "Salvelinus": "곤들매기",
    "Coregonus": "백어",
    "Betta": "베타",
    "Channa": "가물치",
    "Oreochromis": "틸라피아",
    "Cichla": "피콕배스",
    "Potamotrygon": "담수가오리",
    "Raja": "홍어",
    "Dasyatis": "노랑가오리",
    "Carcharhinus": "흉상어",
    "Squalus": "곱상어",
    "Etmopterus": "발광가시상어",
    "Paralichthys": "넙치",
    "Pleuronectes": "가자미",
}

EPITHET_KO_MAP: Dict[str, str] = {
    "japonica": "일본", "japonicus": "일본", "japonicum": "일본",
    "coreana": "한국", "coreanus": "한국", "coreanum": "한국", "koreana": "한국", "koreanus": "한국",
    "sinensis": "중국", "chinensis": "중국",
    "taiwanensis": "대만", "formosana": "대만", "formosanus": "대만", "okinawae": "오키나와",
    "orientalis": "동양", "occidentalis": "서양", "borealis": "북방", "australis": "남방",
    "septentrionalis": "북방", "meridionalis": "남방",
    "atlanticus": "대서양", "atlantica": "대서양",
    "pacificus": "태평양", "pacifica": "태평양", "indicus": "인도양", "indica": "인도양",
    "mediterraneus": "지중해", "mediterranea": "지중해",
    "americanus": "아메리카", "americana": "아메리카",
    "africanus": "아프리카", "africana": "아프리카",
    "europaeus": "유럽", "europaea": "유럽",
    "asiaticus": "아시아", "asiatica": "아시아",
    "amazonica": "아마존", "amazonicus": "아마존",
    "brasiliensis": "브라질", "peruvianus": "페루", "peruviana": "페루",
    "colombianus": "콜롬비아", "colombiana": "콜롬비아",
    "venezuelae": "베네수엘라", "argentinus": "아르헨티나",
    "mexicanus": "멕시코", "mexicana": "멕시코", "californicus": "캘리포니아",
    "floridanus": "플로리다", "caribbaea": "카리브",
    "niloticus": "나일", "congoensis": "콩고", "tanganyikae": "탕가니카", "malawiensis": "말라위",
    "mekongensis": "메콩", "borneensis": "보르네오", "sumatranus": "수마트라", "javanicus": "자바",
    "luzonensis": "루손", "philippinus": "필리핀", "thailandiae": "태국", "siamensis": "태국",
    "indonesiensis": "인도네시아", "guineensis": "기니", "madagascariensis": "마다가스카르",
    "hawaiiensis": "하와이", "galapagensis": "갈라파고스", "antarcticus": "남극", "antarctica": "남극",
    "glacialis": "빙하", "abyssalis": "심해", "bathybia": "심해", "bathybius": "심해",
    "pelagicus": "원양", "pelagica": "원양", "littoralis": "연안", "marinus": "바다", "marina": "바다",
    "fluviatilis": "강", "fluvialis": "하천", "lacustris": "호수", "palustris": "늪",
    "montanus": "산악", "montana": "산악", "alpinus": "고산", "alpina": "고산",
    "cavernicola": "동굴", "subterraneus": "지하", "caecus": "눈먼", "coecus": "눈먼",
    "maculatus": "점박이", "maculata": "점박이", "maculatum": "점박이",
    "punctatus": "잔점", "punctata": "잔점", "guttatus": "물방울점", "guttata": "물방울점",
    "ocellatus": "안점", "ocellata": "안점", "marmoratus": "대리석", "marmorata": "대리석",
    "fasciatus": "띠무늬", "fasciata": "띠무늬", "vittatus": "세로줄", "vittata": "세로줄",
    "lineatus": "줄무늬", "lineata": "줄무늬", "striatus": "줄무늬", "striata": "줄무늬",
    "taeniatus": "띠무늬", "taeniata": "띠무늬", "zonatus": "고리띠", "zonata": "고리띠",
    "reticulatus": "그물무늬", "reticulata": "그물무늬", "annulatus": "고리무늬", "annulata": "고리무늬",
    "tigrinus": "호랑이무늬", "tigrina": "호랑이무늬", "pardalis": "표범무늬",
    "albus": "흰", "alba": "흰", "albidus": "흰", "niger": "검은", "nigra": "검은", "nigrum": "검은",
    "ater": "검은", "atra": "검은", "fuscus": "어두운", "fusca": "어두운",
    "ruber": "붉은", "rubra": "붉은", "rubrum": "붉은", "rufus": "적갈색", "rufa": "적갈색",
    "coccineus": "진홍", "sanguineus": "선홍", "roseus": "장미", "rosea": "장미",
    "flavus": "노랑", "flava": "노랑", "luteus": "황색", "lutea": "황색",
    "aureus": "황금", "aurea": "황금", "auratus": "황금", "aurata": "황금",
    "argenteus": "은빛", "argentea": "은빛", "coeruleus": "푸른", "caeruleus": "푸른",
    "cyaneus": "청색", "viridis": "초록", "viride": "초록", "chloris": "초록",
    "brunneus": "갈색", "griseus": "회색", "bicolor": "두색", "tricolor": "삼색",
    "multicolor": "다색", "splendens": "찬란한", "pulcher": "아름다운", "pulchra": "아름다운",
    "elegans": "우아한", "ornatus": "화려한", "ornata": "화려한", "formosus": "고운", "formosa": "고운",
    "speciosus": "수려한", "magnificus": "장엄한", "mirabilis": "신비한", "paradoxus": "기이한",
    "maximus": "초대형", "maxima": "초대형", "giganteus": "자이언트", "gigas": "거대",
    "grandis": "큰", "major": "큰", "minor": "작은", "minimus": "초소형", "minima": "초소형",
    "parvus": "작은", "parva": "작은", "nanus": "꼬마", "nana": "꼬마",
    "pumilus": "꼬마", "pumila": "꼬마", "pygmaeus": "꼬마", "pusillus": "작은",
    "longus": "긴", "longa": "긴", "brevis": "짧은", "breve": "짧은",
    "latus": "넓은", "lata": "넓은", "angustus": "좁은", "angusta": "좁은",
    "tenuis": "가는", "gracilis": "가녀린", "robustus": "튼튼한", "robusta": "튼튼한",
    "crassus": "두꺼운", "compressus": "납작한", "depressus": "납작한", "elongatus": "긴몸",
    "acutus": "뾰족", "acuta": "뾰족", "obtusus": "뭉툭", "spinosus": "가시", "armatus": "무장",
    "inermis": "민가시", "glaber": "매끈한", "asper": "거친", "scaber": "거친",
    "barbatus": "수염", "cirrhosus": "수염", "cristatus": "벼슬", "cornutus": "뿔",
    "dentatus": "이빨", "ferox": "사나운", "vorax": "탐식", "rapax": "사냥",
    "communis": "일반", "vulgaris": "일반", "typicus": "전형", "verus": "참",
    "similis": "닮은", "affinis": "근연", "intermedius": "중간", "ambigua": "모호",
    "rex": "왕", "regis": "왕", "regina": "여왕", "imperator": "황제",
    "diabolus": "악마", "daemon": "악마", "angelus": "천사",
    "nebulosus": "구름무늬", "nebulosa": "구름무늬", "mosaica": "모자이크", "mosaicus": "모자이크",
    "filamentosa": "실지느러미", "filamentosus": "실지느러미", "filaria": "실줄",
    "tenebrica": "어두운", "tenebricus": "어두운", "orbitalis": "큰눈", "nigroventralis": "검은배",
    "attenuatus": "가는몸", "attenuata": "가는몸", "robustum": "튼튼한",
    "holopteros": "온지느러미", "holopterus": "온지느러미", "latifrons": "넓은이마",
}

_LATIN_PREFIX_PARTS: List[Tuple[str, str]] = [
    ("melano", "검은"), ("melani", "검은"), ("melan", "검은"),
    ("leuco", "흰"), ("leuci", "흰"), ("leuc", "흰"),
    ("albo", "흰"), ("albi", "흰"), ("alb", "흰"),
    ("erythro", "붉은"), ("erythri", "붉은"), ("erythr", "붉은"), ("rhodo", "장미"),
    ("xantho", "노랑"), ("xanthi", "노랑"), ("xanth", "노랑"),
    ("chryso", "황금"), ("auro", "황금"), ("auri", "황금"), ("argyro", "은빛"), ("argenti", "은빛"),
    ("cyano", "푸른"), ("cyani", "푸른"), ("cyan", "푸른"),
    ("chloro", "초록"), ("chlor", "초록"), ("nigro", "검은"), ("nigri", "검은"), ("nigr", "검은"),
    ("rubro", "붉은"), ("rubri", "붉은"), ("flavo", "노랑"), ("flavi", "노랑"), ("rufo", "적갈"), ("rufi", "적갈"),
    ("macro", "큰"), ("macri", "큰"), ("macr", "큰"), ("megalo", "거대"),
    ("micro", "작은"), ("micri", "작은"), ("micr", "작은"),
    ("nano", "꼬마"), ("brevi", "짧은"), ("longi", "긴"), ("dolicho", "긴"), ("brachy", "짧은"),
    ("lati", "넓은"), ("lato", "넓은"), ("angusti", "좁은"), ("tenui", "가는"),
    ("gracili", "가녀린"), ("crassi", "두꺼운"), ("alti", "높은"),
    ("platy", "납작"), ("lepto", "가는"), ("steno", "좁은"), ("eury", "넓은"), ("pachy", "두꺼운"),
    ("acantho", "가시"), ("spini", "가시"), ("multi", "다수"), ("poly", "다중"),
    ("unimacul", "한점"), ("bimacul", "두점"), ("trimacul", "세점"),
    ("bi", "두"), ("tri", "세"), ("quadri", "네"), ("quinque", "다섯"), ("octo", "여덟"),
    ("ocell", "안점"), ("punct", "점"), ("macul", "점"), ("fasci", "띠"), ("vitt", "줄"),
    ("line", "줄"), ("zon", "띠"), ("reticul", "그물"), ("marmor", "대리석"), ("pogon", "수염"),
]

_LATIN_SUFFIX_PARTS: List[Tuple[str, str]] = [
    ("pinnis", "지느러미"), ("pinna", "지느러미"), ("pterus", "지느러미"), ("ptera", "지느러미"), ("pteron", "지느러미"),
    ("cauda", "꼬리"), ("caudatus", "꼬리"), ("caudis", "꼬리"), ("urus", "꼬리"), ("ura", "꼬리"),
    ("rostris", "주둥이"), ("rostratus", "주둥이"), ("rhynchus", "주둥이"), ("rhyncha", "주둥이"),
    ("stomus", "입"), ("stoma", "입"), ("gnathus", "턱"), ("cheilus", "입술"), ("labris", "입술"),
    ("cephalus", "머리"), ("cephala", "머리"), ("ceps", "머리"), ("frons", "이마"), ("frontis", "이마"),
    ("ops", "눈"), ("ophthalmus", "눈"), ("oculus", "눈"), ("blepharus", "눈꺼풀"),
    ("lepis", "비늘"), ("squamis", "비늘"), ("ichthys", "고기"),
    ("maculatus", "점박이"), ("maculata", "점박이"), ("guttatus", "점박이"), ("guttata", "점박이"),
    ("punctatus", "점"), ("punctata", "점"),
    ("fasciatus", "띠"), ("fasciata", "띠"), ("lineatus", "줄"), ("lineata", "줄"),
    ("vittatus", "줄"), ("vittata", "줄"), ("gaster", "배"), ("ventralis", "배"), ("ventris", "배"),
    ("notus", "등"), ("dorsalis", "등"), ("pectoralis", "가슴"), ("analis", "뒷지느러미"),
    ("spina", "가시"), ("spinis", "가시"), ("acanthus", "가시"), ("odon", "이빨"), ("dens", "이빨"),
]

_GEO_SUFFIX_RE = re.compile(r"(ensis|ense|iensis|iense)$")
_LATIN_PHONETIC_DIGRAPHS: List[Tuple[str, str]] = [
    ("sch", "시"), ("tsch", "치"), ("ch", "크"), ("ph", "프"), ("th", "트"), ("rh", "르"),
    ("qu", "쿠"), ("gh", "그"), ("kn", "크"), ("pf", "프"), ("ts", "츠"), ("tz", "츠"),
    ("dz", "즈"), ("ae", "에"), ("oe", "외"), ("au", "아우"), ("eu", "에우"), ("ei", "에이"),
    ("ou", "우"), ("oo", "우"), ("ee", "이"), ("ia", "이아"), ("io", "이오"), ("iu", "이우"),
    ("ya", "야"), ("ye", "예"), ("yo", "요"), ("yu", "유"),
]
_CHO_MAP = {
    "g": "ㄱ", "k": "ㅋ", "n": "ㄴ", "d": "ㄷ", "t": "ㅌ", "r": "ㄹ", "l": "ㄹ",
    "m": "ㅁ", "b": "ㅂ", "p": "ㅍ", "s": "ㅅ", "z": "ㅈ", "j": "ㅈ", "h": "ㅎ",
    "f": "ㅍ", "v": "ㅂ", "c": "ㅋ", "q": "ㅋ", "x": "ㅅ", "": "ㅇ",
}
_CHUNG_MAP = {
    "a": "ㅏ", "e": "ㅔ", "i": "ㅣ", "o": "ㅗ", "u": "ㅜ", "y": "ㅣ",
    "ya": "ㅑ", "ye": "ㅖ", "yo": "ㅛ", "yu": "ㅠ", "wa": "ㅘ", "wi": "ㅟ", "we": "ㅞ",
    "ae": "ㅐ", "eo": "ㅓ", "eu": "ㅡ", "ui": "ㅢ",
}
_CHO_LIST = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG_LIST = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG_LIST = [""] + list("ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")


def _compose_hangul(cho: str, jung: str, jong: str = "") -> str:
    ci = _CHO_LIST.find(cho)
    ji = _JUNG_LIST.find(jung)
    ki = _JONG_LIST.index(jong) if jong in _JONG_LIST else 0
    if ci < 0 or ji < 0:
        return ""
    return chr(0xAC00 + ci * 588 + ji * 28 + ki)


def latin_to_hangul(word: str) -> str:
    """Latin/English proper-noun or taxonomic stem -> crisp Hangul syllable blocks."""
    w = re.sub(r"[^a-z]", "", (word or "").lower())
    if not w:
        return "어"
    # Replace common taxonomic endings smoothly
    w = re.sub(r"ae$", "에", w) if False else w

    # Tokenize into phonological chunks
    i = 0
    out: List[str] = []
    vowels = set("aeiouy")
    while i < len(w):
        prev_i = i
        if w.startswith("pseudo", i):
            out.append("슈")
            c, v = "ㄷ", "ㅗ"
            i += 6
        elif w.startswith(("sch", "sh"), i):
            c, v = "ㅅ", ""
            i += 3 if w.startswith("sch", i) else 2
        elif w.startswith("ng", i) and i == 0:
            c, v = "ㅇ", ""
            i += 2
        elif w.startswith("ps", i) and i == 0:
            c, v = "ㅅ", ""
            i += 2
        elif w.startswith("pt", i) and i == 0:
            c, v = "ㅌ", ""
            i += 2
        elif w.startswith("ch", i):
            c, v = "ㅋ", ""
            i += 2
        elif w.startswith("th", i):
            c, v = "ㅌ", ""
            i += 2
        elif w.startswith("ph", i):
            c, v = "ㅍ", ""
            i += 2
        elif w.startswith("rh", i):
            c, v = "ㄹ", ""
            i += 2
        elif w.startswith("qu", i):
            c, v = "ㅋ", "ㅜ"
            i += 2
        elif w[i] == "x":
            if not out:
                c, v = "ㅅ", ""
            else:
                out.append(_compose_hangul("ㅋ", "ㅡ"))
                c, v = "ㅅ", ""
            i += 1
        elif w[i] not in vowels:
            ch = w[i]
            v = ""
            if ch == "w":
                if i + 1 < len(w) and w[i + 1] in "aeio":
                    v = {"a": "ㅘ", "e": "ㅞ", "i": "ㅟ", "o": "ㅝ"}.get(w[i + 1], "ㅜ")
                    c = "ㅇ"
                    i += 2
                else:
                    c = "ㅇ"
                    i += 1
                if i < len(w) and w[i] == ch:
                    i += 1
            else:
                if ch == "c":
                    c = "ㅅ" if (i + 1 < len(w) and w[i + 1] in "eiy") else "ㅋ"
                elif ch == "g":
                    c = "ㅈ" if (i + 1 < len(w) and w[i + 1] in "ei") else "ㄱ"
                else:
                    c = _CHO_MAP.get(ch, "ㅇ")
                i += 1
                if i < len(w) and w[i] == ch:
                    i += 1
        else:
            c, v = "ㅇ", ""

        # Read vowel only if not already set (e.g. qu, pseudo, w+vowel)
        if not v:
            if i < len(w) and w[i] in vowels:
                if w.startswith("ia", i) and i + 2 >= len(w):
                    out.append(_compose_hangul(c, "ㅣ"))
                    c, v = "ㅇ", "ㅏ"
                    i += 2
                elif w.startswith("io", i):
                    out.append(_compose_hangul(c, "ㅣ"))
                    c, v = "ㅇ", "ㅗ"
                    i += 2
                elif w.startswith("iu", i):
                    out.append(_compose_hangul(c, "ㅣ"))
                    c, v = "ㅇ", "ㅜ"
                    i += 2
                elif w.startswith(("ae", "oe"), i):
                    v = "ㅔ"
                    i += 2
                elif w.startswith("au", i):
                    out.append(_compose_hangul(c, "ㅏ"))
                    c, v = "ㅇ", "ㅜ"
                    i += 2
                elif w.startswith("eu", i):
                    if c in ("ㅅ", "ㅈ", "ㅊ", "ㄹ"):
                        v = "ㅠ"
                    elif c == "ㅇ" and not out:
                        v = "ㅠ"
                    else:
                        out.append(_compose_hangul(c, "ㅔ"))
                        c, v = "ㅇ", "ㅜ"
                    i += 2
                elif w.startswith("ou", i) or w.startswith("oo", i):
                    v = "ㅜ"
                    i += 2
                elif w.startswith("ee", i):
                    v = "ㅣ"
                    i += 2
                elif w.startswith("ya", i):
                    v = "ㅑ"
                    i += 2
                elif w.startswith("yo", i):
                    v = "ㅛ"
                    i += 2
                elif w.startswith("yu", i):
                    v = "ㅠ"
                    i += 2
                else:
                    v = _CHUNG_MAP.get(w[i], "ㅡ")
                    i += 1
            else:
                v = "ㅡ"

        # Optional nasal/liquid coda (n, m, ng, l) if followed by consonant or end
        jong = ""
        if i < len(w) and w[i] in ("n", "m") and (i + 1 >= len(w) or w[i + 1] not in vowels):
            if i + 1 < len(w) and w[i] == "n" and w[i + 1] == "g" and (i + 2 >= len(w) or w[i + 2] not in vowels):
                jong = "ㅇ"
                i += 2
            elif w[i] == "n":
                jong = "ㄴ"
                i += 1
            elif w[i] == "m":
                jong = "ㅁ"
                i += 1
        elif i + 1 < len(w) and w[i] == "l" and w[i + 1] != "l" and w[i + 1] not in vowels:
            jong = "ㄹ"
            i += 1

        syl = _compose_hangul(c, v, jong)
        if syl:
            out.append(syl)
        if i <= prev_i:
            i += 1
    res = "".join(out)
    return res if res else "어"


def _clean_ko_spacing_and_dups(text: str) -> str:
    s = re.sub(r"['’`\".,;:!?]+", " ", text or "")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    tokens = s.split(" ")
    cleaned: List[str] = []
    for tok in tokens:
        if not tok:
            continue
        if cleaned:
            prev = cleaned[-1]
            # Collapse exact duplicate modifier ("심해 심해첨치" -> "심해 첨치", "점박이 점박이" -> "점박이")
            if tok == prev or tok.startswith(prev):
                if len(tok) > len(prev):
                    cleaned[-1] = prev
                    rem = tok[len(prev):].strip()
                    if rem:
                        cleaned.append(rem)
                    continue
                else:
                    continue
        cleaned.append(tok)
    out = " ".join(cleaned)
    out = out.replace("심해 심해", "심해 ").replace("산호 산호", "산호 ").replace("모래 모래", "모래 ").replace("바다 바다뱀장어", "바다뱀장어")
    out = re.sub(r"\s+", " ", out).strip()
    return out


def parse_latin_epithet_ko(epithet: str) -> Tuple[str, bool]:
    """Return (Korean epithet descriptor or transliteration, is_curated_meaning)."""
    el = re.sub(r"[^a-z]", "", (epithet or "").lower())
    if not el:
        return "특수", False
    if el in EPITHET_KO_MAP:
        return EPITHET_KO_MAP[el], True

    # Try Greek/Latin compound prefix + suffix match
    for pref, p_ko in _LATIN_PREFIX_PARTS:
        if el.startswith(pref):
            rest = el[len(pref):]
            for suf, s_ko in _LATIN_SUFFIX_PARTS:
                if rest == suf or rest.startswith(suf[:5]):
                    if p_ko and s_ko and p_ko != s_ko:
                        return f"{p_ko}{s_ko}", True

    # Try geographic -ensis suffix
    if _GEO_SUFFIX_RE.search(el) and len(el) >= 7:
        stem = _GEO_SUFFIX_RE.sub("", el)
        if stem in EPITHET_KO_MAP:
            return EPITHET_KO_MAP[stem], True
        return latin_to_hangul(stem), False

    # Patronymic -i / -orum / -ae
    if el.endswith("orum") and len(el) >= 6:
        return latin_to_hangul(el[:-4]), False
    if (el.endswith("ii") or el.endswith("ae")) and len(el) >= 5:
        return latin_to_hangul(el[:-1]), False
    if el.endswith("i") and len(el) >= 5:
        return latin_to_hangul(el[:-1]), False

    return latin_to_hangul(el), False


def translate_en_fish_name(
    en_name: str,
    fam_kr: str = "",
    gtx_cache: Optional[Dict[str, str]] = None,
) -> str:
    """Translate English common fish name cleanly into natural Korean (0 ASCII letters)."""
    s = re.sub(r"\s+", " ", (en_name or "").strip())
    if not s:
        return ""
    sl = s.lower()
    head_keys = sorted(EN_HEAD_NOUNS.keys(), key=lambda x: (-len(x), x))
    matched_head = None
    prefix = s

    for hk in head_keys:
        if sl == hk:
            matched_head = EN_HEAD_NOUNS[hk]
            prefix = ""
            break
        if sl.endswith(" " + hk) or sl.endswith("-" + hk):
            matched_head = EN_HEAD_NOUNS[hk]
            prefix = s[: len(s) - len(hk) - 1].strip()
            break

    # Fallback: strip parentheticals if unmatched and retry
    if not matched_head and "(" in sl:
        no_paren = re.sub(r"\([^)]*\)", "", s).strip()
        if no_paren and no_paren != s:
            return translate_en_fish_name(no_paren, fam_kr=fam_kr, gtx_cache=gtx_cache)

    gtx = gtx_cache or {}

    def _translate_tokens(raw_prefix: str) -> str:
        tokens = re.split(r"[\s/,&]+", raw_prefix)
        parts: List[str] = []
        for tok in tokens:
            # Handle hyphenated compounds ("Two-spot", "Blue-banded")
            sub_toks = [t for t in tok.split("-") if t]
            sub_out: List[str] = []
            for st in sub_toks:
                clean = re.sub(r"('s|’s|'|’)$", "", st).strip()
                clean = re.sub(r"[^A-Za-z0-9]", "", clean)
                if not clean:
                    continue
                cl = clean.lower()
                if cl in EN_MOD_WORDS:
                    val = EN_MOD_WORDS[cl]
                    if val:
                        sub_out.append(val)
                elif cl in EN_HEAD_NOUNS:
                    sub_out.append(EN_HEAD_NOUNS[cl])
                else:
                    # Only accept gtx on single token if purely Hangul (no English leak)
                    gt = (gtx.get(st) or gtx.get(clean) or gtx.get(cl) or "").strip()
                    gt = re.sub(r"[A-Za-z0-9'’`]+", "", gt).strip()
                    if gt and re.search(r"[\uac00-\ud7a3]", gt) and len(gt) <= 12:
                        sub_out.append(gt)
                    else:
                        sub_out.append(latin_to_hangul(cl))
            if sub_out:
                parts.append("".join(sub_out) if len(sub_toks) > 1 and all(len(x) <= 4 for x in sub_out) else " ".join(sub_out))
        return " ".join(p for p in parts if p)

    if matched_head:
        mod_kr = _translate_tokens(prefix) if prefix else ""
        comb = f"{mod_kr} {matched_head}".strip() if mod_kr else matched_head
        res = _clean_ko_spacing_and_dups(comb)
    else:
        # Unknown head: translate tokens individually and append family base noun if helpful
        mod_kr = _translate_tokens(s)
        fam_base = re.sub(r"(아?과|목|속|어류)$", "", (fam_kr or "").split("(")[0].strip()).split("·")[-1].strip()
        if fam_base and fam_base not in mod_kr and len(mod_kr) <= 12:
            comb = f"{mod_kr} {fam_base}"
        else:
            comb = mod_kr
        res = _clean_ko_spacing_and_dups(comb)

    # Guarantee zero ASCII letters remain
    res = re.sub(r"[A-Za-z]+", "", res)
    res = re.sub(r"\s+", " ", res).strip()
    return res or latin_to_hangul(s)


def resolve_family_bio(
    family_sci: str,
    ancestors: List[int],
    fam_info_map: Dict[str, Dict[str, str]],
    family_biology: Dict[str, BioTuple],
    gtx_cache: Optional[Dict[str, str]] = None,
) -> BioTuple:
    """Resolve biology tuple with a guaranteed pure-Korean '...과' label (0 Latin ASCII)."""
    if family_sci in family_biology:
        return family_biology[family_sci]
    if family_sci in CURATED_MISSING_FAMILIES:
        return CURATED_MISSING_FAMILIES[family_sci]

    # Pick base biology from taxonomic Order in ancestor_ids
    base_bio: Optional[BioTuple] = None
    for aid in reversed(ancestors or []):
        if aid in ORDER_BIOLOGY:
            base_bio = ORDER_BIOLOGY[aid]
            break

    finfo = fam_info_map.get(family_sci, {})
    en_fam = (finfo.get("en") or "").lower()
    if base_bio is None:
        if any(w in en_fam for w in ("catfish", "tetra", "loach", "characin", "minnow", "carp", "knifefish", "darter")):
            base_bio = ORDER_BIOLOGY[49216]
        elif any(w in en_fam for w in ("cichlid", "killifish", "pupfish", "livebearer", "lampeye", "rainbowfish")):
            base_bio = ORDER_BIOLOGY[49333]
        elif any(w in en_fam for w in ("deep", "abyss", "angler", "grenadier", "lantern", "slickhead", "brotula", "cusk")):
            base_bio = ORDER_BIOLOGY[63741]
        elif any(w in en_fam for w in ("shark", "dogfish")):
            base_bio = ORDER_BIOLOGY[551307]
        elif any(w in en_fam for w in ("ray", "skate", "torpedo", "numbfish")):
            base_bio = ORDER_BIOLOGY[448201]
        else:
            base_bio = ("sea", "연안 갯바위·내만", (14.0, 44.0), (0.014, 3.01), 2, "all", "clear", "shrimp", "🐟", "해양어류")

    hab, zone, cm_r, wb, rar, atime, pweather, pbait, emoji, _ = base_bio

    # Build pure Korean family label
    ko_fam = (finfo.get("ko") or "").strip()
    ko_fam = re.sub(r"[A-Za-z]+", "", ko_fam).strip()
    if ko_fam and re.search(r"[\uac00-\ud7a3]", ko_fam):
        fam_kr = ko_fam if ko_fam.endswith(("과", "아과", "목", "류")) else f"{ko_fam}과"
    elif finfo.get("en"):
        en_tr = translate_en_fish_name(finfo["en"], fam_kr="", gtx_cache=gtx_cache)
        en_tr = re.sub(r"\s+", "", en_tr)
        if en_tr and not en_tr.endswith(("과", "류")):
            fam_kr = f"{en_tr}과"
        else:
            fam_kr = en_tr or f"{latin_to_hangul(re.sub(r'idae$', '', family_sci))}과"
    else:
        stem = re.sub(r"(idae|inae)$", "", family_sci or "어류")
        fam_kr = f"{latin_to_hangul(stem)}과" if family_sci else "경골어류"

    return (hab, zone, cm_r, wb, rar, atime, pweather, pbait, emoji, fam_kr)


def build_korean_species_name(
    raw: Dict[str, Any],
    fam_kr: str,
    inat_genera_map: Dict[str, Dict[str, str]],
    gtx_cache: Optional[Dict[str, str]] = None,
) -> Tuple[str, int]:
    """Return (Korean fish name with 0 ASCII chars, source_tier: 0=KO, 1=EN->KO, 2=SCI->KO)."""
    sci = raw["sci"]
    parts = sci.split()
    genus = parts[0]
    epithet = parts[1] if len(parts) > 1 else ""

    # Tier 0: Official iNaturalist / Wikidata Korean name
    ko = (raw.get("ko") or "").strip()
    if ko and re.search(r"[\uac00-\ud7a3]", ko):
        ko_clean = re.sub(r"\([^)]*[A-Za-z][^)]*\)", "", ko)
        ko_clean = re.sub(r"[A-Za-z]+", "", ko_clean)
        ko_clean = re.sub(r"\s+", " ", ko_clean).strip()
        if 2 <= len(ko_clean) <= 36:
            return ko_clean, 0

    # Tier 1: English Common Name -> Curated Biological Korean Translator
    en = (raw.get("en") or "").strip()
    if en:
        ko_from_en = translate_en_fish_name(en, fam_kr=fam_kr, gtx_cache=gtx_cache)
        if ko_from_en and re.search(r"[\uac00-\ud7a3]", ko_from_en):
            return ko_from_en[:36].strip(), 1

    # Tier 2: Binomial Scientific Name -> [Korean Epithet] + [Korean Genus]
    if genus in GENUS_KR_MAP:
        genus_kr = GENUS_KR_MAP[genus]
    else:
        ginfo = inat_genera_map.get(genus, {})
        gko = re.sub(r"(속|류)$", "", (ginfo.get("ko") or "").strip())
        gko = re.sub(r"[A-Za-z]+", "", gko).strip()
        if gko and re.search(r"[\uac00-\ud7a3]", gko):
            genus_kr = gko
        elif ginfo.get("en"):
            genus_kr = re.sub(r"\s+", "", translate_en_fish_name(ginfo["en"], fam_kr=fam_kr, gtx_cache=gtx_cache))
        else:
            fam_base = re.sub(r"(아?과|목|류)$", "", (fam_kr or "").split("(")[0].strip()).split("·")[-1].strip()
            g_han = latin_to_hangul(genus)
            if fam_base and len(fam_base) <= 6 and fam_base not in g_han:
                genus_kr = f"{g_han}{fam_base}"
            else:
                genus_kr = g_han

    epi_kr, _ = parse_latin_epithet_ko(epithet)
    combined = _clean_ko_spacing_and_dups(f"{epi_kr} {genus_kr}")
    combined = re.sub(r"[A-Za-z]+", "", combined).strip()
    return (combined[:36].strip() or latin_to_hangul(sci)), 2
