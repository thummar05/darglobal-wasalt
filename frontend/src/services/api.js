/**
 * API service for Real Estate Chatbot
 * Handles SSE streaming from POST /chat, source citations, and session management.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || '';

/**
 * Generate or retrieve persistent session thread_id
 */
export function getOrCreateThreadId(forceNew = false) {
  if (forceNew) {
    const newId = `session_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
    localStorage.setItem('drg_thread_id', newId);
    return newId;
  }
  let threadId = localStorage.getItem('drg_thread_id');
  if (!threadId) {
    threadId = `session_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
    localStorage.setItem('drg_thread_id', threadId);
  }
  return threadId;
}

/**
 * Check backend health
 */
export async function checkBackendHealth() {
  try {
    const res = await fetch(`${API_BASE_URL}/health`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
      signal: AbortSignal.timeout(3000),
    });
    if (res.ok) {
      const data = await res.json();
      return { online: true, data };
    }
    return { online: false, error: `HTTP ${res.status}` };
  } catch (err) {
    return { online: false, error: err.message };
  }
}

/**
 * Stream chat response using SSE from POST /chat
 *
 * @param {Object} params
 * @param {string} params.query - User query text
 * @param {string} params.threadId - Conversational thread ID
 * @param {function} params.onToken - Callback for each streamed token (text chunk)
 * @param {function} params.onSources - Callback when sources/citations are received
 * @param {function} params.onComplete - Callback when stream completes
 * @param {function} params.onError - Callback on error
 * @param {AbortSignal} params.signal - Abort signal to cancel stream
 */
export async function streamChatQuery({
  query,
  threadId,
  onToken,
  onSources,
  onComplete,
  onError,
  signal,
}) {
  let fullAnswer = '';
  let collectedSources = [];

  try {
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream, application/json',
      },
      body: JSON.stringify({
        message: query,
        query: query,
        thread_id: threadId,
      }),
      signal,
    });

    if (!response.ok) {
      const errText = await response.text().catch(() => '');
      throw new Error(`Server returned error ${response.status}: ${errText || response.statusText}`);
    }

    const contentType = response.headers.get('content-type') || '';

    // Case 1: Standard JSON response (fallback if not streaming SSE)
    if (contentType.includes('application/json')) {
      const json = await response.json();
      const ans = json.answer || json.response || json.message || '';
      const sources = json.sources || [];
      if (ans && onToken) onToken(ans);
      if (sources.length > 0 && onSources) onSources(sources);
      if (onComplete) onComplete({ answer: ans, sources });
      return;
    }

    // Case 2: Server-Sent Events (SSE) Stream
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || ''; // Keep partial line in buffer

      for (const rawLine of lines) {
        const line = rawLine.trim();
        if (!line || line.startsWith(':')) continue; // Skip comments/keep-alive

        if (line.startsWith('data:')) {
          const dataContent = line.slice(5).trim();

          if (dataContent === '[DONE]') {
            continue;
          }

          // Try parsing JSON payload
          try {
            const parsed = JSON.parse(dataContent);

            // Handle token or chunk
            const token = parsed.token ?? parsed.chunk ?? parsed.delta ?? parsed.content ?? parsed.text;
            if (token !== undefined) {
              fullAnswer += token;
              if (onToken) onToken(token);
            }

            // Handle sources
            if (parsed.sources && Array.isArray(parsed.sources)) {
              collectedSources = parsed.sources;
              if (onSources) onSources(parsed.sources);
            }

            // Handle event types inside JSON
            if (parsed.event === 'sources' && parsed.data) {
              const srcList = Array.isArray(parsed.data) ? parsed.data : [parsed.data];
              collectedSources = srcList;
              if (onSources) onSources(srcList);
            } else if (parsed.event === 'token' && parsed.data) {
              fullAnswer += parsed.data;
              if (onToken) onToken(parsed.data);
            } else if (parsed.event === 'done') {
              // Completed event
            }
          } catch {
            // Not JSON; treat dataContent as raw token string
            fullAnswer += dataContent;
            if (onToken) onToken(dataContent);
          }
        } else if (line.startsWith('event:')) {
          // Event type marker handled on subsequent data line if needed
        }
      }
    }

    // Process any trailing bytes
    if (buffer.trim().startsWith('data:')) {
      const dataContent = buffer.trim().slice(5).trim();
      if (dataContent !== '[DONE]') {
        try {
          const parsed = JSON.parse(dataContent);
          const token = parsed.token ?? parsed.chunk ?? parsed.delta ?? parsed.content;
          if (token) {
            fullAnswer += token;
            if (onToken) onToken(token);
          }
          if (parsed.sources) {
            collectedSources = parsed.sources;
            if (onSources) onSources(parsed.sources);
          }
        } catch {
          fullAnswer += dataContent;
          if (onToken) onToken(dataContent);
        }
      }
    }

    if (onComplete) {
      onComplete({ answer: fullAnswer, sources: collectedSources });
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      if (onComplete) onComplete({ answer: fullAnswer, sources: collectedSources, aborted: true });
      return;
    }

    // If backend is unavailable (e.g. during frontend standalone dev before FastAPI is up),
    // provide an informative error or fallback
    if (onError) onError(err);
  }
}
