# Real-Time Google Meet AI Integration Architecture

This document provides a senior-engineer perspective on architecting a production-grade real-time meeting intelligence system, similar to Otter.ai or Fireflies.ai, built on top of your existing MeetingAI platform.

---

## 1. Google Meet Integration: How Bots Join Meetings

To integrate with Google Meet, you cannot rely purely on official APIs for raw audio extraction, as Google Workspace does not expose real-time raw audio streams to third parties via API. Production systems use **Headless Browser Bot Infrastructures**.

### Comparison of Approaches

| Approach | Scalability | Reliability | Infrastructure Complexity | Enterprise Readiness |
| :--- | :--- | :--- | :--- | :--- |
| **Headless Browser (Puppeteer/Playwright)** | High (with K8s) | High | Very High | Yes (Standard industry approach) |
| **Chrome Extension** | N/A (Client-side) | Medium (Depends on user machine) | Low | No (Cannot run 24/7 autonomously) |
| **Google Meet Add-on/API** | High | High | Low | No (No raw audio stream access) |
| **Virtual Audio Cables (WebRTC)** | Low | Low | Extreme | No |

**The Industry Standard Approach (How Fireflies/Otter work):**
1. A scheduling system provisions a **headless Chromium container** using Playwright or Puppeteer via a cloud provider (e.g., AWS ECS or Kubernetes).
2. The headless browser navigates to the Google Meet URL.
3. The bot bypasses the "Join" screen using DOM manipulation (clicking "Join Now").
4. It hooks into the WebRTC stream or uses a virtual audio device (like PulseAudio/Xvfb in Linux) to capture the incoming speaker audio.

> [!WARNING]
> **Anti-Bot Detection Risks:** Google frequently changes the DOM structure of Meet. Bots using hardcoded CSS selectors will break. Production bots use resilient locators (ARIA labels) and computer vision fallbacks to find the "Join" button.

---

## 2. Google Calendar Integration

To achieve "auto-join," the system must know when meetings occur. This requires deep Google Calendar integration.

### Architecture Workflow
1. **OAuth2 Flow:** Users authenticate via Google Workspace OAuth2. You request `https://www.googleapis.com/auth/calendar.readonly`.
2. **Webhook Sync (Google Push Notifications):** Instead of polling, register a Google Calendar Webhook channel. When a user's calendar changes, Google hits your endpoint.
3. **Event Parsing:** Extract the Google Meet URL (`meet.google.com/...`) from the event metadata.
4. **Job Scheduling:** Use a distributed scheduler (e.g., Celery, Temporal, AWS EventBridge, or Redis Queue) to schedule a bot launch 1 minute before the meeting starts.

### Enterprise Considerations
* **Token Refresh:** Store refresh tokens securely in a KMS (Key Management Service). Implement middleware to auto-refresh tokens before expiry.
* **Security Review:** To request Calendar scopes, your app will require a **Google Cloud Security Assessment (CASA)**, which costs $15k-$75k and takes weeks to pass for production.

---

## 3. Real-Time Audio Streaming & Transcription

You currently use Deepgram Nova-3. Deepgram is excellent for this. You need to pivot from REST API batch uploads to their **WebSocket Live Streaming API**.

### Streaming Pipeline
1. **Audio Capture:** The Headless Bot captures PCM audio from the virtual audio device.
2. **Chunking & Buffering:** Chunk audio into small buffers (e.g., 100ms or 250ms) to ensure low latency without overflowing the WebSocket.
3. **WebSocket Connection:** The bot establishes a secure WSS connection to Deepgram.
4. **Diarization:** Deepgram's streaming API provides endpointing (`is_final=True` vs `is_final=False`). As the speaker talks, interim transcripts are sent. When they pause, a final transcript with the `speaker_id` is sent.

> [!TIP]
> **Production Architecture:** Decouple the headless browser from the AI pipeline. The bot should *only* push audio to an event broker (like Kafka or Redis Streams). A separate fleet of worker microservices consumes this stream and talks to Deepgram. This prevents the bot container from crashing if the AI pipeline stalls.

---

## 4. Real-Time AI Meeting Intelligence

Generating live action items and summaries requires handling "rolling context" without running out of tokens or causing hallucination.

