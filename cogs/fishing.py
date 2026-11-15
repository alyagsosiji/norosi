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
    """서식지(호수·강·바다) + 세부 탐사 구역을 단일 Select(16개 옵션)로 통합"""

    def __init__(self, parent_view: "FishingCastView"):
        self.parent_view = parent_view
        super().__init__(
            placeholder="📍 낚시터 & 세부 수역(2.2x 집중 탐사) 선택...",
            min_values=1,
            max_values=1,
            options=self._build_opts(),
            row=0,
        )

    def _build_opts(self) -> List[discord.SelectOption]:
        cur_val = f"{self.parent_view.habitat}:{self.parent_view.zone_filter}"
        opts: List[discord.SelectOption] = []
        for h_id in ("lake", "river", "sea"):
            h = fishing_core.HABITATS[h_id]
            tot_cnt = len(fishing_core.FISH_BY_HABITAT[h_id])
            val_all = f"{h_id}:all"
            opts.append(discord.SelectOption(
                label=f"{h['name']} · 전체 수역 ({tot_cnt}종)"[:95],
                value=val_all,
                description=f"{h['name']} 전 구역 고르게 출조 · {h['desc']}"[:95],
                emoji=h["emoji"],
                default=(val_all == cur_val),
            ))
            for z in fishing_core.CANONICAL_ZONES[h_id]:
                z_cnt = len(fishing_core.FISH_BY_ZONE.get((h_id, z), []))
                val_z = f"{h_id}:{z}"
                opts.append(discord.SelectOption(
                    label=f"  └ {h['name']} · {z} ({z_cnt}종)"[:95],
                    value=val_z,
                    description=f"'{z}' 어종 출현 가중치 2.2배 집중 탐사!"[:95],
                    emoji="🎯",
                    default=(val_z == cur_val),
                ))
        return opts[:25]

    def refresh(self):
        self.options = self._build_opts()

    async def callback(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        chosen_hab, chosen_zone = self.values[0].split(":", 1)
        await asyncio.to_thread(
            fishing_core.update_user_fishing_prefs,
            self.parent_view.guild_id,
            self.parent_view.user.id,
            interaction.user.display_name,
            habitat=chosen_hab,
            zone_filter=chosen_zone,
        )
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
        super().__init__(placeholder="🪱 사용할 미끼 선택...", min_values=1, max_values=1, options=opts, row=1)

    def _build_opts(self) -> List[discord.SelectOption]:
        u = self.parent_view.summary.get("user", {}) if self.parent_view.summary else {}
        cur_bait = u.get("selected_bait", "dough")
        bag_baits = u.get("baits", {})
        opts = []
        for b_id, b in fishing_core.BAITS.items():
            if b.get("unlimited"):
                qty_txt = "무제한"
            else:
                cnt = int(bag_baits.get(b_id, 0))
                qty_txt = f"보유 {cnt}개"
            opts.append(discord.SelectOption(
                label=f"{b['name']} ({qty_txt})"[:95],
                value=b_id,
                description=b["desc"][:95],
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
            await interaction.followup.send(
                f"❌ **{fishing_core.BAITS[chosen]['name']}**을(를) 보유하고 있지 않습니다! **`🛒 낚시 상점`**에서 구매해 보세요.",
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
        self.habitat = habitat or self.summary["user"]["selected_habitat"]
        self.zone_filter = zone_filter or self.summary["user"].get("selected_zone", "all")
        self.last_catch: Optional[Dict[str, Any]] = None
        self.last_catches: List[Dict[str, Any]] = []

        self.habitat_select = FishingLocationSelect(self)
        self.bait_select = FishingBaitSelect(self)
        self.add_item(self.habitat_select)
        self.add_item(self.bait_select)
        self.sync_controls(phase="idle")

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
        self.habitat = self.summary["user"]["selected_habitat"]
        self.zone_filter = self.summary["user"].get("selected_zone", "all")

    def sync_controls(self, phase: str = "idle"):
        u = self.summary["user"]
        auto_on = bool(u.get("auto_mode", False))

        # 드롭다운 최신화 (대기/입질 중에는 잠금해 혼선 차단)
        self.habitat_select.refresh()
        self.habitat_select.disabled = phase in ("waiting_bite", "biting")
        self.bait_select.refresh()
        self.bait_select.disabled = phase in ("waiting_bite", "biting")

        # 핵심 액션 버튼 상태
        if phase == "waiting_bite":
            self.btn_cast.disabled = True
            self.btn_cast.label = "🌊 입질 기다리는 중..."
            self.btn_pull.disabled = True
            self.btn_pull.style = discord.ButtonStyle.secondary
            self.btn_pull.label = "⏳ 아직 입질 전..."
            self.btn_retract.disabled = False
        elif phase == "biting":
            self.btn_cast.disabled = True
            self.btn_cast.label = "⚡ 입질 왔다!"
            self.btn_pull.disabled = False
            self.btn_pull.style = discord.ButtonStyle.success
            self.btn_pull.label = "🎣 지금 당기기! (채집)"
            self.btn_retract.disabled = False
        else:
            self.btn_cast.disabled = False
            self.btn_cast.label = "⚡ 빠른 낚시(즉시채집)" if auto_on else "🪝 찌 던지기"
            self.btn_pull.disabled = True
            self.btn_pull.style = discord.ButtonStyle.secondary
            self.btn_pull.label = "🎣 당기기 (입질 시 활성)"
            self.btn_retract.disabled = True

        self.btn_auto_toggle.label = "⏩ 자동채집: ON" if auto_on else "⏩ 자동채집: OFF"
        self.btn_auto_toggle.style = discord.ButtonStyle.primary if auto_on else discord.ButtonStyle.secondary

        # 포획 직후 처분 버튼 활성 여부 & 라벨 최신화
        pending = self._get_pending_fish_list()
        has_catch = bool(pending) and phase in ("idle", "resolved")
        if len(pending) > 1:
            self.btn_sell_last.label = f"💰 방금 잡은 {len(pending)}마리 판매"
            self.btn_tank_last.label = "🐠 수족관 전시"
            self.btn_release_last.label = f"🌊 방생 ({len(pending)}마리 +EXP)"
        else:
            self.btn_sell_last.label = "💰 방금 잡은 물고기 판매"
            self.btn_tank_last.label = "🐠 수족관 전시"
            self.btn_release_last.label = "🌊 방생(+EXP)"
        self.btn_sell_last.disabled = not has_catch
        self.btn_tank_last.disabled = not has_catch
        self.btn_release_last.disabled = not has_catch

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if not self.guild_id and interaction.guild_id:
            self.guild_id = interaction.guild_id
        if self.user and interaction.user.id != self.user.id:
            await core.safe_send_response(
                interaction,
                "❌ 본인의 낚싯대만 조작할 수 있습니다! 직접 **`/낚시 출조`**로 나만의 낚시터를 열어보세요.",
                ephemeral=True,
            )
            return False
        if not self.user:
            self.user = interaction.user
        return True

    def build_dashboard_embed(self, status_banner: Optional[str] = None, phase: str = "idle") -> discord.Embed:
        u = self.summary["user"]
        env = self.summary["env"]
        hab = fishing_core.HABITATS[self.habitat]
        rod = self.summary["rod"]
        reel = self.summary["reel"]
        net = self.summary.get("net")
        bait = self.summary["bait"]
        crystals = self.summary["crystals"]
        cur_bait_id = u.get("selected_bait", "dough")
        bait_qty_txt = "무제한" if bait.get("unlimited") else f"{core.as_dict(u.get('baits')).get(cur_bait_id, 0)}개 남음"
        net_line = (
            f"• **그물:** {net['emoji']} `{net['name']}` (1회 `{net['min_catch']}~{net['max_catch']}마리` 포획 · 희귀 `+{int(net['rare_bonus']*100)}%`)\n"
            if net
            else "• **그물:** 🚫 `미장착` *(상점 `🕸️ 그물` 탭에서 구매 시 1회 2~10마리 포획!)*\n"
        )

        color_val = hab["discord_color"]
        if phase == "biting":
            color_val = 0x22C55E
        elif phase == "waiting_bite":
            color_val = 0x0EA5E9

        title_prefix = {
            "waiting_bite": "🌊 찌를 던졌습니다! 수면을 주시하세요...",
            "biting": "⚡ 찌가 물속으로 깊이 끌려갑니다! 지금 당기세요!",
        }.get(phase, f"{hab['emoji']} {self.user.display_name}님의 낚시터 ({hab['name']})")

        zone_txt = (
            f"🎯 `{self.zone_filter}` (출현율 2.2배 집중)"
            if self.zone_filter and self.zone_filter != "all"
            else f"`전체 수역 ({len(fishing_core.FISH_BY_HABITAT[self.habitat]):,}종)`"
        )
        desc_lines = [
            f"• **현재 장소:** {hab['label']}  ·  **수역:** {zone_txt}",
            f"> *{hab['desc']}*",
            "",
            f"• **KST 시간/물때:** {env['time_label']} · `{env['feeding_label']}`",
            f"• **현재 날씨 (2시간):** {env['weather_emoji']} **`{env['weather_name']}`** *(다음 변화까지 `{env['remain_str']}` · 희귀 ×{env['weather_rare_mult']:.2f})*",
            f"> *{env['weather_desc']}*",
        ]
        if status_banner:
            desc_lines.append("")
            desc_lines.append(status_banner)

        embed = discord.Embed(
            title=title_prefix,
            description="\n".join(desc_lines)[:4096],
            color=color_val,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.add_field(
            name="🧰 장착 장비 & 미끼",
            value=(
                f"• **낚싯대:** {rod['emoji']} `{rod['name']}` (희귀 `+{int(rod['rare_bonus']*100)}%` · 판매 `+{int(rod['gold_bonus']*100)}%`)\n"
                f"• **릴:** {reel['emoji']} `{reel['name']}` (입질 허용 `{reel['window_sec']:.1f}초+유예`)\n"
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
                name="🐾 생활 버프 적용 중 (/생활 펫·요리·공동농장)",
                value="\n".join(f"• {ln}" for ln in life_lines[:4])
                + f"\n└ 통합: 쿨타임 `-{float(life_buffs.get('cooldown_reduce', 0.0)):.1f}초` · 희귀 `+{int(float(life_buffs.get('rare_bonus', 0.0))*100)}%` · 골드 `+{int(float(life_buffs.get('gold_bonus', 0.0))*100)}%`",
                inline=False,
            )
        bag_cap = fishing_core.get_bag_capacity(u)
        embed.add_field(
            name=f"💰 재화 & 낚시꾼 Lv.{u['level']}",
            value=(
                f"• **🪙 낚시 골드:** **`{u['gold']:,}🪙`**  ·  **💎 크리스탈:** **`{crystals:,}💎`**\n"
                f"• **🎒 가방:** `{len(u.get('bag', [])):,}/{bag_cap:,}마리`  ·  **📖 도감:** `{len(u.get('pokedex', {})):,}/{len(fishing_core.FISH_SPECIES_DB):,}종`  ·  **🐠 수족관:** `{len(u.get('tank', [])):,}/{u.get('tank_slots', 4)}칸`"
            ),
            inline=False,
        )
        embed.set_footer(text=f"💡 [🪝 찌 던지기] 클릭(쿨타임 {cd_note}) ➔ 입질 신호가 오면 초록색 [🎣 지금 당기세요!]를 누르세요! (모바일 지연 보정 +1.25초 적용)")
        return embed

    def build_catch_embed(self, res: Dict[str, Any]) -> discord.Embed:
        fish = res["fish"]
        sp = res["species"]
        hab = fishing_core.HABITATS[sp["habitat"]]
        rmeta = fishing_core.RARITY_META[sp["rarity"]]
        catches = res.get("catches") or []
        catch_count = int(res.get("catch_count", len(catches) or 1) or 1)
        net = res.get("net") or self.summary.get("net")

        tags = []
        if res.get("any_server_record") or res.get("new_server_len_record") or res.get("new_server_wt_record"):
            tags.append("🏆 **서버 신기록 경신!**")
        if fish.get("is_trophy") or any(c.get("fish", {}).get("is_trophy") for c in catches):
            tags.append("👑 **대물 월척!**")
        if fish.get("variant") == "golden" or any(c.get("fish", {}).get("variant") == "golden" for c in catches):
            tags.append("✨ **황금 변이(가치 2배)!**")
        if res.get("any_first_catch") or res.get("is_first_catch"):
            tags.append("🆕 **도감 첫 등록!**")
        if res.get("perfect_hook"):
            tags.append("⚡ **번개 챔질!**")
        if res.get("leveled_up"):
            tags.append(f"🆙 **낚시 Lv.{res['new_level']} 달성!**")

        tag_line = "  ·  ".join(tags) if tags else "✨ 깔끔하게 낚아 올렸습니다!"
        bait_rem = "무제한" if res["remaining_bait"] < 0 else f"{res['remaining_bait']}개 남음"

        if catch_count > 1 and catches:
            net_lbl = f"{net['emoji']} `{net['name']}`" if isinstance(net, dict) else "🕸️ 그물"
            total_gold = int(res.get("total_gold_value", sum(c["fish"]["gold"] for c in catches)))
            haul_lines = []
            for idx, c in enumerate(catches, 1):
                cf = c["fish"]
                csp = c["species"]
                crm = fishing_core.RARITY_META[csp["rarity"]]
                b_icons = ""
                if c.get("new_server_len_record") or c.get("new_server_wt_record"):
                    b_icons += "🏆"
                if cf.get("is_trophy"):
                    b_icons += "👑"
                if cf.get("variant") == "golden":
                    b_icons += "✨"
                if c.get("is_first_catch"):
                    b_icons += "🆕"
                b_suffix = f" {b_icons}" if b_icons else ""
                haul_lines.append(
                    f"`{idx:2d}.` {cf['emoji']} {crm['stars']} **{cf['name']}** — `{cf['length_cm']:.1f}cm` · `{_format_weight(cf['weight_kg'])}` · **`{cf['gold']:,}🪙`**{b_suffix}"
                )
            desc = (
                f"{tag_line}\n"
                f"• **사용 장비:** {net_lbl} (**총 `{catch_count}마리` 포획** · 1회 미끼 1개 소모)\n"
                f"• **대표 대물:** {fish['emoji']} **{fish['name']}** ({rmeta['name']} `{rmeta['full_stars']}`)\n"
                f"• **총 추정 판매가:** **`{total_gold:,}🪙`**  ·  **총 EXP:** `+{res['gain_exp']:,}`\n\n"
                "**📦 이번 투망 포획 목록**\n"
                + "\n".join(haul_lines)
            )
            title = f"{net['emoji'] if isinstance(net, dict) else '🕸️'} [{hab['name']}] 그물 포획 성공! 총 {catch_count}마리 만선!"
        else:
            desc = (
                f"{tag_line}\n\n"
                f"• **서식지:** {hab['emoji']} `{hab['name']} · {sp['sub_zone']}`\n"
                f"• **등급:** {rmeta['emoji']} **`{rmeta['name']} ({rmeta['full_stars']})`**\n"
                f"• **체장 / 무게:** **`{fish['length_cm']:.1f} cm`**  ·  **`{_format_weight(fish['weight_kg'])}`**\n"
                f"• **추정 판매가:** **`{fish['gold']:,}🪙`**  ·  **EXP:** `+{res['gain_exp']}`\n"
                f"> *{sp['desc']}*"
            )
            title = f"{fish['emoji']} [{hab['name']}] {fish['name']} ({sp['scientific_name']}) 포획 성공!"

        if res.get("bonus_reasons"):
            reasons_txt = ", ".join(res["bonus_reasons"][:5])
            if len(res["bonus_reasons"]) > 5:
                reasons_txt += f" 외 {len(res['bonus_reasons']) - 5}건"
            desc += f"\n\n💎 **크리스탈 보너스:** `+{res['crystal_bonus']:,}💎` ({reasons_txt})"
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
                f"🎒 *포획한 물고기는 이미 가방에 안전 저장되었습니다! 아래 버튼으로 즉시 판매/수족관 전시하거나 다시 출조할 수 있습니다.*"
            ),
            inline=False,
        )
        return embed

    async def _present_catch_result(
        self,
        interaction: Optional[discord.Interaction],
        message: Optional[discord.Message],
        res: Dict[str, Any],
    ):
        self.last_catch = res
        catches = res.get("catches")
        if isinstance(catches, list) and catches:
            self.last_catches = [
                c["fish"] for c in catches
                if isinstance(c, dict) and isinstance(c.get("fish"), dict)
            ]
        elif isinstance(res.get("fish"), dict):
            self.last_catches = [res["fish"]]
        else:
            self.last_catches = []
        await self.refresh_summary()
        self.sync_controls(phase="idle")
        embed = self.build_catch_embed(res)
        png_buf = await asyncio.to_thread(fishing_core.build_catch_card_bytes, res, self.user.display_name)
        png_bytes = png_buf.getvalue() if png_buf is not None else None
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
            )
            await self._present_catch_result(interaction, target_msg, res)
            return

        # 대기 단계 UI 반영
        self.sync_controls(phase="waiting_bite")
        zone_note = f" `{params.get('zone_filter')}`" if params.get("zone_filter", "all") != "all" else ""
        wait_embed = self.build_dashboard_embed(
            status_banner=f"🪝 **{fishing_core.HABITATS[params['habitat']]['name']}{zone_note}** 수면 위로 찌를 힘껏 던졌습니다! 곧 입질이 옵니다...",
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
                        f"👉 **`{params['window_sec']:.1f}초`** 안에 초록색 **`[🎣 지금 당기기! (채집)]`** 버튼을 눌러 채집하세요!"
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
                        await self.refresh_summary()
                        async with sess.lock:
                            if sess.cast_seq != my_seq or sess.phase != "idle":
                                return
                        self.sync_controls(phase="idle")
                        miss_embed = self.build_dashboard_embed(
                            status_banner="💨 **아쉽네요! 물고기가 미끼만 살짝 건드리고 도망갔습니다.** *(미끼는 소모되지 않았습니다 — 다시 `[🪝 찌 던지기]`를 눌러보세요!)*",
                            phase="idle",
                        )
                        await _safe_update_message_or_interaction(
                            interaction, self.message, embed=miss_embed, view=self, clear_attachments=True
                        )
                    except asyncio.CancelledError:
                        return
                    except Exception as ex:
                        print(f"⚠️ [낚시 입질 만료 태스크 예외] {ex}", flush=True)

                # UI에 초록색 [지금 당기기!] 버튼이 실제로 표시된 이후부터 제한시간 카운트다운 시작
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

    @discord.ui.button(label="🎣 당기기 (입질 시 활성)", style=discord.ButtonStyle.secondary, disabled=True, row=2)
    async def btn_pull(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        target_msg = interaction.message or self.message
        self.message = target_msg

        sess = _get_or_create_cast_session(self.guild_id, self.user.id)
        async with sess.lock:
            # 1. 정상 입질 중 채집 성공
            if sess.phase == "biting":
                _cancel_session_tasks(sess)
                sess.cast_seq += 1
                reaction_sec = max(0.05, time.monotonic() - sess.bite_started_at)
                sess.phase = "resolved"
                sess.updated_at = time.monotonic()
                hab_id = sess.habitat
                z_id = sess.zone_filter
                b_id = sess.bait_id
            # 2. 아직 입질 오기 전 실수로 클릭 -> 현재 낚시 세션 보존하며 부드럽게 안내
            elif sess.phase == "waiting_bite":
                await interaction.followup.send("⏳ 아직 입질이 오지 않았습니다! 초록색 버튼으로 바뀔 때까지 1~2초만 기다려 주세요.", ephemeral=True)
                return
            # 3. 봇 재시작 등으로 세션 메모리가 유실되었으나 기존 패널에 입질 경보가 떠 있던 경우 복구 채집
            else:
                emb_title = ""
                if target_msg and target_msg.embeds:
                    emb_title = f"{target_msg.embeds[0].title or ''} {target_msg.embeds[0].description or ''}"
                if "지금 당기세요" in emb_title or "입질 경보" in emb_title:
                    sess.cast_seq += 1
                    hab_id = self.habitat
                    z_id = self.zone_filter
                    b_id = self.summary["user"].get("selected_bait", "dough")
                    reaction_sec = 1.5
                    sess.phase = "resolved"
                else:
                    await self.refresh_summary()
                    self.sync_controls(phase="idle")
                    await _safe_update_message_or_interaction(
                        interaction,
                        target_msg,
                        embed=self.build_dashboard_embed(status_banner="🎣 새로운 출조를 준비했습니다! **`[🪝 찌 던지기]`**를 눌러 시작하세요."),
                        view=self,
                        clear_attachments=True,
                    )
                    await interaction.followup.send(
                        "💨 이미 입질 시간이 지나갔거나 종료된 출조입니다. **`[🪝 찌 던지기]`**로 다시 던져주세요!",
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
        )
        await self._present_catch_result(interaction, target_msg, res)

    @discord.ui.button(label="🛑 찌 회수", style=discord.ButtonStyle.danger, disabled=True, row=2)
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

    @discord.ui.button(label="⏩ 자동채집: OFF", style=discord.ButtonStyle.secondary, row=2)
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

    @discord.ui.button(label="💰 방금 잡은 물고기 판매", style=discord.ButtonStyle.success, disabled=True, row=3)
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
        await self.refresh_summary()
        self.sync_controls(phase="idle")
        await _safe_update_message_or_interaction(interaction, interaction.message or self.message, view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🐠 수족관 전시", style=discord.ButtonStyle.primary, disabled=True, row=3)
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
        await self.refresh_summary()
        self.sync_controls(phase="idle")
        await _safe_update_message_or_interaction(interaction, interaction.message or self.message, view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🌊 방생(+EXP)", style=discord.ButtonStyle.secondary, disabled=True, row=3)
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
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        view.message = msg

    @discord.ui.button(label="🏆 랭킹", style=discord.ButtonStyle.secondary, row=4)
    async def btn_open_rank(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        view = FishingRankingView(self.user, self.guild_id)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True, wait=True)
        view.message = msg


# ==========================================
# 2. 낚시 가방 (보관함 · 잠금 · 일괄판매 · 수족관 전시)
# ==========================================
class FishingBagSelect(discord.ui.Select):
    def __init__(self, parent_view: "FishingBagView"):
        self.parent_view = parent_view
        opts = self._build_opts()
        is_empty = (len(opts) == 1 and opts[0].value == "NONE")
        super().__init__(
            placeholder="🐟 여러 마리 동시 선택 가능 (잠금 · 잠금해제 · 판매 · 전시)...",
            min_values=1 if is_empty else 0,
            max_values=1 if is_empty else len(opts),
            options=opts,
            row=0,
        )
        self.disabled = is_empty

    def _build_opts(self) -> List[discord.SelectOption]:
        items = self.parent_view.get_page_items()
        if not items:
            return [discord.SelectOption(label="표시할 물고기가 없습니다", value="NONE")]
        sel_set = set(self.parent_view.selected_uids)
        opts = []
        seen_vals = set()
        for it in items[:25]:
            uid_s = str(it.get("uid") or "")[:100]
            if not uid_s or uid_s in seen_vals:
                continue
            seen_vals.add(uid_s)
            lock_icon = "🔒" if it.get("locked") else ""
            trophy_icon = "👑" if it.get("is_trophy") else ""
            hab_name = fishing_core.HABITATS.get(it.get("habitat", "lake"), fishing_core.HABITATS["lake"]).get("name", "호수")
            cm_val = float(it.get("length_cm", 0) or 0)
            wt_val = float(it.get("weight_kg", 0) or 0)
            g_val = int(it.get("gold", 0) or 0)
            r_val = int(it.get("rarity", 1) or 1)
            lbl = f"{lock_icon}{trophy_icon} ★{r_val} {it.get('name', '물고기')} ({cm_val:.1f}cm)"[:95]
            desc = f"[{hab_name}] {_format_weight(wt_val)} · 가치 {g_val:,}🪙"[:95]
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
        self.btn_clear_sel.label = f"↩️ 선택 해제 ({n_sel})" if n_sel else "↩️ 선택 해제"
        self.btn_lock_sel.disabled = (unlocked_sel == 0)
        self.btn_unlock_sel.disabled = (locked_sel == 0)
        self.btn_sell_one.disabled = not has_sel
        self.btn_sell_one.label = f"💰 선택 판매 ({n_sel})" if n_sel else "💰 선택 판매"
        self.btn_to_tank.disabled = not has_sel
        self.btn_to_tank.label = f"🐠 수족관 전시 ({n_sel})" if n_sel else "🐠 수족관 전시"

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
        bag_raw = u.get("bag", []) if isinstance(u.get("bag"), list) else []
        bag_cap = fishing_core.get_bag_capacity(u)

        total_gold = sum(int(i.get("gold", 0)) for i in filtered)
        unlocked_gold = sum(int(i.get("gold", 0)) for i in filtered if not i.get("locked"))
        unlocked_cnt = sum(1 for i in filtered if not i.get("locked"))

        sel_set = set(self.selected_uids)
        filtered_by_uid = {str(it["uid"]): it for it in filtered if it.get("uid")}
        sel_items = [filtered_by_uid[uid] for uid in self.selected_uids if uid in filtered_by_uid]
        sel_gold = sum(int(i.get("gold", 0) or 0) for i in sel_items)
        sel_summary = (
            f"• **☑️ 현재 선택:** `{len(sel_items):,}마리` (가치 `{sel_gold:,}🪙`)"
            if sel_items
            else "• **☑️ 현재 선택:** `0마리` *(드롭다운 복수 선택 또는 [☑️ 페이지 전체선택])*"
        )

        lines = []
        for idx, it in enumerate(page_items, start=self.page * self.per_page + 1):
            mark = "👉 " if str(it.get("uid") or "") in sel_set else ""
            lock_s = "🔒" if it.get("locked") else ""
            tr_s = "👑" if it.get("is_trophy") else ""
            var_s = "✨" if it.get("variant") == "golden" else ""
            hab_e = fishing_core.HABITATS.get(it.get("habitat", "lake"), fishing_core.HABITATS["lake"]).get("emoji", "🐟")
            cm_val = float(it.get("length_cm", 0) or 0)
            wt_val = float(it.get("weight_kg", 0) or 0)
            g_val = int(it.get("gold", 0) or 0)
            r_val = int(it.get("rarity", 1) or 1)
            lines.append(
                f"{mark}`{idx}.` {lock_s}{tr_s}{var_s}{hab_e} **★{r_val} {it.get('name', '물고기')}** — "
                f"`{cm_val:.1f}cm` · `{_format_weight(wt_val)}` · `{g_val:,}🪙`"
            )

        body = "\n".join(lines) if lines else "> *(조건에 맞는 물고기가 가방에 없습니다. `/낚시 출조`로 낚아 보세요!)*"
        embed = discord.Embed(
            title=f"🎒 {self.user.display_name}님의 낚시 가방 (`{len(bag_raw):,}/{bag_cap:,}마리`)",
            description=(
                f"• **보유 골드:** `{u['gold']:,}🪙`  ·  **조회 총 가치:** `{total_gold:,}🪙` (잠금제외 `{unlocked_cnt:,}마리 = {unlocked_gold:,}🪙`)\n"
                f"{sel_summary}  ·  **페이지:** `{self.page + 1} / {total_p}`\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{body}"
            )[:4096],
            color=0x38BDF8,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="🔒 ★4 이상·월척은 자동 잠금 · 드롭다운으로 여러 마리를 체크해 [🔒 선택 잠금]/[🔓 선택 잠금해제]/판매/전시 가능!")
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

    @discord.ui.button(label="☑️ 페이지 전체선택", style=discord.ButtonStyle.secondary, row=2)
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

    @discord.ui.button(label="↩️ 선택 해제", style=discord.ButtonStyle.secondary, row=2)
    async def btn_clear_sel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.selected_uids = []
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔒 선택 잠금", style=discord.ButtonStyle.secondary, row=2)
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

    @discord.ui.button(label="🔓 선택 잠금해제", style=discord.ButtonStyle.secondary, row=2)
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

    @discord.ui.button(label="💰 선택 판매", style=discord.ButtonStyle.success, row=3)
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
                await interaction.followup.send("🔒 잠금 보호 중인 물고기입니다! 먼저 **`[🔓 선택 잠금해제]`**로 잠금을 풀어주세요.", ephemeral=True)
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

    @discord.ui.button(label="🐠 수족관 전시", style=discord.ButtonStyle.primary, row=3)
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

    @discord.ui.button(label="💸 미잠금 전체 판매", style=discord.ButtonStyle.danger, row=3)
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
                description="★1 ~ ★5 모든 희귀도 어종 표시",
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
                description=f"{rm['full_stars']} 등급 어종만 필터링"[:95],
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
        )

    def _build_opts(self) -> List[discord.SelectOption]:
        tab = self.parent_view.tab
        cur_z = self.parent_view.zone_filter
        by_z = core.as_dict(self.parent_view.stats.get("by_zone"))
        opts = [
            discord.SelectOption(
                label="전체 세부 수역",
                value="all",
                description="선택된 탭의 모든 세부 수역을 표시합니다",
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
                prefix = f"{h['name']} · " if len(habs) > 1 else ""
                opts.append(discord.SelectOption(
                    label=f"{prefix}{z} ({z_stat.get('owned', 0):,}/{z_stat.get('total', 0):,}종)"[:95],
                    value=z,
                    description=f"[{h['name']}] '{z}' 서식 어종 모아보기"[:95],
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
        )

    def _build_opts(self) -> List[discord.SelectOption]:
        cur_s = self.parent_view.sort_mode
        choices = [
            ("owned_hangul", "📌 보유 어종 · 한글명 우선 (기본)", "획득한 물고기와 한국어 대표 어종을 1페이지부터 표시", "📌"),
            ("rarity_desc", "⭐ 성급 높은순 (★5 → ★1)", "전설/신화 희귀 어종부터 차례로 표시", "⭐"),
            ("size_desc", "📏 최대 체장(cm) 큰순", "가장 크게 자라는 거대어종 순으로 표시", "📏"),
            ("rarity_asc", "🔤 성급 낮은순 (★1 → ★5)", "기본 ★1 소형어부터 오름차순으로 표시", "🔤"),
        ]
        return [
            discord.SelectOption(label=lbl, value=val, description=desc, emoji=em, default=(cur_s == val))
            for val, lbl, desc, em in choices
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
                lines.append(
                    f"✅ {rm['emoji']} {prefix_hab}**★{sp['rarity']} {sp['name']}** (`{z_lbl}`) — "
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
            body = "🎣 *아직 이 조건으로 포획한 어종이 없습니다! `/낚시 출조`로 물고기를 낚아 도감을 채워보세요.*"
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
            else f"⚠️ 폴백 {self.stats['total_species']:,}종 모드 (fish_species_db.json 확인 필요)"
        )

        embed = discord.Embed(
            title=f"📖 {self.user.display_name}님의 {tab_title}",
            description=(
                f"• **전체 수집률:** **`{self.stats['owned_total']:,}/{self.stats['total_species']:,}종 ({pct:.2f}%)`**  ·  {db_badge}\n"
                f"• 🏞️ 호수 `{by_h['lake']['owned']:,}/{by_h['lake']['total']:,}`  ·  "
                f"🌊 강 `{by_h['river']['owned']:,}/{by_h['river']['total']:,}`  ·  "
                f"⚓ 바다 `{by_h['sea']['owned']:,}/{by_h['sea']['total']:,}`\n"
                f"• **필터:** `{r_label}` · `{z_label}`{q_label} (`{len(items):,}종 일치`)  ·  **페이지:** `{self.page + 1:,} / {total_p:,}`\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{body}"
            )[:4096],
            color=0x0EA5E9,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="💡 [🔍 검색] 버튼으로 한글·영문·학명 검색 및 페이지 점프, 하단 드롭다운으로 정렬/필터를 바꿀 수 있습니다.")
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
# 4. 개인 수족관 (어항 전시 · 패시브 골드 수확 · 회수)
# ==========================================
class TankWithdrawSelect(discord.ui.Select):
    def __init__(self, parent_view: "FishingAquariumView"):
        self.parent_view = parent_view
        super().__init__(placeholder="🐠 가방으로 꺼낼 어종 선택...", min_values=1, max_values=1, options=self._build_opts(), row=0)

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
            opts.append(
                discord.SelectOption(
                    label=f"★{r_val} {it.get('name', '물고기')} ({cm_val:.1f}cm)"[:95],
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
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.parent_view.build_embed(), view=self.parent_view)
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
        self.add_item(self.withdraw_select)
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
        self.btn_harvest.disabled = not is_owner
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

    def build_embed(self) -> discord.Embed:
        u = self.summary["user"]
        tank = [it for it in (u.get("tank", []) if isinstance(u.get("tank"), list) else []) if isinstance(it, dict)]
        max_slots = int(u.get("tank_slots", 4))
        pending = self.summary["tank_pending"]
        hourly = self.summary["tank_hourly"]

        lines = []
        for idx, it in enumerate(tank, start=1):
            rm = fishing_core.RARITY_META.get(int(it.get("rarity", 1) or 1), fishing_core.RARITY_META[1])
            rate = rm["tank_rate"]
            if it.get("is_trophy"):
                rate = int(rate * 1.35)
            tr_s = "👑" if it.get("is_trophy") else ""
            cm_val = float(it.get("length_cm", 0) or 0)
            wt_val = float(it.get("weight_kg", 0) or 0)
            lines.append(
                f"`{idx}.` {it.get('emoji', '🐟')} {tr_s}**★{it.get('rarity', 1)} {it.get('name', '물고기')}** — "
                f"`{cm_val:.1f}cm` · `{_format_weight(wt_val)}` (`+{rate}🪙/시간`)"
            )
        body = "\n".join(lines) if lines else "> *(아직 전시된 물고기가 없습니다! `/낚시 가방`에서 아끼는 대물을 수족관에 넣어 보세요.)*"
        next_cost = 600 + (max_slots - 4) * 500
        exp_txt = "최대 크기 달성!" if max_slots >= 20 else f"다음 확장(+2칸): `{next_cost:,}🪙`"

        return discord.Embed(
            title=f"🐠 {self.target_user.display_name}님의 프라이빗 수족관 (`{len(tank)}/{max_slots}칸`)",
            description=(
                f"• **시간당 관람 수익:** **`+{hourly:,}🪙/시간`**  ·  **수확 대기 골드:** **`+{pending:,}🪙`** *(최대 24시간 누적)*\n"
                f"• **어항 크기:** `{max_slots}/20칸` ({exp_txt})\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{body}"
            )[:4096],
            color=0x14B8A6,
            timestamp=datetime.datetime.now(core.KST),
        )

    @discord.ui.button(label="🪙 수족관 수익 수확", style=discord.ButtonStyle.success, row=1)
    async def btn_harvest(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg, _ = await asyncio.to_thread(fishing_core.harvest_tank_gold, self.guild_id, self.target_user.id)
        await self.reload()
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🏗️ 수족관 +2칸 확장", style=discord.ButtonStyle.primary, row=1)
    async def btn_expand(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(fishing_core.purchase_shop_item, self.guild_id, self.target_user.id, "tank_expand", "expand")
        await self.reload()
        self.sync_controls()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)
        await interaction.followup.send(msg, ephemeral=True)


# ==========================================
# 5. 낚시 장비 & 미끼 상점 View
# ==========================================
class FishingShopSelect(discord.ui.Select):
    def __init__(self, parent_view: "FishingShopView"):
        self.parent_view = parent_view
        super().__init__(placeholder="🛒 구매/장착할 상품 선택...", min_values=1, max_values=1, options=self._build_opts(), row=0)

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
                if b.get("unlimited"):
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
                if b.get("unlimited"):
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
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(lines)
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

        body = "\n".join(lines) if lines else "> *(아직 이 조건의 서버 낚시 기록이 없습니다. `/낚시 출조`로 첫 신기록의 주인공이 되어보세요!)*"
        embed = discord.Embed(
            title=title,
            description=body[:4096],
            color=0xF59E0B,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_footer(text="아래 드롭다운에서 특정 낚시 랭커를 선택하면 장착 장비·보유 신기록을 자세히 확인할 수 있습니다.")
        return embed

    @discord.ui.button(label="📏 최대 길이(cm)", style=discord.ButtonStyle.primary, row=0)
    async def btn_len(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.selected_ranker_id = None
        self.mode = "length"
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="⚖️ 최대 무게(kg)", style=discord.ButtonStyle.secondary, row=0)
    async def btn_wt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.selected_ranker_id = None
        self.mode = "weight"
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="📖 도감 수집왕", style=discord.ButtonStyle.secondary, row=0)
    async def btn_dex(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        self.selected_ranker_id = None
        self.mode = "dex"
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)

    @discord.ui.button(label="📍 전체장소", style=discord.ButtonStyle.secondary, row=0)
    async def btn_hab(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction)
        order = ["all", "lake", "river", "sea"]
        self.habitat_filter = order[(order.index(self.habitat_filter) + 1) % len(order)] if self.habitat_filter in order else "all"
        self.sync_buttons()
        await _safe_update_message_or_interaction(interaction, interaction.message, embed=self.build_embed(), view=self)


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


# ==========================================
# /낚시 GroupCog
# ==========================================
class FishingCog(commands.GroupCog, name="낚시", description="🏞️ 호수 · 🌊 강 · ⚓ 바다 통합 낚시 · 수족관 · 도감 · 상점 · 최대어 랭킹"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    async def _open_cast_hub(
        self,
        interaction: discord.Interaction,
        habitat_val: Optional[str] = None,
        bait_val: Optional[str] = None,
        quick_mode: Optional[bool] = None,
    ):
        await core.safe_defer(interaction)
        guild_id = interaction.guild_id or 0
        # 이전 미완료 세션이 있으면 깔끔하게 정리 (자동 세션 갱신)
        sess = _get_or_create_cast_session(guild_id, interaction.user.id)
        async with sess.lock:
            _cancel_session_tasks(sess)
            sess.cast_seq += 1
            sess.phase = "idle"
            sess.updated_at = time.monotonic()

        summary = await asyncio.to_thread(
            fishing_core.update_user_fishing_prefs,
            guild_id,
            interaction.user.id,
            interaction.user.display_name,
            habitat=habitat_val,
            bait_id=bait_val,
            auto_mode=quick_mode,
        )
        view = FishingCastView(interaction.user, guild_id=guild_id, summary=summary)
        msg = await interaction.followup.send(embed=view.build_dashboard_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="출조", description="🏞️ 호수·🌊 강·⚓ 바다로 출조해 글로벌 공개 어종 낚시 미니게임을 플레이합니다")
    @app_commands.describe(
        장소="출조할 낚시터 (호수 / 강 / 바다)",
        미끼="사용할 미끼 종류 (미선택 시 기존 설정 유지)",
        빠른모드="입질 대기 없이 바로 채집하는 자동채집 모드 여부",
    )
    @app_commands.choices(
        장소=[
            app_commands.Choice(name=f"🏞️ 호수 ({len(fishing_core.FISH_BY_HABITAT['lake']):,}종 서식)", value="lake"),
            app_commands.Choice(name=f"🌊 강 ({len(fishing_core.FISH_BY_HABITAT['river']):,}종 서식)", value="river"),
            app_commands.Choice(name=f"⚓ 바다 ({len(fishing_core.FISH_BY_HABITAT['sea']):,}종 서식)", value="sea"),
        ],
        미끼=[
            app_commands.Choice(name="🍡 기본 곡물 떡밥 (무제한)", value="dough"),
            app_commands.Choice(name="🪱 싱싱한 붉은 지렁이", value="worm"),
            app_commands.Choice(name="🦐 활력 생물 크릴새우", value="shrimp"),
            app_commands.Choice(name="🪝 메탈 지그 루어", value="lure"),
            app_commands.Choice(name="💠 야광 심해 집어 미끼", value="glow"),
            app_commands.Choice(name="✨ 황금 전설 떡밥", value="golden"),
        ],
    )
    async def fishing_cast_cmd(
        self,
        interaction: discord.Interaction,
        장소: Optional[app_commands.Choice[str]] = None,
        미끼: Optional[app_commands.Choice[str]] = None,
        빠른모드: Optional[bool] = None,
    ):
        await self._open_cast_hub(
            interaction,
            habitat_val=장소.value if 장소 else None,
            bait_val=미끼.value if 미끼 else None,
            quick_mode=빠른모드,
        )

    @app_commands.command(name="가방", description="🎒 잡은 물고기 보관함 조회 · 다중 선택 잠금/해제 · 판매 · 수족관 전시")
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

    @app_commands.command(name="도감", description=f"📖 호수·강·바다 {len(fishing_core.FISH_SPECIES_DB):,}종 글로벌 물고기 도감 & 개인 최고 기록 확인")
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

            rec_str = (
                f"✅ **획득 완료 (`{rec['count']}마리`)** — 내 최고 `{rec['max_cm']:.1f}cm` · `{_format_weight(float(rec['max_kg']))}`"
                if rec else "⬜ **아직 포획하지 못한 어종입니다.**"
            )
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

    @app_commands.command(name="수족관", description="🐠 나만의 개인 어항에 대물을 전시하고 시간당 낚시 골드 수익을 수확합니다")
    @app_commands.describe(유저="다른 멤버의 수족관 구경하기 (미지정 시 내 수족관)")
    async def fishing_aquarium_cmd(self, interaction: discord.Interaction, 유저: Optional[discord.Member] = None):
        await core.safe_defer(interaction)
        target = 유저 or interaction.user
        guild_id = interaction.guild_id or 0
        summary = await asyncio.to_thread(
            fishing_core.get_user_fishing_summary, guild_id, target.id, target.display_name
        )
        view = FishingAquariumView(interaction.user, target, guild_id, summary=summary)
        msg = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        view.message = msg

    @app_commands.command(name="상점", description="🛒 낚싯대(6티어) · 릴(5티어) · 그물(5티어·2~10마리) · 특급 미끼 · 수족관/가방(180→2,000칸) 확장 구매")
    @app_commands.describe(분류="상점 초기 카테고리")
    @app_commands.choices(분류=[
        app_commands.Choice(name="🎣 낚싯대 (Rod)", value="rod"),
        app_commands.Choice(name="🌀 릴 (Reel)", value="reel"),
        app_commands.Choice(name="🕸️ 그물 (Net · 2~10마리 포획)", value="net"),
        app_commands.Choice(name="🪱 미끼 (Bait)", value="bait"),
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

    @app_commands.command(name="프로필", description="🪪 낚시꾼 레벨·장비·미끼·도감 수집률·수족관 종합 프로필 조회")
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
        net_txt = (
            f"{net['emoji']} `{net['name']}` (1회 `{net['min_catch']}~{net['max_catch']}마리`)"
            if net
            else "🚫 `미장착` *(상점에서 그물 구매 시 2~10마리 포획)*"
        )

        pct = (stats["owned_total"] / max(1, stats["total_species"])) * 100
        by_h = stats["by_habitat"]
        bag_cap = fishing_core.get_bag_capacity(u)
        bag_len = len(u.get("bag", []) if isinstance(u.get("bag"), list) else [])
        embed = discord.Embed(
            title=f"🎣 {target.display_name}님의 낚시꾼 라이선스 (Lv.{u['level']})",
            description=(
                f"• **EXP:** `{summary['rem_exp']} / {summary['need_exp']}`  ·  **누적 포획:** `{u['total_catches']:,}마리` (👑 월척 `{u['total_trophy']:,}회`)\n"
                f"• **🪙 보유 낚시 골드:** **`{u['gold']:,}🪙`** (누적 수익 `{u['total_gold_earned']:,}🪙`)  ·  **💎 크리스탈:** **`{summary['crystals']:,}💎`**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **낚싯대:** {rod['emoji']} `{rod['name']}`\n"
                f"• **릴:** {reel['emoji']} `{reel['name']}`\n"
                f"• **그물:** {net_txt}\n"
                f"• **기본 미끼:** {bait['emoji']} `{bait['name']}`\n"
                f"• **도감 수집률:** **`{stats['owned_total']:,}/{stats['total_species']:,}종 ({pct:.2f}%)`** "
                f"(🏞️ `{by_h['lake']['owned']:,}/{by_h['lake']['total']:,}` · 🌊 `{by_h['river']['owned']:,}/{by_h['river']['total']:,}` · ⚓ `{by_h['sea']['owned']:,}/{by_h['sea']['total']:,}`)\n"
                f"• **🎒 낚시 가방:** `{bag_len:,}/{bag_cap:,}마리`  ·  **🐠 개인 수족관:** `{len(u.get('tank', [])):,}/{u.get('tank_slots', 4)}칸` (시간당 `+{summary['tank_hourly']:,}🪙`)"
            )[:4096],
            color=0x0EA5E9,
            timestamp=datetime.datetime.now(core.KST),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="환경", description="🌤️ 현재 KST 낮/밤 · 2시간 날씨 · 피딩타임 · 잘 잡히는 추천 어종 예보")
    async def fishing_env_cmd(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        env = fishing_core.get_current_fishing_env()

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

        embed = discord.Embed(
            title=f"{env['weather_emoji']} 실시간 낚시 기상 & 조황 예보 (KST)",
            description=(
                f"• **현재 시각/시간대:** `{env['now'].strftime('%Y-%m-%d %H:%M')} KST` — **{env['time_label']}**\n"
                f"• **물때/피딩타임:** `{env['feeding_label']}`\n"
                f"• **현재 날씨:** {env['weather_emoji']} **`{env['weather_name']}`** (다음 날씨 변동까지 `{env['remain_str']}`)\n"
                f"> *{env['weather_desc']}*\n"
                f"• **환경 보정치:** 희귀어 확률 `×{env['weather_rare_mult'] * env['feeding_mult']:.2f}` · 크기 보정 `×{env['weather_size_mult']:.2f}`\n\n"
                + "\n".join(rec_lines)
            )[:4096],
            color=0x38BDF8,
            timestamp=datetime.datetime.now(core.KST),
        )
        await interaction.followup.send(embed=embed)

    @commands.command(name="낚시", aliases=["fishing", "출조"])
    async def prefix_fishing(self, ctx: commands.Context, 장소: Optional[str] = None):
        """채팅창에 !낚시 [호수|강|바다] 입력 시 낚시 출조 패널을 즉시 오픈합니다"""
        hab_map = {"호수": "lake", "lake": "lake", "강": "river", "river": "river", "바다": "sea", "sea": "sea"}
        hab_val = hab_map.get((장소 or "").strip().lower())
        guild_id = ctx.guild.id if ctx.guild else 0
        summary = await asyncio.to_thread(
            fishing_core.update_user_fishing_prefs,
            guild_id,
            ctx.author.id,
            ctx.author.display_name,
            habitat=hab_val,
        )
        view = FishingCastView(ctx.author, guild_id=guild_id, summary=summary)
        msg = await ctx.send(embed=view.build_dashboard_embed(), view=view)
        view.message = msg


class FishingStandaloneCog(commands.Cog):
    """!낚시랭킹 · !대물랭킹 접두사 단축 명령어 Cog (/낚시 랭킹과 슬래시 중복 방지)"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="낚시랭킹", aliases=["fishingrank", "대물랭킹"])
    async def prefix_fishing_ranking(self, ctx: commands.Context, 장소: Optional[str] = None):
        """채팅창에 !낚시랭킹 [호수|강|바다] 입력 시 서버 대물 랭킹 보드를 즉시 출력합니다"""
        hab_map = {"호수": "lake", "lake": "lake", "강": "river", "river": "river", "바다": "sea", "sea": "sea"}
        hab_val = hab_map.get((장소 or "").strip().lower(), "all")
        guild_id = ctx.guild.id if ctx.guild else 0
        view = FishingRankingView(ctx.author, guild_id=guild_id, mode="length", habitat_filter=hab_val)
        msg = await ctx.send(embed=view.build_embed(), view=view)
        view.message = msg


async def setup(bot: commands.Bot):
    await bot.add_cog(FishingCog(bot))
    await bot.add_cog(FishingStandaloneCog(bot))
