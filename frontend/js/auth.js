const API_BASE_URL = '/api/user'; // Dynamically uses current host to prevent cookie drop failures

function hasAuthToken() {
    return document.cookie.split(';').some(c => c.trim().startsWith('access_token='));
}

if (localStorage.getItem('isAuthenticated') === 'true' && !hasAuthToken()) {
    localStorage.removeItem('isAuthenticated');
}

// Check for existing login flag on page load
// REMOVED: Auto-redirect to chat.html. Users must explicitly select a workspace on index.html.

document.addEventListener('DOMContentLoaded', () => {
    
    // Check which form exists
    const loginForm = document.getElementById('login-form');
    const signupForm = document.getElementById('signup-form');
    const errorMessage = document.getElementById('error-message');
    const successMessage = document.getElementById('success-message');

    // Link preservation: Ensure 'mode' is passed between login/signup pages
    const urlParams = new URLSearchParams(window.location.search);
    const currentMode = urlParams.get('mode');
    if (currentMode) {
        const authLinks = document.querySelectorAll('.auth-footer a, .nav-links a');
        authLinks.forEach(link => {
            const href = link.getAttribute('href');
            if (href && (href.includes('login.html') || href.includes('signup.html'))) {
                const separator = href.includes('?') ? '&' : '?';
                link.setAttribute('href', `${href}${separator}mode=${currentMode}`);
            }
        });
    }

    function showError(msg) {
        if (!errorMessage) return;
        errorMessage.innerText = msg;
        errorMessage.style.display = 'block';
        if(successMessage) successMessage.style.display = 'none';
    }

    function showSuccess(msg) {
        if (!successMessage) return;
        successMessage.innerText = msg;
        successMessage.style.display = 'block';
        if(errorMessage) errorMessage.style.display = 'none';
    }

    // Handles User Signup
    if (signupForm) {
        signupForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const name = document.getElementById('name').value;
            const email = document.getElementById('email').value;
            const dept = parseInt(document.getElementById('dept').value);
            const team_id = parseInt(document.getElementById('team_id').value);
            
            const signupBtn = signupForm.querySelector('button');
            signupBtn.innerHTML = 'Signing Up...';
            signupBtn.disabled = true;

            try {
                const res = await fetch(`${API_BASE_URL}/signup`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({ name, email, dept, team_id })
                });
                
                const data = await res.json();
                
                if (res.ok) {
                    // Automatically log in the user
                    const loginRes = await fetch(`${API_BASE_URL}/login`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'include',
                        body: JSON.stringify({ email, dept })
                    });
                    
                    if (loginRes.ok) {
                        localStorage.setItem('isAuthenticated', 'true');
                        localStorage.setItem('userName', name);
                        showSuccess("Account created! Logging you in...");
                        setTimeout(() => {
                            const mode = urlParams.get('mode');
                            // If no mode, go to index.html to select one
                            const redirectUrl = mode ? `chat.html?mode=${mode}` : '../index.html';
                            window.location.replace(redirectUrl);
                        }, 500);
                    } else {
                        showError("Account created, but automatic login failed. Please log in.");
                    }
                } else {
                    showError(data.detail || 'Signup failed. Please try again.');
                }
            } catch (err) {
                showError('Could not connect to the server. Is it running?');
            } finally {
                signupBtn.innerHTML = 'Sign Up';
                signupBtn.disabled = false;
            }
        });
    }

    // Handles User Login
    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const email = document.getElementById('email').value;
            const dept = parseInt(document.getElementById('dept').value);
            
            const loginBtn = loginForm.querySelector('button');
            loginBtn.innerHTML = 'Logging In...';
            loginBtn.disabled = true;

            try {
                const res = await fetch(`${API_BASE_URL}/login`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({ email, dept })
                });
                
                const data = await res.json();
                
                if (res.ok) {
                    localStorage.setItem('isAuthenticated', 'true');
                    if (data.name) localStorage.setItem('userName', data.name);
                    loginBtn.innerHTML = 'Success!';
                    setTimeout(() => {
                        const mode = urlParams.get('mode');
                        // If no mode, go to index.html to select one
                        const redirectUrl = mode ? `chat.html?mode=${mode}` : '../index.html';
                        window.location.replace(redirectUrl);
                    }, 500);
                } else {
                    showError(data.detail || 'Login failed. Please check credentials.');
                }
            } catch (err) {
                showError('Could not connect to the server. Is it running?');
            } finally {
                if(loginBtn && loginBtn.innerHTML !== 'Success!') {
                    loginBtn.innerHTML = 'Log In';
                    loginBtn.disabled = false;
                }
            }
        });
    }

});
