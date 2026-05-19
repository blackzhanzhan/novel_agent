import { fetchApi } from './client';

export interface DraftResponse {
    status: 'success';
    message?: string;
}

export interface MaterializedChapter {
    number: number;
    title: string;
    file_name: string;
    status: string;
    heading_line?: number;
    end_line?: number;
}

export interface PostConfirmWorldPayload {
    status: 'pending';
    action: 'post_confirm_world_distill';
    route_agent_key: 'world_model';
    active_file: 'status_card.md';
    file_type: 'world_core';
    write_scope: 'world_core';
    dify_user: string;
    intent: string;
    materialized_chapters: Array<{
        number: number;
        title: string;
        file_name: string;
        status: string;
    }>;
    required_writes: string[];
    optional_writes: string[];
    forbidden_writes: string[];
    no_prose_boundary: {
        payload_contains_chapter_prose: boolean;
        world_model_route_must_not_rewrite_prose: boolean;
        review_agent_is_not_responsible: boolean;
    };
}

export interface DraftConfirmResponse extends DraftResponse {
    book_id: string;
    mainline_branch: string;
    merged_branch: string;
    commit_id: string;
    warning?: string;
    draft_branch_deleted?: boolean;
    materialized_chapters?: MaterializedChapter[];
    chapter_canon_commit_id?: string;
    post_confirm_actions?: Array<{
        action: string;
        agent_key: string;
        target_file: string;
        required?: boolean;
    }>;
    post_confirm_payload?: PostConfirmWorldPayload | null;
}

export type DraftWriteScope = 'generic' | 'world_core' | 'active_file_strict';

export interface DraftSyncWrite {
    file_name: string;
    op: 'update' | 'append' | 'prepend';
    content: string;
    base_etag?: string;
}

export interface DraftSyncAllPayload {
    write_scope?: DraftWriteScope;
    active_file?: string;
    message?: string;
    origin?: string;
    writes: DraftSyncWrite[];
}

function getQueryParam(bookRef: { kind: 'book_name' | 'book_id'; value: string }): string {
    return bookRef.kind === 'book_name'
        ? `book_name=${encodeURIComponent(bookRef.value)}`
        : `book_id=${encodeURIComponent(bookRef.value)}`;
}

export async function confirmDraft(
    bookRef: { kind: 'book_name' | 'book_id'; value: string }
): Promise<DraftConfirmResponse> {
    return fetchApi<DraftConfirmResponse>(`/api/draft/confirm?${getQueryParam(bookRef)}`, {
        method: 'POST'
    });
}

export async function rollbackDraft(
    bookRef: { kind: 'book_name' | 'book_id'; value: string },
    commitHash: string
): Promise<void> {
    await fetchApi<DraftResponse>(`/api/draft/rollback?${getQueryParam(bookRef)}`, {
        method: 'POST',
        body: JSON.stringify({
            commit_hash: commitHash
        }),
    });
}
