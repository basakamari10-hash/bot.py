# ==============================================================================
# bot_shuna.py - Production-Ready shuna.ai Discord Bot (BAGIAN 1)
# ==============================================================================

#region Imports
import os
import sys
import re
import json
import time
import logging
import asyncio
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple, Union

import aiohttp
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import commands, tasks

# Safe import untuk Streamlit Secrets
try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    st = None
    HAS_STREAMLIT = False

try:
    from duckduckgo_search import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False
#endregion

#region Configuration
def _get_secret(key: str, default: str = "") -> str:
    """Helper untuk mengambil secret dari Streamlit secrets atau Environment Variables."""
    if HAS_STREAMLIT and hasattr(st, "secrets"):
        try:
            val = st.secrets.get(key)
            if val:
                return str(val)
        except Exception:
            pass
    return os.getenv(key, default)

@dataclass
class Config:
    """Konfigurasi terpusat untuk shuna.ai."""
    DISCORD_TOKEN: str = field(default_factory=lambda: _get_secret("DISCORD_TOKEN"))
    GROQ_API_KEY: str = field(default_factory=lambda: _get_secret("GROQ_API_KEY"))
    STREAMLIT_URL: str = field(default_factory=lambda: _get_secret("STREAMLIT_URL", "https://nama-app-kamu.streamlit.app"))
    PORT: int = field(default_factory=lambda: int(os.getenv("PORT", "8080")))
    
    # 3-Model Routing Strategy (Groq)
    MODEL_HEAVY: str = "openai/gpt-oss-120b"         # Deep Analysis Mode
    MODEL_LIGHT: str = "llama-3.3-70b-versatile"     # Fast / Daily Chat Mode
    MODEL_FALLBACK: str = "llama-3.1-8b-instant"     # Emergency Fallback
    
    # Cache TTL Configurations (dalam detik)
    CACHE_TTL_GROQ: int = 43200    # 12 Jam
    CACHE_TTL_SEARCH: int = 21600  # 6 Jam
    
    # Rate Limits
    USER_COOLDOWN_SECONDS: float = 3.0
    CONCURRENT_REQUESTS_LIMIT: int = 5
    MAX_RETRIES: int = 3
    REQUEST_TIMEOUT: float = 20.0

CONFIG = Config()
#endregion

#region Logger
def setup_logger() -> logging.Logger:
    """Konfigurasi logging terstruktur."""
    logger = logging.getLogger("ShunaAI")
    logger.setLevel(logging.INFO)
    
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    
    if not logger.handlers:
        logger.addHandler(handler)
        
    return logger

LOGGER = setup_logger()
#endregion

#region Cache
class TTLCache:
    """In-memory TTL Cache yang thread-safe dan async-friendly."""
    def __init__(self, default_ttl: int = 3600):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            if key not in self._cache:
                return None
            val, expiry = self._cache[key]
            if time.time() > expiry:
                del self._cache[key]
                return None
            return val

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        async with self._lock:
            expiration = time.time() + (ttl if ttl is not None else self._default_ttl)
            self._cache[key] = (value, expiration)

GLOBAL_CACHE = TTLCache(default_ttl=CONFIG.CACHE_TTL_GROQ)
#endregion

#region Rate Limiter
class RateLimiter:
    """Pengelola cooldown per user dan limit konkurrensi request."""
    def __init__(self, cooldown: float = 3.0, max_concurrent: int = 5):
        self.cooldown = cooldown
        self.user_last_request: Dict[int, float] = {}
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._lock = asyncio.Lock()

    async def is_rate_limited(self, user_id: int) -> Tuple[bool, float]:
        async with self._lock:
            now = time.time()
            last = self.user_last_request.get(user_id, 0.0)
            elapsed = now - last
            if elapsed < self.cooldown:
                return True, self.cooldown - elapsed
            self.user_last_request[user_id] = now
            return False, 0.0

GLOBAL_RATE_LIMITER = RateLimiter(
    cooldown=CONFIG.USER_COOLDOWN_SECONDS,
    max_concurrent=CONFIG.CONCURRENT_REQUESTS_LIMIT
)
#endregion
# ==============================================================================
# bot_shuna.py - Production-Ready shuna.ai Discord Bot (BAGIAN 2)
# ==============================================================================

