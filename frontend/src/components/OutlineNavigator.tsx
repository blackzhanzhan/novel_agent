import React, { useMemo } from 'react';
import { useUiCopy } from '../i18n/ui';

interface OutlineItem {
    id: string;
    level: number;
    label: string;
}

interface OutlineNavigatorProps {
    content: string;
    activeFile: string;
}

function slugify(input: string): string {
    return input
        .trim()
        .toLowerCase()
        .replace(/[^\p{L}\p{N}\s-]/gu, '')
        .replace(/\s+/g, '-')
        .replace(/-+/g, '-')
        .replace(/^-|-$/g, '');
}

function parseOutline(content: string): OutlineItem[] {
    if (!content) return [];
    const seen = new Map<string, number>();
    return content
        .split('\n')
        .map((line) => line.match(/^(#{1,4})\s+(.+?)\s*$/))
        .filter((match): match is RegExpMatchArray => Boolean(match))
        .map((match) => {
            const level = match[1].length;
            const label = match[2].trim();
            const baseId = slugify(label) || `heading-${level}`;
            const count = seen.get(baseId) || 0;
            seen.set(baseId, count + 1);
            return {
                id: count === 0 ? baseId : `${baseId}-${count + 1}`,
                level,
                label,
            };
        });
}

export const OutlineNavigator: React.FC<OutlineNavigatorProps> = ({ content, activeFile }) => {
    const copy = useUiCopy();
    const outlineItems = useMemo(() => parseOutline(content), [content]);

    const handleNavigate = (label: string, id: string) => {
        const container = document.querySelector('[data-mainline-scroll="true"]');
        if (!container) return;
        const headings = Array.from(container.querySelectorAll('h1, h2, h3, h4'));
        const target =
            headings.find((node) => node.getAttribute('data-heading-id') === id)
            || headings.find((node) => node.textContent?.trim() === label);
        if (!target) return;
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    return (
        <div className="flex h-full min-h-0 flex-col overflow-hidden">
            <div className="border-b border-[rgba(255,255,255,0.035)] px-3 py-2.5">
                <div className="cursor-section-label">{copy.outline.section}</div>
                <div className="mt-1 truncate text-[12px] font-medium text-[var(--color-dark-text-main)]">
                    {activeFile}
                </div>
            </div>
            <div className="app-scrollbar min-h-0 flex-1 overflow-y-auto px-2 py-2">
                {outlineItems.length === 0 ? (
                    <div className="rounded-[10px] border border-[rgba(255,255,255,0.04)] bg-[rgba(255,255,255,0.012)] px-3 py-3 text-[11px] leading-5 text-[var(--color-dark-text-faint)]">
                        {copy.outline.empty}
                    </div>
                ) : (
                    <div className="space-y-0.5">
                        {outlineItems.map((item) => (
                            <button
                                key={item.id}
                                type="button"
                                onClick={() => handleNavigate(item.label, item.id)}
                                className="w-full rounded-[8px] border-l border-transparent py-1.5 pr-2 text-left text-[11px] text-[var(--color-dark-text-muted)] transition-colors hover:border-[rgba(255,255,255,0.08)] hover:bg-[rgba(255,255,255,0.012)] hover:text-[var(--color-dark-text-main)]"
                                style={{ paddingLeft: `${10 + (item.level - 1) * 14}px` }}
                            >
                                <div className="truncate">
                                    <span className="mr-2 font-mono text-[10px] text-[var(--color-dark-text-faint)]">
                                        {item.level}
                                    </span>
                                    {item.label}
                                </div>
                            </button>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};
