// ============================================
// YoBotz Chat Widget Scripts
// ============================================

let isChatOpen = false;
let unreadCount = 0;
let lastMessageTime = 0;

const chatWindow = document.getElementById('chatWindow');
const chatToggle = document.getElementById('chatToggle');
const chatMessages = document.getElementById('chatMessages');
const chatInput = document.getElementById('chatInput');
const chatSend = document.getElementById('chatSend');
const chatBadge = document.getElementById('chatBadge');
const quickReplies = document.getElementById('quickReplies');

function toggleChat() {
    isChatOpen = !isChatOpen;
    chatWindow.classList.toggle('open', isChatOpen);
    chatToggle.classList.toggle('active', isChatOpen);

    if (isChatOpen) {
        chatInput.focus();
        clearUnread();
    }
}

function handleKeyPress(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

function getTimeString() {
    const now = new Date();
    return now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function addMessage(text, isUser = false) {
    const welcome = document.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    const msg = document.createElement('div');
    msg.className = 'message ' + (isUser ? 'user' : 'bot');
    msg.innerHTML = `
        <span class="message-content">${text}</span>
        <span class="message-time">${getTimeString()}</span>
    `;
    chatMessages.appendChild(msg);
    scrollToBottom();

    // Play sound for bot messages
    if (!isUser) {
        playNotificationSound();
    }
}

function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function showTyping() {
    const typing = document.createElement('div');
    typing.className = 'message bot typing';
    typing.id = 'typingIndicator';
    typing.innerHTML = '<span></span><span></span><span></span>';
    chatMessages.appendChild(typing);
    scrollToBottom();
}

function hideTyping() {
    const typing = document.getElementById('typingIndicator');
    if (typing) typing.remove();
}

function playNotificationSound() {
    try {
        // Create a simple beep using Web Audio API
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioContext.createOscillator();
        const gainNode = audioContext.createGain();
        
        oscillator.connect(gainNode);
        gainNode.connect(audioContext.destination);
        
        oscillator.frequency.value = 800;
        oscillator.type = 'sine';
        gainNode.gain.value = 0.1;
        
        oscillator.start();
        oscillator.stop(audioContext.currentTime + 0.1);
    } catch (e) {
        // Fallback: silent if audio not supported
    }
}

function showUnread() {
    if (!isChatOpen) {
        unreadCount++;
        chatBadge.textContent = unreadCount;
        chatBadge.classList.add('show');
        
        // Pulse animation on the toggle
        chatToggle.style.animation = 'none';
        chatToggle.offsetHeight; // Trigger reflow
        chatToggle.style.animation = 'badgePulse 2s infinite';
    }
}

function clearUnread() {
    unreadCount = 0;
    chatBadge.classList.remove('show');
}

async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text) return;

    chatInput.value = '';
    chatSend.disabled = true;

    // Hide quick replies after first message
    if (quickReplies) {
        quickReplies.style.display = 'none';
    }

    addMessage(text, true);
    showTyping();

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
        });

        if (response.ok) {
            const data = await response.json();
            hideTyping();
            addMessage(data.reply || "Thanks! We'll get back to you soon.");
        } else {
            throw new Error('API not available');
        }
    } catch (error) {
        hideTyping();
        // Smart demo responses
        const demoResponse = getDemoResponse(text);
        addMessage(demoResponse);
    }

    chatSend.disabled = false;
    chatInput.focus();
}

function sendQuickReply(text) {
    chatInput.value = text;
    sendMessage();
}

function clearChat() {
    chatMessages.innerHTML = `
        <div class="chat-welcome">
            <div class="chat-welcome-icon">👋</div>
            <h4>Welcome to YoBotz!</h4>
            <p>How can I help you today?</p>
            <p class="chat-welcome-hint">Try clicking a quick reply below 👇</p>
        </div>
    `;
    if (quickReplies) {
        quickReplies.style.display = 'flex';
    }
}

function getDemoResponse(input) {
    const lower = input.toLowerCase();
    
    if (lower.includes('start') || lower.includes('get started') || lower.includes('begin')) {
        return "Great! Click the 'Start Free Trial' button to begin. It takes just 5 minutes to set up your business bot! 🚀";
    }
    if (lower.includes('pricing') || lower.includes('cost') || lower.includes('price') || lower.includes('plan')) {
        return "We have two plans:\n• Starter: $25/month (basic FAQ bot)\n• Business: $80/month (full ordering, booking)\n\nWhich one interests you?";
    }
    if (lower.includes('help') || lower.includes('setup') || lower.includes('how')) {
        return "I can help you with:\n• Setting up your business bot\n• Choosing the right features\n• Understanding our pricing\n\nWhat would you like to know more about?";
    }
    if (lower.includes('order') || lower.includes('reservation')) {
        return "Our Reservation Mode is perfect for bakeries, cafes, and shops serving customers offline. It lets customers book time slots and pay in-person! 📅";
    }
    if (lower.includes('telegram')) {
        return "YoBotz works on Telegram! Just connect your bot token during setup. 📱";
    }
    
    return "Thanks for your interest in YoBotz! Visit /setup to start your free trial, or check our pricing above. I'm here to help! 😊";
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Auto-show unread after 10 seconds (demo)
    setTimeout(() => {
        if (!isChatOpen && unreadCount === 0) {
            showUnread();
        }
    }, 10000);
});
