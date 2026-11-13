"""
norosi Bot - 이모지 반응 역할 (Reaction Roles) 종합 관리 Cog
- 서버 관리자 전용 대화형 스튜디오 패널 (/반응역할, !반응역할)
- 한 번에 발행하는 슬래시 커맨드 (/반응역할생성, /반응역할추가, /반응역할목록, /반응역할삭제)
- 유니코드 및 커스텀 이모지 완벽 지원, 봇 자동 리액션 추가
- 다중 선택(multiple) 및 단일 선택(unique) 모드 지원
- 봇 역할 서열(Hierarchy) 및 관리 권한 엄격 사전 검증
- 메시지/역할 삭제 시 DB 자동 동기화 및 정리
- 이모지 반응 + 상호작용 버튼(Button) 하이브리드 지원
"""

import asyncio
import datetime
import re
from typing import Optional, Union

import discord
from discord import app_commands
from discord.ext import commands

import core


def _is_admin_user(user: discord.abc.User, guild: Optional[discord.Guild], bot: commands.Bot) -> bool:
    """서버 관리자, 역할 관리 권한자 또는 봇 소유자인지 확인"""
    if not guild or not isinstance(user, discord.Member):
        return False
    if user.guild_permissions.administrator or user.guild_permissions.manage_roles:
        return True
    if core.BOT_OWNER_ID and user.id == core.BOT_OWNER_ID:
        return True
    return False


def _build_reaction_role_embed(
    title: str,
    description: str,
    roles_list: list[dict],
    mode: str = "multiple",
    guild: Optional[discord.Guild] = None,
    show_role_list: Optional[bool] = None,
    color: Optional[discord.Color] = None
) -> discord.Embed:
    """반응역할 안내 임베드를 예쁘고 깔끔하게 빌드 (첨부 사진 스타일 완벽 지원)"""
    # 디스코드 다크 테마/블러플 배경에 어울리는 색상 (기본 다크 슬레이트 0x2b2d31 또는 블러플)
    embed_color = color or discord.Color.from_rgb(43, 45, 49)

    # 사용자가 제목에 직접 넣은 이모지/포맷을 100% 보존 (접두사 임의 추가 방지)
    clean_title = (title or "역할 선택 안내").strip()

    embed = discord.Embed(
        title=clean_title,
        description=description or "아래 버튼을 눌러 원하는 역할을 획득하거나 해제하세요!",
        color=embed_color,
        timestamp=datetime.datetime.now(core.KST)
    )

    # 사용자가 직접 본문(description)을 상세하게 작성한 경우(첨부 사진 스타일),
    # 불필요한 역할 목록 필드를 표시하지 않고 깔끔하게 본문만 노출
    should_show_list = show_role_list
    if should_show_list is None:
        # 본문이 없거나 아주 짧을 때만 보조 목록 필드 출력
        should_show_list = not description or len(description.strip()) < 15

    if should_show_list and roles_list:
        lines = []
        for r_entry in roles_list:
            emoji_disp = r_entry.get("button_emoji") or r_entry.get("emoji", "✨")
            role_id = r_entry.get("role_id")
            role_name = r_entry.get("button_label") or r_entry.get("role_name", "역할")
            desc = r_entry.get("description", "").strip()

            role_mention = f"<@&{role_id}>" if role_id else f"`@{role_name}`"
            desc_part = f" — *{desc}*" if desc else ""
            lines.append(f"{emoji_disp} **:** {role_mention}{desc_part}")

        embed.add_field(
            name=f"📋 역할 배정 목록 ({len(roles_list)}개)",
            value="\n".join(lines),
            inline=False
        )

    return embed


# ==========================================
# 🔘 하이브리드 영구 버튼 View (이모지 외 버튼 클릭으로도 수령 지원)
# ==========================================
class PersistentRoleButton(discord.ui.Button):
    def __init__(
        self,
        role_id: int,
        label: str = "역할",
        emoji_str: Optional[str] = None,
        style: discord.ButtonStyle = discord.ButtonStyle.primary,
        custom_id: Optional[str] = None
    ):
        clean_label = (label or "역할").strip()[:80]

        # 유니코드 및 커스텀 이모지 완벽 지원
        button_emoji = None
        if emoji_str:
            e_obj, _, _ = core.parse_emoji_for_reaction(emoji_str)
            if isinstance(e_obj, (discord.PartialEmoji, discord.Emoji)):
                button_emoji = e_obj
            elif isinstance(e_obj, str) and e_obj.strip():
                button_emoji = e_obj.strip()

        btn_cid = custom_id or f"rr_btn_{role_id}"
        super().__init__(
            label=clean_label,
            style=style,
            emoji=button_emoji,
            custom_id=btn_cid
        )
        self.role_id = int(role_id)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return

        guild = interaction.guild
        member = interaction.user
        role = guild.get_role(self.role_id)
        if not role:
            await core.safe_send_response(interaction, "❌ 대상 역할을 찾을 수 없습니다 (삭제되었거나 변경됨).", ephemeral=True)
            return

        # 봇 권한 검사
        bot_member = guild.me or await guild.fetch_member(interaction.client.user.id)
        can_assign, reason = core.check_role_assignable(bot_member, role)
        if not can_assign:
            await core.safe_send_response(interaction, reason, ephemeral=True)
            return

        # 단일 선택 모드(unique) 체크
        data = await asyncio.to_thread(core.load_data)
        mid_s = str(interaction.message.id) if interaction.message else ""
        panel_cfg = data.get("reaction_roles", {}).get(mid_s, {})
        is_unique_mode = panel_cfg.get("mode") == "unique"

        # 역할 토글 (있으면 제거, 없으면 지급)
        if role in member.roles:
            try:
                await member.remove_roles(role, reason="반응역할 버튼 조작으로 회수")
                await core.safe_send_response(interaction, f"➖ **{role.name}** 역할이 해제되었습니다.", ephemeral=True)
            except discord.Forbidden:
                await core.safe_send_response(interaction, "🚨 봇에게 역할을 회수할 권한이 없습니다.", ephemeral=True)
        else:
            # 단일 선택 모드일 때 동일 패널 내 다른 역할들 자동 회수
            if is_unique_mode:
                other_role_ids = [
                    int(r["role_id"]) for r in panel_cfg.get("roles", [])
                    if int(r.get("role_id", 0)) != self.role_id
                ]
                roles_to_remove = [r for r in member.roles if r.id in other_role_ids]
                if roles_to_remove:
                    try:
                        await member.remove_roles(*roles_to_remove, reason="단일 선택 모드: 다른 역할 선택으로 자동 회수")
                    except Exception:
                        pass

            try:
                await member.add_roles(role, reason="반응역할 버튼 조작으로 지급")
                await core.safe_send_response(interaction, f"✅ **{role.name}** 역할이 지급되었습니다!", ephemeral=True)
            except discord.Forbidden:
                await core.safe_send_response(interaction, "🚨 봇에게 역할을 지급할 권한이 없습니다.", ephemeral=True)


class PersistentReactionRoleView(discord.ui.View):
    """메시지 하단에 표시되는 역할 토글 버튼 뷰"""
    def __init__(self, roles_list: list[dict]):
        super().__init__(timeout=None)
        style_map = {
            "primary": discord.ButtonStyle.primary,
            "blurple": discord.ButtonStyle.primary,
            "파랑": discord.ButtonStyle.primary,
            "보라": discord.ButtonStyle.primary,
            "secondary": discord.ButtonStyle.secondary,
            "grey": discord.ButtonStyle.secondary,
            "gray": discord.ButtonStyle.secondary,
            "회색": discord.ButtonStyle.secondary,
            "success": discord.ButtonStyle.success,
            "green": discord.ButtonStyle.success,
            "초록": discord.ButtonStyle.success,
            "danger": discord.ButtonStyle.danger,
            "red": discord.ButtonStyle.danger,
            "빨강": discord.ButtonStyle.danger,
        }
        for r_entry in roles_list[:25]:
            rid = r_entry.get("role_id")
            if not rid:
                continue
            btn_label = r_entry.get("button_label") or r_entry.get("role_name") or "역할"
            btn_emoji = r_entry.get("button_emoji") or r_entry.get("emoji")
            style_val = str(r_entry.get("style", "primary")).lower()
            btn_style = style_map.get(style_val, discord.ButtonStyle.primary)

            self.add_item(PersistentRoleButton(
                role_id=int(rid),
                label=btn_label,
                emoji_str=btn_emoji,
                style=btn_style,
                custom_id=f"rr_btn_{rid}"
            ))


