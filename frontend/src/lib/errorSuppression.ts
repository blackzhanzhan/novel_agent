export const SUPPRESSED_BACKEND_ERROR_CODES = new Set<string>([
    'JSON_PAYLOAD_INVALID',
]);
export const MAX_SUPPRESSED_DEBUG_LOGS = 20;

export interface SuppressedBackendErrorLog {
    id: string;
    ts: number;
    code: string;
    message: string;
    reqId: string | null;
}

export function shouldSuppressBackendError(code: string, message: string): boolean {
    if (SUPPRESSED_BACKEND_ERROR_CODES.has(code)) return true;
    const normalizedMessage = message.toUpperCase();
    if (code === 'STREAM_ERROR' && normalizedMessage.includes('JSON_PAYLOAD_INVALID')) return true;
    return false;
}
