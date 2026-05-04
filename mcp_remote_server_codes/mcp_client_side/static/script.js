// ── Theme Toggle ──
const themeToggleBtn = document.getElementById('theme-toggle-btn');
const themeDropdown = document.getElementById('theme-dropdown');

function setTheme(themeName) {
  document.documentElement.setAttribute('data-theme', themeName);
  localStorage.setItem('mcp-theme', themeName);
  document.querySelectorAll('.theme-option').forEach(opt => {
    opt.classList.toggle('active', opt.dataset.theme === themeName);
  });
}

const savedTheme = localStorage.getItem('mcp-theme') || 'blue-white';
setTheme(savedTheme);

themeToggleBtn.addEventListener('click', (e) => {
  e.stopPropagation();
  themeDropdown.classList.toggle('open');
});

document.querySelectorAll('.theme-option').forEach(opt => {
  opt.addEventListener('click', () => {
    setTheme(opt.dataset.theme);
    themeDropdown.classList.remove('open');
  });
});

document.addEventListener('click', (e) => {
  if (!e.target.closest('.theme-toggle')) {
    themeDropdown.classList.remove('open');
  }
});

// ══════════════════════════════════════════════════════════════════════════════
// CONVERSATION MANAGEMENT
// ══════════════════════════════════════════════════════════════════════════════

// Storage keys
const CONVERSATIONS_KEY = 'mcp_conversations';
const CURRENT_CONV_KEY = 'current_conversation_id';

// Get all saved conversations
function getConversations() {
  const data = localStorage.getItem(CONVERSATIONS_KEY);
  return data ? JSON.parse(data) : [];
}

// Save conversations list
function saveConversations(convs) {
  localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(convs));
}

// Get current conversation ID
function getCurrentConversationId() {
  return localStorage.getItem(CURRENT_CONV_KEY);
}

// Save current conversation ID
function setCurrentConversationId(id) {
  localStorage.setItem(CURRENT_CONV_KEY, id);
}

// Generate unique ID
function generateId() {
  return 'conv_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8);
}

// Create a new conversation
function createConversation() {
  const id = generateId();
  const conv = {
    id: id,
    title: 'New conversation',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    messageCount: 0
  };

  const convs = getConversations();
  convs.unshift(conv); // Add to beginning
  saveConversations(convs);

  return conv;
}

// Update conversation title (auto-name from first message)
function updateConversationTitle(convId, title) {
  const convs = getConversations();
  const conv = convs.find(c => c.id === convId);
  if (conv) {
    // Truncate title to 40 chars
    conv.title = title.length > 40 ? title.substring(0, 40) + '...' : title;
    conv.updatedAt = new Date().toISOString();
    saveConversations(convs);
    renderConversationsList();
    updateTopbarTitle(conv.title);
  }
}

// Update conversation message count
function updateConversationMeta(convId) {
  const convs = getConversations();
  const conv = convs.find(c => c.id === convId);
  if (conv) {
    conv.messageCount = messages.length;
    conv.updatedAt = new Date().toISOString();
    saveConversations(convs);
  }
}

// Delete a conversation
function deleteConversation(convId) {
  let convs = getConversations();
  convs = convs.filter(c => c.id !== convId);
  saveConversations(convs);

  // If deleted current conversation, switch to another or create new
  if (convId === conversationId) {
    if (convs.length > 0) {
      switchToConversation(convs[0].id);
    } else {
      startNewChat();
    }
  } else {
    renderConversationsList();
  }
}

// Switch to a different conversation
function switchToConversation(convId) {
  if (convId === conversationId) return;

  // Close current WebSocket
  if (ws) ws.close();

  // Update state
  conversationId = convId;
  setCurrentConversationId(convId);
  messages = [];
  messagesContainer.innerHTML = '';

  // Update UI
  renderConversationsList();

  // Find conversation and update topbar
  const convs = getConversations();
  const conv = convs.find(c => c.id === convId);
  if (conv) {
    updateTopbarTitle(conv.title);
  }

  // Reconnect WebSocket (will load history)
  connectWebSocket();
}

// Update topbar title
function updateTopbarTitle(title) {
  const topbarTitle = document.querySelector('.topbar-title');
  if (topbarTitle) {
    topbarTitle.textContent = title;
  }
}

// Format date for display
function formatDate(dateStr) {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

// Group conversations by date
function groupConversationsByDate(convs) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  const lastWeek = new Date(today);
  lastWeek.setDate(lastWeek.getDate() - 7);

  const groups = {
    'Today': [],
    'Yesterday': [],
    'Previous 7 Days': [],
    'Older': []
  };

  convs.forEach(conv => {
    const convDate = new Date(conv.updatedAt);
    convDate.setHours(0, 0, 0, 0);

    if (convDate >= today) {
      groups['Today'].push(conv);
    } else if (convDate >= yesterday) {
      groups['Yesterday'].push(conv);
    } else if (convDate >= lastWeek) {
      groups['Previous 7 Days'].push(conv);
    } else {
      groups['Older'].push(conv);
    }
  });

  return groups;
}

// Render conversations list in sidebar
function renderConversationsList() {
  const container = document.getElementById('conversations');
  if (!container) return;

  const convs = getConversations();
  const groups = groupConversationsByDate(convs);

  let html = '';

  Object.entries(groups).forEach(([groupName, groupConvs]) => {
    if (groupConvs.length === 0) return;

    html += `<div class="conv-section-title">${groupName}</div>`;

    groupConvs.forEach(conv => {
      const isActive = conv.id === conversationId;
      html += `
        <div class="conv-item ${isActive ? 'active' : ''}" data-conv-id="${conv.id}" onclick="switchToConversation('${conv.id}')">
          <div class="conv-item-title">${escapeHtml(conv.title)}</div>
          <div class="conv-item-time">${formatDate(conv.updatedAt)}</div>
          <button class="conv-delete-btn" onclick="event.stopPropagation(); deleteConversation('${conv.id}')" title="Delete">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </svg>
          </button>
        </div>
      `;
    });
  });

  // If no conversations, show empty state
  if (convs.length === 0) {
    html = `
      <div class="conv-section-title">Today</div>
      <div class="conv-item active">
        <div class="conv-item-title">New conversation</div>
        <div class="conv-item-time">Just now</div>
      </div>
    `;
  }

  container.innerHTML = html;
}

// Start a new chat
function startNewChat() {
  // Create new conversation
  const conv = createConversation();
  conversationId = conv.id;
  setCurrentConversationId(conv.id);

  // Reset UI
  messages = [];
  messagesContainer.innerHTML = '';
  messagesContainer.style.display = 'none';
  welcomeScreen.style.display = 'flex';
  messageInput.value = '';
  attachedFiles = [];
  renderFilePreview();
  sendBtn.disabled = true;
  userTurnCount = 0;
  clearContextSelection();

  // Update topbar
  updateTopbarTitle('New conversation');

  // Render sidebar
  renderConversationsList();

  // Reconnect WebSocket
  if (ws) ws.close();
  connectWebSocket();
}

// ══════════════════════════════════════════════════════════════════════════════
// WEBSOCKET CONNECTION
// ══════════════════════════════════════════════════════════════════════════════

