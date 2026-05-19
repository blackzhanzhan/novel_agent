import { ApiError } from '../api/client';
import type { RepoIntegrity } from '../types/store';
import { getUiCopy } from '../i18n/ui';

export function isTargetPathForbidden(code: string | null | undefined, message: string | null | undefined): boolean {
    const signature = `${code || ''} ${message || ''}`.toUpperCase();
    return signature.includes('TARGET_PATH_FORBIDDEN');
}

export function getErrorMessage(err: unknown, fallback: string): string {
    if (err instanceof ApiError) return err.message;
    return fallback;
}

export function isLayoutRepairRequired(err: unknown): err is ApiError {
    return err instanceof ApiError && (err.code === 'LAYOUT_REPAIR_REQUIRED' || err.code === 'BOOK_NOT_FOUND');
}

export function extractIntegrityFromError(err: unknown): RepoIntegrity | null {
    if (!(err instanceof ApiError)) return null;
    const integrity = err.data?.integrity;
    if (!integrity || typeof integrity !== 'object') return null;
    return {
        bookId: typeof integrity.book_id === 'string' ? integrity.book_id : '',
        exists: Boolean(integrity.exists),
        repoExists: Boolean(integrity.repo_exists),
        headExists: Boolean(integrity.head_exists),
        headCommit: typeof integrity.head_commit === 'string' ? integrity.head_commit : null,
        missingCoreFiles: Array.isArray(integrity.missing_core_files) ? integrity.missing_core_files : [],
        missingDirectories: Array.isArray(integrity.missing_directories) ? integrity.missing_directories : [],
        untrackedLayoutFiles: Array.isArray(integrity.untracked_layout_files) ? integrity.untracked_layout_files : [],
        problemCodes: Array.isArray(integrity.problem_codes) ? integrity.problem_codes : [],
        needsRepair: Boolean(integrity.needs_repair),
    };
}

export function extractReqIdFromErrorMessage(message: string): string | null {
    const match = message.match(/\breq_id:\s*([A-Za-z0-9_-]+)/i);
    return match ? match[1] : null;
}

export function formatVisibleDeductionError(code: string, message: string): string {
    if (/insufficient balance/i.test(message)) {
        return '模型账户余额不足，Dify 已终止本次推演。请补充模型余额或切换可用模型后重试。';
    }
    if (code === 'DIFY_WORKFLOW_FAILED') {
        return `Dify workflow 失败：${message}`;
    }
    return message;
}

export function formatSuppressedBackendErrorTitle(code: string, copy: ReturnType<typeof getUiCopy>): string {
    if (code === 'JSON_PAYLOAD_INVALID') return copy.debug.hiddenPayloadTitle;
    return code;
}