# ==========================================
# 🎛️ 관리자용 대화형 스튜디오 UI & 모달들
# ==========================================
class ReactionRolePanelModal(core.SafeModal, title="➕ 새 반응역할 패널 생성"):
    p_title = discord.ui.TextInput(
        label="반응역할 패널 제목",
        placeholder="예: 📢 공지 알림 및 게임 역할 선택",
        default="📢 공지 알림 및 게임 역할 선택",
        max_length=100
    )
    p_desc = discord.ui.TextInput(
        label="안내 메시지 설명 문구",
        placeholder="예: 원하는 이모지를 클릭하여 역할을 받으세요!",
        default="아래 이모지를 클릭하여 원하는 역할을 자유롭게 선택하세요!",
        style=discord.TextStyle.paragraph,
        max_length=500
    )
    p_mode = discord.ui.TextInput(
        label="선택 모드 (1: 자유 다중 선택 / 2: 단일 선택)",
        placeholder="1 또는 2 입력 (기본: 1)",
        default="1",
        max_length=2
    )

    def __init__(self, studio_view: "ReactionRoleStudioView"):
        super().__init__()
        self.studio_view = studio_view

    async def on_submit(self, interaction: discord.Interaction):
        mode_val = "unique" if self.p_mode.value.strip() == "2" else "multiple"
        builder_view = ReactionRoleBuilderView(
            studio_view=self.studio_view,
            title=self.p_title.value.strip() or "반응역할 패널",
            description=self.p_desc.value.strip(),
            mode=mode_val
        )
        embed = builder_view.build_builder_embed()
        await core.safe_send_response(interaction, embed=embed, view=builder_view, ephemeral=True)


class AddRoleMappingModal(core.SafeModal, title="➕ 역할 및 버튼/이모지 매핑 추가"):
    m_role = discord.ui.TextInput(
        label="지급할 역할 이름 또는 역할 ID",
        placeholder="예: 공지알림 또는 역할 ID 숫자",
        max_length=50
    )
    m_btn_label = discord.ui.TextInput(
        label="버튼 이름 (버튼에 표시될 텍스트)",
        placeholder="예: [ 이용자 ] 또는 이용자 (비워두면 역할 이름)",
        required=False,
        max_length=50
    )
    m_emoji = discord.ui.TextInput(
        label="버튼/반응 이모지 (선택 사항)",
        placeholder="예: 🌑 또는 <:emoji:12345678> (비워둘 수 있음)",
        required=False,
        max_length=100
    )
    m_style = discord.ui.TextInput(
        label="버튼 색상 (보라 / 초록 / 회색 / 빨강)",
        placeholder="보라 (기본값)",
        default="보라",
        required=False,
        max_length=10
    )
    m_desc = discord.ui.TextInput(
        label="역할 한 줄 설명 (선택 사항)",
        placeholder="예: 서버 규정을 숙지한 주민 역할입니다.",
        required=False,
        max_length=100
    )

    def __init__(self, builder_view: "ReactionRoleBuilderView"):
        super().__init__()
        self.builder_view = builder_view

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await core.safe_send_response(interaction, "❌ 서버에서만 실행 가능합니다.", ephemeral=True)
            return

        role_query = self.m_role.value.strip()
        target_role: Optional[discord.Role] = None

        # 1. 역할 ID 조회
        if role_query.isdigit():
            target_role = guild.get_role(int(role_query))
        
        # 2. 역할 멘션 (<@&123456>) 파싱
        if not target_role:
            m_r = re.match(r"^<@&(\d+)>$", role_query)
            if m_r:
                target_role = guild.get_role(int(m_r.group(1)))

        # 3. 이름으로 조회
        if not target_role:
            target_role = discord.utils.get(guild.roles, name=role_query)

        # 4. 부분 일치 조회
        if not target_role:
            target_role = next((r for r in guild.roles if role_query.lower() in r.name.lower()), None)

        if not target_role:
            await core.safe_send_response(
                interaction,
                f"❌ `{role_query}`에 해당하는 역할을 서버에서 찾을 수 없습니다. 정확한 역할 이름 또는 ID를 입력해 주세요.",
                ephemeral=True
            )
            return

        # 봇 권한 서열 검사
        bot_member = guild.me or await guild.fetch_member(interaction.client.user.id)
        can_assign, reason = core.check_role_assignable(bot_member, target_role)
        if not can_assign:
            await core.safe_send_response(interaction, reason, ephemeral=True)
            return

        # 이모지 파싱 (비어있을 수 있음)
        emoji_input = self.m_emoji.value.strip()
        emoji_obj, emoji_disp, emoji_id = None, "", None
        if emoji_input:
            emoji_obj, emoji_disp, emoji_id = core.parse_emoji_for_reaction(emoji_input, guild)

        # 중복 검사
        if any(r["role_id"] == target_role.id for r in self.builder_view.roles_list):
            await core.safe_send_response(interaction, f"⚠️ 이미 목록에 등록된 역할입니다: `{target_role.name}`", ephemeral=True)
            return
        if emoji_disp and any(r["emoji"] == emoji_disp for r in self.builder_view.roles_list):
            await core.safe_send_response(interaction, f"⚠️ 이미 사용 중인 이모지입니다: {emoji_disp}", ephemeral=True)
            return

        btn_label = self.m_btn_label.value.strip() or target_role.name
        btn_style = self.m_style.value.strip() or "보라"

        self.builder_view.roles_list.append({
            "emoji": emoji_disp,
            "emoji_name": emoji_obj.name if hasattr(emoji_obj, "name") else str(emoji_obj or ""),
            "emoji_id": emoji_id,
            "button_emoji": emoji_disp,
            "button_label": btn_label,
            "style": btn_style,
            "role_id": target_role.id,
            "role_name": target_role.name,
            "description": self.m_desc.value.strip()
        })

        await interaction.response.edit_message(
            embed=self.builder_view.build_builder_embed(),
            view=self.builder_view
        )


