import React, { useMemo, useState } from 'react';
import ReactDiffViewer from 'react-diff-viewer-continued';
import { GitCommitFile, GitDiffPayload, GitHistoryCommit, GitStatusSummary, GitWorkingTreeEntry } from '../types/store';
import { useUiCopy } from '../i18n/ui';
import { codeReviewDiffStyles } from './diffStyles';

interface GitWorkingTreePanelProps {
    status: GitStatusSummary | null;
    workingTree: GitWorkingTreeEntry[];
    commitFiles: GitCommitFile[];
    selectedCommit: GitHistoryCommit | null;
    selectedPath: string | null;
    commitDiffPayload: GitDiffPayload | null;
    pending: boolean;
    onSelectPath: (path: string) => void;
    onOpenCommitDiff: (path: string, commitId: string) => void;
    onStage: (path: string) => void;
    onUnstage: (path: string) => void;
    onStageAll: () => void;
    onCommit: (message: string) => void;
    onOpenFullscreenDiff: () => void;
}

function StatusBadge({ status }: { status: string }) {
    const color = status === 'A'
        ? 'text-[#3fb950] border-[#3fb950]'
        : status === 'D'
            ? 'text-[#f85149] border-[#f85149]'
            : 'text-[var(--color-accent-blue)] border-[var(--color-accent-blue)]';

    return (
        <span className={`rounded border px-1.5 py-0.5 text-[9px] font-mono ${color}`}>
            {status}
        </span>
    );
}

