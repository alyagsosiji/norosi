"""
ticket_core.py - 서버 1:1 문의 티켓 시스템 백엔드 엔진
서버별 티켓 설정, 순차 티켓 번호 발급, 중복/최대 오픈 제한 검증,
담당자 접수, 멤버 초대/제거, 닫기/재개, UTF-8 TXT 트랜스크립트(대화 내역) 아카이브 생성을 제공합니다.
"""

from __future__ import annotations

import copy
import datetime
import io
from typing import Any, Dict, List, Optional, Tuple

import core


DEFAULT_TICKET_CONFIG: Dict[str, Any] = {
    "panel_channel_id": None,
    "staff_role_id": None,
    "category_id": None,
    "log_channel_id": None,
    "mode": "channel",  # "channel" (비공개 텍스트 채널) | "thread" (비공개 스레드)
    "max_per_user": 2,
    "counter": 0,
    "panel_title": "📩 1:1 문의 & 서포트 티켓",
    "panel_desc": (
        "운영진과의 비공개 1:1 상담, 신고, 건의, 역할/이벤트 문의가 필요하신가요?\n"
        "아래 **`[📩 1:1 문의 티켓 열기]`** 버튼을 눌러 문의 내용을 작성하시면\n"
        "요청자와 담당 운영진만 볼 수 있는 **전용 비공개 티켓 공간**이 즉시 생성됩니다."
    ),
}


def _safe_optional_id(val: Any) -> Optional[int]:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val if val > 0 else None
    s = str(val).strip()
    if s.isdigit():
        iv = int(s)
        return iv if iv > 0 else None
    return None


def get_ticket_config(guild_id: int | str, data: Optional[dict] = None) -> Dict[str, Any]:
    if data is None:
        data = core.get_cached_data_ro()
    g_key = str(guild_id or 0)
    raw = core.safe_get_dict(data, "ticket_configs", g_key)
    cfg = copy.deepcopy(DEFAULT_TICKET_CONFIG)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if v is not None:
                cfg[k] = v
    for id_key in ("panel_channel_id", "staff_role_id", "category_id", "log_channel_id"):
        cfg[id_key] = _safe_optional_id(cfg.get(id_key))
    cfg["mode"] = "thread" if cfg.get("mode") == "thread" else "channel"
    try:
        cfg["max_per_user"] = max(1, min(5, int(cfg.get("max_per_user", 2) or 2)))
    except (TypeError, ValueError):
        cfg["max_per_user"] = 2
    try:
        cfg["counter"] = max(0, int(cfg.get("counter", 0) or 0))
    except (TypeError, ValueError):
        cfg["counter"] = 0
    return cfg


def update_ticket_config(guild_id: int | str, **updates) -> Dict[str, Any]:
    g_key = str(guild_id or 0)
    with core._DATA_LOCK:
        data = core.load_data()
        t_cfgs = core.ensure_dict_path(data, "ticket_configs")
        cur = get_ticket_config(g_key, data=data)
        for k, v in updates.items():
            if k in DEFAULT_TICKET_CONFIG:
                if k == "mode":
                    cur[k] = "thread" if v == "thread" else "channel"
                elif k == "max_per_user":
                    cur[k] = max(1, min(5, int(v or 2)))
                elif k in ("panel_channel_id", "staff_role_id", "category_id", "log_channel_id"):
                    cur[k] = _safe_optional_id(v)
                else:
                    cur[k] = v
        t_cfgs[g_key] = cur
        core.save_data(data)
        return copy.deepcopy(cur)


def count_user_open_tickets(guild_id: int | str, user_id: int | str, data: Optional[dict] = None) -> int:
    if data is None:
        data = core.get_cached_data_ro()
    g_key = str(guild_id or 0)
    u_id = int(user_id)
    g_tickets = core.safe_get_dict(data, "tickets", g_key)
    cnt = 0
    for rec in g_tickets.values():
        if isinstance(rec, dict) and rec.get("status") == "open" and int(rec.get("opener_id", 0) or 0) == u_id:
            cnt += 1
    return cnt


def can_open_ticket(guild_id: int | str, user_id: int | str) -> Tuple[bool, str, Dict[str, Any]]:
    with core._DATA_LOCK:
        data = core.get_cached_data_ro()
        cfg = get_ticket_config(guild_id, data=data)
        open_cnt = count_user_open_tickets(guild_id, user_id, data=data)
        limit = int(cfg["max_per_user"])
        if open_cnt >= limit:
            return (
                False,
                f"⚠️ 현재 열려 있는 티켓이 이미 **`{open_cnt}/{limit}개`**입니다. 기존 티켓을 닫은 뒤 새로 열어주세요!",
                cfg,
            )
        return True, "", cfg


def reserve_next_ticket_number(guild_id: int | str) -> int:
    g_key = str(guild_id or 0)
    with core._DATA_LOCK:
        data = core.load_data()
        t_cfgs = core.ensure_dict_path(data, "ticket_configs")
        cur = get_ticket_config(g_key, data=data)
        nxt = int(cur.get("counter", 0)) + 1
        cur["counter"] = nxt
        t_cfgs[g_key] = cur
        core.save_data(data)
        return nxt


