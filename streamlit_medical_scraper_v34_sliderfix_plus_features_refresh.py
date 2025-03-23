
import streamlit as st
import openai
import os
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import quote, urlparse
from random import choice

st.set_page_config(page_title="Medical FAQ Generator (v34)", layout="wide")
st.title("🧠 Medical FAQ Generator (v34)")
st.markdown("Uses Google search to gather URLs and generate patient-friendly questions with **token usage tracking**.")

# === Step 1: API Keys and Topic ===
openai_key = st.text_input("🔑 OpenAI API Key", type="password", key="api_key")
google_key = st.text_input("🔑 Google API Key", type="password", key="google_api_key")
google_cx = st.text_input("🔍 Google Search Engine ID (CX)", key="google_cx")
topic = st.text_input("💬 Enter a medical topic", key="topic_input")

if 'step' not in st.session_state:
    st.session_state.step = 1

if openai_key and topic and google_key and google_cx and st.session_state.step == 1:
    st.session_state.client = openai.OpenAI(api_key=openai_key)
    st.success("✅ Keys and topic received.")
    st.session_state.step = 2

# === Step 2: Query Setup ===
if st.session_state.step == 2:
    st.subheader("🧠 Choose how many URLs to get per query")

    base_queries = {
        f"{topic}": st.slider("🔍 General Search", 0, 20, 5),
        f"{topic} causes and symptoms": st.slider("🧬 Causes and Symptoms", 0, 20, 3),
        f"{topic} diagnosis and treatment": st.slider("🩺 Diagnosis and Treatment", 0, 20, 3),
        f"{topic} patient experiences": st.slider("👥 Patient Experiences", 0, 20, 3),
        f"{topic} FAQs": st.slider("❓ FAQs", 0, 20, 2),
        f"{topic} real stories": st.slider("📖 Real Stories", 0, 20, 2),
        f"{topic} therapy and recovery": st.slider("🏥 Therapy and Recovery", 0, 20, 2),
        f"{topic} support groups": st.slider("🤝 Support Groups", 0, 20, 2),
        f"{topic} prognosis": st.slider("📈 Prognosis", 0, 20, 2),
        f"{topic} complications": st.slider("⚠️ Complications", 0, 20, 2),
    }

    if st.button("🔎 Run Google Search"):
        st.session_state.custom_query_settings = base_queries
        st.session_state.step = 3

# === Step 3: Google Search Engine Queries ===
if st.session_state.step == 3:
    st.subheader("🔍 Searching Google...")

    def google_cse_search(query, key, cx, limit):
        urls = []
        start = 1
        while len(urls) < limit:
            try:
                url = f"https://www.googleapis.com/customsearch/v1?q={quote(query)}&key={key}&cx={cx}&start={start}"
                res = requests.get(url, timeout=10)
                data = res.json()
                for item in data.get("items", []):
                    link = item.get("link")
                    if link and not any(x in link for x in ["youtube.com", ".pdf", ".gov"]):
                        urls.append(link)
                        if len(urls) == limit:
                            break
                start += 10
                if "items" not in data:
                    break
            except Exception as e:
                st.warning(f"⚠️ {query[:35]}... error: {e}")
                break
        return urls

    all_urls = []
    for query, limit in st.session_state.custom_query_settings.items():
        if limit > 0:
            with st.spinner(f"Searching: {query}"):
                found = google_cse_search(query, google_key, google_cx, limit)
                st.markdown(f"**{query}** → {len(found)} URLs")
                for url in found:
                    parsed = urlparse(url)
                    label = f"{parsed.netloc}{parsed.path[:50]}"
                    st.markdown(f"📄 [{label}]({url})")
                all_urls.extend(found)

    all_urls = list(set(all_urls))
    st.session_state.scraped_urls = all_urls
    st.success(f"✅ Total unique URLs gathered: {len(all_urls)}")
    st.session_state.step = 4

# === Step 4: Scrape + GPT with Token Tracking ===
if st.session_state.step == 4:
    st.subheader("🧠 Extracting Text and Generating Questions")

    def scrape_url(url):
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                paragraphs = soup.find_all(["p", "li"])
                return [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30]
        except Exception as e:
            st.warning(f"⚠️ Failed to scrape {url} ({e})")
        return []

    def chunk_texts(text_list, chunk_size=1200):
        chunks, current = [], ""
        for t in text_list:
            if len(current) + len(t) < chunk_size:
                current += t + " "
            else:
                chunks.append(current.strip())
                current = t + " "
        if current:
            chunks.append(current.strip())
        return chunks

    def generate_questions_from_texts(texts, topic, client):
        prompts = [
            "Using this text, generate as many patient-facing questions as possible about {topic}.",
            "From this content, create relevant medical questions regarding {topic}.",
            "Based on the following extract, generate informative and helpful questions about {topic}.",
        ]
        all_questions = []
        total_tokens = 0
        for chunk in chunk_texts(texts):
            prompt = choice(prompts).format(topic=topic) + f"\n\n{chunk}"
            try:
                res = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}]
                )
                content = res.choices[0].message.content.strip()
                usage = res.usage
                tokens_used = usage.total_tokens if usage else 0
                total_tokens += tokens_used
                questions = [q.strip("-• \n") for q in content.splitlines() if len(q.strip()) > 10]
                all_questions.extend(questions)
            except Exception as e:
                st.warning(f"⚠️ GPT error: {e}")
            time.sleep(1)
        return list(set(all_questions)), total_tokens

    all_texts = []
    for url in st.session_state.scraped_urls:
        all_texts.extend(scrape_url(url))

    st.info(f"🧾 Extracted {len(all_texts)} text sections from {len(st.session_state.scraped_urls)} pages.")

    if all_texts:
        questions, total_tokens = generate_questions_from_texts(all_texts, topic, st.session_state.client)
        if questions:
            df = pd.DataFrame({"Generated Questions": questions})
            filename = f"questions_{topic.replace(' ', '_')}.xlsx"
            filepath = os.path.join(os.getcwd(), filename)
            df.to_excel(filepath, index=False)
            st.success(f"✅ {len(questions)} questions generated.")
            st.info(f"📊 Estimated total tokens used: {total_tokens:,} (~${(total_tokens/1000)*0.002:.4f})")
            with open(filepath, "rb") as f:
                st.download_button("📥 Download Excel", f, file_name=filename)
        else:
            st.warning("⚠️ No questions were generated.")
    else:
        st.error("❌ No text extracted from the URLs.")


with st.expander("❓ Help / FAQ"):
    st.markdown("""
    **What does 'Clinical Reasoning' mean?**  
    These questions test how well you can apply knowledge to real patient cases.

    **What is 'Patient Communication'?**  
    These questions simulate interactions and empathy-related scenarios with patients.

    **What is 'Basic Science'?**  
    These cover anatomy, physiology, biochemistry, and similar foundational topics.

    **What is 'EBM/Statistics'?**  
    Evidence-based medicine and biostatistics, including interpreting clinical trials.

    **What does 'AI Difficulty' mean?**  
    Adjusts the complexity of AI-generated questions — lower is simpler.

    **Where does the content come from?**  
    Publicly available trusted content from sources like Reddit, Quora, and site-specific medical pages you specify.
    """)

# === Refresh Button ===
st.markdown("---")
if st.button("🔄 Start Over / Enter Another Medical Topic"):
    st.experimental_rerun()
