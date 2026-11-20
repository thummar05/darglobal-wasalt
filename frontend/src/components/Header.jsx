import React from 'react';
import { BrandLogo } from './BrandLogo';
import { Globe2, Plus } from 'lucide-react';

export function Header({
  isArabic,
  onToggleLanguage,
  onNewChat,
  isStreaming,
  healthStatus
}) {
  return (
    <header className="sticky top-0 z-40 w-full bg-[#131314]/95 backdrop-blur-md border-b border-[#282a2c]/60">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
        
        {/* Brand Mark & Title */}
        <div className="flex items-center space-x-3 rtl:space-x-reverse">
          <div className="flex items-center justify-center w-9 h-9 rounded-full bg-[#1e1f20] border border-[#282a2c] shadow-sm">
            <BrandLogo className="w-5 h-5" />
          </div>

          <div className="flex items-baseline space-x-2 rtl:space-x-reverse">
            <h1 className="text-base sm:text-lg font-medium text-[#e3e3e3] tracking-tight">
              DarGlobal <span className="text-[#8e918f] font-light">×</span> Wasalt
            </h1>
            <span className="text-[11px] font-medium text-[#8ab4f8] bg-[#1e1f20] px-2 py-0.5 rounded-full border border-[#282a2c]">
              Real Estate AI
            </span>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center space-x-2.5 rtl:space-x-reverse">
          
          {/* Language Toggle Pill */}
          <button
            onClick={onToggleLanguage}
            className="flex items-center space-x-1.5 rtl:space-x-reverse px-3 py-1.5 rounded-full bg-[#1e1f20] hover:bg-[#282a2c] text-[#c4c7c5] hover:text-[#e3e3e3] border border-[#282a2c] transition-all text-xs font-medium"
            title={isArabic ? 'Switch to English' : 'التحويل إلى العربية'}
          >
            <Globe2 className="w-3.5 h-3.5 text-[#8ab4f8]" />
            <span>{isArabic ? 'English' : 'العربية'}</span>
          </button>

          {/* New Chat Pill Button */}
          <button
            onClick={onNewChat}
            disabled={isStreaming}
            className="flex items-center space-x-1.5 rtl:space-x-reverse px-3.5 py-1.5 rounded-full bg-[#1e1f20] hover:bg-[#282a2c] text-[#e3e3e3] border border-[#282a2c] hover:border-[#8ab4f8]/40 transition-all text-xs font-medium disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
          >
            <Plus className="w-4 h-4 text-[#8ab4f8]" />
            <span className="hidden sm:inline">
              {isArabic ? 'محادثة جديدة' : 'New chat'}
            </span>
          </button>

        </div>

      </div>
    </header>
  );
}