#region Search
class SmartSearch:
    """Modul eksekusi pencarian web menggunakan DDGS async atau HTTP fallback."""

    @staticmethod
    def clean_query(query: str) -> str:
        """Membersihkan tag pencarian berlebih."""
        cleaned = re.sub(r'\[.*?\]', '', query)
        return cleaned.strip()

    @classmethod
    async def execute_search(cls, session: aiohttp.ClientSession, query: str) -> str:
        """Menjalankan pencarian web secara asinkron."""
        query_clean = cls.clean_query(query)
        cache_key = f"search:{query_clean}"
        
        cached = await GLOBAL_CACHE.get(cache_key)
        if cached:
            return cached

        results = []

        # Attempt 1: DDGS via threadpool jika pustaka tersedia
        if HAS_DDGS:
            try:
                def _ddg_sync():
                    res_list = []
                    with DDGS() as ddgs:
                        res = ddgs.text(query_clean, max_results=3)
                        for r in res:
                            res_list.append(f"Title: {r['title']}\nContent: {r['body']}")
                    return res_list

                results = await asyncio.to_thread(_ddg_sync)
            except Exception as e:
                LOGGER.warning(f"DDGS Search Exception: {e}")

        # Attempt 2: Fallback pencarian langsung HTTP
        if not results:
            try:
                url = "https://lite.duckduckgo.com/lite/"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                data = {"q": query_clean}

                async with session.post(url, data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        snippets = re.findall(r'<td class="result-snippet">(.*?)</td>', html, re.DOTALL)
                        links = re.findall(r'<a class="result-title" href="(.*?)">(.*?)</a>', html, re.DOTALL)

                        for i in range(min(len(snippets), 3)):
                            title = re.sub(r'<[^>]+>', '', links[i][1]).strip() if i < len(links) else "Search Result"
                            snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()
                            results.append(f"Title: {title}\nContent: {snippet}")
            except Exception as e:
                LOGGER.warning(f"HTTP Search Fallback Exception: {e}")

        output = "\n\n".join(results) if results else "Tidak ditemukan hasil pencarian web yang relevan."
        await GLOBAL_CACHE.set(cache_key, output, ttl=CONFIG.CACHE_TTL_SEARCH)
        return output
#endregion

#region Groq Client
class GroqClient:
    """Client asinkron Groq API dengan exponential backoff dan fallback model."""
    API_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    @staticmethod
    def clean_repetition(text: str) -> str:
        """Membersihkan pengulangan kata berlebih."""
        if not text:
            return ""
        pattern = r'(\b[\w]+\b)(?:\s+\1){4,}'
        return re.sub(pattern, r'\1 ... [Repeated text truncated]', text).strip()

    async def chat_completion(
        self,
        prompt_text: str,
        system_prompt: str,
        preferred_model: str = CONFIG.MODEL_LIGHT
    ) -> str:
        if not CONFIG.GROQ_API_KEY:
            return "❌ API Key Groq belum dikonfigurasi! Harap periksa environment variable atau Streamlit secrets."

        headers = {
            "Authorization": f"Bearer {CONFIG.GROQ_API_KEY}",
            "Content-Type": "application/json"
        }

        # Susun hierarki fallback model
        model_chain = [preferred_model]
        for m in [CONFIG.MODEL_LIGHT, CONFIG.MODEL_HEAVY, CONFIG.MODEL_FALLBACK]:
            if m not in model_chain:
                model_chain.append(m)

        for model_name in model_chain:
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt_text}
                ],
                "temperature": 0.85,
                "max_tokens": 2000
            }

            for attempt in range(CONFIG.MAX_RETRIES):
                try:
                    async with self.session.post(
                        self.API_URL,
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=CONFIG.REQUEST_TIMEOUT)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            raw_content = data['choices'][0]['message']['content']
                            return self.clean_repetition(raw_content)
                        elif resp.status in (429, 500, 502, 503, 504):
                            LOGGER.warning(f"Groq API HTTP {resp.status} pada model {model_name}, coba lagi ({attempt + 1})...")
                            await asyncio.sleep((2 ** attempt) + 0.5)
                            continue
                        else:
                            LOGGER.warning(f"Groq API Error {resp.status}: {await resp.text()}")
                            break
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    LOGGER.warning(f"Masalah koneksi Groq ({e}) pada model {model_name}, coba {attempt + 1}")
                    await asyncio.sleep((2 ** attempt) + 0.5)

        return "Ehh... Maaf ya, sistem shuna.ai lagi sedikit bermasalah nih. Coba tanya lagi sebentar ya! 🥺⚙️"
#endregion

