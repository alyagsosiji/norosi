"""
cogs/fishing.py - /낚시 전용 명령어 그룹 Cog
호수·강·바다 초대규모 글로벌 공개 어종 DB, KST 시간/날씨 연동, 세부 수역 탐사,
무결점 입질 타이밍 미니게임(SafeView + 원자적 상태머신), 개인 수족관, 도감, 상점, 최대어 랭킹 지원
"""

from __future__ import annotations

import asyncio
import datetime
import io
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

import core
import fishing_core


# ==========================================
# 원자적 낚시 출조 세션 레지스트리 (먹통·경합·중복포획 원천 차단)
# ==========================================
@dataclass
class _CastSession:
    guild_id: int
    user_id: int
    cast_seq: int = 0
    phase: str = "idle"  # idle -> waiting_bite -> biting -> resolved
    habitat: str = "lake"
    zone_filter: str = "all"
    spot_id: Optional[str] = None
    bait_id: str = "dough"
    window_sec: float = 5.5
    grace_sec: float = 1.25
    bite_started_at: float = 0.0
    updated_at: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    wait_task: Optional[asyncio.Task] = None
    expire_task: Optional[asyncio.Task] = None


_ACTIVE_CASTS: Dict[Tuple[int, int], _CastSession] = {}


def _get_or_create_cast_session(guild_id: int, user_id: int) -> _CastSession:
    key = (int(guild_id or 0), int(user_id))
    sess = _ACTIVE_CASTS.get(key)
    if sess is None:
        sess = _CastSession(guild_id=key[0], user_id=key[1])
        _ACTIVE_CASTS[key] = sess
    else:
        # 25초 이상 방치된 유령 세션은 자동 초기화 (먹통 방지)
        if sess.phase in ("waiting_bite", "biting") and (time.monotonic() - sess.updated_at) > 25.0:
            _cancel_session_tasks(sess)
            sess.phase = "idle"
    return sess


def _cancel_session_tasks(sess: _CastSession):
    for t_attr in ("wait_task", "expire_task"):
        t = getattr(sess, t_attr, None)
        if t is not None and not t.done():
            try:
                t.cancel()
            except Exception:
                pass
        setattr(sess, t_attr, None)


def _format_weight(w_kg: float) -> str:
    if w_kg < 0.2:
        return f"{w_kg:.3f} kg ({int(round(w_kg * 1000))}g)"
    return f"{w_kg:.2f} kg"


def _strip_attachment_image(embed: Optional[discord.Embed]) -> Optional[discord.Embed]:
    if embed is None:
        return None
    img_url = getattr(getattr(embed, "image", None), "url", None) or ""
    if str(img_url).startswith("attachment://"):
        cloned = embed.copy()
        cloned.set_image(url=None)
        return cloned
    return embed


async def _safe_update_message_or_interaction(
    interaction: Optional[discord.Interaction],
    message: Optional[discord.Message],
    *,
    embed: Optional[discord.Embed] = None,
    view: Optional[discord.ui.View] = None,
    file: Optional[discord.File] = None,
    png_bytes: Optional[bytes] = None,
    png_filename: str = "catch_card.png",
    clear_attachments: bool = False,
    content: Optional[str] = None,
    raise_on_fail: bool = False,
):
    """
    공개 메시지는 봇 토큰 직접 편집 우선, 나만 보기(ephemeral) 메시지는 인터랙션 원본 응답 편집 우선으로
    첨부파일 잔존/소진 버퍼 및 404/40060/10062/10015 오류 없이 안전하게 UI를 갱신합니다.
    """
    has_attachment = (png_bytes is not None) or (file is not None)

    def _build_kwargs(include_attachment: bool) -> Dict[str, Any]:
        kw: Dict[str, Any] = {}
        if content is not None:
            kw["content"] = content
        if view is not None:
            kw["view"] = view
        if include_attachment and has_attachment:
            if embed is not None:
                kw["embed"] = embed
            if png_bytes is not None:
                kw["attachments"] = [discord.File(fp=io.BytesIO(png_bytes), filename=png_filename)]
            elif file is not None:
                try:
                    file.fp.seek(0)
                except Exception:
                    pass
                kw["attachments"] = [file]
        else:
            if embed is not None:
                kw["embed"] = _strip_attachment_image(embed) if has_attachment else embed
            if clear_attachments or has_attachment:
                kw["attachments"] = []
        return kw

    is_ephemeral = bool(getattr(getattr(message, "flags", None), "ephemeral", False))
    last_err: Optional[Exception] = None

    if is_ephemeral and interaction is not None:
        for inc_att in ((True, False) if has_attachment else (False,)):
            try:
                await core.safe_edit_response(interaction, **_build_kwargs(inc_att), raise_on_error=True)
                return interaction.message or message
            except Exception as ex:
                last_err = ex

    # 1순위: 공개 메시지 직접 편집 (봇 토큰 기반이라 15분 웹훅 제한 무관)
    if message is not None and not is_ephemeral:
        for inc_att in ((True, False) if has_attachment else (False,)):
            kw = _build_kwargs(inc_att)
            try:
                await message.edit(**kw)
                return message
            except Exception as ex:
                last_err = ex
                ch = getattr(interaction, "channel", None) or getattr(message, "channel", None)
                if ch is not None and hasattr(ch, "get_partial_message"):
                    try:
                        await ch.get_partial_message(message.id).edit(**kw)
                        return message
                    except Exception as p_ex:
                        last_err = p_ex

    # 2순위: 인터랙션 원본 응답 편집 (ephemeral 메시지 등)
    if interaction is not None:
        for inc_att in ((True, False) if has_attachment else (False,)):
            try:
                await core.safe_edit_response(interaction, **_build_kwargs(inc_att), raise_on_error=True)
                return interaction.message or message
            except Exception as ex:
                last_err = ex

    if raise_on_fail and last_err is not None:
        raise last_err
    return message


