import { FileType } from '../types/store';

export function resolveFileType(filePath: string): FileType {
    const normalized = String(filePath || '').replace(/\\/g, '/').trim().toLowerCase();
    if (normalized === 'world_model.md' || normalized === 'status_card.md') {
        return 'world_core';
    }
    if (normalized === 'summary.md') {
        return 'summary';
    }
    if (
        normalized === 'brainstorm.md'
        || normalized === 'master_outline.md'
        || normalized === 'arc_outline.md'
        || normalized === 'chapter_outline.md'
    ) {
        return 'outline';
    }
    if (
        normalized === 'style_guide.md'
        || normalized === 'style_fingerprint.md'
        || normalized === 'style_review.md'
        || normalized === 'style_constraints_for_continuation.md'
    ) {
        return 'style';
    }
    if (normalized === 'error_archive.md') {
        return 'error_archive';
    }
    if (normalized === 'chapter_draft.md' || normalized.startsWith('chapters/')) {
        return 'chapter';
    }
    return 'world_core';
}
