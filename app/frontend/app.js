/* ─── Storage schema ─────────────────────────────────────
   localStorage key: 'rag_store'
   {
     currentId: "uuid",
     sessions: {
       "uuid": {
         id, title, sessionId, documentIds, docStatuses,
         messages: [{role, text, citations, confidence}],
         lastActiveAt
       }
     }
   }
──────────────────────────────────────────────────────── */

const STORE_KEY  = 'rag_store';
const AUTH_KEY   = 'rag_auth';   // { token, user_id, email }

// Markdown renderer — GFM + soft line breaks
marked.use({ gfm: true, breaks: true });
function renderMarkdown(text) {
  return DOMPurify.sanitize(marked.parse(text || ''));
}

/* ─── Auth helpers ───────────────────────────────────── */
function getAuth()  { try { return JSON.parse(localStorage.getItem(AUTH_KEY)) || null; } catch { return null; } }
function setAuth(a) { localStorage.setItem(AUTH_KEY, JSON.stringify(a)); }
function clearAuth(){ localStorage.removeItem(AUTH_KEY); }

function switchAuthTab(tab) {
  document.getElementById('loginForm').classList.toggle('hidden', tab !== 'login');
  document.getElementById('registerForm').classList.toggle('hidden', tab !== 'register');
  document.getElementById('tabLogin').classList.toggle('active', tab === 'login');
  document.getElementById('tabRegister').classList.toggle('active', tab === 'register');
  const _le = document.getElementById('loginError');
  _le.textContent = ''; _le.classList.add('hidden');
  const _re = document.getElementById('registerError');
  _re.textContent = ''; _re.classList.add('hidden');
}

/* ─── Google OAuth ───────────────────────────────────── */
function handleGoogleLogin() {
  window.location.href = '/api/v1/auth/google';
}

/* ─── Forgot password modal ──────────────────────────── */
function showForgotPassword(e) {
  if (e) e.preventDefault();
  document.getElementById('forgotModal').classList.remove('hidden');
  document.getElementById('forgotEmail').value = '';
  document.getElementById('forgotError').textContent = '';
  document.getElementById('forgotError').classList.add('hidden');
  document.getElementById('forgotSuccess').textContent = '';
  document.getElementById('forgotSuccess').classList.add('hidden');
  document.getElementById('forgotBtn').disabled = false;
  document.getElementById('forgotBtn').textContent = 'Send Reset Link';
  setTimeout(() => document.getElementById('forgotEmail').focus(), 50);
}

function hideForgotPassword() {
  document.getElementById('forgotModal').classList.add('hidden');
}

function hideForgotOnBackdrop(e) {
  if (e.target === document.getElementById('forgotModal')) hideForgotPassword();
}

async function handleForgotPassword(e) {
  e.preventDefault();
  const btn = document.getElementById('forgotBtn');
  const errEl = document.getElementById('forgotError');
  const successEl = document.getElementById('forgotSuccess');
  errEl.textContent = '';
  errEl.classList.add('hidden');
  successEl.textContent = '';
  successEl.classList.add('hidden');
  btn.disabled = true;
  btn.textContent = 'Sending…';
  try {
    await apiFetch('/api/v1/auth/forgot-password', 'POST', {
      email: document.getElementById('forgotEmail').value,
    });
    successEl.textContent = 'If that email is registered, a reset link has been sent.';
    successEl.classList.remove('hidden');
    btn.textContent = 'Sent';
  } catch (err) {
    if (err.message.includes('not configured')) {
      errEl.textContent = 'Email service is not configured on this server.';
    } else {
      errEl.textContent = err.message;
    }
    errEl.classList.remove('hidden');
    btn.disabled = false;
    btn.textContent = 'Send Reset Link';
  }
}

async function handleLogin(e) {
  e.preventDefault();
  const btn = document.getElementById('loginBtn');
  const errEl = document.getElementById('loginError');
  errEl.textContent = ''; errEl.classList.add('hidden');
  btn.disabled = true;
  btn.textContent = 'Signing in…';
  try {
    const data = await apiFetch('/api/v1/auth/login', 'POST', {
      email: document.getElementById('loginEmail').value,
      password: document.getElementById('loginPassword').value,
    });
    setAuth({ token: data.access_token, user_id: data.user_id, email: data.email, name: data.name || '' });
    showMainApp();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Sign In';
  }
}

