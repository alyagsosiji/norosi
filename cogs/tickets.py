"""
cogs/tickets.py - 서버 1:1 비공개 문의 티켓 시스템 Cog
- /티켓 설정 [Admin]: 패널 채널 · 담당자 역할 · 카테고리 · 트랜스크립트 로그 채널 · 방식(channel/thread) · 1인당 최대 수
- /티켓 패널생성 [Admin]: 영구 지속 버튼 패널 발행 (봇 재시작 후에도 동작)
- /티켓 닫기 · /티켓 멤버추가 · /티켓 멤버제거 · /티켓 목록
- 티켓 종료 시 UTF-8 .txt 전체 대화 기록(트랜스크립트) 자동 생성 · 로그 채널 아카이브 · 개설자 DM 발송
"""

from __future__ import annotations

import asyncio
import datetime
import io
import re
import unicodedata
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

import core
import ticket_core


_CLEAR_ROLE_KEYWORDS = {"__clear__", "해제", "초기화", "없음", "제거", "clear", "none", "reset", "null"}


_INVISIBLE_FILLERS = {"\u3164", "\u115f", "\u1160", "\uffa0", "\u2800", "\u00a0", "\u3000"}
_SEPARATING_DOTS = {"\u318d", "\u119e"}


def _clean_role_invisible(text: str) -> str:
    """유니코드 호환 정규화(NFKC) + 제로너비/공백필러(ㅤ 등)/제어문자/선행 '@' 제거."""
    s = unicodedata.normalize("NFKC", str(text or ""))
    out = []
    for ch in s:
        if ch in _INVISIBLE_FILLERS:
            out.append(" ")
            continue
        cat = unicodedata.category(ch)
        # Cf: 포맷문자(\u200b 등), Cc: 제어문자, Mn: 결합부호(variation selector 등)
        if cat in ("Cf", "Cc", "Mn"):
            continue
        out.append(ch)
    cleaned = re.sub(r"\s+", " ", "".join(out)).strip()
    while cleaned.startswith("@") or cleaned.startswith("＠"):
        cleaned = cleaned[1:].strip()
    return cleaned


def _strip_role_specials(text: str) -> str:
    """특수문자·이모지·공백필러·구분선·공백을 제거하고 핵심 문자(한글/영문/숫자)만 추출합니다."""
    s = unicodedata.normalize("NFKC", str(text or ""))
    out = []
    for ch in s:
        if ch in _INVISIBLE_FILLERS or ch in _SEPARATING_DOTS:
            continue
        cat = unicodedata.category(ch)
        if cat and cat[0] in ("L", "N"):
            out.append(ch.lower())
    return "".join(out)


def _list_guild_assignable_roles(guild: Any) -> List[Any]:
    if guild is None:
        return []
    gid = getattr(guild, "id", None)
    roles = []
    for r in (getattr(guild, "roles", None) or []):
        try:
            if getattr(r, "is_default", None) and r.is_default():
                continue
        except Exception:
            pass
        if gid is not None and getattr(r, "id", None) == gid:
            continue
        roles.append(r)
    roles.sort(key=lambda r: (-int(getattr(r, "position", 0) or 0), str(getattr(r, "name", ""))))
    return roles


async def _fetch_guild_roles_safe(guild: Any) -> List[Any]:
    roles = _list_guild_assignable_roles(guild)
    if roles or guild is None or not hasattr(guild, "fetch_roles"):
        return roles
    try:
        fetched = await guild.fetch_roles()
        gid = getattr(guild, "id", None)
        res = [
            r for r in fetched
            if not (getattr(r, "is_default", None) and r.is_default()) and getattr(r, "id", None) != gid
        ]
        res.sort(key=lambda r: (-int(getattr(r, "position", 0) or 0), str(getattr(r, "name", ""))))
        return res
    except Exception:
        return roles


async def _resolve_guild_role(guild: Any, raw_query: str) -> Optional[Any]:
    """<@&ID>, 숫자 ID, 특수문자/이모지/제로너비 문자가 포함된 역할명 모두 정확하게 매칭."""
    if guild is None:
        return None
    raw = str(raw_query or "").strip()
    if not raw:
        return None

    # 1. 멘션 <@&123456> 또는 숫자 ID 직접 조회
    m_mention = re.fullmatch(r"\s*<@&(\d+)>\s*", raw)
    rid_str = m_mention.group(1) if m_mention else (raw if re.fullmatch(r"\d{5,25}", raw) else None)
    if rid_str:
        rid = int(rid_str)
        if rid != getattr(guild, "id", -1):
            role = guild.get_role(rid) if hasattr(guild, "get_role") else None
            if role is not None:
                return role
            for r in await _fetch_guild_roles_safe(guild):
                if getattr(r, "id", None) == rid:
                    return r

    roles = _list_guild_assignable_roles(guild)
    if not roles:
        roles = await _fetch_guild_roles_safe(guild)
    if not roles:
        return None

    raw_no_at = raw.lstrip("@＠").strip()
    # 2. 원본 정확 일치
    for r in roles:
        rn = str(getattr(r, "name", ""))
        if rn == raw or (raw_no_at and rn == raw_no_at):
            return r

    clean_q = _clean_role_invisible(raw).lower()
    # 3. 유니코드 정규화 + 보이지 않는 문자 제거 후 대소문자 무시 정확 일치
    if clean_q:
        for r in roles:
            if _clean_role_invisible(getattr(r, "name", "")).lower() == clean_q:
                return r

    strip_q = _strip_role_specials(raw)
    # 4. 특수문자·공백 제거 후 핵심 문자 정확 일치 (예: "담당자" -> "『★ 담당자 ★』")
    if strip_q:
        for r in roles:
            if _strip_role_specials(getattr(r, "name", "")) == strip_q:
                return r

    # 5. 부분 일치 (가장 짧고 밀접한 이름 우선)
    candidates = []
    for r in roles:
        r_name = str(getattr(r, "name", ""))
        r_clean = _clean_role_invisible(r_name).lower()
        r_strip = _strip_role_specials(r_name)
        if clean_q and clean_q in r_clean:
            candidates.append((0, len(r_clean), r))
        elif strip_q and strip_q in r_strip:
            candidates.append((1, len(r_strip), r))
    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1], -int(getattr(item[2], "position", 0) or 0)))
        return candidates[0][2]
    return None


