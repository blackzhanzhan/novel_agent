import { fetchApi } from './client';
import { GitGraphCommit } from '../types/store';

interface GitGraphApiRow {
    commit_id: string;
    parent_ids?: string[];
    parent_id?: string | null;
    timestamp: string;
    message: string;
    refs?: string[];
}

interface GitGraphApiResponse {
    status: 'success';
    book_id: string;
    total: number;
    commits: GitGraphApiRow[];
}

export async function fetchGitGraph(
    bookRef: { kind: 'book_name' | 'book_id'; value: string }
): Promise<GitGraphCommit[]> {
    const queryParam = bookRef.kind === 'book_name'
        ? `book_name=${encodeURIComponent(bookRef.value)}`
        : `book_id=${encodeURIComponent(bookRef.value)}`;

    const response = await fetchApi<GitGraphApiResponse>(`/books/git_graph?${queryParam}`);
    return response.commits.map((row) => {
        const parentIds = Array.isArray(row.parent_ids)
            ? row.parent_ids
            : (row.parent_id ? [row.parent_id] : []);
        return {
            commitId: row.commit_id,
            parentIds,
            timestamp: row.timestamp,
            message: row.message,
            refs: Array.isArray(row.refs) ? row.refs : [],
        };
    });
}
