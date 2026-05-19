import { useCallback, useEffect, useRef } from 'react';
import { AppStore, RepoIntegrity } from '../types/store';

import {
    checkoutGitBranch,
    mergeGitBranch,
    commitGitStagedFiles,
    createGitBranch,
    fetchGitBranches,
    fetchGitCommitFiles,
    fetchGitDiffView,
    fetchGitHistoryList,
    fetchGitStatus,
    fetchGitWorkingTree,
    hardRollbackGitBranch,
    stageAllGitFiles,
    stageGitFile,
    unstageGitFile,
} from '../api/gitConsole';
import { fetchHotFiles } from '../api/checkout';
import { ApiError } from '../api/client';
import { extractIntegrityFromError, getErrorMessage } from '../lib/errorUtils';

const GIT_DIFF_MAX_CONSECUTIVE_FAILURES = 3;
const GIT_DIFF_MAX_TOTAL_ATTEMPTS = 12;

export function useGitWorkbench(deps: {
    store: AppStore;
    repoIntegrity: RepoIntegrity | null;
    setRepoIntegrity: (v: RepoIntegrity | null) => void;
    hasPendingDraftDecision: boolean;
    loadMainline: (targetFile?: string, options?: { preserveDraftReview?: boolean }) => Promise<void>;
    loadRepoIntegrity: (bookRefOverride?: { kind: 'book_name' | 'book_id'; value: string }) => Promise<RepoIntegrity | null>;
}) {
    const { store, repoIntegrity, setRepoIntegrity, hasPendingDraftDecision, loadMainline, loadRepoIntegrity } = deps;

    // ── Circuit breaker refs ──
    const gitDiffCircuitRef = useRef({
        consecutiveFailures: 0,
        totalAttempts: 0,
        isOpen: false,
    });
    const gitDiffCircuitScopeRef = useRef('');
    const gitDiffCircuitNoticeScopeRef = useRef('');

    const resetGitDiffCircuit = useCallback(() => {
        gitDiffCircuitRef.current = {
            consecutiveFailures: 0,
            totalAttempts: 0,
            isOpen: false,
        };
    }, []);

    // ── loadGitWorkbench ──
    const loadGitWorkbench = useCallback(async () => {
        if (!store.bookRef.value) return;
        const bookRef = { kind: store.bookRef.kind, value: store.bookRef.value };

        if (repoIntegrity?.needsRepair) {
            store.setGitStatus(null);
            store.setGitBranches([]);
            store.setGitHistoryCommits([]);
            store.setGitWorkingTree([]);
            store.setGitCommitFiles([]);
            store.setGitDiffPayload(null);
            store.setGitError('仓库核心布局不完整，修复后才能进入 Git 视图。');
            return;
        }

        store.setGitLoading(true);
        store.setGitError(null);
        try {
            const [status, branchPayload, history, workingTreePayload] = await Promise.all([
                fetchGitStatus(bookRef),
                fetchGitBranches(bookRef),
                fetchGitHistoryList(bookRef, 220),
                fetchGitWorkingTree(bookRef),
            ]);
            store.setGitStatus(status);
            store.setGitBranches(branchPayload.branches);
            store.setGitHistoryCommits(history);
            store.setGitWorkingTree(workingTreePayload.entries);

            const selectedCommitId = (
                store.selectedGitCommitId && history.some((item) => item.commitId === store.selectedGitCommitId)
            )
                ? store.selectedGitCommitId
                : (history[0]?.commitId || null);
            store.setSelectedGitCommit(selectedCommitId);
            if (!selectedCommitId) {
                store.setGitCommitFiles([]);
                store.setGitDiffPayload(null);
            }
        } catch (err) {
            const integrity = extractIntegrityFromError(err);
            if (integrity) {
                setRepoIntegrity(integrity);
            }
            const errorMessage = getErrorMessage(err, '未知异常');
            store.setGitError(`Git 控制台加载失败：${errorMessage}`);
            store.setUiNotice({
                type: 'error',
                message: `Git 控制台加载失败：${errorMessage}`,
                ts: Date.now(),
            });
        } finally {
            store.setGitLoading(false);
        }
    }, [repoIntegrity?.needsRepair, store.bookRef.kind, store.bookRef.value, store.selectedGitCommitId]);

    // ── Effects ──

    // Load git workbench when switching to git mode
    useEffect(() => {
        if (store.workbenchMode !== 'git') return;
        void loadGitWorkbench();
    }, [store.workbenchMode]);

    // Reset circuit breaker when scope changes
    useEffect(() => {
        if (store.workbenchMode !== 'git') return;
        const nextScope = `${store.gitStatus?.currentBranch || ''}::${store.selectedGitCommitId || ''}`;
        if (gitDiffCircuitScopeRef.current === nextScope) return;
        gitDiffCircuitScopeRef.current = nextScope;
        gitDiffCircuitNoticeScopeRef.current = '';
        resetGitDiffCircuit();
    }, [store.workbenchMode, store.gitStatus?.currentBranch, store.selectedGitCommitId, resetGitDiffCircuit]);

    // Load commit files and diff with circuit breaker
    useEffect(() => {
        if (store.workbenchMode !== 'git') return;
        if (repoIntegrity?.needsRepair) {
            store.setGitCommitFiles([]);
            store.setGitDiffPayload(null);
            return;
        }
        if (!store.selectedGitCommitId || !store.bookRef.value) {
            store.setGitCommitFiles([]);
            store.setGitDiffPayload(null);
            return;
        }
        let cancelled = false;

        const loadCommitFiles = async () => {
            try {
                const selectedCommitId = store.selectedGitCommitId as string;
                const files = await fetchGitCommitFiles(
                    { kind: store.bookRef.kind, value: store.bookRef.value },
                    selectedCommitId
                );
                if (cancelled) return;
                store.setGitCommitFiles(files);
                if (files.length === 0) {
                    store.setGitDiffPayload(null);
                    return;
                }

                const preferredPath = (
                    store.selectedGitPath && files.some((row) => row.path === store.selectedGitPath)
                )
                    ? store.selectedGitPath
                    : files[0].path;
                const candidatePaths = [
                    preferredPath,
                    ...files.map((row) => row.path).filter((path) => path !== preferredPath),
                ];

                let loaded = false;
                let lastError: unknown = null;
                for (const path of candidatePaths) {
                    if (gitDiffCircuitRef.current.isOpen) break;
                    if (gitDiffCircuitRef.current.totalAttempts >= GIT_DIFF_MAX_TOTAL_ATTEMPTS) {
                        gitDiffCircuitRef.current.isOpen = true;
                        break;
                    }

                    gitDiffCircuitRef.current.totalAttempts += 1;
                    try {
                        const payload = await fetchGitDiffView(
                            { kind: store.bookRef.kind, value: store.bookRef.value },
                            {
                                path,
                                scope: 'commit',
                                commitId: selectedCommitId,
                            }
                        );
                        if (cancelled) return;
                        gitDiffCircuitRef.current.consecutiveFailures = 0;
                        store.setSelectedGitPath(path);
                        store.setGitDiffPayload(payload);
                        loaded = true;
                        break;
                    } catch (err) {
                        lastError = err;
                        gitDiffCircuitRef.current.consecutiveFailures += 1;
                        if (gitDiffCircuitRef.current.consecutiveFailures >= GIT_DIFF_MAX_CONSECUTIVE_FAILURES) {
                            gitDiffCircuitRef.current.isOpen = true;
                            break;
                        }
                    }
                }

                if (cancelled || loaded) return;
                store.setGitDiffPayload(null);
                const baseMessage = getErrorMessage(lastError, '未知异常');
                const detail = gitDiffCircuitRef.current.isOpen
                    ? `熔断触发：连续失败 ${gitDiffCircuitRef.current.consecutiveFailures} 次，已停止后续重试。`
                    : baseMessage;
                const noticeScope = gitDiffCircuitScopeRef.current;
                if (gitDiffCircuitNoticeScopeRef.current !== noticeScope) {
                    gitDiffCircuitNoticeScopeRef.current = noticeScope;
                    store.setUiNotice({
                        type: 'error',
                        message: `提交文件差异加载失败：${detail}`,
                        ts: Date.now(),
                    });
                }
            } catch (err) {
                if (cancelled) return;
                store.setUiNotice({
                    type: 'error',
                    message: `提交文件列表加载失败：${getErrorMessage(err, '未知异常')}`,
                    ts: Date.now(),
                });
            }
        };

        void loadCommitFiles();
        return () => {
            cancelled = true;
        };
    }, [repoIntegrity?.needsRepair, store.workbenchMode, store.selectedGitCommitId, store.bookRef.kind, store.bookRef.value]);

    // ── Git action helpers ──

    const runGitAction = useCallback(async (runner: () => Promise<void>) => {
        store.setGitActionPending(true);
        try {
            await runner();
        } finally {
            store.setGitActionPending(false);
        }
    }, [store.setGitActionPending]);

    const reloadAfterBranchSwitch = useCallback(async () => {
        if (!store.bookRef.value) return;
        const currentFile = store.activeFile;
        const bookRef = { kind: store.bookRef.kind, value: store.bookRef.value };
        store.flushAllStore();
        const integrity = await loadRepoIntegrity(bookRef);
        try {
            if (integrity?.exists !== false) {
                const { files, integrity: hotIntegrity } = await fetchHotFiles(bookRef);
                setRepoIntegrity(hotIntegrity);
                if (files.length > 0) {
                    store.setHotFiles(files);
                }
            }
        } catch (err) {
            console.warn('Failed to refresh hot files after branch switch:', err);
        }
        await loadMainline(currentFile);
        await loadGitWorkbench();
    }, [store.bookRef.kind, store.bookRef.value, store.activeFile, loadGitWorkbench, loadMainline, loadRepoIntegrity]);

    // ── Git action handlers ──

    const handleGitCheckout = async (branchName: string, force = false) => {
        if (!store.bookRef.value || !branchName) return;
        if (hasPendingDraftDecision) {
            store.setUiNotice({
                type: 'info',
                message: '当前存在未完成草稿，禁止切换分支。',
                ts: Date.now(),
            });
            return;
        }
        await runGitAction(async () => {
            try {
                await checkoutGitBranch({ kind: store.bookRef.kind, value: store.bookRef.value }, branchName, force);
                await reloadAfterBranchSwitch();
                store.setUiNotice({
                    type: 'success',
                    message: force ? `已强制切换到分支：${branchName}（本地变更已丢弃）` : `已切换到分支：${branchName}`,
                    ts: Date.now(),
                });
            } catch (err) {
                // WORKTREE_DIRTY (409): offer force checkout via confirm dialog
                if (err instanceof ApiError && err.code === 'WORKTREE_DIRTY') {
                    const dirtyEntries: Array<{ path: string }> = (err as ApiError & { entries?: Array<{ path: string }> }).entries || [];
                    const fileList = dirtyEntries.slice(0, 5).map((e) => `• ${e.path}`).join('\n');
                    const extra = dirtyEntries.length > 5 ? `\n...等共 ${dirtyEntries.length} 个文件` : '';
                    const confirmed = window.confirm(
                        `工作区有未提交变更，无法直接切换分支：\n${fileList}${extra}\n\n强制切换将丢弃所有本地变更（包括未追踪文件），是否继续？`
                    );
                    if (confirmed) {
                        // tail-call into force mode; runGitAction is not re-entered here
                        void handleGitCheckout(branchName, true);
                    } else {
                        store.setUiNotice({
                            type: 'info',
                            message: '切换已取消，工作区变更保留。',
                            ts: Date.now(),
                        });
                    }
                    return;
                }
                const message = getErrorMessage(err, '切换分支失败');
                store.setUiNotice({
                    type: 'error',
                    message: `切换分支失败：${message}`,
                    ts: Date.now(),
                });
            }
        });
    };

    const handleGitCreateBranch = async (payload: { branchName: string; fromRef: string | null }) => {
        if (!store.bookRef.value || !payload.branchName) return;
        if (hasPendingDraftDecision) {
            store.setUiNotice({
                type: 'info',
                message: '当前存在未完成草稿，禁止创建或切换分支。',
                ts: Date.now(),
            });
            return;
        }

        await runGitAction(async () => {
            try {
                await createGitBranch(
                    { kind: store.bookRef.kind, value: store.bookRef.value },
                    {
                        branchName: payload.branchName,
                        fromRef: payload.fromRef,
                        checkout: true,
                    }
                );
                await reloadAfterBranchSwitch();
                store.setUiNotice({
                    type: 'success',
                    message: `分支已创建并切换：${payload.branchName}`,
                    ts: Date.now(),
                });
            } catch (err) {
                const message = getErrorMessage(err, '创建分支失败');
                store.setUiNotice({
                    type: 'error',
                    message: `创建分支失败：${message}`,
                    ts: Date.now(),
                });
            }
        });
    };

    const handleGitMerge = async (payload: { sourceBranch: string; noFf: boolean }) => {
        if (!store.bookRef.value || !payload.sourceBranch) return;
        if (hasPendingDraftDecision) {
            store.setUiNotice({ type: 'info', message: '当前存在未完成草稿，禁止执行合并。', ts: Date.now() });
            return;
        }
        await runGitAction(async () => {
            try {
                const result = await mergeGitBranch(
                    { kind: store.bookRef.kind, value: store.bookRef.value },
                    { sourceBranch: payload.sourceBranch, noFf: payload.noFf }
                );
                if (result.merge_type === 'up_to_date') {
                    store.setUiNotice({
                        type: 'info',
                        message: `当前分支已包含「${payload.sourceBranch}」的所有修改，无需合并。`,
                        ts: Date.now(),
                    });
                } else {
                    await reloadAfterBranchSwitch();
                    const label = result.merge_type === 'fast_forward' ? '快进合并' : 'Merge Commit';
                    store.setUiNotice({
                        type: 'success',
                        message: `合并成功（${label}）：${result.commit_id.slice(0, 8)}`,
                        ts: Date.now(),
                    });
                }
            } catch (err) {
                if (err instanceof ApiError && err.code === 'MERGE_CONFLICT') {
                    const files: string[] = (err as ApiError & { conflictedFiles?: string[] }).conflictedFiles || [];
                    const preview = files.slice(0, 3).join('、');
                    const extra = files.length > 3 ? ` 等 ${files.length} 个文件` : '';
                    store.setUiNotice({
                        type: 'error',
                        message: `合并冲突已中止：${preview}${extra}`,
                        ts: Date.now(),
                    });
                    // Surface conflict files back to the panel via a custom event
                    window.dispatchEvent(new CustomEvent('git-merge-conflict', { detail: { files } }));
                    return;
                }
                store.setUiNotice({
                    type: 'error',
                    message: `合并失败：${getErrorMessage(err, '未知异常')}`,
                    ts: Date.now(),
                });
            }
        });
    };

    const handleGitHardRollback = async (targetCommit: string) => {
        if (!store.bookRef.value || !targetCommit) return;
        if (hasPendingDraftDecision) {
            store.setUiNotice({
                type: 'info',
                message: '当前存在未完成草稿，禁止执行硬回退。',
                ts: Date.now(),
            });
            return;
        }

        const confirmed = window.confirm(
            `即将把当前剧情分支回退到节点 ${targetCommit.slice(0, 8)}。\n\n其他剧情分支会保留；当前剧情线在该节点之后的节点会从这条线移除。此操作不可撤销，确认继续？`
        );
        if (!confirmed) return;

        await runGitAction(async () => {
            try {
                const result = await hardRollbackGitBranch(
                    { kind: store.bookRef.kind, value: store.bookRef.value },
                    {
                        targetCommit,
                        deleteOtherBranches: false,
                    }
                );
                await reloadAfterBranchSwitch();
                store.setUiNotice({
                    type: 'success',
                    message: `当前剧情分支已回退到 ${result.head_commit.slice(0, 8)}，其他剧情分支已保留`,
                    ts: Date.now(),
                });
            } catch (err) {
                store.setUiNotice({
                    type: 'error',
                    message: `硬回退失败：${getErrorMessage(err, '未知异常')}`,
                    ts: Date.now(),
                });
            }
        });
    };

    const handleGitOpenCommitDiff = async (path: string, commitId: string) => {
        if (!store.bookRef.value) return;
        await runGitAction(async () => {
            try {
                const payload = await fetchGitDiffView(
                    { kind: store.bookRef.kind, value: store.bookRef.value },
                    { path, scope: 'commit', commitId }
                );
                store.setSelectedGitPath(path);
                store.setGitDiffPayload(payload);
                store.setGitFilePayload(null);
            } catch (err) {
                store.setUiNotice({
                    type: 'error',
                    message: `加载提交 Diff 失败：${getErrorMessage(err, '未知异常')}`,
                    ts: Date.now(),
                });
            }
        });
    };

    const handleGitStage = async (path: string) => {
        if (!store.bookRef.value) return;
        await runGitAction(async () => {
            try {
                await stageGitFile({ kind: store.bookRef.kind, value: store.bookRef.value }, path);
                await loadGitWorkbench();
            } catch (err) {
                store.setUiNotice({
                    type: 'error',
                    message: `暂存失败：${getErrorMessage(err, '未知异常')}`,
                    ts: Date.now(),
                });
            }
        });
    };

    const handleGitUnstage = async (path: string) => {
        if (!store.bookRef.value) return;
        await runGitAction(async () => {
            try {
                await unstageGitFile({ kind: store.bookRef.kind, value: store.bookRef.value }, path);
                await loadGitWorkbench();
            } catch (err) {
                store.setUiNotice({
                    type: 'error',
                    message: `取消暂存失败：${getErrorMessage(err, '未知异常')}`,
                    ts: Date.now(),
                });
            }
        });
    };

    const handleGitStageAll = async () => {
        if (!store.bookRef.value) return;
        await runGitAction(async () => {
            try {
                await stageAllGitFiles({ kind: store.bookRef.kind, value: store.bookRef.value });
                await loadGitWorkbench();
            } catch (err) {
                store.setUiNotice({
                    type: 'error',
                    message: `Stage All 失败：${getErrorMessage(err, '未知异常')}`,
                    ts: Date.now(),
                });
            }
        });
    };

    const handleGitCommit = async (message: string) => {
        if (!store.bookRef.value || !message.trim()) return;
        await runGitAction(async () => {
            try {
                const response = await commitGitStagedFiles(
                    { kind: store.bookRef.kind, value: store.bookRef.value },
                    message
                );
                await loadGitWorkbench();
                store.setUiNotice({
                    type: 'success',
                    message: `提交成功：${response.commit_id.slice(0, 8)}`,
                    ts: Date.now(),
                });
            } catch (err) {
                store.setUiNotice({
                    type: 'error',
                    message: `提交失败：${getErrorMessage(err, '未知异常')}`,
                    ts: Date.now(),
                });
            }
        });
    };

    return {
        loadGitWorkbench,
        reloadAfterBranchSwitch,
        handleGitCheckout,
        handleGitCreateBranch,
        handleGitMerge,
        handleGitHardRollback,
        handleGitOpenCommitDiff,
        handleGitStage,
        handleGitUnstage,
        handleGitStageAll,
        handleGitCommit,
    };
}
