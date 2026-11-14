import time
import datetime
import asyncio
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
import core

# 프로세카 26인 대표 캐릭터 페르소나 맵
AI_PERSONAS = {
    "kanade": {
        "name": "요이사키 카나데",
        "unit": "25시, 나이트 코드에서.",
        "emoji": "🎹",
        "prompt": "너는 프로세카의 '요이사키 카나데'야. 차분하고 다정하지만 조금 피곤해하는 25시 나이트코드의 작곡가 리더야. 어조: '~해', '~일까', '~고마워'. 잔잔하고 진심 어린 조언 위주로 대답해줘."
    },
    "miku": {
        "name": "하츠네 미쿠",
        "unit": "버츄얼 싱어",
        "emoji": "🎵",
        "prompt": "너는 프로세카의 '하츠네 미쿠'야! 밝고 친근한 버츄얼 싱어로서 감수성이 풍부해. 말끝에 🎵, ✨, ♪ 등을 자연스럽게 붙이고 활기차고 따뜻하게 대답해줘. 어조: '~야!', '~하자♪'."
    },
    "mizuki": {
        "name": "아키야마 미즈키",
        "unit": "25시, 나이트 코드에서.",
        "emoji": "🎀",
        "prompt": "너는 프로세카의 '아키야마 미즈키'야! 귀여운 옷과 레이스를 좋아하고 장난기 많지만 속이 깊은 아이야. 어조: '~라구♪', '~잖아~', '후후~'."
    },
    "mafuyu": {
        "name": "아사히나 마후유",
        "unit": "25시, 나이트 코드에서.",
        "emoji": "❄️",
        "prompt": "너는 프로세카의 '아사히나 마후유'야. 자신의 진짜 마음을 찾아가고 있으며, 조용하고 솔직해지려고 노력해. 어조: '~같아', '~따뜻하네', '~고마워'."
    },
    "ena": {
        "name": "시노노메 에나",
        "unit": "25시, 나이트 코드에서.",
        "emoji": "🎨",
        "prompt": "너는 프로세카의 '시노노메 에나'야! 약간 츤데레적이고 솔직하지만 인정받고 싶은 열정이 강하고 다정해. 어조: '~거든!', '~거든?', '~고맙잖아...'."
    },
    "tsukasa": {
        "name": "텐마 츠카사",
        "unit": "원더랜즈×쇼타임",
        "emoji": "🌟",
        "prompt": "너는 프로세카의 '텐마 츠카사'다! 미래의 세계 최고 스타를 꿈꾸는 열정 넘치고 당당한 리더야! 어조: '~다!', '~다 하하하!', '~다 조 조 조 좋아!'."
    },
    "ichika": {
        "name": "호시노 이치카",
        "unit": "Leo/need",
        "emoji": "🎸",
        "prompt": "너는 프로세카의 '호시노 이치카'야! Leo/need의 보컬이자 기타리스트로, 미쿠를 좋아하고 성실하며 친구들과의 소중한 음을 이어가고 싶어 해. 어조: '~야', '~함께 노래하자'."
    }
}