# ==========================================
# 1. 출조 · 입질 미니게임 · 포획 결과 View
# ==========================================
class FishingLocationSelect(discord.ui.Select):
    """서식지(호수·강·바다) + 세부 구역 + 해금형 특수 낚시터 3종 통합 Select (19개 옵션)"""

    def __init__(self, parent_view: "FishingCastView"):
        self.parent_view = parent_view
        super().__init__(
            placeholder="📍 낚시터 · 세부 수역 · 특수 낚시터 선택...",
            min_values=1,
            max_values=1,
            options=self._build_opts(),
            row=0,
            custom_id="norosi:FishingCastView:location_select",
        )

    def _build_opts(self) -> List[discord.SelectOption]:
        u = core.as_dict(self.parent_view.summary.get("user") if isinstance(self.parent_view.summary, dict) else {})
        cur_spot = self.parent_view.spot_id
        cur_hab = self.parent_view.habitat
        cur_zone = self.parent_view.zone_filter
        opts: List[discord.SelectOption] = []
        for h_id in ("lake", "river", "sea"):
            h = fishing_core.HABITATS[h_id]
            val_all = f"{h_id}:all"
            opts.append(discord.SelectOption(
                label=f"{h['name']} 전체"[:95],
                value=val_all,
                emoji=h["emoji"],
                default=(not cur_spot and cur_hab == h_id and cur_zone == "all"),
            ))
            for z_idx, z in enumerate(fishing_core.CANONICAL_ZONES[h_id]):
                opts.append(discord.SelectOption(
                    label=f"└ {z}"[:95],
                    value=f"{h_id}:{z_idx}",
                    default=(not cur_spot and cur_hab == h_id and cur_zone == z),
                ))
        for s_id, sp in fishing_core.SPECIAL_SPOTS.items():
            unlocked = fishing_core.is_special_spot_unlocked(u, s_id)
            opts.append(discord.SelectOption(
                label=f"{sp['short']}"[:95],
                value=f"spot:{s_id}",
                emoji=(sp["emoji"] if unlocked else "🔒"),
                default=(cur_spot == s_id),
            ))
        return opts[:25]

    def refresh(self):
        self.options = self._build_opts()

    async def callback(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        raw = self.values[0]
        if raw.startswith("spot:"):
            s_id = raw.split(":", 1)[1]
            spot = fishing_core.SPECIAL_SPOTS.get(s_id)
            u = core.as_dict(self.parent_view.summary.get("user") if isinstance(self.parent_view.summary, dict) else {})
            if not spot:
                return
            if not fishing_core.is_special_spot_unlocked(u, s_id):
                lvl = int(u.get("level", 1) or 1)
                pd_cnt = len(u.get("pokedex") or {}) if isinstance(u.get("pokedex"), dict) else 0
                await interaction.followup.send(
                    f"🔒 {spot['emoji']} **{spot['name']}**은(는) 아직 잠겨 있습니다!\n"
                    f"• **해금 조건:** `{spot['req_desc']}`\n"
                    f"• **현재 진행:** 낚시 `Lv.{lvl}` · 도감 `{pd_cnt}종`",
                    ephemeral=True,
                )
                return
            await asyncio.to_thread(
                fishing_core.update_user_fishing_prefs,
                self.parent_view.guild_id,
                self.parent_view.user.id,
                interaction.user.display_name,
                spot_id=s_id,
            )
            self.parent_view.spot_id = s_id
            self.parent_view.habitat = spot["base_habitat"]
            self.parent_view.zone_filter = "all"
        else:
            chosen_hab, raw_zone = raw.split(":", 1)
            zones = fishing_core.CANONICAL_ZONES.get(chosen_hab, [])
            if raw_zone.isdigit() and 0 <= int(raw_zone) < len(zones):
                chosen_zone = zones[int(raw_zone)]
            else:
                chosen_zone = raw_zone
            await asyncio.to_thread(
                fishing_core.update_user_fishing_prefs,
                self.parent_view.guild_id,
                self.parent_view.user.id,
                interaction.user.display_name,
                habitat=chosen_hab,
                zone_filter=chosen_zone,
                spot_id="",
            )
            self.parent_view.spot_id = None
            self.parent_view.habitat = chosen_hab
            self.parent_view.zone_filter = chosen_zone

        await self.parent_view.refresh_summary()
        self.parent_view.sync_controls(phase="idle")
        await _safe_update_message_or_interaction(
            interaction,
            interaction.message or self.parent_view.message,
            embed=self.parent_view.build_dashboard_embed(),
            view=self.parent_view,
            clear_attachments=True,
            content=None,
        )


class FishingBaitSelect(discord.ui.Select):
    def __init__(self, parent_view: "FishingCastView"):
        self.parent_view = parent_view
        opts = self._build_opts()
        super().__init__(
            placeholder="🪱 사용할 미끼 선택...",
            min_values=1,
            max_values=1,
            options=opts,
            row=1,
            custom_id="norosi:FishingCastView:bait_select",
        )

    def _build_opts(self) -> List[discord.SelectOption]:
        u = self.parent_view.summary.get("user", {}) if isinstance(self.parent_view.summary, dict) else {}
        cur_bait = u.get("selected_bait", "dough")
        bag_baits = u.get("baits", {}) if isinstance(u.get("baits"), dict) else {}
        short_names = {
            "dough": "곡물 떡밥",
            "worm": "붉은 지렁이",
            "shrimp": "크릴새우",
            "lure": "메탈 루어",
            "glow": "야광 미끼",
            "golden": "황금 떡밥",
            "live_minnow": "특제 생미끼",
            "trophy_chum": "대물 집어제",
        }
        opts = []
        for b_id, b in fishing_core.BAITS.items():
            nm = short_names.get(b_id, b["name"])
            if b.get("unlimited"):
                qty_txt = "∞"
            else:
                cnt = int(bag_baits.get(b_id, 0) or 0)
                qty_txt = f"{cnt}"
            opts.append(discord.SelectOption(
                label=f"{nm} ({qty_txt})"[:70],
                value=b_id,
                emoji=b["emoji"],
                default=(b_id == cur_bait),
            ))
        return opts[:25]

    def refresh(self):
        self.options = self._build_opts()

    async def callback(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        chosen = self.values[0]
        u = core.as_dict(self.parent_view.summary.get("user") if self.parent_view.summary else {})
        if chosen != "dough" and int(core.as_dict(u.get("baits")).get(chosen, 0)) <= 0:
            b_meta = fishing_core.BAITS[chosen]
            if b_meta.get("craft_only"):
                await interaction.followup.send(
                    f"❌ **{b_meta['name']}**을(를) 보유하고 있지 않습니다! `🛒 상점 ➔ 🧪 미끼제작` 또는 가방 `[🧪 미끼 제작]`에서 소형어를 분해해 제작해 보세요.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"❌ **{b_meta['name']}**을(를) 보유하고 있지 않습니다! `🛒 상점`에서 구매해 보세요.",
                    ephemeral=True,
                )
            return
        await asyncio.to_thread(
            fishing_core.update_user_fishing_prefs,
            self.parent_view.guild_id,
            self.parent_view.user.id,
            interaction.user.display_name,
            bait_id=chosen,
        )
        await self.parent_view.refresh_summary()
        self.parent_view.sync_controls(phase="idle")
        await _safe_update_message_or_interaction(
            interaction,
            interaction.message or self.parent_view.message,
            embed=self.parent_view.build_dashboard_embed(),
            view=self.parent_view,
            clear_attachments=True,
        )


class FishingCastView(core.SafeView):
    """무결점 낚시 출조 & 입질 타이밍 미니게임 뷰"""

    def __init__(
        self,
        user: discord.abc.User,
        guild_id: int = 0,
        summary: Optional[Dict[str, Any]] = None,
        habitat: Optional[str] = None,
        zone_filter: Optional[str] = None,
    ):
        super().__init__(timeout=None)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.summary = summary or fishing_core.get_user_fishing_summary(self.guild_id, user.id, user.display_name)
        u_dict = core.as_dict(self.summary.get("user"))
        raw_hab = habitat or u_dict.get("selected_habitat") or "lake"
        self.habitat = raw_hab if raw_hab in fishing_core.HABITATS else "lake"
        self.zone_filter = zone_filter or u_dict.get("selected_zone", "all")
        raw_spot = u_dict.get("selected_spot")
        self.spot_id: Optional[str] = raw_spot if raw_spot in fishing_core.SPECIAL_SPOTS else None
        self.last_catch: Optional[Dict[str, Any]] = None
        self.last_catches: List[Dict[str, Any]] = []
        self.catch_card_idx: int = 0
        self._catch_card_cache: Dict[int, bytes] = {}

        self.habitat_select = FishingLocationSelect(self)
        self.bait_select = FishingBaitSelect(self)
        self.add_item(self.habitat_select)
        self.add_item(self.bait_select)
        self.sync_controls(phase="idle")

    def _get_catch_entries(self) -> List[Dict[str, Any]]:
        if not isinstance(self.last_catch, dict):
            return []
        catches = self.last_catch.get("catches")
        if isinstance(catches, list) and catches:
            return [c for c in catches if isinstance(c, dict) and isinstance(c.get("fish"), dict)]
        f = self.last_catch.get("fish")
        sp = self.last_catch.get("species")
        if isinstance(f, dict) and isinstance(sp, dict):
            return [{
                "fish": f,
                "species": sp,
                "is_first_catch": bool(self.last_catch.get("is_first_catch")),
                "new_server_len_record": bool(self.last_catch.get("new_server_len_record")),
                "new_server_wt_record": bool(self.last_catch.get("new_server_wt_record")),
            }]
        return []

    def _get_pending_fish_list(self) -> List[Dict[str, Any]]:
        if self.last_catches:
            return [f for f in self.last_catches if isinstance(f, dict) and f.get("uid")]
        if isinstance(self.last_catch, dict):
            catches = self.last_catch.get("catches")
            if isinstance(catches, list) and catches:
                return [
                    c["fish"] for c in catches
                    if isinstance(c, dict) and isinstance(c.get("fish"), dict) and c["fish"].get("uid")
                ]
            f = self.last_catch.get("fish")
            if isinstance(f, dict) and f.get("uid"):
                return [f]
        return []

    async def refresh_summary(self):
        self.summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary,
            self.guild_id,
            self.user.id,
            self.user.display_name,
        )
        u_dict = core.as_dict(self.summary.get("user"))
        raw_hab = u_dict.get("selected_habitat", "lake")
        self.habitat = raw_hab if raw_hab in fishing_core.HABITATS else "lake"
        self.zone_filter = u_dict.get("selected_zone", "all")
        raw_spot = u_dict.get("selected_spot")
        self.spot_id = raw_spot if raw_spot in fishing_core.SPECIAL_SPOTS else None

    def sync_controls(self, phase: str = "idle"):
        u = core.as_dict(self.summary.get("user"))
        auto_on = bool(u.get("auto_mode", False))

        # 드롭다운 최신화 (대기/입질 중에는 잠금해 혼선 차단)
        self.habitat_select.refresh()
        self.habitat_select.disabled = phase in ("waiting_bite", "biting")
        self.bait_select.refresh()
        self.bait_select.disabled = phase in ("waiting_bite", "biting")

        # 핵심 액션 버튼 상태 (간결한 라벨로 6,000B 페이로드 여유 유지)
        if phase == "waiting_bite":
            self.btn_cast.disabled = True
            self.btn_cast.label = "🌊 대기중..."
            self.btn_pull.disabled = True
            self.btn_pull.style = discord.ButtonStyle.secondary
            self.btn_pull.label = "⏳ 입질 전"
            self.btn_retract.disabled = False
        elif phase == "biting":
            self.btn_cast.disabled = True
            self.btn_cast.label = "⚡ 입질!"
            self.btn_pull.disabled = False
            self.btn_pull.style = discord.ButtonStyle.success
            self.btn_pull.label = "🎣 지금 당기기!"
            self.btn_retract.disabled = False
        else:
            self.btn_cast.disabled = False
            self.btn_cast.label = "⚡ 빠른 낚시" if auto_on else "🪝 찌 던지기"
            self.btn_pull.disabled = True
            self.btn_pull.style = discord.ButtonStyle.secondary
            self.btn_pull.label = "🎣 당기기"
            self.btn_retract.disabled = True

        self.btn_auto_toggle.label = "⏩ 자동: ON" if auto_on else "⏩ 자동: OFF"
        self.btn_auto_toggle.style = discord.ButtonStyle.primary if auto_on else discord.ButtonStyle.secondary

        pending = self._get_pending_fish_list()
        entries = self._get_catch_entries()
        total_cards = len(entries)
        if total_cards > 0:
            self.catch_card_idx = max(0, min(self.catch_card_idx, total_cards - 1))
        else:
            self.catch_card_idx = 0

        has_catch = bool(pending) and phase in ("idle", "resolved")
        if len(pending) > 1:
            self.btn_sell_last.label = f"💰 {len(pending)}마리 판매"
            self.btn_tank_last.label = "🐠 전시"
            self.btn_release_last.label = f"🌊 방생({len(pending)})"
        else:
            self.btn_sell_last.label = "💰 판매"
            self.btn_tank_last.label = "🐠 수족관"
            self.btn_release_last.label = "🌊 방생"
        self.btn_sell_last.disabled = not has_catch
        self.btn_tank_last.disabled = not has_catch
        self.btn_release_last.disabled = not has_catch

        can_nav_cards = (total_cards > 1) and phase in ("idle", "resolved")
        if total_cards > 1:
            self.btn_prev_fish_card.label = f"◀ ({self.catch_card_idx + 1}/{total_cards})"
            self.btn_next_fish_card.label = f"다음 ({self.catch_card_idx + 1}/{total_cards}) ▶"
        else:
            self.btn_prev_fish_card.label = "◀ 이전"
            self.btn_next_fish_card.label = "다음 ▶"
        self.btn_prev_fish_card.disabled = (not can_nav_cards) or (self.catch_card_idx <= 0)
        self.btn_next_fish_card.disabled = (not can_nav_cards) or (self.catch_card_idx >= total_cards - 1)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                "❌ 본인의 낚싯대만 조작할 수 있습니다! 직접 **`/설정`** (`🎮 미니게임` ➔ `🎣 세카이 낚시 출조`)으로 나만의 낚시터를 열어보세요.",
                ephemeral=True,
            )
            return False
        if not self.user:
            self.user = interaction.user
        return True

    def build_dashboard_embed(self, status_banner: Optional[str] = None, phase: str = "idle") -> discord.Embed:
        u = core.as_dict(self.summary.get("user"))
        env = self.summary.get("env") or fishing_core.get_current_fishing_env()
        market = self.summary.get("market") or fishing_core.get_current_fish_market(env["now"])
        hab = fishing_core.HABITATS.get(self.habitat, fishing_core.HABITATS["lake"])
        spot_meta = fishing_core.SPECIAL_SPOTS.get(self.spot_id) if self.spot_id else None
        rod = self.summary.get("rod") or fishing_core.RODS["bamboo"]
        reel = self.summary.get("reel") or fishing_core.REELS["basic_reel"]
        net = self.summary.get("net")
        bait = self.summary.get("bait") or fishing_core.BAITS["dough"]
        enh = self.summary.get("enhance") or fishing_core.get_gear_enhance_bonuses(u)
        crystals = int(self.summary.get("crystals", 0) or 0)
        cur_bait_id = u.get("selected_bait", "dough")
        bait_qty_txt = "무제한" if bait.get("unlimited") else f"{core.as_dict(u.get('baits')).get(cur_bait_id, 0)}개 남음"

        rod_lv_tag = f" **`+{enh['rod_lv']}`**" if int(enh.get("rod_lv", 0)) > 0 else ""
        reel_lv_tag = f" **`+{enh['reel_lv']}`**" if int(enh.get("reel_lv", 0)) > 0 else ""
        net_lv_tag = f" **`+{enh['net_lv']}`**" if int(enh.get("net_lv", 0)) > 0 else ""
        eff_win = float(reel["window_sec"]) + float(enh.get("window_sec", 0.0))

        net_line = (
            f"• **그물:** {net['emoji']} `{net['name']}`{net_lv_tag} (1회 `{net['min_catch']}~{net['max_catch']}마리` 포획 · 희귀 `+{int(net['rare_bonus']*100)}%`)\n"
            if net
            else "• **그물:** 🚫 `미장착` *(상점 `🕸️ 그물` 탭에서 구매 시 1회 2~10마리 포획!)*\n"
        )

        color_val = spot_meta["discord_color"] if spot_meta else hab["discord_color"]
        if phase == "biting":
            color_val = 0x22C55E
        elif phase == "waiting_bite":
            color_val = 0x0EA5E9

        loc_name = f"{spot_meta['emoji']} {spot_meta['name']}" if spot_meta else f"{hab['emoji']} {hab['name']}"
        title_prefix = {
            "waiting_bite": "🌊 찌를 던졌습니다! 수면을 주시하세요...",
            "biting": "⚡ 찌가 물속으로 깊이 끌려갑니다! 지금 당기세요!",
        }.get(phase, f"{loc_name} — {self.user.display_name}님의 낚시터")

        if spot_meta:
            loc_line = f"• **특수 낚시터:** {spot_meta['emoji']} **`{spot_meta['name']}`** (기반: {hab['name']})"
            loc_desc = spot_meta["desc"]
        else:
            zone_txt = (
                f"🎯 `{self.zone_filter}` (출현율 3.2배 집중)"
                if self.zone_filter and self.zone_filter != "all"
                else f"`전체 수역 ({len(fishing_core.FISH_BY_HABITAT[self.habitat]):,}종)`"
            )
            loc_line = f"• **현재 장소:** {hab['label']}  ·  **수역:** {zone_txt}"
            loc_desc = hab["desc"]

        combo = int(u.get("combo", 0) or 0)
        combo_line = (
            f"• **⚡ 연속 성공 콤보:** **`{combo}연승`** *(희귀 `+{int(min(30, combo * 1.5))}%` · EXP `+{min(40, combo * 2)}%` · 변이율 ↑)*"
            if combo >= 2
            else "• **⚡ 연속 콤보:** `0` *(연속 채집 성공 시 최대 20연승 보너스!)*"
        )

        desc_lines = [
            loc_line,
            f"> *{loc_desc}*",
            "",
            f"• **KST 시간/물때:** {env['time_label']} · `{env['feeding_label']}`",
            f"• **현재 날씨 (2시간):** {env['weather_emoji']} **`{env['weather_name']}`** *(다음 변화까지 `{env['remain_str']}` · 희귀 ×{env['weather_rare_mult']:.2f})*",
            combo_line,
            f"• **📈 실시간 어시장:** {market['headline']} *(갱신 `{market['remain_str']}`)*",
        ]
        if status_banner:
            desc_lines.append("")
            desc_lines.append(status_banner)

        embed = discord.Embed(
            title=title_prefix[:256],
            description="\n".join(desc_lines)[:4096],
            color=color_val,
            timestamp=datetime.datetime.now(core.KST),
        )
        eff_rare_pct = int(round((float(rod["rare_bonus"]) + float(enh.get("rare_bonus", 0.0))) * 100))
        eff_gold_pct = int(round((float(rod["gold_bonus"]) + float(enh.get("gold_bonus", 0.0))) * 100))
        embed.add_field(
            name="🧰 장착 장비 & 미끼",
            value=(
                f"• **낚싯대:** {rod['emoji']} `{rod['name']}`{rod_lv_tag} (희귀 `+{eff_rare_pct}%` · 판매 `+{eff_gold_pct}%`)\n"
                f"• **릴:** {reel['emoji']} `{reel['name']}`{reel_lv_tag} (입질 허용 `{eff_win:.1f}초+유예`)\n"
                f"{net_line}"
                f"• **미끼:** {bait['emoji']} `{bait['name']}` (`{bait_qty_txt}`)"
            ),
            inline=False,
        )
        life_buffs = self.summary.get("life_buffs") or {}
        eff_cd = max(1.5, round(fishing_core.FISHING_CAST_COOLDOWN_SECONDS - float(life_buffs.get("cooldown_reduce", 0.0) or 0.0), 1))
        cd_note = f"{eff_cd:.1f}초 (버프 적용)" if float(life_buffs.get("cooldown_reduce", 0.0) or 0.0) > 0 else "4초"
        life_lines = life_buffs.get("summary_lines") or []
        if life_lines:
            embed.add_field(
                name="🐾 생활 버프 적용 중 (/설정 ➔ 세카이 라이프 펫·요리·공동농장)",
                value="\n".join(f"• {ln}" for ln in life_lines[:4])
                + f"\n└ 통합: 쿨타임 `-{float(life_buffs.get('cooldown_reduce', 0.0)):.1f}초` · 희귀 `+{int(float(life_buffs.get('rare_bonus', 0.0))*100)}%` · 골드 `+{int(float(life_buffs.get('gold_bonus', 0.0))*100)}%`",
                inline=False,
            )
        bag_cap = fishing_core.get_bag_capacity(u)
        bag_cnt = len(u.get("bag", []))
        bag_warn = ""
        if bag_cap > 0:
            if bag_cnt >= bag_cap:
                bag_warn = " 🚨 **가득 참!**"
            elif bag_cnt / bag_cap >= 0.85:
                bag_warn = " ⚠️ **거의 가득 참**"
        embed.add_field(
            name=f"💰 재화 & 낚시꾼 Lv.{u.get('level', 1)}",
            value=(
                f"• **🪙 낚시 골드:** **`{int(u.get('gold', 0)):,}🪙`**  ·  **💎 크리스탈:** **`{crystals:,}💎`**\n"
                f"• **🎒 가방:** `{bag_cnt:,}/{bag_cap:,}마리`{bag_warn}  ·  **📖 도감:** `{len(u.get('pokedex', {})):,}/{len(fishing_core.FISH_SPECIES_DB):,}종`  ·  **🐠 수족관:** `{len(u.get('tank', [])):,}/{u.get('tank_slots', 4)}칸`"
            ),
            inline=False,
        )
        embed.set_footer(text=f"💡 [🪝 찌 던지기](쿨타임 {cd_note}) ➔ 입질 시 초록색 [🎣 지금 당기기!] 클릭 · /낚시 시세 · /낚시 레이드 · /낚시 공방 · /낚시 대결")
        return embed

    def build_catch_embed(self, res: Dict[str, Any]) -> discord.Embed:
        catches = res.get("catches") or []
        catch_count = int(res.get("catch_count", len(catches) or 1) or 1)
        if catches:
            idx = max(0, min(self.catch_card_idx, len(catches) - 1))
            cur_entry = catches[idx]
            fish = cur_entry.get("fish") or res["fish"]
            sp = cur_entry.get("species") or res["species"]
        else:
            idx = 0
            fish = res["fish"]
            sp = res["species"]

        hab = fishing_core.HABITATS[sp["habitat"]]
        spot_meta = res.get("spot")
        rmeta = fishing_core.RARITY_META[sp["rarity"]]
        net = res.get("net") or self.summary.get("net")

        tags = []
        if res.get("any_server_record") or res.get("new_server_len_record") or res.get("new_server_wt_record"):
            tags.append("🏆 **서버 신기록 경신!**")
        v_id = str(fish.get("variant") or "normal")
        if v_id != "normal":
            vm = fishing_core.get_variant_meta(v_id)
            tags.append(f"{vm['emoji']} **{vm['name']} (×{vm['gold_mult']:.1f}🪙)!**")
        elif res.get("any_variant"):
            tags.append("✨ **희귀 변이 개체 포획!**")
        crown_id = fish.get("crown")
        if crown_id in fishing_core.CROWN_META:
            cm = fishing_core.CROWN_META[crown_id]
            tags.append(f"{cm['emoji']} **{cm['name']} 달성!**")
        elif fish.get("is_trophy") or any(c.get("fish", {}).get("is_trophy") for c in catches):
            tags.append("👑 **대물 월척!**")
        if res.get("any_seasonal_bonus") or fish.get("is_seasonal"):
            tags.append("🌸 **제철 어종(+25%🪙)!**")
        if res.get("any_first_catch") or res.get("is_first_catch"):
            tags.append("🆕 **도감 첫 등록!**")
        if res.get("perfect_hook"):
            tags.append("⚡ **번개 챔질!**")
        combo_n = int(res.get("combo", 0) or 0)
        if combo_n >= 2:
            tags.append(f"🔥 **{combo_n}연승 콤보!**")
        if res.get("leveled_up"):
            tags.append(f"🆙 **낚시 Lv.{res['new_level']} 달성!**")

        tag_line = "  ·  ".join(tags) if tags else "✨ 깔끔하게 낚아 올렸습니다!"
        bait_rem = "무제한" if res["remaining_bait"] < 0 else f"{res['remaining_bait']}개 남음"
        loc_badge = f"{spot_meta['emoji']} `{spot_meta['name']}`" if isinstance(spot_meta, dict) else f"{hab['emoji']} `{hab['name']} · {sp.get('sub_zone') or sp.get('zone', '')}`"

        if catch_count > 1 and catches:
            net_lbl = f"{net['emoji']} `{net['name']}`" if isinstance(net, dict) else "🕸️ 그물"
            total_gold = int(res.get("total_gold_value", sum(c["fish"]["gold"] for c in catches)))
            haul_lines = []
            for c_idx, c in enumerate(catches, 1):
                cf = c["fish"]
                csp = c["species"]
                crm = fishing_core.RARITY_META[csp["rarity"]]
                b_icons = ""
                if c.get("new_server_len_record") or c.get("new_server_wt_record"):
                    b_icons += "🏆"
                c_vid = str(cf.get("variant") or "normal")
                if c_vid != "normal":
                    b_icons += fishing_core.get_variant_meta(c_vid)["emoji"]
                c_cr = cf.get("crown")
                if c_cr in fishing_core.CROWN_META:
                    b_icons += fishing_core.CROWN_META[c_cr]["emoji"]
                elif cf.get("is_trophy"):
                    b_icons += "👑"
                if cf.get("is_seasonal"):
                    b_icons += "🌸"
                if c.get("is_first_catch"):
                    b_icons += "🆕"
                b_suffix = f" {b_icons}" if b_icons else ""
                pointer = "👉 " if (c_idx - 1) == idx else "   "
                haul_lines.append(
                    f"{pointer}`{c_idx:2d}.` {cf['emoji']} {crm['stars']} **{cf['name']}** — `{cf['length_cm']:.1f}cm` · `{_format_weight(cf['weight_kg'])}` · **`{cf['gold']:,}🪙`**{b_suffix}"
                )
            desc = (
                f"{tag_line}\n"
                f"• **사용 장비:** {net_lbl} (**총 `{catch_count}마리` 포획** · 희귀/변이순 정렬)\n"
                f"• **총 추정 판매가:** **`{total_gold:,}🪙`**  ·  **총 EXP:** `+{res['gain_exp']:,}`\n\n"
                f"🪪 **현재 조회 중인 포획 카드 (`{idx + 1} / {len(catches)}`)**\n"
                f"• **어종:** {fish['emoji']} **{fish['name']}** (`{sp['scientific_name']}`) — {rmeta['emoji']} **`{rmeta['name']} ({rmeta['full_stars']})`**\n"
                f"• **장소:** {loc_badge}  ·  **체장/무게:** **`{fish['length_cm']:.1f} cm`** · **`{_format_weight(fish['weight_kg'])}`** (`{fish['gold']:,}🪙`)\n"
                f"> *{sp['desc']}*\n\n"
                "**📦 이번 투망 포획 목록 (`[다음 ▶]` 버튼으로 카드 전환)**\n"
                + "\n".join(haul_lines)
            )
            title = f"{net['emoji'] if isinstance(net, dict) else '🕸️'} [{spot_meta['name'] if isinstance(spot_meta, dict) else hab['name']}] 그물 {catch_count}마리 포획! ({idx + 1}/{len(catches)}: ★{sp['rarity']} {fish['name']})"
        else:
            desc = (
                f"{tag_line}\n\n"
                f"• **장소:** {loc_badge}\n"
                f"• **등급:** {rmeta['emoji']} **`{rmeta['name']} ({rmeta['full_stars']})`**\n"
                f"• **체장 / 무게:** **`{fish['length_cm']:.1f} cm`**  ·  **`{_format_weight(fish['weight_kg'])}`**\n"
                f"• **추정 판매가:** **`{fish['gold']:,}🪙`**  ·  **EXP:** `+{res['gain_exp']}`\n"
                f"> *{sp['desc']}*"
            )
            title = f"{fish['emoji']} [{spot_meta['name'] if isinstance(spot_meta, dict) else hab['name']}] {fish['name']} ({sp['scientific_name']}) 포획 성공!"

        # 돌발 보물상자 · 표류물 인양 알림
        tdrop = res.get("treasure_drop")
        if isinstance(tdrop, dict):
            loot_parts = []
            if tdrop.get("gold", 0) > 0:
                loot_parts.append(f"`+{tdrop['gold']:,}🪙`")
            if tdrop.get("crystals", 0) > 0:
                loot_parts.append(f"`+{tdrop['crystals']:,}💎`")
            if tdrop.get("bait_qty", 0) > 0:
                loot_parts.append(f"`{tdrop['bait_name']} ×{tdrop['bait_qty']}`")
            desc += f"\n\n🏴‍☠️ **돌발 인양!! {tdrop['emoji']} {tdrop['name']}** — {' · '.join(loot_parts)}\n> *{tdrop['flavor']}*"

        # 폭풍우/피딩타임 서버 협동 보스 돌발 출현 알림
        b_spawn = res.get("boss_spawned")
        if isinstance(b_spawn, dict):
            desc += f"\n\n🚨 **서버 대어 보스 출현!!** {b_spawn['emoji']} **{b_spawn['name']}** (HP `{b_spawn['max_hp']:,}`) 등장! `/낚시 레이드` 명령으로 서버원들과 협동 토벌하세요!"

        if res.get("bonus_reasons"):
            reasons_txt = ", ".join(res["bonus_reasons"][:5])
            if len(res["bonus_reasons"]) > 5:
                reasons_txt += f" 외 {len(res['bonus_reasons']) - 5}건"
            desc += f"\n\n💎 **크리스탈 보너스:** `+{res['crystal_bonus']:,}💎` ({reasons_txt})"
        t_upd = res.get("tournament_update")
        if isinstance(t_upd, dict):
            leader_tag = " 🔥 **(현재 단독 1위 등극!)**" if t_upd.get("became_leader") else ""
            s_hits = t_upd.get("seasonal_hit_names") or []
            s_note = f" · 🌸 제철 보너스1.5배(`{', '.join(s_hits[:2])}`)" if s_hits else ""
            desc += (
                f"\n🏅 **[{t_upd.get('title', '낚시 대회')}]** 현재 **`{t_upd.get('rank', 1)}위 / {t_upd.get('total_participants', 1)}명`**"
                f" (`+{t_upd.get('gained_pts', 0):,}pt` · `+{t_upd.get('gained_kg', 0):.2f}kg`{s_note}){leader_tag}"
            )
        life_buffs = res.get("life_buffs") or {}
        if life_buffs.get("summary_lines"):
            desc += (
                f"\n🐾 **생활 버프 적용:** 희귀 `+{int(float(life_buffs.get('rare_bonus', 0.0))*100)}%` · "
                f"골드 `+{int(float(life_buffs.get('gold_bonus', 0.0))*100)}%` · "
                f"크기 `+{int(float(life_buffs.get('size_bonus', 0.0))*100)}%`"
            )
        if res.get("auto_sold_msg"):
            desc += f"\n📦 *{res['auto_sold_msg']}*"

        embed = discord.Embed(
            title=title[:256],
            description=desc[:4096],
            color=rmeta["discord_color"],
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.add_field(
            name="📊 내 낚시 현황",
            value=(
                f"🪙 보유 골드: **`{res['user_gold']:,}🪙`**  ·  💎 크리스탈: **`{res['user_crystals']:,}💎`**  ·  "
                f"미끼({res['bait']['name']}): `{bait_rem}`\n"
                f"🎒 *포획한 물고기는 가방에 안전 저장되었습니다! 아래 버튼으로 즉시 시세 판매/수족관 전시할 수 있습니다.*"
            ),
            inline=False,
        )
        return embed

    async def _get_or_render_catch_card_bytes(self, res: Dict[str, Any], card_idx: int) -> Optional[bytes]:
        cached = self._catch_card_cache.get(card_idx)
        if cached is not None:
            return cached
        png_buf = await asyncio.to_thread(
            fishing_core.build_catch_card_bytes,
            res,
            self.user.display_name,
            card_idx,
        )
        png_bytes = png_buf.getvalue() if png_buf is not None else None
        if png_bytes is not None:
            self._catch_card_cache[card_idx] = png_bytes
        return png_bytes

    async def _present_catch_result(
        self,
        interaction: Optional[discord.Interaction],
        message: Optional[discord.Message],
        res: Dict[str, Any],
        card_idx: int = 0,
    ):
        if self.last_catch is not res:
            self._catch_card_cache.clear()
        self.last_catch = res
        self.catch_card_idx = max(0, int(card_idx or 0))
        catches = res.get("catches")
        if isinstance(catches, list) and catches:
            self.catch_card_idx = min(self.catch_card_idx, len(catches) - 1)
            self.last_catches = [
                c["fish"] for c in catches
                if isinstance(c, dict) and isinstance(c.get("fish"), dict)
            ]
        elif isinstance(res.get("fish"), dict):
            self.catch_card_idx = 0
            self.last_catches = [res["fish"]]
        else:
            self.catch_card_idx = 0
            self.last_catches = []
        await self.refresh_summary()
        self.sync_controls(phase="idle")
        embed = self.build_catch_embed(res)
        png_bytes = await self._get_or_render_catch_card_bytes(res, self.catch_card_idx)
        if png_bytes is not None:
            embed.set_image(url="attachment://catch_card.png")
        try:
            updated_msg = await _safe_update_message_or_interaction(
                interaction,
                message,
                embed=embed,
                view=self,
                png_bytes=png_bytes,
                png_filename="catch_card.png",
                content=None,
                raise_on_fail=True,
            )
            if updated_msg is not None:
                self.message = updated_msg
        except Exception as edit_err:
            print(f"⚠️ [낚시 포획 결과 편집 폴백] {edit_err}", flush=True)
            if interaction is not None:
                try:
                    if png_bytes is not None:
                        sent = await interaction.followup.send(
                            embed=embed,
                            file=discord.File(fp=io.BytesIO(png_bytes), filename="catch_card.png"),
                            view=self,
                            wait=True,
                        )
                    else:
                        sent = await interaction.followup.send(embed=embed, view=self, wait=True)
                    self.message = sent
                except Exception:
                    try:
                        no_img = _strip_attachment_image(embed)
                        sent = await interaction.followup.send(embed=no_img, view=self, wait=True)
                        self.message = sent
                    except Exception:
                        pass

    @discord.ui.button(label="🪝 찌 던지기", style=discord.ButtonStyle.primary, row=2)
    async def btn_cast(self, interaction: discord.Interaction, button: discord.ui.Button):
        allowed, rem_sec = fishing_core.check_and_update_fishing_cooldown(interaction.user.id, guild_id=self.guild_id)
        if not allowed:
            await core.safe_send_response(
                interaction,
                f"⏳ **낚시 출조(낚기) 쿨타임입니다!** `{rem_sec:.1f}초` 후에 다시 찌를 던져주세요.",
                ephemeral=True,
            )
            return

        await core.safe_defer(interaction)
        target_msg = interaction.message or self.message
        self.message = target_msg

        params = await asyncio.to_thread(
            fishing_core.prepare_cast_parameters,
            self.guild_id,
            self.user.id,
            self.user.display_name,
        )

        sess = _get_or_create_cast_session(self.guild_id, self.user.id)
        async with sess.lock:
            _cancel_session_tasks(sess)
            sess.cast_seq += 1
            my_seq = sess.cast_seq
            sess.habitat = params["habitat"]
            sess.zone_filter = params.get("zone_filter", "all")
            sess.spot_id = params.get("spot_id")
            sess.bait_id = params["bait_id"]
            sess.window_sec = params["window_sec"]
            sess.grace_sec = params["grace_sec"]
            sess.updated_at = time.monotonic()

            is_auto = bool(params["auto_mode"])
            sess.phase = "resolved" if is_auto else "waiting_bite"

        if is_auto:
            res = await asyncio.to_thread(
                fishing_core.finalize_fish_catch,
                self.guild_id,
                self.user.id,
                self.user.display_name,
                params["habitat"],
                params["bait_id"],
                None,
                params.get("zone_filter", "all"),
                params.get("spot_id"),
            )
            await self._present_catch_result(interaction, target_msg, res)
            return

        # 대기 단계 UI 반영
        self.sync_controls(phase="waiting_bite")
        spot_obj = params.get("spot")
        if isinstance(spot_obj, dict):
            loc_str = f"{spot_obj['emoji']} {spot_obj['name']}"
        else:
            zone_note = f" `{params.get('zone_filter')}`" if params.get("zone_filter", "all") != "all" else ""
            loc_str = f"{fishing_core.HABITATS[params['habitat']]['name']}{zone_note}"
        wait_embed = self.build_dashboard_embed(
            status_banner=f"🪝 **{loc_str}** 수면 위로 찌를 힘껏 던졌습니다! 곧 입질이 옵니다...",
            phase="waiting_bite",
        )
        target_msg = await _safe_update_message_or_interaction(
            interaction,
            target_msg,
            embed=wait_embed,
            view=self,
            clear_attachments=True,
            content=None,
        )
        self.message = target_msg

        async def _wait_and_bite():
            try:
                await asyncio.sleep(params["wait_sec"])
                async with sess.lock:
                    if sess.cast_seq != my_seq or sess.phase != "waiting_bite":
                        return
                    sess.phase = "biting"
                    sess.updated_at = time.monotonic()

                self.sync_controls(phase="biting")
                bite_embed = self.build_dashboard_embed(
                    status_banner=(
                        f"🚨 **입질 경보!!** 찌가 수면 아래로 강하게 빨려 들어갑니다!\n"
                        f"👉 **`{params['window_sec']:.1f}초`** 안에 초록색 **`[🎣 지금 당기기!]`** 버튼을 눌러 채집하세요!"
                    ),
                    phase="biting",
                )
                try:
                    updated_bite_msg = await _safe_update_message_or_interaction(
                        interaction,
                        self.message,
                        embed=bite_embed,
                        view=self,
                        clear_attachments=True,
                        raise_on_fail=True,
                    )
                    if updated_bite_msg is not None:
                        self.message = updated_bite_msg
                except Exception as bite_edit_err:
                    print(f"⚠️ [낚시 입질 UI 갱신 실패] {bite_edit_err}", flush=True)
                    async with sess.lock:
                        if sess.cast_seq == my_seq and sess.phase == "biting":
                            sess.phase = "idle"
                            sess.updated_at = time.monotonic()
                    self.sync_controls(phase="idle")
                    try:
                        await interaction.followup.send(
                            "⚠️ 입질 신호 메시지를 갱신하지 못해 출조를 초기화했습니다. `[🪝 찌 던지기]`를 다시 눌러주세요.",
                            ephemeral=True,
                        )
                    except Exception:
                        pass
                    return

                async def _on_bite_expire():
                    try:
                        await asyncio.sleep(params["window_sec"] + params["grace_sec"])
                        async with sess.lock:
                            if sess.cast_seq != my_seq or sess.phase != "biting":
                                return
                            sess.phase = "idle"
                            sess.updated_at = time.monotonic()
                        prev_combo = await asyncio.to_thread(
                            fishing_core.reset_fishing_combo, self.guild_id, self.user.id
                        )
                        await self.refresh_summary()
                        async with sess.lock:
                            if sess.cast_seq != my_seq or sess.phase != "idle":
                                return
                        self.sync_controls(phase="idle")
                        combo_lost = f" (💔 `{prev_combo}연승` 콤보 초기화)" if prev_combo >= 2 else ""
                        miss_embed = self.build_dashboard_embed(
                            status_banner=f"💨 **아쉽네요! 물고기가 미끼만 살짝 건드리고 도망갔습니다.**{combo_lost} *(미끼는 소모되지 않았습니다 — 다시 `[🪝 찌 던지기]`를 눌러보세요!)*",
                            phase="idle",
                        )
                        await _safe_update_message_or_interaction(
                            interaction, self.message, embed=miss_embed, view=self, clear_attachments=True
                        )
                    except asyncio.CancelledError:
                        return
                    except Exception as ex:
                        print(f"⚠️ [낚시 입질 만료 태스크 예외] {ex}", flush=True)

                async with sess.lock:
                    if sess.cast_seq != my_seq or sess.phase != "biting":
                        return
                    sess.bite_started_at = time.monotonic()
                    sess.updated_at = sess.bite_started_at
                    sess.expire_task = asyncio.create_task(_on_bite_expire())
            except asyncio.CancelledError:
                return
            except Exception as ex:
                print(f"⚠️ [낚시 대기 태스크 예외] {ex}", flush=True)

        async with sess.lock:
            if sess.cast_seq == my_seq and sess.phase == "waiting_bite":
                sess.wait_task = asyncio.create_task(_wait_and_bite())

    @discord.ui.button(label="🎣 당기기", style=discord.ButtonStyle.secondary, disabled=True, row=2)
    async def btn_pull(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        target_msg = interaction.message or self.message
        self.message = target_msg

        sess = _get_or_create_cast_session(self.guild_id, self.user.id)
        async with sess.lock:
            if sess.phase == "biting":
                _cancel_session_tasks(sess)
                sess.cast_seq += 1
                reaction_sec = max(0.05, time.monotonic() - sess.bite_started_at)
                sess.phase = "resolved"
                sess.updated_at = time.monotonic()
                hab_id = sess.habitat
                z_id = sess.zone_filter
                sp_id = sess.spot_id
                b_id = sess.bait_id
            elif sess.phase == "waiting_bite":
                await interaction.followup.send("⏳ 아직 입질이 오지 않았습니다! 초록색 버튼으로 바뀔 때까지 1~2초만 기다려 주세요.", ephemeral=True)
                return
            else:
                emb_title = ""
                if target_msg and target_msg.embeds:
                    emb_title = f"{target_msg.embeds[0].title or ''} {target_msg.embeds[0].description or ''}"
                if "지금 당기세요" in emb_title or "입질 경보" in emb_title:
                    sess.cast_seq += 1
                    hab_id = self.habitat
                    z_id = self.zone_filter
                    sp_id = self.spot_id
                    b_id = self.summary["user"].get("selected_bait", "dough")
                    reaction_sec = 1.5
                    sess.phase = "resolved"
                else:
                    await self.refresh_summary()
                    self.sync_controls(phase="idle")
                    await _safe_update_message_or_interaction(
                        interaction,
                        target_msg,
                        embed=self.build_dashboard_embed(status_banner="🎣 새로운 출조를 준비했습니다! `[🪝 찌 던지기]`를 눌러 시작하세요."),
                        view=self,
                        clear_attachments=True,
                    )
                    await interaction.followup.send(
                        "💨 이미 입질 시간이 지나갔거나 종료된 출조입니다. `[🪝 찌 던지기]`로 다시 던져주세요!",
                        ephemeral=True,
                    )
                    return

        res = await asyncio.to_thread(
            fishing_core.finalize_fish_catch,
            self.guild_id,
            self.user.id,
            self.user.display_name,
            hab_id,
            b_id,
            reaction_sec,
            z_id,
            sp_id,
        )
        await self._present_catch_result(interaction, target_msg, res)

    @discord.ui.button(label="🛑 회수", style=discord.ButtonStyle.danger, disabled=True, row=2)
    async def btn_retract(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        sess = _get_or_create_cast_session(self.guild_id, self.user.id)
        async with sess.lock:
            _cancel_session_tasks(sess)
            sess.cast_seq += 1
            sess.phase = "idle"
            sess.updated_at = time.monotonic()
        await self.refresh_summary()
        self.sync_controls(phase="idle")
        await _safe_update_message_or_interaction(
            interaction,
            interaction.message or self.message,
            embed=self.build_dashboard_embed(status_banner="🛑 찌를 안전하게 회수했습니다. 장소나 미끼를 바꾸고 다시 던질 수 있습니다."),
            view=self,
            clear_attachments=True,
        )

    @discord.ui.button(label="⏩ 자동: OFF", style=discord.ButtonStyle.secondary, row=2)
    async def btn_auto_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        cur_auto = bool(self.summary["user"].get("auto_mode", False))
        self.summary = await asyncio.to_thread(
            fishing_core.update_user_fishing_prefs,
            self.guild_id,
            self.user.id,
            self.user.display_name,
            auto_mode=not cur_auto,
        )
        self.sync_controls(phase="idle")
        mode_txt = "⚡ **빠른 자동 채집 모드 ON!** 이제 `[⚡ 빠른 낚시]`를 누르면 기다림 없이 즉시 채집됩니다." if not cur_auto else "🎣 **타이밍 미니게임 모드 복귀!** 입질 손맛을 즐겨보세요."
        await _safe_update_message_or_interaction(
            interaction,
            interaction.message or self.message,
            embed=self.build_dashboard_embed(status_banner=mode_txt),
            view=self,
            clear_attachments=True,
        )

    @discord.ui.button(label="📈 시세", style=discord.ButtonStyle.secondary, row=2)
    async def btn_open_market(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        view = FishingMarketView(self.user, self.guild_id)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        view.message = msg

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary, disabled=True, row=3)
    async def btn_prev_fish_card(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        entries = self._get_catch_entries()
        if not isinstance(self.last_catch, dict) or len(entries) <= 1:
            return
        new_idx = max(0, self.catch_card_idx - 1)
        await self._present_catch_result(interaction, interaction.message or self.message, self.last_catch, card_idx=new_idx)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.primary, disabled=True, row=3)
    async def btn_next_fish_card(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        entries = self._get_catch_entries()
        if not isinstance(self.last_catch, dict) or len(entries) <= 1:
            return
        new_idx = min(len(entries) - 1, self.catch_card_idx + 1)
        await self._present_catch_result(interaction, interaction.message or self.message, self.last_catch, card_idx=new_idx)

    @discord.ui.button(label="💰 판매", style=discord.ButtonStyle.success, disabled=True, row=3)
    async def btn_sell_last(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        pending = self._get_pending_fish_list()
        if not pending:
            await interaction.followup.send("ℹ️ 판매할 직전 포획 물고기가 없습니다.", ephemeral=True)
            return
        if len(pending) == 1:
            uid = pending[0]["uid"]
            ok, msg, _ = await asyncio.to_thread(fishing_core.sell_fish_by_uid, self.guild_id, self.user.id, uid)
            if ok:
                self.last_catches = []
                self.last_catch = None
                self._catch_card_cache.clear()
        else:
            uids = [f["uid"] for f in pending]
            ok, msg, _, _, rem_uids = await asyncio.to_thread(
                fishing_core.sell_fishes_by_uids, self.guild_id, self.user.id, uids
            )
            if ok:
                rem_set = set(rem_uids)
                self.last_catches = [f for f in pending if f["uid"] in rem_set]
                if not self.last_catches:
                    self.last_catch = None
                    self._catch_card_cache.clear()
        await self.refresh_summary()
        self.sync_controls(phase="idle")
        await _safe_update_message_or_interaction(interaction, interaction.message or self.message, view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🐠 수족관", style=discord.ButtonStyle.primary, disabled=True, row=3)
    async def btn_tank_last(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        pending = self._get_pending_fish_list()
        if not pending:
            await interaction.followup.send("ℹ️ 전시할 직전 포획 물고기가 없습니다.", ephemeral=True)
            return
        if len(pending) == 1:
            uid = pending[0]["uid"]
            ok, msg = await asyncio.to_thread(fishing_core.move_fish_to_tank, self.guild_id, self.user.id, uid)
            if ok:
                self.last_catches = []
                self.last_catch = None
                self._catch_card_cache.clear()
        else:
            ordered = sorted(
                pending,
                key=lambda f: (int(f.get("rarity", 1)), int(f.get("gold", 0)), float(f.get("length_cm", 0))),
                reverse=True,
            )
            uids = [f["uid"] for f in ordered]
            ok, msg, _, rem_uids = await asyncio.to_thread(
                fishing_core.move_fishes_to_tank, self.guild_id, self.user.id, uids
            )
            if ok:
                rem_set = set(rem_uids)
                self.last_catches = [f for f in ordered if f["uid"] in rem_set]
                if not self.last_catches:
                    self.last_catch = None
                    self._catch_card_cache.clear()
        await self.refresh_summary()
        self.sync_controls(phase="idle")
        await _safe_update_message_or_interaction(interaction, interaction.message or self.message, view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🌊 방생", style=discord.ButtonStyle.secondary, disabled=True, row=3)
    async def btn_release_last(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        pending = self._get_pending_fish_list()
        if not pending:
            await interaction.followup.send("ℹ️ 방생할 직전 포획 물고기가 없습니다.", ephemeral=True)
            return
        if len(pending) == 1:
            uid = pending[0]["uid"]
            ok, msg = await asyncio.to_thread(fishing_core.release_fish_by_uid, self.guild_id, self.user.id, uid)
            if ok:
                self.last_catches = []
                self.last_catch = None
                self._catch_card_cache.clear()
        else:
            uids = [f["uid"] for f in pending]
            ok, msg, _, _, rem_uids = await asyncio.to_thread(
                fishing_core.release_fishes_by_uids, self.guild_id, self.user.id, uids
            )
            if ok:
                rem_set = set(rem_uids)
                self.last_catches = [f for f in pending if f["uid"] in rem_set]
                if not self.last_catches:
                    self.last_catch = None
                    self._catch_card_cache.clear()
        await self.refresh_summary()
        self.sync_controls(phase="idle")
        await _safe_update_message_or_interaction(interaction, interaction.message or self.message, view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🛒 상점", style=discord.ButtonStyle.secondary, row=4)
    async def btn_open_shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary, self.guild_id, self.user.id, self.user.display_name
        )
        view = FishingShopView(self.user, self.guild_id, summary=summary)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        view.message = msg

    @discord.ui.button(label="🎒 가방", style=discord.ButtonStyle.secondary, row=4)
    async def btn_open_bag(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary, self.guild_id, self.user.id, self.user.display_name
        )
        view = FishingBagView(self.user, self.guild_id, summary=summary)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        view.message = msg

    @discord.ui.button(label="📖 도감", style=discord.ButtonStyle.secondary, row=4)
    async def btn_open_pokedex(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        stats = await asyncio.to_thread(
            fishing_core.get_fishing_pokedex_stats, self.guild_id, self.user.id
        )
        view = FishingPokedexView(self.user, self.guild_id, stats=stats)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        view.message = msg

    @discord.ui.button(label="🐠 수족관", style=discord.ButtonStyle.secondary, row=4)
    async def btn_open_tank(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary, self.guild_id, self.user.id, self.user.display_name
        )
        view = FishingAquariumView(self.user, self.user, self.guild_id, summary=summary)
        msg = await view.send_initial(interaction, ephemeral=True)
        view.message = msg

    @discord.ui.button(label="🏆 랭킹", style=discord.ButtonStyle.secondary, row=4)
    async def btn_open_rank(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        view = FishingRankingView(self.user, self.guild_id)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        view.message = msg



# ==========================================
# 2. 낚시 가방 (보관함 · 잠금 · 실시간 시세 판매 · 스마트 정리 · 선물 · 수족관 전시)
# ==========================================
class FishingGiftRecipientView(core.SafeView):
    """가방에서 선택한 물고기를 받을 멤버를 고르는 선물 전달 뷰"""

    def __init__(
        self,
        user: discord.abc.User,
        guild_id: int = 0,
        fish_uid: str = "",
        fish_label: str = "물고기",
    ):
        super().__init__(timeout=180)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.fish_uid = str(fish_uid or "")
        self.fish_label = str(fish_label or "물고기")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 선물 창을 연 본인만 선택할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="🎁 물고기를 선물할 서버 멤버를 선택하세요...",
        min_values=1,
        max_values=1,
        row=0,
    )
    async def select_recipient(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        await core.safe_defer(interaction, ephemeral=True)
        if not self.fish_uid:
            await interaction.followup.send("⚠️ 선물할 물고기 정보가 유실되었습니다. 가방에서 다시 시도해 주세요.", ephemeral=True)
            return
        target = select.values[0]
        if getattr(target, "bot", False):
            await interaction.followup.send("❌ 봇에게는 물고기를 선물할 수 없습니다!", ephemeral=True)
            return
        gid = self.guild_id or (interaction.guild_id or 0)
        ok, msg, _ = await asyncio.to_thread(
            fishing_core.gift_fish_to_user,
            gid,
            interaction.user.id,
            interaction.user.display_name,
            target.id,
            target.display_name,
            self.fish_uid,
        )
        select.disabled = True
        try:
            await core.safe_edit_response(interaction, content=msg, view=self)
        except Exception:
            await interaction.followup.send(msg, ephemeral=True)


class FishingBagSelect(discord.ui.Select):
    def __init__(self, parent_view: "FishingBagView"):
        self.parent_view = parent_view
        opts = self._build_opts()
        is_empty = (len(opts) == 1 and opts[0].value == "NONE")
        super().__init__(
            placeholder="🐟 여러 마리 동시 선택 가능 (잠금 · 잠금해제 · 판매 · 전시 · 선물)...",
            min_values=1 if is_empty else 0,
            max_values=1 if is_empty else len(opts),
            options=opts,
            row=0,
            custom_id="norosi:FishingBagView:bag_select",
        )
        self.disabled = is_empty

    def _build_opts(self) -> List[discord.SelectOption]:
        items = self.parent_view.get_page_items()
        if not items:
            return [discord.SelectOption(label="표시할 물고기가 없습니다", value="NONE")]
        sel_set = set(self.parent_view.selected_uids)
        market = self.parent_view.summary.get("market") or fishing_core.get_current_fish_market()
        opts = []
        seen_vals = set()
        for it in items[:25]:
            uid_s = str(it.get("uid") or "")[:100]
            if not uid_s or uid_s in seen_vals:
                continue
            seen_vals.add(uid_s)
            lock_icon = "🔒" if it.get("locked") else ""
            v_em = fishing_core.get_variant_meta(it.get("variant"))["emoji"]
            cr_id = it.get("crown")
            cr_em = fishing_core.CROWN_META[cr_id]["emoji"] if cr_id in fishing_core.CROWN_META else ("👑" if it.get("is_trophy") else "")
            hab_name = fishing_core.HABITATS.get(it.get("habitat", "lake"), fishing_core.HABITATS["lake"]).get("name", "호수")
            cm_val = float(it.get("length_cm", 0) or 0)
            wt_val = float(it.get("weight_kg", 0) or 0)
            mk_g, mk_m, _ = fishing_core.compute_market_sell_price(it, market)
            r_val = int(it.get("rarity", 1) or 1)
            lbl = f"{lock_icon}{v_em}{cr_em} ★{r_val} {it.get('name', '물고기')} ({cm_val:.1f}cm)"[:95]
            mk_tag = f" (×{mk_m:.2f})" if mk_m >= 1.15 else ""
            desc = f"[{hab_name}] {_format_weight(wt_val)} · 시세 {mk_g:,}🪙{mk_tag}"[:95]
            opts.append(discord.SelectOption(
                label=lbl,
                value=uid_s,
                description=desc,
                default=(uid_s in sel_set),
            ))
        return opts or [discord.SelectOption(label="표시할 물고기가 없습니다", value="NONE")]

    def refresh(self):
        opts = self._build_opts()
        is_empty = (len(opts) == 1 and opts[0].value == "NONE")
        self.options = opts
        self.disabled = is_empty
        if is_empty:
            self.min_values = 1
            self.max_values = 1
        else:
            self.min_values = 0
            self.max_values = len(opts)

    async def callback(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        page_uids = [str(it.get("uid")) for it in self.parent_view.get_page_items() if it.get("uid")]
        page_set = set(page_uids)
        picked = {str(v) for v in self.values if v and v != "NONE" and str(v) in page_set}
        kept = [uid for uid in self.parent_view.selected_uids if uid not in page_set]
        for uid in page_uids:
            if uid in picked:
                kept.append(uid)
        self.parent_view.selected_uids = kept
        self.parent_view.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.parent_view.build_embed(), view=self.parent_view)


class FishingBagView(core.SafeView):
    def __init__(
        self,
        user: discord.abc.User,
        guild_id: int = 0,
        habitat_filter: str = "all",
        rarity_filter: int = 0,
        summary: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(timeout=None)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.habitat_filter = habitat_filter
        self.rarity_filter = rarity_filter
        self.page = 0
        self.per_page = 10
        self.selected_uids: List[str] = []
        self.summary = summary or fishing_core.get_user_fishing_summary(self.guild_id, user.id, user.display_name)
        self.bag_select = FishingBagSelect(self)
        self.add_item(self.bag_select)
        self.sync_controls()

    def _restore_from_message(self, interaction: discord.Interaction):
        msg = getattr(interaction, "message", None)
        if not msg:
            return
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        for row in getattr(msg, "components", []) or []:
            for comp in getattr(row, "children", []):
                cid = getattr(comp, "custom_id", "") or ""
                lbl = getattr(comp, "label", "") or ""
                if cid.endswith(":btn_filter_hab"):
                    if "호수" in lbl:
                        self.habitat_filter = "lake"
                    elif "강" in lbl:
                        self.habitat_filter = "river"
                    elif "바다" in lbl:
                        self.habitat_filter = "sea"
                    else:
                        self.habitat_filter = "all"
                elif cid.endswith(":btn_filter_rar"):
                    import re as _re
                    m = _re.search(r"★(\d+)", lbl)
                    self.rarity_filter = int(m.group(1)) if m else 0
                elif cid == "norosi:FishingBagView:bag_select":
                    self.selected_uids = [
                        str(opt.value)
                        for opt in (getattr(comp, "options", []) or [])
                        if getattr(opt, "default", False) and getattr(opt, "value", None) not in (None, "NONE")
                    ]
        embeds = getattr(msg, "embeds", None) or []
        if embeds and getattr(embeds[0], "description", None):
            import re as _re
            m = _re.search(r"페이지:\s*`?(\d+)\s*/\s*(\d+)`?", embeds[0].description)
            if m:
                self.page = max(0, int(m.group(1)) - 1)
        self.sync_controls()

    async def reload(self):
        self.summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary,
            self.guild_id,
            self.user.id,
            self.user.display_name,
        )

    def get_filtered(self) -> List[Dict[str, Any]]:
        raw_bag = core.as_dict(self.summary.get("user")).get("bag", [])
        if isinstance(raw_bag, dict):
            raw_bag = list(raw_bag.values())
        bag = list(reversed([it for it in (raw_bag or []) if isinstance(it, dict) and it.get("uid")]))  # 최신 포획 순
        res = []
        for it in bag:
            if self.habitat_filter != "all" and it.get("habitat") != self.habitat_filter:
                continue
            if self.rarity_filter > 0 and int(it.get("rarity", 1)) != self.rarity_filter:
                continue
            res.append(it)
        return res

    def get_page_items(self) -> List[Dict[str, Any]]:
        items = self.get_filtered()
        max_p = max(0, math.ceil(len(items) / self.per_page) - 1)
        self.page = max(0, min(self.page, max_p))
        start = self.page * self.per_page
        return items[start:start + self.per_page]

    def sync_controls(self):
        filtered = self.get_filtered()
        total_p = max(1, math.ceil(len(filtered) / self.per_page))
        self.page = max(0, min(self.page, total_p - 1))
        page_items = self.get_page_items()

        filtered_by_uid = {str(it["uid"]): it for it in filtered if it.get("uid")}
        cleaned_sel: List[str] = []
        seen_sel = set()
        for uid in self.selected_uids:
            u_s = str(uid or "")
            if u_s and u_s in filtered_by_uid and u_s not in seen_sel:
                seen_sel.add(u_s)
                cleaned_sel.append(u_s)
        self.selected_uids = cleaned_sel
        self.bag_select.refresh()

        sel_items = [filtered_by_uid[uid] for uid in self.selected_uids]
        n_sel = len(sel_items)
        has_sel = n_sel > 0
        unlocked_sel = sum(1 for it in sel_items if not it.get("locked"))
        locked_sel = sum(1 for it in sel_items if it.get("locked"))

        self.btn_prev.disabled = (self.page <= 0)
        self.btn_next.disabled = (self.page >= total_p - 1)
        self.btn_select_page.disabled = (len(page_items) == 0)
        self.btn_clear_sel.disabled = not has_sel
        self.btn_clear_sel.label = f"↩️ 해제 ({n_sel})" if n_sel else "↩️ 해제"
        self.btn_lock_sel.disabled = (unlocked_sel == 0)
        self.btn_unlock_sel.disabled = (locked_sel == 0)
        self.btn_sell_one.disabled = not has_sel
        self.btn_sell_one.label = f"💰 선택판매 ({n_sel})" if n_sel else "💰 선택판매"
        self.btn_to_tank.disabled = not has_sel
        self.btn_to_tank.label = f"🐠 전시 ({n_sel})" if n_sel else "🐠 수족관전시"
        self.btn_gift_sel.disabled = (n_sel != 1)

        hab_lbl = {"all": "전체장소", "lake": "🏞️ 호수", "river": "🌊 강", "sea": "⚓ 바다"}.get(self.habitat_filter, "전체장소")
        self.btn_filter_hab.label = f"📍 {hab_lbl}"
        self.btn_filter_rar.label = "⭐ 전체성급" if self.rarity_filter == 0 else f"⭐ ★{self.rarity_filter} 필터"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 낚시 가방만 조작할 수 있습니다.", ephemeral=True)
            return False
        if not self.user:
            self.user = interaction.user
        return True

    def build_embed(self) -> discord.Embed:
        filtered = self.get_filtered()
        total_p = max(1, math.ceil(len(filtered) / self.per_page))
        page_items = self.get_page_items()
        u = self.summary["user"]
        market = self.summary.get("market") or fishing_core.get_current_fish_market()
        bag_raw = u.get("bag", []) if isinstance(u.get("bag"), list) else []
        bag_cap = fishing_core.get_bag_capacity(u)

        total_gold = sum(fishing_core.compute_market_sell_price(i, market)[0] for i in filtered)
        unlocked_gold = sum(fishing_core.compute_market_sell_price(i, market)[0] for i in filtered if not i.get("locked"))
        unlocked_cnt = sum(1 for i in filtered if not i.get("locked"))

        sel_set = set(self.selected_uids)
        filtered_by_uid = {str(it["uid"]): it for it in filtered if it.get("uid")}
        sel_items = [filtered_by_uid[uid] for uid in self.selected_uids if uid in filtered_by_uid]
        sel_gold = sum(fishing_core.compute_market_sell_price(i, market)[0] for i in sel_items)
        sel_summary = (
            f"• **☑️ 현재 선택:** `{len(sel_items):,}마리` (시세 `{sel_gold:,}🪙`)"
            if sel_items
            else "• **☑️ 현재 선택:** `0마리` *(드롭다운 복수 선택 또는 [☑️ 전체선택])*"
        )

        lines = []
        for idx, it in enumerate(page_items, start=self.page * self.per_page + 1):
            mark = "👉 " if str(it.get("uid") or "") in sel_set else ""
            lock_s = "🔒" if it.get("locked") else ""
            v_em = fishing_core.get_variant_meta(it.get("variant"))["emoji"]
            cr_id = it.get("crown")
            cr_s = fishing_core.CROWN_META[cr_id]["emoji"] if cr_id in fishing_core.CROWN_META else ("👑" if it.get("is_trophy") else "")
            gift_s = "🎁" if it.get("gifted_from") else ""
            hab_e = fishing_core.HABITATS.get(it.get("habitat", "lake"), fishing_core.HABITATS["lake"]).get("emoji", "🐟")
            cm_val = float(it.get("length_cm", 0) or 0)
            wt_val = float(it.get("weight_kg", 0) or 0)
            mk_g, mk_m, _ = fishing_core.compute_market_sell_price(it, market)
            r_val = int(it.get("rarity", 1) or 1)
            mk_badge = f" 🔥×{mk_m:.2f}" if mk_m >= 1.5 else (f" 📈×{mk_m:.2f}" if mk_m >= 1.15 else "")
            lines.append(
                f"{mark}`{idx}.` {lock_s}{gift_s}{v_em}{cr_s}{hab_e} **★{r_val} {it.get('name', '물고기')}** — "
                f"`{cm_val:.1f}cm` · `{_format_weight(wt_val)}` · `{mk_g:,}🪙`{mk_badge}"
            )

        body = "\n".join(lines) if lines else "> *(조건에 맞는 물고기가 가방에 없습니다. `/낚시 출조`로 물고기를 낚아 보세요!)*"
        embed = discord.Embed(
            title=f"🎒 {self.user.display_name}님의 낚시 가방 ({len(bag_raw):,}/{bag_cap:,}마리)",
            description=(
                f"• **보유 골드:** `{u['gold']:,}🪙`  ·  **실시간 시세 총액:** `{total_gold:,}🪙` (미잠금 `{unlocked_cnt:,}마리 = {unlocked_gold:,}🪙`)\n"
                f"• **📈 어시장 시세:** {market['headline']}\n"
                f"{sel_summary}  ·  **페이지:** `{self.page + 1} / {total_p}`\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{body}"
            )[:4096],
            color=0x38BDF8,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="🔒 ★4↑·월척·변이·금관은 자동 잠금 · 하단 스마트 정리(★1~2판매/중복정리/미끼제작/선물)로 쾌속 관리!")
        return embed

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=1)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.page = max(0, self.page - 1)
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=1)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.page += 1
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="📍 전체장소", style=discord.ButtonStyle.secondary, row=1)
    async def btn_filter_hab(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        order = ["all", "lake", "river", "sea"]
        self.habitat_filter = order[(order.index(self.habitat_filter) + 1) % len(order)] if self.habitat_filter in order else "all"
        self.page = 0
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="⭐ 전체성급", style=discord.ButtonStyle.secondary, row=1)
    async def btn_filter_rar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.rarity_filter = (self.rarity_filter + 1) % 6
        self.page = 0
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="☑️ 전체선택", style=discord.ButtonStyle.secondary, row=2)
    async def btn_select_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        sel_set = set(self.selected_uids)
        for it in self.get_page_items():
            uid_s = str(it.get("uid") or "")
            if uid_s and uid_s not in sel_set:
                sel_set.add(uid_s)
                self.selected_uids.append(uid_s)
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="↩️ 해제", style=discord.ButtonStyle.secondary, row=2)
    async def btn_clear_sel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.selected_uids = []
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔒 잠금", style=discord.ButtonStyle.secondary, row=2)
    async def btn_lock_sel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        if not self.selected_uids:
            await interaction.followup.send("ℹ️ 먼저 잠금할 물고기를 선택하세요.", ephemeral=True)
            return
        ok, msg, _ = await asyncio.to_thread(
            fishing_core.set_fishes_lock_state, self.guild_id, self.user.id, list(self.selected_uids), True
        )
        await self.reload()
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🔓 잠금해제", style=discord.ButtonStyle.secondary, row=2)
    async def btn_unlock_sel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        if not self.selected_uids:
            await interaction.followup.send("ℹ️ 먼저 잠금 해제할 물고기를 선택하세요.", ephemeral=True)
            return
        ok, msg, _ = await asyncio.to_thread(
            fishing_core.set_fishes_lock_state, self.guild_id, self.user.id, list(self.selected_uids), False
        )
        await self.reload()
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="💰 선택판매", style=discord.ButtonStyle.success, row=3)
    async def btn_sell_one(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        target_uids = list(self.selected_uids)
        if not target_uids:
            await interaction.followup.send("ℹ️ 먼저 판매할 물고기를 선택하세요.", ephemeral=True)
            return
        if len(target_uids) == 1:
            sel_uid = target_uids[0]
            sel_item = next((x for x in self.summary["user"].get("bag", []) if isinstance(x, dict) and x.get("uid") == sel_uid), None)
            if sel_item and sel_item.get("locked"):
                await interaction.followup.send("🔒 잠금 보호 중인 물고기입니다! 먼저 `[🔓 잠금해제]`로 잠금을 풀어주세요.", ephemeral=True)
                return
            ok, msg, _ = await asyncio.to_thread(fishing_core.sell_fish_by_uid, self.guild_id, self.user.id, sel_uid)
            if ok:
                self.selected_uids = []
        else:
            ok, msg, _, _, skipped_locked_uids = await asyncio.to_thread(
                fishing_core.sell_fishes_by_uids, self.guild_id, self.user.id, target_uids, skip_locked=True
            )
            if ok:
                skipped_set = set(skipped_locked_uids or [])
                self.selected_uids = [uid for uid in self.selected_uids if uid in skipped_set]
        await self.reload()
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🐠 수족관전시", style=discord.ButtonStyle.primary, row=3)
    async def btn_to_tank(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        target_uids = list(self.selected_uids)
        if not target_uids:
            await interaction.followup.send("ℹ️ 먼저 전시할 물고기를 선택하세요.", ephemeral=True)
            return
        if len(target_uids) == 1:
            ok, msg = await asyncio.to_thread(fishing_core.move_fish_to_tank, self.guild_id, self.user.id, target_uids[0])
            if ok:
                self.selected_uids = []
        else:
            ok, msg, _, rem_uids = await asyncio.to_thread(
                fishing_core.move_fishes_to_tank, self.guild_id, self.user.id, target_uids
            )
            if ok:
                rem_set = set(rem_uids or [])
                self.selected_uids = [uid for uid in self.selected_uids if uid in rem_set]
        await self.reload()
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="💸 미잠금 전체판매", style=discord.ButtonStyle.danger, row=3)
    async def btn_sell_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg, _, _ = await asyncio.to_thread(
            fishing_core.sell_all_unlocked_bag,
            self.guild_id,
            self.user.id,
            self.habitat_filter,
            5,
        )
        await self.reload()
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🧹 ★1~2 판매", style=discord.ButtonStyle.secondary, row=4)
    async def btn_sell_low(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg, _, _ = await asyncio.to_thread(
            fishing_core.sell_bag_by_max_rarity,
            self.guild_id,
            self.user.id,
            2,
            self.habitat_filter,
        )
        await self.reload()
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="✨ 중복 정리", style=discord.ButtonStyle.secondary, row=4)
    async def btn_dedup_sell(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg, _, _ = await asyncio.to_thread(
            fishing_core.sell_bag_duplicates_keep_best,
            self.guild_id,
            self.user.id,
            self.habitat_filter,
        )
        await self.reload()
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🧪 미끼제작", style=discord.ButtonStyle.secondary, row=4)
    async def btn_quick_craft(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg, _ = await asyncio.to_thread(
            fishing_core.craft_bait_from_bag,
            self.guild_id,
            self.user.id,
            "live_minnow",
        )
        await self.reload()
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🎁 선택선물", style=discord.ButtonStyle.secondary, row=4)
    async def btn_gift_sel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        if len(self.selected_uids) != 1:
            await interaction.followup.send("ℹ️ 선물할 미잠금 물고기 **1마리**를 드롭다운에서 선택해 주세요!", ephemeral=True)
            return
        sel_uid = self.selected_uids[0]
        sel_item = next((x for x in self.summary["user"].get("bag", []) if isinstance(x, dict) and x.get("uid") == sel_uid), None)
        if not sel_item:
            await interaction.followup.send("⚠️ 선택한 물고기를 찾지 못했습니다.", ephemeral=True)
            return
        if sel_item.get("locked"):
            await interaction.followup.send("🔒 잠금 보호 중인 물고기입니다! 먼저 `[🔓 잠금해제]` 후 선물해 주세요.", ephemeral=True)
            return
        label = f"★{sel_item.get('rarity', 1)} {sel_item.get('name', '물고기')} ({float(sel_item.get('length_cm', 0)):.1f}cm)"
        gift_view = FishingGiftRecipientView(self.user, self.guild_id, fish_uid=sel_uid, fish_label=label)
        await interaction.followup.send(
            f"🎁 **{label}**을(를) 선물받을 멤버를 아래에서 선택해 주세요!",
            view=gift_view,
            ephemeral=True,
        )

    @discord.ui.button(label="📈 시세", style=discord.ButtonStyle.secondary, row=4)
    async def btn_open_market(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        mv = FishingMarketView(self.user, self.guild_id)
        msg = await interaction.followup.send(embed=mv.build_embed(), view=mv, ephemeral=True, wait=True)
        mv.message = msg



# ==========================================
# 3. 낚시 도감 (호수 · 강 · 바다 · 보유 · 미보유 + 검색 모달/정렬/성급/세부 수역 필터)
# ==========================================
class FishingPokedexSearchModal(core.SafeModal, title="🔍 글로벌 어종 도감 검색 & 페이지 이동"):
    keyword = discord.ui.TextInput(
        label="어종 검색어 (비워두면 검색 초기화)",
        placeholder="예: 참다랑어, 연어, medaka, Regalecus, 심해...",
        required=False,
        max_length=60,
    )
    page_jump = discord.ui.TextInput(
        label="바로 이동할 페이지 번호 (선택)",
        placeholder="숫자만 입력 (예: 15)",
        required=False,
        max_length=6,
    )

    def __init__(self, parent_view: "FishingPokedexView"):
        super().__init__()
        self.parent_view = parent_view
        if parent_view.search_query:
            self.keyword.default = parent_view.search_query

    async def on_submit(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        kw = (self.keyword.value or "").strip()
        pj = (self.page_jump.value or "").strip()

        if kw != self.parent_view.search_query:
            self.parent_view.search_query = kw
            self.parent_view.page = 0
            if kw and self.parent_view.tab in ("lake", "river", "sea"):
                # 현재 탭에 결과가 없으면 전체 DB 탭으로 자동 전환
                cur_hits = self.parent_view._get_list()
                if not cur_hits:
                    self.parent_view.tab = "all"
                    self.parent_view.zone_filter = "all"

        if pj.isdigit():
            target_p = max(1, int(pj)) - 1
            self.parent_view.page = target_p

        self.parent_view.sync_buttons()
        await _safe_update_message_or_interaction(
            interaction,
            interaction.message or self.parent_view.message,
            embed=self.parent_view.build_embed(),
            view=self.parent_view,
        )


class FishingPokedexRaritySelect(discord.ui.Select):
    def __init__(self, parent_view: "FishingPokedexView"):
        self.parent_view = parent_view
        super().__init__(
            placeholder="⭐ 희귀도(성급) 필터...",
            min_values=1,
            max_values=1,
            options=self._build_opts(),
            row=2,
            custom_id="norosi:FishingPokedexView:rarity_select",
        )

    def _build_opts(self) -> List[discord.SelectOption]:
        by_r = core.as_dict(self.parent_view.stats.get("by_rarity"))
        cur_r = self.parent_view.rarity_filter
        tot_owned = self.parent_view.stats.get("owned_total", 0)
        tot_all = self.parent_view.stats.get("total_species", len(fishing_core.FISH_SPECIES_DB))
        opts = [
            discord.SelectOption(
                label=f"전체 성급 ({tot_owned:,}/{tot_all:,}종)"[:95],
                value="0",
                emoji="📖",
                default=(cur_r == 0),
            )
        ]
        for r in range(1, 6):
            rm = fishing_core.RARITY_META[r]
            raw_r_stat = by_r.get(r) or by_r.get(str(r))
            r_stat = raw_r_stat if isinstance(raw_r_stat, dict) else {"owned": 0, "total": 0}
            opts.append(discord.SelectOption(
                label=f"★{r} {rm['name']} ({r_stat.get('owned', 0):,}/{r_stat.get('total', 0):,}종)"[:95],
                value=str(r),
                emoji=rm["emoji"],
                default=(cur_r == r),
            ))
        return opts

    def refresh(self):
        self.options = self._build_opts()

    async def callback(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        self.parent_view.rarity_filter = int(self.values[0])
        self.parent_view.page = 0
        self.parent_view.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.parent_view.build_embed(), view=self.parent_view)


class FishingPokedexZoneSelect(discord.ui.Select):
    def __init__(self, parent_view: "FishingPokedexView"):
        self.parent_view = parent_view
        super().__init__(
            placeholder="🧭 세부 수역 필터...",
            min_values=1,
            max_values=1,
            options=self._build_opts(),
            row=3,
            custom_id="norosi:FishingPokedexView:zone_select",
        )

    def _build_opts(self) -> List[discord.SelectOption]:
        tab = self.parent_view.tab
        cur_z = self.parent_view.zone_filter
        by_z = core.as_dict(self.parent_view.stats.get("by_zone"))
        opts = [
            discord.SelectOption(
                label="전체 세부 수역",
                value="all",
                emoji="🧭",
                default=(cur_z == "all"),
            )
        ]
        habs = [tab] if tab in ("lake", "river", "sea") else ["lake", "river", "sea"]
        for h_id in habs:
            h = fishing_core.HABITATS[h_id]
            h_zones = core.as_dict(by_z.get(h_id))
            for z in fishing_core.CANONICAL_ZONES[h_id]:
                raw_z_stat = h_zones.get(z)
                z_stat = raw_z_stat if isinstance(raw_z_stat, dict) else {"owned": 0, "total": len(fishing_core.FISH_BY_ZONE.get((h_id, z), []))}
                prefix = f"{h['name']}·" if len(habs) > 1 else ""
                opts.append(discord.SelectOption(
                    label=f"{prefix}{z} ({z_stat.get('owned', 0):,}/{z_stat.get('total', 0):,}종)"[:95],
                    value=z,
                    emoji=h["emoji"],
                    default=(cur_z == z),
                ))
        return opts[:25]

    def refresh(self):
        self.options = self._build_opts()

    async def callback(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        self.parent_view.zone_filter = self.values[0]
        self.parent_view.page = 0
        self.parent_view.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.parent_view.build_embed(), view=self.parent_view)


class FishingPokedexSortSelect(discord.ui.Select):
    def __init__(self, parent_view: "FishingPokedexView"):
        self.parent_view = parent_view
        super().__init__(
            placeholder="🔀 도감 정렬 기준...",
            min_values=1,
            max_values=1,
            options=self._build_opts(),
            row=4,
            custom_id="norosi:FishingPokedexView:sort_select",
        )

    def _build_opts(self) -> List[discord.SelectOption]:
        cur_s = self.parent_view.sort_mode
        choices = [
            ("owned_hangul", "📌 보유 어종 · 한글명 우선 (기본)", "📌"),
            ("rarity_desc", "⭐ 성급 높은순 (★5 → ★1)", "⭐"),
            ("size_desc", "📏 최대 체장(cm) 큰순", "📏"),
            ("rarity_asc", "🔤 성급 낮은순 (★1 → ★5)", "🔤"),
        ]
        return [
            discord.SelectOption(label=lbl, value=val, emoji=em, default=(cur_s == val))
            for val, lbl, em in choices
        ]

    def refresh(self):
        self.options = self._build_opts()

    async def callback(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        self.parent_view.sort_mode = self.values[0]
        self.parent_view.page = 0
        self.parent_view.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.parent_view.build_embed(), view=self.parent_view)


class FishingPokedexView(core.SafeView):
    def __init__(
        self,
        user: discord.abc.User,
        guild_id: int = 0,
        tab: str = "lake",
        rarity_filter: int = 0,
        zone_filter: str = "all",
        stats: Optional[Dict[str, Any]] = None,
        search_query: str = "",
        sort_mode: str = "owned_hangul",
    ):
        super().__init__(timeout=None)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.tab = tab  # lake, river, sea, owned, unowned, all
        self.rarity_filter = rarity_filter
        self.zone_filter = zone_filter
        self.search_query = (search_query or "").strip()
        self.sort_mode = sort_mode
        self.page = 0
        self.per_page = 10
        self.stats = stats or fishing_core.get_fishing_pokedex_stats(self.guild_id, user.id)
        self.rarity_select = FishingPokedexRaritySelect(self)
        self.zone_select = FishingPokedexZoneSelect(self)
        self.sort_select = FishingPokedexSortSelect(self)
        self.add_item(self.rarity_select)
        self.add_item(self.zone_select)
        self.add_item(self.sort_select)
        self.sync_buttons()

    def _restore_from_message(self, interaction: discord.Interaction):
        msg = getattr(interaction, "message", None)
        if not msg:
            return
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        tab_by_cid = {
            "btn_tab_lake": "lake",
            "btn_tab_river": "river",
            "btn_tab_sea": "sea",
            "btn_tab_owned": "owned",
            "btn_tab_unowned": "unowned",
        }
        for row in getattr(msg, "components", []) or []:
            for comp in getattr(row, "children", []):
                cid = getattr(comp, "custom_id", "") or ""
                for suffix, tab_name in tab_by_cid.items():
                    if cid.endswith(f":{suffix}") and getattr(comp, "style", None) == discord.ButtonStyle.primary:
                        self.tab = tab_name
                if cid == "norosi:FishingPokedexView:rarity_select":
                    for opt in getattr(comp, "options", []) or []:
                        if getattr(opt, "default", False) and getattr(opt, "value", None) is not None:
                            try:
                                self.rarity_filter = int(opt.value)
                            except Exception:
                                pass
                            break
                elif cid == "norosi:FishingPokedexView:zone_select":
                    for opt in getattr(comp, "options", []) or []:
                        if getattr(opt, "default", False) and getattr(opt, "value", None):
                            self.zone_filter = str(opt.value)
                            break
                elif cid == "norosi:FishingPokedexView:sort_select":
                    for opt in getattr(comp, "options", []) or []:
                        if getattr(opt, "default", False) and getattr(opt, "value", None):
                            self.sort_mode = str(opt.value)
                            break
        embeds = getattr(msg, "embeds", None) or []
        if embeds:
            if "전체 어종 검색" in (getattr(embeds[0], "title", "") or ""):
                self.tab = "all"
            if getattr(embeds[0], "description", None):
                import re as _re
                m = _re.search(r"페이지:\s*`?([\d,]+)\s*/\s*[\d,]+`?", embeds[0].description)
                if m:
                    self.page = max(0, int(m.group(1).replace(",", "")) - 1)
        self.sync_buttons()

    def _get_list(self) -> List[Dict[str, Any]]:
        pd = core.as_dict(self.stats.get("pokedex"))
        if self.tab == "owned":
            items = [sp for sp in fishing_core.FISH_SPECIES_DB if sp["id"] in pd]
        elif self.tab == "unowned":
            items = [sp for sp in fishing_core.FISH_SPECIES_DB if sp["id"] not in pd]
        elif self.tab == "all":
            items = list(fishing_core.FISH_SPECIES_DB)
        else:
            items = list(fishing_core.FISH_BY_HABITAT.get(self.tab, fishing_core.FISH_BY_HABITAT["lake"]))

        if self.rarity_filter > 0:
            items = [sp for sp in items if sp["rarity"] == self.rarity_filter]
        if self.zone_filter != "all":
            items = [sp for sp in items if sp.get("zone") == self.zone_filter]
        if self.search_query:
            q = self.search_query.lower()
            items = [
                sp for sp in items
                if q in sp["name"].lower()
                or q in sp.get("scientific_name", "").lower()
                or q in (sp.get("zone") or "").lower()
                or q in (sp.get("sub_zone") or "").lower()
                or q in sp.get("desc", "").lower()
            ]

        if self.sort_mode == "rarity_desc":
            items.sort(key=lambda x: (-x["rarity"], -x["max_cm"], x["name"]))
        elif self.sort_mode == "size_desc":
            items.sort(key=lambda x: (-x["max_cm"], -x["rarity"], x["name"]))
        elif self.sort_mode == "rarity_asc":
            items.sort(key=lambda x: (x["rarity"], x["min_cm"], x["name"]))
        else:
            # 기본(owned_hangul): 보유 어종 우선 → 한국어 공식 명칭 우선 → 성급 높은순
            items.sort(key=lambda x: (
                0 if x["id"] in pd else 1,
                0 if fishing_core._IS_HANGUL_SP_CACHE.get(x["id"], False) else 1,
                -x["rarity"],
                x["min_cm"],
                x["name"],
            ))
        return items

    def sync_buttons(self):
        items = self._get_list()
        total_p = max(1, math.ceil(len(items) / self.per_page))
        self.page = max(0, min(self.page, total_p - 1))
        self.btn_prev_10.disabled = (self.page <= 0)
        self.btn_prev.disabled = (self.page <= 0)
        self.btn_next.disabled = (self.page >= total_p - 1)
        self.btn_next_10.disabled = (self.page >= total_p - 1)

        self.btn_tab_lake.style = discord.ButtonStyle.primary if self.tab == "lake" else discord.ButtonStyle.secondary
        self.btn_tab_river.style = discord.ButtonStyle.primary if self.tab == "river" else discord.ButtonStyle.secondary
        self.btn_tab_sea.style = discord.ButtonStyle.primary if self.tab == "sea" else discord.ButtonStyle.secondary
        self.btn_tab_owned.style = discord.ButtonStyle.primary if self.tab == "owned" else discord.ButtonStyle.secondary
        self.btn_tab_unowned.style = discord.ButtonStyle.primary if self.tab == "unowned" else discord.ButtonStyle.secondary
        self.btn_search.style = discord.ButtonStyle.success if self.search_query else discord.ButtonStyle.secondary
        self.rarity_select.refresh()
        self.zone_select.refresh()
        self.sort_select.refresh()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 도감 패널만 조작할 수 있습니다.", ephemeral=True)
            return False
        if not self.user:
            self.user = interaction.user
        return True

    def build_embed(self) -> discord.Embed:
        self.stats = fishing_core.get_fishing_pokedex_stats(self.guild_id, self.user.id)
        pd = core.as_dict(self.stats.get("pokedex"))
        by_h = core.as_dict(self.stats.get("by_habitat"))
        items = self._get_list()
        total_p = max(1, math.ceil(len(items) / self.per_page))
        self.page = max(0, min(self.page, total_p - 1))
        page_items = items[self.page * self.per_page:(self.page + 1) * self.per_page]

        pct = (self.stats["owned_total"] / max(1, self.stats["total_species"])) * 100
        tab_title = {
            "lake": "🏞️ 호수 어종 도감",
            "river": "🌊 강 어종 도감",
            "sea": "⚓ 바다 어종 도감",
            "owned": "✅ 보유 어종 도감",
            "unowned": "🔒 미보유 어종 도감",
            "all": "🌐 전체 어종 검색 결과",
        }.get(self.tab, "📖 낚시 도감")

        lines = []
        for sp in page_items:
            raw_rec = pd.get(sp["id"])
            rec = raw_rec if isinstance(raw_rec, dict) else None
            rm = fishing_core.RARITY_META.get(int(sp.get("rarity", 1)), fishing_core.RARITY_META[1])
            z_lbl = sp.get("zone") or sp.get("sub_zone", "")
            hab_e = fishing_core.HABITATS.get(sp.get("habitat", "lake"), fishing_core.HABITATS["lake"])["emoji"]
            prefix_hab = f"{hab_e} " if self.tab in ("owned", "unowned", "all") else ""
            if rec:
                badges = ""
                if rec.get("max_crown"):
                    badges += "🏆"
                if rec.get("min_crown"):
                    badges += "🥈"
                for vk in (rec.get("variants") or []):
                    badges += fishing_core.get_variant_meta(vk)["emoji"]
                b_str = f" {badges}" if badges else ""
                lines.append(
                    f"✅ {rm['emoji']} {prefix_hab}**★{sp['rarity']} {sp['name']}**{b_str} (`{z_lbl}`) — "
                    f"최고 `{float(rec.get('max_cm', 0)):.1f}cm` · `{_format_weight(float(rec.get('max_kg', 0)))}` (`{int(rec.get('count', 1))}회`)"
                )
            else:
                time_hint = {"day": "☀️낮", "night": "🌙밤", "all": "⏰상시"}.get(sp.get("active_time", "all"), "⏰상시")
                w_hint = fishing_core.WEATHERS.get(sp.get("prefer_weather", "all"), {}).get("emoji", "🌤️")
                b_hint = fishing_core.BAITS.get(sp.get("prefer_bait", "dough"), {}).get("name", "기본 떡밥")
                lines.append(
                    f"⬜ {rm['emoji']} {prefix_hab}**★{sp['rarity']} {sp['name']}** (`{z_lbl}` · `{sp['min_cm']}~{sp['max_cm']}cm`) — "
                    f"{time_hint}·{w_hint}·`{b_hint}`"
                )

        if lines:
            body = "\n".join(lines)
        elif self.tab == "owned":
            body = "🎣 *아직 이 조건으로 포획한 어종이 없습니다! `/설정` (`🎮 미니게임` ➔ `🎣 세카이 낚시 출조`)로 물고기를 낚아 도감을 채워보세요.*"
        elif self.tab == "unowned" and self.rarity_filter == 0 and self.zone_filter == "all" and not self.search_query:
            body = "🎉 **축하합니다! 모든 어종을 도감에 수집했습니다!**"
        else:
            body = "ℹ️ *선택한 필터/검색어 조건에 해당하는 어종이 없습니다.*"

        r_label = "전체 성급" if self.rarity_filter == 0 else f"★{self.rarity_filter} {fishing_core.RARITY_META[self.rarity_filter]['name']}"
        z_label = "전체 수역" if self.zone_filter == "all" else self.zone_filter
        q_label = f" · 검색: `{self.search_query}`" if self.search_query else ""
        db_src = getattr(fishing_core, "FISH_DB_SOURCE", "unknown")
        db_badge = (
            f"🌐 글로벌 {self.stats['total_species']:,}종 DB 활성"
            if str(db_src).startswith("json:")
            else f"⚠️ 폴백 {self.stats['total_species']:,}종 모드 (`fish_species_db.json` 확인 필요)"
        )
        max_cr = int(self.stats.get("max_crowns", 0) or 0)
        min_cr = int(self.stats.get("min_crowns", 0) or 0)
        vc = core.as_dict(self.stats.get("variant_counts"))
        var_line = f"🏆 최대금관 `{max_cr}` · 🥈 최소은관 `{min_cr}` · ✨ 황금 `{vc.get('golden', 0)}` · ❄️ 알비노 `{vc.get('albino', 0)}` · 🌌 심해 `{vc.get('abyssal', 0)}`"

        embed = discord.Embed(
            title=f"📖 {self.user.display_name}님의 {tab_title}",
            description=(
                f"• **전체 수집률:** **`{self.stats['owned_total']:,}/{self.stats['total_species']:,}종 ({pct:.2f}%)`**  ·  {db_badge}\n"
                f"• 🏞️ 호수 `{by_h['lake']['owned']:,}/{by_h['lake']['total']:,}`  ·  "
                f"🌊 강 `{by_h['river']['owned']:,}/{by_h['river']['total']:,}`  ·  "
                f"⚓ 바다 `{by_h['sea']['owned']:,}/{by_h['sea']['total']:,}`\n"
                f"• **👑 금관 & 변이:** {var_line}\n"
                f"• **필터:** `{r_label}` · `{z_label}`{q_label} (`{len(items):,}종 일치`)  ·  **페이지:** `{self.page + 1:,} / {total_p:,}`\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{body}"
            )[:4096],
            color=0x0EA5E9,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="💡 [🔍 검색] 버튼으로 한글·영문·학명 검색 및 페이지 점프 · 🏆 최대금관 / 🥈 최소은관 / ✨❄️🌌 변이 기록 자동 누적!")
        return embed

    @discord.ui.button(label="🏞️ 호수", style=discord.ButtonStyle.primary, row=0)
    async def btn_tab_lake(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.tab = "lake"
        self.zone_filter = "all"
        self.page = 0
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🌊 강", style=discord.ButtonStyle.secondary, row=0)
    async def btn_tab_river(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.tab = "river"
        self.zone_filter = "all"
        self.page = 0
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="⚓ 바다", style=discord.ButtonStyle.secondary, row=0)
    async def btn_tab_sea(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.tab = "sea"
        self.zone_filter = "all"
        self.page = 0
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="✅ 보유", style=discord.ButtonStyle.secondary, row=0)
    async def btn_tab_owned(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.tab = "owned"
        self.zone_filter = "all"
        self.page = 0
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔒 미보유", style=discord.ButtonStyle.secondary, row=0)
    async def btn_tab_unowned(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.tab = "unowned"
        self.zone_filter = "all"
        self.page = 0
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="⏪ -10", style=discord.ButtonStyle.secondary, row=1)
    async def btn_prev_10(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.page = max(0, self.page - 10)
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary, row=1)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.page = max(0, self.page - 1)
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔍 검색", style=discord.ButtonStyle.secondary, row=1)
    async def btn_search(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.message = interaction.message or self.message
        await interaction.response.send_modal(FishingPokedexSearchModal(self))

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary, row=1)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.page += 1
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="+10 ⏩", style=discord.ButtonStyle.secondary, row=1)
    async def btn_next_10(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.page += 10
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)


# ==========================================
# 4. 개인 수족관 (PNG 수조 스냅샷 · 먹이주기 · 테마 · 패시브 골드 수확 · 회수)
# ==========================================
class TankWithdrawSelect(discord.ui.Select):
    def __init__(self, parent_view: "FishingAquariumView"):
        self.parent_view = parent_view
        super().__init__(
            placeholder="🐠 가방으로 꺼낼 어종 선택...",
            min_values=1,
            max_values=1,
            options=self._build_opts(),
            row=0,
            custom_id="norosi:FishingAquariumView:withdraw_select",
        )

    def _build_opts(self) -> List[discord.SelectOption]:
        raw_tank = self.parent_view.summary["user"].get("tank", [])
        tank = [it for it in (raw_tank if isinstance(raw_tank, list) else []) if isinstance(it, dict) and it.get("uid")]
        if not tank:
            return [discord.SelectOption(label="전시된 물고기가 없습니다", value="NONE")]
        opts = []
        seen = set()
        for it in tank[:25]:
            uid_s = str(it.get("uid") or "")[:100]
            if not uid_s or uid_s in seen:
                continue
            seen.add(uid_s)
            cm_val = float(it.get("length_cm", 0) or 0)
            wt_val = float(it.get("weight_kg", 0) or 0)
            r_val = int(it.get("rarity", 1) or 1)
            v_em = fishing_core.get_variant_meta(it.get("variant"))["emoji"]
            opts.append(
                discord.SelectOption(
                    label=f"{v_em}★{r_val} {it.get('name', '물고기')} ({cm_val:.1f}cm)"[:95],
                    value=uid_s,
                    description=f"{_format_weight(wt_val)} · 전시 중"[:95],
                )
            )
        return opts or [discord.SelectOption(label="전시된 물고기가 없습니다", value="NONE")]

    def refresh(self):
        opts = self._build_opts()
        self.options = opts
        self.disabled = (len(opts) == 1 and opts[0].value == "NONE") or (self.parent_view.caller.id != self.parent_view.target_user.id)

    async def callback(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        val = self.values[0]
        if val == "NONE":
            return
        ok, msg = await asyncio.to_thread(fishing_core.remove_fish_from_tank, self.parent_view.guild_id, self.parent_view.target_user.id, val)
        await self.parent_view.reload()
        self.parent_view.sync_controls()
        await self.parent_view.update_with_png(interaction, interaction.message)
        await interaction.followup.send(msg, ephemeral=True)


class TankThemeSelect(discord.ui.Select):
    def __init__(self, parent_view: "FishingAquariumView"):
        self.parent_view = parent_view
        super().__init__(
            placeholder="🎨 수족관 배경 테마 변경 / 구매...",
            min_values=1,
            max_values=1,
            options=self._build_opts(),
            row=2,
            custom_id="norosi:FishingAquariumView:theme_select",
        )

    def _build_opts(self) -> List[discord.SelectOption]:
        u = self.parent_view.summary["user"]
        owned = set(u.get("owned_tank_themes") or ["coral"])
        cur_t = str(u.get("tank_theme") or "coral")
        opts = []
        for t_id, t in fishing_core.TANK_THEMES.items():
            if t_id == cur_t:
                tag = " [적용중]"
            elif t_id in owned:
                tag = " [보유·적용]"
            else:
                tag = f" ({t['price']:,}🪙)"
            opts.append(discord.SelectOption(
                label=f"{t['name']}{tag}"[:95],
                value=t_id,
                emoji=t["emoji"],
                description=t["desc"][:95],
                default=(t_id == cur_t),
            ))
        return opts

    def refresh(self):
        self.options = self._build_opts()
        self.disabled = (self.parent_view.caller.id != self.parent_view.target_user.id)

    async def callback(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        t_id = self.values[0]
        ok, msg = await asyncio.to_thread(fishing_core.buy_or_equip_tank_theme, self.parent_view.guild_id, self.parent_view.target_user.id, t_id)
        await self.parent_view.reload()
        self.parent_view.sync_controls()
        await self.parent_view.update_with_png(interaction, interaction.message)
        await interaction.followup.send(msg, ephemeral=True)


class FishingAquariumView(core.SafeView):
    def __init__(
        self,
        caller: discord.abc.User,
        target_user: Optional[discord.abc.User] = None,
        guild_id: int = 0,
        summary: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(timeout=None)
        self.caller = caller
        self.target_user = target_user or caller
        self.guild_id = int(guild_id or 0)
        self.summary = summary or fishing_core.get_user_fishing_summary(self.guild_id, self.target_user.id, self.target_user.display_name)
        self.withdraw_select = TankWithdrawSelect(self)
        self.theme_select = TankThemeSelect(self)
        self.add_item(self.withdraw_select)
        self.add_item(self.theme_select)
        self.sync_controls()

    async def reload(self):
        self.summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary,
            self.guild_id,
            self.target_user.id,
            self.target_user.display_name,
        )

    def sync_controls(self):
        is_owner = (self.caller.id == self.target_user.id)
        self.withdraw_select.refresh()
        self.theme_select.refresh()
        self.btn_harvest.disabled = not is_owner
        self.btn_feed.disabled = not is_owner
        self.btn_expand.disabled = not is_owner or int(self.summary["user"].get("tank_slots", 4)) >= 20

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if self.caller and interaction.user.id != self.caller.id:
            await core.safe_send_response(interaction, "❌ 이 수족관 패널을 연 유저만 조작할 수 있습니다.", ephemeral=True)
            return False
        if not self.caller:
            self.caller = interaction.user
        return True

    async def _render_png_bytes(self) -> Optional[bytes]:
        buf = await asyncio.to_thread(
            fishing_core.build_aquarium_card_bytes,
            self.summary,
            self.target_user.display_name,
        )
        return buf.getvalue() if buf is not None else None

    async def send_initial(self, interaction: discord.Interaction, ephemeral: bool = False):
        png_bytes = await self._render_png_bytes()
        embed = self.build_embed(with_image=png_bytes is not None)
        if png_bytes is not None:
            return await interaction.followup.send(
                embed=embed,
                file=discord.File(fp=io.BytesIO(png_bytes), filename="aquarium.png"),
                view=self,
                ephemeral=ephemeral,
                wait=True,
            )
        return await interaction.followup.send(embed=embed, view=self, ephemeral=ephemeral, wait=True)

    async def update_with_png(self, interaction: discord.Interaction, message: Optional[discord.Message]):
        png_bytes = await self._render_png_bytes()
        embed = self.build_embed(with_image=png_bytes is not None)
        await _safe_update_message_or_interaction(
            interaction,
            message,
            embed=embed,
            view=self,
            png_bytes=png_bytes,
            png_filename="aquarium.png",
        )

    def build_embed(self, with_image: bool = False) -> discord.Embed:
        u = self.summary["user"]
        tank = [it for it in (u.get("tank", []) if isinstance(u.get("tank"), list) else []) if isinstance(it, dict)]
        max_slots = int(u.get("tank_slots", 4))
        pending = self.summary["tank_pending"]
        hourly = self.summary["tank_hourly"]
        theme = self.summary.get("tank_theme") or fishing_core.TANK_THEMES["coral"]
        feed_active = bool(self.summary.get("tank_feed_active", False))
        feed_rem_min = int(self.summary.get("tank_feed_rem_min", 0) or 0)
        feed_txt = f"🍖 **먹이 버프 활성 (+35% · `{feed_rem_min}분` 남음)**" if feed_active else f"🍖 미적용 *(`[🍖 먹이주기]` {fishing_core.TANK_FEED_COST}🪙 ➔ 4시간 +35% & 전시어 성장!)*"

        lines = []
        for idx, it in enumerate(tank, start=1):
            rm = fishing_core.RARITY_META.get(int(it.get("rarity", 1) or 1), fishing_core.RARITY_META[1])
            rate = rm["tank_rate"]
            if it.get("is_trophy"):
                rate = int(rate * 1.35)
            v_meta = fishing_core.get_variant_meta(it.get("variant"))
            if v_meta["tank_mult"] > 1.0:
                rate = int(rate * v_meta["tank_mult"])
            tr_s = "👑" if it.get("is_trophy") else ""
            v_s = v_meta["emoji"]
            cm_val = float(it.get("length_cm", 0) or 0)
            wt_val = float(it.get("weight_kg", 0) or 0)
            lines.append(
                f"`{idx}.` {it.get('emoji', '🐟')} {v_s}{tr_s}**★{it.get('rarity', 1)} {it.get('name', '물고기')}** — "
                f"`{cm_val:.1f}cm` · `{_format_weight(wt_val)}` (`+{rate}🪙/시간`)"
            )
        body = "\n".join(lines) if lines else "> *(아직 전시된 물고기가 없습니다! `/낚시 가방`에서 아끼는 대물을 수족관에 전시해 보세요.)*"
        next_cost = 600 + (max_slots - 4) * 500
        exp_txt = "최대 크기 달성!" if max_slots >= 20 else f"다음 확장(+2칸): `{next_cost:,}🪙`"

        emb = discord.Embed(
            title=f"🐠 {self.target_user.display_name}님의 프라이빗 수족관 ({len(tank)}/{max_slots}칸)",
            description=(
                f"• **수조 테마:** {theme['emoji']} **`{theme['name']}`**  ·  **어항 크기:** `{max_slots}/20칸` ({exp_txt})\n"
                f"• **시간당 관람 수익:** **`+{hourly:,}🪙/시간`**  ·  **수확 대기 골드:** **`+{pending:,}🪙`** *(최대 24시간)*\n"
                f"• **먹이 상태:** {feed_txt}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{body}"
            )[:4096],
            color=0x14B8A6,
            timestamp=datetime.datetime.now(core.KST),
        )
        if with_image:
            emb.set_image(url="attachment://aquarium.png")
        emb.set_footer(text="💡 하단 드롭다운으로 수조 테마를 꾸미고, [🍖 먹이주기]로 전시어를 키우며 수익 +35% 버프를 받으세요!")
        return emb

    @discord.ui.button(label="🪙 수익 수확", style=discord.ButtonStyle.success, row=1)
    async def btn_harvest(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg, _ = await asyncio.to_thread(fishing_core.harvest_tank_gold, self.guild_id, self.target_user.id)
        await self.reload()
        self.sync_controls()
        await self.update_with_png(interaction, interaction.message)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🍖 먹이주기", style=discord.ButtonStyle.primary, row=1)
    async def btn_feed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg, _ = await asyncio.to_thread(fishing_core.feed_aquarium_fish, self.guild_id, self.target_user.id)
        await self.reload()
        self.sync_controls()
        await self.update_with_png(interaction, interaction.message)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🏗️ +2칸 확장", style=discord.ButtonStyle.secondary, row=1)
    async def btn_expand(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(fishing_core.purchase_shop_item, self.guild_id, self.target_user.id, "tank_expand", "expand")
        await self.reload()
        self.sync_controls()
        await self.update_with_png(interaction, interaction.message)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="👜 가방", style=discord.ButtonStyle.secondary, row=1)
    async def btn_open_bag(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        gid = self.guild_id or (interaction.guild_id or 0)
        summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary, gid, interaction.user.id, interaction.user.display_name
        )
        bag_view = FishingBagView(interaction.user, gid, summary=summary)
        await interaction.followup.send(embed=bag_view.build_embed(), view=bag_view, wait=True)

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=1)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        await self.reload()
        self.sync_controls()
        await self.update_with_png(interaction, interaction.message)


# ==========================================
# 5. 낚시 장비 · 미끼 상점 & 강화/미끼제작 공방 View
# ==========================================
class FishingShopSelect(discord.ui.Select):
    def __init__(self, parent_view: "FishingShopView"):
        self.parent_view = parent_view
        super().__init__(
            placeholder="🛒 구매 · 강화 · 제작할 항목 선택...",
            min_values=1,
            max_values=1,
            options=self._build_opts(),
            row=0,
            custom_id="norosi:FishingShopView:shop_select",
        )

    def _build_opts(self) -> List[discord.SelectOption]:
        cat = self.parent_view.category
        u = self.parent_view.summary["user"]
        opts = []
        if cat == "rod":
            for r_id, r in fishing_core.RODS.items():
                owned = r_id in u["owned_rods"]
                equipped = (u["rod_id"] == r_id)
                tag = " [장착중]" if equipped else (" [보유·장착]" if owned else f" ({r['price']:,}🪙)")
                opts.append(discord.SelectOption(
                    label=f"{r['name']}{tag}"[:95],
                    value=f"rod:{r_id}",
                    description=r["desc"][:95],
                    emoji=r["emoji"],
                ))
        elif cat == "reel":
            for rl_id, rl in fishing_core.REELS.items():
                owned = rl_id in u["owned_reels"]
                equipped = (u["reel_id"] == rl_id)
                tag = " [장착중]" if equipped else (" [보유·장착]" if owned else f" ({rl['price']:,}🪙)")
                opts.append(discord.SelectOption(
                    label=f"{rl['name']}{tag}"[:95],
                    value=f"reel:{rl_id}",
                    description=rl["desc"][:95],
                    emoji=rl["emoji"],
                ))
        elif cat == "net":
            owned_nets = set(u.get("owned_nets") or [])
            cur_net_id = u.get("net_id")
            if cur_net_id:
                opts.append(discord.SelectOption(
                    label="그물 장착 해제 (기본 1마리 낚시)",
                    value="net:none",
                    description="그물을 벗고 1회 1마리 정밀 낚시로 전환합니다.",
                    emoji="🚫",
                ))
            for n_id, nt in fishing_core.NETS.items():
                owned = n_id in owned_nets
                equipped = (cur_net_id == n_id)
                tag = " [장착중]" if equipped else (" [보유·장착]" if owned else f" ({nt['price']:,}🪙)")
                opts.append(discord.SelectOption(
                    label=f"{nt['name']}{tag}"[:95],
                    value=f"net:{n_id}",
                    description=nt["desc"][:95],
                    emoji=nt["emoji"],
                ))
        elif cat == "bait":
            for b_id, b in fishing_core.BAITS.items():
                if b.get("unlimited") or b.get("craft_only"):
                    continue
                cnt = int(core.as_dict(u.get("baits")).get(b_id, 0))
                opts.append(discord.SelectOption(
                    label=f"{b['name']} ×{b['pack_qty']}개 ({b['price_per_pack']:,}🪙 | 보유 {cnt})"[:95],
                    value=f"bait:{b_id}",
                    description=b["desc"][:95],
                    emoji=b["emoji"],
                ))
        elif cat == "bag_expand":
            cur_cap = fishing_core.get_bag_capacity(u)
            nxt = fishing_core.get_next_bag_upgrade(u)
            for start_cap, step in fishing_core.BAG_UPGRADE_STEPS.items():
                nc = int(step["next_cap"])
                price = int(step["price"])
                if cur_cap >= nc:
                    tag = " [✅ 보유중]"
                elif nxt and int(nxt["next_cap"]) == nc:
                    tag = f" ({price:,}🪙 · 구매가능)"
                else:
                    tag = f" ({price:,}🪙 · 🔒 순차해금)"
                opts.append(discord.SelectOption(
                    label=f"{step['tier_name']} ({start_cap:,}→{nc:,}칸){tag}"[:95],
                    value=f"bag_expand:{nc}",
                    description=f"최대 가방 한도 {nc:,}마리 확장 (비용 {price:,}🪙 · 단계별 순차 업그레이드)"[:95],
                    emoji=step["emoji"],
                ))
        elif cat == "enhance":
            lvls = fishing_core.get_gear_enhance_levels(u)
            pity_map = core.as_dict(u.get("enhance_pity"))
            for slot in ("rod", "reel", "net"):
                meta = fishing_core.ENHANCE_SLOT_META[slot]
                cur_lv = lvls[slot]
                step = fishing_core.get_gear_enhance_step(cur_lv)
                if step:
                    pity = int(pity_map.get(slot, 0) or 0)
                    rate_pct = int(round(min(1.0, float(step["rate"]) + pity * 0.08) * 100))
                    lbl = f"{meta['name']} +{cur_lv} → +{cur_lv + 1} ({step['cost']:,}🪙 · 성공 {rate_pct}%)"
                else:
                    lbl = f"{meta['name']} +{cur_lv} [🏆 MAX 강화 완료]"
                opts.append(discord.SelectOption(
                    label=lbl[:95],
                    value=f"enhance:{slot}",
                    description=meta["effect"][:95],
                    emoji=meta["emoji"],
                ))
        elif cat == "craft":
            bag = [it for it in (u.get("bag") or []) if isinstance(it, dict)]
            small_cnt = sum(1 for it in bag if not it.get("locked") and int(it.get("rarity", 1) or 1) <= 2)
            for r_id, rec in fishing_core.BAIT_CRAFT_RECIPES.items():
                need = int(rec["need_fish"])
                ok_tag = f" [재료 {small_cnt}/{need} ✅]" if small_cnt >= need else f" [재료 {small_cnt}/{need} 부족]"
                opts.append(discord.SelectOption(
                    label=f"{rec['name']}{ok_tag}"[:95],
                    value=f"craft:{r_id}",
                    description=rec["desc"][:95],
                    emoji=rec["emoji"],
                ))
        elif cat == "tank_theme":
            owned_t = set(u.get("owned_tank_themes") or ["coral"])
            cur_t = str(u.get("tank_theme") or "coral")
            for t_id, t in fishing_core.TANK_THEMES.items():
                tag = " [적용중]" if t_id == cur_t else (" [보유·적용]" if t_id in owned_t else f" ({t['price']:,}🪙)")
                opts.append(discord.SelectOption(
                    label=f"{t['name']}{tag}"[:95],
                    value=f"tank_theme:{t_id}",
                    description=t["desc"][:95],
                    emoji=t["emoji"],
                ))
        else:
            cur_slots = int(u.get("tank_slots", 4))
            cost = 600 + (cur_slots - 4) * 500
            lbl = "수족관 최대 크기(20칸) 도달!" if cur_slots >= 20 else f"수족관 +2칸 확장 ({cur_slots}→{cur_slots+2}칸 / {cost:,}🪙)"
            opts.append(discord.SelectOption(label=lbl, value="tank_expand:expand", description="수족관 전시 칸을 2칸 늘려 패시브 골드를 극대화합니다.", emoji="🐠"))
        return opts[:25]

    def refresh(self):
        self.options = self._build_opts()

    async def callback(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        raw = self.values[0]
        cat, item_id = raw.split(":", 1)
        ok, msg = await asyncio.to_thread(fishing_core.purchase_shop_item, self.parent_view.guild_id, self.parent_view.user.id, cat, item_id)
        await self.parent_view.reload()
        self.parent_view.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.parent_view.build_embed(), view=self.parent_view)
        await interaction.followup.send(msg, ephemeral=True)


class FishingShopView(core.SafeView):
    def __init__(
        self,
        user: discord.abc.User,
        guild_id: int = 0,
        category: str = "rod",
        summary: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(timeout=None)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.category = category
        self.summary = summary or fishing_core.get_user_fishing_summary(self.guild_id, user.id, user.display_name)
        self.shop_select = FishingShopSelect(self)
        self.add_item(self.shop_select)
        self.sync_controls()

    def _restore_from_message(self, interaction: discord.Interaction):
        msg = getattr(interaction, "message", None)
        if not msg:
            return
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        cat_by_cid = {
            "btn_cat_rod": "rod",
            "btn_cat_reel": "reel",
            "btn_cat_net": "net",
            "btn_cat_bait": "bait",
            "btn_cat_tank": "tank_expand",
            "btn_cat_bag": "bag_expand",
            "btn_cat_enhance": "enhance",
            "btn_cat_craft": "craft",
            "btn_cat_theme": "tank_theme",
        }
        for row in getattr(msg, "components", []) or []:
            for comp in getattr(row, "children", []):
                cid = getattr(comp, "custom_id", "") or ""
                for suffix, cat_name in cat_by_cid.items():
                    if cid.endswith(f":{suffix}") and getattr(comp, "style", None) == discord.ButtonStyle.primary:
                        self.category = cat_name
                        break
        self.sync_controls()

    async def reload(self):
        self.summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary,
            self.guild_id,
            self.user.id,
            self.user.display_name,
        )

    def sync_controls(self):
        self.shop_select.refresh()
        self.btn_cat_rod.style = discord.ButtonStyle.primary if self.category == "rod" else discord.ButtonStyle.secondary
        self.btn_cat_reel.style = discord.ButtonStyle.primary if self.category == "reel" else discord.ButtonStyle.secondary
        self.btn_cat_net.style = discord.ButtonStyle.primary if self.category == "net" else discord.ButtonStyle.secondary
        self.btn_cat_bait.style = discord.ButtonStyle.primary if self.category == "bait" else discord.ButtonStyle.secondary
        self.btn_cat_tank.style = discord.ButtonStyle.primary if self.category == "tank_expand" else discord.ButtonStyle.secondary
        self.btn_cat_bag.style = discord.ButtonStyle.primary if self.category == "bag_expand" else discord.ButtonStyle.secondary
        self.btn_cat_enhance.style = discord.ButtonStyle.primary if self.category == "enhance" else discord.ButtonStyle.secondary
        self.btn_cat_craft.style = discord.ButtonStyle.primary if self.category == "craft" else discord.ButtonStyle.secondary
        self.btn_cat_theme.style = discord.ButtonStyle.primary if self.category == "tank_theme" else discord.ButtonStyle.secondary

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 상점 패널만 조작할 수 있습니다.", ephemeral=True)
            return False
        if not self.user:
            self.user = interaction.user
        return True

    def build_embed(self) -> discord.Embed:
        u = self.summary["user"]
        lines = []
        if self.category == "rod":
            title = "🎣 낚시 상점 — 낚싯대(Rod) 업그레이드"
            for r_id, r in fishing_core.RODS.items():
                st = "✅ 장착중" if u["rod_id"] == r_id else ("🎒 보유중" if r_id in u["owned_rods"] else f"`{r['price']:,}🪙`")
                lines.append(f"{r['emoji']} **{r['name']}** [{st}]\n> {r['desc']}")
        elif self.category == "reel":
            title = "🌀 낚시 상점 — 릴(Reel) 업그레이드"
            for rl_id, rl in fishing_core.REELS.items():
                st = "✅ 장착중" if u["reel_id"] == rl_id else ("🎒 보유중" if rl_id in u["owned_reels"] else f"`{rl['price']:,}🪙`")
                lines.append(f"{rl['emoji']} **{rl['name']}** [{st}]\n> {rl['desc']}")
        elif self.category == "net":
            title = "🕸️ 낚시 상점 — 그물(Net · 1회 2~10마리 포획)"
            owned_nets = set(u.get("owned_nets") or [])
            cur_net_id = u.get("net_id")
            cur_net = fishing_core.NETS.get(cur_net_id)
            cur_net_txt = f"{cur_net['emoji']} `{cur_net['name']}` (`{cur_net['min_catch']}~{cur_net['max_catch']}마리`)" if cur_net else "🚫 `미장착 (1마리 정밀 낚시)`"
            lines.append(f"• **현재 장착 그물:** {cur_net_txt} *(낚싯대와 별도 장착 가능 · 초기 구매 필요)*\n")
            for n_id, nt in fishing_core.NETS.items():
                st = "✅ 장착중" if cur_net_id == n_id else ("🎒 보유중" if n_id in owned_nets else f"`{nt['price']:,}🪙`")
                lines.append(f"{nt['emoji']} **{nt['name']}** (`{nt['min_catch']}~{nt['max_catch']}마리`) [{st}]\n> {nt['desc']}")
        elif self.category == "bait":
            title = "🪱 낚시 상점 — 특급 미끼 판매"
            for b_id, b in fishing_core.BAITS.items():
                if b.get("unlimited") or b.get("craft_only"):
                    continue
                cnt = int(core.as_dict(u.get("baits")).get(b_id, 0))
                lines.append(f"{b['emoji']} **{b['name']} ×{b['pack_qty']}개** (`{b['price_per_pack']:,}🪙` · 보유 `{cnt}개`)\n> {b['desc']}")
        elif self.category == "bag_expand":
            title = "🎒 낚시 상점 — 낚시 가방 용량 확장"
            cur_cap = fishing_core.get_bag_capacity(u)
            bag_len = len(u.get("bag", []) if isinstance(u.get("bag"), list) else [])
            nxt = fishing_core.get_next_bag_upgrade(u)
            lines.append(
                f"• **현재 가방 한도:** `{bag_len:,} / {cur_cap:,}마리` "
                f"*(기본 `180칸` → 최대 `2,000칸` · 단계별 순차 업그레이드)*\n"
            )
            for start_cap, step in fishing_core.BAG_UPGRADE_STEPS.items():
                nc = int(step["next_cap"])
                price = int(step["price"])
                if cur_cap >= nc:
                    st = "✅ 확장 완료"
                elif nxt and int(nxt["next_cap"]) == nc:
                    st = f"🛒 **`{price:,}🪙`** (구매 가능)"
                else:
                    st = f"🔒 `{price:,}🪙` (이전 단계 필요)"
                lines.append(
                    f"{step['emoji']} **{step['tier_name']} (`{start_cap:,} → {nc:,}칸`)** [{st}]"
                )
        elif self.category == "enhance":
            title = "🔨 낚시 공방 — 장비 강화 (+1 ~ +10 · 파괴/하락 없음!)"
            lvls = fishing_core.get_gear_enhance_levels(u)
            pity_map = core.as_dict(u.get("enhance_pity"))
            lines.append("• *강화 단계는 부위별로 영구 보존되며, 실패해도 하락/파괴 없이 다음 성공률 +8% 천장 보정이 누적됩니다!*\n")
            for slot in ("rod", "reel", "net"):
                meta = fishing_core.ENHANCE_SLOT_META[slot]
                cur_lv = lvls[slot]
                step = fishing_core.get_gear_enhance_step(cur_lv)
                if step:
                    pity = int(pity_map.get(slot, 0) or 0)
                    rate_pct = int(round(min(1.0, float(step["rate"]) + pity * 0.08) * 100))
                    pity_txt = f" (천장 +{pity * 8}%)" if pity > 0 else ""
                    lines.append(
                        f"{meta['emoji']} **{meta['name']} 강화 `+{cur_lv} → +{cur_lv + 1}`** — 비용 `{step['cost']:,}🪙` · 성공률 **`{rate_pct}%`**{pity_txt}\n"
                        f"> {meta['effect']}"
                    )
                else:
                    lines.append(f"{meta['emoji']} **{meta['name']} `+{cur_lv}`** [🏆 최고 강화 달성!]\n> {meta['effect']}")
        elif self.category == "craft":
            title = "🧪 낚시 공방 — 소형어(★1~2) 분해 특제 미끼 제작"
            bag = [it for it in (u.get("bag") or []) if isinstance(it, dict)]
            small_cnt = sum(1 for it in bag if not it.get("locked") and int(it.get("rarity", 1) or 1) <= 2)
            lines.append(f"• **현재 분해 가능 소형어(미잠금 ★1~★2):** **`{small_cnt}마리`** *(잠긴 물고기는 절대 건드리지 않습니다!)*\n")
            for r_id, rec in fishing_core.BAIT_CRAFT_RECIPES.items():
                yb = fishing_core.BAITS[rec["yield_bait"]]
                owned_q = int(core.as_dict(u.get("baits")).get(rec["yield_bait"], 0))
                lines.append(
                    f"{rec['emoji']} **{rec['name']}** (보유 `{owned_q}개` · 희귀 `×{yb['rare_mult']:.2f}`)\n"
                    f"> {rec['desc']}"
                )
        elif self.category == "tank_theme":
            title = "🎨 낚시 상점 — 프라이빗 수족관 PNG 배경 테마"
            owned_t = set(u.get("owned_tank_themes") or ["coral"])
            cur_t = str(u.get("tank_theme") or "coral")
            for t_id, t in fishing_core.TANK_THEMES.items():
                st = "✅ 적용중" if t_id == cur_t else ("🎒 보유중" if t_id in owned_t else f"`{t['price']:,}🪙`")
                lines.append(f"{t['emoji']} **{t['name']}** [{st}]\n> {t['desc']}")
        else:
            title = "🐠 낚시 상점 — 수족관 슬롯 확장"
            cur_slots = int(u.get("tank_slots", 4))
            cost = 600 + (cur_slots - 4) * 500
            lines.append(f"• **현재 수족관 크기:** `{cur_slots} / 20칸`")
            lines.append(f"• **확장 비용 (+2칸):** `{cost:,}🪙`" if cur_slots < 20 else "• 🏆 최대 크기 확장 완료!")

        return discord.Embed(
            title=title,
            description=(
                f"🪙 **보유 낚시 골드:** **`{u['gold']:,}🪙`**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(lines)
            )[:4096],
            color=0xF59E0B,
            timestamp=datetime.datetime.now(core.KST),
        )

    @discord.ui.button(label="🎣 낚싯대", style=discord.ButtonStyle.primary, row=1)
    async def btn_cat_rod(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.category = "rod"
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🌀 릴", style=discord.ButtonStyle.secondary, row=1)
    async def btn_cat_reel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.category = "reel"
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🕸️ 그물", style=discord.ButtonStyle.secondary, row=1)
    async def btn_cat_net(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.category = "net"
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🪱 미끼", style=discord.ButtonStyle.secondary, row=1)
    async def btn_cat_bait(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.category = "bait"
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🐠 수족관확장", style=discord.ButtonStyle.secondary, row=1)
    async def btn_cat_tank(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.category = "tank_expand"
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🎒 가방확장", style=discord.ButtonStyle.secondary, row=2)
    async def btn_cat_bag(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.category = "bag_expand"
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔨 장비강화", style=discord.ButtonStyle.secondary, row=2)
    async def btn_cat_enhance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.category = "enhance"
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🧪 미끼제작", style=discord.ButtonStyle.secondary, row=2)
    async def btn_cat_craft(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.category = "craft"
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🎨 수조테마", style=discord.ButtonStyle.secondary, row=2)
    async def btn_cat_theme(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.category = "tank_theme"
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="📈 어시장시세", style=discord.ButtonStyle.success, row=2)
    async def btn_cat_market(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        mv = FishingMarketView(self.user, self.guild_id)
        msg = await interaction.followup.send(embed=mv.build_embed(), view=mv, ephemeral=True, wait=True)
        mv.message = msg



# ==========================================
# 6. 서버 최대어 (cm · kg) & 도감 랭킹 View
# ==========================================
class FishingRankerSelect(discord.ui.Select):
    def __init__(self, parent_view: "FishingRankingView"):
        self.parent_view = parent_view
        super().__init__(
            placeholder="👤 랭커 상세 정보 & 보유 신기록 조회...",
            min_values=1,
            max_values=1,
            options=self._build_opts(),
            row=1,
            custom_id="norosi:FishingRankingView:ranker_select",
        )

    def _build_opts(self) -> List[discord.SelectOption]:
        lb = self.parent_view.get_leaderboard()
        seen: Dict[str, Dict[str, Any]] = {}
        profiles = core.as_dict(lb.get("ranker_profiles"))
        all_recs = (
            (lb.get("length_top") if isinstance(lb.get("length_top"), list) else [])
            + (lb.get("weight_top") if isinstance(lb.get("weight_top"), list) else [])
            + (lb.get("dex_top") if isinstance(lb.get("dex_top"), list) else [])
        )
        for rec in all_recs:
            if not isinstance(rec, dict):
                continue
            uid_s = str(rec.get("user_id") or "")
            if not uid_s or uid_s in seen:
                continue
            prof = core.as_dict(profiles.get(uid_s))
            seen[uid_s] = {
                "user_id": uid_s,
                "user_name": rec.get("user_name") or prof.get("user_name") or f"User({uid_s[:4]})",
                "level": prof.get("level", 1),
                "rec_cnt": prof.get("len_records_held", 0) + prof.get("wt_records_held", 0),
                "pokedex_cnt": prof.get("pokedex_cnt", 0),
            }

        opts = [
            discord.SelectOption(
                label="🏆 전체 서버 대물 순위표 보기",
                value="OVERVIEW",
                description="길이(cm)·무게(kg)·도감 순위 보드로 돌아갑니다",
                default=(self.parent_view.selected_ranker_id is None),
            )
        ]
        for uid_s, info in list(seen.items())[:24]:
            opts.append(
                discord.SelectOption(
                    label=f"👤 {info['user_name']} (Lv.{info['level']})"[:95],
                    value=uid_s,
                    description=f"서버 신기록 {info['rec_cnt']}개 · 도감 {info['pokedex_cnt']}종"[:95],
                    default=(self.parent_view.selected_ranker_id == uid_s),
                )
            )
        return opts[:25]

    def refresh(self):
        opts = self._build_opts()
        self.options = opts
        self.disabled = len(opts) <= 1

    async def callback(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        val = self.values[0]
        self.parent_view.selected_ranker_id = None if val == "OVERVIEW" else val
        self.parent_view.sync_buttons()
        await _safe_update_message_or_interaction(
            interaction,
            interaction.message,
            embed=self.parent_view.build_embed(),
            view=self.parent_view,
        )


class FishingRankingView(core.SafeView):
    def __init__(
        self,
        user: discord.abc.User,
        guild_id: int = 0,
        mode: str = "length",
        habitat_filter: str = "all",
        search_query: str = "",
        selected_ranker_id: Optional[str] = None,
    ):
        super().__init__(timeout=None)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.mode = mode  # length, weight, dex
        self.habitat_filter = habitat_filter
        self.search_query = (search_query or "").strip()
        self.selected_ranker_id = str(selected_ranker_id) if selected_ranker_id else None
        self.ranker_select = FishingRankerSelect(self)
        self.add_item(self.ranker_select)
        self.sync_buttons()

    def _restore_from_message(self, interaction: discord.Interaction):
        msg = getattr(interaction, "message", None)
        if not msg:
            return
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        for row in getattr(msg, "components", []) or []:
            for comp in getattr(row, "children", []):
                cid = getattr(comp, "custom_id", "") or ""
                if cid.endswith(":btn_len") and getattr(comp, "style", None) == discord.ButtonStyle.primary:
                    self.mode = "length"
                elif cid.endswith(":btn_wt") and getattr(comp, "style", None) == discord.ButtonStyle.primary:
                    self.mode = "weight"
                elif cid.endswith(":btn_dex") and getattr(comp, "style", None) == discord.ButtonStyle.primary:
                    self.mode = "dex"
                elif cid.endswith(":btn_hab"):
                    lbl = getattr(comp, "label", "") or ""
                    if "호수" in lbl:
                        self.habitat_filter = "lake"
                    elif "강" in lbl:
                        self.habitat_filter = "river"
                    elif "바다" in lbl:
                        self.habitat_filter = "sea"
                    else:
                        self.habitat_filter = "all"
                elif cid == "norosi:FishingRankingView:ranker_select":
                    for opt in getattr(comp, "options", []) or []:
                        if getattr(opt, "default", False) and getattr(opt, "value", None):
                            self.selected_ranker_id = None if opt.value == "OVERVIEW" else str(opt.value)
                            break
        self.sync_buttons()

    def get_leaderboard(self) -> Dict[str, Any]:
        return fishing_core.get_fishing_leaderboard(self.guild_id, self.habitat_filter)

    def sync_buttons(self):
        self.btn_len.style = discord.ButtonStyle.primary if (self.mode == "length" and not self.selected_ranker_id) else discord.ButtonStyle.secondary
        self.btn_wt.style = discord.ButtonStyle.primary if (self.mode == "weight" and not self.selected_ranker_id) else discord.ButtonStyle.secondary
        self.btn_dex.style = discord.ButtonStyle.primary if (self.mode == "dex" and not self.selected_ranker_id) else discord.ButtonStyle.secondary
        hab_lbl = {"all": "전체장소", "lake": "🏞️ 호수", "river": "🌊 강", "sea": "⚓ 바다"}.get(self.habitat_filter, "전체장소")
        self.btn_hab.label = f"📍 {hab_lbl}"
        self.ranker_select.refresh()

    def _matches_query(self, rec: Dict[str, Any]) -> bool:
        if not self.search_query:
            return True
        q = self.search_query.lower()
        return (
            q in str(rec.get("name", "")).lower()
            or q in str(rec.get("scientific_name", "")).lower()
            or q in str(rec.get("user_name", "")).lower()
            or q in str(rec.get("fish_id", "")).lower()
        )

    def build_embed(self) -> discord.Embed:
        lb = self.get_leaderboard()
        medals = ["🥇", "🥈", "🥉"]

        if self.selected_ranker_id:
            prof = core.as_dict(core.as_dict(lb.get("ranker_profiles")).get(self.selected_ranker_id)) or None
            len_recs = [r for r in (lb.get("length_top") or []) if isinstance(r, dict) and str(r.get("user_id") or "") == self.selected_ranker_id]
            wt_recs = [r for r in (lb.get("weight_top") or []) if isinstance(r, dict) and str(r.get("user_id") or "") == self.selected_ranker_id]
            disp_name = (
                (prof or {}).get("user_name")
                or (len_recs[0]["user_name"] if len_recs else None)
                or (wt_recs[0]["user_name"] if wt_recs else "낚시꾼")
            )
            tot = lb["total_species_count"]
            pd_cnt = (prof or {}).get("pokedex_cnt", 0)
            pct = (pd_cnt / max(1, tot)) * 100
            desc_parts = []
            if prof:
                net_badge = f"  ·  {prof.get('net_emoji', '🚫')} `{prof.get('net_name', '미장착')}`"
                desc_parts.append(
                    f"• **레벨:** `Lv.{prof['level']}`  ·  **누적 포획:** `{prof['total_catches']:,}마리` (👑 월척 `{prof['total_trophy']:,}회`)\n"
                    f"• **장착 장비:** {prof['rod_emoji']} `{prof['rod_name']}`  ·  {prof['reel_emoji']} `{prof['reel_name']}`{net_badge}\n"
                    f"• **어종 도감:** `{pd_cnt}/{tot}종 ({pct:.1f}%)`  ·  **수족관:** `{prof['tank_cnt']}칸`  ·  **보유 골드:** `{prof['gold']:,}🪙`"
                )
            desc_parts.append("\n**📏 보유 중인 서버 최대 길이(cm) 어종 1위 기록**")
            if len_recs:
                for rec in len_recs[:8]:
                    he = fishing_core.HABITATS.get(rec.get("habitat", "lake"), fishing_core.HABITATS["lake"])["emoji"]
                    tr = " 👑월척" if rec.get("is_trophy") else ""
                    desc_parts.append(
                        f"• {he} ★{rec.get('rarity', 1)} **{rec.get('name', '물고기')}** — **`{float(rec.get('val', 0)):.1f} cm`**{tr} *({rec.get('at', '')})*"
                    )
            else:
                desc_parts.append("> *(현재 보유 중인 길이 1위 신기록이 없습니다.)*")

            desc_parts.append("\n**⚖️ 보유 중인 서버 최대 무게(kg) 어종 1위 기록**")
            if wt_recs:
                for rec in wt_recs[:8]:
                    he = fishing_core.HABITATS.get(rec.get("habitat", "lake"), fishing_core.HABITATS["lake"])["emoji"]
                    desc_parts.append(
                        f"• {he} ★{rec.get('rarity', 1)} **{rec.get('name', '물고기')}** — **`{_format_weight(float(rec.get('val', 0)))}`** *({rec.get('at', '')})*"
                    )
            else:
                desc_parts.append("> *(현재 보유 중인 무게 1위 신기록이 없습니다.)*")

            embed = discord.Embed(
                title=f"👤 서버 낚시 랭커 상세 정보 — {disp_name}",
                description="\n".join(desc_parts)[:4096],
                color=0x0EA5E9,
                timestamp=datetime.datetime.now(core.KST),
            )
            embed.set_footer(text="상단 드롭다운에서 '전체 서버 대물 순위표 보기'를 고르거나 탭 버튼을 눌러 순위표로 돌아가세요.")
            return embed

        lines = []
        q_suffix = f" · 검색: `{self.search_query}`" if self.search_query else ""
        if self.mode == "length":
            title = f"📏 서버 최대 길이(cm) 대물 랭킹 TOP 12{q_suffix}"
            filtered = [r for r in lb["length_top"] if self._matches_query(r)]
            for i, rec in enumerate(filtered[:12]):
                m = medals[i] if i < 3 else f"`{i+1}.`"
                he = fishing_core.HABITATS.get(rec.get("habitat", "lake"), fishing_core.HABITATS["lake"])["emoji"]
                tr = " 👑" if rec.get("is_trophy") else ""
                lines.append(
                    f"{m} **`{float(rec.get('val', 0)):.1f} cm`**{tr} — {he} ★{rec.get('rarity', 1)} **{rec.get('name', '물고기')}** · 👤 `{rec.get('user_name', '낚시꾼')}`"
                )
        elif self.mode == "weight":
            title = f"⚖️ 서버 최대 무게(kg) 거대어 랭킹 TOP 12{q_suffix}"
            filtered = [r for r in lb["weight_top"] if self._matches_query(r)]
            for i, rec in enumerate(filtered[:12]):
                m = medals[i] if i < 3 else f"`{i+1}.`"
                he = fishing_core.HABITATS.get(rec.get("habitat", "lake"), fishing_core.HABITATS["lake"])["emoji"]
                lines.append(
                    f"{m} **`{_format_weight(float(rec.get('val', 0)))}`** — {he} ★{rec.get('rarity', 1)} **{rec.get('name', '물고기')}** · 👤 `{rec.get('user_name', '낚시꾼')}`"
                )
        else:
            title = f"📖 서버 어종 도감 수집왕 & 랭커 TOP 12{q_suffix}"
            tot = lb["total_species_count"]
            filtered = [r for r in lb["dex_top"] if self._matches_query(r)]
            for i, rec in enumerate(filtered[:12]):
                m = medals[i] if i < 3 else f"`{i+1}.`"
                pct = (rec["pokedex_cnt"] / max(1, tot)) * 100
                rec_badge = f" · 👑신기록 {rec['len_records_held']}종" if rec.get("len_records_held") else ""
                lines.append(
                    f"{m} **{rec['user_name']}** — **`{rec['pokedex_cnt']}/{tot}종`** (`{pct:.1f}%`) · Lv.{rec['level']} · `{rec['total_catches']}마리`{rec_badge}"
                )

        body = "\n".join(lines) if lines else "> *(아직 이 조건의 서버 낚시 기록이 없습니다. `/설정` (`🎮 미니게임` ➔ `🎣 세카이 낚시 출조`)로 첫 신기록의 주인공이 되어보세요!)*"
        embed = discord.Embed(
            title=title,
            description=body[:4096],
            color=0xF59E0B,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="아래 드롭다운에서 특정 낚시 랭커를 선택하면 장착 장비·보유 신기록을 자세히 확인할 수 있습니다.")
        return embed

    @discord.ui.button(label="📏 길이순", style=discord.ButtonStyle.primary, row=0)
    async def btn_len(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.selected_ranker_id = None
        self.mode = "length"
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="⚖️ 무게순", style=discord.ButtonStyle.secondary, row=0)
    async def btn_wt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.selected_ranker_id = None
        self.mode = "weight"
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="📖 도감왕", style=discord.ButtonStyle.secondary, row=0)
    async def btn_dex(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.selected_ranker_id = None
        self.mode = "dex"
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="📍 전체", style=discord.ButtonStyle.secondary, row=0)
    async def btn_hab(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        order = ["all", "lake", "river", "sea"]
        self.habitat_filter = order[(order.index(self.habitat_filter) + 1) % len(order)] if self.habitat_filter in order else "all"
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🏅 대회", style=discord.ButtonStyle.success, row=0)
    async def btn_open_tourney(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        status = await asyncio.to_thread(fishing_core.get_fishing_tournament_status, self.guild_id)
        view = FishingTournamentView(self.user, self.guild_id, status=status)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        view.message = msg


# ==========================================
# 7. 일일 낚시 의뢰 View
# ==========================================
class FishingQuestView(core.SafeView):
    def __init__(
        self,
        user: discord.abc.User,
        guild_id: int = 0,
        summary: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(timeout=None)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.summary = summary or fishing_core.get_user_fishing_summary(self.guild_id, user.id, user.display_name)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 본인의 일일 의뢰만 조작할 수 있습니다.", ephemeral=True)
            return False
        if not self.user:
            self.user = interaction.user
        return True

    def build_embed(self) -> discord.Embed:
        u = core.as_dict(self.summary.get("user"))
        dq = core.as_dict(u.get("daily_quests"))
        raw_items = dq.get("items", [])
        items = [q for q in (raw_items if isinstance(raw_items, list) else []) if isinstance(q, dict)]
        lines = []
        for q in items:
            prog = int(q.get("progress", 0))
            tgt = int(q.get("target", 1))
            if q.get("claimed"):
                st = "✅ 보상 수령 완료"
            elif prog >= tgt:
                st = "🎁 **완료! 수령 가능**"
            else:
                st = f"진행 중 (`{prog}/{tgt}`)"
            lines.append(
                f"• **{q.get('title', '낚시 의뢰')}** — {st}\n"
                f"  └ 보상: `{int(q.get('gold', 0)):,}🪙` + `{int(q.get('crystals', 0)):,}💎`"
            )

        return discord.Embed(
            title=f"📜 {self.user.display_name}님의 오늘의 낚시 의뢰 ({dq.get('date', core.get_today_str())})",
            description="\n".join(lines)[:4096],
            color=0x10B981,
            timestamp=datetime.datetime.now(core.KST),
        )

    @discord.ui.button(label="🎁 완료 의뢰 보상 일괄 수령", style=discord.ButtonStyle.success, row=0)
    async def btn_claim_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg, _, _ = await asyncio.to_thread(
            fishing_core.claim_all_completed_quests,
            self.guild_id,
            self.user.id,
            self.user.display_name,
        )
        self.summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary,
            self.guild_id,
            self.user.id,
            self.user.display_name,
        )
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🎣 낚시터 열기", style=discord.ButtonStyle.primary, row=0)
    async def btn_open_fishing(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        gid = self.guild_id or (interaction.guild_id or 0)
        summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary, gid, interaction.user.id, interaction.user.display_name
        )
        cast_view = FishingCastView(interaction.user, gid, summary=summary)
        await interaction.followup.send(embed=cast_view.build_dashboard_embed(), view=cast_view, wait=True)

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary,
            self.guild_id,
            self.user.id,
            self.user.display_name,
        )
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)


# ==========================================
# 8. 주말 낚시 대회 & 계절 한정 어종 토너먼트 View (#8)
# ==========================================
class FishingTournamentStartModal(core.SafeModal, title="🏆 커스텀 낚시 대회 개최 설정"):
    mode_input = discord.ui.TextInput(
        label="대회 종목 (계절 / 최장어 / 중량)",
        placeholder="계절 (또는 최장어, 중량 입력)",
        default="계절",
        required=True,
        max_length=20,
    )
    habitat_input = discord.ui.TextInput(
        label="대상 수역 (전체 / 호수 / 강 / 바다)",
        placeholder="전체 (또는 호수, 강, 바다 입력)",
        default="전체",
        required=True,
        max_length=20,
    )
    duration_input = discord.ui.TextInput(
        label="진행 시간 (분 단위, 10~1440분)",
        placeholder="예: 60 (1시간)",
        default="60",
        required=True,
        max_length=6,
    )
    title_input = discord.ui.TextInput(
        label="대회 이름 (비워두면 자동 생성)",
        placeholder="예: 주말 밤 대물 낚시 토너먼트!",
        required=False,
        max_length=60,
    )

    def __init__(self, parent_view: Optional["FishingTournamentView"] = None, guild_id: int = 0):
        super().__init__()
        self.parent_view = parent_view
        self.guild_id = int(guild_id or (parent_view.guild_id if parent_view else 0))

    async def on_submit(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        gid = self.guild_id or interaction.guild_id or 0
        m_raw = (self.mode_input.value or "").strip().lower()
        if any(k in m_raw for k in ("최장", "길이", "cm", "max")):
            mode_val = "max_cm"
        elif any(k in m_raw for k in ("중량", "무게", "kg", "total")):
            mode_val = "total_kg"
        else:
            mode_val = "seasonal_pts"

        h_raw = (self.habitat_input.value or "").strip().lower()
        hab_map = {"호수": "lake", "lake": "lake", "강": "river", "river": "river", "바다": "sea", "sea": "sea"}
        hab_val = hab_map.get(h_raw, "all")

        try:
            dur_val = max(10, min(1440, int((self.duration_input.value or "60").strip())))
        except ValueError:
            dur_val = 60

        ok, msg, _ = await asyncio.to_thread(
            fishing_core.start_fishing_tournament,
            gid,
            interaction.user.id,
            interaction.user.display_name,
            mode=mode_val,
            habitat=hab_val,
            duration_min=dur_val,
            custom_title=(self.title_input.value or "").strip(),
        )
        if self.parent_view is not None:
            await self.parent_view.reload()
            await _safe_update_message_or_interaction(
                interaction,
                interaction.message or self.parent_view.message,
                embed=self.parent_view.build_embed(),
                view=self.parent_view,
            )
        await interaction.followup.send(msg, ephemeral=not ok)


class FishingTournamentView(core.SafeView):
    """주말 자동 낚시 대회 & 커스텀 토너먼트 & 계절 제철 어종 보드"""

    def __init__(
        self,
        user: Optional[discord.abc.User] = None,
        guild_id: int = 0,
        status: Optional[Dict[str, Any]] = None,
        tab: str = "live",
    ):
        super().__init__(timeout=None)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.tab = tab
        self.status = status or fishing_core.get_fishing_tournament_status(self.guild_id)
        self.sync_controls()

    async def reload(self):
        self.status = await asyncio.to_thread(fishing_core.get_fishing_tournament_status, self.guild_id)
        self.sync_controls()

    def sync_controls(self):
        active = self.status.get("active") if isinstance(self.status, dict) else None
        has_active = isinstance(active, dict) and not active.get("settled")
        self.btn_tab_live.style = discord.ButtonStyle.primary if self.tab == "live" else discord.ButtonStyle.secondary
        self.btn_tab_season.style = discord.ButtonStyle.primary if self.tab == "season" else discord.ButtonStyle.secondary
        self.btn_tab_history.style = discord.ButtonStyle.primary if self.tab == "history" else discord.ButtonStyle.secondary
        self.btn_settle.disabled = not has_active

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if not self.user:
            self.user = interaction.user
        return True

    def build_embed(self) -> discord.Embed:
        season = self.status.get("season") or fishing_core.get_current_season_meta()
        active = self.status.get("active")
        rankings = self.status.get("rankings") or []
        featured = self.status.get("featured_species") or []
        history = self.status.get("history") or []

        if self.tab == "season":
            sp_lines = []
            for sp in featured[:15]:
                hab = fishing_core.HABITATS.get(sp["habitat"], fishing_core.HABITATS["lake"])
                rm = fishing_core.RARITY_META.get(sp["rarity"], fishing_core.RARITY_META[1])
                sp_lines.append(
                    f"• {hab['emoji']} {rm['stars']} {sp['emoji']} **{sp['name']}** (`{sp['sub_zone']}`) — "
                    f"`{sp['min_cm']:.0f}~{sp['max_cm']:.0f}cm` · 기본 `{sp['base_gold']:,}🪙` *(제철 +25%🪙 / 대회 1.5x)*"
                )
            body = "\n".join(sp_lines) if sp_lines else "• 계절 어종 데이터 로드 중"
            embed = discord.Embed(
                title=f"{season['emoji']} 현재 계절: {season['name']} 제철 보너스 어종 도감",
                description=(
                    f"> *{season['desc']}*\n\n"
                    "✨ **계절(제철) 어종 특별 혜택**\n"
                    "• 상시 포획 시 **판매 가치 `+25%🪙`** 자동 보너스!\n"
                    "• 낚시 대회 진행 중 포획 시 **계절 포인트 `1.5배` · 최장어 환산 `+15%`** 적용!\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{body}"
                )[:4096],
                color=season["color"],
                timestamp=datetime.datetime.now(core.KST),
            )
            embed.set_footer(text="계절은 KST 월(봄 3~5월 / 여름 6~8월 / 가을 9~11월 / 겨울 12~2월)에 따라 자동 전환됩니다.")
            return embed

        if self.tab == "history":
            if not history:
                hist_txt = "> *(아직 종료된 대회 기록이 없습니다. 첫 대회를 개최하거나 주말 자동 대회를 완주해 보세요!)*"
            else:
                h_blocks = []
                for idx, h in enumerate(history[:5], 1):
                    m_meta = fishing_core.TOURNAMENT_MODES.get(h.get("mode", "seasonal_pts"), fishing_core.TOURNAMENT_MODES["seasonal_pts"])
                    finals = h.get("final_rankings") or []
                    top_str = (
                        " · ".join(f"{r['badge'].split()[0]} **{r['user_name']}**(`{r['primary_score']:,.1f}{m_meta['unit']}`)" for r in finals[:3])
                        if finals
                        else "참가자 없음"
                    )
                    settled_at = str(h.get("settled_at") or "")[:16].replace("T", " ")
                    h_blocks.append(
                        f"**`#{idx}` {h.get('title', '낚시 대회')}** (`{settled_at} KST` 마감)\n"
                        f"└ 수상자: {top_str}"
                    )
                hist_txt = "\n\n".join(h_blocks)

            embed = discord.Embed(
                title="🏛️ 역대 낚시 토너먼트 명예의 전당 (최근 5회)",
                description=(
                    "🏆 **대회 순위별 시상 보상**\n"
                    "• 🥇 **1위 (챔피언):** `15,000🪙` + `500💎` + 우승 트로피 `+1`\n"
                    "• 🥈 **2위 (준우승):** `8,000🪙` + `300💎`\n"
                    "• 🥉 **3위 (입상):** `4,000🪙` + `150💎`\n"
                    "• 🎖️ **참가 완주상 (4위~):** `1,000🪙` + `30💎`\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{hist_txt}"
                )[:4096],
                color=0xF59E0B,
                timestamp=datetime.datetime.now(core.KST),
            )
            return embed

        # 기본 탭: 실시간 대회 현황 (live)
        if not isinstance(active, dict) or active.get("settled"):
            feat_preview = ", ".join(f"{s['emoji']}{s['name']}" for s in featured[:6])
            embed = discord.Embed(
                title=f"🏆 낚시 토너먼트 본부 ({season['emoji']} {season['name']} 시즌)",
                description=(
                    "현재 진행 중인 대회가 없습니다!\n"
                    "• **🗓️ 주말 정규 토너먼트:** 매주 **토요일 00:00 ~ 일요일 23:59 (KST)** 자동 오픈!\n"
                    "• **🏁 깜짝 번개 대회:** 아래 **`[🏁 새 대회 개최]`** 버튼으로 지금 바로 30분~2시간 대회를 열 수 있습니다.\n"
                    f"• **{season['emoji']} 이번 계절 제철 어종 (+25%🪙 / 대회 1.5x):** {feat_preview}\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "🎁 **시상 보상:** 🥇 `15,000🪙 + 500💎` · 🥈 `8,000🪙 + 300💎` · 🥉 `4,000🪙 + 150💎` · 참가상 `1,000🪙 + 30💎`"
                )[:4096],
                color=season["color"],
                timestamp=datetime.datetime.now(core.KST),
            )
            embed.set_footer(text="💡 [🏁 새 대회 개최] 버튼을 눌러 친구들과 실시간 대물 대결을 시작해 보세요!")
            return embed

        m_meta = fishing_core.TOURNAMENT_MODES.get(active.get("mode", "seasonal_pts"), fishing_core.TOURNAMENT_MODES["seasonal_pts"])
        hab_id = active.get("habitat", "all")
        hab_lbl = fishing_core.HABITATS[hab_id]["label"] if hab_id in fishing_core.HABITATS else "🌍 전체 수역 (호수·강·바다)"
        rem_str = self.status.get("remain_str") or "진행 중"

        rank_lines = []
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for r in rankings[:10]:
            rk = r["rank"]
            medal = medals.get(rk, f"`#{rk:2d}`")
            if active.get("mode") == "max_cm":
                score_txt = f"**`{r['score_cm']:.1f}cm`** (실측 `{r['max_cm']:.1f}cm`)"
            elif active.get("mode") == "total_kg":
                score_txt = f"**`{r['total_kg']:,.2f}kg`** (`{r['catch_count']}마리`)"
            else:
                score_txt = f"**`{r['seasonal_pts']:,}pt`** (`{r['catch_count']}마리` · 제철 `{r['seasonal_catches']}회`)"
            s_mark = "🌸" if r.get("best_is_seasonal") else ""
            rank_lines.append(
                f"{medal} **{r['user_name']}** — {score_txt}  |  대표어: {r['best_fish_emoji']}{s_mark} `★{r['best_fish_rarity']} {r['best_fish_name']} ({r['max_cm']:.1f}cm)`"
            )

        board_txt = "\n".join(rank_lines) if rank_lines else "> *(아직 첫 물고기를 낚은 참가자가 없습니다! 지금 `/설정` (`🎣 세카이 낚시 출조`) 또는 아래 `[🎣 바로 출조하기]`로 첫 1위를 차지하세요!)*"
        feat_names = ", ".join(f"{s['emoji']}{s['name']}" for s in featured[:6])

        embed = discord.Embed(
            title=f"🏆 {active.get('title', '실시간 낚시 토너먼트')}",
            description=(
                f"• **종목:** {m_meta['emoji']} **`{m_meta['name']}`**  ·  **주최:** `{active.get('host_name', '시스템')}`\n"
                f"• **대상 수역:** {hab_lbl}  ·  **남은 시간:** ⏳ **`{rem_str}`**\n"
                f"> *{m_meta['desc']}*\n"
                f"• **{season['emoji']} {season['name']} 제철 보너스 어종:** {feat_names}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "📊 **실시간 리더보드 (TOP 10)**\n"
                f"{board_txt}"
            )[:4096],
            color=0x10B981,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="낚시터에서 물고기를 잡으면 대회 기록이 자동으로 집계됩니다! (🥇1위 15,000🪙+500💎)")
        return embed

    @discord.ui.button(label="📊 실시간 순위", style=discord.ButtonStyle.primary, row=0)
    async def btn_tab_live(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.tab = "live"
        await self.reload()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🌸 제철 어종 도감", style=discord.ButtonStyle.secondary, row=0)
    async def btn_tab_season(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.tab = "season"
        await self.reload()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🏛️ 명예의 전당", style=discord.ButtonStyle.secondary, row=0)
    async def btn_tab_history(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.tab = "history"
        await self.reload()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        await self.reload()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🎣 바로 출조하기", style=discord.ButtonStyle.success, row=1)
    async def btn_go_fish(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        active = self.status.get("active") if isinstance(self.status, dict) else None
        req_hab = active.get("habitat") if isinstance(active, dict) and active.get("habitat") in fishing_core.HABITATS else None
        summary = await asyncio.to_thread(
            fishing_core.update_user_fishing_prefs,
            self.guild_id,
            interaction.user.id,
            interaction.user.display_name,
            habitat=req_hab,
        )
        cast_view = FishingCastView(interaction.user, guild_id=self.guild_id, summary=summary)
        msg = await interaction.followup.send(embed=cast_view.build_dashboard_embed(), view=cast_view, wait=True)
        cast_view.message = msg

    @discord.ui.button(label="🏁 새 대회 개최", style=discord.ButtonStyle.primary, row=1)
    async def btn_start_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        active = self.status.get("active") if isinstance(self.status, dict) else None
        is_admin = False
        if isinstance(interaction.user, discord.Member):
            perms = interaction.user.guild_permissions
            is_admin = bool(perms.administrator or perms.manage_guild)
        if isinstance(active, dict) and not active.get("settled") and active.get("is_auto_weekend") and not is_admin:
            await core.safe_send_response(
                interaction,
                "🗓️ 현재 **주말 정규 토너먼트**가 진행 중입니다! 진행 중인 주말 대회를 덮어쓰고 새 대회를 여는 것은 **서버 관리자**만 가능합니다.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(FishingTournamentStartModal(self, guild_id=self.guild_id))

    @discord.ui.button(label="🏅 대회 종료 및 시상", style=discord.ButtonStyle.danger, row=1)
    async def btn_settle(self, interaction: discord.Interaction, button: discord.ui.Button):
        active = self.status.get("active") if isinstance(self.status, dict) else None
        if not isinstance(active, dict) or active.get("settled"):
            await core.safe_send_response(interaction, "ℹ️ 현재 진행 중인 대회가 없습니다.", ephemeral=True)
            return
        is_admin = False
        if isinstance(interaction.user, discord.Member):
            perms = interaction.user.guild_permissions
            is_admin = bool(perms.administrator or perms.manage_guild)
        host_id = int(active.get("host_id") or 0)
        if not is_admin and (host_id == 0 or interaction.user.id != host_id):
            await core.safe_send_response(
                interaction,
                "🚨 대회 수동 마감은 **대회 개최자** 또는 **서버 관리자**만 실행할 수 있습니다. (주말 정규 대회 및 시간 만료 시에는 자동 정산됩니다!)",
                ephemeral=True,
            )
            return

        await core.safe_defer(interaction)
        ok, msg, settled = await asyncio.to_thread(fishing_core.finish_fishing_tournament, self.guild_id)
        await self.reload()
        self.tab = "history" if ok else self.tab
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)
        if ok and isinstance(settled, dict):
            finals = settled.get("final_rankings") or []
            podium = "\n".join(
                f"• {r['badge']} **{r['user_name']}** — `+{r['reward_gold']:,}🪙` · `+{r['reward_crystals']:,}💎`"
                for r in finals[:5]
            ) or "• 참가 기록 없음"
            await interaction.followup.send(f"{msg}\n{podium}")
        else:
            await interaction.followup.send(msg, ephemeral=True)


# ==========================================
# 9. 실시간 어시장 시세 & 오늘의 특가 매입 View
# ==========================================
class FishingMarketView(core.SafeView):
    def __init__(self, user: discord.abc.User, guild_id: int = 0):
        super().__init__(timeout=None)
        self.user = user
        self.guild_id = int(guild_id or 0)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        return True

    def build_embed(self) -> discord.Embed:
        mk = fishing_core.get_current_fish_market()
        hab_lines = []
        for h_id in ("lake", "river", "sea"):
            h = fishing_core.HABITATS[h_id]
            m = float(mk["habitat_mults"].get(h_id, 1.0))
            pct = int(round((m - 1.0) * 100))
            arrow = "🔺" if pct >= 15 else ("🟢" if pct >= 0 else "🔻")
            hab_lines.append(f"• {h['emoji']} **{h['name']}**: {arrow} **`×{m:.2f}`** (`{pct:+d}%`)")

        boosted_r = int(mk.get("boosted_rarity", 3))
        boosted_m = float(mk["rarity_mults"].get(boosted_r, 1.25))
        rm = fishing_core.RARITY_META.get(boosted_r, fishing_core.RARITY_META[3])

        feat_lines = []
        for sp in (mk.get("featured_species") or {}).values():
            h = fishing_core.HABITATS.get(sp["habitat"], fishing_core.HABITATS["lake"])
            feat_lines.append(
                f"• 🔥 {sp['emoji']} **★{sp['rarity']} {sp['name']}** ({h['emoji']} {h['name']}) — 매입가 **`×{sp['mult']:.2f}`**"
            )

        embed = discord.Embed(
            title="📈 실시간 노로시 수산 어시장 시세표 (3시간 KST 주기)",
            description=(
                f"• **적용 시간대:** `{mk['updated_label']}`  ·  **다음 시세 갱신:** ⏳ `{mk['remain_str']}`\n"
                f"• **시황 요약:** {mk['headline']}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "**🗺️ 서식지별 실시간 매입 배율**\n"
                + "\n".join(hab_lines)
                + f"\n\n**⭐ 수요 급증 성급:** {rm['emoji']} **`{rm['stars']} {rm['name']}`** 어종 전체 **`×{boosted_m:.2f}`**\n\n"
                "**🔥 오늘의 특가 매입 어종 (최대 ×2.05 고가 매입!)**\n"
                + ("\n".join(feat_lines) or "• 특가 어종 준비 중")
            )[:4096],
            color=0x10B981,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="💡 가방에서 물고기를 판매할 때 위 실시간 시세가 자동 적용됩니다! 아래 버튼으로 특가어만 골라 팔 수 있습니다.")
        return embed

    @discord.ui.button(label="🔥 내 가방 특가어 즉시 판매", style=discord.ButtonStyle.success, row=0)
    async def btn_sell_featured(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        gid = self.guild_id or (interaction.guild_id or 0)
        ok, msg, _, _ = await asyncio.to_thread(fishing_core.sell_bag_market_featured, gid, interaction.user.id)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🎒 내 가방 열기", style=discord.ButtonStyle.primary, row=0)
    async def btn_open_bag(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        gid = self.guild_id or (interaction.guild_id or 0)
        summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary, gid, interaction.user.id, interaction.user.display_name
        )
        bv = FishingBagView(interaction.user, gid, summary=summary)
        msg = await interaction.followup.send(embed=bv.build_embed(), view=bv, ephemeral=True, wait=True)
        bv.message = msg

    @discord.ui.button(label="🔄 시세 새로고침", style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)


# ==========================================
# 10. 서버 협동 거대 대어 보스 레이드 View
# ==========================================
class FishingBossRaidView(core.SafeView):
    def __init__(
        self,
        user: discord.abc.User,
        guild_id: int = 0,
        status: Optional[Dict[str, Any]] = None,
        show_history: bool = False,
    ):
        super().__init__(timeout=None)
        self.user = user
        self.guild_id = int(guild_id or 0)
        self.show_history = bool(show_history)
        self.status = status or fishing_core.get_fishing_boss_status(self.guild_id)
        self.sync_controls()

    async def reload(self):
        self.status = await asyncio.to_thread(fishing_core.get_fishing_boss_status, self.guild_id)
        self.sync_controls()

    def sync_controls(self):
        active = self.status.get("active") if isinstance(self.status, dict) else None
        has_active = isinstance(active, dict) and not active.get("defeated")
        self.btn_attack.disabled = not has_active
        self.btn_spawn.disabled = has_active
        self.btn_history.style = discord.ButtonStyle.primary if self.show_history else discord.ButtonStyle.secondary

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        return True

    def build_embed(self) -> discord.Embed:
        active = self.status.get("active") if isinstance(self.status, dict) else None
        rankings = self.status.get("rankings") or []
        history = self.status.get("history") or []

        if self.show_history:
            h_lines = []
            for h in history[:8]:
                st_badge = "🏆 토벌 성공" if h.get("defeated") else "💨 도주"
                h_lines.append(
                    f"• {h.get('emoji', '🐙')} **{h.get('name', '보스')}** — `{st_badge}` · `{h.get('ended_at', '')}` · 참가 `{h.get('participants_cnt', 0)}명` · MVP: `{h.get('mvp_name', '-')}`"
                )
            body = "\n".join(h_lines) if h_lines else "> *(아직 보스 레이드 토벌 기록이 없습니다!)*"
            return discord.Embed(
                title="📜 서버 협동 대어 보스 레이드 토벌 기록",
                description=body[:4096],
                color=0xF59E0B,
                timestamp=datetime.datetime.now(core.KST),
            )

        if not isinstance(active, dict) or active.get("defeated"):
            cd_min = int(self.status.get("cooldown_rem_min", 0) or 0)
            cd_txt = f"⏳ 다음 보스 소환까지 약 **`{cd_min}분`** 남았습니다." if cd_min > 0 else "🌊 지금 **`[🌊 거대 보스 소환]`** 버튼을 눌러 서버 협동 레이드를 시작할 수 있습니다!"
            pool_lines = "\n".join(
                f"• {b['emoji']} **{b['name']}** (HP `{b['max_hp']:,}`) — 보상 풀 `{b['pool_gold']:,}🪙` + `{b['pool_crystals']:,}💎` + 특급 미끼"
                for b in fishing_core.BOSS_SPECIES_POOL
            )
            return discord.Embed(
                title="🐙 서버 협동 거대 대어 보스 레이드 본부",
                description=(
                    f"{cd_txt}\n"
                    "• *폭풍우·피딩타임 중 낚시 출조 시에도 보스가 돌발 출현합니다!*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "**🌊 출현 가능 전설 대어 보스**\n"
                    f"{pool_lines}"
                )[:4096],
                color=0x6366F1,
                timestamp=datetime.datetime.now(core.KST),
            )

        hp = max(0, int(active.get("hp", 0) or 0))
        max_hp = max(1, int(active.get("max_hp", 1) or 1))
        ratio = max(0.0, min(1.0, hp / max_hp))
        filled = int(round(ratio * 14))
        hp_bar = "🟥" * filled + "⬜" * (14 - filled)
        rem_str = self.status.get("remain_str") or "진행 중"
        bait_name = fishing_core.BAITS.get(active.get("bait_id", "glow"), {}).get("name", "특급 미끼")

        rk_lines = []
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for idx, r in enumerate(rankings[:10], 1):
            m_icon = medals.get(idx, f"`#{idx}`")
            rk_lines.append(f"{m_icon} **{r['user_name']}** — 누적 피해 **`{r['damage']:,}`** (`{r['hits']}회`)")
        board = "\n".join(rk_lines) if rk_lines else "> *(아직 릴을 당긴 출조사가 없습니다! 첫 공격을 가해 MVP를 노려보세요!)*"

        embed = discord.Embed(
            title=f"🚨 [협동 레이드] {active['emoji']} {active['name']} 출현!",
            description=(
                f"> *{active['desc']}*\n\n"
                f"• **보스 체력:** {hp_bar} **`{hp:,} / {max_hp:,}`** (`{ratio * 100:.1f}%`)\n"
                f"• **남은 시간:** ⏳ `{rem_str}`  ·  **발견:** `{active.get('spawner_name', '서버')}`\n"
                f"• **토벌 보상:** 기본 `{active['base_gold']:,}🪙+{active['base_crystals']}💎` + 기여도 분배(`{active['pool_gold']:,}🪙+{active['pool_crystals']}💎`) + `{bait_name} ×{active['bait_qty']}` *(MVP 보너스 +1,500🪙+60💎)*\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "**⚔️ 실시간 서버 합동 기여도 TOP 10**\n"
                f"{board}"
            )[:4096],
            color=0xEF4444,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="💡 서버 멤버 누구나 [🎣 합동 릴 당기기!] 클릭 가능 (개인 쿨타임 8초 · 장비 티어 & 강화 수치에 비례해 피해 증가!)")
        return embed

    @discord.ui.button(label="🎣 합동 릴 당기기!", style=discord.ButtonStyle.danger, row=0)
    async def btn_attack(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        gid = self.guild_id or (interaction.guild_id or 0)
        ok, msg, info = await asyncio.to_thread(
            fishing_core.attack_fishing_boss, gid, interaction.user.id, interaction.user.display_name
        )
        self.show_history = False
        await self.reload()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)
        if ok and info.get("defeated"):
            rewards = info.get("rewards") or []
            podium = "\n".join(
                f"• {'👑 MVP ' if r.get('is_mvp') else ''}**{r['user_name']}** (`피해 {r['damage']:,}`) ➔ `+{r['gold']:,}🪙` · `+{r['crystals']:,}💎` · `{r['bait_name']} ×{r['bait_qty']}`"
                for r in rewards[:8]
            )
            await interaction.followup.send(f"{msg}\n{podium}")
        else:
            await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🌊 거대 보스 소환", style=discord.ButtonStyle.primary, row=0)
    async def btn_spawn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        gid = self.guild_id or (interaction.guild_id or 0)
        ok, msg, _ = await asyncio.to_thread(
            fishing_core.spawn_fishing_boss, gid, interaction.user.id, interaction.user.display_name
        )
        self.show_history = False
        await self.reload()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)
        await interaction.followup.send(msg, ephemeral=not ok)

    @discord.ui.button(label="📜 토벌 기록", style=discord.ButtonStyle.secondary, row=0)
    async def btn_history(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.show_history = not self.show_history
        await self.reload()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        await self.reload()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)


# ==========================================
# 11. 채널 즉석 1:1 대물 낚시 대결 View
# ==========================================
class FishingDuelView(core.SafeView):
    MAX_ROUNDS = 3

    def __init__(
        self,
        user: discord.abc.User,
        guild_id: int = 0,
        opponent: Optional[discord.abc.User] = None,
        wager: int = 0,
    ):
        super().__init__(timeout=120 if (wager or 0) > 0 else 600)
        self.user = user
        self.challenger = user
        self.opponent = opponent or user
        self.guild_id = int(guild_id or 0)
        self.wager = max(0, int(wager or 0))
        self.phase = "pending"  # pending -> active -> finished / cancelled
        self.escrowed = False
        self.p1_rolls: List[Dict[str, Any]] = []
        self.p2_rolls: List[Dict[str, Any]] = []
        self.result_banner: str = ""
        self._lock = asyncio.Lock()
        self.sync_controls()

    async def on_timeout(self):
        async with self._lock:
            if self.phase == "active" and self.escrowed and self.wager > 0:
                self.escrowed = False
                self.phase = "cancelled"
                self.result_banner = "⌛ 시간 만료로 대결이 중단되어 예치된 내기 골드가 양측에 전액 환불되었습니다."
                self.sync_controls()
                await asyncio.to_thread(
                    fishing_core.refund_fishing_duel_wager,
                    self.guild_id,
                    self.challenger.id,
                    self.challenger.display_name,
                    self.opponent.id,
                    self.opponent.display_name,
                    self.wager,
                )
        await super().on_timeout()

    def sync_controls(self):
        self.btn_accept.disabled = (self.phase != "pending")
        self.btn_decline.disabled = (self.phase != "pending")
        self.btn_throw.disabled = (self.phase != "active")
        if self.phase == "active":
            self.btn_throw.label = f"🎣 대결 투척! ({len(self.p1_rolls)}/{self.MAX_ROUNDS} vs {len(self.p2_rolls)}/{self.MAX_ROUNDS})"
        elif self.phase == "finished":
            self.btn_throw.label = "🏁 대결 종료"
        else:
            self.btn_throw.label = "🎣 대결 투척 (수락 대기)"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        allowed_ids = {self.challenger.id, self.opponent.id}
        if interaction.user.id not in allowed_ids:
            await core.safe_send_response(interaction, "❌ 이 1:1 낚시 대결의 참가자만 버튼을 누를 수 있습니다!", ephemeral=True)
            return False
        return True

    def _format_player_rolls(self, rolls: List[Dict[str, Any]]) -> str:
        if not rolls:
            return "> *(아직 투척 전)*"
        lines = []
        for idx, r in enumerate(rolls, 1):
            t_em = "👑" if r.get("is_trophy") else ""
            v_em = r.get("variant_emoji") or ""
            lines.append(f"`{idx}R` {r['emoji']} {v_em}{t_em}**★{r['rarity']} {r['name']}** `{r['length_cm']:.1f}cm` (**{r['score']:,}pt**)")
        return "\n".join(lines)

    def build_embed(self) -> discord.Embed:
        p1_tot = sum(int(r.get("score", 0)) for r in self.p1_rolls)
        p2_tot = sum(int(r.get("score", 0)) for r in self.p2_rolls)
        wager_txt = f"🪙 내기 골드: **`{self.wager:,}🪙`** (승자 독식)" if self.wager > 0 else "🤝 친선 대결 (내기 없음)"

        if self.phase == "pending":
            status_txt = f"⏳ {self.opponent.mention}님의 수락을 기다리고 있습니다! (`[⚔️ 대결 수락]` 클릭)"
            color = 0xF59E0B
        elif self.phase == "active":
            status_txt = f"🔥 **대결 진행 중!** 두 분 모두 **`[🎣 대결 투척!]`** 버튼을 각 **{self.MAX_ROUNDS}회**씩 눌러 최고 점수를 겨루세요!"
            color = 0x0EA5E9
        elif self.phase == "finished":
            status_txt = self.result_banner or "🏁 대결이 종료되었습니다!"
            color = 0x10B981
        else:
            status_txt = self.result_banner or "🛑 대결이 취소되었습니다."
            color = 0x64748B

        emb = discord.Embed(
            title=f"⚔️ 1:1 대물 낚시 대결 — {self.challenger.display_name} vs {self.opponent.display_name}",
            description=f"{status_txt}\n• {wager_txt}  ·  **방식:** 3라운드 총점제 (실제 장비·강화 반영)",
            color=color,
            timestamp=datetime.datetime.now(core.KST),
        )
        emb.add_field(
            name=f"🔵 {self.challenger.display_name} — 합계 {p1_tot:,}pt ({len(self.p1_rolls)}/{self.MAX_ROUNDS})",
            value=self._format_player_rolls(self.p1_rolls)[:1024],
            inline=True,
        )
        emb.add_field(
            name=f"🔴 {self.opponent.display_name} — 합계 {p2_tot:,}pt ({len(self.p2_rolls)}/{self.MAX_ROUNDS})",
            value=self._format_player_rolls(self.p2_rolls)[:1024],
            inline=True,
        )
        emb.set_footer(text="💡 희귀도 · 체장 비율 · 월척 · 변이(황금/알비노/심해)가 점수에 반영됩니다!")
        return emb

    @discord.ui.button(label="⚔️ 대결 수락", style=discord.ButtonStyle.success, row=0)
    async def btn_accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        async with self._lock:
            if self.phase != "pending":
                return
            if self.challenger.id == self.opponent.id:
                await interaction.followup.send("❌ 자기 자신과는 1:1 낚시 대결을 진행할 수 없습니다! 다른 서버 멤버를 지정해 주세요.", ephemeral=True)
                return
            if interaction.user.id != self.opponent.id:
                await interaction.followup.send(f"❌ 대결 수락은 상대방(**{self.opponent.display_name}**)만 누를 수 있습니다!", ephemeral=True)
                return
            if self.wager > 0:
                ok, err = await asyncio.to_thread(
                    fishing_core.escrow_fishing_duel_wager,
                    self.guild_id,
                    self.challenger.id,
                    self.challenger.display_name,
                    self.opponent.id,
                    self.opponent.display_name,
                    self.wager,
                )
                if not ok:
                    await interaction.followup.send(err, ephemeral=True)
                    return
                self.escrowed = True
            self.phase = "active"
            self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="❌ 거절/취소", style=discord.ButtonStyle.danger, row=0)
    async def btn_decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        async with self._lock:
            if self.phase != "pending":
                return
            self.phase = "cancelled"
            self.result_banner = f"🛑 **{interaction.user.display_name}**님이 1:1 낚시 대결을 취소/거절했습니다."
            self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🎣 대결 투척!", style=discord.ButtonStyle.primary, disabled=True, row=0)
    async def btn_throw(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        async with self._lock:
            if self.phase != "active":
                return
            is_p1 = (interaction.user.id == self.challenger.id)
            target_rolls = self.p1_rolls if is_p1 else self.p2_rolls
            if len(target_rolls) >= self.MAX_ROUNDS:
                await interaction.followup.send("✅ 이미 3라운드 투척을 모두 완료했습니다! 상대방의 결과를 기다려 주세요.", ephemeral=True)
                return

            roll = await asyncio.to_thread(
                fishing_core.roll_duel_cast, self.guild_id, interaction.user.id, interaction.user.display_name
            )
            target_rolls.append(roll)

            if len(self.p1_rolls) >= self.MAX_ROUNDS and len(self.p2_rolls) >= self.MAX_ROUNDS:
                p1_tot = sum(int(r.get("score", 0)) for r in self.p1_rolls)
                p2_tot = sum(int(r.get("score", 0)) for r in self.p2_rolls)
                if p1_tot > p2_tot:
                    winner_id = self.challenger.id
                elif p2_tot > p1_tot:
                    winner_id = self.opponent.id
                else:
                    winner_id = None
                was_escrowed = self.escrowed
                self.escrowed = False
                _, settle_msg, _ = await asyncio.to_thread(
                    fishing_core.settle_fishing_duel,
                    self.guild_id,
                    self.challenger.id,
                    self.challenger.display_name,
                    self.opponent.id,
                    self.opponent.display_name,
                    winner_id,
                    self.wager,
                    was_escrowed,
                )
                self.phase = "finished"
                self.result_banner = f"{settle_msg} (`{p1_tot:,}pt` vs `{p2_tot:,}pt`)"
            self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)


# ==========================================
# 12. 유저 간 물고기 선물 선택 View (/낚시 선물 @유저)
# ==========================================
class FishingGiftFishSelect(discord.ui.Select):
    def __init__(self, parent_view: "FishingGiftView"):
        self.parent_view = parent_view
        opts = self._build_opts()
        is_empty = (len(opts) == 1 and opts[0].value == "NONE")
        super().__init__(
            placeholder="🎁 선물할 미잠금 물고기 선택...",
            min_values=1,
            max_values=1,
            options=opts,
            row=0,
            custom_id="norosi:FishingGiftView:fish_select",
        )
        self.disabled = is_empty

    def _build_opts(self) -> List[discord.SelectOption]:
        u = self.parent_view.summary["user"]
        bag = [it for it in reversed(u.get("bag") or []) if isinstance(it, dict) and not it.get("locked") and it.get("uid")]
        if not bag:
            return [discord.SelectOption(label="선물 가능한 미잠금 물고기가 없습니다", value="NONE")]
        opts = []
        seen = set()
        for it in bag[:25]:
            uid_s = str(it["uid"])[:100]
            if uid_s in seen:
                continue
            seen.add(uid_s)
            v_em = fishing_core.get_variant_meta(it.get("variant"))["emoji"]
            opts.append(discord.SelectOption(
                label=f"{v_em}★{it.get('rarity', 1)} {it.get('name', '물고기')} ({float(it.get('length_cm', 0)):.1f}cm)"[:95],
                value=uid_s,
                description=f"가치 {int(it.get('gold', 0)):,}🪙 · 선택 즉시 선물 전달"[:95],
            ))
        return opts or [discord.SelectOption(label="선물 가능한 미잠금 물고기가 없습니다", value="NONE")]

    async def callback(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        val = self.values[0]
        if val == "NONE":
            return
        ok, msg, _ = await asyncio.to_thread(
            fishing_core.gift_fish_to_user,
            self.parent_view.guild_id,
            self.parent_view.user.id,
            self.parent_view.user.display_name,
            self.parent_view.receiver.id,
            self.parent_view.receiver.display_name,
            val,
        )
        self.parent_view.summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary,
            self.parent_view.guild_id,
            self.parent_view.user.id,
            self.parent_view.user.display_name,
        )
        new_opts = self._build_opts()
        self.options = new_opts
        self.disabled = (len(new_opts) == 1 and new_opts[0].value == "NONE")
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.parent_view.build_embed(), view=self.parent_view)
        await interaction.followup.send(msg, ephemeral=not ok)


class FishingGiftView(core.SafeView):
    def __init__(
        self,
        user: discord.abc.User,
        guild_id: int = 0,
        receiver: Optional[discord.abc.User] = None,
        summary: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(timeout=180)
        self.user = user
        self.receiver = receiver or user
        self.guild_id = int(guild_id or 0)
        self.summary = summary or fishing_core.get_user_fishing_summary(self.guild_id, user.id, user.display_name)
        self.fish_select = FishingGiftFishSelect(self)
        self.add_item(self.fish_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, "❌ 선물 창을 연 본인만 선택할 수 있습니다.", ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        u = self.summary["user"]
        unlocked = [it for it in (u.get("bag") or []) if isinstance(it, dict) and not it.get("locked")]
        return discord.Embed(
            title=f"🎁 {self.receiver.display_name}님에게 물고기 선물하기",
            description=(
                f"• **받는 분:** {self.receiver.mention}\n"
                f"• **선물 가능한 미잠금 물고기:** `{len(unlocked)}마리` *(최근 포획 25마리 표시)*\n"
                "> *🔒 잠금 보호 중인 물고기를 선물하려면 `/낚시 가방`에서 먼저 잠금을 해제해 주세요!*"
            ),
            color=0xF472B6,
            timestamp=datetime.datetime.now(core.KST),
        )


# ==========================================
# /낚시 GroupCog
# ==========================================
class FishingCog(commands.GroupCog, name="낚시", description="🏞️ 호수 · 🌊 강 · ⚓ 바다 통합 낚시 · 수족관 · 어시장 · 보스레이드 · 공방 · 대결"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    async def _open_cast_hub(
        self,
        interaction: discord.Interaction,
        habitat_val: Optional[str] = None,
        bait_val: Optional[str] = None,
        quick_mode: Optional[bool] = None,
        spot_val: Optional[str] = None,
    ):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        sess = _get_or_create_cast_session(guild_id, interaction.user.id)
        async with sess.lock:
            _cancel_session_tasks(sess)
            sess.cast_seq += 1
            sess.phase = "idle"
            sess.updated_at = time.monotonic()

        if spot_val and spot_val in fishing_core.SPECIAL_SPOTS:
            cur_sum = await asyncio.to_thread(
                fishing_core.get_user_fishing_summary, guild_id, interaction.user.id, interaction.user.display_name
            )
            if not fishing_core.is_special_spot_unlocked(cur_sum["user"], spot_val):
                sp = fishing_core.SPECIAL_SPOTS[spot_val]
                await interaction.followup.send(
                    f"🔒 {sp['emoji']} **{sp['name']}**은(는) 아직 해금되지 않았습니다! (조건: `{sp['req_desc']}`)",
                    ephemeral=True,
                )
                spot_val = None

        summary = await asyncio.to_thread(
            fishing_core.update_user_fishing_prefs,
            guild_id,
            interaction.user.id,
            interaction.user.display_name,
            habitat=habitat_val,
            bait_id=bait_val,
            auto_mode=quick_mode,
            spot_id=spot_val,
        )
        view = FishingCastView(interaction.user, guild_id=guild_id, summary=summary)
        msg = await interaction.followup.send(embed=view.build_dashboard_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="출조", description="🏞️ 호수·🌊 강·⚓ 바다·해금 특수터로 출조해 글로벌 어종 낚시 미니게임을 플레이합니다")
    @app_commands.describe(
        장소="출조할 낚시터 (호수 / 강 / 바다 / 해금형 특수 낚시터 3종)",
        미끼="사용할 미끼 종류 (미선택 시 기존 설정 유지)",
        빠른모드="입질 대기 없이 바로 채집하는 자동채집 모드 여부",
    )
    @app_commands.choices(
        장소=[
            app_commands.Choice(name=f"🏞️ 호수 ({len(fishing_core.FISH_BY_HABITAT['lake']):,}종)", value="lake"),
            app_commands.Choice(name=f"🌊 강 ({len(fishing_core.FISH_BY_HABITAT['river']):,}종)", value="river"),
            app_commands.Choice(name=f"⚓ 바다 ({len(fishing_core.FISH_BY_HABITAT['sea']):,}종)", value="sea"),
            app_commands.Choice(name="🧊 [특수] 빙하 빙어호수 (Lv.5 / 도감 20종)", value="spot:glacier"),
            app_commands.Choice(name="🏝️ [특수] 산호초 환초군도 (Lv.10 / 도감 50종)", value="spot:coral_atoll"),
            app_commands.Choice(name="🕳️ [특수] 마리아나 심해 해구 (Lv.18 / 도감 100종)", value="spot:mariana_trench"),
        ],
        미끼=[
            app_commands.Choice(name="🍡 기본 곡물 떡밥 (무제한)", value="dough"),
            app_commands.Choice(name="🪱 싱싱한 붉은 지렁이", value="worm"),
            app_commands.Choice(name="🦐 활력 생물 크릴새우", value="shrimp"),
            app_commands.Choice(name="🪝 메탈 지그 루어", value="lure"),
            app_commands.Choice(name="💠 야광 심해 집어 미끼", value="glow"),
            app_commands.Choice(name="✨ 황금 전설 떡밥", value="golden"),
            app_commands.Choice(name="🐟 특제 생미끼 (공방 제작)", value="live_minnow"),
            app_commands.Choice(name="🍖 대물 특제 집어제 (공방 제작)", value="trophy_chum"),
        ],
    )
    async def fishing_cast_cmd(
        self,
        interaction: discord.Interaction,
        장소: Optional[app_commands.Choice[str]] = None,
        미끼: Optional[app_commands.Choice[str]] = None,
        빠른모드: Optional[bool] = None,
    ):
        raw_loc = 장소.value if 장소 else None
        hab_v = None
        spot_v = None
        if raw_loc and raw_loc.startswith("spot:"):
            spot_v = raw_loc.split(":", 1)[1]
        elif raw_loc:
            hab_v = raw_loc
            spot_v = ""
        await self._open_cast_hub(
            interaction,
            habitat_val=hab_v,
            bait_val=미끼.value if 미끼 else None,
            quick_mode=빠른모드,
            spot_val=spot_v,
        )

    @app_commands.command(name="가방", description="🎒 잡은 물고기 보관함 조회 · 다중 선택 잠금/해제 · 실시간 시세 판매 · 스마트 정리 · 선물")
    @app_commands.describe(장소="필터링할 낚시터", 성급="필터링할 희귀도")
    @app_commands.choices(
        장소=[
            app_commands.Choice(name="전체 장소", value="all"),
            app_commands.Choice(name="🏞️ 호수", value="lake"),
            app_commands.Choice(name="🌊 강", value="river"),
            app_commands.Choice(name="⚓ 바다", value="sea"),
        ],
        성급=[
            app_commands.Choice(name="전체 성급", value=0),
            app_commands.Choice(name="★1 일반", value=1),
            app_commands.Choice(name="★2 고급", value=2),
            app_commands.Choice(name="★3 희귀", value=3),
            app_commands.Choice(name="★4 전설", value=4),
            app_commands.Choice(name="★5 신화", value=5),
        ],
    )
    async def fishing_bag_cmd(
        self,
        interaction: discord.Interaction,
        장소: Optional[app_commands.Choice[str]] = None,
        성급: Optional[app_commands.Choice[int]] = None,
    ):
        await core.safe_defer(interaction)
        hab = 장소.value if 장소 else "all"
        rar = 성급.value if 성급 else 0
        summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary, interaction.guild_id or 0, interaction.user.id, interaction.user.display_name
        )
        view = FishingBagView(interaction.user, interaction.guild_id or 0, hab, rar, summary=summary)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="도감", description=f"📖 호수·강·바다 {len(fishing_core.FISH_SPECIES_DB):,}종 글로벌 물고기 도감 · 금관/은관 · 변이 기록 확인")
    @app_commands.describe(탭="초기 표시 탭", 어종검색="특정 물고기 이름/학명/키워드 조회")
    @app_commands.choices(탭=[
        app_commands.Choice(name=f"🏞️ 호수 ({len(fishing_core.FISH_BY_HABITAT['lake']):,}종)", value="lake"),
        app_commands.Choice(name=f"🌊 강 ({len(fishing_core.FISH_BY_HABITAT['river']):,}종)", value="river"),
        app_commands.Choice(name=f"⚓ 바다 ({len(fishing_core.FISH_BY_HABITAT['sea']):,}종)", value="sea"),
        app_commands.Choice(name="✅ 보유 어종", value="owned"),
        app_commands.Choice(name="🔒 미보유 어종", value="unowned"),
    ])
    @app_commands.autocomplete(어종검색=fishing_core.fish_species_autocomplete)
    async def fishing_pokedex_cmd(
        self,
        interaction: discord.Interaction,
        탭: Optional[app_commands.Choice[str]] = None,
        어종검색: Optional[str] = None,
    ):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        q_raw = (어종검색 or "").strip()
        stats = await asyncio.to_thread(fishing_core.get_fishing_pokedex_stats, guild_id, interaction.user.id)

        target_sp: Optional[Dict[str, Any]] = None
        if q_raw in fishing_core.FISH_BY_ID:
            target_sp = fishing_core.FISH_BY_ID[q_raw]
        elif q_raw:
            hits = await asyncio.to_thread(fishing_core.search_fish_species, q_raw, 50)
            if len(hits) == 1:
                target_sp = hits[0]

        if target_sp is not None:
            sp = target_sp
            hab = fishing_core.HABITATS.get(sp["habitat"], fishing_core.HABITATS["lake"])
            rm = fishing_core.RARITY_META.get(int(sp.get("rarity", 1)), fishing_core.RARITY_META[1])
            rec = stats["pokedex"].get(sp["id"])
            time_txt = {"day": "☀️ 낮 (06~18시)", "night": "🌙 밤 (18~06시)", "all": "⏰ 전 시간대"}.get(sp.get("active_time", "all"), "⏰ 전 시간대")
            w_meta = fishing_core.WEATHERS.get(sp["prefer_weather"])
            w_txt = f"{w_meta['emoji']} {w_meta['name']}" if w_meta else "🌤️ 모든 날씨"
            b_txt = fishing_core.BAITS.get(sp["prefer_bait"], {}).get("name", "기본 떡밥")

            if rec:
                crown_tags = []
                if rec.get("max_crown"):
                    crown_tags.append("🏆최대금관")
                if rec.get("min_crown"):
                    crown_tags.append("🥈최소은관")
                for vk in (rec.get("variants") or []):
                    vm = fishing_core.get_variant_meta(vk)
                    crown_tags.append(f"{vm['emoji']}{vm['name']}")
                extra_b = f" · {' '.join(crown_tags)}" if crown_tags else ""
                rec_str = f"✅ **획득 완료 (`{rec['count']}마리`)** — 내 최고 `{rec['max_cm']:.1f}cm` · `{_format_weight(float(rec['max_kg']))}`{extra_b}"
            else:
                rec_str = "⬜ **아직 포획하지 못한 어종입니다.**"
            embed = discord.Embed(
                title=f"{sp['emoji']} {sp['name']} ({sp['scientific_name']})",
                description=(
                    f"• **서식지:** {hab['emoji']} `{hab['name']} · {sp['sub_zone']}`\n"
                    f"• **등급:** {rm['emoji']} `{rm['name']} ({rm['full_stars']})`\n"
                    f"• **서식 크기 범위:** `{sp['min_cm']:.1f}cm ~ {sp['max_cm']:.1f}cm`  ·  **기본 가치:** `{sp['base_gold']:,}🪙`\n"
                    f"• **선호 환경:** {time_txt} · {w_txt} · 🪱 `{b_txt}`\n"
                    f"• **내 도감 기록:** {rec_str}\n\n"
                    f"> *{sp['desc']}*"
                ),
                color=rm["discord_color"],
            )
            await interaction.followup.send(embed=embed)
            return

        tab_val = (탭.value if 탭 else ("all" if q_raw else "lake"))
        view = FishingPokedexView(interaction.user, guild_id, tab_val, stats=stats, search_query=q_raw)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="수족관", description="🐠 나만의 개인 어항 PNG 스냅샷 감상 · 먹이주기(+35%/성장) · 테마 꾸미기 · 수익 수확")
    @app_commands.describe(유저="다른 멤버의 수족관 구경하기 (미지정 시 내 수족관)")
    async def fishing_aquarium_cmd(self, interaction: discord.Interaction, 유저: Optional[discord.Member] = None):
        await core.safe_defer(interaction)
        target = 유저 or interaction.user
        guild_id = interaction.guild_id or 0
        summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary, guild_id, target.id, target.display_name
        )
        view = FishingAquariumView(interaction.user, target, guild_id, summary=summary)
        msg = await view.send_initial(interaction, ephemeral=False)
        view.message = msg

    @app_commands.command(name="상점", description="🛒 낚싯대 · 릴 · 그물 · 미끼 · 장비강화(+10) · 미끼제작 · 수조테마 · 가방/수족관 확장")
    @app_commands.describe(분류="상점 초기 카테고리")
    @app_commands.choices(분류=[
        app_commands.Choice(name="🎣 낚싯대 (Rod)", value="rod"),
        app_commands.Choice(name="🌀 릴 (Reel)", value="reel"),
        app_commands.Choice(name="🕸️ 그물 (Net · 2~10마리 포획)", value="net"),
        app_commands.Choice(name="🪱 미끼 (Bait)", value="bait"),
        app_commands.Choice(name="🔨 장비 강화 (+1 ~ +10)", value="enhance"),
        app_commands.Choice(name="🧪 소형어 미끼 제작 공방", value="craft"),
        app_commands.Choice(name="🎨 수족관 배경 테마", value="tank_theme"),
        app_commands.Choice(name="🐠 수족관 확장", value="tank_expand"),
        app_commands.Choice(name="🎒 가방 확장 (180→2,000칸)", value="bag_expand"),
    ])
    async def fishing_shop_cmd(self, interaction: discord.Interaction, 분류: Optional[app_commands.Choice[str]] = None):
        await core.safe_defer(interaction, ephemeral=True)
        cat = 분류.value if 분류 else "rod"
        guild_id = interaction.guild_id or 0
        summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary, guild_id, interaction.user.id, interaction.user.display_name
        )
        view = FishingShopView(interaction.user, guild_id, cat, summary=summary)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        view.message = msg

    @app_commands.command(name="시세", description="📈 3시간마다 변동되는 실시간 어시장 시세 & 오늘의 특가(×2.05) 매입 확인 및 즉시 판매")
    async def fishing_market_cmd(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        view = FishingMarketView(interaction.user, interaction.guild_id or 0)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="레이드", description="🐙 서버 멤버들과 협동해 거대 대어 보스(크라켄·메갈로돈·리바이어던)를 토벌하고 보상을 받습니다")
    async def fishing_boss_raid_cmd(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        status = await asyncio.to_thread(fishing_core.get_fishing_boss_status, guild_id)
        view = FishingBossRaidView(interaction.user, guild_id=guild_id, status=status)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="공방", description="🔨 장비 강화(+1~+10 · 파괴없음) · 소형어 분해 특제 생미끼 제작 · 수족관 테마 공방 열기")
    @app_commands.describe(탭="초기 공방 탭")
    @app_commands.choices(탭=[
        app_commands.Choice(name="🔨 장비 강화 (+1 ~ +10)", value="enhance"),
        app_commands.Choice(name="🧪 소형어 특제 미끼 제작", value="craft"),
        app_commands.Choice(name="🎨 수족관 배경 테마", value="tank_theme"),
    ])
    async def fishing_workshop_cmd(self, interaction: discord.Interaction, 탭: Optional[app_commands.Choice[str]] = None):
        await core.safe_defer(interaction, ephemeral=True)
        cat = 탭.value if 탭 else "enhance"
        guild_id = interaction.guild_id or 0
        summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary, guild_id, interaction.user.id, interaction.user.display_name
        )
        view = FishingShopView(interaction.user, guild_id, cat, summary=summary)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        view.message = msg

    @app_commands.command(name="대결", description="⚔️ 채널에서 다른 멤버와 즉석 1:1 3라운드 대물 낚시 대결을 신청합니다")
    @app_commands.describe(
        상대="대결을 신청할 서버 멤버",
        내기골드="내기할 낚시 골드 (0 입력 시 친선전, 최대 50,000🪙)",
    )
    async def fishing_duel_cmd(
        self,
        interaction: discord.Interaction,
        상대: discord.Member,
        내기골드: app_commands.Range[int, 0, 50000] = 0,
    ):
        if 상대.bot:
            await core.safe_send_response(interaction, "❌ 봇에게는 낚시 대결을 신청할 수 없습니다!", ephemeral=True)
            return
        if 상대.id == interaction.user.id:
            await core.safe_send_response(interaction, "❌ 자기 자신에게는 대결을 신청할 수 없습니다!", ephemeral=True)
            return
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        if 내기골드 > 0:
            s1 = await asyncio.to_thread(fishing_core.get_user_fishing_summary, guild_id, interaction.user.id, interaction.user.display_name)
            if int(s1["user"].get("gold", 0)) < 내기골드:
                await interaction.followup.send(
                    f"❌ 보유 낚시 골드가 부족합니다! (보유 `{int(s1['user'].get('gold', 0)):,}🪙` / 신청 `{내기골드:,}🪙`)",
                    ephemeral=True,
                )
                return
        view = FishingDuelView(interaction.user, guild_id=guild_id, opponent=상대, wager=내기골드)
        msg = await interaction.followup.send(
            content=f"⚔️ {상대.mention}님, {interaction.user.mention}님이 **1:1 대물 낚시 대결**을 신청했습니다!",
            embed=view.build_embed(),
            view=view,
            wait=True,
        )
        view.message = msg

    @app_commands.command(name="선물", description="🎁 내 낚시 가방에 있는 미잠금 물고기를 다른 멤버에게 선물합니다")
    @app_commands.describe(유저="물고기를 선물받을 멤버")
    async def fishing_gift_cmd(self, interaction: discord.Interaction, 유저: discord.Member):
        if 유저.bot:
            await core.safe_send_response(interaction, "❌ 봇에게는 물고기를 선물할 수 없습니다!", ephemeral=True)
            return
        if 유저.id == interaction.user.id:
            await core.safe_send_response(interaction, "❌ 자기 자신에게는 물고기를 선물할 수 없습니다!", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild_id or 0
        summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary, guild_id, interaction.user.id, interaction.user.display_name
        )
        view = FishingGiftView(interaction.user, guild_id=guild_id, receiver=유저, summary=summary)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        view.message = msg

    @app_commands.command(name="랭킹", description="🏆 서버 내 물고기 최대 길이(cm)·무게(kg)·도감 수집왕 순위 및 랭커 상세 정보 조회")
    @app_commands.describe(
        기준="초기 순위표 기준 (최대 길이 / 최대 무게 / 도감 수집왕)",
        장소="서식지 필터 (전체 / 호수 / 강 / 바다)",
        어종검색="특정 물고기 이름 검색 (선택)",
        랭커="특정 멤버의 낚시 랭커 기록 바로 보기 (선택)",
    )
    @app_commands.choices(
        기준=[
            app_commands.Choice(name="📏 최대 길이(cm)", value="length"),
            app_commands.Choice(name="⚖️ 최대 무게(kg)", value="weight"),
            app_commands.Choice(name="📖 도감 수집왕", value="dex"),
        ],
        장소=[
            app_commands.Choice(name="전체 장소", value="all"),
            app_commands.Choice(name="🏞️ 호수", value="lake"),
            app_commands.Choice(name="🌊 강", value="river"),
            app_commands.Choice(name="⚓ 바다", value="sea"),
        ],
    )
    @app_commands.autocomplete(어종검색=fishing_core.fish_species_autocomplete)
    async def fishing_ranking_cmd(
        self,
        interaction: discord.Interaction,
        기준: Optional[app_commands.Choice[str]] = None,
        장소: Optional[app_commands.Choice[str]] = None,
        어종검색: Optional[str] = None,
        랭커: Optional[discord.Member] = None,
    ):
        await core.safe_defer(interaction)
        mode = 기준.value if 기준 else "length"
        hab = 장소.value if 장소 else "all"
        q_val = 어종검색 or ""
        if q_val in fishing_core.FISH_BY_ID:
            q_val = fishing_core.FISH_BY_ID[q_val]["name"]
        ranker_id = str(랭커.id) if 랭커 else None
        view = FishingRankingView(
            interaction.user,
            guild_id=interaction.guild_id or 0,
            mode=mode,
            habitat_filter=hab,
            search_query=q_val,
            selected_ranker_id=ranker_id,
        )
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="대회", description="🏅 주말 자동 낚시 토너먼트 · 커스텀 번개 대회 개최 · 계절 제철 어종 보너스 및 순위 확인")
    @app_commands.describe(탭="초기 조회할 대회 탭")
    @app_commands.choices(탭=[
        app_commands.Choice(name="📊 실시간 대회 리더보드", value="live"),
        app_commands.Choice(name="🌸 계절 제철 보너스 어종 도감", value="season"),
        app_commands.Choice(name="🏛️ 역대 대회 명예의 전당", value="history"),
    ])
    async def fishing_tournament_cmd(
        self,
        interaction: discord.Interaction,
        탭: Optional[app_commands.Choice[str]] = None,
    ):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        tab_val = 탭.value if 탭 else "live"
        status = await asyncio.to_thread(fishing_core.get_fishing_tournament_status, guild_id)
        view = FishingTournamentView(interaction.user, guild_id=guild_id, status=status, tab=tab_val)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="퀘스트", description="📜 매일 KST 00:00 갱신되는 일일 낚시 의뢰 3종 확인 및 골드+💎 크리스탈 보상 수령")
    async def fishing_quest_cmd(self, interaction: discord.Interaction):
        await core.safe_defer(interaction, ephemeral=True)
        guild_id = interaction.guild_id or 0
        summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary, guild_id, interaction.user.id, interaction.user.display_name
        )
        view = FishingQuestView(interaction.user, guild_id, summary=summary)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        view.message = msg

    @app_commands.command(name="프로필", description="🪪 낚시꾼 레벨·장비 강화·금관/변이·콤보·레이드·대결 전적 종합 프로필 조회")
    @app_commands.describe(유저="조회할 멤버 (미지정 시 본인)")
    async def fishing_profile_cmd(self, interaction: discord.Interaction, 유저: Optional[discord.Member] = None):
        await core.safe_defer(interaction)
        target = 유저 or interaction.user
        guild_id = interaction.guild_id or 0
        summary = await asyncio.to_thread(fishing_core.get_user_fishing_summary, guild_id, target.id, target.display_name)
        stats = await asyncio.to_thread(fishing_core.get_fishing_pokedex_stats, guild_id, target.id)
        u = summary["user"]
        rod = summary["rod"]
        reel = summary["reel"]
        net = summary.get("net")
        bait = summary["bait"]
        enh = summary.get("enhance") or fishing_core.get_gear_enhance_bonuses(u)
        r_tag = f" `+{enh['rod_lv']}`" if enh.get("rod_lv") else ""
        rl_tag = f" `+{enh['reel_lv']}`" if enh.get("reel_lv") else ""
        n_tag = f" `+{enh['net_lv']}`" if enh.get("net_lv") else ""
        net_txt = (
            f"{net['emoji']} `{net['name']}`{n_tag} (1회 `{net['min_catch']}~{net['max_catch']}마리`)"
            if net
            else "🚫 `미장착` *(상점에서 그물 구매 시 2~10마리 포획)*"
        )

        pct = (stats["owned_total"] / max(1, stats["total_species"])) * 100
        by_h = stats["by_habitat"]
        bag_cap = fishing_core.get_bag_capacity(u)
        bag_len = len(u.get("bag", []) if isinstance(u.get("bag"), list) else [])
        wins = int(u.get("tournament_wins", 0) or 0)
        vc = core.as_dict(stats.get("variant_counts"))
        spots_unlocked = summary.get("unlocked_spots") or []
        spots_txt = ", ".join(f"{fishing_core.SPECIAL_SPOTS[s]['emoji']}{fishing_core.SPECIAL_SPOTS[s]['short']}" for s in spots_unlocked) or "아직 해금 없음"

        embed = discord.Embed(
            title=f"🎣 {target.display_name}님의 낚시꾼 라이선스 (Lv.{u['level']})",
            description=(
                f"• **EXP:** `{summary['rem_exp']} / {summary['need_exp']}`  ·  **누적 포획:** `{u['total_catches']:,}마리` (👑 월척 `{u['total_trophy']:,}` · 🏆 대회 우승 `{wins}`)\n"
                f"• **🪙 보유 골드:** **`{u['gold']:,}🪙`** (누적 `{u['total_gold_earned']:,}🪙`)  ·  **💎 크리스탈:** **`{summary['crystals']:,}💎`**\n"
                f"• **⚡ 최고 콤보:** `{u.get('max_combo', 0)}연승`  ·  **🏴‍☠️ 보물 인양:** `{u.get('treasures_found', 0)}회`  ·  **🐙 보스 토벌:** `{u.get('boss_defeats', 0)}회`  ·  **⚔️ 1:1 대결:** `{u.get('duel_wins', 0)}승 {u.get('duel_losses', 0)}패`\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **낚싯대:** {rod['emoji']} `{rod['name']}`{r_tag}  ·  **릴:** {reel['emoji']} `{reel['name']}`{rl_tag}\n"
                f"• **그물:** {net_txt}  ·  **기본 미끼:** {bait['emoji']} `{bait['name']}`\n"
                f"• **🗺️ 해금 특수터:** {spots_txt}\n"
                f"• **📖 도감 수집률:** **`{stats['owned_total']:,}/{stats['total_species']:,}종 ({pct:.2f}%)`** "
                f"(🏞️ `{by_h['lake']['owned']:,}` · 🌊 `{by_h['river']['owned']:,}` · ⚓ `{by_h['sea']['owned']:,}`)\n"
                f"• **👑 금관 & 변이:** 🏆 최대금관 `{stats.get('max_crowns', 0)}` · 🥈 최소은관 `{stats.get('min_crowns', 0)}` · ✨ `{vc.get('golden', 0)}` · ❄️ `{vc.get('albino', 0)}` · 🌌 `{vc.get('abyssal', 0)}`\n"
                f"• **🎒 낚시 가방:** `{bag_len:,}/{bag_cap:,}마리`  ·  **🐠 수족관:** `{len(u.get('tank', [])):,}/{u.get('tank_slots', 4)}칸` (시간당 `+{summary['tank_hourly']:,}🪙`)"
            )[:4096],
            color=0x0EA5E9,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="환경", description="🌤️ 현재 KST 날씨 · 피딩타임 · 어시장 시세 · 서버 보스 레이드 · 추천 어종 예보")
    async def fishing_env_cmd(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        env = fishing_core.get_current_fishing_env()
        mk = fishing_core.get_current_fish_market(env["now"])
        boss_st = await asyncio.to_thread(fishing_core.get_fishing_boss_status, interaction.guild_id or 0)
        season = fishing_core.get_current_season_meta()
        feat_sp = fishing_core.get_seasonal_featured_species(season["id"], limit=6)
        feat_txt = ", ".join(f"{s['emoji']}{s['name']}" for s in feat_sp)

        rec_lines = []
        for hab_id in ("lake", "river", "sea"):
            hab = fishing_core.HABITATS[hab_id]
            matched = [
                sp for sp in fishing_core.FISH_BY_HABITAT[hab_id]
                if sp["rarity"] >= 3
                and (sp["active_time"] in (env["time_phase"], "all"))
                and (sp["prefer_weather"] in (env["weather_id"], "all"))
            ]
            matched.sort(key=lambda x: (
                0 if fishing_core._IS_HANGUL_SP_CACHE.get(x["id"], False) else 1,
                -x["rarity"],
                -x["max_cm"],
            ))
            names = ", ".join(f"★{s['rarity']} {s['name']}" for s in matched[:5]) or "전 어종 고르게 출현"
            rec_lines.append(f"• {hab['emoji']} **{hab['name']} 추천 대물 (`{len(matched):,}종` 활발):** {names}")

        b_act = boss_st.get("active")
        boss_line = (
            f"🚨 **진행 중:** {b_act['emoji']} `{b_act['name']}` (HP `{b_act['hp']:,}/{b_act['max_hp']:,}` · `/낚시 레이드`)"
            if isinstance(b_act, dict) and not b_act.get("defeated")
            else "🌊 출현 보스 없음 (`/낚시 레이드`에서 소환 가능)"
        )

        embed = discord.Embed(
            title=f"{env['weather_emoji']} 실시간 낚시 기상 · 시세 · 보스 조황 예보 (KST)",
            description=(
                f"• **현재 시각/시간대:** `{env['now'].strftime('%Y-%m-%d %H:%M')} KST` — **{env['time_label']}**\n"
                f"• **현재 계절 (제철 보너스):** {season['emoji']} **`{season['name']}`** ({feat_txt} `+25%🪙`)\n"
                f"• **물때/피딩타임:** `{env['feeding_label']}`\n"
                f"• **현재 날씨:** {env['weather_emoji']} **`{env['weather_name']}`** (다음 날씨 변동까지 `{env['remain_str']}`)\n"
                f"> *{env['weather_desc']}*\n"
                f"• **환경 보정치:** 희귀어 확률 `×{env['weather_rare_mult'] * env['feeding_mult']:.2f}` · 크기 보정 `×{env['weather_size_mult']:.2f}`\n"
                f"• **📈 어시장 시세 ({mk['remain_str']} 남음):** {mk['headline']}\n"
                f"• **🐙 서버 보스 레이드:** {boss_line}\n\n"
                + "\n".join(rec_lines)
            )[:4096],
            color=0x38BDF8,
            timestamp=datetime.datetime.now(core.KST),
        )
        await interaction.followup.send(embed=embed)

class FishingStandaloneCog(commands.Cog):
    """/낚시랭킹 · /낚시대회 슬래시 명령어 Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="낚시랭킹", description="🏆 서버 내 물고기 최대 크기(cm)·무게(kg)·도감 순위 보드 및 랭커 상세 정보 조회")
    @app_commands.describe(
        기준="정렬 기준 (최대 길이 / 최대 무게 / 도감)",
        장소="수역 필터 (전체 / 호수 / 강 / 바다)",
    )
    @app_commands.choices(
        기준=[
            app_commands.Choice(name="📏 최대 길이 (cm)", value="length"),
            app_commands.Choice(name="⚖️ 최대 무게 (kg)", value="weight"),
            app_commands.Choice(name="📖 도감 수집왕", value="dex"),
        ],
        장소=[
            app_commands.Choice(name="🌏 전체 수역", value="all"),
            app_commands.Choice(name="🏞️ 호수 (Lake)", value="lake"),
            app_commands.Choice(name="🛶 강 (River)", value="river"),
            app_commands.Choice(name="🌊 바다 (Sea)", value="sea"),
        ],
    )
    async def slash_fishing_ranking_standalone(
        self,
        interaction: discord.Interaction,
        기준: Optional[app_commands.Choice[str]] = None,
        장소: Optional[app_commands.Choice[str]] = None,
    ):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        mode_val = 기준.value if 기준 else "length"
        hab_val = 장소.value if 장소 else "all"
        view = FishingRankingView(interaction.user, guild_id=guild_id, mode=mode_val, habitat_filter=hab_val)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="낚시대회", description="🏅 주말 자동 낚시 토너먼트 · 커스텀 번개 대회 개최 · 계절 제철 어종 보너스 및 순위 확인")
    @app_commands.describe(탭="초기 조회할 대회 탭")
    @app_commands.choices(탭=[
        app_commands.Choice(name="📊 실시간 대회 리더보드", value="live"),
        app_commands.Choice(name="🌸 계절 제철 보너스 어종 도감", value="season"),
        app_commands.Choice(name="🏛️ 역대 대회 명예의 전당", value="history"),
    ])
    async def slash_fishing_tournament(
        self,
        interaction: discord.Interaction,
        탭: Optional[app_commands.Choice[str]] = None,
    ):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        tab_val = 탭.value if 탭 else "live"
        status = await asyncio.to_thread(fishing_core.get_fishing_tournament_status, guild_id)
        view = FishingTournamentView(interaction.user, guild_id=guild_id, status=status, tab=tab_val)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg


async def setup(bot: commands.Bot):
    await bot.add_cog(FishingCog(bot))
    await bot.add_cog(FishingStandaloneCog(bot))
