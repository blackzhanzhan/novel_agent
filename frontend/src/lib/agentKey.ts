import { AgentKey, FileType } from '../types/store';

export function resolveAgentKey(fileName: string, fileType: FileType): AgentKey {
    const normalized = String(fileName || '').replace(/\\/g, '/').trim().toLowerCase();
    if (normalized === 'chapter_draft.md') {
        return 'continuation_agent';
    }
    if (normalized === 'style_guide.md' || fileType === 'style') {
        return 'style_agent';
    }
    if (
        normalized === 'brainstorm.md'
        || normalized === 'master_outline.md'
        || normalized === 'arc_outline.md'
        || normalized === 'chapter_outline.md'
        || fileType === 'outline'
    ) {
        return 'outline_agent';
    }
    return 'world_agent';
}