async function handleRegister(e) {
  e.preventDefault();
  const btn = document.getElementById('registerBtn');
  const errEl = document.getElementById('registerError');
  errEl.textContent = ''; errEl.classList.add('hidden');
  btn.disabled = true;
  btn.textContent = 'Creating…';
  try {
    const data = await apiFetch('/api/v1/auth/register', 'POST', {
      email: document.getElementById('regEmail').value,
      password: document.getElementById('regPassword').value,
    });
    setAuth({ token: data.access_token, user_id: data.user_id, email: data.email, name: data.name || '' });
    showMainApp();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Create Account';
  }
}

async function handleLogout() {
  try {
    const auth = getAuth();
    if (auth && auth.token) {
      await apiFetch('/api/v1/auth/logout', 'POST').catch(() => {});
    }
  } finally {
    clearAuth();
    document.getElementById('mainApp').style.display = 'none';
    document.getElementById('authOverlay').style.display = 'flex';
  }
}

async function showMainApp() {
  const auth = getAuth();
  document.getElementById('authOverlay').style.display = 'none';
  document.getElementById('mainApp').style.display = 'flex';
  if (auth) {
    document.getElementById('footerUser').textContent = auth.name || auth.email || '';
    const initial = (auth.name || auth.email || 'U').charAt(0).toUpperCase();
    const avatarEl = document.getElementById('footerAvatar');
    if (avatarEl) avatarEl.textContent = initial;
  }
  // Hydrate sidebar with user's existing documents from the server
  if (auth && auth.token) await refreshDocStatuses();
}

/* ─── Persistent store helpers ──────────────────────── */
function getStore() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY)) || { currentId: null, sessions: {} }; }
  catch (_) { return { currentId: null, sessions: {} }; }
}
function setStore(s) {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(s)); } catch (_) {}
}
function saveCurrentSession() {
  if (!state.id) return;
  const s = getStore();
  s.sessions[state.id] = {
    id:           state.id,
    title:        state.title,
    sessionId:    state.sessionId,
    documentIds:  state.documentIds,
    docStatuses:  state.docStatuses,
    messages:     state.messages,
    lastActiveAt: new Date().toISOString(),
  };
  s.currentId = state.id;
  setStore(s);
}

/* ─── Active state (current chat) ───────────────────── */
const state = {
  id:          null,   // local UUID for this chat entry
  title:       'New Chat',
  sessionId:   null,   // backend session ID
  documentIds: [],
  isLoading:   false,
  docStatuses: {},
  messages:    [],     // {role, text, citations, confidence}
};

function newLocalId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

/* ─── DOM refs ──────────────────────────────────────── */
const $ = id => document.getElementById(id);
const chatMessages    = $('chatMessages');
const messageInput    = $('messageInput');
const sendBtn         = $('sendBtn');
const fileInput       = $('fileInput');
const uploadZone      = $('uploadZone');
const docList         = $('docList');
const chatHistoryList = $('chatHistoryList');
const inputHint       = $('inputHint');

/* ─── Bootstrap ─────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', async () => {
  // Handle Google OAuth callback: ?access_token=...&user_id=...&email=...
  const urlParams = new URLSearchParams(window.location.search);
  const oauthToken = urlParams.get('access_token');
  const authError  = urlParams.get('auth_error');
  if (oauthToken) {
    setAuth({
      token:   oauthToken,
      user_id: urlParams.get('user_id') || '',
      email:   urlParams.get('email') || '',
      name:    urlParams.get('name') || '',
    });
    // Clean URL without reload
    history.replaceState({}, '', window.location.pathname);
  } else if (authError) {
    history.replaceState({}, '', window.location.pathname);
  }

  // Show auth overlay or main app depending on stored token
  const auth = getAuth();
  if (auth && auth.token) {
    showMainApp();
  } else {
    // Auth overlay is visible by default
  }

  fileInput.addEventListener('change', e => {
    const file = e.target.files[0];
    if (file) handleUpload(file);
    fileInput.value = '';
  });
  uploadZone.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('drag-over'); });
  uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
  uploadZone.addEventListener('drop', e => {
    e.preventDefault();
    uploadZone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file && file.type === 'application/pdf') handleUpload(file);
    else showToast('Please drop a PDF file.', 'error');
  });
  uploadZone.addEventListener('click', e => { if (e.target === uploadZone) fileInput.click(); });

  if (auth && auth.token) {
    await restoreLastSession();
    renderChatHistory();
  }
});

/* ─── Doc library helpers ───────────────────────────────── */

