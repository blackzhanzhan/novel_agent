import { useCallback, useEffect, useState } from 'react';
import { useAppStore } from '../store';
import { AppStore, RepoIntegrity } from '../types/store';
import { fetchMainlineFile } from '../api/checkout';
import {
    fetchGitBranches,
    fetchGitCommitFiles,
    fetchGitDiffView,
    fetchGitFileView,
} from '../api/gitConsole';
import { confirmDraft, rollbackDraft, type DraftConfirmResponse } from '../api/draft';
import { ApiError } from '../api/client';

export function useDraftReview(deps: {
    store: AppStore;
    repoIntegrity: RepoIntegrity | null;
    setRepoIntegrity: (v: RepoIntegrity | null) => void;
    loadMainline: (file?: string, opts?: { preserveDraftReview?: boolean }) => Promise<void>;
    onPostConfirm?: (result: DraftConfirmResponse) => Promise<void> | void;
}) {
    const { store, loadMainline, onPostConfirm } = deps;

    const [reviewDiffFullscreenOpen, setReviewDiffFullscreenOpen] = useState(false);

    const loadReviewTargetMainline = useCallback(async (targetFile: string) => {
        if (!store.bookRef.value || !targetFile) return;
        try {
            const { content, etag } = await fetchMainlineFile(store.bookRef, targetFile);
            store.setReviewMainlineFact(content, etag);
        } catch (err) {
            console.error('Failed to load review target mainline fact:', err);
            store.setReviewMainlineFact('', '');
        }
    }, [store.bookRef.kind, store.bookRef.value]);

    const hydrateDraftReviewFromBranch = useCallback(async (targetFile?: string) => {
        const runtimeState = useAppStore.getState();
        if (!runtimeState.bookRef.value) return false;
        if (runtimeState.draftContent || runtimeState.draftCommitId) return false;
        if (runtimeState.draftActionPending !== 'none') return false;
        if (
            runtimeState.fsmState !== 'IDLE'
            && runtimeState.fsmState !== 'REVIEW'
            && runtimeState.fsmState !== 'CONFLICT'
        ) return false;

        let fileName = targetFile || runtimeState.activeFile;
        if (!fileName) return false;

        try {
            const branchesPayload = await fetchGitBranches(runtimeState.bookRef);
            const draftBranch = branchesPayload.branches.find((row) => row.name === runtimeState.draftBranch);
            if (!draftBranch?.headCommit) return false;
            const mainlineBranch = branchesPayload.branches.find((row) => row.name === branchesPayload.mainlineBranch);
            if (mainlineBranch?.headCommit && draftBranch.headCommit === mainlineBranch.headCommit) return false;

            let changedFiles: string[] = [];
            try {
                const commitFiles = await fetchGitCommitFiles(runtimeState.bookRef, draftBranch.headCommit);
                changedFiles = commitFiles
                    .map((row) => row.path)
                    .filter((path): path is string => Boolean(path));
            } catch {
                changedFiles = [];
            }

            const isReviewArchiveOnlyChange = changedFiles.includes('error_archive.md')
                && !changedFiles.includes('chapter_draft.md');
            if (isReviewArchiveOnlyChange) {
                fileName = 'chapter_draft.md';
                changedFiles = ['chapter_draft.md', ...changedFiles.filter((path) => path !== 'chapter_draft.md')];
            } else if (changedFiles.length > 0 && !changedFiles.includes(fileName)) {
                fileName = changedFiles[0];
            }

            let mainlineFile: { content: string; etag: string };
            let draftContent = '';
            try {
                const commitDiff = await fetchGitDiffView(runtimeState.bookRef, {
                    scope: 'commit',
                    path: fileName,
                    commitId: draftBranch.headCommit,
                });
                if (!commitDiff.changed) throw new Error('draft head commit has no file diff');
                mainlineFile = {
                    content: commitDiff.oldText,
                    etag: runtimeState.baseEtag,
                };
                draftContent = commitDiff.newText;
            } catch {
                try {
                    const gitMainlineFile = await fetchGitFileView(runtimeState.bookRef, fileName, branchesPayload.mainlineBranch);
                    mainlineFile = {
                        content: gitMainlineFile.content,
                        etag: runtimeState.baseEtag,
                    };
                } catch {
                    const checkoutMainlineFile = await fetchMainlineFile(runtimeState.bookRef, fileName);
                    mainlineFile = {
                        content: checkoutMainlineFile.content,
                        etag: checkoutMainlineFile.etag,
                    };
                }
                const draftFile = await fetchGitFileView(runtimeState.bookRef, fileName, runtimeState.draftBranch);
                draftContent = draftFile.content;
            }

            if (!draftContent || draftContent === mainlineFile.content) return false;

            const latestStore = useAppStore.getState();
            latestStore.setReviewTarget(fileName, changedFiles.length > 0 ? changedFiles : [fileName]);
            latestStore.setReviewMainlineFact(mainlineFile.content, mainlineFile.etag);
            latestStore.setSandboxDraft(draftContent, draftBranch.headCommit);
            latestStore.setFsmState(runtimeState.fsmState === 'CONFLICT' ? 'CONFLICT' : 'REVIEW');
            latestStore.setWorkbenchMode('review');
            return true;
        } catch (err) {
            console.warn('Failed to hydrate draft review from branch:', err);
            return false;
        }
    }, []);

    const handleConfirm = async () => {
        if (store.fsmState !== 'REVIEW') return;
        store.setDraftActionPending('confirm');
        try {
            const result = await confirmDraft(store.bookRef);
            store.markDraftResolved('confirmed');
            store.resetSandbox();
            store.clearReviewReadyNotice();
            store.setWorkbenchMode('editor');
            await loadMainline();
            const materializedCount = result.materialized_chapters?.length || 0;
            const message = materializedCount > 0
                ? `正文已归档：${materializedCount} 章，${result.commit_id.slice(0, 8)} -> ${result.mainline_branch}`
                : `草稿已确权：${result.commit_id.slice(0, 8)} -> ${result.mainline_branch}`;
            store.setUiNotice({
                type: 'success',
                message,
                ts: Date.now(),
            });
            await onPostConfirm?.(result);
        } catch (err) {
            console.error('Confirmation failed:', err);
            if (err instanceof ApiError) {
                if (err.status === 409 || err.code === 'MERGE_CONFLICT') {
                    store.setFsmState('CONFLICT');
                    store.setUiNotice({
                        type: 'error',
                        message: `确权失败：${err.message}`,
                        ts: Date.now(),
                    });
                } else if (err.status === 404) {
                    store.resetSandbox();
                    store.clearReviewReadyNotice();
                    store.setWorkbenchMode('editor');
                    await loadMainline();
                    store.setUiNotice({
                        type: 'info',
                        message: '草稿分支不存在，已回到主线最新版本。',
                        ts: Date.now(),
                    });
                } else {
                    store.setUiNotice({
                        type: 'error',
                        message: `确权失败：${err.message}`,
                        ts: Date.now(),
                    });
                }
            } else {
                store.setUiNotice({
                    type: 'error',
                    message: '确权失败：未知异常',
                    ts: Date.now(),
                });
            }
        } finally {
            store.setDraftActionPending('none');
        }
    };

    const handleRollback = async () => {
        if (store.fsmState !== 'REVIEW' && store.fsmState !== 'CONFLICT') return;
        store.setDraftActionPending('rollback');
        const draftCommit = store.draftCommitId;
        if (!draftCommit) {
            console.warn('Rollback skipped: draftCommitId is missing, fallback to mainline refresh.');
            store.resetSandbox();
            await loadMainline();
            store.setUiNotice({
                type: 'info',
                message: '未检测到草稿提交，已刷新主线内容。',
                ts: Date.now(),
            });
            store.setDraftActionPending('none');
            return;
        }
        try {
            const branchesPayload = await fetchGitBranches(store.bookRef);
            const mainlineBranch = branchesPayload.branches.find((row) => row.name === branchesPayload.mainlineBranch);
            const targetCommit = mainlineBranch?.headCommit;
            if (!targetCommit) {
                throw new Error(`无法定位主线分支 ${branchesPayload.mainlineBranch} 的 HEAD，已停止回滚。`);
            }
            await rollbackDraft(store.bookRef, targetCommit);
            store.markDraftResolved('rolled_back');
            store.resetSandbox();
            store.clearReviewReadyNotice();
            store.setWorkbenchMode('editor');
            await loadMainline();
            store.setUiNotice({
                type: 'success',
                message: `草稿已回滚：${draftCommit.slice(0, 8)} → ${targetCommit.slice(0, 8)}`,
                ts: Date.now(),
            });
        } catch (err) {
            console.error('Rollback failed:', err);
            if (err instanceof ApiError) {
                if (err.status === 404) {
                    store.resetSandbox();
                    store.clearReviewReadyNotice();
                    store.setWorkbenchMode('editor');
                    await loadMainline();
                    store.setUiNotice({
                        type: 'info',
                        message: '草稿分支不存在，已回到主线最新版本。',
                        ts: Date.now(),
                    });
                } else {
                    store.setUiNotice({
                        type: 'error',
                        message: `回滚失败：${err.message}`,
                        ts: Date.now(),
                    });
                }
            } else {
                store.setUiNotice({
                    type: 'error',
                    message: '回滚失败：未知异常',
                    ts: Date.now(),
                });
            }
        } finally {
            store.setDraftActionPending('none');
        }
    };

    const handleRefreshLock = async () => {
        store.resetSandbox();
        store.clearReviewReadyNotice();
        store.setWorkbenchMode('editor');
        await loadMainline();
    };

    const pendingReviewTargetFile = useCallback(() => {
        const runtimeState = useAppStore.getState();
        return runtimeState.reviewTargetFile || runtimeState.reviewReadyNotice?.fileName || runtimeState.activeFile;
    }, []);

    // Auto-exit review when no review workspace
    const hasReviewPayload = Boolean(
        store.draftCommitId
        || store.draftContent
    );
    const hasReviewWorkspace = Boolean(
        hasReviewPayload
        || store.fsmState === 'REVIEW'
        || store.fsmState === 'CONFLICT'
    );

    useEffect(() => {
        if (hasReviewWorkspace) return;
        setReviewDiffFullscreenOpen(false);
        if (store.workbenchMode === 'review') {
            store.setWorkbenchMode('editor');
        }
    }, [hasReviewWorkspace, store.workbenchMode]);

    useEffect(() => {
        if (hasReviewPayload) return;
        if (store.draftActionPending !== 'none') return;
        if (store.fsmState !== 'IDLE' && store.fsmState !== 'REVIEW' && store.fsmState !== 'CONFLICT') return;
        void hydrateDraftReviewFromBranch(store.activeFile);
    }, [
        hasReviewPayload,
        hydrateDraftReviewFromBranch,
        store.bookRef.kind,
        store.bookRef.value,
        store.activeFile,
        store.fsmState,
        store.draftActionPending,
        store.mainlineContent,
        store.baseEtag,
    ]);

    return {
        reviewDiffFullscreenOpen,
        setReviewDiffFullscreenOpen,
        loadReviewTargetMainline,
        hydrateDraftReviewFromBranch,
        handleConfirm,
        handleRollback,
        handleRefreshLock,
        pendingReviewTargetFile,
        hasPendingDraftDecision: store.fsmState !== 'IDLE'
            || store.draftActionPending !== 'none'
            || Boolean(store.draftCommitId),
        hasReviewPayload,
        hasReviewWorkspace,
    };
}