let ws = null;
let conversationId = null;
let currentAssistantDiv = null;
let currentResponseText = '';
let currentStreamingToolCalls = [];  // Track tool calls for skill recording (Day 5)
let currentStreamingThinking = null;  // Track thinking for skill recording (Day 5.5)
let currentThinkingSteps = [];  // Track thinking steps
let isStreaming = false;

// Initialize conversation on load
function initializeConversation() {
  const savedId = getCurrentConversationId();
  const convs = getConversations();

  if (savedId && convs.find(c => c.id === savedId)) {
    // Resume existing conversation
    conversationId = savedId;
    const conv = convs.find(c => c.id === savedId);
    updateTopbarTitle(conv.title);
  } else if (convs.length > 0) {
    // Use most recent conversation
    conversationId = convs[0].id;
    setCurrentConversationId(conversationId);
    updateTopbarTitle(convs[0].title);
  } else {
    // Create first conversation
    const conv = createConversation();
    conversationId = conv.id;
    setCurrentConversationId(conv.id);
  }

  renderConversationsList();
}

function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/${conversationId}`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log('WebSocket connected:', conversationId);
    loadChatHistory();
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    handleWebSocketMessage(data);
  };

  ws.onclose = () => {
    console.log('WebSocket disconnected');
    // Only reconnect if not intentionally closed
    // setTimeout(connectWebSocket, 2000);
  };

  ws.onerror = (err) => {
    console.error('WebSocket error:', err);
  };
}

function handleWebSocketMessage(data) {
  switch (data.type) {
    case 'start':
      console.log('[WS] Received START event');
      removeTypingIndicator();
      currentAssistantDiv = createAssistantMessage();
      currentResponseText = '';
      currentStreamingThinking = null;
      currentThinkingSteps = [];
      setStreamingState(true);
      break;

    case 'thinking':
      // Day 5.5: Show thinking/reasoning before the answer
      // Create assistant div if not exists (fallback for race condition)
      if (!currentAssistantDiv) {
        removeTypingIndicator();
        currentAssistantDiv = createAssistantMessage();
        currentResponseText = '';
        setStreamingState(true);
        console.log('[WS] Created assistant div for thinking');
      }
      currentStreamingThinking = data.content;
      currentThinkingSteps = data.steps || [];
      showThinkingSection(currentAssistantDiv, data.content, data.steps);
      console.log('[WS] Thinking displayed:', data.steps?.length || 0, 'steps');
      break;

    case 'token':
      if (currentAssistantDiv) {
        currentResponseText = data.content;
        updateAssistantMessage(currentAssistantDiv, currentResponseText);
      }
      break;

    case 'tool_call':
      showToolCall(data.tool, data.args);
      // Track tool call for skill recording
      if (!currentStreamingToolCalls) currentStreamingToolCalls = [];
      currentStreamingToolCalls.push({ name: data.tool, args: data.args });
      break;

    case 'tool_result':
      showToolResult(data.content);
      break;

    case 'screenshot':
      showBrowserScreenshot(data.screenshot_b64, data.url, data.title);
      break;

    case 'end':
      // Remove all tool call messages
      document.querySelectorAll('.tool-message').forEach(el => el.remove());

      if (currentAssistantDiv && currentResponseText) {
        const newMsgIndex = messages.length;
        messages.push({ role: 'assistant', text: currentResponseText, files: [] });
        updateConversationMeta(conversationId);

        // Save tool calls for this message (for skill recording)
        if (currentStreamingToolCalls && currentStreamingToolCalls.length > 0) {
          messageToolCalls[newMsgIndex] = currentStreamingToolCalls;
        }

        // Day 5.5: Save thinking data for skill recording
        if (currentStreamingThinking || currentThinkingSteps.length > 0) {
          messageThinkingData[newMsgIndex] = {
            thinking_raw: currentStreamingThinking,
            thinking_steps: currentThinkingSteps
          };
        }
      }
      currentAssistantDiv = null;
      currentResponseText = '';
      currentStreamingToolCalls = [];  // Reset for next message
      currentStreamingThinking = null;  // Reset thinking
      currentThinkingSteps = [];
      setStreamingState(false);
      break;

    case 'error':
      removeTypingIndicator();
      addMessage('assistant', `Error: ${data.content}`);
      setStreamingState(false);
      break;

    case 'approval_required':
      // Show approval modal for HITL
      removeTypingIndicator();
      showApprovalModal(data);
      break;

    case 'credential_required':
      showCredentialModal(data.fields, data.submit_index);
      break;

    case 'rewind_result':
      if (data.success) {
        addMessage('assistant', `Rewound to checkpoint: ${data.checkpoint_id}`);
      } else {
        addMessage('assistant', `Rewind failed: ${data.message}`);
      }
      break;
  }
}

function createAssistantMessage() {
  const div = document.createElement('div');
  div.className = 'message assistant';
  div.innerHTML = `
    <div class="message-avatar">M</div>
    <div class="message-content">
      <div class="message-sender">MCP Assistant</div>
      <div class="message-body"></div>
    </div>
  `;
  messagesContainer.appendChild(div);
  chatArea.scrollTop = chatArea.scrollHeight;
  return div;
}

function updateAssistantMessage(div, text) {
  const body = div.querySelector('.message-body');
  if (body) {
    body.textContent = text;
    chatArea.scrollTop = chatArea.scrollHeight;
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// THINKING DISPLAY (Day 5.5 - Chain of Thought)
// ══════════════════════════════════════════════════════════════════════════════

/**
 * Show the thinking/reasoning section in assistant message
 * Collapsible like Claude's thinking blocks
 */
function showThinkingSection(messageDiv, thinkingContent, thinkingSteps) {
  if (!messageDiv || !thinkingContent) return;

  const contentDiv = messageDiv.querySelector('.message-content');
  if (!contentDiv) return;

  // Check if thinking section already exists
  let thinkingSection = contentDiv.querySelector('.thinking-section');

  if (!thinkingSection) {
    // Create new thinking section
    thinkingSection = document.createElement('div');
    thinkingSection.className = 'thinking-section';

    // Insert before message-body
    const messageBody = contentDiv.querySelector('.message-body');
    if (messageBody) {
      contentDiv.insertBefore(thinkingSection, messageBody);
    } else {
      contentDiv.appendChild(thinkingSection);
    }
  }

  // Build steps HTML
  const stepsHtml = thinkingSteps && thinkingSteps.length > 0
    ? thinkingSteps.map(step => `<div class="thinking-step">${escapeHtml(step)}</div>`).join('')
    : `<div class="thinking-step">${escapeHtml(thinkingContent)}</div>`;

  thinkingSection.innerHTML = `
    <div class="thinking-header" onclick="toggleThinking(this)">
      <div class="thinking-icon">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <path d="M12 16v-4"/>
          <path d="M12 8h.01"/>
        </svg>
      </div>
      <span class="thinking-label">Thinking</span>
      <span class="thinking-count">${thinkingSteps ? thinkingSteps.length : 1} steps</span>
      <svg class="thinking-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="6 9 12 15 18 9"/>
      </svg>
    </div>
    <div class="thinking-content">
      ${stepsHtml}
    </div>
  `;

  chatArea.scrollTop = chatArea.scrollHeight;
}

/**
 * Toggle thinking section expand/collapse
 */
function toggleThinking(headerEl) {
  const section = headerEl.closest('.thinking-section');
  if (section) {
    section.classList.toggle('expanded');
  }
}

function showBrowserScreenshot(b64, url, title) {
  const messagesDiv = document.getElementById('messages-container');
  const div = document.createElement('div');
  div.className = 'message assistant browser-screenshot-msg';
  const label = title ? `${title}` : (url ? url : 'Browser screenshot');
  div.innerHTML = `
    <div class="avatar">M</div>
    <div class="message-content">
      <div class="screenshot-label">${escapeHtml(label)}</div>
      <img class="browser-screenshot-img" src="data:image/png;base64,${b64}"
           alt="Browser screenshot" onclick="this.classList.toggle('expanded')" title="Click to expand" />
    </div>`;
  messagesDiv.appendChild(div);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function showToolCall(toolName, args) {
  const div = document.createElement('div');
  div.className = 'message assistant tool-message';
  div.innerHTML = `
    <div class="message-avatar">M</div>
    <div class="message-content">
      <div class="tool-call">
        <span class="spinner"></span>
        Calling tool: <strong>${escapeHtml(toolName)}</strong>
      </div>
    </div>
  `;
  messagesContainer.appendChild(div);
  chatArea.scrollTop = chatArea.scrollHeight;
}

function showToolResult(content) {
  const toolMsgs = document.querySelectorAll('.tool-message');
  const lastTool = toolMsgs[toolMsgs.length - 1];
  if (lastTool) {
    const spinner = lastTool.querySelector('.spinner');
    if (spinner) spinner.remove();
  }
}

// ── Load Chat History ──
async function loadChatHistory() {
  try {
    const response = await fetch(`/api/history/${conversationId}`);
    if (!response.ok) {
      // No history, show welcome screen
      welcomeScreen.style.display = 'flex';
      messagesContainer.style.display = 'none';
      return;
    }

    const data = await response.json();
    if (!data.checkpoints || data.checkpoints.length === 0) {
      welcomeScreen.style.display = 'flex';
      messagesContainer.style.display = 'none';
      return;
    }

    // Get the latest checkpoint state
    const latestCheckpoint = data.checkpoints[0];
    const stateResponse = await fetch(`/api/history/${conversationId}/${latestCheckpoint.checkpoint_id}`);
    if (!stateResponse.ok) return;

    const stateData = await stateResponse.json();
    if (!stateData.messages || stateData.messages.length === 0) {
      welcomeScreen.style.display = 'flex';
      messagesContainer.style.display = 'none';
      return;
    }

    // Clear current messages and tool calls cache
    messages = [];
    messageToolCalls = {};  // Clear tool calls cache
    messagesContainer.innerHTML = '';
    userTurnCount = 0;
    clearContextSelection();
    welcomeScreen.style.display = 'none';
    messagesContainer.style.display = 'block';

    // Restore messages and tool calls from history
    // Flow: AIMessage(tool_calls, empty) -> ToolMessage(result) -> AIMessage(final response)
    // We need to attach tool_calls to the FINAL AIMessage, not ToolMessage
    let pendingToolCalls = [];

    stateData.messages.forEach(msg => {
      const msgType = msg.type || '';
      const content = msg.content || '';

      // Collect tool_calls from AIMessages (even if content is empty)
      if (msg.tool_calls && msg.tool_calls.length > 0) {
        pendingToolCalls = pendingToolCalls.concat(msg.tool_calls);
        console.log(`[History] Found ${msg.tool_calls.length} tool calls, pending: ${pendingToolCalls.length}`);
      }

      // Skip ToolMessage - don't display raw tool results
      if (msgType === 'ToolMessage') {
        console.log(`[History] Skipping ToolMessage`);
        return;
      }

      // Determine role
      const role = msgType === 'HumanMessage' ? 'user' : 'assistant';

      // Only display messages with content
      if (content) {
        const messageIndex = messages.length;
        addMessage(role, content);

        // Attach pending tool_calls ONLY to AIMessage (not ToolMessage)
        if (role === 'assistant' && msgType.includes('AI') && pendingToolCalls.length > 0) {
          messageToolCalls[messageIndex] = [...pendingToolCalls];
          console.log(`[History] Attached ${pendingToolCalls.length} tool calls to AIMessage ${messageIndex}`);
          pendingToolCalls = [];  // Clear after attaching
        }
      }
    });

    // Day 5.5: Show thinking from history (if available)
    // Use raw thinking content and split into lines for complete display
    if (stateData.thinking) {
      const lastAssistantDiv = messagesContainer.querySelector('.message.assistant:last-of-type .message-content');
      if (lastAssistantDiv) {
        // Split raw thinking into lines for complete display
        const fullSteps = stateData.thinking.split('\n').filter(line => line.trim());
        showThinkingSection(lastAssistantDiv.closest('.message'), stateData.thinking, fullSteps);
        console.log(`[History] Restored thinking: ${fullSteps.length} lines from raw`);

        // ALSO populate messageThinkingData so skill recording can access it
        const lastAssistantIndex = messages.length - 1;
        if (lastAssistantIndex >= 0 && messages[lastAssistantIndex]?.role === 'assistant') {
          messageThinkingData[lastAssistantIndex] = {
            thinking_raw: stateData.thinking,
            thinking_steps: fullSteps
          };
          console.log(`[History] 📝 Saved thinking to messageThinkingData[${lastAssistantIndex}] for skill recording`);
        }
      }
    }

    console.log(`Restored ${stateData.messages.length} messages from history`);
  } catch (err) {
    console.log('No previous history:', err.message);
    welcomeScreen.style.display = 'flex';
    messagesContainer.style.display = 'none';
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// CHAT LOGIC
// ══════════════════════════════════════════════════════════════════════════════

const chatArea = document.getElementById('chat-area');
const welcomeScreen = document.getElementById('welcome-screen');
const messagesContainer = document.getElementById('messages-container');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const fileInput = document.getElementById('file-input');
const filePreview = document.getElementById('file-preview');
const newChatBtn = document.getElementById('new-chat-btn');

let attachedFiles = [];
let messages = [];
let pendingEdit = null;  // For edit message feature

// Context selection: tracks which user turn indices are pinned
let selectedContextIndices = new Set();
let userTurnCount = 0;  // increments for each user message added

// Initialize on load
initializeConversation();
connectWebSocket();

messageInput.addEventListener('input', () => {
  messageInput.style.height = 'auto';
  messageInput.style.height = Math.min(messageInput.scrollHeight, 150) + 'px';
  sendBtn.disabled = messageInput.value.trim() === '' && attachedFiles.length === 0;
});

messageInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    if (!sendBtn.disabled) sendMessage();
  }
});

sendBtn.addEventListener('click', () => {
  if (isStreaming) {
    stopStreaming();
  } else {
    sendMessage();
  }
});

newChatBtn.addEventListener('click', startNewChat);

fileInput.addEventListener('change', () => {
  const files = Array.from(fileInput.files);
  files.forEach(f => {
    if (!attachedFiles.find(a => a.name === f.name)) {
      attachedFiles.push(f);
    }
  });
  renderFilePreview();
  fileInput.value = '';
  sendBtn.disabled = messageInput.value.trim() === '' && attachedFiles.length === 0;
});

function renderFilePreview() {
  if (attachedFiles.length === 0) {
    filePreview.classList.remove('active');
    filePreview.innerHTML = '';
    return;
  }
  filePreview.classList.add('active');
  filePreview.innerHTML = attachedFiles.map((f, i) => `
    <span class="file-tag">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
      ${f.name}
      <button onclick="removeFile(${i})">&times;</button>
    </span>
  `).join('');
}

function removeFile(index) {
  attachedFiles.splice(index, 1);
  renderFilePreview();
  sendBtn.disabled = messageInput.value.trim() === '' && attachedFiles.length === 0;
}

function usePrompt(text) {
  messageInput.value = text;
  messageInput.dispatchEvent(new Event('input'));
  sendMessage();
}

async function sendMessage() {
  const text = messageInput.value.trim();
  if (!text && attachedFiles.length === 0) return;

  welcomeScreen.style.display = 'none';
  messagesContainer.style.display = 'block';

  // Handle pending edit - need to rewind first
  if (pendingEdit) {
    await handleEditSend(text);
    return;
  }

  const fileNames = attachedFiles.map(f => f.name);
  addMessage('user', text, fileNames);

  // Auto-name conversation from first message
  if (messages.length === 1) {
    updateConversationTitle(conversationId, text);
  }

  messageInput.value = '';
  messageInput.style.height = 'auto';
  attachedFiles = [];
  renderFilePreview();
  sendBtn.disabled = true;

  // Show typing indicator
  addTypingIndicator();

  // Send via WebSocket
  if (ws && ws.readyState === WebSocket.OPEN) {
    const payload = { message: text };
    if (selectedContextIndices.size > 0) {
      payload.selected_context_indices = [...selectedContextIndices];
    }
    ws.send(JSON.stringify(payload));
    // Reset context selection after sending
    clearContextSelection();
  } else {
    removeTypingIndicator();
    addMessage('assistant', 'Connection error. Please refresh the page.');
  }
}

async function handleEditSend(newText) {
  const editInfo = pendingEdit;

  // Hide edit indicator and clear pending
  hideEditIndicator();
  pendingEdit = null;

  messageInput.value = '';
  messageInput.style.height = 'auto';
  attachedFiles = [];
  renderFilePreview();
  sendBtn.disabled = true;

  try {
    // Find the parent checkpoint (state BEFORE the user message we're editing)
    const timelineResponse = await fetch(`/api/history/${conversationId}`);
    const timelineData = await timelineResponse.json();

    // We want the checkpoint with message_count = editInfo.messageCount - 1
    // This is the state RIGHT BEFORE the user message we're editing
    const targetMsgCount = editInfo.messageCount - 1;
    let parentCheckpointId = null;

    console.log(`[EDIT] Looking for checkpoint with ${targetMsgCount} messages (editing message at count ${editInfo.messageCount})`);

    if (targetMsgCount > 0 && timelineData.checkpoints) {
      for (const cp of timelineData.checkpoints) {
        if (cp.message_count === targetMsgCount) {
          parentCheckpointId = cp.checkpoint_id;
          console.log(`[EDIT] Found parent checkpoint: ${parentCheckpointId}`);
          break;
        }
      }
    }

    // If no parent found and targetMsgCount = 0, it means we're editing the first message
    // In this case, LangGraph will start fresh (no checkpoint_id passed)
    if (targetMsgCount === 0) {
      console.log('[EDIT] Editing first message - will start fresh');
    } else if (!parentCheckpointId) {
      console.log('[EDIT] Warning: Could not find parent checkpoint, will send as normal message');
    }

    // Show the new user message in UI
    addMessage('user', newText, []);
    addTypingIndicator();

    // Use LangGraph's native checkpoint resumption - SAME thread, resume from checkpoint
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'edit_from_checkpoint',
        message: newText,
        checkpoint_id: parentCheckpointId  // Resume from this checkpoint (null for first message)
      }));
      console.log(`[EDIT] Sent edit request with checkpoint_id: ${parentCheckpointId}`);
    } else {
      removeTypingIndicator();
      addMessage('assistant', 'Connection error. Please refresh.');
    }

  } catch (err) {
    console.error('Edit send failed:', err);
    removeTypingIndicator();
    addMessage('assistant', 'Failed to edit. Please try again.');
  }
}

function addMessage(role, text, files = []) {
  const messageIndex = messages.length;
  messages.push({ role, text, files });

  const div = document.createElement('div');
  div.className = `message ${role}`;
  div.setAttribute('data-message-index', messageIndex);

  const avatarLabel = role === 'user' ? 'U' : 'M';
  let fileHtml = '';
  if (files.length > 0) {
    fileHtml = `<div style="margin-top:6px;">${files.map(f =>
      `<span class="file-tag"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg> ${escapeHtml(f)}</span>`
    ).join(' ')}</div>`;
  }

  // Context selection checkbox for user messages
  let contextCheckboxHtml = '';
  if (role === 'user') {
    const turnIndex = userTurnCount;
    userTurnCount++;
    div.setAttribute('data-turn-index', turnIndex);
    contextCheckboxHtml = `
      <button class="context-checkbox" data-turn-index="${turnIndex}" onclick="toggleContextSelection(${turnIndex}, this)" title="Pin this message as context for LLM">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
      </button>
    `;
  }

  // Add feedback buttons for assistant messages
  let feedbackHtml = '';
  if (role === 'assistant' && text && !text.startsWith('Error:')) {
    feedbackHtml = `
      <div class="message-feedback" data-message-index="${messageIndex}">
        <button class="feedback-btn thumbs-up" onclick="submitFeedback(${messageIndex}, 'positive')" title="Good response">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
          </svg>
        </button>
        <button class="feedback-btn thumbs-down" onclick="submitFeedback(${messageIndex}, 'negative')" title="Bad response">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/>
          </svg>
        </button>
        <button class="skill-like-btn" onclick="openSkillPopup(${messageIndex})" title="Save as skill">
          <span class="skill-like-tooltip">Save as skill?</span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
          </svg>
        </button>
      </div>
    `;
  }

  div.innerHTML = `
    <div class="message-avatar">${avatarLabel}</div>
    <div class="message-content">
      ${contextCheckboxHtml}
      <div class="message-sender">${role === 'user' ? 'You' : 'MCP Assistant'}</div>
      <div class="message-body">${escapeHtml(text)}${fileHtml}</div>
      ${feedbackHtml}
    </div>
  `;

  messagesContainer.appendChild(div);
  chatArea.scrollTop = chatArea.scrollHeight;
}

function toggleContextSelection(turnIndex, btn) {
  if (selectedContextIndices.has(turnIndex)) {
    selectedContextIndices.delete(turnIndex);
    btn.classList.remove('active');
  } else {
    selectedContextIndices.add(turnIndex);
    btn.classList.add('active');
  }
  updateContextFilterBanner();
}

function updateContextFilterBanner() {
  let banner = document.getElementById('context-filter-banner');
  if (selectedContextIndices.size > 0) {
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'context-filter-banner';
      banner.className = 'context-filter-banner';
      banner.innerHTML = `
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z"/></svg>
        <span id="context-filter-text"></span>
        <button onclick="clearContextSelection()" title="Clear filter">✕</button>
      `;
      const inputArea = document.querySelector('.input-area');
      inputArea.insertBefore(banner, inputArea.firstChild);
    }
    document.getElementById('context-filter-text').textContent =
      `Sending ${selectedContextIndices.size} pinned message${selectedContextIndices.size > 1 ? 's' : ''} as context`;
  } else if (banner) {
    banner.remove();
  }
}

function clearContextSelection() {
  selectedContextIndices.clear();
  document.querySelectorAll('.context-checkbox.active').forEach(btn => btn.classList.remove('active'));
  updateContextFilterBanner();
}

function addTypingIndicator() {
  const div = document.createElement('div');
  div.className = 'message assistant';
  div.id = 'typing-msg';
  div.innerHTML = `
    <div class="message-avatar">M</div>
    <div class="message-content">
      <div class="message-sender">MCP Assistant</div>
      <div class="typing-indicator"><span></span><span></span><span></span></div>
    </div>
  `;
  messagesContainer.appendChild(div);
  chatArea.scrollTop = chatArea.scrollHeight;
}

function removeTypingIndicator() {
  const el = document.getElementById('typing-msg');
  if (el) el.remove();
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ══════════════════════════════════════════════════════════════════════════════
// MCP CONNECTOR
// ══════════════════════════════════════════════════════════════════════════════

const mcpConnectorBtn = document.getElementById('mcp-connector-btn');
const mcpConnectorPopup = document.getElementById('mcp-connector-popup');
const mcpServersList = document.getElementById('mcp-servers-list');
let mcpTools = [];

mcpConnectorBtn.addEventListener('click', (e) => {
  e.stopPropagation();
  mcpConnectorPopup.classList.toggle('open');
  if (mcpConnectorPopup.classList.contains('open')) {
    loadMcpTools();
  }
});

document.addEventListener('click', (e) => {
  if (!e.target.closest('.mcp-connector')) {
    mcpConnectorPopup.classList.remove('open');
  }
});

async function loadMcpTools() {
  try {
    const response = await fetch('/api/tools');
    const data = await response.json();
    mcpTools = data.tools || [];
    renderMcpServers();
  } catch (err) {
    console.error('Failed to load MCP tools:', err);
    mcpServersList.innerHTML = '<div class="mcp-no-tools">Failed to load tools</div>';
  }
}

function renderMcpServers() {
  if (mcpTools.length === 0) {
    mcpServersList.innerHTML = '<div class="mcp-no-tools">No tools connected</div>';
    return;
  }

  const servers = {};
  for (const tool of mcpTools) {
    let serverName = 'Expense Tracker';
    if (tool.name.startsWith('browser_')) serverName = 'Browser Agent';
    if (!servers[serverName]) servers[serverName] = [];
    servers[serverName].push(tool);
  }

  mcpServersList.innerHTML = Object.entries(servers).map(([serverName, tools]) => `
    <div class="mcp-server-item" data-server="${serverName}">
      <div class="mcp-server-header" onclick="toggleServerTools('${serverName}')">
        <div class="mcp-server-icon">${serverName[0]}</div>
        <div class="mcp-server-info">
          <div class="mcp-server-name">${serverName}</div>
          <div class="mcp-server-count">${tools.length} tools</div>
        </div>
        <svg class="mcp-server-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
      </div>
      <div class="mcp-tools-list">
        ${tools.map(tool => `
          <div class="mcp-tool-item" onclick="insertToolPrompt('${escapeHtml(tool.name)}')">
            <div class="mcp-tool-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>
            </div>
            <div class="mcp-tool-info">
              <div class="mcp-tool-name">${escapeHtml(tool.name)}</div>
              <div class="mcp-tool-desc">${escapeHtml(tool.description || 'No description')}</div>
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `).join('');
}