export const GitWorkingTreePanel: React.FC<GitWorkingTreePanelProps> = ({
    status,
    workingTree,
    commitFiles,
    selectedCommit,
    selectedPath,
    commitDiffPayload,
    pending,
    onSelectPath,
    onOpenCommitDiff,
    onStage,
    onUnstage,
    onStageAll,
    onCommit,
    onOpenFullscreenDiff,
}) => {
    const copy = useUiCopy();
    const [commitMessage, setCommitMessage] = useState('');
    const [diffSplitView, setDiffSplitView] = useState(false);

    const summary = useMemo(() => {
        if (!status) return '...';
        return `${copy.git.workingTree}：${status.isDirty ? copy.git.dirty : copy.git.clean} · ${copy.git.stagedLabel} ${status.stagedCount} · ${copy.git.unstagedLabel} ${status.unstagedCount}`;
    }, [copy.git, status]);

    return (
        <div className="flex h-full min-h-0 flex-col overflow-hidden">
            <div className="border-b border-[var(--color-dark-border)] px-4 py-2 text-xs font-mono text-[var(--color-dark-text-muted)]">
                <div>{copy.git.waitingInspector}</div>
                <div className="mt-1 text-[10px]">{selectedCommit ? selectedCommit.commitId : copy.git.selectCommit}</div>
            </div>

            <div className="app-scrollbar min-h-0 flex-1 overflow-y-auto px-3 py-3">
                <div className="git-console-card rounded-[12px] p-3">
                    {!selectedCommit && (
                        <div className="git-console-card-muted rounded-[10px] px-4 py-4 text-[11px] text-[var(--color-dark-text-muted)]">
                            <div className="cursor-section-label">{copy.git.waitingInspector}</div>
                            <div className="mt-2 text-[15px] font-medium text-[var(--color-dark-text-main)]">{copy.git.selectCommit}</div>
                            <div className="mt-1 leading-6 text-[var(--color-dark-text-faint)]">
                                {copy.git.selectCommitHintBody}
                            </div>
                        </div>
                    )}

                    {selectedCommit && (
                        <>
                            <div className="font-mono text-[11px] text-[var(--color-accent-blue)]">{selectedCommit.shortId}</div>
                            <div className="mt-1 text-[10px] text-[var(--color-dark-text-muted)]">{selectedCommit.timestamp}</div>
                            <div className="mt-1 text-[10px] text-[var(--color-dark-text-muted)]">
                                {selectedCommit.authorName} &lt;{selectedCommit.authorEmail}&gt;
                            </div>
                            <div className="git-console-card-muted mt-2 rounded-[10px] px-3 py-3 text-xs leading-5 text-[var(--color-dark-text-main)]">
                                {selectedCommit.message || copy.git.emptyCommitMessage}
                            </div>

                            <div className="mt-3 text-[10px] font-semibold tracking-wide text-[var(--color-dark-text-muted)]">
                                {copy.git.changedFiles}
                            </div>
                            <div className="mt-2 space-y-2">
                                {commitFiles.length === 0 && (
                                    <div className="text-[11px] text-[var(--color-dark-text-muted)]">{copy.git.noFiles}</div>
                                )}
                                {commitFiles.map((row) => (
                                    <button
                                        key={`${selectedCommit.commitId}:${row.path}`}
                                        type="button"
                                        onClick={() => {
                                            onSelectPath(row.path);
                                            onOpenCommitDiff(row.path, selectedCommit.commitId);
                                        }}
                                        disabled={pending}
                                    className={`w-full rounded-[10px] border px-2.5 py-2 text-left transition-colors ${
                                        selectedPath === row.path
                                            ? 'git-console-card border-[rgba(255,255,255,0.14)]'
                                            : 'git-console-card-muted hover:border-[var(--color-dark-border-strong)]'
                                    } disabled:cursor-not-allowed disabled:opacity-60`}
                                    >
                                        <div className="flex items-center justify-between gap-2">
                                            <span className="truncate font-mono text-[11px] text-[var(--color-dark-text-main)]">{row.path}</span>
                                            <StatusBadge status={row.status} />
                                        </div>
                                    </button>
                                ))}
                            </div>

                            <div className="mt-3 text-[10px] font-semibold tracking-wide text-[var(--color-dark-text-muted)]">{copy.git.diffPreview}</div>
                            {!commitDiffPayload && (
                                <div className="mt-2 text-[11px] text-[var(--color-dark-text-muted)]">{copy.git.loadingDiff}</div>
                            )}
                            {commitDiffPayload && (
                                <div className="mt-2 overflow-hidden rounded-[8px] border border-[var(--color-dark-border)] bg-[#0f1722]">
                                    <div className="flex items-center justify-between gap-2 border-b border-[var(--color-dark-border)] px-2 py-1 text-[10px] text-[var(--color-dark-text-muted)]">
                                        <span className="truncate">
                                            {commitDiffPayload.path} · {commitDiffPayload.oldLabel} -&gt; {commitDiffPayload.newLabel}
                                        </span>
                                        <div className="flex items-center gap-1">
                                            <button
                                                type="button"
                                                onClick={onOpenFullscreenDiff}
                                                className="rounded border border-[var(--color-dark-border)] px-1.5 py-0.5 text-[10px] hover:border-[var(--color-accent-blue)]"
                                            >
                                                {copy.git.fullscreen}
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => setDiffSplitView(false)}
                                                className={`rounded border px-1.5 py-0.5 ${
                                                    !diffSplitView
                                                        ? 'border-[var(--color-accent-blue)] text-[var(--color-accent-blue)]'
                                                        : 'border-[var(--color-dark-border)]'
                                                }`}
                                            >
                                                {copy.review.singleColumn}
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => setDiffSplitView(true)}
                                                className={`rounded border px-1.5 py-0.5 ${
                                                    diffSplitView
                                                        ? 'border-[var(--color-accent-blue)] text-[var(--color-accent-blue)]'
                                                        : 'border-[var(--color-dark-border)]'
                                                }`}
                                            >
                                                {copy.review.splitColumn}
                                            </button>
                                        </div>
                                    </div>
                                    <div className="app-scrollbar min-h-[160px] max-h-[45vh] overflow-auto p-2">
                                        <ReactDiffViewer
                                            oldValue={commitDiffPayload.oldText}
                                            newValue={commitDiffPayload.newText}
                                            splitView={diffSplitView}
                                            useDarkTheme={true}
                                            showDiffOnly={false}
                                            styles={codeReviewDiffStyles}
                                        />
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                </div>

                <div className="mt-5 border-t border-[var(--color-dark-border)] pt-4">
                    <div className="mb-2 text-[10px] font-semibold tracking-wide text-[var(--color-dark-text-muted)]">{copy.git.workingTree}</div>
                    <div className="mb-3 text-[10px] text-[var(--color-dark-text-muted)]">{summary}</div>

                    <div className="mb-4 flex items-center justify-between">
                        <div className="text-[10px] font-semibold tracking-wide text-[var(--color-dark-text-muted)]">{copy.git.changedFiles}</div>
                        <button
                            type="button"
                            onClick={onStageAll}
                            disabled={pending || workingTree.length === 0}
                            className="git-console-primary rounded-[10px] px-2.5 py-1 text-[10px] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                            {copy.git.stageAll}
                        </button>
                    </div>

                    <div className="space-y-2">
                        {workingTree.length === 0 && (
                            <div className="git-console-card-muted rounded-[12px] px-3 py-6 text-center text-[11px] text-[var(--color-dark-text-muted)]">
                                <div className="cursor-section-label">{copy.git.workingTree}</div>
                                <div className="mt-2 text-[14px] font-medium text-[var(--color-dark-text-main)]">{copy.git.noLocalChanges}</div>
                                <div className="mt-1 text-[11px] text-[var(--color-dark-text-faint)]">{copy.git.noLocalChangesHint}</div>
                            </div>
                        )}
                        {workingTree.map((entry) => (
                            <div
                                key={entry.path}
                                className={`rounded-[10px] border px-2.5 py-2 ${
                                    selectedPath === entry.path
                                        ? 'git-console-card border-[rgba(255,255,255,0.14)]'
                                        : 'git-console-card-muted'
                                }`}
                            >
                                <button
                                    type="button"
                                    onClick={() => onSelectPath(entry.path)}
                                    className="w-full text-left"
                                >
                                    <div className="flex items-start justify-between gap-2">
                                        <div className="min-w-0 flex-1">
                                            <div className="truncate font-mono text-[11px] text-[var(--color-dark-text-main)]">{entry.path}</div>
                                            {entry.previousPath && (
                                                <div className="truncate text-[10px] text-[var(--color-dark-text-muted)]">{copy.git.source} {entry.previousPath}</div>
                                            )}
                                        </div>
                                        <div className="flex items-center gap-1">
                                            {entry.indexStatus !== ' ' && entry.indexStatus !== '?' && <StatusBadge status={entry.indexStatus} />}
                                            {entry.worktreeStatus !== ' ' && <StatusBadge status={entry.worktreeStatus} />}
                                            {entry.isUntracked && <StatusBadge status="?" />}
                                        </div>
                                    </div>
                                </button>

                                <div className="mt-2 flex flex-wrap gap-2">
                                    {entry.staged ? (
                                        <button
                                            type="button"
                                            onClick={() => onUnstage(entry.path)}
                                            disabled={pending}
                                            className="rounded-[10px] border border-[var(--tone-danger-border)] px-2 py-1 text-[10px] text-[var(--tone-danger-text)] disabled:cursor-not-allowed disabled:opacity-60"
                                        >
                                            {copy.git.unstage}
                                        </button>
                                    ) : (
                                        <button
                                            type="button"
                                            onClick={() => onStage(entry.path)}
                                            disabled={pending}
                                            className="git-console-primary rounded-[10px] px-2 py-1 text-[10px] disabled:cursor-not-allowed disabled:opacity-60"
                                        >
                                            {copy.git.stage}
                                        </button>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>

                    <div className="mt-5 border-t border-[var(--color-dark-border)] pt-4">
                        <div className="git-console-card rounded-[10px] px-3 py-3">
                            <div className="mb-2 text-[10px] font-semibold tracking-wide text-[var(--color-dark-text-muted)]">
                                {copy.git.commitToCurrent}
                            </div>
                            <textarea
                                value={commitMessage}
                                onChange={(event) => setCommitMessage(event.target.value)}
                                rows={3}
                                placeholder={copy.git.commitPlaceholder}
                                className="git-console-field w-full resize-none rounded-[12px] px-2.5 py-2 text-xs"
                            />
                            <button
                                type="button"
                                disabled={pending || !commitMessage.trim()}
                                onClick={() => {
                                    onCommit(commitMessage.trim());
                                    setCommitMessage('');
                                }}
                                className="git-console-primary mt-3 w-full rounded-[12px] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                            >
                                {copy.git.commitStagedFiles}
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
