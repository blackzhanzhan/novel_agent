import React, { useEffect, useRef, useState } from 'react';
import { AssistantTimelineSegment, ChatMessage, DraftActionPending, FsmState } from '../types/store';
import { useUiCopy } from '../i18n/ui';
import { MarkdownRender } from './MarkdownRender';

interface ChatMessageBubbleProps {
    message: ChatMessage;
    fsmState: FsmState;
    onConfirmDraft: () => void;
    onRollbackDraft: () => void;
    isConfirmDisabled: boolean;
    draftActionPending: DraftActionPending;
    canEditUserMessage?: boolean;
    onRequestEditUserMessage?: (messageId: string, text: string) => void;
    isEditingUserMessage?: boolean;
    editDraftValue?: string;
    onEditDraftChange?: (next: string) => void;
    onSubmitEditUserMessage?: () => void;
    onCancelEditUserMessage?: () => void;
}

interface RollingSlotProps {
    slotKey: string;
    status: 'streaming' | 'done';
    eyebrow: string;
    title: string;
    body?: string;
    kind: 'reasoning' | 'stage' | 'preview';
    defaultOpen?: boolean;
}

function decodeDisplayEscapes(value: string): string {
    return value
        .replace(/\\u([0-9a-fA-F]{4})/g, (_, hex: string) => String.fromCharCode(parseInt(hex, 16)))
        .replace(/\\u[0-9a-fA-F]{0,3}$/g, '');
}

function normalizeTraceLabel(value?: string): string {
    return decodeDisplayEscapes(value || '').replace(/\s+/g, ' ').trim();
}

function normalizeTraceBody(value?: string): string {
    const text = decodeDisplayEscapes(value || '').replace(/\r\n/g, '\n').trim();
    if (!text || text === '/' || text === '...') return '';
    return text;
}

const areRollingSlotsEqual = (left: RollingSlotProps, right: RollingSlotProps) => (
    left.slotKey === right.slotKey &&
    left.status === right.status &&
    left.eyebrow === right.eyebrow &&
    left.title === right.title &&
    left.body === right.body &&
    left.kind === right.kind &&
    left.defaultOpen === right.defaultOpen
);

