import os
import sys
import subprocess
import requests
import streamlit as st

# Setup Halaman Streamlit
st.set_page_config(page_title="Palestine AI Bot Hub", page_icon="🇵🇸", layout="wide")

st.title("🇵🇸 Palestine AI Bot Host & Live Testing Hub")
st.write("Aplikasi ini menjalankan Bot Discord Palestine Server 24/7 di latar belakang sekaligus menyediakan **Live Chat Box** untuk pengetesan.")

# ---------------------------------------------------------
# 1. Definisi Variabel Global & Prompt
# ---------------------------------------------------------
MODEL_TESTER = "llama-3.1-8b-instant"

PROMPT_BOT = (
    "You are the official virtual assistant for the 'Palestine' Discord server.\n"
    "Response guidelines:\n"
    "- Speak strictly in polite, educated, and friendly English.\n"
    "- Answer all questions factually. If discussing humanitarian topics, history, Islam, or current events, respond with empathy, objectivity, and authentic informative detail.\n"
    "- Strictly NO harsh, inappropriate, NSFW, or explicit language.\n"
    "- Use a natural and professional tone—neither too stiff nor overly casual/slangy.\n"
    "- Keep answers clear, concise, and honest."
)

# ---------------------------------------------------------
# 2. Menyiapkan Environment Variables dengan Aman
# ---------------------------------------------------------
env = os.environ.copy()

try:
    for key in st.secrets:
        val = st.secrets[key]
        if isinstance(val, str):
            env[key] = val
        elif isinstance(val, dict):
            for sub_key, sub_val in val.items():
                if isinstance(sub_val, str):
                    env[sub_key] = sub_val
except Exception as e:
    st.warning(f"Peringatan Secrets: {e}")

# Ambil API Key Groq dari Environment
KEY_API = env.get("GROQ_API_KEY_PERSONA") or env.get("GROQ_API_KEY")

# ---------------------------------------------------------
# 3. Spawn Subprocess Bot Discord (Hanya 1x secara Global)
# ---------------------------------------------------------
@st.cache_resource
def start_bots():
    print("🚀 Memulai subprocess Bot Palestine AI...")
    # Pastikan file discord bot lu disave dengan nama "bot.py" di folder yang sama
    p_bot = subprocess.Popen([sys.executable, "bot.py"], env=env)
    return p_bot

bot_proc = start_bots()

# ---------------------------------------------------------
# 4. Status Monitoring Process
# ---------------------------------------------------------
st.subheader("📊 Status Server Discord Bot:")

if bot_proc.poll() is None:
    st.success(f"🟢 **Bot Palestine AI**: Running (PID: {bot_proc.pid})")
else:
    st.error(f"🔴 **Bot Palestine AI**: Stopped (Exit Code: {bot_proc.poll()})")

st.divider()

# ---------------------------------------------------------
# 5. Fungsi Pemanggil API untuk Web Chat Tester
# ---------------------------------------------------------
def tanya_groq_direct(prompt_text, system_prompt, api_key, model=MODEL_TESTER):
    if not api_key:
        return "❌ Error: GROQ_API_KEY belum diisi di Environment atau Streamlit Secrets!"
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt_text}
        ],
        "temperature": 0.7,
        "max_tokens": 1500
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=20)
        if res.status_code == 200:
            return res.json()['choices'][0]['message']['content']
        else:
            return f"❌ Error API [{res.status_code}]: {res.text}"
    except Exception as e:
        return f"❌ Exception: {e}"

# ---------------------------------------------------------
# 6. Live Chat Box Tester UI
# ---------------------------------------------------------
st.subheader("🧪 Live AI Tester - Palestine Assistant")

if "messages_bot" not in st.session_state:
    st.session_state.messages_bot = []

for msg in st.session_state.messages_bot:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if user_input := st.chat_input("Ask anything about Palestine, Islam, or general knowledge...", key="chat_bot"):
    st.session_state.messages_bot.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("AI is thinking... 🇵🇸"):
            reply = tanya_groq_direct(user_input, PROMPT_BOT, KEY_API)
            st.markdown(reply)
            st.session_state.messages_bot.append({"role": "assistant", "content": reply})
