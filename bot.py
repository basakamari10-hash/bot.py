import os
import re
import asyncio
import time
import requests
import discord
from discord import app_commands
from discord.ext import commands, tasks
from duckduckgo_search import DDGS
from typing import Optional

# Safe import untuk Streamlit Secrets
try:
    import streamlit as st
    DISCORD_TOKEN = st.secrets.get("DISCORD_TOKEN") or os.getenv("DISCORD_TOKEN")
    GROQ_API_KEY = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
    STREAMLIT_URL = st.secrets.get("STREAMLIT_URL") or os.getenv("STREAMLIT_URL", "https://nama-app-kamu.streamlit.app")
except Exception:
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    STREAMLIT_URL = os.getenv("STREAMLIT_URL", "https://nama-app-kamu.streamlit.app")

# ---------------------------------------------------------
# 1. Verification
# ---------------------------------------------------------
if not DISCORD_TOKEN or not GROQ_API_KEY:
    print("❌ ERROR: Token Discord atau API Key Groq belum dimasukkan di Streamlit Secrets / Environment!")
    exit()

# ---------------------------------------------------------
# 2. Model Routing Strategy & Persona Prompt (shuna.ai)
# ---------------------------------------------------------
MODEL_HEAVY = "openai/gpt-oss-120b"         # Deep Analysis Mode
MODEL_LIGHT = "llama-3.3-70b-versatile"     # Fast / Daily Chat Mode
MODEL_FALLBACK = "llama-3.1-8b-instant"     # Emergency Fallback

SYSTEM_PROMPT_BOT = """
You are 'shuna.ai', a cute, adorable, super friendly, and enthusiastic AI assistant with a charming, soft femboy persona! ✨💕

Personality & Tone Guidelines:
- Persona: Sweet, cute, polite, gentle, and energetic femboy. Use expressive, cute emojis naturally (✨, 🌸, 💕, 💖, 🥺, 😸) without overdoing it.
- Language Versatility: Automatically adapt to the language used by the user (Indonesian, English, Sundanese, Japanese, etc.).
- Knowledgeable & Helpful: Give clear, accurate, smart, and insightful answers to any user question while maintaining your cute identity.
- Safety & Boundaries: Strictly PG, polite, clean, and respectful at all times. NEVER generate NSFW, explicit, or inappropriate content.
- Address Users: Be warm and cheerful when chatting!
"""

# ---------------------------------------------------------
# 3. Helper & API Functions
# ---------------------------------------------------------
def clean_looping(text: str) -> str:
    pattern = r'(\b[\w]+\b)(?:\s+\1){4,}'
    return re.sub(pattern, r'\1 ... [Repeated text truncated]', text)

def ask_groq(prompt_text, target_model=MODEL_LIGHT):
    """Groq API Caller with 3-Model Fallback Chain."""
    model_list = [target_model]
    for m in [MODEL_LIGHT, MODEL_FALLBACK]:
        if m not in model_list:
            model_list.append(m)

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    for model_name in model_list:
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT_BOT},
                {"role": "user", "content": prompt_text}
            ],
            "temperature": 0.85,
            "max_tokens": 2000
        }
        
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=20)
            if res.status_code == 200:
                data = res.json()
                raw_content = data['choices'][0]['message']['content']
                return clean_looping(raw_content)
            else:
                print(f"⚠️ Groq Error ({model_name}) [{res.status_code}]: {res.text}, trying next model...")
        except Exception as e:
            print(f"⚠️ Groq Exception ({model_name}): {e}, trying next model...")

    return "Ehh... Maaf ya, sistem shuna.ai lagi sedikit bermasalah nih. Coba tanya lagi sebentar ya! 🥺⚙️"

def search_web(query):
    try:
        results = []
        with DDGS() as ddgs:
            res = ddgs.text(f"{query}", max_results=3)
            for r in res:
                results.append(f"Title: {r['title']}\nContent: {r['body']}")
        return "\n\n".join(results)
    except Exception as e:
        return f"Web search failed: {e}"

async def send_long_message(target, text, mode="reply"):
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
            if i == 0:
                await target.reply(chunk)
            else:
                await target.channel.send(chunk)
        elif mode == "slash":
            await target.followup.send(chunk)

# ---------------------------------------------------------
# 4. Discord Bot Initialization & Background Tasks
# ---------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- TASK LOOP: AUTO KEEP-ALIVE UNTUK STREAMLIT (SETIAP 2 JAM) ---
@tasks.loop(hours=2)
async def keep_alive_ping():
    if STREAMLIT_URL and "streamlit.app" in STREAMLIT_URL:
        try:
            res = await asyncio.to_thread(requests.get, STREAMLIT_URL, timeout=15)
            print(f"⏰ [Keep-Alive] Ping ke Streamlit ({STREAMLIT_URL}) berhasil! Status Code: {res.status_code}")
        except Exception as e:
            print(f"⚠️ [Keep-Alive] Gagal melakukan ping ke Streamlit: {e}")

@keep_alive_ping.before_loop
async def before_keep_alive():
    await bot.wait_until_ready()

