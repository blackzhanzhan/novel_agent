import { ApiError, fetchApi } from './client';
import { streamSseJson } from './sse';
import { AgentKey, CoreSessionState } from '../types/store';

export type DeductionWriteScope = 'generic' | 'world_core' | 'active_file_strict';

export interface DeductionPayload {
    intent: string;
    active_file: string;
    file_type: CoreSessionState['activeFileType'];
    write_scope?: DeductionWriteScope;
    base_etag: string;
    thread_id?: string;
    conversation_id?: string;
    upstream_conversation_id?: string;
    rewrite_user_message_id?: string;
    route_agent_key?: string;
    detached_job?: boolean;
    dify_user?: string;
    chapter_index: number;
}

export interface DeductionResponse {
    status: 'success';
    file_name: string;
    content: string;
    etag: string;
    branch: string;
    commit_id?: string;
    conversation_id?: string;
    answer?: string;
}

export interface DeductionStreamHandlers {
    onAck?: (payload: any) => void;
    onStage?: (payload: any) => void;
    onReasoning?: (payload: any) => void;
    onPreview?: (payload: any) => void;
    onDelta?: (delta: string, payload: any) => void;
    onDraftReady?: (payload: any) => void;
    onGitSyncSuccess?: (payload: any) => void;
    onDone?: (payload: any) => void;
    onError?: (payload: any) => void;
}

function looksLikeWorldInitIntent(intent: string): boolean {
    const normalized = intent.trim().toLowerCase();
    if (!normalized) return false;
    return ['初始化', 'init', 'bootstrap', '双写', '双核心', '双底座'].some((token) =>
        normalized.includes(token)
    );
}