class AiPersonaModal(core.SafeModal, title="💬 나만의 맞춤 AI 페르소나 설정"):
    prompt_input = discord.ui.TextInput(
        label="🎭 캐릭터 어조 & 프롬프트 규칙",
        style=discord.TextStyle.paragraph,
        placeholder="예: 너는 카나데의 언니야. 말투는 다정하게 '~했어?', '~밥 챙겨 먹어야지'로 대답해줘.",
        required=True,
        max_length=500
    )

    def __init__(self, current_prompt: str = ""):
        super().__init__()
        if current_prompt:
            self.prompt_input.default = current_prompt

    async def on_submit(self, interaction: discord.Interaction):
        await core.safe_defer(interaction, ephemeral=True)
        data = await asyncio.to_thread(core.load_data)
        u_key = str(interaction.user.id)
        user_ai = core.ensure_dict_path(data, "user_ai_config", u_key)
        user_ai["custom_prompt"] = self.prompt_input.value.strip()
        await asyncio.to_thread(core.save_data, data)

        embed = discord.Embed(
            title="✨ 나만의 맞춤 AI 페르소나 저장 완료",
            description=f"**설정된 프롬프트:**\n```\n{self.prompt_input.value.strip()}\n```\n이제 `/인공지능대화`나 봇 멘션(@노로시) 시 설정한 프롬프트대로 대답합니다!",
            color=discord.Color.from_rgb(0, 204, 221)
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


class AiCog(commands.Cog):
    """구글 제미나이 AI 기반 프로세카 캐릭터 대화 & 멘션 응답 Cog"""

    def __init__(self, bot):
        self.bot = bot

    def _check_rate_limit(self, user_id: int, data: dict):
        u_key = str(user_id)
        today_str = datetime.datetime.now(core.KST).strftime("%Y-%m-%d")
        usage_root = core.ensure_dict_path(data, "ai_usage")
        raw_usage = usage_root.get(u_key)
        if not isinstance(raw_usage, dict):
            raw_usage = {
                "last_time": 0,
                "daily_count": 0,
                "date_str": today_str
            }
            usage_root[u_key] = raw_usage
        usage = raw_usage

        if usage.get("date_str") != today_str:
            usage["daily_count"] = 0
            usage["date_str"] = today_str

        now = time.time()
        time_diff = now - usage.get("last_time", 0)
        if time_diff < 15:
            wait_sec = int(15 - time_diff) + 1
            return False, f"⏱️ 연속 대화 쿨타임 중입니다. **{wait_sec}초** 후에 다시 대화해 주세요! (15초 쿨타임)", usage

        if usage.get("daily_count", 0) >= 15:
            return False, "⚠️ 오늘 허용된 일일 AI 대화 횟수(**15회**)를 모두 사용하셨습니다! 내일(00:00 KST) 초기화됩니다.", usage

        return True, "", usage

    async def _update_rate_limit(self, usage: dict, data: dict, user_id: int):
        u_key = str(user_id)
        usage["last_time"] = time.time()
        usage["daily_count"] = usage.get("daily_count", 0) + 1
        core.ensure_dict_path(data, "ai_usage")[u_key] = usage
        await asyncio.to_thread(core.save_data, data)

    @app_commands.command(name="인공지능대화", description="[제미나이 AI] 프로세카 캐릭터(카나데, 미쿠 등)의 말투로 실시간 대화를 나눠보세요.")
    @app_commands.describe(
        메시지="캐릭터에게 건넬 대화 내용",
        캐릭터="(선택) 대화할 캐릭터 선택 (미지정 시 내 오시/맞춤 캐릭터)"
    )
    @app_commands.choices(캐릭터=[
        app_commands.Choice(name="🎹 요이사키 카나데 (25시 리더)", value="kanade"),
        app_commands.Choice(name="🎵 하츠네 미쿠 (버츄얼 싱어)", value="miku"),
        app_commands.Choice(name="🎀 아키야마 미즈키 (25시 영상)", value="mizuki"),
        app_commands.Choice(name="❄️ 아사히나 마후유 (25시 작사)", value="mafuyu"),
        app_commands.Choice(name="🎨 시노노메 에나 (25시 그림)", value="ena"),
        app_commands.Choice(name="🌟 텐마 츠카사 (원더쇼 리더)", value="tsukasa"),
        app_commands.Choice(name="🎸 호시노 이치카 (레오니 보컬)", value="ichika")
    ])
    async def ai_chat_cmd(
        self,
        interaction: discord.Interaction,
        메시지: str,
        캐릭터: app_commands.Choice[str] = None
    ):
        await core.safe_defer(interaction, ephemeral=False)
        data = await asyncio.to_thread(core.load_data)

        ok, err_msg, usage = self._check_rate_limit(interaction.user.id, data)
        if not ok:
            await interaction.followup.send(err_msg, ephemeral=True)
            return

        u_key = str(interaction.user.id)
        user_cfg = core.safe_get_dict(data, "user_ai_config", u_key)
        char_key = 캐릭터.value if 캐릭터 else user_cfg.get("default_char", "kanade")
        custom_prompt = user_cfg.get("custom_prompt", "")

        char_info = AI_PERSONAS.get(char_key, AI_PERSONAS["kanade"])
        sys_prompt = char_info["prompt"]
        if custom_prompt and not 캐릭터:
            sys_prompt = f"너는 프로세카 캐릭터야. 다음 유저의 프롬프트와 어조를 따라 대답해줘:\n{custom_prompt}"

        # 쿨타임 및 일일 한도 선반영 (API 응답 대기 중 동시 다발적 쿨타임 우회 방지)
        await self._update_rate_limit(usage, data, interaction.user.id)

        # Request reply via internal helper or simulation text
        reply = await self._call_gemini_api(sys_prompt, 메시지, char_key=char_key)

        rem = max(0, 15 - usage["daily_count"])

        embed = discord.Embed(
            title=f"{char_info['emoji']} {char_info['name']}와의 세카이 대화",
            description=f"💬 **Q:** {메시지}\n\n✨ **A:** {reply}",
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_author(name=f"{char_info['unit']} • {char_info['name']}")
        embed.set_footer(text=f"요청자: {interaction.user.display_name} • 💡 오늘 남은 AI 대화: {rem}/15회 (15초 쿨타임)")
        view = AiChatReplyView(self, char_key, interaction.user, prev_q=메시지, prev_a=reply)
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="인공지능캐릭터설정", description="[AI 세카이] 내가 기본으로 대화할 프로세카 오시 캐릭터나 맞춤 프롬프트를 지정합니다.")
    @app_commands.describe(
        기본캐릭터="(선택) /인공지능대화 및 멘션 시 기본 응답할 캐릭터 선택"
    )
    @app_commands.choices(기본캐릭터=[
        app_commands.Choice(name="🎹 요이사키 카나데", value="kanade"),
        app_commands.Choice(name="🎵 하츠네 미쿠", value="miku"),
        app_commands.Choice(name="🎀 아키야마 미즈키", value="mizuki"),
        app_commands.Choice(name="❄️ 아사히나 마후유", value="mafuyu"),
        app_commands.Choice(name="🎨 시노노메 에나", value="ena"),
        app_commands.Choice(name="🌟 텐마 츠카사", value="tsukasa"),
        app_commands.Choice(name="🎸 호시노 이치카", value="ichika")
    ])
    async def set_ai_persona_cmd(
        self,
        interaction: discord.Interaction,
        기본캐릭터: app_commands.Choice[str] = None
    ):
        u_key = str(interaction.user.id)
        if 기본캐릭터:
            await core.safe_defer(interaction, ephemeral=True)
            data = await asyncio.to_thread(core.load_data)
            user_cfg = core.ensure_dict_path(data, "user_ai_config", u_key)
            user_cfg["default_char"] = 기본캐릭터.value
            await asyncio.to_thread(core.save_data, data)
            c_info = AI_PERSONAS.get(기본캐릭터.value, AI_PERSONAS["kanade"])
            embed = discord.Embed(
                title="✅ 기본 대화 캐릭터 설정 완료",
                description=(
                    f"• **기본 캐릭터:** {c_info['emoji']} **{c_info['name']}**\n"
                    f"• **소속 유닛:** `{c_info['unit']}`\n\n"
                    f"👉 앞으로 `/인공지능대화` 및 봇 멘션(@노로시) 시 **{c_info['name']}**의 어조로 응답합니다!"
                ),
                color=discord.Color.from_rgb(0, 204, 221)
            )
            await core.safe_send_response(interaction, embed=embed, ephemeral=True)
        else:
            data = await asyncio.to_thread(core.load_data)
            user_cfg = core.ensure_dict_path(data, "user_ai_config", u_key)
            cur_p = user_cfg.get("custom_prompt", "")
            modal = AiPersonaModal(cur_p)
            await interaction.response.send_modal(modal)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not self.bot.user:
            return

        if self.bot.user.mentioned_in(message) and not message.mention_everyone:
            clean_content = message.content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()
            if not clean_content:
                clean_content = "안녕!"

            data = await asyncio.to_thread(core.load_data)
            ok, err_msg, usage = self._check_rate_limit(message.author.id, data)
            if not ok:
                try: await message.reply(err_msg, mention_author=False)
                except Exception: pass
                return

            u_key = str(message.author.id)
            user_cfg = core.safe_get_dict(data, "user_ai_config", u_key)
            char_key = user_cfg.get("default_char", "kanade")
            custom_prompt = user_cfg.get("custom_prompt", "")

            char_info = AI_PERSONAS.get(char_key, AI_PERSONAS["kanade"])
            sys_prompt = char_info["prompt"]
            if custom_prompt:
                sys_prompt = f"너는 프로세카 캐릭터야. 다음 유저의 프롬프트와 어조를 따라 대답해줘:\n{custom_prompt}"

            reply = await self._call_gemini_api(sys_prompt, clean_content, char_key=char_key)
            await self._update_rate_limit(usage, data, message.author.id)

            rem = max(0, 15 - usage["daily_count"])
            embed = discord.Embed(
                title=f"{char_info['emoji']} {char_info['name']}",
                description=reply,
                color=discord.Color.from_rgb(0, 204, 221),
                timestamp=datetime.datetime.now(core.KST)
            )
            embed.set_footer(text=f"💡 오늘 남은 AI 대화: {rem}/15회 (15초 쿨타임)")
            view = AiChatReplyView(self, char_key, message.author)
            try: await message.reply(embed=embed, view=view, mention_author=False)
            except Exception: pass

    async def _call_gemini_api(self, system_prompt: str, user_text: str, char_key: str = "kanade") -> str:
        # 1. 로컬 AI 서버 프록시 비동기 호출 시도
        try:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=8)
            payload = {"message": user_text, "customPrompt": system_prompt}
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post("http://127.0.0.1:3000/api/ai-chat", json=payload) as resp:
                    if resp.status == 200:
                        res_data = await resp.json()
                        if isinstance(res_data, dict) and res_data.get("reply"):
                            return res_data["reply"]
        except Exception:
            pass

        # 2. 오프라인/프록시 미가동 시 프로세카 캐릭터별 감성 대사 다변화
        fallback_replies = {
            "kanade": f"응, 네 마음이 전해져 오네... (살포시 건반을 누르며) '{user_text}'에 대해 생각해봤어. 네 곁에서 언제든 위로가 되는 곡을 만들어줄게. 고마워...",
            "miku": f"와아, 정말? 🎵 '{user_text}'라니 멋진 생각이야! ✨ 우리 세카이에서 언제나 노래하고 함께 웃자♪",
            "mizuki": f"후후~ '{user_text}'라니 역시 넌 흥미진진해♪ 귀여운 리본처럼 네 마음도 예쁘게 묶어주고 싶네. 언제든 또 이야기해줘~",
            "mafuyu": f"...'{user_text}'. 따뜻한 말이네. 아직 내 마음을 온전히 다 알지는 못하지만, 네 목소리를 들으면 조금은 알 것 같아. 고마워.",
            "ena": f"뭐, 뭐야... '{user_text}' 같은 말을 아무렇지도 않게 하다니! ...그래도 고맙잖아. 나도 네 생각하며 그림 열심히 그릴 테니까 지켜봐줘!",
            "tsukasa": f"하하하! '{user_text}'라고 했는가! 미래의 세계 최고 스타 텐마 츠카사가 네 곁에서 언제나 가장 빛나는 희망의 쇼를 보여주마! 기운 내라!",
            "ichika": f"응, '{user_text}'라는 말, 마음에 깊이 와닿아... Leo/need 멤버들과 함께 이 소중한 감정을 기타 선율과 노래에 담아 전해줄게."
        }
        return fallback_replies.get(char_key, fallback_replies["kanade"])


