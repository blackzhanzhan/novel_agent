import { fetchApi } from './client';

export type GitDiffScope = 'unstaged' | 'staged' | 'commit';

export interface GitStatusSummary {
    currentBranch: string;
    mainlineBranch: string;
    headCommit: string;
    isDirty: boolean;
    stagedCount: number;
    unstagedCount: number;
    untrackedCount: number;
}

export interface GitBranchRow {
    name: string;
    headCommit: string;
    updatedAt: string;
    headMessage: string;
    isCurrent: boolean;
    isMainline: boolean;
}

export interface GitHistoryCommit {
    commitId: string;
    shortId: string;
    parentIds: string[];
    timestamp: string;
    authorName: string;
    authorEmail: string;
    message: string;
    refs: string[];
}

export interface GitWorkingTreeEntry {
    path: string;
    previousPath: string | null;
    indexStatus: string;
    worktreeStatus: string;
    staged: boolean;
    unstaged: boolean;
    isUntracked: boolean;
}

export interface GitCommitFile {
    path: string;
    previousPath: string | null;
    status: string;
}

export interface GitDiffPayload {
    scope: GitDiffScope;
    path: string;
    oldLabel: string;
    newLabel: string;
    oldText: string;
    newText: string;
    changed: boolean;
    commitId?: string;
}

export interface GitFilePayload {
    path: string;
    source: string;
    content: string;
}

interface GitStatusApiResponse {
    status: 'success';
    book_id: string;
    current_branch: string;
    mainline_branch: string;
    head_commit: string;
    is_dirty: boolean;
    staged_count: number;
    unstaged_count: number;
    untracked_count: number;
}

interface GitBranchesApiResponse {
    status: 'success';
    book_id: string;
    current_branch: string;
    mainline_branch: string;
    branches: Array<{
        name: string;
        head_commit: string;
        updated_at: string;
        head_message: string;
        is_current: boolean;
        is_mainline: boolean;
    }>;
}

interface GitHistoryApiResponse {
    status: 'success';
    book_id: string;
    total: number;
    commits: Array<{
        commit_id: string;
        short_id: string;
        parent_ids: string[];
        timestamp: string;
        author_name: string;
        author_email: string;
        message: string;
        refs: string[];
    }>;
}

interface GitWorkingTreeApiResponse {
    status: 'success';
    book_id: string;
    is_dirty: boolean;
    staged_count: number;
    unstaged_count: number;
    untracked_count: number;
    entries: Array<{
        path: string;
        previous_path?: string | null;
        index_status: string;
        worktree_status: string;
        staged: boolean;
        unstaged: boolean;
        is_untracked: boolean;
    }>;
}

interface GitCommitFilesApiResponse {
    status: 'success';
    book_id: string;
    commit_id: string;
    files: Array<{
        path: string;
        previous_path?: string | null;
        status: string;
    }>;
}

interface GitFileViewApiResponse {
    status: 'success';
    book_id: string;
    path: string;
    source: string;
    content: string;
}

interface GitDiffViewApiResponse {
    status: 'success';
    book_id: string;
    scope: GitDiffScope;
    path: string;
    old_label: string;
    new_label: string;
    old_text: string;
    new_text: string;
    changed: boolean;
}

interface GitCheckoutApiResponse {
    status: 'success';
    book_id: string;
    current_branch: string;
    mainline_branch: string;
    head_commit: string;
}

interface GitHardRollbackApiResponse {
    status: 'success';
    book_id: string;
    current_branch: string;
    head_commit: string;
    target_commit: string;
    delete_other_branches: boolean;
    deleted_branches: string[];
    skipped_branches: Array<{
        branch: string;
        reason: string;
    }>;
}

function getBookQuery(bookRef: { kind: 'book_name' | 'book_id'; value: string }): string {
    return bookRef.kind === 'book_name'
        ? `book_name=${encodeURIComponent(bookRef.value)}`
        : `book_id=${encodeURIComponent(bookRef.value)}`;
}

function mapStatusPayload(payload: {
    current_branch: string;
    mainline_branch: string;
    head_commit: string;
    is_dirty: boolean;
    staged_count: number;
    unstaged_count: number;
    untracked_count: number;
}): GitStatusSummary {
    return {
        currentBranch: payload.current_branch,
        mainlineBranch: payload.mainline_branch,
        headCommit: payload.head_commit,
        isDirty: payload.is_dirty,
        stagedCount: payload.staged_count,
        unstagedCount: payload.unstaged_count,
        untrackedCount: payload.untracked_count,
    };
}

