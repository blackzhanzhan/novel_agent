import { fetchApi } from './client';
import { AgentKey, ConversationMeta } from '../types/store';

interface BookRef {
    kind: 'book_name' | 'book_id';
    value: string;
}

export interface ConversationRecordPayload {
    id: string;
    ts: string;
    role: 'user' | 'assistant' | 'system';
    text: string;
    conversation_id: string;
    upstream_conversation_id?: string | null;
    active_file: string;
    status: 'streaming' | 'done' | 'error' | 'interrupted';
}

export interface ConversationContextResponse {
    status: 'success';
    book_id: string;
    agent_key: AgentKey;
    active_conversation_id: string | null;
    conversation_id: string | null;
    upstream_conversation_id: string | null;
    conversations: ConversationMeta[];
    messages: ConversationRecordPayload[];
}

function getBookQuery(bookRef: BookRef): string {
    return bookRef.kind === 'book_name'
        ? `book_name=${encodeURIComponent(bookRef.value)}`
        : `book_id=${encodeURIComponent(bookRef.value)}`;
}

export async function fetchConversationContext(
    bookRef: BookRef,
    agentKey: AgentKey,
    conversationId?: string | null,
): Promise<ConversationContextResponse> {
    const conversationQuery = conversationId ? `&conversation_id=${encodeURIComponent(conversationId)}` : '';
    return fetchApi<ConversationContextResponse>(
        `/api/conversations/context?${getBookQuery(bookRef)}&agent=${encodeURIComponent(agentKey)}${conversationQuery}`
    );
}

export async function createConversation(
    bookRef: BookRef,
    agentKey: AgentKey,
    activeFile: string,
    title?: string,
): Promise<ConversationContextResponse> {
    return fetchApi<ConversationContextResponse>('/api/conversations/create', {
        method: 'POST',
        body: JSON.stringify({
            [bookRef.kind]: bookRef.value,
            agent: agentKey,
            active_file: activeFile,
            title,
        }),
    });
}

export async function activateConversation(
    bookRef: BookRef,
    agentKey: AgentKey,
    conversationId: string,
): Promise<ConversationContextResponse> {
    return fetchApi<ConversationContextResponse>('/api/conversations/activate', {
        method: 'POST',
        body: JSON.stringify({
            [bookRef.kind]: bookRef.value,
            agent: agentKey,
            conversation_id: conversationId,
        }),
    });
}

export async function renameConversation(
    bookRef: BookRef,
    agentKey: AgentKey,
    conversationId: string,
    title: string,
): Promise<ConversationContextResponse> {
    return fetchApi<ConversationContextResponse>('/api/conversations/rename', {
        method: 'POST',
        body: JSON.stringify({
            [bookRef.kind]: bookRef.value,
            agent: agentKey,
            conversation_id: conversationId,
            title,
        }),
    });
}

export async function archiveConversation(
    bookRef: BookRef,
    agentKey: AgentKey,
    conversationId: string,
): Promise<ConversationContextResponse> {
    return fetchApi<ConversationContextResponse>('/api/conversations/archive', {
        method: 'POST',
        body: JSON.stringify({
            [bookRef.kind]: bookRef.value,
            agent: agentKey,
            conversation_id: conversationId,
        }),
    });
}

export async function deleteConversation(
    bookRef: BookRef,
    agentKey: AgentKey,
    conversationId: string,
): Promise<ConversationContextResponse> {
    return fetchApi<ConversationContextResponse>('/api/conversations/delete', {
        method: 'POST',
        body: JSON.stringify({
            [bookRef.kind]: bookRef.value,
            agent: agentKey,
            conversation_id: conversationId,
        }),
    });
}
