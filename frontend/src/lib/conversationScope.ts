import { AgentKey, FileType } from '../types/store';

const OUTLINE_WORKSPACE_FILES = new Set([
    'brainstorm.md',
    'master_outline.md',
    'arc_outline.md',
    'chapter_outline.md',
]);

const STYLE_WORKSPACE_FILES = new Set([
    'style_guide.md',
    'style_fingerprint.md',
    'style_review.md',
    'style_constraints_for_continuation.md',
]);

const WORLD_WORKSPACE_FILES = new Set([
    'world_model.md',
    'status_card.md',
    'domain_rules.md',
]);

function normalizeFileName(fileName?: string | null): string {
    return String(fileName || '').replace(/\\/g, '/').trim().toLowerCase();
}

export function conversationScopeKey(
    fileName?: string | null,
    fileType?: FileType,
    _agent?: AgentKey,
): string {
    const normalized = normalizeFileName(fileName);
    if (fileType === 'outline' || OUTLINE_WORKSPACE_FILES.has(normalized)) {
        return 'workspace:outline';
    }
    if (fileType === 'style' || STYLE_WORKSPACE_FILES.has(normalized)) {
        return 'workspace:style';
    }
    if (WORLD_WORKSPACE_FILES.has(normalized)) {
        return 'workspace:world';
    }
    return normalized || 'workspace:unscoped';
}

export function isSameConversationScope(
    leftFileName: string | null | undefined,
    leftFileType: FileType | undefined,
    rightFileName: string | null | undefined,
    rightFileType: FileType | undefined,
    agent?: AgentKey,
): boolean {
    return conversationScopeKey(leftFileName, leftFileType, agent)
        === conversationScopeKey(rightFileName, rightFileType, agent);
}
