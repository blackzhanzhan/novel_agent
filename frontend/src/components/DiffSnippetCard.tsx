import React from 'react';
import { DiffAttachment } from '../types/store';

interface DiffSnippetCardProps {
    attachment: DiffAttachment;
}

export const DiffSnippetCard: React.FC<DiffSnippetCardProps> = ({ attachment }) => {
    return (
        <div className="cursor-card rounded-[16px]">
            <div className="border-b border-[var(--color-dark-border)] px-3 py-3 text-[11px] font-mono text-[var(--color-dark-text-faint)]">
                <div className="cursor-section-label mb-2">Draft Snapshot</div>
                <div>Branch: {attachment.branch}</div>
                <div>File: {attachment.fileName}</div>
                <div>Commit: {attachment.commitId || 'pending'}</div>
            </div>
            <details className="px-3 py-3" open>
                <summary className="cursor-pointer text-xs font-medium text-[var(--color-accent-blue)]">局部 Diff 预览</summary>
                <pre className="app-scrollbar mt-3 max-h-56 overflow-auto rounded-[12px] border border-[var(--color-dark-border)] bg-[rgba(9,12,16,0.9)] px-3 py-3 text-[11px] leading-5 text-[#b8d3f1] whitespace-pre-wrap break-words">
                    {attachment.diffPreview || '本次草稿未产生文本差异。'}
                </pre>
            </details>
        </div>
    );
};
