import React, { useState, useRef, useEffect } from 'react';
import { ArrowUp, Square, Sparkles } from 'lucide-react';
import { isArabicText } from '../utils/textUtils';

export function ChatInput({ onSendMessage, isStreaming, onStopStreaming, isArabicGlobal }) {
  const [input, setInput] = useState('');
  const textareaRef = useRef(null);

  const inputIsArabic = input ? isArabicText(input) : isArabicGlobal;

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [input]);

  const handleSubmit = (e) => {
    e?.preventDefault();
    if (!input.trim() || isStreaming) return;
    onSendMessage(input.trim());
    setInput('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const hasInput = input.trim().length > 0;

  return (
    <div className="w-full max-w-3xl mx-auto px-4 pb-4">
      <form
        onSubmit={handleSubmit}
        className="relative rounded-[28px] bg-[#1e1f20] border border-[#282a2c] focus-within:border-[#37393b] focus-within:bg-[#202124] transition-all shadow-lg p-2.5 sm:p-3"
      >
        <div className="flex items-end gap-2.5">
          
          {/* Text Area */}
          <textarea
            ref={textareaRef}
            dir={inputIsArabic ? 'rtl' : 'ltr'}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              inputIsArabic
                ? 'اسأل عن مشاريع دار غلوبال، الفلل، الشقق، أو الأسعار...'
                : 'Ask DarGlobal & Wasalt Real Estate...'
            }
            className={`flex-1 bg-transparent text-[#e3e3e3] placeholder-[#8e918f] resize-none outline-none text-sm sm:text-base leading-relaxed max-h-44 py-1 px-3 ${
              inputIsArabic ? 'font-arabic' : 'font-sans'
            }`}
          />

          {/* Action Button: Send (Gemini Arrow Up) or Stop (Square) */}
          <div className="shrink-0 flex items-center mb-0.5">
            {isStreaming ? (
              <button
                type="button"
                onClick={onStopStreaming}
                className="flex items-center justify-center w-9 h-9 rounded-full bg-[#282a2c] text-[#8ab4f8] hover:bg-[#37393b] transition-all"
                title="Stop response"
              >
                <Square className="w-4 h-4 fill-current" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!hasInput}
                className={`flex items-center justify-center w-9 h-9 rounded-full transition-all ${
                  hasInput
                    ? 'bg-[#e3e3e3] text-[#131314] hover:bg-white shadow-sm cursor-pointer'
                    : 'bg-[#282a2c] text-[#8e918f] opacity-40 cursor-not-allowed'
                }`}
                title={inputIsArabic ? 'إرسال' : 'Send'}
              >
                <ArrowUp className="w-4 h-4 stroke-[2.5]" />
              </button>
            )}
          </div>
        </div>
      </form>

      {/* Subtle Gemini Disclaimer Underneath */}
      <div className="text-center mt-2.5">
        <p className="text-[11px] text-[#8e918f]">
          {inputIsArabic
            ? 'المستشار العقاري الذكي قد يعرض معلومات غير دقيقة، يُرجى التحقق من القوائم الرسمية.'
            : 'DarGlobal & Wasalt AI may display inaccurate info, so verify with official listings.'}
        </p>
      </div>
    </div>
  );
}
