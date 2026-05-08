const API_BASE_URL = '/api';

const STAGE_CONFIG = {
    transcription:  { icon: '🔊', label: 'Transcribing audio...' },
    summary:        { icon: '📝', label: 'Generating summary...' },
    action_items:   { icon: '✅', label: 'Extracting action items...' },
    key_decisions:  { icon: '🔑', label: 'Identifying key decisions...' },
    formatting:     { icon: '📋', label: 'Formatting report...' },
    saving:         { icon: '💾', label: 'Saving to workspace...' }
};

document.getElementById('upload-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const fileInput = document.getElementById('audio-file');
    const isDepartmentWide = document.querySelector('input[name="is_department_wide"]:checked').value === 'true';
    const statusMessage = document.getElementById('status-message');
    
    if (!fileInput.files.length) {
        if (statusMessage) statusMessage.innerText = "Please select an audio file.";
        return;
    }

    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append("file", file);
    formData.append("is_department_wide", isDepartmentWide);

    // Build the progress stages HTML
    const stagesHTML = Object.entries(STAGE_CONFIG).map(([key, config]) => `
        <div class="stage-row" id="stage-${key}" style="display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-radius: 10px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05); transition: all 0.4s ease;">
            <span class="stage-icon" style="font-size: 1.3rem; min-width: 28px; text-align: center;">${config.icon}</span>
            <span class="stage-label" style="flex: 1; color: var(--text-secondary); font-size: 0.95rem; font-weight: 500;">${config.label}</span>
            <span class="stage-status" style="font-size: 0.85rem; color: var(--text-secondary); min-width: 24px; text-align: center;">⬚</span>
        </div>
    `).join('');

    // Replace UI with the streaming progress layout
    document.body.innerHTML = `
        <div class="app-container">
            <aside class="sidebar" style="pointer-events: none; opacity: 0.6;">
                <div class="sidebar-header">
                    <div class="logo" style="margin-bottom: 2rem; justify-content: center; display: flex; color: white;">
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
                            <polyline points="2 17 12 22 22 17"></polyline>
                            <polyline points="2 12 12 17 22 12"></polyline>
                        </svg>
                    </div>
                </div>
                <div style="padding: 1rem; color: var(--text-secondary); text-align: center; font-size: 0.85rem; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">
                    Workspace Preparing...
                </div>
            </aside>
            <main class="main-chat" style="display: flex; flex-direction: column; align-items: center; justify-content: center; background: var(--bg-main);">
                <svg width="60" height="60" viewBox="0 0 100 100" class="claude-icon" style="margin-bottom: 1.5rem;">
                     <rect x="20" y="20" width="25" height="25" rx="6" fill="#a855f7" class="block1" />
                     <rect x="55" y="20" width="25" height="25" rx="6" fill="#ec4899" class="block2" />
                     <rect x="20" y="55" width="25" height="25" rx="6" fill="#6366f1" class="block3" />
                     <rect x="55" y="55" width="25" height="25" rx="6" fill="#3b82f6" class="block4" />
                </svg>
                <h2 style="color: var(--text-primary); font-size: 1.5rem; font-weight: 600; letter-spacing: 0.5px; text-align: center; margin-bottom: 0.5rem;">Processing Meeting</h2>
                <p style="color: var(--text-secondary); font-size: 0.9rem; margin-bottom: 2rem; text-align: center;">AI pipeline is analyzing your audio in real-time</p>
                <div id="progress-stages" style="display: flex; flex-direction: column; gap: 8px; width: 100%; max-width: 420px;">
                    ${stagesHTML}
                </div>
                <div id="completion-msg" style="display: none; margin-top: 2rem; text-align: center;"></div>
            </main>
        </div>
        <style>
            .claude-icon {
                animation: pulse-container 2.5s infinite ease-in-out;
            }
            .block1 { transform-origin: center; animation: slide1 1.2s infinite alternate cubic-bezier(0.4, 0, 0.2, 1); }
            .block2 { transform-origin: center; animation: slide2 1.2s infinite alternate cubic-bezier(0.4, 0, 0.2, 1); animation-delay: 0.3s; }
            .block3 { transform-origin: center; animation: slide3 1.2s infinite alternate cubic-bezier(0.4, 0, 0.2, 1); animation-delay: 0.6s; }
            .block4 { transform-origin: center; animation: slide4 1.2s infinite alternate cubic-bezier(0.4, 0, 0.2, 1); animation-delay: 0.9s; }

            @keyframes pulse-container {
                0% { transform: scale(0.95); filter: drop-shadow(0 0 15px rgba(168,85,247,0.2)); }
                50% { transform: scale(1.05); filter: drop-shadow(0 0 25px rgba(168,85,247,0.6)); }
                100% { transform: scale(0.95); filter: drop-shadow(0 0 15px rgba(168,85,247,0.2)); }
            }
            @keyframes slide1 { 0% { transform: translate(0, 0) scale(1); border-radius: 6px; } 100% { transform: translate(12px, 12px) scale(0.85); border-radius: 12px; } }
            @keyframes slide2 { 0% { transform: translate(0, 0) scale(1); border-radius: 6px; } 100% { transform: translate(-12px, 12px) scale(0.85); border-radius: 12px; } }
            @keyframes slide3 { 0% { transform: translate(0, 0) scale(1); border-radius: 6px; } 100% { transform: translate(12px, -12px) scale(0.85); border-radius: 12px; } }
            @keyframes slide4 { 0% { transform: translate(0, 0) scale(1); border-radius: 6px; } 100% { transform: translate(-12px, -12px) scale(0.85); border-radius: 12px; } }
            
            .stage-active {
                background: rgba(168, 85, 247, 0.1) !important;
                border-color: rgba(168, 85, 247, 0.3) !important;
            }
            .stage-done {
                background: rgba(16, 185, 129, 0.08) !important;
                border-color: rgba(16, 185, 129, 0.2) !important;
            }
            
            @keyframes spin-status {
                100% { transform: rotate(360deg); }
            }
        </style>
    `;

    try {
        const res = await fetch(`${API_BASE_URL}/chat/fileUpload`, {
            method: 'POST',
            credentials: 'include',
            body: formData
        });

        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.detail || "Upload failed");
        }

        // Read the SSE stream
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
                const payload = line.slice(6).trim();
                
                if (payload === '[DONE]') continue;

                try {
                    const event = JSON.parse(payload);
                    handleStageEvent(event);
                } catch (e) {
                    // Skip unparseable events
                }
            }
        }

    } catch (err) {
        console.error(err);
        const completionMsg = document.getElementById('completion-msg') || document.body;
        completionMsg.style.display = 'block';
        completionMsg.innerHTML = `
            <h2 style="color: #ef4444; font-size: 1.4rem; font-weight: 600;">Processing Error</h2>
            <p style="color: var(--text-secondary); margin-top: 0.5rem; font-size: 0.95rem;">${err.message || "An error occurred during processing."}</p>
            <button onclick="window.location.reload()" class="btn-primary" style="margin-top: 1.5rem; padding: 0.75rem 1.5rem;">Try Again</button>
        `;
    }
});

