import type { ChatMessage } from '../types/store';

export function mapConversationMessages(messages: Array<any>): ChatMessage[] {
    return messages.map((item, idx) => ({
        id: typeof item?.id === 'string' ? item.id : `restored_${idx}`,
        role: item?.role === 'assistant' || item?.role === 'system' ? item.role : 'user',
        text: typeof item?.text === 'string' ? item.text : '',
        status: item?.status === 'streaming' || item?.status === 'error' || item?.status === 'interrupted' ? item.status : 'done',
        conversationId: typeof item?.conversation_id === 'string' ? item.conversation_id : null,
        upstreamConversationId: typeof item?.upstream_conversation_id === 'string' ? item.upstream_conversation_id : null,
        activeFile: typeof item?.active_file === 'string' ? item.active_file : undefined,
        diffAttachment: null,
        stageProgress: null,
        stageEvents: [],
        reasoningEvents: [],
        previewEvents: [],
        timelineSegments: [],
        resolution: null,
        resolvedAt: null,
    }));
}

export function normalizeChangedFilesPayload(value: unknown): string[] {
    return Array.isArray(value)
        ? value.filter((item: unknown): item is string => typeof item === 'string' && item.length > 0)
        : [];
}

export function normalizeConversationText(text: string): string {
    return text.replace(/\r\n/g, '\n').replace(/\s+/g, ' ').trim();
}

export function markUiTraceItemsDone<T extends { status?: 'streaming' | 'done' }>(items: T[]): T[] {
    return items.map((item) => ({
        ...item,
        status: 'done' as const,
    }));
}

export function hasLocalUiTrace(message: ChatMessage): boolean {
    return (
        message.stageEvents.length > 0
        || message.reasoningEvents.length > 0
        || message.previewEvents.length > 0
        || message.timelineSegments.length > 0
        || Boolean(message.diffAttachment)
        || Boolean(message.resolution)
    );
}

export function isSameConversationMessage(remote: ChatMessage, local: ChatMessage): boolean {
    if (remote.role !== local.role) return false;
    if (remote.activeFile && local.activeFile && remote.activeFile !== local.activeFile) return false;
    const remoteText = normalizeConversationText(remote.text);
    const localText = normalizeConversationText(local.text);
    if (!remoteText || !localText) return false;
    if (remoteText === localText) return true;
    return remote.role === 'assistant' && (remoteText.endsWith(localText) || localText.endsWith(remoteText));
}

export function mergeHydratedMessagesWithLocalUiState(
    hydratedMessages: ChatMessage[],
    localMessages: ChatMessage[],
): ChatMessage[] {
    const usedLocalIndexes = new Set<number>();
    return hydratedMessages.map((remote) => {
        let matchedIndex = -1;
        for (let idx = localMessages.length - 1; idx >= 0; idx -= 1) {
            if (usedLocalIndexes.has(idx)) continue;
            const local = localMessages[idx];
            if (!hasLocalUiTrace(local)) continue;
            if (!isSameConversationMessage(remote, local)) continue;
            matchedIndex = idx;
            break;
        }
        if (matchedIndex < 0) return remote;
        usedLocalIndexes.add(matchedIndex);
        const local = localMessages[matchedIndex];
        return {
            ...remote,
            diffAttachment: local.diffAttachment,
            stageProgress: null,
            stageEvents: markUiTraceItemsDone(local.stageEvents),
            reasoningEvents: markUiTraceItemsDone(local.reasoningEvents),
            previewEvents: markUiTraceItemsDone(local.previewEvents),
            timelineSegments: markUiTraceItemsDone(local.timelineSegments),
            resolution: local.resolution,
            resolvedAt: local.resolvedAt,
        };
    });
}
