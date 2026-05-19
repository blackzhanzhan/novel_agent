import { WorkbenchActionItem, WorkbenchActionRunState } from '../components/WorkbenchActionDock';
import { RollingWorkbenchState } from '../api/orchestration';
import { FileType, FsmState, WorkbenchMode } from '../types/store';

export interface WorkbenchActionContext {
    activeFile: string;
    activeFileType: FileType;
    fsmState: FsmState;
    workbenchMode: WorkbenchMode;
    repoNeedsRepair: boolean;
    hasReviewWorkspace: boolean;
    worldInitRunState: WorkbenchActionRunState;
    worldInitProgress: {
        current: number;
        total: number;
        label?: string;
        lines: string[];
    };
    styleInitRunState: WorkbenchActionRunState;
    styleInitProgress: {
        current: number;
        total: number;
        label?: string;
        lines: string[];
    };
    rollingRunState: WorkbenchActionRunState;
    rollingState: RollingWorkbenchState | null;
    rollingProgress: {
        current: number;
        total: number;
        label?: string;
        lines: string[];
    };
    postConfirmRunState: WorkbenchActionRunState;
    postConfirmProgress: {
        current: number;
        total: number;
        label?: string;
        lines: string[];
    };
    hasPostConfirmPayload: boolean;
}

export interface WorkbenchActionHandlers {
    onRunWorldInit: (options?: { forceRebuild?: boolean }) => void;
    onRunStyleInit: (options?: { forceRebuild?: boolean }) => void;
    onRefreshRollingState: () => void;
    onRunRollingContinuation: () => void;
    onOpenRuntimeConfig: () => void;
    onRunPostConfirmHandoff: () => void;
}

function formatChapterList(values: number[], empty = '无'): string {
    if (!values.length) return empty;
    return values.join(', ');
}

function rollingNextActionLabel(nextAction?: string): string {
    if (nextAction === 'continue_existing_cards') return '可以写正文';
    if (nextAction === 'replenish_outline') return '需要补充逐章大纲';
    if (nextAction === 'await_human_review') return '等待作者审查';
    if (nextAction === 'repair_outline_cards') return '需要修复章节卡';
    if (nextAction === 'await_quality_gate') return '等待质量闸门处理';
    return nextAction || '等待刷新';
}

function formatCardState(card: RollingWorkbenchState['outline_card_states'][number]): string {
    const prefix = card.number ? `CH${card.number}` : 'CH?';
    const title = card.title || '未命名';
    if (card.status === 'selected') return `${prefix}《${title}》：本轮`;
    if (card.status === 'pending') return `${prefix}《${title}》：待写`;
    if (card.status === 'written') return `${prefix}《${title}》：已写`;
    if (card.status === 'blocked') {
        const missing = card.missing_fields.length ? `，缺 ${card.missing_fields.join(', ')}` : '';
        return `${prefix}《${title}》：需修复${missing}`;
    }
    return `${prefix}《${title}》：未入队`;
}

function rollingCardGuidance(rollingState: RollingWorkbenchState): string[] {
    const selected = rollingState.outline_card_states.filter((card) => card.status === 'selected');
    const blocked = rollingState.outline_card_states.filter((card) => card.status === 'blocked');
    const pending = rollingState.outline_card_states.filter((card) => card.status === 'pending');
    const visibleCards = [
        ...selected,
        ...blocked,
        ...pending.slice(0, Math.max(0, 3 - selected.length - blocked.length)),
    ].slice(0, 5);
    if (visibleCards.length > 0) return visibleCards.map(formatCardState);
    if (rollingState.outline_diagnostics?.detected_but_unparsed) {
        return [rollingState.outline_diagnostics.message || '逐章大纲有内容，但没有识别到章节卡。'];
    }
    return ['暂无可显示的章节卡状态。'];
}

