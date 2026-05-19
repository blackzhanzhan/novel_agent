export type FsmState = 'IDLE' | 'THINKING' | 'REVIEW' | 'CONFLICT';
export type ChatRole = 'user' | 'assistant' | 'system';
export type ChatMessageStatus = 'streaming' | 'done' | 'error' | 'interrupted';
export type DraftActionPending = 'none' | 'confirm' | 'rollback';
export type DraftResolution = 'confirmed' | 'rolled_back';
export type FileType = 'world_core' | 'summary' | 'outline' | 'style' | 'chapter' | 'error_archive';
export type WorkbenchMode = 'editor' | 'review' | 'git';
export type GitCenterMode = 'commit_list' | 'file_view' | 'diff_view';
export type GitDiffScope = 'unstaged' | 'staged' | 'commit';
export type AgentKey = 'world_agent' | 'outline_agent' | 'style_agent' | 'continuation_agent' | 'review_agent';
export type UiLanguage = 'zh-CN' | 'en-US';

export interface RepoIntegrity {
    bookId: string;
    exists: boolean;
    repoExists: boolean;
    headExists: boolean;
    headCommit: string | null;
    missingCoreFiles: string[];
    missingDirectories: string[];
    untrackedLayoutFiles: string[];
    problemCodes: string[];
    needsRepair: boolean;
}

export interface HotFileItem {
    fileName: string;
    fileType: FileType;
    label: string;
    exists?: boolean;
    virtual?: boolean;
}

export interface StageProgress {
    stageCode: string;
    stageText: string;
    sourceEvent?: string;
    nodeTitle?: string;
    nodeType?: string;
    status?: 'streaming' | 'done';
}

export interface ReasoningTrace {
    label: string;
    text: string;
    append?: boolean;
    sourceEvent?: string;
    status?: 'streaming' | 'done';
}

export interface PreviewTrace {
    label: string;
    text: string;
    sourceEvent?: string;
    status?: 'streaming' | 'done';
}

export interface AssistantThinkingTimelineSegment {
    id: string;
    kind: 'thinking';
    label: string;
    text: string;
    sourceEvent?: string;
    status?: 'streaming' | 'done';
}

export interface AssistantAnswerTimelineSegment {
    id: string;
    kind: 'answer';
    text: string;
    status?: 'streaming' | 'done';
}

export type AssistantTimelineSegment = AssistantThinkingTimelineSegment | AssistantAnswerTimelineSegment;

export interface ConversationMeta {
    conversation_id: string;
    title: string;
    created_at: string;
    updated_at: string;
    last_active_file: string;
    message_count: number;
    upstream_conversation_id?: string | null;
}

export interface GitStatusSummary {
    currentBranch: string;
    mainlineBranch: string;
    headCommit: string;
    isDirty: boolean;
    stagedCount: number;
    unstagedCount: number;
    untrackedCount: number;
}

export interface GitBranchRow {
    name: string;
    headCommit: string;
    updatedAt: string;
    headMessage: string;
    isCurrent: boolean;
    isMainline: boolean;
}

export interface GitHistoryCommit {
    commitId: string;
    shortId: string;
    parentIds: string[];
    timestamp: string;
    authorName: string;
    authorEmail: string;
    message: string;
    refs: string[];
}

export interface GitGraphCommit {
    commitId: string;
    parentIds: string[];
    timestamp: string;
    message: string;
    refs: string[];
}

export interface GitWorkingTreeEntry {
    path: string;
    previousPath: string | null;
    indexStatus: string;
    worktreeStatus: string;
    staged: boolean;
    unstaged: boolean;
    isUntracked: boolean;
}

export interface GitCommitFile {
    path: string;
    previousPath: string | null;
    status: string;
}

export interface GitDiffPayload {
    scope: GitDiffScope;
    path: string;
    oldLabel: string;
    newLabel: string;
    oldText: string;
    newText: string;
    changed: boolean;
    commitId?: string;
}

export interface GitFilePayload {
    path: string;
    source: string;
    content: string;
}

export interface DiffAttachment {
    fileName: string;
    branch: string;
    commitId: string | null;
    etag: string;
    content: string;
    diffPreview: string;
}

export interface ChatMessage {
    id: string;
    role: ChatRole;
    text: string;
    status: ChatMessageStatus;
    conversationId: string | null;
    upstreamConversationId?: string | null;
    activeFile?: string;
    diffAttachment: DiffAttachment | null;
    stageProgress: StageProgress | null;
    stageEvents: StageProgress[];
    reasoningEvents: ReasoningTrace[];
    previewEvents: PreviewTrace[];
    timelineSegments: AssistantTimelineSegment[];
    code?: string;
    resolution?: DraftResolution | null;
    resolvedAt?: number | null;
}

export interface UiNotice {
    type: 'success' | 'error' | 'info';
    message: string;
    ts: number;
}

export interface ReviewReadyNotice {
    fileName: string;
    branch: string;
    commitId: string | null;
    diffPreview: string;
    changedFiles: string[];
    ts: number;
}

