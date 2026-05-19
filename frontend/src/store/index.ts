import { create } from 'zustand';
import {
    AppStore,
    AssistantTimelineSegment,
    ChatMessage,
    CoreSessionState,
    DiffAttachment,
    DraftResolution,
    GitBranchRow,
    GitCommitFile,
    GitDiffPayload,
    GitFilePayload,
    GitHistoryCommit,
    GitStatusSummary,
    GitWorkingTreeEntry,
    ReasoningTrace,
    StageProgress,
} from '../types/store';
import { resolveAgentKey } from '../lib/agentKey';
import { rewriteTailMessages } from '../lib/tailRewrite.js';

const UI_LANGUAGE_STORAGE_KEY = 'novel-agent-ui-language';

function readInitialUiLanguage(): 'zh-CN' | 'en-US' {
    if (typeof window === 'undefined') return 'zh-CN';
    const savedLanguage = window.localStorage.getItem(UI_LANGUAGE_STORAGE_KEY);
    return savedLanguage === 'en-US' ? 'en-US' : 'zh-CN';
}

const initialState: CoreSessionState = {
    bookRef: { kind: 'book_name', value: '' },
    activeFile: 'world_model.md',
    activeFileType: 'world_core',
    hotFiles: [],
    mainlineContent: '',
    draftContent: '',
    baseEtag: '',
    reviewTargetFile: null,
    reviewMainlineContent: '',
    reviewMainlineEtag: '',
    reviewChangedFiles: [],
    draftBranch: 'draft/sandbox',
    draftCommitId: null,
    activeAgent: 'world_agent',
    conversationId: null,
    upstreamConversationId: null,
    conversationByAgent: {},
    upstreamConversationByAgent: {},
    conversationIndexByAgent: {},
    chatMessages: [],
    chatMessagesByAgent: {},
    activeAssistantMessageId: null,
    fsmState: 'IDLE',
    draftActionPending: 'none',
    uiNotice: null,
    reviewReadyNotice: null,
    uiLanguage: readInitialUiLanguage(),
    workbenchMode: 'editor',
    gitStatus: null,
    gitBranches: [],
    gitHistoryCommits: [],
    gitWorkingTree: [],
    gitCommitFiles: [],
    gitLoading: false,
    gitActionPending: false,
    gitError: null,
    selectedGitCommitId: null,
    selectedGitPath: null,
    gitCenterMode: 'commit_list',
    gitDiffPayload: null,
    gitFilePayload: null,
    gitDiffFullscreen: false,
};

