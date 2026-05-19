import { ApiError } from './client';

export interface SseEventPacket {
    event: string;
    data: any;
    rawData: string;
    id?: string;
}

interface StreamSseOptions {
    endpoint: string;
    payload: unknown;
    signal?: AbortSignal;
    onEvent: (packet: SseEventPacket) => void;
}

const BASE_URL = '';
const STREAM_TIMEOUT_MS = Number(import.meta.env.VITE_DEDUCTION_TIMEOUT_MS || 600000);

function parseSsePacket(lines: string[]): SseEventPacket | null {
    if (!lines.length) return null;

    let event = 'message';
    let id: string | undefined;
    const dataParts: string[] = [];

    for (const line of lines) {
        if (!line || line.startsWith(':')) continue;
        const separatorIndex = line.indexOf(':');
        const field = separatorIndex >= 0 ? line.slice(0, separatorIndex) : line;
        let value = separatorIndex >= 0 ? line.slice(separatorIndex + 1) : '';
        if (value.startsWith(' ')) value = value.slice(1);

        if (field === 'event') {
            event = value || 'message';
        } else if (field === 'id') {
            id = value;
        } else if (field === 'data') {
            dataParts.push(value);
        }
    }

    const rawData = dataParts.join('\n');
    if (!rawData && event === 'message') return null;

    let data: any = {};
    if (rawData === '[DONE]') {
        data = { done: true };
    } else if (rawData) {
        try {
            data = JSON.parse(rawData);
        } catch {
            data = { raw: rawData };
        }
    }

    return { event, data, rawData, id };
}

export async function streamSseJson(options: StreamSseOptions): Promise<void> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), STREAM_TIMEOUT_MS);
    const mergedSignal = controller.signal;

    if (options.signal) {
        if (options.signal.aborted) {
            controller.abort();
        } else {
            options.signal.addEventListener('abort', () => controller.abort(), { once: true });
        }
    }

    try {
        const response = await fetch(`${BASE_URL}${options.endpoint}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream',
            },
            body: JSON.stringify(options.payload),
            signal: mergedSignal,
        });

        if (!response.ok) {
            const fallbackText = await response.text().catch(() => '');
            let parsed: any = {};
            try {
                parsed = fallbackText ? JSON.parse(fallbackText) : {};
            } catch {
                parsed = {};
            }
            throw new ApiError(
                response.status,
                parsed.code || 'HTTP_ERROR',
                parsed.message || fallbackText || `HTTP ${response.status}`,
                parsed,
            );
        }

        if (!response.body) {
            throw new ApiError(502, 'EMPTY_STREAM_BODY', 'SSE response body is empty');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        let pendingLines: string[] = [];

        const flushPacket = () => {
            const packet = parseSsePacket(pendingLines);
            pendingLines = [];
            if (packet) options.onEvent(packet);
        };

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            let lineBreak = buffer.indexOf('\n');
            while (lineBreak >= 0) {
                let line = buffer.slice(0, lineBreak);
                buffer = buffer.slice(lineBreak + 1);
                if (line.endsWith('\r')) line = line.slice(0, -1);

                if (line === '') {
                    flushPacket();
                } else {
                    pendingLines.push(line);
                }
                lineBreak = buffer.indexOf('\n');
            }
        }

        buffer += decoder.decode();
        if (buffer.length) {
            pendingLines.push(buffer.replace(/\r$/, ''));
        }
        flushPacket();
    } catch (err: any) {
        if (err?.name === 'AbortError') {
            if (options.signal?.aborted) {
                throw new ApiError(499, 'REQUEST_ABORTED', 'SSE request aborted by user');
            }
            throw new ApiError(504, 'REQUEST_TIMEOUT', `SSE request timeout after ${STREAM_TIMEOUT_MS}ms`);
        }
        throw err;
    } finally {
        clearTimeout(timeoutId);
    }
}