// Fetch the current user's document library from the server and update state.
async function refreshDocStatuses() {
  try {
    const data = await apiFetch('/api/v1/documents');
    const docs = data.documents || [];
    state.docStatuses = {};
    state.documentIds = [];
    for (const doc of docs) {
      state.documentIds.push(doc.document_id);
      state.docStatuses[doc.document_id] = {
        name:   doc.filename,
        status: doc.status,
        chunks: doc.total_chunks,
        pages:  doc.page_count,
      };
    }
    renderDocList();
  } catch (_) {}
}

// When a session expires, create a new one — the server auto-attaches
// the user's ready documents so no re-upload is needed.
async function autoRenewSession() {
  try {
    await refreshDocStatuses();
    const hasReady = Object.values(state.docStatuses).some(d => d.status === 'ready');
    if (!hasReady) {
      messageInput.placeholder = 'Upload a PDF to start chatting…';
      return;
    }
    const sess = await apiFetch('/api/v1/sessions', 'POST', {});
    state.sessionId = sess.session_id;
    state.documentIds = sess.document_ids;
    saveCurrentSession();
    if (sess.document_ids.length > 0) {
      enableChat();
      if (state.messages.length > 0) {
        showToast('Session renewed — your documents are still available.', 'success');
      }
    }
  } catch (_) {}
}

/* ─── Session restore ───────────────────────────────── */
async function restoreLastSession() {
  const s = getStore();
  if (!s.currentId || !s.sessions[s.currentId]) return;
  await loadSession(s.currentId, false);
}

async function loadSession(localId, saveBeforeSwitch = true) {
  if (saveBeforeSwitch && state.id && state.sessionId) saveCurrentSession();

  const s = getStore();
  const saved = s.sessions[localId];
  if (!saved) return;

  // Verify backend session still alive
  let backendAlive = false;
  if (saved.sessionId) {
    try {
      await apiFetch(`/api/v1/sessions/${saved.sessionId}`);
      backendAlive = true;
    } catch (_) { backendAlive = false; }
  }

  // Load into active state
  state.id          = saved.id;
  state.title       = saved.title;
  state.sessionId   = backendAlive ? saved.sessionId : null;
  state.documentIds = backendAlive ? (saved.documentIds || []) : [];
  state.docStatuses = saved.docStatuses || {};
  state.messages    = saved.messages    || [];

  // Re-render UI
  chatMessages.innerHTML = '';
  if (state.messages.length === 0) {
    chatMessages.appendChild(buildWelcomeEl());
  } else {
    hideWelcome();
    for (const msg of state.messages) {
      if (msg.role === 'user') renderUserMessage(msg.text);
      else renderAssistantMessage(msg.text, msg.citations || [], msg.confidence ?? null);
    }
    scrollToBottom();
  }

  renderDocList();
  renderChatHistory();

  if (backendAlive && Object.values(state.docStatuses).some(d => d.status === 'ready')) {
    enableChat();
  } else if (!backendAlive) {
    // Session expired — try to auto-renew using user's existing documents
    await autoRenewSession();
  }
}