const RollingSlot: React.FC<RollingSlotProps> = ({
    slotKey,
    status,
    eyebrow,
    title,
    body,
    kind,
    defaultOpen = true,
}) => {
    const [open, setOpen] = useState(defaultOpen);
    const [phase, setPhase] = useState<'idle' | 'out' | 'in'>('idle');
    const bodyRef = useRef<HTMLDivElement | null>(null);
    const [current, setCurrent] = useState<RollingSlotProps>({
        slotKey,
        status,
        eyebrow,
        title,
        body,
        kind,
        defaultOpen,
    });
    const currentRef = useRef(current);
    const exitTimeoutRef = useRef<number | null>(null);
    const enterTimeoutRef = useRef<number | null>(null);
    const nextRef = useRef<RollingSlotProps | null>(null);

    useEffect(() => {
        currentRef.current = current;
    }, [current]);

    useEffect(() => {
        const node = bodyRef.current;
        if (!node || current.kind !== 'reasoning' || current.status !== 'streaming') return;
        node.scrollTop = node.scrollHeight;
    }, [current.body, current.kind, current.status]);

    useEffect(() => {
        const next = { slotKey, status, eyebrow, title, body, kind, defaultOpen };
        const currentSlot = currentRef.current;
        if (areRollingSlotsEqual(currentSlot, next)) return;
        const isSameSlotIdentity = currentSlot.slotKey === next.slotKey && currentSlot.kind === next.kind;
        if (isSameSlotIdentity) {
            setCurrent(next);
            currentRef.current = next;
            return;
        }
        nextRef.current = next;
        if (exitTimeoutRef.current) {
            window.clearTimeout(exitTimeoutRef.current);
            exitTimeoutRef.current = null;
        }
        if (enterTimeoutRef.current) {
            window.clearTimeout(enterTimeoutRef.current);
            enterTimeoutRef.current = null;
        }
        setOpen(true);
        setPhase('out');
        exitTimeoutRef.current = window.setTimeout(() => {
            const incoming = nextRef.current ?? next;
            setCurrent(incoming);
            currentRef.current = incoming;
            setPhase('in');
            enterTimeoutRef.current = window.setTimeout(() => {
                setPhase('idle');
                enterTimeoutRef.current = null;
            }, 180);
            exitTimeoutRef.current = null;
        }, 120);
        return () => {
            if (exitTimeoutRef.current) {
                window.clearTimeout(exitTimeoutRef.current);
                exitTimeoutRef.current = null;
            }
            if (enterTimeoutRef.current) {
                window.clearTimeout(enterTimeoutRef.current);
                enterTimeoutRef.current = null;
            }
        };
    }, [slotKey, status, eyebrow, title, body, kind, defaultOpen]);

    const isStreaming = current.status === 'streaming';
    const slotClassName = `rounded-[10px] border border-[rgba(255,255,255,0.045)] bg-[rgba(255,255,255,0.014)] px-3 py-2 text-[11px] text-[#c9d1d9] ${
        isStreaming && kind === 'reasoning' ? 'reasoning-shell' : ''
    } ${
        isStreaming && kind === 'stage' ? 'stage-shell' : ''
    } ${
        isStreaming && kind === 'preview' ? 'preview-shell' : ''
    }`;

    const renderHeader = (item: RollingSlotProps) => {
        const itemStreaming = item.status === 'streaming';
        const displayTitle = normalizeTraceLabel(item.title) || item.title;
        return (
            <button
                type="button"
                onClick={() => setOpen((value) => !value)}
                className="reasoning-summary w-full cursor-pointer select-none font-mono text-[#8b949e]"
            >
                {itemStreaming ? (
                    <span className={kind === 'reasoning' ? 'reasoning-dots' : kind === 'preview' ? 'preview-dots' : 'stage-dots'} aria-hidden="true">
                        <span className={kind === 'reasoning' ? 'reasoning-dot' : kind === 'preview' ? 'preview-dot' : 'stage-dot'} />
                        <span className={kind === 'reasoning' ? 'reasoning-dot' : kind === 'preview' ? 'preview-dot' : 'stage-dot'} />
                        <span className={kind === 'reasoning' ? 'reasoning-dot' : kind === 'preview' ? 'preview-dot' : 'stage-dot'} />
                    </span>
                ) : (
                    <span className="inline-flex h-2 w-2 rounded-full bg-[rgba(139,148,158,0.55)]" aria-hidden="true" />
                )}
                <span className="truncate">{item.eyebrow} · {displayTitle}</span>
                <span
                    aria-hidden="true"
                    className={`ml-auto text-[10px] transition-transform duration-200 ${open ? 'rotate-90' : 'rotate-0'}`}
                >
                    ›
                </span>
            </button>
        );
    };

    const renderBody = (item: RollingSlotProps) => {
        const displayBody = normalizeTraceBody(item.body);
        if (!displayBody) return null;
        const isReasoning = item.kind === 'reasoning';
        return (
            <div
                className={`transition-all duration-200 ease-out ${
                    open ? 'mt-2 opacity-100' : 'max-h-0 overflow-hidden opacity-0'
                }`}
            >
                <div
                    ref={isReasoning ? bodyRef : undefined}
                    className={`reasoning-body leading-5 text-[12px] text-[var(--color-dark-text-main)] ${
                        isReasoning ? 'reasoning-body-scroll app-scrollbar' : ''
                    }`}
                >
                    {isReasoning ? (
                        <MarkdownRender
                            content={displayBody}
                            className="reasoning-markdown"
                        />
                    ) : (
                        displayBody
                    )}
                </div>
            </div>
        );
    };

    return (
        <div className={`${slotClassName} relative overflow-hidden`}>
            <div className={phase === 'out' ? 'slot-roll-out' : phase === 'in' ? 'slot-roll-in' : ''}>
                {renderHeader(current)}
                {renderBody(current)}
            </div>
        </div>
    );
};

interface InlineThinkingBoxProps {
    segment: Extract<AssistantTimelineSegment, { kind: 'thinking' }>;
}

