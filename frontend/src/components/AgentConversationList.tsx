import React, { useEffect, useMemo, useState } from 'react';
import { AgentKey, ConversationMeta } from '../types/store';
import { getAgentLabel, useUiCopy, useUiLanguage } from '../i18n/ui';

interface AgentConversationListProps {
    agent: AgentKey;
    activeConversationId: string | null;
    activeFile: string;
    conversations: ConversationMeta[];
    currentFileAgent: AgentKey;
    onSwitchAgent: (agent: AgentKey) => void;
    onCreateConversation: () => void;
    onSelectConversation: (conversationId: string) => void;
    onRenameConversation: (conversationId: string) => void;
    onArchiveConversation: (conversationId: string) => void;
    onDeleteConversation: (conversationId: string) => void;
    disabled?: boolean;
}

export const AgentConversationList: React.FC<AgentConversationListProps> = ({
    agent,
    activeConversationId,
    activeFile,
    conversations,
    currentFileAgent,
    onSwitchAgent,
    onCreateConversation,
    onSelectConversation,
    onRenameConversation,
    onArchiveConversation,
    onDeleteConversation,
    disabled = false,
}) => {
    const agentOptions: AgentKey[] = ['world_agent', 'outline_agent', 'style_agent', 'continuation_agent', 'review_agent'];
    const copy = useUiCopy();
    const uiLanguage = useUiLanguage();
    const [panelOpen, setPanelOpen] = useState(false);
    const [search, setSearch] = useState('');
    const currentConversation = useMemo(
        () => conversations.find((item) => item.conversation_id === activeConversationId) || conversations[0] || null,
        [activeConversationId, conversations],
    );
    const filteredConversations = useMemo(() => {
        const keyword = search.trim().toLowerCase();
        if (!keyword) return conversations;
        return conversations.filter((conversation) => {
            const haystack = `${conversation.title || ''} ${conversation.last_active_file || ''}`.toLowerCase();
            return haystack.includes(keyword);
        });
    }, [conversations, search]);

    useEffect(() => {
        setSearch('');
        setPanelOpen(false);
    }, [agent]);

    const currentAgentLabel = getAgentLabel(uiLanguage, agent);

    return (
        <div
            data-shot="conversation-rail"
            className="border-b border-[rgba(255,255,255,0.035)] bg-transparent px-2 py-1"
        >
            <div className="mb-1 flex items-center justify-between gap-3">
                <div className="min-w-0">
                    <div className="flex items-baseline gap-1.5">
                        <div className="cursor-section-label">{copy.conversation.section}</div>
                        <div className="truncate text-[10px] font-medium text-[var(--color-dark-text-main)]">
                            {currentAgentLabel}
                        </div>
                    </div>
                </div>
                <button
                    type="button"
                    onClick={onCreateConversation}
                    disabled={disabled}
                    aria-label={copy.conversation.newThread}
                    title={copy.conversation.newThread}
                    className="cursor-chip shrink-0 rounded-[10px] px-2.5 py-[4px] text-[11px] font-medium text-[var(--color-dark-text-faint)] transition-colors hover:border-[var(--color-dark-border-strong)] hover:text-[var(--color-dark-text-main)] disabled:cursor-not-allowed disabled:opacity-60"
                >
                    +
                </button>
            </div>

            <button
                type="button"
                onClick={() => setPanelOpen((open) => !open)}
                disabled={disabled}
                className="group/thread w-full rounded-[8px] border border-[rgba(255,255,255,0.035)] bg-[rgba(255,255,255,0.01)] px-2.5 py-2 text-left transition-colors hover:border-[rgba(255,255,255,0.08)] disabled:cursor-not-allowed disabled:opacity-60"
                aria-expanded={panelOpen}
            >
                <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0 flex-1">
                        <div className="truncate text-[11px] font-medium text-[var(--color-dark-text-main)]">
                            {currentConversation?.title || copy.conversation.noCurrentThread}
                        </div>
                        <div className="mt-0.5 flex items-center gap-2 text-[9px] text-[var(--color-dark-text-faint)]">
                            <span className="truncate font-mono">
                                {currentConversation?.last_active_file || activeFile}
                            </span>
                            {currentConversation ? <span>{copy.conversation.messages(currentConversation.message_count)}</span> : null}
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        {currentConversation ? (
                            <div className="flex items-center gap-1.5 opacity-0 transition-opacity group-hover/thread:opacity-100 group-focus-within/thread:opacity-100">
                                <span
                                    role="button"
                                    tabIndex={0}
                                    onClick={(event) => {
                                        event.stopPropagation();
                                        if (!disabled) onRenameConversation(currentConversation.conversation_id);
                                    }}
                                    onKeyDown={(event) => {
                                        if ((event.key === 'Enter' || event.key === ' ') && !disabled) {
                                            event.preventDefault();
                                            onRenameConversation(currentConversation.conversation_id);
                                        }
                                    }}
                                    className="text-[9px] text-[var(--color-dark-text-faint)] hover:text-[var(--color-dark-text-main)]"
                                >
                                    {copy.conversation.rename}
                                </span>
                                <span
                                    role="button"
                                    tabIndex={0}
                                    onClick={(event) => {
                                        event.stopPropagation();
                                        if (!disabled) onArchiveConversation(currentConversation.conversation_id);
                                    }}
                                    onKeyDown={(event) => {
                                        if ((event.key === 'Enter' || event.key === ' ') && !disabled) {
                                            event.preventDefault();
                                            onArchiveConversation(currentConversation.conversation_id);
                                        }
                                    }}
                                    className="text-[9px] text-[#c79ea1] hover:text-[#ffd3d6]"
                                >
                                    {copy.conversation.archive}
                                </span>
                                <span
                                    role="button"
                                    tabIndex={0}
                                    onClick={(event) => {
                                        event.stopPropagation();
                                        if (!disabled) onDeleteConversation(currentConversation.conversation_id);
                                    }}
                                    onKeyDown={(event) => {
                                        if ((event.key === 'Enter' || event.key === ' ') && !disabled) {
                                            event.preventDefault();
                                            onDeleteConversation(currentConversation.conversation_id);
                                        }
                                    }}
                                    className="text-[9px] text-[#d28f93] hover:text-[#ffd9dc]"
                                >
                                    {copy.conversation.remove}
                                </span>
                            </div>
                        ) : null}
                        <span className={`text-[10px] text-[var(--color-dark-text-faint)] transition-transform ${panelOpen ? 'rotate-180' : 'rotate-0'}`}>
                            ▾
                        </span>
                    </div>
                </div>
            </button>

            {panelOpen ? (
                <div className="mt-1.5 rounded-[8px] border border-[rgba(255,255,255,0.035)] bg-[rgba(12,14,18,0.72)] px-2 py-2">
                    <div className="mb-2 flex items-center gap-2 border-b border-[rgba(255,255,255,0.035)] pb-2">
                        <input
                            value={search}
                            onChange={(event) => setSearch(event.target.value)}
                            placeholder={copy.conversation.searchHistory}
                            className="w-full border-0 bg-transparent text-[11px] text-[var(--color-dark-text-main)] outline-none placeholder:text-[var(--color-dark-text-faint)]"
                        />
                    </div>

                    <div className="mb-2 flex gap-1">
                        {agentOptions.map((candidate) => {
                            const isSelected = candidate === agent;
                            const isCurrent = candidate === currentFileAgent;
                            return (
                                <button
                                    key={candidate}
                                    type="button"
                                    onClick={() => {
                                        setPanelOpen(true);
                                        onSwitchAgent(candidate);
                                    }}
                                    disabled={disabled || isSelected}
                                    className={`rounded-[8px] border px-2 py-[4px] text-[10px] font-mono transition-colors ${
                                        isSelected
                                            ? 'cursor-chip-active'
                                            : 'cursor-chip text-[var(--color-dark-text-faint)] hover:border-[var(--color-dark-border-strong)] hover:text-[var(--color-dark-text-main)]'
                                    } ${disabled ? 'cursor-not-allowed opacity-60' : ''}`}
                                >
                                    <span className="truncate">{getAgentLabel(uiLanguage, candidate)}</span>
                                    {isCurrent ? <span className="ml-1 opacity-60">·</span> : null}
                                </button>
                            );
                        })}
                    </div>

                    {filteredConversations.length === 0 ? (
                        <div className="px-1 py-2 text-[10px] text-[var(--color-dark-text-faint)]">
                            {copy.conversation.noMatchedHistory}
                        </div>
                    ) : (
                        <div className="app-scrollbar max-h-56 overflow-y-auto">
                            {filteredConversations.map((conversation) => {
                                const isActive = conversation.conversation_id === activeConversationId;
                                return (
                                    <button
                                        key={conversation.conversation_id}
                                        type="button"
                                        onClick={() => {
                                            if (disabled) return;
                                            setPanelOpen(false);
                                            onSelectConversation(conversation.conversation_id);
                                        }}
                                        className={`w-full rounded-[8px] border-l border-transparent px-2 py-2 text-left text-[10px] transition-colors ${
                                            isActive
                                                ? 'border-[rgba(255,255,255,0.16)] bg-[rgba(255,255,255,0.035)] text-[var(--color-dark-text-main)]'
                                                : 'text-[var(--color-dark-text-muted)] hover:border-[rgba(255,255,255,0.08)] hover:bg-[rgba(255,255,255,0.02)] hover:text-[var(--color-dark-text-main)]'
                                        }`}
                                    >
                                        <div className="truncate font-medium">{conversation.title || copy.conversation.untitledThread}</div>
                                        <div className="mt-0.5 flex items-center justify-between gap-2 text-[9px] text-[var(--color-dark-text-faint)]">
                                            <span className="truncate font-mono">{conversation.last_active_file}</span>
                                            <span>{copy.conversation.messages(conversation.message_count)}</span>
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                    )}
                </div>
            ) : null}
        </div>
    );
};