export async function fetchGitStatus(
    bookRef: { kind: 'book_name' | 'book_id'; value: string }
): Promise<GitStatusSummary> {
    const response = await fetchApi<GitStatusApiResponse>(`/books/git_status?${getBookQuery(bookRef)}`);
    return mapStatusPayload(response);
}

export async function fetchGitBranches(
    bookRef: { kind: 'book_name' | 'book_id'; value: string }
): Promise<{ currentBranch: string; mainlineBranch: string; branches: GitBranchRow[] }> {
    const response = await fetchApi<GitBranchesApiResponse>(`/books/git_branches?${getBookQuery(bookRef)}`);
    return {
        currentBranch: response.current_branch,
        mainlineBranch: response.mainline_branch,
        branches: response.branches.map((row) => ({
            name: row.name,
            headCommit: row.head_commit,
            updatedAt: row.updated_at,
            headMessage: row.head_message,
            isCurrent: row.is_current,
            isMainline: row.is_mainline,
        })),
    };
}

export async function fetchGitHistoryList(
    bookRef: { kind: 'book_name' | 'book_id'; value: string },
    limit = 150
): Promise<GitHistoryCommit[]> {
    const response = await fetchApi<GitHistoryApiResponse>(`/books/git_history_list?${getBookQuery(bookRef)}&limit=${limit}`);
    return response.commits.map((row) => ({
        commitId: row.commit_id,
        shortId: row.short_id,
        parentIds: Array.isArray(row.parent_ids) ? row.parent_ids : [],
        timestamp: row.timestamp,
        authorName: row.author_name,
        authorEmail: row.author_email,
        message: row.message,
        refs: Array.isArray(row.refs) ? row.refs : [],
    }));
}

export async function fetchGitWorkingTree(
    bookRef: { kind: 'book_name' | 'book_id'; value: string }
): Promise<{
    isDirty: boolean;
    stagedCount: number;
    unstagedCount: number;
    untrackedCount: number;
    entries: GitWorkingTreeEntry[];
}> {
    const response = await fetchApi<GitWorkingTreeApiResponse>(`/books/git_working_tree?${getBookQuery(bookRef)}`);
    return {
        isDirty: response.is_dirty,
        stagedCount: response.staged_count,
        unstagedCount: response.unstaged_count,
        untrackedCount: response.untracked_count,
        entries: response.entries.map((row) => ({
            path: row.path,
            previousPath: row.previous_path || null,
            indexStatus: row.index_status,
            worktreeStatus: row.worktree_status,
            staged: row.staged,
            unstaged: row.unstaged,
            isUntracked: row.is_untracked,
        })),
    };
}

export async function fetchGitCommitFiles(
    bookRef: { kind: 'book_name' | 'book_id'; value: string },
    commitId: string
): Promise<GitCommitFile[]> {
    const response = await fetchApi<GitCommitFilesApiResponse>(`/books/git_commit_files?${getBookQuery(bookRef)}&commit_id=${encodeURIComponent(commitId)}`);
    return response.files.map((row) => ({
        path: row.path,
        previousPath: row.previous_path || null,
        status: row.status,
    }));
}

export async function fetchGitFileView(
    bookRef: { kind: 'book_name' | 'book_id'; value: string },
    path: string,
    ref?: string
): Promise<GitFilePayload> {
    const refQuery = ref ? `&ref=${encodeURIComponent(ref)}` : '';
    const response = await fetchApi<GitFileViewApiResponse>(`/books/git_file_view?${getBookQuery(bookRef)}&path=${encodeURIComponent(path)}${refQuery}`);
    return {
        path: response.path,
        source: response.source,
        content: response.content,
    };
}