async def _staff_role_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    guild = interaction.guild
    roles = _list_guild_assignable_roles(guild)
    q_raw = str(current or "").strip()
    q_clean = _clean_role_invisible(q_raw).lower()
    q_strip = _strip_role_specials(q_raw)

    choices: List[app_commands.Choice[str]] = []
    if not q_clean or any(k in q_clean for k in ("해제", "초기", "없음", "clear", "none")):
        choices.append(app_commands.Choice(name="🔓 담당자 역할 해제 (서버 관리자 전용)", value="__CLEAR__"))

    scored = []
    for r in roles:
        r_name = str(getattr(r, "name", ""))
        r_id = str(getattr(r, "id", ""))
        r_clean = _clean_role_invisible(r_name).lower()
        r_strip = _strip_role_specials(r_name)

        if not q_raw:
            score = (0, -int(getattr(r, "position", 0) or 0))
        elif r_clean == q_clean or (q_strip and r_strip == q_strip) or r_id == q_raw:
            score = (0, len(r_name))
        elif q_clean and q_clean in r_clean:
            score = (1, len(r_name))
        elif q_strip and q_strip in r_strip:
            score = (2, len(r_name))
        elif q_raw.isdigit() and q_raw in r_id:
            score = (3, len(r_name))
        else:
            continue
        scored.append((score, r))

    scored.sort(key=lambda it: (it[0], -int(getattr(it[1], "position", 0) or 0)))
    for _, r in scored:
        if len(choices) >= 25:
            break
        mem_cnt = len(getattr(r, "members", None) or [])
        label = f"🛡️ {str(getattr(r, 'name', '역할'))[:78]} ({mem_cnt}명)"[:100]
        choices.append(app_commands.Choice(name=label, value=str(getattr(r, "id", ""))))
    return choices[:25]


def _is_ticket_admin(member: Any, bot: Any) -> bool:
    if member is None:
        return False
    perms = getattr(member, "guild_permissions", None)
    if perms and (getattr(perms, "administrator", False) or getattr(perms, "manage_guild", False) or getattr(perms, "manage_channels", False)):
        return True
    if core.BOT_OWNER_ID and getattr(member, "id", 0) == core.BOT_OWNER_ID:
        return True
    return False


def _is_ticket_staff(member: Any, guild_id: int, bot: Any) -> bool:
    if _is_ticket_admin(member, bot):
        return True
    cfg = ticket_core.get_ticket_config(guild_id)
    staff_rid = cfg.get("staff_role_id")
    if staff_rid and member is not None:
        try:
            target_rid = int(staff_rid)
        except (TypeError, ValueError):
            return False
        roles = getattr(member, "roles", None) or []
        if any(getattr(r, "id", 0) == target_rid for r in roles):
            return True
    return False


def _build_ticket_config_embed(cfg: Dict[str, Any], guild: Optional[discord.Guild] = None) -> discord.Embed:
    p_ch = f"<#{cfg['panel_channel_id']}>" if cfg.get("panel_channel_id") else "미지정 (`/티켓 패널생성` 시 현재 채널)"
    s_rid = cfg.get("staff_role_id")
    if s_rid:
        s_role_obj = guild.get_role(int(s_rid)) if (guild and hasattr(guild, "get_role")) else None
        if s_role_obj is not None:
            safe_rname = str(getattr(s_role_obj, "name", "")).replace("`", "")
            s_role = f"<@&{s_rid}> (`{safe_rname}`)"
        else:
            s_role = f"<@&{s_rid}> (`ID: {s_rid}`)"
    else:
        s_role = "미지정 (서버 관리자 전용)"
    cat_ch = f"<#{cfg['category_id']}>" if cfg.get("category_id") else "카테고리 없음 (최상단)"
    l_ch = f"<#{cfg['log_channel_id']}>" if cfg.get("log_channel_id") else "미지정 (개설자 DM·채널에만 출력)"
    embed = discord.Embed(
        title="⚙️ 서버 1:1 티켓 시스템 설정 완료",
        description=(
            f"• **패널 채널:** {p_ch}\n"
            f"• **담당자 역할:** {s_role}\n"
            f"• **티켓 카테고리:** {cat_ch}\n"
            f"• **트랜스크립트 로그 채널:** {l_ch}\n"
            f"• **티켓 생성 방식:** `{'비공개 텍스트 채널' if cfg['mode'] == 'channel' else '비공개 스레드'}`\n"
            f"• **유저당 동시 오픈 상한:** `{cfg['max_per_user']}개` · **누적 발행:** `{cfg['counter']}건`"
        ),
        color=0x38BDF8,
        timestamp=datetime.datetime.now(core.KST),
    )
    embed.set_footer(text="아래 역할 드롭다운으로 특수문자 포함 역할을 바로 선택하거나, `/티켓 패널생성`으로 패널을 발행하세요!")
    return embed


