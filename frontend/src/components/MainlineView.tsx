import React, { useEffect, useRef } from 'react';
import Editor from '@monaco-editor/react';
import { useUiCopy } from '../i18n/ui';
import { MarkdownRender } from './MarkdownRender';
import { StyleAuthorPanel } from './StyleAuthorPanel';
import { isStyleAuthorFile } from '../lib/styleAuthorLens';

type MainlineViewMode = 'view' | 'edit' | 'diff';

interface MainlineViewProps {
    content: string;
    fileName?: string;
    readOnly?: boolean;
    onChange?: (next: string) => void;
    mode?: MainlineViewMode;
    diffView?: React.ReactNode;
}

export const MainlineView: React.FC<MainlineViewProps> = ({
    content,
    fileName,
    readOnly = false,
    onChange,
    mode = 'view',
    diffView = null,
}) => {
    const copy = useUiCopy();
    const viewRef = useRef<HTMLDivElement | null>(null);
    const showStyleAuthorPanel = mode === 'view' && isStyleAuthorFile(fileName);

    useEffect(() => {
        const container = viewRef.current;
        if (!container) return;
        const headings = Array.from(container.querySelectorAll('h1, h2, h3, h4'));
        const seen = new Map<string, number>();
        headings.forEach((node) => {
            const text = node.textContent?.trim() || '';
            const baseId = text
                .toLowerCase()
                .replace(/[^\p{L}\p{N}\s-]/gu, '')
                .replace(/\s+/g, '-')
                .replace(/-+/g, '-')
                .replace(/^-|-$/g, '') || 'heading';
            const count = seen.get(baseId) || 0;
            seen.set(baseId, count + 1);
            const id = count === 0 ? baseId : `${baseId}-${count + 1}`;
            node.setAttribute('data-heading-id', id);
        });
    }, [content, mode]);

    return (
        <div className="relative h-full min-h-0 w-full flex-1 overflow-hidden bg-[rgba(9,11,15,0.66)]">
            <div className={mode === 'view' ? 'h-full min-h-0 overflow-hidden' : 'hidden'}>
                <div ref={viewRef} data-mainline-scroll="true" className="app-scrollbar h-full min-h-0 overflow-y-auto px-6 py-5">
                    {showStyleAuthorPanel ? (
                        <StyleAuthorPanel
                            fileName={fileName || ''}
                            content={content}
                            rawReport={
                                <MarkdownRender
                                    content={content}
                                    className="prose-h1:text-[1.45rem] prose-h2:text-[1.2rem] prose-h3:text-[1rem] prose-table:text-[11px]"
                                />
                            }
                        />
                    ) : (
                        <MarkdownRender content={content} />
                    )}
                </div>
            </div>

            <div className={mode === 'diff' ? 'h-full min-h-0 overflow-hidden' : 'hidden'}>
                {diffView || (
                    <div className="flex h-full items-center justify-center text-sm text-[var(--color-dark-text-muted)]">
                        {copy.review.diffReview}
                    </div>
                )}
            </div>

            <div
                className={mode === 'edit' ? 'h-full min-h-0 overflow-hidden' : 'hidden h-full min-h-0 overflow-hidden'}
                aria-hidden={mode !== 'edit'}
                inert={mode !== 'edit'}
            >
                <Editor
                    height="100%"
                    defaultLanguage="markdown"
                    theme="vs-dark"
                    value={content}
                    onChange={(value) => {
                        if (typeof value === 'string') {
                            onChange?.(value);
                        }
                    }}
                    options={{
                        readOnly: readOnly || mode !== 'edit',
                        minimap: { enabled: false },
                        wordWrap: 'on',
                        scrollBeyondLastLine: false,
                        padding: { top: 16 },
                        fontSize: 13,
                        lineHeight: 21,
                        smoothScrolling: true,
                        overviewRulerBorder: false,
                    }}
                    loading={<div className="p-4 text-[var(--color-dark-text-muted)]">{copy.git.loadingMainline}</div>}
                />
            </div>
        </div>
    );
};
