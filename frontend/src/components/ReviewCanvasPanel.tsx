import React, { useMemo, useState } from 'react';
import { FsmState } from '../types/store';
import { useUiCopy } from '../i18n/ui';
import { SandboxView } from './SandboxView';
import { MarkdownRender } from './MarkdownRender';

type ReviewSurfaceMode = 'diff' | 'draft' | 'mainline';

interface ReviewCanvasPanelProps {
    fileName: string;
    mainlineContent: string;
    draftContent: string;
    draftCommitId: string | null;
    fsmState: FsmState;
    onOpenFullscreen: () => void;
}

function lineCount(text: string): number {
    if (!text) return 0;
    return text.split('\n').length;
}

export const ReviewCanvasPanel: React.FC<ReviewCanvasPanelProps> = ({
    fileName,
    mainlineContent,
    draftContent,
    draftCommitId,
    fsmState,
    onOpenFullscreen,
}) => {
    const copy = useUiCopy();
    const [surfaceMode, setSurfaceMode] = useState<ReviewSurfaceMode>('diff');
    const [splitView, setSplitView] = useState(true);

    const summaryText = useMemo(() => {
        const draftLines = lineCount(draftContent);
        const mainlineLines = lineCount(mainlineContent);
        return copy.review.lineSummary(mainlineLines, draftLines);
    }, [copy.review, draftContent, mainlineContent]);

    return (
        <div className="flex h-full min-h-0 flex-col overflow-hidden">
            <div className="border-b border-[rgba(255,255,255,0.035)] px-4 py-3">
                <div className="cursor-section-label">{copy.review.canvas}</div>
                <div className="mt-1 flex items-center justify-between gap-4">
                    <div className="min-w-0">
                        <div className="text-[14px] font-semibold text-[var(--color-dark-text-main)]">{fileName}</div>
                        <div className="text-[11px] text-[var(--color-dark-text-faint)]">
                            {summaryText} · {copy.review.draftCommit} {draftCommitId ? draftCommitId.slice(0, 8) : copy.common.pending}
                        </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                        <div className="rounded-[8px] border border-[rgba(255,255,255,0.04)] bg-[rgba(255,255,255,0.012)] px-2.5 py-1 text-[10px] font-mono text-[var(--color-dark-text-faint)]">
                            {fsmState === 'CONFLICT' ? copy.review.conflictReview : copy.review.diffReview}
                        </div>
                        <button
                            type="button"
                            onClick={onOpenFullscreen}
                            disabled={!draftContent}
                            className="rounded-[8px] border border-[rgba(255,255,255,0.1)] bg-[rgba(255,255,255,0.035)] px-2.5 py-1 text-[10px] font-semibold text-[var(--color-dark-text-main)] transition-colors hover:bg-[rgba(255,255,255,0.08)] disabled:cursor-not-allowed disabled:opacity-45"
                        >
                            全屏审阅
                        </button>
                    </div>
                </div>
            </div>

            <div className="border-b border-[rgba(255,255,255,0.03)] px-4 py-2">
                <div className="flex items-center justify-between gap-3">
                    <div className="workspace-strip-muted flex gap-1 rounded-[8px] border p-1">
                        {[
                            { id: 'diff', label: copy.review.diff },
                            { id: 'draft', label: copy.review.draft },
                            { id: 'mainline', label: copy.review.mainline },
                        ].map((item) => (
                            <button
                                key={item.id}
                                type="button"
                                onClick={() => setSurfaceMode(item.id as ReviewSurfaceMode)}
                                className={`rounded-[8px] px-3 py-1.5 text-[11px] transition-colors ${
                                    surfaceMode === item.id
                                        ? 'cursor-chip-active'
                                        : 'text-[var(--color-dark-text-muted)] hover:bg-[rgba(255,255,255,0.03)] hover:text-[var(--color-dark-text-main)]'
                                }`}
                            >
                                {item.label}
                            </button>
                        ))}
                    </div>
                    {surfaceMode === 'diff' ? (
                        <div className="workspace-strip-muted flex gap-1 rounded-[8px] border p-1">
                            <button
                                type="button"
                                onClick={() => setSplitView(false)}
                                className={`rounded-[8px] px-3 py-1.5 text-[11px] transition-colors ${
                                    !splitView
                                        ? 'cursor-chip-active'
                                        : 'text-[var(--color-dark-text-muted)] hover:bg-[rgba(255,255,255,0.03)] hover:text-[var(--color-dark-text-main)]'
                                }`}
                            >
                                {copy.review.singleColumn}
                            </button>
                            <button
                                type="button"
                                onClick={() => setSplitView(true)}
                                className={`rounded-[8px] px-3 py-1.5 text-[11px] transition-colors ${
                                    splitView
                                        ? 'cursor-chip-active'
                                        : 'text-[var(--color-dark-text-muted)] hover:bg-[rgba(255,255,255,0.03)] hover:text-[var(--color-dark-text-main)]'
                                }`}
                            >
                                {copy.review.splitColumn}
                            </button>
                        </div>
                    ) : (
                        <div className="text-[10px] font-mono text-[var(--color-dark-text-faint)]">
                            {copy.review.readingView}
                        </div>
                    )}
                </div>
            </div>

            <div className="min-h-0 flex-1 overflow-hidden">
                {surfaceMode === 'diff' ? (
                    <SandboxView
                        original={mainlineContent}
                        modified={draftContent}
                        isVisible={Boolean(draftContent)}
                        splitView={splitView}
                    />
                ) : (
                    <div className="app-scrollbar h-full overflow-y-auto bg-[rgba(9,11,15,0.64)] px-6 py-5">
                        <MarkdownRender content={surfaceMode === 'draft' ? draftContent : mainlineContent} />
                    </div>
                )}
            </div>
        </div>
    );
};