function toggleServerTools(serverName) {
  const serverItem = document.querySelector(`.mcp-server-item[data-server="${serverName}"]`);
  if (serverItem) {
    serverItem.classList.toggle('expanded');
  }
}

function insertToolPrompt(toolName) {
  const prompts = {
    'add_expense': 'Add an expense: [date], [amount], [category]',
    'list_expenses': 'List expenses from [start_date] to [end_date]',
    'summarize': 'Summarize expenses from [start_date] to [end_date]',
    'payload_generator': 'Generate XSS payload'
  };

  const prompt = prompts[toolName] || `Use ${toolName} tool`;
  messageInput.value = prompt;
  messageInput.dispatchEvent(new Event('input'));
  mcpConnectorPopup.classList.remove('open');
  messageInput.focus();
  messageInput.select();
}

// ══════════════════════════════════════════════════════════════════════════════
// STREAMING STATE
// ══════════════════════════════════════════════════════════════════════════════

function setStreamingState(streaming) {
  isStreaming = streaming;
  const sendIcon = sendBtn.querySelector('.send-icon');
  const stopIcon = sendBtn.querySelector('.stop-icon');

  if (streaming) {
    sendIcon.style.display = 'none';
    stopIcon.style.display = 'block';
    sendBtn.disabled = false;
    sendBtn.classList.add('streaming');
  } else {
    sendIcon.style.display = 'block';
    stopIcon.style.display = 'none';
    sendBtn.classList.remove('streaming');
    sendBtn.disabled = messageInput.value.trim() === '' && attachedFiles.length === 0;
  }
}

