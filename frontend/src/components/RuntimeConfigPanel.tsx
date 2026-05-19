import React, { useEffect, useMemo, useState } from 'react';
import { ApiError } from '../api/client';
import {
    fetchRuntimeConfig,
    saveRuntimeConfig,
    type RuntimeConfigItem,
    type RuntimeConfigResponse,
} from '../api/runtimeConfig';

interface RuntimeConfigPanelProps {
    isOpen: boolean;
    onClose: () => void;
    onSaved?: () => void;
}

const GROUP_LABELS: Record<string, string> = {
    dify_service: 'Dify 服务',
    dify_agents: 'Dify Agent 密钥',
    model_provider: '本地模型供应商',
};

const GROUP_HELP: Record<string, string> = {
    dify_service: '配置 Flask 调用 Dify Service API 的地址和超时时间。',
    dify_agents: '每个 Agent 使用独立 App API key。保存后后端会热刷新，下一次调用立即生效。',
    model_provider: '供摘要、世界观、文风等本地批处理管线使用。可选择 DeepSeek 或任意 OpenAI-compatible 接口。',
};

const FIELD_HELP: Record<string, string> = {
    MODEL_PROVIDER: 'deepseek 使用旧 DeepSeek 配置；openai_compatible 使用下面的兼容接口配置。',
    OPENAI_COMPATIBLE_BASE_URL: '例如 https://api.openai.com/v1、OpenRouter/SiliconFlow/本地 vLLM 的 /v1 地址。',
    OPENAI_COMPATIBLE_MODEL: '第三方兼容接口里的模型名，例如 gpt-4.1-mini、deepseek-chat、qwen-plus 等。',
    OPENAI_COMPATIBLE_API_KEY: '第三方兼容接口的 API key。不会进入聊天记录或书库文件。',
    SUMMARY_ARCHIVE_MODEL: '可选。只覆盖导入摘要管线使用的模型，留空则使用默认批处理模型。',
};

function groupLabel(group: string): string {
    return GROUP_LABELS[group] || group;
}

function sourceLabel(item: RuntimeConfigItem): string {
    if (item.source === 'local_env') return item.source_key === item.key ? '本机文件' : `本机文件：${item.source_key}`;
    if (item.source === 'process_env') return item.source_key === item.key ? '进程环境' : `进程环境：${item.source_key}`;
    if (item.source === 'default') return '默认值';
    return '未配置';
}

function displayValue(item: RuntimeConfigItem): string {
    if (item.secret) return item.masked_value || '';
    return item.value || '';
}

function emptyDraft(config: RuntimeConfigResponse | null): Record<string, string> {
    if (!config) return {};
    return Object.fromEntries(config.items.map((item) => [item.key, '']));
}

function hasDraftValue(draft: Record<string, string>): boolean {
    return Object.values(draft).some((value) => value.trim().length > 0);
}

function fieldPlaceholder(item: RuntimeConfigItem): string {
    if (item.key === 'MODEL_PROVIDER') return 'deepseek 或 openai_compatible';
    if (item.secret) return item.configured ? `${displayValue(item)}，留空则不修改` : '粘贴 API key';
    return displayValue(item) || '留空则不修改';
}

function fieldInputType(item: RuntimeConfigItem): string {
    return item.secret ? 'password' : 'text';
}