/* ─── New Chat ──────────────────────────────────────── */
function newChat() {
  // Save current chat to history before switching
  if (state.id && state.sessionId) saveCurrentSession();

  // Reset active state
  state.id          = newLocalId();
  state.title       = 'New Chat';
  state.sessionId   = null;
  state.documentIds = [];
  state.docStatuses = {};
  state.messages    = [];
  state.isLoading   = false;

  // Update store's currentId
  const s = getStore();
  s.currentId = state.id;
  setStore(s);

  // Reset UI
  chatMessages.innerHTML = '';
  chatMessages.appendChild(buildWelcomeEl());
  docList.innerHTML = '';
  messageInput.disabled = true;
  sendBtn.disabled = true;
  messageInput.placeholder = 'Upload a PDF to start chatting…';
  inputHint.textContent = 'Responses are grounded in your uploaded document.';

  renderChatHistory();
}

/* ─── Sidebar: chat history ─────────────────────────── */
function renderChatHistory() {
  chatHistoryList.innerHTML = '';
  const s = getStore();
  const sessions = Object.values(s.sessions).sort(
    (a, b) => new Date(b.lastActiveAt) - new Date(a.lastActiveAt)
  );

  if (sessions.length === 0) {
    chatHistoryList.innerHTML = '<div class="no-history">No chats yet</div>';
    return;
  }

  for (const sess of sessions) {
    const isActive = sess.id === state.id;
    const preview  = sess.messages.length > 0
      ? sess.messages.find(m => m.role === 'user')?.text?.slice(0, 45) || sess.title
      : 'No messages yet';
    const timeStr  = relativeTime(sess.lastActiveAt);

    const item = document.createElement('div');
    item.className = 'chat-history-item' + (isActive ? ' active' : '');
    item.innerHTML = `
      <div class="chi-icon">💬</div>
      <div class="chi-body">
        <div class="chi-title">${escHtml(sess.title)}</div>
        <div class="chi-preview">${escHtml(preview)}</div>
        <div class="chi-time">${timeStr}</div>
      </div>
      <button class="chi-delete" title="Delete" onclick="deleteSession(event,'${sess.id}')">✕</button>`;
    item.addEventListener('click', () => loadSession(sess.id));
    chatHistoryList.appendChild(item);
  }
}

function deleteSession(e, localId) {
  e.stopPropagation();
  const s = getStore();
  delete s.sessions[localId];
  if (s.currentId === localId) {
    s.currentId = null;
    newChat();
  }
  setStore(s);
  renderChatHistory();
}

/* ─── Upload flow ───────────────────────────────────── */
async function handleUpload(file) {
  if (!file.name.endsWith('.pdf')) {
    showToast('Only PDF files are supported.', 'error');
    return;
  }
  showToast('Uploading PDF…');

  try {
    // Ensure we have an active local chat entry
    if (!state.id) {
      state.id = newLocalId();
      const s = getStore();
      s.currentId = state.id;
      setStore(s);
    }

    // Create backend session if needed
    if (!state.sessionId) {
      const sess = await apiFetch('/api/v1/sessions', 'POST', {});
      state.sessionId = sess.session_id;
    }

    // Set title from filename if still default
    if (state.title === 'New Chat') {
      state.title = file.name.replace(/\.pdf$/i, '');
    }

    // Upload file
    const formData = new FormData();
    formData.append('file', file);
    formData.append('session_id', state.sessionId);
    const uploadHeaders = {};
    const authData = getAuth();
    if (authData && authData.token) uploadHeaders['Authorization'] = `Bearer ${authData.token}`;
    const resp = await fetch('/api/v1/documents/upload', { method: 'POST', headers: uploadHeaders, body: formData });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err?.error?.message || `Upload failed (${resp.status})`);
    }
    const data = await resp.json();
    const docId = data.document_id;

    state.documentIds.push(docId);
    state.docStatuses[docId] = { name: file.name, status: 'processing' };
    renderDocList();
    saveCurrentSession();
    renderChatHistory();
    showToast('Uploaded — processing…');

    await pollDocument(docId);

  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function pollDocument(docId) {
  for (let i = 0; i < 40; i++) {
    await sleep(3000);
    try {
      const doc = await apiFetch(`/api/v1/documents/${docId}`);
      state.docStatuses[docId] = {
        name:   state.docStatuses[docId]?.name || docId,
        status: doc.status,
        chunks: doc.total_chunks,
        pages:  doc.page_count,
      };
      renderDocList();
      saveCurrentSession();
      if (doc.status === 'ready') {
        enableChat();
        showToast(`Ready — ${doc.total_chunks} chunk(s) indexed.`, 'success');
        return;
      }
      if (doc.status === 'error') {
        showToast('Processing failed. Try another file.', 'error');
        return;
      }
    } catch (_) {}
  }
  showToast('Processing is taking long. Check server logs.', 'error');
}