function stopStreaming() {
  removeTypingIndicator();
  document.querySelectorAll('.tool-message').forEach(el => el.remove());

  if (currentAssistantDiv && currentResponseText) {
    messages.push({ role: 'assistant', text: currentResponseText + ' [stopped]', files: [] });
  } else if (currentAssistantDiv) {
    currentAssistantDiv.remove();
  }

  currentAssistantDiv = null;
  currentResponseText = '';
  setStreamingState(false);

  if (ws) ws.close();
  connectWebSocket();
}

// ══════════════════════════════════════════════════════════════════════════════
// TIME TRAVEL
// ══════════════════════════════════════════════════════════════════════════════

const timeTravelBtn = document.getElementById('time-travel-btn');
const timeTravelPanel = document.getElementById('time-travel-panel');
const ttCloseBtn = document.getElementById('tt-close-btn');
const ttTimeline = document.getElementById('tt-timeline');

timeTravelBtn.addEventListener('click', () => {
  timeTravelPanel.classList.add('open');
  loadTimeline();
});

ttCloseBtn.addEventListener('click', () => {
  timeTravelPanel.classList.remove('open');
});

// Close panel when clicking outside
document.addEventListener('click', (e) => {
  if (timeTravelPanel.classList.contains('open') &&
    !e.target.closest('.time-travel-panel') &&
    !e.target.closest('#time-travel-btn')) {
    timeTravelPanel.classList.remove('open');
  }
});

