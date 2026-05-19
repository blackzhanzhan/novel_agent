export class ApiError extends Error {
    constructor(
        public status: number,
        public code: string,
        message: string,
        public data?: any
    ) {
        super(message);
        this.name = 'ApiError';
    }
}

const BASE_URL = '';
const DEFAULT_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS || 20000);
const DEDUCTION_TIMEOUT_MS = Number(import.meta.env.VITE_DEDUCTION_TIMEOUT_MS || 90000);
const TOMATO_IMPORT_TIMEOUT_MS = Number(import.meta.env.VITE_TOMATO_IMPORT_TIMEOUT_MS || 600000);

function getTimeoutMs(endpoint: string): number {
    if (endpoint.startsWith('/api/world/deduce')) {
        return DEDUCTION_TIMEOUT_MS;
    }
    if (endpoint.startsWith('/books/tomato/online_import')) {
        return TOMATO_IMPORT_TIMEOUT_MS;
    }
    return DEFAULT_TIMEOUT_MS;
}

export async function fetchApi<T>(endpoint: string, options: RequestInit = {}): Promise<T> {

    const url = `${BASE_URL}${endpoint}`;
    const timeoutMs = getTimeoutMs(endpoint);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    if (options.signal) {
        if (options.signal.aborted) {
            controller.abort();
        } else {
            options.signal.addEventListener('abort', () => controller.abort(), { once: true });
        }
    }

    const headers = {
        'Content-Type': 'application/json',
        ...options.headers,
    };

    let response: Response;
    let data: any;
    try {
        response = await fetch(url, { ...options, headers, signal: controller.signal });
        data = await response.json().catch(() => ({}));
    } catch (error: any) {
        if (error?.name === 'AbortError') {
            throw new ApiError(504, 'REQUEST_TIMEOUT', `Request timeout after ${timeoutMs}ms`);
        }
        throw error;
    } finally {
        clearTimeout(timeoutId);
    }

    if (!response.ok || data.status === 'error') {
        // Non-conflict 409s must pass through with their own code before the generic WRITE_CONFLICT trap.
        if (response.status === 409 && data.code === 'MERGE_CONFLICT') {
            const err = new ApiError(409, 'MERGE_CONFLICT', data.message || 'Merge conflict detected.', data) as ApiError & { conflictedFiles?: string[] };
            err.conflictedFiles = Array.isArray(data.conflicted_files) ? data.conflicted_files : [];
            throw err;
        }
        if (response.status === 409 && data.code === 'WORKTREE_DIRTY') {
            const err = new ApiError(409, 'WORKTREE_DIRTY', data.message || 'Worktree has uncommitted changes.', data) as ApiError & { entries?: unknown[] };
            err.entries = Array.isArray(data.entries) ? data.entries : [];
            throw err;
        }
        // [Task 3.1.2] Protocol-level interception of 409 WRITE_CONFLICT and 428.
        if (response.status === 409 || data.code === 'WRITE_CONFLICT') {
            console.error('[API Interceptor] Detected 409 WRITE_CONFLICT. FSM should route to CONFLICT state.');
            throw new ApiError(409, 'WRITE_CONFLICT', data.message || 'Baseline modified by another process.', data);
        }
        if (response.status === 428 || data.code === 'PRECONDITION_REQUIRED') {
            console.error('[API Interceptor] Detected 428 PRECONDITION_REQUIRED. ETag signature missing.');
            throw new ApiError(428, 'PRECONDITION_REQUIRED', data.message || 'Missing required ETag.', data);
        }

        throw new ApiError(
            response.status,
            data.code || 'UNKNOWN_ERROR',
            data.message || 'An unknown API error occurred',
            data
        );
    }

    return data;
}