class QuickRoleButtonModal(core.SafeModal, title="🚀 역할 버튼 패널 생성 (사진 스타일)"):
    m_title = discord.ui.TextInput(
        label="패널 제목",
        placeholder="예: 🌑 | 어두운 세상의 주민 되기",
        default="🌑 | 어두운 세상의 주민 되기",
        max_length=100
    )
    m_desc = discord.ui.TextInput(
        label="본문 내용 (줄바꿈 가능)",
        placeholder="예:\n⚠️ 본 역할 획득 시 서버 내 규정을 모두 숙지하신 것으로 간주합니다.\n\n✅ 아래 [ 이용자 ] 버튼을 눌러 이 어두운 세상의 주민이 되어주세요!",
        default="⚠️ 본 역할 획득 시 서버 내 규정을 모두 숙지하신 것으로 간주합니다.\n\n✅ 아래 [ 이용자 ] 버튼을 눌러 이 어두운 세상의 주민이 되어주세요!",
        style=discord.TextStyle.paragraph,
        max_length=1500
    )
    m_role = discord.ui.TextInput(
        label="지급할 역할 이름 또는 ID",
        placeholder="예: 이용자 또는 역할 ID",
        max_length=50
    )
    m_btn_label = discord.ui.TextInput(
        label="버튼에 표시될 이름 (버튼 텍스트)",
        placeholder="예: [ 이용자 ] 또는 이용자 (비워두면 역할 이름)",
        default="[ 이용자 ]",
        required=False,
        max_length=50
    )
    m_emoji = discord.ui.TextInput(
        label="버튼 이모지 (선택 사항)",
        placeholder="예: 🌑 또는 <:emoji:12345678> (비워둘 수 있음)",
        required=False,
        max_length=100
    )

    def __init__(self, target_channel: Optional[discord.TextChannel] = None):
        super().__init__()
        self.target_channel = target_channel

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await core.safe_send_response(interaction, "❌ 서버에서만 실행 가능합니다.", ephemeral=True)
            return

        out_channel = self.target_channel or interaction.channel
        if not isinstance(out_channel, discord.TextChannel):
            await core.safe_send_response(interaction, "❌ 텍스트 채널에서만 패널을 발행할 수 있습니다.", ephemeral=True)
            return

        role_query = self.m_role.value.strip()
        target_role: Optional[discord.Role] = None

        if role_query.isdigit():
            target_role = guild.get_role(int(role_query))
        if not target_role:
            m_r = re.match(r"^<@&(\d+)>$", role_query)
            if m_r:
                target_role = guild.get_role(int(m_r.group(1)))
        if not target_role:
            target_role = discord.utils.get(guild.roles, name=role_query)
        if not target_role:
            target_role = next((r for r in guild.roles if role_query.lower() in r.name.lower()), None)

        if not target_role:
            await core.safe_send_response(
                interaction,
                f"❌ `{role_query}` 역할을 찾을 수 없습니다. 정확한 역할 이름 또는 ID를 확인해 주세요.",
                ephemeral=True
            )
            return

        # 봇 권한 서열 검사
        bot_member = guild.me or await guild.fetch_member(interaction.client.user.id)
        can_assign, reason = core.check_role_assignable(bot_member, target_role)
        if not can_assign:
            await core.safe_send_response(interaction, reason, ephemeral=True)
            return

        # 이모지 파싱
        emoji_input = self.m_emoji.value.strip()
        emoji_obj, emoji_disp, emoji_id = None, "", None
        if emoji_input:
            emoji_obj, emoji_disp, emoji_id = core.parse_emoji_for_reaction(emoji_input, guild)

        btn_label = self.m_btn_label.value.strip() or target_role.name

        roles_list = [{
            "emoji": emoji_disp,
            "emoji_name": emoji_obj.name if hasattr(emoji_obj, "name") else str(emoji_obj or ""),
            "emoji_id": emoji_id,
            "button_emoji": emoji_disp,
            "button_label": btn_label,
            "style": "primary",
            "role_id": target_role.id,
            "role_name": target_role.name,
            "description": ""
        }]

        # 사진 스타일 임베드 빌드 (불필요한 필드 없이 제목과 본문만 깔끔하게 노출)
        panel_embed = _build_reaction_role_embed(
            title=self.m_title.value.strip(),
            description=self.m_desc.value.strip(),
            roles_list=roles_list,
            mode="multiple",
            guild=guild,
            show_role_list=False
        )

        persistent_view = PersistentReactionRoleView(roles_list)

        try:
            panel_msg = await out_channel.send(embed=panel_embed, view=persistent_view)
        except Exception as e:
            await core.safe_send_response(interaction, f"❌ 메시지 발행 실패: `{e}`", ephemeral=True)
            return

        # 이모지가 입력된 경우 리액션도 추가
        if emoji_obj:
            try:
                await panel_msg.add_reaction(emoji_obj)
            except Exception:
                pass

        # DB 저장
        data = await asyncio.to_thread(core.load_data)
        core.save_reaction_role_entry(
            data=data,
            message_id=panel_msg.id,
            guild_id=guild.id,
            channel_id=out_channel.id,
            roles=roles_list,
            title=self.m_title.value.strip(),
            description=self.m_desc.value.strip(),
            mode="multiple",
            creator_id=interaction.user.id
        )
        await asyncio.to_thread(core.save_data, data)

        await core.safe_send_response(
            interaction,
            (
                f"🎉 **역할 버튼 패널이 성공적으로 발행되었습니다!**\n\n"
                f"• **게시 채널:** {out_channel.mention}\n"
                f"• **역할:** {target_role.mention}\n"
                f"• **버튼 라벨:** `{btn_label}`\n"
                f"• **메시지 링크:** [👉 발행된 메시지 바로가기]({panel_msg.jump_url})"
            ),
            ephemeral=True
        )


