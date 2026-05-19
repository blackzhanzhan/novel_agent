import React, { useMemo } from 'react';
import { DiffAttachment, DraftActionPending, FsmState } from '../types/store';
import { useUiCopy } from '../i18n/ui';
import { measureChapterLengths } from '../lib/chapterLength';

interface ReviewInspectorPanelProps {
    fileName: string;
    branch: string;
    draftCommitId: string | null;
    draftContent: string;
    mainlineContent: string;
    draftAttachment: DiffAttachment | null;
    fsmState: FsmState;
    draftActionPending: DraftActionPending;
    onConfirm: () => void;
    onRollback: () => void;
    onRunReviewAgent?: () => void;
    onRewriteWithReview?: () => void;
    onOpenFullscreen: () => void;
    onBackToEditor: () => void;
    onRefreshLock: () => void;
}

function lineCount(text: string): number {
    if (!text) return 0;
    return text.split('\n').length;
}

export const ReviewInspectorPanel: React.FC<ReviewInspectorPanelProps> = ({
    fileName,
    branch,
    draftCommitId,
    draftContent,
    mainlineContent,
    draftAttachment,
    fsmState,
    draftActionPending,
    onConfirm,
    onRollback,
    onRunReviewAgent,
    onRewriteWithReview,
    onOpenFullscreen,
    onBackToEditor,
    onRefreshLock,
}) => {
    const copy = useUiCopy();
    const stats = useMemo(
        () => ({
            draftLines: lineCount(draftContent),
            mainlineLines: lineCount(mainlineContent),
        }),
        [draftContent, mainlineContent],
    );
    const chapterLengthReport = useMemo(
        () => fileName === 'chapter_draft.md' ? measureChapterLengths(draftContent) : null,
        [draftContent, fileName],
    );
    const isChapterDraftReview = fileName === 'chapter_draft.md';
    const confirmLabel = isChapterDraftReview ? '归入正文归档' : copy.review.confirm;
    const confirmHint = isChapterDraftReview
        ? '把已确认的续写草稿归档为正式 chapters/*.md，并自动接棒刷新状态卡，按需更新世界模型。'
        : '批准当前草稿并合入主线。';

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="border-b border-[rgba(255,255,255,0.035)] px-3.5 py-2.5">
                <div className="cursor-section-label">{copy.review.inspector}</div>
                <div className="mt-1 text-[13px] font-semibold text-[var(--color-dark-text-main)]">{fileName}</div>
                <div className="text-[10px] text-[var(--color-dark-text-faint)]">
                    {branch} · {draftCommitId ? draftCommitId.slice(0, 8) : copy.common.pending}
                </div>
            </div>

            <div className="app-scrollbar min-h-0 flex-1 overflow-y-auto px-3 py-3">
                <div className="workspace-strip-muted rounded-[10px] px-3 py-3">
                    <div className="cursor-section-label">{copy.review.currentDraft}</div>
                    <div className="mt-2 text-sm font-semibold text-[var(--color-dark-text-main)]">
                        {isChapterDraftReview ? '续写草稿等待正文归档。' : copy.review.workspaceReady}
                    </div>
                    <div className="mt-1 text-[11px] leading-5 text-[var(--color-dark-text-faint)]">
                        {isChapterDraftReview
                            ? '确认后会保留草稿原文，拆入正式章节归档，并把最新剧情状态交给世界观路由接棒。'
                            : copy.review.workspaceHint}
                    </div>
                </div>

                <div className="mt-3 workspace-strip-muted rounded-[10px] px-3 py-3">
                    <div className="cursor-section-label">{copy.review.changeScale}</div>
                    <div className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                        <div className="rounded-[10px] border border-[rgba(255,255,255,0.05)] bg-[rgba(255,255,255,0.014)] px-3 py-2">
                            <div className="text-[var(--color-dark-text-faint)]">{copy.review.mainlineLines}</div>
                            <div className="mt-1 text-[13px] font-semibold text-[var(--color-dark-text-main)]">{stats.mainlineLines}</div>
                        </div>
                        <div className="rounded-[10px] border border-[rgba(255,255,255,0.05)] bg-[rgba(255,255,255,0.014)] px-3 py-2">
                            <div className="text-[var(--color-dark-text-faint)]">{copy.review.draftLines}</div>
                            <div className="mt-1 text-[13px] font-semibold text-[var(--color-dark-text-main)]">{stats.draftLines}</div>
                        </div>
                    </div>
                </div>

                {chapterLengthReport && chapterLengthReport.chapterCount > 0 ? (
                    <div className={`mt-3 rounded-[10px] border px-3 py-3 ${
                        chapterLengthReport.ok
                            ? 'border-[var(--tone-success-border)] bg-[var(--tone-success-bg)]'
                            : 'border-[var(--tone-warning-border)] bg-[rgba(245,158,11,0.08)]'
                    }`}>
                        <div className="flex items-center justify-between gap-2">
                            <div className="cursor-section-label">章节篇幅</div>
                            <div className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                                chapterLengthReport.ok
                                    ? 'text-[var(--tone-success-text)]'
                                    : 'text-[var(--tone-warning-text)]'
                            }`}>
                                {chapterLengthReport.ok ? '达标' : `${chapterLengthReport.underMinCount} 章不足`}
                            </div>
                        </div>
                        <div className="mt-1 text-[11px] leading-5 text-[var(--color-dark-text-faint)]">
                            硬下限 {chapterLengthReport.minChars}，目标 {chapterLengthReport.targetChars}，按非空白字符估算。
                        </div>
                        <div className="mt-2 space-y-1.5">
                            {chapterLengthReport.chapters.map((chapter) => (
                                <div
                                    key={chapter.title}
                                    className="rounded-[8px] border border-[rgba(255,255,255,0.045)] bg-[rgba(255,255,255,0.018)] px-2.5 py-2"
                                >
                                    <div className="flex items-center justify-between gap-2 text-[11px]">
                                        <div className="min-w-0 truncate font-medium text-[var(--color-dark-text-main)]">
                                            {chapter.title}
                                        </div>
                                        <div className={`shrink-0 font-mono ${
                                            chapter.status === 'under_min'
                                                ? 'text-[var(--tone-warning-text)]'
                                                : chapter.status === 'over_max'
                                                    ? 'text-[#bfdbfe]'
                                                    : 'text-[var(--tone-success-text)]'
                                        }`}>
                                            {chapter.nonWhitespaceChars}
                                        </div>
                                    </div>
                                    {chapter.status === 'under_min' ? (
                                        <div className="mt-1 text-[10px] text-[var(--tone-warning-text)]">
                                            距下限差 {chapter.deficitToMin}，距目标差 {chapter.deficitToTarget}
                                        </div>
                                    ) : null}
                                </div>
                            ))}
                        </div>
                    </div>
                ) : null}

                {fsmState === 'CONFLICT' ? (
                    <div className="mt-3 workspace-strip rounded-[10px] border border-[var(--tone-danger-border)] bg-[var(--tone-danger-bg)] px-3 py-3">
                        <div className="cursor-section-label text-[var(--tone-danger-text)]">{copy.review.conflictHandling}</div>
                        <div className="mt-2 text-sm font-semibold text-[var(--tone-danger-text)]">
                            {copy.review.conflictHint}
                        </div>
                        <button
                            onClick={onRefreshLock}
                            className="mt-3 w-full rounded-[10px] border border-[rgba(255,255,255,0.12)] bg-[rgba(255,255,255,0.05)] px-3 py-2 text-sm text-[var(--color-dark-text-main)] hover:bg-[rgba(255,255,255,0.08)]"
                        >
                            {copy.review.refreshLock}
                        </button>
                    </div>
                ) : null}

                <div className="mt-3 space-y-2">
                    <button
                        onClick={onOpenFullscreen}
                        disabled={!draftContent}
                        className="w-full rounded-[10px] border border-[rgba(255,255,255,0.14)] bg-[rgba(255,255,255,0.055)] px-3 py-2.5 text-sm font-semibold text-[var(--color-dark-text-main)] transition-colors hover:bg-[rgba(255,255,255,0.1)] disabled:cursor-not-allowed disabled:opacity-45"
                    >
                        全屏 Diff 审阅
                    </button>
                    <button
                        onClick={onConfirm}
                        disabled={fsmState === 'CONFLICT' || draftActionPending !== 'none'}
                        title={confirmHint}
                        className="w-full rounded-[10px] border border-[var(--tone-success-border)] bg-[var(--tone-success-bg)] px-3 py-2.5 text-sm font-semibold text-[var(--tone-success-text)] transition-colors hover:bg-[rgba(255,255,255,0.12)] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {confirmLabel}
                    </button>
                    <button
                        onClick={onRunReviewAgent}
                        disabled={!onRunReviewAgent || draftActionPending !== 'none'}
                        className="w-full rounded-[10px] border border-[rgba(96,165,250,0.55)] bg-[rgba(37,99,235,0.12)] px-3 py-2.5 text-sm font-semibold text-[#bfdbfe] transition-colors hover:bg-[rgba(37,99,235,0.18)] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        启动审核 Agent
                    </button>
                    <button
                        onClick={onRewriteWithReview}
                        disabled={!onRewriteWithReview || draftActionPending !== 'none'}
                        className="w-full rounded-[10px] border border-[var(--tone-warning-border)] bg-[rgba(255,255,255,0.018)] px-3 py-2.5 text-sm font-semibold text-[var(--tone-warning-text)] transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        打回续写 Agent 重写
                    </button>
                    <button
                        onClick={onRollback}
                        disabled={draftActionPending !== 'none'}
                        className="w-full rounded-[10px] border border-[var(--tone-danger-border)] px-3 py-2.5 text-sm font-semibold text-[var(--tone-danger-text)] transition-colors hover:bg-[var(--tone-danger-bg)] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {copy.review.rollback}
                    </button>
                    <button
                        onClick={onBackToEditor}
                        className="w-full rounded-[10px] border border-[var(--color-dark-border)] px-3 py-2.5 text-sm text-[var(--color-dark-text-main)] transition-colors hover:border-[var(--color-dark-border-strong)]"
                    >
                        {copy.review.backToEditor}
                    </button>
                </div>

                {draftAttachment?.diffPreview ? (
                    <div className="mt-4">
                        <div className="cursor-section-label mb-2">{copy.review.diffSummary}</div>
                        <pre className="app-scrollbar max-h-64 overflow-auto rounded-[10px] border border-[rgba(255,255,255,0.05)] bg-[rgba(9,12,16,0.78)] px-3 py-3 text-[11px] leading-5 text-[var(--color-dark-text-main)] whitespace-pre-wrap break-words">
                            {draftAttachment.diffPreview}
                        </pre>
                    </div>
                ) : null}
            </div>
        </div>
    );
};