def _build_ticket_welcome_embed(rec: Dict[str, Any], cfg: Dict[str, Any]) -> discord.Embed:
    tno = int(rec.get("ticket_no", 0) or 0)
    status = rec.get("status", "open")
    status_badge = "🟢 **진행 중 (Open)**" if status == "open" else "🔒 **종료됨 (Closed)**"
    claimed_txt = f"<@{rec['claimed_by']}> (`{rec.get('claimed_name', '')}`)" if rec.get("claimed_by") else "⏳ *대기 중 (`[🙋 담당자 접수]` 클릭)*"
    staff_txt = f"<@&{cfg['staff_role_id']}>" if cfg.get("staff_role_id") else "서버 관리자"

    embed = discord.Embed(
        title=f"🎫 1:1 문의 티켓 #{tno:04d} — {rec.get('subject', '문의')}",
        description=(
            f"안녕하세요 <@{rec.get('opener_id')}>님! 문의가 정상적으로 접수되었습니다.\n"
            f"담당 운영진({staff_txt})이 확인 후 답변해 드립니다.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **상태:** {status_badge}\n"
            f"• **개설자:** <@{rec.get('opener_id')}> (`{rec.get('opener_name', '-')}`)\n"
            f"• **담당자:** {claimed_txt}\n"
            f"• **개설 시각:** `{rec.get('created_at', '-')}`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"**📝 문의 상세 내용**\n>>> {rec.get('details', '-')}"
        )[:4096],
        color=0x22C55E if status == "open" else 0x64748B,
        timestamp=datetime.datetime.now(core.KST),
    )
    embed.set_footer(text=f"Ticket #{tno:04d} · 닫기 시 전체 대화 내역이 UTF-8 .txt 파일로 안전 아카이브됩니다.")
    return embed


async def _collect_channel_messages(channel: Any, limit: int = 500) -> List[Any]:
    msgs: List[Any] = []
    if channel is None or not hasattr(channel, "history"):
        return msgs
    try:
        async for m in channel.history(limit=limit, oldest_first=True):
            msgs.append(m)
    except Exception as e:
        print(f"⚠️ [티켓 트랜스크립트 수집 예외] {e}", flush=True)
    return msgs


async def _perform_close_ticket(
    guild: Optional[discord.Guild],
    channel: Any,
    actor: Any,
) -> tuple[bool, str, Optional[discord.Embed], Optional[discord.File]]:
    guild_id = guild.id if guild else 0
    channel_id = getattr(channel, "id", 0)
    rec_check = ticket_core.get_ticket(guild_id, channel_id)
    if not rec_check:
        return False, "❌ 이 채널은 등록된 문의 티켓 채널이 아닙니다.", None, None

    opener_id = int(rec_check.get("opener_id", 0) or 0)
    is_opener = getattr(actor, "id", 0) == opener_id
    is_staff = _is_ticket_staff(actor, guild_id, None)
    if not (is_opener or is_staff):
        return False, "❌ 티켓 개설자 또는 담당 운영진만 티켓을 닫을 수 있습니다.", None, None

    msgs = await _collect_channel_messages(channel, limit=500)
    ok, msg, closed_rec = await asyncio.to_thread(
        ticket_core.close_ticket,
        guild_id,
        channel_id,
        getattr(actor, "id", 0),
        getattr(actor, "display_name", None) or getattr(actor, "name", "관리자"),
    )
    if not ok or not closed_rec:
        return False, msg, None, None

    guild_name = getattr(guild, "name", "서버") if guild else "서버"
    filename, txt_buf = await asyncio.to_thread(
        ticket_core.format_ticket_transcript, closed_rec, guild_name, msgs
    )
    raw_bytes = txt_buf.getvalue()

    # 1. 로그 채널에 트랜스크립트 .txt 업로드
    cfg = ticket_core.get_ticket_config(guild_id)
    log_cid = cfg.get("log_channel_id")
    tno = int(closed_rec.get("ticket_no", 0) or 0)
    archive_embed = discord.Embed(
        title=f"📄 티켓 #{tno:04d} 종료 & 대화 기록 아카이브",
        description=(
            f"• **제목:** `{closed_rec.get('subject', '-')}`\n"
            f"• **개설자:** <@{opener_id}> (`{closed_rec.get('opener_name', '-')}`)\n"
            f"• **담당자:** {closed_rec.get('claimed_name') or '미지정'}\n"
            f"• **종료자:** {getattr(actor, 'display_name', '-')} (`{closed_rec.get('closed_at', '-')}`)\n"
            f"• **보존 메시지:** `{len(msgs)}개` (첨부 `.txt` 파일 확인)"
        ),
        color=0x64748B,
        timestamp=datetime.datetime.now(core.KST),
    )
    if guild and log_cid and hasattr(guild, "get_channel"):
        log_ch = guild.get_channel(int(log_cid))
        if log_ch and hasattr(log_ch, "send"):
            try:
                await log_ch.send(
                    embed=archive_embed,
                    file=discord.File(io.BytesIO(raw_bytes), filename=filename),
                )
            except Exception as le:
                print(f"⚠️ [티켓 로그 채널 전송 실패] {le}", flush=True)

    # 2. 개설자 DM 사본 발송 시도 (차단/미허용 시 무시)
    if guild and opener_id and hasattr(guild, "get_member"):
        opener_member = guild.get_member(opener_id)
        if opener_member and hasattr(opener_member, "send"):
            try:
                await opener_member.send(
                    content=f"🔒 **`{guild_name}`**의 문의 티켓 `#{tno:04d}`이(가) 종료되었습니다. 대화 내역 사본을 전달해 드립니다.",
                    file=discord.File(io.BytesIO(raw_bytes), filename=filename),
                )
            except Exception:
                pass

    # 3. 채널/스레드 잠금 및 이름 변경
    try:
        if isinstance(channel, discord.Thread):
            await channel.edit(locked=True, archived=True, reason=f"티켓 #{tno:04d} 종료")
        elif hasattr(channel, "set_permissions") and guild:
            if opener_id and hasattr(guild, "get_member"):
                op_m = guild.get_member(opener_id)
                if op_m:
                    await channel.set_permissions(op_m, view_channel=True, send_messages=False, read_message_history=True)
            for mid in closed_rec.get("members") or []:
                m_obj = guild.get_member(int(mid)) if hasattr(guild, "get_member") else None
                if m_obj:
                    await channel.set_permissions(m_obj, view_channel=True, send_messages=False, read_message_history=True)
            if hasattr(channel, "edit"):
                cur_name = getattr(channel, "name", "")
                if not cur_name.startswith("closed-"):
                    await channel.edit(name=f"closed-{tno:04d}", reason=f"티켓 #{tno:04d} 종료")
    except Exception as perm_err:
        print(f"ℹ️ [티켓 채널 잠금 예외] {perm_err}", flush=True)

    close_embed = discord.Embed(
        title=f"🔒 티켓 #{tno:04d} 이(가) 닫혔습니다",
        description=(
            f"• **처리자:** {getattr(actor, 'mention', getattr(actor, 'display_name', '-'))}\n"
            f"• **트랜스크립트:** `{filename}` ({len(msgs)}개 메시지 UTF-8 백업 완료)\n"
            "• 운영진은 아래 `[🔓 다시 열기]` 또는 `[🗑️ 티켓 삭제]` 버튼을 사용할 수 있습니다."
        ),
        color=0xEF4444,
        timestamp=datetime.datetime.now(core.KST),
    )
    return True, msg, close_embed, discord.File(io.BytesIO(raw_bytes), filename=filename)


