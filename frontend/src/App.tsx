import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Group, Panel, Separator, useDefaultLayout } from 'react-resizable-panels';
import { useMemo } from 'react';
import { useAppStore } from './store';
import { useHumanEditMode } from './hooks/useHumanEditMode';
import { useDraftReview } from './hooks/useDraftReview';
import { useGitWorkbench } from './hooks/useGitWorkbench';
import { useAgentSession } from './hooks/useAgentSession';
import { AppLayout } from './layouts/AppLayout';
import { MainlineView } from './components/MainlineView';
import { ChatPanel } from './components/ChatPanel';
import { AgentConversationList } from './components/AgentConversationList';
import { ChatComposerDock } from './components/ChatComposerDock';
import { ConflictBanner } from './components/ConflictBanner';
import { ToastNotice } from './components/ToastNotice';
import { FileExplorer } from './components/FileExplorer';
import { OutlineNavigator } from './components/OutlineNavigator';
import { WorkbenchModeToggle } from './components/WorkbenchModeToggle';
import { WorkbenchModeLayer } from './components/WorkbenchModeLayer';
import { GitBranchPanel } from './components/GitBranchPanel';
import { GitCenterPanel } from './components/GitCenterPanel';
import { GitWorkingTreePanel } from './components/GitWorkingTreePanel';
import { GitDiffFullscreen } from './components/GitDiffFullscreen';
import { ReviewCanvasPanel } from './components/ReviewCanvasPanel';
import { ReviewDiffFullscreen } from './components/ReviewDiffFullscreen';
import { ReviewInspectorPanel } from './components/ReviewInspectorPanel';
import { ReviewReadyNotice } from './components/ReviewReadyNotice';
import { WorkbenchActionDock } from './components/WorkbenchActionDock';
import { RuntimeConfigPanel } from './components/RuntimeConfigPanel';

import { fetchHotFiles, fetchMainlineFile, fetchRepoIntegrity, repairBookLayout, updateMainlineFile } from './api/checkout';

import { buildRollingContinuationPayload, fetchRollingWorkbenchState, runDeductionStream, stopDeductionStream, runBatchInit, runStyleInit, type RollingAuthorWritingBrief, type RollingWorkbenchState } from './api/orchestration';
import { type DraftConfirmResponse, type MaterializedChapter, type PostConfirmWorldPayload } from './api/draft';
import { createConversation } from './api/session';
import { ApiError } from './api/client';
import { DEFAULT_HOT_FILES } from './config/hotFiles';
import { resolveFileType } from './lib/fileType';
import { findLatestUserMessage } from './lib/tailRewrite.js';
import { getAgentLabel, getFileTypeLabel, getFsmStateLabel, getUiCopy } from './i18n/ui';
import { DEFAULT_WORKBENCH_THEME_ID } from './lib/themePresets';
import { AgentKey, HotFileItem, ReasoningTrace, RepoIntegrity, WorkbenchMode } from './types/store';
import { isTargetPathForbidden, getErrorMessage, isLayoutRepairRequired, extractIntegrityFromError, extractReqIdFromErrorMessage, formatVisibleDeductionError, formatSuppressedBackendErrorTitle } from './lib/errorUtils';
import { mapConversationMessages, normalizeChangedFilesPayload } from './lib/conversationUtils';
import { MAX_SUPPRESSED_DEBUG_LOGS, shouldSuppressBackendError, type SuppressedBackendErrorLog } from './lib/errorSuppression';
import { buildWorkbenchActions } from './lib/workbenchActions';
import { isSameConversationScope } from './lib/conversationScope';

const REASONING_FLUSH_DELAY_MS = 100;

function compactList(values: number[] | undefined, empty = '无'): string {
    if (!values || values.length === 0) return empty;
    return values.join(', ');
}

function compactBriefText(value: unknown, limit = 56): string {
    const text = String(value || '').trim();
    if (!text) return '未填写';
    if (text.length <= limit) return text;
    return `${text.slice(0, limit - 1).trim()}…`;
}

function buildRollingBriefLines(brief?: RollingAuthorWritingBrief): string[] {
    if (!brief) return [];
    const cards = brief.chapter_cards || [];
    const firstCard = cards[0];
    const sourceNames = (brief.truth_sources || [])
        .filter((source) => source.exists)
        .map((source) => source.name)
        .slice(0, 5);
    const lines = [
        `写作依据：本轮 ${compactList(brief.batch?.selected_card_numbers)}，目标文件 ${brief.target_file}`,
        `进度游标：已归档 ${compactList(brief.progress_cursor?.accepted_chapter_numbers)}；待审 ${compactList(brief.progress_cursor?.pending_review_chapter_numbers)}`,
    ];
    if (firstCard) {
        lines.push(`首章卡：CH${firstCard.number} ${compactBriefText(firstCard.title, 34)}｜目标：${compactBriefText(firstCard.goal)}`);
        lines.push(`冲突/兑现：${compactBriefText(firstCard.conflict)} → ${compactBriefText(firstCard.payoff)}`);
    }
    if (cards.length > 1) {
        lines.push(`其余章节卡：${cards.slice(1).map((card) => `CH${card.number}`).join(', ')}`);
    }
    if (sourceNames.length > 0) {
        lines.push(`读取依据：${sourceNames.join(', ')}`);
    }
    if (brief.quality_and_style?.style_advisory_active) {
        lines.push('文风：作为模仿提示，不作为卡死调度闸门。');
    }
    lines.push('边界：工作台不写正文，只有 continuation Agent 可写 chapter_draft.md。');
    return lines;
}

function RailIcon({ path, active }: { path: ReactNode; active: boolean }) {
    return (
        <span
            className={`inline-flex h-5 w-5 items-center justify-center transition-colors ${
                active ? 'text-[var(--color-dark-text-main)]' : 'text-[var(--color-dark-text-faint)]'
            }`}
            aria-hidden="true"
        >
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5">
                {path}
            </svg>
        </span>
    );
}

