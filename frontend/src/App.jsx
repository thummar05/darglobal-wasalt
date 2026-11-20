import React, { useState, useEffect, useRef } from 'react';
import { Header } from './components/Header';
import { ChatMessage } from './components/ChatMessage';
import { ChatInput } from './components/ChatInput';
import { BrandLogo } from './components/BrandLogo';
import { useChatStream } from './hooks/useChatStream';
import { AlertCircle } from 'lucide-react';

export default function App() {
  const [globalLang, setGlobalLang] = useState('en');
  const isArabic = globalLang === 'ar';

  const {
    messages,
    isStreaming,
    error,
    sendMessage,
    stopStreaming,
    resetSession,
  } = useChatStream(globalLang);

  const [healthStatus, setHealthStatus] = useState(null);
  const messagesEndRef = useRef(null);
  const isStreamingRef = useRef(isStreaming);
  isStreamingRef.current = isStreaming;

  // Base API URL for health check
  const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || '';

  // Fetch health status on mount
  useEffect(() => {
    fetch(`${API_BASE_URL}/health`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => data && setHealthStatus(data))
      .catch(() => {});
  }, [API_BASE_URL]);

  // Auto-scroll: instant tracking during streaming for butter-smooth word typing, smooth on new message
  useEffect(() => {
    if (messagesEndRef.current) {
      if (isStreamingRef.current) {
        messagesEndRef.current.scrollIntoView({ behavior: 'auto' });
      } else {
        messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
      }
    }
  }, [messages]);

  const handleToggleLanguage = () => {
    const nextLang = isArabic ? 'en' : 'ar';
    setGlobalLang(nextLang);
    document.documentElement.dir = nextLang === 'ar' ? 'rtl' : 'ltr';
    document.documentElement.lang = nextLang;
  };

  return (
    <div
      dir={isArabic ? 'rtl' : 'ltr'}
      className={`min-h-screen flex flex-col bg-[#131314] text-[#E3E3E3] ${
        isArabic ? 'font-arabic' : 'font-sans'
      }`}
    >
      {/* Header */}
      <Header
        isArabic={isArabic}
        onToggleLanguage={handleToggleLanguage}
        onNewChat={resetSession}
        isStreaming={isStreaming}
        healthStatus={healthStatus}
      />

      {/* Main Chat Area */}
      <main className="flex-1 flex flex-col w-full max-w-4xl mx-auto px-4 pt-4 pb-2 overflow-y-auto">
        
        {/* Error Alert Bar */}
        {error && (
          <div className="mb-4 p-3 rounded-2xl bg-[#282a2c] border border-red-500/40 text-red-300 text-xs flex items-center justify-between shadow-sm">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
              <span>{error}</span>
            </div>
            <button
              onClick={() => resetSession()}
              className="text-[#8ab4f8] hover:underline font-medium ml-3"
            >
              Reset Session
            </button>
          </div>
        )}

        {/* Clean Empty State - Architectural Brand Mark */}
        {messages.length === 0 && (
          <div className="flex-1 flex flex-col items-start justify-center max-w-2xl mx-auto my-auto py-12 px-2">
            <div className="mb-4 p-3 rounded-2xl bg-[#1e1f20] border border-[#282a2c] shadow-sm">
              <BrandLogo className="w-10 h-10" />
            </div>

            <h1 className="text-4xl sm:text-5xl font-medium tracking-tight mb-2">
              <span className="gemini-gradient-text">
                {isArabic ? 'مرحباً بك،' : 'Hello,'}
              </span>
            </h1>

            <h2 className="text-2xl sm:text-4xl font-normal text-[#8e918f] leading-snug">
              {isArabic
                ? 'كيف يمكنني مساعدتك في استكشاف العقارات اليوم؟'
                : 'How can I help you explore real estate today?'}
            </h2>
          </div>
        )}

        {/* Message Thread */}
        {messages.length > 0 && (
          <div className="flex-1 space-y-1 py-4">
            {messages.map((msg, index) => (
              <ChatMessage
                key={msg.id || index}
                message={msg}
              />
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}

      </main>

      {/* Sticky Pill Input Container */}
      <div className="sticky bottom-0 z-30 bg-gradient-to-t from-[#131314] via-[#131314]/95 to-transparent pt-4">
        <ChatInput
          onSendMessage={sendMessage}
          isStreaming={isStreaming}
          onStopStreaming={stopStreaming}
          isArabicGlobal={isArabic}
        />
      </div>
    </div>
  );
}
