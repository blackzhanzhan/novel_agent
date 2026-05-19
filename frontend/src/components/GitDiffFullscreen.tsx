import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import ReactDiffViewer from 'react-diff-viewer-continued';
import { useAppStore } from '../store';
import { codeReviewDiffStyles } from './diffStyles';

export const GitDiffFullscreen: React.FC = () => {
    const { isOpen, payload, close } = useAppStore((state) => ({
        isOpen: state.gitDiffFullscreen,
        payload: state.gitDiffPayload,
        close: () => state.setGitDiffFullscreen(false),
    }));
    const [splitView, setSplitView] = useState(true);

    useEffect(() => {
        if (!isOpen) return;
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') return;
            if (event.defaultPrevented) return;
            event.preventDefault();
            event.stopPropagation();
            close();
        };
        window.addEventListener('keydown', onKeyDown);
        return () => {
            window.removeEventListener('keydown', onKeyDown);
        };
    }, [isOpen, close]);

    if (!isOpen || !payload || typeof document === 'undefined') return null;

    return createPortal(
        <div className="fixed inset-0 z-[70] flex bg-[rgba(8,10,13,0.78)] backdrop-blur-sm" onMouseDown={close}>
            <section
                className="cursor-panel-elevated m-3 flex h-[calc(100%-24px)] w-[calc(100%-24px)] min-h-0 min-w-0 flex-col overflow-hidden rounded-[20px] border"
                onMouseDown={(event) => event.stopPropagation()}
                onKeyDown={(event) => {
                    if (event.key === 'Escape') {
                        event.stopPropagation();
                    }
                }}
            >
                <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-[var(--color-dark-border)] px-5 text-xs text-[var(--color-dark-text-muted)]">
                    <div className="min-w-0">
                        <div className="cursor-section-label">Diff Fullscreen</div>
                        <div className="truncate font-mono text-[11px] text-[var(--color-dark-text-main)]">{payload.path}</div>
                        <div className="truncate text-[10px] text-[var(--color-dark-text-faint)]">{payload.oldLabel} -&gt; {payload.newLabel}</div>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            onClick={() => setSplitView(false)}
                            className={`rounded-[10px] border px-2 py-1 text-[10px] ${
                                !splitView
                                    ? 'cursor-chip-active'
                                    : 'cursor-chip text-[var(--color-dark-text-faint)]'
                            }`}
                        >
                            Unified
                        </button>
                        <button
                            type="button"
                            onClick={() => setSplitView(true)}
                            className={`rounded-[10px] border px-2 py-1 text-[10px] ${
                                splitView
                                    ? 'cursor-chip-active'
                                    : 'cursor-chip text-[var(--color-dark-text-faint)]'
                            }`}
                        >
                            Split
                        </button>
                        <button
                            type="button"
                            onClick={close}
                            className="cursor-chip rounded-[10px] px-2 py-1 text-[10px] text-[var(--color-dark-text-main)] hover:border-[rgba(255,255,255,0.18)]"
                        >
                            关闭
                        </button>
                    </div>
                </header>

                <div className="app-scrollbar min-h-0 flex-1 overflow-auto bg-[rgba(9,11,15,0.72)] p-5">
                    <ReactDiffViewer
                        oldValue={payload.oldText}
                        newValue={payload.newText}
                        splitView={splitView}
                        useDarkTheme={true}
                        showDiffOnly={false}
                        styles={codeReviewDiffStyles}
                    />
                </div>
            </section>
        </div>,
        document.body
    );
};
