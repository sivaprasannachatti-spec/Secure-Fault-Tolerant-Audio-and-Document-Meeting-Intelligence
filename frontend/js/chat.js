// Use dynamic origin path to support seamless deployment and resolve local CORS issues
const API_BASE_URL = `${window.location.origin}/api`;
const AUDIO_API_URL = API_BASE_URL; 
const DOCS_API_URL = API_BASE_URL;

document.addEventListener('DOMContentLoaded', async () => {
    const chatHistoryList = document.getElementById('chat-history-list');
    const chatMessages = document.getElementById('chat-messages');
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');

    let currentChatTitle = null; // Tracks which chat we are currently in
    let currentChatId = null;
    let activeTimerInterval = null;
    let currentMeetingId = null;
    let currentUploadMode = 'audio'; // Tracks modal state: 'audio' or 'document'
    let currentMeetingType = 'audio'; // Tracks the type of the currently viewed meeting
    
    // Performance Pagination state variables (Phase 1, Item 3)
    let hasMoreMessages = true;
    let isLoadingMore = false;
    let oldestMessageId = null;
    let isInitialLoading = false;
    const PAGE_LIMIT = 25;

    // ======================================================================
    // WORKSPACE ISOLATION LOGIC (Spec §A, §B)
    // ======================================================================
    const urlParams = new URLSearchParams(window.location.search);
    const workspaceMode = urlParams.get('mode'); // 'audio' or 'notes'
    
    // CRITICAL GUARD: No user should enter workspace without explicit selection
    if (!workspaceMode) {
        console.warn("⚠️ No workspace mode selected. Redirecting to selection page.");
        window.location.replace('../index.html');
        return;
    }
    
    // CRITICAL: Determine the API Base based on the workspace mode
    const API_BASE_URL = (workspaceMode === 'notes' || workspaceMode === 'document') ? DOCS_API_URL : AUDIO_API_URL;
    const WORKSPACE_TYPE = (workspaceMode === 'notes' || workspaceMode === 'document') ? 'document' : 'audio';
    const WORKSPACE_API_PREFIX = (WORKSPACE_TYPE === 'document') ? `${API_BASE_URL}/documents` : `${API_BASE_URL}/chat`;

    // Set initial state based on workspace
    currentMeetingType = WORKSPACE_TYPE;
    currentUploadMode = (workspaceMode === 'notes' || workspaceMode === 'document') ? 'document' : 'audio';

    // Update UI title or workspace indicator
    const sidebarTitle = document.querySelector('.logo');
    if (sidebarTitle) {
        sidebarTitle.innerHTML = WORKSPACE_TYPE === 'document'
            ? '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg> MeetingAI <span style="font-size: 0.7rem; opacity: 0.6; vertical-align: middle; background: rgba(168, 85, 247, 0.2); padding: 2px 6px; border-radius: 4px; margin-left: 5px;">NOTES</span>'
            : '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg> MeetingAI <span style="font-size: 0.7rem; opacity: 0.6; vertical-align: middle; background: rgba(99, 102, 241, 0.2); padding: 2px 6px; border-radius: 4px; margin-left: 5px;">AUDIO</span>';
    }

    function showToast(message, type = 'warning') {
        let container = document.querySelector('.toast-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'toast-container';
            document.body.appendChild(container);
        }

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `
            <div class="toast-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                    <line x1="12" y1="9" x2="12" y2="13"></line>
                    <line x1="12" y1="17" x2="12.01" y2="17"></line>
                </svg>
            </div>
            <div class="toast-message">${message}</div>
        `;

        container.appendChild(toast);

        setTimeout(() => {
            toast.style.animation = 'toastSlideOut 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards';
            setTimeout(() => toast.remove(), 400);
        }, 4000);
    }

    // ----------------------------------------------------------------------
    // Markdown Rendering & Sanitization (Phase 1 & 2)
    // ----------------------------------------------------------------------
    function safeRenderMarkdown(text) {
        if (!text) return "";
        let html = "";
        
        if (window.marked) {
            // Configure marked for line breaks
            marked.setOptions({
                breaks: true,
                gfm: true
            });
            html = window.marked.parse(text);
        } else {
            // Fallback Regex Parser for 100% Offline Mode
            html = text
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;");
            
            // Fenced Code Blocks (Basic multiline parsing)
            html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
                return `<pre><code class="language-${lang}">${code.trim()}</code></pre>`;
            });
            
            // Blockquotes
            html = html.replace(/^\s*>\s+(.*$)/gim, '<blockquote>$1</blockquote>');
            html = html.replace(/<\/blockquote>\s*<blockquote>/g, '<br>');
            
            // Headings
            html = html.replace(/^###\s+(.*$)/gim, '<h3>$1</h3>');
            html = html.replace(/^##\s+(.*$)/gim, '<h2>$1</h2>');
            html = html.replace(/^#\s+(.*$)/gim, '<h1>$1</h1>');
            
            // Bold
            html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
            // Italic
            html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
            // Inline Code
            html = html.replace(/`(.*?)`/g, '<code>$1</code>');
            
            // Unordered Lists
            html = html.replace(/^\s*[-*]\s+(.*$)/gim, '<ul><li>$1</li></ul>');
            html = html.replace(/<\/ul>\s*<ul>/g, '\n');
            
            // Ordered Lists
            html = html.replace(/^\s*\d+\.\s+(.*$)/gim, '<ol><li>$1</li></ol>');
            html = html.replace(/<\/ol>\s*<ol>/g, '\n');
            
            // Paragraphs and double-newlines split
            const parts = html.split(/\n\n+/);
            html = parts.map(part => {
                const trimmed = part.trim();
                if (trimmed.startsWith('<h') || 
                    trimmed.startsWith('<ul') || 
                    trimmed.startsWith('<ol') || 
                    trimmed.startsWith('<pre') || 
                    trimmed.startsWith('<blockquote')) {
                    return part;
                }
                return `<p>${part.replace(/\n/g, '<br>')}</p>`;
            }).join('\n');
        }
        
        // Sanitize parsed HTML to prevent XSS
        if (window.DOMPurify) {
            return window.DOMPurify.sanitize(html, {
                ALLOWED_TAGS: [
                    'p', 'br', 'strong', 'em', 'code', 'pre', 'ul', 'ol', 'li', 
                    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'span', 'blockquote', 'a'
                ],
                ALLOWED_ATTR: ['href', 'title', 'target', 'class']
            });
        } else {
            // Offline security sanitize fallback
            return html
                .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
                .replace(/<iframe\b[^<]*(?:(?!<\/iframe>)<[^<]*)*<\/iframe>/gi, '')
                .replace(/<embed\b[^<]*(?:(?!<\/embed>)<[^<]*)*<\/embed>/gi, '')
                .replace(/<object\b[^<]*(?:(?!<\/object>)<[^<]*)*<\/object>/gi, '')
                .replace(/href\s*=\s*["']\s*javascript:/gi, 'href="#"')
                .replace(/on\w+\s*=/gi, 'data-removed=');
        }
    }

    // --- Persistence & Recovery Logic ---
    function saveActiveProcess(meetingId, fileName, visibility, startTime) {
        localStorage.setItem('pending_upload', JSON.stringify({
            id: meetingId,
            fileName: fileName,
            visibility: visibility,
            startTime: startTime || Date.now()
        }));
    }

    function clearActiveProcess() {
        localStorage.removeItem('pending_upload');
    }

    async function recoverPendingUpload() {
        const pending = JSON.parse(localStorage.getItem('pending_upload'));
        if (!pending) return;

        console.log("🔄 Recovering pending upload:", pending.fileName);

        // Re-render the UI as if it's processing
        renderFileCard(pending.fileName, pending.visibility, true);
        const { timerElement, stepsElement, containerElement, iconElement, titleElement } = renderThinkingBlock(true);

        // Start the timer from the original start time
        const elapsedAtStart = Math.floor((Date.now() - pending.startTime) / 1000);
        startThinkingTimer(timerElement, elapsedAtStart);

        // Start polling for the result
        pollForMeetingResult(pending.id, containerElement, stepsElement, timerElement, iconElement, titleElement);
    }

    // --- Modern UI Rendering Helpers ---
    function renderFileCard(fileName, visibility, isUser = true) {
        const chatMessages = document.getElementById('chat-messages');
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${isUser ? 'user' : 'ai'}`;

        const initials = isUser ? document.getElementById('avatar-initials').innerText : 'AI';
        const avatarBg = isUser ? 'rgba(255, 255, 255, 0.1)' : 'var(--accent-gradient)';

        msgDiv.innerHTML = `
            <div class="avatar" style="background: ${avatarBg}; color: white; font-size: 0.8rem; font-weight: bold;">${initials}</div>
            <div class="message-box" style="background: transparent; border: none; padding: 0; box-shadow: none;">
                <div class="file-card">
                    <div class="file-icon">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
                    </div>
                        <div class="file-info">
                            <div class="file-name">${fileName}</div>
                            <div class="file-meta">
                                <span>${WORKSPACE_TYPE === 'document' ? '📄 Document' : '🎵 Audio'}</span>
                                <span>•</span>
                                <span>${visibility}</span>
                            </div>
                        </div>
                </div>
            </div>
        `;
        chatMessages.appendChild(msgDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function renderThinkingBlock(isRecovery = false) {
        const chatMessages = document.getElementById('chat-messages');
        const aiMsgDiv = document.createElement('div');
        aiMsgDiv.className = 'message ai';

        const uniqueId = Date.now();
        aiMsgDiv.innerHTML = `
            <div class="avatar" style="background: var(--accent-gradient); color: white; font-size: 0.8rem; font-weight: bold;">AI</div>
            <div class="message-box" style="width: 100%; max-width: 650px;">
                <details class="thinking-block" open id="think-container-${uniqueId}">
                    <summary class="thinking-header">
                        <div class="thinking-status">
                            <div class="thinking-icon-wrapper" id="think-icon-${uniqueId}">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" class="spin-anim" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><path d="M12 2a10 10 0 0 1 10 10"></path></svg>
                            </div>
                            <span id="think-title-${uniqueId}">${isRecovery ? 'Resuming Synthesis...' : 'Thinking & Processing'}</span>
                            <div class="thinking-timer" id="think-timer-${uniqueId}">0s</div>
                        </div>
                        <div class="thinking-toggle-icon">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
                        </div>
                    </summary>
                    <div class="thinking-body" id="think-steps-${uniqueId}">
                        <div class="thought-step"><span class="thought-bullet">></span> Initializing neural synthesis...</div>
                    </div>
                </details>
                <div class="message-content" id="report-content-${uniqueId}" style="display:none; margin-top: 15px;"></div>
            </div>
        `;
        chatMessages.appendChild(aiMsgDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;

        return {
            timerElement: document.getElementById(`think-timer-${uniqueId}`),
            stepsElement: document.getElementById(`think-steps-${uniqueId}`),
            containerElement: document.getElementById(`think-container-${uniqueId}`),
            iconElement: document.getElementById(`think-icon-${uniqueId}`),
            titleElement: document.getElementById(`think-title-${uniqueId}`),
            reportElement: document.getElementById(`report-content-${uniqueId}`)
        };
    }

    function startThinkingTimer(element, startFrom = 0) {
        let seconds = startFrom;
        element.innerText = `${seconds}s`;
        const interval = setInterval(() => {
            seconds++;
            element.innerText = `${seconds}s`;

            // Add custom thought sentences based on time
            const steps = element.closest('.message-box').querySelector('.thinking-body');
            if (seconds === 3) addThoughtStep(steps, "Extracting diarized transcript...");
            if (seconds === 7) addThoughtStep(steps, "Analyzing speaker interactions...");
            if (seconds === 12) addThoughtStep(steps, "Generating meeting minutes...");
            if (seconds === 18) addThoughtStep(steps, "Optimizing content quality...");
        }, 1000);
        return interval;
    }

    function addThoughtStep(container, text) {
        if (!container) return;
        const step = document.createElement('div');
        step.className = 'thought-step';
        step.innerHTML = `<span class="thought-bullet">></span> ${text}`;
        container.appendChild(step);
    }

    async function pollForMeetingResult(meetingId, container, steps, timer, icon, title) {
        const reportDiv = container.closest('.message-box').querySelector('.message-content');

        const pollInterval = setInterval(async () => {
            try {
                // We check if the meeting has content yet by calling getAllMeetings 
                // or a specific getMeetingContent if title was known.
                // For simplicity, let's look at the "meetings" list.
                // Use workspace-aware endpoint
                const res = await fetch(`${WORKSPACE_API_PREFIX}/getAllMeetings`, { credentials: 'include' });
                const data = await res.json();

                const meeting = data.meetings.find(m => m.meeting_id == meetingId);

                if (meeting && meeting.final_report && meeting.final_report.trim() !== "") {
                    // Success!
                    clearInterval(pollInterval);
                    clearInterval(activeTimerInterval);

                    addThoughtStep(steps, "<strong>Synthesis Complete.</strong>");
                    container.removeAttribute('open');

                    icon.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>`;
                    title.innerText = "Synthesized Meeting";

                    reportDiv.style.display = 'block';
                    reportDiv.innerHTML = renderMeetingReport(meeting.final_report);

                    currentMeetingId = meetingId;
                    clearActiveProcess();
                    loadChatHistory();
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                }
            } catch (e) {
                console.error("Polling error:", e);
            }
        }, 3000);
    }


    // 1. Authentication Check
    if (localStorage.getItem('isAuthenticated') !== 'true') {
        window.location.replace('../index.html');
        return;
    }

    // 1b. Load User Profile from localStorage
    const userName = localStorage.getItem('userName') || 'User';
    document.getElementById('user-display-name').innerText = userName;
    const initials = userName.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
    document.getElementById('avatar-initials').innerText = initials || 'U';

    // 2. Logout Handler
    document.getElementById('logout-btn').addEventListener('click', async () => {
        try {
            await fetch(`${API_BASE_URL}/user/logout`, {
                method: 'DELETE',
                credentials: 'include'
            });
            localStorage.removeItem('isAuthenticated');
            localStorage.removeItem('userName');
            window.location.replace('../index.html');
        } catch (err) {
            console.error(err);
        }
    });

    // 3. Delete Account Handler
    document.getElementById('delete-account-btn').addEventListener('click', async () => {
        if (confirm("Are you entirely sure you want to permanently delete your MeetingAI Workspace? This action cannot be undone.")) {
            try {
                await fetch(`${API_BASE_URL}/user/delete_account`, {
                    method: 'DELETE',
                    credentials: 'include'
                });
                localStorage.removeItem('isAuthenticated');
                localStorage.removeItem('userName');
                window.location.replace('../index.html');
            } catch (err) {
                console.error(err);
            }
        }
    });

    // 4. Load Chat History
    // Helper to render chat history list in DOM (Phase 2, Item 7)
    function renderChatHistoryUI(chats) {
        const chatHistoryList = document.getElementById('chat-history-list');
        chatHistoryList.innerHTML = '';
        const fragment = document.createDocumentFragment();
        chats.forEach(chat => {
            const item = document.createElement('div');
            item.className = 'history-item';
            item.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
                <span>${chat.chat_title}</span>
            `;
            item.addEventListener('click', () => {
                localStorage.setItem('last_viewed_type', 'chat');
                localStorage.setItem('last_viewed_chat_id', chat.chat_id);
                localStorage.setItem('last_viewed_title', chat.chat_title);
                localStorage.setItem('last_viewed_meeting_type', WORKSPACE_TYPE);
                loadOldChat(chat.chat_id, chat.chat_title);
            });
            fragment.appendChild(item);
        });
        chatHistoryList.appendChild(fragment);
    }

    // 4. Load Chat History (Personal) - Optimized with Stale-While-Revalidate cache (Phase 4, Item 12)
    async function loadChatHistory() {
        try {
            const cacheKey = `cache_chats_${WORKSPACE_TYPE}`;
            const cached = localStorage.getItem(cacheKey);
            if (cached) {
                try {
                    renderChatHistoryUI(JSON.parse(cached));
                } catch (e) {
                    console.error("Failed to parse cached chats:", e);
                }
            }

            const res = await fetch(`${WORKSPACE_API_PREFIX}/getChats`, { credentials: 'include' });
            if (!res.ok) return;
            const data = await res.json();
            const chats = data.chats.reverse();

            localStorage.setItem(cacheKey, JSON.stringify(chats));
            renderChatHistoryUI(chats);
        } catch (err) {
            console.error("Failed to load chats:", err);
        }
    }

    // Helper to render meetings list in DOM (Phase 2, Item 7)
    function renderMeetingsUI(meetings) {
        const meetingList = document.getElementById('meeting-list');
        meetingList.innerHTML = '';
        const fragment = document.createDocumentFragment();
        meetings.forEach(meeting => {
            const item = document.createElement('div');
            item.className = 'history-item';
            item.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"></path></svg>
                <span>${meeting.meeting_title}</span>
            `;
            item.addEventListener('click', () => {
                localStorage.setItem('last_viewed_type', 'meeting');
                localStorage.setItem('last_viewed_meeting_id', meeting.meeting_id);
                localStorage.setItem('last_viewed_title', meeting.meeting_title);
                localStorage.setItem('last_viewed_meeting_type', WORKSPACE_TYPE);
                loadMeetingOnly(meeting.meeting_id, meeting.meeting_title);
            });
            fragment.appendChild(item);
        });
        meetingList.appendChild(fragment);
    }

    // 4b. Load Meeting History (Shared) - Optimized with Stale-While-Revalidate cache (Phase 4, Item 12)
    async function loadAllMeetings() {
        try {
            const cacheKey = `cache_meetings_${WORKSPACE_TYPE}`;
            const cached = localStorage.getItem(cacheKey);
            if (cached) {
                try {
                    renderMeetingsUI(JSON.parse(cached));
                } catch (e) {
                    console.error("Failed to parse cached meetings:", e);
                }
            }

            const res = await fetch(`${WORKSPACE_API_PREFIX}/getAllMeetings`, { credentials: 'include' });
            if (!res.ok) return;
            const data = await res.json();
            const meetings = data.meetings.reverse();

            localStorage.setItem(cacheKey, JSON.stringify(meetings));
            renderMeetingsUI(meetings);
        } catch (err) {
            console.error("Failed to load meetings:", err);
        }
    }

    // 5b. Load ONLY Meeting Report (Clean View)
    async function loadMeetingOnly(meetingId, title) {
        currentChatTitle = null; // Exit chat mode
        currentMeetingType = 'audio'; // Default; overridden if document type detected

        // Highlight in sidebar using the title text
        document.querySelectorAll('.history-item').forEach(i => {
            if (i.innerText.trim() === title) i.classList.add('active');
            else i.classList.remove('active');
        });

        chatMessages.innerHTML = '<div class="typing-indicator" style="margin: auto;"></div>';

        try {
            const res = await fetch(`${WORKSPACE_API_PREFIX}/getMeetingContent/${meetingId}`, { credentials: 'include' });
            if (!res.ok) throw new Error("Failed to fetch meeting");
            const data = await res.json();

            chatMessages.innerHTML = '';
            const content = data.meeting_content;
            if (content && content.final_report) {
                const reportDiv = document.createElement('div');
                reportDiv.className = 'message ai';
                reportDiv.innerHTML = `
                    <div class="avatar" style="background: var(--accent-gradient); color: white; font-size: 0.8rem; font-weight: bold;">AI</div>
                    <div class="message-box" style="width: 100%; max-width: 680px;">
                        ${renderMeetingReport(content.final_report)}
                    </div>
                `;
                chatMessages.appendChild(reportDiv);
                currentMeetingId = content.meeting_id;
                // Detect meeting type from backend response
                if (content.meeting_type === 'document') currentMeetingType = 'document';
            } else {
                chatMessages.innerHTML = '<p style="text-align:center; color: var(--text-secondary); margin-top: 2rem;">No report content available for this meeting.</p>';
            }
        } catch (err) {
            console.error(err);
            chatMessages.innerHTML = '<p style="text-align:center; color: #f87171; margin-top: 2rem;">Error loading meeting report.</p>';
        }
    }

    // 5. Load Specific Chat Messages with progressive pagination cursor (Phase 1, Item 3 / Phase 2, Item 8)
    async function loadOldChat(chatId, title, isLoadMore = false) {
        currentChatTitle = title;
        currentChatId = chatId;

        // Highlight in sidebar
        document.querySelectorAll('.history-item').forEach(i => {
            if (i.innerText.trim() === title) i.classList.add('active');
            else i.classList.remove('active');
        });

        if (!isLoadMore) {
            isInitialLoading = true;
            hasMoreMessages = true;
            isLoadingMore = false;
            oldestMessageId = null;

            chatMessages.innerHTML = `
                <div class="skeleton-chat-loading" style="height: 100%; display: flex; align-items: center; justify-content: center;">
                    <div class="typing-indicator">
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                    </div>
                </div>`;
        } else {
            isLoadingMore = true;
            // Prepend a lightweight spinner/loading element at the top
            let loadSpinner = document.getElementById('chat-history-load-spinner');
            if (!loadSpinner) {
                loadSpinner = document.createElement('div');
                loadSpinner.id = 'chat-history-load-spinner';
                loadSpinner.style = 'text-align: center; padding: 10px; color: var(--text-secondary); font-size: 0.85rem; font-weight: 500;';
                loadSpinner.innerHTML = '⚡ Loading past messages...';
                
                const reportDiv = chatMessages.querySelector('.report-message');
                if (reportDiv) {
                    reportDiv.insertAdjacentElement('afterend', loadSpinner);
                } else {
                    chatMessages.prepend(loadSpinner);
                }
            }
        }

        try {
            const url = isLoadMore 
                ? `${WORKSPACE_API_PREFIX}/getOldChat/${chatId}?limit=${PAGE_LIMIT}&before_id=${oldestMessageId}`
                : `${WORKSPACE_API_PREFIX}/getOldChat/${chatId}?limit=${PAGE_LIMIT}`;

            const res = await fetch(url, { credentials: 'include' });
            if (!res.ok) throw new Error("Failed to fetch messages");
            const data = await res.json();

            // Store scroll positioning metrics before updating DOM if prepending items
            const previousScrollHeight = chatMessages.scrollHeight;
            const previousScrollTop = chatMessages.scrollTop;

            if (!isLoadMore) {
                chatMessages.innerHTML = ''; // Clear indicator/skeleton
                
                // Render the Meeting Report at the top so user has context
                if (data.final_report) {
                    const reportDiv = document.createElement('div');
                    reportDiv.className = 'message ai report-message';
                    reportDiv.innerHTML = `
                        <div class="avatar" style="background: var(--accent-gradient); color: white; font-size: 0.8rem; font-weight: bold;">AI</div>
                        <div class="message-box" style="width: 100%; max-width: 680px;">
                            ${renderMeetingReport(data.final_report)}
                        </div>
                        <div style="width: 100%; height: 1px; background: rgba(255, 255, 255, 0.05); margin: 20px 0;"></div>
                    `;
                    chatMessages.appendChild(reportDiv);
                }
            } else {
                // Remove the loading spinner
                const loadSpinner = document.getElementById('chat-history-load-spinner');
                if (loadSpinner) loadSpinner.remove();
            }

            const fragment = document.createDocumentFragment();
            data.chat.forEach(msg => {
                const msgDiv = createMessageElement(msg.type.toLowerCase(), msg.message, msg.message_id);
                fragment.appendChild(msgDiv);
            });

            if (data.chat.length > 0) {
                // Capture the oldest message ID in the returned chunk for next fetch cursor
                oldestMessageId = data.chat[0].message_id;
            }

            if (data.chat.length < PAGE_LIMIT) {
                hasMoreMessages = false;
            }

            // Insert messages block into DOM
            if (!isLoadMore) {
                chatMessages.appendChild(fragment);
                requestAnimationFrame(() => {
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                });
            } else {
                const reportDiv = chatMessages.querySelector('.report-message');
                if (reportDiv) {
                    reportDiv.after(fragment);
                } else {
                    chatMessages.prepend(fragment);
                }
                
                // Keep the viewport scroll stable so user is not disoriented by prepended logs
                requestAnimationFrame(() => {
                    const newScrollHeight = chatMessages.scrollHeight;
                    chatMessages.scrollTop = previousScrollTop + (newScrollHeight - previousScrollHeight);
                });
            }

            currentMeetingId = data.meeting_id;
            // Detect meeting type from backend response
            if (data.meeting_type === 'document') currentMeetingType = 'document';
            else currentMeetingType = 'audio';
            
        } catch (err) {
            console.error(err);
            if (!isLoadMore) {
                chatMessages.innerHTML = '<p style="text-align:center; color: #f87171; margin-top: 2rem;">Error loading messages.</p>';
            } else {
                const loadSpinner = document.getElementById('chat-history-load-spinner');
                if (loadSpinner) loadSpinner.innerHTML = '⚠️ Failed to load older messages.';
            }
        } finally {
            isInitialLoading = false;
            isLoadingMore = false;
        }
    }

    // Helpers to support progressive rendering and batch DocumentFragments (Phase 2, Item 9 / Phase 4, Item 15)
    function escapeHtml(string) {
        return String(string)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function createMessageElement(role, text, messageId = null) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${role === 'ai' ? 'ai' : 'user'}`;
        if (messageId) {
            msgDiv.setAttribute('data-message-id', messageId);
        }

        const avatarColor = role === 'ai' ? 'var(--accent-gradient)' : 'rgba(255, 255, 255, 0.1)';
        const initials = role === 'ai' ? 'AI' : document.getElementById('avatar-initials').innerText;

        // Render message with temporary plain text preview to make DOM paint near-instant
        msgDiv.innerHTML = `
            <div class="avatar" style="background: ${avatarColor}; color: white; font-size: 0.8rem; font-weight: bold;">${initials}</div>
            <div class="message-box">
                <div class="message-content message-content-pending" style="white-space: pre-wrap; font-family: inherit;">${escapeHtml(text)}</div>
            </div>
        `;

        // Progressive Markdown parsing in browser idle cycles
        const scheduleHydration = window.requestIdleCallback || (cb => setTimeout(cb, 15));
        scheduleHydration(() => {
            const contentDiv = msgDiv.querySelector('.message-content');
            if (contentDiv) {
                contentDiv.innerHTML = safeRenderMarkdown(text);
                contentDiv.classList.remove('message-content-pending');
                contentDiv.style.whiteSpace = '';
                contentDiv.style.fontFamily = '';
            }
        });

        return msgDiv;
    }

    // 6. Helper to render messages
    function renderMessage(role, text) {
        const chatMessages = document.getElementById('chat-messages');
        const msgDiv = createMessageElement(role, text);
        chatMessages.appendChild(msgDiv);
        requestAnimationFrame(() => {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        });
    }

    // 6b. Render structured meeting report as premium cards
    function renderMeetingReport(reportData) {
        // Try parsing JSON, fallback to plain text for old reports
        let report;
        try {
            report = typeof reportData === 'string' ? JSON.parse(reportData) : reportData;
        } catch (e) {
            // Old plain-text format — render as-is
            return `<div class="message-content" style="padding: 10px;"><strong>Meeting Analysis Report:</strong><br><br>${reportData.replace(/\n/g, '<br>')}</div>`;
        }

        // Build Action Items HTML
        let actionItemsHTML = '';
        if (report.action_items && report.action_items.length > 0) {
            actionItemsHTML = report.action_items.map(item => `
                <div class="action-item-card">
                    <div class="action-item-title">${item.action_item || 'N/A'}</div>
                    <div class="action-item-meta">
                        <span class="action-meta-tag speaker">👤 ${item.speaker || 'Unknown'}</span>
                        <span class="action-meta-tag deadline">📅 ${item.deadline || 'N/A'}</span>
                        <span class="action-meta-tag status">● ${item.status || 'Pending'}</span>
                    </div>
                </div>
            `).join('');
        } else {
            actionItemsHTML = '<div class="report-empty">No action items identified</div>';
        }

        // Build Key Decisions HTML
        let decisionsHTML = '';
        if (report.key_decisions && report.key_decisions.length > 0) {
            decisionsHTML = report.key_decisions.map(item => `
                <div class="decision-item">
                    <div class="decision-bullet"></div>
                    <div class="decision-content">
                        <div class="decision-topic">${item.topic || 'General'}</div>
                        <div class="decision-text">${item.decision || 'N/A'}</div>
                        <div class="decision-speaker">by ${item.speaker || 'Unknown'}</div>
                    </div>
                </div>
            `).join('');
        } else {
            decisionsHTML = '<div class="report-empty">No key decisions recorded</div>';
        }

        return `
            <div class="report-container">
                <div class="report-section">
                    <div class="report-section-header">
                        <div class="report-section-icon summary">📝</div>
                        <div class="report-section-title">Summary</div>
                    </div>
                    <div class="report-section-body">
                        <div class="report-summary-text">${safeRenderMarkdown(report.summary || 'No summary available.')}</div>
                    </div>
                </div>

                <div class="report-section">
                    <div class="report-section-header">
                        <div class="report-section-icon actions">✅</div>
                        <div class="report-section-title">Action Items</div>
                    </div>
                    <div class="report-section-body">
                        ${actionItemsHTML}
                    </div>
                </div>

                <div class="report-section">
                    <div class="report-section-header">
                        <div class="report-section-icon decisions">🔑</div>
                        <div class="report-section-title">Key Decisions</div>
                    </div>
                    <div class="report-section-body">
                        ${decisionsHTML}
                    </div>
                </div>
            </div>
        `;
    }

    // 6c. Render an empty report shell for streaming
    function renderStreamingShell(container) {
        container.style.display = 'block';
        container.innerHTML = `
            <div class="report-container">
                <div class="report-section" id="section-summary">
                    <div class="report-section-header">
                        <div class="report-section-icon summary">📝</div>
                        <div class="report-section-title">Summary</div>
                    </div>
                    <div class="report-section-body">
                        <div class="report-summary-text streaming-content"></div>
                    </div>
                </div>

                <div class="report-section" id="section-action_items">
                    <div class="report-section-header">
                        <div class="report-section-icon actions">✅</div>
                        <div class="report-section-title">Action Items</div>
                    </div>
                    <div class="report-section-body">
                        <div class="action-items-stream streaming-content" style="font-family: monospace; white-space: pre-wrap; font-size: 0.85rem; opacity: 0.8;"></div>
                    </div>
                </div>

                <div class="report-section" id="section-key_decisions">
                    <div class="report-section-header">
                        <div class="report-section-icon decisions">🔑</div>
                        <div class="report-section-title">Key Decisions</div>
                    </div>
                    <div class="report-section-body">
                        <div class="decisions-stream streaming-content" style="font-family: monospace; white-space: pre-wrap; font-size: 0.85rem; opacity: 0.8;"></div>
                    </div>
                </div>
            </div>
        `;
        return container.querySelector('.report-container');
    }


    // 11. Mobile Responsiveness Handlers
    const mobileMenuBtn = document.getElementById('mobile-menu-btn');
    const mobileCloseBtn = document.getElementById('mobile-close-btn');
    const sidebarOverlay = document.getElementById('sidebar-overlay');
    const appContainer = document.querySelector('.app-container');
    const mobileUploadShortcut = document.getElementById('mobile-upload-shortcut-btn');

    function toggleMobileSidebar(show) {
        if (show) {
            appContainer.classList.add('sidebar-open');
        } else {
            appContainer.classList.remove('sidebar-open');
        }
    }

    if (mobileMenuBtn) {
        mobileMenuBtn.addEventListener('click', () => toggleMobileSidebar(true));
    }

    if (mobileCloseBtn) {
        mobileCloseBtn.addEventListener('click', () => toggleMobileSidebar(false));
    }

    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', () => toggleMobileSidebar(false));
    }

    if (mobileUploadShortcut) {
        mobileUploadShortcut.addEventListener('click', () => {
            uploadModal.style.display = 'flex';
        });
    }

    // Auto-close sidebar on mobile when a chat history item is clicked
    document.getElementById('chat-history-list').addEventListener('click', (e) => {
        if (window.innerWidth <= 768 && (e.target.classList.contains('history-item') || e.target.closest('.history-item'))) {
            toggleMobileSidebar(false);
        }
    });

    // Handle initial state and recovery in parallel (Phase 2, Item 5)
    const listsPromise = Promise.all([
        loadChatHistory(),
        loadAllMeetings()
    ]);
    recoverPendingUpload();

    // Restore last viewed item ONLY if it matches the current workspace (Spec §A, §B)
    const lastType = localStorage.getItem('last_viewed_type');
    const lastTitle = localStorage.getItem('last_viewed_title');
    const lastMeetingId = localStorage.getItem('last_viewed_meeting_id');
    const lastChatId = localStorage.getItem('last_viewed_chat_id');
    const lastMeetingType = localStorage.getItem('last_viewed_meeting_type') || 'audio';

    if (lastMeetingType === WORKSPACE_TYPE) {
        if (lastType === 'chat' && lastChatId && lastTitle) {
            loadOldChat(lastChatId, lastTitle);
        } else if (lastType === 'meeting' && lastMeetingId && lastTitle) {
            loadMeetingOnly(lastMeetingId, lastTitle);
        }
    } else {
        // Clear state if workspace mismatch to prevent cross-contamination
        localStorage.removeItem('last_viewed_type');
        localStorage.removeItem('last_viewed_title');
        localStorage.removeItem('last_viewed_meeting_id');
        localStorage.removeItem('last_viewed_chat_id');
        localStorage.removeItem('last_viewed_meeting_type');
    }

    await listsPromise;

    // Attach Scroll Observer on chatMessages to trigger progressive cursor pagination (Phase 3, Item 10 / Phase 4, Item 14)
    chatMessages.addEventListener('scroll', () => {
        if (chatMessages.scrollTop < 30 && hasMoreMessages && !isLoadingMore && !isInitialLoading && currentChatId) {
            loadOldChat(currentChatId, currentChatTitle, true);
        }
    });

    // 7. Send Message Handler
    async function sendMessage() {
        const text = chatInput.value.trim();
        if (!text) return;

        // Gating: Block chat if no context exists (Spec §4)
        if (!currentMeetingId) {
            showToast('Please upload a meeting recording or document before starting a chat.', 'warning');
            return;
        }

        chatInput.value = '';
        chatInput.style.height = 'auto';
        sendBtn.disabled = true;

        renderMessage('user', text);

        // Show typing indicator while waiting for stream to start
        const typingIndicator = document.createElement('div');
        typingIndicator.className = 'message ai';
        typingIndicator.innerHTML = `
            <div class="avatar" style="background: var(--accent-gradient); color: white; font-size: 0.8rem; font-weight: bold;">AI</div>
            <div class="message-box">
                <div class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
        `;
        chatMessages.appendChild(typingIndicator);
        chatMessages.scrollTop = chatMessages.scrollHeight;

        try {
            // Route to correct API based on workspace ecosystem
            let url;
            if (currentChatId) {
                // Continuation of existing chat
                url = (currentMeetingType === 'document')
                    ? `${API_BASE_URL}/documents/chat/${currentChatId}`
                    : `${API_BASE_URL}/chat/oldChat/${currentChatId}`;
            } else {
                // Starting a new chat
                url = (currentMeetingType === 'document')
                    ? `${API_BASE_URL}/documents/chat/new`
                    : `${API_BASE_URL}/chat/newChat`;
            }

            const body = currentChatTitle
                ? { query: text }
                : { query: text, meeting_id: currentMeetingId };

            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(body)
            });

            if (!res.ok) {
                const errorData = await res.json().catch(() => ({}));
                throw new Error(errorData.detail || "Failed to get response");
            }

            // Remove typing indicator and create an EMPTY AI message div to stream into
            typingIndicator.remove();
            const aiMsgDiv = document.createElement('div');
            aiMsgDiv.className = 'message ai';
            aiMsgDiv.innerHTML = `
                <div class="avatar" style="background: var(--accent-gradient); color: white; font-size: 0.8rem; font-weight: bold;">AI</div>
                <div class="message-box">
                    <div class="message-content"></div>
                </div>
            `;
            chatMessages.appendChild(aiMsgDiv);
            const contentDiv = aiMsgDiv.querySelector('.message-content');

            // Throttled & Scroll-Stabilized Streaming Renderer (Phase 2, Edge Case 1 & 4)
            let lastRenderTime = 0;
            let renderTimeout = null;

            function scheduleRender() {
                const now = Date.now();
                if (now - lastRenderTime > 120) {
                    performRender();
                } else {
                    if (renderTimeout) clearTimeout(renderTimeout);
                    renderTimeout = setTimeout(performRender, 120 - (now - lastRenderTime));
                }
            }

            function performRender() {
                lastRenderTime = Date.now();
                
                // Scroll stabilization: only auto-scroll if user is close to the bottom (within 150px)
                const shouldScroll = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight < 150;
                
                // Streaming-safe markdown rendering
                contentDiv.innerHTML = safeRenderMarkdown(fullText);
                
                if (shouldScroll) {
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                }
            }

            // Read the SSE stream token by token
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let fullText = '';
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop(); // Keep incomplete line in buffer

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const data = line.slice(6).trim();
                    if (data === '[DONE]') break;

                    try {
                        const parsed = JSON.parse(data);

                        // If it's a chat_title event (new chat only), save it and refresh sidebar
                        if (parsed.chat_title && !currentChatTitle) {
                            currentChatTitle = parsed.chat_title;
                            if (parsed.chat_id) {
                                currentChatId = parsed.chat_id;
                                localStorage.setItem('last_viewed_chat_id', currentChatId);
                                localStorage.setItem('last_viewed_type', 'chat');
                                localStorage.setItem('last_viewed_title', currentChatTitle);
                                localStorage.setItem('last_viewed_meeting_type', WORKSPACE_TYPE);
                                if (currentMeetingId) {
                                    localStorage.setItem('last_viewed_meeting_id', currentMeetingId);
                                }
                            }
                            loadChatHistory();
                        }

                        // If it's a token, append to text and schedule throttled render
                        if (parsed.token) {
                            fullText += parsed.token;
                            scheduleRender();
                        }
                    } catch (e) {
                        // Ignore malformed SSE lines
                    }
                }
            }
            
            // Force final render to clean up any remaining buffered content
            if (renderTimeout) clearTimeout(renderTimeout);
            performRender();

        } catch (err) {
            console.error(err);
            if (typingIndicator.parentNode) typingIndicator.remove();

            // If it's a "no meeting" error, show toast instead of AI bubble
            if (err.message.includes("upload a meeting first")) {
                showToast(err.message, 'warning');
            } else {
                renderMessage('ai', err.message || "Sorry, I encountered an error. Please try again.");
            }
        } finally {
            sendBtn.disabled = false;
        }
    }

    sendBtn.addEventListener('click', sendMessage);
    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // 8. New Chat Button
    document.querySelector('.new-chat-btn').addEventListener('click', () => {
        currentChatTitle = null;
        currentChatId = null;
        currentMeetingId = null;
        currentMeetingType = WORKSPACE_TYPE; // Preserves the active workspace type
        localStorage.removeItem('last_viewed_type');
        localStorage.removeItem('last_viewed_title');
        document.querySelectorAll('.history-item').forEach(i => i.classList.remove('active'));
        chatMessages.innerHTML = `
            <div style="height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; color: var(--text-secondary); text-align: center;">
                <h2 style="color: var(--text-primary); margin-bottom: 0.5rem; font-weight: 600; font-size: 1.8rem;">New Chat</h2>
                <p style="max-width: 400px; line-height: 1.5; font-size: 1.05rem;">Upload a new audio file or ask a general question about the current meeting.</p>
            </div>`;
    });

    // 9. Meeting Upload Modal Handlers
    const uploadModal = document.getElementById('upload-modal');
    // ======================================================================
    // 7. Initialize Synthesis Modal Handlers
    // ======================================================================
    const openModalBtn = document.getElementById('open-upload-modal-btn') || document.getElementById('initialize-synthesis-btn');
    if (openModalBtn) {
        openModalBtn.addEventListener('click', () => {
            uploadModal.style.display = 'flex';
            
            // STRICT WORKSPACE ISOLATION: Hide the mode toggle and force the correct mode
            const modeToggle = document.querySelector('.modal-mode-toggle');
            if (modeToggle) modeToggle.style.display = 'none';

            if (workspaceMode === 'notes' || workspaceMode === 'document') {
                setUploadMode('document');
            } else {
                setUploadMode('audio');
            }
        });
    }
    document.getElementById('close-modal-btn').addEventListener('click', () => {
        uploadModal.style.display = 'none';
        document.getElementById('chat-upload-form').reset();
    });

    // 10. Process Audio Upload inside Chat page
    document.getElementById('chat-upload-form').addEventListener('submit', async (e) => {
        e.preventDefault();

        // If document mode, let the capture-phase document handler run instead
        if (currentUploadMode === 'document') return;

        const isDepartmentWide = document.querySelector('input[name="is_department_wide"]:checked').value === 'true';
        const fileInput = document.getElementById('chat-meeting-audio');
        if (!fileInput.files.length) return;
        const file = fileInput.files[0];

        // File validation: reject document files in audio mode
        const audioExt = file.name.split('.').pop().toLowerCase();
        if (['pdf', 'docx', 'txt', 'md'].includes(audioExt)) {
            showToast('Only audio files are accepted in this workspace. Switch to Document mode for meeting notes.', 'warning');
            return;
        }

        const visibilityLabel = isDepartmentWide ? 'Entire Department (Public)' : 'Just My Team (Private)';

        // 1. Close modal
        uploadModal.style.display = 'none';
        document.getElementById('chat-upload-form').reset();

        // 2. Clear current view for new context
        currentChatTitle = null;
        chatMessages.innerHTML = '';

        // 3. Render Premium File Card
        renderFileCard(file.name, visibilityLabel, true);

        // 4. Render Advanced Thinking UI
        const { timerElement, stepsElement, containerElement, iconElement, titleElement } = renderThinkingBlock();
        activeTimerInterval = startThinkingTimer(timerElement);

        try {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('is_department_wide', isDepartmentWide);

            const res = await fetch(`${API_BASE_URL}/chat/fileUpload`, {
                method: 'POST',
                credentials: 'include',
                body: formData
            });

            if (!res.ok) {
                const errorData = await res.json().catch(() => ({}));
                throw new Error(errorData.detail || "Upload failed");
            }

            // Process SSE Stream
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop(); // Keep incomplete line in buffer

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const dataStr = line.slice(6).trim();
                    if (dataStr === '[DONE]') break;

                    try {
                        const parsed = JSON.parse(dataStr);

                        // Skip keep-alive heartbeat events
                        if (parsed.keep_alive) continue;

                        // Handle stage errors (e.g. transcription failure)
                        if (parsed.status === 'error' && parsed.error) {
                            clearInterval(activeTimerInterval);
                            addThoughtStep(stepsElement, `<span style="color: #ef4444">Error: ${parsed.error}</span>`);
                            titleElement.innerText = "Process Failed";
                            iconElement.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`;
                            showToast(parsed.error, 'error');
                            continue;
                        }

                        // --- Updated Full Block Logic ---
                        if (parsed.stage && parsed.status === 'done' && parsed.final_text) {
                            const reportDiv = containerElement.closest('.message-box').querySelector('.message-content');

                            // If title stage is done, update the main thinking block title immediately
                            if (parsed.stage === 'title') {
                                titleElement.innerText = parsed.final_text;
                                addThoughtStep(stepsElement, `Title Generated: <strong>${parsed.final_text}</strong>`);
                            }

                            // Initialize shell if not present for summary/actions/decisions
                            if (parsed.stage !== 'title' && !reportDiv.querySelector('.report-container')) {
                                renderStreamingShell(reportDiv);
                                containerElement.removeAttribute('open');
                                if (titleElement.innerText === "Thinking & Processing") {
                                    titleElement.innerText = "Synthesizing...";
                                }
                            }

                            // Find the correct block to fill
                            let streamBox;
                            if (parsed.stage === 'summary') {
                                streamBox = reportDiv.querySelector('.report-summary-text');
                                if (streamBox) streamBox.innerHTML = safeRenderMarkdown(parsed.final_text);
                            }
                            if (parsed.stage === 'action_items' || parsed.stage === 'key_decisions') {
                                const statusEl = reportDiv.querySelector(`#section-${parsed.stage} .report-section-title`);
                                if (statusEl) statusEl.innerHTML += ' <span style="color: #10b981; font-size: 0.7rem;">(Done)</span>';
                            }
                            
                            chatMessages.scrollTop = chatMessages.scrollHeight;
                        }


                        if (parsed.stage === 'formatting' && parsed.status === 'in_progress') {
                            titleElement.innerText = "Finalizing Report...";
                        }

                        // Finalizing UI after DB save
                        if (parsed.stage === 'saved') {
                            currentMeetingId = parsed.meeting_id;
                            loadChatHistory();
                            loadAllMeetings();
                            clearActiveProcess();
                        }

                        // We care about the final saved stage to finalize the UI
                        if (parsed.stage === 'complete') {
                            clearInterval(activeTimerInterval);

                            const reportDiv = containerElement.closest('.message-box').querySelector('.message-content');

                            addThoughtStep(stepsElement, "<strong>Synthesis Complete.</strong>");
                            containerElement.removeAttribute('open');

                            iconElement.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>`;
                            
                            // Only update title if not already set by title stage
                            if (titleElement.innerText === "Synthesizing..." || titleElement.innerText === "Finalizing Report...") {
                                titleElement.innerText = parsed.meeting_title || "Synthesized Meeting";
                            }

                            reportDiv.style.display = 'block';
                            reportDiv.innerHTML = renderMeetingReport(parsed.final_report);

                            chatMessages.scrollTop = chatMessages.scrollHeight;
                        }

                    } catch (e) {
                        // Ignore malformed SSE lines
                    }
                }
            }

        } catch (error) {
            console.error('File upload failed:', error);
            clearInterval(activeTimerInterval);
            addThoughtStep(stepsElement, `<span style="color: #ef4444">Error: ${error.message}</span>`);
            titleElement.innerText = "Process Failed";
            iconElement.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`;
            showToast(error.message, 'error');
        }
    });

    // ======================================================================
    // DOCUMENT WORKFLOW — Modal Mode Toggle & Document Upload Handler
    // ======================================================================

    const modeAudioBtn = document.getElementById('mode-audio-btn');
    const modeDocumentBtn = document.getElementById('mode-document-btn');
    const fileInput = document.getElementById('chat-meeting-audio');
    const fileLabel = document.getElementById('upload-file-label');
    const formatHint = document.getElementById('upload-format-hint');
    const submitBtn = document.getElementById('upload-submit-btn');

    function setUploadMode(mode) {
        currentUploadMode = mode;
        if (mode === 'audio') {
            modeAudioBtn.style.background = 'var(--accent-gradient)';
            modeAudioBtn.style.color = 'white';
            modeDocumentBtn.style.background = 'transparent';
            modeDocumentBtn.style.color = 'var(--text-secondary)';
            fileInput.setAttribute('accept', 'audio/*');
            fileLabel.innerText = 'Select Audio Recording';
            formatHint.innerText = 'Supports MP3, WAV, M4A';
            submitBtn.innerText = 'Initialize Synthesis';
        } else {
            modeDocumentBtn.style.background = 'var(--accent-gradient)';
            modeDocumentBtn.style.color = 'white';
            modeAudioBtn.style.background = 'transparent';
            modeAudioBtn.style.color = 'var(--text-secondary)';
            fileInput.setAttribute('accept', '.pdf,.docx,.txt,.md');
            fileLabel.innerText = 'Select Meeting Notes';
            formatHint.innerText = 'Supports PDF, DOCX, TXT, MD';
            submitBtn.innerText = 'Analyze Document';
        }
    }

    if (modeAudioBtn) {
        modeAudioBtn.addEventListener('click', () => setUploadMode('audio'));
    }
    if (modeDocumentBtn) {
        modeDocumentBtn.addEventListener('click', () => setUploadMode('document'));
    }

    // Intercept form submission for DOCUMENT mode
    document.getElementById('chat-upload-form').addEventListener('submit', async (e) => {
        if (currentUploadMode !== 'document') return; // Let the existing audio handler run
        e.preventDefault();
        e.stopImmediatePropagation();

        const isDepartmentWide = document.querySelector('input[name="is_department_wide"]:checked').value === 'true';
        const fileInput = document.getElementById('chat-meeting-audio');
        if (!fileInput.files.length) return;
        const file = fileInput.files[0];

        // Validate file type
        const ext = file.name.split('.').pop().toLowerCase();
        if (!['pdf', 'docx', 'txt', 'md'].includes(ext)) {
            showToast('Only PDF, DOCX, TXT, and MD files are supported in Document mode.', 'warning');
            return;
        }

        const visibilityLabel = isDepartmentWide ? 'Entire Department (Public)' : 'Just My Team (Private)';

        // 1. Close modal
        uploadModal.style.display = 'none';
        document.getElementById('chat-upload-form').reset();
        setUploadMode('audio'); // Reset to default

        // 2. Clear current view
        currentChatTitle = null;
        currentMeetingType = 'document';
        chatMessages.innerHTML = '';

        // 3. Render Premium File Card (document type)
        const chatMessagesEl = document.getElementById('chat-messages');
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message user';
        const initials = document.getElementById('avatar-initials').innerText;
        msgDiv.innerHTML = `
            <div class="avatar" style="background: rgba(255, 255, 255, 0.1); color: white; font-size: 0.8rem; font-weight: bold;">${initials}</div>
            <div class="message-box" style="background: transparent; border: none; padding: 0; box-shadow: none;">
                <div class="file-card">
                    <div class="file-icon">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
                    </div>
                    <div class="file-info">
                        <div class="file-name">${file.name}</div>
                        <div class="file-meta">
                            <span>📄 Document</span>
                            <span>•</span>
                            <span>${visibilityLabel}</span>
                        </div>
                    </div>
                </div>
            </div>
        `;
        chatMessagesEl.appendChild(msgDiv);
        chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;

        // 4. Render Thinking UI with document-specific stages
        const { timerElement, stepsElement, containerElement, iconElement, titleElement } = renderThinkingBlock();
        activeTimerInterval = startDocumentThinkingTimer(timerElement);

        try {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('is_department_wide', isDepartmentWide);

            const res = await fetch(`${API_BASE_URL}/documents/upload`, {
                method: 'POST',
                credentials: 'include',
                body: formData
            });

            if (!res.ok) {
                const errorData = await res.json().catch(() => ({}));
                throw new Error(errorData.detail || "Upload failed");
            }

            // Process SSE Stream (same format as audio)
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const dataStr = line.slice(6).trim();
                    if (dataStr === '[DONE]') break;

                    try {
                        const parsed = JSON.parse(dataStr);

                        // Document pipeline stages
                        if (parsed.stage === 'parsing') addThoughtStep(stepsElement, "📄 Parsing document content...");
                        if (parsed.stage === 'analyzing') addThoughtStep(stepsElement, `🔍 Analyzing tokens (${parsed.token_count || '...'})...`);
                        if (parsed.stage === 'tree_generation' && parsed.status === 'in_progress') addThoughtStep(stepsElement, "🌳 Generating knowledge tree...");
                        if (parsed.stage === 'tree_generation' && parsed.status === 'done') addThoughtStep(stepsElement, "✅ Tree generation complete.");

                        // --- Updated Full Block Logic (Matched with Audio) ---
                        if (parsed.stage && parsed.status === 'done' && parsed.final_text) {
                            const reportDiv = containerElement.closest('.message-box').querySelector('.message-content');

                            if (parsed.stage === 'title') {
                                titleElement.innerText = parsed.final_text;
                                addThoughtStep(stepsElement, `Title Generated: <strong>${parsed.final_text}</strong>`);
                            }

                            if (parsed.stage !== 'title' && !reportDiv.querySelector('.report-container')) {
                                renderStreamingShell(reportDiv);
                                containerElement.removeAttribute('open');
                                if (titleElement.innerText === "Analyzing Document...") {
                                    titleElement.innerText = "Synthesizing...";
                                }
                            }

                            let streamBox;
                            if (parsed.stage === 'summary') {
                                streamBox = reportDiv.querySelector('.report-summary-text');
                                if (streamBox) streamBox.innerHTML = safeRenderMarkdown(parsed.final_text);
                            }
                            if (parsed.stage === 'action_items' || parsed.stage === 'key_decisions') {
                                const statusEl = reportDiv.querySelector(`#section-${parsed.stage} .report-section-title`);
                                if (statusEl) statusEl.innerHTML += ' <span style="color: #10b981; font-size: 0.7rem;">(Done)</span>';
                            }
                            chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
                        }

                        if (parsed.stage === 'formatting') {
                            titleElement.innerText = "Finalizing Report...";
                        }

                        // The 'saved' stage contains the meeting_id and final report
                        if (parsed.stage === 'saved') {
                            clearInterval(activeTimerInterval);
                            const reportDiv = containerElement.closest('.message-box').querySelector('.message-content');
                            addThoughtStep(stepsElement, "<strong>Document Analysis Complete.</strong>");
                            containerElement.removeAttribute('open');
                            iconElement.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>`;
                            titleElement.innerText = "Document Analyzed";
                            reportDiv.style.display = 'block';
                            reportDiv.innerHTML = renderMeetingReport(parsed.final_report);
                            currentMeetingId = parsed.meeting_id;
                            currentMeetingType = 'document';
                            clearActiveProcess();
                            loadChatHistory();
                            loadAllMeetings();
                            chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
                        }

                        // Handle the 'complete' stage (contains final_report for the saved stage to use)
                        if (parsed.stage === 'complete') {
                            // The complete stage is now followed by 'saved' stage
                            // which contains the meeting_id and persisted report.
                        }

                    } catch (e) {
                        // Ignore malformed SSE lines
                    }
                }
            }

        } catch (error) {
            console.error('Document upload failed:', error);
            clearInterval(activeTimerInterval);
            addThoughtStep(stepsElement, `<span style="color: #ef4444">Error: ${error.message}</span>`);
            titleElement.innerText = "Process Failed";
            iconElement.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`;
            showToast(error.message, 'error');
        }
    }, true); // Use capture phase to run before the audio handler

    function startDocumentThinkingTimer(element, startFrom = 0) {
        let seconds = startFrom;
        element.innerText = `${seconds}s`;
        const interval = setInterval(() => {
            seconds++;
            element.innerText = `${seconds}s`;
            const steps = element.closest('.message-box').querySelector('.thinking-body');
            if (seconds === 2) addThoughtStep(steps, "Extracting document content...");
            if (seconds === 5) addThoughtStep(steps, "Normalizing structure...");
            if (seconds === 10) addThoughtStep(steps, "Building semantic tree...");
            if (seconds === 20) addThoughtStep(steps, "Streaming intelligence report...");
        }, 1000);
        return interval;
    }

});

