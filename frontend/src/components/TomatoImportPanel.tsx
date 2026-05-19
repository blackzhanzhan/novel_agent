import React, { useEffect, useMemo, useState } from 'react';
import { ApiError } from '../api/client';
import {
    confirmTomatoImport,
    previewTomatoImport,
    TomatoImportPreview,
} from '../api/tomatoImport';

interface TomatoImportPanelProps {
    isOpen: boolean;
    currentBookId: string;
    onClose: () => void;
    onImported: (payload: { bookId: string; firstFile: string | null; bookName: string; commitId: string }) => void;
}

function issueTone(severity: string): string {
    return severity === 'block'
        ? 'border-[#7f3434] bg-[#2a1114] text-[#ffd7d7]'
        : 'border-[#755b26] bg-[#241b0c] text-[#ffe2a6]';
}

export const TomatoImportPanel: React.FC<TomatoImportPanelProps> = ({
    isOpen,
    currentBookId,
    onClose,
    onImported,
}) => {
    const [sourceDir, setSourceDir] = useState('');
    const [allowedRoot, setAllowedRoot] = useState('');
    const [bookId, setBookId] = useState('');
    const [bookName, setBookName] = useState('');
    const [overwrite, setOverwrite] = useState(false);
    const [force, setForce] = useState(false);
    const [preview, setPreview] = useState<TomatoImportPreview | null>(null);
    const [pending, setPending] = useState<'preview' | 'confirm' | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (isOpen) {
            setSourceDir('');
            setAllowedRoot('');
            setBookId('');
            setBookName('');
            setOverwrite(false);
            setForce(false);
            setPreview(null);
            setPending(null);
            setError(null);
        }
    }, [isOpen]);

    const quality = preview?.quality;
    const canConfirm = Boolean(preview && (quality?.can_confirm || force));
    const totalChars = preview?.report.total_non_whitespace_chars ?? 0;
    const firstFile = useMemo(() => preview?.chapters[0]?.target_file ? `chapters/${preview.chapters[0].target_file}` : null, [preview]);

    if (!isOpen) return null;

    const payload = () => ({
        source_dir: sourceDir.trim(),
        ...(allowedRoot.trim() ? { allowed_root: allowedRoot.trim() } : {}),
        ...(bookId.trim() ? { book_id: bookId.trim() } : {}),
        ...(bookName.trim() ? { book_name: bookName.trim() } : {}),
        overwrite,
        force,
    });

    const handlePreview = async () => {
        setError(null);
        setPreview(null);
        setPending('preview');
        try {
            const result = await previewTomatoImport(payload());
            setPreview(result);
            if (!bookName.trim()) setBookName(result.book_name);
        } catch (err) {
            setError(err instanceof ApiError ? err.message : '番茄导入预览失败');
        } finally {
            setPending(null);
        }
    };

    const handleConfirm = async () => {
        setError(null);
        setPending('confirm');
        try {
            const result = await confirmTomatoImport(payload());
            onImported({
                bookId: result.book_id,
                firstFile: result.chapters[0]?.target_file ? `chapters/${result.chapters[0].target_file}` : firstFile,
                bookName: result.book_name,
                commitId: result.commit_id,
            });
            onClose();
        } catch (err) {
            if (err instanceof ApiError) {
                const blockedPreview = err.data?.preview as TomatoImportPreview | undefined;
                if (blockedPreview) setPreview(blockedPreview);
                setError(err.message);
            } else {
                setError('番茄导入确认失败');
            }
        } finally {
            setPending(null);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/58 px-4 py-6 backdrop-blur-sm">
            <div role="dialog" aria-modal="true" className="flex max-h-full w-full max-w-5xl flex-col overflow-hidden rounded-[16px] border border-[rgba(255,255,255,0.08)] bg-[#111318] shadow-[0_24px_80px_rgba(0,0,0,0.5)]">
                <div className="flex items-start justify-between gap-4 border-b border-[rgba(255,255,255,0.06)] px-5 py-4">
                    <div className="min-w-0">
                        <div className="text-[11px] font-mono tracking-[0.16em] text-[var(--color-dark-text-faint)]">BOOK IMPORT</div>
                        <h2 className="mt-1 text-lg font-semibold text-[var(--color-dark-text-main)]">番茄小说导入</h2>
                        <p className="mt-1 text-xs leading-5 text-[var(--color-dark-text-muted)]">
                            从 Tomato-Novel-Downloader 的 bulk_files 目录预览章节，确认后写入 storage 下的章节 Markdown。
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="rounded-[10px] border border-[rgba(255,255,255,0.06)] px-3 py-2 text-xs text-[var(--color-dark-text-muted)] hover:text-[var(--color-dark-text-main)]"
                    >
                        关闭
                    </button>
                </div>

                <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(280px,360px)_1fr]">
                    <div className="space-y-4 overflow-y-auto border-b border-[rgba(255,255,255,0.06)] p-5 lg:border-b-0 lg:border-r">
                        <label className="block">
                            <span className="text-[11px] font-medium text-[var(--color-dark-text-muted)]">导出目录</span>
                            <input
                                value={sourceDir}
                                onChange={(event) => setSourceDir(event.target.value)}
                                placeholder="C:\\NovelDownloads\\某本书\\bulk_files"
                                className="mt-2 w-full rounded-[10px] border border-[rgba(255,255,255,0.07)] bg-[#171a20] px-3 py-2 text-sm text-[var(--color-dark-text-main)] outline-none focus:border-[rgba(115,134,255,0.55)]"
                            />
                        </label>
                        <label className="block">
                            <span className="text-[11px] font-medium text-[var(--color-dark-text-muted)]">允许根目录</span>
                            <input
                                value={allowedRoot}
                                onChange={(event) => setAllowedRoot(event.target.value)}
                                placeholder="可留空，或填 TOMATO_LIBRARY_ROOT"
                                className="mt-2 w-full rounded-[10px] border border-[rgba(255,255,255,0.07)] bg-[#171a20] px-3 py-2 text-sm text-[var(--color-dark-text-main)] outline-none focus:border-[rgba(115,134,255,0.55)]"
                            />
                        </label>
                        <div className="grid grid-cols-2 gap-3">
                            <label className="block">
                                <span className="text-[11px] font-medium text-[var(--color-dark-text-muted)]">book_id</span>
                                <input
                                    value={bookId}
                                    onChange={(event) => setBookId(event.target.value)}
                                    placeholder={currentBookId ? `留空按书名创建；当前 ${currentBookId}` : '留空按书名创建'}
                                    className="mt-2 w-full rounded-[10px] border border-[rgba(255,255,255,0.07)] bg-[#171a20] px-3 py-2 text-sm text-[var(--color-dark-text-main)] outline-none focus:border-[rgba(115,134,255,0.55)]"
                                />
                            </label>
                            <label className="block">
                                <span className="text-[11px] font-medium text-[var(--color-dark-text-muted)]">书名</span>
                                <input
                                    value={bookName}
                                    onChange={(event) => setBookName(event.target.value)}
                                    placeholder="可由元数据补齐"
                                    className="mt-2 w-full rounded-[10px] border border-[rgba(255,255,255,0.07)] bg-[#171a20] px-3 py-2 text-sm text-[var(--color-dark-text-main)] outline-none focus:border-[rgba(115,134,255,0.55)]"
                                />
                            </label>
                        </div>
                        <div className="space-y-2 rounded-[12px] border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.015)] p-3">
                            <label className="flex items-center gap-2 text-xs text-[var(--color-dark-text-muted)]">
                                <input type="checkbox" checked={overwrite} onChange={(event) => setOverwrite(event.target.checked)} />
                                覆盖同名章节
                            </label>
                            <label className="flex items-center gap-2 text-xs text-[var(--color-dark-text-muted)]">
                                <input type="checkbox" checked={force} onChange={(event) => setForce(event.target.checked)} />
                                强制越过质量阻断
                            </label>
                        </div>
                        <div className="flex gap-2">
                            <button
                                type="button"
                                disabled={!sourceDir.trim() || Boolean(pending)}
                                onClick={handlePreview}
                                className="flex-1 rounded-[10px] border border-[rgba(115,134,255,0.45)] bg-[rgba(115,134,255,0.14)] px-3 py-2 text-sm font-semibold text-[#eef1ff] disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                {pending === 'preview' ? '预览中…' : '预览'}
                            </button>
                            <button
                                type="button"
                                disabled={!canConfirm || (!bookId.trim() && !bookName.trim()) || Boolean(pending)}
                                onClick={handleConfirm}
                                className="flex-1 rounded-[10px] border border-[rgba(71,197,129,0.42)] bg-[rgba(71,197,129,0.13)] px-3 py-2 text-sm font-semibold text-[#d9ffe9] disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                {pending === 'confirm' ? '写入中…' : '确认写入'}
                            </button>
                        </div>
                        {error && (
                            <div className="rounded-[10px] border border-[#7f3434] bg-[#2a1114] px-3 py-2 text-xs leading-5 text-[#ffd7d7]">
                                {error}
                            </div>
                        )}
                    </div>

                    <div className="min-h-0 overflow-y-auto p-5">
                        {!preview ? (
                            <div className="flex h-full min-h-[360px] items-center justify-center text-sm text-[var(--color-dark-text-faint)]">
                                先选择番茄导出目录并预览，确认章节数量、质量门槛和目标文件名。
                            </div>
                        ) : (
                            <div className="space-y-5">
                                <div className="grid grid-cols-4 gap-3">
                                    <div className="rounded-[12px] border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.015)] p-3">
                                        <div className="text-[10px] text-[var(--color-dark-text-faint)]">书名</div>
                                        <div className="mt-1 truncate text-sm font-semibold">{preview.book_name}</div>
                                    </div>
                                    <div className="rounded-[12px] border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.015)] p-3">
                                        <div className="text-[10px] text-[var(--color-dark-text-faint)]">章节</div>
                                        <div className="mt-1 text-sm font-semibold">{preview.report.chapter_count}</div>
                                    </div>
                                    <div className="rounded-[12px] border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.015)] p-3">
                                        <div className="text-[10px] text-[var(--color-dark-text-faint)]">正文字符</div>
                                        <div className="mt-1 text-sm font-semibold">{totalChars.toLocaleString()}</div>
                                    </div>
                                    <div className="rounded-[12px] border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.015)] p-3">
                                        <div className="text-[10px] text-[var(--color-dark-text-faint)]">质量</div>
                                        <div className="mt-1 text-sm font-semibold">{quality?.risk_level || 'unknown'}</div>
                                    </div>
                                </div>

                                {quality && quality.issues.length > 0 && (
                                    <div className="space-y-2">
                                        <div className="text-[11px] font-medium text-[var(--color-dark-text-muted)]">质量门槛</div>
                                        {quality.issues.slice(0, 8).map((issue, index) => (
                                            <div key={`${issue.code}_${index}`} className={`rounded-[10px] border px-3 py-2 text-xs leading-5 ${issueTone(issue.severity)}`}>
                                                <div className="font-mono text-[10px] opacity-80">{issue.severity.toUpperCase()} · {issue.code}</div>
                                                <div className="mt-1">{issue.chapter ? `${issue.chapter}：` : ''}{issue.message}</div>
                                            </div>
                                        ))}
                                    </div>
                                )}

                                <div>
                                    <div className="mb-2 text-[11px] font-medium text-[var(--color-dark-text-muted)]">章节预览</div>
                                    <div className="max-h-[420px] overflow-y-auto rounded-[12px] border border-[rgba(255,255,255,0.06)]">
                                        {preview.chapters.slice(0, 80).map((chapter) => (
                                            <div key={chapter.target_file} className="grid grid-cols-[64px_1fr_110px_110px] gap-3 border-b border-[rgba(255,255,255,0.045)] px-3 py-2 text-xs last:border-b-0">
                                                <span className="font-mono text-[var(--color-dark-text-faint)]">{String(chapter.index).padStart(4, '0')}</span>
                                                <span className="min-w-0 truncate text-[var(--color-dark-text-main)]">{chapter.title}</span>
                                                <span className="text-right text-[var(--color-dark-text-muted)]">{chapter.non_whitespace_chars} 字</span>
                                                <span className="truncate text-right font-mono text-[var(--color-dark-text-faint)]">{chapter.target_file}</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};
