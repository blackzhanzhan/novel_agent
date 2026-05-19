import { useMemo } from 'react';
import { useAppStore } from '../store';
import { AgentKey, FileType, FsmState, UiLanguage, WorkbenchMode } from '../types/store';

type UiCopy = {
    common: {
        close: string;
        later: string;
        pending: string;
        cancel: string;
    };
    language: {
        label: string;
        zhShort: string;
        enShort: string;
        zhFull: string;
        enFull: string;
    };
    workbench: {
        section: string;
        mode: string;
        workspace: string;
        reviewWorkspace: string;
        versionControl: string;
        projectFiles: string;
        reviewFiles: string;
        gitConsole: string;
        repository: string;
        draftReview: string;
        editor: string;
        review: string;
        git: string;
        noBookSelected: string;
        quickOpen: string;
        reviewState: string;
        editorRail: string;
        gitRail: string;
    };
    conversation: {
        section: string;
        newThread: string;
        noCurrentThread: string;
        searchHistory: string;
        noMatchedHistory: string;
        untitledThread: string;
        messages: (count: number) => string;
        rename: string;
        archive: string;
        remove: string;
    };
    composer: {
        stop: string;
        send: string;
        resend: string;
        placeholderIdle: string;
        placeholderStreaming: string;
        placeholderRewrite: string;
        rewriteNotice: string;
        cancelRewrite: string;
    };
    chat: {
        currentNode: string;
        recentNode: string;
        thinkingNow: string;
        recentThought: string;
        previewNow: string;
        recentPreview: string;
        thinking: string;
        draftReady: string;
        interrupted: string;
        confirmed: string;
        rolledBack: string;
        edit: string;
        editDraftLabel: string;
    };
    explorer: {
        treeAriaLabel: string;
        virtualBadge: string;
        filesSection: string;
    };
    outline: {
        section: string;
        empty: string;
    };
    debug: {
        suppressedHeader: (count: number) => string;
        clear: string;
        hiddenPayloadTitle: string;
    };
    review: {
        canvas: string;
        lineSummary: (mainlineLines: number, draftLines: number) => string;
        draftCommit: string;
        diffReview: string;
        conflictReview: string;
        diff: string;
        draft: string;
        mainline: string;
        singleColumn: string;
        splitColumn: string;
        readingView: string;
        inspector: string;
        currentDraft: string;
        workspaceReady: string;
        workspaceHint: string;
        changeScale: string;
        mainlineLines: string;
        draftLines: string;
        conflictHandling: string;
        conflictHint: string;
        refreshLock: string;
        confirm: string;
        rollback: string;
        backToEditor: string;
        diffSummary: string;
    };
    editor: {
        mainlineContent: (fileName: string) => string;
        etag: string;
        editorEntryBottom: string;
        editing: string;
        bottomEditor: (fileName: string) => string;
        collapseEditor: string;
        saveAndCollapse: string;
        saving: string;
        humanEdit: string;
        editMainline: string;
        editHint: string;
        expandEditor: string;
    };
    git: {
        console: string;
        branches: string;
        branchCount: (count: number) => string;
        branchFlow: string;
        plotBranchStatus: string;
        plotProgressSummary: (count: number, latestTitle: string) => string;
        plotProgressUnavailable: string;
        plotProgressHint: string;
        plotBranchPlaceholder: string;
        refresh: string;
        currentBranch: string;
        mainlineBranch: string;
        workingTree: string;
        clean: string;
        dirty: string;
        current: string;
        emptyCommitMessage: string;
        switchSection: string;
        switchToSelected: string;
        backToMainline: (branch: string) => string;
        mergeBranch: string;
        chooseMergeSource: string;
        mergeNoFf: string;
        mergeIntoCurrent: string;
        mergeConflictTitle: string;
        createBranch: string;
        fromCommitPlaceholder: string;
        createAndSwitch: string;
        hardRollback: string;
        selectCommitHint: string;
        hardRollbackAndPrune: string;
        rollbackCurrentOnlyHint: string;
        historyStream: string;
        loadingTimeline: string;
        loadingTimelineHint: string;
        historyUnavailable: string;
        timelineUnavailable: string;
        backendRetryHint: string;
        history: string;
        commitTimeline: string;
        timelineEmpty: string;
        noCommitRecords: string;
        waitingInspector: string;
        selectCommit: string;
        selectCommitHintBody: string;
        changedFiles: string;
        noFiles: string;
        diffPreview: string;
        loadingDiff: string;
        fullscreen: string;
        stageAll: string;
        stagedLabel: string;
        unstagedLabel: string;
        noLocalChanges: string;
        noLocalChangesHint: string;
        source: string;
        unstage: string;
        stage: string;
        commitToCurrent: string;
        commitPlaceholder: string;
        commitStagedFiles: string;
        loadingMainline: string;
        diffIdle: string;
        noActiveDiff: string;
        noActiveDiffHint: string;
    };
    reviewReadyNotice: {
        section: string;
        readyMessage: (fileName: string) => string;
        previewSummary: string;
        previewFallback: string;
        enterReview: string;
    };
    agent: Record<AgentKey, string>;
    fileType: Record<FileType, string>;
    fsmState: Record<FsmState, string>;
};

