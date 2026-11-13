import os
import io
import re
import asyncio
import datetime
import urllib.request
from typing import Optional, Union, List, Dict, Any, Tuple
import discord
from discord import app_commands
from discord.ext import commands
import core

ANNOUNCEMENT_COLORS = {
    "cyan": (discord.Color.from_rgb(0, 204, 221), "청록 (시그니처 민트)"),
    "royal_blue": (discord.Color.from_rgb(88, 101, 242), "로열블루 (클래식)"),
    "emerald": (discord.Color.from_rgb(36, 128, 70), "에메랄드그린 (안정감)"),
    "rose_pink": (discord.Color.from_rgb(235, 69, 158), "로즈핑크 (이벤트)"),
    "gold": (discord.Color.from_rgb(241, 196, 15), "골드옐로우 (점검/VIP)"),
    "dark_navy": (discord.Color.from_rgb(47, 49, 54), "다크나이트 (모던 차콜)")
}

ANNOUNCEMENT_BADGES = {
    "normal": ("📢", "OFFICIAL NOTICE", "일반 공지"),
    "urgent": ("🚨", "URGENT NOTICE", "필독 / 긴급 공지"),
    "event": ("🎉", "SPECIAL EVENT", "이벤트 & 축제"),
    "update": ("🛠️", "SYSTEM UPDATE", "시스템 점검 & 패치"),
    "rules": ("📜", "RULES & GUIDES", "서버 규정 & 수칙"),
    "reward": ("🎁", "SPECIAL REWARD", "보상 & 선물 배포")
}

ANNOUNCEMENT_TEMPLATES = {
    "maintenance": {
        "title": "시스템 정기 점검 및 업데이트 안내",
        "badge": "update",
        "color": "gold",
        "content": (
            "안녕하세요, 서버 멤버 여러분.\n"
            "더욱 쾌적하고 안정적인 환경을 제공해 드리기 위해 정기 점검 및 업데이트를 진행합니다.\n\n"
            "⏰ **점검 일시:** 2026년 00월 00일 00:00 ~ 00:00 (약 0시간 소요 예정)\n"
            "🛠️ **작업 내용:** 서버 봇 안정화, 신규 편의 기능 패치 및 데이터 최적화\n"
            "⚠️ **영향 범위:** 점검 시간 동안 일부 봇 명령어 및 서비스 이용이 일시 중단될 수 있습니다.\n\n"
            "> 작업이 예정보다 일찍 완료될 경우 즉시 재안내 드리겠습니다. 이용에 불편을 드려 죄송합니다."
        )
    },
    "rules": {
        "title": "서버 이용 수칙 및 커뮤니티 가이드라인",
        "badge": "rules",
        "color": "rose_pink",
        "content": (
            "모든 멤버가 서로를 존중하며 쾌적하게 소통할 수 있도록 기본 수칙을 준수해 주세요.\n\n"
            "1️⃣ **상호 존중:** 비방, 욕설, 차별적 언행 및 타인을 불쾌하게 하는 행동 금지\n"
            "2️⃣ **채널 목적 준수:** 각 텍스트/음성 채널의 주제에 맞는 대화 및 미디어 공유\n"
            "3️⃣ **스팸 및 홍보 금지:** 무단 광고, 초대 링크 배포, 무분별한 멘션 도배 금지\n"
            "4️⃣ **개인정보 보호:** 본인 및 타인의 민감한 개인정보 공개 주의\n\n"
            "> 수칙 위반 시 경고 및 활동 제한 조치가 취해질 수 있으니 협조 부탁드립니다."
        )
    },
    "event": {
        "title": "🎉 세카이 스페셜 이벤트 개최 안내",
        "badge": "event",
        "color": "cyan",
        "content": (
            "서버 멤버 여러분을 위한 특별한 이벤트가 시작됩니다!\n"
            "풍성한 보상과 즐거운 추억이 준비되어 있으니 많은 관심과 참여 부탁드립니다.\n\n"
            "📅 **이벤트 기간:** 2026년 00월 00일 ~ 2026년 00월 00일\n"
            "🎁 **참여 보상:** 5,000💎 크리스탈 + 전용 이벤트 한정 역할\n"
            "🎯 **참여 방법:** 이벤트 채널에 인증샷 또는 소감을 남겨주시면 자동 응모!\n\n"
            "> 세부 진행 규칙 및 일정은 이벤트 채널 핀(Pin) 메시지를 참고해 주세요."
        )
    },
    "reward": {
        "title": "🎁 출석 감사 & 깜짝 보너스 선물 배포",
        "badge": "reward",
        "color": "emerald",
        "content": (
            "항상 저희 서버와 함께해 주시는 멤버 여러분께 진심으로 감사드립니다.\n"
            "감사의 마음을 담아 모든 멤버분들께 특별 보너스를 지급해 드립니다!\n\n"
            "💎 **지급 보상:** 전원 1,000💎 크리스탈 지급\n"
            "📬 **수령 방법:** 채팅창에 `/출석체크` 입력 시 추가 보너스 자동 합산\n\n"
            "> 앞으로도 더욱 즐겁고 활기찬 세카이 커뮤니티를 만들어가겠습니다!"
        )
    },
    "notice": {
        "title": "서버 공식 소식 및 안내사항",
        "badge": "normal",
        "color": "royal_blue",
        "content": (
            "안녕하세요, 서버 멤버 여러분!\n\n"
            "서버의 중요한 소식과 안내사항을 전달해 드립니다.\n"
            "아래 세부 내용을 꼼꼼히 확인해 주시기 바랍니다.\n\n"
            "📌 **주요 안내:**\n"
            "• 내용 1: 상세 안내 사항을 입력하세요.\n"
            "• 내용 2: 필요한 세부 일정이나 지침을 입력하세요.\n\n"
            "> 추가로 궁금한 점이 있으시다면 언제든 질문 채널 또는 관리진에게 문의해 주세요."
        )
    }
}



LOG_CATEGORY_META = [
    ("mod_admin", "🛡️ Mod/Admin", "경고, 뮤트, 킥, 밴, 닉네임 변경 감지"),
    ("channels", "📢 Channels", "채널 생성, 삭제, 설정 변경 감지"),
    ("messages", "💬 Messages", "메시지 삭제, 수정, 대량 삭제 감지"),
    ("members", "👥 Members", "멤버 입·퇴장, 차단, 역할 부여/제거 감지"),
    ("voice", "🔊 Voice", "음성 채널 입장, 퇴장, 이동 감지"),
    ("roles", "🛡️ Roles", "역할 생성, 삭제, 권한 변경 감지"),
    ("server", "🌐 Server", "서버 설정 및 커스텀 이모지 변동 감지"),
]


class ServerLogCategorySelect(discord.ui.Select):
    """7대 감사 로그 카테고리를 1클릭 멀티 선택으로 즉시 켜고 끄는 드롭다운"""
    def __init__(self, parent_view: "ServerLogHubView"):
        self.parent_view = parent_view
        events = parent_view.guild_cfg.get("events", {})
        options = []
        for key, label, desc in LOG_CATEGORY_META:
            is_on = events.get(key, True)
            options.append(
                discord.SelectOption(
                    label=f"{label} ({'ON' if is_on else 'OFF'})",
                    value=key,
                    description=desc,
                    default=bool(is_on)
                )
            )
        super().__init__(
            placeholder="📋 감지할 로그 카테고리를 선택하세요 (복수 선택 가능)...",
            min_values=0,
            max_values=len(LOG_CATEGORY_META),
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, "❌ 서버 관리자만 변경할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        data = await core.asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id)
        guild_cfg = data.setdefault("server_logs", {}).setdefault(g_key, {"channel_id": None, "enabled": False})
        ev_map = guild_cfg.setdefault("events", {})

        selected_set = set(self.values)
        for key, _, _ in LOG_CATEGORY_META:
            ev_map[key] = (key in selected_set)

        await core.asyncio.to_thread(core.save_data, data)
        self.parent_view.guild_cfg = guild_cfg
        self.parent_view.refresh_select_options()
        await interaction.edit_original_response(embed=self.parent_view.build_embed(), view=self.parent_view)


class ServerLogConfigModal(core.SafeModal, title="⚙️ 서버 7대 카테고리 감사 로그 설정"):
    mod_admin_input = discord.ui.TextInput(
        label="🛡️ Mod/Admin (경고, 뮤트, 킥, 밴, 닉네임) (O/X)",
        placeholder="입력: O (활성) 또는 X (비활성)",
        default="O",
        required=True,
        max_length=5
    )
    messages_input = discord.ui.TextInput(
        label="💬 Messages (삭제, 수정, 대량삭제) (O/X)",
        placeholder="입력: O (활성) 또는 X (비활성)",
        default="O",
        required=True,
        max_length=5
    )
    members_input = discord.ui.TextInput(
        label="👥 Members (입퇴장, 차단, 역할부여/제거) (O/X)",
        placeholder="입력: O (활성) 또는 X (비활성)",
        default="O",
        required=True,
        max_length=5
    )
    voice_input = discord.ui.TextInput(
        label="🔊 Voice (음성 입장, 퇴장, 이동) (O/X)",
        placeholder="입력: O (활성) 또는 X (비활성)",
        default="O",
        required=True,
        max_length=5
    )
    infra_input = discord.ui.TextInput(
        label="📢/🛡️/🌐 채널·역할·서버 (O/X 또는 O/O/O)",
        placeholder="예: O (일괄 활성), X (일괄 비활성), 또는 O/O/X",
        default="O/O/O",
        required=True,
        max_length=15
    )

    def __init__(self, parent_view, guild_cfg: dict):
        super().__init__()
        self.parent_view = parent_view
        events = guild_cfg.get("events", {})
        self.mod_admin_input.default = "O" if events.get("mod_admin", True) else "X"
        self.messages_input.default = "O" if events.get("messages", True) else "X"
        self.members_input.default = "O" if events.get("members", True) else "X"
        self.voice_input.default = "O" if events.get("voice", True) else "X"
        c_flag = "O" if events.get("channels", True) else "X"
        r_flag = "O" if events.get("roles", True) else "X"
        s_flag = "O" if events.get("server", True) else "X"
        self.infra_input.default = f"{c_flag}/{r_flag}/{s_flag}"

    def _parse_bool(self, val: str) -> bool:
        v = (val or "").strip().upper()
        return v in ("O", "ON", "Y", "YES", "TRUE", "1", "ㅇ", "예")

    async def on_submit(self, interaction: discord.Interaction):
        await core.safe_defer(interaction, ephemeral=True)
        data = await core.asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id)
        guild_cfg = data.setdefault("server_logs", {}).setdefault(g_key, {"channel_id": None, "enabled": False})

        guild_cfg.setdefault("events", {})
        guild_cfg["events"]["mod_admin"] = self._parse_bool(self.mod_admin_input.value)
        guild_cfg["events"]["messages"] = self._parse_bool(self.messages_input.value)
        guild_cfg["events"]["members"] = self._parse_bool(self.members_input.value)
        guild_cfg["events"]["voice"] = self._parse_bool(self.voice_input.value)

        infra_raw = (self.infra_input.value or "").strip()
        parts = [p.strip() for p in re.split(r"[/,\s]+", infra_raw) if p.strip()]
        if len(parts) >= 3:
            guild_cfg["events"]["channels"] = self._parse_bool(parts[0])
            guild_cfg["events"]["roles"] = self._parse_bool(parts[1])
            guild_cfg["events"]["server"] = self._parse_bool(parts[2])
        else:
            all_infra = self._parse_bool(infra_raw)
            guild_cfg["events"]["channels"] = all_infra
            guild_cfg["events"]["roles"] = all_infra
            guild_cfg["events"]["server"] = all_infra

        await core.asyncio.to_thread(core.save_data, data)
        self.parent_view.guild_cfg = guild_cfg
        self.parent_view.refresh_select_options()
        await interaction.edit_original_response(embed=self.parent_view.build_embed(), view=self.parent_view)


