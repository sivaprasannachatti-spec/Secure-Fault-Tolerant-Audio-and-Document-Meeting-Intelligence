# 🎙️ Multi-Tenant AI Meeting Assistant Workspace

An enterprise-grade, offline-first meeting intelligence application. Upload your raw meeting audio, and our multi-agent AI pipeline automatically cleans the audio, performs speaker diarization, generates highly optimized meeting minutes, and allows team members to interact with the meeting data via a streaming Q&A AI chatbot.

Built with **Group-Based Access Control (GBAC)** so departments can securely share meeting knowledge without leaking Q&A histories.

---

## ✨ Key Features

- **🎧 Smart Audio Preprocessing:** Accepts chaotic audio uploads (`.mp3`, `.m4a`, etc.), strips silence, and aggressively mitigates background noise utilizing SNR thresholds.
- **🗣️ Advanced Diarization & Transcription:** Uses Pyannote for speaker clustering and Whisper for high-fidelity offline transcription.
- **🧠 LangGraph Multi-Agent Pipeline:** Meeting minutes aren't just summarized; they are *engineered*. An evaluator/optimizer loop refines the transcription into structured summaries, key decisions, and actionable items.
- **💬 Streaming Q&A Chatbot:** Ask the AI questions about the meeting ("What was the budget?", "Who is assigned to X?"). Responses are streamed token-by-token (SSE) right into the UI for a ChatGPT-like feel.
- **🔒 Department-Based Access Control:** Meeting summaries are shared securely within a department (`dept_id`), but every user's Q&A chat history remains 100% strictly private. 
- **🌐 Offline-First Architecture:** No internet? No problem. The app seamlessly fails over to a local SQLite database (using a negative-ID sync pattern) and will automatically securely sync to Supabase once the internet connection is restored.
- **🛡️ JWT Authentication:** Rock-solid security utilizing secure `HttpOnly` cookies. 

---

## 🛠️ Tech Stack & Architecture

### **AI & Machine Learning**
- **[Ollama (Llama 3.2: 3b)](https://ollama.com/)** - Core local LLM responsible for chat generation and reasoning.
- **[LangChain](https://www.langchain.com/)** - Framework mapping prompts, system messages, and streaming response pipelines.
- **[LangGraph](https://www.langchain.com/langgraph)** - Orchestrates the StateGraph for iterative evaluation and optimization of the meeting minutes.
- **[Whisper (OpenAI)](https://github.com/openai/whisper) & [Pyannote](https://huggingface.co/pyannote/speaker-diarization-3.1)** - Transcription and Speaker Diarization.
- **[Librosa](https://librosa.org/) & [Noisereduce](https://pypi.org/project/noisereduce/)** - Raw byte manipulation, silence trimming, and SNR audio cleaning.

### **Backend**
- **[FastAPI](https://fastapi.tiangolo.com/)** - High performance, asynchronous Python backend. Features custom route dependencies, streaming responses (`text/event-stream`), and multipart form ingestion.
- **[Supabase](https://supabase.com/)** - Primary cloud database (PostgreSQL) for user, meeting, and chat state management.
- **[SQLite](https://www.sqlite.org/)** - Local offline database engine capturing state securely when the network drops.
- **[PyJWT](https://pyjwt.readthedocs.io/en/latest/)** - Token generation and authentication middleware.

### **Frontend**
- **Vanilla JS / HTML / CSS** - Zero-dependency, blazing-fast client. Built with custom CSS custom variables (`var(--accent)`), glassmorphism, and responsive gradients.
- **Server-Sent Events (SSE)** - Real-time DOM manipulation powered by stream readers intercepting network byte chunks.

---

## 🚀 How It Works Under The Hood

1. **Ingestion:** User uploads an audio file via the frontend. The backend safely streams it to a local temporary disk to avoid RAM saturation.
2. **The Pipeline:** 
   - `preprocess_audio` normalizes the bytes.
   - `whisper/pyannote` converts audio to text with speaker labels.
   - A `LangGraph` workflow passes the raw text to an **Evaluator AI**, which grades the summary, passes it to an **Optimizer AI**, and repeats until the final Action Items meet enterprise standards.
3. **Persistence:** The summarized report is saved. If the user is online, it is saved directly to **Supabase** with the department's Access ID. If offline, a temporary `-ID` is generated and saved via **SQLite**.
4. **Interaction:** Users can click on a meeting. The frontend calls the backend Q&A Chatbot, initializing `chain.stream()`. The tokens fly sequentially back to the UI.