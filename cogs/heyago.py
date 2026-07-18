import discord
from discord.ext import commands
from groq import AsyncGroq
import os
import json
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
import urllib.parse
import httpx

class AdaptiveAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
        self.gemini_api_key = "AQ.Ab8RN6KIs2IdmrhZYohOjZqg0A8rWal6eQync4sgYqnyLtTaqA"
        self.chat_model = "llama-3.1-8b-instant"

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if self.bot.user in message.mentions:
            command_text = message.content.replace(f'<@{self.bot.user.id}>', '').strip()
            
            if not command_text:
                await message.channel.send("用事があれば話しかけてください。")
                return

            async with message.channel.typing():
                try:
                    mode_info = await self._determine_mode(command_text)
                    await self._dispatch_mode(message, command_text, mode_info)
                except Exception as e:
                    await message.channel.send(f"エラーが発生しました: {e}")

    async def _determine_mode(self, text):
        judge_prompt = (
            "ユーザーの入力文の文脈から、どのモードで処理すべきかを厳格に判定してください。\n\n"
            "【モード一覧】\n"
            "- command: ボットの既存機能（BGM操作、音量、速度、EQ、Google検索など）への明確な指示・要求である場合\n"
            "- search_web: 最新のニュース、時事ネタ、天気、ボットが知らないような情報について「調べて」「検索して」「教えて」と要求されている場合\n"
            "- chat: 単なる雑談、挨拶、一般的な知識に関する質問、あるいは明確なコマンド指示や最新情報の検索要求ではない場合\n\n"
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

    async def _dispatch_mode(self, message, text, mode_info):
        mode = mode_info.get("mode")

        if mode == "command":
            await self._handle_command_mode(message, text)
        elif mode == "search_web":
            await self._handle_search_web_mode(message, text)
        elif mode == "chat":
            await self._handle_chat_mode(message, text)
        else:
            await self._handle_chat_mode(message, text)

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

    async def _call_gemini_25_flash(self, system_prompt, user_text):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self.gemini_api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_text}]
                }
            ],
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=30.0)
            response.raise_for_status()
            res_json = response.json()
            return res_json['candidates'][0]['content']['parts'][0]['text']

    async def _handle_chat_mode(self, message, text):
        prompt = "あなたはDiscordボットのAIアシスタントです。ユーザーからの話しかけに対して、親しみやすく自然な日本語で返答してください。"
        reply_text = await self._call_gemini_25_flash(prompt, text)
        await self._send_long_message(message.channel, reply_text)

    async def _handle_search_web_mode(self, message, text):
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

        answer_prompt = (
            "あなたは与えられたWeb検索結果を参考にしてユーザーの質問に答えるAIアシスタントです。\n"
            "提供された情報を元に、正確で自然な日本語の回答を作成してください。\n"
            f"【検索結果の参考情報】\n{web_context}"
        )
        
        reply_text = await self._call_gemini_25_flash(answer_prompt, text)
        await self._send_long_message(message.channel, reply_text)

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

    async def _send_long_message(self, channel, text):
        if len(text) > 2000:
            for i in range(0, len(text), 2000):
                await channel.send(text[i:i+2000])
        else:
            await channel.send(text)

async def setup(bot):
    await bot.add_cog(AdaptiveAI(bot))