class ServerLogHubView(core.SafeView):
    """서버 관리자를 위한 7대 카테고리 감사 로그 통합 설정 관리 뷰"""
    def __init__(self, guild: discord.Guild, guild_cfg: dict):
        super().__init__(timeout=600)
        self.guild = guild
        self.guild_cfg = dict(guild_cfg)
        self.category_select = ServerLogCategorySelect(self)
        self.add_item(self.category_select)

    def refresh_select_options(self):
        events = self.guild_cfg.get("events", {})
        new_opts = []
        for key, label, desc in LOG_CATEGORY_META:
            is_on = events.get(key, True)
            new_opts.append(
                discord.SelectOption(
                    label=f"{label} ({'ON' if is_on else 'OFF'})",
                    value=key,
                    description=desc,
                    default=bool(is_on)
                )
            )
        self.category_select.options = new_opts

    def build_embed(self):
        enabled = self.guild_cfg.get("enabled", False)
        ch_id = self.guild_cfg.get("channel_id")
        ch_mention = f"<#{ch_id}>" if ch_id else "*(미지정)*"
        status_str = "✅ **활성화됨**" if (enabled and ch_id) else "❌ **비활성화됨**"

        e = self.guild_cfg.get("events", {})
        mod_st = "🟢 ON" if e.get("mod_admin", True) else "🔴 OFF"
        chan_st = "🟢 ON" if e.get("channels", True) else "🔴 OFF"
        msg_st = "🟢 ON" if e.get("messages", True) else "🔴 OFF"
        mem_st = "🟢 ON" if e.get("members", True) else "🔴 OFF"
        voice_st = "🟢 ON" if e.get("voice", True) else "🔴 OFF"
        roles_st = "🟢 ON" if e.get("roles", True) else "🔴 OFF"
        server_st = "🟢 ON" if e.get("server", True) else "🔴 OFF"

        embed = discord.Embed(
            title=f"🛡️ {self.guild.name} 7대 카테고리 통합 감사 로그 설정",
            description=(
                f"📢 **로그 수신 채널:** {ch_mention}\n"
                f"⚙️ **전체 로그 상태:** {status_str}\n\n"
                "### 📋 카테고리별 감지 현황\n"
                f"• 🛡️ **Mod/Admin (제재·모더레이션·닉네임):** `{mod_st}`\n"
                f"• 📢 **Channels (채널 생성/삭제/수정):** `{chan_st}`\n"
                f"• 💬 **Messages (메시지 삭제/수정/대량삭제):** `{msg_st}`\n"
                f"• 👥 **Members (입퇴장·차단·역할지급/제거):** `{mem_st}`\n"
                f"• 🔊 **Voice (음성 입장/퇴장/이동):** `{voice_st}`\n"
                f"• 🛡️ **Roles (역할 생성/삭제/수정):** `{roles_st}`\n"
                f"• 🌐 **Server (서버 설정 및 이모지 변동):** `{server_st}`\n\n"
                "💡 **상단 드롭다운 메뉴**에서 원하는 카테고리를 체크/해제하여 1클릭으로 즉시 적용할 수 있습니다.\n"
                "*(모든 이벤트 로그에는 이용자의 고유 유저 ID가 함께 기록됩니다)*"
            ),
            color=discord.Color.from_rgb(0, 204, 221) if (enabled and ch_id) else discord.Color.dark_grey(),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text="서버 관리자(Administrator) 전용 컨트롤 보드")
        return embed

    @discord.ui.button(label="📢 현재 채널을 로그 채널로 지정", style=discord.ButtonStyle.primary, row=1)
    async def set_channel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, "❌ 서버 관리자만 변경할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        data = await core.asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id)
        guild_cfg = data.setdefault("server_logs", {}).setdefault(g_key, {"channel_id": None, "enabled": False})
        guild_cfg["channel_id"] = interaction.channel_id
        guild_cfg["enabled"] = True
        await core.asyncio.to_thread(core.save_data, data)

        self.guild_cfg = guild_cfg
        self.refresh_select_options()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="⚙️ 직접 입력 설정 (모달)", style=discord.ButtonStyle.success, row=1)
    async def config_events_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, "❌ 서버 관리자만 변경할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.send_modal(ServerLogConfigModal(self, self.guild_cfg))

    @discord.ui.button(label="❌ 서버 로그 비활성화", style=discord.ButtonStyle.danger, row=1)
    async def disable_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, "❌ 서버 관리자만 변경할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        data = await core.asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id)
        guild_cfg = data.setdefault("server_logs", {}).setdefault(g_key, {"channel_id": None, "enabled": False})
        guild_cfg["enabled"] = False
        await core.asyncio.to_thread(core.save_data, data)

        self.guild_cfg = guild_cfg
        self.refresh_select_options()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)


AUDIT_LOG_ACTION_KOREAN = {
    "guild_update": "서버 설정 변경",
    "channel_create": "채널 생성",
    "channel_update": "채널 설정 변경",
    "channel_delete": "채널 삭제",
    "overwrite_create": "채널 권한 덮어쓰기 생성",
    "overwrite_update": "채널 권한 덮어쓰기 수정",
    "overwrite_delete": "채널 권한 덮어쓰기 삭제",
    "kick": "유저 추방",
    "member_prune": "멤버 정원 정리",
    "ban": "유저 차단",
    "unban": "유저 차단 해제",
    "member_update": "멤버 정보 변경",
    "member_role_update": "멤버 역할 변경",
    "member_move": "음성 채널 이동",
    "member_disconnect": "음성 연결 끊기",
    "bot_add": "봇 서버 추가",
    "role_create": "역할 생성",
    "role_update": "역할 설정 변경",
    "role_delete": "역할 삭제",
    "invite_create": "초대 링크 생성",
    "invite_update": "초대 링크 수정",
    "invite_delete": "초대 링크 삭제",
    "webhook_create": "웹훅 생성",
    "webhook_update": "웹훅 수정",
    "webhook_delete": "웹훅 삭제",
    "emoji_create": "이모지 추가",
    "emoji_update": "이모지 수정",
    "emoji_delete": "이모지 삭제",
    "message_delete": "메시지 삭제",
    "message_bulk_delete": "메시지 대량 삭제",
    "message_pin": "메시지 고정",
    "message_unpin": "메시지 고정 해제",
    "integration_create": "통합(연동) 추가",
    "integration_update": "통합(연동) 수정",
    "integration_delete": "통합(연동) 삭제",
    "stage_instance_create": "스테이지 생성",
    "stage_instance_update": "스테이지 수정",
    "stage_instance_delete": "스테이지 삭제",
    "sticker_create": "스티커 추가",
    "sticker_update": "스티커 수정",
    "sticker_delete": "스티커 삭제",
    "scheduled_event_create": "이벤트 생성",
    "scheduled_event_update": "이벤트 수정",
    "scheduled_event_delete": "이벤트 삭제",
    "thread_create": "스레드 생성",
    "thread_update": "스레드 수정",
    "thread_delete": "스레드 삭제",
    "app_command_permission_update": "명령어 권한 변경",
    "automod_rule_create": "오토모드 규칙 생성",
    "automod_rule_update": "오토모드 규칙 수정",
    "automod_rule_delete": "오토모드 규칙 삭제",
    "automod_block_message": "오토모드 메시지 차단",
    "automod_flag_message": "오토모드 메시지 플래그",
    "automod_timeout_member": "오토모드 유저 타임아웃",
    "automod_quarantine_user": "오토모드 유저 격리",
    "soundboard_sound_create": "사운드보드 사운드 추가",
    "soundboard_sound_update": "사운드보드 사운드 수정",
    "soundboard_sound_delete": "사운드보드 사운드 삭제",
    "voice_channel_status_create": "음성 채널 상태 생성",
    "voice_channel_status_delete": "음성 채널 상태 삭제",
}

PERM_KR_MAP = {
    "administrator": "관리자",
    "manage_guild": "서버 관리",
    "manage_roles": "역할 관리",
    "manage_channels": "채널 관리",
    "kick_members": "멤버 추방",
    "ban_members": "멤버 차단",
    "create_instant_invite": "초대 링크 생성",
    "change_nickname": "별명 변경",
    "manage_nicknames": "별명 관리",
    "manage_emojis": "이모지 관리",
    "manage_emojis_and_stickers": "이모지/스티커 관리",
    "manage_webhooks": "웹훅 관리",
    "view_audit_log": "감사 로그 보기",
    "view_channel": "채널 보기",
    "view_guild_insights": "서버 인사이트 보기",
    "send_messages": "메시지 보내기",
    "send_messages_in_threads": "스레드에서 메시지 보내기",
    "create_public_threads": "공개 스레드 만들기",
    "create_private_threads": "비공개 스레드 만들기",
    "embed_links": "링크 첨부",
    "attach_files": "파일 첨부",
    "add_reactions": "반응 추가",
    "use_external_emojis": "외부 이모지 사용",
    "use_external_stickers": "외부 스티커 사용",
    "mention_everyone": "@everyone, @here 멘션",
    "manage_messages": "메시지 관리",
    "manage_threads": "스레드 관리",
    "read_message_history": "메시지 기록 보기",
    "send_tts_messages": "TTS 메시지 전송",
    "use_application_commands": "명령어(슬래시) 사용",
    "connect": "음성 연결",
    "speak": "음성 발언",
    "mute_members": "멤버 음소거",
    "deafen_members": "멤버 헤드셋 음소거",
    "move_members": "멤버 이동",
    "use_voice_activation": "음성 감지 사용",
    "priority_speaker": "우선 발언권",
    "stream": "화면 공유",
    "request_to_speak": "발언 요청",
    "manage_events": "이벤트 관리",
    "moderate_members": "멤버 타임아웃(활동 제한)",
    "send_voice_messages": "음성 메시지 전송",
    "use_soundboard": "사운드보드 사용",
    "use_external_sounds": "외부 사운드 사용",
}

VERIFICATION_LEVEL_KR = {
    discord.VerificationLevel.none: "없음 (제한 없음)",
    discord.VerificationLevel.low: "낮음 (이메일 인증 필수)",
    discord.VerificationLevel.medium: "중간 (가입 5분 경과)",
    discord.VerificationLevel.high: "높음 (서버 체류 10분 경과)",
    discord.VerificationLevel.highest: "최고 (전화번호 인증 필수)",
}

NOTIFICATION_LEVEL_KR = {
    discord.NotificationLevel.all_messages: "모든 메시지",
    discord.NotificationLevel.only_mentions: "@mentions만",
}

CONTENT_FILTER_KR = {
    discord.ContentFilter.disabled: "비활성화 (스캔 안 함)",
    discord.ContentFilter.no_role: "역할 없는 멤버만 스캔",
    discord.ContentFilter.all_members: "모든 멤버 스캔 (권장)",
}

ATTR_KR_MAP = {
    "name": "이름",
    "topic": "채널 주제",
    "rate_limit_per_user": "슬로우 모드",
    "slowmode_delay": "슬로우 모드",
    "nsfw": "연령 제한(NSFW)",
    "bitrate": "음성 비트레이트",
    "user_limit": "음성 인원 제한",
    "color": "역할 색상",
    "colour": "역할 색상",
    "hoist": "역할 멤버 분리 표시",
    "mentionable": "역할 멘션 허용",
    "permissions": "역할 권한",
    "icon": "아이콘",
    "banner": "배너",
    "splash": "초대 배경",
    "discovery_splash": "발견 배경",
    "description": "서버 설명",
    "preferred_locale": "기본 언어",
    "verification_level": "보안/인증 수준",
    "explicit_content_filter": "유해 콘텐츠 필터",
    "default_notifications": "기본 알림 설정",
    "afk_timeout": "잠수(AFK) 시간",
    "afk_channel": "잠수(AFK) 채널",
    "system_channel": "시스템 채널",
    "rules_channel": "규칙 채널",
    "public_updates_channel": "업데이트 채널",
    "mfa_level": "2단계 인증(MFA) 요구",
    "nick": "별명(닉네임)",
    "mute": "서버 음소거",
    "deaf": "서버 헤드셋 음소거",
    "communication_disabled_until": "타임아웃(활동 제한)",
    "roles": "역할 목록",
    "type": "유형",
    "vanity_url_code": "커스텀 초대 코드(Vanity)",
    "archived": "보관 상태",
    "locked": "잠금 상태",
    "invitable": "초대 가능 여부",
    "auto_archive_duration": "자동 보관 시간",
    "allow": "허용된 권한",
    "deny": "거부된 권한"
}