const uiCopyByLanguage: Record<UiLanguage, UiCopy> = {
    'zh-CN': {
        common: {
            close: '关闭',
            later: '稍后处理',
            pending: '待生成',
            cancel: '取消',
        },
        language: {
            label: '语言',
            zhShort: '中',
            enShort: 'EN',
            zhFull: '中文',
            enFull: 'English',
        },
        workbench: {
            section: '工作台',
            mode: '模式',
            workspace: '工作区',
            reviewWorkspace: '审阅工作台',
            versionControl: '版本控制',
            projectFiles: '项目文件',
            reviewFiles: '审阅文件',
            gitConsole: '版本控制台',
            repository: '版本库',
            draftReview: '草稿审阅',
            editor: '编辑',
            review: '审阅',
            git: '版本',
            noBookSelected: '未选择书籍',
            quickOpen: '快速打开（⌘K）',
            reviewState: '审阅中',
            editorRail: '编辑',
            gitRail: '版本',
        },
        conversation: {
            section: '会话',
            newThread: '新建会话',
            noCurrentThread: '当前暂无会话',
            searchHistory: '搜索历史会话',
            noMatchedHistory: '没有匹配的历史会话。',
            untitledThread: '未命名会话',
            messages: (count) => `${count} 条`,
            rename: '改名',
            archive: '归档',
            remove: '删除',
        },
        composer: {
            stop: '停止',
            send: '发送',
            resend: '重发',
            placeholderIdle: '输入你的指令…',
            placeholderStreaming: '输出进行中，可停止后修改最后一问…',
            placeholderRewrite: '修改最后一问后重新发送…',
            rewriteNotice: '正在重写当前线程的最后一问：前文保留，本轮尾部会被替换。',
            cancelRewrite: '取消修改最后一问',
        },
        chat: {
            currentNode: '当前节点',
            recentNode: '最近节点',
            thinkingNow: '思考中',
            recentThought: '最近思考',
            previewNow: '中间预览',
            recentPreview: '最近预览',
            thinking: '思考',
            draftReady: '已生成草稿，审阅工作台已就绪',
            interrupted: '已中止，可修改最后一问后重发',
            confirmed: '已确权',
            rolledBack: '已回滚',
            edit: '编辑',
            editDraftLabel: '正在编辑这条消息',
        },
        explorer: {
            treeAriaLabel: '文件树',
            virtualBadge: '虚拟',
            filesSection: '项目',
        },
        outline: {
            section: '大纲',
            empty: '当前文档还没有可导航的标题结构。',
        },
        debug: {
            suppressedHeader: (count) => `Debug 日志（已静默错误 ${count} 条）`,
            clear: '清空',
            hiddenPayloadTitle: '兼容载荷格式错误',
        },
        review: {
            canvas: '审阅画布',
            lineSummary: (mainlineLines, draftLines) => `主线 ${mainlineLines} 行 · 草稿 ${draftLines} 行`,
            draftCommit: '草稿提交',
            diffReview: '差异审阅',
            conflictReview: '冲突审阅',
            diff: '差异',
            draft: '草稿',
            mainline: '主线',
            singleColumn: '单栏',
            splitColumn: '双栏',
            readingView: '阅读视图',
            inspector: '审阅检查器',
            currentDraft: '当前草稿',
            workspaceReady: '主线与草稿差异已经进入独立审阅工作台。',
            workspaceHint: '中栏负责差异画布，右栏负责上下文、风险与动作。',
            changeScale: '变化规模',
            mainlineLines: '主线行数',
            draftLines: '草稿行数',
            conflictHandling: '冲突处理',
            conflictHint: '当前草稿确权失败，请先刷新锁或直接回滚。',
            refreshLock: '刷新锁并回到主线',
            confirm: '批准确权',
            rollback: '湮灭回滚',
            backToEditor: '回到编辑面',
            diffSummary: '差异摘要',
        },
        editor: {
            mainlineContent: (fileName) => `主线内容 [${fileName}]`,
            etag: 'ETAG',
            editorEntryBottom: '编辑入口在底部',
            editing: '正在编辑',
            bottomEditor: (fileName) => `底部编辑栏 [${fileName}]`,
            collapseEditor: '收起编辑栏',
            saveAndCollapse: '保存并收起',
            saving: '保存中…',
            humanEdit: '人工编辑',
            editMainline: '直接修改主线文件内容',
            editHint: '编辑栏将在底部展开，保存后自动回到阅览模式',
            expandEditor: '展开编辑栏',
        },
        git: {
            console: '剧情分支台',
            branches: '剧情分支',
            branchCount: (count) => `${count} 条剧情线`,
            branchFlow: '剧情线流向',
            plotBranchStatus: '当前剧情线',
            plotProgressSummary: (count, latestTitle) => `已推进 ${count} 章${latestTitle ? ` · 最近：${latestTitle}` : ''}`,
            plotProgressUnavailable: '当前剧情线尚未定位到续写章节',
            plotProgressHint: '这里显示已推进到哪里，不预设作者必须写到多少章。',
            plotBranchPlaceholder: 'plot/if-hero-refuses',
            refresh: '刷新',
            currentBranch: '当前剧情分支',
            mainlineBranch: '主剧情线',
            workingTree: '未入库改动',
            clean: '干净',
            dirty: '有变更',
            current: '当前',
            emptyCommitMessage: '（空提交信息）',
            switchSection: '切换剧情线',
            switchToSelected: '切到选中剧情分支',
            backToMainline: (branch) => `回到主剧情线 (${branch || '...'})`,
            mergeBranch: '合并剧情分支',
            chooseMergeSource: '— 选择要合入的剧情分支 —',
            mergeNoFf: '保留独立合并节点',
            mergeIntoCurrent: '合入当前剧情线',
            mergeConflictTitle: '合并冲突，已自动中止',
            createBranch: '新开剧情试写',
            fromCommitPlaceholder: '从哪个剧情节点开始（默认选中节点）',
            createAndSwitch: '+ 新建并切换剧情分支',
            hardRollback: '回退当前剧情线',
            selectCommitHint: '请先在中栏选择目标剧情节点',
            hardRollbackAndPrune: '只回退当前剧情线',
            rollbackCurrentOnlyHint: '会把当前剧情分支退回选中节点，其他剧情分支会保留。',
            historyStream: '剧情节点流',
            loadingTimeline: '正在加载提交时间线…',
            loadingTimelineHint: '正在读取剧情分支与节点历史，稍后这里会显示可回看的剧情时间线。',
            historyUnavailable: '历史流不可用',
            timelineUnavailable: '剧情节点时间线暂时不可用。',
            backendRetryHint: '后端恢复后，可在左栏重新刷新。',
            history: '历史',
            commitTimeline: '剧情节点时间线',
            timelineEmpty: '时间线为空',
            noCommitRecords: '当前还没有剧情节点。',
            waitingInspector: '剧情节点检查器',
            selectCommit: '先在中栏选择一个剧情节点。',
            selectCommitHintBody: '选中后，这里会展示节点说明、变更文件和差异预览。',
            changedFiles: '变更文件',
            noFiles: '该剧情节点暂无可展示文件',
            diffPreview: '剧情差异预览',
            loadingDiff: '正在加载该剧情节点差异...',
            fullscreen: '全屏',
            stageAll: '全部暂存',
            stagedLabel: '已暂存',
            unstagedLabel: '未暂存',
            noLocalChanges: '当前剧情线没有未入库改动',
            noLocalChangesHint: '没有待确认入库的本地变更。',
            source: '来源',
            unstage: '取消暂存',
            stage: '暂存',
            commitToCurrent: '保存为当前剧情节点',
            commitPlaceholder: '写一句这个剧情节点发生了什么',
            commitStagedFiles: '保存剧情节点',
            loadingMainline: '正在加载主线内容…',
            diffIdle: '差异闲置',
            noActiveDiff: '当前没有活跃差异。',
            noActiveDiffHint: '等待新的草稿变更进入这里。',
        },
        reviewReadyNotice: {
            section: '草稿已就绪',
            readyMessage: (fileName) => `${fileName} 已生成新的草稿变更`,
            previewSummary: '预览摘要',
            previewFallback: '本次草稿已生成，但尚未提取到可展示的差异摘要。',
            enterReview: '进入审阅',
        },
        agent: {
            world_agent: '设定助手',
            outline_agent: '大纲助手',
            style_agent: '文风助手',
            continuation_agent: '续写助手',
            review_agent: '审核助手',
        },
        fileType: {
            world_core: '世界设定',
            summary: '摘要',
            outline: '大纲',
            style: '文风',
            chapter: '章节',
            error_archive: '错误档案',
        },
        fsmState: {
            IDLE: '空闲',
            THINKING: '处理中',
            REVIEW: '审阅中',
            CONFLICT: '冲突',
        },
    },
    'en-US': {
        common: {
            close: 'Close',
            later: 'Later',
            pending: 'pending',
            cancel: 'Cancel',
        },
        language: {
            label: 'Language',
            zhShort: '中',
            enShort: 'EN',
            zhFull: 'Chinese',
            enFull: 'English',
        },
        workbench: {
            section: 'Workspace',
            mode: 'Mode',
            workspace: 'Workspace',
            reviewWorkspace: 'Review Workspace',
            versionControl: 'Version Control',
            projectFiles: 'Project Files',
            reviewFiles: 'Review Files',
            gitConsole: 'Git Console',
            repository: 'Repository',
            draftReview: 'Draft Review',
            editor: 'Editor',
            review: 'Review',
            git: 'Git',
            noBookSelected: 'No book selected',
            quickOpen: 'Quick open (⌘K)',
            reviewState: 'Reviewing',
            editorRail: 'Editor',
            gitRail: 'Git',
        },
        conversation: {
            section: 'Thread',
            newThread: 'New thread',
            noCurrentThread: 'No current thread',
            searchHistory: 'Search thread history',
            noMatchedHistory: 'No threads match this search.',
            untitledThread: 'Untitled thread',
            messages: (count) => `${count} msgs`,
            rename: 'Rename',
            archive: 'Archive',
            remove: 'Delete',
        },
        composer: {
            stop: 'Stop',
            send: 'Send',
            resend: 'Resend',
            placeholderIdle: 'Ask anything…',
            placeholderStreaming: 'Still streaming. Stop to rewrite the last turn…',
            placeholderRewrite: 'Rewrite the last turn and send again…',
            rewriteNotice: 'Rewriting the latest user turn. Earlier context stays; only the tail will be replaced.',
            cancelRewrite: 'Cancel rewrite',
        },
        chat: {
            currentNode: 'Current node',
            recentNode: 'Recent node',
            thinkingNow: 'Thinking',
            recentThought: 'Recent thought',
            previewNow: 'Previewing',
            recentPreview: 'Recent preview',
            thinking: 'Thinking',
            draftReady: 'Draft ready. Review workspace is standing by.',
            interrupted: 'Stopped. You can rewrite the last turn and resend.',
            confirmed: 'Confirmed',
            rolledBack: 'Rolled back',
            edit: 'Edit',
            editDraftLabel: 'Editing this message',
        },
        explorer: {
            treeAriaLabel: 'File tree',
            virtualBadge: 'Virtual',
            filesSection: 'Files',
        },
        outline: {
            section: 'Outline',
            empty: 'No navigable headings were found in the current document.',
        },
        debug: {
            suppressedHeader: (count) => `Debug log (${count} suppressed)`,
            clear: 'Clear',
            hiddenPayloadTitle: 'Malformed compatibility payload',
        },
        review: {
            canvas: 'Review Canvas',
            lineSummary: (mainlineLines, draftLines) => `Mainline ${mainlineLines} lines · Draft ${draftLines} lines`,
            draftCommit: 'Draft commit',
            diffReview: 'Diff Review',
            conflictReview: 'Conflict Review',
            diff: 'Diff',
            draft: 'Draft',
            mainline: 'Mainline',
            singleColumn: 'Single',
            splitColumn: 'Split',
            readingView: 'Reading view',
            inspector: 'Review Inspector',
            currentDraft: 'Current Draft',
            workspaceReady: 'The mainline and draft diff has moved into the dedicated review workspace.',
            workspaceHint: 'The center owns the canvas. The right rail owns context, risk, and actions.',
            changeScale: 'Change Scale',
            mainlineLines: 'Mainline lines',
            draftLines: 'Draft lines',
            conflictHandling: 'Conflict Handling',
            conflictHint: 'Draft confirmation failed. Refresh the lock or roll the draft back.',
            refreshLock: 'Refresh lock and return',
            confirm: 'Confirm draft',
            rollback: 'Roll back draft',
            backToEditor: 'Back to editor',
            diffSummary: 'Diff Summary',
        },
        editor: {
            mainlineContent: (fileName) => `Mainline [${fileName}]`,
            etag: 'ETAG',
            editorEntryBottom: 'Composer lives at the bottom',
            editing: 'Editing',
            bottomEditor: (fileName) => `Bottom editor [${fileName}]`,
            collapseEditor: 'Collapse editor',
            saveAndCollapse: 'Save and collapse',
            saving: 'Saving…',
            humanEdit: 'Manual Edit',
            editMainline: 'Edit the mainline file directly',
            editHint: 'The editor opens from the bottom and returns to reading mode after save.',
            expandEditor: 'Open editor',
        },
        git: {
            console: 'Plot Branch Console',
            branches: 'Plot Branches',
            branchCount: (count) => `${count} plot lines`,
            branchFlow: 'Plot branch flow',
            plotBranchStatus: 'Current plot line',
            plotProgressSummary: (count, latestTitle) => `Advanced ${count} chapters${latestTitle ? ` · latest: ${latestTitle}` : ''}`,
            plotProgressUnavailable: 'No continuation chapters found on this line yet',
            plotProgressHint: 'Progress is descriptive. The app does not set a fixed chapter target for the author.',
            plotBranchPlaceholder: 'plot/if-hero-refuses',
            refresh: 'Refresh',
            currentBranch: 'Current plot branch',
            mainlineBranch: 'Main plot line',
            workingTree: 'Uncommitted changes',
            clean: 'Clean',
            dirty: 'Dirty',
            current: 'Current',
            emptyCommitMessage: '(empty commit message)',
            switchSection: 'Switch plot line',
            switchToSelected: 'Switch to selected plot branch',
            backToMainline: (branch) => `Return to main plot line (${branch || '...'})`,
            mergeBranch: 'Merge Plot Branch',
            chooseMergeSource: '— Choose plot branch to merge —',
            mergeNoFf: 'Keep a merge node',
            mergeIntoCurrent: 'Merge into current plot line',
            mergeConflictTitle: 'Merge conflict, auto-aborted',
            createBranch: 'Open Plot Trial',
            fromCommitPlaceholder: 'start from plot node (defaults to selected node)',
            createAndSwitch: '+ Create and switch plot branch',
            hardRollback: 'Rollback current plot line',
            selectCommitHint: 'Select a target plot node from the center panel first',
            hardRollbackAndPrune: 'Rollback current plot line only',
            rollbackCurrentOnlyHint: 'Moves only the current plot branch back to the selected node. Other plot branches are preserved.',
            historyStream: 'Plot Node Stream',
            loadingTimeline: 'Loading the plot timeline…',
            loadingTimelineHint: 'Reading plot branches and node history from the repo. This view will become a browsable plot timeline shortly.',
            historyUnavailable: 'History unavailable',
            timelineUnavailable: 'The plot timeline is temporarily unavailable.',
            backendRetryHint: 'Refresh from the left rail after the backend recovers.',
            history: 'History',
            commitTimeline: 'Plot Node Timeline',
            timelineEmpty: 'Timeline is empty',
            noCommitRecords: 'There are no plot nodes yet.',
            waitingInspector: 'Plot Node Inspector',
            selectCommit: 'Select a plot node in the center rail first.',
            selectCommitHintBody: 'Once selected, this rail shows node details, changed files, and a diff preview.',
            changedFiles: 'Changed Files',
            noFiles: 'No files are available for this plot node.',
            diffPreview: 'Plot Diff Preview',
            loadingDiff: 'Loading the plot node diff…',
            fullscreen: 'Fullscreen',
            stageAll: 'Stage all',
            stagedLabel: 'staged',
            unstagedLabel: 'unstaged',
            noLocalChanges: 'Current plot line has no uncommitted changes',
            noLocalChangesHint: 'There are no local changes waiting to be saved as a plot node.',
            source: 'Source',
            unstage: 'Unstage',
            stage: 'Stage',
            commitToCurrent: 'Save to current plot line',
            commitPlaceholder: 'Describe what changed in this plot node',
            commitStagedFiles: 'Save plot node',
            loadingMainline: 'Loading mainline content…',
            diffIdle: 'Diff idle',
            noActiveDiff: 'No active diff yet.',
            noActiveDiffHint: 'Waiting for the next draft change to arrive here.',
        },
        reviewReadyNotice: {
            section: 'Draft Ready',
            readyMessage: (fileName) => `New draft changes are ready for ${fileName}`,
            previewSummary: 'Preview',
            previewFallback: 'The draft is ready, but no preview summary is available yet.',
            enterReview: 'Open Review',
        },
        agent: {
            world_agent: 'World Agent',
            outline_agent: 'Outline Agent',
            style_agent: 'Style Agent',
            continuation_agent: 'Continuation Agent',
            review_agent: 'Review Agent',
        },
        fileType: {
            world_core: 'World Core',
            summary: 'Summary',
            outline: 'Outline',
            style: 'Style',
            chapter: 'Chapter',
            error_archive: 'Error Archive',
        },
        fsmState: {
            IDLE: 'Idle',
            THINKING: 'Thinking',
            REVIEW: 'Reviewing',
            CONFLICT: 'Conflict',
        },
    },
};

export function getUiCopy(language: UiLanguage): UiCopy {
    return uiCopyByLanguage[language];
}

export function useUiLanguage(): UiLanguage {
    return useAppStore((state) => state.uiLanguage);
}

export function useUiCopy(): UiCopy {
    const uiLanguage = useUiLanguage();
    return useMemo(() => getUiCopy(uiLanguage), [uiLanguage]);
}

export function getAgentLabel(language: UiLanguage, agent: AgentKey): string {
    return uiCopyByLanguage[language].agent[agent];
}

export function getFileTypeLabel(language: UiLanguage, fileType: FileType): string {
    return uiCopyByLanguage[language].fileType[fileType];
}

export function getFsmStateLabel(language: UiLanguage, fsmState: FsmState): string {
    return uiCopyByLanguage[language].fsmState[fsmState];
}

export function getWorkbenchModeLabel(language: UiLanguage, mode: WorkbenchMode): string {
    if (mode === 'review') return uiCopyByLanguage[language].workbench.review;
    if (mode === 'git') return uiCopyByLanguage[language].workbench.git;
    return uiCopyByLanguage[language].workbench.editor;
}
