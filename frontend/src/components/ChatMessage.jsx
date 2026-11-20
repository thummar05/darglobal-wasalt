import React, { useState } from 'react';
import { BrandLogo } from './BrandLogo';
import { User, Copy, Check, ExternalLink } from 'lucide-react';
import { isArabicText } from '../utils/textUtils';

// Inline ChatGPT-style streaming cursor
function StreamingCursor({ isArabic }) {
  return (
    <span
      className={`inline-block w-[7px] h-[1.15em] align-[-0.15em] bg-[#F0F0F0] rounded-[1px] ${
        isArabic ? 'mr-1' : 'ml-1'
      }`}
      style={{
        boxShadow: '0 0 8px rgba(255, 255, 255, 0.5)',
        animation: 'chatgpt-cursor-blink 0.75s infinite',
      }}
      aria-hidden="true"
    />
  );
}

// ChatGPT-style "Thinking..." bouncing dots indicator before first token arrives
function ThinkingIndicator({ isArabic }) {
  return (
    <div className="flex items-center gap-1.5 py-1.5 px-0.5 text-[#8e918f] select-none">
      <span className="inline-block w-2 h-2 rounded-full bg-[#8ab4f8] animate-bounce [animation-delay:-0.32s]" />
      <span className="inline-block w-2 h-2 rounded-full bg-[#8ab4f8] animate-bounce [animation-delay:-0.16s]" />
      <span className="inline-block w-2 h-2 rounded-full bg-[#8ab4f8] animate-bounce" />
      <span className="text-xs text-[#8e918f] ml-2.5 rtl:ml-0 rtl:mr-2.5 font-medium tracking-wide">
        {isArabic ? 'جاري التفكير والبحث...' : 'Thinking...'}
      </span>
    </div>
  );
}

// Tokenize and render inline formatting: bold, code, markdown links, and raw URLs
function parseInlineTokens(text) {
  if (!text) return [];

  const regex = /((?:https?:\/\/[^\s<>)"]+)|(?:\[[^\]]+\]\([^\)]+\))|(?:\*\*[^*]+\*\*)|(?:`[^`]+`))/g;
  const parts = [];
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'text', content: text.substring(lastIndex, match.index) });
    }
    const token = match[0];
    if (token.startsWith('http://') || token.startsWith('https://')) {
      let cleanUrl = token;
      let trailing = '';
      const punctMatch = cleanUrl.match(/[.,;:!?]+$/);
      if (punctMatch) {
        trailing = punctMatch[0];
        cleanUrl = cleanUrl.slice(0, -trailing.length);
      }
      parts.push({ type: 'link', url: cleanUrl, text: cleanUrl });
      if (trailing) {
        parts.push({ type: 'text', content: trailing });
      }
    } else if (token.startsWith('[') && token.includes('](')) {
      const linkMatch = token.match(/^\[(.*)\]\((.*)\)$/);
      if (linkMatch) {
        parts.push({ type: 'link', url: linkMatch[2], text: linkMatch[1] });
      } else {
        parts.push({ type: 'text', content: token });
      }
    } else if (token.startsWith('**') && token.endsWith('**')) {
      parts.push({ type: 'bold', content: token.slice(2, -2) });
    } else if (token.startsWith('`') && token.endsWith('`')) {
      parts.push({ type: 'code', content: token.slice(1, -1) });
    } else {
      parts.push({ type: 'text', content: token });
    }
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push({ type: 'text', content: text.substring(lastIndex) });
  }

  return parts;
}

