import { fetchApi } from './client';

export type RuntimeConfigGroup = 'dify_service' | 'dify_agents' | 'model_provider' | string;

export interface RuntimeConfigItem {
    key: string;
    group: RuntimeConfigGroup;
    label: string;
    secret: boolean;
    configured: boolean;
    source: 'local_env' | 'process_env' | 'default' | 'missing' | string;
    source_key: string;
    value?: string;
    masked_value?: string;
    suffix?: string;
}

export interface RuntimeConfigGroupSummary {
    group: RuntimeConfigGroup;
    configured: number;
    total: number;
    missing_keys: string[];
}

export interface RuntimeConfigResponse {
    status: 'success';
    env_file_exists: boolean;
    items: RuntimeConfigItem[];
    config: Record<string, RuntimeConfigItem>;
    groups: RuntimeConfigGroupSummary[];
    saved_keys?: string[];
}

export interface RuntimeConfigCheckResponse {
    status: 'success';
    ready: boolean;
    missing_required_keys: string[];
    groups: RuntimeConfigGroupSummary[];
}

export async function fetchRuntimeConfig(): Promise<RuntimeConfigResponse> {
    return fetchApi<RuntimeConfigResponse>('/api/runtime/config');
}

export async function saveRuntimeConfig(values: Record<string, string>): Promise<RuntimeConfigResponse> {
    return fetchApi<RuntimeConfigResponse>('/api/runtime/config', {
        method: 'POST',
        body: JSON.stringify({ values }),
    });
}

export async function checkRuntimeConfig(): Promise<RuntimeConfigCheckResponse> {
    return fetchApi<RuntimeConfigCheckResponse>('/api/runtime/config/check');
}