const InlineThinkingBox: React.FC<InlineThinkingBoxProps> = ({ segment }) => {
    const bodyRef = useRef<HTMLDivElement | null>(null);
    const isStreaming = segment.status === 'streaming';
    const [expanded, setExpanded] = useState(isStreaming);
    const displayLabel = normalizeTraceLabel(segment.label) || segment.label;
    const displayText = normalizeTraceBody(segment.text);
    const previewText = displayText.replace(/\s+/g, ' ').trim();

    useEffect(() => {
        const node = bodyRef.current;
        if (!node) return;
        node.scrollTop = node.scrollHeight;
    }, [segment.text]);

    useEffect(() => {
        if (isStreaming) {
            setExpanded(true);
        }
    }, [isStreaming]);

    return (
        <div
            className={`inline-thinking-box ${
                isStreaming ? 'inline-thinking-box-streaming' : 'inline-thinking-box-done'
            } ${expanded ? 'inline-thinking-box-expanded' : 'inline-thinking-box-collapsed'}`}
        >
            <button
                type="button"
                className="inline-thinking-header"
                onClick={() => setExpanded((value) => !value)}
            >
                <span className={isStreaming ? 'reasoning-dots' : 'inline-flex h-2 w-2 rounded-full bg-[rgba(139,148,158,0.55)]'} aria-hidden="true">
                    {isStreaming ? (
                        <>
                            <span className="reasoning-dot" />
                            <span className="reasoning-dot" />
                            <span className="reasoning-dot" />
                        </>
                    ) : null}
                </span>
                <span className="min-w-0 shrink-0 truncate">{isStreaming ? '思考中' : '思考片段'} · {displayLabel}</span>
                {!expanded && previewText ? (
                    <span className="inline-thinking-preview">{previewText}</span>
                ) : null}
                <span className={`inline-thinking-chevron ${expanded ? 'inline-thinking-chevron-open' : ''}`} aria-hidden="true">
                    ›
                </span>
            </button>
            {expanded && displayText ? (
                <div ref={bodyRef} className="inline-thinking-body app-scrollbar">
                    <div className={`inline-thinking-text ${isStreaming ? 'inline-thinking-text-streaming' : ''}`}>
                        <MarkdownRender
                            content={displayText}
                            className="reasoning-markdown"
                        />
                    </div>
                </div>
            ) : null}
        </div>
    );
};

interface TimelineRenderProps {
    segments: AssistantTimelineSegment[];
    contentClassName: string;
    isStreaming: boolean;
}

const TimelineRender: React.FC<TimelineRenderProps> = ({ segments, contentClassName, isStreaming }) => (
    <div className="assistant-timeline">
        {segments.map((segment, index) => {
            if (segment.kind === 'thinking') {
                return <InlineThinkingBox key={segment.id} segment={segment} />;
            }
            const isActiveAnswer = isStreaming && index === segments.length - 1 && segment.status === 'streaming';
            return (
                <div key={segment.id} className="assistant-answer-segment">
                    <MarkdownRender
                        content={segment.text}
                        className={contentClassName}
                    />
                    {isActiveAnswer ? (
                        <span className="stream-caret" aria-hidden="true" />
                    ) : null}
                </div>
            );
        })}
    </div>
);