function renderInline(text) {
  if (!text) return null;
  const tokens = parseInlineTokens(text);

  return tokens.map((tok, idx) => {
    if (tok.type === 'bold') {
      return (
        <strong key={idx} className="font-semibold text-white">
          {tok.content}
        </strong>
      );
    }
    if (tok.type === 'code') {
      return (
        <code
          key={idx}
          className="bg-[#282a2c] text-[#8ab4f8] px-1.5 py-0.5 rounded text-xs font-mono"
        >
          {tok.content}
        </code>
      );
    }
    if (tok.type === 'link') {
      return (
        <a
          key={idx}
          href={tok.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[#8ab4f8] hover:text-[#aecbfa] underline underline-offset-2 break-all inline-flex items-center gap-1 transition-colors"
        >
          <span>{tok.text}</span>
          <ExternalLink className="w-3 h-3 shrink-0 opacity-70 inline" />
        </a>
      );
    }
    return <React.Fragment key={idx}>{tok.content}</React.Fragment>;
  });
}

// Helpers for table parsing
function isTableDelimiter(line) {
  const trimmed = line.trim();
  return /^\|?(\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?$/.test(trimmed);
}

function isTableRow(line) {
  const trimmed = line.trim();
  return trimmed.includes('|') && !trimmed.startsWith('```');
}

function parseTableCells(rowStr) {
  let trimmed = rowStr.trim();
  if (trimmed.startsWith('|')) trimmed = trimmed.slice(1);
  if (trimmed.endsWith('|')) trimmed = trimmed.slice(0, -1);
  return trimmed.split('|').map((c) => c.trim());
}

// Split text into structural markdown blocks
function parseMarkdownBlocks(text) {
  if (!text) return [];
  const lines = text.split('\n');
  const blocks = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    // Check if table starts here
    if (isTableRow(trimmed) && i + 1 < lines.length && isTableDelimiter(lines[i + 1])) {
      const headers = parseTableCells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && isTableRow(lines[i])) {
        if (!isTableDelimiter(lines[i])) {
          const cells = parseTableCells(lines[i]);
          while (cells.length < headers.length) cells.push('');
          rows.push(cells);
        }
        i++;
      }
      blocks.push({ type: 'table', headers, rows });
      continue;
    }

    // Code block ```
    if (trimmed.startsWith('```')) {
      const lang = trimmed.slice(3).trim();
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++;
      blocks.push({ type: 'code', lang, content: codeLines.join('\n') });
      continue;
    }

    // Headings
    if (trimmed.startsWith('### ')) {
      blocks.push({ type: 'h3', content: trimmed.replace(/^###\s+/, '') });
      i++;
      continue;
    }
    if (trimmed.startsWith('## ')) {
      blocks.push({ type: 'h2', content: trimmed.replace(/^##\s+/, '') });
      i++;
      continue;
    }
    if (trimmed.startsWith('# ')) {
      blocks.push({ type: 'h1', content: trimmed.replace(/^#\s+/, '') });
      i++;
      continue;
    }

    // Bullet items (group consecutive)
    if (trimmed.startsWith('- ') || trimmed.startsWith('• ') || trimmed.startsWith('* ')) {
      const items = [];
      while (
        i < lines.length &&
        (lines[i].trim().startsWith('- ') ||
          lines[i].trim().startsWith('• ') ||
          lines[i].trim().startsWith('* '))
      ) {
        items.push(lines[i].trim().replace(/^[-•*]\s+/, ''));
        i++;
      }
      blocks.push({ type: 'bullet_list', items });
      continue;
    }

    // Numbered items (group consecutive)
    if (/^\d+\.\s/.test(trimmed)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ''));
        i++;
      }
      blocks.push({ type: 'numbered_list', items });
      continue;
    }

    // Empty line spacer
    if (!trimmed) {
      blocks.push({ type: 'spacer' });
      i++;
      continue;
    }

    // Regular paragraph
    blocks.push({ type: 'paragraph', content: line });
    i++;
  }

  return blocks;
}

export function ChatMessage({ message }) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';
  const isBot = !isUser;
  const isArabic = message.isArabic ?? isArabicText(message.content);
  const isStreaming = Boolean(message.isStreaming);
  const hasContent = Boolean(message.content && message.content.trim().length > 0);

  const handleCopy = () => {
    if (!message.content) return;
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const renderContentBlocks = (text) => {
    // If streaming and no content yet, show ChatGPT-style thinking indicator
    if (isStreaming && !hasContent) {
      return <ThinkingIndicator isArabic={isArabic} />;
    }

    if (!text) return null;
    const blocks = parseMarkdownBlocks(text);

    return blocks.map((block, idx) => {
      const isLastBlock = idx === blocks.length - 1;

      switch (block.type) {
        case 'table':
          return (
            <div key={idx}>
              <div className="my-3.5 overflow-x-auto rounded-xl border border-[#282a2c] bg-[#1a1b1d]/90 shadow-sm">
                <table className="min-w-full divide-y divide-[#282a2c] text-left rtl:text-right text-xs sm:text-sm">
                  <thead className="bg-[#242628]">
                    <tr>
                      {block.headers.map((h, hIdx) => (
                        <th
                          key={hIdx}
                          className="px-4 py-3 font-semibold text-[#e3e3e3] border-r border-[#282a2c] last:border-r-0 whitespace-nowrap tracking-wide"
                        >
                          {renderInline(h)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#282a2c]/60">
                    {block.rows.map((row, rIdx) => (
                      <tr
                        key={rIdx}
                        className="hover:bg-[#282a2c]/40 transition-colors odd:bg-[#1a1b1d]/40 even:bg-[#1f2023]/70"
                      >
                        {row.map((cell, cIdx) => (
                          <td
                            key={cIdx}
                            className="px-4 py-3 align-top text-[#c4c7c5] leading-relaxed border-r border-[#282a2c]/50 last:border-r-0"
                          >
                            {renderInline(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {isLastBlock && isStreaming && <StreamingCursor isArabic={isArabic} />}
            </div>
          );

        case 'code':
          return (
            <div key={idx}>
              <div className="my-3 rounded-xl border border-[#282a2c] bg-[#1e1f20] overflow-hidden text-xs sm:text-sm font-mono">
                {block.lang && (
                  <div className="px-4 py-1.5 bg-[#282a2c]/60 border-b border-[#282a2c] text-[#8e918f] text-xs">
                    {block.lang}
                  </div>
                )}
                <pre className="p-4 overflow-x-auto text-[#e3e3e3] leading-relaxed">
                  <code>{block.content}</code>
                </pre>
              </div>
              {isLastBlock && isStreaming && <StreamingCursor isArabic={isArabic} />}
            </div>
          );

        case 'h1':
          return (
            <h1 key={idx} className="text-xl font-bold text-white mt-5 mb-2">
              {renderInline(block.content)}
              {isLastBlock && isStreaming && <StreamingCursor isArabic={isArabic} />}
            </h1>
          );

        case 'h2':
          return (
            <h2 key={idx} className="text-lg font-semibold text-white mt-4 mb-1.5">
              {renderInline(block.content)}
              {isLastBlock && isStreaming && <StreamingCursor isArabic={isArabic} />}
            </h2>
          );

        case 'h3':
          return (
            <h3 key={idx} className="text-base font-semibold text-white mt-3.5 mb-1">
              {renderInline(block.content)}
              {isLastBlock && isStreaming && <StreamingCursor isArabic={isArabic} />}
            </h3>
          );

        case 'bullet_list':
          return (
            <ul
              key={idx}
              className="my-2 space-y-1.5 list-disc list-outside ml-5 rtl:mr-5 rtl:ml-0 text-[#c4c7c5] leading-relaxed"
            >
              {block.items.map((item, iIdx) => {
                const isLastItem = isLastBlock && iIdx === block.items.length - 1;
                return (
                  <li key={iIdx}>
                    {renderInline(item)}
                    {isLastItem && isStreaming && <StreamingCursor isArabic={isArabic} />}
                  </li>
                );
              })}
            </ul>
          );

        case 'numbered_list':
          return (
            <ol
              key={idx}
              className="my-2 space-y-1.5 list-decimal list-outside ml-5 rtl:mr-5 rtl:ml-0 text-[#c4c7c5] leading-relaxed"
            >
              {block.items.map((item, iIdx) => {
                const isLastItem = isLastBlock && iIdx === block.items.length - 1;
                return (
                  <li key={iIdx}>
                    {renderInline(item)}
                    {isLastItem && isStreaming && <StreamingCursor isArabic={isArabic} />}
                  </li>
                );
              })}
            </ol>
          );

        case 'spacer':
          return <div key={idx} className="h-2.5" />;

        case 'paragraph':
        default:
          return (
            <p key={idx} className="my-1.5 leading-relaxed text-[#e3e3e3]">
              {renderInline(block.content)}
              {isLastBlock && isStreaming && <StreamingCursor isArabic={isArabic} />}
            </p>
          );
      }
    });
  };

  return (
    <div
      dir={isArabic ? 'rtl' : 'ltr'}
      className={`w-full py-3 sm:py-4 px-2 sm:px-4 ${
        isUser ? 'flex justify-end' : 'flex justify-start'
      }`}
    >
      <div
        className={`flex items-start gap-3 sm:gap-4 max-w-3xl w-full ${
          isUser ? 'justify-end' : 'justify-start'
        }`}
      >
        {/* Assistant Avatar (Brand Architectural Logo) */}
        {isBot && (
          <div className="shrink-0 w-8 h-8 rounded-full bg-[#1e1f20] border border-[#282a2c] flex items-center justify-center mt-0.5 shadow-sm">
            <BrandLogo className="w-4 h-4" />
          </div>
        )}

        {/* Message Content Container */}
        <div
          className={`${
            isUser
              ? 'bg-[#282a2c] text-[#e3e3e3] rounded-3xl px-5 py-3 shadow-sm inline-block max-w-[85%]'
              : 'flex-1 min-w-0 text-[#e3e3e3]'
          }`}
        >
          {/* Text Content */}
          <div
            className={`text-sm sm:text-base leading-relaxed ${
              isArabic ? 'font-arabic text-base sm:text-lg' : 'font-sans'
            }`}
          >
            {renderContentBlocks(message.content)}
          </div>

          {/* Action Row for Assistant Messages (Copy) */}
          {isBot && message.content && !isStreaming && (
            <div className="flex items-center gap-2 mt-3 pt-1 text-[#8e918f]">
              <button
                onClick={handleCopy}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs hover:bg-[#1e1f20] hover:text-[#e3e3e3] transition-colors"
                title="Copy response"
              >
                {copied ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-[#8ab4f8]" />
                    <span className="text-[11px] text-[#8ab4f8]">Copied</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" />
                    <span className="text-[11px]">Copy</span>
                  </>
                )}
              </button>
            </div>
          )}
        </div>

        {/* User Avatar */}
        {isUser && (
          <div className="shrink-0 w-8 h-8 rounded-full bg-[#282a2c] border border-[#37393b] flex items-center justify-center mt-0.5 text-[#c4c7c5] shadow-sm">
            <User className="w-4 h-4" />
          </div>
        )}
      </div>
    </div>
  );
}