def register_ticket(
    guild_id: int | str,
    channel_id: int | str,
    opener_id: int | str,
    opener_name: str,
    subject: str,
    details: str,
    *,
    ticket_no: int,
    mode: str = "channel",
    message_id: Optional[int] = None,
) -> Dict[str, Any]:
    g_key = str(guild_id or 0)
    c_key = str(channel_id)
    now_s = datetime.datetime.now(core.KST).strftime("%Y-%m-%d %H:%M:%S")
    rec = {
        "ticket_no": int(ticket_no),
        "guild_id": int(guild_id or 0),
        "channel_id": int(channel_id),
        "opener_id": int(opener_id),
        "opener_name": opener_name,
        "subject": subject.strip()[:120] or "1:1 문의",
        "details": details.strip()[:1500] or "-",
        "mode": "thread" if mode == "thread" else "channel",
        "status": "open",
        "claimed_by": None,
        "claimed_name": None,
        "members": [],
        "created_at": now_s,
        "closed_at": None,
        "closed_by": None,
        "closed_by_name": None,
        "message_id": int(message_id) if message_id else None,
    }
    with core._DATA_LOCK:
        data = core.load_data()
        g_tickets = core.ensure_dict_path(data, "tickets", g_key)
        g_tickets[c_key] = rec
        core.save_data(data)
    return copy.deepcopy(rec)


def get_ticket(guild_id: int | str, channel_id: int | str) -> Optional[Dict[str, Any]]:
    data = core.get_cached_data_ro()
    rec = core.safe_get_dict(data, "tickets", str(guild_id or 0), str(channel_id))
    return copy.deepcopy(rec) if isinstance(rec, dict) and rec else None