### The Rolling Context Window Architecture
1. **Transcript Aggregation:** Collect finalized Deepgram sentences.
2. **Time-based Chunking:** Every X minutes (e.g., 5 minutes), take the aggregated transcript chunk.
3. **Incremental Summarization:** Pass the chunk to a fast LLM (like your Llama-3.1-8B) with the prompt: *"Update the existing meeting summary with this new context..."*
4. **State Storage:** Store the running summary in a fast key-value store (Redis).
5. **Streaming to UI:** Broadcast the updated summary to the web client via Server-Sent Events (SSE) or WebSockets.

---

## 5. Live AI Meeting Chat

For users to ask questions like *"What tasks were assigned to me?"* mid-meeting, you need real-time Retrieval-Augmented Generation (RAG).

### Real-Time Retrieval Architecture
Since you use Vectorless RAG, you rely on exact matching or passing the entire transcript.
* **For Short Meetings:** Just pass the running transcript into a large-context model (like Llama-3.3-70B).
* **For Long Meetings:** You must segment the transcript as it streams. Keep a rolling buffer of the last 15 minutes of conversation in memory for instant queries, and compress older parts into semantic summaries to preserve token space.

---

## 6. Google Meet Chat/Sidebar Integration

To inject your UI directly into the Google Meet window (so the user doesn't have to visit your site), the standard approach is a **Chrome Extension Overlay**.

### Extension Architecture
1. **Content Script:** Injects React/Vue UI components directly into the Google Meet DOM (e.g., floating right sidebar).
2. **Background Service Worker:** Manages the WebSocket connection to your backend, receiving live transcripts and summaries.
3. **Authentication:** The extension uses cookies or a popup to authenticate with your backend.

> [!CAUTION]
> **Limitations:** Chrome extensions only work on desktop browsers. They cannot easily capture native Google Meet audio due to browser security (CORS/MediaRecorder limits), which is why the Headless Bot (Section 1) is still required to actually "hear" everyone in the meeting.

---

## 7. Fault Tolerance & Edge Cases

### Meeting-Level Edge Cases
* **Stuck in Waiting Room:** The bot must use computer vision to detect "Waiting for host" text. Set a timeout (e.g., 10 mins). If not admitted, kill the container and notify the user.
* **Host Rejects Bot:** Detect the "You have been denied entry" modal. Send an email to the user.
* **Silent Meetings:** If Deepgram returns 0 words after 15 minutes, terminate the bot to save compute costs.

### Streaming Edge Cases
* **WebSocket Disconnects:** Implement exponential backoff for reconnection. Buffer audio locally in the bot container during the disconnect to prevent data loss.
* **Diarization Failures:** Maintain a fallback speaker tag (e.g., "Speaker X") if Deepgram fails to identify the speaker boundary.

### Infrastructure Edge Cases
* **Retry Storms:** If the database goes down, 500 bots trying to reconnect simultaneously will DDoS your own system. Use "Jitter" in your retry logic.

---

## 8. Production-Grade System Design

Here is the high-level architecture a Senior Engineer would design:

1. **Ingress:** AWS API Gateway / Nginx handles traffic.
2. **Bot Fleet (Kubernetes / AWS ECS):** An auto-scaling group of pods running Playwright + Xvfb (Virtual Display). Scaled via KEDA based on the number of upcoming calendar events.
3. **Message Broker (Kafka / Redis Streams):** The Bot Fleet streams raw audio buffers to a Kafka topic.
4. **Transcription Workers:** Consume audio from Kafka, maintain WebSockets with Deepgram, and push transcribed text back to a new Kafka topic.
5. **AI Pipeline Workers:** Consume transcripts, query Groq/LLMs for summaries, and update Redis.
6. **Client Gateway:** Maintains SSE/WebSocket connections to Chrome Extensions and Web UIs, broadcasting the Redis state.
7. **Storage:** PostgreSQL for long-term metadata. S3 for raw audio backups (if allowed by GBAC).

### Observability
* **Tracing:** OpenTelemetry to trace a meeting from "Join" to "Summary Generation."
* **Logging:** Fluentd -> Elasticsearch/Kibana for debugging bot failures.
* **Metrics:** Prometheus + Grafana to monitor Bot RAM usage, Deepgram latency, and LLM token generation speed.
