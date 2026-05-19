import React from 'react';
import { GitHistoryCommit } from '../types/store';
import { useUiCopy } from '../i18n/ui';

interface GitCenterPanelProps {
    commits: GitHistoryCommit[];
    selectedCommitId: string | null;
    loading: boolean;
    error: string | null;
    onSelectCommit: (commitId: string) => void;
}

function renderRefs(refs: string[]): React.ReactNode {
    if (!refs.length) return null;
    return (
        <div className="mt-2 flex flex-wrap gap-1">
            {refs.map((refName) => (
                <span
                    key={refName}
                    className="rounded-full border border-[var(--color-dark-border)] bg-[rgba(255,255,255,0.03)] px-2 py-0.5 font-mono text-[10px] text-[var(--color-dark-text-faint)]"
                >
                    {refName}
                </span>
            ))}
        </div>
    );
}

export const GitCenterPanel: React.FC<GitCenterPanelProps> = ({
    commits,
    selectedCommitId,
    loading,
    error,
    onSelectCommit,
}) => {
    const copy = useUiCopy();
    if (loading && commits.length === 0) {
        return (
            <div className="flex h-full min-h-0 items-center justify-center px-6">
                <div className="git-empty-state w-full max-w-xl rounded-[14px] px-6 py-6 text-left">
                    <div className="cursor-section-label">{copy.git.historyStream}</div>
                    <div className="mt-3 text-xl font-medium text-[var(--color-dark-text-main)]">{copy.git.loadingTimeline}</div>
                    <div className="mt-2 max-w-md text-sm leading-6 text-[var(--color-dark-text-faint)]">
                        {copy.git.loadingTimelineHint}
                    </div>
                </div>
            </div>
        );
    }

    if (error && commits.length === 0) {
        return (
            <div className="flex h-full min-h-0 items-center justify-center px-6">
                <div className="git-empty-state w-full max-w-xl rounded-[14px] px-6 py-6 text-left">
                    <div className="cursor-section-label text-[var(--tone-danger-text)]">{copy.git.historyUnavailable}</div>
                    <div className="mt-3 text-xl font-medium text-[var(--color-dark-text-main)]">{copy.git.timelineUnavailable}</div>
                    <div className="mt-2 text-sm leading-6 text-[var(--color-dark-text-faint)]">
                        {copy.git.loadingTimelineHint}
                    </div>
                    <div className="git-console-card-muted mt-4 rounded-[10px] px-4 py-3 text-sm leading-6 text-[var(--tone-danger-text)]">
                        {error}
                    </div>
                    <div className="mt-4 text-[11px] font-mono tracking-[0.12em] text-[var(--color-dark-text-faint)]">
                        {copy.git.backendRetryHint}
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="flex h-full min-h-0 flex-col overflow-hidden">
            <div className="border-b border-[var(--color-dark-border)] px-4 py-4">
                <div className="cursor-section-label">{copy.git.history}</div>
                <div className="mt-1 flex items-center justify-between gap-3">
                    <span className="text-sm font-semibold text-[var(--color-dark-text-main)]">{copy.git.commitTimeline}</span>
                    <span className="rounded-[8px] border border-[rgba(255,255,255,0.04)] bg-[rgba(255,255,255,0.012)] px-2 py-1 text-[10px] font-mono text-[var(--color-dark-text-faint)]">{copy.git.branchCount(commits.length)}</span>
                </div>
            </div>
            <div className="app-scrollbar min-h-0 flex-1 overflow-y-auto bg-transparent px-4 py-4">
                {commits.length === 0 ? (
                    <div className="git-empty-state rounded-[14px] px-5 py-5 text-left">
                        <div className="cursor-section-label">{copy.git.timelineEmpty}</div>
                        <div className="mt-3 text-lg font-medium text-[var(--color-dark-text-main)]">{copy.git.noCommitRecords}</div>
                        <div className="mt-2 text-sm leading-6 text-[var(--color-dark-text-faint)]">
                            {copy.git.loadingTimelineHint}
                        </div>
                    </div>
                ) : (
                    <div className="relative space-y-3 pl-6 before:absolute before:bottom-6 before:left-[11px] before:top-3 before:w-px before:bg-[linear-gradient(180deg,rgba(255,255,255,0.12)_0%,rgba(255,255,255,0.02)_100%)]">
                        {commits.map((commit) => (
                            <button
                                key={commit.commitId}
                                type="button"
                                onClick={() => onSelectCommit(commit.commitId)}
                                className={`group relative w-full rounded-[10px] border px-4 py-3 text-left transition-all ${
                                    commit.commitId === selectedCommitId
                                        ? 'git-console-card border-[rgba(255,255,255,0.14)]'
                                        : 'git-console-card-muted hover:border-[var(--color-dark-border-strong)] hover:bg-[rgba(255,255,255,0.03)]'
                                }`}
                            >
                                <span
                                    className={`absolute -left-[19px] top-5 h-3 w-3 rounded-full border ${
                                        commit.commitId === selectedCommitId
                                            ? 'border-[rgba(255,255,255,0.35)] bg-[rgba(255,255,255,0.82)]'
                                            : 'border-[rgba(255,255,255,0.12)] bg-[rgba(17,20,26,1)] group-hover:border-[rgba(255,255,255,0.22)]'
                                    }`}
                                />
                                <div className="flex items-center justify-between gap-2">
                                    <div className="font-mono text-xs text-[var(--color-dark-text-main)]">{commit.shortId}</div>
                                    <div className="text-[10px] text-[var(--color-dark-text-muted)]">{commit.timestamp}</div>
                                </div>
                                <div className="mt-1 text-xs leading-5 text-[var(--color-dark-text-main)]">
                                    {commit.message || copy.git.emptyCommitMessage}
                                </div>
                                {renderRefs(commit.refs)}
                            </button>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};