export function buildWorkbenchActions(
    context: WorkbenchActionContext,
    handlers: WorkbenchActionHandlers,
): WorkbenchActionItem[] {
    const worldActionAvailable = context.activeFile === 'world_model.md'
        || context.activeFile === 'status_card.md'
        || context.activeFile === 'domain_rules.md'
        || context.activeFileType === 'world_core';
    const worldInitRunnable = worldActionAvailable
        && !context.repoNeedsRepair
        && context.fsmState !== 'THINKING';

    const styleActionAvailable = context.activeFile === 'style_guide.md'
        || context.activeFile === 'style_fingerprint.md'
        || context.activeFile === 'style_review.md'
        || context.activeFile === 'style_constraints_for_continuation.md'
        || context.activeFileType === 'style';
    const styleInitRunnable = styleActionAvailable
        && !context.repoNeedsRepair
        && context.fsmState !== 'THINKING';

    const rollingActionAvailable = true;
    const rollingRunnable = rollingActionAvailable
        && !context.repoNeedsRepair
        && context.fsmState !== 'THINKING';
    const rollingState = context.rollingState;
    const rollingCanContinue = rollingRunnable
        && rollingState?.next_action === 'continue_existing_cards'
        && rollingState.selected_card_numbers.length > 0;
    const rollingDescription = rollingState
        ? `状态：${rollingNextActionLabel(rollingState.next_action)}；卡 ${rollingState.outline_diagnostics.outline_card_count}/${rollingState.outline_diagnostics.executable_card_count} 可写；本轮 ${formatChapterList(rollingState.selected_card_numbers)}。`
        : rollingActionAvailable
            ? '读取逐章大纲与续写草稿，显示已写章节、章节卡状态和下一批默认三章。'
            : '查看滚动三章队列。';
    const rollingGuidance = rollingState
        ? [
            `已写章节：${formatChapterList(rollingState.written_chapter_numbers)}`,
            `待写章节卡：${formatChapterList(rollingState.pending_card_numbers)}`,
            `本轮选中：${formatChapterList(rollingState.selected_card_numbers)}`,
            ...rollingCardGuidance(rollingState),
            rollingState.next_action === 'replenish_outline'
                ? '当前章节卡已消耗完，需要先让大纲 Agent 补充新的逐章大纲。'
                : '这只是队列投影，不会删除或清空 chapter_outline.md。',
        ]
        : [
            '先刷新队列：系统只读 chapter_outline.md 与 chapter_draft.md，不会生成正文。',
        ];
    const postConfirmRunnable = context.hasPostConfirmPayload
        && !context.repoNeedsRepair
        && context.fsmState !== 'THINKING'
        && context.postConfirmRunState !== 'running';

    return [
        {
            id: 'runtime-config',
            label: '本机配置中心',
            description: '配置 Dify App API key、Dify 地址、DeepSeek key 和本地批处理模型。保存后后端会热刷新，下一次 Agent 调用立即生效。',
            guidance: [
                '这是工作台控制面，不是聊天消息；密钥不会进入对话记录或书库文件。',
                '如果 Dify 调用失败、思考模式或 Agent key 不对，先来这里检查本机配置是否齐全。',
            ],
            executionKind: 'external_panel',
            requiresPrompt: false,
            status: 'available',
            meta: '/api/runtime/config',
            controls: [
                {
                    id: 'open',
                    label: '打开配置',
                    description: '打开本机配置中心，读取脱敏状态并保存本机 API 配置。',
                    tone: 'primary',
                    onRun: handlers.onOpenRuntimeConfig,
                },
            ],
        },
        {
            id: 'world-init',
            label: '初始化/重建世界模型',
            description: worldActionAvailable
                ? '后端 batch pipeline 生成 world_model.md 与 status_card.md；世界观助手保留为初始化后的讨论、解释与局部修订入口。'
                : '切到 world_model.md、status_card.md 或 domain_rules.md 后执行世界模型初始化。',
            guidance: worldActionAvailable
                ? [
                    '首次建档、完整重跑、轮回/阶段切换后的全量刷新：用这里的按钮。',
                    '读取已有设定、解释冲突、联网考据、按作者讨论微调：找世界观助手。',
                    'READ AGENT 保留深读修订；ONLINE_AGENT 保留现实考据与在线补证。',
                ]
                : [
                    '世界观初始化是无提示词后台任务，切到世界观相关文件后会启用。',
                ],
            executionKind: 'direct_job',
            requiresPrompt: false,
            status: worldInitRunnable ? 'available' : 'disabled',
            runState: context.worldInitRunState,
            progress: {
                mode: 'bar',
                current: context.worldInitProgress.current,
                total: context.worldInitProgress.total,
                label: context.worldInitProgress.label,
                lines: context.worldInitProgress.lines,
            },
            meta: '/api/world/init_batch_pipeline',
            controls: [
                {
                    id: 'check-or-fill',
                    label: '补齐/检查',
                    description: '已完成时只检查并补齐缺失状态卡，不强制重跑提取。',
                    tone: 'secondary',
                    disabled: !worldInitRunnable || context.worldInitRunState === 'running',
                    onRun: worldInitRunnable ? () => handlers.onRunWorldInit({ forceRebuild: false }) : undefined,
                },
                {
                    id: 'force-rerun',
                    label: '完整重跑',
                    description: '绕过已完成检测，重新执行世界模型提取与校验管线。',
                    tone: 'primary',
                    disabled: !worldInitRunnable || context.worldInitRunState === 'running',
                    onRun: worldInitRunnable ? () => handlers.onRunWorldInit({ forceRebuild: true }) : undefined,
                },
            ],
        },
        {
            id: 'style-init',
            label: '初始化/重建文风档案',
            description: styleActionAvailable
                ? '后端 diagnostics pipeline 生成文风三件套；文风助手负责根据作者讨论完善文风档案，不再承担初始化入口。'
                : '切到 style_fingerprint.md、style_review.md 或 style_constraints_for_continuation.md 后执行文风初始化。',
            guidance: styleActionAvailable
                ? [
                    '首次生成或整体重跑三件套：用这里的按钮。',
                    '作者觉得某条文风判断不准、要补充偏好或改写提示：找文风助手讨论后局部修订。',
                ]
                : [
                    '文风初始化是无提示词后台任务，切到文风相关文件后会启用。',
                ],
            executionKind: 'direct_job',
            requiresPrompt: false,
            status: styleInitRunnable ? 'available' : 'disabled',
            runState: context.styleInitRunState,
            progress: {
                mode: 'bar',
                current: context.styleInitProgress.current,
                total: context.styleInitProgress.total,
                label: context.styleInitProgress.label,
                lines: context.styleInitProgress.lines,
            },
            meta: '/api/style/init_pipeline',
            controls: [
                {
                    id: 'check-or-fill',
                    label: '补齐/检查',
                    description: '仅在三件套缺失或仍是模板时生成；已有成品则跳过。',
                    tone: 'secondary',
                    disabled: !styleInitRunnable || context.styleInitRunState === 'running',
                    onRun: styleInitRunnable ? () => handlers.onRunStyleInit({ forceRebuild: false }) : undefined,
                },
                {
                    id: 'force-rerun',
                    label: '完整重跑',
                    description: '重新生成 style_fingerprint.md、style_review.md、style_constraints_for_continuation.md。',
                    tone: 'primary',
                    disabled: !styleInitRunnable || context.styleInitRunState === 'running',
                    onRun: styleInitRunnable ? () => handlers.onRunStyleInit({ forceRebuild: true }) : undefined,
                },
            ],
        },
        {
            id: 'repo-repair',
            label: '修复仓库布局',
            description: context.repoNeedsRepair ? '当前仓库需要显式修复。' : '仓库布局正常，无需执行。',
            executionKind: 'external_panel',
            requiresPrompt: false,
            status: context.repoNeedsRepair ? 'external_panel' : 'disabled',
            meta: context.repoNeedsRepair ? '左栏与中心保护态已有修复入口' : undefined,
        },
        ...(context.hasPostConfirmPayload ? [{
            id: 'post-confirm-handoff',
            label: '正文归档接棒',
            description: '续写草稿已归入 chapters 正文归档；这里负责刷新 status_card.md，并按需生成 world_model.md/domain_rules.md 审阅草稿。',
            guidance: [
                '这一步不改写正文，只让世界观路由读取正式章节后更新创作状态。',
                '如果自动接棒失败或被打断，可以从这里重试同一个接棒任务。',
            ],
            executionKind: 'direct_job' as const,
            requiresPrompt: false,
            status: postConfirmRunnable ? 'available' as const : 'disabled' as const,
            runState: context.postConfirmRunState,
            progress: {
                mode: 'bar' as const,
                current: context.postConfirmProgress.current,
                total: context.postConfirmProgress.total,
                label: context.postConfirmProgress.label,
                lines: context.postConfirmProgress.lines,
            },
            meta: 'post_confirm_world_distill',
            controls: [
                {
                    id: 'retry',
                    label: context.postConfirmRunState === 'error' ? '重试接棒' : '运行接棒',
                    description: '调用 world_model 路由刷新状态卡，并按需更新世界模型/领域规则。',
                    tone: 'primary' as const,
                    disabled: !postConfirmRunnable,
                    onRun: postConfirmRunnable ? handlers.onRunPostConfirmHandoff : undefined,
                },
            ],
        }] : []),
        {
            id: 'rolling-three',
            label: '滚动三章生产',
            description: rollingDescription,
            guidance: rollingGuidance,
            executionKind: 'direct_job',
            requiresPrompt: false,
            status: rollingRunnable ? 'available' : 'disabled',
            runState: context.rollingRunState,
            progress: {
                mode: 'bar',
                current: context.rollingProgress.current,
                total: context.rollingProgress.total,
                label: context.rollingProgress.label,
                lines: context.rollingProgress.lines,
            },
            meta: '/api/rolling/state',
            controls: [
                {
                    id: 'start',
                    label: '开始写正文',
                    description: '读取当前滚动队列并调用 continuation Agent 写入 chapter_draft.md，完成后进入审阅工作台。',
                    tone: 'primary',
                    disabled: !rollingCanContinue || context.rollingRunState === 'running',
                    onRun: rollingCanContinue ? handlers.onRunRollingContinuation : undefined,
                },
                {
                    id: 'refresh',
                    label: '刷新队列',
                    description: '只读取逐章大纲与续写草稿，更新滚动三章队列状态。',
                    tone: 'secondary',
                    disabled: !rollingRunnable || context.rollingRunState === 'running',
                    onRun: rollingRunnable ? handlers.onRefreshRollingState : undefined,
                },
            ],
        },
    ];
}
