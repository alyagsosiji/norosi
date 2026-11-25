"""
cogs/other_life.py - 「타인의인생」 0세~노년 풀 스토리 인생 시뮬레이션 Cog
- /타인의인생 플레이 [출신] [시간배율] : 실시간 시간 배율(60초=1년 표준 / 30초 쾌속 / 3분 슬로우 / 턴제) + 능동 분기 선택
- /타인의인생 도감 : 1,000종 멀티 엔딩 도감(필터·검색·요약) & 내 과거 인생 전기 아카이브 열람
- /타인의인생 랭킹 : 서버 엔딩 수집 · 최고 점수 · 최장 수명 랭킹 보드
- !타인의인생 / !인생게임 / !타인 : 빠른 접두사 단축어 지원
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

import core
import other_life_core
import other_life_endings
import other_life_narratives


def _fit_lines_block(lines: List[str], max_chars: int = 980, fallback: str = "> (기록 없음)") -> str:
    kept: List[str] = []
    total = 0
    for ln in reversed(lines):
        item = str(ln)
        if len(item) > max_chars - 10:
            item = item[: max_chars - 11] + "…"
        added = len(item) + (1 if kept else 0)
        if total + added > max_chars:
            break
        kept.append(item)
        total += added
    if not kept:
        return fallback
    kept.reverse()
    return "\n".join(kept)


def _chunk_text_blocks(blocks: List[str], max_chars: int = 980) -> List[str]:
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for blk in blocks:
        s = str(blk)
        if len(s) > max_chars:
            s = s[: max_chars - 1] + "…"
        added = len(s) + (1 if cur else 0)
        if cur and cur_len + added > max_chars:
            chunks.append("\n".join(cur))
            cur = [s]
            cur_len = len(s)
        else:
            cur.append(s)
            cur_len += added
    if cur:
        chunks.append("\n".join(cur))
    return chunks or ["*(선택지 없음)*"]


def _stat_bar(val: int) -> str:
    clamped = max(0, min(100, int(val or 0)))
    filled = round(clamped / 20)
    return ("▓" * filled + "░" * (5 - filled)) + f" `{clamped:02d}`"


def _format_stats_block(stats: Dict[str, Any]) -> str:
    return (
        f"🧠 지성 {_stat_bar(stats.get('intellect', 0))}  ·  "
        f"🔥 열정 {_stat_bar(stats.get('passion', 0))}  ·  "
        f"💗 공감 {_stat_bar(stats.get('empathy', 0))}\n"
        f"🛡️ 근성 {_stat_bar(stats.get('grit', 0))}  ·  "
        f"🪙 자산 {_stat_bar(stats.get('wealth', 0))}"
    )


def _next_tick_text(life: Dict[str, Any]) -> str:
    if life.get("finished"):
        return "인생 완결"
    scale_id = str(life.get("time_scale") or other_life_core.DEFAULT_TIME_SCALE)
    scale = other_life_core.TIME_SCALES.get(scale_id, other_life_core.TIME_SCALES[other_life_core.DEFAULT_TIME_SCALE])
    sec_per_year = int(scale.get("sec_per_year", 0))
    if sec_per_year <= 0:
        return "📖 턴제 정주행 (대기 없음)"

    cur_age = int(life.get("age", 6) or 6)
    ceiling = other_life_core._stage_age_ceiling(int(life.get("beat", 1) or 1), cur_age)
    idle_used_beat = int(life.get("idle_years_beat", 0) or 0)
    if cur_age >= ceiling or idle_used_beat >= other_life_core.MAX_IDLE_YEARS_PER_BEAT:
        return f"⏸️ {cur_age}세 분기점 숙성 완료 (선택지 클릭 시 다음 챕터로)"

    now_f = datetime.datetime.now(core.KST).timestamp()
    last_f = float(life.get("last_tick_at") or now_f)
    rem = max(0, int(sec_per_year - max(0.0, now_f - last_f)))
    if rem == 0:
        return f"⏳ 다음 일상(+1세) 반영 대기 중 (`🔄 세월 확인` 클릭)"
    if rem >= 60:
        m, s = divmod(rem, 60)
        return f"⏳ 다음 +1세까지 `{m}분 {s:02d}초` *(상한 {ceiling}세 · 즉시 진행 가능)*"
    return f"⏳ 다음 +1세까지 `{rem}초` *(상한 {ceiling}세 · 즉시 진행 가능)*"


def _progress_bar_str(cur: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width + " 0.0%"
    ratio = max(0.0, min(1.0, cur / total))
    filled = int(round(ratio * width))
    return ("█" * filled + "░" * (width - filled)) + f" {cur}/{total} ({ratio * 100:.1f}%)"


# ==========================================
# 1. Setup Selects (출신 & 시간 배율)
# ==========================================
class OtherLifeOriginSelect(discord.ui.Select):
    def __init__(self, parent_view: "OtherLifeGameView", selected_origin: str):
        self.parent_view = parent_view
        opts = [
            discord.SelectOption(
                label="🎲 운명에 맡기기 (무작위 출신)",
                value="random",
                description="6가지 출신 배경 중 하나가 랜덤하게 배정됩니다",
                emoji="🎲",
                default=(selected_origin == "random"),
            )
        ]
        for oid, orig in other_life_core.ORIGINS.items():
            opts.append(discord.SelectOption(
                label=orig["name"][:95],
                value=oid,
                description=orig["hook"][:95],
                default=(selected_origin == oid),
            ))
        super().__init__(
            placeholder="🧬 태어날 출신 환경 선택...",
            min_values=1,
            max_values=1,
            options=opts[:25],
            row=0,
            custom_id="norosi:OtherLifeGameView:origin_select",
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        await core.safe_defer(interaction)
        pv.selected_origin = self.values[0]
        pv.status_msg = (
            "🎲 무작위 출신을 선택했습니다."
            if pv.selected_origin == "random"
            else f"🧬 출신지를 **{other_life_core.ORIGINS[pv.selected_origin]['name']}**(으)로 예약했습니다."
        )
        pv._rebuild()
        await core.safe_edit_response(interaction, embed=pv.build_embed(), view=pv)


class OtherLifeScaleSelect(discord.ui.Select):
    def __init__(self, parent_view: "OtherLifeGameView", current_scale: str, row: int = 1):
        self.parent_view = parent_view
        opts = []
        for sid, sc in other_life_core.TIME_SCALES.items():
            opts.append(discord.SelectOption(
                label=sc["name"][:95],
                value=sid,
                description=sc["short_desc"][:95],
                emoji=sc["emoji"],
                default=(sid == current_scale),
            ))
        super().__init__(
            placeholder="⏱️ 세월 시간 배율 변경...",
            min_values=1,
            max_values=1,
            options=opts[:25],
            row=row,
            custom_id="norosi:OtherLifeGameView:scale_select",
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        await core.safe_defer(interaction)
        new_scale = self.values[0]
        pv.selected_scale = new_scale
        ok, msg, updated_u = await asyncio.to_thread(
            other_life_core.set_life_time_scale,
            pv.guild_id,
            interaction.user.id,
            new_scale,
            interaction.user.display_name,
        )
        pv.user_state = updated_u
        pv.status_msg = msg
        pv._rebuild()
        await core.safe_edit_response(interaction, embed=pv.build_embed(), view=pv)


class OtherLifeSpecialtySelect(discord.ui.Select):
    def __init__(self, parent_view: "OtherLifeGameView", career: str, current_spec: str, row: int = 1):
        self.parent_view = parent_view
        allowed = other_life_core.CAREER_SPECIALTIES.get(career, [])
        opts = []
        for sid in allowed:
            smeta = other_life_core.SPECIALTY_CATALOG.get(sid)
            if not smeta:
                continue
            opts.append(discord.SelectOption(
                label=smeta["title"][:95],
                value=sid,
                description=f"무대: {smeta['workplace']}"[:95],
                emoji=smeta["emoji"],
                default=(sid == current_spec),
            ))
        super().__init__(
            placeholder="🎯 세부 전공 선택·변경 (22세 첫 무대 전용)...",
            min_values=1,
            max_values=1,
            options=opts[:25],
            row=row,
            custom_id="norosi:OtherLifeGameView:specialty_select",
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        await core.safe_defer(interaction)
        new_spec = self.values[0]
        ok, msg, updated_u = await asyncio.to_thread(
            other_life_core.set_life_specialty,
            pv.guild_id,
            interaction.user.id,
            new_spec,
            interaction.user.display_name,
        )
        pv.user_state = updated_u
        pv.status_msg = msg
        pv._rebuild()
        await core.safe_edit_response(interaction, embed=pv.build_embed(), view=pv)


# ==========================================
# 2. 새 인생 시작 확인 View (진행 중 덮어쓰기 방지)
# ==========================================
class OtherLifeConfirmResetView(core.SafeView):
    def __init__(
        self,
        parent_view: Optional["OtherLifeGameView"] = None,
        user: Optional[discord.abc.User] = None,
        guild_id: int = 0,
    ):
        super().__init__(timeout=60)
        self.parent_view = parent_view
        self.user = user or (parent_view.user if parent_view else None)
        self.guild_id = int(guild_id or (parent_view.guild_id if parent_view else 0))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인만 선택할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🧬 출신·배율 골라서 새로 시작", style=discord.ButtonStyle.danger, row=0)
    async def btn_confirm_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        u_state, _, _ = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        gv = self.parent_view or OtherLifeGameView(interaction.user, self.guild_id, user_state=u_state)
        gv.user_state = u_state
        gv.mode = "setup"
        gv.status_msg = "🧬 새로운 타인의 인생을 시작하기 위해 출신과 배율을 선택해 주세요."
        gv._rebuild()
        await core.safe_edit_response(interaction, embed=gv.build_embed(), view=gv)

    @discord.ui.button(label="🌱 랜덤으로 즉시 시작", style=discord.ButtonStyle.success, row=0)
    async def btn_confirm_quick(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg, u_state = await asyncio.to_thread(
            other_life_core.start_new_life,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        gv = self.parent_view or OtherLifeGameView(interaction.user, self.guild_id, user_state=u_state)
        gv.user_state = u_state
        gv.mode = "play"
        gv.status_msg = msg
        gv._rebuild()
        await core.safe_edit_response(interaction, embed=gv.build_embed(), view=gv)

    @discord.ui.button(label="◀ 지금 인생 계속하기", style=discord.ButtonStyle.secondary, row=0)
    async def btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        u_state, yrs, logs = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        gv = self.parent_view or OtherLifeGameView(interaction.user, self.guild_id, user_state=u_state)
        gv.user_state = u_state
        gv.mode = "play"
        gv.idle_logs = logs
        gv.status_msg = "📖 현재 살아가던 인생으로 돌아왔습니다."
        gv._rebuild()
        await core.safe_edit_response(interaction, embed=gv.build_embed(), view=gv)


# ==========================================
# 3. 도감 & 연대기 View (1,000종 멀티 엔딩 도감 · 필터 · 검색 · 수집 요약)
# ==========================================
_RARITY_DISPLAY_ORDER = ["신화", "히든", "전설", "희귀", "일반"]
_RARITY_EMOJIS = {
    "신화": "🌠",
    "히든": "🌌",
    "전설": "🔥",
    "희귀": "💠",
    "일반": "🏡",
}


class OtherLifeCollectionSearchModal(core.SafeModal, title="🔍 1,000종 엔딩 도감 검색 & 페이지 이동"):
    keyword = discord.ui.TextInput(
        label="검색어 (비워두면 검색 초기화)",
        placeholder="예: 국수, 별을 건너다, 해송원, 신화, 의학, 39세...",
        required=False,
        max_length=50,
    )
    page_jump = discord.ui.TextInput(
        label="바로 이동할 페이지 번호 (선택)",
        placeholder="숫자만 입력 (예: 12)",
        required=False,
        max_length=5,
    )

    def __init__(self, parent_view: "OtherLifeCollectionView"):
        super().__init__()
        self.parent_view = parent_view
        if parent_view.search_query:
            self.keyword.default = parent_view.search_query

    async def on_submit(self, interaction: discord.Interaction):
        pv = self.parent_view
        kw = (self.keyword.value or "").strip()
        pj = (self.page_jump.value or "").strip()

        if kw != pv.search_query:
            pv.search_query = kw
            pv.page = 0
            pv.tab = "endings"

        if pj.isdigit():
            pv.tab = "endings"
            target_p = max(1, int(pj)) - 1
            pv.page = min(pv._max_page(), target_p)
        else:
            pv.page = max(0, min(pv._max_page(), pv.page))

        pv._rebuild()
        emb = pv.build_embed()
        try:
            await core.safe_edit_response(interaction, embed=emb, view=pv, raise_on_error=True)
        except Exception:
            if pv.message is not None:
                try:
                    await pv.message.edit(embed=emb, view=pv)
                except Exception:
                    pass
            await core.safe_send_response(interaction, "🔍 검색 및 페이지 필터를 적용했습니다.", ephemeral=True)


class OtherLifeCollectionStatusSelect(discord.ui.Select):
    def __init__(self, parent_view: "OtherLifeCollectionView", current: str):
        self.parent_view = parent_view
        options_def = [
            ("all", "🌐 해금/등급: 전체 보기 (1,000종)", "🌐"),
            ("unlocked", "✅ 해금 완료만 보기", "✅"),
            ("locked", "🔒 미해금(달성 힌트)만 보기", "🔒"),
            ("rarity:신화", "🌠 신화 등급만 보기 (4종)", "🌠"),
            ("rarity:히든", "🌌 히든 등급만 보기", "🌌"),
            ("rarity:전설", "🔥 전설 등급만 보기", "🔥"),
            ("rarity:희귀", "💠 희귀 등급만 보기", "💠"),
            ("rarity:일반", "🏡 일반 등급만 보기", "🏡"),
        ]
        opts = [
            discord.SelectOption(
                label=lbl[:95],
                value=val,
                emoji=emo,
                default=(current == val),
            )
            for val, lbl, emo in options_def
        ]
        super().__init__(
            placeholder="🔍 해금 여부 · 등급 필터...",
            min_values=1,
            max_values=1,
            options=opts[:25],
            row=1,
            custom_id="norosi:OtherLifeCollectionView:status_select",
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        await core.safe_defer(interaction)
        pv.status_filter = self.values[0]
        pv.page = 0
        pv._rebuild()
        await core.safe_edit_response(interaction, embed=pv.build_embed(), view=pv)


class OtherLifeCollectionCareerSelect(discord.ui.Select):
    def __init__(self, parent_view: "OtherLifeCollectionView", current: str):
        self.parent_view = parent_view
        options_def = [
            ("all", "🎯 진로·계열: 전체 보기", "🎯"),
            ("group_a", "🎭 공용 서사 276종 (Group A)", "🎭"),
            ("artist", "🎨 예술·창작가 계열", "🎨"),
            ("scholar", "🔬 학자·연구자 계열", "🔬"),
            ("entrepreneur", "💼 사업·개척가 계열", "💼"),
            ("artisan", "🌿 장인·생활인 계열", "🌿"),
            ("guardian", "⚖️ 수호·언론인 계열", "⚖️"),
            ("wanderer", "🧭 방랑·기록가 계열", "🧭"),
            ("shadow", "🕶️ 그림자 브로커 계열", "🕶️"),
            ("myth", "🌠 출신 초월 신화 (Group C)", "🌠"),
        ]
        opts = [
            discord.SelectOption(
                label=lbl[:95],
                value=val,
                emoji=emo,
                default=(current == val),
            )
            for val, lbl, emo in options_def
        ]
        super().__init__(
            placeholder="🎯 진로 · 계열 필터...",
            min_values=1,
            max_values=1,
            options=opts[:25],
            row=2,
            custom_id="norosi:OtherLifeCollectionView:career_select",
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        await core.safe_defer(interaction)
        pv.career_filter = self.values[0]
        pv.page = 0
        pv._rebuild()
        await core.safe_edit_response(interaction, embed=pv.build_embed(), view=pv)


class OtherLifeCollectionOriginSelect(discord.ui.Select):
    def __init__(self, parent_view: "OtherLifeCollectionView", current: str):
        self.parent_view = parent_view
        opts = [
            discord.SelectOption(
                label="🧬 출신 배경: 전체 보기",
                value="all",
                emoji="🧬",
                default=(current == "all"),
            )
        ]
        for oid in other_life_endings.ORIGIN_ORDER:
            orig = other_life_core.ORIGINS.get(oid)
            if not orig:
                continue
            opts.append(discord.SelectOption(
                label=orig["name"][:70],
                value=oid,
                default=(current == oid),
            ))
        opts.append(discord.SelectOption(
            label="🌠 신화 (출신 초월 4종)",
            value="myth",
            emoji="🌠",
            default=(current == "myth"),
        ))
        super().__init__(
            placeholder="🧬 출신 배경 필터...",
            min_values=1,
            max_values=1,
            options=opts[:25],
            row=3,
            custom_id="norosi:OtherLifeCollectionView:origin_select",
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        await core.safe_defer(interaction)
        pv.origin_filter = self.values[0]
        pv.page = 0
        pv._rebuild()
        await core.safe_edit_response(interaction, embed=pv.build_embed(), view=pv)


class OtherLifeCollectionView(core.SafeView):
    def __init__(
        self,
        user: Optional[discord.abc.User] = None,
        guild_id: int = 0,
        user_state: Optional[Dict[str, Any]] = None,
        tab: str = "endings",
    ):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        if user_state is None:
            uid = user.id if user else 0
            uname = user.display_name if user else "여행자"
            u_state, _, _ = other_life_core.get_other_life_state(self.guild_id, uid, uname)
            self.user_state = u_state
        else:
            self.user_state = user_state
        self.tab = tab if tab in ("endings", "summary", "history") else "endings"
        self.page = 0
        self.status_filter = "all"
        self.career_filter = "all"
        self.origin_filter = "all"
        self.search_query = ""
        self._rebuild()

    def _restore_from_message(self, interaction: discord.Interaction):
        msg = getattr(interaction, "message", None)
        if not msg:
            return
        for row in getattr(msg, "components", []) or []:
            for comp in getattr(row, "children", []):
                cid = getattr(comp, "custom_id", "") or ""
                st = getattr(comp, "style", None)
                if cid == "norosi:OtherLifeCollectionView:tab_summary" and st == discord.ButtonStyle.primary:
                    self.tab = "summary"
                elif cid == "norosi:OtherLifeCollectionView:tab_endings" and st == discord.ButtonStyle.primary:
                    self.tab = "endings"
                elif cid == "norosi:OtherLifeCollectionView:tab_history" and st == discord.ButtonStyle.primary:
                    self.tab = "history"
                elif cid == "norosi:OtherLifeCollectionView:status_select":
                    for opt in getattr(comp, "options", []) or []:
                        if getattr(opt, "default", False) and getattr(opt, "value", None):
                            self.status_filter = str(opt.value)
                elif cid == "norosi:OtherLifeCollectionView:career_select":
                    for opt in getattr(comp, "options", []) or []:
                        if getattr(opt, "default", False) and getattr(opt, "value", None):
                            self.career_filter = str(opt.value)
                elif cid == "norosi:OtherLifeCollectionView:origin_select":
                    for opt in getattr(comp, "options", []) or []:
                        if getattr(opt, "default", False) and getattr(opt, "value", None):
                            self.origin_filter = str(opt.value)
        embeds = getattr(msg, "embeds", None) or []
        if embeds and getattr(embeds[0], "description", None):
            import re
            m = re.search(r"페이지\s*`?(\d+)\s*/\s*(\d+)`?", embeds[0].description)
            if m:
                self.page = max(0, int(m.group(1)) - 1)
        self._rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 도감은 **{self.user.display_name}**님의 기록입니다. `/설정` (`🎮 미니게임` ➔ `📚 통합 도감 & 확률 허브`)에서 열어주세요!",
                ephemeral=True,
            )
            return False
        return True

    def _slot_tag(self, em: Dict[str, Any]) -> str:
        oid = str(em.get("origin_id") or "")
        cid = str(em.get("career") or "")
        sid = str(em.get("specialty_id") or "")
        if oid == "myth" or cid == "myth":
            return "🌠 신화 · 출신 초월"
        o_lbl = other_life_endings.ORIGIN_MOTIFS.get(oid, {}).get("label", oid)
        if sid and sid in other_life_core.SPECIALTY_CATALOG:
            spec_t = other_life_core.SPECIALTY_CATALOG[sid]["title"]
            return f"{o_lbl} · {spec_t}"
        c_lbl = other_life_endings.CAREER_LITERARY.get(cid, {}).get("name", cid)
        return f"{o_lbl} · {c_lbl}"

    def _filtered_ending_ids(self) -> List[str]:
        unlocked = self.user_state.get("unlocked_endings") or {}
        q = self.search_query.strip().lower()
        res: List[str] = []
        for eid, em in other_life_core.ENDINGS.items():
            is_unlocked = unlocked.get(eid, 0) > 0
            if self.status_filter == "unlocked" and not is_unlocked:
                continue
            elif self.status_filter == "locked" and is_unlocked:
                continue
            elif self.status_filter.startswith("rarity:"):
                req_r = self.status_filter.split(":", 1)[1]
                if em.get("rarity") != req_r:
                    continue

            if self.career_filter == "group_a":
                if em.get("group") != "A":
                    continue
            elif self.career_filter == "myth":
                if em.get("group") != "C":
                    continue
            elif self.career_filter != "all":
                if em.get("career") != self.career_filter:
                    continue

            if self.origin_filter != "all":
                if em.get("origin_id") != self.origin_filter:
                    continue

            if q:
                arch_name = other_life_core.ARCHETYPE_META.get(str(em.get("archetype") or ""), {}).get("name", "")
                slot_tag = self._slot_tag(em)
                parts = [
                    slot_tag,
                    str(em.get("rarity") or ""),
                    str(em.get("hint") or ""),
                    arch_name,
                ]
                if is_unlocked:
                    parts.append(str(em.get("title") or ""))
                    parts.append(str(em.get("summary") or ""))
                if q not in " ".join(parts).lower():
                    continue

            res.append(eid)
        return res

    def _max_page(self) -> int:
        if self.tab == "endings":
            filtered = self._filtered_ending_ids()
            if not filtered:
                return 0
            return max(0, (len(filtered) - 1) // 6)
        if self.tab == "history":
            hist = self.user_state.get("history") or []
            if not hist:
                return 0
            return max(0, (len(hist) - 1) // 5)
        return 0

    def _rebuild(self):
        self.clear_items()
        total_endings = len(other_life_core.ENDINGS)

        # Row 0: Navigation (Summary / Endings / History / Play)
        btn_summary = discord.ui.Button(
            label="📊 수집 요약",
            style=discord.ButtonStyle.primary if self.tab == "summary" else discord.ButtonStyle.secondary,
            row=0,
            custom_id="norosi:OtherLifeCollectionView:tab_summary",
        )
        btn_summary.callback = self._on_tab_summary
        self.add_item(btn_summary)

        btn_endings = discord.ui.Button(
            label=f"📚 도감 ({total_endings:,}종)",
            style=discord.ButtonStyle.primary if self.tab == "endings" else discord.ButtonStyle.secondary,
            row=0,
            custom_id="norosi:OtherLifeCollectionView:tab_endings",
        )
        btn_endings.callback = self._on_tab_endings
        self.add_item(btn_endings)

        btn_history = discord.ui.Button(
            label="📖 전기 기록",
            style=discord.ButtonStyle.primary if self.tab == "history" else discord.ButtonStyle.secondary,
            row=0,
            custom_id="norosi:OtherLifeCollectionView:tab_history",
        )
        btn_history.callback = self._on_tab_history
        self.add_item(btn_history)

        btn_play = discord.ui.Button(
            label="🎮 인생 플레이로 이동",
            style=discord.ButtonStyle.success,
            row=0,
            custom_id="norosi:OtherLifeCollectionView:open_play",
        )
        btn_play.callback = self._on_open_play
        self.add_item(btn_play)

        max_p = self._max_page()
        self.page = max(0, min(self.page, max_p))

        if self.tab == "endings":
            # Row 1~3: 3-axis filter Selects
            self.add_item(OtherLifeCollectionStatusSelect(self, self.status_filter))
            self.add_item(OtherLifeCollectionCareerSelect(self, self.career_filter))
            self.add_item(OtherLifeCollectionOriginSelect(self, self.origin_filter))

            # Row 4: -10p / prev / search / next / +10p
            btn_prev10 = discord.ui.Button(
                label="⏪ -10p",
                style=discord.ButtonStyle.secondary,
                disabled=(self.page <= 0),
                row=4,
                custom_id="norosi:OtherLifeCollectionView:prev10",
            )
            btn_prev10.callback = self._on_prev10
            self.add_item(btn_prev10)

            btn_prev = discord.ui.Button(
                label="◀ 이전",
                style=discord.ButtonStyle.secondary,
                disabled=(self.page <= 0),
                row=4,
                custom_id="norosi:OtherLifeCollectionView:prev",
            )
            btn_prev.callback = self._on_prev
            self.add_item(btn_prev)

            search_lbl = f"🔍 검색 ({self.search_query[:8]}…)" if len(self.search_query) > 8 else (f"🔍 검색: {self.search_query}" if self.search_query else "🔍 검색/이동")
            btn_search = discord.ui.Button(
                label=search_lbl[:45],
                style=discord.ButtonStyle.primary if self.search_query else discord.ButtonStyle.secondary,
                row=4,
                custom_id="norosi:OtherLifeCollectionView:search",
            )
            btn_search.callback = self._on_search
            self.add_item(btn_search)

            btn_next = discord.ui.Button(
                label="다음 ▶",
                style=discord.ButtonStyle.secondary,
                disabled=(self.page >= max_p),
                row=4,
                custom_id="norosi:OtherLifeCollectionView:next",
            )
            btn_next.callback = self._on_next
            self.add_item(btn_next)

            btn_next10 = discord.ui.Button(
                label="⏩ +10p",
                style=discord.ButtonStyle.secondary,
                disabled=(self.page >= max_p),
                row=4,
                custom_id="norosi:OtherLifeCollectionView:next10",
            )
            btn_next10.callback = self._on_next10
            self.add_item(btn_next10)

        elif self.tab == "history":
            btn_prev = discord.ui.Button(
                label="◀ 이전",
                style=discord.ButtonStyle.secondary,
                disabled=(self.page <= 0),
                row=1,
                custom_id="norosi:OtherLifeCollectionView:prev",
            )
            btn_prev.callback = self._on_prev
            self.add_item(btn_prev)

            btn_next = discord.ui.Button(
                label="다음 ▶",
                style=discord.ButtonStyle.secondary,
                disabled=(self.page >= max_p),
                row=1,
                custom_id="norosi:OtherLifeCollectionView:next",
            )
            btn_next.callback = self._on_next
            self.add_item(btn_next)

    def build_embed(self) -> discord.Embed:
        u = self.user_state
        uname = self.user.display_name if self.user else u.get("user_name", "플레이어")
        unlocked = u.get("unlocked_endings") or {}
        unlocked_cnt = len([k for k in unlocked if k in other_life_core.ENDINGS])
        total_endings = len(other_life_core.ENDINGS)

        # ── Tab 1: 수집 통계 요약 ──
        if self.tab == "summary":
            rarity_totals: Dict[str, int] = {r: 0 for r in _RARITY_DISPLAY_ORDER}
            rarity_unlocked: Dict[str, int] = {r: 0 for r in _RARITY_DISPLAY_ORDER}
            origin_totals: Dict[str, int] = {oid: 0 for oid in other_life_endings.ORIGIN_ORDER + ["myth"]}
            origin_unlocked: Dict[str, int] = {oid: 0 for oid in other_life_endings.ORIGIN_ORDER + ["myth"]}
            career_totals: Dict[str, int] = {c: 0 for c in other_life_endings.ALL_CAREERS + ["myth"]}
            career_unlocked: Dict[str, int] = {c: 0 for c in other_life_endings.ALL_CAREERS + ["myth"]}
            group_totals = {"A": 0, "B": 0, "C": 0}
            group_unlocked = {"A": 0, "B": 0, "C": 0}

            for eid, em in other_life_core.ENDINGS.items():
                is_u = unlocked.get(eid, 0) > 0
                r = str(em.get("rarity") or "일반")
                oid = str(em.get("origin_id") or "orphanage")
                cid = str(em.get("career") or "artisan")
                grp = str(em.get("group") or "B")
                if r in rarity_totals:
                    rarity_totals[r] += 1
                    if is_u:
                        rarity_unlocked[r] += 1
                if oid in origin_totals:
                    origin_totals[oid] += 1
                    if is_u:
                        origin_unlocked[oid] += 1
                if cid in career_totals:
                    career_totals[cid] += 1
                    if is_u:
                        career_unlocked[cid] += 1
                if grp in group_totals:
                    group_totals[grp] += 1
                    if is_u:
                        group_unlocked[grp] += 1

            embed = discord.Embed(
                title=f"📊 {uname}님의 타인의 인생 수집 요약 ({unlocked_cnt}/{total_endings:,}종)",
                description=(
                    f"누적 완결 생애 **`{u.get('lives_completed', 0)}회`** · "
                    f"최고 점수 **`{u.get('best_score', 0):,}점`** · "
                    f"최장 수명 **`{u.get('longest_age', 0)}세`**\n\n"
                    f"**🏆 전체 도감 달성률**\n"
                    f"`{_progress_bar_str(unlocked_cnt, total_endings, 14)}`\n"
                    f"• 공용 서사(Group A): **`{group_unlocked['A']}/{group_totals['A']}`** · "
                    f"세부 전공(Group B): **`{group_unlocked['B']}/{group_totals['B']}`** · "
                    f"신화(Group C): **`{group_unlocked['C']}/{group_totals['C']}`**"
                )[:4000],
                color=0xA855F7,
                timestamp=datetime.datetime.now(core.KST),
            )

            rarity_lines = [
                f"{_RARITY_EMOJIS.get(r, '✨')} **{r}**: `{_progress_bar_str(rarity_unlocked[r], rarity_totals[r], 8)}`"
                for r in _RARITY_DISPLAY_ORDER
            ]
            embed.add_field(
                name="✨ 등급별 수집 현황",
                value="\n".join(rarity_lines)[:1024],
                inline=False,
            )

            origin_lines = []
            for oid in other_life_endings.ORIGIN_ORDER:
                o_name = other_life_core.ORIGINS.get(oid, {}).get("name", oid)
                origin_lines.append(f"{o_name}: `{_progress_bar_str(origin_unlocked[oid], origin_totals[oid], 8)}`")
            origin_lines.append(f"🌠 출신 초월(신화): `{_progress_bar_str(origin_unlocked['myth'], origin_totals['myth'], 8)}`")
            embed.add_field(
                name="🧬 출신 배경별 수집 현황",
                value="\n".join(origin_lines)[:1024],
                inline=False,
            )

            career_lines = []
            for cid in other_life_endings.ALL_CAREERS:
                cm = other_life_core.CAREER_META.get(cid, {"emoji": "🌱", "name": cid})
                career_lines.append(f"{cm['emoji']} **{cm['name']}**: `{_progress_bar_str(career_unlocked[cid], career_totals[cid], 8)}`")
            career_lines.append(f"🌠 **출신 초월 신화**: `{_progress_bar_str(career_unlocked['myth'], career_totals['myth'], 8)}`")
            embed.add_field(
                name="🎯 진로 계열별 수집 현황",
                value="\n".join(career_lines)[:1024],
                inline=False,
            )
            embed.set_footer(text="📚 도감 탭에서 미해금 엔딩의 구체적 달성 힌트와 검색 기능을 이용할 수 있습니다")
            return embed

        # ── Tab 2: 1,000종 엔딩 도감 (필터·검색·힌트) ──
        if self.tab == "endings":
            filtered_ids = self._filtered_ending_ids()
            per = 6
            max_p = self._max_page()
            self.page = max(0, min(self.page, max_p))
            slice_ids = filtered_ids[self.page * per:(self.page + 1) * per]

            lines = []
            for eid in slice_ids:
                em = other_life_core.ENDINGS[eid]
                cnt = unlocked.get(eid, 0)
                if cnt > 0:
                    lines.append(
                        f"{em['emoji']} **{em['title']}** `[{em['rarity']} · {cnt}회]` (+{em['base_crystal']}💎)\n"
                        f"> {em['summary']}"
                    )
                else:
                    slot_tag = self._slot_tag(em)
                    hint = str(em.get("hint") or "다양한 출신과 선택을 시도해 보세요.")
                    if len(hint) > 150:
                        hint = hint[:149] + "…"
                    lines.append(
                        f"🔒 **[{slot_tag}] ???** `[{em['rarity']}]` *(초회 +120💎)*\n"
                        f"> 💡 {hint}"
                    )

            filter_badges: List[str] = []
            if self.status_filter != "all":
                st_label = {
                    "unlocked": "해금완료",
                    "locked": "미해금",
                }.get(self.status_filter, self.status_filter.replace("rarity:", "등급:"))
                filter_badges.append(st_label)
            if self.career_filter != "all":
                c_lbl = (
                    "공용276" if self.career_filter == "group_a"
                    else "신화" if self.career_filter == "myth"
                    else other_life_core.CAREER_META.get(self.career_filter, {}).get("name", self.career_filter)
                )
                filter_badges.append(c_lbl)
            if self.origin_filter != "all":
                o_lbl = "신화" if self.origin_filter == "myth" else other_life_endings.ORIGIN_MOTIFS.get(self.origin_filter, {}).get("label", self.origin_filter)
                filter_badges.append(o_lbl)
            if self.search_query:
                filter_badges.append(f"검색:'{self.search_query}'")

            filter_line = f"🔎 **적용 필터 ({len(filtered_ids):,}건 일치):** " + " · ".join(filter_badges) + "\n" if filter_badges else f"🔎 **전체 목록:** `{len(filtered_ids):,}건` 표시 중\n"
            body_txt = "\n\n".join(lines) if lines else "*(선택한 조건·검색어에 해당하는 엔딩이 없습니다. 필터를 완화하거나 검색어를 비워보세요!)*"

            embed = discord.Embed(
                title=f"📚 {uname}님의 타인의 인생 엔딩 도감 ({unlocked_cnt}/{total_endings:,}종)",
                description=(
                    f"누적 완결 **`{u.get('lives_completed', 0)}회`** · "
                    f"최고 **`{u.get('best_score', 0):,}점`** · "
                    f"최장 **`{u.get('longest_age', 0)}세`**\n"
                    f"{filter_line}"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    + body_txt
                )[:4000],
                color=0x8B5CF6,
                timestamp=datetime.datetime.now(core.KST),
            )
            embed.set_footer(
                text=f"엔딩 도감 {self.page + 1} / {max_p + 1} 페이지 (필터 {len(filtered_ids):,}종)  •  초회 해금 시 +120💎 보너스"
            )
            return embed

        # ── Tab 3: 전기 기록 ──
        hist = u.get("history") or []
        active = u.get("active_life")
        blocks: List[str] = []
        if isinstance(active, dict) and not active.get("finished") and self.page == 0:
            tail = (active.get("chronicle") or [])[-5:]
            blocks.append(
                f"🌱 **현재 진행 중: {active.get('name')} ({active.get('age')}세 · {active.get('beat')}/18장)**\n"
                + "\n".join(f"> {c}" for c in tail)
            )

        if not hist:
            if not blocks:
                blocks.append("*(아직 완결된 타인의 인생 전기가 없습니다. 첫 생애를 끝까지 살아보세요!)*")
        else:
            per = 5
            start = self.page * per
            for idx, h in enumerate(hist[start:start + per], start + 1):
                orig_name = other_life_core.ORIGINS.get(str(h.get("origin_id")), {}).get("place", "알 수 없는 곳")
                role_lbl = h.get("specialty_label") or h.get("career_label") or "방랑"
                tail_s = "\n".join(f"  {t}" for t in (h.get("chronicle_tail") or [])[-3:])
                blocks.append(
                    f"`#{idx}` {h.get('ending_emoji', '📖')} **{h.get('name')}** "
                    f"({h.get('age', 0)}세 · {role_lbl}) — **{h.get('ending_title')}** `[{h.get('score', 0):,}점]`\n"
                    f"출신: {orig_name} · {h.get('finished_at', '')}\n{tail_s}"
                )

        embed = discord.Embed(
            title=f"📖 {uname}님의 타인의 인생 전기 아카이브",
            description="\n\n".join(blocks)[:4000],
            color=0x0EA5E9,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text=f"전기 아카이브 {self.page + 1} / {self._max_page() + 1} 페이지 (최근 50생애 보존)")
        return embed

    async def _on_tab_summary(self, interaction: discord.Interaction):
        self.tab = "summary"
        self.page = 0
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_tab_endings(self, interaction: discord.Interaction):
        self.tab = "endings"
        self.page = 0
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_tab_history(self, interaction: discord.Interaction):
        self.tab = "history"
        self.page = 0
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_prev10(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 10)
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_prev(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_next(self, interaction: discord.Interaction):
        self.page = min(self._max_page(), self.page + 1)
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_next10(self, interaction: discord.Interaction):
        self.page = min(self._max_page(), self.page + 10)
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_search(self, interaction: discord.Interaction):
        await interaction.response.send_modal(OtherLifeCollectionSearchModal(self))

    async def _on_open_play(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        u_state, _, idle_logs = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        gv = OtherLifeGameView(interaction.user, self.guild_id, user_state=u_state, idle_logs=idle_logs)
        await core.safe_edit_response(interaction, embed=gv.build_embed(), view=gv)



# ==========================================
# 3-B. 현재 생애 전체 일대기 & 전환점 View
# ==========================================
class OtherLifeChronicleView(core.SafeView):
    def __init__(
        self,
        user: Optional[discord.abc.User] = None,
        guild_id: int = 0,
        user_state: Optional[Dict[str, Any]] = None,
        parent_view: Optional["OtherLifeGameView"] = None,
        page: int = 0,
    ):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        if user_state is None:
            uid = user.id if user else 0
            uname = user.display_name if user else "여행자"
            u_state, _, _ = other_life_core.get_other_life_state(self.guild_id, uid, uname)
            self.user_state = u_state
        else:
            self.user_state = user_state
        self.parent_view = parent_view
        self.page = max(0, min(self._max_page(), int(page or 0)))
        self._rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 일대기는 **{self.user.display_name}**님의 기록입니다.",
                ephemeral=True,
            )
            return False
        return True

    def _max_page(self) -> int:
        active = self.user_state.get("active_life")
        if not isinstance(active, dict):
            return 0
        chron = active.get("chronicle") or []
        if not chron:
            return 0
        return max(0, (len(chron) - 1) // 10)

    def _rebuild(self):
        self.clear_items()
        max_p = self._max_page()

        btn_prev = discord.ui.Button(
            label="◀ 이전",
            style=discord.ButtonStyle.secondary,
            disabled=(self.page <= 0),
            row=0,
            custom_id="norosi:OtherLifeChronicleView:prev",
        )
        btn_prev.callback = self._on_prev
        self.add_item(btn_prev)

        btn_next = discord.ui.Button(
            label="다음 ▶",
            style=discord.ButtonStyle.secondary,
            disabled=(self.page >= max_p),
            row=0,
            custom_id="norosi:OtherLifeChronicleView:next",
        )
        btn_next.callback = self._on_next
        self.add_item(btn_next)

        btn_back = discord.ui.Button(
            label="🎮 이야기로 돌아가기",
            style=discord.ButtonStyle.success,
            row=0,
            custom_id="norosi:OtherLifeChronicleView:back",
        )
        btn_back.callback = self._on_back
        self.add_item(btn_back)

        btn_col = discord.ui.Button(
            label="📜 엔딩 도감",
            style=discord.ButtonStyle.secondary,
            row=0,
            custom_id="norosi:OtherLifeChronicleView:collection",
        )
        btn_col.callback = self._on_collection
        self.add_item(btn_col)

    def build_embed(self) -> discord.Embed:
        u = self.user_state
        uname = self.user.display_name if self.user else u.get("user_name", "플레이어")
        active = u.get("active_life")
        if not isinstance(active, dict):
            embed = discord.Embed(
                title=f"📖 {uname}님의 타인의 인생 — 전체 일대기",
                description="*(현재 열람할 인생 기록이 없습니다. 새 인생을 시작해 주세요!)*",
                color=0x38BDF8,
                timestamp=datetime.datetime.now(core.KST),
            )
            return embed

        role = other_life_core.get_role_context(active)
        ht = other_life_narratives.get_hometown_meta(active.get("hometown", ""))
        lore = other_life_narratives.get_origin_lore(active.get("origin_id", "orphanage"))
        status_tag = "완결" if active.get("finished") else f"제{active.get('beat', 1)}/18장 진행 중"

        tps = [str(t) for t in (active.get("turning_points") or []) if t]
        tp_text = _fit_lines_block(
            [f"• {tp}" for tp in tps],
            max_chars=1450,
            fallback="• *(아직 분기 전환점이 기록되지 않았습니다)*",
        )

        partner_txt = f" · 💍 동반자 `{active['partner_name']}`" if active.get("partner_name") else ""
        embed = discord.Embed(
            title=f"📖 {active.get('name')} ({active.get('age')}세) — 전체 일대기 [{status_tag}]"[:250],
            description=(
                f"**배경:** {ht['city']} · {lore['place']} · **길:** {role['title']}{partner_txt}\n"
                f"**간직한 유품:** `{lore['item_short']}` · **소꿉친구:** `{active.get('companion_name', '지우')}` · **스승:** `{active.get('mentor_name', '백 선생')}`\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🌟 **삶의 결정적 전환점 ({len(tps)}건)**\n{tp_text}"
            )[:4000],
            color=0x6366F1,
            timestamp=datetime.datetime.now(core.KST),
        )

        chron = [str(c) for c in (active.get("chronicle") or []) if c]
        per = 10
        self.page = max(0, min(self._max_page(), self.page))
        start = self.page * per
        slice_rows = chron[start:start + per]
        if not slice_rows:
            embed.add_field(
                name="🕰️ 연대기 기록",
                value="*(아직 기록된 연대기가 없습니다)*",
                inline=False,
            )
        else:
            first_half = slice_rows[:5]
            second_half = slice_rows[5:]
            embed.add_field(
                name=f"🕰️ 연대기 ({start + 1}~{start + len(first_half)} / 총 {len(chron)}건)",
                value=_fit_lines_block([f"> {line}" for line in first_half], max_chars=960),
                inline=False,
            )
            if second_half:
                embed.add_field(
                    name=f"🕰️ 연대기 ({start + 6}~{start + len(slice_rows)} / 총 {len(chron)}건)",
                    value=_fit_lines_block([f"> {line}" for line in second_half], max_chars=960),
                    inline=False,
                )

        embed.set_footer(
            text=f"{uname}님의 일대기 {self.page + 1} / {self._max_page() + 1} 페이지 · 매 선택과 흐른 세월이 보존됩니다"
        )
        return embed

    async def _on_prev(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_next(self, interaction: discord.Interaction):
        self.page = min(self._max_page(), self.page + 1)
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_back(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        u_state, _, logs = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        gv = self.parent_view or OtherLifeGameView(interaction.user, self.guild_id, user_state=u_state, idle_logs=logs)
        gv.user_state = u_state
        gv.idle_logs = logs
        gv.mode = "play"
        gv.status_msg = ""
        gv._rebuild()
        await core.safe_edit_response(interaction, embed=gv.build_embed(), view=gv)

    async def _on_collection(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        u_state, _, _ = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        cv = OtherLifeCollectionView(interaction.user, self.guild_id, user_state=u_state)
        await core.safe_edit_response(interaction, embed=cv.build_embed(), view=cv)


# ==========================================
# 4. 서버 랭킹 View
# ==========================================
class OtherLifeRankingView(core.SafeView):
    def __init__(self, user: Optional[discord.abc.User] = None, guild_id: int = 0):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.rows = other_life_core.get_other_life_ranking(self.guild_id, limit=10)

    def build_embed(self) -> discord.Embed:
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        total_endings = len(other_life_core.ENDINGS)
        for idx, r in enumerate(self.rows, 1):
            badge = medals[idx - 1] if idx <= 3 else f"`{idx}위`"
            lines.append(
                f"{badge} **{r['user_name']}** — 엔딩 **`{r['endings_cnt']}/{total_endings}종`** · "
                f"최고 **`{r['best_score']:,}점`** · 완결 `{r['lives_completed']}회` *(최장 {r['longest_age']}세)*"
            )
        body = "\n".join(lines) if lines else "*(아직 이 서버에 완결된 타인의 인생 기록이 없습니다. 첫 엔딩의 주인공이 되어보세요!)*"
        embed = discord.Embed(
            title="🏆 타인의 인생 — 서버 랭킹 TOP 10",
            description=(
                "수집한 고유 엔딩 수와 최고 인생 점수 기준으로 집계됩니다.\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                + body
            ),
            color=0xF59E0B,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="/설정 (🎮 미니게임 4p > 👶 타인의 삶 플레이) 또는 !타인의인생 으로 새로운 생애를 살아보세요!")
        return embed

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.rows = await asyncio.to_thread(other_life_core.get_other_life_ranking, self.guild_id, 10)
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🎮 내 인생 플레이하기", style=discord.ButtonStyle.success, row=0)
    async def btn_play(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        u_state, _, idle_logs = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        gv = OtherLifeGameView(interaction.user, self.guild_id, user_state=u_state, idle_logs=idle_logs)
        await core.safe_edit_response(interaction, embed=gv.build_embed(), view=gv)


# ==========================================
# 5. 메인 인터랙티브 플레이 View
# ==========================================
class OtherLifeGameView(core.SafeView):
    def __init__(
        self,
        user: Optional[discord.abc.User] = None,
        guild_id: int = 0,
        user_state: Optional[Dict[str, Any]] = None,
        idle_logs: Optional[List[str]] = None,
        force_setup: bool = False,
    ):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = int(guild_id or 0)
        if user_state is None:
            uid = user.id if user else 0
            uname = user.display_name if user else "여행자"
            u_state, _, logs = other_life_core.get_other_life_state(self.guild_id, uid, uname)
            self.user_state = u_state
            self.idle_logs = idle_logs if idle_logs is not None else logs
        else:
            self.user_state = user_state
            self.idle_logs = idle_logs or []

        self.selected_origin = "random"
        self.selected_scale = str(self.user_state.get("preferred_scale") or other_life_core.DEFAULT_TIME_SCALE)
        self.status_msg = ""

        active = self.user_state.get("active_life")
        if force_setup or not isinstance(active, dict):
            self.mode = "setup"
        else:
            self.mode = "play"
        self._rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                f"❌ 이 인생 이야기는 **{self.user.display_name}**님이 진행 중입니다. `/설정` (`🎮 미니게임` ➔ `🌌 타인의 삶 시작`)에서 본인만의 인생을 시작해 보세요!",
                ephemeral=True,
            )
            return False
        if not self.user:
            self.user = interaction.user
        return True

    def _restore_from_message(self, interaction: discord.Interaction):
        msg = getattr(interaction, "message", None)
        if not msg:
            return
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        is_setup = False
        is_finished = False
        for row in getattr(msg, "components", []) or []:
            for comp in getattr(row, "children", []):
                cid = getattr(comp, "custom_id", "") or ""
                if cid in ("norosi:OtherLifeGameView:origin_select", "norosi:OtherLifeGameView:start_life"):
                    is_setup = True
                elif cid in ("norosi:OtherLifeGameView:quick_new_life", "norosi:OtherLifeGameView:goto_setup"):
                    is_finished = True
                if cid == "norosi:OtherLifeGameView:origin_select":
                    for opt in getattr(comp, "options", []) or []:
                        if getattr(opt, "default", False) and getattr(opt, "value", None):
                            self.selected_origin = str(opt.value)
                            break
                elif cid == "norosi:OtherLifeGameView:scale_select":
                    for opt in getattr(comp, "options", []) or []:
                        if getattr(opt, "default", False) and getattr(opt, "value", None):
                            self.selected_scale = str(opt.value)
                            break
        if is_setup:
            self.mode = "setup"
        elif is_finished:
            self.mode = "play"
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        u = self.user_state
        unlocked_cnt = len([k for k in (u.get("unlocked_endings") or {}) if k in other_life_core.ENDINGS])
        total_endings = len(other_life_core.ENDINGS)
        active = u.get("active_life")

        # ── Setup Mode (새 인생 준비 화면) ──
        if self.mode == "setup" or not isinstance(active, dict):
            self.add_item(OtherLifeOriginSelect(self, self.selected_origin))
            self.add_item(OtherLifeScaleSelect(self, self.selected_scale, row=1))

            btn_start = discord.ui.Button(
                label="🌱 이 설정으로 인생 시작!",
                style=discord.ButtonStyle.success,
                row=2,
                custom_id="norosi:OtherLifeGameView:start_life",
            )
            btn_start.callback = self._on_start_life
            self.add_item(btn_start)

            if isinstance(active, dict) and not active.get("finished"):
                btn_resume = discord.ui.Button(
                    label="📖 진행 중 인생 이어하기",
                    style=discord.ButtonStyle.primary,
                    row=2,
                    custom_id="norosi:OtherLifeGameView:resume_life",
                )
                btn_resume.callback = self._on_resume_life
                self.add_item(btn_resume)

            btn_col = discord.ui.Button(
                label=f"📜 엔딩 도감 ({unlocked_cnt}/{total_endings})",
                style=discord.ButtonStyle.secondary,
                row=2,
                custom_id="norosi:OtherLifeGameView:open_collection",
            )
            btn_col.callback = self._on_open_collection
            self.add_item(btn_col)

            btn_rank = discord.ui.Button(
                label="🏆 서버 랭킹",
                style=discord.ButtonStyle.secondary,
                row=2,
                custom_id="norosi:OtherLifeGameView:open_ranking",
            )
            btn_rank.callback = self._on_open_ranking
            self.add_item(btn_rank)
            return

        # ── Finished Mode (엔딩 도달 화면) ──
        if active.get("finished"):
            btn_quick = discord.ui.Button(
                label="🌱 새 타인의 인생 시작",
                style=discord.ButtonStyle.success,
                row=0,
                custom_id="norosi:OtherLifeGameView:quick_new_life",
            )
            btn_quick.callback = self._on_quick_new_life
            self.add_item(btn_quick)

            btn_setup = discord.ui.Button(
                label="🧬 출신·배율 고르기",
                style=discord.ButtonStyle.primary,
                row=0,
                custom_id="norosi:OtherLifeGameView:goto_setup",
            )
            btn_setup.callback = self._on_goto_setup
            self.add_item(btn_setup)

            btn_chron = discord.ui.Button(
                label="📖 전체 일대기",
                style=discord.ButtonStyle.secondary,
                row=0,
                custom_id="norosi:OtherLifeGameView:open_chronicle",
            )
            btn_chron.callback = self._on_open_chronicle
            self.add_item(btn_chron)

            btn_col = discord.ui.Button(
                label=f"📜 도감 ({unlocked_cnt}/{total_endings})",
                style=discord.ButtonStyle.secondary,
                row=0,
                custom_id="norosi:OtherLifeGameView:open_collection",
            )
            btn_col.callback = self._on_open_collection
            self.add_item(btn_col)

            btn_rank = discord.ui.Button(
                label="🏆 랭킹",
                style=discord.ButtonStyle.secondary,
                row=0,
                custom_id="norosi:OtherLifeGameView:open_ranking",
            )
            btn_rank.callback = self._on_open_ranking
            self.add_item(btn_rank)

            self.add_item(OtherLifeScaleSelect(self, str(u.get("preferred_scale") or self.selected_scale), row=1))
            return

        # ── Active Play Mode (18개 분기점 플레이) ──
        node = other_life_core.build_current_node(active)
        choices = node["choices"]
        num_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]
        cur_beat = int(active.get("beat", 1) or 1)
        career_id = str(active.get("career") or "none")
        allowed_specs = other_life_core.CAREER_SPECIALTIES.get(career_id, [])
        has_spec_select = (cur_beat == 8 and len(allowed_specs) > 1)
        if has_spec_select and len(choices) <= 5:
            split_at = 5
        else:
            split_at = 4 if (len(choices) <= 4 or len(choices) >= 7) else 3

        for idx, ch in enumerate(choices):
            row = 0 if idx < split_at else 1
            raw_lbl = str(ch["label"]).strip()
            short_lbl = f"{num_emojis[idx]} {raw_lbl}"
            if len(short_lbl) > 44:
                short_lbl = short_lbl[:43] + "…"
            btn = discord.ui.Button(
                label=short_lbl,
                style=discord.ButtonStyle.primary if idx == 0 else discord.ButtonStyle.secondary,
                row=row,
                custom_id=f"norosi:OtherLifeGameView:choice:{ch['id']}",
            )
            btn.callback = self._make_choice_cb(ch["id"])
            self.add_item(btn)

        # Beat 8 (22세): 세부 전공 선택 드롭다운 배치 (버튼과 행 충돌 방지)
        spec_row = 1 if len(choices) <= split_at else 2
        if has_spec_select:
            cur_spec = str(active.get("specialty") or other_life_narratives.resolve_specialty_id(active, career_id))
            self.add_item(OtherLifeSpecialtySelect(self, career_id, cur_spec, row=spec_row))
            util_row = 2 if spec_row == 1 else 3
        else:
            util_row = 2

        # Utility actions (5 buttons max)
        cur_age = int(active.get("age", 6) or 6)
        ceiling = other_life_core._stage_age_ceiling(cur_beat, cur_age)
        max_q = 3 if cur_beat == 18 else 2
        quiet_disabled = (int(active.get("quiet_in_stage", 0) or 0) >= max_q) or (cur_age >= ceiling) or (cur_age >= 95)

        btn_quiet = discord.ui.Button(
            label="⏳ 1년 조용히",
            style=discord.ButtonStyle.secondary,
            disabled=quiet_disabled,
            row=util_row,
            custom_id="norosi:OtherLifeGameView:quiet_year",
        )
        btn_quiet.callback = self._on_quiet_year
        self.add_item(btn_quiet)

        btn_tick = discord.ui.Button(
            label="🔄 세월 확인",
            style=discord.ButtonStyle.secondary,
            row=util_row,
            custom_id="norosi:OtherLifeGameView:refresh_time",
        )
        btn_tick.callback = self._on_refresh_time
        self.add_item(btn_tick)

        btn_col = discord.ui.Button(
            label=f"📜 도감 ({unlocked_cnt}/{total_endings})",
            style=discord.ButtonStyle.secondary,
            row=util_row,
            custom_id="norosi:OtherLifeGameView:open_collection",
        )
        btn_col.callback = self._on_open_collection
        self.add_item(btn_col)

        btn_rank = discord.ui.Button(
            label="🏆 랭킹",
            style=discord.ButtonStyle.secondary,
            row=util_row,
            custom_id="norosi:OtherLifeGameView:open_ranking",
        )
        btn_rank.callback = self._on_open_ranking
        self.add_item(btn_rank)

        btn_reset = discord.ui.Button(
            label="🔁 새 인생",
            style=discord.ButtonStyle.danger,
            row=util_row,
            custom_id="norosi:OtherLifeGameView:request_reset",
        )
        btn_reset.callback = self._on_request_reset
        self.add_item(btn_reset)

        # Row 3: Live Time Scale Selector (when util_row <= 2)
        if util_row <= 2:
            self.add_item(
                OtherLifeScaleSelect(
                    self,
                    str(active.get("time_scale") or self.selected_scale),
                    row=3,
                )
            )

        # Row 4: Full Chronicle & Turning Points Viewer
        btn_chron = discord.ui.Button(
            label="📖 살아온 전체 일대기 & 전환점 보기",
            style=discord.ButtonStyle.secondary,
            row=4,
            custom_id="norosi:OtherLifeGameView:open_chronicle",
        )
        btn_chron.callback = self._on_open_chronicle
        self.add_item(btn_chron)

    def _make_choice_cb(self, choice_id: str):
        async def _cb(interaction: discord.Interaction):
            await core.safe_defer(interaction)
            ok, msg, updated_u, _ = await asyncio.to_thread(
                other_life_core.apply_life_choice,
                self.guild_id,
                interaction.user.id,
                choice_id,
                interaction.user.display_name,
            )
            self.user_state = updated_u
            self.idle_logs = []
            is_fin = bool((updated_u.get("active_life") or {}).get("finished"))
            self.status_msg = msg if (not ok or is_fin) else ""
            self._rebuild()
            await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
            if not ok:
                await interaction.followup.send(msg, ephemeral=True)
        return _cb

    def build_embed(self) -> discord.Embed:
        u = self.user_state
        uname = self.user.display_name if self.user else u.get("user_name", "플레이어")
        unlocked_cnt = len([k for k in (u.get("unlocked_endings") or {}) if k in other_life_core.ENDINGS])
        total_endings = len(other_life_core.ENDINGS)
        active = u.get("active_life")

        # ── Setup Embed ──
        if self.mode == "setup" or not isinstance(active, dict):
            scale_meta = other_life_core.TIME_SCALES.get(
                self.selected_scale,
                other_life_core.TIME_SCALES[other_life_core.DEFAULT_TIME_SCALE],
            )
            if self.selected_origin == "random":
                origin_preview = "🎲 **무작위 출신** *(바닷가 보육원·시장통 국수집·한옥 서재 등 6가지 운명 중 랜덤 시작)*"
            else:
                orig = other_life_core.ORIGINS[self.selected_origin]
                origin_preview = f"{orig['name']} — *{orig['hook']}*\n> 유품: `{orig['item']}`"

            status_banner = f"\n🔔 {self.status_msg}\n" if self.status_msg else ""
            embed = discord.Embed(
                title="📖 타인의 인생 — 새로운 일생의 첫 페이지",
                description=(
                    f"**{uname}**님, 이름도 배경도 낯선 어느 타인의 0세부터 노년까지를 대신 살아보세요.\n"
                    f"유년기의 작은 약속, 청소년기의 스승과 유혹, 서른의 선택이 20개 세부 전공과 **1,000종 멀티 엔딩**으로 이어집니다.\n"
                    f"{status_banner}\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🧬 **선택된 출신 배경**\n{origin_preview}\n\n"
                    f"⏱️ **선택된 시간 배율:** **{scale_meta['name']}**\n"
                    f"> {scale_meta['desc']}\n\n"
                    f"📚 **내 수집 기록:** 해금 엔딩 **`{unlocked_cnt}/{total_endings:,}종`** · "
                    f"완결 생애 `{u.get('lives_completed', 0)}회` · 최고 `{u.get('best_score', 0):,}점`\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "👇 아래 드롭다운으로 출신과 시간 배율을 고른 뒤 `🌱 이 설정으로 인생 시작!`을 눌러주세요!"
                ),
                color=0x38BDF8,
                timestamp=datetime.datetime.now(core.KST),
            )
            embed.set_footer(text="하루 3회 완결 💎 보상 (초회 엔딩 해금 시 +120💎 보너스!) · /설정 (타인의 삶 도감)")
            return embed

        # ── Finished Ending Embed ──
        if active.get("finished"):
            fallback_eid = other_life_core.LEGACY_ENDING_MAP.get("quiet_miracle", next(iter(other_life_core.ENDINGS)))
            eid = str(active.get("ending_id") or fallback_eid)
            if eid not in other_life_core.ENDINGS:
                eid = other_life_core.migrate_legacy_ending_id(eid) or fallback_eid
            emeta = other_life_core.ENDINGS.get(eid, other_life_core.ENDINGS[fallback_eid])
            c_meta = other_life_core.CAREER_META.get(str(active.get("career") or "none"), other_life_core.CAREER_META["none"])
            orig = other_life_core.ORIGINS.get(str(active.get("origin_id") or "orphanage"), other_life_core.ORIGINS["orphanage"])
            role = other_life_core.get_role_context(active)
            ht = other_life_narratives.get_hometown_meta(active.get("hometown", ""))
            lore = other_life_narratives.get_origin_lore(active.get("origin_id", "orphanage"))

            reward_line = active.get("reward_note") or "도감 등록 완료"
            partner_line = f" · 💍 동반자 `{active['partner_name']}`" if active.get("partner_name") else ""

            embed = discord.Embed(
                title=f"🎬 [인생 완결] {active.get('name')} ({active.get('age')}세) — {emeta['emoji']} {emeta['title']}"[:250],
                description=(
                    f"**등급:** `[{emeta['rarity']}]` · **주제:** *{emeta['summary']}*\n"
                    f"**배경:** {ht['city']} · {orig['name']} · **길:** {c_meta['emoji']} {role['title']}{partner_line}\n"
                    f"**유품:** `{lore['item_short']}` · **도감 해금:** `{unlocked_cnt}/{total_endings:,}종`\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📜 **생애의 마침표**\n{active.get('ending_epilogue', '')}"
                )[:4000],
                color=emeta["color"],
                timestamp=datetime.datetime.now(core.KST),
            )
            embed.add_field(
                name=f"📊 최종 삶의 결 (인생 점수 {active.get('score', 0):,}점)",
                value=f"{_format_stats_block(active.get('stats') or {})}\n💎 **보상:** {reward_line}"[:1000],
                inline=False,
            )
            tps = [str(t) for t in (active.get("turning_points") or []) if t]
            if tps:
                embed.add_field(
                    name=f"🌟 결정적 전환점 ({len(tps)}건)",
                    value=_fit_lines_block([f"• {t}" for t in tps[-4:]], max_chars=960),
                    inline=False,
                )
            tail_chronicle = (active.get("chronicle") or [])[-5:]
            embed.add_field(
                name="🕰️ 생애 후반 발자취",
                value=_fit_lines_block([f"> {line}" for line in tail_chronicle], max_chars=960),
                inline=False,
            )
            embed.set_footer(text=f"{uname}님의 타인의 인생 · '📖 전체 일대기'로 처음부터 끝까지 다시 읽을 수 있습니다")
            return embed

        # ── Active Play Embed ──
        cur_age = int(active.get("age", 6) or 6)
        cur_beat = int(active.get("beat", 1) or 1)
        stage_id, stage_label, _ = other_life_core.get_stage_for_age(cur_age)
        node = other_life_core.build_current_node(active)
        orig = other_life_core.ORIGINS.get(str(active.get("origin_id") or "orphanage"), other_life_core.ORIGINS["orphanage"])
        c_meta = other_life_core.CAREER_META.get(str(active.get("career") or "none"), other_life_core.CAREER_META["none"])
        role = other_life_core.get_role_context(active)
        ht = other_life_narratives.get_hometown_meta(active.get("hometown", ""))
        lore = other_life_narratives.get_origin_lore(active.get("origin_id", "orphanage"))
        scale_id = str(active.get("time_scale") or other_life_core.DEFAULT_TIME_SCALE)
        scale_meta = other_life_core.TIME_SCALES.get(scale_id, other_life_core.TIME_SCALES[other_life_core.DEFAULT_TIME_SCALE])

        rel_bits = [f"고향 `{ht['city']}`", f"유품 `{lore['item_short']}`"]
        if cur_beat >= 2:
            comp_rel = str(active.get("companion_rel") or "stranger")
            comp_tag = {
                "partner": "(동반자)",
                "reunited": "(재회·동반자)",
                "reunited_love": "(재회·연인)",
                "promised": "(약속)",
                "close": "(절친)",
                "rival": "(라이벌)",
                "estranged": "(멀어짐)",
                "estranged_late": "(멀어짐)",
                "missed": "(엇갈림)",
                "parted_warm": "(작별)",
            }.get(comp_rel, "")
            rel_bits.append(f"소꿉친구 `{active.get('companion_name', '지우')}`{comp_tag}")
        if cur_beat >= 5:
            rel_bits.append(f"스승 `{active.get('mentor_name', '백 선생')}`")
        if active.get("partner_name"):
            rel_bits.append(f"💍 동반자 `{active['partner_name']}`")

        banner_parts = []
        if self.idle_logs:
            banner_parts.append(f"⏳ **방금 흐른 세월 ({len(self.idle_logs)}년):** {self.idle_logs[-1]}")
        if self.status_msg:
            banner_parts.append(f"💬 {self.status_msg}")
        banner_txt = ("\n".join(banner_parts) + "\n\n") if banner_parts else ""

        last_out = str(active.get("last_outcome") or "").strip()
        outcome_sec = f"📜 **직전 선택의 여파**\n> {last_out}\n\n" if last_out else ""

        allowed_specs = other_life_core.CAREER_SPECIALTIES.get(str(active.get("career") or "none"), [])
        spec_tip = (
            "\n\n> 🎯 **세부 전공 변경 가능:** 아래 선택 메뉴에서 세부 전공을 바꾸면 무대와 선택지가 즉시 바뀝니다!"
            if cur_beat == 8 and len(allowed_specs) > 1
            else ""
        )

        stage_colors = {
            "childhood": 0x4ADE80,
            "teen": 0x38BDF8,
            "youth": 0xF97316,
            "midlife": 0xA855F7,
            "elder": 0xEAB308,
        }

        embed = discord.Embed(
            title=f"{node['title']}"[:250],
            description=(
                f"{banner_txt}"
                f"**👤 {active.get('name')}** (`{cur_age}세` · {stage_label} · **Chapter `{cur_beat}/18`**)\n"
                f"🧬 {orig['name']} · {c_meta['emoji']} **{role['title']}**\n"
                f"⏱️ {scale_meta['name']} · {_next_tick_text(active)}\n"
                f"🤝 {' · '.join(rel_bits)}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{outcome_sec}"
                f"📖 **지금 마주한 순간**\n{node['body']}{spec_tip}"
            )[:4000],
            color=stage_colors.get(stage_id, 0x38BDF8),
            timestamp=datetime.datetime.now(core.KST),
        )

        num_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]
        choice_lines = [
            f"{num_emojis[idx]} **{ch['label']}**\n> `{ch['hint']}`"
            for idx, ch in enumerate(node["choices"])
        ]
        choice_chunks = _chunk_text_blocks(choice_lines, max_chars=960)
        for c_idx, chunk in enumerate(choice_chunks):
            fname = "🎯 당신의 선택" if len(choice_chunks) == 1 else f"🎯 당신의 선택 ({c_idx + 1})"
            embed.add_field(name=fname, value=chunk, inline=False)

        embed.add_field(
            name="📊 삶의 결",
            value=_format_stats_block(active.get("stats") or {}),
            inline=False,
        )

        chron_lines = (active.get("chronicle") or [])[-3:]
        embed.add_field(
            name="🕰️ 최근 발자취",
            value=_fit_lines_block([f"> {c}" for c in chron_lines], max_chars=960),
            inline=False,
        )

        max_q = 3 if cur_beat == 18 else 2
        quiet_rem = max(0, max_q - int(active.get("quiet_in_stage", 0) or 0))
        embed.set_footer(
            text=f"{uname}님의 타인의 인생 · 조용한 1년 {quiet_rem}회 남음 · '전체 일대기'에서 지금까지의 삶 열람"
        )
        return embed

    # ── Button Callbacks ──
    async def _on_start_life(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        orig_arg = None if self.selected_origin == "random" else self.selected_origin
        ok, msg, updated_u = await asyncio.to_thread(
            other_life_core.start_new_life,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
            self.selected_scale,
            orig_arg,
        )
        self.user_state = updated_u
        self.idle_logs = []
        self.mode = "play"
        self.status_msg = msg
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_resume_life(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        u_state, _, logs = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        self.user_state = u_state
        self.idle_logs = logs
        self.mode = "play"
        self.status_msg = "📖 진행 중이던 인생을 다시 펼쳤습니다."
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_quick_new_life(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        ok, msg, updated_u = await asyncio.to_thread(
            other_life_core.start_new_life,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        self.user_state = updated_u
        self.idle_logs = []
        self.mode = "play"
        self.status_msg = msg
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_goto_setup(self, interaction: discord.Interaction):
        self.mode = "setup"
        self.status_msg = "🧬 새로운 출신과 시간 배율을 선택해 주세요."
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_quiet_year(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        ok, msg, updated_u = await asyncio.to_thread(
            other_life_core.spend_quiet_year,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        self.user_state = updated_u
        self.idle_logs = []
        self.status_msg = msg
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)

    async def _on_refresh_time(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        u_state, yrs, logs = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        self.user_state = u_state
        self.idle_logs = logs
        self.status_msg = (
            f"⏳ {yrs}년의 일상이 자연스럽게 흘러 일기장에 기록되었습니다!"
            if yrs > 0
            else "🔄 현재 시점까지 세월 상태를 확인했습니다."
        )
        self._rebuild()
        await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)

    async def _on_open_chronicle(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        u_state, _, _ = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        self.user_state = u_state
        cv = OtherLifeChronicleView(interaction.user, self.guild_id, user_state=u_state, parent_view=self)
        await core.safe_edit_response(interaction, embed=cv.build_embed(), view=cv)

    async def _on_open_collection(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        u_state, _, _ = await asyncio.to_thread(
            other_life_core.get_other_life_state,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )
        cv = OtherLifeCollectionView(interaction.user, self.guild_id, user_state=u_state)
        await core.safe_edit_response(interaction, embed=cv.build_embed(), view=cv)

    async def _on_open_ranking(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        rv = OtherLifeRankingView(interaction.user, self.guild_id)
        await core.safe_edit_response(interaction, embed=rv.build_embed(), view=rv)

    async def _on_request_reset(self, interaction: discord.Interaction):
        active = self.user_state.get("active_life") or {}
        if int(active.get("beat", 1) or 1) <= 1 and not active.get("chronicle"):
            self.mode = "setup"
            self._rebuild()
            await core.safe_edit_response(interaction, embed=self.build_embed(), view=self)
            return

        cv = OtherLifeConfirmResetView(self, interaction.user, self.guild_id)
        embed = discord.Embed(
            title="🔁 진행 중인 인생을 새로 시작할까요?",
            description=(
                f"현재 **{active.get('name')} ({active.get('age')}세 · {active.get('beat')}/18장)** 의 이야기가 진행 중입니다.\n"
                "지금 새로 시작하면 현재 생애는 완결 기록(도감)에 저장되지 않고 덮어써집니다.\n\n"
                "어떻게 하시겠어요?"
            ),
            color=0xEF4444,
        )
        await core.safe_edit_response(interaction, embed=embed, view=cv)


# ==========================================
# 6. Cog 등록 (/타인의인생 그룹 + !타인의인생 단축어)
# ==========================================
class OtherLifeCog(
    commands.GroupCog,
    name="타인의인생",
    description="📖 0세부터 노년까지 타인의 일생을 살아가는 스토리 시뮬레이션 (시간 배율 · 1,000종 멀티 엔딩)",
):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="플레이", description="📖 타인의 인생을 시작하거나 진행 중이던 생애를 이어갑니다.")
    @app_commands.describe(
        출신="새 인생 시작 시 고를 출신 환경 (미선택 시 이어하기/랜덤 선택창 표시)",
        시간배율="인생 세월이 흐르는 시간 배율 (표준 60초=1년 추천 / 쾌속 30초 / 슬로우 3분 / 턴제)",
    )
    @app_commands.choices(
        출신=[
            app_commands.Choice(name="🎲 랜덤 출신 (운명에 맡기기)", value="random"),
            app_commands.Choice(name="🌊 바닷가 보육원 '해송원'", value="orphanage"),
            app_commands.Choice(name="🍜 시장통 24시 멸치국수집", value="noodle_shop"),
            app_commands.Choice(name="📚 오래된 한옥 서재 집안", value="scholar_home"),
            app_commands.Choice(name="🏚️ 몰락한 옛 저택의 막내", value="fallen_house"),
            app_commands.Choice(name="🕰️ 골목 끝 시계·목공방", value="artisan_shop"),
            app_commands.Choice(name="⛰️ 안개 낀 산골 약초방", value="mountain_clinic"),
        ],
        시간배율=[
            app_commands.Choice(name="⚖️ 표준 세월 배율 (60초=1년 · 추천)", value="balanced"),
            app_commands.Choice(name="⚡ 쾌속 세월 배율 (30초=1년)", value="brisk"),
            app_commands.Choice(name="🕰️ 슬로우 라이프 (3분=1년)", value="slow"),
            app_commands.Choice(name="📖 턴제 정주행 (대기 없음)", value="turn"),
        ],
    )
    async def play_cmd(
        self,
        interaction: discord.Interaction,
        출신: Optional[app_commands.Choice[str]] = None,
        시간배율: Optional[app_commands.Choice[str]] = None,
    ):
        await core.safe_defer(interaction)
        gid = interaction.guild_id or 0
        uid = interaction.user.id
        uname = interaction.user.display_name

        u_state, yrs, idle_logs = await asyncio.to_thread(other_life_core.get_other_life_state, gid, uid, uname)
        scale_val = 시간배율.value if 시간배율 else None
        origin_val = 출신.value if 출신 else None

        active = u_state.get("active_life")
        has_unfinished = isinstance(active, dict) and not active.get("finished")

        status_msg = ""
        if scale_val and (has_unfinished or not origin_val):
            _, s_msg, u_state = await asyncio.to_thread(
                other_life_core.set_life_time_scale, gid, uid, scale_val, uname
            )
            status_msg = s_msg

        if origin_val and not has_unfinished:
            orig_arg = None if origin_val == "random" else origin_val
            _, start_msg, u_state = await asyncio.to_thread(
                other_life_core.start_new_life,
                gid,
                uid,
                uname,
                scale_val or u_state.get("preferred_scale"),
                orig_arg,
            )
            idle_logs = []
            status_msg = start_msg

        view = OtherLifeGameView(interaction.user, gid, user_state=u_state, idle_logs=idle_logs)
        if scale_val:
            view.selected_scale = scale_val
        if origin_val and has_unfinished:
            view.selected_origin = origin_val
            status_msg = "ℹ️ 이미 진행 중인 인생을 불러왔습니다. 새로 시작하려면 `🔁 새 인생` 버튼을 눌러주세요."
        if status_msg:
            view.status_msg = status_msg
        view._rebuild()

        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="도감", description="📜 해금한 1,000종 멀티 엔딩 도감(필터·검색·수집요약)과 내가 살아온 인생 전기 아카이브를 봅니다.")
    async def collection_cmd(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        gid = interaction.guild_id or 0
        u_state, _, _ = await asyncio.to_thread(
            other_life_core.get_other_life_state, gid, interaction.user.id, interaction.user.display_name
        )
        view = OtherLifeCollectionView(interaction.user, gid, user_state=u_state)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="랭킹", description="🏆 서버 유저들의 타인의 인생 엔딩 수집 · 최고 점수 랭킹을 봅니다.")
    async def ranking_cmd(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        gid = interaction.guild_id or 0
        view = OtherLifeRankingView(interaction.user, gid)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg


class OtherLifeStandaloneCog(commands.Cog):
    """!타인의인생 · !인생게임 · !타인 접두사 단축어 Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="타인의인생")
    async def prefix_other_life(self, ctx: commands.Context):
        gid = ctx.guild.id if ctx.guild else 0
        u_state, _, idle_logs = await asyncio.to_thread(
            other_life_core.get_other_life_state, gid, ctx.author.id, ctx.author.display_name
        )
        view = OtherLifeGameView(ctx.author, gid, user_state=u_state, idle_logs=idle_logs)
        msg = await ctx.send(embed=view.build_embed(), view=view)
        view.message = msg


async def setup(bot: commands.Bot):
    await bot.add_cog(OtherLifeCog(bot))
    await bot.add_cog(OtherLifeStandaloneCog(bot))