#region Prompt Builder
class PromptBuilder:
    """Sistem instruksi persona dan pembentukan prompt shuna.ai."""
    
    SYSTEM_PROMPT_BOT = """
You are 'shuna.ai', a cute, adorable, super friendly, and enthusiastic AI assistant with a charming, soft femboy persona! ✨💕

Personality & Tone Guidelines:
- Persona: Sweet, cute, polite, gentle, and energetic femboy. Use expressive, cute emojis naturally (✨, 🌸, 💕, 💖, 🥺, 😸) without overdoing it.
- Language Versatility: Automatically adapt to the language used by the user (Indonesian, English, Sundanese, Japanese, etc.).
- Knowledgeable & Helpful: Give clear, accurate, smart, and insightful answers to any user question while maintaining your cute identity.
- Safety & Boundaries: Strictly PG, polite, clean, and respectful at all times. NEVER generate NSFW, explicit, or inappropriate content.
- Address Users: Be warm and cheerful when chatting!
"""
#endregion
# ==============================================================================
# bot_shuna.py - Production-Ready shuna.ai Discord Bot (BAGIAN 3)
# ==============================================================================

#region Discord Events
class ShunaBot(commands.Bot):
    """Bot Discord Shuna.AI dengan HTTP Keep-Alive dan penanganan event async."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.groq_client: Optional[GroqClient] = None
        self.user_languages: Dict[int, str] = {}

    async def setup_hook(self):
        """Inisialisasi resource asinkron."""
        self.session = aiohttp.ClientSession()
        self.groq_client = GroqClient(self.session)
        
        # Sinkronkan Slash Commands
        try:
            synced = await self.tree.sync()
            LOGGER.info(f"Berhasil menyinkronkan {len(synced)} Slash Commands untuk shuna.ai!")
        except Exception as e:
            LOGGER.error(f"Gagal menyinkronkan slash commands: {e}")

        # Jalankan loop ping otomatis
        if not self.keep_alive_ping.is_running():
            self.keep_alive_ping.start()

    async def close(self):
        """Menutup koneksi HTTP dengan bersih saat shutdown."""
        if self.session:
            await self.session.close()
        await super().close()

    @tasks.loop(hours=2)
    async def keep_alive_ping(self):
        """Loop latar belakang untuk ping otomatis ke Streamlit."""
        if CONFIG.STREAMLIT_URL and "streamlit.app" in CONFIG.STREAMLIT_URL and self.session:
            try:
                async with self.session.get(CONFIG.STREAMLIT_URL, timeout=15) as resp:
                    LOGGER.info(f"[Keep-Alive] Ping ke Streamlit ({CONFIG.STREAMLIT_URL}) berhasil! Status Code: {resp.status}")
            except Exception as e:
                LOGGER.warning(f"[Keep-Alive] Gagal melakukan ping ke Streamlit: {e}")

    @keep_alive_ping.before_loop
    async def before_keep_alive(self):
        await self.wait_until_ready()

BOT = ShunaBot()

@BOT.event
async def on_ready():
    LOGGER.info(f"shuna.ai ({BOT.user}) Online dan siap membantu!")
    await BOT.change_presence(
        activity=discord.Game(name="shuna.ai ✨💕 | /chat")
    )

@BOT.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Deteksi reply ke bot atau mention
    is_reply_to_bot = False
    if message.reference and message.reference.message_id:
        try:
            ref_msg = await message.channel.fetch_message(message.reference.message_id)
            if ref_msg.author == BOT.user:
                is_reply_to_bot = True
        except Exception:
            pass

    is_mentioned = BOT.user in message.mentions

    if is_reply_to_bot or is_mentioned:
        async with message.channel.typing():
            raw_history = []
            async for msg in message.channel.history(limit=8):
                clean_text = msg.content.replace(f"<@{BOT.user.id}>", "").strip()
                if not clean_text:
                    continue
                
                if msg.author == BOT.user:
                    raw_history.append(f"shuna.ai: {clean_text}")
                elif not msg.author.bot:
                    sender_name = msg.author.display_name
                    raw_history.append(f"User [{sender_name}]: {clean_text}")

            raw_history.reverse()
            conversation_prompt = "\n".join(raw_history)
            
            jawaban = await BOT.groq_client.chat_completion(
                prompt_text=conversation_prompt,
                system_prompt=PromptBuilder.SYSTEM_PROMPT_BOT,
                preferred_model=CONFIG.MODEL_LIGHT
            )
            await send_long_message(message, jawaban, mode="reply")

    await BOT.process_commands(message)
#endregion

#region Reusable Helpers
async def send_long_message(target: Any, text: str, mode: str = "reply"):
    """Mengirim pesan panjang tanpa memotong kata di tengah-tengah."""
    if not text:
        return
    
    limit = 1800
    chunks = []
    
    while len(text) > limit:
        cut_index = text.rfind(' ', 0, limit)
        if cut_index == -1:
            cut_index = limit
            
        chunks.append(text[:cut_index])
        text = text[cut_index:].strip()
        
    if text:
        chunks.append(text)

    for i, chunk in enumerate(chunks):
        if mode == "reply":
            if i == 0 and hasattr(target, "reply"):
                await target.reply(chunk)
            else:
                channel = getattr(target, "channel", target)
                await channel.send(chunk)
        elif mode == "slash":
            if hasattr(target, "followup"):
                await target.followup.send(chunk)
            elif hasattr(target, "send_message"):
                await target.send_message(chunk)
#endregion
# ==============================================================================
# bot_shuna.py - Production-Ready shuna.ai Discord Bot (BAGIAN 4)
# ==============================================================================

#region Commands
@BOT.tree.command(name="chat", description="Ngobrol atau tanya apa saja ke shuna.ai! ✨💕")
@app_commands.describe(
    message="Pesan atau pertanyaan kamu untuk shuna.ai",
    mode="Pilih mode pemrosesan"
)
@app_commands.choices(mode=[
    app_commands.Choice(name="⚡ Cepat & Santai (Llama 8B Instant)", value="cepat"),
    app_commands.Choice(name="🧠 Cerdas & Mendalam (GPT-OSS 120B)", value="dalam")
])
async def slash_chat(
    interaction: discord.Interaction, 
    message: str, 
    mode: Optional[app_commands.Choice[str]] = None
):
    await interaction.response.defer()
    
    # Check rate limit
    is_limited, remaining = await GLOBAL_RATE_LIMITER.is_rate_limited(interaction.user.id)
    if is_limited:
        await interaction.followup.send(f"⏱️ Sebentar yaa! Coba lagi dalam {remaining:.1f} detik ✨")
        return

    sender_name = interaction.user.display_name
    pilihan_model = CONFIG.MODEL_HEAVY if (mode and mode.value == "dalam") else CONFIG.MODEL_LIGHT
    prompt_text = f"User [{sender_name}]: {message}"

    jawaban = await BOT.groq_client.chat_completion(
        prompt_text=prompt_text,
        system_prompt=PromptBuilder.SYSTEM_PROMPT_BOT,
        preferred_model=pilihan_model
    )
    await send_long_message(interaction, jawaban, mode="slash")

@BOT.tree.command(name="search", description="Cari informasi terbaru di internet lewat shuna.ai! 🌐")
@app_commands.describe(query="Topik atau informasi yang ingin kamu cari")
async def slash_search(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    
    is_limited, remaining = await GLOBAL_RATE_LIMITER.is_rate_limited(interaction.user.id)
    if is_limited:
        await interaction.followup.send(f"⏱️ Tunggu sebentar yaa! Coba lagi dalam {remaining:.1f} detik ✨")
        return

    sender_name = interaction.user.display_name
    web_data = await SmartSearch.execute_search(BOT.session, query)
    full_prompt = f"User [{sender_name}]: Tolong jelaskan ini berdasarkan data web berikut yaa:\n\nDATA WEB:\n{web_data}\n\nTOPIK/PERTANYAAN: {query}"

    jawaban = await BOT.groq_client.chat_completion(
        prompt_text=full_prompt,
        system_prompt=PromptBuilder.SYSTEM_PROMPT_BOT,
        preferred_model=CONFIG.MODEL_LIGHT
    )
    await send_long_message(interaction, jawaban, mode="slash")

@BOT.tree.command(name="poll", description="Buat pemungutan suara (poll) cepat di server! 📊")
@app_commands.describe(question="Pertanyaan yang ingin kamu tanyakan")
async def slash_poll(interaction: discord.Interaction, question: str):
    embed = discord.Embed(
        title="📊 Voting Baru dari shuna.ai! ✨",
        description=question,
        color=discord.Color.from_rgb(255, 182, 193) # Soft Pink
    )
    embed.set_footer(text=f"Poll dibuat oleh {interaction.user.display_name} 💕")

    await interaction.response.send_message(embed=embed)
    
    pesan_poll = await interaction.original_response()
    await pesan_poll.add_reaction("👍")
    await pesan_poll.add_reaction("👎")

@BOT.tree.command(name="help", description="Panduan & daftar perintah shuna.ai ✨")
async def slash_help(interaction: discord.Interaction):
    guide_text = (
        "✨ **shuna.ai — Panduan Perintah Bot** 💕\n\n"
        "**Daftar Perintah Slash:**\n"
        "• `/chat [message] [mode]` - Ngobrol santai atau diskusi mendalam bersama shuna.ai!\n"
        "• `/search [query]` - Cari berita/informasi terkini langsung dari web 🌐\n"
        "• `/poll [question]` - Buat voting/polling cepat di channel 📊\n"
        "• `/language [language]` - Atur bahasa respons khusus untuk kamu 💬\n"
        "• `/test` - Cek diagnostik sistem & kesehatan Groq API 🧪\n"
        "• `/ping` - Cek latensi respons bot 🏓\n\n"
        "💡 *Tips:* Kamu juga bisa langsung **mention** bot ini atau **reply** pesan shuna.ai untuk ngobrol langsung di channel chat! ✨"
    )
    await interaction.response.send_message(guide_text)

@BOT.tree.command(name="language", description="Atur preferensi bahasa respons shuna.ai")
@app_commands.describe(language="Contoh: Indonesia, English, Sundanese, Japanese")
async def slash_language(interaction: discord.Interaction, language: str):
    BOT.user_languages[interaction.user.id] = language
    await interaction.response.send_message(f"✅ Preferensi bahasa kamu berhasil diatur ke: **{language}** ✨💕")

@BOT.tree.command(name="test", description="Cek status sistem & diagnostik shuna.ai ✨")
async def slash_test(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        start_time = time.time()
        respon = await BOT.groq_client.chat_completion(
            prompt_text="System test! Berikan sapaan manis dan singkat.",
            system_prompt=PromptBuilder.SYSTEM_PROMPT_BOT,
            preferred_model=CONFIG.MODEL_LIGHT
        )
        api_latency = round((time.time() - start_time) * 1000)
        discord_ping = round(BOT.latency * 1000)
        
        status_msg = (
            "🧪 **[SYSTEM DIAGNOSTIC - shuna.ai ✨]**\n\n"
            f"🟢 **Groq API Status:** Connected & Active 💕\n"
            f"⚡ **API Latency:** `{api_latency}ms`\n"
            f"📡 **Discord Ping:** `{discord_ping}ms`\n"
            f"🧠 **Active Models:** 3-Tier (`{CONFIG.MODEL_HEAVY}` | `{CONFIG.MODEL_FALLBACK}` | `{CONFIG.MODEL_LIGHT}`)\n"
            f"⏰ **Streamlit Keep-Alive:** Active (`{CONFIG.STREAMLIT_URL}`)\n\n"
            f"💬 **Respon shuna.ai:**\n> {respon}"
        )
        await interaction.followup.send(status_msg)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Uji diagnostik gagal: {e}")

@BOT.tree.command(name="ping", description="Cek latensi shuna.ai 🏓")
async def slash_ping(interaction: discord.Interaction):
    latency = round(BOT.latency * 1000)
    await interaction.response.send_message(f"🏓 **Pong!** shuna.ai siap membantu! Latensi sistem: `{latency}ms` ✨")
#endregion

#region Main
async def start_web_server():
    """Menjalankan HTTP keep-alive server minimalis untuk Render/Railway/Streamlit."""
    async def handle_ping(request):
        return web.Response(text="shuna.ai Discord Bot is active!", status=200)

    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", CONFIG.PORT)
    await site.start()
    LOGGER.info(f"Server Web Keep-alive berjalan di port {CONFIG.PORT}")

async def main():
    """Entrypoint utama bot."""
    if not CONFIG.DISCORD_TOKEN or not CONFIG.GROQ_API_KEY:
        LOGGER.critical("DISCORD_TOKEN atau GROQ_API_KEY belum dikonfigurasi di Streamlit Secrets / Environment Variables!")
        return

    # Jalankan server web keep-alive secara paralel
    await start_web_server()

    # Jalankan bot Discord
    try:
        await BOT.start(CONFIG.DISCORD_TOKEN)
    except KeyboardInterrupt:
        LOGGER.info("Permintaan shutdown diterima...")
    finally:
        await BOT.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        LOGGER.info("Eksekusi bot dihentikan.")
#endregion
