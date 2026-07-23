import os
import re
import asyncio
import time
import discord
from discord import app_commands
from discord.ext import commands, tasks # Tambahan 'tasks' untuk timer harian
import requests
import streamlit as st
from duckduckgo_search import DDGS
from typing import Optional

# ---------------------------------------------------------
# 1. Streamlit Dashboard Setup
# ---------------------------------------------------------
st.set_page_config(page_title="Discord Bot - Palestine Server", page_icon="🇵🇸")
st.title("🇵🇸 AI Assistant - 24/7 Virtual Assistant (Groq Engine)")
st.success("🟢 Palestine Server Bot Active!")

# ---------------------------------------------------------
# 2. Token & API Configuration
# ---------------------------------------------------------
DISCORD_TOKEN = (
    os.getenv("DISCORD_TOKEN_PERSONA") 
    or st.secrets.get("DISCORD_TOKEN_PERSONA") 
    or os.getenv("DISCORD_TOKEN") 
    or st.secrets.get("DISCORD_TOKEN")
)
GROQ_API_KEY = (
    os.getenv("GROQ_API_KEY_PERSONA") 
    or st.secrets.get("GROQ_API_KEY_PERSONA") 
    or os.getenv("GROQ_API_KEY") 
    or st.secrets.get("GROQ_API_KEY")
)

# ⚠️ GANTI ANGKA INI DENGAN ID CHANNEL UNTUK DAILY REMINDER!
DAILY_CHANNEL_ID = 1234567890123456789 

# 3-Model Routing Strategy
MODEL_HEAVY = "openai/gpt-oss-120b"          # Deep Analysis Mode
MODEL_LIGHT = "llama-3.1-8b-instant"         # Fast / Daily Chat Mode
MODEL_FALLBACK = "llama-3.3-70b-versatile"   # Emergency Fallback

