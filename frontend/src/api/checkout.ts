import { fetchApi, ApiError } from './client';
import { HotFileItem, RepoIntegrity } from '../types/store';

interface RepoIntegrityApiPayload {
    book_id: string;
    exists: boolean;
    repo_exists: boolean;
    head_exists: boolean;
    head_commit: string | null;
    missing_core_files: string[];
    missing_directories: string[];
    untracked_layout_files: string[];
    problem_codes: string[];
    needs_repair: boolean;
}

export interface GetFileResponse {
    status: 'success';
    book_id: string;
    file_name: string;
    content: string;
    etag: string;
    exists: boolean;
    virtual: boolean;
    integrity: RepoIntegrityApiPayload;
}

interface UpdateFileResponse {
    status: 'success';
    book_id: string;
    file_name: string;
    etag: string;
    commit_id?: string;
    message?: string;
}

interface ListHotFilesResponse {
    status: 'success';
    book_id: string;
    integrity: RepoIntegrityApiPayload;
    files: Array<{
        file_name: string;
        file_type: HotFileItem['fileType'];
        label?: string;
        exists?: boolean;
        virtual?: boolean;
    }>;
}

interface RepoIntegrityResponse {
    status: 'success';
    book_id: string;
    integrity: RepoIntegrityApiPayload;
}

interface RepairLayoutResponse {
    status: 'success';
    book_id: string;
    head_commit: string | null;
    repair_commits: string[];
    integrity: RepoIntegrityApiPayload;
}

function getBookQuery(bookRef: { kind: 'book_name' | 'book_id'; value: string }): string {
    return bookRef.kind === 'book_name'
        ? `book_name=${encodeURIComponent(bookRef.value)}`
        : `book_id=${encodeURIComponent(bookRef.value)}`;
}

function mapIntegrity(payload: RepoIntegrityApiPayload): RepoIntegrity {
    return {
        bookId: payload.book_id,
        exists: payload.exists,
        repoExists: payload.repo_exists,
        headExists: payload.head_exists,
        headCommit: payload.head_commit,
        missingCoreFiles: Array.isArray(payload.missing_core_files) ? payload.missing_core_files : [],
        missingDirectories: Array.isArray(payload.missing_directories) ? payload.missing_directories : [],
        untrackedLayoutFiles: Array.isArray(payload.untracked_layout_files) ? payload.untracked_layout_files : [],
        problemCodes: Array.isArray(payload.problem_codes) ? payload.problem_codes : [],
        needsRepair: Boolean(payload.needs_repair),
    };
}

export async function fetchMainlineFile(
    bookRef: { kind: 'book_name' | 'book_id'; value: string },
    fileName: string
): Promise<{ content: string; etag: string; exists: boolean; virtual: boolean; integrity: RepoIntegrity }> {
    try {
        const response = await fetchApi<GetFileResponse>(`/books/get_file?${getBookQuery(bookRef)}&file_name=${encodeURIComponent(fileName)}`);

        if (!response.etag) {
            throw new ApiError(
                428,
                'PRECONDITION_REQUIRED',
                'Server returned payload without an ETag. Baseline lock cannot be established.'
            );
        }

        return {
            content: response.content,
            etag: response.etag,
            exists: Boolean(response.exists),
            virtual: Boolean(response.virtual),
            integrity: mapIntegrity(response.integrity),
        };
    } catch (error) {
        if (error instanceof ApiError && error.status === 428) {
            console.error('[Protocol Enforcement] 428 PRECONDITION_REQUIRED intercepted:', error.message);
        }
        throw error;
    }
}

export async function fetchHotFiles(
    bookRef: { kind: 'book_name' | 'book_id'; value: string }
): Promise<{ files: HotFileItem[]; integrity: RepoIntegrity }> {
    const response = await fetchApi<ListHotFilesResponse>(`/books/list_hot_files?${getBookQuery(bookRef)}`);
    return {
        integrity: mapIntegrity(response.integrity),
        files: response.files.map((row) => ({
            fileName: row.file_name,
            fileType: row.file_type,
            label: row.label || row.file_name,
            exists: row.exists,
            virtual: row.virtual,
        })),
    };
}

export async function fetchRepoIntegrity(
    bookRef: { kind: 'book_name' | 'book_id'; value: string }
): Promise<RepoIntegrity> {
    const response = await fetchApi<RepoIntegrityResponse>(`/books/repo_integrity?${getBookQuery(bookRef)}`);
    return mapIntegrity(response.integrity);
}

export async function repairBookLayout(
    bookRef: { kind: 'book_name' | 'book_id'; value: string }
): Promise<{ integrity: RepoIntegrity; headCommit: string | null; repairCommits: string[] }> {
    const payload: Record<string, string> = bookRef.kind === 'book_name'
        ? { book_name: bookRef.value }
        : { book_id: bookRef.value };
    const response = await fetchApi<RepairLayoutResponse>('/books/repair_layout', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
    return {
        integrity: mapIntegrity(response.integrity),
        headCommit: response.head_commit || null,
        repairCommits: Array.isArray(response.repair_commits) ? response.repair_commits : [],
    };
}

export async function updateMainlineFile(
    bookRef: { kind: 'book_name' | 'book_id'; value: string },
    fileName: string,
    content: string,
    baseEtag: string
): Promise<{ etag: string; commitId: string | null; message: string | null }> {
    const payload: Record<string, any> = {
        file_name: fileName,
        content,
        base_etag: baseEtag,
        origin: 'user',
        message: `live edit ${fileName}`,
    };
    if (bookRef.kind === 'book_name') {
        payload.book_name = bookRef.value;
    } else {
        payload.book_id = bookRef.value;
    }

    const response = await fetchApi<UpdateFileResponse>('/books/update_file', {
        method: 'POST',
        body: JSON.stringify(payload),
    });

    return {
        etag: response.etag,
        commitId: response.commit_id || null,
        message: response.message || null,
    };
}
