import { useState, useRef, useCallback, useEffect } from 'react';
import { generateSessionId, isArabicText } from '../utils/textUtils';

// Base API URL: support VITE_API_BASE_URL or VITE_API_URL, default to empty string for relative proxying
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || '';

export function useChatStream(initialLanguage = 'en') {
  const [messages, setMessages] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [sessionId, setSessionId] = useState(() => {
    return sessionStorage.getItem('realestate_session_id') || generateSessionId();
  });
  const [error, setError] = useState(null);
  const [currentRoute, setCurrentRoute] = useState(null);
  const [language, setLanguage] = useState(initialLanguage);

  const abortControllerRef = useRef(null);

  useEffect(() => {
    sessionStorage.setItem('realestate_session_id', sessionId);
  }, [sessionId]);

  const resetSession = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    const newSessionId = generateSessionId();
    setSessionId(newSessionId);
    sessionStorage.setItem('realestate_session_id', newSessionId);
    setMessages([]);
    setIsStreaming(false);
    setError(null);
    setCurrentRoute(null);
  }, []);

  const stopStreaming = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setIsStreaming(false);
    }
  }, []);

  const sendMessage = useCallback(async (queryText) => {
    if (!queryText || !queryText.trim() || isStreaming) return;

    const trimmedQuery = queryText.trim();
    const queryIsArabic = isArabicText(trimmedQuery);
    const activeLang = queryIsArabic ? 'ar' : language;

    // 1. Add User Message
    const userMessage = {
      id: `user_${Date.now()}`,
      role: 'user',
      content: trimmedQuery,
      timestamp: new Date().toISOString(),
      isArabic: queryIsArabic,
    };

    // 2. Add placeholder Bot Message
    const botMessageId = `bot_${Date.now()}`;
    const botPlaceholder = {
      id: botMessageId,
      role: 'assistant',
      content: '',
      tokens: [],
      sources: [],
      route: 'real_estate',
      isStreaming: true,
      timestamp: new Date().toISOString(),
      isArabic: queryIsArabic,
    };

    setMessages((prev) => [...prev, userMessage, botPlaceholder]);
    setIsStreaming(true);
    setError(null);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response = await fetch(`${API_BASE_URL}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify({
          query: trimmedQuery,
          session_id: sessionId,
          language: activeLang,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        let errorDetail = `HTTP Error ${response.status}: ${response.statusText}`;
        try {
          const errorJson = await response.json();
          if (errorJson.message) errorDetail = errorJson.message;
          else if (errorJson.detail) errorDetail = errorJson.detail;
        } catch {
          // Keep default message
        }
        throw new Error(errorDetail);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      let accumulatedAnswer = '';
      let accumulatedSources = [];
      let detectedRoute = 'real_estate';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Split by standard SSE double-newline
        const events = buffer.split('\n\n');
        // Keep the last partial event in the buffer
        buffer = events.pop() || '';

        for (const rawEvent of events) {
          if (!rawEvent.trim()) continue;

          let eventName = 'message';
          let eventData = '';

          const lines = rawEvent.split('\n');
          for (const line of lines) {
            if (line.startsWith('event:')) {
              eventName = line.replace('event:', '').trim();
            } else if (line.startsWith('data:')) {
              eventData = line.replace('data:', '').trim();
            }
          }

          if (!eventData) continue;

          try {
            const parsedData = JSON.parse(eventData);

            if (eventName === 'metadata') {
              detectedRoute = parsedData.route || 'real_estate';
              setCurrentRoute(detectedRoute);
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === botMessageId
                    ? { ...msg, route: detectedRoute, retrievedCount: parsedData.retrieved_count }
                    : msg
                )
              );
            } else if (eventName === 'token') {
              const tokenText = parsedData.token || '';
              accumulatedAnswer += tokenText;
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === botMessageId
                    ? {
                        ...msg,
                        content: accumulatedAnswer,
                        isArabic: isArabicText(accumulatedAnswer),
                      }
                    : msg
                )
              );
            } else if (eventName === 'sources') {
              accumulatedSources = parsedData.sources || [];
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === botMessageId
                    ? { ...msg, sources: accumulatedSources }
                    : msg
                )
              );
            } else if (eventName === 'error') {
              throw new Error(parsedData.message || 'Error received from streaming endpoint');
            } else if (eventName === 'done') {
              // Finalize message
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === botMessageId
                    ? {
                        ...msg,
                        content: accumulatedAnswer,
                        sources: accumulatedSources,
                        isStreaming: false,
                        isArabic: isArabicText(accumulatedAnswer),
                      }
                    : msg
                )
              );
            }
          } catch (jsonErr) {
            console.warn('Failed to parse SSE event data:', eventData, jsonErr);
          }
        }
      }

      // Final wrap up if done event was implicit
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === botMessageId ? { ...msg, isStreaming: false } : msg
        )
      );

    } catch (err) {
      if (err.name === 'AbortError') {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === botMessageId
              ? { ...msg, content: msg.content + ' [Generation stopped]', isStreaming: false }
              : msg
          )
        );
      } else {
        const errorMsg = err.message || 'Failed to communicate with the property advisory engine.';
        setError(errorMsg);
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === botMessageId
              ? {
                  ...msg,
                  content: msg.content || `⚠️ Service notice: ${errorMsg}`,
                  isStreaming: false,
                  hasError: true,
                }
              : msg
          )
        );
      }
    } finally {
      setIsStreaming(false);
      abortControllerRef.current = null;
    }
  }, [sessionId, isStreaming, language]);

  return {
    messages,
    isStreaming,
    sessionId,
    error,
    currentRoute,
    language,
    setLanguage,
    sendMessage,
    stopStreaming,
    resetSession,
  };
}