class ReactionRoleBuilderView(core.SafeView):
    """역할-이모지 매핑을 추가하고 최종 발행하는 빌더 뷰"""
    def __init__(self, studio_view: "ReactionRoleStudioView", title: str, description: str, mode: str):
        super().__init__(timeout=600)
        self.studio_view = studio_view
        self.title = title
        self.description = description
        self.mode = mode
        self.roles_list: list[dict] = []
        self.target_channel: Optional[discord.TextChannel] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await super().interaction_check(interaction)
        is_admin = False
        if interaction.guild and isinstance(interaction.user, discord.Member):
            is_admin = (
                interaction.user.guild_permissions.administrator
                or interaction.user.guild_permissions.manage_roles
                or interaction.user.guild_permissions.manage_guild
            )
        if not is_admin and not await interaction.client.is_bot_owner_user(interaction.user):
            await core.safe_send_response(interaction, "❌ 관리자 또는 역할 관리 권한이 있는 멤버만 반응역할 빌더를 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    def build_builder_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🛠️ 반응역할 패널 제작 스튜디오",
            description=(
                f"• **패널 제목:** `{self.title}`\n"
                f"• **안내 문구:** {self.description}\n"
                f"• **선택 모드:** `{'단일 선택 (Unique)' if self.mode == 'unique' else '다중 선택 (Multiple)'}`\n"
                f"• **발행 대상 채널:** {self.target_channel.mention if self.target_channel else '*(아래 채널 선택 드롭다운에서 선택)*'}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.blue()
        )

        if self.roles_list:
            lines = []
            for idx, r in enumerate(self.roles_list, start=1):
                desc_p = f" ({r['description']})" if r.get('description') else ""
                lines.append(f"`#{idx}` {r['emoji']} ➔ <@&{r['role_id']}> (`{r['role_name']}`){desc_p}")
            embed.add_field(name=f"📋 등록된 역할 매핑 ({len(self.roles_list)}개)", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="📋 등록된 역할 매핑", value="아직 매핑된 역할이 없습니다. 아래 **`[➕ 역할-이모지 추가]`** 버튼을 눌러 추가하세요.", inline=False)

        embed.set_footer(text="설정이 완료되면 [🚀 이 채널에 패널 발행]을 눌러주세요!")
        return embed

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="📢 패널을 발행할 텍스트 채널을 선택하세요...",
        channel_types=[discord.ChannelType.text, discord.ChannelType.news],
        row=0
    )
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        ch = select.values[0]
        if isinstance(ch, discord.TextChannel):
            self.target_channel = ch
        else:
            self.target_channel = interaction.guild.get_channel(ch.id) if interaction.guild else None

        await interaction.response.edit_message(embed=self.build_builder_embed(), view=self)

    @discord.ui.button(label="➕ 역할-이모지 추가", style=discord.ButtonStyle.primary, row=1)
    async def add_role_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.roles_list) >= 20:
            await core.safe_send_response(interaction, "❌ 하나의 패널에는 최대 20개까지만 역할을 등록할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(AddRoleMappingModal(self))

    @discord.ui.button(label="🧹 마지막 매핑 삭제", style=discord.ButtonStyle.secondary, row=1)
    async def pop_role_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.roles_list:
            await core.safe_send_response(interaction, "ℹ️ 삭제할 매핑이 없습니다.", ephemeral=True)
            return
        removed = self.roles_list.pop()
        await interaction.response.edit_message(
            embed=self.build_builder_embed(),
            view=self
        )

    @discord.ui.button(label="🚀 이 채널에 패널 발행!", style=discord.ButtonStyle.success, row=1)
    async def publish_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if not guild:
            await core.safe_send_response(interaction, "❌ 서버에서만 실행할 수 있습니다.", ephemeral=True)
            return

        if not self.target_channel:
            self.target_channel = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None

        if not self.target_channel:
            await core.safe_send_response(interaction, "❌ 패널을 발행할 텍스트 채널을 먼저 선택해 주세요.", ephemeral=True)
            return

        if not self.roles_list:
            await core.safe_send_response(interaction, "❌ 최소 1개 이상의 역할-이모지 매핑을 추가해야 발행할 수 있습니다.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)

        # 봇 권한 검증 (채널 메시지 작성 및 리액션 권한)
        bot_member = guild.me or await guild.fetch_member(interaction.client.user.id)
        ch_perms = self.target_channel.permissions_for(bot_member)
        if not ch_perms.send_messages or not ch_perms.add_reactions or not ch_perms.embed_links:
            await interaction.edit_original_response(
                content=f"🚨 봇에게 {self.target_channel.mention} 채널에서 **'메시지 보내기'**, **'반응 추가하기'**, **'링크 첨부(임베드)'** 권한이 부족합니다."
            )
            return

        # 1. 안내 임베드 및 버튼 뷰 생성
        panel_embed = _build_reaction_role_embed(
            title=self.title,
            description=self.description,
            roles_list=self.roles_list,
            mode=self.mode,
            guild=guild
        )
        persistent_view = PersistentReactionRoleView(self.roles_list)

        try:
            panel_msg = await self.target_channel.send(embed=panel_embed, view=persistent_view)
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ 메시지 발행 실패: `{e}`")
            return

        # 2. 봇이 이모지 자동 리액션 추가
        failed_emojis = []
        for r_entry in self.roles_list:
            emoji_input = r_entry.get("emoji")
            emoji_obj, _, _ = core.parse_emoji_for_reaction(emoji_input, guild)
            try:
                if emoji_obj:
                    await panel_msg.add_reaction(emoji_obj)
                    await asyncio.sleep(0.3)  # 디스코드 속도 제한(Rate Limit) 방어 딜레이
            except Exception as e:
                failed_emojis.append(f"{emoji_input}: {e}")

        # 3. DB에 안전하게 저장
        data = await asyncio.to_thread(core.load_data)
        core.save_reaction_role_entry(
            data=data,
            message_id=panel_msg.id,
            guild_id=guild.id,
            channel_id=self.target_channel.id,
            roles=self.roles_list,
            title=self.title,
            description=self.description,
            mode=self.mode,
            creator_id=interaction.user.id
        )
        await asyncio.to_thread(core.save_data, data)

        jump_url = panel_msg.jump_url
        warn_msg = f"\n⚠️ 일부 이모지 반응 실패: `{', '.join(failed_emojis)}`" if failed_emojis else ""

        await interaction.edit_original_response(
            content=(
                f"🎉 **반응역할 패널이 성공적으로 발행되었습니다!**\n\n"
                f"• **게시 채널:** {self.target_channel.mention}\n"
                f"• **등록된 역할:** 총 `{len(self.roles_list)}개`\n"
                f"• **메시지 링크:** [👉 발행된 메시지 바로가기]({jump_url}){warn_msg}\n\n"
                f"💡 멤버들이 이모지를 누르거나 버튼을 클릭하면 즉시 역할이 부여/회수됩니다."
            ),
            embed=None,
            view=None
        )


class AttachExistingMessageModal(core.SafeModal, title="🔗 기존 메시지에 반응역할 연결"):
    msg_link_or_id = discord.ui.TextInput(
        label="기존 메시지 링크 또는 메시지 ID",
        placeholder="예: https://discord.com/channels/... 또는 1234567890",
        max_length=150
    )
    r_role = discord.ui.TextInput(
        label="지급할 역할 이름 또는 ID",
        placeholder="예: 게임알림 또는 역할 ID",
        max_length=50
    )
    r_emoji = discord.ui.TextInput(
        label="클릭할 이모지",
        placeholder="예: 🎮 또는 <:custom:123456>",
        max_length=100
    )
    r_desc = discord.ui.TextInput(
        label="역할 한 줄 설명 (선택 사항)",
        placeholder="예: 주말 게임 내전 알림",
        required=False,
        max_length=100
    )

    def __init__(self, studio_view: "ReactionRoleStudioView"):
        super().__init__()
        self.studio_view = studio_view

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await core.safe_send_response(interaction, "❌ 서버에서만 실행 가능합니다.", ephemeral=True)
            return

        raw_msg_input = self.msg_link_or_id.value.strip()
        channel_id = None
        message_id = None

        # URL 파싱: https://discord.com/channels/guild_id/channel_id/message_id
        m_url = re.search(r"discord\.com/channels/\d+/(\d+)/(\d+)", raw_msg_input)
        if m_url:
            channel_id = int(m_url.group(1))
            message_id = int(m_url.group(2))
        elif raw_msg_input.isdigit():
            message_id = int(raw_msg_input)
            channel_id = interaction.channel_id
        else:
            await core.safe_send_response(interaction, "❌ 올바른 메시지 링크 또는 ID를 입력해 주세요.", ephemeral=True)
            return

        channel = guild.get_channel(channel_id) or await guild.fetch_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await core.safe_send_response(interaction, "❌ 텍스트 채널의 메시지만 지정할 수 있습니다.", ephemeral=True)
            return

        try:
            target_msg = await channel.fetch_message(message_id)
        except Exception:
            await core.safe_send_response(interaction, "❌ 메시지를 찾을 수 없습니다. 링크와 채널 권한을 확인해 주세요.", ephemeral=True)
            return

        # 역할 찾기
        role_q = self.r_role.value.strip()
        target_role = None
        if role_q.isdigit():
            target_role = guild.get_role(int(role_q))
        if not target_role:
            m_r = re.match(r"^<@&(\d+)>$", role_q)
            if m_r:
                target_role = guild.get_role(int(m_r.group(1)))
        if not target_role:
            target_role = discord.utils.get(guild.roles, name=role_q)
        if not target_role:
            target_role = next((r for r in guild.roles if role_q.lower() in r.name.lower()), None)

        if not target_role:
            await core.safe_send_response(interaction, f"❌ `{role_q}` 역할을 찾을 수 없습니다.", ephemeral=True)
            return

        bot_member = guild.me or await guild.fetch_member(interaction.client.user.id)
        can_assign, reason = core.check_role_assignable(bot_member, target_role)
        if not can_assign:
            await core.safe_send_response(interaction, reason, ephemeral=True)
            return

        emoji_obj, emoji_disp, emoji_id = core.parse_emoji_for_reaction(self.r_emoji.value.strip(), guild)
        if not emoji_obj:
            await core.safe_send_response(interaction, "❌ 올바른 이모지를 입력해 주세요.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)

        data = await asyncio.to_thread(core.load_data)
        rr_map = data.setdefault("reaction_roles", {})
        mid_str = str(message_id)

        if mid_str not in rr_map:
            rr_map[mid_str] = {
                "guild_id": guild.id,
                "channel_id": channel.id,
                "title": "기존 메시지 반응 역할",
                "description": "",
                "mode": "multiple",
                "roles": [],
                "created_at": core.get_today_str(),
                "creator_id": interaction.user.id
            }

        cfg = rr_map[mid_str]
        # 중복 체크
        if any(r["role_id"] == target_role.id for r in cfg["roles"]):
            await interaction.edit_original_response(content=f"⚠️ 이미 해당 메시지에 바인딩된 역할입니다: `{target_role.name}`")
            return

        cfg["roles"].append({
            "emoji": emoji_disp,
            "emoji_name": emoji_obj.name if hasattr(emoji_obj, "name") else str(emoji_obj),
            "emoji_id": emoji_id,
            "role_id": target_role.id,
            "role_name": target_role.name,
            "description": self.r_desc.value.strip()
        })

        await asyncio.to_thread(core.save_data, data)

        # 봇이 메시지에 이모지 반응 추가
        try:
            await target_msg.add_reaction(emoji_obj)
        except Exception as e:
            await interaction.edit_original_response(content=f"⚠️ DB에는 등록되었으나 메시지에 이모지 추가 실패: `{e}`")
            return

        await interaction.edit_original_response(
            content=(
                f"✅ **기존 메시지에 반응역할이 성공적으로 추가되었습니다!**\n\n"
                f"• **메시지:** [👉 바로가기]({target_msg.jump_url})\n"
                f"• **추가된 이모지:** {emoji_disp}\n"
                f"• **지급 역할:** {target_role.mention} (`{target_role.name}`)\n"
                f"• **총 등록 역할 수:** `{len(cfg['roles'])}개`"
            )
        )


class ReactionRoleListView(core.SafeView):
    """현재 서버에 등록된 반응역할 목록 열람 및 삭제 지원 뷰"""
    def __init__(self, guild_id: int, entries: list[tuple[str, dict]]):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.entries = entries
        self.page = 0
        self.page_size = 5
        self._update_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await super().interaction_check(interaction)
        is_admin = False
        if interaction.guild and isinstance(interaction.user, discord.Member):
            is_admin = (
                interaction.user.guild_permissions.administrator
                or interaction.user.guild_permissions.manage_roles
                or interaction.user.guild_permissions.manage_guild
            )
        if not is_admin and not await interaction.client.is_bot_owner_user(interaction.user):
            await core.safe_send_response(interaction, "❌ 관리자 또는 역할 관리 권한이 있는 멤버만 반응역할 목록을 관리할 수 있습니다.", ephemeral=True)
            return False
        return True

    @property
    def max_page(self) -> int:
        return max(0, (len(self.entries) - 1) // self.page_size)

    def _update_components(self):
        self.prev_btn.disabled = (self.page <= 0)
        self.next_btn.disabled = (self.page >= self.max_page)
        self.page_indicator.label = f"📄 {self.page + 1} / {self.max_page + 1}"

        # 삭제 드롭다운 옵션 갱신
        start = self.page * self.page_size
        chunk = self.entries[start:start + self.page_size]
        if not chunk:
            self.delete_select.options = [discord.SelectOption(label="등록된 반응역할 없음", value="NONE")]
            self.delete_select.disabled = True
        else:
            opts = []
            for mid, cfg in chunk:
                r_cnt = len(cfg.get("roles", []))
                opts.append(discord.SelectOption(
                    label=f"{cfg.get('title', '반응역할')} ({r_cnt}개 역할)"[:95],
                    value=mid,
                    description=f"ID: {mid} | 채널: {cfg.get('channel_id')}"[:95],
                    emoji="🗑️"
                ))
            self.delete_select.options = opts
            self.delete_select.disabled = False

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="📋 서버 등록 반응역할 전체 목록",
            description=f"현재 서버에 활성화된 반응역할 총 **`{len(self.entries)}개`**",
            color=discord.Color.teal()
        )

        if not self.entries:
            embed.description = "📭 현재 서버에 등록된 반응역할이 없습니다."
            return embed

        start = self.page * self.page_size
        chunk = self.entries[start:start + self.page_size]

        for idx, (mid, cfg) in enumerate(chunk, start=start + 1):
            ch_id = cfg.get("channel_id")
            roles_p = []
            for r in cfg.get("roles", []):
                roles_p.append(f"{r['emoji']} <@&{r['role_id']}>")
            roles_text = " • ".join(roles_p) if roles_p else "*(역할 없음)*"

            jump_link = f"https://discord.com/channels/{self.guild_id}/{ch_id}/{mid}"
            embed.add_field(
                name=f"`#{idx:02d}` 🎭 {cfg.get('title', '반응역할')} (메시지 ID: `{mid}`)",
                value=(
                    f"• **채널:** <#{ch_id}> ([🔗 메시지 바로가기]({jump_link}))\n"
                    f"• **모드:** `{'단일 선택' if cfg.get('mode') == 'unique' else '다중 선택'}`\n"
                    f"• **배정 역할:** {roles_text}\n"
                    f"• **등록일:** `{cfg.get('created_at', '-')}`"
                ),
                inline=False
            )

        embed.set_footer(text="하단 드롭다운에서 삭제할 반응역할을 선택하면 즉시 등록이 해제됩니다.")
        return embed

    @discord.ui.select(placeholder="🗑️ 등록 해제할 반응역할 메시지를 선택하세요...", row=0, options=[discord.SelectOption(label="없음", value="NONE")])
    async def delete_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        if val == "NONE":
            await core.safe_defer(interaction)
            return

        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        ok = core.remove_reaction_role_entry(data, int(val))
        if ok:
            await asyncio.to_thread(core.save_data, data)
            self.entries = [e for e in self.entries if e[0] != val]
            self.page = min(self.page, self.max_page)
            self._update_components()
            await interaction.edit_original_response(
                content=f"✅ 메시지 ID `{val}`의 반응역할 등록을 정상적으로 해제했습니다!",
                embed=self.build_embed(),
                view=self
            )
        else:
            await interaction.edit_original_response(content="ℹ️ 이미 삭제되었거나 찾을 수 없는 반응역할입니다.")

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary, row=1)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._update_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="📄 1 / 1", style=discord.ButtonStyle.secondary, disabled=True, row=1)
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.max_page, self.page + 1)
        self._update_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class ReactionRoleStudioView(core.SafeView):
    """서버 관리자용 반응역할 종합 메인 스튜디오 뷰"""
    def __init__(self, guild: discord.Guild, author: discord.Member):
        super().__init__(timeout=600)
        self.guild = guild
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await super().interaction_check(interaction)
        is_admin = False
        if interaction.guild and isinstance(interaction.user, discord.Member):
            is_admin = (
                interaction.user.guild_permissions.administrator
                or interaction.user.guild_permissions.manage_roles
                or interaction.user.guild_permissions.manage_guild
            )
        if not is_admin and not await interaction.client.is_bot_owner_user(interaction.user):
            await core.safe_send_response(interaction, "❌ 관리자 또는 역할 관리 권한이 있는 멤버만 반응역할 스튜디오를 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    def build_dashboard_embed(self) -> discord.Embed:
        data = core.get_cached_data()
        guild_rr = core.get_guild_reaction_roles(data, self.guild.id)
        total_panels = len(guild_rr)
        total_roles = sum(len(c.get("roles", [])) for c in guild_rr.values())

        embed = discord.Embed(
            title="🎭 이모지 반응 역할 (Reaction Roles) 마스터 스튜디오",
            description=(
                f"안녕하세요, **{self.author.display_name}** 관리자님!\n"
                "서버 멤버들이 이모지를 누르면 원하는 역할을 자동으로 부여/회수하는 반응 역할을 간편하게 제작하고 관리합니다.\n\n"
                f"📊 **현재 서버 ({self.guild.name}) 현황:**\n"
                f"• 📜 활성 반응역할 패널: **`{total_panels}개`**\n"
                f"• 🛡️ 배정 중인 역할 총합: **`{total_roles}개`**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "**💡 주요 기능 안내:**\n"
                "• **`[🚀 사진 스타일 버튼 패널]`** : 제목/본문/버튼이름/이모지를 자유롭게 넣어 깔끔한 버튼 패널 즉시 제작\n"
                "• **`[➕ 새 패널 발행]`** : 단계별 빌더를 통해 다중 역할 안내 임베드 패널 발행\n"
                "• **`[🔗 기존 메시지 연결]`** : 이미 작성된 공지나 규칙 글에 이모지 역할 추가\n"
                "• **`[📋 등록 목록 & 관리]`** : 현재 서버에 띄워진 반응역할 확인 및 원클릭 해제\n"
                "• **`[🛡️ 봇 권한 상태 점검]`** : 봇 역할 위치와 권한 오류를 사전 진단"
            ),
            color=discord.Color.from_rgb(114, 137, 218),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_footer(text="서버 관리자 및 역할 관리 권한자 전용 • norosi Role Engine")
        return embed

    @discord.ui.button(label="🚀 사진 스타일 버튼 패널", style=discord.ButtonStyle.primary, emoji="🚀", row=0)
    async def quick_button_panel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(QuickRoleButtonModal())

    @discord.ui.button(label="➕ 새 패널 발행", style=discord.ButtonStyle.success, emoji="➕", row=0)
    async def create_panel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReactionRolePanelModal(self))

    @discord.ui.button(label="🔗 기존 메시지에 연결", style=discord.ButtonStyle.secondary, emoji="🔗", row=0)
    async def attach_existing_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AttachExistingMessageModal(self))

    @discord.ui.button(label="📋 등록 목록 & 관리", style=discord.ButtonStyle.secondary, emoji="📋", row=1)
    async def list_panels_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await asyncio.to_thread(core.load_data)
        guild_rr = core.get_guild_reaction_roles(data, self.guild.id)
        entries = list(guild_rr.items())
        list_view = ReactionRoleListView(self.guild.id, entries)
        await core.safe_send_response(interaction, embed=list_view.build_embed(), view=list_view, ephemeral=True)

    @discord.ui.button(label="🛡️ 봇 권한 상태 점검", style=discord.ButtonStyle.secondary, emoji="🛡️", row=1)
    async def check_perms_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot_member = self.guild.me or await self.guild.fetch_member(interaction.client.user.id)
        has_manage_roles = bot_member.guild_permissions.manage_roles
        top_role = bot_member.top_role

        status_icon = "✅ 정상" if has_manage_roles else "🚨 권한 부족 (Manage Roles 필요)"

        embed = discord.Embed(
            title="🛡️ 봇 역할 관리 권한 자가진단",
            description=(
                f"• **'역할 관리' 권한 여부:** {status_icon}\n"
                f"• **봇의 최고 역할 위치:** {top_role.mention} (`{top_role.name}` / 서열 `{top_role.position}`)\n\n"
                "💡 **반응 역할이 작동하지 않을 때 체크리스트:**\n"
                "1. 서버 설정 → [역할]에서 봇 역할이 부여하려는 역할보다 **반드시 위에** 위치해야 합니다.\n"
                "2. 봇에게 '메시지에 반응 추가하기' 및 '외부 이모지 사용' 권한이 켜져 있는지 확인해 주세요."
            ),
            color=discord.Color.green() if has_manage_roles else discord.Color.red()
        )
        await core.safe_send_response(interaction, embed=embed, ephemeral=True)

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, emoji="🔄", row=1)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.build_dashboard_embed(), view=self)


