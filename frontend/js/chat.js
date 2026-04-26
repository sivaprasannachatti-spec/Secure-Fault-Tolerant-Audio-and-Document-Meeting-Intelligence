const API_BASE_URL = '/api'; // Dynamically resolve host

document.addEventListener('DOMContentLoaded', async () => {
    const chatHistoryList = document.getElementById('chat-history-list');
    const chatMessages = document.getElementById('chat-messages');
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');

    let currentChatTitle = null; // Tracks which chat we are currently in
    let activeTimerInterval = null;
    let currentMeetingId = null;

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
                            <span>Audio</span>
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
                const res = await fetch(`${API_BASE_URL}/chat/getAllMeetings`, { credentials: 'include' });
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
                    reportDiv.innerHTML = `<strong>Final Report:</strong><br><br>${meeting.final_report.replace(/\n/g, '<br>')}`;
                    
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
    // 4. Load Chat History (Personal)
    async function loadChatHistory() {
        try {
            const chatHistoryList = document.getElementById('chat-history-list');
            const res = await fetch(`${API_BASE_URL}/chat/getChats`, { credentials: 'include' });
            if (!res.ok) return;
            const data = await res.json();
            
            // Clear existing history
            chatHistoryList.innerHTML = '';

            data.chats.forEach(chat => {
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
                    loadOldChat(chat.chat_id, chat.chat_title);
                });
                chatHistoryList.appendChild(item);
            });
        } catch (err) {
            console.error("Failed to load chats:", err);
        }
    }

    // 4b. Load Meeting History (Shared)
    async function loadAllMeetings() {
        try {
            const meetingList = document.getElementById('meeting-list');
            const res = await fetch(`${API_BASE_URL}/chat/getAllMeetings`, { credentials: 'include' });
            if (!res.ok) return;
            const data = await res.json();
            
            meetingList.innerHTML = '';

            data.meetings.forEach(meeting => {
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
                    loadMeetingOnly(meeting.meeting_id, meeting.meeting_title);
                });
                meetingList.appendChild(item);
            });
        } catch (err) {
            console.error("Failed to load meetings:", err);
        }
    }

    // 5b. Load ONLY Meeting Report (Clean View)
    async function loadMeetingOnly(meetingId, title) {
        currentChatTitle = null; // Exit chat mode
        
        // Highlight in sidebar using the title text
        document.querySelectorAll('.history-item').forEach(i => {
            if (i.innerText.trim() === title) i.classList.add('active');
            else i.classList.remove('active');
        });

        chatMessages.innerHTML = '<div class="typing-indicator" style="margin: auto;"></div>';

        try {
            const res = await fetch(`${API_BASE_URL}/chat/getMeetingContent/${meetingId}`, { credentials: 'include' });
            if (!res.ok) throw new Error("Failed to fetch meeting");
            const data = await res.json();

            chatMessages.innerHTML = ''; 
            const content = data.meeting_content;
            if (content && content.final_report) {
                const reportDiv = document.createElement('div');
                reportDiv.className = 'message ai';
                reportDiv.innerHTML = `
                    <div class="avatar" style="background: var(--accent-gradient); color: white; font-size: 0.8rem; font-weight: bold;">AI</div>
                    <div class="message-box" style="width: 100%; max-width: 650px; border: 1px solid rgba(255, 255, 255, 0.1);">
                        <div class="message-content" style="padding: 10px;">
                            <strong>Meeting Analysis Report:</strong><br><br>
                            ${content.final_report.replace(/\n/g, '<br>')}
                        </div>
                    </div>
                `;
                chatMessages.appendChild(reportDiv);
                currentMeetingId = content.meeting_id;
            } else {
                chatMessages.innerHTML = '<p style="text-align:center; color: var(--text-secondary); margin-top: 2rem;">No report content available for this meeting.</p>';
            }
        } catch (err) {
            console.error(err);
            chatMessages.innerHTML = '<p style="text-align:center; color: #f87171; margin-top: 2rem;">Error loading meeting report.</p>';
        }
    }

    // 5. Load Specific Chat Messages
    async function loadOldChat(chatId, title) {
        currentChatTitle = title; 
        currentChatId = chatId;
        
        // Highlight in sidebar
        document.querySelectorAll('.history-item').forEach(i => {
            if (i.innerText.trim() === title) i.classList.add('active');
            else i.classList.remove('active');
        });

        chatMessages.innerHTML = '';

        chatMessages.innerHTML = `
            <div style="height: 100%; display: flex; align-items: center; justify-content: center;">
                <div class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>`;

        try {
            const res = await fetch(`${API_BASE_URL}/chat/getOldChat/${chatId}`, { credentials: 'include' });
            if (!res.ok) throw new Error("Failed to fetch messages");
            const data = await res.json();

            chatMessages.innerHTML = ''; // Clear indicator

            // Render the Meeting Report at the top so user has context
            if (data.final_report) {
                const reportDiv = document.createElement('div');
                reportDiv.className = 'message ai';
                reportDiv.innerHTML = `
                    <div class="avatar" style="background: var(--accent-gradient); color: white; font-size: 0.8rem; font-weight: bold;">AI</div>
                    <div class="message-box" style="width: 100%; max-width: 650px; border: 1px solid rgba(255, 255, 255, 0.1);">
                        <div class="message-content" style="padding: 10px;">
                            <strong>Meeting Analysis Report:</strong><br><br>
                            ${data.final_report.replace(/\n/g, '<br>')}
                        </div>
                    </div>
                    <div style="width: 100%; height: 1px; background: rgba(255, 255, 255, 0.05); margin: 20px 0;"></div>
                `;
                chatMessages.appendChild(reportDiv);
            }

            data.chat.forEach(msg => {
                renderMessage(msg.type.toLowerCase(), msg.message);
            });
            currentMeetingId = data.meeting_id;
            chatMessages.scrollTop = chatMessages.scrollHeight;
        } catch (err) {
            console.error(err);
            chatMessages.innerHTML = '<p style="text-align:center; color: #f87171; margin-top: 2rem;">Error loading messages.</p>';
        }
    }

    // 6. Helper to render messages
    function renderMessage(role, text) {
        const chatMessages = document.getElementById('chat-messages');
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${role === 'ai' ? 'ai' : 'user'}`;
        
        const avatarColor = role === 'ai' ? 'var(--accent-gradient)' : 'rgba(255, 255, 255, 0.1)';
        const initials = role === 'ai' ? 'AI' : document.getElementById('avatar-initials').innerText;

        msgDiv.innerHTML = `
            <div class="avatar" style="background: ${avatarColor}; color: white; font-size: 0.8rem; font-weight: bold;">${initials}</div>
            <div class="message-box">
                <div class="message-content">${text}</div>
            </div>
        `;
        chatMessages.appendChild(msgDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
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

    // Handle initial state and recovery
    await loadChatHistory();
    await loadAllMeetings();
    recoverPendingUpload();

    // Restore last viewed item
    const lastType = localStorage.getItem('last_viewed_type');
    const lastTitle = localStorage.getItem('last_viewed_title');
    const lastMeetingId = localStorage.getItem('last_viewed_meeting_id');
    const lastChatId = localStorage.getItem('last_viewed_chat_id');

    if (lastType === 'chat' && lastChatId && lastTitle) {
        loadOldChat(lastChatId, lastTitle);
    } else if (lastType === 'meeting' && lastMeetingId && lastTitle) {
        loadMeetingOnly(lastMeetingId, lastTitle);
    } else {
        // If the session is from the old code and missing an ID, start fresh
        localStorage.removeItem('last_viewed_type');
        localStorage.removeItem('last_viewed_title');
        localStorage.removeItem('last_viewed_meeting_id');
        localStorage.removeItem('last_viewed_chat_id');
    }

    // 7. Send Message Handler
    async function sendMessage() {
        const text = chatInput.value.trim();
        if (!text) return;

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
            const url = currentChatId 
                ? `${API_BASE_URL}/chat/oldChat/${currentChatId}`
                : `${API_BASE_URL}/chat/newChat`;
            
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
                            loadChatHistory();
                        }

                        // If it's a token, append it to the message div
                        if (parsed.token) {
                            fullText += parsed.token;
                            contentDiv.innerText = fullText;
                            chatMessages.scrollTop = chatMessages.scrollHeight;
                        }
                    } catch (e) {
                        // Ignore malformed SSE lines
                    }
                }
            }

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
    document.getElementById('open-upload-modal-btn').addEventListener('click', () => {
        uploadModal.style.display = 'flex';
    });
    document.getElementById('close-modal-btn').addEventListener('click', () => {
        uploadModal.style.display = 'none';
        document.getElementById('chat-upload-form').reset();
    });

    // 10. Process Audio Upload inside Chat page
    document.getElementById('chat-upload-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const isDepartmentWide = document.querySelector('input[name="is_department_wide"]:checked').value === 'true';
        const fileInput = document.getElementById('chat-meeting-audio');
        if (!fileInput.files.length) return;
        const file = fileInput.files[0];
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
            
            const data = await res.json();

            // SUCCESS! Since backend is synchronous, we have the result now
            clearInterval(activeTimerInterval);
            
            const reportDiv = containerElement.closest('.message-box').querySelector('.message-content');
            
            addThoughtStep(stepsElement, "<strong>Synthesis Complete.</strong>");
            containerElement.removeAttribute('open');
            
            iconElement.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>`;
            titleElement.innerText = "Synthesized Meeting";
            
            reportDiv.style.display = 'block';
            reportDiv.innerHTML = `<strong>Final Report:</strong><br><br>${data.final_report.replace(/\n/g, '<br>')}`;
            
            currentMeetingId = data.meeting_id;
            clearActiveProcess();
            loadChatHistory();
            loadAllMeetings();
            chatMessages.scrollTop = chatMessages.scrollHeight;

        } catch (error) {
            console.error('File upload failed:', error);
            clearInterval(activeTimerInterval);
            addThoughtStep(stepsElement, `<span style="color: #ef4444">Error: ${error.message}</span>`);
            titleElement.innerText = "Process Failed";
            iconElement.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`;
            showToast(error.message, 'error');
        }
    });

});
