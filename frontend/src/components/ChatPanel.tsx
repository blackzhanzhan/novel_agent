import React, { useEffect, useMemo, useRef } from 'react';
import { ChatMessage, DraftActionPending, FsmState } from '../types/store';
import { ChatMessageBubble } from './ChatMessageBubble';

interface ChatPanelProps {
    messages: ChatMessage[];
    fsmState: FsmState;
    onConfirmDraft: () => void;
    onRollbackDraft: () => void;
    isConfirmDisabled: boolean;
    draftActionPending: DraftActionPending;
    editableUserMessageId?: string | null;
    onRequestEditUserMessage?: (messageId: string, text: string) => void;
    editingUserMessageId?: string | null;
    editDraftValue?: string;
    onEditDraftChange?: (next: string) => void;
    onSubmitEditUserMessage?: () => void;
    onCancelEditUserMessage?: () => void;
}

const ChatPanelImpl: React.FC<ChatPanelProps> = ({
    messages,
    fsmState,
    onConfirmDraft,
    onRollbackDraft,
    isConfirmDisabled,
    draftActionPending,
    editableUserMessageId = null,
    onRequestEditUserMessage,
    editingUserMessageId = null,
    editDraftValue = '',
    onEditDraftChange,
    onSubmitEditUserMessage,
    onCancelEditUserMessage,
}) => {
    const scrollAnchorRef = useRef<HTMLDivElement | null>(null);
    const scrollToken = useMemo(() => (
        messages.map((message) => {
            const timelineShape = message.timelineSegments
                .map((segment) => (
                    segment.kind === 'answer'
                        ? `a:${segment.text.length}`
                        : `t:${segment.id}:${segment.status || 'streaming'}`
                ))
                .join(',');
            const diffState = message.diffAttachment ? 'diff' : '';
            return `${message.id}:${message.status}:${message.text.length}:${timelineShape}:${diffState}`;
        }).join('|')
    ), [messages]);

    useEffect(() => {
        scrollAnchorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }, [scrollToken]);

    if (messages.length === 0) {
        return (
            <div
                data-shot="conversation-body"
                className="workspace-lane-empty relative flex min-h-0 w-full flex-1 flex-col overflow-hidden bg-transparent px-2.5 py-2 text-left text-[var(--color-dark-text-muted)]"
            >
                <div className="relative mt-auto min-h-16 pl-2.5">
                    <div className="absolute bottom-0 left-0 top-1 w-px bg-[linear-gradient(180deg,rgba(255,255,255,0.1)_0%,rgba(255,255,255,0.01)_100%)]" />
                </div>
            </div>
        );
    }

    return (
        <div data-shot="conversation-body" className="app-scrollbar flex-1 min-h-0 overflow-y-auto bg-transparent px-2 py-2">
            <div className="space-y-2.5">
            {messages.map((message) => (
                <ChatMessageBubble
                    key={message.id}
                    message={message}
                    fsmState={fsmState}
                    onConfirmDraft={onConfirmDraft}
                    onRollbackDraft={onRollbackDraft}
                    isConfirmDisabled={isConfirmDisabled}
                    draftActionPending={draftActionPending}
                    canEditUserMessage={message.id === editableUserMessageId}
                    onRequestEditUserMessage={onRequestEditUserMessage}
                    isEditingUserMessage={message.id === editingUserMessageId}
                    editDraftValue={editDraftValue}
                    onEditDraftChange={onEditDraftChange}
                    onSubmitEditUserMessage={onSubmitEditUserMessage}
                    onCancelEditUserMessage={onCancelEditUserMessage}
                />
            ))}
            </div>
            <div ref={scrollAnchorRef} />
        </div>
    );
};

function areChatPanelPropsEqual(prev: ChatPanelProps, next: ChatPanelProps): boolean {
    return (
        prev.messages === next.messages &&
        prev.fsmState === next.fsmState &&
        prev.isConfirmDisabled === next.isConfirmDisabled &&
        prev.draftActionPending === next.draftActionPending &&
        prev.editableUserMessageId === next.editableUserMessageId &&
        prev.editingUserMessageId === next.editingUserMessageId &&
        prev.editDraftValue === next.editDraftValue &&
        prev.onConfirmDraft === next.onConfirmDraft &&
        prev.onRollbackDraft === next.onRollbackDraft &&
        prev.onRequestEditUserMessage === next.onRequestEditUserMessage &&
        prev.onEditDraftChange === next.onEditDraftChange &&
        prev.onSubmitEditUserMessage === next.onSubmitEditUserMessage &&
        prev.onCancelEditUserMessage === next.onCancelEditUserMessage
    );
}

export const ChatPanel = React.memo(ChatPanelImpl, areChatPanelPropsEqual);
