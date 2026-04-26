const API_BASE_URL = '/api';

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

    // Immediately replace the UI with a beautiful "Chat Processing" layout
    // This allows the user to feel they've entered the workspace while waiting.
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
                <svg width="80" height="80" viewBox="0 0 100 100" class="claude-icon">
                     <rect x="20" y="20" width="25" height="25" rx="6" fill="#a855f7" class="block1" />
                     <rect x="55" y="20" width="25" height="25" rx="6" fill="#ec4899" class="block2" />
                     <rect x="20" y="55" width="25" height="25" rx="6" fill="#6366f1" class="block3" />
                     <rect x="55" y="55" width="25" height="25" rx="6" fill="#3b82f6" class="block4" />
                </svg>
                <div id="processing-msg">
                    <h2 style="color: var(--text-primary); margin-top: 2.5rem; font-size: 1.6rem; font-weight: 600; letter-spacing: 0.5px; text-align: center;">Synthesizing Meeting...</h2>
                    <p style="color: var(--text-secondary); max-width: 420px; text-align: center; margin-top: 1rem; line-height: 1.6; font-size: 1.05rem;">We are securely analyzing the audio and generating your departmental summary. This usually takes just a moment.</p>
                </div>
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

        const result = await res.json();
        
        // Success! Redirect the user straight into the specific chat workspace
        document.getElementById('processing-msg').innerHTML = `
            <h2 style="color: #10b981; margin-top: 2.5rem; font-size: 1.6rem; font-weight: 600; text-align: center;">✓ Workspace Ready!</h2>
            <p style="color: var(--text-secondary); max-width: 420px; text-align: center; margin-top: 1rem; line-height: 1.6; font-size: 1.05rem;">Redirecting to your chat...</p>
        `;
        
        setTimeout(() => {
            // Once the chat logic is ready we go to the chat and flag auto-load (optional)
            // Storing slightly as session state if we wanted to auto-open it
            sessionStorage.setItem('newlyCreatedMeetingId', result.meeting_id);
            window.location.replace('chat.html');
        }, 1000);

    } catch (err) {
        console.error(err);
        document.getElementById('processing-msg').innerHTML = `
            <h2 style="color: #ef4444; margin-top: 2.5rem; font-size: 1.6rem; font-weight: 600; text-align: center;">Processing Error</h2>
            <p style="color: var(--text-secondary); max-width: 420px; text-align: center; margin-top: 1rem; line-height: 1.6; font-size: 1.05rem;">${err.message || "An error occurred during processing."}</p>
            <button onclick="window.location.reload()" class="btn-primary" style="margin-top: 1.5rem; padding: 0.75rem 1.5rem;">Try Again</button>
        `;
    }
});
