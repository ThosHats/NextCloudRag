document.addEventListener('DOMContentLoaded', () => {
    const chatContainer = document.getElementById('chat-container');
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');

    // Auto-resize textarea
    userInput.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        if (this.value.trim().length > 0) {
            sendBtn.removeAttribute('disabled');
        } else {
            sendBtn.setAttribute('disabled', 'true');
        }
    });

    // Handle Enter key
    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!sendBtn.disabled) {
                sendMessage();
            }
        }
    });

    sendBtn.addEventListener('click', sendMessage);

    async function sendMessage() {
        const query = userInput.value.trim();
        if (!query) return;

        // UI Reset
        userInput.value = '';
        userInput.style.height = 'auto';
        sendBtn.setAttribute('disabled', 'true');

        // Remove welcome message if exists
        const welcome = document.querySelector('.welcome-message');
        if (welcome) welcome.remove();

        // Add User Message
        appendMessage('user', query);

        // Add Loading Indicator
        const loadingId = appendLoading();

        try {
            // API Call
            const response = await fetch('/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    // Optional: Add Authorization header if OIDC is enabled later
                    // 'Authorization': 'Bearer ' + token 
                },
                body: JSON.stringify({
                    query: query,
                    top_k: 5
                })
            });

            if (!response.ok) {
                throw new Error(`API Error: ${response.statusText}`);
            }

            const data = await response.json();

            // Remove Loading
            removeMessage(loadingId);

            // Add AI Response
            appendMessage('ai', data.answer, data.sources);

        } catch (error) {
            removeMessage(loadingId);
            appendMessage('ai', `⚠️ Sorry, something went wrong: ${error.message}`);
        }
    }

    function appendMessage(role, text, sources = []) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${role}`;

        let contentHtml = `<div class="message-bubble">${formatText(text)}</div>`;

        if (sources && sources.length > 0) {
            contentHtml += `<div class="sources-container">`;
            sources.forEach(source => {
                // Determine Nextcloud Link
                // Assuming Nextcloud URL is accessible via a global var or relative if proxy matches
                // For now, we link to the file path. Adjust domain as needed.
                const ncBase = 'https://cloud.qvibe.eu'; // Hardcoded for this setup, or dynamic?
                // Ideally, backend should return full web_url, or we construct it.
                // Nextcloud file link format: /index.php/f/{fileId} is best if we have ID.
                // If we only have path: /remote.php/webdav/{path} or /index.php/apps/files?dir={dir}&openfile={filename}

                // Constructing a "Files" app link:
                const pathParts = source.nc_path.split('/');
                const filename = pathParts.pop(); // remove filename
                const dir = pathParts.join('/');

                // Simplification: just show path for now if no ID available
                const link = `${ncBase}/apps/files/?dir=${encodeURIComponent(dir)}&openfile=${encodeURIComponent(filename)}`; // This is a guess, might need file ID for robust linking

                contentHtml += `
                    <a href="${link}" target="_blank" class="source-chip" title="Score: ${source.score.toFixed(2)}">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                            <polyline points="14 2 14 8 20 8"></polyline>
                        </svg>
                        ${source.title}
                    </a>
                `;
            });
            contentHtml += `</div>`;
        }

        msgDiv.innerHTML = contentHtml;
        chatContainer.appendChild(msgDiv);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function appendLoading() {
        const id = 'loading-' + Date.now();
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message ai';
        msgDiv.id = id;
        msgDiv.innerHTML = `
            <div class="message-bubble">
                <div class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
        `;
        chatContainer.appendChild(msgDiv);
        chatContainer.scrollTop = chatContainer.scrollHeight;
        return id;
    }

    function removeMessage(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    function formatText(text) {
        // Simple Markdown-like formatting
        // Escape HTML
        let safeText = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

        // Bold **text**
        safeText = safeText.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

        // Newlines to <br>
        safeText = safeText.replace(/\n/g, '<br>');

        return safeText;
    }
});
