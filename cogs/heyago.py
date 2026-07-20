import discord
from discord.ext import commands
from groq import AsyncGroq
import os
import json
import urllib.parse
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

class AdaptiveAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
        self.gemini_api_key = "AQ.Ab8RN6LqsTEvK4h4ZW0u-Ni7qdxbytjUuXEJaZLDV3JG0Anygg"
        self.gemini_client = genai.Client(api_key=self.gemini_api_key)
        self.chat_model = "llama-3.1-8b-instant"

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        is_mentioned = self.bot.user in message.mentions
        ref_msg = None

        if message.reference and message.reference.message_id:
            try:
                ref_msg = message.reference.cached_message
                if not ref_msg:
                    ref_msg = await message.channel.fetch_message(message.reference.message_id)
            except Exception:
                pass

        is_reply_to_bot = ref_msg is not None and ref_msg.author == self.bot.user
        is_reply_to_other_user = ref_msg is not None and not ref_msg.author.bot

        if not (is_mentioned or is_reply_to_bot):
            return

        command_text = message.content.replace(f'<@{self.bot.user.id}>', '').strip()

        async with message.channel.typing():
            try:
                if is_mentioned and is_reply_to_other_user:
                    await self._handle_analyze_mode(message, ref_msg, command_text)
                    return

                if not command_text:
                    await message.reply("用事があれば話しかけてください。")
                    return

                history = await self._fetch_conversation_history(message)
                mode_info = await self._determine_mode(command_text)
                await self._dispatch_mode(message, command_text, history, mode_info)
            except Exception as e:
                await message.reply(f"エラーが発生しました: {e}")

    async def _fetch_conversation_history(self, message, limit=6):
        history = []
        curr = message
        while curr and len(history) < limit:
            content = curr.content.replace(f'<@{self.bot.user.id}>', '').strip()
            role = "assistant" if curr.author == self.bot.user else "user"
            history.append({"role": role, "content": content})

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
        return history

    async def _determine_mode(self, text):
        judge_prompt = (
            "ユーザーの入力文の文脈から、どのモードで処理すべきかを厳格に判定してください。\n\n"
            "【モード一覧】\n"
            "- command: ボットの既存機能（BGM操作、音量、速度、EQ、Google検索など）への明確な指示・要求である場合\n"
            "- search_web: 最新のニュース、時事ネタ、天気、リアルタイム情報など、Web検索・スクレイピングが必要な問い合わせである場合\n"
            "- chat: 単なる雑談、挨拶、一般的な知識に関する質問など、Web検索が不要な会話である場合\n\n"
            "出力は必ず以下のJSONフォーマットのみにしてください。\n"
            '{"mode": "command_または_search_web_または_chat"}'
        )

        chat_completion = await self.groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": judge_prompt},
                {"role": "user", "content": text}
            ],
            model=self.chat_model,
            response_format={"type": "json_object"}
        )
        return json.loads(chat_completion.choices[0].message.content)

    async def _dispatch_mode(self, message, text, history, mode_info):
        mode = mode_info.get("mode")

        if mode == "command":
            await self._handle_command_mode(message, text)
        elif mode == "search_web":
            await self._handle_search_web_mode(message, text, history)
        else:
            await self._handle_chat_mode(message, text, history)

    async def _handle_command_mode(self, message, text):
        prompt = (
            "入力文から実行すべきコマンドと引数を抽出してください。\n"
            "利用可能なコマンド: ggrks, join, leave, play, search, volume, speed, eq, panel\n\n"
            "出力JSONフォーマット:\n"
            '{"commands": [{"name": "コマンド名", "arg": "引数（不要なら空文字）"}]}'
        )
        chat_completion = await self.groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ],
            model=self.chat_model,
            response_format={"type": "json_object"}
        )
        result = json.loads(chat_completion.choices[0].message.content)

        for cmd_info in result.get("commands", []):
            cmd_name = cmd_info.get("name")
            cmd_arg = cmd_info.get("arg", "")
            
            command = self.bot.get_command(cmd_name)
            if command:
                if cmd_arg:
                    message.content = f"{self.bot.command_prefix}{cmd_name} {cmd_arg}"
                else:
                    message.content = f"{self.bot.command_prefix}{cmd_name}"
                
                ctx = await self.bot.get_context(message)
                await self.bot.invoke(ctx)

    async def _handle_analyze_mode(self, message, ref_msg, command_text):
        attachments = list(ref_msg.attachments) + list(message.attachments)
        file_parts = []
        text_attachments_content = ""

        async with AsyncSession(impersonate="chrome") as session:
            for att in attachments:
                try:
                    res = await session.get(att.url, timeout=15)
                    if res.status_code == 200:
                        content_type = att.content_type or "application/octet-stream"
                        if content_type.startswith("text/") or att.name.endswith(('.txt', '.py', '.json', '.html', '.css', '.js', '.md', '.csv')):
                            try:
                                decoded_text = res.content.decode('utf-8', errors='ignore')
                                text_attachments_content += f"\n--- 添付ファイル ({att.name}) ---\n{decoded_text[:5000]}\n"
                            except Exception:
                                file_parts.append(types.Part.from_bytes(data=res.content, mime_type=content_type))
                        else:
                            file_parts.append(types.Part.from_bytes(data=res.content, mime_type=content_type))
                except Exception:
                    continue

        ref_author_name = ref_msg.author.display_name
        ref_text = ref_msg.content.replace(f'<@{self.bot.user.id}>', '').strip()

        analysis_prompt = (
            "あなたは高度なコンテンツ・ファイル解析を行うAIアシスタントです。\n"
            "ユーザーからの指示に従い、対象となるメッセージ内容や添付ファイル（画像、動画、音声、文書など）を精読・解析して適切な回答を作成してください。\n"
            f"【対象ユーザー ({ref_author_name}) のメッセージ】\n{ref_text}\n"
            f"{text_attachments_content}\n"
            f"【分析・回答に対する指示】\n{command_text if command_text else '対象のメッセージおよびファイルを解析して、要約や内容の説明を行ってください。'}"
        )

        contents = [analysis_prompt] + file_parts

        try:
            response = await self.gemini_client.aio.models.generate_content(
                model='gemini-3.5-flash',
                contents=contents
            )
            reply_text = response.text
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                reply_text = await self._call_groq_fallback(
                    "対象のメッセージテキストと指示に基づいて解析・回答してください。",
                    f"【対象メッセージ】\n{ref_text}\n{text_attachments_content}\n\n【指示】\n{command_text}"
                )
            else:
                raise e

        await self._send_reply_message(message, reply_text)

    async def _call_gemini_with_fallback(self, system_prompt, user_text, history=None):
        try:
            response = await self.gemini_client.aio.models.generate_content(
                model='gemini-3.5-flash',
                contents=user_text,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                ),
            )
            return response.text
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                return await self._call_groq_fallback(system_prompt, user_text, history)
            raise e

    async def _call_groq_fallback(self, system_prompt, user_text, history=None):
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        else:
            messages.append({"role": "user", "content": user_text})

        chat_completion = await self.groq_client.chat.completions.create(
            messages=messages,
            model=self.chat_model
        )
        return chat_completion.choices[0].message.content

    async def _handle_chat_mode(self, message, text, history):
        history_text = "\n".join([f"{'ボット' if h['role']=='assistant' else 'ユーザー'}: {h['content']}" for h in history])
        
        prompt = (
            "あなたはDiscordボットのAIアシスタントです。\n"
            "これまでの会話の流れを踏まえ、親しみやすく自然な日本語で返答してください。\n\n"
            f"【これまでの会話履歴】\n{history_text}"
        )
        reply_text = await self._call_gemini_with_fallback(prompt, text, history)
        await self._send_reply_message(message, reply_text)

    async def _handle_search_web_mode(self, message, text, history):
        keyword_prompt = (
            "ユーザーの質問から、Web検索に最適な検索キーワードを1つだけ抽出してください。\n"
            "余計な解説は含めず、必ず以下のJSONフォーマットのみで出力してください。\n"
            '{"keyword": "検索キーワード"}'
        )
        keyword_completion = await self.groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": keyword_prompt},
                {"role": "user", "content": text}
            ],
            model=self.chat_model,
            response_format={"type": "json_object"}
        )
        keyword_res = json.loads(keyword_completion.choices[0].message.content)
        query = keyword_res.get("keyword", text)

        search_results = await self._search_duckduckgo(query)
        
        web_context = ""
        async with AsyncSession(impersonate="chrome") as session:
            for url in search_results[:2]:
                try:
                    res = await session.get(url, timeout=5)
                    if res.status_code == 200:
                        soup = BeautifulSoup(res.text, "html.parser")
                        for s in soup(["script", "style", "nav", "footer", "header"]):
                            s.decompose()
                        text_content = " ".join(soup.stripped_strings)[:1000]
                        web_context += f"\n--- Source: {url} ---\n{text_content}\n"
                except:
                    continue

        if not web_context:
            web_context = "検索結果から情報を取得できませんでした。"

        history_text = "\n".join([f"{'ボット' if h['role']=='assistant' else 'ユーザー'}: {h['content']}" for h in history])

        answer_prompt = (
            "あなたは与えられたWeb検索結果を参考にしてユーザーの質問に答えるAIアシスタントです。\n"
            "これまでの会話の流れと提供された情報を元に、正確で自然な日本語の回答を作成してください。\n\n"
            f"【これまでの会話履歴】\n{history_text}\n\n"
            f"【検索結果の参考情報】\n{web_context}"
        )
        
        reply_text = await self._call_gemini_with_fallback(answer_prompt, text, history)
        await self._send_reply_message(message, reply_text)

    async def _search_duckduckgo(self, query):
        urls = []
        encoded_query = urllib.parse.quote(query)
        search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
        
        try:
            async with AsyncSession(impersonate="chrome") as session:
                res = await session.get(search_url, timeout=5)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    for a in soup.find_all("a", class_="result__url"):
                        href = a.get("href")
                        if href:
                            if "declined" not in href and "duckduckgo.com" not in href:
                                parsed_url = urllib.parse.urlparse(href)
                                qs = urllib.parse.parse_qs(parsed_url.query)
                                if "uddg" in qs:
                                    urls.append(qs["uddg"][0])
                                else:
                                    urls.append(href)
        except:
            pass
        return urls

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