function createMessageId(prefix: string): string {
    return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function patchMessage(
    messages: ChatMessage[],
    messageId: string,
    updater: (current: ChatMessage) => ChatMessage
): ChatMessage[] {
    return messages.map((msg) => (msg.id === messageId ? updater(msg) : msg));
}

function appendAnswerTimelineSegment(
    segments: AssistantTimelineSegment[],
    delta: string
): AssistantTimelineSegment[] {
    if (!delta) return segments;
    const existing = segments.length > 0
        ? [
            ...segments.slice(0, -1),
            segments[segments.length - 1].status === 'streaming'
                ? { ...segments[segments.length - 1], status: 'done' as const }
                : segments[segments.length - 1],
        ]
        : segments;
    const prev = existing[existing.length - 1];
    if (prev?.kind === 'answer') {
        return [
            ...existing.slice(0, -1),
            {
                ...prev,
                text: `${prev.text}${delta}`,
                status: 'streaming',
            },
        ];
    }
    return [
        ...existing,
        {
            id: createMessageId('answer_segment'),
            kind: 'answer',
            text: delta,
            status: 'streaming',
        },
    ];
}

function appendThinkingTimelineSegment(
    segments: AssistantTimelineSegment[],
    reasoning: ReasoningTrace
): AssistantTimelineSegment[] {
    const normalizedReasoning = {
        ...reasoning,
        status: reasoning.status || 'streaming' as const,
    };
    const prev = segments[segments.length - 1];
    if (
        prev?.kind === 'thinking'
        && prev.status === 'streaming'
        && prev.label === normalizedReasoning.label
        && prev.sourceEvent === normalizedReasoning.sourceEvent
    ) {
        const nextText = normalizedReasoning.append
            ? `${prev.text}${normalizedReasoning.text}`
            : normalizedReasoning.text;
        return [
            ...segments.slice(0, -1),
            {
                ...prev,
                text: nextText,
                status: normalizedReasoning.status,
            },
        ];
    }
    if (
        prev?.kind === 'thinking'
        && prev.label === normalizedReasoning.label
        && prev.text === normalizedReasoning.text
        && prev.sourceEvent === normalizedReasoning.sourceEvent
        && prev.status === normalizedReasoning.status
    ) {
        return segments;
    }
    const existing = prev?.status === 'streaming'
        ? [
            ...segments.slice(0, -1),
            { ...prev, status: 'done' as const },
        ]
        : segments;
    return [
        ...existing,
        {
            id: createMessageId('thinking_segment'),
            kind: 'thinking',
            label: normalizedReasoning.label,
            text: normalizedReasoning.text,
            sourceEvent: normalizedReasoning.sourceEvent,
            status: normalizedReasoning.status,
        },
    ];
}

function markTimelineSegmentsDone(segments: AssistantTimelineSegment[]): AssistantTimelineSegment[] {
    return segments.map((item) => ({
        ...item,
        status: 'done',
    }));
}

function resetGitState(): Pick<
    CoreSessionState,
    | 'gitStatus'
    | 'gitBranches'
    | 'gitHistoryCommits'
    | 'gitWorkingTree'
    | 'gitCommitFiles'
    | 'gitLoading'
    | 'gitActionPending'
    | 'gitError'
    | 'selectedGitCommitId'
    | 'selectedGitPath'
    | 'gitCenterMode'
    | 'gitDiffPayload'
    | 'gitFilePayload'
    | 'gitDiffFullscreen'
> {
    return {
        gitStatus: null,
        gitBranches: [],
        gitHistoryCommits: [],
        gitWorkingTree: [],
        gitCommitFiles: [],
        gitLoading: false,
        gitActionPending: false,
        gitError: null,
        selectedGitCommitId: null,
        selectedGitPath: null,
        gitCenterMode: 'commit_list',
        gitDiffPayload: null,
        gitFilePayload: null,
        gitDiffFullscreen: false,
    };
}

export const useAppStore = create<AppStore>()((set) => ({
    ...initialState,
    setFsmState: (fsmState) => set({ fsmState }),
    setAddressingContext: (bookRef, activeFile, activeFileType = 'world_core') =>
        set({
            bookRef,
            activeFile,
            activeFileType,
            activeAgent: resolveAgentKey(activeFile, activeFileType),
            mainlineContent: '',
            draftContent: '',
            baseEtag: '',
            reviewTargetFile: null,
            reviewMainlineContent: '',
            reviewMainlineEtag: '',
            reviewChangedFiles: [],
            draftCommitId: null,
            conversationId: null,
            upstreamConversationId: null,
            conversationByAgent: {},
            upstreamConversationByAgent: {},
            conversationIndexByAgent: {},
            activeAssistantMessageId: null,
            draftActionPending: 'none',
            uiNotice: null,
            reviewReadyNotice: null,
            workbenchMode: 'editor',
            chatMessages: [],
            chatMessagesByAgent: {},
            ...resetGitState(),
        }),
    setActiveFile: (fileName, fileType) =>
        set((state) => {
            const nextAgent = resolveAgentKey(fileName, fileType);
            const nextConversationByAgent = { ...state.conversationByAgent };
            const nextUpstreamConversationByAgent = { ...state.upstreamConversationByAgent };
            const nextChatMessagesByAgent = {
                ...state.chatMessagesByAgent,
                [state.activeAgent]: state.chatMessages,
            };
            if (state.conversationId) {
                nextConversationByAgent[state.activeAgent] = state.conversationId;
            }
            if (state.upstreamConversationId) {
                nextUpstreamConversationByAgent[state.activeAgent] = state.upstreamConversationId;
            }
            return {
                activeFile: fileName,
                activeFileType: fileType,
                activeAgent: nextAgent,
                conversationByAgent: nextConversationByAgent,
                upstreamConversationByAgent: nextUpstreamConversationByAgent,
                conversationId: nextConversationByAgent[nextAgent] ?? null,
                upstreamConversationId: nextUpstreamConversationByAgent[nextAgent] ?? null,
                chatMessagesByAgent: nextChatMessagesByAgent,
                chatMessages: nextChatMessagesByAgent[nextAgent] ?? [],
                activeAssistantMessageId: null,
                draftContent: '',
                draftCommitId: null,
                reviewTargetFile: null,
                reviewMainlineContent: '',
                reviewMainlineEtag: '',
                reviewChangedFiles: [],
                draftActionPending: 'none',
                reviewReadyNotice: null,
            };
        }),
    setHotFiles: (hotFiles) => set({ hotFiles }),
    setMainlineFact: (content, etag) => set({ mainlineContent: content, baseEtag: etag }),
    setSandboxDraft: (content, commitId) => set({ draftContent: content, draftCommitId: commitId }),
    setReviewTarget: (fileName, changedFiles = []) =>
        set({
            reviewTargetFile: fileName,
            reviewChangedFiles: fileName ? changedFiles : [],
        }),
    setReviewMainlineFact: (content, etag) =>
        set({
            reviewMainlineContent: content,
            reviewMainlineEtag: etag,
        }),
    setConversationId: (conversationId) =>
        set((state) => {
            const nextConversationByAgent = { ...state.conversationByAgent };
            if (conversationId) {
                nextConversationByAgent[state.activeAgent] = conversationId;
            } else {
                delete nextConversationByAgent[state.activeAgent];
            }
            return {
                conversationId,
                conversationByAgent: nextConversationByAgent,
            };
        }),
    setUpstreamConversationId: (conversationId) =>
        set((state) => {
            const nextUpstreamConversationByAgent = { ...state.upstreamConversationByAgent };
            if (conversationId) {
                nextUpstreamConversationByAgent[state.activeAgent] = conversationId;
            } else {
                delete nextUpstreamConversationByAgent[state.activeAgent];
            }
            return {
                upstreamConversationId: conversationId,
                upstreamConversationByAgent: nextUpstreamConversationByAgent,
            };
        }),
    hydrateAgentConversation: (agent, conversationId, upstreamConversationId, messages, conversations) =>
        set((state) => {
            const nextConversationByAgent = { ...state.conversationByAgent };
            const nextUpstreamConversationByAgent = { ...state.upstreamConversationByAgent };
            const nextChatMessagesByAgent = { ...state.chatMessagesByAgent };
            const nextConversationIndexByAgent = { ...state.conversationIndexByAgent };
            if (conversationId) nextConversationByAgent[agent] = conversationId;
            else delete nextConversationByAgent[agent];
            if (upstreamConversationId) nextUpstreamConversationByAgent[agent] = upstreamConversationId;
            else delete nextUpstreamConversationByAgent[agent];
            nextChatMessagesByAgent[agent] = messages;
            nextConversationIndexByAgent[agent] = conversations;
            return {
                conversationByAgent: nextConversationByAgent,
                upstreamConversationByAgent: nextUpstreamConversationByAgent,
                conversationIndexByAgent: nextConversationIndexByAgent,
                chatMessagesByAgent: nextChatMessagesByAgent,
                conversationId: state.activeAgent === agent ? (nextConversationByAgent[agent] ?? null) : state.conversationId,
                upstreamConversationId: state.activeAgent === agent ? (nextUpstreamConversationByAgent[agent] ?? null) : state.upstreamConversationId,
                chatMessages: state.activeAgent === agent ? messages : state.chatMessages,
            };
        }),
    pushUserMessage: (text) => {
        const id = createMessageId('user');
        set((state) => ({
            chatMessages: (() => {
                const nextMessages = [
                    ...state.chatMessages,
                    {
                        id,
                        role: 'user' as const,
                        text,
                        status: 'done' as const,
                        conversationId: state.conversationId,
                        upstreamConversationId: state.upstreamConversationId,
                        activeFile: state.activeFile,
                        diffAttachment: null,
                        stageProgress: null,
                        stageEvents: [],
                        reasoningEvents: [],
                        previewEvents: [],
                        timelineSegments: [],
                        resolution: null,
                        resolvedAt: null,
                    },
                ];
                return nextMessages;
            })(),
            chatMessagesByAgent: {
                ...state.chatMessagesByAgent,
                [state.activeAgent]: [
                    ...state.chatMessages,
                    {
                        id,
                        role: 'user' as const,
                        text,
                        status: 'done' as const,
                        conversationId: state.conversationId,
                        upstreamConversationId: state.upstreamConversationId,
                        activeFile: state.activeFile,
                        diffAttachment: null,
                        stageProgress: null,
                        stageEvents: [],
                        reasoningEvents: [],
                        previewEvents: [],
                        timelineSegments: [],
                        resolution: null,
                        resolvedAt: null,
                    },
                ],
            },
        }));
        return id;
    },
    startAssistantMessage: () => {
        const id = createMessageId('assistant');
        set((state) => ({
            activeAssistantMessageId: id,
            chatMessages: [
                ...state.chatMessages,
                {
                    id,
                    role: 'assistant' as const,
                    text: '',
                    status: 'streaming' as const,
                    conversationId: state.conversationId,
                    upstreamConversationId: state.upstreamConversationId,
                    activeFile: state.activeFile,
                    diffAttachment: null,
                    stageProgress: null,
                    stageEvents: [],
                    reasoningEvents: [],
                    previewEvents: [],
                    timelineSegments: [],
                    resolution: null,
                    resolvedAt: null,
                },
            ],
            chatMessagesByAgent: {
                ...state.chatMessagesByAgent,
                [state.activeAgent]: [
                    ...state.chatMessages,
                    {
                        id,
                        role: 'assistant' as const,
                        text: '',
                        status: 'streaming' as const,
                        conversationId: state.conversationId,
                        upstreamConversationId: state.upstreamConversationId,
                        activeFile: state.activeFile,
                        diffAttachment: null,
                        stageProgress: null,
                        stageEvents: [],
                        reasoningEvents: [],
                        previewEvents: [],
                        timelineSegments: [],
                        resolution: null,
                        resolvedAt: null,
                    },
                ],
            },
        }));
        return id;
    },
    appendAssistantDelta: (messageId, delta, conversationId) =>
        set((state) => {
            const nextUpstreamConversationId = conversationId ?? state.upstreamConversationId;
            const nextConversationByAgent = { ...state.conversationByAgent };
            const nextUpstreamConversationByAgent = { ...state.upstreamConversationByAgent };
            if (state.conversationId) {
                nextConversationByAgent[state.activeAgent] = state.conversationId;
            }
            if (nextUpstreamConversationId) {
                nextUpstreamConversationByAgent[state.activeAgent] = nextUpstreamConversationId;
            }
            const nextMessages = patchMessage(state.chatMessages, messageId, (msg) => ({
                ...msg,
                text: `${msg.text}${delta}`,
                status: 'streaming',
                upstreamConversationId: conversationId ?? msg.upstreamConversationId,
                stageProgress: null,
                timelineSegments: appendAnswerTimelineSegment(msg.timelineSegments, delta),
            }));
            return {
                conversationId: state.conversationId,
                upstreamConversationId: nextUpstreamConversationId,
                conversationByAgent: nextConversationByAgent,
                upstreamConversationByAgent: nextUpstreamConversationByAgent,
                chatMessages: nextMessages,
                chatMessagesByAgent: {
                    ...state.chatMessagesByAgent,
                    [state.activeAgent]: nextMessages,
                },
            };
        }),
    appendAssistantPreview: (messageId, preview) =>
        set((state) => {
            const nextMessages = patchMessage(state.chatMessages, messageId, (msg) => {
                const normalizedPreview = {
                    ...preview,
                    status: preview.status || 'streaming' as const,
                };
                const existing = msg.previewEvents;
                const prev = existing[existing.length - 1];
                const shouldMergeIntoPrev = Boolean(
                    prev
                    && prev.status === 'streaming'
                    && prev.label === normalizedPreview.label
                    && prev.sourceEvent === normalizedPreview.sourceEvent
                );
                if (shouldMergeIntoPrev) {
                    const merged = [
                        ...existing.slice(0, -1),
                        {
                            ...prev,
                            text: normalizedPreview.text,
                            status: normalizedPreview.status,
                        },
                    ];
                    return {
                        ...msg,
                        previewEvents: merged.slice(-11),
                    };
                }
                const nextExisting = prev && prev.status === 'streaming'
                    ? [
                        ...existing.slice(0, -1),
                        {
                            ...prev,
                            status: 'done' as const,
                        },
                    ]
                    : existing;
                const isDuplicate = Boolean(
                    prev
                    && prev.label === normalizedPreview.label
                    && prev.text === normalizedPreview.text
                    && prev.sourceEvent === normalizedPreview.sourceEvent
                    && prev.status === normalizedPreview.status
                );
                return {
                    ...msg,
                    previewEvents: isDuplicate
                        ? nextExisting
                        : [...nextExisting.slice(-11), normalizedPreview],
                };
            });
            return {
                chatMessages: nextMessages,
                chatMessagesByAgent: {
                    ...state.chatMessagesByAgent,
                    [state.activeAgent]: nextMessages,
                },
            };
        }),
    appendAssistantReasoning: (messageId, reasoning) =>
        set((state) => {
            const nextMessages = patchMessage(state.chatMessages, messageId, (msg) => {
                const normalizedReasoning = {
                    ...reasoning,
                    status: reasoning.status || 'streaming' as const,
                };
                const existing = msg.reasoningEvents;
                const prev = existing[existing.length - 1];
                const shouldMergeIntoPrev = Boolean(
                    prev
                    && prev.status === 'streaming'
                    && prev.label === normalizedReasoning.label
                    && prev.sourceEvent === normalizedReasoning.sourceEvent
                );
                if (shouldMergeIntoPrev) {
                    const nextText = normalizedReasoning.append
                        ? `${prev.text}${normalizedReasoning.text}`
                        : normalizedReasoning.text;
                    const merged = [
                        ...existing.slice(0, -1),
                        {
                            ...prev,
                            text: nextText,
                            status: normalizedReasoning.status,
                        },
                    ];
                    return {
                        ...msg,
                        reasoningEvents: merged.slice(-11),
                        timelineSegments: appendThinkingTimelineSegment(msg.timelineSegments, normalizedReasoning),
                    };
                }
                const nextExisting = prev && prev.status === 'streaming'
                    ? [
                        ...existing.slice(0, -1),
                        {
                            ...prev,
                            status: 'done' as const,
                        },
                    ]
                    : existing;
                const isDuplicate = Boolean(
                    prev
                    && prev.label === normalizedReasoning.label
                    && prev.text === normalizedReasoning.text
                    && prev.sourceEvent === normalizedReasoning.sourceEvent
                    && prev.status === normalizedReasoning.status
                );
                return {
                    ...msg,
                    reasoningEvents: isDuplicate
                        ? nextExisting
                        : [...nextExisting.slice(-11), normalizedReasoning],
                    timelineSegments: appendThinkingTimelineSegment(msg.timelineSegments, normalizedReasoning),
                };
            });
            return {
                chatMessages: nextMessages,
                chatMessagesByAgent: {
                    ...state.chatMessagesByAgent,
                    [state.activeAgent]: nextMessages,
                },
            };
        }),
    setAssistantStageProgress: (messageId, stage: StageProgress | null) =>
        set((state) => {
            const nextMessages = patchMessage(state.chatMessages, messageId, (msg) => ({
                ...(() => {
                    const existing = msg.stageEvents;
                    if (!stage) {
                        return {
                            ...msg,
                            stageProgress: null,
                            stageEvents: existing.map((item, idx) => (
                                idx === existing.length - 1 && item.status === 'streaming'
                                    ? { ...item, status: 'done' as const }
                                    : item
                            )),
                        };
                    }
                    const normalizedStage = {
                        ...stage,
                        status: stage.status || 'streaming' as const,
                    };
                    const prev = existing[existing.length - 1];
                    const isDuplicate = Boolean(
                        prev
                        && prev.stageCode === normalizedStage.stageCode
                        && prev.stageText === normalizedStage.stageText
                        && prev.nodeTitle === normalizedStage.nodeTitle
                        && prev.nodeType === normalizedStage.nodeType
                    );
                    if (isDuplicate) {
                        const merged = [
                            ...existing.slice(0, -1),
                            {
                                ...prev,
                                ...normalizedStage,
                            },
                        ];
                        return {
                            ...msg,
                            stageProgress: normalizedStage,
                            stageEvents: merged,
                        };
                    }
                    const nextExisting = prev && prev.status === 'streaming'
                        ? [
                            ...existing.slice(0, -1),
                            {
                                ...prev,
                                status: 'done' as const,
                            },
                        ]
                        : existing;
                    return {
                        ...msg,
                        stageProgress: normalizedStage,
                        stageEvents: [...nextExisting.slice(-11), normalizedStage],
                    };
                })(),
            }));
            return {
                chatMessages: nextMessages,
                chatMessagesByAgent: {
                    ...state.chatMessagesByAgent,
                    [state.activeAgent]: nextMessages,
                },
            };
        }),
    finishAssistantMessage: (messageId, conversationId, upstreamConversationId, finalAnswer) =>
        set((state) => {
            const nextConversationId = conversationId ?? state.conversationId;
            const nextUpstreamConversationId = upstreamConversationId ?? state.upstreamConversationId;
            const nextConversationByAgent = { ...state.conversationByAgent };
            const nextUpstreamConversationByAgent = { ...state.upstreamConversationByAgent };
            if (nextConversationId) {
                nextConversationByAgent[state.activeAgent] = nextConversationId;
            }
            if (nextUpstreamConversationId) {
                nextUpstreamConversationByAgent[state.activeAgent] = nextUpstreamConversationId;
            }
            const nextMessages = patchMessage(state.chatMessages, messageId, (msg) => ({
                ...msg,
                status: 'done',
                text: msg.text || (typeof finalAnswer === 'string' ? finalAnswer : ''),
                conversationId: conversationId ?? msg.conversationId,
                upstreamConversationId: upstreamConversationId ?? msg.upstreamConversationId,
                stageProgress: null,
                stageEvents: msg.stageEvents.map((item) => ({
                    ...item,
                    status: 'done',
                })),
                previewEvents: msg.previewEvents.map((item) => ({
                    ...item,
                    status: 'done',
                })),
                reasoningEvents: msg.reasoningEvents.map((item) => ({
                    ...item,
                    status: 'done',
                })),
                timelineSegments: markTimelineSegmentsDone(
                    msg.timelineSegments.length > 0
                        ? msg.timelineSegments
                        : (
                            msg.text || typeof finalAnswer === 'string'
                                ? [{
                                    id: createMessageId('answer_segment'),
                                    kind: 'answer' as const,
                                    text: msg.text || (finalAnswer ?? ''),
                                    status: 'done' as const,
                                }]
                                : []
                        )
                ),
            }));
            return {
                activeAssistantMessageId: state.activeAssistantMessageId === messageId ? null : state.activeAssistantMessageId,
                conversationId: nextConversationId,
                upstreamConversationId: nextUpstreamConversationId,
                conversationByAgent: nextConversationByAgent,
                upstreamConversationByAgent: nextUpstreamConversationByAgent,
                chatMessages: nextMessages,
                chatMessagesByAgent: {
                    ...state.chatMessagesByAgent,
                    [state.activeAgent]: nextMessages,
                },
            };
        }),
    failAssistantMessage: (messageId, code, reason) =>
        set((state) => {
            const nextMessages = patchMessage(state.chatMessages, messageId, (msg) => ({
                ...msg,
                status: 'error',
                code,
                text: msg.text ? `${msg.text}\n\n[${code}] ${reason}` : `[${code}] ${reason}`,
                stageProgress: null,
                stageEvents: msg.stageEvents.map((item) => ({
                    ...item,
                    status: 'done',
                })),
                previewEvents: msg.previewEvents.map((item) => ({
                    ...item,
                    status: 'done',
                })),
                reasoningEvents: msg.reasoningEvents.map((item) => ({
                    ...item,
                    status: 'done',
                })),
                timelineSegments: markTimelineSegmentsDone(msg.timelineSegments),
            }));
            return {
                activeAssistantMessageId: state.activeAssistantMessageId === messageId ? null : state.activeAssistantMessageId,
                chatMessages: nextMessages,
                chatMessagesByAgent: {
                    ...state.chatMessagesByAgent,
                    [state.activeAgent]: nextMessages,
                },
            };
        }),
    interruptAssistantMessage: (messageId) =>
        set((state) => {
            const nextMessages = patchMessage(state.chatMessages, messageId, (msg) => ({
                ...msg,
                status: 'interrupted',
                stageProgress: null,
                stageEvents: msg.stageEvents.map((item) => ({
                    ...item,
                    status: 'done',
                })),
                previewEvents: msg.previewEvents.map((item) => ({
                    ...item,
                    status: 'done',
                })),
                reasoningEvents: msg.reasoningEvents.map((item) => ({
                    ...item,
                    status: 'done',
                })),
                timelineSegments: markTimelineSegmentsDone(msg.timelineSegments),
            }));
            return {
                activeAssistantMessageId: state.activeAssistantMessageId === messageId ? null : state.activeAssistantMessageId,
                chatMessages: nextMessages,
                chatMessagesByAgent: {
                    ...state.chatMessagesByAgent,
                    [state.activeAgent]: nextMessages,
                },
            };
        }),
    attachDiffToAssistantMessage: (messageId, attachment: DiffAttachment) =>
        set((state) => {
            const nextMessages = patchMessage(state.chatMessages, messageId, (msg) => ({
                ...msg,
                diffAttachment: attachment,
                resolution: null,
                resolvedAt: null,
            }));
            return {
                chatMessages: nextMessages,
                chatMessagesByAgent: {
                    ...state.chatMessagesByAgent,
                    [state.activeAgent]: nextMessages,
                },
            };
        }),
    updateUserMessageText: (messageId, text) =>
        set((state) => {
            const nextMessages = patchMessage(state.chatMessages, messageId, (msg) => (
                msg.role !== 'user'
                    ? msg
                    : { ...msg, text }
            ));
            return {
                chatMessages: nextMessages,
                chatMessagesByAgent: {
                    ...state.chatMessagesByAgent,
                    [state.activeAgent]: nextMessages,
                },
            };
        }),
    removeMessagesAfter: (messageId) =>
        set((state) => {
            const targetIndex = state.chatMessages.findIndex((msg) => msg.id === messageId);
            const nextMessages = targetIndex >= 0 ? state.chatMessages.slice(0, targetIndex + 1) : state.chatMessages;
            return {
                activeAssistantMessageId: nextMessages.some((msg) => msg.id === state.activeAssistantMessageId)
                    ? state.activeAssistantMessageId
                    : null,
                chatMessages: nextMessages,
                chatMessagesByAgent: {
                    ...state.chatMessagesByAgent,
                    [state.activeAgent]: nextMessages,
                },
            };
        }),
    rewriteTailFromUserMessage: (messageId, text) =>
        set((state) => {
            const nextMessages = rewriteTailMessages(state.chatMessages, messageId, text);
            return {
                activeAssistantMessageId: nextMessages.some((msg) => msg.id === state.activeAssistantMessageId)
                    ? state.activeAssistantMessageId
                    : null,
                chatMessages: nextMessages,
                chatMessagesByAgent: {
                    ...state.chatMessagesByAgent,
                    [state.activeAgent]: nextMessages,
                },
            };
        }),
    setDraftActionPending: (draftActionPending) => set({ draftActionPending }),
    setUiNotice: (uiNotice) => set({ uiNotice }),
    clearUiNotice: () => set({ uiNotice: null }),
    setReviewReadyNotice: (reviewReadyNotice) => set({ reviewReadyNotice }),
    clearReviewReadyNotice: () => set({ reviewReadyNotice: null }),
    setUiLanguage: (uiLanguage) => {
        if (typeof window !== 'undefined') {
            window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, uiLanguage);
        }
        set({ uiLanguage });
    },
    setWorkbenchMode: (workbenchMode) => set({ workbenchMode }),
    setGitStatus: (gitStatus: GitStatusSummary | null) => set({ gitStatus }),
    setGitBranches: (gitBranches: GitBranchRow[]) => set({ gitBranches }),
    setGitHistoryCommits: (gitHistoryCommits: GitHistoryCommit[]) =>
        set((state) => ({
            gitHistoryCommits,
            selectedGitCommitId: state.selectedGitCommitId && gitHistoryCommits.some((row) => row.commitId === state.selectedGitCommitId)
                ? state.selectedGitCommitId
                : (gitHistoryCommits[0]?.commitId || null),
        })),
    setGitWorkingTree: (gitWorkingTree: GitWorkingTreeEntry[]) => set({ gitWorkingTree }),
    setGitCommitFiles: (gitCommitFiles: GitCommitFile[]) => set({ gitCommitFiles }),
    setGitLoading: (gitLoading) => set({ gitLoading }),
    setGitActionPending: (gitActionPending) => set({ gitActionPending }),
    setGitError: (gitError) => set({ gitError }),
    setSelectedGitCommit: (selectedGitCommitId) => set({ selectedGitCommitId }),
    setSelectedGitPath: (selectedGitPath) => set({ selectedGitPath }),
    setGitCenterMode: (gitCenterMode) => set({ gitCenterMode }),
    setGitDiffPayload: (gitDiffPayload: GitDiffPayload | null) => set({ gitDiffPayload }),
    setGitFilePayload: (gitFilePayload: GitFilePayload | null) => set({ gitFilePayload }),
    setGitDiffFullscreen: (gitDiffFullscreen) => set({ gitDiffFullscreen }),
    resetGitConsole: () => set({ ...resetGitState() }),
    flushAllStore: () =>
        set((state) => ({
            mainlineContent: '',
            draftContent: '',
            baseEtag: '',
            reviewTargetFile: null,
            reviewMainlineContent: '',
            reviewMainlineEtag: '',
            reviewChangedFiles: [],
            draftCommitId: null,
            activeAgent: resolveAgentKey(state.activeFile, state.activeFileType),
            conversationId: null,
            upstreamConversationId: null,
            conversationByAgent: {},
            upstreamConversationByAgent: {},
            conversationIndexByAgent: {},
            chatMessages: [],
            chatMessagesByAgent: {},
            activeAssistantMessageId: null,
            fsmState: 'IDLE',
            draftActionPending: 'none',
            uiNotice: null,
            reviewReadyNotice: null,
            uiLanguage: state.uiLanguage,
            ...resetGitState(),
            workbenchMode: state.workbenchMode,
            hotFiles: state.hotFiles,
            activeFile: state.activeFile,
            activeFileType: state.activeFileType,
        })),
    markDraftResolved: (resolution: DraftResolution) =>
        set((state) => {
            const nextMessages = state.chatMessages.map((msg) => {
                if (!msg.diffAttachment) return msg;
                return {
                    ...msg,
                    diffAttachment: null,
                    resolution,
                    resolvedAt: Date.now(),
                };
            });
            return {
                chatMessages: nextMessages,
                chatMessagesByAgent: {
                    ...state.chatMessagesByAgent,
                    [state.activeAgent]: nextMessages,
                },
            };
        }),
    clearChat: () => set((state) => ({
        chatMessages: [],
        activeAssistantMessageId: null,
        chatMessagesByAgent: {
            ...state.chatMessagesByAgent,
            [state.activeAgent]: [],
        },
    })),
    resetSandbox: () =>
        set((state) => ({
            draftContent: '',
            draftCommitId: null,
            reviewTargetFile: null,
            reviewMainlineContent: '',
            reviewMainlineEtag: '',
            reviewChangedFiles: [],
            activeAssistantMessageId: null,
            fsmState: 'IDLE',
            draftActionPending: 'none',
            reviewReadyNotice: null,
            chatMessages: (() => {
                const nextMessages = state.chatMessages.map((msg) => ({
                    ...msg,
                    diffAttachment: null,
                }));
                return nextMessages;
            })(),
            chatMessagesByAgent: {
                ...state.chatMessagesByAgent,
                [state.activeAgent]: state.chatMessages.map((msg) => ({
                    ...msg,
                    diffAttachment: null,
                })),
            },
        })),
}));