# ==========================================
# 🚀 Roles Cog 메인 클래스
# ==========================================
class Roles(commands.Cog, name="역할"):
    """서버 관리자용 이모지 반응 역할 (Reaction Roles) 관리 모듈"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ----------------------------------------------------
    # 관리자 명령어 (/반응역할, !반응역할)
    # ----------------------------------------------------
    @app_commands.command(name="반응역할", description="[관리자 전용] 이모지 반응 역할 생성, 조회, 삭제 종합 스튜디오를 엽니다.")
    async def slash_reaction_role_studio(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return

        if not _is_admin_user(interaction.user, interaction.guild, self.bot):
            await core.safe_send_response(
                interaction,
                "❌ 이 명령어는 **서버 관리자** 또는 **'역할 관리' 권한**을 보유한 멤버만 실행할 수 있습니다.",
                ephemeral=True
            )
            return

        studio = ReactionRoleStudioView(interaction.guild, interaction.user)
        await core.safe_send_response(interaction, embed=studio.build_dashboard_embed(), view=studio, ephemeral=True)

    @commands.command(name="반응역할", aliases=["반응역할스튜디오", "리액션롤", "역할지급", "이모지역할"])
    async def prefix_reaction_role(self, ctx: commands.Context):
        """[관리자 전용] 채팅창에서 반응역할 마스터 스튜디오 호출"""
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            await ctx.send("❌ 서버 채널에서만 사용할 수 있습니다.")
            return

        if not _is_admin_user(ctx.author, ctx.guild, self.bot):
            await ctx.send("❌ 이 명령어는 **서버 관리자** 또는 **'역할 관리' 권한**을 보유한 멤버만 실행할 수 있습니다.")
            return

        studio = ReactionRoleStudioView(ctx.guild, ctx.author)
        await ctx.send(embed=studio.build_dashboard_embed(), view=studio)

    # ----------------------------------------------------
    # 사진 스타일 역할 버튼 패널 생성 (/역할버튼제작, /역할버튼생성)
    # ----------------------------------------------------
    @app_commands.command(name="역할버튼제작", description="[관리자 전용] 팝업 창에서 제목, 본문, 버튼 이름과 이모지를 직접 적어 역할 버튼을 발행합니다.")
    @app_commands.describe(채널="패널을 발행할 채널 (선택, 기본: 현재 채널)")
    async def slash_create_role_button_modal(
        self,
        interaction: discord.Interaction,
        채널: Optional[discord.TextChannel] = None
    ):
        """[관리자 전용] 첨부 사진과 같은 형태의 역할 버튼 패널을 모달 대화창으로 간편 제작"""
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await core.safe_send_response(interaction, "❌ 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return

        if not _is_admin_user(interaction.user, interaction.guild, self.bot):
            await core.safe_send_response(
                interaction,
                "❌ 이 명령어는 **서버 관리자** 또는 **'역할 관리' 권한**을 보유한 멤버만 실행할 수 있습니다.",
                ephemeral=True
            )
            return

        target_ch = 채널 or interaction.channel
        await interaction.response.send_modal(QuickRoleButtonModal(target_channel=target_ch))

    @app_commands.command(name="역할버튼생성", description="[관리자 전용] 제목, 본문, 버튼 이름과 이모지를 직접 지정하여 역할 버튼 패널을 즉시 발행합니다.")
    @app_commands.describe(
        제목="패널 제목 (예: 🌑 | 어두운 세상의 주민 되기)",
        본문="패널 본문 안내 문구 (줄바꿈 가능)",
        역할="버튼 클릭 시 지급/회수할 디스코드 역할",
        버튼이름="버튼에 표시될 텍스트 (예: [ 이용자 ] 또는 이용자, 비워두면 역할 이름)",
        버튼이모지="버튼에 붙일 이모지 (예: 🌑, 선택 사항)",
        버튼색상="버튼 색상 (보라, 초록, 회색, 빨강 중 선택, 기본: 보라)",
        채널="패널을 게시할 텍스트 채널 (선택, 기본: 현재 채널)",
        단일선택="다른 버튼 클릭 시 이전 역할 자동 해제 여부 (기본: 아니오)",
        역할2="두 번째 역할 (선택)",
        버튼이름2="두 번째 버튼 텍스트 (선택)",
        버튼이모지2="두 번째 버튼 이모지 (선택)",
        버튼색상2="두 번째 버튼 색상 (기본: 보라)",
        역할3="세 번째 역할 (선택)",
        버튼이름3="세 번째 버튼 텍스트 (선택)",
        버튼이모지3="세 번째 버튼 이모지 (선택)",
        버튼색상3="세 번째 버튼 색상 (기본: 보라)"
    )
    @app_commands.choices(
        버튼색상=[
            app_commands.Choice(name="🟣 보라색 (Primary / Blurple)", value="보라"),
            app_commands.Choice(name="🟢 초록색 (Success / Green)", value="초록"),
            app_commands.Choice(name="⚪ 회색 (Secondary / Grey)", value="회색"),
            app_commands.Choice(name="🔴 빨간색 (Danger / Red)", value="빨강")
        ],
        버튼색상2=[
            app_commands.Choice(name="🟣 보라색 (Primary / Blurple)", value="보라"),
            app_commands.Choice(name="🟢 초록색 (Success / Green)", value="초록"),
            app_commands.Choice(name="⚪ 회색 (Secondary / Grey)", value="회색"),
            app_commands.Choice(name="🔴 빨간색 (Danger / Red)", value="빨강")
        ],
        버튼색상3=[
            app_commands.Choice(name="🟣 보라색 (Primary / Blurple)", value="보라"),
            app_commands.Choice(name="🟢 초록색 (Success / Green)", value="초록"),
            app_commands.Choice(name="⚪ 회색 (Secondary / Grey)", value="회색"),
            app_commands.Choice(name="🔴 빨간색 (Danger / Red)", value="빨강")
        ]
    )
    async def slash_create_custom_role_button(
        self,
        interaction: discord.Interaction,
        제목: str,
        본문: str,
        역할: discord.Role,
        버튼이름: Optional[str] = None,
        버튼이모지: Optional[str] = None,
        버튼색상: Optional[str] = "보라",
        채널: Optional[discord.TextChannel] = None,
        단일선택: bool = False,
        역할2: Optional[discord.Role] = None,
        버튼이름2: Optional[str] = None,
        버튼이모지2: Optional[str] = None,
        버튼색상2: Optional[str] = "보라",
        역할3: Optional[discord.Role] = None,
        버튼이름3: Optional[str] = None,
        버튼이모지3: Optional[str] = None,
        버튼색상3: Optional[str] = "보라"
    ):
        guild = interaction.guild
        if not guild:
            await core.safe_send_response(interaction, "❌ 서버에서만 사용 가능합니다.", ephemeral=True)
            return

        if not _is_admin_user(interaction.user, guild, self.bot):
            await core.safe_send_response(
                interaction,
                "❌ 이 명령어는 **서버 관리자** 또는 **'역할 관리' 권한**을 보유한 멤버만 실행할 수 있습니다.",
                ephemeral=True
            )
            return

        await core.safe_defer(interaction, ephemeral=True)

        target_ch = 채널 or interaction.channel
        if not isinstance(target_ch, discord.TextChannel):
            await interaction.edit_original_response(content="❌ 텍스트 채널에서만 패널을 발행할 수 있습니다.")
            return

        bot_member = guild.me or await guild.fetch_member(interaction.client.user.id)

        items = [
            (역할, 버튼이름, 버튼이모지, 버튼색상),
            (역할2, 버튼이름2, 버튼이모지2, 버튼색상2),
            (역할3, 버튼이름3, 버튼이모지3, 버튼색상3),
        ]

        roles_list = []
        for r_obj, b_label, b_emo, b_style in items:
            if not r_obj:
                continue
            can_assign, reason = core.check_role_assignable(bot_member, r_obj)
            if not can_assign:
                await interaction.edit_original_response(content=f"⚠️ `{r_obj.name}` 검증 실패: {reason}")
                return

            emoji_obj, emoji_disp, emoji_id = None, "", None
            if b_emo:
                emoji_obj, emoji_disp, emoji_id = core.parse_emoji_for_reaction(b_emo, guild)

            clean_label = (b_label or "").strip() or r_obj.name

            roles_list.append({
                "emoji": emoji_disp,
                "emoji_name": emoji_obj.name if hasattr(emoji_obj, "name") else str(emoji_obj or ""),
                "emoji_id": emoji_id,
                "button_emoji": emoji_disp,
                "button_label": clean_label,
                "style": b_style or "보라",
                "role_id": r_obj.id,
                "role_name": r_obj.name,
                "description": ""
            })

        if not roles_list:
            await interaction.edit_original_response(content="❌ 유효한 역할이 지정되지 않았습니다.")
            return

        mode_val = "unique" if 단일선택 else "multiple"
        panel_embed = _build_reaction_role_embed(
            title=제목,
            description=본문,
            roles_list=roles_list,
            mode=mode_val,
            guild=guild,
            show_role_list=False
        )
        persistent_view = PersistentReactionRoleView(roles_list)

        try:
            panel_msg = await target_ch.send(embed=panel_embed, view=persistent_view)
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ 메시지 발행 실패: `{e}`")
            return

        # 이모지가 지정된 경우 리액션 추가
        for r_entry in roles_list:
            if r_entry.get("emoji"):
                e_obj, _, _ = core.parse_emoji_for_reaction(r_entry["emoji"], guild)
                try:
                    if e_obj:
                        await panel_msg.add_reaction(e_obj)
                        await asyncio.sleep(0.3)
                except Exception:
                    pass

        # DB 저장
        data = await asyncio.to_thread(core.load_data)
        core.save_reaction_role_entry(
            data=data,
            message_id=panel_msg.id,
            guild_id=guild.id,
            channel_id=target_ch.id,
            roles=roles_list,
            title=제목,
            description=본문,
            mode=mode_val,
            creator_id=interaction.user.id
        )
        await asyncio.to_thread(core.save_data, data)

        await interaction.edit_original_response(
            content=(
                f"🎉 **역할 버튼 패널이 성공적으로 발행되었습니다!**\n"
                f"• 채널: {target_ch.mention}\n"
                f"• 배정 역할 수: `{len(roles_list)}개`\n"
                f"• 바로가기: [👉 메시지로 이동]({panel_msg.jump_url})"
            )
        )

    # ----------------------------------------------------
    # 단축 생성 명령어 (/반응역할생성)
    # ----------------------------------------------------
    @app_commands.command(name="반응역할생성", description="[관리자 전용] 지정 채널에 새 반응역할 안내 패널을 즉시 발행합니다.")
    @app_commands.describe(
        채널="반응역할 패널을 게시할 텍스트 채널",
        제목="패널의 제목 (예: 공지 알림 및 게임 역할 선택)",
        설명="패널의 안내 문구",
        단일선택="하나의 역할만 선택 가능하게 할지 여부 (기본: 아니오)",
        역할1="첫 번째로 지급할 역할",
        이모지1="첫 번째 역할의 클릭 이모지 (예: 📢 또는 🔥)",
        버튼이름1="첫 번째 버튼 이름 (선택, 비워두면 역할 이름)",
        역할2="두 번째 역할 (선택)",
        이모지2="두 번째 이모지 (선택)",
        버튼이름2="두 번째 버튼 이름 (선택)",
        역할3="세 번째 역할 (선택)",
        이모지3="세 번째 이모지 (선택)",
        역할4="네 번째 역할 (선택)",
        이모지4="네 번째 이모지 (선택)",
        역할5="다섯 번째 역할 (선택)",
        이모지5="다섯 번째 이모지 (선택)"
    )
    async def slash_create_reaction_role(
        self,
        interaction: discord.Interaction,
        채널: discord.TextChannel,
        제목: str,
        역할1: discord.Role,
        이모지1: str,
        설명: str = "아래 이모지를 클릭하여 원하는 역할을 자유롭게 받으세요!",
        단일선택: bool = False,
        버튼이름1: Optional[str] = None,
        역할2: Optional[discord.Role] = None,
        이모지2: Optional[str] = None,
        버튼이름2: Optional[str] = None,
        역할3: Optional[discord.Role] = None,
        이모지3: Optional[str] = None,
        역할4: Optional[discord.Role] = None,
        이모지4: Optional[str] = None,
        역할5: Optional[discord.Role] = None,
        이모지5: Optional[str] = None
    ):
        guild = interaction.guild
        if not guild:
            await core.safe_send_response(interaction, "❌ 서버에서만 사용 가능합니다.", ephemeral=True)
            return

        if not _is_admin_user(interaction.user, guild, self.bot):
            await core.safe_send_response(
                interaction,
                "❌ 이 명령어는 **서버 관리자** 또는 **'역할 관리' 권한**을 보유한 멤버만 실행할 수 있습니다.",
                ephemeral=True
            )
            return

        await core.safe_defer(interaction, ephemeral=True)

        bot_member = guild.me or await guild.fetch_member(interaction.client.user.id)
        pairs = [
            (역할1, 이모지1, 버튼이름1),
            (역할2, 이모지2, 버튼이름2),
            (역할3, 이모지3, None),
            (역할4, 이모지4, None),
            (역할5, 이모지5, None)
        ]

        roles_list = []
        for r_obj, e_str, b_lbl in pairs:
            if not r_obj or not e_str:
                continue
            can_assign, reason = core.check_role_assignable(bot_member, r_obj)
            if not can_assign:
                await interaction.edit_original_response(content=f"⚠️ `{r_obj.name}` 검증 실패: {reason}")
                return
            e_obj, e_disp, e_id = core.parse_emoji_for_reaction(e_str, guild)
            if not e_obj:
                await interaction.edit_original_response(content=f"⚠️ `{e_str}` 이모지를 인식하지 못했습니다.")
                return
            roles_list.append({
                "emoji": e_disp,
                "emoji_name": e_obj.name if hasattr(e_obj, "name") else str(e_obj),
                "emoji_id": e_id,
                "button_emoji": e_disp,
                "button_label": (b_lbl or "").strip() or r_obj.name,
                "style": "primary",
                "role_id": r_obj.id,
                "role_name": r_obj.name,
                "description": ""
            })

        if not roles_list:
            await interaction.edit_original_response(content="❌ 유효한 역할과 이모지 쌍이 없습니다.")
            return

        mode_val = "unique" if 단일선택 else "multiple"
        panel_embed = _build_reaction_role_embed(
            title=제목,
            description=설명,
            roles_list=roles_list,
            mode=mode_val,
            guild=guild
        )
        persistent_view = PersistentReactionRoleView(roles_list)

        try:
            panel_msg = await 채널.send(embed=panel_embed, view=persistent_view)
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ 메시지 발행 실패: `{e}`")
            return

        for r_entry in roles_list:
            e_obj, _, _ = core.parse_emoji_for_reaction(r_entry["emoji"], guild)
            try:
                if e_obj:
                    await panel_msg.add_reaction(e_obj)
                    await asyncio.sleep(0.3)
            except Exception:
                pass

        data = await asyncio.to_thread(core.load_data)
        core.save_reaction_role_entry(
            data=data,
            message_id=panel_msg.id,
            guild_id=guild.id,
            channel_id=채널.id,
            roles=roles_list,
            title=제목,
            description=설명,
            mode=mode_val,
            creator_id=interaction.user.id
        )
        await asyncio.to_thread(core.save_data, data)

        await interaction.edit_original_response(
            content=(
                f"🎉 **반응역할 패널이 정상적으로 발행되었습니다!**\n"
                f"• 채널: {채널.mention}\n"
                f"• 배정 역할 수: `{len(roles_list)}개`\n"
                f"• 바로가기: [👉 메시지로 이동]({panel_msg.jump_url})"
            )
        )

    # ----------------------------------------------------
    # 단축 목록 및 삭제 명령어 (/반응역할목록, /반응역할삭제)
    # ----------------------------------------------------
    @app_commands.command(name="반응역할목록", description="[관리자 전용] 현재 서버에 등록된 반응역할 전체 목록을 조회합니다.")
    async def slash_list_reaction_roles(self, interaction: discord.Interaction):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버에서만 실행 가능합니다.", ephemeral=True)
            return

        if not _is_admin_user(interaction.user, interaction.guild, self.bot):
            await core.safe_send_response(
                interaction,
                "❌ 이 명령어는 **서버 관리자** 또는 **'역할 관리' 권한**을 보유한 멤버만 실행할 수 있습니다.",
                ephemeral=True
            )
            return

        data = await asyncio.to_thread(core.load_data)
        guild_rr = core.get_guild_reaction_roles(data, interaction.guild.id)
        entries = list(guild_rr.items())
        list_view = ReactionRoleListView(interaction.guild.id, entries)
        await core.safe_send_response(interaction, embed=list_view.build_embed(), view=list_view, ephemeral=True)

    @app_commands.command(name="반응역할삭제", description="[관리자 전용] 메시지 링크 또는 ID를 지정하여 반응역할 설정을 삭제합니다.")
    @app_commands.describe(메시지링크_또는_id="삭제할 반응역할 메시지의 링크 또는 ID")
    async def slash_delete_reaction_role(self, interaction: discord.Interaction, 메시지링크_또는_id: str):
        if not interaction.guild:
            await core.safe_send_response(interaction, "❌ 서버에서만 실행 가능합니다.", ephemeral=True)
            return

        if not _is_admin_user(interaction.user, interaction.guild, self.bot):
            await core.safe_send_response(
                interaction,
                "❌ 이 명령어는 **서버 관리자** 또는 **'역할 관리' 권한**을 보유한 멤버만 실행할 수 있습니다.",
                ephemeral=True
            )
            return

        raw = 메시지링크_또는_id.strip()
        m_id = None
        m_url = re.search(r"discord\.com/channels/\d+/\d+/(\d+)", raw)
        if m_url:
            m_id = int(m_url.group(1))
        elif raw.isdigit():
            m_id = int(raw)

        if not m_id:
            await core.safe_send_response(interaction, "❌ 올바른 메시지 링크 또는 ID를 입력해 주세요.", ephemeral=True)
            return

        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        ok = core.remove_reaction_role_entry(data, m_id)
        if ok:
            await asyncio.to_thread(core.save_data, data)
            await interaction.edit_original_response(content=f"✅ 메시지 ID `{m_id}`의 반응역할 등록이 정상적으로 해제되었습니다.")
        else:
            await interaction.edit_original_response(content="ℹ️ 등록되어 있지 않거나 이미 삭제된 반응역할 메시지입니다.")

    # ====================================================
    # 🎧 핵심 이벤트 리스너: on_raw_reaction_add
    # ====================================================
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # 1. 봇 본인의 리액션 무시
        if payload.user_id == self.bot.user.id:
            return

        # 2. DM 무시
        if not payload.guild_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        data = core.get_cached_data()
        rr_map = data.get("reaction_roles", {})
        mid_str = str(payload.message_id)

        if mid_str not in rr_map:
            return

        config = rr_map[mid_str]
        roles_list = config.get("roles", [])

        # 3. 매칭되는 역할 찾기
        target_role_info = None
        for r_entry in roles_list:
            if core.match_payload_emoji(payload.emoji, r_entry):
                target_role_info = r_entry
                break

        if not target_role_info:
            return

        role_id = target_role_info.get("role_id")
        target_role = guild.get_role(role_id)
        if not target_role:
            return

        # 4. 멤버 객체 안전하게 획득
        member = payload.member
        if not member:
            member = guild.get_member(payload.user_id)
        if not member:
            try:
                member = await guild.fetch_member(payload.user_id)
            except Exception:
                return

        # 봇 권한 서열 검사
        bot_member = guild.me or await guild.fetch_member(self.bot.user.id)
        can_assign, _ = core.check_role_assignable(bot_member, target_role)
        if not can_assign:
            return

        # 5. 단일 선택 모드 (unique) 처리
        if config.get("mode") == "unique":
            # 이 패널에 속한 다른 역할들을 멤버에게서 회수
            other_role_ids = [r["role_id"] for r in roles_list if r["role_id"] != role_id]
            roles_to_remove = [r for r in member.roles if r.id in other_role_ids]
            if roles_to_remove:
                try:
                    await member.remove_roles(*roles_to_remove, reason="반응역할 단일선택 모드: 이전 역할 교체")
                except Exception:
                    pass

            # 메시지에서 유저가 이전에 달았던 다른 반응 이모지 자동 제거
            try:
                ch_obj = guild.get_channel(payload.channel_id) or await guild.fetch_channel(payload.channel_id)
                if ch_obj and hasattr(ch_obj, "fetch_message"):
                    orig_msg = await ch_obj.fetch_message(payload.message_id)
                    for r_entry in roles_list:
                        if r_entry["role_id"] != role_id:
                            for rx in orig_msg.reactions:
                                if core.match_payload_emoji(rx.emoji, r_entry):
                                    try:
                                        await orig_msg.remove_reaction(rx.emoji, member)
                                    except Exception:
                                        pass
            except Exception:
                pass

        # 6. 대상 역할 부여
        if target_role not in member.roles:
            try:
                await member.add_roles(target_role, reason=f"이모지 반응역할 자동 지급 ({target_role_info.get('emoji')})")
            except discord.Forbidden:
                print(f"⚠️ [반응역할 오류] 봇에게 {target_role.name} 역할을 부여할 권한이 없습니다.", flush=True)
            except Exception as e:
                print(f"⚠️ [반응역할 예외]: {e}", flush=True)

    # ====================================================
    # 🎧 핵심 이벤트 리스너: on_raw_reaction_remove
    # ====================================================
    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        # 1. 봇 본인의 리액션 무시
        if payload.user_id == self.bot.user.id:
            return

        # 2. DM 무시
        if not payload.guild_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        data = core.get_cached_data()
        rr_map = data.get("reaction_roles", {})
        mid_str = str(payload.message_id)

        if mid_str not in rr_map:
            return

        config = rr_map[mid_str]
        roles_list = config.get("roles", [])

        # 3. 매칭되는 역할 찾기
        target_role_info = None
        for r_entry in roles_list:
            if core.match_payload_emoji(payload.emoji, r_entry):
                target_role_info = r_entry
                break

        if not target_role_info:
            return

        role_id = target_role_info.get("role_id")
        target_role = guild.get_role(role_id)
        if not target_role:
            return

        # 4. 멤버 객체 안전하게 획득 (reaction_remove 시 payload.member는 항상 None임!)
        member = guild.get_member(payload.user_id)
        if not member:
            try:
                member = await guild.fetch_member(payload.user_id)
            except Exception:
                return

        # 5. 대상 역할 회수
        if target_role in member.roles:
            try:
                await member.remove_roles(target_role, reason=f"이모지 반응 취소에 따른 역할 회수 ({target_role_info.get('emoji')})")
            except discord.Forbidden:
                print(f"⚠️ [반응역할 오류] 봇에게 {target_role.name} 역할을 회수할 권한이 없습니다.", flush=True)
            except Exception as e:
                print(f"⚠️ [반응역할 예외]: {e}", flush=True)

    # ====================================================
    # 🎧 메시지 삭제 시 DB 자동 정리
    # ====================================================
    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        mid_str = str(payload.message_id)
        data = core.get_cached_data()
        if mid_str in data.get("reaction_roles", {}):
            async def _bg_clean():
                try:
                    d = await asyncio.to_thread(core.load_data)
                    if core.remove_reaction_role_entry(d, payload.message_id):
                        await asyncio.to_thread(core.save_data, d)
                        print(f"🧹 [반응역할 자동정리] 메시지({payload.message_id}) 삭제 감지 -> DB 정리 완료", flush=True)
                except Exception as ex:
                    print(f"⚠️ [반응역할 정리 예외]: {ex}", flush=True)
            asyncio.create_task(_bg_clean())

    # ====================================================
    # 🎧 서버 역할 삭제 시 매핑 자동 정리
    # ====================================================
    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        guild_id = role.guild.id
        data = core.get_cached_data()
        rr_map = data.get("reaction_roles", {})

        has_changed = False
        for mid, cfg in list(rr_map.items()):
            if int(cfg.get("guild_id", 0)) == guild_id:
                orig_len = len(cfg.get("roles", []))
                cfg["roles"] = [r for r in cfg.get("roles", []) if r.get("role_id") != role.id]
                if len(cfg["roles"]) != orig_len:
                    has_changed = True

        if has_changed:
            async def _bg_save_role_del():
                try:
                    d = await asyncio.to_thread(core.load_data)
                    for mid, cfg in list(d.get("reaction_roles", {}).items()):
                        if int(cfg.get("guild_id", 0)) == guild_id:
                            cfg["roles"] = [r for r in cfg.get("roles", []) if r.get("role_id") != role.id]
                    await asyncio.to_thread(core.save_data, d)
                    print(f"🧹 [반응역할 자동정리] 역할({role.name}) 삭제 감지 -> 매핑 정리 완료", flush=True)
                except Exception as ex:
                    print(f"⚠️ [반응역할 정리 예외]: {ex}", flush=True)
            asyncio.create_task(_bg_save_role_del())


async def setup(bot: commands.Bot):
    await bot.add_cog(Roles(bot))