export async function fetchGitDiffView(
    bookRef: { kind: 'book_name' | 'book_id'; value: string },
    payload: { scope: GitDiffScope; path: string; commitId?: string }
): Promise<GitDiffPayload> {
    const commitQuery = payload.commitId ? `&commit_id=${encodeURIComponent(payload.commitId)}` : '';
    const response = await fetchApi<GitDiffViewApiResponse>(
        `/books/git_diff_view?${getBookQuery(bookRef)}&scope=${payload.scope}&path=${encodeURIComponent(payload.path)}${commitQuery}`
    );
    return {
        scope: response.scope,
        path: response.path,
        oldLabel: response.old_label,
        newLabel: response.new_label,
        oldText: response.old_text,
        newText: response.new_text,
        changed: response.changed,
        commitId: payload.commitId,
    };
}

export async function mergeGitBranch(
    bookRef: { kind: 'book_name' | 'book_id'; value: string },
    payload: { sourceBranch: string; noFf?: boolean; message?: string }
): Promise<{
    status: 'success';
    book_id: string;
    current_branch: string;
    source_branch: string;
    merge_type: 'fast_forward' | 'merge_commit' | 'up_to_date';
    commit_id: string;
}> {
    return fetchApi('/books/git_merge', {
        method: 'POST',
        body: JSON.stringify({
            [bookRef.kind]: bookRef.value,
            source_branch: payload.sourceBranch,
            ...(payload.noFf ? { no_ff: true } : {}),
            ...(payload.message ? { message: payload.message } : {}),
        }),
    });
}

export async function checkoutGitBranch(
    bookRef: { kind: 'book_name' | 'book_id'; value: string },
    branchName: string,
    force = false
): Promise<GitCheckoutApiResponse> {
    return fetchApi<GitCheckoutApiResponse>('/books/git_checkout', {
        method: 'POST',
        body: JSON.stringify({
            [bookRef.kind]: bookRef.value,
            branch_name: branchName,
            ...(force ? { force: true } : {}),
        }),
    });
}

export async function createGitBranch(
    bookRef: { kind: 'book_name' | 'book_id'; value: string },
    payload: { branchName: string; fromRef?: string | null; checkout?: boolean }
): Promise<{
    status: 'success';
    book_id: string;
    branch_name: string;
    from_commit: string;
    checked_out: boolean;
    current_branch: string;
    head_commit: string;
}> {
    return fetchApi('/books/git_branch_create', {
        method: 'POST',
        body: JSON.stringify({
            [bookRef.kind]: bookRef.value,
            branch_name: payload.branchName,
            from_ref: payload.fromRef || undefined,
            checkout: payload.checkout ?? true,
        }),
    });
}

export async function hardRollbackGitBranch(
    bookRef: { kind: 'book_name' | 'book_id'; value: string },
    payload: { targetCommit: string; deleteOtherBranches?: boolean }
): Promise<GitHardRollbackApiResponse> {
    return fetchApi<GitHardRollbackApiResponse>('/books/git_hard_rollback', {
        method: 'POST',
        body: JSON.stringify({
            [bookRef.kind]: bookRef.value,
            target_commit: payload.targetCommit,
            delete_other_branches: payload.deleteOtherBranches ?? false,
        }),
    });
}

export async function stageGitFile(
    bookRef: { kind: 'book_name' | 'book_id'; value: string },
    path: string
): Promise<void> {
    await fetchApi('/books/git_stage', {
        method: 'POST',
        body: JSON.stringify({
            [bookRef.kind]: bookRef.value,
            path,
        }),
    });
}

export async function unstageGitFile(
    bookRef: { kind: 'book_name' | 'book_id'; value: string },
    path: string
): Promise<void> {
    await fetchApi('/books/git_unstage', {
        method: 'POST',
        body: JSON.stringify({
            [bookRef.kind]: bookRef.value,
            path,
        }),
    });
}

export async function stageAllGitFiles(
    bookRef: { kind: 'book_name' | 'book_id'; value: string }
): Promise<void> {
    await fetchApi('/books/git_stage_all', {
        method: 'POST',
        body: JSON.stringify({
            [bookRef.kind]: bookRef.value,
        }),
    });
}

export async function commitGitStagedFiles(
    bookRef: { kind: 'book_name' | 'book_id'; value: string },
    message: string
): Promise<{ status: 'success'; commit_id: string; current_branch: string; files: string[] }> {
    return fetchApi('/books/git_commit', {
        method: 'POST',
        body: JSON.stringify({
            [bookRef.kind]: bookRef.value,
            message,
        }),
    });
}