/* ─── Chat ──────────────────────────────────────────── */
async function sendMessage() {
  const text = messageInput.value.trim();
  if (!text || state.isLoading) return;
  if (!state.sessionId || state.documentIds.length === 0) {
    showToast('Upload a document first.', 'error');
    return;
  }

  hideWelcome();
  renderUserMessage(text);
  state.messages.push({ role: 'user', text });
  saveCurrentSession();
  renderChatHistory();

  messageInput.value = '';
  autoResize(messageInput);
  setLoading(true);

  const assistantRow = createAssistantPlaceholder();
  const contentEl    = assistantRow.querySelector('.msg-content');

  try {
    const { fullText, citations, confidence } = await streamQuery(text, contentEl, assistantRow);
    state.messages.push({ role: 'assistant', text: fullText, citations, confidence });
    saveCurrentSession();
    renderChatHistory();
  } catch (err) {
    // Clean up thinking dots if still visible
    const dots = assistantRow.querySelector('#thinkingDots');
    if (dots) dots.remove();
    contentEl.style.display = '';
    contentEl.classList.remove('typing-cursor');
    contentEl.classList.add('msg-error');
    contentEl.textContent = `Error: ${err.message}`;
  } finally {
    setLoading(false);
    scrollToBottom();
  }
}

async function streamQuery(question, contentEl, rowEl) {
  const payload = {
    question,
    session_id:   state.sessionId,
    document_ids: state.documentIds,
  };
  const streamAuth = getAuth();
  const streamHeaders = { 'Content-Type': 'application/json' };
  if (streamAuth && streamAuth.token) streamHeaders['Authorization'] = `Bearer ${streamAuth.token}`;
  const resp = await fetch('/api/v1/query/stream', {
    method: 'POST', headers: streamHeaders,
    body: JSON.stringify(payload),
  });
  if (resp.status === 401) {
    clearAuth();
    document.getElementById('mainApp').style.display = 'none';
    document.getElementById('authOverlay').style.display = 'flex';
    throw new Error('Your login has expired — please sign in again.');
  }
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err?.detail || err?.error?.message || `Server error (${resp.status})`);
  }

  const reader    = resp.body.getReader();
  const decoder   = new TextDecoder();
  const dotsEl    = rowEl.querySelector('#thinkingDots');
  let buffer      = '';
  let fullText    = '';
  let eventName   = '';
  let citations   = [];
  let confidence  = null;
  let firstToken  = true;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split(/\n\n/);
    buffer = parts.pop();                          // keep incomplete last chunk

    for (const part of parts) {
      for (const line of part.split('\n')) {
        if (line.startsWith('event: ')) {
          eventName = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          const raw = line.slice(6).trim();
          if (!raw) continue;
          let data;
          try { data = JSON.parse(raw); } catch { continue; }

          if (eventName === 'token') {
            const delta = data.text || '';
            if (!delta) continue;

            // First token: hide thinking dots, show content area with cursor
            if (firstToken) {
              firstToken = false;
              if (dotsEl) dotsEl.remove();
              contentEl.style.display = '';
              contentEl.classList.add('typing-cursor', 'markdown-body');
            }

            // Append only the new delta as raw text during streaming
            contentEl.appendChild(document.createTextNode(delta));
            fullText += delta;
            scrollToBottom();

          } else if (eventName === 'citation') {
            citations = data.citations || [];
          } else if (eventName === 'done') {
            confidence = data.confidence ?? null;
          } else if (eventName === 'error') {
            throw new Error(data.message || 'Stream error');
          }
        }
      }
    }
  }

  // Stream finished — remove cursor, render accumulated markdown
  contentEl.classList.remove('typing-cursor');
  if (!firstToken && fullText) {
    contentEl.innerHTML = renderMarkdown(fullText);
  }

  // If no tokens ever arrived (empty response), clean up dots and show fallback
  if (firstToken) {
    if (dotsEl) dotsEl.remove();
    contentEl.style.display = '';
    contentEl.textContent = '(No response)';
  }

  const bubble = rowEl.querySelector('.msg-bubble');
  if (citations.length > 0) bubble.appendChild(buildCitationsEl(citations));
  if (confidence !== null) bubble.appendChild(buildConfidenceEl(confidence));
  return { fullText: fullText || '(No response)', citations, confidence };
}

