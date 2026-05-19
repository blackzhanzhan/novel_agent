import React, { useEffect, useMemo, useState } from 'react';
import { GitBranchRow, GitStatusSummary } from '../types/store';
import { useUiCopy } from '../i18n/ui';

interface GitBranchPanelProps {
    status: GitStatusSummary | null;
    branches: GitBranchRow[];
    selectedCommitId: string | null;
    chapterDraftContent?: string;
    pending: boolean;
    onRefresh: () => void;
    onCheckout: (branchName: string) => void;
    onMerge: (payload: { sourceBranch: string; noFf: boolean }) => void;
    onCreateBranch: (payload: { branchName: string; fromRef: string | null }) => void;
    onHardRollback: (targetCommit: string) => void;
}

export const GitBranchPanel: React.FC<GitBranchPanelProps> = ({
    status,
    branches,
    selectedCommitId,
    chapterDraftContent = '',
    pending,
    onRefresh,
    onCheckout,
    onMerge,
    onCreateBranch,
    onHardRollback,
}) => {
    const copy = useUiCopy();
    const currentBranch = status?.currentBranch || '';
    const mainlineBranch = status?.mainlineBranch || '';

    const [selectedBranch, setSelectedBranch] = useState('');
    const [newBranchName, setNewBranchName] = useState('');
    const [fromRef, setFromRef] = useState('');
    const [mergeSource, setMergeSource] = useState('');
    const [mergeNoFf, setMergeNoFf] = useState(false);
    const [mergeConflictFiles, setMergeConflictFiles] = useState<string[]>([]);

    const draftProgress = useMemo(() => {
        const headings = [...chapterDraftContent.matchAll(/^##\s+(.+?)\s*$/gm)]
            .map((match) => match[1]?.trim())
            .filter(Boolean);
        return {
            count: headings.length,
            latestTitle: headings[headings.length - 1] || '',
        };
    }, [chapterDraftContent]);

    useEffect(() => {
        if (currentBranch) {
            setSelectedBranch(currentBranch);
        }
    }, [currentBranch]);

    useEffect(() => {
        if (!fromRef && selectedCommitId) {
            setFromRef(selectedCommitId);
        }
    }, [selectedCommitId, fromRef]);

    const canSwitch = Boolean(selectedBranch) && selectedBranch !== currentBranch && !pending;
    const sortedBranches = useMemo(() => {
        const rows = [...branches];
        rows.sort((a, b) => Number(b.isCurrent) - Number(a.isCurrent) || a.name.localeCompare(b.name));
        return rows;
    }, [branches]);

    return (
        <div className="flex h-full min-h-0 flex-col overflow-hidden">
            <div className="border-b border-[var(--color-dark-border)] px-4 py-4">
                <div className="cursor-section-label">{copy.git.console}</div>
                <div className="mt-1 flex items-center justify-between gap-3">
                    <span className="text-sm font-semibold text-[var(--color-dark-text-main)]">{copy.git.branches}</span>
                    <span className="rounded-[8px] border border-[rgba(255,255,255,0.04)] bg-[rgba(255,255,255,0.012)] px-2 py-1 text-[10px] font-mono text-[var(--color-dark-text-faint)]">{copy.git.branchCount(branches.length)}</span>
                </div>
            </div>
            <div className="border-b border-[var(--color-dark-border)] px-3 py-3">
                <div className="workspace-strip-muted flex items-center justify-between rounded-[10px] border px-3 py-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-dark-text-muted)]">
                    <span>{copy.git.branchFlow}</span>
                    <button
                        type="button"
                        onClick={onRefresh}
                        disabled={pending}
                        className="cursor-chip rounded-[10px] px-2.5 py-1 text-[10px] font-medium normal-case text-[var(--color-dark-text-main)] hover:border-[rgba(126,162,255,0.45)] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                        {copy.git.refresh}
                    </button>
                </div>
            </div>

            <div className="border-b border-[var(--color-dark-border)] px-3 py-3 text-[11px] leading-5 text-[var(--color-dark-text-muted)]">
                <div className="git-console-card-muted grid gap-2 rounded-[10px] px-3 py-3">
                    <div>
                        <div className="cursor-section-label">{copy.git.plotBranchStatus}</div>
                        <div className="mt-1 text-[13px] font-semibold text-[var(--color-dark-text-main)]">
                            {draftProgress.count > 0
                                ? copy.git.plotProgressSummary(draftProgress.count, draftProgress.latestTitle)
                                : copy.git.plotProgressUnavailable}
                        </div>
                        <div className="mt-1 text-[10px] text-[var(--color-dark-text-faint)]">
                            {copy.git.plotProgressHint}
                        </div>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                        <span className="font-mono tracking-[0.1em] text-[var(--color-dark-text-faint)]">{copy.git.currentBranch}</span>
                        <span className="font-mono text-[var(--color-dark-text-main)]">{status?.currentBranch || '...'}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                        <span className="font-mono tracking-[0.1em] text-[var(--color-dark-text-faint)]">{copy.git.mainlineBranch}</span>
                        <span className="font-mono text-[var(--color-dark-text-main)]">{status?.mainlineBranch || '...'}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                        <span className="font-mono tracking-[0.1em] text-[var(--color-dark-text-faint)]">{copy.git.workingTree}</span>
                        <span className={status?.isDirty ? 'text-[var(--tone-danger-text)]' : 'text-[var(--color-dark-text-main)]'}>
                            {status ? (status.isDirty ? copy.git.dirty : copy.git.clean) : '...'}
                        </span>
                    </div>
                </div>
            </div>

            <div className="app-scrollbar min-h-0 flex-1 overflow-y-auto px-2 py-2">
                <div className="space-y-1">
                    {sortedBranches.map((branch) => (
                        <button
                            key={branch.name}
                            type="button"
                            onClick={() => setSelectedBranch(branch.name)}
                            disabled={pending}
                            className={`w-full rounded-[10px] border px-2.5 py-2.5 text-left text-xs transition-all ${
                                selectedBranch === branch.name
                                    ? 'git-console-card border-[rgba(255,255,255,0.14)]'
                                    : 'git-console-card-muted hover:border-[var(--color-dark-border-strong)] hover:bg-[rgba(255,255,255,0.03)]'
                            } disabled:cursor-not-allowed disabled:opacity-70`}
                        >
                            <div className="flex items-center justify-between gap-2">
                                <span className="truncate font-mono text-[11px] text-[var(--color-dark-text-main)]">{branch.name}</span>
                                {branch.isCurrent && (
                                    <span className="rounded-full border border-[rgba(79,186,122,0.35)] px-2 py-0.5 text-[9px] text-[var(--color-accent-green)]">
                                        {copy.git.current}
                                    </span>
                                )}
                            </div>
                            <div className="mt-1 truncate text-[10px] text-[var(--color-dark-text-muted)]">
                                {branch.headCommit.slice(0, 8)} · {branch.headMessage || copy.git.emptyCommitMessage}
                            </div>
                        </button>
                    ))}
                </div>
            </div>

            <div className="space-y-3 border-t border-[var(--color-dark-border)] px-3 py-3">
                <div className="git-console-card rounded-[10px] px-3 py-3">
                    <div className="cursor-section-label">{copy.git.switchSection}</div>
                    <div className="mt-3 space-y-2">
                        <button
                            type="button"
                            onClick={() => onCheckout(selectedBranch)}
                            disabled={!canSwitch}
                            className="git-console-primary w-full rounded-[12px] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                        >
                            {copy.git.switchToSelected}
                        </button>
                        <button
                            type="button"
                            onClick={() => {
                                if (!mainlineBranch || mainlineBranch === currentBranch) return;
                                onCheckout(mainlineBranch);
                            }}
                            disabled={!mainlineBranch || mainlineBranch === currentBranch || pending}
                            className="w-full rounded-[12px] border border-[var(--color-dark-border)] px-3 py-2 text-xs text-[var(--color-dark-text-main)] hover:border-[var(--color-dark-border-strong)] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                            {copy.git.backToMainline(mainlineBranch)}
                        </button>
                    </div>
                </div>
            </div>

            <div className="space-y-3 border-t border-[var(--color-dark-border)] px-3 py-3">
                <div className="git-console-card rounded-[10px] px-3 py-3">
                    <div className="text-[10px] font-semibold tracking-wide text-[var(--color-dark-text-muted)]">{copy.git.mergeBranch}</div>
                    <div className="mt-1 text-[10px] text-[var(--color-dark-text-muted)]">
                        {copy.git.current}: <span className="font-mono text-[var(--color-dark-text-main)]">{currentBranch || '...'}</span>
                    </div>
                    <select
                        value={mergeSource}
                        onChange={(e) => { setMergeSource(e.target.value); setMergeConflictFiles([]); }}
                        disabled={pending}
                        className="git-console-field mt-3 w-full rounded-[12px] px-2.5 py-2 text-xs disabled:cursor-not-allowed disabled:opacity-60"
                    >
                        <option value="">{copy.git.chooseMergeSource}</option>
                        {sortedBranches.filter((b) => !b.isCurrent).map((b) => (
                            <option key={b.name} value={b.name}>{b.name}</option>
                        ))}
                    </select>
                    <label className="mt-3 flex items-center gap-2 text-[10px] text-[var(--color-dark-text-muted)] cursor-pointer">
                        <input
                            type="checkbox"
                            checked={mergeNoFf}
                            onChange={(e) => setMergeNoFf(e.target.checked)}
                            disabled={pending}
                            className="accent-[var(--color-accent-blue)]"
                        />
                        {copy.git.mergeNoFf}
                    </label>
                    <button
                        type="button"
                        disabled={!mergeSource || pending}
                        onClick={() => {
                            setMergeConflictFiles([]);
                            onMerge({ sourceBranch: mergeSource, noFf: mergeNoFf });
                        }}
                        className="git-console-primary mt-3 w-full rounded-[12px] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                    >
                        {copy.git.mergeIntoCurrent}
                    </button>
                    {mergeConflictFiles.length > 0 && (
                        <div className="mt-3 rounded-[12px] border border-[var(--tone-danger-border)] bg-[var(--tone-danger-bg)] px-3 py-2 text-[10px]">
                            <div className="mb-1 font-semibold text-[var(--tone-danger-text)]">{copy.git.mergeConflictTitle}</div>
                            {mergeConflictFiles.map((f) => (
                                <div key={f} className="truncate font-mono text-[var(--color-dark-text-main)]">• {f}</div>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            <div className="space-y-3 border-t border-[var(--color-dark-border)] px-3 py-3">
                <div className="git-console-card rounded-[10px] px-3 py-3">
                    <div className="text-[10px] font-semibold tracking-wide text-[var(--color-dark-text-muted)]">{copy.git.createBranch}</div>
                    <input
                        value={newBranchName}
                        onChange={(event) => setNewBranchName(event.target.value)}
                        placeholder={copy.git.plotBranchPlaceholder}
                        className="git-console-field mt-3 w-full rounded-[12px] px-2.5 py-2 text-xs"
                    />
                    <input
                        value={fromRef}
                        onChange={(event) => setFromRef(event.target.value)}
                        placeholder={copy.git.fromCommitPlaceholder}
                        className="git-console-field mt-2 w-full rounded-[12px] px-2.5 py-2 font-mono text-[11px]"
                    />
                    <button
                        type="button"
                        disabled={!newBranchName.trim() || pending}
                        onClick={() => {
                            onCreateBranch({
                                branchName: newBranchName.trim(),
                                fromRef: fromRef.trim() || selectedCommitId || null,
                            });
                            setNewBranchName('');
                        }}
                        className="git-console-primary mt-3 w-full rounded-[12px] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                    >
                        {copy.git.createAndSwitch}
                    </button>
                </div>
            </div>

            <div className="space-y-3 border-t border-[var(--color-dark-border)] px-3 py-3">
                <div className="git-console-card rounded-[10px] px-3 py-3">
                    <div className="text-[10px] font-semibold tracking-wide text-[var(--color-dark-text-muted)]">{copy.git.hardRollback}</div>
                    <div className="mt-1 text-[10px] leading-5 text-[var(--color-dark-text-faint)]">
                        {copy.git.rollbackCurrentOnlyHint}
                    </div>
                    <div className="git-console-field mt-3 rounded-[12px] px-2.5 py-2 font-mono text-[10px] text-[var(--color-dark-text-muted)]">
                        {selectedCommitId ? selectedCommitId : copy.git.selectCommitHint}
                    </div>
                    <button
                        type="button"
                        disabled={!selectedCommitId || pending}
                        onClick={() => {
                            if (!selectedCommitId) return;
                            onHardRollback(selectedCommitId);
                        }}
                        className="git-console-danger mt-3 w-full rounded-[12px] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                    >
                        {copy.git.hardRollbackAndPrune}
                    </button>
                </div>
            </div>
        </div>
    );
};