export async function stopDeductionStream(
    bookRef: CoreSessionState['bookRef'],
    activeFile: string,
    taskId: string,
): Promise<{ status: 'success'; task_id: string; result: string }> {
    const payload = {
        [bookRef.kind]: bookRef.value,
        active_file: activeFile,
        task_id: taskId,
    };
    return fetchApi<{ status: 'success'; task_id: string; result: string }>('/api/world/stop_generation', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
}

export async function runDeduction(
    intent: string,
    state: CoreSessionState,
    options?: { rewriteUserMessageId?: string }
): Promise<{ draftContent: string; commitId: string | null; conversationId: string | null }> {
    const payload: DeductionPayload = {
        intent,
        active_file: state.activeFile,
        file_type: state.activeFileType,
        write_scope: 'active_file_strict',
        base_etag: state.baseEtag,
        thread_id: state.conversationId || undefined,
        chapter_index: 0,
    };
    const isolatedConversationId = state.upstreamConversationByAgent[state.activeAgent] || state.upstreamConversationId;
    if (isolatedConversationId) {
        payload.upstream_conversation_id = isolatedConversationId;
        payload.conversation_id = isolatedConversationId;
    }
    if (options?.rewriteUserMessageId) {
        payload.rewrite_user_message_id = options.rewriteUserMessageId;
    }

    const queryParam = state.bookRef.kind === 'book_name'
        ? `book_name=${encodeURIComponent(state.bookRef.value)}`
        : `book_id=${encodeURIComponent(state.bookRef.value)}`;

    const response = await fetchApi<DeductionResponse>(`/api/world/deduce?${queryParam}`, {
        method: 'POST',
        body: JSON.stringify(payload)
    });

    return {
        draftContent: response.content,
        commitId: response.commit_id || null,
        conversationId: response.conversation_id || null,
    };
}

export async function runDeductionStream(
    intent: string,
    state: CoreSessionState,
    handlers: DeductionStreamHandlers,
    options?: {
        signal?: AbortSignal;
        rewriteUserMessageId?: string;
        routeAgentKey?: AgentKey;
        activeFile?: string;
        fileType?: CoreSessionState['activeFileType'];
        writeScope?: DeductionWriteScope;
        baseEtag?: string;
        detachedJob?: boolean;
        difyUser?: string;
    }
): Promise<void> {
    const routedAgent = options?.routeAgentKey || state.activeAgent;
    const routedThreadId = options?.detachedJob
        ? undefined
        : (state.conversationByAgent[routedAgent] || state.conversationId || undefined);
    const frontendToBackendAgentKey: Record<string, string> = {
        world_agent: 'world_model',
        outline_agent: 'outline',
        style_agent: 'style_guide',
        continuation_agent: 'continuation_agent',
        review_agent: 'review_agent',
    };
    const resolvedAgentKey = options?.routeAgentKey || state.activeAgent;
    const backendRouteKey = frontendToBackendAgentKey[resolvedAgentKey] || resolvedAgentKey;
    const payload: DeductionPayload = {
        intent,
        active_file: options?.activeFile || state.activeFile,
        file_type: options?.fileType || state.activeFileType,
        base_etag: options?.baseEtag ?? state.baseEtag,
        thread_id: routedThreadId,
        chapter_index: 0,
    };
    if (options?.detachedJob) {
        payload.detached_job = true;
    }
    if (options?.difyUser) {
        payload.dify_user = options.difyUser;
    }
    const payloadActiveFile = payload.active_file;
    const shouldUseWorldCoreScope =
        backendRouteKey === 'world_model' &&
        payloadActiveFile === 'world_model.md' &&
        looksLikeWorldInitIntent(intent);
    if (options?.writeScope) {
        payload.write_scope = options.writeScope;
    } else if (shouldUseWorldCoreScope) {
        payload.write_scope = 'world_core';
    } else if (options?.routeAgentKey !== 'review_agent') {
        payload.write_scope = 'active_file_strict';
    }
    payload.route_agent_key = backendRouteKey;
    const isolatedConversationId = options?.detachedJob
        ? null
        : (state.upstreamConversationByAgent[routedAgent] || state.upstreamConversationId);
    if (isolatedConversationId) {
        payload.upstream_conversation_id = isolatedConversationId;
        payload.conversation_id = isolatedConversationId;
    }
    if (options?.rewriteUserMessageId) {
        payload.rewrite_user_message_id = options.rewriteUserMessageId;
    }

    const queryParam = state.bookRef.kind === 'book_name'
        ? `book_name=${encodeURIComponent(state.bookRef.value)}`
        : `book_id=${encodeURIComponent(state.bookRef.value)}`;

    await streamSseJson({
        endpoint: `/api/world/deduce_stream?${queryParam}`,
        payload,
        signal: options?.signal,
        onEvent: (packet) => {
            const eventPayload = packet.data || {};
            if (packet.event === 'ack') {
                handlers.onAck?.(eventPayload);
                return;
            }
            if (packet.event === 'stage') {
                handlers.onStage?.(eventPayload);
                return;
            }
            if (packet.event === 'reasoning') {
                handlers.onReasoning?.(eventPayload);
                return;
            }
            if (packet.event === 'preview') {
                handlers.onPreview?.(eventPayload);
                return;
            }
            if (packet.event === 'delta') {
                const delta = typeof eventPayload.text === 'string' ? eventPayload.text : '';
                handlers.onDelta?.(delta, eventPayload);
                return;
            }
            if (packet.event === 'draft_ready') {
                handlers.onDraftReady?.(eventPayload);
                return;
            }
            if (packet.event === 'git_sync_success') {
                handlers.onGitSyncSuccess?.(eventPayload);
                return;
            }
            if (packet.event === 'done') {
                handlers.onDone?.(eventPayload);
                return;
            }
            if (packet.event === 'error') {
                handlers.onError?.(eventPayload);
                const status = typeof eventPayload.status === 'number' ? eventPayload.status : 500;
                const code = typeof eventPayload.code === 'string' ? eventPayload.code : 'STREAM_ERROR';
                const message = typeof eventPayload.message === 'string' ? eventPayload.message : 'stream failed';
                throw new ApiError(status, code, message, eventPayload);
            }
        },
    });
}

export interface BatchInitHandlers {
    onAck?: (payload: { total_batches: number; book_id: string; force_rebuild?: boolean }) => void;
    onProgress?: (payload: { batch_index: number; total: number; title: string; status: string }) => void;
    onBatchDone?: (payload: { batch_index: number; total: number; title: string }) => void;
    onBatchError?: (payload: { batch_index: number; title: string; error: string }) => void;
    onDone?: (payload: { completed: number; failed: number; skipped?: boolean; status_card_committed?: boolean; force_rebuild?: boolean }) => void;
    onError?: (payload: { message: string }) => void;
}

export async function runBatchInit(
    bookRef: CoreSessionState['bookRef'],
    handlers: BatchInitHandlers,
    options?: { signal?: AbortSignal; forceRebuild?: boolean }
): Promise<void> {
    const queryParam = bookRef.kind === 'book_name'
        ? `book_name=${encodeURIComponent(bookRef.value)}`
        : `book_id=${encodeURIComponent(bookRef.value)}`;

    await streamSseJson({
        endpoint: `/api/world/init_batch_pipeline?${queryParam}`,
        payload: { [bookRef.kind]: bookRef.value, force_rebuild: options?.forceRebuild === true },
        signal: options?.signal,
        onEvent: (packet) => {
            const d = packet.data || {};
            if (packet.event === 'ack') { handlers.onAck?.(d); return; }
            if (packet.event === 'progress') { handlers.onProgress?.(d); return; }
            if (packet.event === 'batch_done') { handlers.onBatchDone?.(d); return; }
            if (packet.event === 'batch_error') { handlers.onBatchError?.(d); return; }
            if (packet.event === 'done') { handlers.onDone?.(d); return; }
            if (packet.event === 'error') { handlers.onError?.(d); return; }
            if (packet.event === 'pipeline_end') { return; }
        },
    });
}

export interface StyleInitHandlers {
    onAck?: (payload: { total_steps: number; book_id: string; force_rebuild?: boolean; artifacts?: string[] }) => void;
    onProgress?: (payload: { step_index: number; total: number; title: string; status: string }) => void;
    onDone?: (payload: {
        completed: number;
        failed: number;
        skipped?: boolean;
        force_rebuild?: boolean;
        artifacts?: string[];
        updated_artifacts?: string[];
        commit_id?: string | null;
        warnings?: string[];
        source_files?: string[];
    }) => void;
    onError?: (payload: { message: string; artifact?: string }) => void;
}

export async function runStyleInit(
    bookRef: CoreSessionState['bookRef'],
    handlers: StyleInitHandlers,
    options?: { signal?: AbortSignal; forceRebuild?: boolean; sourceCount?: number }
): Promise<void> {
    const queryParam = bookRef.kind === 'book_name'
        ? `book_name=${encodeURIComponent(bookRef.value)}`
        : `book_id=${encodeURIComponent(bookRef.value)}`;

    await streamSseJson({
        endpoint: `/api/style/init_pipeline?${queryParam}`,
        payload: {
            [bookRef.kind]: bookRef.value,
            force_rebuild: options?.forceRebuild === true,
            source_count: options?.sourceCount || 12,
        },
        signal: options?.signal,
        onEvent: (packet) => {
            const d = packet.data || {};
            if (packet.event === 'ack') { handlers.onAck?.(d); return; }
            if (packet.event === 'progress') { handlers.onProgress?.(d); return; }
            if (packet.event === 'done') { handlers.onDone?.(d); return; }
            if (packet.event === 'error') { handlers.onError?.(d); return; }
            if (packet.event === 'pipeline_end') { return; }
        },
    });
}

export interface RollingWorkbenchState {
    status: 'ready';
    requiresPrompt: false;
    executionKind: 'direct_job';
    default_batch_size: number;
    batch_size: number;
    next_action: string;
    stop_reason: string;
    written_chapter_numbers: number[];
    pending_card_numbers: number[];
    selected_card_numbers: number[];
    blocked_card_numbers: number[];
    outline_card_states: Array<{
        number: number;
        title: string;
        status: 'selected' | 'pending' | 'blocked' | 'written' | 'ignored';
        executable: boolean;
        missing_fields: string[];
        heading_line: number;
        end_line: number;
    }>;
    outline_diagnostics: {
        outline_card_count: number;
        executable_card_count: number;
        detected_but_unparsed: boolean;
        message: string;
    };
    remaining_executable_after_selected: number[];
    full_batch_available: boolean;
    replenishment_needed_after_selected_batch: boolean;
    review_gate_open: boolean;
    quality_gate_locked: boolean;
    quality_gate_unlocked: boolean;
    source_files: {
        chapter_outline: { file_name: string; exists: boolean; size: number };
        chapter_draft: { file_name: string; exists: boolean; size: number };
    };
    no_prose_boundary: {
        state_contains_generated_prose: boolean;
        state_mutates_chapter_outline: boolean;
        state_writes_chapter_draft: boolean;
        continuation_agent_remains_only_chapter_draft_writer: boolean;
    };
}

export interface RollingStateResponse {
    status: 'success';
    book_id: string;
    generated_at: string;
    workbench_state: RollingWorkbenchState;
    plan: any;
}

export interface RollingAuthorWritingBrief {
    schema_version: number;
    brief_type: 'rolling_author_writing_brief';
    generated_at: string;
    book_id: string;
    target_file: 'chapter_draft.md';
    route_agent_key: 'continuation_agent';
    batch: {
        batch_size: number;
        selected_card_numbers: number[];
        full_batch_available: boolean;
        remaining_executable_after_selected: number[];
    };
    progress_cursor: {
        accepted_chapter_numbers: number[];
        pending_review_chapter_numbers: number[];
        pending_card_numbers: number[];
        next_action: string;
        stop_reason: string;
    };
    chapter_cards: Array<{
        number: number;
        title: string;
        goal: string;
        entry_scene: string;
        conflict: string;
        payoff: string;
        state_change: string;
        hook: string;
        constraint_refs: string;
        evidence_mode: string;
    }>;
    writing_contract: {
        what_to_write: string;
        where_to_write: string;
        what_not_to_do: string[];
    };
    truth_sources: Array<{
        name: string;
        path: string;
        role: string;
        exists: boolean;
        contains_prose: boolean;
    }>;
    quality_and_style: {
        quality_gate_locked: boolean;
        quality_gate_blocks_next_action: boolean;
        quality_gate_summary: Record<string, unknown>;
        style_advisory_active: boolean;
        style_is_reference_only: boolean;
        style_summary: Record<string, unknown>;
        repair_goals: Record<string, unknown>;
    };
    no_prose_boundary: {
        brief_contains_generated_prose: boolean;
        brief_reads_chapter_draft_text: boolean;
        brief_writes_files: boolean;
        continuation_agent_remains_only_chapter_draft_writer: boolean;
    };
}

export interface RollingContinuationPayloadResponse {
    status: 'success';
    book_id: string;
    generated_at: string;
    chapter_number: number;
    target_file: 'chapter_draft.md';
    route_agent_key: 'continuation_agent';
    file_type: 'chapter';
    write_scope: 'active_file_strict';
    dify_user: string;
    intent: string;
    workbench_state: RollingWorkbenchState;
    chapter_context_pack: any;
    author_writing_brief: RollingAuthorWritingBrief;
    no_prose_boundary: {
        payload_contains_generated_prose: boolean;
        payload_writes_chapter_draft: boolean;
        continuation_agent_remains_only_chapter_draft_writer: boolean;
    };
    plan: any;
}

export async function fetchRollingWorkbenchState(
    bookRef: CoreSessionState['bookRef'],
    options?: { batchSize?: number; reviewGate?: 'open' | 'closed' }
): Promise<RollingStateResponse> {
    const query = new URLSearchParams();
    query.set(bookRef.kind, bookRef.value);
    query.set('batch_size', String(options?.batchSize || 3));
    if (options?.reviewGate === 'closed') {
        query.set('review_gate', 'closed');
    }
    return fetchApi<RollingStateResponse>(`/api/rolling/state?${query.toString()}`);
}

export async function buildRollingContinuationPayload(
    bookRef: CoreSessionState['bookRef'],
    options?: { batchSize?: number; reviewGate?: 'open' | 'closed' }
): Promise<RollingContinuationPayloadResponse> {
    const payload: Record<string, unknown> = {
        [bookRef.kind]: bookRef.value,
        batch_size: options?.batchSize || 3,
    };
    if (options?.reviewGate === 'closed') {
        payload.review_gate = 'closed';
    }
    return fetchApi<RollingContinuationPayloadResponse>('/api/rolling/continuation_payload', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
}
