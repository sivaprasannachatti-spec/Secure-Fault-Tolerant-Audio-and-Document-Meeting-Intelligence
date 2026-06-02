# 🎙️ Secure Fault Tolerant Audio and Document Meeting Intelligence: Enterprise-Grade Meeting Intelligence

Welcome to **Secure Fault Tolerant Audio and Document Meeting Intelligence**, a production-ready, high-performance meeting intelligence platform. MeetingAI transforms chaotic audio recordings into structured, high-value business insights using a state-of-the-art multi-agent AI pipeline. 

Whether you are in a high-speed corporate environment or a remote team, MeetingAI ensures that no decision is forgotten, no action item is missed, and every meeting becomes a searchable, interactive knowledge asset.

---

## 🌟 Why Secure Fault Tolerant Audio and Document Meeting Intelligence?

*   **⚡ Sub-Second Responsiveness:** Experience "ChatGPT-style" real-time streaming for summaries and chat.
*   **🔒 Privacy-First Security:** Your data is protected by **Group-Based Access Control (GBAC)**. Summaries are shared within teams, but your personal chat history remains 100% private.
*   **📡 Resilience by Design:** Built with an "Offline-First" architecture. If your internet drops, the app automatically switches to **Local AI (Ollama)** and syncs your data back to the cloud once you're back online.
*   **🧠 Tiered Intelligence:** We don't just use one model. Our engine intelligently routes complex reasoning to heavy models and simple tasks to lightning-fast models.

---

## 🧠 The Inference Orchestration Engine

MeetingAI features a custom-built **Provider Manager** that orchestrates multiple AI backends to ensure 100% uptime and maximum performance.

### **1. Model Tiering Strategy**
We utilize a "Right Tool for the Job" approach to balance intelligence and speed:
*   **High-Reasoning Tasks (Summary/Chat):** Powered by `Llama-3.3-70B-Versatile` on Groq. This ensures deep contextual understanding and nuanced summaries.
*   **Latency-Sensitive Tasks (Action Items/Decisions):** Offloaded to `Llama-3.1-8B-Instant`. This provides near-instant UI feedback for structured data extraction.

### **2. Automatic Failover Chain**
The system monitors provider health and latency in real-time. If a cloud provider hits a rate limit or goes down, the engine automatically pivots:
1.  **Groq (Primary):** Ultra-low latency cloud inference.
2.  **HuggingFace (Cloud Fallback):** High-reliability backup using Qwen and Mistral models.
3.  **Ollama (Local Fallback):** Truly offline inference running directly on your CPU/GPU.

### **3. Parallel Streaming Workflow**
MeetingAI doesn't wait for one task to finish before starting the next. Our pipeline uses a `ThreadPoolExecutor` to run Transcription, Summary Generation, Action Item Extraction, and Decision Mapping **simultaneously**.
*   **SSE (Server-Sent Events):** All AI outputs are streamed to your browser via a single, robust event stream.
*   **ChatGPT-Style UI:** Watch as the AI "thinks" and types out your meeting report in real-time.

---

## 🛠️ Technical Stack

### **AI Core**
- **Inference Pool:** Groq, HuggingFace, Ollama.
- **Orchestration:** LangChain & LangGraph (Iterative Optimizer Loops).
- **Audio Processing:** AssemblyAI / Deepgram / Whisper (Local).
- **Diarization:** Pyannote (Speaker Identification).

### **Backend & Data**
- **FastAPI:** High-concurrency asynchronous Python core.
- **Supabase:** Primary Cloud Database (PostgreSQL) with JWT Auth.
- **SQLite:** Local database for offline persistence.
- **Redis (Optional):** Ready for high-speed caching.

### **Frontend Aesthetics**
- **Vanilla Modern JS:** Zero-dependency, blazing-fast client.
- **Premium UI:** Dark-mode by default, featuring glassmorphism, vibrant gradients, and micro-animations.

---

## 🚀 Getting Started

### **1. Prerequisites**
- **Python 3.10+**
- **Ollama** (For offline support)
- **Groq API Key** (For maximum speed)

### **2. Setup**
1. Clone the repository and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Configure your `.env` file with your API keys (Groq, Supabase, HuggingFace).
3. Start the local server:
   ```bash
   python -m uvicorn backend.app:app --port 9000
   ```

### **3. Local AI Setup**
To enable the offline fallback, pull the required models:
```bash
ollama pull qwen3:8b
ollama pull llama3.2:3b
```

---

## 📈 Performance Metrics

| Task | Primary Model | Avg. Latency | Fallback |
| :--- | :--- | :--- | :--- |
| **Summary** | Llama-3.3-70B | ~1.5s (Streaming) | Qwen2.5-7B |
| **Action Items** | Llama-3.1-8B-Instant | ~0.4s (Streaming) | Mistral-7B |
| **Chat Q&A** | Llama-3.3-70B | ~80 tokens/sec | Llama-3.2-3B |

---

## 🤝 Contributing
We believe in the power of open meeting intelligence. Feel free to submit PRs, report bugs, or suggest new features to help make **Secure Fault Tolerant Audio and Document Meeting Intelligence** the best workspace for every team!

---
**Built with ❤️ by the Secure Fault Tolerant Audio and Document Meeting Intelligence Team.**