export const RuntimeConfigPanel: React.FC<RuntimeConfigPanelProps> = ({
    isOpen,
    onClose,
    onSaved,
}) => {
    const [config, setConfig] = useState<RuntimeConfigResponse | null>(null);
    const [draft, setDraft] = useState<Record<string, string>>({});
    const [pending, setPending] = useState<'load' | 'save' | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [savedKeys, setSavedKeys] = useState<string[]>([]);

    const groupedItems = useMemo(() => {
        const groups = new Map<string, RuntimeConfigItem[]>();
        for (const item of config?.items || []) {
            const rows = groups.get(item.group) || [];
            rows.push(item);
            groups.set(item.group, rows);
        }
        return Array.from(groups.entries());
    }, [config?.items]);

    const missingSecretCount = useMemo(
        () => (config?.items || []).filter((item) => item.secret && !item.configured).length,
        [config?.items],
    );

    useEffect(() => {
        if (!isOpen) return;
        let cancelled = false;
        setPending('load');
        setError(null);
        setSavedKeys([]);
        fetchRuntimeConfig()
            .then((payload) => {
                if (cancelled) return;
                setConfig(payload);
                setDraft(emptyDraft(payload));
            })
            .catch((err) => {
                if (cancelled) return;
                setError(err instanceof ApiError ? err.message : '读取本机配置失败');
            })
            .finally(() => {
                if (!cancelled) setPending(null);
            });
        return () => {
            cancelled = true;
        };
    }, [isOpen]);

    if (!isOpen) return null;

    const updateDraft = (key: string, value: string) => {
        setDraft((current) => ({ ...current, [key]: value }));
    };

    const reload = async () => {
        setPending('load');
        setError(null);
        try {
            const payload = await fetchRuntimeConfig();
            setConfig(payload);
            setDraft(emptyDraft(payload));
        } catch (err) {
            setError(err instanceof ApiError ? err.message : '读取本机配置失败');
        } finally {
            setPending(null);
        }
    };

    const handleSave = async () => {
        const values = Object.fromEntries(
            Object.entries(draft)
                .map(([key, value]) => [key, value.trim()])
                .filter(([, value]) => value.length > 0),
        );
        if (!Object.keys(values).length) return;
        setPending('save');
        setError(null);
        setSavedKeys([]);
        try {
            const payload = await saveRuntimeConfig(values);
            setConfig(payload);
            setDraft(emptyDraft(payload));
            setSavedKeys(payload.saved_keys || Object.keys(values));
            onSaved?.();
        } catch (err) {
            if (err instanceof ApiError && Array.isArray(err.data?.errors)) {
                setError(
                    err.data.errors
                        .map((item: { key?: string; message?: string }) => `${item.key || '配置'}：${item.message || '无效'}`)
                        .join('；'),
                );
            } else {
                setError(err instanceof ApiError ? err.message : '保存本机配置失败');
            }
        } finally {
            setPending(null);
        }
    };

    return (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/58 px-4 py-6 backdrop-blur-sm">
            <div role="dialog" aria-modal="true" className="flex max-h-full w-full max-w-5xl flex-col overflow-hidden rounded-[14px] border border-[rgba(255,255,255,0.08)] bg-[#101319] shadow-[0_24px_80px_rgba(0,0,0,0.52)]">
                <div className="flex items-start justify-between gap-4 border-b border-[rgba(255,255,255,0.06)] px-5 py-4">
                    <div className="min-w-0">
                        <div className="text-[11px] font-mono text-[var(--color-dark-text-faint)]">LOCAL RUNTIME CONFIG</div>
                        <h2 className="mt-1 text-lg font-semibold text-[var(--color-dark-text-main)]">本机配置中心</h2>
                        <p className="mt-1 max-w-3xl text-xs leading-5 text-[var(--color-dark-text-muted)]">
                            这里配置本机 Dify 与模型 API。密钥只会发送到后端写入本地 .env.local，页面只显示脱敏状态。
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="rounded-[8px] border border-[rgba(255,255,255,0.08)] px-3 py-2 text-xs text-[var(--color-dark-text-muted)] hover:text-[var(--color-dark-text-main)]"
                    >
                        关闭
                    </button>
                </div>

                <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[280px_1fr]">
                    <aside className="space-y-3 border-b border-[rgba(255,255,255,0.06)] p-5 lg:border-b-0 lg:border-r">
                        <div className="rounded-[12px] border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.025)] p-3">
                            <div className="text-[10px] text-[var(--color-dark-text-faint)]">配置文件</div>
                            <div className="mt-1 text-sm font-semibold text-[var(--color-dark-text-main)]">
                                {config?.env_file_exists ? '已创建' : '尚未创建'}
                            </div>
                        </div>
                        <div className="rounded-[12px] border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.025)] p-3">
                            <div className="text-[10px] text-[var(--color-dark-text-faint)]">密钥缺口</div>
                            <div className="mt-1 text-sm font-semibold text-[var(--color-dark-text-main)]">
                                {pending === 'load' ? '读取中' : `${missingSecretCount} 项`}
                            </div>
                        </div>
                        <div className="rounded-[12px] border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.015)] p-3 text-xs leading-5 text-[var(--color-dark-text-muted)]">
                            保存后后端会更新进程环境，并原地刷新 Dify Agent registry。Dify 数据库、工作流、prompt 不会在这里被修改。
                        </div>
                        {savedKeys.length > 0 && (
                            <div className="rounded-[12px] border border-[var(--tone-success-border)] bg-[var(--tone-success-bg)] p-3 text-xs leading-5 text-[var(--tone-success-text)]">
                                已保存并热刷新：{savedKeys.join('、')}
                            </div>
                        )}
                        {error && (
                            <div className="rounded-[12px] border border-[var(--tone-danger-border)] bg-[var(--tone-danger-bg)] p-3 text-xs leading-5 text-[var(--tone-danger-text)]">
                                {error}
                            </div>
                        )}
                        <div className="flex gap-2">
                            <button
                                type="button"
                                onClick={() => void reload()}
                                disabled={Boolean(pending)}
                                className="flex-1 rounded-[8px] border border-[rgba(255,255,255,0.1)] px-3 py-2 text-xs font-semibold text-[var(--color-dark-text-muted)] disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                {pending === 'load' ? '刷新中' : '刷新状态'}
                            </button>
                            <button
                                type="button"
                                onClick={() => void handleSave()}
                                disabled={Boolean(pending) || !hasDraftValue(draft)}
                                className="flex-1 rounded-[8px] border border-[rgba(95,141,255,0.45)] bg-[rgba(95,141,255,0.14)] px-3 py-2 text-xs font-semibold text-[#eef1ff] disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                {pending === 'save' ? '保存中' : '保存'}
                            </button>
                        </div>
                    </aside>

                    <main className="app-scrollbar min-h-0 overflow-y-auto p-5">
                        {pending === 'load' && !config ? (
                            <div className="flex min-h-[360px] items-center justify-center text-sm text-[var(--color-dark-text-faint)]">
                                正在读取本机配置状态
                            </div>
                        ) : (
                            <div className="space-y-5">
                                {groupedItems.map(([group, items]) => (
                                    <section key={group} className="rounded-[12px] border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.015)]">
                                        <div className="border-b border-[rgba(255,255,255,0.05)] px-4 py-3">
                                            <div className="text-sm font-semibold text-[var(--color-dark-text-main)]">{groupLabel(group)}</div>
                                            <div className="mt-1 text-xs leading-5 text-[var(--color-dark-text-muted)]">{GROUP_HELP[group] || '本机运行时配置。'}</div>
                                        </div>
                                        <div className="divide-y divide-[rgba(255,255,255,0.045)]">
                                            {items.map((item) => (
                                                <div key={item.key} className="grid gap-3 px-4 py-3 lg:grid-cols-[220px_1fr_160px]">
                                                    <div className="min-w-0">
                                                        <div className="truncate text-xs font-semibold text-[var(--color-dark-text-main)]">{item.label}</div>
                                                        <div className="mt-1 font-mono text-[10px] text-[var(--color-dark-text-faint)]">{item.key}</div>
                                                    </div>
                                                    <div>
                                                        <input
                                                            type={fieldInputType(item)}
                                                            value={draft[item.key] || ''}
                                                            onChange={(event) => updateDraft(item.key, event.target.value)}
                                                            placeholder={fieldPlaceholder(item)}
                                                            autoComplete="off"
                                                            spellCheck={false}
                                                            className="w-full rounded-[8px] border border-[rgba(255,255,255,0.08)] bg-[#171b22] px-3 py-2 font-mono text-xs text-[var(--color-dark-text-main)] outline-none focus:border-[rgba(115,134,255,0.58)]"
                                                        />
                                                        <div className="mt-1 text-[10px] text-[var(--color-dark-text-faint)]">
                                                            当前：{item.configured ? displayValue(item) || '已配置' : '未配置'} / 来源：{sourceLabel(item)}
                                                        </div>
                                                        {FIELD_HELP[item.key] && (
                                                            <div className="mt-1 text-[10px] leading-4 text-[var(--color-dark-text-muted)]">
                                                                {FIELD_HELP[item.key]}
                                                            </div>
                                                        )}
                                                    </div>
                                                    <div className="flex items-start justify-end">
                                                        <span className={`rounded-full border px-2 py-[3px] text-[10px] ${
                                                            item.configured
                                                                ? 'border-[var(--tone-success-border)] bg-[var(--tone-success-bg)] text-[var(--tone-success-text)]'
                                                                : 'border-[var(--tone-warning-border)] bg-[var(--tone-warning-bg)] text-[var(--tone-warning-text)]'
                                                        }`}>
                                                            {item.configured ? '已配置' : '缺失'}
                                                        </span>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </section>
                                ))}
                            </div>
                        )}
                    </main>
                </div>
            </div>
        </div>
    );
};