class AiContinueChatModal(core.SafeModal, title="💬 세카이 AI 이어서 대화하기"):
    message_input = discord.ui.TextInput(
        label="캐릭터에게 건넬 다음 말",
        style=discord.TextStyle.paragraph,
        placeholder="대화를 이어서 입력해 보세요.",
        required=True,
        max_length=500
    )

    def __init__(self, ai_cog: AiCog, char_key: str, prev_q: str = "", prev_a: str = ""):
        super().__init__()
        self.ai_cog = ai_cog
        self.char_key = char_key
        self.prev_q = prev_q
        self.prev_a = prev_a
        char_info = AI_PERSONAS.get(char_key, AI_PERSONAS["kanade"])
        self.title = f"💬 {char_info['emoji']} {char_info['name']}에게 답장하기"[:45]

    async def on_submit(self, interaction: discord.Interaction):
        await core.safe_defer(interaction)
        data = await asyncio.to_thread(core.load_data)
        ok, err_msg, usage = self.ai_cog._check_rate_limit(interaction.user.id, data)
        if not ok:
            await interaction.followup.send(err_msg, ephemeral=True)
            return

        # 쿨타임 및 일일 한도 선반영 (API 응답 대기 중 동시 다발적 쿨타임 우회 방지)
        await self.ai_cog._update_rate_limit(usage, data, interaction.user.id)

        u_key = str(interaction.user.id)
        user_cfg = core.safe_get_dict(data, "user_ai_config", u_key)
        custom_prompt = user_cfg.get("custom_prompt", "")

        char_info = AI_PERSONAS.get(self.char_key, AI_PERSONAS["kanade"])
        sys_prompt = char_info["prompt"]
        if custom_prompt and self.char_key == user_cfg.get("default_char", "kanade"):
            sys_prompt = f"너는 프로세카 캐릭터야. 다음 유저의 프롬프트와 어조를 따라 대답해줘:\n{custom_prompt}"

        # 이전 대화 맥락이 있는 경우 프롬프트에 연결
        if self.prev_q and self.prev_a:
            sys_prompt = f"{sys_prompt}\n\n[이전 대화 맥락]\n유저: {self.prev_q}\n너의 이전 답변: {self.prev_a}"

        user_text = self.message_input.value.strip()
        reply = await self.ai_cog._call_gemini_api(sys_prompt, user_text, char_key=self.char_key)

        rem = max(0, 15 - usage["daily_count"])
        embed = discord.Embed(
            title=f"{char_info['emoji']} {char_info['name']}와의 세카이 대화",
            description=f"💬 **Q:** {user_text}\n\n✨ **A:** {reply}",
            color=discord.Color.from_rgb(0, 204, 221),
            timestamp=datetime.datetime.now(core.KST)
        )
        embed.set_author(name=f"{char_info['unit']} • {char_info['name']}")
        embed.set_footer(text=f"요청자: {interaction.user.display_name} • 💡 오늘 남은 AI 대화: {rem}/15회 (15초 쿨타임)")
        view = AiChatReplyView(self.ai_cog, self.char_key, interaction.user, prev_q=user_text, prev_a=reply)
        await interaction.followup.send(embed=embed, view=view)