SYSTEM_PROMPT_BOT = """
You are the official virtual assistant for the "Palestine" Discord server.
Response guidelines:
- Speak strictly in polite, educated, and friendly English.
- Answer all questions factually. If discussing humanitarian topics, history, Islam, or current events, respond with empathy, objectivity, and authentic informative detail.
- Strictly NO harsh, inappropriate, NSFW, or explicit language.
- Use a natural and professional tone—neither too stiff nor overly casual/slangy.
- Keep answers clear, concise, and honest.
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

    return "I apologize, but the AI system is currently experiencing issues. Please try again in a moment. ⚙️"

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
    chunks = [text[i:i+1800] for i in range(0, len(text), 1800)]
    for i, chunk in enumerate(chunks):
        if mode == "reply":
            if i == 0:
                await target.reply(chunk)
            else:
                await target.channel.send(chunk)
        elif mode == "slash":
            await target.followup.send(chunk)
        elif mode == "channel": # Tambahan mode untuk ngirim pesan harian
            await target.send(chunk)

# ---------------------------------------------------------
# 4. Discord Bot Initialization & Daily Task
# ---------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Required for Welcome System
bot = commands.Bot(command_prefix="!", intents=intents)

# --- FITUR BARU: AUTO DAILY ISLAMIC REMINDER ---
@tasks.loop(hours=24) # Berjalan otomatis setiap 24 jam
async def daily_islamic_reminder():
    channel = bot.get_channel(DAILY_CHANNEL_ID)
    if channel:
        print("⏳ Generating Daily Islamic Content...")
        daily_prompt = (
            "Generate a beautiful daily Islamic message for a Discord server. It MUST contain:\n"
            "1. 📖 **Daily Quranic Ayah**: One authentic Ayah in English with its Surah/Verse reference.\n"
            "2. 📜 **Daily Hadith**: One authentic Hadith in English with its reference (e.g., Sahih Bukhari, Muslim).\n"
            "3. ❓ **Daily Trivia Question**: One engaging Islamic trivia question to test the community's knowledge.\n\n"
            "Format the output using Discord markdown, use appropriate emojis, and make it look clean and inspiring. Do not include the answers to the trivia immediately."
        )
        
        daily_content = await asyncio.to_thread(ask_groq, daily_prompt, MODEL_HEAVY)
        await send_long_message(channel, daily_content, mode="channel")
        print("✅ Daily Islamic Content sent successfully!")

@daily_islamic_reminder.before_loop
async def before_daily_reminder():
    await bot.wait_until_ready()

# ---------------------------------------------------------
# 5. Discord Events (On Ready & On Message)
# ---------------------------------------------------------
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} Slash Commands for the Bot!")
    except Exception as e:
        print(f"❌ Failed to sync slash commands: {e}")
        
    await bot.change_presence(activity=discord.Game(name="Protecting Palestine Server 🇵🇸 | /chat"))
    print(f"✅ Bot ({bot.user}) is Online!")
    
    # Jalankan timer harian jika belum jalan
    if not daily_islamic_reminder.is_running():
        daily_islamic_reminder.start()

@bot.event
async def on_member_join(member):
    channel = member.guild.system_channel 
    if channel is not None:
        await channel.send(f"Welcome to the server, {member.mention}! I am the AI assistant here. Feel free to ask me anything if you need help. 🇵🇸")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # --- AUTO-MODERATOR ---
    banned_words = ["fuck", "shit", "bitch", "n-word", "asshole", "slut", "whore"] 
    
    if any(word in message.content.lower() for word in banned_words):
        await message.delete()
        warning = await message.channel.send(f"Excuse me {message.author.mention}, please refrain from using inappropriate language in this server.")
        await asyncio.sleep(5)
        await warning.delete()
        return 
    # --- END AUTO-MODERATOR ---

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
                    raw_history.append(f"AI Assistant: {clean_text}")
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
@bot.tree.command(name="chat", description="Chat or ask anything to the AI assistant. 🇵🇸")
@app_commands.describe(
    message="Your message or question for the AI",
    mode="Select processing engine"
)
@app_commands.choices(mode=[
    app_commands.Choice(name="⚡ Fast & Casual (Llama 8B Instant)", value="cepat"),
    app_commands.Choice(name="🧠 Deep & Smart (GPT-OSS 120B)", value="dalam")
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

@bot.tree.command(name="search", description="Ask the AI to search the web for the latest info.")
@app_commands.describe(query="The topic or information you want to search")
async def slash_search(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    sender_name = interaction.user.display_name
    
    web_data = await asyncio.to_thread(search_web, query)
    full_prompt = f"User [{sender_name}]: Please explain this based on the following web data:\n\nWEB DATA:\n{web_data}\n\nQUESTION/TOPIC: {query}"
        
    jawaban = await asyncio.to_thread(ask_groq, full_prompt, MODEL_LIGHT)
    await send_long_message(interaction, jawaban, mode="slash")

@bot.tree.command(name="poll", description="Create a quick poll for the server members.")
@app_commands.describe(question="What do you want to ask?")
async def slash_poll(interaction: discord.Interaction, question: str):
    embed = discord.Embed(
        title="📊 New Poll!",
        description=question,
        color=discord.Color.green() 
    )
    embed.set_footer(text=f"Poll created by {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)
    
    pesan_poll = await interaction.original_response()
    await pesan_poll.add_reaction("👍")
    await pesan_poll.add_reaction("👎")

@bot.tree.command(name="test", description="Test Groq AI system & diagnostics.")
async def slash_test(interaction: discord.Interaction):
    await interaction.response.defer()
    start_time = time.time()
    
    respon = await asyncio.to_thread(ask_groq, "System test! Give me a short, polite greeting.", MODEL_LIGHT)
    api_latency = round((time.time() - start_time) * 1000)
    discord_ping = round(bot.latency * 1000)
    
    status_msg = (
        "🧪 **[SYSTEM DIAGNOSTIC - AI ASSISTANT]**\n\n"
        f"🟢 **Groq API Status:** Connected & Active\n"
        f"⚡ **API Latency:** `{api_latency}ms`\n"
        f"📡 **Discord Ping:** `{discord_ping}ms`\n"
        f"🧠 **Model Active:** 3-Tier (`openai/gpt-oss-120b` | `llama-3.1-8b-instant` | `llama-3.3-70b-versatile`)\n\n"
        f"💬 **AI Response:**\n> {respon}"
    )
    await interaction.followup.send(status_msg)

@bot.tree.command(name="ping", description="Check bot latency.")
async def slash_ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 **Pong!** System is active with latency: `{latency}ms` (Groq Engine Active).")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