async function loadTimeline() {
  ttTimeline.innerHTML = '<div class="tt-loading">Loading history...</div>';

  try {
    const response = await fetch(`/api/history/${conversationId}`);

    if (!response.ok) {
      ttTimeline.innerHTML = '<div class="tt-empty">No history available yet. Start chatting to create checkpoints.</div>';
      return;
    }

    const data = await response.json();

    if (!data.checkpoints || data.checkpoints.length === 0) {
      ttTimeline.innerHTML = '<div class="tt-empty">No checkpoints found. History will appear after you chat.</div>';
      return;
    }

    renderTimeline(data.checkpoints);
  } catch (err) {
    console.error('Failed to load timeline:', err);
    ttTimeline.innerHTML = '<div class="tt-empty">Failed to load history. Make sure MongoDB is running.</div>';
  }
}

function renderTimeline(checkpoints) {
  if (checkpoints.length === 0) {
    ttTimeline.innerHTML = '<div class="tt-empty">No checkpoints yet. Start chatting!</div>';
    return;
  }

  // Filter to show ONLY user message checkpoints (odd message counts: 1, 3, 5, ...)
  // These represent states right after user sent a message
  const userCheckpoints = [];
  const seenMsgCounts = new Set();

  for (const cp of checkpoints) {
    const msgCount = cp.message_count || 0;
    // Only odd counts (user messages) and deduplicate
    if (msgCount > 0 && msgCount % 2 === 1 && !seenMsgCounts.has(msgCount)) {
      userCheckpoints.push(cp);
      seenMsgCounts.add(msgCount);
    }
  }

  if (userCheckpoints.length === 0) {
    ttTimeline.innerHTML = '<div class="tt-empty">No user messages to edit yet. Start chatting!</div>';
    return;
  }

  ttTimeline.innerHTML = `
    <div class="tt-timeline-line"></div>
    ${userCheckpoints.map((cp, index) => {
    const preview = cp.preview || {};
    const userMsg = preview.last_user_message || 'No message';
    const stepNum = userCheckpoints.length - index;
    const msgNum = Math.ceil((cp.message_count || 1) / 2); // User message number (1st, 2nd, 3rd...)

    return `
        <div class="tt-checkpoint" data-checkpoint-id="${cp.checkpoint_id}" data-msg-count="${cp.message_count}">
          <div class="tt-checkpoint-dot">
            <span class="tt-step-num">${stepNum}</span>
          </div>
          <div class="tt-checkpoint-card">
            <div class="tt-checkpoint-header">
              <span class="tt-checkpoint-time">${formatCheckpointTime(cp.created_at)}</span>
              <span class="tt-checkpoint-count">Message #${msgNum}</span>
            </div>
            <div class="tt-checkpoint-preview">
              <div class="tt-preview-user">
                <span class="tt-preview-icon">U</span>
                <span class="tt-preview-text">${escapeHtml(userMsg)}</span>
              </div>
            </div>
            <div class="tt-checkpoint-actions">
              <button class="tt-btn edit" onclick="editFromCheckpoint('${cp.checkpoint_id}', ${cp.message_count})" title="Edit this message">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
                  <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
                </svg>
                Edit
              </button>
              <button class="tt-btn branch" onclick="branchFromCheckpoint('${cp.checkpoint_id}')" title="Create new chat from here">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="6" y1="3" x2="6" y2="15"/>
                  <circle cx="18" cy="6" r="3"/>
                  <circle cx="6" cy="18" r="3"/>
                  <path d="M18 9a9 9 0 01-9 9"/>
                </svg>
                Branch
              </button>
            </div>
          </div>
        </div>
      `;
  }).join('')}
  `;
}