export interface CoreSessionState {
    bookRef: { kind: 'book_name' | 'book_id'; value: string };
    activeFile: string;
    activeFileType: FileType;
    hotFiles: HotFileItem[];
    mainlineContent: string;
    draftContent: string;
    baseEtag: string;
    reviewTargetFile: string | null;
    reviewMainlineContent: string;
    reviewMainlineEtag: string;
    reviewChangedFiles: string[];
    draftBranch: 'draft/sandbox';
    draftCommitId: string | null;
    activeAgent: AgentKey;
    conversationId: string | null;
    upstreamConversationId: string | null;
    conversationByAgent: Record<string, string>;
    upstreamConversationByAgent: Record<string, string>;
    conversationIndexByAgent: Record<string, ConversationMeta[]>;
    chatMessages: ChatMessage[];
    chatMessagesByAgent: Record<string, ChatMessage[]>;
    activeAssistantMessageId: string | null;
    fsmState: FsmState;
    draftActionPending: DraftActionPending;
    uiNotice: UiNotice | null;
    reviewReadyNotice: ReviewReadyNotice | null;
    uiLanguage: UiLanguage;
    workbenchMode: WorkbenchMode;
    gitStatus: GitStatusSummary | null;
    gitBranches: GitBranchRow[];
    gitHistoryCommits: GitHistoryCommit[];
    gitWorkingTree: GitWorkingTreeEntry[];
    gitCommitFiles: GitCommitFile[];
    gitLoading: boolean;
    gitActionPending: boolean;
    gitError: string | null;
    selectedGitCommitId: string | null;
    selectedGitPath: string | null;
    gitCenterMode: GitCenterMode;
    gitDiffPayload: GitDiffPayload | null;
    gitFilePayload: GitFilePayload | null;
    gitDiffFullscreen: boolean;
}

export interface StoreActions {
    setFsmState: (state: FsmState) => void;
    setAddressingContext: (
        bookRef: CoreSessionState['bookRef'],
        activeFile: CoreSessionState['activeFile'],
        activeFileType?: FileType
    ) => void;
    setActiveFile: (fileName: string, fileType: FileType) => void;
    setHotFiles: (files: HotFileItem[]) => void;
    setMainlineFact: (content: string, etag: string) => void;
    setSandboxDraft: (content: string, commitId: string | null) => void;
    setReviewTarget: (fileName: string | null, changedFiles?: string[]) => void;
    setReviewMainlineFact: (content: string, etag: string) => void;
    setConversationId: (conversationId: string | null) => void;
    setUpstreamConversationId: (conversationId: string | null) => void;
    hydrateAgentConversation: (
        agent: AgentKey,
        conversationId: string | null,
        upstreamConversationId: string | null,
        messages: ChatMessage[],
        conversations: ConversationMeta[]
    ) => void;
    pushUserMessage: (text: string) => string;
    startAssistantMessage: () => string;
    appendAssistantDelta: (messageId: string, delta: string, conversationId?: string | null) => void;
    appendAssistantPreview: (messageId: string, preview: PreviewTrace) => void;
    appendAssistantReasoning: (messageId: string, reasoning: ReasoningTrace) => void;
    setAssistantStageProgress: (messageId: string, stage: StageProgress | null) => void;
    finishAssistantMessage: (
        messageId: string,
        conversationId?: string | null,
        upstreamConversationId?: string | null,
        finalAnswer?: string
    ) => void;
    failAssistantMessage: (messageId: string, code: string, reason: string) => void;
    interruptAssistantMessage: (messageId: string) => void;
    attachDiffToAssistantMessage: (messageId: string, attachment: DiffAttachment) => void;
    updateUserMessageText: (messageId: string, text: string) => void;
    removeMessagesAfter: (messageId: string) => void;
    rewriteTailFromUserMessage: (messageId: string, text: string) => void;
    setDraftActionPending: (pending: DraftActionPending) => void;
    setUiNotice: (notice: UiNotice) => void;
    clearUiNotice: () => void;
    setReviewReadyNotice: (notice: ReviewReadyNotice | null) => void;
    clearReviewReadyNotice: () => void;
    setUiLanguage: (language: UiLanguage) => void;
    setWorkbenchMode: (mode: WorkbenchMode) => void;
    setGitStatus: (status: GitStatusSummary | null) => void;
    setGitBranches: (branches: GitBranchRow[]) => void;
    setGitHistoryCommits: (commits: GitHistoryCommit[]) => void;
    setGitWorkingTree: (entries: GitWorkingTreeEntry[]) => void;
    setGitCommitFiles: (files: GitCommitFile[]) => void;
    setGitLoading: (loading: boolean) => void;
    setGitActionPending: (pending: boolean) => void;
    setGitError: (error: string | null) => void;
    setSelectedGitCommit: (commitId: string | null) => void;
    setSelectedGitPath: (path: string | null) => void;
    setGitCenterMode: (mode: GitCenterMode) => void;
    setGitDiffPayload: (payload: GitDiffPayload | null) => void;
    setGitFilePayload: (payload: GitFilePayload | null) => void;
    setGitDiffFullscreen: (open: boolean) => void;
    resetGitConsole: () => void;
    flushAllStore: () => void;
    markDraftResolved: (resolution: DraftResolution) => void;
    clearChat: () => void;
    resetSandbox: () => void;
}

export type AppStore = CoreSessionState & StoreActions;