function handleStageEvent(event) {
    const { stage, status } = event;

    if (stage === 'saved') {
        // Final event — redirect to chat
        sessionStorage.setItem('newlyCreatedMeetingId', event.meeting_id);
        
        // Stop the loading animation
        const icon = document.querySelector('.claude-icon');
        if (icon) icon.style.animation = 'none';

        const completionMsg = document.getElementById('completion-msg');
        if (completionMsg) {
            completionMsg.style.display = 'block';
            completionMsg.innerHTML = `
                <h2 style="color: #10b981; font-size: 1.4rem; font-weight: 600;">✓ Workspace Ready!</h2>
                <p style="color: var(--text-secondary); margin-top: 0.5rem; font-size: 0.95rem;">Redirecting to your chat...</p>
            `;
        }
        setTimeout(() => {
            window.location.replace('chat.html');
        }, 1000);
        return;
    }

    if (stage === 'complete') return; // Internal event, skip UI update

    const stageEl = document.getElementById(`stage-${stage}`);
    if (!stageEl) return;

    const statusEl = stageEl.querySelector('.stage-status');
    const labelEl = stageEl.querySelector('.stage-label');

    if (status === 'in_progress') {
        stageEl.classList.add('stage-active');
        stageEl.classList.remove('stage-done');
        if (statusEl) statusEl.innerHTML = '<span style="display:inline-block; animation: spin-status 1s linear infinite;">⏳</span>';
        if (labelEl) labelEl.style.color = 'var(--text-primary)';
    } else if (status === 'done') {
        stageEl.classList.remove('stage-active');
        stageEl.classList.add('stage-done');
        if (statusEl) statusEl.textContent = '✅';
        if (labelEl) labelEl.style.color = '#10b981';
    }
}