# ==========================================
# 모달: 티켓 생성 & 멤버 추가
# ==========================================
class TicketCreateModal(core.SafeModal, title="📩 1:1 비공개 문의 티켓 작성"):
    subject = discord.ui.TextInput(
        label="문의 제목",
        placeholder="예: 역할 오류 문의 / 이벤트 제보 / 1:1 상담 요청",
        required=True,
        max_length=80,
    )
    details = discord.ui.TextInput(
        label="상세 내용",
        style=discord.TextStyle.paragraph,
        placeholder="운영진에게 전달할 구체적인 상황이나 내용을 입력해 주세요.",
        required=True,
        max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 티켓을 열 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True, thinking=True)
        allowed, err_msg, cfg = await asyncio.to_thread(
            ticket_core.can_open_ticket, guild.id, interaction.user.id
        )
        if not allowed:
            await interaction.followup.send(err_msg, ephemeral=True)
            return

        ticket_no = await asyncio.to_thread(ticket_core.reserve_next_ticket_number, guild.id)
        safe_user = re.sub(r"[^a-zA-Z0-9가-힣_-]", "", (interaction.user.name or "user"))[:12] or "user"
        ch_name = f"ticket-{ticket_no:04d}-{safe_user}".lower()

        staff_rid = cfg.get("staff_role_id")
        staff_role = guild.get_role(int(staff_rid)) if (staff_rid and hasattr(guild, "get_role")) else None

        created_ch = None
        actual_mode = cfg.get("mode", "channel")
        try:
            if actual_mode == "thread":
                parent_ch = None
                if cfg.get("panel_channel_id") and hasattr(guild, "get_channel"):
                    parent_ch = guild.get_channel(int(cfg["panel_channel_id"]))
                if parent_ch is None:
                    parent_ch = interaction.channel
                if parent_ch is not None and hasattr(parent_ch, "create_thread"):
                    created_ch = await parent_ch.create_thread(
                        name=f"ticket-{ticket_no:04d}",
                        type=discord.ChannelType.private_thread,
                        invitable=False,
                        reason=f"티켓 #{ticket_no:04d} 생성 ({interaction.user})",
                    )
                    if hasattr(created_ch, "add_user"):
                        await created_ch.add_user(interaction.user)
            else:
                if hasattr(guild, "create_text_channel"):
                    overwrites: Dict[Any, discord.PermissionOverwrite] = {
                        guild.default_role: discord.PermissionOverwrite(view_channel=False),
                        interaction.user: discord.PermissionOverwrite(
                            view_channel=True,
                            send_messages=True,
                            read_message_history=True,
                            attach_files=True,
                            embed_links=True,
                        ),
                    }
                    if getattr(guild, "me", None):
                        overwrites[guild.me] = discord.PermissionOverwrite(
                            view_channel=True,
                            send_messages=True,
                            manage_channels=True,
                            manage_messages=True,
                            read_message_history=True,
                            attach_files=True,
                        )
                    if staff_role is not None:
                        overwrites[staff_role] = discord.PermissionOverwrite(
                            view_channel=True,
                            send_messages=True,
                            read_message_history=True,
                            manage_messages=True,
                            attach_files=True,
                        )
                    cat_obj = None
                    if cfg.get("category_id") and hasattr(guild, "get_channel"):
                        maybe_cat = guild.get_channel(int(cfg["category_id"]))
                        if isinstance(maybe_cat, discord.CategoryChannel):
                            cat_obj = maybe_cat
                    created_ch = await guild.create_text_channel(
                        name=ch_name,
                        category=cat_obj,
                        overwrites=overwrites,
                        topic=f"norosi 1:1 티켓 #{ticket_no:04d} | 개설자: {interaction.user} ({interaction.user.id})",
                        reason=f"티켓 #{ticket_no:04d} 생성 ({interaction.user})",
                    )
        except discord.Forbidden:
            await interaction.followup.send(
                "🚨 봇에게 채널/스레드 생성 및 권한 설정 권한(`채널 관리`)이 부족합니다. 서버 관리자에게 권한을 확인해 주세요.",
                ephemeral=True,
            )
            return
        except Exception as e:
            await interaction.followup.send(f"⚠️ 티켓 채널 생성 중 오류가 발생했습니다: `{e}`", ephemeral=True)
            return

        if created_ch is None:
            await interaction.followup.send("⚠️ 이 환경에서는 티켓 채널을 생성할 수 없습니다.", ephemeral=True)
            return

        rec = await asyncio.to_thread(
            ticket_core.register_ticket,
            guild.id,
            created_ch.id,
            interaction.user.id,
            interaction.user.display_name,
            self.subject.value,
            self.details.value,
            ticket_no=ticket_no,
            mode=actual_mode,
        )
        ctrl_view = TicketControlView()
        welcome_embed = _build_ticket_welcome_embed(rec, cfg)
        ping_txt = f"{interaction.user.mention}" + (f" {staff_role.mention}" if staff_role else "")
        try:
            sent_welcome = await created_ch.send(content=ping_txt, embed=welcome_embed, view=ctrl_view)
            ctrl_view.message = sent_welcome
        except Exception as se:
            print(f"⚠️ [티켓 환영 메시지 전송 예외] {se}", flush=True)

        await interaction.followup.send(
            f"✅ **1:1 비공개 티켓 `#{ticket_no:04d}`이(가) 생성되었습니다!** ➔ <#{created_ch.id}>",
            ephemeral=True,
        )


