const BRIDGE = 'http://127.0.0.1:8765';
let streamAbort = null;
let reconnectTimer = null;

function notify(payload) {
  const title = payload.event === 'error' ? 'Tele Workspace • Error' : 'Tele Workspace';
  chrome.notifications.create(`tele-${Date.now()}`, {
    type: 'basic',
    title,
    message: String(payload.message || payload.event || 'มี event ใหม่').slice(0, 240),
    priority: payload.event === 'error' ? 2 : 0
  });
}

async function getToken() {
  const settings = await chrome.storage.local.get({ notifyToken: '' });
  return settings.notifyToken.trim();
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectStream();
  }, 5000);
}

async function connectStream() {
  if (streamAbort) streamAbort.abort();
  const token = await getToken();
  if (!token) return;
  streamAbort = new AbortController();
  try {
    const response = await fetch(`${BRIDGE}/events?token=${encodeURIComponent(token)}`, {
      headers: { Accept: 'text/event-stream' },
      signal: streamAbort.signal,
      cache: 'no-store'
    });
    if (!response.ok || !response.body) throw new Error(`bridge ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split('\n\n');
      buffer = chunks.pop() || '';
      for (const chunk of chunks) {
        const line = chunk.split('\n').find((item) => item.startsWith('data: '));
        if (line) {
          try { notify(JSON.parse(line.slice(6))); } catch (_) { /* ignore malformed event */ }
        }
      }
    }
  } catch (_) {
    // The CLI bridge may be stopped; retry quietly when it becomes available.
  } finally {
    streamAbort = null;
    scheduleReconnect();
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create('tele-reconnect', { periodInMinutes: 1 });
  connectStream();
});
chrome.runtime.onStartup.addListener(connectStream);
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'tele-reconnect') connectStream();
});
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.notifyToken) connectStream();
});
