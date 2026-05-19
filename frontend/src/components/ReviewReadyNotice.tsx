import React from 'react';
import { ReviewReadyNotice as ReviewReadyNoticePayload, UiLanguage } from '../types/store';
import { getUiCopy } from '../i18n/ui';

interface ReviewReadyNoticeProps {
    notice: ReviewReadyNoticePayload | null;
    uiLanguage: UiLanguage;
    onEnterReview: () => void;
    onClose: () => void;
}

export const ReviewReadyNotice: React.FC<ReviewReadyNoticeProps> = ({
    notice,
    uiLanguage,
    onEnterReview,
    onClose,
}) => {
    if (!notice) return null;
    const copy = getUiCopy(uiLanguage);

    return (
        <div className="pointer-events-none fixed bottom-5 left-1/2 z-[65] w-[460px] max-w-[calc(100vw-32px)] -translate-x-1/2">
            <div className="workspace-strip pointer-events-auto rounded-[18px] border px-4 py-4 shadow-[0_18px_36px_rgba(0,0,0,0.28)]">
                <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                        <div className="cursor-section-label">{copy.reviewReadyNotice.section}</div>
                        <div className="mt-2 text-[15px] font-semibold text-[var(--color-dark-text-main)]">
                            {copy.reviewReadyNotice.readyMessage(notice.fileName)}
                        </div>
                        <div className="mt-1 text-[11px] text-[var(--color-dark-text-faint)]">
                            {notice.branch} · {notice.commitId ? notice.commitId.slice(0, 8) : copy.common.pending}
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="text-[11px] text-[var(--color-dark-text-faint)] hover:text-[var(--color-dark-text-main)]"
                    >
                        {copy.common.close}
                    </button>
                </div>

                <div className="mt-3 rounded-[14px] border border-[rgba(255,255,255,0.06)] bg-[rgba(9,12,16,0.9)] px-3 py-3">
                    <div className="text-[10px] font-mono tracking-[0.12em] text-[var(--color-dark-text-faint)]">
                        {copy.reviewReadyNotice.previewSummary}
                    </div>
                    <pre className="app-scrollbar mt-2 max-h-44 overflow-auto whitespace-pre-wrap break-words text-[11px] leading-5 text-[var(--color-dark-text-main)]">
                        {notice.diffPreview || copy.reviewReadyNotice.previewFallback}
                    </pre>
                </div>

                <div className="mt-3 flex gap-2">
                    <button
                        type="button"
                        onClick={onEnterReview}
                        className="flex-1 rounded-[12px] border border-[var(--tone-success-border)] bg-[var(--tone-success-bg)] px-3 py-2.5 text-sm font-semibold text-[var(--tone-success-text)] transition-colors hover:bg-[rgba(255,255,255,0.12)]"
                    >
                        {copy.reviewReadyNotice.enterReview}
                    </button>
                    <button
                        type="button"
                        onClick={onClose}
                        className="rounded-[12px] border border-[var(--color-dark-border)] px-3 py-2.5 text-sm text-[var(--color-dark-text-main)] transition-colors hover:border-[var(--color-dark-border-strong)]"
                    >
                        {copy.common.later}
                    </button>
                </div>
            </div>
        </div>
    );
};