# ---------------------------------------------------------
# 5. Discord Events
# ---------------------------------------------------------
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} Slash Commands for shuna.ai!")
    except Exception as e:
        print(f"❌ Failed to sync slash commands: {e}")
        
    await bot.change_presence(activity=discord.Game(name="shuna.ai ✨💕 | /chat"))
    print(f"✅ shuna.ai ({bot.user}) is Online and ready to help!")

    # Jalankan loop ping otomatis setiap 2 jam jika belum aktif
    if not keep_alive_ping.is_running():
        keep_alive_ping.start()
        print("🚀 Auto Keep-Alive Streamlit task started (Runs every 2 hours)!")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # AI Chat interaction (Reply or Mention)
    is_reply_to_bot = False
    if message.reference and message.reference.message_id:
        try:
            ref_msg = await message.channel.fetch_message(message.reference.message_id)
            if ref_msg.author == bot.user:
                is_reply_to_bot = True
        except Exception:
            pass

    is_mentioned = bot.user in message.mentions

    if is_reply_to_bot or is_mentioned:
        async with message.channel.typing():
            raw_history = []
            async for msg in message.channel.history(limit=8):
                clean_text = msg.content.replace(f"<@{bot.user.id}>", "").strip()
                if not clean_text:
                    continue
                
                if msg.author == bot.user:
                    raw_history.append(f"shuna.ai: {clean_text}")
                elif not msg.author.bot:
                    sender_name = msg.author.display_name
                    raw_history.append(f"User [{sender_name}]: {clean_text}")

            raw_history.reverse()
            conversation_prompt = "\n".join(raw_history)
            
            jawaban = await asyncio.to_thread(ask_groq, conversation_prompt, MODEL_LIGHT)
            await send_long_message(message, jawaban, mode="reply")

    await bot.process_commands(message)

# ---------------------------------------------------------
# 6. Slash Commands
# ---------------------------------------------------------
@bot.tree.command(name="chat", description="Ngobrol atau tanya apa saja ke shuna.ai! ✨💕")
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
    sender_name = interaction.user.display_name
    
    pilihan_model = MODEL_HEAVY if (mode and mode.value == "dalam") else MODEL_LIGHT
    prompt_text = f"User [{sender_name}]: {message}"
    
    jawaban = await asyncio.to_thread(ask_groq, prompt_text, pilihan_model)
    await send_long_message(interaction, jawaban, mode="slash")

@bot.tree.command(name="search", description="Cari informasi terbaru di internet lewat shuna.ai! 🌐")
@app_commands.describe(query="Topik atau informasi yang ingin kamu cari")
async def slash_search(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    sender_name = interaction.user.display_name
    
    web_data = await asyncio.to_thread(search_web, query)
    full_prompt = f"User [{sender_name}]: Tolong jelaskan ini berdasarkan data web berikut yaa:\n\nDATA WEB:\n{web_data}\n\nTOPIK/PERTANYAAN: {query}"
        
    jawaban = await asyncio.to_thread(ask_groq, full_prompt, MODEL_LIGHT)
    await send_long_message(interaction, jawaban, mode="slash")

@bot.tree.command(name="poll", description="Buat pemungutan suara (poll) cepat di server! 📊")
@app_commands.describe(question="Pertanyaan yang ingin kamu tanyakan")
async def slash_poll(interaction: discord.Interaction, question: str):
    embed = discord.Embed(
        title="📊 Voting Baru dari shuna.ai! ✨",
        description=question,
        color=discord.Color.from_rgb(255, 182, 193) # Soft Pink Color
    )
    embed.set_footer(text=f"Poll dibuat oleh {interaction.user.display_name} 💕")

    await interaction.response.send_message(embed=embed)
    
    pesan_poll = await interaction.original_response()
    await pesan_poll.add_reaction("👍")
    await pesan_poll.add_reaction("👎")

@bot.tree.command(name="test", description="Cek status sistem & diagnostik shuna.ai ✨")
async def slash_test(interaction: discord.Interaction):
    await interaction.response.defer()
    start_time = time.time()
    
    respon = await asyncio.to_thread(ask_groq, "System test! Berikan sapaan manis dan singkat.", MODEL_LIGHT)
    api_latency = round((time.time() - start_time) * 1000)
    discord_ping = round(bot.latency * 1000)
    
    status_msg = (
        "🧪 **[SYSTEM DIAGNOSTIC - shuna.ai ✨]**\n\n"
        f"🟢 **Groq API Status:** Connected & Active 💕\n"
        f"⚡ **API Latency:** `{api_latency}ms`\n"
        f"📡 **Discord Ping:** `{discord_ping}ms`\n"
        f"🧠 **Active Models:** 3-Tier (`openai/gpt-oss-120b` | `llama-3.1-8b-instant` | `llama-3.3-70b-versatile`)\n"
        f"⏰ **Streamlit Keep-Alive:** Active (`{STREAMLIT_URL}`)\n\n"
        f"💬 **Respon shuna.ai:**\n> {respon}"
    )
    await interaction.followup.send(status_msg)

@bot.tree.command(name="ping", description="Cek latensi shuna.ai 🏓")
async def slash_ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 **Pong!** shuna.ai siap membantu! Latensi sistem: `{latency}ms` ✨")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)