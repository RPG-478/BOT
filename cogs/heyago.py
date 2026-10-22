import discord
from discord.ext import commands
import os
import re
import mimetypes
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from core.gemini_compat import generate_content

class AdaptiveAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY")
        self.gemini_client = genai.Client(api_key=self.gemini_api_key)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if os.environ.get("BLOCKRUN_MENTION_ENABLED", "false").lower() in {"1", "true", "yes", "on"}:
            return

        if message.flags.forwarded:
            return

        is_mentioned = self.bot.user in message.mentions
        ref_msg = None

        if message.reference and message.reference.message_id:
            if message.reference.type == discord.MessageReferenceType.forward:
                return

            
            try:
                ref_msg = message.reference.cached_message
                if not ref_msg:
                    ref_msg = await message.channel.fetch_message(message.reference.message_id)
            except Exception:
                pass

        is_reply_to_bot = ref_msg is not None and ref_msg.author == self.bot.user

        if not (is_mentioned or is_reply_to_bot):
            return

        async with message.channel.typing():
            try:
                history_text = await self._fetch_conversation_history(message)
                reply_text = await self._process_ai_request(message, ref_msg, history_text)
                await self._send_reply_message(message, reply_text)
            except Exception as e:
                await message.reply(f"エラーが発生しました: {e}")

    async def _fetch_conversation_history(self, message, limit=6):
        history = []
        curr = message
        while curr and len(history) < limit:
            content = curr.content.replace(f'<@{self.bot.user.id}>', '').strip()
            role = "assistant" if curr.author == self.bot.user else "user"
            history.append(f"{'ボット' if role == 'assistant' else 'ユーザー'}: {content}")

            if curr.reference and curr.reference.message_id:
                try:
                    ref_msg = curr.reference.cached_message
                    if not ref_msg:
                        ref_msg = await message.channel.fetch_message(curr.reference.message_id)
                    curr = ref_msg
                except Exception:
                    curr = None
            else:
                curr = None

        history.reverse()
        return "\n".join(history)

    async def _process_ai_request(self, message, ref_msg, history_text):
        command_text = message.content.replace(f'<@{self.bot.user.id}>', '').strip()
        ref_text = ""
        if ref_msg:
            ref_author_name = ref_msg.author.display_name
            ref_content = ref_msg.content.replace(f'<@{self.bot.user.id}>', '').strip()
            ref_text = f"【参照メッセージ ({ref_author_name})】\n{ref_content}\n"

        target_attachments = list(message.attachments)
        if ref_msg:
            target_attachments.extend(ref_msg.attachments)

        combined_text = f"{ref_text} {command_text}"
        extracted_urls = re.findall(r'https?://[^\s>]+', combined_text)

        file_parts = []
        text_context = ""

        async with AsyncSession(impersonate="chrome") as session:
            for att in target_attachments:
                part, txt = await self._fetch_resource(session, att.url, att.filename, att.content_type)
                if part:
                    file_parts.append(part)
                if txt:
                    text_context += f"\n{txt}\n"

            for url in extracted_urls:
                filename = url.split('/')[-1].split('?')[0]
                part, txt = await self._fetch_resource(session, url, filename, None)
                if part:
                    file_parts.append(part)
                if txt:
                    text_context += f"\n{txt}\n"

        system_instruction = (
            "あなたはDiscordボットのAGO BOTです。冷静で落ち着いた回答をしてください\n"
            "ユーザーからの入力、過去の会話履歴、添付されたファイル（画像・動画・音声・PDFなど）、Webページの情報を総合して適切な回答を作成してください。"
        )

        prompt = (
            f"【会話履歴】\n{history_text}\n\n"
            f"{ref_text}"
            f"【取得テキスト・Webデータ】\n{text_context}\n\n"
            f"【ユーザーの指示・入力】\n{command_text if command_text else '添付されたファイルやURL、参照メッセージの内容を解説・回答してください。'}"
        )

        contents = [prompt] + file_parts

        response = await generate_content(
            self.gemini_client,
            model='gemini-3.5-flash-lite',
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
            )
        )
        return response.text

    async def _fetch_resource(self, session, url, filename, content_type_hint):
        try:
            res = await session.get(url, timeout=20)
            if res.status_code != 200:
                return None, None

            header_type = res.headers.get("content-type", "").split(";")[0].strip()
            guessed_type, _ = mimetypes.guess_type(filename)
            mime_type = content_type_hint or header_type or guessed_type or "application/octet-stream"

            if mime_type.startswith(("image/", "video/", "audio/", "application/pdf")):
                return types.Part.from_bytes(data=res.content, mime_type=mime_type), None

            if mime_type.startswith("text/html"):
                soup = BeautifulSoup(res.text, "html.parser")
                for s in soup(["script", "style", "nav", "footer", "header"]):
                    s.decompose()
                web_text = " ".join(soup.stripped_strings)[:4000]
                return None, f"--- Web URL ({url}) ---\n{web_text}"

            try:
                decoded_text = res.content.decode('utf-8', errors='ignore')
                return None, f"--- テキストデータ ({filename}) ---\n{decoded_text[:5000]}"
            except Exception:
                return types.Part.from_bytes(data=res.content, mime_type=mime_type), None

        except Exception:
            return None, None

    async def _send_reply_message(self, message, text):
        if len(text) > 2000:
            chunks = [text[i:i+2000] for i in range(0, len(text), 2000)]
            await message.reply(chunks[0])
            for chunk in chunks[1:]:
                await message.channel.send(chunk)
        else:
            await message.reply(text)

async def setup(bot):
    await bot.add_cog(AdaptiveAI(bot))