def claim_ticket(guild_id: int | str, channel_id: int | str, staff_id: int, staff_name: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    g_key = str(guild_id or 0)
    c_key = str(channel_id)
    with core._DATA_LOCK:
        data = core.load_data()
        g_tickets = core.ensure_dict_path(data, "tickets", g_key)
        rec = g_tickets.get(c_key)
        if not isinstance(rec, dict):
            return False, "❌ 이 채널에 등록된 티켓 정보를 찾을 수 없습니다.", None
        if rec.get("status") != "open":
            return False, "⚠️ 이미 닫힌 티켓은 접수할 수 없습니다.", rec
        rec["claimed_by"] = int(staff_id)
        rec["claimed_name"] = staff_name
        core.save_data(data)
        return True, f"🙋 **{staff_name}**님이 티켓 `#{int(rec.get('ticket_no', 0)):04d}`의 담당자로 접수했습니다!", copy.deepcopy(rec)


def add_ticket_member(guild_id: int | str, channel_id: int | str, target_id: int) -> Tuple[bool, str]:
    g_key = str(guild_id or 0)
    c_key = str(channel_id)
    with core._DATA_LOCK:
        data = core.load_data()
        g_tickets = core.ensure_dict_path(data, "tickets", g_key)
        rec = g_tickets.get(c_key)
        if not isinstance(rec, dict):
            return False, "❌ 등록된 티켓 채널이 아닙니다."
        members = [int(m) for m in (rec.get("members") or []) if str(m).isdigit()]
        if int(target_id) not in members:
            members.append(int(target_id))
        rec["members"] = members
        core.save_data(data)
        return True, f"👥 <@{target_id}>님이 티켓 멤버로 추가되었습니다."


def remove_ticket_member(guild_id: int | str, channel_id: int | str, target_id: int) -> Tuple[bool, str]:
    g_key = str(guild_id or 0)
    c_key = str(channel_id)
    with core._DATA_LOCK:
        data = core.load_data()
        g_tickets = core.ensure_dict_path(data, "tickets", g_key)
        rec = g_tickets.get(c_key)
        if not isinstance(rec, dict):
            return False, "❌ 등록된 티켓 채널이 아닙니다."
        if int(target_id) == int(rec.get("opener_id", 0) or 0):
            return False, "❌ 티켓 개설자는 제외할 수 없습니다."
        members = [int(m) for m in (rec.get("members") or []) if str(m).isdigit() and int(m) != int(target_id)]
        rec["members"] = members
        core.save_data(data)
        return True, f"👋 <@{target_id}>님이 티켓에서 제외되었습니다."


def close_ticket(guild_id: int | str, channel_id: int | str, closer_id: int, closer_name: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    g_key = str(guild_id or 0)
    c_key = str(channel_id)
    now_s = datetime.datetime.now(core.KST).strftime("%Y-%m-%d %H:%M:%S")
    with core._DATA_LOCK:
        data = core.load_data()
        g_tickets = core.ensure_dict_path(data, "tickets", g_key)
        rec = g_tickets.get(c_key)
        if not isinstance(rec, dict):
            return False, "❌ 이 채널에 등록된 티켓 정보를 찾을 수 없습니다.", None
        if rec.get("status") == "closed":
            return False, "ℹ️ 이미 닫힌 티켓입니다.", copy.deepcopy(rec)
        rec["status"] = "closed"
        rec["closed_at"] = now_s
        rec["closed_by"] = int(closer_id)
        rec["closed_by_name"] = closer_name
        core.save_data(data)
        return True, f"🔒 티켓 `#{int(rec.get('ticket_no', 0)):04d}`이(가) 닫혔습니다.", copy.deepcopy(rec)


def reopen_ticket(guild_id: int | str, channel_id: int | str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    g_key = str(guild_id or 0)
    c_key = str(channel_id)
    with core._DATA_LOCK:
        data = core.load_data()
        g_tickets = core.ensure_dict_path(data, "tickets", g_key)
        rec = g_tickets.get(c_key)
        if not isinstance(rec, dict):
            return False, "❌ 등록된 티켓이 아닙니다.", None
        rec["status"] = "open"
        rec["closed_at"] = None
        core.save_data(data)
        return True, f"🔓 티켓 `#{int(rec.get('ticket_no', 0)):04d}`이(가) 다시 열렸습니다.", copy.deepcopy(rec)


def delete_ticket_record(guild_id: int | str, channel_id: int | str) -> Optional[Dict[str, Any]]:
    g_key = str(guild_id or 0)
    c_key = str(channel_id)
    with core._DATA_LOCK:
        data = core.load_data()
        g_tickets = core.ensure_dict_path(data, "tickets", g_key)
        removed = g_tickets.pop(c_key, None)
        if removed is not None:
            core.save_data(data)
        return copy.deepcopy(removed) if isinstance(removed, dict) else None


def list_guild_tickets(guild_id: int | str, status_filter: str = "all") -> List[Dict[str, Any]]:
    data = core.get_cached_data_ro()
    g_tickets = core.safe_get_dict(data, "tickets", str(guild_id or 0))
    rows: List[Dict[str, Any]] = []
    for rec in g_tickets.values():
        if not isinstance(rec, dict):
            continue
        if status_filter != "all" and rec.get("status") != status_filter:
            continue
        rows.append(copy.deepcopy(rec))
    rows.sort(key=lambda r: -int(r.get("ticket_no", 0) or 0))
    return rows


# ==========================================
# UTF-8 TXT 트랜스크립트 아카이브 포맷터
# ==========================================
def format_ticket_transcript(
    ticket_rec: Dict[str, Any],
    guild_name: str,
    messages: List[Any],
) -> Tuple[str, io.BytesIO]:
    """
    디스코드 메시지 목록(또는 dict 목록)을 받아 UTF-8 TXT 대화 기록 파일로 포맷팅합니다.
    """
    tno = int(ticket_rec.get("ticket_no", 0) or 0)
    filename = f"ticket-{tno:04d}-transcript.txt"
    lines: List[str] = [
        "================================================================",
        f"norosi 1:1 문의 티켓 대화 기록 (Ticket #{tno:04d})",
        "================================================================",
        f"서버명     : {guild_name} (ID: {ticket_rec.get('guild_id')})",
        f"제목       : {ticket_rec.get('subject', '-')}",
        f"개설자     : {ticket_rec.get('opener_name', '-')} (ID: {ticket_rec.get('opener_id')})",
        f"담당자     : {ticket_rec.get('claimed_name') or '미지정'}",
        f"종료 처리  : {ticket_rec.get('closed_by_name') or '-'} ({ticket_rec.get('closed_at') or '-'})",
        f"개설 시각  : {ticket_rec.get('created_at', '-')}",
        f"상세 사유  : {ticket_rec.get('details', '-')}",
        "----------------------------------------------------------------",
        f"총 메시지 수: {len(messages)}개",
        "================================================================",
        "",
    ]

    for msg in messages:
        if isinstance(msg, dict):
            ts = str(msg.get("created_at") or "-")
            author = str(msg.get("author") or "알 수 없음")
            content = str(msg.get("content") or "")
            atts = msg.get("attachments") or []
            emb_cnt = int(msg.get("embeds_count") or 0)
        else:
            dt = getattr(msg, "created_at", None)
            if isinstance(dt, datetime.datetime):
                try:
                    dt_kst = dt.astimezone(core.KST)
                    ts = dt_kst.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    ts = dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                ts = "-"
            author_obj = getattr(msg, "author", None)
            author = f"{getattr(author_obj, 'display_name', '알 수 없음')} ({getattr(author_obj, 'id', '-')})"
            content = getattr(msg, "content", "") or ""
            atts = [getattr(a, "url", str(a)) for a in (getattr(msg, "attachments", None) or [])]
            emb_cnt = len(getattr(msg, "embeds", None) or [])

        body_parts = []
        if content.strip():
            body_parts.append(content.strip())
        if emb_cnt > 0:
            body_parts.append(f"[임베드 {emb_cnt}개 포함]")
        if atts:
            body_parts.append("첨부파일: " + ", ".join(str(u) for u in atts))
        text_line = " | ".join(body_parts) if body_parts else "(내용 없음)"
        lines.append(f"[{ts}] {author}: {text_line}")

    lines.append("")
    lines.append("==================== END OF TRANSCRIPT ====================")
    payload = "\n".join(lines).encode("utf-8")
    buf = io.BytesIO(payload)
    buf.seek(0)
    return filename, buf