/* ─── DOM builders ──────────────────────────────────── */
function renderUserMessage(text) {
  const row = document.createElement('div');
  row.className = 'msg-row user';
  row.innerHTML = `<div class="msg-avatar">U</div><div class="msg-bubble"><div class="msg-content">${escHtml(text)}</div></div>`;
  chatMessages.appendChild(row);
  scrollToBottom();
}

function renderAssistantMessage(text, citations, confidence) {
  const row    = document.createElement('div');
  row.className = 'msg-row assistant';
  const bubble  = document.createElement('div');
  bubble.className = 'msg-bubble';
  const content = document.createElement('div');
  content.className = 'msg-content markdown-body';
  if (text && text !== '(No response)') {
    content.innerHTML = renderMarkdown(text);
  } else {
    content.textContent = '(No response)';
  }
  bubble.appendChild(content);
  if (citations && citations.length > 0) bubble.appendChild(buildCitationsEl(citations));
  if (confidence !== null && confidence !== undefined) bubble.appendChild(buildConfidenceEl(confidence));
  row.innerHTML = `<div class="msg-avatar">AI</div>`;
  row.appendChild(bubble);
  chatMessages.appendChild(row);
}

function createAssistantPlaceholder() {
  const row = document.createElement('div');
  row.className = 'msg-row assistant';
  row.innerHTML = `
    <div class="msg-avatar">AI</div>
    <div class="msg-bubble">
      <div class="thinking-dots" id="thinkingDots">
        <span></span><span></span><span></span>
      </div>
      <div class="msg-content" style="display:none"></div>
    </div>`;
  chatMessages.appendChild(row);
  scrollToBottom();
  return row;
}

function buildWelcomeEl() {
  const el = document.createElement('div');
  el.id = 'welcomeScreen';
  el.className = 'welcome';
  el.innerHTML = `
    <div class="welcome-icon">
      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">
        <circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/>
      </svg>
    </div>
    <h2>Ask anything about your PDF</h2>
    <p>Upload a document using the sidebar, then type your question below.</p>
    <div class="example-queries">
      <div class="example-chip" onclick="useExample(this)">Summarise this document</div>
      <div class="example-chip" onclick="useExample(this)">What are the key findings?</div>
      <div class="example-chip" onclick="useExample(this)">List the main topics covered</div>
    </div>`;
  return el;
}

function buildCitationsEl(citations) {
  const wrap   = document.createElement('div');
  wrap.className = 'citations';
  const toggle = document.createElement('button');
  toggle.className = 'citations-toggle';
  toggle.innerHTML = `<span>📎</span> ${citations.length} Source${citations.length > 1 ? 's' : ''}`;
  const list   = document.createElement('div');
  list.className = 'citations-list collapsed';
  citations.forEach((c, i) => {
    const pages = (c.page_numbers || []).join(', ');
    const item  = document.createElement('div');
    item.className = 'citation-item';
    item.innerHTML = `
      <div class="citation-source">Source ${i+1} — ${escHtml(c.document_name)}${pages ? `, p. ${pages}` : ''}</div>
      <div class="citation-excerpt">"${escHtml((c.excerpt||'').trim())}"</div>`;
    list.appendChild(item);
  });
  toggle.addEventListener('click', () => {
    const col = list.classList.toggle('collapsed');
    toggle.innerHTML = `<span>📎</span> ${citations.length} Source${citations.length > 1 ? 's' : ''} ${col ? '' : '▲'}`;
  });
  wrap.appendChild(toggle);
  wrap.appendChild(list);
  return wrap;
}