function formatCheckpointTime(dateStr) {
  const date = new Date(dateStr);
  return date.toLocaleString();
}

async function editFromCheckpoint(checkpointId, messageCount) {
  try {
    // Get the state at this checkpoint
    const response = await fetch(`/api/history/${conversationId}/${checkpointId}`);
    if (!response.ok) {
      alert('Failed to load checkpoint state.');
      return;
    }

    const stateData = await response.json();
    if (!stateData.messages || stateData.messages.length === 0) {
      alert('No messages found in this checkpoint.');
      return;
    }

    // Close the time travel panel
    timeTravelPanel.classList.remove('open');

    // Clear current UI
    messages = [];
    messagesContainer.innerHTML = '';

    // Get the user message that will be edited (last message in this checkpoint)
    const allMessages = stateData.messages;
    const userMessageToEdit = allMessages[allMessages.length - 1];
    const userMessageContent = userMessageToEdit.content || '';

    // Display messages BEFORE the user message (all except last)
    const messagesToShow = allMessages.slice(0, -1);

    if (messagesToShow.length === 0) {
      // This is the first user message, show welcome screen briefly then input
      welcomeScreen.style.display = 'none';
      messagesContainer.style.display = 'block';
    } else {
      welcomeScreen.style.display = 'none';
      messagesContainer.style.display = 'block';

      // Restore messages before the edit point
      messagesToShow.forEach(msg => {
        const msgType = msg.type || '';
        const role = msgType.toLowerCase().includes('human') ? 'user' : 'assistant';
        const content = msg.content || '';
        if (content) {
          addMessage(role, content);
        }
      });
    }

    // Put the user message in the input box for editing
    messageInput.value = userMessageContent;
    messageInput.dispatchEvent(new Event('input'));
    messageInput.focus();
    messageInput.select();

    // Store pending edit info - we need to rewind before sending
    pendingEdit = {
      checkpointId: checkpointId,
      originalMessage: userMessageContent,
      messageCount: messageCount
    };

    // Show edit indicator
    showEditIndicator(userMessageContent);

  } catch (err) {
    console.error('Edit failed:', err);
    alert('Failed to load checkpoint for editing. Please try again.');
  }
}

function showEditIndicator(originalMessage) {
  // Remove existing indicator if any
  hideEditIndicator();

  const indicator = document.createElement('div');
  indicator.className = 'edit-indicator';
  indicator.id = 'edit-indicator';
  indicator.innerHTML = `
    <div class="edit-indicator-content">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
        <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
      </svg>
      <span>Editing message</span>
      <button class="edit-cancel-btn" onclick="cancelEdit()" title="Cancel edit">&times;</button>
    </div>
  `;

  // Insert before input area
  const inputArea = document.querySelector('.input-area');
  inputArea.insertBefore(indicator, inputArea.firstChild);
}

function hideEditIndicator() {
  const indicator = document.getElementById('edit-indicator');
  if (indicator) indicator.remove();
}

function cancelEdit() {
  pendingEdit = null;
  hideEditIndicator();
  messageInput.value = '';
  messageInput.dispatchEvent(new Event('input'));

  // Reload original conversation
  loadChatHistory();
}

