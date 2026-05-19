import { fetchApi } from './client';

export interface TomatoImportIssue {
    severity: 'block' | 'warn';
    code: string;
    message: string;
    chapter?: string;
    first?: string;
    missing_indices?: number[];
    non_whitespace_chars?: number;
    line_count?: number;
    avg_chars_per_line?: number;
}

export interface TomatoImportQuality {
    can_confirm: boolean;
    risk_level: 'ok' | 'warn' | 'block';
    block_count: number;
    warn_count: number;
    issues: TomatoImportIssue[];
}

export interface TomatoChapterPreview {
    index: number;
    title: string;
    source_file: string;
    target_file: string;
    content_hash: string;
    chars: number;
    non_whitespace_chars: number;
    line_count: number;
    warnings: string[];
}

export interface TomatoImportReport {
    source_dir: string;
    metadata_file: string | null;
    book_name: string;
    chapter_count: number;
    total_non_whitespace_chars: number;
    warnings: Array<Record<string, unknown>>;
    source_files: string[];
}

export interface TomatoImportPreview {
    status: 'success';
    book_name: string;
    source_dir: string;
    metadata: Record<string, string>;
    report: TomatoImportReport;
    quality: TomatoImportQuality;
    chapters: TomatoChapterPreview[];
}

export interface TomatoImportConfirm extends TomatoImportPreview {
    book_id: string;
    saved_count: number;
    written_files: string[];
    force_used: boolean;
    commit_id: string;
}

export interface TomatoImportPayload {
    source_dir: string;
    allowed_root?: string;
    book_id?: string;
    book_name?: string;
    overwrite?: boolean;
    force?: boolean;
}

export async function previewTomatoImport(payload: TomatoImportPayload): Promise<TomatoImportPreview> {
    return fetchApi<TomatoImportPreview>('/books/tomato/preview', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
}

export async function confirmTomatoImport(payload: TomatoImportPayload): Promise<TomatoImportConfirm> {
    return fetchApi<TomatoImportConfirm>('/books/tomato/confirm', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
}

// ---------------------------------------------------------------------------
// Online search & import
// ---------------------------------------------------------------------------

export interface TomatoSearchResult {
    book_id: string;
    book_name: string;
    author: string;
    word_count: number;
    chapter_count: number;
    cover_url: string;
    abstract: string;
}

export interface TomatoBookInfo {
    book_id: string;
    book_name: string;
    author: string;
    abstract: string;
    word_count: number;
    chapter_count: number;
}

export interface TomatoOnlineImportResult {
    status: 'success';
    book_id: string;
    book_name: string;
    author: string;
    chapter_count: number;
    saved_count: number;
    written_files: string[];
    quality: TomatoImportQuality;
    force_used: boolean;
    commit_id: string;
}

export async function searchTomatoNovels(query: string, count = 20): Promise<TomatoSearchResult[]> {
    const res = await fetchApi<{ status: string; count: number; results: TomatoSearchResult[] }>(
        `/books/tomato/search?q=${encodeURIComponent(query)}&count=${count}`,
    );
    return res.results;
}

export async function getTomatoBookInfo(bookId: string): Promise<TomatoBookInfo> {
    return fetchApi<TomatoBookInfo>(`/books/tomato/book_info?book_id=${encodeURIComponent(bookId)}`);
}

export async function onlineImportTomatoNovel(
    bookId: string,
    options?: { overwrite?: boolean; force?: boolean },
): Promise<TomatoOnlineImportResult> {
    return fetchApi<TomatoOnlineImportResult>('/books/tomato/online_import', {
        method: 'POST',
        body: JSON.stringify({ book_id: bookId, overwrite: options?.overwrite ?? false, force: options?.force ?? false }),
    });
}

// ---------------------------------------------------------------------------
// Summary generation progress
// ---------------------------------------------------------------------------

export interface SummaryStatus {
    book_id: string;
    status: 'idle' | 'reading' | 'generating' | 'writing' | 'done' | 'empty' | 'failed' | 'no_chapters';
    batch?: number;
    total_batches?: number;
    chapter_count?: number;
    chars?: number;
    book_name?: string;
    error?: string;
}

export async function fetchSummaryStatus(bookId: string): Promise<SummaryStatus> {
    return fetchApi<SummaryStatus>(`/books/tomato/summary_status?book_id=${encodeURIComponent(bookId)}`);
}

export interface DownloadStatus {
    book_id: string;
    status: 'idle' | 'downloading';
    saved_chapters?: number;
    chapter_total?: number;
    state?: string;
}

export async function fetchDownloadStatus(bookId: string): Promise<DownloadStatus> {
    return fetchApi<DownloadStatus>(`/books/tomato/download_status?book_id=${encodeURIComponent(bookId)}`);
}