class TicketMemberModal(core.SafeModal, title="👥 티켓에 멤버 초대"):
    member_input = discord.ui.TextInput(
        label="초대할 유저 ID 또는 @멘션",
        placeholder="예: 123456789012345678 또는 <@123456789012345678>",
        required=True,
        max_length=40,
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        channel = interaction.channel
        if not guild or not channel:
            await core.safe_send_response(interaction, "❌ 서버 티켓 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return

        rec = ticket_core.get_ticket(guild.id, channel.id)
        if not rec:
            await core.safe_send_response(interaction, "❌ 이 채널은 등록된 티켓 채널이 아닙니다.", ephemeral=True)
            return
        opener_id = int(rec.get("opener_id", 0) or 0)
        if interaction.user.id != opener_id and not _is_ticket_staff(interaction.user, guild.id, interaction.client):
            await core.safe_send_response(interaction, "❌ 티켓 개설자 또는 담당 운영진만 멤버를 초대할 수 있습니다.", ephemeral=True)
            return

        digits = re.sub(r"\D", "", self.member_input.value or "")
        if not digits:
            await core.safe_send_response(interaction, "❌ 올바른 디스코드 유저 ID를 입력해 주세요.", ephemeral=True)
            return

        target_id = int(digits)
        member = guild.get_member(target_id) if hasattr(guild, "get_member") else None
        if member is None:
            await core.safe_send_response(interaction, f"❌ 서버에서 유저 ID `{target_id}`를 찾을 수 없습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True, thinking=True)
        ok, msg = await asyncio.to_thread(ticket_core.add_ticket_member, guild.id, channel.id, member.id)
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)
            return

        try:
            if isinstance(channel, discord.Thread) and hasattr(channel, "add_user"):
                await channel.add_user(member)
            elif hasattr(channel, "set_permissions"):
                await channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
        except Exception:
            pass

        await interaction.followup.send(f"✅ {member.mention}님을 현재 티켓에 초대했습니다!", ephemeral=True)


# ==========================================
# 영구 지속 View: 티켓 열기 패널 & 티켓 제어 버튼
# ==========================================
class TicketPanelView(core.SafeView):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📩 1:1 문의 티켓 열기",
        style=discord.ButtonStyle.primary,
        custom_id="norosi:TicketPanelView:open_ticket",
        row=0,
    )
    async def btn_open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 티켓을 열 수 있습니다.", ephemeral=True)
            return
        allowed, err_msg, _ = await asyncio.to_thread(
            ticket_core.can_open_ticket, interaction.guild.id, interaction.user.id
        )
        if not allowed:
            await core.safe_send_response(interaction, err_msg, ephemeral=True)
            return
        await interaction.response.send_modal(TicketCreateModal())


class TicketControlView(core.SafeView):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🙋 담당자 접수",
        style=discord.ButtonStyle.primary,
        custom_id="norosi:TicketControlView:btn_claim",
        row=0,
    )
    async def btn_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 티켓 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not _is_ticket_staff(interaction.user, interaction.guild.id, interaction.client):
            await core.safe_send_response(interaction, "❌ 담당자 역할 또는 서버 관리자만 티켓을 접수할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        ok, msg, rec = await asyncio.to_thread(
            ticket_core.claim_ticket,
            interaction.guild.id,
            interaction.channel.id,
            interaction.user.id,
            interaction.user.display_name,
        )
        if ok and rec:
            cfg = ticket_core.get_ticket_config(interaction.guild.id)
            await core.safe_edit_response(interaction, embed=_build_ticket_welcome_embed(rec, cfg), view=self)
        await interaction.followup.send(msg)

    @discord.ui.button(
        label="👥 멤버 추가",
        style=discord.ButtonStyle.secondary,
        custom_id="norosi:TicketControlView:btn_add_member",
        row=0,
    )
    async def btn_add_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 티켓 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not _is_ticket_staff(interaction.user, interaction.guild.id, interaction.client):
            await core.safe_send_response(interaction, "❌ 운영진만 다른 멤버를 티켓에 초대할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(TicketMemberModal())

    @discord.ui.button(
        label="🔒 티켓 닫기",
        style=discord.ButtonStyle.danger,
        custom_id="norosi:TicketControlView:btn_close",
        row=0,
    )
    async def btn_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 티켓 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        ok, msg, close_embed, txt_file = await _perform_close_ticket(
            interaction.guild, interaction.channel, interaction.user
        )
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)
            return
        if close_embed and txt_file:
            await interaction.followup.send(embed=close_embed, file=txt_file, view=self)
        else:
            await interaction.followup.send(msg)

    @discord.ui.button(
        label="🔓 다시 열기",
        style=discord.ButtonStyle.success,
        custom_id="norosi:TicketControlView:btn_reopen",
        row=1,
    )
    async def btn_reopen(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 티켓 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not _is_ticket_staff(interaction.user, interaction.guild.id, interaction.client):
            await core.safe_send_response(interaction, "❌ 운영진만 닫힌 티켓을 다시 열 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        ok, msg, rec = await asyncio.to_thread(ticket_core.reopen_ticket, interaction.guild.id, interaction.channel.id)
        if ok and rec:
            try:
                ch = interaction.channel
                if isinstance(ch, discord.Thread):
                    await ch.edit(archived=False, locked=False, reason="티켓 재개")
                elif hasattr(ch, "set_permissions"):
                    op_m = interaction.guild.get_member(int(rec.get("opener_id", 0) or 0))
                    if op_m:
                        await ch.set_permissions(op_m, view_channel=True, send_messages=True, read_message_history=True)
                    if hasattr(ch, "edit"):
                        await ch.edit(name=f"ticket-{int(rec.get('ticket_no', 0)):04d}", reason="티켓 재개")
            except Exception:
                pass
        await interaction.followup.send(msg)

    @discord.ui.button(
        label="🗑️ 티켓 삭제",
        style=discord.ButtonStyle.secondary,
        custom_id="norosi:TicketControlView:btn_delete",
        row=1,
    )
    async def btn_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 티켓 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not _is_ticket_staff(interaction.user, interaction.guild.id, interaction.client):
            await core.safe_send_response(interaction, "❌ 운영진만 티켓 채널을 삭제할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        removed = await asyncio.to_thread(ticket_core.delete_ticket_record, interaction.guild.id, interaction.channel.id)
        if not removed:
            await interaction.followup.send("❌ 등록된 티켓을 찾을 수 없습니다.", ephemeral=True)
            return
        await interaction.followup.send(f"🗑️ 티켓 `#{int(removed.get('ticket_no', 0)):04d}`을(를) 영구 삭제합니다...", ephemeral=True)
        if hasattr(interaction.channel, "delete"):
            try:
                await interaction.channel.delete(reason=f"티켓 삭제 ({interaction.user})")
            except Exception:
                pass


class TicketConfigRoleView(core.SafeView):
    """특수문자·이모지 포함 역할도 1클릭으로 선택/해제 가능한 티켓 담당자 역할 설정 뷰"""
    def __init__(self, guild_id: int = 0, author_id: int = 0):
        super().__init__(timeout=300)
        self.guild_id = int(guild_id or 0)
        self.author_id = int(author_id or 0)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if self.author_id and interaction.user.id != self.author_id:
            await core.safe_send_response(interaction, "❌ `/티켓 설정`을 호출한 관리자만 조작할 수 있습니다.", ephemeral=True)
            return False
        if not _is_ticket_admin(interaction.user, interaction.client):
            await core.safe_send_response(interaction, "❌ **서버 관리자** 권한이 필요합니다.", ephemeral=True)
            return False
        return True

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="🛡️ 담당자 역할 직접 선택 (특수문자·이모지 포함 100% 인식)",
        min_values=1,
        max_values=1,
        row=0,
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        guild = interaction.guild
        gid = self.guild_id or (guild.id if guild else 0)
        if not gid or not select.values:
            await core.safe_send_response(interaction, "❌ 서버 역할을 확인할 수 없습니다.", ephemeral=True)
            return
        picked_role = select.values[0]
        if (guild and getattr(picked_role, "id", None) == guild.id) or (getattr(picked_role, "is_default", None) and picked_role.is_default()):
            await core.safe_send_response(interaction, "❌ `@everyone` 기본 역할은 담당자 역할로 지정할 수 없습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        cfg = await asyncio.to_thread(ticket_core.update_ticket_config, gid, staff_role_id=picked_role.id)
        embed = _build_ticket_config_embed(cfg, guild)
        await core.safe_edit_response(interaction, content=f"✅ 담당자 역할을 {picked_role.mention} 로 설정했습니다!", embed=embed, view=self)

    @discord.ui.button(label="🔓 담당자 역할 해제 (관리자 전용)", style=discord.ButtonStyle.secondary, row=1)
    async def btn_clear_staff_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        gid = self.guild_id or (guild.id if guild else 0)
        if not gid:
            await core.safe_send_response(interaction, "❌ 서버 정보를 확인할 수 없습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        cfg = await asyncio.to_thread(ticket_core.update_ticket_config, gid, staff_role_id=None)
        embed = _build_ticket_config_embed(cfg, guild)
        await core.safe_edit_response(interaction, content="🔓 담당자 역할 지정을 해제했습니다. (서버 관리자만 접수 가능)", embed=embed, view=self)


# ==========================================
# Slash Command GroupCog (/티켓)
# ==========================================
class TicketGroupCog(commands.GroupCog, name="티켓", description="🎫 1:1 비공개 문의 티켓 설정 · 패널 생성 · 트랜스크립트 아카이브"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="설정", description="[관리자] 서버의 1:1 티켓 채널, 담당자 역할, 로그 채널, 방식, 최대 오픈 수를 설정합니다.")
    @app_commands.describe(
        패널채널="문의 열기 패널이 위치할 기본 채널",
        담당자역할="모든 티켓 열람·접수 권한을 가질 운영진 역할 (역할명·일부 글자·특수문자 포함·@멘션·ID·해제 지원)",
        카테고리="비공개 티켓 채널이 생성될 디스코드 카테고리",
        로그채널="티켓 종료 시 UTF-8 .txt 대화 기록이 백업될 로그 채널",
        방식="티켓 생성 방식 (비공개 채널 vs 비공개 스레드)",
        최대티켓수="유저 1명당 동시에 열 수 있는 최대 티켓 수 (1~5)",
    )
    @app_commands.autocomplete(담당자역할=_staff_role_autocomplete)
    @app_commands.choices(방식=[
        app_commands.Choice(name="📁 비공개 텍스트 채널 (권장)", value="channel"),
        app_commands.Choice(name="🧵 비공개 스레드 (Thread)", value="thread"),
    ])
    async def ticket_config_cmd(
        self,
        interaction: discord.Interaction,
        패널채널: Optional[discord.TextChannel] = None,
        담당자역할: Optional[str] = None,
        카테고리: Optional[discord.CategoryChannel] = None,
        로그채널: Optional[discord.TextChannel] = None,
        방식: Optional[app_commands.Choice[str]] = None,
        최대티켓수: Optional[app_commands.Range[int, 1, 5]] = None,
    ):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 설정할 수 있습니다.", ephemeral=True)
            return
        if not _is_ticket_admin(interaction.user, self.bot):
            await core.safe_send_response(interaction, "❌ 이 명령어는 **서버 관리자(Manage Server / Administrator)** 전용입니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        updates: Dict[str, Any] = {}
        warn_msg: Optional[str] = None
        if 패널채널 is not None:
            updates["panel_channel_id"] = 패널채널.id
        if 담당자역할 is not None:
            q_role = str(담당자역할).strip()
            if q_role.lower() in _CLEAR_ROLE_KEYWORDS:
                updates["staff_role_id"] = None
            else:
                resolved_role = await _resolve_guild_role(interaction.guild, q_role)
                if resolved_role is None:
                    safe_q = q_role.replace("`", "")[:60]
                    warn_msg = (
                        f"⚠️ 입력하신 역할 **`{safe_q}`**을(를) 서버에서 자동으로 찾지 못했습니다.\n"
                        "👉 아래 **역할 선택 드롭다운**에서 특수문자 포함 역할을 클릭해 바로 지정해 주세요!"
                    )
                else:
                    updates["staff_role_id"] = resolved_role.id
        if 카테고리 is not None:
            updates["category_id"] = 카테고리.id
        if 로그채널 is not None:
            updates["log_channel_id"] = 로그채널.id
        if 방식 is not None:
            updates["mode"] = 방식.value
        if 최대티켓수 is not None:
            updates["max_per_user"] = int(최대티켓수)

        cfg = await asyncio.to_thread(ticket_core.update_ticket_config, interaction.guild.id, **updates)
        embed = _build_ticket_config_embed(cfg, interaction.guild)
        view = TicketConfigRoleView(guild_id=interaction.guild.id, author_id=interaction.user.id)
        await interaction.followup.send(content=warn_msg, embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="패널생성", description="[관리자] 1:1 문의 티켓 열기 영구 버튼 패널을 지정 채널에 생성합니다.")
    @app_commands.describe(
        채널="패널을 게시할 채널 (미지정 시 설정된 패널 채널 또는 현재 채널)",
        제목="패널 임베드 제목",
        설명="패널 안내 문구",
    )
    async def ticket_panel_cmd(
        self,
        interaction: discord.Interaction,
        채널: Optional[discord.TextChannel] = None,
        제목: Optional[str] = None,
        설명: Optional[str] = None,
    ):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not _is_ticket_admin(interaction.user, self.bot):
            await core.safe_send_response(interaction, "❌ **서버 관리자**만 티켓 패널을 생성할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        cfg = ticket_core.get_ticket_config(interaction.guild.id)
        target_ch = 채널 or (interaction.guild.get_channel(int(cfg["panel_channel_id"])) if cfg.get("panel_channel_id") else None) or interaction.channel
        if target_ch is None or not hasattr(target_ch, "send"):
            await interaction.followup.send("❌ 패널을 게시할 텍스트 채널을 찾을 수 없습니다.", ephemeral=True)
            return

        updates: Dict[str, Any] = {"panel_channel_id": target_ch.id}
        if 제목:
            updates["panel_title"] = 제목.strip()[:120]
        if 설명:
            updates["panel_desc"] = 설명.strip()[:1500]
        cfg = await asyncio.to_thread(ticket_core.update_ticket_config, interaction.guild.id, **updates)

        panel_embed = discord.Embed(
            title=cfg["panel_title"],
            description=cfg["panel_desc"],
            color=0x5865F2,
            timestamp=datetime.datetime.now(core.KST),
        )
        panel_embed.set_footer(text=f"{interaction.guild.name} 서포트 데스크 · 유저당 최대 {cfg['max_per_user']}개 동시 개설 가능")
        view = TicketPanelView()
        msg = await target_ch.send(embed=panel_embed, view=view)
        view.message = msg
        await interaction.followup.send(f"✅ <#{target_ch.id}> 채널에 영구 티켓 패널을 생성했습니다!", ephemeral=True)

    @app_commands.command(name="닫기", description="현재 티켓을 종료하고 UTF-8 .txt 대화 기록(트랜스크립트)을 저장합니다.")
    async def ticket_close_cmd(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        ok, msg, close_embed, txt_file = await _perform_close_ticket(
            interaction.guild, interaction.channel, interaction.user
        )
        if not ok:
            await interaction.followup.send(msg, ephemeral=True)
            return
        ctrl = TicketControlView()
        if close_embed and txt_file:
            await interaction.followup.send(embed=close_embed, file=txt_file, view=ctrl)
        else:
            await interaction.followup.send(msg)

    @app_commands.command(name="멤버추가", description="[운영진] 현재 티켓 채널에 다른 서버 멤버를 초대합니다.")
    @app_commands.describe(멤버="티켓에 초대할 서버 멤버")
    async def ticket_add_member_cmd(self, interaction: discord.Interaction, 멤버: discord.Member):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not _is_ticket_staff(interaction.user, interaction.guild.id, self.bot):
            await core.safe_send_response(interaction, "❌ 운영진만 티켓 멤버를 추가할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(ticket_core.add_ticket_member, interaction.guild.id, interaction.channel.id, 멤버.id)
        if ok:
            try:
                if isinstance(interaction.channel, discord.Thread):
                    await interaction.channel.add_user(멤버)
                elif hasattr(interaction.channel, "set_permissions"):
                    await interaction.channel.set_permissions(멤버, view_channel=True, send_messages=True, read_message_history=True)
            except Exception:
                pass
        await interaction.followup.send(msg)

    @app_commands.command(name="멤버제거", description="[운영진] 현재 티켓 채널에서 추가된 멤버를 제외합니다.")
    @app_commands.describe(멤버="티켓에서 제외할 서버 멤버")
    async def ticket_remove_member_cmd(self, interaction: discord.Interaction, 멤버: discord.Member):
        if not interaction.guild or not interaction.channel:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not _is_ticket_staff(interaction.user, interaction.guild.id, self.bot):
            await core.safe_send_response(interaction, "❌ 운영진만 티켓 멤버를 제외할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction)
        ok, msg = await asyncio.to_thread(ticket_core.remove_ticket_member, interaction.guild.id, interaction.channel.id, 멤버.id)
        if ok:
            try:
                if isinstance(interaction.channel, discord.Thread):
                    await interaction.channel.remove_user(멤버)
                elif hasattr(interaction.channel, "set_permissions"):
                    await interaction.channel.set_permissions(멤버, overwrite=None)
            except Exception:
                pass
        await interaction.followup.send(msg)

    @app_commands.command(name="목록", description="[운영진] 서버의 진행 중 / 종료된 문의 티켓 목록을 확인합니다.")
    @app_commands.describe(상태="조회할 티켓 상태 필터")
    @app_commands.choices(상태=[
        app_commands.Choice(name="전체 티켓", value="all"),
        app_commands.Choice(name="🟢 진행 중 (Open)", value="open"),
        app_commands.Choice(name="🔒 종료됨 (Closed)", value="closed"),
    ])
    async def ticket_list_cmd(self, interaction: discord.Interaction, 상태: Optional[app_commands.Choice[str]] = None):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if not _is_ticket_staff(interaction.user, interaction.guild.id, self.bot):
            await core.safe_send_response(interaction, "❌ 운영진만 전체 티켓 목록을 열람할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        flt = 상태.value if 상태 else "all"
        rows = await asyncio.to_thread(ticket_core.list_guild_tickets, interaction.guild.id, flt)
        if not rows:
            await interaction.followup.send("📭 조건에 해당하는 문의 티켓이 없습니다.", ephemeral=True)
            return
        lines = []
        for r in rows[:20]:
            st_em = "🟢" if r.get("status") == "open" else "🔒"
            cl = f" · 담당: {r['claimed_name']}" if r.get("claimed_name") else ""
            lines.append(
                f"{st_em} **`#{int(r['ticket_no']):04d}`** <#{r['channel_id']}> — `{r.get('subject', '-')}` "
                f"(<@{r['opener_id']}>{cl})"
            )
        embed = discord.Embed(
            title=f"🎫 {interaction.guild.name} 티켓 현황 ({len(rows)}건)",
            description="\n".join(lines)[:4096],
            color=0x38BDF8,
            timestamp=datetime.datetime.now(core.KST),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketGroupCog(bot))
