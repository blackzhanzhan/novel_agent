import type { ChatMessage } from '../types/store';

export declare function findLatestUserMessage(messages: ChatMessage[]): ChatMessage | null;
export declare function rewriteTailMessages(
    messages: ChatMessage[],
    targetUserMessageId: string,
    nextText: string
): ChatMessage[];