function buildConfidenceEl(score) {
  const pct   = Math.round(score * 100);
  const cls   = score >= 0.65 ? 'conf-high' : score >= 0.4 ? 'conf-medium' : 'conf-low';
  const label = score >= 0.65 ? 'High' : score >= 0.4 ? 'Medium' : 'Low';
  const el    = document.createElement('div');
  el.className = 'confidence-badge';
  el.innerHTML = `<span class="conf-dot ${cls}"></span> Confidence: ${label} (${pct}%)`;
  return el;
}

/* ─── Doc list ──────────────────────────────────────── */
function renderDocList() {
  docList.innerHTML = '';
  for (const [id, info] of Object.entries(state.docStatuses)) {
    const card = document.createElement('div');
    card.className = 'doc-card';
    let badge = info.status === 'processing'
      ? `<span class="doc-status-badge processing"><span class="spinner"></span> Processing</span>`
      : info.status === 'ready'
      ? `<span class="doc-status-badge ready">✓ Ready · ${info.chunks||'?'} chunks</span>`
      : `<span class="doc-status-badge error">✗ Error</span>`;
    card.innerHTML = `
      <div class="doc-card-icon">📄</div>
      <div class="doc-card-info">
        <div class="doc-card-name" title="${escHtml(info.name)}">${escHtml(info.name)}</div>
        <div class="doc-card-meta">${info.pages ? `${info.pages} page(s)` : ''}</div>
        ${badge}
      </div>`;
    docList.appendChild(card);
  }
}

/* ─── UI helpers ────────────────────────────────────── */
function enableChat() {
  messageInput.disabled = false;
  sendBtn.disabled      = false;
  messageInput.placeholder = 'Ask a question about your document…';
  inputHint.textContent = 'Responses are grounded in your uploaded document.';
}

function hideWelcome() {
  const ws = document.getElementById('welcomeScreen');
  if (ws) ws.style.display = 'none';
}

function setLoading(on) {
  state.isLoading       = on;
  sendBtn.disabled      = on;
  messageInput.disabled = on;
  if (!on) {
    const hasReady = Object.values(state.docStatuses).some(d => d.status === 'ready');
    messageInput.disabled = !hasReady;
    sendBtn.disabled      = !hasReady;
  }
}

function scrollToBottom() { chatMessages.scrollTop = chatMessages.scrollHeight; }

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}

function useExample(el) {
  if (state.documentIds.length === 0) { showToast('Upload a PDF first.', 'error'); return; }
  messageInput.value = el.textContent;
  messageInput.focus();
}

/* ─── Toast ─────────────────────────────────────────── */
let _toastTimer = null;
function showToast(msg, type = '') {
  const toast = $('toast');
  toast.textContent = msg;
  toast.className   = `toast show ${type}`;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { toast.className = 'toast'; }, 3000);
}

/* ─── API helper ─────────────────────────────────────── */
async function apiFetch(path, method = 'GET', body = undefined) {
  const auth = getAuth();
  const headers = { 'Content-Type': 'application/json' };
  if (auth && auth.token) headers['Authorization'] = `Bearer ${auth.token}`;
  const opts = { method, headers };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const resp = await fetch(path, opts);
  if (resp.status === 401) {
    // Token expired or invalid — force re-login
    clearAuth();
    document.getElementById('mainApp').style.display = 'none';
    document.getElementById('authOverlay').style.display = 'flex';
    throw new Error('Your login has expired — please sign in again.');
  }
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err?.detail || err?.error?.message || `Request failed (${resp.status})`);
  }
  return resp.json();
}

/* ─── Utilities ─────────────────────────────────────── */
function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function relativeTime(iso) {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const mins  = Math.floor(diff / 60000);
  if (mins < 1)   return 'just now';
  if (mins < 60)  return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)   return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}
