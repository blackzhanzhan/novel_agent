import React, { useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import ReactDiffViewer from 'react-diff-viewer-continued';
import { DraftActionPending, FsmState } from '../types/store';
import { codeReviewDiffStyles } from './diffStyles';

interface ReviewDiffFullscreenProps {
    isOpen: boolean;
    fileName: string;
    branch: string;
    draftCommitId: string | null;
    mainlineContent: string;
    draftContent: string;
    fsmState: FsmState;
    draftActionPending: DraftActionPending;
    onConfirm: () => void;
    onRollback: () => void;
    onClose: () => void;
}

function lineCount(text: string): number {
    if (!text) return 0;
    return text.split('\n').length;
}

export const ReviewDiffFullscreen: React.FC<ReviewDiffFullscreenProps> = ({
    isOpen,
    fileName,
    branch,
    draftCommitId,
    mainlineContent,
    draftContent,
    fsmState,
    draftActionPending,
    onConfirm,
    onRollback,
    onClose,
}) => {
    const stats = useMemo(
        () => ({
            mainlineLines: lineCount(mainlineContent),
            draftLines: lineCount(draftContent),
        }),
        [draftContent, mainlineContent],
    );

    useEffect(() => {
        if (!isOpen) return;
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') return;
            if (event.defaultPrevented) return;
            event.preventDefault();
            event.stopPropagation();
            onClose();
        };
        window.addEventListener('keydown', onKeyDown);
        return () => {
            window.removeEventListener('keydown', onKeyDown);
        };
    }, [isOpen, onClose]);

    if (!isOpen || typeof document === 'undefined') return null;

    const canConfirm = fsmState === 'REVIEW' && draftActionPending === 'none';
    const canRollback = (fsmState === 'REVIEW' || fsmState === 'CONFLICT') && draftActionPending === 'none';
    const isChapterDraftReview = fileName === 'chapter_draft.md';
    const confirmLabel = isChapterDraftReview ? '归入正文归档' : '批准确权';
    const actionLabel = draftActionPending === 'confirm'
        ? (isChapterDraftReview ? '正在归档' : '正在批准')
        : draftActionPending === 'rollback'
            ? '正在回滚'
            : (isChapterDraftReview ? '等待归档确认' : '等待审批');

    return createPortal(
        <div className="fixed inset-0 z-[80] flex bg-[rgba(6,8,11,0.82)] backdrop-blur-sm" onMouseDown={onClose}>
            <section
                className="cursor-panel-elevated m-3 flex h-[calc(100%-24px)] w-[calc(100%-24px)] min-h-0 min-w-0 flex-col overflow-hidden rounded-[18px] border"
                onMouseDown={(event) => event.stopPropagation()}
            >
                <header className="flex min-h-[72px] shrink-0 items-center justify-between gap-4 border-b border-[var(--color-dark-border)] px-5 py-3">
                    <div className="min-w-0">
                        <div className="cursor-section-label">全屏 Diff 审批</div>
                        <div className="mt-1 truncate text-[15px] font-semibold text-[var(--color-dark-text-main)]">{fileName}</div>
                        <div className="mt-0.5 truncate text-[11px] text-[var(--color-dark-text-faint)]">
                            {branch} · {draftCommitId ? draftCommitId.slice(0, 8) : 'pending'} · 主线 {stats.mainlineLines} 行 / 草稿 {stats.draftLines} 行
                        </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                        <span className="rounded-[9px] border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.018)] px-2.5 py-1 text-[10px] font-mono text-[var(--color-dark-text-faint)]">
                            {actionLabel}
                        </span>
                        <button
                            type="button"
                            onClick={onConfirm}
                            disabled={!canConfirm}
                            title={isChapterDraftReview ? '把续写草稿归档为正式 chapters/*.md，并触发状态卡/世界模型接棒。' : '批准当前草稿并合入主线。'}
                            className="rounded-[10px] border border-[var(--tone-success-border)] bg-[var(--tone-success-bg)] px-3 py-2 text-xs font-semibold text-[var(--tone-success-text)] transition-colors hover:bg-[rgba(255,255,255,0.12)] disabled:cursor-not-allowed disabled:opacity-45"
                        >
                            {confirmLabel}
                        </button>
                        <button
                            type="button"
                            onClick={onRollback}
                            disabled={!canRollback}
                            className="rounded-[10px] border border-[var(--tone-danger-border)] px-3 py-2 text-xs font-semibold text-[var(--tone-danger-text)] transition-colors hover:bg-[var(--tone-danger-bg)] disabled:cursor-not-allowed disabled:opacity-45"
                        >
                            湮灭回滚
                        </button>
                        <button
                            type="button"
                            onClick={onClose}
                            className="rounded-[10px] border border-[var(--color-dark-border)] px-3 py-2 text-xs text-[var(--color-dark-text-main)] transition-colors hover:border-[var(--color-dark-border-strong)]"
                        >
                            关闭
                        </button>
                    </div>
                </header>

                <div className="flex shrink-0 items-center justify-between gap-3 border-b border-[rgba(255,255,255,0.035)] px-5 py-2">
                    <div className="workspace-strip-muted grid w-full max-w-[520px] grid-cols-2 rounded-[8px] border text-[11px] font-mono text-[var(--color-dark-text-muted)]">
                        <div className="border-r border-[rgba(255,255,255,0.05)] px-3 py-1.5">左侧：主线</div>
                        <div className="px-3 py-1.5">右侧：草稿</div>
                    </div>
                    <div className="text-[10px] font-mono text-[var(--color-dark-text-faint)]">左右对照 Diff</div>
                </div>

                <div className="app-scrollbar min-h-0 flex-1 overflow-auto bg-[rgba(9,11,15,0.72)] p-5">
                    <ReactDiffViewer
                        oldValue={mainlineContent}
                        newValue={draftContent}
                        splitView={true}
                        useDarkTheme={true}
                        showDiffOnly={false}
                        styles={codeReviewDiffStyles}
                    />
                </div>
            </section>
        </div>,
        document.body,
    );
};
