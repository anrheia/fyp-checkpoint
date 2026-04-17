function initScheduleChat({ messagesId, inputId, sendBtnId, apiUrl, counterId = null, chatUsed = 0, chatLimit = 30 }) {
    const msgs = document.getElementById(messagesId);
    const input = document.getElementById(inputId);
    const sendBtn = document.getElementById(sendBtnId);
    const counter = counterId ? document.getElementById(counterId) : null;
    const typingId = messagesId + '-typing';
    let used = chatUsed;

    function getCsrf() {
        return document.cookie.split('; ').find(r => r.startsWith('csrftoken='))?.split('=')[1] || '';
    }

    function updateCounter(newUsed) {
        used = newUsed;
        if (!counter) return;
        const remaining = Math.max(0, chatLimit - used);
        counter.textContent = remaining + ' left today';
        const ratio = used / chatLimit;
        counter.style.color = ratio >= 1
            ? 'oklch(45% 0.18 25)'
            : ratio >= 0.8
                ? 'oklch(50% 0.12 70)'
                : 'oklch(55% 0.04 195)';
    }

    function disableInput() {
        input.disabled = true;
        input.placeholder = 'Daily limit reached. Check back tomorrow.';
        sendBtn.disabled = true;
        sendBtn.style.opacity = '0.4';
        sendBtn.style.cursor = 'not-allowed';
    }

    function appendMessage(role, text) {
        const isUser = role === 'user';
        const wrapper = document.createElement('div');
        wrapper.style.cssText = `display: flex; gap: 0.6rem; align-items: flex-start; ${isUser ? 'flex-direction: row-reverse;' : ''}`;

        const avatar = document.createElement('div');
        avatar.style.cssText = `width: 1.6rem; height: 1.6rem; border-radius: 9999px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; font-size: 0.65rem; font-weight: 600; background: oklch(62% 0.17 265 / 0.12); border: 1px solid oklch(62% 0.17 265 / 0.2); color: oklch(38% 0.12 265);`;
        avatar.textContent = isUser ? 'You' : '✦';

        const bubble = document.createElement('div');
        bubble.style.cssText = `border: 1px solid oklch(0% 0 0 / 0.06); padding: 0.5rem 0.75rem; max-width: 85%; ${isUser ? 'background: oklch(62% 0.17 265 / 0.08); border-radius: 0.75rem 0 0.75rem 0.75rem;' : 'background: oklch(97% 0.01 195 / 0.8); border-radius: 0 0.75rem 0.75rem 0.75rem;'}`;

        const p = document.createElement('p');
        p.style.cssText = 'font-size: 0.8rem; color: oklch(35% 0.04 195); margin: 0; line-height: 1.55; white-space: pre-wrap;';
        p.textContent = text;

        bubble.appendChild(p);
        wrapper.appendChild(avatar);
        wrapper.appendChild(bubble);
        msgs.appendChild(wrapper);
        msgs.scrollTop = msgs.scrollHeight;
    }

    function appendTyping() {
        const wrapper = document.createElement('div');
        wrapper.id = typingId;
        wrapper.style.cssText = 'display: flex; gap: 0.6rem; align-items: flex-start;';
        wrapper.innerHTML = `
            <div style="width:1.6rem;height:1.6rem;border-radius:9999px;background:oklch(62% 0.17 265/0.15);border:1px solid oklch(62% 0.17 265/0.25);display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:0.7rem;">✦</div>
            <div style="background:oklch(97% 0.01 195/0.8);border:1px solid oklch(0% 0 0/0.06);border-radius:0 0.75rem 0.75rem 0.75rem;padding:0.5rem 0.75rem;">
                <span style="display:inline-flex;gap:0.3rem;align-items:center;">
                    <span style="width:0.35rem;height:0.35rem;border-radius:50%;background:oklch(55% 0.04 195);animation:chat-bounce 1s infinite 0s;display:inline-block;"></span>
                    <span style="width:0.35rem;height:0.35rem;border-radius:50%;background:oklch(55% 0.04 195);animation:chat-bounce 1s infinite 0.2s;display:inline-block;"></span>
                    <span style="width:0.35rem;height:0.35rem;border-radius:50%;background:oklch(55% 0.04 195);animation:chat-bounce 1s infinite 0.4s;display:inline-block;"></span>
                </span>
            </div>`;
        msgs.appendChild(wrapper);
        msgs.scrollTop = msgs.scrollHeight;
    }

    async function sendMessage() {
        const text = input.value.trim();
        if (!text) return;
        input.value = '';
        input.disabled = true;
        sendBtn.disabled = true;
        appendMessage('user', text);
        appendTyping();
        try {
            const res = await fetch(apiUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': getCsrf() },
                body: new URLSearchParams({ message: text, csrfmiddlewaretoken: getCsrf() }),
            });
            const data = await res.json();
            document.getElementById(typingId)?.remove();
            appendMessage('bot', data.answer || 'Something went wrong.');
            if (!data.limit_reached) updateCounter(used + 1);
        } catch {
            document.getElementById(typingId)?.remove();
            appendMessage('bot', 'Error contacting server.');
        } finally {
            input.disabled = false;
            sendBtn.disabled = false;
            sendBtn.style.opacity = '';
            sendBtn.style.cursor = '';
            input.focus();
            if (used >= chatLimit) disableInput();
        }
    }

    function clearChat() {
        msgs.innerHTML = '';
        appendMessage('bot', "Chat cleared. Prompts to try:\n- Who's working Friday?\n- How many hours does John have this week?\n- Who's late right now?\n- Who's not scheduled next week?\n- Do any shifts overlap on Saturday?");
    }

    sendBtn.addEventListener('click', sendMessage);
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });

    updateCounter(used);
    if (used >= chatLimit) disableInput();

    return { clearChat };
}