def format_audit_log_diff(entry: discord.AuditLogEntry) -> list[str]:
    """감사 로그 항목의 세부 변경 내역(diff)을 읽기 쉬운 한국어로 포맷팅"""
    diff_lines = []
    if not hasattr(entry, "after") or not entry.after:
        return diff_lines

    after_dict = dict(entry.after)
    before_dict = dict(entry.before) if hasattr(entry, "before") and entry.before else {}

    for attr, val in after_dict.items():
        if attr.startswith("_"):
            continue
        b_val = before_dict.get(attr)

        if attr == "name":
            diff_lines.append(f"• **이름:** `{b_val or '(없음)'}` ➡️ `{val}`")
        elif attr == "topic":
            b_top = (b_val or "(없음)")[:80]
            a_top = (val or "(없음)")[:80]
            diff_lines.append(f"• **채널 주제:** `{b_top}` ➡️ `{a_top}`")
        elif attr in ("rate_limit_per_user", "slowmode_delay"):
            diff_lines.append(f"• **슬로우 모드(느린 모드):** `{b_val or 0}초` ➡️ `{val}초`")
        elif attr == "nsfw":
            b_n = "설정" if b_val else "해제"
            a_n = "설정" if val else "해제"
            diff_lines.append(f"• **연령 제한(NSFW):** `{b_n}` ➡️ `{a_n}`")
        elif attr in ("color", "colour"):
            b_hex = f"#{b_val.value:06x}" if hasattr(b_val, "value") and b_val.value else "기본값"
            a_hex = f"#{val.value:06x}" if hasattr(val, "value") and val.value else "기본값"
            diff_lines.append(f"• **역할 색상:** `{b_hex}` ➡️ `{a_hex}`")
        elif attr == "hoist":
            b_h = "분리 표시" if b_val else "일반 표시"
            a_h = "분리 표시" if val else "일반 표시"
            diff_lines.append(f"• **멤버 목록 분리 표시:** `{b_h}` ➡️ `{a_h}`")
        elif attr == "mentionable":
            b_m = "허용" if b_val else "비허용"
            a_m = "허용" if val else "비허용"
            diff_lines.append(f"• **멘션 허용 여부:** `{b_m}` ➡️ `{a_m}`")
        elif attr == "permissions":
            if isinstance(val, discord.Permissions) and isinstance(b_val, discord.Permissions):
                granted = [PERM_KR_MAP.get(name, name) for name, p in val if p and not getattr(b_val, name, False)]
                revoked = [PERM_KR_MAP.get(name, name) for name, p in b_val if p and not getattr(val, name, False)]
                if granted:
                    diff_lines.append(f"• **➕ 새로 부여된 권한:** `{', '.join(granted)}`")
                if revoked:
                    diff_lines.append(f"• **➖ 회수/제거된 권한:** `{', '.join(revoked)}`")
            else:
                diff_lines.append("• **역할 권한(Permissions) 변경**")
        elif attr == "verification_level":
            b_vl = VERIFICATION_LEVEL_KR.get(b_val, str(b_val))
            a_vl = VERIFICATION_LEVEL_KR.get(val, str(val))
            diff_lines.append(f"• **보안/인증 수준:** `{b_vl}` ➡️ `{a_vl}`")
        elif attr == "default_notifications":
            b_dn = NOTIFICATION_LEVEL_KR.get(b_val, str(b_val))
            a_dn = NOTIFICATION_LEVEL_KR.get(val, str(val))
            diff_lines.append(f"• **기본 알림:** `{b_dn}` ➡️ `{a_dn}`")
        elif attr == "explicit_content_filter":
            b_ec = CONTENT_FILTER_KR.get(b_val, str(b_val))
            a_ec = CONTENT_FILTER_KR.get(val, str(val))
            diff_lines.append(f"• **유해 콘텐츠 필터:** `{b_ec}` ➡️ `{a_ec}`")
        elif attr == "afk_timeout":
            diff_lines.append(f"• **잠수(AFK) 시간:** `{(b_val or 0) // 60}분` ➡️ `{val // 60}분`")
        elif attr == "description":
            b_d = (b_val or "(없음)")[:80]
            a_d = (val or "(없음)")[:80]
            diff_lines.append(f"• **서버 설명:** `{b_d}` ➡️ `{a_d}`")
        elif attr == "vanity_url_code":
            diff_lines.append(f"• **커스텀 초대 코드:** `{b_val or '(없음)'}` ➡️ `{val or '(없음)'}`")
        elif attr == "roles":
            if isinstance(val, (list, tuple)):
                role_names = [f"@{r.name}" if hasattr(r, 'name') else str(r) for r in val]
                diff_lines.append(f"• **역할 목록 변경:** `{', '.join(role_names)}`")
        elif attr == "nick":
            diff_lines.append(f"• **별명(닉네임):** `{b_val or '(없음)'}` ➡️ `{val or '(없음)'}`")
        elif attr == "mute":
            diff_lines.append(f"• **서버 음소거:** `{'설정' if val else '해제'}`")
        elif attr == "deaf":
            diff_lines.append(f"• **서버 헤드셋 음소거:** `{'설정' if val else '해제'}`")
        elif attr == "communication_disabled_until":
            if val:
                ts_str = val.astimezone(core.KST).strftime('%Y-%m-%d %H:%M:%S KST') if hasattr(val, 'astimezone') else str(val)
                diff_lines.append(f"• **타임아웃(활동 제한):** `{ts_str}`까지")
            else:
                diff_lines.append("• **타임아웃(활동 제한) 해제**")
        elif attr in ("allow", "deny"):
            mode_kr = "허용" if attr == "allow" else "거부"
            if isinstance(val, discord.Permissions):
                p_list = [PERM_KR_MAP.get(name, name) for name, p in val if p]
                if p_list:
                    diff_lines.append(f"• **권한 {mode_kr}:** `{', '.join(p_list)}`")
        elif attr in ("bitrate",):
            diff_lines.append(f"• **비트레이트:** `{(b_val or 0) // 1000}kbps` ➡️ `{val // 1000}kbps`")
        elif attr in ("user_limit",):
            b_u = f"{b_val}명" if b_val else "무제한"
            a_u = f"{val}명" if val else "무제한"
            diff_lines.append(f"• **인원 제한:** `{b_u}` ➡️ `{a_u}`")
        else:
            kr_name = ATTR_KR_MAP.get(attr, attr)
            if b_val is not None:
                diff_lines.append(f"• **{kr_name}:** `{b_val}` ➡️ `{val}`")
            else:
                diff_lines.append(f"• **{kr_name}:** `{val}`")

    return diff_lines


class GithubWebhookView(core.SafeView):
    """깃허브 웹훅 연동 관리 뷰 (원클릭 테스트 알림 발송 및 연동 해제)"""
    def __init__(self, author: discord.User, channel: discord.TextChannel, bot: commands.Bot, role: Optional[discord.Role] = None):
        super().__init__(timeout=300)
        self.author = author
        self.channel = channel
        self.bot = bot
        self.role = role

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await super().interaction_check(interaction)
        if interaction.user.id != self.author.id:
            await core.safe_send_response(interaction, "❌ 연동을 설정한 관리자만 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="테스트 알림 발송", style=discord.ButtonStyle.success, emoji="🚀", row=0)
    async def send_test_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await core.safe_defer(interaction, ephemeral=True)
        sample_embed = discord.Embed(
            title="🚀 업데이트 완료: feat(core): 하드코어 스터디 및 깃허브 실시간 배포 알림 시스템 탑재",
            url="https://github.com/alyagsosiji/norosi",
            color=discord.Color.from_rgb(46, 204, 113),
            timestamp=datetime.datetime.now(core.KST)
        )
        sample_embed.description = (
            f"📦 **저장소:** [`alyagsosiji/norosi`](https://github.com/alyagsosiji/norosi)  ·  🌿 **브랜치:** `master`\n"
            f"👤 **커밋 작성자:** `{interaction.user.display_name}`  ·  🔖 **커밋:** [`7a9b1c2`](https://github.com/alyagsosiji/norosi)\n\n"
            "### 📝 커밋 상세 내용\n"
            "```feat(study): 50분 집중/10분 휴식 음성 안내 사이클 및 보라색 은하수 잔디(🟪) 지급\nfeat(github): 웹훅 연동 실시간 커밋 및 Actions 배포 알림 자동 발송```\n"
            "📂 **파일 변경:** `+15 추가` · `~4 수정` · `-0 삭제`\n"
            "🔗 [커밋 비교 및 세부 코드 변경내역 보기 (GitHub)](https://github.com/alyagsosiji/norosi)"
        )
        sample_embed.set_thumbnail(url="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png")
        sample_embed.set_footer(text="GitHub Push Event • norosi Live Deploy • 테스트 알림")

        content = self.role.mention if self.role else None
        try:
            await self.channel.send(content=content, embed=sample_embed)
            await core.safe_send_response(interaction, f"✅ {self.channel.mention} 채널로 **[🚀 업데이트 완료]** 테스트 알림이 성공적으로 발송되었습니다!", ephemeral=True)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 테스트 알림 발송 실패 (채널 메시지 전송 권한을 확인해 주세요): {e}", ephemeral=True)

    @discord.ui.button(label="연동 해제", style=discord.ButtonStyle.danger, emoji="🛑", row=0)
    async def disable_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, "❌ 관리자 권한이 필요합니다.", ephemeral=True)
            return
        data = await asyncio.to_thread(core.load_data)
        core.remove_github_webhook_config(data, interaction.guild_id)
        await asyncio.to_thread(core.save_data, data)
        for item in self.children:
            item.disabled = True
        await core.safe_send_response(interaction, "🛑 **이 서버의 GitHub 웹훅 알림 연동이 해제되었습니다.**", view=self)


GithubWebhookGuideView = GithubWebhookView