async function branchFromCheckpoint(checkpointId) {
  try {
    // Create new conversation from this checkpoint
    const newConv = createConversation();
    newConv.title = 'Branched conversation';

    const convs = getConversations();
    const idx = convs.findIndex(c => c.id === newConv.id);
    if (idx >= 0) {
      convs[idx] = newConv;
      saveConversations(convs);
    }

    // Call branch API
    const response = await fetch('/api/history/branch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_thread_id: conversationId,
        checkpoint_id: checkpointId,
        new_thread_id: newConv.id
      })
    });

    if (response.ok) {
      // Switch to the new branched conversation
      timeTravelPanel.classList.remove('open');
      switchToConversation(newConv.id);
    } else {
      alert('Failed to create branch. Please try again.');
    }

  } catch (err) {
    console.error('Branch failed:', err);
    alert('Failed to create branch. Please try again.');
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// APPROVAL MODAL
// ══════════════════════════════════════════════════════════════════════════════

const approvalModal = document.getElementById('approval-modal');
const approvalTool = document.getElementById('approval-tool');
const approvalMessage = document.getElementById('approval-message');
const approvalRisk = document.getElementById('approval-risk');
const approvalApproveBtn = document.getElementById('approval-approve');
const approvalRejectBtn = document.getElementById('approval-reject');

let currentInterruptId = null;

function showApprovalModal(data) {
  currentInterruptId = data.interrupt_id;

  approvalTool.textContent = `Tool: ${data.tool_call?.name || 'Unknown'}`;
  approvalMessage.textContent = data.message || 'This action requires your approval.';

  const riskLevel = (data.risk_level || 'medium').toLowerCase();
  approvalRisk.textContent = riskLevel;
  approvalRisk.className = 'approval-risk ' + riskLevel;

  approvalModal.classList.add('open');
}

function hideApprovalModal() {
  approvalModal.classList.remove('open');
  currentInterruptId = null;
}

approvalApproveBtn.addEventListener('click', () => {
  if (currentInterruptId && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'interrupt_response',
      interrupt_id: currentInterruptId,
      status: 'approved',
      data: {}
    }));
  }
  hideApprovalModal();
});

approvalRejectBtn.addEventListener('click', () => {
  if (currentInterruptId && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'interrupt_response',
      interrupt_id: currentInterruptId,
      status: 'rejected',
      data: {}
    }));
  }
  hideApprovalModal();
  addMessage('assistant', 'Action was rejected by user.');
});

// ══════════════════════════════════════════════════════════════════════════════
// CREDENTIAL MODAL
// ══════════════════════════════════════════════════════════════════════════════

let _credentialFields = [];
let _credentialSubmitIndex = null;
const credentialModal = document.getElementById('credential-modal');
const credentialFieldsDiv = document.getElementById('credential-fields');

function showCredentialModal(fields, submitIndex) {
  _credentialFields = fields;
  _credentialSubmitIndex = submitIndex;
  credentialFieldsDiv.innerHTML = fields.map(f => `
    <div style="margin-bottom:10px;">
      <label style="display:block;margin-bottom:4px;font-weight:600;">${escapeHtml(f.label)}</label>
      <input type="${f.type}" data-index="${f.index}" placeholder="${escapeHtml(f.label)}"
        style="width:100%;padding:8px;border:1px solid #ccc;border-radius:6px;font-size:14px;" />
    </div>`).join('');
  credentialModal.classList.add('open');
}

document.getElementById('credential-submit').addEventListener('click', () => {
  const inputs = credentialFieldsDiv.querySelectorAll('input');
  const credentials = {};
  inputs.forEach(inp => { credentials[inp.dataset.index] = inp.value; });
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'credential_response',
      credentials,
      submit_index: _credentialSubmitIndex
    }));
  }
  credentialModal.classList.remove('open');
});

document.getElementById('credential-cancel').addEventListener('click', () => {
  credentialModal.classList.remove('open');
});

// ══════════════════════════════════════════════════════════════════════════════
// FEEDBACK SYSTEM (Day 4 - Prompt Improvements)
// ══════════════════════════════════════════════════════════════════════════════

async function submitFeedback(messageIndex, feedbackType) {
  const messageData = messages[messageIndex];
  if (!messageData || messageData.role !== 'assistant') {
    console.error('Invalid message for feedback');
    return;
  }

  // Get the user message that preceded this response
  let originalPrompt = '';
  for (let i = messageIndex - 1; i >= 0; i--) {
    if (messages[i].role === 'user') {
      originalPrompt = messages[i].text;
      break;
    }
  }

  // Update UI to show feedback received
  const feedbackDiv = document.querySelector(`.message-feedback[data-message-index="${messageIndex}"]`);
  if (feedbackDiv) {
    if (feedbackType === 'positive') {
      feedbackDiv.innerHTML = `
        <span class="feedback-received positive">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none">
            <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
          </svg>
          Thanks for the feedback!
        </span>
      `;
    } else {
      // For negative feedback, show input for additional context
      feedbackDiv.innerHTML = `
        <div class="feedback-form">
          <input type="text" class="feedback-input" placeholder="What was wrong? (optional)" id="feedback-input-${messageIndex}">
          <button class="feedback-submit-btn" onclick="sendNegativeFeedback(${messageIndex}, '${escapeHtml(originalPrompt)}', '${escapeHtml(messageData.text)}')">
            Submit
          </button>
          <button class="feedback-cancel-btn" onclick="cancelFeedback(${messageIndex})">
            Cancel
          </button>
        </div>
      `;
    }
  }

  // For positive feedback, send immediately
  if (feedbackType === 'positive') {
    try {
      await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          feedback_type: 'positive',
          original_prompt: originalPrompt,
          llm_response: messageData.text,
          thread_id: conversationId,
        })
      });
      console.log('Positive feedback submitted');
    } catch (err) {
      console.error('Failed to submit feedback:', err);
    }
  }
}

async function sendNegativeFeedback(messageIndex, originalPrompt, llmResponse) {
  const inputEl = document.getElementById(`feedback-input-${messageIndex}`);
  const userFeedback = inputEl ? inputEl.value : '';

  // Update UI to show processing
  const feedbackDiv = document.querySelector(`.message-feedback[data-message-index="${messageIndex}"]`);
  if (feedbackDiv) {
    feedbackDiv.innerHTML = `
      <span class="feedback-processing">
        <span class="spinner-small"></span>
        Learning from feedback...
      </span>
    `;
  }

  try {
    const response = await fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        feedback_type: 'negative',
        original_prompt: originalPrompt,
        llm_response: llmResponse,
        user_feedback: userFeedback || 'User marked as unhelpful',
        thread_id: conversationId,
      })
    });

    const data = await response.json();

    if (feedbackDiv) {
      if (data.success) {
        feedbackDiv.innerHTML = `
          <span class="feedback-received negative">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M22 11.08V12a10 10 0 11-5.93-9.14"/>
              <polyline points="22 4 12 14.01 9 11.01"/>
            </svg>
            Learned! I'll do better next time.
          </span>
        `;
      } else {
        feedbackDiv.innerHTML = `
          <span class="feedback-received error">
            Failed to process feedback
          </span>
        `;
      }
    }

    console.log('Negative feedback submitted:', data);

  } catch (err) {
    console.error('Failed to submit negative feedback:', err);
    if (feedbackDiv) {
      feedbackDiv.innerHTML = `
        <span class="feedback-received error">
          Error submitting feedback
        </span>
      `;
    }
  }
}

function cancelFeedback(messageIndex) {
  const feedbackDiv = document.querySelector(`.message-feedback[data-message-index="${messageIndex}"]`);
  if (feedbackDiv) {
    // Restore original feedback buttons
    feedbackDiv.innerHTML = `
      <button class="feedback-btn thumbs-up" onclick="submitFeedback(${messageIndex}, 'positive')" title="Good response">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
        </svg>
      </button>
      <button class="feedback-btn thumbs-down" onclick="submitFeedback(${messageIndex}, 'negative')" title="Bad response">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/>
        </svg>
      </button>
      <button class="skill-like-btn" onclick="openSkillPopup(${messageIndex})" title="Save as skill">
        <span class="skill-like-tooltip">Save as skill?</span>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
        </svg>
      </button>
    `;
  }
}