export default function App() {
    const store = useAppStore();
    const copy = getUiCopy(store.uiLanguage);
    const [editorContent, setEditorContent] = useState('');
    const [editorSaveState, setEditorSaveState] = useState<'idle' | 'saving' | 'error'>('idle');
    // ── Human edit mode (extracted to useHumanEditMode) ──
    const [suppressedBackendErrors, setSuppressedBackendErrors] = useState<SuppressedBackendErrorLog[]>([]);
    const [suppressedDebugOpen, setSuppressedDebugOpen] = useState(false);
    const [runtimeConfigOpen, setRuntimeConfigOpen] = useState(false);
    const [bootstrapState, setBootstrapState] = useState<'bootstrapping' | 'loaded'>('bootstrapping');
    const [repoIntegrity, setRepoIntegrity] = useState<RepoIntegrity | null>(null);
    const [mainlineFileState, setMainlineFileState] = useState<{ exists: boolean; virtual: boolean } | null>(null);
    const [repairPending, setRepairPending] = useState(false);
    const [commandInput, setCommandInput] = useState('');
    const [rewriteUserMessageId, setRewriteUserMessageId] = useState<string | null>(null);
    const [worldInitActionState, setWorldInitActionState] = useState<{
        runState: 'idle' | 'running' | 'success' | 'error';
        progress: {
            current: number;
            total: number;
            label: string;
            lines: string[];
        };
    }>({
        runState: 'idle',
        progress: {
            current: 0,
            total: 1,
            label: '等待启动',
            lines: [],
        },
    });
    const [postConfirmHandoffState, setPostConfirmHandoffState] = useState<{
        runState: 'idle' | 'running' | 'success' | 'error';
        payload: PostConfirmWorldPayload | null;
        materializedChapters: MaterializedChapter[];
        progress: {
            current: number;
            total: number;
            label: string;
            lines: string[];
        };
    }>({
        runState: 'idle',
        payload: null,
        materializedChapters: [],
        progress: {
            current: 0,
            total: 3,
            label: '等待正文归档',
            lines: [],
        },
    });
    const [styleInitActionState, setStyleInitActionState] = useState<{
        runState: 'idle' | 'running' | 'success' | 'error';
        progress: {
            current: number;
            total: number;
            label: string;
            lines: string[];
        };
    }>({
        runState: 'idle',
        progress: {
            current: 0,
            total: 1,
            label: '等待启动',
            lines: [],
        },
    });
    const [rollingActionState, setRollingActionState] = useState<{
        runState: 'idle' | 'running' | 'success' | 'error';
        state: RollingWorkbenchState | null;
        progress: {
            current: number;
            total: number;
            label: string;
            lines: string[];
        };
    }>({
        runState: 'idle',
        state: null,
        progress: {
            current: 0,
            total: 1,
            label: '等待刷新',
            lines: [],
        },
    });
    const saveTicketRef = useRef(0);
    const streamAbortControllerRef = useRef<AbortController | null>(null);
    const streamStableUpstreamConversationIdRef = useRef<string | null>(null);
    const streamTaskIdRef = useRef<string | null>(null);

    useEffect(() => {
        document.documentElement.dataset.workbenchTheme = DEFAULT_WORKBENCH_THEME_ID;
        return () => {
            delete document.documentElement.dataset.workbenchTheme;
        };
    }, []);

    useEffect(() => {
        document.documentElement.lang = store.uiLanguage;
    }, [store.uiLanguage]);

    const appendSuppressedBackendError = useCallback((code: string, message: string) => {
        const reqId = extractReqIdFromErrorMessage(message);
        setSuppressedBackendErrors((prev) => {
            const isDuplicate = prev.some((item) =>
                reqId
                    ? (item.reqId === reqId && item.code === code)
                    : (item.code === code && item.message === message)
            );
            if (isDuplicate) return prev;
            const nextEntry: SuppressedBackendErrorLog = {
                id: `supp_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
                ts: Date.now(),
                code,
                message,
                reqId,
            };
            return [...prev, nextEntry].slice(-MAX_SUPPRESSED_DEBUG_LOGS);
        });
    }, []);

    const loadRepoIntegrity = useCallback(async (bookRefOverride?: { kind: 'book_name' | 'book_id'; value: string }) => {
        const bookRef = bookRefOverride ?? { kind: store.bookRef.kind, value: store.bookRef.value };
        if (!bookRef.value) return null;
        try {
            const integrity = await fetchRepoIntegrity(bookRef);
            setRepoIntegrity(integrity);
            return integrity;
        } catch (err) {
            const fallbackIntegrity = extractIntegrityFromError(err);
            if (fallbackIntegrity) {
                setRepoIntegrity(fallbackIntegrity);
                return fallbackIntegrity;
            }
            console.error('Failed to load repo integrity:', err);
            return null;
        }
    }, [store.bookRef.kind, store.bookRef.value]);

    useEffect(() => {
        let cancelled = false;

        const bootstrap = async () => {
            const params = new URLSearchParams(window.location.search);
            const bookId = params.get('book_id');
            const initialFile = params.get('file') || 'world_model.md';
            if (!bookId) {
                window.location.href = '/bookshelf.html';
                return;
            }

            const bookRef = { kind: 'book_id' as const, value: bookId };
            store.setAddressingContext(bookRef, initialFile, resolveFileType(initialFile));
            setIsEditing(false);
            setEditDraft('');
            setEditBaseEtag('');
            setSaveConflict(null);
            setEditorContent('');
            setEditorSaveState('idle');
            setMainlineFileState(null);

            try {
                const integrity = await loadRepoIntegrity(bookRef);
                if (cancelled) return;
                if (integrity?.exists === false) {
                    setBootstrapState('loaded');
                    return;
                }

                try {
                    const { files, integrity: hotIntegrity } = await fetchHotFiles(bookRef);
                    setRepoIntegrity(hotIntegrity);
                    store.setHotFiles(files.length > 0 ? files : DEFAULT_HOT_FILES);
                } catch {
                    store.setHotFiles(DEFAULT_HOT_FILES);
                }

                try {
                    const mainline = await fetchMainlineFile(bookRef, initialFile);
                    setRepoIntegrity(mainline.integrity);
                    setMainlineFileState({ exists: mainline.exists, virtual: mainline.virtual });
                    store.setMainlineFact(mainline.content, mainline.etag);
                    setEditorContent(mainline.content);
                } catch {
                    // non-fatal
                }

                setBootstrapState('loaded');
            } catch (err) {
                console.error('Failed to load book:', err);
                setBootstrapState('loaded');
            }
        };

        void bootstrap();
        return () => { cancelled = true; };
    }, [loadRepoIntegrity]);

    const handleBackToBookshelf = useCallback(() => {
        window.location.href = '/bookshelf.html';
    }, []);

    const loadMainline = useCallback(async (
        targetFile?: string,
        options?: { preserveDraftReview?: boolean }
    ) => {
        if (!store.bookRef.value) return;
        try {
            const fileName = targetFile || store.activeFile;
            const { content, etag, exists, virtual, integrity } = await fetchMainlineFile(store.bookRef, fileName);
            setRepoIntegrity(integrity);
            setMainlineFileState({ exists, virtual });
            store.setMainlineFact(content, etag);
            const runtimeState = useAppStore.getState();
            const shouldPreserveReview = Boolean(
                options?.preserveDraftReview
                && (runtimeState.draftCommitId || runtimeState.reviewTargetFile || runtimeState.reviewReadyNotice)
                && (runtimeState.fsmState === 'REVIEW' || runtimeState.fsmState === 'CONFLICT')
            );
            if (!shouldPreserveReview) {
                store.setFsmState('IDLE');
            }
        } catch (err) {
            const integrity = extractIntegrityFromError(err);
            if (integrity) {
                setRepoIntegrity(integrity);
            }
            setMainlineFileState(null);
            store.setMainlineFact('', '');
            const runtimeState = useAppStore.getState();
            const shouldPreserveReview = Boolean(
                options?.preserveDraftReview
                && (runtimeState.draftCommitId || runtimeState.reviewTargetFile || runtimeState.reviewReadyNotice)
                && (runtimeState.fsmState === 'REVIEW' || runtimeState.fsmState === 'CONFLICT')
            );
            if (!shouldPreserveReview) {
                store.setFsmState('IDLE');
            }
            if (!isLayoutRepairRequired(err)) {
                console.error('Failed to load mainline fact:', err);
            }
        }
    }, [store.bookRef.kind, store.bookRef.value, store.activeFile]);

    const {
        isEditing, setIsEditing,
        setEditBaseEtag,
        editDraft, setEditDraft,
        isSaving,
        saveConflict, setSaveConflict,
        handleEnterEdit, handleCancelEdit, handleSaveEdit,
    } = useHumanEditMode({
        store,
        editorContent,
        setEditorContent,
        repoIntegrity,
        setRepoIntegrity,
        getErrorMessage,
        loadMainline,
    });

    const runPostConfirmWorldDistill = useCallback(async (
        payload: PostConfirmWorldPayload,
        materializedChapters: MaterializedChapter[],
    ) => {
        const materializedCount = materializedChapters.length;
        if (!payload || materializedCount <= 0) return;
        setPostConfirmHandoffState((current) => ({
            ...current,
            payload,
            materializedChapters,
        }));
        if (postConfirmHandoffState.runState === 'running') {
            store.setUiNotice({
                type: 'info',
                message: '正文已归档；状态卡接棒任务正在运行。',
                ts: Date.now(),
            });
            return;
        }
        if (store.fsmState === 'THINKING') {
            store.setUiNotice({
                type: 'info',
                message: '正文已归档；当前 Agent 正在输出，稍后可在动作面板运行状态接棒。',
                ts: Date.now(),
            });
            return;
        }
        if (payload.no_prose_boundary?.payload_contains_chapter_prose) {
            store.setUiNotice({
                type: 'error',
                message: '状态接棒已拦截：payload 不应包含章节正文。',
                ts: Date.now(),
            });
            setPostConfirmHandoffState({
                runState: 'error',
                payload,
                materializedChapters,
                progress: {
                    current: 0,
                    total: 3,
                    label: '接棒边界失败',
                    lines: ['状态接棒已拦截：payload_contains_chapter_prose=true。'],
                },
            });
            return;
        }
        const lines = [
            `章节已入库：${materializedCount} 章`,
            `正式归档：${materializedChapters.map((chapter) => chapter.file_name).join(', ')}`,
            '交给 world_model 路由刷新 status_card.md，并按需更新 world_model.md/domain_rules.md。',
        ];
        const setProgress = (
            runState: 'running' | 'success' | 'error',
            label: string,
            current: number,
            total = 3,
        ) => {
            setPostConfirmHandoffState({
                runState,
                payload,
                materializedChapters,
                progress: {
                    current,
                    total,
                    label,
                    lines: [...lines],
                },
            });
        };
        setProgress('running', '确认后状态接棒', 0);
        try {
            let draftReady = false;
            let draftTargetFile = payload.active_file;
            let draftCommitId = '';
            let changedFiles: string[] = [];
            await runDeductionStream(payload.intent, useAppStore.getState(), {
                onAck: (ack) => {
                    const routed = typeof ack?.routed_agent === 'string' ? ack.routed_agent : 'world_model';
                    lines.push(`Dify 路由：${routed}`);
                    setProgress('running', '读取正式章节', 1);
                },
                onStage: (stage) => {
                    const text = typeof stage?.stage_text === 'string' ? stage.stage_text : '';
                    if (text) {
                        lines.push(text);
                        setProgress('running', '状态蒸馏中', 1);
                    }
                },
                onDraftReady: (draftPayload) => {
                    draftReady = true;
                    draftTargetFile = typeof draftPayload?.file_name === 'string' ? draftPayload.file_name : payload.active_file;
                    draftCommitId = typeof draftPayload?.commit_id === 'string' ? draftPayload.commit_id : '';
                    const draftContent = typeof draftPayload?.content === 'string' ? draftPayload.content : '';
                    const branch = typeof draftPayload?.branch === 'string' ? draftPayload.branch : store.draftBranch;
                    const diffPreview = typeof draftPayload?.diff_preview === 'string' ? draftPayload.diff_preview : '';
                    changedFiles = normalizeChangedFilesPayload(draftPayload?.changed_files);
                    const reviewChangedFiles = changedFiles.includes(draftTargetFile)
                        ? changedFiles
                        : [draftTargetFile, ...changedFiles];
                    store.setSandboxDraft(draftContent, draftCommitId || null);
                    store.setReviewTarget(draftTargetFile, reviewChangedFiles);
                    store.setReviewReadyNotice({
                        fileName: draftTargetFile,
                        branch,
                        commitId: draftCommitId || null,
                        diffPreview,
                        changedFiles: reviewChangedFiles,
                        ts: Date.now(),
                    });
                    store.setFsmState('REVIEW');
                    store.setWorkbenchMode('review');
                    void fetchMainlineFile(store.bookRef, draftTargetFile)
                        .then(({ content, etag }) => {
                            store.setReviewMainlineFact(content, etag);
                        })
                        .catch((err) => {
                            console.warn('Failed to load post-confirm review target mainline:', err);
                            store.setReviewMainlineFact('', '');
                        });
                    lines.push(`生成审阅草稿：${draftTargetFile}${draftCommitId ? ` @ ${draftCommitId.slice(0, 8)}` : ''}`);
                    setProgress('running', '等待审阅确权', 2);
                },
                onDone: (donePayload) => {
                    const doneChangedFiles = normalizeChangedFilesPayload(donePayload?.changed_files);
                    if (!changedFiles.length && doneChangedFiles.length) {
                        changedFiles = doneChangedFiles;
                    }
                    if (!draftCommitId && typeof donePayload?.sync_commit_id === 'string') {
                        draftCommitId = donePayload.sync_commit_id;
                    }
                    if (changedFiles.length) {
                        lines.push(`待审更新：${changedFiles.join(', ')}`);
                    } else {
                        lines.push('world_model 路由完成：没有检测到需要写入的状态变更。');
                    }
                },
                onError: (errorPayload) => {
                    const code = typeof errorPayload?.code === 'string' ? errorPayload.code : 'STREAM_ERROR';
                    const message = typeof errorPayload?.message === 'string' ? errorPayload.message : '确认后状态接棒失败';
                    throw new ApiError(
                        typeof errorPayload?.status === 'number' ? errorPayload.status : 500,
                        code,
                        message,
                        errorPayload,
                    );
                },
            }, {
                routeAgentKey: 'world_agent',
                activeFile: payload.active_file,
                fileType: payload.file_type,
                writeScope: payload.write_scope,
                baseEtag: '',
                detachedJob: true,
                difyUser: payload.dify_user,
            });
            if (draftReady) {
                try {
                    const { files, integrity } = await fetchHotFiles(store.bookRef);
                    setRepoIntegrity(integrity);
                    if (files.length > 0) {
                        store.setHotFiles(files);
                    }
                } catch (err) {
                    console.warn('Failed to refresh hot files after post-confirm world distill:', err);
                }
                await loadMainline(store.activeFile, { preserveDraftReview: true });
                const latestState = useAppStore.getState();
                if (draftTargetFile !== latestState.activeFile) {
                    try {
                        const { content, etag } = await fetchMainlineFile(latestState.bookRef, draftTargetFile);
                        latestState.setReviewMainlineFact(content, etag);
                    } catch (err) {
                        console.warn('Failed to refresh post-confirm review target mainline:', err);
                    }
                }
            }
            setProgress('success', draftReady ? '等待作者审阅状态更新' : '状态接棒已完成', 3);
            store.setUiNotice({
                type: draftReady ? 'info' : 'success',
                message: draftReady
                    ? '正文已归档；状态卡/世界观草稿已生成，等待作者审阅确权。'
                    : '正文已归档，world_model 路由未检测到需要写入的状态变更。',
                ts: Date.now(),
            });
        } catch (err: any) {
            const message = err instanceof ApiError
                ? formatVisibleDeductionError(err.code, err.message)
                : (err?.message || '确认后状态接棒失败');
            lines.push(`错误：${message}`);
            setProgress('error', '状态接棒失败', 0);
            store.setUiNotice({
                type: 'error',
                message,
                ts: Date.now(),
            });
        }
    }, [loadMainline, postConfirmHandoffState.runState, setRepoIntegrity, store]);

    const runPostConfirmWorldDistillFromResult = useCallback(async (result: DraftConfirmResponse) => {
        const payload = result.post_confirm_payload;
        const materializedChapters = result.materialized_chapters || [];
        if (!payload || materializedChapters.length <= 0) return;
        await runPostConfirmWorldDistill(payload, materializedChapters);
    }, [runPostConfirmWorldDistill]);

    const handleRunPostConfirmHandoff = useCallback(() => {
        const payload = postConfirmHandoffState.payload;
        const materializedChapters = postConfirmHandoffState.materializedChapters;
        if (!payload || materializedChapters.length <= 0) {
            store.setUiNotice({
                type: 'info',
                message: '没有可重试的正文归档接棒任务。',
                ts: Date.now(),
            });
            return;
        }
        void runPostConfirmWorldDistill(payload, materializedChapters);
    }, [
        postConfirmHandoffState.materializedChapters,
        postConfirmHandoffState.payload,
        runPostConfirmWorldDistill,
        store,
    ]);

    const {
        reviewDiffFullscreenOpen,
        setReviewDiffFullscreenOpen,
        loadReviewTargetMainline,
        handleConfirm,
        handleRollback,
        handleRefreshLock,
        pendingReviewTargetFile,
        hasPendingDraftDecision,
        hasReviewWorkspace,
    } = useDraftReview({
        store,
        repoIntegrity,
        setRepoIntegrity,
        loadMainline,
        onPostConfirm: runPostConfirmWorldDistillFromResult,
    });

    const {
        loadGitWorkbench,
        handleGitCheckout,
        handleGitCreateBranch,
        handleGitMerge,
        handleGitHardRollback,
        handleGitOpenCommitDiff,
        handleGitStage,
        handleGitUnstage,
        handleGitStageAll,
        handleGitCommit,
    } = useGitWorkbench({
        store,
        repoIntegrity,
        setRepoIntegrity,
        hasPendingDraftDecision,
        loadMainline,
        loadRepoIntegrity,
    });


    useEffect(() => {
        void loadMainline();
    }, [loadMainline]);

    useEffect(() => {
        setEditorContent(store.mainlineContent);
    }, [store.mainlineContent, store.activeFile]);

    useEffect(() => {
        if (store.workbenchMode !== 'editor') return;
        if (isEditing) return;          // Human edit mode: skip autosave
        if (editorContent === store.mainlineContent) return;
        if (!store.bookRef.value || !store.activeFile) return;

        const snapshotContent = editorContent;
        const snapshotEtag = store.baseEtag;
        const snapshotFile = store.activeFile;
        const snapshotBookRef = { kind: store.bookRef.kind, value: store.bookRef.value } as const;
        const ticket = saveTicketRef.current + 1;
        saveTicketRef.current = ticket;

        const timer = window.setTimeout(async () => {
            setEditorSaveState('saving');
            try {
                const response = await updateMainlineFile(
                    snapshotBookRef,
                    snapshotFile,
                    snapshotContent,
                    snapshotEtag
                );
                if (saveTicketRef.current !== ticket) return;
                store.setMainlineFact(snapshotContent, response.etag);
                setEditorSaveState('idle');
            } catch (err) {
                if (saveTicketRef.current !== ticket) return;
                setEditorSaveState('error');
                const message = getErrorMessage(err, '未知异常');
                store.setUiNotice({
                    type: 'error',
                    message: `主编辑区保存失败：${message}`,
                    ts: Date.now(),
                });
            }
        }, 600);

        return () => {
            window.clearTimeout(timer);
        };
    }, [
        editorContent,
        isEditing,
        store.mainlineContent,
        store.baseEtag,
        store.activeFile,
        store.workbenchMode,
        store.bookRef.kind,
        store.bookRef.value,
    ]);

    const getLatestUserMessage = useCallback(() => findLatestUserMessage(store.chatMessages), [store.chatMessages]);

    const handleStopStream = useCallback(async () => {
        const taskId = streamTaskIdRef.current;
        streamAbortControllerRef.current?.abort();
        if (taskId) {
            void stopDeductionStream(store.bookRef, store.activeFile, taskId).catch((err) => {
                console.warn('Native stop failed after local abort fallback:', err);
            });
        }
    }, [store.activeFile, store.bookRef]);

    const handleRunWorldInitAction = useCallback(async (options?: { forceRebuild?: boolean }) => {
        const forceRebuild = options?.forceRebuild === true;
        if (worldInitActionState.runState === 'running') return;
        if (store.fsmState === 'THINKING') {
            store.setUiNotice({
                type: 'info',
                message: '当前 Agent 正在输出，稍后再执行工作台动作。',
                ts: Date.now(),
            });
            return;
        }
        const lines: string[] = [
            forceRebuild
                ? '准备完整重跑 world/status 初始化 pipeline…'
                : '准备调用后端初始化 pipeline…',
        ];
        let totalBatches = 1;
        let completedBatches = 0;
        const setProgress = (
            runState: 'running' | 'success' | 'error',
            label: string,
            current = completedBatches,
            total = totalBatches,
        ) => {
            setWorldInitActionState({
                runState,
                progress: {
                    current,
                    total: Math.max(total, 1),
                    label,
                    lines: [...lines],
                },
            });
        };
        setProgress('running', forceRebuild ? '准备完整重跑' : '准备检查/补齐', 0, 1);
        const pushLine = (line: string, label: string, current = completedBatches, total = totalBatches) => {
            lines.push(line);
            setProgress('running', label, current, total);
        };
        try {
            await runBatchInit(store.bookRef, {
                onAck: (d) => {
                    totalBatches = Math.max(d.total_batches || 1, 1);
                    completedBatches = 0;
                    pushLine(
                        `开始：${totalBatches} 个批次${forceRebuild ? '（完整重跑）' : ''}`,
                        forceRebuild ? '完整重跑已连接 pipeline' : '已连接 pipeline',
                        0,
                        totalBatches,
                    );
                },
                onProgress: (d) => {
                    totalBatches = Math.max(d.total || totalBatches, 1);
                    pushLine(`处理中 ${d.batch_index + 1}/${totalBatches}: ${d.title}`, `处理中 ${d.batch_index + 1}/${totalBatches}`, d.batch_index, totalBatches);
                },
                onBatchDone: (d) => {
                    totalBatches = Math.max(d.total || totalBatches, 1);
                    completedBatches = Math.max(completedBatches, d.batch_index + 1);
                    pushLine(`完成 ${completedBatches}/${totalBatches}: ${d.title}`, `完成 ${completedBatches}/${totalBatches}`, completedBatches, totalBatches);
                },
                onBatchError: (d) => {
                    pushLine(`失败: ${d.title} - ${d.error}`, '批次失败');
                },
                onDone: (d) => {
                    const skipped = d.skipped
                        ? (d.status_card_committed ? '；已补齐状态卡' : '；已存在，跳过重建')
                        : '';
                    lines.push(`完成${skipped}：成功 ${d.completed}，失败 ${d.failed}`);
                    const total = Math.max(totalBatches, d.completed + d.failed, 1);
                    const successLabel = forceRebuild
                        ? '完整重跑完成'
                        : d.skipped
                            ? '检查完成'
                            : '初始化完成';
                    setWorldInitActionState({
                        runState: d.failed > 0 ? 'error' : 'success',
                        progress: {
                            current: d.failed > 0 ? Math.min(d.completed, total) : total,
                            total,
                            label: d.failed > 0 ? '完成但存在失败' : successLabel,
                            lines: [...lines],
                        },
                    });
                    const currentFile = useAppStore.getState().activeFile;
                    if (currentFile === 'world_model.md' || currentFile === 'status_card.md') {
                        void loadMainline(currentFile);
                    }
                },
                onError: (d) => {
                    lines.push(`错误: ${d.message}`);
                    setProgress('error', '初始化失败');
                },
            }, { forceRebuild });
        } catch (err: any) {
            lines.push(`错误: ${err?.message || '批量初始化失败'}`);
            setWorldInitActionState({
                runState: 'error',
                progress: {
                    current: completedBatches,
                    total: Math.max(totalBatches, 1),
                    label: '初始化失败',
                    lines: [...lines],
                },
            });
        }
    }, [loadMainline, store, worldInitActionState.runState]);

    const handleRunStyleInitAction = useCallback(async (options?: { forceRebuild?: boolean }) => {
        const forceRebuild = options?.forceRebuild === true;
        if (styleInitActionState.runState === 'running') return;
        if (store.fsmState === 'THINKING') {
            store.setUiNotice({
                type: 'info',
                message: '当前 Agent 正在输出，稍后再执行工作台动作。',
                ts: Date.now(),
            });
            return;
        }
        const lines: string[] = [
            forceRebuild
                ? '准备完整重跑文风 diagnostics pipeline…'
                : '准备检查/补齐文风 diagnostics pipeline…',
        ];
        let totalSteps = 1;
        let currentStep = 0;
        const setProgress = (
            runState: 'running' | 'success' | 'error',
            label: string,
            current = currentStep,
            total = totalSteps,
        ) => {
            setStyleInitActionState({
                runState,
                progress: {
                    current,
                    total: Math.max(total, 1),
                    label,
                    lines: [...lines],
                },
            });
        };
        setProgress('running', forceRebuild ? '准备完整重跑' : '准备检查/补齐', 0, 1);
        const pushLine = (line: string, label: string, current = currentStep, total = totalSteps) => {
            lines.push(line);
            setProgress('running', label, current, total);
        };
        try {
            await runStyleInit(store.bookRef, {
                onAck: (d) => {
                    totalSteps = Math.max(d.total_steps || 1, 1);
                    currentStep = 0;
                    pushLine(
                        `开始：${totalSteps} 个步骤${forceRebuild ? '（完整重跑）' : ''}`,
                        forceRebuild ? '完整重跑已连接 pipeline' : '已连接 pipeline',
                        0,
                        totalSteps,
                    );
                },
                onProgress: (d) => {
                    totalSteps = Math.max(d.total || totalSteps, 1);
                    currentStep = Math.max(0, d.step_index);
                    pushLine(`处理中 ${Math.min(currentStep + 1, totalSteps)}/${totalSteps}: ${d.title}`, `处理中 ${Math.min(currentStep + 1, totalSteps)}/${totalSteps}`, currentStep, totalSteps);
                },
                onDone: (d) => {
                    const skipped = d.skipped ? '；已有成品，跳过重建' : '';
                    const updated = d.updated_artifacts?.length ? `；更新 ${d.updated_artifacts.join(', ')}` : '';
                    lines.push(`完成${skipped}${updated}：成功 ${d.completed}，失败 ${d.failed}`);
                    const total = Math.max(totalSteps, d.completed + d.failed, 1);
                    setStyleInitActionState({
                        runState: d.failed > 0 ? 'error' : 'success',
                        progress: {
                            current: d.failed > 0 ? Math.min(d.completed, total) : total,
                            total,
                            label: d.failed > 0 ? '完成但存在失败' : d.skipped ? '检查完成' : '文风初始化完成',
                            lines: [...lines],
                        },
                    });
                    const currentFile = useAppStore.getState().activeFile;
                    if (
                        currentFile === 'style_fingerprint.md'
                        || currentFile === 'style_review.md'
                        || currentFile === 'style_constraints_for_continuation.md'
                        || currentFile === 'style_guide.md'
                    ) {
                        void loadMainline(currentFile);
                    }
                },
                onError: (d) => {
                    lines.push(`错误: ${d.message}`);
                    setProgress('error', '文风初始化失败');
                },
            }, { forceRebuild, sourceCount: 12 });
        } catch (err: any) {
            lines.push(`错误: ${err?.message || '文风初始化失败'}`);
            setStyleInitActionState({
                runState: 'error',
                progress: {
                    current: currentStep,
                    total: Math.max(totalSteps, 1),
                    label: '文风初始化失败',
                    lines: [...lines],
                },
            });
        }
    }, [loadMainline, store, styleInitActionState.runState]);

    const handleRefreshRollingState = useCallback(async () => {
        if (rollingActionState.runState === 'running') return;
        if (store.fsmState === 'THINKING') {
            store.setUiNotice({
                type: 'info',
                message: '当前 Agent 正在输出，稍后再刷新滚动队列。',
                ts: Date.now(),
            });
            return;
        }
        const lines = ['读取 chapter_outline.md 与 chapter_draft.md…'];
        setRollingActionState((prev) => ({
            ...prev,
            runState: 'running',
            progress: {
                current: 0,
                total: 1,
                label: '刷新队列',
                lines: [...lines],
            },
        }));
        try {
            const response = await fetchRollingWorkbenchState(store.bookRef, { batchSize: 3 });
            const next = response.workbench_state;
            lines.push(`下一步：${next.next_action}`);
            lines.push(`已写：${next.written_chapter_numbers.length ? next.written_chapter_numbers.join(', ') : '无'}`);
            lines.push(`本轮：${next.selected_card_numbers.length ? next.selected_card_numbers.join(', ') : '无'}`);
            if (next.next_action === 'replenish_outline') {
                lines.push('章节卡已消耗完，需要先补纲。');
            }
            setRollingActionState({
                runState: 'success',
                state: next,
                progress: {
                    current: 1,
                    total: 1,
                    label: '队列已刷新',
                    lines,
                },
            });
        } catch (err: any) {
            lines.push(`错误：${err?.message || '滚动队列刷新失败'}`);
            setRollingActionState((prev) => ({
                ...prev,
                runState: 'error',
                progress: {
                    current: 0,
                    total: 1,
                    label: '刷新失败',
                    lines,
                },
            }));
        }
    }, [rollingActionState.runState, store]);

    const handleRunRollingContinuation = useCallback(async () => {
        if (rollingActionState.runState === 'running') return;
        if (repoIntegrity?.needsRepair) {
            store.setUiNotice({
                type: 'error',
                message: '仓库核心布局不完整，修复后才能启动滚动续写。',
                ts: Date.now(),
            });
            return;
        }
        if (store.fsmState === 'THINKING') {
            store.setUiNotice({
                type: 'info',
                message: '当前 Agent 正在输出，稍后再启动滚动续写。',
                ts: Date.now(),
            });
            return;
        }
        if (store.fsmState === 'REVIEW' || store.fsmState === 'CONFLICT' || hasPendingDraftDecision) {
            store.setWorkbenchMode('review');
            store.setUiNotice({
                type: 'info',
                message: '当前已有待审草稿，先确权或回滚后再启动下一轮滚动续写。',
                ts: Date.now(),
            });
            return;
        }

        const lines = ['刷新滚动队列…'];
        const setRunningProgress = (current: number, total: number, label: string, nextLines = lines) => {
            setRollingActionState((prev) => ({
                ...prev,
                runState: 'running',
                progress: {
                    current,
                    total,
                    label,
                    lines: [...nextLines],
                },
            }));
        };
        setRunningProgress(0, 4, '准备续写');

        try {
            const payload = await buildRollingContinuationPayload(store.bookRef, { batchSize: 3 });
            const nextState = payload.workbench_state;
            lines.push(`本轮章节：${nextState.selected_card_numbers.length ? nextState.selected_card_numbers.join(', ') : '无'}`);
            lines.push(...buildRollingBriefLines(payload.author_writing_brief));
            lines.push('已生成章节执行包，交给 continuation Agent。');
            setRunningProgress(1, 4, '调用续写 Agent');

            let draftReady = false;
            let draftCommitId = '';
            let draftTargetFile = 'chapter_draft.md';
            let changedFiles: string[] = [];
            const abortController = new AbortController();
            await runDeductionStream(payload.intent, useAppStore.getState(), {
                onAck: (ack) => {
                    const routed = typeof ack?.routed_agent === 'string' ? ack.routed_agent : 'continuation_agent';
                    lines.push(`续写 Agent 已接单：${routed}`);
                    setRunningProgress(2, 4, '续写中');
                },
                onStage: (stage) => {
                    const text = typeof stage?.stage_text === 'string' ? stage.stage_text : '';
                    if (text) {
                        lines.push(`执行阶段：${text}`);
                        setRunningProgress(2, 4, '续写中');
                    }
                },
                onDraftReady: (draftPayload) => {
                    draftReady = true;
                    draftTargetFile = typeof draftPayload?.file_name === 'string' ? draftPayload.file_name : 'chapter_draft.md';
                    draftCommitId = typeof draftPayload?.commit_id === 'string' ? draftPayload.commit_id : '';
                    const draftContent = typeof draftPayload?.content === 'string' ? draftPayload.content : '';
                    const branch = typeof draftPayload?.branch === 'string' ? draftPayload.branch : store.draftBranch;
                    const diffPreview = typeof draftPayload?.diff_preview === 'string' ? draftPayload.diff_preview : '';
                    changedFiles = normalizeChangedFilesPayload(draftPayload?.changed_files);
                    const reviewChangedFiles = changedFiles.includes(draftTargetFile)
                        ? changedFiles
                        : [draftTargetFile, ...changedFiles];
                    store.setSandboxDraft(draftContent, draftCommitId || null);
                    store.setReviewTarget(draftTargetFile, reviewChangedFiles);
                    if (draftTargetFile === store.activeFile) {
                        store.setReviewMainlineFact(store.mainlineContent, store.baseEtag);
                    } else {
                        void loadReviewTargetMainline(draftTargetFile);
                    }
                    store.setReviewReadyNotice({
                        fileName: draftTargetFile,
                        branch,
                        commitId: draftCommitId || null,
                        diffPreview,
                        changedFiles: reviewChangedFiles,
                        ts: Date.now(),
                    });
                    store.setFsmState('REVIEW');
                    store.setWorkbenchMode('review');
                    lines.push(`草稿已写入：${draftTargetFile}${draftCommitId ? ` @ ${draftCommitId.slice(0, 8)}` : ''}`);
                    setRunningProgress(3, 4, '进入审阅');
                },
                onDone: (donePayload) => {
                    const doneChangedFiles = normalizeChangedFilesPayload(donePayload?.changed_files);
                    if (!changedFiles.length && doneChangedFiles.length) {
                        changedFiles = doneChangedFiles;
                    }
                    if (!draftCommitId && typeof donePayload?.sync_commit_id === 'string') {
                        draftCommitId = donePayload.sync_commit_id;
                    }
                },
                onError: (errorPayload) => {
                    const code = typeof errorPayload?.code === 'string' ? errorPayload.code : 'STREAM_ERROR';
                    const message = typeof errorPayload?.message === 'string' ? errorPayload.message : '滚动续写失败';
                    throw new ApiError(
                        typeof errorPayload?.status === 'number' ? errorPayload.status : 500,
                        code,
                        message,
                        errorPayload,
                    );
                },
            }, {
                signal: abortController.signal,
                routeAgentKey: 'continuation_agent',
                activeFile: payload.target_file,
                fileType: payload.file_type,
                baseEtag: '',
                detachedJob: true,
                difyUser: payload.dify_user,
            });

            if (!draftReady) {
                lines.push('续写流程结束，但没有检测到 chapter_draft.md 草稿写入。');
                setRollingActionState((prev) => ({
                    ...prev,
                    runState: 'error',
                    progress: {
                        current: 3,
                        total: 4,
                        label: '未生成草稿',
                        lines: [...lines],
                    },
                }));
                return;
            }

            try {
                const { files, integrity } = await fetchHotFiles(store.bookRef);
                setRepoIntegrity(integrity);
                if (files.length > 0) {
                    store.setHotFiles(files);
                }
            } catch (err) {
                console.warn('Failed to refresh hot files after rolling continuation:', err);
            }
            await loadMainline(store.activeFile, { preserveDraftReview: true });
            if (draftTargetFile !== store.activeFile) {
                await loadReviewTargetMainline(draftTargetFile);
            }
            const refreshed = await fetchRollingWorkbenchState(store.bookRef, { batchSize: 3 });
            lines.push('审阅工作台已打开，等待作者确权或回滚。');
            setRollingActionState({
                runState: 'success',
                state: refreshed.workbench_state,
                progress: {
                    current: 4,
                    total: 4,
                    label: '已进入审阅',
                    lines,
                },
            });
            store.setUiNotice({
                type: 'success',
                message: draftCommitId
                    ? `滚动续写完成，草稿提交 ${draftCommitId.slice(0, 8)} 等待审阅。`
                    : '滚动续写完成，草稿等待审阅。',
                ts: Date.now(),
            });
        } catch (err: any) {
            const message = err instanceof ApiError
                ? formatVisibleDeductionError(err.code, err.message)
                : (err?.message || '滚动续写失败');
            lines.push(`错误：${message}`);
            setRollingActionState((prev) => ({
                ...prev,
                runState: 'error',
                progress: {
                    current: 0,
                    total: 4,
                    label: '续写失败',
                    lines: [...lines],
                },
            }));
            store.setUiNotice({
                type: 'error',
                message,
                ts: Date.now(),
            });
        }
    }, [
        hasPendingDraftDecision,
        loadMainline,
        loadReviewTargetMainline,
        repoIntegrity?.needsRepair,
        rollingActionState.runState,
        store,
    ]);

    const handleIntentSubmit = async (
        intent: string,
        options?: {
            rewriteUserMessageId?: string;
            routeAgentKey?: AgentKey;
            activeFile?: string;
            fileType?: HotFileItem['fileType'];
            baseEtag?: string;
            onAccepted?: () => void;
        }
    ) => {
        const batchInitKeywords = ['初始化', '批量初始化', '全量初始化', '重建', '重跑', '完整重跑', 'batch init', 'rebuild'];
        const isBatchInit = batchInitKeywords.some(kw => intent.includes(kw));
        const isWorldInitSurface = store.activeFile === 'world_model.md'
            || store.activeFile === 'status_card.md'
            || store.activeFile === 'domain_rules.md'
            || store.activeFileType === 'world_core';
        const isStyleInitSurface = store.activeFile === 'style_guide.md'
            || store.activeFile === 'style_fingerprint.md'
            || store.activeFile === 'style_review.md'
            || store.activeFile === 'style_constraints_for_continuation.md'
            || store.activeFileType === 'style';
        if (isBatchInit && (isWorldInitSurface || isStyleInitSurface) && !options?.rewriteUserMessageId) {
            const targetLabel = isWorldInitSurface ? '世界模型' : '文风档案';
            options?.onAccepted?.();
            store.setUiNotice({
                type: 'info',
                message: `${targetLabel}初始化/重建属于右下角「动作」面板；聊天助手用于读取、解释、联网核查和按作者讨论做局部修订。`,
                ts: Date.now(),
            });
            return;
        }

        if (repoIntegrity?.needsRepair) {
            store.setUiNotice({
                type: "error",
                message: "仓库核心布局不完整，修复后才能继续 AI 推演。",
                ts: Date.now(),
            });
            return;
        }
        const routeAgentKey = options?.routeAgentKey;
        const shouldBindConversationToActiveAgent = !routeAgentKey || routeAgentKey === store.activeAgent;
        if (!store.conversationId) {
            try {
                const payload = await createConversation(
                    { kind: store.bookRef.kind, value: store.bookRef.value },
                    store.activeAgent,
                    store.activeFile,
                );
                store.hydrateAgentConversation(
                    store.activeAgent,
                    payload.active_conversation_id || payload.conversation_id || null,
                    payload.upstream_conversation_id || null,
                    mapConversationMessages(payload.messages || []),
                    payload.conversations || [],
                );
            } catch (err) {
                console.error('Failed to create implicit conversation before send:', err);
                store.setUiNotice({
                    type: 'error',
                    message: '初始化会话失败',
                    ts: Date.now(),
                });
                return;
            }
        }
        if (options?.rewriteUserMessageId) {
            store.rewriteTailFromUserMessage(options.rewriteUserMessageId, intent);
        } else {
            store.pushUserMessage(intent);
        }
        setSuppressedBackendErrors([]);
        setSuppressedDebugOpen(false);
        setRewriteUserMessageId(null);
        if (options?.rewriteUserMessageId) {
            setCommandInput('');
        } else {
            options?.onAccepted?.();
        }
        const assistantMessageId = store.startAssistantMessage();
        streamStableUpstreamConversationIdRef.current = useAppStore.getState().upstreamConversationId;
        streamTaskIdRef.current = null;
        const abortController = new AbortController();
        streamAbortControllerRef.current = abortController;
        store.setFsmState('THINKING');
        const draftWriteState: {
            writeConfirmed: boolean;
            commitId: string | null;
            syncStatus: string;
            syncMessage: string;
            compatibilityPayloadDetected: boolean;
            reviewTargetFile: string | null;
            changedFiles: string[];
        } = {
            writeConfirmed: false,
            commitId: null,
            syncStatus: '',
            syncMessage: '',
            compatibilityPayloadDetected: false,
            reviewTargetFile: null,
            changedFiles: [],
        };
        let defenseToastShown = false;
        let streamErrorHandled = false;
        const deductionErrorToastKeys = new Set<string>();
        type ReasoningBufferKey = string;
        const reasoningBuffers = new Map<ReasoningBufferKey, {
            trace: ReasoningTrace;
            timer: number | null;
        }>();
        const getReasoningBufferKey = (trace: Pick<ReasoningTrace, 'label' | 'sourceEvent'>): ReasoningBufferKey =>
            `${trace.sourceEvent || ''}\u0000${trace.label}`;
        const flushReasoningBuffer = (key: ReasoningBufferKey) => {
            const buffered = reasoningBuffers.get(key);
            if (!buffered) return;
            if (buffered.timer !== null) {
                window.clearTimeout(buffered.timer);
            }
            reasoningBuffers.delete(key);
            store.appendAssistantReasoning(assistantMessageId, buffered.trace);
        };
        const flushReasoningBuffers = () => {
            Array.from(reasoningBuffers.keys()).forEach(flushReasoningBuffer);
        };
        const enqueueReasoningTrace = (trace: ReasoningTrace) => {
            if (!trace.append || trace.status === 'done') {
                flushReasoningBuffers();
                store.appendAssistantReasoning(assistantMessageId, trace);
                return;
            }
            const key = getReasoningBufferKey(trace);
            const buffered = reasoningBuffers.get(key);
            if (buffered) {
                buffered.trace = {
                    ...trace,
                    text: `${buffered.trace.text}${trace.text}`,
                    append: true,
                    status: trace.status || buffered.trace.status,
                };
                return;
            }
            const nextBuffered = {
                trace,
                timer: null as number | null,
            };
            nextBuffered.timer = window.setTimeout(() => {
                flushReasoningBuffer(key);
            }, REASONING_FLUSH_DELAY_MS);
            reasoningBuffers.set(key, nextBuffered);
        };
        const maybeShowDefenseToast = (code: string, message: string) => {
            if (defenseToastShown || !isTargetPathForbidden(code, message)) return;
            defenseToastShown = true;
            store.setUiNotice({
                type: 'error',
                message: '系统拦截：AI 试图非法越权修改只读档案（TARGET_PATH_FORBIDDEN）',
                ts: Date.now(),
            });
        };
        const maybeShowDeductionErrorToast = (code: string, message: string) => {
            const reqId = extractReqIdFromErrorMessage(message);
            const dedupeKey = reqId ? `req:${reqId}` : `sig:${code}:${message}`;
            if (deductionErrorToastKeys.has(dedupeKey)) return;
            deductionErrorToastKeys.add(dedupeKey);
            const visibleMessage = formatVisibleDeductionError(code, message);
            store.setUiNotice({
                type: 'error',
                message: `[${code}] ${visibleMessage}`,
                ts: Date.now(),
            });
        };
        try {
            await runDeductionStream(intent, useAppStore.getState(), {
                onAck: (payload) => {
                    const localThreadId = typeof payload?.thread_id === 'string' ? payload.thread_id : null;
                    if (localThreadId && shouldBindConversationToActiveAgent) {
                        store.setConversationId(localThreadId);
                    }
                    if (typeof payload?.task_id === 'string' && payload.task_id) {
                        streamTaskIdRef.current = payload.task_id;
                    }
                },
                onStage: (payload) => {
                    if (typeof payload?.task_id === 'string' && payload.task_id) {
                        streamTaskIdRef.current = payload.task_id;
                    }
                    const stageCode = typeof payload?.stage_code === 'string' ? payload.stage_code : 'progress';
                    const stageText = typeof payload?.stage_text === 'string' ? payload.stage_text : '';
                    if (!stageText) return;
                    const sourceEvent = typeof payload?.source_event === 'string' ? payload.source_event : undefined;
                    const nodeTitle = typeof payload?.node_title === 'string' ? payload.node_title : undefined;
                    const nodeType = typeof payload?.node_type === 'string' ? payload.node_type : undefined;
                    store.setAssistantStageProgress(assistantMessageId, {
                        stageCode,
                        stageText,
                        sourceEvent,
                        nodeTitle,
                        nodeType,
                    });
                },
                onReasoning: (payload) => {
                    if (typeof payload?.task_id === 'string' && payload.task_id) {
                        streamTaskIdRef.current = payload.task_id;
                    }
                    const text = typeof payload?.text === 'string' ? payload.text : '';
                    if (!text) return;
                    const label = typeof payload?.label === 'string' && payload.label
                        ? payload.label
                        : '已深度思考';
                    const sourceEvent = typeof payload?.source_event === 'string' ? payload.source_event : undefined;
                    const status = payload?.status === 'done' ? 'done' : 'streaming';
                    const append = status === 'streaming' && sourceEvent !== 'scratchpad_compacted';
                    enqueueReasoningTrace({
                        label,
                        text,
                        append,
                        sourceEvent,
                        status,
                    });
                },
                onPreview: (payload) => {
                    if (typeof payload?.task_id === 'string' && payload.task_id) {
                        streamTaskIdRef.current = payload.task_id;
                    }
                    const text = typeof payload?.text === 'string' ? payload.text : '';
                    if (!text) return;
                    const label = typeof payload?.label === 'string' && payload.label
                        ? payload.label
                        : '中间预览';
                    const sourceEvent = typeof payload?.source_event === 'string' ? payload.source_event : undefined;
                    store.appendAssistantPreview(assistantMessageId, {
                        label,
                        text,
                        sourceEvent,
                    });
                },
                onDelta: (delta, payload) => {
                    if (typeof payload?.task_id === 'string' && payload.task_id) {
                        streamTaskIdRef.current = payload.task_id;
                    }
                    flushReasoningBuffers();
                    store.appendAssistantDelta(assistantMessageId, delta, payload?.upstream_conversation_id || null);
                },
                onDraftReady: (payload) => {
                    const draftContent = typeof payload?.content === 'string' ? payload.content : '';
                    const commitId = typeof payload?.commit_id === 'string' ? payload.commit_id : '';
                    const etag = typeof payload?.etag === 'string' ? payload.etag : '';
                    const fileName = typeof payload?.file_name === 'string' ? payload.file_name : store.activeFile;
                    const reviewSurfaceFile = routeAgentKey === 'review_agent' && options?.activeFile === 'chapter_draft.md'
                        ? options.activeFile
                        : fileName;
                    const branch = typeof payload?.branch === 'string' ? payload.branch : store.draftBranch;
                    const diffPreview = typeof payload?.diff_preview === 'string' ? payload.diff_preview : '';
                    const changedFiles = normalizeChangedFilesPayload(payload?.changed_files);
                    const reviewChangedFiles = changedFiles.includes(reviewSurfaceFile)
                        ? changedFiles
                        : [reviewSurfaceFile, ...changedFiles];
                    const draftChanged = payload?.draft_changed === true || changedFiles.length > 0;
                    if (!draftChanged) return;
                    draftWriteState.reviewTargetFile = reviewSurfaceFile;
                    draftWriteState.changedFiles = reviewChangedFiles;
                    store.setSandboxDraft(
                        reviewSurfaceFile === fileName ? draftContent : useAppStore.getState().draftContent,
                        commitId,
                    );
                    store.setReviewTarget(reviewSurfaceFile, reviewChangedFiles);
                    if (reviewSurfaceFile === store.activeFile) {
                        store.setReviewMainlineFact(store.mainlineContent, store.baseEtag);
                    } else {
                        void loadReviewTargetMainline(reviewSurfaceFile);
                    }
                    store.attachDiffToAssistantMessage(assistantMessageId, {
                        fileName,
                        branch,
                        commitId,
                        etag,
                        content: draftContent,
                        diffPreview,
                    });
                    store.setReviewReadyNotice({
                        fileName: reviewSurfaceFile,
                        branch,
                        commitId: commitId || null,
                        diffPreview,
                        changedFiles: reviewChangedFiles,
                        ts: Date.now(),
                    });
                    store.setFsmState('REVIEW');
                    store.setWorkbenchMode('review');
                },
                onGitSyncSuccess: (payload) => {
                    draftWriteState.writeConfirmed = true;
                    draftWriteState.commitId = typeof payload?.commit_id === 'string' ? payload.commit_id : null;
                },
                onDone: (payload) => {
                    flushReasoningBuffers();
                    if (typeof payload?.task_id === 'string' && payload.task_id) {
                        streamTaskIdRef.current = payload.task_id;
                    }
                    const conversationId = typeof payload?.thread_id === 'string'
                        ? payload.thread_id
                        : (typeof payload?.conversation_id === 'string' ? payload.conversation_id : null);
                    const upstreamConversationId = typeof payload?.upstream_conversation_id === 'string'
                        ? payload.upstream_conversation_id
                        : null;
                    const finalAnswer = typeof payload?.answer === 'string' ? payload.answer : '';
                    const draftChanged = Boolean(payload?.draft_changed);
                    const writeConfirmed = Boolean(payload?.write_confirmed || payload?.git_sync_applied);
                    const syncStatus = typeof payload?.sync_status === 'string' ? payload.sync_status : '';
                    const syncMessage = typeof payload?.sync_message === 'string' ? payload.sync_message : '';
                    const syncCommitId = typeof payload?.sync_commit_id === 'string' ? payload.sync_commit_id : '';
                    const compatibilityPayloadDetected = Boolean(payload?.hidden_payload_detected);
                    const changedFiles = normalizeChangedFilesPayload(payload?.changed_files);
                    const shouldKeepReviewDecisionSurface = routeAgentKey === 'review_agent' && options?.activeFile === 'chapter_draft.md';
                    const shouldEnterReview = draftChanged || changedFiles.length > 0 || shouldKeepReviewDecisionSurface;
                    const forcedReviewTargetFile = routeAgentKey === 'review_agent' && options?.activeFile === 'chapter_draft.md'
                        ? options.activeFile
                        : null;
                    const payloadReviewTargetFile = typeof payload?.review_target_file === 'string' && payload.review_target_file
                        ? payload.review_target_file
                        : null;
                    const reviewTargetFile = shouldEnterReview
                        ? (forcedReviewTargetFile || payloadReviewTargetFile || changedFiles[0] || store.activeFile)
                        : null;
                    const reviewChangedFiles = reviewTargetFile && !changedFiles.includes(reviewTargetFile)
                        ? [reviewTargetFile, ...changedFiles]
                        : changedFiles;
                    const hadDraftReadyEvent = Boolean(draftWriteState.reviewTargetFile);
                    store.finishAssistantMessage(assistantMessageId, conversationId, upstreamConversationId, finalAnswer);
                    if (conversationId && shouldBindConversationToActiveAgent) {
                        store.setConversationId(conversationId);
                        store.setUpstreamConversationId(upstreamConversationId);
                        void loadConversationContext(store.activeAgent, conversationId);
                    }
                    draftWriteState.compatibilityPayloadDetected = compatibilityPayloadDetected;
                    draftWriteState.syncStatus = syncStatus;
                    draftWriteState.syncMessage = syncMessage;
                    if (syncCommitId) {
                        draftWriteState.commitId = syncCommitId;
                    }
                    draftWriteState.reviewTargetFile = reviewTargetFile;
                    draftWriteState.changedFiles = shouldEnterReview ? reviewChangedFiles : [];
                    if (writeConfirmed) {
                        draftWriteState.writeConfirmed = true;
                    }
                    if (shouldEnterReview && reviewTargetFile) {
                        store.setReviewTarget(reviewTargetFile, reviewChangedFiles);
                        if (reviewTargetFile === store.activeFile) {
                            store.setReviewMainlineFact(store.mainlineContent, store.baseEtag);
                        } else {
                            void loadReviewTargetMainline(reviewTargetFile);
                        }
                        if (!hadDraftReadyEvent) {
                            store.setReviewReadyNotice({
                                fileName: reviewTargetFile,
                                branch: store.draftBranch,
                                commitId: syncCommitId || draftWriteState.commitId || null,
                                diffPreview: '',
                                changedFiles: reviewChangedFiles,
                                ts: Date.now(),
                            });
                        }
                        store.setFsmState('REVIEW');
                        store.setWorkbenchMode('review');
                    } else {
                        store.setSandboxDraft('', null);
                        store.setReviewTarget(null, []);
                        store.setReviewMainlineFact('', '');
                        store.clearReviewReadyNotice();
                        store.setFsmState('IDLE');
                        store.setWorkbenchMode('editor');
                    }
                },
                onError: (payload) => {
                    flushReasoningBuffers();
                    if (typeof payload?.task_id === 'string' && payload.task_id) {
                        streamTaskIdRef.current = payload.task_id;
                    }
                    const code = typeof payload?.code === 'string' ? payload.code : 'STREAM_ERROR';
                    const message = typeof payload?.message === 'string' ? payload.message : '推演流异常中断';
                    const visibleMessage = formatVisibleDeductionError(code, message);
                    if (shouldSuppressBackendError(code, message)) {
                        appendSuppressedBackendError(code, message);
                        console.warn('[world_deduce] suppressed backend error:', code, message);
                        return;
                    }
                    maybeShowDefenseToast(code, message);
                    maybeShowDeductionErrorToast(code, message);
                    store.failAssistantMessage(assistantMessageId, code, visibleMessage);
                    streamErrorHandled = true;
                },
            }, {
                signal: abortController.signal,
                rewriteUserMessageId: options?.rewriteUserMessageId,
                routeAgentKey,
                activeFile: options?.activeFile,
                fileType: options?.fileType,
                baseEtag: options?.baseEtag,
            });
            if (draftWriteState.writeConfirmed) {
                const bookRef = { kind: store.bookRef.kind, value: store.bookRef.value };
                const currentFile = store.activeFile;
                const reviewTargetFile = draftWriteState.reviewTargetFile || useAppStore.getState().reviewTargetFile || currentFile;
                const shouldReloadGit = store.workbenchMode === 'git';
                try {
                    const { files, integrity } = await fetchHotFiles(bookRef);
                    setRepoIntegrity(integrity);
                    if (files.length > 0) {
                        store.setHotFiles(files);
                    }
                } catch (err) {
                    console.warn('Failed to refresh hot files after draft write sync:', err);
                }
                await loadMainline(currentFile, { preserveDraftReview: true });
                if (reviewTargetFile === currentFile) {
                    const runtimeState = useAppStore.getState();
                    store.setReviewMainlineFact(runtimeState.mainlineContent, runtimeState.baseEtag);
                } else {
                    await loadReviewTargetMainline(reviewTargetFile);
                }
                if (shouldReloadGit) {
                    await loadGitWorkbench();
                }
                const shortCommitId = typeof draftWriteState.commitId === 'string' ? draftWriteState.commitId.slice(0, 8) : '';
                store.setUiNotice({
                    type: 'success',
                    message: shortCommitId
                        ? `草稿写入完成：${shortCommitId}`
                        : '草稿写入完成，审阅工作台已同步。',
                    ts: Date.now(),
                });
            } else if (draftWriteState.compatibilityPayloadDetected && draftWriteState.syncStatus && draftWriteState.syncStatus !== 'success') {
                const syncErrorMessage = draftWriteState.syncMessage || `兼容写入链失败（${draftWriteState.syncStatus}）`;
                maybeShowDeductionErrorToast('DRAFT_SYNC_FAILED', syncErrorMessage);
            }
        } catch (err) {
            flushReasoningBuffers();
            if (err instanceof ApiError && err.code === 'REQUEST_ABORTED') {
                store.interruptAssistantMessage(assistantMessageId);
                store.setUpstreamConversationId(streamStableUpstreamConversationIdRef.current);
                const latestUserMessage = getLatestUserMessage();
                if (latestUserMessage) {
                    beginRewriteFromMessage(latestUserMessage.id, latestUserMessage.text);
                }
                store.setUiNotice({
                    type: 'info',
                    message: '输出已中止，可直接修改最后一问后重发。',
                    ts: Date.now(),
                });
                store.setFsmState('IDLE');
                return;
            }
            if (err instanceof ApiError && shouldSuppressBackendError(err.code, err.message)) {
                appendSuppressedBackendError(err.code, err.message);
                console.warn('[world_deduce] ignored ApiError after successful write path:', err.code, err.message);
                store.finishAssistantMessage(assistantMessageId, store.conversationId, store.upstreamConversationId, undefined);
                store.setFsmState('IDLE');
                return;
            }
            if (err instanceof ApiError && streamErrorHandled) {
                if ([409, 428].includes(err.status) || ['WRITE_CONFLICT', 'PRECONDITION_REQUIRED'].includes(err.code)) {
                    store.setFsmState('CONFLICT');
                } else {
                    store.setFsmState('IDLE');
                }
                return;
            }
            if (err instanceof ApiError && ([409, 428].includes(err.status) || ['WRITE_CONFLICT', 'PRECONDITION_REQUIRED'].includes(err.code))) {
                store.setFsmState('CONFLICT');
                maybeShowDeductionErrorToast(err.code, err.message);
                store.failAssistantMessage(assistantMessageId, err.code, formatVisibleDeductionError(err.code, err.message));
            } else {
                console.error('Deduction failed:', err);
                if (err instanceof ApiError) {
                    maybeShowDefenseToast(err.code, err.message);
                    maybeShowDeductionErrorToast(err.code, err.message);
                    store.failAssistantMessage(assistantMessageId, err.code, formatVisibleDeductionError(err.code, err.message));
                } else {
                    maybeShowDeductionErrorToast('UNKNOWN_ERROR', '推演失败');
                    store.failAssistantMessage(assistantMessageId, 'UNKNOWN_ERROR', '推演失败');
                }
                store.setFsmState('IDLE');
            }
        } finally {
            flushReasoningBuffers();
            streamTaskIdRef.current = null;
            if (streamAbortControllerRef.current === abortController) {
                streamAbortControllerRef.current = null;
            }
        }
    };

    const handleCommandSubmit = async (intent: string, clearComposer?: () => void) => {
        await handleIntentSubmit(
            intent,
            rewriteUserMessageId
                ? { rewriteUserMessageId }
                : clearComposer
                    ? { onAccepted: clearComposer }
                    : undefined,
        );
    };

    const beginRewriteFromMessage = useCallback((messageId: string, text: string) => {
        setRewriteUserMessageId(messageId);
        setCommandInput(text);
    }, []);

    const handleCancelRewrite = useCallback(() => {
        setRewriteUserMessageId(null);
        setCommandInput('');
    }, []);

    const handleInlineRewriteSubmit = useCallback(async () => {
        if (!commandInput.trim()) return;
        await handleCommandSubmit(commandInput);
    }, [commandInput]);


    const prepareFileContextSwitch = (nextFile: string) => {
        if (!isEditing) return true;

        if (editDraft !== editorContent) {
            store.setUiNotice({
                type: 'info',
                message: `当前文件 ${store.activeFile} 有未保存人工编辑，请先保存或收起编辑栏，再切换到 ${nextFile}。`,
                ts: Date.now(),
            });
            return false;
        }

        setEditDraft('');
        setEditBaseEtag('');
        setSaveConflict(null);
        setIsEditing(false);
        return true;
    };

    const {
        conversationPanelAgent,
        loadConversationContext,
        handleConversationSelect,
        handleSwitchConversationAgent,
        handleCreateConversation,
        handleRenameConversation,
        handleArchiveConversation,
        handleDeleteConversation,
    } = useAgentSession({
        store,
        loadMainline,
        prepareFileContextSwitch,
        hasPendingDraftDecision,
        pendingReviewTargetFile,
        isEditing,
        editDraft,
        editorContent,
        setIsEditing,
        setEditDraft,
        setEditBaseEtag,
        setSaveConflict,
    });

    const handleFileSelect = async (file: HotFileItem) => {
        if (file.fileName === store.activeFile) return;
        if (hasPendingDraftDecision) {
            const reviewFile = pendingReviewTargetFile();
            store.setUiNotice({
                type: 'info',
                message: `当前被审阅文件 ${reviewFile} 已进入差异审阅态，请先归档/确权或湮灭回滚，再切换文件。`,
                ts: Date.now(),
            });
            return;
        }
        if (!prepareFileContextSwitch(file.fileName)) return;
        store.setActiveFile(file.fileName, file.fileType);
        await loadMainline(file.fileName);
    };

    const handleWorkbenchModeChange = (nextMode: WorkbenchMode) => {
        if (nextMode === store.workbenchMode) return;
        if (nextMode === 'review' && !hasReviewWorkspace) {
            return;
        }
        if (nextMode === 'git' && hasPendingDraftDecision) {
            store.setUiNotice({
                type: 'info',
                message: `当前文件 ${store.activeFile} 正处于差异审阅态；剧情分支可查看，切换、合并、回退会在确权或回滚前保持禁用。`,
                ts: Date.now(),
            });
        }
        store.setWorkbenchMode(nextMode);
        if (nextMode === 'editor') {
            store.setGitCenterMode('commit_list');
            store.setGitDiffPayload(null);
            store.setGitFilePayload(null);
            store.setGitDiffFullscreen(false);
        }
    };

    const handleRepairLayout = useCallback(async () => {
        if (!store.bookRef.value || repairPending) return;
        const bookRef = { kind: store.bookRef.kind, value: store.bookRef.value } as const;
        setRepairPending(true);
        try {
            const result = await repairBookLayout(bookRef);
            setRepoIntegrity(result.integrity);
            const { files, integrity } = await fetchHotFiles(bookRef);
            setRepoIntegrity(integrity);
            if (files.length > 0) {
                store.setHotFiles(files);
            }
            await loadMainline();
            if (!integrity.needsRepair && store.workbenchMode === 'git') {
                await loadGitWorkbench();
            }
            const shortCommit = (result.headCommit || '').slice(0, 8);
            store.setUiNotice({
                type: 'success',
                message: shortCommit ? `仓库布局已修复：${shortCommit}` : '仓库布局已修复。',
                ts: Date.now(),
            });
        } catch (err) {
            const integrity = extractIntegrityFromError(err);
            if (integrity) {
                setRepoIntegrity(integrity);
            }
            store.setUiNotice({
                type: 'error',
                message: `修复布局失败：${getErrorMessage(err, '未知异常')}`,
                ts: Date.now(),
            });
        } finally {
            setRepairPending(false);
        }
    }, [repairPending, store.bookRef.kind, store.bookRef.value, store.workbenchMode, loadGitWorkbench, loadMainline]);

    const isReviewMode = store.workbenchMode === 'review';
    const isGitMode = store.workbenchMode === 'git';
    const outlineSourceContent = isEditing
        ? editDraft
        : (isReviewMode && store.draftContent ? store.draftContent : editorContent);
    const leftRailVerticalLayout = useDefaultLayout({
        id: 'novel-agent-left-rail-stack',
        panelIds: ['left-files-panel', 'left-outline-panel'],
    });
    const leftPanelTitle = isGitMode ? copy.workbench.gitConsole : copy.workbench.projectFiles;
    const editorRailActive = store.workbenchMode !== 'git';
    const explorerFiles = store.hotFiles.length > 0 ? store.hotFiles : DEFAULT_HOT_FILES;
    const explorerFileKey = explorerFiles.map((file) => `${file.fileType}:${file.fileName}`).join('|');
    const topBar = (
        <div className="flex w-full items-center gap-4">
            <button
                type="button"
                onClick={handleBackToBookshelf}
                className="flex shrink-0 items-center gap-1.5 rounded-[10px] border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.016)] px-2.5 py-1.5 text-[11px] font-medium text-[var(--color-dark-text-muted)] transition-colors hover:border-[rgba(115,134,255,0.32)] hover:text-[var(--color-dark-text-main)]"
            >
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-3.5 w-3.5">
                    <path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H14l3 3v10.5a2.5 2.5 0 0 1-2.5 2.5h-8A2.5 2.5 0 0 1 4 15.5v-11Z" />
                </svg>
                <span>书架</span>
            </button>
            <div className="min-w-0 flex items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-[10px] bg-[rgba(115,134,255,0.14)] text-[var(--color-dark-text-main)] shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
                    <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4" stroke="currentColor" strokeWidth="1.7">
                        <path d="M10 2.8 16.2 6v8L10 17.2 3.8 14V6 10" />
                        <path d="M10 2.8v6.1L3.8 10" />
                        <path d="M16.2 6 10 8.9" />
                    </svg>
                </div>
                <div className="min-w-0">
                    <div className="truncate text-[13px] font-semibold text-[var(--color-dark-text-main)]">
                        {store.bookRef.value || copy.workbench.noBookSelected}
                    </div>
                </div>
            </div>
            <button
                type="button"
                className="novel-quick-open flex min-w-0 max-w-[360px] flex-1 items-center gap-2 rounded-[10px] border border-[rgba(255,255,255,0.05)] bg-[rgba(255,255,255,0.012)] px-3 py-2 text-left text-[12px] text-[var(--color-dark-text-faint)] transition-colors hover:border-[rgba(255,255,255,0.1)] hover:text-[var(--color-dark-text-main)]"
            >
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4 shrink-0">
                    <circle cx="8.5" cy="8.5" r="4.5" />
                    <path d="m12 12 4 4" />
                </svg>
                <span className="truncate">{copy.workbench.quickOpen}</span>
            </button>
            <div className="ml-auto flex items-center gap-2 text-[10px] font-mono text-[var(--color-dark-text-faint)]">
                <span className="rounded-[8px] border border-[rgba(255,255,255,0.04)] bg-[rgba(255,255,255,0.012)] px-2 py-1">
                    {isGitMode ? copy.workbench.gitRail : isReviewMode ? copy.workbench.reviewState : copy.workbench.editorRail}
                </span>
                <span className="truncate">{store.activeFile}</span>
            </div>
        </div>
    );
    const activityBar = (
        <div className="flex h-full flex-col items-center justify-between px-2 py-3">
            <div className="flex flex-col items-center gap-2">
                <button
                    type="button"
                    onClick={() => handleWorkbenchModeChange('editor')}
                    className={`flex h-11 w-11 items-center justify-center rounded-[12px] border transition-colors ${
                        editorRailActive
                            ? 'border-[rgba(115,134,255,0.46)] bg-[rgba(115,134,255,0.14)] shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]'
                            : 'border-transparent bg-transparent hover:border-[rgba(255,255,255,0.06)] hover:bg-[rgba(255,255,255,0.02)]'
                    }`}
                    aria-label={copy.workbench.editorRail}
                >
                    <RailIcon
                        active={editorRailActive}
                        path={<path d="M5.25 3.75h6.5l3 3v9.5H5.25zM11.75 3.75v3h3" />}
                    />
                </button>
                <button
                    type="button"
                    onClick={() => handleWorkbenchModeChange('git')}
                    className={`flex h-11 w-11 items-center justify-center rounded-[12px] border transition-colors ${
                        isGitMode
                            ? 'border-[rgba(115,134,255,0.46)] bg-[rgba(115,134,255,0.14)] shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]'
                            : 'border-transparent bg-transparent hover:border-[rgba(255,255,255,0.06)] hover:bg-[rgba(255,255,255,0.02)]'
                    }`}
                    aria-label={copy.workbench.gitRail}
                >
                    <RailIcon
                        active={isGitMode}
                        path={
                            <>
                                <circle cx="6" cy="5.5" r="1.75" />
                                <circle cx="14" cy="10" r="1.75" />
                                <circle cx="6" cy="14.5" r="1.75" />
                                <path d="M7.5 6.4 12.5 9.1M7.5 13.6l5-2.7" />
                            </>
                        }
                    />
                </button>
            </div>
            <div className="h-9 w-9 rounded-[10px] border border-[rgba(255,255,255,0.04)] bg-[rgba(255,255,255,0.012)]" />
        </div>
    );
    const workbenchLeftPanel = (
        <div className="flex h-full min-h-0 flex-col overflow-hidden">
            <div className="border-b border-[var(--color-dark-border)] px-3 py-3">
                <div className="cursor-section-label">
                    {isGitMode ? copy.workbench.versionControl : copy.workbench.workspace}
                </div>
                <div className="mt-1 flex items-center justify-between gap-2.5">
                    <div className="min-w-0">
                        <div className="truncate text-[13px] font-medium text-[var(--color-dark-text-main)]">{leftPanelTitle}</div>
                        <div className="truncate text-[10px] text-[var(--color-dark-text-faint)]">
                            {store.bookRef.value || copy.workbench.noBookSelected}
                        </div>
                    </div>
                    <div className="rounded-[8px] border border-[rgba(255,255,255,0.04)] bg-[rgba(255,255,255,0.015)] px-2 py-[3px] text-[9px] font-mono text-[var(--color-dark-text-faint)]">
                        {isGitMode ? copy.workbench.repository : isReviewMode ? copy.workbench.reviewState : getFileTypeLabel(store.uiLanguage, store.activeFileType)}
                    </div>
                </div>
            </div>
            <WorkbenchModeToggle
                uiLanguage={store.uiLanguage}
                onChangeLanguage={store.setUiLanguage}
            />
            {repoIntegrity?.needsRepair && bootstrapState === 'loaded' && (
                <div className="border-b border-[#583d1f] bg-[linear-gradient(180deg,#24180d_0%,#1a120a_100%)] px-3 py-3">
                    <div className="rounded-xl border border-[#7f5a2e] bg-[#120d08] p-3 shadow-[0_10px_24px_rgba(0,0,0,0.28)]">
                        <div className="text-[10px] font-mono tracking-[0.14em] text-[#f2bf72]">仓库修复</div>
                        <div className="mt-1 text-sm font-semibold text-[#fff1d6]">当前仓库核心布局不完整</div>
                        <div className="mt-1 text-[11px] leading-5 text-[#d9bf95]">
                            缺失或未追踪文件：{[...repoIntegrity.missingCoreFiles, ...repoIntegrity.untrackedLayoutFiles].slice(0, 3).join('、') || '核心底座'}
                        </div>
                        <button
                            type="button"
                            onClick={() => { void handleRepairLayout(); }}
                            disabled={repairPending}
                            className="mt-3 w-full rounded-lg border border-[#f2bf72] bg-[#4a2e12] px-3 py-2 text-xs font-bold text-[#fff4e2] transition-colors hover:bg-[#61401a] disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {repairPending ? '修复中…' : '修复仓库布局'}
                        </button>
                    </div>
                </div>
            )}
            <div className="min-h-0 flex-1 overflow-hidden">
                {isGitMode ? (
                    <GitBranchPanel
                        status={store.gitStatus}
                        branches={store.gitBranches}
                        selectedCommitId={store.selectedGitCommitId}
                        chapterDraftContent={store.activeFile === 'chapter_draft.md' ? (store.draftContent || store.mainlineContent) : ''}
                        pending={store.gitActionPending}
                        onRefresh={() => {
                            void loadGitWorkbench();
                        }}
                        onCheckout={(branchName) => {
                            void handleGitCheckout(branchName);
                        }}
                        onMerge={(payload) => {
                            void handleGitMerge(payload);
                        }}
                        onCreateBranch={(payload) => {
                            void handleGitCreateBranch(payload);
                        }}
                        onHardRollback={(targetCommit) => {
                            void handleGitHardRollback(targetCommit);
                        }}
                    />
                ) : (
                    <Group
                        orientation="vertical"
                        className="h-full min-h-0"
                        data-left-rail-stack="true"
                        defaultLayout={leftRailVerticalLayout.defaultLayout}
                        onLayoutChanged={leftRailVerticalLayout.onLayoutChanged}
                    >
                        <Panel id="left-files-panel" defaultSize="52%" minSize="18%">
                            <div className="flex h-full min-h-0 flex-col overflow-hidden">
                                <div className="border-b border-[rgba(255,255,255,0.035)] px-3 py-2">
                                    <div className="cursor-section-label">{copy.explorer.filesSection}</div>
                                </div>
                                <div className="min-h-0 flex-1 overflow-hidden">
                                    <FileExplorer
                                        key={explorerFileKey}
                                        files={explorerFiles}
                                        activeFile={store.activeFile}
                                        disabled={hasPendingDraftDecision}
                                        hotkeysEnabled={store.workbenchMode !== 'git'}
                                        onSelectFile={handleFileSelect}
                                    />
                                </div>
                            </div>
                        </Panel>
                        <Separator className="group relative h-3 shrink-0 cursor-row-resize bg-transparent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-accent-blue)]">
                            <div className="absolute inset-x-4 top-1/2 h-px -translate-y-1/2 rounded-full bg-[rgba(255,255,255,0.05)] transition-all duration-150 group-hover:inset-x-3 group-hover:bg-[rgba(255,255,255,0.18)]" />
                            <div className="absolute left-1/2 top-1/2 hidden h-[3px] w-8 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[rgba(255,255,255,0.14)] blur-[1px] transition-opacity duration-150 group-hover:block" />
                        </Separator>
                        <Panel id="left-outline-panel" defaultSize="48%" minSize="20%">
                            <div className="h-full min-h-0 overflow-hidden border-t border-[rgba(255,255,255,0.035)]">
                                <OutlineNavigator
                                    content={outlineSourceContent}
                                    activeFile={store.activeFile}
                                />
                            </div>
                        </Panel>
                    </Group>
                )}
            </div>
        </div>
    );



    const editorCenterPanel = (
        <>
            {/* Conflict guard modal — draft-file UX, no force-overwrite */}
            {saveConflict && (
                <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/70">
                    <div className="workspace-strip w-[520px] rounded-[16px] border border-[var(--tone-warning-border)] bg-[var(--tone-warning-bg)] p-6 shadow-[0_24px_50px_rgba(0,0,0,0.35)]">
                        <div className="mb-2 text-sm font-bold text-[var(--tone-warning-text)]">⚠️ 写入冲突 — 你的修改已自动存为草稿</div>
                        <div className="mb-4 text-xs text-[var(--color-dark-text-muted)] leading-relaxed">
                            在你编辑期间，AI Agent 已向此文件提交了更新（ETag 已变更）。<br />
                            为防止内容丢失，你的修改已被系统自动保存到：
                        </div>
                        <div className="mb-4 rounded-[12px] border border-[rgba(255,255,255,0.08)] bg-[rgba(9,12,16,0.9)] px-3 py-2 font-mono text-[11px] text-[var(--tone-warning-text)] break-all">
                            📄 {saveConflict.draftFile}
                        </div>
                        <div className="mb-4 text-xs text-[var(--color-dark-text-muted)] leading-relaxed">
                            请在文件管理器中打开该草稿，复制你需要的内容，然后<strong className="text-white">删除草稿文件</strong>。<br />
                            点击「拉取最新」可查看 AI 的当前版本。
                        </div>
                        <div className="flex gap-3 justify-end">
                            <button
                                onClick={() => { setSaveConflict(null); setIsEditing(false); void loadMainline(); }}
                                className="rounded-[10px] border border-[rgba(255,255,255,0.14)] bg-[rgba(255,255,255,0.08)] px-4 py-2 text-xs font-semibold text-[var(--color-dark-text-main)] hover:bg-[rgba(255,255,255,0.12)]"
                            >📥 拉取最新版本</button>
                            <button
                                onClick={() => setSaveConflict(null)}
                                className="rounded px-4 py-2 text-xs border border-[var(--color-dark-border)] text-[var(--color-dark-text-muted)] hover:bg-white/5"
                            >关闭（稍后处理）</button>
                        </div>
                    </div>
                </div>
            )}
            {repoIntegrity?.needsRepair && bootstrapState === 'loaded' && (
                <div className="border-b border-[var(--tone-warning-border)] bg-transparent px-4 py-3">
                    <div className="workspace-strip flex items-center justify-between gap-4 rounded-[14px] border border-[var(--tone-warning-border)] bg-[var(--tone-warning-bg)] px-4 py-3">
                        <div className="min-w-0">
                            <div className="cursor-section-label text-[var(--tone-warning-text)]">Integrity Guard</div>
                            <div className="mt-1 text-sm font-semibold text-[#fff1d6]">已切入只读保护态，正常保存 / AI / Git 均已阻断</div>
                            <div className="text-[11px] leading-5 text-[#d9bf95]">
                                缺失核心文件：{repoIntegrity.missingCoreFiles.join('、') || '无'}
                                {repoIntegrity.untrackedLayoutFiles.length > 0 ? `；未追踪：${repoIntegrity.untrackedLayoutFiles.join('、')}` : ''}
                            </div>
                        </div>
                        <button
                            type="button"
                            onClick={() => { void handleRepairLayout(); }}
                            disabled={repairPending}
                            className="shrink-0 rounded-[10px] border border-[rgba(255,255,255,0.14)] bg-[rgba(255,255,255,0.06)] px-4 py-2 text-xs font-bold text-[#fff4e2] transition-colors hover:bg-[rgba(255,255,255,0.1)] disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {repairPending ? '修复中…' : '立即修复'}
                        </button>
                    </div>
                </div>
            )}
            {!repoIntegrity?.needsRepair && mainlineFileState?.virtual && (
                <div className="border-b border-[var(--color-dark-border)] bg-[rgba(255,255,255,0.025)] px-4 py-2.5 text-[11px] text-[var(--color-dark-text-faint)]">
                    当前文件在此状态下不存在，正在使用虚拟空文件预览：`{store.activeFile}`。修复布局后将恢复真实物理文件。
                </div>
            )}
            <div className="flex items-center justify-between border-b border-[var(--color-dark-border)] p-2 px-4 text-xs font-mono">
                {/* Left: file name + ETAG */}
                <span className="text-[var(--color-dark-text-muted)]">{copy.editor.mainlineContent(store.activeFile)}
                    {!isEditing && <span className="ml-2 opacity-50">{copy.editor.etag}: {store.baseEtag?.slice(0, 8) || '…'}</span>}
                </span>
                {/* Right: action buttons */}
                <span className="flex items-center gap-2">
                    {!isEditing ? (
                        <>
                            <span className="opacity-50">{editorSaveState === 'saving' ? '⏳ 保存中' : editorSaveState === 'error' ? '❌ 保存失败' : ''}</span>
                            <span className="text-[11px] text-[var(--color-dark-text-muted)]">{copy.editor.editorEntryBottom}</span>
                        </>
                    ) : (
                        <span className="inline-flex items-center rounded-full border border-amber-400/40 bg-amber-400/10 px-2.5 py-1 text-[11px] font-bold text-amber-300 animate-pulse">
                            ● {copy.editor.editing}
                        </span>
                    )}
                </span>
            </div>
            <div className="relative min-h-0 flex-1 overflow-hidden">
                {!isEditing && (
                    <MainlineView
                        mode="view"
                        fileName={store.activeFile}
                        content={editorContent}
                        readOnly
                    />
                )}
                <div
                    className={`absolute inset-x-3 bottom-3 z-20 flex h-[80vh] min-h-0 flex-col overflow-hidden rounded-t-[18px] border border-[var(--color-dark-border)] bg-[linear-gradient(180deg,rgba(255,255,255,0.018)_0%,rgba(255,255,255,0)_100%),rgba(17,20,26,0.98)] shadow-[0_-20px_45px_rgba(0,0,0,0.6)] transition-all duration-200 ${
                        isEditing ? 'translate-y-0 opacity-100' : 'translate-y-full opacity-0 pointer-events-none'
                    }`}
                    aria-hidden={!isEditing}
                    inert={!isEditing}
                >
                    <div className="flex items-center justify-between border-b border-[var(--color-dark-border)] bg-[rgba(255,255,255,0.02)] px-4 py-2.5 text-[12px] font-mono">
                        <span className="text-[var(--color-dark-text-main)] font-semibold">{copy.editor.bottomEditor(store.activeFile)}</span>
                        <span className="flex items-center gap-2">
                            <span className="inline-flex items-center rounded-full border border-amber-400/40 bg-amber-400/10 px-2.5 py-1 text-[11px] font-bold text-amber-300 animate-pulse">
                                ● {copy.editor.editing}
                            </span>
                            <button
                                onClick={handleCancelEdit}
                                disabled={isSaving}
                                className="rounded-md border border-[#ffb86b] bg-[#4a2b11] px-4 py-1.5 text-[11px] font-semibold text-[#ffd9ac] shadow-[0_0_0_1px_rgba(255,184,107,0.15)] transition-all hover:border-[#ffc37d] hover:bg-[#663815] disabled:opacity-40"
                            >{copy.editor.collapseEditor}</button>
                            <button
                                onClick={() => void handleSaveEdit()}
                                disabled={isSaving}
                                className="rounded-md border border-[var(--tone-success-border)] bg-[var(--tone-success-bg)] px-4 py-1.5 text-[11px] font-bold text-[var(--tone-success-text)] transition-all hover:bg-[rgba(255,255,255,0.12)] disabled:opacity-40"
                            >{isSaving ? `⏳ ${copy.editor.saving}` : copy.editor.saveAndCollapse}</button>
                        </span>
                    </div>
                    <div className="min-h-0 flex-1 overflow-hidden">
                        <MainlineView
                            mode="edit"
                            fileName={store.activeFile}
                            content={editDraft}
                            readOnly={false}
                            onChange={(next) => {
                                if (isEditing) setEditDraft(next);
                            }}
                        />
                    </div>
                </div>
            </div>
            {!isEditing && (
                <div className="px-4 pb-2 pt-3">
                    <div className="workspace-strip-muted rounded-[14px] px-4 py-3">
                        <div className="flex items-center justify-between gap-4">
                            <div className="min-w-0">
                                <div className="cursor-section-label">{copy.editor.humanEdit}</div>
                                <div className="mt-1 text-sm font-semibold text-[var(--color-dark-text-main)]">{copy.editor.editMainline}</div>
                                <div className="text-[11px] text-[var(--color-dark-text-faint)]">{copy.editor.editHint}</div>
                            </div>
                            <button
                                onClick={handleEnterEdit}
                                disabled={store.fsmState === 'THINKING' || isSaving || Boolean(repoIntegrity?.needsRepair)}
                                className="shrink-0 rounded-[12px] border border-[rgba(255,255,255,0.14)] bg-[rgba(255,255,255,0.06)] px-4 py-2 text-xs font-bold tracking-wide text-[var(--color-dark-text-main)] transition-all duration-150 hover:-translate-y-[1px] hover:bg-[rgba(255,255,255,0.1)] disabled:cursor-not-allowed disabled:opacity-40"
                            >
                                {copy.editor.expandEditor}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );

    const gitCenterPanel = repoIntegrity?.needsRepair ? (
        <div className="flex h-full min-h-0 items-center justify-center bg-[#0b1119] p-6">
            <div className="w-full max-w-xl rounded-2xl border border-[#7f5a2e] bg-[linear-gradient(180deg,#1f140b_0%,#120d08_100%)] p-6 text-left shadow-[0_22px_46px_rgba(0,0,0,0.34)]">
                <div className="text-[10px] font-mono uppercase tracking-[0.16em] text-[#f2bf72]">Git Console Locked</div>
                <div className="mt-2 text-xl font-semibold text-[#fff1d6]">当前历史状态缺少核心布局，Git 工作台已冻结</div>
                <div className="mt-2 text-sm leading-6 text-[#d9bf95]">
                    这是硬回退后的保护态，不再允许 GET 路径偷偷补文件。先执行一次显式修复，再继续查看分支、提交和 Diff。
                </div>
                <button
                    type="button"
                    onClick={() => { void handleRepairLayout(); }}
                    disabled={repairPending}
                    className="mt-5 rounded-lg border border-[#f2bf72] bg-[#4a2e12] px-4 py-2 text-sm font-bold text-[#fff4e2] transition-colors hover:bg-[#61401a] disabled:cursor-not-allowed disabled:opacity-50"
                >
                    {repairPending ? '修复中…' : '修复后重新载入 Git 视图'}
                </button>
            </div>
        </div>
    ) : (
        <GitCenterPanel
            commits={store.gitHistoryCommits}
            selectedCommitId={store.selectedGitCommitId}
            loading={store.gitLoading}
            error={store.gitError}
            onSelectCommit={(commitId) => {
                store.setSelectedGitCommit(commitId);
                store.setSelectedGitPath(null);
                store.setGitDiffPayload(null);
            }}
        />
    );

    const visibleChatMessages = useMemo(() => (
        store.chatMessages.filter((message) => {
            if (!message.activeFile) return true;
            return isSameConversationScope(
                message.activeFile,
                resolveFileType(message.activeFile),
                store.activeFile,
                store.activeFileType,
                store.activeAgent,
            );
        })
    ), [store.activeAgent, store.activeFile, store.activeFileType, store.chatMessages]);
    const latestUserMessageId = getLatestUserMessage()?.id ?? null;
    const latestDraftAttachment = useMemo(() => (
        [...visibleChatMessages]
            .reverse()
            .find((message) => message.diffAttachment)?.diffAttachment || null
    ), [visibleChatMessages]);
    const reviewTargetFile = useMemo(() => (
        store.reviewTargetFile
        || store.reviewReadyNotice?.fileName
        || latestDraftAttachment?.fileName
        || store.activeFile
    ), [latestDraftAttachment?.fileName, store.activeFile, store.reviewReadyNotice?.fileName, store.reviewTargetFile]);
    const reviewMainlineContent = useMemo(() => (
        reviewTargetFile === store.activeFile
            ? (store.reviewMainlineContent || store.mainlineContent)
            : store.reviewMainlineContent
    ), [reviewTargetFile, store.activeFile, store.reviewMainlineContent, store.mainlineContent]);
    const handleEnterReviewFromNotice = () => {
        store.setWorkbenchMode('review');
        store.clearReviewReadyNotice();
    };
    const handleRunReviewAgent = () => {
        const targetFile = pendingReviewTargetFile();
        if (targetFile !== 'chapter_draft.md') return;
        void handleIntentSubmit(
            `请审核当前续写草稿 ${targetFile}。你必须读取 chapter_draft.md，并结合 chapter_outline.md、summary.md、status_card.md、world_model.md、style_guide.md、error_archive.md 判断：1）是否越过本章大纲边界；2）是否违反世界观、状态卡、文风或错误档案；3）是否存在情节水位、占比、手法失衡。若发现真实问题，请只把可复用的硬约束写入 error_archive.md；若没有问题，请用一句话说明通过，不要写文件。`,
            { routeAgentKey: 'review_agent', activeFile: 'chapter_draft.md', fileType: 'chapter', baseEtag: '' },
        );
    };
    const handleRewriteWithReview = () => {
        const targetFile = pendingReviewTargetFile();
        if (targetFile !== 'chapter_draft.md') return;
        void handleIntentSubmit(
            `请根据 error_archive.md、最近审核意见和当前上下文，修复 ${targetFile} 中所有被审核命中的真实问题；如果问题跨越当前三章，也必须一并修复，不要只处理最新三章。必须遵守 chapter_outline.md 的本章边界、summary.md 与 status_card.md 的最新事实、world_model.md 的设定、style_guide.md 的文风，以及 error_archive.md 的硬性禁令。请直接更新 chapter_draft.md，不要修改其他文件。`,
            { routeAgentKey: 'continuation_agent', activeFile: 'chapter_draft.md', fileType: 'chapter', baseEtag: '' },
        );
    };

    const editorRightPanel = (
        <div className="flex h-full min-h-0 flex-col">
            <div className="border-b border-[rgba(255,255,255,0.032)] px-2 py-[6px]">
                <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                        <div className="text-[11px] font-medium text-[var(--color-dark-text-main)]">
                            {getAgentLabel(store.uiLanguage, conversationPanelAgent)}
                        </div>
                        <div className="truncate text-[9px] text-[var(--color-dark-text-faint)]">
                            {store.activeFile}
                        </div>
                    </div>
                    <div className="rounded-[8px] border border-[rgba(255,255,255,0.035)] bg-[rgba(255,255,255,0.01)] px-2 py-[2px] text-[8px] font-mono text-[var(--color-dark-text-faint)]">
                        {getFsmStateLabel(store.uiLanguage, store.fsmState)}
                    </div>
                </div>
            </div>
            <AgentConversationList
                agent={conversationPanelAgent}
                currentFileAgent={store.activeAgent}
                activeConversationId={store.conversationByAgent[conversationPanelAgent] ?? null}
                activeFile={store.activeFile}
                conversations={store.conversationIndexByAgent[conversationPanelAgent] ?? []}
                onSwitchAgent={(agent) => { void handleSwitchConversationAgent(agent); }}
                onCreateConversation={() => { void handleCreateConversation(); }}
                onSelectConversation={(conversationId) => { void handleConversationSelect(conversationId); }}
                onRenameConversation={(conversationId) => { void handleRenameConversation(conversationId); }}
                onArchiveConversation={(conversationId) => { void handleArchiveConversation(conversationId); }}
                onDeleteConversation={(conversationId) => { void handleDeleteConversation(conversationId); }}
                disabled={store.fsmState === 'THINKING'}
            />
            {suppressedBackendErrors.length > 0 && (
                <div className="border-b border-[#2b3440] bg-[#0b1119] px-3 py-2">
                    <div className="flex items-center justify-between">
                        <button
                            type="button"
                            className="text-[11px] font-mono text-[#8b949e] hover:text-[#c9d1d9] transition-colors"
                            onClick={() => setSuppressedDebugOpen((open) => !open)}
                        >
                            {suppressedDebugOpen ? '▼' : '▶'} {copy.debug.suppressedHeader(suppressedBackendErrors.length)}
                        </button>
                        {suppressedDebugOpen && (
                            <button
                                type="button"
                                className="text-[10px] font-mono text-[#8b949e] hover:text-[#c9d1d9] transition-colors"
                                onClick={() => setSuppressedBackendErrors([])}
                            >
                                {copy.debug.clear}
                            </button>
                        )}
                    </div>
                    {suppressedDebugOpen && (
                        <div className="app-scrollbar mt-2 max-h-36 overflow-y-auto rounded border border-[#2b3440] bg-[#0a0f18] p-2 text-[11px] font-mono text-[#9ca3af]">
                            {[...suppressedBackendErrors].reverse().map((item) => (
                                <div key={item.id} className="py-1 border-b border-[#1e2632] last:border-b-0">
                                    <div className="text-[#e5e7eb]">
                                        [{formatSuppressedBackendErrorTitle(item.code, copy)}] {item.reqId ? `(req:${item.reqId})` : ''}
                                    </div>
                                    <div className="text-[#9ca3af] break-all">{item.message}</div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
            <ChatPanel
                messages={visibleChatMessages}
                fsmState={store.fsmState}
                onConfirmDraft={handleConfirm}
                onRollbackDraft={handleRollback}
                isConfirmDisabled={store.fsmState === 'CONFLICT'}
                draftActionPending={store.draftActionPending}
                editableUserMessageId={latestUserMessageId}
                onRequestEditUserMessage={beginRewriteFromMessage}
                editingUserMessageId={rewriteUserMessageId}
                editDraftValue={commandInput}
                onEditDraftChange={setCommandInput}
                onSubmitEditUserMessage={handleInlineRewriteSubmit}
                onCancelEditUserMessage={handleCancelRewrite}
            />
            {!rewriteUserMessageId ? (
                <ChatComposerDock
                    isRunDisabled={store.fsmState === 'THINKING'}
                    isStreaming={store.fsmState === 'THINKING'}
                    submitLabel={copy.composer.send}
                    onSubmit={handleCommandSubmit}
                    onStop={handleStopStream}
                />
            ) : null}
        </div>
    );

    const reviewCenterPanel = (
        <div className="relative flex h-full min-h-0 flex-col overflow-hidden">
            {store.fsmState === 'CONFLICT' && (
                <ConflictBanner isVisible={true} onRefreshLock={handleRefreshLock} />
            )}
            <div className={store.fsmState === 'CONFLICT' ? 'min-h-0 flex-1 pt-16' : 'min-h-0 flex-1'}>
                <ReviewCanvasPanel
                    fileName={reviewTargetFile}
                    mainlineContent={reviewMainlineContent}
                    draftContent={store.draftContent}
                    draftCommitId={store.draftCommitId}
                    fsmState={store.fsmState}
                    onOpenFullscreen={() => setReviewDiffFullscreenOpen(true)}
                />
            </div>
        </div>
    );

    const gitRightPanel = repoIntegrity?.needsRepair ? (
        <div className="flex h-full min-h-0 items-center justify-center bg-[#0b1119] px-6 text-sm text-[#d9bf95]">
            修复仓库布局后，这里才会恢复工作区状态、提交文件与 Diff 预览。
        </div>
    ) : (
        <GitWorkingTreePanel
            status={store.gitStatus}
            workingTree={store.gitWorkingTree}
            commitFiles={store.gitCommitFiles}
            selectedCommit={
                store.gitHistoryCommits.find((row) => row.commitId === store.selectedGitCommitId) || null
            }
            selectedPath={store.selectedGitPath}
            commitDiffPayload={store.gitDiffPayload}
            pending={store.gitActionPending}
            onSelectPath={store.setSelectedGitPath}
            onOpenCommitDiff={(path, commitId) => {
                void handleGitOpenCommitDiff(path, commitId);
            }}
            onStage={(path) => {
                void handleGitStage(path);
            }}
            onUnstage={(path) => {
                void handleGitUnstage(path);
            }}
            onStageAll={() => {
                void handleGitStageAll();
            }}
            onCommit={(message) => {
                void handleGitCommit(message);
            }}
            onOpenFullscreenDiff={() => {
                store.setGitDiffFullscreen(true);
            }}
        />
    );
    const reviewRightPanel = (
        <div className="flex h-full min-h-0 flex-col">
            <div className="min-h-[220px] flex-[0_0_42%] border-b border-[rgba(255,255,255,0.04)]">
                <ReviewInspectorPanel
                    fileName={reviewTargetFile}
                    branch={latestDraftAttachment?.branch || store.draftBranch}
                    draftCommitId={store.draftCommitId}
                    draftContent={store.draftContent}
                    mainlineContent={reviewMainlineContent}
                    draftAttachment={latestDraftAttachment}
                    fsmState={store.fsmState}
                    draftActionPending={store.draftActionPending}
                    onConfirm={handleConfirm}
                    onRollback={handleRollback}
                    onRunReviewAgent={reviewTargetFile === 'chapter_draft.md' ? handleRunReviewAgent : undefined}
                    onRewriteWithReview={reviewTargetFile === 'chapter_draft.md' ? handleRewriteWithReview : undefined}
                    onOpenFullscreen={() => setReviewDiffFullscreenOpen(true)}
                    onBackToEditor={() => store.setWorkbenchMode('editor')}
                    onRefreshLock={handleRefreshLock}
                />
            </div>
            <div className="min-h-0 flex-1">
                {editorRightPanel}
            </div>
        </div>
    );

    const workbenchCenterPanel = (
        <WorkbenchModeLayer
            activeMode={store.workbenchMode}
            editorView={editorCenterPanel}
            reviewView={hasReviewWorkspace ? reviewCenterPanel : null}
            gitView={gitCenterPanel}
        />
    );

    const workbenchRightPanel = (
        <WorkbenchModeLayer
            activeMode={store.workbenchMode}
            editorView={editorRightPanel}
            reviewView={hasReviewWorkspace ? reviewRightPanel : null}
            gitView={gitRightPanel}
        />
    );
    const workbenchActions = buildWorkbenchActions(
        {
            activeFile: store.activeFile,
            activeFileType: store.activeFileType,
            fsmState: store.fsmState,
            workbenchMode: store.workbenchMode,
            repoNeedsRepair: Boolean(repoIntegrity?.needsRepair),
            hasReviewWorkspace,
            worldInitRunState: worldInitActionState.runState,
            worldInitProgress: worldInitActionState.progress,
            styleInitRunState: styleInitActionState.runState,
            styleInitProgress: styleInitActionState.progress,
            rollingRunState: rollingActionState.runState,
            rollingState: rollingActionState.state,
            rollingProgress: rollingActionState.progress,
            postConfirmRunState: postConfirmHandoffState.runState,
            postConfirmProgress: postConfirmHandoffState.progress,
            hasPostConfirmPayload: Boolean(postConfirmHandoffState.payload),
        },
        {
            onRunWorldInit: handleRunWorldInitAction,
            onRunStyleInit: handleRunStyleInitAction,
            onRefreshRollingState: handleRefreshRollingState,
            onRunRollingContinuation: handleRunRollingContinuation,
            onOpenRuntimeConfig: () => setRuntimeConfigOpen(true),
            onRunPostConfirmHandoff: handleRunPostConfirmHandoff,
        },
    );

    return (
        <>
            <AppLayout
                activityBar={activityBar}
                topBar={topBar}
                leftPanel={workbenchLeftPanel}
                centerPanel={workbenchCenterPanel}
                rightPanel={workbenchRightPanel}
            />
            <GitDiffFullscreen />
            <ReviewDiffFullscreen
                isOpen={hasReviewWorkspace && reviewDiffFullscreenOpen}
                fileName={reviewTargetFile}
                branch={latestDraftAttachment?.branch || store.draftBranch}
                draftCommitId={store.draftCommitId}
                mainlineContent={reviewMainlineContent}
                draftContent={store.draftContent}
                fsmState={store.fsmState}
                draftActionPending={store.draftActionPending}
                onConfirm={handleConfirm}
                onRollback={handleRollback}
                onClose={() => setReviewDiffFullscreenOpen(false)}
            />
            <ReviewReadyNotice
                notice={store.reviewReadyNotice}
                uiLanguage={store.uiLanguage}
                onEnterReview={handleEnterReviewFromNotice}
                onClose={store.clearReviewReadyNotice}
            />
            <WorkbenchActionDock
                activeFile={store.activeFile}
                activeFileType={store.activeFileType}
                fsmState={store.fsmState}
                workbenchMode={store.workbenchMode}
                repoNeedsRepair={Boolean(repoIntegrity?.needsRepair)}
                actions={workbenchActions}
            />
            <RuntimeConfigPanel
                isOpen={runtimeConfigOpen}
                onClose={() => setRuntimeConfigOpen(false)}
                onSaved={() => store.setUiNotice({ type: 'success', message: '本机配置已保存，后端 Dify 路由已热刷新。', ts: Date.now() })}
            />
            <ToastNotice notice={store.uiNotice} onClose={store.clearUiNotice} />
        </>
    );
}