class LoggerCog(commands.Cog):
    """디스코드 7대 카테고리 시스템 활동 실시간 감지 및 유저 ID 포함 로그 Cog"""
    def __init__(self, bot):
        self.bot = bot

    def _get_log_channel(self, guild: discord.Guild, data: dict, category_key: str = None):
        if not guild:
            return None
        g_key = str(guild.id)
        log_cfg = data.get("server_logs", {}).get(g_key, {})
        if not log_cfg.get("enabled", False):
            return None
        ch_id = log_cfg.get("channel_id")
        if not ch_id:
            return None
        events_map = log_cfg.get("events", {})
        if category_key and not events_map.get(category_key, True):
            return None
        return guild.get_channel(ch_id)

    @app_commands.command(name="로그채널설정", description="[서버 관리자 전용] 7대 카테고리 실시간 감사 로그 수신 채널 및 항목을 설정합니다.")
    @app_commands.describe(
        채널="(선택) 실시간 감사 로그를 전송받을 텍스트 채널 (미지정 시 현재 설정 보드 표시)",
        상태="(선택) 로그 기능 활성화 여부 (기본: 활성화)"
    )
    @app_commands.choices(상태=[
        app_commands.Choice(name="✅ 서버 로그 활성화", value="enable"),
        app_commands.Choice(name="❌ 서버 로그 비활성화", value="disable")
    ])
    @app_commands.default_permissions(administrator=True)
    async def set_server_log_channel_cmd(
        self,
        interaction: discord.Interaction,
        채널: discord.TextChannel = None,
        상태: app_commands.Choice[str] = None
    ):
        if not interaction.guild or not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, content="❌ 이 명령어는 **서버 관리자(Administrator)**만 사용할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        data = await core.asyncio.to_thread(core.load_data)
        g_key = str(interaction.guild_id)
        logs_dict = data.setdefault("server_logs", {})
        guild_cfg = logs_dict.setdefault(g_key, {"channel_id": None, "enabled": False})

        if 채널:
            guild_cfg["channel_id"] = 채널.id
            guild_cfg["enabled"] = True

        if 상태:
            guild_cfg["enabled"] = (상태.value != "disable")

        await core.asyncio.to_thread(core.save_data, data)
        hub_view = ServerLogHubView(interaction.guild, guild_cfg)
        await interaction.followup.send(embed=hub_view.build_embed(), view=hub_view, ephemeral=True)

    @app_commands.command(name="메시지삭제", description="[서버 관리자 전용] 채널 메시지를 조건별(유저, 봇, 미디어, 키워드)로 선택하여 일괄 삭제합니다.")
    @app_commands.describe(
        개수="검사 및 삭제할 메시지 수 (1~100개)",
        유저="(선택) 특정 유저가 작성한 메시지만 삭제",
        봇만="(선택) 봇이 작성한 메시지만 삭제",
        미디어만="(선택) 사진/영상/파일 등 첨부파일이 포함된 메시지만 삭제",
        키워드="(선택) 특정 단어나 문구가 포함된 메시지만 삭제"
    )
    @app_commands.default_permissions(administrator=True)
    async def purge_messages_cmd(
        self,
        interaction: discord.Interaction,
        개수: app_commands.Range[int, 1, 100],
        유저: discord.User = None,
        봇만: bool = False,
        미디어만: bool = False,
        키워드: str = None
    ):
        if not interaction.guild or not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, content="❌ 이 명령어는 **서버 관리자(Administrator)**만 사용할 수 있습니다.", ephemeral=True)
            return

        if not isinstance(interaction.channel, (discord.TextChannel, discord.VoiceChannel, discord.Thread)):
            await core.safe_send_response(interaction, content="❌ 메시지 삭제가 가능한 텍스트 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)

        clean_keyword = 키워드.strip() if 키워드 and 키워드.strip() else None

        def check_msg(msg: discord.Message) -> bool:
            if 유저 and msg.author.id != 유저.id:
                return False
            if 봇만 and not msg.author.bot:
                return False
            if 미디어만 and not msg.attachments:
                return False
            if clean_keyword and clean_keyword.lower() not in msg.content.lower():
                return False
            return True

        try:
            deleted = await interaction.channel.purge(limit=개수, check=check_msg)
            deleted_cnt = len(deleted)

            cond_parts = []
            if 유저:
                cond_parts.append(f"• **작성 유저:** {유저.mention} (`{유저.display_name}`)")
            if 봇만:
                cond_parts.append("• **봇 메시지 전용:** `예`")
            if 미디어만:
                cond_parts.append("• **미디어/첨부파일 전용:** `예`")
            if clean_keyword:
                cond_parts.append(f"• **포함 키워드:** `{clean_keyword}`")

            cond_str = "\n".join(cond_parts) if cond_parts else "• **전체 메시지 (필터 없음)**"

            embed = discord.Embed(
                title="🧹 메시지 선택적 일괄 삭제 완료",
                description=(
                    f"📢 **채널:** {interaction.channel.mention}\n"
                    f"🗑️ **검사한 범위:** `{개수}개` 메시지 중 **`{deleted_cnt}개` 삭제 완료**\n\n"
                    f"📋 **적용된 필터 조건:**\n{cond_str}"
                ),
                color=discord.Color.from_rgb(0, 204, 221),
                timestamp=datetime.datetime.now(core.KST)
            )
            embed.set_footer(text=f"실행 관리자: {interaction.user.display_name}")

            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ 봇에게 `메시지 관리(Manage Messages)` 권한이 없어 메시지를 삭제할 수 없습니다.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 메시지 삭제 실행 중 오류가 발생했습니다: {e}", ephemeral=True)

    # ==========================================
    # 테마 5 - 2: /공지발송 [서버 관리자 전용] (가독성 & 디자인 극대화)
    # ==========================================
    @app_commands.command(name="공지발송", description="[서버 관리자 전용] 세련된 디자인과 템플릿, 실시간 미리보기를 지원하는 고품격 공지 발송 스튜디오")
    @app_commands.describe(
        채널="(선택) 공지를 게시할 텍스트 채널 (미지정 시 현재 채널)",
        중요도="(선택) 공지 배지 및 중요도 (📢 일반 / 🚨 필독 / 🎉 이벤트 / 🛠️ 점검 / 📜 규칙 / 🎁 보상)",
        멘션="(선택) 공지 알림 멘션 대상 (없음 / @everyone / @here)",
        테마색상="(선택) 공지 임베드 테두리 색상 (청록 / 로열블루 / 에메랄드 / 핑크 / 골드 / 네이비)",
        제목="(선택) 공지 제목 (미입력 시 스튜디오에서 템플릿 선택 또는 모달 작성)",
        내용="(선택) 공지 상세 본문 내용 (마크다운 지원)",
        배너이미지="(선택) 공지 하단에 첨부할 이미지 파일"
    )
    @app_commands.choices(중요도=[
        app_commands.Choice(name="📢 일반 공지 (안내 및 소식)", value="normal"),
        app_commands.Choice(name="🚨 필독 / 긴급 공지 (규칙 및 필수 확인)", value="urgent"),
        app_commands.Choice(name="🎉 이벤트 & 축제 공지 (참여 및 보상)", value="event"),
        app_commands.Choice(name="🛠️ 시스템 점검 & 업데이트 안내", value="update"),
        app_commands.Choice(name="📜 서버 이용 수칙 및 규정 안내", value="rules"),
        app_commands.Choice(name="🎁 보상 및 깜짝 선물 배포 안내", value="reward")
    ])
    @app_commands.choices(멘션=[
        app_commands.Choice(name="🔕 멘션 없음 (조용히 게시)", value="none"),
        app_commands.Choice(name="🔔 @everyone (서버 전체 멘션)", value="everyone"),
        app_commands.Choice(name="💬 @here (온라인 멤버만 멘션)", value="here")
    ])
    @app_commands.choices(테마색상=[
        app_commands.Choice(name="💠 청록 (시그니처 민트)", value="cyan"),
        app_commands.Choice(name="🔷 로열블루 (클래식)", value="royal_blue"),
        app_commands.Choice(name="🌿 에메랄드그린 (안정감)", value="emerald"),
        app_commands.Choice(name="🌸 로즈핑크 (이벤트)", value="rose_pink"),
        app_commands.Choice(name="⭐ 골드옐로우 (점검/VIP)", value="gold"),
        app_commands.Choice(name="🌌 다크나이트 (모던 차콜)", value="dark_navy")
    ])
    @app_commands.default_permissions(administrator=True)
    async def announce_cmd(
        self,
        interaction: discord.Interaction,
        채널: discord.TextChannel = None,
        중요도: app_commands.Choice[str] = None,
        멘션: app_commands.Choice[str] = None,
        테마색상: app_commands.Choice[str] = None,
        제목: str = None,
        내용: str = None,
        배너이미지: discord.Attachment = None
    ):
        if not interaction.guild or not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, "❌ 이 명령어는 **서버 관리자(Administrator)**만 사용할 수 있습니다.", ephemeral=True)
            return

        target_ch = 채널 or interaction.channel
        badge_key = 중요도.value if 중요도 else "normal"
        mention_mode = 멘션.value if 멘션 else "none"
        color_key = 테마색상.value if 테마색상 else "cyan"
        banner_url = 배너이미지.url if 배너이미지 else None

        init_title = 제목.strip() if 제목 and 제목.strip() else "서버 공식 소식 및 안내사항"
        init_content = 내용.strip() if 내용 and 내용.strip() else (
            "안녕하세요, 서버 멤버 여러분!\n\n"
            "서버의 새로운 소식과 안내사항을 전달해 드립니다.\n"
            "하단의 **`[✏️ 내용/제목 수정]`** 버튼을 눌러 본문을 자유롭게 작성하시거나,\n"
            "**`[📋 추천 공지 템플릿 불러오기]`** 메뉴에서 정기 점검, 서버 규칙, 이벤트 템플릿을 선택하여 1초 만에 완성해 보세요!"
        )

        await core.safe_defer(interaction, ephemeral=True)
        preview_view = AnnouncementPreviewView(
            author=interaction.user,
            guild=interaction.guild,
            target_channel=target_ch,
            title=init_title,
            content=init_content,
            badge_key=badge_key,
            color_key=color_key,
            mention_mode=mention_mode,
            banner_url=banner_url
        )
        await interaction.followup.send(
            content=preview_view.build_preview_content(),
            embed=preview_view.build_embed(),
            view=preview_view,
            ephemeral=True
        )

    # ==========================================
    # 테마 5 - 4: /비활성유저조회 [서버 관리자 전용] (유령 멤버 탐지기)
    # ==========================================
    @app_commands.command(name="비활성유저조회", description="[서버 관리자 전용] 최근 N일간 활동(출석/채팅)이 없는 잠수/유령 멤버 목록과 리포트를 조회합니다.")
    @app_commands.describe(
        기준일수="비활성으로 판정할 최근 미활동 일수 (7일 / 14일 / 30일 / 60일 / 90일)"
    )
    @app_commands.choices(기준일수=[
        app_commands.Choice(name="⏳ 최근 7일 이상 미활동", value=7),
        app_commands.Choice(name="⏳ 최근 14일 이상 미활동", value=14),
        app_commands.Choice(name="⏳ 최근 30일 이상 미활동 (기본)", value=30),
        app_commands.Choice(name="⏳ 최근 60일 이상 미활동", value=60),
        app_commands.Choice(name="⏳ 최근 90일 이상 미활동", value=90)
    ])
    @app_commands.default_permissions(administrator=True)
    async def inactive_users_cmd(
        self,
        interaction: discord.Interaction,
        기준일수: app_commands.Choice[int] = None
    ):
        if not interaction.guild or not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, "❌ 이 명령어는 **서버 관리자(Administrator)**만 사용할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        days_threshold = 기준일수.value if 기준일수 else 30
        now_dt = datetime.datetime.now(core.KST)
        g_key = str(interaction.guild_id)

        data = await core.asyncio.to_thread(core.load_data)
        g_attendance = data.get("guild_attendance", {}).get(g_key, {})
        u_profiles = data.get("user_profiles", {})
        g_stats = data.get("server_stats", {}).get(g_key, {})
        chat_active_users = g_stats.get("active_users", {})

        # 서버 멤버 스캔 (봇 제외)
        members = [m for m in interaction.guild.members if not m.bot]
        total_members = len(members)

        inactive_list = []
        for m in members:
            m_key = str(m.id)
            last_date_str = None

            # 1. 서버 채팅 활동 기록 확인 (당일 활동 멤버는 미활동에서 제외)
            chat_count = chat_active_users.get(m_key, 0)
            if chat_count > 0:
                days_inactive = 0
                last_act_str = f"최근 채팅 활동 ({chat_count}회)"
            else:
                # 2. 서버 출석 기록 확인
                if m_key in g_attendance and isinstance(g_attendance[m_key], dict):
                    last_date_str = g_attendance[m_key].get("last_date")

                # 3. 글로벌 프로필 출석 기록 확인
                if not last_date_str and m_key in u_profiles and isinstance(u_profiles[m_key], dict):
                    att = u_profiles[m_key].get("attendance", {})
                    last_date_str = att.get("last_date")

                if last_date_str:
                    try:
                        last_dt = datetime.datetime.strptime(last_date_str, "%Y-%m-%d").replace(tzinfo=core.KST)
                        days_inactive = max(0, (now_dt.date() - last_dt.date()).days)
                        last_act_str = f"{last_date_str} (출석)"
                    except Exception:
                        days_inactive = 999
                        last_act_str = "기록 오류"
                else:
                    # 출석/채팅 기록이 전혀 없는 경우 서버 가입일 기준
                    if m.joined_at:
                        j_kst = m.joined_at.astimezone(core.KST)
                        days_inactive = max(0, (now_dt.date() - j_kst.date()).days)
                        last_act_str = f"{j_kst.strftime('%Y-%m-%d')} (가입 후 무활동)"
                    else:
                        days_inactive = 999
                        last_act_str = "활동 기록 없음"

            if days_inactive >= days_threshold:
                inactive_list.append({
                    "member": m,
                    "days_inactive": days_inactive,
                    "last_activity_str": last_act_str
                })

        # 미활동 일수가 많은 순서대로 정렬
        inactive_list.sort(key=lambda x: x["days_inactive"], reverse=True)

        view = InactiveUserListView(
            author=interaction.user,
            guild=interaction.guild,
            days_threshold=days_threshold,
            inactive_list=inactive_list,
            total_members=total_members
        )
        embed = view.build_embed()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def _execute_github_webhook(
        self,
        interaction: discord.Interaction,
        채널: Optional[discord.TextChannel] = None,
        역할멘션: Optional[discord.Role] = None,
        연동해제: bool = False,
        동작: Optional[str] = None
    ):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 이 명령어는 서버(길드)에서만 사용할 수 있습니다.", ephemeral=True)
            return

        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, "❌ 이 명령어를 사용하려면 **서버 관리(Manage Server)** 권한이 필요합니다.", ephemeral=True)
            return

        data = await asyncio.to_thread(core.load_data)

        # 1. 연동 해제 요청 처리
        if 연동해제 or (동작 and str(동작).lower() in ("disable", "off", "해제")):
            removed = core.remove_github_webhook_config(data, interaction.guild_id)
            if removed:
                await asyncio.to_thread(core.save_data, data)
                await core.safe_send_response(interaction, "🛑 **이 서버의 GitHub 웹훅 알림 연동이 해제되었습니다.**", ephemeral=True)
            else:
                await core.safe_send_response(interaction, "ℹ️ 현재 설정된 GitHub 알림 채널이 없습니다.", ephemeral=True)
            return

        # 2. 연동 대상 채널 확인 (미지정 시 현재 채널)
        target_ch = 채널 or interaction.channel
        if not isinstance(target_ch, discord.TextChannel):
            await core.safe_send_response(interaction, "❌ 알림을 수신할 **텍스트 채널**을 올바르게 지정해 주세요.", ephemeral=True)
            return

        role_id = 역할멘션.id if 역할멘션 else None
        core.set_github_webhook_config(data, interaction.guild_id, target_ch.id, role_id)
        await asyncio.to_thread(core.save_data, data)

        # 3. 디스코드 채널 자체 웹훅 자동 조회/생성 (0-config 초간편 연동)
        discord_webhook_url = None
        try:
            if target_ch.permissions_for(interaction.guild.me).manage_webhooks:
                whs = await target_ch.webhooks()
                existing_wh = next((w for w in whs if w.name in ("GitHub 알림", "norosi-github")), None)
                if not existing_wh:
                    existing_wh = await target_ch.create_webhook(name="GitHub 알림", reason="GitHub 실시간 업데이트 알림 연동")
                if existing_wh:
                    discord_webhook_url = f"{existing_wh.url}/github"
        except Exception:
            pass

        # 4. 봇 전용 aiohttp 웹훅 URL 계산
        ext_host = os.getenv("EXTERNAL_URL") or os.getenv("WEBHOOK_HOST")
        if not ext_host:
            try:
                req = urllib.request.Request("https://api.ipify.org", headers={"User-Agent": "norosi"})
                with urllib.request.urlopen(req, timeout=1.5) as r:
                    ext_ip = r.read().decode("utf-8").strip()
                    if ext_ip:
                        ext_host = f"http://{ext_ip}:{core.PORT}"
            except Exception:
                pass
        if not ext_host:
            ext_host = f"http://<서버IP>:{core.PORT}"

        bot_webhook_url = f"{ext_host.rstrip('/')}/api/github/webhook"
        primary_url = bot_webhook_url if "http" in ext_host and "<" not in ext_host else (discord_webhook_url or bot_webhook_url)

        total_linked = len(core.get_github_webhook_configs(data))
        embed = discord.Embed(
            title="🚀 GitHub 업데이트 알림 연동 완료",
            description=(
                f"• 📢 **수신 채널:** {target_ch.mention} (`#{target_ch.name}`)\n"
                f"• 👥 **멘션 역할:** {역할멘션.mention if 역할멘션 else '지정 안함'}\n"
                f"• 🌐 **전체 연동 서버:** 총 {total_linked}개 서버 채널에 실시간 동시 전파됩니다.\n\n"
                f"### 📋 GitHub 등록용 Webhook URL\n"
                f"```{primary_url}```\n"
                f"👉 깃허브 저장소 > **Settings** > **Webhooks** > **[Add webhook]**에서\n"
                f"**Payload URL**에 위 주소를 붙여넣고 Content type을 `application/json`으로 저장하면 연동된 **모든 서버 채널**에 동시 공지됩니다!"
            ),
            color=discord.Color.from_rgb(46, 204, 113),
            timestamp=datetime.datetime.now(core.KST)
        )
        if discord_webhook_url and discord_webhook_url != primary_url:
            embed.set_footer(text=f"디스코드 개별 채널 웹훅: {discord_webhook_url}")
        else:
            embed.set_footer(text=f"총 {total_linked}개 연동 서버 채널 동시 방송 모드 활성화됨")

        view = GithubWebhookView(interaction.user, target_ch, self.bot, 역할멘션)
        await core.safe_send_response(interaction, embed=embed, view=view, ephemeral=True)

    @app_commands.command(
        name="깃허브연동",
        description="현재 채널 또는 지정한 채널에 GitHub 푸시 및 Actions 배포 알림을 즉시 연동합니다."
    )
    @app_commands.describe(
        채널="(선택) 알림을 수신할 채널 (미입력 시 현재 채널로 즉시 연동)",
        역할멘션="(선택) 배포 알림 시 멘션할 역할 (예: @공지, @개발자 등)",
        연동해제="(선택) True 선택 시 이 서버의 GitHub 알림 연동을 해제합니다."
    )
    async def github_webhook_cmd(
        self,
        interaction: discord.Interaction,
        채널: Optional[discord.TextChannel] = None,
        역할멘션: Optional[discord.Role] = None,
        연동해제: bool = False,
        동작: Optional[str] = None
    ):
        await self._execute_github_webhook(interaction, 채널=채널, 역할멘션=역할멘션, 연동해제=연동해제, 동작=동작)

    @app_commands.command(
        name="깃허브알림",
        description="현재 채널 또는 지정한 채널에 GitHub 푸시 및 Actions 배포 알림을 즉시 연동합니다."
    )
    @app_commands.describe(
        채널="(선택) 알림을 수신할 채널 (미입력 시 현재 채널로 즉시 연동)",
        역할멘션="(선택) 배포 알림 시 멘션할 역할 (예: @공지, @개발자 등)",
        연동해제="(선택) True 선택 시 이 서버의 GitHub 알림 연동을 해제합니다."
    )
    async def github_notify_cmd(
        self,
        interaction: discord.Interaction,
        채널: Optional[discord.TextChannel] = None,
        역할멘션: Optional[discord.Role] = None,
        연동해제: bool = False,
        동작: Optional[str] = None
    ):
        await self._execute_github_webhook(interaction, 채널=채널, 역할멘션=역할멘션, 연동해제=연동해제, 동작=동작)

    # ==========================================
    # 1. 🔊 Voice (음성 채널 입장/퇴장/이동)
    # ==========================================
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if not member.guild or member.bot:
            return
        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(member.guild, data, category_key="voice")
        if not ch:
            return

        user_info = f"👤 **유저:** {member.mention} (`{member.display_name}` / **ID: `{member.id}`**)"

        # Voice Join
        if before.channel is None and after.channel is not None:
            embed = discord.Embed(
                title="🔊 음성 채널 입장",
                description=f"{user_info}\n📢 **입장 채널:** {after.channel.mention} (`#{after.channel.name}`)",
                color=discord.Color.green(),
                timestamp=datetime.datetime.now(core.KST)
            )
            embed.set_thumbnail(url=member.display_avatar.url if hasattr(member, "display_avatar") else None)
            try: await ch.send(embed=embed)
            except Exception: pass

        # Voice Leave
        elif before.channel is not None and after.channel is None:
            embed = discord.Embed(
                title="🔇 음성 채널 퇴장",
                description=f"{user_info}\n📢 **퇴장 채널:** {before.channel.mention} (`#{before.channel.name}`)",
                color=discord.Color.red(),
                timestamp=datetime.datetime.now(core.KST)
            )
            embed.set_thumbnail(url=member.display_avatar.url if hasattr(member, "display_avatar") else None)
            try: await ch.send(embed=embed)
            except Exception: pass

        # Voice Move
        elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
            embed = discord.Embed(
                title="🔄 음성 채널 이동",
                description=(
                    f"{user_info}\n"
                    f"🔴 **이전 채널:** {before.channel.mention}\n"
                    f"🟢 **이동 채널:** {after.channel.mention}"
                ),
                color=discord.Color.blue(),
                timestamp=datetime.datetime.now(core.KST)
            )
            embed.set_thumbnail(url=member.display_avatar.url if hasattr(member, "display_avatar") else None)
            try: await ch.send(embed=embed)
            except Exception: pass

    def _format_attachments(self, attachments: list[discord.Attachment]) -> tuple[str, str | None]:
        if not attachments:
            return "", None
        lines = []
        img_url = None
        for att in attachments:
            lines.append(f"• [{att.filename}]({att.url}) (`{att.size // 1024} KB`)")
            if not img_url and att.content_type and att.content_type.startswith("image/"):
                img_url = att.url
            elif not img_url and any(att.filename.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
                img_url = att.url
        return "\n".join(lines), img_url

    # ==========================================
    # 2. 💬 Messages (삭제, 수정, 대량삭제)
    # ==========================================
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(message.guild, data, category_key="messages")
        if not ch:
            return

        content_str = message.content if message.content else "*(텍스트 내용 없음)*"
        if len(content_str) > 1000:
            content_str = content_str[:1000] + "..."

        att_str, img_url = self._format_attachments(message.attachments)
        att_section = f"\n\n📎 **첨부파일 및 미디어:**\n{att_str}" if att_str else ""

        embed = discord.Embed(
            title="🗑️ 메시지 삭제",
            description=(
                f"👤 **작성자:** {message.author.mention} (`{message.author.display_name}` / **ID: `{message.author.id}`**)\n"
                f"📢 **채널:** {message.channel.mention}\n\n"
                f"📝 **삭제된 내용 원본:**\n```text\n{content_str}\n```"
                f"{att_section}"
            ),
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(core.KST)
        )
        if img_url:
            embed.set_image(url=img_url)
        embed.set_thumbnail(url=message.author.display_avatar.url if hasattr(message.author, "display_avatar") else None)
        try: await ch.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot:
            return
        if before.content == after.content and before.attachments == after.attachments:
            return

        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(before.guild, data, category_key="messages")
        if not ch:
            return

        before_text = before.content if before.content else "*(내용 없음)*"
        after_text = after.content if after.content else "*(내용 없음)*"
        if len(before_text) > 800: before_text = before_text[:800] + "..."
        if len(after_text) > 800: after_text = after_text[:800] + "..."

        att_before, img_before = self._format_attachments(before.attachments)
        att_after, img_after = self._format_attachments(after.attachments)

        att_section = ""
        if att_before or att_after:
            att_section = f"\n\n📎 **첨부파일 변동:**\n• 수정 전: {att_before or '없음'}\n• 수정 후: {att_after or '없음'}"

        embed = discord.Embed(
            title="✏️ 메시지 수정",
            description=(
                f"👤 **작성자:** {before.author.mention} (`{before.author.display_name}` / **ID: `{before.author.id}`**)\n"
                f"📢 **채널:** {before.channel.mention} · [🔗 메시지 바로가기]({after.jump_url})\n\n"
                f"🔴 **수정 전:**\n```text\n{before_text}\n```\n"
                f"🟢 **수정 후:**\n```text\n{after_text}\n```"
                f"{att_section}"
            ),
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(core.KST)
        )
        if img_after:
            embed.set_image(url=img_after)
        elif img_before:
            embed.set_image(url=img_before)

        embed.set_thumbnail(url=before.author.display_avatar.url if hasattr(before.author, "display_avatar") else None)
        try: await ch.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        if not messages or not messages[0].guild:
            return
        guild = messages[0].guild
        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(guild, data, category_key="messages")
        if not ch:
            return

        embed = discord.Embed(
            title="🧹 메시지 대량 삭제",
            description=(
                f"📢 **채널:** {messages[0].channel.mention}\n"
                f"🗑️ **삭제된 메시지 수:** **`{len(messages):,}개`**"
            ),
            color=discord.Color.dark_red(),
            timestamp=datetime.datetime.now(core.KST)
        )
        try: await ch.send(embed=embed)
        except Exception: pass

    # ==========================================
    # 3. 👥 Members (입장, 퇴장, 차단, 해제, 역할부여/제거)
    # ==========================================
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.guild:
            return
        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(member.guild, data, category_key="members")
        if not ch:
            return

        created_str = member.created_at.astimezone(core.KST).strftime("%Y-%m-%d %H:%M:%S")
        embed = discord.Embed(
            title="📥 유저 입장",
            description=(
                f"👤 **유저:** {member.mention} (`{member.name}` / **ID: `{member.id}`**)\n"
                f"📅 **계정 생성일:** `{created_str}` (KST)\n"
                f"📊 **현재 서버 인원:** **`{member.guild.member_count:,}명`**"
            ),
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_thumbnail(url=member.display_avatar.url if hasattr(member, "display_avatar") else None)
        try: await ch.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if not member.guild:
            return
        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(member.guild, data, category_key="members")
        if not ch:
            return

        embed = discord.Embed(
            title="📤 유저 퇴장",
            description=(
                f"👤 **유저:** `{member.display_name}` (`{member.name}` / **ID: `{member.id}`**)\n"
                f"📊 **현재 서버 인원:** **`{member.guild.member_count:,}명`**"
            ),
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_thumbnail(url=member.display_avatar.url if hasattr(member, "display_avatar") else None)
        try: await ch.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(guild, data, category_key="members")
        if not ch: return

        embed = discord.Embed(
            title="🔨 유저 차단",
            description=f"👤 **차단 대상:** {user.mention} (`{user.name}` / **ID: `{user.id}`**)",
            color=discord.Color.dark_red(),
            timestamp=datetime.datetime.now(core.KST)
        )
        try: await ch.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(guild, data, category_key="members")
        if not ch: return

        embed = discord.Embed(
            title="🔓 유저 차단 해제",
            description=f"👤 **해제 대상:** {user.mention} (`{user.name}` / **ID: `{user.id}`**)",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(core.KST)
        )
        try: await ch.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if not before.guild:
            return
        data = await core.asyncio.to_thread(core.load_data)

        # 1. Nicknames -> Mod/Admin
        if before.nick != after.nick:
            ch_mod = self._get_log_channel(before.guild, data, category_key="mod_admin")
            if ch_mod:
                b_nick = before.nick or before.name
                a_nick = after.nick or after.name
                embed = discord.Embed(
                    title="🏷️ 닉네임 변경",
                    description=(
                        f"👤 **유저:** {after.mention} (`{after.name}` / **ID: `{after.id}`**)\n"
                        f"🔴 **변경 전:** `{b_nick}`\n"
                        f"🟢 **변경 후:** `{a_nick}`"
                    ),
                    color=discord.Color.blue(),
                    timestamp=datetime.datetime.now(core.KST)
                )
                embed.set_thumbnail(url=after.display_avatar.url if hasattr(after, "display_avatar") else None)
                try: await ch_mod.send(embed=embed)
                except Exception: pass

        # 2. Role Given / Role Removed -> Members
        b_roles, a_roles = set(before.roles), set(after.roles)
        added_roles, removed_roles = a_roles - b_roles, b_roles - a_roles
        if added_roles or removed_roles:
            ch_mem = self._get_log_channel(before.guild, data, category_key="members")
            if ch_mem:
                user_hdr = f"👤 **멤버:** {after.mention} (`{after.name}` / **ID: `{after.id}`**)"
                lines = [user_hdr]
                if added_roles:
                    for r in added_roles:
                        lines.append(f"➕ **역할 부여:** {r.mention} (`{r.name}`)")
                if removed_roles:
                    for r in removed_roles:
                        lines.append(f"➖ **역할 제거:** {r.mention} (`{r.name}`)")

                embed = discord.Embed(
                    title="🛡️ 멤버 역할 변경",
                    description="\n".join(lines),
                    color=discord.Color.purple(),
                    timestamp=datetime.datetime.now(core.KST)
                )
                embed.set_thumbnail(url=after.display_avatar.url if hasattr(after, "display_avatar") else None)
                try: await ch_mem.send(embed=embed)
                except Exception: pass

        # 3. Timeout (타임아웃 / 활동 제한) -> Mod/Admin
        b_timeout = getattr(before, "timed_out_until", None)
        a_timeout = getattr(after, "timed_out_until", None)
        if b_timeout != a_timeout:
            ch_mod = self._get_log_channel(before.guild, data, category_key="mod_admin")
            if ch_mod:
                if a_timeout:
                    ts_str = a_timeout.astimezone(core.KST).strftime('%Y-%m-%d %H:%M:%S KST')
                    desc = (
                        f"👤 **대상 멤버:** {after.mention} (`{after.name}` / **ID: `{after.id}`**)\n"
                        f"⏳ **타임아웃(활동 제한) 적용:** `{ts_str}`까지"
                    )
                    col = discord.Color.red()
                    t_title = "⏳ 멤버 타임아웃(활동 제한) 적용"
                else:
                    desc = (
                        f"👤 **대상 멤버:** {after.mention} (`{after.name}` / **ID: `{after.id}`**)\n"
                        f"🔓 **타임아웃(활동 제한) 해제됨**"
                    )
                    col = discord.Color.green()
                    t_title = "🔓 멤버 타임아웃(활동 제한) 해제"

                embed = discord.Embed(
                    title=t_title,
                    description=desc,
                    color=col,
                    timestamp=datetime.datetime.now(core.KST)
                )
                embed.set_thumbnail(url=after.display_avatar.url if hasattr(after, "display_avatar") else None)
                try: await ch_mod.send(embed=embed)
                except Exception: pass

    # ==========================================
    # 4. 🛡️ Mod/Admin (Mod Actions - 감사 로그 기반 밴/킥/뮤트/경고)
    # ==========================================
    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        if not entry.guild:
            return
        if entry.user and self.bot.user and entry.user.id == self.bot.user.id:
            return
        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(entry.guild, data, category_key="mod_admin")
        if not ch:
            return

        raw_action = str(entry.action).replace("AuditLogAction.", "")
        kr_action = AUDIT_LOG_ACTION_KOREAN.get(raw_action, raw_action)
        target = entry.target
        user = entry.user

        target_info = f"{target.mention} (`{target}` / **ID: `{target.id}`**)" if isinstance(target, (discord.abc.User, discord.Role, discord.abc.GuildChannel)) else f"`{target}`"
        mod_info = f"{user.mention} (`{user}` / **ID: `{user.id}`**)" if user else "시스템"

        diff_lines = format_audit_log_diff(entry)
        diff_str = ("\n\n📝 **상세 변경 내역:**\n" + "\n".join(diff_lines)) if diff_lines else ""

        embed = discord.Embed(
            title=f"⚖️ 모더레이션 조치: {kr_action} (`{raw_action}`)",
            description=(
                f"👮 **조치자 (Mod):** {mod_info}\n"
                f"🎯 **조치 대상:** {target_info}\n"
                f"💬 **사유:** `{entry.reason or '사유 미입력'}`"
                f"{diff_str}"
            ),
            color=discord.Color.dark_gold(),
            timestamp=datetime.datetime.now(core.KST)
        )
        try: await ch.send(embed=embed)
        except Exception: pass

    # ==========================================
    # 5. 📢 Channels (생성, 삭제, 수정)
    # ==========================================
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        if not channel.guild: return
        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(channel.guild, data, category_key="channels")
        if not ch: return

        embed = discord.Embed(
            title="➕ 채널 생성",
            description=f"📢 **생성된 채널:** {channel.mention} (`#{channel.name}` / **ID: `{channel.id}`** · 유형: `{channel.type}`)",
            color=discord.Color.teal(),
            timestamp=datetime.datetime.now(core.KST)
        )
        try: await ch.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if not channel.guild: return
        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(channel.guild, data, category_key="channels")
        if not ch: return

        embed = discord.Embed(
            title="➖ 채널 삭제",
            description=f"📢 **삭제된 채널:** `#{channel.name}` (**ID: `{channel.id}`** · 유형: `{channel.type}`)",
            color=discord.Color.dark_red(),
            timestamp=datetime.datetime.now(core.KST)
        )
        try: await ch.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        if not before.guild: return
        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(before.guild, data, category_key="channels")
        if not ch: return

        changes = []
        if before.name != after.name:
            changes.append(f"• **채널 이름:** `#{before.name}` ➡️ `#{after.name}`")
        if hasattr(before, "topic") and hasattr(after, "topic") and before.topic != after.topic:
            b_top = f"`{before.topic[:80]}`" if before.topic else "(없음)"
            a_top = f"`{after.topic[:80]}`" if after.topic else "(없음)"
            changes.append(f"• **채널 주제:** {b_top} ➡️ {a_top}")
        if getattr(before, "category", None) != getattr(after, "category", None):
            b_cat = f"`{before.category.name}`" if getattr(before, "category", None) else "(카테고리 없음)"
            a_cat = f"`{after.category.name}`" if getattr(after, "category", None) else "(카테고리 없음)"
            changes.append(f"• **상위 카테고리:** {b_cat} ➡️ {a_cat}")
        if getattr(before, "position", 0) != getattr(after, "position", 0):
            changes.append(f"• **채널 위치(순서):** `{before.position}` ➡️ `{after.position}`")
        if getattr(before, "slowmode_delay", 0) != getattr(after, "slowmode_delay", 0):
            changes.append(f"• **슬로우 모드(느린 모드):** `{getattr(before, 'slowmode_delay', 0)}초` ➡️ `{getattr(after, 'slowmode_delay', 0)}초`")
        if getattr(before, "nsfw", False) != getattr(after, "nsfw", False):
            b_nsfw = "연령 제한(NSFW)" if before.nsfw else "일반 채널"
            a_nsfw = "연령 제한(NSFW)" if after.nsfw else "일반 채널"
            changes.append(f"• **연령 제한(NSFW):** `{b_nsfw}` ➡️ `{a_nsfw}`")
        if getattr(before, "bitrate", 0) != getattr(after, "bitrate", 0):
            changes.append(f"• **음성 비트레이트:** `{before.bitrate // 1000}kbps` ➡️ `{after.bitrate // 1000}kbps`")
        if getattr(before, "user_limit", 0) != getattr(after, "user_limit", 0):
            b_lim = f"{before.user_limit}명" if before.user_limit else "무제한"
            a_lim = f"{after.user_limit}명" if after.user_limit else "무제한"
            changes.append(f"• **음성 인원 제한:** `{b_lim}` ➡️ `{a_lim}`")
        if getattr(before, "rtc_region", None) != getattr(after, "rtc_region", None):
            changes.append(f"• **음성 채널 지역:** `{before.rtc_region or '자동'}` ➡️ `{after.rtc_region or '자동'}`")
        if getattr(before, "default_auto_archive_duration", None) != getattr(after, "default_auto_archive_duration", None):
            changes.append(f"• **스레드 자동 보관 시간:** `{before.default_auto_archive_duration}분` ➡️ `{after.default_auto_archive_duration}분`")

        # 권한 덮어쓰기(Permissions Overwrites) 비교
        if hasattr(before, "overwrites") and hasattr(after, "overwrites") and before.overwrites != after.overwrites:
            b_targets = set(before.overwrites.keys())
            a_targets = set(after.overwrites.keys())

            for target in a_targets - b_targets:
                target_str = target.mention if hasattr(target, "mention") else f"`{getattr(target, 'name', str(target))}`"
                changes.append(f"• **🔐 권한 덮어쓰기 추가:** {target_str}")

            for target in b_targets - a_targets:
                target_str = target.mention if hasattr(target, "mention") else f"`{getattr(target, 'name', str(target))}`"
                changes.append(f"• **🔓 권한 덮어쓰기 제거:** {target_str}")

            for target in a_targets & b_targets:
                b_ow, a_ow = before.overwrites[target], after.overwrites[target]
                if b_ow != a_ow:
                    target_str = target.mention if hasattr(target, "mention") else f"`{getattr(target, 'name', str(target))}`"
                    p_allowed, p_denied, p_neutral = [], [], []
                    for perm, val in a_ow:
                        old_val = getattr(b_ow, perm)
                        if val != old_val:
                            kr_perm = PERM_KR_MAP.get(perm, perm)
                            if val is True: p_allowed.append(kr_perm)
                            elif val is False: p_denied.append(kr_perm)
                            elif val is None: p_neutral.append(kr_perm)
                    ow_details = []
                    if p_allowed: ow_details.append(f"✅ 허용: {', '.join(p_allowed)}")
                    if p_denied: ow_details.append(f"❌ 거부: {', '.join(p_denied)}")
                    if p_neutral: ow_details.append(f"⚪ 초기화: {', '.join(p_neutral)}")
                    changes.append(f"• **🔐 권한 덮어쓰기 변경 ({target_str}):** {' / '.join(ow_details)}")

        if changes:
            embed = discord.Embed(
                title="✏️ 채널 설정 변경",
                description=f"📢 **대상 채널:** {after.mention} (`#{after.name}` / **ID: `{after.id}`**)\n\n" + "\n".join(changes),
                color=discord.Color.gold(),
                timestamp=datetime.datetime.now(core.KST)
            )
            try: await ch.send(embed=embed)
            except Exception: pass

    # ==========================================
    # 6. 🛡️ Roles (생성, 삭제, 수정)
    # ==========================================
    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        if not role.guild: return
        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(role.guild, data, category_key="roles")
        if not ch: return

        embed = discord.Embed(
            title="➕ 역할 생성",
            description=f"🛡️ **생성된 역할:** {role.mention} (`{role.name}` / **ID: `{role.id}`**)",
            color=discord.Color.dark_purple(),
            timestamp=datetime.datetime.now(core.KST)
        )
        try: await ch.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        if not role.guild: return
        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(role.guild, data, category_key="roles")
        if not ch: return

        embed = discord.Embed(
            title="➖ 역할 삭제",
            description=f"🛡️ **삭제된 역할:** `{role.name}` (**ID: `{role.id}`**)",
            color=discord.Color.dark_magenta(),
            timestamp=datetime.datetime.now(core.KST)
        )
        try: await ch.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        if not before.guild: return
        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(before.guild, data, category_key="roles")
        if not ch: return

        changes = []
        if before.name != after.name:
            changes.append(f"• **역할 이름:** `{before.name}` ➡️ `{after.name}`")
        if before.color != after.color:
            b_hex = f"#{before.color.value:06x}" if before.color.value else "기본값"
            a_hex = f"#{after.color.value:06x}" if after.color.value else "기본값"
            changes.append(f"• **역할 색상:** `{b_hex}` ➡️ `{a_hex}`")
        if before.hoist != after.hoist:
            b_h = "분리 표시" if before.hoist else "일반 표시"
            a_h = "분리 표시" if after.hoist else "일반 표시"
            changes.append(f"• **멤버 목록 분리 표시:** `{b_h}` ➡️ `{a_h}`")
        if before.mentionable != after.mentionable:
            b_m = "허용" if before.mentionable else "비허용"
            a_m = "허용" if after.mentionable else "비허용"
            changes.append(f"• **모든 멤버 멘션 가능 여부:** `{b_m}` ➡️ `{a_m}`")
        if hasattr(before, "icon") and hasattr(after, "icon") and before.icon != after.icon:
            b_icon = f"[이전 아이콘]({before.icon.url})" if before.icon else "없음"
            a_icon = f"[새 아이콘]({after.icon.url})" if after.icon else "제거됨"
            changes.append(f"• **역할 아이콘:** {b_icon} ➡️ {a_icon}")
        if hasattr(before, "unicode_emoji") and hasattr(after, "unicode_emoji") and before.unicode_emoji != after.unicode_emoji:
            changes.append(f"• **역할 이모지:** `{before.unicode_emoji or '없음'}` ➡️ `{after.unicode_emoji or '없음'}`")
        if before.position != after.position:
            changes.append(f"• **역할 서열/순서:** `{before.position}` ➡️ `{after.position}`")

        # 역할 권한 변경 세부 내역
        if before.permissions.value != after.permissions.value:
            granted = [PERM_KR_MAP.get(name, name) for name, p in after.permissions if p and not getattr(before.permissions, name, False)]
            revoked = [PERM_KR_MAP.get(name, name) for name, p in before.permissions if p and not getattr(after.permissions, name, False)]
            if granted:
                changes.append(f"• **➕ 새로 부여된 권한:** `{', '.join(granted)}`")
            if revoked:
                changes.append(f"• **➖ 회수/제거된 권한:** `{', '.join(revoked)}`")

        if changes:
            embed = discord.Embed(
                title="✏️ 역할 설정 변경",
                description=f"🛡️ **대상 역할:** {after.mention} (`{after.name}` / **ID: `{after.id}`**)\n\n" + "\n".join(changes),
                color=after.color if after.color.value else discord.Color.gold(),
                timestamp=datetime.datetime.now(core.KST)
            )
            try: await ch.send(embed=embed)
            except Exception: pass

    # ==========================================
    # 7. 🌐 Server (서버설정 변경 및 이모지 추가/삭제/수정)
    # ==========================================
    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(after, data, category_key="server")
        if not ch: return

        changes = []
        if before.name != after.name:
            changes.append(f"• **서버 이름:** `{before.name}` ➡️ `{after.name}`")
        if before.description != after.description:
            b_desc = (before.description or "(없음)")[:80]
            a_desc = (after.description or "(없음)")[:80]
            changes.append(f"• **서버 설명:** `{b_desc}` ➡️ `{a_desc}`")
        if before.icon != after.icon:
            b_url = f"[이전 아이콘]({before.icon.url})" if before.icon else "없음"
            a_url = f"[새 아이콘]({after.icon.url})" if after.icon else "제거됨"
            changes.append(f"• **서버 아이콘:** {b_url} ➡️ {a_url}")
        if before.banner != after.banner:
            b_url = f"[이전 배너]({before.banner.url})" if before.banner else "없음"
            a_url = f"[새 배너]({after.banner.url})" if after.banner else "제거됨"
            changes.append(f"• **서버 배너:** {b_url} ➡️ {a_url}")
        if before.splash != after.splash:
            changes.append("• **초대 배경(Splash) 이미지 변경**")
        if getattr(before, "discovery_splash", None) != getattr(after, "discovery_splash", None):
            changes.append("• **서버 찾기 배경(Discovery Splash) 이미지 변경**")
        if before.owner_id != after.owner_id:
            changes.append(f"• **👑 서버 소유자 이전:** <@{before.owner_id}> ➡️ <@{after.owner_id}>")
        if before.afk_channel != after.afk_channel:
            b_afk = before.afk_channel.mention if before.afk_channel else "(없음)"
            a_afk = after.afk_channel.mention if after.afk_channel else "(없음)"
            changes.append(f"• **잠수(AFK) 채널:** {b_afk} ➡️ {a_afk}")
        if before.afk_timeout != after.afk_timeout:
            changes.append(f"• **잠수(AFK) 대기 시간:** `{before.afk_timeout // 60}분` ➡️ `{after.afk_timeout // 60}분`")
        if before.system_channel != after.system_channel:
            b_sys = before.system_channel.mention if before.system_channel else "(없음)"
            a_sys = after.system_channel.mention if after.system_channel else "(없음)"
            changes.append(f"• **시스템 메시지 채널:** {b_sys} ➡️ {a_sys}")
        if before.rules_channel != after.rules_channel:
            b_rul = before.rules_channel.mention if before.rules_channel else "(없음)"
            a_rul = after.rules_channel.mention if after.rules_channel else "(없음)"
            changes.append(f"• **규칙 채널:** {b_rul} ➡️ {a_rul}")
        if before.public_updates_channel != after.public_updates_channel:
            b_upd = before.public_updates_channel.mention if before.public_updates_channel else "(없음)"
            a_upd = after.public_updates_channel.mention if after.public_updates_channel else "(없음)"
            changes.append(f"• **커뮤니티 업데이트 채널:** {b_upd} ➡️ {a_upd}")
        if before.verification_level != after.verification_level:
            b_vl = VERIFICATION_LEVEL_KR.get(before.verification_level, str(before.verification_level))
            a_vl = VERIFICATION_LEVEL_KR.get(after.verification_level, str(after.verification_level))
            changes.append(f"• **보안/인증 수준:** `{b_vl}` ➡️ `{a_vl}`")
        if before.default_notifications != after.default_notifications:
            b_dn = NOTIFICATION_LEVEL_KR.get(before.default_notifications, str(before.default_notifications))
            a_dn = NOTIFICATION_LEVEL_KR.get(after.default_notifications, str(after.default_notifications))
            changes.append(f"• **기본 알림 설정:** `{b_dn}` ➡️ `{a_dn}`")
        if before.explicit_content_filter != after.explicit_content_filter:
            b_ec = CONTENT_FILTER_KR.get(before.explicit_content_filter, str(before.explicit_content_filter))
            a_ec = CONTENT_FILTER_KR.get(after.explicit_content_filter, str(after.explicit_content_filter))
            changes.append(f"• **유해 콘텐츠 필터:** `{b_ec}` ➡️ `{a_ec}`")
        if before.mfa_level != after.mfa_level:
            b_mfa = "2단계 인증 필수" if before.mfa_level else "비활성화"
            a_mfa = "2단계 인증 필수" if after.mfa_level else "비활성화"
            changes.append(f"• **2단계 인증(2FA) 관리자 요구:** `{b_mfa}` ➡️ `{a_mfa}`")
        if before.preferred_locale != after.preferred_locale:
            changes.append(f"• **서버 기본 언어:** `{before.preferred_locale}` ➡️ `{after.preferred_locale}`")
        if getattr(before, "vanity_url_code", None) != getattr(after, "vanity_url_code", None):
            b_van = f"`discord.gg/{before.vanity_url_code}`" if getattr(before, "vanity_url_code", None) else "(없음)"
            a_van = f"`discord.gg/{after.vanity_url_code}`" if getattr(after, "vanity_url_code", None) else "(없음)"
            changes.append(f"• **커스텀 초대 코드(Vanity):** {b_van} ➡️ {a_van}")
        if getattr(before, "premium_tier", None) != getattr(after, "premium_tier", None):
            changes.append(f"• **서버 부스트 레벨:** `레벨 {before.premium_tier}` ➡️ `레벨 {after.premium_tier}`")
        if getattr(before, "premium_subscription_count", 0) != getattr(after, "premium_subscription_count", 0):
            changes.append(f"• **서버 부스트 개수:** `{before.premium_subscription_count}개` ➡️ `{after.premium_subscription_count}개`")

        if not changes:
            try:
                async for entry in after.audit_logs(limit=2, action=discord.AuditLogAction.guild_update):
                    audit_changes = format_audit_log_diff(entry)
                    if audit_changes:
                        changes.extend(audit_changes)
                        break
            except Exception:
                pass

        if not changes:
            changes.append("• **서버 위젯 / 커뮤니티 활성화 / 기타 내부 설정 변경**")

        embed = discord.Embed(
            title="🌐 서버 설정 변경",
            description=f"🏠 **서버:** **{after.name}** (**ID: `{after.id}`**)\n\n" + "\n".join(changes),
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now(core.KST)
        )
        if after.icon:
            embed.set_thumbnail(url=after.icon.url)
        try: await ch.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before: list[discord.Emoji], after: list[discord.Emoji]):
        data = await core.asyncio.to_thread(core.load_data)
        ch = self._get_log_channel(guild, data, category_key="server")
        if not ch: return

        b_set, a_set = set(before), set(after)
        added, removed = a_set - b_set, b_set - a_set

        # 이모지 이름 변경(Rename) 감지
        renamed = []
        b_dict = {e.id: e for e in before}
        for a_e in after:
            if a_e.id in b_dict:
                b_e = b_dict[a_e.id]
                if b_e.name != a_e.name:
                    renamed.append(f"✏️ **이모지 이름 변경:** `:{b_e.name}:` ➡️ `:{a_e.name}:` ({a_e})")

        if added or removed or renamed:
            lines = []
            if added: lines.append(f"➕ **이모지 추가:** {', '.join([str(e) for e in added])}")
            if removed: lines.append(f"➖ **이모지 삭제:** {', '.join([f'`:{e.name}:`' for e in removed])}")
            if renamed: lines.extend(renamed)

            embed = discord.Embed(
                title="🎨 이모지 변경",
                description="\n".join(lines),
                color=discord.Color.gold(),
                timestamp=datetime.datetime.now(core.KST)
            )
            try: await ch.send(embed=embed)
            except Exception: pass


# ==========================================
# /공지발송 관련 임베드 빌더 & 모달 & 미리보기 뷰
# ==========================================
def build_announcement_embed(
    guild: discord.Guild,
    author: discord.User | discord.Member,
    title: str,
    content: str,
    badge_key: str = "normal",
    color_key: str = "cyan",
    banner_url: str = None,
    mention_mode: str = "none"
) -> discord.Embed:
    emoji, badge_text, badge_label = ANNOUNCEMENT_BADGES.get(badge_key, ANNOUNCEMENT_BADGES["normal"])
    color, _ = ANNOUNCEMENT_COLORS.get(color_key, ANNOUNCEMENT_COLORS["cyan"])
    now_kst = datetime.datetime.now(core.KST)
    ts = int(now_kst.timestamp())

    mention_display_map = {
        "everyone": "🔔 @everyone (서버 전체)",
        "here": "💬 @here (온라인 멤버)",
        "none": "🔕 일반 안내 (멘션 없음)"
    }
    mention_disp = mention_display_map.get(mention_mode, "🔕 일반 안내")

    meta_line = (
        f"🏷️ **분류:** `[{badge_label}]`  ·  "
        f"📢 **수신:** `{mention_disp}`  ·  "
        f"📅 **일시:** <t:{ts}:F>"
    )

    embed = discord.Embed(
        title=f"{emoji}  {title}",
        description=(
            f"{meta_line}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{content}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💬 *공지사항 관련 문의 또는 건의사항은 서버 관리진에게 문의해 주세요.*"
        ),
        color=color,
        timestamp=now_kst
    )

    if guild and guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.set_author(
        name=f"{guild.name} 공식 공지사항" if guild else "공식 공지사항",
        icon_url=guild.icon.url if (guild and guild.icon) else None
    )

    if banner_url:
        embed.set_image(url=banner_url)

    embed.set_footer(
        text=f"작성 관리자: {author.display_name}  ·  norosi Notice Studio",
        icon_url=author.display_avatar.url if hasattr(author, "display_avatar") else None
    )
    return embed


class AnnouncementEditModal(core.SafeModal):
    def __init__(self, parent_view: "AnnouncementPreviewView", current_title: str, current_content: str, current_banner: str = None):
        super().__init__(title="✏️ norosi 공지사항 본문/제목 수정")
        self.parent_view = parent_view

        self.title_input = discord.ui.TextInput(
            label="공지 제목",
            placeholder="공지사항의 핵심 제목을 입력하세요",
            default=current_title,
            min_length=2,
            max_length=100,
            required=True
        )
        self.content_input = discord.ui.TextInput(
            label="공지 본문 내용 (마크다운 지원)",
            style=discord.TextStyle.paragraph,
            placeholder="공지할 내용을 작성하세요. (줄바꿈, **굵게**, > 인용구 등 마크다운 지원)",
            default=current_content,
            min_length=5,
            max_length=3500,
            required=True
        )
        self.banner_input = discord.ui.TextInput(
            label="배너 이미지 링크 URL (선택)",
            placeholder="예: https://... 이미지 URL (미입력 가능)",
            default=current_banner or "",
            required=False,
            max_length=500
        )
        self.add_item(self.title_input)
        self.add_item(self.content_input)
        self.add_item(self.banner_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.title = self.title_input.value.strip()
        self.parent_view.content = self.content_input.value.strip()
        banner_val = self.banner_input.value.strip() if self.banner_input.value else None
        self.parent_view.banner_url = banner_val
        self.parent_view._refresh_components()

        await interaction.response.edit_message(
            content=self.parent_view.build_preview_content(),
            embed=self.parent_view.build_embed(),
            view=self.parent_view
        )


class AnnouncementPreviewView(core.SafeView):
    def __init__(
        self,
        author: discord.Member,
        guild: discord.Guild,
        target_channel: discord.TextChannel,
        title: str,
        content: str,
        badge_key: str = "normal",
        color_key: str = "cyan",
        mention_mode: str = "none",
        banner_url: str = None
    ):
        super().__init__(timeout=600)
        self.author = author
        self.guild = guild
        self.target_channel = target_channel
        self.title = title
        self.content = content
        self.badge_key = badge_key
        self.color_key = color_key
        self.mention_mode = mention_mode
        self.banner_url = banner_url

        self._refresh_components()

    def build_preview_content(self) -> str:
        mention_labels = {
            "everyone": "🔔 @everyone (서버 전체 멘션)",
            "here": "💬 @here (온라인 멤버 멘션)",
            "none": "🔕 멘션 없음 (조용히 게시)"
        }
        m_label = mention_labels.get(self.mention_mode, "🔕 멘션 없음")
        badge_label = ANNOUNCEMENT_BADGES.get(self.badge_key, ANNOUNCEMENT_BADGES["normal"])[2]
        color_label = ANNOUNCEMENT_COLORS.get(self.color_key, ANNOUNCEMENT_COLORS["cyan"])[1]

        return (
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
            "   📢 **norosi 공지사항 프리미엄 스튜디오 (미리보기)**\n"
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
            f"• 📢 **발송 채널:** {self.target_channel.mention}\n"
            f"• 🔔 **멘션 모드:** `{m_label}`\n"
            f"• 🏷️ **분류 배지:** `{badge_label}`  ·  🎨 **테마 색상:** `{color_label}`\n"
            f"• 🖼️ **배너 첨부:** `{'이미지 등록됨' if self.banner_url else '없음'}`\n\n"
            "👇 **[발송 전 실시간 검수]** 아래 임베드가 실제 채널에 게시될 모습입니다.\n"
            "수정이 필요하면 **`[✏️ 내용/제목 수정]`**을, 템플릿/색상/채널 변경은 **하단 드롭다운**을 선택하세요!"
        )

    def build_embed(self) -> discord.Embed:
        return build_announcement_embed(
            self.guild,
            self.author,
            self.title,
            self.content,
            badge_key=self.badge_key,
            color_key=self.color_key,
            banner_url=self.banner_url,
            mention_mode=self.mention_mode
        )

    def _refresh_components(self):
        self.clear_items()

        # Row 0: Quick Action Buttons
        send_btn = discord.ui.Button(
            label="이대로 즉시 공지 발송",
            style=discord.ButtonStyle.success,
            emoji="🚀",
            row=0
        )
        send_btn.callback = self.on_send_click
        self.add_item(send_btn)

        edit_btn = discord.ui.Button(
            label="내용/제목 수정",
            style=discord.ButtonStyle.primary,
            emoji="✏️",
            row=0
        )
        edit_btn.callback = self.on_edit_click
        self.add_item(edit_btn)

        mention_short = {
            "none": "멘션: 없음 🔕",
            "here": "멘션: @here 💬",
            "everyone": "멘션: @everyone 🔔"
        }
        mention_btn = discord.ui.Button(
            label=mention_short.get(self.mention_mode, "멘션 전환"),
            style=discord.ButtonStyle.secondary if self.mention_mode == "none" else discord.ButtonStyle.danger,
            row=0
        )
        mention_btn.callback = self.on_mention_toggle
        self.add_item(mention_btn)

        cancel_btn = discord.ui.Button(
            label="발송 취소",
            style=discord.ButtonStyle.secondary,
            emoji="✖️",
            row=0
        )
        cancel_btn.callback = self.on_cancel_click
        self.add_item(cancel_btn)

        # Row 1: 템플릿 불러오기 드롭다운
        template_select = discord.ui.Select(
            placeholder="📋 추천 공지 템플릿 불러오기 (점검 / 이벤트 / 수칙 / 보상)...",
            min_values=1,
            max_values=1,
            row=1,
            options=[
                discord.SelectOption(label="🛠️ 시스템 정기 점검 및 업데이트 안내", value="maintenance", description="점검 일시, 작업 내용, 영향 범위 템플릿"),
                discord.SelectOption(label="🚨 서버 이용 수칙 및 커뮤니티 가이드라인", value="rules", description="상호 존중, 채널 목적, 금지 행위 수칙"),
                discord.SelectOption(label="🎉 세카이 스페셜 이벤트 개최 안내", value="event", description="이벤트 일정, 참여 방법, 보상 안내"),
                discord.SelectOption(label="🎁 출석 감사 & 깜짝 보너스 선물 배포", value="reward", description="크리스탈 지급 및 수령 방법 안내"),
                discord.SelectOption(label="📢 서버 공식 소식 및 기본 안내", value="notice", description="주요 소식 및 안내사항 기본 뼈대"),
            ]
        )
        template_select.callback = self.on_template_select
        self.add_item(template_select)

        # Row 2: 테마 색상 변경 드롭다운
        color_options = []
        for c_key, (c_col, c_name) in ANNOUNCEMENT_COLORS.items():
            color_options.append(discord.SelectOption(
                label=f"🎨 {c_name}",
                value=c_key,
                default=(c_key == self.color_key)
            ))
        color_select = discord.ui.Select(
            placeholder="🎨 공지 테마 색상 변경...",
            min_values=1,
            max_values=1,
            row=2,
            options=color_options
        )
        color_select.callback = self.on_color_select
        self.add_item(color_select)

        # Row 3: 발송 채널 변경 드롭다운
        if self.guild and self.guild.text_channels:
            raw_channels = list(self.guild.text_channels)
            if self.target_channel in raw_channels:
                raw_channels.remove(self.target_channel)
                raw_channels.insert(0, self.target_channel)
            ch_options = []
            for ch in raw_channels[:25]:
                is_selected = (ch.id == self.target_channel.id)
                ch_options.append(discord.SelectOption(
                    label=f"#{ch.name}"[:100],
                    value=str(ch.id),
                    description="[현재 선택된 채널]" if is_selected else None,
                    default=is_selected
                ))
            ch_select = discord.ui.Select(
                placeholder="📢 공지 발송 채널 변경...",
                min_values=1,
                max_values=1,
                row=3,
                options=ch_options
            )
            ch_select.callback = self.on_channel_select
            self.add_item(ch_select)

    async def _check_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await core.safe_send_response(interaction, content="❌ 공지 작성 관리자만 조작할 수 있습니다.", ephemeral=True)
            return False
        if not interaction.user.guild_permissions.administrator:
            await core.safe_send_response(interaction, content="❌ 서버 관리자(Administrator)만 사용할 수 있습니다.", ephemeral=True)
            return False
        return True

    async def on_send_click(self, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
            return
        await core.safe_defer(interaction, ephemeral=True)

        mention_content = None
        if self.mention_mode == "everyone":
            mention_content = "@everyone"
        elif self.mention_mode == "here":
            mention_content = "@here"

        embed = self.build_embed()
        try:
            sent_msg = await self.target_channel.send(content=mention_content, embed=embed)
            for item in self.children:
                item.disabled = True
            await interaction.edit_original_response(
                content=(
                    f"🎉 **공지사항 발송 완료!**\n"
                    f"• **게시 채널:** {self.target_channel.mention}\n"
                    f"• **적용 멘션:** `{self.mention_mode}`\n"
                    f"👉 **[공지글 바로가기]({sent_msg.jump_url})**"
                ),
                embed=embed,
                view=self
            )
        except discord.Forbidden:
            await interaction.followup.send(
                f"❌ 봇에게 {self.target_channel.mention} 채널의 메시지 전송(Send Messages) 또는 임베드 링크(Embed Links) 권한이 없습니다.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ 공지 발송 중 오류가 발생했습니다: {e}", ephemeral=True)

    async def on_edit_click(self, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
            return
        await interaction.response.send_modal(
            AnnouncementEditModal(
                parent_view=self,
                current_title=self.title,
                current_content=self.content,
                current_banner=self.banner_url
            )
        )

    async def on_mention_toggle(self, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
            return
        order = ["none", "here", "everyone"]
        idx = order.index(self.mention_mode) if self.mention_mode in order else 0
        self.mention_mode = order[(idx + 1) % len(order)]
        self._refresh_components()
        await interaction.response.edit_message(
            content=self.build_preview_content(),
            embed=self.build_embed(),
            view=self
        )

    async def on_template_select(self, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
            return
        tpl_key = interaction.data["values"][0]
        tpl = ANNOUNCEMENT_TEMPLATES.get(tpl_key)
        if tpl:
            self.title = tpl["title"]
            self.content = tpl["content"]
            self.badge_key = tpl["badge"]
            self.color_key = tpl["color"]
        self._refresh_components()
        await interaction.response.edit_message(
            content=self.build_preview_content(),
            embed=self.build_embed(),
            view=self
        )

    async def on_color_select(self, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
            return
        self.color_key = interaction.data["values"][0]
        self._refresh_components()
        await interaction.response.edit_message(
            content=self.build_preview_content(),
            embed=self.build_embed(),
            view=self
        )

    async def on_channel_select(self, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
            return
        ch_id = int(interaction.data["values"][0])
        ch = self.guild.get_channel(ch_id)
        if ch and isinstance(ch, discord.TextChannel):
            self.target_channel = ch
        self._refresh_components()
        await interaction.response.edit_message(
            content=self.build_preview_content(),
            embed=self.build_embed(),
            view=self
        )

    async def on_cancel_click(self, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="🛑 공지 발송이 취소되었습니다.", embed=None, view=self)


# ==========================================
# /비활성유저조회 관련 페이지네이션 뷰
# ==========================================
class InactiveUserListView(core.SafeView):
    def __init__(self, author: discord.Member, guild: discord.Guild, days_threshold: int, inactive_list: list, total_members: int):
        super().__init__(timeout=300)
        self.author = author
        self.guild = guild
        self.days_threshold = days_threshold
        self.inactive_list = inactive_list
        self.total_members = total_members
        self.page = 0
        self.page_size = 10
        self.max_page = max(0, (len(inactive_list) - 1) // self.page_size)
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = (self.page <= 0)
        self.page_indicator_btn.label = f"📄 {self.page + 1} / {self.max_page + 1}"
        self.next_btn.disabled = (self.page >= self.max_page)

    def build_embed(self) -> discord.Embed:
        now_kst = datetime.datetime.now(core.KST)
        inactive_cnt = len(self.inactive_list)
        active_cnt = max(0, self.total_members - inactive_cnt)
        active_ratio = (active_cnt / self.total_members * 100) if self.total_members > 0 else 0
        inactive_ratio = 100 - active_ratio

        # 시각적 게이지 바 (10칸)
        gauge_blocks = 10
        act_blocks = min(10, max(0, int(active_ratio // 10)))
        inact_blocks = gauge_blocks - act_blocks
        gauge_str = ("🟩" * act_blocks) + ("🟥" * inact_blocks)

        start_idx = self.page * self.page_size
        page_items = self.inactive_list[start_idx:start_idx + self.page_size]

        lines = []
        if not page_items:
            lines.append("🎉 **최근 해당 기준 동안 모든 멤버가 정상적으로 활동 중입니다!** (비활성 유저 0명)")
        else:
            for idx, item in enumerate(page_items, start=start_idx + 1):
                mem = item["member"]
                days = item["days_inactive"]
                last_act = item["last_activity_str"]
                joined = mem.joined_at.strftime("%Y-%m-%d") if mem.joined_at else "정보 없음"
                lines.append(
                    f"**{idx}.** {mem.mention} (`{mem.display_name}` / ID: `{mem.id}`)\n"
                    f"   └ ⏳ **미활동:** `{days}일째`  |  🕒 **마지막 기록:** `{last_act}`  |  📅 **가입:** `{joined}`"
                )

        embed = discord.Embed(
            title=f"👻 [{self.guild.name}] 비활성(잠수) 유저 리포트",
            description=(
                f"📊 **조회 기준:** 최근 **`{self.days_threshold}일 이상`** 활동(출석/채팅)이 없는 멤버 스캔\n"
                f"• **서버 전체 인원:** `{self.total_members:,}명` (봇 제외)\n"
                f"• **활동 멤버:** `{active_cnt:,}명` (**{active_ratio:.1f}%**)\n"
                f"• **비활성 유저:** `{inactive_cnt:,}명` (**{inactive_ratio:.1f}%**)\n"
                f"• **활동 비율:** `{gauge_str}`\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                + "\n".join(lines)
            ),
            color=discord.Color.from_rgb(235, 69, 158) if inactive_cnt > 0 else discord.Color.green(),
            timestamp=now_kst
        )
        embed.set_footer(text=f"페이지 {self.page + 1}/{self.max_page + 1}  ·  총 {inactive_cnt}명 비활성 멤버 감지")
        return embed

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await core.safe_send_response(interaction, content="❌ 조회 관리자만 페이지를 넘길 수 있습니다.", ephemeral=True)
            return
        if self.page > 0:
            self.page -= 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="📄 1 / 1", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def page_indicator_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await core.safe_send_response(interaction, content="❌ 조회 관리자만 페이지를 넘길 수 있습니다.", ephemeral=True)
            return
        if self.page < self.max_page:
            self.page += 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="명단 TXT 다운로드", style=discord.ButtonStyle.primary, emoji="💾", row=0)
    async def download_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await core.safe_send_response(interaction, content="❌ 조회 관리자만 다운로드할 수 있습니다.", ephemeral=True)
            return
        await core.safe_defer(interaction, ephemeral=True)
        now_kst = datetime.datetime.now(core.KST)
        txt_lines = [
            f"=== {self.guild.name} 비활성 유저 명단 리포트 ===",
            f"기준 일수: {self.days_threshold}일 이상 미활동",
            f"스캔 일시: {now_kst.strftime('%Y-%m-%d %H:%M:%S KST')}",
            f"비활성 멤버 수: {len(self.inactive_list)}명 / 전체 {self.total_members}명",
            "--------------------------------------------------",
            "순번 | 유저 닉네임 | 유저 ID | 미활동 일수 | 마지막 활동일 | 서버 가입일"
        ]
        for idx, item in enumerate(self.inactive_list, start=1):
            mem = item["member"]
            joined = mem.joined_at.strftime("%Y-%m-%d") if mem.joined_at else "-"
            txt_lines.append(f"{idx} | {mem.display_name} | {mem.id} | {item['days_inactive']}일 | {item['last_activity_str']} | {joined}")

        txt_content = "\n".join(txt_lines).encode("utf-8")
        fp = io.BytesIO(txt_content)
        file = discord.File(fp, filename=f"inactive_users_{self.guild.id}_{now_kst.strftime('%Y%m%d_%H%M%S')}.txt")
        await interaction.followup.send(
            content=f"💾 **비활성 유저 `{len(self.inactive_list)}명` 명단 텍스트 파일 생성 완료**",
            file=file,
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(LoggerCog(bot))