const ChatMessageBubbleImpl: React.FC<ChatMessageBubbleProps> = ({
    message,
    fsmState: _fsmState,
    onConfirmDraft: _onConfirmDraft,
    onRollbackDraft: _onRollbackDraft,
    isConfirmDisabled: _isConfirmDisabled,
    draftActionPending: _draftActionPending,
    canEditUserMessage = false,
    onRequestEditUserMessage,
    isEditingUserMessage = false,
    editDraftValue = '',
    onEditDraftChange,
    onSubmitEditUserMessage,
    onCancelEditUserMessage,
}) => {
    const copy = useUiCopy();
    const isUser = message.role === 'user';
    const isError = message.status === 'error';
    const isInterrupted = message.status === 'interrupted';
    const currentStageIndex = !isUser
        ? message.stageEvents.findIndex((event) => event.status === 'streaming')
        : -1;
    const resolvedStageIndex = !isUser
        ? (currentStageIndex >= 0 ? currentStageIndex : message.stageEvents.length - 1)
        : -1;
    const currentStage = !isUser && resolvedStageIndex >= 0
        ? (message.stageProgress || message.stageEvents[resolvedStageIndex] || null)
        : null;
    const currentPreviewIndex = !isUser
        ? message.previewEvents.findIndex((event) => event.status === 'streaming')
        : -1;
    const resolvedPreviewIndex = !isUser
        ? (currentPreviewIndex >= 0 ? currentPreviewIndex : message.previewEvents.length - 1)
        : -1;
    const currentPreview = !isUser && resolvedPreviewIndex >= 0
        ? (message.previewEvents[resolvedPreviewIndex] || null)
        : null;
    const currentReasoningIndex = !isUser
        ? message.reasoningEvents.findIndex((event) => event.status === 'streaming')
        : -1;
    const resolvedReasoningIndex = !isUser
        ? (currentReasoningIndex >= 0 ? currentReasoningIndex : message.reasoningEvents.length - 1)
        : -1;
    const currentReasoning = !isUser && resolvedReasoningIndex >= 0
        ? (message.reasoningEvents[resolvedReasoningIndex] || null)
        : null;
    const hasTimelineSegments = !isUser && message.timelineSegments.length > 0;
    const showStageTrace = Boolean(currentStage);
    const showPreviewTrace = Boolean(currentPreview) && (message.status === 'streaming' || !message.text);
    const showReasoningTrace = Boolean(currentReasoning) && !hasTimelineSegments;
    const textPlaceholder = !message.text
        ? message.diffAttachment
            ? copy.chat.draftReady
            : message.status === 'streaming'
                ? '...'
                : ''
        : '';
    const resolutionText = message.resolution === 'confirmed'
        ? copy.chat.confirmed
        : message.resolution === 'rolled_back'
            ? copy.chat.rolledBack
            : null;
    const isPlainAssistant = !isUser && !isError && !isInterrupted;
    const shapeClasses = isUser ? 'rounded-[18px_18px_10px_18px]' : 'rounded-[18px_18px_18px_10px]';

    const bubbleClasses = isUser
        ? 'ml-auto border border-[var(--tone-info-border)] bg-[var(--tone-info-bg)] text-[var(--tone-info-text)] shadow-[0_10px_20px_rgba(0,0,0,0.16)]'
        : isError
            ? 'mr-auto border border-[var(--tone-danger-border)] bg-[var(--tone-danger-bg)] text-[var(--tone-danger-text)]'
            : isInterrupted
                ? 'mr-auto border border-[var(--tone-warning-border)] bg-[var(--tone-warning-bg)] text-[var(--tone-warning-text)]'
            : 'mr-auto border border-[rgba(255,255,255,0.04)] bg-[rgba(255,255,255,0.012)] text-[var(--color-dark-text-main)]';

    const contentClassName = isPlainAssistant
        ? 'max-w-[41rem] !text-inherit [&>*:first-child]:mt-0 [&>*:last-child]:mb-0'
        : 'max-w-[32rem] !text-inherit [&>*:first-child]:mt-0 [&>*:last-child]:mb-0';

    if (isUser && isEditingUserMessage) {
        return (
            <div className="max-w-[92%] rounded-[20px] border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.018)] px-5 py-4 shadow-[0_10px_24px_rgba(0,0,0,0.18)]">
                <div className="mb-3 text-[11px] font-medium text-[var(--color-dark-text-faint)]">
                    {copy.chat.editDraftLabel}
                </div>
                <textarea
                    value={editDraftValue}
                    onChange={(event) => onEditDraftChange?.(event.target.value)}
                    rows={4}
                    className="min-h-[144px] w-full resize-none rounded-[14px] border border-[rgba(255,255,255,0.06)] bg-[rgba(12,15,20,0.92)] px-4 py-3 text-[15px] leading-7 text-[var(--color-dark-text-main)] outline-none transition-colors focus:border-[rgba(255,255,255,0.14)]"
                />
                <div className="mt-4 flex items-center justify-end gap-3">
                    <button
                        type="button"
                        onClick={onCancelEditUserMessage}
                        className="rounded-[999px] border border-[rgba(255,255,255,0.08)] px-4 py-2 text-[14px] text-[var(--color-dark-text-muted)] transition-colors hover:border-[rgba(255,255,255,0.14)] hover:text-[var(--color-dark-text-main)]"
                    >
                        {copy.common.cancel}
                    </button>
                    <button
                        type="button"
                        onClick={onSubmitEditUserMessage}
                        className="rounded-[999px] border border-[var(--tone-success-border)] bg-[var(--tone-success-bg)] px-4 py-2 text-[14px] font-medium text-[var(--tone-success-text)] transition-colors hover:bg-[rgba(255,255,255,0.12)]"
                    >
                        {copy.composer.resend}
                    </button>
                </div>
            </div>
        );
    }

    const innerContent = (
        <>
            {showStageTrace && currentStage ? (
                <div className="mb-2">
                    <RollingSlot
                        slotKey={`stage:${resolvedStageIndex}:${currentStage.sourceEvent || ''}:${currentStage.nodeTitle || currentStage.stageCode}`}
                        status={currentStage.status || (message.status === 'streaming' ? 'streaming' : 'done')}
                        eyebrow={currentStage.status === 'streaming' ? copy.chat.currentNode : copy.chat.recentNode}
                        title={currentStage.nodeTitle || currentStage.stageCode}
                        body={currentStage.nodeTitle ? currentStage.stageText : undefined}
                        kind="stage"
                        defaultOpen={false}
                    />
                </div>
            ) : null}
            {showReasoningTrace && (
                <div className="mb-3">
                    <RollingSlot
                        slotKey={`reasoning:${resolvedReasoningIndex}:${currentReasoning?.sourceEvent || ''}:${currentReasoning?.label || ''}`}
                        status={currentReasoning?.status || (message.status === 'streaming' ? 'streaming' : 'done')}
                        eyebrow={currentReasoning?.status === 'streaming' ? copy.chat.thinkingNow : copy.chat.recentThought}
                        title={currentReasoning?.label || copy.chat.thinking}
                        body={currentReasoning?.text || ''}
                        kind="reasoning"
                    />
                </div>
            )}
            {showPreviewTrace && currentPreview ? (
                <div className="mb-3">
                    <RollingSlot
                        slotKey={`preview:${resolvedPreviewIndex}:${currentPreview.sourceEvent || ''}:${currentPreview.label}`}
                        status={currentPreview.status || (message.status === 'streaming' ? 'streaming' : 'done')}
                        eyebrow={currentPreview.status === 'streaming' ? copy.chat.previewNow : copy.chat.recentPreview}
                        title={currentPreview.label}
                        body={currentPreview.text}
                        kind="preview"
                    />
                </div>
            ) : null}

            {hasTimelineSegments ? (
                <TimelineRender
                    segments={message.timelineSegments}
                    contentClassName={contentClassName}
                    isStreaming={message.status === 'streaming'}
                />
            ) : message.text ? (
                <MarkdownRender
                    content={message.text}
                    className={contentClassName}
                />
            ) : (
                <div>{textPlaceholder}</div>
            )}
            {message.status === 'streaming' && !isUser && !!message.text && !hasTimelineSegments && (
                <span className="stream-caret" aria-hidden="true" />
            )}

            {isInterrupted && (
                <div className="mt-3 inline-flex rounded-full border border-[var(--tone-warning-border)] bg-[var(--tone-warning-bg)] px-2.5 py-1 text-[11px] text-[var(--tone-warning-text)]">
                    {copy.chat.interrupted}
                </div>
            )}

            {message.diffAttachment && (
                <div className="mt-3 inline-flex rounded-full border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-2.5 py-1 text-[11px] text-[var(--color-dark-text-muted)]">
                    {copy.chat.draftReady}
                </div>
            )}

            {resolutionText && (
                <div className="mt-3 inline-flex rounded-full border border-[var(--color-dark-border)] bg-[rgba(9,12,16,0.9)] px-2.5 py-1 text-[11px] text-[var(--color-dark-text-muted)]">
                    {resolutionText}
                </div>
            )}
        </>
    );

    if (isPlainAssistant) {
        return (
            <div className="w-full px-0.5 py-0.5 text-[13px] leading-[1.72] text-[var(--color-dark-text-main)]">
                <div className="max-w-[94%] border-l border-[rgba(255,255,255,0.08)] pl-3 pr-1.5">
                    {innerContent}
                </div>
            </div>
        );
    }

    return (
        <div className="group/message relative max-w-[76%]">
            <div className={`px-4 py-3.5 text-[13px] leading-5 ${shapeClasses} ${bubbleClasses}`}>
                {innerContent}
            </div>
            {isUser && canEditUserMessage && onRequestEditUserMessage ? (
                <button
                    type="button"
                    onClick={() => onRequestEditUserMessage(message.id, message.text)}
                    className="absolute bottom-2 right-2 rounded-[999px] border border-[rgba(255,255,255,0.12)] bg-[rgba(14,17,22,0.92)] px-3 py-1.5 text-[11px] font-medium text-[var(--color-dark-text-main)] opacity-0 transition-all group-hover/message:opacity-100 hover:border-[rgba(255,255,255,0.22)] hover:bg-[rgba(20,24,30,0.96)]"
                >
                    {copy.chat.edit}
                </button>
            ) : null}
        </div>
    );
};

function areChatMessageBubblePropsEqual(prev: ChatMessageBubbleProps, next: ChatMessageBubbleProps): boolean {
    return (
        prev.message === next.message &&
        prev.fsmState === next.fsmState &&
        prev.isConfirmDisabled === next.isConfirmDisabled &&
        prev.draftActionPending === next.draftActionPending &&
        prev.canEditUserMessage === next.canEditUserMessage &&
        prev.isEditingUserMessage === next.isEditingUserMessage &&
        prev.editDraftValue === next.editDraftValue &&
        prev.onRequestEditUserMessage === next.onRequestEditUserMessage &&
        prev.onEditDraftChange === next.onEditDraftChange &&
        prev.onSubmitEditUserMessage === next.onSubmitEditUserMessage &&
        prev.onCancelEditUserMessage === next.onCancelEditUserMessage
    );
}

export const ChatMessageBubble = React.memo(ChatMessageBubbleImpl, areChatMessageBubblePropsEqual);
