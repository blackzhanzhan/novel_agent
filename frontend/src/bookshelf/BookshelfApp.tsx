import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchApi, ApiError } from '../api/client';
import { BookListItem, deleteBook } from '../api/library';
import {
    searchTomatoNovels,
    onlineImportTomatoNovel,
    getTomatoBookInfo,
    fetchSummaryStatus,
    fetchDownloadStatus,
    TomatoSearchResult,
    TomatoBookInfo,
    SummaryStatus,
    DownloadStatus,
} from '../api/tomatoImport';

type PageState = 'loading' | 'empty' | 'bookshelf' | 'importing';

function isSummaryBusyStatus(status?: SummaryStatus['status']): boolean {
    return status === 'reading' || status === 'generating' || status === 'writing';
}

export function BookshelfApp() {
    const [pageState, setPageState] = useState<PageState>('loading');
    const [books, setBooks] = useState<BookListItem[]>([]);
    const [toast, setToast] = useState<{ text: string; ts: number } | null>(null);

    // Online search state
    const [searchQuery, setSearchQuery] = useState('');
    const [directBookId, setDirectBookId] = useState('');
    const [directLookupPending, setDirectLookupPending] = useState(false);
    const [searchResults, setSearchResults] = useState<TomatoSearchResult[]>([]);
    const [searching, setSearching] = useState(false);
    const [searchError, setSearchError] = useState<string | null>(null);
    const [selectedBook, setSelectedBook] = useState<TomatoBookInfo | null>(null);
    const [downloading, setDownloading] = useState(false);
    const [downloadError, setDownloadError] = useState<string | null>(null);
    const [deleteTarget, setDeleteTarget] = useState<BookListItem | null>(null);
    const [deleting, setDeleting] = useState(false);
    const [summaryStatus, setSummaryStatus] = useState<SummaryStatus | null>(null);
    const [downloadStatus, setDownloadStatus] = useState<DownloadStatus | null>(null);
    const summaryPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const downloadPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const summaryBusy = isSummaryBusyStatus(summaryStatus?.status);

    const refreshBooks = useCallback(async (options?: { updatePageState?: boolean }): Promise<BookListItem[]> => {
        const updatePageState = options?.updatePageState ?? true;
        try {
            const list = await fetchApi<{ status: string; total: number; books: BookListItem[] }>('/books/list');
            setBooks(list.books);
            if (updatePageState) {
                setPageState(list.books.length === 0 ? 'empty' : 'bookshelf');
            }
            return list.books;
        } catch {
            if (updatePageState) {
                setPageState('empty');
            }
            return [];
        }
    }, []);

    const handleOpenImport = () => {
        if (summaryBusy) return;
        setSearchQuery('');
        setDirectBookId('');
        setSearchResults([]);
        setSearchError(null);
        setSelectedBook(null);
        setDownloading(false);
        setDownloadError(null);
        setPageState('importing');
    };

    const handleCloseImport = () => {
        if (summaryBusy) return;
        setPageState(books.length === 0 ? 'empty' : 'bookshelf');
    };

    const handleEnterBook = (bookId: string) => {
        if (summaryBusy) return;
        const url = new URL(window.location.origin + '/index.html');
        url.searchParams.set('book_id', bookId);
        window.location.href = url.toString();
    };

    const handleSearch = async () => {
        if (summaryBusy) return;
        const q = searchQuery.trim();
        if (!q) return;
        setSearching(true);
        setSearchError(null);
        setSearchResults([]);
        setSelectedBook(null);
        try {
            const results = await searchTomatoNovels(q);
            setSearchResults(results);
        } catch (err) {
            setSearchError(err instanceof ApiError ? err.message : '搜索失败');
        } finally {
            setSearching(false);
        }
    };

    const handleSelectBook = async (bookId: string) => {
        if (summaryBusy) return;
        setSelectedBook(null);
        setDownloadError(null);
        // Use search result data directly (has correct word_count from exe)
        const searchHit = searchResults.find((r) => r.book_id === bookId);
        if (searchHit) {
            setSelectedBook({
                book_id: searchHit.book_id,
                book_name: searchHit.book_name,
                author: searchHit.author,
                abstract: searchHit.abstract,
                word_count: searchHit.word_count,
                chapter_count: searchHit.chapter_count,
            });
            return;
        }
        // Fallback for non-search paths (direct book_id lookup)
        try {
            const info = await getTomatoBookInfo(bookId);
            setSelectedBook(info);
        } catch (err) {
            setDownloadError(err instanceof ApiError ? err.message : '获取书籍信息失败');
        }
    };

    const handleDirectBookLookup = async () => {
        if (summaryBusy) return;
        const bookId = directBookId.trim();
        if (!bookId) return;
        setDirectLookupPending(true);
        setSelectedBook(null);
        setDownloadError(null);
        try {
            const info = await getTomatoBookInfo(bookId);
            setSearchError(null);
            setSearchResults([]);
            setSelectedBook(info);
        } catch (err) {
            setDownloadError(err instanceof ApiError ? err.message : '获取书籍信息失败');
        } finally {
            setDirectLookupPending(false);
        }
    };

    const startSummaryPoll = useCallback((bookId: string, bookName?: string) => {
        setSummaryStatus({ book_id: bookId, book_name: bookName, status: 'reading' });
        if (summaryPollRef.current) clearInterval(summaryPollRef.current);
        const poll = async () => {
            try {
                const s = await fetchSummaryStatus(bookId);
                setSummaryStatus(s);
                if (s.status === 'done' || s.status === 'failed' || s.status === 'empty' || s.status === 'no_chapters') {
                    if (summaryPollRef.current) clearInterval(summaryPollRef.current);
                    summaryPollRef.current = null;
                    if (s.status === 'done') {
                        setToast({ text: `摘要已生成（${(s.chars ?? 0).toLocaleString()} 字）`, ts: Date.now() });
                    }
                }
            } catch {
                // ignore poll errors
            }
        };
        void poll();
        summaryPollRef.current = setInterval(() => {
            void poll();
        }, 3000);
    }, []);

    useEffect(() => {
        let cancelled = false;
        const loadBooksAndResumeSummary = async () => {
            const list = await refreshBooks();
            if (cancelled || summaryPollRef.current) return;
            for (const book of list) {
                try {
                    const status = await fetchSummaryStatus(book.book_id);
                    if (!isSummaryBusyStatus(status.status)) continue;
                    if (cancelled) return;
                    startSummaryPoll(book.book_id, status.book_name ?? book.book_name);
                    return;
                } catch {
                    // ignore cold-start summary status probes
                }
            }
        };
        void loadBooksAndResumeSummary();
        return () => {
            cancelled = true;
        };
    }, [refreshBooks, startSummaryPoll]);

    const startDownloadPoll = (bookId: string) => {
        setDownloadStatus({ book_id: bookId, status: 'idle' });
        if (downloadPollRef.current) clearInterval(downloadPollRef.current);
        downloadPollRef.current = setInterval(async () => {
            try {
                const s = await fetchDownloadStatus(bookId);
                setDownloadStatus(s);
                if (s.status !== 'downloading') {
                    if (downloadPollRef.current) clearInterval(downloadPollRef.current);
                    downloadPollRef.current = null;
                    setDownloadStatus(null);
                }
            } catch {
                // ignore poll errors
            }
        }, 2000);
    };

    const summaryLabel = (s: SummaryStatus | null): string => {
        if (!s) return '';
        switch (s.status) {
            case 'reading': return '正在读取章节…';
            case 'generating': return `正在生成摘要（${s.batch ?? 0}/${s.total_batches ?? '?'} 批）`;
            case 'writing': return '正在写入摘要…';
            case 'done': return '';
            case 'failed': return '摘要生成失败';
            case 'empty': return '摘要为空';
            case 'no_chapters': return '无章节可归档';
            default: return '';
        }
    };

    const handleOnlineImport = async () => {
        if (!selectedBook || summaryBusy) return;
        setDownloading(true);
        setDownloadError(null);
        startDownloadPoll(selectedBook.book_id);
        try {
            const result = await onlineImportTomatoNovel(selectedBook.book_id, { overwrite: true, force: true });
            const refreshedBooks = await refreshBooks({ updatePageState: false });
            const importedBook = { book_id: result.book_id, book_name: result.book_name };
            const nextBooks = refreshedBooks.some((book) => book.book_id === result.book_id)
                ? refreshedBooks
                : [importedBook, ...refreshedBooks];
            setBooks(nextBooks);
            setPageState('bookshelf');
            setToast({ text: `已导入《${result.book_name}》，正在生成摘要`, ts: Date.now() });
            startSummaryPoll(result.book_id, result.book_name);
        } catch (err) {
            setDownloadError(err instanceof ApiError ? err.message : '在线导入失败');
        } finally {
            setDownloading(false);
            if (downloadPollRef.current) clearInterval(downloadPollRef.current);
            downloadPollRef.current = null;
            setDownloadStatus(null);
        }
    };

    const handleDeleteBook = async () => {
        if (!deleteTarget || summaryBusy) return;
        setDeleting(true);
        try {
            const result = await deleteBook(deleteTarget.book_id);
            const toastText = result.cleanup_pending
                ? `已从书架移除「${deleteTarget.book_name}」，后台会继续清理被占用的目录`
                : `已删除「${deleteTarget.book_name}」`;
            setToast({ text: toastText, ts: Date.now() });
            setDeleteTarget(null);
            await refreshBooks();
        } catch (err) {
            setToast({ text: err instanceof ApiError ? err.message : '删除失败', ts: Date.now() });
        } finally {
            setDeleting(false);
        }
    };

    // Auto-dismiss toast
    useEffect(() => {
        if (!toast) return;
        const timer = setTimeout(() => setToast(null), 4000);
        return () => clearTimeout(timer);
    }, [toast?.ts]);

    // Cleanup polls on unmount
    useEffect(() => {
        return () => {
            if (summaryPollRef.current) clearInterval(summaryPollRef.current);
            if (downloadPollRef.current) clearInterval(downloadPollRef.current);
        };
    }, []);

    return (
        <div aria-busy={summaryBusy} className="flex h-screen w-screen flex-col items-center justify-center overflow-hidden text-[var(--color-dark-text-main)]">
            {/* Ambient glow */}
            <div className="pointer-events-none absolute inset-0 overflow-hidden">
                <div className="absolute left-[18%] top-0 h-[38vh] w-[42vw] rounded-full bg-[radial-gradient(circle,rgba(255,255,255,0.06)_0%,rgba(255,255,255,0)_72%)] opacity-55 blur-3xl" />
                <div className="absolute bottom-[-18vh] right-[14%] h-[46vh] w-[34vw] rounded-full bg-[radial-gradient(circle,rgba(255,255,255,0.035)_0%,rgba(255,255,255,0)_74%)] opacity-70 blur-3xl" />
            </div>

            <div className="relative z-10 flex w-full max-w-4xl flex-col items-center gap-8 px-8">
                {/* Logo + Title */}
                <div className="flex items-center gap-4">
                    <div className="flex h-12 w-12 items-center justify-center rounded-[14px] bg-[rgba(115,134,255,0.14)] text-[var(--color-dark-text-main)] shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
                        <svg viewBox="0 0 20 20" fill="none" className="h-6 w-6" stroke="currentColor" strokeWidth="1.7">
                            <path d="M10 2.8 16.2 6v8L10 17.2 3.8 14V6 10" />
                            <path d="M10 2.8v6.1L3.8 10" />
                            <path d="M16.2 6 10 8.9" />
                        </svg>
                    </div>
                    <div>
                        <div className="text-2xl font-bold text-[var(--color-dark-text-main)]">创作工作台</div>
                        <div className="text-sm text-[var(--color-dark-text-muted)]">AI 辅助小说创作平台</div>
                    </div>
                </div>

                {/* Loading state */}
                {pageState === 'loading' && (
                    <div className="text-sm text-[var(--color-dark-text-faint)]">加载中…</div>
                )}

                {/* Empty state */}
                {pageState === 'empty' && (
                    <div className="flex flex-col items-center gap-6 rounded-[20px] border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.02)] px-12 py-10">
                        <div className="text-center">
                            <div className="text-lg font-semibold text-[var(--color-dark-text-main)]">欢迎使用创作工作台</div>
                            <div className="mt-2 max-w-sm text-sm text-[var(--color-dark-text-muted)]">
                                当前仓库中还没有书籍。搜索并导入一本番茄小说，即可开始 AI 辅助创作。
                            </div>
                        </div>
                        <button
                            type="button"
                            onClick={handleOpenImport}
                            disabled={summaryBusy}
                            className="rounded-[10px] border border-[rgba(115,134,255,0.32)] bg-[rgba(115,134,255,0.08)] px-5 py-2.5 text-sm font-semibold text-[var(--color-dark-text-main)] transition-colors hover:bg-[rgba(115,134,255,0.16)] disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            导入第一本书
                        </button>
                    </div>
                )}

                {/* Bookshelf */}
                {(pageState === 'bookshelf' || pageState === 'importing') && (
                    <>
                        <div className="text-center">
                            <div className="text-xl font-bold text-[var(--color-dark-text-main)]">书架</div>
                            <div className="mt-1 text-sm text-[var(--color-dark-text-muted)]">选择一本书进入工作台，或导入新书</div>
                        </div>
                        <div className="flex max-w-3xl flex-wrap justify-center gap-4">
                            {books.map((book) => (
                                <div
                                    key={book.book_id}
                                    className="group relative flex w-60 flex-col items-start gap-2 rounded-[14px] border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.02)] p-4 transition-colors hover:border-[rgba(115,134,255,0.32)] hover:bg-[rgba(115,134,255,0.06)]"
                                >
                                    <button
                                        type="button"
                                        onClick={() => handleEnterBook(book.book_id)}
                                        disabled={summaryBusy}
                                        className="flex w-full flex-col items-start gap-2 text-left disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                        <div className="flex h-10 w-10 items-center justify-center rounded-[10px] bg-[rgba(115,134,255,0.12)] text-[var(--color-dark-text-main)]">
                                            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5">
                                                <path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H14l3 3v10.5a2.5 2.5 0 0 1-2.5 2.5h-8A2.5 2.5 0 0 1 4 15.5v-11Z" />
                                                <path d="M14 2v3.5h3M7 9h6M7 12h4" />
                                            </svg>
                                        </div>
                                        <div className="min-w-0 w-full">
                                            <div className="truncate text-[13px] font-semibold text-[var(--color-dark-text-main)] group-hover:text-[rgba(115,134,255,1)]">
                                                {book.book_name}
                                            </div>
                                            <div className="truncate text-[11px] text-[var(--color-dark-text-faint)]">
                                                {book.book_id}
                                            </div>
                                        </div>
                                    </button>
                                    <button
                                        type="button"
                                        onClick={(e) => { e.stopPropagation(); setDeleteTarget(book); }}
                                        disabled={summaryBusy}
                                        className="absolute right-2 top-2 rounded-lg p-1.5 text-[var(--color-dark-text-faint)] opacity-0 transition-all hover:bg-[rgba(255,80,80,0.12)] hover:text-[#ff6b6b] disabled:cursor-not-allowed disabled:opacity-40 group-hover:opacity-100"
                                        title="删除"
                                    >
                                        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
                                            <path d="M6 6l8 8M14 6l-8 8" />
                                        </svg>
                                    </button>
                                </div>
                            ))}
                        </div>
                        <button
                            type="button"
                            onClick={handleOpenImport}
                            disabled={summaryBusy}
                            className="rounded-[10px] border border-[rgba(115,134,255,0.32)] bg-[rgba(115,134,255,0.08)] px-5 py-2.5 text-sm font-semibold text-[var(--color-dark-text-main)] transition-colors hover:bg-[rgba(115,134,255,0.16)] disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            导入新书
                        </button>
                    </>
                )}
            </div>

            {/* Import dialog */}
            {pageState === 'importing' && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/58 px-4 py-6 backdrop-blur-sm">
                    <div role="dialog" aria-modal="true" className="flex max-h-full w-full max-w-3xl flex-col overflow-hidden rounded-[16px] border border-[rgba(255,255,255,0.08)] bg-[#111318] shadow-[0_24px_80px_rgba(0,0,0,0.5)]">
                        <div className="flex items-start justify-between gap-4 border-b border-[rgba(255,255,255,0.06)] px-5 py-4">
                            <div className="min-w-0">
                                <div className="text-[11px] font-mono tracking-[0.16em] text-[var(--color-dark-text-faint)]">BOOK IMPORT</div>
                                <h2 className="mt-1 text-lg font-semibold text-[var(--color-dark-text-main)]">番茄小说在线导入</h2>
                                <p className="mt-1 text-xs leading-5 text-[var(--color-dark-text-muted)]">
                                    搜索番茄小说在线书库，一键下载导入到工作台。
                                </p>
                            </div>
                            <button
                                type="button"
                                onClick={handleCloseImport}
                                disabled={summaryBusy}
                                className="rounded-[10px] border border-[rgba(255,255,255,0.06)] px-3 py-2 text-xs text-[var(--color-dark-text-muted)] hover:text-[var(--color-dark-text-main)] disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                关闭
                            </button>
                        </div>

                        <div className="flex-1 overflow-y-auto p-5">
                            <div className="space-y-4">
                                {/* Search bar */}
                                <div className="flex gap-2">
                                    <input
                                        value={searchQuery}
                                        onChange={(e) => setSearchQuery(e.target.value)}
                                        onKeyDown={(e) => { if (e.key === 'Enter') void handleSearch(); }}
                                        disabled={summaryBusy}
                                        placeholder="搜索书名或作者…"
                                        className="flex-1 rounded-[10px] border border-[rgba(255,255,255,0.07)] bg-[#171a20] px-3 py-2 text-sm text-[var(--color-dark-text-main)] outline-none focus:border-[rgba(115,134,255,0.55)]"
                                    />
                                    <button
                                        type="button"
                                        disabled={summaryBusy || searching || !searchQuery.trim()}
                                        onClick={() => { void handleSearch(); }}
                                        className="rounded-[10px] border border-[rgba(115,134,255,0.45)] bg-[rgba(115,134,255,0.14)] px-4 py-2 text-sm font-semibold text-[#eef1ff] disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                        {searching ? '搜索中…' : '搜索'}
                                    </button>
                                </div>

                                {searchError && (
                                    <div className="rounded-[10px] border border-[#7f3434] bg-[#2a1114] px-3 py-2 text-xs leading-5 text-[#ffd7d7]">
                                        {searchError}
                                    </div>
                                )}

                                <div className="space-y-2 rounded-[12px] border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.015)] p-3">
                                    <div className="text-[11px] font-medium text-[var(--color-dark-text-muted)]">按 book_id 直接导入</div>
                                    <div className="flex gap-2">
                                        <input
                                            aria-label="番茄 book_id"
                                            value={directBookId}
                                            onChange={(e) => setDirectBookId(e.target.value)}
                                            onKeyDown={(e) => { if (e.key === 'Enter') void handleDirectBookLookup(); }}
                                            disabled={summaryBusy}
                                            placeholder="7539874853881383998"
                                            className="flex-1 rounded-[10px] border border-[rgba(255,255,255,0.07)] bg-[#171a20] px-3 py-2 text-sm text-[var(--color-dark-text-main)] outline-none focus:border-[rgba(115,134,255,0.55)]"
                                        />
                                        <button
                                            type="button"
                                            disabled={summaryBusy || directLookupPending || downloading || !directBookId.trim()}
                                            onClick={() => { void handleDirectBookLookup(); }}
                                            className="rounded-[10px] border border-[rgba(115,134,255,0.45)] bg-[rgba(115,134,255,0.14)] px-4 py-2 text-sm font-semibold text-[#eef1ff] disabled:cursor-not-allowed disabled:opacity-50"
                                        >
                                            {directLookupPending ? '读取中…' : '读取书籍'}
                                        </button>
                                    </div>
                                    <div className="text-[11px] leading-5 text-[var(--color-dark-text-faint)]">
                                        搜索受限时，粘贴 fanqienovel.com/page/&lt;book_id&gt; 中的数字 ID，先读取详情，再一键导入。
                                    </div>
                                </div>

                                {/* Empty state */}
                                {searchResults.length === 0 && !searching && !searchError && (
                                    <div className="flex items-center justify-center py-12 text-sm text-[var(--color-dark-text-faint)]">
                                        输入书名或作者搜索番茄小说在线书库。
                                    </div>
                                )}

                                {/* Search results */}
                                {searchResults.length > 0 && (
                                    <div className="space-y-2">
                                        <div className="text-[11px] font-medium text-[var(--color-dark-text-muted)]">
                                            搜索结果（{searchResults.length}）
                                        </div>
                                        <div className="max-h-[360px] overflow-y-auto rounded-[12px] border border-[rgba(255,255,255,0.06)]">
                                            {searchResults.map((result) => (
                                                <button
                                                    key={result.book_id}
                                                    type="button"
                                                    onClick={() => { void handleSelectBook(result.book_id); }}
                                                    disabled={summaryBusy}
                                                    className={`w-full text-left px-3 py-3 border-b border-[rgba(255,255,255,0.045)] last:border-b-0 transition-colors ${
                                                        selectedBook?.book_id === result.book_id
                                                            ? 'bg-[rgba(115,134,255,0.1)]'
                                                            : 'hover:bg-[rgba(255,255,255,0.02)]'
                                                    }`}
                                                >
                                                    <div className="min-w-0">
                                                        <div className="truncate text-sm font-semibold text-[var(--color-dark-text-main)]">
                                                            {result.book_name}
                                                        </div>
                                                        <div className="mt-1 text-xs text-[var(--color-dark-text-muted)]">
                                                            {result.author} · {result.chapter_count} 章 · {(result.word_count / 10000).toFixed(1)} 万字
                                                        </div>
                                                    </div>
                                                    {result.abstract && (
                                                        <div className="mt-1.5 line-clamp-2 text-[11px] leading-4 text-[var(--color-dark-text-faint)]">
                                                            {result.abstract}
                                                        </div>
                                                    )}
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {/* Selected book info + import */}
                                {selectedBook && (
                                    <div className="space-y-3 rounded-[12px] border border-[rgba(115,134,255,0.18)] bg-[rgba(115,134,255,0.04)] p-4">
                                        <div className="text-sm font-semibold text-[var(--color-dark-text-main)]">
                                            {selectedBook.book_name}
                                        </div>
                                        <div className="flex gap-4 text-xs text-[var(--color-dark-text-muted)]">
                                            <span>{selectedBook.author}</span>
                                            <span>{selectedBook.chapter_count} 章</span>
                                            <span>{(selectedBook.word_count / 10000).toFixed(1)} 万字</span>
                                        </div>
                                        <div className="flex flex-col gap-2">
                                            <button
                                                type="button"
                                                disabled={summaryBusy || downloading}
                                                onClick={() => { void handleOnlineImport(); }}
                                                className="rounded-[10px] border border-[rgba(71,197,129,0.42)] bg-[rgba(71,197,129,0.13)] px-4 py-2 text-sm font-semibold text-[#d9ffe9] disabled:cursor-not-allowed disabled:opacity-50"
                                            >
                                                {downloading ? '导入中…' : '一键导入'}
                                            </button>
                                            {downloading && downloadStatus && downloadStatus.status === 'downloading' && (
                                                <div className="flex items-center gap-3">
                                                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[rgba(255,255,255,0.06)]">
                                                        <div
                                                            className="h-full rounded-full bg-[rgba(71,197,129,0.7)] transition-all duration-500"
                                                            style={{ width: downloadStatus.chapter_total ? `${((downloadStatus.saved_chapters ?? 0) / downloadStatus.chapter_total) * 100}%` : '0%' }}
                                                        />
                                                    </div>
                                                    <span className="shrink-0 text-xs text-[var(--color-dark-text-muted)]">
                                                        {downloadStatus.saved_chapters ?? 0}/{downloadStatus.chapter_total ?? '?'} 章
                                                    </span>
                                                </div>
                                            )}
                                        </div>
                                        {downloadError && (
                                            <div className="rounded-[10px] border border-[#7f3434] bg-[#2a1114] px-3 py-2 text-xs leading-5 text-[#ffd7d7]">
                                                {downloadError}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Delete confirmation */}
            {deleteTarget && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/58 px-4 backdrop-blur-sm">
                    <div role="dialog" aria-modal="true" className="w-full max-w-sm rounded-[16px] border border-[rgba(255,255,255,0.08)] bg-[#111318] p-6 shadow-[0_24px_80px_rgba(0,0,0,0.5)]">
                        <div className="text-base font-semibold text-[var(--color-dark-text-main)]">确认删除</div>
                        <div className="mt-2 text-sm text-[var(--color-dark-text-muted)]">
                            确定要删除「{deleteTarget.book_name}」吗？此操作不可撤销。
                        </div>
                        <div className="mt-5 flex justify-end gap-2">
                            <button
                                type="button"
                                onClick={() => setDeleteTarget(null)}
                                disabled={summaryBusy || deleting}
                                className="rounded-[10px] border border-[rgba(255,255,255,0.06)] px-4 py-2 text-sm text-[var(--color-dark-text-muted)] hover:text-[var(--color-dark-text-main)] disabled:opacity-50"
                            >
                                取消
                            </button>
                            <button
                                type="button"
                                onClick={() => { void handleDeleteBook(); }}
                                disabled={summaryBusy || deleting}
                                className="rounded-[10px] border border-[rgba(255,80,80,0.45)] bg-[rgba(255,80,80,0.14)] px-4 py-2 text-sm font-semibold text-[#ffd7d7] disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                {deleting ? '删除中…' : '删除'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Summary interaction lock */}
            {summaryBusy && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/68 px-4 backdrop-blur-sm">
                    <div role="status" aria-live="polite" className="w-full max-w-md rounded-[16px] border border-[rgba(115,134,255,0.22)] bg-[#111318] px-6 py-5 text-center shadow-[0_24px_80px_rgba(0,0,0,0.55)]">
                        <div className="mx-auto h-9 w-9 animate-spin rounded-full border-2 border-[rgba(115,134,255,0.25)] border-t-[rgba(115,134,255,1)]" />
                        <div className="mt-4 text-base font-semibold text-[var(--color-dark-text-main)]">正在生成摘要</div>
                        <div className="mt-2 text-sm leading-6 text-[var(--color-dark-text-muted)]">
                            {summaryStatus?.book_name ? `《${summaryStatus.book_name}》` : '当前书籍'}正在整理章节信息。生成完成前暂时不能进入工作台或继续操作书架。
                        </div>
                        <div className="mt-4 flex items-center justify-center gap-3">
                            <span className="text-xs text-[var(--color-dark-text-muted)]">{summaryLabel(summaryStatus)}</span>
                            {summaryStatus?.status === 'generating' && summaryStatus?.total_batches && summaryStatus.total_batches > 0 && (
                                <div className="h-1.5 w-28 overflow-hidden rounded-full bg-[rgba(255,255,255,0.06)]">
                                    <div
                                        className="h-full rounded-full bg-[rgba(115,134,255,0.78)] transition-all duration-500"
                                        style={{ width: `${((summaryStatus?.batch ?? 0) / summaryStatus.total_batches) * 100}%` }}
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* Summary progress */}
            {summaryStatus && !summaryBusy && summaryLabel(summaryStatus) && (
                <div className="fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-[12px] border border-[rgba(115,134,255,0.18)] bg-[#1a1d24] px-5 py-3 shadow-[0_8px_32px_rgba(0,0,0,0.4)]">
                    {(summaryStatus.status === 'reading' || summaryStatus.status === 'generating' || summaryStatus.status === 'writing') && (
                        <div className="h-4 w-4 animate-spin rounded-full border-2 border-[rgba(115,134,255,0.3)] border-t-[rgba(115,134,255,1)]" />
                    )}
                    <span className="text-sm text-[var(--color-dark-text-main)]">{summaryLabel(summaryStatus)}</span>
                    {summaryStatus.status === 'generating' && summaryStatus.total_batches && summaryStatus.total_batches > 0 && (
                        <div className="h-1.5 w-24 overflow-hidden rounded-full bg-[rgba(255,255,255,0.06)]">
                            <div
                                className="h-full rounded-full bg-[rgba(115,134,255,0.7)] transition-all duration-500"
                                style={{ width: `${((summaryStatus.batch ?? 0) / summaryStatus.total_batches) * 100}%` }}
                            />
                        </div>
                    )}
                    {summaryStatus.status === 'failed' && (
                        <button
                            type="button"
                            onClick={() => setSummaryStatus(null)}
                            className="text-xs text-[var(--color-dark-text-faint)] hover:text-[var(--color-dark-text-main)]"
                        >
                            关闭
                        </button>
                    )}
                </div>
            )}

            {/* Toast */}
            {toast && (
                <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-[12px] border border-[rgba(255,255,255,0.08)] bg-[#1a1d24] px-5 py-3 text-sm text-[var(--color-dark-text-main)] shadow-[0_8px_32px_rgba(0,0,0,0.4)]">
                    {toast.text}
                </div>
            )}
        </div>
    );
}