// ══════════════════════════════════════════════════════════════════════════════
// SKILL RECORDING (Day 5)
// ══════════════════════════════════════════════════════════════════════════════

// Skill popup elements
const skillPopupOverlay = document.getElementById('skill-popup-overlay');
const skillPreviewQuery = document.getElementById('skill-preview-query');
const skillPreviewTools = document.getElementById('skill-preview-tools');
const skillPopupCancel = document.getElementById('skill-popup-cancel');
const skillPopupConfirm = document.getElementById('skill-popup-confirm');

// Notification toast elements
const notificationToast = document.getElementById('notification-toast');
const notificationTitle = document.getElementById('notification-title');
const notificationMessage = document.getElementById('notification-message');
const notificationClose = document.getElementById('notification-close');

// Current skill recording context
let currentSkillContext = null;

// Track tool calls for each message (populated during streaming)
let messageToolCalls = {};

// Day 5.5: Track thinking data for each message
let messageThinkingData = {};

/**
 * Open the skill recording popup
 * @param {number} messageIndex - Index of the assistant message
 */
function openSkillPopup(messageIndex) {
  // Get the user query (message before this assistant message)
  let userQuery = '';
  let assistantResponse = '';

  // Find the user message that triggered this response
  for (let i = messageIndex - 1; i >= 0; i--) {
    if (messages[i] && messages[i].role === 'user') {
      userQuery = messages[i].text;
      break;
    }
  }

  // Get the assistant response
  if (messages[messageIndex]) {
    assistantResponse = messages[messageIndex].text;
  }

  // Get tool calls for this message (if any)
  const toolCalls = messageToolCalls[messageIndex] || [];

  // Day 5.5: Get thinking data for this message
  const thinkingData = messageThinkingData[messageIndex] || { thinking_raw: '', thinking_steps: [] };

  // Store context for confirmation
  currentSkillContext = {
    messageIndex,
    userQuery,
    assistantResponse,
    toolCalls,
    reasoningSteps: thinkingData.thinking_steps,
    reasoningRaw: thinkingData.thinking_raw
  };

  // Populate popup preview
  skillPreviewQuery.textContent = userQuery.length > 100
    ? userQuery.substring(0, 100) + '...'
    : userQuery;

  // Show tools used
  if (toolCalls.length > 0) {
    skillPreviewTools.innerHTML = toolCalls.map(tc =>
      `<span class="skill-tool-tag">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
        </svg>
        ${tc.name || tc.tool || 'unknown'}
      </span>`
    ).join('');
  } else {
    skillPreviewTools.innerHTML = '<span class="skill-tool-tag" style="opacity: 0.6;">No tools (reasoning only)</span>';
  }

  // Show popup
  skillPopupOverlay.classList.add('active');
}

/**
 * Close the skill recording popup
 */
function closeSkillPopup() {
  skillPopupOverlay.classList.remove('active');
  currentSkillContext = null;
}

/**
 * Confirm and record the skill
 */
async function confirmRecordSkill() {
  if (!currentSkillContext) return;

  const { userQuery, assistantResponse, toolCalls, messageIndex, reasoningSteps, reasoningRaw } = currentSkillContext;

  // Disable confirm button and show loading
  skillPopupConfirm.disabled = true;
  skillPopupConfirm.innerHTML = `
    <div class="spinner-small"></div>
    Saving...
  `;

  try {
    // Debug: Log what's being sent to API
    console.log('[SKILL] Recording skill with:', {
      userQuery: userQuery?.substring(0, 50),
      reasoningSteps: reasoningSteps?.length || 0,
      reasoningRaw: reasoningRaw?.length || 0,
      toolCalls: toolCalls?.length || 0
    });

    const response = await fetch('/api/record-skill', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_query: userQuery,
        llm_response: assistantResponse,
        tool_calls: toolCalls,
        conversation_id: getCurrentConversationId(),
        user_id: 'default',
        reasoning_steps: reasoningSteps || [],
        reasoning_raw: reasoningRaw || ''
      })
    });

    const data = await response.json();

    if (data.success) {
      // Mark the button as liked
      const likeBtn = document.querySelector(`.message-feedback[data-message-index="${messageIndex}"] .skill-like-btn`);
      if (likeBtn) {
        likeBtn.classList.add('liked');
      }

      // Show success notification
      showNotification('success', 'Skill Saved!', `"${data.skill_name}" added to your skill library.`);

      closeSkillPopup();
    } else {
      // Show info notification for non-recordable skills
      showNotification('info', 'Cannot Save', data.message || 'This response cannot be saved as a skill.');
      closeSkillPopup();
    }

  } catch (err) {
    console.error('Failed to record skill:', err);
    showNotification('error', 'Error', 'Failed to save skill. Please try again.');
  } finally {
    // Reset confirm button
    skillPopupConfirm.disabled = false;
    skillPopupConfirm.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
      </svg>
      Save Skill
    `;
  }
}

/**
 * Show a notification toast
 * @param {string} type - 'success', 'error', or 'info'
 * @param {string} title - Notification title
 * @param {string} message - Notification message
 */
function showNotification(type, title, message) {
  // Set content
  notificationTitle.textContent = title;
  notificationMessage.textContent = message;

  // Set type class
  notificationToast.className = 'notification-toast active ' + type;

  // Update icon based on type
  const iconContainer = document.getElementById('notification-icon');
  if (type === 'success') {
    iconContainer.innerHTML = `
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
        <polyline points="22 4 12 14.01 9 11.01"/>
      </svg>
    `;
  } else if (type === 'error') {
    iconContainer.innerHTML = `
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/>
        <line x1="15" y1="9" x2="9" y2="15"/>
        <line x1="9" y1="9" x2="15" y2="15"/>
      </svg>
    `;
  } else {
    iconContainer.innerHTML = `
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="16" x2="12" y2="12"/>
        <line x1="12" y1="8" x2="12.01" y2="8"/>
      </svg>
    `;
  }

  // Auto-hide after 4 seconds
  setTimeout(() => {
    hideNotification();
  }, 4000);
}

/**
 * Hide the notification toast
 */
function hideNotification() {
  notificationToast.classList.add('hiding');
  setTimeout(() => {
    notificationToast.classList.remove('active', 'hiding', 'success', 'error', 'info');
  }, 300);
}

// Event listeners for skill popup
if (skillPopupCancel) {
  skillPopupCancel.addEventListener('click', closeSkillPopup);
}

if (skillPopupConfirm) {
  skillPopupConfirm.addEventListener('click', confirmRecordSkill);
}

if (skillPopupOverlay) {
  skillPopupOverlay.addEventListener('click', (e) => {
    if (e.target === skillPopupOverlay) {
      closeSkillPopup();
    }
  });
}

if (notificationClose) {
  notificationClose.addEventListener('click', hideNotification);
}

// Track tool calls during message streaming
function trackToolCall(messageIndex, toolCall) {
  if (!messageToolCalls[messageIndex]) {
    messageToolCalls[messageIndex] = [];
  }
  messageToolCalls[messageIndex].push(toolCall);
}