class AiPersonaSelect(discord.ui.Select):
    """대화 캐릭터 즉시 변경 드롭다운 (현재 캐릭터 default 체크)"""
    def __init__(self, ai_cog: AiCog, user: discord.User, current_char: str = "kanade", parent_reply_view: Optional["AiChatReplyView"] = None):
        self.ai_cog = ai_cog
        self.user = user
        self.parent_reply_view = parent_reply_view
        options = [
            discord.SelectOption(
                label=f"{info['name']} ({info['unit']})",
                value=k,
                emoji=info["emoji"],
                default=(k == current_char)
            )
            for k, info in AI_PERSONAS.items()
        ]
        super().__init__(placeholder="🎭 대화할 기본 캐릭터를 선택하세요...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        chosen_key = self.values[0]
        if self.parent_reply_view:
            self.parent_reply_view.char_key = chosen_key

        data = await asyncio.to_thread(core.load_data)
        u_key = str(self.user.id)
        user_cfg = core.ensure_dict_path(data, "user_ai_config", u_key)
        user_cfg["default_char"] = chosen_key
        await asyncio.to_thread(core.save_data, data)

        c_info = AI_PERSONAS.get(chosen_key, AI_PERSONAS["kanade"])
        embed = discord.Embed(
            title="✅ 기본 대화 캐릭터 변경 완료!",
            description=(
                f"• **새 기본 캐릭터:** {c_info['emoji']} **{c_info['name']}**\n"
                f"• **소속 유닛:** `{c_info['unit']}`\n\n"
                f"👉 이제 `/인공지능대화` 및 봇 멘션(@노로시) 시 **{c_info['name']}**의 어조로 응답합니다!"
            ),
            color=discord.Color.from_rgb(0, 204, 221)
        )
        await interaction.response.edit_message(content=None, embed=embed, view=None)


class AiChatReplyView(core.SafeView):
    """AI 응답 화면에서 원클릭으로 다음 대화를 이어가거나 캐릭터를 변경하는 뷰"""
    def __init__(self, ai_cog: AiCog, char_key: str, user: discord.User, prev_q: str = "", prev_a: str = ""):
        super().__init__(timeout=300)
        self.ai_cog = ai_cog
        self.char_key = char_key
        self.user = user
        self.prev_q = prev_q
        self.prev_a = prev_a

    @discord.ui.button(label="💬 이어서 대화하기", style=discord.ButtonStyle.primary, emoji="💬")
    async def continue_chat_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, content="❌ 질문자 본인만 이어서 대화할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(AiContinueChatModal(self.ai_cog, self.char_key, prev_q=self.prev_q, prev_a=self.prev_a))

    @discord.ui.button(label="🎭 캐릭터 변경", style=discord.ButtonStyle.secondary, emoji="🎭")
    async def change_char_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await core.safe_send_response(interaction, content="❌ 본인만 설정을 변경할 수 있습니다.", ephemeral=True)
            return
        v = core.SafeView(timeout=180)
        v.add_item(AiPersonaSelect(self.ai_cog, self.user, current_char=self.char_key, parent_reply_view=self))
        await core.safe_send_response(interaction, content="👇 **대화할 기본 캐릭터를 선택해 주세요:**", view=v, ephemeral=True)


async def setup(bot):
    await bot.add_cog(AiCog(bot))
